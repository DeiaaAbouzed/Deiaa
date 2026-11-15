"""Manuscript builder and reviewer-proof statistical report (Word).

* build_manuscript: a submission-ready "Statistical analysis" (Methods) paragraph, a Results section that cites the
  numbered tables and figures, APA three-line tables, a figure-legends list and the figures sized to the target
  journal's column width.
* build_reviewer_report: for every analysis, why the test was chosen (design + assumption checks), effect sizes with
  95 % CIs, a sensitivity (minimum detectable effect) analysis, a non-parametric robustness check, and a
  reproducibility statement — the questions statistical reviewers usually ask.
"""
from __future__ import annotations

import io
import math
import re

import numpy as np
import pandas as pd

from ..core.result import APP_NAME, APP_VERSION, Result, fmt_p, fig_to_png_bytes
from ..core.settings import SETTINGS
from .export import _set_cell_border
from .journals import JOURNALS

_RESULT_SENT = re.compile(r"(=|<\s*0?\.\d|χ²|η²|\bCI\b|\bHR\b|\bOR\b|\(\d+(,\s*\d+)?\)\s*=)")


def _sentences(text: str):
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z(])", text.strip())
    return [p.strip() for p in parts if p.strip()]


def split_methods(text: str):
    """Split an analysis' 'Methods / Results' text into method sentences and result sentences."""
    meth, res = [], []
    for s in _sentences(text):
        if re.search(r"considered (statistically )?significant", s):
            continue
        (res if _RESULT_SENT.search(s) else meth).append(s)
    return meth, res


def _interp(b, lang):
    c = b.content
    if lang == "both":
        return c.get("en", ""), c.get("ar", "")
    return (c.get(lang) or c.get("en", "")), ""


def _p_word(journal):
    j = JOURNALS.get(journal or "", {})
    return "P" if j.get("p_style") == "P" else "p"


def _doc(font="Times New Roman", size=11):
    from docx import Document
    from docx.shared import Pt, Mm
    doc = Document()
    st = doc.styles["Normal"]; st.font.name = font; st.font.size = Pt(size)
    sec = doc.sections[0]; sec.left_margin = sec.right_margin = Mm(25)
    return doc


def _apa_table(doc, df, caption, note, number, p_columns=()):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt
    thick = {"sz": 12, "val": "single", "color": "000000"}
    thin = {"sz": 6, "val": "single", "color": "000000"}
    none = {"val": "nil"}
    df = Result.format_df(df, p_columns)
    if not isinstance(df.index, pd.RangeIndex):
        df = df.reset_index()
    p = doc.add_paragraph(); p.add_run(f"Table {number}. ").bold = True; p.add_run(caption or "").italic = True
    t = doc.add_table(rows=len(df) + 1, cols=len(df.columns))
    for j, c in enumerate(df.columns):
        cell = t.cell(0, j); cell.text = str(c); cell.paragraphs[0].runs[0].bold = True
        _set_cell_border(cell, top=thick, bottom=thin, left=none, right=none)
    for i in range(len(df)):
        for j in range(len(df.columns)):
            cell = t.cell(i + 1, j); cell.text = str(df.iat[i, j])
            _set_cell_border(cell, top=none, left=none, right=none, bottom=thick if i == len(df) - 1 else none)
    for row in t.rows:
        for j, cell in enumerate(row.cells):
            for par in cell.paragraphs:
                par.alignment = WD_ALIGN_PARAGRAPH.LEFT if j == 0 else WD_ALIGN_PARAGRAPH.CENTER
                for run in par.runs:
                    run.font.size = Pt(9)
    if note:
        p = doc.add_paragraph(); p.add_run("Note. ").italic = True; r = p.add_run(note); r.font.size = Pt(9)
    doc.add_paragraph()


