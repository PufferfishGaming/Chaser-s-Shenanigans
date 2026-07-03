# Chaser's Shenanigans

A small desktop suite of photo utilities, behind one launcher. Five tools:

- **PhotoBorder** — add clean borders, EXIF strips and colour palettes to photos,
  batching a whole folder in parallel with a live preview.
- **Format Converter** — convert images between JPEG, PNG, WEBP, TIFF, BMP and
  (where available) HEIF/HEIC/HIF, with optional resize, metadata/GPS stripping
  and pattern-based renaming, preserving EXIF and DPI wherever the target allows.
- **Metadata** — copy EXIF from one image into another (restore camera metadata
  onto an edited export), edit fields directly (artist, copyright, dates, GPS)
  on a single file or a whole folder, *and* browse and edit every raw EXIF tag,
  exiftool-style.
- **Astro Stacker** — combine a night-sky sequence into one image: lock onto the
  stars for a sharp sky over a smeared foreground, or onto the foreground for
  sharp ground under trailing stars. Reads RAW (incl. DNG), exports to 8-bit
  formats plus 16-bit / 32-bit-float TIFF and FITS.
- **Quick Edit** — fast single-image adjustments with a live preview: white
  balance, light-pollution gradient removal and one-click looks. RAW in, 8/16-bit
  out.

Built for photographers who want a tidy, consistent workflow — from night-sky
sequences to everyday shoots straight off the camera.

<div align="center">

