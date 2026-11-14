"""Friendly, bilingual error messages: what went wrong and what to do about it."""
from __future__ import annotations

import re
import traceback

import numpy as np
import pandas as pd

from .result import AnalysisError
from .settings import SETTINGS

# (regex on the English message, English hint, Arabic text) – {0}, {1} = regex groups
PATTERNS = [
    (r"Variable '(.+)' has no numeric values", "Variable '{0}' contains no numbers.",
     "المتغير «{0}» لا يحتوي على أرقام. اختر متغيرًا رقميًا (مثل قيم القياس)، وتأكد في إكسل أن الخلايا أرقام وليست نصًا."),
    (r"Variable '(.+)' not found", "Variable '{0}' was not found.", "المتغير «{0}» غير موجود في البيانات الحالية."),
    (r"Group '(.+)' has fewer than (\d+) observations", "Group '{0}' has fewer than {1} values.",
     "المجموعة «{0}» بها أقل من {1} قيم. تأكد من إدخال القيم الفردية لكل حيوان/مريض في صف مستقل، وأن اسم المجموعة مكتوب بنفس الطريقة في كل الصفوف."),
    (r"'(.+)' must have exactly 2 groups \(found (\d+)\)", "'{0}' must have exactly 2 groups (found {1}).",
     "هذا الاختبار يقارن مجموعتين فقط، والمتغير «{0}» به {1} مجموعات. استخدم تحليل التباين الأحادي (One-way ANOVA) أو كروسكال-واليس، أو اضغط «التحليل الذكي»."),
    (r"'(.+)' must have exactly two categories \(found (\d+)\)", "'{0}' must have exactly two categories (found {1}).",
     "المتغير «{0}» يجب أن يحتوي على فئتين فقط (مثل نعم/لا أو 0/1)، ووُجد به {1} فئات."),
    (r"Select at least (\w+)", "Select at least {0} variable(s).", "اختر {0} متغير على الأقل."),
    (r"Need at least 3 complete pairs", "Need at least 3 complete pairs.", "يلزم 3 أزواج كاملة على الأقل (قيمتان لنفس الحالة في نفس الصف)."),
    (r"Need at least 2 groups", "Need at least 2 groups.", "يلزم وجود مجموعتين على الأقل في متغير المجموعة."),
    (r"Doses must be > 0", "Doses must be > 0 for log transformation.", "الجرعات يجب أن تكون أكبر من صفر عند استخدام اللوغاريتم. احذف مجموعة الصفر (الضابطة) أو اختر جرعة خطية."),
    (r"perfect separation", "The model failed (perfect separation or too few events).",
     "فشل النموذج: إما أن أحد المتغيرات يفصل النتيجة تمامًا، أو أن عدد الأحداث قليل جدًا. قلل عدد المتغيرات المستقلة."),
    (r"did not converge", "The model did not converge.", "لم يتقارب النموذج. جرّب تقليل عدد المتغيرات أو التحقق من القيم الشاذة."),
    (r"Survival times must be non-negative", "Survival times must be ≥ 0.", "أزمنة البقاء يجب أن تكون صفرًا أو أكثر."),
    (r"Responders cannot exceed n", "Responders cannot exceed n.", "عدد المستجيبين لا يمكن أن يزيد عن العدد الكلي."),
]

GENERIC_EN = ("The analysis could not run with the selected variables. Common causes: an ID column was chosen as the group, "
              "the same variable was chosen twice, the outcome is text instead of numbers, or a group has only one value.")
GENERIC_AR = ("تعذّر إجراء التحليل بالمتغيرات المختارة. الأسباب الشائعة:\n"
              "• اختيار عمود رقم الحالة (ID) كمتغير للمجموعة.\n"
              "• اختيار نفس المتغير مرتين.\n"
              "• المتغير التابع نص وليس أرقامًا.\n"
              "• مجموعة بها قيمة واحدة فقط.\n\n"
              "الحل الأسرع: استخدم «التحليل الذكي» واختر المتغير التابع (القياس) والمجموعة، وسيختار البرنامج الاختبار المناسب.")


def ar() -> bool:
    return SETTINGS.language == "ar"


def bi(en, ar_text):
    return ar_text if ar() else en


def friendly(exc: Exception) -> tuple[str, str]:
    """Return (message, technical details) for any exception, in the interface language."""
    details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__, limit=4))
    if isinstance(exc, AnalysisError):
        if ar() and getattr(exc, "ar", None):
            return exc.ar, details
        msg = str(exc)
        for pat, en, ar_t in PATTERNS:
            m = re.search(pat, msg, re.I)
            if m:
                g = m.groups()
                return (ar_t if ar() else en).format(*g), details
        return msg, details
    return bi(GENERIC_EN, GENERIC_AR), details


# --------------------------------------------------------------------------- validation
ID_LIKE_ROLES = {"var_cat"}


