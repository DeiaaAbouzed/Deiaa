"""Comparison of groups: t-tests, non-parametric tests, ANOVA family with post hoc tests."""
from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats

from ..core.data import group_arrays, numeric, _level_order
from ..core.result import Result, AnalysisError, fmt_p
from ..plots import figures as F
from .common import (cohen_d_ind, describe_groups, magnitude_d, magnitude_eta, magnitude_r, mean_ci,
                     normality_check, p_adjust, pstr, sig_words)
from .registry import register, P, ALT, POSTHOC, P_ADJ


def _two_groups(df, outcome, group):
    g = group_arrays(df, outcome, group)
    if len(g) != 2:
        raise AnalysisError(f"'{group}' must have exactly 2 groups (found {len(g)}). Use one-way ANOVA for more.")
    return g


# ---------------------------------------------------------------------------
@register("ttest_ind", "compare", "Independent-samples t-test (Student / Welch)", "اختبار t لعينتين مستقلتين",
          [P("outcome", "Outcome (continuous)", "المتغير التابع (كمي)", "var_num"),
           P("group", "Grouping variable (2 groups)", "متغير المجموعات (مجموعتان)", "var_cat"),
           P("alternative", "Alternative hypothesis", "الفرض البديل", "choice", ALT, "two-sided")],
          "Levene's test, Student and Welch t-tests, mean difference with 95% CI, Cohen's d and Hedges' g.",
          "اختبار ليفين وt لستيودنت وويلش وفرق المتوسطات مع فترة الثقة وحجم الأثر كوهين d.")
def ttest_ind(df, outcome, group, alternative="two-sided"):
    g = _two_groups(df, outcome, group)
    (n1, a), (n2, b) = g.items()
    res = Result("Independent-samples t-test", f"{outcome} by {group}")
    res.table(describe_groups(g), "Group statistics")
    lev = stats.levene(a, b, center="median")
    norm, all_normal = normality_check(g)
    st = stats.ttest_ind(a, b, equal_var=True, alternative=alternative)
    we = stats.ttest_ind(a, b, equal_var=False, alternative=alternative)
    diff = a.mean() - b.mean()
    ci_s = st.confidence_interval(0.95)
    ci_w = we.confidence_interval(0.95)
    se_s = math.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(a) + len(b) - 2) * (1 / len(a) + 1 / len(b)))
    se_w = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    tab = pd.DataFrame([
        {"Test": "Student (equal variances)", "t": st.statistic, "df": st.df, "p": st.pvalue,
         "Mean diff.": diff, "SE diff.": se_s, "95% CI lower": ci_s.low, "95% CI upper": ci_s.high},
        {"Test": "Welch (unequal variances)", "t": we.statistic, "df": we.df, "p": we.pvalue,
         "Mean diff.": diff, "SE diff.": se_w, "95% CI lower": ci_w.low, "95% CI upper": ci_w.high},
    ])
    res.table(tab, f"t-test results ({alternative})", f"Mean difference = {n1} − {n2}. Levene's test (median-centred, "
              f"Brown-Forsythe): F = {lev.statistic:.3f}, {pstr(lev.pvalue)}.")
    d, gH, dlo, dhi = cohen_d_ind(a, b)
    res.table(pd.DataFrame([{"Effect size": "Cohen's d", "Estimate": d, "95% CI lower": dlo, "95% CI upper": dhi},
                            {"Effect size": "Hedges' g", "Estimate": gH, "95% CI lower": np.nan, "95% CI upper": np.nan}]),
              "Effect size")
    res.table(norm, "Assumption check — normality (Shapiro-Wilk)")
    use = we  # Welch is the recommended default
    mag = magnitude_d(d)
    sw = sig_words(use.pvalue)
    en = (f"Welch's t-test (recommended default; does not assume equal variances) shows the difference between {n1} "
          f"(mean {a.mean():.2f} ± {a.std(ddof=1):.2f}) and {n2} (mean {b.mean():.2f} ± {b.std(ddof=1):.2f}) is {sw[0]} "
          f"(t({we.df:.1f}) = {we.statistic:.2f}, {pstr(we.pvalue)}; mean difference {diff:.2f}, 95% CI {ci_w.low:.2f} to {ci_w.high:.2f}). "
          f"The effect size is {mag[0]} (Cohen's d = {d:.2f}).")
    ar = (f"أظهر اختبار t لويلش (الاختيار الافتراضي الموصى به) أن الفرق بين {n1} ({a.mean():.2f} ± {a.std(ddof=1):.2f}) و{n2} "
          f"({b.mean():.2f} ± {b.std(ddof=1):.2f}) {sw[1]} (t = {we.statistic:.2f}، {pstr(we.pvalue)}؛ فرق المتوسطات {diff:.2f}، "
          f"فترة الثقة 95%: {ci_w.low:.2f} إلى {ci_w.high:.2f}). حجم الأثر {mag[1]} (d = {d:.2f}).")
    if not all_normal:
        en += " Note: normality is doubtful in at least one group; confirm with the Mann-Whitney U test."
        ar += " ملاحظة: التوزيع الطبيعي مشكوك فيه في إحدى المجموعات؛ أكّد النتيجة باختبار مان-ويتني."
    res.interpret(en, ar)
    res.methods(f"Data are presented as mean ± SD. The difference in {outcome} between groups was assessed with Welch's "
                f"unequal-variances t-test; Cohen's d was computed as the standardized effect size. Normality was checked with the "
                f"Shapiro-Wilk test and homogeneity of variance with Levene's test. {n1} vs {n2}: t({we.df:.1f}) = {we.statistic:.2f}, "
                f"{pstr(we.pvalue)}, mean difference = {diff:.2f} (95% CI {ci_w.low:.2f} to {ci_w.high:.2f}), d = {d:.2f}.")
    res.figure_auto(F.group_plot(g, ylabel=outcome, xlabel=group, comparisons=[(n1, n2, we.pvalue)],
                                 test_name=f"Welch's t-test ({pstr(we.pvalue)})"))
    return res


