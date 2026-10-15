"""Fuzzy drug-name matching against the pharmacy's drug database.

A handwriting misread rarely produces a random string: vowels and minims get
confused while the outline survives. Candidates are therefore scored with a
blend of edit similarity, Jaro-Winkler (rewards a correct beginning) and a
consonant-skeleton similarity, plus a prior for drugs this doctor actually
prescribes.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process
from rapidfuzz.distance import JaroWinkler

from .text import core_name, norm, skeleton


@dataclass(frozen=True)
class DrugRecord:
    id: int
    brand: str
    generic: str
    drug_class: str
    forms: tuple[str, ...] = ()
    strengths: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    is_generic: bool = False


@dataclass
class Candidate:
    drug: DrugRecord
    score: float  # 0..100
    matched_on: str
    doctor_count: int = 0

    def as_dict(self) -> dict:
        return {
            "drug_id": self.drug.id,
            "brand": self.drug.brand,
            "generic": self.drug.generic,
            "drug_class": self.drug.drug_class,
            "score": round(self.score, 1),
            "doctor_count": self.doctor_count,
        }


@dataclass
class _Entry:
    key: str
    skel: str
    drug_index: int


@dataclass
class Lexicon:
    drugs: list[DrugRecord]
    _entries: list[_Entry] = field(default_factory=list)
    _keys: list[str] = field(default_factory=list)
    _by_id: dict[int, DrugRecord] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for index, drug in enumerate(self.drugs):
            self._by_id[drug.id] = drug
            names = {drug.brand, *drug.aliases}
            if drug.is_generic:
                names.add(drug.generic)
            for name in names:
                key = core_name(name) or norm(name)
                if key:
                    self._entries.append(_Entry(key, skeleton(key), index))
        self._keys = [e.key for e in self._entries]

    def get(self, drug_id: int | None) -> DrugRecord | None:
        return self._by_id.get(drug_id) if drug_id is not None else None

    def match(
        self,
        text: str | None,
        *,
        limit: int = 5,
        doctor_counts: dict[int, int] | None = None,
    ) -> list[Candidate]:
        query = core_name(text) or norm(text)
        if not query or not self._entries:
            return []
        queries = {query}
        first = query.split()[0]
        if len(first) >= 3:
            queries.add(first)  # the brand is usually the first word on the line

        pool: dict[int, float] = {}
        for q in queries:
            for _key, _score, idx in process.extract(q, self._keys, scorer=fuzz.WRatio, limit=40):
                pool[idx] = 0.0
        q_skels = {q: skeleton(q) for q in queries}

        best: dict[int, Candidate] = {}
        for idx in pool:
            entry = self._entries[idx]
            score = 0.0
            for q in queries:
                s = (
                    0.45 * fuzz.ratio(q, entry.key)
                    + 0.35 * JaroWinkler.normalized_similarity(q, entry.key) * 100
                    + 0.20 * fuzz.ratio(q_skels[q], entry.skel)
                )
                if q != query:
                    s -= 4  # a first-word-only match is slightly weaker evidence
                score = max(score, s)
            drug = self.drugs[entry.drug_index]
            count = (doctor_counts or {}).get(drug.id, 0)
            if count:
                score += min(8.0, 2.5 * math.log2(1 + count))
            score = min(100.0, score)
            current = best.get(drug.id)
            if current is None or score > current.score:
                best[drug.id] = Candidate(drug, score, entry.key, count)
        ranked = sorted(best.values(), key=lambda c: (-c.score, c.drug.is_generic, c.drug.brand))
        return ranked[:limit]


class LexiconCache:
    """Rebuilds the in-memory lexicon only when the drug table changes.

    ``fingerprint`` is a cheap query over the drug table; comparing it on each
    access catches changes committed by other transactions or processes (an
    explicit invalidate() alone can run before the change is committed).
    """

    def __init__(self, loader, fingerprint=None):
        self._loader = loader
        self._fingerprint = fingerprint
        self._lock = threading.Lock()
        self._version = 0
        self._built_version = -1
        self._built_fingerprint = None
        self._lexicon: Lexicon | None = None

    def invalidate(self) -> None:
        with self._lock:
            self._version += 1

    def get(self) -> Lexicon:
        current = self._fingerprint() if self._fingerprint else None
        with self._lock:
            if self._lexicon is None or self._built_version != self._version or current != self._built_fingerprint:
                self._lexicon = Lexicon(self._loader())
                self._built_version = self._version
                self._built_fingerprint = current
            return self._lexicon
