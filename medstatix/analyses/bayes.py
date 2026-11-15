"""Bayesian tests (JASP / R BayesFactor-style default Bayes factors).

* t-tests: JZS Bayes factor with a Cauchy prior on the standardised effect (Rouder et al., 2009; default r = √2/2,
  as in R BayesFactor ≥ 0.9.12 and JASP) — validated against BayesFactor::ttestBF.
* Correlation: JZS Bayes factor for Pearson's r (Wetzels & Wagenmakers, 2012).
* One-way ANOVA: BIC approximation to the Bayes factor (Wagenmakers, 2007).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import integrate, special, stats

from ..core.data import _level_order, numeric
from ..core.result import AnalysisError, Result
from ..plots import figures as F
from .registry import P, register

CATS = [(1, "anecdotal", "ضعيف (حكائي)"), (3, "moderate", "متوسط"), (10, "strong", "قوي"), (30, "very strong", "قوي جدًا"),
        (100, "extreme", "حاسم")]


def _category(bf10):
    b = bf10 if bf10 >= 1 else 1 / bf10
    en, ar = "anecdotal", "ضعيف (حكائي)"
    for lim, e, a in CATS:
        if b >= lim:
            en, ar = e, a
    side_en = "for H1 (an effect)" if bf10 >= 1 else "for H0 (no effect)"
    side_ar = "لصالح وجود أثر (H1)" if bf10 >= 1 else "لصالح عدم وجود أثر (H0)"
    return f"{en} evidence {side_en}", f"دليل {ar} {side_ar}"


def jzs_bf_t(t, n_eff, nu, r=math.sqrt(2) / 2):
    """BF10 for a t statistic (Rouder et al. 2009, eq. 1), Cauchy(0, r) prior on δ."""
    def integrand(g):
        a = 1 + n_eff * g * r * r
        return a ** -0.5 * (1 + t * t / (a * nu)) ** (-(nu + 1) / 2) * (2 * math.pi) ** -0.5 * g ** -1.5 * math.exp(-1 / (2 * g))
    num = integrate.quad(integrand, 0, np.inf, limit=200)[0]
    den = (1 + t * t / nu) ** (-(nu + 1) / 2)
    return num / den


def jzs_bf_r(r, n):
    """BF10 for Pearson's r (Wetzels & Wagenmakers 2012, eq. 13)."""
    def integrand(g):
        return (1 + g) ** ((n - 2) / 2) * (1 + (1 - r * r) * g) ** (-(n - 1) / 2) * g ** -1.5 * math.exp(-n / (2 * g))
    val = integrate.quad(integrand, 0, np.inf, limit=200)[0]
    return math.sqrt(n / 2) / special.gamma(0.5) * val


def _robustness(fn):
    rs = np.linspace(0.1, 1.5, 40)
    return rs, [fn(r) for r in rs]


def _bf_plot(rs, bfs, r0, title):
    with F.styled():
        fig, ax = F.new_figure()
        ax.plot(rs, bfs, color=F.palette(1)[0], lw=2)
        ax.axvline(r0, color="#888", ls="--", lw=1)
        ax.axhline(1, color="#444", lw=0.8)
        for lim in (3, 10, 1 / 3, 1 / 10):
            ax.axhline(lim, color="#BBB", lw=0.6, ls=":")
        ax.set_yscale("log")
        ax.set_xlabel("Cauchy prior width r"); ax.set_ylabel("BF₁₀ (log scale)"); ax.set_title(title)
        fig.tight_layout()
    return fig


@register("bayes_t", "bayes", "Bayesian t-test (independent, paired or one-sample)", "اختبار t البايزي (مستقل، مزدوج، عينة واحدة)",
          [P("design", "Design", "التصميم", "choice", ["Independent groups", "Paired", "One sample"], "Independent groups"),
           P("outcome", "Outcome / measurement 1", "المتغير التابع / القياس الأول", "var_num"),
           P("group", "Grouping variable (independent design)", "متغير المجموعات (للتصميم المستقل)", "var_cat", optional=True),
           P("var2", "Measurement 2 (paired design)", "القياس الثاني (للتصميم المزدوج)", "var_num", optional=True),
           P("mu", "Test value (one sample)", "القيمة المرجعية (عينة واحدة)", "float", default=0.0),
           P("prior_r", "Prior width r (default √2/2 = 0.707)", "عرض التوزيع المسبق r", "float", default=0.707)],
          "Default JZS Bayes factor (JASP / BayesFactor) with a robustness check over prior widths.",
          "معامل بايز (JZS) كما في JASP مع فحص ثبات النتيجة لعرض التوزيع المسبق.")
