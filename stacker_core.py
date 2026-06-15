"""
Astro Stacker - GUI-agnostic processing core.

Combines a sequence of night-sky frames into one image. Two modes:

  * "sharp_stars"  - register every frame onto a reference so the star field
                     overlaps, then combine. Stars sharpen and noise drops; the
                     static foreground, shifted to keep the stars fixed, smears.
  * "star_trails"  - don't register (fixed tripod): combine with a per-pixel
                     maximum ("lighten") so the foreground stays sharp and the
                     stars draw trails as the sky rotates.

Design notes
------------
* Frames are decoded to float32 RGB in 0..1 so every combine works in one space
  regardless of the source bit depth.
* Heavy/awkward dependencies degrade gracefully, mirroring the suite's existing
  pillow-heif handling: no rawpy -> RAW input disabled; no astroalign -> star
  alignment falls back to a coarse FFT translation; no tifffile -> 16/32-bit
  TIFF hidden; no astropy -> FITS hidden. numpy is the only hard requirement.
* There is deliberately NO camera-RAW export. A stack is demosaiced, multi-frame
  RGB data — it is not single-exposure sensor mosaic data, and the RAW containers
  are proprietary/read-only. The high-fidelity outputs are 16-bit TIFF, 32-bit
  float TIFF and FITS, which is what astro tools actually produce.
"""
from __future__ import annotations

import os
import logging

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# --- Optional dependencies (graceful degradation) ----------------------------
try:
    import rawpy  # RAW decode via libraw
    RAW_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    RAW_AVAILABLE = False
    logger.warning("rawpy unavailable, RAW input disabled: %r", exc)

try:
    import tifffile  # 16/32-bit RGB TIFF (Pillow's high-bit-depth RGB is awkward)
    TIFFFILE_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    TIFFFILE_AVAILABLE = False
    logger.warning("tifffile unavailable, 16/32-bit TIFF disabled: %r", exc)

try:
    from astropy.io import fits  # FITS output
    FITS_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    FITS_AVAILABLE = False
    logger.warning("astropy unavailable, FITS export disabled: %r", exc)

try:
    import astroalign  # star-asterism registration (optional; needs sep/compiler)
    ASTROALIGN_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    ASTROALIGN_AVAILABLE = False
    logger.info("astroalign not present (optional): %r", exc)

try:
    # scikit-image gives rotation+translation registration from wheels alone
    # (no C compiler), so it's the default aligner.
    from skimage.feature import ORB, match_descriptors
    from skimage.measure import ransac
    from skimage.transform import SimilarityTransform, warp as _sk_warp
    SKIMAGE_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    SKIMAGE_AVAILABLE = False
    logger.warning("scikit-image unavailable, alignment limited to translation: %r", exc)


# --- Formats -----------------------------------------------------------------
RAW_EXTENSIONS = ("cr2", "cr3", "nef", "arw", "dng", "raf", "rw2", "orf", "pef", "srw")
_PIL_INPUT_EXTENSIONS = ("jpg", "jpeg", "png", "tif", "tiff", "webp", "bmp")

# Output formats: key -> (label, needs). 'needs' None = always available.
_OUTPUT_FORMATS = [
    ("jpeg", "JPEG (8-bit)", None),
    ("png", "PNG (8-bit)", None),
    ("webp", "WEBP (8-bit)", None),
    ("tiff8", "TIFF (8-bit)", None),
    ("tiff16", "TIFF (16-bit)", "tifffile"),
    ("tiff32", "TIFF (32-bit float)", "tifffile"),
    ("fits", "FITS (32-bit float)", "astropy"),
]


def supported_input_extensions() -> list[str]:
    exts = list(_PIL_INPUT_EXTENSIONS)
    if RAW_AVAILABLE:
        exts += list(RAW_EXTENSIONS)
    return exts


def supported_output_formats() -> list[tuple[str, str]]:
    """List of (key, label) for formats available in this install."""
    avail = {"tifffile": TIFFFILE_AVAILABLE, "astropy": FITS_AVAILABLE}
    return [(k, label) for k, label, needs in _OUTPUT_FORMATS
            if needs is None or avail.get(needs, False)]


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lower().lstrip(".")


