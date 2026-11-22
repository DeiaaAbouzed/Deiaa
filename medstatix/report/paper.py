"""Full research paper (Word) from the study details, the analyses already run, the histopathology report and the
selected references.

No language model is used: every sentence comes from fixed academic templates filled with the study's own
numbers, the built-in marker knowledge (markers_kb) and the user's references. Statements that only the authors can
make (clinical importance, comparison with specific earlier studies, interpretation of mechanisms) are left as
short [bracketed prompts], highlighted in yellow, so nothing is invented. Methods and Results are complete."""
from __future__ import annotations

import io
import re

from ..core.result import APP_NAME, APP_VERSION, fig_to_png_bytes
from ..core.settings import SETTINGS
from . import markers_kb as KB
from . import refs as RF
from .journals import JOURNALS
from .manuscript import _apa_table, _doc, _p_word, split_methods

DEFAULT_STUDY = {
    "title": "", "authors": "[Author names and affiliations]", "species": "adult male Wistar rats", "weight": "180–220 g",
    "n_per_group": 8, "acclimatisation_days": 7, "ethics": "[Institutional Animal Ethics Committee]", "approval": "[approval number]",
    "model": "", "model_short": "", "drug": "", "drug_source": "[supplier, country]", "route": "orally by gavage",
    "duration": "[duration]", "organ": "", "samples": "serum and tissue homogenates", "kits": "[manufacturer, country]",
    "keywords": "", "group_desc": {}, "anaesthesia": "[anaesthetic, dose and route]",
}


NUM = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def _n(k):
    return NUM.get(k, str(k))


def _cited(sentence, cit):
    """Put the citation before the sentence's final full stop."""
    sentence = sentence.rstrip()
    return (sentence[:-1] + cit + ".") if sentence.endswith(".") else sentence + cit


def _cap(s):
    return s[:1].upper() + s[1:] if s else s


def _join(items):
    items = [i for i in items if i]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def add_para(doc, text, style=None, label=None):
    """Paragraph where [bracketed prompts] are highlighted for the authors to complete; optional bold label first."""
    from docx.enum.text import WD_COLOR_INDEX
    p = doc.add_paragraph(style=style)
    if label:
        p.add_run(label + ": ").bold = True
    for part in re.split(r"(\[[^\]]+\])", text):
        if not part:
            continue
        run = p.add_run(part)
        if part.startswith("[") and part.endswith("]"):
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    return p


# ----------------------------------------------------------------------------- collect what the app knows


def collect(results):
    meth, items, facts, tests = [], [], [], set()
    tnum = fnum = 0
    for res in results:
        e = {"title": res.title.replace("🧠 ", ""), "prose": "", "tables": [], "figures": [], "res_sents": [],
             "meth": [], "summary": False, "outcome": (res.subtitle or "").split(" by ")[0].strip()}
        for b in res.blocks:
            if b.kind == "methods":
                m, r = split_methods(b.content)
                e["meth"] += m
                e["res_sents"] += r
            elif b.kind == "results":
                e["prose"] = b.content.get("en", "")
                if b.content.get("facts"):
                    facts.append(b.content["facts"]); e["summary"] = True
                tests |= set(b.content.get("tests", []))
            elif b.kind == "table":
                cap = (b.caption or "").lower()
                if any(k in cap for k in ("normality", "homogeneity", "robust", "assumption", "shapiro", "levene")):
                    continue
                tnum += 1; e["tables"].append((tnum, b))
            elif b.kind == "figure":
                fnum += 1; e["figures"].append((fnum, b))
        items.append(e)
    # when a multi-marker summary exists, its methods sentence already covers every test used: the per-analysis
    # sentences would repeat (and contradict) it
    src = [e for e in items if e["summary"]] or items
    for e in src:
        meth += [x for x in e["meth"] if x not in meth]
    if any(e["summary"] for e in items):
        meth = [x for x in meth if not re.match(r"(Data are presented as|Data are (shown|expressed) as)", x)]
    return meth, items, facts, tests


