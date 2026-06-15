# Chaser's Shenanigans

A small desktop suite of photo utilities, behind one launcher. Three tools:

- **PhotoBorder** — add clean borders, EXIF strips and colour palettes to photos,
  batching a whole folder in parallel with a live preview.
- **Format Converter** — convert images between JPEG, PNG, WEBP, TIFF, BMP and
  (where available) HEIF/HEIC/HIF, preserving EXIF and DPI wherever the target
  format allows.
- **Metadata Baker** — copy EXIF from one image into another (e.g. restore the
  original camera metadata onto an edited export), with safety toggles.

Built for photographers who want a tidy, consistent export workflow — for
example stage, dance and portrait work straight off the camera.

---

## Credits

This project is built on top of [**photoborder** by stevequinn](https://github.com/stevequinn/photoborder),
which provides the original border / EXIF / palette engine and CLI. That original
work is (c) 2024 stevequinn and released under the MIT License.

**Chaser's Shenanigans** (formerly *Chaser's PhotoBorder*) extends it with a
desktop launcher, two additional tools, and a number of features listed below.
The project remains under stevequinn's original MIT License — his copyright
notice is preserved in the `LICENSE` file, as MIT requires.

---

## Installation

### Windows (recommended)

1. Install **Python 3.10+** from <https://www.python.org/downloads/> and tick
   *"Add python.exe to PATH"* in the installer.
2. Double-click **`install.bat`**. It creates an isolated virtual environment in
   `.venv`, installs all dependencies into it (so your global Python stays
   clean), and reports whether optional HEIF support loaded.
3. Double-click **`run.bat`** to start the app.

If `run.bat` does nothing when double-clicked, use **`run_debug.bat`** instead —
it keeps a console window open so you can see any startup error.

> **HEIF note (especially on Arm64 Windows):** `pillow-heif` ships prebuilt
> wheels for most platforms, but a wheel may not exist for Windows on Arm
> (e.g. a Snapdragon laptop). If its install fails, **the app still runs** — the
> HEIF/HEIC/HIF options simply disappear from the converter and a notice is
> shown. Every other format keeps working. Run `install.bat` on each machine to
> confirm what that machine supports.

### Desktop shortcuts & taskbar icon

A `.bat` file can't carry its own icon — Windows always shows the generic
batch-script icon for the file itself. To get a real icon on a launcher, use a
**shortcut**. Double-click **`create_shortcuts.bat`** once and it generates two,
in the project folder:

- **`Chaser's Shenanigans.lnk`** — launches the app with no console window and
  the app icon.
- **`Install.lnk`** — runs `install.bat`, with an install-themed icon.

Drag either onto your Desktop, or right-click the running app on the taskbar and
choose *Pin to taskbar*. The app sets a Windows *AppUserModelID*, so the taskbar
shows the app's own icon and groups its windows under it — rather than falling
back to Python's generic icon, as a `pythonw`-hosted app otherwise would.

### Any OS (manual)

```bash
pip install -r requirements.txt
python launcher.py
```

Dependencies: Pillow, extcolors, PySide6, pillow-heif, piexif (and pytest for
the tests).

---

## Usage

Launch the app (`run.bat`, or `python launcher.py`). The home window shows three
cards — click one to open that tool in its own window. The launcher stays open,
so you can hop between tools.

Each tool also runs standalone if you prefer:

```bash
python photoborder_gui.py
python converter_gui.py
python metadata_gui.py
```

### PhotoBorder

