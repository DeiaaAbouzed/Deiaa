"""Pure logic: dose parsing, drug matching, safety checks, metrics."""

import pytest

from rushd.ai.lexicon import DrugRecord, Lexicon
from rushd.ai.metrics import compare
from rushd.ai.safety import build_class_map, check, ingredients
from rushd.ai.sig import arabic_instructions, parse_sig
from rushd.ai.text import core_name, norm_strength


@pytest.mark.parametrize(
    "text,form,expected",
    [
        ("1x3 a.c for 5 days", "tablet", "قرص واحد ٣ مرات يومياً (كل ٨ ساعات) قبل الأكل لمدة ٥ أيام"),
        ("1×2 p.c. x 7 days", "tablet", "قرص واحد مرتين يومياً (كل ١٢ ساعة) بعد الأكل لمدة أسبوع"),
        ("5 ml x 3 after meals 5/7", "syrup", "٥ مل ٣ مرات يومياً (كل ٨ ساعات) بعد الأكل لمدة ٥ أيام"),
        ("1/2 x 2", "tablet", "نصف قرص مرتين يومياً (كل ١٢ ساعة)"),
        ("2 puffs q12h", "inhaler", "بختين استنشاق مرتين يومياً (كل ١٢ ساعة)"),
        ("1 amp IM stat", "ampoule", "حقنة واحدة بالعضل جرعة واحدة فوراً"),
        ("prn", "tablet", "قرص واحد عند اللزوم"),
        ("h.s.", "tablet", "قرص واحد مرة واحدة يومياً قبل النوم"),
        (
            "twice daily after food for 2 weeks",
            "capsule",
            "كبسولة واحدة مرتين يومياً (كل ١٢ ساعة) بعد الأكل لمدة أسبوعين",
        ),
        ("قرص مرتين يوميا بعد الأكل لمدة ٥ أيام", "tablet", "قرص واحد مرتين يومياً (كل ١٢ ساعة) بعد الأكل لمدة ٥ أيام"),
        ("1 drop q8h 1/52", "eye_drops", "نقطة واحدة في العين ٣ مرات يومياً (كل ٨ ساعات) لمدة أسبوع"),
        ("2.5 ml x 2", "suspension", "٢٫٥ مل مرتين يومياً (كل ١٢ ساعة)"),
        ("apply bid", "cream", "دهان موضعي على المكان المصاب مرتين يومياً (كل ١٢ ساعة)"),
        ("1x1 empty stomach 1/12", "capsule", "كبسولة واحدة مرة واحدة يومياً على الريق لمدة شهر"),
    ],
)
def test_arabic_instructions(text, form, expected):
    assert arabic_instructions(parse_sig(text, form)) == expected


def test_strength_normalisation():
    assert norm_strength("1 gm") == norm_strength("1000mg") == "1g"
    assert norm_strength("٥٠٠ مجم") == "500mg"
    assert norm_strength("0.5mg") == "500mcg"
    assert core_name("Augmentin 1gm tab") == "augmentin"
    assert core_name("Brufen 600 mg tabs") == "brufen"


@pytest.fixture
def lexicon():
    drugs = [
        DrugRecord(
            1, "Augmentin", "amoxicillin + clavulanic acid", "Penicillin antibiotic", ("tablet",), ("625mg", "1g")
        ),
        DrugRecord(2, "Cataflam", "diclofenac potassium", "NSAID", ("tablet",), ("50mg",)),
        DrugRecord(3, "Brufen", "ibuprofen", "NSAID", ("tablet",), ("400mg", "600mg")),
        DrugRecord(4, "Nexium", "esomeprazole", "PPI", ("tablet",), ("20mg", "40mg")),
        DrugRecord(5, "Panadol", "paracetamol", "Analgesic/antipyretic", ("tablet",), ("500mg",), ("بنادول",)),
        DrugRecord(6, "Congestal", "paracetamol + pseudoephedrine + chlorpheniramine", "Cold & flu combination"),
        DrugRecord(7, "Marevan", "warfarin", "Anticoagulant"),
        DrugRecord(8, "Motilium", "domperidone", "Prokinetic/antiemetic"),
        DrugRecord(9, "Motinorm", "domperidone", "Prokinetic/antiemetic"),
        DrugRecord(10, "Paracetamol", "paracetamol", "Analgesic/antipyretic", is_generic=True),
        DrugRecord(11, "Voltaren", "diclofenac sodium", "NSAID", ("tablet", "gel")),
        DrugRecord(12, "Controloc", "pantoprazole", "PPI"),
    ]
    return Lexicon(drugs)


@pytest.mark.parametrize(
    "reading,expected",
    [
        ("Augmantin", "Augmentin"),
        ("Augmentin 1gm", "Augmentin"),
        ("Cataflan", "Cataflam"),
        ("Brufin 600", "Brufen"),
        ("Nexum", "Nexium"),
        ("Nexuim 40", "Nexium"),
        ("بنادول", "Panadol"),
        ("paracetamol 500", "Paracetamol"),
    ],
)
def test_lexicon_handles_misreadings(lexicon, reading, expected):
    assert lexicon.match(reading)[0].drug.brand == expected


def test_doctor_habit_breaks_ties(lexicon):
    # An ambiguous scribble between two look-alike brands...
    plain = [c.drug.brand for c in lexicon.match("Motinium")[:2]]
    assert plain == ["Motilium", "Motinorm"]
    boosted = lexicon.match("Motinium", doctor_counts={9: 40})
    assert boosted[0].drug.brand == "Motinorm"  # this doctor always writes Motinorm


def test_safety_duplicates_and_interactions(lexicon):
    cmap = build_class_map(lexicon.drugs)

    def item(drug_id, form="tablet"):
        d = lexicon.get(drug_id)
        return {"brand": d.brand, "generic": d.generic, "drug_class": d.drug_class, "form": form}

    warnings = check([item(5), item(6)], cmap)
    assert warnings[0]["type"] == "duplicate_ingredient" and warnings[0]["level"] == "major"
    assert "paracetamol" in warnings[0]["message"]

    warnings = check([item(2), item(3)], cmap)
    assert [w["type"] for w in warnings] == ["duplicate_class"]

    warnings = check([item(7), item(3)], cmap)
    assert warnings[0]["type"] == "interaction" and warnings[0]["level"] == "major"

    assert check([item(7), item(11, form="gel")], cmap) == []  # topical gel is not systemic
    assert check([item(1), item(4)], cmap) == []
    assert {"diclofenac"} == ingredients("diclofenac potassium")
    assert {"aspirin"} == ingredients("acetylsalicylic acid")


def test_metrics_compare():
    ai = [
        {"brand": "Augmentin", "drug_id": 1, "strength": "1g", "sig": {"times_per_day": 2}},
        {"brand": "Motilium", "drug_id": 8, "strength": "", "sig": {}},
    ]
    truth = [
        {"brand": "Augmentin", "drug_id": 1, "strength": "1 gm", "sig": {"times_per_day": 2}, "ai_index": 0},
        {"brand": "Motinorm", "drug_id": 9, "strength": "", "sig": {}, "ai_index": 1},
        {"brand": "Nexium", "drug_id": 4, "strength": "40mg", "sig": {}},
    ]
    result = compare(ai, truth)
    assert result.pairs == [(0, 0), (1, 1)]
    assert result.name_correct == {0: True, 1: False}
    assert result.acc_drug == pytest.approx(1 / 3)
    assert result.items_changed == 2  # one misread + one missed
    assert result.acc_fields == 1.0
    assert 0 < result.cer < 1
