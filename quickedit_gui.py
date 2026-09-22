"""Quick Edit - interactive white-balance + presets with a live preview.

Decodes once, keeps a full-resolution copy and a downscaled preview base, and
runs the (cheap) white-balance + look pipeline on the base while you drag
sliders, in a worker thread, debounced. Full resolution is only touched on
export. The core (quickedit_core) still supports gradient removal and tone
controls - this panel just exposes white balance and presets.

Frontend notes
--------------
Built on `ui` (components) and `theme` (colour). Three things the rebuild
changed and why:

* **Every slider shows its value.** Temperature and Tint could previously be
  moved but not *set*: the label said "Temperature (cool <-> warm)" and nothing
  said where the handle was, so a look could not be described, repeated or
  undone by eye. `ui.SliderField` puts the number in a fixed-width cell beside
  the label, which also stops the row reflowing as the number changes width.

* **Before/after is a hold, not a checkbox.** Holding the preview (or the space
  bar) shows the untouched image. An editing tool whose whole output is a
  judgement call needs the comparison to cost nothing; a toggle you have to
  click twice is not nothing.

* **The preview owns the empty state.** "No image loaded" as a bare string in
  the middle of a large rectangle told the user what was wrong but not what to
  do about it, and the only control that would fix it was on the far side of
  the window. The empty state carries the Open action and accepts a drop.
"""
from __future__ import annotations

import logging
import os

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

import quickedit_core as qe
import settings
import theme
import ui
from theme import ensure_applied

logger = logging.getLogger(__name__)

TOOL = "quickedit"
PREVIEW_MAX_EDGE = 1800          # higher base resolution -> crisper preview


def _to_pixmap(arr: np.ndarray) -> QtGui.QPixmap:
    a = np.ascontiguousarray((np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8))
    h, w, _ = a.shape
    qimg = QtGui.QImage(a.data, w, h, 3 * w, QtGui.QImage.Format_RGB888)
    return QtGui.QPixmap.fromImage(qimg.copy())


def _downscale(arr: np.ndarray, max_edge: int) -> np.ndarray:
    h, w = arr.shape[:2]
    if max(h, w) <= max_edge:
        return arr
    from PIL import Image
    im = Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8))
    f = max_edge / float(max(h, w))
    im = im.resize((max(1, int(w * f)), max(1, int(h * f))), Image.LANCZOS)
    return np.asarray(im).astype(np.float32) / 255.0


class PreviewWorker(QtCore.QThread):
    ready = QtCore.Signal(object)

    def __init__(self, base, params, bg):
        super().__init__()
        self.base, self.params, self.bg = base, params, bg

    def run(self):
        try:
            self.ready.emit(qe.apply_pipeline(self.base, self.params, bg=self.bg))
        except Exception as exc:  # noqa: BLE001
            logger.warning("preview failed: %r", exc)


