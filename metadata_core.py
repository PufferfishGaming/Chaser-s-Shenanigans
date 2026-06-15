"""
Metadata baking core (GUI-agnostic).

Copies EXIF from a DONOR image (the "first" image) into a RECIPIENT image (the
"second" image) and writes the result to a new file. The canonical use case:
an export pipeline (Lightroom/Photoshop) stripped or altered the camera EXIF,
and you want to restore it from the original.

Scope / honest limitations (v1)
--------------------------------
* EXIF only. IPTC and XMP are NOT copied. If you need those, this needs a
  different library (e.g. pyexiv2 / exiftool) - flagged deliberately.
* piexif is used for JPEG/TIFF recipients, which lets us surgically edit the
  EXIF (drop GPS, normalize Orientation, rewrite stale dimension tags). For
  other recipient formats we fall back to copying the donor's raw EXIF block
  verbatim via Pillow, which does NOT support those edits - they are silently
  skipped and reported back to the caller.

Why the edit toggles exist
--------------------------
Blindly copying a donor's EXIF onto a different-sized recipient is a known
footgun: the Orientation tag can double-rotate already-correct pixels, the
PixelXDimension / ImageWidth tags become wrong for the recipient, and GPS
travels silently. The toggles below let the caller neutralise each.
"""
import os
import logging
import shutil

from PIL import Image
import piexif

logger = logging.getLogger(__name__)

# Recipient formats for which we can do *surgical* EXIF editing via piexif.
_PIEXIF_FORMATS = {".jpg", ".jpeg", ".tif", ".tiff"}


class BakeResult:
    """Outcome of a bake operation."""
    def __init__(self, out_path: str, edited: bool, notes: list[str]):
        self.out_path = out_path
        self.edited = edited            # True if surgical edits were applied
        self.notes = notes              # human-readable caveats / skips


def _load_donor_exif_dict(donor_path: str):
    """Return a piexif dict for the donor, or None if it has no parseable EXIF."""
    try:
        return piexif.load(donor_path)
    except Exception as e:  # noqa: BLE001
        logger.info("piexif could not parse donor EXIF (%s); will try raw bytes.", e)
        return None


def _donor_raw_exif(donor_path: str) -> bytes | None:
    """Fallback: the donor's raw EXIF block as bytes, via Pillow."""
    try:
        with Image.open(donor_path) as im:
            return im.info.get("exif")
    except Exception:  # noqa: BLE001
        return None


