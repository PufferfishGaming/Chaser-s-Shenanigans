"""
Geometry tests for the caption band (EXIF caption + optional custom text).

These are deliberately *pixel* tests rather than unit tests of the sizing
helpers. The established way to verify visual behaviour in this project is to
render and inspect, and the failures that actually happen here are geometric:
text overlapping the line above it, a script descender clipped by the canvas
edge, or a caption running into the palette. None of those are visible from the
return value of a font-size function.

Method: render a solid-black synthetic photo (PNG, so there is no JPEG noise to
threshold against) onto a white border, then find every row and column in the
caption band containing ink. Rows of ink cluster into text lines, and the
assertions are about those clusters.
"""
import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fontcatalog                                    # noqa: E402
from border import BorderType, create_border          # noqa: E402
from core import process_image                        # noqa: E402

FONTDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
# Caption ink is neutral grey - (100, 100, 100) for the heading and custom text,
# (128, 128, 128) for the body lines - so "ink" is defined by chroma as well as
# lightness. That distinction is load-bearing: the colour palette is rendered from
# the photo's own colours INTO the same band, and a purely lightness-based test
# picks the palette's swatches up as if they were text. One assertion here failed
# for exactly that reason - it reported the caption "reaching" column 1804 when
# 1804 was the palette's right edge and the text stopped at 1670.
#
# So the synthetic photo is a saturated colour: paper stays neutral-and-light, the
# palette and photo are saturated, and only the caption is neutral-and-dark.
INK_MAX_LEVEL = 250          # at or above this on every channel = paper
INK_MAX_CHROMA = 12          # max-min channel spread; above this = photo/palette
PHOTO_COLOUR = (200, 30, 30)
CUSTOM_TEXT = "Gábor Fauszt"


def _is_ink(pixel):
    r, g, b = pixel
    return max(r, g, b) < INK_MAX_LEVEL and (max(r, g, b) - min(r, g, b)) <= INK_MAX_CHROMA


@pytest.fixture(scope="module")
def source_png(tmp_path_factory):
    """A solid, saturated 1800x1200 source photo carrying real EXIF.

    PNG rather than JPEG so the white border is exactly (255, 255, 255) and the
    ink threshold below has no compression ringing to trip over - JPEG artefacts
    along the photo's bottom edge would otherwise register as caption ink in the
    first rows of the band.

    The EXIF has to be real: `exif.get_exif` returns a fully-populated dict of
    empty strings when a file has no EXIF, which is truthy, so `process_image`
    happily "draws" three lines of whitespace and the pixel assertions see
    nothing at all.
    """
    d = tmp_path_factory.mktemp("src")
    p = os.path.join(str(d), "synthetic.png")
    img = Image.new("RGB", (1800, 1200), PHOTO_COLOUR)
    exif = Image.Exif()
    exif[0x010F] = "SONY"                       # Make
    exif[0x0110] = "ILCE-7M4"                   # Model
    exif.get_ifd(0x8769).update({
        0x829D: 2.8,                            # FNumber
        0x920A: 70.0,                           # FocalLength
        0x8827: 2000,                           # ISOSpeedRatings
        0x829A: 0.025,                          # ExposureTime
        0xA433: "Sigma",                        # LensMake
        0xA434: "24-70mm F2.8 DG DN II",        # LensModel
    })
    img.save(p, exif=exif)
    return p


def _render(source_png, tmp_path, border_type, *, add_exif=True, add_palette=False,
            custom_text=CUSTOM_TEXT, text_font="greatvibes", size_mult=1.0,
            exif_font="ebgaramond", centered=False):
    out = process_image(
        path=source_png,
        add_exif=add_exif,
        add_palette=add_palette,
        border_type=border_type,
        font=fontcatalog.spec(exif_font),
        boldfont=fontcatalog.spec(exif_font, bold=True),
        fontdir=FONTDIR,
        output_root=str(tmp_path),
        input_root=os.path.dirname(source_png),
        custom_text=custom_text,
        custom_font=fontcatalog.spec(text_font) if custom_text else None,
        custom_size_mult=size_mult,
        custom_centered=centered,
    )
    assert out is not None, "process_image returned None - unsupported file type?"
    return Image.open(out).convert("RGB")


def _band_geometry(img, border_type):
    """(band_top, band) for a rendered canvas, recomputed the same way core does."""
    border = create_border(1800, 1200, border_type, target_ratio=None)
    band = border.caption_band or border.bottom
    return img.height - band, band, border


