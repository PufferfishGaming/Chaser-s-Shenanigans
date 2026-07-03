"""
Chaser's Shenanigans - suite launcher (PySide6).

A small home window with three cards. Each card opens its tool as a separate
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
"""
import sys
import logging

from PySide6 import QtCore, QtGui, QtWidgets

from theme import ensure_applied, resolved_mode, set_mode, icon_path, set_app_user_model_id
from updater import run_update_check, current_sha

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _load_tool(module_name):
    """Import a tool's MainWindow, returning (class, None) or (None, error).

    A tool whose dependencies are missing (e.g. the Astro Stacker without numpy)
    must NOT take down the whole launcher — its card is disabled instead, and the
    other tools plus the updater keep working.
    """
    try:
        mod = __import__(module_name, fromlist=["MainWindow"])
        return mod.MainWindow, None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tool '%s' unavailable: %s", module_name, exc)
        return None, exc


_PhotoBorder, _err_pb = _load_tool("photoborder_gui")
_Converter, _err_cv = _load_tool("converter_gui")
_Metadata, _err_md = _load_tool("metadata_gui")
_Stacker, _err_st = _load_tool("stacker_gui")
_QuickEdit, _err_qe = _load_tool("quickedit_gui")

# Displayed bottom-left in the launcher. Bump this and push to main to test the
# auto-updater — the bump is a new commit, so copies will pull it and the number
# they show will change. (The updater compares commit SHAs, not this string.)
__version__ = "3.4"


# (title, description, window class or None, import error or None)
TOOLS = [
    ("PhotoBorder", "Add borders, EXIF strips and colour palettes. Batch a whole "
                    "folder in parallel with a live preview.", _PhotoBorder, _err_pb),
    ("Format Converter", "Convert images between JPEG, PNG, WEBP, TIFF, BMP and "
                         "HEIF/HEIC/HIF — keeping EXIF where the format allows.", _Converter, _err_cv),
    ("Metadata Baker", "Copy EXIF from one image into another (e.g. restore camera "
                       "metadata onto an export), edit fields, or browse and edit "
                       "every raw EXIF tag.",
     _Metadata, _err_md),
    ("Astro Stacker", "Stack a night-sky sequence into sharp stars (aligned) or "
                      "star trails. RAW in; TIFF / FITS out.", _Stacker, _err_st),
    ("Quick Edit", "Film simulations, white balance, light-pollution gradient "
                   "removal and one-click looks, live preview. RAW in, 8/16-bit out.", _QuickEdit, _err_qe),
]


# External links shown as a footer row in the launcher. (label, glyph, url).
# Glyphs are drawn at runtime by _link_icon() — original, generic marks rather
# than the brands' trademarked logos.
LINKS = [
    ("Support on Ko-fi", "kofi", "https://ko-fi.com/pufferfishgaming"),
    ("Instagram", "instagram", "https://www.instagram.com/stormchaserphotography/"),
    ("GitHub", "github", "https://github.com/PufferfishGaming/Chaser-s-Shenanigans"),
]


def _link_icon(kind: str, color: str = "#c8cad0", accent: str = "#ff6b52") -> QtGui.QIcon:
    """Draw a small, original glyph for a footer link and return it as a QIcon.

    Generic marks (coffee cup / camera / git-branch), not the brand logos.
    Painted on a transparent 48px canvas so they stay crisp when Qt scales them.
    """
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
        # Coffee cup: body, handle, steam — with a small accent heart.
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

    elif kind == "update":
        # Download-into-tray: clearly "fetch the update".
        p.drawLine(QtCore.QPointF(24, 11), QtCore.QPointF(24, 27))   # shaft
        p.drawLine(QtCore.QPointF(24, 27), QtCore.QPointF(18, 21))   # left barb
        p.drawLine(QtCore.QPointF(24, 27), QtCore.QPointF(30, 21))   # right barb
        p.drawLine(QtCore.QPointF(15, 32), QtCore.QPointF(33, 32))   # tray base
        p.drawLine(QtCore.QPointF(15, 32), QtCore.QPointF(15, 28))   # left riser
        p.drawLine(QtCore.QPointF(33, 32), QtCore.QPointF(33, 28))   # right riser

    elif kind == "sun":
        # Sun: disc + 8 rays. Shown on the theme toggle while light mode is on.
        p.drawEllipse(QtCore.QPointF(24, 24), 6.5, 6.5)
        import math
        for i in range(8):
            a = math.radians(i * 45)
            p.drawLine(QtCore.QPointF(24 + 10.5 * math.cos(a), 24 + 10.5 * math.sin(a)),
                       QtCore.QPointF(24 + 14.5 * math.cos(a), 24 + 14.5 * math.sin(a)))

    elif kind == "moon":
        # Crescent moon: a disc minus an offset disc. Shown while dark mode is on.
        disc = QtGui.QPainterPath()
        disc.addEllipse(QtCore.QPointF(23, 25), 10.0, 10.0)
        bite = QtGui.QPainterPath()
        bite.addEllipse(QtCore.QPointF(29, 20), 9.0, 9.0)
        p.drawPath(disc.subtracted(bite))

    p.end()
    return QtGui.QIcon(px)


