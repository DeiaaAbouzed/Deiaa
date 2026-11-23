"""Reference formats. Internally every reference is a CSL-JSON item (the format citation styles are written for).

Import: RIS (EndNote, Google Scholar, Scopus, Web of Science, Mendeley, Zotero), EndNote tagged (.enw, Google Scholar
"Import into EndNote"), EndNote XML, BibTeX (Google Scholar, Zotero, JabRef), PubMed/MEDLINE (.nbib/.txt), Scopus CSV,
CSL-JSON. Export: RIS, EndNote XML, BibTeX, CSL-JSON."""
from __future__ import annotations

import csv
import html
import io
import json
import re
import xml.etree.ElementTree as ET

RIS_TYPES = {"JOUR": "article-journal", "JFULL": "article-journal", "ABST": "article-journal", "EJOUR": "article-journal",
             "BOOK": "book", "EBOOK": "book", "EDBOOK": "book", "CHAP": "chapter", "ECHAP": "chapter",
             "CONF": "paper-conference", "CPAPER": "paper-conference", "THES": "thesis", "RPRT": "report",
             "ELEC": "webpage", "WEB": "webpage", "PAT": "patent", "GEN": "article", "NEWS": "article-newspaper",
             "MGZN": "article-magazine", "DATA": "dataset", "STAND": "standard"}
CSL_TO_RIS = {"article-journal": "JOUR", "book": "BOOK", "chapter": "CHAP", "paper-conference": "CONF", "thesis": "THES",
              "report": "RPRT", "webpage": "ELEC", "patent": "PAT", "article-newspaper": "NEWS", "article-magazine": "MGZN",
              "dataset": "DATA", "article": "GEN"}
EN_TYPES = {"Journal Article": "article-journal", "Book": "book", "Book Section": "chapter", "Edited Book": "book",
            "Conference Paper": "paper-conference", "Conference Proceedings": "paper-conference", "Thesis": "thesis",
            "Report": "report", "Web Page": "webpage", "Electronic Article": "article-journal", "Patent": "patent",
            "Newspaper Article": "article-newspaper", "Magazine Article": "article-magazine", "Dataset": "dataset"}
CSL_TO_EN = {v: k for k, v in reversed(list(EN_TYPES.items()))}
EN_TYPE_NUM = {"Journal Article": 17, "Book": 6, "Book Section": 5, "Conference Paper": 47, "Thesis": 32, "Report": 27,
               "Web Page": 12, "Patent": 25, "Newspaper Article": 23, "Magazine Article": 19, "Dataset": 59}
BIB_TYPES = {"article": "article-journal", "book": "book", "incollection": "chapter", "inbook": "chapter",
             "inproceedings": "paper-conference", "conference": "paper-conference", "phdthesis": "thesis",
             "mastersthesis": "thesis", "techreport": "report", "misc": "article", "online": "webpage"}
CSL_TO_BIB = {"article-journal": "article", "book": "book", "chapter": "incollection", "paper-conference": "inproceedings",
              "thesis": "phdthesis", "report": "techreport", "webpage": "misc"}


# ----------------------------------------------------------------------------- small helpers


def person(text: str) -> dict:
    """'Hassan, Ahmed M.' / 'Hassan AM' / 'Ahmed M. Hassan' → {'family': 'Hassan', 'given': 'Ahmed M.'}."""
    t = re.sub(r"\s+", " ", (text or "").strip().strip(","))
    if not t:
        return {}
    if "," in t:
        fam, _, giv = t.partition(",")
        return {"family": fam.strip(), "given": giv.strip()} if giv.strip() else {"family": fam.strip()}
    parts = t.split(" ")
    if len(parts) >= 2 and re.fullmatch(r"[A-Z]{1,4}", parts[-1]):          # MEDLINE style: Hassan AM
        return {"family": " ".join(parts[:-1]), "given": " ".join(parts[-1])}
    if len(parts) >= 2:
        return {"family": parts[-1], "given": " ".join(parts[:-1])}
    return {"family": t}


def person_text(p: dict) -> str:
    if p.get("literal"):
        return p["literal"]
    return p.get("family", "") + (", " + p["given"] if p.get("given") else "")


