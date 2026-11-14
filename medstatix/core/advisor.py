"""Smart statistical advisor.

1. ``auto_analyze``: inspects the chosen variables (type, number of groups,
   normality, variance homogeneity, expected counts) and selects + runs the
   appropriate test, explaining every decision in English and Arabic.
2. ``WIZARD``: decision tree used by the "Which test?" assistant dialog.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .data import var_kind, numeric, _level_order
from .result import Result, AnalysisError, fmt_p


def _pe(p):
    """'= 0.023' or '< 0.001' (so text reads 'p = 0.023' / 'p < 0.001')."""
    t = fmt_p(p)
    return t if t.startswith("<") else "= " + t


def _normal(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) < 3:
        return True, np.nan
    p = stats.shapiro(x)[1] if len(x) <= 5000 else stats.normaltest(x)[1]
    return p >= 0.05, p


def auto_analyze(df: pd.DataFrame, outcome: str, factor: str | None = None):
    from ..analyses.registry import run
    en, ar = [], []
    from .errors import validate_smart
    validate_smart(df, outcome, factor)
    ok = var_kind(df[outcome])
    en.append(f"Outcome '{outcome}' detected as {ok}.")
    ar.append(f"تم التعرف على المتغير التابع '{outcome}' كمتغير {({'continuous': 'كمي متصل', 'binary': 'ثنائي', 'categorical': 'فئوي'})[ok]}.")
    if factor is None:
        if ok == "continuous":
            aid, kw = "descriptives", {"variables": [outcome]}
            en.append("No grouping factor → descriptive statistics with normality assessment.")
            ar.append("لا يوجد عامل تقسيم ← إحصاء وصفي مع تقييم التوزيع الطبيعي.")
        else:
            aid, kw = "frequencies", {"variables": [outcome]}
            en.append("Categorical outcome without factor → frequency table.")
            ar.append("متغير فئوي بدون عامل ← جدول تكرارات.")
    else:
        fk = var_kind(df[factor])
        en.append(f"Factor '{factor}' detected as {fk}.")
        ar.append(f"تم التعرف على العامل '{factor}' كمتغير {({'continuous': 'كمي متصل', 'binary': 'ثنائي', 'categorical': 'فئوي'})[fk]}.")
        if ok == "continuous" and fk in ("binary", "categorical"):
            levels = _level_order(df[factor].dropna())
            y = numeric(df, outcome)
            groups = {str(l): y[df[factor] == l].dropna().values for l in levels}
            norms = {k: _normal(v) for k, v in groups.items()}
            all_norm = all(v[0] for v in norms.values())
            small = min(len(v) for v in groups.values())
            en.append(f"{len(levels)} independent groups (smallest n = {small}). Shapiro-Wilk: " +
                      ", ".join(f"{k} p {_pe(v[1])}" for k, v in norms.items()) + ".")
            ar.append(f"{len(levels)} مجموعات مستقلة (أصغر عدد = {small}). اختبار شابيرو-ويلك: " +
                      "، ".join(f"{k} p {_pe(v[1])}" for k, v in norms.items()) + ".")
            lev_p = stats.levene(*groups.values(), center="median")[1]
            if len(levels) >= 3:
                # ANOVA assumes normal residuals; testing the pooled residuals avoids the inflated false-alarm
                # rate of running one Shapiro-Wilk test per group
                resid = np.concatenate([v - v.mean() for v in groups.values()])
                all_norm, p_res = _normal(resid)
                en.append(f"Normality of the ANOVA residuals (pooled, n = {len(resid)}): Shapiro-Wilk p {_pe(p_res)}.")
                ar.append(f"التوزيع الطبيعي لبواقي تحليل التباين (مجمّعة، العدد = {len(resid)}): شابيرو-ويلك p {_pe(p_res)}.")
            if len(levels) == 2:
                if all_norm:
                    aid, kw = "ttest_ind", {"outcome": outcome, "group": factor}
                    en.append("Normal data in both groups → independent t-test (Welch's version reported as default).")
                    ar.append("البيانات طبيعية في المجموعتين ← اختبار t للعينات المستقلة (يُعرض اختبار ويلش افتراضيًا).")
                else:
                    aid, kw = "mannwhitney", {"outcome": outcome, "group": factor}
                    en.append("Normality violated → Mann-Whitney U test (non-parametric).")
                    ar.append("التوزيع غير طبيعي ← اختبار مان-ويتني (لامعلمي).")
            else:
                if all_norm:
                    ph = "Tukey HSD" if lev_p >= 0.05 else "Games-Howell"
                    aid, kw = "anova1", {"outcome": outcome, "group": factor, "posthoc": ph}
                    en.append(f"Normal data, ≥ 3 groups → one-way ANOVA; Levene p {_pe(lev_p)} → {ph} post hoc.")
                    ar.append(f"بيانات طبيعية و3 مجموعات أو أكثر ← تحليل التباين الأحادي؛ اختبار ليفين p {_pe(lev_p)} ← اختبار {ph} البعدي.")
                else:
                    aid, kw = "kruskal", {"outcome": outcome, "group": factor}
                    en.append("Normality violated, ≥ 3 groups → Kruskal-Wallis with Dunn's post hoc.")
                    ar.append("توزيع غير طبيعي و3 مجموعات أو أكثر ← كروسكال-واليس مع اختبار دن البعدي.")
        elif ok in ("binary", "categorical") and fk in ("binary", "categorical"):
            aid, kw = "chisq", {"row": factor, "col": outcome}
            en.append("Two categorical variables → contingency table; Fisher's exact is used automatically if expected counts < 5.")
            ar.append("متغيران فئويان ← جدول تقاطعي؛ يُستخدم اختبار فيشر تلقائيًا إذا كانت التكرارات المتوقعة أقل من 5.")
        elif ok == "continuous" and fk == "continuous":
            n1, _ = _normal(numeric(df, outcome))
            n2, _ = _normal(numeric(df, factor))
            meth = "Pearson" if (n1 and n2) else "Spearman"
            aid, kw = "correlation", {"variables": [factor, outcome], "method": meth}
            en.append(f"Two continuous variables; {'both normal' if meth == 'Pearson' else 'at least one non-normal'} → {meth} correlation.")
            ar.append(f"متغيران كميان؛ {'كلاهما طبيعي' if meth == 'Pearson' else 'أحدهما على الأقل غير طبيعي'} ← ارتباط {meth}.")
        elif ok == "binary" and fk == "continuous":
            aid, kw = "logreg", {"outcome": outcome, "predictors": [factor], "univariable": False}
            en.append("Binary outcome with continuous predictor → logistic regression (OR per unit). For a diagnostic marker use ROC analysis.")
            ar.append("متغير تابع ثنائي مع متغير مستقل كمي ← انحدار لوجستي. إذا كان المتغير مؤشرًا تشخيصيًا استخدم تحليل ROC.")
        else:
            raise AnalysisError("Could not determine an appropriate test for this combination; use the analysis menu.")
    res = run(aid, df, **kw)
    res.blocks.insert(0, __import__("medstatix.core.result", fromlist=["Block"]).Block(
        "interpret", {"en": "Smart advisor — design diagnosis:\n" + "\n".join("• " + e for e in en),
                      "ar": "المساعد الذكي — تشخيص التصميم:\n" + "\n".join("• " + a for a in ar)}))
    res.title = "🧠 " + res.title
    return res, aid


# --------------------------------------------------------------- wizard tree
# Each node: question (en, ar), options [(en, ar, next_node_or_result)]
# A result is ("RESULT", analysis_id, explanation_en, explanation_ar)
WIZARD = {
    "start": (("What is your research goal?", "ما هدف التحليل؟"), [
        (("Compare groups", "مقارنة مجموعات"), "outcome"),
        (("Relationship / prediction between variables", "علاقة أو تنبؤ بين متغيرات"), "relation"),
        (("Time-to-event (survival)", "الزمن حتى حدوث الحدث (البقاء)"), "surv"),
        (("Diagnostic test accuracy", "دقة اختبار تشخيصي"), "diag"),
        (("Agreement / reliability of measurements", "الاتفاق / ثبات القياسات"), "agree"),
        (("Dose-response / toxicity / pharmacokinetics", "الجرعة-الاستجابة / السمية / الحرائك"), "pharm"),
        (("Combine published studies (meta-analysis)", "دمج دراسات منشورة (تحليل تجميعي)"), ("RESULT", "meta", "Random-effects meta-analysis with forest plot.", "تحليل تجميعي بنموذج التأثيرات العشوائية.")),
        (("Plan a study (sample size)", "التخطيط لدراسة (حجم العينة)"), ("RESULT", "power", "A-priori sample size calculation.", "حساب حجم العينة المسبق.")),
    ]),
    "outcome": (("What type is the outcome variable?", "ما نوع المتغير التابع؟"), [
        (("Continuous (e.g. blood pressure, enzyme level)", "كمي متصل (ضغط الدم، مستوى إنزيم)"), "ngroups"),
        (("Categorical / binary (e.g. cured yes/no)", "فئوي/ثنائي (شُفي نعم/لا)"), "catpaired"),
        (("Ordinal score (e.g. pain 0–10, grade)", "ترتيبي (درجة ألم، تصنيف)"), "ngroups_np"),
    ]),
    "ngroups": (("How many groups and how are they related?", "كم عدد المجموعات وما العلاقة بينها؟"), [
        (("2 independent groups", "مجموعتان مستقلتان"), "norm2"),
        (("2 paired measurements (before/after)", "قياسان مزدوجان (قبل/بعد)"), "normp"),
        (("≥ 3 independent groups", "3 مجموعات مستقلة أو أكثر"), "norm3"),
        (("≥ 3 repeated measurements on the same subjects", "3 قياسات متكررة أو أكثر على نفس الأفراد"), "normrm"),
        (("Two factors (e.g. drug × sex)", "عاملان (مثل الدواء × الجنس)"), ("RESULT", "anova2", "Two-way ANOVA: test the interaction first.", "تحليل التباين الثنائي: افحص التفاعل أولًا.")),
        (("Groups + baseline covariate", "مجموعات مع قيمة أساسية مصاحبة"), ("RESULT", "ancova", "ANCOVA adjusting for baseline (better than change scores).", "تحليل التغاير مع ضبط القيمة الأساسية.")),
        (("Repeated measures with missing visits / groups", "قياسات متكررة مع زيارات مفقودة / مجموعات"), ("RESULT", "mixed", "Linear mixed model (handles missing data).", "النموذج المختلط الخطي (يتعامل مع البيانات المفقودة).")),
    ]),
    "ngroups_np": (("How many groups?", "كم عدد المجموعات؟"), [
        (("2 independent", "مجموعتان مستقلتان"), ("RESULT", "mannwhitney", "Mann-Whitney U test.", "اختبار مان-ويتني.")),
        (("2 paired", "قياسان مزدوجان"), ("RESULT", "wilcoxon", "Wilcoxon signed-rank test.", "اختبار ويلكوكسون.")),
        (("≥ 3 independent", "3 مستقلة أو أكثر"), ("RESULT", "kruskal", "Kruskal-Wallis + Dunn.", "كروسكال-واليس مع دن.")),
        (("≥ 3 repeated", "3 متكررة أو أكثر"), ("RESULT", "friedman", "Friedman test.", "اختبار فريدمان.")),
        (("Ordinal outcome with predictors", "متغير ترتيبي مع متغيرات مستقلة"), ("RESULT", "ordinal", "Ordinal logistic regression.", "الانحدار اللوجستي الترتيبي.")),
    ]),
    "norm2": (("Is the outcome approximately normal in each group (Shapiro-Wilk p > 0.05, n ≥ 15)?", "هل التوزيع طبيعي تقريبًا في كل مجموعة؟"), [
        (("Yes", "نعم"), ("RESULT", "ttest_ind", "Independent t-test (Welch).", "اختبار t للعينات المستقلة (ويلش).")),
        (("No / not sure / small n", "لا / غير متأكد / عينة صغيرة"), ("RESULT", "mannwhitney", "Mann-Whitney U test.", "اختبار مان-ويتني.")),
    ]),
    "normp": (("Are the paired differences approximately normal?", "هل الفروق المزدوجة طبيعية التوزيع؟"), [
        (("Yes", "نعم"), ("RESULT", "ttest_paired", "Paired t-test.", "اختبار t المزدوج.")),
        (("No", "لا"), ("RESULT", "wilcoxon", "Wilcoxon signed-rank test.", "اختبار ويلكوكسون.")),
    ]),
    "norm3": (("Is the outcome approximately normal in each group?", "هل التوزيع طبيعي في كل مجموعة؟"), [
        (("Yes", "نعم"), ("RESULT", "anova1", "One-way ANOVA + Tukey (or Dunnett vs control; Games-Howell if variances unequal).", "تحليل التباين الأحادي + توكي (أو دانيت مقابل الضابطة).")),
        (("No", "لا"), ("RESULT", "kruskal", "Kruskal-Wallis + Dunn's test.", "كروسكال-واليس + اختبار دن.")),
    ]),
    "normrm": (("Is the outcome approximately normal at each time point?", "هل التوزيع طبيعي عند كل نقطة زمنية؟"), [
        (("Yes, complete data", "نعم وبيانات كاملة"), ("RESULT", "rmanova", "Repeated-measures ANOVA with Greenhouse-Geisser.", "تحليل التباين للقياسات المتكررة.")),
        (("Yes, but missing visits", "نعم مع زيارات مفقودة"), ("RESULT", "mixed", "Linear mixed model.", "النموذج المختلط الخطي.")),
        (("No", "لا"), ("RESULT", "friedman", "Friedman test.", "اختبار فريدمان.")),
    ]),
    "catpaired": (("Are the groups independent or paired?", "هل المجموعات مستقلة أم مزدوجة؟"), [
        (("Independent groups", "مجموعات مستقلة"), ("RESULT", "chisq", "χ² test (Fisher's exact automatically when expected counts < 5); OR/RR for 2×2.", "كاي تربيع (فيشر تلقائيًا عند الحاجة) مع OR/RR.")),
        (("Paired (before/after, matched)", "مزدوجة (قبل/بعد، مطابقة)"), ("RESULT", "mcnemar", "McNemar test.", "اختبار مكنمار.")),
        (("Adjust for a confounder (strata)", "ضبط متغير مربك (طبقات)"), ("RESULT", "mantel", "Mantel-Haenszel.", "مانتل-هانزل.")),
        (("Several predictors", "عدة متغيرات مستقلة"), ("RESULT", "logreg", "Multivariable logistic regression.", "الانحدار اللوجستي المتعدد.")),
    ]),
    "relation": (("What type is the outcome?", "ما نوع المتغير التابع؟"), [
        (("Continuous — association only (2 variables)", "كمي — ارتباط فقط بين متغيرين"), ("RESULT", "correlation", "Pearson (normal) or Spearman correlation.", "ارتباط بيرسون أو سبيرمان.")),
        (("Continuous — prediction / adjustment", "كمي — تنبؤ / ضبط متغيرات"), ("RESULT", "linreg", "Multiple linear regression.", "الانحدار الخطي المتعدد.")),
        (("Binary (yes/no)", "ثنائي (نعم/لا)"), ("RESULT", "logreg", "Binary logistic regression.", "الانحدار اللوجستي الثنائي.")),
        (("Count (number of events)", "عدّ (عدد الأحداث)"), ("RESULT", "countreg", "Poisson / negative binomial regression.", "انحدار بواسون / ذو الحدين السالب.")),
        (("Ordinal", "ترتيبي"), ("RESULT", "ordinal", "Ordinal logistic regression.", "الانحدار اللوجستي الترتيبي.")),
        (("Many variables — find structure", "متغيرات كثيرة — اكتشاف البنية"), ("RESULT", "pca", "Principal component analysis.", "تحليل المكونات الرئيسية.")),
    ]),
    "surv": (("What do you need?", "ماذا تحتاج؟"), [
        (("Survival curves and group comparison", "منحنيات البقاء ومقارنة المجموعات"), ("RESULT", "km", "Kaplan-Meier with log-rank.", "كابلان-ماير مع لوغ-رانك.")),
        (("Hazard ratios adjusted for covariates", "نسب الخطورة المعدلة"), ("RESULT", "cox", "Cox proportional hazards regression.", "انحدار كوكس.")),
    ]),
    "diag": (("What data do you have?", "ما البيانات المتاحة؟"), [
        (("A continuous marker and a reference standard", "مؤشر كمي ومعيار مرجعي"), ("RESULT", "roc", "ROC analysis with optimal cut-off.", "تحليل ROC مع نقطة القطع المثلى.")),
        (("A 2×2 table (TP, FP, FN, TN)", "جدول 2×2"), ("RESULT", "diag2x2", "Sensitivity, specificity, PPV, NPV, LRs.", "الحساسية والنوعية والقيم التنبؤية.")),
    ]),
    "agree": (("What type are the measurements?", "ما نوع القياسات؟"), [
        (("Continuous — two methods", "كمية — طريقتان"), ("RESULT", "blandaltman", "Bland-Altman (not correlation).", "بلاند-ألتمان (وليس الارتباط).")),
        (("Continuous — ≥ 2 raters / test-retest", "كمية — مقيمون أو إعادة اختبار"), ("RESULT", "icc", "Intraclass correlation.", "معامل ICC.")),
        (("Categorical ratings", "تقييمات فئوية"), ("RESULT", "kappa", "Cohen's / Fleiss' kappa.", "معامل كابا.")),
        (("Questionnaire items", "بنود استبيان"), ("RESULT", "cronbach", "Cronbach's alpha.", "ألفا كرونباخ.")),
    ]),
    "pharm": (("Which analysis?", "أي تحليل؟"), [
        (("Quantal mortality data → LD50", "بيانات نفوق → LD50"), ("RESULT", "probit", "Probit analysis with Fieller limits.", "تحليل البروبيت مع حدود فيلر.")),
        (("Graded concentration-response → EC50/IC50", "استجابة متدرجة → EC50/IC50"), ("RESULT", "doseresp", "4-parameter logistic fit.", "مواءمة لوجستية رباعية.")),
        (("Enzyme kinetics", "حركية إنزيمية"), ("RESULT", "michaelis", "Michaelis-Menten.", "ميكاليس-منتن.")),
        (("Plasma concentration-time data", "تركيز البلازما مع الزمن"), ("RESULT", "nca", "Non-compartmental PK analysis.", "التحليل اللاحجيري للحرائك.")),
    ]),
}


# --------------------------------------------------------------- recommendations after import
def _plan_group_test(y_by_group):
    """Decide the test for a numeric outcome across independent groups (same rules as auto_analyze)."""
    groups = [np.asarray(v, float) for v in y_by_group if len(v)]
    k = len(groups)
    small = min(len(g) for g in groups)
    if k == 2:
        normal = all(_normal(g)[0] for g in groups)
        return (("Welch t-test", "اختبار t (ويلش)", "normal data in both groups", "البيانات طبيعية في المجموعتين") if normal else
                ("Mann-Whitney U", "مان-ويتني", "normality not met", "التوزيع غير طبيعي"))
    resid = np.concatenate([g - g.mean() for g in groups])
    normal = _normal(resid)[0]
    lev = stats.levene(*groups, center="median")[1] if small >= 2 else 1.0
    if normal:
        ph = "Tukey" if lev >= 0.05 else "Games-Howell"
        why_en = f"ANOVA residuals normal; variances {'equal' if lev >= 0.05 else 'unequal'} (Levene p {_pe(lev)})"
        why_ar = f"البواقي طبيعية؛ التباين {'متجانس' if lev >= 0.05 else 'غير متجانس'} (ليفين p {_pe(lev)})"
        return f"One-way ANOVA + {ph}", f"تحليل التباين الأحادي + {ph}", why_en, why_ar
    return "Kruskal-Wallis + Dunn", "كروسكال-واليس + دن", "residuals not normal", "البواقي غير طبيعية"


def recommend(df: pd.DataFrame, max_items=8):
    """Ranked list of the most suitable analyses for this dataset.

    Each item: dict(en, ar, why_en, why_ar, action) where action is a tuple understood by the UI:
    ("smart", [outcomes], factor) | ("run", analysis_id, kwargs) | ("open", analysis_id, preset)."""
    from .smartimport import guess_roles
    roles = guess_roles(df)
    G, M, B = roles["group"], roles["measure"], roles["binary"]
    out = []
    names = {c.lower(): c for c in map(str, df.columns)}
    time_c = next((names[n] for n in names if any(t in n for t in ("time", "days", "months", "survival", "الزمن", "المدة"))), None)
    event_c = next((names[n] for n in names if any(t in n for t in ("event", "status", "death", "died", "الحدث", "الوفاة"))), None)
    surv = bool(time_c and event_c and time_c != event_c)
    if surv:
        G = [g for g in G if g != event_c]
        M = [m for m in M if m != time_c]
        B = [b for b in B if b != event_c]
        out.append({"en": f"Survival: Kaplan-Meier + log-rank ({time_c}, {event_c})" + (f" by '{G[0]}'" if G else ""),
                    "ar": f"تحليل البقاء: كابلان-ماير ولوج-رانك ({time_c}، {event_c})" + (f" حسب «{G[0]}»" if G else ""),
                    "why_en": "time-to-event and event columns detected", "why_ar": "تم التعرف على عمودي الزمن والحدث",
                    "action": ("open", "km", {"time": time_c, "event": event_c, "group": G[0] if G else None}), "primary": True})
    dose = next((names[n] for n in names if "dose" in n or "جرعة" in n or "conc" in n), None)
    n_c = next((names[n] for n in names if n in ("n", "total", "number", "العدد")), None)
    r_c = next((names[n] for n in names if any(t in n for t in ("dead", "died", "killed", "respon", "mortal", "affected", "نافق", "مستجيب"))), None)
    if dose and n_c and r_c:
        out.append({"en": f"Probit analysis: LD50/ED50 with 95% CI ({r_c}/{n_c} vs {dose})", "ar": f"تحليل بروبيت: LD50/ED50 مع 95% CI ({r_c}/{n_c} مقابل {dose})",
                    "why_en": "dose, number tested and number responding detected", "why_ar": "تم التعرف على الجرعة والعدد والمستجيبين",
                    "action": ("open", "probit", {"dose": dose, "n": n_c, "responders": r_c}), "primary": True})
        M = [m for m in M if m not in (dose, n_c, r_c)]
    if G and M:
        g = G[0]
        levels = _level_order(df[g].dropna())
        plans = []
        for m in M:
            y = numeric(df, m)
            arrs = [y[df[g] == l].dropna().values for l in levels]
            if sum(len(a) >= 2 for a in arrs) >= 2:
                plans.append((m, _plan_group_test([a for a in arrs if len(a) >= 2])))
        if plans:
            tests = sorted({p[1][0] for p in plans})
            out.append({"en": f"Compare all {len(plans)} measurement(s) between the {len(levels)} groups of '{g}'",
                        "ar": f"مقارنة كل القياسات ({len(plans)}) بين مجموعات «{g}» الـ{len(levels)}",
                        "why_en": "; ".join(f"{m}: {p[0]} ({p[2]})" for m, p in plans[:4]) + (" …" if len(plans) > 4 else ""),
                        "why_ar": "؛ ".join(f"{m}: {p[1]} ({p[3]})" for m, p in plans[:4]) + (" …" if len(plans) > 4 else ""),
                        "action": ("smart", [m for m, _ in plans], g), "primary": True})
        out.append({"en": f"Descriptive table (mean ± SD, median, 95% CI) by '{g}'",
                    "ar": f"جدول وصفي (المتوسط ± الانحراف، الوسيط، 95% CI) حسب «{g}»",
                    "why_en": "Table 1 of most papers", "why_ar": "الجدول الأول في أغلب الأبحاث",
                    "action": ("run", "descriptives", {"variables": M, "group": g})})
        if len(G) >= 2 and df[G[1]].nunique() <= 6:
            out.append({"en": f"Two-way ANOVA: {M[0]} by '{G[0]}' × '{G[1]}'",
                        "ar": f"تحليل التباين الثنائي: {M[0]} حسب «{G[0]}» × «{G[1]}»",
                        "why_en": "two grouping factors detected (tests the interaction)", "why_ar": "يوجد عاملان للتقسيم (يختبر التفاعل بينهما)",
                        "action": ("open", "anova2", {"outcome": M[0], "factor_a": G[0], "factor_b": G[1]})})
    if len(M) >= 2:
        out.append({"en": f"Correlation matrix of the {len(M)} measurements", "ar": f"مصفوفة الارتباط بين القياسات ({len(M)})",
                    "why_en": "Pearson or Spearman with p values and heatmap", "why_ar": "بيرسون أو سبيرمان مع قيم p وخريطة حرارية",
                    "action": ("run", "correlation", {"variables": M[:8]})})
    import re as _re
    bin_out = [b for b in B if b not in G[:1] and not _re.search(r"sex|gender|الجنس|النوع", str(b), _re.I)]
    if bin_out and M:
        b = bin_out[0]
        out.append({"en": f"ROC curve: how well each measurement discriminates '{b}'",
                    "ar": f"منحنى ROC: قدرة كل قياس على التمييز في «{b}»",
                    "why_en": "binary outcome + numeric markers", "why_ar": "نتيجة ثنائية مع مؤشرات رقمية",
                    "action": ("open", "roc", {"truth": b, "markers": M[:4]})})
        out.append({"en": f"Logistic regression for '{b}'", "ar": f"انحدار لوجستي لـ «{b}»",
                    "why_en": "odds ratios adjusted for several predictors", "why_ar": "نسب أرجحية معدّلة لعدة متغيرات",
                    "action": ("open", "logreg", {"outcome": b, "predictors": M[:3]})})
    pre = [c for c in M if any(t in str(c).lower() for t in ("pre", "post", "before", "after", "baseline", "day", "week", "قبل", "بعد", "يوم"))]
    if len(pre) >= 2 and not G:
        aid = "ttest_paired" if len(pre) == 2 else "rmanova"
        out.append({"en": f"Repeated measurements: {', '.join(map(str, pre[:4]))}", "ar": f"قياسات متكررة: {'، '.join(map(str, pre[:4]))}",
                    "why_en": "same subjects measured more than once", "why_ar": "نفس الحالات قيست أكثر من مرة",
                    "action": ("open", aid, {"var1": pre[0], "var2": pre[1]} if aid == "ttest_paired" else {"measures": pre})})
    if dose and M and not (n_c and r_c):
        resp = next((m for m in M if m != dose), None)
        if resp:
            out.append({"en": f"Dose-response curve (EC50/IC50): {resp} vs {dose}", "ar": f"منحنى الجرعة والاستجابة (EC50/IC50): {resp} مقابل {dose}",
                        "why_en": "dose column detected", "why_ar": "تم التعرف على عمود الجرعة",
                        "action": ("open", "doseresp", {"dose": dose, "response": resp})})
    if not out and M:
        out.append({"en": "Descriptive statistics and normality", "ar": "إحصاء وصفي واختبار التوزيع الطبيعي",
                    "why_en": "no grouping variable detected", "why_ar": "لم يُعثر على متغير مجموعات",
                    "action": ("run", "descriptives", {"variables": M})})
    return out[:max_items]
