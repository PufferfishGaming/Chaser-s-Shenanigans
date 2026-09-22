"""
Photo Border - Windows 11 desktop frontend (PySide6).

Architecture
------------
Two clearly separated execution paths share one pipeline (core.process_image):

  Preview path   : single image, runs the REAL full-res pipeline on a QThread,
                   debounced ~400ms, then downscales only the finished result for
                   display. Accurate (it is literally the output, shown smaller).
                   Emits per-stage progress.

  Batch path     : a folder of images. Uses ProcessPoolExecutor to process files
                   in parallel across CPU cores. Per-FILE progress only (parallel
                   workers cannot stream per-stage progress across the process
                   boundary). One bad file is reported, not fatal.

  Single-file    : if the user points the batch at one file, it is processed
  batch          : sequentially in-thread so per-stage progress is still shown.

Output always goes to a chosen output folder, mirroring input sub-folder
structure to avoid same-name collisions.
"""
import os
import sys
import time
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed

from PySide6 import QtCore, QtGui, QtWidgets

import json

import fontcatalog
import layout as layout_mod
from border import BorderType
from core import process_image, build_preview_source, preview_source_key
from filemanager import should_include_file, get_directory_files
from worker import WorkerArgs, WorkerResult, process_one, set_below_normal_priority
import theme
import ui
from theme import ensure_applied

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

INCLUDE = ['*.jpg', '*.jpeg', '*.png', '*.JPG', '*.JPEG', '*.PNG']
EXCLUDE = ['*_border*']
PREVIEW_DISPLAY_EDGE = 900   # px, longest edge of the displayed preview

BORDER_LABELS = {
    BorderType.POLAROID: "Polaroid",
    BorderType.SMALL: "Small",
    BorderType.MEDIUM: "Medium",
    BorderType.LARGE: "Large",
}

# Rotation presets: label -> clockwise degrees. Right angles only, so every one
# of these is a lossless pixel remap rather than a resample.
ROTATION_PRESETS = [
    ("None", 0),
    ("90° clockwise", 90),
    ("180°", 180),
    ("90° anticlockwise", 270),
]

# Aspect-ratio presets: label -> width/height float (None = native, no padding).
RATIO_PRESETS = [
    ("Native (no padding)", None),
    ("1:1 Square", 1.0),
    ("4:5 Portrait", 4 / 5),
    ("5:4 Landscape", 5 / 4),
    ("3:2", 3 / 2),
    ("2:3", 2 / 3),
    ("16:9 Wide", 16 / 9),
    ("9:16 Tall", 9 / 16),
]


def module_fontdir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")


ELEMENT_COLOURS = {
    "exif": QtGui.QColor(0, 150, 255),
    "text": QtGui.QColor(255, 140, 0),
    "palette": QtGui.QColor(0, 200, 120),
}


