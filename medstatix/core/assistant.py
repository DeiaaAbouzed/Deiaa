"""Offline Arabic / English analysis assistant.

The user types a request in plain words ("قارن MDA بين المجموعات", "ارسم خريطة حرارية", "correlation between ALT and AST")
and the assistant turns it into MedStatix analyses on the current data: it recognises the intent from key words and the
variables from the column names (fuzzy matching that tolerates Arabic spelling variants, case, spaces and typos).
It runs locally: no text or data leaves the computer."""
from __future__ import annotations

import difflib
import re

import pandas as pd

AR_NORM = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي", "ـ": ""})
DIAC = re.compile(r"[ً-ْ]")


def norm(s):
    s = DIAC.sub("", str(s)).translate(AR_NORM).lower()
    return re.sub(r"[\s_\-./()]+", " ", s).strip()


INTENTS = [  # (intent, keywords) — first match wins, so specific intents come first
    ("help", ["مساعده", "ماذا تستطيع", "ايه اللي تقدر", "help", "what can you"]),
    ("power", ["حجم العينه", "حجم عينه", "قوه الاختبار", "قوه احصائيه", "sample size", "power analysis", "power", "g*power", "gpower"]),
    ("heatmap", ["خريطه حراريه", "heatmap", "heat map"]),
    ("volcano", ["بركان", "volcano"]),
    ("radar", ["رادار", "عنكبوت", "radar", "spider"]),
    ("survival", ["بقاء", "كابلان", "kaplan", "survival", "km curve"]),
    ("normality", ["طبيعي", "طبيعيه", "توزيع طبيعي", "normality", "normal distribution", "shapiro"]),
    ("chisq", ["كاي", "مربع كاي", "chi", "chi-square", "contingency"]),
    ("regression", ["انحدار", "تنبؤ", "regression", "predict"]),
    ("correlation", ["ارتباط", "علاقه", "correlat", "relationship", "associated with", "سبيرمان", "بيرسون", "spearman", "pearson"]),
    ("describe", ["وصف", "وصفي", "ملخص", "متوسط", "describe", "descriptive", "summary", "summarize", "mean of"]),
    ("compare", ["قارن", "مقارنه", "فرق", "الفروق", "اختلاف", "تاثير", "compare", "comparison", "difference", "differ", "effect of",
                 "t test", "t-test", "anova", "تباين", "مان", "mann", "kruskal", "كروسكال", "versus", " vs "]),
    ("plot", ["ارسم", "رسم", "شكل", "plot", "graph", "chart", "figure"]),
]


def match_columns(text, columns, cutoff=0.82):
    """Return the columns mentioned in `text`, in order of appearance (exact, then fuzzy word-window matching)."""
    t = " " + norm(text) + " "
    found = []
    for c in sorted(columns, key=lambda c: -len(norm(c))):
        nc = norm(c)
        if not nc:
            continue
        pos = t.find(" " + nc + " ")
        if pos < 0 and len(nc) >= 3:
            pos = t.find(nc) if re.search(r"[a-z0-9]", nc) and len(nc) >= 4 else -1
        if pos >= 0 and not any(p <= pos < p + len(norm(f)) + 2 for f, p in found):
            found.append((c, pos))
    words = t.split()
    taken = {c for c, _ in found}
    for c in columns:
        if c in taken:
            continue
        nc = norm(c); k = max(1, len(nc.split()))
        for i in range(len(words) - k + 1):
            w = " ".join(words[i:i + k])
            if len(w) >= 3 and difflib.SequenceMatcher(None, w, nc).ratio() >= cutoff:
                found.append((c, t.find(" " + w + " "))); break
    return [c for c, _ in sorted(found, key=lambda x: x[1])]


def _is_num(s):
    return pd.api.types.is_numeric_dtype(s) and s.nunique(dropna=True) > 2


def _is_id(s, name):
    if re.fullmatch(r"(id|no|code|subject|animal|rat|case|رقم|كود)( ?(id|no|number|رقم))?", norm(name)):
        return True
    v = pd.to_numeric(s, errors="coerce").dropna()
    return len(v) > 5 and v.is_unique and (v.diff().dropna() == 1).all()