def year_of(item: dict) -> str:
    try:
        return str(item["issued"]["date-parts"][0][0])
    except (KeyError, IndexError, TypeError):
        r = (item.get("issued") or {}).get("raw", "") if isinstance(item.get("issued"), dict) else ""
        m = re.search(r"(1[89]|20)\d\d", r or "")
        return m.group(0) if m else ""


def set_year(item: dict, text: str):
    m = re.search(r"(1[5-9]|20)\d\d", str(text or ""))
    if m:
        parts = [int(m.group(0))]
        mm = re.search(r"(?:^|[/-])(\d{1,2})(?:[/-](\d{1,2}))?", str(text)[m.end():])
        if mm and 1 <= int(mm.group(1)) <= 12:
            parts.append(int(mm.group(1)))
            if mm.group(2) and 1 <= int(mm.group(2)) <= 31:
                parts.append(int(mm.group(2)))
        item["issued"] = {"date-parts": [parts]}


def first_author(item: dict) -> str:
    a = item.get("author") or item.get("editor") or []
    return (a[0].get("family") or a[0].get("literal") or "") if a else ""


def clean(item: dict) -> dict:
    out = {k: v for k, v in item.items() if v not in (None, "", [], {})}
    out.setdefault("type", "article-journal")
    for k in ("title", "container-title", "abstract"):
        if isinstance(out.get(k), str):
            out[k] = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", out[k]))).strip()
    if out.get("title"):
        out["title"] = out["title"].rstrip(".")
    if out.get("DOI"):
        out["DOI"] = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", out["DOI"].strip(), flags=re.I)
    return out


def key(item: dict) -> str:
    """Identity used to detect duplicates: DOI, else PMID, else normalised title + year."""
    if item.get("DOI"):
        return "doi:" + item["DOI"].lower()
    if item.get("PMID"):
        return "pmid:" + str(item["PMID"])
    return "t:" + re.sub(r"[^a-z0-9]", "", (item.get("title") or "").lower())[:80] + year_of(item)


# ----------------------------------------------------------------------------- RIS


def from_ris(text: str) -> list[dict]:
    items, cur, last = [], None, None
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])  -\s?(.*)$", line.rstrip("\r"))
        if not m:
            if cur is not None and last in ("AB", "N2") and line.strip():
                cur["abstract"] = cur.get("abstract", "") + " " + line.strip()
            continue
        tag, v = m.group(1), m.group(2).strip()
        last = tag
        if tag == "TY":
            cur = {"type": RIS_TYPES.get(v, "article-journal")}
            continue
        if cur is None:
            continue
        if tag == "ER":
            items.append(clean(cur)); cur = None
        elif tag in ("AU", "A1"):
            cur.setdefault("author", []).append(person(v))
        elif tag in ("A2", "ED"):
            cur.setdefault("editor", []).append(person(v))
        elif tag in ("PY", "Y1", "DA") and "issued" not in cur:
            set_year(cur, v)
        elif tag in ("TI", "T1"):
            cur["title"] = v
        elif tag in ("T2", "JF", "JO", "BT") and "container-title" not in cur:
            cur["container-title"] = v
        elif tag in ("JA", "J2"):
            cur["container-title-short"] = v
            cur.setdefault("container-title", v)
        elif tag == "VL":
            cur["volume"] = v
        elif tag == "IS":
            cur["issue"] = v
        elif tag == "SP":
            cur["page"] = v
        elif tag == "EP":
            cur["page"] = cur.get("page", "") + "-" + v if cur.get("page") and "-" not in cur.get("page", "") else cur.get("page", v)
        elif tag == "DO":
            cur["DOI"] = v
        elif tag in ("AN", "C2") and re.fullmatch(r"\d{5,9}", v):
            cur["PMID"] = v
        elif tag in ("AB", "N2"):
            cur["abstract"] = (cur.get("abstract", "") + " " + v).strip()
        elif tag == "KW":
            cur["keyword"] = (cur.get("keyword", "") + "; " + v).strip("; ")
        elif tag == "SN":
            cur["ISSN"] = v
        elif tag in ("UR", "L2") and "URL" not in cur:
            cur["URL"] = v
            mm = re.search(r"10\.\d{4,9}/\S+", v)
            if mm and "DOI" not in cur:
                cur["DOI"] = mm.group(0)
        elif tag == "PB":
            cur["publisher"] = v
        elif tag == "CY":
            cur["publisher-place"] = v
        elif tag == "LA":
            cur["language"] = v
        elif tag == "N1":
            cur["note"] = (cur.get("note", "") + " " + v).strip()
    return items


