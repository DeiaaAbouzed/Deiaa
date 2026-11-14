"""Validation of the Histology & IHC module on real public images.

Positive controls: every legitimate global operation must pass the integrity check.
Negative controls: cloned, painted-in, erased cells and local blur must all be flagged.
Quantification: synthetic ground truth for fibrosis; DAB reference values for IHC.
"""
import glob
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from medstatix.imaging import core as IC  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "medstatix", "resources", "sample_images")
HE = sorted(glob.glob(os.path.join(SAMPLES, "HE_*.png")))
IHC = os.path.join(SAMPLES, "IHC_DAB_colon.png")

LEGIT = [
    [{"op": "white_balance"}],
    [{"op": "auto_levels"}],
    [{"op": "levels", "params": {"brightness": 0.05, "contrast": 1.2}}],
    [{"op": "gamma", "params": {"gamma": 0.85}}],
    [{"op": "saturation", "params": {"factor": 1.2}}],
    [{"op": "reinhard"}],
    [{"op": "macenko"}],
    [{"op": "denoise", "params": {"strength": 0.4}}],
    [{"op": "white_balance"}, {"op": "levels", "params": {"brightness": 0, "contrast": 1.15}},
     {"op": "reinhard"}, {"op": "denoise", "params": {"strength": 0.3}}],
]


@pytest.mark.parametrize("path", HE)
@pytest.mark.parametrize("steps", LEGIT)
def test_global_operations_preserve_structure(path, steps):
    img = IC.load_image(path)
    out, log = IC.apply_pipeline(img, steps)
    rep = IC.integrity_report(img, out)
    assert rep["passed"], (os.path.basename(path), steps, rep)
    assert len(log) == len(steps)


def _tampered(img, kind, seed=0):
    rng = np.random.default_rng(seed)
    t = img.copy()
    H, W = img.shape[:2]
    y, x = rng.integers(100, H - 160, 2)
    if kind == "clone":
        t[y:y + 60, x:x + 60] = img[(y + 200) % (H - 60):(y + 200) % (H - 60) + 60, (x + 300) % (W - 60):(x + 300) % (W - 60) + 60]
    elif kind == "paint_cell":
        yy, xx = np.ogrid[:H, :W]
        t[(yy - y) ** 2 + (xx - x) ** 2 < 14 ** 2] = (60, 30, 110)
    elif kind == "erase":
        patch = t[y:y + 50, x:x + 50].astype(float)
        t[y:y + 50, x:x + 50] = np.median(img.reshape(-1, 3), axis=0) * 0 + patch.mean(axis=(0, 1))
    elif kind == "local_blur":
        from scipy import ndimage as ndi
        t[y:y + 120, x:x + 120] = ndi.gaussian_filter(img[y:y + 120, x:x + 120].astype(float), (4, 4, 0)).astype(np.uint8)
    return t


@pytest.mark.parametrize("path", HE)
@pytest.mark.parametrize("kind", ["clone", "paint_cell", "erase", "local_blur"])
def test_local_manipulation_is_flagged(path, kind):
    img = IC.load_image(path)
    rep = IC.integrity_report(img, _tampered(img, kind))
    assert not rep["passed"], (os.path.basename(path), kind, rep)


def test_fibrosis_ground_truth():
    img = np.full((200, 200, 3), 245, np.uint8)
    img[20:180, 20:180] = (225, 120, 140)        # pink tissue (cytoplasm)
    img[60:100, 40:160] = (60, 90, 190)          # blue collagen (Masson) = 40*120 px
    res, mask = IC.fibrosis_area(img, "Masson trichrome")
    assert res["Collagen area (px)"] == 40 * 120
    assert abs(res["Fibrosis / collagen area %"] - 100 * 4800 / (160 * 160)) < 0.01


def test_ihc_dab_reference():
    img = IC.load_image(IHC)
    res, masks, cells = IC.ihc_dab(img)
    assert 35 < res["DAB positive area %"] < 50
    assert 40 < res["H-score (pixel)"] < 55
    assert res["Positive nuclei %"] > 80
    he, _, _ = IC.ihc_dab(IC.load_image(HE[0]))   # H&E has no DAB
    assert he["DAB positive area %"] < 1


@pytest.mark.parametrize("path", HE)
def test_candidates_stable_under_global_ops(path):
    img = IC.load_image(path)
    base = len(IC.inflammatory_candidates(img))
    out, _ = IC.apply_pipeline(img, [{"op": "white_balance"}, {"op": "levels", "params": {"brightness": 0, "contrast": 1.1}}])
    assert base > 0
    assert abs(len(IC.inflammatory_candidates(out)) - base) <= max(3, 0.3 * base)


def test_methods_text_discloses_everything():
    img = IC.load_image(HE[0])
    _, log = IC.apply_pipeline(img, LEGIT[-1])
    txt = IC.EditLog("x.png", log).methods_text()
    for word in ("white balance", "Reinhard", "generative"):
        assert word.lower() in txt.lower()
