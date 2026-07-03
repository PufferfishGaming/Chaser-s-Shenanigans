"""
Format Converter - desktop frontend (PySide6).

Converts a single image or a whole folder between formats (JPEG/PNG/WEBP/TIFF/
BMP and, when pillow-heif is available, HEIF/HEIC/HIF). Runs the batch on a
background QThread so the UI stays responsive; conversion is fast and IO-bound,
so a simple sequential thread is plenty (no multiprocessing needed here).
"""
import os
import logging

from PySide6 import QtCore, QtWidgets

import converter_core as cc
from filemanager import get_directory_files
from theme import ensure_applied

logger = logging.getLogger(__name__)


def _include_globs() -> list[str]:
    globs = []
    for ext in cc.supported_input_extensions():
        globs.append(f"*.{ext}")
        globs.append(f"*.{ext.upper()}")
    return globs


EXCLUDE: list[str] = []


class ConvertWorker(QtCore.QThread):
    file_done = QtCore.Signal(int, int, str, str)   # done, total, src, msg
    finished_all = QtCore.Signal(int, int)          # success, fail
    failed = QtCore.Signal(str)

    def __init__(self, paths, input_root, output_root, out_ext, quality,
                 preserve_exif, overwrite, max_edge=None, strip_gps=False,
                 rename_pattern=""):
        super().__init__()
        self.paths = paths
        self.input_root = input_root
        self.output_root = output_root
        self.out_ext = out_ext
        self.quality = quality
        self.preserve_exif = preserve_exif
        self.overwrite = overwrite
        self.max_edge = max_edge
        self.strip_gps = strip_gps
        self.rename_pattern = rename_pattern
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total = len(self.paths)
        success = fail = 0
        for i, src in enumerate(self.paths):
            if self._cancelled:
                break
            try:
                dst = cc.build_output_path(src, self.input_root, self.output_root, self.out_ext)
                if self.rename_pattern:
                    stem = cc.apply_name_pattern(self.rename_pattern, src, i + 1)
                    dst = os.path.join(os.path.dirname(dst),
                                       stem + os.path.splitext(dst)[1])
                out = cc.convert_image(src, dst, quality=self.quality,
                                       preserve_exif=self.preserve_exif,
                                       overwrite=self.overwrite,
                                       max_edge=self.max_edge,
                                       strip_gps=self.strip_gps)
                success += 1
                self.file_done.emit(i + 1, total, src, f"Saved: {os.path.basename(out)}")
            except Exception as e:  # noqa: BLE001 - one bad file must not kill the batch
                fail += 1
                self.file_done.emit(i + 1, total, src, f"ERROR: {e}")
        self.finished_all.emit(success, fail)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Format Converter")
        self.resize(900, 620)
        self.settings = QtCore.QSettings("Chaser", "PhotoTools-Converter")

        self.input_path = None
        self.input_is_dir = False
        self.output_root = None
        self.worker = None

        self._build_ui()
        ensure_applied()
        self._load_settings()

    def _section(self, text):
        lbl = QtWidgets.QLabel(text.upper())
        lbl.setObjectName("section")
        return lbl

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        title = QtWidgets.QLabel("Format Converter")
        title.setObjectName("title")
        root.addWidget(title)
        sub = QtWidgets.QLabel("Convert images between formats, preserving EXIF where supported")
        sub.setObjectName("subtitle")
        root.addWidget(sub)

        if not cc.HEIF_AVAILABLE:
            warn = QtWidgets.QLabel(
                "HEIF/HEIC/HIF support is unavailable (pillow-heif failed to load). "
                "Other formats still work.")
            warn.setObjectName("error")
            warn.setWordWrap(True)
            root.addWidget(warn)

        # Input
        root.addWidget(self._section("Input"))
        self.input_label = QtWidgets.QLabel("No input selected")
        self.input_label.setObjectName("pathlabel")
        self.input_label.setWordWrap(True)
        root.addWidget(self.input_label)
        in_row = QtWidgets.QHBoxLayout()
        b_file = QtWidgets.QPushButton("Choose file…")
        b_file.clicked.connect(self.choose_file)
        b_dir = QtWidgets.QPushButton("Choose folder…")
        b_dir.clicked.connect(self.choose_folder)
        in_row.addWidget(b_file)
        in_row.addWidget(b_dir)
        root.addLayout(in_row)

        self.cb_recursive = QtWidgets.QCheckBox("Recurse into sub-folders")
        root.addWidget(self.cb_recursive)

        # Output
        root.addWidget(self._section("Output folder"))
        self.output_label = QtWidgets.QLabel("Not set")
        self.output_label.setObjectName("pathlabel")
        self.output_label.setWordWrap(True)
        root.addWidget(self.output_label)
        b_out = QtWidgets.QPushButton("Choose output folder…")
        b_out.clicked.connect(self.choose_output)
        root.addWidget(b_out)

        # Options
        root.addWidget(self._section("Options"))
        fmt_row = QtWidgets.QHBoxLayout()
        fmt_row.addWidget(QtWidgets.QLabel("Convert to"))
        self.format_combo = QtWidgets.QComboBox()
        for ext in cc.supported_output_extensions():
            self.format_combo.addItem(ext.upper(), ext)
        self.format_combo.currentIndexChanged.connect(self._update_quality_enabled)
        fmt_row.addWidget(self.format_combo, 1)
        root.addLayout(fmt_row)

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

        self.cb_exif = QtWidgets.QCheckBox("Preserve EXIF metadata")
        self.cb_exif.setChecked(True)
        self.cb_exif.toggled.connect(self._update_gps_enabled)
        root.addWidget(self.cb_exif)

        self.cb_gps = QtWidgets.QCheckBox("Remove GPS (location) only — keep other EXIF")
        root.addWidget(self.cb_gps)

        # Resize (downscale longest edge; never upscales)
        rs_row = QtWidgets.QHBoxLayout()
        self.cb_resize = QtWidgets.QCheckBox("Resize: longest edge to")
        self.cb_resize.toggled.connect(lambda on: self.resize_px.setEnabled(on))
        self.resize_px = QtWidgets.QSpinBox()
        self.resize_px.setRange(16, 30000)
        self.resize_px.setValue(2048)
        self.resize_px.setSuffix(" px")
        self.resize_px.setEnabled(False)
        rs_row.addWidget(self.cb_resize)
        rs_row.addWidget(self.resize_px)
        rs_row.addStretch(1)
        root.addLayout(rs_row)

        # Optional rename pattern
        rn_row = QtWidgets.QHBoxLayout()
        rn_row.addWidget(QtWidgets.QLabel("Rename"))
        self.rename_edit = QtWidgets.QLineEdit()
        self.rename_edit.setPlaceholderText("optional pattern — tokens: {name} {n} {n:03d} {date}")
        rn_row.addWidget(self.rename_edit, 1)
        root.addLayout(rn_row)

        self.cb_no_overwrite = QtWidgets.QCheckBox("Don't overwrite existing files")
        root.addWidget(self.cb_no_overwrite)

        root.addStretch(1)

        # Progress + actions
        self.file_bar = QtWidgets.QProgressBar()
        self.file_bar.setRange(0, 100)
        self.file_bar.setFormat("%v / %m files")
        root.addWidget(self.file_bar)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("log")
        self.log.setFixedHeight(120)
        root.addWidget(self.log)

        act = QtWidgets.QHBoxLayout()
        self.run_btn = QtWidgets.QPushButton("Convert")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self.start)
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        act.addWidget(self.run_btn, 2)
        act.addWidget(self.cancel_btn, 1)
        root.addLayout(act)

        self._update_quality_enabled()
        self._update_gps_enabled()

    def _update_gps_enabled(self):
        # GPS-only strip only makes sense when EXIF is being preserved.
        self.cb_gps.setEnabled(self.cb_exif.isChecked())

    def _update_quality_enabled(self):
        # Quality only applies to lossy targets.
        ext = self.format_combo.currentData()
        fmt = cc.format_for_extension(ext)
        lossy = fmt in ("JPEG", "WEBP", "HEIF")
        self.quality.setEnabled(lossy)
        self.quality_label.setEnabled(lossy)

    # ---- selection ----------------------------------------------------------
    def choose_file(self):
        exts = " ".join(f"*.{e}" for e in cc.supported_input_extensions())
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose image", "", f"Images ({exts})")
        if path:
            self.input_path = path
            self.input_is_dir = False
            self.input_label.setText(path)
            self._default_output_for(os.path.dirname(path))

    def choose_folder(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose folder")
        if path:
            self.input_path = path
            self.input_is_dir = True
            self.input_label.setText(path)
            self._default_output_for(path)

    def choose_output(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose output folder")
        if path:
            self.output_root = path
            self.output_label.setText(path)

    def _default_output_for(self, base):
        if not self.output_root:
            self.output_root = os.path.join(base, "converted")
            self.output_label.setText(self.output_root)

    # ---- run ----------------------------------------------------------------
    def start(self):
        if not self.input_path:
            self._log("No input selected.")
            return
        if not self.output_root:
            self._log("No output folder selected.")
            return

        if self.input_is_dir:
            input_root = os.path.abspath(self.input_path)
            paths = get_directory_files(self.input_path, self.cb_recursive.isChecked(),
                                        _include_globs(), EXCLUDE)
        else:
            input_root = os.path.dirname(os.path.abspath(self.input_path))
            paths = [self.input_path]

        if not paths:
            self._log("No images matched.")
            return

        os.makedirs(self.output_root, exist_ok=True)
        out_ext = self.format_combo.currentData()
        self.file_bar.setRange(0, len(paths))
        self.file_bar.setValue(0)
        self._log(f"Converting {len(paths)} file(s) to .{out_ext} → {self.output_root}")
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        self.worker = ConvertWorker(
            paths, input_root, self.output_root, out_ext,
            self.quality.value(), self.cb_exif.isChecked(),
            overwrite=not self.cb_no_overwrite.isChecked(),
            max_edge=self.resize_px.value() if self.cb_resize.isChecked() else None,
            strip_gps=self.cb_gps.isChecked() and self.cb_exif.isChecked(),
            rename_pattern=self.rename_edit.text().strip())
        self.worker.file_done.connect(self._on_file_done)
        self.worker.finished_all.connect(self._on_finished)
        self.worker.failed.connect(lambda m: self._log(f"FAILED: {m}"))
        self.worker.start()

    def cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self._log("Cancelling…")

    def _on_file_done(self, done, total, src, msg):
        self.file_bar.setValue(done)
        self._log(f"[{done}/{total}] {os.path.basename(src)} — {msg}")

    def _on_finished(self, success, fail):
        self._log(f"Done. {success} converted, {fail} failed.")
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

    def _log(self, msg):
        self.log.appendPlainText(msg)

    # ---- settings -----------------------------------------------------------
    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        s = self.settings
        s.setValue("output_root", self.output_root or "")
        s.setValue("format_index", self.format_combo.currentIndex())
        s.setValue("quality", self.quality.value())
        s.setValue("preserve_exif", self.cb_exif.isChecked())
        s.setValue("strip_gps", self.cb_gps.isChecked())
        s.setValue("resize_enabled", self.cb_resize.isChecked())
        s.setValue("resize_px", self.resize_px.value())
        s.setValue("rename_pattern", self.rename_edit.text())
        s.setValue("recursive", self.cb_recursive.isChecked())
        s.setValue("no_overwrite", self.cb_no_overwrite.isChecked())
        s.sync()
        super().closeEvent(e)

    def _load_settings(self):
        s = self.settings

        def get_bool(key, default):
            v = s.value(key, default)
            return v.lower() == "true" if isinstance(v, str) else bool(v)

        fi = s.value("format_index", None)
        if fi is not None:
            try:
                self.format_combo.setCurrentIndex(int(fi))
            except (ValueError, TypeError):
                pass
        q = s.value("quality", None)
        if q is not None:
            try:
                self.quality.setValue(int(q))
            except (ValueError, TypeError):
                pass
        self.cb_exif.setChecked(get_bool("preserve_exif", True))
        self.cb_gps.setChecked(get_bool("strip_gps", False))
        self.cb_resize.setChecked(get_bool("resize_enabled", False))
        rpx = s.value("resize_px", None)
        if rpx is not None:
            try:
                self.resize_px.setValue(int(rpx))
            except (ValueError, TypeError):
                pass
        self.resize_px.setEnabled(self.cb_resize.isChecked())
        self.rename_edit.setText(s.value("rename_pattern", "") or "")
        self.cb_recursive.setChecked(get_bool("recursive", False))
        self.cb_no_overwrite.setChecked(get_bool("no_overwrite", False))
        out = s.value("output_root", "")
        if out and os.path.isdir(out):
            self.output_root = out
            self.output_label.setText(out)
        self._update_quality_enabled()
        self._update_gps_enabled()


def main():
    import sys
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
