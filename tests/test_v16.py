"""v1.6: scale-bar calibration, annotation-mark masking, rodent inflammatory gate, glomerulus finder, reader profiles."""
import os
import sys

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from medstatix.imaging import core as IC  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "medstatix", "resources", "sample_images")


def _tissue(h=600, w=800, seed=0):
    rng = np.random.default_rng(seed)
    img = np.empty((h, w, 3), np.uint8)
    img[...] = (225, 130, 215)
    img = np.clip(img + rng.normal(0, 6, img.shape), 0, 255).astype(np.uint8)
    return img


def _with_scale_bar(img, bar_px=120, label="50"):
    im = Image.fromarray(img); d = ImageDraw.Draw(im)
    H, W = img.shape[:2]
    x1, y1 = W - 10, H - 10
    x0, y0 = x1 - bar_px - 30, y1 - 60
    d.rectangle([x0, y0, x1, y1], fill=(255, 255, 255))
    d.rectangle([x0 + 15, y0 + 10, x0 + 15 + bar_px - 1, y0 + 16], fill=(0, 0, 0))
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    d.text((x0 + 30, y0 + 20), label + " µm", fill=(0, 0, 0), font=font)
    return np.array(im)


def test_scale_bar_length_and_mask():
    from medstatix.imaging import marks as MK
    img = _with_scale_bar(_tissue(), 120)
    sb = MK.scale_bar(img)
    assert sb is not None and abs(sb["px"] - 120) <= 2
    if sb["um"] is not None:                       # digits read only when a TrueType font was available
        assert sb["um"] == 50 and abs(sb["um_per_px"] - 50 / 120) < 0.01
    m = MK.find_marks(img)["mask"]
    assert m[-30, -60] and not m[100, 100]


def test_arrowhead_tip_found():
    from medstatix.imaging import marks as MK
    img = _tissue()
    im = Image.fromarray(img); d = ImageDraw.Draw(im)
    d.polygon([(300, 300), (340, 280), (340, 320)], fill=(0, 0, 0))      # arrowhead pointing left, tip at (300, 300)
    tips = MK.find_marks(np.array(im))["tips"]
    assert tips and min(abs(t["x"] - 300) + abs(t["y"] - 300) for t in tips) < 8
    t = min(tips, key=lambda t: abs(t["x"] - 300))
    assert t["dx"] < -0.8


def test_scale_for_working_resolution():
    from medstatix.imaging import nuclei as NU
    assert NU.scale_for(0.25, (1000, 1000)) == 1.0
    assert abs(NU.scale_for(0.5, (1000, 1000)) - 2.0) < 1e-9
    assert NU.scale_for(1.0, (4000, 4000)) == 1.0            # capped by the pixel budget
    assert NU.scale_for(0.05, (500, 500)) == 0.5


def test_tissue_gate_scores():
    from medstatix.imaging import tissue_gate as TG, cellclass as CC
    if not TG.available():
        pytest.skip("rodent model missing")
    rng = np.random.default_rng(0)
    n = 200
    X = rng.normal(size=(n, len(CC.FEATURES))).astype(np.float32)
    cen = rng.uniform(0, 800, (n, 2))
    p = rng.uniform(0, 1, n)
    q = TG.score(X, cen, 0.5, p)
    assert q.shape == (n,) and np.all((q >= 0) & (q <= 1))
    q2 = TG.score(X, cen, 0.5, np.clip(p + 0.3, 0, 1))
    assert q2.mean() > q.mean()                  # a higher built-in probability raises the gated score
    m = TG.model()
    assert "validation" in m or "report" in m or "trained_on" in m


def test_glomeruli_low_magnification_and_blank():
    from medstatix.imaging import structures as ST
    img = _tissue(400, 400)
    assert ST.glomeruli(img, [], 1.0)[0] == []               # disabled at low magnification
    out, mask = ST.glomeruli(img, [], 0.4)
    assert out == [] and mask.shape == img.shape[:2]


