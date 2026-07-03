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


# ---------------------------------------------------------------- raw tag browser
# ExifTool-style "show me everything" view of a JPEG/TIFF's EXIF, with editing
# restricted to tag types we can round-trip safely. Design rules:
#
# * Structural tags (IFD pointers, strip/thumbnail offsets) are shown but never
#   editable - piexif recomputes them on save, and hand-edited offsets corrupt
#   files. Honest display beats hiding them.
# * MakerNote and UserComment are never editable. MakerNotes are proprietary
#   binary blobs (Sony's especially) that do not survive naive rewrites;
#   UserComment carries an 8-byte charset prefix that plain text editing breaks.
# * Everything else is editable if its value is text, integers, or rationals -
#   the shapes piexif can validate and re-dump deterministically.

_IFDS = ("0th", "Exif", "GPS", "1st", "Interop")

_TYPE_NAMES = {1: "Byte", 2: "Ascii", 3: "Short", 4: "Long", 5: "Rational",
               6: "SByte", 7: "Undefined", 8: "SShort", 9: "SLong",
               10: "SRational", 11: "Float", 12: "DFloat"}

# (ifd, tag_id) pairs that are structural: piexif recomputes them on dump, so a
# user edit is at best ignored and at worst corrupting. Numeric IDs on purpose -
# they're stable in the EXIF spec, unlike piexif attribute names.
_STRUCTURAL_TAGS = {
    ("0th", 34665), ("0th", 34853),            # ExifTag / GPSTag IFD pointers
    ("Exif", 40965),                           # Interoperability IFD pointer
    ("0th", 273), ("0th", 278), ("0th", 279),  # StripOffsets / RowsPerStrip / StripByteCounts
    ("1st", 273), ("1st", 278), ("1st", 279),
    ("1st", 513), ("1st", 514),                # JPEGInterchangeFormat(+Length): thumbnail offsets
}

# (ifd, tag_id) pairs that are technically data but unsafe to edit as text.
_BLOB_TAGS = {
    ("Exif", 37500),   # MakerNote - proprietary binary, breaks if rewritten naively
    ("Exif", 37510),   # UserComment - 8-byte charset prefix, not plain text
}


class TagEntry:
    """One row of the raw tag browser."""
    def __init__(self, ifd: str, tag_id: int, name: str, type_name: str,
                 value: str, editable: bool, note: str = ""):
        self.ifd = ifd
        self.tag_id = tag_id
        self.name = name
        self.type_name = type_name
        self.value = value          # display/edit text
        self.editable = editable
        self.note = note            # why not editable (tooltip), or ""


def _tag_info(ifd: str, tag_id: int) -> tuple[str, int | None]:
    """(name, declared_type_code) from piexif's tag tables, best-effort."""
    table = piexif.TAGS.get("Interop" if ifd == "Interop" else ifd, {})
    info = table.get(tag_id, {})
    return info.get("name", f"Unknown-{tag_id}"), info.get("type")


def _decode_text(raw: bytes) -> str | None:
    """Bytes -> printable text, or None if it isn't cleanly textual."""
    try:
        s = raw.rstrip(b"\x00").decode("utf-8")
    except UnicodeDecodeError:
        return None
    if all(ch.isprintable() or ch in "\r\n\t" for ch in s):
        return s
    return None


def _fmt_rational(raw) -> str:
    if isinstance(raw, tuple) and len(raw) == 2 and all(isinstance(x, int) for x in raw):
        return f"{raw[0]}/{raw[1]}"
    return ", ".join(f"{n}/{d}" for n, d in raw)


def format_tag_value(raw, type_code: int | None) -> tuple[str, bool, str]:
    """(display_text, editable, note) for a stored piexif value."""
    if isinstance(raw, bytes):
        text = _decode_text(raw)
        if text is not None:
            return text, True, ""
        preview = raw[:16].hex(" ")
        more = "…" if len(raw) > 16 else ""
        return f"<{len(raw)} bytes: {preview}{more}>", False, "Binary data - view only."
    if isinstance(raw, int):
        return str(raw), True, ""
    if isinstance(raw, float):
        return str(raw), True, ""
    if isinstance(raw, tuple):
        try:
            if type_code in (5, 10):  # (S)Rational: (n,d) or ((n,d),...)
                return _fmt_rational(raw), True, ""
            if len(raw) == 2 and all(isinstance(x, int) for x in raw) and type_code is None:
                # Unknown tag, pair of ints: could be a rational - show as one,
                # parsing accepts both forms so the round-trip is safe.
                return _fmt_rational(raw), True, ""
            if all(isinstance(x, tuple) for x in raw):
                return _fmt_rational(raw), True, ""
            return ", ".join(str(x) for x in raw), True, ""
        except Exception:  # noqa: BLE001 - malformed value: show, don't die
            return repr(raw), False, "Unrecognised value shape - view only."
    return repr(raw), False, "Unrecognised value type - view only."


def _parse_number_pair(part: str) -> tuple[int, int]:
    from fractions import Fraction
    part = part.strip()
    if "/" in part:
        n, d = part.split("/", 1)
        return int(n.strip()), int(d.strip())
    f = Fraction(part).limit_denominator(1_000_000)
    return f.numerator, f.denominator


