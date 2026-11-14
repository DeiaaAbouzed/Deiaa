"""Publication-quality figures (GraphPad Prism-like by default).

All functions return a ``matplotlib.figure.Figure`` built without pyplot so
they are safe inside the Qt application and in headless tests.
"""
from __future__ import annotations

import contextlib
import math

import matplotlib
matplotlib.use("Agg", force=False)
import matplotlib as mpl
import numpy as np
from matplotlib.figure import Figure
from scipy import stats

from ..core.settings import SETTINGS
from ..core.result import stars

MM = 1 / 25.4

PALETTES = {
    "Prism": ["#1F4E9A", "#C0392B", "#2E8B57", "#E08E0B", "#7D3C98", "#17A2B8", "#5D6D7E", "#D35400"],
    "Okabe-Ito": ["#0072B2", "#D55E00", "#009E73", "#E69F00", "#CC79A7", "#56B4E9", "#F0E442", "#000000"],
    "Grayscale": ["#000000", "#7F7F7F", "#BFBFBF", "#404040", "#A6A6A6", "#D9D9D9", "#262626", "#595959"],
    "Nature (NPG)": ["#E64B35", "#4DBBD5", "#00A087", "#3C5488", "#F39B7F", "#8491B4", "#91D1C2", "#DC0000"],
    "Science (AAAS)": ["#3B4992", "#EE0000", "#008B45", "#631879", "#008280", "#BB0021", "#5F559B", "#A20056"],
    "NEJM": ["#BC3C29", "#0072B5", "#E18727", "#20854E", "#7876B1", "#6F99AD", "#FFDC91", "#EE4C97"],
    "Lancet": ["#00468B", "#ED0000", "#42B540", "#0099B4", "#925E9F", "#FDAF91", "#AD002A", "#ADB6B6"],
    "JAMA": ["#374E55", "#DF8F44", "#00A1D5", "#B24745", "#79AF97", "#6A6599", "#80796B", "#000000"],
    "JCO": ["#0073C2", "#EFC000", "#868686", "#CD534C", "#7AA6DC", "#003C67", "#8F7700", "#3B3B3B"],
    "BMJ": ["#2A6EBB", "#F0AB00", "#C50084", "#7D5CC6", "#E37222", "#69BE28", "#00B2A9", "#CD202C"],
    "Cell": ["#1B9E77", "#D95F02", "#7570B3", "#E7298A", "#66A61E", "#E6AB02", "#A6761D", "#666666"],
    "Viridis (CB-safe)": ["#440154", "#46327E", "#365C8D", "#277F8E", "#1FA187", "#4AC16D", "#A0DA39", "#FDE725"],
    "Pastel": ["#8DA0CB", "#FC8D62", "#66C2A5", "#E78AC3", "#A6D854", "#FFD92F", "#E5C494", "#B3B3B3"],
}

FIG_STYLES = ["Prism", "Classic", "Nature", "ggplot", "Minimal"]
GROUP_PLOT_TYPES = ["Scatter + mean ± SD", "Bar + points", "Box + points", "Violin + points", "Bar (no points)"]


def palette(n=8):
    cols = PALETTES.get(SETTINGS.palette, PALETTES["Prism"])
    return [cols[i % len(cols)] for i in range(n)]


