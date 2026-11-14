"""Smart spreadsheet import.

Real lab spreadsheets are rarely tidy. They often have title rows, merged cells, several
tables stacked on one sheet (one per marker), groups written in rows with animals in
columns, "Mean" or "Mean ± SD" rows and columns, numbers stored as text, Arabic-Indic
digits, and so on.

``smart_read`` turns such a sheet into one tidy table (one row per subject, one column
per variable). It also returns a bilingual report of every change it made.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
MISSING_TOKENS = {"", "-", "--", "—", "na", "n/a", "nan", "none", "null", ".", "?", "؟", "missing", "nd", "n.d.", "لا يوجد", "مفقود"}
SUMMARY_RE = re.compile(r"(mean|average|avg|\bsd\b|s\.d|\bsem\b|s\.e|std|total|sum|median|calculated|±|"
                        r"المتوسط|متوسط|الانحراف|المجموع|الوسيط)", re.I)
REPLICATE_RE = re.compile(r"^\s*(subject|subj|rat|mouse|mice|animal|rep|replicate|sample|case|patient|no\.?|n|#|s|r|a|"
                          r"حيوان|فأر|جرذ|عينة|مكرر|حالة|مريض)?\s*[-_ ]?\s*\d+\s*$", re.I)
GROUP_HDR_RE = re.compile(r"^(group|groups|treatment|groupname|المجموعة|المجموعات|مجموعة|المعالجة)$", re.I)


# --------------------------------------------------------------------------- cells
def to_number(v):
    """Convert one cell to float if it is a number written as text; return None if not numeric."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool):
        return float(v)
    s = str(v).strip().translate(AR_DIGITS).replace("٫", ".").replace("٬", "").replace("٪", "%")
    if s.lower() in MISSING_TOKENS:
        return np.nan
    s = s.replace(" ", "").replace(" ", "")
    if re.fullmatch(r"[-+]?\d{1,3}(,\d{3})+(\.\d+)?", s):          # 1,234.5
        s = s.replace(",", "")
    elif re.fullmatch(r"[-+]?\d+,\d+", s):                           # 12,5 (decimal comma)
        s = s.replace(",", ".")
    s = s.rstrip("%")
    try:
        return float(s)
    except ValueError:
        return None


def is_missing(v):
    if v is None:
        return True
    if isinstance(v, float) and np.isnan(v):
        return True
    return isinstance(v, str) and v.strip().lower() in MISSING_TOKENS


def _txt(v):
    return "" if is_missing(v) else str(v).strip()


# --------------------------------------------------------------------------- report
class Report(list):
    def add(self, en, ar, level="info"):
        self.append({"en": en, "ar": ar, "level": level})


# --------------------------------------------------------------------------- blocks
def _split_blocks(grid: pd.DataFrame):
    """Split a raw grid into blocks separated by fully blank rows."""
    blank = grid.apply(lambda r: all(is_missing(v) for v in r), axis=1).to_numpy()
    blocks, start = [], None
    for i, b in enumerate(list(blank) + [True]):
        if not b and start is None:
            start = i
        elif b and start is not None:
            blocks.append(grid.iloc[start:i])
            start = None
    return blocks


def _parse_block(block: pd.DataFrame, rep: Report):
    """Return dict(title, header, rows) where rows are lists of raw values (after title rows)."""
    rows = [list(r) for r in block.itertuples(index=False)]
    titles = []
    while rows and sum(not is_missing(v) for v in rows[0]) == 1 and len(rows) > 1:
        titles.append(next(_txt(v) for v in rows[0] if not is_missing(v)))
        rows.pop(0)
    if not rows:
        return None
    header = [_txt(v) for v in rows[0]]
    body = rows[1:]
    # a header row should be mostly text; if it is mostly numeric there is no header
    nums = sum(to_number(v) is not None and not is_missing(v) for v in rows[0])
    if nums > len([h for h in header if h]) / 2:
        header = [f"V{i + 1}" for i in range(len(rows[0]))]
        body = rows
    return {"title": titles[-1] if titles else "", "titles": titles, "header": header, "rows": body}


def _drop_empty_cols(header, rows):
    keep = [j for j in range(len(header)) if header[j] or any(not is_missing(r[j]) for r in rows)]
    return [header[j] for j in keep], [[r[j] for j in keep] for r in rows]


def _is_summary_row(r):
    first = _txt(r[0])
    return bool(first and SUMMARY_RE.search(first)) or any(isinstance(v, str) and "±" in v for v in r)


