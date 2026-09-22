"""
 Add a border to the image named in the first parameter.
 A new image with {filename}_border... will be generated in the output directory.
 TODO: Read up on sorting images by appearance https://github.com/Visual-Computing/LAS_FLAS/blob/main/README.md
 """

import os
import argparse
import logging
from filemanager import should_include_file, get_directory_files
from border import BorderType
from core import process_image, ROTATIONS
import fontcatalog
import layout as layout_mod

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO, datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Named aspect-ratio presets -> width/height float. "native" / None = no padding.
RATIO_PRESETS = {
    "native": None,
    "1:1": 1.0,
    "4:5": 4 / 5,
    "5:4": 5 / 4,
    "3:2": 3 / 2,
    "2:3": 2 / 3,
    "16:9": 16 / 9,
    "9:16": 9 / 16,
}


def parse_ratio(value: str) -> float:
    """Parse a ratio string ('4:5', 'native', or 'W:H') into a float or None."""
    if value is None:
        return None
    key = value.strip().lower()
    if key in RATIO_PRESETS:
        return RATIO_PRESETS[key]
    if ":" in key:
        w, h = key.split(":", 1)
        w, h = float(w), float(h)
        if h == 0:
            raise ValueError("Ratio height cannot be zero")
        return w / h
    raise ValueError(f"Unrecognised ratio '{value}'. Use one of {list(RATIO_PRESETS)} or W:H.")


def parse_place(values):
    """Parse repeated --place NAME=ANCHOR[,HEIGHT%[,SIZE]] into a placements dict.

    e.g. --place palette=left --place exif=right,80,1.2
    """
    placements = layout_mod.default_placements()
    for raw in values or []:
        if "=" not in raw:
            raise ValueError(f"--place needs NAME=ANCHOR, got {raw!r}")
        name, spec = raw.split("=", 1)
        name = name.strip().lower()
        if name not in layout_mod.ELEMENTS:
            raise ValueError(f"--place name must be one of {layout_mod.ELEMENTS}, got {name!r}")
        parts = [p.strip() for p in spec.split(",")]
        anchor = parts[0].lower() or "default"
        if anchor in ("default", ""):
            anchor = None
        elif anchor not in layout_mod.ANCHORS:
            raise ValueError(f"--place anchor must be default/{'/'.join(layout_mod.ANCHORS)}, "
                             f"got {parts[0]!r}")
        y = None
        if len(parts) > 1 and parts[1] and parts[1].lower() != "auto":
            y = float(parts[1].rstrip("%")) / 100.0
        size = 1.0
        if len(parts) > 2 and parts[2]:
            size = float(parts[2])
        placements[name] = layout_mod.Placement(anchor=anchor, y=y, size_mult=size)
    return placements


def parse_arguments():
    parser = argparse.ArgumentParser(
        prog='python main.py',
        description='Add a border and exif data to jpg or png photos',
        epilog='Made for fun and to solve a little problem.'
    )
    # Optional so `--list-fonts` can run on its own, as the README shows. Absence
    # is checked in main() rather than by argparse, which would demand it here.
    parser.add_argument('path', nargs='?', default=None, help='File or directory path')
    parser.add_argument('-e', '--exif', action='store_true', default=False,
                        help='Print photo exif data on the border')
    parser.add_argument('-p', '--palette', action='store_true', default=False,
                        help='Add colour palette to the photo border')
    parser.add_argument('-t', '--border_type', type=BorderType, choices=list(BorderType), default=BorderType.SMALL,
                        help='Border Type: p for polaroid, s for small, m for medium, l for large')
    parser.add_argument('-r', '--recursive', action='store_true', default=False,
                        help='Process directories recursively')
    parser.add_argument('-o', '--output', default=None,
                        help='Output directory (default: a "bordered" folder next to the input)')
    parser.add_argument('--ratio', default='native',
                        help='Target output aspect ratio, padded with extra border (never crops). '
                             'One of: native, 1:1, 4:5, 5:4, 3:2, 2:3, 16:9, 9:16, or custom W:H.')
    parser.add_argument('--no-overwrite', action='store_true', default=False,
                        help='Never overwrite existing output files; append " (1)", " (2)", etc. instead')
    parser.add_argument('--include', nargs='+', default=['*.jpg', '*.jpeg', '*.png', '*.JPG', '*.JPEG', '*.PNG'],
                        help='File patterns to include')
    parser.add_argument('--exclude', nargs='+', default=["*_border*"],
                        help='File patterns to exclude (default: *_border*)')
    parser.add_argument('-f', '--font', default='Roboto-Regular.ttf', help='Font file in fonts directory')
    parser.add_argument('-fv', '--fontvariant', default=0, type=int, help='Font style variant index')
    parser.add_argument('-fb', '--fontbold', default='Roboto-Medium.ttf', help='Bold font file in fonts directory')
    parser.add_argument('-fbv', '--fontboldvariant', default=0, type=int, help='Bold font style variant index')
    parser.add_argument('--rotate', type=int, default=0, choices=list(ROTATIONS),
                        help='Rotate the photo clockwise before the border is sized. '
                             'Right angles only, which keeps it lossless.')
    parser.add_argument('--no-auto-orient', action='store_true', default=False,
                        help="Ignore the file's EXIF orientation tag (auto-orient is on by "
                             'default; this is for the rare file whose tag is wrong)')
    parser.add_argument('--exif-font', default=None, choices=fontcatalog.caption_keys(),
                        help='Font family for the EXIF caption')
    parser.add_argument('--text', default=None,
                        help='Literal custom text drawn on the bottom border')
    parser.add_argument('--text-font', default=None, choices=fontcatalog.keys(),
                        help='Font family for the custom text (script faces allowed here)')
    parser.add_argument('--text-size', type=float, default=1.0,
                        help='Multiplier on the automatic custom-text size (default 1.0)')
    parser.add_argument('--text-center', '--text-centre', dest='text_center',
                        action='store_true', default=False,
                        help="Centre the custom text. Applies to p and l; on s/m only without -e")
    parser.add_argument('--place', action='append', default=None,
                        help='NAME=ANCHOR[,HEIGHT%%[,SIZE]], repeatable. NAME is exif, text or '
                             'palette; ANCHOR is default, left, center or right; HEIGHT is 0-100 '
                             'or auto. e.g. --place exif=right,80,1.2')
    parser.add_argument('--list-fonts', action='store_true', default=False,
                        help='Print the bundled font families and exit')
    return parser.parse_args()


