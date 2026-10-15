"""Prescription-reading academy: pharmacists practise on real, verified prescriptions."""

from __future__ import annotations

from rapidfuzz import fuzz

from ..ai.lexicon import Lexicon
from ..ai.text import core_name, norm_strength


def _resolve(lexicon: Lexicon, name: str) -> int | None:
    matches = lexicon.match(name, limit=1)
    return matches[0].drug.id if matches and matches[0].score >= 88 else None


def _same_name(answer: dict, truth: dict) -> float:
    if answer.get("drug_id") and answer["drug_id"] == truth.get("drug_id"):
        return 1.0
    return fuzz.ratio(core_name(answer.get("brand")), core_name(truth.get("brand"))) / 100


def score(truth_items: list[dict], answers: list[dict], lexicon: Lexicon) -> dict:
    answers = [
        dict(a, drug_id=_resolve(lexicon, a.get("brand", ""))) for a in answers if (a.get("brand") or "").strip()
    ]
    used: set[int] = set()
    details: list[dict] = []
    points = maximum = 0.0
    for truth in truth_items:
        best, best_sim = None, 0.55
        for i, answer in enumerate(answers):
            if i in used:
                continue
            sim = _same_name(answer, truth)
            if sim > best_sim:
                best, best_sim = i, sim
        answer = answers[best] if best is not None else None
        if best is not None:
            used.add(best)
        name_ok = answer is not None and best_sim >= 0.9
        item_max = 2.0
        item_points = 2.0 if name_ok else 0.0
        strength_ok = freq_ok = None
        if truth.get("strength"):
            item_max += 1
            strength_ok = bool(answer and norm_strength(answer.get("strength")) == norm_strength(truth["strength"]))
            item_points += 1 if strength_ok else 0
        times = (truth.get("sig") or {}).get("times_per_day")
        if times:
            item_max += 1
            try:
                freq_ok = bool(
                    answer
                    and answer.get("times_per_day") is not None
                    and float(answer["times_per_day"]) == float(times)
                )
            except (TypeError, ValueError):
                freq_ok = False
            item_points += 1 if freq_ok else 0
        points += item_points
        maximum += item_max
        details.append(
            {
                "expected": {
                    "brand": truth.get("brand"),
                    "strength": truth.get("strength"),
                    "form": truth.get("form"),
                    "instructions_ar": truth.get("instructions_ar"),
                    "line_text": truth.get("line_text"),
                },
                "answer": {k: answer.get(k) for k in ("brand", "strength", "times_per_day")} if answer else None,
                "name_ok": name_ok,
                "strength_ok": strength_ok,
                "freq_ok": freq_ok,
                "points": item_points,
                "max": item_max,
            }
        )
    extra = [answers[i]["brand"] for i in range(len(answers)) if i not in used]
    penalty = float(len(extra))
    final = max(0.0, points - penalty)
    return {
        "score": final,
        "max_score": maximum,
        "percent": round(100 * final / maximum, 1) if maximum else 0.0,
        "details": details,
        "extra_answers": extra,
    }
