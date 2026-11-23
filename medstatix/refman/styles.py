"""Journal output styles (Citation Style Language) and the formatting engine.

About 70 styles ship with the app (general styles plus the pharmacology/toxicology journals authors use most); any of the
10,000+ styles of the CSL repository can be downloaded by name, or loaded from a .csl file. Formatting is done by
citeproc-py; the HTML it returns (italic, bold, superscript) is turned into real Word formatting."""
from __future__ import annotations

import html
import os
import re
import urllib.request
import warnings
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "csl")
REPO = "https://raw.githubusercontent.com/citation-style-language/styles/master/"
NS = {"c": "http://purl.org/net/xbiblio/csl"}


def user_dir() -> str:
    from .library import default_path
    d = os.path.join(os.path.dirname(default_path()), "styles")
    os.makedirs(d, exist_ok=True)
    return d


def _info(path: str) -> dict:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return {}
    title = root.findtext("c:info/c:title", "", NS)
    cat = root.find("c:info/c:category[@citation-format]", NS)
    parent = root.find("c:info/c:link[@rel='independent-parent']", NS)
    return {"id": os.path.splitext(os.path.basename(path))[0], "title": title, "path": path,
            "format": cat.get("citation-format") if cat is not None else "",
            "parent": parent.get("href").rstrip("/").split("/")[-1] if parent is not None else ""}


def list_styles() -> list[dict]:
    """All available styles: bundled general, bundled journal (dependent) and user-added, sorted by title."""
    seen, out = set(), []
    for d in (user_dir(), HERE, os.path.join(HERE, "dependent")):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith(".csl") and f[:-4] not in seen:
                inf = _info(os.path.join(d, f))
                if inf.get("title"):
                    seen.add(inf["id"]); out.append(inf)
    return sorted(out, key=lambda s: s["title"].lower())


def find(style_id: str) -> dict:
    for d in (user_dir(), HERE, os.path.join(HERE, "dependent")):
        p = os.path.join(d, style_id + ".csl")
        if os.path.exists(p):
            return _info(p)
    raise KeyError(style_id)


def download(name_or_id: str, getter=None) -> dict:
    """Fetch a style from the CSL repository by id (e.g. 'toxicology-reports') and keep it with the user's styles."""
    sid = re.sub(r"[^a-z0-9-]+", "-", name_or_id.strip().lower()).strip("-")
    get = getter or (lambda u: urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "MedStatixPro"}),
                                                      timeout=20).read().decode("utf-8"))
    last = None
    for url in (REPO + sid + ".csl", REPO + "dependent/" + sid + ".csl"):
        try:
            txt = get(url)
        except Exception as e:      # noqa: BLE001
            last = e; continue
        if "<style" in txt:
            p = os.path.join(user_dir(), sid + ".csl")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(txt)
            inf = _info(p)
            if inf.get("parent"):
                try:
                    find(inf["parent"])
                except KeyError:
                    download(inf["parent"], getter)
            return inf
    raise ValueError(f"Style '{sid}' was not found in the CSL repository ({last}). Use the id shown on "
                     f"zotero.org/styles, e.g. 'food-and-chemical-toxicology'.")


def add_file(path: str) -> dict:
    import shutil
    dst = os.path.join(user_dir(), os.path.basename(path))
    shutil.copyfile(path, dst)
    inf = _info(dst)
    if not inf.get("title"):
        os.remove(dst); raise ValueError("This file is not a CSL style.")
    return inf


def _independent(style_id: str) -> tuple[str, dict]:
    inf = find(style_id)
    if inf.get("parent"):
        try:
            return find(inf["parent"])["path"], inf
        except KeyError:
            return download(inf["parent"])["path"], inf
    return inf["path"], inf


# ----------------------------------------------------------------------------- engine


def _flat(x) -> str:
    if isinstance(x, (list, tuple)):
        return "".join(_flat(y) for y in x)
    return str(x)