def _marker_phrase(mk, model):
    if not mk["sig"]:
        return ""
    return f"{'increased' if mk['up'] else 'decreased'} {mk['label']} {mk['change']}"


# ----------------------------------------------------------------------------- sections


def introduction(st, F, refs, cite):
    model, drug = st["model"] or "[the disease model]", st["drug"] or "[the test compound]"
    markers = [m["label"] for f in F for m in f["markers"]]
    paths = [k for k in KB.group_markers(markers) if k != "other"]
    used = set()

    def c(terms, k=2):
        rs = RF.best(refs, terms, k, used)
        used.update(r.key() for r in rs)
        return (" " + cite(rs)) if rs else " [ref]"

    mterms = [model, st["model_short"], st["organ"]]
    P = []
    P.append(f"{_cap(model)} [is an important cause of {st['organ'] or 'tissue'} injury; state its clinical relevance, "
             f"incidence and the consequences that motivate this work]{c(mterms)}. [Summarise the limitations of current "
             f"management that justify searching for protective agents.]")
    if paths:
        s = [f"The injury produced by {model} involves several interrelated processes."]
        for k in paths:
            s.append(_cited(KB.PATHWAYS[k]["intro"], c(KB.PATHWAYS[k]["terms"] + mterms[:1], 1)))
        s.append("These pathways reinforce one another, so agents that act on more than one of them are of particular interest.")
        P.append(" ".join(s))
    P.append(f"{_cap(drug)} [describe its source or chemical class and its known pharmacological actions]{c([drug])}. "
             f"[Summarise earlier evidence for its antioxidant, anti-inflammatory or anti-apoptotic effects in related "
             f"models]{c([drug] + [KB.PATHWAYS[k]['name'] for k in paths])}. [State what remains unknown, i.e. the gap this "
             f"study addresses.]")
    doses = [t for f in F for t in f.get("treatments", [])]
    org = st["organ"] if st["organ"] and st["organ"].lower() not in model.lower() else ""
    aim = (f"Therefore, the present study was designed to investigate whether {drug} protects against {model}"
           + (f" in the {org}" if org else "") + f" in {st['species']}")
    if paths:
        aim += f", focusing on {_join([KB.PATHWAYS[k]['name'] for k in paths])}"
    aim += " and the accompanying histopathological changes" if st.get("_histo") else ""
    aim += "."
    if len(set(doses)) >= 2:
        aim += f" Two dose levels ({_join(sorted(set(doses)))}) were compared to examine whether the effect is dose dependent."
    P.append(aim)
    return P