[![Download for Windows](https://img.shields.io/badge/Windows-Download_the_installer-2ea44f?style=for-the-badge)](https://github.com/PufferfishGaming/Chaser-s-Shenanigans/releases/download/Installer/install-chasers-shenanigans.bat)

One click, one file. It installs Python if needed, downloads the latest
version, and creates your shortcuts. Re-run it any time to update or repair.

</div>

---

## Credits

This project is built on top of [**photoborder** by stevequinn](https://github.com/stevequinn/photoborder),
which provides the original border / EXIF / palette engine and CLI. That original
work is (c) 2024 stevequinn and released under the MIT License.

**Chaser's Shenanigans** (formerly *Chaser's PhotoBorder*) extends it with a
desktop launcher, four additional tools, a self-updater, and the features listed
below. The project remains under stevequinn's original MIT License — his
copyright notice is preserved in the `LICENSE` file, as MIT requires.

---

## Installation

### Windows (recommended)

1. **[Download the installer](https://github.com/PufferfishGaming/Chaser-s-Shenanigans/releases/download/Installer/install-chasers-shenanigans.bat)**
   — a single `install-chasers-shenanigans.bat`. (Your browser may warn that
   `.bat` files can harm your computer — that's a blanket warning for all
   script files. Choose *Keep*.)
2. **Double-click it.** It walks through everything on its own:
   - installs **Python 3.10+** for you if it isn't already there (official
     python.org installer, x64 or ARM64 auto-detected),
   - asks **where to install** (Enter accepts the default under your user
     folder — pick somewhere you can write to without admin rights, since the
     app updates itself by writing into its own folder),
   - downloads the **latest version** straight from this repository,
   - sets up an isolated `.venv` and installs all dependencies,
   - creates **Start Menu and Desktop shortcuts**, then launches the app.
3. That's it. From then on, start the app from its shortcut. The app keeps
   itself up to date (see [Updates](#updates)); the *Update Chaser's
   Shenanigans* Start Menu shortcut re-runs the installer as a manual
   update / repair if you ever need it.

### Windows (from source)

If you'd rather clone or download this repository yourself:

1. Install **Python 3.10+** from <https://www.python.org/downloads/> and tick
   *"Add python.exe to PATH"* in the installer.
2. Double-click **`install.bat`**. It creates an isolated virtual environment in
   `.venv`, installs all dependencies into it (so your global Python stays
   clean), and reports whether optional components (HEIF, RAW) loaded.
3. Double-click **`run.bat`** to start the app.

If `run.bat` does nothing when double-clicked, use **`run_debug.bat`** instead —
it keeps a console window open so you can see any startup error.

> **Optional components degrade gracefully.** Some features ride on packages that
> may not have a prebuilt wheel for every platform (notably Windows on Arm):
>
> - **`pillow-heif`** → HEIF/HEIC/HIF read & write in the Converter.
> - **`rawpy`** → RAW/DNG input for the Astro Stacker and Quick Edit.
> - **`tifffile`** → 16-bit / 32-bit-float TIFF export from the Stacker.
> - **`astropy`** → FITS export from the Stacker.
>
> If any of these can't install, **the app still runs** — the relevant option
> simply disappears and a notice is shown. Everything else keeps working. Run
> `install.bat` on each machine to confirm what that machine supports.

### Desktop shortcuts & taskbar icon

*(The one-click installer creates Start Menu and Desktop shortcuts for you —
this section is for source installs.)*

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

Core dependencies: Pillow, extcolors, PySide6, pillow-heif, piexif (and pytest
for the tests). The Astro Stacker and Quick Edit also use numpy and scikit-image
(which brings scipy) — used for star registration in the stacker and for the
gradient-removal background model in Quick Edit — plus optional rawpy (RAW
input), tifffile (16/32-bit TIFF) and astropy (FITS). All install from prebuilt
wheels — no C compiler needed — and each degrades gracefully if its wheel is
missing on a given machine. (`astroalign` is supported too if you install it for
the best sparse-field star matching, but it needs a C compiler, so it isn't
required.)

---

## Usage

Launch the app (`run.bat`, or `python launcher.py`). The home window shows five
cards — click one to open that tool in its own window. The launcher stays open,
so you can hop between tools. A tool whose optional dependency is missing shows a
disabled card explaining what to install, while the others keep working.

**Light / dark mode.** The suite follows your Windows theme out of the box. The
sun/moon button in the launcher footer (next to *Check for updates*) toggles it
manually — a moon means dark mode is on, a sun means light. The switch applies
instantly to every open tool window, and your choice is remembered.

Each tool also runs standalone if you prefer:

```bash
python photoborder_gui.py
python converter_gui.py
python metadata_gui.py
python stacker_gui.py
python quickedit_gui.py
```

### PhotoBorder

Choose an input file or folder and an output folder, pick a border type and
aspect ratio, toggle EXIF / palette / options, check the live preview, then
**Process**. A folder runs in parallel with a per-file progress bar; a single
file runs sequentially with per-stage progress. **Cancel** stops a running batch
promptly (it drops queued files; files already in flight finish, since a worker
can't be killed mid-task).

PhotoBorder also keeps its original command-line interface:

```bash
python main.py -t p -e -p -o output_folder Pictures\Waiting
```

| Option | Description |
| --- | --- |
| `-e, --exif` | Print photo EXIF data on the border |
| `-p, --palette` | Add a colour palette to the border |
| `-t, --border_type` | `p` polaroid, `s` small, `m` medium, `l` large |
| `-r, --recursive` | Recurse into sub-folders |
| `-o, --output` | Output directory (default: a `bordered` folder next to the input) |
| `--ratio` | `native`, `1:1`, `4:5`, `5:4`, `3:2`, `2:3`, `16:9`, `9:16`, or custom `W:H` |
| `--no-overwrite` | Append ` (1)`, ` (2)`, ... instead of overwriting existing outputs |
| `-f / -fv` | Regular font file / variant index |
| `-fb / -fbv` | Bold font file / variant index |
| `--include / --exclude` | Glob patterns for which files to process |

### Format Converter

Choose a file or folder and an output folder, pick the target format, set the
quality (for lossy formats), and run. Output mirrors the input's sub-folder
structure, and a *don't-overwrite* option appends ` (1)`, ` (2)`, ... rather than
clobbering.

Options:

- **Convert to** — JPEG, PNG, WEBP, TIFF, BMP, or HEIF (when `pillow-heif` is
  present). Quality slider applies to the lossy formats.
- **Preserve EXIF metadata** *(default on)* — uncheck to strip **all** metadata.
- **Remove GPS only** — keep the rest of the EXIF but surgically drop the
  location block. (Only relevant while preserving EXIF.)
- **Resize: longest edge to N px** — downscale so the longest side is at most N
  pixels. Never upscales; off by default.
- **Rename** *(optional pattern)* — build output names from tokens: `{name}`
  (original stem), `{n}` / `{n:03d}` (1-based index), `{date}` (today). Blank
  keeps the original name.
- **Don't overwrite existing files** — append ` (1)`, ` (2)`, ...

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

### Metadata

Three tabs.

**Bake (copy EXIF).** Pick a **donor** image (copy metadata *from*) and a
**recipient** image (keep *these* pixels), see a short EXIF preview of each, set
the options, and **Bake**. The result is written to a new file
(`<recipient>_meta.<ext>`). It copies **EXIF only** (IPTC/XMP are not copied).
Because blindly copying a donor's EXIF onto a different image is a known footgun,
three toggles exist:

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

**Edit fields.** Choose a single image (its current values prefill the fields) or
a whole folder (batch). Set any of:

- **Artist / creator**, **Copyright**, **Description** — blank fields are left
  unchanged, so you can stamp just one field (e.g. copyright) across a folder.
- **Remove GPS** — drop the location block.
- **Shift capture time** — adjust the capture timestamps by ± minutes (fix a
  wrong camera clock or a timezone offset).

Edits write to a new `<name>_meta` file by default, or overwrite the original if
you tick it. JPEG edits are **lossless** — the file is copied and only its EXIF
segment is rewritten, never re-compressed (TIFF re-saves losslessly). JPEG/TIFF
only; other formats are declined with a clear message.

**All tags.** An exiftool-style raw browser: every EXIF tag in the file, across
all IFDs, with its name, type and value — filterable by name, IFD or value.
Double-click a value to edit it in place (edits show green until saved); text,
numbers, number lists and rationals are accepted (`28/10` and `2.8` both work).
Select tags and hit *Delete selected* to stage removals (shown struck-through;
click again to undo). Nothing touches the file until **Save**, which follows the
same conventions as above: a new `<name>_meta` file by default, overwrite
optional, JPEG pixels never re-encoded.

Not everything is editable, on purpose. Structural entries (IFD pointers,
strip/thumbnail offsets) are recomputed on save, so hand-editing them would
corrupt files; the **MakerNote** is a proprietary camera blob (Sony's
especially) that does not survive naive rewrites, and **UserComment** carries an
encoded charset prefix. These rows are shown dimmed with a tooltip explaining
why — the MakerNote can still be *deleted* if you want it gone. Like the rest of
the tool, this is EXIF only: XMP and IPTC blocks are neither shown nor touched.

### Astro Stacker

Stacking needs a *sequence* of frames shot on a fixed tripod — you can't stack a
single photo. Choose the frames (files or a whole folder), pick what to lock onto,
**Preview** at reduced resolution, then **Export** at full resolution.

- **Lock onto stars** — every frame is registered so the star field overlaps,
  then combined. Stars sharpen and noise drops; the static foreground, shifted to
  keep the stars fixed, smears.
- **Lock onto foreground** — frames aren't registered (fixed tripod) and are
  combined with a per-pixel maximum ("lighten"), so the ground stays sharp and the
  stars draw trails.

Combine methods for an aligned sky are average, median (rejects planes and
satellites) and a sigma-clipped average; star trails always use lighten.

**Reduce transient anomalies** *(checkbox)* — suppresses passing intruders
(planes, satellites, brief flashes, stray light, drifting cloud). It works on the
*source frames during stacking*, so it can't clean an already-stacked image. In
aligned mode it applies a per-pixel sigma-clip; in trail mode it drops whole
frames whose brightness spikes against the sequence (which may slightly shorten
trails). It reliably removes broad or bright contamination; small, thin
light-painting squiggles can score near normal star variation and slip through.

**Smooth sky** *(checkbox, trail mode)* — lighten blending keeps the brightest,
noisiest sample at every pixel, which amplifies background grain. This rebuilds
the sky from the average of all frames (low noise) and keeps the max only for the
bright trails. Tradeoff: it cleans the sky but dims or drops the very faintest
trails, which sit at the noise level. The bigger quality lever is to stack
RAW/DNG and export 16-bit rather than 8-bit JPEG.

The trail stack **streams** frame-by-frame (running max, plus running mean/
variance for smooth-sky) rather than holding every frame in memory, so dozens of
full-resolution RAW frames don't exhaust RAM.

**RAW in, no RAW out — by design.** RAW frames (incl. DNG, CR2/CR3, NEF, ARW,
RAF, RW2, ORF, PEF, SRW) are decoded for input via rawpy / libraw, linearly, so
averaging is photometrically correct. A *stacked* result is demosaiced
multi-frame RGB — no longer single-exposure sensor data — and camera RAW
containers are proprietary and read-only, so there is no meaningful "export to
RAW". The high-fidelity outputs are **16-bit TIFF, 32-bit-float TIFF and FITS**,
alongside 8-bit JPEG/PNG/WEBP/TIFF.

### Quick Edit

Fast, non-destructive single-image adjustments with a live preview. Open an image
(or drag one in) — including RAW/DNG, decoded with normal sRGB rendering so it
looks like a photo, not flat linear data. Editing happens on a downscaled preview
for responsiveness; full resolution is processed only on export. Controls:

- **Preset** — one-click looks: *Silver* and *Red-filter sky* (black & white),
  *Moonlit* (cool), *Ember* (warm) and *Faded* (matte). Your white-balance and
  gradient settings layer on top of the chosen look.
- **Gradient removal** — flattens a light-pollution gradient or vignette by
  modelling the smooth background and subtracting it. Good for skies; a large
  bright/dark foreground can bias the automatic model.
- **White balance** — *Auto* (gray-world; note it can cool a night sky), plus
  manual **Temperature** (cool ↔ warm) and **Tint** (green ↔ magenta).

Export to JPEG/PNG/WEBP/TIFF (8-bit) or 16-bit TIFF; the suggested name is
`<original>_edited`.

---

## Updates

The suite updates itself from this repository. On launch it asks GitHub whether
`main` has moved on; if so, it offers to download the latest source, overlay it
onto your install, and restart. The version is shown bottom-left in the launcher.

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

## Settings

Tools remember small conveniences between sessions — last-used folders, window
size and position, and (where applicable) saved presets — via a JSON file in your
OS config directory. It's written atomically and never load-bearing: a missing or
corrupt file simply means "no remembered state", never a crash. The light/dark
choice is remembered too (until you first click the toggle, the suite simply
follows Windows).

---

## Project structure

The GUI is kept separate from a GUI-agnostic processing core, so the same logic
serves the desktop app, the CLI, and parallel workers.

| File | Role |
| --- | --- |
| `launcher.py` | Suite home window; opens the five tools. Entry point for the app. |
| `updater.py` | Checks GitHub on launch and self-updates the suite from this repo. |
| `settings.py` | Cross-cutting persistent settings (last folders, window geometry, presets). |
| `theme.py` | Shared light/dark theme (stylesheet + palette, live switching, Windows-mode detection) + icon path resolver. |
| `photoborder_gui.py` | PhotoBorder desktop UI (parallel batch + live preview). |
| `core.py`, `border.py`, `palette.py`, `exif.py`, `text.py`, `worker.py`, `filemanager.py` | PhotoBorder engine (from the original project). |
| `main.py` | PhotoBorder command-line entry point. |
| `converter_core.py` / `converter_gui.py` | Format conversion — logic / UI. |
| `metadata_core.py` / `metadata_gui.py` | EXIF baking & field editing — logic / UI. |
| `stacker_core.py` / `stacker_gui.py` | Astro stacking — align/combine engine (numpy) and UI with rendered preview. |
| `quickedit_core.py` / `quickedit_gui.py` | Quick Edit — adjustment pipeline (numpy/scipy) and live-preview UI. |
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

The processing cores (`converter_core.py`, `metadata_core.py`, `stacker_core.py`,
`quickedit_core.py`, and the PhotoBorder pipeline) are designed to be testable
without a display.

---

## License

MIT License.

- (c) 2024 stevequinn — original [photoborder](https://github.com/stevequinn/photoborder) author.
- (c) 2026 PufferfishGaming/Stormchaser Photography — Chaser's Shenanigans fork and additional features.

Both are released under the same MIT terms. See [`LICENSE`](LICENSE). Under MIT,
stevequinn's original copyright notice is retained; the fork's notice is added
alongside it, not in place of it.
