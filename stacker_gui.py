"""
Astro Stacker - desktop frontend (PySide6).

Pick a sequence of night-sky frames, choose what to lock onto (the stars, for a
sharp sky over a smeared foreground; or the foreground, for sharp ground under
trailing stars), preview the rendered stack, and export to any format including
high-bit-depth TIFF and FITS. RAW frames are read via rawpy when available.

Heavy work (load/align/combine) runs on a background QThread so the UI stays
responsive; the preview stacks at reduced resolution for speed, the export
stacks at full resolution.

Frontend notes
--------------
* **Frames are a list, not a count.** "12 frame(s) selected" was the entire
  feedback on the most error-prone input in the suite: a folder pick that
  silently swept up a stray JPEG, or an out-of-order sequence, looked identical
  to a correct one. The frame list shows what will actually be stacked and lets
  single frames be removed.

* **Progress and log only exist while something is running.** The old panel
  carried an empty progress trough and an empty 96px log box at rest, which is
  most of what made the window look unfinished. `ui.StatusStrip` appears when
  there is something to say.

* **"Lock onto" explains the consequence.** The mode combo drives a one-line
  description under it, because "Stars" versus "Foreground" is the decision
  that determines what the output looks like and it is not self-evident which
  one gives trails.
"""
import os
import logging

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

import stacker_core as sc
import theme
import ui
from theme import ensure_applied

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


class StackView(QtWidgets.QWidget):
    """Preview surface for the stacked result, with a caption strip above it."""

    dropped = QtCore.Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("preview_area")
        self.setAcceptDrops(True)
        self.setMinimumWidth(420)
        self._pm = None

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(ui.SPACE_MD, ui.SPACE_MD, ui.SPACE_MD, ui.SPACE_MD)
        lay.setSpacing(ui.SPACE_SM)

        self.caption = QtWidgets.QLabel("")
        self.caption.setObjectName("preview_status")
        self.caption.setAlignment(QtCore.Qt.AlignCenter)
        self.caption.setVisible(False)
        lay.addWidget(self.caption)

        self.empty = ui.EmptyState(
            "stars", "No stack yet",
            "Choose a sequence of frames, then Preview to see the stack.")
        lay.addWidget(self.empty, 1)

        self.canvas = _Canvas(self)
        self.canvas.setVisible(False)
        lay.addWidget(self.canvas, 1)

    def set_image(self, pm, caption=""):
        self._pm = pm
        self.canvas.set_pixmap(pm)
        self.canvas.setVisible(True)
        self.empty.setVisible(False)
        self.caption.setText(caption)
        self.caption.setVisible(bool(caption))

    def set_caption(self, text):
        self.caption.setText(text)
        self.caption.setVisible(bool(text))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.dropped.emit(paths)
            e.acceptProposedAction()

    def retint(self):
        self.empty.retint()


