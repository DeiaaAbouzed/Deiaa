"""Repeated measures: RM-ANOVA (sphericity, GG/HF), mixed RM-ANOVA via LMM, Friedman, linear mixed models, GEE."""
from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats

from ..core.data import numeric
from ..core.result import Result, AnalysisError
from ..plots import figures as F
from .common import describe_groups, magnitude_eta, p_adjust, pstr, sig_words
from .registry import register, P, P_ADJ


def sphericity(Y):
    """Mauchly's W, GG and HF epsilons for an n×k matrix."""
    n, k = Y.shape
    # orthonormal contrasts
    C = np.linalg.qr(np.vstack([np.ones(k), np.eye(k)[:-1] - np.eye(k)[1:]]).T)[0][:, 1:]
    S = np.cov(Y, rowvar=False)
    T = C.T @ S @ C
    p = k - 1
    W = np.linalg.det(T) / (np.trace(T) / p) ** p
    d = 1 - (2 * p ** 2 + p + 2) / (6 * p * (n - 1))
    chi = -(n - 1) * d * np.log(W) if W > 0 else np.inf
    dfm = p * (p + 1) / 2 - 1
    pm = stats.chi2.sf(chi, dfm) if p > 1 else np.nan
    gg = np.trace(T) ** 2 / (p * np.trace(T @ T))
    hf = (n * p * gg - 2) / (p * (n - 1 - p * gg))
    hf = min(hf, 1.0)
    return W, chi, dfm, pm, gg, hf


@register("rmanova", "repeated", "Repeated-measures ANOVA (one-way)", "تحليل التباين للقياسات المتكررة",
          [P("measures", "Repeated measurements (columns, in time order)", "القياسات المتكررة (أعمدة بالترتيب الزمني)", "vars_num"),
           P("adjust", "Pairwise p adjustment", "تصحيح المقارنات الثنائية", "choice", P_ADJ, "Bonferroni")],
          "Mauchly's sphericity test, Greenhouse-Geisser and Huynh-Feldt corrections, partial η², pairwise paired t-tests.",
          "اختبار موكلي للكروية وتصحيحات جرينهاوس-جايسر وهوين-فيلدت وحجم الأثر والمقارنات الثنائية.")
def rmanova(df, measures, adjust="Bonferroni"):
    if len(measures) < 2:
        raise AnalysisError("Select at least 2 repeated measurement columns.")
    d = pd.DataFrame({m: numeric(df, m) for m in measures}).dropna()
    Y = d.to_numpy(float)
    n, k = Y.shape
    gm = Y.mean()
    ss_time = n * ((Y.mean(0) - gm) ** 2).sum()
    ss_subj = k * ((Y.mean(1) - gm) ** 2).sum()
    ss_tot = ((Y - gm) ** 2).sum()
    ss_err = ss_tot - ss_time - ss_subj
    df1, df2 = k - 1, (k - 1) * (n - 1)
    Fv = (ss_time / df1) / (ss_err / df2)
    W, chi, dfm, pm, gg, hf = sphericity(Y) if k > 2 else (1, 0, 0, np.nan, 1, 1)
    peta = ss_time / (ss_time + ss_err)
    rows = []
    for name, eps in [("Sphericity assumed", 1.0), ("Greenhouse-Geisser", gg), ("Huynh-Feldt", hf), ("Lower-bound", 1 / (k - 1))]:
        rows.append({"Correction": name, "ε": eps, "df1": df1 * eps, "df2": df2 * eps, "F": Fv,
                     "p": stats.f.sf(Fv, df1 * eps, df2 * eps), "Partial η²": peta})
    res = Result("Repeated-measures ANOVA", f"{k} time points, n = {n} complete subjects")
    res.table(describe_groups({m: Y[:, i] for i, m in enumerate(measures)}), "Descriptive statistics")
    if k > 2:
        res.table(pd.DataFrame([{"Mauchly's W": W, "χ²": chi, "df": dfm, "p": pm, "GG ε": gg, "HF ε": hf}]),
                  "Mauchly's test of sphericity")
    res.table(pd.DataFrame(rows), "Tests of within-subjects effects",
              f"SS(time) = {ss_time:.3f}, SS(error) = {ss_err:.3f}, SS(subjects) = {ss_subj:.3f}.")
    pr = []
    for i, j in itertools.combinations(range(k), 2):
        t = stats.ttest_rel(Y[:, i], Y[:, j])
        pr.append([measures[i], measures[j], (Y[:, i] - Y[:, j]).mean(), t.statistic, t.pvalue])
    padj = p_adjust([r[4] for r in pr], adjust)
    ptab = pd.DataFrame([r + [p] for r, p in zip(pr, padj)], columns=["A", "B", "Mean diff.", "t", "p (unadj.)", "p (adj.)"])
    res.table(ptab, f"Pairwise comparisons (paired t, {adjust})", p_columns=("p (unadj.)", "p (adj.)"))
    use = rows[1] if (k > 2 and pm < 0.05) else rows[0]
    s = sig_words(use["p"])
    res.interpret(f"{'Sphericity was violated (Mauchly ' + pstr(pm) + '), so the Greenhouse-Geisser correction is reported. ' if k > 2 and pm < 0.05 else ''}"
                  f"The change over time is {s[0]} (F({use['df1']:.2f}, {use['df2']:.2f}) = {Fv:.2f}, {pstr(use['p'])}, partial η² = {peta:.3f}, "
                  f"{magnitude_eta(peta)[0]} effect). For unbalanced data or dropouts, prefer the linear mixed model.",
                  f"{'تم انتهاك افتراض الكروية، لذا يُعرض تصحيح جرينهاوس-جايسر. ' if k > 2 and pm < 0.05 else ''}"
                  f"التغير عبر الزمن {s[1]} (F = {Fv:.2f}، {pstr(use['p'])}، η² الجزئي = {peta:.3f}). "
                  "في حال وجود قيم مفقودة أو انسحاب، يُفضّل النموذج المختلط الخطي.")
    res.methods(f"Changes across the {k} time points were analysed by one-way repeated-measures ANOVA; sphericity was tested "
                f"with Mauchly's test and the Greenhouse-Geisser correction applied when violated. Pairwise comparisons used paired "
                f"t-tests with {adjust} correction.")
    res.figure_auto(F.group_plot({m: Y[:, i] for i, m in enumerate(measures)}, ylabel="Value", paired=True,
                                 comparisons=[(r[0], r[1], p) for r, p in zip(pr, padj)],
                                 test_name=f"repeated-measures ANOVA with paired t-tests ({adjust} correction); lines join the same subject"))
    return res


