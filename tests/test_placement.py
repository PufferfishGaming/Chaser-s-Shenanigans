"""
Placement tests: per-element anchor, vertical position and size multiplier.

The guarantee that matters most here is the negative one - that a DEFAULT
placement changes nothing at all. `layout.resolve_offset` returns a literal
(0.0, 0.0) for a default placement rather than recomputing a position that ought
to come out the same, and these tests pin that down pixel for pixel. The wider
proof is a 512-render matrix compared against pre-refactor hashes; this file
keeps a representative slice of it in the suite.

Everything else is checked by where the ink actually lands. Ink is separated from
the photograph and the palette by chroma: the caption is neutral grey, while the
synthetic photo and the swatches rendered from it are saturated.
"""
import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fontcatalog                                        # noqa: E402
from border import BorderType, create_border              # noqa: E402
from core import process_image                            # noqa: E402
from layout import Placement, default_placements, resolve_offset  # noqa: E402

FONTDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
PHOTO = (200, 30, 30)
SRC_W, SRC_H = 1800, 1200
TEXT = "Stormchaser"


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    d = tmp_path_factory.mktemp("src")
    p = os.path.join(str(d), "s.png")
    img = Image.new("RGB", (SRC_W, SRC_H), PHOTO)
    exif = Image.Exif()
    exif[0x010F] = "SONY"
    exif[0x0110] = "ILCE-7M4"
    exif.get_ifd(0x8769).update({
        0x829D: 2.8, 0x920A: 70.0, 0x8827: 2000, 0x829A: 0.025,
        0xA433: "Sigma", 0xA434: "24-70mm F2.8 DG DN II",
    })
    img.save(p, exif=exif)
    return p


def _render(source, out_dir, *, border_type=BorderType.POLAROID, add_exif=True,
            add_palette=True, custom_text=TEXT, placements=None, centered=False):
    out = process_image(
        path=source, add_exif=add_exif, add_palette=add_palette, border_type=border_type,
        font=fontcatalog.spec("ebgaramond"), boldfont=fontcatalog.spec("ebgaramond", bold=True),
        fontdir=FONTDIR, output_root=str(out_dir), input_root=os.path.dirname(source),
        custom_text=custom_text,
        custom_font=fontcatalog.spec("greatvibes") if custom_text else None,
        custom_centered=centered, placements=placements,
    )
    return Image.open(out)


def _band(img, border_type):
    border = create_border(SRC_W, SRC_H, border_type)
    band = border.caption_band or border.bottom
    return img.height - band, band, border


def _ink(img, border_type, *, neutral=True):
    """Bounding box of caption ink (neutral) or palette ink (saturated) in the band."""
    band_top, band, _ = _band(img, border_type)
    px = img.load()
    cols, rows = [], []
    for y in range(band_top + 1, img.height):
        for x in range(img.width):
            r, g, b = px[x, y]
            chroma = max(r, g, b) - min(r, g, b)
            hit = (max(r, g, b) < 250 and chroma <= 12) if neutral else (chroma > 40)
            if hit:
                cols.append(x)
                rows.append(y)
    assert cols, "no ink found in the caption band"
    return min(cols), min(rows), max(cols), max(rows)


# ---------------------------------------------------------------------------
# The negative guarantee
# ---------------------------------------------------------------------------
def test_default_placement_is_a_literal_no_op():
    """A default placement resolves to a zero offset, not a recomputed position.

    The palette's default sits half a swatch in from the photo's edge, which is
    NOT the same as flush right - so a default that recomputed "right anchor"
    would silently shift it. Hence the identity.
    """
    box, region = (100, 500, 400, 560), (100, 400, 1700, 700)
    for anchor in (None, "right"):
        assert resolve_offset(box, region, Placement(anchor=anchor), "right", 1800) == (0.0, 0.0)


@pytest.mark.parametrize("border_type", list(BorderType))
@pytest.mark.parametrize("centered", [False, True])
def test_passing_default_placements_changes_nothing(source, tmp_path, border_type, centered):
    """Explicit all-default placements must be byte-identical to passing none."""
    a = _render(source, tmp_path / "a", border_type=border_type, centered=centered)
    b = _render(source, tmp_path / "b", border_type=border_type, centered=centered,
                placements=default_placements())
    assert list(a.getdata()) == list(b.getdata())


