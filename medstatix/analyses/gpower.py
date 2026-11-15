"""G*Power-style power analysis: a priori (N), post hoc (power) and sensitivity (effect size) for the common test
families, using the same noncentral distributions as G*Power 3 (Faul et al., 2007), with the G*Power distribution
plot (H0 and H1 curves, critical value, α and β) and the power curve."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import optimize, stats

from ..core.result import AnalysisError, Result
from ..plots import figures as F
from .registry import P, register

FAMILIES = ["t: two independent means", "t: paired means / one sample", "F: one-way ANOVA (fixed effects)",
            "F: multiple regression (R² ≠ 0)", "χ²: goodness of fit / contingency table", "Correlation: ρ ≠ 0",
            "z: two independent proportions"]
MODES = ["A priori: compute required sample size", "Post hoc: compute achieved power", "Sensitivity: compute detectable effect size"]
ES_NAME = {0: "d", 1: "dz", 2: "f", 3: "f²", 4: "w", 5: "ρ", 6: "h"}


def _model(fam, es, N, alpha, k, ratio, tails):
    """Return dict(power, crit, ncp, df1, df2, dist) for total sample size N."""
    i = FAMILIES.index(fam)
    a = alpha / tails if i in (0, 1, 5, 6) else alpha
    if i == 0:
        n1 = N / (1 + ratio); n2 = N - n1
        df = n1 + n2 - 2
        if df <= 0:
            return None
        ncp = es * math.sqrt(n1 * n2 / (n1 + n2)); crit = stats.t.ppf(1 - a, df)
        pw = stats.nct.sf(crit, df, ncp) + (stats.nct.cdf(-crit, df, ncp) if tails == 2 else 0)
        return dict(power=pw, crit=crit, ncp=ncp, df1=df, df2=None, dist="t")
    if i == 1:
        df = N - 1
        if df <= 0:
            return None
        ncp = es * math.sqrt(N); crit = stats.t.ppf(1 - a, df)
        pw = stats.nct.sf(crit, df, ncp) + (stats.nct.cdf(-crit, df, ncp) if tails == 2 else 0)
        return dict(power=pw, crit=crit, ncp=ncp, df1=df, df2=None, dist="t")
    if i in (2, 3):
        df1 = (k - 1) if i == 2 else k
        df2 = N - k if i == 2 else N - k - 1
        if df2 <= 0:
            return None
        ncp = (es ** 2 if i == 2 else es) * N
        crit = stats.f.ppf(1 - a, df1, df2)
        return dict(power=stats.ncf.sf(crit, df1, df2, ncp), crit=crit, ncp=ncp, df1=df1, df2=df2, dist="F")
    if i == 4:
        df = k
        ncp = es ** 2 * N; crit = stats.chi2.ppf(1 - a, df)
        return dict(power=stats.ncx2.sf(crit, df, ncp), crit=crit, ncp=ncp, df1=df, df2=None, dist="chi2")
    if i == 5:   # Fisher z approximation
        if N <= 3:
            return None
        ncp = math.atanh(es) * math.sqrt(N - 3); crit = stats.norm.ppf(1 - a)
        pw = stats.norm.sf(crit - ncp) + (stats.norm.cdf(-crit - ncp) if tails == 2 else 0)
        return dict(power=pw, crit=crit, ncp=ncp, df1=None, df2=None, dist="z")
    n1 = N / (1 + ratio); n2 = N - n1
    ncp = es * math.sqrt(n1 * n2 / (n1 + n2)); crit = stats.norm.ppf(1 - a)
    pw = stats.norm.sf(crit - ncp) + (stats.norm.cdf(-crit - ncp) if tails == 2 else 0)
    return dict(power=pw, crit=crit, ncp=ncp, df1=None, df2=None, dist="z")


def _min_n(fam):
    i = FAMILIES.index(fam)
    return {0: 4, 1: 2, 2: 4, 3: 5, 4: 2, 5: 5, 6: 4}[i]


def solve_n(fam, es, alpha, power, k, ratio, tails):
    """Smallest total N reaching the target power (whole subjects; equal groups rounded up like G*Power)."""
    i = FAMILIES.index(fam)
    step = 1
    if i in (0, 6):
        step = 1   # handled by rounding n1 up below
    N = _min_n(fam)
    while N < 100000:
        if i in (0, 6):
            n1 = math.ceil(N / (1 + ratio)); n2 = math.ceil(n1 * ratio); Nt = n1 + n2
        elif i == 2:
            n = math.ceil(N / k); Nt = n * k
        else:
            Nt = N
        m = _model(fam, es, Nt, alpha, k, ratio, tails)
        if m and m["power"] >= power:
            return Nt, m
        N = Nt + step if Nt >= N else N + step
    raise AnalysisError("No sample size below 100 000 reaches this power.")


def solve_es(fam, N, alpha, power, k, ratio, tails):
    hi = 0.999 if FAMILIES.index(fam) == 5 else 5.0

    def f(e):
        pw = _model(fam, e, N, alpha, k, ratio, tails)["power"]
        return (1.0 if not np.isfinite(pw) else pw) - power
    if f(hi) < 0:
        raise AnalysisError("Even a very large effect does not reach this power with this N.")
    return optimize.brentq(f, 1e-6, hi)


def _dist_plot(m, alpha, tails, title):
    with F.styled():
        fig, ax = F.new_figure()
        c0, c1 = "#C0392B", "#1F4E9A"
        if m["dist"] == "t":
            df, ncp = m["df1"], m["ncp"]
            x = np.linspace(min(-4, ncp - 4), max(4, ncp + 4), 600)
            y0, y1 = stats.t.pdf(x, df), stats.nct.pdf(x, df, ncp)
        elif m["dist"] == "F":
            df1, df2, ncp = m["df1"], m["df2"], m["ncp"]
            x = np.linspace(0.001, max(stats.ncf.ppf(0.995, df1, df2, ncp), m["crit"] * 2), 600)
            y0, y1 = stats.f.pdf(x, df1, df2), stats.ncf.pdf(x, df1, df2, ncp)
        elif m["dist"] == "chi2":
            df, ncp = m["df1"], m["ncp"]
            x = np.linspace(0.001, max(stats.ncx2.ppf(0.995, df, ncp), m["crit"] * 2), 600)
            y0, y1 = stats.chi2.pdf(x, df), stats.ncx2.pdf(x, df, ncp)
        else:
            ncp = m["ncp"]
            x = np.linspace(min(-4, ncp - 4), max(4, ncp + 4), 600)
            y0, y1 = stats.norm.pdf(x), stats.norm.pdf(x, ncp)
        ax.plot(x, y0, color=c0, lw=1.8, label="H0")
        ax.plot(x, y1, color=c1, lw=1.8, label="H1")
        cr = m["crit"]
        ax.fill_between(x, 0, y0, where=x >= cr, color=c0, alpha=0.35, label="α")
        ax.fill_between(x, 0, y1, where=x < cr, color=c1, alpha=0.25, label="β")
        if tails == 2 and m["dist"] in ("t", "z"):
            ax.fill_between(x, 0, y0, where=x <= -cr, color=c0, alpha=0.35)
            ax.axvline(-cr, color="#333", lw=0.8, ls="--")
        ax.axvline(cr, color="#333", lw=0.8, ls="--")
        ax.set_title(title + f"   critical = {cr:.3f}")
        ax.set_yticks([]); ax.legend(frameon=False, fontsize=8)
        fig.tight_layout()
    return fig


@register("gpower", "power", "Power analysis (G*Power style: a priori, post hoc, sensitivity)",
          "تحليل القوة الإحصائية على طريقة G*Power (قبل التجربة، بعدها، الحساسية)",
          [P("family", "Test family", "نوع الاختبار", "choice", FAMILIES, FAMILIES[0]),
           P("mode", "Type of power analysis", "نوع التحليل", "choice", MODES, MODES[0]),
           P("effect", "Effect size (d, dz, f, f², w, ρ or h)", "حجم الأثر (d أو f أو w أو ρ أو h)", "float", default=0.5),
           P("alpha", "α error probability", "احتمال خطأ α", "float", default=0.05),
           P("power", "Power (1 − β)", "القوة (1 − β)", "float", default=0.80),
           P("total_n", "Total sample size (post hoc / sensitivity)", "حجم العينة الكلي (بعد التجربة / الحساسية)", "int", default=40),
           P("groups", "Groups (ANOVA) / predictors (regression) / df (χ²)", "عدد المجموعات / المتغيرات المستقلة / درجات الحرية", "int", default=3),
           P("ratio", "Allocation ratio n2/n1", "نسبة التوزيع n2/n1", "float", default=1.0),
           P("tails", "Tails", "الذيول", "choice", ["Two", "One"], "Two")],
          "Same distributions as G*Power 3.1, with the H0/H1 distribution plot and the power curve.",
          "نفس توزيعات G*Power 3.1 مع رسم توزيعي H0 وH1 ومنحنى القوة.", needs_data=False)
def gpower(family=FAMILIES[0], mode=MODES[0], effect=0.5, alpha=0.05, power=0.80, total_n=40, groups=3, ratio=1.0, tails="Two"):
    tl = 2 if tails.startswith("Two") else 1
    k = int(groups); ratio = float(ratio or 1.0)
    i = FAMILIES.index(family)
    esn = ES_NAME[i]
    res = Result("Power analysis (G*Power style)", f"{family} — {mode.split(':')[0]}")
    if mode.startswith("A priori"):
        N, m = solve_n(family, effect, alpha, power, k, ratio, tl)
        es = effect
    elif mode.startswith("Post hoc"):
        N = int(total_n); m = _model(family, effect, N, alpha, k, ratio, tl)
        if m is None:
            raise AnalysisError("Sample size too small for this design.")
        es = effect
    else:
        N = int(total_n); es = solve_es(family, N, alpha, power, k, ratio, tl); m = _model(family, es, N, alpha, k, ratio, tl)
    rows = [("Input: effect size " + esn, es), ("Input: α", alpha)]
    if not mode.startswith("Post hoc"):
        rows.append(("Input: power (1 − β)", power))
    if i == 2:
        rows.append(("Input: number of groups", k))
    if i == 3:
        rows.append(("Input: number of predictors", k))
    if i == 4:
        rows.append(("Input: df", k))
    if i in (0, 6):
        rows.append(("Input: allocation ratio n2/n1", ratio))
    nc_name = {"t": "Noncentrality parameter δ", "F": "Noncentrality parameter λ", "chi2": "Noncentrality parameter λ", "z": "Noncentrality (z)"}[m["dist"]]
    rows += [(nc_name, m["ncp"]), ("Critical " + {"t": "t", "F": "F", "chi2": "χ²", "z": "z"}[m["dist"]], m["crit"])]
    if m["df1"] is not None:
        rows.append(("Numerator df" if m["dist"] == "F" else "df", m["df1"]))
    if m["df2"] is not None:
        rows.append(("Denominator df", m["df2"]))
    if i in (0, 6):
        n1 = round(N / (1 + ratio)); rows += [("Sample size group 1", n1), ("Sample size group 2", N - n1)]
    if i == 2:
        rows.append(("Sample size per group", N / k))
    rows += [("Total sample size", N), ("Actual power", m["power"])]
    res.table(pd.DataFrame(rows, columns=["Output", "Value"]), "G*Power-style output", p_columns=())
    res.figure(_dist_plot(m, alpha, tl, family.split(":")[0] + " tests"), "Central (H0) and noncentral (H1) distributions; "
               "shaded areas are α and β.")
    ns = np.arange(_min_n(family), max(int(N * 2.2), 20))
    pw = [(_model(family, es, n, alpha, k, ratio, tl) or {"power": np.nan})["power"] for n in ns]
    res.figure(F.power_curve(ns, pw, (N, m["power"]), xlabel="Total sample size"), "Power as a function of the total sample size.")
    note = " (Fisher-z approximation; G*Power's exact bivariate-normal test may differ by 1–2 subjects)" if i == 5 else ""
    if mode.startswith("A priori"):
        en = (f"A total sample size of {N} gives {m['power'] * 100:.1f}% power to detect an effect of {esn} = {es:g} "
              f"({family.split(':')[1].strip()}, α = {alpha}, {tails.lower()}-tailed){note}.")
        ar = f"حجم عينة كلي قدره {N} يعطي قوة {m['power'] * 100:.1f}% لاكتشاف أثر {esn} = {es:g} عند α = {alpha}{note}."
    elif mode.startswith("Post hoc"):
        en = f"With N = {N}, the power to detect {esn} = {es:g} at α = {alpha} is {m['power'] * 100:.1f}%{note}."
        ar = f"مع حجم عينة {N} تكون القوة لاكتشاف أثر {esn} = {es:g} عند α = {alpha} هي {m['power'] * 100:.1f}%."
    else:
        en = f"With N = {N}, effects of {esn} ≥ {es:.3f} can be detected with {power * 100:.0f}% power at α = {alpha}{note}."
        ar = f"مع حجم عينة {N} يمكن اكتشاف أثر {esn} ≥ {es:.3f} بقوة {power * 100:.0f}% عند α = {alpha}."
    res.interpret(en, ar)
    res.methods(f"Power analysis ({mode.split(':')[0].lower()}) was performed for the {family.split(':')[1].strip()} with the "
                "noncentral distributions used by G*Power 3.1 (Faul et al., 2007), computed in MedStatix Pro. " + en)
    return res
