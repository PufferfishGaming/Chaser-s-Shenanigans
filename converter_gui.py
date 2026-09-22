"""
Format Converter - desktop frontend (PySide6).

Converts a single image or a whole folder between formats (JPEG/PNG/WEBP/TIFF/
BMP and, when pillow-heif is available, HEIF/HEIC/HIF). Runs the batch on a
background QThread so the UI stays responsive; conversion is fast and IO-bound,
so a simple sequential thread is plenty (no multiprocessing needed here).

Frontend notes
--------------
* **Two columns, not one 1280px-wide stack.** Every control was full-window
  width, so a checkbox label ended 1100px from its tick and the rename field
  stretched to the size of a paragraph. The settings sit in a fixed-width
  column; the job log gets the rest.

* **The batch is counted before it runs.** "Convert" used to be the first point
  at which the number of matching files was known - including the case where a
  folder matched none, which was reported only in the log after the click. The
  file count and destination are shown up front and the button says how many it
  will do.

* **Options that do not apply are disabled AND say why.** Quality on a PNG and
  the GPS strip with EXIF off were both silently inert. They are disabled with
  a tooltip giving the reason.
"""
import os
import logging

from PySide6 import QtCore, QtGui, QtWidgets

import converter_core as cc
import theme
import ui
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
        self.resize(1080, 700)
        _ic = theme.icon_path()
        if _ic:
            self.setWindowIcon(QtGui.QIcon(_ic))
        self.settings = QtCore.QSettings("Chaser", "PhotoTools-Converter")

        self.input_path = None
        self.input_is_dir = False
        self.output_root = None
        self.worker = None
        self._matched = []            # the files a run would actually touch

        self._build_ui()
        ensure_applied()
        self._load_settings()
        self._rescan()

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
        title = QtWidgets.QLabel("Format Converter")
        title.setObjectName("title")
        head.addWidget(title)
        sub = QtWidgets.QLabel("Convert between formats, preserving EXIF where supported")
        sub.setObjectName("subtitle")
        sub.setWordWrap(True)
        head.addWidget(sub)
        p.add_layout(head)

        if not cc.HEIF_AVAILABLE:
            warn = ui.StatusStrip()
            warn.show_message(
                "HEIF/HEIC/HIF unavailable (pillow-heif failed to load). "
                "Other formats still work.", "warn")
            p.add(warn)

        # -- input -----------------------------------------------------------
        p.add_section("Input")
        self.drop = ui.DropZone("Drop an image or folder here", "or click to browse")
        self.drop.clicked.connect(self.choose_file)
        self.drop.dropped.connect(self._on_drop)
        p.add(self.drop)

        self.input_label = QtWidgets.QLabel("No input selected")
        self.input_label.setObjectName("pathlabel")
        self.input_label.setWordWrap(True)
        p.add(self.input_label)

        b_file = ui.button("Choose file…", "file")
        b_file.clicked.connect(self.choose_file)
        b_dir = ui.button("Choose folder…", "folder")
        b_dir.clicked.connect(self.choose_folder)
        p.add_layout(ui.equal_row(b_file, b_dir))

        self.cb_recursive = QtWidgets.QCheckBox("Recurse into sub-folders")
        self.cb_recursive.toggled.connect(self._rescan)
        p.add(self.cb_recursive)

        # -- output ----------------------------------------------------------
        p.add_section("Output folder")
        self.output_label = QtWidgets.QLabel("Not set")
        self.output_label.setObjectName("pathlabel")
        self.output_label.setWordWrap(True)
        p.add(self.output_label)
        b_out = ui.button("Choose output folder…", "folder")
        b_out.clicked.connect(self.choose_output)
        p.add(b_out)

        # -- format ----------------------------------------------------------
        p.add_section("Format")
        fmt_grid = ui.FormGrid()
        self.format_combo = QtWidgets.QComboBox()
        for ext in cc.supported_output_extensions():
            self.format_combo.addItem(ext.upper(), ext)
        self.format_combo.currentIndexChanged.connect(self._update_quality_enabled)
        self.format_combo.currentIndexChanged.connect(self._refresh_run_button)
        fmt_grid.add_row("Convert to", self.format_combo)
        p.add_layout(fmt_grid)

        self.quality = ui.SliderField("Quality", 1, 100, 95, resettable=False)
        p.add(self.quality)

        # -- metadata ---------------------------------------------------------
        p.add_section("Metadata")
        self.cb_exif = QtWidgets.QCheckBox("Preserve EXIF metadata")
        self.cb_exif.setChecked(True)
        self.cb_exif.toggled.connect(self._update_gps_enabled)
        p.add(self.cb_exif)

        self.cb_gps = QtWidgets.QCheckBox("Remove GPS (location) only")
        self.cb_gps.setToolTip("Keeps camera, lens and exposure EXIF; drops where it was taken.")
        p.add(self.cb_gps)

        # -- transform --------------------------------------------------------
        p.add_section("Transform")
        self.cb_resize = QtWidgets.QCheckBox("Resize longest edge")
        self.cb_resize.setToolTip("Downscales only - a smaller image is never enlarged.")
        self.cb_resize.toggled.connect(lambda on: self.resize_px.setEnabled(on))
        p.add(self.cb_resize)

        rs_grid = ui.FormGrid()
        self.resize_px = QtWidgets.QSpinBox()
        self.resize_px.setRange(16, 30000)
        self.resize_px.setValue(2048)
        self.resize_px.setSuffix(" px")
        self.resize_px.setEnabled(False)
        rs_grid.add_row("Longest edge", self.resize_px)

        self.rename_edit = QtWidgets.QLineEdit()
        self.rename_edit.setPlaceholderText("{name}_web")
        self.rename_edit.setToolTip("Tokens: {name} {n} {n:03d} {date}. Leave empty to "
                                    "keep the original names.")
        rs_grid.add_row("Rename", self.rename_edit)
        p.add_layout(rs_grid)

        hint = QtWidgets.QLabel("Rename tokens: {name} {n} {n:03d} {date}")
        hint.setObjectName("empty_body")
        hint.setWordWrap(True)
        p.add(hint)

        self.cb_no_overwrite = QtWidgets.QCheckBox("Don't overwrite existing files")
        p.add(self.cb_no_overwrite)

        p.add_stretch(1)

        # -- run (pinned) ------------------------------------------------------
        self.status = ui.StatusStrip()
        p.add_footer(self.status)
        self.run_btn = ui.primary_button("Convert", "convert")
        self.run_btn.clicked.connect(self.start)
        self.cancel_btn = ui.button("Cancel", "close")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        p.add_footer_layout(ui.equal_row(self.run_btn, self.cancel_btn))

        outer.addWidget(self.panel)

        # -- job pane ----------------------------------------------------------
        right = QtWidgets.QWidget()
        # NOT #preview_area. That token is the near-black/neutral surface a
        # photograph is judged against; this pane shows a job log, and the
        # heavy grey made the window look like a disabled image viewer.
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(ui.SPACE_LG, ui.SPACE_LG, ui.SPACE_LG, ui.SPACE_LG)
        rl.setSpacing(ui.SPACE_MD)

        self.summary = QtWidgets.QLabel("")
        self.summary.setObjectName("subtitle")
        self.summary.setWordWrap(True)
        rl.addWidget(self.summary)

        self.empty = ui.EmptyState(
            "convert", "Nothing queued",
            "Choose a file or a folder, pick a target format, then Convert.")
        rl.addWidget(self.empty, 1)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("log")
        self.log.setVisible(False)
        rl.addWidget(self.log, 1)

        outer.addWidget(right, 1)

        self._update_quality_enabled()
        self._update_gps_enabled()
        self.panel.fit_width()

    def _update_gps_enabled(self):
        # GPS-only strip only makes sense when EXIF is being preserved.
        on = self.cb_exif.isChecked()
        self.cb_gps.setEnabled(on)
        self.cb_gps.setToolTip(
            "Keeps camera, lens and exposure EXIF; drops where it was taken."
            if on else "No EXIF is being written, so there is no GPS to remove.")

    def _update_quality_enabled(self):
        # Quality only applies to lossy targets.
        ext = self.format_combo.currentData()
        fmt = cc.format_for_extension(ext)
        lossy = fmt in ("JPEG", "WEBP", "HEIF")
        self.quality.setEnabled(lossy)
        self.quality.setToolTip(
            "" if lossy else f"{ext.upper()} is lossless - quality does not apply.")

    # ---- selection ----------------------------------------------------------
    def choose_file(self):
        exts = " ".join(f"*.{e}" for e in cc.supported_input_extensions())
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose image", "", f"Images ({exts})")
        if path:
            self._set_input(path, False)

    def choose_folder(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose folder")
        if path:
            self._set_input(path, True)

    def _on_drop(self, paths):
        p = paths[0]
        if os.path.isdir(p):
            self._set_input(p, True)
        elif os.path.isfile(p):
            self._set_input(p, False)

    def _set_input(self, path, is_dir):
        self.input_path = path
        self.input_is_dir = is_dir
        self.input_label.setText(path)
        self.drop.setText("Drop another image or folder", "or click to browse")
        self._default_output_for(path if is_dir else os.path.dirname(path))
        self._rescan()

    def choose_output(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose output folder")
        if path:
            self.output_root = path
            self.output_label.setText(path)
            self._refresh_run_button()

    def _default_output_for(self, base):
        if not self.output_root:
            self.output_root = os.path.join(base, "converted")
            self.output_label.setText(self.output_root)

    # ---- the queue ----------------------------------------------------------
    def _rescan(self):
        """Work out now what a run would touch, instead of at the click.

        A folder that matched nothing used to be reported only after Convert
        had been pressed, in the log, as one line among many. Scanning on every
        input change means the count on the button is the answer.
        """
        if not self.input_path:
            self._matched = []
        elif self.input_is_dir:
            try:
                self._matched = get_directory_files(
                    self.input_path, self.cb_recursive.isChecked(),
                    _include_globs(), EXCLUDE)
            except Exception as exc:  # noqa: BLE001
                logger.warning("scan failed: %r", exc)
                self._matched = []
        else:
            self._matched = [self.input_path]
        self._refresh_run_button()

    def _refresh_run_button(self):
        n = len(self._matched)
        ext = self.format_combo.currentData()
        ready = bool(n and self.output_root)
        self.run_btn.setEnabled(ready and not (self.worker and self.worker.isRunning()))
        if not self.input_path:
            self.run_btn.setText("Convert")
            self.summary.setText("")
            self.status.clear()
            return
        if not n:
            self.run_btn.setText("Convert")
            self.summary.setText("")
            self.status.show_message("No images matched this input.", "warn")
            return
        self.run_btn.setText(f"Convert {n} file{'s' if n != 1 else ''}")
        self.summary.setText(
            f"{n} file{'s' if n != 1 else ''} → .{ext}   into   {self.output_root}")
        self.status.clear()

    # ---- run ----------------------------------------------------------------
    def start(self):
        if not self.input_path:
            self.status.show_message("No input selected.", "warn")
            return
        if not self.output_root:
            self.status.show_message("No output folder selected.", "warn")
            return
        self._rescan()
        paths = self._matched
        if not paths:
            self.status.show_message("No images matched.", "warn")
            return

        input_root = (os.path.abspath(self.input_path) if self.input_is_dir
                      else os.path.dirname(os.path.abspath(self.input_path)))
        os.makedirs(self.output_root, exist_ok=True)
        out_ext = self.format_combo.currentData()

        self.log.clear()
        self.log.setVisible(True)
        self.empty.setVisible(False)
        self._log(f"Converting {len(paths)} file(s) to .{out_ext} → {self.output_root}")
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.status.show_progress(0, len(paths), "Starting…")

        self.worker = ConvertWorker(
            paths, input_root, self.output_root, out_ext,
            int(self.quality.value()), self.cb_exif.isChecked(),
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
            self.status.show_message("Cancelling…", "busy")
            self._log("Cancelling…")

    def _on_file_done(self, done, total, src, msg):
        self.status.show_progress(done, total, f"{os.path.basename(src)}  ({done}/{total})")
        self._log(f"[{done}/{total}] {os.path.basename(src)} — {msg}")

    def _on_finished(self, success, fail):
        self._log(f"Done. {success} converted, {fail} failed.")
        self.status.hide_progress()
        self.status.show_message(
            f"{success} converted, {fail} failed" if fail else f"{success} converted",
            "warn" if fail else "ok")
        self.cancel_btn.setEnabled(False)
        self._refresh_run_button()

    def _log(self, msg):
        self.log.appendPlainText(msg)

    def changeEvent(self, e):
        if e.type() in (QtCore.QEvent.PaletteChange, QtCore.QEvent.StyleChange):
            ui.retint_tree(self)
        super().changeEvent(e)

    # ---- settings -----------------------------------------------------------
    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        s = self.settings
        s.setValue("output_root", self.output_root or "")
        s.setValue("format_index", self.format_combo.currentIndex())
        s.setValue("quality", int(self.quality.value()))
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
