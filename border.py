"""
Image border functions and classes
"""
import math
from enum import Enum
from dataclasses import dataclass
from PIL import Image, ImageDraw
import text as tm
import layout

class BorderType(Enum):
    POLAROID = 'p'
    SMALL = 's'
    MEDIUM = 'm'
    LARGE = 'l'

    def __str__(self):
        return self.value

@dataclass
class Border:
    top: int
    right: int
    bottom: int
    left: int
    border_type: BorderType
    # The bottom-strip height the EXIF/palette caption should be sized and placed
    # within. This is the ORIGINAL per-type bottom border, before any aspect-ratio
    # padding is added below it. When a wide photo is padded to a tall ratio, the
    # actual `bottom` balloons with empty space, but the caption stays in a band of
    # this height near the bottom edge instead of floating in the middle.
    caption_band: int = 0

def get_border_size(img_width: int, img_height: int, reduceby: int=4) -> int:
    """Calculate an image border size based on the golden ratio.

    Args:
        img_width (number): Source image width
        img_height (number): Source image height
        reduceby (int): Reduce the border by a factor of this

    Returns:
        int: The border size
    """
    # Use golden ratio to determine border size from image size.
    golden_ratio = (1 + 5 ** 0.5) / 2
    img_area = img_width * img_height
    canvas_area = img_area * golden_ratio
    border_size = math.ceil(math.sqrt(canvas_area - img_area) / reduceby)

    return border_size

def create_border(imgw: int, imgh: int, border_type: Border, target_ratio: float = None) -> Border:
    """Create a Border for an image.

    Args:
        imgw, imgh: Source image dimensions.
        border_type: The border style.
        target_ratio: Optional final canvas width/height ratio to pad TO (e.g. 0.8
                      for 4:5, 1.0 for square, 1.7778 for 16:9). None = native, no
                      ratio padding. The image is never cropped; extra border is
                      added to the deficient axis only.
    """
    # top, right, bottom, left
    reduceby_map = {
        BorderType.POLAROID: (32, 32, 6, 32),
        BorderType.SMALL: (32, 32, 32, 32),
        BorderType.MEDIUM: (16, 16, 16, 16),
        BorderType.LARGE: (6, 6, 6, 6),
    }
    rtop, rright, rbottom, rleft = reduceby_map[border_type]
    btop = get_border_size(imgw, imgh, rtop)
    bright = get_border_size(imgw, imgh, rright)
    bbottom = get_border_size(imgw, imgh, rbottom)
    bleft = get_border_size(imgw, imgh, rleft)

    # The caption band is the per-type bottom border BEFORE any ratio padding.
    # The caption (EXIF + palette) is sized and placed within a strip of this
    # height at the bottom of the canvas, so ratio padding that balloons `bottom`
    # only adds empty space - it doesn't drag the caption into the middle.
    caption_band = bbottom

    if target_ratio:
        # Generalised ratio padding for every border type.
        #
        # We pad the canvas (image + the per-type borders already computed) out to
        # target_ratio by ADDING extra border to the deficient axis only. Padding is
        # added on top of the existing borders rather than replacing them, so the
        # border character of the type is preserved - crucially polaroid's large
        # asymmetric bottom border survives. The extra needed on an axis is split
        # evenly between its two sides.
        cur_w = imgw + bleft + bright
        cur_h = imgh + btop + bbottom
        cur_ratio = cur_w / cur_h

        if cur_ratio > target_ratio:
            # Too wide -> need more height. Add equally to top and bottom.
            target_h = math.ceil(cur_w / target_ratio)
            extra = max(0, target_h - cur_h)
            add_top = extra // 2
            add_bottom = extra - add_top
            btop += add_top
            bbottom += add_bottom
        elif cur_ratio < target_ratio:
            # Too tall -> need more width. Add equally to left and right.
            target_w = math.ceil(cur_h * target_ratio)
            extra = max(0, target_w - cur_w)
            add_left = extra // 2
            add_right = extra - add_left
            bleft += add_left
            bright += add_right

    border = Border(btop, bright, bbottom, bleft, border_type, caption_band=caption_band)

    return border

