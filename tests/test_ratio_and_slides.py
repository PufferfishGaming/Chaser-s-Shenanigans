"""
Custom text size independence, per-ratio placements and Instagram landscape mode.

Three separate requests that landed together:

  * The EXIF caption's size multiplier used to resize the custom text as well,
    because `draw_exif` derived the custom text's base size from the body size
    AFTER the EXIF multiplier had been applied to it.
  * Placements are remembered per aspect ratio in the GUI, so a layout tuned for
    16:9 comes back when 16:9 is chosen again after working on 4:5.
  * Instagram landscape mode pads the canvas to 2 x 4:5 and saves it as two 4:5
    slides that line up when swiped.
"""
import os
import subprocess
import sys

import pytest
from PIL import Image, ImageChops

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fontcatalog                                        # noqa: E402
from border import BorderType                             # noqa: E402
from core import process_image, split_into_slides, slides_ratio  # noqa: E402
from layout import Placement                              # noqa: E402

FONTDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
TEXT = "Stormchaser"


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    d = tmp_path_factory.mktemp("src")
    p = os.path.join(str(d), "s.png")
    img = Image.new("RGB", (1800, 1200), (200, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = "SONY"
    exif[0x0110] = "ILCE-7M4"
    exif.get_ifd(0x8769).update({
        0x829D: 2.8, 0x920A: 70.0, 0x8827: 2000, 0x829A: 0.025,
        0xA433: "Sigma", 0xA434: "24-70mm F2.8 DG DN II",
    })
    img.save(p, exif=exif)
    return p


def _render(source, out_dir, **kw):
    geometry = {}
    out = process_image(
        path=source, add_exif=True, add_palette=kw.pop("add_palette", True),
        border_type=kw.pop("border_type", BorderType.POLAROID),
        font=fontcatalog.spec("ebgaramond"), boldfont=fontcatalog.spec("ebgaramond", bold=True),
        fontdir=FONTDIR, output_root=str(out_dir), input_root=os.path.dirname(source),
        custom_text=TEXT, custom_font=fontcatalog.spec("greatvibes"),
        geometry_out=geometry, **kw)
    return out, geometry


# ---------------------------------------------------------------------------
# EXIF size must not resize the custom text
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("border_type", list(BorderType))
def test_exif_size_does_not_change_the_custom_text_size(source, tmp_path, border_type):
    _, base = _render(source, tmp_path / "a", border_type=border_type)
    _, bigger = _render(source, tmp_path / "b", border_type=border_type,
                        placements={"exif": Placement(size_mult=1.6)})
    a, b = base["boxes"]["text"], bigger["boxes"]["text"]
    # +-1px: the boxes are rounded from fractional pen positions, and on
    # SMALL/MEDIUM the text is the row's last segment, so it moves along with a
    # bigger caption. Before the fix the change was ~60% of the height.
    assert abs((b[2] - b[0]) - (a[2] - a[0])) <= 1 and abs((b[3] - b[1]) - (a[3] - a[1])) <= 1, (
        f"custom text resized from {a} to {b} by the EXIF size multiplier")
    # ...while the EXIF caption itself did grow.
    ea, eb = base["boxes"]["exif"], bigger["boxes"]["exif"]
    assert (eb[3] - eb[1]) > (ea[3] - ea[1])


@pytest.mark.parametrize("border_type", list(BorderType))
@pytest.mark.parametrize("centered", [False, True])
@pytest.mark.parametrize("mult", [0.5, 1.3, 1.6, 2.5])
def test_exif_size_does_not_move_the_custom_text(source, tmp_path, border_type, centered, mult):
    """The custom text sits where it would with the EXIF at 1x, whatever the EXIF size.

    It used to be laid out against the RESIZED caption - a line under the block on
    POLAROID/LARGE, the next segment of the row on SMALL/MEDIUM - so a bigger
    EXIF pushed it down or along. An explicit size is taken literally instead,
    and a big caption may overlap the text.
    """
    _, base = _render(source, tmp_path / "a", border_type=border_type, custom_centered=centered)
    _, other = _render(source, tmp_path / "b", border_type=border_type, custom_centered=centered,
                       placements={"exif": Placement(size_mult=mult)})
    a, b = base["boxes"]["text"], other["boxes"]["text"]
    assert all(abs(p - q) <= 1 for p, q in zip(a, b)), f"text moved {a} -> {b} at EXIF {mult}x"
    assert other["custom_centered"] == base["custom_centered"]


@pytest.mark.parametrize("border_type", list(BorderType))
def test_the_placement_text_size_resizes_the_custom_text(source, tmp_path, border_type):
    """The Placement grid's Text row "Size" used to be stored and never read."""
    _, base = _render(source, tmp_path / "a", border_type=border_type)
    _, bigger = _render(source, tmp_path / "b", border_type=border_type,
                        placements={"text": Placement(size_mult=1.6)})
    a, b = base["boxes"]["text"], bigger["boxes"]["text"]
    assert (b[2] - b[0]) > (a[2] - a[0]) * 1.3, f"text {a} -> {b}"
    # ...and leaves the EXIF caption alone.
    ea, eb = base["boxes"]["exif"], bigger["boxes"]["exif"]
    assert abs((eb[3] - eb[1]) - (ea[3] - ea[1])) <= 1


def test_the_text_size_control_still_resizes_the_custom_text(source, tmp_path):
    _, base = _render(source, tmp_path / "a")
    _, bigger = _render(source, tmp_path / "b", custom_size_mult=1.6)
    a, b = base["boxes"]["text"], bigger["boxes"]["text"]
    assert (b[3] - b[1]) > (a[3] - a[1])


# ---------------------------------------------------------------------------
# Instagram landscape mode
# ---------------------------------------------------------------------------
def test_slides_ratio_is_two_portraits_side_by_side():
    assert slides_ratio(2) == pytest.approx(8 / 5)


@pytest.mark.parametrize("size", [(1601, 1000), (1600, 1000), (1000, 999), (2001, 1250)])
def test_split_gives_equal_exact_four_by_five_slides(size):
    canvas = Image.new("RGB", size, (10, 20, 30))
    slides = split_into_slides(canvas, 2)
    assert len(slides) == 2
    assert slides[0].size == slides[1].size
    w, h = slides[0].size
    assert w * 5 == h * 4, f"slide {w}x{h} is not exactly 4:5"
    # Nothing of the original is lost to the cut.
    assert 2 * w >= size[0] and h >= size[1]


def test_slides_rejoin_into_the_unsplit_render(source, tmp_path):
    """Two slides side by side are the whole render: nothing dropped, nothing doubled."""
    whole, _ = _render(source, tmp_path / "whole", target_ratio=slides_ratio(2))
    first, _ = _render(source, tmp_path / "split", slides=2)
    second = first.replace("_slide1", "_slide2")
    assert first.endswith("_slide1.png") and os.path.exists(second)

    with Image.open(whole) as w, Image.open(first) as a, Image.open(second) as b:
        assert a.size == b.size and a.width * 5 == a.height * 4
        joined = Image.new("RGB", (a.width * 2, a.height))
        joined.paste(a.convert("RGB"), (0, 0))
        joined.paste(b.convert("RGB"), (a.width, 0))
        expected = split_into_slides(w.convert("RGB"), 2)
        rebuilt = Image.new("RGB", joined.size)
        rebuilt.paste(expected[0], (0, 0))
        rebuilt.paste(expected[1], (a.width, 0))
        assert ImageChops.difference(joined, rebuilt).getbbox() is None


def test_slides_override_the_requested_ratio(source, tmp_path):
    first, _ = _render(source, tmp_path / "o", slides=2, target_ratio=1.0)
    with Image.open(first) as a:
        assert a.width * 5 == a.height * 4


def test_no_unsplit_file_is_written_in_slide_mode(source, tmp_path):
    out_dir = tmp_path / "only"
    _render(source, out_dir, slides=2)
    names = sorted(os.listdir(out_dir))
    assert len(names) == 2 and all("_slide" in n for n in names), names


def test_cli_instagram_landscape_writes_two_slides(source, tmp_path):
    main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    out_dir = tmp_path / "cli"
    run = subprocess.run([sys.executable, main_py, source, "-o", str(out_dir), "-t", "p",
                          "--instagram-landscape", "--ratio", "1:1"],
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    names = sorted(os.listdir(out_dir))
    assert [n.rsplit("_", 1)[-1] for n in names] == ["slide1.png", "slide2.png"], names
    for n in names:
        with Image.open(out_dir / n) as im:
            assert im.width * 5 == im.height * 4
    assert "--ratio 1:1 ignored" in run.stderr


def test_cli_text_size_is_the_text_placement_size(source, tmp_path):
    """--text-size and --place text=...,SIZE are one size, as in the GUI."""
    main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    out_dir = tmp_path / "cli"
    run = subprocess.run([sys.executable, main_py, source, "-o", str(out_dir), "-t", "p", "-e",
                          "--exif-font", "ebgaramond", "--text", TEXT, "--text-font", "greatvibes",
                          "--text-size", "1.6"],
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    (cli_name,) = os.listdir(out_dir)
    direct, _ = _render(source, tmp_path / "direct", add_palette=False,
                        placements={"text": Placement(size_mult=1.6)})
    with Image.open(out_dir / cli_name) as a, Image.open(direct) as b:
        assert ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox() is None
