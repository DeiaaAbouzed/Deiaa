"""Dose-instruction ("signa") parsing and Arabic patient-label generation.

Understands the Egyptian prescription conventions: ``1×3`` (one unit three
times daily), Latin abbreviations (b.i.d, t.d.s, a.c, p.c, h.s, prn, stat...),
British durations (``5/7`` days, ``2/52`` weeks, ``1/12`` month) and Arabic.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

from .text import to_western_digits

TIMINGS = {
    "before_meal": "قبل الأكل",
    "after_meal": "بعد الأكل",
    "with_meal": "مع الأكل",
    "empty_stomach": "على الريق",
    "bedtime": "قبل النوم",
    "morning": "صباحاً",
    "evening": "مساءً",
}

ROUTES = {
    "oral": "",
    "eye": "في العين",
    "ear": "في الأذن",
    "nose": "في الأنف",
    "topical": "دهان موضعي على المكان المصاب",
    "inhalation": "استنشاق",
    "im": "بالعضل",
    "iv": "بالوريد",
    "sc": "تحت الجلد",
    "rectal": "شرجي",
    "vaginal": "مهبلي",
    "sublingual": "تحت اللسان",
}

# unit -> (singular, dual, plural 3-10, masculine?)
_UNITS: dict[str, tuple[str, str, str, bool]] = {
    "tablet": ("قرص", "قرصين", "أقراص", True),
    "capsule": ("كبسولة", "كبسولتين", "كبسولات", False),
    "drop": ("نقطة", "نقطتين", "نقط", False),
    "puff": ("بخة", "بختين", "بخات", False),
    "sachet": ("كيس", "كيسين", "أكياس", True),
    "suppository": ("لبوس", "لبوسين", "لبوس", True),
    "ampoule": ("حقنة", "حقنتين", "حقن", False),
    "vial": ("فيال", "فيالين", "فيالات", True),
    "teaspoon": ("معلقة صغيرة", "معلقتين صغيرتين", "معالق صغيرة", False),
    "tablespoon": ("معلقة كبيرة", "معلقتين كبيرتين", "معالق كبيرة", False),
    "application": ("دهان", "دهان", "دهان", True),
}

FORM_DEFAULTS: dict[str, tuple[str, str]] = {
    # form -> (default unit, default route)
    "tablet": ("tablet", "oral"),
    "chewable_tablet": ("tablet", "oral"),
    "effervescent": ("tablet", "oral"),
    "capsule": ("capsule", "oral"),
    "syrup": ("ml", "oral"),
    "suspension": ("ml", "oral"),
    "drops": ("drop", "oral"),
    "sachet": ("sachet", "oral"),
    "lozenge": ("tablet", "oral"),
    "ampoule": ("ampoule", "im"),
    "vial": ("vial", "im"),
    "infusion": ("vial", "iv"),
    "prefilled_syringe": ("ampoule", "sc"),
    "pen": ("ampoule", "sc"),
    "suppository": ("suppository", "rectal"),
    "vaginal_tablet": ("tablet", "vaginal"),
    "cream": ("application", "topical"),
    "ointment": ("application", "topical"),
    "gel": ("application", "topical"),
    "lotion": ("application", "topical"),
    "shampoo": ("application", "topical"),
    "oral_gel": ("application", "oral"),
    "eye_drops": ("drop", "eye"),
    "eye_ointment": ("application", "eye"),
    "ear_drops": ("drop", "ear"),
    "nasal_spray": ("puff", "nose"),
    "nasal_drops": ("drop", "nose"),
    "inhaler": ("puff", "inhalation"),
    "nebulizer": ("ml", "inhalation"),
    "mouthwash": ("ml", "oral"),
    "solution": ("ml", "oral"),
}

_AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def to_ar_digits(text: str) -> str:
    return re.sub(r"(?<=\d)\.(?=\d)", "٫", text).translate(_AR_DIGITS)


@dataclass
class Sig:
    dose_amount: float | None = None
    dose_unit: str | None = None
    times_per_day: float | None = None
    interval_hours: float | None = None
    timing: str | None = None
    prn: bool = False
    stat: bool = False
    duration_days: float | None = None
    route: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _num(token: str) -> float | None:
    token = token.strip()
    if token in ("½", "1/2"):
        return 0.5
    if token in ("¼", "1/4"):
        return 0.25
    if token in ("1½", "1 1/2"):
        return 1.5
    try:
        return float(token)
    except ValueError:
        return None


# Most specific first: "twice daily" must not be caught by the bare "daily".
_FREQ_ABBR = [
    (r"\b(?:q\.?i\.?d|q\.?d\.?s|four\s+times\s+(?:a\s+day|daily))\b", 4),
    (r"\b(?:t\.?i\.?d|t\.?d\.?s|thrice\s+daily|three\s+times\s+(?:a\s+day|daily))\b", 3),
    (r"\b(?:b\.?i\.?d|b\.?d|twice\s+daily|twice\s+a\s+day)\b", 2),
    (r"مرتين", 2),
    (r"\b(?:o\.?d|q\.?d|once\s+daily|once\s+a\s+day|daily)\b", 1),
    (r"مر[ةه]\s*(?:واحد[ةه])?\s*(?:يوميا|في اليوم)", 1),
]
_UNIT_WORDS = [
    (r"tabs?|tablets?|قرص|اقراص|أقراص", "tablet"),
    (r"caps?|capsules?|كبسول[ةه]?|كبسولات", "capsule"),
    (r"ml|cc|cm|مل|سم", "ml"),
    (r"tsp|teaspoons?|معلق[ةه] صغير[ةه]", "teaspoon"),
    (r"tbsp|tablespoons?|معلق[ةه] كبير[ةه]", "tablespoon"),
    (r"drops?|gtts?|نقط[ةه]?|نقط", "drop"),
    (r"puffs?|بخ[ةه]|بخات|بختين", "puff"),
    (r"sachets?|sach|كيس|اكياس|أكياس", "sachet"),
    (r"supps?|suppositor(?:y|ies)|لبوس", "suppository"),
    (r"amps?|ampoules?|حقن[ةه]?", "ampoule"),
    (r"vials?|فيال", "vial"),
]


def parse_sig(text: str | None, form: str | None = None) -> Sig:
    sig = Sig()
    if form in FORM_DEFAULTS:
        sig.dose_unit, sig.route = FORM_DEFAULTS[form]
    if not text:
        return sig
    t = unicodedata.normalize("NFKC", to_western_digits(text)).lower()
    t = t.replace("×", "x").replace("*", "x")

    m = re.search(r"(\d+(?:\.\d+)?|½|¼|1/2|1/4)\s*x\s*(\d+)(?!\s*(?:days?|d\b|weeks?|يوم|ايام|أيام))", t)
    if m and (times := float(m.group(2))) <= 6:
        sig.dose_amount, sig.times_per_day = _num(m.group(1)), times
    elif m2 := re.search(r"(?<![\d.])x\s*([1-6])\b(?!\s*(?:days?|d\b|weeks?))", t):
        sig.times_per_day = float(m2.group(1))  # "5 ml x 3": the amount comes from the unit below

    if sig.times_per_day is None and (m := re.search(r"\b(\d+)\s*(?:times|مرات)\b", t)):
        sig.times_per_day = float(m.group(1))
    if sig.times_per_day is None:
        for pattern, times in _FREQ_ABBR:
            if re.search(pattern, t):
                sig.times_per_day = float(times)
                break

    interval = re.search(r"(?:\bq\s*(\d+)\s*h|every\s*(\d+)\s*h(?:ours?|rs?)?|/\s*(\d+)\s*h\b|كل\s*(\d+)\s*ساع)", t)
    if interval:
        hours = float(next(g for g in interval.groups() if g))
        if 0 < hours <= 72:
            sig.interval_hours = hours
            if sig.times_per_day is None and hours <= 24:
                sig.times_per_day = round(24 / hours, 2)
    elif sig.times_per_day in (2, 3, 4, 6):
        sig.interval_hours = 24 / sig.times_per_day

    if re.search(r"\bq\.?o\.?d\b|every\s+other\s+day|يوم\s*(?:بعد|و)\s*يوم", t):
        sig.times_per_day, sig.interval_hours = 0.5, 48.0
    if re.search(r"\b(?:once\s+)?weekly\b|/\s*week|اسبوعيا|أسبوعيا", t):
        sig.times_per_day, sig.interval_hours = round(1 / 7, 3), 168.0

    if re.search(
        r"\bp\.?r\.?n\b|\bs\.?o\.?s\b|when\s+needed|as\s+needed|if\s+needed|عند\s+(?:اللزوم|الحاج[ةه]|الالم|الألم)", t
    ):
        sig.prn = True
    if re.search(r"\bstat\b|فورا|فوراً", t):
        sig.stat = True

    if re.search(r"\ba\.?c\.?(?![a-z])|before\s+(?:meals?|food|eating)|قبل\s+(?:الاكل|الأكل|الأكل|الطعام|الوجبات)", t):
        sig.timing = "before_meal"
    elif re.search(r"\bp\.?c\.?(?![a-z])|after\s+(?:meals?|food|eating)|بعد\s+(?:الاكل|الأكل|الطعام|الوجبات)", t):
        sig.timing = "after_meal"
    elif re.search(r"with\s+(?:meals?|food)|مع\s+(?:الاكل|الأكل|الطعام)", t):
        sig.timing = "with_meal"
    elif re.search(r"empty\s+stomach|على\s+الريق|صائم", t):
        sig.timing = "empty_stomach"
    elif re.search(r"\bh\.?s\.?(?![a-z])|bed\s*time|at\s+night|\bnocte\b|قبل\s+النوم|مساء", t):
        sig.timing = "bedtime"
        if sig.times_per_day is None:
            sig.times_per_day = 1.0
    elif re.search(r"\bmane\b|morning|صباحا|صباحاً", t):
        sig.timing = "morning"
        if sig.times_per_day is None:
            sig.times_per_day = 1.0

    duration = re.search(
        r"(\d+)\s*(days?|d\b|weeks?|wks?|w\b|months?|يوم|ايام|أيام|اسبوع|أسبوع|اسابيع|أسابيع|شهر|شهور)", t
    )
    if duration:
        n, unit = float(duration.group(1)), duration.group(2)
        if unit.startswith(("w", "اسبوع", "أسبوع", "اسابيع", "أسابيع")):
            n *= 7
        elif unit.startswith(("month", "شهر")):
            n *= 30
        sig.duration_days = n
    elif m := re.search(r"(?<![\d/])(\d+)\s*/\s*(7|52|12)(?!\d)", t):
        n = float(m.group(1))
        sig.duration_days = {"7": n, "52": n * 7, "12": n * 30}[m.group(2)]

    for pattern, unit in _UNIT_WORDS:
        if um := re.search(rf"(\d+(?:\.\d+)?|½|¼|1/2)?\s*(?:{pattern})(?![a-z])", t):
            sig.dose_unit = unit
            if um.group(1) and sig.dose_amount is None:
                sig.dose_amount = _num(um.group(1))
            break
    if sig.dose_unit == "teaspoon" and sig.dose_amount is None:
        sig.dose_amount = 1.0
    if re.search(r"\bhalf\b|نصف|نص\b", t) and sig.dose_amount in (None, 1.0):
        sig.dose_amount = 0.5

    if re.search(r"\bi\.?m\.?(?![a-z])|عضل", t):
        sig.route = "im"
    elif re.search(r"\bi\.?v\.?(?![a-z])|وريد", t):
        sig.route = "iv"
    elif re.search(r"\bs\.?c\.?(?![a-z])|تحت الجلد", t):
        sig.route = "sc"
    elif re.search(r"sublingual|\bs\.?l\.?(?![a-z])|تحت اللسان", t):
        sig.route = "sublingual"

    if (
        sig.dose_amount is None
        and (sig.times_per_day is not None or sig.prn or sig.stat)
        and sig.dose_unit not in (None, "ml", "application")
    ):
        sig.dose_amount = 1.0
    return sig


def merge_sig(structured: dict, text: str | None, form: str | None) -> Sig:
    """Prefer the AI's structured interpretation, fill gaps from the raw text."""
    parsed = parse_sig(text, form)
    merged = Sig(**{k: v for k, v in parsed.as_dict().items()})
    for key in ("dose_amount", "dose_unit", "times_per_day", "interval_hours", "timing", "duration_days", "route"):
        value = structured.get(key)
        if value not in (None, "", 0):
            setattr(merged, key, value)
    for key in ("prn", "stat"):
        if structured.get(key):
            setattr(merged, key, True)
    if merged.interval_hours is None and merged.times_per_day in (2, 3, 4, 6):
        merged.interval_hours = 24 / merged.times_per_day
    return merged