@register("ttest_paired", "compare", "Paired t-test", "اختبار t للعينات المزدوجة",
          [P("var1", "Measurement 1 (e.g. before)", "القياس الأول (قبل)", "var_num"),
           P("var2", "Measurement 2 (e.g. after)", "القياس الثاني (بعد)", "var_num"),
           P("alternative", "Alternative hypothesis", "الفرض البديل", "choice", ALT, "two-sided")],
          "Paired t-test with mean difference CI and Cohen's dz.", "اختبار t المزدوج مع فترة الثقة لفرق المتوسطات و dz.")
def ttest_paired(df, var1, var2, alternative="two-sided"):
    d = pd.DataFrame({"a": numeric(df, var1), "b": numeric(df, var2)}).dropna()
    if len(d) < 3:
        raise AnalysisError("Need at least 3 complete pairs.")
    a, b = d.a.to_numpy(), d.b.to_numpy()
    diff = a - b
    r = stats.ttest_rel(a, b, alternative=alternative)
    ci = r.confidence_interval(0.95)
    dz = diff.mean() / diff.std(ddof=1)
    rr = stats.pearsonr(a, b)[0]
    res = Result("Paired-samples t-test", f"{var1} vs {var2} (n = {len(d)} pairs)")
    res.table(describe_groups({var1: a, var2: b}), "Paired samples statistics")
    res.table(pd.DataFrame([{"Pair": f"{var1} − {var2}", "Mean diff.": diff.mean(), "SD diff.": diff.std(ddof=1),
                             "SE": diff.std(ddof=1) / math.sqrt(len(diff)), "95% CI lower": ci.low, "95% CI upper": ci.high,
                             "t": r.statistic, "df": r.df, "p": r.pvalue, "Cohen's dz": dz, "r (pairs)": rr}]),
              f"Paired t-test ({alternative})")
    sw = stats.shapiro(diff) if len(diff) >= 3 else (np.nan, np.nan)
    res.note(f"Normality of differences (Shapiro-Wilk): W = {sw[0]:.3f}, {pstr(sw[1])}.")
    s = sig_words(r.pvalue)
    res.interpret(f"The mean change ({var1} − {var2}) was {diff.mean():.2f} (95% CI {ci.low:.2f} to {ci.high:.2f}), {s[0]} "
                  f"(t({r.df}) = {r.statistic:.2f}, {pstr(r.pvalue)}); effect size dz = {dz:.2f} ({magnitude_d(dz)[0]})."
                  + (" Differences are not normal — confirm with Wilcoxon signed-rank." if sw[1] < 0.05 else ""),
                  f"بلغ متوسط التغير ({var1} − {var2}) {diff.mean():.2f} (فترة الثقة 95%: {ci.low:.2f} إلى {ci.high:.2f})، وهو {s[1]} "
                  f"({pstr(r.pvalue)})؛ حجم الأثر dz = {dz:.2f} ({magnitude_d(dz)[1]})."
                  + (" الفروق غير طبيعية التوزيع — أكّد باختبار ويلكوكسون." if sw[1] < 0.05 else ""))
    res.methods(f"Paired measurements were compared with a two-tailed paired t-test. Mean difference = {diff.mean():.2f} "
                f"(95% CI {ci.low:.2f} to {ci.high:.2f}), t({r.df}) = {r.statistic:.2f}, {pstr(r.pvalue)}, dz = {dz:.2f}.")
    res.figure_auto(F.group_plot({var1: a, var2: b}, ylabel="Value", comparisons=[(var1, var2, r.pvalue)], paired=True,
                                 test_name=f"paired t-test ({pstr(r.pvalue)}); lines join the same subject"))
    return res


@register("ttest_one", "compare", "One-sample t-test", "اختبار t لعينة واحدة",
          [P("variable", "Variable", "المتغير", "var_num"),
           P("mu", "Test value (μ0)", "القيمة المرجعية", "float", default=0.0),
           P("alternative", "Alternative hypothesis", "الفرض البديل", "choice", ALT, "two-sided")],
          "Compare a mean with a reference value.", "مقارنة المتوسط بقيمة مرجعية.")
def ttest_one(df, variable, mu=0.0, alternative="two-sided"):
    x = numeric(df, variable).dropna().to_numpy()
    r = stats.ttest_1samp(x, mu, alternative=alternative)
    ci = r.confidence_interval(0.95)
    d = (x.mean() - mu) / x.std(ddof=1)
    w = stats.wilcoxon(x - mu) if np.any(x != mu) else None
    res = Result("One-sample t-test", f"{variable} vs μ0 = {mu}")
    res.table(pd.DataFrame([{"n": len(x), "Mean": x.mean(), "SD": x.std(ddof=1), "Test value": mu,
                             "Mean diff.": x.mean() - mu, "95% CI lower": ci.low + 0 if False else ci.low - mu,
                             "95% CI upper": ci.high - mu, "t": r.statistic, "df": r.df, "p": r.pvalue, "Cohen's d": d,
                             "Wilcoxon p": w.pvalue if w else np.nan}]), "One-sample test",
              "CI is for the difference from the test value. Wilcoxon signed-rank shown as the non-parametric alternative.",
              p_columns=("p", "Wilcoxon p"))
    s = sig_words(r.pvalue)
    res.interpret(f"The mean of {variable} ({x.mean():.2f}) differs from {mu} by {x.mean() - mu:.2f}; this is {s[0]} ({pstr(r.pvalue)}).",
                  f"متوسط {variable} ({x.mean():.2f}) يختلف عن {mu} بمقدار {x.mean() - mu:.2f}؛ والفرق {s[1]} ({pstr(r.pvalue)}).")
    return res


