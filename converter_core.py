"""
Image format conversion core (GUI-agnostic).

Converts between common still-image formats (JPEG, PNG, WEBP, TIFF, BMP) and,
when pillow-heif is importable, HEIF/HEIC/HIF as well. EXIF is carried through
where the target format supports it.

Design notes
------------
* HEIF is OPTIONAL. pillow-heif is imported lazily and its absence is non-fatal:
  HEIF_AVAILABLE is False and HEIF extensions are simply unsupported. This is the
  graceful-degradation path for platforms where no pillow-heif wheel exists (e.g.
  some win-arm64 setups). Nothing else in the converter breaks.
* This module is deliberately free of any Qt / GUI imports so it can be unit
  tested headlessly and reused from a CLI later.
"""
import os
import logging

from PIL import Image
import piexif

logger = logging.getLogger(__name__)

# --- optional HEIF support --------------------------------------------------
# Imported lazily and defensively. If the wheel is missing or fails to load its
# native libheif, we carry on without HEIF rather than crashing the whole tool.
HEIF_AVAILABLE = False
HEIF_IMPORT_ERROR = None
try:
    import pillow_heif  # noqa: F401
    pillow_heif.register_heif_opener()
    HEIF_AVAILABLE = True
except Exception as e:  # noqa: BLE001 - any failure means "no HEIF", report why
    HEIF_IMPORT_ERROR = f"{type(e).__name__}: {e}"
    logger.warning("pillow-heif unavailable, HEIF/HEIC/HIF disabled: %s", HEIF_IMPORT_ERROR)


# Map a lower-case extension (no dot) -> Pillow format string.
_EXT_TO_FORMAT = {
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "tif": "TIFF",
    "tiff": "TIFF",
    "bmp": "BMP",
    "heic": "HEIF",
    "heif": "HEIF",
    "hif": "HEIF",  # Canon's HEIF extension
}

# Formats that cannot store an alpha channel; RGBA/LA/P sources are flattened.
_NO_ALPHA_FORMATS = {"JPEG", "BMP"}

# Formats we can WRITE. (Reading HEIF is enabled by register_heif_opener above.)
_WRITABLE_FORMATS = {"JPEG", "PNG", "WEBP", "TIFF", "BMP"}
if HEIF_AVAILABLE:
    _WRITABLE_FORMATS.add("HEIF")


def supported_input_extensions() -> list[str]:
    """Extensions we can OPEN, given current HEIF availability."""
    exts = ["jpg", "jpeg", "png", "webp", "tif", "tiff", "bmp"]
    if HEIF_AVAILABLE:
        exts += ["heic", "heif", "hif"]
    return exts


def supported_output_extensions() -> list[str]:
    """Extensions we can SAVE TO, given current HEIF availability."""
    exts = ["jpg", "jpeg", "png", "webp", "tif", "tiff", "bmp"]
    if HEIF_AVAILABLE:
        exts += ["heif", "heic"]
    return exts


def format_for_extension(ext_or_path: str) -> str | None:
    """Pillow format string for a file extension OR a full path.

    Accepts 'jpg', '.jpg', or '/some/dir/file.JPG' alike.
    """
    # splitext on a bare 'jpg' returns ('jpg', ''); on a path it returns the ext.
    ext = os.path.splitext(ext_or_path)[1] or ext_or_path
    return _EXT_TO_FORMAT.get(ext.lower().lstrip("."))


def _flatten_alpha(img: Image.Image, background=(255, 255, 255)) -> Image.Image:
    """Composite an image with transparency onto a solid background.

    JPEG/BMP cannot store alpha; pasting onto white avoids Pillow either raising
    or silently producing a black background from an unhandled alpha channel.
    """
    if img.mode in ("RGBA", "LA"):
        base = Image.new("RGB", img.size, background)
        # Use the alpha channel as the paste mask.
        base.paste(img, mask=img.split()[-1])
        return base
    if img.mode == "P":
        # Palette image possibly with transparency -> go through RGBA first.
        return _flatten_alpha(img.convert("RGBA"), background)
    return img.convert("RGB")


