"""Teach the nucleus-type classifier on the user's own slides (for example rat liver or kidney).

Workflow: the AI reader detects the nuclei; the user labels some of them by clicking (inflammatory / epithelial /
spindle / other); the features of each labelled nucleus are stored locally (never uploaded). Training fine-tunes the
built-in network starting from its weights, with an L2 penalty that keeps it close to the original (L2-SP, Li et al.
2018) so that a few hundred examples adapt it without forgetting what it learned from CoNSeP.

Before the new model is used it is validated by cross-validation grouped by image (each image is predicted by a model
that never saw it). The fine-tuned model is only activated when its held-out macro-F1 is at least as good as the
built-in model on the same nuclei; the report shows both."""
from __future__ import annotations

import datetime as _dt
import json
import os

import numpy as np

from . import cellclass as CC

LABELS = ["other", "inflammatory", "epithelial", "spindle"]


def store_dir():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    d = os.path.join(base, "MedStatix", "ai")
    os.makedirs(d, exist_ok=True)
    return d


def _store_path():
    return os.path.join(store_dir(), "user_nuclei_labels.npz")


def load_examples():
    p = _store_path()
    if not os.path.exists(p):
        return np.zeros((0, len(CC.FEATURES)), np.float32), np.zeros(0, int), np.zeros(0, dtype=object)
    z = np.load(p, allow_pickle=True)
    return z["X"], z["y"], z["img"]


def add_examples(X, y, image_name):
    """Add (or replace) the labelled nuclei of one image."""
    X0, y0, g0 = load_examples()
    keep = g0 != image_name
    X1 = np.concatenate([X0[keep], np.asarray(X, np.float32)]) if len(X) else X0[keep]
    y1 = np.concatenate([y0[keep], np.asarray(y, int)]) if len(X) else y0[keep]
    g1 = np.concatenate([g0[keep], np.array([image_name] * len(X), dtype=object)]) if len(X) else g0[keep]
    np.savez_compressed(_store_path(), X=X1, y=y1, img=g1)
    return len(y1)


def summary():
    X, y, g = load_examples()
    return {"images": int(len(set(g.tolist()))), "nuclei": int(len(y)),
            **{LABELS[k]: int((y == k).sum()) for k in range(4)}}


def clear_examples():
    for p in (_store_path(), CC.user_weights_path()):
        if os.path.exists(p):
            os.remove(p)
    CC.reset()


# ----------------------------------------------------------------------------- NumPy MLP


def _base():
    with open(CC.WEIGHTS, encoding="utf-8") as fh:
        W = json.load(fh)
    return W, [(np.asarray(w, np.float64), np.asarray(b, np.float64)) for w, b in W["layers"]]


def _forward(layers, H):
    acts = [H]
    for i, (w, b) in enumerate(layers):
        H = H @ w + b
        if i < len(layers) - 1:
            H = np.maximum(H, 0)
        acts.append(H)
    Z = acts[-1] - acts[-1].max(1, keepdims=True)
    P = np.exp(Z); P /= P.sum(1, keepdims=True)
    return acts, P


def _fit(X, y, mean, scale, init, epochs=300, lr=3e-3, lam=1e-2, seed=0):
    """Full-batch Adam on class-weighted cross-entropy + λ‖θ − θ₀‖² (L2-SP)."""
    rng = np.random.default_rng(seed)
    H0 = (X - mean) / scale
    layers = [(w.copy(), b.copy()) for w, b in init]
    ref = [(w.copy(), b.copy()) for w, b in init]
    cnt = np.bincount(y, minlength=4).astype(float)
    cw = np.where(cnt > 0, len(y) / (4 * np.maximum(cnt, 1)), 0.0)
    sw = cw[y]; sw /= sw.sum()
    Y = np.eye(4)[y]
    m = [(np.zeros_like(w), np.zeros_like(b)) for w, b in layers]
    v = [(np.zeros_like(w), np.zeros_like(b)) for w, b in layers]
    b1, b2 = 0.9, 0.999
    for t in range(1, epochs + 1):
        H = H0 + rng.normal(0, 0.02, H0.shape)          # small input noise as augmentation
        acts, P = _forward(layers, H)
        d = (P - Y) * sw[:, None]
        grads = [None] * len(layers)
        for i in range(len(layers) - 1, -1, -1):
            w, b = layers[i]
            gw = acts[i].T @ d + 2 * lam * (w - ref[i][0]); gb = d.sum(0) + 2 * lam * (b - ref[i][1])
            grads[i] = (gw, gb)
            if i:
                d = (d @ w.T) * (acts[i] > 0)
        for i, (gw, gb) in enumerate(grads):
            mw, mb = m[i]; vw, vb = v[i]
            mw = b1 * mw + (1 - b1) * gw; mb = b1 * mb + (1 - b1) * gb
            vw = b2 * vw + (1 - b2) * gw * gw; vb = b2 * vb + (1 - b2) * gb * gb
            m[i] = (mw, mb); v[i] = (vw, vb)
            a = lr * np.sqrt(1 - b2 ** t) / (1 - b1 ** t)
            w, b = layers[i]
            layers[i] = (w - a * mw / (np.sqrt(vw) + 1e-8), b - a * mb / (np.sqrt(vb) + 1e-8))
    return layers