# ---------------------------------------------------------------------------
# Horizontal anchors
# ---------------------------------------------------------------------------
def test_exif_anchor_moves_the_caption_horizontally(source, tmp_path):
    """Rendered without custom text, so the measured ink is the EXIF block alone.

    With the custom text present its own (still default, left-aligned) ink pins
    the measured left edge at `border.left` no matter where the EXIF block goes -
    which is a property of the measurement, not of the placement.
    """
    def x0(anchor):
        img = _render(source, tmp_path / f"a{anchor}", custom_text=None,
                      placements={"exif": Placement(anchor=anchor)})
        return _ink(img, BorderType.POLAROID)[0]

    left, centre, right = x0("left"), x0("center"), x0("right")
    assert left < centre < right, (left, centre, right)


def test_text_anchor_moves_the_custom_text_independently(source, tmp_path):
    """Anchoring the custom text must move only it, not the EXIF caption.

    Measured on the block's stable edges rather than by sampling a column range:
    the custom text sits at `border.left` by default, so ANY column window that
    contains the EXIF caption also contains the custom text, and the two cannot
    be separated that way.

    Unchanged: the topmost ink row (the EXIF heading) and the leftmost ink column
    (the EXIF lines, which stay left-aligned). Changed: the rightmost ink column,
    because the custom text has gone right.
    """
    ref = _ink(_render(source, tmp_path / "ref"), BorderType.POLAROID)
    moved = _ink(_render(source, tmp_path / "mv",
                         placements={"text": Placement(anchor="right")}), BorderType.POLAROID)

    assert ref[1] == moved[1], "the EXIF caption's top edge moved"
    assert ref[0] == moved[0], "the EXIF caption's left edge moved"
    assert moved[2] > ref[2], "the custom text did not move right"


def test_palette_anchor_left_puts_it_at_the_photo_edge(source, tmp_path):
    img = _render(source, tmp_path / "o",
                  placements={"palette": Placement(anchor="left")})
    x0, _, _, _ = _ink(img, BorderType.POLAROID, neutral=False)
    _, _, border = _band(img, BorderType.POLAROID)
    assert abs(x0 - border.left) <= 2, f"palette starts at {x0}, photo edge is {border.left}"


@pytest.mark.parametrize("palette_placement", [
    Placement(anchor="left"),
    Placement(anchor="center"),
    Placement(x=0.45, y=0.5),
    Placement(x=0.20, y=0.5),
])
def test_a_moved_palette_does_not_resize_the_caption(source, tmp_path, palette_placement):
    """A hand-placed palette leaves the automatic sizing negotiation entirely.

    This is the second half of "allow overlap", and the half that is easy to miss
    because it is not positional. With the palette still constraining the width
    budget, the caption was made to dodge it by SHRINKING rather than moving:
    dragging the palette towards the middle squeezed the caption from 110x35 to
    75x24 px. Quietly resizing someone's caption to avoid a collision is still
    preventing the overlap they asked for.

    The earlier version of this test only checked the caption had not collapsed to
    less than 90% of its height, which the shrink slipped straight past.
    """
    ref = _boxes(source, tmp_path / "ref")["exif"]
    got = _boxes(source, tmp_path / "moved", {"palette": palette_placement})["exif"]
    ref_w, got_w = ref[2] - ref[0], got[2] - got[0]
    ref_h, got_h = ref[3] - ref[1], got[3] - got[1]
    assert abs(got_w - ref_w) <= 1, f"caption width changed: {ref_w} -> {got_w}"
    assert abs(got_h - ref_h) <= 1, f"caption height changed: {ref_h} -> {got_h}"


def test_a_bigger_palette_in_its_default_place_still_pushes_the_caption(source, tmp_path):
    """A size change is not a move.

    A larger palette still sitting in its default corner is still an obstacle the
    automatic layout should route around, so the auto-fit has to keep applying.
    """
    narrow = _boxes(source, tmp_path / "big",
                    {"palette": Placement(size_mult=3.0)})
    assert not _overlaps(narrow["exif"], narrow["palette"]), (
        "a default-placed palette should still be avoided, however large")


