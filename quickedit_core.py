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
    film: str = ""                 # film simulation name ("" = none)
    grain: bool = False            # add luminance grain (uses the film's speed)

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


# ---------------------------------------------------------------- film simulations
# Looks *inspired by* classic film stocks. These are parametric approximations
# (tone curve + colour cast + saturation + split toning + grain), NOT
# colorimetric emulations from measured LUTs - the names indicate the character
# aimed for, and remain trademarks of Kodak / Fujifilm / Ilford respectively.
# (Note: the artistic PRESETS above deliberately keep original names; the film
# list below is a separate, explicitly "inspired by" feature.)
#
# Each entry:
#   curve      - master tone-curve control points (input, output), monotonic
#   cast       - global RGB multipliers (the stock's overall colour bias)
#   sat        - saturation multiplier around luminance
#   shadows /
#   highlights - split-tone RGB multipliers, blended by (1-L)^2 / L^2 masks
#   bw         - RGB weights for black & white stocks (replaces cast/sat)
#   grain      - luminance-grain sigma matched to the stock's speed

_NEUTRAL = ((0.0, 0.0), (0.5, 0.5), (1.0, 1.0))

FILM_SIMS: dict[str, dict] = {
    # ---- colour negative ----
    "Kodak Portra 400": dict(
        curve=((0.0, 0.02), (0.25, 0.26), (0.5, 0.52), (0.75, 0.78), (1.0, 0.985)),
        cast=(1.030, 1.000, 0.965), sat=0.92,
        shadows=(0.99, 1.00, 1.01), highlights=(1.02, 1.00, 0.98), grain=0.012),
    "Kodak Portra 160": dict(
        curve=((0.0, 0.015), (0.25, 0.255), (0.5, 0.51), (0.75, 0.765), (1.0, 0.99)),
        cast=(1.020, 1.000, 0.975), sat=0.90,
        shadows=(1.0, 1.0, 1.0), highlights=(1.015, 1.0, 0.985), grain=0.008),
    "Kodak Gold 200": dict(
        curve=((0.0, 0.01), (0.25, 0.27), (0.5, 0.54), (0.75, 0.79), (1.0, 0.99)),
        cast=(1.055, 1.010, 0.905), sat=1.08,
        shadows=(1.0, 1.0, 1.0), highlights=(1.04, 1.02, 0.94), grain=0.010),
    "Kodak Ektar 100": dict(
        curve=((0.0, 0.0), (0.25, 0.22), (0.5, 0.52), (0.75, 0.80), (1.0, 1.0)),
        cast=(1.020, 1.000, 0.980), sat=1.22,
        shadows=(1.0, 1.0, 1.0), highlights=(1.0, 1.0, 1.0), grain=0.006),
    "Fujifilm Superia 400": dict(
        curve=((0.0, 0.01), (0.25, 0.24), (0.5, 0.51), (0.75, 0.78), (1.0, 0.995)),
        cast=(0.980, 1.020, 1.000), sat=1.05,
        shadows=(0.97, 1.00, 1.03), highlights=(1.0, 1.0, 1.0), grain=0.012),
    "Fujifilm Pro 400H": dict(
        curve=((0.0, 0.03), (0.25, 0.27), (0.5, 0.52), (0.75, 0.76), (1.0, 0.97)),
        cast=(0.995, 1.010, 1.000), sat=0.88,
        shadows=(0.985, 1.015, 1.005), highlights=(1.0, 1.0, 1.0), grain=0.009),
    # ---- colour slide ----
    "Fujifilm Velvia 50": dict(
        curve=((0.0, 0.0), (0.25, 0.19), (0.5, 0.50), (0.75, 0.82), (1.0, 1.0)),
        cast=(1.000, 0.995, 1.010), sat=1.35,
        shadows=(1.0, 1.0, 1.0), highlights=(1.0, 1.0, 1.0), grain=0.004),
    "Fujifilm Provia 100F": dict(
        curve=((0.0, 0.0), (0.25, 0.23), (0.5, 0.51), (0.75, 0.79), (1.0, 1.0)),
        cast=(1.000, 1.000, 1.000), sat=1.08,
        shadows=(1.0, 1.0, 1.0), highlights=(1.0, 1.0, 1.0), grain=0.005),
    "Kodachrome 64": dict(
        curve=((0.0, 0.0), (0.25, 0.20), (0.5, 0.50), (0.75, 0.80), (1.0, 1.0)),
        cast=(1.050, 1.000, 0.950), sat=1.15,
        shadows=(0.97, 1.005, 1.02), highlights=(1.03, 1.0, 0.97), grain=0.007),
    # ---- cine ----
    "CineStill 800T": dict(
        curve=((0.0, 0.025), (0.25, 0.26), (0.5, 0.52), (0.75, 0.78), (1.0, 0.99)),
        cast=(0.900, 0.985, 1.100), sat=1.00,
        shadows=(0.96, 1.01, 1.05), highlights=(1.05, 0.99, 0.97), grain=0.018),
    # ---- black & white ----
    "Ilford HP5 Plus 400": dict(
        curve=((0.0, 0.015), (0.25, 0.25), (0.5, 0.52), (0.75, 0.78), (1.0, 0.99)),
        bw=(0.26, 0.55, 0.19), grain=0.016),
    "Kodak Tri-X 400": dict(
        curve=((0.0, 0.0), (0.25, 0.20), (0.5, 0.51), (0.75, 0.82), (1.0, 1.0)),
        bw=(0.30, 0.55, 0.15), grain=0.020),
    "Fujifilm Acros 100": dict(
        curve=((0.0, 0.005), (0.25, 0.245), (0.5, 0.51), (0.75, 0.775), (1.0, 0.97)),
        bw=(0.24, 0.58, 0.18), grain=0.006),
}

