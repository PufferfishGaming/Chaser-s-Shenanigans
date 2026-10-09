"""
Placements are remembered per aspect ratio in the PhotoBorder window.

Set a placement for 16:9, set another for 4:5, go back to 16:9: the 16:9 one
comes back. Also checks the round trip through settings, on a throwaway INI file
so the user's own saved state is never read back into or written over.
"""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PySide6 import QtCore, QtWidgets               # noqa: E402
except ImportError as exc:                              # pragma: no cover
    pytest.skip(f"PySide6/Qt unavailable: {exc}", allow_module_level=True)

from layout import Placement                            # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def win(qt_app, tmp_path):
    from photoborder_gui import MainWindow
    w = MainWindow()
    # Swap in a private settings store before anything is saved.
    w.settings = QtCore.QSettings(str(tmp_path / "pb.ini"), QtCore.QSettings.IniFormat)
    w.preview_source = None       # no renders
    return w


def _select(win, value):
    idx = win.ratio_combo.findData(value)
    assert idx >= 0, value
    win.ratio_combo.setCurrentIndex(idx)


def test_each_ratio_keeps_its_own_placements(win):
    from photoborder_gui import IG_LANDSCAPE
    wide, portrait = 16 / 9, 4 / 5
    _select(win, wide)
    win.placements["exif"] = Placement(x=0.3, y=0.2, size_mult=1.5)
    _select(win, portrait)
    # A ratio never set up starts from the defaults, not from 16:9's layout.
    assert win.placements["exif"] == Placement()
    win.placements["palette"] = Placement(anchor="left")
    _select(win, IG_LANDSCAPE)
    win.placements["text"] = Placement(anchor="right")

    _select(win, wide)
    assert win.placements["exif"] == Placement(x=0.3, y=0.2, size_mult=1.5)
    assert win.placements["palette"] == Placement()
    # The controls show the restored placement, not the previous ratio's.
    assert win._place_widgets["exif"]["size"].value() == pytest.approx(1.5)

    _select(win, portrait)
    assert win.placements["palette"] == Placement(anchor="left")
    assert win.placements["exif"] == Placement()
    _select(win, IG_LANDSCAPE)
    assert win.placements["text"] == Placement(anchor="right")


def test_per_ratio_placements_survive_a_restart(win, qt_app):
    from photoborder_gui import MainWindow
    _select(win, 16 / 9)
    win.placements["exif"] = Placement(anchor="right")
    _select(win, 4 / 5)
    win.placements["exif"] = Placement(anchor="center")
    win._save_settings()

    again = MainWindow()
    again.settings = win.settings
    again.preview_source = None
    again._load_settings()
    again.preview_source = None
    assert again.ratio_combo.currentData() == pytest.approx(4 / 5)
    assert again.placements["exif"] == Placement(anchor="center")
    _select(again, 16 / 9)
    assert again.placements["exif"] == Placement(anchor="right")


def test_old_single_placement_setting_becomes_the_current_ratios(win):
    import json
    import layout as layout_mod
    s = win.settings
    s.setValue("ratio_index", win.ratio_combo.findData(16 / 9))
    s.setValue("placements", json.dumps(layout_mod.placements_to_settings(
        {"exif": Placement(anchor="right")})))
    s.remove("placements_by_ratio")
    win._load_settings()
    win.preview_source = None
    assert win.placements["exif"] == Placement(anchor="right")
    _select(win, 4 / 5)
    assert win.placements["exif"] == Placement()
    _select(win, 16 / 9)
    assert win.placements["exif"] == Placement(anchor="right")


def test_instagram_mode_params(win):
    from photoborder_gui import IG_LANDSCAPE
    _select(win, IG_LANDSCAPE)
    p = win._current_params()
    assert p["slides"] == 2 and p["target_ratio"] == pytest.approx(1.6)
    assert "4:5" in win.ratio_hint.text()
    _select(win, None)
    p = win._current_params()
    assert p["slides"] == 1 and p["target_ratio"] is None
    assert win.ratio_hint.text() == ""


def test_one_custom_text_size_control(win):
    """The Typography "Text size" box was merged into the Placement grid's Text Size."""
    assert not hasattr(win, "text_size_spin")
    assert "custom_size_mult" not in win._current_params()
    win._place_widgets["text"]["size"].setValue(1.7)
    assert win._current_params()["placements"]["text"].size_mult == pytest.approx(1.7)


def test_old_text_size_setting_folds_into_every_ratios_text_size(win):
    import json
    import layout as layout_mod
    s = win.settings
    s.setValue("ratio_index", win.ratio_combo.findData(16 / 9))
    s.setValue("text_size_mult", 1.5)
    s.setValue("placements_by_ratio", json.dumps({
        "1.7778": layout_mod.placements_to_settings({"text": Placement(size_mult=1.2)}),
        "0.8000": layout_mod.placements_to_settings({"text": Placement(anchor="right")}),
    }))
    win._load_settings()
    win.preview_source = None
    assert win.placements["text"].size_mult == pytest.approx(1.8)
    assert win._place_widgets["text"]["size"].value() == pytest.approx(1.8)
    _select(win, 4 / 5)
    assert win.placements["text"] == Placement(anchor="right", size_mult=1.5)
    # Folded once: the key is gone, so a reload does not multiply again.
    assert s.value("text_size_mult") is None
    win._save_settings()
    win._load_settings()
    win.preview_source = None
    assert win.placements["text"].size_mult == pytest.approx(1.5)
