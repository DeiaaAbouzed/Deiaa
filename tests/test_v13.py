"""v1.3: one-click publication-ready histology, eyepiece crop, measurement image, projects, manuscript and reviewer
report, animal-study helpers (randomisation, Mead, Grubbs, ROUT, templates), journal presets."""
import glob
import os
import sys
import tempfile

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from medstatix.imaging import core as IC  # noqa: E402
from medstatix.core import animal as AN  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "medstatix", "resources", "sample_images")
IMGS = sorted(glob.glob(os.path.join(SAMPLES, "*.png")))


def degrade(img):
    H, W = img.shape[:2]; y, x = np.mgrid[:H, :W]
    r = np.hypot((x - W / 2) / (W / 2), (y - H / 2) / (H / 2)) / 1.414
    f = img.astype(float) * (1 - 0.35 * r ** 2)[..., None] * np.array([1.0, 0.93, 0.8])
    f = 60 + f * 0.6  # low contrast, grey background
    return np.clip(f, 0, 255).astype(np.uint8)


@pytest.mark.parametrize("path", IMGS[:2])
def test_publication_ready_improves_and_passes_integrity(path):
    bad = degrade(IC.load_image(path))
    out, done, rep, steps, info = IC.publication_ready(bad)
    assert rep["passed"]
    assert out.shape[2] == 3 and out.dtype == np.uint8
    assert IC.image_qc(out)["score"] > IC.image_qc(bad)["score"]
    bo, bb = IC.background_colour(out.astype(float) / 255)[0], IC.background_colour(bad.astype(float) / 255)[0]
    if bo is not None and bb is not None:
        assert np.mean(bo) > np.mean(bb)
    assert all(s["op"] in IC.OPS for s in done)


def test_eyepiece_crop_found_on_synthetic_phone_photo():
    img = np.zeros((600, 800, 3), np.uint8)
    y, x = np.mgrid[:600, :800]
    img[(x - 400) ** 2 + (y - 300) ** 2 < 250 ** 2] = (225, 215, 225)
    box = IC.eyepiece_crop_box(img)
    assert box is not None
    y0, y1, x0, x1 = box
    assert 150 < x0 < 400 < x1 < 650 and 50 < y0 < 300 < y1 < 550


def test_measurement_image_excludes_cosmetic_steps():
    img = IC.load_image(IMGS[0])
    steps = [{"op": "gamma", "params": {"gamma": 1.3}}, {"op": "saturation", "params": {"factor": 1.3}}]
    assert np.array_equal(IC.measurement_image(img, steps), img)


def test_project_roundtrip():
    from medstatix.core.project import save_project, load_project
    df = pd.DataFrame({"g": ["a", "b"], "y": [1.5, 2.5]})
    p = os.path.join(tempfile.mkdtemp(), "t.msx")
    save_project(p, {"dataset_name": "d", "df": df, "entries": [], "settings": {}})
    st = load_project(p)
    assert st["dataset_name"] == "d" and st["df"]["y"].tolist() == [1.5, 2.5]


def test_manuscript_and_reviewer_report():
    from medstatix.analyses import run
    from medstatix.report.manuscript import build_manuscript, build_reviewer_report
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"Group": ["C"] * 8 + ["T"] * 8 + ["D"] * 8,
                       "MDA": np.r_[rng.normal(2, .3, 8), rng.normal(4, .3, 8), rng.normal(3, .3, 8)]})
    from medstatix.core.advisor import auto_analyze
    res, _ = auto_analyze(df, "MDA", "Group")
    d = tempfile.mkdtemp()
    build_manuscript([res], os.path.join(d, "m.docx"), journal="Elsevier", lang="both")
    build_reviewer_report([res], os.path.join(d, "r.docx"))
    import docx
    txt = "\n".join(p.text for p in docx.Document(os.path.join(d, "m.docx")).paragraphs)
    assert "Statistical analysis" in txt and "Figure 1" in txt
    assert os.path.getsize(os.path.join(d, "r.docx")) > 5000


def test_randomize_balanced_and_reproducible():
    a = AN.randomize({"C": 6, "T": 6, "D": 6}, seed=7)
    b = AN.randomize({"C": 6, "T": 6, "D": 6}, seed=7)
    assert a.equals(b) and a["Group"].value_counts().tolist() == [6, 6, 6]
    w = list(np.random.default_rng(0).normal(200, 20, 18))
    s = AN.randomize({"C": 6, "T": 6, "D": 6}, seed=1, weights=w)
    means = s.groupby("Group")["Body weight"].mean()
    assert means.max() - means.min() < 12  # stratified: similar mean weights


def test_mead_and_power():
    lo, hi = AN.mead(5)
    assert (lo, hi) == (3, 5)  # E between 10 and 20 with 5 groups
    assert AN.n_for_power(1.0, 2) == 17


def test_grubbs_and_rout_find_the_obvious_outlier():
    x = [10.1, 9.8, 10.3, 9.9, 10.0, 10.2, 9.7, 25.0]
    g = AN.grubbs(x)
    assert len(g) == 1 and g[0][1] == 25.0
    r = AN.rout(x)
    assert [v for _, v, _, _ in r] == [25.0]
    assert AN.rout([10.1, 9.8, 10.3, 9.9, 10.0, 10.2, 9.7, 10.4]) == []


def test_templates_and_arrive():
    df = AN.make_template("liver", ["C", "T"], 6)
    assert df.shape == (12, 2 + 5) and df["Animal"].is_unique
    assert len(AN.ARRIVE) == 21


def test_journal_preset_sets_figure_specs():
    from medstatix.report.journals import apply_journal, JOURNALS

    class S: pass
    s = S()
    for k in JOURNALS:
        apply_journal(k, s, "double")
        assert s.fig_width_mm == JOURNALS[k]["widths"]["double"] and s.export_dpi >= 500
