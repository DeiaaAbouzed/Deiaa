"""Nucleus detection with a pretrained deep-learning model (StarDist 2D 'versatile H&E', Schmidt et al. 2018, Weigert et al.
2020; BSD-3 code, model trained on MoNuSeg 2018 and TNBC). The Keras network was converted to ONNX and is run offline with
onnxruntime; the star-convex polygon post-processing (probability threshold + non-maximum suppression with overlap =
intersection / smaller area) follows the reference implementation.

The model reads the image; it never writes pixels. Detections are suggestions that the user reviews."""
from __future__ import annotations

import math
import os

import numpy as np

MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "models", "stardist_he.onnx")
PROB_THRESH = 0.6924782541382084
NMS_THRESH = 0.3
N_RAYS = 32
GRID = 2
DIV = 16
REF_AREA = 220.0   # typical median nucleus area (px²) in the training data (40×, ~0.25 µm/px)
REF_UM_PER_PX = 0.25   # resolution of the training images (40× objective)
MAX_PIXELS = 16_000_000


def scale_for(um_per_px, shape):
    """Working scale for a calibrated image: brings it to the training resolution, within the memory budget."""
    s = um_per_px / REF_UM_PER_PX
    return float(np.clip(s, 0.5, min(5.0, math.sqrt(MAX_PIXELS / (shape[0] * shape[1])))))
CITATION = ("Schmidt U, Weigert M, Broaddus C, Myers G. Cell detection with star-convex polygons. MICCAI 2018; "
            "Weigert M, Schmidt U, Haase R, Sugawara K, Myers G. Star-convex polyhedra for 3D object detection and "
            "segmentation in microscopy. WACV 2020.")

_SESSION = None


def available() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except Exception:
        return False
    return os.path.exists(MODEL_PATH)


def _session():
    global _SESSION
    if _SESSION is None:
        import onnxruntime as ort
        so = ort.SessionOptions(); so.log_severity_level = 3
        _SESSION = ort.InferenceSession(MODEL_PATH, so, providers=["CPUExecutionProvider"])
    return _SESSION


def _normalize(img):
    x = img.astype(np.float32)
    lo, hi = np.percentile(x, (1, 99.8))
    return ((x - lo) / max(hi - lo, 1e-6)).astype(np.float32)