# ---------------------------------------------------------------------------
@register("mannwhitney", "compare", "Mann-Whitney U test", "اختبار مان-ويتني",
          [P("outcome", "Outcome", "المتغير التابع", "var_num"),
           P("group", "Grouping variable (2 groups)", "متغير المجموعات (مجموعتان)", "var_cat"),
           P("alternative", "Alternative hypothesis", "الفرض البديل", "choice", ALT, "two-sided")],
          "Non-parametric comparison of two independent groups with rank-biserial r and Hodges-Lehmann shift.",
          "مقارنة لامعلمية بين مجموعتين مستقلتين مع حجم الأثر وتقدير هودجز-ليمان.")
def mannwhitney(df, outcome, group, alternative="two-sided"):
    g = _two_groups(df, outcome, group)
    (n1, a), (n2, b) = g.items()
    r = stats.mannwhitneyu(a, b, alternative=alternative, method="auto")
    U = r.statistic
    nA, nB = len(a), len(b)
    rbc = 1 - 2 * min(U, nA * nB - U) / (nA * nB)
    rbc = rbc if U > nA * nB / 2 else -rbc
    # z (normal approx with tie correction)
    allv = np.concatenate([a, b])
    _, t = np.unique(allv, return_counts=True)
    N = nA + nB
    sigma = math.sqrt(nA * nB / 12 * ((N + 1) - np.sum(t ** 3 - t) / (N * (N - 1))))
    z = (U - nA * nB / 2) / sigma if sigma > 0 else np.nan
    hl = np.median(np.subtract.outer(a, b))
    res = Result("Mann-Whitney U test", f"{outcome} by {group}")
    ranks = stats.rankdata(allv)
    desc = describe_groups(g)[["Group", "n", "Median", "IQR"]]
    desc["Mean rank"] = [ranks[:nA].mean(), ranks[nA:].mean()]
    res.table(desc, "Group statistics")
    res.table(pd.DataFrame([{"U": U, "Z": z, "p": r.pvalue, "Rank-biserial r": rbc, "r = |Z|/√N": abs(z) / math.sqrt(N),
                             "Hodges-Lehmann shift": hl}]), f"Mann-Whitney U ({alternative})",
              "Exact p used for small samples without ties; otherwise normal approximation with tie correction.")
    s = sig_words(r.pvalue)
    res.interpret(f"Median {outcome} was {np.median(a):.2f} in {n1} vs {np.median(b):.2f} in {n2}; the difference is {s[0]} "
                  f"(U = {U:.1f}, {pstr(r.pvalue)}), with a {magnitude_r(rbc)[0]} effect (rank-biserial r = {rbc:.2f}).",
                  f"بلغ الوسيط {np.median(a):.2f} في {n1} مقابل {np.median(b):.2f} في {n2}؛ والفرق {s[1]} "
                  f"(U = {U:.1f}، {pstr(r.pvalue)}) بحجم أثر {magnitude_r(rbc)[1]} (r = {rbc:.2f}).")
    res.methods(f"Because {outcome} was not normally distributed, groups were compared with the two-tailed Mann-Whitney U test; "
                f"data are presented as median (IQR). U = {U:.1f}, {pstr(r.pvalue)}, rank-biserial r = {rbc:.2f}.")
    res.figure_auto(F.group_plot(g, ylabel=outcome, xlabel=group, comparisons=[(n1, n2, r.pvalue)], plot_type="Box + points",
                                 center="median", test_name=f"Mann-Whitney U test ({pstr(r.pvalue)})"))
    return res


@register("wilcoxon", "compare", "Wilcoxon signed-rank test", "اختبار ويلكوكسون للرتب المزدوجة",
          [P("var1", "Measurement 1", "القياس الأول", "var_num"), P("var2", "Measurement 2", "القياس الثاني", "var_num"),
           P("alternative", "Alternative hypothesis", "الفرض البديل", "choice", ALT, "two-sided")],
          "Non-parametric paired comparison.", "مقارنة لامعلمية للبيانات المزدوجة.")
