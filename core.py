"""
Core image processing pipeline.

This module holds the single source of truth for turning a source photo into a
bordered (optionally exif + palette) output. It is deliberately GUI-agnostic and
picklable-friendly so the same `process_image` can be called both:

  * sequentially from the GUI thread (with a progress callback for per-stage UI), and
  * inside a ProcessPoolExecutor worker (with progress_cb=None) for parallel folder runs.
"""
import os
import logging
from PIL import Image, ImageOps
from exif import get_exif
from palette import load_image_color_palette, overlay_palette, extract_colors, render_color_platte
from border import BorderType, create_border, draw_border, draw_exif
import layout as layout_mod
from text import validate_font

# Wide aspect ratios on large source images legitimately produce very large
# canvases (e.g. a 33MP portrait padded to 16:9 exceeds 100 megapixels). Pillow's
# default ~89MP guard treats these as possible decompression-bomb attacks and can
# raise, killing the file mid-batch. We are creating these canvases deliberately
# from the user's own files, so the guard is a false positive here. Disable it.
Image.MAX_IMAGE_PIXELS = None

logger = logging.getLogger(__name__)

# Pipeline stage labels, in order. Exposed so the GUI can render a stage list.
STAGES = ("open", "border", "exif", "palette", "save")

FILETYPES = ("jpg", "jpeg", "png")

# Right angles only. `transpose` is an exact pixel remap, so these are lossless -
# no resampling, no cropping, no blank corners. An arbitrary angle would have to
# either crop back to the aspect ratio (2.3% of the frame at 1 degree, 22.8% at
# 15) or leave white triangles cutting into the photo. Horizon straightening
# belongs in Quick Edit.
ROTATIONS = (0, 90, 180, 270)

# Pillow's ROTATE_* constants are COUNTER-clockwise, so a clockwise quarter turn
# is ROTATE_270. Getting this backwards still rotates and still produces a
# correctly-shaped canvas, which is exactly why a dimension assertion cannot
# catch it - tests/test_rotation.py tracks a marker pixel through the corners.
_CLOCKWISE = {
    90: Image.Transpose.ROTATE_270,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_90,
}

ORIENTATION_TAG = 274


