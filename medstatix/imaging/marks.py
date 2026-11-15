"""Annotation marks already drawn on a photomicrograph: arrows, arrowheads, stars, letters and the scale-bar box.

Published figures and figures prepared for a thesis usually carry these marks. They must be ignored by every
measurement (a black arrowhead looks like a very dark nucleus to a detector), and the scale bar gives the image
calibration (µm per pixel) for free. ``find_marks`` returns a mask of the marks, the arrow tips (where each arrow
points) and the scale bar (length in pixels and, when the digits can be read, its length in µm)."""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi
from skimage import measure, morphology

COMMON_UM = (5, 10, 20, 25, 50, 100, 200, 250, 500, 1000)


def _dark(img):
    return img[..., :3].max(2) < 75


def _pure_white(img):
    return img[..., :3].min(2) >= 250


def _scale_box(img):
    """The white rectangle holding the scale bar and its label, near a corner."""
    H, W = img.shape[:2]
    wh = _pure_white(img)
    lab = measure.label(ndi.binary_fill_holes(wh | _dark(img)) & ~_border_tissue(img))
    best = None
    for r in measure.regionprops(lab):
        y0, x0, y1, x1 = r.bbox
        h, w = y1 - y0, x1 - x0
        if not (0.003 * H * W <= r.area <= 0.08 * H * W) or r.extent < 0.9 or w < 1.3 * h:
            continue
        near = min(y0, H - y1) <= 0.08 * H and min(x0, W - x1) <= 0.08 * W
        inner = img[y0 + 2:y1 - 2, x0 + 2:x1 - 2]
        if not near or inner.size == 0:
            continue
        frac_white = _pure_white(inner).mean(); frac_dark = _dark(inner).mean()
        if frac_white > 0.55 and frac_dark > 0.04:
            if best is None or r.area > best.area:
                best = r
    return best


def _border_tissue(img):
    # never used to exclude anything: placeholder that keeps the label image well defined
    return np.zeros(img.shape[:2], bool)


