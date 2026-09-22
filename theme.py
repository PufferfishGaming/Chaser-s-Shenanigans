"""
Shared look & feel for the whole suite, with light/dark support.

Three theme modes:
  * "system" (default) - follows Windows light/dark mode, live: if Windows
    switches while the suite is open, the suite follows.
  * "light" / "dark"   - forced, remembered across sessions (QSettings).

How theming works here
----------------------
Styling is applied at the *QApplication* level (stylesheet + palette), never
per-window. All tools share one QApplication (see launcher.py), so a mode
switch in the launcher restyles every open tool window live. The palette
matters as much as the QSS: scrollbars, combo popups, menus and message boxes
follow the palette, so forcing dark on a light-mode Windows (or vice versa)
would leave mismatched native chrome without it.

The stylesheet is one template with @TOKEN@ placeholders and two colour sets.
If you add a rule, use tokens - a hardcoded colour will look right in one mode
and wrong in the other. Code-side state colours (e.g. the tag browser's
modified/deleted rows) come from state_color() for the same reason.

Sub-controls must be styled or Qt draws them natively
-----------------------------------------------------
This is the trap that produced the suite's most visible cosmetic bug. Applying
ANY stylesheet property to a widget switches it to QStyleSheetStyle, but each
*sub-control* you do not style is still drawn by the platform style. QSlider
and QCheckBox carried a field-like `background`/`border` rule and no
`::groove`, `::handle` or `::indicator`, so the Windows style painted its own
groove fill and check mark inside our frame - in its own olive/khaki highlight
colour, which matched neither the blue accent nor either theme. It rendered as
a solid yellow bar across every quality slider and a yellow tick in every
checkbox.

So: every sub-control of every styled widget is covered below. If you style a
new widget class, style its sub-controls in the same change or the platform
will fill the gap for you.

Glyphs are generated, not shipped
---------------------------------
Check marks, chevrons and arrows are drawn with QPainter into small PNGs in the
user's cache directory and referenced from the QSS by path (see `_glyphs`).
Two reasons this beats the alternatives: Qt's QSS has no `transform`, so the
usual pure-CSS check mark (a rotated L) is not expressible, and the CSS
zero-size-plus-borders triangle renders as a grey block rather than an arrow in
Qt. Generating them also means they are tinted per theme rather than being one
colour that is wrong in one mode.

The cache is keyed by mode and colour, so a theme switch regenerates only what
changed, and a failure to write falls back to un-imaged sub-controls rather
than crashing - the app must survive a read-only or full cache directory.
"""
import os
import sys

# ---------------------------------------------------------------- app identity


