"""Chart library: heatmap (group means or correlations, optional clustering), volcano plot, radar chart, custom forest
plot and Kaplan–Meier, in the journal palette chosen in Settings."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

from ..core.data import _level_order, numeric
from ..core.result import AnalysisError, Result
from ..plots import figures as F
from .common import p_adjust
from .registry import P, P_ADJ, register


def _cmap():
    from matplotlib.colors import LinearSegmentedColormap
    pal = F.palette(2)
    return LinearSegmentedColormap.from_list("mx", [pal[0], "#FFFFFF", pal[1]])


@register("heatmap", "charts", "Heatmap (group means or correlations, with clustering)", "خريطة حرارية (متوسطات المجموعات أو الارتباطات مع التجميع)",
          [P("variables", "Variables (markers)", "المتغيرات (المؤشرات)", "vars_num"),
           P("group", "Groups (for a group-means heatmap)", "المجموعات (لخريطة المتوسطات)", "var_cat", optional=True),
           P("kind", "Content", "المحتوى", "choice", ["Group means (z-score per marker)", "Correlation matrix (Spearman)",
                                                         "Correlation matrix (Pearson)"], "Group means (z-score per marker)"),
           P("cluster", "Cluster rows", "تجميع الصفوف (cluster)", "bool", default=True)],
          "Marker panel overview: which groups move which markers, or how markers correlate.",
          "نظرة شاملة على لوحة المؤشرات: أي المجموعات تغيّر أي المؤشرات، أو كيف ترتبط المؤشرات.")
def heatmap(df, variables, group=None, kind="Group means (z-score per marker)", cluster=True):
    if len(variables) < 2:
        raise AnalysisError("Choose at least 2 variables.")
    X = df[variables].apply(pd.to_numeric, errors="coerce")
    res = Result("Heatmap", kind)
    if kind.startswith("Group"):
        if not group:
            raise AnalysisError("Choose the grouping variable for a group-means heatmap.")
        lv = _level_order(df[group].dropna())
        M = pd.DataFrame({str(l): X[df[group] == l].mean() for l in lv})
        Z = M.sub(M.mean(1), axis=0).div(M.std(1, ddof=0).replace(0, 1), axis=0)
        vmin, vmax, lab = -2, 2, "z-score of group mean"
        annot = M
    else:
        meth = "spearman" if "Spearman" in kind else "pearson"
        Z = X.corr(method=meth); annot = Z; vmin, vmax, lab = -1, 1, f"{meth.title()} r"
    order = list(Z.index)
    if cluster and len(Z) > 2:
        from scipy.cluster.hierarchy import leaves_list, linkage
        order = [Z.index[i] for i in leaves_list(linkage(Z.fillna(0).values, "average"))]
        Z = Z.loc[order]; annot = annot.loc[order]
        if not kind.startswith("Group"):
            Z = Z[order]; annot = annot[order]
    with F.styled():
        h = max(60, 9 * len(Z) + 25)
        fig, ax = F.new_figure(h_mm=min(h, 230))
        im = ax.imshow(Z.values, cmap=_cmap(), vmin=vmin, vmax=vmax, aspect="auto")
        ax.set_xticks(range(Z.shape[1])); ax.set_xticklabels(Z.columns, rotation=45, ha="right")
        ax.set_yticks(range(Z.shape[0])); ax.set_yticklabels(Z.index)
        if Z.size <= 120:
            for i in range(Z.shape[0]):
                for j in range(Z.shape[1]):
                    v = annot.values[i, j]
                    ax.text(j, i, f"{v:.2f}" if abs(v) < 100 else f"{v:.0f}", ha="center", va="center", fontsize=6.5)
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04); cb.set_label(lab)
        for s in ax.spines.values():
            s.set_visible(False)
        fig.tight_layout()
    res.figure(fig, f"Heatmap of {lab}" + (" (rows clustered, average linkage)." if cluster else "."))
    res.table(annot.reset_index().rename(columns={"index": "Marker"}), "Values shown in the heatmap", p_columns=())
    return res


@register("volcano", "charts", "Volcano plot (many markers, two groups)", "رسم البركان Volcano (مؤشرات كثيرة، مجموعتان)",
          [P("variables", "Markers", "المؤشرات", "vars_num"),
           P("group", "Groups", "المجموعات", "var_cat"),
           P("reference", "Reference group (control)", "المجموعة المرجعية (الضابطة)", "text", default=""),
           P("comparison", "Compared group (empty = all other groups)", "المجموعة المقارنة (فارغ = باقي المجموعات)", "text", default=""),
           P("test", "Test", "الاختبار", "choice", ["Welch t-test", "Mann-Whitney"], "Welch t-test"),
           P("adjust", "Multiple-testing correction", "تصحيح الاختبارات المتعددة", "choice", P_ADJ, "Benjamini-Hochberg (FDR)"),
           P("fc", "Fold-change threshold (×)", "حد التغير (مرات)", "float", default=1.5)],
          "log2 fold change against −log10 adjusted p for every marker; markers beyond both thresholds are labelled.",
          "التغير log2 مقابل −log10 للقيمة الاحتمالية المعدلة لكل مؤشر، مع تسمية المؤشرات المهمة.")
def volcano(df, variables, group, reference="", comparison="", test="Welch t-test", adjust="Benjamini-Hochberg (FDR)", fc=1.5):
    lv = [str(l) for l in _level_order(df[group].dropna())]
    if len(lv) < 2:
        raise AnalysisError("At least 2 groups are needed.")
    ref = reference if reference in lv else lv[0]
    comp = comparison if comparison in lv and comparison != ref else (next(l for l in lv if l != ref) if len(lv) == 2 else None)
    rows = []
    g = df[group].astype(str)
    for v in variables:
        y = numeric(df, v)
        a, b = y[g == ref].dropna().values, (y[g == comp] if comp else y[g != ref]).dropna().values
        if len(a) < 2 or len(b) < 2 or a.mean() <= 0 or b.mean() <= 0:
            continue
        p = stats.ttest_ind(b, a, equal_var=False).pvalue if test.startswith("Welch") else stats.mannwhitneyu(b, a).pvalue
        rows.append({"Marker": v, "Mean ref": a.mean(), "Mean comp": b.mean(), "Fold change": b.mean() / a.mean(),
                     "log2 FC": math.log2(b.mean() / a.mean()), "p": p})
    if not rows:
        raise AnalysisError("No marker could be compared (needs positive means and ≥ 2 values per group).")
    T = pd.DataFrame(rows)
    T["p adj."] = p_adjust(T.p.values, adjust)
    T["−log10 p adj."] = -np.log10(T["p adj."].clip(lower=1e-300))
    thr = math.log2(fc)
    T["Regulation"] = np.where((T["p adj."] < 0.05) & (T["log2 FC"] >= thr), "Up",
                               np.where((T["p adj."] < 0.05) & (T["log2 FC"] <= -thr), "Down", "n.s."))
    with F.styled():
        fig, ax = F.new_figure()
        pal = F.palette(2)
        col = T.Regulation.map({"Up": pal[1], "Down": pal[0], "n.s.": "#B0B0B0"})
        ax.scatter(T["log2 FC"], T["−log10 p adj."], c=col, s=26, edgecolor="black", linewidth=0.3, zorder=3)
        ax.axhline(-math.log10(0.05), color="#777", ls="--", lw=0.8)
        for x in (thr, -thr):
            ax.axvline(x, color="#777", ls="--", lw=0.8)
        for _, r in T[T.Regulation != "n.s."].nlargest(15, "−log10 p adj.").iterrows():
            ax.annotate(r.Marker, (r["log2 FC"], r["−log10 p adj."]), fontsize=7, xytext=(3, 3), textcoords="offset points")
        ax.set_xlabel(f"log2 fold change ({comp or 'others'} / {ref})"); ax.set_ylabel("−log10 adjusted p")
        fig.tight_layout()
    res = Result("Volcano plot", f"{comp or 'all other groups'} vs {ref}")
    res.figure(fig, f"Volcano plot: dashed lines mark adjusted p = 0.05 and a {fc:g}-fold change.")
    res.table(T.sort_values("p"), "Fold changes and tests", p_columns=("p", "p adj."))
    up, dn = (T.Regulation == "Up").sum(), (T.Regulation == "Down").sum()
    res.interpret(f"{up} marker(s) increased and {dn} decreased significantly (≥ {fc:g}-fold, adjusted p < 0.05) versus {ref}.",
                  f"{up} مؤشر ارتفع و{dn} انخفض بشكل دال (≥ {fc:g} مرة، p معدلة < 0.05) مقارنة بـ {ref}.")
    return res


@register("radar", "charts", "Radar (spider) chart of group profiles", "رسم الرادار لملامح المجموعات",
          [P("variables", "Markers (3 or more)", "المؤشرات (3 أو أكثر)", "vars_num"),
           P("group", "Groups", "المجموعات", "var_cat"),
           P("scale", "Scaling", "المقياس", "choice", ["% of the first (control) group", "Min–max across groups (0–1)"],
             "% of the first (control) group")],
          "Each group's profile across markers on one chart.", "ملف كل مجموعة عبر المؤشرات في رسم واحد.")
def radar(df, variables, group, scale="% of the first (control) group"):
    if len(variables) < 3:
        raise AnalysisError("Choose at least 3 markers.")
    lv = _level_order(df[group].dropna())
    M = pd.DataFrame({str(l): df.loc[df[group] == l, variables].apply(pd.to_numeric, errors="coerce").mean() for l in lv})
    if scale.startswith("%"):
        S = M.div(M.iloc[:, 0].replace(0, np.nan), axis=0) * 100; lab = f"% of {M.columns[0]}"
    else:
        S = M.sub(M.min(1), axis=0).div((M.max(1) - M.min(1)).replace(0, 1), axis=0); lab = "scaled 0–1"
    ang = np.linspace(0, 2 * np.pi, len(variables), endpoint=False).tolist()
    with F.styled():
        from matplotlib.figure import Figure
        fig = Figure(figsize=(F.SETTINGS.fig_width_mm * F.MM, F.SETTINGS.fig_width_mm * F.MM))
        ax = fig.add_subplot(111, polar=True)
        for i, (gname, col) in enumerate(zip(S.columns, F.palette(len(S.columns)))):
            v = S[gname].tolist()
            ax.plot(ang + ang[:1], v + v[:1], color=col, lw=1.8, label=gname)
            ax.fill(ang + ang[:1], v + v[:1], color=col, alpha=0.12)
        ax.set_xticks(ang); ax.set_xticklabels(variables, fontsize=7)
        ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), frameon=False, fontsize=7)
        fig.tight_layout()
    res = Result("Radar chart", f"Group profiles ({lab})")
    res.figure(fig, f"Radar chart of group means ({lab}).")
    res.table(S.reset_index().rename(columns={"index": "Marker"}), f"Plotted values ({lab})", p_columns=())
    return res


@register("forest_custom", "charts", "Forest plot from your own estimates", "رسم Forest من تقديراتك",
          [P("label", "Label column", "عمود الأسماء", "var_any"), P("estimate", "Estimate", "التقدير", "var_num"),
           P("lower", "Lower 95% CI", "الحد الأدنى 95%", "var_num"), P("upper", "Upper 95% CI", "الحد الأعلى 95%", "var_num"),
           P("log_scale", "Ratio measure (OR / RR / HR, log scale)", "مقياس نسبة (OR / RR / HR، مقياس لوغاريتمي)", "bool", default=True)],
          "Draw a forest plot from a table of estimates and confidence limits (e.g. odds ratios from several models).",
          "رسم Forest من جدول تقديرات وحدود ثقة (مثل نسب الأرجحية من عدة نماذج).")
def forest_custom(df, label, estimate, lower, upper, log_scale=True):
    d = df[[label, estimate, lower, upper]].dropna()
    e, lo, hi = (d[c].astype(float).values for c in (estimate, lower, upper))
    if log_scale:
        if (np.r_[e, lo, hi] <= 0).any():
            raise AnalysisError("Ratio measures must be positive (untick 'ratio measure' for differences).")
        e, lo, hi = np.log(e), np.log(lo), np.log(hi)
    fig = F.forest_plot(d[label].astype(str).tolist(), e, lo, hi, xlabel="Estimate (95% CI)", log_scale=log_scale)
    res = Result("Forest plot", f"{len(d)} estimates")
    res.figure(fig, "Forest plot of the estimates with 95% confidence intervals.")
    return res


def _km_alias(df, time, event, group=None):
    from .survival import km
    return km(df, time, event, group)


register("km_chart", "charts", "Kaplan–Meier curves", "منحنيات كابلان-ماير",
         [P("time", "Time", "الزمن", "var_num"), P("event", "Event (1 = event)", "الحدث (1 = حدث)", "var_num"),
          P("group", "Groups", "المجموعات", "var_cat", optional=True)],
         "Survival curves with the number at risk (same as Survival → Kaplan–Meier).",
         "منحنيات البقاء مع عدد المعرضين للخطر.")(_km_alias)
