import os
import pytest
from PIL import ImageFont
from text import create_font, load_font_variants



def test_font_index():
    fontname = 'Roboto-Regular.ttf'
    moduledir = os.path.dirname(os.path.abspath(__file__))
    fontdir = os.path.join(moduledir, "../fonts")
    font_path = os.path.join(fontdir, fontname)
    index = 20
    variants = []

    try:
        font = create_font(size=12, fontpath=font_path, index=index)
    except Exception:
        variants = load_font_variants(fontpath=font_path)
        print(f'Error loading {fontname} font variant {index}. Available variants: {variants}')
        assert len(variants) is not 0

    for variant in variants:
        try:
            font = create_font(size=12, fontpath=font_path, index=variant[0])
            print(f'{variant[1]} loaded')
        except Exception as exc:
            pytest.fail(f'Unexpected eception raised: {exc}')




def test_variable_font_weights_differ():
    """A variable font must actually render at the requested weight.

    This is the trap the font catalogue exists to avoid: a variable font loaded
    without selecting an axis position renders at its *default* instance, and for
    Cormorant Garamond that default is Light, not Regular. If `create_font`
    silently ignored the weight, the EXIF heading would be indistinguishable from
    the body text and nothing would visibly fail.
    """
    from text import measure_text_width, load_font_weights
    fontdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../fonts")
    path = os.path.join(fontdir, "CormorantGaramond-VF.ttf")

    weights = load_font_weights(path)
    assert 'Regular' in weights and 'SemiBold' in weights, weights

    regular = measure_text_width('FUJIFILM X-T5', 64, path, 0, 'Regular')
    semibold = measure_text_width('FUJIFILM X-T5', 64, path, 0, 'SemiBold')
    light = measure_text_width('FUJIFILM X-T5', 64, path, 0, None)
    assert semibold > regular > light, (light, regular, semibold)


def test_static_font_ignores_weight_without_raising():
    """Passing a weight to a static font degrades silently, per house rules."""
    from text import create_font, validate_font
    fontdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../fonts")
    path = os.path.join(fontdir, "GreatVibes-Regular.ttf")
    assert validate_font(path, 0, 'Bold') is None
    assert create_font(48, path, 0, 'Bold').size == 48


def test_bad_weight_name_is_reported_not_swallowed():
    """A typo'd weight on a variable font must fail loudly, once, up front."""
    from text import validate_font
    fontdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../fonts")
    path = os.path.join(fontdir, "EBGaramond-VF.ttf")
    err = validate_font(path, 0, 'UltraHeavy')
    assert err and 'UltraHeavy' in err


def test_every_catalogue_family_loads():
    """Every family the GUI and CLI offer must resolve to a loadable font."""
    import fontcatalog
    from text import validate_font
    fontdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../fonts")
    for fam in fontcatalog.all_families():
        for bold in (False, True):
            name, index, weight = fontcatalog.spec(fam.key, bold=bold)
            err = validate_font(os.path.join(fontdir, name), index, weight)
            assert err is None, f"{fam.key} (bold={bold}): {err}"