def _ink_cols(img, top, bottom, left=0, right=None):
    """Column indices in [left, right) that contain any ink in [top, bottom)."""
    right = img.width if right is None else right
    px = img.load()
    cols = []
    for x in range(max(0, left), min(right, img.width)):
        for y in range(max(0, top), min(bottom, img.height)):
            if _is_ink(px[x, y]):
                cols.append(x)
                break
    return cols


def _ink_rows(img, top, bottom, left=0, right=None):
    """Row indices in [top, bottom) that contain any ink in [left, right)."""
    right = img.width if right is None else right
    px = img.load()
    rows = []
    for y in range(max(0, top), min(bottom, img.height)):
        for x in range(left, right):
            if _is_ink(px[x, y]):
                rows.append(y)
                break
    return rows


def _clusters(rows, gap=2):
    """Group consecutive-ish row indices into runs. One run == one line of text."""
    out = []
    for y in rows:
        if out and y - out[-1][1] <= gap:
            out[-1][1] = y
        else:
            out.append([y, y])
    return [tuple(c) for c in out]


ALL_TYPES = list(BorderType)
STACKED = [BorderType.POLAROID, BorderType.LARGE]
ROW_TYPES = [BorderType.SMALL, BorderType.MEDIUM]


@pytest.mark.parametrize("border_type", ALL_TYPES)
def test_caption_ink_stays_inside_canvas(source_png, tmp_path, border_type):
    """No caption ink may touch the bottom edge of the canvas.

    Regression guard for script faces: Great Vibes descends ~25px at size 64
    where Roboto descends ~1px, so a baseline derived from the band midpoint used
    to push the tail of a signature off the frame.
    """
    img = _render(source_png, tmp_path, border_type)
    band_top, band, _ = _band_geometry(img, border_type)
    rows = _ink_rows(img, band_top + 1, img.height)
    assert rows, "expected caption ink in the band"
    assert max(rows) < img.height - 1, (
        f"{border_type.name}: caption ink reaches row {max(rows)} of {img.height} - clipped at the edge")


@pytest.mark.parametrize("border_type", ALL_TYPES)
def test_caption_ink_does_not_reach_the_photograph(source_png, tmp_path, border_type):
    """The caption block must stay below the photo, never overlap it."""
    img = _render(source_png, tmp_path, border_type, size_mult=3.0)
    band_top, band, _ = _band_geometry(img, border_type)
    # The photo's bottom edge sits at band_top for the native-ratio case. Since the
    # photo is saturated it never registers as ink, so any ink found above band_top
    # is a caption that has escaped the band.
    photo_bottom = img.height - create_border(1800, 1200, border_type).bottom
    assert band_top >= photo_bottom - 1, "band should not start above the photo's bottom edge"
    # Scan a generous strip above the band, not a single row: at a 3x multiplier the
    # failure mode is a whole line of text sitting over the photograph, not one
    # stray pixel. Anything neutral-and-dark up here is escaped caption ink.
    probe = _ink_rows(img, band_top - band, band_top)
    assert probe == [], (
        f"{border_type.name}: caption ink found above the band at 3x multiplier, rows "
        f"{probe[:5]}{'...' if len(probe) > 5 else ''}")


@pytest.mark.parametrize("border_type", STACKED)
def test_custom_line_never_overlaps_the_exif_lines(source_png, tmp_path, border_type):
    """Four distinct, non-touching text lines on the stacked layouts.

    This is the regression test for the 2.5x bug: `draw_text_on_image` advances
    by 1.5x the size of the line it just drew, so a custom line larger than the
    EXIF body reached its ascenders back up through the settings line. At 2.5x
    the two lines visibly struck through each other.
    """
    for mult in (1.0, 1.5, 2.5):
        img = _render(source_png, tmp_path, border_type, size_mult=mult)
        band_top, band, _ = _band_geometry(img, border_type)
        clusters = _clusters(_ink_rows(img, band_top + 1, img.height))
        assert len(clusters) == 4, (
            f"{border_type.name} at {mult}x: expected 4 separate text lines "
            f"(heading, lens, settings, custom), found {len(clusters)}: {clusters}")