class ExportWorker(QtCore.QThread):
    done = QtCore.Signal(str)
    failed = QtCore.Signal(str)

    def __init__(self, full, params, path, fmt_key, quality):
        super().__init__()
        self.full, self.params = full, params
        self.path, self.fmt_key, self.quality = path, fmt_key, quality

    def run(self):
        try:
            out = qe.apply_pipeline(self.full, self.params)
            qe.export_image(out, self.path, self.fmt_key, self.quality)
            self.done.emit(self.path)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class ImageView(QtWidgets.QWidget):
    """The preview surface: the edited image, or the empty state, or the original.

    Scaling happens in `paintEvent` from the stored pixmap rather than by
    writing a scaled pixmap into a QLabel. The QLabel version re-scaled on every
    resize event *and* kept the scaled copy alive, so dragging the window edge
    of a 1800px preview allocated a new full-size pixmap per frame.
    """

    dropped = QtCore.Signal(str)
    browse = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("preview_area")
        self.setAcceptDrops(True)
        self.setMinimumWidth(420)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self._pm = None
        self._original_pm = None
        self._showing_original = False

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.empty = ui.EmptyState(
            "image", "No image open",
            "Drop a photo here, or open one to start editing.",
            "Open image…")
        self.empty.action_btn.clicked.connect(self.browse.emit)
        lay.addWidget(self.empty)

    # -- content -----------------------------------------------------------
    def set_image(self, pm: QtGui.QPixmap) -> None:
        self._pm = pm
        self.empty.setVisible(False)
        self.update()

    def set_original(self, pm: QtGui.QPixmap) -> None:
        self._original_pm = pm

    def clear(self) -> None:
        self._pm = None
        self._original_pm = None
        self.empty.setVisible(True)
        self.update()

    # -- before/after ------------------------------------------------------
    def set_showing_original(self, on: bool) -> None:
        if on == self._showing_original:
            return
        self._showing_original = on and self._original_pm is not None
        self.update()

    def showing_original(self) -> bool:
        return self._showing_original

    # -- painting ----------------------------------------------------------
    def paintEvent(self, _e):
        pm = self._original_pm if self._showing_original else self._pm
        if pm is None or pm.isNull():
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        area = self.rect().adjusted(ui.SPACE_MD, ui.SPACE_MD, -ui.SPACE_MD, -ui.SPACE_MD)
        scaled = pm.size().scaled(area.size(), QtCore.Qt.KeepAspectRatio)
        target = QtCore.QRect(QtCore.QPoint(0, 0), scaled)
        target.moveCenter(area.center())
        p.drawPixmap(target, pm)
        if self._showing_original:
            self._draw_badge(p, target)

    def _draw_badge(self, p: QtGui.QPainter, target: QtCore.QRect) -> None:
        """A corner marker, so a held comparison can never be mistaken for the edit."""
        text = "ORIGINAL"
        font = p.font()
        font.setPointSizeF(max(8.0, font.pointSizeF() - 1))
        font.setBold(True)
        p.setFont(font)
        fm = QtGui.QFontMetrics(font)
        pad = 7
        w = fm.horizontalAdvance(text) + pad * 2
        h = fm.height() + pad
        box = QtCore.QRect(target.left() + 10, target.top() + 10, w, h)
        p.setPen(QtCore.Qt.NoPen)
        bg = QtGui.QColor(theme.palette_color("OVERLAY"))
        bg.setAlpha(215)
        p.setBrush(bg)
        p.drawRoundedRect(box, 5, 5)
        p.setPen(QtGui.QColor(theme.palette_color("ACCENT")))
        p.drawText(box, QtCore.Qt.AlignCenter, text)

    # -- input -------------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton and self._original_pm is not None:
            self.set_showing_original(True)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self.set_showing_original(False)
        super().mouseReleaseEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if p and os.path.isfile(p):
                self.dropped.emit(p)
                e.acceptProposedAction()
                return

    def retint(self):
        self.empty.retint()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Quick Edit")
        ensure_applied()
        self.setAcceptDrops(True)
        self.resize(1240, 800)
        _ic = theme.icon_path()
        if _ic:
            self.setWindowIcon(QtGui.QIcon(_ic))

        self.full = None
        self.base = None
        self.base_bg = None       # cached background model for the preview base
        self.path = None
        self.preview_worker = None
        self.export_worker = None
        self._last_arr = None

        self._build_ui()
        self._restore_geometry()

        # Debounced rather than throttled: a mid-drag render answers a question
        # the user has already moved past. 120ms is the measured pause between
        # deliberate slider steps on this pipeline.
        self._preview = ui.Debouncer(self._run_preview, 120, self)

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.panel = ui.Panel()
        p = self.panel

        head = QtWidgets.QVBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(2)
        title = QtWidgets.QLabel("Quick Edit")
        title.setObjectName("title")
        head.addWidget(title)
        sub = QtWidgets.QLabel("White balance, film simulations and one-click looks")
        sub.setObjectName("subtitle")
        sub.setWordWrap(True)
        head.addWidget(sub)
        p.add_layout(head)

        # -- source ---------------------------------------------------------
        self.drop = ui.DropZone("Drop a photo here", "or click to browse")
        self.drop.clicked.connect(self.open_image)
        self.drop.dropped.connect(lambda paths: self._load(paths[0]))
        p.add(self.drop)

        self.file_label = QtWidgets.QLabel("No image open")
        self.file_label.setObjectName("pathlabel")
        self.file_label.setWordWrap(True)
        p.add(self.file_label)

        # -- look -----------------------------------------------------------
        self.sec_look = ui.Collapsible("Look", True)
        look_grid = ui.FormGrid()
        self.preset_combo = QtWidgets.QComboBox()
        self.preset_combo.addItems(qe.preset_names())
        self.preset_combo.currentTextChanged.connect(self._schedule_preview)
        look_grid.add_row("Preset", self.preset_combo)

        self.film_combo = QtWidgets.QComboBox()
        self.film_combo.addItems(qe.film_names())
        self.film_combo.setToolTip(
            "Looks inspired by classic film stocks - parametric approximations "
            "of their character, not exact emulations.")
        self.film_combo.currentTextChanged.connect(self._schedule_preview)
        look_grid.add_row("Film", self.film_combo)
        self.sec_look.add_layout(look_grid)

        self.cb_grain = QtWidgets.QCheckBox("Film grain")
        self.cb_grain.setToolTip("Luminance grain matched to the chosen stock's speed "
                                 "(a subtle default when no film is selected).")
        self.cb_grain.toggled.connect(self._schedule_preview)
        self.sec_look.add(self.cb_grain)

        # The honest-framing note from the README belongs beside the control it
        # is about, not only in the tooltip of one combo.
        note = QtWidgets.QLabel("Inspired by the stocks' character - not exact emulations.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        self.sec_look.add(note)
        p.add(self.sec_look)

        # -- white balance ---------------------------------------------------
        self.sec_wb = ui.Collapsible("White balance", True)
        self.cb_autowb = QtWidgets.QCheckBox("Auto (gray-world)")
        self.cb_autowb.setToolTip("Gray-world balance. Can cool a night sky, because it "
                                  "assumes the average of the frame should be neutral.")
        self.cb_autowb.toggled.connect(self._schedule_preview)
        self.sec_wb.add(self.cb_autowb)

        self.s_temp = ui.SliderField("Temperature", -100, 100, 0, suffix="")
        self.s_temp.label.setToolTip("Negative is cooler, positive is warmer.")
        self.s_temp.valueChanged.connect(self._schedule_preview)
        self.sec_wb.add(self.s_temp)

        self.s_tint = ui.SliderField("Tint", -100, 100, 0, suffix="")
        self.s_tint.label.setToolTip("Negative is greener, positive is more magenta.")
        self.s_tint.valueChanged.connect(self._schedule_preview)
        self.sec_wb.add(self.s_tint)
        p.add(self.sec_wb)

        # -- light pollution -------------------------------------------------
        self.sec_lp = ui.Collapsible("Light pollution", False)
        self.s_gradient = ui.SliderField("Gradient removal", 0, 100, 0, suffix="%")
        self.s_gradient.label.setToolTip(
            "Fits and subtracts a smooth background gradient - the skyglow from a town "
            "on the horizon. Costs one extra pass the first time it is used on an image.")
        self.s_gradient.valueChanged.connect(self._schedule_preview)
        self.sec_lp.add(self.s_gradient)
        p.add(self.sec_lp)

        self.reset_btn = ui.button("Reset all adjustments", "reset")
        self.reset_btn.clicked.connect(self._reset)
        p.add(self.reset_btn)

        p.add_stretch(1)

        # -- export (pinned: reachable whatever the adjustment list is doing) --
        exp_grid = ui.FormGrid()
        self.format_combo = QtWidgets.QComboBox()
        for key, label in qe.supported_output_formats():
            self.format_combo.addItem(label, key)
        exp_grid.add_row("Format", self.format_combo)
        p.add_footer_layout(exp_grid)

        self.export_btn = ui.primary_button("Export…", "export")
        self.export_btn.clicked.connect(self.export_image)
        p.add_footer(self.export_btn)

        self.status = ui.StatusStrip()
        p.add_footer(self.status)

        outer.addWidget(self.panel)

        # -- preview ----------------------------------------------------------
        self.view = ImageView()
        self.view.browse.connect(self.open_image)
        self.view.dropped.connect(self._load)
        outer.addWidget(self.view, 1)

        self._set_enabled(False)
        self.panel.fit_width()

    def _set_enabled(self, on):
        for w in (self.preset_combo, self.film_combo, self.cb_grain, self.s_gradient,
                  self.cb_autowb, self.s_temp, self.s_tint, self.reset_btn,
                  self.export_btn, self.format_combo):
            w.setEnabled(on)

    # ---------------------------------------------------------------- params
    def _params(self) -> qe.EditParams:
        base = qe.PRESETS.get(self.preset_combo.currentText(), qe.EditParams())
        p = qe.EditParams.from_dict(base.to_dict())   # copy; don't mutate the preset
        p.gradient = self.s_gradient.value() / 100.0
        p.auto_wb = self.cb_autowb.isChecked()
        p.temp = self.s_temp.value() / 100.0
        p.tint = self.s_tint.value() / 100.0
        film = self.film_combo.currentText()
        p.film = "" if film == "None" else film
        p.grain = self.cb_grain.isChecked()
        return p

    def _reset(self):
        # Block signals while clearing so the reset queues ONE preview at the
        # end rather than one per control - eight renders of intermediate
        # states nobody asked for, the last of which is the only correct one.
        for s in (self.s_gradient, self.s_temp, self.s_tint):
            s.slider.blockSignals(True)
            s.setValue(0)
            s.slider.blockSignals(False)
        for w, setter, val in ((self.cb_autowb, "setChecked", False),
                               (self.cb_grain, "setChecked", False),
                               (self.preset_combo, "setCurrentIndex", 0),
                               (self.film_combo, "setCurrentIndex", 0)):
            w.blockSignals(True)
            getattr(w, setter)(val)
            w.blockSignals(False)
        self._schedule_preview()

    # ---------------------------------------------------------------- preview
    def _schedule_preview(self, *_):
        if self.base is not None:
            self._preview.poke()

    def _run_preview(self):
        if self.base is None:
            return
        p = self._params()
        if p.gradient > 0 and self.base_bg is None:
            # computed once per image, on the small base, then reused across edits
            self.status.show_message("Estimating background gradient…", "busy")
            QtWidgets.QApplication.processEvents()
            self.base_bg = qe.estimate_background(self.base)
            self.status.clear()
        self.preview_worker = PreviewWorker(self.base, p, self.base_bg)
        self.preview_worker.ready.connect(self._show_preview)
        self.preview_worker.start()

    def _show_preview(self, arr):
        self._last_arr = arr
        self.view.set_image(_to_pixmap(arr))

    # ---------------------------------------------------------------- IO
    def open_image(self):
        exts = " ".join(f"*.{e}" for e in qe.supported_input_extensions())
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open image", settings.last_dir(TOOL), f"Images ({exts})")
        if path:
            self._load(path)

    def _load(self, path):
        self.status.show_message(f"Opening {os.path.basename(path)}…", "busy")
        QtWidgets.QApplication.processEvents()
        try:
            self.full = qe.load_image(path)
        except Exception as exc:  # noqa: BLE001
            self.status.show_message(f"Could not open: {exc}", "error")
            QtWidgets.QMessageBox.warning(self, "Quick Edit", f"Could not open:\n{exc}")
            # Back to the empty state. Leaving the previous photo on screen
            # after a failed open is worse than showing nothing: the window
            # then claims to be editing a file it could not read, and
            # hold-to-compare would still be serving the old image's original.
            self.view.clear()
            self.full = None
            self.base = None
            self.base_bg = None
            self._set_enabled(False)
            return
        self.path = path
        settings.remember_dir(TOOL, path)
        h, w = self.full.shape[:2]
        self.file_label.setText(f"{os.path.basename(path)}   ·   {w} × {h}")
        self.drop.setText("Drop another photo", "or click to browse")
        self.base = _downscale(self.full, PREVIEW_MAX_EDGE)
        self.base_bg = None       # invalidate cache for the new image
        # The untouched base is what the hold-to-compare shows. Captured here,
        # once, so the comparison costs a blit rather than a pipeline run.
        self.view.set_original(_to_pixmap(self.base))
        self._set_enabled(True)
        self.status.clear()
        self._reset()

    def export_image(self):
        if self.full is None:
            return
        fmt_key = self.format_combo.currentData()
        ext = qe.extension_for_format(fmt_key)
        stem = os.path.splitext(os.path.basename(self.path))[0]
        suggested = os.path.join(os.path.dirname(self.path), f"{stem}_edited.{ext}")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export edited image", suggested, f"{ext.upper()} (*.{ext})")
        if not path:
            return
        self.export_btn.setEnabled(False)
        self.status.show_message("Exporting at full resolution…", "busy")
        self.export_worker = ExportWorker(self.full, self._params(), path, fmt_key, 95)
        self.export_worker.done.connect(self._on_exported)
        self.export_worker.failed.connect(self._on_export_failed)
        self.export_worker.start()

    def _on_exported(self, path):
        self.export_btn.setEnabled(True)
        self.status.show_message(f"Saved {os.path.basename(path)}", "ok")

    def _on_export_failed(self, msg):
        self.export_btn.setEnabled(True)
        self.status.show_message(f"Export failed: {msg}", "error")
        QtWidgets.QMessageBox.warning(self, "Quick Edit", f"Export failed:\n{msg}")

    # ---------------------------------------------------------------- input
    def keyPressEvent(self, e):
        # Space held = show the original. autoRepeat is filtered or the held key
        # re-triggers at the keyboard repeat rate and the badge flickers.
        if e.key() == QtCore.Qt.Key_Space and not e.isAutoRepeat():
            self.view.set_showing_original(True)
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == QtCore.Qt.Key_Space and not e.isAutoRepeat():
            self.view.set_showing_original(False)
            return
        super().keyReleaseEvent(e)

    def changeEvent(self, e):
        # Drawn pixmaps do not follow a live theme switch on their own.
        if e.type() in (QtCore.QEvent.PaletteChange, QtCore.QEvent.StyleChange):
            ui.retint_tree(self)
        super().changeEvent(e)

    # ---------------------------------------------------------------- drag & drop
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        for url in ev.mimeData().urls():
            p = url.toLocalFile()
            if p and os.path.isfile(p):
                self._load(p)
                break

    # ---------------------------------------------------------------- geometry
    def _restore_geometry(self):
        geo = settings.window_geometry(TOOL)
        if geo:
            try:
                self.restoreGeometry(QtCore.QByteArray.fromHex(geo.encode()))
            except Exception:  # noqa: BLE001
                pass

    def closeEvent(self, ev):
        try:
            settings.remember_window(TOOL, bytes(self.saveGeometry().toHex()).decode())
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(ev)


def main():
    import sys
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
