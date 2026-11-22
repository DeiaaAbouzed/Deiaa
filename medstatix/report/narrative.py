"""Results-section prose for a multi-group, multi-marker experiment (control, disease model, treatments).

Written the way pharmacology / toxicology papers report such designs: the model's effect versus control
(fold or % change, values, p), each treatment versus the model (attenuation, recovery %, whether control values are
restored), dose comparison between treatments, then a closing synthesis. Every number comes from the analysis; the
wording varies between markers so the section reads like an author wrote it."""
from __future__ import annotations

import re

import numpy as np

from ..core.result import fmt_p
from ..plots.figures import is_control

UP = ["increased", "raised", "elevated", "increased"]
DOWN = ["decreased", "reduced", "lowered", "decreased"]
COUNTER = ["significantly attenuated", "significantly counteracted", "significantly reversed", "significantly attenuated"]


def _p(p):
    if p is None or not np.isfinite(p):
        return "p not available"
    s = fmt_p(p)
    return f"p {s}" if s.startswith("<") else f"p = {s}"


def split_unit(name: str):
    m = re.match(r"^\s*(.*?)\s*\(([^()]*)\)\s*$", str(name))
    return (m.group(1), m.group(2)) if m else (str(name), "")


def _centre(a, npar):
    return float(np.median(a)) if npar else float(np.mean(a))


def _val(a, npar, dec, sem=False):
    if npar:
        q1, med, q3 = np.percentile(a, [25, 50, 75])
        return f"{med:.{dec}f} ({q1:.{dec}f}–{q3:.{dec}f})"
    e = np.std(a, ddof=1) / (np.sqrt(len(a)) if sem else 1) if len(a) > 1 else 0.0
    return f"{np.mean(a):.{dec}f} ± {e:.{dec}f}"


def _change(m1, m0, lang="en"):
    """'about 3.0-fold' / 'by 59%' (Arabic: 'بنحو 3.0 أضعاف' / 'بنسبة 59%') for m1 relative to m0."""
    if m0 == 0 or not np.isfinite(m0):
        return ""
    r = m1 / m0
    if r >= 2:
        return f"about {r:.1f}-fold" if lang == "en" else f"بنحو {r:.1f} ضعف"
    pct = abs(r - 1) * 100
    return f"by {pct:.0f}%" if lang == "en" else f"بنسبة {pct:.0f}%"