# ---------------------------------------------------------------------------- manuscript
def build_manuscript(results: list[Result], path: str, journal: str = "", width_key: str = "single",
                     lang: str = "en", tables_inline: bool = False, histology_methods: str = "",
                     main_tables_only: bool = True):
    """Write a Word file with Methods (statistical analysis), Results, Tables, Figure legends and Figures."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Mm, Pt
    doc = _doc()
    pw = _p_word(journal)
    j = JOURNALS.get(journal or "")
    fig_w = (j["widths"].get(width_key) or list(j["widths"].values())[0]) if j else 160
    dpi = j["dpi_combo"] if j else 600
    doc.add_heading("Manuscript draft — statistics sections", level=0)
    info = doc.add_paragraph(f"Prepared with {APP_NAME} {APP_VERSION}" + (f" for {journal} artwork/statistics conventions" if j else "")
                             + ". Review and adapt the wording before submission.")
    info.runs[0].italic = True; info.runs[0].font.size = Pt(9)

    # ---- collect
    meth_sents, items = [], []
    tnum = fnum = 0
    for res in results:
        entry = {"title": res.title.replace("🧠 ", ""), "res_sents": [], "interp": ("", ""), "tables": [], "figures": []}
        for b in res.blocks:
            if b.kind == "methods":
                m, r = split_methods(b.content)
                for s in m:
                    if s not in meth_sents:
                        meth_sents.append(s)
                entry["res_sents"] += r
            elif b.kind == "results":
                entry["prose"] = b.content.get("en", "")
            elif b.kind == "interpret" and not str(b.content.get("en", "")).startswith("Smart advisor"):
                entry["interp"] = _interp(b, lang if lang in ("en", "ar", "both") else "en")
            elif b.kind == "table":
                cap = (b.caption or "").lower()
                aux = any(k in cap for k in ("normality", "homogeneity", "robust", "assumption", "shapiro", "levene"))
                if main_tables_only and aux:
                    continue
                tnum += 1; entry["tables"].append((tnum, b))
            elif b.kind == "figure":
                fnum += 1; entry["figures"].append((fnum, b))
        items.append(entry)

    # ---- Methods
    doc.add_heading("2.x Statistical analysis", level=1)
    eb = {"SD": "mean ± standard deviation (SD)", "SEM": "mean ± standard error of the mean (SEM)",
          "95% CI": "mean with 95% confidence interval"}.get(SETTINGS.error_bar, "mean ± SD")
    para = [f"Data are presented as {eb}, with individual values shown in the figures."]
    para += meth_sents
    para.append(f"All tests were two-sided and {pw} < {SETTINGS.alpha:g} was considered statistically significant.")
    para.append(f"Analyses were performed with {APP_NAME} version {APP_VERSION} (Python; SciPy, statsmodels).")
    doc.add_paragraph(" ".join(para))
    if histology_methods:
        doc.add_heading("2.x Image acquisition and processing", level=1)
        doc.add_paragraph(histology_methods)

    # ---- Results
    doc.add_heading("3. Results", level=1)
    for e in items:
        doc.add_heading(e["title"], level=2)
        refs = []
        if e["tables"]:
            refs.append("Table " + ", ".join(str(n) for n, _ in e["tables"]))
        if e["figures"]:
            refs.append("Figure " + ", ".join(str(n) for n, _ in e["figures"]))
        if e.get("prose"):     # a written Results narrative replaces the per-analysis interpretation
            for para in e["prose"].split("\n\n"):
                doc.add_paragraph(re.sub(r"\bp ([=<])", f"{pw} \\1", para))
            continue
        txt = e["interp"][0] or " ".join(e["res_sents"])
        txt = re.sub(r"\bp = <", "p <", txt)
        txt = re.sub(r"\bp ([=<])", f"{pw} \\1", txt)
        p = doc.add_paragraph(txt + (f" ({'; '.join(refs)})." if refs else ""))
        if e["interp"][1]:
            pa = doc.add_paragraph(e["interp"][1]); pa.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        if tables_inline:
            for n, b in e["tables"]:
                _apa_table(doc, b.content, b.caption, b.note, n, b.p_columns)

    if not tables_inline and any(e["tables"] for e in items):
        doc.add_page_break(); doc.add_heading("Tables", level=1)
        for e in items:
            for n, b in e["tables"]:
                _apa_table(doc, b.content, b.caption, b.note, n, b.p_columns)

    figs = [(n, b) for e in items for n, b in e["figures"]]
    if figs:
        doc.add_page_break(); doc.add_heading("Figure legends", level=1)
        for n, b in figs:
            p = doc.add_paragraph(); p.add_run(f"Figure {n}. ").bold = True
            p.add_run(re.sub(r"\bp ([=<])", f"{pw} \\1", b.caption or ""))
        doc.add_page_break(); doc.add_heading("Figures", level=1)
        for n, b in figs:
            doc.add_paragraph().add_run(f"Figure {n}").bold = True
            doc.add_picture(io.BytesIO(fig_to_png_bytes(b.content, dpi=min(dpi, 600))), width=Mm(fig_w))
    doc.save(path)
    return {"tables": tnum, "figures": fnum}


# ---------------------------------------------------------------------------- reviewer report
def _hedges_g(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return np.nan, np.nan, np.nan
    sp = math.sqrt(((n1 - 1) * a.var(ddof=1) + (n2 - 1) * b.var(ddof=1)) / (n1 + n2 - 2))
    if sp == 0:
        return np.nan, np.nan, np.nan
    d = (b.mean() - a.mean()) / sp
    J = 1 - 3 / (4 * (n1 + n2) - 9)
    g = d * J
    se = math.sqrt((n1 + n2) / (n1 * n2) + g * g / (2 * (n1 + n2)))
    return g, g - 1.96 * se, g + 1.96 * se


def effect_table(groups: dict, ref: str | None = None) -> pd.DataFrame:
    """Mean difference (Welch 95 % CI) and Hedges' g (95 % CI) of every group versus the reference group."""
    from scipy import stats
    names = list(groups)
    ref = ref if ref in groups else names[0]
    a = np.asarray(groups[ref], float); a = a[~np.isnan(a)]
    rows = []
    for g in names:
        if g == ref:
            continue
        b = np.asarray(groups[g], float); b = b[~np.isnan(b)]
        if len(a) < 2 or len(b) < 2:
            continue
        diff = b.mean() - a.mean()
        v1, v2 = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
        se = math.sqrt(v1 + v2)
        dfw = (v1 + v2) ** 2 / (v1 ** 2 / (len(a) - 1) + v2 ** 2 / (len(b) - 1)) if (v1 + v2) > 0 else len(a) + len(b) - 2
        tcrit = stats.t.ppf(0.975, dfw)
        hg, lo, hi = _hedges_g(a, b)
        rows.append({"Comparison": f"{g} vs {ref}", "Mean difference": diff, "95% CI": f"{diff - tcrit * se:.3f} to {diff + tcrit * se:.3f}",
                     "Hedges' g": hg, "g 95% CI": f"{lo:.2f} to {hi:.2f}",
                     "Magnitude": ("negligible" if abs(hg) < 0.2 else "small" if abs(hg) < 0.5 else "medium" if abs(hg) < 0.8 else "large")})
    return pd.DataFrame(rows)


