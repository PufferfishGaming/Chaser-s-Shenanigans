"""
Shared visual theme for the PhotoTools suite.

Extracted from the original PhotoBorder stylesheet so the launcher and all three
tools read as one application. Import APP_QSS and apply it once on the
QApplication (or per-window) to get the consistent dark look.

Also exposes icon_path(): the on-disk path to the app icon, resolved correctly
whether running from source or from a PyInstaller bundle.
"""
import os
import sys


def icon_path() -> str | None:
    """Absolute path to icon.ico, or None if it isn't present.

    Handles PyInstaller's bundle dir (sys._MEIPASS) so the packaged .exe finds
    the icon that build_exe.bat added with --add-data.
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


APP_QSS = """
QWidget { color: #e8e8ea; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
#panel { background: #1b1c20; border-right: 1px solid #2c2e34; }
#preview_area { background: #232428; }
#title { font-size: 22px; font-weight: 600; color: #f4f4f6; }
#subtitle { color: #8a8d96; font-size: 12px; }
#hint { color: #c89b5a; font-size: 11px; font-style: italic; }
#error { color: #d98a8a; font-size: 11px; }
#section { color: #6f727b; font-size: 10px; font-weight: 700; letter-spacing: 1px; margin-top: 6px; }
#pathlabel { color: #b9bcc4; font-size: 11px; background: #16171a; border: 1px solid #2c2e34; border-radius: 6px; padding: 6px 8px; }
#preview_status { color: #8a8d96; font-size: 12px; }
QPushButton { background: #2a2c32; border: 1px solid #3a3d45; border-radius: 6px; padding: 7px 10px; }
QPushButton:hover { background: #33363d; }
QPushButton:disabled { color: #555; background: #202126; }
QPushButton#primary { background: #3b6ea5; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #447dbb; }
QComboBox { background: #16171a; border: 1px solid #2c2e34; border-radius: 6px; padding: 5px 8px; }
QSpinBox, QSlider { background: #16171a; border: 1px solid #2c2e34; border-radius: 6px; padding: 5px 0px 5px 8px; }
QSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right;
    width: 22px; height: 14px; border-left: 1px solid #2c2e34;
    border-top-right-radius: 6px; background: #2a2c32;
}
QSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 22px; height: 14px; border-left: 1px solid #2c2e34;
    border-bottom-right-radius: 6px; background: #2a2c32;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #3a3d45; }
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed { background: #447dbb; }
QSpinBox::up-arrow { image: none; width: 0; height: 0;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-bottom: 5px solid #c8cad0; }
QSpinBox::down-arrow { image: none; width: 0; height: 0;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid #c8cad0; }
QCheckBox { spacing: 8px; }
QProgressBar { background: #16171a; border: 1px solid #2c2e34; border-radius: 6px; text-align: center; height: 20px; }
QProgressBar::chunk { background: #3b6ea5; border-radius: 5px; }
#log { background: #16171a; border: 1px solid #2c2e34; border-radius: 6px; font-family: 'Consolas', monospace; font-size: 11px; color: #9aa; }
#card { background: #1b1c20; border: 1px solid #2c2e34; border-radius: 10px; }
#card:hover { border: 1px solid #3b6ea5; background: #20222a; }
#card_title { font-size: 16px; font-weight: 600; color: #f4f4f6; }
#card_desc { color: #8a8d96; font-size: 12px; }
"""