def _missing(v):
    return v is None or (isinstance(v, float) and np.isnan(v)) or (isinstance(v, str) and not v.strip())


def validate(analysis, df: pd.DataFrame, kwargs: dict):
    """Check variable choices before running; raise AnalysisError with bilingual guidance."""
    singles = {}
    for p in analysis.params:
        if not p.kind.startswith("var"):
            continue
        v = kwargs.get(p.name)
        if p.kind.startswith("vars"):
            if not v and not p.optional:
                raise AnalysisError(f"Choose at least one variable for '{p.en}'.", f"اختر متغيرًا واحدًا على الأقل في خانة «{p.ar}».")
            cols = list(v or [])
        else:
            if _missing(v):
                if p.optional:
                    continue
                raise AnalysisError(f"Choose a variable for '{p.en}'.", f"اختر متغيرًا في خانة «{p.ar}».")
            cols = [v]
            if v in singles:
                raise AnalysisError(f"'{v}' was chosen for both '{singles[v][0]}' and '{p.en}'. Choose different variables.",
                                    f"تم اختيار «{v}» في خانتين: «{singles[v][1]}» و«{p.ar}». اختر متغيرًا مختلفًا لكل خانة.")
            singles[v] = (p.en, p.ar)
        for c in cols:
            if c not in df.columns:
                raise AnalysisError(f"Variable '{c}' not found.", f"المتغير «{c}» غير موجود في البيانات الحالية.")
            s = df[c]
            if p.kind in ("var_num", "vars_num"):
                num = pd.to_numeric(s, errors="coerce")
                if num.notna().sum() == 0:
                    raise AnalysisError(f"'{c}' contains no numbers, but '{p.en}' needs a numeric variable.",
                                        f"الخانة «{p.ar}» تحتاج متغيرًا رقميًا، لكن «{c}» لا يحتوي على أرقام (نص أو فئات). "
                                        "اختر عمود القياس الرقمي.")
            if p.kind == "var_cat":
                k = s.dropna().nunique()
                if k < 2:
                    raise AnalysisError(f"'{c}' has only {k} category; at least 2 are needed.",
                                        f"المتغير «{c}» به فئة واحدة فقط، والمطلوب فئتان على الأقل.")
                if k > 20 and k > 0.5 * s.notna().sum():
                    raise AnalysisError(f"'{c}' has {k} different values (one per row) — it looks like an ID or a measurement, not a grouping variable.",
                                        f"المتغير «{c}» به {k} قيمة مختلفة (تقريبًا قيمة لكل صف)، فهو يبدو رقم حالة (ID) أو قياسًا وليس متغير مجموعة. "
                                        "اختر العمود الذي يحتوي أسماء المجموعات (مثل Group).")
    # same variable as outcome and predictor
    outcome = kwargs.get("outcome")
    for key in ("predictors", "covariates", "categorical"):
        if outcome and kwargs.get(key) and outcome in kwargs[key]:
            raise AnalysisError(f"'{outcome}' cannot be both the outcome and a predictor.",
                                f"لا يمكن أن يكون «{outcome}» متغيرًا تابعًا ومستقلًا في نفس الوقت.")


def validate_smart(df: pd.DataFrame, outcome, factor):
    if _missing(outcome) or outcome not in df.columns:
        raise AnalysisError("Choose the outcome variable.", "اختر المتغير التابع (القياس الذي تريد تحليله).")
    if factor is not None and factor == outcome:
        raise AnalysisError("The outcome and the group must be different variables.",
                            "المتغير التابع والمجموعة يجب أن يكونا متغيرين مختلفين.")
    s = df[outcome].dropna()
    if s.nunique() < 2:
        raise AnalysisError(f"'{outcome}' has fewer than 2 different values.", f"المتغير «{outcome}» لا يحتوي على قيمتين مختلفتين على الأقل.")
    if not pd.api.types.is_numeric_dtype(s) and s.nunique() > 20 and s.nunique() > 0.5 * len(s):
        raise AnalysisError(f"'{outcome}' looks like an ID column (text, one value per row). Choose a measurement.",
                            f"«{outcome}» يبدو عمود أرقام حالات (نص مختلف في كل صف). اختر عمود القياس كمتغير تابع.")
    if factor is not None:
        f = df[factor].dropna()
        k = f.nunique()
        if k < 2:
            raise AnalysisError(f"'{factor}' has only one group.", f"المتغير «{factor}» به مجموعة واحدة فقط.")
        num = pd.api.types.is_numeric_dtype(f)
        if not num and k > 20 and k > 0.5 * len(f):
            raise AnalysisError(f"'{factor}' has {k} different values — it looks like an ID, not a group.",
                                f"«{factor}» به {k} قيمة مختلفة، فهو يبدو رقم حالة (ID) وليس متغير مجموعة. اختر عمود المجموعات (مثل Group).")