def icon_path():
    """Absolute path to icon.ico, or None if it isn't present.

    Handles PyInstaller's bundle dir (sys._MEIPASS) so the packaged .exe finds
    it too.
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(base, "icon.ico")
    return p if os.path.exists(p) else None


def set_app_user_model_id(appid: str = "ChasersShenanigans.Suite") -> None:
    """Tell Windows this process is its own app, not 'pythonw'.

    Without an explicit AppUserModelID, a pythonw-hosted GUI is grouped under
    Python's generic taskbar icon. Setting one (before any window is shown) makes
    the taskbar use OUR window icon and group the windows under this app. No-op
    off Windows; failures are swallowed (it's cosmetic, never correctness).
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(appid)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- colour sets
#
# Photography-forward: the chrome is a deep, desaturated neutral so that the
# thing on screen with the most contrast is the photograph. PREVIEW_BG is the
# darkest surface in the dark set and the most neutral in the light set for
# exactly that reason - a preview area lighter than the panel around it makes
# every image look flat, and a tinted one shifts the apparent white balance of
# whatever is being judged against it.
#
# The greys are very slightly blue (hue ~225) rather than pure neutral. Pure
# #101010 greys read as "switched off" next to a photograph; a few points of
# blue reads as considered. The accent stays blue - it is the suite's identity -
# but is lifted from #3b6ea5 to #4c8dd9, because the old accent was only 2.9:1
# against the new darker surfaces and disappeared into them.

_DARK = {
    # surfaces, darkest to lightest
    "PREVIEW_BG": "#090a0c",  "WINDOW_BG": "#0e0f13",  "PANEL_BG": "#14161a",
    "SURFACE": "#1a1d22",     "SURFACE_HI": "#21242b", "FIELD_BG": "#101115",
    "PATH_BG": "#101115",     "LOG_BG": "#0d0e11",     "EDITOR_BG": "#0b0c0f",
    "TREE_ALT": "#17191e",    "CARD_HOVER_BG": "#1c1f26",
    "OVERLAY": "#0b0c0f",
    # lines
    "BORDER": "#23262d",      "BORDER_STRONG": "#32363f", "BTN_BORDER": "#31353e",
    "DIVIDER": "#282c34",
    # type
    "TEXT": "#e4e6ea",        "TITLE": "#f4f5f7",      "MUTED": "#8b909b",
    "SECTION": "#6d727d",     "PATH_TEXT": "#b4b8c2",  "PLACEHOLDER": "#5f636d",
    "LOG_TEXT": "#93a3a3",    "HINT": "#d0a469",       "ERROR": "#e08b8b",
    # accent
    "ACCENT": "#4c8dd9",      "ACCENT_HOVER": "#5f9ce5", "ACCENT_PRESS": "#3f7cc4",
    "ACCENT_SOFT": "#1b2a3d", "ACCENT_TEXT": "#ffffff",  "FOCUS_RING": "#4c8dd9",
    # controls
    "BTN_BG": "#23262d",      "BTN_HOVER": "#2b2f37",  "BTN_PRESS": "#191c21",
    "BTN_DIS_BG": "#15171b",  "BTN_DIS_TEXT": "#4e535c", "BTN_DIS_BORDER": "#1f2228",
    "TRACK": "#272b33",       "THUMB": "#3a3f49",      "THUMB_HOVER": "#4a505c",
    "TREE_SEL": "#24405e",
    # link / ko-fi chrome
    "LINK_TEXT": "#b4b8c2",   "LINK_HOVER_BG": "#1c1f26", "LINK_HOVER_TEXT": "#e4e6ea",
    "KOFI_BORDER": "#6e463f", "KOFI_TEXT": "#e9b9ac",  "KOFI_HOVER_BG": "#2a211f",
    "KOFI_HOVER_TEXT": "#ffd9cc", "KOFI_HOVER_BORDER": "#ff6b52",
    # glyph tints
    "GLYPH": "#c6cad2",       "GLYPH_MUTED": "#6d727d", "GLYPH_ON_ACCENT": "#ffffff",
}

_LIGHT = {
    "PREVIEW_BG": "#d9dbe0",  "WINDOW_BG": "#f6f7f9",  "PANEL_BG": "#eff1f4",
    "SURFACE": "#ffffff",     "SURFACE_HI": "#f7f8fa", "FIELD_BG": "#ffffff",
    "PATH_BG": "#e8eaee",     "LOG_BG": "#f2f4f6",     "EDITOR_BG": "#ffffff",
    "TREE_ALT": "#f4f5f8",    "CARD_HOVER_BG": "#eef3fa",
    "OVERLAY": "#ffffff",
    "BORDER": "#d3d6dd",      "BORDER_STRONG": "#b9bdc7", "BTN_BORDER": "#c6cad2",
    "DIVIDER": "#e2e5ea",
    "TEXT": "#22242a",        "TITLE": "#14161a",      "MUTED": "#666b76",
    "SECTION": "#767b86",     "PATH_TEXT": "#464a53",  "PLACEHOLDER": "#969ba5",
    "LOG_TEXT": "#4e5f5f",    "HINT": "#8f6520",       "ERROR": "#b04a4a",
    "ACCENT": "#2f6fb8",      "ACCENT_HOVER": "#3a80cc", "ACCENT_PRESS": "#275f9f",
    "ACCENT_SOFT": "#e2edfa", "ACCENT_TEXT": "#ffffff",  "FOCUS_RING": "#2f6fb8",
    "BTN_BG": "#e7e9ed",      "BTN_HOVER": "#dcdfe5",  "BTN_PRESS": "#cdd1d9",
    "BTN_DIS_BG": "#eef0f3",  "BTN_DIS_TEXT": "#a5a9b2", "BTN_DIS_BORDER": "#e0e3e8",
    "TRACK": "#d5d8df",       "THUMB": "#b4b9c3",      "THUMB_HOVER": "#9aa0ac",
    "TREE_SEL": "#cfe0f5",
    "LINK_TEXT": "#565a63",   "LINK_HOVER_BG": "#eaeff7", "LINK_HOVER_TEXT": "#22242a",
    "KOFI_BORDER": "#d0977e", "KOFI_TEXT": "#a8543c",  "KOFI_HOVER_BG": "#faeee9",
    "KOFI_HOVER_TEXT": "#8c3b24", "KOFI_HOVER_BORDER": "#ff6b52",
    "GLYPH": "#4a4e57",       "GLYPH_MUTED": "#767b86", "GLYPH_ON_ACCENT": "#ffffff",
}

# Code-side row/state colours (used by widgets that colour items directly,
# e.g. the Metadata tag browser). Kept here so both modes stay readable.
_STATE = {
    "dark":  {"modified": "#7ee787", "deleted": "#f28b82", "viewonly": "#8b8d93",
              "accent": "#4c8dd9", "warn": "#d0a469"},
    "light": {"modified": "#1a7f37", "deleted": "#b3261e", "viewonly": "#8b8d93",
              "accent": "#2f6fb8", "warn": "#8f6520"},
}


# ------------------------------------------------------------------- glyph PNGs

def _cache_dir():
    """Writable directory for the generated glyph PNGs, or None.

    QStandardPaths rather than the install directory: the install directory is
    user-writable by design (the updater overlays into it) but it is also what
    `_overlay_tree()` walks, and generated files there would be shipped around
    by nothing and cleaned by nothing. A cache directory is the right home and
    is safe to lose at any moment.
    """
    try:
        from PySide6 import QtCore
        base = QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.CacheLocation)
        if not base:
            return None
        d = os.path.join(base, "glyphs")
        os.makedirs(d, exist_ok=True)
        return d
    except Exception:  # noqa: BLE001
        return None


