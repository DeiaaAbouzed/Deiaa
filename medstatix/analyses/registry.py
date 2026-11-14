"""Declarative registry of analyses.

Each analysis declares its parameters; the UI builds the dialog
automatically from this specification, so adding a new test means writing
one function and one ``register`` call.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

CATEGORIES = [
    ("describe", "Descriptive statistics", "الإحصاء الوصفي"),
    ("compare", "Compare groups (means)", "مقارنة المجموعات"),
    ("repeated", "Repeated measures & mixed models", "القياسات المتكررة والنماذج المختلطة"),
    ("categorical", "Categorical data", "البيانات الفئوية"),
    ("correlation", "Correlation", "الارتباط"),
    ("regression", "Regression models", "نماذج الانحدار"),
    ("survival", "Survival analysis", "تحليل البقاء"),
    ("diagnostic", "Diagnostic accuracy & ROC", "دقة الاختبارات التشخيصية و ROC"),
    ("agreement", "Agreement & reliability", "الاتفاق والثبات"),
    ("pharmtox", "Pharmacology & toxicology", "الفارماكولوجي والسموم"),
    ("multivariate", "Multivariate", "التحليل متعدد المتغيرات"),
    ("meta", "Meta-analysis", "التحليل التجميعي"),
    ("power", "Sample size & power", "حجم العينة والقوة"),
]


@dataclass
class Param:
    name: str
    en: str
    ar: str
    kind: str  # var_num | var_cat | var_any | vars_num | vars_any | choice | float | int | bool | text
    options: list = field(default_factory=list)
    default: Any = None
    optional: bool = False


@dataclass
class Analysis:
    id: str
    category: str
    en: str
    ar: str
    func: Callable
    params: list
    desc_en: str = ""
    desc_ar: str = ""
    needs_data: bool = True


REGISTRY: dict[str, Analysis] = {}


def register(id, category, en, ar, params, desc_en="", desc_ar="", needs_data=True):
    def deco(func):
        REGISTRY[id] = Analysis(id, category, en, ar, func, params, desc_en, desc_ar, needs_data)
        return func
    return deco


def P(name, en, ar, kind, options=None, default=None, optional=False):
    return Param(name, en, ar, kind, options or [], default, optional)


# common option lists
ALT = ["two-sided", "less", "greater"]
POSTHOC = ["Tukey HSD", "Bonferroni", "Holm", "Šidák", "Dunnett (vs first group)", "Games-Howell", "Fisher LSD", "None"]
P_ADJ = ["Holm", "Bonferroni", "Benjamini-Hochberg (FDR)", "Šidák", "None"]


def run(analysis_id: str, df, **kwargs):
    a = REGISTRY[analysis_id]
    if a.needs_data:
        return a.func(df, **kwargs)
    return a.func(**kwargs)
