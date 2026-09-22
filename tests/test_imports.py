"""
Every module must import with NO QApplication in existence.

This is how the suite actually starts. `launcher.py` imports `theme`, `ui` and
the tool modules at module level, and only constructs the QApplication inside
`main()` - so anything that builds a Qt GUI object at import time runs before
there is a GUI to build it with.

The failure mode is not an exception. Qt calls qFatal and the process aborts:

    QPixmap: Must construct a QGuiApplication before a QPixmap

so `try/except` around the offending call catches nothing, `pytest` reports no
assertion, and the app simply dies on launch with a one-line message. That is
exactly what shipped when `theme.APP_QSS` was a module-level constant built by
drawing the UI glyphs: every test in this suite created a QApplication in a
fixture before importing anything, so all 149 passed against a suite that could
not start.

Each import therefore runs in its own SUBPROCESS, and the assertion is on the
exit code. In-process would abort the test runner itself.
"""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Every module the launcher pulls in at import time, plus the launcher itself.
MODULES = [
    "theme",
    "ui",
    "launcher",
    "photoborder_gui",
    "converter_gui",
    "metadata_gui",
    "stacker_gui",
    "quickedit_gui",
]


def _import_in_subprocess(module: str) -> subprocess.CompletedProcess:
    code = (
        "import sys\n"
        f"sys.path.insert(0, {ROOT!r})\n"
        f"import {module}\n"
        "print('ok')\n"
    )
    env = dict(os.environ)
    # Offscreen so a box with no display behaves like the real one here. This
    # does NOT create a QApplication - it only picks the platform plugin.
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    return subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, timeout=180, env=env)


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_without_a_qapplication(module):
    proc = _import_in_subprocess(module)
    assert proc.returncode == 0, (
        f"`import {module}` failed with no QApplication "
        f"(exit {proc.returncode}).\n"
        "A Qt GUI object is being constructed at import time - a QPixmap, QIcon, "
        "QFont or QPainter at module scope, or a module-level constant computed "
        "from one.\n"
        f"stdout: {proc.stdout!r}\nstderr: {proc.stderr!r}")
    assert "ok" in proc.stdout


def test_theme_app_qss_is_not_built_at_import_time():
    """`theme.APP_QSS` is the specific constant that caused this.

    It is a compatibility shim for a half-overlaid update (old GUI file + new
    theme), so it has to keep working - but it must be built on ACCESS, not at
    import, because building it draws the glyph pixmaps.
    """
    proc = _import_in_subprocess("theme")
    assert proc.returncode == 0

    # Reading it once a QApplication exists must still give a real stylesheet.
    code = (
        "import sys\n"
        f"sys.path.insert(0, {ROOT!r})\n"
        "import theme\n"
        "from PySide6 import QtWidgets\n"
        "app = QtWidgets.QApplication([])\n"
        "qss = theme.APP_QSS\n"
        "assert 'QCheckBox::indicator' in qss, 'APP_QSS lost its content'\n"
        "print('ok')\n"
    )
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, timeout=180, env=env)
    assert proc.returncode == 0, f"stderr: {proc.stderr!r}"
    assert "ok" in proc.stdout


def test_glyph_generation_is_skipped_without_a_gui():
    """`theme._glyph` must decline rather than abort when there is no GUI.

    The guard is a check, not a catch: `_gui_is_up()` has to be consulted BEFORE
    the QPixmap is constructed, because once it is constructed with no
    QGuiApplication the process is already gone.
    """
    code = (
        "import sys\n"
        f"sys.path.insert(0, {ROOT!r})\n"
        "import theme\n"
        "assert theme._gui_is_up() is False\n"
        "assert theme._glyph('check', 14, '#ffffff') is None\n"
        # And the whole stylesheet still builds, just without images.
        "qss = theme._build_qss(theme._DARK)\n"
        "assert 'QSlider::handle' in qss\n"
        "print('ok')\n"
    )
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, timeout=180, env=env)
    assert proc.returncode == 0, f"stderr: {proc.stderr!r}"
    assert "ok" in proc.stdout
