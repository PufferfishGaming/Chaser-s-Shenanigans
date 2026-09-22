from exif import ExifItem

def test_ExifItem():
    itm = ExifItem('FocalLength', '23  ')
    assert str(itm) == '23mm'
    itm = ExifItem('UnknownItem', ' Bleh  ')
    assert str(itm) == 'Bleh'


def test_control_characters_are_stripped_from_exif_text():
    """Cameras NUL-pad ASCII EXIF strings; those NULs must never reach the render.

    `str.strip()` removes whitespace but not control characters, so they used to
    survive - and whether they were VISIBLE depended on the font. Roboto and EB
    Garamond map NUL to a zero-width glyph, while Cormorant Garamond, Libre
    Baskerville and Lora map it to a .notdef box, which is why the caption grew
    boxes in exactly three of the five EXIF fonts.
    """
    from exif import ExifItem, clean_exif_text

    assert str(ExifItem('Make', 'FUJIFILM\x00')) == 'Shot on FUJIFILM'
    assert str(ExifItem('Model', 'X-M1\x00\x00\x00')) == 'X-M1'
    # An all-control value collapses to empty rather than to a row of boxes.
    assert str(ExifItem('Model', '\x00\x00')) == ''
    # Bytes that failed to decode in get_exif must not render as "b'\\x00...'".
    assert str(ExifItem('LensModel', b'XF16-55\x00\xff')) == 'XF16-55'
    # Whitespace-like controls become spaces so words are not joined together.
    assert clean_exif_text('line1\nline2') == 'line1 line2'
    assert clean_exif_text('a​b') == 'ab'      # zero-width space (Cf)
    assert clean_exif_text('  spaced   out  ') == 'spaced out'


def test_boxed_glyphs_no_longer_widen_the_measured_string():
    """The stripped NULs also stop inflating the measured text width.

    The boxes were not only ugly: they were measured, so the width-constrained
    sizing shrank real text to make room for them.
    """
    import os
    from PIL import Image, ImageDraw
    from text import create_font
    from exif import ExifItem

    fontdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../fonts")
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for name, weight in [("Lora-VF.ttf", "Regular"),
                         ("LibreBaskerville-VF.ttf", "Regular"),
                         ("CormorantGaramond-VF.ttf", "Regular")]:
        font = create_font(48, os.path.join(fontdir, name), 0, weight)
        clean = draw.textlength(str(ExifItem('Model', 'X-M1')), font=font)
        padded = draw.textlength(str(ExifItem('Model', 'X-M1\x00\x00\x00')), font=font)
        assert clean == padded, f"{name}: NUL padding still affects measured width"
