"""Tissue structures that change how nuclei must be read.

Glomeruli: the glomerular tuft is a tight cluster of dark nuclei (mesangial, endothelial, podocytes) inside Bowman's
space. A cell-level classifier sees exactly what an inflammatory infiltrate looks like, so in kidney sections the
glomeruli are found first and their nuclei are never proposed as inflammatory cells. A glomerulus is recognised as a
round, densely nucleated region that is surrounded for a large part of its outline by the clear rim of Bowman's space.
The function also returns the tuft and Bowman's-space areas, which are measurements in their own right (glomerular
atrophy / widened Bowman's space)."""
from __future__ import annotations

import math

import numpy as np
from scipy import ndimage as ndi
from skimage import filters, measure, morphology


def glomeruli(img, cells, px_um, min_diam_um=50, max_diam_um=260):
    """Return list of dicts (y, x, tuft_area_um2, bowman_area_um2, ring_fraction, contour) and a boolean mask.

    Bowman's space is a clear crescent or ring wrapped around the tuft. Clear components are examined: a component
    whose convex hull encloses a large, round, densely nucleated and non-clear region that it surrounds on most sides
    is a glomerulus (tubular lumens are compact clear blobs with the epithelium outside them)."""
    H, W = img.shape[:2]
    if not px_um or px_um > 0.7:        # at 10× the Bowman's space is only a few pixels wide: not reliable
        return [], np.zeros((H, W), bool)
    f = max(1, int(round(1.0 / px_um)))          # work at ~1 µm per pixel
    h, w = H // f, W // f
    rgb = img[:h * f, :w * f, :3].astype(np.float32).reshape(h, f, w, f, 3).mean((1, 3)) / 255.0
    um = px_um * f
    gray = rgb.mean(2); sat = rgb.max(2) - rgb.min(2)
    bright = (gray > 0.86) & (sat < 0.18)                       # clear space: Bowman's space, lumens, background
    fat = morphology.opening(bright, morphology.disk(max(2, int(round(7.0 / um))))).astype(bool)
    labs = []
    for src in (bright, bright & ~fat):     # as is, and with wide clear areas removed (separates touching capsules)
        labs.append(measure.label(ndi.binary_dilation(src, morphology.disk(max(1, int(round(1.0 / um)))))))
    amin = math.pi * (min_diam_um / 2) ** 2 / (um * um); amax = math.pi * (max_diam_um / 2) ** 2 / (um * um)
    pts = np.array([[c["y"] / f, c["x"] / f] for c in cells]) if cells else np.zeros((0, 2))
    out = []
    mask = np.zeros((h, w), bool)
    regions = [r for lab in labs for r in measure.regionprops(lab)]
    for r in regions:
        if r.area < 0.05 * amin:
            continue
        hull = r.image_convex
        ha = hull.sum()
        if not (amin <= ha <= amax * 1.6):
            continue
        y0, x0 = r.bbox[:2]
        if y0 == 0 or x0 == 0 or r.bbox[2] >= h or r.bbox[3] >= w:
            continue                                 # cut by the image edge: the ring cannot be judged
        inner = hull & ~r.image
        if inner.sum() < 0.35 * ha:
            continue
        iy, ix = np.nonzero(inner)
        cy, cx = iy.mean(), ix.mean()
        by, bx = np.nonzero(r.image)
        cover = np.unique(((np.arctan2(by - cy, bx - cx) + np.pi) / (2 * np.pi) * 36).astype(int) % 36).size / 36
        if cover < 0.7:
            continue
        reg = np.zeros((h, w), bool)
        reg[y0:y0 + hull.shape[0], x0:x0 + hull.shape[1]] = inner
        reg = morphology.opening(reg, morphology.disk(max(1, int(round(3 / um))))).astype(bool)
        if reg.sum() < 0.5 * amin:
            continue
        lr = measure.label(reg)
        big = max(measure.regionprops(lr), key=lambda q: q.area)
        reg = lr == big.label
        if (reg & mask).sum() > 0.3 * reg.sum():
            continue
        if big.area < 0.5 * amin or big.eccentricity > 0.9 or big.solidity < 0.8 or float(bright[reg].mean()) > 0.3:
            continue
        if len(pts):
            inside = reg[np.clip(pts[:, 0].astype(int), 0, h - 1), np.clip(pts[:, 1].astype(int), 0, w - 1)].sum()
            if inside / (reg.sum() * um * um) * 1000 < 4:      # a tuft is densely nucleated (≥ 4 nuclei / 1000 µm²)
                continue
        cs = measure.find_contours(np.pad(reg, 1).astype(float), 0.5)
        cont = (max(cs, key=len) - 1) * f if cs else None
        out.append({"y": big.centroid[0] * f, "x": big.centroid[1] * f, "tuft_area_um2": float(reg.sum() * um * um),
                    "bowman_area_um2": float(r.image.sum() * um * um), "ring_fraction": round(cover, 2), "contour": cont})
        mask |= ndi.binary_dilation(reg, morphology.disk(max(1, int(round(3 / um)))))
    full = np.zeros((H, W), bool)
    full[:h * f, :w * f] = np.repeat(np.repeat(mask, f, 0), f, 1)
    return out, full
