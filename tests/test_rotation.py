"""
Rotation and EXIF auto-orientation tests for the PhotoBorder pipeline.

Two separate behaviours share this file because they interact: the EXIF
orientation tag is resolved first, and the manual rotation is applied on top of
the result, so a test for either has to pin the other down.

The claims worth testing here are not "does it rotate" - that is obvious from the
output size - but the ones that would silently regress:

  * the rotation direction (Pillow's ROTATE_* constants are counter-clockwise, so
    90 degrees clockwise is ROTATE_270; getting it backwards still rotates),
  * that right-angle rotation is genuinely lossless,
  * that the BORDER is recomputed from the rotated dimensions rather than the
    original, and
  * that the output no longer carries an orientation tag that would make a viewer
    rotate the finished canvas a second time.
"""
import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fontcatalog                                     # noqa: E402
from border import BorderType, create_border           # noqa: E402
from core import ROTATIONS, process_image              # noqa: E402

FONTDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
ORIENTATION_TAG = 274


def _write_source(path, size, orientation=None, marker=True):
    """A source photo with a distinguishable corner, and optionally an orientation tag."""
    img = Image.new("RGB", size, (200, 30, 30))
    if marker:
        # A green block in the top-left quarter-ish, so rotation direction is
        # detectable from the output rather than merely assumed.
        for x in range(size[0] // 8):
            for y in range(size[1] // 8):
                img.putpixel((x, y), (0, 255, 0))
    exif = Image.Exif()
    exif[0x010F] = "SONY"
    exif[0x0110] = "ILCE-7M4"
    if orientation is not None:
        exif[ORIENTATION_TAG] = orientation
    exif.get_ifd(0x8769).update({
        0x829D: 2.8, 0x920A: 70.0, 0x8827: 2000, 0x829A: 0.025,
        0xA433: "Sigma", 0xA434: "24-70mm F2.8 DG DN II",
    })
    img.save(path, exif=exif)
    return path


def _run(src, out_dir, *, rotate=0, auto_orient=True, border_type=BorderType.SMALL,
         add_exif=False, add_palette=False, target_ratio=None):
    return process_image(
        path=src, add_exif=add_exif, add_palette=add_palette, border_type=border_type,
        font=fontcatalog.spec("roboto"), boldfont=fontcatalog.spec("roboto", bold=True),
        fontdir=FONTDIR, output_root=str(out_dir), input_root=os.path.dirname(src),
        rotate=rotate, auto_orient=auto_orient, target_ratio=target_ratio,
    )


def _photo_box(img):
    """Bounding box of the photo inside the bordered canvas.

    The border is pure white and the photo is saturated, so the photo is found by
    looking for the first and last row/column containing a non-white pixel. Probing
    the CANVAS corners instead does not work: white is green-dominant, so every
    corner of the border reads as the green marker.
    """
    px = img.load()

    def coloured(x, y):
        r, g, b = px[x, y]
        return (max(r, g, b) - min(r, g, b)) > 40      # saturated => photo, not border

    xs = [x for x in range(img.width) if any(coloured(x, y) for y in range(0, img.height, 5))]
    ys = [y for y in range(img.height) if any(coloured(x, y) for x in range(0, img.width, 5))]
    assert xs and ys, "could not locate the photo inside the canvas"
    return min(xs), min(ys), max(xs), max(ys)


def _green_corner(img):
    """Which corner of the PHOTO holds the green marker: 'tl', 'tr', 'br' or 'bl'."""
    x0, y0, x1, y1 = _photo_box(img)
    w, h = x1 - x0, y1 - y0
    inset_x, inset_y = max(1, round(w * 0.02)), max(1, round(h * 0.02))
    probes = {
        "tl": (x0 + inset_x, y0 + inset_y),
        "tr": (x1 - inset_x, y0 + inset_y),
        "br": (x1 - inset_x, y1 - inset_y),
        "bl": (x0 + inset_x, y1 - inset_y),
    }
    px = img.load()

    def is_green(x, y):
        r, g, b = px[x, y]
        return g > r + 50 and g > b + 50

    found = [k for k, (x, y) in probes.items() if is_green(*(x, y))]
    assert len(found) == 1, f"expected exactly one green corner, found {found}"
    return found[0]


# ---------------------------------------------------------------------------
# Manual rotation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rotate,expect_swap", [(0, False), (90, True), (180, False), (270, True)])
def test_rotation_swaps_dimensions(tmp_path, rotate, expect_swap):
    src = _write_source(str(tmp_path / "src.png"), (1800, 1200))
    out = Image.open(_run(src, tmp_path / "o", rotate=rotate))
    # The canvas includes the border, so compare which axis is longer rather than
    # exact pixel counts.
    landscape = out.width > out.height
    assert landscape == (not expect_swap), (
        f"rotate={rotate}: got {out.size}, expected a "
        f"{'portrait' if expect_swap else 'landscape'} canvas")


def test_rotation_direction_is_clockwise(tmp_path):
    """90 must turn the image clockwise, not anticlockwise.

    Pillow's `ROTATE_90` is counter-clockwise, so a clockwise quarter turn is
    `ROTATE_270`. Both produce a correctly-shaped canvas, which is exactly why a
    dimension check cannot catch the mistake - the marker corner can.
    """
    src = _write_source(str(tmp_path / "src.png"), (1800, 1200))
    assert _green_corner(Image.open(_run(src, tmp_path / "a", rotate=0))) == "tl"
    assert _green_corner(Image.open(_run(src, tmp_path / "b", rotate=90))) == "tr"
    assert _green_corner(Image.open(_run(src, tmp_path / "c", rotate=180))) == "br"
    assert _green_corner(Image.open(_run(src, tmp_path / "d", rotate=270))) == "bl"


def test_right_angle_rotation_is_lossless(tmp_path):
    """Four 90-degree turns must return bit-identical pixels.

    This is the justification for restricting rotation to right angles, so it is
    worth asserting rather than asserting in a comment.
    """
    import random
    random.seed(7)
    img = Image.new("RGB", (61, 43))
    img.putdata([(random.randrange(256), random.randrange(256), random.randrange(256))
                 for _ in range(61 * 43)])
    turned = img
    for _ in range(4):
        turned = turned.transpose(Image.Transpose.ROTATE_270)
    assert turned.size == img.size
    assert list(turned.getdata()) == list(img.getdata())


def test_border_is_recomputed_from_rotated_dimensions(tmp_path):
    """A rotated landscape must get a portrait's border, not a landscape's.

    Border widths come from `get_border_size(img.width, img.height, ...)`, so
    rotating after the border was computed would leave a portrait photo sitting in
    a frame proportioned for a landscape.
    """
    src = _write_source(str(tmp_path / "src.png"), (1800, 1200))
    rotated = Image.open(_run(src, tmp_path / "r", rotate=90))
    # The same pipeline given an already-portrait source of the rotated shape must
    # produce an identically-sized canvas.
    native = _write_source(str(tmp_path / "nat.png"), (1200, 1800))
    reference = Image.open(_run(native, tmp_path / "n"))
    assert rotated.size == reference.size, (
        f"rotated canvas {rotated.size} != natively-portrait canvas {reference.size}")


def test_rotation_composes_with_ratio_padding(tmp_path):
    """Ratio padding must apply to the rotated shape."""
    src = _write_source(str(tmp_path / "src.png"), (1800, 1200))
    out = Image.open(_run(src, tmp_path / "o", rotate=90, target_ratio=1.0))
    assert abs(out.width - out.height) <= 2, f"expected a square canvas, got {out.size}"


def test_caption_band_stays_at_the_bottom_after_rotation(tmp_path):
    """The caption band must be at the bottom of the ROTATED canvas."""
    src = _write_source(str(tmp_path / "src.png"), (1800, 1200))
    out = Image.open(_run(src, tmp_path / "o", rotate=90, add_exif=True,
                          border_type=BorderType.POLAROID))
    border = create_border(1200, 1800, BorderType.POLAROID)
    band = border.caption_band or border.bottom
    band_top = out.height - band
    px = out.load()
    ink = [y for y in range(band_top + 1, out.height)
           for x in range(0, out.width, 7)
           if max(px[x, y]) < 250 and (max(px[x, y]) - min(px[x, y])) <= 12]
    assert ink, "no caption ink in the bottom band of the rotated canvas"


def test_invalid_rotation_is_rejected(tmp_path):
    src = _write_source(str(tmp_path / "src.png"), (600, 400))
    with pytest.raises(ValueError, match="rotate must be one of"):
        _run(src, tmp_path / "o", rotate=45)


def test_rotation_suffix_only_when_rotated(tmp_path):
    src = _write_source(str(tmp_path / "src.png"), (600, 400))
    assert "_rot" not in os.path.basename(_run(src, tmp_path / "a", rotate=0))
    assert "_rot90" in os.path.basename(_run(src, tmp_path / "b", rotate=90))


# ---------------------------------------------------------------------------
# EXIF auto-orientation
# ---------------------------------------------------------------------------
def test_tagged_file_is_oriented_before_the_border_is_sized(tmp_path):
    """Orientation 6 means "display this landscape file rotated a quarter turn".

    Before this fix the border was sized from the stored (landscape) pixels, so
    such a file got a landscape frame around what is really a portrait photo.
    """
    tagged = _write_source(str(tmp_path / "tagged.jpg"), (1800, 1200), orientation=6)
    out = Image.open(_run(tagged, tmp_path / "o"))
    assert out.height > out.width, (
        f"orientation-6 source produced a {out.size} canvas; expected portrait")


def test_output_orientation_tag_is_reset(tmp_path):
    """The finished canvas must not carry a tag that rotates it again.

    This was the actual bug: the pipeline copied the source's orientation tag
    into the output while ignoring it for layout, so a viewer honouring the tag
    turned the whole bordered canvas - caption band included - a quarter turn.
    """
    tagged = _write_source(str(tmp_path / "tagged.jpg"), (1800, 1200), orientation=6)
    out = Image.open(_run(tagged, tmp_path / "o"))
    assert out.getexif().get(ORIENTATION_TAG) in (None, 1), (
        f"output still tagged orientation {out.getexif().get(ORIENTATION_TAG)}")


def test_auto_orient_can_be_disabled(tmp_path):
    """`auto_orient=False` keeps the old behaviour for a file with a wrong tag."""
    tagged = _write_source(str(tmp_path / "tagged.jpg"), (1800, 1200), orientation=6)
    out = Image.open(_run(tagged, tmp_path / "o", auto_orient=False))
    assert out.width > out.height, "auto_orient=False should leave the pixels alone"


def test_untagged_files_are_unaffected(tmp_path):
    """A file with no orientation tag must come out exactly as before.

    Guards the no-op path: auto-orient is on by default, so it runs for every
    file, and the overwhelming majority carry no tag at all.
    """
    plain = _write_source(str(tmp_path / "plain.png"), (1800, 1200))
    on = Image.open(_run(plain, tmp_path / "a", auto_orient=True))
    off = Image.open(_run(plain, tmp_path / "b", auto_orient=False))
    assert on.size == off.size
    assert list(on.getdata()) == list(off.getdata())


def test_manual_rotation_applies_on_top_of_auto_orientation(tmp_path):
    """Rotation is relative to what the user sees, not to the raw sensor readout.

    An orientation-6 file already displays as a portrait, so rotating it 90 more
    must give a landscape - not return it to the stored landscape by cancelling
    out, and not double-rotate.
    """
    tagged = _write_source(str(tmp_path / "tagged.jpg"), (1800, 1200), orientation=6)
    oriented = Image.open(_run(tagged, tmp_path / "a"))
    plus90 = Image.open(_run(tagged, tmp_path / "b", rotate=90))
    assert oriented.height > oriented.width, "auto-oriented result should be portrait"
    assert plus90.width > plus90.height, "portrait + 90 should be landscape"


@pytest.mark.parametrize("rotate", ROTATIONS)
def test_every_documented_rotation_runs(tmp_path, rotate):
    """ROTATIONS is what the GUI and CLI offer; all of it must work end to end."""
    src = _write_source(str(tmp_path / "src.png"), (900, 600))
    out = _run(src, tmp_path / f"o{rotate}", rotate=rotate, add_exif=True, add_palette=True,
               border_type=BorderType.POLAROID)
    assert out and os.path.isfile(out)