@register("friedman", "repeated", "Friedman test", "اختبار فريدمان",
          [P("measures", "Repeated measurements (columns)", "القياسات المتكررة (أعمدة)", "vars_num"),
           P("adjust", "Pairwise p adjustment", "تصحيح المقارنات الثنائية", "choice", P_ADJ, "Bonferroni")],
          "Non-parametric repeated measures with Kendall's W and Wilcoxon pairwise tests.",
          "بديل لامعلمي للقياسات المتكررة مع معامل كندال W.")
def friedman(df, measures, adjust="Bonferroni"):
    d = pd.DataFrame({m: numeric(df, m) for m in measures}).dropna()
    Y = d.to_numpy(float)
    n, k = Y.shape
    chi, p = stats.friedmanchisquare(*[Y[:, i] for i in range(k)])
    Wk = chi / (n * (k - 1))
    res = Result("Friedman test", f"{k} conditions, n = {n}")
    res.table(describe_groups({m: Y[:, i] for i, m in enumerate(measures)})[["Group", "n", "Median", "IQR"]], "Medians")
    res.table(pd.DataFrame([{"χ²": chi, "df": k - 1, "p": p, "Kendall's W": Wk}]), "Friedman test")
    pr = []
    for i, j in itertools.combinations(range(k), 2):
        w = stats.wilcoxon(Y[:, i], Y[:, j])
        pr.append([measures[i], measures[j], np.median(Y[:, i] - Y[:, j]), w.statistic, w.pvalue])
    padj = p_adjust([r[4] for r in pr], adjust)
    res.table(pd.DataFrame([r + [q] for r, q in zip(pr, padj)], columns=["A", "B", "Median diff.", "W", "p (unadj.)", "p (adj.)"]),
              f"Pairwise Wilcoxon signed-rank ({adjust})", p_columns=("p (unadj.)", "p (adj.)"))
    s = sig_words(p)
    res.interpret(f"Differences among conditions are {s[0]} (χ²({k-1}) = {chi:.2f}, {pstr(p)}; Kendall's W = {Wk:.3f}).",
                  f"الفروق بين القياسات {s[1]} (χ² = {chi:.2f}، {pstr(p)}؛ W = {Wk:.3f}).")
    return res


