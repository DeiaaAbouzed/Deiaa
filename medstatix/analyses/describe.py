"""Descriptive statistics, frequencies, normality, outliers."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.diagnostic import lilliefors

from ..core.data import numeric, _level_order
from ..core.result import Result, AnalysisError
from ..plots import figures as F
from .common import mean_ci
from .registry import register, P


@register("descriptives", "describe", "Descriptive statistics", "الإحصاء الوصفي",
          [P("variables", "Variables", "المتغيرات", "vars_num"),
           P("group", "Split by group (optional)", "تقسيم حسب مجموعة (اختياري)", "var_cat", optional=True)],
          "Mean, SD, SEM, 95% CI, median, IQR, skewness, kurtosis and Shapiro-Wilk, optionally by group.",
          "المتوسط والانحراف المعياري والخطأ المعياري وفترة الثقة والوسيط والمدى الربيعي والالتواء والتفلطح واختبار شابيرو-ويلك.")
def descriptives(df, variables, group=None):
    if not variables:
        raise AnalysisError("Select at least one variable.")
    res = Result("Descriptive statistics", f"Variables: {', '.join(variables)}" + (f" | by {group}" if group else ""))
    rows = []
    hist_data = {}
    for v in variables:
        s = numeric(df, v)
        if group:
            parts = [(str(l), s[df[group] == l]) for l in _level_order(df[group])]
        else:
            parts = [("All", s)]
        for gname, x in parts:
            n_miss = int(x.isna().sum())
            x = x.dropna().to_numpy(float)
            n = len(x)
            if n == 0:
                continue
            m, lo, hi = mean_ci(x)
            sd = x.std(ddof=1) if n > 1 else np.nan
            q1, med, q3 = np.percentile(x, [25, 50, 75])
            sw_p = stats.shapiro(x)[1] if 3 <= n <= 5000 else np.nan
            rows.append({"Variable": v, "Group": gname, "n": n, "Missing": n_miss, "Mean": m, "SD": sd,
                         "SEM": sd / math.sqrt(n) if n > 1 else np.nan, "95% CI lower": lo, "95% CI upper": hi,
                         "Median": med, "Q1": q1, "Q3": q3, "Min": x.min(), "Max": x.max(),
                         "CV%": sd / m * 100 if m else np.nan,
                         "Skewness": stats.skew(x, bias=False) if n > 2 else np.nan,
                         "Kurtosis": stats.kurtosis(x, bias=False) if n > 3 else np.nan,
                         "Shapiro-Wilk p": sw_p})
            hist_data[f"{v} | {gname}" if group else v] = x
    tab = pd.DataFrame(rows)
    if not group:
        tab = tab.drop(columns="Group")
    res.table(tab, "Descriptive statistics", "CI = confidence interval; SEM = standard error of the mean; "
              "CV = coefficient of variation; skewness and kurtosis are bias-corrected (as in SPSS).",
              p_columns=("Shapiro-Wilk p",))
    # Smart summary line
    lines_en, lines_ar = [], []
    for r in rows:
        nonnormal = not np.isnan(r["Shapiro-Wilk p"]) and r["Shapiro-Wilk p"] < 0.05
        tag = f"{r['Variable']}" + (f" ({r['Group']})" if group else "")
        if nonnormal:
            lines_en.append(f"• {tag}: non-normal (Shapiro-Wilk p = {r['Shapiro-Wilk p']:.3f}); report median (IQR) = "
                            f"{r['Median']:.2f} ({r['Q1']:.2f}–{r['Q3']:.2f}) and use non-parametric tests.")
            lines_ar.append(f"• {tag}: التوزيع غير طبيعي؛ يُفضّل عرض الوسيط (المدى الربيعي) = {r['Median']:.2f} "
                            f"({r['Q1']:.2f}–{r['Q3']:.2f}) واستخدام الاختبارات اللامعلمية.")
        else:
            lines_en.append(f"• {tag}: approximately normal; report mean ± SD = {r['Mean']:.2f} ± {r['SD']:.2f}.")
            lines_ar.append(f"• {tag}: التوزيع قريب من الطبيعي؛ يُعرض المتوسط ± الانحراف المعياري = {r['Mean']:.2f} ± {r['SD']:.2f}.")
    res.interpret("\n".join(lines_en), "\n".join(lines_ar))
    if group and len(variables) == 1:
        res.figure_auto(F.group_plot({k.split(" | ")[1]: v for k, v in hist_data.items()}, ylabel=variables[0], xlabel=group))
    res.figure(F.histogram(hist_data, xlabel=", ".join(variables)), "Histograms with fitted normal density.")
    return res


@register("frequencies", "describe", "Frequencies (categorical)", "التكرارات للمتغيرات الفئوية",
          [P("variables", "Variables", "المتغيرات", "vars_any")],
          "Counts, percentages and valid percentages with 95% Wilson CI.",
          "الأعداد والنسب المئوية مع فترات الثقة.")
def frequencies(df, variables):
    from .common import wilson_ci
    res = Result("Frequencies", ", ".join(variables))
    for v in variables:
        s = df[v]
        n_total = len(s)
        valid = s.dropna()
        counts = valid.value_counts()
        try:
            counts = counts.reindex(_level_order(s))
        except Exception:
            pass
        rows = []
        for lev, c in counts.items():
            lo, hi = wilson_ci(c, len(valid))
            rows.append({"Category": str(lev), "n": int(c), "Percent": c / n_total * 100,
                         "Valid %": c / len(valid) * 100, "95% CI (valid %)": f"{lo*100:.1f} – {hi*100:.1f}"})
        if s.isna().sum():
            rows.append({"Category": "Missing", "n": int(s.isna().sum()), "Percent": s.isna().sum() / n_total * 100,
                         "Valid %": np.nan, "95% CI (valid %)": ""})
        rows.append({"Category": "Total", "n": n_total, "Percent": 100.0, "Valid %": np.nan, "95% CI (valid %)": ""})
        res.table(pd.DataFrame(rows), f"Frequency distribution of {v}")
        ct = pd.DataFrame({v: counts.values}, index=[str(i) for i in counts.index]).T
        res.figure(F.bar_counts(ct, xlabel="", ylabel="Percentage (%)"), f"Distribution of {v}.")
    return res


@register("normality", "describe", "Normality tests", "اختبارات التوزيع الطبيعي",
          [P("variables", "Variables", "المتغيرات", "vars_num"),
           P("group", "Split by group (optional)", "تقسيم حسب مجموعة (اختياري)", "var_cat", optional=True)],
          "Shapiro-Wilk, Kolmogorov-Smirnov (Lilliefors), D'Agostino-Pearson and Anderson-Darling with Q-Q plots.",
          "اختبارات شابيرو-ويلك وكولموجوروف-سميرنوف ودي أجوستينو وأندرسون-دارلنج مع رسم Q-Q.")
def normality(df, variables, group=None):
    res = Result("Tests of normality", ", ".join(variables) + (f" by {group}" if group else ""))
    rows = []
    qq = {}
    for v in variables:
        s = numeric(df, v)
        parts = [(str(l), s[df[group] == l]) for l in _level_order(df[group])] if group else [("All", s)]
        for g, x in parts:
            x = x.dropna().to_numpy(float)
            if len(x) < 3:
                continue
            sw = stats.shapiro(x)
            try:
                ks_d, ks_p = lilliefors(x, dist="norm")
            except Exception:
                ks_d, ks_p = np.nan, np.nan
            if len(x) >= 8:
                dag = stats.normaltest(x)
                dag_s, dag_p = dag.statistic, dag.pvalue
            else:
                dag_s, dag_p = np.nan, np.nan
            ad = stats.anderson(x, dist="norm")
            ad_crit = ad.critical_values[list(ad.significance_level).index(5.0)]
            rows.append({"Variable": v, "Group": g, "n": len(x), "Shapiro-Wilk W": sw.statistic, "SW p": sw.pvalue,
                         "K-S (Lilliefors) D": ks_d, "K-S p": ks_p, "D'Agostino K²": dag_s, "D'Agostino p": dag_p,
                         "Anderson-Darling A²": ad.statistic, "A² > crit (5%)": "Yes" if ad.statistic > ad_crit else "No",
                         "Decision": "Normal" if sw.pvalue >= 0.05 else "Non-normal"})
            qq[f"{v}" + (f" | {g}" if group else "")] = x
    tab = pd.DataFrame(rows)
    if not group:
        tab = tab.drop(columns="Group")
    res.table(tab, "Tests of normality", "Decision based on Shapiro-Wilk (recommended for n < 2000). "
              "Lilliefors significance correction applied to K-S (as in SPSS).",
              p_columns=("SW p", "K-S p", "D'Agostino p"))
    nn = [r for r in rows if r["Decision"] == "Non-normal"]
    if nn:
        res.interpret("Non-normal distribution detected in: " + ", ".join(f"{r['Variable']} ({r['Group']})" if group else r["Variable"] for r in nn)
                      + ". Consider non-parametric tests (Mann-Whitney, Kruskal-Wallis, Wilcoxon, Spearman) or a log transformation. "
                      "With large samples (n > 50) minor deviations become 'significant'; inspect the Q-Q plot.",
                      "تم رصد توزيع غير طبيعي في: " + "، ".join(r["Variable"] for r in nn)
                      + ". يُنصح بالاختبارات اللامعلمية أو التحويل اللوغاريتمي. مع العينات الكبيرة تُصبح الانحرافات البسيطة دالة، لذا افحص رسم Q-Q.")
    else:
        res.interpret("All variables are compatible with a normal distribution; parametric tests are appropriate.",
                      "جميع المتغيرات متوافقة مع التوزيع الطبيعي؛ الاختبارات المعلمية مناسبة.")
    res.figure(F.qq_plot(qq), "Normal Q–Q plots.")
    return res


@register("outliers", "describe", "Outlier detection", "الكشف عن القيم الشاذة",
          [P("variable", "Variable", "المتغير", "var_num"),
           P("method", "Method", "الطريقة", "choice", ["Grubbs (alpha 0.05)", "Tukey fences (1.5 IQR)", "ROUT-like robust z (MAD > 3.5)"], "Grubbs (alpha 0.05)")],
          "Grubbs' test, Tukey fences or robust MAD z-scores.", "اختبار جرابس أو حدود توكي أو الدرجات المعيارية القوية.")
def outliers(df, variable, method="Grubbs (alpha 0.05)"):
    s = numeric(df, variable).dropna()
    x = s.to_numpy(float)
    res = Result("Outlier detection", f"{variable} — {method}")
    flagged = []
    if method.startswith("Grubbs"):
        idx = list(s.index)
        xx = x.copy()
        while len(xx) > 2:
            n = len(xx)
            z = np.abs(xx - xx.mean()) / xx.std(ddof=1)
            i = int(np.argmax(z))
            t = stats.t.ppf(1 - 0.05 / (2 * n), n - 2)
            gcrit = (n - 1) / math.sqrt(n) * math.sqrt(t ** 2 / (n - 2 + t ** 2))
            if z[i] > gcrit:
                flagged.append({"Row": idx[i] + 1, "Value": xx[i], "G": z[i], "G critical": gcrit})
                xx = np.delete(xx, i); idx.pop(i)
            else:
                break
    elif method.startswith("Tukey"):
        q1, q3 = np.percentile(x, [25, 75])
        lo, hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
        for i, v in s.items():
            if v < lo or v > hi:
                flagged.append({"Row": i + 1, "Value": v, "Lower fence": lo, "Upper fence": hi})
    else:
        med = np.median(x)
        mad = np.median(np.abs(x - med))
        for i, v in s.items():
            z = 0.6745 * (v - med) / mad if mad > 0 else 0
            if abs(z) > 3.5:
                flagged.append({"Row": i + 1, "Value": v, "Robust z": z})
    if flagged:
        res.table(pd.DataFrame(flagged), "Potential outliers")
        res.interpret(f"{len(flagged)} potential outlier(s) flagged. Do not delete automatically: check for data-entry errors "
                      "and report any exclusion with its justification; run a sensitivity analysis with and without them.",
                      f"تم رصد {len(flagged)} قيمة شاذة محتملة. لا تحذفها تلقائيًا: راجع أخطاء الإدخال، واذكر سبب أي استبعاد، وأجرِ تحليل حساسية بوجودها وبدونها.")
    else:
        res.text("No outliers detected.")
        res.interpret("No outliers detected by the chosen method.", "لم تُرصد قيم شاذة بالطريقة المختارة.")
    return res
