"""
Preview-canvas tests: hit-testing and the screen -> canvas coordinate mapping.

Skipped when PySide6 is unavailable, and forced onto the offscreen Qt platform
otherwise, so the suite still runs without a display.

Why a drag moves an outline and not the element: one render of the real pipeline
takes ~650ms with the palette on, and a drag needs ~16ms a frame - about 40x out.
So the rectangle moves live and the pipeline runs once on release. What has to be
right, and is what these tests pin down, is the arithmetic in between: the
preview pixmap may itself be a downscaled render of a much larger canvas, so
there are two scale factors between a mouse position and a stored fraction.
"""
import os

import pytest

# The offscreen platform has to be selected BEFORE Qt is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys                                              # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# `pytest.importorskip` is not enough here, twice over. Importing the `PySide6`
# package succeeds on a headless box and it is the Qt submodule that fails; and
# since pytest 8 importorskip only swallows ModuleNotFoundError, so a missing
# shared library (libEGL) propagates and errors the whole collection instead of
# skipping. Hence the explicit guard.
try:
    from PySide6 import QtCore, QtGui, QtWidgets       # noqa: E402
except ImportError as exc:                              # pragma: no cover
    pytest.skip(f"PySide6/Qt unavailable: {exc}", allow_module_level=True)

CANVAS = (1874, 1430)
BAND = (37, 1237, 1837, 1430)
BOXES = {
    "exif": (37, 1284, 273, 1362),
    "palette": (1741, 1301, 1805, 1365),
    "text": (37, 1372, 300, 1400),
}
GEOM = {"canvas": CANVAS, "band": BAND, "boxes": BOXES,
        "anchors": {"exif": "left", "text": "left", "palette": "right"}}


@pytest.fixture(scope="module")
def qt_app():
    from PySide6 import QtWidgets as W
    return W.QApplication.instance() or W.QApplication([])


@pytest.fixture
def canvas(qt_app):
    from photoborder_gui import PreviewCanvas
    c = PreviewCanvas()
    c.resize(900, 700)
    pm = QtGui.QPixmap(*CANVAS)
    pm.fill(QtGui.QColor("white"))
    c.set_render(pm, GEOM)
    c.show()
    qt_app.processEvents()
    return c


def _widget_pt(canvas, cx, cy):
    origin, scale = canvas._fit()
    return QtCore.QPoint(int(origin.x() + cx * scale), int(origin.y() + cy * scale))


def _send(canvas, kind, pt):
    types = {"press": QtCore.QEvent.MouseButtonPress,
             "move": QtCore.QEvent.MouseMove,
             "release": QtCore.QEvent.MouseButtonRelease}
    ev = QtGui.QMouseEvent(types[kind], QtCore.QPointF(pt), QtCore.Qt.LeftButton,
                           QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)
    {"press": canvas.mousePressEvent, "move": canvas.mouseMoveEvent,
     "release": canvas.mouseReleaseEvent}[kind](ev)


