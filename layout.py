"""
Placement model for the three caption-band elements.

The three things drawn on the bottom border - the EXIF caption, the custom text
and the colour palette - each get a `Placement`: a horizontal anchor, an optional
dragged position, an optional vertical position, and a size multiplier.

Design note, because it is the reason this is small rather than a rewrite
-----------------------------------------------------------------------
`border.draw_exif` carries ~290 lines of interdependent sizing and clamping:
width budgets computed from the palette's position, four-line block centring,
two-sided baseline clamps, a shrink-to-fit loop for the SMALL/MEDIUM row. None of
that is re-derived here. Instead the default layout is computed exactly as
before, each element's resulting box is measured, and a placement becomes a
**translation** of that box.

Two things follow from that, both wanted:

  * Defaults are byte-identical to the previous behaviour, because a default
    placement resolves to a zero offset - not to a recomputed position that
    merely ought to match.
  * "Auto-fit until you move it" falls out for free. The width budgets are
    computed once, on the default layout, so an element that has been moved keeps
    the size it was given and is simply relocated; it is not re-shrunk against
    its new neighbours. An element left alone keeps the full automatic behaviour.

Coordinates are stored as FRACTIONS, never pixels: every size in this pipeline is
derived from the band height so that a layout looks identical at 12MP and 60MP,
and pixel offsets would break that the moment the export resolution changed.
`x` is a fraction of canvas width, `y` a fraction of the band height.
"""
import math
from dataclasses import dataclass, replace
from typing import Optional, Tuple

# Order matters only for display; the palette is laid out first in the pipeline
# because it is the obstacle the text budgets are computed against.
ELEMENTS = ("exif", "text", "palette")

ELEMENT_LABELS = {
    "exif": "EXIF caption",
    "text": "Custom text",
    "palette": "Colour palette",
}

# Short forms for the placement grid's row labels. Taking the first word of the
# long label instead gave "EXIF / Custom / Colour", where "Colour" reads as a
# colour setting rather than as the palette.
ELEMENT_SHORT_LABELS = {
    "exif": "EXIF",
    "text": "Text",
    "palette": "Palette",
}

ANCHORS = ("left", "center", "right")

# No "Default" entry. It was a meta-value sitting next to the three real ones and
# duplicating whichever of them the element already used, so the combo showed
# "Default" for something that was plainly left-aligned. The element's own default
# is preselected instead, and selecting it explicitly is verified to be
# byte-identical to leaving it unset (see `default_anchor`).
ANCHOR_LABELS = [
    ("Left", "left"),
    ("Centre", "center"),
    ("Right", "right"),
]

# How the EXIF caption's lines align WITH EACH OTHER, which is separate from
# where the block as a whole sits. Previously implicit and fixed per border type:
# POLAROID/SMALL/MEDIUM left-aligned the lines, LARGE centred each one.
LINE_ALIGNS = ("left", "center", "right")

LINE_ALIGN_LABELS = [
    ("Left", "left"),
    ("Centre", "center"),
    ("Right", "right"),
]

LINE_ALIGN_FACTORS = {"left": 0.0, "center": 0.5, "right": 1.0}


def default_anchor(element: str, border_type_name: str) -> str:
    """The anchor an element uses when the user has not chosen one.

    Kept here rather than in `core` so the GUI can preselect the same value the
    pipeline would have used, instead of showing a separate "Default" entry.

    Selecting the returned value explicitly produces byte-identical output to
    leaving `anchor` as None - `resolve_offset` treats an anchor equal to the
    default as an identity, and that equivalence is asserted for all twelve
    element/border combinations in the test suite. Without that property the
    palette would visibly jump when "Right" was selected, because its default
    sits half a swatch in from the photo's edge rather than flush against it.
    """
    if element == "palette":
        return "right"
    return "center" if border_type_name == "LARGE" else "left"


def default_line_align(element: str, border_type_name: str) -> str:
    """The EXIF block's line alignment before the user changes it."""
    return "center" if border_type_name == "LARGE" else "left"