def bayes_t(df, design="Independent groups", outcome=None, group=None, var2=None, mu=0.0, prior_r=0.707):
    if design.startswith("Independent"):
        if not group:
            raise AnalysisError("Choose the grouping variable.")
        lv = _level_order(df[group].dropna())
        if len(lv) != 2:
            raise AnalysisError(f"'{group}' must have exactly 2 groups (found {len(lv)}).")
        y = numeric(df, outcome)
        a, b = y[df[group] == lv[0]].dropna().values, y[df[group] == lv[1]].dropna().values
        t = stats.ttest_ind(a, b).statistic
        n1, n2 = len(a), len(b); n_eff, nu = n1 * n2 / (n1 + n2), n1 + n2 - 2
        sp = math.sqrt(((n1 - 1) * a.var(ddof=1) + (n2 - 1) * b.var(ddof=1)) / nu)
        d = (a.mean() - b.mean()) / sp
        sub = f"{outcome}: {lv[0]} vs {lv[1]}"
        desc = pd.DataFrame([{"Group": lv[0], "n": n1, "Mean": a.mean(), "SD": a.std(ddof=1)},
                             {"Group": lv[1], "n": n2, "Mean": b.mean(), "SD": b.std(ddof=1)}])
    elif design.startswith("Paired"):
        if not var2:
            raise AnalysisError("Choose measurement 2.")
        d2 = df[[outcome, var2]].apply(pd.to_numeric, errors="coerce").dropna()
        diff = (d2[outcome] - d2[var2]).values
        n = len(diff); t = stats.ttest_1samp(diff, 0).statistic; n_eff, nu = n, n - 1
        d = diff.mean() / diff.std(ddof=1)
        sub = f"{outcome} − {var2} (paired)"
        desc = pd.DataFrame([{"Measure": c, "n": n, "Mean": d2[c].mean(), "SD": d2[c].std(ddof=1)} for c in (outcome, var2)])
    else:
        x = numeric(df, outcome).dropna().values
        n = len(x); t = stats.ttest_1samp(x, mu).statistic; n_eff, nu = n, n - 1
        d = (x.mean() - mu) / x.std(ddof=1)
        sub = f"{outcome} vs {mu}"
        desc = pd.DataFrame([{"Variable": outcome, "n": n, "Mean": x.mean(), "SD": x.std(ddof=1)}])
    bf = jzs_bf_t(t, n_eff, nu, prior_r)
    res = Result("Bayesian t-test", sub)
    res.table(desc, "Descriptive statistics")
    cat_en, cat_ar = _category(bf)
    res.table(pd.DataFrame([{"t": t, "df": nu, "Cohen's d": d, "Prior": f"Cauchy(0, {prior_r:g})", "BF₁₀": bf, "BF₀₁": 1 / bf,
                             "log(BF₁₀)": math.log(bf), "Evidence": cat_en}]), "Bayes factor",
              "BF₁₀ > 1 favours an effect, < 1 favours no effect. 1–3 anecdotal, 3–10 moderate, 10–30 strong, 30–100 very "
              "strong, > 100 extreme (Lee & Wagenmakers 2013).", p_columns=())
    rs, bfs = _robustness(lambda r: jzs_bf_t(t, n_eff, nu, r))
    res.table(pd.DataFrame([{"Prior width": "medium (0.707)", "BF₁₀": jzs_bf_t(t, n_eff, nu, 0.707)},
                            {"Prior width": "wide (1.0)", "BF₁₀": jzs_bf_t(t, n_eff, nu, 1.0)},
                            {"Prior width": "ultrawide (1.414)", "BF₁₀": jzs_bf_t(t, n_eff, nu, 1.414)}]),
              "Robustness check", p_columns=())
    res.figure(_bf_plot(rs, bfs, prior_r, "Bayes factor robustness"), "Bayes factor as a function of the prior width.")
    res.interpret(f"The data are {bf:.2f} times more likely under H1 than under H0 (BF₁₀ = {bf:.2f}): {cat_en}.",
                  f"البيانات أرجح بمقدار {bf:.2f} مرة تحت فرض وجود أثر مقارنة بعدم وجوده (BF₁₀ = {bf:.2f}): {cat_ar}.")
    res.methods(f"A Bayesian {design.lower()} t-test was performed with the default JZS prior (Cauchy scale r = {prior_r:g}; "
                "Rouder et al., 2009). Bayes factors were interpreted following Lee and Wagenmakers (2013), and their robustness "
                "to the prior width was checked.")
    return res