@pytest.mark.parametrize("name", sorted(BOXES))
def test_each_element_is_hit_at_its_centre(canvas, name):
    box = BOXES[name]
    pt = _widget_pt(canvas, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    assert canvas._hit(pt) == name


def test_empty_band_is_not_a_hit(canvas):
    assert canvas._hit(_widget_pt(canvas, 900, 1260)) is None


def test_smallest_overlapping_box_wins(canvas):
    """A small element inside a large one must still be grabbable.

    Once the caption is dragged around, boxes overlap - and the caption block is
    far larger than the palette, so a "first match" hit test would make the
    palette impossible to pick up.
    """
    geom = dict(GEOM, boxes=dict(BOXES, exif=(0, 1240, 1870, 1428)))
    pm = QtGui.QPixmap(*CANVAS)
    pm.fill(QtGui.QColor("white"))
    canvas.set_render(pm, geom)
    pal = BOXES["palette"]
    pt = _widget_pt(canvas, (pal[0] + pal[2]) / 2, (pal[1] + pal[3]) / 2)
    assert canvas._hit(pt) == "palette"


def test_drag_maps_back_to_the_right_fractions(canvas):
    """The emitted fractions must match the canvas-space distance dragged.

    The palette is right-anchored, so its stored x is the fraction of canvas
    width of its RIGHT edge - not its centre - which is what keeps it put when
    the number of swatches changes.
    """
    got = {}
    canvas.moved.connect(lambda n, x, y: got.update(n=n, x=x, y=y))
    box = BOXES["palette"]
    start = _widget_pt(canvas, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    _, scale = canvas._fit()
    dx_canvas, dy_canvas = -300, -60
    end = QtCore.QPoint(start.x() + int(dx_canvas * scale), start.y() + int(dy_canvas * scale))

    _send(canvas, "press", start)
    _send(canvas, "move", end)
    _send(canvas, "release", end)

    assert got.get("n") == "palette"
    expected_x = (box[2] + dx_canvas) / CANVAS[0]
    expected_y = (((box[1] + box[3]) / 2) + dy_canvas - BAND[1]) / (BAND[3] - BAND[1])
    # Tolerance covers one widget pixel rounding, which is ~2 canvas px here.
    assert abs(got["x"] - expected_x) < 0.005, (got["x"], expected_x)
    assert abs(got["y"] - expected_y) < 0.02, (got["y"], expected_y)


def test_a_click_without_movement_does_not_place_the_element(canvas):
    """Clicking an element must not silently disable its automatic sizing.

    Any stored position marks the element hand-placed, which switches off its
    auto-fit - so an accidental click would be a hidden behaviour change.
    """
    got = {}
    canvas.moved.connect(lambda n, x, y: got.update(n=n))
    box = BOXES["exif"]
    pt = _widget_pt(canvas, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    _send(canvas, "press", pt)
    _send(canvas, "release", pt)
    assert got == {}, "a bare click emitted a placement"


# ---------------------------------------------------------------------------
# Live dragging
# ---------------------------------------------------------------------------
def _fresh_render(canvas, moved_box=None):
    """Simulate a live re-render arriving mid-drag."""
    boxes = dict(BOXES)
    if moved_box:
        boxes["exif"] = moved_box
    pm = QtGui.QPixmap(*CANVAS)
    pm.fill(QtGui.QColor("white"))
    canvas.set_render(pm, dict(GEOM, boxes=boxes))


def test_a_render_arriving_mid_drag_does_not_cancel_the_drag(canvas):
    """Live re-rendering calls straight back into `set_render`.

    `set_render` used to clear `_drag_element`, so the first rendered frame killed
    the drag: exactly one frame appeared, no further moves were tracked, and the
    mouse release did nothing at all.
    """
    box = BOXES["exif"]
    start = _widget_pt(canvas, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    _send(canvas, "press", start)
    assert canvas._drag_element == "exif"

    _fresh_render(canvas, moved_box=(137, 1284, 373, 1362))
    assert canvas._drag_element == "exif", "the in-progress drag was cancelled by a render"
    assert canvas._drag_ref is not None


def test_deltas_do_not_compound_across_live_renders(canvas):
    """Each delta maps against the PRESS-TIME box, not the live geometry.

    Mapping against the live geometry applies every delta to an already-moved
    box, so the element accelerates away from the cursor - it reached the clamp
    limit within a couple of frames.
    """
    positions = []
    canvas.dragging.connect(lambda n, x, y: positions.append(x))

    box = BOXES["exif"]
    start = _widget_pt(canvas, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    _, scale = canvas._fit()
    _send(canvas, "press", start)

    step_canvas = 100
    for i in (1, 2, 3):
        _send(canvas, "move",
              QtCore.QPoint(start.x() + int(step_canvas * i * scale), start.y()))
        # The pipeline reports the element at its new position between frames.
        _fresh_render(canvas, moved_box=(box[0] + step_canvas * i, box[1],
                                         box[2] + step_canvas * i, box[3]))

    assert len(positions) == 3, positions
    # x is the left edge as a fraction of canvas width, and the steps are equal,
    # so the reported positions must be evenly spaced.
    deltas = [positions[i + 1] - positions[i] for i in range(2)]
    expected = step_canvas / CANVAS[0]
    for d in deltas:
        assert abs(d - expected) < 0.01, (
            f"delta {d:.4f} != {expected:.4f}; positions compounded: {positions}")


def test_release_still_reports_after_live_frames(canvas):
    """The final position must be emitted even after mid-drag renders."""
    got = {}
    canvas.moved.connect(lambda n, x, y: got.update(n=n, x=x))
    box = BOXES["exif"]
    start = _widget_pt(canvas, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    _, scale = canvas._fit()
    _send(canvas, "press", start)
    end = QtCore.QPoint(start.x() + int(200 * scale), start.y())
    _send(canvas, "move", end)
    _fresh_render(canvas, moved_box=(box[0] + 200, box[1], box[2] + 200, box[3]))
    _send(canvas, "release", end)

    assert got.get("n") == "exif"
    assert abs(got["x"] - (box[0] + 200) / CANVAS[0]) < 0.01, got
    assert canvas._drag_element is None, "drag state not cleared on release"
    assert canvas._drag_ref is None


# ---------------------------------------------------------------------------
# Control panel width
# ---------------------------------------------------------------------------
def test_panel_width_follows_its_content(qt_app):
    """The control panel must never clip its own widgets.

    Its required width depends on the system font, the applied stylesheet, the
    display scaling and the locale's decimal separator, so it cannot be a constant
    - two hardcoded values were each wrong on some machine, the second clipping
    the reset buttons and the right end of every combo behind the preview area.
    """
    from photoborder_gui import MainWindow

    win = MainWindow()
    win.settings.clear()
    win = MainWindow()
    win.resize(1400, 1200)
    win.show()
    qt_app.processEvents()

    scroll, inner = win._panel_scroll, win._panel_scroll.widget()
    assert inner.sizeHint().width() <= scroll.viewport().width(), (
        f"content {inner.sizeHint().width()} exceeds viewport {scroll.viewport().width()}")

    # Nothing on the right-hand edge is cut off.
    for name, widget in (("border", win.border_combo), ("ratio", win.ratio_combo),
                         ("exif font", win.exif_font_combo),
                         ("line align", win.line_align_combo)):
        right = widget.geometry().x() + widget.geometry().width()
        assert right <= scroll.viewport().width() + 1, f"{name} clipped at {right}"
    for element, widgets in win._place_widgets.items():
        right = widgets["reset"].geometry().x() + widgets["reset"].geometry().width()
        assert right <= scroll.viewport().width() + 1, f"{element} reset button clipped"
    win.close()


def test_panel_grows_for_wider_content(qt_app):
    """Genuinely wider content must widen the panel rather than be clipped.

    The content is widened BEFORE the first show on purpose. A QComboBox defaults
    to `AdjustToContentsOnFirstShow`, so items added afterwards never change its
    size hint - which is also why this is a fair model of the real cause: the
    system font, stylesheet, scaling and locale are all fixed before the window
    appears, and it is those that made the panel too narrow on one machine and not
    another.
    """
    from photoborder_gui import MainWindow

    baseline = MainWindow()
    baseline.settings.clear()
    baseline = MainWindow()
    baseline.resize(1400, 1200)
    baseline.show()
    qt_app.processEvents()
    before = baseline._panel_scroll.width()
    baseline.close()

    win = MainWindow()
    win.border_combo.addItem("A deliberately very long border name to widen the panel")
    win.border_combo.setCurrentIndex(win.border_combo.count() - 1)
    win.resize(1400, 1200)
    win.show()
    qt_app.processEvents()
    win._fit_panel_width()
    qt_app.processEvents()

    assert win._panel_scroll.width() > before, (before, win._panel_scroll.width())
    inner = win._panel_scroll.widget()
    assert inner.sizeHint().width() <= win._panel_scroll.viewport().width()
    win.close()