def is_raw(path: str) -> bool:
    return _ext(path) in RAW_EXTENSIONS


# --- Loading -----------------------------------------------------------------
def _decode_raw(path: str) -> np.ndarray:
    """Decode a RAW/DNG to float32 RGB in 0..1.

    libraw forbids calling postprocess() more than once on a single handle —
    a second call raises "Out of order call of libraw function". So each fallback
    attempt opens a FRESH rawpy.imread handle. Attempts go from astro-tuned
    (16-bit, linear, camera WB) to progressively simpler, covering linear/odd
    DNGs that reject the tuned settings; if all fail, the real error surfaces.
    """
    attempts = (
        dict(output_bps=16, use_camera_wb=True, no_auto_bright=True, gamma=(1, 1)),
        dict(output_bps=16, no_auto_bright=True),
        dict(),  # library defaults (8-bit) as a last resort
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
            logger.info("RAW decode attempt failed for %s: %r", os.path.basename(path), exc)
    raise RuntimeError(f"Could not decode {os.path.basename(path)}: {last_exc}")


def load_frame(path: str) -> np.ndarray:
    """Decode one frame to float32 RGB in 0..1, whatever the source format."""
    if is_raw(path):
        if not RAW_AVAILABLE:
            raise RuntimeError("RAW input requires rawpy, which isn't installed.")
        return _decode_raw(path)

    img = Image.open(path)
    if img.mode not in ("RGB", "I;16", "I"):
        img = img.convert("RGB")
    arr = np.asarray(img)
    if arr.dtype == np.uint8:
        arr = arr.astype(np.float32) / 255.0
    elif arr.dtype in (np.uint16, np.int32):
        arr = arr.astype(np.float32) / float(np.iinfo(arr.dtype).max)
    else:
        arr = arr.astype(np.float32)
    if arr.ndim == 2:  # grayscale -> 3 channels
        arr = np.stack([arr] * 3, axis=-1)
    return arr[:, :, :3]


def _downscale(arr: np.ndarray, max_edge: int | None) -> np.ndarray:
    if not max_edge:
        return arr
    h, w = arr.shape[:2]
    scale = max_edge / float(max(h, w))
    if scale >= 1.0:
        return arr
    img = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))
    img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    return np.asarray(img).astype(np.float32) / 255.0


# --- Alignment ---------------------------------------------------------------
def _luma(arr: np.ndarray) -> np.ndarray:
    return arr[:, :, 0] * 0.2126 + arr[:, :, 1] * 0.7152 + arr[:, :, 2] * 0.0722


def align_to_reference(img: np.ndarray, ref: np.ndarray) -> tuple[np.ndarray, bool]:
    """Register img onto ref using the star field. Returns (aligned, ok).

    Tiers, best first: astroalign (if installed) → scikit-image ORB+RANSAC
    similarity (rotation+translation, wheels-only) → whole-image FFT translation
    → unchanged with ok=False so the caller can drop the frame.
    """
    if ASTROALIGN_AVAILABLE:
        try:
            transform, _ = astroalign.find_transform(_luma(img), _luma(ref))
            out = np.zeros_like(img)
            for c in range(3):
                out[:, :, c] = astroalign.apply_transform(
                    transform, img[:, :, c], ref[:, :, c])[0]
            return out, True
        except Exception as exc:  # noqa: BLE001 — fall through
            logger.info("astroalign failed on a frame: %r", exc)

    if SKIMAGE_AVAILABLE:
        try:
            return _align_skimage(img, ref), True
        except Exception as exc:  # noqa: BLE001 — fall through to FFT
            logger.info("scikit-image align failed, FFT fallback: %r", exc)

    try:
        dy, dx = _fft_shift(_luma(img), _luma(ref))
        out = np.zeros_like(img)
        for c in range(3):
            out[:, :, c] = np.roll(np.roll(img[:, :, c], dy, axis=0), dx, axis=1)
        return out, True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Alignment failed entirely on a frame: %r", exc)
        return img, False


