"""Format a Word manuscript the way EndNote's "Format Bibliography / Update Citations" does.

Write citations in your Word file as temporary citations, in any of the forms EndNote uses:
    {Hassan, 2021}   {Hassan et al., 2021}   {Hassan, 2021 #12}   {#12}   {Hassan, 2021 #12; Omar, 2019 #7}
(#12 is the record number in the reference library; Copy citation in the library puts it on the clipboard.)
The app finds each reference in the library, writes the citations in the chosen journal style (numbers in order of
first citation, or author-year with 2020a/2020b) and inserts the formatted reference list under the "References"
heading, or at the end. The original file is never changed: a new "…_formatted.docx" is written."""
from __future__ import annotations

import re

from . import styles as ST

CIT = re.compile(r"\{([^{}]*?\d{4}[a-z]?[^{}]*|#\d+(?:\s*;\s*#\d+)*)\}")
ONE = re.compile(r"^\s*(?:(?P<au>[^,#;]+?)\s*,\s*(?P<yr>\d{4}[a-z]?))?\s*(?:#(?P<rec>\d+))?\s*$")
HEADS = ("references", "reference list", "bibliography", "literature cited", "المراجع")


def parse_temp(text: str) -> list[tuple[str, str, str]]:
    out = []
    for part in text.split(";"):
        m = ONE.match(part.replace(" ", " "))
        if m and (m.group("rec") or m.group("au")):
            out.append(((m.group("au") or "").strip(), m.group("yr") or "", m.group("rec") or ""))
    return out


def _all_paragraphs(doc):
    for p in doc.paragraphs:
        yield p
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    yield p


def _replace_span(paragraph, start, end, new_text):
    """Replace characters [start, end) of the paragraph's text with new_text, across runs, keeping run formatting."""
    pos = 0
    first = True
    for run in paragraph.runs:
        t = run.text
        a, b = pos, pos + len(t)
        pos = b
        if b <= start or a >= end:
            continue
        s0, s1 = max(start, a) - a, min(end, b) - a
        if first:
            run.text = t[:s0] + new_text + t[s1:]
            first = False
        else:
            run.text = t[:s0] + t[s1:]


def format_document(src: str, dst: str, library, style_id: str, heading="References") -> dict:
    from docx import Document
    doc = Document(src)
    items_by_rec, unmatched = {}, []
    found = []                                    # (paragraph, start, end, [record ids])
    for p in _all_paragraphs(doc):
        txt = "".join(r.text for r in p.runs)
        for m in CIT.finditer(txt):
            recs = []
            for au, yr, rec in parse_temp(m.group(1)):
                rid = library.match_citation(au, yr, rec)
                if rid is None:
                    unmatched.append("{" + ", ".join(x for x in (au, yr) if x) + (f" #{rec}" if rec else "") + "}")
                else:
                    recs.append(rid)
            if recs:
                found.append((p, m.start(), m.end(), recs))
    for _, _, _, recs in found:
        for r in recs:
            if r not in items_by_rec:
                items_by_rec[r] = library.get(r)
    if not found:
        return {"citations": 0, "references": 0, "unmatched": sorted(set(unmatched)), "path": ""}
    citer = ST.CslCiter(list(items_by_rec.values()), style_id)
    tokens = []
    for p, s, e, recs in found:
        tokens.append((p, s, e, citer.cite_ids([f"r{r}" for r in dict.fromkeys(recs)])))
    by_par = {}
    for p, s, e, tok in tokens:
        by_par.setdefault(id(p), (p, []))[1].append((s, e, tok))
    for p, spans in by_par.values():          # right to left so earlier offsets stay valid
        for s, e, tok in sorted(spans, key=lambda x: -x[0]):
            _replace_span(p, s, e, tok)
    rendered = citer.render()
    for p in _all_paragraphs(doc):
        ST.replace_tokens(p, rendered)
    _insert_bibliography(doc, citer.bibliography_html(), heading)
    doc.save(dst)
    return {"citations": len(tokens), "references": len(citer.order), "unmatched": sorted(set(unmatched)), "path": dst}


def _insert_bibliography(doc, entries, heading):
    from copy import deepcopy
    target = None
    for p in doc.paragraphs:
        if p.text.strip().lower().rstrip(":") in HEADS:
            target = p
    if target is None:
        target = doc.add_paragraph(heading, style="Heading 1") if "Heading 1" in [s.name for s in doc.styles] else doc.add_paragraph(heading)
        if target.runs:
            target.runs[0].bold = True
    anchor = target._p
    from docx.text.paragraph import Paragraph
    for h in entries:
        newp = deepcopy(anchor)
        for child in list(newp):
            if child.tag.endswith("}r") or child.tag.endswith("}hyperlink"):
                newp.remove(child)
        anchor.addnext(newp); anchor = newp
        para = Paragraph(newp, target._parent)
        try:
            para.style = doc.styles["Normal"]
        except KeyError:
            pass
        ST.add_html(para, h)