Choose an input file or folder and an output folder, pick a border type and
aspect ratio, toggle EXIF / palette / options, check the live preview, then
**Process**. A folder runs in parallel with a per-file progress bar; a single
file runs sequentially with per-stage progress. **Cancel** now stops a running
batch promptly (it drops queued files; files already in flight finish, since a
worker can't be killed mid-task).

PhotoBorder also keeps its original command-line interface:

```bash
python main.py -t p -e -p -o output_folder Pictures\Waiting
```

| Option | Description |
| --- | --- |
| `-e, --exif` | Print photo EXIF data on the border |
| `-p, --palette` | Add a colour palette to the border |
| `-t, --border_type` | `p` polaroid, `s` small, `m` medium, `l` large, `i` instagram |
| `-r, --recursive` | Recurse into sub-folders |
| `-o, --output` | Output directory (default: a `bordered` folder next to the input) |
| `--ratio` | `native`, `1:1`, `4:5`, `5:4`, `3:2`, `2:3`, `16:9`, `9:16`, or custom `W:H` |
| `--no-overwrite` | Append ` (1)`, ` (2)`, ... instead of overwriting existing outputs |
| `-f / -fv` | Regular font file / variant index |
| `-fb / -fbv` | Bold font file / variant index |
| `--include / --exclude` | Glob patterns for which files to process |

### Format Converter

Choose a file or folder, choose an output folder, pick the target format, set the
quality (for lossy formats), and optionally preserve EXIF. Converts one image or
a whole folder. Output mirrors the input's sub-folder structure, and a
*don't-overwrite* option appends ` (1)`, ` (2)`, ... rather than clobbering.

**Format and metadata support:**

| | JPEG | PNG | WEBP | TIFF | BMP | HEIF/HEIC/HIF |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| Read (input) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (if `pillow-heif`) |
| Write (output) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (if `pillow-heif`) |
| EXIF preserved | ✓ | ✓ | ✓ | ✓ | — | ✓ |
| DPI preserved | ✓ | ✓ | ✓\* | ✓ | ✓ | ✓\* |

`*` WEBP and HEIF have no native DPI field, so the DPI is written into their
**EXIF resolution tags** instead — print labs and EXIF-aware viewers read it
correctly. (Source DPI is read from the native field *or* from EXIF, so a phone
HEIF whose resolution lives only in EXIF is handled too.) The only case where DPI
can't be preserved is a source that genuinely has no resolution metadata at all.

### Metadata Baker

Pick a **donor** image (copy metadata *from*) and a **recipient** image (keep
*these* pixels), see a short EXIF preview of each, set the options, and **Bake**.
The result is written to a new file (`<recipient>_meta.<ext>`).

It copies **EXIF only** (IPTC/XMP are not copied). Because blindly copying a
donor's EXIF onto a different image is a known footgun, three toggles exist:

- **Normalize orientation** *(default on)* — forces the Orientation tag to
  Normal, so the donor's rotation doesn't double-rotate the recipient's
  already-correct pixels.
- **Rewrite dimensions** *(default on)* — the donor's pixel-dimension tags
  describe the donor; this rewrites them to the recipient's real size.
- **Drop GPS** *(default off)* — so the donor's location doesn't travel onto the
  recipient.

Surgical edits apply to JPEG/TIFF recipients (via `piexif`). For other recipient
formats it falls back to a raw EXIF-block copy and tells you the edits were
skipped.

---

## Updates

The suite updates itself from this repository. On launch it asks GitHub whether
`main` has moved on; if so, it offers to download the latest source, overlay it
onto your install, and restart.

- **Opt-in:** you're asked before anything is downloaded.
- **Safe to be offline:** if GitHub can't be reached, or anything goes wrong
  mid-update, the version already on disk just starts as normal.
- **Dependencies:** if an update changes `requirements.txt`, the updater
  re-installs into your `.venv` automatically (and tells you to run
  `install.bat` if no `.venv` is found).
- **Your files are kept:** the update overlays code only — your `.venv`, scratch
  photo folders and shortcuts are left alone. The synced commit is tracked in a
  per-machine `.update_state.json` (git-ignored). The first launch on a new copy
  syncs to the latest commit automatically; after that it just checks and asks.

---

## Project structure

The GUI is kept separate from a GUI-agnostic processing core, so the same logic
serves the desktop app, the CLI, and parallel workers.

| File | Role |
| --- | --- |
| `launcher.py` | Suite home window; opens the three tools. Entry point for the app. |
| `updater.py` | Checks GitHub on launch and self-updates the suite from this repo. |
| `theme.py` | Shared dark stylesheet + icon path resolver. |
| `photoborder_gui.py` | PhotoBorder desktop UI (parallel batch + live preview). |
| `core.py`, `border.py`, `palette.py`, `exif.py`, `text.py`, `worker.py`, `filemanager.py` | PhotoBorder engine (unchanged from the original). |
| `main.py` | PhotoBorder command-line entry point. |
| `converter_core.py` / `converter_gui.py` | Format conversion (logic / UI). |
| `metadata_core.py` / `metadata_gui.py` | EXIF baking (logic / UI). |
| `install.bat` / `run.bat` / `run_debug.bat` | Windows install and launch. |
| `create_shortcuts.bat` / `create_shortcuts.ps1` | Generate app + installer shortcuts with their icons. |
| `icon.ico` / `icon.png` | App icon. |
| `install.ico` / `install.png` | Installer-shortcut icon. |
| `fonts/` | Roboto (Regular & Medium) used by PhotoBorder's EXIF strip. |

---

## Fonts

Roboto (Regular, Medium, Bold) lives in `fonts/`. Add other TrueType fonts there
and select them with PhotoBorder's `-f` / `-fb` options.

---

## Testing

```bash
pytest -s ./tests
```

The processing cores (`converter_core.py`, `metadata_core.py`, and the
PhotoBorder pipeline) are designed to be testable without a display.

---

## License

MIT License.

- (c) 2024 stevequinn — original [photoborder](https://github.com/stevequinn/photoborder) author.
- (c) 2026 PufferfishGaming/Stormchaser Photography — Chaser's Shenanigans fork and additional features.

Both are released under the same MIT terms. See [`LICENSE`](LICENSE). Under MIT,
stevequinn's original copyright notice is retained; the fork's notice is added
alongside it, not in place of it.