def _align_skimage(img: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """ORB keypoints + RANSAC similarity transform; warp img onto ref's grid."""
    def kp(gray):
        orb = ORB(n_keypoints=400, fast_threshold=0.05)
        orb.detect_and_extract(gray.astype(np.float64))
        return orb.keypoints, orb.descriptors

    k_mov, d_mov = kp(_luma(img))
    k_ref, d_ref = kp(_luma(ref))
    matches = match_descriptors(d_mov, d_ref, cross_check=True)
    if len(matches) < 6:
        raise RuntimeError("too few star matches to align")
    src = k_mov[matches[:, 0]][:, ::-1]   # (x, y)
    dst = k_ref[matches[:, 1]][:, ::-1]
    model, inliers = ransac((src, dst), SimilarityTransform, min_samples=3,
                            residual_threshold=2.0, max_trials=2000)
    if model is None or inliers is None or int(inliers.sum()) < 4:
        raise RuntimeError("alignment did not converge")
    out = np.zeros_like(img)
    for c in range(3):
        out[:, :, c] = _sk_warp(img[:, :, c], model.inverse, output_shape=img.shape[:2],
                                order=1, mode="constant", cval=0.0, preserve_range=True)
    return out.astype(np.float32)


def _fft_shift(a: np.ndarray, b: np.ndarray) -> tuple[int, int]:
    """Integer (dy, dx) that best shifts a onto b, via phase correlation."""
    fa = np.fft.fft2(a)
    fb = np.fft.fft2(b)
    r = fa * np.conj(fb)
    r /= np.abs(r) + 1e-12
    cc = np.fft.ifft2(r).real
    peak = np.unravel_index(np.argmax(cc), cc.shape)
    dy = peak[0] if peak[0] <= a.shape[0] // 2 else peak[0] - a.shape[0]
    dx = peak[1] if peak[1] <= a.shape[1] // 2 else peak[1] - a.shape[1]
    return int(dy), int(dx)


# --- Stacking ----------------------------------------------------------------
COMBINE_METHODS = [
    ("mean", "Average (mean)"),
    ("median", "Median (rejects planes/satellites)"),
    ("sigma", "Sigma-clipped average"),
    ("max", "Lighten (max) — for trails"),
]


def _combine(frames: list[np.ndarray], method: str) -> np.ndarray:
    stack = np.stack(frames, axis=0)
    if method == "median":
        return np.median(stack, axis=0)
    if method == "sigma":
        mean = stack.mean(axis=0)
        std = stack.std(axis=0) + 1e-6
        mask = np.abs(stack - mean) <= 2.5 * std
        summed = np.where(mask, stack, 0).sum(axis=0)
        counts = mask.sum(axis=0)
        return summed / np.maximum(counts, 1)
    if method == "max":
        return stack.max(axis=0)
    return stack.mean(axis=0)  # default: mean


# Strength of the smooth-sky trail blend: how many per-pixel std deviations a
# value must rise above the averaged background to count as a trail rather than
# noise. Lower keeps fainter trails (but more residual grain); higher is cleaner.
SMOOTH_K = 2.0


def _trail_smooth(acc_max, base, std):
    """Clean-sky lighten: smooth averaged background + only the bright trail
    excess, so the dark sky's amplified max-noise is replaced by the low-noise
    average. Trades away the very faintest trails (they sit at the noise level)."""
    return base + np.maximum(0.0, acc_max - base - SMOOTH_K * (std + 1e-6))


def _combine_trails_smooth(frames: list[np.ndarray]) -> np.ndarray:
    s = np.stack(frames, axis=0)
    return _trail_smooth(s.max(axis=0), s.mean(axis=0), s.std(axis=0))


def stack(paths: list[str],
          mode: str = "sharp_stars",
          method: str = "median",
          ref_index: int | None = None,
          max_edge: int | None = None,
          reject_anomalies: bool = False,
          smooth_sky: bool = False,
          progress_cb=None,
          cancel_cb=None) -> dict:
    """Stack the given frames and return a result dict.

    mode: "sharp_stars" (align on stars) or "star_trails" (no align, lighten).
    method: combine method; star_trails forces "max".
    max_edge: downscale longest edge to this many px (used for fast previews).
    reject_anomalies: try to suppress transient intruders (planes, flashes,
        passing light, drifting cloud). In aligned mode this is a clean per-pixel
        sigma-clip; in trail mode — where a real star trail is itself a brief
        bright blip and can't be told apart per-pixel — it instead screens out
        whole frames whose brightness spikes against the sequence, at the cost of
        slightly shorter trails where frames are dropped.
    progress_cb(done, total, message); cancel_cb() -> bool.

    Returns {'image', 'used', 'failed', 'rejected'} where 'rejected' is the
    number of contaminated frames dropped by the trail screener.
    """
    if not paths:
        raise ValueError("No frames to stack.")

    def report(done, total, msg):
        if progress_cb:
            progress_cb(done, total, msg)

    def cancelled() -> bool:
        return bool(cancel_cb and cancel_cb())

    if mode == "star_trails":
        method = "max"
    elif reject_anomalies and method in ("mean", "max"):
        # Aligned stars are consistent frame-to-frame, so a sigma-clip cleanly
        # rejects per-pixel transients (planes/flashes) — upgrade to it.
        method = "sigma"

    total = len(paths)
    if ref_index is None:
        ref_index = total // 2

    report(0, total, "Loading reference frame…")
    ref = None
    for j in [ref_index] + [k for k in range(total) if k != ref_index]:
        try:
            ref = _downscale(load_frame(paths[j]), max_edge)
            ref_index = j
            break
        except Exception as exc:  # noqa: BLE001 — a bad reference shouldn't end the run
            report(0, total, f"Skipping {os.path.basename(paths[j])} as reference: {exc}")
    if ref is None:
        raise RuntimeError("No frames could be loaded.")

    # Trails without anomaly screening can STREAM: keep a running max (plus
    # running mean/variance for smooth-sky) instead of holding every frame, so
    # even dozens of full-resolution DNGs stay within memory. Aligned mode and
    # the anomaly screener still need all frames, so they use the list path.
    streaming = (mode == "star_trails" and not reject_anomalies)
    frames: list[np.ndarray] = []
    acc_max = acc_sum = acc_sumsq = None
    acc_n = 0
    used = failed = 0
    for i, p in enumerate(paths):
        if cancelled():
            break
        try:
            arr = ref if i == ref_index else _downscale(load_frame(p), max_edge)
            if arr.shape != ref.shape:
                arr = _resize_to(arr, ref.shape)
            if mode == "sharp_stars" and i != ref_index:
                arr, ok = align_to_reference(arr, ref)
                if not ok:
                    failed += 1
                    report(i + 1, total, f"Skipped (no alignment): {os.path.basename(p)}")
                    continue
            if streaming:
                if acc_max is None:
                    acc_max = arr.copy()
                    if smooth_sky:
                        acc_sum = arr.astype(np.float64)
                        acc_sumsq = acc_sum ** 2
                else:
                    np.maximum(acc_max, arr, out=acc_max)
                    if smooth_sky:
                        acc_sum += arr
                        acc_sumsq += arr.astype(np.float64) ** 2
                acc_n += 1
            else:
                frames.append(arr)
            used += 1
            report(i + 1, total, f"Stacked {os.path.basename(p)}")
        except Exception as exc:  # noqa: BLE001 — one bad frame shouldn't kill the run
            failed += 1
            report(i + 1, total, f"ERROR {os.path.basename(p)}: {exc}")

    rejected = 0
    if streaming:
        if acc_max is None:
            raise RuntimeError("No frames could be stacked.")
        report(total, total, "Combining…")
        if smooth_sky and acc_n >= 2:
            base = (acc_sum / acc_n).astype(np.float32)
            var = np.maximum(acc_sumsq / acc_n - (acc_sum / acc_n) ** 2, 0.0)
            result = _trail_smooth(acc_max, base, np.sqrt(var).astype(np.float32))
        else:
            result = acc_max
    else:
        if not frames:
            raise RuntimeError("No frames could be stacked.")
        if mode == "star_trails" and reject_anomalies:
            frames, rejected = _screen_frames(frames)
            used -= rejected
            report(total, total, f"Anomaly screening dropped {rejected} contaminated frame(s)")
        report(total, total, "Combining…")
        if mode == "star_trails" and smooth_sky:
            result = _combine_trails_smooth(frames)
        else:
            result = _combine(frames, method)

    result = np.clip(result, 0.0, 1.0)
    return {"image": result, "used": used, "failed": failed, "rejected": rejected}


def _screen_frames(frames: list[np.ndarray], k: float = 3.0) -> tuple[list[np.ndarray], int]:
    """Drop frames whose bright content spikes against the sequence.

    Per frame we count pixels well above the sequence's per-pixel median (the
    "clean" baseline). Every frame contributes a roughly steady count from its
    own stars; a frame with a cloud, stray light or a plane carries extra bright
    pixels and stands out. Frames beyond a robust median±k·MAD band are dropped.
    Conservative by design: it removes spikes, not the gradual baseline, and
    never drops below two frames.
    """
    if len(frames) < 4:
        return frames, 0
    arr = np.stack(frames, axis=0)
    luma = arr[..., 0] * 0.2126 + arr[..., 1] * 0.7152 + arr[..., 2] * 0.0722
    baseline = np.median(luma, axis=0)
    scores = (luma - baseline[None] > 0.12).reshape(len(frames), -1).sum(axis=1).astype(np.float64)
    med = np.median(scores)
    # Spread from the clean (lower) side only: contaminated frames sit above the
    # median, so including them would inflate the spread and let moderate
    # intruders mask each other. The clean side gives a tight, honest threshold.
    lower = scores[scores <= med]
    spread = np.median(np.abs(lower - med)) + 1e-9
    keep = scores <= med + k * spread
    if keep.sum() < 2:                      # never strip the stack to nothing
        return frames, 0
    kept = [f for f, kp in zip(frames, keep) if kp]
    return kept, len(frames) - len(kept)


def _resize_to(arr: np.ndarray, shape) -> np.ndarray:
    img = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))
    img = img.resize((shape[1], shape[0]), Image.LANCZOS)
    return np.asarray(img).astype(np.float32) / 255.0


