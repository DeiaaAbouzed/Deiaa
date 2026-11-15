"""Image-integrity tools.

1. ``external_edit_check``: compares an image that was sent to an external editor (Photopea) with the file that came
   back. The sent image is located inside the returned figure (multi-scale normalised cross-correlation, so a panel
   that was placed and resized in a layout is still found), resampled back, and compared pixel by pixel with the
   colour-mapping residual (``local_edit_map``). Labels and arrows show up as small flagged areas; anything else that is
   flagged inside the tissue is a local edit.
2. ``find_duplicates``: a Proofig-style screen of a set of images for duplicated or re-used fields: perceptual hash
   (dHash, on all 8 rotations/flips) for whole-image re-use, ORB keypoint matching with RANSAC for partial overlap
   (cropped, rotated, flipped or rescaled), and within-image clone detection (repeated patches).

Both are screening tools: a flagged pair must be inspected by eye before any conclusion is drawn."""
from __future__ import annotations

import itertools
import math

import numpy as np
from skimage import color, feature, measure, transform

from .core import local_edit_map, integrity_report

# ----------------------------------------------------------------------------- 1. external editor round trip


def _gray_small(img, max_side):
    g = color.rgb2gray(img[..., :3]) if img.ndim == 3 else img.astype(float)
    s = min(1.0, max_side / max(g.shape))
    return (transform.rescale(g, s, anti_aliasing=True) if s < 1 else g), s


def locate(sent, returned, max_side=700):
    """Find where (and at what size) `sent` appears inside `returned`. Returns (y0, x0, h, w, score) in returned px."""
    R, sr = _gray_small(returned, max_side)
    best = None
    H, W = R.shape
    for frac in np.r_[np.linspace(0.15, 1.0, 35)]:
        h = int(round(frac * min(H / sent.shape[0], W / sent.shape[1]) * sent.shape[0]))
        w = int(round(h * sent.shape[1] / sent.shape[0]))
        if h < 24 or w < 24 or h > H or w > W:
            continue
        T = transform.resize(color.rgb2gray(sent[..., :3]), (h, w), anti_aliasing=True)
        m = feature.match_template(R, T)
        y, x = np.unravel_index(np.argmax(m), m.shape)
        sc = float(m[y, x])
        if best is None or sc > best[4]:
            best = (y, x, h, w, sc)
    if best is None:
        return None
    y, x, h, w, sc = best
    return int(y / sr), int(x / sr), int(round(h / sr)), int(round(w / sr)), sc


def _refine(sent, returned, box, pad=6):
    """Refine a coarse location at full resolution (±pad px in position, ±1 % in size)."""
    y, x, h, w, sc = box
    G = color.rgb2gray(returned[..., :3]); S = color.rgb2gray(sent[..., :3])
    best = box
    for dh in sorted({0, -2, 2, -int(0.01 * h), int(0.01 * h)}):
        hh = h + dh; ww = int(round(hh * sent.shape[1] / sent.shape[0]))
        y0, x0 = max(0, y - pad), max(0, x - pad)
        R = G[y0:y + hh + pad, x0:x + ww + pad]
        if R.shape[0] < hh or R.shape[1] < ww or hh < 8:
            continue
        T = transform.resize(S, (hh, ww), anti_aliasing=True)
        m = feature.match_template(R, T)
        j, i = np.unravel_index(np.argmax(m), m.shape)
        if m[j, i] > best[4]:
            best = (y0 + j, x0 + i, hh, ww, float(m[j, i]))
    return best


def _is_mark(region, returned, resid, ref):
    """A drawn label/arrow/line replaces pixels with one flat colour that is unrelated to the tissue underneath; an
    edit of the tissue (cloning, darkening, blurring) leaves textured pixels or keeps the original texture."""
    rr, cc = region.coords[:, 0], region.coords[:, 1]
    o = ref[rr, cc].astype(float); n = returned[rr, cc].astype(float)
    ch = np.abs(n - o).max(1) > 25
    if ch.sum() < 5:
        return True
    o, n = o[ch], n[ch]
    flat = float(np.mean(np.abs(n - np.median(n, 0)).max(1) <= 12)) >= 0.6
    if not flat:
        return False
    og, ng = o.mean(1), n.mean(1)
    if og.std() < 1 or ng.std() < 1:
        return True
    return abs(float(np.corrcoef(og, ng)[0, 1])) < 0.5