def open_oriented(path: str, rotate: int = 0, auto_orient: bool = True,
                  preview_max_edge: int = None):
    """Open an image with its orientation and rotation already baked into pixels.

    Everything downstream - every border dimension, the caption band, the palette
    size - is derived from `img.width` / `img.height`, so both transforms have to
    happen HERE, before `create_border`. Doing either later leaves a landscape
    border around a portrait photo and the caption band on its side.

    Auto-orientation runs first and manual rotation on top of it, so `rotate` is
    relative to how the photo actually looks rather than to the raw sensor
    readout. An orientation-6 file already displays as a portrait; asking for 90
    more gives a landscape rather than cancelling back to the stored pixels.
    """
    if rotate is None:
        rotate = 0
    if int(rotate) % 360 not in ROTATIONS:
        raise ValueError(f"rotate must be one of {ROTATIONS}, got {rotate!r}")
    rotate = int(rotate) % 360

    img = Image.open(path)

    if auto_orient:
        # exif_transpose returns a NEW image when there is a tag to honour, and
        # strips the tag from it; with no tag it hands back an equivalent image.
        oriented = ImageOps.exif_transpose(img)
        if oriented is not img:
            img.close()
            img = oriented

    if rotate:
        turned = img.transpose(_CLOCKWISE[rotate])
        img.close()
        img = turned

    if preview_max_edge:
        longest = max(img.width, img.height)
        if longest > preview_max_edge:
            scale = preview_max_edge / longest
            resized = img.resize(
                (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                Image.BILINEAR,
            )
            img.close()
            img = resized

    return img


def _noop(stage: str, fraction: float) -> None:
    """Default progress callback: does nothing.

    Used when no progress reporting is wanted (e.g. inside parallel workers,
    where callbacks cannot cross the process boundary anyway)."""
    return None


class PreviewSource:
    """A decoded, oriented, downscaled photo plus its extracted palette colours.

    Exists because a preview's cost is almost entirely layout-INDEPENDENT.
    Measured on a 29.5MP JPEG, one ~740ms preview is:

        decode 208ms | downscale 65ms | extract palette 424ms | border+caption+save ~30ms

    Only that last ~30ms changes when an element moves, so holding the first
    three between renders takes an interactive re-render to about 30ms. That is
    what makes dragging an element at full preview quality possible.

    Do NOT "optimise" this by rendering a rougher preview instead - the quality
    was never the problem, the repeated work was.

    The owner keeps this object and closes it; `process_image(preview_source=...)`
    borrows the image and must not close it.
    """

    __slots__ = ("image", "colors", "exif", "key")

    def __init__(self, image, colors, exif, key):
        self.image = image
        self.colors = colors
        self.exif = exif
        self.key = key

    def close(self):
        try:
            if self.image is not None:
                self.image.close()
        except Exception:  # noqa: BLE001
            pass
        self.image = None


def preview_source_key(path: str, rotate: int = 0, auto_orient: bool = True,
                       preview_max_edge: int = None):
    """Everything a cached PreviewSource actually depends on.

    Deliberately NOT the whole parameter set - the point of the cache is that a
    LAYOUT change cannot invalidate it. Border type, ratio, fonts, text and
    placement are all layout, and layout is the thing this exists to make cheap.

    `extract_palette` is not part of the key either: the GUI drops the cache
    explicitly when the palette is toggled, because that changes what the object
    CONTAINS rather than whether it still matches the file.

    The file's modification time is included so editing the source on disk is
    picked up.
    """
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    return (os.path.abspath(path), mtime, int(rotate or 0) % 360,
            bool(auto_orient), preview_max_edge)


def build_preview_source(path: str, add_exif: bool = True, rotate: int = 0,
                         auto_orient: bool = True, preview_max_edge: int = None,
                         extract_palette: bool = False) -> PreviewSource:
    """Do the expensive, layout-independent part of a render once.

    That is the decode, the orientation and rotation, the preview downscale and
    the palette colour extraction - ~620ms of a ~740ms cold preview, none of
    which a layout change can affect.
    """
    exif = None
    if add_exif:
        with Image.open(path) as probe:
            exif = get_exif(probe)
    img = open_oriented(path, rotate=rotate, auto_orient=auto_orient,
                        preview_max_edge=preview_max_edge)
    colors = extract_colors(img) if extract_palette else None
    return PreviewSource(img, colors, exif,
                         preview_source_key(path, rotate, auto_orient, preview_max_edge))


def resolve_output_path(src_path: str, input_root: str, output_root: str, save_as_name: str, ext: str,
                        overwrite: bool = True) -> str:
    """Compute the output path inside output_root, mirroring the source's
    location relative to input_root so that identically-named files in
    different sub-directories never collide.

    Args:
        src_path: Full path to the source image.
        input_root: The root folder the batch was scanned from (or the file's
                    own directory for single-file runs).
        output_root: The chosen output folder.
        save_as_name: The computed output basename (without extension).
        ext: File extension (without dot).
        overwrite: If True (default), return the natural path even if it exists
                   (it will be overwritten on save). If False, and the natural
                   path already exists, append " (1)", " (2)", ... until a free
                   name is found, so previous outputs are never clobbered.

    Returns:
        Full destination path. Parent directories are created.
    """
    src_dir = os.path.dirname(os.path.abspath(src_path))
    input_root = os.path.abspath(input_root)

    # Mirror the relative sub-path of the source dir under the output root.
    try:
        rel_dir = os.path.relpath(src_dir, input_root)
    except ValueError:
        # Different drive on Windows etc. - fall back to flat.
        rel_dir = ""
    if rel_dir == os.curdir or rel_dir.startswith(".."):
        rel_dir = ""

    dest_dir = os.path.join(output_root, rel_dir) if rel_dir else output_root
    os.makedirs(dest_dir, exist_ok=True)

    candidate = os.path.join(dest_dir, f"{save_as_name}.{ext}")
    if overwrite or not os.path.exists(candidate):
        return candidate

    # Don't overwrite: find the next free " (n)" suffix.
    n = 1
    while True:
        candidate = os.path.join(dest_dir, f"{save_as_name} ({n}).{ext}")
        if not os.path.exists(candidate):
            return candidate
        n += 1


def process_image(path: str,
                  add_exif: bool,
                  add_palette: bool,
                  border_type: BorderType,
                  font: tuple,
                  boldfont: tuple,
                  fontdir: str,
                  output_root: str,
                  input_root: str = None,
                  progress_cb=None,
                  preview_max_edge: int = None,
                  target_ratio: float = None,
                  overwrite: bool = True,
                  rotate: int = 0,
                  auto_orient: bool = True,
                  custom_text: str = None,
                  custom_font: tuple = None,
                  custom_size_mult: float = 1.0,
                  custom_centered: bool = False,
                  placements: dict = None,
                  geometry_out: dict = None,
                  preview_source=None) -> str:
    """Add a border to an image and save it into output_root.

    Supported image types: jpg, jpeg, png.

    Args:
        path: The image file path.
        add_exif: Add photo exif information to the border.
        add_palette: Add colour palette information to the border.
        border_type: The type of border to add.
        font: (fontFileName, fontVariantIndex).
        boldfont: (fontFileName, fontVariantIndex).
        fontdir: Directory containing the font files.
        output_root: Folder to write the output into.
        input_root: Root folder the scan started from, used to mirror sub-folder
                    structure in the output. Defaults to the file's own directory.
        progress_cb: Optional callable(stage_name: str, fraction: float). Called
                     as each stage completes. None disables reporting (used by
                     parallel workers). fraction is 0..1 across the whole file.
        preview_max_edge: If set, the SOURCE image is downscaled so its longest
                          edge is at most this many pixels BEFORE processing.
                          Used only for previews. Note: because border and font
                          sizes are derived from absolute pixel dimensions, a
                          preview produced this way is proportionally accurate
                          only if the same downscale is applied consistently -
                          which it is, since the whole pipeline runs on the
                          downscaled copy. See GUI for how this is used.
        target_ratio: Optional final canvas width/height ratio to pad to (adds
                      border on the deficient axis, never crops). None = native.
        rotate: Degrees CLOCKWISE, one of ROTATIONS. Applied after auto-orientation
                and before the border is sized, so a rotated landscape gets a
                portrait's border.
        auto_orient: Honour the file's EXIF Orientation tag by baking it into the
                     pixels (default). The output's tag is reset to 1 either way,
                     so a viewer cannot rotate the finished canvas a second time.
        custom_text: Optional literal caption drawn beside the EXIF block.
        custom_font: (file, index, weight) for that caption.
        custom_size_mult: Multiplier on its automatic size.
        custom_centered: Put it in the band's centre when the centre is free.
        placements: {element: layout.Placement} for 'exif', 'text', 'palette'.
                    Passing all-defaults is byte-identical to passing None.
        geometry_out: Optional dict filled with the rendered canvas/band/element
                      boxes. This is how the GUI gets its draggable outlines.
        preview_source: A PreviewSource from build_preview_source, reusing the
                        decode + downscale + palette extraction across renders.
                        The caller keeps ownership; this must not close it.

    Returns:
        The output path, or None if the file type was unsupported.
    """
    cb = progress_cb or _noop

    filetypes = list(FILETYPES)
    path_dot_parts = path.split('.')
    ext = path_dot_parts[-1:][0]
    filename = os.path.basename(".".join(path_dot_parts[:-1]))

    if not ext or ext.lower() not in filetypes:
        logger.error(f'Image must be one of {filetypes}')
        return None

    if input_root is None:
        input_root = os.path.dirname(os.path.abspath(path))

    # --- open -------------------------------------------------------------
    # EXIF is read from the file before any transform: the metadata we caption
    # with is independent of pixel size and orientation.
    if add_exif:
        with Image.open(path) as probe:
            exif = get_exif(probe)
    else:
        exif = None

    # Orientation, rotation and the preview downscale all happen here, before
    # create_border, because every border dimension comes from img.width/height.
    borrowed = preview_source is not None
    if borrowed:
        # Almost none of a preview's cost depends on the layout. Measured on a
        # 29.5MP JPEG: decode 208ms, downscale 65ms, extract palette colours
        # 424ms, and only ~30ms of border/caption/save. Reusing the first three
        # is what makes live dragging possible at full preview quality.
        img = preview_source.image
        if exif is None and add_exif:
            exif = preview_source.exif
    else:
        img = open_oriented(path, rotate=rotate, auto_orient=auto_orient,
                            preview_max_edge=preview_max_edge)
    cb("open", 0.15)

    # --- border -----------------------------------------------------------
    border = create_border(img.width, img.height, border_type, target_ratio=target_ratio)
    img_with_border = draw_border(img, border)
    save_as = f'{filename}_border-{border.border_type}'
    if rotate:
        # Same per-feature pattern as _exif and _palette. Auto-orientation adds
        # no suffix: it corrects a file to its own stated intent rather than
        # applying a choice the user made.
        save_as = f'{save_as}_rot{int(rotate) % 360}'
    cb("border", 0.35)

    # --- palette (compute early so EXIF text can avoid it) ----------------
    # The palette image is rendered first (but pasted last) so we know its
    # footprint before sizing the EXIF text. In the polaroid layout the text is
    # left-aligned and the palette sits bottom-right, so the text must be sized to
    # fit the space to the LEFT of the palette or it collides (which it did on
    # real EXIF strings). For centered border types the text is centered and this
    # constraint does not apply.
    color_palette = None
    palette_x = palette_y = 0
    palette_size = 0
    available_text_width = None
    pal_place = (placements or {}).get("palette") or layout_mod.Placement()
    # Choosing an alignment or dragging is a statement of position, taken
    # literally - so a hand-placed palette leaves the automatic negotiation
    # entirely. It must stop constraining right_bound too, not just move:
    # otherwise the caption is still made to dodge it, by shrinking instead of
    # moving (measured: 110x35 -> 75x24 px when the palette was dragged towards
    # the middle). Resizing someone's caption to avoid a collision is still
    # preventing the overlap they asked for.
    #
    # A size_mult change is NOT a move: a bigger palette in its default corner
    # still gets routed around.
    palette_hand_placed = (pal_place.anchor is not None
                           or pal_place.x is not None
                           or pal_place.y is not None)
    if add_palette:
        # Use the caption band (original per-type bottom border), not the possibly
        # ballooned border.bottom, so the palette stays a sensible size and sits in
        # the bottom band rather than scaling up / floating mid-canvas when a wide
        # photo is padded to a tall ratio.
        band = border.caption_band or border.bottom
        palette_size = max(1, round(band / 3 * float(pal_place.size_mult or 1.0)))
        if borrowed and preview_source.colors is not None:
            color_palette = render_color_platte(preview_source.colors, palette_size)
        else:
            color_palette = load_image_color_palette(img, palette_size)
        margin = round(palette_size / 2)
        # Anchor the palette to the bottom-right corner of the PHOTO horizontally,
        # and to the caption band at the bottom of the canvas vertically.
        image_right_edge = border.left + img.width
        palette_x = image_right_edge - color_palette.width - margin
        band_top = img_with_border.height - band
        palette_y = band_top + round(band / 2) - round(color_palette.height / 2)

    # Width budget for left-anchored caption text. POLAROID stacks it vertically;
    # SMALL/MEDIUM lay it out in a single horizontal row. Either way the text starts
    # at border.left and must stay clear of the palette (when present) or the photo's
    # right edge, or it overflows / collides. LARGE centres its caption, so it
    # doesn't use this budget.
    # right_bound is computed for EVERY border type, because the custom text needs
    # it even on LARGE (which does not use a left-anchored EXIF budget). Giving
    # LARGE the photo's width instead would let a long centred string run straight
    # across the palette.
    if color_palette is not None and not palette_hand_placed:
        right_bound = palette_x - palette_size           # leave one cell before the palette
    else:
        right_bound = border.left + img.width            # stay within the photo's width
    if border_type in (BorderType.POLAROID, BorderType.SMALL, BorderType.MEDIUM):
        available_text_width = max(50, right_bound - border.left)

    # The effective centring flag is decided HERE, before the width budget is
    # picked, so the two always agree. On SMALL/MEDIUM with EXIF on the custom
    # text is a segment of the single caption row, so centring it would draw it
    # on top of the caption - the flag is a no-op there, and it must be a no-op
    # without also changing the text's SIZE, which is why this cannot be left to
    # border.draw_exif.
    effective_centered = bool(custom_centered)
    if border_type in (BorderType.SMALL, BorderType.MEDIUM) and add_exif and exif:
        effective_centered = False

    # --- palette placement -------------------------------------------------
    band_for_layout = border.caption_band or border.bottom
    band_region = (border.left, img_with_border.height - band_for_layout,
                   img_with_border.width - border.right, img_with_border.height)
    palette_box = None
    if color_palette is not None:
        auto_box = (palette_x, palette_y,
                    palette_x + color_palette.width, palette_y + color_palette.height)
        dx, dy = layout_mod.resolve_offset(
            auto_box, band_region, pal_place,
            layout_mod.default_anchor("palette", border_type.name), img_with_border.width)
        palette_x = round(palette_x + dx)
        palette_y = round(palette_y + dy)
        palette_box = (palette_x, palette_y,
                       palette_x + color_palette.width, palette_y + color_palette.height)

    # --- exif -------------------------------------------------------------
    # A caption is drawn whenever there is EXIF to draw OR a custom string, so a
    # custom credit still renders with "Print EXIF on border" switched off.
    if (add_exif and exif) or custom_text:
        font_index = font[1] if len(font) > 1 else 0
        font_weight = font[2] if len(font) > 2 else None
        bold_index = boldfont[1] if len(boldfont) > 1 else 0
        bold_weight = boldfont[2] if len(boldfont) > 2 else None
        font_path = os.path.join(fontdir, font[0])
        bold_font_path = os.path.join(fontdir, boldfont[0])

        custom_spec = None
        if custom_text and custom_font:
            custom_spec = (os.path.join(fontdir, custom_font[0]),
                           custom_font[1] if len(custom_font) > 1 else 0,
                           custom_font[2] if len(custom_font) > 2 else None)

        checks = [(font_path, font_index, font_weight),
                  (bold_font_path, bold_index, bold_weight)]
        if custom_spec:
            checks.append(custom_spec)
        # Reported once, up front: a bad weight on a variable font would
        # otherwise degrade into a caption drawn at the wrong weight, which
        # nothing visibly fails on.
        error_messages = [err for f in checks
                          if (err := validate_font(fontpath=f[0], index=f[1], weight=f[2]))]
        if len(error_messages) > 0:
            raise ValueError(error_messages)

        # With EXIF off the caption lines are empty strings, so the block
        # measures to nothing and only the custom text is laid out.
        exif_data = exif if (add_exif and exif) else {
            'Make': '', 'Model': '', 'LensMake': '', 'LensModel': '',
            'FNumber': '', 'FocalLength': '', 'ISOSpeedRatings': '', 'ExposureTime': ''}

        img_with_border = draw_exif(
            img_with_border, exif_data, border,
            (font_path, font_index, font_weight), (bold_font_path, bold_index, bold_weight),
            available_width=available_text_width,
            custom_text=custom_text, custom_font=custom_spec,
            custom_size_mult=custom_size_mult, custom_centered=effective_centered,
            placements=placements, geometry_out=geometry_out, palette_box=palette_box,
            right_bound=right_bound)
        if add_exif and exif:
            save_as = f'{save_as}_exif'
    cb("exif", 0.55)

    # --- palette (overlay now, on top of the border) ----------------------
    if add_palette and color_palette is not None:
        img_with_border = overlay_palette(img=img_with_border,
                                          color_palette=color_palette,
                                          offset=(palette_x, palette_y))
        save_as = f'{save_as}_palette'
    cb("palette", 0.8)

    # --- save -------------------------------------------------------------
    # quality=95 + subsampling=0 keeps red edges sharp. See original notes.
    save_path = resolve_output_path(path, input_root, output_root, save_as, ext, overwrite=overwrite)
    exifdata = img.getexif()
    # The orientation is already baked into the pixels, so re-emitting the source
    # tag makes any viewer that honours it turn the finished canvas - caption band
    # and all - a second time. That was a real bug; reset it rather than pass it on.
    try:
        exifdata[ORIENTATION_TAG] = 1
    except Exception:  # noqa: BLE001 - a file with no writable exif block
        pass
    img_with_border.save(save_path, exif=exifdata, subsampling=0, quality=95)

    img_with_border.close()
    # A borrowed preview source belongs to the caller, which reuses it across
    # renders; closing it here would invalidate their cache after one frame.
    if not borrowed:
        img.close()
    cb("save", 1.0)

    return save_path