def _spec3(spec):
    """Unpack a font spec into (path, index, weight).

    `fontcatalog.spec()` returns a (file, index, weight) triple, but older
    callers - and the CLI's bare -f / -fb filenames - pass a (file, index) pair.
    Accepting both keeps those working; a missing weight means "the face default",
    which is correct for a static font and deliberate for the CLI escape hatch.
    """
    path = spec[0]
    index = spec[1] if len(spec) > 1 else 0
    weight = spec[2] if len(spec) > 2 else None
    return path, index, weight


def draw_border(img: Image, border: Border) -> Image:
    w = img.width + border.left + border.right
    h = img.height + border.top + border.bottom
    canvas = Image.new("RGB", (w, h), (255, 255, 255, 0))
    canvas.paste(img, (border.left, border.top))

    return canvas

def _line_metrics(line, size, path, index, weight):
    """(width, ink ascent, ink descent) for one caption line.

    INK extents, not the font's declared metrics: a script face's declared
    ascender sits far above its actual capitals, so clamping against the metric
    leaves a gap on some faces and clips on others.
    """
    if not line:
        return 0.0, 0.0, 0.0
    return (tm.measure_text_width(line, size, path, index, weight),
            tm.measure_text_ascent(line, size, path, index, weight),
            tm.measure_text_descent(line, size, path, index, weight))


