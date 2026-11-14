"""Meta-analysis: fixed and random effects (DerSimonian-Laird, REML), heterogeneity, prediction interval, Egger, leave-one-out."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize_scalar

from ..core.data import numeric
from ..core.result import Result, AnalysisError
from ..plots import figures as F
from .common import pstr
from .registry import register, P

EFFECTS = ["Generic (effect + SE)", "Odds ratio (2×2 counts)", "Risk ratio (2×2 counts)", "Mean difference (means, SDs, n)",
           "Standardized mean difference — Hedges' g (means, SDs, n)"]


def _tau2_reml(y, v):
    def nll(t2):
        w = 1 / (v + t2)
        mu = (w * y).sum() / w.sum()
        return 0.5 * (np.log(v + t2).sum() + np.log(w.sum()) + (w * (y - mu) ** 2).sum())
    r = minimize_scalar(nll, bounds=(0, max(10 * np.var(y), 1e-6) + 10), method="bounded", options={"xatol": 1e-10})
    return max(r.x, 0.0)


def pool(y, v, method="REML"):
    w = 1 / v
    fe = (w * y).sum() / w.sum()
    se_fe = math.sqrt(1 / w.sum())
    Q = (w * (y - fe) ** 2).sum()
    k = len(y)
    dfq = k - 1
    C = w.sum() - (w ** 2).sum() / w.sum()
    t2_dl = max(0.0, (Q - dfq) / C) if C > 0 else 0.0
    t2 = _tau2_reml(y, v) if method == "REML" else t2_dl
    wr = 1 / (v + t2)
    re = (wr * y).sum() / wr.sum()
    se_re = math.sqrt(1 / wr.sum())
    I2 = max(0.0, (Q - dfq) / Q) * 100 if Q > 0 else 0.0
    # I² based on the chosen tau² (as metafor reports)
    s2 = dfq / C if C > 0 else np.nan
    I2_t = t2 / (t2 + s2) * 100 if s2 == s2 else I2
    H2 = Q / dfq if dfq > 0 else np.nan
    tcrit = stats.t.ppf(0.975, k - 2) if k > 2 else np.nan
    pi = (re - tcrit * math.sqrt(t2 + se_re ** 2), re + tcrit * math.sqrt(t2 + se_re ** 2)) if k > 2 else (np.nan, np.nan)
    return dict(fe=fe, se_fe=se_fe, re=re, se_re=se_re, Q=Q, df=dfq, pQ=stats.chi2.sf(Q, dfq) if dfq > 0 else np.nan,
                tau2=t2, I2=I2_t, I2_Q=I2, H2=H2, pi=pi, w_fe=w / w.sum() * 100, w_re=wr / wr.sum() * 100)


@register("meta", "meta", "Meta-analysis (forest & funnel plots)", "التحليل التجميعي (Forest وFunnel)",
          [P("study", "Study label", "اسم الدراسة", "var_any"),
           P("effect_type", "Effect measure / data layout", "مقياس الأثر / شكل البيانات", "choice", EFFECTS, EFFECTS[1]),
           P("c1", "Effect | events trt | mean trt", "الأثر | أحداث المعالجة | متوسط المعالجة", "var_num"),
           P("c2", "SE | total trt | SD trt", "الخطأ المعياري | إجمالي المعالجة | انحراف المعالجة", "var_num"),
           P("c3", "— | events ctrl | n trt", "— | أحداث الضابطة | عدد المعالجة", "var_num", optional=True),
           P("c4", "— | total ctrl | mean ctrl", "— | إجمالي الضابطة | متوسط الضابطة", "var_num", optional=True),
           P("c5", "— | — | SD ctrl", "— | — | انحراف الضابطة", "var_num", optional=True),
           P("c6", "— | — | n ctrl", "— | — | عدد الضابطة", "var_num", optional=True),
           P("method", "τ² estimator", "مقدّر τ²", "choice", ["REML", "DerSimonian-Laird"], "REML"),
           P("model", "Primary model", "النموذج الأساسي", "choice", ["Random effects", "Fixed effect"], "Random effects")],
          "Pooled effect with 95% CI, Q, I², τ², prediction interval, Egger's test, leave-one-out sensitivity; forest and funnel plots.",
          "الأثر المجمّع مع فترة الثقة وQ وI² وτ² وفترة التنبؤ واختبار إيجر وتحليل الحساسية مع رسم Forest وFunnel.")
def meta(df, study, effect_type=EFFECTS[1], c1=None, c2=None, c3=None, c4=None, c5=None, c6=None, method="REML", model="Random effects"):
    lab = df[study].astype(str)
    log_scale = False
    if effect_type.startswith("Generic"):
        y, se = numeric(df, c1), numeric(df, c2)
        v = se ** 2
        xl = "Effect size"
        null = 0
    elif effect_type.startswith(("Odds", "Risk")):
        if not (c3 and c4):
            raise AnalysisError("Provide events and totals for both arms (4 columns).")
        a, n1, c, n2 = numeric(df, c1), numeric(df, c2), numeric(df, c3), numeric(df, c4)
        b, dd = n1 - a, n2 - c
        cc = ((a == 0) | (b == 0) | (c == 0) | (dd == 0)).astype(float) * 0.5
        a_, b_, c_, d_ = a + cc, b + cc, c + cc, dd + cc
        if effect_type.startswith("Odds"):
            y = np.log(a_ * d_ / (b_ * c_)); v = 1 / a_ + 1 / b_ + 1 / c_ + 1 / d_; xl = "Odds ratio (log scale)"
        else:
            y = np.log((a_ / (a_ + b_)) / (c_ / (c_ + d_))); v = 1 / a_ - 1 / (a_ + b_) + 1 / c_ - 1 / (c_ + d_); xl = "Risk ratio (log scale)"
        log_scale = True
        null = 0
    else:
        if not all([c3, c4, c5, c6]):
            raise AnalysisError("Provide mean, SD and n for both arms (6 columns).")
        m1, s1, n1, m2, s2, n2 = (numeric(df, c) for c in [c1, c2, c3, c4, c5, c6])
        if effect_type.startswith("Mean"):
            y = m1 - m2; v = s1 ** 2 / n1 + s2 ** 2 / n2; xl = "Mean difference"
        else:
            sp = np.sqrt(((n1 - 1) * s1 ** 2 + (n2 - 1) * s2 ** 2) / (n1 + n2 - 2))
            J = 1 - 3 / (4 * (n1 + n2) - 9)
            y = J * (m1 - m2) / sp
            v = (n1 + n2) / (n1 * n2) + y ** 2 / (2 * (n1 + n2)); xl = "Hedges' g"
        null = 0
    dfm = pd.DataFrame({"lab": lab, "y": y, "v": v}).dropna()
    if len(dfm) < 2:
        raise AnalysisError("Need at least 2 studies.")
    yv, vv = dfm.y.values.astype(float), dfm.v.values.astype(float)
    r = pool(yv, vv, "REML" if method == "REML" else "DL")
    tr = np.exp if log_scale else (lambda x: x)
    se = np.sqrt(vv)
    use_re = model.startswith("Random")
    est, sest = (r["re"], r["se_re"]) if use_re else (r["fe"], r["se_fe"])
    z = est / sest
    p = 2 * stats.norm.sf(abs(z))
    res = Result("Meta-analysis", f"{len(dfm)} studies; {effect_type}; {model} ({method})")
    st = pd.DataFrame({"Study": dfm.lab.values, "Effect": tr(yv), "95% CI lower": tr(yv - 1.96 * se), "95% CI upper": tr(yv + 1.96 * se),
                       "Weight % (FE)": r["w_fe"], "Weight % (RE)": r["w_re"]})
    res.table(st, "Individual studies")
    summ = pd.DataFrame([
        {"Model": "Fixed effect (inverse variance)", "Pooled effect": tr(r["fe"]), "95% CI lower": tr(r["fe"] - 1.96 * r["se_fe"]),
         "95% CI upper": tr(r["fe"] + 1.96 * r["se_fe"]), "z": r["fe"] / r["se_fe"], "p": 2 * stats.norm.sf(abs(r["fe"] / r["se_fe"]))},
        {"Model": f"Random effects ({method})", "Pooled effect": tr(r["re"]), "95% CI lower": tr(r["re"] - 1.96 * r["se_re"]),
         "95% CI upper": tr(r["re"] + 1.96 * r["se_re"]), "z": r["re"] / r["se_re"], "p": 2 * stats.norm.sf(abs(r["re"] / r["se_re"]))}])
    res.table(summ, "Pooled estimates", f"Prediction interval (RE): {tr(r['pi'][0]):.3f} to {tr(r['pi'][1]):.3f}.")
    res.table(pd.DataFrame([{"Q": r["Q"], "df": r["df"], "p": r["pQ"], "I² (%)": r["I2"], "H²": r["H2"], "τ²": r["tau2"], "τ": math.sqrt(r["tau2"])}]),
              "Heterogeneity")
    egg_p = np.nan
    if len(dfm) >= 3:
        prec = 1 / se
        lr = stats.linregress(prec, yv / se)
        tval = lr.intercept / lr.intercept_stderr
        egg_p = 2 * stats.t.sf(abs(tval), len(dfm) - 2)
        res.table(pd.DataFrame([{"Egger intercept": lr.intercept, "SE": lr.intercept_stderr, "t": tval, "df": len(dfm) - 2, "p": egg_p}]),
                  "Egger's regression test for funnel-plot asymmetry", "Interpret with caution when fewer than 10 studies.")
        loo = []
        for i in range(len(dfm)):
            mask = np.arange(len(dfm)) != i
            rr = pool(yv[mask], vv[mask], "REML" if method == "REML" else "DL")
            e, s_ = (rr["re"], rr["se_re"]) if use_re else (rr["fe"], rr["se_fe"])
            loo.append({"Omitted study": dfm.lab.values[i], "Pooled effect": tr(e), "95% CI lower": tr(e - 1.96 * s_),
                        "95% CI upper": tr(e + 1.96 * s_), "I² (%)": rr["I2"]})
        res.table(pd.DataFrame(loo), "Leave-one-out sensitivity analysis")
    het = "low" if r["I2"] < 25 else "moderate" if r["I2"] < 50 else "substantial" if r["I2"] < 75 else "considerable"
    het_ar = {"low": "منخفض", "moderate": "متوسط", "substantial": "كبير", "considerable": "كبير جدًا"}[het]
    res.interpret(f"Pooled {xl.split(' (')[0]} = {tr(est):.3f} (95% CI {tr(est - 1.96*sest):.3f}–{tr(est + 1.96*sest):.3f}, {pstr(p)}). "
                  f"Heterogeneity is {het} (I² = {r['I2']:.1f}%, τ² = {r['tau2']:.4f}, Q {pstr(r['pQ'])}); the 95% prediction interval "
                  f"({tr(r['pi'][0]):.3f} to {tr(r['pi'][1]):.3f}) shows the range of true effects expected in a new study. "
                  + (f"Egger's test {pstr(egg_p)}" + (" suggests small-study effects / publication bias." if egg_p < 0.1 else " shows no evidence of asymmetry.") if egg_p == egg_p else ""),
                  f"الأثر المجمّع = {tr(est):.3f} (فترة الثقة 95%: {tr(est - 1.96*sest):.3f}–{tr(est + 1.96*sest):.3f}، {pstr(p)}). "
                  f"عدم التجانس {het_ar} (I² = {r['I2']:.1f}%)؛ وفترة التنبؤ ({tr(r['pi'][0]):.3f} إلى {tr(r['pi'][1]):.3f}) توضح مدى الأثر المتوقع في دراسة جديدة."
                  + (f" اختبار إيجر {pstr(egg_p)}." if egg_p == egg_p else ""))
    summary = [(f"{'RE' if use_re else 'FE'} model (I² = {r['I2']:.0f}%)", est, est - 1.96 * sest, est + 1.96 * sest)]
    res.figure(F.forest_plot(list(dfm.lab.values), yv, yv - 1.96 * se, yv + 1.96 * se, weights=r["w_re"] if use_re else r["w_fe"],
                             summary=summary, xlabel=xl, log_scale=log_scale, null=null, pi=r["pi"] if use_re else None),
               "Forest plot (squares ∝ weight; diamond = pooled estimate; red bar = prediction interval).")
    res.figure(F.funnel_plot(yv, se, est, xlabel=xl.replace(" (log scale)", " (log)")), "Funnel plot with pseudo-95% confidence limits.")
    res.methods(f"Effect sizes were pooled using a {model.lower()} model with the {method} estimator of between-study variance. "
                "Heterogeneity was quantified with Cochran's Q, I² and τ², and a 95% prediction interval was calculated. Publication bias was "
                "assessed by funnel-plot inspection and Egger's regression test; robustness by leave-one-out analysis.")
    return res
