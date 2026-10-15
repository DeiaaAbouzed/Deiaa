"""Prescription-reading academy: pharmacists practise on real, verified prescriptions."""

from __future__ import annotations

from datetime import timedelta

from rapidfuzz import fuzz
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ..ai.lexicon import Lexicon
from ..ai.text import core_name, norm_strength
from ..db import utcnow
from ..models import Branch, Prescription, QuizAttempt, User

# How hard a prescription is to read, judged by how the AI itself did on it.
DIFFICULTY = {
    "easy": lambda: Prescription.ai_confidence >= 0.9,
    "medium": lambda: (Prescription.ai_confidence >= 0.7) & (Prescription.ai_confidence < 0.9),
    "hard": lambda: or_(Prescription.ai_confidence < 0.7, Prescription.acc_drug < 1.0),
}


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


def _percent(points: float, maximum: float) -> float | None:
    return round(100 * points / maximum, 1) if maximum else None


def progress_report(db: Session, days: int, branch_id: int | None = None) -> dict:
    """Academy results per person for the training manager: who practises, how well, and who is improving."""
    since = utcnow() - timedelta(days=days)
    attempts = db.execute(
        select(
            QuizAttempt.user_id,
            QuizAttempt.score,
            QuizAttempt.max_score,
            QuizAttempt.details,
            case((DIFFICULTY["hard"](), 1), else_=0).label("hard"),
        )
        .join(Prescription, Prescription.id == QuizAttempt.prescription_id)
        .where(QuizAttempt.submitted_at >= since, QuizAttempt.max_score > 0)
        .order_by(QuizAttempt.submitted_at)
    ).all()
    per_user: dict[int, list] = {}
    for row in attempts:
        per_user.setdefault(row.user_id, []).append(row)
    last_seen = dict(
        db.execute(select(QuizAttempt.user_id, func.max(QuizAttempt.submitted_at)).group_by(QuizAttempt.user_id)).all()
    )
    branches = {b.id: b.name for b in db.execute(select(Branch)).scalars()}
    people = select(User).where(
        or_(User.id.in_(list(per_user)), (User.is_active.is_(True)) & User.role.in_(("trainee", "pharmacist")))
    )
    if branch_id:
        people = people.where(User.branch_id == branch_id)

    rows = []
    for user in db.execute(people).scalars():
        mine = per_user.get(user.id, [])
        percents = [100 * (a.score or 0) / a.max_score for a in mine]
        half = len(percents) // 2
        hard = [a for a in mine if a.hard]
        rows.append(
            {
                "user_id": user.id,
                "name": user.full_name or user.username,
                "username": user.username,
                "role": user.role,
                "branch": branches.get(user.branch_id),
                "attempts": len(mine),
                "percent": _percent(sum(a.score or 0 for a in mine), sum(a.max_score for a in mine)),
                # Recent half of the period against the earlier half; too noisy below four attempts.
                "improvement": round(sum(percents[-half:]) / half - sum(percents[:half]) / half, 1)
                if len(percents) >= 4
                else None,
                "hard_attempts": len(hard),
                "hard_percent": _percent(sum(a.score or 0 for a in hard), sum(a.max_score for a in hard)),
                "minutes": round(sum((a.details or {}).get("seconds") or 0 for a in mine) / 60),
                "last_activity": last_seen[user.id].isoformat() if user.id in last_seen else None,
            }
        )
    # Weakest participants first - they need the trainer's attention; then those who did not practise.
    rows.sort(key=lambda r: (r["attempts"] == 0, r["percent"] if r["percent"] is not None else 0, r["name"]))
    included = [a for r in rows for a in per_user.get(r["user_id"], [])]
    participants = sum(1 for r in rows if r["attempts"])
    return {
        "days": days,
        "since": since.isoformat(),
        "rows": rows,
        "summary": {
            "participants": participants,
            "inactive": len(rows) - participants,
            "attempts": len(included),
            "percent": _percent(sum(a.score or 0 for a in included), sum(a.max_score for a in included)),
        },
    }