def sensitivity(groups: dict, alpha=0.05, power=0.8) -> str:
    """Minimum effect detectable with 80 % power given the actual group sizes (sensitivity power analysis)."""
    from statsmodels.stats.power import FTestAnovaPower, TTestIndPower
    ns = [int(np.sum(~np.isnan(np.asarray(v, float)))) for v in groups.values()]
    k = len(ns)
    if k < 2 or min(ns) < 2:
        return ""
    if k == 2:
        d = TTestIndPower().solve_power(nobs1=ns[0], ratio=ns[1] / ns[0], alpha=alpha, power=power)
        return (f"With n = {ns[0]} and {ns[1]} per group, the study had 80% power (two-sided α = {alpha:g}) to detect a "
                f"standardised difference of Cohen's d ≥ {d:.2f}.")
    f = FTestAnovaPower().solve_power(nobs=sum(ns), k_groups=k, alpha=alpha, power=power)
    return (f"With {k} groups (total N = {sum(ns)}, n = {min(ns)}–{max(ns)} per group), the study had 80% power "
            f"(α = {alpha:g}) to detect an overall effect of Cohen's f ≥ {f:.2f} (η² ≥ {f * f / (1 + f * f):.2f}).")


def robustness(groups: dict) -> str:
    from scipy import stats
    vals = [np.asarray(v, float)[~np.isnan(np.asarray(v, float))] for v in groups.values()]
    if len(vals) < 2 or min(len(v) for v in vals) < 2:
        return ""
    if len(vals) == 2:
        p = stats.mannwhitneyu(vals[0], vals[1], alternative="two-sided").pvalue
        return f"Robustness check: the non-parametric Mann–Whitney U test gave p = {fmt_p(p)}."
    p = stats.kruskal(*vals).pvalue
    return f"Robustness check: the non-parametric Kruskal–Wallis test gave p = {fmt_p(p)}."


