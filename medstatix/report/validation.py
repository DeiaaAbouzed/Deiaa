"""Validation report: runs every reference check (R, SPSS, GraphPad Prism, metafor, BayesFactor, G*Power) and exports
the results as a Word document that can be attached to a thesis or a reviewer response."""
from __future__ import annotations

import datetime as _dt
import importlib.util
import os

from ..core.result import APP_NAME, APP_VERSION

EQUIVALENCE = [
    ("Independent / paired t, Welch t", "SPSS T-TEST; Prism unpaired/paired t; R t.test", "Identical formulas (Student and Welch–Satterthwaite df)."),
    ("One-way ANOVA + Tukey HSD", "SPSS ONEWAY / UNIANOVA; Prism one-way ANOVA; R aov + TukeyHSD", "Same sums of squares; Tukey uses the studentized range distribution."),
    ("Mann–Whitney, Wilcoxon, Kruskal–Wallis", "SPSS NPTESTS; Prism nonparametric tests; R wilcox.test / kruskal.test", "Tie-corrected statistics; exact p for small samples where SPSS offers exact."),
    ("Pearson / Spearman correlation", "SPSS CORRELATIONS / NONPAR CORR; Prism correlation; R cor.test", "Same t-based test of r."),
    ("Linear / logistic regression", "SPSS REGRESSION / LOGISTIC REGRESSION; R lm / glm", "OLS and maximum likelihood (IRLS)."),
    ("Kaplan–Meier, log-rank, Cox", "SPSS KM / COXREG; Prism survival; R survival", "Product-limit, Mantel log-rank, Efron/Breslow partial likelihood."),
    ("Dose–response (4PL), probit LD50", "Prism nonlinear regression; R drc / glm probit", "Least squares (4PL) and probit ML (Finney)."),
    ("Meta-analysis (DL random effects)", "R metafor rma(method = 'DL')", "Same τ², I², Q."),
    ("Bayes factors (JZS)", "R BayesFactor ttestBF / correlationBF; JASP", "Rouder et al. (2009) integral, Cauchy prior r = √2/2."),
    ("Power analysis", "G*Power 3.1; R pwr / power.t.test", "Noncentral t, F, χ² and normal distributions as in G*Power."),
]


def _load_module():
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for path in (os.path.join(here, "tests", "test_validation.py"),
                 os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "validation", "test_validation.py")):
        if os.path.exists(path):
            spec = importlib.util.spec_from_file_location("mval", path)
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError("Validation suite (test_validation.py) not found.")


def run_checks():
    """Return a list of (check, MedStatix value, reference value, tolerance, PASS/FAIL, reference source)."""
    mod = _load_module()
    mod.RESULTS.clear()
    for name in sorted(dir(mod)):
        if name.startswith("test_") and name != "test_all_analyses_run":
            try:
                getattr(mod, name)()
            except AssertionError:
                pass
    return list(mod.RESULTS)


def results_html(rows):
    body = "".join(f"<tr><td style='text-align:left'>{n}</td><td>{g:.5g}</td><td>{r:.5g}</td>"
                   f"<td style='color:{'#2E8B57' if s == 'PASS' else '#C0392B'}'><b>{s}</b></td><td>{src}</td></tr>"
                   for n, g, r, t, s, src in rows)
    npass = sum(1 for r in rows if r[4] == "PASS")
    return (f"<h2>Validation against reference software</h2><p><b>{npass}/{len(rows)}</b> checks passed.</p>"
            f"<table class='apa' cellpadding='4'><tr><th>Check</th><th>MedStatix</th><th>Reference</th><th>Result</th>"
            f"<th>Source</th></tr>{body}</table>")


def export_docx(path, rows=None):
    from docx import Document
    from docx.shared import Pt
    from .export import _set_cell_border, _shade
    rows = rows if rows is not None else run_checks()
    npass = sum(1 for r in rows if r[4] == "PASS")
    doc = Document()
    st = doc.styles["Normal"]; st.font.name = "Times New Roman"; st.font.size = Pt(11)
    doc.add_heading(f"{APP_NAME} {APP_VERSION}: validation report", 1)
    doc.add_paragraph(f"Date: {_dt.date.today().isoformat()}.  Result: {npass} of {len(rows)} reference checks passed.")
    doc.add_paragraph(
        "Each analysis was run in MedStatix on a published reference data set (R data sets sleep, PlantGrowth, mtcars, aml; "
        "Bliss beetle data; metafor dat.bcg; Shrout & Fleiss 1979) and its output compared with the value reported by the "
        "reference software, within the stated tolerance. The suite is re-run on the installed copy each time this report "
        "is generated, so it documents the exact build used for the analysis.")
    doc.add_heading("1. Numerical agreement", 2)
    tb = doc.add_table(rows=1, cols=6)
    for c, h in zip(tb.rows[0].cells, ["Check", "MedStatix", "Reference", "Tolerance", "Result", "Reference software"]):
        c.text = h; _shade(c, "DCE6F1"); c.paragraphs[0].runs[0].bold = True
    for n, g, r, t, s, src in rows:
        cells = tb.add_row().cells
        for c, v in zip(cells, [n, f"{g:.5g}", f"{r:.5g}", f"± {t:g}", s, src]):
            c.text = v
    for row in tb.rows:
        for c in row.cells:
            _set_cell_border(c, top={"val": "single", "sz": 4}, bottom={"val": "single", "sz": 4},
                             start={"val": "single", "sz": 4}, end={"val": "single", "sz": 4})
            for p in c.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(9)
    doc.add_heading("2. Formula equivalence with SPSS, GraphPad Prism and R", 2)
    tb = doc.add_table(rows=1, cols=3)
    for c, h in zip(tb.rows[0].cells, ["Procedure", "Equivalent procedure", "Note"]):
        c.text = h; _shade(c, "DCE6F1"); c.paragraphs[0].runs[0].bold = True
    for proc, eq, note in EQUIVALENCE:
        cells = tb.add_row().cells
        for c, v in zip(cells, [proc, eq, note]):
            c.text = v
    for row in tb.rows:
        for c in row.cells:
            _set_cell_border(c, top={"val": "single", "sz": 4}, bottom={"val": "single", "sz": 4},
                             start={"val": "single", "sz": 4}, end={"val": "single", "sz": 4})
            for p in c.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(9)
    doc.add_heading("3. Suggested statement for the methods section", 2)
    doc.add_paragraph(
        f"Statistical analyses were performed with {APP_NAME} {APP_VERSION}, which uses SciPy and statsmodels; its output "
        f"was verified against R, SPSS-equivalent formulas, metafor, BayesFactor and G*Power on published reference data "
        f"({npass}/{len(rows)} checks agreed within tolerance).")
    doc.save(path)
    return npass, len(rows)