def wilcoxon(df, var1, var2, alternative="two-sided"):
    d = pd.DataFrame({"a": numeric(df, var1), "b": numeric(df, var2)}).dropna()
    a, b = d.a.to_numpy(), d.b.to_numpy()
    r = stats.wilcoxon(a, b, alternative=alternative, zero_method="wilcox", method="auto")
    diff = a - b
    nz = diff[diff != 0]
    n = len(nz)
    W = r.statistic
    mu = n * (n + 1) / 4
    _, t = np.unique(np.abs(nz), return_counts=True)
    sigma = math.sqrt(n * (n + 1) * (2 * n + 1) / 24 - np.sum(t ** 3 - t) / 48)
    z = (W - mu) / sigma if sigma else np.nan
    ranks = stats.rankdata(np.abs(nz))
    rpos, rneg = ranks[nz > 0].sum(), ranks[nz < 0].sum()
    rbc = (rpos - rneg) / (rpos + rneg) if (rpos + rneg) else np.nan
    res = Result("Wilcoxon signed-rank test", f"{var1} vs {var2} (n = {len(d)} pairs)")
    res.table(describe_groups({var1: a, var2: b})[["Group", "n", "Median", "IQR"]], "Paired statistics")
    res.table(pd.DataFrame([{"W (smaller rank sum)": W, "Z": z, "p": r.pvalue, "Matched-pairs rank-biserial r": rbc,
                             "Median difference": np.median(diff), "Positive ranks": int((nz > 0).sum()),
                             "Negative ranks": int((nz < 0).sum()), "Ties": int((diff == 0).sum())}]),
              f"Wilcoxon signed-rank ({alternative})")
    s = sig_words(r.pvalue)
    res.interpret(f"The median paired difference was {np.median(diff):.2f}; the change is {s[0]} ({pstr(r.pvalue)}), effect r = {rbc:.2f}.",
                  f"بلغ وسيط الفرق المزدوج {np.median(diff):.2f}؛ والتغير {s[1]} ({pstr(r.pvalue)})، حجم الأثر r = {rbc:.2f}.")
    res.figure_auto(F.group_plot({var1: a, var2: b}, ylabel="Value", comparisons=[(var1, var2, r.pvalue)], paired=True,
                                 plot_type="Box + points", center="median", test_name="Wilcoxon signed-rank test; lines join the same subject"))
    return res


# ---------------------------------------------------------------------------
def games_howell(groups: dict):
    labels = list(groups)
    rows = []
    k = len(labels)
    for i, j in itertools.combinations(range(k), 2):
        a, b = groups[labels[i]], groups[labels[j]]
        na, nb = len(a), len(b)
        va, vb = a.var(ddof=1) / na, b.var(ddof=1) / nb
        diff = a.mean() - b.mean()
        se = math.sqrt(va + vb)
        dfw = (va + vb) ** 2 / (va ** 2 / (na - 1) + vb ** 2 / (nb - 1))
        q = abs(diff) / (se / math.sqrt(2))
        p = stats.studentized_range.sf(q, k, dfw)
        qcrit = stats.studentized_range.ppf(0.95, k, dfw)
        h = qcrit * se / math.sqrt(2)
        rows.append((labels[i], labels[j], diff, se, diff - h, diff + h, p))
    return rows


def pairwise_pooled(groups: dict, mse, df_err, method):
    labels = list(groups)
    raw = []
    for i, j in itertools.combinations(range(len(labels)), 2):
        a, b = groups[labels[i]], groups[labels[j]]
        diff = a.mean() - b.mean()
        se = math.sqrt(mse * (1 / len(a) + 1 / len(b)))
        t = diff / se
        p = 2 * stats.t.sf(abs(t), df_err)
        raw.append([labels[i], labels[j], diff, se, t, p])
    m = len(raw)
    padj = p_adjust([r[5] for r in raw], {"Fisher LSD": "None"}.get(method, method))
    # simultaneous CIs for Bonferroni/Šidák; unadjusted for others
    if method == "Bonferroni":
        crit = stats.t.ppf(1 - 0.05 / (2 * m), df_err)
    elif method == "Šidák":
        crit = stats.t.ppf(1 - (1 - (0.95) ** (1 / m)) / 2, df_err)
    else:
        crit = stats.t.ppf(0.975, df_err)
    return [(r[0], r[1], r[2], r[3], r[2] - crit * r[3], r[2] + crit * r[3], pa) for r, pa in zip(raw, padj)]


def posthoc_table(groups: dict, method: str, mse=None, df_err=None):
    labels = list(groups)
    arrs = [groups[l] for l in labels]
    if method == "Tukey HSD":
        r = stats.tukey_hsd(*arrs)
        ci = r.confidence_interval(0.95)
        rows = []
        for i, j in itertools.combinations(range(len(labels)), 2):
            diff = arrs[i].mean() - arrs[j].mean()
            se = math.sqrt(mse / 2 * (1 / len(arrs[i]) + 1 / len(arrs[j]))) * math.sqrt(2) if mse else np.nan
            rows.append((labels[i], labels[j], diff, se, ci.low[i, j], ci.high[i, j], r.pvalue[i, j]))
    elif method.startswith("Dunnett"):
        ctrl = arrs[0]
        r = stats.dunnett(*arrs[1:], control=ctrl)
        ci = r.confidence_interval(0.95)
        rows = []
        for j in range(1, len(labels)):
            diff = arrs[j].mean() - ctrl.mean()
            se = math.sqrt(mse * (1 / len(arrs[j]) + 1 / len(ctrl))) if mse else np.nan
            rows.append((labels[j], labels[0], diff, se, ci.low[j - 1], ci.high[j - 1], r.pvalue[j - 1]))
    elif method == "Games-Howell":
        rows = games_howell(groups)
    elif method == "None":
        return pd.DataFrame(), []
    else:
        rows = pairwise_pooled(groups, mse, df_err, method)
    tab = pd.DataFrame(rows, columns=["Group A", "Group B", "Mean diff. (A−B)", "SE", "95% CI lower", "95% CI upper", "p (adj.)"])
    tab["Summary"] = [("****" if p < 1e-4 else "***" if p < 1e-3 else "**" if p < 0.01 else "*" if p < 0.05 else "ns")
                      for p in tab["p (adj.)"]]
    comps = [(r[0], r[1], r[6]) for r in rows if r[6] < 0.05]
    tab.attrs["all_pairs"] = [(r[0], r[1], r[6]) for r in rows]
    return tab, comps