# ---------------------------------------------------------------------------
# Vertical position
# ---------------------------------------------------------------------------
def test_vertical_position_moves_the_element(source, tmp_path):
    high = _ink(_render(source, tmp_path / "h",
                        placements={"exif": Placement(y=0.05)}), BorderType.POLAROID)
    low = _ink(_render(source, tmp_path / "l",
                       placements={"exif": Placement(y=0.95)}), BorderType.POLAROID)
    assert high[1] < low[1], (high[1], low[1])


@pytest.mark.parametrize("y", [-0.5, 0.0, 0.5, 1.0, 1.5])
def test_elements_stay_inside_the_caption_band(source, tmp_path, y):
    """Bounds are the band by choice, so no placement may escape it.

    Every font size and the palette size derive from the band height; an element
    outside it would have no size reference.
    """
    img = _render(source, tmp_path / f"y{y}",
                  placements={"exif": Placement(y=y), "text": Placement(y=y),
                              "palette": Placement(y=y)})
    band_top, band, _ = _band(img, BorderType.POLAROID)
    x0, y0, x1, y1 = _ink(img, BorderType.POLAROID)
    assert y0 >= band_top, f"ink at row {y0} is above the band top {band_top}"
    assert y1 < img.height, "ink runs off the bottom of the canvas"


# ---------------------------------------------------------------------------
# Size multipliers
# ---------------------------------------------------------------------------
def test_exif_size_multiplier_changes_the_caption_height(source, tmp_path):
    small = _ink(_render(source, tmp_path / "s", custom_text=None,
                         placements={"exif": Placement(size_mult=1.0)}), BorderType.POLAROID)
    big = _ink(_render(source, tmp_path / "b", custom_text=None,
                       placements={"exif": Placement(size_mult=2.0)}), BorderType.POLAROID)
    assert (big[3] - big[1]) > (small[3] - small[1]) * 1.2


def test_palette_size_multiplier_changes_the_swatches(source, tmp_path):
    small = _ink(_render(source, tmp_path / "s",
                         placements={"palette": Placement(size_mult=1.0)}),
                 BorderType.POLAROID, neutral=False)
    big = _ink(_render(source, tmp_path / "b",
                       placements={"palette": Placement(size_mult=2.0)}),
               BorderType.POLAROID, neutral=False)
    assert (big[3] - big[1]) > (small[3] - small[1]) * 1.4


def test_size_multiplier_is_resolution_independent(source, tmp_path):
    """The multiplier scales a fraction of the band, not an absolute pixel size.

    So the caption occupies the same proportion of the band whatever the export
    resolution - which is the whole reason sizes are band-derived in this
    pipeline.
    """
    ratios = []
    for w, h in [(1800, 1200), (3600, 2400)]:
        p = str(tmp_path / f"src{w}.png")
        img = Image.new("RGB", (w, h), PHOTO)
        exif = Image.Exif()
        exif[0x010F] = "SONY"
        exif[0x0110] = "ILCE-7M4"
        exif.get_ifd(0x8769).update({0x829D: 2.8, 0x920A: 70.0, 0x8827: 2000,
                                     0x829A: 0.025, 0xA433: "Sigma", 0xA434: "24-70mm"})
        img.save(p, exif=exif)
        out = process_image(
            path=p, add_exif=True, add_palette=False, border_type=BorderType.POLAROID,
            font=fontcatalog.spec("ebgaramond"), boldfont=fontcatalog.spec("ebgaramond", bold=True),
            fontdir=FONTDIR, output_root=str(tmp_path / f"o{w}"), input_root=str(tmp_path),
            custom_text=None, placements={"exif": Placement(size_mult=1.5)},
        )
        rendered = Image.open(out)
        border = create_border(w, h, BorderType.POLAROID)
        band = border.caption_band or border.bottom
        band_top = rendered.height - band
        px = rendered.load()
        rows = [y for y in range(band_top + 1, rendered.height)
                for x in range(0, rendered.width, 5)
                if max(px[x, y]) < 250 and (max(px[x, y]) - min(px[x, y])) <= 12]
        ratios.append((max(rows) - min(rows)) / band)
    assert abs(ratios[0] - ratios[1]) < 0.03, f"caption/band ratio drifted with resolution: {ratios}"