def build_reviewer_report(results: list[Result], path: str, lang: str = "en"):
    from docx.shared import Pt
    doc = _doc()
    doc.add_heading("Statistical report for reviewers", level=0)
    p = doc.add_paragraph(f"Generated by {APP_NAME} {APP_VERSION}. For each analysis: design and choice of test, assumption checks, "
                          "effect sizes with 95% confidence intervals, sensitivity power, a robustness check and reproducibility.")
    p.runs[0].italic = True; p.runs[0].font.size = Pt(9)
    tn = 0
    for i, res in enumerate(results, 1):
        doc.add_heading(f"{i}. {res.title.replace('🧠 ', '')}", level=1)
        diag = [b for b in res.blocks if b.kind == "interpret" and str(b.content.get("en", "")).startswith("Smart advisor")]
        meth = [b for b in res.blocks if b.kind == "methods"]
        doc.add_heading("Why this test", level=2)
        if diag:
            for line in str(diag[0].content.get("en", "")).split("\n")[1:]:
                doc.add_paragraph(line.lstrip("• "), style="List Bullet")
        if meth:
            m, r = split_methods(meth[0].content)
            doc.add_paragraph(" ".join(m) or meth[0].content)
        checks = [b for b in res.tables if any(k in (b.caption or "").lower() for k in
                                                ("normality", "homogeneity", "robust", "shapiro", "levene", "sphericity", "assumption"))]
        if checks:
            doc.add_heading("Assumption checks", level=2)
            for b in checks:
                tn += 1; _apa_table(doc, b.content, b.caption, b.note, tn, b.p_columns)
        specs = [getattr(b.content, "_mx_spec", None) for b in res.figures]
        specs = [s for s in specs if s is not None and len(s.groups) >= 2]
        if specs:
            sp = specs[0]
            doc.add_heading("Effect sizes (95% CI)", level=2)
            et = effect_table(sp.groups, sp.ref1 or None)
            if len(et):
                tn += 1; _apa_table(doc, et, f"Effect sizes versus {sp.ref1 or list(sp.groups)[0]}",
                                    "Mean difference with Welch 95% CI; Hedges' g (bias-corrected standardised difference) with "
                                    "approximate 95% CI. |g| < 0.2 negligible, 0.2–0.5 small, 0.5–0.8 medium, ≥ 0.8 large.", tn)
            doc.add_heading("Sensitivity (power) and robustness", level=2)
            for t in (sensitivity(sp.groups, SETTINGS.alpha), robustness(sp.groups)):
                if t:
                    doc.add_paragraph(t)
            doc.add_paragraph("Post hoc 'observed power' is not reported because it is a direct function of the p value "
                              "(Hoenig & Heisey, 2001); the sensitivity analysis above is the recommended alternative.")
        if meth:
            m, r = split_methods(meth[0].content)
            if r:
                doc.add_heading("Main result", level=2)
                doc.add_paragraph(" ".join(r))
    doc.add_heading("Reproducibility", level=1)
    doc.add_paragraph(f"All analyses were run in {APP_NAME} {APP_VERSION}, whose statistical engine is validated against R "
                      "(t.test, aov, TukeyHSD, kruskal.test, lm, glm, coxph), metafor and published reference values. "
                      "The project file (.msx) stores the data and every analysis setting, so all results can be re-run exactly.")
    doc.save(path)
