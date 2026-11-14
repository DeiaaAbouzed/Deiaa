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


def save_image(arr: np.ndarray, path: str, dpi: int = 600):
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    ext = path.lower().rsplit(".", 1)[-1]
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


FUNCS = {"white_balance": op_white_balance, "levels": op_levels, "auto_levels": op_auto_levels, "gamma": op_gamma,
         "saturation": op_saturation, "reinhard": op_reinhard, "macenko": op_macenko, "denoise": op_denoise}

# Hard limits keep every operation within what image-integrity guidelines accept
LIMITS = {"brightness": (-0.25, 0.25), "contrast": (0.6, 1.6), "gamma": (0.6, 1.6), "factor": (0.6, 1.5), "strength": (0.0, 1.0)}


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


def _rank_gray(img):
    """Grey levels replaced by their rank (histogram equalisation): any global monotonic
    brightness/contrast/gamma change leaves this image exactly unchanged, so remaining
    differences reflect genuine structural change."""
    g = color.rgb2gray(img).ravel()
    r = np.empty(g.size); r[np.argsort(g, kind="stable")] = np.arange(g.size)
    return (r / (g.size - 1)).reshape(img.shape[:2])


def local_edit_map(original: np.ndarray, processed: np.ndarray, bins: int = 32, sigma: float = 2.5):
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
    res = np.linalg.norm(p - pred[idx], axis=1).reshape(original.shape[:2]) / math.sqrt(3)
    sm = filters.gaussian(res, sigma)
    med = float(np.median(sm))
    mad = float(np.median(np.abs(sm - med))) * 1.4826 + 0.004
    score = float((sm.max() - med) / mad)
    return sm, score


def integrity_report(original: np.ndarray, processed: np.ndarray, nuclear_fraction: float | None = None) -> dict:
    """Prove that processing did not alter tissue structure.

    Both images are first converted to rank-normalised grey (invariant to any global monotonic
    intensity mapping), then compared with:
    * SSIM (structural similarity, Wang et al. 2004)
    * Pearson r of Sobel edge maps (cell and nuclear boundaries)
    * Nuclear mask agreement (Dice): the darkest-pixel fraction that Otsu assigns to nuclei in the
      original is taken from both images, so identical nuclei give Dice = 1
    """
    a, b = _rank_gray(original), _rank_gray(processed)
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
    _, local_score = local_edit_map(original, processed)
    passed = edge_r >= 0.90 and dice >= 0.90 and ssim >= 0.85 and local_score < LOCAL_EDIT_THRESHOLD
    return {"SSIM (structure)": round(float(ssim), 4),
            "Local-edit score (threshold %g)" % LOCAL_EDIT_THRESHOLD: round(local_score, 1), "Edge correlation": round(edge_r, 4),
            "Nuclei mask agreement (Dice)": round(dice, 4), "Dark objects original": int(ca), "Dark objects processed": int(cb),
            "Verdict": "Structure preserved" if passed else "Check: structural change detected", "passed": bool(passed)}


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