# --- Export ------------------------------------------------------------------
def export_image(arr: np.ndarray, path: str, fmt_key: str, quality: int = 95) -> str:
    """Write the stacked float image to `path` in the chosen format/bit depth."""
    arr = np.clip(arr, 0.0, 1.0)

    if fmt_key == "tiff16":
        if not TIFFFILE_AVAILABLE:
            raise RuntimeError("16-bit TIFF needs tifffile.")
        tifffile.imwrite(path, (arr * 65535.0 + 0.5).astype(np.uint16), photometric="rgb")
        return path
    if fmt_key == "tiff32":
        if not TIFFFILE_AVAILABLE:
            raise RuntimeError("32-bit TIFF needs tifffile.")
        tifffile.imwrite(path, arr.astype(np.float32), photometric="rgb")
        return path
    if fmt_key == "fits":
        if not FITS_AVAILABLE:
            raise RuntimeError("FITS needs astropy.")
        # FITS convention: axis order (channel, row, col).
        fits.PrimaryHDU(np.moveaxis(arr.astype(np.float32), -1, 0)).writeto(path, overwrite=True)
        return path

    # 8-bit raster formats via Pillow.
    img = Image.fromarray((arr * 255.0 + 0.5).astype(np.uint8), mode="RGB")
    fmt_map = {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "tiff8": "TIFF"}
    fmt = fmt_map.get(fmt_key)
    if not fmt:
        raise ValueError(f"Unknown output format: {fmt_key}")
    save_kwargs = {}
    if fmt in ("JPEG", "WEBP"):
        save_kwargs["quality"] = int(quality)
    img.save(path, fmt, **save_kwargs)
    return path


def extension_for_format(fmt_key: str) -> str:
    return {"jpeg": "jpg", "png": "png", "webp": "webp", "tiff8": "tiff",
            "tiff16": "tiff", "tiff32": "tiff", "fits": "fits"}[fmt_key]