# ---------------------------------------------------------------------------
# Snap back
# ---------------------------------------------------------------------------
def test_snapped_drops_the_hand_placed_position(source, tmp_path):
    moved = Placement(anchor="right", x=0.7, y=0.2, size_mult=1.5)
    assert moved.moved is True
    snapped = moved.snapped()
    assert snapped.moved is False
    assert snapped.size_mult == 1.5, "snapping back must keep the size, only drop the position"
    assert snapped.anchor is None


def test_snapping_back_restores_the_default_render(source, tmp_path):
    reference = _render(source, tmp_path / "ref")
    snapped = _render(source, tmp_path / "snap",
                      placements={"exif": Placement(anchor="right", x=0.7, y=0.2).snapped()})
    assert list(reference.getdata()) == list(snapped.getdata())


# ---------------------------------------------------------------------------
# Alignment presets vs a hand-placed position
# ---------------------------------------------------------------------------
def test_choosing_an_alignment_discards_a_hand_placed_x():
    """`realigned` must clear x, keep y and the size.

    Regression test for the reported bug. `resolve_offset` gives a stored x
    priority over the anchor, so after a drag the presets did nothing useful -
    the same stored fraction was just re-read against a different edge of the
    box, which made Left a no-op and slid both Centre and Right to the frame's
    left edge. Only elements that had never been dragged appeared to work.
    """
    dragged = Placement(anchor="left", x=0.42, y=0.7, size_mult=1.5, line_align="right")
    out = dragged.realigned("right")
    assert out.x is None, "the hand-placed x survived an alignment choice"
    assert out.anchor == "right"
    assert out.y == 0.7, "a horizontal alignment must not change the height"
    assert out.size_mult == 1.5
    assert out.line_align == "right"


@pytest.mark.parametrize("anchor", ["left", "center", "right"])
def test_alignments_are_ordered_after_a_drag(source, tmp_path, anchor):
    """Left < Centre < Right, even starting from a dragged position."""
    positions = {}
    for a in ("left", "center", "right"):
        dragged = Placement(x=0.42, y=0.5)
        img = _render(source, tmp_path / f"a{a}", custom_text=None,
                      placements={"exif": dragged.realigned(a)})
        positions[a] = _ink(img, BorderType.POLAROID)[0]
    assert positions["left"] < positions["center"] < positions["right"], positions


def test_explicit_default_anchor_matches_unset(source, tmp_path):
    """Selecting the alignment an element already uses must change nothing.

    This is what allows the "Default" entry to be dropped from the combo in
    favour of preselecting the real alignment. The palette is the case that would
    break loudly: its default sits half a swatch in from the photo's edge, not
    flush against it, so a "Right" that recomputed the position would visibly
    shift it.
    """
    import layout as layout_mod
    for border_type in BorderType:
        unset = _render(source, tmp_path / f"u{border_type.name}", border_type=border_type)
        explicit = {name: Placement(anchor=layout_mod.default_anchor(name, border_type.name))
                    for name in layout_mod.ELEMENTS}
        chosen = _render(source, tmp_path / f"e{border_type.name}", border_type=border_type,
                         placements=explicit)
        assert list(unset.getdata()) == list(chosen.getdata()), border_type.name


# ---------------------------------------------------------------------------
# Line alignment inside the EXIF block
# ---------------------------------------------------------------------------
def _line_lefts(img, border_type):
    """Left ink column of each text line in the band, top to bottom."""
    band_top, band, _ = _band(img, border_type)
    px = img.load()
    rows = []
    for y in range(band_top + 1, img.height):
        xs = [x for x in range(img.width)
              if max(px[x, y]) < 250 and (max(px[x, y]) - min(px[x, y])) <= 12]
        rows.append((y, min(xs) if xs else None))
    # Cluster into lines and take each line's leftmost ink.
    lines, run = [], []
    for y, left in rows:
        if left is None:
            if run:
                lines.append(min(run))
                run = []
        else:
            run.append(left)
    if run:
        lines.append(min(run))
    return lines