# Rendered at 3x the on-screen size and scaled down by the QSS `width`/`height`,
# so the glyphs stay crisp on a 150%/200% display without shipping @2x assets.
_GLYPH_SCALE = 3


def _draw_glyph(kind: str, size: int, color: str):
    """Return a QPixmap of one UI glyph, drawn at _GLYPH_SCALE resolution.

    Deliberately geometric and drawn from primitives - no font glyphs. A font
    dependency here would mean the check mark changes shape with the system
    font, and the suite already ships with a "boxes in some fonts" story it does
    not need a second of.
    """
    from PySide6 import QtCore, QtGui
    s = size * _GLYPH_SCALE
    pm = QtGui.QPixmap(s, s)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    col = QtGui.QColor(color)
    pen = QtGui.QPen(col, max(1.6, s * 0.115))
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    p.setPen(pen)

    if kind == "check":
        path = QtGui.QPainterPath()
        path.moveTo(s * 0.22, s * 0.52)
        path.lineTo(s * 0.42, s * 0.72)
        path.lineTo(s * 0.79, s * 0.28)
        p.drawPath(path)
    elif kind == "dash":                       # tri-state / partial
        p.drawLine(QtCore.QPointF(s * 0.24, s * 0.5), QtCore.QPointF(s * 0.76, s * 0.5))
    elif kind == "dot":                        # radio button centre
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(QtCore.QRectF(s * 0.28, s * 0.28, s * 0.44, s * 0.44))
    elif kind in ("chevron_down", "chevron_up", "chevron_left", "chevron_right"):
        path = QtGui.QPainterPath()
        path.moveTo(s * 0.26, s * 0.40)
        path.lineTo(s * 0.50, s * 0.64)
        path.lineTo(s * 0.74, s * 0.40)
        p.save()
        p.translate(s / 2.0, s / 2.0)
        p.rotate({"chevron_down": 0, "chevron_up": 180,
                  "chevron_left": 90, "chevron_right": -90}[kind])
        p.translate(-s / 2.0, -s / 2.0)
        p.drawPath(path)
        p.restore()
    elif kind in ("caret_up", "caret_down"):   # spin box steppers - filled
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(col)
        tri = QtGui.QPolygonF()
        if kind == "caret_up":
            tri << QtCore.QPointF(s * 0.5, s * 0.34) \
                << QtCore.QPointF(s * 0.78, s * 0.66) \
                << QtCore.QPointF(s * 0.22, s * 0.66)
        else:
            tri << QtCore.QPointF(s * 0.5, s * 0.66) \
                << QtCore.QPointF(s * 0.78, s * 0.34) \
                << QtCore.QPointF(s * 0.22, s * 0.34)
        p.drawPolygon(tri)
    elif kind == "branch_closed":
        path = QtGui.QPainterPath()
        path.moveTo(s * 0.40, s * 0.26)
        path.lineTo(s * 0.64, s * 0.50)
        path.lineTo(s * 0.40, s * 0.74)
        p.drawPath(path)
    elif kind == "branch_open":
        path = QtGui.QPainterPath()
        path.moveTo(s * 0.26, s * 0.40)
        path.lineTo(s * 0.50, s * 0.64)
        path.lineTo(s * 0.74, s * 0.40)
        p.drawPath(path)
    p.end()
    return pm


# Cache of (kind, size, colour) -> written file path, so a theme switch only
# regenerates glyphs whose tint actually changed.
_glyph_files: dict = {}


def _gui_is_up() -> bool:
    """Whether a QGuiApplication exists yet.

    Constructing a QPixmap without one is not a Python exception - Qt calls
    qFatal and the process aborts, so `try/except` around the QPixmap does
    nothing. The only defence is not to make the call, which is what this is for.
    """
    try:
        from PySide6 import QtGui
        return QtGui.QGuiApplication.instance() is not None
    except Exception:  # noqa: BLE001
        return False


def _glyph(kind: str, size: int, color: str):
    """Path (forward-slashed, for QSS) to a glyph PNG, or None if unavailable."""
    key = (kind, size, color)
    hit = _glyph_files.get(key)
    if hit and os.path.exists(hit):
        return hit
    # A previously-written PNG is reusable without any GUI; drawing a new one is
    # not. Check the cache on disk before demanding a QGuiApplication.
    if not _gui_is_up():
        return None
    d = _cache_dir()
    if d is None:
        return None
    safe = color.lstrip("#")
    path = os.path.join(d, f"{kind}-{size}-{safe}.png")
    try:
        if not os.path.exists(path):
            _draw_glyph(kind, size, color).save(path, "PNG")
    except Exception:  # noqa: BLE001
        return None
    path = path.replace("\\", "/")
    _glyph_files[key] = path
    return path