@register("bayes_corr", "bayes", "Bayesian correlation (Pearson)", "الارتباط البايزي (بيرسون)",
          [P("x", "Variable X", "المتغير X", "var_num"), P("y", "Variable Y", "المتغير Y", "var_num")],
          "Default JZS Bayes factor for a Pearson correlation.", "معامل بايز لارتباط بيرسون.")
def bayes_corr(df, x, y):
    d = df[[x, y]].apply(pd.to_numeric, errors="coerce").dropna()
    n = len(d)
    if n < 4:
        raise AnalysisError("At least 4 complete pairs are needed.")
    r, p = stats.pearsonr(d[x], d[y])
    bf = jzs_bf_r(r, n)
    cat_en, cat_ar = _category(bf)
    res = Result("Bayesian correlation", f"{x} and {y}")
    res.table(pd.DataFrame([{"n": n, "Pearson r": r, "BF₁₀": bf, "BF₀₁": 1 / bf, "Evidence": cat_en}]), "Bayes factor", p_columns=())
    with F.styled():
        fig, ax = F.new_figure()
        ax.scatter(d[x], d[y], color=F.palette(1)[0], s=22)
        ax.set_xlabel(x); ax.set_ylabel(y); ax.set_title(f"r = {r:.2f}, BF₁₀ = {bf:.2f}")
        fig.tight_layout()
    res.figure(fig, "Scatter plot.")
    res.interpret(f"r = {r:.2f}; BF₁₀ = {bf:.2f}: {cat_en}.", f"r = {r:.2f}؛ BF₁₀ = {bf:.2f}: {cat_ar}.")
    res.methods("A Bayesian Pearson correlation was computed with the JZS Bayes factor (Wetzels & Wagenmakers, 2012).")
    return res


@register("bayes_anova", "bayes", "Bayesian one-way ANOVA (BIC approximation)", "تحليل التباين البايزي (تقريب BIC)",
          [P("outcome", "Outcome", "المتغير التابع", "var_num"), P("group", "Groups", "المجموعات", "var_cat")],
          "Bayes factor for a group effect from the BIC of the null and the one-way model.",
          "معامل بايز لتأثير المجموعات من معيار BIC.")
def bayes_anova(df, outcome, group):
    d = pd.DataFrame({"y": numeric(df, outcome), "g": df[group]}).dropna()
    k = d.g.nunique(); n = len(d)
    if k < 2:
        raise AnalysisError("At least 2 groups are needed.")
    rss0 = ((d.y - d.y.mean()) ** 2).sum()
    rss1 = sum(((s - s.mean()) ** 2).sum() for _, s in d.groupby("g").y)
    bic0 = n * math.log(rss0 / n) + 1 * math.log(n)
    bic1 = n * math.log(rss1 / n) + k * math.log(n)
    bf = math.exp((bic0 - bic1) / 2)
    cat_en, cat_ar = _category(bf)
    F_ = ((rss0 - rss1) / (k - 1)) / (rss1 / (n - k))
    res = Result("Bayesian one-way ANOVA", f"{outcome} by {group}")
    res.table(pd.DataFrame([{"Groups": k, "N": n, "F": F_, "η²": 1 - rss1 / rss0, "BF₁₀ (BIC)": bf, "BF₀₁": 1 / bf,
                             "Evidence": cat_en}]), "Bayes factor",
              "BIC approximation with unit-information prior (Wagenmakers 2007); JASP's default Bayesian ANOVA uses "
              "JZS priors and can give somewhat different values.", p_columns=())
    res.interpret(f"BF₁₀ = {bf:.2f}: {cat_en}.", f"BF₁₀ = {bf:.2f}: {cat_ar}.")
    res.methods("The Bayes factor for the group effect was approximated from the BIC of the null and one-way models (Wagenmakers, 2007).")
    return res