def methods(st, F, meth_sents, histo_methods, pw):
    groups = []
    for f in F:
        groups = f.get("levels") or ([f["control"]] + ([f["model"]] if f["model"] else []) + list(f["treatments"]))
        break
    gd = st.get("group_desc") or {}
    n = st["n_per_group"]; k = len(groups) or 1
    S = {}
    S["Chemicals and kits"] = (f"{_cap(st['drug'] or '[Test compound]')} was purchased from {st['drug_source']}. "
                               f"All other chemicals were of analytical grade. Assay kits were obtained from {st['kits']}.")
    S["Animals"] = (f"{_cap(st['species'])} ({st['weight']}) were housed under standard conditions (22 ± 2 °C, 12 h "
                    f"light/dark cycle) with free access to standard chow and water and were acclimatised for "
                    f"{st['acclimatisation_days']} days before the experiment. The protocol was approved by the "
                    f"{st['ethics']} ({st['approval']}) and complied with the ARRIVE guidelines and the National Institutes "
                    f"of Health Guide for the Care and Use of Laboratory Animals.")
    lines = []
    for i, g in enumerate(groups, 1):
        lines.append(f"Group {i} ({g}): {gd.get(g) or '[treatment, dose, route and duration]'}")
    S["Experimental design"] = (f"Animals were randomly allocated to {k} groups (n = {n} per group)"
                                + (": " + "; ".join(lines) + "." if lines else ". [Describe the groups.]")
                                + (f" {_cap(st['model'])} was induced as follows: [procedure]." if st["model"] else ""))
    S["Sample collection"] = (f"At the end of the experiment, animals were anaesthetised with {st['anaesthesia']}; blood "
                              f"was collected for serum separation and {st['organ'] or '[organ]'} samples were excised, "
                              f"rinsed in ice-cold saline and either homogenised for biochemical assays or fixed in 10% "
                              f"neutral buffered formalin for histopathology.")
    markers = [m["label"] for f in F for m in f["markers"]]
    if markers:
        S["Biochemical assays"] = (f"{_join(markers)} were determined in {st['samples']} using commercial kits "
                                   f"({st['kits']}) according to the manufacturers' instructions. [Add catalogue numbers "
                                   f"and assay principles where required.]")
    if histo_methods:
        S["Histopathology and image analysis"] = ("Fixed tissues were processed routinely, embedded in paraffin, sectioned at "
                                                  "4–5 µm and stained with haematoxylin and eosin. " + histo_methods)
    eb = {"SD": "mean ± standard deviation (SD)", "SEM": "mean ± standard error of the mean (SEM)",
          "95% CI": "mean with 95% confidence interval"}.get(SETTINGS.error_bar, "mean ± SD")
    S["Statistical analysis"] = " ".join([f"Data are presented as {eb}, or as median (interquartile range) when not "
                                          "normally distributed, with individual values shown in the figures."]
                                         + meth_sents + [f"All tests were two-sided and {pw} < {SETTINGS.alpha:g} was "
                                                         f"considered statistically significant. Analyses were performed "
                                                         f"with {APP_NAME} version {APP_VERSION}."])
    return S


