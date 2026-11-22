"""References: PubMed search (NCBI E-utilities), RIS import/export for EndNote, and citation formatting.

EndNote: citations are written into the Word file as EndNote *temporary citations* ``{Author, Year}``. When the file is
opened in Word with EndNote installed and "Update Citations and Bibliography" is pressed, EndNote finds each
reference in the user's library (import the RIS file written alongside first) and formats citations and the
reference list in the journal's style. Without EndNote, the same file can be built with numbered (Vancouver) or
author–year (APA/Harvard) citations and a formatted reference list."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
STYLES = {"endnote": "EndNote temporary citations {Author, Year}", "vancouver": "Numbered (Vancouver)",
          "apa": "Author–year (APA / Harvard)"}


@dataclass
class Ref:
    authors: list = field(default_factory=list)     # "Surname AB"
    year: str = ""
    title: str = ""
    journal: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    pmid: str = ""
    abstract: str = ""
    keywords: list = field(default_factory=list)

    @property
    def first_surname(self):
        return (self.authors[0].split(" ")[0] if self.authors else "Anonymous").strip(",")

    def key(self):
        return self.pmid or self.doi or f"{self.first_surname}{self.year}{self.title[:20]}"

    def to_dict(self):
        return asdict(self)


# ----------------------------------------------------------------------------- PubMed


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "MedStatixPro/2 (desktop statistics app)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def pubmed_search(query: str, n: int = 20, getter=_get) -> list[Ref]:
    """Search PubMed and return references (with abstracts). `getter` is injectable for tests."""
    q = urllib.parse.urlencode({"db": "pubmed", "term": query, "retmax": n, "retmode": "json", "sort": "relevance"})
    ids = json.loads(getter(EUTILS + "esearch.fcgi?" + q))["esearchresult"].get("idlist", [])
    if not ids:
        return []
    xml = getter(EUTILS + "efetch.fcgi?" + urllib.parse.urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}))
    return parse_pubmed_xml(xml)


def parse_pubmed_xml(xml: str) -> list[Ref]:
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml)
    out = []
    for art in root.iter("PubmedArticle"):
        mc = art.find("MedlineCitation"); a = mc.find("Article")
        authors = []
        for au in a.findall("AuthorList/Author"):
            ln, ini = au.findtext("LastName"), au.findtext("Initials")
            if ln:
                authors.append(f"{ln} {ini or ''}".strip())
            elif au.findtext("CollectiveName"):
                authors.append(au.findtext("CollectiveName"))
        ji = a.find("Journal/JournalIssue")
        year = (ji.findtext("PubDate/Year") or (ji.findtext("PubDate/MedlineDate") or "")[:4]) if ji is not None else ""
        abstract = " ".join("".join(t.itertext()) for t in a.findall("Abstract/AbstractText"))
        doi = ""
        for idn in art.findall("PubmedData/ArticleIdList/ArticleId"):
            if idn.get("IdType") == "doi":
                doi = idn.text or ""
        out.append(Ref(authors=authors, year=year, title="".join(a.find("ArticleTitle").itertext()).rstrip("."),
                       journal=a.findtext("Journal/ISOAbbreviation") or a.findtext("Journal/Title") or "",
                       volume=ji.findtext("Volume") if ji is not None else "", issue=ji.findtext("Issue") if ji is not None else "",
                       pages=a.findtext("Pagination/MedlinePgn") or "", doi=doi, pmid=mc.findtext("PMID") or "",
                       abstract=abstract, keywords=[k.text for k in mc.findall("KeywordList/Keyword") if k.text]))
    return out


# ----------------------------------------------------------------------------- RIS


def to_ris(refs: list[Ref]) -> str:
    lines = []
    for r in refs:
        lines.append("TY  - JOUR")
        lines += [f"AU  - {a.split(' ')[0]}, {' '.join(a.split(' ')[1:])}".rstrip(", ") for a in r.authors]
        for tag, v in (("PY", r.year), ("TI", r.title), ("JO", r.journal), ("VL", r.volume), ("IS", r.issue),
                       ("DO", r.doi), ("AB", r.abstract)):
            if v:
                lines.append(f"{tag}  - {v}")
        if r.pages:
            sp, _, ep = r.pages.partition("-")
            lines.append(f"SP  - {sp}")
            if ep:
                lines.append(f"EP  - {ep}")
        if r.pmid:
            lines.append(f"AN  - {r.pmid}")
        lines += [f"KW  - {k}" for k in r.keywords]
        lines.append("ER  - ")
        lines.append("")
    return "\n".join(lines)


def from_ris(text: str) -> list[Ref]:
    refs, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])  -\s?(.*)$", line)
        if not m:
            continue
        tag, v = m.group(1), m.group(2).strip()
        if tag == "TY":
            cur = Ref()
        elif cur is None:
            continue
        elif tag == "ER":
            refs.append(cur); cur = None
        elif tag in ("AU", "A1"):
            sur, _, ini = v.partition(",")
            words = ini.replace(".", " ").split()
            inits = "".join(w if (w.isupper() and len(w) <= 3) else w[0] for w in words)   # "AM", "A. M." or "Ahmed M"
            cur.authors.append(f"{sur.strip()} {inits}".strip())
        elif tag in ("PY", "Y1", "DA") and not cur.year:
            cur.year = v[:4]
        elif tag in ("TI", "T1"):
            cur.title = v.rstrip(".")
        elif tag in ("JO", "JF", "T2", "JA") and not cur.journal:
            cur.journal = v
        elif tag == "VL":
            cur.volume = v
        elif tag == "IS":
            cur.issue = v
        elif tag == "SP":
            cur.pages = v
        elif tag == "EP":
            cur.pages += "-" + v
        elif tag == "DO":
            cur.doi = v
        elif tag == "AN":
            cur.pmid = v
        elif tag == "AB":
            cur.abstract = v
        elif tag == "KW":
            cur.keywords.append(v)
    return refs


# ----------------------------------------------------------------------------- citing


class Citer:
    """Keeps citation order and formats in-text citations and the reference list."""

    def __init__(self, refs: list[Ref], style="endnote"):
        self.refs = list(refs); self.style = style; self.order = []

    def cite(self, refs: list[Ref]) -> str:
        refs = [r for r in refs if r is not None]
        if not refs:
            return ""
        for r in refs:
            if r.key() not in [x.key() for x in self.order]:
                self.order.append(r)
        if self.style == "endnote":
            return "".join("{" + f"{r.first_surname}, {r.year}" + "}" for r in refs)
        if self.style == "vancouver":
            nums = sorted(1 + [x.key() for x in self.order].index(r.key()) for r in refs)
            return "[" + _ranges(nums) + "]"
        parts = []
        for r in refs:
            n = len(r.authors)
            who = r.first_surname + (" et al." if n > 2 else (f" and {r.authors[1].split(' ')[0]}" if n == 2 else ""))
            parts.append(f"{who}, {r.year}")
        return "(" + "; ".join(parts) + ")"

    def bibliography(self) -> list[str]:
        if self.style == "endnote":
            return []            # EndNote builds it
        items = self.order if self.style == "vancouver" else sorted(self.order, key=lambda r: (r.first_surname, r.year))
        out = []
        for i, r in enumerate(items, 1):
            au = ", ".join(r.authors[:6]) + (", et al." if len(r.authors) > 6 else "")
            src = f"{r.journal}. {r.year};{r.volume}" + (f"({r.issue})" if r.issue else "") + (f":{r.pages}" if r.pages else "")
            if self.style == "vancouver":
                out.append(f"{i}. {au}. {r.title}. {src}." + (f" doi:{r.doi}" if r.doi else ""))
            else:
                out.append(f"{au} ({r.year}). {r.title}. {r.journal}, {r.volume}" + (f"({r.issue})" if r.issue else "")
                           + (f", {r.pages}" if r.pages else "") + "." + (f" https://doi.org/{r.doi}" if r.doi else ""))
        return out


def _ranges(nums):
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else (f"{nums[i]},{nums[j]}" if j == i + 1 else f"{nums[i]}–{nums[j]}"))
        i = j + 1
    return ",".join(out)


def best(refs: list[Ref], terms: list[str], k=2, used=None) -> list[Ref]:
    """References whose title/abstract/keywords mention the most of `terms` (case-insensitive), at most k."""
    ex = []
    for t in terms:                      # "modified citrus pectin (MCP)" → itself, "modified citrus pectin", "MCP"
        if not t:
            continue
        ex.append(t)
        m = re.match(r"^(.*?)\s*\(([^()]+)\)\s*$", t)
        if m:
            ex += [m.group(1), m.group(2)]
    terms = list(dict.fromkeys(t.lower().strip() for t in ex if t and len(t.strip()) > 2))
    if not terms:
        return []
    scored = []
    for r in refs:
        txt = " ".join([r.title, r.abstract, " ".join(r.keywords)]).lower()
        s = sum(2 * (t in r.title.lower()) + (t in txt) for t in terms)
        if s:
            scored.append((s - (0.5 if used and r.key() in used else 0), r))
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:k]]
