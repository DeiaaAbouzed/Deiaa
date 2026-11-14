"""Correlation: Pearson, Spearman, Kendall, partial correlation, matrix with heatmap."""
from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd
from scipy import stats

from ..core.data import numeric
from ..core.result import Result, AnalysisError
from ..plots import figures as F
from .common import magnitude_r, p_adjust, pstr, sig_words
from .registry import register, P, P_ADJ


def _corr(x, y, method):
    if method == "Pearson":
        r = stats.pearsonr(x, y)
        ci = r.confidence_interval(0.95)
        return r.statistic, r.pvalue, ci.low, ci.high
    if method == "Spearman":
        r, p = stats.spearmanr(x, y)
    else:
        r, p = stats.kendalltau(x, y)
    n = len(x)
    # Fisher-z CI (Bonett-Wright SE for Spearman, Fieller for Kendall)
    se = math.sqrt((1 + r ** 2 / 2) / (n - 3)) if method == "Spearman" else math.sqrt(0.437 / (n - 4))
    z = np.arctanh(np.clip(r, -0.9999, 0.9999))
    return r, p, np.tanh(z - 1.96 * se), np.tanh(z + 1.96 * se)


@register("correlation", "correlation", "Correlation (Pearson / Spearman / Kendall)", "الارتباط (بيرسون / سبيرمان / كندال)",
          [P("variables", "Variables (≥ 2)", "المتغيرات (2 أو أكثر)", "vars_num"),
           P("method", "Coefficient", "المعامل", "choice", ["Pearson", "Spearman", "Kendall"], "Pearson"),
           P("adjust", "Multiplicity adjustment", "تصحيح التعدد", "choice", P_ADJ, "None")],
          "Correlation coefficients with 95% CI and p, scatter plot with regression line or heatmap.",
          "معاملات الارتباط مع فترات الثقة ورسم الانتشار أو الخريطة الحرارية.")
def correlation(df, variables, method="Pearson", adjust="None"):
    if len(variables) < 2:
        raise AnalysisError("Select at least 2 variables.")
    d = pd.DataFrame({v: numeric(df, v) for v in variables})
    rows = []
    k = len(variables)
    R = np.eye(k)
    Pm = np.zeros((k, k))
    for i, j in itertools.combinations(range(k), 2):
        sub = d[[variables[i], variables[j]]].dropna()
        r, p, lo, hi = _corr(sub.iloc[:, 0], sub.iloc[:, 1], method)
        R[i, j] = R[j, i] = r
        Pm[i, j] = Pm[j, i] = p
        rows.append({"Variable 1": variables[i], "Variable 2": variables[j], "n": len(sub), "r": r,
                     "95% CI lower": lo, "95% CI upper": hi, "p": p, "R²": r ** 2 if method == "Pearson" else np.nan})
    tab = pd.DataFrame(rows)
    if adjust != "None" and len(tab) > 1:
        tab["p (adj.)"] = p_adjust(tab.p, adjust)
    sym = {"Pearson": "r", "Spearman": "ρ (rho)", "Kendall": "τ (tau-b)"}[method]
    tab = tab.rename(columns={"r": sym})
    res = Result(f"{method} correlation", ", ".join(variables))
    res.table(tab, f"{method} correlation coefficients", "Pairwise deletion of missing values.", p_columns=("p", "p (adj.)"))
    en, ar = [], []
    for r_ in rows:
        mag = magnitude_r(r_["r"])
        dirn = ("positive", "طردية") if r_["r"] > 0 else ("negative", "عكسية")
        en.append(f"{r_['Variable 1']} – {r_['Variable 2']}: {mag[0]} {dirn[0]} correlation ({sym} = {r_['r']:.2f}, 95% CI "
                  f"{r_['95% CI lower']:.2f} to {r_['95% CI upper']:.2f}, {pstr(r_['p'])}).")
        ar.append(f"{r_['Variable 1']} – {r_['Variable 2']}: علاقة {dirn[1]} {mag[1]} ({r_['r']:.2f}، {pstr(r_['p'])}).")
    en.append("Correlation does not imply causation; for agreement between two methods use Bland-Altman, not correlation.")
    ar.append("الارتباط لا يعني السببية؛ ولتقييم الاتفاق بين طريقتين قياس استخدم بلاند-ألتمان وليس الارتباط.")
    res.interpret("\n".join(en[:12] + en[-1:]), "\n".join(ar[:12] + ar[-1:]))
    if k == 2:
        sub = d.dropna()
        res.figure(F.scatter_fit(sub.iloc[:, 0], sub.iloc[:, 1], variables[0], variables[1],
                                 annotate=f"{sym.split()[0]} = {rows[0]['r']:.2f}, {pstr(rows[0]['p'])}"),
                   f"Scatter plot with least-squares line and 95% confidence band.")
    else:
        res.figure(F.heatmap(R, variables, f"{method} correlation matrix", annot_p=Pm), "Correlation heatmap (*p < 0.05).")
    res.methods(f"Associations were assessed with {method}'s correlation coefficient{' (data not normally distributed)' if method != 'Pearson' else ''}, "
                f"reported with 95% confidence intervals.")
    return res


@register("partial_corr", "correlation", "Partial correlation", "الارتباط الجزئي",
          [P("x", "Variable X", "المتغير X", "var_num"), P("y", "Variable Y", "المتغير Y", "var_num"),
           P("controls", "Control for", "ضبط المتغيرات", "vars_num"),
           P("method", "Type", "النوع", "choice", ["Pearson", "Spearman"], "Pearson")],
          "Correlation between X and Y controlling for covariates.", "الارتباط بين متغيرين مع ضبط متغيرات أخرى.")
def partial_corr(df, x, y, controls, method="Pearson"):
    cols = [x, y] + list(controls)
    d = pd.DataFrame({c: numeric(df, c) for c in cols}).dropna()
    if method == "Spearman":
        d = d.rank()
    Z = np.column_stack([np.ones(len(d))] + [d[c] for c in controls])
    rx = d[x] - Z @ np.linalg.lstsq(Z, d[x], rcond=None)[0]
    ry = d[y] - Z @ np.linalg.lstsq(Z, d[y], rcond=None)[0]
    r = np.corrcoef(rx, ry)[0, 1]
    n, k = len(d), len(controls)
    dfree = n - 2 - k
    t = r * math.sqrt(dfree / (1 - r ** 2))
    p = 2 * stats.t.sf(abs(t), dfree)
    se = 1 / math.sqrt(n - 3 - k)
    z = np.arctanh(r)
    zero = stats.pearsonr(d[x], d[y])[0]
    res = Result("Partial correlation", f"{x} – {y} | {', '.join(controls)}")
    res.table(pd.DataFrame([{"Zero-order r": zero, "Partial r": r, "95% CI lower": np.tanh(z - 1.96 * se),
                             "95% CI upper": np.tanh(z + 1.96 * se), "df": dfree, "t": t, "p": p}]), "Partial correlation")
    res.interpret(f"After controlling for {', '.join(controls)}, r changed from {zero:.2f} to {r:.2f} ({pstr(p)}).",
                  f"بعد ضبط {', '.join(controls)}، تغير معامل الارتباط من {zero:.2f} إلى {r:.2f} ({pstr(p)}).")
    return res