def _run(x):
    """x: normalised float32 HxWx3 → prob (H/2, W/2), dist (H/2, W/2, 32). Pads to a multiple of 16 (reflect)."""
    H, W = x.shape[:2]
    ph, pw = (-H) % DIV, (-W) % DIV
    xp = np.pad(x, ((0, ph), (0, pw), (0, 0)), mode="reflect") if (ph or pw) else x
    s = _session()
    prob, dist = s.run(None, {s.get_inputs()[0].name: np.ascontiguousarray(xp[None], np.float32)})
    return prob[0, :H // GRID, :W // GRID, 0], dist[0, :H // GRID, :W // GRID]


def predict(img, tile=1024, overlap=96):
    """Dense prediction, tiled for large images. img: uint8 RGB."""
    x = _normalize(img[..., :3])
    H, W = x.shape[:2]
    if H <= tile + overlap and W <= tile + overlap:
        return _run(x)
    prob = np.zeros((H // GRID, W // GRID), np.float32)
    dist = np.zeros((H // GRID, W // GRID, N_RAYS), np.float32)
    for y0 in range(0, H, tile):
        for x0 in range(0, W, tile):
            ya, xa = max(0, y0 - overlap), max(0, x0 - overlap)
            yb, xb = min(H, y0 + tile + overlap), min(W, x0 + tile + overlap)
            ya -= ya % GRID; xa -= xa % GRID
            p, d = _run(x[ya:yb, xa:xb])
            cy0, cx0 = (y0 - ya) // GRID, (x0 - xa) // GRID
            cy1 = cy0 + (min(H, y0 + tile) - y0) // GRID; cx1 = cx0 + (min(W, x0 + tile) - x0) // GRID
            prob[y0 // GRID:y0 // GRID + cy1 - cy0, x0 // GRID:x0 // GRID + cx1 - cx0] = p[cy0:cy1, cx0:cx1]
            dist[y0 // GRID:y0 // GRID + cy1 - cy0, x0 // GRID:x0 // GRID + cx1 - cx0] = d[cy0:cy1, cx0:cx1]
    return prob, dist


def _polys(points, dist):
    phi = np.linspace(0, 2 * np.pi, N_RAYS, endpoint=False)
    ys = points[:, :1] + dist * np.sin(phi)[None]
    xs = points[:, 1:] + dist * np.cos(phi)[None]
    return ys, xs


def nms(prob, dist, shape, prob_thresh=PROB_THRESH, nms_thresh=NMS_THRESH, b=2, fast=True):
    """Greedy NMS on rasterised star-convex polygons. Returns label image and list of nuclei (highest prob first)."""
    from skimage.draw import polygon as draw_polygon
    mask = prob > prob_thresh
    if fast:
        # only local maxima of the probability map become candidates: the same nuclei, ~5–10× fewer polygons to rasterise
        from scipy.ndimage import maximum_filter
        mask &= prob >= maximum_filter(prob, size=3)
    if b:
        m2 = np.zeros_like(mask); m2[b:-b, b:-b] = True; mask &= m2
    pts = np.argwhere(mask)
    if not len(pts):
        return np.zeros(shape, np.int32), []
    sc = prob[mask]; d = dist[mask]
    order = np.argsort(sc)[::-1]
    pts, sc, d = pts[order] * GRID, sc[order], d[order]
    ys, xs = _polys(pts.astype(float), d)
    H, W = shape
    lab = np.zeros((H, W), np.int32)
    areas = [0]
    keep = []
    for i in range(len(pts)):
        rr, cc = draw_polygon(ys[i], xs[i], (H, W))
        a = len(rr)
        if a < 6:
            continue
        under = lab[rr, cc]
        hit = under[under > 0]
        if hit.size:
            ids, cnt = np.unique(hit, return_counts=True)
            if np.any(cnt / np.minimum(a, np.asarray(areas)[ids]) > nms_thresh):
                continue
        free = under == 0
        k = len(keep) + 1
        lab[rr[free], cc[free]] = k
        areas.append(a)
        keep.append({"y": float(pts[i, 0]), "x": float(pts[i, 1]), "prob": float(sc[i]),
                     "poly": np.stack([ys[i], xs[i]], 1).astype(np.float32)})
    return lab, keep


def detect(img, scale="auto", prob_thresh=PROB_THRESH, nms_thresh=NMS_THRESH, keep_scaled=False, detect_on=None):
    """Detect nuclei. scale='auto' rescales low-magnification images so nuclei reach the size the model was trained on.
    Returns (label image at the original size, nuclei list with coordinates in original pixels, scale used); with
    keep_scaled=True also (image, label image) at the working scale, where the cell features are measured.
    detect_on: optional image of the same size that the network looks at instead of `img` (e.g. a hematoxylin-like
    rendering of an IHC image); `img` is what is returned for measurement."""
    meas = img
    if detect_on is not None:
        img = detect_on
    from skimage.transform import rescale, resize
    img = img[..., :3]
    H, W = img.shape[:2]

    def at(s):
        im = img if s == 1 else (rescale(img, s, order=1, channel_axis=2, preserve_range=True, anti_aliasing=s < 1).astype(np.uint8))
        p, d = predict(im)
        lab, nu = nms(p, d, im.shape[:2], prob_thresh, nms_thresh)
        return lab, nu

    if scale == "auto":
        # the model was trained at ~40× (nuclei ≈ 150–600 px²). Low-magnification images are enlarged until nuclei
        # reach that size; images are only reduced when they are too large for memory.
        budget = 12_000_000
        s = min(1.0, math.sqrt(budget / (H * W)))
        lab, nu = at(s)
        med = np.median(np.bincount(lab.ravel())[1:]) / (s * s) if len(nu) >= 5 else 0.0
        if (len(nu) < 5 or med < 90 or max(H, W) < 1000) and s >= 1.0:
            best = (len(nu), s, lab, nu)
            cands = [math.sqrt(REF_AREA / med)] if med else []
            cands += [2.0, 3.0, 4.0]
            for s2 in sorted({round(float(np.clip(c, 1.5, 4.0)), 1) for c in cands}):
                if s2 * s2 * H * W > budget:
                    continue
                l2, n2 = at(s2)
                if len(n2) > best[0] * 1.15:
                    best = (len(n2), s2, l2, n2)
            _, s, lab, nu = best
    else:
        s = float(scale); lab, nu = at(s)
    lab_s = lab
    img_s = meas[..., :3] if s == 1 else rescale(meas[..., :3], s, order=1, channel_axis=2, preserve_range=True,
                                                    anti_aliasing=s < 1).astype(np.uint8)
    if s != 1:
        lab = resize(lab, (H, W), order=0, preserve_range=True, anti_aliasing=False).astype(np.int32)
        for n in nu:
            n["y"] /= s; n["x"] /= s; n["poly"] = n["poly"] / s
    if keep_scaled:
        return lab, nu, s, img_s, lab_s
    return lab, nu, s