def convert_image(src_path: str,
                  dst_path: str,
                  quality: int = 95,
                  preserve_exif: bool = True,
                  overwrite: bool = True) -> str:
    """Convert a single image to the format implied by dst_path's extension.

    Args:
        src_path: Source image path.
        dst_path: Destination path. Its extension determines the output format.
        quality: Lossy quality (1-100) for JPEG/WEBP/HEIF. Ignored otherwise.
        preserve_exif: Carry the source EXIF block into the output when both the
                       source provides one and the target format supports it.
        overwrite: If False and dst exists, append " (1)", " (2)", ... instead.

    Returns:
        The path actually written.

    Raises:
        ValueError: unknown/unwritable target format, or HEIF requested without
                    pillow-heif available.
    """
    out_fmt = format_for_extension(dst_path)
    if out_fmt is None:
        raise ValueError(f"Unknown output extension for '{os.path.basename(dst_path)}'")
    if out_fmt not in _WRITABLE_FORMATS:
        if out_fmt == "HEIF":
            raise ValueError("HEIF output requested but pillow-heif is not available.")
        raise ValueError(f"Cannot write format '{out_fmt}'.")

    if not overwrite:
        dst_path = _next_free_path(dst_path)

    os.makedirs(os.path.dirname(os.path.abspath(dst_path)), exist_ok=True)

    with Image.open(src_path) as img:
        img.load()

        # Pull EXIF before any mode conversion (conversion can drop img.info).
        exif_bytes = img.info.get("exif") if preserve_exif else None

        # DPI is metadata only (it sets assumed print size, not pixels), but it
        # must be carried explicitly: it lives in img.info['dpi'], NOT in the EXIF
        # bytes for JFIF-only sources, so copying EXIF alone silently drops it.
        # Normalize to plain floats - TIFF reports dpi as IFDRational (a Fraction
        # subclass), which is NOT an int/float and would otherwise be rejected.
        dpi = _source_dpi(img)

        save_kwargs = {}

        if out_fmt in _NO_ALPHA_FORMATS:
            img = _flatten_alpha(img)
        elif out_fmt in ("WEBP", "HEIF") and img.mode == "P":
            img = img.convert("RGBA")
        elif out_fmt == "PNG" and img.mode not in ("RGB", "RGBA", "L", "LA", "P", "I", "1"):
            img = img.convert("RGBA")

        if out_fmt in ("JPEG", "WEBP", "HEIF"):
            save_kwargs["quality"] = int(quality)
        if out_fmt == "JPEG":
            # subsampling=0 keeps sharp coloured edges; matches the border tool.
            save_kwargs["subsampling"] = 0
        if exif_bytes:
            # Pillow accepts raw EXIF bytes for JPEG/WEBP/TIFF/PNG/HEIF saves.
            save_kwargs["exif"] = exif_bytes

        # Carry DPI where the target format can store it. JPEG/PNG/TIFF/BMP honour
        # the dpi kwarg (JFIF density / pHYs / TIFF resolution / BMP ppm).
        if dpi and out_fmt in ("JPEG", "PNG", "TIFF", "BMP"):
            save_kwargs["dpi"] = dpi

        # WEBP and HEIF have NO native DPI field, so the dpi kwarg is ignored and
        # the output ends up with no resolution metadata - viewers then assume a
        # default (commonly 72). They DO carry EXIF, so we write the DPI into the
        # EXIF resolution tags instead. Done only for these two formats to avoid
        # perturbing the EXIF of the others (which already carry DPI natively).
        if dpi and preserve_exif and out_fmt in ("WEBP", "HEIF"):
            merged = _exif_with_resolution(exif_bytes, dpi)
            if merged is not None:
                save_kwargs["exif"] = merged

        img.save(dst_path, format=out_fmt, **save_kwargs)

    return dst_path


