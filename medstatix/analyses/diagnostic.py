"""Diagnostic accuracy (ROC with DeLong, 2×2 metrics) and agreement / reliability."""
from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd
from scipy import stats

from ..core.data import binary01, numeric, _level_order
from ..core.result import Result, AnalysisError
from ..plots import figures as F
from .common import pstr, wilson_ci
from .regression import roc_curve
from .registry import register, P


# ------------------------------------------------------------------ DeLong
def _placements(pos, neg):
    V10 = np.array([np.mean((p > neg) + 0.5 * (p == neg)) for p in pos])
    V01 = np.array([np.mean((pos > n) + 0.5 * (pos == n)) for n in neg])
    return V10, V01


def delong(y, scores: list):
    y = np.asarray(y)
    aucs, V10s, V01s = [], [], []
    for s in scores:
        s = np.asarray(s, float)
        V10, V01 = _placements(s[y == 1], s[y == 0])
        aucs.append(V10.mean()); V10s.append(V10); V01s.append(V01)
    m, n = len(V10s[0]), len(V01s[0])
    S10 = np.atleast_2d(np.cov(np.vstack(V10s)))
    S01 = np.atleast_2d(np.cov(np.vstack(V01s)))
    S = S10 / m + S01 / n
    return np.array(aucs), S


@register("roc", "diagnostic", "ROC curve analysis (AUC, cut-off, DeLong)", "تحليل منحنى ROC",
          [P("truth", "Reference standard (disease yes/no)", "المعيار المرجعي (مريض/سليم)", "var_cat"),
           P("markers", "Test variable(s) / biomarker(s)", "المتغير/المؤشرات الحيوية", "vars_num"),
           P("positive", "Positive (diseased) category (blank = auto)", "الفئة الموجبة (فارغ = تلقائي)", "text", default=""),
           P("direction", "Higher values indicate", "القيم الأعلى تدل على", "choice", ["Auto", "Disease", "Health"], "Auto")],
          "AUC with DeLong 95% CI, Youden-optimal cut-off with sensitivity, specificity, PPV, NPV, LRs; DeLong comparison of AUCs.",
          "المساحة تحت المنحنى مع فترة ثقة ديلونج ونقطة القطع المثلى (يودن) والحساسية والنوعية والقيم التنبؤية ومقارنة المنحنيات.")
