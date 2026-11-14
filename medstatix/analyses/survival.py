"""Survival analysis: Kaplan-Meier, log-rank family, Cox proportional hazards."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.duration.hazard_regression import PHReg
from statsmodels.duration.survfunc import SurvfuncRight, survdiff

from ..core.data import binary01, numeric, _level_order
from ..core.result import Result, AnalysisError
from ..plots import figures as F
from .common import pstr, sig_words
from .registry import register, P


def _surv_data(df, time, event, group=None):
    t = numeric(df, time)
    e, _ = binary01(df, event) if df[event].nunique() == 2 else (numeric(df, event), "")
    d = pd.DataFrame({"t": t, "e": e})
    if group:
        d["g"] = df[group].astype(str).where(df[group].notna())
    d = d.dropna()
    if (d.t < 0).any():
        raise AnalysisError("Survival times must be non-negative.")
    return d


@register("km", "survival", "Kaplan-Meier + log-rank", "منحنى كابلان-ماير واختبار اللوغ-رانك",
          [P("time", "Time variable", "متغير الزمن", "var_num"), P("event", "Event (1 = event, 0 = censored)", "الحدث (1 = حدث، 0 = مراقب)", "var_any"),
           P("group", "Group (optional)", "المجموعة (اختياري)", "var_cat", optional=True),
           P("time_unit", "Time unit label", "وحدة الزمن", "text", default="Months"),
           P("show_ci", "Show 95% CI band", "إظهار فترة الثقة", "bool", default=True),
           P("risk_table", "Number-at-risk table", "جدول الأعداد المعرضة للخطر", "bool", default=True)],
          "Survival curves with median survival (95% CI), log-rank, Breslow (Wilcoxon) and Tarone-Ware tests.",
          "منحنيات البقاء مع الوسيط وفترة الثقة واختبارات لوغ-رانك وبريسلو وتارون-وير.")
def km(df, time, event, group=None, time_unit="Months", show_ci=True, risk_table=True):
    d = _surv_data(df, time, event, group)
    groups = [(g, d[d.g == g]) for g in _level_order(d.g)] if group else [("All", d)]
    res = Result("Kaplan-Meier survival analysis", f"Time: {time}; event: {event}" + (f"; groups: {group}" if group else ""))
    curves, summ = {}, []
    tmax = d.t.max()
    grid = np.unique(np.round(np.linspace(0, tmax, 6), 1))
    rt = {"times": grid, "n": {}}
    for gname, sub in groups:
        sf = SurvfuncRight(sub.t.values, sub.e.values)
        t = np.concatenate([[0], sf.surv_times])
        s = np.concatenate([[1], sf.surv_prob])
        se = np.concatenate([[0], sf.surv_prob_se])
        # log-log CI (as in R/SPSS default 'log-log' in Stata)
        with np.errstate(divide="ignore", invalid="ignore"):
            ll = np.log(-np.log(s))
            sell = se / (s * np.abs(np.log(s)))
            lo = np.exp(-np.exp(ll + 1.96 * sell))
            hi = np.exp(-np.exp(ll - 1.96 * sell))
        lo[0], hi[0] = 1, 1
        if sub.t.max() > t[-1]:  # extend the curve to the last (censored) follow-up time
            t = np.append(t, sub.t.max()); s = np.append(s, s[-1]); lo = np.append(lo, lo[-1]); hi = np.append(hi, hi[-1])
        lo, hi = np.nan_to_num(lo, nan=1.0), np.nan_to_num(hi, nan=1.0)
        cens = sub[sub.e == 0].t.values
        cs = [s[np.searchsorted(t, c, side="right") - 1] for c in cens]
        curves[gname] = (t, s, lo if show_ci else None, hi, cens, cs)
        try:
            med = sf.quantile(0.5)
            mci = sf.quantile_ci(0.5, method="cloglog")
        except Exception:
            med, mci = np.nan, (np.nan, np.nan)
        # restricted mean survival up to max time
        rmst = np.sum(np.diff(np.concatenate([t, [tmax]])) * s)
        summ.append({"Group": gname, "n": len(sub), "Events": int(sub.e.sum()), "Censored": int((sub.e == 0).sum()),
                     "Median survival": med if med is not None else np.nan,
                     "Median 95% CI": f"{mci[0] if mci[0] is not None else np.nan:.2f} – {mci[1] if mci[1] is not None else np.nan:.2f}",
                     f"RMST (to {tmax:g})": rmst})
        rt["n"][gname] = [int((sub.t >= gt).sum()) for gt in grid]
    st = pd.DataFrame(summ)
    res.table(st, "Survival summary", "Median survival with Brookmeyer-Crowley (cloglog) CI; NaN = median not reached. RMST = restricted mean survival time.")
    # survival at landmark times
    lm = []
    for gname, sub in groups:
        sf = SurvfuncRight(sub.t.values, sub.e.values)
        for gt in grid[1:-1]:
            i = np.searchsorted(sf.surv_times, gt, side="right") - 1
            lm.append({"Group": gname, f"Time ({time_unit})": gt, "Survival %": (sf.surv_prob[i] if i >= 0 else 1) * 100,
                       "SE %": (sf.surv_prob_se[i] if i >= 0 else 0) * 100, "At risk": int((sub.t >= gt).sum())})
    res.table(pd.DataFrame(lm), "Survival probability at landmark times")
    ptxt = ""
    if group and len(groups) > 1:
        tests = []
        for name, wt in [("Log-rank (Mantel-Cox)", None), ("Breslow (generalized Wilcoxon)", "gb"), ("Tarone-Ware", "tw"), ("Fleming-Harrington", "fh")]:
            try:
                chi, p = survdiff(d.t.values, d.e.values, d.g.values, weight_type=wt) if wt else survdiff(d.t.values, d.e.values, d.g.values)
                tests.append({"Test": name, "χ²": chi, "df": len(groups) - 1, "p": p})
            except Exception:
                pass
        res.table(pd.DataFrame(tests), "Comparison of survival distributions")
        p_lr = tests[0]["p"]
        ptxt = f"Log-rank {pstr(p_lr)}"
        s = sig_words(p_lr)
        meds = "; ".join(f"{r['Group']}: {r['Median survival']:.1f}" if not pd.isna(r['Median survival']) else f"{r['Group']}: not reached" for r in summ)
        res.interpret(f"Survival differs between groups: {s[0]} (log-rank χ²({len(groups)-1}) = {tests[0]['χ²']:.2f}, {pstr(p_lr)}). "
                      f"Median survival ({time_unit}) — {meds}. If curves cross, the Breslow test (early differences) or RMST are more informative; "
                      "quantify the effect with Cox regression (hazard ratio).",
                      f"يختلف البقاء بين المجموعات: {s[1]} (لوغ-رانك χ² = {tests[0]['χ²']:.2f}، {pstr(p_lr)}). وسيط البقاء — {meds}. "
                      "لتقدير حجم التأثير استخدم انحدار كوكس (نسبة الخطورة).")
    else:
        r = summ[0]
        res.interpret(f"{r['Events']} events among {r['n']} subjects; median survival = {r['Median survival']:.2f} {time_unit}.",
                      f"{r['Events']} حدثًا بين {r['n']} حالة؛ وسيط البقاء = {r['Median survival']:.2f} {time_unit}.")
    res.figure(F.km_plot(curves, xlabel=f"Time ({time_unit})", risk_table=rt if risk_table else None, ptext=ptxt, ci=show_ci),
               "Kaplan-Meier survival curves (tick marks = censored observations" + (", shaded = 95% CI" if show_ci else "") + ").")
    res.methods(f"Survival was estimated with the Kaplan-Meier method and compared between groups with the log-rank test; "
                f"median survival is reported with 95% CI. {ptxt}.")
    return res


def harrell_c(time, event, risk):
    time, event, risk = map(np.asarray, (time, event, risk))
    conc = disc = ties = 0
    for i in range(len(time)):
        if not event[i]:
            continue
        mask = time > time[i]
        conc += (risk[i] > risk[mask]).sum()
        disc += (risk[i] < risk[mask]).sum()
        ties += (risk[i] == risk[mask]).sum()
    tot = conc + disc + ties
    return (conc + 0.5 * ties) / tot if tot else np.nan


@register("cox", "survival", "Cox proportional hazards regression", "انحدار كوكس للمخاطر النسبية",
          [P("time", "Time variable", "متغير الزمن", "var_num"), P("event", "Event (1/0)", "الحدث (1/0)", "var_any"),
           P("predictors", "Covariates", "المتغيرات المستقلة", "vars_any"),
           P("categorical", "Treat as categorical (optional)", "معاملة كفئوية (اختياري)", "vars_any", optional=True),
           P("strata", "Stratify by (optional)", "التقسيم الطبقي (اختياري)", "var_cat", optional=True)],
          "Hazard ratios with 95% CI (Efron ties), Harrell's C, likelihood-ratio test and Schoenfeld-residual PH test.",
          "نسب الخطورة وفترات الثقة ومؤشر هاريل C واختبار افتراض تناسب المخاطر ببواقي شونفيلد.")
def cox(df, time, event, predictors, categorical=None, strata=None):
    categorical = set(categorical or [])
    d = _surv_data(df, time, event)
    X = pd.DataFrame(index=d.index)
    names = []
    for p in predictors:
        col = df.loc[d.index, p]
        if p in categorical or not pd.api.types.is_numeric_dtype(col):
            levels = _level_order(col)
            for lv in levels[1:]:
                nm = f"{p} [{lv} vs {levels[0]}]"
                X[nm] = (col == lv).astype(float).where(col.notna())
                names.append(nm)
        else:
            X[p] = pd.to_numeric(col, errors="coerce")
            names.append(p)
    full = pd.concat([d, X], axis=1)
    if strata:
        full["strata"] = df.loc[d.index, strata].astype(str)
    full = full.dropna()
    m = PHReg(full.t.values, full[names].values, status=full.e.values, ties="efron",
              strata=full["strata"].values if strata else None).fit()
    ci = m.conf_int()
    rows = []
    for i, nm in enumerate(names):
        rows.append({"Covariate": nm, "B": m.params[i], "SE": m.bse[i], "Wald χ²": (m.params[i] / m.bse[i]) ** 2,
                     "p": m.pvalues[i], "HR": np.exp(m.params[i]), "95% CI lower": np.exp(ci[i, 0]), "95% CI upper": np.exp(ci[i, 1])})
    # LR test vs null
    m0 = PHReg(full.t.values, np.zeros((len(full), 1)), status=full.e.values, ties="efron",
               strata=full["strata"].values if strata else None)
    ll0 = m0.loglike(np.zeros(1))
    lr = 2 * (m.llf - ll0)
    plr = stats.chi2.sf(lr, len(names))
    risk = full[names].values @ m.params
    C = harrell_c(full.t.values, full.e.values, risk)
    res = Result("Cox proportional hazards regression", f"n = {len(full)}, events = {int(full.e.sum())}" + (f", stratified by {strata}" if strata else ""))
    res.table(pd.DataFrame(rows), "Hazard ratios", "Efron method for ties (as in R coxph / Stata).")
    res.table(pd.DataFrame([{"−2 Log-likelihood": -2 * m.llf, "LR χ²": lr, "df": len(names), "p": plr, "Harrell's C": C}]), "Model fit")
    # PH assumption: Schoenfeld residuals vs rank of time
    try:
        sch = m.schoenfeld_residuals
        ev = full.e.values.astype(bool)
        tt = stats.rankdata(full.t.values[ev])
        ph = []
        for i, nm in enumerate(names):
            r_ = sch[ev, i]
            ok = ~np.isnan(r_)
            rho, p = stats.pearsonr(tt[ok], r_[ok])
            ph.append({"Covariate": nm, "ρ (Schoenfeld vs rank time)": rho, "p": p,
                       "PH assumption": "Violated" if p < 0.05 else "Holds"})
        res.table(pd.DataFrame(ph), "Test of proportional hazards assumption")
        viol = [r["Covariate"] for r in ph if r["p"] < 0.05]
    except Exception:
        viol = []
    epv = full.e.sum() / max(len(names), 1)
    if epv < 10:
        res.warning(f"Events per variable = {epv:.1f} (< 10): estimates may be unstable.")
    en = f"The model is {'significant' if plr < 0.05 else 'not significant'} (LR χ²({len(names)}) = {lr:.2f}, {pstr(plr)}); Harrell's C = {C:.3f}. "
    ar = f"النموذج {'دال' if plr < 0.05 else 'غير دال'} ({pstr(plr)})؛ مؤشر هاريل C = {C:.3f}. "
    for r in rows:
        if r["p"] < 0.05:
            en += f"{r['Covariate']}: HR = {r['HR']:.2f} (95% CI {r['95% CI lower']:.2f}–{r['95% CI upper']:.2f}, {pstr(r['p'])}) — {abs(r['HR']-1)*100:.0f}% {'higher' if r['HR'] > 1 else 'lower'} hazard. "
            ar += f"{r['Covariate']}: نسبة الخطورة = {r['HR']:.2f} ({pstr(r['p'])}) — خطر {'أعلى' if r['HR'] > 1 else 'أقل'} بنسبة {abs(r['HR']-1)*100:.0f}%. "
    if viol:
        en += f"Proportional-hazards assumption violated for {', '.join(viol)}: stratify on it or add a time interaction."
        ar += f"افتراض تناسب المخاطر منتهك لـ {', '.join(viol)}: استخدم التقسيم الطبقي أو تفاعلًا مع الزمن."
    res.interpret(en, ar)
    res.figure(F.forest_plot([r["Covariate"] for r in rows], np.log([r["HR"] for r in rows]),
                             np.log([r["95% CI lower"] for r in rows]), np.log([r["95% CI upper"] for r in rows]),
                             xlabel="Hazard ratio (95% CI)", log_scale=True), "Forest plot of hazard ratios.")
    res.methods(f"Cox proportional hazards regression (Efron ties) estimated hazard ratios with 95% CIs. The proportional-hazards "
                f"assumption was assessed with Schoenfeld residuals; discrimination with Harrell's C-index ({C:.3f}).")
    return res