def test_reader_profiles_run():
    from medstatix.imaging import reader as RD
    img = IC.load_image(os.path.join(SAMPLES, "HE_breast_carcinoma_1.png"))[:384, :384]
    for prof in RD.PROFILES:
        r = RD.read_image(img, 0.5, "auto", 0.65, profile=prof)
        assert r["profile"] == prof and len(r["cells"]) > 10
        assert "Calibration (µm per pixel)" in r["summary"] or r["px_um"]


def test_enhancement_keeps_drawn_marks():
    img = _with_scale_bar(_tissue(), 120)
    out, done, rep, steps, info = IC.publication_ready(img)
    H, W = img.shape[:2]
    box = img[H - 60:H - 12, W - 150:W - 12]
    assert (out[H - 60:H - 12, W - 150:W - 12][box.min(2) >= 250] >= 250).all()     # label box stays white
    assert info.get("marks_kept_px", 0) > 0
    a = IC.load_image(os.path.join(SAMPLES, "HE_breast_carcinoma_1.png"))
    assert "marks_kept_px" not in IC.publication_ready(a)[4]


def _scores_df():
    import pandas as pd
    rng = np.random.default_rng(0)
    return pd.DataFrame({"Group": np.repeat(["G1", "G2", "G3", "G4"], 6),
                         "Score": np.r_[[0, 0, 0, 1, 0, 0], [1, 1, 2, 1, 2, 1], [3, 3, 2, 3, 3, 2], [2, 1, 2, 2, 1, 2]],
                         "Infl": np.r_[rng.normal(50, 10, 6), rng.normal(60, 10, 6), rng.normal(700, 150, 6), rng.normal(500, 100, 6)]})


def test_advisor_ordinal_scores_and_unequal_variances():
    from medstatix.core.advisor import auto_analyze
    df = _scores_df()
    assert auto_analyze(df.copy(), "Score", "Group")[1] == "kruskal"          # lesion grade: rank test, not chi-square
    assert auto_analyze(df[df.Group.isin(["G1", "G3"])].copy(), "Score", "Group")[1] == "mannwhitney"
    res, aid = auto_analyze(df.copy(), "Infl", "Group")                       # normal groups, unequal SDs
    assert aid == "anova1" and "Games-Howell" in res.blocks[0].content["en"]


def test_burned_scale_bar_round_trip():
    from medstatix.imaging import marks as MK
    for W, px in [(800, 0.5), (1040, 0.25), (2000, 1.0)]:
        img = _tissue(int(W * 0.75), W)
        um = IC.nice_bar_um(W, px)
        out = IC.draw_scale_bar(img, px)
        sb = MK.scale_bar(out)
        assert sb and abs(sb["px"] - um / px) <= 1 and sb["um"] == um
        changed = (out != img).any(2)
        assert changed.mean() < 0.05 and not changed[: int(W * 0.5)].any()     # only the corner box changes
    with pytest.raises(ValueError):
        IC.draw_scale_bar(_tissue(), 0)