def to_ris(items: list[dict]) -> str:
    L = []
    for it in items:
        L.append(f"TY  - {CSL_TO_RIS.get(it.get('type'), 'JOUR')}")
        L += [f"AU  - {person_text(a)}" for a in it.get("author", [])]
        L += [f"A2  - {person_text(a)}" for a in it.get("editor", [])]
        for tag, k in (("TI", "title"), ("T2", "container-title"), ("J2", "container-title-short"), ("VL", "volume"),
                       ("IS", "issue"), ("DO", "DOI"), ("SN", "ISSN"), ("UR", "URL"), ("PB", "publisher"),
                       ("CY", "publisher-place"), ("LA", "language"), ("AB", "abstract"), ("N1", "note")):
            if it.get(k):
                L.append(f"{tag}  - {it[k]}")
        y = year_of(it)
        if y:
            L.append(f"PY  - {y}")
        if it.get("page"):
            sp, _, ep = str(it["page"]).replace("–", "-").partition("-")
            L.append(f"SP  - {sp}")
            if ep:
                L.append(f"EP  - {ep}")
        if it.get("PMID"):
            L.append(f"AN  - {it['PMID']}")
        L += [f"KW  - {k.strip()}" for k in str(it.get("keyword", "")).split(";") if k.strip()]
        L += ["ER  - ", ""]
    return "\n".join(L)


# ----------------------------------------------------------------------------- EndNote tagged (.enw) and MEDLINE


def from_enw(text: str) -> list[dict]:
    items, cur = [], None
    for line in text.splitlines() + [""]:
        m = re.match(r"^%(\S)\s+(.*)$", line.strip())
        if not m:
            if not line.strip() and cur:
                items.append(clean(cur)); cur = None
            continue
        tag, v = m.group(1), m.group(2).strip()
        cur = cur if cur is not None else {"type": "article-journal"}
        if tag == "0":
            cur["type"] = EN_TYPES.get(v, "article-journal")
        elif tag == "A":
            cur.setdefault("author", []).append(person(v))
        elif tag == "E":
            cur.setdefault("editor", []).append(person(v))
        elif tag == "T":
            cur["title"] = v
        elif tag in ("J", "B"):
            cur["container-title"] = v
        elif tag == "V":
            cur["volume"] = v
        elif tag == "N":
            cur["issue"] = v
        elif tag == "P":
            cur["page"] = v
        elif tag == "D":
            set_year(cur, v)
        elif tag == "R":
            cur["DOI"] = v
        elif tag == "X":
            cur["abstract"] = v
        elif tag == "K":
            cur["keyword"] = "; ".join(x.strip() for x in re.split(r"[\n;]", v) if x.strip())
        elif tag == "@":
            cur["ISSN"] = v
        elif tag == "U":
            cur["URL"] = v
        elif tag == "I":
            cur["publisher"] = v
        elif tag == "C":
            cur["publisher-place"] = v
        elif tag == "M" and re.fullmatch(r"\d{5,9}", v):
            cur["PMID"] = v
    return items


def from_medline(text: str) -> list[dict]:
    """PubMed 'Send to → Citation manager' (.nbib) / MEDLINE format."""
    items, cur, tag = [], None, None
    for line in text.splitlines() + [""]:
        m = re.match(r"^([A-Z]{2,4})\s*- (.*)$", line)
        if m:
            tag, v = m.group(1), m.group(2).strip()
        elif line.startswith("      ") and cur is not None and tag:
            v = line.strip()
            if tag in ("AB", "TI"):
                k = "abstract" if tag == "AB" else "title"
                cur[k] = cur.get(k, "") + " " + v
            continue
        else:
            if not line.strip() and cur:
                items.append(clean(cur)); cur = None
            continue
        if tag == "PMID":
            if cur:
                items.append(clean(cur))
            cur = {"type": "article-journal", "PMID": v}
            continue
        if cur is None:
            continue
        if tag == "TI":
            cur["title"] = v
        elif tag == "FAU":
            cur.setdefault("author", []).append(person(v))
        elif tag == "AU":
            cur.setdefault("_au", []).append(person(v))
        elif tag == "JT":
            cur["container-title"] = v
        elif tag == "TA":
            cur["container-title-short"] = v
        elif tag == "VI":
            cur["volume"] = v
        elif tag == "IP":
            cur["issue"] = v
        elif tag == "PG":
            cur["page"] = v
        elif tag == "DP":
            set_year(cur, v)
        elif tag == "AB":
            cur["abstract"] = v
        elif tag in ("AID", "LID") and v.endswith("[doi]"):
            cur["DOI"] = v.replace("[doi]", "").strip()
        elif tag == "IS" and "ISSN" not in cur:
            cur["ISSN"] = v.split(" ")[0]
        elif tag == "OT" or tag == "MH":
            cur["keyword"] = (cur.get("keyword", "") + "; " + v).strip("; ")
    out = []
    for it in items:
        au = it.pop("_au", [])
        if not it.get("author") and au:
            it["author"] = au
        out.append(it)
    return out