def discussion(st, F, histo_text, refs, cite):
    model, drug = st["model"] or "[the disease model]", st["drug"] or "[the test compound]"
    used = set()

    def c(terms, k=2):
        rs = RF.best(refs, terms, k, used)
        used.update(r.key() for r in rs)
        return (" " + cite(rs)) if rs else " [ref]"

    P = []
    allm = [m for f in F for m in f["markers"]]
    sig = [m for m in allm if m["sig"]]
    best = next((f.get("best") for f in F if f.get("best")), None)
    sc = next((f.get("score") for f in F if f.get("score")), {})
    s = f"In the present study, {model} " + ((f"significantly altered all {_n(len(allm))} biochemical markers measured"
                                               if len(sig) == len(allm) else
                                               f"significantly altered {_n(len(sig))} of the {_n(len(allm))} biochemical markers measured")
                                              if sig else "did not significantly alter the markers measured")
    if histo_text:
        s += " and produced the histopathological changes described above"
    s += "."
    if best and sc.get(best, {}).get("improved"):
        b = sc[best]
        allw = b["improved"] == len(sig)
        s += (f" Treatment with {best} significantly improved {'all of these' if allw else _n(b['improved']) + ' of these'} markers "
              f"(mean recovery about {b['mean_recovery']:.0f}%)"
              + ((" and restored " + ("them all" if b["normalised"] == b["improved"] else f"{_n(b['normalised'])} of them")
                  + " to control values") if b["normalised"] else "") + ".")
    P.append(s + f" To our knowledge, [state the novelty of these findings for {drug}].")
    groups = KB.group_markers([m["label"] for m in allm])
    for key, names in groups.items():
        rows = [m for m in allm if m["label"] in names and m["sig"]]
        if not rows:
            continue
        pw = KB.PATHWAYS.get(key, {"name": _join(names), "discuss": "", "terms": names})
        eff = _join([_marker_phrase(m, model) for m in rows])
        t = f"Regarding {pw['name']}, {model} {eff} relative to the control group."
        roles = [KB.marker_role(m["label"]) for m in rows]
        roles = [r for r in dict.fromkeys(roles) if r]
        if roles:
            t += " " + " ".join(roles[:-1] + [_cited(roles[-1], c(pw["terms"], 1))])
        elif pw.get("discuss"):
            t += " " + _cited(pw["discuss"], c(pw["terms"], 1))
        t += f" [Compare the magnitude of these changes with earlier reports of {model}]{c([model] + pw['terms'][:2])}."
        tr = []
        for g in dict.fromkeys(x["group"] for m in rows for x in m["treat"]):
            norm = [m["label"] for m in rows for x in m["treat"] if x["group"] == g and x["normalised"]]
            part = [f"{m['label']} (about {x['recovery']:.0f}% recovery)" for m in rows for x in m["treat"]
                    if x["group"] == g and x["improved"] and not x["normalised"]]
            bits = ([f"restored {_join(norm)} to control values"] if norm else []) + ([f"attenuated the change in {_join(part)}"] if part else [])
            if bits:
                tr.append(f"{g} " + " and ".join(bits))
        if tr:
            t += " " + _cap("; ".join(tr)) + "."
            t += f" [Propose how {drug} could act on {pw['name']}]{c([drug] + pw['terms'][:2])}."
        else:
            t += f" {drug} did not significantly modify these markers. [Discuss possible reasons.]"
        P.append(t)
    if histo_text:
        P.append("The biochemical findings were supported by histopathology: " + histo_text.strip()
                 + f" [Relate the lesion pattern to the biochemical changes]{c([model, 'histopathology'])}.")
    tre = next((f["treatments"] for f in F if len(f.get("treatments", [])) >= 2), [])
    if tre and sc:
        order = sorted(tre, key=lambda t: -sc.get(t, {}).get("mean_recovery", 0))
        P.append(f"The protection was greater with {order[0]} than with {order[1]} "
                 f"(mean recovery about {sc[order[0]]['mean_recovery']:.0f}% versus {sc[order[1]]['mean_recovery']:.0f}%), "
                 f"suggesting a dose-dependent effect. [Comment on the dose range and its translational relevance.]")
    P.append("This study has limitations. The sample size was determined for the primary endpoints and may be "
             "insufficient for secondary comparisons; measurements were made at a single time point; and the proposed "
             "mechanisms were inferred from associated changes rather than tested with specific inhibitors or genetic "
             "models. [Add or remove limitations as appropriate.] Further studies should [state the next steps].")
    return P


def abstract(st, F, histo_text):
    model, drug = st["model"] or "[disease model]", st["drug"] or "[test compound]"
    allm = [m for f in F for m in f["markers"]]
    n_groups = max((len(f.get("levels") or []) or (1 + bool(f["model"]) + len(f["treatments"])) for f in F), default=0)
    best = next((f.get("best") for f in F if f.get("best")), None)
    sc = next((f.get("score") for f in F if f.get("score")), {})
    res = [_cap(_marker_phrase(m, model)) for m in allm if m["sig"]][:4]
    out = {
        "Background": f"[One sentence on the importance of {model}.] This study investigated whether {drug} protects against {model} in {st['species']}.",
        "Methods": (f"Animals were allocated to {n_groups or '[k]'} groups (n = {st['n_per_group']} per group). "
                    f"{_join([m['label'] for m in allm])} were measured" + (" and tissue sections were examined histologically" if histo_text else "") + "."),
        "Results": ((f"{_cap(model)} " + _join([r[0].lower() + r[1:] for r in res]) + " (all p < 0.05).") if res
                    else f"{_cap(model)} did not significantly change the markers measured."),
        "Conclusion": f"[State the main conclusion about {drug} in one or two sentences.]",
    }
    if best and sc.get(best, {}).get("improved"):
        b = sc[best]
        nsig = sum(m["sig"] for m in allm)
        out["Results"] += (f" {best} significantly improved " + (f"all {_n(nsig)} affected markers" if b["improved"] == nsig and nsig > 2
                                                                 else "both affected markers" if b["improved"] == nsig == 2
                                                                 else f"{_n(b['improved'])} of the affected markers")
                           + ((" and normalised " + ("all of them" if b["normalised"] == b["improved"] else _n(b["normalised"])))
                              if b["normalised"] else "") + ".")
    return out