def external_edit_check(sent, returned):
    """Return dict with verdict, located box, residual map (in the returned figure's geometry) and metrics."""
    sent = sent[..., :3]; returned = returned[..., :3]
    if sent.shape == returned.shape:
        box = (0, 0, sent.shape[0], sent.shape[1], 1.0)
        ref, crop = sent, returned
    else:
        box = locate(sent, returned)
        if box is None or box[4] < 0.5:
            return {"found": False, "verdict": "The original image could not be found in the returned file "
                                               "(it may have been cropped heavily, rotated or re-drawn).",
                    "verdict_ar": "لم يُعثر على الصورة الأصلية داخل الملف العائد (ربما قُصّت بشدة أو دُوّرت أو أُعيد رسمها)."}
        box = _refine(sent, returned, box)
        y, x, h, w, _ = box
        crop = returned[y:y + h, x:x + w]
        # compare in the geometry of the returned panel, at most at the original resolution
        ref = (transform.resize(sent, (h, w), order=1, anti_aliasing=h < sent.shape[0], preserve_range=True)
               .round().clip(0, 255).astype(np.uint8))
    resampled = sent.shape != returned.shape
    sm, score = local_edit_map(ref, crop, sigma=3.0 if resampled else 2.5)
    thr = float(np.median(sm)) + (0.08 if resampled else 0.05)
    flag = sm > thr
    lab = measure.label(flag)
    regions = [r for r in measure.regionprops(lab) if r.area >= 30]
    flag = np.isin(lab, [r.label for r in regions])
    marks = [r for r in regions if _is_mark(r, crop, sm, ref)]
    tissue = [r for r in regions if r not in marks]
    tissue_px = sum(r.area for r in tissue)
    frac = float(flag.mean()); tfrac = tissue_px / flag.size
    rep = integrity_report(ref, crop) if not resampled else None
    clean = not regions
    if clean:
        v, va = ("No local change: the image inside the figure matches the original (global edits only).",
                 "لا يوجد تعديل موضعي: الصورة داخل اللوحة مطابقة للأصل (تعديلات شاملة فقط).")
    elif not tissue:
        v, va = (f"Only added marks found: {len(marks)} flat-colour area(s) (labels, arrows, lines), {100 * frac:.2f} % of the "
                 f"image. The tissue itself is unchanged.",
                 f"لم يُعثر إلا على إضافات: {len(marks)} منطقة بلون واحد (تسميات أو أسهم أو خطوط) تمثل {100 * frac:.2f}٪ من "
                 f"الصورة، والنسيج نفسه لم يتغير.")
    else:
        v, va = (f"Local change of the tissue detected: {len(tissue)} region(s), {100 * tfrac:.2f} % of the image, that are not "
                 f"flat-colour labels or arrows. Journals treat local edits of tissue as image manipulation; use the original.",
                 f"اكتُشف تعديل موضعي في النسيج: {len(tissue)} منطقة ({100 * tfrac:.2f}٪ من الصورة) ليست تسميات أو أسهماً بلون "
                 f"واحد. المجلات تعدّ التعديل الموضعي للنسيج تلاعباً؛ استخدم الصورة الأصلية.")
    tflag = np.isin(lab, [r.label for r in tissue])
    return {"found": True, "box": box[:4], "match": round(box[4], 3), "map": sm, "flag": flag, "tissue_flag": tflag,
            "regions": len(regions), "marks": len(marks), "tissue_regions": len(tissue),
            "flagged_pct": round(100 * frac, 3), "tissue_pct": round(100 * tfrac, 3), "local_score": round(score, 1),
            "integrity": rep, "clean": clean, "marks_only": bool(regions) and not tissue,
            "verdict": v, "verdict_ar": va, "panel": crop}


def overlay_flags(img, flag, colour=(255, 0, 0)):
    out = img[..., :3].copy()
    from skimage import segmentation
    edge = segmentation.find_boundaries(flag, mode="outer")
    out[flag] = (0.6 * out[flag] + 0.4 * np.array(colour)).astype(np.uint8)
    out[edge] = colour
    return out


# ----------------------------------------------------------------------------- 2. duplicates


def dhash(img, size=16):
    g = transform.resize(color.rgb2gray(img[..., :3]) if img.ndim == 3 else img, (size, size + 1), anti_aliasing=True)
    return (g[:, 1:] > g[:, :-1]).ravel()