def _union(boxes):
    boxes = [b for b in boxes if b is not None]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _overlaps(a, b):
    if a is None or b is None:
        return False
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def draw_exif(img: Image, exif: dict, border: Border, font: tuple, boldfont: tuple,
              available_width: int = None, custom_text: str = None,
              custom_font: tuple = None, custom_size_mult: float = 1.0,
              custom_centered: bool = False, placements: dict = None,
              measure_only: bool = False, geometry_out: dict = None,
              palette_box: tuple = None, right_bound: float = None) -> Image:
    """Draw the EXIF caption (and optional custom text) on the bottom border.

    Placement is a TRANSLATION of a measured box, never a re-layout. The
    automatic layout is computed exactly as it always was; the element's boxes
    are then measured and `layout.resolve_offset` returns an offset to shift
    them by. Two properties depend on that and are lost if this is "cleaned up"
    into a single positioning pass:

      * a default placement resolves to a literal (0.0, 0.0), so defaults are
        byte-identical rather than merely intended to be, and
      * "auto-fit until you move it" is free, because the width budgets are
        computed once, on the automatic layout.

    `measure_only=True` returns the element boxes without drawing anything. That
    is the geometry API: the GUI uses it for its draggable outlines and `core`
    uses it to resolve placements. Keeping the measurement in the same function
    as the layout is what stops the two drifting apart.

    Args:
        available_width: Width budget for left-anchored text, so the caption
                         never collides with the palette. None = no limit.
        custom_text: Optional literal string drawn alongside the EXIF caption.
        custom_font: (file, index, weight) for that string.
        custom_size_mult: 0.5-3.0 multiplier on its automatic size.
        custom_centered: Put the custom text in the band's centre (both axes)
                         when the centre is actually free.
        placements: {element: layout.Placement}. Missing entries are defaults.
        measure_only: Measure and return, drawing nothing.
        geometry_out: Optional dict, filled with canvas/band/boxes/anchors.
        palette_box: The palette's (x0, y0, x1, y1) if one is being drawn, so the
                     centre-slot test and the geometry report can see it.
        right_bound: Rightmost column the caption may reach (one cell before the
                     palette, or the photo's right edge). Used for the custom
                     text's width budget on every border type.
    """
    font_path, font_index, font_weight = _spec3(font)
    bold_path, bold_index, bold_weight = _spec3(boldfont)
    custom_path = custom_index = custom_weight = None
    if custom_text and custom_font:
        custom_path, custom_index, custom_weight = _spec3(custom_font)

    type_name = border.border_type.name if hasattr(border.border_type, "name") \
        else str(border.border_type)
    placements = placements or {}

    centered = border.border_type in (BorderType.POLAROID, BorderType.LARGE)
    multiplier = 0.10 if centered else 0.5
    band = border.caption_band or border.bottom
    band_top = img.height - band
    # Horizontally bounded by the PHOTOGRAPH's edges, not the canvas: 'left'
    # means the photo's left edge, which is where every other element lines
    # up. Anchoring to the canvas would put it out in the border margin.
    band_region = (border.left, band_top, img.width - border.right, img.height)

    line_heading = f"{exif['Make']} {exif['Model']}"
    line_lens = f"{exif['LensMake']} {exif['LensModel']}"
    line_settings = (f"{exif['FocalLength']}  {exif['FNumber']}  "
                     f"{exif['ISOSpeedRatings']}  {exif['ExposureTime']}")

    font_size = tm.get_optimal_font_size_constrained(
        [line_lens, line_settings], band * multiplier, available_width,
        font_path, index=font_index, max_font_size=band, weight=font_weight)
    heading_font_size = tm.get_optimal_font_size_constrained(
        [line_heading], band * (multiplier + 0.02), available_width,
        bold_path, index=bold_index, max_font_size=band, weight=bold_weight)

    stack_lines = centered
    horizontally_centered = centered and border.border_type != BorderType.POLAROID

    if not stack_lines and available_width:
        def _row_width(body_sz, head_sz):
            # Measured at the SAME weights they are drawn at. Measuring the
            # heading as Regular while drawing it SemiBold underestimates the row
            # and lets it overrun the palette.
            return (tm.measure_text_width(line_heading, head_sz, bold_path, bold_index,
                                          bold_weight) + head_sz / 2
                    + tm.measure_text_width(line_lens, body_sz, font_path, font_index,
                                            font_weight) + body_sz / 2
                    + tm.measure_text_width(line_settings, body_sz, font_path, font_index,
                                            font_weight))

        guard = 0
        while font_size > 1 and _row_width(font_size, heading_font_size) > available_width and guard < 500:
            scale = available_width / _row_width(font_size, heading_font_size)
            new_body = max(1, int(font_size * scale))
            new_head = max(1, int(heading_font_size * scale))
            if new_body >= font_size:            # guarantee progress past int() rounding
                new_body = font_size - 1
                new_head = max(1, heading_font_size - 1)
            font_size, heading_font_size = new_body, new_head
            guard += 1

    # ---- the EXIF block's automatic layout --------------------------------
    exif_place = placements.get("exif") or layout.Placement()
    size_mult = float(getattr(exif_place, "size_mult", 1.0) or 1.0)
    if size_mult != 1.0:
        font_size = max(1, int(round(font_size * size_mult)))
        heading_font_size = max(1, int(round(heading_font_size * size_mult)))

    font_obj = tm.create_font(font_size, fontpath=font_path, index=font_index, weight=font_weight)
    heading_font = tm.create_font(heading_font_size, fontpath=bold_path, index=bold_index,
                                  weight=bold_weight)

    if stack_lines:
        # 3 lines of text: 1 heading, two normal. Minus heading margins.
        total_font_height = heading_font.size + (2 * font_obj.size) - (heading_font.size / 2)
        y0 = band_top + (band / 2) - (total_font_height / 2)
    else:
        y0 = band_top + (band / 2) + (heading_font.size / 3)

    specs = [(line_heading, heading_font_size, bold_path, bold_index, bold_weight, heading_font,
              (100, 100, 100)),
             (line_lens, font_size, font_path, font_index, font_weight, font_obj, (128, 128, 128)),
             (line_settings, font_size, font_path, font_index, font_weight, font_obj, (128, 128, 128))]

    draws = []          # (text, font_obj, x, baseline_y, fill)
    if stack_lines:
        widths = [_line_metrics(t, s, p, i, w)[0] for (t, s, p, i, w, _f, _c) in specs]
        block_w = max(widths) if widths else 0.0
        if horizontally_centered:
            block_x = (img.width - block_w) / 2
        else:
            block_x = border.left
        # Line alignment inside the block is separable from where the block sits
        # by an algebraic identity: LARGE's old "centre each line on the canvas"
        # is exactly "centre the block, then centre the lines inside it". Keeping
        # it explicit lets the two be chosen independently without changing any
        # existing output.
        line_align = getattr(exif_place, "line_align", None) or \
            layout.default_line_align("exif", type_name)
        factor = layout.LINE_ALIGN_FACTORS.get(line_align, 0.0)
        y = y0
        for (text_, size_, path_, idx_, wt_, fobj, fill_), w_ in zip(specs, widths):
            x = block_x + factor * (block_w - w_)
            draws.append((text_, fobj, x, y, fill_, size_, path_, idx_, wt_))
            y = y + fobj.size + (fobj.size / 2)
    else:
        x = border.left
        y = y0
        for (text_, size_, path_, idx_, wt_, fobj, fill_) in specs:
            w_ = _line_metrics(text_, size_, path_, idx_, wt_)[0]
            draws.append((text_, fobj, x, y, fill_, size_, path_, idx_, wt_))
            x = x + w_ + (fobj.size / 2)

    def _ink_boxes_of(items):
        out = []
        for (text_, _fobj, x_, y_, _fill, size_, path_, idx_, wt_) in items:
            if not text_:
                continue
            bx0, by0, bx1, by1 = tm.measure_text_bounds(text_, size_, path_, idx_, wt_)
            out.append((x_ + bx0, y_ + by0, x_ + bx1, y_ + by1))
        return out

    def _boxes_of(items):
        out = []
        for (text_, _fobj, x_, y_, _fill, size_, path_, idx_, wt_) in items:
            if not text_:
                continue
            w_, asc_, desc_ = _line_metrics(text_, size_, path_, idx_, wt_)
            out.append((x_, y_ - asc_, x_ + w_, y_ + desc_))
        return out

    exif_box = _union(_boxes_of(draws))

    # ---- the custom text's automatic layout -------------------------------
    custom_draws = []
    custom_box = None
    custom_used_centre = False
    if custom_text and custom_path:
        base = font_size if not stack_lines else font_obj.size
        c_size = max(1, int(round(base * float(custom_size_mult or 1.0))))
        # Cap so the glyphs can never be taller than the band.
        while c_size > 1:
            asc = tm.measure_text_ascent(custom_text, c_size, custom_path, custom_index, custom_weight)
            desc = tm.measure_text_descent(custom_text, c_size, custom_path, custom_index, custom_weight)
            if asc + desc <= band * 0.9:
                break
            c_size -= 1
        # Width budget. A centred line of width W spans (canvas - W)/2 to
        # (canvas + W)/2, so it reaches FURTHER RIGHT than a left-anchored line of
        # the same W - its budget is 2 * right_bound - canvas, not right_bound
        # minus the left margin. Getting this wrong let a long centred string run
        # straight across the palette.
        rb = right_bound if right_bound is not None else (img.width - border.right)
        if custom_centered:
            budget = max(50.0, 2.0 * rb - img.width)
        else:
            budget = max(50.0, rb - border.left)
        def _ink(sz):
            return tm.measure_text_bounds(custom_text, sz, custom_path, custom_index,
                                          custom_weight)

        while c_size > 1:
            bx0, _by0, bx1, _by1 = _ink(c_size)
            if (bx1 - bx0) <= budget:
                break
            c_size -= 1
        c_w, c_asc, c_desc = _line_metrics(custom_text, c_size, custom_path, custom_index, custom_weight)
        cb_x0, cb_y0, cb_x1, cb_y1 = _ink(c_size)
        c_font = tm.create_font(c_size, fontpath=custom_path, index=custom_index, weight=custom_weight)

        centre_box = None
        if custom_centered:
            # Centre the INK, not the advance box: the pen goes wherever it must
            # for the visible glyphs to straddle the centre line.
            cx = (img.width - (cb_x0 + cb_x1)) / 2
            cy = band_top + (band / 2) + (c_asc - c_desc) / 2
            centre_box = (cx + cb_x0, cy + cb_y0, cx + cb_x1, cy + cb_y1)
            # Decided by an actual overlap test, not by border type, so it is
            # self-correcting: POLAROID's left caption clears the centre and uses
            # it, LARGE centres its own caption and therefore does not, and an
            # over-long string falls back the same way.
            if not _overlaps(centre_box, exif_box) and not _overlaps(centre_box, palette_box):
                custom_draws.append((custom_text, c_font, cx, cy, (128, 128, 128),
                                     c_size, custom_path, custom_index, custom_weight))
                custom_used_centre = True

        if not custom_used_centre:
            if stack_lines:
                # A fourth stacked line. Its baseline is computed from real font
                # metrics rather than from the previous line's advance, because
                # draw_text_on_image advances by 1.5x the size of the line it just
                # drew - a larger following line would reach its ascenders back up
                # through it.
                last = draws[-1] if draws else None
                if last is not None:
                    prev_desc = _line_metrics(last[0], last[5], last[6], last[7], last[8])[2]
                    prev_y, prev_size = last[3], last[1].size
                else:
                    prev_desc, prev_y, prev_size = 0.0, y0, font_obj.size
                # Baseline from real INK metrics, not from the previous line's
                # advance. draw_text_on_image advances by 1.5x the size of the line
                # it just drew, so a custom line larger than the EXIF body reached
                # its ascenders back up through the settings line - at 2.5x the two
                # visibly struck through each other.
                gap = max(2.0, prev_size * 0.25)
                cy = prev_y + prev_desc + gap + c_asc
                block_left = min((d[2] for d in draws), default=border.left)
                block_right = max((d[2] + _line_metrics(d[0], d[5], d[6], d[7], d[8])[0]
                                   for d in draws), default=border.left)
                align = getattr(exif_place, "line_align", None) or \
                    layout.default_line_align("exif", type_name)
                f = layout.LINE_ALIGN_FACTORS.get(align, 0.0)
                cx = block_left + f * ((block_right - block_left) - c_w)
            else:
                # Last segment of the single caption row.
                last = draws[-1] if draws else None
                if last is not None:
                    lw = _line_metrics(last[0], last[5], last[6], last[7], last[8])[0]
                    cx = last[2] + lw + (last[1].size / 2)
                    cy = last[3]
                else:
                    cx, cy = border.left, y0
            # Two-sided clamp: clear the canvas bottom AND stay below band_top.
            cy = min(cy, img.height - c_desc - 1)
            cy = max(cy, band_top + c_asc + 1)
            custom_draws.append((custom_text, c_font, cx, cy, (128, 128, 128),
                                 c_size, custom_path, custom_index, custom_weight))

        custom_box = _union(_ink_boxes_of(custom_draws))

    # ---- translate each element by its resolved offset --------------------
    def _shift(items, dx, dy):
        return [(t, f, x + dx, y + dy, fill, s, p, i, w)
                for (t, f, x, y, fill, s, p, i, w) in items]

    boxes = {}
    anchors = {}

    for name, box, items in (("exif", exif_box, draws), ("text", custom_box, custom_draws)):
        if box is None:
            continue
        place = placements.get(name) or layout.Placement()
        default = layout.default_anchor(name, type_name)
        dx, dy = layout.resolve_offset(box, band_region, place, default, img.width)
        if dx or dy:
            shifted = _shift(items, dx, dy)
            box = (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
            if name == "exif":
                draws = shifted
            else:
                custom_draws = shifted
        boxes[name] = tuple(round(v) for v in box)
        # The EFFECTIVE anchor, never the default: the GUI stores a dragged
        # position as a fraction of canvas width at the element's anchor EDGE and
        # resolve_offset reads it back the same way, so the two must agree on
        # which edge. Reporting only defaults put a dragged centred element 55px
        # out and a right-aligned one 110px out in the opposite direction.
        anchors[name] = getattr(place, "anchor", None) or default

    if palette_box is not None:
        boxes["palette"] = tuple(round(v) for v in palette_box)
        pal_place = placements.get("palette") or layout.Placement()
        anchors["palette"] = getattr(pal_place, "anchor", None) or \
            layout.default_anchor("palette", type_name)

    if geometry_out is not None:
        geometry_out["canvas"] = (img.width, img.height)
        # The SAME region resolve_offset clamps against. The GUI records a drag
        # as a fraction within this rectangle and reads it back the same way, so
        # reporting a different one here puts a dragged element out by the
        # difference between the canvas and the photograph edges.
        geometry_out["band"] = tuple(round(v) for v in band_region)
        geometry_out["boxes"] = boxes
        geometry_out["anchors"] = anchors
        geometry_out["custom_centered"] = custom_used_centre

    if measure_only:
        return img

    # ---- draw -------------------------------------------------------------
    draw = ImageDraw.Draw(img)
    draw.fontmode = 'L'
    for (text_, fobj, x_, y_, fill_, _s, _p, _i, _w) in draws + custom_draws:
        if not text_:
            continue
        draw.text((x_, y_), text_, font=fobj, fill=fill_, anchor="ls")

    return img