def style_rc():
    s = SETTINGS
    base = {
        "font.family": "sans-serif",
        "font.sans-serif": [s.font_family, "Arial", "Helvetica", "DejaVu Sans"],
        "font.size": s.font_size,
        "axes.titlesize": s.font_size + 1,
        "axes.labelsize": s.font_size + 0.5,
        "axes.labelweight": "bold",
        "axes.titleweight": "bold",
        "xtick.labelsize": s.font_size,
        "ytick.labelsize": s.font_size,
        "legend.fontsize": s.font_size - 1,
        "legend.frameon": False,
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 1.5,
        "xtick.major.width": 1.5,
        "ytick.major.width": 1.5,
        "xtick.major.size": 6,
        "ytick.major.size": 6,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "lines.linewidth": 1.8,
        "axes.grid": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
    }
    st = s.fig_style
    if st == "Classic":  # SPSS-like boxed
        base.update({"axes.spines.top": True, "axes.spines.right": True, "axes.linewidth": 1.0,
                     "axes.labelweight": "normal", "axes.titleweight": "normal",
                     "xtick.direction": "in", "ytick.direction": "in", "xtick.major.width": 1, "ytick.major.width": 1})
    elif st == "Nature":
        base.update({"axes.linewidth": 0.8, "xtick.major.width": 0.8, "ytick.major.width": 0.8,
                     "xtick.major.size": 3, "ytick.major.size": 3, "axes.labelweight": "normal",
                     "axes.titleweight": "normal", "lines.linewidth": 1.2})
    elif st == "ggplot":
        base.update({"axes.facecolor": "#EBEBEB", "axes.grid": True, "grid.color": "white", "grid.linewidth": 1.0,
                     "axes.spines.left": False, "axes.spines.bottom": False, "axes.linewidth": 0,
                     "xtick.major.size": 3, "ytick.major.size": 3, "axes.labelweight": "normal",
                     "axes.titleweight": "normal", "axes.axisbelow": True})
    elif st == "Minimal":
        base.update({"axes.grid": True, "axes.grid.axis": "y", "grid.color": "#DDDDDD", "grid.linewidth": 0.7,
                     "axes.spines.left": False, "axes.linewidth": 1.0, "ytick.major.size": 0,
                     "axes.labelweight": "normal", "axes.axisbelow": True})
    return base


@contextlib.contextmanager
def styled():
    with mpl.rc_context(style_rc()):
        yield


def new_figure(w_mm=None, h_mm=None, nrows=1, ncols=1, **kw):
    w = (w_mm or SETTINGS.fig_width_mm) * MM
    h = (h_mm or SETTINGS.fig_height_mm) * MM
    fig = Figure(figsize=(w * ncols ** 0.75 if ncols > 1 else w, h * nrows ** 0.8 if nrows > 1 else h))
    axes = fig.subplots(nrows, ncols, **kw)
    return fig, axes


def _err(values, kind=None):
    kind = kind or SETTINGS.error_bar
    v = np.asarray(values, float)
    n = len(v)
    if n < 2:
        return 0.0
    sd = np.std(v, ddof=1)
    if kind == "SEM":
        return sd / math.sqrt(n)
    if kind == "95% CI":
        return stats.t.ppf(0.975, n - 1) * sd / math.sqrt(n)
    return sd


def _jitter(n, width=0.18, seed=1):
    rng = np.random.default_rng(seed)
    if n <= 1:
        return np.zeros(n)
    return rng.uniform(-width, width, n)


def add_bracket(ax, x1, x2, y, h, text, lw=1.3, fs=None):
    ax.plot([x1, x1, x2, x2], [y, y + h, y + h, y], lw=lw, c="black", clip_on=False)
    ax.text((x1 + x2) / 2, y + h, text, ha="center", va="bottom", fontsize=fs or SETTINGS.font_size)


