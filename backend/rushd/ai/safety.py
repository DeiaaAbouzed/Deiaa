"""Basic dispensing safety checks on a reading.

Deliberately conservative and short: duplicated active ingredients,
duplicated drug classes where duplication is rarely intended, and a curated
list of well-established interactions. It supports - never replaces - the
pharmacist's own interaction reference.
"""

from __future__ import annotations

import re
from itertools import combinations

SYSTEMIC_FORMS = {
    None,
    "tablet",
    "chewable_tablet",
    "effervescent",
    "capsule",
    "syrup",
    "suspension",
    "drops",
    "sachet",
    "lozenge",
    "ampoule",
    "vial",
    "infusion",
    "prefilled_syringe",
    "pen",
    "suppository",
    "solution",
}

_SALTS = {
    "sodium",
    "potassium",
    "hydrochloride",
    "hcl",
    "besylate",
    "besilate",
    "maleate",
    "mesylate",
    "acetate",
    "valerate",
    "propionate",
    "dipropionate",
    "furoate",
    "butylbromide",
    "bromide",
    "sulfate",
    "sulphate",
    "methylsulfate",
    "calcium",
    "magnesium",
    "succinate",
    "tartrate",
    "fumarate",
    "citrate",
    "phosphate",
    "monohydrate",
    "trihydrate",
    "acetonide",
}
_SYNONYMS = {
    "acetylsalicylic acid": "aspirin",
    "acetaminophen": "paracetamol",
    "chlorphenamine": "chlorpheniramine",
    "aciclovir": "acyclovir",
    "clomifene": "clomiphene",
    "glyburide": "glibenclamide",
    "albuterol": "salbutamol",
}
# Classes for combination ingredients that have no single-ingredient product.
_EXTRA_CLASSES = {
    "chlorpheniramine": "Antihistamine",
    "pseudoephedrine": "Decongestant",
    "hydrochlorothiazide": "Thiazide diuretic",
    "metformin": "Biguanide",
    "aspirin": "Antiplatelet",
    "simvastatin": "Statin",
}
# Classes where two different products are rarely intended.
_DUP_CLASSES = {
    "NSAID": "مسكنين من مضادات الالتهاب غير الستيرويدية (NSAIDs)",
    "PPI": "دواءين من مثبطات مضخة البروتون (PPI)",
    "Antihistamine": "مضادين للهيستامين",
    "Statin": "دواءين لخفض الكوليسترول (Statins)",
    "ARB": "دواءين من حاصرات مستقبلات الأنجيوتنسين (ARB)",
    "ACE inhibitor": "دواءين من مثبطات ACE",
    "Beta blocker": "دواءين من حاصرات بيتا",
    "SSRI": "دواءين من مضادات الاكتئاب SSRI",
    "Benzodiazepine": "دواءين من البنزوديازيبينات",
    "Sulfonylurea": "دواءين من السلفونيل يوريا",
    "DPP-4 inhibitor": "دواءين من مثبطات DPP-4",
    "SGLT2 inhibitor": "دواءين من مثبطات SGLT2",
    "Fluoroquinolone": "مضادين حيويين من الفلوروكينولون",
    "Macrolide": "مضادين حيويين من الماكروليد",
    "Anticoagulant": "مضادين للتجلط",
    "Corticosteroid": "دواءين من الكورتيزون الجهازي",
    "Calcium channel blocker": "دواءين من حاصرات قنوات الكالسيوم",
}