@register("anova1", "compare", "One-way ANOVA + post hoc", "تحليل التباين الأحادي مع الاختبارات البعدية",
          [P("outcome", "Outcome (continuous)", "المتغير التابع (كمي)", "var_num"),
           P("group", "Factor (≥ 3 groups)", "العامل (3 مجموعات أو أكثر)", "var_cat"),
           P("posthoc", "Post hoc test", "الاختبار البعدي", "choice", POSTHOC, "Tukey HSD")],
          "Classic and Welch ANOVA, Levene, η²/ω² with Tukey, Bonferroni, Holm, Šidák, Dunnett, Games-Howell or LSD.",
          "تحليل التباين الكلاسيكي وويلش مع اختبار ليفين وحجم الأثر والاختبارات البعدية (توكي، بونفيروني، دانيت، جيمس-هاول...).")
def anova1(df, outcome, group, posthoc="Tukey HSD"):
    g = group_arrays(df, outcome, group)
    if len(g) < 2:
        raise AnalysisError("Need at least 2 groups.")
    labels = list(g)
    arrs = [g[l] for l in labels]
    N = sum(len(a) for a in arrs)
    k = len(arrs)
    grand = np.concatenate(arrs).mean()
    ssb = sum(len(a) * (a.mean() - grand) ** 2 for a in arrs)
    ssw = sum(((a - a.mean()) ** 2).sum() for a in arrs)
    dfb, dfw = k - 1, N - k
    msb, msw = ssb / dfb, ssw / dfw
    Fv = msb / msw
    p = stats.f.sf(Fv, dfb, dfw)
    eta2 = ssb / (ssb + ssw)
    omega2 = (ssb - dfb * msw) / (ssb + ssw + msw)
    res = Result("One-way ANOVA", f"{outcome} by {group} ({k} groups, N = {N})")
    res.table(describe_groups(g), "Descriptive statistics")
    res.table(pd.DataFrame([
        {"Source": "Between groups", "SS": ssb, "df": dfb, "MS": msb, "F": Fv, "p": p},
        {"Source": "Within groups", "SS": ssw, "df": dfw, "MS": msw, "F": np.nan, "p": np.nan},
        {"Source": "Total", "SS": ssb + ssw, "df": N - 1, "MS": np.nan, "F": np.nan, "p": np.nan}]),
        "ANOVA table", f"η² = {eta2:.3f}; ω² = {omega2:.3f}.")
    # Welch & Brown-Forsythe ANOVA
    w = np.array([len(a) / a.var(ddof=1) for a in arrs])
    means = np.array([a.mean() for a in arrs])
    mw = (w * means).sum() / w.sum()
    A = (w * (means - mw) ** 2).sum() / (k - 1)
    lam = ((1 - w / w.sum()) ** 2 / np.array([len(a) - 1 for a in arrs])).sum()
    B = 1 + 2 * (k - 2) / (k ** 2 - 1) * lam
    Fw = A / B
    df2w = (k ** 2 - 1) / (3 * lam)
    pw = stats.f.sf(Fw, k - 1, df2w)
    lev = stats.levene(*arrs, center="median")
    bart = stats.bartlett(*arrs)
    norm, all_normal = normality_check(g)
    if len(g) >= 3:   # ANOVA assumption = normal residuals (pooled); per-group tests over-flag with many groups
        _res = np.concatenate([a - a.mean() for a in g.values()])
        if len(_res) >= 3:
            all_normal = stats.shapiro(_res)[1] >= 0.05 if len(_res) <= 5000 else stats.normaltest(_res)[1] >= 0.05
    res.table(pd.DataFrame([
        {"Test": "Welch ANOVA", "Statistic": Fw, "df1": k - 1, "df2": df2w, "p": pw},
        {"Test": "Levene (Brown-Forsythe, median)", "Statistic": lev.statistic, "df1": k - 1, "df2": N - k, "p": lev.pvalue},
        {"Test": "Bartlett", "Statistic": bart.statistic, "df1": k - 1, "df2": np.nan, "p": bart.pvalue}]),
        "Robust test and homogeneity of variance")
    res.table(norm, "Normality per group (Shapiro-Wilk)")
    method = posthoc
    if lev.pvalue < 0.05 and posthoc == "Tukey HSD":
        res.warning("Variances are unequal (Levene p < 0.05): Games-Howell is more appropriate than Tukey; it is shown below as well.")
    tab, comps = posthoc_table(g, method, msw, dfw)
    if len(tab):
        res.table(tab, f"Multiple comparisons — {method}", p_columns=("p (adj.)",))
    if lev.pvalue < 0.05 and posthoc == "Tukey HSD":
        tab2, comps = posthoc_table(g, "Games-Howell")
        res.table(tab2, "Multiple comparisons — Games-Howell (unequal variances)", p_columns=("p (adj.)",))
    mainp = pw if lev.pvalue < 0.05 else p
    s = sig_words(mainp)
    mag = magnitude_eta(eta2)
    sig_pairs = [f"{a} vs {b}" for a, b, _ in comps]
    en = (f"{'Welch' if lev.pvalue < 0.05 else 'One-way'} ANOVA indicates that {outcome} differs among the {k} groups: {s[0]} "
          f"(F({dfb}, {dfw}) = {Fv:.2f}, {pstr(p)}; Welch {pstr(pw)}). η² = {eta2:.3f} ({mag[0]} effect: "
          f"{eta2*100:.1f}% of variance explained by {group}). ")
    ar = (f"يشير تحليل التباين إلى أن الاختلاف في {outcome} بين المجموعات الـ{k} {s[1]} (F = {Fv:.2f}، {pstr(p)}). "
          f"حجم الأثر η² = {eta2:.3f} ({mag[1]}) أي أن {eta2*100:.1f}% من التباين يُعزى إلى {group}. ")
    if sig_pairs:
        en += "Significant pairwise differences: " + "; ".join(sig_pairs) + "."
        ar += "الفروق الثنائية الدالة: " + "؛ ".join(sig_pairs) + "."
    else:
        en += "No pairwise comparison reached significance after adjustment."
        ar += "لم تصل أي مقارنة ثنائية إلى الدلالة بعد التصحيح."
    if not all_normal:
        en += " Normality is doubtful; confirm with Kruskal-Wallis."
        ar += " التوزيع الطبيعي مشكوك فيه؛ أكّد النتيجة باختبار كروسكال-واليس."
    res.interpret(en, ar)
    res.methods(f"Differences among groups were analysed by one-way ANOVA followed by {method} post hoc test. Assumptions were "
                f"checked with Shapiro-Wilk (normality) and Levene's test (homogeneity of variance); Welch's ANOVA was computed "
                f"as a robust alternative. F({dfb}, {dfw}) = {Fv:.2f}, {pstr(p)}, η² = {eta2:.3f}. P < 0.05 was considered significant.")
    shown = tab2 if (lev.pvalue < 0.05 and posthoc == "Tukey HSD") else tab
    used = "Games-Howell" if shown is not tab else method
    _tn = f"one-way ANOVA followed by {used} post hoc test" if used != "None" else "one-way ANOVA"
    res.figure_auto(F.group_plot(g, ylabel=outcome, xlabel=group, comparisons=shown.attrs.get("all_pairs", comps) if len(shown) else [],
                                 test_name=_tn))
    return res