# ----------------------------------------------------------------------------
# Group comparison plot (t-test, ANOVA, Mann-Whitney, Kruskal...)
# ----------------------------------------------------------------------------
def group_plot(groups: dict, ylabel="", xlabel="", title="", comparisons=None, plot_type=None,
               paired=False, center="mean"):
    """groups: {label: array}. comparisons: list of (label_i, label_j, p)."""
    plot_type = plot_type or SETTINGS.group_plot
    labels = list(groups)
    cols = palette(len(labels))
    with styled():
        fig, ax = new_figure()
        xs = np.arange(len(labels))
        all_max = max(np.nanmax(np.asarray(groups[k], float)) for k in labels)
        all_min = min(np.nanmin(np.asarray(groups[k], float)) for k in labels)
        show_points = "no points" not in plot_type
        for i, k in enumerate(labels):
            v = np.asarray(groups[k], float)
            v = v[~np.isnan(v)]
            c = cols[i]
            m = np.median(v) if center == "median" else v.mean()
            e = _err(v)
            if plot_type.startswith("Bar"):
                ax.bar(i, m, width=0.6, color=c, alpha=0.35 if show_points else 0.85, edgecolor=c, linewidth=1.6, zorder=1)
                ax.errorbar(i, m, yerr=[[0], [e]] if not show_points else e, fmt="none", ecolor="black", capsize=6,
                            elinewidth=1.5, capthick=1.5, zorder=3)
            elif plot_type.startswith("Box"):
                bp = ax.boxplot(v, positions=[i], widths=0.5, patch_artist=True, showfliers=not show_points,
                                medianprops=dict(color="black", lw=2), whiskerprops=dict(lw=1.4), capprops=dict(lw=1.4),
                                boxprops=dict(lw=1.4))
                bp["boxes"][0].set_facecolor(mpl.colors.to_rgba(c, 0.35))
                bp["boxes"][0].set_edgecolor(c)
            elif plot_type.startswith("Violin") and len(v) > 2:
                vp = ax.violinplot(v, positions=[i], widths=0.7, showextrema=False)
                for b in vp["bodies"]:
                    b.set_facecolor(c); b.set_edgecolor(c); b.set_alpha(0.3)
                q1, med, q3 = np.percentile(v, [25, 50, 75])
                ax.plot([i, i], [q1, q3], c="black", lw=4, solid_capstyle="butt", zorder=3)
                ax.scatter([i], [med], c="white", s=22, zorder=4, edgecolor="black")
            else:  # scatter + mean ± error
                ax.hlines(m, i - 0.25, i + 0.25, color="black", lw=2.2, zorder=4)
                ax.errorbar(i, m, yerr=e, fmt="none", ecolor="black", capsize=7, elinewidth=1.6, capthick=1.6, zorder=4)
            if show_points:
                ax.scatter(i + _jitter(len(v), seed=i + 3), v, s=28, color=c, edgecolor="black" if plot_type.startswith("Scatter") else "white",
                           linewidth=0.6, zorder=3, alpha=0.95)
        if paired and len(labels) >= 2:
            arrs = [np.asarray(groups[k], float) for k in labels]
            for row in zip(*arrs):
                ax.plot(xs, row, color="#888888", lw=0.7, zorder=2, alpha=0.7)
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, rotation=0 if len(labels) < 5 else 35, ha="center" if len(labels) < 5 else "right")
        ax.set_xlim(-0.6, len(labels) - 0.4)
        ax.set_ylabel(ylabel)
        if xlabel:
            ax.set_xlabel(xlabel)
        if title:
            ax.set_title(title)
        rng = (all_max - all_min) or abs(all_max) or 1.0
        if plot_type.startswith("Bar") and all_min >= 0:
            ax.set_ylim(bottom=0)
        if comparisons and SETTINGS.show_significance:
            ymax = all_max + 0.08 * rng
            step = 0.11 * rng
            shown = 0
            for (a, b, p) in comparisons:
                if a not in labels or b not in labels:
                    continue
                ia, ib = labels.index(a), labels.index(b)
                add_bracket(ax, ia, ib, ymax + shown * step, 0.025 * rng, stars(p))
                shown += 1
            ax.set_ylim(top=ymax + (shown + 0.6) * step)
        fig.tight_layout()
    return fig


def qq_plot(values_dict: dict, title="Normal Q–Q plot"):
    labels = list(values_dict)
    n = len(labels)
    ncols = min(n, 3)
    nrows = math.ceil(n / ncols)
    cols = palette(n)
    with styled():
        fig = Figure(figsize=(3.0 * ncols, 2.8 * nrows))
        axs = np.atleast_1d(fig.subplots(nrows, ncols)).ravel()
        for i, k in enumerate(labels):
            v = np.asarray(values_dict[k], float)
            v = v[~np.isnan(v)]
            ax = axs[i]
            (osm, osr), (slope, inter, _) = stats.probplot(v, dist="norm")
            ax.scatter(osm, osr, s=18, color=cols[i], edgecolor="black", linewidth=0.4)
            ax.plot(osm, slope * np.asarray(osm) + inter, color="black", lw=1.2)
            ax.set_title(str(k), fontsize=SETTINGS.font_size)
            ax.set_xlabel("Theoretical quantiles")
            ax.set_ylabel("Observed")
        for j in range(n, len(axs)):
            axs[j].set_visible(False)
        fig.suptitle(title, fontweight="bold")
        fig.tight_layout()
    return fig


