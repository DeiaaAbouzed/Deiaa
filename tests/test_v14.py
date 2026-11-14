"""v1.4: AI image reader (StarDist nuclei via ONNX, nucleus-type classifier, reader suggestions)."""
import glob
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from medstatix.imaging import core as IC, nuclei as NU, cellclass as CC, reader as RD  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "medstatix", "resources", "sample_images")
pytestmark = pytest.mark.skipif(not NU.available(), reason="onnxruntime not installed")


def test_stardist_onnx_reproduces_reference_count():
    # the reference StarDist implementation (TensorFlow) finds 252 nuclei in this image; ours must agree closely
    img = IC.load_image(os.path.join(SAMPLES, "HE_breast_carcinoma_1.png"))
    lab, nu, s = NU.detect(img, scale=1.0)
    assert abs(len(nu) - 252) <= 5 and lab.max() == len(nu)
    assert all(n["prob"] >= NU.PROB_THRESH for n in nu)


def test_classifier_outputs_and_reported_accuracy():
    W = json.load(open(CC.WEIGHTS))
    assert W["test_report"]["Inflammatory"]["f1-score"] > 0.7   # held-out CoNSeP test images
    X = np.random.default_rng(0).normal(size=(5, len(CC.FEATURES))).astype(np.float32)
    P = CC.predict_proba(X)
    assert P.shape == (5, 4) and np.allclose(P.sum(1), 1)


def test_reader_he_sample():
    img = IC.load_image(os.path.join(SAMPLES, "HE_breast_carcinoma_1.png"))
    r = RD.read_image(img, stain="H&E")
    assert r["summary"]["Nuclei detected"] > 150
    assert r["vacuoles"] == []                       # experimental detector is off by default
    assert all(c["p"] >= 0.65 for c in r["inflammatory"])
    assert "StarDist" in r["methods"]
    assert RD.describe(r, ar=True) and RD.describe(r)


def test_reader_ihc_grades_nuclei():
    img = IC.load_image(os.path.join(SAMPLES, "IHC_DAB_colon.png"))
    r = RD.read_image(img, stain="IHC")
    S = r["summary"]
    assert S["Nuclei detected"] > 30 and S["Positive nuclei %"] > 30
    assert 0 <= S["Cell H-score (0–300)"] <= 300
    t = r["dab_thresholds"]; assert t[0] < t[1] < t[2]


def test_low_magnification_is_upscaled():
    img = IC.load_image(os.path.join(SAMPLES, "HE_breast_carcinoma_1.png"))
    from skimage.transform import rescale
    small = (rescale(img[..., :3], 0.3, channel_axis=2, anti_aliasing=True) * 255).astype(np.uint8)
    lab, nu, s = NU.detect(small)
    assert s > 1.5 and len(nu) > 100