_DEFAULT_GRAIN = 0.012      # grain sigma when the toggle is on with no film chosen


def film_names() -> list[str]:
    """Combo entries: 'None' plus every simulated stock, in menu order."""
    return ["None"] + list(FILM_SIMS.keys())


def _tone_curve(channel: np.ndarray, points) -> np.ndarray:
    xs = np.array([p[0] for p in points], np.float32)
    ys = np.array([p[1] for p in points], np.float32)
    return np.interp(channel, xs, ys).astype(np.float32)


def _apply_film(img: np.ndarray, name: str = "", grain: bool = False) -> np.ndarray:
    """Apply a film-inspired look (and/or luminance grain) to a 0..1 float image.

    Deterministic: the grain uses a fixed seed, so the preview doesn't shimmer
    on every slider move and exports are reproducible.
    """
    out = img
    f = None
    if name:
        f = FILM_SIMS.get(name)
        if f is None:
            raise ValueError(f"Unknown film simulation: {name!r}")

    if f is not None:
        if "bw" in f:
            w = np.asarray(f["bw"], np.float32)
            w = w / w.sum()
            lum = out @ w
            lum = _tone_curve(lum, f["curve"])
            out = np.repeat(lum[..., None], 3, axis=2)
        else:
            out = np.clip(out * np.asarray(f["cast"], np.float32), 0.0, 1.0)
            out = _tone_curve(out, f["curve"])
            l = _luma(out)
            out = l[..., None] + (out - l[..., None]) * f["sat"]
            out = np.clip(out, 0.0, 1.0)
            sh = np.asarray(f["shadows"], np.float32) - 1.0
            hi = np.asarray(f["highlights"], np.float32) - 1.0
            if np.any(sh) or np.any(hi):
                l = _luma(out)
                mix = (1.0 + sh * ((1.0 - l) ** 2)[..., None]
                           + hi * (l ** 2)[..., None])
                out = np.clip(out * mix, 0.0, 1.0)

    if grain:
        sigma = f["grain"] if f is not None else _DEFAULT_GRAIN
        l = _luma(out)
        rng = np.random.default_rng(12345)
        noise = rng.standard_normal(l.shape).astype(np.float32)
        # Film grain lives in luminance and is strongest in the midtones.
        strength = (0.3 + 1.6 * l * (1.0 - l)) * sigma
        out = out + (noise * strength)[..., None]

    return np.clip(out, 0.0, 1.0)


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

    # 3.5 film simulation + grain (layered under the artistic look controls,
    # so a preset like Faded can still sit on top of a film look)
    if p.film or p.grain:
        out = _apply_film(out, p.film, grain=p.grain)

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
