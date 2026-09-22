"""
Chaser's Shenanigans - suite launcher (PySide6).

A home window with one card per tool. Each card opens its tool as a separate
top-level window; the launcher stays open so you can hop between tools.

Why a single process (not subprocess-per-tool)
----------------------------------------------
All tools share one QApplication. The only tool that uses multiprocessing is
PhotoBorder (its parallel batch via ProcessPoolExecutor). That works fine here
because:
  * the pool's target, process_one, lives in worker.py (a top-level importable
    module), so 'spawn' re-imports it cleanly in each worker, and
  * freeze_support() is called below before the QApplication, as PyInstaller's
    'spawn' on Windows requires.
The `if __name__ == "__main__"` guard stops workers from re-launching the GUI.

Layout notes
------------
The card grid reflows (`ui.FlowGrid`). The previous version put the five cards
in one fixed QHBoxLayout row and gave that row all the vertical stretch, which
produced the launcher's two worst habits: on a narrow window the cards were
squeezed to unreadable columns, and at any normal height each card stretched to
the full window with the description at the top, the Open button pinned to the
bottom and ~470px of dead space between them. Cards now take their natural
height and the leftover space goes below the grid, where it belongs.

A card also shows whether its tool is *running*, because opening a tool twice
from the launcher used to give you two windows of the same tool with no hint
that the first one was already behind you.
"""
import sys
import logging

from PySide6 import QtCore, QtGui, QtWidgets

import theme
import ui
from theme import ensure_applied, resolved_mode, set_mode, icon_path, set_app_user_model_id
from updater import run_update_check, current_sha

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Import results, filled in lazily. (class, error) per module name.
_tool_cache: dict = {}