class _Canvas(QtWidgets.QWidget):
    """Scales in paintEvent rather than storing a scaled copy per resize."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pm = None

    def set_pixmap(self, pm):
        self._pm = pm
        self.update()

    def paintEvent(self, _e):
        if self._pm is None or self._pm.isNull():
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        scaled = self._pm.size().scaled(self.size(), QtCore.Qt.KeepAspectRatio)
        target = QtCore.QRect(QtCore.QPoint(0, 0), scaled)
        target.moveCenter(self.rect().center())
        p.drawPixmap(target, self._pm)


class MainWindow(QtWidgets.QMainWindow):
    # What each lock-on mode actually produces. Shown under the combo, because
    # this is the choice that decides what the picture looks like and the label
    # "Stars / Foreground" does not say which one gives trails.
    MODE_HELP = {
        "sharp_stars": "Frames are aligned on the stars: pin-sharp sky, "
                       "and the ground smears.",
        "star_trails": "Frames are stacked as shot: sharp ground, and the "
                       "stars draw trails.",
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Astro Stacker")
        self.resize(1180, 760)
        _ic = theme.icon_path()
        if _ic:
            self.setWindowIcon(QtGui.QIcon(_ic))
        self.settings = QtCore.QSettings("Chaser", "PhotoTools-Stacker")

        self.paths: list[str] = []
        self.worker = None
        self._last_result = None  # np image of the most recent (preview) stack

        self._build_ui()
        ensure_applied()
        self._load_settings()

    # ---- UI -----------------------------------------------------------------
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
        title = QtWidgets.QLabel("Astro Stacker")
        title.setObjectName("title")
        head.addWidget(title)
        sub = QtWidgets.QLabel("Stack a sequence into sharp stars or star trails")
        sub.setObjectName("subtitle")
        sub.setWordWrap(True)
        head.addWidget(sub)
        p.add_layout(head)

        # Optional-dependency notices. Each is a separate line with its own
        # icon rather than one run-on paragraph: they are independent facts and
        # concatenating them made a four-clause sentence nobody read.
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
        self._notices = []
        for text in notes:
            strip = ui.StatusStrip()
            strip.show_message(text, "warn")
            self._notices.append(strip)
            p.add(strip)

        # -- frames ----------------------------------------------------------
        p.add_section("Frames")
        # A drop target stands in for the list while it is empty: an empty
        # 190px list box is a large hole that names neither the problem nor the
        # fix, and the sequence usually arrives as a folder drag anyway.
        self.drop = ui.DropZone("Drop frames or a folder here", "or use the buttons below")
        self.drop.clicked.connect(self.choose_files)
        self.drop.dropped.connect(self._add_paths)
        p.add(self.drop)

        self.frames = QtWidgets.QListWidget()
        self.frames.setAlternatingRowColors(True)
        self.frames.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.frames.setMinimumHeight(110)
        self.frames.setMaximumHeight(190)
        self.frames.setToolTip("The exact frames that will be stacked, in order. "
                               "Select rows and press Delete to drop them.")
        self.frames.setVisible(False)
        p.add(self.frames)

        self.input_label = QtWidgets.QLabel("No frames selected")
        self.input_label.setObjectName("pathlabel")
        self.input_label.setWordWrap(True)
        p.add(self.input_label)

        b_files = ui.button("Choose files…", "file")
        b_files.clicked.connect(self.choose_files)
        b_dir = ui.button("Choose folder…", "folder")
        b_dir.clicked.connect(self.choose_folder)
        self.clear_btn = ui.ghost_button("Clear", "close")
        self.clear_btn.clicked.connect(self._clear_frames)
        p.add_layout(ui.equal_row(b_files, b_dir))
        p.add_layout(ui.hbox(self.clear_btn, None))

        # -- stacking --------------------------------------------------------
        p.add_section("Stacking")
        grid = ui.FormGrid()
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItem("Stars — sharp sky, smeared foreground", "sharp_stars")
        self.mode_combo.addItem("Foreground — sharp ground, star trails", "star_trails")
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        grid.add_row("Lock onto", self.mode_combo)

        self.method_combo = QtWidgets.QComboBox()
        for key, label in sc.COMBINE_METHODS:
            self.method_combo.addItem(label, key)
        grid.add_row("Combine", self.method_combo)
        p.add_layout(grid)

        self.mode_help = QtWidgets.QLabel("")
        self.mode_help.setObjectName("empty_body")
        self.mode_help.setWordWrap(True)
        p.add(self.mode_help)

        self.cb_reject = QtWidgets.QCheckBox("Reduce transient anomalies")
        self.cb_reject.setToolTip(
            "Try to suppress passing intruders — planes, satellites, brief flashes, "
            "stray light, drifting cloud.\n\n"
            "Aligned (stars) mode: per-pixel outlier rejection.\n"
            "Trails mode: drops whole frames whose brightness spikes against the "
            "sequence (may slightly shorten trails). Works on the source frames — "
            "it can't clean an already-stacked image.")
        p.add(self.cb_reject)

        self.cb_smooth = QtWidgets.QCheckBox("Smooth sky (trails only)")
        self.cb_smooth.setToolTip(
            "Star-trail mode keeps the brightest sample at every pixel, which "
            "amplifies background noise. This rebuilds the sky from the average of "
            "all frames (low noise) and keeps the max only for the bright trails.\n\n"
            "Tradeoff: it cleans the sky but dims or drops the very faintest trails, "
            "which sit at the noise level. Best results come from stacking RAW/DNG "
            "frames and exporting 16-bit TIFF rather than 8-bit JPEG.")
        p.add(self.cb_smooth)

        # -- export ----------------------------------------------------------
        p.add_section("Export")
        exp = ui.FormGrid()
        self.format_combo = QtWidgets.QComboBox()
        for key, label in sc.supported_output_formats():
            self.format_combo.addItem(label, key)
        self.format_combo.currentIndexChanged.connect(self._update_quality_enabled)
        exp.add_row("Format", self.format_combo)
        p.add_layout(exp)

        self.quality = ui.SliderField("Quality", 1, 100, 95, resettable=False)
        p.add(self.quality)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("log")
        self.log.setFixedHeight(84)
        # Hidden at rest. An empty log box is 84px of the panel spent saying
        # nothing, and it made the window look like it had failed to load.
        self.log.setVisible(False)
        p.add(self.log)

        p.add_stretch(1)

        # -- run (pinned; must stay reachable however far the body scrolls) ---
        self.status = ui.StatusStrip()
        p.add_footer(self.status)

        self.preview_btn = ui.button("Preview", "image")
        self.preview_btn.clicked.connect(self.start_preview)
        self.export_btn = ui.primary_button("Export…", "export")
        self.export_btn.clicked.connect(self.start_export)
        self.cancel_btn = ui.button("Cancel", "close")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        p.add_footer_layout(ui.equal_row(self.preview_btn, self.export_btn))
        p.add_footer(self.cancel_btn)

        outer.addWidget(self.panel)

        self.view = StackView()
        self.view.dropped.connect(self._add_paths)
        outer.addWidget(self.view, 1)

        self._on_mode_changed()
        self._update_quality_enabled()
        self._refresh_input_label()
        self.panel.fit_width()

    def _on_mode_changed(self):
        # Star trails forces lighten (max); the other methods are for aligned skies.
        mode = self.mode_combo.currentData()
        trails = mode == "star_trails"
        self.method_combo.setEnabled(not trails)
        self.method_combo.setToolTip(
            "Fixed to Lighten (max) in trails mode - that is what draws a trail."
            if trails else "")
        if trails:
            for i in range(self.method_combo.count()):
                if self.method_combo.itemData(i) == "max":
                    self.method_combo.setCurrentIndex(i)
                    break
        self.cb_smooth.setEnabled(trails)
        self.mode_help.setText(self.MODE_HELP.get(mode, ""))

    def _update_quality_enabled(self):
        lossy = self.format_combo.currentData() in ("jpeg", "webp")
        self.quality.setEnabled(lossy)
        self.quality.setToolTip("" if lossy else
                                "This format is lossless - quality does not apply.")

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

    def _add_paths(self, paths):
        """Accept a drop of files or a folder."""
        exts = set(sc.supported_input_extensions())
        found = []
        for p in paths:
            if os.path.isdir(p):
                found += [os.path.join(p, n) for n in sorted(os.listdir(p))
                          if n.rsplit(".", 1)[-1].lower() in exts]
            elif os.path.isfile(p) and p.rsplit(".", 1)[-1].lower() in exts:
                found.append(p)
        if found:
            self.paths = sorted(set(self.paths) | set(found))
            self._refresh_input_label()

    def _clear_frames(self):
        self.paths = []
        self._refresh_input_label()

    def _refresh_input_label(self):
        self.frames.clear()
        for path in self.paths:
            item = QtWidgets.QListWidgetItem(os.path.basename(path))
            item.setToolTip(path)
            self.frames.addItem(item)
        n = len(self.paths)
        self.frames.setVisible(bool(n))
        self.drop.setVisible(not n)
        if not n:
            self.input_label.setText("No frames selected")
        else:
            folder = os.path.dirname(self.paths[0])
            self.input_label.setText(f"{n} frame{'s' if n != 1 else ''} from {folder}")
        # Stacking one frame is not stacking; say so on the control rather than
        # in a modal after the user has already committed to a run.
        ready = n >= 2
        self.preview_btn.setEnabled(ready)
        self.export_btn.setEnabled(ready)
        self.clear_btn.setEnabled(bool(n))
        if n == 1:
            self.status.show_message("Stacking needs at least two frames.", "warn")
        elif not n:
            self.status.clear()
        else:
            self.status.clear()

    def keyPressEvent(self, e):
        if e.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace) \
                and self.frames.hasFocus():
            drop = {self.frames.row(i) for i in self.frames.selectedItems()}
            if drop:
                self.paths = [p for i, p in enumerate(self.paths) if i not in drop]
                self._refresh_input_label()
                return
        super().keyPressEvent(e)

    # ---- run ----------------------------------------------------------------
    def _busy(self, on: bool):
        self.preview_btn.setEnabled(not on and len(self.paths) >= 2)
        self.export_btn.setEnabled(not on and len(self.paths) >= 2)
        self.cancel_btn.setEnabled(on)
        self.log.setVisible(on or bool(self.log.toPlainText()))
        if not on:
            self.status.hide_progress()

    def start_preview(self):
        if not self._guard():
            return
        self._busy(True)
        self.log.clear()
        self.log.setVisible(True)
        self.view.set_caption("Rendering preview…")
        self.status.show_progress(0, len(self.paths), "Starting…")
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
        self.log.setVisible(True)
        self.view.set_caption("Stacking at full resolution…")
        self.status.show_progress(0, len(self.paths), "Starting…")
        self.worker = StackWorker(
            self.paths, self.mode_combo.currentData(),
            self.method_combo.currentData(), None,
            export_path=path, fmt_key=fmt_key, quality=int(self.quality.value()),
            reject_anomalies=self.cb_reject.isChecked(),
            smooth_sky=self.cb_smooth.isChecked())
        self.worker.progress.connect(self._on_progress)
        self.worker.exported.connect(self._on_exported)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(lambda: self._busy(False))
        self.worker.start()

    def _guard(self) -> bool:
        if len(self.paths) < 2:
            self.status.show_message(
                "Select at least two frames — stacking needs a sequence.", "warn")
            return False
        return True

    def cancel(self):
        if self.worker:
            self.worker.cancel()
        self.cancel_btn.setEnabled(False)
        self.status.show_message("Cancelling…", "busy")

    # ---- worker signals -----------------------------------------------------
    def _on_progress(self, done, total, msg):
        self.status.show_progress(done, total, f"{msg}  ({done}/{total})")
        self.log.appendPlainText(msg)

    def _on_preview_ready(self, arr):
        self._last_result = arr
        h, w = arr.shape[:2]
        self.view.set_image(_np_to_pixmap(arr),
                            f"Preview — {w} × {h}, reduced resolution")
        self.status.show_message(f"Stacked {len(self.paths)} frames", "ok")

    def _on_exported(self, path, used, failed):
        self.view.set_caption(f"Exported {os.path.basename(path)}")
        self.status.show_message(
            f"Saved {os.path.basename(path)} — {used} stacked, {failed} skipped",
            "warn" if failed else "ok")
        self.log.appendPlainText(
            f"Saved {path}  (stacked {used} frame(s), {failed} skipped)")

    def _on_failed(self, msg):
        self.view.set_caption("")
        self.status.show_message(msg, "error")
        self.log.appendPlainText(f"ERROR: {msg}")
        QtWidgets.QMessageBox.warning(self, "Astro Stacker", msg)

    def changeEvent(self, e):
        if e.type() in (QtCore.QEvent.PaletteChange, QtCore.QEvent.StyleChange):
            ui.retint_tree(self)
        super().changeEvent(e)

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
