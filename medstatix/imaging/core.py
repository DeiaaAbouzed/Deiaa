"""Histopathology / IHC image engine.

Design principles (Rossner & Yamada 2004; Nature/Cell/JBC image-integrity policies):
* The original image is never modified; every enhancement is a *global*
  operation applied uniformly to the whole image and recorded in an edit log.
* No generative / AI pixel synthesis, no cloning, no local retouching:
  nothing is added to or removed from the tissue.
* Every processed image is checked against the original with structural
  metrics (SSIM on intensity-normalised images, edge correlation) so that
  the user can prove cell detail was not altered.
* Annotations are vector overlays drawn on top of the image (arrows,
  labels, outlines, scale bar); they never alter the underlying pixels.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime

import numpy as np
from scipy import ndimage as ndi
from PIL import Image
from skimage import color, exposure, filters, measure, morphology, restoration, segmentation, feature
from skimage.metrics import structural_similarity

# ----------------------------------------------------------------------------- I/O


def load_image(path: str) -> np.ndarray:
    im = Image.open(path)
    if im.mode in ("I;16", "I;16B", "I"):
        a = np.asarray(im, dtype=np.float32)
        a = (a - a.min()) / max(np.ptp(a), 1) * 255
        im = Image.fromarray(a.astype(np.uint8)).convert("RGB")
    elif im.mode != "RGB":
        im = im.convert("RGB")
    return np.asarray(im).copy()


def save_image(arr: np.ndarray, path: str, dpi: int = 600, width_mm: float | None = None):
    """Save an RGB image as PNG / TIFF (LZW) / JPEG / PDF / EPS / SVG at the given resolution.

    dpi is written as metadata. If width_mm is given the image is resampled (Lanczos) so that it prints at that
    width at the requested dpi; otherwise the original pixels are kept untouched."""
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    if width_mm:
        w_px = int(round(width_mm / 25.4 * dpi))
        if w_px > 0 and w_px != im.width:
            im = im.resize((w_px, int(round(im.height * w_px / im.width))), Image.LANCZOS)
    ext = path.lower().rsplit(".", 1)[-1]
    if ext == "svg":
        import base64, io
        buf = io.BytesIO(); im.save(buf, format="PNG", dpi=(dpi, dpi))
        w_mm, h_mm = im.width / dpi * 25.4, im.height / dpi * 25.4
        with open(path, "w", encoding="utf-8") as f:
            f.write(f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                    f'width="{w_mm:.2f}mm" height="{h_mm:.2f}mm" viewBox="0 0 {im.width} {im.height}">'
                    f'<image width="{im.width}" height="{im.height}" xlink:href="data:image/png;base64,'
                    f'{base64.b64encode(buf.getvalue()).decode()}"/></svg>')
        return
    if ext == "pdf":
        im.save(path, "PDF", resolution=float(dpi))
        return
    if ext == "eps":
        im.convert("RGB").save(path, "EPS")
        return
    kw = {"dpi": (dpi, dpi)}
    if ext in ("tif", "tiff"):
        kw["compression"] = "tiff_lzw"
    elif ext in ("jpg", "jpeg"):
        kw["quality"] = 98
        kw["subsampling"] = 0
    im.save(path, **kw)


def to_float(img):
    return img.astype(np.float64) / 255.0


def to_uint8(f):
    return np.clip(np.round(f * 255.0), 0, 255).astype(np.uint8)


# ----------------------------------------------------------------------------- operations
OPS = {
    "white_balance": ("White balance (background → neutral)", "توازن اللون الأبيض (الخلفية ← محايد)"),
    "levels": ("Brightness / contrast (linear levels)", "الإضاءة والتباين (مستويات خطية)"),
    "auto_levels": ("Auto contrast stretch (0.5–99.5 percentile)", "تمديد التباين التلقائي"),
    "gamma": ("Gamma (mid-tones)", "جاما (الدرجات المتوسطة)"),
    "saturation": ("Colour saturation (global)", "تشبع اللون (كلي)"),
    "reinhard": ("Stain normalization — Reinhard (LAB)", "توحيد الصبغة — رينهارد"),
    "macenko": ("Stain normalization — Macenko (H&E)", "توحيد الصبغة — ماسينكو (H&E)"),
    "denoise": ("Mild denoising (edge-preserving)", "إزالة ضوضاء خفيفة (تحافظ على الحواف)"),
    "flatfield": ("Uneven illumination correction (flat-field / shading)", "تصحيح الإضاءة غير المتساوية (Flat-field)"),
    "sharpen": ("Mild sharpening (unsharp mask, whole image)", "زيادة حدة خفيفة (Unsharp mask للصورة كاملة)"),
    "crop": ("Crop to the eyepiece field", "قص حدود دائرة العدسة"),
    "background_white": ("Background whitening (neutral white slide background)", "تبييض الخلفية (خلفية الشريحة بيضاء محايدة)"),
    "black_point": ("Haze removal (black point)", "إزالة الضبابية (نقطة الأسود)"),
    "clahe": ("Mild local contrast (CLAHE on lightness only)", "تباين موضعي خفيف (CLAHE على الإضاءة فقط)"),
}

# Reference H&E appearance (target stain vectors and LAB statistics) — a well-stained
# public reference used by Macenko et al. 2009 / Reinhard et al. 2001 implementations.
REF_HE = np.array([[0.5626, 0.2159], [0.7201, 0.8012], [0.4062, 0.5581]])
REF_MAX_C = np.array([1.9705, 1.0308])
REF_LAB_MEAN = np.array([63.0, 25.0, -12.0])
REF_LAB_STD = np.array([17.0, 9.5, 7.5])


def _tissue_mask(img, thr=0.82):
    g = color.rgb2gray(img) if img.dtype != np.uint8 else color.rgb2gray(img)
    return g < thr


def op_white_balance(f, strength=1.0, percentile=99.0):
    """Scale each channel so that the bright background becomes neutral grey/white.
    A single multiplicative gain per channel is applied to every pixel."""
    lum = f.mean(2)
    thr = np.percentile(lum, percentile - 4)
    bg = f[lum >= thr]
    if len(bg) < 50:
        bg = f.reshape(-1, 3)
    ref = np.percentile(bg, 50, axis=0)
    target = ref.max()
    gains = target / np.maximum(ref, 1e-6)
    gains = 1 + (gains - 1) * strength
    return np.clip(f * gains, 0, 1), {"channel_gains_RGB": [round(float(g), 4) for g in gains]}


def op_levels(f, brightness=0.0, contrast=1.0):
    """out = (in − 0.5)·contrast + 0.5 + brightness   (identical for all pixels/channels)."""
    out = (f - 0.5) * contrast + 0.5 + brightness
    return np.clip(out, 0, 1), {"brightness": brightness, "contrast": contrast}


def op_auto_levels(f, low=0.5, high=99.5):
    lum = f.mean(2)
    lo, hi = np.percentile(lum, [low, high])
    out = (f - lo) / max(hi - lo, 1e-6)
    return np.clip(out, 0, 1), {"black_point": round(float(lo), 4), "white_point": round(float(hi), 4)}


def op_gamma(f, gamma=1.0):
    return np.clip(f, 0, 1) ** (1 / gamma), {"gamma": gamma}


def op_saturation(f, factor=1.0):
    hsv = color.rgb2hsv(f)
    hsv[..., 1] = np.clip(hsv[..., 1] * factor, 0, 1)
    return color.hsv2rgb(hsv), {"factor": factor}


def op_reinhard(f, target_mean=None, target_std=None):
    """Reinhard colour transfer in CIELAB, statistics computed on tissue pixels only."""
    lab = color.rgb2lab(f)
    m = _tissue_mask(f)
    if m.sum() < 100:
        m = np.ones(m.shape, bool)
    mu = lab[m].mean(0)
    sd = lab[m].std(0) + 1e-6
    tm = np.asarray(target_mean if target_mean is not None else REF_LAB_MEAN, float)
    ts = np.asarray(target_std if target_std is not None else REF_LAB_STD, float)
    out = (lab - mu) / sd * ts + tm
    rgb = color.lab2rgb(out)
    return np.clip(rgb, 0, 1), {"source_LAB_mean": mu.round(2).tolist(), "target_LAB_mean": tm.round(2).tolist(),
                                "source_LAB_sd": sd.round(2).tolist(), "target_LAB_sd": ts.round(2).tolist()}


def macenko_vectors(img8, Io=240, alpha=1, beta=0.15):
    I = img8.reshape(-1, 3).astype(float)
    OD = -np.log((I + 1) / Io)
    ODhat = OD[~np.any(OD < beta, axis=1)]
    if len(ODhat) < 50:
        raise ValueError("Too little stained tissue for Macenko estimation.")
    _, eigvecs = np.linalg.eigh(np.cov(ODhat.T))
    That = ODhat.dot(eigvecs[:, 1:3])
    phi = np.arctan2(That[:, 1], That[:, 0])
    minPhi, maxPhi = np.percentile(phi, alpha), np.percentile(phi, 100 - alpha)
    vMin = eigvecs[:, 1:3].dot(np.array([(np.cos(minPhi), np.sin(minPhi))]).T)
    vMax = eigvecs[:, 1:3].dot(np.array([(np.cos(maxPhi), np.sin(maxPhi))]).T)
    HE = np.array((vMin[:, 0], vMax[:, 0])).T if vMin[0] > vMax[0] else np.array((vMax[:, 0], vMin[:, 0])).T
    HE = HE * np.sign(HE.sum(0))
    Y = OD.T
    C = np.linalg.lstsq(HE, Y, rcond=None)[0]
    maxC = np.array([np.percentile(C[0, :], 99), np.percentile(C[1, :], 99)])
    return HE, C, maxC


def op_macenko(f, Io=240):
    """Macenko et al. 2009: estimate H and E stain vectors by SVD of optical density and map them to a reference.
    Concentrations of each stain per pixel are preserved (scaled), so tissue structure is unchanged."""
    img8 = to_uint8(f)
    h, w, _ = img8.shape
    HE, C, maxC = macenko_vectors(img8, Io)
    C2 = C * (REF_MAX_C / maxC)[:, None]
    Inorm = Io * np.exp(-REF_HE.dot(C2))
    Inorm = np.clip(Inorm, 0, 255).T.reshape(h, w, 3)
    return Inorm / 255.0, {"estimated_stain_vectors_HE": HE.round(4).tolist(), "reference_vectors": REF_HE.round(4).tolist()}


def noise_sigma(f):
    """Immerkaer (1996) fast noise variance estimation, averaged over channels."""
    from scipy.signal import convolve2d
    M = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], float)
    sig = []
    for c in range(f.shape[2]):
        H, W = f.shape[:2]
        conv = np.abs(convolve2d(f[..., c], M, mode="valid"))
        sig.append(math.sqrt(math.pi / 2) / (6 * (W - 2) * (H - 2)) * conv.sum())
    return float(np.mean(sig))


def op_denoise(f, strength=0.5):
    """Non-local means with a small filter strength estimated from the image noise level.
    strength 0–1 maps to h = (0.4–0.9) × sigma_est; patch size 5, search 13."""
    sigma = noise_sigma(f)
    h = (0.4 + 0.5 * float(np.clip(strength, 0, 1))) * sigma
    out = restoration.denoise_nl_means(f, h=h, sigma=sigma, patch_size=5, patch_distance=6, channel_axis=-1, fast_mode=True)
    return np.clip(out, 0, 1), {"estimated_noise_sigma": round(sigma, 5), "h": round(h, 5), "method": "non-local means"}


def shading_surface(f, tiles=12, channel=None):
    """Estimate the illumination (shading) field as a smooth 2nd-order polynomial surface fitted, robustly,
    to the brightness of *background* pixels (bright, unstained: low saturation) in a grid of tiles.

    A quadratic surface has only six coefficients, so it can model vignetting / an uneven lamp but cannot
    carry any tissue structure. Returns (surface H×W, unevenness 0–1, number of background tiles used)."""
    lum = f.mean(2)
    val = lum if channel is None else f[..., channel]
    um = _unstained_mask(f)
    H, W = lum.shape
    ty, tx = max(H // tiles, 8), max(W // tiles, 8)
    ny, nx = max(H // ty, 1), max(W // tx, 1)
    bright_thr = np.percentile(lum, 60)
    yy, xx, vv = [], [], []
    for i in range(ny):
        for j in range(nx):
            m = um[i * ty:(i + 1) * ty, j * tx:(j + 1) * tx]
            if m.mean() >= 0.03:
                vv.append(np.percentile(val[i * ty:(i + 1) * ty, j * tx:(j + 1) * tx][m], 80))
                yy.append((i + 0.5) / ny - 0.5); xx.append((j + 0.5) / nx - 0.5)
    n_bg = len(vv)
    if n_bg < 8:  # little background: fall back to the bright percentile of every tile (less specific)
        yy, xx, vv = [], [], []
        for i in range(ny):
            for j in range(nx):
                vv.append(np.percentile(val[i * ty:(i + 1) * ty, j * tx:(j + 1) * tx], 97))
                yy.append((i + 0.5) / ny - 0.5); xx.append((j + 0.5) / nx - 0.5)
    yy, xx, vv = map(np.asarray, (yy, xx, vv))
    A = np.stack([np.ones_like(xx), xx, yy, xx * xx, yy * yy, xx * yy], 1)
    w = np.ones_like(vv)
    for _ in range(4):
        coef = np.linalg.lstsq(A * w[:, None], vv * w, rcond=None)[0]
        r = vv - A @ coef
        sc = np.median(np.abs(r)) * 1.4826 + 1e-3
        w = 1 / np.maximum(1, np.abs(r) / (2 * sc))
    Y, X = np.mgrid[0:H, 0:W]
    Yn, Xn = (Y + 0.5) / H - 0.5, (X + 0.5) / W - 0.5
    surf = coef[0] + coef[1] * Xn + coef[2] * Yn + coef[3] * Xn ** 2 + coef[4] * Yn ** 2 + coef[5] * Xn * Yn
    fit = A @ coef
    unev = float((fit.max() - fit.min()) / max(fit.max(), 1e-3))
    return np.clip(surf, 0.05, None), unev, n_bg


def _unstained_mask(f):
    """Pixels that look like empty slide: bright, and with the same chromaticity as the slide background (so the test
    still works under a colour cast); falls back to low absolute saturation."""
    lum = f.mean(2)
    bg, _ = background_colour(f)
    bright = lum > np.percentile(lum, 60)
    if bg is None:
        sat = (f.max(2) - f.min(2)) / np.maximum(f.max(2), 1e-3)
        return bright & (sat < 0.14)
    chrom = f / np.maximum(lum[..., None], 1e-3)
    bgc = bg / max(float(np.mean(bg)), 1e-3)
    return bright & (np.abs(chrom - bgc).max(2) < 0.07)


def _bg_tiles(f, tiles=12):
    """Background tiles: (yy, xx, rgb) of bright, unstained pixels per tile (normalised tile centres)."""
    lum = f.mean(2)
    um = _unstained_mask(f)
    H, W = lum.shape
    ty, tx = max(H // tiles, 8), max(W // tiles, 8)
    ny, nx = max(H // ty, 1), max(W // tx, 1)
    yy, xx, cc = [], [], []
    for i in range(ny):
        for j in range(nx):
            sl = (slice(i * ty, (i + 1) * ty), slice(j * tx, (j + 1) * tx))
            m = um[sl]
            if m.mean() >= 0.15:
                cc.append(np.median(f[sl][m], axis=0))
                yy.append((i + 0.5) / ny - 0.5); xx.append((j + 0.5) / nx - 0.5)
    return np.asarray(yy), np.asarray(xx), np.asarray(cc).reshape(-1, 3)


def chroma_planes(f):
    """Colour drift of the background across the field, modelled for each channel as a *plane* (3 coefficients) of
    the channel/lightness ratio, fitted robustly to background tiles. Returns (ratio fields H×W×3 or None, drift)."""
    yy, xx, cc = _bg_tiles(f)
    if len(cc) < 10 or (np.ptp(yy) < 0.4 and np.ptp(xx) < 0.4):
        return None, 0.0
    ratio = cc / np.maximum(cc.mean(1, keepdims=True), 1e-3)
    quad = len(cc) >= 30
    A = np.stack([np.ones_like(xx), xx, yy] + ([xx * xx, yy * yy, xx * yy] if quad else []), 1)
    H, W = f.shape[:2]
    Y, X = np.mgrid[0:H, 0:W]
    Yn, Xn = (Y + 0.5) / H - 0.5, (X + 0.5) / W - 0.5
    fields, drift = [], 0.0
    for c in range(3):
        v = ratio[:, c]; w = np.ones_like(v)
        for _ in range(4):
            coef = np.linalg.lstsq(A * w[:, None], v * w, rcond=None)[0]
            r = v - A @ coef
            sc = np.median(np.abs(r)) * 1.4826 + 1e-3
            w = 1 / np.maximum(1, np.abs(r) / (2 * sc))
        fit = coef[0] + coef[1] * Xn + coef[2] * Yn
        if quad:
            fit = fit + coef[3] * Xn ** 2 + coef[4] * Yn ** 2 + coef[5] * Xn * Yn
        fields.append(fit / coef[0])
        drift = max(drift, float(np.abs(fit / coef[0] - 1).max()))
    return np.stack(fields, -1), drift


def shading_chroma(f):
    return chroma_planes(f)[1]


def op_flatfield(f, strength=1.0, colour=True):
    """Shading correction: divide by a smooth 2nd-order polynomial illumination surface fitted to the background
    (same for all channels). With colour=True, a gentle colour-drift correction is added: each channel/lightness ratio
    of the background is modelled as a plane and divided out (limited to ±8 %), which removes e.g. bluish edges / a warm
    centre in the way a blank-field reference would. Corrects vignetting / uneven lamp illumination."""
    k = float(np.clip(strength, 0, 1))
    field, unev, n_bg = shading_surface(f)
    gain = np.clip(np.percentile(field, 98) / np.maximum(field, 1e-3), 0.7, 1.6)
    gain = 1 + (gain - 1) * k
    out = f * gain[..., None]
    drift = 0.0
    if colour:
        planes, drift = chroma_planes(f)
        if planes is not None:
            out = out / np.clip(1 + (planes - 1) * k, 0.92, 1.08)
    return np.clip(out, 0, 1), {"gain_min": round(float(gain.min()), 3), "gain_max": round(float(gain.max()), 3),
                                "colour_drift_corrected": round(drift, 3), "background_tiles": n_bg,
                                "method": "robust 2nd-order polynomial surface fitted to background pixels"}


def op_sharpen(f, amount=0.4, radius=1.0):
    """Unsharp mask applied identically to the whole image (amount ≤ 0.8, radius ≤ 2 px)."""
    amount = float(np.clip(amount, 0, 0.8)); radius = float(np.clip(radius, 0.5, 2.0))
    blur = np.stack([filters.gaussian(f[..., c], radius) for c in range(3)], -1)
    return np.clip(f + amount * (f - blur), 0, 1), {"amount": amount, "radius_px": radius}


def find_eyepiece_field(img, min_frac=0.25):
    """Detect the circular eyepiece field in a phone photo taken through the microscope eyepiece (bright disc on a
    dark surround). Returns (cy, cx, r) in pixels or None when the image has no dark surround."""
    a = np.asarray(img)
    s = max(1, max(a.shape[:2]) // 600)
    lum = a[::s, ::s].mean(2) / 255.0
    H, W = lum.shape
    border = np.concatenate([lum[:H // 20].ravel(), lum[-H // 20:].ravel(), lum[:, :W // 20].ravel(), lum[:, -W // 20:].ravel()])
    if np.percentile(border, 60) > 0.25:  # corners not dark → no eyepiece circle
        return None
    thr = filters.threshold_otsu(lum)
    m = ndi.binary_opening(lum > max(thr, 0.15), structure=morphology.disk(3))
    lab = measure.label(m)
    if lab.max() == 0:
        return None
    r = max(measure.regionprops(lab), key=lambda r: r.area)
    if r.area < min_frac * H * W * 0.5:
        return None
    cy, cx = r.centroid
    y0, x0, y1, x1 = r.bbox
    rad = min(math.sqrt(r.area / math.pi), (y1 - y0) / 2, (x1 - x0) / 2)
    return cy * s, cx * s, rad * s


def op_crop(f, box=None):
    """Rectangular crop (box = y0, y1, x0, x1). Cropping removes only the dark area outside the eyepiece field."""
    if not box:
        return f, {}
    y0, y1, x0, x1 = [int(v) for v in box]
    return f[y0:y1, x0:x1], {"box_y0_y1_x0_x1": [y0, y1, x0, x1]}


def eyepiece_crop_box(img, margin=0.86):
    """Largest axis-aligned rectangle inside the eyepiece circle (keeps the image aspect ratio close to 4:3)."""
    c = find_eyepiece_field(img)
    if c is None:
        return None
    cy, cx, r = c
    r *= margin
    ang = math.atan(3 / 4) if img.shape[1] >= img.shape[0] else math.atan(4 / 3)
    hw, hh = r * math.cos(ang), r * math.sin(ang)
    H, W = img.shape[:2]
    y0, y1 = int(max(0, cy - hh)), int(min(H, cy + hh)); x0, x1 = int(max(0, cx - hw)), int(min(W, cx + hw))
    if (y1 - y0) < 0.2 * H or (x1 - x0) < 0.2 * W:
        return None
    return [y0, y1, x0, x1]


def background_colour(f):
    """Robust colour of the empty slide background: the brightest, smoothest pixels (works even with a colour cast).
    Returns (rgb, fraction_of_image) or (None, 0)."""
    st = int(max(1, math.ceil(max(f.shape[:2]) / 700)))
    f = f[::st, ::st]
    lum = f.mean(2)
    tex = ndi.uniform_filter(lum * lum, 5) - ndi.uniform_filter(lum, 5) ** 2
    cand = lum >= np.percentile(lum, 92)
    smooth = tex <= np.percentile(tex[cand], 50) if cand.any() else cand
    m = cand & smooth
    if m.sum() < 200 or float(np.median(lum[m])) < 0.45:
        return None, 0.0
    bgc = np.median(f[m], axis=0)
    frac = float((lum > np.median(lum[m]) - 0.06).mean())
    # real slide background forms sizeable empty areas; scattered bright gaps inside dense tissue do not count
    big = ndi.binary_opening(lum > np.median(lum[m]) - 0.06, structure=np.ones((9, 9), bool))
    if frac < 0.06 or big.mean() < 0.03:
        return None, 0.0
    if bgc.max() / max(bgc.min(), 1e-3) > 1.4:  # strongly coloured → stained tissue, not a cast slide background
        return None, 0.0
    return bgc, frac


def op_background_white(f, target=0.95, strength=1.0):
    """Background whitening: one linear gain per colour channel so that the empty slide background becomes neutral
    white (corrects colour cast and dim exposure together). Identical for every pixel."""
    bg, frac = background_colour(f)
    if bg is None:
        return f, {"skipped": "no clear background"}
    gains = np.clip(target / np.maximum(bg, 1e-3), 0.7, 1.6)
    gains = 1 + (gains - 1) * float(np.clip(strength, 0, 1))
    return np.clip(f * gains, 0, 1), {"background_RGB": [round(float(v) * 255) for v in bg],
                                      "channel_gains_RGB": [round(float(g), 4) for g in gains]}


def op_black_point(f, pct=0.3, target=0.04, max_slope=3.0):
    """Lift haze: linear stretch that takes the darkest tissue to near black while the slide background keeps its
    level (same straight line for all channels and pixels)."""
    lum = f.mean(2)
    lo = float(np.percentile(lum, pct))
    if lo <= target + 0.02:
        return f, {"black_point": round(lo, 4), "skipped": "already dark enough"}
    bg, _ = background_colour(f)
    anchor = float(np.clip(np.mean(bg), 0.6, 1.0)) if bg is not None else 1.0
    if anchor - lo < 0.05:
        anchor = 1.0
    a = min((anchor - target) / (anchor - lo), float(max_slope))
    return np.clip(anchor - (anchor - f) * a, 0, 1), {"black_point_in": round(lo, 4), "black_point_out": target,
                                                       "white_anchor": round(anchor, 4), "slope": round(a, 3)}


def op_clahe(f, strength=0.3, clip=0.008):
    """Mild local-contrast enhancement: CLAHE (Zuiderveld 1994) on CIE L* only (hue/stain colour unchanged),
    large tiles (1/6 of the image), low clip limit, blended with the input at the given strength (≤ 0.5)."""
    strength = float(np.clip(strength, 0, 0.5))
    lab = color.rgb2lab(f)
    L = lab[..., 0] / 100.0
    ks = (max(f.shape[0] // 6, 16), max(f.shape[1] // 6, 16))
    Lc = exposure.equalize_adapthist(np.clip(L, 0, 1), kernel_size=ks, clip_limit=clip)
    lab[..., 0] = (L * (1 - strength) + Lc * strength) * 100
    return np.clip(color.lab2rgb(lab), 0, 1), {"strength": strength, "clip_limit": clip, "kernel": list(ks), "channel": "L* only"}


FUNCS = {"crop": op_crop, "background_white": op_background_white, "black_point": op_black_point, "clahe": op_clahe, "flatfield": op_flatfield, "sharpen": op_sharpen, "white_balance": op_white_balance, "levels": op_levels, "auto_levels": op_auto_levels, "gamma": op_gamma,
         "saturation": op_saturation, "reinhard": op_reinhard, "macenko": op_macenko, "denoise": op_denoise}

# Hard limits keep every operation within what image-integrity guidelines accept
LIMITS = {"brightness": (-0.25, 0.25), "contrast": (0.6, 1.6), "gamma": (0.6, 1.6), "factor": (0.6, 1.5), "strength": (0.0, 1.0),
          "amount": (0.0, 0.8), "radius": (0.5, 2.0)}


@dataclass
class EditLog:
    source: str = ""
    steps: list = field(default_factory=list)
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def methods_text(self) -> str:
        if not self.steps:
            return "Images are presented without any processing."
        names = [OPS[s["op"]][0].split(" (")[0].lower() for s in self.steps]
        txt = ("Image adjustments were restricted to global operations applied equally to the entire image "
               f"({', '.join(names)}), using MedStatix Pro. No local editing, cloning, or generative/AI-based pixel "
               "synthesis was performed, and no features were added, removed, or obscured. Original unprocessed images were retained.")
        if any(s["op"] in ("reinhard", "macenko") for s in self.steps):
            txt += (" Stain normalization (" + ", ".join(sorted({'Reinhard et al., 2001' if s['op'] == 'reinhard' else 'Macenko et al., 2009'
                                                              for s in self.steps if s['op'] in ('reinhard', 'macenko')})) +
                    ") was applied identically to all images in a comparison.")
        if any(s["op"] == "flatfield" for s in self.steps):
            txt += " Uneven illumination (vignetting) was corrected by flat-field (shading) correction, dividing the image by a smooth second-order polynomial illumination surface fitted to background pixels."
        if any(s["op"] == "crop" for s in self.steps):
            txt += " Photographs taken through the eyepiece were cropped to the illuminated field of view."
        if any(s["op"] == "background_white" for s in self.steps):
            txt += " Colour balance was set with one linear gain per colour channel so that the empty slide background is neutral white."
        if any(s["op"] == "black_point" for s in self.steps):
            txt += " A linear black-point (levels) adjustment was applied to remove haze."
        if any(s["op"] == "clahe" for s in self.steps):
            txt += (" Mild contrast-limited adaptive histogram equalization (CLAHE; Zuiderveld 1994) was applied to the lightness "
                    "channel of the whole image (blended at ≤ 50 %), leaving stain hue unchanged.")
        if any(s["op"] == "sharpen" for s in self.steps):
            txt += " Mild unsharp masking was applied uniformly to the whole image."
        if any(s["op"] == "denoise" for s in self.steps):
            txt += " Mild edge-preserving non-local-means denoising was applied to the whole image."
        return txt

    def to_json(self):
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)


def apply_pipeline(original: np.ndarray, steps: list[dict]) -> tuple[np.ndarray, list[dict]]:
    """steps: [{"op": name, "params": {...}}]. Returns processed uint8 image and steps with recorded details."""
    f = to_float(original)
    out_steps = []
    for st in steps:
        params = dict(st.get("params", {}))
        for k, (lo, hi) in LIMITS.items():
            if k in params:
                params[k] = float(np.clip(params[k], lo, hi))
        f, details = FUNCS[st["op"]](f, **params)
        out_steps.append({"op": st["op"], "name": OPS[st["op"]][0], "params": params, "details": details})
    return to_uint8(f), out_steps


# ----------------------------------------------------------------------------- integrity
def _norm_gray(img):
    g = color.rgb2gray(img).astype(np.float64)
    return (g - g.mean()) / (g.std() + 1e-9)


LOCAL_EDIT_THRESHOLD = 6.0
# flat-field leaves a small smooth residual; tampering scores 27–90 in validation, clean flat-field ≤ 7
LOCAL_EDIT_THRESHOLD_FLAT = 10.0


def _rank_gray(img):
    """Grey levels replaced by their rank (histogram equalisation): any global monotonic
    brightness/contrast/gamma change leaves this image exactly unchanged, so remaining
    differences reflect genuine structural change."""
    g = color.rgb2gray(img).ravel()
    r = np.empty(g.size); r[np.argsort(g, kind="stable")] = np.arange(g.size)
    return (r / (g.size - 1)).reshape(img.shape[:2])


def _big_blur(x, sigma):
    """Gaussian blur with a large sigma, computed on a downsampled copy (same result to within interpolation error,
    ~50× faster)."""
    if sigma <= 8:
        return filters.gaussian(x, sigma)
    from skimage.transform import resize
    fct = sigma / 4.0
    small = resize(x, (max(int(x.shape[0] / fct), 4), max(int(x.shape[1] / fct), 4)), order=1, anti_aliasing=True)
    small = ndi.gaussian_filter(small, 4.0, mode="nearest")
    return resize(small, x.shape, order=1)


def _rank_gray_flat(img):
    """Rank-normalised grey after dividing by a very smooth local mean, so a smooth multiplicative shading
    field (vignetting) and its flat-field correction give the same image."""
    g = color.rgb2gray(img).astype(np.float64)
    big = max(img.shape[:2]) / 16
    g = g / (_big_blur(g, big) + 1e-3)
    r = np.empty(g.size); r[np.argsort(g.ravel(), kind="stable")] = np.arange(g.size)
    return (r / (g.size - 1)).reshape(img.shape[:2])


def local_edit_map(original: np.ndarray, processed: np.ndarray, bins: int = 32, sigma: float = 2.5, smooth_field: bool = False):
    """Detect *local* edits independent of any global colour/intensity mapping.

    A global operation makes each output pixel a function of the input colour only.
    We estimate that function non-parametrically (mean output colour per input-colour bin)
    and measure, per pixel, how far the processed image departs from it. Cloning,
    painting or inserting/removing cells produce clustered residuals; global edits do not.
    Neighbourhood filters (denoising) produce a small, spatially uniform residual.
    Returns (smoothed residual map in 0–1 units, robust anomaly score)."""
    o = original.reshape(-1, 3).astype(np.int64) * bins // 256
    idx = (o[:, 0] * bins + o[:, 1]) * bins + o[:, 2]
    p = processed.reshape(-1, 3).astype(np.float64) / 255.0
    cnt = np.bincount(idx, minlength=bins ** 3).astype(float)
    pred = np.stack([np.bincount(idx, weights=p[:, c], minlength=bins ** 3) for c in range(3)], 1) / np.maximum(cnt, 1)[:, None]
    if smooth_field:
        # flat-field correction multiplies the image by a smooth gain field. Estimate that field from the
        # ratio processed / colour-mapping prediction (very heavily smoothed, so it cannot carry structure),
        # divide it out, refit the colour mapping, and only then measure structure-scale residuals.
        H, W = original.shape[:2]
        big = max(H, W) / 16
        p_img = p.reshape(H, W, 3)
        for _ in range(2):
            pr = pred[idx].reshape(H, W, 3)
            num = _big_blur(p_img.mean(2) * pr.mean(2), big)
            den = _big_blur(pr.mean(2) ** 2, big) + 1e-6
            gain = num / den
            p_img = np.clip(p_img / gain[..., None], 0, 1.5)
            pf = p_img.reshape(-1, 3)
            pred = np.stack([np.bincount(idx, weights=pf[:, c], minlength=bins ** 3) for c in range(3)], 1) / np.maximum(cnt, 1)[:, None]
        res = np.linalg.norm(p_img.reshape(-1, 3) - pred[idx], axis=1).reshape(H, W) / math.sqrt(3)
    else:
        res = np.linalg.norm(p - pred[idx], axis=1).reshape(original.shape[:2]) / math.sqrt(3)
    sm = filters.gaussian(res, sigma)
    med = float(np.median(sm))
    mad = float(np.median(np.abs(sm - med))) * 1.4826 + 0.004
    score = float((sm.max() - med) / mad)
    return sm, score


def integrity_report(original: np.ndarray, processed: np.ndarray, nuclear_fraction: float | None = None,
                     smooth_field: bool = False, structure_scale: float = 0.0) -> dict:
    """Prove that processing did not alter tissue structure.

    Both images are first converted to rank-normalised grey (invariant to any global monotonic
    intensity mapping), then compared with:
    * SSIM (structural similarity, Wang et al. 2004)
    * Pearson r of Sobel edge maps (cell and nuclear boundaries)
    * Nuclear mask agreement (Dice): the darkest-pixel fraction that Otsu assigns to nuclei in the
      original is taken from both images, so identical nuclei give Dice = 1
    """
    a, b = (_rank_gray_flat(original), _rank_gray_flat(processed)) if smooth_field else (_rank_gray(original), _rank_gray(processed))
    if structure_scale > 0:
        # denoising removes pixel-level noise by design; compare structure at the cellular scale instead
        ssim = structural_similarity(filters.gaussian(a, structure_scale), filters.gaussian(b, structure_scale), data_range=1.0)
    else:
        ssim = structural_similarity(a, b, data_range=1.0)
    ea, eb = filters.sobel(filters.gaussian(a, 1)), filters.sobel(filters.gaussian(b, 1))
    edge_r = float(np.corrcoef(ea.ravel(), eb.ravel())[0, 1])
    g0 = color.rgb2gray(original)
    if nuclear_fraction is None:
        nuclear_fraction = float((g0 < filters.threshold_otsu(g0)).mean())
        nuclear_fraction = min(max(nuclear_fraction, 0.05), 0.5)
    na, nb = a < nuclear_fraction, b < nuclear_fraction
    na = _drop_small(na, 20); nb = _drop_small(nb, 20)
    dice = float(2 * (na & nb).sum() / max(na.sum() + nb.sum(), 1))
    ca, cb = measure.label(na).max(), measure.label(nb).max()
    _, local_score = local_edit_map(original, processed, smooth_field=smooth_field)
    thr = LOCAL_EDIT_THRESHOLD_FLAT if smooth_field else LOCAL_EDIT_THRESHOLD
    passed = edge_r >= 0.90 and dice >= 0.90 and ssim >= 0.85 and local_score < thr
    return {"SSIM (structure)": round(float(ssim), 4),
            "Local-edit score (threshold %g)" % thr: round(local_score, 1), "Edge correlation": round(edge_r, 4),
            "Nuclei mask agreement (Dice)": round(dice, 4), "Dark objects original": int(ca), "Dark objects processed": int(cb),
            "Verdict": "Structure preserved" if passed else "Check: structural change detected", "passed": bool(passed)}



NEIGHBOURHOOD_OPS = ("denoise", "sharpen", "clahe")


def pipeline_integrity(original: np.ndarray, steps: list[dict]) -> dict:
    """Integrity of a whole pipeline, verified stage by stage.

    A crop is applied to the original first (cropping only removes the area outside the field). Neighbourhood filters
    (denoise, sharpen, CLAHE) are each checked against their own input; the runs of pointwise / smooth-field operations
    between them are checked as one stage (flat-field mode when it contains flatfield; CLAHE, whose tone curve varies
    smoothly across the image, is also checked in that mode). A strong-but-legitimate denoise of a very noisy image is
    therefore not confused with a structural change, while a local edit anywhere is still caught.
    The report shows the worst value of every metric."""
    steps = list(steps)
    while steps and steps[0]["op"] == "crop":
        original = apply_pipeline(original, [steps.pop(0)])[0]
    if not steps:
        return integrity_report(original, original)
    stages, cur = [], []
    for st in steps:
        if st["op"] in NEIGHBOURHOOD_OPS or st["op"] == "flatfield":
            if cur:
                stages.append(cur); cur = []
            stages.append([st])
        else:
            cur.append(st)
    if cur:
        stages.append(cur)
    prev, reps = original, []
    for stg in stages:
        nxt = apply_pipeline(prev, stg)[0]
        reps.append(integrity_report(prev, nxt, smooth_field=any(s["op"] in ("flatfield", "clahe") for s in stg),
                                     structure_scale=1.5 if stg[0]["op"] == "denoise" else 0.0))
        prev = nxt
    passed = all(r["passed"] for r in reps)
    if len(reps) == 1:
        return reps[0]
    lk = lambda r: next(k for k in r if k.startswith("Local-edit"))
    thr = lambda r: float(lk(r).split("threshold ")[1].rstrip(")"))
    worst_local = max(reps, key=lambda r: r[lk(r)] / thr(r))
    return {"SSIM (structure)": min(r["SSIM (structure)"] for r in reps),
            lk(worst_local): worst_local[lk(worst_local)],
            "Edge correlation": min(r["Edge correlation"] for r in reps),
            "Nuclei mask agreement (Dice)": min(r["Nuclei mask agreement (Dice)"] for r in reps),
            "Dark objects original": reps[0]["Dark objects original"], "Dark objects processed": reps[-1]["Dark objects processed"],
            "Stages checked": len(reps),
            "Verdict": "Structure preserved" if passed else "Check: structural change detected", "passed": passed}


# ----------------------------------------------------------------------------- image quality control
QC_ORDER = ["denoise", "flatfield", "white_balance", "levels", "auto_levels", "gamma", "saturation", "sharpen", "reinhard"]


def _qc_status(v, warn, bad, higher_is_worse=True):
    if v is None:
        return "na"
    if not higher_is_worse:
        v, warn, bad = -v, -warn, -bad
    return "bad" if v >= bad else "warn" if v >= warn else "ok"


def _exposure_fix(lo, white):
    """Linear levels that put the background at ~0.95 and the darkest tissue at ~0.05 (no tissue clipping)."""
    c = float(np.clip((0.93 - 0.08) / max(white - lo, 1e-3), 0.6, 1.45))
    b = float(np.clip(0.08 - ((lo - 0.5) * c + 0.5), -0.25, 0.25))
    return {"op": "levels", "params": {"brightness": round(b, 3), "contrast": round(c, 3)}}


def guess_stain(img: np.ndarray) -> str:
    """'IHC' when brown (DAB-hue) pixels outnumber pink/magenta (eosin-hue) ones among stained pixels, else 'H&E'."""
    a = np.asarray(img)[::4, ::4]
    hsv = color.rgb2hsv(a)
    h, sat, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    m = (sat > 0.15) & (v < 0.95)
    brown = ((h > 0.02) & (h < 0.14) & m).sum()
    pink = (((h > 0.80) | (h <= 0.02)) & m).sum()
    return "IHC" if brown > pink else "H&E"


def image_qc(img: np.ndarray, stain: str = "auto") -> dict:
    """Detect common acquisition defects and propose *global* corrections.

    Checks: uneven illumination, colour cast of the background, exposure / dynamic range, clipping,
    mid-tone balance, colour saturation (faded stain), noise, focus (global and out-of-focus areas),
    stain deviation from a reference H&E, and large very dark regions (folds / debris / bubbles edges).
    Folds, debris, bubbles and blur cannot be honestly *repaired*; they are only flagged (re-acquire or
    choose another field). Returns {"score", "checks": [...], "steps": [...], "problem_mask", "stain"}."""
    if stain == "auto":
        stain = guess_stain(img)
    a = np.asarray(img)
    H0, W0 = a.shape[:2]
    step = int(max(1, math.ceil(max(H0, W0) / 1400)))
    a = a[::step, ::step]
    f = to_float(a)
    H, W = f.shape[:2]
    lum = f.mean(2)
    checks, steps = [], []
    problem = np.zeros((H, W), bool)

    def add(key, en, ar, value, status, detail_en, detail_ar, fix=None, default_on=True):
        checks.append({"key": key, "name_en": en, "name_ar": ar, "value": value, "status": status,
                       "detail_en": detail_en, "detail_ar": detail_ar, "fix": fix, "default_on": default_on and fix is not None
                       and status in ("warn", "bad")})

    bright = lum >= np.percentile(lum, 96)
    bg_lum = float(np.median(lum[bright]))
    has_bg = bg_lum > 0.70 and (lum > 0.80).mean() > 0.02
    tissue = lum < (bg_lum - 0.08 if has_bg else 2)
    if tissue.mean() < 0.05:
        tissue = np.ones_like(tissue)

    # 1 illumination ------------------------------------------------------------
    _, unev, _nbg = shading_surface(f)
    st = _qc_status(unev, 0.10, 0.18)
    add("illumination", "Uneven illumination / vignetting", "إضاءة غير متساوية / تعتيم الأطراف", f"{unev * 100:.0f}%", st,
        "Brightness of the background differs across the field.", "سطوع الخلفية يختلف بين أجزاء الصورة (الأطراف أغمق من المركز مثلاً).",
        {"op": "flatfield", "params": {"strength": 1.0}})

    # 2 colour cast -------------------------------------------------------------
    if has_bg:
        ref = np.median(f[bright], axis=0)
        cast = float((ref.max() - ref.min()) / max(ref.max(), 1e-3))
        st = _qc_status(cast, 0.06, 0.12)
        tint = ["red", "green", "blue"][int(np.argmax(ref))] if cast > 0.06 else ""
        tint_ar = {"red": "أحمر/أصفر", "green": "أخضر", "blue": "أزرق"}.get(tint, "")
        add("cast", "Colour cast (white balance)", "انحراف لوني (توازن الأبيض)", f"{cast * 100:.1f}%", st,
            f"Background is not neutral{' (' + tint + ' tint)' if tint else ''}.",
            f"الخلفية ليست بيضاء محايدة{' (ميل ' + tint_ar + ')' if tint_ar else ''}.",
            {"op": "white_balance", "params": {"strength": 1.0}})
    else:
        add("cast", "Colour cast (white balance)", "انحراف لوني (توازن الأبيض)", "—", "na",
            "No clear background to judge white balance.", "لا توجد خلفية فارغة واضحة للحكم على توازن الأبيض.")

    # 3 exposure / dynamic range -----------------------------------------------
    lo, hi = np.percentile(lum, [0.5, 99.5])
    span = float(hi - lo)
    dark_bg = has_bg and bg_lum < 0.84
    st = "bad" if span < 0.35 or (has_bg and bg_lum < 0.70) else "warn" if span < 0.46 or dark_bg else "ok"
    add("exposure", "Exposure & contrast (dynamic range)", "التعريض والتباين (المدى الديناميكي)",
        f"{lo * 255:.0f}–{hi * 255:.0f}", st,
        "Image does not use the full tonal range (dull / under-exposed)." if st != "ok" else "Full tonal range is used.",
        "الصورة لا تستخدم المدى الكامل للدرجات (باهتة أو معتمة)." if st != "ok" else "الصورة تستخدم المدى الكامل للدرجات.",
        _exposure_fix(lo, bg_lum if has_bg else hi))

    clip_tissue = float(((f.min(2) >= 254.5 / 255) & tissue).mean() / max(tissue.mean(), 1e-6))
    clip_lo = float((f.max(2) <= 0.5 / 255).mean())
    st = "bad" if clip_tissue > 0.05 or clip_lo > 0.03 else "warn" if clip_tissue > 0.01 or clip_lo > 0.005 else "ok"
    add("clipping", "Clipped highlights / shadows", "قص الإضاءات أو الظلال", f"{max(clip_tissue, clip_lo) * 100:.1f}%", st,
        "Some tissue pixels are pure white/black; this detail is lost and cannot be recovered (re-acquire with lower exposure)."
        if st != "ok" else "No meaningful clipping.",
        "بعض بكسلات النسيج أبيض أو أسود تام؛ التفاصيل مفقودة ولا يمكن استرجاعها (أعد التصوير بتعريض أقل)."
        if st != "ok" else "لا يوجد قص مؤثر.")

    # 4 mid-tones (after the levels stretch the suggestion would be applied to) --
    fx = _exposure_fix(lo, bg_lum if has_bg else hi)["params"]
    after = np.clip((lum - 0.5) * fx["contrast"] + 0.5 + fx["brightness"], 0, 1) if checks[-2]["status"] != "ok" else lum
    med_t = float(np.median(after[tissue])) if tissue.any() else 0.5
    g = math.log(max(min(med_t, 0.95), 0.05)) / math.log(0.64)
    g = float(np.clip(g, 0.75, 1.35))
    st = "warn" if (med_t < 0.42 or med_t > 0.82) else "ok"
    add("midtones", "Mid-tone balance", "توازن الدرجات المتوسطة", f"{med_t * 255:.0f}", st,
        ("Tissue looks too dark" if g > 1 else "Tissue looks washed out") + " in the mid-tones." if st != "ok" else "Mid-tones are balanced.",
        ("النسيج داكن أكثر من اللازم" if g > 1 else "النسيج فاتح/باهت") + " في الدرجات المتوسطة." if st != "ok" else "الدرجات المتوسطة متوازنة.",
        {"op": "gamma", "params": {"gamma": round(g, 2)}})

    # 5 saturation ---------------------------------------------------------------
    hsv = color.rgb2hsv(f)
    sat = float(np.median(hsv[..., 1][tissue]))
    if sat < 0.20:
        fac = float(np.clip(0.26 / max(sat, 0.05), 1.1, 1.3)); st = "bad" if sat < 0.13 else "warn"
        d_en, d_ar = "Stain colours look faded.", "ألوان الصبغة باهتة."
    elif sat > 0.72:
        fac = 0.85; st = "warn"; d_en, d_ar = "Colours are over-saturated.", "الألوان مشبعة أكثر من اللازم."
    else:
        fac = 1.0; st = "ok"; d_en, d_ar = "Colour saturation is normal.", "تشبع الألوان طبيعي."
    add("saturation", "Colour saturation", "تشبع الألوان", f"{sat * 100:.0f}%", st, d_en, d_ar,
        {"op": "saturation", "params": {"factor": round(fac, 2)}})

    # 6 noise ----------------------------------------------------------------------
    nz = noise_sigma(f) * 255
    st = _qc_status(nz, 3.5, 6.0)
    add("noise", "Noise (graininess)", "الضوضاء (التحبب)", f"σ ≈ {nz:.1f}", st,
        "Visible sensor noise." if st != "ok" else "Noise level is low.",
        "ضوضاء الكاميرا واضحة (تحبب)." if st != "ok" else "مستوى الضوضاء منخفض.",
        {"op": "denoise", "params": {"strength": 0.5 if st == "bad" else 0.35}})

    # 7 focus ----------------------------------------------------------------------
    gray = ndi.gaussian_filter(color.rgb2gray(f), 0.8)
    lap = ndi.laplace(gray)
    contrast = float(np.std(gray[tissue])) + 1e-3
    tsz = max(min(H, W) // 8, 32)
    tile_f, tile_mask = [], []
    for i in range(0, H - tsz + 1, tsz):
        for j in range(0, W - tsz + 1, tsz):
            if tissue[i:i + tsz, j:j + tsz].mean() > 0.5:
                tile_f.append(float(np.var(lap[i:i + tsz, j:j + tsz])) / contrast ** 2 * 1e3)
                tile_mask.append((i, j))
    focus = float(np.median(tile_f)) if tile_f else float(np.var(lap)) / contrast ** 2 * 1e3
    soft = []
    if len(tile_f) >= 6:
        ref_f = np.percentile(tile_f, 90)
        soft = [m for v, m in zip(tile_f, tile_mask) if v < 0.30 * ref_f]
        for i, j in soft:
            problem[i:i + tsz, j:j + tsz] = True
    st = "bad" if focus < 6 else "warn" if focus < 12 or len(soft) > 0.2 * max(len(tile_f), 1) else "ok"
    add("focus", "Focus / sharpness", "التركيز / الحدة", f"{focus:.1f}" + (f" ({len(soft)} soft areas)" if soft else ""), st,
        ("Image is soft / out of focus" + (f"; {len(soft)} areas are clearly blurred" if soft else "") +
         ". Mild sharpening improves edges; severe blur needs re-acquisition.") if st != "ok" else "Image is in focus.",
        ("الصورة غير حادة / خارج التركيز" + (f"؛ {len(soft)} مناطق ضبابية بوضوح" if soft else "") +
         ". زيادة الحدة الخفيفة تحسن الحواف، أما الضبابية الشديدة فتحتاج إعادة تصوير.") if st != "ok" else "الصورة في التركيز.",
        {"op": "sharpen", "params": {"amount": 0.6 if st == "bad" else 0.4, "radius": 1.5 if st == "bad" else 1.0}})

    # 8 stain deviation (H&E) -------------------------------------------------------
    if stain.upper().startswith("H") and tissue.any():
        lab = color.rgb2lab(f)
        mu = lab[tissue].mean(0)
        dev = float(np.linalg.norm(mu - REF_LAB_MEAN))
        st = _qc_status(dev, 14, 24)
        add("stain", "Stain colour vs reference H&E", "لون الصبغة مقارنة بمرجع H&E", f"ΔE ≈ {dev:.0f}", st,
            "Stain colour differs from a typical H&E; normalise only if all compared images are normalised the same way.",
            "لون الصبغة يختلف عن H&E النموذجي؛ استخدم التوحيد فقط إذا طُبق على كل الصور المقارنة بنفس الطريقة.",
            {"op": "reinhard", "params": {}}, default_on=False)

    # 9 folds / debris / bubbles ----------------------------------------------------
    od = -np.log(np.clip(f, 1 / 255, 1)).sum(2)
    very_dark = od > max(np.percentile(od[tissue], 99.5) if tissue.any() else 3, 2.4)
    very_dark = ndi.binary_opening(very_dark, structure=morphology.disk(2))
    lab_ = measure.label(very_dark)
    min_area = 0.004 * H * W
    big = [r for r in measure.regionprops(lab_) if r.area >= min_area]
    frac = float(sum(r.area for r in big) / (H * W))
    for r in big:
        problem[lab_ == r.label] = True
    st = "bad" if frac > 0.03 else "warn" if big else "ok"
    add("artefacts", "Folds / debris / dark artefacts", "طيات / شوائب / مناطق داكنة غير طبيعية",
        f"{len(big)} region(s), {frac * 100:.1f}%", st,
        "Large very dark regions (tissue folds, debris, bubble edges). These cannot be removed honestly: crop to another field or re-acquire."
        if big else "No large artefacts detected.",
        "مناطق داكنة كبيرة (طيات نسيج، شوائب، حواف فقاعات). لا يجوز إزالتها؛ اختر حقلاً آخر أو أعد التصوير."
        if big else "لم تُكتشف شوائب أو طيات كبيرة.")

    pen = {"ok": 0, "na": 0, "warn": 7, "bad": 16}
    weight = {"illumination": 1.0, "cast": 1.0, "exposure": 1.0, "clipping": 0.8, "midtones": 0.6, "saturation": 0.8,
              "noise": 0.9, "focus": 1.3, "stain": 0.5, "artefacts": 1.0}
    score = 100 - sum(pen[c["status"]] * weight.get(c["key"], 1) for c in checks)
    for c in checks:
        if c["default_on"]:
            steps.append(c["fix"])
    steps.sort(key=lambda s: QC_ORDER.index(s["op"]))
    if step > 1:
        problem = np.kron(problem, np.ones((step, step), bool))[:H0, :W0]
    return {"score": int(round(max(0, min(100, score)))), "checks": checks, "steps": steps, "problem_mask": problem, "stain": stain}


def auto_enhance(img: np.ndarray, steps: list[dict] | None = None, stain: str = "auto"):
    """Apply the QC-suggested global corrections, then verify structure. If integrity fails, the step most
    likely to be responsible (sharpen, denoise, then the rest from the end) is dropped and the check repeated."""
    if steps is None:
        steps = image_qc(img, stain)["steps"]
    steps = [dict(s) for s in steps]
    while True:
        out, done = apply_pipeline(img, steps)
        rep = pipeline_integrity(img, steps)
        if rep["passed"] or not steps:
            return out, done, rep, steps
        # first soften the neighbourhood filters, then drop them, then drop steps from the end
        soft = False
        for s_ in steps:
            k = "amount" if s_["op"] == "sharpen" else "strength" if s_["op"] in ("denoise", "clahe") else None
            if k and s_["params"].get(k, 0) > 0.2:
                s_["params"] = {**s_["params"], k: round(s_["params"][k] / 2, 2)}
                soft = True
        if soft:
            continue
        for drop in ("sharpen", "clahe", "denoise"):
            if any(s["op"] == drop for s in steps):
                steps = [s for s in steps if s["op"] != drop]
                break
        else:
            steps = steps[:-1]


# ----------------------------------------------------------------------------- quantification
def robust_otsu(values):
    """Otsu threshold after clipping the extreme 0.5 % tails (saturated/black pixels give huge optical densities
    that would otherwise drag the threshold far away from the nuclear population)."""
    v = np.asarray(values, float).ravel()
    lo, hi = np.percentile(v, [0.5, 99.5])
    return float(filters.threshold_otsu(np.clip(v, lo, hi)))


def _drop_small(mask, n):
    """remove objects with fewer than n pixels (version-independent)."""
    lab, k = ndi.label(mask)
    if k == 0:
        return mask.astype(bool)
    sizes = np.bincount(lab.ravel())
    keep = sizes >= n
    keep[0] = False
    return keep[lab]


def stain_channels(img):
    """Colour deconvolution (Ruifrok & Johnston 2001) → hematoxylin, eosin/DAB optical densities."""
    hed = color.rgb2hed(img)
    return hed[..., 0], hed[..., 1], hed[..., 2]


def ihc_dab(img, weak=0.08, moderate=0.15, strong=0.22, min_nucleus_px=30):
    """DAB IHC quantification. Thresholds are in DAB optical-density units (adjustable).

    Returns pixel-based H-score and % positive area, plus nucleus-based % positive cells.
    """
    h, e, d = stain_channels(img)
    tissue = _tissue_mask(img, 0.85)
    tissue = _drop_small(tissue, 64)
    dt = d[tissue]
    n = max(len(dt), 1)
    p_weak = float(((dt >= weak) & (dt < moderate)).sum() / n * 100)
    p_mod = float(((dt >= moderate) & (dt < strong)).sum() / n * 100)
    p_str = float((dt >= strong).sum() / n * 100)
    hscore = 1 * p_weak + 2 * p_mod + 3 * p_str
    # nuclei: combined hematoxylin + DAB density
    dens = filters.gaussian(np.clip(h, 0, None) + np.clip(d, 0, None), 1)
    thr = robust_otsu(dens[tissue]) if tissue.any() else robust_otsu(dens)
    nuc = _drop_small(dens > thr, min_nucleus_px)
    nuc = ndi.binary_opening(nuc, morphology.disk(1))
    dist = filters.gaussian(np.asarray(nuc, float), 1.5)
    coords = feature.peak_local_max(dist, min_distance=max(3, int(math.sqrt(min_nucleus_px) / 1.2)), labels=measure.label(nuc))
    markers = np.zeros(nuc.shape, int)
    markers[tuple(coords.T)] = np.arange(1, len(coords) + 1)
    lab = segmentation.watershed(-dist, markers, mask=nuc)
    props = measure.regionprops(lab, intensity_image=d)
    cells = []
    for p in props:
        if p.area < min_nucleus_px:
            continue
        md = p.intensity_mean
        cls = 3 if md >= strong else 2 if md >= moderate else 1 if md >= weak else 0
        cells.append((p.centroid[1], p.centroid[0], cls, p.area))
    nc = len(cells)
    pos = sum(1 for c in cells if c[2] > 0)
    cell_h = sum(c[2] for c in cells) / max(nc, 1) * 100
    masks = {"weak": tissue & (d >= weak) & (d < moderate), "moderate": tissue & (d >= moderate) & (d < strong),
             "strong": tissue & (d >= strong)}
    return {
        "Tissue area (px)": int(tissue.sum()), "DAB weak %": p_weak, "DAB moderate %": p_mod, "DAB strong %": p_str,
        "DAB positive area %": p_weak + p_mod + p_str, "H-score (pixel)": hscore,
        "Nuclei detected": nc, "Positive nuclei": pos, "Positive nuclei %": pos / max(nc, 1) * 100,
        "H-score (cell)": cell_h,
    }, masks, cells


def fibrosis_area(img, stain="Masson trichrome", sat_min=0.12, background=0.88):
    """Collagen area fraction by hue segmentation in HSV after background removal.
    Masson trichrome: collagen = blue/green (hue 150–270°). Sirius red (bright-field): red/pink-red (hue < 20° or > 330°)
    with saturation ≥ 0.30. Values reported as % of tissue area."""
    f = to_float(img)
    hsv = color.rgb2hsv(f)
    H, S, V = hsv[..., 0] * 360, hsv[..., 1], hsv[..., 2]
    tissue = (color.rgb2gray(f) < background) & (S > 0.05)
    tissue = _drop_small(tissue, 64)
    if stain.startswith("Masson"):
        col = tissue & (H >= 150) & (H <= 270) & (S >= sat_min)
    elif stain.startswith("Sirius"):
        col = tissue & ((H <= 20) | (H >= 330)) & (S >= max(sat_min, 0.30))
    else:  # Van Gieson: collagen red, muscle/cytoplasm yellow
        col = tissue & ((H <= 15) | (H >= 335)) & (S >= max(sat_min, 0.35))
    col = _drop_small(col, 16)
    pct = col.sum() / max(tissue.sum(), 1) * 100
    return {"Stain": stain, "Tissue area (px)": int(tissue.sum()), "Collagen area (px)": int(col.sum()),
            "Fibrosis / collagen area %": float(pct)}, col


def inflammatory_candidates(img, min_area=20, max_area=220, min_circularity=0.72, darkness_pct=70):
    """Suggest candidate mononuclear inflammatory cells (lymphocytes/plasma-cell-like nuclei) in H&E.

    Criteria: small, round, dense hematoxylin nuclei (area window in px, circularity, intensity above the
    darkness percentile of all nuclei). These are SUGGESTIONS for the pathologist to accept or reject —
    never added to the image as pixels, only as removable markers.
    """
    h, _, _ = stain_channels(img)
    hs = filters.gaussian(h, 1)
    thr = robust_otsu(hs)
    nuc = _drop_small(hs > thr, min_area)
    nuc = ndi.binary_opening(nuc, morphology.disk(1))
    lab = measure.label(nuc)
    props = measure.regionprops(lab, intensity_image=hs)
    if not props:
        return []
    dens_cut = np.percentile([p.intensity_mean for p in props], darkness_pct)
    out = []
    for p in props:
        if not (min_area <= p.area <= max_area):
            continue
        circ = 4 * math.pi * p.area / max(p.perimeter, 1) ** 2
        if circ >= min_circularity and p.intensity_mean >= dens_cut and p.eccentricity < 0.8:
            out.append({"x": float(p.centroid[1]), "y": float(p.centroid[0]), "r": float(math.sqrt(p.area / math.pi)) + 3,
                        "area_px": int(p.area), "circularity": round(circ, 3)})
    return out


def congestion_area(img, sat_min=0.45):
    """Suggest erythrocyte-rich (congested / haemorrhagic) areas in H&E: intensely eosinophilic red
    pixels (hue ≤ 15° or ≥ 340°, high saturation, low hematoxylin)."""
    f = to_float(img)
    hsv = color.rgb2hsv(f)
    H, S = hsv[..., 0] * 360, hsv[..., 1]
    h, _, _ = stain_channels(img)
    rbc = ((H <= 15) | (H >= 340)) & (S >= sat_min) & (h < np.percentile(h, 60))
    rbc = _drop_small(rbc, 25)
    tissue = color.rgb2gray(f) < 0.88
    return {"RBC-rich (congestion) area %": float(rbc.sum() / max(tissue.sum(), 1) * 100)}, rbc


def outline_mask(mask, min_size=30):
    """Contours of a mask (for drawing outlines over the image, never filling)."""
    m = _drop_small(mask, min_size)
    return measure.find_contours(m.astype(float), 0.5)


# ----------------------------------------------------------------------------- figure composer
def compose_panels(images: list[np.ndarray], ncols=2, labels=None, gap_px=12, label_size=None, bg=255,
                   label_color=(0, 0, 0), label_box=True):
    """Arrange images into a multi-panel figure with A, B, C… labels (no resampling of content other than
    uniform scaling to a common panel height)."""
    from PIL import ImageDraw, ImageFont
    n = len(images)
    if n == 0:
        raise ValueError("No images.")
    labels = labels or [chr(65 + i) for i in range(n)]
    h_target = min(im.shape[0] for im in images)
    ims = []
    for im in images:
        pil = Image.fromarray(im)
        scale = h_target / im.shape[0]
        if scale != 1:
            pil = pil.resize((int(round(im.shape[1] * scale)), h_target), Image.LANCZOS)
        ims.append(pil)
    w_target = max(im.size[0] for im in ims)
    nrows = math.ceil(n / ncols)
    W = ncols * w_target + (ncols + 1) * gap_px
    Hh = nrows * h_target + (nrows + 1) * gap_px
    canvas = Image.new("RGB", (W, Hh), (bg, bg, bg))
    draw = ImageDraw.Draw(canvas)
    ls = label_size or max(18, h_target // 12)
    font = None
    for name in ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(name, ls)
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    for i, (pil, lab) in enumerate(zip(ims, labels)):
        r, c = divmod(i, ncols)
        x = gap_px + c * (w_target + gap_px)
        y = gap_px + r * (h_target + gap_px)
        canvas.paste(pil, (x, y))
        tx, ty = x + ls // 3, y + ls // 4
        if label_box:
            bb = draw.textbbox((tx, ty), lab, font=font)
            draw.rectangle([bb[0] - 4, bb[1] - 3, bb[2] + 4, bb[3] + 3], fill=(255, 255, 255))
        draw.text((tx, ty), lab, fill=label_color, font=font)
    return np.asarray(canvas)


# ----------------------------------------------------------------------------- one-click publication-ready
STAIN_PRESETS = {
    # mid-tone target (tissue median lightness), tissue saturation target, sharpen amount, CLAHE strength
    "H&E": {"mid": 0.66, "sat": 0.30, "sharp": 0.45, "clahe": 0.25, "ar": "H&E"},
    "IHC-DAB": {"mid": 0.72, "sat": 0.26, "sharp": 0.40, "clahe": 0.20, "ar": "هستوكيمياء مناعية DAB"},
    "Masson trichrome": {"mid": 0.64, "sat": 0.34, "sharp": 0.40, "clahe": 0.25, "ar": "ماسون ثلاثي الألوان"},
    "Sirius red": {"mid": 0.66, "sat": 0.34, "sharp": 0.40, "clahe": 0.20, "ar": "سيريوس الأحمر"},
    "PAS": {"mid": 0.66, "sat": 0.30, "sharp": 0.45, "clahe": 0.25, "ar": "PAS"},
    "Other": {"mid": 0.66, "sat": 0.28, "sharp": 0.40, "clahe": 0.20, "ar": "أخرى"},
}
SOURCES = {"auto": ("Auto-detect", "تحديد تلقائي"), "camera": ("Microscope camera / slide scanner", "كاميرا المجهر / ماسح الشرائح"),
           "phone": ("Phone through the eyepiece", "موبايل من خلال العدسة العينية")}
LEVELS = {"light": (0.6, "Light", "خفيف"), "standard": (1.0, "Standard", "قياسي"), "strong": (1.3, "Strong", "قوي")}


def _stain_preset_name(img, stain):
    if stain in STAIN_PRESETS:
        return stain
    return "IHC-DAB" if guess_stain(img) == "IHC" else "H&E"


def _tissue_stats(f):
    lum = f.mean(2)
    bg, _ = background_colour(f)
    bgl = float(np.mean(bg)) if bg is not None else 2.0
    tissue = lum < min(bgl - 0.06, 0.97)
    if tissue.mean() < 0.03:
        tissue = np.ones_like(lum, bool)
    hsv = color.rgb2hsv(f)
    return float(np.median(lum[tissue])), float(np.median(hsv[..., 1][tissue]))


def publication_ready(img: np.ndarray, stain: str = "auto", source: str = "auto", level: str = "standard"):
    """One-click, journal-safe enhancement. Builds a pipeline of disclosed global operations suited to the stain and to
    how the image was acquired, applies it, and verifies structure stage by stage (weakening the neighbourhood filters
    if needed). Returns (processed uint8, steps_done, integrity report, steps, info)."""
    preset_name = _stain_preset_name(img, stain)
    P = STAIN_PRESETS[preset_name]
    k = LEVELS.get(level, LEVELS["standard"])[0]
    steps = []
    work = img
    box = eyepiece_crop_box(img) if source in ("auto", "phone") else None
    if box:
        steps.append({"op": "crop", "params": {"box": box}})
        work = apply_pipeline(img, steps)[0]
    phone = bool(box) or source == "phone"
    f = to_float(work)
    nz = noise_sigma(f) * 255
    if nz > 2.2 or phone:
        steps.append({"op": "denoise", "params": {"strength": round(min(0.6, (0.35 if phone else 0.25) + 0.04 * nz), 2)}})
    if phone or shading_surface(f)[1] > 0.035 or shading_chroma(f) > 0.025:
        steps.append({"op": "flatfield", "params": {"strength": 1.0}})
    steps.append({"op": "background_white", "params": {"target": 0.955, "strength": 1.0}})
    steps.append({"op": "black_point", "params": {"pct": 0.3, "target": round(float(np.clip(0.19 - 0.07 * k, 0.06, 0.16)), 3),
                                                  "max_slope": round(1.8 + 0.7 * k, 2) if not phone else 2.0}})
    # mid-tones and saturation measured after the linear steps
    tmp = to_float(apply_pipeline(img, steps)[0])
    mid, sat = _tissue_stats(tmp)
    g = math.log(max(min(mid, 0.95), 0.05)) / math.log(P["mid"])
    has_bg = background_colour(tmp)[0] is not None
    g = float(np.clip(1 + (g - 1) * min(k, 1.0), 0.95, 1.4 if has_bg else 1.15))
    if abs(g - 1) > 0.04:
        steps.append({"op": "gamma", "params": {"gamma": round(g, 2)}})
    fac = float(np.clip((P["sat"] / max(sat, 0.03)) ** (0.6 * min(k, 1.2)), 0.85, 1.4))
    if fac < 1 and sat < 1.6 * P["sat"]:  # only tone down clearly over-saturated images
        fac = max(fac, 0.97)
    if abs(fac - 1) > 0.04:
        steps.append({"op": "saturation", "params": {"factor": round(fac, 2)}})
    steps.append({"op": "clahe", "params": {"strength": round(min(0.5, P["clahe"] * k), 2)}})
    # final touch-up: saturation/local contrast can re-tint a near-neutral background slightly
    steps.append({"op": "background_white", "params": {"target": 0.96, "strength": 1.0}})
    small = min(f.shape[:2]) < 700
    steps.append({"op": "sharpen", "params": {"amount": round(min(0.8, P["sharp"] * k * (0.8 if phone else 1.0)), 2),
                                              "radius": 0.8 if small else (1.4 if phone else 1.0)}})
    out, done, rep, steps = auto_enhance(img, steps)
    info = {"stain": preset_name, "source": "phone" if phone else "camera", "level": level, "cropped": bool(box)}
    return out, done, rep, steps, info


# ----------------------------------------------------------------------------- measurement & batch
MEASURE_SAFE_OPS = ("crop", "denoise", "flatfield", "background_white", "white_balance")
QUANT_KINDS = ["IHC — DAB (H-score, % positive)", "Fibrosis — Masson trichrome", "Fibrosis — Sirius red",
               "Fibrosis — Van Gieson", "H&E — inflammatory cell candidates", "H&E — congestion / RBC areas", "None (enhance only)"]


def measurement_image(original: np.ndarray, steps: list[dict]) -> np.ndarray:
    """Image used for quantification: the original with only illumination/white-reference corrections (crop, denoise,
    flat-field, background whitening, white balance). Cosmetic steps (levels, gamma, saturation, CLAHE, sharpening,
    stain normalisation) change optical densities and are therefore excluded from measurement."""
    keep = [{"op": s["op"], "params": s.get("params", {})} for s in steps if s["op"] in MEASURE_SAFE_OPS]
    return apply_pipeline(original, keep)[0] if keep else original


def quantify(img: np.ndarray, kind: str, px_um: float = 0.0, dab=(0.08, 0.15, 0.22)) -> dict:
    """Headless quantification used by the batch processor (same algorithms as the studio)."""
    if kind.startswith("IHC"):
        res = dict(ihc_dab(img, *dab)[0])
    elif kind.startswith("Fibrosis"):
        res = dict(fibrosis_area(img, kind.split("— ")[1])[0])
        if px_um:
            res["Collagen area (µm²)"] = res["Collagen area (px)"] * px_um ** 2
    elif "inflammatory" in kind:
        n = len(inflammatory_candidates(img))
        res = {"Candidate mononuclear inflammatory cells": n}
        if px_um:
            res["Candidates per mm²"] = n / (img.shape[0] * img.shape[1] * (px_um / 1000) ** 2)
    elif "congestion" in kind:
        res = dict(congestion_area(img)[0])
    else:
        res = {}
    return {k: (float(v) if isinstance(v, (np.floating, np.integer)) else v) for k, v in res.items()}
