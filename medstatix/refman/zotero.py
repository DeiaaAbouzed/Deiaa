"""Zotero: read the user's Zotero library (with its collections) into the MedStatix reference library.

Three ways, whichever the user has: the local database file (zotero.sqlite, read from a copy so Zotero can stay open),
Zotero 7's local API (Settings → Advanced → "Allow other applications on this computer to communicate with Zotero"),
or the Zotero web API (user ID + API key from zotero.org/settings/keys)."""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
import urllib.request

from . import formats as FM

TYPES = {"journalArticle": "article-journal", "book": "book", "bookSection": "chapter", "conferencePaper": "paper-conference",
         "thesis": "thesis", "report": "report", "webpage": "webpage", "patent": "patent", "newspaperArticle": "article-newspaper",
         "magazineArticle": "article-magazine", "preprint": "article", "dataset": "dataset", "document": "article"}
FIELDS = {"title": "title", "publicationTitle": "container-title", "bookTitle": "container-title",
          "proceedingsTitle": "container-title", "journalAbbreviation": "container-title-short", "volume": "volume",
          "issue": "issue", "pages": "page", "DOI": "DOI", "url": "URL", "abstractNote": "abstract", "ISSN": "ISSN",
          "ISBN": "ISBN", "publisher": "publisher", "place": "publisher-place", "language": "language", "university": "publisher",
          "institution": "publisher"}


def default_sqlite() -> str:
    for d in (os.path.join(os.path.expanduser("~"), "Zotero"),
              os.path.join(os.environ.get("APPDATA", ""), "Zotero", "Zotero")):
        p = os.path.join(d, "zotero.sqlite")
        if os.path.exists(p):
            return p
    return ""


def read_sqlite(path: str) -> list[tuple[dict, list[str]]]:
    """Return [(CSL item, [collection names])]. The database is copied first because Zotero keeps it locked."""
    tmp = os.path.join(tempfile.mkdtemp(), "z.sqlite")
    shutil.copyfile(path, tmp)
    db = sqlite3.connect(tmp)
    try:
        q = db.execute
        deleted = {r[0] for r in q("SELECT itemID FROM deletedItems")} if _has(db, "deletedItems") else set()
        items = {}
        for iid, tname in q("SELECT i.itemID, t.typeName FROM items i JOIN itemTypes t ON t.itemTypeID=i.itemTypeID"):
            if iid in deleted or tname in ("attachment", "note", "annotation"):
                continue
            items[iid] = {"type": TYPES.get(tname, "article-journal")}
        for iid, field, value in q("SELECT d.itemID, f.fieldName, v.value FROM itemData d JOIN fields f ON f.fieldID=d.fieldID "
                                   "JOIN itemDataValues v ON v.valueID=d.valueID"):
            it = items.get(iid)
            if it is None:
                continue
            if field == "date":
                FM.set_year(it, value)
            elif field == "extra":
                m = re.search(r"PMID:\s*(\d+)", str(value))
                if m:
                    it["PMID"] = m.group(1)
            elif field in FIELDS and FIELDS[field] not in it:
                it[FIELDS[field]] = value
        for iid, first, last, ctype in q("SELECT ic.itemID, c.firstName, c.lastName, ct.creatorType FROM itemCreators ic "
                                         "JOIN creators c ON c.creatorID=ic.creatorID JOIN creatorTypes ct "
                                         "ON ct.creatorTypeID=ic.creatorTypeID ORDER BY ic.itemID, ic.orderIndex"):
            it = items.get(iid)
            if it is None:
                continue
            p = {"family": last, "given": first} if first else {"literal": last}
            it.setdefault("editor" if ctype == "editor" else "author", []).append(p)
        cols = {}
        if _has(db, "collectionItems"):
            for iid, name in q("SELECT ci.itemID, c.collectionName FROM collectionItems ci JOIN collections c "
                               "ON c.collectionID=ci.collectionID"):
                cols.setdefault(iid, []).append(name)
        return [(FM.clean(it), cols.get(iid, [])) for iid, it in items.items() if it.get("title")]
    finally:
        db.close()
        shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)


def _has(db, table):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def read_api(user_id: str = "0", api_key: str = "", local: bool = True, getter=None, limit: int = 5000) -> list[dict]:
    """CSL-JSON from Zotero's local API (Zotero 7, user 0) or the web API."""
    base = "http://localhost:23119/api" if local else "https://api.zotero.org"
    out, start = [], 0
    get = getter or (lambda u: urllib.request.urlopen(urllib.request.Request(
        u, headers={"Zotero-API-Version": "3", **({"Zotero-API-Key": api_key} if api_key else {})}), timeout=30).read().decode("utf-8"))
    while start < limit:
        url = f"{base}/users/{user_id or '0'}/items/top?format=csljson&limit=100&start={start}"
        data = json.loads(get(url))
        batch = data.get("items", data) if isinstance(data, dict) else data
        if not batch:
            break
        out += [FM.clean({k: v for k, v in it.items() if k != "id"}) for it in batch]
        if len(batch) < 100:
            break
        start += 100
    return out