def _glyph_tokens(colors: dict) -> dict:
    """@GLYPH_*@ tokens: a `url(...)` for each glyph, or an empty string.

    An empty string leaves `image:` with no value, which Qt parses as "no
    image" and skips - so a cache directory that cannot be written degrades to
    plain indicators rather than to a stack trace. Every rule below that uses
    one of these tokens is written so that it still looks deliberate without it.
    """
    want = {
        "GLYPH_CHECK":        ("check", 14, colors["GLYPH_ON_ACCENT"]),
        "GLYPH_CHECK_DIS":    ("check", 14, colors["BTN_DIS_TEXT"]),
        "GLYPH_DASH":         ("dash", 14, colors["GLYPH_ON_ACCENT"]),
        "GLYPH_DOT":          ("dot", 14, colors["GLYPH_ON_ACCENT"]),
        "GLYPH_CHEVRON":      ("chevron_down", 12, colors["GLYPH"]),
        "GLYPH_CHEVRON_DIS":  ("chevron_down", 12, colors["BTN_DIS_TEXT"]),
        "GLYPH_CARET_UP":     ("caret_up", 9, colors["GLYPH"]),
        "GLYPH_CARET_DOWN":   ("caret_down", 9, colors["GLYPH"]),
        "GLYPH_BRANCH_SHUT":  ("branch_closed", 12, colors["GLYPH_MUTED"]),
        "GLYPH_BRANCH_OPEN":  ("branch_open", 12, colors["GLYPH_MUTED"]),
        "GLYPH_ARROW_LEFT":   ("chevron_left", 12, colors["GLYPH"]),
        "GLYPH_ARROW_RIGHT":  ("chevron_right", 12, colors["GLYPH"]),
    }
    out = {}
    for token, (kind, size, color) in want.items():
        path = _glyph(kind, size, color)
        out[token] = f"url({path})" if path else ""
    return out


# -------------------------------------------------------------------- the QSS
#
# Ordering matters: generic widget rules first, then sub-controls, then
# object-name rules last. QSS has no !important and specificity ties are broken
# by source order, so an `#objectName` rule placed above a `QPushButton:hover`
# rule loses its background on hover - which is how the launcher's link buttons
# used to flash grey.