def roc(df, truth, markers, positive="", direction="Auto"):
    y, poslab = binary01(df, truth, positive)
    d = pd.DataFrame({"y": y})
    for mk in markers:
        d[mk] = numeric(df, mk)
    d = d.dropna()
    yy = d.y.values.astype(int)
    if yy.sum() < 2 or (1 - yy).sum() < 2:
        raise AnalysisError("Need at least 2 positive and 2 negative cases.")
    scores, flipped = [], {}
    for mk in markers:
        s = d[mk].values
        auc0 = delong(yy, [s])[0][0]
        flip = direction == "Health" or (direction == "Auto" and auc0 < 0.5)
        flipped[mk] = flip
        scores.append(-s if flip else s)
    aucs, S = delong(yy, scores)
    res = Result("ROC curve analysis", f"Reference: {truth} (positive = {poslab}); n = {len(d)} ({yy.sum()} positive, {(1-yy).sum()} negative)")
    rows, curves, cuts, cut_rows = [], {}, {}, []
    for i, mk in enumerate(markers):
        se = math.sqrt(S[i, i])
        # logit-transformed CI keeps bounds within (0,1)
        a = aucs[i]
        lo, hi = a - 1.96 * se, a + 1.96 * se
        z = (a - 0.5) / se if se > 0 else np.inf
        p = 2 * stats.norm.sf(abs(z))
        rows.append({"Test variable": mk, "AUC": a, "SE (DeLong)": se, "95% CI lower": max(0, lo), "95% CI upper": min(1, hi), "p (AUC = 0.5)": p,
                     "Direction": "lower = positive" if flipped[mk] else "higher = positive"})
        fpr, tpr, th = roc_curve(yy, scores[i])
        curves[mk] = (fpr, tpr, a)
        J = tpr - fpr
        k = int(np.argmax(J[1:]) + 1)
        thr = -th[k] if flipped[mk] else th[k]
        pred = scores[i] >= th[k]
        TP = int((pred & (yy == 1)).sum()); FP = int((pred & (yy == 0)).sum())
        FN = int((~pred & (yy == 1)).sum()); TN = int((~pred & (yy == 0)).sum())
        sens, spec = TP / (TP + FN), TN / (TN + FP)
        cuts[mk] = (fpr[k], tpr[k])
        cut_rows.append({"Test variable": mk, "Optimal cut-off": f"{'≤' if flipped[mk] else '≥'} {thr:.4g}", "Youden J": J[k],
                         "Sensitivity %": sens * 100, "Sens 95% CI": "%.1f–%.1f" % tuple(np.array(wilson_ci(TP, TP + FN)) * 100),
                         "Specificity %": spec * 100, "Spec 95% CI": "%.1f–%.1f" % tuple(np.array(wilson_ci(TN, TN + FP)) * 100),
                         "PPV %": TP / max(TP + FP, 1) * 100, "NPV %": TN / max(TN + FN, 1) * 100,
                         "LR+": sens / (1 - spec) if spec < 1 else np.inf, "LR−": (1 - sens) / spec if spec > 0 else np.inf})
    res.table(pd.DataFrame(rows), "Area under the ROC curve", "DeLong nonparametric SE.", p_columns=("p (AUC = 0.5)",))
    res.table(pd.DataFrame(cut_rows), "Optimal cut-off (maximum Youden index)", "Wilson 95% CIs. PPV/NPV depend on the sample prevalence "
              f"({yy.mean()*100:.1f}%).")
    if len(markers) > 1:
        comp = []
        for i, j in itertools.combinations(range(len(markers)), 2):
            var = S[i, i] + S[j, j] - 2 * S[i, j]
            z = (aucs[i] - aucs[j]) / math.sqrt(var) if var > 0 else np.nan
            comp.append({"Comparison": f"{markers[i]} vs {markers[j]}", "ΔAUC": aucs[i] - aucs[j], "z": z, "p": 2 * stats.norm.sf(abs(z))})
        res.table(pd.DataFrame(comp), "Pairwise comparison of ROC curves (DeLong test)")

    def grade(a):
        return ("excellent", "ممتازة") if a >= 0.9 else ("good", "جيدة") if a >= 0.8 else ("fair", "مقبولة") if a >= 0.7 else ("poor", "ضعيفة") if a >= 0.6 else ("fail", "فاشلة")
    en = "; ".join(f"{r['Test variable']}: AUC = {r['AUC']:.3f} (95% CI {r['95% CI lower']:.3f}–{r['95% CI upper']:.3f}), {grade(r['AUC'])[0]} discrimination" for r in rows)
    ar = "؛ ".join(f"{r['Test variable']}: AUC = {r['AUC']:.3f}، قدرة تمييزية {grade(r['AUC'])[1]}" for r in rows)
    c0 = cut_rows[0]
    en += f". Best cut-off for {c0['Test variable']}: {c0['Optimal cut-off']} (sensitivity {c0['Sensitivity %']:.1f}%, specificity {c0['Specificity %']:.1f}%)."
    ar += f". أفضل نقطة قطع لـ{c0['Test variable']}: {c0['Optimal cut-off']} (حساسية {c0['Sensitivity %']:.1f}%، نوعية {c0['Specificity %']:.1f}%)."
    res.interpret(en, ar)
    res.figure(F.roc_plot(curves, cuts), "ROC curve(s); dot = Youden-optimal cut-off.")
    res.methods("Diagnostic performance was evaluated with ROC curve analysis; AUC 95% CIs and comparisons used DeLong's method; "
                "the optimal cut-off maximised Youden's index (sensitivity + specificity − 1).")
    return res


@register("diag2x2", "diagnostic", "Diagnostic test 2×2 (sensitivity, specificity...)", "دقة الاختبار التشخيصي 2×2",
          [P("tp", "True positives (a)", "إيجابي حقيقي", "int", default=90), P("fp", "False positives (b)", "إيجابي كاذب", "int", default=15),
           P("fn", "False negatives (c)", "سلبي كاذب", "int", default=10), P("tn", "True negatives (d)", "سلبي حقيقي", "int", default=185),
           P("prevalence", "Population prevalence % (optional, for PPV/NPV)", "الانتشار في المجتمع % (اختياري)", "float", default=0.0)],
          "All accuracy indices with exact/Wilson CIs from a 2×2 table (no dataset needed).",
          "جميع مؤشرات الدقة مع فترات الثقة من جدول 2×2.", needs_data=False)