def _load_tool(module_name):
    """Import a tool's MainWindow, returning (class, None) or (None, error).

    A tool whose dependencies are missing (e.g. the Astro Stacker without numpy)
    must NOT take down the whole launcher - its card is disabled instead, and the
    other tools plus the updater keep working.

    Cached, because this is now called from two places: the deferred probe and a
    card click that beats the probe to it.
    """
    hit = _tool_cache.get(module_name)
    if hit is not None:
        return hit
    try:
        mod = __import__(module_name, fromlist=["MainWindow"])
        result = (mod.MainWindow, None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tool '%s' unavailable: %s", module_name, exc)
        result = (None, exc)
    _tool_cache[module_name] = result
    return result


# Displayed bottom-left in the launcher. Bump this and push to main to test the
# auto-updater - the bump is a new commit, so copies will pull it and the number
# they show will change. (The updater compares commit SHAs, not this string.)
__version__ = "4.0"


# (title, icon, one-line summary, detail, module name)
#
# The module is a NAME, not an imported class: importing the five tool modules
# at import time cost ~840ms of the launcher's startup, almost all of it
# stacker_gui and quickedit_gui pulling numpy/scipy/scikit-image/astropy. See
# `_probe_next_tool`.
#
# The summary is what the card shows; the detail is the tooltip. Splitting them
# is what lets every card be the same height without truncating anything - the
# old single paragraph ran to five lines for Metadata and two for Astro Stacker,
# so the row of cards had a ragged internal rhythm even before the dead space.
TOOLS = [
    ("PhotoBorder", "border",
     "Borders, EXIF strips and colour palettes, with a live preview.",
     "Add borders, EXIF strips and colour palettes. Batch a whole folder in "
     "parallel with a live preview.",
     "photoborder_gui"),
    ("Format Converter", "convert",
     "Convert between JPEG, PNG, WEBP, TIFF, BMP and HEIF.",
     "Convert images between JPEG, PNG, WEBP, TIFF, BMP and HEIF/HEIC/HIF - "
     "keeping EXIF where the format allows.",
     "converter_gui"),
    ("Metadata Baker", "tag",
     "Copy EXIF between images, or edit every raw tag.",
     "Copy EXIF from one image into another (e.g. restore camera metadata onto "
     "an export), edit fields, or browse and edit every raw EXIF tag.",
     "metadata_gui"),
    ("Astro Stacker", "stars",
     "Stack a night-sky sequence into sharp stars or trails.",
     "Stack a night-sky sequence into sharp stars (aligned) or star trails. "
     "RAW in; TIFF / FITS out.",
     "stacker_gui"),
    ("Quick Edit", "wand",
     "Film simulations, white balance and one-click looks.",
     "Film simulations, white balance, light-pollution gradient removal and "
     "one-click looks, live preview. RAW in, 8/16-bit out.",
     "quickedit_gui"),
]


# External links shown as a footer row in the launcher. (label, glyph, url).
# Glyphs are drawn at runtime by _link_icon() - original, generic marks rather
# than the brands' trademarked logos.
LINKS = [
    ("Support on Ko-fi", "kofi", "https://ko-fi.com/pufferfishgaming"),
    ("Instagram", "instagram", "https://www.instagram.com/stormchaserphotography/"),
    ("GitHub", "github", "https://github.com/PufferfishGaming/Chaser-s-Shenanigans"),
]


def _link_icon(kind: str, color: str = None, accent: str = "#ff6b52") -> QtGui.QIcon:
    """Draw a small, original glyph for a footer link and return it as a QIcon.

    Generic marks (coffee cup / camera / git-branch), not the brand logos.
    Painted on a transparent 48px canvas so they stay crisp when Qt scales them.

    The theme-following glyphs (update, sun, moon) live in `ui.icon` now; only
    the three link marks that have no general-purpose equivalent stay here.
    """
    color = color or theme.palette_color("GLYPH")
    px = QtGui.QPixmap(48, 48)
    px.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(px)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor(color))
    pen.setWidthF(3.0)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(QtCore.Qt.NoBrush)

    if kind == "kofi":
        # Coffee cup: body, handle, steam - with a small accent heart.
        p.drawRoundedRect(QtCore.QRectF(11, 17, 22, 21), 4, 4)
        p.drawArc(QtCore.QRectF(31, 19, 12, 14), 90 * 16, -180 * 16)  # handle
        p.drawLine(QtCore.QPointF(17, 12), QtCore.QPointF(17, 8))      # steam
        p.drawLine(QtCore.QPointF(24, 12), QtCore.QPointF(24, 8))
        heart = QtGui.QPainterPath()
        heart.moveTo(22, 31)
        heart.cubicTo(18, 27, 18.5, 23.5, 22, 25)
        heart.cubicTo(25.5, 23.5, 26, 27, 22, 31)
        p.fillPath(heart, QtGui.QColor(accent))
    elif kind == "instagram":
        # Camera: frame, lens, flash dot.
        p.drawRoundedRect(QtCore.QRectF(9, 12, 30, 26), 7, 7)
        p.drawEllipse(QtCore.QPointF(24, 25), 7, 7)
        p.setBrush(QtGui.QColor(color))
        p.drawEllipse(QtCore.QPointF(33, 17.5), 1.7, 1.7)
        p.setBrush(QtCore.Qt.NoBrush)
    elif kind == "github":
        # Git-branch mark: two nodes on a trunk, one branched node.
        p.drawLine(QtCore.QPointF(17, 17), QtCore.QPointF(17, 33))
        branch = QtGui.QPainterPath()
        branch.moveTo(17, 26)
        branch.cubicTo(28, 26, 33, 25, 33, 18)
        p.drawPath(branch)
        p.setBrush(QtGui.QColor(color))
        for c in (QtCore.QPointF(17, 14), QtCore.QPointF(17, 36), QtCore.QPointF(33, 14)):
            p.drawEllipse(c, 3.2, 3.2)
        p.setBrush(QtCore.Qt.NoBrush)
    p.end()
    return QtGui.QIcon(px)