def histogram(values_dict: dict, xlabel="", title="Distribution"):
    labels = list(values_dict)
    cols = palette(len(labels))
    with styled():
        fig, ax = new_figure()
        for i, k in enumerate(labels):
            v = np.asarray(values_dict[k], float)
            v = v[~np.isnan(v)]
            if len(v) < 2:
                continue
            ax.hist(v, bins="auto", density=True, alpha=0.45, color=cols[i], edgecolor="white", label=str(k))
            if np.std(v) > 0:
                xs = np.linspace(v.min(), v.max(), 200)
                ax.plot(xs, stats.norm.pdf(xs, v.mean(), v.std(ddof=1)), color=cols[i], lw=1.8)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("Density")
        ax.set_title(title)
        if len(labels) > 1:
            ax.legend()
        fig.tight_layout()
    return fig


def scatter_fit(x, y, xlabel="", ylabel="", annotate="", ci=True):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    with styled():
        fig, ax = new_figure()
        c = palette(1)[0]
        ax.scatter(x, y, s=30, color=c, edgecolor="black", linewidth=0.5, zorder=3)
        if len(x) > 2:
            b1, b0 = np.polyfit(x, y, 1)
            xs = np.linspace(x.min(), x.max(), 200)
            ax.plot(xs, b0 + b1 * xs, color="black", lw=1.8, zorder=4)
            if ci:
                n = len(x)
                yhat = b0 + b1 * x
                s = np.sqrt(np.sum((y - yhat) ** 2) / (n - 2))
                se = s * np.sqrt(1 / n + (xs - x.mean()) ** 2 / np.sum((x - x.mean()) ** 2))
                t = stats.t.ppf(0.975, n - 2)
                ax.fill_between(xs, b0 + b1 * xs - t * se, b0 + b1 * xs + t * se, color=c, alpha=0.15, lw=0)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        if annotate:
            ax.text(0.03, 0.97, annotate, transform=ax.transAxes, va="top", ha="left", fontsize=SETTINGS.font_size - 1)
        fig.tight_layout()
    return fig


def heatmap(mat, labels, title="Correlation matrix", vmin=-1, vmax=1, annot_p=None):
    with styled():
        n = len(labels)
        fig = Figure(figsize=(max(4, 0.75 * n + 2), max(3.5, 0.65 * n + 1.5)))
        ax = fig.subplots()
        im = ax.imshow(mat, cmap="RdBu_r", vmin=vmin, vmax=vmax)
        ax.set_xticks(range(n)); ax.set_yticks(range(n))
        ax.set_xticklabels(labels, rotation=45, ha="right"); ax.set_yticklabels(labels)
        for i in range(n):
            for j in range(n):
                txt = f"{mat[i, j]:.2f}"
                if annot_p is not None and i != j:
                    txt += stars(annot_p[i, j]).replace("ns", "")
                ax.text(j, i, txt, ha="center", va="center", fontsize=max(6, SETTINGS.font_size - 3),
                        color="white" if abs(mat[i, j]) > 0.6 else "black")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        ax.set_title(title)
        for s in ax.spines.values():
            s.set_visible(False)
        fig.tight_layout()
    return fig


