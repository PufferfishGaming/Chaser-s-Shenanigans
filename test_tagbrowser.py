"""Tests for the raw tag browser in metadata_core (load_all_tags / apply_tag_edits).

Headless: builds a small camera-like JPEG with piexif, then exercises the
browse -> edit -> save -> reload loop, the safety blocklists, and the
pixels-never-touched guarantee.
"""
import piexif
import pytest
from PIL import Image

import metadata_core as mc


def _make_jpeg(path):
    exif = {
        "0th": {piexif.ImageIFD.Make: b"SONY",
                piexif.ImageIFD.Model: b"ILCE-7M4",
                piexif.ImageIFD.Artist: b"Gabor",
                piexif.ImageIFD.Orientation: 1,
                piexif.ImageIFD.XResolution: (300, 1)},
        "Exif": {piexif.ExifIFD.FNumber: (28, 10),
                 piexif.ExifIFD.ExposureTime: (1, 250),
                 piexif.ExifIFD.ISOSpeedRatings: 800,
                 piexif.ExifIFD.DateTimeOriginal: b"2026:07:01 21:00:00",
                 piexif.ExifIFD.MakerNote: b"\x00\x01\x02sonyblob",
                 piexif.ExifIFD.LensModel: b"FE 24-70mm F2.8 GM"},
        "GPS": {piexif.GPSIFD.GPSLatitudeRef: b"N",
                piexif.GPSIFD.GPSLatitude: ((47, 1), (29, 1), (3000, 100))},
        "1st": {}, "thumbnail": None,
    }
    Image.new("RGB", (40, 30), (10, 20, 30)).save(path, exif=piexif.dump(exif))
    return str(path)


def _entry(entries, name):
    return next(e for e in entries if e.name == name)


def test_load_lists_all_ifds_with_names_and_types(tmp_path):
    p = _make_jpeg(tmp_path / "t.jpg")
    entries = mc.load_all_tags(p)
    names = {e.name for e in entries}
    assert {"Make", "Artist", "FNumber", "GPSLatitude", "DateTimeOriginal"} <= names
    assert _entry(entries, "FNumber").type_name == "Rational"
    assert _entry(entries, "FNumber").value == "28/10"
    assert _entry(entries, "GPSLatitude").value == "47/1, 29/1, 3000/100"
    assert _entry(entries, "Artist").editable


def test_structural_and_makernote_are_view_only(tmp_path):
    p = _make_jpeg(tmp_path / "t.jpg")
    entries = mc.load_all_tags(p)
    assert not _entry(entries, "ExifTag").editable       # IFD pointer
    assert not _entry(entries, "MakerNote").editable     # proprietary blob
    # And apply refuses them outright, belt-and-braces:
    with pytest.raises(ValueError):
        mc.apply_tag_edits(p, {("Exif", 37500): "boom"})
    with pytest.raises(ValueError):
        mc.apply_tag_edits(p, {}, deletions=[("0th", 34665)])


def test_ascii_edit_roundtrip_preserves_pixels(tmp_path):
    p = _make_jpeg(tmp_path / "t.jpg")
    before = Image.open(p).tobytes()
    res = mc.apply_tag_edits(p, {("0th", piexif.ImageIFD.Artist): "Stormchaser"})
    assert res.out_path.endswith("_meta.jpg")
    entries = mc.load_all_tags(res.out_path)
    assert _entry(entries, "Artist").value == "Stormchaser"
    assert Image.open(res.out_path).tobytes() == before   # EXIF-only rewrite


def test_rational_and_int_edits(tmp_path):
    p = _make_jpeg(tmp_path / "t.jpg")
    res = mc.apply_tag_edits(p, {
        ("Exif", piexif.ExifIFD.FNumber): "4/1",
        ("Exif", piexif.ExifIFD.ISOSpeedRatings): "1600",
        ("GPS", piexif.GPSIFD.GPSLatitude): "48/1, 0/1, 0/1",
    })
    entries = mc.load_all_tags(res.out_path)
    assert _entry(entries, "FNumber").value == "4/1"
    assert _entry(entries, "ISOSpeedRatings").value == "1600"
    assert _entry(entries, "GPSLatitude").value == "48/1, 0/1, 0/1"


def test_decimal_input_becomes_rational(tmp_path):
    p = _make_jpeg(tmp_path / "t.jpg")
    res = mc.apply_tag_edits(p, {("Exif", piexif.ExifIFD.FNumber): "2.8"})
    entries = mc.load_all_tags(res.out_path)
    assert _entry(entries, "FNumber").value == "14/5"     # Fraction(2.8) normalised


def test_delete_tag(tmp_path):
    p = _make_jpeg(tmp_path / "t.jpg")
    res = mc.apply_tag_edits(p, {}, deletions=[("0th", piexif.ImageIFD.Artist)])
    assert all(e.name != "Artist" for e in mc.load_all_tags(res.out_path))


def test_bad_value_raises_with_tag_name(tmp_path):
    p = _make_jpeg(tmp_path / "t.jpg")
    with pytest.raises(ValueError, match="FNumber"):
        mc.apply_tag_edits(p, {("Exif", piexif.ExifIFD.FNumber): "wide open"})


def test_overwrite_writes_in_place(tmp_path):
    p = _make_jpeg(tmp_path / "t.jpg")
    res = mc.apply_tag_edits(p, {("0th", piexif.ImageIFD.Artist): "X"}, overwrite=True)
    assert res.out_path == p
    assert _entry(mc.load_all_tags(p), "Artist").value == "X"


def test_unsupported_format_refused(tmp_path):
    png = tmp_path / "t.png"
    Image.new("RGB", (8, 8)).save(png)
    with pytest.raises(ValueError):
        mc.load_all_tags(str(png))