class CslCiter:
    """Same interface as report.refs.Citer, but formats with a CSL style.

    cite() returns a placeholder; render() formats every citation at once (so numbering and 2020a/2020b
    disambiguation are right) and returns {placeholder: html}; bibliography_html() gives the reference list."""

    def __init__(self, items: list[dict], style_id: str):
        from citeproc import CitationStylesBibliography, CitationStylesStyle, formatter
        from citeproc.source.json import CiteProcJSON
        path, self.info = _independent(style_id)
        self.items = {it["id"]: it for it in items}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.style = CitationStylesStyle(path, validate=False)
            self.bib = CitationStylesBibliography(self.style, CiteProcJSON(list(self.items.values())), formatter.html)
        self.clusters = []
        self.order = []
        self.numeric = (self.info.get("format") or _info(path).get("format")) in ("numeric",)
        self.html = True

    def cite_ids(self, ids) -> str:
        from citeproc import Citation, CitationItem
        ids = [i for i in ids if i in self.items]
        if not ids:
            return ""
        for i in ids:
            if i not in self.order:
                self.order.append(i)
        c = Citation([CitationItem(i) for i in ids])
        self.bib.register(c)
        self.clusters.append(c)
        return f"⟦CIT{len(self.clusters) - 1}⟧"

    def cite(self, refs) -> str:          # report.refs.Ref objects or CSL items
        ids = []
        for r in refs:
            if r is None:
                continue
            ids.append(r["id"] if isinstance(r, dict) else getattr(r, "_csl_id", None))
        return self.cite_ids([i for i in ids if i])

    def render(self) -> dict:
        out = {}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for n, c in enumerate(self.clusters):
                out[f"⟦CIT{n}⟧"] = _flat(self.bib.cite(c, lambda item: None))
        return out

    def bibliography_html(self) -> list[str]:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            entries = [_flat(e) for e in self.bib.bibliography()]
        fixed = []
        for e in entries:     # citeproc-py drops the gap after "1." / "[1]" in second-field layouts
            fixed.append(re.sub(r"^(\[?\d+[.\])]?)(?=[A-Za-z<])", r"\1 ", e))
        return fixed

    def bibliography(self) -> list[str]:
        return [plain(h) for h in self.bibliography_html()]


def format_items(items: list[dict], style_id: str) -> tuple[list[str], list[str]]:
    """Preview: in-text citation of each item alone, and the formatted reference list (HTML)."""
    c = CslCiter(items, style_id)
    toks = [c.cite_ids([it["id"]]) for it in items]
    r = c.render()
    return [r.get(t, "") for t in toks], c.bibliography_html()


def plain(h: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", h or ""))


# ----------------------------------------------------------------------------- HTML → Word runs


class _Runs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.out = [], []

    def handle_starttag(self, tag, attrs):
        st = dict(attrs).get("style", "") or ""
        self.stack.append({"i": tag in ("i", "em"), "b": tag in ("b", "strong"), "sup": tag == "sup", "sub": tag == "sub",
                           "sc": "small-caps" in st, "u": tag == "u" or "underline" in st})

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        f = {k: any(s[k] for s in self.stack) for k in ("i", "b", "sup", "sub", "sc", "u")}
        self.out.append((data, f))


def html_runs(h: str) -> list[tuple[str, dict]]:
    p = _Runs(); p.feed(h or ""); p.close()
    return [(t, f) for t, f in p.out if t]


def add_html(paragraph, h: str, base_run=None):
    """Append HTML-formatted text to a python-docx paragraph, copying the font of base_run if given."""
    runs = []
    for text, f in html_runs(h):
        r = paragraph.add_run(text)
        if base_run is not None:
            _copy_font(base_run, r)
        if f["i"]:
            r.italic = True
        if f["b"]:
            r.bold = True
        if f["sup"]:
            r.font.superscript = True
        if f["sub"]:
            r.font.subscript = True
        if f["sc"]:
            r.font.small_caps = True
        if f["u"]:
            r.underline = True
        runs.append(r)
    return runs


def _copy_font(src, dst):
    s, d = src.font, dst.font
    for a in ("name", "size", "bold", "italic", "underline", "color"):
        try:
            v = getattr(s, a)
            if a == "color":
                if s.color is not None and s.color.rgb is not None:
                    d.color.rgb = s.color.rgb
            elif v is not None:
                setattr(d, a, v)
        except (AttributeError, ValueError):
            pass
    try:
        if src.style is not None:
            dst.style = src.style
    except (AttributeError, ValueError):
        pass


def replace_tokens(paragraph, rendered: dict):
    """Swap the placeholders left by CslCiter.cite for formatted citations, keeping the surrounding run's formatting."""
    pat = re.compile("|".join(re.escape(k) for k in rendered)) if rendered else None
    if pat is None or not pat.search(paragraph.text):
        return
    from copy import deepcopy
    for run in list(paragraph.runs):
        if not pat.search(run.text):
            continue
        parts = pat.split(run.text)
        keys = pat.findall(run.text)
        for i, k in enumerate(keys):          # superscript citations sit directly after the word: "injury¹."
            if rendered[k].lstrip().startswith("<sup>"):
                parts[i] = parts[i].rstrip()
        run.text = parts[0]
        anchor = run._r
        for k, after in zip(keys, parts[1:]):
            tmp = paragraph.add_run("")
            new = add_html(paragraph, rendered[k], run)
            tmp._r.getparent().remove(tmp._r)
            for r in new:
                anchor.addnext(r._r); anchor = r._r
            if after:
                tail = deepcopy(run._r)
                anchor.addnext(tail); anchor = tail
                from docx.text.run import Run
                Run(tail, paragraph).text = after
