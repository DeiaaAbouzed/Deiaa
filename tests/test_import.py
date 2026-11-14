"""Smart import of messy lab spreadsheets and friendly validation errors."""
import os
import sys

import numpy as np
import openpyxl
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from medstatix.core.smartimport import smart_read_excel, tidy_grid, guess_roles, columns_to_groups, column_groups_candidate  # noqa: E402
from medstatix.core.result import AnalysisError  # noqa: E402
from medstatix.analyses.registry import run  # noqa: E402
from medstatix.core.advisor import auto_analyze  # noqa: E402

GROUPS = ["Control", "Drug 200 mg/kg", "Injury", "Injury + Drug 200", "Injury + Drug 100"]


def _stacked_workbook(path):
    """Several marker tables stacked on one sheet, groups in rows, animals in columns, Mean column and Mean ± SD row."""
    rng = np.random.default_rng(0)
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Markers - individual values (n=8 per group)"]); ws.merge_cells("A1:J1"); ws.append([])
    for marker, base in [("MarkerA (ng/mg)", [0.5, 0.55, 1.5, 0.6, 0.9]), ("MarkerB (pg/mg)", [20, 22, 80, 30, 50])]:
        ws.append([marker]); ws.append(["Group"] + [f"Subject {i}" for i in range(1, 9)] + ["Mean (Calculated)"])
        for g, m in zip(GROUPS, base):
            v = list(np.round(rng.normal(m, m * 0.12, 8), 4))
            ws.append([g] + v + [round(float(np.mean(v)), 4)])
        ws.append(["Original Mean ± SD"] + [f"{m} ± 0.1" for m in base]); ws.append([]); ws.append([])
    wb.save(path)


def test_stacked_grouped_tables(tmp_path):
    p = tmp_path / "stacked.xlsx"; _stacked_workbook(p)
    df, rep = smart_read_excel(str(p))
    assert df.shape == (40, 5)
    assert list(df.columns) == ["ID", "Group", "Subject", "MarkerA (ng/mg)", "MarkerB (pg/mg)"]
    assert list(df["Group"].cat.categories) == GROUPS          # original order kept (Control first)
    assert df.groupby("Group", observed=True).size().eq(8).all()
    roles = guess_roles(df)
    assert roles["group"][0] == "Group" and set(roles["measure"]) == {"MarkerA (ng/mg)", "MarkerB (pg/mg)"}
    res, aid = auto_analyze(df, "MarkerB (pg/mg)", "Group")
    assert aid in ("anova1", "kruskal")


def test_text_numbers_arabic_digits_and_footer():
    grid = pd.DataFrame([["عنوان الدراسة", None, None], [None, None, None],
                         ["المجموعة", "ALT", "Weight"],
                         ["ضابطة", "٣٢٫٥", "200"], ["ضابطة ", "30,1", "210"], ["دواء", 45, "1,205.5"], ["دواء", "N/A", "199"],
                         ["المتوسط", 36, 400]], dtype=object)
    df, rep = tidy_grid(grid)
    assert len(df) == 4
    assert df["ALT"].tolist()[:3] == [32.5, 30.1, 45.0] and np.isnan(df["ALT"].iloc[3])
    assert df["Weight"].iloc[2] == 1205.5
    assert df["المجموعة"].nunique() == 2


def test_prism_column_table():
    grid = pd.DataFrame([["MDA"], ], dtype=object)
    grid = pd.DataFrame([["MDA", None, None], ["Control", "CCl4", "CCl4+Sily"], [2.1, 6.0, 3.1], [2.3, 5.8, 3.3], [2.0, 6.2, None]], dtype=object)
    df, _ = tidy_grid(grid)
    assert column_groups_candidate(df)
    long = columns_to_groups(df, value_name=df.attrs["title"])
    assert long.shape == (8, 3) and list(long.columns) == ["Group", "Replicate", "MDA"]


def test_friendly_validation():
    df = pd.DataFrame({"ID": [f"P{i}" for i in range(30)], "G": ["a", "b", "c"] * 10, "Y": np.arange(30.0)})
    with pytest.raises(AnalysisError) as e:
        run("ttest_ind", df, outcome="Y", group="ID")
    assert e.value.ar and "ID" in e.value.ar
    with pytest.raises(AnalysisError):
        run("anova1", df, outcome="G", group="G")
    with pytest.raises(AnalysisError):
        auto_analyze(df, "Y", "Y")
