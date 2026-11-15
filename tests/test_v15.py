"""v1.5: SPSS/Prism files, SPSS tables, Bayes, G*Power, charts, assumption fallback, R bridge, image forensics,
assistant, AI training, updater."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import matplotlib  # noqa: E402
matplotlib.use("Agg")

from medstatix.analyses import run, REGISTRY  # noqa: E402
from medstatix.core.data import make_sample_datasets, load_file, save_file  # noqa: E402
from medstatix.imaging import core as IC  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "medstatix", "resources", "sample_images")
TRIAL = make_sample_datasets()["Clinical trial (simulated)"]


def _tox():
    rng = np.random.default_rng(3)
    g = np.repeat(["Control", "Toxin", "Toxin + Drug"], 8)
    return pd.DataFrame({"Group": pd.Categorical(g, ["Control", "Toxin", "Toxin + Drug"]),
                         "MDA": np.r_[rng.normal(2, .3, 8), rng.normal(5, .5, 8), rng.normal(3, .4, 8)],
                         "GSH": np.r_[rng.normal(9, 1, 8), rng.normal(4, .8, 8), rng.normal(7, 1, 8)],
                         "ALT": np.r_[rng.normal(40, 5, 8), rng.normal(110, 15, 8), rng.normal(60, 8, 8)],
                         "AST": np.r_[rng.normal(90, 9, 8), rng.normal(200, 25, 8), rng.normal(120, 15, 8)]})


def test_new_analyses_registered():
    for aid in ("bayes_t", "bayes_corr", "bayes_anova", "gpower", "heatmap", "volcano", "radar", "forest_custom", "km_chart"):
        assert aid in REGISTRY, aid


def test_pzfx_and_sav_round_trip(tmp_path):
    df = _tox()
    p = str(tmp_path / "tox.pzfx")
    save_file(df, p)
    back, _ = load_file(p)
    assert set(back["Group"].astype(str)) == {"Control", "Toxin", "Toxin + Drug"} and len(back) == 24
    from medstatix.core import pzfx
    tables = pzfx.list_tables(p)
    assert len(tables) == 4
    gsh, title = pzfx.read_pzfx(p, "GSH")
    assert np.allclose(np.sort(gsh["GSH"].to_numpy()), np.sort(df["GSH"].to_numpy()))
    pytest.importorskip("pyreadstat")
    s = str(tmp_path / "tox.sav")
    save_file(df, s)
    b2, labels = load_file(s)
    assert len(b2) == 24 and "MDA" in b2.columns


def test_spss_table_style():
    from medstatix.core.settings import SETTINGS
    from medstatix.core.result import Result, _df_to_html, _fmt_p_spss
    old = SETTINGS.table_style
    try:
        SETTINGS.table_style = "SPSS"
        assert _fmt_p_spss(0.0004) == "<.001" and _fmt_p_spss(0.045) == ".045"
        assert "spss" in _df_to_html(pd.DataFrame({"t": [2.5]}), "cap", "")
        f = Result.format_df(pd.DataFrame({"t": [2.5], "p": [0.0004]}), ("p",))
        assert f["p"].iloc[0] == "<.001"
    finally:
        SETTINGS.table_style = old


def test_bayes_and_gpower_reference_values():
    from medstatix.analyses.bayes import jzs_bf_t
    from medstatix.analyses.gpower import solve_n, FAMILIES as F
    assert abs(jzs_bf_t(-4.0621, 10, 9) - 17.2589) < 0.01
    assert solve_n(F[0], .5, .05, .8, 2, 1, 2)[0] == 128
    assert solve_n(F[2], .25, .05, .8, 4, 1, 2)[0] == 180
    assert run("bayes_t", _tox()[lambda d: d.Group != "Toxin + Drug"], outcome="MDA", group="Group").tables


def test_charts_run():
    df = _tox()
    for aid, kw in [("heatmap", dict(variables=["MDA", "GSH", "ALT", "AST"], group="Group")),
                    ("radar", dict(variables=["MDA", "GSH", "ALT", "AST"], group="Group")),
                    ("volcano", dict(variables=["MDA", "GSH", "ALT", "AST"], group="Group", reference="Control"))]:
        r = run(aid, df, **kw)
        assert any(b.kind == "figure" for b in r.blocks), aid


def test_validation_report(tmp_path):
    pytest.importorskip("docx")
    from medstatix.report import validation as V
    rows = V.run_checks()
    assert len(rows) >= 50 and all(r[4] == "PASS" for r in rows)
    npass, n = V.export_docx(str(tmp_path / "v.docx"), rows)
    assert npass == n and os.path.getsize(tmp_path / "v.docx") > 10000


def test_assumption_fallback():
    from medstatix.core.fallback import run_with_fallback, suggest
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"y": np.r_[rng.lognormal(0, 1.2, 25), rng.lognormal(.8, 1.2, 25)], "g": ["A"] * 25 + ["B"] * 25})
    out = run_with_fallback("ttest_ind", df, {"outcome": "y", "group": "g"}, run)
    assert len(out) == 2 and "Mann" in out[1].title
    assert any(b.kind == "warning" for b in out[0].blocks)
    normal = pd.DataFrame({"y": rng.normal(0, 1, 40), "g": ["A"] * 20 + ["B"] * 20})
    assert suggest("ttest_ind", normal, {"outcome": "y", "group": "g"}) is None


def test_r_bridge():
    from medstatix.core import rbridge
    code = rbridge.r_code("anova1", {"outcome": "MDA", "group": "Group"})
    assert "aov(" in code and "TukeyHSD" in code
    if not rbridge.find_rscript():
        pytest.skip("R not installed")
    ok, out = rbridge.run_r(code, _tox())
    assert ok and "Pr(>F)" in out


def test_duplicate_and_clone_detection():
    from medstatix.imaging import forensics as FO
    a = IC.load_image(os.path.join(SAMPLES, "HE_breast_carcinoma_1.png"))
    b = IC.load_image(os.path.join(SAMPLES, "HE_breast_carcinoma_2.png"))
    c = IC.load_image(os.path.join(SAMPLES, "IHC_DAB_colon.png"))
    cl = b.copy(); cl[612:712, 312:412] = cl[200:300, 600:700]
    found = FO.find_duplicates({"a": a, "a_mirror": np.rot90(a)[:, ::-1].copy(), "c": c, "clone": cl})
    kinds = {(f["type"], f["a"], f["b"]) for f in found}
    assert ("whole image", "a", "a_mirror") in kinds
    assert any(t == "within-image clone" and x == "clone" for t, x, _ in kinds)
    assert not any("c" in (x, y) and t != "within-image clone" for t, x, y in kinds)
    for img in (a, b, c):
        assert FO.clone_check(img) is None


def test_photopea_round_trip_check():
    from medstatix.imaging import forensics as FO
    from skimage import transform
    a = IC.load_image(os.path.join(SAMPLES, "HE_breast_carcinoma_1.png"))
    fig = np.full((1000, 1800, 3), 255, np.uint8)
    sm = (transform.rescale(a, 0.8, channel_axis=2, anti_aliasing=True) * 255).round().astype(np.uint8)
    fig[50:50 + sm.shape[0], 30:30 + sm.shape[1]] = sm
    fig[100:130, 80:160] = 0                              # a text label
    r = FO.external_edit_check(a, fig)
    assert r["found"] and r["tissue_regions"] == 0 and r["marks"] >= 1
    b = a.copy(); b[300:420, 300:420] = a[600:720, 600:720]   # cloned tissue
    assert FO.external_edit_check(a, b)["tissue_regions"] >= 1
    assert FO.external_edit_check(a, np.clip(a * 1.1, 0, 255).astype(np.uint8))["clean"]


def test_assistant_parsing():
    from medstatix.core.assistant import parse, match_columns
    df = _tox()
    p = parse("قارن MDA و gsh بين المجموعات", df)
    assert p["actions"] == [("smart", None, {"outcomes": ["MDA", "GSH"], "factor": "Group"})]
    p = parse("الارتباط بين ALT و AST", df)
    assert p["actions"][0][1] == "correlation" and p["actions"][0][2]["method"] == "Pearson"
    assert parse("ارسم خريطة حرارية", df)["actions"][0][1] == "heatmap"
    assert parse("حجم العينة", df)["actions"][0][1] == "gpower"
    assert match_columns("compare MDA levels", list(df.columns)) == ["MDA"]


def test_ai_training_store(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from medstatix.imaging import training as TR, cellclass as CC
    W, init = TR._base()
    mean, sc = np.array(W["mean"]), np.array(W["scale"])
    rng = np.random.default_rng(0)
    X = (rng.normal(size=(240, len(CC.FEATURES))) * sc * 0.8 + mean).astype(np.float32)
    y = TR._predict(init, X, mean, sc)
    for i in range(3):
        TR.add_examples(X[i * 80:(i + 1) * 80], y[i * 80:(i + 1) * 80], f"img{i}")
    assert TR.summary()["nuclei"] == 240 and TR.summary()["images"] == 3
    r = TR.train(epochs=60)
    assert "leave-one-image-out" in r["cv"] and r["macro_f1_finetuned"] > 0.5
    TR.clear_examples(); CC.reset()
    assert TR.summary()["nuclei"] == 0 and CC.active_source() == "built-in"


def test_updater_version_logic():
    from medstatix.core import updater as U
    rel = [{"tag_name": "medstatix-v1.4.0", "assets": [{"name": "MedStatixPro-Setup-1.4.0.exe", "browser_download_url": "u14"}]},
           {"tag_name": "medstatix-v1.10.0", "assets": [{"name": "MedStatixPro-Setup-1.10.0.exe", "browser_download_url": "u110"}]},
           {"tag_name": "other-v9.0", "assets": []},
           {"tag_name": "medstatix-v2.0.0", "draft": True, "assets": []}]
    best = U.pick_latest(rel)
    assert best["version"] == "1.10.0" and best["url"] == "u110"
    assert U.is_newer("1.10.0", "1.5.0") and not U.is_newer("1.5.0", "1.5.0")
