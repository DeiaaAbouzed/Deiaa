"""Congestion (RBC-rich areas) learned from the investigator's own brush strokes.

Colour alone cannot separate packed erythrocytes from other eosinophilic structures in every stain: in the user's rat
H&E sections skeletal-muscle fibres have the same magenta as red cells. Here the investigator paints red cells and
"not red cells" on about ten images; every painted pixel is described by colour and texture at three scales
(smoothed CIELAB and hematoxylin/eosin densities, gradient magnitude, Laplacian of Gaussian and local variance, which
capture the fine granular texture of packed erythrocytes versus the smooth or striated texture of muscle and
collagen), and a small neural network (one hidden layer, NumPy) is trained on them.

The model is validated image by image (each image is predicted by a model trained without it). It is used by the
reader only when it beats the built-in colour rule on the held-out images; the comparison is kept with the model and
the methods text discloses it. Labels and model stay on this computer."""
from __future__ import annotations

import datetime as _dt
import json
import os

import numpy as np
from scipy import ndimage as ndi

WORK_SIDE = 1024          # features are computed on the image resized to this longest side (same in training and use)
SIGMAS = (1.0, 2.0, 4.0)
PER_IMAGE = 4000          # sampled pixels per class per image
FEATURE_VERSION = 1

METHOD_TEXT = ("RBC-rich (congested or haemorrhagic) areas were proposed by a pixel classifier trained in MedStatix Pro "
               "on the investigator's own annotations ({n_img} images, colour and multi-scale texture features); in "
               "leave-one-image-out validation it reached a pixel F1 of {f1:.2f} versus {f1_rule:.2f} for a colour "
               "threshold. All proposed areas were reviewed by the investigator.")


def _dir():
    from .training import store_dir
    return store_dir()


def _store():
    return os.path.join(_dir(), "rbc_examples.npz")


def model_path():
    return os.path.join(_dir(), "rbc_user.json")


# ----------------------------------------------------------------------------- features


def work_scale(shape):
    return min(1.0, WORK_SIDE / max(shape[:2]))


def _resize(img, s):
    if s >= 1.0:
        return img
    from skimage.transform import resize
    H, W = img.shape[:2]
    return resize(img, (max(1, round(H * s)), max(1, round(W * s))), order=1, anti_aliasing=True, preserve_range=True)


def feature_stack(img):
    """(h, w, F) float32 features of the image at the working scale, and the scale used."""
    from skimage import color
    s = work_scale(img.shape)
    f = np.clip(_resize(img[..., :3].astype(np.float64) / (255.0 if img.dtype == np.uint8 else 1.0), s), 0, 1)
    lab = color.rgb2lab(f)
    L, a, b = lab[..., 0] / 100, lab[..., 1] / 100, lab[..., 2] / 100
    hed = color.rgb2hed(f)
    h, e = hed[..., 0] * 10, hed[..., 1] * 10
    F = [ndi.gaussian_filter(c, 0.7) for c in (L, a, b, h, e)]
    for sg in SIGMAS:
        gL, ga = ndi.gaussian_filter(L, sg), ndi.gaussian_filter(a, sg)
        F += [gL, ga, ndi.gaussian_filter(e, sg),
              ndi.gaussian_gradient_magnitude(L, sg),
              ndi.gaussian_laplace(L, sg),
              np.sqrt(np.maximum(ndi.gaussian_filter(a * a, sg) - ga * ga, 0)),
              np.sqrt(np.maximum(ndi.gaussian_filter(L * L, sg) - gL * gL, 0))]
    return np.stack(F, -1).astype(np.float32), s


N_FEATURES = 5 + 7 * len(SIGMAS)


def colour_rule(img):
    """The built-in colour rule (imaging.core.congestion_area), for comparison."""
    from . import core as IC
    return IC._congestion_rule(img)[1]


# ----------------------------------------------------------------------------- examples


def load_examples():
    p = _store()
    if not os.path.exists(p):
        return (np.zeros((0, N_FEATURES), np.float32), np.zeros(0, int), np.zeros(0, dtype=object), np.zeros(0, bool))
    z = np.load(p, allow_pickle=True)
    return z["X"], z["y"], z["img"], z["rule"]


