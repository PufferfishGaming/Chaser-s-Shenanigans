"""
Text on image functions.

Weight is not optional
----------------------
Most families in `fonts/` are unmodified upstream *variable* fonts with a `wght`
axis, and two rules follow from that.

First, never load one without naming a weight: a variable font loaded with no
axis position renders at its *default* instance, and that is not always Regular
(Cormorant Garamond defaults to Light). If the weight were silently dropped, the
EXIF heading would be indistinguishable from the body text and nothing would
visibly fail.

Second, measure at the same weight you draw at. The shrink-to-fit sizing
compares measured widths against a budget, so measuring Regular and drawing
SemiBold underestimates and the caption overruns. Every measuring helper here
therefore takes the same `weight` argument as `create_font`, and callers thread
it through.

A weight passed to a *static* font is ignored silently - that is the house rule
for optional capability. A weight that a variable font does not have is an
error, and `validate_font` reports it once, up front, rather than letting it
degrade into the wrong-looking caption.
"""
import os
from collections import OrderedDict
from typing import List, Optional, TypeVar

from PIL import Image, ImageDraw, ImageFont

T = TypeVar('T')

# Font objects are cached because building one is expensive and the caption
# pipeline asks for the same handful repeatedly while binary-searching a size.
#
# The cap is a memory decision, not a tidiness one: each FreeTypeFont for a
# 1.2 MB variable font costs ~339 KB of RSS, and a folder batch runs one process
# per core. Raising this multiplies by the worker count.
_CACHE_LIMIT = 48
_cached_font: "OrderedDict[tuple, ImageFont.FreeTypeFont]" = OrderedDict()


def load_font_variants(fontpath: str) -> List[T]:
    """Try loading the different font variant indices.

    Args:
        fontpath (str): Path to the font file

    Returns:
        [(index, {'family': str, 'style': str})]: A list containing the available font variants
    """
    variants = []
    index = 0

    while True:
        try:
            font = ImageFont.truetype(fontpath, size=12, index=index)
            info = {
                'family': font.getname()[0],
                'style': font.getname()[1]
            }
            variants.append((index, info))
            index += 1
        except Exception:
            break

    return variants


def load_font_weights(fontpath: str) -> List[str]:
    """Named weight instances of a variable font, or [] for a static one.

    Pillow raises OSError from `get_variation_names()` when the face has no
    variation axes, which is how a static font is detected - there is no
    "is this variable" query.
    """
    try:
        font = ImageFont.truetype(fontpath, size=12)
        names = font.get_variation_names()
    except Exception:
        return []
    out = []
    for n in names:
        out.append(n.decode('utf-8', 'ignore') if isinstance(n, bytes) else str(n))
    return out


def validate_font(fontpath: str, index: int, weight: Optional[str] = None) -> Optional[str]:
    """Validate that the font exists, has the variant index, and has the weight.

    Args:
        fontpath (str): Path to the font file
        index (int): The font variant index.
        weight (str, optional): Named weight instance to require.

    Returns:
        str: None if the font is usable, otherwise an error message.
    """
    if not os.path.isfile(fontpath):
        return f'Font {fontpath} does not exist.'

    font_variants = load_font_variants(fontpath)
    if not any(variant[0] == index for variant in font_variants):
        return (f'Font {fontpath} does not contain a variant with index: {index}. '
                f'Available variants: {font_variants}')

    if weight:
        available = load_font_weights(fontpath)
        # No axes at all: a static face. Ignoring the weight is deliberate -
        # optional capability degrades, it does not fail.
        if available and weight not in available:
            return (f'Font {fontpath} has no weight named {weight!r}. '
                    f'Available weights: {available}')

    return None


def create_font(size: int, fontpath: str, index: int = 0,
                weight: Optional[str] = None) -> ImageFont.FreeTypeFont:
    """Create the font object at a specific named weight.

    Args:
        size (int): Pixel size
        fontpath (str): Path to the font file
        index (int): The font variant index. Defaults to 0.
        weight (str, optional): Named weight instance, e.g. 'SemiBold'. Ignored
            (silently) when the face has no variation axes.

    Returns:
        ImageFont.FreeTypeFont: The created font
    """
    key = (size, fontpath, index, weight)
    hit = _cached_font.get(key)
    if hit is not None:
        _cached_font.move_to_end(key)
        return hit

    font = ImageFont.truetype(fontpath, size, index)
    if weight:
        try:
            font.set_variation_by_name(weight)
        except Exception:
            # Static face, or a name it does not carry. validate_font reports the
            # latter up front; here it degrades rather than taking down a render.
            pass
        # Selecting a variation can reset the reported size on some Pillow
        # versions, and every sizing helper reads `font.size` back.
        font.size = size

    _cached_font[key] = font
    if len(_cached_font) > _CACHE_LIMIT:
        _cached_font.popitem(last=False)
    return font


