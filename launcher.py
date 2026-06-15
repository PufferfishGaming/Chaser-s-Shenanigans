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

from theme import APP_QSS, icon_path, set_app_user_model_id
from updater import run_update_check

# Import the three tool windows. Each is a self-contained QMainWindow.
from photoborder_gui import MainWindow as PhotoBorderWindow
from converter_gui import MainWindow as ConverterWindow
from metadata_gui import MainWindow as MetadataWindow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


TOOLS = [
    ("PhotoBorder", "Add borders, EXIF strips and colour palettes. Batch a whole "
                    "folder in parallel with a live preview.", PhotoBorderWindow),
    ("Format Converter", "Convert images between JPEG, PNG, WEBP, TIFF, BMP and "
                         "HEIF/HEIC/HIF — keeping EXIF where the format allows.", ConverterWindow),
    ("Metadata Baker", "Copy EXIF from one image into another (e.g. restore camera "
                       "metadata onto an export), with GPS/orientation safety toggles.",
     MetadataWindow),
]


class Card(QtWidgets.QFrame):
    """A clickable tile that opens a tool."""
    def __init__(self, title, desc, on_click):
        super().__init__()
        self.setObjectName("card")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self._on_click = on_click

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)
        t = QtWidgets.QLabel(title)
        t.setObjectName("card_title")
        d = QtWidgets.QLabel(desc)
        d.setObjectName("card_desc")
        d.setWordWrap(True)
        lay.addWidget(t)
        lay.addWidget(d, 1)
        open_btn = QtWidgets.QPushButton("Open")
        open_btn.setObjectName("primary")
        open_btn.clicked.connect(self._on_click)
        lay.addWidget(open_btn)

    def mouseReleaseEvent(self, e):
        # Clicking anywhere on the card opens it too.
        if e.button() == QtCore.Qt.LeftButton:
            self._on_click()
        super().mouseReleaseEvent(e)


class Launcher(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chaser's Shenanigans")
        self.resize(900, 360)
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
        for title_, desc_, cls in TOOLS:
            cards.addWidget(Card(title_, desc_, self._make_opener(cls)))
        root.addLayout(cards, 1)

        self.setStyleSheet(APP_QSS)

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