@register("mixed", "repeated", "Linear mixed model (long format)", "النموذج الخطي المختلط",
          [P("outcome", "Outcome", "المتغير التابع", "var_num"), P("subject", "Subject ID", "رقم الحالة", "var_any"),
           P("time", "Time / within factor", "الزمن / العامل الداخلي", "var_any"),
           P("group", "Between-subject group (optional)", "مجموعة بين الأفراد (اختياري)", "var_cat", optional=True),
           P("covariates", "Covariates (optional)", "متغيرات مصاحبة (اختياري)", "vars_any", optional=True),
           P("time_type", "Treat time as", "معاملة الزمن كـ", "choice", ["Categorical", "Continuous"], "Categorical"),
           P("random", "Random effects", "التأثيرات العشوائية", "choice", ["Random intercept", "Random intercept + slope (time)"], "Random intercept")],
          "REML linear mixed-effects model: handles missing visits and unbalanced designs (preferred to RM-ANOVA).",
          "نموذج مختلط بطريقة REML يتعامل مع الزيارات المفقودة والتصاميم غير المتوازنة.")
def mixed(df, outcome, subject, time, group=None, covariates=None, time_type="Categorical", random="Random intercept"):
    covariates = list(covariates or [])
    cols = [outcome, subject, time] + ([group] if group else []) + covariates
    d = df[cols].copy().dropna()
    ren = {outcome: "Y", subject: "S", time: "T"}
    if group:
        ren[group] = "G"
    for i, c in enumerate(covariates):
        ren[c] = f"X{i}"
    d = d.rename(columns=ren)
    d["Y"] = pd.to_numeric(d["Y"], errors="coerce")
    d = d.dropna()
    tterm = "C(T)" if time_type == "Categorical" else "T"
    if time_type == "Continuous":
        d["T"] = pd.to_numeric(d["T"], errors="coerce")
    else:
        d["T"] = d["T"].astype(str)
    rhs = tterm + (" * C(G)" if group else "") + "".join(f" + X{i}" for i in range(len(covariates)))
    re_formula = "~T" if (random.endswith("(time)") and time_type == "Continuous") else "1"
    md = smf.mixedlm(f"Y ~ {rhs}", d, groups=d["S"], re_formula=re_formula)
    try:
        m = md.fit(reml=True, method=["lbfgs", "powell"])
    except Exception as e:
        raise AnalysisError(f"Model did not converge: {e}")
    ci = m.conf_int()
    rows = []
    for name in m.fe_params.index:
        nm = name.replace("C(T)", time).replace("C(G)", group or "").replace("[T.", "[")
        for i, c in enumerate(covariates):
            nm = nm.replace(f"X{i}", c)
        rows.append({"Term": nm, "Estimate": m.fe_params[name], "SE": m.bse_fe[name], "z": m.tvalues[name],
                     "p": m.pvalues[name], "95% CI lower": ci.loc[name, 0], "95% CI upper": ci.loc[name, 1]})
    res = Result("Linear mixed-effects model", f"{outcome} ~ {rhs.replace('C(T)', time).replace('C(G)', group or '')} + (1 | {subject})")
    res.table(pd.DataFrame(rows), "Fixed effects (REML)")
    vc = [{"Component": f"{subject} (intercept) variance", "Estimate": float(m.cov_re.iloc[0, 0])},
          {"Component": "Residual variance", "Estimate": float(m.scale)}]
    icc = vc[0]["Estimate"] / (vc[0]["Estimate"] + vc[1]["Estimate"])
    vc.append({"Component": "ICC (subject)", "Estimate": icc})
    res.table(pd.DataFrame(vc), "Random effects")
    # Wald tests for whole terms
    wt = []
    try:
        w = m.wald_test_terms(skip_single=False, scalar=True)
        for nm, r in w.table.iterrows():
            if nm in ("Intercept", "Group Var"):
                continue
            wt.append({"Term": nm.replace("C(T)", time).replace("C(G)", group or "").replace(":", " × "),
                       "χ²": float(r["statistic"]), "df": int(r["df_constraint"]), "p": float(r["pvalue"])})
        res.table(pd.DataFrame(wt), "Type III Wald tests of fixed effects")
    except Exception:
        pass
    res.note(f"n = {d.S.nunique()} subjects, {len(d)} observations. Log-likelihood (REML) = {m.llf:.2f}. "
             f"Estimation: REML; covariance: {random}.")
    inter = [r for r in wt if "×" in r["Term"]]
    en = f"The model used all {len(d)} available observations from {d.S.nunique()} subjects (no listwise deletion). "
    ar = f"استخدم النموذج جميع المشاهدات المتاحة ({len(d)}) من {d.S.nunique()} حالة دون حذف الحالات الناقصة. "
    if inter:
        s = sig_words(inter[0]["p"])
        en += f"The {inter[0]['Term']} interaction — i.e. whether the time course differs between groups (the key treatment effect) — is {s[0]} ({pstr(inter[0]['p'])}). "
        ar += f"التفاعل {inter[0]['Term']} — أي اختلاف مسار الزمن بين المجموعات (وهو تأثير العلاج الأساسي) — {s[1]} ({pstr(inter[0]['p'])}). "
    en += f"Subject-level ICC = {icc:.2f}: {icc*100:.0f}% of the variance is between subjects."
    ar += f"معامل الارتباط داخل الأفراد ICC = {icc:.2f}."
    res.interpret(en, ar)
    # profile plot
    if time_type == "Categorical" or True:
        tl = sorted(d["T"].unique(), key=lambda v: (str(type(v)), v))
        series, errs = {}, {}
        for gname, sub in (d.groupby("G") if group else [("All", d)]):
            mm = sub.groupby("T")["Y"]
            series[gname] = [mm.mean().get(t, np.nan) for t in tl]
            errs[gname] = [(mm.std() / np.sqrt(mm.count())).get(t, np.nan) for t in tl]
        res.figure(F.line_profile(tl, series, ylabel=outcome, xlabel=time, errs=errs), "Observed means ± SEM over time.")
    res.methods(f"Longitudinal data were analysed with a linear mixed-effects model (REML) with {time}"
                f"{' , ' + group + ' and their interaction' if group else ''} as fixed effects and a random intercept for {subject}"
                f"{' and random slope for time' if re_formula != '1' else ''}, using all available observations under a missing-at-random assumption.")
    return res


