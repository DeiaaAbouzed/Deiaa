"""Per-nucleus features and the nucleus-type classifier (inflammatory / epithelial / spindle / other).

The classifier is a small neural network (MLP) trained on nuclei detected by the StarDist model in the CoNSeP dataset
(Graham et al., HoVer-Net, Medical Image Analysis 2019; colorectal H&E, 40×). The weights are stored as plain JSON and
run with NumPy. Colour features are also expressed relative to the other nuclei of the same image, which reduces the
effect of stain differences between laboratories."""
from __future__ import annotations

import json
import os

import numpy as np
from scipy import ndimage as ndi

CLASSES = ["Other", "Inflammatory", "Epithelial", "Spindle (fibroblast / muscle / endothelial)"]
CLASSES_AR = ["أخرى", "خلية التهابية", "طلائية", "مغزلية (ليفية / عضلية / بطانية)"]
WEIGHTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "models", "nucleus_types.json")
CITATION = ("Graham S, Vu QD, Raza SEA, et al. HoVer-Net: Simultaneous segmentation and classification of nuclei in "
            "multi-tissue histology images. Med Image Anal 2019;58:101563 (CoNSeP dataset).")

RAW = ["area", "perim_ratio", "ecc", "solidity", "minor_major", "ray_cv", "ray_minmax", "prob",
       "h_mean", "h_std", "e_mean", "dab_mean", "gray_mean", "gray_std", "ring_h", "ring_e", "ring_gray", "contrast",
       "n_density", "area_rel_nb", "nb_dist"]
REL = ["h_mean", "e_mean", "gray_mean", "ring_e", "ring_gray", "contrast", "area"]
FEATURES = RAW + [f + "_z" for f in REL]


def _hed(img):
    from skimage.color import rgb2hed
    return rgb2hed(img[..., :3])


def features(img, lab, nuclei, scale=1.0):
    """Feature table (n × len(FEATURES)) for the nuclei of `lab` (ids 1..n, order of `nuclei`).
    `scale` = factor that brings this image to the model's working magnification (size features are multiplied)."""
    from skimage.measure import regionprops
    n = int(lab.max())
    if n == 0:
        return np.zeros((0, len(FEATURES)), np.float32), np.zeros((0, 2))
    hed = _hed(img)
    gray = img[..., :3].astype(np.float32).mean(2) / 255.0
    ring_r = max(2, int(round(4 / max(scale, 1e-3))))
    dil = ndi.grey_dilation(lab, size=(2 * ring_r + 1, 2 * ring_r + 1))
    ring = (lab == 0) & (dil > 0)
    idx = np.arange(1, n + 1)

    def mean(a, mask_lab):
        return np.nan_to_num(ndi.mean(a, mask_lab, idx))

    def std(a, mask_lab):
        return np.nan_to_num(ndi.standard_deviation(a, mask_lab, idx))
    rl = np.where(ring, dil, 0)
    F = {}
    F["h_mean"] = mean(hed[..., 0], lab); F["h_std"] = std(hed[..., 0], lab)
    F["e_mean"] = mean(hed[..., 1], lab); F["dab_mean"] = mean(hed[..., 2], lab)
    F["gray_mean"] = mean(gray, lab); F["gray_std"] = std(gray, lab)
    F["ring_h"] = mean(hed[..., 0], rl); F["ring_e"] = mean(hed[..., 1], rl); F["ring_gray"] = mean(gray, rl)
    F["contrast"] = F["ring_gray"] - F["gray_mean"]
    props = {p.label: p for p in regionprops(lab)}
    s2 = scale * scale
    area = np.zeros(n); per = np.zeros(n); ecc = np.zeros(n); sol = np.zeros(n); mm = np.zeros(n)
    cy = np.zeros(n); cx = np.zeros(n)
    for i in range(1, n + 1):
        p = props.get(i)
        if p is None:
            area[i - 1] = 1; per[i - 1] = 1; sol[i - 1] = 1; mm[i - 1] = 1
            cy[i - 1], cx[i - 1] = nuclei[i - 1]["y"], nuclei[i - 1]["x"]; continue
        area[i - 1] = p.area * s2
        per[i - 1] = (p.perimeter * scale) / max(np.sqrt(4 * np.pi * p.area * s2), 1e-6)
        ecc[i - 1] = p.eccentricity; sol[i - 1] = p.solidity
        mm[i - 1] = p.minor_axis_length / max(p.major_axis_length, 1e-6)
        cy[i - 1], cx[i - 1] = p.centroid
    F["area"] = area; F["perim_ratio"] = per; F["ecc"] = ecc; F["solidity"] = sol; F["minor_major"] = mm
    rays = np.array([np.hypot(*(nu["poly"] - [nu["y"], nu["x"]]).T) for nu in nuclei]) * scale
    F["ray_cv"] = rays.std(1) / np.maximum(rays.mean(1), 1e-6)
    F["ray_minmax"] = rays.min(1) / np.maximum(rays.max(1), 1e-6)
    F["prob"] = np.array([nu["prob"] for nu in nuclei])
    # neighbourhood (radius 40 px at 40× ≈ 10 µm)
    from scipy.spatial import cKDTree
    pts = np.c_[cy, cx] * scale
    tree = cKDTree(pts)
    nb = tree.query_ball_point(pts, r=40.0)
    F["n_density"] = np.array([len(b) - 1 for b in nb], float)
    F["area_rel_nb"] = np.array([area[i] / max(np.median(area[b]), 1.0) for i, b in enumerate(nb)])
    d, _ = tree.query(pts, k=min(2, len(pts)))
    F["nb_dist"] = d[:, 1] if d.ndim == 2 and d.shape[1] > 1 else np.full(n, 60.0)
    for f in REL:
        v = F[f]; F[f + "_z"] = (v - np.median(v)) / (np.percentile(v, 75) - np.percentile(v, 25) + 1e-6)
    X = np.stack([F[f] for f in FEATURES], 1).astype(np.float32)
    return np.nan_to_num(X), np.c_[cy, cx]


_W = None


_W_SRC = None


def user_weights_path():
    from .training import store_dir
    return os.path.join(store_dir(), "nucleus_types_user.json")


def active_source():
    """'user' when a model fine-tuned on the user's own slides is active, else 'built-in'."""
    return "user" if _W_SRC == "user" else "built-in"


def reset():
    global _W, _W_SRC
    _W = None; _W_SRC = None


def load():
    global _W, _W_SRC
    if _W is None:
        src, path = "built-in", WEIGHTS
        try:
            from ..core.settings import SETTINGS
            up = user_weights_path()
            if getattr(SETTINGS, "ai_user_model", True) and os.path.exists(up):
                src, path = "user", up
        except Exception:
            pass
        with open(path, encoding="utf-8") as fh:
            _W = json.load(fh)
        _W_SRC = src
        _W["layers"] = [(np.asarray(w, np.float32), np.asarray(b, np.float32)) for w, b in _W["layers"]]
        _W["mean"] = np.asarray(_W["mean"], np.float32); _W["scale"] = np.asarray(_W["scale"], np.float32)
    return _W


def available():
    return os.path.exists(WEIGHTS)


def predict_proba(X):
    W = load()
    h = (X - W["mean"]) / W["scale"]
    L = W["layers"]
    for i, (w, b) in enumerate(L):
        h = h @ w + b
        if i < len(L) - 1:
            h = np.maximum(h, 0)
    h = h - h.max(1, keepdims=True)
    e = np.exp(h)
    return e / e.sum(1, keepdims=True)
