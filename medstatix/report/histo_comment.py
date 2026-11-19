"""Professional histopathology comments, figure legends and a group Results paragraph from the AI reader.

Wording follows how toxicologic-pathology papers describe rodent sections: lesion, distribution, severity grade
(0 none, 1 mild, 2 moderate, 3 marked) with the measurement that supports it, then a closing impression. Grades use
fixed, stated cut-offs (``GRADING``), so the same image always receives the same grade and the criteria can be quoted
in the methods. Every text is a draft for the investigator and pathologist to confirm."""
from __future__ import annotations

import numpy as np

SEV_EN = ["no", "mild", "moderate", "marked"]
SEV_AR = ["لا يوجد", "خفيف", "متوسط", "شديد"]
SEV_AR_ACC = ["", "خفيفًا", "متوسطًا", "شديدًا"]     # after an accusative noun (أظهر ... ارتشاحًا شديدًا)

# metric: (cut-offs for grades 1, 2, 3)
GRADING = {
    "inflammation": ("Inflammatory cells % of nuclei", (3.0, 8.0, 15.0)),
    "congestion": ("Congestion area % of tissue", (0.5, 2.0, 5.0)),
    "vacuolation": ("Vacuolated area % of tissue", (1.0, 5.0, 15.0)),
}
GRADING_TEXT = ("Lesions were graded semi-quantitatively as 0 (none), 1 (mild), 2 (moderate) or 3 (marked) from the "
                "automated measurements: inflammatory cell infiltration by the proportion of inflammatory nuclei "
                "(<3%, 3–8%, 8–15%, ≥15%), congestion by the RBC-rich area (<0.5%, 0.5–2%, 2–5%, ≥5% of the tissue) and "
                "vacuolation by the vacuolated area (<1%, 1–5%, 5–15%, ≥15%); a focus-forming infiltrate raised the "
                "inflammation grade by one step (maximum 3). Grades were reviewed by the investigator.")


def _grade(v, cuts):
    return int(sum(v >= c for c in cuts)) if v is not None and np.isfinite(v) else 0


def grades(r) -> dict:
    S = r.get("summary", {})
    g = {k: _grade(S.get(m), cuts) for k, (m, cuts) in GRADING.items()}
    if r.get("foci") and g["inflammation"] < 3:
        g["inflammation"] += 1
    return g


def _ar_count(n, one, two, few, many):
    return f"{one} واحدة" if n == 1 else two if n == 2 else f"{n} {few}" if 3 <= n <= 10 else f"{n} {many}"


def _an(word):
    return "an" if word[:1].upper() in "AEFHILMNORSX" and (word[:1].isupper() or word[:1] in "aeiou") else "a"


def _dist(r):
    nf = len(r.get("foci") or [])
    if nf >= 3:
        return "multifocal", "متعدد البؤر"
    if nf:
        return "focal", "بؤري"
    return "scattered", "متناثر"


