"""v2.0: expert mode, professional histopathology comments / legends / group report."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from medstatix.report import histo_comment as HC  # noqa: E402
from test_v19 import _blot, _chart  # noqa: E402


def _reading(pct=10.0, foci=3, cong=0.0, vac=0.0, glom=0):
    return {"stain": "H&E", "summary": {"Nuclei detected": 900, "Inflammatory cells % of nuclei": pct,
                                        "Inflammatory cells per mm²": 500.0, "Congestion area % of tissue": cong,
                                        "Vacuolated area % of tissue": vac},
            "foci": [{"n": 20 + i} for i in range(foci)], "inflammatory": [1] * 5, "congestion": [1] if cong else [],
            "glomeruli": [{}] * glom, "px_um": 0.5, "width_px": 1000,
            "marks": {"scale_bar": {"um": 50, "um_per_px": 0.5, "px": 100}}}


def test_grades_and_comment():
    r = _reading(10.0, 3, 2.5, 0.2, 2)
    assert HC.grades(r) == {"inflammation": 3, "congestion": 2, "vacuolation": 0}
    t = HC.image_comment(r, "kidney", "G2")
    assert t.startswith("The kidney section from G2 showed marked (grade 3) multifocal") and "moderate (grade 2) vascular congestion" in t
    assert "2 glomeruli" in t
    ar = HC.image_comment(r, "الكلى", "G2", ar=True)
    assert "شديدًا (درجة 3)" in ar and "كبيبتين" in ar
    normal = HC.image_comment(_reading(1.0, 0), "liver")
    assert "preserved histological architecture" in normal


def test_legend_uses_existing_scale_bar():
    leg = HC.legend(_reading(), "kidney", "G3", "H&E", "×400", "Figure 2")
    assert leg.startswith("Figure 2. Representative photomicrograph of an H&E-stained kidney section from G3 (×400)")
    assert "Scale bar = 50 µm." in leg and "Yellow outlines, inflammatory foci" in leg


def test_ihc_comment():
    r = {"stain": "IHC", "summary": {"Nuclei detected": 500, "Positive nuclei %": 42.0, "Cell H-score (0–300)": 95.0,
                                     "Weak / moderate / strong %": "20 / 15 / 7"}}
    assert "moderate immunoreactivity" in HC.image_comment(r, "liver", "G2")


def test_group_results():
    rng = np.random.default_rng(0)
    rows = [{"group": g, "Inflammatory cells % of nuclei": rng.normal(m, 1), "Congestion grade": 0}
            for g, m in (("Control", 1), ("Toxin", 12), ("Toxin + Drug", 5)) for _ in range(6)]
    t = HC.group_results(pd.DataFrame(rows))
    assert "Kruskal–Wallis" in t and "higher in Toxin" in t and "No significant between-group differences were found in Congestion grade" in t
    assert "كروسكال" in HC.group_results(pd.DataFrame(rows), ar=True)


def test_expert_mode_blots_and_upscale():
    from medstatix.imaging import general as GN
    img = _blot()
    steps = GN.preset("blot", img) + [{"op": "sharpen", "params": {}}]
    _, done = GN.apply(img, steps, "blot")
    assert "sharpen" not in [s["op"] for s in done]
    out, log, _ = GN.process(img, "blot", steps, expert=True)
    assert "sharpen" in [s["op"] for s in log.steps] and "Non-linear adjustments (unsharp mask)" in log.methods_text()
    out, log, plan = GN.process(_chart(), "chart", width_mm=85, dpi=1000, expert=True)
    assert log.resize["factor"] == 8.0
    out, log, plan = GN.process(_chart(), "chart", width_mm=85, dpi=1000, tag_only=True)
    assert out.shape == _chart().shape[:2] + (3,) or out.shape[1] <= _chart().shape[1]
    assert log.output["dpi"] == 1000 and log.output["tag_only"] and log.output["width_mm"] < 20


def test_expert_limits_in_histology_pipeline():
    from medstatix.core.settings import SETTINGS
    from medstatix.imaging import core as IC
    img = np.full((60, 60, 3), 128, np.uint8); img[20:40, 20:40] = 90
    old = SETTINGS.expert_mode
    try:
        SETTINGS.expert_mode = False
        assert IC.apply_pipeline(img, [{"op": "levels", "params": {"contrast": 2.4}}])[1][0]["params"]["contrast"] == 1.6
        SETTINGS.expert_mode = True
        assert IC.apply_pipeline(img, [{"op": "levels", "params": {"contrast": 2.4}}])[1][0]["params"]["contrast"] == 2.4
    finally:
        SETTINGS.expert_mode = old


def test_comment_dialog_offscreen():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from medstatix.ui.comment_ui import CommentDialog
    d = CommentDialog(None, _reading(), "G2", "kidney")
    assert "G2" in d.boxes["legend_en"].toPlainText() and d.boxes["comment_ar"].toPlainText()
    d.group.setText("Toxin")
    assert "Toxin" in d.boxes["comment_en"].toPlainText()
    d.close(); d.deleteLater(); app.processEvents()
    del d
