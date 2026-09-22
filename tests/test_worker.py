"""
The parallel batch path must render exactly what the single-file path renders.

PhotoBorder has two routes to `process_image`. One file goes through
`BatchWorker._run_sequential`, which calls it directly. A folder goes through a
ProcessPoolExecutor, and there the options travel inside a `WorkerArgs`
dataclass and are unpacked again by `worker.process_one`. That second route is a
separately maintained copy of the parameter list.

It drifted once, and the way it failed is worth recording: `WorkerArgs` lacked
the new options, so building it raised TypeError - inside the batch QThread and
outside any try. The thread died, no finished signal fired, and the window kept
Process disabled. A single file processed fine; a folder did nothing at all, with
no message. None of the other suites could see it, because none of them go
through the worker.

These tests pin both halves: every option is CARRIED (a WorkerArgs field) and
FORWARDED (process_one passes it on), checked structurally and by rendering.
"""
import inspect
import os
import pickle
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fontcatalog                                          # noqa: E402
from border import BorderType                               # noqa: E402
from core import process_image                              # noqa: E402
from layout import Placement                                # noqa: E402
from worker import WorkerArgs, WorkerResult, process_one    # noqa: E402

FONTDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")

# process_image parameters that deliberately do NOT cross the process boundary.
# Anything else added to process_image must be added to WorkerArgs as well.
NOT_CARRIED = {
    "progress_cb",       # a callable; cannot be pickled, workers report per file instead
    "preview_max_edge",  # previews never go through the pool
    "preview_source",    # an open image handle owned by the GUI process
    "geometry_out",      # an out-parameter; only the GUI's preview reads it
    "border_type",       # carried as border_type_value, a plain str that pickles
}


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    d = tmp_path_factory.mktemp("src")
    p = os.path.join(str(d), "s.jpg")
    img = Image.new("RGB", (900, 600), (200, 30, 30))
    for x in range(110):
        for y in range(70):
            img.putpixel((x, y), (0, 255, 0))
    exif = Image.Exif()
    exif[0x010F] = "SONY"
    exif[0x0110] = "ILCE-7M4"
    exif.get_ifd(0x8769).update({0x829D: 2.8, 0x920A: 70.0, 0x8827: 2000, 0x829A: 0.025,
                                 0xA433: "Sigma", 0xA434: "24-70mm F2.8 DG DN II"})
    img.save(p, exif=exif, quality=95)
    return p


def test_every_process_image_option_is_a_worker_field():
    """Structural guard: adding a process_image option without a WorkerArgs field fails here."""
    wanted = set(inspect.signature(process_image).parameters) - NOT_CARRIED
    have = set(WorkerArgs.__dataclass_fields__)
    missing = sorted(wanted - have)
    assert not missing, (
        f"process_image takes {missing} but WorkerArgs does not carry them, so folder "
        "batches would silently drop them (or fail to build). Add them to WorkerArgs "
        "and forward them in process_one - or list them in NOT_CARRIED with a reason.")


def test_process_one_forwards_every_field():
    """Every WorkerArgs field must reach process_image, not just exist."""
    src = inspect.getsource(process_one)
    fields = set(WorkerArgs.__dataclass_fields__) - {"border_type_value"}
    unforwarded = sorted(f for f in fields if f"args.{f}" not in src)
    assert not unforwarded, f"process_one never passes on: {unforwarded}"


def test_worker_args_with_placements_pickle():
    """Spawn-mode workers receive their arguments by pickle, placements included."""
    args = WorkerArgs(path="x.jpg", add_exif=True, add_palette=True, border_type_value="p",
                      font=fontcatalog.spec("roboto"), boldfont=fontcatalog.spec("roboto", True),
                      fontdir=FONTDIR, output_root=".", input_root=".", rotate=90,
                      custom_text="Stormchaser", custom_font=fontcatalog.spec("greatvibes"),
                      placements={"palette": Placement(anchor="left"),
                                  "exif": Placement(x=0.4, y=0.3, size_mult=1.2)})
    back = pickle.loads(pickle.dumps(args))
    assert back == args


@pytest.mark.parametrize("options", [
    {},
    {"rotate": 90},
    {"custom_text": "Stormchaser", "custom_font": fontcatalog.spec("greatvibes"),
     "custom_size_mult": 1.6},
    {"custom_text": "Stormchaser", "custom_font": fontcatalog.spec("greatvibes"),
     "custom_centered": True},
    {"placements": {"palette": Placement(anchor="left"), "exif": Placement(anchor="right")}},
    {"placements": {"exif": Placement(x=0.45, y=0.3)}},
    {"target_ratio": 0.8, "rotate": 270, "custom_text": "Stormchaser",
     "custom_font": fontcatalog.spec("parisienne")},
], ids=["defaults", "rotate", "custom-text", "centred", "anchors", "dragged", "combined"])
def test_worker_output_matches_direct_render(source, tmp_path, options):
    """The worker must produce the same pixels as calling process_image directly."""
    common = dict(path=source, add_exif=True, add_palette=True,
                  font=fontcatalog.spec("ebgaramond"),
                  boldfont=fontcatalog.spec("ebgaramond", bold=True), fontdir=FONTDIR,
                  input_root=os.path.dirname(source))
    direct = process_image(border_type=BorderType.POLAROID,
                           output_root=str(tmp_path / "direct"), **common, **options)
    res = process_one(WorkerArgs(border_type_value=BorderType.POLAROID.value,
                                 output_root=str(tmp_path / "worker"), **common, **options))
    assert res.error is None, res.error
    assert os.path.basename(res.save_path) == os.path.basename(direct)
    a = Image.open(direct).convert("RGB")
    b = Image.open(res.save_path).convert("RGB")
    assert a.size == b.size
    assert list(a.getdata()) == list(b.getdata()), (
        f"worker render differs from direct render for {sorted(options)}")


def test_process_one_reports_errors_instead_of_raising(tmp_path):
    """One bad file must come back as an error, never raise across the pool."""
    res = process_one(WorkerArgs(
        path=str(tmp_path / "missing.jpg"), add_exif=True, add_palette=False,
        border_type_value="p", font=fontcatalog.spec("roboto"),
        boldfont=fontcatalog.spec("roboto", bold=True), fontdir=FONTDIR,
        output_root=str(tmp_path), input_root=str(tmp_path)))
    assert isinstance(res, WorkerResult)
    assert res.error and res.save_path is None