def test_line_alignment_changes_the_ragged_edge(source, tmp_path):
    """The lines' own alignment is independent of where the block sits.

    The block's bounding box is identical for all three settings - the widest
    line still spans the full width - so this has to be measured from the
    NARROWER lines' left edges, not from the block box.
    """
    lefts = {}
    for la in ("left", "center", "right"):
        img = _render(source, tmp_path / f"l{la}", custom_text=None, add_palette=False,
                      placements={"exif": Placement(line_align=la)})
        lefts[la] = _line_lefts(img, BorderType.POLAROID)

    for la, got in lefts.items():
        assert len(got) >= 2, f"{la}: expected several caption lines, got {got}"
    # Left-aligned: every line starts at the same column. Right-aligned: they do not.
    assert max(lefts["left"]) - min(lefts["left"]) <= 2, lefts["left"]
    assert max(lefts["right"]) - min(lefts["right"]) > 5, lefts["right"]
    assert max(lefts["center"]) - min(lefts["center"]) > 2, lefts["center"]


def test_line_alignment_default_is_unchanged(source, tmp_path):
    """None must reproduce each border type's existing look exactly."""
    import layout as layout_mod
    for border_type in BorderType:
        base = _render(source, tmp_path / f"b{border_type.name}", border_type=border_type)
        explicit = _render(
            source, tmp_path / f"x{border_type.name}", border_type=border_type,
            placements={"exif": Placement(
                line_align=layout_mod.default_line_align("exif", border_type.name))})
        assert list(base.getdata()) == list(explicit.getdata()), border_type.name


# ---------------------------------------------------------------------------
# Overlap
# ---------------------------------------------------------------------------
def _boxes(source, out_dir, placements=None, border_type=BorderType.POLAROID):
    geometry = {}
    process_image(
        path=source, add_exif=True, add_palette=True, border_type=border_type,
        font=fontcatalog.spec("ebgaramond"), boldfont=fontcatalog.spec("ebgaramond", bold=True),
        fontdir=FONTDIR, output_root=str(out_dir), input_root=os.path.dirname(source),
        custom_text=TEXT, custom_font=fontcatalog.spec("greatvibes"),
        placements=placements, geometry_out=geometry,
    )
    return geometry["boxes"]