def _is_group(s):
    return (not pd.api.types.is_numeric_dtype(s) or isinstance(s.dtype, pd.CategoricalDtype) or s.nunique(dropna=True) <= 6) \
        and 2 <= s.nunique(dropna=True) <= 12


def _default_group(df):
    cands = [c for c in df.columns if _is_group(df[c])]
    pref = [c for c in cands if re.search(r"group|treat|dose|arm|مجموع|معامل|جرع", norm(c))]
    return (pref or cands or [None])[0]


def intent_of(text):
    t = " " + norm(text) + " "
    for name, kws in INTENTS:
        if any(norm(k) in t if not k.startswith(" ") else k in t for k in kws):
            return name
    return None


def parse(text, df):
    """Return a plan: dict(intent, actions=[(kind, aid_or_None, kwargs)], say_en, say_ar) or an explanation."""
    cols = list(df.columns) if df is not None else []
    intent = intent_of(text)
    mentioned = match_columns(text, cols) if cols else []
    nums = [c for c in mentioned if _is_num(df[c])]
    groups = [c for c in mentioned if c not in nums and _is_group(df[c])]
    t = norm(text)
    all_num = [c for c in cols if _is_num(df[c]) and not _is_id(df[c], c)]
    plan = {"intent": intent, "actions": [], "say_en": "", "say_ar": ""}

    def need(msg_en, msg_ar):
        plan.update(say_en=msg_en, say_ar=msg_ar)
        return plan

    if intent == "help" or (intent is None and not mentioned):
        return need("I can compare groups, test correlations, describe variables, check normality, run regression, chi-square "
                    "and survival analysis, draw heatmaps, volcano and radar charts, and compute sample size. Example: "
                    "“compare MDA and GSH between groups”, “correlation between ALT and AST”, “heatmap of all markers”.",
                    "أستطيع مقارنة المجموعات، وحساب الارتباط، ووصف المتغيرات، وفحص التوزيع الطبيعي، والانحدار، ومربع كاي، "
                    "وتحليل البقاء، ورسم الخريطة الحرارية والبركان والرادار، وحساب حجم العينة. أمثلة: «قارن MDA وGSH بين "
                    "المجموعات»، «الارتباط بين ALT وAST»، «ارسم خريطة حرارية لكل المؤشرات».")
    if intent == "power":
        plan["actions"].append(("open", "gpower", {}))
        return need("Opening the G*Power-style power analysis.", "فتح تحليل القوة وحجم العينة بأسلوب G*Power.")
    if df is None or df.empty:
        return need("Please open or paste a data set first.", "افتح ملف بيانات أو الصقه أولاً.")
    if intent is None and nums:
        intent = "compare" if (groups or _default_group(df)) else "describe"
        plan["intent"] = intent
    group = groups[0] if groups else _default_group(df)
    if intent in ("compare", "plot"):
        outcomes = nums or ([c for c in all_num if c != group] if re.search(r"كل|جميع|all|every", t) else [])
        if not outcomes:
            return need("Which variable should I compare? Write its column name, e.g. “compare MDA between groups”.",
                        "أي متغير تريد مقارنته؟ اكتب اسم العمود، مثل «قارن MDA بين المجموعات».")
        if not group:
            return need("I could not find a grouping column. Name it, e.g. “… by Group”.",
                        "لم أجد عمود المجموعات. اذكر اسمه، مثل «… حسب Group».")
        plan["actions"].append(("smart", None, {"outcomes": outcomes, "factor": group}))
        return need(f"Comparing {', '.join(outcomes)} between the levels of {group} (test chosen automatically from the assumptions).",
                    f"مقارنة {', '.join(outcomes)} بين مستويات {group} (يُختار الاختبار تلقائياً حسب فحص الافتراضات).")
    if intent == "correlation":
        vs = nums if len(nums) >= 2 else ([c for c in all_num] if re.search(r"كل|جميع|all", t) or not nums else [])
        if len(vs) < 2:
            return need("Name at least two numeric variables, e.g. “correlation between ALT and AST”.",
                        "اذكر متغيرين رقميين على الأقل، مثل «الارتباط بين ALT وAST».")
        method = "Spearman" if re.search(r"سبيرمان|spearman|الرتب|rank", t) else "Pearson"
        plan["actions"].append(("run", "correlation", {"variables": vs[:12], "method": method}))
        return need(f"{method} correlation of {', '.join(vs[:12])}.", f"معامل ارتباط {method} بين {', '.join(vs[:12])}.")
    if intent == "describe":
        vs = nums or all_num[:12]
        kw = {"variables": vs}
        if groups or re.search(r"حسب|لكل|بين|by|per|each", t):
            kw["group"] = group
        plan["actions"].append(("run", "descriptives", kw))
        return need(f"Descriptive statistics of {', '.join(vs)}" + (f" by {group}." if "group" in kw else "."),
                    f"الإحصاء الوصفي لـ {', '.join(vs)}" + (f" حسب {group}." if "group" in kw else "."))
    if intent == "normality":
        vs = nums or all_num[:12]
        kw = {"variables": vs, **({"group": group} if group else {})}
        plan["actions"].append(("run", "normality", kw))
        return need(f"Normality tests (Shapiro–Wilk) of {', '.join(vs)}.", f"اختبارات التوزيع الطبيعي (شابيرو-ويلك) لـ {', '.join(vs)}.")
    if intent == "regression":
        if len(mentioned) < 2 or not nums:
            return need("Name the outcome first, then the predictors, e.g. “regression of SBP on age and dose”.",
                        "اذكر المتغير التابع أولاً ثم المتغيرات المستقلة، مثل «انحدار SBP على age وdose».")
        y = nums[0]
        plan["actions"].append(("run", "linreg", {"outcome": y, "predictors": [c for c in mentioned if c != y]}))
        return need(f"Linear regression of {y} on {', '.join(c for c in mentioned if c != y)}.",
                    f"انحدار خطي لـ {y} على {', '.join(c for c in mentioned if c != y)}.")
    if intent == "chisq":
        cats = [c for c in mentioned if c not in nums]
        if len(cats) < 2:
            return need("Name two categorical variables for the chi-square test.", "اذكر متغيرين فئويين لاختبار مربع كاي.")
        plan["actions"].append(("run", "chisq", {"row": cats[0], "col": cats[1]}))
        return need(f"Chi-square test of {cats[0]} × {cats[1]}.", f"اختبار مربع كاي لـ {cats[0]} × {cats[1]}.")
    if intent in ("heatmap", "radar", "volcano"):
        vs = nums if len(nums) >= 2 else [c for c in all_num if c != group]
        if not group or len(vs) < 2:
            return need("This chart needs a group column and at least two numeric variables.",
                        "هذا الرسم يحتاج عمود مجموعات ومتغيرين رقميين على الأقل.")
        kw = {"variables": vs[:30], "group": group}
        plan["actions"].append(("run", intent, kw))
        names = {"heatmap": ("Heatmap", "خريطة حرارية"), "radar": ("Radar chart", "مخطط رادار"), "volcano": ("Volcano plot", "مخطط بركاني")}[intent]
        return need(f"{names[0]} of {len(vs[:30])} variables by {group}.", f"{names[1]} لـ {len(vs[:30])} متغيراً حسب {group}.")
    if intent == "survival":
        time = next((c for c in nums + all_num if re.search(r"time|زمن|مده|day|month|week", norm(c))), nums[0] if nums else None)
        event = next((c for c in cols if re.search(r"event|death|status|حدث|وفاه", norm(c))), None)
        if not time or not event:
            return need("Name the time column and the event column (1 = event, 0 = censored).",
                        "اذكر عمود الزمن وعمود الحدث (1 = حدث، 0 = مراقب).")
        plan["actions"].append(("run", "km", {"time": time, "event": event, **({"group": group} if groups else {})}))
        return need(f"Kaplan–Meier curves of {time} (event: {event}).", f"منحنيات كابلان-ماير لـ {time} (الحدث: {event}).")
    return need("I did not understand the request. Type “help” to see examples.", "لم أفهم الطلب. اكتب «مساعدة» لرؤية أمثلة.")
