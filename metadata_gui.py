"""
Metadata Baker - desktop frontend (PySide6).

Copies EXIF from a DONOR image into a RECIPIENT image and writes a new file.
Shows a small before/after EXIF preview so you can see what travelled across,
and exposes the three safety toggles (drop GPS, normalize orientation, rewrite
stale dimension tags) discussed in metadata_core. Two further tabs edit the
common fields directly and browse/edit every raw EXIF tag.

Frontend notes
--------------
* **Donor and recipient are named on the card, not only above it.** The one
  irreversible confusion this tool offers is getting them the wrong way round -
  the recipient keeps its pixels and the donor keeps nothing. Each column says
  what it contributes, and the direction between them is drawn.

* **Every tab ends in a pinned action bar.** The Bake, Apply and Save buttons
  were the last widget in a scrolling column, so on a short window the verb was
  off-screen while all its options were visible.

* **Logs are hidden until they have something to say.** Three tabs each carried
  a permanently-visible empty log box.

The tag browser's staged-row colouring is unchanged and still comes from
`theme.state_color()` via `_tags_recolor()`: those colours are painted into the
items in code, so they do not follow a live theme switch without the
PaletteChange hook.
"""
import os
import logging

from PySide6 import QtCore, QtGui, QtWidgets

import metadata_core as mc
import theme
import ui
from theme import ensure_applied, state_color

logger = logging.getLogger(__name__)