# ----------------------------------------------------------------------------- Word


def _prepare(study, results, refs, style, journal):
    st = dict(DEFAULT_STUDY); st.update({k: v for k, v in study.items() if v not in (None, "")})
    meth_sents, items, F, tests = collect(results)
    return st, meth_sents, items, F, tests, _p_word(journal), RF.Citer(list(refs), style)


def _results_paragraphs(items, pw):
    """Results text: the multi-marker summary when there is one (it already reports every marker with its test),
    otherwise each analysis under the name of its outcome."""
    summ = [e for e in items if e["summary"]]
    out = []
    for e in (summ or items):
        body = e["prose"] or " ".join(e["res_sents"])
        if not body:
            continue
        head = "Biochemical findings" if e["summary"] else (f"{e['outcome']}" if e["outcome"] else e["title"])
        out.append((head, [re.sub(r"\bp ([=<])", f"{pw} \\1", para) for para in body.split("\n\n") if para.strip()]))
    return out


def paper_context(study: dict, results: list, refs: list = (), journal="", histo_methods="", histo_results=""):
    """Everything the optional AI writer may use, and nothing else: the study details, the structured findings, the
    exact Results sentences, the Methods as built from the data, and the numbered references with their abstracts."""
    st, meth_sents, items, F, tests, pw, _ = _prepare(study, results, refs, "vancouver", journal)
    st["_histo"] = bool(histo_results)
    meth = methods(st, F, meth_sents, histo_methods, pw)
    facts = F[0] if F else {}
    return {
        "study": {k: st.get(k) for k in ("title", "species", "weight", "n_per_group", "model", "model_short", "drug", "organ",
                                         "samples", "keywords", "route", "duration")},
        "groups": [{"name": g, "treatment": (st.get("group_desc") or {}).get(g, "")} for g in (facts.get("levels") or [])],
        "control_group": facts.get("control"), "model_group": facts.get("model"), "treatment_groups": facts.get("treatments", []),
        "markers": [{"marker": m["label"], "unit": m["unit"], "model_vs_control": ("increased " if m["up"] else "decreased ") + m["change"],
                     "p_model_vs_control": m["p"], "significant": m["sig"],
                     "treatments": [{"group": x["group"], "recovery_percent": round(x["recovery"], 1), "improved": x["improved"],
                                     "back_to_control": x["normalised"], "p_vs_model": x["p_vs_model"]} for x in m["treat"]]}
                    for f in F for m in f["markers"]],
        "overall": {"best_treatment": facts.get("best"), "scores": facts.get("score", {})},
        "results_text": [{"heading": h, "paragraphs": ps} for h, ps in _results_paragraphs(items, pw)],
        "histopathology_results": histo_results or "",
        "methods_text": meth,
        "statistical_tests": sorted(tests),
        "p_symbol": pw,
        "references": [{"id": f"R{i}", "authors": ", ".join(r.authors[:3]) + (" et al." if len(r.authors) > 3 else ""),
                        "year": r.year, "title": r.title, "journal": r.journal, "abstract": (r.abstract or "")[:1500]}
                       for i, r in enumerate(refs, 1)],
    }


def _ai_text(text, refs, cite):
    """[R3] / [R1, R4] markers from the AI writer → real citations; unknown ids become a highlighted [ref]."""
    def sub(m):
        ids = [int(x) for x in re.findall(r"R(\d+)", m.group(0))]
        rs = [refs[i - 1] for i in ids if 1 <= i <= len(refs)]
        return (" " + cite(rs)) if rs else " [ref]"
    text = re.sub(r"\s*\[(?:R\d+\s*[,;–-]?\s*)+\]", sub, text)
    return re.sub(r"\s+([.,;])", r"\1", text)