def diag2x2(tp=90, fp=15, fn=10, tn=185, prevalence=0.0):
    n = tp + fp + fn + tn
    sens, spec = tp / (tp + fn), tn / (tn + fp)
    prev = prevalence / 100 if prevalence else (tp + fn) / n
    ppv = sens * prev / (sens * prev + (1 - spec) * (1 - prev))
    npv = spec * (1 - prev) / (spec * (1 - prev) + (1 - sens) * prev)
    lrp = sens / (1 - spec) if spec < 1 else np.inf
    lrn = (1 - sens) / spec if spec > 0 else np.inf
    dor = lrp / lrn if lrn > 0 else np.inf
    rows = []
    for name, x, m in [("Sensitivity", tp, tp + fn), ("Specificity", tn, tn + fp), ("Accuracy", tp + tn, n)]:
        lo, hi = wilson_ci(x, m)
        rows.append({"Index": name, "Estimate": x / m * 100, "95% CI lower": lo * 100, "95% CI upper": hi * 100})
    if not prevalence:
        for name, x, m in [("PPV", tp, tp + fp), ("NPV", tn, tn + fn)]:
            lo, hi = wilson_ci(x, m)
            rows.append({"Index": name, "Estimate": x / m * 100, "95% CI lower": lo * 100, "95% CI upper": hi * 100})
    else:
        rows += [{"Index": f"PPV (prevalence {prevalence}%)", "Estimate": ppv * 100, "95% CI lower": np.nan, "95% CI upper": np.nan},
                 {"Index": f"NPV (prevalence {prevalence}%)", "Estimate": npv * 100, "95% CI lower": np.nan, "95% CI upper": np.nan}]

    def lr_ci(a, b, c, d, pos=True):
        if pos:
            se = math.sqrt(1 / a - 1 / (a + c) + 1 / b - 1 / (b + d))
            v = (a / (a + c)) / (b / (b + d))
        else:
            se = math.sqrt(1 / c - 1 / (a + c) + 1 / d - 1 / (b + d))
            v = (c / (a + c)) / (d / (b + d))
        return v * math.exp(-1.96 * se), v * math.exp(1.96 * se)
    try:
        lp = lr_ci(tp, fp, fn, tn, True); ln = lr_ci(tp, fp, fn, tn, False)
    except (ZeroDivisionError, ValueError):
        lp = ln = (np.nan, np.nan)
    rows += [{"Index": "LR+", "Estimate": lrp, "95% CI lower": lp[0], "95% CI upper": lp[1]},
             {"Index": "LR−", "Estimate": lrn, "95% CI lower": ln[0], "95% CI upper": ln[1]},
             {"Index": "Diagnostic odds ratio", "Estimate": dor, "95% CI lower": np.nan, "95% CI upper": np.nan},
             {"Index": "Youden index", "Estimate": sens + spec - 1, "95% CI lower": np.nan, "95% CI upper": np.nan}]
    res = Result("Diagnostic accuracy (2×2)", f"TP = {tp}, FP = {fp}, FN = {fn}, TN = {tn}")
    res.table(pd.DataFrame(rows), "Diagnostic accuracy indices (%)", "Wilson score CIs; log-method CIs for likelihood ratios.")
    res.interpret(f"Sensitivity {sens*100:.1f}% and specificity {spec*100:.1f}%. LR+ = {lrp:.2f}: "
                  + ("a positive result strongly rules IN disease (LR+ > 10)" if lrp > 10 else "moderate rule-in value" if lrp > 5 else "limited rule-in value")
                  + f"; LR− = {lrn:.2f}: " + ("a negative result strongly rules OUT disease (LR− < 0.1)." if lrn < 0.1 else "limited rule-out value." if lrn > 0.2 else "moderate rule-out value."),
                  f"الحساسية {sens*100:.1f}% والنوعية {spec*100:.1f}%. نسبة الأرجحية الموجبة {lrp:.2f} والسالبة {lrn:.2f}.")
    return res