# ----------------------------------------------------------------------------- BibTeX


def _bib_fields(body: str) -> dict:
    out, i, n = {}, 0, len(body)
    while i < n:
        m = re.compile(r"\s*,?\s*([A-Za-z][\w-]*)\s*=\s*").match(body, i)
        if not m:
            break
        name, i = m.group(1).lower(), m.end()
        if i < n and body[i] == "{":
            depth, j = 0, i
            while j < n:
                depth += body[j] == "{"
                depth -= body[j] == "}"
                j += 1
                if depth == 0:
                    break
            val, i = body[i + 1:j - 1], j
        elif i < n and body[i] == '"':
            j = body.index('"', i + 1); val, i = body[i + 1:j], j + 1
        else:
            m2 = re.compile(r"[^,}]+").match(body, i); val, i = (m2.group(0) if m2 else ""), (m2.end() if m2 else i + 1)
        out[name] = re.sub(r"\s+", " ", re.sub(r"[{}]", "", val)).strip()
    return out


def from_bibtex(text: str) -> list[dict]:
    items = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,]*),", text):
        kind = m.group(1).lower()
        if kind in ("comment", "string", "preamble"):
            continue
        start, depth, j = m.end(), 1, m.end()
        while j < len(text) and depth:
            depth += text[j] == "{"; depth -= text[j] == "}"; j += 1
        f = _bib_fields(text[start:j - 1])
        it = {"type": BIB_TYPES.get(kind, "article-journal"), "title": f.get("title", ""),
              "container-title": f.get("journal") or f.get("booktitle") or f.get("journaltitle", ""),
              "volume": f.get("volume", ""), "issue": f.get("number", ""), "page": f.get("pages", "").replace("--", "-"),
              "DOI": f.get("doi", ""), "URL": f.get("url", ""), "abstract": f.get("abstract", ""),
              "publisher": f.get("publisher", ""), "ISSN": f.get("issn", ""), "keyword": f.get("keywords", "").replace(",", ";"),
              "PMID": f.get("pmid", "")}
        if f.get("author"):
            it["author"] = [person(a) for a in re.split(r"\s+and\s+", f["author"]) if a.strip()]
        if f.get("editor"):
            it["editor"] = [person(a) for a in re.split(r"\s+and\s+", f["editor"]) if a.strip()]
        set_year(it, f.get("year") or f.get("date", ""))
        items.append(clean(it))
    return items


def to_bibtex(items: list[dict]) -> str:
    out, used = [], set()
    for it in items:
        base = re.sub(r"[^A-Za-z]", "", first_author(it)) + year_of(it) or "ref"
        k, n = base, 1
        while k in used:
            n += 1; k = base + chr(96 + n)
        used.add(k)
        f = {"author": " and ".join(person_text(a) for a in it.get("author", [])), "title": it.get("title", ""),
             "journal": it.get("container-title", "") if it.get("type") == "article-journal" else "",
             "booktitle": it.get("container-title", "") if it.get("type") in ("chapter", "paper-conference") else "",
             "year": year_of(it), "volume": it.get("volume", ""), "number": it.get("issue", ""),
             "pages": str(it.get("page", "")).replace("-", "--"), "doi": it.get("DOI", ""), "pmid": it.get("PMID", ""),
             "publisher": it.get("publisher", ""), "url": it.get("URL", ""), "abstract": it.get("abstract", ""),
             "keywords": it.get("keyword", "")}
        body = ",\n".join(f"  {a} = {{{v}}}" for a, v in f.items() if v)
        out.append(f"@{CSL_TO_BIB.get(it.get('type'), 'article')}{{{k},\n{body}\n}}")
    return "\n\n".join(out) + "\n"