@register("gee", "repeated", "GEE (binary / count repeated outcomes)", "معادلات التقدير المعممة GEE",
          [P("outcome", "Outcome", "المتغير التابع", "var_num"), P("subject", "Subject / cluster ID", "رقم الحالة/العنقود", "var_any"),
           P("predictors", "Predictors", "المتغيرات المستقلة", "vars_any"),
           P("family", "Outcome type", "نوع المتغير التابع", "choice", ["Binary (logit)", "Count (Poisson)", "Continuous (Gaussian)"], "Binary (logit)"),
           P("corr", "Working correlation", "مصفوفة الارتباط", "choice", ["Exchangeable", "Independence", "AR(1)"], "Exchangeable")],
          "Population-averaged effects with robust (sandwich) standard errors.", "تأثيرات متوسطة على مستوى المجتمع مع أخطاء معيارية قوية.")
def gee(df, outcome, subject, predictors, family="Binary (logit)", corr="Exchangeable"):
    cols = [outcome, subject] + list(predictors)
    d = df[cols].dropna().copy()
    ren = {outcome: "Y", subject: "S"}
    terms = []
    for i, p in enumerate(predictors):
        ren[p] = f"X{i}"
        terms.append(f"X{i}" if pd.api.types.is_numeric_dtype(df[p]) and df[p].nunique() > 2 else f"C(X{i})")
    d = d.rename(columns=ren)
    if family.startswith("Binary"):
        from ..core.data import binary01
        d["Y"], _ = binary01(d, "Y")
        fam = sm.families.Binomial()
    elif family.startswith("Count"):
        fam = sm.families.Poisson()
    else:
        fam = sm.families.Gaussian()
    cs = {"Exchangeable": sm.cov_struct.Exchangeable(), "Independence": sm.cov_struct.Independence(),
          "AR(1)": sm.cov_struct.Autoregressive()}[corr]
    m = smf.gee("Y ~ " + " + ".join(terms), "S", d, family=fam, cov_struct=cs).fit()
    ci = m.conf_int()
    exp = not family.startswith("Continuous")
    lab = "OR" if family.startswith("Binary") else "IRR" if family.startswith("Count") else "B"
    rows = []
    for nm in m.params.index:
        out = nm
        for i, p in enumerate(predictors):
            out = out.replace(f"C(X{i})", p).replace(f"X{i}", p)
        rows.append({"Term": out, "B": m.params[nm], "Robust SE": m.bse[nm], "z": m.tvalues[nm], "p": m.pvalues[nm],
                     lab: np.exp(m.params[nm]) if exp else m.params[nm],
                     "95% CI lower": np.exp(ci.loc[nm, 0]) if exp else ci.loc[nm, 0],
                     "95% CI upper": np.exp(ci.loc[nm, 1]) if exp else ci.loc[nm, 1]})
    res = Result("Generalized estimating equations", f"{family}, {corr} working correlation, {d.S.nunique()} clusters")
    res.table(pd.DataFrame(rows), "GEE parameter estimates (robust SE)")
    res.interpret("Estimates are population-averaged (marginal) effects with sandwich standard errors robust to misspecification of the working correlation.",
                  "التقديرات تمثل التأثيرات المتوسطة على مستوى المجتمع مع أخطاء معيارية قوية.")
    return res