@dataclass(frozen=True)
class Placement:
    """Where one element goes, and how big it is.

    Attributes:
        anchor:    "left" | "center" | "right", or None for the border type's own
                   default. A placement whose anchor is None or equal to the
                   default resolves to a zero horizontal offset - so "default"
                   means "exactly as before", not "recomputed to the left edge".
                   That distinction is what keeps existing output identical: the
                   palette's default sits half a swatch in from the photo edge,
                   which is not the same as flush right.
        x:         Fraction of canvas width for the element's anchor edge (its
                   left edge when anchored left, its centre when centred, its
                   right edge when anchored right). Set by dragging. None means
                   "use the anchor".
        y:         Fraction of band height for the element's vertical centre,
                   0 at the top of the caption band and 1 at the bottom. None
                   means the default vertical position.
        size_mult: Multiplier on the element's automatic size. For the two text
                   elements this scales the band-derived font size; for the
                   palette it scales the swatch size.
        line_align: For the EXIF caption only: how its three lines align with each
                   other, independently of where the block sits. None follows the
                   border type's default. Meaningless for the palette, and for the
                   custom text and the SMALL/MEDIUM caption, which are single
                   lines.
    """
    anchor: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    size_mult: float = 1.0
    line_align: Optional[str] = None

    @property
    def moved(self) -> bool:
        """True once the element has been positioned by hand.

        This is the switch for the hybrid auto-fit rule: a moved element keeps
        the size the automatic pass gave it and is relocated, rather than being
        re-fitted against whatever it now sits next to.
        """
        return self.x is not None or self.y is not None

    @property
    def is_default(self) -> bool:
        return (self.anchor is None and self.x is None and self.y is None
                and self.size_mult == 1.0 and self.line_align is None)

    def snapped(self, anchor: Optional[str] = None) -> "Placement":
        """Drop the dragged position, keeping the size. The snap-back operation."""
        return replace(self, anchor=anchor, x=None, y=None)

    def placed(self, x: Optional[float], y: Optional[float]) -> "Placement":
        """Record a hand-placed position, keeping every other field.

        Built on `replace` rather than by constructing a fresh Placement: the
        latter silently dropped whatever fields the caller forgot, which is how a
        drag came to reset the EXIF block's line alignment.
        """
        return replace(self, x=x, y=y)

    def realigned(self, anchor: Optional[str]) -> "Placement":
        """Apply a horizontal alignment, discarding any hand-placed x.

        Choosing an alignment has to clear `x`, because `resolve_offset` gives a
        stored x priority over the anchor. Without this, picking an alignment
        after dragging did nothing useful: the same stored fraction was simply
        re-read against a different edge of the box, so "Left" was a no-op and
        "Centre" and "Right" both slid the block to the frame's left edge. That is
        what made the presets look broken for every element the user had dragged.

        `y` is kept: a horizontal alignment says nothing about height.
        """
        return replace(self, anchor=anchor, x=None)

    def to_dict(self) -> dict:
        return {"anchor": self.anchor, "x": self.x, "y": self.y,
                "size_mult": self.size_mult, "line_align": self.line_align}

    @classmethod
    def from_dict(cls, data) -> "Placement":
        """Rebuild from stored settings, tolerating anything.

        Settings are never load-bearing in this suite, so a corrupt or
        hand-edited value degrades to the default placement rather than raising
        part-way through a batch.
        """
        if not isinstance(data, dict):
            return cls()

        def frac(key):
            v = data.get(key)
            try:
                v = float(v)
            except (TypeError, ValueError):
                return None
            # NaN and infinity have to be rejected explicitly. float("nan")
            # PARSES, and every comparison against it is False, so it slips
            # through min/max clamping unchanged in one direction and silently
            # becomes a bound in the other - "nan" was landing as -0.5.
            if not math.isfinite(v):
                return None
            # Allow a little overshoot so a drag that ends just past the edge is
            # clamped later rather than discarded here.
            return min(1.5, max(-0.5, v))

        anchor = data.get("anchor")
        if anchor not in ANCHORS:
            anchor = None
        try:
            size = float(data.get("size_mult", 1.0))
        except (TypeError, ValueError):
            size = 1.0
        if not math.isfinite(size):
            size = 1.0
        line_align = data.get("line_align")
        if line_align not in LINE_ALIGNS:
            line_align = None
        return cls(anchor=anchor, x=frac("x"), y=frac("y"),
                   size_mult=min(3.0, max(0.25, size)), line_align=line_align)