def _groups_in_rows(header, rows):
    """Prism 'grouped' layout: first column = group names, other columns = replicates."""
    if len(header) < 3 or not rows:
        return False
    first = [r[0] for r in rows]
    if not all(isinstance(v, str) and to_number(v) is None for v in first if not is_missing(v)):
        return False
    rest = [h for h in header[1:] if h and not SUMMARY_RE.search(h)]
    rep_like = sum(bool(REPLICATE_RE.match(h)) for h in rest)
    head_ok = GROUP_HDR_RE.match(header[0] or "") or not header[0]
    vals = [to_number(v) for r in rows for v in r[1:]]
    numeric_frac = np.mean([v is not None for v in vals]) if vals else 0
    return rest and rep_like >= 0.6 * len(rest) and numeric_frac > 0.8 and (head_ok or rep_like == len(rest))


def _unique_names(names):
    out, seen = [], {}
    for i, n in enumerate(names):
        n = n or f"Var{i + 1}"
        n = re.sub(r"\s+", " ", n).strip()
        if n in seen:
            seen[n] += 1
            n = f"{n}_{seen[n]}"
        else:
            seen[n] = 1
        out.append(n)
    return out


def _clean_columns(df: pd.DataFrame, rep: Report):
    """Convert text-numbers, tidy category spellings."""
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s):
            continue
        conv = s.map(to_number)
        nonmiss = s.map(lambda v: not is_missing(v))
        ok = conv.map(lambda v: v is not None)
        n_nonmiss = int(nonmiss.sum())
        if n_nonmiss and (ok & nonmiss).sum() >= 0.8 * n_nonmiss:
            bad = int((nonmiss & ~ok).sum())
            had_text = bool(s[nonmiss].map(lambda v: isinstance(v, str)).any())
            df[c] = conv.map(lambda v: np.nan if v is None else v).astype(float)
            if had_text:
                rep.add(f"'{c}': numbers stored as text were converted to numbers" + (f" ({bad} non-numeric cell(s) set to missing)" if bad else "") + ".",
                        f"«{c}»: تم تحويل أرقام مكتوبة كنص إلى أرقام" + (f" (وتحويل {bad} خلية غير رقمية إلى قيمة مفقودة)" if bad else "") + ".",
                        "warn" if bad else "info")
        else:
            txt = s.map(lambda v: np.nan if is_missing(v) else re.sub(r"\s+", " ", str(v)).strip())
            # unify spellings that differ only by case/spaces (e.g. "Control" vs "control ")
            canon = {}
            for v in txt.dropna():
                canon.setdefault(v.lower(), v)
            fixed = txt.map(lambda v: canon[v.lower()] if isinstance(v, str) else v)
            if (fixed.dropna() != s[fixed.notna()].astype(str)).any():
                n_var = txt.dropna().nunique() - fixed.dropna().nunique()
                if n_var > 0:
                    rep.add(f"'{c}': {n_var} spelling variant(s) differing only in case/spaces were merged.",
                            f"«{c}»: تم توحيد {n_var} كتابة مختلفة لنفس الفئة (اختلاف حروف كبيرة/صغيرة أو مسافات).")
            df[c] = fixed
            if s.map(lambda v: isinstance(v, str) and "±" in v).any():
                rep.add(f"'{c}' contains 'mean ± SD' text. Statistics need the individual values, not summaries.",
                        f"«{c}» يحتوي على قيم بصيغة «المتوسط ± الانحراف». التحليل يحتاج القيم الفردية لكل حالة وليس الملخص.", "warn")
    return df


def _ordered_category(values):
    order = list(dict.fromkeys(v for v in values if isinstance(v, str)))
    return pd.Categorical(values, categories=order, ordered=False)


