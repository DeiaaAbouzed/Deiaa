"""Prism-style group comparison figure with a fully editable specification.

Every figure made by ``render`` keeps its ``GroupFigSpec`` on ``fig._mx_spec``, so the
figure editor can change chart type, colours, points, fonts, axes and significance marks,
then redraw instantly without re-running the analysis.
"""
from __future__ import annotations

import copy
import math
import textwrap
from dataclasses import dataclass, field

import matplotlib as mpl
import numpy as np
from scipy import stats

from ..core.settings import SETTINGS

MM = 1 / 25.4

PLOT_TYPES = ["Scatter + mean ± SD", "Bar + points", "Bar (no points)", "Box + points", "Violin + points", "Mean ± error only"]
PLOT_TYPES_AR = ["نقاط + المتوسط ± الخطأ", "أعمدة + نقاط", "أعمدة فقط", "صندوق + نقاط", "كمان + نقاط", "المتوسط ± الخطأ فقط"]
ERROR_TYPES = ["SD", "SEM", "95% CI", "Range", "None"]
MARKERS = {"Circle ●": "o", "Square ■": "s", "Triangle ▲": "^", "Diamond ◆": "D", "Inverted ▼": "v", "Hexagon ⬢": "h"}
SIG_MODES = ["Significant pairs", "All pairs (with ns)", "Versus reference group", "Custom selection", "None"]
SIG_MODES_AR = ["الأزواج الدالة فقط", "كل الأزواج (مع ns)", "مقارنة بمجموعة مرجعية", "اختيار يدوي", "بدون"]
SIG_STYLES = ["Stars", "Exact p", "Stars + exact p"]
SIG_STYLES_AR = ["نجوم", "قيمة p الفعلية", "نجوم + قيمة p"]
SIG_LAYOUTS = ["Brackets", "Symbols above groups"]
SIG_LAYOUTS_AR = ["أقواس", "رموز فوق المجموعات"]
STAR_SCHEMES = ["Standard: 0.05 / 0.01 / 0.001 / 0.0001", "GraphPad: 0.0332 / 0.0021 / 0.0002 / 0.0001"]
LABEL_MODES = ["Wrap", "Rotate 45°", "Horizontal"]
LABEL_MODES_AR = ["التفاف السطر", "مائل 45°", "أفقي"]


@dataclass
class GroupFigSpec:
    groups: dict
    ylabel: str = ""
    xlabel: str = ""
    title: str = ""
    comparisons: list = field(default_factory=list)       # [(a, b, p)] — ALL computed pairs, including ns
    test_name: str = ""                                    # e.g. "one-way ANOVA with Tukey's test"
    paired: bool = False
    center: str = "mean"
    # appearance
    plot_type: str = ""
    error_bar: str = ""
    colors: dict = field(default_factory=dict)             # label -> hex
    fill_alpha: float = 0.30
    point_size: float = 6.0                                # points (diameter)
    marker: str = "o"
    point_edge: bool = True
    line_width: float = 1.3
    bar_width: float = 0.62
    font_family: str = ""
    font_size: float = 0.0
    width_mm: float = 0.0                                  # 0 = automatic
    height_mm: float = 0.0
    y_min: float | None = None
    y_max: float | None = None
    y_log: bool = False
    label_mode: str = "Wrap"
    # significance
    sig_mode: str = "Significant pairs"
    sig_style: str = "Stars"
    sig_layout: str = "Brackets"
    star_scheme: str = STAR_SCHEMES[0]
    show_ns: bool = False
    ref1: str = ""                                         # reference group for symbols "*"
    ref2: str = ""                                         # second reference group for symbols "#"
    selected: list = field(default_factory=list)           # custom selection: ["a|||b", ...]
    caption: str = ""                                      # user-edited caption ("" = automatic)

    def copy(self):
        return copy.deepcopy(self)


# --------------------------------------------------------------------------- helpers
def pair_key(a, b):
    return f"{a}|||{b}"


def star_text(p, scheme=STAR_SCHEMES[0]):
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "ns"
    if scheme.startswith("GraphPad"):
        cuts = [(0.0001, "****"), (0.0002, "***"), (0.0021, "**"), (0.0332, "*")]
    else:
        cuts = [(0.0001, "****"), (0.001, "***"), (0.01, "**"), (0.05, "*")]
    for c, s in cuts:
        if p < c:
            return s
    return "ns"