def dunn_test(groups: dict, adjust="Holm"):
    labels = list(groups)
    allv = np.concatenate([groups[l] for l in labels])
    N = len(allv)
    ranks = stats.rankdata(allv)
    _, t = np.unique(allv, return_counts=True)
    tie = np.sum(t ** 3 - t) / (12 * (N - 1))
    idx = np.cumsum([0] + [len(groups[l]) for l in labels])
    mr = [ranks[idx[i]:idx[i + 1]].mean() for i in range(len(labels))]
    rows = []
    for i, j in itertools.combinations(range(len(labels)), 2):
        ni, nj = len(groups[labels[i]]), len(groups[labels[j]])
        se = math.sqrt((N * (N + 1) / 12 - tie) * (1 / ni + 1 / nj))
        z = (mr[i] - mr[j]) / se
        rows.append([labels[i], labels[j], mr[i] - mr[j], z, 2 * stats.norm.sf(abs(z))])
    padj = p_adjust([r[4] for r in rows], adjust)
    tab = pd.DataFrame([r + [pa] for r, pa in zip(rows, padj)],
                       columns=["Group A", "Group B", "Mean rank diff.", "z", "p (unadj.)", "p (adj.)"])
    return tab, mr


@register("kruskal", "compare", "Kruskal-Wallis + Dunn's test", "اختبار كروسكال-واليس مع اختبار دن",
          [P("outcome", "Outcome", "المتغير التابع", "var_num"), P("group", "Factor", "العامل", "var_cat"),
           P("adjust", "p adjustment", "تصحيح القيمة الاحتمالية", "choice", P_ADJ, "Holm")],
          "Non-parametric one-way analysis with ε² and Dunn's pairwise comparisons.",
          "تحليل لامعلمي لعدة مجموعات مع حجم الأثر ومقارنات دن الثنائية.")
def kruskal(df, outcome, group, adjust="Holm"):
    g = group_arrays(df, outcome, group)
    arrs = list(g.values())
    H, p = stats.kruskal(*arrs)
    N = sum(len(a) for a in arrs)
    k = len(arrs)
    eps2 = H / ((N ** 2 - 1) / (N + 1))
    res = Result("Kruskal-Wallis test", f"{outcome} by {group}")
    tab, mr = dunn_test(g, adjust)
    desc = describe_groups(g)[["Group", "n", "Median", "IQR"]]
    desc["Mean rank"] = mr
    res.table(desc, "Group statistics")
    res.table(pd.DataFrame([{"H (χ²)": H, "df": k - 1, "p": p, "ε²": eps2}]), "Kruskal-Wallis test",
              "H corrected for ties (as in SPSS/R).")
    res.table(tab, f"Dunn's multiple comparisons ({adjust} adjustment)", p_columns=("p (unadj.)", "p (adj.)"))
    comps = [(r["Group A"], r["Group B"], r["p (adj.)"]) for _, r in tab.iterrows() if r["p (adj.)"] < 0.05]
    s = sig_words(p)
    res.interpret(f"The distribution of {outcome} differs among groups: {s[0]} (H({k-1}) = {H:.2f}, {pstr(p)}; ε² = {eps2:.3f}). "
                  + ("Significant pairs (Dunn): " + "; ".join(f"{a} vs {b}" for a, b, _ in comps) if comps else "No pair significant after adjustment."),
                  f"الاختلاف في توزيع {outcome} بين المجموعات {s[1]} (H = {H:.2f}، {pstr(p)}؛ ε² = {eps2:.3f}). "
                  + ("الأزواج الدالة: " + "؛ ".join(f"{a} مقابل {b}" for a, b, _ in comps) if comps else "لا توجد أزواج دالة بعد التصحيح."))
    res.methods(f"Groups were compared with the Kruskal-Wallis H test followed by Dunn's test with {adjust} correction; "
                f"data are median (IQR). H({k-1}) = {H:.2f}, {pstr(p)}.")
    res.figure_auto(F.group_plot(g, ylabel=outcome, xlabel=group, center="median", plot_type="Box + points",
                                 comparisons=[(r["Group A"], r["Group B"], r["p (adj.)"]) for _, r in tab.iterrows()],
                                 test_name=f"Kruskal-Wallis test followed by Dunn's test ({adjust} adjustment)"))
    return res


