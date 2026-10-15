"""CSV files that people open in Excel.

Excel runs a cell that starts like a formula (CSV injection), and many values in Rushd come from
people's typing (learned drug names, user names), so such text cells get a leading apostrophe and
stay plain text. Numbers are written as numbers. The BOM makes Excel read Arabic as UTF-8.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
BOM = "﻿"


def safe_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    text = str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def to_csv(header: list[str], rows: Iterable[Iterable]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in rows:
        writer.writerow([safe_cell(value) for value in row])
    return BOM + buf.getvalue()
