"""Rodent-tissue gate for the inflammatory-cell suggestions.

The nucleus-type network was trained on human colon (CoNSeP). On rat kidney and skeletal muscle it calls most
tubular, glomerular and muscle nuclei "inflammatory". This gate re-scores every nucleus with what an inflammatory
infiltrate looks like in rodent tissue: the network's own score, the number of other dark nuclei within 8, 15 and
25 µm (infiltrates are clusters), the nucleus size in µm² and its darkness relative to the other nuclei of the image.
The weights were fitted on the user's rat kidney and muscle photomicrographs (positives at the targets of the
pathologist's inflammation arrows, negatives in sections described as normal) and validated image by image
(leave-one-image-out); the validation is stored with the weights and shown in the report."""
from __future__ import annotations

import json
import math
import os

import numpy as np

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "models", "rodent_inflammation.json")
_M = None


def available():
    return os.path.exists(PATH)


def model():
    global _M
    if _M is None:
        with open(PATH, encoding="utf-8") as fh:
            _M = json.load(fh)
    return _M


def features(X, centroids_px, px_um, p_infl):
    """X: cell feature table (cellclass.FEATURES, measured at the 0.25 µm/px working scale)."""
    from scipy.spatial import cKDTree
    from .cellclass import FEATURES
    gray = X[:, FEATURES.index("gray_mean")]
    area = X[:, FEATURES.index("area")] * 0.0625                    # µm² (working scale 0.25 µm/px)
    dark = gray < np.percentile(gray, 30)
    pts = np.asarray(centroids_px, float) * px_um
    t = cKDTree(pts)
    cols = []
    for r in (8, 15, 25):
        nb = t.query_ball_point(pts, r)
        nd = np.array([dark[b].sum() - dark[i] for i, b in enumerate(nb)], float)
        cols.append(nd / (math.pi * r * r) * 1000)
    gz = (gray - np.median(gray)) / (np.percentile(gray, 75) - np.percentile(gray, 25) + 1e-6)
    p = np.clip(np.asarray(p_infl, float), 1e-4, 1 - 1e-4)
    return np.c_[np.log(p / (1 - p)), cols[0], cols[1], cols[2], np.log(np.maximum(area, 1e-3)), gz]


def score(X, centroids_px, px_um, p_infl, report_conf=0.65):
    """Gate probability, rescaled so that the validated operating point corresponds to `report_conf`
    (the reader's default minimum confidence)."""
    M = model()
    if len(X) < 3:
        return np.zeros(len(X))
    Z = (features(X, centroids_px, px_um, p_infl) - np.array(M["mean"])) / np.array(M["scale"])
    z = Z @ np.array(M["coef"]) + M["intercept"]
    t = M["threshold"]
    shift = math.log(t / (1 - t)) - math.log(report_conf / (1 - report_conf))
    return 1 / (1 + np.exp(-(z - shift)))
