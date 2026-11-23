"""Online sources for the reference library.

PubMed (NCBI E-utilities), Crossref (every DOI-registered journal), OpenAlex (≈250 million works; the open index with
coverage closest to Google Scholar), Scopus (Elsevier Scopus Search API; needs the user's Elsevier API key, usually from
the university), DOI and PMID look-up. Google Scholar has no public interface for programs, so the library opens the
search in the browser and imports what Scholar exports ("Import into EndNote" .enw, RIS or BibTeX)."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from ..report import refs as RF
from . import formats as FM

UA = {"User-Agent": "MedStatixPro/2 (desktop reference manager)"}

SOURCES = {"pubmed": "PubMed", "scholar": "Google Scholar", "scopus": "Scopus", "openalex": "OpenAlex (Scholar-like, all fields)",
           "crossref": "Crossref (all DOI journals)"}


def _get(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def pubmed(query: str, n: int = 25, getter=None) -> list[dict]:
    refs = RF.pubmed_search(query, n, getter or RF._get)
    return [FM.from_ref(r) for r in refs]


def _crossref_item(w: dict) -> dict:
    it = {"type": {"journal-article": "article-journal", "book-chapter": "chapter", "book": "book",
                   "proceedings-article": "paper-conference", "posted-content": "article"}.get(w.get("type"), "article-journal"),
          "title": (w.get("title") or [""])[0], "container-title": (w.get("container-title") or [""])[0],
          "container-title-short": (w.get("short-container-title") or [""])[0], "volume": w.get("volume", ""),
          "issue": w.get("issue", ""), "page": w.get("page", ""), "DOI": w.get("DOI", ""), "publisher": w.get("publisher", ""),
          "ISSN": (w.get("ISSN") or [""])[0], "abstract": re.sub(r"<[^>]+>", "", w.get("abstract", "")),
          "author": [{"family": a.get("family", ""), "given": a.get("given", "")} if a.get("family") else {"literal": a.get("name", "")}
                     for a in w.get("author", [])]}
    dp = (w.get("issued") or w.get("published-print") or w.get("published-online") or {}).get("date-parts") or [[None]]
    if dp and dp[0] and dp[0][0]:
        it["issued"] = {"date-parts": [[x for x in dp[0] if x]]}
    return FM.clean(it)


def crossref(query: str, n: int = 25, getter=None) -> list[dict]:
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode({"query.bibliographic": query, "rows": n})
    data = json.loads((getter or _get)(url))
    return [_crossref_item(w) for w in data.get("message", {}).get("items", [])]


def _openalex_item(w: dict) -> dict:
    inv = w.get("abstract_inverted_index") or {}
    words = sorted(((p, t) for t, ps in inv.items() for p in ps))
    src = ((w.get("primary_location") or {}).get("source") or {})
    bib = w.get("biblio") or {}
    it = {"type": "article-journal" if w.get("type") in ("article", "review", None) else
          {"book-chapter": "chapter", "book": "book"}.get(w.get("type"), "article"),
          "title": w.get("title") or w.get("display_name") or "", "container-title": src.get("display_name", ""),
          "volume": bib.get("volume") or "", "issue": bib.get("issue") or "",
          "page": "-".join(x for x in (bib.get("first_page"), bib.get("last_page")) if x),
          "DOI": (w.get("doi") or "").replace("https://doi.org/", ""), "abstract": " ".join(t for _, t in words),
          "PMID": ((w.get("ids") or {}).get("pmid") or "").rstrip("/").split("/")[-1],
          "author": [FM.person((a.get("author") or {}).get("display_name", "")) for a in w.get("authorships", [])]}
    if w.get("publication_year"):
        it["issued"] = {"date-parts": [[w["publication_year"]]]}
    return FM.clean(it)


def openalex(query: str, n: int = 25, getter=None) -> list[dict]:
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode({"search": query, "per-page": n})
    data = json.loads((getter or _get)(url))
    return [_openalex_item(w) for w in data.get("results", [])]


def scopus(query: str, n: int = 25, api_key: str = "", insttoken: str = "", getter=None) -> list[dict]:
    if not api_key:
        raise ValueError("Scopus needs an Elsevier API key (dev.elsevier.com → I want an API key). Enter it in the "
                         "library settings. Scopus access usually works only from the university network.")
    q = query if re.search(r"[A-Z-]+\(", query) else f"TITLE-ABS-KEY({query})"
    url = "https://api.elsevier.com/content/search/scopus?" + urllib.parse.urlencode({"query": q, "count": min(n, 25)})
    h = {"X-ELS-APIKey": api_key, "Accept": "application/json"}
    if insttoken:
        h["X-ELS-Insttoken"] = insttoken
    data = json.loads((getter or (lambda u: _get(u, h)))(url))
    out = []
    for e in (data.get("search-results") or {}).get("entry", []):
        if "error" in e:
            continue
        it = {"title": e.get("dc:title", ""), "container-title": e.get("prism:publicationName", ""),
              "volume": e.get("prism:volume", ""), "issue": e.get("prism:issueIdentifier", ""),
              "page": e.get("prism:pageRange", "") or "", "DOI": e.get("prism:doi", ""), "PMID": e.get("pubmed-id", ""),
              "ISSN": e.get("prism:issn", ""), "author": [FM.person(e["dc:creator"])] if e.get("dc:creator") else [],
              "abstract": e.get("dc:description", "")}
        FM.set_year(it, e.get("prism:coverDate", ""))
        out.append(FM.clean(it))
    return out


def scholar_url(query: str) -> str:
    return "https://scholar.google.com/scholar?" + urllib.parse.urlencode({"q": query})


def doi(d: str, getter=None) -> dict:
    """Full metadata for a DOI (Crossref), e.g. to complete a Scopus or Scholar record that lists only the first author."""
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", d.strip(), flags=re.I)
    data = json.loads((getter or _get)("https://api.crossref.org/works/" + urllib.parse.quote(d)))
    return _crossref_item(data["message"])


def pmid(p: str, getter=None) -> dict:
    xml = (getter or RF._get)(RF.EUTILS + "efetch.fcgi?" + urllib.parse.urlencode({"db": "pubmed", "id": p.strip(), "retmode": "xml"}))
    refs = RF.parse_pubmed_xml(xml)
    if not refs:
        raise ValueError(f"PMID {p} was not found.")
    return FM.from_ref(refs[0])


def lookup(text: str, getter=None) -> dict:
    """A DOI or a PMID typed or pasted by the user."""
    t = text.strip()
    m = re.search(r"10\.\d{4,9}/\S+", t)
    if m:
        return doi(m.group(0).rstrip(".,;"), getter)
    if re.fullmatch(r"(PMID:?\s*)?\d{5,9}", t, re.I):
        return pmid(re.sub(r"\D", "", t), getter)
    raise ValueError("Enter a DOI (10.xxxx/…) or a PubMed ID.")


def search(source: str, query: str, n: int = 25, settings: dict | None = None, getter=None) -> list[dict]:
    s = settings or {}
    if source == "pubmed":
        return pubmed(query, n, getter)
    if source == "crossref":
        return crossref(query, n, getter)
    if source == "openalex":
        return openalex(query, n, getter)
    if source == "scopus":
        return scopus(query, n, s.get("scopus_key", ""), s.get("scopus_token", ""), getter)
    raise ValueError(source)