# (side A, side B, level, Arabic message). A side is a set of ingredient names
# and/or "class:<Class>" tokens.
_INTERACTIONS: list[tuple[set[str], set[str], str, str]] = [
    ({"warfarin"}, {"class:NSAID"}, "major", "خطر نزيف: الوارفارين مع مسكن من مضادات الالتهاب (NSAID)"),
    ({"warfarin"}, {"aspirin", "clopidogrel"}, "major", "خطر نزيف: الوارفارين مع مضاد للصفائح"),
    ({"warfarin"}, {"metronidazole", "fluconazole"}, "major", "يرفع تأثير الوارفارين (INR) وخطر النزيف"),
    ({"rivaroxaban", "apixaban", "enoxaparin"}, {"class:NSAID"}, "major", "خطر نزيف: مضاد تجلط مع مسكن NSAID"),
    (
        {"clopidogrel"},
        {"omeprazole", "esomeprazole"},
        "moderate",
        "قد يقلل فاعلية الكلوبيدوجريل - البانتوبرازول بديل أنسب",
    ),
    ({"class:ACE inhibitor", "class:ARB"}, {"spironolactone"}, "major", "خطر ارتفاع البوتاسيوم في الدم"),
    ({"class:ACE inhibitor", "class:ARB"}, {"class:NSAID"}, "moderate", "قد يقلل تأثير دواء الضغط ويؤثر على الكلى"),
    ({"class:PDE5 inhibitor"}, {"class:Nitrate"}, "contraindicated", "ممنوع الجمع: هبوط شديد في ضغط الدم"),
    ({"class:PDE5 inhibitor"}, {"class:Alpha blocker"}, "moderate", "احتمال هبوط في ضغط الدم"),
    ({"clarithromycin"}, {"atorvastatin", "simvastatin"}, "major", "خطر تكسر العضلات (اعتلال عضلي)"),
    ({"clarithromycin"}, {"domperidone"}, "major", "خطر اضطراب نظم القلب (إطالة QT)"),
    ({"class:SSRI"}, {"class:NSAID"}, "moderate", "زيادة خطر النزيف المعدي"),
    ({"class:SSRI"}, {"tramadol"}, "major", "خطر متلازمة السيروتونين والتشنجات"),
    ({"class:Benzodiazepine"}, {"class:Opioid analgesic"}, "major", "خطر تثبيط التنفس والنعاس الشديد"),
    ({"class:Fluoroquinolone"}, {"class:Corticosteroid"}, "moderate", "خطر التهاب أو تمزق الأوتار خاصة لكبار السن"),
]

_LEVEL_ORDER = {"contraindicated": 0, "major": 1, "moderate": 2}


def ingredients(generic: str | None) -> set[str]:
    out: set[str] = set()
    for part in re.split(r"\s*\+\s*", (generic or "").lower()):
        part = re.sub(r"\(.*?\)", "", part).strip()
        if not part:
            continue
        part = _SYNONYMS.get(part, part)
        words = [w for w in part.split() if w not in _SALTS] or part.split()
        name = " ".join(words)
        out.add(_SYNONYMS.get(name, name))
    return out


def build_class_map(drugs) -> dict[str, str]:
    """Ingredient -> class, learned from single-ingredient products in the database."""
    mapping = dict(_EXTRA_CLASSES)
    for drug in drugs:
        ing = ingredients(drug.generic)
        if len(ing) == 1 and drug.drug_class:
            mapping.setdefault(next(iter(ing)), drug.drug_class)
    return mapping


def _tokens(item: dict, class_map: dict[str, str]) -> set[str]:
    ing = ingredients(item.get("generic"))
    classes = {f"class:{class_map[i]}" for i in ing if i in class_map}
    if item.get("drug_class") and len(ing) <= 1:
        classes.add(f"class:{item['drug_class']}")
    return ing | classes


def check(items: list[dict], class_map: dict[str, str]) -> list[dict]:
    warnings: list[dict] = []
    systemic = [(i, it) for i, it in enumerate(items) if it.get("form") in SYSTEMIC_FORMS and it.get("generic")]
    for (i, a), (j, b) in combinations(systemic, 2):
        ing_a, ing_b = ingredients(a["generic"]), ingredients(b["generic"])
        shared = ing_a & ing_b
        if shared:
            names = "، ".join(sorted(shared))
            level = "major" if "paracetamol" in shared else "moderate"
            msg = f"نفس المادة الفعالة ({names}) في {a['brand']} و{b['brand']} - احتمال جرعة زائدة"
            warnings.append({"type": "duplicate_ingredient", "level": level, "items": [i, j], "message": msg})
            continue
        classes_a = {class_map[x] for x in ing_a if x in class_map}
        classes_b = {class_map[x] for x in ing_b if x in class_map}
        for cls in sorted((classes_a & classes_b) & _DUP_CLASSES.keys()):
            msg = f"{_DUP_CLASSES[cls]}: {a['brand']} و{b['brand']} - تأكد أن ذلك مقصود"
            warnings.append({"type": "duplicate_class", "level": "moderate", "items": [i, j], "message": msg})

    tokens = [(i, _tokens(it, class_map)) for i, it in systemic]
    for side_a, side_b, level, message in _INTERACTIONS:
        for (i, ta), (j, tb) in combinations(tokens, 2):
            if (ta & side_a and tb & side_b) or (ta & side_b and tb & side_a):
                pair = f"{items[i]['brand']} + {items[j]['brand']}"
                warnings.append(
                    {"type": "interaction", "level": level, "items": [i, j], "message": f"{pair}: {message}"}
                )
    warnings.sort(key=lambda w: _LEVEL_ORDER.get(w["level"], 9))
    return warnings