def _read_digits(glyphs):
    """Very small digit reader for scale-bar labels (0, 1, 2, 5 cover 5–1000 µm)."""
    out = ""
    for g in glyphs:
        h, w = g.shape
        holes = measure.label(~np.pad(g, 1), connectivity=1).max() - 1
        if holes >= 2:
            out += "8"; continue
        if holes == 1:
            out += "0" if w / h > 0.45 else "0"; continue
        if w / h < 0.42:
            out += "1"; continue
        band = g[int(0.15 * h):int(0.4 * h) + 1, : max(1, w // 3)]
        out += "5" if band.any(1).mean() >= 0.6 else "2"     # '5' has a vertical stroke at the upper left
    return out


def scale_bar(img):
    """Return dict(px, um, box) or None. `um` is None when the label cannot be read."""
    box = _scale_box(img)
    if box is None:
        return None
    y0, x0, y1, x1 = box.bbox
    inner = _dark(img[y0:y1, x0:x1])
    lab = measure.label(inner)
    regs = measure.regionprops(lab)
    bars = [r for r in regs if (r.bbox[3] - r.bbox[1]) >= 4 * (r.bbox[2] - r.bbox[0]) and (r.bbox[3] - r.bbox[1]) >= 15]
    if not bars:
        return None
    bar = max(bars, key=lambda r: r.bbox[3] - r.bbox[1])
    px = bar.bbox[3] - bar.bbox[1]
    # label glyphs: below the bar, ordered left to right; digits come before "µm"
    gl = [r for r in regs if r.label != bar.label and r.bbox[0] >= bar.bbox[2] - 2 and r.area >= 8]
    gl.sort(key=lambda r: r.bbox[1])
    um = None
    if gl:
        hmax = max(r.bbox[2] - r.bbox[0] for r in gl)
        gl = [r for r in gl if r.bbox[2] - r.bbox[0] >= 0.5 * hmax]
        # 'µ' descends below the baseline and 'm' is wider than tall: digits are the leading tall, narrow glyphs
        digits = []
        for r in gl:
            h, w = r.bbox[2] - r.bbox[0], r.bbox[3] - r.bbox[1]
            aligned = not digits or abs(r.bbox[0] - digits[0].bbox[0]) <= 0.15 * hmax
            if h >= 0.8 * hmax and w <= 0.85 * h and aligned and (not digits or r.bbox[1] - digits[-1].bbox[3] <= 0.6 * hmax):
                digits.append(r)
            elif digits:
                break
        txt = _read_digits([r.image for r in digits])
        try:
            v = int(txt)
            um = v if v in COMMON_UM else None
        except ValueError:
            um = None
    return {"px": int(px), "um": um, "box": (y0, x0, y1, x1),
            "um_per_px": (um / px) if um else None}


def find_marks(img, dilate=3):
    """Mask of drawn marks (black or white arrows, arrowheads, stars, text, scale-bar box) + arrow tips + scale bar."""
    H, W = img.shape[:2]
    dark = _dark(img)
    lab = measure.label(dark)
    mask = np.zeros((H, W), bool)
    tips = []
    for r in measure.regionprops(lab):
        if r.area < 25:
            continue
        mask[lab == r.label] = True
        y0, x0, y1, x1 = r.bbox
        long_ = max(y1 - y0, x1 - x0)
        if long_ < 12:
            continue
        tip = _arrow_tip(r)
        if tip is not None:
            tips.append({"y": tip[0], "x": tip[1], "kind": tip[2], "dy": tip[3], "dx": tip[4], "colour": "black"})
    # white marks with a dark or coloured outline (open arrows, stars): pure white blobs fully enclosed by an outline
    wh = _pure_white(img)
    wl = measure.label(wh)
    for r in measure.regionprops(wl):
        if not (30 <= r.area <= 0.01 * H * W) or r.solidity < 0.5:
            continue
        ring = ndi.binary_dilation(wl == r.label, morphology.disk(2)) & ~(wl == r.label)
        rv = img[ring][:, :3].astype(int)
        outline = (rv.max(1) < 120) | ((rv[:, 0] > 150) & (rv[:, 1] < 90))
        if outline.mean() > 0.5:
            mask |= ndi.binary_dilation(wl == r.label, morphology.disk(2))
            t = _arrow_tip(r)
            if t is not None:
                tips.append({"y": t[0], "x": t[1], "kind": t[2], "dy": t[3], "dx": t[4], "colour": "white"})
    sb = scale_bar(img)
    if sb:
        y0, x0, y1, x1 = sb["box"]
        mask[max(0, y0 - 2):y1 + 2, max(0, x0 - 2):x1 + 2] = True
        tips = [t for t in tips if not (y0 - 3 <= t["y"] <= y1 + 3 and x0 - 3 <= t["x"] <= x1 + 3)]
    if dilate:
        mask = ndi.binary_dilation(mask, morphology.disk(dilate))
    return {"mask": mask, "tips": tips, "scale_bar": sb}


def _arrow_tip(r):
    """Tip of an arrow (line + head) or arrowhead (filled triangle); None for text and stars."""
    img = np.pad(r.image, 2)
    oy, ox = r.bbox[0] - 2, r.bbox[1] - 2
    ys, xs = np.nonzero(img)
    pts = np.c_[ys, xs].astype(float)
    c = pts.mean(0)
    dt = ndi.distance_transform_edt(img)
    hy, hx = np.unravel_index(np.argmax(dt), dt.shape)
    thick = dt.max()
    elong = r.major_axis_length / max(r.minor_axis_length, 1)
    if r.solidity > 0.6 and 1.0 <= elong <= 2.6 and r.area >= 60:          # arrowhead (filled or notched triangle)
        from scipy.spatial import ConvexHull
        try:
            hv = pts[ConvexHull(pts).vertices]
        except Exception:
            return None
        D = np.hypot(*(hv[:, None] - hv[None]).transpose(2, 0, 1))
        i, j = np.unravel_index(np.argmax(D), D.shape)
        A, B = hv[i], hv[j]
        ab = (B - A) / max(D[i, j], 1e-6)
        perp = np.abs((hv - A) @ np.array([-ab[1], ab[0]]))
        C = hv[int(np.argmax(perp))]
        tri = [A, B, C]
        sides = [np.hypot(*(tri[(k + 1) % 3] - tri[(k + 2) % 3])) for k in range(3)]   # side opposite each vertex
        t = tri[int(np.argmin(sides))]                                     # the tip faces the shortest side (the base)
        base_mid = (tri[(int(np.argmin(sides)) + 1) % 3] + tri[(int(np.argmin(sides)) + 2) % 3]) / 2
        v = (t - base_mid) / max(np.hypot(*(t - base_mid)), 1e-6)
        return (oy + t[0], ox + t[1], "arrowhead", float(v[0]), float(v[1]))
    if elong >= 4 and thick >= 1.5:                                          # arrow: shaft + head
        v = np.array([hy, hx]) - c
        if np.hypot(*v) < 2:
            return None
        v /= np.hypot(*v)
        proj = (pts - c) @ v
        k = int(np.argmax(proj))
        return (oy + pts[k, 0], ox + pts[k, 1], "arrow", float(v[0]), float(v[1]))
    return None