def bake_metadata(donor_path: str,
                  recipient_path: str,
                  out_path: str,
                  drop_gps: bool = False,
                  normalize_orientation: bool = True,
                  rewrite_dimensions: bool = True,
                  overwrite: bool = False) -> BakeResult:
    """Bake the donor's EXIF into the recipient, writing to out_path.

    Args:
        donor_path: Image whose metadata you want to copy FROM.
        recipient_path: Image whose PIXELS you want to keep (copy metadata INTO).
        out_path: Where to write the result.
        drop_gps: Remove the GPS IFD from the baked metadata.
        normalize_orientation: Force Orientation -> 1 (Normal). Prevents the
            donor's orientation double-rotating the recipient's pixels.
        rewrite_dimensions: Update the EXIF pixel-dimension tags to the
            recipient's ACTUAL size, so they don't lie. (Only the EXIF tags;
            the file's real dimensions are always the recipient's.)
        overwrite: If False and out_path exists, append ' (1)', ' (2)', ... .

    Returns:
        BakeResult with the path written, whether surgical edits applied, and
        any caveats.
    """
    notes: list[str] = []
    recipient_ext = os.path.splitext(recipient_path)[1].lower()

    if not overwrite:
        out_path = _next_free_path(out_path)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    surgical = recipient_ext in _PIEXIF_FORMATS
    want_edits = drop_gps or normalize_orientation or rewrite_dimensions

    if surgical:
        exif_dict = _load_donor_exif_dict(donor_path)
        if exif_dict is None:
            raw = _donor_raw_exif(donor_path)
            if raw is None:
                raise ValueError("Donor image has no readable EXIF to copy.")
            return _save_raw(recipient_path, out_path, raw,
                             notes + ["Donor EXIF not piexif-parseable; copied raw, no edits applied."])

        with Image.open(recipient_path) as rim:
            rw, rh = rim.size

        if drop_gps:
            exif_dict["GPS"] = {}
        if normalize_orientation:
            exif_dict.setdefault("0th", {})[piexif.ImageIFD.Orientation] = 1
        if rewrite_dimensions:
            exif_dict.setdefault("Exif", {})[piexif.ExifIFD.PixelXDimension] = rw
            exif_dict["Exif"][piexif.ExifIFD.PixelYDimension] = rh
            # 0th width/length are less universally present but worth keeping honest.
            exif_dict.setdefault("0th", {})[piexif.ImageIFD.ImageWidth] = rw
            exif_dict["0th"][piexif.ImageIFD.ImageLength] = rh

        try:
            exif_bytes = piexif.dump(exif_dict)
        except Exception as e:  # noqa: BLE001
            # Some donor dicts contain values piexif refuses to re-dump (e.g. a
            # MakerNote it half-parsed). Drop the offending thumbnail/maker note
            # and retry once before giving up.
            notes.append(f"piexif.dump issue ({e}); retried without thumbnail/MakerNote.")
            exif_dict.pop("thumbnail", None)
            exif_dict.get("Exif", {}).pop(piexif.ExifIFD.MakerNote, None)
            exif_bytes = piexif.dump(exif_dict)

        with Image.open(recipient_path) as rim:
            save_kwargs = {"exif": exif_bytes}
            fmt = "JPEG" if recipient_ext in (".jpg", ".jpeg") else "TIFF"
            if fmt == "JPEG":
                save_kwargs.update(quality=95, subsampling=0)
                if rim.mode not in ("RGB", "L"):
                    rim = rim.convert("RGB")
            rim.save(out_path, format=fmt, **save_kwargs)
        return BakeResult(out_path, edited=want_edits, notes=notes)

    # Non-piexif recipient: raw copy only, edits not possible.
    raw = _donor_raw_exif(donor_path)
    if raw is None:
        raise ValueError("Donor image has no readable EXIF to copy.")
    if want_edits:
        notes.append(f"Recipient '{recipient_ext}' supports raw EXIF copy only; "
                     "GPS/orientation/dimension edits were skipped.")
    return _save_raw(recipient_path, out_path, raw, notes)


def _save_raw(recipient_path: str, out_path: str, exif_bytes: bytes, notes: list[str]) -> BakeResult:
    """Save the recipient with the donor's raw EXIF block attached, no edits."""
    with Image.open(recipient_path) as rim:
        rim.load()
        fmt = rim.format
        try:
            rim.save(out_path, exif=exif_bytes)
        except (ValueError, OSError):
            # Target format/path mismatch - fall back to explicit format.
            rim.save(out_path, format=fmt, exif=exif_bytes)
    return BakeResult(out_path, edited=False, notes=notes)


def _next_free_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    n = 1
    while True:
        cand = f"{root} ({n}){ext}"
        if not os.path.exists(cand):
            return cand
        n += 1


def describe_exif(path: str, limit: int = 12) -> list[tuple[str, str]]:
    """Return a short list of (tag_name, value) for previewing an image's EXIF.

    Used by the GUI to show 'before/after'. Best-effort and never raises.
    """
    out: list[tuple[str, str]] = []
    try:
        exif_dict = piexif.load(path)
    except Exception:  # noqa: BLE001
        return out
    for ifd in ("0th", "Exif", "GPS"):
        for tag_id, val in exif_dict.get(ifd, {}).items():
            name = piexif.TAGS[ifd].get(tag_id, {}).get("name", str(tag_id))
            if isinstance(val, bytes):
                val = val[:32]  # avoid dumping long binary blobs
            out.append((name, str(val)))
            if len(out) >= limit:
                return out
    return out


# ---------------------------------------------------------------- field editing
# Editable string fields and their 0th-IFD tags. Used for both read and write.
_EDIT_TAGS = {
    "artist": piexif.ImageIFD.Artist,
    "copyright": piexif.ImageIFD.Copyright,
    "description": piexif.ImageIFD.ImageDescription,
}


