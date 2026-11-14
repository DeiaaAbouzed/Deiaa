"""Result container shared by every analysis.

An analysis returns a ``Result`` holding an ordered list of blocks
(headings, tables, notes, figures, methods prose). The same object is
rendered to the on-screen output viewer (HTML), to Word and to Excel.
"""
from __future__ import annotations

import base64
import html
import io
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

APP_NAME = "MedStatix Pro"
APP_VERSION = "1.1.0"


# ----------------------------------------------------------------------------
# Number formatting (journal style)
# ----------------------------------------------------------------------------
def fmt_p(p: float | None, digits: int = 3) -> str:
    """APA/journal style p value: exact to 3 dp, '< .001' below threshold."""
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "—"
    if p < 0.001:
        return "< 0.001"
    return f"{p:.{digits}f}"


def stars(p: float | None) -> str:
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return ""
    if p < 0.0001:
        return "****"
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return "ns"


def fmt_num(x: Any, digits: int = 3) -> str:
    if x is None:
        return "—"
    if isinstance(x, (str,)):
        return x
    if isinstance(x, (bool, np.bool_)):
        return "Yes" if x else "No"
    if isinstance(x, (int, np.integer)):
        return f"{int(x)}"
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return str(x)
    if math.isnan(xf):
        return "—"
    if math.isinf(xf):
        return "∞" if xf > 0 else "−∞"
    if xf != 0 and (abs(xf) < 10 ** (-digits) or abs(xf) >= 1e7):
        return f"{xf:.{digits}e}"
    return f"{xf:.{digits}f}"


def fmt_ci(lo: float, hi: float, digits: int = 3) -> str:
    return f"{fmt_num(lo, digits)} to {fmt_num(hi, digits)}"


# ----------------------------------------------------------------------------
# Blocks
# ----------------------------------------------------------------------------
@dataclass
class Block:
    kind: str  # heading | table | text | note | figure | methods | warning
    content: Any
    caption: str = ""
    note: str = ""
    p_columns: tuple = ()