def _join(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def write(info: dict, levels: list, ctrl: str, mdl: str, sem=False, table_ref="Table 1", fig_ref="Figure 1"):
    """info[marker] = dict(g={group: array}, pairs={(a, b): p}, dec=int, npar=bool, test, post, stat, p).
    Returns (english, arabic) text."""
    en, ar = [], []
    markers = list(info)
    others_ctrl = [l for l in levels if l not in (ctrl, mdl) and is_control(l)]
    treats = [l for l in levels if l not in (ctrl, mdl) and l not in others_ctrl]
    ms = "mean ± SEM" if sem else "mean ± SD"
    nps = [info[v]["npar"] for v in markers]
    disp = "median (IQR)" if all(nps) else (ms if not any(nps) else f"{ms} or median (IQR), as indicated in {table_ref}")
    score = {t: [0, 0, 0.0] for t in treats}   # [markers normalised, markers improved vs model, summed recovery %]
    sig_model = [v for v in markers if mdl and info[v]["pairs"].get((mdl, ctrl), 1) < 0.05]
    if mdl:
        if len(sig_model) == len(markers):
            allw = "both markers" if len(markers) == 2 else f"all {len(markers)} markers"
            en.append(f"{mdl} produced significant changes in {allw} measured ({table_ref}; {fig_ref}).")
        elif sig_model:
            en.append(f"{mdl} significantly altered {len(sig_model)} of the {len(markers)} markers measured ({table_ref}; {fig_ref}).")
        else:
            en.append(f"{mdl} did not significantly change any of the markers measured ({table_ref}; {fig_ref}).")
        ar.append(f"أحدثت مجموعة {mdl} تغيرًا دالًا في {len(sig_model)} من {len(markers)} مؤشرات ({table_ref}؛ {fig_ref}).")
    for i, v in enumerate(markers):
        I = info[v]; g, P, dec, npar = I["g"], I["pairs"], I["dec"], I["npar"]
        label, unit = split_unit(v)
        u = f" {unit}" if unit else ""
        c = _centre(g[ctrl], npar)
        s = []
        sa = []
        if not mdl or mdl not in g:
            s.append(f"{label} differed among the groups ({I['stat']}, {_p(I['p'])}).")
            en.append(" ".join(s)); continue
        m = _centre(g[mdl], npar)
        p_mc = P.get((mdl, ctrl))
        up = m > c
        if p_mc is not None and p_mc < 0.05:
            verb = (UP if up else DOWN)[i % 4]
            cg = "the control group" if ctrl.lower() == "control" else ctrl
            s.append([f"{mdl} {verb} {label} {_change(m, c)} compared with {cg} ({_val(g[mdl], npar, dec, sem)} vs "
                      f"{_val(g[ctrl], npar, dec, sem)}{u}; {_p(p_mc)}).",
                      f"Relative to {cg}, {label} was {verb} {_change(m, c)} in {mdl} ({_val(g[mdl], npar, dec, sem)} vs "
                      f"{_val(g[ctrl], npar, dec, sem)}{u}; {_p(p_mc)})."][i % 2])
            sa.append(f"{'رفعت' if up else 'خفضت'} مجموعة {mdl} مستوى {label} {_change(m, c, 'ar')} مقارنة بالضابطة ({_p(p_mc)}).")
        else:
            s.append(f"{label} in {mdl} did not differ significantly from {ctrl} ({_val(g[mdl], npar, dec, sem)} vs "
                     f"{_val(g[ctrl], npar, dec, sem)}{u}; {_p(p_mc)}).")
            sa.append(f"لم يختلف {label} في مجموعة {mdl} عن الضابطة اختلافًا دالًا ({_p(p_mc)}).")
        for oc in others_ctrl:
            p_oc = P.get((oc, ctrl))
            if p_oc is not None and p_oc >= 0.05:
                s.append([f"{oc} alone had no significant effect ({_p(p_oc)} vs {ctrl}).",
                          f"{oc} given alone did not change it ({_p(p_oc)} vs {ctrl}).",
                          f"No significant change was seen with {oc} alone ({_p(p_oc)})."][i % 3])
            elif p_oc is not None:
                s.append(f"Notably, {oc} alone also changed {label} ({_val(g[oc], npar, dec, sem)}{u}; {_p(p_oc)} vs {ctrl}).")
        if treats and p_mc is not None and p_mc < 0.05:
            better, partial, none_ = [], [], []
            for t in treats:
                if t not in g:
                    continue
                mt = _centre(g[t], npar)
                rec = (m - mt) / (m - c) * 100 if m != c else 0.0
                p_tm, p_tc = P.get((t, mdl), 1.0), P.get((t, ctrl), 0.0)
                if p_tm < 0.05 and rec > 0:
                    score[t][1] += 1; score[t][2] += min(rec, 100.0)
                    if p_tc >= 0.05:
                        score[t][0] += 1
                        better.append((t, rec, p_tm, p_tc))
                    else:
                        partial.append((t, rec, p_tm, p_tc))
                else:
                    none_.append((t, rec, p_tm))
            word = COUNTER[i % 4]
            direction = "increase" if up else "decrease"
            if better or partial:
                names = [t for t, *_ in better + partial]
                tail = ""
                if none_:
                    tail = f", whereas {_join([t for t, *_ in none_])} did not" + (f" ({_p(none_[0][2])} vs {mdl})" if len(none_) == 1 else "")
                s.append(f"{_join(names)} {word} this {direction}{tail}.")
                none_ = []      # already reported in the sentence above
            for t, rec, p_tm, p_tc in better:
                s.append(f"In the {t} group, {label} returned to control values ({_val(g[t], npar, dec, sem)}{u}; "
                         f"{_p(p_tm)} vs {mdl}; {_p(p_tc)} vs {ctrl}).")
                sa.append(f"أعادت مجموعة {t} مستوى {label} إلى قيم الضابطة ({_p(p_tm)} مقارنة بـ {mdl}).")
            for t, rec, p_tm, p_tc in partial:
                s.append(f"{t} produced a partial recovery of about {rec:.0f}% ({_val(g[t], npar, dec, sem)}{u}; {_p(p_tm)} vs "
                         f"{mdl}), although values remained different from {ctrl} ({_p(p_tc)}).")
                sa.append(f"أحدثت مجموعة {t} تحسنًا جزئيًا بنحو {rec:.0f}% ({_p(p_tm)} مقارنة بـ {mdl}) دون الوصول لقيم الضابطة.")
            for t, rec, p_tm in none_:
                s.append(f"{t} did not significantly modify {label} relative to {mdl} ({_p(p_tm)}).")
                sa.append(f"لم تُحدث مجموعة {t} تغيرًا دالًا في {label} مقارنة بـ {mdl}.")
            eff = [x for x in better + partial]
            if len(eff) >= 2:
                (t1, r1, *_), (t2, r2, *_) = sorted(eff, key=lambda x: -x[1])[:2]
                p12 = P.get((t1, t2))
                if p12 is not None and p12 < 0.05:
                    s.append(f"The effect of {t1} was significantly greater than that of {t2} ({_p(p12)}).")
                    sa.append(f"وكان تأثير {t1} أكبر دالًا من {t2}.")
                elif p12 is not None:
                    s.append(f"{t1} and {t2} did not differ significantly from each other ({_p(p12)}).")
        en.append(" ".join(s))
        ar.append(" ".join(sa))
    if treats and mdl and sig_model:
        best = max(treats, key=lambda t: (score[t][0], score[t][1], score[t][2]))
        n0, n1, tot = score[best]
        if n1:
            k = len(sig_model)
            imp = ("all" if k > 2 else "both") + f" {k} affected markers" if n1 == k else f"{n1} of the {k} affected markers"
            if n1 == k and k <= 2:
                imp = "both affected markers" if k == 2 else "the affected marker"
            if n0 == 0:
                rest = "although none returned fully to control values"
            elif n0 == n1:
                rest = "and restored " + ("it" if n1 == 1 else "all of them") + " to control values"
            else:
                rest = f"and restored {n0} of them to control values"
            en.append(f"Overall, {best} gave the most consistent protection: it significantly improved {imp} "
                      f"(mean recovery about {tot / n1:.0f}%), {rest}. Values are {disp}.")
            ar.append(f"إجمالًا، كانت {best} الأكثر حماية: حسّنت {n1} من {len(sig_model)} مؤشرات متأثرة وأعادت {n0} منها لقيم الضابطة.")
    return "\n\n".join(en), "\n".join(ar)


def facts(info: dict, levels: list, ctrl: str, mdl: str) -> dict:
    """Structured findings for the Discussion / Abstract: per marker, the model effect and each treatment's effect."""
    others_ctrl = [l for l in levels if l not in (ctrl, mdl) and is_control(l)]
    treats = [l for l in levels if l not in (ctrl, mdl) and l not in others_ctrl]
    out = {"control": ctrl, "model": mdl, "treatments": treats, "levels": list(levels), "markers": []}
    score = {t: [0, 0, 0.0] for t in treats}
    for v, I in info.items():
        g, P, npar = I["g"], I["pairs"], I["npar"]
        label, unit = split_unit(v)
        if not mdl or mdl not in g or ctrl not in g:
            continue
        c, m = _centre(g[ctrl], npar), _centre(g[mdl], npar)
        p_mc = P.get((mdl, ctrl))
        row = {"label": label, "unit": unit, "up": bool(m > c), "change": _change(m, c), "p": p_mc,
               "sig": bool(p_mc is not None and p_mc < 0.05), "treat": []}
        for t in treats:
            if t not in g:
                continue
            mt = _centre(g[t], npar)
            rec = (m - mt) / (m - c) * 100 if m != c else 0.0
            p_tm, p_tc = P.get((t, mdl), 1.0), P.get((t, ctrl), 0.0)
            improved = bool(row["sig"] and p_tm < 0.05 and rec > 0)
            normal = bool(improved and p_tc >= 0.05)
            row["treat"].append({"group": t, "recovery": rec, "improved": improved, "normalised": normal, "p_vs_model": p_tm})
            if improved:
                score[t][1] += 1; score[t][2] += min(rec, 100.0); score[t][0] += normal
        out["markers"].append(row)
    if treats:
        out["best"] = max(treats, key=lambda t: tuple(score[t]))
        out["score"] = {t: {"normalised": s[0], "improved": s[1], "mean_recovery": s[2] / s[1] if s[1] else 0.0}
                        for t, s in score.items()}
    return out