# ------------------------------------------------------------------ Agreement
@register("kappa", "agreement", "Cohen's kappa (weighted) / Fleiss' kappa", "معامل كابا لكوهين وفلايس",
          [P("raters", "Rater columns (2 = Cohen, ≥3 = Fleiss)", "أعمدة المقيمين (2 = كوهين، 3+ = فلايس)", "vars_any"),
           P("weights", "Weighting (Cohen, ordinal)", "الترجيح (للفئات الترتيبية)", "choice", ["None", "Linear", "Quadratic"], "None")],
          "Inter-rater agreement for categorical ratings with SE, 95% CI and Landis-Koch interpretation.",
          "الاتفاق بين المقيمين للتقييمات الفئوية مع فترة الثقة وتفسير لانديس-كوخ.")
def kappa(df, raters, weights="None"):
    d = df[list(raters)].dropna()
    if len(raters) < 2:
        raise AnalysisError("Select at least 2 rater columns.")
    cats = sorted(set(np.unique(d.values.astype(str))), key=lambda v: (float(v) if _isnum(v) else np.inf, v))
    res = Result("Inter-rater agreement (kappa)", f"{len(raters)} raters, {len(d)} subjects, categories: {', '.join(cats)}")

    def landis(k):
        return ("poor", "ضعيف") if k < 0 else ("slight", "طفيف") if k <= .2 else ("fair", "مقبول") if k <= .4 else ("moderate", "متوسط") if k <= .6 else ("substantial", "جيد") if k <= .8 else ("almost perfect", "شبه تام")
    if len(raters) == 2:
        a = d[raters[0]].astype(str).values; b = d[raters[1]].astype(str).values
        k = len(cats)
        idx = {c: i for i, c in enumerate(cats)}
        O = np.zeros((k, k))
        for x, y in zip(a, b):
            O[idx[x], idx[y]] += 1
        n = O.sum()
        P_ = O / n
        r, c = P_.sum(1), P_.sum(0)
        E = np.outer(r, c)
        I, J = np.meshgrid(range(k), range(k), indexing="ij")
        if weights == "Linear":
            W = 1 - np.abs(I - J) / (k - 1)
        elif weights == "Quadratic":
            W = 1 - (I - J) ** 2 / (k - 1) ** 2
        else:
            W = np.eye(k)
        po, pe = (W * P_).sum(), (W * E).sum()
        kap = (po - pe) / (1 - pe)
        # Fleiss-Cohen-Everitt asymptotic SE
        wr = W @ c
        wc = W.T @ r
        se = math.sqrt(max(((P_ * (W * (1 - pe) - (wr[:, None] + wc[None, :]) * (1 - po)) ** 2).sum() - (po * pe - 2 * pe + po) ** 2, 0)) / ((1 - pe) ** 2 * math.sqrt(n)))
        se0 = math.sqrt(max((E * (W - (wr[:, None] + wc[None, :])) ** 2).sum() - pe ** 2, 0)) / ((1 - pe) * math.sqrt(n))
        z = kap / se0 if se0 > 0 else np.nan
        tab = pd.DataFrame(O.astype(int), index=[f"{raters[0]}: {c_}" for c_ in cats], columns=[f"{raters[1]}: {c_}" for c_ in cats])
        res.table(tab, "Agreement table")
        res.table(pd.DataFrame([{"Kappa": kap, "Weighting": weights, "Observed agreement %": po * 100, "Expected agreement %": pe * 100,
                                 "ASE": se, "95% CI lower": kap - 1.96 * se, "95% CI upper": kap + 1.96 * se, "z": z,
                                 "p": 2 * stats.norm.sf(abs(z))}]), "Cohen's kappa")
    else:
        X = d.astype(str).values
        n, m = X.shape
        counts = np.array([[np.sum(row == c_) for c_ in cats] for row in X])
        pj = counts.sum(0) / (n * m)
        Pi = (np.sum(counts ** 2, 1) - m) / (m * (m - 1))
        Pbar, Pe = Pi.mean(), np.sum(pj ** 2)
        kap = (Pbar - Pe) / (1 - Pe)
        se = math.sqrt(2) / (np.sum(pj * (1 - pj)) * math.sqrt(n * m * (m - 1))) * math.sqrt(
            np.sum(pj * (1 - pj)) ** 2 - np.sum(pj * (1 - pj) * (1 - 2 * pj)))
        z = kap / se
        res.table(pd.DataFrame([{"Fleiss' kappa": kap, "SE (H0)": se, "z": z, "p": 2 * stats.norm.sf(abs(z)),
                                 "95% CI lower": kap - 1.96 * se, "95% CI upper": kap + 1.96 * se}]), "Fleiss' kappa")
    L = landis(kap)
    res.interpret(f"κ = {kap:.3f}: {L[0]} agreement (Landis & Koch). Kappa corrects for chance agreement; for ordinal scales use weighted kappa.",
                  f"κ = {kap:.3f}: اتفاق {L[1]} حسب تصنيف لانديس وكوخ. معامل كابا يصحح الاتفاق الناتج عن الصدفة.")
    return res


