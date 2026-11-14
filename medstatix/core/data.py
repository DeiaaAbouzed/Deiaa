"""Data import/export and variable helpers."""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from .result import AnalysisError

IMPORT_FILTER = ("All supported (*.xlsx *.xls *.csv *.txt *.tsv *.sav *.dta *.sas7bdat);;"
                 "Excel (*.xlsx *.xls);;CSV (*.csv *.txt *.tsv);;SPSS (*.sav);;Stata (*.dta);;SAS (*.sas7bdat)")


def load_file(path: str, sheet=0) -> tuple[pd.DataFrame, dict]:
    """Returns (DataFrame, value_labels) where value_labels maps column -> {code: label}."""
    ext = os.path.splitext(path)[1].lower()
    labels: dict = {}
    if ext in (".xlsx", ".xls", ".xlsm"):
        df = pd.read_excel(path, sheet_name=sheet)
    elif ext in (".csv", ".txt", ".tsv"):
        df = pd.read_csv(path, sep=None, engine="python")
    elif ext == ".sav":
        import pyreadstat
        df, meta = pyreadstat.read_sav(path, apply_value_formats=False)
        labels = dict(meta.variable_value_labels or {})
        for col, mapping in labels.items():
            if col in df.columns:
                df[col] = df[col].map(lambda v, m=mapping: m.get(v, v))
    elif ext == ".dta":
        df = pd.read_stata(path)
    elif ext == ".sas7bdat":
        df = pd.read_sas(path)
    else:
        raise AnalysisError(f"Unsupported file type: {ext}")
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all").dropna(axis=1, how="all")
    return df.reset_index(drop=True), labels


def save_file(df: pd.DataFrame, path: str):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx",):
        df.to_excel(path, index=False)
    elif ext == ".sav":
        import pyreadstat
        pyreadstat.write_sav(df, path)
    elif ext == ".dta":
        df.to_stata(path, write_index=False)
    else:
        df.to_csv(path, index=False, encoding="utf-8-sig")


def is_numeric(s: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)


def var_kind(s: pd.Series) -> str:
    """continuous | categorical | binary"""
    nun = s.dropna().nunique()
    if nun == 2:
        return "binary"
    if is_numeric(s) and nun > 7:
        return "continuous"
    if is_numeric(s):
        return "continuous" if nun > 5 else "categorical"
    return "categorical"