def regression_diagnostics(fitted, resid, influence=None):
    with styled():
        fig = Figure(figsize=(8.5, 3.0))
        axs = fig.subplots(1, 3)
        c = palette(1)[0]
        axs[0].scatter(fitted, resid, s=16, color=c, edgecolor="black", linewidth=0.3)
        axs[0].axhline(0, color="black", lw=1, ls="--")
        axs[0].set_xlabel("Fitted values"); axs[0].set_ylabel("Residuals"); axs[0].set_title("Residuals vs fitted", fontsize=SETTINGS.font_size)
        (osm, osr), (sl, it, _) = stats.probplot(resid, dist="norm")
        axs[1].scatter(osm, osr, s=16, color=c, edgecolor="black", linewidth=0.3)
        axs[1].plot(osm, sl * np.asarray(osm) + it, color="black", lw=1)
        axs[1].set_xlabel("Theoretical quantiles"); axs[1].set_ylabel("Residuals"); axs[1].set_title("Normal Q–Q", fontsize=SETTINGS.font_size)
        if influence is not None:
            axs[2].stem(np.arange(len(influence)), influence, markerfmt=" ", basefmt=" ")
            axs[2].axhline(4 / len(influence), color="#C0392B", lw=1, ls="--")
            axs[2].set_xlabel("Observation"); axs[2].set_ylabel("Cook's distance"); axs[2].set_title("Influence", fontsize=SETTINGS.font_size)
        fig.tight_layout()
    return fig


def km_plot(curves: dict, xlabel="Time", ylabel="Survival probability", risk_table: dict | None = None,
            ptext="", ci=True, times_grid=None):
    """curves: {label: (t, s, lo, hi, censor_times, censor_s)}"""
    labels = list(curves)
    cols = palette(len(labels))
    with styled():
        has_rt = risk_table is not None
        fig = Figure(figsize=(SETTINGS.fig_width_mm * MM * 1.35, SETTINGS.fig_height_mm * MM * (1.45 if has_rt else 1.1)))
        if has_rt:
            gs = fig.add_gridspec(2, 1, height_ratios=[4, 0.45 + 0.28 * len(labels)], hspace=0.30)
            ax = fig.add_subplot(gs[0])
            axr = fig.add_subplot(gs[1], sharex=ax)
        else:
            ax = fig.subplots()
        for i, k in enumerate(labels):
            t, s, lo, hi, ct, cs = curves[k]
            ax.step(t, s, where="post", color=cols[i], lw=2, label=str(k))
            if ci and lo is not None:
                ax.fill_between(t, lo, hi, step="post", color=cols[i], alpha=0.12, lw=0)
            if len(ct):
                ax.plot(ct, cs, "|", color=cols[i], markersize=9, mew=1.5)
        ax.set_ylim(-0.02, 1.04)
        ax.set_ylabel(ylabel)
        if len(labels) > 1 or labels[0] != "All":
            ax.legend(loc="lower left" if not ptext else "upper right")
        if ptext:
            ax.text(0.03, 0.05, ptext, transform=ax.transAxes, fontsize=SETTINGS.font_size - 1)
        if has_rt:
            ax.tick_params(labelbottom=False)
            tg = risk_table["times"]
            for i, k in enumerate(labels):
                y = len(labels) - 1 - i
                for tt, nn in zip(tg, risk_table["n"][k]):
                    axr.text(tt, y, str(nn), ha="center", va="center", color=cols[i], fontsize=SETTINGS.font_size - 1.5)
            axr.set_ylim(-0.6, len(labels) - 0.4)
            axr.set_yticks(range(len(labels)))
            axr.set_yticklabels(list(reversed([str(l) for l in labels])), fontsize=SETTINGS.font_size - 1.5)
            for s in ["left", "top", "right"]:
                axr.spines[s].set_visible(False)
            axr.tick_params(axis="y", length=0, pad=16)
            axr.set_xlabel(xlabel)
            axr.set_title("Number at risk", fontsize=SETTINGS.font_size - 1, loc="left", fontweight="bold")
        else:
            ax.set_xlabel(xlabel)
        ax.set_xlim(left=0)
        fig.subplots_adjust(left=0.22, right=0.96, top=0.96, bottom=0.12)
    return fig