class FileSlot(QtWidgets.QFrame):
    """One labelled image slot: what it is for, the path, and its EXIF.

    Used for the donor and the recipient. The role description lives on the
    card because "Donor" and "Recipient" are only meaningful once you know
    which one survives, and a heading above two identical columns is exactly
    where that gets lost.
    """

    chosen = QtCore.Signal(str)

    def __init__(self, title: str, role: str, icon_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("surface")
        self.setAcceptDrops(True)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(ui.SPACE_MD, ui.SPACE_MD, ui.SPACE_MD, ui.SPACE_MD)
        lay.setSpacing(ui.SPACE_SM)

        head = QtWidgets.QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(ui.SPACE_SM)
        self.glyph = QtWidgets.QLabel()
        self.glyph.setFixedSize(18, 18)
        self._icon_name = icon_name
        head.addWidget(self.glyph)
        t = QtWidgets.QLabel(title)
        t.setObjectName("card_title")
        head.addWidget(t)
        head.addStretch(1)
        lay.addLayout(head)

        role_lab = QtWidgets.QLabel(role)
        role_lab.setObjectName("empty_body")
        role_lab.setWordWrap(True)
        lay.addWidget(role_lab)

        self.path_label = QtWidgets.QLabel("Nothing selected")
        self.path_label.setObjectName("pathlabel")
        self.path_label.setWordWrap(True)
        lay.addWidget(self.path_label)

        self.btn = ui.button(f"Choose {title.lower()}…", "file")
        self.btn.clicked.connect(self._browse)
        lay.addWidget(self.btn)

        self.exif = QtWidgets.QPlainTextEdit()
        self.exif.setReadOnly(True)
        self.exif.setObjectName("log")
        self.exif.setMinimumHeight(150)
        self.exif.setPlaceholderText("EXIF appears here once an image is chosen.")
        lay.addWidget(self.exif, 1)

        self._filter = "Images (*.jpg *.jpeg *.tif *.tiff *.png *.webp)"
        self.path = None
        self.retint()

    def _browse(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, f"Choose image", "", self._filter)
        if path:
            self.set_path(path)

    def set_path(self, path: str) -> None:
        self.path = path
        self.path_label.setText(path)
        items = mc.describe_exif(path, limit=16)
        self.exif.setPlainText("\n".join(f"{k}: {v}" for k, v in items)
                               if items else "(no readable EXIF)")
        self.chosen.emit(path)

    def refresh_exif(self, path: str) -> None:
        items = mc.describe_exif(path, limit=16)
        self.exif.setPlainText("\n".join(f"{k}: {v}" for k, v in items)
                               if items else "(no readable EXIF)")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if p and os.path.isfile(p):
                self.set_path(p)
                e.acceptProposedAction()
                return

    def retint(self):
        self.glyph.setPixmap(ui.pixmap(self._icon_name, 16, theme.palette_color("ACCENT")))


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Metadata Baker")
        self.resize(1180, 760)
        _ic = theme.icon_path()
        if _ic:
            self.setWindowIcon(QtGui.QIcon(_ic))
        self.settings = QtCore.QSettings("Chaser", "PhotoTools-Metadata")

        self.donor_path = None
        self.recipient_path = None
        self.output_dir = None

        self._build_ui()
        ensure_applied()
        self._load_settings()

    # ---------------------------------------------------------------- shell
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QtWidgets.QWidget()
        bar.setObjectName("toolbar")
        bl = QtWidgets.QVBoxLayout(bar)
        bl.setContentsMargins(ui.SPACE_XL, ui.SPACE_LG, ui.SPACE_XL, ui.SPACE_MD)
        bl.setSpacing(2)
        title = QtWidgets.QLabel("Metadata Baker")
        title.setObjectName("title")
        bl.addWidget(title)
        sub = QtWidgets.QLabel("Copy EXIF between images, edit fields, or browse every raw "
                               "tag (EXIF only; IPTC/XMP not handled)")
        sub.setObjectName("subtitle")
        sub.setWordWrap(True)
        bl.addWidget(sub)
        root.addWidget(bar)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_bake_tab(), "Bake")
        self.tabs.addTab(self._build_edit_tab(), "Edit fields")
        self.tabs.addTab(self._build_tags_tab(), "All tags")
        # The tab bar stays inside its QTabWidget. Reparenting it into the
        # header strip to line the selected-tab underline up with the chrome
        # boundary does not work: QTabWidget keeps positioning its own tab bar,
        # so the moved widget was drawn at the top-left of the window, on top of
        # the title. The theme's underline tabs already read as a boundary.
        self.tabs.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.tabs, 1)
        ui.retint_tree(self)

    @staticmethod
    def _tab_shell():
        """A tab: scrolling body + a pinned action bar. Returns (tab, body, footer)."""
        tab = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        inner = QtWidgets.QWidget()
        body = QtWidgets.QVBoxLayout(inner)
        body.setContentsMargins(ui.SPACE_XL, ui.SPACE_LG, ui.SPACE_XL, ui.SPACE_LG)
        body.setSpacing(ui.SPACE_MD)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        rule = ui.divider()
        outer.addWidget(rule)
        foot_w = QtWidgets.QWidget()
        foot_w.setObjectName("statusbar")
        footer = QtWidgets.QHBoxLayout(foot_w)
        footer.setContentsMargins(ui.SPACE_XL, ui.SPACE_MD, ui.SPACE_XL, ui.SPACE_MD)
        footer.setSpacing(ui.SPACE_MD)
        outer.addWidget(foot_w)
        return tab, body, footer

    # ---------------------------------------------------------------- bake tab
    def _build_bake_tab(self):
        tab, root, footer = self._tab_shell()

        cols = QtWidgets.QHBoxLayout()
        cols.setSpacing(ui.SPACE_MD)
        self.donor = FileSlot("Donor", "Its EXIF is copied out. Its pixels are not used.",
                              "tag")
        self.donor.chosen.connect(self._on_donor)
        cols.addWidget(self.donor, 1)

        # The direction marker: which way the metadata travels. Without it the
        # two columns are symmetrical and the only cue is the word order.
        arrow = QtWidgets.QLabel()
        arrow.setAlignment(QtCore.Qt.AlignCenter)
        arrow.setFixedWidth(34)
        self._arrow = arrow
        cols.addWidget(arrow)

        self.recipient = FileSlot("Recipient",
                                  "Keeps its pixels. Receives the donor's EXIF.", "image")
        self.recipient.chosen.connect(self._on_recipient)
        cols.addWidget(self.recipient, 1)
        root.addLayout(cols, 1)

        root.addWidget(ui.section("Safety options"))
        self.cb_drop_gps = QtWidgets.QCheckBox("Drop GPS location")
        self.cb_drop_gps.setToolTip("Remove the donor's GPS coordinates so they don't "
                                    "travel onto the recipient.")
        root.addWidget(self.cb_drop_gps)

        self.cb_orientation = QtWidgets.QCheckBox("Normalize orientation (recommended)")
        self.cb_orientation.setChecked(True)
        self.cb_orientation.setToolTip(
            "Force the Orientation tag to 'Normal'. Prevents the donor's rotation "
            "tag double-rotating the recipient's already-correct pixels.")
        root.addWidget(self.cb_orientation)

        self.cb_dimensions = QtWidgets.QCheckBox(
            "Rewrite dimension tags to match recipient (recommended)")
        self.cb_dimensions.setChecked(True)
        self.cb_dimensions.setToolTip(
            "The donor's pixel-dimension EXIF tags describe the donor, not the "
            "recipient. This rewrites them to the recipient's real size so they "
            "aren't misleading. (JPEG/TIFF recipients only.)")
        root.addWidget(self.cb_dimensions)

        self.cb_overwrite = QtWidgets.QCheckBox(
            "Overwrite if output exists (otherwise appends ' (1)')")
        root.addWidget(self.cb_overwrite)

        root.addWidget(ui.section("Output"))
        out_grid = ui.FormGrid()
        out_row = QtWidgets.QHBoxLayout()
        out_row.setContentsMargins(0, 0, 0, 0)
        out_row.setSpacing(ui.SPACE_SM)
        self.output_label = QtWidgets.QLabel("(same folder as recipient)")
        self.output_label.setObjectName("pathlabel")
        self.output_label.setWordWrap(True)
        out_row.addWidget(self.output_label, 1)
        b_out = ui.button("Choose…", "folder")
        b_out.clicked.connect(self.choose_output)
        out_row.addWidget(b_out)
        holder = QtWidgets.QWidget()
        holder.setLayout(out_row)
        out_grid.add_row("Folder", holder)
        root.addLayout(out_grid)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("log")
        self.log.setFixedHeight(90)
        self.log.setVisible(False)
        root.addWidget(self.log)
        root.addStretch(1)

        self.status = ui.StatusStrip()
        footer.addWidget(self.status, 1)
        self.run_btn = ui.primary_button("Bake metadata", "tag")
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self.bake)
        footer.addStretch(1)
        self.run_btn.setMinimumWidth(180)
        footer.addWidget(self.run_btn, 0)
        return tab

    def _on_donor(self, path):
        self.donor_path = path
        self._refresh_bake_ready()

    def _on_recipient(self, path):
        self.recipient_path = path
        self._refresh_bake_ready()

    def _refresh_bake_ready(self):
        """Bake needs both sides; say which one is missing rather than
        waiting for the click to find out."""
        ready = bool(self.donor_path and self.recipient_path)
        self.run_btn.setEnabled(ready)
        if ready:
            self.status.clear()
        elif self.donor_path:
            self.status.show_message("Choose a recipient image.", "info")
        elif self.recipient_path:
            self.status.show_message("Choose a donor image.", "info")
        else:
            self.status.clear()

    # ---------------------------------------------------------------- edit tab
    def _build_edit_tab(self):
        tab, root, footer = self._tab_shell()

        self.edit_target = None
        self.edit_is_dir = False

        root.addWidget(ui.section("Image or folder"))
        b_img = ui.button("Choose image…", "file")
        b_img.clicked.connect(self.edit_choose_image)
        b_dir = ui.button("Choose folder… (batch)", "folder")
        b_dir.clicked.connect(self.edit_choose_folder)
        root.addLayout(ui.hbox(b_img, b_dir, None))

        self.edit_target_label = QtWidgets.QLabel("Nothing selected (JPEG / TIFF only)")
        self.edit_target_label.setObjectName("pathlabel")
        self.edit_target_label.setWordWrap(True)
        root.addWidget(self.edit_target_label)

        root.addWidget(ui.section("Fields"))
        note = QtWidgets.QLabel("A blank field is left unchanged - it does not clear the tag.")
        note.setObjectName("empty_body")
        root.addWidget(note)

        form = ui.FormGrid()
        self.ed_artist = QtWidgets.QLineEdit()
        self.ed_copyright = QtWidgets.QLineEdit()
        self.ed_desc = QtWidgets.QLineEdit()
        form.add_row("Artist / creator", self.ed_artist)
        form.add_row("Copyright", self.ed_copyright)
        form.add_row("Description", self.ed_desc)
        self.ed_shift = QtWidgets.QSpinBox()
        self.ed_shift.setRange(-100000, 100000)
        self.ed_shift.setSuffix(" min")
        self.ed_shift.setToolTip("Adjust DateTimeOriginal/Digitized and DateTime "
                                 "(e.g. fix a wrong clock or a timezone offset).")
        form.add_row("Shift capture time", self.ed_shift)
        root.addLayout(form)

        self.ed_strip_gps = QtWidgets.QCheckBox("Remove GPS (location)")
        root.addWidget(self.ed_strip_gps)
        self.ed_overwrite = QtWidgets.QCheckBox(
            "Overwrite original (otherwise writes <name>_meta)")
        root.addWidget(self.ed_overwrite)

        self.edit_log = QtWidgets.QPlainTextEdit()
        self.edit_log.setReadOnly(True)
        self.edit_log.setObjectName("log")
        self.edit_log.setFixedHeight(110)
        self.edit_log.setVisible(False)
        root.addWidget(self.edit_log)
        root.addStretch(1)

        self.edit_status = ui.StatusStrip()
        footer.addWidget(self.edit_status, 1)
        self.edit_apply_btn = ui.primary_button("Apply", "check")
        # Disabled until a target exists, the same as Bake on the first tab. An
        # enabled primary button whose only behaviour is to explain that it
        # cannot run is an invitation to a dead end.
        self.edit_apply_btn.setEnabled(False)
        self.edit_apply_btn.clicked.connect(self.apply_edits)
        footer.addStretch(1)
        self.edit_apply_btn.setMinimumWidth(180)
        footer.addWidget(self.edit_apply_btn, 0)
        return tab

    # ---- edit tab handlers --------------------------------------------------
    _EDIT_FILTER = "JPEG / TIFF (*.jpg *.jpeg *.tif *.tiff)"

    def edit_choose_image(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose image", "", self._EDIT_FILTER)
        if not path:
            return
        self.edit_target = path
        self.edit_is_dir = False
        self.edit_target_label.setText(path)
        self.edit_apply_btn.setEnabled(True)
        fields = mc.read_fields(path)
        self.ed_artist.setText(fields["artist"])
        self.ed_copyright.setText(fields["copyright"])
        self.ed_desc.setText(fields["description"])
        self.edit_status.show_message(
            "Loaded current fields. A blank field stays unchanged.", "info")

    def edit_choose_folder(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose folder")
        if not path:
            return
        self.edit_target = path
        self.edit_is_dir = True
        self.edit_target_label.setText(f"{path}   (batch — every JPEG/TIFF)")
        self.edit_apply_btn.setEnabled(True)
        self.edit_status.show_message(
            "Batch mode: the fields you fill are written to every JPEG/TIFF.", "warn")

    def apply_edits(self):
        if not self.edit_target:
            self.edit_status.show_message("Choose an image or a folder first.", "warn")
            return

        def val(line):
            t = line.text().strip()
            return t if t else None        # blank -> leave the field unchanged

        edits = dict(artist=val(self.ed_artist), copyright=val(self.ed_copyright),
                     description=val(self.ed_desc), strip_gps=self.ed_strip_gps.isChecked(),
                     datetime_shift_sec=self.ed_shift.value() * 60)
        self.edit_log.setVisible(True)
        try:
            if self.edit_is_dir:
                from filemanager import get_directory_files
                globs = ["*.jpg", "*.jpeg", "*.tif", "*.tiff",
                         "*.JPG", "*.JPEG", "*.TIF", "*.TIFF"]
                paths = get_directory_files(self.edit_target, False, globs, [])
                if not paths:
                    self.edit_status.show_message(
                        "No JPEG/TIFF files found in that folder.", "warn")
                    return
                results = mc.stamp_files(paths, **edits)
                ok = sum(1 for r in results if r.edited)
                self._elog(f"Edited {ok}/{len(results)} file(s).")
                self.edit_status.show_message(f"Edited {ok} of {len(results)} files",
                                              "ok" if ok == len(results) else "warn")
                for r in results:
                    if not r.edited:
                        self._elog(f"  {os.path.basename(r.out_path)}: {'; '.join(r.notes)}")
            else:
                res = mc.edit_metadata(self.edit_target, None,
                                       overwrite=self.ed_overwrite.isChecked(), **edits)
                self._elog(f"Saved: {os.path.basename(res.out_path)}")
                self.edit_status.show_message(f"Saved {os.path.basename(res.out_path)}", "ok")
                for n in res.notes:
                    self._elog(f"  {n}")
        except Exception as e:  # noqa: BLE001
            self._elog(f"ERROR: {e}")
            self.edit_status.show_message(str(e), "error")

    def _elog(self, msg):
        self.edit_log.setVisible(True)
        self.edit_log.appendPlainText(msg)

    # ---- "All tags" tab (exiftool-style raw browser/editor) ------------------
    # Row-state colours come from theme.state_color() so they stay readable in
    # both light and dark mode.

    def _build_tags_tab(self):
        tab, root, footer = self._tab_shell()

        self.tags_path = None
        self.tags_edits = {}         # (ifd, tag_id) -> new text (unsaved)
        self.tags_deletions = set()  # (ifd, tag_id) staged for deletion

        b_img = ui.button("Choose image…", "file")
        b_img.clicked.connect(self.tags_choose_image)
        self.tags_filter = QtWidgets.QLineEdit()
        self.tags_filter.setPlaceholderText("Filter by tag name, IFD or value…")
        self.tags_filter.textChanged.connect(self._tags_apply_filter)
        self.tags_count = ui.Chip("0")
        root.addLayout(ui.hbox(b_img, self.tags_filter, self.tags_count))

        self.tags_path_label = QtWidgets.QLabel("Nothing loaded (JPEG / TIFF only)")
        self.tags_path_label.setObjectName("pathlabel")
        self.tags_path_label.setWordWrap(True)
        root.addWidget(self.tags_path_label)

        self.tags_tree = QtWidgets.QTreeWidget()
        self.tags_tree.setColumnCount(4)
        self.tags_tree.setHeaderLabels(["Tag", "IFD", "Type", "Value"])
        self.tags_tree.setRootIsDecorated(False)
        self.tags_tree.setAlternatingRowColors(True)
        self.tags_tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        # Only the Value column of editable rows may be edited - triggers are
        # off and we open the editor ourselves on double-click.
        self.tags_tree.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tags_tree.itemDoubleClicked.connect(self._tags_double_clicked)
        self.tags_tree.itemChanged.connect(self._tags_item_changed)
        self.tags_tree.header().setStretchLastSection(True)
        self.tags_tree.setMinimumHeight(260)
        root.addWidget(self.tags_tree, 1)

        b_del = ui.button("Delete selected", "close")
        b_del.setToolTip("Stage the selected tags for deletion (click again to undo). "
                         "Nothing is written until Save.")
        b_del.clicked.connect(self._tags_delete_selected)
        b_rev = ui.button("Revert", "reset")
        b_rev.clicked.connect(self._tags_revert)
        self.tags_overwrite = QtWidgets.QCheckBox(
            "Overwrite original (otherwise writes <name>_meta)")
        root.addLayout(ui.hbox(b_del, b_rev, None, self.tags_overwrite))

        self.tags_log = QtWidgets.QPlainTextEdit()
        self.tags_log.setReadOnly(True)
        self.tags_log.setObjectName("log")
        self.tags_log.setFixedHeight(80)
        self.tags_log.setVisible(False)
        root.addWidget(self.tags_log)

        self.tags_status = ui.StatusStrip()
        footer.addWidget(self.tags_status, 1)
        self.tags_save_btn = ui.primary_button("Save changes", "check")
        self.tags_save_btn.setEnabled(False)
        self.tags_save_btn.clicked.connect(self._tags_save)
        footer.addStretch(1)
        self.tags_save_btn.setMinimumWidth(180)
        footer.addWidget(self.tags_save_btn, 0)
        return tab

    def tags_choose_image(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose image", "", self._EDIT_FILTER)
        if path:
            self._tags_load(path)

    def _tags_load(self, path):
        try:
            entries = mc.load_all_tags(path)
        except Exception as e:  # noqa: BLE001
            self._tlog(f"ERROR: {e}")
            self.tags_status.show_message(str(e), "error")
            return
        self.tags_path = path
        self.tags_edits.clear()
        self.tags_deletions.clear()
        self.tags_path_label.setText(path)
        self.tags_count.setText(f"{len(entries)} tags")

        t = self.tags_tree
        t.blockSignals(True)       # populating must not fire itemChanged
        t.clear()
        for e in entries:
            it = QtWidgets.QTreeWidgetItem([e.name, e.ifd, e.type_name, e.value])
            it.setData(0, QtCore.Qt.UserRole, (e.ifd, e.tag_id))
            it.setData(0, QtCore.Qt.UserRole + 1, e.editable)
            it.setData(3, QtCore.Qt.UserRole, e.value)      # original text
            if e.editable:
                it.setFlags(it.flags() | QtCore.Qt.ItemIsEditable)
            else:
                it.setToolTip(3, e.note)
                brush = QtGui.QBrush(QtGui.QColor(state_color("viewonly")))
                for c in range(4):
                    it.setForeground(c, brush)
            t.addTopLevelItem(it)
        for c in range(3):
            t.resizeColumnToContents(c)
        t.blockSignals(False)
        self._tags_apply_filter(self.tags_filter.text())
        self._refresh_tags_dirty()
        self.tags_status.show_message(
            "Double-click a value to edit. Nothing is written until Save.", "info")

    def _refresh_tags_dirty(self):
        """Enable Save only when there is something to save, and say how much.

        The old Save reported "No changes to save." after the click. The count
        of staged changes is knowable before it, and is also the only running
        indication that a staged deletion registered at all.
        """
        n = len(self.tags_edits) + len(self.tags_deletions)
        self.tags_save_btn.setEnabled(bool(n))
        self.tags_save_btn.setText(
            f"Save {n} change{'s' if n != 1 else ''}" if n else "Save changes")

    def _tags_double_clicked(self, item, column):
        if column == 3 and item.data(0, QtCore.Qt.UserRole + 1):
            self.tags_tree.editItem(item, 3)

    def _tags_item_changed(self, item, column):
        if column != 3:
            return
        key = item.data(0, QtCore.Qt.UserRole)
        original = item.data(3, QtCore.Qt.UserRole)
        text = item.text(3)
        if text == original:
            self.tags_edits.pop(key, None)
            item.setData(3, QtCore.Qt.ForegroundRole, None)   # back to theme default
        else:
            self.tags_edits[key] = text
            item.setForeground(3, QtGui.QBrush(QtGui.QColor(state_color("modified"))))
        self._refresh_tags_dirty()

    def _tags_delete_selected(self):
        for it in self.tags_tree.selectedItems():
            key = it.data(0, QtCore.Qt.UserRole)
            name = it.text(0)
            if key in mc._STRUCTURAL_TAGS or key[1] == -1:
                self._tlog(f"{name} is structural / derived and can't be deleted.")
                self.tags_status.show_message(
                    f"{name} is structural / derived and can't be deleted.", "warn")
                continue
            font = it.font(0)
            if key in self.tags_deletions:                    # toggle: un-stage
                self.tags_deletions.discard(key)
                font.setStrikeOut(False)
                editable = it.data(0, QtCore.Qt.UserRole + 1)
                brush = (QtGui.QBrush(QtGui.QColor(state_color("viewonly"))) if not editable
                         else None)
                for c in range(4):
                    it.setFont(c, font)
                    if brush is None:
                        it.setData(c, QtCore.Qt.ForegroundRole, None)
                    else:
                        it.setForeground(c, brush)
            else:                                             # stage deletion
                self.tags_deletions.add(key)
                self.tags_edits.pop(key, None)                # deletion trumps an edit
                font.setStrikeOut(True)
                brush = QtGui.QBrush(QtGui.QColor(state_color("deleted")))
                for c in range(4):
                    it.setFont(c, font)
                    it.setForeground(c, brush)
        self._refresh_tags_dirty()

    def _tags_revert(self):
        if self.tags_path:
            self._tags_load(self.tags_path)
            self.tags_status.show_message("Reverted to the file's saved state.", "info")

    def _tags_apply_filter(self, text):
        text = text.lower().strip()
        t = self.tags_tree
        shown = 0
        for i in range(t.topLevelItemCount()):
            it = t.topLevelItem(i)
            hit = (not text or text in it.text(0).lower()
                   or text in it.text(1).lower() or text in it.text(3).lower())
            it.setHidden(not hit)
            shown += int(hit)
        total = t.topLevelItemCount()
        self.tags_count.setText(f"{shown} of {total}" if text else f"{total} tags")

    def changeEvent(self, e):
        # A live theme switch changes the app palette; re-derive the baked-in
        # row colours (modified/deleted/view-only) so they match the new mode,
        # and repaint the drawn glyphs for the same reason.
        if e.type() in (QtCore.QEvent.PaletteChange, QtCore.QEvent.StyleChange):
            self._tags_recolor()
            ui.retint_tree(self)
            if getattr(self, "_arrow", None) is not None:
                self._arrow.setPixmap(
                    ui.pixmap("chevron_right", 20, theme.palette_color("ACCENT")))
        super().changeEvent(e)

    def _tags_recolor(self):
        tree = getattr(self, "tags_tree", None)   # changeEvent can fire pre-build
        if tree is None:
            return
        for i in range(tree.topLevelItemCount()):
            it = tree.topLevelItem(i)
            key = it.data(0, QtCore.Qt.UserRole)
            editable = it.data(0, QtCore.Qt.UserRole + 1)
            if key in self.tags_deletions:
                brush = QtGui.QBrush(QtGui.QColor(state_color("deleted")))
                for c in range(4):
                    it.setForeground(c, brush)
            elif not editable:
                brush = QtGui.QBrush(QtGui.QColor(state_color("viewonly")))
                for c in range(4):
                    it.setForeground(c, brush)
            elif key in self.tags_edits:
                it.setForeground(3, QtGui.QBrush(QtGui.QColor(state_color("modified"))))

    def _tags_save(self):
        if not self.tags_path:
            self.tags_status.show_message("Choose an image first.", "warn")
            return
        if not self.tags_edits and not self.tags_deletions:
            self.tags_status.show_message("No changes to save.", "info")
            return
        try:
            res = mc.apply_tag_edits(self.tags_path, dict(self.tags_edits),
                                     deletions=set(self.tags_deletions),
                                     overwrite=self.tags_overwrite.isChecked())
        except Exception as e:  # noqa: BLE001
            self._tlog(f"ERROR: {e}")
            self.tags_status.show_message(str(e), "error")
            return
        self._tlog(f"Saved: {os.path.basename(res.out_path)}")
        for n in res.notes:
            self._tlog(f"  {n}")
        saved = os.path.basename(res.out_path)
        self._tags_load(res.out_path)   # continue working on the written file
        self.tags_status.show_message(f"Saved {saved}", "ok")

    def _tlog(self, msg):
        self.tags_log.setVisible(True)
        self.tags_log.appendPlainText(msg)

    # ---- selection ----------------------------------------------------------
    _FILTER = "Images (*.jpg *.jpeg *.tif *.tiff *.png *.webp)"

    def choose_output(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose output folder")
        if path:
            self.output_dir = path
            self.output_label.setText(path)

    # ---- bake ---------------------------------------------------------------
    def bake(self):
        if not self.donor_path:
            self.status.show_message("Choose a donor image.", "warn")
            return
        if not self.recipient_path:
            self.status.show_message("Choose a recipient image.", "warn")
            return

        rec_dir = os.path.dirname(os.path.abspath(self.recipient_path))
        out_dir = self.output_dir or rec_dir
        base, ext = os.path.splitext(os.path.basename(self.recipient_path))
        out_path = os.path.join(out_dir, f"{base}_meta{ext}")

        self.log.setVisible(True)
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
            self.status.show_message(str(e), "error")
            return

        self._log(f"Saved: {res.out_path}")
        if not res.edited:
            self._log("Note: raw EXIF copy only — safety edits not applied for "
                      "this recipient format.")
            self.status.show_message(
                f"Saved {os.path.basename(res.out_path)} — raw EXIF copy only, "
                "safety edits skipped for this format.", "warn")
        else:
            self.status.show_message(f"Saved {os.path.basename(res.out_path)}", "ok")
        for n in res.notes:
            self._log(f"Note: {n}")
        # Refresh the recipient panel to show the baked result's EXIF.
        self.recipient.refresh_exif(res.out_path)

    def _log(self, msg):
        self.log.setVisible(True)
        self.log.appendPlainText(msg)

    # ---- settings -----------------------------------------------------------
    def closeEvent(self, e):
        s = self.settings
        s.setValue("output_dir", self.output_dir or "")
        s.setValue("drop_gps", self.cb_drop_gps.isChecked())
        s.setValue("orientation", self.cb_orientation.isChecked())
        s.setValue("dimensions", self.cb_dimensions.isChecked())
        s.setValue("overwrite", self.cb_overwrite.isChecked())
        s.setValue("tags_overwrite", self.tags_overwrite.isChecked())
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
        self.tags_overwrite.setChecked(get_bool("tags_overwrite", False))
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