def numeric(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        raise AnalysisError(f"Variable '{col}' not found.")
    s = pd.to_numeric(df[col], errors="coerce")
    if s.notna().sum() == 0:
        raise AnalysisError(f"Variable '{col}' has no numeric values.")
    return s


def group_arrays(df: pd.DataFrame, outcome: str, group: str, min_n=2) -> dict:
    y = numeric(df, outcome)
    g = df[group]
    d = pd.DataFrame({"y": y, "g": g}).dropna()
    order = _level_order(df[group])
    out = {}
    for lev in order:
        v = d.loc[d.g == lev, "y"].to_numpy(float)
        if len(v):
            out[str(lev)] = v
    for k, v in out.items():
        if len(v) < min_n:
            raise AnalysisError(f"Group '{k}' has fewer than {min_n} observations.")
    return out


def _level_order(s: pd.Series):
    if isinstance(s.dtype, pd.CategoricalDtype):
        return [c for c in s.cat.categories if c in set(s.dropna())]
    vals = s.dropna().unique().tolist()
    try:
        return sorted(vals)
    except TypeError:
        return vals


def binary01(df: pd.DataFrame, col: str, positive=None) -> tuple[pd.Series, str]:
    """Convert a two-level variable to 0/1. Returns (series, label_of_positive)."""
    s = df[col]
    levels = _level_order(s)
    if len(levels) != 2:
        raise AnalysisError(f"'{col}' must have exactly two categories (found {len(levels)}).")
    if positive is None or str(positive) == "":
        # numeric 0/1 -> 1 positive ; otherwise the second sorted level
        pos = 1 if set(levels) <= {0, 1, 0.0, 1.0} else levels[1]
    else:
        pos = [l for l in levels if str(l) == str(positive)]
        pos = pos[0] if pos else levels[1]
    out = s.map(lambda v: np.nan if pd.isna(v) else (1.0 if v == pos else 0.0))
    return out.astype(float), str(pos)


def make_sample_datasets() -> dict:
    """Small classic datasets for learning and validation (embedded so the app works offline)."""
    rng = np.random.default_rng(2026)
    pg = pd.DataFrame({
        "weight": [4.17, 5.58, 5.18, 6.11, 4.50, 4.61, 5.17, 4.53, 5.33, 5.14,
                   4.81, 4.17, 4.41, 3.59, 5.87, 3.83, 6.03, 4.89, 4.32, 4.69,
                   6.31, 5.12, 5.54, 5.50, 5.37, 5.29, 4.92, 6.15, 5.80, 5.26],
        "group": ["ctrl"] * 10 + ["trt1"] * 10 + ["trt2"] * 10,
    })
    aml = pd.DataFrame({
        "time": [9, 13, 13, 18, 23, 28, 31, 34, 45, 48, 161, 5, 5, 8, 8, 12, 16, 23, 27, 30, 33, 43, 45],
        "status": [1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 0, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1],
        "x": ["Maintained"] * 11 + ["Nonmaintained"] * 12,
    })
    beetle = pd.DataFrame({
        "dose_mg_L": np.round(10 ** np.array([1.6907, 1.7242, 1.7552, 1.7842, 1.8113, 1.8369, 1.8610, 1.8839]), 3),
        "n": [59, 60, 62, 56, 63, 59, 62, 60],
        "dead": [6, 13, 18, 28, 52, 53, 61, 60],
    })
    # simulated clinical trial
    n = 120
    grp = np.repeat(["Placebo", "Drug A"], n // 2)
    age = rng.normal(55, 10, n).round(0)
    sex = rng.choice(["Male", "Female"], n)
    base = rng.normal(150, 15, n).round(1)
    eff = np.where(grp == "Drug A", -12, -3)
    sbp4 = (base + eff + rng.normal(0, 9, n)).round(1)
    sbp8 = (sbp4 + np.where(grp == "Drug A", -5, -1) + rng.normal(0, 6, n)).round(1)
    lin = -6 + 0.06 * age + 0.03 * (base - 150) + np.where(grp == "Drug A", -0.9, 0)
    event = (rng.uniform(size=n) < 1 / (1 + np.exp(-lin))).astype(int)
    crp = np.exp(rng.normal(1.2, 0.6, n) + np.where(grp == "Drug A", -0.3, 0)).round(2)
    marker = (rng.normal(0, 1, n) + 1.4 * event).round(3)
    ttime = rng.exponential(np.where(grp == "Drug A", 30, 18)).round(1)
    cens = rng.uniform(5, 40, n)
    trial = pd.DataFrame({
        "id": np.arange(1, n + 1), "group": grp, "sex": sex, "age": age, "SBP_0": base, "SBP_4": sbp4, "SBP_8": sbp8,
        "CRP": crp, "biomarker": marker, "MACE": event,
        "time_months": np.minimum(ttime, cens).round(1), "death": (ttime <= cens).astype(int),
        "rater1": rng.integers(1, 4, n),
    })
    trial["rater2"] = np.where(rng.uniform(size=n) < 0.75, trial.rater1, rng.integers(1, 4, n))
    trial["methodA"] = rng.normal(100, 15, n).round(1)
    trial["methodB"] = (trial.methodA + rng.normal(2, 5, n)).round(1)
    return {"Clinical trial (simulated)": trial, "PlantGrowth (ANOVA)": pg,
            "AML survival (Cox/KM)": aml, "Beetle mortality (probit LD50)": beetle}
