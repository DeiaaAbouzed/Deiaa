"""Pharmacology & toxicology: probit/logit LD50, 4PL dose-response (EC50/IC50), Michaelis-Menten, non-compartmental PK."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from scipy.optimize import curve_fit

from ..core.data import numeric
from ..core.result import Result, AnalysisError
from ..plots import figures as F
from .common import pstr
from .registry import register, P


@register("probit", "pharmtox", "Probit / logit analysis (LD50, ED50)", "تحليل البروبيت/اللوجيت (LD50، ED50)",
          [P("dose", "Dose", "الجرعة", "var_num"), P("n", "Number of animals per dose", "عدد الحيوانات لكل جرعة", "var_num"),
           P("responders", "Number responding / dead", "عدد المستجيبين/النافقين", "var_num"),
           P("link", "Model", "النموذج", "choice", ["Probit (Finney)", "Logit"], "Probit (Finney)"),
           P("log_dose", "Dose scale", "مقياس الجرعة", "choice", ["log10(dose)", "Dose already in log10", "Linear dose"], "log10(dose)"),
           P("unit", "Dose unit", "وحدة الجرعة", "text", default="mg/kg")],
          "Maximum-likelihood probit/logit regression with LD10/LD50/LD90 and Fieller 95% confidence limits, Pearson goodness of fit.",
          "انحدار البروبيت/اللوجيت بطريقة الإمكان الأعظم مع LD10/LD50/LD90 وحدود ثقة فيلر واختبار حسن المطابقة.")
def probit(df, dose, n, responders, link="Probit (Finney)", log_dose="log10(dose)", unit="mg/kg"):
    d = pd.DataFrame({"dose": numeric(df, dose), "n": numeric(df, n), "r": numeric(df, responders)}).dropna()
    if (d.r > d.n).any():
        raise AnalysisError("Responders cannot exceed n.")
    if log_dose == "log10(dose)":
        if (d.dose <= 0).any():
            raise AnalysisError("Doses must be > 0 for log transformation (remove the control group or use linear dose).")
        x = np.log10(d.dose.values)
    else:
        x = d.dose.values.astype(float)
    lk = sm.families.links.Probit() if link.startswith("Probit") else sm.families.links.Logit()
    X = sm.add_constant(x)
    endog = np.column_stack([d.r.values, d.n.values - d.r.values])
    m = sm.GLM(endog, X, family=sm.families.Binomial(link=lk)).fit()
    a, b = m.params
    V = m.cov_params()
    dist = stats.norm if link.startswith("Probit") else stats.logistic
    # heterogeneity
    fitted = m.predict()
    pear = (((d.r - d.n * fitted) ** 2) / (d.n * fitted * (1 - fitted))).sum()
    dfh = len(d) - 2
    ph = stats.chi2.sf(pear, dfh) if dfh > 0 else np.nan
    hetero = dfh > 0 and ph < 0.15
    h = pear / dfh if hetero else 1.0
    tcrit = stats.t.ppf(0.975, dfh) if hetero else 1.96
    rows = []
    for pct in [1, 5, 10, 16, 25, 50, 75, 84, 90, 95, 99]:
        q = dist.ppf(pct / 100)
        xq = (q - a) / b
        # Fieller's theorem
        v11, v22, v12 = V[0, 0] * h, V[1, 1] * h, V[0, 1] * h
        g = tcrit ** 2 * v22 / b ** 2
        if g < 1:
            num = xq + g / (1 - g) * (xq + v12 / v22)
            hw = tcrit / (b * (1 - g)) * math.sqrt(v11 + 2 * xq * v12 + xq ** 2 * v22 - g * (v11 - v12 ** 2 / v22))
            lo, hi = num - hw, num + hw
        else:
            lo, hi = np.nan, np.nan
        back = (lambda v: 10 ** v) if log_dose != "Linear dose" else (lambda v: v)
        rows.append({"Effect level": f"LD{pct}", f"Dose ({unit})": back(xq), "95% FL lower": back(lo), "95% FL upper": back(hi)})
    res = Result(f"{'Probit' if link.startswith('Probit') else 'Logit'} analysis", f"{responders}/{n} vs {dose} ({log_dose})")
    obs = d.assign(**{"Observed %": d.r / d.n * 100, "Expected %": fitted * 100})
    obs = obs.rename(columns={"dose": f"Dose ({unit})", "n": "n", "r": "Responders"})
    res.table(obs, "Observed and expected responses")
    res.table(pd.DataFrame([{"Parameter": "Intercept (a)", "Estimate": a, "SE": m.bse[0], "p": m.pvalues[0]},
                            {"Parameter": "Slope (b)", "Estimate": b, "SE": m.bse[1], "p": m.pvalues[1]}]),
              "Regression parameters", f"Pearson goodness-of-fit χ²({dfh}) = {pear:.3f}, {pstr(ph)}"
              + (" → heterogeneity factor applied to the fiducial limits (t-based, as in SPSS)." if hetero else "."))
    res.table(pd.DataFrame(rows), "Lethal/effective doses with 95% fiducial limits (Fieller)")
    ld50 = rows[5]
    res.interpret(f"LD50 = {ld50[f'Dose ({unit})']:.4g} {unit} (95% fiducial limits {ld50['95% FL lower']:.4g}–{ld50['95% FL upper']:.4g}); "
                  f"slope = {b:.3f} — {'a steep' if b > 5 else 'a shallow'} dose-response curve "
                  f"({'narrow' if b > 5 else 'wide'} margin between ineffective and lethal doses). "
                  + ("Goodness of fit acceptable." if ph >= 0.15 or np.isnan(ph) else "Significant heterogeneity: limits widened accordingly."),
                  f"الجرعة المميتة الوسطى LD50 = {ld50[f'Dose ({unit})']:.4g} {unit} (حدود الثقة 95%: {ld50['95% FL lower']:.4g}–{ld50['95% FL upper']:.4g})؛ "
                  f"الميل = {b:.3f}. " + ("المطابقة مقبولة." if ph >= 0.15 or np.isnan(ph) else "يوجد عدم تجانس دال وتم توسيع حدود الثقة."))
    xs = np.linspace(x.min() - 0.1 * np.ptp(x), x.max() + 0.1 * np.ptp(x), 300)
    ys = dist.cdf(a + b * xs) * 100
    x50 = (dist.ppf(0.5) - a) / b
    res.figure(F.dose_response_plot(x, d.r / d.n * 100, xs, ys, xlabel=f"log10 dose ({unit})" if log_dose != "Linear dose" else f"Dose ({unit})",
                                    ylabel="Response / mortality (%)", marks=[(x50, 50, "LD50")], ylim=(-3, 103)),
               f"{'Probit' if link.startswith('Probit') else 'Logit'} dose-response curve with LD50.")
    res.methods(f"The median lethal dose (LD50) and its 95% fiducial limits were estimated by {'probit' if link.startswith('Probit') else 'logit'} "
                f"regression on log10-transformed dose using maximum likelihood (Finney's method) with Fieller's theorem for the limits. "
                f"LD50 = {ld50[f'Dose ({unit})']:.4g} {unit} (95% FL {ld50['95% FL lower']:.4g}–{ld50['95% FL upper']:.4g}).")
    return res


def four_pl(x, bottom, top, logec50, hill):
    return bottom + (top - bottom) / (1 + 10 ** ((logec50 - x) * hill))


@register("doseresp", "pharmtox", "Dose-response curve 4PL (EC50 / IC50)", "منحنى الجرعة-الاستجابة رباعي المعاملات (EC50/IC50)",
          [P("dose", "Concentration / dose", "التركيز/الجرعة", "var_num"), P("response", "Response", "الاستجابة", "var_num"),
           P("xscale", "X values are", "قيم المحور X", "choice", ["Concentration (will log10)", "Already log10"], "Concentration (will log10)"),
           P("constrain", "Constraints", "القيود", "choice", ["None (4PL)", "Bottom = 0", "Top = 100", "Bottom = 0 and Top = 100", "Hill slope = 1 (3PL)"], "None (4PL)"),
           P("label", "Parameter name", "اسم المعامل", "choice", ["EC50", "IC50", "ED50"], "EC50")],
          "Non-linear 4-parameter logistic (Hill) fit as in GraphPad Prism 'log(agonist) vs response — variable slope'.",
          "مواءمة لوجستية رباعية المعاملات كما في GraphPad Prism.")
def doseresp(df, dose, response, xscale="Concentration (will log10)", constrain="None (4PL)", label="EC50"):
    d = pd.DataFrame({"x": numeric(df, dose), "y": numeric(df, response)}).dropna()
    if xscale.startswith("Concentration"):
        d = d[d.x > 0]
        x = np.log10(d.x.values)
    else:
        x = d.x.values
    y = d.y.values
    fixed = {}
    if "Bottom = 0" in constrain:
        fixed["bottom"] = 0.0
    if "Top = 100" in constrain:
        fixed["top"] = 100.0
    if "Hill" in constrain:
        fixed["hill"] = 1.0
    names = ["bottom", "top", "logec50", "hill"]
    free = [n_ for n_ in names if n_ not in fixed]
    # sensible starting values
    order = np.argsort(x)
    inc = np.corrcoef(x, y)[0, 1] >= 0
    init = {"bottom": y.min(), "top": y.max(), "logec50": np.median(x), "hill": 1.0 if inc else -1.0}

    def f(xx, *pars):
        p = dict(fixed)
        p.update(dict(zip(free, pars)))
        return four_pl(xx, p["bottom"], p["top"], p["logec50"], p["hill"])
    try:
        popt, pcov = curve_fit(f, x, y, p0=[init[n_] for n_ in free], maxfev=20000)
    except Exception as e:
        raise AnalysisError(f"Curve fit did not converge: {e}")
    perr = np.sqrt(np.diag(pcov))
    dfree = len(x) - len(free)
    t = stats.t.ppf(0.975, max(dfree, 1))
    est = dict(fixed); est.update(dict(zip(free, popt)))
    rows = []
    for n_ in names:
        if n_ in free:
            i = free.index(n_)
            rows.append({"Parameter": {"logec50": f"log{label}"}.get(n_, n_.capitalize()), "Estimate": popt[i], "SE": perr[i],
                         "95% CI lower": popt[i] - t * perr[i], "95% CI upper": popt[i] + t * perr[i]})
        else:
            rows.append({"Parameter": n_.capitalize() + " (fixed)", "Estimate": fixed[n_], "SE": np.nan, "95% CI lower": np.nan, "95% CI upper": np.nan})
    i50 = free.index("logec50")
    ec50 = 10 ** popt[i50]
    rows.append({"Parameter": label, "Estimate": ec50, "SE": np.nan, "95% CI lower": 10 ** (popt[i50] - t * perr[i50]),
                 "95% CI upper": 10 ** (popt[i50] + t * perr[i50])})
    yhat = f(x, *popt)
    ss_res = ((y - yhat) ** 2).sum()
    r2 = 1 - ss_res / ((y - y.mean()) ** 2).sum()
    res = Result("Non-linear regression: dose-response (4PL)", f"{response} vs log({dose}); {constrain}")
    res.table(pd.DataFrame(rows), "Best-fit values", f"R² = {r2:.4f}; Sy.x = {math.sqrt(ss_res / max(dfree, 1)):.4g}; df = {dfree}. "
              "CI of EC50 is asymmetric (back-transformed from log scale), as in Prism.")
    res.interpret(f"{label} = {ec50:.4g} (95% CI {rows[-1]['95% CI lower']:.4g}–{rows[-1]['95% CI upper']:.4g}); Hill slope = {est['hill']:.2f}"
                  + (" (steeper than a simple 1:1 binding — possible cooperativity)" if abs(est['hill']) > 1.5 else "")
                  + f"; R² = {r2:.3f}. Compare potency between compounds with an extra-sum-of-squares F test or by overlapping CIs of log{label}.",
                  f"{label} = {ec50:.4g} (فترة الثقة 95%: {rows[-1]['95% CI lower']:.4g}–{rows[-1]['95% CI upper']:.4g})؛ ميل هيل = {est['hill']:.2f}؛ R² = {r2:.3f}.")
    xs = np.linspace(x.min() - 0.3, x.max() + 0.3, 300)
    # mean ± SD per concentration for plotting replicates
    agg = pd.DataFrame({"x": x, "y": y}).groupby("x").y.agg(["mean", "std"]).reset_index()
    res.figure(F.dose_response_plot(agg.x, agg["mean"], xs, f(xs, *popt), xlabel=f"log [{dose}]", ylabel=response,
                                    marks=[(popt[i50], f(np.array([popt[i50]]), *popt)[0], label)],
                                    yerr=agg["std"].fillna(0).values if (agg["std"].notna().any()) else None),
               f"Four-parameter logistic fit; points are mean ± SD of replicates.")
    res.methods(f"Concentration-response data were fitted by non-linear regression to a four-parameter logistic equation "
                f"(log(agonist) vs response, variable slope); {label} values are reported with 95% CI.")
    return res


@register("michaelis", "pharmtox", "Enzyme kinetics (Michaelis-Menten)", "حركية الإنزيمات (ميكاليس-منتن)",
          [P("substrate", "Substrate concentration [S]", "تركيز الركيزة", "var_num"), P("velocity", "Velocity (v)", "السرعة", "var_num")],
          "Non-linear fit of Vmax and Km with 95% CI plus Lineweaver-Burk values.", "مواءمة غير خطية لـ Vmax وKm.")
def michaelis(df, substrate, velocity):
    d = pd.DataFrame({"s": numeric(df, substrate), "v": numeric(df, velocity)}).dropna()
    s, v = d.s.values, d.v.values
    fmm = lambda S, Vmax, Km: Vmax * S / (Km + S)
    popt, pcov = curve_fit(fmm, s, v, p0=[v.max(), np.median(s)], maxfev=10000)
    se = np.sqrt(np.diag(pcov))
    t = stats.t.ppf(0.975, len(s) - 2)
    r2 = 1 - ((v - fmm(s, *popt)) ** 2).sum() / ((v - v.mean()) ** 2).sum()
    res = Result("Michaelis-Menten kinetics", f"{velocity} vs {substrate}")
    res.table(pd.DataFrame([{"Parameter": "Vmax", "Estimate": popt[0], "SE": se[0], "95% CI lower": popt[0] - t * se[0], "95% CI upper": popt[0] + t * se[0]},
                            {"Parameter": "Km", "Estimate": popt[1], "SE": se[1], "95% CI lower": popt[1] - t * se[1], "95% CI upper": popt[1] + t * se[1]}]),
              "Best-fit values", f"R² = {r2:.4f}. Non-linear least squares (preferred over Lineweaver-Burk linearisation).")
    res.interpret(f"Vmax = {popt[0]:.4g}, Km = {popt[1]:.4g}: half-maximal velocity is reached at [S] = {popt[1]:.4g}.",
                  f"Vmax = {popt[0]:.4g} وKm = {popt[1]:.4g}: يتم الوصول لنصف السرعة القصوى عند تركيز {popt[1]:.4g}.")
    xs = np.linspace(0, s.max() * 1.1, 200)
    res.figure(F.dose_response_plot(s, v, xs, fmm(xs, *popt), xlabel=substrate, ylabel=velocity, marks=[(popt[1], popt[0] / 2, "Km")]),
               "Michaelis-Menten fit.")
    return res


@register("nca", "pharmtox", "Pharmacokinetics — non-compartmental analysis", "الحرائك الدوائية — التحليل اللاحجيري",
          [P("time", "Time", "الزمن", "var_num"), P("conc", "Concentration", "التركيز", "var_num"),
           P("subject", "Subject (optional)", "رقم الحالة (اختياري)", "var_any", optional=True),
           P("dose", "Dose (for CL/F and Vz/F; 0 = skip)", "الجرعة (لحساب التصفية والحجم)", "float", default=0.0),
           P("n_terminal", "Points for terminal phase", "عدد النقاط للمرحلة النهائية", "int", default=3),
           P("auc_method", "AUC method", "طريقة حساب AUC", "choice", ["Linear-up / log-down", "Linear trapezoidal"], "Linear-up / log-down")],
          "Cmax, Tmax, AUC0-t, AUC0-∞, λz, t½, MRT, CL/F, Vz/F per subject with summary statistics (WinNonlin-style).",
          "Cmax وTmax وAUC ونصف العمر وMRT والتصفية وحجم التوزيع لكل حالة مع ملخص إحصائي.")
def nca(df, time, conc, subject=None, dose=0.0, n_terminal=3, auc_method="Linear-up / log-down"):
    d = pd.DataFrame({"t": numeric(df, time), "c": numeric(df, conc)})
    d["s"] = df[subject].astype(str) if subject else "All"
    d = d.dropna()
    out = []
    curves = {}
    for sid, sub in d.groupby("s"):
        sub = sub.groupby("t").c.mean().reset_index().sort_values("t")
        t, c = sub.t.values, sub.c.values
        auc = aumc = 0.0
        for i in range(1, len(t)):
            dt = t[i] - t[i - 1]
            if auc_method.startswith("Linear-up") and c[i] < c[i - 1] and c[i] > 0 and c[i - 1] > 0:
                k = math.log(c[i - 1] / c[i]) / dt
                auc += (c[i - 1] - c[i]) / k
                aumc += (c[i - 1] * t[i - 1] - c[i] * t[i]) / k + (c[i - 1] - c[i]) / k ** 2
            else:
                auc += dt * (c[i] + c[i - 1]) / 2
                aumc += dt * (c[i] * t[i] + c[i - 1] * t[i - 1]) / 2
        imax = int(np.argmax(c))
        tail = [(tt, cc) for tt, cc in zip(t[imax + 1:], c[imax + 1:]) if cc > 0][-n_terminal:]
        lz = r2 = np.nan
        if len(tail) >= 2:
            tt, cc = np.array(tail).T
            lr = stats.linregress(tt, np.log(cc))
            lz, r2 = -lr.slope, lr.rvalue ** 2
        clast, tlast = c[c > 0][-1], t[c > 0][-1]
        auc_inf = auc + clast / lz if lz and lz > 0 else np.nan
        aumc_inf = aumc + clast * tlast / lz + clast / lz ** 2 if lz and lz > 0 else np.nan
        row = {"Subject": sid, "Cmax": c[imax], "Tmax": t[imax], "AUC0-t": auc, "AUC0-∞": auc_inf,
               "% AUC extrap.": (auc_inf - auc) / auc_inf * 100 if auc_inf == auc_inf else np.nan,
               "λz": lz, "t½": math.log(2) / lz if lz and lz > 0 else np.nan, "R² (λz)": r2,
               "MRT": aumc_inf / auc_inf if auc_inf == auc_inf else np.nan}
        if dose:
            row["CL/F"] = dose / auc_inf if auc_inf == auc_inf else np.nan
            row["Vz/F"] = dose / (lz * auc_inf) if auc_inf == auc_inf else np.nan
        out.append(row)
        curves[sid] = (t, c)
    tab = pd.DataFrame(out)
    res = Result("Non-compartmental pharmacokinetic analysis", f"{conc} vs {time}; {auc_method}")
    res.table(tab, "PK parameters per subject", f"λz from the last {n_terminal} quantifiable points by log-linear regression.")
    if len(tab) > 1:
        num = tab.drop(columns="Subject")
        gmean = np.exp(np.log(num.where(num > 0)).mean())
        summ = pd.DataFrame({"Mean": num.mean(), "SD": num.std(), "CV%": num.std() / num.mean() * 100, "Geometric mean": gmean,
                             "Median": num.median(), "Min": num.min(), "Max": num.max()})
        summ.index.name = "Parameter"
        res.table(summ, "Summary statistics")
    r0 = tab.iloc[0] if len(tab) == 1 else tab.drop(columns="Subject").median()
    res.interpret(f"Cmax = {r0['Cmax']:.4g} at Tmax = {r0['Tmax']:.4g}; terminal t½ = {r0['t½']:.3g}; AUC0-∞ = {r0['AUC0-∞']:.4g}"
                  + (" (median across subjects)." if len(tab) > 1 else ".") + " If % AUC extrapolated > 20%, AUC0-∞ is unreliable — extend sampling.",
                  f"أقصى تركيز Cmax = {r0['Cmax']:.4g} عند الزمن {r0['Tmax']:.4g}؛ نصف العمر = {r0['t½']:.3g}؛ AUC0-∞ = {r0['AUC0-∞']:.4g}. "
                  "إذا تجاوزت نسبة الاستقراء 20% فإن AUC0-∞ غير موثوق.")
    from ..plots.figures import styled, new_figure, palette
    with styled():
        fig, axs = new_figure(w_mm=170, ncols=2)
        cols = palette(len(curves))
        for i, (sid, (t, c)) in enumerate(curves.items()):
            axs[0].plot(t, c, marker="o", color=cols[i], mec="black", mew=0.4, ms=5, label=str(sid))
            axs[1].semilogy(t[c > 0], c[c > 0], marker="o", color=cols[i], mec="black", mew=0.4, ms=5)
        axs[0].set_xlabel(time); axs[0].set_ylabel(conc); axs[0].set_title("Linear scale", fontsize=10)
        axs[1].set_xlabel(time); axs[1].set_ylabel(conc + " (log)"); axs[1].set_title("Semi-log scale", fontsize=10)
        if len(curves) <= 8 and len(curves) > 1:
            axs[0].legend()
        fig.tight_layout()
    res.figure(fig, "Concentration-time profiles (linear and semi-logarithmic).")
    return res