@pytest.mark.parametrize("border_type", STACKED)
def test_three_lines_when_no_custom_text(source_png, tmp_path, border_type):
    """Without custom text the stacked layout is unchanged: exactly 3 lines."""
    img = _render(source_png, tmp_path, border_type, custom_text=None)
    band_top, band, _ = _band_geometry(img, border_type)
    clusters = _clusters(_ink_rows(img, band_top + 1, img.height))
    assert len(clusters) == 3, f"{border_type.name}: expected 3 lines, found {clusters}"


@pytest.mark.parametrize("border_type", ROW_TYPES)
def test_row_layout_stays_single_line(source_png, tmp_path, border_type):
    """SMALL/MEDIUM keep the custom text on the existing single row."""
    img = _render(source_png, tmp_path, border_type, size_mult=1.0)
    band_top, band, _ = _band_geometry(img, border_type)
    clusters = _clusters(_ink_rows(img, band_top + 1, img.height))
    assert len(clusters) == 1, (
        f"{border_type.name}: custom text should join the EXIF row, not start a "
        f"new line; found {len(clusters)} lines: {clusters}")


@pytest.mark.parametrize("border_type", [BorderType.POLAROID, BorderType.SMALL, BorderType.MEDIUM])
def test_caption_never_enters_the_palette_column(source_png, tmp_path, border_type):
    """With the palette on, no caption ink may appear in the palette's column.

    The palette owns the bottom-right of the band. This is what makes placing the
    custom text alongside the EXIF caption safe rather than a collision.
    """
    img = _render(source_png, tmp_path, border_type, add_palette=True, size_mult=2.0)
    band_top, band, border = _band_geometry(img, border_type)

    palette_size = round(band / 3)
    margin = round(palette_size / 2)
    # Reconstruct the palette's left edge exactly as core.process_image does. The
    # synthetic source is a single flat colour, so extcolors returns one swatch.
    palette_left = border.left + 1800 - palette_size - margin
    text_limit = palette_left - palette_size

    rows = _ink_rows(img, band_top + 1, img.height, left=text_limit, right=palette_left)
    assert rows == [], (
        f"{border_type.name}: caption ink found in the gap reserved before the "
        f"palette (columns {text_limit}-{palette_left})")


def test_custom_text_alone_when_exif_disabled(source_png, tmp_path):
    """EXIF off + custom text on renders exactly one line, inside the band."""
    img = _render(source_png, tmp_path, BorderType.POLAROID, add_exif=False)
    band_top, band, _ = _band_geometry(img, BorderType.POLAROID)
    clusters = _clusters(_ink_rows(img, band_top + 1, img.height))
    assert len(clusters) == 1, f"expected a single custom line, found {clusters}"
    assert clusters[0][1] < img.height - 1


def test_blank_custom_text_is_a_no_op(source_png, tmp_path):
    """Whitespace-only custom text must not change the output or the filename."""
    plain = _render(source_png, tmp_path, BorderType.POLAROID, custom_text=None)
    blank = _render(source_png, tmp_path, BorderType.POLAROID, custom_text="   ")
    assert plain.size == blank.size
    assert list(plain.getdata()) == list(blank.getdata())


# ---------------------------------------------------------------------------
# Centred custom text
# ---------------------------------------------------------------------------
def _exif_block_right_edge(img, border_type, exclude_from):
    """Rightmost column of the EXIF caption, ignoring anything from `exclude_from`."""
    band_top, band, _ = _band_geometry(img, border_type)
    cols = _ink_cols(img, band_top + 1, img.height, 0, exclude_from)
    return max(cols) if cols else 0


def _custom_ink_box(img, border_type, left_of_palette):
    """Bounding box of the custom text's ink.

    On the centred POLAROID layout the custom line no longer has rows to itself -
    it sits at the band's vertical centre beside the left-aligned EXIF block - so it
    cannot be found by taking the last row-cluster. It is isolated by column
    instead: everything right of a gap after the EXIF block and left of the palette.
    """
    band_top, band, border = _band_geometry(img, border_type)
    cols = _ink_cols(img, band_top + 1, img.height, 0, left_of_palette)
    assert cols, "no caption ink found"
    # Split the columns into runs; the custom text is the rightmost run whenever it
    # is separated from the caption, and the only run when the caption is centred.
    runs = []
    for c in cols:
        if runs and c - runs[-1][1] <= 40:
            runs[-1][1] = c
        else:
            runs.append([c, c])
    left, right = runs[-1]
    rows = _ink_rows(img, band_top + 1, img.height, left, right + 1)
    return left, right, min(rows), max(rows)


