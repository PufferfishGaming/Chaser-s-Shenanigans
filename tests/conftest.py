"""
Shared pytest setup.

Every QSettings the app opens by name - QtCore.QSettings("Chaser", "PhotoBorder")
and friends - lives in the user's real store (the registry on Windows), so a test
that builds a window would read the user's saved folders, fonts and placements,
and closing the window would write over them. Here every by-name QSettings is
redirected to an INI file in the test's own tmp_path instead: each test starts
from an empty store and the user's state is never read or written.
"""
import pytest

try:
    from PySide6 import QtCore
except ImportError:                                     # pragma: no cover
    QtCore = None


@pytest.fixture(autouse=True)
def private_qsettings(tmp_path, monkeypatch):
    """Point every by-name QSettings at tmp_path for the length of one test."""
    if QtCore is None:
        yield None
        return
    real = QtCore.QSettings
    root = tmp_path / "qsettings"
    root.mkdir()

    class PrivateQSettings(real):
        def __init__(self, *args, **kwargs):
            # QSettings(org, app) -> a per-(org, app) INI file under tmp_path, so
            # two windows in one test still share a store, as they would for real.
            # QSettings(fileName, format) already names its own file: left alone.
            if args and isinstance(args[0], str) and not (
                    len(args) > 1 and isinstance(args[1], real.Format)):
                org = args[0]
                app = args[1] if len(args) > 1 else kwargs.get("application", "")
                path = root / f"{org}-{app or 'default'}.ini"
                super().__init__(str(path), real.IniFormat)
            else:
                super().__init__(*args, **kwargs)

    monkeypatch.setattr(QtCore, "QSettings", PrivateQSettings)
    yield root