def roc_plot(curves: dict, cut_points=None):
    """curves: {label: (fpr, tpr, auc)}; cut_points {label: (fpr, tpr)}"""
    labels = list(curves)
    cols = palette(len(labels))
    with styled():
        fig, ax = new_figure(h_mm=SETTINGS.fig_width_mm)
        for i, k in enumerate(labels):
            fpr, tpr, auc = curves[k]
            ax.plot(fpr, tpr, color=cols[i], lw=2.2, label=f"{k} (AUC = {auc:.3f})")
            if cut_points and k in cut_points:
                ax.scatter(*cut_points[k], s=60, color=cols[i], edgecolor="black", zorder=5)
        ax.plot([0, 1], [0, 1], ls="--", color="#999999", lw=1)
        ax.set_xlim(-0.01, 1.01); ax.set_ylim(-0.01, 1.01)
        ax.set_xlabel("1 − Specificity"); ax.set_ylabel("Sensitivity")
        ax.set_aspect("equal")
        ax.legend(loc="lower right")
        fig.tight_layout()
    return fig


def bland_altman_plot(mean, diff, bias, lo, hi, ci=None, xlabel="Mean of methods", ylabel="Difference"):
    with styled():
        fig, ax = new_figure(w_mm=SETTINGS.fig_width_mm * 1.2)
        c = palette(1)[0]
        ax.scatter(mean, diff, s=28, color=c, edgecolor="black", linewidth=0.5, zorder=3)
        xr = (np.min(mean), np.max(mean))
        for val, lab, ls in [(bias, "Bias", "-"), (lo, "−1.96 SD", "--"), (hi, "+1.96 SD", "--")]:
            ax.axhline(val, color="#C0392B" if lab != "Bias" else "black", ls=ls, lw=1.4)
            ax.text(xr[1], val, f" {lab}\n {val:.3g}", va="center", ha="left", fontsize=SETTINGS.font_size - 2)
        if ci:
            for (a, b) in ci:
                ax.axhspan(a, b, color="#999999", alpha=0.15, lw=0)
        ax.axhline(0, color="#999999", lw=0.8, ls=":")
        ax.set_xlabel(xlabel); ax.set_ylabel(ylabel)
        fig.subplots_adjust(right=0.80, left=0.16, bottom=0.15)
    return fig


def dose_response_plot(x, y, xfit, yfit, xlabel="log10 dose", ylabel="Response", marks=None, yerr=None,
                       logx_values=False, ylim=None):
    with styled():
        fig, ax = new_figure(w_mm=SETTINGS.fig_width_mm * 1.15)
        c = palette(1)[0]
        if yerr is not None:
            ax.errorbar(x, y, yerr=yerr, fmt="o", color=c, mec="black", mew=0.6, ms=7, capsize=4, ecolor="black", zorder=3)
        else:
            ax.scatter(x, y, s=40, color=c, edgecolor="black", linewidth=0.6, zorder=3)
        ax.plot(xfit, yfit, color="black", lw=2)
        if marks:
            for (mx, my, lab) in marks:
                ax.plot([mx, mx], [ax.get_ylim()[0] if ylim is None else ylim[0], my], ls="--", color="#C0392B", lw=1)
                ax.text(mx, my, f"  {lab}", color="#C0392B", va="center", fontsize=SETTINGS.font_size - 1)
        if ylim:
            ax.set_ylim(*ylim)
        ax.set_xlabel(xlabel); ax.set_ylabel(ylabel)
        fig.tight_layout()
    return fig