@dataclass
class Result:
    title: str
    subtitle: str = ""
    blocks: list = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))

    # -- builders -----------------------------------------------------------
    def heading(self, text: str):
        self.blocks.append(Block("heading", text))
        return self

    def text(self, text: str):
        self.blocks.append(Block("text", text))
        return self

    def note(self, text: str):
        self.blocks.append(Block("note", text))
        return self

    def warning(self, text: str):
        self.blocks.append(Block("warning", text))
        return self

    def interpret(self, en: str, ar: str = ""):
        """Plain-language interpretation (the 'smart assistant' layer), bilingual."""
        self.blocks.append(Block("interpret", {"en": en, "ar": ar or en}))
        return self

    def methods(self, text: str):
        self.blocks.append(Block("methods", text))
        return self

    def table(self, df: pd.DataFrame, caption: str = "", note: str = "",
              p_columns=("p", "p value", "p (adj.)", "p adj.", "Sig.")):
        self.blocks.append(Block("table", df, caption, note, tuple(p_columns)))
        return self

    def figure(self, fig, caption: str = ""):
        self.blocks.append(Block("figure", fig, caption))
        return self

    # -- accessors ----------------------------------------------------------
    @property
    def tables(self):
        return [b for b in self.blocks if b.kind == "table"]

    @property
    def figures(self):
        return [b for b in self.blocks if b.kind == "figure"]

    # -- rendering ----------------------------------------------------------
    @staticmethod
    def format_df(df: pd.DataFrame, p_columns=()) -> pd.DataFrame:
        out = df.copy()
        for c in out.columns:
            if str(c) in p_columns:
                out[c] = [fmt_p(v) if isinstance(v, (float, int, np.floating)) else ("—" if v is None else str(v))
                          for v in out[c]]
            else:
                out[c] = [fmt_num(v) for v in out[c]]
        return out

    def to_html(self, embed_figures: bool = True, fig_ids: dict | None = None) -> str:
        parts = [f'<div class="result"><h2>{html.escape(self.title)}</h2>']
        if self.subtitle:
            parts.append(f'<div class="subtitle">{html.escape(self.subtitle)}</div>')
        tcount = 0
        fcount = 0
        for b in self.blocks:
            if b.kind == "heading":
                parts.append(f"<h3>{html.escape(b.content)}</h3>")
            elif b.kind == "text":
                parts.append(f"<p>{html.escape(b.content)}</p>")
            elif b.kind == "note":
                parts.append(f'<p class="note">{html.escape(b.content)}</p>')
            elif b.kind == "warning":
                parts.append(_card(f"⚠ {html.escape(b.content)}", "#FFF4E5", "#E08E0B", "warning"))
            elif b.kind == "interpret":
                from .settings import SETTINGS
                lang = SETTINGS.language
                txt = b.content.get(lang) or b.content.get("en")
                d = ' dir="rtl"' if lang == "ar" else ""
                head = "🧠 التفسير الذكي" if lang == "ar" else "🧠 Smart interpretation"
                parts.append(_card(f'<b>{head}:</b><br>{html.escape(txt).replace(chr(10), "<br>")}', "#EEF6FF", "#1F6FEB", "interpret", d))
            elif b.kind == "methods":
                parts.append(_card(f"<b>Methods / Results text (ready to paste):</b><br>{html.escape(b.content)}", "#F3FAF3", "#2E8B57", "methods"))
            elif b.kind == "table":
                tcount += 1
                df = self.format_df(b.content, b.p_columns)
                cap = f"Table {tcount}. {b.caption}" if b.caption else f"Table {tcount}"
                parts.append(_df_to_html(df, cap, b.note))
            elif b.kind == "figure":
                fcount += 1
                cap = f"Figure {fcount}. {b.caption}" if b.caption else f"Figure {fcount}"
                if fig_ids is not None and id(b.content) in fig_ids:
                    src = fig_ids[id(b.content)]
                elif embed_figures:
                    src = "data:image/png;base64," + fig_to_base64(b.content, dpi=110)
                else:
                    src = ""
                parts.append(f'<div class="figure"><img src="{src}" width="560"><div class="caption">{html.escape(cap)}</div></div>')
        parts.append("</div>")
        return "\n".join(parts)


def _card(inner, bg, edge, cls, attrs=""):
    # table-based card renders identically in Qt's rich-text engine and in browsers
    return (f'<table class="{cls}" width="100%" cellspacing="0" cellpadding="0" style="margin:8px 0"{attrs}><tr>'
            f'<td width="5" bgcolor="{edge}"></td><td bgcolor="{bg}" style="padding:8px 12px;color:#1D2433">{inner}</td></tr></table>')


def _df_to_html(df: pd.DataFrame, caption: str, note: str) -> str:
    show_index = not isinstance(df.index, pd.RangeIndex)
    rows = ['<table class="apa" cellspacing="0" cellpadding="4">']
    rows.append(f'<caption>{html.escape(caption)}</caption>')
    head = "<tr>"
    if show_index:
        head += f"<th>{html.escape(str(df.index.name or ''))}</th>"
    for c in df.columns:
        head += f"<th>{html.escape(str(c))}</th>"
    rows.append(head + "</tr>")
    for idx, r in df.iterrows():
        line = "<tr>"
        if show_index:
            line += f'<td class="rowhead">{html.escape(str(idx))}</td>'
        for v in r.values:
            line += f"<td>{html.escape(str(v))}</td>"
        rows.append(line + "</tr>")
    rows.append("</table>")
    if note:
        rows.append(f'<p class="tnote"><i>Note.</i> {html.escape(note)}</p>')
    return "\n".join(rows)


def fig_to_base64(fig, dpi=110) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    return base64.b64encode(buf.getvalue()).decode()


def fig_to_png_bytes(fig, dpi=150) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    return buf.getvalue()


class AnalysisError(Exception):
    """Raised for user-facing problems (wrong variable type, too few cases...)."""
