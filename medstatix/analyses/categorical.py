"""Categorical data: chi-square, Fisher, risk measures, McNemar, Mantel-Haenszel, goodness of fit, trend."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.contingency_tables import StratifiedTable, mcnemar as sm_mcnemar, Table2x2

from ..core.data import _level_order
from ..core.result import Result, AnalysisError
from ..plots import figures as F
from .common import pstr, sig_words, wilson_ci
from .registry import register, P


def _crosstab(df, row, col):
    d = df[[row, col]].dropna()
    t = pd.crosstab(d[row], d[col])
    try:
        t = t.reindex(index=_level_order(d[row]), columns=_level_order(d[col]))
    except Exception:
        pass
    t.index = [str(i) for i in t.index]
    t.columns = [str(c) for c in t.columns]
    t.index.name, t.columns.name = row, col
    return t


@register("chisq", "categorical", "Crosstabs: χ² / Fisher's exact (OR, RR)", "الجداول التقاطعية: كاي تربيع / فيشر",
          [P("row", "Row variable (exposure / group)", "متغير الصفوف (التعرض/المجموعة)", "var_cat"),
           P("col", "Column variable (outcome)", "متغير الأعمدة (النتيجة)", "var_cat")],
          "Pearson χ², Yates, likelihood ratio, Fisher's exact, linear-by-linear trend, Cramér's V; OR, RR and RD with 95% CI for 2×2.",
          "كاي تربيع وتصحيح ييتس وفيشر الدقيق ونسبة الأرجحية والخطر النسبي مع فترات الثقة.")
def chisq(df, row, col):
    t = _crosstab(df, row, col)
    if t.shape[0] < 2 or t.shape[1] < 2:
        raise AnalysisError("Each variable needs at least 2 categories.")
    obs = t.to_numpy()
    chi2, p, dof, exp = stats.chi2_contingency(obs, correction=False)
    res = Result("Crosstabulation and tests of association", f"{row} × {col} (N = {obs.sum()})")
    disp = t.copy().astype(object)
    rowpct = t.div(t.sum(1), axis=0) * 100
    for i in range(t.shape[0]):
        for j in range(t.shape[1]):
            disp.iat[i, j] = f"{obs[i, j]} ({rowpct.iat[i, j]:.1f}%)"
    disp["Total"] = t.sum(1).values
    res.table(disp, f"{row} × {col}: n (row %)")
    small = (exp < 5).sum()
    tests = [{"Test": "Pearson χ²", "Value": chi2, "df": dof, "p": p}]
    if obs.shape == (2, 2):
        c2, pc, _, _ = stats.chi2_contingency(obs, correction=True)
        tests.append({"Test": "Continuity correction (Yates)", "Value": c2, "df": 1, "p": pc})
    g, pg, _, _ = stats.chi2_contingency(obs, correction=False, lambda_="log-likelihood")
    tests.append({"Test": "Likelihood ratio", "Value": g, "df": dof, "p": pg})
    fisher_p = np.nan
    try:
        if obs.shape == (2, 2):
            fisher_p = stats.fisher_exact(obs).pvalue
        elif obs.sum() <= 300:
            fisher_p = stats.fisher_exact(obs).pvalue
        tests.append({"Test": "Fisher's exact test", "Value": np.nan, "df": np.nan, "p": fisher_p})
    except Exception:
        pass
    # linear-by-linear (Mantel trend) for ordinal tables
    if obs.shape[0] > 2 or obs.shape[1] > 2:
        rr = np.repeat(np.arange(obs.shape[0]), obs.sum(1))
        cc = np.concatenate([np.repeat(np.arange(obs.shape[1]), obs[i]) for i in range(obs.shape[0])])
        rr = np.concatenate([np.full(obs[i].sum(), i) for i in range(obs.shape[0])])
        r = np.corrcoef(rr, cc)[0, 1]
        M2 = (obs.sum() - 1) * r ** 2
        tests.append({"Test": "Linear-by-linear association", "Value": M2, "df": 1, "p": stats.chi2.sf(M2, 1)})
    N = obs.sum()
    V = math.sqrt(chi2 / (N * (min(obs.shape) - 1)))
    res.table(pd.DataFrame(tests), "Tests of association",
              f"{small} cell(s) ({small / obs.size * 100:.0f}%) have expected count < 5. Minimum expected count = {exp.min():.2f}. "
              f"Cramér's V = {V:.3f}.")
    use_fisher = small > 0
    main_p = fisher_p if (use_fisher and not np.isnan(fisher_p)) else p
    test_name = "Fisher's exact test" if use_fisher and not np.isnan(fisher_p) else "Pearson χ² test"
    en = f"{test_name} was selected ({'some expected counts < 5' if use_fisher else 'all expected counts ≥ 5'}). The association between {row} and {col} is {sig_words(main_p)[0]} ({pstr(main_p)}); Cramér's V = {V:.2f}."
    ar = f"تم اختيار {('اختبار فيشر الدقيق' if use_fisher else 'اختبار كاي تربيع')} ({'لوجود خلايا بتكرار متوقع أقل من 5' if use_fisher else 'لأن جميع التكرارات المتوقعة ≥ 5'}). العلاقة بين {row} و{col} {sig_words(main_p)[1]} ({pstr(main_p)})؛ معامل كرامر V = {V:.2f}."
    if obs.shape == (2, 2):
        tb = Table2x2(obs)
        a, b, c, d = obs.ravel()
        r1, r2 = a / (a + b), c / (c + d)
        rd = r1 - r2
        se_rd = math.sqrt(r1 * (1 - r1) / (a + b) + r2 * (1 - r2) / (c + d))
        orc = tb.oddsratio_confint()
        rrc = tb.riskratio_confint()
        nnt = 1 / abs(rd) if rd != 0 else np.inf
        risk = pd.DataFrame([
            {"Measure": f"Odds ratio ({t.index[0]} vs {t.index[1]})", "Estimate": tb.oddsratio, "95% CI lower": orc[0], "95% CI upper": orc[1]},
            {"Measure": f"Relative risk of '{t.columns[0]}'", "Estimate": tb.riskratio, "95% CI lower": rrc[0], "95% CI upper": rrc[1]},
            {"Measure": "Risk difference", "Estimate": rd, "95% CI lower": rd - 1.96 * se_rd, "95% CI upper": rd + 1.96 * se_rd},
            {"Measure": "NNT / NNH", "Estimate": nnt, "95% CI lower": np.nan, "95% CI upper": np.nan},
        ])
        res.table(risk, "Risk estimates (2×2)", f"Risk of '{t.columns[0]}' = {r1*100:.1f}% in {t.index[0]} vs {r2*100:.1f}% in {t.index[1]}. "
                  "Woolf (log) CI for OR, Katz (log) CI for RR, Wald CI for RD.")
        en += f" Odds ratio = {tb.oddsratio:.2f} (95% CI {orc[0]:.2f}–{orc[1]:.2f}); relative risk = {tb.riskratio:.2f} (95% CI {rrc[0]:.2f}–{rrc[1]:.2f})."
        ar += f" نسبة الأرجحية = {tb.oddsratio:.2f} (فترة الثقة {orc[0]:.2f}–{orc[1]:.2f})؛ الخطر النسبي = {tb.riskratio:.2f}."
    res.interpret(en, ar)
    res.methods(f"Categorical variables are presented as n (%) and compared using the {test_name.lower()}"
                f"{' (expected counts < 5)' if use_fisher else ''}. {test_name}: {pstr(main_p)}.")
    res.figure(F.bar_counts(t, xlabel=row), f"Percentage of {col} categories within each {row} group.")
    return res


@register("mcnemar", "categorical", "McNemar test (paired proportions)", "اختبار مكنمار للنسب المزدوجة",
          [P("var1", "Before / test 1 (binary)", "قبل / الاختبار 1 (ثنائي)", "var_cat"),
           P("var2", "After / test 2 (binary)", "بعد / الاختبار 2 (ثنائي)", "var_cat")],
          "Exact and asymptotic McNemar test for paired binary data.", "اختبار مكنمار الدقيق والتقريبي للبيانات الثنائية المزدوجة.")
def mcnemar(df, var1, var2):
    t = _crosstab(df, var1, var2)
    if t.shape != (2, 2):
        raise AnalysisError("Both variables must be binary with the same two categories.")
    ex = sm_mcnemar(t.to_numpy(), exact=True)
    asy = sm_mcnemar(t.to_numpy(), exact=False, correction=True)
    b, c = t.iat[0, 1], t.iat[1, 0]
    res = Result("McNemar test", f"{var1} vs {var2}")
    res.table(t, "Paired 2×2 table")
    res.table(pd.DataFrame([{"Test": "McNemar exact (binomial)", "Statistic": ex.statistic, "p": ex.pvalue},
                            {"Test": "McNemar χ² (continuity corrected)", "Statistic": asy.statistic, "p": asy.pvalue}]),
              "McNemar test", f"Discordant pairs: b = {b}, c = {c}. Paired OR = b/c = {b / c if c else np.inf:.3f}.")
    res.interpret(f"Change in the proportion between paired measurements is {sig_words(ex.pvalue)[0]} (exact {pstr(ex.pvalue)}).",
                  f"التغير في النسبة بين القياسين المزدوجين {sig_words(ex.pvalue)[1]} ({pstr(ex.pvalue)}).")
    return res


@register("mantel", "categorical", "Mantel-Haenszel (stratified 2×2)", "اختبار مانتل-هانزل للجداول الطبقية",
          [P("exposure", "Exposure (binary)", "التعرض (ثنائي)", "var_cat"), P("outcome", "Outcome (binary)", "النتيجة (ثنائي)", "var_cat"),
           P("strata", "Stratification variable (confounder)", "متغير الطبقات (المربك)", "var_cat")],
          "Pooled (adjusted) OR across strata with Breslow-Day homogeneity test.", "نسبة الأرجحية المعدلة عبر الطبقات مع اختبار التجانس.")
def mantel(df, exposure, outcome, strata):
    tables, names = [], []
    for s, sub in df.groupby(strata):
        t = _crosstab(sub, exposure, outcome)
        if t.shape == (2, 2):
            tables.append(t.to_numpy()); names.append(str(s))
    if len(tables) < 2:
        raise AnalysisError("Need ≥ 2 strata with complete 2×2 tables.")
    st = StratifiedTable(tables)
    rows = []
    for n, tb in zip(names, tables):
        t2 = Table2x2(tb + (0.5 if (tb == 0).any() else 0))
        ci = t2.oddsratio_confint()
        rows.append({"Stratum": n, "OR": t2.oddsratio, "95% CI lower": ci[0], "95% CI upper": ci[1], "n": tb.sum()})
    ci = st.oddsratio_pooled_confint()
    rows.append({"Stratum": "Mantel-Haenszel pooled", "OR": st.oddsratio_pooled, "95% CI lower": ci[0], "95% CI upper": ci[1], "n": sum(t.sum() for t in tables)})
    crude = Table2x2(sum(tables))
    rows.append({"Stratum": "Crude (unadjusted)", "OR": crude.oddsratio, "95% CI lower": crude.oddsratio_confint()[0],
                 "95% CI upper": crude.oddsratio_confint()[1], "n": sum(t.sum() for t in tables)})
    res = Result("Mantel-Haenszel analysis", f"{exposure} → {outcome}, stratified by {strata}")
    res.table(pd.DataFrame(rows), "Stratum-specific and pooled odds ratios")
    tn = st.test_null_odds()
    te = st.test_equal_odds()
    res.table(pd.DataFrame([{"Test": "Cochran-Mantel-Haenszel (OR = 1)", "χ²": tn.statistic, "p": tn.pvalue},
                            {"Test": "Breslow-Day homogeneity", "χ²": te.statistic, "p": te.pvalue}]), "Tests")
    conf = abs(st.oddsratio_pooled - crude.oddsratio) / crude.oddsratio * 100
    res.interpret(f"Adjusted OR = {st.oddsratio_pooled:.2f} vs crude OR = {crude.oddsratio:.2f} ({conf:.0f}% change"
                  f"{' — suggests confounding by ' + strata if conf > 10 else ''}). Homogeneity across strata: {pstr(te.pvalue)}"
                  f"{' — effect modification likely; report stratum-specific ORs.' if te.pvalue < 0.05 else '.'}",
                  f"نسبة الأرجحية المعدلة = {st.oddsratio_pooled:.2f} مقابل الخام = {crude.oddsratio:.2f} (تغير {conf:.0f}%"
                  f"{' يشير إلى تأثير مربك لـ' + strata if conf > 10 else ''}).")
    return res


@register("gof", "categorical", "Chi-square goodness of fit / binomial test", "اختبار حسن المطابقة",
          [P("variable", "Variable", "المتغير", "var_cat"),
           P("expected", "Expected proportions (comma separated, blank = equal)", "النسب المتوقعة (مفصولة بفواصل)", "text", default="")],
          "Compare observed category frequencies with expected proportions.", "مقارنة التكرارات المشاهدة بالنسب المتوقعة.")
def gof(df, variable, expected=""):
    s = df[variable].dropna()
    counts = s.value_counts().reindex(_level_order(s))
    k = len(counts)
    if expected and expected.strip():
        pr = np.array([float(x) for x in expected.split(",")])
        if len(pr) != k:
            raise AnalysisError(f"Give {k} expected proportions (categories: {', '.join(map(str, counts.index))}).")
        pr = pr / pr.sum()
    else:
        pr = np.ones(k) / k
    exp = pr * counts.sum()
    chi, p = stats.chisquare(counts.values, exp)
    res = Result("Goodness of fit", variable)
    res.table(pd.DataFrame({"Category": [str(i) for i in counts.index], "Observed": counts.values, "Expected": exp,
                            "Residual": counts.values - exp}), "Observed vs expected")
    rows = [{"Test": "χ² goodness of fit", "Statistic": chi, "df": k - 1, "p": p}]
    if k == 2:
        bt = stats.binomtest(int(counts.values[0]), int(counts.sum()), pr[0])
        rows.append({"Test": "Exact binomial", "Statistic": counts.values[0] / counts.sum(), "df": np.nan, "p": bt.pvalue})
    res.table(pd.DataFrame(rows), "Tests")
    res.interpret(f"The observed distribution {'differs' if p < 0.05 else 'does not differ'} significantly from expected ({pstr(p)}).",
                  f"التوزيع المشاهد {'يختلف' if p < 0.05 else 'لا يختلف'} معنويًا عن المتوقع ({pstr(p)}).")
    return res


@register("proportion_ci", "categorical", "Proportion with 95% CI / compare two proportions", "النسبة مع فترة الثقة / مقارنة نسبتين",
          [P("x1", "Events group 1", "عدد الأحداث - المجموعة 1", "int", default=15), P("n1", "Total group 1", "الإجمالي - المجموعة 1", "int", default=50),
           P("x2", "Events group 2 (0 = single proportion)", "عدد الأحداث - المجموعة 2 (0 = نسبة واحدة)", "int", default=0),
           P("n2", "Total group 2", "الإجمالي - المجموعة 2", "int", default=0)],
          "Quick calculator from summary counts (no dataset needed).", "حاسبة سريعة من الأعداد الملخصة.", needs_data=False)
def proportion_ci(x1=15, n1=50, x2=0, n2=0):
    res = Result("Proportions", "From summary counts")
    rows = []
    for lab, x, n in [("Group 1", x1, n1), ("Group 2", x2, n2)]:
        if n and n > 0:
            lo, hi = wilson_ci(x, n)
            ex = stats.binomtest(int(x), int(n)).proportion_ci(method="exact")
            rows.append({"Group": lab, "x": x, "n": n, "Proportion": x / n, "Wilson 95% CI": f"{lo:.3f} – {hi:.3f}",
                         "Clopper-Pearson 95% CI": f"{ex.low:.3f} – {ex.high:.3f}"})
    res.table(pd.DataFrame(rows), "Proportions")
    if n2:
        obs = np.array([[x1, n1 - x1], [x2, n2 - x2]])
        chi2, p, _, exp = stats.chi2_contingency(obs, correction=False)
        fp = stats.fisher_exact(obs).pvalue
        tb = Table2x2(obs)
        res.table(pd.DataFrame([{"Difference": x1 / n1 - x2 / n2, "χ² p": p, "Fisher p": fp, "OR": tb.oddsratio, "RR": tb.riskratio}]),
                  "Comparison", p_columns=("χ² p", "Fisher p"))
        res.interpret(f"Difference in proportions = {(x1/n1 - x2/n2)*100:.1f} percentage points ({pstr(fp if (exp < 5).any() else p)}).",
                      f"الفرق بين النسبتين = {(x1/n1 - x2/n2)*100:.1f} نقطة مئوية ({pstr(fp if (exp < 5).any() else p)}).")
    return res