def print_fonts():
    rows = [("Family", "Key", "EXIF caption")]
    for fam in fontcatalog.all_families():
        rows.append((fam.label, fam.key, "no (custom text only)" if fam.display_only else "yes"))
    widths = [max(len(r[i]) for r in rows) for i in range(3)]
    for i, row in enumerate(rows):
        print("  ".join(cell.ljust(widths[j]) for j, cell in enumerate(row)))
        if i == 0:
            print("  ".join("-" * w for w in widths))


def main():
    args = parse_arguments()
    if args.list_fonts:
        print_fonts()
        return
    if not args.path:
        logger.error('A file or directory path is required.')
        return
    paths = []
    input_root = None

    if os.path.isdir(args.path):
        input_root = os.path.abspath(args.path)
        paths = get_directory_files(args.path, args.recursive, args.include, args.exclude)
    elif os.path.isfile(args.path):
        input_root = os.path.dirname(os.path.abspath(args.path))
        if should_include_file(args.path, args.include, args.exclude):
            paths.append(args.path)
        else:
            logger.info(f'Skipping {args.path} as it does not match the include/exclude patterns')
    else:
        logger.error(f'{args.path} is not a valid file or directory')
        return

    # Default output folder: a "bordered" directory next to the input.
    output_root = args.output or os.path.join(input_root, "bordered")
    os.makedirs(output_root, exist_ok=True)

    moduledir = os.path.dirname(os.path.abspath(__file__))
    fontdir = os.path.join(moduledir, "fonts")

    target_ratio = parse_ratio(args.ratio)
    placements = parse_place(args.place)

    # -f / -fb still take a bare filename and WIN over --exif-font, so existing
    # command lines and hand-dropped font files keep working unchanged.
    if args.exif_font and args.font == 'Roboto-Regular.ttf' and args.fontbold == 'Roboto-Medium.ttf':
        font_spec = fontcatalog.spec(args.exif_font)
        bold_spec = fontcatalog.spec(args.exif_font, bold=True)
    else:
        font_spec = (args.font, args.fontvariant)
        bold_spec = (args.fontbold, args.fontboldvariant)

    custom_spec = fontcatalog.spec(args.text_font) if (args.text and args.text_font) else (
        fontcatalog.spec(fontcatalog.DEFAULT_TEXT_KEY) if args.text else None)

    # Centring is unhonourable on a row layout that is already carrying the EXIF
    # caption. Say so once rather than failing or silently ignoring it.
    text_center = args.text_center
    if text_center and args.border_type in (BorderType.SMALL, BorderType.MEDIUM) and args.exif:
        logger.info('--text-center ignored: on %s the custom text shares the EXIF row. '
                    'Drop -e to centre it.', args.border_type.name.lower())
        text_center = False

    for path in paths:
        logger.info(f'Adding border to {path}')
        save_path = process_image(
            path=path,
            add_exif=args.exif,
            add_palette=args.palette,
            border_type=args.border_type,
            font=font_spec,
            boldfont=bold_spec,
            fontdir=fontdir,
            output_root=output_root,
            input_root=input_root,
            target_ratio=target_ratio,
            overwrite=not args.no_overwrite,
            rotate=args.rotate,
            auto_orient=not args.no_auto_orient,
            custom_text=args.text,
            custom_font=custom_spec,
            custom_size_mult=args.text_size,
            custom_centered=text_center,
            placements=placements,
        )
        logger.info(f'Saved as {save_path}')


if __name__ == "__main__":
    try:
        main()
    except ValueError as e:
        logger.error(e)
