"""Quick Edit core — GUI-agnostic image adjustments.

Loads any format the stacker can (including RAW/DNG), works in float32 RGB in
0..1, and applies a fixed-order pipeline:

    gradient removal -> white balance -> exposure / levels -> look / B&W

Gradient removal is first so its background model depends only on the original
pixels (cacheable, white-balance-independent), which keeps the live preview
fast. All ops are vectorised numpy; the GUI runs the pipeline on a downscaled
preview while editing and only at full resolution on export.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict
import numpy as np

import stacker_core as _io   # reuse the stacker's encode + format lists

# Re-export the shared I/O surface so the GUI can stay decoupled from stacker.
export_image = _io.export_image
supported_input_extensions = _io.supported_input_extensions
supported_output_formats = _io.supported_output_formats
extension_for_format = _io.extension_for_format


def load_image(path: str) -> np.ndarray:
    """Decode to float32 RGB 0..1 with a *display-referred* rendering.

    The stacker decodes RAW linearly (gamma 1,1, no auto-bright) because that is
    correct for averaging frames — but shown on screen that looks dark and flat.
    Quick Edit instead wants a normal photo, so RAW is decoded with the standard
    sRGB gamma and camera white balance, matching what a viewer shows. Non-RAW
    files are already display-referred and load through the shared PIL path.
    """
    if _io.is_raw(path):
        return _decode_raw_display(path)
    return _io.load_frame(path)


def _decode_raw_display(path: str) -> np.ndarray:
    if not _io.RAW_AVAILABLE:
        raise RuntimeError("RAW input requires rawpy, which isn't installed.")
    import rawpy
    # Fresh handle per attempt (libraw forbids a second postprocess on one handle).
    attempts = (
        dict(output_bps=16, use_camera_wb=True),                       # sRGB gamma + auto-bright
        dict(output_bps=16, use_camera_wb=True, no_auto_bright=True),  # faithful exposure
        dict(),                                                        # library defaults
    )
    last_exc = None
    for kwargs in attempts:
        try:
            with rawpy.imread(path) as raw:
                rgb = raw.postprocess(**kwargs)
            scale = 65535.0 if rgb.dtype == np.uint16 else 255.0
            return rgb.astype(np.float32) / scale
        except Exception as exc:  # noqa: BLE001 — try the next, simpler decode
            last_exc = exc
    raise RuntimeError(f"Could not decode {os.path.basename(path)}: {last_exc}")


def _luma(img: np.ndarray) -> np.ndarray:
    return img[..., 0] * 0.2126 + img[..., 1] * 0.7152 + img[..., 2] * 0.0722


# ----------------------------------------------------------------- white balance
def auto_white_balance_gains(img: np.ndarray) -> tuple[float, float, float]:
    """Gray-world gains that equalise the channel means. Returns (gr, gg, gb)."""
    means = img.reshape(-1, 3).mean(axis=0) + 1e-6
    gray = float(means.mean())
    g = gray / means
    # don't let a near-black channel blow up
    g = np.clip(g, 0.2, 5.0)
    return float(g[0]), float(g[1]), float(g[2])


def _wb_multipliers(temp: float, tint: float) -> np.ndarray:
    """temp in -1..1 (warm + / cool -), tint in -1..1 (magenta + / green -)."""
    return np.array([1.0 + 0.4 * temp, 1.0 - 0.25 * tint, 1.0 - 0.4 * temp], np.float32)


# ------------------------------------------------------------------- auto levels
def auto_levels(img: np.ndarray, lo_pct: float = 0.5, hi_pct: float = 99.6) -> tuple[float, float]:
    """Black/white points from luma percentiles, for an auto contrast stretch."""
    lum = _luma(img)
    lo = float(np.percentile(lum, lo_pct))
    hi = float(np.percentile(lum, hi_pct))
    if hi - lo < 1e-3:
        return 0.0, 1.0
    return lo, hi


# ------------------------------------------------------- gradient / light pollution
def estimate_background(img: np.ndarray, scale: float = 0.08) -> np.ndarray:
    """Per-channel smooth background model (light-pollution gradient + vignette).

    Downsample, suppress small bright features (stars, highlights) with a median,
    then heavily blur. Upsampled back, this is the slow varying component to
    subtract. Large bright or dark foreground can bias it — that's the known
    limit of an automatic flattener versus a manual sample-point method.
    """
    from skimage.transform import resize
    from scipy import ndimage

    h, w = img.shape[:2]
    edge = max(48, int(round(max(h, w) * scale)))
    factor = edge / float(max(h, w))
    nh, nw = max(8, round(h * factor)), max(8, round(w * factor))
    small = resize(img, (nh, nw), order=1, preserve_range=True,
                   anti_aliasing=True).astype(np.float32)
    msz = max(3, (min(nh, nw) // 12) | 1)        # odd kernel
    sigma = max(nh, nw) / 10.0
    bg = np.empty_like(small)
    for c in range(3):
        med = ndimage.median_filter(small[..., c], size=msz)
        bg[..., c] = ndimage.gaussian_filter(med, sigma=sigma)
    bg_full = resize(bg, (h, w), order=1, preserve_range=True,
                     anti_aliasing=True).astype(np.float32)
    return bg_full


def remove_gradient(img: np.ndarray, strength: float = 1.0,
                    bg: np.ndarray | None = None) -> np.ndarray:
    """Subtract the smooth background but preserve the overall level so the image
    isn't globally darkened. ``bg`` may be precomputed and reused across edits."""
    if strength <= 0:
        return img
    if bg is None:
        bg = estimate_background(img)
    keep = bg.reshape(-1, 3).mean(axis=0)        # neutral level to add back
    out = img - strength * (bg - keep)
    return np.clip(out, 0.0, 1.0)