class ToolCard(ui.Card):
    """A tile that opens a tool (or explains why it can't).

    Fixed height by design. Cards in a grid that size to their own text make
    each row as tall as its tallest card and leave the others with a gap under
    the button, which reads as a rendering fault rather than as a layout. The
    summary line is one sentence and elided if it somehow is not; the full text
    is the tooltip.
    """

    # Measured, not guessed: 18+18 margins, a 30px title row, two 17px
    # description lines, a 32px button and three 8px gaps = 156. Anything more
    # reintroduces the dead band under the description that the fixed-row
    # version had.
    CARD_HEIGHT = 156

    def __init__(self, title, icon_name, summary, detail, on_click, error=None):
        super().__init__()
        self._icon_name = icon_name
        self._on_click = on_click if (on_click and error is None) else None
        self._error = error
        self._summary = summary
        self.setFixedHeight(self.CARD_HEIGHT)
        if self._on_click is None:
            self.setCursor(QtCore.Qt.ArrowCursor)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(ui.SPACE_LG, ui.SPACE_LG, ui.SPACE_LG, ui.SPACE_LG)
        lay.setSpacing(ui.SPACE_SM)

        head = QtWidgets.QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(ui.SPACE_MD)
        self.glyph = QtWidgets.QLabel()
        self.glyph.setFixedSize(30, 30)
        self.glyph.setAlignment(QtCore.Qt.AlignCenter)
        head.addWidget(self.glyph, 0, QtCore.Qt.AlignTop)

        titles = QtWidgets.QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(2)
        t = QtWidgets.QLabel(title)
        t.setObjectName("card_title")
        titles.addWidget(t)
        self.running_chip = ui.Chip("OPEN")
        self.running_chip.setVisible(False)
        titles.addWidget(self.running_chip, 0, QtCore.Qt.AlignLeft)
        head.addLayout(titles, 1)
        lay.addLayout(head)

        if error is not None:
            summary = (f"Unavailable - missing dependencies ({error}). "
                       "Run install.bat to add them.")
            detail = summary
        self.desc = QtWidgets.QLabel(summary)
        self.desc.setObjectName("card_desc")
        self.desc.setWordWrap(True)
        self.desc.setAlignment(QtCore.Qt.AlignTop)
        lay.addWidget(self.desc, 1)
        self.setToolTip(detail)

        self.open_btn = QtWidgets.QPushButton("Open" if error is None else "Unavailable")
        self.open_btn.setObjectName("primary")
        self.open_btn.setEnabled(error is None)
        self.open_btn.setMinimumHeight(ui.FIELD_HEIGHT)
        if self._on_click:
            self.open_btn.setCursor(QtCore.Qt.PointingHandCursor)
            self.open_btn.clicked.connect(self._on_click)
        lay.addWidget(self.open_btn)

        self.retint()

    def set_unavailable(self, error) -> None:
        """Mark the tool as unopenable, with the reason.

        Applied after construction rather than passed in, because availability
        is now discovered by the deferred probe rather than at import time.
        """
        self._error = error
        self._on_click = None
        self.setCursor(QtCore.Qt.ArrowCursor)
        text = (f"Unavailable - missing dependencies ({error}). "
                "Run install.bat to add them.")
        self.desc.setText(text)
        self.setToolTip(text)
        self.open_btn.setText("Unavailable")
        self.open_btn.setEnabled(False)
        self.retint()

    def set_running(self, running: bool) -> None:
        self.running_chip.setVisible(running)
        if self._error is None:
            self.open_btn.setText("Bring to front" if running else "Open")

    def retint(self) -> None:
        """Repaint the tool mark for the current theme.

        A QLabel pixmap is baked at the colour it was drawn with, so without
        this the card glyphs keep the previous theme's tint through a live
        light/dark switch while everything around them changes.
        """
        token = "BTN_DIS_TEXT" if self._error is not None else "ACCENT"
        self.glyph.setPixmap(ui.pixmap(self._icon_name, 26, theme.palette_color(token)))

    def mouseReleaseEvent(self, e):
        # Clicking anywhere on the card opens it too (when it's available).
        if self._on_click and e.button() == QtCore.Qt.LeftButton:
            self._on_click()
        QtWidgets.QFrame.mouseReleaseEvent(self, e)