# --------------------------------------------------------------------------- main
def tidy_grid(grid: pd.DataFrame) -> tuple[pd.DataFrame, Report]:
    """Turn a raw cell grid (header=None) into a tidy DataFrame + report."""
    rep = Report()
    grid = grid.copy()
    grid = grid.loc[:, ~grid.apply(lambda c: all(is_missing(v) for v in c))]
    blocks = [b for b in (_parse_block(b, rep) for b in _split_blocks(grid)) if b]
    if not blocks:
        return pd.DataFrame(), rep
    for b in blocks:
        b["header"], b["rows"] = _drop_empty_cols(b["header"], b["rows"])

    grouped = [b for b in blocks if _groups_in_rows(b["header"], [r for r in b["rows"] if not _is_summary_row(r)])]
    if grouped:
        long = None
        for k, b in enumerate(grouped):
            name = b["title"] or (f"Value{k + 1}" if len(grouped) > 1 else "Value")
            rows = [r for r in b["rows"] if not _is_summary_row(r)]
            n_sum_rows = len(b["rows"]) - len(rows)
            hdr = b["header"]
            rep_cols = [j for j in range(1, len(hdr)) if not (hdr[j] and SUMMARY_RE.search(hdr[j]))]
            dropped_cols = [hdr[j] for j in range(1, len(hdr)) if j not in rep_cols]
            recs = []
            for r in rows:
                g = _txt(r[0])
                if not g:
                    continue
                for idx, j in enumerate(rep_cols, 1):
                    v = to_number(r[j])
                    if v is not None and not np.isnan(v):
                        recs.append({"Group": g, "Subject": idx, name: v})
            part = pd.DataFrame(recs)
            msg_en = f"Table '{name}': groups were in rows and animals/subjects in columns; reshaped to one row per subject"
            msg_ar = f"جدول «{name}»: كانت المجموعات في الصفوف والحيوانات في الأعمدة، فأُعيد ترتيبه بحيث يكون كل حيوان في صف"
            extra_en, extra_ar = [], []
            if dropped_cols:
                extra_en.append("removed summary column(s) " + ", ".join(f"'{c}'" for c in dropped_cols))
                extra_ar.append("وحُذفت أعمدة الملخص (" + "، ".join(dropped_cols) + ")")
            if n_sum_rows:
                extra_en.append(f"removed {n_sum_rows} summary row(s) (mean/SD)")
                extra_ar.append(f"وحُذف {n_sum_rows} صف ملخص (متوسط/انحراف)")
            rep.add(msg_en + ("; " + "; ".join(extra_en) if extra_en else "") + ".",
                    msg_ar + (" " + " ".join(extra_ar) if extra_ar else "") + ".")
            if long is None:
                long = part
            else:
                long = long.merge(part, on=["Group", "Subject"], how="outer", sort=False)
        if len(grouped) > 1:
            rep.add(f"{len(grouped)} tables stacked on the sheet were combined into one dataset (one column per marker). "
                    "Subject k is assumed to be the same animal in every table.",
                    f"تم دمج {len(grouped)} جداول موجودة فوق بعضها في ملف واحد (عمود لكل مؤشر)، "
                    "مع افتراض أن الحيوان رقم k هو نفسه في كل الجداول.")
        others = [b for b in blocks if b not in grouped and b["rows"]]
        if others:
            rep.add(f"{len(others)} other block(s) on the sheet (notes or a different layout) were ignored.",
                    f"تم تجاهل {len(others)} جزء آخر في الصفحة (ملاحظات أو تنسيق مختلف).", "warn")
        order = list(dict.fromkeys(_txt(r[0]) for b in grouped for r in b["rows"] if not _is_summary_row(r) and _txt(r[0])))
        long["Group"] = pd.Categorical(long["Group"], categories=order)
        long = long.sort_values(["Group", "Subject"], kind="stable").reset_index(drop=True)
        long.insert(0, "ID", [f"{g}-{s}" for g, s in zip(long["Group"].astype(str), long["Subject"])])
        long["Group"] = long["Group"].astype(str)
        long["Group"] = _ordered_category(long["Group"].tolist())
        return long, rep

    # ordinary (tidy or column-per-group) tables: use the largest block
    blocks = [b for b in blocks if b["rows"]] or blocks
    blocks.sort(key=lambda b: len(b["rows"]) * len(b["header"]), reverse=True)
    main = blocks[0]
    if main["titles"]:
        rep.add(f"Title row(s) above the table were skipped: {' / '.join(main['titles'])}.",
                f"تم تخطي صفوف العنوان أعلى الجدول: {' / '.join(main['titles'])}.")
    same = [b for b in blocks[1:] if b["header"] == main["header"]]
    rows = main["rows"] + [r for b in same for r in b["rows"]]
    if same:
        rep.add(f"{len(same) + 1} parts with identical headers were stacked into one table.",
                f"تم دمج {len(same) + 1} أجزاء لها نفس العناوين في جدول واحد.")
    if len(blocks) - 1 - len(same) > 0:
        rep.add(f"{len(blocks) - 1 - len(same)} other block(s) on the sheet were ignored (only the main table was read).",
                f"تمت قراءة الجدول الرئيسي فقط وتجاهل {len(blocks) - 1 - len(same)} جزء آخر في الصفحة.", "warn")
    n0 = len(rows)
    rows = [r for r in rows if not _is_summary_row(r)]
    if len(rows) < n0:
        rep.add(f"Removed {n0 - len(rows)} summary row(s) (mean, SD, total…).",
                f"تم حذف {n0 - len(rows)} صف ملخص (متوسط، انحراف، مجموع…).")
    names = _unique_names(main["header"])
    if names != main["header"]:
        rep.add("Empty or duplicated column names were renamed.", "تمت تسمية الأعمدة الفارغة أو المكررة تلقائيًا.")
    df = pd.DataFrame(rows, columns=names)
    sum_cols = [c for c in df.columns if SUMMARY_RE.search(c) and re.search(r"calculated|mean|average|المتوسط", c, re.I)]
    if sum_cols and len(df.columns) > 2:
        df = df.drop(columns=sum_cols)
        rep.add("Removed calculated summary column(s): " + ", ".join(sum_cols) + ".",
                "تم حذف أعمدة الملخص المحسوبة: " + "، ".join(sum_cols) + ".")
    df = df.dropna(how="all").reset_index(drop=True)
    df = _clean_columns(df, rep)
    df.attrs["title"] = main["titles"][-1] if main["titles"] else ""
    return df, rep