# ----------------------------------------------------------------------------- EndNote XML


def _t(el, path):
    x = el.find(path)
    return "".join(x.itertext()).strip() if x is not None else ""


def from_endnote_xml(text: str) -> list[dict]:
    root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    items = []
    for r in root.iter("record"):
        rt = r.find("ref-type")
        it = {"type": EN_TYPES.get(rt.get("name", "") if rt is not None else "", "article-journal"),
              "title": _t(r, "titles/title"),
              "container-title": _t(r, "titles/secondary-title") or _t(r, "periodical/full-title"),
              "container-title-short": _t(r, "periodical/abbr-1") or _t(r, "alt-periodical/full-title"),
              "volume": _t(r, "volume"), "issue": _t(r, "number"), "page": _t(r, "pages"),
              "DOI": _t(r, "electronic-resource-num"), "abstract": _t(r, "abstract"), "ISSN": _t(r, "isbn"),
              "publisher": _t(r, "publisher"), "publisher-place": _t(r, "pub-location"), "URL": _t(r, "urls/related-urls/url"),
              "note": _t(r, "notes"), "language": _t(r, "language")}
        an = _t(r, "accession-num")
        if re.fullmatch(r"\d{5,9}", an):
            it["PMID"] = an
        it["author"] = [person("".join(a.itertext())) for a in r.findall("contributors/authors/author")]
        ed = [person("".join(a.itertext())) for a in r.findall("contributors/secondary-authors/author")]
        if ed:
            it["editor"] = ed
        kws = ["".join(k.itertext()).strip() for k in r.findall("keywords/keyword")]
        it["keyword"] = "; ".join(k for k in kws if k)
        set_year(it, _t(r, "dates/year"))
        items.append(clean(it))
    return items


def to_endnote_xml(items: list[dict]) -> str:
    def s(v):
        return f'<style face="normal" font="default" size="100%">{html.escape(str(v))}</style>'
    out = ['<?xml version="1.0" encoding="UTF-8"?><xml><records>']
    for i, it in enumerate(items, 1):
        name = CSL_TO_EN.get(it.get("type"), "Journal Article")
        r = [f'<record><rec-number>{i}</rec-number><ref-type name="{name}">{EN_TYPE_NUM.get(name, 17)}</ref-type>',
             "<contributors><authors>" + "".join(f"<author>{s(person_text(a))}</author>" for a in it.get("author", [])) + "</authors>"
             + ("<secondary-authors>" + "".join(f"<author>{s(person_text(a))}</author>" for a in it.get("editor", [])) + "</secondary-authors>" if it.get("editor") else "")
             + "</contributors>",
             f"<titles><title>{s(it.get('title', ''))}</title><secondary-title>{s(it.get('container-title', ''))}</secondary-title></titles>",
             f"<periodical><full-title>{s(it.get('container-title', ''))}</full-title>"
             + (f"<abbr-1>{s(it['container-title-short'])}</abbr-1>" if it.get("container-title-short") else "") + "</periodical>"]
        for tag, k in (("pages", "page"), ("volume", "volume"), ("number", "issue"), ("isbn", "ISSN"), ("abstract", "abstract"),
                       ("electronic-resource-num", "DOI"), ("accession-num", "PMID"), ("publisher", "publisher"),
                       ("pub-location", "publisher-place"), ("notes", "note"), ("language", "language")):
            if it.get(k):
                r.append(f"<{tag}>{s(it[k])}</{tag}>")
        kws = [k.strip() for k in str(it.get("keyword", "")).split(";") if k.strip()]
        if kws:
            r.append("<keywords>" + "".join(f"<keyword>{s(k)}</keyword>" for k in kws) + "</keywords>")
        if year_of(it):
            r.append(f"<dates><year>{s(year_of(it))}</year></dates>")
        if it.get("URL"):
            r.append(f"<urls><related-urls><url>{s(it['URL'])}</url></related-urls></urls>")
        out.append("".join(r) + "</record>")
    out.append("</records></xml>")
    return "".join(out)