_TEMPLATE = """
/* ------------------------------------------------------------ base surfaces */
QMainWindow, QDialog { background: @WINDOW_BG@; }
QWidget { color: @TEXT@; font-family: 'Segoe UI', 'Helvetica Neue', sans-serif;
          font-size: 13px; }
QToolTip { background: @SURFACE@; color: @TEXT@; border: 1px solid @BORDER_STRONG@;
           border-radius: 6px; padding: 5px 8px; }

#panel { background: @PANEL_BG@; border-right: 1px solid @BORDER@; }
#panel_flat { background: @PANEL_BG@; }
#preview_area { background: @PREVIEW_BG@; }
#surface { background: @SURFACE@; border: 1px solid @BORDER@; border-radius: 10px; }
#toolbar { background: @PANEL_BG@; border-bottom: 1px solid @BORDER@; }
#statusbar { background: @PANEL_BG@; border-top: 1px solid @BORDER@; }
#divider { background: @DIVIDER@; border: none; }

/* ------------------------------------------------------------------ type */
#title { font-size: 21px; font-weight: 600; color: @TITLE@; }
#subtitle { color: @MUTED@; font-size: 12px; }
#hint { color: @HINT@; font-size: 11px; font-style: italic; }
#error { color: @ERROR@; font-size: 11px; }
#section { color: @SECTION@; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
#fieldlabel { color: @MUTED@; font-size: 12px; }
#value { color: @TEXT@; font-size: 12px; font-weight: 600; }
#pathlabel { color: @PATH_TEXT@; font-size: 11px; background: @PATH_BG@;
             border: 1px solid @BORDER@; border-radius: 6px; padding: 7px 9px; }
#empty_title { color: @MUTED@; font-size: 14px; font-weight: 600; }
#empty_body { color: @SECTION@; font-size: 12px; }

/* --------------------------------------------------------------- buttons */
QPushButton { background: @BTN_BG@; color: @TEXT@; border: 1px solid @BTN_BORDER@;
              border-radius: 7px; padding: 7px 12px; }
QPushButton:hover { background: @BTN_HOVER@; border-color: @BORDER_STRONG@; }
QPushButton:pressed { background: @BTN_PRESS@; }
QPushButton:focus { border: 1px solid @FOCUS_RING@; }
QPushButton:disabled { color: @BTN_DIS_TEXT@; background: @BTN_DIS_BG@;
                       border-color: @BTN_DIS_BORDER@; }

QPushButton#primary { background: @ACCENT@; border: 1px solid @ACCENT@;
                      color: @ACCENT_TEXT@; font-weight: 600; }
QPushButton#primary:hover { background: @ACCENT_HOVER@; border-color: @ACCENT_HOVER@; }
QPushButton#primary:pressed { background: @ACCENT_PRESS@; border-color: @ACCENT_PRESS@; }
QPushButton#primary:disabled { background: @BTN_DIS_BG@; border-color: @BTN_DIS_BORDER@;
                               color: @BTN_DIS_TEXT@; }

QPushButton#ghost { background: transparent; border: 1px solid transparent;
                    color: @MUTED@; }
QPushButton#ghost:hover { background: @SURFACE_HI@; color: @TEXT@; }
QPushButton#ghost:pressed { background: @BTN_PRESS@; }
QPushButton#ghost:disabled { color: @BTN_DIS_TEXT@; background: transparent; }

QPushButton#danger { background: transparent; border: 1px solid @ERROR@; color: @ERROR@; }
QPushButton#danger:hover { background: @ERROR@; color: @ACCENT_TEXT@; }

/* Segmented control - a row of buttons that reads as one object. */
QPushButton#seg { background: transparent; border: 1px solid transparent;
                  border-radius: 6px; padding: 5px 12px; color: @MUTED@;
                  font-size: 12px; }
QPushButton#seg:hover { color: @TEXT@; background: @SURFACE_HI@; }
QPushButton#seg:checked { background: @SURFACE@; color: @TEXT@; font-weight: 600;
                          border: 1px solid @BORDER@; }
#segbar { background: @FIELD_BG@; border: 1px solid @BORDER@; border-radius: 8px; }

/* ------------------------------------------------------------ text fields */
QLineEdit, QPlainTextEdit, QTextEdit {
    background: @FIELD_BG@; color: @TEXT@; border: 1px solid @BORDER@;
    border-radius: 7px; padding: 6px 9px;
    selection-background-color: @ACCENT@; selection-color: @ACCENT_TEXT@; }
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover { border-color: @BORDER_STRONG@; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus { border: 1px solid @FOCUS_RING@; }
QLineEdit:disabled { background: @BTN_DIS_BG@; color: @BTN_DIS_TEXT@;
                     border-color: @BTN_DIS_BORDER@; }

/* The tree's in-cell editor is a QLineEdit too - the form-field padding above
   makes it taller than the row and clips the text, so keep it flat and snug. */
QTreeWidget QLineEdit { background: @EDITOR_BG@; border: 1px solid @ACCENT@;
                        border-radius: 3px; padding: 0px 3px; margin: 0px; }

/* ------------------------------------------------------------- combo boxes */
QComboBox { background: @FIELD_BG@; color: @TEXT@; border: 1px solid @BORDER@;
            border-radius: 7px; padding: 6px 9px; padding-right: 28px; }
QComboBox:hover { border-color: @BORDER_STRONG@; }
QComboBox:focus, QComboBox:on { border: 1px solid @FOCUS_RING@; }
QComboBox:disabled { background: @BTN_DIS_BG@; color: @BTN_DIS_TEXT@;
                     border-color: @BTN_DIS_BORDER@; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right;
                       width: 26px; border: none; background: transparent; }
QComboBox::down-arrow { image: @GLYPH_CHEVRON@; width: 12px; height: 12px; }
QComboBox::down-arrow:disabled { image: @GLYPH_CHEVRON_DIS@; }
QComboBox QAbstractItemView {
    background: @SURFACE@; color: @TEXT@; border: 1px solid @BORDER_STRONG@;
    border-radius: 8px; padding: 4px; outline: none;
    selection-background-color: @ACCENT@; selection-color: @ACCENT_TEXT@; }
QComboBox QAbstractItemView::item { padding: 5px 8px; border-radius: 5px;
                                    min-height: 20px; }

/* --------------------------------------------------------------- spin boxes */
QSpinBox, QDoubleSpinBox {
    background: @FIELD_BG@; color: @TEXT@; border: 1px solid @BORDER@;
    border-radius: 7px; padding: 6px 9px; padding-right: 22px;
    selection-background-color: @ACCENT@; selection-color: @ACCENT_TEXT@; }
QSpinBox:hover, QDoubleSpinBox:hover { border-color: @BORDER_STRONG@; }
QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid @FOCUS_RING@; }
QSpinBox:disabled, QDoubleSpinBox:disabled { background: @BTN_DIS_BG@;
    color: @BTN_DIS_TEXT@; border-color: @BTN_DIS_BORDER@; }
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right;
    width: 20px; margin: 1px 1px 0px 0px; border: none;
    border-top-right-radius: 6px; background: transparent; }
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 20px; margin: 0px 1px 1px 0px; border: none;
    border-bottom-right-radius: 6px; background: transparent; }
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: @BTN_HOVER@; }
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed { background: @ACCENT@; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: @GLYPH_CARET_UP@;
                                               width: 9px; height: 9px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: @GLYPH_CARET_DOWN@;
                                                   width: 9px; height: 9px; }

/* ------------------------------------------------------------- check / radio
   These two blocks are the reason the module docstring warns about
   sub-controls. Without `::indicator` the platform style drew its own tick in
   its own highlight colour inside our frame. */
QCheckBox, QRadioButton { spacing: 9px; background: transparent; }
QCheckBox:disabled, QRadioButton:disabled { color: @BTN_DIS_TEXT@; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
QCheckBox::indicator {
    background: @FIELD_BG@; border: 1px solid @BORDER_STRONG@; border-radius: 4px; }
QCheckBox::indicator:hover { border-color: @ACCENT@; }
QCheckBox::indicator:checked { background: @ACCENT@; border-color: @ACCENT@;
                               image: @GLYPH_CHECK@; }
QCheckBox::indicator:checked:hover { background: @ACCENT_HOVER@; border-color: @ACCENT_HOVER@; }
QCheckBox::indicator:indeterminate { background: @ACCENT@; border-color: @ACCENT@;
                                     image: @GLYPH_DASH@; }
QCheckBox::indicator:disabled { background: @BTN_DIS_BG@; border-color: @BTN_DIS_BORDER@; }
QCheckBox::indicator:checked:disabled { background: @BTN_DIS_BG@;
                                        border-color: @BTN_DIS_BORDER@;
                                        image: @GLYPH_CHECK_DIS@; }
QRadioButton::indicator {
    background: @FIELD_BG@; border: 1px solid @BORDER_STRONG@; border-radius: 8px; }
QRadioButton::indicator:hover { border-color: @ACCENT@; }
QRadioButton::indicator:checked { background: @ACCENT@; border-color: @ACCENT@;
                                  image: @GLYPH_DOT@; }
QRadioButton::indicator:disabled { background: @BTN_DIS_BG@;
                                   border-color: @BTN_DIS_BORDER@; }

/* ------------------------------------------------------------------ sliders
   No `background`/`border` on QSlider itself: a slider is a track and a handle,
   not a field. The old rule drew a rounded input box around the whole widget,
   which is what made the native groove inside it look like a bug even before
   the colour was wrong. */
QSlider { background: transparent; border: none; }
QSlider::groove:horizontal { height: 4px; border-radius: 2px; background: @TRACK@;
                             margin: 0px; }
QSlider::sub-page:horizontal { height: 4px; border-radius: 2px; background: @ACCENT@; }
QSlider::add-page:horizontal { height: 4px; border-radius: 2px; background: @TRACK@; }
QSlider::handle:horizontal {
    width: 14px; height: 14px; margin: -6px 0px; border-radius: 7px;
    background: @SURFACE_HI@; border: 2px solid @ACCENT@; }
QSlider::handle:horizontal:hover { background: @ACCENT@; }
QSlider::handle:horizontal:pressed { background: @ACCENT_PRESS@; border-color: @ACCENT_PRESS@; }
QSlider::groove:vertical { width: 4px; border-radius: 2px; background: @TRACK@; }
QSlider::sub-page:vertical { width: 4px; border-radius: 2px; background: @TRACK@; }
QSlider::add-page:vertical { width: 4px; border-radius: 2px; background: @ACCENT@; }
QSlider::handle:vertical {
    width: 14px; height: 14px; margin: 0px -6px; border-radius: 7px;
    background: @SURFACE_HI@; border: 2px solid @ACCENT@; }
/* Disabled state: the sub-control comes FIRST and the state qualifies it.
   `QSlider:disabled::handle` (widget state, then sub-control) parses but never
   matches, so a disabled slider kept a live blue handle and a blue filled
   track - it looked adjustable and was not. */
QSlider::sub-page:horizontal:disabled, QSlider::add-page:vertical:disabled {
    background: @BTN_DIS_BORDER@; }
QSlider::groove:horizontal:disabled, QSlider::add-page:horizontal:disabled,
QSlider::groove:vertical:disabled, QSlider::sub-page:vertical:disabled {
    background: @BTN_DIS_BG@; }
QSlider::handle:horizontal:disabled, QSlider::handle:vertical:disabled {
    background: @BTN_DIS_BG@; border-color: @BTN_DIS_BORDER@; }

/* -------------------------------------------------------------- scroll bars
   Thin and quiet: on a photo tool the scrollbar is never the subject. */
QScrollBar:vertical { background: transparent; width: 11px; margin: 0px; border: none; }
QScrollBar::handle:vertical { background: @THUMB@; border-radius: 5px; min-height: 28px;
                              margin: 2px; }
QScrollBar::handle:vertical:hover { background: @THUMB_HOVER@; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 0px; border: none; }
QScrollBar::handle:horizontal { background: @THUMB@; border-radius: 5px; min-width: 28px;
                                margin: 2px; }
QScrollBar::handle:horizontal:hover { background: @THUMB_HOVER@; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0px; width: 0px; border: none;
                                             background: transparent; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ---------------------------------------------------------------- item views */
QTreeWidget, QTreeView, QListWidget, QListView, QTableWidget, QTableView {
    background: @FIELD_BG@; alternate-background-color: @TREE_ALT@;
    border: 1px solid @BORDER@; border-radius: 8px; outline: none;
    selection-background-color: @TREE_SEL@; selection-color: @TEXT@; }
QTreeWidget::item, QListWidget::item { padding: 3px 5px; border: none; }
QTreeWidget::item:hover, QListWidget::item:hover { background: @SURFACE_HI@; }
QTreeWidget::item:selected, QListWidget::item:selected { background: @TREE_SEL@;
                                                         color: @TEXT@; }
QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings { image: @GLYPH_BRANCH_SHUT@; }
QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings { image: @GLYPH_BRANCH_OPEN@; }
QHeaderView::section { background: @PANEL_BG@; color: @SECTION@; border: none;
                       border-bottom: 1px solid @BORDER@; padding: 6px 7px;
                       font-size: 10px; font-weight: 700; letter-spacing: 0.6px; }
QHeaderView::section:hover { color: @TEXT@; }

/* ----------------------------------------------------------------- tabs
   Underline tabs rather than folder tabs: less chrome, and the selected tab no
   longer has to fake a join with the pane below it. */
QTabWidget::pane { border: none; border-top: 1px solid @BORDER@; top: -1px; }
QTabBar { qproperty-drawBase: 0; background: transparent; }
QTabWidget::tab-bar { left: 18px; }   /* line the tabs up with the body margin */
QTabBar::tab { background: transparent; color: @MUTED@; padding: 8px 14px;
               border: none; border-bottom: 2px solid transparent; margin-right: 2px; }
QTabBar::tab:hover { color: @TEXT@; }
QTabBar::tab:selected { color: @TEXT@; font-weight: 600;
                        border-bottom: 2px solid @ACCENT@; }
QTabBar::tab:disabled { color: @BTN_DIS_TEXT@; }

/* ------------------------------------------------------------- progress bar */
/* Tall enough for its own text. At 8px the percentage still drew - QSS cannot
   hide it - but centred over a 8px bar it spilled onto the track beside the
   chunk and read as a stray label. Code that wants the hairline version calls
   setTextVisible(False) and #thin. */
QProgressBar { background: @TRACK@; border: none; border-radius: 8px;
               text-align: center; color: @TEXT@; min-height: 16px; max-height: 16px;
               font-size: 10px; font-weight: 600; }
QProgressBar::chunk { background: @ACCENT@; border-radius: 8px; }
QProgressBar#thin { min-height: 5px; max-height: 5px; border-radius: 3px; }
QProgressBar#thin::chunk { border-radius: 3px; }

/* ------------------------------------------------------------------ splitter */
QSplitter::handle { background: @BORDER@; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }
QSplitter::handle:hover { background: @ACCENT@; }

/* -------------------------------------------------------------------- menus */
QMenu { background: @SURFACE@; border: 1px solid @BORDER_STRONG@; border-radius: 8px;
        padding: 5px; }
QMenu::item { padding: 6px 22px 6px 12px; border-radius: 5px; }
QMenu::item:selected { background: @ACCENT@; color: @ACCENT_TEXT@; }
QMenu::separator { height: 1px; background: @BORDER@; margin: 4px 8px; }
QMenuBar { background: @PANEL_BG@; }
QMenuBar::item { padding: 5px 10px; border-radius: 5px; background: transparent; }
QMenuBar::item:selected { background: @SURFACE_HI@; }

/* ------------------------------------------------------------------ grouping */
QGroupBox { border: 1px solid @BORDER@; border-radius: 9px; margin-top: 10px;
            padding-top: 10px; background: transparent; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left;
                   left: 11px; padding: 0px 5px; color: @SECTION@;
                   font-size: 10px; font-weight: 700; letter-spacing: 1px; }

/* ------------------------------------------------------------ named objects */
#log { background: @LOG_BG@; border: 1px solid @BORDER@; border-radius: 8px;
       font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 11px;
       color: @LOG_TEXT@; padding: 6px; }

#card { background: @SURFACE@; border: 1px solid @BORDER@; border-radius: 12px; }
#card:hover { border-color: @ACCENT@; background: @CARD_HOVER_BG@; }
#card_title { font-size: 15px; font-weight: 600; color: @TITLE@; }
#card_desc { color: @MUTED@; font-size: 12px; }
#card_badge { color: @ACCENT@; font-size: 10px; font-weight: 700; letter-spacing: 1px; }

#dropzone { background: @FIELD_BG@; border: 1px dashed @BORDER_STRONG@;
            border-radius: 10px; color: @MUTED@; }
#dropzone[dragover="true"] { border: 1px dashed @ACCENT@; background: @ACCENT_SOFT@;
                             color: @TEXT@; }

#chip { background: @ACCENT_SOFT@; color: @ACCENT@; border: none; border-radius: 9px;
        padding: 2px 9px; font-size: 11px; font-weight: 600; }

QPushButton#linkbtn { background: transparent; border: 1px solid @BORDER@;
                      border-radius: 8px; padding: 6px 12px; color: @LINK_TEXT@;
                      font-size: 12px; }
QPushButton#linkbtn:hover { background: @LINK_HOVER_BG@; border-color: @ACCENT@;
                            color: @LINK_HOVER_TEXT@; }
QPushButton#kofi { background: transparent; border: 1px solid @KOFI_BORDER@;
                   border-radius: 8px; padding: 6px 12px; color: @KOFI_TEXT@;
                   font-size: 12px; font-weight: 600; }
QPushButton#kofi:hover { background: @KOFI_HOVER_BG@; border-color: @KOFI_HOVER_BORDER@;
                         color: @KOFI_HOVER_TEXT@; }
"""