def p_text(p):
    if p < 0.0001:
        return "p < 0.0001"
    if p < 0.001:
        return f"p = {p:.4f}"
    return f"p = {p:.3f}"


def sig_label(p, spec: GroupFigSpec, symbol="*"):
    st = star_text(p, spec.star_scheme)
    if symbol != "*" and st != "ns":
        st = symbol * len(st)
    if spec.sig_style == "Exact p":
        return p_text(p)
    if spec.sig_style == "Stars + exact p":
        return f"{st}\n{p_text(p)}" if st != "ns" else f"ns\n{p_text(p)}"
    return st


def _err(v, kind):
    n = len(v)
    if n < 2 or kind == "None":
        return 0.0, 0.0
    sd = np.std(v, ddof=1)
    if kind == "SEM":
        e = sd / math.sqrt(n)
    elif kind == "95% CI":
        e = stats.t.ppf(0.975, n - 1) * sd / math.sqrt(n)
    elif kind == "Range":
        m = v.mean()
        return m - v.min(), v.max() - m
    else:
        e = sd
    return e, e


def _darker(c, f=0.65):
    r, g, b, a = mpl.colors.to_rgba(c)
    return (r * f, g * f, b * f, 1)


def swarm_offsets(values, y_range, max_width=0.32, point_frac=0.035):
    """Deterministic bee-swarm: spread points with similar values sideways so none overlap."""
    v = np.asarray(values, float)
    n = len(v)
    if n == 0:
        return np.zeros(0)
    order = np.argsort(v)
    dy = point_frac * (y_range or 1.0)
    dx = 0.075
    placed_x, placed_y = [], []
    xs = np.zeros(n)
    for idx in order:
        y = v[idx]
        cands = [0.0]
        for k in range(1, 40):
            cands += [k * dx, -k * dx]
        for c in cands:
            if abs(c) > max_width:
                c = (np.random.default_rng(idx).uniform(-1, 1)) * max_width
                break
            ok = True
            for px, py in zip(placed_x, placed_y):
                if abs(px - c) < dx * 0.98 and abs(py - y) < dy:
                    ok = False
                    break
            if ok:
                break
        xs[idx] = c
        placed_x.append(c); placed_y.append(y)
    return xs


def stack_levels(intervals):
    """Assign each [x1, x2] interval to the lowest level where it does not overlap another (greedy, short spans first)."""
    order = sorted(range(len(intervals)), key=lambda i: (intervals[i][1] - intervals[i][0], intervals[i][0]))
    levels = [0] * len(intervals)
    occupied = {}
    for i in order:
        a, b = intervals[i]
        lvl = 0
        while any(not (b + 0.08 < c or a - 0.08 > d) for c, d in occupied.get(lvl, [])):
            lvl += 1
        occupied.setdefault(lvl, []).append((a, b))
        levels[i] = lvl
    return levels


def visible_comparisons(spec: GroupFigSpec):
    """Return list of (a, b, p) to draw as brackets according to the significance settings."""
    labels = list(spec.groups)
    comps = [(a, b, p) for a, b, p in spec.comparisons if a in labels and b in labels and p is not None and not np.isnan(p)]
    m = spec.sig_mode
    if m == "None" or not SETTINGS.show_significance:
        return []
    if m == "Custom selection":
        sel = set(spec.selected)
        return [c for c in comps if pair_key(c[0], c[1]) in sel or pair_key(c[1], c[0]) in sel]
    if m == "Versus reference group":
        refs = [r for r in (spec.ref1 or labels[0], spec.ref2) if r]
        comps = [c for c in comps if c[0] in refs or c[1] in refs]
    if m == "All pairs (with ns)" or spec.show_ns:
        return comps
    return [c for c in comps if star_text(c[2], spec.star_scheme) != "ns"]