# ----------------------------------------------------------------------------- Scopus / Web of Science CSV


def from_csv(text: str) -> list[dict]:
    """Scopus 'Export → CSV' (also works for most citation-manager CSV exports)."""
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    items = []
    for r in rows:
        g = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
        au = g.get("author full names") or g.get("authors") or ""
        sep = ";" if ";" in au else ","
        authors = []
        for a in [x for x in au.split(sep) if x.strip()]:
            a = re.sub(r"\s*\(\d+\)\s*$", "", a.strip())
            authors.append(person(a.replace(".", ". ").strip()) if sep == ";" else person(a))
        it = {"type": "article-journal", "title": g.get("title", ""), "container-title": g.get("source title") or g.get("journal", ""),
              "volume": g.get("volume", ""), "issue": g.get("issue", ""),
              "page": "-".join(x for x in (g.get("page start", ""), g.get("page end", "")) if x) or g.get("pages", ""),
              "DOI": g.get("doi", ""), "abstract": g.get("abstract", ""), "keyword": g.get("author keywords", ""),
              "PMID": g.get("pubmed id", ""), "ISSN": g.get("issn", ""), "URL": g.get("link", ""), "author": authors,
              "publisher": g.get("publisher", "")}
        set_year(it, g.get("year", ""))
        if it["title"]:
            items.append(clean(it))
    return items


# ----------------------------------------------------------------------------- dispatch


def parse(text: str, name: str = "") -> list[dict]:
    """Recognise the format from the file name and the content."""
    n, t = name.lower(), text.lstrip("﻿ \n\r\t")
    if n.endswith(".json") or t.startswith("["):
        return [clean(x) for x in json.loads(t)]
    if n.endswith(".xml") or t.startswith("<?xml") or t.startswith("<xml"):
        return from_endnote_xml(t)
    if n.endswith(".bib") or re.match(r"@\w+\s*\{", t):
        return from_bibtex(t)
    if re.search(r"^TY  - ", t, re.M):
        return from_ris(t)
    if re.search(r"^PMID- ", t, re.M):
        return from_medline(t)
    if re.search(r"^%[0AT] ", t, re.M):
        return from_enw(t)
    if n.endswith(".csv") or ("Title" in t.split("\n", 1)[0] and "," in t.split("\n", 1)[0]):
        return from_csv(t)
    raise ValueError("Unrecognised reference file. Use RIS, EndNote XML, ENW, BibTeX, PubMed (MEDLINE/.nbib), CSV or CSL-JSON.")


def read_file(path: str) -> list[dict]:
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return parse(raw.decode(enc), path)
        except UnicodeDecodeError:
            continue
    return parse(raw.decode("utf-8", "replace"), path)


EXPORTERS = {"RIS (EndNote, Zotero, Mendeley)": (".ris", to_ris), "EndNote XML": (".xml", to_endnote_xml),
             "BibTeX": (".bib", to_bibtex), "CSL-JSON": (".json", lambda items: json.dumps(items, ensure_ascii=False, indent=1))}


# ----------------------------------------------------------------------------- bridge to the paper writer's Ref


def from_ref(r) -> dict:
    it = {"type": "article-journal", "title": r.title, "container-title": r.journal, "volume": r.volume, "issue": r.issue,
          "page": r.pages, "DOI": r.doi, "PMID": r.pmid, "abstract": r.abstract, "keyword": "; ".join(r.keywords),
          "author": [person(a) for a in r.authors]}
    set_year(it, r.year)
    return clean(it)


def to_ref(it: dict):
    from ..report.refs import Ref
    au = []
    for a in it.get("author", []):
        if a.get("literal"):
            au.append(a["literal"])
        else:
            ini = "".join(w[0] for w in re.split(r"[\s.\-]+", a.get("given", "")) if w)
            au.append(f"{a.get('family', '')} {ini}".strip())
    return Ref(authors=au, year=year_of(it), title=it.get("title", ""), journal=it.get("container-title-short") or it.get("container-title", ""),
               volume=str(it.get("volume", "")), issue=str(it.get("issue", "")), pages=str(it.get("page", "")), doi=it.get("DOI", ""),
               pmid=str(it.get("PMID", "")), abstract=it.get("abstract", ""),
               keywords=[k.strip() for k in str(it.get("keyword", "")).split(";") if k.strip()])