def _build_qss(colors: dict) -> str:
    tokens = dict(colors)
    tokens.update(_glyph_tokens(colors))
    qss = _TEMPLATE
    for key, val in tokens.items():
        qss = qss.replace(f"@{key}@", val)
    return qss


def palette_color(name: str) -> str:
    """One theme token for the current mode, for code that paints directly.

    Anything drawing with QPainter (the preview canvas's outlines, the launcher's
    glyphs) needs the same colours the QSS uses, and hardcoding them there is how
    a widget ends up correct in one mode only.
    """
    colors = _DARK if resolved_mode() == "dark" else _LIGHT
    return colors.get(name, colors["TEXT"])


# Kept for compatibility: the dark stylesheet under its historical name, so a
# half-overlaid update (old GUI file + new theme) still imports cleanly.
#
# It is built ON ACCESS, never at import. Building it eagerly called
# `_glyph_tokens`, which draws QPixmaps - and a QPixmap constructed before the
# QGuiApplication exists is a qFatal abort, not an exception. Every entry point
# in the suite imports this module at module level and constructs its
# QApplication inside main(), so `import theme` killed the process outright with
# "QPixmap: Must construct a QGuiApplication before a QPixmap". Nothing in the
# suite reads APP_QSS any more, so the cost of deferring it is nil, and by the
# time legacy code could read it a QApplication is up.
def __getattr__(name):
    if name == "APP_QSS":
        return _build_qss(_DARK)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------- mode handling