def _source_dpi(img):
    """Best-effort source DPI as a clean (float, float), or None.

    Prefers the native img.info['dpi']. Falls back to the EXIF resolution tags
    (XResolution/YResolution/ResolutionUnit) - important for HEIF/WEBP sources,
    where Pillow doesn't populate info['dpi'] but the resolution may still live
    in EXIF (e.g. a HEIF straight from a phone). Converts cm-based resolution to
    inches so the value is always DPI.
    """
    dpi = _norm_dpi(img.info.get("dpi"))
    if dpi:
        return dpi
    try:
        ex = img.getexif()
        xr, yr, unit = ex.get(282), ex.get(283), ex.get(296)
        if xr is None:
            return None
        x = float(xr)
        y = float(yr) if yr is not None else x
        if unit == 3:           # 3 = centimetres -> convert to per-inch
            x, y = x * 2.54, y * 2.54
        return _norm_dpi((x, y))
    except Exception:  # noqa: BLE001 - resolution is optional, never fatal
        return None


def _norm_dpi(dpi):
    """Coerce a Pillow dpi value to a clean (float, float) tuple, or None.

    Pillow returns dpi as plain floats for most formats but as IFDRational
    (a Fraction subclass) for TIFF. We convert to float so downstream isinstance
    checks and save kwargs behave uniformly, and drop junk values like (0,0)/(1,1)
    that some sources report when no real resolution is set.
    """
    try:
        if not dpi:
            return None
        x, y = float(dpi[0]), float(dpi[1])
    except (TypeError, ValueError, ZeroDivisionError, IndexError):
        return None
    if x > 1 and y > 1:
        return (x, y)
    return None


def _exif_with_resolution(exif_bytes, dpi) -> bytes | None:
    """Return an EXIF byte block with XResolution/YResolution/ResolutionUnit set
    from `dpi`, merged into any existing EXIF.

    Used for WEBP/HEIF output, which have no native DPI field but do carry EXIF.
    Returns None if the EXIF can't be built (caller then leaves EXIF untouched).
    """
    try:
        exif_dict = piexif.load(exif_bytes) if exif_bytes else {
            "0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    except Exception:  # noqa: BLE001 - unparseable donor EXIF -> don't risk it
        return None

    xr, yr = int(round(dpi[0])), int(round(dpi[1]))
    exif_dict.setdefault("0th", {})
    exif_dict["0th"][piexif.ImageIFD.XResolution] = (xr, 1)
    exif_dict["0th"][piexif.ImageIFD.YResolution] = (yr, 1)
    exif_dict["0th"][piexif.ImageIFD.ResolutionUnit] = 2  # 2 = inches

    try:
        return piexif.dump(exif_dict)
    except Exception:  # noqa: BLE001 - e.g. a half-parsed MakerNote; retry clean
        exif_dict.pop("thumbnail", None)
        exif_dict.get("Exif", {}).pop(piexif.ExifIFD.MakerNote, None)
        try:
            return piexif.dump(exif_dict)
        except Exception:  # noqa: BLE001
            return None


def _next_free_path(path: str) -> str:
    """Return path unchanged if free, else append ' (1)', ' (2)', ... ."""
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    n = 1
    while True:
        cand = f"{root} ({n}){ext}"
        if not os.path.exists(cand):
            return cand
        n += 1


def build_output_path(src_path: str, input_root: str, output_root: str, out_ext: str) -> str:
    """Mirror the source's sub-folder structure under output_root and swap the
    extension to out_ext. (Same collision-avoidance philosophy as the border
    tool's resolve_output_path.)"""
    src_dir = os.path.dirname(os.path.abspath(src_path))
    input_root = os.path.abspath(input_root)
    try:
        rel_dir = os.path.relpath(src_dir, input_root)
    except ValueError:
        rel_dir = ""
    if rel_dir == os.curdir or rel_dir.startswith(".."):
        rel_dir = ""
    dest_dir = os.path.join(output_root, rel_dir) if rel_dir else output_root
    base = os.path.splitext(os.path.basename(src_path))[0]
    return os.path.join(dest_dir, f"{base}.{out_ext.lstrip('.')}")
