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

_DARK = {
    "WINDOW_BG": "#131418",  "TEXT": "#e8e8ea",     "TITLE": "#f4f4f6",
    "PANEL_BG": "#1b1c20",   "BORDER": "#2c2e34",   "PREVIEW_BG": "#232428",
    "MUTED": "#8a8d96",      "HINT": "#c89b5a",     "ERROR": "#d98a8a",
    "SECTION": "#6f727b",    "FIELD_BG": "#16171a", "PATH_BG": "#16171a",
    "PATH_TEXT": "#b9bcc4",  "BTN_BG": "#2a2c32",   "BTN_BORDER": "#3a3d45",
    "BTN_HOVER": "#33363d",  "BTN_DIS_TEXT": "#555a63", "BTN_DIS_BG": "#202126",
    "ACCENT": "#3b6ea5",     "ACCENT_HOVER": "#447dbb", "SPIN_ARROW": "#c8cad0",
    "LOG_BG": "#16171a",     "LOG_TEXT": "#99aaaa", "CARD_HOVER_BG": "#20222a",
    "LINK_TEXT": "#b9bcc4",  "LINK_HOVER_BG": "#20222a", "LINK_HOVER_TEXT": "#e8e8ea",
    "KOFI_BORDER": "#6e463f", "KOFI_TEXT": "#e9b9ac", "KOFI_HOVER_BG": "#2a211f",
    "KOFI_HOVER_TEXT": "#ffd9cc",
    "TREE_ALT": "#1a1b20",   "TREE_SEL": "#2b4a6f", "EDITOR_BG": "#101114",
    "PLACEHOLDER": "#6f727b",
}

_LIGHT = {
    "WINDOW_BG": "#f7f8fa",  "TEXT": "#26282e",     "TITLE": "#1a1b1f",
    "PANEL_BG": "#f2f3f5",   "BORDER": "#d5d7dc",   "PREVIEW_BG": "#e3e4e8",
    "MUTED": "#6b6e78",      "HINT": "#a3742c",     "ERROR": "#b04a4a",
    "SECTION": "#7a7d86",    "FIELD_BG": "#ffffff", "PATH_BG": "#e9eaee",
    "PATH_TEXT": "#4a4d55",  "BTN_BG": "#e4e5e9",   "BTN_BORDER": "#c9ccd3",
    "BTN_HOVER": "#d8dade",  "BTN_DIS_TEXT": "#a0a3ab", "BTN_DIS_BG": "#eceef1",
    "ACCENT": "#3b6ea5",     "ACCENT_HOVER": "#447dbb", "SPIN_ARROW": "#5a5d66",
    "LOG_BG": "#f4f5f7",     "LOG_TEXT": "#556666", "CARD_HOVER_BG": "#eef2f8",
    "LINK_TEXT": "#5a5d66",  "LINK_HOVER_BG": "#eef1f6", "LINK_HOVER_TEXT": "#26282e",
    "KOFI_BORDER": "#d0977e", "KOFI_TEXT": "#a8543c", "KOFI_HOVER_BG": "#faeee9",
    "KOFI_HOVER_TEXT": "#8c3b24",
    "TREE_ALT": "#f4f5f8",   "TREE_SEL": "#cfe0f5", "EDITOR_BG": "#ffffff",
    "PLACEHOLDER": "#9aa0a8",
}

# Code-side row/state colours (used by widgets that colour items directly,
# e.g. the Metadata tag browser). Kept here so both modes stay readable.
_STATE = {
    "dark":  {"modified": "#7ee787", "deleted": "#f28b82", "viewonly": "#8b8d93"},
    "light": {"modified": "#1a7f37", "deleted": "#b3261e", "viewonly": "#8b8d93"},
}