def column_groups_candidate(df: pd.DataFrame) -> bool:
    """True if the table looks like a Prism column table (each column = one group, no grouping column)."""
    if df.shape[1] < 2 or df.shape[1] > 20:
        return False
    num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if len(num) != df.shape[1]:
        return False
    counts = df.notna().sum()
    return counts.nunique() > 1 or df.shape[0] <= 30


def columns_to_groups(df: pd.DataFrame, cols=None, group_name="Group", value_name="Value") -> pd.DataFrame:
    cols = list(cols or df.columns)
    recs = []
    for c in cols:
        for i, v in enumerate(df[c].tolist(), 1):
            if pd.notna(v):
                recs.append({group_name: str(c), "Replicate": i, value_name: float(v)})
    out = pd.DataFrame(recs)
    out[group_name] = pd.Categorical(out[group_name], categories=[str(c) for c in cols])
    return out


def sheet_names(path: str) -> list[str]:
    import openpyxl
    if path.lower().endswith((".xlsx", ".xlsm")):
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        names = [ws.title for ws in wb.worksheets if (ws.max_row or 0) > 0]
        wb.close()
        return names
    return list(pd.ExcelFile(path).sheet_names)


def smart_read_excel(path: str, sheet=0) -> tuple[pd.DataFrame, Report]:
    grid = pd.read_excel(path, sheet_name=sheet, header=None, dtype=object)
    return tidy_grid(grid)


def smart_read_csv(path: str) -> tuple[pd.DataFrame, Report]:
    grid = None
    for enc in ("utf-8-sig", "cp1256", "latin-1"):
        try:
            grid = pd.read_csv(path, sep=None, engine="python", header=None, dtype=object, encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    return tidy_grid(grid)


# --------------------------------------------------------------------------- roles
ID_NAME_RE = re.compile(r"^(id|subject|subj|rep|replicate|no\.?|#|serial|code|case|animal|rat|patient|name|"
                        r"رقم.*|م|مسلسل|الكود|كود|الاسم|اسم)(\s*(id|no\.?|number|#))?$", re.I)


def guess_roles(df: pd.DataFrame) -> dict:
    """Classify columns: 'id' (identifiers), 'group' (grouping factors, best first), 'measure' (numeric outcomes)."""
    ids, groups, measures, binaries = [], [], [], []
    n = len(df)
    for c in df.columns:
        s = df[c].dropna()
        k = s.nunique()
        num = pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)
        name = str(c).strip()
        seq = num and k == len(s) and k > 3 and s.min() in (0, 1) and np.allclose(np.sort(s.to_numpy(float)), np.arange(s.min(), s.min() + k))
        if ID_NAME_RE.match(name) or (not num and k > 20 and k > 0.5 * max(n, 1)) or seq:
            ids.append(c)
        elif not num and 2 <= k <= 15:
            groups.append(c)
            if k == 2:
                binaries.append(c)
        elif num and k == 2:
            binaries.append(c)
            groups.append(c)
        elif num and k > 2:
            measures.append(c)
    # best group first: closest to 'group' name, then 3-8 levels
    def gscore(c):
        nm = str(c).lower()
        named = bool(re.search(r"group|treat|arm|مجموع|معالج|ذراع", nm))
        k = df[c].nunique()
        return (not named, not (2 <= k <= 10), k)
    groups.sort(key=gscore)
    return {"id": ids, "group": groups, "measure": measures, "binary": binaries}