def _isnum(v):
    try:
        float(v)
        return True
    except ValueError:
        return False


@register("icc", "agreement", "Intraclass correlation (ICC)", "معامل الارتباط داخل الفئة ICC",
          [P("raters", "Raters / repeated measurements (columns)", "المقيمون / القياسات المتكررة (أعمدة)", "vars_num")],
          "All six Shrout-Fleiss / McGraw-Wong ICC forms with F tests and 95% CIs.",
          "الأشكال الستة لمعامل ICC مع اختبارات F وفترات الثقة.")
def icc(df, raters):
    d = pd.DataFrame({r: numeric(df, r) for r in raters}).dropna()
    Y = d.to_numpy(float)
    n, k = Y.shape
    gm = Y.mean()
    ssr = k * ((Y.mean(1) - gm) ** 2).sum()
    ssc = n * ((Y.mean(0) - gm) ** 2).sum()
    sst = ((Y - gm) ** 2).sum()
    sse = sst - ssr - ssc
    msr, msc = ssr / (n - 1), ssc / (k - 1)
    mse = sse / ((n - 1) * (k - 1))
    msw = (ssc + sse) / (n * (k - 1))
    a = 0.05
    rows = []
    # ICC1 one-way random
    F1 = msr / msw
    df1, df2 = n - 1, n * (k - 1)
    FL, FU = F1 / stats.f.ppf(1 - a / 2, df1, df2), F1 * stats.f.ppf(1 - a / 2, df2, df1)
    rows.append(("ICC(1,1)", "One-way random, single", (msr - msw) / (msr + (k - 1) * msw), F1, df1, df2,
                 (FL - 1) / (FL + k - 1), (FU - 1) / (FU + k - 1)))
    rows.append(("ICC(1,k)", "One-way random, average", (msr - msw) / msr, F1, df1, df2, 1 - 1 / FL, 1 - 1 / FU))
    # ICC2 two-way random, absolute agreement
    F2 = msr / mse
    icc21 = (msr - mse) / (msr + (k - 1) * mse + k * (msc - mse) / n)
    Fj = msc / mse
    vn = (k - 1) * (n - 1) * (k * icc21 * Fj + n * (1 + (k - 1) * icc21) - k * icc21) ** 2
    vd = (n - 1) * k ** 2 * icc21 ** 2 * Fj ** 2 + (n * (1 + (k - 1) * icc21) - k * icc21) ** 2
    v = vn / vd
    Fs, Fi = stats.f.ppf(1 - a / 2, n - 1, v), stats.f.ppf(1 - a / 2, v, n - 1)
    L2 = n * (msr - Fs * mse) / (Fs * (k * msc + (k * n - k - n) * mse) + n * msr)
    U2 = n * (Fi * msr - mse) / (k * msc + (k * n - k - n) * mse + n * Fi * msr)
    rows.append(("ICC(2,1)", "Two-way random, absolute agreement, single", icc21, F2, n - 1, (n - 1) * (k - 1), L2, U2))
    rows.append(("ICC(2,k)", "Two-way random, absolute agreement, average", (msr - mse) / (msr + (msc - mse) / n), F2, n - 1,
                 (n - 1) * (k - 1), L2 * k / (1 + L2 * (k - 1)), U2 * k / (1 + U2 * (k - 1))))
    # ICC3 two-way mixed, consistency
    FL3, FU3 = F2 / stats.f.ppf(1 - a / 2, n - 1, (n - 1) * (k - 1)), F2 * stats.f.ppf(1 - a / 2, (n - 1) * (k - 1), n - 1)
    rows.append(("ICC(3,1)", "Two-way mixed, consistency, single", (msr - mse) / (msr + (k - 1) * mse), F2, n - 1, (n - 1) * (k - 1),
                 (FL3 - 1) / (FL3 + k - 1), (FU3 - 1) / (FU3 + k - 1)))
    rows.append(("ICC(3,k)", "Two-way mixed, consistency, average", (msr - mse) / msr, F2, n - 1, (n - 1) * (k - 1), 1 - 1 / FL3, 1 - 1 / FU3))
    tab = pd.DataFrame(rows, columns=["Type", "Model", "ICC", "F", "df1", "df2", "95% CI lower", "95% CI upper"])
    tab["p"] = [stats.f.sf(r[3], r[4], r[5]) for r in rows]
    res = Result("Intraclass correlation coefficients", f"{k} raters/measurements, n = {n} subjects")
    res.table(tab, "ICC (Shrout & Fleiss 1979; McGraw & Wong 1996)",
              "For inter-rater reliability with raters representing a larger population use ICC(2,1) absolute agreement; for test-retest use ICC(3,1).")
    v21 = rows[2][2]
    grade = ("poor", "ضعيف") if v21 < 0.5 else ("moderate", "متوسط") if v21 < 0.75 else ("good", "جيد") if v21 < 0.9 else ("excellent", "ممتاز")
    res.interpret(f"ICC(2,1) = {v21:.3f} (95% CI {rows[2][6]:.3f}–{rows[2][7]:.3f}): {grade[0]} reliability (Koo & Li 2016). "
                  "Always state the ICC form (model, type, unit) in the manuscript.",
                  f"ICC(2,1) = {v21:.3f}: ثبات {grade[1]} حسب تصنيف كو ولي 2016. اذكر دائمًا نوع ICC المستخدم في البحث.")
    return res