# --------------------------------------------------------------------------- render
def render(spec: GroupFigSpec):
    from matplotlib.figure import Figure
    from .figures import style_rc, palette

    labels = list(spec.groups)
    k = len(labels)
    pal = palette(k)
    colors = [spec.colors.get(l, pal[i]) for i, l in enumerate(labels)]
    plot_type = spec.plot_type or SETTINGS.group_plot
    err_kind = spec.error_bar or SETTINGS.error_bar
    fs = spec.font_size or SETTINGS.font_size
    rc = style_rc()
    rc["font.size"] = fs
    if spec.font_family:
        rc["font.family"] = [spec.font_family, "DejaVu Sans"]
    arrs = [np.asarray(spec.groups[l], float) for l in labels]
    arrs = [a[~np.isnan(a)] for a in arrs]
    allv = np.concatenate([a for a in arrs if len(a)]) if any(len(a) for a in arrs) else np.array([0.0])
    vmin, vmax = float(allv.min()), float(allv.max())
    rng = (vmax - vmin) or abs(vmax) or 1.0

    width = spec.width_mm or max(SETTINGS.fig_width_mm, 26 + 22 * k)
    comps_vis = visible_comparisons(spec)
    n_levels = 0
    if comps_vis and spec.sig_layout == "Brackets":
        _idx = {l: i for i, l in enumerate(labels)}
        n_levels = max(stack_levels([(min(_idx[a], _idx[b]), max(_idx[a], _idx[b])) for a, b, _ in comps_vis])) + 1
    text_lines = 2 if spec.sig_style == "Stars + exact p" else 1
    level_mm = (fs * 0.3528) * (1.25 + 0.95 * (text_lines - 1)) + 1.2      # text height + gap, in mm
    height = spec.height_mm or max(SETTINGS.fig_height_mm, 70, width * 0.62, 55 + n_levels * level_mm * 1.15)
    with mpl.rc_context(rc):
        fig = Figure(figsize=(width * MM, height * MM))
        ax = fig.add_subplot(111)
        tops = []
        show_points = plot_type not in ("Bar (no points)", "Mean ± error only")
        for i, (lab, v, c) in enumerate(zip(labels, arrs, colors)):
            if not len(v):
                tops.append(np.nan)
                continue
            m = np.median(v) if spec.center == "median" else v.mean()
            lo_e, hi_e = _err(v, err_kind)
            top = max(v.max() if show_points else m + hi_e, m + hi_e)
            if plot_type.startswith("Bar"):
                ax.bar(i, m, width=spec.bar_width, color=mpl.colors.to_rgba(c, spec.fill_alpha if show_points else 0.85),
                       edgecolor=_darker(c, 0.8), linewidth=spec.line_width, zorder=1)
                if err_kind != "None":
                    ax.errorbar(i, m, yerr=[[0 if not show_points else lo_e], [hi_e]], fmt="none", ecolor="black",
                                capsize=5, elinewidth=spec.line_width, capthick=spec.line_width, zorder=4)
            elif plot_type.startswith("Box"):
                bp = ax.boxplot(v, positions=[i], widths=spec.bar_width * 0.85, patch_artist=True, showfliers=not show_points,
                                medianprops=dict(color="black", lw=spec.line_width * 1.4),
                                whiskerprops=dict(lw=spec.line_width), capprops=dict(lw=spec.line_width),
                                boxprops=dict(lw=spec.line_width))
                bp["boxes"][0].set_facecolor(mpl.colors.to_rgba(c, spec.fill_alpha))
                bp["boxes"][0].set_edgecolor(_darker(c, 0.8))
                top = max(top, v.max())
            elif plot_type.startswith("Violin") and len(v) > 2:
                vp = ax.violinplot(v, positions=[i], widths=spec.bar_width * 1.1, showextrema=False)
                for b in vp["bodies"]:
                    b.set_facecolor(mpl.colors.to_rgba(c, spec.fill_alpha)); b.set_edgecolor(_darker(c, 0.8)); b.set_alpha(None)
                q1, med, q3 = np.percentile(v, [25, 50, 75])
                ax.plot([i, i], [q1, q3], c="black", lw=spec.line_width * 3, solid_capstyle="butt", zorder=4)
                ax.scatter([i], [med], c="white", s=20, zorder=5, edgecolor="black", linewidth=0.8)
                top = max(top, v.max())
            else:  # scatter / mean ± error
                ax.hlines(m, i - 0.26, i + 0.26, color="black", lw=spec.line_width * 1.5, zorder=5)
                if err_kind != "None":
                    ax.errorbar(i, m, yerr=[[lo_e], [hi_e]], fmt="none", ecolor="black", capsize=5,
                                elinewidth=spec.line_width, capthick=spec.line_width, zorder=5)
            if show_points:
                xo = swarm_offsets(v, rng, max_width=min(0.34, spec.bar_width * 0.55),
                                   point_frac=0.022 * spec.point_size / 6)
                ax.scatter(i + xo, v, s=spec.point_size ** 2, marker=spec.marker, color=c,
                           edgecolor=_darker(c) if spec.point_edge else "none", linewidth=0.7, zorder=3, alpha=0.95)
            tops.append(top)
        if spec.paired and k >= 2 and len({len(a) for a in arrs}) == 1:
            for row in zip(*[np.asarray(spec.groups[l], float) for l in labels]):
                ax.plot(range(k), row, color="#9AA5B1", lw=0.7, zorder=2)

        # axes / labels
        ax.set_xticks(range(k))
        if spec.label_mode == "Rotate 45°":
            ax.set_xticklabels(labels, rotation=45, ha="right", rotation_mode="anchor")
        elif spec.label_mode == "Horizontal":
            ax.set_xticklabels(labels)
        else:
            wrap = max(6, int((width - 20) / max(k, 1) / (fs * 0.24)))
            ax.set_xticklabels(["\n".join(textwrap.wrap(str(l), wrap, break_long_words=False, break_on_hyphens=False)) or str(l) for l in labels])
        ax.set_xlim(-0.6, k - 0.4)
        ax.set_ylabel(spec.ylabel)
        if spec.xlabel:
            ax.set_xlabel(spec.xlabel)
        if spec.title:
            ax.set_title(spec.title, fontweight="bold")
        if spec.y_log:
            ax.set_yscale("log")
        bottom = 0 if (plot_type.startswith("Bar") and vmin >= 0) else None
        if bottom is not None:
            ax.set_ylim(bottom=0)

        # significance
        comps = visible_comparisons(spec)
        top_needed = vmax + 0.06 * rng
        if comps and spec.sig_layout == "Symbols above groups":
            refs = [(spec.ref1 or labels[0], "*")] + ([(spec.ref2, "#")] if spec.ref2 else [])
            marks = {l: [] for l in labels}
            for a, b, p in comps:
                for ref, sym in refs:
                    if ref in (a, b):
                        other = b if a == ref else a
                        txt = sig_label(p, spec, sym)
                        if txt != "ns" or spec.show_ns:
                            marks[other].append((sym, txt))
            for i, l in enumerate(labels):
                if not marks[l] or np.isnan(tops[i]):
                    continue
                txt = "\n".join(t for _, t in sorted(marks[l]))
                ax.text(i, tops[i] + 0.03 * rng, txt, ha="center", va="bottom", fontsize=fs * 0.95,
                        linespacing=1.0, fontweight="bold")
                top_needed = max(top_needed, tops[i] + (0.09 + 0.07 * (txt.count("\n"))) * rng)
        elif comps:
            idx = {l: i for i, l in enumerate(labels)}
            ints = [(min(idx[a], idx[b]), max(idx[a], idx[b])) for a, b, _ in comps]
            levels = stack_levels(ints)
            axis_mm = height * 0.62
            step = level_mm * 1.0 * rng / max(axis_mm - level_mm * len(set(levels)), axis_mm * 0.25)
            base = vmax + 0.07 * rng
            h = 0.018 * rng
            level_y = {}
            prev = None
            for lvl in sorted(set(levels)):
                local = max(np.nanmax(tops[x1:x2 + 1]) for (x1, x2), l in zip(ints, levels) if l == lvl)
                y_l = max(local + 0.07 * rng, base)
                if prev is not None:
                    y_l = max(y_l, prev + step)
                level_y[lvl] = prev = y_l
            for (a, b, p), (x1, x2), lvl in zip(comps, ints, levels):
                y = level_y[lvl]
                ax.plot([x1 + 0.04, x1 + 0.04, x2 - 0.04, x2 - 0.04], [y, y + h, y + h, y], lw=spec.line_width * 0.85,
                        c="black", clip_on=False, solid_capstyle="butt")
                txt = sig_label(p, spec)
                is_star = spec.sig_style == "Stars" and txt != "ns"
                ax.text((x1 + x2) / 2, y + h * (0.2 if is_star else 1.3), txt, ha="center", va="bottom",
                        fontsize=fs * (1.05 if is_star else 0.78), linespacing=0.95)
                top_needed = max(top_needed, y + step * 0.9)
        lo, hi = ax.get_ylim()
        new_hi = max(hi, top_needed)
        ax.set_ylim(lo if bottom is None else 0, new_hi)
        if spec.y_min is not None or spec.y_max is not None:
            ax.set_ylim(spec.y_min if spec.y_min is not None else ax.get_ylim()[0],
                        spec.y_max if spec.y_max is not None else ax.get_ylim()[1])
        fig.tight_layout()
    fig._mx_spec = spec
    return fig


