"""v1.2: image QC + auto-correction, flat-field/sharpen integrity, Prism-style figures, recommendations, export formats."""
import glob
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from medstatix.imaging import core as IC  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "medstatix", "resources", "sample_images")
IMGS = sorted(glob.glob(os.path.join(SAMPLES, "*.png")))


def vignette(img, k=0.45):
    H, W = img.shape[:2]; y, x = np.mgrid[:H, :W]
    r = np.hypot((x - W / 2) / (W / 2), (y - H / 2) / (H / 2)) / 1.414
    return np.clip(img * (1 - k * r ** 2)[..., None], 0, 255).astype(np.uint8)


def cast(img):
    return np.clip(img * np.array([1.0, 0.92, 0.78]), 0, 255).astype(np.uint8)


def noisy(img):
    return np.clip(img + np.random.default_rng(0).normal(0, 9, img.shape), 0, 255).astype(np.uint8)


def clone(img):
    o = img.copy(); H, W = img.shape[:2]; s = min(H, W) // 10
    o[H // 2:H // 2 + s, W // 2:W // 2 + s] = img[H // 5:H // 5 + s, W // 5:W // 5 + s]
    return o


@pytest.mark.parametrize("path", IMGS)
def test_flatfield_and_sharpen_preserve_structure(path):
    img = IC.load_image(path)
    for src in (img, vignette(img)):
        assert IC.pipeline_integrity(src, [{"op": "flatfield", "params": {"strength": 1}}])["passed"]
    assert IC.pipeline_integrity(img, [{"op": "sharpen", "params": {"amount": 0.5}}])["passed"]


@pytest.mark.parametrize("path", IMGS)
def test_clone_flagged_even_with_flatfield(path):
    img = IC.load_image(path)
    out, _ = IC.apply_pipeline(clone(img), [{"op": "flatfield", "params": {"strength": 1}}])
    assert not IC.integrity_report(img, out, smooth_field=True)["passed"]


@pytest.mark.parametrize("path", IMGS)
def test_qc_clean_image_needs_little(path):
    qc = IC.image_qc(IC.load_image(path))
    assert qc["score"] >= 90


@pytest.mark.parametrize("path", IMGS)
@pytest.mark.parametrize("defect,key", [(vignette, "illumination"), (cast, "cast"), (noisy, "noise")])
def test_qc_detects_and_auto_fix_improves(path, defect, key):
    bad = defect(IC.load_image(path))
    qc = IC.image_qc(bad)
    c = next(c for c in qc["checks"] if c["key"] == key)
    assert c["status"] in ("warn", "bad")
    out, done, rep, steps = IC.auto_enhance(bad, qc["steps"])
    assert rep["passed"]
    assert IC.image_qc(out)["score"] > qc["score"]


def test_guess_stain():
    assert IC.guess_stain(IC.load_image(os.path.join(SAMPLES, "IHC_DAB_colon.png"))) == "IHC"
    assert IC.guess_stain(IC.load_image(os.path.join(SAMPLES, "HE_breast_carcinoma_1.png"))) == "H&E"


@pytest.mark.parametrize("ext", ["tiff", "png", "jpg", "pdf", "svg", "eps"])
def test_image_export_formats(tmp_path, ext):
    img = IC.load_image(IMGS[0])[:200, :200]
    p = tmp_path / f"x.{ext}"
    IC.save_image(img, str(p), 600, 85)
    assert p.stat().st_size > 1000


def test_groupfig_stacking_and_render():
    from medstatix.plots import groupfig as G
    levels = G.stack_levels([(0, 1), (1, 2), (0, 2), (0, 3)])
    assert len(levels) == 4 and max(levels) >= 1
    rng = np.random.default_rng(1)
    groups = {f"G{i}": rng.normal(10 + i, 1, 8) for i in range(4)}
    from medstatix.plots.figures import group_plot
    pairs = [(a, b, 0.001 * (i + 1)) for i, (a, b) in enumerate([("G0", "G1"), ("G0", "G2"), ("G0", "G3")])]
    fig = group_plot(groups, "Value", comparisons=pairs)
    spec = fig._mx_spec
    for pt in G.PLOT_TYPES:
        s = spec.copy(); s.plot_type = pt
        G.render(s)
    s = spec.copy(); s.star_scheme = G.STAR_SCHEMES[1]; s.sig_style = "Stars + exact p"; s.sig_mode = G.SIG_MODES[1]
    G.render(s)
    assert G.auto_caption(spec, "en")


def test_recommendations():
    from medstatix.core.advisor import recommend
    rng = np.random.default_rng(2)
    df = pd.DataFrame({"Group": np.repeat(["Control", "Low", "High"], 8), "ALT": rng.normal(40, 5, 24), "AST": rng.normal(60, 6, 24)})
    recs = recommend(df)
    assert recs and len(recs) <= 8