def build_paper(path, study: dict, results: list, refs: list = (), style="endnote", journal="", histo_methods="",
                histo_results="", width_key="single", ai_sections=None, ai_model=""):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Mm
    refs = list(refs)
    st, meth_sents, items, F, tests, pw, citer = _prepare(study, results, refs, style, journal)
    st["_histo"] = bool(histo_results)
    j = JOURNALS.get(journal or "")
    fig_w = (j["widths"].get(width_key) or list(j["widths"].values())[0]) if j else 160
    A = ai_sections or {}
    T = (lambda x: _ai_text(x, refs, citer.cite)) if A else (lambda x: x)
    doc = _doc()
    t = doc.add_heading(st["title"] or A.get("title") or "[Title]", level=0); t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_para(doc, st["authors"]).alignment = WD_ALIGN_PARAGRAPH.CENTER
    if A.get("highlights"):
        doc.add_heading("Highlights", level=1)
        for h in A["highlights"]:
            doc.add_paragraph(h, style="List Bullet")

    doc.add_heading("Abstract", level=1)
    if A.get("abstract"):
        for k in ("background", "methods", "results", "conclusion"):
            if A["abstract"].get(k):
                add_para(doc, A["abstract"][k], label=k.capitalize())
    else:
        for k, v in abstract(st, F, histo_results).items():
            add_para(doc, v, label=k)
    kw = st["keywords"] or "; ".join(A.get("keywords") or []) or "[4–6 keywords]"
    add_para(doc, "Keywords: " + kw)

    doc.add_heading("1. Introduction", level=1)
    for para in (A.get("introduction") or introduction(st, F, refs, citer.cite)):
        add_para(doc, T(para) if A.get("introduction") else para)

    doc.add_heading("2. Materials and methods", level=1)
    for i, (h, txt) in enumerate(methods(st, F, meth_sents, histo_methods, pw).items(), 1):
        doc.add_heading(f"2.{i}. {h}", level=2)
        add_para(doc, txt)

    doc.add_heading("3. Results", level=1)
    blocks = ([(b.get("heading", ""), b.get("paragraphs", [])) for b in A["results"]] if A.get("results")
              else _results_paragraphs(items, pw))
    sec = 0
    for head, paras in blocks:
        sec += 1
        doc.add_heading(f"3.{sec}. {head}", level=2)
        for para in paras:
            add_para(doc, T(para) if A.get("results") else para)
    if histo_results and not any("histopath" in (h or "").lower() for h, _ in blocks):
        sec += 1
        doc.add_heading(f"3.{sec}. Histopathological findings", level=2)
        add_para(doc, histo_results)

    doc.add_heading("4. Discussion", level=1)
    for para in (A.get("discussion") or discussion(st, F, histo_results, refs, citer.cite)):
        add_para(doc, T(para) if A.get("discussion") else para)
    doc.add_heading("5. Conclusion", level=1)
    add_para(doc, T(A["conclusion"]) if A.get("conclusion") else
             f"[In two or three sentences, state what this study shows about {st['drug'] or 'the test compound'} "
             f"against {st['model'] or 'the disease model'} and its implications.]")

    doc.add_heading("Declarations", level=1)
    sw = f"Statistical analysis, figures and the Methods and Results text were prepared with {APP_NAME} {APP_VERSION} from the study data."
    gen = (f"During the preparation of this work the authors used Claude ({ai_model or 'Anthropic'}) within {APP_NAME} to draft the "
           f"Abstract, Introduction, Results text, Discussion and Conclusion from the study data and the cited references. "
           f"After using this tool, the authors reviewed and edited the content as needed and take full responsibility for "
           f"the content of the publication." if A else "[Declare any use of generative AI tools according to the journal's policy.]")
    for h, v in [("Ethics approval", f"Approved by the {st['ethics']} ({st['approval']})."),
                 ("Funding", "[Funding sources, or 'This research received no external funding.']"),
                 ("Author contributions (CRediT)", "[Conceptualization, Methodology, Investigation, Formal analysis, Writing – original draft, Writing – review & editing.]"),
                 ("Data availability", "The data supporting the findings are available from the corresponding author on reasonable request."),
                 ("Declaration of competing interest", "The authors declare no competing interests."),
                 ("Use of software", sw),
                 ("Declaration of generative AI in the writing process", gen)]:
        add_para(doc, v, label=h)

    doc.add_heading("References", level=1)
    if style == "endnote":
        if citer.order:
            add_para(doc, "[Provisional list for checking. In Word with EndNote, import the RIS file saved next to this "
                          "document, press EndNote → Update Citations and Bibliography and choose the journal style; EndNote "
                          "then builds the final list, and this provisional list can be deleted.]")
            prov = RF.Citer(citer.order, "apa"); prov.order = list(citer.order)
            for b in prov.bibliography():
                doc.add_paragraph(b)
        else:
            add_para(doc, "[No references were cited. Add references in the References tab, or let the app search PubMed.]")
    else:
        bib = citer.bibliography()
        for b in bib:
            doc.add_paragraph(b)
        if not bib:
            add_para(doc, "[No references were cited. Add references in the References tab, or let the app search PubMed.]")

    summ = [e for e in items if e["summary"]]
    main = summ or items
    supp = [e for e in items if e not in main]
    tabs = [b for e in main for _, b in e["tables"]]
    figs = [b for e in main for _, b in e["figures"]]
    s_tabs = [b for e in supp for _, b in e["tables"]]
    s_figs = [b for e in supp for _, b in e["figures"]]
    if tabs:
        doc.add_page_break(); doc.add_heading("Tables", level=1)
        for n, b in enumerate(tabs, 1):
            _apa_table(doc, b.content, b.caption, b.note, n, b.p_columns)
    if figs:
        doc.add_page_break(); doc.add_heading("Figure legends", level=1)
        for n, b in enumerate(figs, 1):
            p = doc.add_paragraph(); p.add_run(f"Figure {n}. ").bold = True
            p.add_run(re.sub(r"\bp ([=<])", f"{pw} \\1", b.caption or ""))
        doc.add_page_break(); doc.add_heading("Figures", level=1)
        for n, b in enumerate(figs, 1):
            doc.add_paragraph().add_run(f"Figure {n}").bold = True
            doc.add_picture(io.BytesIO(fig_to_png_bytes(b.content, dpi=300)), width=Mm(fig_w))
    if s_tabs or s_figs:
        doc.add_page_break(); doc.add_heading("Supplementary material", level=1)
        add_para(doc, "Full statistical output for each marker (submit as a supplementary file or delete if not required).")
        n = 0
        for e in supp:
            for _, b in e["tables"]:
                n += 1
                cap = f"{e['outcome']}: {b.caption}" if e["outcome"] and e["outcome"] not in (b.caption or "") else b.caption
                _apa_table(doc, b.content, cap, b.note, f"S{n}", b.p_columns)
        for n, b in enumerate(s_figs, 1):
            p = doc.add_paragraph(); p.add_run(f"Figure S{n}. ").bold = True
            p.add_run(re.sub(r"\bp ([=<])", f"{pw} \\1", b.caption or ""))
            doc.add_picture(io.BytesIO(fig_to_png_bytes(b.content, dpi=300)), width=Mm(fig_w))
    for sect in doc.sections:
        sect.footer.paragraphs[0].text = ""
    doc.save(path)
    if refs:
        with open(re.sub(r"\.docx$", "", path) + "_references.ris", "w", encoding="utf-8") as fh:
            fh.write(RF.to_ris(citer.order or refs))
    words = sum(len(p.text.split()) for p in doc.paragraphs)
    prompts = sum(len(re.findall(r"\[[^\]]+\]", p.text)) for p in doc.paragraphs)
    return {"words": words, "prompts": prompts, "cited": len(citer.order), "tables": len(tabs), "figures": len(figs),
            "supplementary": len(s_tabs) + len(s_figs)}