def replace_line_align(placement: "Placement", line_align: Optional[str]) -> "Placement":
    """Set a placement's line alignment, leaving everything else alone."""
    return replace(placement, line_align=line_align)


def default_placements() -> dict:
    return {name: Placement() for name in ELEMENTS}


def placements_from_settings(raw) -> dict:
    if not isinstance(raw, dict):
        return default_placements()
    return {name: Placement.from_dict(raw.get(name)) for name in ELEMENTS}


def placements_to_settings(placements: dict) -> dict:
    return {name: placements.get(name, Placement()).to_dict() for name in ELEMENTS}


def anchor_point(box: Tuple[float, float, float, float], anchor: str) -> float:
    """The x coordinate an anchor refers to on a box (x0, y0, x1, y1)."""
    x0, _, x1, _ = box
    if anchor == "right":
        return x1
    if anchor == "center":
        return (x0 + x1) / 2.0
    return x0


def resolve_offset(box, region, placement: Placement, default_anchor: str,
                   canvas_width: int) -> Tuple[float, float]:
    """Translation to apply to `box` for this placement.

    Args:
        box: (x0, y0, x1, y1) of the element as the automatic layout placed it.
        region: (left, top, right, bottom) the element must stay inside - the
                caption band, horizontally bounded by the photograph's edges.
        placement: The requested placement.
        default_anchor: The border type's own anchor for this element.
        canvas_width: Used to turn the stored `x` fraction into pixels.

    Returns:
        (dx, dy) in pixels, already clamped so the box stays inside `region`.
        (0.0, 0.0) for a default placement - see the class docstring for why that
        is an identity rather than a recomputation.
    """
    x0, y0, x1, y1 = box
    r_left, r_top, r_right, r_bottom = region
    anchor = placement.anchor or default_anchor

    # --- horizontal ---
    if placement.x is not None:
        target = placement.x * canvas_width
        dx = target - anchor_point(box, anchor)
    elif placement.anchor is None or placement.anchor == default_anchor:
        # Default: change nothing at all.
        dx = 0.0
    elif anchor == "left":
        dx = r_left - x0
    elif anchor == "right":
        dx = r_right - x1
    else:
        dx = ((r_left + r_right) / 2.0) - ((x0 + x1) / 2.0)

    # --- vertical ---
    if placement.y is not None:
        target = r_top + placement.y * (r_bottom - r_top)
        dy = target - ((y0 + y1) / 2.0)
    else:
        dy = 0.0

    # --- keep it inside the region ---
    # Bounds are the caption band by choice: every font size and the palette size
    # are derived from the band height, so an element outside it would have no
    # size reference and the same multiplier would mean different things in
    # different places.
    width, height = x1 - x0, y1 - y0
    if width <= (r_right - r_left):
        dx = min(max(dx, r_left - x0), r_right - x1)
    else:
        # Wider than the region (a long string at a big multiplier): keep its left
        # edge in rather than letting the clamp fight itself.
        dx = r_left - x0
    if height <= (r_bottom - r_top):
        dy = min(max(dy, r_top - y0), r_bottom - y1)
    else:
        dy = r_top - y0

    return dx, dy


def fraction_from_offset(box, region, dx, dy, anchor: str, canvas_width: int):
    """Inverse of `resolve_offset`, for turning a finished drag into storage."""
    x0, y0, x1, y1 = box
    r_top, r_bottom = region[1], region[3]
    x = (anchor_point(box, anchor) + dx) / float(canvas_width)
    span = float(r_bottom - r_top) or 1.0
    y = (((y0 + y1) / 2.0) + dy - r_top) / span
    return x, y
