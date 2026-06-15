"""
Astro Stacker - desktop frontend (PySide6).

Pick a sequence of night-sky frames, choose what to lock onto (the stars, for a
sharp sky over a smeared foreground; or the foreground, for sharp ground under
trailing stars), preview the rendered stack, and export to any format including
high-bit-depth TIFF and FITS. RAW frames are read via rawpy when available.

Heavy work (load/align/combine) runs on a background QThread so the UI stays
responsive; the preview stacks at reduced resolution for speed, the export
stacks at full resolution.
"""
import os
import logging

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

import stacker_core as sc
from theme import APP_QSS

logger = logging.getLogger(__name__)

PREVIEW_MAX_EDGE = 900  # px, longest edge for the fast preview stack


def _np_to_pixmap(arr: np.ndarray) -> QtGui.QPixmap:
    a = np.ascontiguousarray((np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8))
    h, w, _ = a.shape
    qimg = QtGui.QImage(a.data, w, h, 3 * w, QtGui.QImage.Format_RGB888).copy()
    return QtGui.QPixmap.fromImage(qimg)


class StackWorker(QtCore.QThread):
    progress = QtCore.Signal(int, int, str)
    preview_ready = QtCore.Signal(object)        # np.ndarray
    exported = QtCore.Signal(str, int, int)      # path, used, failed
    failed = QtCore.Signal(str)

    def __init__(self, paths, mode, method, max_edge,
                 export_path=None, fmt_key=None, quality=95,
                 reject_anomalies=False, smooth_sky=False):
        super().__init__()
        self.paths = paths
        self.mode = mode
        self.method = method
        self.max_edge = max_edge
        self.export_path = export_path
        self.fmt_key = fmt_key
        self.quality = quality
        self.reject_anomalies = reject_anomalies
        self.smooth_sky = smooth_sky
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            res = sc.stack(
                self.paths, mode=self.mode, method=self.method, max_edge=self.max_edge,
                reject_anomalies=self.reject_anomalies, smooth_sky=self.smooth_sky,
                progress_cb=lambda d, t, m: self.progress.emit(d, t, m),
                cancel_cb=lambda: self._cancel)
            if self.export_path:
                sc.export_image(res["image"], self.export_path, self.fmt_key, self.quality)
                self.exported.emit(self.export_path, res["used"], res["failed"])
            else:
                self.preview_ready.emit(res["image"])
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Astro Stacker")
        self.resize(1040, 660)
        self.settings = QtCore.QSettings("Chaser", "PhotoTools-Stacker")

        self.paths: list[str] = []
        self.worker = None
        self._last_result = None  # np image of the most recent (preview) stack

        self._build_ui()
        self.setStyleSheet(APP_QSS)
        self._load_settings()

    # ---- UI -----------------------------------------------------------------
    def _section(self, text):
        lbl = QtWidgets.QLabel(text.upper())
        lbl.setObjectName("section")
        return lbl

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- left control panel ----
        panel = QtWidgets.QWidget()
        panel.setObjectName("panel")
        panel.setFixedWidth(380)
        root = QtWidgets.QVBoxLayout(panel)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(10)

        title = QtWidgets.QLabel("Astro Stacker")
        title.setObjectName("title")
        root.addWidget(title)
        sub = QtWidgets.QLabel("Stack a sequence into sharp stars or star trails")
        sub.setObjectName("subtitle")
        root.addWidget(sub)

        notes = []
        if not sc.RAW_AVAILABLE:
            notes.append("RAW input unavailable (rawpy not installed).")
        if not sc.TIFFFILE_AVAILABLE:
            notes.append("16/32-bit TIFF export needs tifffile.")
        if not sc.FITS_AVAILABLE:
            notes.append("FITS export needs astropy.")
        if not (sc.SKIMAGE_AVAILABLE or sc.ASTROALIGN_AVAILABLE):
            notes.append("Star alignment is translation-only — install scikit-image "
                         "to handle the sky's rotation.")
        if notes:
            warn = QtWidgets.QLabel(" ".join(notes))
            warn.setObjectName("error")
            warn.setWordWrap(True)
            root.addWidget(warn)

        # Input frames
        root.addWidget(self._section("Frames"))
        self.input_label = QtWidgets.QLabel("No frames selected")
        self.input_label.setObjectName("pathlabel")
        self.input_label.setWordWrap(True)
        root.addWidget(self.input_label)
        in_row = QtWidgets.QHBoxLayout()
        b_files = QtWidgets.QPushButton("Choose files…")
        b_files.clicked.connect(self.choose_files)
        b_dir = QtWidgets.QPushButton("Choose folder…")
        b_dir.clicked.connect(self.choose_folder)
        in_row.addWidget(b_files)
        in_row.addWidget(b_dir)
        root.addLayout(in_row)

        # Mode
        root.addWidget(self._section("Lock onto"))
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItem("Stars — sharp sky, smeared foreground", "sharp_stars")
        self.mode_combo.addItem("Foreground — sharp ground, star trails", "star_trails")
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        root.addWidget(self.mode_combo)

        # Combine method
        root.addWidget(self._section("Combine"))
        self.method_combo = QtWidgets.QComboBox()
        for key, label in sc.COMBINE_METHODS:
            self.method_combo.addItem(label, key)
        root.addWidget(self.method_combo)

        self.cb_reject = QtWidgets.QCheckBox("Reduce transient anomalies")
        self.cb_reject.setToolTip(
            "Try to suppress passing intruders — planes, satellites, brief flashes, "
            "stray light, drifting cloud.\n\n"
            "Aligned (stars) mode: per-pixel outlier rejection.\n"
            "Trails mode: drops whole frames whose brightness spikes against the "
            "sequence (may slightly shorten trails). Works on the source frames — "
            "it can't clean an already-stacked image.")
        root.addWidget(self.cb_reject)

        self.cb_smooth = QtWidgets.QCheckBox("Smooth sky (trails — reduce background noise)")
        self.cb_smooth.setToolTip(
            "Star-trail mode keeps the brightest sample at every pixel, which "
            "amplifies background noise. This rebuilds the sky from the average of "
            "all frames (low noise) and keeps the max only for the bright trails.\n\n"
            "Tradeoff: it cleans the sky but dims or drops the very faintest trails, "
            "which sit at the noise level. Best results come from stacking RAW/DNG "
            "frames and exporting 16-bit TIFF rather than 8-bit JPEG.")
        root.addWidget(self.cb_smooth)

        # Output format
        root.addWidget(self._section("Export format"))
        self.format_combo = QtWidgets.QComboBox()
        for key, label in sc.supported_output_formats():
            self.format_combo.addItem(label, key)
        self.format_combo.currentIndexChanged.connect(self._update_quality_enabled)
        root.addWidget(self.format_combo)

        q_row = QtWidgets.QHBoxLayout()
        self.quality_label = QtWidgets.QLabel("Quality 95")
        self.quality = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.quality.setRange(1, 100)
        self.quality.setValue(95)
        self.quality.valueChanged.connect(
            lambda v: self.quality_label.setText(f"Quality {v}"))
        q_row.addWidget(self.quality_label)
        q_row.addWidget(self.quality, 1)
        root.addLayout(q_row)

        root.addStretch(1)

        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setFormat("%v / %m frames")
        root.addWidget(self.bar)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("log")
        self.log.setFixedHeight(96)
        root.addWidget(self.log)

        act = QtWidgets.QHBoxLayout()
        self.preview_btn = QtWidgets.QPushButton("Preview")
        self.preview_btn.clicked.connect(self.start_preview)
        self.export_btn = QtWidgets.QPushButton("Export…")
        self.export_btn.setObjectName("primary")
        self.export_btn.clicked.connect(self.start_export)
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        act.addWidget(self.preview_btn, 1)
        act.addWidget(self.export_btn, 2)
        act.addWidget(self.cancel_btn, 1)
        root.addLayout(act)

        outer.addWidget(panel)

        # ---- right preview area ----
        right = QtWidgets.QWidget()
        right.setObjectName("preview_area")
        rlay = QtWidgets.QVBoxLayout(right)
        rlay.setContentsMargins(16, 16, 16, 16)
        self.preview_status = QtWidgets.QLabel("Select frames, then Preview")
        self.preview_status.setObjectName("preview_status")
        self.preview_status.setAlignment(QtCore.Qt.AlignCenter)
        self.preview_label = QtWidgets.QLabel()
        self.preview_label.setAlignment(QtCore.Qt.AlignCenter)
        self.preview_label.setMinimumSize(400, 400)
        rlay.addWidget(self.preview_status)
        rlay.addWidget(self.preview_label, 1)
        outer.addWidget(right, 1)

        self._on_mode_changed()
        self._update_quality_enabled()

    def _on_mode_changed(self):
        # Star trails forces lighten (max); the other methods are for aligned skies.
        trails = self.mode_combo.currentData() == "star_trails"
        self.method_combo.setEnabled(not trails)
        if trails:
            for i in range(self.method_combo.count()):
                if self.method_combo.itemData(i) == "max":
                    self.method_combo.setCurrentIndex(i)
                    break

    def _update_quality_enabled(self):
        lossy = self.format_combo.currentData() in ("jpeg", "webp")
        self.quality.setEnabled(lossy)
        self.quality_label.setEnabled(lossy)

    # ---- selection ----------------------------------------------------------
    def choose_files(self):
        exts = " ".join(f"*.{e}" for e in sc.supported_input_extensions())
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Choose frames", "", f"Images ({exts})")
        if paths:
            self.paths = sorted(paths)
            self._refresh_input_label()

    def choose_folder(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose frame folder")
        if not d:
            return
        exts = set(sc.supported_input_extensions())
        found = [os.path.join(d, n) for n in sorted(os.listdir(d))
                 if n.rsplit(".", 1)[-1].lower() in exts]
        self.paths = found
        self._refresh_input_label()

    def _refresh_input_label(self):
        if not self.paths:
            self.input_label.setText("No frames selected")
        else:
            self.input_label.setText(f"{len(self.paths)} frame(s) selected")

    # ---- run ----------------------------------------------------------------
    def _busy(self, on: bool):
        self.preview_btn.setEnabled(not on)
        self.export_btn.setEnabled(not on)
        self.cancel_btn.setEnabled(on)

    def start_preview(self):
        if not self._guard():
            return
        self._busy(True)
        self.log.clear()
        self.preview_status.setText("Rendering preview…")
        self.worker = StackWorker(
            self.paths, self.mode_combo.currentData(),
            self.method_combo.currentData(), PREVIEW_MAX_EDGE,
            reject_anomalies=self.cb_reject.isChecked(),
            smooth_sky=self.cb_smooth.isChecked())
        self.worker.progress.connect(self._on_progress)
        self.worker.preview_ready.connect(self._on_preview_ready)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(lambda: self._busy(False))
        self.worker.start()

    def start_export(self):
        if not self._guard():
            return
        fmt_key = self.format_combo.currentData()
        ext = sc.extension_for_format(fmt_key)
        # Default to the first frame's name + _stacked, saved next to the source
        # frames (a stack has many inputs, so the first frame names the result).
        if self.paths:
            stem = os.path.splitext(os.path.basename(self.paths[0]))[0]
            suggested = os.path.join(os.path.dirname(self.paths[0]), f"{stem}_stacked.{ext}")
        else:
            suggested = f"stacked.{ext}"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export stacked image", suggested, f"{ext.upper()} (*.{ext})")
        if not path:
            return
        self._busy(True)
        self.log.clear()
        self.preview_status.setText("Stacking at full resolution…")
        self.worker = StackWorker(
            self.paths, self.mode_combo.currentData(),
            self.method_combo.currentData(), None,
            export_path=path, fmt_key=fmt_key, quality=self.quality.value(),
            reject_anomalies=self.cb_reject.isChecked(),
            smooth_sky=self.cb_smooth.isChecked())
        self.worker.progress.connect(self._on_progress)
        self.worker.exported.connect(self._on_exported)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(lambda: self._busy(False))
        self.worker.start()

    def _guard(self) -> bool:
        if len(self.paths) < 2:
            QtWidgets.QMessageBox.information(
                self, "Astro Stacker",
                "Select at least two frames — stacking needs a sequence.")
            return False
        return True

    def cancel(self):
        if self.worker:
            self.worker.cancel()
        self.cancel_btn.setEnabled(False)

    # ---- worker signals -----------------------------------------------------
    def _on_progress(self, done, total, msg):
        self.bar.setRange(0, total)
        self.bar.setValue(done)
        self.log.appendPlainText(msg)

    def _on_preview_ready(self, arr):
        self._last_result = arr
        pm = _np_to_pixmap(arr).scaled(
            self.preview_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        self.preview_label.setPixmap(pm)
        self.preview_status.setText("Preview (reduced resolution)")

    def _on_exported(self, path, used, failed):
        self.preview_status.setText(f"Exported {os.path.basename(path)}")
        self.log.appendPlainText(
            f"Saved {path}  (stacked {used} frame(s), {failed} skipped)")

    def _on_failed(self, msg):
        self.preview_status.setText("Failed")
        self.log.appendPlainText(f"ERROR: {msg}")
        QtWidgets.QMessageBox.warning(self, "Astro Stacker", msg)

    # ---- settings -----------------------------------------------------------
    def _load_settings(self):
        mode = self.settings.value("mode")
        if mode is not None:
            i = self.mode_combo.findData(mode)
            if i >= 0:
                self.mode_combo.setCurrentIndex(i)
        self._on_mode_changed()

    def closeEvent(self, e):
        self.settings.setValue("mode", self.mode_combo.currentData())
        super().closeEvent(e)


def main():
    import sys
    from theme import set_app_user_model_id
    set_app_user_model_id()
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