def _predict(layers, X, mean, scale):
    return _forward(layers, (X - mean) / scale)[1].argmax(1)


def _f1(y, p):
    out = {}
    for k in range(4):
        tp = int(((p == k) & (y == k)).sum()); fp = int(((p == k) & (y != k)).sum()); fn = int(((p != k) & (y == k)).sum())
        if tp + fn == 0:
            continue
        out[LABELS[k]] = 2 * tp / max(2 * tp + fp + fn, 1)
    return out


def train(epochs=300, lam=1e-2, progress=None):
    """Cross-validate, then fit on all examples. Returns a report dict; activates the model if it is not worse."""
    X, y, g = load_examples()
    if len(y) < 40 or len(set(y.tolist())) < 2:
        raise ValueError("Label at least 40 nuclei of at least two types (ideally 10–20 images, 30+ nuclei per type).")
    W, init = _base()
    mean = np.asarray(W["mean"], np.float64); scale = np.asarray(W["scale"], np.float64)
    imgs = sorted(set(g.tolist()))
    if len(imgs) >= 3:
        folds = [g == im for im in imgs]
        cv_kind = f"leave-one-image-out ({len(imgs)} images)"
    else:
        rng = np.random.default_rng(1); idx = rng.permutation(len(y)); k = 5
        folds = [np.isin(np.arange(len(y)), idx[i::k]) for i in range(k)]
        cv_kind = "5-fold (fewer than 3 images: nuclei of the same image appear in training and test)"
    pred_new = np.zeros(len(y), int)
    for i, te in enumerate(folds):
        tr = ~te
        if te.sum() == 0 or len(set(y[tr].tolist())) < 2:
            pred_new[te] = _predict(init, X[te], mean, scale); continue
        L = _fit(X[tr], y[tr], mean, scale, init, epochs, lam=lam)
        pred_new[te] = _predict(L, X[te], mean, scale)
        if progress:
            progress(i + 1, len(folds) + 1)
    pred_old = _predict(init, X, mean, scale)
    f_old, f_new = _f1(y, pred_old), _f1(y, pred_new)
    macro_old = float(np.mean(list(f_old.values()))); macro_new = float(np.mean(list(f_new.values())))
    acc_old = float((pred_old == y).mean()); acc_new = float((pred_new == y).mean())
    L = _fit(X, y, mean, scale, init, epochs, lam=lam)
    if progress:
        progress(len(folds) + 1, len(folds) + 1)
    activated = macro_new >= macro_old
    report = {"date": _dt.datetime.now().isoformat(timespec="minutes"), "images": len(imgs), "nuclei": int(len(y)),
              "per_class_n": {LABELS[k]: int((y == k).sum()) for k in range(4)}, "cv": cv_kind,
              "f1_builtin": {k: round(v, 3) for k, v in f_old.items()}, "f1_finetuned": {k: round(v, 3) for k, v in f_new.items()},
              "macro_f1_builtin": round(macro_old, 3), "macro_f1_finetuned": round(macro_new, 3),
              "accuracy_builtin": round(acc_old, 3), "accuracy_finetuned": round(acc_new, 3), "activated": bool(activated)}
    if activated:
        out = dict(W)
        out["layers"] = [(w.astype(np.float32).tolist(), b.astype(np.float32).tolist()) for w, b in L]
        out["trained_on"] = W.get("trained_on", "") + f" + fine-tuned on {len(y)} user-labelled nuclei from {len(imgs)} images"
        out["test_report"] = report
        with open(CC.user_weights_path(), "w", encoding="utf-8") as fh:
            json.dump(out, fh)
        CC.reset()
    return report
