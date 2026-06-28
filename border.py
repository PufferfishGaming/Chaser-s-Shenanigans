"""
Image border functions and classes
"""
import math
from enum import Enum
from dataclasses import dataclass
from PIL import Image
import text as tm

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

def draw_border(img: Image, border: Border) -> Image:
    w = img.width + border.left + border.right
    h = img.height + border.top + border.bottom
    canvas = Image.new("RGB", (w, h), (255, 255, 255, 0))
    canvas.paste(img, (border.left, border.top))

    return canvas

def draw_exif(img: Image, exif: dict, border: Border, font: tuple[str, int], boldfont: tuple[str, int],
              available_width: int = None) -> Image:
    """Draw EXIF text on the bottom border.

    Args:
        available_width: If set, the font size is reduced so that every text line
                         fits within this many pixels. Used for the left-aligned
                         polaroid layout so the text never overlaps the palette
                         that occupies the bottom-right. None = no width limit.
    """
    centered = border.border_type in (BorderType.POLAROID, BorderType.LARGE)
    # Fraction of the caption band the body text fills (heading gets +0.02). Lower
    # = smaller text with more empty margin above and below within the band. 0.10
    # leaves ~36% of the band as breathing room on each side. Because the size is
    # derived from the band (which scales with image resolution), this proportion
    # is identical on every export regardless of source megapixels.
    multiplier = 0.10 if centered else 0.5

    # The caption lives in a band of height `band` at the very bottom of the
    # canvas. Normally this equals border.bottom; but when ratio padding has
    # ballooned border.bottom (e.g. a landscape padded to a tall 9:16), band stays
    # the original per-type bottom, so the text is sized and placed near the
    # bottom edge instead of growing huge and floating in the middle.
    band = border.caption_band or border.bottom

    # Build the three lines up front so we can size against their widths.
    line_heading = f"{exif['Make']} {exif['Model']}"
    line_lens = f"{exif['LensMake']} {exif['LensModel']}"
    line_settings = f"{exif['FocalLength']}  {exif['FNumber']}  {exif['ISOSpeedRatings']}  {exif['ExposureTime']}"

    # Height-and-width constrained sizing. The heading uses the bold font; the two
    # body lines use the regular font. We size each against the width budget.
    # Ceiling scales with the band so the proportional sizing is never clamped on
    # high-resolution exports. (The old default of 100px capped the font on large
    # images, making the EXIF text shrink relative to the frame as resolution grew.)
    font_size = tm.get_optimal_font_size_constrained(
        [line_lens, line_settings], band * multiplier, available_width,
        font[0], index=font[1], max_font_size=band)
    heading_font_size = tm.get_optimal_font_size_constrained(
        [line_heading], band * (multiplier + 0.02), available_width,
        boldfont[0], index=boldfont[1], max_font_size=band)

    stack_lines = centered
    horizontally_centered = centered and border.border_type != BorderType.POLAROID

    # The SMALL/MEDIUM layout draws heading + lens + settings in a single horizontal
    # row (stack_lines is False). A per-line width limit isn't enough there - the
    # COMBINED row can still overrun the palette / right edge (it did on tall frames
    # and the MEDIUM border). Shrink both fonts together, preserving the heading:body
    # ratio, until the whole row fits the width budget. The stacked polaroid layout
    # is handled by the per-line constraint above and is left untouched.
    if not stack_lines and available_width:
        reg_path, reg_idx = font[0], font[1]
        bold_path, bold_idx = boldfont[0], boldfont[1]

        def _row_width(body_sz, head_sz):
            return (tm.measure_text_width(line_heading, head_sz, bold_path, bold_idx) + head_sz / 2
                    + tm.measure_text_width(line_lens, body_sz, reg_path, reg_idx) + body_sz / 2
                    + tm.measure_text_width(line_settings, body_sz, reg_path, reg_idx))

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

    font = tm.create_font(font_size, fontpath=font[0], index=font[1])
    heading_font = tm.create_font(heading_font_size, fontpath=boldfont[0], index=boldfont[1])

    # Vertical align text within the caption band at the BOTTOM of the canvas.
    # The band occupies the last `band` pixels of the image height.
    band_top = img.height - band
    if stack_lines:
         # 3 Lines of text. 1 heading, two normal. Minus heading margins.
        total_font_height = heading_font.size + (2 * font.size) - (heading_font.size / 2)
        y = band_top + (band / 2) - (total_font_height / 2)
    else:
        y = band_top + (band / 2) + (heading_font.size / 3)

    x = border.left

    text_img, (x, y) = tm.draw_text_on_image(img, line_heading, (x, y), horizontally_centered, heading_font,
                                             fill=(100, 100, 100), stack_lines=stack_lines)

    text_img, (x, y) = tm.draw_text_on_image(text_img, line_lens, (x, y), horizontally_centered, font,
                                             fill=(128, 128, 128), stack_lines=stack_lines)

    text_img, (x, y) = tm.draw_text_on_image(text_img, line_settings, (x, y), horizontally_centered, font,
                                             fill=(128, 128, 128), stack_lines=stack_lines)

    return text_img
