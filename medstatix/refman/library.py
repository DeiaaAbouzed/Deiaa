"""The reference library: one SQLite file in the user's profile, holding CSL-JSON items, groups, notes, ratings and
attached PDFs. Record numbers are stable (like EndNote's #), so citations such as {Hassan, 2021 #12} can be found again."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time

from . import formats as FM


def default_path() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".medstatix")
    d = os.path.join(base, "MedStatixPro") if os.environ.get("APPDATA") else base
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "reference_library.sqlite")


class Library:
    def __init__(self, path: str | None = None):
        self.path = path or default_path()
        self.db = sqlite3.connect(self.path)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS refs (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL, ukey TEXT,
                added REAL, modified REAL, notes TEXT DEFAULT '', pdf TEXT DEFAULT '', rating INTEGER DEFAULT 0,
                is_read INTEGER DEFAULT 0, trashed INTEGER DEFAULT 0);
            CREATE INDEX IF NOT EXISTS refs_ukey ON refs(ukey);
            CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL);
            CREATE TABLE IF NOT EXISTS ref_groups (ref_id INTEGER, group_id INTEGER, PRIMARY KEY (ref_id, group_id));
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    # -- references ------------------------------------------------------------
    def find(self, item: dict):
        row = self.db.execute("SELECT id FROM refs WHERE ukey=? AND trashed=0", (FM.key(item),)).fetchone()
        return row[0] if row else None

    def add(self, item: dict, group: str | None = None) -> tuple[int, bool]:
        """Add one reference; returns (record number, True if new). A duplicate (same DOI, PMID or title + year) is not
        added twice; empty fields of the stored copy are filled from the new one."""
        item = FM.clean({k: v for k, v in item.items() if k != "id"})
        rid = self.find(item)
        if rid:
            old = self.get(rid)
            merged = dict(item); merged.update({k: v for k, v in old.items() if v not in (None, "", [])})
            merged.pop("id", None)
            self.db.execute("UPDATE refs SET data=? WHERE id=?", (json.dumps(merged, ensure_ascii=False), rid))
            new = False
        else:
            now = time.time()
            cur = self.db.execute("INSERT INTO refs (data, ukey, added, modified) VALUES (?,?,?,?)",
                                  (json.dumps(item, ensure_ascii=False), FM.key(item), now, now))
            rid, new = cur.lastrowid, True
        if group:
            self.assign([rid], group)
        self.db.commit()
        return rid, new

    def add_many(self, items, group: str | None = None) -> tuple[int, int]:
        added = dup = 0
        for it in items:
            _, new = self.add(it, group)
            added += new; dup += not new
        return added, dup

    def get(self, rid: int) -> dict:
        row = self.db.execute("SELECT data FROM refs WHERE id=?", (rid,)).fetchone()
        if not row:
            raise KeyError(rid)
        it = json.loads(row[0]); it["id"] = f"r{rid}"
        return it

    def meta(self, rid: int) -> dict:
        r = self.db.execute("SELECT added, modified, notes, pdf, rating, is_read FROM refs WHERE id=?", (rid,)).fetchone()
        return dict(zip(("added", "modified", "notes", "pdf", "rating", "read"), r)) if r else {}

    def update(self, rid: int, item: dict):
        item = FM.clean({k: v for k, v in item.items() if k != "id"})
        self.db.execute("UPDATE refs SET data=?, ukey=?, modified=? WHERE id=?",
                        (json.dumps(item, ensure_ascii=False), FM.key(item), time.time(), rid))
        self.db.commit()

    def set_meta(self, rid: int, **kw):
        cols = {"notes": "notes", "pdf": "pdf", "rating": "rating", "read": "is_read"}
        for k, v in kw.items():
            if k in cols:
                self.db.execute(f"UPDATE refs SET {cols[k]}=? WHERE id=?", (v, rid))
        self.db.commit()

    def delete(self, ids):
        for rid in ids:
            self.db.execute("DELETE FROM refs WHERE id=?", (rid,))
            self.db.execute("DELETE FROM ref_groups WHERE ref_id=?", (rid,))
        self.db.commit()

    def ids(self, group: str | None = None, query: str = "", unfiled=False, recent_days: float = 0) -> list[int]:
        sql, args = "SELECT r.id, r.data FROM refs r WHERE r.trashed=0", []
        if group:
            sql += " AND r.id IN (SELECT rg.ref_id FROM ref_groups rg JOIN groups g ON g.id=rg.group_id WHERE g.name=?)"
            args.append(group)
        if unfiled:
            sql += " AND r.id NOT IN (SELECT ref_id FROM ref_groups)"
        if recent_days:
            sql += " AND r.added >= ?"; args.append(time.time() - recent_days * 86400)
        rows = self.db.execute(sql + " ORDER BY r.id", args).fetchall()
        if query:
            terms = [t.lower() for t in query.split() if t]
            rows = [r for r in rows if all(t in self._haystack(r[1], r[0]) for t in terms)]
        return [r[0] for r in rows]

    def _haystack(self, data: str, rid: int) -> str:
        it = json.loads(data)
        au = " ".join(FM.person_text(a) for a in it.get("author", []))
        return " ".join([str(rid), "#" + str(rid), au, FM.year_of(it), it.get("title", ""), it.get("container-title", ""),
                         it.get("keyword", ""), it.get("abstract", ""), it.get("DOI", ""), str(it.get("PMID", ""))]).lower()

    def items(self, ids) -> list[dict]:
        return [self.get(i) for i in ids]

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM refs WHERE trashed=0").fetchone()[0]

    # -- groups ----------------------------------------------------------------
    def groups(self) -> list[tuple[str, int]]:
        return self.db.execute("SELECT g.name, COUNT(rg.ref_id) FROM groups g LEFT JOIN ref_groups rg ON rg.group_id=g.id "
                               "GROUP BY g.id ORDER BY g.name").fetchall()

    def add_group(self, name: str) -> int:
        self.db.execute("INSERT OR IGNORE INTO groups (name) VALUES (?)", (name.strip(),)); self.db.commit()
        return self.db.execute("SELECT id FROM groups WHERE name=?", (name.strip(),)).fetchone()[0]

    def rename_group(self, old: str, new: str):
        self.db.execute("UPDATE groups SET name=? WHERE name=?", (new.strip(), old)); self.db.commit()

    def delete_group(self, name: str):
        gid = self.db.execute("SELECT id FROM groups WHERE name=?", (name,)).fetchone()
        if gid:
            self.db.execute("DELETE FROM ref_groups WHERE group_id=?", gid)
            self.db.execute("DELETE FROM groups WHERE id=?", gid)
            self.db.commit()

    def assign(self, ids, group: str):
        gid = self.add_group(group)
        self.db.executemany("INSERT OR IGNORE INTO ref_groups VALUES (?,?)", [(i, gid) for i in ids]); self.db.commit()

    def unassign(self, ids, group: str):
        gid = self.db.execute("SELECT id FROM groups WHERE name=?", (group,)).fetchone()
        if gid:
            self.db.executemany("DELETE FROM ref_groups WHERE ref_id=? AND group_id=?", [(i, gid[0]) for i in ids])
            self.db.commit()

    def groups_of(self, rid: int) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT g.name FROM groups g JOIN ref_groups rg ON rg.group_id=g.id "
                                              "WHERE rg.ref_id=? ORDER BY g.name", (rid,))]

    # -- duplicates and lookup ---------------------------------------------------
    def duplicates(self) -> list[list[int]]:
        """Records that are probably the same paper (same DOI, PMID or near-identical title and year)."""
        seen = {}
        for rid, data in self.db.execute("SELECT id, data FROM refs WHERE trashed=0"):
            it = json.loads(data)
            keys = {FM.key(it), "t:" + re.sub(r"[^a-z0-9]", "", (it.get("title") or "").lower())[:60] + FM.year_of(it)}
            for k in keys:
                if len(k) > 8:
                    seen.setdefault(k, set()).add(rid)
        groups, done = [], set()
        for ids in seen.values():
            ids = sorted(ids)
            if len(ids) > 1 and tuple(ids) not in done:
                done.add(tuple(ids)); groups.append(ids)
        return groups

    def match_citation(self, author: str, year: str, rec: str = "") -> int | None:
        """Find the record for a temporary citation {Author, Year #rec}."""
        if rec and rec.isdigit():
            r = self.db.execute("SELECT id FROM refs WHERE id=?", (int(rec),)).fetchone()
            if r:
                return r[0]
        a = re.sub(r"\s+et al\.?$", "", author.strip(), flags=re.I).lower()
        a = re.split(r"\s+(?:and|&)\s+", a)[0].strip()
        hits = []
        for rid, data in self.db.execute("SELECT id, data FROM refs WHERE trashed=0 ORDER BY id"):
            it = json.loads(data)
            if FM.first_author(it).lower() == a and (not year or FM.year_of(it) == year[:4]):
                hits.append(rid)
        if len(hits) > 1 and len(year) == 5 and year[4].isalpha():        # 2020a, 2020b
            i = ord(year[4].lower()) - 97
            return hits[i] if i < len(hits) else hits[0]
        return hits[0] if hits else None