class PreviewCanvas(QtWidgets.QLabel):
    """The preview, with draggable outlines over the three caption elements.

    Why the drag moves an outline rather than the element itself: one render of
    the real pipeline takes ~650ms with the palette on (measured), and a drag
    needs ~16ms a frame to feel attached to the cursor - about 40x out. So the
    drag moves a lightweight rectangle and the pipeline is re-run once, on
    release. The preview therefore stays literally the output rather than a
    separate approximation of it, which is the property this tool has always had.

    The pixmap is scaled here rather than by the caller so that the mapping
    between screen pixels and canvas pixels is derived from exactly the geometry
    being painted - the two cannot disagree about the scale factor.
    """
    moved = QtCore.Signal(str, float, float)    # element, x fraction, y fraction
    dragging = QtCore.Signal(str, float, float)  # same, emitted continuously while dragging

    HANDLE_PAD = 6          # px of slop around a box, so thin text is still grabbable

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMouseTracking(True)
        self._pixmap = None
        self._geometry = {}
        self._drag_element = None
        self._drag_from = None      # QPoint in widget coords, at press
        self._drag_delta = QtCore.QPoint(0, 0)
        # The dragged element's box, band and anchor AS THEY WERE AT PRESS. Every
        # delta is mapped against this snapshot, never against the live geometry.
        # Live re-rendering during a drag feeds new geometry back in, so mapping
        # against it would apply each delta to an already-moved box and the
        # element would accelerate away from the cursor.
        self._drag_ref = None
        self._hover = None

    # ---- content -------------------------------------------------------
    def set_render(self, pixmap: QtGui.QPixmap, geometry: dict):
        """Show a new render. Safe to call mid-drag.

        A drag in progress is deliberately NOT cancelled here. It used to be, and
        because live re-rendering calls straight back into this method, the first
        rendered frame killed the drag - so exactly one frame ever appeared and
        the mouse release did nothing.
        """
        self._pixmap = pixmap
        self._geometry = geometry or {}
        if self._drag_element is None:
            self._drag_delta = QtCore.QPoint(0, 0)
            self._drag_ref = None
        self.update()

    def clear_render(self):
        self._pixmap = None
        self._geometry = {}
        self.update()

    # ---- coordinate mapping --------------------------------------------
    def _fit(self):
        """(origin QPoint, scale) mapping canvas pixels to widget pixels."""
        if not self._pixmap or self._pixmap.isNull():
            return None, 1.0
        avail = self.size()
        pm = self._pixmap.size()
        if pm.width() == 0 or pm.height() == 0:
            return None, 1.0
        scale = min(avail.width() / pm.width(), avail.height() / pm.height())
        w, h = pm.width() * scale, pm.height() * scale
        origin = QtCore.QPoint(int((avail.width() - w) / 2), int((avail.height() - h) / 2))
        # The pixmap may itself be a downscaled render of the real canvas, so fold
        # that in: geometry boxes are in REAL canvas coordinates.
        canvas = self._geometry.get("canvas")
        canvas_scale = (pm.width() / canvas[0]) if canvas and canvas[0] else 1.0
        return origin, scale * canvas_scale

    def _box_rect(self, box):
        origin, scale = self._fit()
        if origin is None:
            return None
        x0, y0, x1, y1 = box
        return QtCore.QRectF(origin.x() + x0 * scale, origin.y() + y0 * scale,
                             max(1.0, (x1 - x0) * scale), max(1.0, (y1 - y0) * scale))

    def _hit(self, pos):
        """Smallest element box under `pos`, so a small item inside a big one wins."""
        best, best_area = None, None
        for name, box in (self._geometry.get("boxes") or {}).items():
            rect = self._box_rect(box)
            if rect is None:
                continue
            padded = rect.adjusted(-self.HANDLE_PAD, -self.HANDLE_PAD,
                                   self.HANDLE_PAD, self.HANDLE_PAD)
            if padded.contains(QtCore.QPointF(pos)):
                area = rect.width() * rect.height()
                if best_area is None or area < best_area:
                    best, best_area = name, area
        return best

    # ---- painting ------------------------------------------------------
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        if not self._pixmap or self._pixmap.isNull():
            painter.end()
            return
        origin, _ = self._fit()
        avail, pm = self.size(), self._pixmap.size()
        scale = min(avail.width() / pm.width(), avail.height() / pm.height())
        scaled = self._pixmap.scaled(
            max(1, int(pm.width() * scale)), max(1, int(pm.height() * scale)),
            QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        painter.drawPixmap(origin, scaled)

        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        for name, box in (self._geometry.get("boxes") or {}).items():
            if name == self._drag_element and self._drag_ref:
                # Draw from the press-time snapshot plus the raw cursor delta. The
                # live geometry for this element has already moved, so translating
                # THAT by the delta would show it at twice the distance dragged.
                rect = self._box_rect(self._drag_ref["box"])
                if rect is not None:
                    rect = rect.translated(QtCore.QPointF(self._drag_delta))
            else:
                rect = self._box_rect(box)
            if rect is None:
                continue
            colour = ELEMENT_COLOURS.get(name, QtGui.QColor(200, 200, 200))
            active = name in (self._drag_element, self._hover)
            pen = QtGui.QPen(colour, 2 if active else 1,
                             QtCore.Qt.SolidLine if active else QtCore.Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRect(rect.adjusted(-2, -2, 2, 2))
        painter.end()

    # ---- interaction ---------------------------------------------------
    def _emit_position(self, name, delta, signal):
        origin, scale = self._fit()
        ref = self._drag_ref
        if origin is None or not ref or scale <= 0:
            return False
        x_frac, y_frac = layout_mod.fraction_from_offset(
            ref["box"], ref["band"], delta.x() / scale, delta.y() / scale,
            ref["anchor"], ref["canvas"][0])
        signal.emit(name, x_frac, y_frac)
        return True

    def mouseMoveEvent(self, event):
        if self._drag_element:
            self._drag_delta = event.pos() - self._drag_from
            self.update()
            # Ask for a live re-render. A cached preview source makes one render
            # ~30ms (measured), so this genuinely tracks the cursor; the receiver
            # throttles and silently ignores it when no cache is available yet.
            if abs(self._drag_delta.x()) >= 2 or abs(self._drag_delta.y()) >= 2:
                self._emit_position(self._drag_element, self._drag_delta, self.dragging)
            return
        hover = self._hit(event.pos())
        if hover != self._hover:
            self._hover = hover
            self.setCursor(QtCore.Qt.OpenHandCursor if hover else QtCore.Qt.ArrowCursor)
            self.update()

    def mousePressEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton:
            return
        name = self._hit(event.pos())
        if not name:
            return
        box = (self._geometry.get("boxes") or {}).get(name)
        band = self._geometry.get("band")
        canvas = self._geometry.get("canvas")
        if not box or not band or not canvas:
            return
        self._drag_element = name
        self._drag_from = event.pos()
        self._drag_delta = QtCore.QPoint(0, 0)
        self._drag_ref = {
            "box": box, "band": band, "canvas": canvas,
            # The element's EFFECTIVE anchor, so the fraction recorded here is
            # read back against the same edge of the box.
            "anchor": (self._geometry.get("anchors") or {}).get(name, "left"),
        }
        self.setCursor(QtCore.Qt.ClosedHandCursor)
        self.update()

    def mouseReleaseEvent(self, event):
        if not self._drag_element:
            return
        name, delta = self._drag_element, self._drag_delta
        self.setCursor(QtCore.Qt.OpenHandCursor if self._hover else QtCore.Qt.ArrowCursor)

        # A click with no movement must not turn a default element into a
        # hand-placed one - that would silently disable its auto-fit.
        moved_enough = abs(delta.x()) >= 2 or abs(delta.y()) >= 2
        if moved_enough:
            self._emit_position(name, delta, self.moved)
        # Clear the drag AFTER emitting: `_emit_position` needs the snapshot.
        self._drag_element = None
        self._drag_ref = None
        self._drag_delta = QtCore.QPoint(0, 0)
        self.update()


# ----------------------------------------------------------------------------
# Preview worker: runs the real pipeline on ONE file in a background thread.
# ----------------------------------------------------------------------------
class PreviewWorker(QtCore.QThread):
    stage = QtCore.Signal(str, float)        # stage name, fraction
    done = QtCore.Signal(str, dict, object)  # output path, geometry, PreviewSource
    failed = QtCore.Signal(str)

    def __init__(self, params: dict, tmp_out: str, source=None):
        super().__init__()
        self.params = params
        self.tmp_out = tmp_out
        # A reusable PreviewSource from a previous render, if it is still valid.
        self.source = source
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        p = self.params

        def cb(stage_name, frac):
            if self._cancelled:
                # Cooperative cancel: raise to unwind out of the pipeline.
                raise _Cancelled()
            self.stage.emit(stage_name, frac)

        geometry = {}
        try:
            source = self.source
            if source is None:
                # The expensive, layout-independent part: decode, orient, rotate,
                # downscale and extract the palette colours. ~620ms of a ~740ms
                # cold preview, and none of it changes when the layout does.
                source = build_preview_source(
                    p["path"], p["add_exif"], rotate=p.get("rotate", 0),
                    auto_orient=p.get("auto_orient", True),
                    preview_max_edge=p.get("preview_max_edge"),
                    extract_palette=p.get("add_palette", False))
            if self._cancelled:
                return
            out = process_image(
                path=p["path"],
                add_exif=p["add_exif"],
                add_palette=p["add_palette"],
                border_type=p["border_type"],
                font=p["font"],
                boldfont=p["boldfont"],
                fontdir=p["fontdir"],
                output_root=self.tmp_out,
                input_root=os.path.dirname(p["path"]),
                progress_cb=cb,
                target_ratio=p.get("target_ratio"),
                preview_max_edge=p.get("preview_max_edge"),
                custom_text=p.get("custom_text"),
                custom_font=p.get("custom_font"),
                custom_size_mult=p.get("custom_size_mult", 1.0),
                custom_centered=p.get("custom_centered", False),
                rotate=p.get("rotate", 0),
                auto_orient=p.get("auto_orient", True),
                placements=p.get("placements"),
                geometry_out=geometry,
                preview_source=source,
            )
            if self._cancelled:
                return
            self.done.emit(out, geometry, source)
        except _Cancelled:
            return
        except Exception as e:  # noqa: BLE001
            if not self._cancelled:
                self.failed.emit(f"{type(e).__name__}: {e}")


class _Cancelled(Exception):
    pass


# ----------------------------------------------------------------------------
# Batch worker: parallel folder processing OR sequential single-file.
# ----------------------------------------------------------------------------
class BatchWorker(QtCore.QThread):
    file_done = QtCore.Signal(int, int, str, str)   # done_count, total, src, result_msg
    stage = QtCore.Signal(str, float)               # used only in sequential mode
    finished_all = QtCore.Signal(int, int)          # success_count, fail_count
    failed = QtCore.Signal(str)

    def __init__(self, paths, params: dict, output_root: str, input_root: str, max_workers: int,
                 background: bool = False):
        super().__init__()
        self.paths = paths
        self.params = params
        self.output_root = output_root
        self.input_root = input_root
        self.max_workers = max_workers
        self.background = background
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total = len(self.paths)
        if total == 0:
            self.finished_all.emit(0, 0)
            return

        # Nothing may escape this method without a signal. An exception raised in
        # QThread.run() is printed to stderr and the thread just ends: no
        # finished_all, no failed, so the window keeps Process disabled for ever
        # and the user sees a button that "does nothing". That is exactly how a
        # WorkerArgs TypeError presented.
        try:
            # Single file -> sequential, keep per-stage progress.
            if total == 1:
                self._run_sequential(total)
            else:
                self._run_parallel(total)
        except Exception as e:  # noqa: BLE001
            logger.exception("batch failed")
            self.failed.emit(f"{type(e).__name__}: {e}")

    def _run_sequential(self, total):
        p = self.params
        success = fail = 0

        def cb(stage_name, frac):
            if self._cancelled:
                raise _Cancelled()
            self.stage.emit(stage_name, frac)

        for i, path in enumerate(self.paths):
            if self._cancelled:
                break
            try:
                out = process_image(
                    path=path, add_exif=p["add_exif"], add_palette=p["add_palette"],
                    border_type=p["border_type"], font=p["font"], boldfont=p["boldfont"],
                    fontdir=p["fontdir"], output_root=self.output_root,
                    input_root=self.input_root, progress_cb=cb,
                    target_ratio=p.get("target_ratio"),
                    overwrite=p.get("overwrite", True),
                    custom_text=p.get("custom_text"),
                    custom_font=p.get("custom_font"),
                    custom_size_mult=p.get("custom_size_mult", 1.0),
                    custom_centered=p.get("custom_centered", False),
                    rotate=p.get("rotate", 0),
                    auto_orient=p.get("auto_orient", True),
                    placements=p.get("placements"),
                )
                success += 1
                self.file_done.emit(i + 1, total, path, f"Saved: {os.path.basename(out)}")
            except _Cancelled:
                break
            except Exception as e:  # noqa: BLE001
                fail += 1
                self.file_done.emit(i + 1, total, path, f"ERROR: {e}")
        self.finished_all.emit(success, fail)

    def _run_parallel(self, total):
        p = self.params
        success = fail = 0
        done = 0
        try:
            args_list = self._build_worker_args(p)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")
            return
        try:
            initializer = set_below_normal_priority if self.background else None
            with ProcessPoolExecutor(max_workers=self.max_workers,
                                     initializer=initializer) as ex:
                futures = {ex.submit(process_one, a): a.path for a in args_list}
                for fut in as_completed(futures):
                    if self._cancelled:
                        # Real cancel: drop every future that hasn't STARTED yet.
                        # cancel_futures=True (3.9+) discards the queued work so a
                        # 500-file batch cancelled at file 10 stops promptly. Only
                        # the handful already running finish (workers can't be
                        # killed mid-task). wait=False so we don't block the UI
                        # thread waiting on them.
                        ex.shutdown(wait=False, cancel_futures=True)
                        break
                    res: WorkerResult = fut.result()
                    done += 1
                    if res.error:
                        fail += 1
                        self.file_done.emit(done, total, res.path, f"ERROR: {res.error}")
                    else:
                        success += 1
                        self.file_done.emit(done, total, res.path,
                                            f"Saved: {os.path.basename(res.save_path)}")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")
            return
        self.finished_all.emit(success, fail)

    def _build_worker_args(self, p):
        return [
            WorkerArgs(
                path=path, add_exif=p["add_exif"], add_palette=p["add_palette"],
                border_type_value=p["border_type"].value, font=p["font"],
                boldfont=p["boldfont"], fontdir=p["fontdir"],
                output_root=self.output_root, input_root=self.input_root,
                target_ratio=p.get("target_ratio"),
                overwrite=p.get("overwrite", True),
                custom_text=p.get("custom_text"),
                custom_font=p.get("custom_font"),
                custom_size_mult=p.get("custom_size_mult", 1.0),
                custom_centered=p.get("custom_centered", False),
                rotate=p.get("rotate", 0),
                auto_orient=p.get("auto_orient", True),
                placements=p.get("placements"),
            )
            for path in self.paths
        ]


# ----------------------------------------------------------------------------
# Main window
# ----------------------------------------------------------------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chaser's PhotoBorder")
        self.resize(1180, 760)

        # Persistent settings (Windows: registry under Chaser/PhotoBorder).
        self.settings = QtCore.QSettings("Chaser", "PhotoBorder")

        self.input_path = None       # file or folder
        self.input_is_dir = False
        self.output_root = None
        self.preview_source = None   # single image used for preview
        self.preview_worker = None
        # Decoded/oriented/downscaled image plus extracted palette colours, kept
        # between renders. Everything a layout change can affect is cheap; this
        # holds the ~620ms of work it cannot affect.
        self._cached_source = None
        self._drag_render_clock = QtCore.QElapsedTimer()
        self._drag_render_clock.start()
        self._last_drag_render = -10000
        # Minimum gap between live drag renders, re-estimated from the last frame's
        # actual cost. Not monotonic: an early frame is often slower (cold font
        # cache), and a budget that only ever went up would leave the drag
        # sluggish for the rest of the session.
        self._live_drag_budget_ms = 30
        self.batch_worker = None
        # Who is allowed to write the status strip and stage bar. Preview and batch
        # share both, and the preview used to clear them unconditionally on every
        # render - so a debounced preview finishing just after a batch erased the
        # "N processed" result, and one landing mid-batch replaced the progress.
        # "batch" holds the strip from Process until the next input change.
        self._status_owner = "preview"
        self.tmp_preview_dir = os.path.join(
            QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.TempLocation),
            "photoborder_preview",
        )
        os.makedirs(self.tmp_preview_dir, exist_ok=True)

        self._debounce = QtCore.QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(400)
        self._debounce.timeout.connect(self._start_preview)

        self._build_ui()
        self._apply_style()
        self._load_settings()
        # After the stylesheet and the restored values, both of which change the
        # widths the controls need.
        self._fit_panel_width()
        self._panel_width_settled = False

    # ---- UI construction ----------------------------------------------------
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Left control panel: `ui.Panel` is a scrolling body plus a pinned
        # footer. The body scrolls because this panel's minimum height was
        # already 928px against a requested 760 before the Typography section
        # existed, and 1157px after it - past the usable height of a 1080p
        # screen. The footer exists because Process and Cancel were the last
        # widgets in that column, so the tool's verb sat below the fold while
        # every one of its options was visible.
        #
        # The sections fold. At 1157px of controls the user cannot see the
        # section being worked on and the one being compared against it at the
        # same time; folding what is not in use is the cheapest fix that removes
        # nothing. Placement and Batch start folded - they are the two sections
        # most often left alone.
        self.panel = ui.Panel()
        p = self.panel
        # Kept under their historical names: `_fit_panel_width` and the panel
        # width test address these directly.
        self._panel = p.body
        self._panel_scroll = p.scroll

        head = QtWidgets.QVBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(2)
        title = QtWidgets.QLabel("PhotoBorder")
        title.setObjectName("title")
        head.addWidget(title)
        head.addWidget(ui.wrap_label("Borders, EXIF & palette for your photos",
                                     "subtitle"))
        p.add_layout(head)

        # ---- Input / output ------------------------------------------------
        self.drop = ui.DropZone("Drop a photo or folder here", "or click to browse")
        self.drop.clicked.connect(self.choose_file)
        self.drop.dropped.connect(self._on_dropped)
        p.add(self.drop)

        self.input_label = ui.wrap_label("No input selected", "pathlabel")
        p.add(self.input_label)

        b_file = ui.button("Choose file…", "file")
        b_file.clicked.connect(self.choose_file)
        b_dir = ui.button("Choose folder…", "folder")
        b_dir.clicked.connect(self.choose_folder)
        p.add_layout(ui.equal_row(b_file, b_dir))

        p.add_section("Output folder")
        self.output_label = ui.wrap_label("Not set", "pathlabel")
        p.add(self.output_label)
        b_out = ui.button("Choose output folder…", "folder")
        b_out.clicked.connect(self.choose_output)
        p.add(b_out)

        # ---- Border --------------------------------------------------------
        sec_border = ui.Collapsible("Border", True)
        bgrid = ui.FormGrid()
        self.border_combo = QtWidgets.QComboBox()
        for bt in BorderType:
            self.border_combo.addItem(BORDER_LABELS[bt], bt)
        self.border_combo.setCurrentIndex(list(BorderType).index(BorderType.POLAROID))
        self.border_combo.currentIndexChanged.connect(self._schedule_preview)
        self.border_combo.currentIndexChanged.connect(self._update_ratio_hint)
        bgrid.add_row("Style", self.border_combo)

        self.rotate_combo = QtWidgets.QComboBox()
        for label, deg in ROTATION_PRESETS:
            self.rotate_combo.addItem(label, deg)
        self.rotate_combo.setToolTip(
            "Rotate the photo before the border is calculated, so a rotated "
            "landscape gets a portrait's border. Right angles only, which makes it "
            "lossless — no resampling and no cropping.\n\n"
            "Photos are already auto-oriented from their EXIF tag, so this is for "
            "deliberate rotation, not for fixing sideways files.")
        self.rotate_combo.currentIndexChanged.connect(self._invalidate_source_cache)
        self.rotate_combo.currentIndexChanged.connect(self._schedule_preview)
        bgrid.add_row("Rotate", self.rotate_combo)

        self.ratio_combo = QtWidgets.QComboBox()
        for label, val in RATIO_PRESETS:
            self.ratio_combo.addItem(label, val)
        self.ratio_combo.currentIndexChanged.connect(self._on_ratio_changed)
        bgrid.add_row("Ratio", self.ratio_combo)
        sec_border.add_layout(bgrid)

        # Optional one-line hint under the ratio control (currently unused), so
        # it stays hidden until something sets it rather than reserving a blank
        # line under the control for ever.
        self.ratio_hint = ui.wrap_label("", "hint")
        sec_border.add(self.ratio_hint)

        self.cb_exif = QtWidgets.QCheckBox("Print EXIF on border")
        self.cb_exif.setChecked(True)
        self.cb_exif.stateChanged.connect(self._schedule_preview)
        sec_border.add(self.cb_exif)

        self.cb_palette = QtWidgets.QCheckBox("Add colour palette")
        self.cb_palette.setChecked(True)
        # Toggling the palette changes whether the cached source has colours in it.
        self.cb_palette.stateChanged.connect(self._invalidate_source_cache)
        self.cb_palette.stateChanged.connect(self._schedule_preview)
        sec_border.add(self.cb_palette)
        p.add(sec_border)
        self._sections = {"border": sec_border}

        # ---- Typography ----------------------------------------------------
        # Two independent font choices: the EXIF caption (heading + body, one
        # family at two weights) and the custom text. Script faces are offered
        # for the custom text only - see fontcatalog.display_only.
        sec_type = ui.Collapsible("Typography", True)
        tgrid = ui.FormGrid()
        self.exif_font_combo = QtWidgets.QComboBox()
        for fam in fontcatalog.caption_families():
            self.exif_font_combo.addItem(fam.label, fam.key)
            self.exif_font_combo.setItemData(self.exif_font_combo.count() - 1, fam.note,
                                             QtCore.Qt.ToolTipRole)
        self.exif_font_combo.currentIndexChanged.connect(self._schedule_preview)
        tgrid.add_row("EXIF font", self.exif_font_combo)

        self.text_edit = QtWidgets.QLineEdit()
        self.text_edit.setPlaceholderText("Optional caption")
        self.text_edit.setToolTip(
            "Drawn on the bottom border next to the EXIF caption. Literal text — "
            "the same string is used for every file in a batch.")
        # Typing fires the same 400ms debounce as every other control, so the
        # preview re-renders once when you stop typing rather than per keystroke.
        self.text_edit.textChanged.connect(self._schedule_preview)
        tgrid.add_row("Custom text", self.text_edit)

        self.text_font_combo = QtWidgets.QComboBox()
        for fam in fontcatalog.all_families():
            label = f"{fam.label} (script)" if fam.display_only else fam.label
            self.text_font_combo.addItem(label, fam.key)
            self.text_font_combo.setItemData(self.text_font_combo.count() - 1, fam.note,
                                             QtCore.Qt.ToolTipRole)
        default_row = [f.key for f in fontcatalog.all_families()].index(
            fontcatalog.DEFAULT_TEXT_KEY)
        self.text_font_combo.setCurrentIndex(default_row)
        self.text_font_combo.currentIndexChanged.connect(self._schedule_preview)
        tgrid.add_row("Text font", self.text_font_combo)

        self.text_size_spin = QtWidgets.QDoubleSpinBox()
        self.text_size_spin.setRange(0.5, 3.0)
        self.text_size_spin.setSingleStep(0.1)
        self.text_size_spin.setDecimals(1)
        self.text_size_spin.setValue(1.0)
        self.text_size_spin.setSuffix(" x")
        self.text_size_spin.setToolTip(
            "Multiplier on the automatic size. 1.0 matches the EXIF body text. "
            "The result is capped so the text can never be taller than the "
            "caption band or overlap the lines above it.")
        self.text_size_spin.valueChanged.connect(self._schedule_preview)
        tgrid.add_row("Text size", self.text_size_spin)
        sec_type.add_layout(tgrid)
        p.add(sec_type)
        self._sections["typography"] = sec_type

        # ---- Placement -----------------------------------------------------
        # One row per element: anchor, vertical position, size, snap-back. The
        # anchor combo replaces the old "Centre the custom text" checkbox, which
        # it strictly supersedes - its Centre entry drives exactly the same
        # `custom_centered` behaviour, and Left/Right are new.
        sec_place = ui.Collapsible("Placement", True)
        self.placements = layout_mod.default_placements()
        self._place_widgets = {}

        sec_place.add(ui.wrap_label(
            "Drag an element directly on the preview, or set it here. Either one "
            "marks it hand-placed.", "empty_body"))

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        for col, heading in ((2, "Align"), (3, "Height"), (4, "Size")):
            lbl = QtWidgets.QLabel(heading)
            lbl.setObjectName("section")
            grid.addWidget(lbl, 0, col)

        for row, name in enumerate(layout_mod.ELEMENTS, start=1):
            # A swatch in the element's own outline colour. The preview draws
            # three differently-coloured rectangles and nothing previously said
            # which row belonged to which rectangle.
            swatch = QtWidgets.QLabel()
            swatch.setFixedSize(9, 9)
            colour = ELEMENT_COLOURS.get(name)
            if colour is not None:
                swatch.setStyleSheet(f"background: {colour.name()}; border-radius: 4px;")
            grid.addWidget(swatch, row, 0, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft)

            row_label = QtWidgets.QLabel(layout_mod.ELEMENT_SHORT_LABELS[name])
            row_label.setMinimumWidth(48)
            row_label.setToolTip(layout_mod.ELEMENT_LABELS[name])
            grid.addWidget(row_label, row, 1)

            anchor = QtWidgets.QComboBox()
            for label, value in layout_mod.ANCHOR_LABELS:
                anchor.addItem(label, value)
            anchor.setToolTip(
                f"Horizontal alignment of the {layout_mod.ELEMENT_LABELS[name].lower()}. "
                "Default leaves it exactly where it has always been, and keeps its "
                "automatic sizing.")
            # `activated`, not `currentIndexChanged`: it fires whenever the user
            # picks an entry INCLUDING the one already shown, and never on a
            # programmatic setCurrentIndex. Both matter here. After a drag the
            # combo still displays the alignment the element would snap to, so
            # with currentIndexChanged picking that same entry emitted nothing and
            # the block stayed where it was dragged - the one case where a user
            # most wants the preset to act.
            anchor.activated.connect(
                lambda _=0, n=name: self._on_anchor_changed(n))
            grid.addWidget(anchor, row, 2)

            vpos = QtWidgets.QSpinBox()
            vpos.setRange(-1, 100)
            vpos.setValue(-1)
            vpos.setSpecialValueText("auto")
            vpos.setSuffix("%")
            vpos.setToolTip(
                "Vertical position inside the caption band: 0% at the top, 100% at "
                "the bottom. auto is the default position.\n\n"
                "Setting this, or dragging the element, marks it as hand-placed — "
                "it then keeps the size it was given instead of being re-fitted "
                "around its neighbours.")
            vpos.valueChanged.connect(
                lambda _=0, n=name: self._on_placement_control_changed(n))
            grid.addWidget(vpos, row, 3)

            size = QtWidgets.QDoubleSpinBox()
            size.setRange(0.25, 3.0)
            size.setSingleStep(0.1)
            size.setDecimals(1)
            size.setValue(1.0)
            size.setSuffix(" x")
            size.setToolTip(
                "Size multiplier. Scales the element's automatic, band-derived size, "
                "so a given value looks the same at any export resolution.")
            size.valueChanged.connect(
                lambda _=0, n=name: self._on_placement_control_changed(n))
            grid.addWidget(size, row, 4)

            reset = ui.icon_button("reset", "Snap back to the default position and size.", 26)
            reset.clicked.connect(lambda _=False, n=name: self._reset_placement(n))
            grid.addWidget(reset, row, 5)

            self._place_widgets[name] = {"anchor": anchor, "vpos": vpos,
                                         "size": size, "reset": reset}

        # Stretch a trailing spacer column, not a control column, so every widget
        # keeps the natural width its content needs.
        grid.setColumnStretch(6, 1)
        sec_place.add_layout(grid)

        # Line alignment applies to the EXIF caption only - the custom text and the
        # SMALL/MEDIUM caption are single lines, which have nothing to align
        # against - so it gets its own row rather than a fifth grid column.
        lgrid = ui.FormGrid()
        self.line_align_combo = QtWidgets.QComboBox()
        for label, value in layout_mod.LINE_ALIGN_LABELS:
            self.line_align_combo.addItem(label, value)
        self.line_align_combo.setToolTip(
            "How the three EXIF lines line up with each other, separately from "
            "where the block sits. Anchoring the block right with its lines "
            "ragged-left is a different look from both lines and block right.")
        self.line_align_combo.activated.connect(self._on_line_align_changed)
        lgrid.add_row("EXIF lines", self.line_align_combo)
        sec_place.add_layout(lgrid)

        self.line_align_hint = ui.wrap_label("", "hint")
        sec_place.add(self.line_align_hint)

        reset_all = ui.button("Reset all placement", "reset")
        reset_all.clicked.connect(self._reset_all_placements)
        sec_place.add(reset_all)

        self.text_center_hint = ui.wrap_label("", "hint")
        sec_place.add(self.text_center_hint)
        p.add(sec_place)
        self._sections["placement"] = sec_place

        # Availability of Centre for the custom text depends on the border type
        # AND the EXIF toggle, so both have to re-evaluate it.
        self.border_combo.currentIndexChanged.connect(self._update_text_center_state)
        self.cb_exif.stateChanged.connect(self._update_text_center_state)
        # The displayed default alignment depends on the border type (LARGE centres
        # its caption), so a type change has to refresh the combos.
        self.border_combo.currentIndexChanged.connect(self._sync_placement_widgets)
        self.cb_exif.stateChanged.connect(self._update_line_align_state)
        self._suppress_placement_signals = False

        # ---- Batch ---------------------------------------------------------
        sec_batch = ui.Collapsible("Batch", True)
        self.cb_recursive = QtWidgets.QCheckBox("Recurse into sub-folders")
        sec_batch.add(self.cb_recursive)

        self.cb_no_overwrite = QtWidgets.QCheckBox("Don't overwrite existing files")
        self.cb_no_overwrite.setToolTip(
            "If an output file with the same name already exists (e.g. from a "
            "previous run), append ' (1)', ' (2)', etc. instead of overwriting it.")
        sec_batch.add(self.cb_no_overwrite)

        wgrid = ui.FormGrid()
        self.workers_spin = QtWidgets.QSpinBox()
        cpu = max(1, os.cpu_count() or 1)
        self.workers_spin.setRange(1, cpu)
        # Default to roughly half the logical cores: enough for good throughput
        # without saturating the whole machine. (Using ALL logical cores tends to
        # add cache/memory pressure with little throughput gain for this workload.)
        self.workers_spin.setValue(max(1, cpu // 2))
        wgrid.add_row("Parallel workers", self.workers_spin)
        sec_batch.add_layout(wgrid)

        # Background mode: low priority + reduced workers so the machine stays
        # responsive during big batches (Windows parks low-priority work on E-cores).
        self.cb_background = QtWidgets.QCheckBox("Background mode (stay responsive)")
        self.cb_background.setToolTip(
            "Runs processing at reduced priority and fewer workers so you can keep "
            "using your PC during large batches. Slightly slower overall.")
        self.cb_background.stateChanged.connect(self._on_background_toggled)
        sec_batch.add(self.cb_background)
        self.background_hint = ui.wrap_label("", "hint")
        sec_batch.add(self.background_hint)
        p.add(sec_batch)
        self._sections["batch"] = sec_batch

        p.add_stretch(1)

        # ---- Pinned action footer -------------------------------------------
        # Both bars are hidden at rest. The old panel showed an empty stage
        # trough and an empty batch trough permanently, each under its own
        # label - four widgets saying nothing whenever nothing was running.
        self.stage_bar = QtWidgets.QProgressBar()
        self.stage_bar.setRange(0, 100)
        self.stage_bar.setObjectName("thin")
        self.stage_bar.setTextVisible(False)
        self.stage_bar.setVisible(False)
        self.stage_bar.setToolTip("Stages of the file currently being rendered")
        p.add_footer(self.stage_bar)

        self.file_bar = QtWidgets.QProgressBar()
        self.file_bar.setRange(0, 100)
        self.file_bar.setFormat("%v / %m files")
        self.file_bar.setVisible(False)
        p.add_footer(self.file_bar)

        self.status = ui.StatusStrip()
        p.add_footer(self.status)

        self.run_btn = ui.primary_button("Process", "export")
        self.run_btn.clicked.connect(self.start_batch)
        self.cancel_btn = ui.button("Cancel", "close")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_batch)
        p.add_footer_layout(ui.equal_row(self.run_btn, self.cancel_btn))

        root.addWidget(p)

        # ---- Right preview area ---------------------------------------------
        right = QtWidgets.QWidget()
        right.setObjectName("preview_area")
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(ui.SPACE_LG, ui.SPACE_MD, ui.SPACE_LG, ui.SPACE_MD)
        rl.setSpacing(ui.SPACE_SM)

        self.preview_status = QtWidgets.QLabel("")
        self.preview_status.setObjectName("preview_status")
        self.preview_status.setAlignment(QtCore.Qt.AlignCenter)
        self.preview_status.setVisible(False)
        rl.addWidget(self.preview_status)

        self.preview_empty = ui.EmptyState(
            "border", "No photo open",
            "Drop a photo here, or choose one to see the border render live.",
            "Choose a photo…")
        self.preview_empty.action_btn.clicked.connect(self.choose_file)
        rl.addWidget(self.preview_empty, 1)

        self.preview_label = PreviewCanvas()
        self.preview_label.setMinimumSize(400, 400)
        self.preview_label.moved.connect(self._on_element_dragged)
        self.preview_label.dragging.connect(self._on_element_dragging)
        self.preview_label.setVisible(False)
        rl.addWidget(self.preview_label, 1)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("log")
        self.log.setFixedHeight(110)
        self.log.setVisible(False)
        rl.addWidget(self.log)
        root.addWidget(right, 1)

    def _on_dropped(self, paths):
        """Accept a dropped file or folder as the input.

        Routes through the same two methods the buttons use rather than
        reimplementing them. A first version set `input_path` directly and forgot
        `preview_source`, which every render reads - so a dropped photo loaded,
        showed its path, and then previewed nothing at all.
        """
        path = paths[0]
        if os.path.isdir(path):
            self._accept_folder(path)
        elif os.path.isfile(path):
            self._accept_file(path)

    def _accept_file(self, path):
        self._status_owner = "preview"
        self.input_path = path
        self.input_is_dir = False
        self.input_label.setText(path)
        self.drop.setText("Drop another photo or folder", "or click to browse")
        self.preview_source = path
        self._invalidate_source_cache()
        self._default_output_for(os.path.dirname(path))
        self._schedule_preview()

    def _accept_folder(self, path):
        self._status_owner = "preview"
        self.input_path = path
        self.input_is_dir = True
        self.input_label.setText(path)
        self.drop.setText("Drop another photo or folder", "or click to browse")
        self._default_output_for(path)
        # Pick first matching image for preview.
        files = get_directory_files(path, self.cb_recursive.isChecked(), INCLUDE, EXCLUDE)
        self.preview_source = files[0] if files else None
        self._invalidate_source_cache()
        if self.preview_source:
            self._schedule_preview()
        else:
            self._show_preview_canvas(False)
            self.status.show_message("No matching images in that folder.", "warn")

    def _show_preview_canvas(self, on: bool) -> None:
        """Swap between the empty state and the live canvas.

        Both exist at all times and one is hidden, rather than the canvas
        showing placeholder text: PreviewCanvas owns the drag machinery and the
        coordinate mapping, and giving it a second "nothing loaded" mode would
        put an empty-state branch inside every one of those paths.
        """
        self.preview_empty.setVisible(not on)
        self.preview_label.setVisible(on)
        self.preview_status.setVisible(on)
        if not on:
            # Drop the old render with it. Without this the canvas keeps the
            # previous photo's pixmap AND its element geometry, so picking a
            # folder with no matching images and then a valid one flashed the
            # previous photo, and a drag started in that window mapped against
            # boxes belonging to an image that was no longer on screen.
            self.preview_label.clear_render()

    # ---- placement ----------------------------------------------------------
    def _on_placement_control_changed(self, name):
        """A control changed: rebuild that element's Placement and re-preview."""
        if self._suppress_placement_signals:
            return
        w = self._place_widgets[name]
        current = self.placements.get(name) or layout_mod.Placement()
        vpos = w["vpos"].value()
        # Height and size only. The anchor has its own handler because choosing an
        # alignment must additionally clear the hand-placed x; a size change must
        # not.
        self.placements[name] = layout_mod.Placement(
            anchor=current.anchor,
            x=current.x,
            y=None if vpos < 0 else vpos / 100.0,
            size_mult=w["size"].value(),
            line_align=current.line_align,
        )
        self._update_text_center_state()
        self._schedule_preview()

    def _border_type_name(self):
        bt = self.border_combo.currentData()
        return bt.name if bt is not None else "POLAROID"

    def _on_anchor_changed(self, name):
        """An alignment was chosen: apply it and discard any hand-placed x.

        A stored x takes priority over the anchor in `layout.resolve_offset`, so
        without clearing it the presets did nothing after a drag - which is
        exactly why they appeared to work only for elements that had never been
        dragged.
        """
        if self._suppress_placement_signals:
            return
        current = self.placements.get(name) or layout_mod.Placement()
        anchor = self._place_widgets[name]["anchor"].currentData()
        self.placements[name] = current.realigned(anchor)
        self._update_text_center_state()
        self._schedule_preview()

    def _on_line_align_changed(self, _index=0):
        if self._suppress_placement_signals:
            return
        current = self.placements.get("exif") or layout_mod.Placement()
        self.placements["exif"] = layout_mod.replace_line_align(
            current, self.line_align_combo.currentData())
        self._schedule_preview()

    def _on_element_dragged(self, name, x_frac, y_frac):
        current = self.placements.get(name) or layout_mod.Placement()
        self.placements[name] = current.placed(x_frac, y_frac)
        self._sync_placement_widgets()
        self._log(f"{layout_mod.ELEMENT_LABELS[name]} placed by hand "
                  f"({x_frac * 100:.0f}%, {y_frac * 100:.0f}% of band) — "
                  f"it keeps its current size from now on")
        # The live frames during the drag were already the real pipeline at
        # preview scale, so this final pass is only there to settle the last
        # position; it goes through the usual debounce.
        self._schedule_preview()

    def _reset_placement(self, name):
        """Snap back: drop the hand-placed position, anchor AND size."""
        self.placements[name] = layout_mod.Placement()
        self._sync_placement_widgets()
        self._schedule_preview()

    def _reset_all_placements(self):
        self.placements = layout_mod.default_placements()
        self._sync_placement_widgets()
        self._schedule_preview()

    def _sync_placement_widgets(self):
        """Push `self.placements` into the controls without re-triggering them."""
        bt_name = self._border_type_name()
        self._suppress_placement_signals = True
        try:
            for name, w in self._place_widgets.items():
                pl = self.placements.get(name) or layout_mod.Placement()
                # An untouched element shows the alignment it is actually using,
                # rather than the word "Default" next to three real alignments one
                # of which it already is.
                shown = pl.anchor or layout_mod.default_anchor(name, bt_name)
                w["anchor"].setCurrentIndex(max(0, w["anchor"].findData(shown)))
                w["vpos"].setValue(-1 if pl.y is None else int(round(pl.y * 100)))
                w["size"].setValue(pl.size_mult)
            exif_pl = self.placements.get("exif") or layout_mod.Placement()
            shown_lines = exif_pl.line_align or layout_mod.default_line_align("exif", bt_name)
            self.line_align_combo.setCurrentIndex(
                max(0, self.line_align_combo.findData(shown_lines)))
        finally:
            self._suppress_placement_signals = False
        self._update_text_center_state()
        self._update_line_align_state()

    def _update_line_align_state(self):
        """Line alignment needs more than one line to mean anything."""
        if not getattr(self, "line_align_combo", None):
            return
        stacked = self.border_combo.currentData() in (BorderType.POLAROID, BorderType.LARGE)
        exif_on = self.cb_exif.isChecked()
        enabled = stacked and exif_on
        self.line_align_combo.setEnabled(enabled)
        if not exif_on:
            self.line_align_hint.setText("No EXIF caption to align.")
        elif not stacked:
            self.line_align_hint.setText(
                f"{BORDER_LABELS.get(self.border_combo.currentData(), 'This border')} draws the "
                "caption as a single row, so there are no lines to align.")
        else:
            self.line_align_hint.setText("")

    def _text_anchor(self):
        return (self.placements.get("text") or layout_mod.Placement()).anchor

    def _set_text_center_display(self, enabled: bool, forced: bool = None, hint: str = ""):
        """Enable/disable the custom text's Centre option and show a hint.

        Centre is the one anchor with a structural meaning rather than a purely
        horizontal one - it is what drives `custom_centered`, which moves the
        custom text out of the stacked block and into the band's centre. Where
        that is not possible the entry is disabled rather than silently ignored.
        """
        combo = self._place_widgets["text"]["anchor"]
        centre_idx = combo.findData("center")
        if centre_idx >= 0:
            model = combo.model()
            item = model.item(centre_idx)
            if item is not None:
                item.setEnabled(enabled)
        if forced is not None and not enabled:
            blocked = combo.blockSignals(True)
            combo.setCurrentIndex(combo.findData("center") if forced
                                  else max(0, combo.findData(self._text_anchor())))
            combo.blockSignals(blocked)
        self.text_center_hint.setText(hint)

    def _update_text_center_state(self):
        """Enable/disable the centre toggle to match what the pipeline will honour.

        Centring needs the custom text to have a line of its own. POLAROID and
        LARGE always give it one. SMALL and MEDIUM lay the caption out as a single
        horizontal row and make the custom text its last segment, so a centred
        segment would be drawn on top of the EXIF caption - unless the EXIF caption
        is switched off, in which case the band is empty and the line owns it.

        LARGE is a special case worth being honest about in the UI rather than
        pretending the toggle does something: its caption is centred already, so
        the box is shown ticked and disabled.
        """
        if not getattr(self, "_place_widgets", None):
            return
        bt = self.border_combo.currentData()
        exif_on = self.cb_exif.isChecked()

        if bt == BorderType.LARGE:
            self._set_text_center_display(
                False, hint="Large centres its caption already, so Centre is the default there.")
        elif bt == BorderType.POLAROID:
            self._set_text_center_display(True)
        elif exif_on:
            self._set_text_center_display(
                False,
                hint=f"{BORDER_LABELS.get(bt, 'This border')} draws the caption as one row and "
                     "puts the custom text at its end, so Centre isn't available. Turn off "
                     "\"Print EXIF on border\" — or just drag it — to place it freely.")
        else:
            self._set_text_center_display(True)

    def _apply_style(self):
        # Suite-wide look (incl. light/dark mode) is applied app-wide by theme.py
        # three tools stay visually consistent.
        ensure_applied()


    # ---- input/output selection --------------------------------------------
    def choose_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose image", "", "Images (*.jpg *.jpeg *.png)")
        if path:
            self._accept_file(path)

    def choose_folder(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose folder")
        if path:
            self._accept_folder(path)

    def choose_output(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose output folder")
        if path:
            self.output_root = path
            self.output_label.setText(path)

    def _default_output_for(self, base):
        if not self.output_root:
            self.output_root = os.path.join(base, "bordered")
            self.output_label.setText(self.output_root)

    # ---- preview ------------------------------------------------------------
    def _on_background_toggled(self):
        on = self.cb_background.isChecked()
        # In background mode we override the worker count to a low fixed value and
        # disable the spinbox so there is one source of truth at a time.
        self.workers_spin.setEnabled(not on)
        if on:
            cpu = max(1, os.cpu_count() or 1)
            bg = self._background_worker_count()
            self.background_hint.setText(
                f"Low priority, {bg} of {cpu} workers. Machine stays responsive; batch is slower.")
        else:
            self.background_hint.setText("")

    def _background_worker_count(self):
        # A quarter of logical cores, at least 1, capped at 4 - a small footprint
        # that leaves the machine usable.
        cpu = max(1, os.cpu_count() or 1)
        return max(1, min(4, cpu // 4))

    def _effective_workers(self):
        if self.cb_background.isChecked():
            return self._background_worker_count()
        return self.workers_spin.value()

    def _current_params(self):
        exif_key = self.exif_font_combo.currentData() or fontcatalog.DEFAULT_KEY
        text_key = self.text_font_combo.currentData() or fontcatalog.DEFAULT_TEXT_KEY
        custom_text = self.text_edit.text().strip()
        return {
            "add_exif": self.cb_exif.isChecked(),
            "add_palette": self.cb_palette.isChecked(),
            "border_type": self.border_combo.currentData(),
            "target_ratio": self.ratio_combo.currentData(),
            # (filename, variant_index, weight_name) - the weight matters because
            # most of the bundled families are variable fonts. Plain tuples, so
            # they still pickle across the ProcessPoolExecutor boundary.
            "font": fontcatalog.spec(exif_key),
            "boldfont": fontcatalog.spec(exif_key, bold=True),
            "fontdir": module_fontdir(),
            "custom_text": custom_text or None,
            "custom_font": fontcatalog.spec(text_key, default=fontcatalog.DEFAULT_TEXT_KEY)
                           if custom_text else None,
            "custom_size_mult": self.text_size_spin.value(),
            # Send the raw checkbox state; core.process_image decides whether it is
            # honourable for this border type and EXIF combination, so the GUI and
            # the CLI cannot drift apart on that rule.
            # The custom text's Centre anchor IS the old centred behaviour.
            "custom_centered": self._text_anchor() == "center",
            "placements": {k: v for k, v in self.placements.items()},
            "rotate": self.rotate_combo.currentData() or 0,
            # Always on. Cameras tag rotation rather than rewriting pixels, and the
            # old behaviour sized the border from the untagged pixels and then
            # copied the tag through, so such files came out a quarter turn wrong.
            # There is no reason to offer that as a choice; `--no-auto-orient` is
            # the CLI escape hatch for a file whose own tag is wrong.
            "auto_orient": True,
        }

    def _on_ratio_changed(self):
        self._update_ratio_hint()
        self._schedule_preview()

    def _update_ratio_hint(self):
        # No border type overrides the ratio control any more, so nothing to warn
        # about. Kept (and wired to the combos) so a future override has a home.
        self.ratio_hint.setText("")

    def _invalidate_source_cache(self):
        """Drop the cached source. Only the inputs it actually depends on do this.

        Those are the file itself, its mtime, the rotation, auto-orientation and
        the preview scale - `core.preview_source_key` is the authority. Border
        type, ratio, fonts, text and placement are all layout, and layout is what
        the cache exists to make cheap.
        """
        if self._cached_source is not None:
            self._cached_source.close()
            self._cached_source = None

    def _valid_cached_source(self):
        if self._cached_source is None or not self.preview_source:
            return None
        want = preview_source_key(self.preview_source, self.rotate_combo.currentData() or 0,
                                  True, PREVIEW_DISPLAY_EDGE)
        return self._cached_source if self._cached_source.key == want else None

    def _on_element_dragging(self, name, x_frac, y_frac):
        """Re-render while the drag is in progress, if it can be done in time.

        Runs synchronously on the GUI thread on purpose: a cached re-render is
        ~30ms, and a queue of background renders would deliver frames out of
        order behind the cursor. Throttled, and skipped entirely until the first
        full render has produced a cache - so the very first move after opening a
        file just moves the outline.
        """
        source = self._valid_cached_source()
        if source is None:
            return
        now = self._drag_render_clock.elapsed()
        if now - self._last_drag_render < self._live_drag_budget_ms:
            return

        current = self.placements.get(name) or layout_mod.Placement()
        self.placements[name] = current.placed(x_frac, y_frac)

        params = self._current_params()
        params["path"] = self.preview_source
        params["preview_max_edge"] = PREVIEW_DISPLAY_EDGE
        geometry = {}
        started = self._drag_render_clock.elapsed()
        try:
            out = process_image(
                path=params["path"], add_exif=params["add_exif"],
                add_palette=params["add_palette"], border_type=params["border_type"],
                font=params["font"], boldfont=params["boldfont"],
                fontdir=params["fontdir"], output_root=self.tmp_preview_dir,
                input_root=os.path.dirname(params["path"]),
                target_ratio=params.get("target_ratio"),
                preview_max_edge=PREVIEW_DISPLAY_EDGE,
                custom_text=params.get("custom_text"),
                custom_font=params.get("custom_font"),
                custom_size_mult=params.get("custom_size_mult", 1.0),
                custom_centered=params.get("custom_centered", False),
                rotate=params.get("rotate", 0),
                auto_orient=params.get("auto_orient", True),
                placements=params.get("placements"),
                geometry_out=geometry,
                preview_source=source,
            )
        except Exception:  # noqa: BLE001 - a dropped drag frame is not worth an error box
            return
        elapsed = self._drag_render_clock.elapsed() - started
        # Track the real cost in both directions, so a single slow frame does not
        # permanently throttle the drag.
        self._live_drag_budget_ms = max(16, min(400, int(elapsed * 1.2)))
        self._last_drag_render = self._drag_render_clock.elapsed()

        pix = QtGui.QPixmap(out)
        if not pix.isNull():
            # Deliberately NOT syncing the placement spin boxes here: that rebuilds
            # three rows of widgets on every frame for numbers the user is not
            # reading mid-drag. They are updated once, on release.
            self.preview_label.set_render(pix, geometry)

    def _schedule_preview(self):
        if self.preview_source:
            self._debounce.start()   # restart -> debounce

    def _start_preview(self):
        if not self.preview_source:
            return
        # Cancel any in-flight preview render.
        if self.preview_worker and self.preview_worker.isRunning():
            self.preview_worker.cancel()
            self.preview_worker.wait(2000)

        params = self._current_params()
        params["path"] = self.preview_source
        # Render previews from a downscaled source so a full 33MP file (or a huge
        # wide-ratio canvas) renders in a fraction of a second instead of grinding
        # at full resolution. Border proportions differ by <1% from the full-res
        # output, which is imperceptible in a preview.
        params["preview_max_edge"] = PREVIEW_DISPLAY_EDGE
        if self._status_owner == "preview":
            self.status.show_message("Rendering preview…", "busy")
            self.stage_bar.setVisible(True)
        self.preview_worker = PreviewWorker(params, self.tmp_preview_dir,
                                            source=self._valid_cached_source())
        self.preview_worker.stage.connect(self._on_stage)
        self.preview_worker.done.connect(self._on_preview_done)
        self.preview_worker.failed.connect(self._on_preview_failed)
        self.preview_worker.start()

    def _on_stage(self, stage, frac):
        # Both workers report stages here; a preview's must not overwrite a batch.
        from_batch = self.batch_worker is not None and self.sender() is self.batch_worker
        if not from_batch and self._status_owner != "preview":
            return
        self.stage_bar.setVisible(True)
        self.stage_bar.setValue(int(frac * 100))
        self.status.show_message(f"{stage}…", "busy")

    def _on_preview_done(self, out_path, geometry, source):
        if source is not None and source is not self._cached_source:
            if self._cached_source is not None:
                self._cached_source.close()
            self._cached_source = source
        pix = QtGui.QPixmap(out_path)
        if pix.isNull():
            if self._status_owner == "preview":
                self.status.show_message("Preview failed to load", "error")
                self.stage_bar.setVisible(False)
            return
        # The canvas scales the pixmap itself so its screen->canvas mapping comes
        # from the same numbers it paints with.
        self._show_preview_canvas(True)
        self.preview_label.set_render(pix, geometry)
        self.preview_status.setText(
            f"{os.path.basename(self.preview_source)}  ·  drag an outline to move it")
        if self._status_owner == "preview":
            self.stage_bar.setVisible(False)
            self.status.clear()

    def _on_preview_failed(self, msg):
        if self._status_owner == "preview":
            self.status.show_message(f"Preview error: {msg}", "error")
            self.stage_bar.setVisible(False)
        self._log(f"Preview error: {msg}")

    # ---- batch processing ---------------------------------------------------
    def start_batch(self):
        if not self.input_path:
            self.status.show_message("No input selected.", "warn")
            self._log("No input selected.")
            return
        if not self.output_root:
            self.status.show_message("No output folder selected.", "warn")
            self._log("No output folder selected.")
            return

        if self.input_is_dir:
            input_root = os.path.abspath(self.input_path)
            paths = get_directory_files(self.input_path, self.cb_recursive.isChecked(), INCLUDE, EXCLUDE)
        else:
            input_root = os.path.dirname(os.path.abspath(self.input_path))
            paths = [self.input_path] if should_include_file(self.input_path, INCLUDE, EXCLUDE) else []

        if not paths:
            self.status.show_message("No images matched.", "warn")
            self._log("No images matched.")
            return

        os.makedirs(self.output_root, exist_ok=True)
        params = self._current_params()
        params["overwrite"] = not self.cb_no_overwrite.isChecked()
        self.file_bar.setRange(0, len(paths))
        self.file_bar.setValue(0)
        self.file_bar.setVisible(True)
        self._status_owner = "batch"
        self.status.show_message(f"Processing {len(paths)} file(s)…", "busy")
        self._log(f"Processing {len(paths)} file(s) → {self.output_root}")
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        self.batch_worker = BatchWorker(
            paths, params, self.output_root, input_root,
            self._effective_workers(), background=self.cb_background.isChecked())
        self.batch_worker.file_done.connect(self._on_file_done)
        self.batch_worker.stage.connect(self._on_stage)
        self.batch_worker.finished_all.connect(self._on_batch_finished)
        self.batch_worker.failed.connect(self._on_batch_failed)
        self.batch_worker.start()

    def _on_file_done(self, done, total, src, msg):
        self.file_bar.setValue(done)
        self.status.show_message(
            f"{os.path.basename(src)}  ({done}/{total})", "busy")
        self._log(f"[{done}/{total}] {os.path.basename(src)} — {msg}")

    def _on_batch_finished(self, success, fail):
        self._log(f"Done. {success} succeeded, {fail} failed.")
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.stage_bar.setValue(0)
        self.stage_bar.setVisible(False)
        self.file_bar.setVisible(False)
        self.status.show_message(
            f"{success} processed, {fail} failed" if fail else f"{success} processed",
            "warn" if fail else "ok")

    def _on_batch_failed(self, msg):
        # Separate from _on_preview_failed on purpose: that one leaves the batch
        # controls alone, so a failed batch routed there kept Process disabled.
        self._log(f"Batch failed: {msg}")
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.stage_bar.setVisible(False)
        self.file_bar.setVisible(False)
        self._status_owner = "batch"
        self.status.show_message(f"Batch failed: {msg}", "error")

    def cancel_batch(self):
        if self.batch_worker and self.batch_worker.isRunning():
            self.batch_worker.cancel()
            self.status.show_message(
                "Cancelling… in-flight files will finish.", "busy")
            self._log("Cancelling… (in-flight files will finish)")

    def _log(self, msg):
        # The log reveals itself on its first line. A permanently-visible empty
        # 110px box under the preview cost the photograph that much height for
        # the whole session in exchange for nothing.
        self.log.setVisible(True)
        self.log.appendPlainText(msg)

    def changeEvent(self, e):
        # Drawn pixmaps (the empty state's mark, the icon buttons) are baked at
        # the colour they were painted with and do not follow a live theme
        # switch on their own.
        if e.type() in (QtCore.QEvent.PaletteChange, QtCore.QEvent.StyleChange):
            ui.retint_tree(self)
        super().changeEvent(e)

    def _fit_panel_width(self):
        """Size the control panel to whatever its contents actually need.

        Delegates to `ui.Panel.fit_width`, which is the same measurement this
        method used to do inline, extended to cover the pinned footer - the
        footer holds Process and Cancel, which are often the widest things in
        the column, and measuring only the scrolling body would clip them.

        The width is not predictable from here: it depends on the system font,
        `theme.py`'s stylesheet, the display scaling and the locale's decimal
        separator ("1,0 x" is wider than "1.0 x"). Two hardcoded values were both
        wrong on some machine - the second clipped the reset buttons and the
        right-hand end of every combo behind the preview area.
        """
        panel = getattr(self, "panel", None)
        if panel is None:
            return
        panel.fit_width(minimum=360)

    def showEvent(self, e):
        super().showEvent(e)
        # Hints are more reliable once the widgets have been realised, so measure
        # once more on the first show and then leave it alone.
        if not getattr(self, "_panel_width_settled", False):
            self._panel_width_settled = True
            self._fit_panel_width()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # PreviewCanvas rescales in paintEvent, so there is nothing to redo here;
        # repainting keeps the element outlines aligned with the new scale.
        self.preview_label.update()

    def closeEvent(self, e):
        if self.preview_worker and self.preview_worker.isRunning():
            self.preview_worker.cancel()
            self.preview_worker.wait(2000)
        if self.batch_worker and self.batch_worker.isRunning():
            self.batch_worker.cancel()
            self.batch_worker.wait(3000)
        self._invalidate_source_cache()
        self._save_settings()
        super().closeEvent(e)

    # ---- settings persistence ----------------------------------------------
    def _save_sections(self):
        """Remember which panel sections the user folded away."""
        for key, sec in getattr(self, "_sections", {}).items():
            self.settings.setValue(f"section_{key}", sec.isExpanded())

    def _load_sections(self):
        """Restore fold state. Everything starts expanded on a first run, so a
        control the user has never seen is never hidden from them."""
        for key, sec in getattr(self, "_sections", {}).items():
            v = self.settings.value(f"section_{key}", True)
            on = v.lower() == "true" if isinstance(v, str) else bool(v)
            sec.setExpanded(on)

    def _save_settings(self):
        self._save_sections()
        s = self.settings
        s.setValue("input_path", self.input_path or "")
        s.setValue("input_is_dir", self.input_is_dir)
        s.setValue("output_root", self.output_root or "")
        s.setValue("border_index", self.border_combo.currentIndex())
        s.setValue("ratio_index", self.ratio_combo.currentIndex())
        s.setValue("rotate_deg", self.rotate_combo.currentData() or 0)
        s.setValue("exif", self.cb_exif.isChecked())
        s.setValue("palette", self.cb_palette.isChecked())
        s.setValue("recursive", self.cb_recursive.isChecked())
        s.setValue("no_overwrite", self.cb_no_overwrite.isChecked())
        s.setValue("background", self.cb_background.isChecked())
        s.setValue("workers", self.workers_spin.value())
        # Font choices and custom text are persisted by KEY, not combo index, so
        # reordering or adding families in fontcatalog cannot silently reassign a
        # remembered choice to a different font.
        s.setValue("exif_font_key", self.exif_font_combo.currentData() or "")
        s.setValue("text_font_key", self.text_font_combo.currentData() or "")
        s.setValue("custom_text", self.text_edit.text())
        s.setValue("text_size_mult", self.text_size_spin.value())
        # JSON rather than a nested QVariant: QSettings' nested-dict round-tripping
        # is platform-dependent, and settings are never load-bearing here.
        s.setValue("placements", json.dumps(layout_mod.placements_to_settings(self.placements)))
        s.sync()

    def _load_settings(self):
        self._load_sections()
        s = self.settings

        def get_bool(key, default):
            v = s.value(key, default)
            # QSettings may return strings ('true'/'false') depending on platform.
            if isinstance(v, str):
                return v.lower() == "true"
            return bool(v)

        # Options first (always safe to restore).
        bi = s.value("border_index", None)
        if bi is not None:
            try:
                # Clamp to range: a stale saved index (e.g. the removed Instagram
                # type) would otherwise make setCurrentIndex clear the selection,
                # leaving currentData() == None and crashing on process.
                idx = max(0, min(int(bi), self.border_combo.count() - 1))
                self.border_combo.setCurrentIndex(idx)
            except (ValueError, TypeError):
                pass
        rd = s.value("rotate_deg", None)
        if rd is not None:
            # Persisted by DEGREES, not combo index, so reordering the presets
            # cannot silently turn a saved "None" into a 180-degree flip.
            try:
                idx = self.rotate_combo.findData(int(rd))
                self.rotate_combo.setCurrentIndex(idx if idx >= 0 else 0)
            except (ValueError, TypeError):
                self.rotate_combo.setCurrentIndex(0)

        ri = s.value("ratio_index", None)
        if ri is not None:
            try:
                self.ratio_combo.setCurrentIndex(int(ri))
            except (ValueError, TypeError):
                pass

        self.cb_exif.setChecked(get_bool("exif", True))
        self.cb_palette.setChecked(get_bool("palette", True))
        self.cb_recursive.setChecked(get_bool("recursive", False))
        self.cb_no_overwrite.setChecked(get_bool("no_overwrite", False))
        self.cb_background.setChecked(get_bool("background", False))

        def select_key(combo, key, fallback):
            # Unknown or missing key -> fall back rather than clearing the combo.
            # A combo left with no selection returns None from currentData(),
            # which is exactly how the stale-border-index crash used to happen.
            idx = combo.findData(key)
            if idx < 0:
                idx = combo.findData(fallback)
            combo.setCurrentIndex(max(0, idx))

        select_key(self.exif_font_combo, s.value("exif_font_key", ""), fontcatalog.DEFAULT_KEY)
        select_key(self.text_font_combo, s.value("text_font_key", ""), fontcatalog.DEFAULT_TEXT_KEY)
        self.text_edit.setText(s.value("custom_text", "") or "")
        try:
            self.text_size_spin.setValue(float(s.value("text_size_mult", 1.0)))
        except (ValueError, TypeError):
            self.text_size_spin.setValue(1.0)

        w = s.value("workers", None)
        if w is not None:
            try:
                self.workers_spin.setValue(int(w))
            except (ValueError, TypeError):
                pass
        raw = s.value("placements", "")
        loaded = None
        if raw:
            try:
                loaded = json.loads(raw)
            except (ValueError, TypeError):
                loaded = None
        if loaded is not None:
            self.placements = layout_mod.placements_from_settings(loaded)
        elif get_bool("text_center", False):
            # Migrate the superseded checkbox: it meant exactly the Centre anchor.
            self.placements["text"] = layout_mod.Placement(anchor="center")
        self._sync_placement_widgets()

        # Re-apply background toggle side effects (disables spinbox + hint).
        self._on_background_toggled()
        # ... and the centre-toggle availability, which depends on the border type
        # and EXIF state just restored above.
        self._update_text_center_state()
        self._update_ratio_hint()

        # Paths last, and only if they still exist - a stale path (unplugged
        # drive, deleted folder) must NOT be restored, or it could break the
        # preview on launch. Silently skip anything missing.
        out = s.value("output_root", "")
        if out and os.path.isdir(out):
            self.output_root = out
            self.output_label.setText(out)

        inp = s.value("input_path", "")
        is_dir = get_bool("input_is_dir", False)
        if inp and os.path.exists(inp):
            self.input_path = inp
            self.input_is_dir = is_dir
            self.input_label.setText(inp)
            if is_dir:
                files = get_directory_files(inp, self.cb_recursive.isChecked(), INCLUDE, EXCLUDE)
                self.preview_source = files[0] if files else None
            else:
                self.preview_source = inp
            if self.preview_source:
                self._schedule_preview()


def main():
    # Required for ProcessPoolExecutor under PyInstaller/spawn on Windows.
    from multiprocessing import freeze_support
    freeze_support()
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
