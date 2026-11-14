"""Sample size and power calculations (G*Power / PASS / nQuery-style)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.power import TTestIndPower, TTestPower, FTestAnovaPower

from ..core.result import Result, AnalysisError
from ..plots import figures as F
from .registry import register, P

DESIGNS = ["Two independent means (t-test)", "Paired means (paired t-test)", "Two independent proportions",
           "One-way ANOVA (k groups)", "Correlation (r ≠ 0)", "Survival — log-rank (hazard ratio)",
           "Diagnostic accuracy — sensitivity", "Animal study — resource equation (Mead)"]


def _inflate(n, dropout):
    return math.ceil(n / (1 - dropout / 100)) if dropout else math.ceil(n)


@register("power", "power", "Sample size & power calculator", "حاسبة حجم العينة والقوة الإحصائية",
          [P("design", "Study design / test", "تصميم الدراسة / الاختبار", "choice", DESIGNS, DESIGNS[0]),
           P("alpha", "α (two-sided)", "مستوى الدلالة α", "float", default=0.05),
           P("power", "Power (1 − β)", "القوة (1 − β)", "float", default=0.80),
           P("mean_diff", "Expected difference in means (Δ)", "الفرق المتوقع بين المتوسطات Δ", "float", default=10.0),
           P("sd", "Standard deviation (σ) / SD of differences", "الانحراف المعياري σ", "float", default=15.0),
           P("p1", "Proportion group 1 / expected sensitivity / r", "النسبة 1 / الحساسية المتوقعة / r", "float", default=0.30),
           P("p2", "Proportion group 2 / CI half-width (precision)", "النسبة 2 / نصف عرض فترة الثقة", "float", default=0.15),
           P("k", "Groups (ANOVA) / allocation ratio n2:n1", "عدد المجموعات / نسبة التوزيع", "float", default=1.0),
           P("effect_f", "Cohen's f (ANOVA) / hazard ratio", "حجم الأثر f / نسبة الخطورة", "float", default=0.25),
           P("event_rate", "Overall event probability (survival) / prevalence (diagnostic)", "احتمال الحدث / الانتشار", "float", default=0.5),
           P("dropout", "Expected dropout %", "نسبة الانسحاب المتوقعة %", "float", default=10.0)],
          "A-priori sample size with all inputs stated, power curve and a ready-to-paste justification paragraph.",
          "حساب حجم العينة مسبقًا مع ذكر جميع المدخلات ومنحنى القوة وفقرة تبرير جاهزة للبحث.", needs_data=False)
def power(design=DESIGNS[0], alpha=0.05, power=0.80, mean_diff=10.0, sd=15.0, p1=0.30, p2=0.15, k=1.0, effect_f=0.25,
          event_rate=0.5, dropout=10.0):
    za, zb = stats.norm.ppf(1 - alpha / 2), stats.norm.ppf(power)
    res = Result("Sample size calculation", design)
    curve = None
    inputs = {"α (two-sided)": alpha, "Power": power}
    if design.startswith("Two independent means"):
        d = mean_diff / sd
        ratio = k or 1.0
        n1 = TTestIndPower().solve_power(effect_size=d, alpha=alpha, power=power, ratio=ratio)
        n1 = math.ceil(n1); n2 = math.ceil(n1 * ratio)
        inputs.update({"Δ": mean_diff, "σ": sd, "Cohen's d": d, "Allocation n2:n1": ratio})
        out = {"n per group (group 1)": n1, "n group 2": n2, "Total": n1 + n2,
               "Total after dropout": _inflate(n1, dropout) + _inflate(n2, dropout)}
        ns = np.arange(4, max(3 * n1, 20))
        curve = (ns, [TTestIndPower().power(d, n, alpha, ratio=ratio) for n in ns], (n1, power))
        txt = (f"A sample size of {n1} per group ({n1 + n2} in total) provides {power*100:.0f}% power to detect a difference of {mean_diff} "
               f"(SD {sd}; Cohen's d = {d:.2f}) with a two-sided independent t-test at α = {alpha}. Allowing for {dropout:.0f}% dropout, "
               f"{_inflate(n1, dropout)} per group will be recruited.")
    elif design.startswith("Paired"):
        dz = mean_diff / sd
        n = math.ceil(TTestPower().solve_power(effect_size=dz, alpha=alpha, power=power))
        inputs.update({"Δ": mean_diff, "SD of differences": sd, "dz": dz})
        out = {"Pairs required": n, "After dropout": _inflate(n, dropout)}
        ns = np.arange(3, max(3 * n, 15))
        curve = (ns, [TTestPower().power(dz, x, alpha) for x in ns], (n, power))
        txt = f"{n} pairs give {power*100:.0f}% power to detect a mean change of {mean_diff} (SD of differences {sd}, dz = {dz:.2f}) at α = {alpha}."
    elif design.startswith("Two independent proportions"):
        ratio = k or 1.0
        pbar = (p1 + ratio * p2) / (1 + ratio)
        n1 = (za * math.sqrt(pbar * (1 - pbar) * (1 + 1 / ratio)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2) / ratio)) ** 2 / (p1 - p2) ** 2
        # Fleiss continuity correction
        n1c = n1 / 4 * (1 + math.sqrt(1 + 2 * (ratio + 1) / (n1 * ratio * abs(p1 - p2)))) ** 2
        n1, n1c = math.ceil(n1), math.ceil(n1c)
        inputs.update({"p1": p1, "p2": p2, "Allocation n2:n1": ratio})
        out = {"n group 1": n1, "n group 2": math.ceil(n1 * ratio), "n group 1 (continuity corrected)": n1c,
               "Total after dropout": _inflate(n1, dropout) + _inflate(n1 * ratio, dropout)}
        txt = (f"To detect a difference between proportions of {p1*100:.0f}% and {p2*100:.0f}% with {power*100:.0f}% power at two-sided α = {alpha}, "
               f"{n1} participants per group are required ({n1c} with continuity correction); with {dropout:.0f}% dropout, {_inflate(n1, dropout)} per group.")
    elif design.startswith("One-way ANOVA"):
        kk = int(k) if k and k >= 2 else 3
        nt = FTestAnovaPower().solve_power(effect_size=effect_f, alpha=alpha, power=power, k_groups=kk)
        ng = math.ceil(nt / kk)
        inputs.update({"Groups": kk, "Cohen's f": effect_f})
        out = {"n per group": ng, "Total": ng * kk, "Total after dropout": _inflate(ng, dropout) * kk}
        txt = f"With {kk} groups, Cohen's f = {effect_f} ({'small' if effect_f < .25 else 'medium' if effect_f < .4 else 'large'}), α = {alpha} and power {power*100:.0f}%, {ng} subjects per group ({ng*kk} total) are needed."
    elif design.startswith("Correlation"):
        r = p1
        n = math.ceil(((za + zb) / (0.5 * math.log((1 + r) / (1 - r)))) ** 2 + 3)
        inputs.update({"Expected r": r})
        out = {"Total N": n, "After dropout": _inflate(n, dropout)}
        txt = f"{n} subjects provide {power*100:.0f}% power to detect a correlation of r = {r} (Fisher z approximation, α = {alpha})."
    elif design.startswith("Survival"):
        hr = effect_f if effect_f and effect_f != 0.25 else 0.7
        ratio = k or 1.0
        pa = 1 / (1 + ratio)
        events = math.ceil((za + zb) ** 2 / (pa * (1 - pa) * math.log(hr) ** 2))
        n = math.ceil(events / event_rate)
        inputs.update({"Hazard ratio": hr, "Probability of event": event_rate, "Allocation": ratio})
        out = {"Events required (Schoenfeld)": events, "Total N": n, "Total after dropout": _inflate(n, dropout)}
        txt = (f"Using Schoenfeld's formula, {events} events are required to detect a hazard ratio of {hr} with {power*100:.0f}% power (two-sided α = {alpha}); "
               f"with an anticipated event probability of {event_rate*100:.0f}%, {n} patients ({_inflate(n, dropout)} after {dropout:.0f}% dropout) will be enrolled.")
    elif design.startswith("Diagnostic"):
        se_, w, prev = p1, p2, event_rate
        npos = math.ceil(za ** 2 * se_ * (1 - se_) / w ** 2)
        n = math.ceil(npos / prev)
        inputs.update({"Expected sensitivity": se_, "Precision (± half-width)": w, "Prevalence": prev})
        out = {"Diseased subjects needed": npos, "Total N to screen": n, "After dropout": _inflate(n, dropout)}
        txt = (f"To estimate a sensitivity of {se_*100:.0f}% with a 95% CI half-width of ±{w*100:.0f}%, {npos} diseased subjects are needed; "
               f"at a prevalence of {prev*100:.0f}%, {n} subjects must be screened (Buderer 1996).")
    else:  # resource equation
        kk = int(k) if k and k >= 2 else 4
        lo, hi = math.ceil(10 / kk + 1), math.floor(20 / kk + 1)
        inputs.update({"Groups": kk})
        out = {"Minimum animals per group (E = 10)": lo, "Maximum animals per group (E = 20)": hi,
               "Total range": f"{lo*kk} – {hi*kk}"}
        txt = (f"According to Mead's resource equation (E = N − k between 10 and 20), with {kk} groups each group should include "
               f"{lo}–{hi} animals ({lo*kk}–{hi*kk} in total), consistent with the 3Rs principle of reduction.")
    res.table(pd.DataFrame([{"Input": k_, "Value": v} for k_, v in inputs.items()]), "Assumptions")
    res.table(pd.DataFrame([{"Result": k_, "Value": v} for k_, v in out.items()]), "Required sample size")
    res.methods("Sample size justification: " + txt)
    res.interpret("State the source of the expected effect size (pilot study, previous literature or minimal clinically important difference). "
                  "Never compute 'post-hoc power' for a non-significant result — report the confidence interval instead.",
                  "اذكر مصدر حجم الأثر المتوقع (دراسة استطلاعية أو أبحاث سابقة أو أقل فرق ذي أهمية سريرية). لا تحسب القوة بعد إجراء الدراسة "
                  "لنتيجة غير دالة — اعرض فترة الثقة بدلًا من ذلك.")
    if curve:
        res.figure(F.power_curve(curve[0], curve[1], curve[2]), "Power as a function of sample size.")
    return res