def _custom_line_band(img, border_type):
    """(top, bottom) rows of the LAST ink cluster in the band - the custom line."""
    band_top, band, _ = _band_geometry(img, border_type)
    clusters = _clusters(_ink_rows(img, band_top + 1, img.height))
    assert clusters, "no caption ink found"
    return clusters[-1]


def _palette_left(img, border_type):
    band_top, band, border = _band_geometry(img, border_type)
    palette_size = round(band / 3)
    return border.left + 1800 - palette_size - round(palette_size / 2)


@pytest.mark.parametrize("border_type", STACKED)
def test_centered_custom_text_is_actually_centred(source_png, tmp_path, border_type):
    """The centred custom line's ink must be symmetric about the canvas midline.

    Canvas-centre and photo-centre are the same pixel here, because `bleft` equals
    `bright` for every border type and ratio padding splits evenly, so one
    assertion covers both readings of "the middle".
    """
    img = _render(source_png, tmp_path, border_type, add_palette=True,
                  centered=True, size_mult=1.5)
    left, right, _, _ = _custom_ink_box(img, border_type, _palette_left(img, border_type))
    mid_ink = (left + right) / 2
    mid_canvas = img.width / 2
    # A glyph's side bearings are not symmetric, so allow a small slack rather
    # than demanding exact equality.
    slack = max(4, 0.01 * img.width)
    assert abs(mid_ink - mid_canvas) <= slack, (
        f"{border_type.name}: custom line centred at {mid_ink:.0f}, canvas midline "
        f"{mid_canvas:.0f} (slack {slack:.0f})")


def test_centring_does_not_move_the_exif_caption(source_png, tmp_path):
    """Switching centring on must leave the EXIF caption exactly where it was.

    Regression test for the reported bug. Adding a fourth stacked line re-centres
    the whole block and shifted the EXIF caption up by 41px in a 642px band, while
    dropping the custom line below the palette. With centring on, the custom text
    takes the band's vertical centre beside the caption instead, so the caption
    keeps the rows it occupies with no custom text at all - byte for byte.
    """
    without = _render(source_png, tmp_path, BorderType.POLAROID,
                      custom_text=None, add_palette=True)
    centred = _render(source_png, tmp_path, BorderType.POLAROID,
                      centered=True, add_palette=True)
    pal = _palette_left(img=centred, border_type=BorderType.POLAROID)
    band_top, band, border = _band_geometry(centred, BorderType.POLAROID)

    # Compare the caption's own column range, left of wherever the custom text is.
    custom_left, _, _, _ = _custom_ink_box(centred, BorderType.POLAROID, pal)
    caption_zone = custom_left - 20

    rows_without = _ink_rows(without, band_top + 1, without.height, 0, caption_zone)
    rows_centred = _ink_rows(centred, band_top + 1, centred.height, 0, caption_zone)
    assert rows_without, "no EXIF caption ink found"
    assert (min(rows_without), max(rows_without)) == (min(rows_centred), max(rows_centred)), (
        f"EXIF caption moved: rows {min(rows_without)}-{max(rows_without)} without custom "
        f"text vs {min(rows_centred)}-{max(rows_centred)} with it centred")


def test_centred_custom_text_sits_at_the_band_centre(source_png, tmp_path):
    """...and the custom text is at the band's vertical centre, not near the floor.

    The other half of the reported bug: as a fourth line the custom text landed at
    row 441 of a 642px band, below the palette (which ends at 428), reading as
    detached and too low.
    """
    img = _render(source_png, tmp_path, BorderType.POLAROID, centered=True, add_palette=True)
    band_top, band, _ = _band_geometry(img, BorderType.POLAROID)
    _, _, top, bottom = _custom_ink_box(img, BorderType.POLAROID, _palette_left(img, BorderType.POLAROID))
    ink_mid = ((top + bottom) / 2) - band_top
    assert abs(ink_mid - band / 2) <= 0.08 * band, (
        f"custom ink centred at {ink_mid:.0f} of a {band}px band, expected ~{band / 2:.0f}")


