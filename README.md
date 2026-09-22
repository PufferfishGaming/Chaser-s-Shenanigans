# Chaser's Shenanigans

**v4** — a small desktop suite of photo utilities, behind one launcher.

- **PhotoBorder** — add clean borders, EXIF strips and colour palettes to photos,
  batching a whole folder in parallel with a live, draggable preview.
- **Format Converter** — convert images between JPEG, PNG, WEBP, TIFF, BMP and
  (where available) HEIF/HEIC/HIF, with optional resize, metadata/GPS stripping
  and pattern-based renaming, preserving EXIF and DPI wherever the target allows.
- **Metadata Baker** — copy EXIF from one image into another (restore camera
  metadata onto an edited export), edit fields directly (artist, copyright,
  dates, GPS) on a single file or a whole folder, *and* browse and edit every raw
  EXIF tag, exiftool-style.
- **Astro Stacker** — combine a night-sky sequence into one image: lock onto the
  stars for a sharp sky over a smeared foreground, or onto the foreground for
  sharp ground under trailing stars. Reads RAW (incl. DNG), exports to 8-bit
  formats plus 16-bit / 32-bit-float TIFF and FITS.
- **Quick Edit** — fast single-image adjustments with a live preview: film
  simulations inspired by classic stocks, white balance, light-pollution gradient
  removal and one-click looks. RAW in, 8/16-bit out.

Built for photographers who want a tidy, consistent workflow — from night-sky
sequences to everyday shoots straight off the camera.

<div align="center">

