"""Shared statistical helpers."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from ..core.result import fmt_p

ADJ_MAP = {"Holm": "holm", "Bonferroni": "bonferroni", "Benjamini-Hochberg (FDR)": "fdr_bh",
           "Šidák": "sidak", "None": None}


def p_adjust(pvals, method: str):
    m = ADJ_MAP.get(method, method)
    pvals = np.asarray(pvals, float)
    if m is None or len(pvals) == 0:
        return pvals
    return multipletests(pvals, method=m)[1]


def mean_ci(v, level=0.95):
    v = np.asarray(v, float)
    n = len(v)
    m = v.mean()
    if n < 2:
        return m, np.nan, np.nan
    h = stats.t.ppf(0.5 + level / 2, n - 1) * v.std(ddof=1) / math.sqrt(n)
    return m, m - h, m + h


def cohen_d_ind(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    n1, n2 = len(a), len(b)
    sp = math.sqrt(((n1 - 1) * a.var(ddof=1) + (n2 - 1) * b.var(ddof=1)) / (n1 + n2 - 2))
    d = (a.mean() - b.mean()) / sp if sp > 0 else np.nan
    J = 1 - 3 / (4 * (n1 + n2) - 9)
    g = d * J
    se = math.sqrt((n1 + n2) / (n1 * n2) + d ** 2 / (2 * (n1 + n2)))
    return d, g, d - 1.96 * se, d + 1.96 * se


def wilson_ci(x, n, level=0.95):
    if n == 0:
        return np.nan, np.nan
    z = stats.norm.ppf(0.5 + level / 2)
    p = x / n
    den = 1 + z ** 2 / n
    c = (p + z ** 2 / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / den
    return max(0, c - h), min(1, c + h)


def magnitude_d(d):
    d = abs(d)
    if d < 0.2:
        return "negligible", "ضئيل"
    if d < 0.5:
        return "small", "صغير"
    if d < 0.8:
        return "medium", "متوسط"
    return "large", "كبير"


def magnitude_r(r):
    r = abs(r)
    if r < 0.1:
        return "negligible", "ضئيل"
    if r < 0.3:
        return "weak", "ضعيف"
    if r < 0.5:
        return "moderate", "متوسط"
    if r < 0.7:
        return "strong", "قوي"
    return "very strong", "قوي جدًا"


def magnitude_eta(e):
    if e < 0.01:
        return "negligible", "ضئيل"
    if e < 0.06:
        return "small", "صغير"
    if e < 0.14:
        return "medium", "متوسط"
    return "large", "كبير"


def sig_words(p, alpha=0.05):
    if p < alpha:
        return ("statistically significant", "ذو دلالة إحصائية")
    return ("not statistically significant", "غير دال إحصائيًا")


def pstr(p):
    s = fmt_p(p)
    return f"p {s}" if s.startswith("<") else f"p = {s}"


def normality_check(groups: dict, alpha=0.05):
    """Shapiro-Wilk per group. Returns DataFrame and bool all_normal."""
    rows = []
    ok = True
    for k, v in groups.items():
        v = np.asarray(v, float)
        if 3 <= len(v) <= 5000:
            w, p = stats.shapiro(v)
        else:
            w, p = np.nan, np.nan
        if not np.isnan(p) and p < alpha:
            ok = False
        rows.append({"Group": k, "n": len(v), "Shapiro-Wilk W": w, "p": p,
                     "Normal?": "—" if np.isnan(p) else ("Yes" if p >= alpha else "No")})
    return pd.DataFrame(rows), ok


def describe_groups(groups: dict) -> pd.DataFrame:
    rows = []
    for k, v in groups.items():
        v = np.asarray(v, float)
        m, lo, hi = mean_ci(v)
        q1, med, q3 = np.percentile(v, [25, 50, 75])
        rows.append({"Group": k, "n": len(v), "Mean": m, "SD": v.std(ddof=1) if len(v) > 1 else np.nan,
                     "SEM": v.std(ddof=1) / math.sqrt(len(v)) if len(v) > 1 else np.nan,
                     "95% CI": f"{lo:.3f} to {hi:.3f}", "Median": med, "IQR": f"{q1:.3f} – {q3:.3f}",
                     "Min": v.min(), "Max": v.max()})
    return pd.DataFrame(rows)