def forest_plot(labels, est, lo, hi, weights=None, summary=None, xlabel="Effect size", log_scale=False,
                null=0.0, pi=None):
    """summary: list of (label, est, lo, hi). Values on the analysis scale; log_scale exponentiates labels."""
    k = len(labels)
    nsum = len(summary or [])
    with styled():
        fig = Figure(figsize=(7.2, 0.32 * (k + nsum) + 1.4))
        ax = fig.subplots()
        tr = np.exp if log_scale else (lambda v: v)
        ys = np.arange(k)[::-1] + nsum + 1
        w = np.asarray(weights if weights is not None else np.ones(k), float)
        sizes = 30 + 220 * w / w.max()
        c = palette(1)[0]
        for i in range(k):
            ax.plot([tr(lo[i]), tr(hi[i])], [ys[i]] * 2, color="black", lw=1.2)
            ax.scatter(tr(est[i]), ys[i], s=sizes[i], marker="s", color=c, zorder=3)
        ylabels = list(labels)
        ypos = list(ys)
        for j, (lab, e, l, h) in enumerate(summary or []):
            y = nsum - j - 0.2
            ax.fill([tr(l), tr(e), tr(h), tr(e)], [y, y + 0.28, y, y - 0.28], color="#C0392B" if j == 0 else "#7D3C98", zorder=3)
            ylabels.append(lab); ypos.append(y)
        if pi is not None:
            ax.plot([tr(pi[0]), tr(pi[1])], [nsum - 0.2 - 0.5] * 2, color="#C0392B", lw=3, alpha=0.4)
        ax.axvline(tr(null), color="#555555", ls="--", lw=1)
        if log_scale:
            ax.set_xscale("log")
        ax.set_yticks(ypos); ax.set_yticklabels(ylabels)
        ax.tick_params(axis="y", length=0)
        ax.spines["left"].set_visible(False)
        ax.set_xlabel(xlabel)
        # right-hand text column
        txts = [f"{tr(e):.2f} [{tr(l):.2f}, {tr(h):.2f}]" for e, l, h in zip(est, lo, hi)]
        txts += [f"{tr(e):.2f} [{tr(l):.2f}, {tr(h):.2f}]" for _, e, l, h in (summary or [])]
        for y, t in zip(ypos, txts):
            ax.text(1.02, y, t, transform=ax.get_yaxis_transform(), va="center", fontsize=SETTINGS.font_size - 2)
        if weights is not None:
            for y, ww in zip(ys, w / w.sum() * 100):
                ax.text(1.36, y, f"{ww:.1f}%", transform=ax.get_yaxis_transform(), va="center", fontsize=SETTINGS.font_size - 2)
        ax.set_ylim(-1, k + nsum + 1.5)
        fig.subplots_adjust(left=0.28, right=0.68, bottom=0.12, top=0.97)
    return fig


def funnel_plot(est, se, pooled, xlabel="Effect size"):
    with styled():
        fig, ax = new_figure()
        c = palette(1)[0]
        ax.scatter(est, se, s=30, color=c, edgecolor="black", linewidth=0.5, zorder=3)
        smax = max(se) * 1.1
        ss = np.linspace(0, smax, 50)
        ax.plot(pooled - 1.96 * ss, ss, ls="--", color="black", lw=1)
        ax.plot(pooled + 1.96 * ss, ss, ls="--", color="black", lw=1)
        ax.axvline(pooled, color="#C0392B", lw=1.2)
        ax.set_ylim(smax, 0)
        ax.set_xlabel(xlabel); ax.set_ylabel("Standard error")
        fig.tight_layout()
    return fig


def interaction_plot(levels_a, series: dict, ylabel="", xlabel="", errs: dict | None = None):
    cols = palette(len(series))
    with styled():
        fig, ax = new_figure(w_mm=SETTINGS.fig_width_mm * 1.2)
        xs = np.arange(len(levels_a))
        markers = ["o", "s", "^", "D", "v", "P", "X", "*"]
        for i, (k, means) in enumerate(series.items()):
            e = errs[k] if errs else None
            ax.errorbar(xs + (i - (len(series) - 1) / 2) * 0.05, means, yerr=e, color=cols[i], marker=markers[i % 8],
                        ms=7, mec="black", mew=0.5, capsize=4, lw=2, label=str(k))
        ax.set_xticks(xs); ax.set_xticklabels([str(l) for l in levels_a])
        ax.set_xlabel(xlabel); ax.set_ylabel(ylabel)
        ax.legend(title=None)
        fig.tight_layout()
    return fig