def add_examples(img, rbc_mask, bg_mask, image_name, seed=0):
    """Store sampled features of the painted pixels of one image (replacing earlier labels of that image).
    Masks are boolean arrays of the image size. Returns the total number of stored pixels."""
    Fs, s = feature_stack(img)
    h, w = Fs.shape[:2]
    rule = colour_rule(img)
    rng = np.random.default_rng(seed)
    Xs, ys, rs = [], [], []
    for cls, m in ((1, rbc_mask), (0, bg_mask)):
        yy, xx = np.nonzero(m)
        if not len(yy):
            continue
        k = rng.choice(len(yy), min(PER_IMAGE, len(yy)), replace=False)
        yy, xx = yy[k], xx[k]
        Xs.append(Fs[np.minimum((yy * s).astype(int), h - 1), np.minimum((xx * s).astype(int), w - 1)])
        ys.append(np.full(len(yy), cls)); rs.append(rule[yy, xx])
    X0, y0, g0, r0 = load_examples()
    keep = g0 != image_name
    if Xs:
        X1 = np.concatenate([X0[keep]] + Xs); y1 = np.concatenate([y0[keep]] + ys)
        r1 = np.concatenate([r0[keep]] + rs); g1 = np.concatenate([g0[keep], np.array([image_name] * sum(map(len, ys)), dtype=object)])
    else:
        X1, y1, g1, r1 = X0[keep], y0[keep], g0[keep], r0[keep]
    np.savez_compressed(_store(), X=X1, y=y1, img=g1, rule=r1)
    return len(y1)


def summary():
    X, y, g, _ = load_examples()
    return {"images": int(len(set(g.tolist()))), "rbc": int((y == 1).sum()), "background": int((y == 0).sum())}


def clear():
    for p in (_store(), model_path()):
        if os.path.exists(p):
            os.remove(p)
    reset()


# ----------------------------------------------------------------------------- network


def _forward(layers, H):
    acts = [H]
    for i, (w, b) in enumerate(layers):
        H = H @ w + b
        if i < len(layers) - 1:
            H = np.maximum(H, 0)
        acts.append(H)
    return acts, 1 / (1 + np.exp(-np.clip(acts[-1][:, 0], -30, 30)))


def _fit(X, y, hidden=24, epochs=400, lr=1e-2, l2=1e-4, seed=0):
    rng = np.random.default_rng(seed)
    mean = X.mean(0); scale = X.std(0) + 1e-6
    H0 = (X - mean) / scale
    d = H0.shape[1]
    layers = [(rng.normal(0, np.sqrt(2 / d), (d, hidden)), np.zeros(hidden)),
              (rng.normal(0, np.sqrt(1 / hidden), (hidden, 1)), np.zeros(1))]
    npos = max(1, (y == 1).sum()); nneg = max(1, (y == 0).sum())
    sw = np.where(y == 1, 0.5 / npos, 0.5 / nneg)
    m = [(np.zeros_like(w), np.zeros_like(b)) for w, b in layers]
    v = [(np.zeros_like(w), np.zeros_like(b)) for w, b in layers]
    for t in range(1, epochs + 1):
        acts, p = _forward(layers, H0)
        dz = ((p - y) * sw)[:, None]
        grads = [None, None]
        for i in (1, 0):
            w, b = layers[i]
            grads[i] = (acts[i].T @ dz + l2 * w, dz.sum(0))
            if i:
                dz = (dz @ w.T) * (acts[i] > 0)
        for i, (gw, gb) in enumerate(grads):
            (mw, mb), (vw, vb) = m[i], v[i]
            mw = 0.9 * mw + 0.1 * gw; mb = 0.9 * mb + 0.1 * gb
            vw = 0.999 * vw + 0.001 * gw * gw; vb = 0.999 * vb + 0.001 * gb * gb
            m[i], v[i] = (mw, mb), (vw, vb)
            a = lr * np.sqrt(1 - 0.999 ** t) / (1 - 0.9 ** t)
            w, b = layers[i]
            layers[i] = (w - a * mw / (np.sqrt(vw) + 1e-8), b - a * mb / (np.sqrt(vb) + 1e-8))
    return {"mean": mean, "scale": scale, "layers": layers}


def _proba(M, X):
    return _forward(M["layers"], (X - M["mean"]) / M["scale"])[1]


