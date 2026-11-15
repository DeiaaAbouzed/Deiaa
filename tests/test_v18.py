"""v1.8: Results prose, study colour reference, congestion learned from brush strokes, faster teaching of the reader."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from medstatix.imaging import core as IC  # noqa: E402
from test_v16 import _apo_like  # noqa: E402


@pytest.fixture
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from medstatix.imaging import cellclass as CC, rbc_learn as RL, tissue_gate as TG
    CC.reset(); RL.reset(); TG.reset()
    yield tmp_path
    CC.reset(); RL.reset(); TG.reset()


def test_results_prose_from_journal_table():
    from medstatix.analyses import run
    r = run("journal_table", _apo_like(), variables=["Bax", "Bcl2"], group="Group")
    blk = [b for b in r.blocks if b.kind == "results"]
    assert blk, "journal table must carry a Results section"
    en, ar = blk[0].content["en"], blk[0].content["ar"]
    assert "Toxin" in en and "Bax" in en and "Bcl2" in en and "p " in en
    assert "fold" in en or "%" in en
    assert "Overall" in en and "Toxin + Drug 100" in en.split("Overall")[1]
    assert "الضابطة" in ar


def test_narrative_handles_no_effect():
    from medstatix.report import narrative as NR
    g = {"Control": np.array([1.0, 1.1, 0.9]), "Model": np.array([1.0, 1.05, 0.95])}
    en, _ = NR.write({"X (mg/dL)": dict(g=g, pairs={("Model", "Control"): 0.8}, dec=2, npar=False, test="", post="",
                                        stat="F = 0.1", p=0.8)}, ["Control", "Model"], "Control", "Model")
    assert "did not" in en and "mg/dL" in en


def test_study_reference_colour_match():
    rng = np.random.default_rng(0)
    ref = np.clip(rng.normal((200, 120, 190), 12, (200, 200, 3)), 0, 255).astype(np.uint8)
    img = np.clip(rng.normal((170, 140, 150), 12, (200, 200, 3)), 0, 255).astype(np.uint8)
    st = IC.reference_stats(ref)
    out, done = IC.match_reference(img, st)
    assert done and np.abs(IC.reference_stats(out)["target_mean"][1] - st["target_mean"][1]) < 2


def _rbc_image(seed, with_rbc=True):
    """Same magenta everywhere; packed red cells are granular (small dots), 'muscle' is smooth striped."""
    rng = np.random.default_rng(seed)
    img = np.empty((240, 320, 3), float); img[...] = (235, 225, 235)
    yy, xx = np.mgrid[:240, :320]
    band = (np.sin(yy / 6.0) > -0.2) & (xx < 160)
    img[band] = (200, 90, 150)
    rbc = np.zeros((240, 320), bool)
    if with_rbc:
        for _ in range(500):
            cy, cx = rng.integers(40, 200), rng.integers(180, 300)
            m = (yy - cy) ** 2 + (xx - cx) ** 2 <= 9
            img[m] = (200, 90, 150); rbc |= m
        img[rbc] *= 1.0
        img[(~rbc) & (xx >= 175) & (xx <= 305) & (yy >= 35) & (yy <= 205)] = (250, 235, 245)
    img = np.clip(img + rng.normal(0, 4, img.shape), 0, 255).astype(np.uint8)
    return img, rbc, band


def test_congestion_learned_from_brush(appdata):
    from medstatix.imaging import rbc_learn as RL
    for k in range(4):
        img, rbc, band = _rbc_image(k, with_rbc=k != 3)
        assert RL.add_examples(img, rbc, band, f"img{k}") > 0
    rep = RL.train(epochs=150)
    assert rep["images"] == 4 and 0 <= rep["f1"] <= 1 and "f1_rule" in rep
    if rep["activated"]:
        img, rbc, band = _rbc_image(9)
        res, m = IC.congestion_area(img)
        assert m.shape == rbc.shape and (m & band).mean() < 0.2 and res["RBC-rich (congestion) area %"] <= 100
        assert "pixel classifier" in RL.methods_text()
    RL.clear()
    assert not RL.active() and RL.summary()["images"] == 0


def test_congestion_needs_three_images(appdata):
    from medstatix.imaging import rbc_learn as RL
    img, rbc, band = _rbc_image(0)
    RL.add_examples(img, rbc, band, "a")
    with pytest.raises(ValueError):
        RL.train()


def test_gate_refit_and_uncertain(appdata):
    from medstatix.imaging import cellclass as CC, training as TR, tissue_gate as TG
    rng = np.random.default_rng(1)
    for k in range(4):
        G = rng.normal(0, 1, (80, TR.N_GATE)); y = np.where(G[:, 2] + 0.3 * rng.normal(size=80) > 0.8, 1, 2)
        TR.add_examples(np.zeros((80, len(CC.FEATURES)), np.float32), y, f"im{k}", G=G)
    rep = TR.train_gate()
    assert rep is not None and rep["nuclei"] == 320 and set(rep) >= {"f1_builtin_gate", "f1_user_gate", "activated"}
    assert TG.active_source() == ("user" if rep["activated"] else "built-in")
    cells = [{"x": float(i * 20), "y": 10.0, "area_px": 50.0, "p_infl": p, "p_infl_builtin": p}
             for i, p in enumerate([0.1, 0.64, 0.9, 0.66, 0.3])]
    u = TR.uncertain({"cells": cells, "G": np.zeros((5, 6)), "X": None}, 2)
    assert set(u) == {1, 3}
    TR.clear_examples()
    assert TG.active_source() == "built-in"


def test_teach_dialogs_offscreen(appdata):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from medstatix.ui.histology import np_to_qimage
    from medstatix.ui.congestion_ui import CongestionTeachDialog
    from medstatix.ui.teach_ui import TeachDialog
    img, rbc, band = _rbc_image(0)
    d = CongestionTeachDialog(None, img, "x", np_to_qimage)
    d.grp.button(0).setChecked(True); d.dab(250, 100); d.dab(255, 102)
    d.grp.button(1).setChecked(True); d.dab(50, 50)
    assert d.rbc.sum() > 0 and d.bg.sum() > 0 and not (d.rbc & d.bg).any()
    poly = np.array([[0, 0], [0, 8], [8, 8], [8, 0]], float)
    cells = [{"x": 20.0 + 30 * i, "y": 20.0, "poly": poly + [20, 20 + 30 * i], "area_px": 50.0, "p_infl": 0.5, "p": 0.5,
              "type": "other"} for i in range(4)]
    from medstatix.imaging import cellclass as CC
    r = {"cells": cells, "X": np.zeros((4, len(CC.FEATURES)), np.float32), "G": None}
    t = TeachDialog(None, img, r, "y", np_to_qimage)
    t.grp.button(2).setChecked(True)
    t.lasso([(0, 0), (75, 0), (75, 40), (0, 40)])
    assert t.labels == {0: "tubular", 1: "tubular"}
    t.suggest()
    assert t.sugg and all(i not in t.labels for i in t.sugg)
    for w in (d, t):
        w.scene.clear(); w.close(); w.deleteLater()
    app.processEvents()
    del d, t
