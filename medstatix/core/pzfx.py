"""GraphPad Prism .pzfx (XML) import and export.

Import reads every data table (Column, Grouped, XY) into a long ("tidy") DataFrame; export writes Prism Column tables
(one per outcome, one Y column per group), which open directly in Prism 5–10."""
from __future__ import annotations

import datetime as _dt
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd


def _local(tag):
    return tag.split("}", 1)[-1]


def _child(el, name):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _children(el, name):
    return [c for c in el if _local(c.tag) == name]


def _text(el):
    return "".join(el.itertext()).strip() if el is not None else ""


def _num(s):
    s = (s or "").strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return np.nan


def _subcolumns(col):
    out = []
    for sc in _children(col, "Subcolumn"):
        vals = []
        for d in _children(sc, "d"):
            vals.append(np.nan if d.get("Excluded") == "1" else _num(_text(d)))
        out.append(vals)
    return out


def list_tables(path):
    root = ET.parse(path).getroot()
    return [(t.get("ID"), _text(_child(t, "Title")) or t.get("ID"), t.get("TableType", "")) for t in root.iter()
            if _local(t.tag) in ("Table", "HugeTable")]


def read_pzfx(path, table=0):
    """Return (DataFrame, table title). `table` = index or title."""
    root = ET.parse(path).getroot()
    tables = [t for t in root.iter() if _local(t.tag) in ("Table", "HugeTable")]
    if not tables:
        raise ValueError("No data tables found in this Prism file.")
    if isinstance(table, str):
        tables = [t for t in tables if _text(_child(t, "Title")) == table] or tables
        t = tables[0]
    else:
        t = tables[int(table)]
    title = _text(_child(t, "Title")) or "Prism table"
    ttype = t.get("TableType", "OneWay")
    row_titles = []
    rt = _child(t, "RowTitlesColumn")
    if rt is not None:
        sc = _child(rt, "Subcolumn")
        row_titles = [_text(d) for d in _children(sc, "d")] if sc is not None else []
    xcol = _child(t, "XColumn") or _child(t, "XAdvancedColumn")
    xs = _subcolumns(xcol)[0] if xcol is not None and _subcolumns(xcol) else None
    yfmt = (t.get("YFormat") or "replicates").lower()
    stat_names = {"sd": ["Mean", "SD"], "sdn": ["Mean", "SD", "N"], "se": ["Mean", "SEM"], "sen": ["Mean", "SEM", "N"],
                  "cv": ["Mean", "CV%"], "cvn": ["Mean", "CV%", "N"], "low-high": ["Mean", "Plus error", "Minus error"],
                  "upper-lower-limits": ["Mean", "Upper limit", "Lower limit"]}.get(yfmt)
    if stat_names:   # summary-data table (mean, SD/SEM, n): one row per data set and row
        rows = []
        for yi, yc in enumerate(_children(t, "YColumn") + _children(t, "YAdvancedColumn")):
            name = _text(_child(yc, "Title")) or f"Data set {yi + 1}"
            subs = _subcolumns(yc)
            for i in range(max((len(x) for x in subs), default=0)):
                r = {"Row": row_titles[i] if i < len(row_titles) else (xs[i] if xs is not None and i < len(xs) else f"Row {i + 1}"),
                     "Group": name}
                for k, nm in enumerate(stat_names):
                    r[nm] = subs[k][i] if k < len(subs) and i < len(subs[k]) else np.nan
                if not np.isnan(r["Mean"]):
                    rows.append(r)
        df = pd.DataFrame(rows)
        if df.empty:
            raise ValueError("The selected Prism table is empty.")
        return df, title + " (summary data)"
    rows = []
    for yi, yc in enumerate(_children(t, "YColumn") + _children(t, "YAdvancedColumn")):
        name = _text(_child(yc, "Title")) or f"Data set {yi + 1}"
        for ri, sub in enumerate(_subcolumns(yc), 1):
            for i, v in enumerate(sub):
                if np.isnan(v):
                    continue
                r = {"Group": name, "Value": v, "Replicate": ri}
                if xs is not None and i < len(xs):
                    r["X"] = xs[i]
                if row_titles and i < len(row_titles):
                    r["Row"] = row_titles[i]
                elif ttype == "TwoWay":
                    r["Row"] = f"Row {i + 1}"
                rows.append(r)
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("The selected Prism table is empty.")
    if "X" in df.columns:          # XY table → X, then one column per data set (replicates as rows)
        df = df[["X", "Group", "Replicate", "Value"]]
    elif "Row" in df.columns:      # grouped table
        df = df[["Row", "Group", "Replicate", "Value"]]
    else:                          # column table: name the value column after the table (e.g. "MDA (nmol/g)")
        df = df[["Group", "Value"]]
        if title and not title.lower().startswith("data ") and title not in ("Group",):
            df = df.rename(columns={"Value": title})
    df["Group"] = pd.Categorical(df["Group"], categories=list(dict.fromkeys(df["Group"])), ordered=True)
    return df.reset_index(drop=True), title


def _ycol(title, values, decimals=3):
    vals = "".join(f"<d>{'' if pd.isna(v) else repr(float(v))}</d>" for v in values)
    return (f'<YColumn Width="89" Decimals="{decimals}" Subcolumns="1"><Title>{escape(str(title))}</Title>'
            f"<Subcolumn>{vals}</Subcolumn></YColumn>")


def write_pzfx(df: pd.DataFrame, path: str, group: str | None = None, outcomes: list | None = None):
    """One Prism Column table per outcome, one Y column per group (or one Y column per numeric variable)."""
    num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != group]
    outcomes = outcomes or num
    tables = []
    if group:
        levels = list(df[group].cat.categories) if hasattr(df[group], "cat") else list(dict.fromkeys(df[group].dropna()))
        for o in outcomes:
            cols = "".join(_ycol(l, df.loc[df[group] == l, o].dropna().values) for l in levels)
            tables.append((o, cols))
    else:
        tables.append(("Data", "".join(_ycol(c, df[c].dropna().values) for c in outcomes)))
    now = _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    sel = ' Selected="1"'
    seq = "".join(f'<Ref ID="Table{i}"{sel if i == 0 else ""}/>' for i in range(len(tables)))
    body = "".join(f'<Table ID="Table{i}" XFormat="none" TableType="OneWay" EVFormat="AsteriskAfterNumber">'
                   f"<Title>{escape(str(t))}</Title>{cols}</Table>" for i, (t, cols) in enumerate(tables))
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<GraphPadPrismFile PrismXMLVersion="5.00">'
           f'<Created><OriginalVersion CreatedByProgram="MedStatix Pro" CreatedByVersion="1.5" Login="" DateTime="{now}"/></Created>'
           '<InfoSequence><Ref ID="Info0" Selected="1"/></InfoSequence><Info ID="Info0"><Title>Project info 1</Title>'
           '<Notes></Notes></Info>'
           f"<TableSequence>{seq}</TableSequence>{body}</GraphPadPrismFile>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(xml)
    return len(tables)