def _variants(img):
    for k in range(4):
        r = np.rot90(img, k)
        yield f"rot{90 * k}", r
        yield f"rot{90 * k}+flip", r[:, ::-1]


def _orb(img, n=600, max_side=640):
    g, s = _gray_small(img, max_side)
    orb = feature.ORB(n_keypoints=n, fast_threshold=0.05)
    try:
        orb.detect_and_extract(g)
    except (RuntimeError, IndexError, ValueError):
        return None
    if orb.descriptors is None or len(orb.keypoints) < 10:
        return None
    return orb.keypoints / s, orb.descriptors, s


def _orb_pair(a, b):
    if a is None or b is None:
        return 0, None
    m = feature.match_descriptors(a[1], b[1], cross_check=True, max_ratio=0.8)
    if len(m) < 8:
        return 0, None
    src, dst = a[0][m[:, 0]][:, ::-1], b[0][m[:, 1]][:, ::-1]
    try:
        model, inl = measure.ransac((src, dst), transform.SimilarityTransform, min_samples=3, residual_threshold=6,
                                    max_trials=300, rng=0)
    except Exception:
        return 0, None
    if inl is None:
        return 0, None
    return int(inl.sum()), (src[inl], dst[inl])


def find_duplicates(images: dict, hash_thresh=0.12, min_inliers=18, clones=True):
    """images: {name: RGB array}. Returns list of findings (dicts) sorted by strength."""
    names = list(images)
    hashes = {n: {k: dhash(v) for k, v in _variants(images[n])} for n in names}
    orbs = {n: _orb(images[n]) for n in names}
    orbs_flip = {n: _orb(images[n][:, ::-1]) for n in names}
    out = []
    for a, b in itertools.combinations(names, 2):
        ha = hashes[a]["rot0"]
        dist, how = min((float(np.mean(ha != hb)), k) for k, hb in hashes[b].items())
        if dist <= hash_thresh:
            out.append({"type": "whole image", "a": a, "b": b, "transform": how, "strength": round(1 - dist, 3),
                        "detail": f"Perceptual-hash distance {dist:.3f} ({how})"})
            continue
        n1, pts1 = _orb_pair(orbs[a], orbs[b])
        n2, pts2 = _orb_pair(orbs[a], orbs_flip[b])
        if max(n1, n2) >= min_inliers:
            flipped = n2 > n1
            pts = pts2 if flipped else pts1
            if flipped and pts is not None:
                w = images[b].shape[1]
                pts = (pts[0], np.c_[w - 1 - pts[1][:, 0], pts[1][:, 1]])
            out.append({"type": "partial overlap", "a": a, "b": b, "transform": "mirrored" if flipped else "rigid/scaled",
                        "strength": max(n1, n2), "detail": f"{max(n1, n2)} geometrically consistent keypoint matches",
                        "points": pts})
    if clones:
        for n in names:
            c = clone_check(images[n])
            if c:
                out.append({"type": "within-image clone", "a": n, "b": n, "transform": "copy-move", "strength": c["n"],
                            "detail": f"{c['n']} keypoints repeated at offset {c['offset']} px", "points": c["points"]})
    return sorted(out, key=lambda d: (d["type"] != "whole image", -float(d["strength"])))