@register("blandaltman", "agreement", "Bland-Altman agreement", "تحليل بلاند-ألتمان للاتفاق",
          [P("method1", "Method 1", "الطريقة الأولى", "var_num"), P("method2", "Method 2", "الطريقة الثانية", "var_num"),
           P("percent", "Plot differences as", "عرض الفروق كـ", "choice", ["Absolute", "Percentage of mean"], "Absolute")],
          "Bias, 95% limits of agreement with CIs, proportional-bias regression and plot.",
          "التحيز وحدود الاتفاق 95% مع فترات الثقة واختبار التحيز التناسبي والرسم.")
def blandaltman(df, method1, method2, percent="Absolute"):
    d = pd.DataFrame({"a": numeric(df, method1), "b": numeric(df, method2)}).dropna()
    mean = (d.a + d.b) / 2
    diff = d.a - d.b
    if percent.startswith("Percentage"):
        diff = diff / mean * 100
    n = len(d)
    bias, sd = diff.mean(), diff.std(ddof=1)
    lo, hi = bias - 1.96 * sd, bias + 1.96 * sd
    t = stats.t.ppf(0.975, n - 1)
    se_b = sd / math.sqrt(n)
    se_l = math.sqrt(3 * sd ** 2 / n)
    reg = stats.linregress(mean, diff)
    res = Result("Bland-Altman analysis", f"{method1} − {method2} (n = {n})")
    res.table(pd.DataFrame([
        {"Parameter": "Bias (mean difference)", "Estimate": bias, "95% CI lower": bias - t * se_b, "95% CI upper": bias + t * se_b},
        {"Parameter": "SD of differences", "Estimate": sd, "95% CI lower": np.nan, "95% CI upper": np.nan},
        {"Parameter": "Lower limit of agreement", "Estimate": lo, "95% CI lower": lo - t * se_l, "95% CI upper": lo + t * se_l},
        {"Parameter": "Upper limit of agreement", "Estimate": hi, "95% CI lower": hi - t * se_l, "95% CI upper": hi + t * se_l}]),
        "Bland-Altman statistics" + (" (% of mean)" if percent.startswith("Percentage") else ""))
    pb = stats.ttest_1samp(diff, 0).pvalue
    res.table(pd.DataFrame([{"Test": "Fixed bias (one-sample t on differences)", "Statistic": stats.ttest_1samp(diff, 0).statistic, "p": pb},
                            {"Test": "Proportional bias (slope of difference on mean)", "Statistic": reg.slope, "p": reg.pvalue}]),
              "Bias tests")
    res.interpret(f"On average {method1} reads {abs(bias):.3g} {'higher' if bias > 0 else 'lower'} than {method2} "
                  f"({'significant fixed bias' if pb < 0.05 else 'no significant fixed bias'}, {pstr(pb)}). 95% of differences lie between "
                  f"{lo:.3g} and {hi:.3g}; whether this range is clinically acceptable must be judged against a pre-defined clinical limit. "
                  + ("Proportional bias present (" + pstr(reg.pvalue) + ")." if reg.pvalue < 0.05 else "No proportional bias."),
                  f"في المتوسط تعطي {method1} قراءات {'أعلى' if bias > 0 else 'أقل'} بمقدار {abs(bias):.3g} من {method2} ({pstr(pb)}). "
                  f"95% من الفروق تقع بين {lo:.3g} و{hi:.3g}؛ ويجب الحكم على قبول هذا المدى سريريًا مقابل حد مسبق التحديد.")
    res.figure(F.bland_altman_plot(mean.values, diff.values, bias, lo, hi,
                                   ci=[(lo - t * se_l, lo + t * se_l), (hi - t * se_l, hi + t * se_l)],
                                   xlabel=f"Mean of {method1} and {method2}",
                                   ylabel=f"{method1} − {method2}" + (" (%)" if percent.startswith("Percentage") else "")),
               "Bland-Altman plot: bias (solid) and 95% limits of agreement (dashed) with CIs (shaded).")
    res.methods("Agreement between methods was assessed by the Bland-Altman method, reporting the bias and 95% limits of agreement with their CIs.")
    return res