_VALID_MODES = ("system", "light", "dark")
_hooked_system_follow = False


def _qsettings():
    from PySide6 import QtCore
    return QtCore.QSettings("Chaser", "PhotoTools-Theme")


def get_mode() -> str:
    """The user's chosen mode: 'system' (default), 'light' or 'dark'."""
    try:
        mode = str(_qsettings().value("mode", "system"))
    except Exception:  # noqa: BLE001
        return "system"
    return mode if mode in _VALID_MODES else "system"


def set_mode(mode: str) -> None:
    """Persist a mode choice and restyle every open window immediately."""
    if mode not in _VALID_MODES:
        raise ValueError(f"Unknown theme mode: {mode!r}")
    s = _qsettings()
    s.setValue("mode", mode)
    s.sync()
    ensure_applied()


def _system_prefers_dark() -> bool:
    """Best-effort read of the OS light/dark preference.

    Qt 6.5+ exposes it directly; older Qt falls back to the Windows registry.
    Defaults to dark (the suite's historical look) if nothing can be read.
    """
    try:
        from PySide6 import QtCore, QtGui
        app = QtGui.QGuiApplication.instance()
        if app is not None and hasattr(app.styleHints(), "colorScheme"):
            scheme = app.styleHints().colorScheme()
            if scheme == QtCore.Qt.ColorScheme.Light:
                return False
            if scheme == QtCore.Qt.ColorScheme.Dark:
                return True
    except Exception:  # noqa: BLE001
        pass
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion"
                                r"\Themes\Personalize") as key:
                light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return int(light) == 0
        except Exception:  # noqa: BLE001
            pass
    return True