def _fmt(n: float) -> str:
    return to_ar_digits(f"{n:g}")


def _dose_phrase(amount: float | None, unit: str | None) -> str:
    if not unit:
        return _fmt(amount) if amount else ""
    if unit == "ml":
        return f"{_fmt(amount)} مل" if amount else ""
    if unit == "application":
        return ""
    singular, dual, plural, masculine = _UNITS.get(unit, (unit, unit, unit, True))
    if amount is None:
        return singular
    if amount == 0.25:
        return f"ربع {singular}"
    if amount == 0.5:
        return f"نصف {singular}"
    if amount == 1:
        return f"{singular} {'واحد' if masculine else 'واحدة'}"
    if amount == 1.5:
        return f"{singular} ونصف"
    if amount == 2:
        return dual
    if amount == int(amount) and 3 <= amount <= 10:
        return f"{_fmt(amount)} {plural}"
    return f"{_fmt(amount)} {singular}"


def _freq_phrase(sig: Sig) -> str:
    times = sig.times_per_day
    if sig.stat:
        return "جرعة واحدة فوراً"
    parts: list[str] = []
    if times is not None:
        if abs(times - 0.5) < 1e-6:
            parts.append("يوم بعد يوم")
        elif abs(times - 1 / 7) < 0.01:
            parts.append("مرة واحدة أسبوعياً")
        elif times == 1:
            parts.append("مرة واحدة يومياً")
        elif times == 2:
            parts.append("مرتين يومياً")
        elif times == int(times):
            parts.append(f"{_fmt(times)} مرات يومياً")
        else:
            parts.append(f"{_fmt(times)} مرة يومياً")
        if sig.interval_hours and sig.interval_hours < 24 and times >= 2:
            h = sig.interval_hours
            parts.append(f"(كل {_fmt(h)} {'ساعة' if h > 10 or h == 1 else 'ساعات'})")
    if sig.prn:
        parts = ["عند اللزوم"] + ([f"بحد أقصى {parts[0]}"] if parts else [])
    return " ".join(parts)


def _duration_phrase(days: float | None) -> str:
    if not days:
        return ""
    special = {
        1: "يوم واحد",
        2: "يومين",
        7: "أسبوع",
        14: "أسبوعين",
        21: "٣ أسابيع",
        30: "شهر",
        60: "شهرين",
        90: "٣ شهور",
    }
    if days in special:
        return f"لمدة {special[days]}"
    if days == int(days) and 3 <= days <= 10:
        return f"لمدة {_fmt(days)} أيام"
    return f"لمدة {_fmt(days)} يوماً"


def arabic_instructions(sig: Sig) -> str:
    """'قرص واحد ٣ مرات يومياً (كل ٨ ساعات) بعد الأكل لمدة ٥ أيام'."""
    parts = [
        _dose_phrase(sig.dose_amount, sig.dose_unit),
        ROUTES.get(sig.route or "", ""),
        _freq_phrase(sig),
        TIMINGS.get(sig.timing or "", ""),
        _duration_phrase(sig.duration_days),
    ]
    text = " ".join(p for p in parts if p)
    return re.sub(r"\s+", " ", text).strip()
