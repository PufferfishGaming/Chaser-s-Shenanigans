"""
Metadata Baker - desktop frontend (PySide6).

Copies EXIF from a DONOR image into a RECIPIENT image and writes a new file.
Shows a small before/after EXIF preview so you can see what travelled across,
and exposes the three safety toggles (drop GPS, normalize orientation, rewrite
stale dimension tags) discussed in metadata_core.
"""
import os
import logging

from PySide6 import QtCore, QtWidgets

import metadata_core as mc
from theme import APP_QSS

logger = logging.getLogger(__name__)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Metadata Baker")
        self.resize(960, 660)
        self.settings = QtCore.QSettings("Chaser", "PhotoTools-Metadata")

        self.donor_path = None
        self.recipient_path = None
        self.output_dir = None

        self._build_ui()
        self.setStyleSheet(APP_QSS)
        self._load_settings()

    def _section(self, text):
        lbl = QtWidgets.QLabel(text.upper())
        lbl.setObjectName("section")
        return lbl

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        title = QtWidgets.QLabel("Metadata")
        title.setObjectName("title")
        root.addWidget(title)
        sub = QtWidgets.QLabel("Copy EXIF between images, or edit fields directly "
                               "(EXIF only; IPTC/XMP not handled)")
        sub.setObjectName("subtitle")
        sub.setWordWrap(True)
        root.addWidget(sub)

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._build_bake_tab(), "Bake (copy EXIF)")
        tabs.addTab(self._build_edit_tab(), "Edit fields")
        root.addWidget(tabs, 1)

    def _build_bake_tab(self):
        tab = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(tab)
        root.setSpacing(12)

        # Donor + recipient side by side
        cols = QtWidgets.QHBoxLayout()

        # Donor column
        donor_col = QtWidgets.QVBoxLayout()
        donor_col.addWidget(self._section("Donor (copy metadata FROM)"))
        self.donor_label = QtWidgets.QLabel("No donor selected")
        self.donor_label.setObjectName("pathlabel")
        self.donor_label.setWordWrap(True)
        donor_col.addWidget(self.donor_label)
        b_donor = QtWidgets.QPushButton("Choose donor…")
        b_donor.clicked.connect(self.choose_donor)
        donor_col.addWidget(b_donor)
        self.donor_exif = QtWidgets.QPlainTextEdit()
        self.donor_exif.setReadOnly(True)
        self.donor_exif.setObjectName("log")
        donor_col.addWidget(self.donor_exif, 1)
        cols.addLayout(donor_col, 1)

        # Recipient column
        rec_col = QtWidgets.QVBoxLayout()
        rec_col.addWidget(self._section("Recipient (keep these PIXELS)"))
        self.recipient_label = QtWidgets.QLabel("No recipient selected")
        self.recipient_label.setObjectName("pathlabel")
        self.recipient_label.setWordWrap(True)
        rec_col.addWidget(self.recipient_label)
        b_rec = QtWidgets.QPushButton("Choose recipient…")
        b_rec.clicked.connect(self.choose_recipient)
        rec_col.addWidget(b_rec)
        self.recipient_exif = QtWidgets.QPlainTextEdit()
        self.recipient_exif.setReadOnly(True)
        self.recipient_exif.setObjectName("log")
        rec_col.addWidget(self.recipient_exif, 1)
        cols.addLayout(rec_col, 1)

        root.addLayout(cols, 1)

        # Options
        root.addWidget(self._section("Options"))
        self.cb_drop_gps = QtWidgets.QCheckBox("Drop GPS location")
        self.cb_drop_gps.setToolTip("Remove the donor's GPS coordinates so they don't travel onto the recipient.")
        root.addWidget(self.cb_drop_gps)

        self.cb_orientation = QtWidgets.QCheckBox("Normalize orientation (recommended)")
        self.cb_orientation.setChecked(True)
        self.cb_orientation.setToolTip(
            "Force the Orientation tag to 'Normal'. Prevents the donor's rotation "
            "tag double-rotating the recipient's already-correct pixels.")
        root.addWidget(self.cb_orientation)

        self.cb_dimensions = QtWidgets.QCheckBox("Rewrite dimension tags to match recipient (recommended)")
        self.cb_dimensions.setChecked(True)
        self.cb_dimensions.setToolTip(
            "The donor's pixel-dimension EXIF tags describe the donor, not the "
            "recipient. This rewrites them to the recipient's real size so they "
            "aren't misleading. (JPEG/TIFF recipients only.)")
        root.addWidget(self.cb_dimensions)

        self.cb_overwrite = QtWidgets.QCheckBox("Overwrite if output exists (otherwise appends ' (1)')")
        root.addWidget(self.cb_overwrite)

        out_row = QtWidgets.QHBoxLayout()
        out_row.addWidget(QtWidgets.QLabel("Output folder"))
        self.output_label = QtWidgets.QLabel("(same folder as recipient)")
        self.output_label.setObjectName("pathlabel")
        self.output_label.setWordWrap(True)
        out_row.addWidget(self.output_label, 1)
        b_out = QtWidgets.QPushButton("Choose…")
        b_out.clicked.connect(self.choose_output)
        out_row.addWidget(b_out)
        root.addLayout(out_row)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("log")
        self.log.setFixedHeight(90)
        root.addWidget(self.log)

        self.run_btn = QtWidgets.QPushButton("Bake metadata")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self.bake)
        root.addWidget(self.run_btn)
        return tab

    def _build_edit_tab(self):
        tab = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(tab)
        root.setSpacing(10)

        self.edit_target = None
        self.edit_is_dir = False

        root.addWidget(self._section("Image or folder"))
        sel_row = QtWidgets.QHBoxLayout()
        b_img = QtWidgets.QPushButton("Choose image…")
        b_img.clicked.connect(self.edit_choose_image)
        b_dir = QtWidgets.QPushButton("Choose folder… (batch)")
        b_dir.clicked.connect(self.edit_choose_folder)
        sel_row.addWidget(b_img)
        sel_row.addWidget(b_dir)
        root.addLayout(sel_row)
        self.edit_target_label = QtWidgets.QLabel("Nothing selected (JPEG / TIFF only)")
        self.edit_target_label.setObjectName("pathlabel")
        self.edit_target_label.setWordWrap(True)
        root.addWidget(self.edit_target_label)

        root.addWidget(self._section("Fields (blank = keep unchanged)"))
        form = QtWidgets.QFormLayout()
        self.ed_artist = QtWidgets.QLineEdit()
        self.ed_copyright = QtWidgets.QLineEdit()
        self.ed_desc = QtWidgets.QLineEdit()
        form.addRow("Artist / creator", self.ed_artist)
        form.addRow("Copyright", self.ed_copyright)
        form.addRow("Description", self.ed_desc)
        root.addLayout(form)

        self.ed_strip_gps = QtWidgets.QCheckBox("Remove GPS (location)")
        root.addWidget(self.ed_strip_gps)

        ds_row = QtWidgets.QHBoxLayout()
        ds_row.addWidget(QtWidgets.QLabel("Shift capture time by"))
        self.ed_shift = QtWidgets.QSpinBox()
        self.ed_shift.setRange(-100000, 100000)
        self.ed_shift.setSuffix(" min")
        self.ed_shift.setToolTip("Adjust DateTimeOriginal/Digitized and DateTime "
                                 "(e.g. fix a wrong clock or a timezone offset).")
        ds_row.addWidget(self.ed_shift)
        ds_row.addStretch(1)
        root.addLayout(ds_row)

        self.ed_overwrite = QtWidgets.QCheckBox("Overwrite original (otherwise writes <name>_meta)")
        root.addWidget(self.ed_overwrite)

        self.edit_log = QtWidgets.QPlainTextEdit()
        self.edit_log.setReadOnly(True)
        self.edit_log.setObjectName("log")
        self.edit_log.setFixedHeight(110)
        root.addWidget(self.edit_log)

        self.edit_apply_btn = QtWidgets.QPushButton("Apply")
        self.edit_apply_btn.setObjectName("primary")
        self.edit_apply_btn.clicked.connect(self.apply_edits)
        root.addWidget(self.edit_apply_btn)
        root.addStretch(1)
        return tab

    # ---- edit tab handlers --------------------------------------------------
    _EDIT_FILTER = "JPEG / TIFF (*.jpg *.jpeg *.tif *.tiff)"

    def edit_choose_image(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Choose image", "", self._EDIT_FILTER)
        if not path:
            return
        self.edit_target = path
        self.edit_is_dir = False
        self.edit_target_label.setText(path)
        fields = mc.read_fields(path)
        self.ed_artist.setText(fields["artist"])
        self.ed_copyright.setText(fields["copyright"])
        self.ed_desc.setText(fields["description"])
        self._elog("Loaded current fields. Blank fields stay unchanged.")

    def edit_choose_folder(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose folder")
        if not path:
            return
        self.edit_target = path
        self.edit_is_dir = True
        self.edit_target_label.setText(f"{path}   (batch — applies to every JPEG/TIFF)")
        self._elog("Batch mode: fields you fill will be written to every JPEG/TIFF.")

    def apply_edits(self):
        if not self.edit_target:
            self._elog("Choose an image or a folder first.")
            return

        def val(line):
            t = line.text().strip()
            return t if t else None        # blank -> leave the field unchanged

        edits = dict(artist=val(self.ed_artist), copyright=val(self.ed_copyright),
                     description=val(self.ed_desc), strip_gps=self.ed_strip_gps.isChecked(),
                     datetime_shift_sec=self.ed_shift.value() * 60)
        try:
            if self.edit_is_dir:
                from filemanager import get_directory_files
                globs = ["*.jpg", "*.jpeg", "*.tif", "*.tiff",
                         "*.JPG", "*.JPEG", "*.TIF", "*.TIFF"]
                paths = get_directory_files(self.edit_target, False, globs, [])
                if not paths:
                    self._elog("No JPEG/TIFF files found in that folder.")
                    return
                results = mc.stamp_files(paths, **edits)
                ok = sum(1 for r in results if r.edited)
                self._elog(f"Edited {ok}/{len(results)} file(s).")
                for r in results:
                    if not r.edited:
                        self._elog(f"  {os.path.basename(r.out_path)}: {'; '.join(r.notes)}")
            else:
                res = mc.edit_metadata(self.edit_target, None,
                                       overwrite=self.ed_overwrite.isChecked(), **edits)
                self._elog(f"Saved: {os.path.basename(res.out_path)}")
                for n in res.notes:
                    self._elog(f"  {n}")
        except Exception as e:  # noqa: BLE001
            self._elog(f"ERROR: {e}")

    def _elog(self, msg):
        self.edit_log.appendPlainText(msg)


    # ---- selection ----------------------------------------------------------
    _FILTER = "Images (*.jpg *.jpeg *.tif *.tiff *.png *.webp)"

    def choose_donor(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Choose donor image", "", self._FILTER)
        if path:
            self.donor_path = path
            self.donor_label.setText(path)
            self._show_exif(self.donor_exif, path)

    def choose_recipient(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Choose recipient image", "", self._FILTER)
        if path:
            self.recipient_path = path
            self.recipient_label.setText(path)
            self._show_exif(self.recipient_exif, path)

    def choose_output(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose output folder")
        if path:
            self.output_dir = path
            self.output_label.setText(path)

    def _show_exif(self, widget, path):
        items = mc.describe_exif(path, limit=16)
        if not items:
            widget.setPlainText("(no readable EXIF)")
        else:
            widget.setPlainText("\n".join(f"{k}: {v}" for k, v in items))

    # ---- bake ---------------------------------------------------------------
    def bake(self):
        if not self.donor_path:
            self._log("Choose a donor image.")
            return
        if not self.recipient_path:
            self._log("Choose a recipient image.")
            return

        rec_dir = os.path.dirname(os.path.abspath(self.recipient_path))
        out_dir = self.output_dir or rec_dir
        base, ext = os.path.splitext(os.path.basename(self.recipient_path))
        out_path = os.path.join(out_dir, f"{base}_meta{ext}")

        try:
            res = mc.bake_metadata(
                self.donor_path, self.recipient_path, out_path,
                drop_gps=self.cb_drop_gps.isChecked(),
                normalize_orientation=self.cb_orientation.isChecked(),
                rewrite_dimensions=self.cb_dimensions.isChecked(),
                overwrite=self.cb_overwrite.isChecked(),
            )
        except Exception as e:  # noqa: BLE001
            self._log(f"ERROR: {e}")
            return

        self._log(f"Saved: {res.out_path}")
        if not res.edited:
            self._log("Note: raw EXIF copy only — safety edits not applied for this recipient format.")
        for n in res.notes:
            self._log(f"Note: {n}")
        # Refresh the recipient panel to show the baked result's EXIF.
        self._show_exif(self.recipient_exif, res.out_path)

    def _log(self, msg):
        self.log.appendPlainText(msg)

    # ---- settings -----------------------------------------------------------
    def closeEvent(self, e):
        s = self.settings
        s.setValue("output_dir", self.output_dir or "")
        s.setValue("drop_gps", self.cb_drop_gps.isChecked())
        s.setValue("orientation", self.cb_orientation.isChecked())
        s.setValue("dimensions", self.cb_dimensions.isChecked())
        s.setValue("overwrite", self.cb_overwrite.isChecked())
        s.sync()
        super().closeEvent(e)

    def _load_settings(self):
        s = self.settings

        def get_bool(key, default):
            v = s.value(key, default)
            return v.lower() == "true" if isinstance(v, str) else bool(v)

        self.cb_drop_gps.setChecked(get_bool("drop_gps", False))
        self.cb_orientation.setChecked(get_bool("orientation", True))
        self.cb_dimensions.setChecked(get_bool("dimensions", True))
        self.cb_overwrite.setChecked(get_bool("overwrite", False))
        out = s.value("output_dir", "")
        if out and os.path.isdir(out):
            self.output_dir = out
            self.output_label.setText(out)


def main():
    import sys
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
