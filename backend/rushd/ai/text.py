"""Text normalisation shared by matching, metrics and learning."""

from __future__ import annotations

import re
import unicodedata

_AR_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_AR_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_NON_WORD = re.compile(r"[^0-9a-zء-ي]+")

# Dosage-form words that say nothing about *which* drug it is.
FORM_WORDS = {
    "tab",
    "tabs",
    "tablet",
    "tablets",
    "cap",
    "caps",
    "capsule",
    "capsules",
    "syr",
    "syrup",
    "susp",
    "suspension",
    "amp",
    "amps",
    "ampoule",
    "ampoules",
    "ampule",
    "vial",
    "vials",
    "inj",
    "injection",
    "drop",
    "drops",
    "gtt",
    "gtts",
    "cream",
    "crm",
    "oint",
    "ointment",
    "ung",
    "gel",
    "supp",
    "supps",
    "suppository",
    "suppositories",
    "sachet",
    "sachets",
    "sach",
    "eff",
    "effervescent",
    "spray",
    "inhaler",
    "inh",
    "lotion",
    "shampoo",
    "sol",
    "solution",
    "neb",
    "nebulizer",
    "resp",
    "respules",
    "powder",
    "pdr",
    "film",
    "coated",
    "oral",
    "eye",
    "ear",
    "nasal",
    "topical",
    "vag",
    "vaginal",
    "pen",
    "prefilled",
    "syringe",
    "lozenge",
    "lozenges",
    "patch",
    "mouthwash",
    "bottle",
    "box",
    "pack",
    "strip",
    "strips",
    "قرص",
    "اقراص",
    "كبسول",
    "كبسوله",
    "شراب",
    "معلق",
    "حقن",
    "حقنه",
    "امبول",
    "نقط",
    "كريم",
    "مرهم",
    "جل",
    "لبوس",
    "اكياس",
    "كيس",
    "بخاخ",
}
_UNIT_TOKENS = {
    "mg",
    "mgm",
    "g",
    "gm",
    "gram",
    "grams",
    "mcg",
    "ug",
    "ml",
    "cc",
    "iu",
    "unit",
    "units",
    "مجم",
    "ملجم",
    "مل",
    "جم",
}
_STRENGTH = re.compile(r"^\d+([.,/]\d+)*(mg|mgm|g|gm|gram|mcg|ug|µg|ml|iu|u|%|mg/ml|mg/5ml|k)?$")


def to_western_digits(text: str) -> str:
    return text.translate(_DIGITS)


def norm(text: str | None) -> str:
    """Lower-case, Arabic-folded, punctuation-free text with single spaces."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower().translate(_DIGITS)
    text = _AR_DIACRITICS.sub("", text).translate(_AR_MAP)
    return " ".join(_NON_WORD.sub(" ", text).split())


def core_name(text: str | None) -> str:
    """The drug-identifying part of a medication line (no forms or strengths)."""
    tokens = [t for t in norm(text).split() if t not in FORM_WORDS and t not in _UNIT_TOKENS and not _STRENGTH.match(t)]
    return " ".join(tokens)


def skeleton(text: str) -> str:
    """Consonant outline: keeps the first letter, drops vowels and doubled letters.

    Handwriting misreads mostly hit vowels (a/o/u/e) and minims, so two
    readings of the same scribble often share a skeleton.
    """
    out: list[str] = []
    for i, ch in enumerate(text.replace(" ", "")):
        if i > 0 and ch in "aeiouy":
            continue
        if out and out[-1] == ch:
            continue
        out.append(ch)
    return "".join(out)


_UNIT_ALIASES = {"gm": "g", "gram": "g", "grams": "g", "mgm": "mg", "ug": "mcg", "µg": "mcg", "i.u": "iu"}


def norm_strength(text: str | None) -> str:
    """'1 gm' -> '1g', '625 mg' -> '625mg', '٥٠٠ مجم' -> '500mg'."""
    if not text:
        return ""
    t = to_western_digits(unicodedata.normalize("NFKC", text)).lower()
    t = t.replace("مجم", "mg").replace("ملجم", "mg").replace("مل", "ml").replace("جم", "g")
    t = t.replace(",", ".").replace(" ", "")
    for alias, unit in _UNIT_ALIASES.items():
        t = re.sub(rf"(?<=\d){re.escape(alias)}\b", unit, t)
    t = re.sub(r"(\d)\.0+(?=\D|$)", r"\1", t)
    # 1000mg == 1g, so compare in a canonical unit when the value is a plain number.
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(mg|g|mcg)", t)
    if m:
        value, unit = float(m.group(1)), m.group(2)
        mg = value * {"mg": 1, "g": 1000, "mcg": 0.001}[unit]
        if mg >= 1000 and mg % 1000 == 0:
            return f"{int(mg // 1000)}g"
        if mg >= 1:
            return f"{mg:g}mg"
        return f"{mg * 1000:g}mcg"
    return t