# ---------------------------------------------------------------------------
@register("anova2", "compare", "Two-way / factorial ANOVA", "تحليل التباين الثنائي (العاملي)",
          [P("outcome", "Outcome", "المتغير التابع", "var_num"), P("factor_a", "Factor A", "العامل الأول", "var_cat"),
           P("factor_b", "Factor B", "العامل الثاني", "var_cat"),
           P("factor_c", "Factor C (optional)", "العامل الثالث (اختياري)", "var_cat", optional=True),
           P("ss_type", "Sum of squares", "نوع مجموع المربعات", "choice", ["Type III (SPSS)", "Type II"], "Type III (SPSS)"),
           P("posthoc", "Post hoc for main effects", "الاختبار البعدي", "choice", ["Tukey HSD", "Bonferroni", "Holm", "None"], "Tukey HSD")],
          "Factorial ANOVA with interaction, partial η² and interaction plot.",
          "تحليل التباين العاملي مع التفاعل وحجم الأثر الجزئي ورسم التفاعل.")
def anova2(df, outcome, factor_a, factor_b, factor_c=None, ss_type="Type III (SPSS)", posthoc="Tukey HSD"):
    facs = [f for f in [factor_a, factor_b, factor_c] if f]
    d = df[[outcome] + facs].copy()
    d[outcome] = pd.to_numeric(d[outcome], errors="coerce")
    d = d.dropna()
    names = {outcome: "Y"}
    for i, f in enumerate(facs):
        names[f] = f"F{i}"
    d = d.rename(columns=names)
    for i in range(len(facs)):
        d[f"F{i}"] = d[f"F{i}"].astype(str)
    typ = 3 if ss_type.startswith("Type III") else 2
    terms = " * ".join(f"C(F{i}, Sum)" if typ == 3 else f"C(F{i})" for i in range(len(facs)))
    model = smf.ols(f"Y ~ {terms}", data=d).fit()
    aov = sm.stats.anova_lm(model, typ=typ)
    ss_res = aov.loc["Residual", "sum_sq"]
    rows = []
    for idx, r in aov.iterrows():
        name = idx
        for i, f in enumerate(facs):
            name = name.replace(f"C(F{i}, Sum)", f).replace(f"C(F{i})", f)
        if name == "Intercept":
            continue
        pe = r["sum_sq"] / (r["sum_sq"] + ss_res) if name != "Residual" else np.nan
        rows.append({"Source": name.replace(":", " × "), "SS": r["sum_sq"], "df": r["df"], "MS": r["sum_sq"] / r["df"],
                     "F": r["F"], "p": r["PR(>F)"], "Partial η²": pe})
    tab = pd.DataFrame(rows)
    res = Result("Factorial ANOVA", f"{outcome} ~ {' × '.join(facs)} ({ss_type})")
    cell = d.groupby([f"F{i}" for i in range(len(facs))])["Y"].agg(["count", "mean", "std"]).reset_index()
    cell.columns = facs + ["n", "Mean", "SD"]
    res.table(cell, "Cell descriptive statistics")
    res.table(tab, f"Tests of between-subjects effects ({ss_type})", f"R² = {model.rsquared:.3f}, adjusted R² = {model.rsquared_adj:.3f}.")
    lev = stats.levene(*[grp["Y"].values for _, grp in d.groupby([f"F{i}" for i in range(len(facs))])], center="median")
    res.note(f"Levene's test of equality of error variances: F = {lev.statistic:.3f}, {pstr(lev.pvalue)}. "
             f"Shapiro-Wilk on residuals: {pstr(stats.shapiro(model.resid)[1])}.")
    inter = tab[tab.Source.str.contains("×")]
    en, ar = [], []
    if len(inter) and (inter.p < 0.05).any():
        ii = inter[inter.p < 0.05].iloc[0]
        en.append(f"A significant interaction ({ii.Source}: F = {ii.F:.2f}, {pstr(ii.p)}) means the effect of one factor depends on the "
                  f"level of the other; interpret simple effects (see interaction plot) rather than main effects alone.")
        ar.append(f"يوجد تفاعل دال ({ii.Source}: {pstr(ii.p)})، أي أن تأثير أحد العاملين يعتمد على مستوى الآخر؛ "
                  f"فسّر التأثيرات البسيطة (انظر رسم التفاعل) وليس التأثيرات الرئيسية وحدها.")
    else:
        en.append("No significant interaction; main effects can be interpreted directly.")
        ar.append("لا يوجد تفاعل دال؛ ويمكن تفسير التأثيرات الرئيسية مباشرة.")
    for _, r in tab[~tab.Source.str.contains("×") & (tab.Source != "Residual")].iterrows():
        s = sig_words(r.p)
        en.append(f"Main effect of {r.Source}: {s[0]} (F({r.df:.0f}, {model.df_resid:.0f}) = {r.F:.2f}, {pstr(r.p)}, partial η² = {r['Partial η²']:.3f}).")
        ar.append(f"التأثير الرئيسي لـ{r.Source}: {s[1]} ({pstr(r.p)}، η² الجزئي = {r['Partial η²']:.3f}).")
    res.interpret(" ".join(en), " ".join(ar))
    if posthoc != "None":
        for i, f in enumerate(facs):
            gg = {str(k): v["Y"].to_numpy() for k, v in d.groupby(f"F{i}")}
            if len(gg) > 2:
                t, _ = posthoc_table(gg, posthoc, model.mse_resid, model.df_resid)
                res.table(t, f"Post hoc ({posthoc}) for main effect of {f}", p_columns=("p (adj.)",))
    la = sorted(d["F0"].unique(), key=str)
    series, errs = {}, {}
    for lb, sub in d.groupby("F1"):
        mm = sub.groupby("F0")["Y"]
        series[lb] = [mm.mean().get(l, np.nan) for l in la]
        errs[lb] = [(mm.std() / np.sqrt(mm.count())).get(l, np.nan) for l in la]
    res.figure(F.interaction_plot(la, series, ylabel=outcome, xlabel=factor_a, errs=errs),
               f"Interaction plot: {factor_a} × {factor_b} (mean ± SEM).")
    res.methods(f"A {len(facs)}-way factorial ANOVA ({ss_type} sums of squares) tested the main effects of {', '.join(facs)} and their "
                f"interaction on {outcome}; partial η² is reported as effect size.")
    return res