def resolved_mode() -> str:
    """'light' or 'dark' - what should actually be on screen right now."""
    mode = get_mode()
    if mode == "system":
        return "dark" if _system_prefers_dark() else "light"
    return mode


def state_color(name: str) -> str:
    """Code-side state colour ('modified' / 'deleted' / 'viewonly') for the
    current mode."""
    return _STATE[resolved_mode()][name]


def _palette_for(colors: dict):
    from PySide6 import QtGui
    pal = QtGui.QPalette()
    c = QtGui.QColor
    pal.setColor(QtGui.QPalette.Window, c(colors["WINDOW_BG"]))
    pal.setColor(QtGui.QPalette.WindowText, c(colors["TEXT"]))
    pal.setColor(QtGui.QPalette.Base, c(colors["FIELD_BG"]))
    pal.setColor(QtGui.QPalette.AlternateBase, c(colors["TREE_ALT"]))
    pal.setColor(QtGui.QPalette.Text, c(colors["TEXT"]))
    pal.setColor(QtGui.QPalette.Button, c(colors["BTN_BG"]))
    pal.setColor(QtGui.QPalette.ButtonText, c(colors["TEXT"]))
    pal.setColor(QtGui.QPalette.Highlight, c(colors["ACCENT"]))
    pal.setColor(QtGui.QPalette.HighlightedText, c(colors["ACCENT_TEXT"]))
    pal.setColor(QtGui.QPalette.ToolTipBase, c(colors["SURFACE"]))
    pal.setColor(QtGui.QPalette.ToolTipText, c(colors["TEXT"]))
    pal.setColor(QtGui.QPalette.PlaceholderText, c(colors["PLACEHOLDER"]))
    pal.setColor(QtGui.QPalette.Link, c(colors["ACCENT"]))
    pal.setColor(QtGui.QPalette.Mid, c(colors["BORDER"]))
    pal.setColor(QtGui.QPalette.Dark, c(colors["BORDER_STRONG"]))
    pal.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Text, c(colors["BTN_DIS_TEXT"]))
    pal.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.ButtonText, c(colors["BTN_DIS_TEXT"]))
    pal.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.WindowText, c(colors["BTN_DIS_TEXT"]))
    return pal


def ensure_applied() -> None:
    """Apply the current theme (stylesheet + palette) at the application level.

    Idempotent - every window calls this in __init__; the launcher's theme
    switch calls it again to restyle live. Window code must NOT call
    setStyleSheet with a whole theme (a window-level sheet overrides the
    app-level one and freezes that window in the old theme).
    """
    global _hooked_system_follow
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    colors = _DARK if resolved_mode() == "dark" else _LIGHT
    app.setPalette(_palette_for(colors))
    app.setStyleSheet(_build_qss(colors))

    # In "system" mode, follow Windows live if Qt can tell us about changes.
    if not _hooked_system_follow:
        try:
            app.styleHints().colorSchemeChanged.connect(_on_system_scheme_changed)
            _hooked_system_follow = True
        except Exception:  # noqa: BLE001
            pass


def _on_system_scheme_changed(*_args) -> None:
    if get_mode() == "system":
        ensure_applied()
