"""Tests for Quick Edit's film simulations (quickedit_core).

Headless: builds a synthetic colourful scene and checks every stock produces
valid, deterministic output with the character it advertises (saturation
ordering, B&W neutrality, grain behaviour).
"""
import numpy as np
import pytest

import quickedit_core as qe


def _scene():
    """A synthetic scene with sky gradient, colour patches and a gray ramp."""
    h, w = 120, 160
    img = np.zeros((h, w, 3), np.float32)
    # sky: blue -> warm horizon
    for y in range(60):
        t = y / 59
        img[y, :] = (0.25 + 0.55 * t, 0.35 + 0.30 * t, 0.75 - 0.35 * t)
    # colour patches
    patches = [(0.75, 0.2, 0.2), (0.2, 0.65, 0.25), (0.2, 0.3, 0.75),
               (0.85, 0.7, 0.55), (0.9, 0.85, 0.2), (0.5, 0.25, 0.55)]
    for i, c in enumerate(patches):
        img[60:90, i * 26:(i + 1) * 26] = c
    # gray ramp
    img[90:, :] = np.linspace(0, 1, w, dtype=np.float32)[None, :, None]
    return img


def _chroma(img):
    l = img @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    return float(np.mean(np.abs(img - l[..., None])))


def test_film_names_lists_none_first():
    names = qe.film_names()
    assert names[0] == "None"
    assert len(names) == len(qe.FILM_SIMS) + 1


@pytest.mark.parametrize("name", list(qe.FILM_SIMS))
def test_every_film_is_valid_and_deterministic(name):
    img = _scene()
    a = qe._apply_film(img, name, grain=True)
    b = qe._apply_film(img, name, grain=True)
    assert a.shape == img.shape
    assert np.isfinite(a).all()
    assert a.min() >= 0.0 and a.max() <= 1.0
    assert np.array_equal(a, b)          # fixed-seed grain: reproducible


def test_bw_films_are_neutral():
    img = _scene()
    for name in ("Ilford HP5 Plus 400", "Kodak Tri-X 400", "Fujifilm Acros 100"):
        out = qe._apply_film(img, name)
        assert np.allclose(out[..., 0], out[..., 1])
        assert np.allclose(out[..., 1], out[..., 2])


def test_saturation_character_ordering():
    img = _scene()
    velvia = _chroma(qe._apply_film(img, "Fujifilm Velvia 50"))
    provia = _chroma(qe._apply_film(img, "Fujifilm Provia 100F"))
    portra = _chroma(qe._apply_film(img, "Kodak Portra 400"))
    base = _chroma(img)
    assert velvia > provia > portra          # vivid slide > neutral slide > soft negative
    assert velvia > base                     # Velvia saturates
    # NOTE deliberately no `portra < base`: Portra desaturates (sat 0.92) but its
    # warm cast adds chroma in this crude metric, netting out roughly neutral.


def test_gold_is_warmer_and_cinestill_cooler_than_source():
    img = _scene()
    def rb_balance(x):                       # mean red minus mean blue
        return float(x[..., 0].mean() - x[..., 2].mean())
    assert rb_balance(qe._apply_film(img, "Kodak Gold 200")) > rb_balance(img)
    assert rb_balance(qe._apply_film(img, "CineStill 800T")) < rb_balance(img)


def test_grain_toggle_and_no_film_default():
    img = _scene()
    clean = qe._apply_film(img, "Kodak Portra 400", grain=False)
    grainy = qe._apply_film(img, "Kodak Portra 400", grain=True)
    assert not np.array_equal(clean, grainy)
    assert abs(float(grainy.mean() - clean.mean())) < 0.01    # grain adds noise, not brightness
    # grain with no film selected: subtle default, still valid
    only_grain = qe._apply_film(img, "", grain=True)
    assert not np.array_equal(only_grain, img)
    assert only_grain.min() >= 0.0 and only_grain.max() <= 1.0


def test_unknown_film_raises():
    with pytest.raises(ValueError, match="Unknown film"):
        qe._apply_film(_scene(), "Kodak Imaginary 9000")


def test_pipeline_integration():
    img = _scene()
    p = qe.EditParams(film="Fujifilm Velvia 50", grain=True, temp=0.1)
    out = qe.apply_pipeline(img, p)
    assert out.shape == img.shape
    assert np.isfinite(out).all()
    # round-trips through the dict serialisation the GUI uses
    p2 = qe.EditParams.from_dict(p.to_dict())
    assert p2.film == p.film and p2.grain == p.grain
    assert np.array_equal(qe.apply_pipeline(img, p2), out)