def test_polaroid_exif_stays_left_when_custom_text_is_centred(source_png, tmp_path):
    """Centring the custom line must not drag the EXIF stack with it.

    This is the whole point of the option on polaroid: a left-aligned technical
    caption with a centred signature beside it.
    """
    img = _render(source_png, tmp_path, BorderType.POLAROID, centered=True,
                  size_mult=1.5, add_palette=True)
    band_top, band, border = _band_geometry(img, BorderType.POLAROID)
    pal = _palette_left(img, BorderType.POLAROID)
    custom_left, custom_right, _, _ = _custom_ink_box(img, BorderType.POLAROID, pal)

    # The EXIF caption still starts at border.left and stays clear of the custom text.
    exif_cols = _ink_cols(img, band_top + 1, img.height, 0, custom_left - 20)
    assert exif_cols, "no EXIF caption ink found"
    assert min(exif_cols) < border.left + 0.02 * img.width, "EXIF is no longer left-aligned"
    assert max(exif_cols) < custom_left, "EXIF caption runs into the centred custom text"
    assert custom_right < pal, "centred custom text runs into the palette"


def test_large_falls_back_to_a_fourth_line(source_png, tmp_path):
    """LARGE centres its own caption, so the centre slot is taken.

    The placement decision is an overlap test rather than a per-type rule, so this
    is what proves the test actually discriminates: on LARGE it must fail and send
    the custom text back to a fourth stacked line.
    """
    img = _render(source_png, tmp_path, BorderType.LARGE, centered=True, add_palette=True)
    band_top, band, _ = _band_geometry(img, BorderType.LARGE)
    clusters = _clusters(_ink_rows(img, band_top + 1, img.height))
    assert len(clusters) == 4, (
        f"expected 4 stacked lines on LARGE, found {len(clusters)}: {clusters}")


@pytest.mark.parametrize("border_type", ROW_TYPES)
def test_centering_is_ignored_on_row_layouts_with_exif(source_png, tmp_path, border_type):
    """SMALL/MEDIUM + EXIF on: the flag is a no-op, byte for byte.

    The custom text is a segment of the single EXIF row there, so honouring the
    flag would draw it on top of the caption. It must be ignored - and ignored
    without also changing the text's SIZE, which is why `core` decides the
    effective flag before picking the width budget rather than leaving it to
    `border.draw_exif`.
    """
    plain = _render(source_png, tmp_path, border_type, centered=False, size_mult=1.5)
    centred = _render(source_png, tmp_path, border_type, centered=True, size_mult=1.5)
    assert list(plain.getdata()) == list(centred.getdata()), (
        f"{border_type.name}: --text-center changed the output despite being unhonourable")


@pytest.mark.parametrize("border_type", ROW_TYPES)
def test_centering_is_honoured_on_row_layouts_without_exif(source_png, tmp_path, border_type):
    """SMALL/MEDIUM + EXIF off: the band is empty, so centring is honoured."""
    img = _render(source_png, tmp_path, border_type, add_exif=False, centered=True)
    top, bottom = _custom_line_band(img, border_type)
    cols = _ink_cols(img, top, bottom + 1)
    mid_ink = (min(cols) + max(cols)) / 2
    slack = max(4, 0.01 * img.width)
    assert abs(mid_ink - img.width / 2) <= slack, (
        f"{border_type.name}: expected a centred line with EXIF off, got centre {mid_ink:.0f}")


@pytest.mark.parametrize("border_type", STACKED)
def test_long_centred_text_never_reaches_the_palette(source_png, tmp_path, border_type):
    """A centred line must clear the palette on BOTH sides.

    Regression guard for a real bug: a centred line of width W spans
    (canvas - W)/2 to (canvas + W)/2, so it reaches further right than a
    left-anchored line of the same W. LARGE previously gave the custom text the
    photo's width as its budget, which for a long enough string would have centred
    it straight across the palette. The budget for a centred line has to be
    2 * right_bound - canvas_width, not the left-anchored one.
    """
    long_text = "Gábor Fauszt · Stormchaser Photography · Budapest · MMXXVI · all rights reserved"
    img = _render(source_png, tmp_path, border_type, add_palette=True,
                  custom_text=long_text, size_mult=3.0, centered=True)
    band_top, band, border = _band_geometry(img, border_type)

    palette_size = round(band / 3)
    margin = round(palette_size / 2)
    palette_left = border.left + 1800 - palette_size - margin

    top, bottom = _custom_line_band(img, border_type)
    cols = _ink_cols(img, top, bottom + 1)
    assert cols, "no ink on the custom line"
    assert max(cols) < palette_left, (
        f"{border_type.name}: centred text reaches column {max(cols)}, palette starts at "
        f"{palette_left}")
    assert min(cols) >= border.left, (
        f"{border_type.name}: centred text starts at column {min(cols)}, left border ends at "
        f"{border.left}")
