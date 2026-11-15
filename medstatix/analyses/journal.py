"""Journal summary table: several markers × groups in one publication-ready table.

The classic table of pharmacology / toxicology papers: one row per group, one column per marker, each cell
mean ± SD (or median (IQR) when the marker is not normally distributed), with * versus the control group and # versus
the disease-model group. Each marker is tested with the procedure the smart advisor would choose:
one-way ANOVA + Tukey (equal variances), Welch's ANOVA + Games-Howell (unequal variances) or Kruskal-Wallis + Dunn
(non-normal residuals)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

from ..core.data import group_arrays, _level_order
from ..core.result import Result, AnalysisError, fmt_p
from ..plots.figures import is_control
from ..plots.groupfig import GroupFigSpec, render_panels
from .common import pstr
from .registry import register, P


def _decimals(sd):
    if not np.isfinite(sd) or sd <= 0:
        return 2
    return int(np.clip(1 - math.floor(math.log10(sd)), 0, 4))


def _symbols(p, sym):
    if p is None or not np.isfinite(p) or p >= 0.05:
        return ""
    return sym * (4 if p < 0.0001 else 3 if p < 0.001 else 2 if p < 0.01 else 1)


def _choose(g):
    arrs = list(g.values())
    lev_p = stats.levene(*arrs, center="median")[1] if len(arrs) >= 2 else 1.0
    hetero = lev_p < 0.05
    resid = np.concatenate([(a - a.mean()) / (a.std(ddof=1) if hetero and a.std(ddof=1) > 0 else 1) for a in arrs])
    normal = len(resid) < 3 or (stats.shapiro(resid)[1] >= 0.05 if len(resid) <= 5000 else stats.normaltest(resid)[1] >= 0.05)
    if not normal:
        return "Kruskal-Wallis", "Dunn (Holm)"
    return ("Welch's ANOVA", "Games-Howell") if hetero else ("one-way ANOVA", "Tukey HSD")


def _pairwise(g, test, post):
    from .compare import posthoc_table, dunn_test
    labels = list(g)
    if test == "Kruskal-Wallis":
        tab, _ = dunn_test(g, "Holm")
        omni = stats.kruskal(*g.values())
        stat = f"H({len(g) - 1}) = {omni.statistic:.2f}"
        p_all = omni.pvalue
    else:
        arrs = list(g.values())
        if test == "Welch's ANOVA":
            k = len(arrs)
            w = np.array([len(a) / a.var(ddof=1) for a in arrs]); m = np.array([a.mean() for a in arrs])
            mw = (w * m).sum() / w.sum()
            lam = ((1 - w / w.sum()) ** 2 / np.array([len(a) - 1 for a in arrs])).sum()
            Fw = ((w * (m - mw) ** 2).sum() / (k - 1)) / (1 + 2 * (k - 2) / (k ** 2 - 1) * lam)
            df2 = (k ** 2 - 1) / (3 * lam)
            p_all = stats.f.sf(Fw, k - 1, df2); stat = f"F({k - 1}, {df2:.1f}) = {Fw:.2f}"
        else:
            r = stats.f_oneway(*arrs); p_all = r.pvalue
            N = sum(len(a) for a in arrs)
            stat = f"F({len(arrs) - 1}, {N - len(arrs)}) = {r.statistic:.2f}"
        N = sum(len(a) for a in arrs); k = len(arrs)
        msw = sum(((a - a.mean()) ** 2).sum() for a in arrs) / (N - k)
        tab, _ = posthoc_table(g, post, msw, N - k)
    pairs = {}
    for _, r in tab.iterrows():
        pairs[(str(r["Group A"]), str(r["Group B"]))] = pairs[(str(r["Group B"]), str(r["Group A"]))] = float(r["p (adj.)"])
    return pairs, p_all, stat


@register("journal_table", "describe", "Journal summary table (markers × groups)", "جدول النشر الملخص (المؤشرات × المجموعات)",
          [P("variables", "Markers", "المؤشرات", "vars_num"),
           P("group", "Groups", "المجموعات", "var_cat"),
           P("control", "Control group (* versus; empty = automatic)", "المجموعة الضابطة (* مقارنة بها؛ فارغ = تلقائي)", "text", default=""),
           P("model", "Disease-model group (# versus; empty = automatic)", "مجموعة النموذج المرضي (# مقارنة بها؛ فارغ = تلقائي)", "text", default=""),
           P("dispersion", "Show", "العرض", "choice", ["Mean ± SD", "Mean ± SEM"], "Mean ± SD")],
          "One publication-ready table: mean ± SD per group and marker with * vs control and # vs the disease model, "
          "each marker tested with the appropriate ANOVA or Kruskal-Wallis procedure.",
          "جدول واحد جاهز للنشر: المتوسط ± الانحراف لكل مجموعة ومؤشر مع * مقارنة بالضابطة و# مقارنة بالنموذج المرضي، "
          "وكل مؤشر يُختبر بالطريقة المناسبة (ANOVA أو كروسكال-واليس).")
def journal_table(df, variables, group, control="", model="", dispersion="Mean ± SD"):
    variables = [v for v in (variables or []) if v != group]
    if not variables:
        raise AnalysisError("Choose at least one marker.", "اختر مؤشرًا واحدًا على الأقل.")
    levels = [str(l) for l in _level_order(df[group].dropna())]
    if len(levels) < 2:
        raise AnalysisError("At least 2 groups are needed.", "يلزم وجود مجموعتين على الأقل.")
    d = df.copy(); d[group] = d[group].astype(str)
    ctrl = control if control in levels else next((l for l in levels if is_control(l)), levels[0])
    sem = dispersion.endswith("SEM")
    cells = {l: {} for l in levels}
    footer = {}
    notes = []
    models = {}
    for v in variables:
        g = {str(k): a for k, a in group_arrays(d, v, group).items()}
        if model in g:
            models[v] = model
        else:   # the group furthest from control, in control SD units
            c = g.get(ctrl)
            sd = c.std(ddof=1) if c is not None and len(c) > 1 and c.std(ddof=1) > 0 else 1
            others = [l for l in g if l != ctrl and not is_control(l)] or [l for l in g if l != ctrl]
            models[v] = max(others, key=lambda l: abs(np.median(g[l]) - (np.median(c) if c is not None else 0)) / sd) if others else ""
    # one model group for the whole table: the one chosen most often
    mdl = model if model in levels else (pd.Series(list(models.values())).mode().iloc[0] if models else "")
    if mdl == ctrl:
        mdl = ""
    for v in variables:
        g = {str(k): a for k, a in group_arrays(d, v, group).items()}
        if len(g) < 2:
            continue
        test, post = _choose(g)
        pairs, p_all, stat = _pairwise(g, test, post)
        npar = test == "Kruskal-Wallis"
        allsd = np.nanmedian([a.std(ddof=1) for a in g.values() if len(a) > 1]) if any(len(a) > 1 for a in g.values()) else np.nan
        if npar:
            iq = np.nanmedian([np.subtract(*np.percentile(a, [75, 25])) for a in g.values() if len(a)])
            dec = _decimals(iq / 1.35 if iq > 0 else allsd)
        else:
            dec = _decimals(allsd)
        for l in levels:
            a = g.get(l)
            if a is None or not len(a):
                cells[l][v] = "—"; continue
            if npar:
                q1, med, q3 = np.percentile(a, [25, 50, 75])
                txt = f"{med:.{dec}f} ({q1:.{dec}f}–{q3:.{dec}f})"
            else:
                e = a.std(ddof=1) / (math.sqrt(len(a)) if sem else 1) if len(a) > 1 else 0.0
                txt = f"{a.mean():.{dec}f} ± {e:.{dec}f}"
            if l != ctrl:
                txt += _symbols(pairs.get((l, ctrl)), "*")
            if mdl and l not in (ctrl, mdl):
                txt += _symbols(pairs.get((l, mdl)), "#")
            cells[l][v] = txt
        footer[v] = (test, post, stat, p_all, npar)
    cols = [v for v in variables if v in footer]
    rows = []
    for l in levels:
        n = sorted({int(np.sum(d[group] == l) - d.loc[d[group] == l, v].isna().sum()) for v in cols})
        rows.append({"Group": l, "n": n[0] if len(n) == 1 else f"{n[0]}–{n[-1]}", **{v: cells[l][v] for v in cols}})
    rows.append({"Group": "Overall p", "n": "", **{v: fmt_p(footer[v][3]) for v in cols}})
    tab = pd.DataFrame(rows)
    disp = "mean ± SEM" if sem else "mean ± SD"
    tests = {}
    for v in cols:
        test, post, stat, p_all, npar = footer[v]
        tests.setdefault(f"{test} followed by {post}", []).append(v)
    used_np = any(footer[v][4] for v in cols)
    note = (f"Values are {disp}" + ("; markers that were not normally distributed are median (interquartile range)" if used_np else "")
            + ". " + " ".join(f"{k}: {', '.join(vs)}." for k, vs in tests.items())
            + f" *p < 0.05, **p < 0.01, ***p < 0.001, ****p < 0.0001 versus {ctrl}"
            + (f"; #p < 0.05, ##p < 0.01, ###p < 0.001, ####p < 0.0001 versus {mdl}." if mdl else "."))
    res = Result("Journal summary table", f"{len(cols)} markers by {group} ({len(levels)} groups)")
    specs = []
    for v in cols:
        g = {str(k): a for k, a in group_arrays(d, v, group).items()}
        test, post, stat, p_all, npar = footer[v]
        pairs_v = _pairwise(g, test, post)[0]
        comps = [(a, b, p) for (a, b), p in pairs_v.items() if a < b]
        specs.append(GroupFigSpec(groups=g, ylabel=v, comparisons=comps, center="median" if npar else "mean",
                                  plot_type="Box + points" if npar else "Bar + points", error_bar="SEM" if sem else "SD",
                                  sig_mode="Versus reference group", sig_layout="Symbols above groups", ref1=ctrl, ref2=mdl or "",
                                  test_name=f"{test} followed by {post}"))
    res.table(tab, f"Effect of the treatments on {', '.join(cols)}" if len(cols) <= 4 else "Summary of all markers", note, p_columns=())
    detail = pd.DataFrame([{"Marker": v, "Test": footer[v][0], "Post hoc": footer[v][1], "Statistic": footer[v][2],
                            "p": footer[v][3]} for v in cols])
    res.table(detail, "Tests used for each marker", p_columns=("p",))
    en = [f"Control group: {ctrl}" + (f"; disease-model group: {mdl}" if mdl else "") + "."]
    ar = [f"المجموعة الضابطة: {ctrl}" + (f"؛ مجموعة النموذج المرضي: {mdl}" if mdl else "") + "."]
    for v in cols:
        test, post, stat, p_all, npar = footer[v]
        en.append(f"{v}: {test} ({stat}, {pstr(p_all)}) followed by {post}.")
        ar.append(f"{v}: {test} ({stat}، {pstr(p_all)}) ثم {post}.")
    en.append("Change the control or model group, or show SEM instead of SD, in the analysis options.")
    ar.append("يمكن تغيير المجموعة الضابطة أو مجموعة النموذج، أو عرض الخطأ المعياري بدل الانحراف، من خيارات التحليل.")
    res.interpret("\n".join(en), "\n".join(ar))
    res.methods(f"Data are presented as {disp} (n = {rows[0]['n']} per group). For each marker, normality of the residuals "
                f"(Shapiro-Wilk) and homogeneity of variance (Levene) were checked; groups were compared by one-way ANOVA with "
                f"Tukey's test, by Welch's ANOVA with the Games-Howell test when variances differed, or by the Kruskal-Wallis test "
                f"with Dunn's test (Holm correction) when residuals were not normally distributed. P < 0.05 was considered significant.")
    if specs:
        fig = render_panels(specs)
        letters = "; ".join(f"({chr(65 + i)}) {v}" for i, v in enumerate(cols))
        pb = ", ".join(chr(65 + i) for i, v in enumerate(cols) if not footer[v][4])
        pn = ", ".join(chr(65 + i) for i, v in enumerate(cols) if footer[v][4])
        bars = f"bars show the mean ± {'SEM' if sem else 'SD'}" + (f" ({pb})" if pn else "") if pb else ""
        boxes = "boxes show the median and interquartile range, whiskers 1.5 × IQR" + (f" ({pn})" if pb else "") if pn else ""
        desc = "; ".join(x for x in (bars, boxes) if x)
        res.figure(fig, f"{letters} in the {len(levels)} groups. " + desc[:1].upper() + desc[1:]
                   + f"; dots are individual animals (n = {rows[0]['n']} per group). " + " ".join(f"{k}: {', '.join(vs)}." for k, vs in tests.items())
                   + f" *p < 0.05, **p < 0.01, ***p < 0.001, ****p < 0.0001 versus {ctrl}" + (f"; #p < 0.05, ##p < 0.01, ###p < 0.001, ####p < 0.0001 versus {mdl}." if mdl else "."))
    return res