class Card(QtWidgets.QFrame):
    """A clickable tile that opens a tool (or shows why it's unavailable)."""
    def __init__(self, title, desc, on_click, error=None):
        super().__init__()
        self.setObjectName("card")
        self._on_click = on_click if (on_click and error is None) else None
        if self._on_click:
            self.setCursor(QtCore.Qt.PointingHandCursor)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)
        t = QtWidgets.QLabel(title)
        t.setObjectName("card_title")
        if error is not None:
            desc = (desc + f"\n\nUnavailable — missing dependencies ({error}). "
                    "Run install.bat to add them.")
        d = QtWidgets.QLabel(desc)
        d.setObjectName("card_desc")
        d.setWordWrap(True)
        d.setAlignment(QtCore.Qt.AlignTop)
        lay.addWidget(t)
        lay.addWidget(d)
        lay.addStretch(1)
        open_btn = QtWidgets.QPushButton("Open" if error is None else "Unavailable")
        open_btn.setObjectName("primary")
        open_btn.setEnabled(error is None)
        if self._on_click:
            open_btn.clicked.connect(self._on_click)
        lay.addWidget(open_btn)

    def mouseReleaseEvent(self, e):
        # Clicking anywhere on the card opens it too (when it's available).
        if self._on_click and e.button() == QtCore.Qt.LeftButton:
            self._on_click()
        super().mouseReleaseEvent(e)


class Launcher(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chaser's Shenanigans")
        self.resize(1180, 380)
        _ic = icon_path()
        if _ic:
            self.setWindowIcon(QtGui.QIcon(_ic))
        # Keep references so opened tool windows are not garbage-collected.
        self._windows = []

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        title = QtWidgets.QLabel("Chaser's Shenanigans")
        title.setObjectName("title")
        root.addWidget(title)
        sub = QtWidgets.QLabel("A small suite of photo utilities")
        sub.setObjectName("subtitle")
        root.addWidget(sub)

        cards = QtWidgets.QHBoxLayout()
        cards.setSpacing(16)
        for title_, desc_, cls, err in TOOLS:
            opener = self._make_opener(cls) if cls else None
            cards.addWidget(Card(title_, desc_, opener, error=err))
        root.addLayout(cards, 1)

        # Footer: version + update check bottom-left, links bottom-right.
        self._glyph_buttons = []               # (button, kind) - recoloured on theme change
        footer = QtWidgets.QHBoxLayout()
        footer.setSpacing(10)
        ver = QtWidgets.QPushButton(f"v{__version__}")
        ver.setObjectName("linkbtn")           # same bordered style/size as the buttons
        ver.setCursor(QtCore.Qt.PointingHandCursor)
        ver.clicked.connect(self._show_commit)
        footer.addWidget(ver, 0, QtCore.Qt.AlignBottom)
        upd = QtWidgets.QPushButton("  Check for updates")
        upd.setObjectName("linkbtn")
        upd.setCursor(QtCore.Qt.PointingHandCursor)
        upd.setIcon(_link_icon("update"))
        upd.setIconSize(QtCore.QSize(18, 18))
        upd.clicked.connect(self._check_updates)
        self._glyph_buttons.append((upd, "update"))
        footer.addWidget(upd, 0, QtCore.Qt.AlignBottom)

        # Theme toggle: moon while dark mode is on, sun while light mode is on.
        # A fresh install follows the Windows theme ("system" in theme.py);
        # the first click pins an explicit light/dark choice.
        self.theme_btn = QtWidgets.QPushButton()
        self.theme_btn.setObjectName("linkbtn")
        self.theme_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.theme_btn.setIconSize(QtCore.QSize(18, 18))
        self.theme_btn.clicked.connect(self._toggle_theme)
        footer.addWidget(self.theme_btn, 0, QtCore.Qt.AlignBottom)
        footer.addStretch(1)
        for label, kind, url in LINKS:
            footer.addWidget(self._make_link_button(label, kind, url))
        root.addLayout(footer)

        ensure_applied()
        self._refresh_glyphs()

    def _toggle_theme(self):
        # Two-state toggle: flip whatever is currently resolved (which on a
        # fresh install is the Windows theme) and pin it as an explicit choice.
        set_mode("light" if resolved_mode() == "dark" else "dark")
        self._refresh_glyphs()   # PaletteChange refreshes too; this avoids any lag

    def _refresh_glyphs(self):
        """Redraw the footer glyphs in a colour that reads on the current theme,
        and point the theme toggle's icon at the active mode (moon = dark)."""
        color = "#c8cad0" if resolved_mode() == "dark" else "#5a5d66"
        for btn, kind in self._glyph_buttons:
            btn.setIcon(_link_icon(kind, color))
        dark = resolved_mode() == "dark"
        self.theme_btn.setIcon(_link_icon("moon" if dark else "sun", color))
        self.theme_btn.setToolTip("Dark mode is on — click for light mode." if dark
                                  else "Light mode is on — click for dark mode.")

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
                    "No commit recorded yet — this copy hasn't synced with GitHub. "
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
        btn.setIconSize(QtCore.QSize(18, 18))
        self._glyph_buttons.append((btn, kind))
        btn.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl(url)))
        return btn

    def _make_opener(self, window_cls):
        def open_tool():
            win = window_cls()
            # Drop the reference when the window closes so it can be freed.
            win.destroyed.connect(lambda *_: self._forget(win))
            self._windows.append(win)
            win.show()
            win.raise_()
            win.activateWindow()
        return open_tool

    def _forget(self, win):
        try:
            self._windows.remove(win)
        except ValueError:
            pass


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