class Launcher(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chaser's Shenanigans")
        # Sized for two rows of three at the default width. The grid reflows, so
        # this is a starting point rather than a constraint.
        self.resize(1040, 620)
        self.setMinimumSize(420, 420)
        _ic = icon_path()
        if _ic:
            self.setWindowIcon(QtGui.QIcon(_ic))
        # Keep references so opened tool windows are not garbage-collected.
        self._windows = []
        self._open_by_tool = {}                # title -> live window
        self._cards = {}                       # title -> ToolCard

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        # The grid scrolls. At the minimum window size two rows of one card do
        # not fit, and a launcher that clips its last tool with no scrollbar is
        # worse than one that scrolls.
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        body = QtWidgets.QWidget()
        body_lay = QtWidgets.QVBoxLayout(body)
        body_lay.setContentsMargins(ui.SPACE_XL, ui.SPACE_LG, ui.SPACE_XL, ui.SPACE_LG)
        body_lay.setSpacing(ui.SPACE_MD)

        self.grid = ui.FlowGrid(min_item_width=290)
        for title_, icon_name, summary, detail, module in TOOLS:
            card = ToolCard(title_, icon_name, summary, detail,
                            self._make_opener(title_, module))
            self._cards[title_] = card
            self.grid.add_item(card)
        body_lay.addWidget(self.grid)
        # The stretch lives here, under the grid, so the cards keep their own
        # height instead of absorbing the window's.
        body_lay.addStretch(1)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        root.addWidget(self._build_footer())

        ensure_applied()
        self._refresh_glyphs()
        # Probe tool availability AFTER the window is up, not at module import.
        #
        # The launcher used to import all five tool modules at import time to
        # find out which ones their dependencies supported. Two of them pull
        # numpy at module level, which drags in scipy, scikit-image, astropy,
        # rawpy and tifffile: measured at 783ms for stacker_gui and 765ms for
        # quickedit_gui, against 74/31/22ms for the other three. That is ~840ms
        # of the launcher's startup spent importing array libraries to render a
        # page of cards.
        #
        # Deferring it is the pattern this codebase already uses for the GitHub
        # update check. A card clicked before the probe lands imports its own
        # module synchronously and reports the failure itself, so nothing races.
        #
        # One tool per tick, not all five in one callback: importing
        # stacker_gui alone blocks for ~780ms, and a single callback doing all
        # of them holds the event loop for the best part of a second before the
        # window has painted - which is the stall this change exists to remove,
        # just moved. The first tick is delayed a frame so the paint goes first.
        self._probe_queue = [(t[0], t[4]) for t in TOOLS]
        QtCore.QTimer.singleShot(16, self._probe_next_tool)

    def _probe_next_tool(self):
        """Import one tool and disable its card if it cannot load, then queue
        the next. Idempotent with `_make_opener`: `_load_tool` caches, so a card
        clicked before its turn comes up is imported once, not twice."""
        if not self._probe_queue:
            return
        title_, module = self._probe_queue.pop(0)
        _cls, err = _load_tool(module)
        card = self._cards.get(title_)
        if card is not None and err is not None:
            card.set_unavailable(err)
        if self._probe_queue:
            QtCore.QTimer.singleShot(0, self._probe_next_tool)

    # ---------------------------------------------------------------- chrome
    def _build_header(self) -> QtWidgets.QWidget:
        bar = QtWidgets.QWidget()
        bar.setObjectName("toolbar")
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(ui.SPACE_XL, ui.SPACE_LG, ui.SPACE_XL, ui.SPACE_LG)
        lay.setSpacing(ui.SPACE_MD)

        mark = QtWidgets.QLabel()
        _ic = icon_path()
        if _ic:
            mark.setPixmap(QtGui.QIcon(_ic).pixmap(34, 34))
        mark.setFixedSize(34, 34)
        lay.addWidget(mark)

        titles = QtWidgets.QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(1)
        title = QtWidgets.QLabel("Chaser's Shenanigans")
        title.setObjectName("title")
        titles.addWidget(title)
        sub = QtWidgets.QLabel("A small suite of photo utilities")
        sub.setObjectName("subtitle")
        titles.addWidget(sub)
        lay.addLayout(titles)
        lay.addStretch(1)

        # Theme toggle: moon while dark mode is on, sun while light mode is on.
        # A fresh install follows the Windows theme ("system" in theme.py);
        # the first click pins an explicit light/dark choice.
        self.theme_btn = ui.icon_button("moon", "", 32)
        self.theme_btn.clicked.connect(self._toggle_theme)
        lay.addWidget(self.theme_btn)
        return bar

    def _build_footer(self) -> QtWidgets.QWidget:
        bar = QtWidgets.QWidget()
        bar.setObjectName("statusbar")
        footer = QtWidgets.QHBoxLayout(bar)
        footer.setContentsMargins(ui.SPACE_XL, ui.SPACE_MD, ui.SPACE_XL, ui.SPACE_MD)
        footer.setSpacing(ui.SPACE_SM)

        self._glyph_buttons = []       # (button, kind) - recoloured on theme change

        ver = QtWidgets.QPushButton(f"v{__version__}")
        ver.setObjectName("linkbtn")
        ver.setCursor(QtCore.Qt.PointingHandCursor)
        ver.setToolTip("Show the exact commit this copy is synced to")
        ver.clicked.connect(self._show_commit)
        footer.addWidget(ver)

        upd = QtWidgets.QPushButton("  Check for updates")
        upd.setObjectName("linkbtn")
        upd.setCursor(QtCore.Qt.PointingHandCursor)
        upd.setIconSize(QtCore.QSize(16, 16))
        upd.setProperty("iconName", "download")
        upd.clicked.connect(self._check_updates)
        self._update_btn = upd
        footer.addWidget(upd)
        footer.addStretch(1)

        for label, kind, url in LINKS:
            footer.addWidget(self._make_link_button(label, kind, url))
        return bar

    # ------------------------------------------------------------- behaviour
    def _toggle_theme(self):
        # Two-state toggle: flip whatever is currently resolved (which on a
        # fresh install is the Windows theme) and pin it as an explicit choice.
        set_mode("light" if resolved_mode() == "dark" else "dark")
        self._refresh_glyphs()   # PaletteChange refreshes too; this avoids any lag

    def _refresh_glyphs(self):
        """Redraw every painted glyph in a colour that reads on the current theme.

        `ui.retint_tree` handles anything exposing a `retint()` or an
        `iconName` property - the cards, the update button, the empty states.
        The three link marks are drawn here because they carry a fixed accent
        (the Ko-fi heart) that the generic tinting would flatten.
        """
        ui._icon_cache.clear()
        color = theme.palette_color("GLYPH")
        for btn, kind in self._glyph_buttons:
            btn.setIcon(_link_icon(kind, color))
        dark = resolved_mode() == "dark"
        self.theme_btn.setIcon(ui.icon("moon" if dark else "sun", 16, color))
        self.theme_btn.setToolTip("Dark mode is on - click for light mode." if dark
                                  else "Light mode is on - click for dark mode.")
        self._update_btn.setIcon(ui.icon("download", 16, color))
        for card in self._cards.values():
            card.retint()

    def changeEvent(self, e):
        # Covers Windows flipping its theme while we're in "system" mode.
        if e.type() in (QtCore.QEvent.PaletteChange, QtCore.QEvent.StyleChange):
            if hasattr(self, "_glyph_buttons"):
                self._refresh_glyphs()
        super().changeEvent(e)

    def _show_commit(self):
        # Reveal the exact build: the commit this copy is synced to (from the
        # updater's local marker). None until the first sync/update has run.
        sha = current_sha()
        if sha:
            body = (f"Version v{__version__}\n"
                    f"Commit {sha[:7]}\n\n"
                    f"Full commit: {sha}")
        else:
            body = (f"Version v{__version__}\n\n"
                    "No commit recorded yet - this copy hasn't synced with GitHub. "
                    "Use “Check for updates” to record it.")
        QtWidgets.QMessageBox.information(self, "Version", body)

    def _check_updates(self):
        # Manual check: parented to this window, and interactive so it always
        # gives an answer (including "you're up to date").
        run_update_check(self, interactive=True)

    def _make_link_button(self, label, kind, url):
        btn = QtWidgets.QPushButton(f"  {label}")
        btn.setObjectName("kofi" if kind == "kofi" else "linkbtn")
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        btn.setIcon(_link_icon(kind))
        btn.setIconSize(QtCore.QSize(16, 16))
        self._glyph_buttons.append((btn, kind))
        btn.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl(url)))
        return btn

    def _make_opener(self, title, module):
        def open_tool():
            window_cls, err = _load_tool(module)
            if window_cls is None:
                card = self._cards.get(title)
                if card is not None:
                    card.set_unavailable(err)
                QtWidgets.QMessageBox.warning(
                    self, title,
                    f"{title} can't start - a dependency is missing:\n\n{err}\n\n"
                    "Run install.bat to add it.")
                return
            # Raise the existing window rather than opening a second copy. Two
            # windows of the same tool with no visual difference between them is
            # a reliable way to edit in the wrong one.
            live = self._open_by_tool.get(title)
            if live is not None and not live.isHidden():
                live.showNormal()
                live.raise_()
                live.activateWindow()
                return
            win = window_cls()
            win.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
            # Drop the reference when the window closes so it can be freed.
            win.destroyed.connect(lambda *_: self._forget(title, win))
            win.installEventFilter(self)
            self._windows.append(win)
            self._open_by_tool[title] = win
            self._mark_running(title, True)
            win.show()
            win.raise_()
            win.activateWindow()
        return open_tool

    def eventFilter(self, obj, event):
        # A tool window that is closed rather than destroyed still has to clear
        # its card's "open" chip, or the launcher offers to bring a dead window
        # to the front.
        if event.type() == QtCore.QEvent.Close:
            for title, win in list(self._open_by_tool.items()):
                if win is obj:
                    self._forget(title, win)
        return super().eventFilter(obj, event)

    def _mark_running(self, title, running):
        card = self._cards.get(title)
        if card is None:
            return
        try:
            card.set_running(running)
        except RuntimeError:
            # The card's C++ side is already gone. This happens on shutdown: the
            # launcher is destroyed first, taking its cards with it, and the tool
            # windows' `destroyed` signals then fire into `_forget` and reach a
            # deleted Chip. Qt gives no "is this still alive" query from Python,
            # so the ownership question is answered by catching the failure -
            # and there is nothing to update on a card that no longer exists.
            self._cards.pop(title, None)

    def _forget(self, title, win):
        self._open_by_tool.pop(title, None)
        self._mark_running(title, False)
        try:
            self._windows.remove(win)
        except ValueError:
            pass


    def closeEvent(self, e):
        # Closing the launcher closes the suite, so drop the hooks into the tool
        # windows first: their destruction would otherwise call back into cards
        # that are being torn down alongside this window.
        for win in list(self._windows):
            try:
                win.destroyed.disconnect()
                win.removeEventFilter(self)
            except (RuntimeError, TypeError):
                pass
        self._cards.clear()
        self._open_by_tool.clear()
        super().closeEvent(e)


def main():
    # Must come first: ProcessPoolExecutor under PyInstaller/spawn (PhotoBorder).
    from multiprocessing import freeze_support
    freeze_support()
    set_app_user_model_id()  # correct taskbar icon/grouping on Windows
    app = QtWidgets.QApplication(sys.argv)
    _ic = icon_path()
    if _ic:
        app.setWindowIcon(QtGui.QIcon(_ic))
    # Check GitHub for a newer version before showing the UI. Self-disables on
    # any error (offline, etc.) and may restart the app if an update is applied.
    run_update_check()
    win = Launcher()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