[![Download for Windows](https://img.shields.io/badge/Windows-Download_the_installer-2ea44f?style=for-the-badge)](https://github.com/PufferfishGaming/Chaser-s-Shenanigans/releases/download/Installer/install-chasers-shenanigans.bat)

One click, one file. It installs Python if needed, downloads the latest
version, and creates your shortcuts. Re-run it any time to update or repair.

</div>

---

## What's new in v4

v4 rebuilds the entire interface on a shared design system. Every tool is drawn
from the same set of components, so the five windows finally look and behave like
one application instead of five that grew separately.

- **One visual language.** A photography-forward dark theme (and a matching light
  one): deep neutral surfaces, the preview area darker than the chrome around it,
  one accent colour, one spacing scale.
- **Controls that actually render.** Sliders and checkboxes were being drawn by
  Windows rather than by the app, in an olive-yellow highlight that matched
  neither theme — a solid yellow bar across every quality slider. Every control is
  now drawn by the suite itself, in both modes.
- **The main action is always reachable.** Each tool's verb (Process, Convert,
  Export, Bake, Apply) is pinned below the scrolling options instead of being the
  last thing in a long column.
- **Nothing empty on screen.** Progress bars and log boxes appear when there is
  something to report and stay out of the way otherwise.
- **Faster to open.** The launcher window appears in ~340 ms instead of ~1140 ms;
  the heavy numerical libraries now load in the background after the window is up,
  not before it.
- **Drag and drop everywhere**, live slider values with one-click reset, a
  reflowing launcher grid, and hold-to-compare in Quick Edit.

See [The interface](#the-interface) for the details.

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

### macOS (recommended)

Apple Silicon (M-series) is fine — every dependency ships an arm64 wheel.

Open **Terminal** and paste this one line:

```bash
curl -fsSL https://github.com/PufferfishGaming/Chaser-s-Shenanigans/releases/download/Installer/install-chasers-shenanigans.sh | bash
```

It does the same job as the Windows installer: installs Python 3.10+ if it
isn't already there, asks where to install, downloads the latest version, builds
an isolated `.venv`, creates a double-clickable launcher in `~/Applications`,
and starts the app. Re-run it any time to update or repair.

> **Why a Terminal command and not a file you double-click?** macOS won't let
> you. A script downloaded through a browser arrives without the Unix
> executable bit *and* carrying Apple's `com.apple.quarantine` flag, so Finder
> refuses to run it and Gatekeeper blocks it as an unidentified developer. The
> only way to get a genuine double-click is a signed, notarised installer, which
> needs a paid Apple Developer account. One pasted line is the honest
> alternative — it's how Homebrew and rustup install too.
>
> If you'd rather read the script before running it, drop the `| bash` and it
> prints to your screen instead.

If Python has to be installed, the script will ask for your administrator
password — macOS installs Python system-wide. It downloads the official
python.org package and **verifies that it is signed by the Python Software
Foundation before running it**; if the signature doesn't match, it refuses and
stops. Prefer to avoid that entirely? Run `brew install python@3.13` first and
the installer will use it and never ask for a password.

**After installing:** double-click **Chaser's Shenanigans.command** in
`~/Applications` (or drag it to your Dock). That launcher is written on your own
machine rather than downloaded, so it isn't quarantined and opens normally.

### macOS / Linux (from source)

1. Install **Python 3.10+** — either the
   [python.org macOS installer](https://www.python.org/downloads/macos/) or
   `brew install python@3.13`. (The `python3` that comes with the Xcode command
   line tools can be older than 3.10; `install.sh` checks and tells you.)
2. Clone or download this repository, then from the project folder:

```bash
bash install.sh    # creates .venv, installs everything, reports HEIF/RAW status
./run.sh           # starts the launcher
```

Re-run `install.sh` any time to repair or refresh the environment.

**What's different from Windows:**

- **No shortcuts, no installer.** `create_shortcuts.bat` and the one-click
  `install-chasers-shenanigans.bat` are Windows-only. To launch from Finder,
  make a copy of `run.sh` named `run.command` — macOS will run `.command` files
  on double-click (it opens a Terminal window alongside the app).
- **No `pythonw` equivalent**, so `run.sh` uses the venv's `python` directly.
  Launching from Terminal therefore keeps that Terminal window occupied until
  you quit the app.
- **Taskbar/Dock icon grouping** (the Windows AppUserModelID trick) is a no-op;
  the Dock shows the venv's Python icon rather than the app icon.
- **Light/dark follows the system** via Qt 6.5's `colorScheme`, which works on
  macOS — the Windows registry fallback is simply skipped. The manual sun/moon
  toggle works everywhere.
- **The self-updater works**, including the dependency refresh, and re-asserts
  the executable bit on the shell scripts after each update (zip archives don't
  carry it).

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

## The interface

All five tools are built from one shared set of components (`ui.py`) and one set
of colour tokens (`theme.py`), so a control row in Quick Edit is literally the
same object as a control row in PhotoBorder.

**The launcher.** A grid of tool cards that reflows to the window width — one
column on a narrow window, three on a wide one. A card shows an `OPEN` badge
while its tool is running and offers to *bring it to front* rather than opening a
second identical window. A tool whose optional dependency is missing shows a
disabled card explaining what to install, while the others keep working.

**Light / dark.** The suite follows your Windows theme out of the box. The
sun/moon button in the launcher header toggles it manually — a moon means dark
mode is on, a sun means light. The switch applies instantly to every open tool
window, and your choice is remembered.

**Every tool has the same shape.** A scrolling column of options on the left, the
work area on the right, and the tool's main action pinned at the bottom of the
column so it stays reachable however far you scroll. PhotoBorder's sections
(Border, Typography, Placement, Batch) fold away, and the fold state is
remembered between sessions.

**Drag and drop.** Every tool accepts a dropped file; the batch tools accept a
dropped folder. Each has a drop target that doubles as a browse button.

**Live feedback.** Sliders show their current value in a fixed-width readout and
reset to their default with one click. Progress, warnings and results appear
inline, next to the control they belong to — nothing is permanently on screen
saying nothing. Options that cannot apply (quality on a lossless format, the GPS
strip with EXIF off) are disabled *and* say why in a tooltip.

**Hold to compare.** In Quick Edit, hold the space bar — or press and hold on the
preview — to see the untouched image, marked `ORIGINAL`.

**Startup.** The launcher window appears in roughly a third of a second. The
numerical libraries the Stacker and Quick Edit need are imported in the
background one tool at a time after the window is up, so they never hold up the
first paint.

---

## Usage

Launch the app (`run.bat`, or `python launcher.py`). The home window shows a card
per tool — click one to open that tool in its own window. The launcher stays
open, so you can hop between tools.

Each tool also runs standalone if you prefer:

```bash
python photoborder_gui.py
python converter_gui.py
python metadata_gui.py
python stacker_gui.py
python quickedit_gui.py
```

### PhotoBorder

Choose an input file or folder and an output folder, pick a border type, rotation
and aspect ratio, toggle EXIF / palette / options, check the live preview, then
**Process**. A folder runs in parallel with a per-file progress bar; a single file
runs sequentially with per-stage progress. **Cancel** stops a running batch
promptly (it drops queued files; files already in flight finish, since a worker
can't be killed mid-task).

#### Rotation and orientation

**Rotate** turns the photo before the border is calculated — None, 90°
clockwise, 180°, or 90° anticlockwise. Because every border dimension, the
caption band and the palette size are derived from the photo's width and height,
rotating first means a rotated landscape gets a *portrait's* border rather than a
portrait photo sitting in a landscape frame. Ratio padding composes on top, so
rotate-then-pad-to-square does what you'd expect.

Right angles only, and that is the point: `Image.transpose` is an exact pixel
remap, so these rotations are lossless — no resampling, no cropping, no blank
corners. (The test suite asserts it: four consecutive 90° turns return a
bit-identical image.) An arbitrary angle would have to either crop back to the
aspect ratio, which costs 2.3% of the frame at 1° and 22.8% at 15°, or expand the
canvas and leave white triangles cutting into the photo's corners. Straightening
a horizon belongs in Quick Edit, not here.

Photos are **auto-oriented from their EXIF tag** first, and the output is written
with the tag reset to normal. Most cameras record rotation as a tag rather than
rewriting pixels, and previously the pipeline ignored the tag when sizing the
border but copied it into the output — so a viewer that honoured the tag turned
the finished canvas, caption band and all, a quarter turn. There is no GUI switch
for this because the old behaviour was simply wrong; `--no-auto-orient` exists on
the CLI for the rare file whose own orientation tag is incorrect.

Rotation is applied *after* auto-orientation, so it is relative to how the photo
actually looks, not to the raw sensor readout. Rotated output gets a `_rot90`
(or `_rot180` / `_rot270`) suffix in the filename, following the same per-feature
pattern as `_exif` and `_palette`; auto-orientation adds no suffix, since it
corrects the file to its own stated intent rather than applying a choice you made.

#### Placement

The **Placement** section gives each of the three caption elements — EXIF
caption, custom text, colour palette — an alignment, a vertical position and a
size multiplier, plus a snap-back button. Each row carries a small swatch in the
same colour the preview outlines that element with, so the row and the rectangle
on the photo are identifiable as the same thing.

You can also **drag them on the preview**. Each element is outlined; grab one and
move it, and the preview re-renders as you go.

That is possible because almost none of a preview's cost has anything to do with
the layout. Measured on a 29.5MP JPEG, one ~740ms preview breaks down as:

| Stage | Cost |
| --- | --- |
| Decode the source | 208 ms |
| Downscale for preview | 65 ms |
| Extract palette colours | 424 ms |
| Border + caption + save | ~30 ms |

Only that last 30ms changes when you move something. So the decoded, oriented,
downscaled image and the extracted colours are held between renders, which takes
an interactive re-render to **~30ms** — no drop in quality needed, just not
repeating work the move cannot have affected. The cache is dropped only when
something it actually depends on changes: the file, its modification time, the
rotation, auto-orientation or the preview scale.

The drag renders on a self-tuning interval based on how long the last frame
actually took, so it adapts to the machine instead of queueing frames behind the
cursor.

| Control | Meaning |
| --- | --- |
| **Align** | `Left` / `Centre` / `Right`, preselected to the alignment the element already uses. Choosing an alignment also clears a hand-placed position, so it doubles as the horizontal snap-back. |
| **EXIF lines** | How the caption's three lines align *with each other*, separately from where the block sits — so you can have the block anchored right with its lines ragged-left. Only applies to Polaroid and Large; Small and Medium draw the caption as one row. |
| **Height** | Vertical position in the caption band, 0% at the top to 100% at the bottom; `auto` is the default. |
| **Size** | 0.25x–3.0x on the element's automatic size. Scales a *fraction of the band*, so a value looks the same at any export resolution. |
| **↺** | Snap that element back to its default position, alignment and size. |

There is no "Default" entry in the alignment lists. It was a meta-value sitting
next to the three real ones and duplicating whichever the element already used —
the combo said "Default" for a caption that was plainly left-aligned. The
element's own alignment is preselected instead, and picking it explicitly is
verified to produce byte-identical output to leaving it unset.

**Auto-fit until you move it.** An element left at its default keeps all the
automatic behaviour: the EXIF caption shrinks to clear the palette, the custom
text is width-budgeted, everything is clamped inside the band. Give an element a
**Height** or drag it and it becomes hand-placed — it then keeps the size it was
given instead of being re-fitted around its new neighbours.

**Elements may overlap.** Choosing an alignment or dragging something is you
stating where you want it, so it is taken literally: anchor the caption right
with the palette also right and they will sit on top of each other.

This applies to sizing as well as position, which is the less obvious half. A
hand-placed palette leaves the automatic negotiation entirely — otherwise the
caption is still made to dodge it, just by shrinking instead of moving (dragging
the palette towards the middle used to squeeze the caption from 110×35 to 75×24
px). A *size* change is not a move: a larger palette still sitting in its default
corner is still routed around.

Only elements you have left alone are auto-fitted around each other. The caption
band remains a hard bound, because every font size and the palette size derive
from the band height.

Elements are confined to the caption band. Every font size and the palette size
are derived from the band height; an element outside it would have no size
reference, and the same multiplier would then mean different things in different
places.

Positions are stored as fractions of the canvas and of the band, never pixels, so
a layout survives a change of export resolution.

The custom text's **Centre** alignment is the one with a structural meaning
rather than a purely horizontal one: it is what moves the text out of the stacked
block and into the band's centre beside the caption. Where that isn't possible —
Large centres its caption already, and Small/Medium keep the custom text inside
their single caption row — the entry is greyed out with a hint rather than
silently ignored.

#### Typography and custom text

The **Typography** section sets two independent fonts and an optional caption of
your own:

- **EXIF font** — the family used for the EXIF caption. The heading and the two
  body lines are the same family at two weights.
- **Custom text** — an optional literal string (a name, a handle, a studio
  credit). The same string is used for every file in a batch; there are no
  substitution tokens.
- **Text font** — the family for that string, chosen independently of the EXIF
  font. Script faces are marked `(script)` and are offered here only; they are
  unreadable as three lines of technical caption.
- **Text size** — a 0.5x–3.0x multiplier on the automatic size. `1.0` matches the
  EXIF body text.
- **Alignment, position and size** for the custom text live in the **Placement**
  section, alongside the other two elements.

**Where the custom text lands.** It follows each border type's existing caption
convention rather than a fixed corner, because there is no free corner: the
palette owns the bottom-right, and Small/Medium anchor their EXIF row at the
bottom-left.

| Border | EXIF layout | Custom text |
| --- | --- | --- |
| Polaroid | Left-aligned stack | Fourth left-aligned line beneath it |
| Large | Centred stack | Fourth centred line beneath it |
| Small / Medium | Single horizontal row | Last segment of that row |

With EXIF off, the custom text takes the caption band on its own, using the same
alignment for its type.

**Centring.** Setting the custom text's alignment to **Centre** (Placement → Text
→ Align) moves it to the middle of the caption band — both axes, not just
horizontally. On Polaroid that gives three elements side by side at the same
height: the left-aligned technical caption, the centred signature, and the
palette on the right.

Because the centred text sits *beside* the caption rather than beneath it, the
EXIF caption keeps exactly the rows it occupies with no custom text at all.
Un-centred, the custom text is a fourth stacked line, so the block grows and
re-centres — which shifts the EXIF caption up by 41px in a 642px band and puts
the custom line below the palette.

Whether the centre is free is decided by an actual overlap test, not by border
type, so it is self-correcting: Polaroid's left-aligned caption ends at column
927 and a centred line starts at 1959, clearing it by 1032px, so the centre slot
is used. Large centres its own caption and therefore occupies that space, so the
test fails and the custom text falls back to a fourth stacked line. A custom
string long enough to reach the caption falls back the same way.

Centre is only offered where the custom text has a line of its own:

| Border | EXIF on | EXIF off |
| --- | --- | --- |
| Polaroid | available — takes the band centre | available |
| Large | already centred; stays a fourth line | already centred |
| Small / Medium | unavailable — shares the EXIF row | available |

On Small and Medium with EXIF on, the custom text is a segment of the single
caption row, so centring it would draw it on top of the caption. The entry is
disabled there with a hint saying so; switch **Print EXIF on border** off and it
becomes available. The CLI equivalent, `--text-center`, logs a line when it is
ignored for the same reason rather than failing.

Canvas-centre and photo-centre are the same pixel, so there is no ambiguity about
which "middle" is meant: `bleft` equals `bright` for every border type, and ratio
padding splits the extra evenly between the two sides.

Your intent is remembered independently of what the control *displays*, so
visiting a Large border (where Centre is already in force and shown as such) does
not silently switch it on for Polaroid.

The size is always derived from the caption band, so a given multiplier looks
identical at any source resolution. Four caps apply, in this order: the text is
shrunk to fit the width available beside the palette, then capped so its glyphs
cannot exceed the band height, then — on the stacked layouts — shrunk further if
the four-line block would not fit the band, and on Small/Medium shrunk until the
shared row's baseline can hold both its tallest ascender and its deepest
descender inside the band. So a large multiplier is clamped rather than
overflowing onto the photograph.

The width budget differs between the two alignments, which matters more than it
sounds: a left-anchored line of width *W* starts at `border.left`, but a centred
line of the same *W* spans `(canvas − W)/2` to `(canvas + W)/2` and so reaches
further right. A centred line's budget is therefore `2 × right_bound − canvas`,
not the left-anchored one.

#### Command line

PhotoBorder keeps its original command-line interface:

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
| `--rotate` | `0`, `90`, `180` or `270` degrees clockwise, applied before the border is sized |
| `--no-auto-orient` | Ignore the file's EXIF orientation tag (auto-orient is on by default) |
| `--place` | `NAME=ANCHOR[,HEIGHT%[,SIZE]]`, repeatable. `NAME` is `exif`, `text` or `palette`; `ANCHOR` is `default`, `left`, `center` or `right`; `HEIGHT` is `0`–`100` or `auto`. e.g. `--place palette=left --place exif=right,80,1.2` |
| `--no-overwrite` | Append ` (1)`, ` (2)`, ... instead of overwriting existing outputs |
| `-f / -fv` | Regular font file / variant index (overrides `--exif-font`) |
| `-fb / -fbv` | Bold font file / variant index (overrides `--exif-font`) |
| `--exif-font` | Font family for the EXIF caption: `roboto`, `ebgaramond`, `cormorant`, `baskerville`, `lora` |
| `--text` | Literal custom text for the bottom border |
| `--text-font` | Font family for the custom text — any of the above plus `dancingscript`, `greatvibes`, `parisienne` |
| `--text-size` | Multiplier on the automatic custom-text size (default `1.0`, range `0.5`–`3.0` in the GUI) |
| `--text-center` / `--text-centre` | Centre the custom text. Applies to `p` and `l`; on `s`/`m` only without `-e` |
| `--list-fonts` | Print the bundled families and exit |
| `--include / --exclude` | Glob patterns for which files to process |

```bash
# A Garamond caption with a copperplate-script signature
python main.py -t p -e -p --exif-font ebgaramond \
  --text "Gábor Fauszt" --text-font greatvibes --text-size 1.5 --text-center \
  -o output_folder Pictures\Waiting
```

`-f` / `-fb` still take a bare font filename and win over `--exif-font`, so
existing command lines and hand-dropped font files keep working unchanged.

### Format Converter

Choose a file or folder and an output folder, pick the target format, set the
quality (for lossy formats), and run. Output mirrors the input's sub-folder
structure, and a *don't-overwrite* option appends ` (1)`, ` (2)`, ... rather than
clobbering.

The batch is **counted before it runs**: as soon as you pick an input, the button
reads *Convert 34 files* and the pane beside it shows where they are going. A
folder that matches nothing says so immediately, rather than after you commit.

Options:

- **Convert to** — JPEG, PNG, WEBP, TIFF, BMP, or HEIF (when `pillow-heif` is
  present). The quality slider is disabled with a reason on lossless targets.
- **Preserve EXIF metadata** *(default on)* — uncheck to strip **all** metadata.
- **Remove GPS only** — keep the rest of the EXIF but surgically drop the
  location block. (Only relevant while preserving EXIF; disabled with a reason
  otherwise.)
- **Resize longest edge to N px** — downscale so the longest side is at most N
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

### Metadata Baker

Three tabs, each ending in a pinned action bar.

**Bake (copy EXIF).** Pick a **donor** image (copy metadata *from*) and a
**recipient** image (keep *these* pixels), see a short EXIF preview of each, set
the options, and **Bake**. Each card states what it contributes and an arrow
between them shows which way the metadata travels — getting these the wrong way
round is the one genuinely destructive mistake this tool offers. The result is
written to a new file (`<recipient>_meta.<ext>`). It copies **EXIF only**
(IPTC/XMP are not copied). Because blindly copying a donor's EXIF onto a
different image is a known footgun, three toggles exist:

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
all IFDs, with its name, type and value — filterable by name, IFD or value, with
a live count of how many match. Double-click a value to edit it in place (edits
show green until saved); text, numbers, number lists and rationals are accepted
(`28/10` and `2.8` both work). Select tags and hit *Delete selected* to stage
removals (shown struck-through; click again to undo). Nothing touches the file
until **Save**, which tells you how many changes are staged before you press it
and then follows the same conventions as above: a new `<name>_meta` file by
default, overwrite optional, JPEG pixels never re-encoded.

Not everything is editable, on purpose. Structural entries (IFD pointers,
strip/thumbnail offsets) are recomputed on save, so hand-editing them would
corrupt files; the **MakerNote** is a proprietary camera blob (Sony's
especially) that does not survive naive rewrites, and **UserComment** carries an
encoded charset prefix. These rows are shown dimmed with a tooltip explaining
why — the MakerNote can still be *deleted* if you want it gone. Like the rest of
the tool, this is EXIF only: XMP and IPTC blocks are neither shown nor touched.

### Astro Stacker

Stacking needs a *sequence* of frames shot on a fixed tripod — you can't stack a
single photo. Drop the frames in (files or a whole folder), pick what to lock
onto, **Preview** at reduced resolution, then **Export** at full resolution.

The chosen frames are listed by name, in the order they will be stacked, so a
folder pick that swept up a stray JPEG is visible before you run it rather than
after. Select rows and press Delete to drop them.

- **Lock onto stars** — every frame is registered so the star field overlaps,
  then combined. Stars sharpen and noise drops; the static foreground, shifted to
  keep the stars fixed, smears.
- **Lock onto foreground** — frames aren't registered (fixed tripod) and are
  combined with a per-pixel maximum ("lighten"), so the ground stays sharp and the
  stars draw trails.

A line under the control spells out which one you are getting, because the
consequence is the whole point of the choice.

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
for responsiveness; full resolution is processed only on export.

Hold the space bar, or press and hold on the preview, to see the original.

Controls:

- **Preset** — one-click looks: *Silver* and *Red-filter sky* (black & white),
  *Moonlit* (cool), *Ember* (warm) and *Faded* (matte). Your white-balance and
  gradient settings layer on top of the chosen look.
- **Film simulation** — thirteen looks inspired by classic stocks: colour
  negatives (Kodak Portra 400/160, Gold 200, Ektar 100, Fujifilm Superia 400,
  Pro 400H), slides (Fujifilm Velvia 50, Provia 100F, Kodachrome 64), cine
  (CineStill 800T) and black & white (Ilford HP5 Plus 400, Kodak Tri-X 400,
  Fujifilm Acros 100). A **Film grain** toggle adds luminance grain matched to
  the chosen stock's speed (fine on Velvia/Acros, gritty on Tri-X/800T; a
  subtle default when no film is selected). The film layers under the Preset,
  so e.g. *Faded* + Portra combine.
- **White balance** — *Auto* (gray-world; note it can cool a night sky), plus
  manual **Temperature** (cool ↔ warm) and **Tint** (green ↔ magenta), each with
  a numeric readout and a one-click reset.
- **Gradient removal** — flattens a light-pollution gradient or vignette by
  modelling the smooth background and subtracting it. Good for skies; a large
  bright/dark foreground can bias the automatic model.

> **Honest limitations of the film looks.** These are parametric
> approximations — tone curve, colour cast, saturation and split-toning tuned
> to each stock's *character* — not colorimetric emulations built from measured
> film LUTs. They aim for "recognisably Portra-ish", not "indistinguishable
> from a scan". Effects like CineStill's red halation aren't modelled. The
> grain is deterministic (a fixed seed), so re-exporting gives identical
> results. Film names are trademarks of Kodak, Fujifilm and Ilford, used here
> to indicate the inspiration.

Export to JPEG/PNG/WEBP/TIFF (8-bit) or 16-bit TIFF; the suggested name is
`<original>_edited`.

---

## Updates

The suite updates itself from this repository. On launch it asks GitHub whether
`main` has moved on; if so, it offers to download the latest source, overlay it
onto your install, and restart. The version is shown bottom-left in the launcher;
click it to see the exact commit this copy is synced to.

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
size and position, PhotoBorder's folded sections, and (where applicable) saved
presets — via a JSON file in your OS config directory. It's written atomically and
never load-bearing: a missing or corrupt file simply means "no remembered state",
never a crash. The light/dark choice is remembered too (until you first click the
toggle, the suite simply follows Windows).

---

## Project structure

The GUI is kept separate from a GUI-agnostic processing core, so the same logic
serves the desktop app, the CLI, and parallel workers. On top of that,
presentation is separated from both: `theme.py` owns colour and `ui.py` owns
shape, and no tool defines its own margins or its own control widgets.

| File | Role |
| --- | --- |
| `launcher.py` | Suite home window; opens the five tools. Entry point for the app. |
| `updater.py` | Checks GitHub on launch and self-updates the suite from this repo. |
| `settings.py` | Cross-cutting persistent settings (last folders, window geometry, presets). |
| `theme.py` | Design tokens, the shared light/dark stylesheet and palette (live switching, Windows-mode detection), generated UI glyphs, icon path resolver. |
| `ui.py` | Shared UI components every tool's panel is built from — scrolling panel with a pinned action footer, form rows, labelled sliders, foldable sections, drop zones, empty states, status strip, drawn icons. |
| `photoborder_gui.py` | PhotoBorder desktop UI (parallel batch + live preview). |
| `core.py`, `border.py`, `palette.py`, `exif.py`, `text.py`, `layout.py`, `worker.py`, `filemanager.py` | PhotoBorder engine (from the original project). |
| `fontcatalog.py` | The selectable font families, their weight instances, and which are caption-safe. |
| `main.py` | PhotoBorder command-line entry point. |
| `converter_core.py` / `converter_gui.py` | Format conversion — logic / UI. |
| `metadata_core.py` / `metadata_gui.py` | EXIF baking & field editing — logic / UI. |
| `stacker_core.py` / `stacker_gui.py` | Astro stacking — align/combine engine (numpy) and UI with rendered preview. |
| `quickedit_core.py` / `quickedit_gui.py` | Quick Edit — adjustment pipeline (numpy/scipy) and live-preview UI. |
| `install.bat` / `run.bat` / `run_debug.bat` | Windows install and launch. |
| `create_shortcuts.bat` / `create_shortcuts.ps1` | Generate app + installer shortcuts with their icons. |
| `icon.ico` / `icon.png` | App icon. |
| `install.ico` / `install.png` | Installer-shortcut icon. |
| `fonts/` | Bundled caption fonts; licences in `fonts/licenses/`. |

**UI icons are drawn, not shipped.** Every check mark, chevron, spinner arrow and
tool mark is painted with QPainter at request time and tinted for the current
theme, rather than shipped as image files. The suite already sends 3.2 MB of
fonts down the wire on every update; an icon set would be more of the same, and
drawn marks re-colour on a light/dark switch for free.

---

## Fonts

Everything in `fonts/` is redistributable; the licence for each family is in
`fonts/licenses/`, with a summary in `fonts/licenses/README.md`.

| Family | Style | EXIF caption |
| --- | --- | --- |
| Roboto | Neutral grotesque — the original PhotoBorder font | yes |
| EB Garamond | Classical book serif; warm, low contrast, prints well small | yes |
| Cormorant Garamond | High-contrast display Garamond; elegant, delicate when small | yes |
| Libre Baskerville | Sturdy transitional serif, large x-height, very legible | yes |
| Lora | Contemporary brushed serif | yes |
| Dancing Script | Casual script | custom text only |
| Great Vibes | Formal copperplate script | custom text only |
| Parisienne | Light handwritten script | custom text only |

`python main.py --list-fonts` prints the same table.

**A note on boxes in the caption.** Cameras NUL-pad the fixed-length ASCII EXIF
strings, and `.strip()` removes whitespace but not control characters, so those
NULs used to reach the renderer. Whether they were *visible* depended entirely on
the font — Roboto and EB Garamond map NUL to a zero-width glyph, while Cormorant
Garamond, Libre Baskerville and Lora map it to a visible `.notdef` box, which is
why the caption grew boxes in exactly three of the five EXIF fonts. They also
inflated the measured width (3 NULs added 72–120px at size 48), so the automatic
sizing was shrinking real text to make room for them. `exif.py` now strips every
Unicode "other" category character, turning control characters that are also
whitespace into spaces so words are not joined together.

**Variable fonts.** Every family except Roboto and the two single-weight scripts
ships as an unmodified upstream variable font with a `wght` axis, and the weight
is selected at render time. This matters in two places:

- A variable font loaded without selecting an axis position renders at its
  *default* instance, and that is not always Regular — Cormorant Garamond
  defaults to Light. So `fontcatalog` names the weight for each role explicitly.
- Text has to be *measured* at the same weight it is *drawn* at, or the
  shrink-to-fit logic underestimates and the caption overruns. `text.py` threads
  the weight through `create_font`, `measure_text_width` and both sizing helpers
  for that reason.

Adding your own TrueType font still works: drop it in `fonts/` and pass it with
`-f` / `-fb`. To make it appear in the GUI pickers, add a `FontFamily` entry to
`fontcatalog.py` — set `display_only=True` if it is unsuitable for the EXIF
caption, and give the weight names if it is a variable font.

---

## Testing

```bash
pytest
```

The processing cores (`converter_core.py`, `metadata_core.py`, `stacker_core.py`,
`quickedit_core.py`, and the PhotoBorder pipeline) are designed to be testable
without a display, and the Qt tests force the offscreen platform.

Two of the suites are worth knowing about, because both exist to catch a class of
bug that ordinary unit tests do not see.

`tests/test_caption_layout.py` is a pixel test rather than a unit test: it renders
a synthetic photo, finds every row of ink in the caption band, and asserts on the
resulting line clusters. The bugs that actually occur in the caption are
geometric — a line overlapping the one above it, a script descender clipped by the
canvas edge, caption text running into the palette — and none of those are visible
from the return value of a sizing function.

`tests/test_imports.py` imports every module in a **subprocess** with no
`QApplication`, and asserts on the exit code. That is how the app really starts:
`launcher.py` imports everything at module level and only builds the
`QApplication` inside `main()`. Constructing a Qt GUI object before that point —
a `QPixmap` at module scope, say — does not raise a Python exception; Qt calls
`qFatal` and the process aborts, which no amount of `try`/`except` will catch and
which an in-process test cannot survive either. This is not hypothetical: it once
shipped, and every other test passed, because they all built a `QApplication` in a
fixture before importing anything.

The lesson generalises: **"the tests pass" and "the app starts" are separate
claims.** Run it.

---

## License

MIT License.

- (c) 2024 stevequinn — original [photoborder](https://github.com/stevequinn/photoborder) author.
- (c) 2026 PufferfishGaming/Stormchaser Photography — Chaser's Shenanigans fork and additional features.

Both are released under the same MIT terms. See [`LICENSE`](LICENSE). Under MIT,
stevequinn's original copyright notice is retained; the fork's notice is added
alongside it, not in place of it.