def _overlaps(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def test_elements_may_overlap_when_asked_to(source, tmp_path):
    """Anchoring the caption where the palette already is must be honoured.

    An earlier version carved the palette out of the region an anchored text
    element could occupy, so "Right" meant "as far right as it fits BESIDE the
    palette" - which made "caption right, palette right" impossible to ask for.
    Choosing an alignment is the user stating a position, same as a drag.
    """
    boxes = _boxes(source, tmp_path / "ov",
                   {"exif": Placement(anchor="right"), "palette": Placement(anchor="right")})
    assert _overlaps(boxes["exif"], boxes["palette"]), (
        f"expected an overlap; exif={boxes['exif']} palette={boxes['palette']}")


def test_default_layout_still_avoids_overlap(source, tmp_path):
    """Allowing overlap must not make it the default.

    An element left alone is still auto-fitted around the palette; only an
    explicit choice is taken literally.
    """
    boxes = _boxes(source, tmp_path / "def")
    assert not _overlaps(boxes["exif"], boxes["palette"]), boxes
    assert not _overlaps(boxes["text"], boxes["palette"]), boxes


def test_explicit_alignments_are_honoured_exactly(source, tmp_path):
    """Placing the palette elsewhere must not drag the caption's anchor with it."""
    boxes = _boxes(source, tmp_path / "mix",
                   {"exif": Placement(anchor="right"), "palette": Placement(anchor="center")})
    band = (boxes["exif"], boxes["palette"])
    assert not _overlaps(*band), band
    # The caption really is at the right-hand end, not tucked beside the palette.
    assert boxes["exif"][0] > boxes["palette"][2], band


# ---------------------------------------------------------------------------
# Dragging an element that has been re-aligned
# ---------------------------------------------------------------------------
def test_geometry_reports_the_effective_anchor_not_the_default(source, tmp_path):
    """`geometry_out["anchors"]` must reflect the user's choice.

    The GUI records a dragged position as a fraction of canvas width measured at
    the element's ANCHOR edge, and `resolve_offset` reads it back the same way -
    so both must agree on which edge that is. An earlier version reported only the
    per-type defaults under the name `default_anchors`, and the GUI used it as
    though it were the effective anchor.
    """
    for anchor in ("left", "center", "right"):
        geometry = {}
        process_image(
            path=source, add_exif=True, add_palette=True, border_type=BorderType.POLAROID,
            font=fontcatalog.spec("ebgaramond"),
            boldfont=fontcatalog.spec("ebgaramond", bold=True), fontdir=FONTDIR,
            output_root=str(tmp_path / f"a{anchor}"), input_root=os.path.dirname(source),
            custom_text=TEXT, custom_font=fontcatalog.spec("greatvibes"),
            placements={"exif": Placement(anchor=anchor)}, geometry_out=geometry,
        )
        assert geometry["anchors"]["exif"] == anchor, geometry["anchors"]


@pytest.mark.parametrize("element", ["exif", "text", "palette"])
@pytest.mark.parametrize("anchor", ["left", "center", "right"])
def test_a_drag_lands_where_asked_whatever_the_alignment(source, tmp_path, element, anchor):
    """Round-trip a drag through `fraction_from_offset` and back.

    Regression test for a mismatch between the edge a drag was recorded against
    and the edge it was resolved against: measured 55px off for a centred element
    and 110px off IN THE OPPOSITE DIRECTION for a right-aligned one.

    Offsets are sized to the room actually available inside the caption band, so
    that the band clamp - which is a deliberate bound, not the thing under test -
    never decides the result.
    """
    from layout import fraction_from_offset

    def render(placements):
        geometry = {}
        process_image(
            path=source, add_exif=True, add_palette=True, border_type=BorderType.POLAROID,
            font=fontcatalog.spec("ebgaramond"),
            boldfont=fontcatalog.spec("ebgaramond", bold=True), fontdir=FONTDIR,
            output_root=str(tmp_path / "r"), input_root=os.path.dirname(source),
            custom_text=TEXT, custom_font=fontcatalog.spec("greatvibes"),
            placements=placements, geometry_out=geometry,
        )
        return geometry

    start = render({element: Placement(anchor=anchor)})
    box, band, canvas = start["boxes"][element], start["band"], start["canvas"]
    effective = start["anchors"][element]

    room_right, room_left = band[2] - box[2], box[0] - band[0]
    room_down, room_up = band[3] - box[3], box[1] - band[1]
    moves = [
        (min(60, room_right - 2), 0),
        (-min(45, room_left - 2), 0),
        (0, min(20, room_down - 2)),
        (min(30, room_right - 2), -min(15, room_up - 2)),
    ]
    for dx, dy in moves:
        x, y = fraction_from_offset(box, band, dx, dy, effective, canvas[0])
        got = render({element: Placement(anchor=anchor, x=x, y=y)})["boxes"][element]
        assert abs((got[0] - box[0]) - dx) < 3, (
            f"{element}/{anchor}: asked dx={dx}, moved {got[0] - box[0]:+.0f}")
        assert abs((got[1] - box[1]) - dy) < 3, (
            f"{element}/{anchor}: asked dy={dy}, moved {got[1] - box[1]:+.0f}")


def test_placing_by_hand_keeps_every_other_setting():
    """A drag must not reset the alignment, line alignment or size.

    `Placement.placed` is built on `replace` for exactly this reason: the drag
    handlers used to construct a fresh Placement and silently dropped whatever
    they forgot to copy, which reset the EXIF block's line alignment on every
    drag.
    """
    before = Placement(anchor="right", line_align="center", size_mult=1.4, y=0.3)
    after = before.placed(0.62, 0.55)
    assert after.anchor == "right"
    assert after.line_align == "center"
    assert after.size_mult == 1.4
    assert (after.x, after.y) == (0.62, 0.55)