def bar_counts(table, xlabel="", ylabel="Percentage (%)"):
    """Clustered bar chart of column percentages from a crosstab DataFrame (rows=groups, cols=categories)."""
    cols = palette(table.shape[1])
    with styled():
        fig, ax = new_figure(w_mm=SETTINGS.fig_width_mm * 1.2)
        pct = table.div(table.sum(axis=1), axis=0) * 100
        n_r, n_c = pct.shape
        width = 0.8 / n_c
        for j, c in enumerate(pct.columns):
            ax.bar(np.arange(n_r) + (j - (n_c - 1) / 2) * width, pct[c].values, width=width * 0.95,
                   color=cols[j], edgecolor="black", linewidth=0.8, label=str(c))
        ax.set_xticks(np.arange(n_r)); ax.set_xticklabels([str(i) for i in pct.index])
        ax.set_xlabel(xlabel); ax.set_ylabel(ylabel)
        ax.legend(title=str(table.columns.name or ""))
        fig.tight_layout()
    return fig


def line_profile(times, groups: dict, ylabel="", xlabel="Time", errs: dict | None = None):
    return interaction_plot(times, groups, ylabel=ylabel, xlabel=xlabel, errs=errs)


def power_curve(ns, powers, target=None, xlabel="Sample size per group", ylabel="Power"):
    with styled():
        fig, ax = new_figure()
        ax.plot(ns, powers, color=palette(1)[0], lw=2.2)
        ax.axhline(0.8, color="#999999", ls="--", lw=1)
        if target:
            ax.scatter([target[0]], [target[1]], s=50, color="#C0392B", zorder=4, edgecolor="black")
        ax.set_ylim(0, 1.02)
        ax.set_xlabel(xlabel); ax.set_ylabel(ylabel)
        fig.tight_layout()
    return fig


def scree_plot(eigs):
    with styled():
        fig, ax = new_figure()
        xs = np.arange(1, len(eigs) + 1)
        ax.plot(xs, eigs, marker="o", color=palette(1)[0], mec="black")
        ax.axhline(1, color="#999999", ls="--", lw=1)
        ax.set_xlabel("Component"); ax.set_ylabel("Eigenvalue")
        ax.set_xticks(xs)
        fig.tight_layout()
    return fig


def pca_biplot(scores, loadings, var_names, groups=None, pc_var=(0, 0)):
    with styled():
        fig, ax = new_figure(w_mm=SETTINGS.fig_width_mm * 1.25, h_mm=SETTINGS.fig_width_mm * 1.05)
        if groups is not None:
            levels = list(dict.fromkeys(groups))
            cols = palette(len(levels))
            for i, g in enumerate(levels):
                m = np.asarray([gg == g for gg in groups])
                ax.scatter(scores[m, 0], scores[m, 1], s=26, color=cols[i], edgecolor="black", linewidth=0.4, label=str(g))
            ax.legend()
        else:
            ax.scatter(scores[:, 0], scores[:, 1], s=26, color=palette(1)[0], edgecolor="black", linewidth=0.4)
        scale = np.abs(scores[:, :2]).max() / max(np.abs(loadings[:, :2]).max(), 1e-9) * 0.8
        for j, v in enumerate(var_names):
            ax.arrow(0, 0, loadings[j, 0] * scale, loadings[j, 1] * scale, color="#C0392B", width=0.002 * scale,
                     head_width=0.04 * scale, length_includes_head=True)
            ax.text(loadings[j, 0] * scale * 1.08, loadings[j, 1] * scale * 1.08, v, color="#C0392B",
                    fontsize=SETTINGS.font_size - 2)
        ax.axhline(0, color="#BBBBBB", lw=0.8); ax.axvline(0, color="#BBBBBB", lw=0.8)
        ax.set_xlabel(f"PC1 ({pc_var[0]:.1f}%)"); ax.set_ylabel(f"PC2 ({pc_var[1]:.1f}%)")
        fig.tight_layout()
    return fig