def read_fields(path: str) -> dict:
    """Current values of the editable string fields (for prefilling the GUI)."""
    out = {k: "" for k in _EDIT_TAGS}
    try:
        zero = piexif.load(path).get("0th", {})
    except Exception:  # noqa: BLE001
        return out
    for key, tag in _EDIT_TAGS.items():
        val = zero.get(tag)
        if isinstance(val, bytes):
            out[key] = val.decode("utf-8", "replace").rstrip("\x00")
        elif val is not None:
            out[key] = str(val)
    return out


def _shift_datetimes(data: dict, seconds: int, notes: list[str]) -> None:
    import datetime
    targets = [("Exif", piexif.ExifIFD.DateTimeOriginal),
               ("Exif", piexif.ExifIFD.DateTimeDigitized),
               ("0th", piexif.ImageIFD.DateTime)]
    changed = 0
    for ifd, tag in targets:
        raw = data.get(ifd, {}).get(tag)
        if not raw:
            continue
        try:
            s = raw.decode() if isinstance(raw, bytes) else str(raw)
            dt = datetime.datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
            dt += datetime.timedelta(seconds=seconds)
            data[ifd][tag] = dt.strftime("%Y:%m:%d %H:%M:%S").encode()
            changed += 1
        except Exception:  # noqa: BLE001
            notes.append("A date tag couldn't be parsed; left unchanged.")
    if changed:
        notes.append(f"Shifted {changed} date tag(s) by {seconds}s.")


def edit_metadata(path: str, out_path: str | None = None, *,
                  artist: str | None = None,
                  copyright: str | None = None,   # noqa: A002 — EXIF field name
                  description: str | None = None,
                  strip_gps: bool = False,
                  datetime_shift_sec: int = 0,
                  overwrite: bool = False) -> BakeResult:
    """Edit EXIF fields on a JPEG/TIFF and write the result.

    Only the arguments you pass are changed; ``None`` leaves a field untouched
    (pass "" to clear one). JPEG edits are lossless — the file is copied and only
    its EXIF segment is rewritten, never re-compressed. TIFF is re-saved (also
    lossless). Other formats can't be surgically edited and raise ValueError.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in _PIEXIF_FORMATS:
        raise ValueError(f"Editing fields needs a JPEG or TIFF; '{ext}' isn't supported.")

    notes: list[str] = []
    try:
        data = piexif.load(path)
    except Exception as exc:  # noqa: BLE001
        data = {}
        notes.append(f"No readable EXIF found; writing a fresh block ({exc}).")
    for ifd in ("0th", "Exif", "GPS", "1st"):
        data.setdefault(ifd, {})

    for key, value in (("artist", artist), ("copyright", copyright),
                       ("description", description)):
        if value is not None:
            data["0th"][_EDIT_TAGS[key]] = value.encode("utf-8", "replace")
    if strip_gps:
        data["GPS"] = {}
        notes.append("GPS removed.")
    if datetime_shift_sec:
        _shift_datetimes(data, datetime_shift_sec, notes)

    if out_path is None:
        root, e = os.path.splitext(path)
        out_path = path if overwrite else _next_free_path(f"{root}_meta{e}")

    exif_bytes = piexif.dump(data)
    if ext in (".jpg", ".jpeg"):
        if out_path != path:
            shutil.copy2(path, out_path)          # preserve pixels byte-for-byte
        piexif.insert(exif_bytes, out_path)       # rewrite EXIF only, no re-encode
    else:  # TIFF — lossless re-save with the new EXIF
        with Image.open(path) as im:
            im.save(out_path, exif=exif_bytes)
    return BakeResult(out_path, edited=True, notes=notes)


def stamp_files(paths: list[str], *, suffix: str = "_meta", **edits) -> list[BakeResult]:
    """Apply the same edits (artist/copyright/strip_gps/...) to many files.
    Each is written to a new ``<name><suffix>`` file; one failure doesn't stop
    the batch (it's reported as a note in that file's result)."""
    results = []
    for p in paths:
        try:
            root, ext = os.path.splitext(p)
            results.append(edit_metadata(p, _next_free_path(f"{root}{suffix}{ext}"), **edits))
        except Exception as exc:  # noqa: BLE001
            results.append(BakeResult(p, edited=False, notes=[f"ERROR: {exc}"]))
    return results
