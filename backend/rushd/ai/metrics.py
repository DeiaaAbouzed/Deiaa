"""How good was the AI reading, compared with what the pharmacist verified?"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from .text import core_name, norm_strength


@dataclass
class Comparison:
    acc_drug: float
    acc_fields: float
    cer: float
    items_changed: int
    pairs: list[tuple[int, int]]  # (ai index, verified index)
    name_correct: dict[int, bool]  # verified index -> AI got the drug right


def same_drug(a: dict, b: dict) -> bool:
    if a.get("drug_id") and b.get("drug_id"):
        return a["drug_id"] == b["drug_id"]
    return fuzz.ratio(core_name(a.get("brand")), core_name(b.get("brand"))) >= 92


def _name_sim(a: dict, b: dict) -> float:
    if a.get("drug_id") and a.get("drug_id") == b.get("drug_id"):
        return 1.0
    return fuzz.ratio(core_name(a.get("brand")), core_name(b.get("brand"))) / 100


def pair_items(ai_items: list[dict], verified: list[dict]) -> list[tuple[int, int]]:
    """Pair verified items with the AI items they came from.

    The editor records ``ai_index`` for every item that started as an AI
    suggestion; anything else is paired greedily by name similarity.
    """
    pairs: list[tuple[int, int]] = []
    used_ai: set[int] = set()
    pending: list[int] = []
    for vi, item in enumerate(verified):
        ai_index = item.get("ai_index")
        if isinstance(ai_index, int) and 0 <= ai_index < len(ai_items) and ai_index not in used_ai:
            pairs.append((ai_index, vi))
            used_ai.add(ai_index)
        else:
            pending.append(vi)
    for vi in pending:
        best, best_sim = None, 0.5
        for ai_i, ai_item in enumerate(ai_items):
            if ai_i in used_ai:
                continue
            sim = _name_sim(ai_item, verified[vi])
            if sim > best_sim:
                best, best_sim = ai_i, sim
        if best is not None:
            pairs.append((best, vi))
            used_ai.add(best)
    return sorted(pairs, key=lambda p: p[1])


def _field_matches(a: dict, b: dict) -> tuple[int, int]:
    checks = 0
    good = 0
    for key in ("strength", "form"):
        if b.get(key):
            checks += 1
            va, vb = a.get(key), b.get(key)
            if key == "strength":
                va, vb = norm_strength(va), norm_strength(vb)
            good += int(va == vb)
    sig_a, sig_b = a.get("sig") or {}, b.get("sig") or {}
    for key in ("dose_amount", "times_per_day", "duration_days", "timing"):
        if sig_b.get(key) not in (None, ""):
            checks += 1
            good += int(sig_a.get(key) == sig_b.get(key))
    return good, checks


def compare(ai_items: list[dict], verified: list[dict]) -> Comparison:
    pairs = pair_items(ai_items, verified)
    name_correct: dict[int, bool] = {}
    good_fields = total_fields = 0
    changed = 0
    for ai_i, vi in pairs:
        a, v = ai_items[ai_i], verified[vi]
        ok = same_drug(a, v)
        name_correct[vi] = ok
        g, t = _field_matches(a, v)
        good_fields += g
        total_fields += t
        if not ok or g < t:
            changed += 1
    changed += len(verified) - len(pairs)  # items the AI missed
    correct = sum(name_correct.values())
    denom = max(len(ai_items), len(verified), 1)
    ai_for = {vi: ai_i for ai_i, vi in pairs}
    truth = " | ".join(core_name(v.get("brand")) for v in verified)
    guess = " | ".join(
        core_name(ai_items[ai_for[vi]].get("brand")) if vi in ai_for else "" for vi in range(len(verified))
    )
    cer = Levenshtein.distance(truth, guess) / max(len(truth), 1)
    return Comparison(
        acc_drug=correct / denom,
        acc_fields=(good_fields / total_fields) if total_fields else 1.0,
        cer=min(1.0, cer),
        items_changed=changed,
        pairs=pairs,
        name_correct=name_correct,
    )