@register("cronbach", "agreement", "Cronbach's alpha (scale reliability)", "معامل ألفا كرونباخ لثبات المقياس",
          [P("items", "Scale items", "بنود المقياس", "vars_num")],
          "Internal consistency with item-total statistics and alpha-if-item-deleted.", "الاتساق الداخلي مع إحصاءات البنود.")
def cronbach(df, items):
    d = pd.DataFrame({c: numeric(df, c) for c in items}).dropna()
    k = d.shape[1]

    def alpha(x):
        kk = x.shape[1]
        return kk / (kk - 1) * (1 - x.var(ddof=1).sum() / x.sum(1).var(ddof=1))
    a = alpha(d)
    n = len(d)
    lo = 1 - (1 - a) * stats.f.ppf(0.975, n - 1, (n - 1) * (k - 1))
    hi = 1 - (1 - a) * stats.f.ppf(0.025, n - 1, (n - 1) * (k - 1))
    std_a = k * d.corr().values[np.triu_indices(k, 1)].mean() / (1 + (k - 1) * d.corr().values[np.triu_indices(k, 1)].mean())
    rows = []
    for c in items:
        rest = d.drop(columns=c)
        rows.append({"Item": c, "Mean": d[c].mean(), "SD": d[c].std(), "Corrected item-total r": np.corrcoef(d[c], rest.sum(1))[0, 1],
                     "Alpha if deleted": alpha(rest) if rest.shape[1] > 1 else np.nan})
    res = Result("Reliability analysis", f"{k} items, n = {n}")
    res.table(pd.DataFrame([{"Cronbach's α": a, "95% CI lower": lo, "95% CI upper": hi, "Standardized α": std_a, "Items": k}]), "Reliability statistics")
    res.table(pd.DataFrame(rows), "Item-total statistics")
    g = ("excellent", "ممتاز") if a >= .9 else ("good", "جيد") if a >= .8 else ("acceptable", "مقبول") if a >= .7 else ("questionable", "مشكوك فيه") if a >= .6 else ("poor", "ضعيف")
    weak = [r["Item"] for r in rows if r["Corrected item-total r"] < 0.3]
    res.interpret(f"Cronbach's α = {a:.3f}: {g[0]} internal consistency." + (f" Items with item-total r < 0.30: {', '.join(weak)} — consider revising." if weak else ""),
                  f"ألفا كرونباخ = {a:.3f}: اتساق داخلي {g[1]}." + (f" بنود ضعيفة الارتباط: {', '.join(weak)}." if weak else ""))
    return res