# ------------------------------------------------------------------------- presets
@dataclass
class EditParams:
    gradient: float = 0.0          # 0..1 strength of light-pollution removal
    auto_wb: bool = False
    temp: float = 0.0              # -1..1
    tint: float = 0.0              # -1..1
    exposure: float = 0.0          # EV stops
    black: float = 0.0             # levels black point (0..1)
    white: float = 1.0             # levels white point (0..1)
    gamma: float = 1.0             # >1 lifts shadows
    contrast: float = 0.0          # -1..1
    bw: bool = False
    bw_weights: tuple = (0.2126, 0.7152, 0.0722)
    look_temp: float = 0.0         # stylistic colour cast applied at the end
    look_tint: float = 0.0
    fade: float = 0.0              # raise blacks for a matte look (0..1)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "EditParams":
        f = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        if "bw_weights" in f:
            f["bw_weights"] = tuple(f["bw_weights"])
        return cls(**f)


# Built-in looks. Original names — not emulations of trademarked film stocks.
PRESETS: dict[str, EditParams] = {
    "None": EditParams(),
    "Silver (B&W)": EditParams(bw=True, contrast=0.12),
    "Red-filter sky (B&W)": EditParams(bw=True, bw_weights=(0.62, 0.30, 0.08), contrast=0.15),
    "Moonlit (cool)": EditParams(look_temp=-0.28, look_tint=-0.04, contrast=0.06),
    "Ember (warm)": EditParams(look_temp=0.30, contrast=0.05),
    "Faded (matte)": EditParams(fade=0.06, contrast=-0.08),
}


def preset_names() -> list[str]:
    return list(PRESETS.keys())


# ------------------------------------------------------------------------ pipeline
def apply_pipeline(img: np.ndarray, p: EditParams,
                   bg: np.ndarray | None = None) -> np.ndarray:
    """Apply the full edit pipeline. ``bg`` is an optional precomputed background
    (from :func:`estimate_background` on this same image) to avoid recomputing it
    on every preview update."""
    out = img.astype(np.float32, copy=True)

    # 1. gradient / light-pollution removal (background depends on original pixels)
    if p.gradient > 0:
        out = remove_gradient(out, p.gradient, bg=bg)

    # 2. white balance
    if p.auto_wb:
        out = out * np.array(auto_white_balance_gains(out), np.float32)
    if p.temp or p.tint:
        out = out * _wb_multipliers(p.temp, p.tint)
    out = np.clip(out, 0.0, 1.0)

    # 3. exposure / levels / tone
    if p.exposure:
        out = out * (2.0 ** p.exposure)
    if p.black != 0.0 or p.white != 1.0:
        out = (out - p.black) / max(p.white - p.black, 1e-4)
    out = np.clip(out, 0.0, 1.0)
    if p.gamma and abs(p.gamma - 1.0) > 1e-3:
        out = np.power(out, 1.0 / p.gamma)
    if p.contrast:
        out = (out - 0.5) * (1.0 + p.contrast) + 0.5
    out = np.clip(out, 0.0, 1.0)

    # 4. look / black & white
    if p.bw:
        w = np.asarray(p.bw_weights, np.float32)
        w = w / (w.sum() + 1e-9)
        lum = out @ w
        out = np.repeat(lum[..., None], 3, axis=2)
    if p.look_temp or p.look_tint:
        out = out * _wb_multipliers(p.look_temp, p.look_tint)
    if p.fade:
        out = out * (1.0 - p.fade) + p.fade

    return np.clip(out, 0.0, 1.0)