def draw_text_on_image(img: Image, text: str, xy: tuple, centered: bool,
                       font: ImageFont.FreeTypeFont, fill: tuple = (100, 100, 100),
                       stack_lines: bool = None) -> Image:
    """Draw text on an image

    Args:
        img (Image): The image to draw on
        text (str): The text to draw
        xy (tuple): The xy position of the starting point
        centered (bool): Center the text relative to the entire image
        font (ImageFont.FreeTypeFont): The font to use. See create_font.
        fill (tuple, optional): The font color. Defaults to (100, 100, 100).
        stack_lines (bool, optional): If True, advance vertically (y) to the next line
                                      instead of horizontally (x). Defaults to the value
                                      of `centered` to preserve original behaviour.

    Returns:
        Image: The image with the text drawn on it.
        xy (tuple): The xy position of the next drawing pos

    NOTE: `next_y` advances by 1.5x the size of the line JUST DRAWN. A following
    line that is larger will reach its ascenders back up through it, so any
    stacked line of a different size must compute its own baseline from real font
    metrics rather than using the returned y.
    """
    # By default, vertical stacking is coupled to centering (original behaviour).
    # Callers that want left-aligned but still multiline text can set stack_lines=True.
    if stack_lines is None:
        stack_lines = centered

    draw = ImageDraw.Draw(img)

    # Enable antialiasing
    draw.fontmode = 'L'

    x, y = xy

    # Get the width of the text line so we can return the finish x pos
    w = draw.textlength(text, font=font)

    if centered:
        # Center the starting x pos
        x = (img.width - w) / 2

    draw.text((x, y), text, font=font, fill=fill, anchor="ls")

    # Figure out next x, y positions
    next_y = y + font.size + (font.size / 2) if stack_lines else y
    next_x = x if stack_lines else x + w + (font.size / 2)

    return img, (next_x, next_y)


def _measure_draw():
    return ImageDraw.Draw(Image.new("RGB", (1, 1)))


def measure_text_width(text, font_size, fontpath, index,
                       weight: Optional[str] = None) -> float:
    """Measure the pixel width of `text` at a given font size AND weight.

    The weight argument is not decorative: measuring at a lighter weight than is
    drawn underestimates the width, and the shrink-to-fit sizing then lets the
    caption overrun its budget.
    """
    font = create_font(font_size, fontpath, index, weight)
    return _measure_draw().textlength(text, font=font)


def measure_text_bounds(text, font_size, fontpath, index,
                        weight: Optional[str] = None):
    """Ink bounding box (x0, y0, x1, y1) relative to the pen on the baseline.

    `textlength` returns the ADVANCE, which is not the ink. A script face with a
    swash has a negative left side bearing, so its ink starts left of where the
    pen was put - measured at 3px on Great Vibes, which is enough to push a
    "centred" line past the left border. Anything positioning by ink must use
    this rather than the advance.
    """
    font = create_font(font_size, fontpath, index, weight)
    if not text:
        return (0.0, 0.0, 0.0, 0.0)
    return _measure_draw().textbbox((0, 0), text, font=font, anchor="ls")


def measure_text_ascent(text, font_size, fontpath, index,
                        weight: Optional[str] = None) -> float:
    """Pixels of INK above the baseline for `text`.

    Deliberately the ink extent rather than the font's declared ascender: a
    script face's declared ascender sits far above its actual capitals, so
    clamping against the metric leaves a visible gap on some faces and clips on
    others. Used to keep a caption baseline below the caption band's top.
    """
    font = create_font(font_size, fontpath, index, weight)
    if not text:
        return 0.0
    box = _measure_draw().textbbox((0, 0), text, font=font, anchor="ls")
    return max(0.0, -box[1])


def measure_text_descent(text, font_size, fontpath, index,
                         weight: Optional[str] = None) -> float:
    """Pixels of INK below the baseline for `text`. See measure_text_ascent."""
    font = create_font(font_size, fontpath, index, weight)
    if not text:
        return 0.0
    box = _measure_draw().textbbox((0, 0), text, font=font, anchor="ls")
    return max(0.0, box[3])


def get_optimal_font_size(text, target_height, fontpath, index,
                          max_font_size=100, min_font_size=1,
                          weight: Optional[str] = None):
    """
    Calculate the optimal font size based on a target height

    Args:
        text (str): Sample text to draw
        target_height (int): The target height
        fontpath: (str): The path of the font to determine the size for.
        index (int): The font variant index.
        max_font_size (int, optional): Max font size to return. Defaults to 100.
        min_font_size (int, optional): Min font size to return. Defaults to 1.
        weight (str, optional): Named weight instance to measure at.
    """
    def check_size(font_size):
        font = create_font(font_size, fontpath, index, weight)
        _, _, _, text_height = font.getbbox(text)
        return text_height <= target_height

    # Binary search for the optimal font size
    low, high = min_font_size, max_font_size
    while low <= high:
        mid = (low + high) // 2
        if check_size(mid):
            low = mid + 1
        else:
            high = mid - 1

    return high  # The largest font size that fits


def get_optimal_font_size_constrained(texts, target_height, available_width,
                                      fontpath, index, max_font_size=100,
                                      min_font_size=1, weight: Optional[str] = None):
    """Largest font size such that text height <= target_height AND every line in
    `texts` fits within available_width.

    This is the height-based binary search, plus a width cap: once the
    height-optimal size is found, shrink further if any line would overflow the
    available horizontal space. Used so EXIF text never collides with the palette.

    Args:
        texts (list[str]): All lines that must fit the width.
        target_height (int): Height budget (as in get_optimal_font_size).
        available_width (int|None): Width budget in px. None = no width constraint.
        fontpath, index: Font.
        weight (str, optional): Measured AND drawn at this weight.
    """
    # Start from the height-optimal size for a representative sample.
    size = get_optimal_font_size("Test", target_height, fontpath, index,
                                 max_font_size, min_font_size, weight)
    if not available_width or available_width <= 0:
        return size

    # Shrink until the widest line fits, or we hit the minimum.
    while size > min_font_size:
        widest = max((measure_text_width(t, size, fontpath, index, weight)
                      for t in texts if t), default=0)
        if widest <= available_width:
            break
        size -= 1
    return size