@register("ancova", "compare", "ANCOVA (adjusted for covariates)", "تحليل التغاير ANCOVA",
          [P("outcome", "Outcome", "المتغير التابع", "var_num"), P("group", "Group factor", "عامل المجموعات", "var_cat"),
           P("covariates", "Covariate(s) e.g. baseline", "المتغيرات المصاحبة (مثل القيمة الأساسية)", "vars_num")],
          "Group comparison adjusted for baseline/covariates with adjusted (estimated marginal) means.",
          "مقارنة المجموعات بعد ضبط القيم الأساسية مع المتوسطات المعدلة.")
def ancova(df, outcome, group, covariates):
    cols = [outcome, group] + list(covariates)
    d = df[cols].copy()
    for c in [outcome] + list(covariates):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna()
    ren = {outcome: "Y", group: "G"}
    for i, c in enumerate(covariates):
        ren[c] = f"X{i}"
    d = d.rename(columns=ren)
    d["G"] = d["G"].astype(str)
    xs = " + ".join(f"X{i}" for i in range(len(covariates)))
    m = smf.ols(f"Y ~ C(G, Sum) + {xs}", data=d).fit()
    aov = sm.stats.anova_lm(m, typ=3)
    ssr = aov.loc["Residual", "sum_sq"]
    rows = []
    for idx, r in aov.iterrows():
        if idx == "Intercept":
            continue
        name = idx.replace("C(G, Sum)", group)
        for i, c in enumerate(covariates):
            name = name.replace(f"X{i}", c)
        rows.append({"Source": name, "SS": r.sum_sq, "df": r.df, "F": r.F, "p": r["PR(>F)"],
                     "Partial η²": r.sum_sq / (r.sum_sq + ssr) if idx != "Residual" else np.nan})
    res = Result("ANCOVA", f"{outcome} by {group}, adjusted for {', '.join(covariates)}")
    res.table(pd.DataFrame(rows), "ANCOVA table (Type III SS)")
    # homogeneity of regression slopes
    m_int = smf.ols(f"Y ~ C(G) * X0", data=d).fit()
    a_int = sm.stats.anova_lm(m_int, typ=2)
    p_slopes = a_int.loc["C(G):X0", "PR(>F)"]
    res.note(f"Homogeneity of regression slopes ({group} × {covariates[0]}): {pstr(p_slopes)}"
             + (" — assumption violated; consider reporting the interaction." if p_slopes < 0.05 else " — assumption met."))
    # adjusted means at covariate means
    levels = sorted(d.G.unique())
    adj = []
    base = {f"X{i}": d[f"X{i}"].mean() for i in range(len(covariates))}
    for lv in levels:
        nd = pd.DataFrame([{**base, "G": lv}])
        pr = m.get_prediction(nd).summary_frame(alpha=0.05)
        adj.append({"Group": lv, "n": int((d.G == lv).sum()), "Unadjusted mean": d.loc[d.G == lv, "Y"].mean(),
                    "Adjusted mean": pr["mean"].iloc[0], "SE": pr["mean_se"].iloc[0],
                    "95% CI lower": pr["mean_ci_lower"].iloc[0], "95% CI upper": pr["mean_ci_upper"].iloc[0]})
    res.table(pd.DataFrame(adj), "Estimated marginal (adjusted) means", "Covariates evaluated at their means.")
    pg = [r for r in rows if r["Source"] == group][0]
    s = sig_words(pg["p"])
    res.interpret(f"After adjusting for {', '.join(covariates)}, the effect of {group} on {outcome} is {s[0]} "
                  f"(F = {pg['F']:.2f}, {pstr(pg['p'])}, partial η² = {pg['Partial η²']:.3f}). ANCOVA on follow-up values adjusted "
                  "for baseline is more powerful and less biased than analysing change scores.",
                  f"بعد ضبط تأثير {', '.join(covariates)}، فإن تأثير {group} على {outcome} {s[1]} ({pstr(pg['p'])}، η² الجزئي = "
                  f"{pg['Partial η²']:.3f}). تحليل التغاير مع ضبط القيمة الأساسية أقوى وأقل تحيزًا من تحليل درجات التغير.")
    return res
