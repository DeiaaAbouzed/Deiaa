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
import math
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


N_GATE = 6      # tissue_gate.features columns


def load_examples(with_gate=False):
    p = _store_path()
    if not os.path.exists(p):
        out = (np.zeros((0, len(CC.FEATURES)), np.float32), np.zeros(0, int), np.zeros(0, dtype=object))
        return out + (np.zeros((0, N_GATE)),) if with_gate else out
    z = np.load(p, allow_pickle=True)
    out = (z["X"], z["y"], z["img"])
    if with_gate:
        G = z["G"] if "G" in z.files else np.full((len(z["y"]), N_GATE), np.nan)
        out = out + (G,)
    return out


def add_examples(X, y, image_name, G=None):
    """Add (or replace) the labelled nuclei of one image. G: their rodent-gate features (context of the whole image)."""
    X0, y0, g0, G0 = load_examples(with_gate=True)
    keep = g0 != image_name
    n = len(X)
    Gn = np.asarray(G, float).reshape(n, N_GATE) if G is not None else np.full((n, N_GATE), np.nan)
    X1 = np.concatenate([X0[keep], np.asarray(X, np.float32).reshape(n, -1)])
    y1 = np.concatenate([y0[keep], np.asarray(y, int)])
    g1 = np.concatenate([g0[keep], np.array([image_name] * n, dtype=object)])
    G1 = np.concatenate([G0[keep], Gn])
    np.savez_compressed(_store_path(), X=X1, y=y1, img=g1, G=G1)
    return len(y1)


def uncertain(reading, k=25, exclude=()):
    """Indices of the nuclei the reader is least sure about (most informative to label next): gate probability
    closest to its decision point in rodent tissue, otherwise the highest entropy of the cell-type classifier."""
    cells = reading.get("cells") or []
    if not cells:
        return []
    if reading.get("G") is not None and any("p_infl_builtin" in c for c in cells):
        u = -np.abs(np.array([c["p_infl"] for c in cells]) - 0.65)
    else:
        P = np.clip(CC.predict_proba(reading["X"]), 1e-6, 1)
        u = -(P * np.log(P)).sum(1)
    order = [int(i) for i in np.argsort(-u) if int(i) not in set(exclude)]
    # spread the suggestions over the image: skip nuclei within 3 nuclear diameters of one already chosen
    pick = []
    for i in order:
        c = cells[i]; r = 3 * 2 * (c["area_px"] / np.pi) ** 0.5
        if all(np.hypot(c["x"] - cells[j]["x"], c["y"] - cells[j]["y"]) > r for j in pick):
            pick.append(i)
        if len(pick) >= k:
            break
    return pick


def summary():
    X, y, g = load_examples()
    return {"images": int(len(set(g.tolist()))), "nuclei": int(len(y)),
            **{LABELS[k]: int((y == k).sum()) for k in range(4)}}


def clear_examples():
    from . import tissue_gate as TG
    for p in (_store_path(), CC.user_weights_path(), TG.user_path()):
        if os.path.exists(p):
            os.remove(p)
    CC.reset(); TG.reset()


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


# ----------------------------------------------------------------------------- rodent gate refit


def _lr(Z, y, l2=1e-2, iters=60):
    """Class-balanced L2 logistic regression by Newton's method."""
    A = np.c_[Z, np.ones(len(Z))]
    w = np.zeros(A.shape[1])
    sw = np.where(y == 1, 0.5 / max(1, (y == 1).sum()), 0.5 / max(1, (y == 0).sum())) * len(y)
    R = l2 * np.eye(A.shape[1]); R[-1, -1] = 0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(A @ w, -30, 30)))
        g = A.T @ (sw * (p - y)) + R @ w
        Hs = (A * (sw * p * (1 - p))[:, None]).T @ A + R
        step = np.linalg.solve(Hs + 1e-9 * np.eye(len(w)), g)
        w -= step
        if np.abs(step).max() < 1e-7:
            break
    return w[:-1], float(w[-1])


def _best_f1(y, z):
    best = (0.0, 0.0)
    for t in np.quantile(z, np.linspace(0.02, 0.98, 49)):
        pr = z >= t
        tp = (pr & (y == 1)).sum(); f = 2 * tp / max(2 * tp + (pr & (y == 0)).sum() + (~pr & (y == 1)).sum(), 1)
        best = max(best, (float(f), float(t)))
    return best


def train_gate():
    """Refit the rodent inflammatory gate (inflammatory vs every other label) on the user's labelled nuclei.
    Leave-one-image-out; the refitted gate is activated only when its held-out F1 at its own best threshold beats
    the built-in gate on the same nuclei. Returns a report, or None when there are not enough gate-ready labels."""
    from . import tissue_gate as TG
    X, y, g, G = load_examples(with_gate=True)
    ok = np.isfinite(G).all(1)
    G, yb, g = G[ok], (y[ok] == 1).astype(int), g[ok]
    imgs = sorted(set(g.tolist()))
    if len(imgs) < 3 or yb.sum() < 15 or (yb == 0).sum() < 15:
        return None
    B = TG.builtin()
    z_old = TG.logit(G, B)
    z_new = np.zeros(len(yb))
    for im in imgs:
        te = g == im
        if len(set(yb[~te].tolist())) < 2:
            z_new[te] = z_old[te]; continue
        mu, sd = G[~te].mean(0), G[~te].std(0) + 1e-6
        c, b0 = _lr((G[~te] - mu) / sd, yb[~te])
        z_new[te] = ((G[te] - mu) / sd) @ c + b0
    t_old = math.log(B["threshold"] / (1 - B["threshold"]))
    # the built-in gate is credited with the better of its own threshold and the best threshold on these nuclei
    f_old_fixed = max(_best_f1_at(yb, z_old, t_old), _best_f1(yb, z_old)[0])
    f_new, t_new = _best_f1(yb, z_new)
    mu, sd = G.mean(0), G.std(0) + 1e-6
    c, b0 = _lr((G - mu) / sd, yb)
    rep = {"images": len(imgs), "nuclei": int(len(yb)), "inflammatory": int(yb.sum()),
           "f1_builtin_gate": round(f_old_fixed, 3), "f1_user_gate": round(f_new, 3),
           "auc_builtin_gate": round(_auc(yb, z_old), 3), "auc_user_gate": round(_auc(yb, z_new), 3)}
    rep["activated"] = bool(f_new > f_old_fixed and rep["auc_user_gate"] >= rep["auc_builtin_gate"])
    if rep["activated"]:
        thr = float(1 / (1 + math.exp(-t_new)))
        with open(TG.user_path(), "w", encoding="utf-8") as fh:
            json.dump({"mean": mu.tolist(), "scale": sd.tolist(), "coef": c.tolist(), "intercept": b0,
                       "threshold": min(max(thr, 0.05), 0.95), "report": rep,
                       "trained_on": f"{len(yb)} user-labelled nuclei from {len(imgs)} images"}, fh)
    elif os.path.exists(TG.user_path()):
        os.remove(TG.user_path())
    TG.reset()
    return rep


def _best_f1_at(y, z, t):
    pr = z >= t
    tp = (pr & (y == 1)).sum()
    return float(2 * tp / max(2 * tp + (pr & (y == 0)).sum() + (~pr & (y == 1)).sum(), 1))


def _auc(y, s):
    order = np.argsort(s); r = np.empty(len(s)); r[order] = np.arange(1, len(s) + 1)
    n1 = (y == 1).sum(); n0 = len(y) - n1
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / max(n1 * n0, 1))