def image_comment(r, organ="", group="", ar=False) -> str:
    """Pathologist-style description of one AI reading (H&E or IHC)."""
    S = r.get("summary", {})
    where = (f"{organ} " if organ else "") + ("section" if not ar else "")
    who_en = f"from {group} " if group else ""
    who_ar = f"من مجموعة {group} " if group else ""
    org_ar = f"من {organ} " if organ else ""
    if r.get("stain") == "IHC":
        n = S.get("Nuclei detected", 0)
        if not n:
            return "لم تُكتشف أنوية في هذه الصورة." if ar else "No nuclei were detected in this image."
        pos = S.get("Positive nuclei %", 0.0); hs = S.get("Cell H-score (0–300)", 0.0)
        lvl = 0 if pos < 5 else 1 if pos < 25 else 2 if pos < 60 else 3
        w = S.get("Weak / moderate / strong %", "")
        if ar:
            return (f"أظهر المقطع {org_ar}{who_ar}تفاعلًا مناعيًا {['سلبيًا تقريبًا', 'ضعيفًا', 'متوسطًا', 'قويًا'][lvl]} "
                    f"(نسبة الأنوية الموجبة {pos:.1f}%، H-score {hs:.0f} من 300؛ ضعيف/متوسط/قوي {w}%).")
        return (f"The {where} {who_en}showed {['negligible', 'weak', 'moderate', 'strong'][lvl]} immunoreactivity "
                f"({pos:.1f}% positive nuclei; H-score {hs:.0f}/300; weak/moderate/strong {w}%).").replace("  ", " ")
    g = grades(r)
    infl_pct = S.get("Inflammatory cells % of nuclei", 0.0)
    dens = S.get("Inflammatory cells per mm²")
    foci = r.get("foci") or []
    cg = S.get("Congestion area % of tissue", 0.0)
    vac = S.get("Vacuolated area % of tissue", 0.0)
    d_en, d_ar = _dist(r)
    if ar:
        parts = []
        if g["inflammation"]:
            t = (f"ارتشاحًا {SEV_AR_ACC[g['inflammation']]} (درجة {g['inflammation']}) {d_ar} بخلايا التهابية وحيدة النواة "
                 f"({infl_pct:.1f}% من الأنوية" + (f"، {dens:.0f} خلية/مم²" if dens else ""))
            if foci:
                t += f"؛ {_ar_count(len(foci), 'بؤرة', 'بؤرتان', 'بؤر', 'بؤرة')} أكبرها {max(f['n'] for f in foci)} خلية"
            parts.append(t + ")")
        if g["congestion"]:
            parts.append(f"احتقانًا وعائيًا {SEV_AR_ACC[g['congestion']]} (درجة {g['congestion']}؛ {cg:.1f}% من مساحة النسيج)")
        if g["vacuolation"]:
            parts.append(f"تفجّيًا {SEV_AR_ACC[g['vacuolation']]} (درجة {g['vacuolation']}؛ {vac:.1f}% من المساحة)")
        if r.get("glomeruli"):
            parts.append(f"تم التعرف على {_ar_count(len(r['glomeruli']), 'كبيبة', 'كبيبتين', 'كبيبات', 'كبيبة')}")
        if not any(g.values()):
            return (f"أظهر المقطع {org_ar}{who_ar}بنية نسيجية محفوظة دون ارتشاح التهابي أو احتقان أو تفجٍّ ملحوظ "
                    f"في القراءة الآلية ({infl_pct:.1f}% أنوية التهابية).")
        return f"أظهر المقطع {org_ar}{who_ar}" + "، و".join(parts) + "."
    parts = []
    if g["inflammation"]:
        t = (f"{SEV_EN[g['inflammation']]} (grade {g['inflammation']}) {d_en} infiltration by mononuclear inflammatory cells "
             f"({infl_pct:.1f}% of nuclei" + (f"; {dens:.0f} cells/mm²" if dens else ""))
        if foci:
            t += (f"; a single focus of {foci[0]['n']} cells" if len(foci) == 1 else
                  f"; {len(foci)} foci, the largest of {max(f['n'] for f in foci)} cells")
        parts.append(t + ")")
    if g["congestion"]:
        parts.append(f"{SEV_EN[g['congestion']]} (grade {g['congestion']}) vascular congestion ({cg:.1f}% of the tissue area)")
    if g["vacuolation"]:
        parts.append(f"{SEV_EN[g['vacuolation']]} (grade {g['vacuolation']}) vacuolation ({vac:.1f}% of the area)")
    head = f"The {where} {who_en}".replace("  ", " ").strip()
    head = head[0].upper() + head[1:] if head else "The section"
    if not any(g.values()):
        return (f"{head} showed preserved histological architecture without appreciable inflammatory cell infiltration, "
                f"congestion or vacuolation on the automated reading ({infl_pct:.1f}% inflammatory nuclei).")
    txt = f"{head} showed " + (", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]) + "."
    if r.get("glomeruli"):
        ng = len(r["glomeruli"])
        txt += f" {'One glomerulus was' if ng == 1 else f'{ng} glomeruli were'} identified in the field."
    return txt[0].upper() + txt[1:]


def legend(r, organ="", group="", stain="H&E", magnification="", fig="Figure 1", ar=False) -> str:
    """Figure legend draft for one annotated photomicrograph."""
    from ..imaging.core import nice_bar_um
    g = grades(r) if r.get("stain") != "IHC" else {}
    px = r.get("px_um") or 0
    sb = (r.get("marks") or {}).get("scale_bar") or {}
    bar = sb.get("um") or (nice_bar_um(r.get("width_px", 1000), px) if px else None)   # the bar already on the image wins
    marks_en, marks_ar = [], []
    if r.get("foci"):
        marks_en.append("yellow outlines, inflammatory foci"); marks_ar.append("الإطار الأصفر: بؤر التهابية")
    if r.get("inflammatory"):
        marks_en.append("cyan, inflammatory cells"); marks_ar.append("الأزرق السماوي: خلايا التهابية")
    if r.get("congestion"):
        marks_en.append("pink dashed outlines, congestion"); marks_ar.append("الخط الوردي المتقطع: احتقان")
    if ar:
        t = (f"{fig}. صورة مجهرية تمثيلية لمقطع {organ or 'نسيجي'} مصبوغ بـ {stain}"
             + (f" من مجموعة {group}" if group else "") + (f" (تكبير {magnification})" if magnification else "") + " تُظهر "
             + image_comment(r, ar=True).replace("أظهر المقطع ", "").rstrip(".") + ".")
        if marks_ar:
            t += " " + "؛ ".join(marks_ar) + "."
        if bar:
            t += f" مقياس الرسم = {bar:g} ميكرومتر."
        return t
    body = image_comment(r).split(" showed ", 1)
    t = (f"{fig}. Representative photomicrograph of {_an(stain)} {stain}-stained {organ + ' ' if organ else ''}section"
         + (f" from {group}" if group else "") + (f" ({magnification})" if magnification else "")
         + " showing " + (body[1].rstrip(".") if len(body) == 2 else body[0].rstrip(".")) + ".")
    if marks_en:
        m = "; ".join(marks_en)
        t += " " + m[0].upper() + m[1:] + "."
    if bar:
        t += f" Scale bar = {bar:g} µm."
    return t


# ----------------------------------------------------------------------------- groups


def group_results(df, group_col="group", control=None, metrics=None, ar=False) -> str:
    """Results paragraph comparing groups on the per-image AI measurements and grades (Kruskal–Wallis, then
    Mann–Whitney versus control with Holm correction). df: one row per image."""
    import pandas as pd
    from scipy import stats
    metrics = metrics or [c for c in ("Inflammation grade", "Inflammatory cells % of nuclei", "Inflammatory cells per mm²",
                                      "Congestion grade", "Congestion area % of tissue", "Vacuolation grade",
                                      "Positive nuclei %", "Cell H-score (0–300)") if c in df.columns]
    groups = [g for g in pd.unique(df[group_col].astype(str))]
    if len(groups) < 2 or not metrics:
        return ""
    from ..plots.figures import is_control
    ctrl = control or next((g for g in groups if is_control(g)), groups[0])
    out, quiet = [], []
    for m in metrics:
        d = {g: pd.to_numeric(df.loc[df[group_col].astype(str) == g, m], errors="coerce").dropna().values for g in groups}
        d = {g: v for g, v in d.items() if len(v)}
        if len(d) < 2 or ctrl not in d:
            continue
        if np.ptp(np.concatenate(list(d.values()))) == 0:
            quiet.append((m, 1.0)); continue
        try:
            H, p = stats.kruskal(*d.values())
        except ValueError:
            continue
        others = [g for g in d if g != ctrl]
        ps = []
        for g in others:
            try:
                ps.append(stats.mannwhitneyu(d[g], d[ctrl], alternative="two-sided").pvalue)
            except ValueError:
                ps.append(1.0)
        order = np.argsort(ps); adj = np.empty(len(ps)); run = 0.0
        for k, i in enumerate(order):
            run = max(run, min(1.0, ps[i] * (len(ps) - k))); adj[i] = run
        med = {g: float(np.median(v)) for g, v in d.items()}
        def fp(x):
            return "p < 0.001" if x < 0.001 else f"p = {x:.3f}"
        sig = [g for g, a in zip(others, adj) if a < 0.05]
        if p >= 0.05 and not sig:
            quiet.append((m, p)); continue
        if ar:
            s = f"اختلف {m} بين المجموعات (كروسكال–واليس H = {H:.2f}، {fp(p)})؛ الوسيط في {ctrl} {med[ctrl]:.2f}"
            s += "، ".join([""] + [f"{g} {med[g]:.2f}" for g in others]) + "."
            if sig:
                s += f" وكان الفرق دالًا مقارنة بـ {ctrl} في: " + "، ".join(f"{g} ({fp(a)})" for g, a in zip(others, adj) if a < 0.05) + "."
        else:
            verb = "differed among the groups" if p < 0.05 else "showed no overall group effect"
            s = (f"{m} {verb} (Kruskal–Wallis H = {H:.2f}, {fp(p)}; median {med[ctrl]:.2f} in {ctrl}, "
                 + ", ".join(f"{med[g]:.2f} in {g}" for g in others) + ").")
            if sig:
                s += (" Compared with " + ctrl + ", values were significantly " +
                      "; ".join(f"{'higher' if med[g] > med[ctrl] else 'lower'} in {g} ({fp(a)}, Holm-adjusted)"
                                for g, a in zip(others, adj) if a < 0.05) + ".")
        out.append(s)
    if quiet:
        names = [m for m, _ in quiet]
        lst = ", ".join(names[:-1]) + (" and " if len(names) > 1 else "") + names[-1]
        out.append(f"لم تختلف المجموعات اختلافًا دالًا في: {'، '.join(names)} (كل قيم p ≥ 0.05)." if ar else
                   f"No significant between-group differences were found in {lst} (all p ≥ 0.05).")
    return " ".join(out)


def per_image_row(r) -> dict:
    """Numbers and grades of one reading, for the batch table."""
    S = r.get("summary", {})
    row = {k: (float(v) if isinstance(v, (int, float, np.floating, np.integer)) else v) for k, v in S.items()}
    if r.get("stain") != "IHC":
        g = grades(r)
        row.update({"Inflammation grade": g["inflammation"], "Congestion grade": g["congestion"],
                    "Vacuolation grade": g["vacuolation"]})
    return row