def _f1(y, pred):
    tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum()); fn = int((~pred & (y == 1)).sum())
    return 2 * tp / max(2 * tp + fp + fn, 1)


def _auc(y, s):
    order = np.argsort(s); r = np.empty(len(s)); r[order] = np.arange(1, len(s) + 1)
    n1 = (y == 1).sum(); n0 = len(y) - n1
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / max(n1 * n0, 1))


def train(progress=None, epochs=400):
    """Leave-one-image-out validation, then a final fit on everything. Activates the model only when its held-out
    F1 beats the colour rule on the same pixels. Returns the report."""
    X, y, g, rule = load_examples()
    imgs = sorted(set(g.tolist()))
    if len(imgs) < 3 or (y == 1).sum() < 200 or (y == 0).sum() < 200:
        raise ValueError("Paint red cells and background on at least 3 images (ideally about 10).")
    p_cv = np.zeros(len(y))
    for i, im in enumerate(imgs):
        te = g == im
        p_cv[te] = _proba(_fit(X[~te], y[~te], epochs=epochs, seed=i), X[te])
        if progress:
            progress(i + 1, len(imgs) + 1)
    ths = np.linspace(0.2, 0.8, 25)
    f1s = [_f1(y, p_cv >= t) for t in ths]
    th = float(ths[int(np.argmax(f1s))])
    per_img = {}
    for im in imgs:
        k = g == im
        per_img[im] = (f"F1 {_f1(y[k], p_cv[k] >= th):.2f}" if (y[k] == 1).any()
                       else f"false positives {100 * (p_cv[k] >= th).mean():.1f}% of painted background")
    rep = {"date": _dt.datetime.now().isoformat(timespec="minutes"), "images": len(imgs),
           "pixels_rbc": int((y == 1).sum()), "pixels_background": int((y == 0).sum()),
           "cv": f"leave-one-image-out ({len(imgs)} images)", "threshold": round(th, 3),
           "f1": round(max(f1s), 3), "auc": round(_auc(y, p_cv), 3), "f1_rule": round(_f1(y, rule.astype(bool)), 3),
           "f1_per_image": per_img}
    M = _fit(X, y, epochs=epochs, seed=99)
    if progress:
        progress(len(imgs) + 1, len(imgs) + 1)
    rep["activated"] = bool(rep["f1"] > rep["f1_rule"])
    if rep["activated"]:
        with open(model_path(), "w", encoding="utf-8") as fh:
            json.dump({"version": FEATURE_VERSION, "work_side": WORK_SIDE, "mean": M["mean"].tolist(),
                       "scale": M["scale"].tolist(), "layers": [(w.tolist(), b.tolist()) for w, b in M["layers"]],
                       "threshold": th, "report": rep}, fh)
    elif os.path.exists(model_path()):
        os.remove(model_path())
    reset()
    return rep


# ----------------------------------------------------------------------------- use

_M = None


def reset():
    global _M
    _M = None


def active():
    try:
        from ..core.settings import SETTINGS
        if not getattr(SETTINGS, "ai_user_model", True):
            return False
    except Exception:
        pass
    return os.path.exists(model_path())


def model():
    global _M
    if _M is None:
        with open(model_path(), encoding="utf-8") as fh:
            d = json.load(fh)
        d["mean"] = np.asarray(d["mean"]); d["scale"] = np.asarray(d["scale"])
        d["layers"] = [(np.asarray(w), np.asarray(b)) for w, b in d["layers"]]
        _M = d
    return _M


def probability(img):
    """Pixel probability map at full image size."""
    Fs, s = feature_stack(img)
    h, w = Fs.shape[:2]
    p = _proba(model(), Fs.reshape(-1, Fs.shape[-1]).astype(np.float64)).reshape(h, w)
    if s < 1.0:
        from skimage.transform import resize
        p = resize(p, img.shape[:2], order=1, preserve_range=True)
    return p


def predict_mask(img, min_px=25):
    from . import core as IC
    M = model()
    m = probability(img) >= M["threshold"]
    m = ndi.binary_opening(m, iterations=1)
    return IC._drop_small(m, min_px)


def methods_text():
    r = model()["report"]
    return METHOD_TEXT.format(n_img=r["images"], f1=r["f1"], f1_rule=r["f1_rule"])
