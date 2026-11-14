"""Regression: linear, logistic (binary, ordinal), Poisson / negative binomial."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats
from statsmodels.stats.outliers_influence import variance_inflation_factor

from ..core.data import binary01, numeric
from ..core.result import Result, AnalysisError
from ..plots import figures as F
from .common import pstr, sig_words
from .registry import register, P


def _design(df, outcome, predictors, categorical=None):
    categorical = set(categorical or [])
    cols = [outcome] + list(predictors)
    d = df[cols].copy()
    ren = {outcome: "Y"}
    terms = []
    labels = {}
    for i, p in enumerate(predictors):
        key = f"X{i}"
        ren[p] = key
        is_cat = p in categorical or not pd.api.types.is_numeric_dtype(df[p])
        if is_cat:
            terms.append(f"C({key})")
        else:
            d[p] = pd.to_numeric(d[p], errors="coerce")
            terms.append(key)
        labels[key] = p
    d = d.rename(columns=ren).dropna()
    for i, p in enumerate(predictors):
        if terms[i].startswith("C("):
            d[f"X{i}"] = d[f"X{i}"].astype(str)
    return d, terms, labels


def _pretty(name, labels):
    out = name
    for k, v in sorted(labels.items(), key=lambda kv: -len(kv[0])):
        out = out.replace(f"C({k})[T.", f"{v} [").replace(f"C({k})", v).replace(k, v)
    return out


def _vif(model):
    X = model.model.exog
    names = model.model.exog_names
    out = {}
    for i, n in enumerate(names):
        if n == "Intercept":
            continue
        try:
            out[n] = variance_inflation_factor(X, i)
        except Exception:
            out[n] = np.nan
    return out


@register("linreg", "regression", "Linear regression (simple / multiple)", "الانحدار الخطي البسيط والمتعدد",
          [P("outcome", "Dependent variable", "المتغير التابع", "var_num"),
           P("predictors", "Independent variables", "المتغيرات المستقلة", "vars_any"),
           P("categorical", "Treat as categorical (optional)", "معاملة كمتغيرات فئوية (اختياري)", "vars_any", optional=True),
           P("robust", "Standard errors", "الأخطاء المعيارية", "choice", ["Classical", "Robust (HC3)"], "Classical")],
          "B, SE, standardized β, 95% CI, VIF, R²/adjusted R², ANOVA and residual diagnostics.",
          "المعاملات والمعاملات المعيارية وفترات الثقة وعامل تضخم التباين ومعامل التحديد وتشخيص البواقي.")
def linreg(df, outcome, predictors, categorical=None, robust="Classical"):
    if not predictors:
        raise AnalysisError("Select at least one predictor.")
    d, terms, labels = _design(df, outcome, predictors, categorical)
    d["Y"] = pd.to_numeric(d["Y"], errors="coerce")
    d = d.dropna()
    m = smf.ols("Y ~ " + " + ".join(terms), data=d).fit(cov_type="HC3" if robust.startswith("Robust") else "nonrobust")
    ci = m.conf_int()
    vif = _vif(m) if len(m.params) > 2 else {}
    sdy = d["Y"].std()
    rows = []
    for n in m.params.index:
        beta = np.nan
        if n != "Intercept" and n in d.columns:
            beta = m.params[n] * d[n].std() / sdy
        rows.append({"Term": _pretty(n, labels), "B": m.params[n], "SE": m.bse[n], "β (std.)": beta, "t": m.tvalues[n],
                     "p": m.pvalues[n], "95% CI lower": ci.loc[n, 0], "95% CI upper": ci.loc[n, 1], "VIF": vif.get(n, np.nan)})
    res = Result("Linear regression", f"{outcome} ~ {' + '.join(predictors)} (n = {int(m.nobs)})")
    res.table(pd.DataFrame([{"R": math.sqrt(max(m.rsquared, 0)), "R²": m.rsquared, "Adjusted R²": m.rsquared_adj,
                             "SE of estimate": math.sqrt(m.mse_resid), "F": m.fvalue, "df1": m.df_model, "df2": m.df_resid,
                             "p": m.f_pvalue, "AIC": m.aic, "BIC": m.bic,
                             "Durbin-Watson": sm.stats.durbin_watson(m.resid)}]), "Model summary")
    res.table(pd.DataFrame(rows), "Coefficients", "B = unstandardized coefficient; β = standardized coefficient; "
              "VIF > 5 suggests problematic multicollinearity." + (" HC3 heteroscedasticity-robust SEs." if robust.startswith("Robust") else ""))
    sw = stats.shapiro(m.resid) if len(m.resid) <= 5000 else (np.nan, np.nan)
    bp = sm.stats.het_breuschpagan(m.resid, m.model.exog)
    infl = m.get_influence().cooks_distance[0]
    res.table(pd.DataFrame([{"Check": "Normality of residuals (Shapiro-Wilk)", "Statistic": sw[0], "p": sw[1]},
                            {"Check": "Homoscedasticity (Breusch-Pagan)", "Statistic": bp[0], "p": bp[1]},
                            {"Check": "Influential points (Cook's D > 4/n)", "Statistic": int((infl > 4 / len(infl)).sum()), "p": np.nan},
                            {"Check": "Max VIF", "Statistic": max(vif.values()) if vif else np.nan, "p": np.nan}]),
              "Assumption diagnostics")
    sigs = [r for r in rows if r["Term"] != "Intercept" and r["p"] < 0.05]
    en = (f"The model explains {m.rsquared*100:.1f}% of the variance in {outcome} (adjusted R² = {m.rsquared_adj:.3f}; "
          f"F({m.df_model:.0f}, {m.df_resid:.0f}) = {m.fvalue:.2f}, {pstr(m.f_pvalue)}). ")
    ar = (f"يفسّر النموذج {m.rsquared*100:.1f}% من التباين في {outcome} (R² المعدل = {m.rsquared_adj:.3f}؛ {pstr(m.f_pvalue)}). ")
    for r in sigs:
        en += f"Each one-unit increase in {r['Term']} is associated with a {r['B']:.3f} change in {outcome} (95% CI {r['95% CI lower']:.3f} to {r['95% CI upper']:.3f}, {pstr(r['p'])}). "
        ar += f"كل زيادة بوحدة واحدة في {r['Term']} ترتبط بتغير قدره {r['B']:.3f} في {outcome} ({pstr(r['p'])}). "
    if not sigs:
        en += "No predictor was significant. "
        ar += "لم يكن أي متغير مستقل دالًا. "
    if bp[1] < 0.05:
        en += "Heteroscedasticity detected — rerun with robust (HC3) standard errors."
        ar += "تم رصد عدم تجانس التباين — أعد التحليل بالأخطاء المعيارية القوية (HC3)."
    res.interpret(en, ar)
    res.figure(F.regression_diagnostics(m.fittedvalues, m.resid, infl), "Residual diagnostics.")
    if len(predictors) == 1 and terms[0] == "X0":
        res.figure(F.scatter_fit(d["X0"], d["Y"], predictors[0], outcome,
                                 annotate=f"y = {m.params.iloc[0]:.3f} + {m.params.iloc[1]:.3f}x\nR² = {m.rsquared:.3f}"),
                   "Regression line with 95% confidence band.")
    res.methods(f"Multiple linear regression was used to model {outcome} as a function of {', '.join(predictors)}. Assumptions of "
                f"linearity, normality and homoscedasticity of residuals and absence of multicollinearity (VIF) were checked.")
    return res


def hosmer_lemeshow(y, p, g=10):
    d = pd.DataFrame({"y": y, "p": p})
    d["dec"] = pd.qcut(d.p.rank(method="first"), g, labels=False)
    grp = d.groupby("dec").agg(obs=("y", "sum"), exp=("p", "sum"), n=("y", "count"))
    hl = (((grp.obs - grp.exp) ** 2) / (grp.exp * (1 - grp.exp / grp.n))).sum()
    return hl, stats.chi2.sf(hl, g - 2)


def auc_score(y, s):
    y = np.asarray(y)
    s = np.asarray(s, float)
    pos, neg = s[y == 1], s[y == 0]
    U = stats.mannwhitneyu(pos, neg).statistic
    return U / (len(pos) * len(neg))


def roc_curve(y, s):
    y = np.asarray(y)
    s = np.asarray(s, float)
    th = np.unique(s)[::-1]
    P_, N_ = (y == 1).sum(), (y == 0).sum()
    tpr = [0.0]
    fpr = [0.0]
    for t in th:
        pred = s >= t
        tpr.append((pred & (y == 1)).sum() / P_)
        fpr.append((pred & (y == 0)).sum() / N_)
    return np.array(fpr), np.array(tpr), np.concatenate([[np.inf], th])


@register("logreg", "regression", "Binary logistic regression", "الانحدار اللوجستي الثنائي",
          [P("outcome", "Binary outcome", "المتغير التابع الثنائي", "var_cat"),
           P("predictors", "Predictors", "المتغيرات المستقلة", "vars_any"),
           P("categorical", "Treat as categorical (optional)", "معاملة كمتغيرات فئوية (اختياري)", "vars_any", optional=True),
           P("positive", "Event category (blank = auto)", "فئة الحدث (فارغ = تلقائي)", "text", default=""),
           P("univariable", "Also show univariable (crude) ORs", "عرض نسب الأرجحية الخام أيضًا", "bool", default=True)],
          "Crude and adjusted odds ratios with 95% CI, Nagelkerke R², Hosmer-Lemeshow, AUC, classification table, EPV.",
          "نسب الأرجحية الخام والمعدلة وفترات الثقة ومعامل ناجيلكيرك واختبار هوزمر-ليميشو ومساحة ROC وجدول التصنيف.")
def logreg(df, outcome, predictors, categorical=None, positive="", univariable=True):
    yb, poslab = binary01(df, outcome, positive)
    df2 = df.copy()
    df2[outcome] = yb
    d, terms, labels = _design(df2, outcome, predictors, categorical)
    try:
        m = smf.logit("Y ~ " + " + ".join(terms), data=d).fit(disp=0, maxiter=200)
    except Exception as e:
        raise AnalysisError(f"Model failed (perfect separation or too few events?): {e}")
    ci = m.conf_int()
    n = int(m.nobs)
    events = int(d.Y.sum())
    rows = []
    for nm in m.params.index:
        rows.append({"Term": _pretty(nm, labels), "B": m.params[nm], "SE": m.bse[nm], "Wald χ²": m.tvalues[nm] ** 2,
                     "p": m.pvalues[nm], "OR": np.exp(m.params[nm]), "95% CI lower": np.exp(ci.loc[nm, 0]),
                     "95% CI upper": np.exp(ci.loc[nm, 1])})
    ll0, ll1 = m.llnull, m.llf
    cs = 1 - math.exp(2 * (ll0 - ll1) / n)
    nag = cs / (1 - math.exp(2 * ll0 / n))
    hl, hlp = hosmer_lemeshow(d.Y, m.predict(), g=min(10, max(3, n // 10)))
    auc = auc_score(d.Y, m.predict())
    res = Result("Binary logistic regression", f"P({outcome} = {poslab}) ~ {' + '.join(predictors)}; n = {n}, events = {events}")
    if univariable and len(predictors) > 1:
        urows = []
        for i, p in enumerate(predictors):
            mu = smf.logit(f"Y ~ {terms[i]}", data=d).fit(disp=0)
            cu = mu.conf_int()
            for nm in mu.params.index[1:]:
                urows.append({"Term": _pretty(nm, labels), "Crude OR": np.exp(mu.params[nm]), "95% CI lower": np.exp(cu.loc[nm, 0]),
                              "95% CI upper": np.exp(cu.loc[nm, 1]), "p": mu.pvalues[nm]})
        res.table(pd.DataFrame(urows), "Univariable (crude) analysis")
    res.table(pd.DataFrame(rows), "Multivariable model — adjusted odds ratios" if len(predictors) > 1 else "Model coefficients")
    res.table(pd.DataFrame([{"−2 Log-likelihood": -2 * ll1, "Model χ² (LR)": m.llr, "df": m.df_model, "p": m.llr_pvalue,
                             "Cox & Snell R²": cs, "Nagelkerke R²": nag, "AIC": m.aic, "C-statistic (AUC)": auc,
                             "Hosmer-Lemeshow χ²": hl, "H-L p": hlp}]), "Model fit", p_columns=("p", "H-L p"))
    pred = (m.predict() >= 0.5).astype(int)
    tp = int(((pred == 1) & (d.Y == 1)).sum()); tn = int(((pred == 0) & (d.Y == 0)).sum())
    fp = int(((pred == 1) & (d.Y == 0)).sum()); fn = int(((pred == 0) & (d.Y == 1)).sum())
    res.table(pd.DataFrame([{"Observed": f"Non-event", "Predicted non-event": tn, "Predicted event": fp, "% correct": tn / max(tn + fp, 1) * 100},
                            {"Observed": f"Event ({poslab})", "Predicted non-event": fn, "Predicted event": tp, "% correct": tp / max(tp + fn, 1) * 100},
                            {"Observed": "Overall", "Predicted non-event": np.nan, "Predicted event": np.nan, "% correct": (tp + tn) / n * 100}]),
              "Classification table (cut-off 0.5)")
    epv = min(events, n - events) / max(len(m.params) - 1, 1)
    if epv < 10:
        res.warning(f"Events per variable = {epv:.1f} (< 10): risk of overfitting and biased ORs. Reduce predictors or use penalized (Firth) regression.")
    en = (f"The model is {'statistically significant' if m.llr_pvalue < 0.05 else 'not significant'} (LR χ²({m.df_model:.0f}) = {m.llr:.2f}, "
          f"{pstr(m.llr_pvalue)}), explains {nag*100:.1f}% of variance (Nagelkerke), discriminates with AUC = {auc:.3f} and "
          f"{'shows adequate' if hlp >= 0.05 else 'shows poor'} calibration (Hosmer-Lemeshow {pstr(hlp)}). ")
    ar = (f"النموذج {'دال إحصائيًا' if m.llr_pvalue < 0.05 else 'غير دال'} ({pstr(m.llr_pvalue)})، ويفسّر {nag*100:.1f}% من التباين (ناجيلكيرك)، "
          f"وقدرته التمييزية AUC = {auc:.3f}، والمعايرة {'جيدة' if hlp >= 0.05 else 'ضعيفة'} (هوزمر-ليميشو {pstr(hlp)}). ")
    for r in rows[1:]:
        if r["p"] < 0.05:
            ch = (r["OR"] - 1) * 100
            en += f"{r['Term']}: adjusted OR = {r['OR']:.2f} (95% CI {r['95% CI lower']:.2f}–{r['95% CI upper']:.2f}, {pstr(r['p'])}), i.e. {abs(ch):.0f}% {'higher' if ch > 0 else 'lower'} odds of {poslab} per unit/category. "
            ar += f"{r['Term']}: نسبة الأرجحية المعدلة = {r['OR']:.2f} ({pstr(r['p'])})، أي احتمالات {'أعلى' if ch > 0 else 'أقل'} بنسبة {abs(ch):.0f}%. "
    res.interpret(en, ar)
    fpr, tpr, _ = roc_curve(d.Y, m.predict())
    res.figure(F.roc_plot({"Model": (fpr, tpr, auc)}), "ROC curve of the fitted model.")
    res.methods(f"Binary logistic regression was used to identify factors associated with {outcome}. Variables were entered "
                f"simultaneously; results are adjusted odds ratios with 95% CIs. Model fit was assessed with the Hosmer-Lemeshow test "
                f"and discrimination with the C-statistic (AUC = {auc:.3f}).")
    return res


@register("ordinal", "regression", "Ordinal logistic regression", "الانحدار اللوجستي الترتيبي",
          [P("outcome", "Ordinal outcome", "المتغير التابع الترتيبي", "var_any"),
           P("predictors", "Predictors", "المتغيرات المستقلة", "vars_num")],
          "Proportional-odds model (cumulative logit).", "نموذج الأرجحية النسبية التراكمي.")
def ordinal(df, outcome, predictors):
    from statsmodels.miscmodels.ordinal_model import OrderedModel
    d = df[[outcome] + list(predictors)].dropna()
    y = d[outcome]
    levels = sorted(y.unique())
    yc = pd.Categorical(y, categories=levels, ordered=True)
    X = d[list(predictors)].apply(pd.to_numeric, errors="coerce").astype(float)
    bad = [c for c in X.columns if X[c].notna().sum() == 0]
    if bad:
        raise AnalysisError(f"Predictor(s) {', '.join(bad)} are not numeric. Use numeric predictors (code categories as 0/1).")
    keep = X.notna().all(1)
    X, yc = X[keep], pd.Categorical(y[keep], categories=levels, ordered=True)
    if len(levels) > 15:
        raise AnalysisError(f"'{outcome}' has {len(levels)} different values; an ordinal outcome should have a few ordered categories (e.g. score 0-4).",
                            f"المتغير «{outcome}» به {len(levels)} قيمة مختلفة؛ الانحدار الترتيبي يحتاج فئات مرتبة قليلة (مثل درجة 0-4).")
    yc = pd.Series(yc, index=X.index)
    if len(levels) < 3:
        raise AnalysisError(f"'{outcome}' has {len(levels)} categories; ordinal regression needs ≥ 3 ordered categories (use logistic regression for 2).")
    m = OrderedModel(yc, X, distr="logit").fit(method="bfgs", disp=0)
    ci = m.conf_int()
    rows = []
    for nm in m.params.index:
        is_th = nm not in predictors
        rows.append({"Term": nm + (" (threshold)" if is_th else ""), "B": m.params[nm], "SE": m.bse[nm], "p": m.pvalues[nm],
                     "OR": np.nan if is_th else np.exp(m.params[nm]),
                     "95% CI lower": np.nan if is_th else np.exp(ci.loc[nm, 0]),
                     "95% CI upper": np.nan if is_th else np.exp(ci.loc[nm, 1])})
    res = Result("Ordinal logistic regression", f"{outcome} ({' < '.join(map(str, levels))}) ~ {' + '.join(predictors)}")
    res.table(pd.DataFrame(rows), "Proportional odds model", f"Log-likelihood = {m.llf:.2f}; AIC = {m.aic:.2f}. OR > 1 = higher outcome category.")
    res.interpret("Odds ratios express the odds of being in a higher outcome category per unit increase in the predictor, assuming proportional odds.",
                  "تعبّر نسب الأرجحية عن احتمال الانتقال لفئة أعلى من المتغير التابع لكل زيادة بوحدة، بافتراض تناسب الأرجحية.")
    return res


@register("countreg", "regression", "Poisson / negative binomial regression", "انحدار بواسون / ذو الحدين السالب",
          [P("outcome", "Count outcome", "المتغير التابع (عدّ)", "var_num"), P("predictors", "Predictors", "المتغيرات المستقلة", "vars_any"),
           P("offset", "Exposure / person-time (optional)", "زمن التعرض (اختياري)", "var_num", optional=True),
           P("family", "Model", "النموذج", "choice", ["Auto (test overdispersion)", "Poisson", "Negative binomial"], "Auto (test overdispersion)")],
          "Incidence rate ratios with 95% CI and overdispersion test.", "نسب معدلات الحدوث مع اختبار فرط التشتت.")
def countreg(df, outcome, predictors, offset=None, family="Auto (test overdispersion)"):
    d, terms, labels = _design(df if not offset else df, outcome, predictors)
    off = None
    if offset:
        off = np.log(numeric(df, offset).loc[d.index])
    f = "Y ~ " + " + ".join(terms)
    pm = smf.glm(f, d, family=sm.families.Poisson(), offset=off).fit()
    disp = pm.pearson_chi2 / pm.df_resid
    use_nb = family == "Negative binomial" or (family.startswith("Auto") and disp > 1.5)
    m = smf.glm(f, d, family=sm.families.NegativeBinomial(alpha=max(disp - 1, 0.01) / max(d.Y.mean(), 1e-6)), offset=off).fit() if use_nb else pm
    if use_nb:
        try:
            nb = smf.negativebinomial(f, d, offset=off).fit(disp=0)
            alpha = nb.params["alpha"]
            m = smf.glm(f, d, family=sm.families.NegativeBinomial(alpha=alpha), offset=off).fit()
        except Exception:
            pass
    ci = m.conf_int()
    rows = [{"Term": _pretty(n, labels), "B": m.params[n], "SE": m.bse[n], "p": m.pvalues[n], "IRR": np.exp(m.params[n]),
             "95% CI lower": np.exp(ci.loc[n, 0]), "95% CI upper": np.exp(ci.loc[n, 1])} for n in m.params.index]
    res = Result("Count regression", f"{'Negative binomial' if use_nb else 'Poisson'} model for {outcome}")
    res.table(pd.DataFrame(rows), "Incidence rate ratios", f"Pearson χ²/df (Poisson) = {disp:.2f}"
              + (" → overdispersion: negative binomial used." if use_nb else "."))
    res.interpret(f"IRR > 1 indicates a higher event rate. Dispersion ratio = {disp:.2f}; {'negative binomial' if use_nb else 'Poisson'} model selected.",
                  f"نسبة IRR أكبر من 1 تعني معدل أحداث أعلى. نسبة التشتت = {disp:.2f}؛ تم اختيار نموذج {'ذي الحدين السالب' if use_nb else 'بواسون'}.")
    return res