def parse_tag_text(ifd: str, tag_id: int, text: str, current_raw):
    """Text from the editor -> a piexif-storable value shaped like the tag wants.

    Raises ValueError with a human-readable message on bad input.
    """
    _, type_code = _tag_info(ifd, tag_id)
    text = text.strip()
    try:
        if isinstance(current_raw, bytes) or type_code == 2:      # Ascii/text
            return text.encode("utf-8")
        if type_code in (5, 10) or (isinstance(current_raw, tuple)
                                    and current_raw and isinstance(current_raw[0], tuple)):
            parts = [p for p in text.split(",") if p.strip()]
            if not parts:
                raise ValueError("empty value")
            pairs = tuple(_parse_number_pair(p) for p in parts)
            return pairs[0] if len(pairs) == 1 else pairs         # (n,d) or ((n,d),...)
        if isinstance(current_raw, tuple):                        # ints
            vals = tuple(int(p.strip()) for p in text.split(",") if p.strip())
            if not vals:
                raise ValueError("empty value")
            return vals[0] if len(vals) == 1 else vals
        if isinstance(current_raw, float):
            return float(text)
        return int(text)                                          # plain int
    except ValueError as exc:
        name, _ = _tag_info(ifd, tag_id)
        raise ValueError(
            f"{name}: can't parse '{text}' as {_TYPE_NAMES.get(type_code, 'this tag')} "
            f"(expected e.g. text, '42', '1, 2, 3' or '28/10')."
        ) from exc


def load_all_tags(path: str) -> list[TagEntry]:
    """Every EXIF tag in the file, exiftool-style, with editability decided.

    Raises ValueError for unsupported formats and lets piexif errors surface
    so the GUI can report an unreadable file.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in _PIEXIF_FORMATS:
        raise ValueError(f"The tag browser needs a JPEG or TIFF; '{ext}' isn't supported.")
    data = piexif.load(path)
    entries: list[TagEntry] = []
    for ifd in _IFDS:
        for tag_id in sorted(data.get(ifd, {})):
            raw = data[ifd][tag_id]
            name, type_code = _tag_info(ifd, tag_id)
            value, editable, note = format_tag_value(raw, type_code)
            key = (ifd, tag_id)
            if key in _STRUCTURAL_TAGS:
                editable, note = False, "Structural - recomputed on save."
            elif key in _BLOB_TAGS:
                editable, note = False, ("Proprietary binary block - rewriting it corrupts "
                                         "camera data." if tag_id == 37500 else
                                         "Encoded block (charset prefix) - view only.")
            entries.append(TagEntry(ifd, tag_id, name,
                                    _TYPE_NAMES.get(type_code, "?"), value, editable, note))
    thumb = data.get("thumbnail")
    if thumb:
        entries.append(TagEntry("1st", -1, "JPEGThumbnail", "Undefined",
                                f"<{len(thumb)} bytes embedded thumbnail>", False,
                                "Embedded preview image - view only."))
    return entries


def apply_tag_edits(path: str, edits: dict, deletions=(), *,
                    out_path: str | None = None, overwrite: bool = False) -> BakeResult:
    """Write raw tag edits/deletions to a JPEG/TIFF.

    ``edits`` maps (ifd, tag_id) -> new value as TEXT (parsed and validated
    here, so the GUI and any future CLI share one code path). ``deletions`` is
    an iterable of (ifd, tag_id) to remove. Same output conventions as
    edit_metadata: new ``<name>_meta`` file unless ``overwrite``; JPEG pixels
    are never re-encoded.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in _PIEXIF_FORMATS:
        raise ValueError(f"Editing tags needs a JPEG or TIFF; '{ext}' isn't supported.")

    notes: list[str] = []
    data = piexif.load(path)

    for (ifd, tag_id) in deletions:
        if (ifd, tag_id) in _STRUCTURAL_TAGS:
            raise ValueError(f"{_tag_info(ifd, tag_id)[0]} is structural and can't be deleted.")
        if data.get(ifd, {}).pop(tag_id, None) is not None:
            notes.append(f"Deleted {_tag_info(ifd, tag_id)[0]} ({ifd}).")

    for (ifd, tag_id), text in edits.items():
        key = (ifd, tag_id)
        if key in _STRUCTURAL_TAGS or key in _BLOB_TAGS:
            raise ValueError(f"{_tag_info(ifd, tag_id)[0]} is not editable.")
        current = data.get(ifd, {}).get(tag_id)
        if current is None:
            raise ValueError(f"{_tag_info(ifd, tag_id)[0]} is no longer present in the file.")
        data[ifd][tag_id] = parse_tag_text(ifd, tag_id, text, current)
        notes.append(f"Set {_tag_info(ifd, tag_id)[0]} ({ifd}).")

    if out_path is None:
        root, e = os.path.splitext(path)
        out_path = path if overwrite else _next_free_path(f"{root}_meta{e}")

    try:
        exif_bytes = piexif.dump(data)
    except Exception as exc:  # noqa: BLE001 - piexif's type errors are cryptic; name the culprit if we can
        raise ValueError(f"EXIF could not be rebuilt with these values: {exc}") from exc

    if ext in (".jpg", ".jpeg"):
        if out_path != path:
            shutil.copy2(path, out_path)          # preserve pixels byte-for-byte
        piexif.insert(exif_bytes, out_path)       # rewrite EXIF only, no re-encode
    else:  # TIFF - lossless re-save with the new EXIF
        with Image.open(path) as im:
            im.save(out_path, exif=exif_bytes)
    return BakeResult(out_path, edited=True, notes=notes)
