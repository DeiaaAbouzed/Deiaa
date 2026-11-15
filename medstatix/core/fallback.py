"""Automatic assumption checking with a non-parametric fallback.

After a parametric test the same assumption checks are repeated here (Shapiro–Wilk on each group, on the paired
differences, on the pooled ANOVA residuals or on both correlation variables). When normality fails, the matching
rank-based test is chosen and an explanation in English and Arabic is returned, so the user sees both results and
the reason for preferring one of them."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

ALPHA = 0.05


def _sw(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) < 3:
        return np.nan
    return stats.shapiro(x)[1] if len(x) <= 5000 else stats.normaltest(x)[1]


def _groups(df, outcome, group):
    y = pd.to_numeric(df[outcome], errors="coerce")
    d = pd.DataFrame({"y": y, "g": df[group]}).dropna()
    return {str(k): v["y"].to_numpy() for k, v in d.groupby("g", observed=True, sort=False)}


def _fmt(p):
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def suggest(aid, df, kw):
    """Return (fallback_aid, fallback_kwargs, explanation_en, explanation_ar) or None when assumptions hold."""
    try:
        if aid == "ttest_ind":
            g = _groups(df, kw["outcome"], kw["group"])
            bad = [(k, p) for k, v in g.items() if not np.isnan(p := _sw(v)) and p < ALPHA]
            if not bad:
                return None
            k, p = min(bad, key=lambda t: t[1])
            why = f"Shapiro–Wilk rejected normality in group “{k}” ({_fmt(p)})"
            return ("mannwhitney", {"outcome": kw["outcome"], "group": kw["group"], "alternative": kw.get("alternative", "two-sided")},
                    f"{why}, so the t-test assumption is not met. The Mann–Whitney U test, which compares ranks and does not "
                    f"assume normality, was added automatically and is the preferred result to report.",
                    f"اختبار شابيرو-ويلك رفض التوزيع الطبيعي في المجموعة «{k}» ({_fmt(p)})، فافتراض اختبار t غير متحقق. "
                    f"أُضيف اختبار مان-ويتني (يعتمد على الرتب ولا يفترض التوزيع الطبيعي) تلقائياً، وهو النتيجة المفضّل نشرها.")
        if aid == "ttest_paired":
            d = pd.DataFrame({"a": pd.to_numeric(df[kw["var1"]], errors="coerce"),
                              "b": pd.to_numeric(df[kw["var2"]], errors="coerce")}).dropna()
            p = _sw(d.a - d.b)
            if np.isnan(p) or p >= ALPHA:
                return None
            return ("wilcoxon", {"var1": kw["var1"], "var2": kw["var2"], "alternative": kw.get("alternative", "two-sided")},
                    f"The paired differences are not normally distributed (Shapiro–Wilk {_fmt(p)}), so the Wilcoxon signed-rank "
                    f"test was added automatically and is the preferred result to report.",
                    f"الفروق بين القياسين لا تتبع التوزيع الطبيعي (شابيرو-ويلك {_fmt(p)})، لذلك أُضيف اختبار ويلكوكسون للرتب "
                    f"المزدوجة تلقائياً، وهو النتيجة المفضّل نشرها.")
        if aid == "anova1":
            g = _groups(df, kw["outcome"], kw["group"])
            resid = np.concatenate([v - v.mean() for v in g.values() if len(v)])
            p = _sw(resid)
            if np.isnan(p) or p >= ALPHA:
                return None
            return ("kruskal", {"outcome": kw["outcome"], "group": kw["group"]},
                    f"The ANOVA residuals are not normally distributed (Shapiro–Wilk {_fmt(p)}), so the Kruskal–Wallis test with "
                    f"Dunn's post hoc comparisons was added automatically and is the preferred result to report.",
                    f"البواقي في تحليل التباين لا تتبع التوزيع الطبيعي (شابيرو-ويلك {_fmt(p)})، لذلك أُضيف اختبار كروسكال-واليس "
                    f"مع مقارنات دن البعدية تلقائياً، وهو النتيجة المفضّل نشرها.")
        if aid == "correlation" and kw.get("method", "Pearson") == "Pearson":
            bad = [(v, p) for v in kw["variables"] if not np.isnan(p := _sw(pd.to_numeric(df[v], errors="coerce"))) and p < ALPHA]
            if not bad:
                return None
            v, p = min(bad, key=lambda t: t[1])
            kw2 = dict(kw); kw2["method"] = "Spearman"
            return ("correlation", kw2,
                    f"“{v}” is not normally distributed (Shapiro–Wilk {_fmt(p)}), so Spearman's rank correlation was added "
                    f"automatically and is the preferred result to report.",
                    f"المتغير «{v}» لا يتبع التوزيع الطبيعي (شابيرو-ويلك {_fmt(p)})، لذلك أُضيف معامل ارتباط سبيرمان للرتب "
                    f"تلقائياً، وهو النتيجة المفضّل نشرها.")
    except (KeyError, ValueError, TypeError):
        return None
    return None


def run_with_fallback(aid, df, kw, run):
    """Run the requested analysis; if assumptions fail, also run the non-parametric test. Returns a list of Results."""
    res = run(aid, df, **kw)
    out = [res]
    s = suggest(aid, df, kw)
    if s:
        aid2, kw2, en, ar = s
        try:
            res2 = run(aid2, df, **kw2)
        except Exception:
            return out
        from .result import Block
        from .settings import SETTINGS
        res.warning(("فحص الافتراضات: " + ar) if SETTINGS.language == "ar" else ("Assumption check: " + en))
        res2.blocks.insert(0, Block("interpret", {"en": "Automatic fallback. " + en, "ar": "بديل تلقائي. " + ar}))
        res2.subtitle = (res2.subtitle + " · " if res2.subtitle else "") + "automatic non-parametric fallback"
        out.append(res2)
    return out