def clone_check(img, min_blocks=25, min_shift=24, block=16, step=2, q=4.0, min_std=6.0):
    """Copy-move detection by block matching: every 16×16 block (step 2 px) is described by its 4×4 grid of sub-block
    means (quantised); identical descriptors that recur many times with one common displacement mark a cloned region.
    Flat background blocks are ignored."""
    from scipy import ndimage as ndi
    g = (color.rgb2gray(img[..., :3]) * 255.0) if img.ndim == 3 else img.astype(float)
    f = max(1, int(math.ceil(max(g.shape) / 1400)))
    if f > 1:
        g = g[:g.shape[0] // f * f, :g.shape[1] // f * f].reshape(g.shape[0] // f, f, g.shape[1] // f, f).mean((1, 3))
    H, W = g.shape
    sb = block // 4
    m4 = ndi.uniform_filter(g, sb, mode="nearest")
    m16 = ndi.uniform_filter(g, block, mode="nearest"); s16 = ndi.uniform_filter(g * g, block, mode="nearest")
    ys = np.arange(0, H - block, step); xs = np.arange(0, W - block, step)
    Y, X = np.meshgrid(ys, xs, indexing="ij"); Y = Y.ravel(); X = X.ravel()
    off = sb // 2
    feats = np.stack([m4[Y + off + sb * i, X + off + sb * j] for i in range(4) for j in range(4)], 1)
    c = block // 2
    sd = np.sqrt(np.maximum(s16[Y + c, X + c] - m16[Y + c, X + c] ** 2, 0))
    keep = sd >= min_std
    Y, X, feats = Y[keep], X[keep], np.round(feats[keep] / q).astype(np.int32)
    if len(Y) < min_blocks * 2:
        return None
    _, inv, cnt = np.unique(feats, axis=0, return_inverse=True, return_counts=True)
    inv = inv.ravel()
    order = np.argsort(inv, kind="stable")
    starts = np.r_[0, np.cumsum(cnt)[:-1]]
    pairs = []
    for gi in np.nonzero((cnt >= 2) & (cnt <= 12))[0]:
        idx = order[starts[gi]:starts[gi] + cnt[gi]]
        for i, j in itertools.combinations(idx, 2):
            pairs.append((i, j))
    if not pairs:
        return None
    P = np.array(pairs)
    dy = Y[P[:, 1]] - Y[P[:, 0]]; dx = X[P[:, 1]] - X[P[:, 0]]
    sgn = np.where((dy < 0) | ((dy == 0) & (dx < 0)), -1, 1)
    dy, dx = dy * sgn, dx * sgn
    P = np.where(sgn[:, None] < 0, P[:, ::-1], P)
    far = np.hypot(dy, dx) >= min_shift
    if far.sum() < min_blocks:
        return None
    P, dy, dx = P[far], dy[far], dx[far]
    keys, kinv, kcnt = np.unique(np.c_[dy, dx], axis=0, return_inverse=True, return_counts=True)
    k = int(np.argmax(kcnt))
    if kcnt[k] < min_blocks:
        return None
    sel = kinv.ravel() == k
    src = np.c_[X[P[sel, 0]] + c, Y[P[sel, 0]] + c] * f
    dst = np.c_[X[P[sel, 1]] + c, Y[P[sel, 1]] + c] * f
    return {"n": int(kcnt[k]), "offset": (int(keys[k][1] * f), int(keys[k][0] * f)), "points": (src, dst)}


def match_figure(img_a, img_b, finding):
    """Side-by-side figure with match lines (matplotlib Figure)."""
    from matplotlib.figure import Figure
    same = finding["a"] == finding["b"]
    fig = Figure(figsize=(9, 4.5) if not same else (5.5, 5), dpi=110)
    if same:
        ax = fig.add_subplot(111); ax.imshow(img_a); ax.axis("off")
        p, q = finding["points"]
        for (x1, y1), (x2, y2) in zip(p, q):
            ax.plot([x1, x2], [y1, y2], "-", color="#FF3B30", lw=0.6, alpha=0.7)
        ax.set_title(f"{finding['a']}: {finding['detail']}", fontsize=9)
        return fig
    h = max(img_a.shape[0], img_b.shape[0])
    canvas = np.full((h, img_a.shape[1] + img_b.shape[1] + 10, 3), 255, np.uint8)
    canvas[:img_a.shape[0], :img_a.shape[1]] = img_a[..., :3]
    canvas[:img_b.shape[0], img_a.shape[1] + 10:] = img_b[..., :3]
    ax = fig.add_subplot(111); ax.imshow(canvas); ax.axis("off")
    if finding.get("points") is not None:
        p, q = finding["points"]
        off = img_a.shape[1] + 10
        for (x1, y1), (x2, y2) in list(zip(p, q))[:120]:
            ax.plot([x1, x2 + off], [y1, y2], "-", color="#FF3B30", lw=0.5, alpha=0.6)
    ax.set_title(f"{finding['a']}  ↔  {finding['b']}: {finding['type']} ({finding['detail']})", fontsize=9)
    fig.tight_layout()
    return fig


METHOD_TEXT = ("Figures were screened for duplicated or re-used image regions with MedStatix Pro (perceptual hashing over "
               "all rotations and reflections, ORB keypoint matching with RANSAC, and within-image copy-move detection); "
               "every flagged pair was inspected visually.")
