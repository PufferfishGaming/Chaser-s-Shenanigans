"""Quick Edit — interactive white-balance + presets with a live preview.

Decodes once, keeps a full-resolution copy and a downscaled preview base, and
runs the (cheap) white-balance + look pipeline on the base while you drag
sliders, in a worker thread, debounced. Full resolution is only touched on
export. The core (quickedit_core) still supports gradient removal and tone
controls — this panel just exposes white balance and presets.
"""
from __future__ import annotations

import logging
import os

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

import quickedit_core as qe
import settings
from theme import APP_QSS

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


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Quick Edit")
        self.setStyleSheet(APP_QSS)
        self.setAcceptDrops(True)
        self.resize(1180, 760)

        self.full = None
        self.base = None
        self.base_bg = None       # cached background model for the preview base
        self.path = None
        self.preview_worker = None
        self.export_worker = None
        self._last_arr = None

        self._build_ui()
        self._restore_geometry()

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._run_preview)

    # ---------------------------------------------------------------- UI
    def _section(self, text):
        lbl = QtWidgets.QLabel(text.upper())
        lbl.setObjectName("section")
        return lbl

    def _slider(self, lo, hi, val):
        s = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        s.valueChanged.connect(self._schedule_preview)
        return s

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        panel = QtWidgets.QWidget()
        panel.setObjectName("panel")
        panel.setFixedWidth(330)
        root = QtWidgets.QVBoxLayout(panel)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(8)

        title = QtWidgets.QLabel("Quick Edit")
        title.setObjectName("title")
        root.addWidget(title)
        sub = QtWidgets.QLabel("White balance and one-click looks.")
        sub.setWordWrap(True)
        root.addWidget(sub)

        self.open_btn = QtWidgets.QPushButton("Open image…")
        self.open_btn.clicked.connect(self.open_image)
        root.addWidget(self.open_btn)
        self.file_label = QtWidgets.QLabel("Drop an image here or click Open")
        self.file_label.setWordWrap(True)
        root.addWidget(self.file_label)

        root.addWidget(self._section("Preset"))
        self.preset_combo = QtWidgets.QComboBox()
        self.preset_combo.addItems(qe.preset_names())
        self.preset_combo.currentTextChanged.connect(self._schedule_preview)
        root.addWidget(self.preset_combo)

        root.addWidget(self._section("Light pollution"))
        root.addWidget(QtWidgets.QLabel("Gradient removal"))
        self.s_gradient = self._slider(0, 100, 0)
        root.addWidget(self.s_gradient)

        root.addWidget(self._section("White balance"))
        self.cb_autowb = QtWidgets.QCheckBox("Auto (gray-world — can cool night skies)")
        self.cb_autowb.toggled.connect(self._schedule_preview)
        root.addWidget(self.cb_autowb)
        root.addWidget(QtWidgets.QLabel("Temperature  (cool \u2190\u2192 warm)"))
        self.s_temp = self._slider(-100, 100, 0)
        root.addWidget(self.s_temp)
        root.addWidget(QtWidgets.QLabel("Tint  (green \u2190\u2192 magenta)"))
        self.s_tint = self._slider(-100, 100, 0)
        root.addWidget(self.s_tint)

        self.reset_btn = QtWidgets.QPushButton("Reset")
        self.reset_btn.clicked.connect(self._reset)
        root.addWidget(self.reset_btn)

        root.addWidget(self._section("Export"))
        self.format_combo = QtWidgets.QComboBox()
        for key, label in qe.supported_output_formats():
            self.format_combo.addItem(label, key)
        root.addWidget(self.format_combo)
        self.export_btn = QtWidgets.QPushButton("Export…")
        self.export_btn.setObjectName("primary")
        self.export_btn.clicked.connect(self.export_image)
        root.addWidget(self.export_btn)
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        root.addStretch(1)          # absorb extra height BELOW the controls

        outer.addWidget(panel)

        right = QtWidgets.QWidget()
        right.setObjectName("preview_area")
        rlay = QtWidgets.QVBoxLayout(right)
        rlay.setContentsMargins(16, 16, 16, 16)
        self.preview = QtWidgets.QLabel("No image loaded")
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setMinimumWidth(700)
        self.preview.setObjectName("preview")
        rlay.addWidget(self.preview, 1)
        outer.addWidget(right, 1)

        self._set_enabled(False)

    def _set_enabled(self, on):
        for w in (self.preset_combo, self.s_gradient, self.cb_autowb, self.s_temp,
                  self.s_tint, self.reset_btn, self.export_btn):
            w.setEnabled(on)

    # ---------------------------------------------------------------- params
    def _params(self) -> qe.EditParams:
        base = qe.PRESETS.get(self.preset_combo.currentText(), qe.EditParams())
        p = qe.EditParams.from_dict(base.to_dict())   # copy; don't mutate the preset
        p.gradient = self.s_gradient.value() / 100.0
        p.auto_wb = self.cb_autowb.isChecked()
        p.temp = self.s_temp.value() / 100.0
        p.tint = self.s_tint.value() / 100.0
        return p

    def _reset(self):
        for s in (self.s_gradient, self.s_temp, self.s_tint):
            s.blockSignals(True)
            s.setValue(0)
            s.blockSignals(False)
        self.cb_autowb.setChecked(False)
        self.preset_combo.setCurrentIndex(0)
        self._schedule_preview()

    # ---------------------------------------------------------------- preview
    def _schedule_preview(self, *_):
        if self.base is not None:
            self._timer.start()

    def _run_preview(self):
        if self.base is None:
            return
        p = self._params()
        if p.gradient > 0 and self.base_bg is None:
            # computed once per image, on the small base, then reused across edits
            self.base_bg = qe.estimate_background(self.base)
        self.preview_worker = PreviewWorker(self.base, p, self.base_bg)
        self.preview_worker.ready.connect(self._show_preview)
        self.preview_worker.start()

    def _show_preview(self, arr):
        self._last_arr = arr
        pm = _to_pixmap(arr)
        self.preview.setPixmap(pm.scaled(self.preview.size(), QtCore.Qt.KeepAspectRatio,
                                         QtCore.Qt.SmoothTransformation))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._last_arr is not None:
            self._show_preview(self._last_arr)

    # ---------------------------------------------------------------- IO
    def open_image(self):
        exts = " ".join(f"*.{e}" for e in qe.supported_input_extensions())
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open image", settings.last_dir(TOOL), f"Images ({exts})")
        if path:
            self._load(path)

    def _load(self, path):
        try:
            self.full = qe.load_image(path)
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "Quick Edit", f"Could not open:\n{exc}")
            return
        self.path = path
        settings.remember_dir(TOOL, path)
        self.file_label.setText(os.path.basename(path))
        self.base = _downscale(self.full, PREVIEW_MAX_EDGE)
        self.base_bg = None       # invalidate cache for the new image
        self._set_enabled(True)
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
        self.status.setText("Exporting at full resolution…")
        self.export_worker = ExportWorker(self.full, self._params(), path, fmt_key, 95)
        self.export_worker.done.connect(self._on_exported)
        self.export_worker.failed.connect(self._on_export_failed)
        self.export_worker.start()

    def _on_exported(self, path):
        self.export_btn.setEnabled(True)
        self.status.setText(f"Saved {os.path.basename(path)}")

    def _on_export_failed(self, msg):
        self.export_btn.setEnabled(True)
        self.status.setText("")
        QtWidgets.QMessageBox.warning(self, "Quick Edit", f"Export failed:\n{msg}")

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