def test_batch_scale_bar(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from medstatix.ui.histobatch import process_one
    from medstatix.imaging import marks as MK
    src = tmp_path / "a.png"
    Image.fromarray(IC.load_image(os.path.join(SAMPLES, "HE_breast_carcinoma_1.png"))[:400, :500]).save(src)
    res, _ = process_one(str(src), "auto", "camera", "standard", "None (enhance only)", 0.5, str(tmp_path), "png", 300, False,
                         dict(position="bottom-left", style="black on white box", length_um=50))
    assert res["scale_bar"] == "added"
    sb = MK.scale_bar(IC.load_image(str(tmp_path / "a_processed.png")))
    assert sb and abs(sb["px"] - 100) <= 1 and sb["um"] == 50
    os.makedirs(tmp_path / "x")
    res2, _ = process_one(str(tmp_path / "a_processed.png"), "auto", "camera", "standard", "None (enhance only)", 0, str(tmp_path / "x"),
                          "png", 300, False, dict(position="bottom-right", style="black", length_um=None))
    assert res2["scale_bar"] == "already on image" and abs(res2["um_per_px"] - 0.5) < 0.01


def test_scale_bar_dialog_offscreen():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QGraphicsScene
    app = QApplication.instance() or QApplication([])
    from medstatix.ui.scalebar_ui import ScaleBarDialog, scale_bar_item
    img = _with_scale_bar(_tissue(), 120)
    d = ScaleBarDialog(None, img, 0.0)
    d._read()
    v = d.values()
    if v["um_per_px"]:
        assert abs(v["um_per_px"] - 50 / 120) < 0.01
    v["um_per_px"] = 0.5
    sc = QGraphicsScene()
    grp, um = scale_bar_item(sc, img.shape, v)
    assert um == IC.nice_bar_um(img.shape[1], 0.5) and len(grp.childItems()) == 3
    sc.clear(); sc.deleteLater(); d.close(); d.deleteLater()      # release Qt objects before the interpreter exits
    app.processEvents()
    del grp, sc, d


def _apo_like():
    import pandas as pd
    rng = np.random.default_rng(5)
    groups = ["Control", "Toxin", "Toxin + Drug 50", "Toxin + Drug 100"]
    mu = {"Control": (0.5, 2.5), "Toxin": (1.5, 1.0), "Toxin + Drug 50": (0.9, 1.8), "Toxin + Drug 100": (0.6, 2.2)}
    rows = [{"Group": g, "Bax": rng.normal(mu[g][0], 0.08), "Bcl2": rng.normal(mu[g][1], 0.2)} for g in groups for _ in range(8)]
    return pd.DataFrame(rows)


def test_groups_keep_design_order():
    from medstatix.core.data import _level_order
    import pandas as pd
    assert _level_order(pd.Series(["Control", "Toxin", "Toxin + Drug", "Control"])) == ["Control", "Toxin", "Toxin + Drug"]
    assert _level_order(pd.Series([10, 2, 1, 2])) == [1, 2, 10]


def test_journal_table_and_panels():
    from medstatix.analyses import run
    r = run("journal_table", _apo_like(), variables=["Bax", "Bcl2"], group="Group")
    tab = r.tables[0].content
    assert list(tab["Group"])[:4] == ["Control", "Toxin", "Toxin + Drug 50", "Toxin + Drug 100"]
    assert tab.loc[1, "Bax"].endswith("****") and "#" in tab.loc[2, "Bax"] and "±" in tab.loc[0, "Bax"]
    assert "versus Control" in r.tables[0].note and "versus Toxin" in r.tables[0].note
    fig = r.figures[0].content
    assert len([a for a in fig.axes if a.get_visible()]) == 2 and "(A) Bax" in r.figures[0].caption


def test_signature_outputs(tmp_path):
    pytest.importorskip("docx")
    from medstatix.core.settings import SETTINGS
    from medstatix.analyses import run
    from medstatix.report.export import results_to_docx
    old = SETTINGS.table_style
    try:
        SETTINGS.table_style = "Signature"
        r = run("anova1", _apo_like(), outcome="Bax", group="Group")
        html = r.to_html(embed_figures=False)
        assert 'class="sig"' in html and "psig" in html
        assert "one-way anova (f(3, 28)" in r.figures[0].caption.lower()
        p = tmp_path / "r.docx"
        results_to_docx([r], str(p))
        from docx import Document
        d = Document(str(p))
        assert d.tables and d.tables[0].rows[0].cells[0].text == "Group"
        assert not any(par.text.startswith("Interpretation: Smart advisor") for par in d.paragraphs)
    finally:
        SETTINGS.table_style = old


def test_correlation_caption_complete():
    from medstatix.analyses import run
    r = run("correlation", _apo_like(), variables=["Bax", "Bcl2"], method="Pearson")
    cap = r.figures[0].caption
    assert "95% CI" in cap and "n = 32" in cap and "r²" in cap