# --------------------------------------------------------------------------- caption
def auto_caption(spec: GroupFigSpec, lang="en"):
    labels = list(spec.groups)
    ns = [int(np.sum(~np.isnan(np.asarray(spec.groups[l], float)))) for l in labels]
    n_txt = f"n = {ns[0]} per group" if len(set(ns)) == 1 else "n = " + ", ".join(map(str, ns))
    pt = spec.plot_type or SETTINGS.group_plot
    err = spec.error_bar or SETTINGS.error_bar
    center = "median" if spec.center == "median" else "mean"
    comps = visible_comparisons(spec)
    scheme = spec.star_scheme
    cuts = ("*p < 0.0332, **p < 0.0021, ***p < 0.0002, ****p < 0.0001" if scheme.startswith("GraphPad")
            else "*p < 0.05, **p < 0.01, ***p < 0.001, ****p < 0.0001")
    if lang == "ar":
        what = {"Box + points": "الصندوق يمثل الوسيط والمدى الربيعي", "Violin + points": "شكل الكمان يمثل توزيع القيم مع الوسيط والمدى الربيعي"}.get(
            pt, f"{'الأعمدة' if pt.startswith('Bar') else 'الخط الأفقي'} = {'الوسيط' if center == 'median' else 'المتوسط'}"
                + (f" ± {err}" if err != "None" else ""))
        s = f"{spec.ylabel} في المجموعات ({len(labels)}). {what}"
        if pt not in ("Bar (no points)", "Mean ± error only"):
            s += "، والنقاط قيم فردية"
        s += f" ({n_txt})."
        if spec.test_name:
            s += f" الاختبار: {spec.test_name}."
        if comps:
            if spec.sig_layout == "Symbols above groups":
                s += f" * مقارنة بـ {spec.ref1 or labels[0]}" + (f"، # مقارنة بـ {spec.ref2}" if spec.ref2 else "") + "."
            s += f" {cuts}; ns غير دال."
        return s
    if pt == "Box + points":
        what = "Boxes show median and interquartile range, whiskers 1.5 × IQR"
    elif pt == "Violin + points":
        what = "Violins show the distribution with median and interquartile range"
    else:
        what = f"{'Bars' if pt.startswith('Bar') else 'Horizontal lines'} show the {center}" + (f" ± {err}" if err != "None" else "")
    s = f"{spec.ylabel} across the {len(labels)} groups. {what}"
    if pt not in ("Bar (no points)", "Mean ± error only"):
        s += "; dots are individual values"
    s += f" ({n_txt})."
    if spec.test_name:
        s += f" {spec.test_name[0].upper() + spec.test_name[1:]}."
    if comps:
        if spec.sig_layout == "Symbols above groups":
            s += f" * versus {spec.ref1 or labels[0]}" + (f"; # versus {spec.ref2}" if spec.ref2 else "") + "."
        if spec.sig_style != "Exact p":
            s += f" {cuts}" + ("; ns, not significant." if spec.show_ns or spec.sig_mode == "All pairs (with ns)" else ".")
    return s


def caption_for(spec: GroupFigSpec):
    return spec.caption or auto_caption(spec, "en")