_TEMPLATE = """
QMainWindow, QDialog { background: @WINDOW_BG@; }
QWidget { color: @TEXT@; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
#panel { background: @PANEL_BG@; border-right: 1px solid @BORDER@; }
#preview_area { background: @PREVIEW_BG@; }
#title { font-size: 22px; font-weight: 600; color: @TITLE@; }
#subtitle { color: @MUTED@; font-size: 12px; }
#hint { color: @HINT@; font-size: 11px; font-style: italic; }
#error { color: @ERROR@; font-size: 11px; }
#section { color: @SECTION@; font-size: 10px; font-weight: 700; letter-spacing: 1px; margin-top: 6px; }
#pathlabel { color: @PATH_TEXT@; font-size: 11px; background: @PATH_BG@; border: 1px solid @BORDER@; border-radius: 6px; padding: 6px 8px; }
#preview_status { color: @MUTED@; font-size: 12px; }
QPushButton { background: @BTN_BG@; border: 1px solid @BTN_BORDER@; border-radius: 6px; padding: 7px 10px; }
QPushButton:hover { background: @BTN_HOVER@; }
QPushButton:disabled { color: @BTN_DIS_TEXT@; background: @BTN_DIS_BG@; }
QPushButton#primary { background: @ACCENT@; border: none; font-weight: 600; color: #ffffff; }
QPushButton#primary:hover { background: @ACCENT_HOVER@; }
QComboBox { background: @FIELD_BG@; border: 1px solid @BORDER@; border-radius: 6px; padding: 5px 8px; }
QComboBox QAbstractItemView { background: @FIELD_BG@; border: 1px solid @BORDER@; selection-background-color: @TREE_SEL@; }
QSpinBox, QSlider { background: @FIELD_BG@; border: 1px solid @BORDER@; border-radius: 6px; padding: 5px 0px 5px 8px; }
QSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right;
    width: 22px; height: 14px; border-left: 1px solid @BORDER@;
    border-top-right-radius: 6px; background: @BTN_BG@;
}
QSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 22px; height: 14px; border-left: 1px solid @BORDER@;
    border-bottom-right-radius: 6px; background: @BTN_BG@;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: @BTN_HOVER@; }
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed { background: @ACCENT_HOVER@; }
QSpinBox::up-arrow { image: none; width: 0; height: 0;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-bottom: 5px solid @SPIN_ARROW@; }
QSpinBox::down-arrow { image: none; width: 0; height: 0;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid @SPIN_ARROW@; }
QCheckBox { spacing: 8px; }
QLineEdit { background: @FIELD_BG@; border: 1px solid @BORDER@; border-radius: 6px; padding: 5px 8px; }
/* The tree's in-cell editor is a QLineEdit too - the form-field padding above
   makes it taller than the row and clips the text, so keep it flat and snug. */
QTreeWidget QLineEdit { background: @EDITOR_BG@; border: 1px solid @ACCENT@; border-radius: 2px; padding: 0px 3px; margin: 0px; }
QTreeWidget { background: @FIELD_BG@; alternate-background-color: @TREE_ALT@; border: 1px solid @BORDER@; border-radius: 6px; }
QTreeWidget::item { padding: 2px 4px; }
QTreeWidget::item:selected { background: @TREE_SEL@; }
QHeaderView::section { background: @PANEL_BG@; color: @MUTED@; border: none; border-bottom: 1px solid @BORDER@; padding: 4px 6px; font-size: 11px; font-weight: 600; }
QTabWidget::pane { border: 1px solid @BORDER@; border-radius: 6px; }
QTabBar::tab { background: @BTN_BG@; color: @TEXT@; padding: 6px 14px; border: 1px solid @BORDER@; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }
QTabBar::tab:selected { background: @CARD_HOVER_BG@; }
QProgressBar { background: @FIELD_BG@; border: 1px solid @BORDER@; border-radius: 6px; text-align: center; height: 20px; }
QProgressBar::chunk { background: @ACCENT@; border-radius: 5px; }
#log { background: @LOG_BG@; border: 1px solid @BORDER@; border-radius: 6px; font-family: 'Consolas', monospace; font-size: 11px; color: @LOG_TEXT@; }
#card { background: @PANEL_BG@; border: 1px solid @BORDER@; border-radius: 10px; }
#card:hover { border: 1px solid @ACCENT@; background: @CARD_HOVER_BG@; }
#card_title { font-size: 16px; font-weight: 600; color: @TITLE@; }
#card_desc { color: @MUTED@; font-size: 12px; }
QPushButton#linkbtn { background: transparent; border: 1px solid @BORDER@; border-radius: 8px; padding: 6px 12px; color: @LINK_TEXT@; font-size: 12px; }
QPushButton#linkbtn:hover { background: @LINK_HOVER_BG@; border: 1px solid @ACCENT@; color: @LINK_HOVER_TEXT@; }
QPushButton#kofi { background: transparent; border: 1px solid @KOFI_BORDER@; border-radius: 8px; padding: 6px 12px; color: @KOFI_TEXT@; font-size: 12px; font-weight: 600; }
QPushButton#kofi:hover { background: @KOFI_HOVER_BG@; border: 1px solid #ff6b52; color: @KOFI_HOVER_TEXT@; }
"""


def _build_qss(colors: dict) -> str:
    qss = _TEMPLATE
    for key, val in colors.items():
        qss = qss.replace(f"@{key}@", val)
    return qss


# Kept for compatibility: the dark stylesheet under its historical name, so a
# half-overlaid update (old GUI file + new theme) still imports cleanly.
APP_QSS = _build_qss(_DARK)


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
    pal.setColor(QtGui.QPalette.HighlightedText, c("#ffffff"))
    pal.setColor(QtGui.QPalette.ToolTipBase, c(colors["PANEL_BG"]))
    pal.setColor(QtGui.QPalette.ToolTipText, c(colors["TEXT"]))
    pal.setColor(QtGui.QPalette.PlaceholderText, c(colors["PLACEHOLDER"]))
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
