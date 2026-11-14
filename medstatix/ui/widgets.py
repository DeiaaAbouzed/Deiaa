"""Reusable widgets: pandas table model, auto-generated analysis dialog, advisor dialogs, settings, data-management dialogs."""
from __future__ import annotations

import numpy as np
import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
                               QSpinBox, QVBoxLayout, QWidget, QTextBrowser)

from ..analyses.registry import REGISTRY
from ..core.advisor import WIZARD
from ..core.data import var_kind, is_numeric
from ..core.settings import SETTINGS
from ..plots.figures import PALETTES, FIG_STYLES, GROUP_PLOT_TYPES
from .i18n import tr, lbl


# --------------------------------------------------------------------------- table model
class PandasModel(QAbstractTableModel):
    edited = Signal()

    def __init__(self, df: pd.DataFrame | None = None):
        super().__init__()
        self._df = df if df is not None else pd.DataFrame()

    def set_df(self, df):
        self.beginResetModel()
        self._df = df
        self.endResetModel()

    def df(self):
        return self._df

    def rowCount(self, parent=QModelIndex()):
        return len(self._df)

    def columnCount(self, parent=QModelIndex()):
        return self._df.shape[1]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        v = self._df.iat[index.row(), index.column()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            if v is None or (isinstance(v, float) and np.isnan(v)) or (v is pd.NA):
                return ""
            if isinstance(v, (float, np.floating)):
                return f"{v:.6g}"
            return str(v)
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignRight | Qt.AlignVCenter) if isinstance(v, (int, float, np.number)) else int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole:
            return False
        col = self._df.columns[index.column()]
        txt = str(value).strip()
        if txt == "":
            new = np.nan
        else:
            try:
                new = float(txt)
                if new.is_integer() and pd.api.types.is_integer_dtype(self._df[col]):
                    new = int(new)
            except ValueError:
                new = txt
        if isinstance(new, str) and is_numeric(self._df[col]):
            self._df[col] = self._df[col].astype(object)
        elif isinstance(new, (int, float)) and pd.api.types.is_integer_dtype(self._df[col]) and isinstance(new, float):
            self._df[col] = self._df[col].astype(float)
        self._df.iat[index.row(), index.column()] = new
        self.dataChanged.emit(index, index)
        self.edited.emit()
        return True

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self._df.columns[section]) if section < self._df.shape[1] else None
        return str(section + 1)


def variables_frame(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for c in df.columns:
        s = df[c]
        k = var_kind(s)
        if is_numeric(s):
            lv = f"{s.min():.4g} – {s.max():.4g}" if s.notna().any() else ""
        else:
            u = s.dropna().unique()
            lv = ", ".join(map(str, u[:6])) + (" …" if len(u) > 6 else "")
        rows.append({tr("name"): c, tr("type"): "numeric" if is_numeric(s) else "text", tr("role"): k,
                     tr("n_valid"): int(s.notna().sum()), tr("missing"): int(s.isna().sum()), tr("levels"): lv})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- analysis dialog
class VarList(QListWidget):
    def __init__(self, cols):
        super().__init__()
        for c in cols:
            it = QListWidgetItem(str(c))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            self.addItem(it)
        self.setMinimumHeight(110)
        self.itemClicked.connect(lambda it: it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked))

    def values(self):
        return [self.item(i).text() for i in range(self.count()) if self.item(i).checkState() == Qt.Checked]


class AnalysisDialog(QDialog):
    def __init__(self, analysis_id: str, df: pd.DataFrame | None, parent=None, preset: dict | None = None):
        super().__init__(parent)
        self.a = REGISTRY[analysis_id]
        self.df = df
        self.setWindowTitle(lbl(self.a))
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        h = QLabel(lbl(self.a)); h.setObjectName("h1")
        lay.addWidget(h)
        d = QLabel(self.a.desc_ar if SETTINGS.language == "ar" else self.a.desc_en); d.setWordWrap(True); d.setObjectName("hint")
        lay.addWidget(d)
        area = QScrollArea(); area.setWidgetResizable(True)
        inner = QWidget(); form = QFormLayout(inner); form.setLabelAlignment(Qt.AlignLeft)
        self.widgets = {}
        cols = list(df.columns) if df is not None else []
        num_cols = [c for c in cols if is_numeric(df[c])] if df is not None else []
        cat_cols = [c for c in cols if df[c].nunique() <= 30] if df is not None else []
        used = set()
        for p in self.a.params:
            label = p.ar if SETTINGS.language == "ar" else p.en
            if p.kind in ("var_num", "var_cat", "var_any"):
                w = QComboBox()
                pool = {"var_num": num_cols, "var_cat": cat_cols, "var_any": cols}[p.kind]
                rest = [c for c in cols if c not in pool]
                if p.optional:
                    w.addItem(tr("none"), None)
                for c in pool:
                    w.addItem(str(c), c)
                if rest and p.kind != "var_any":
                    w.insertSeparator(w.count())
                    for c in rest:
                        w.addItem(str(c), c)
                if not p.optional:
                    for i in range(w.count()):
                        if w.itemData(i) is not None and w.itemData(i) not in used:
                            w.setCurrentIndex(i); used.add(w.itemData(i)); break
            elif p.kind in ("vars_num", "vars_any"):
                pool = num_cols if p.kind == "vars_num" else cols
                w = VarList(pool + [c for c in cols if c not in pool])
            elif p.kind == "choice":
                w = QComboBox(); w.addItems(p.options)
                if p.default in p.options:
                    w.setCurrentText(p.default)
            elif p.kind == "float":
                w = QDoubleSpinBox(); w.setRange(-1e12, 1e12); w.setDecimals(4); w.setValue(float(p.default or 0))
            elif p.kind == "int":
                w = QSpinBox(); w.setRange(-10 ** 9, 10 ** 9); w.setValue(int(p.default or 0))
            elif p.kind == "bool":
                w = QCheckBox(); w.setChecked(bool(p.default))
            else:
                w = QLineEdit(str(p.default or ""))
            self.widgets[p.name] = (p, w)
            form.addRow(QLabel(label + ("" if p.optional or p.kind in ("bool", "choice", "float", "int", "text") else " *")), w)
        area.setWidget(inner)
        lay.addWidget(area, 1)
        if preset:
            self.apply_preset(preset)
        bb = QDialogButtonBox()
        run = bb.addButton(tr("run"), QDialogButtonBox.AcceptRole); run.setObjectName("primary")
        bb.addButton(tr("cancel"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(620, min(760, 220 + 62 * len(self.a.params)))

    def apply_preset(self, preset):
        for k, v in preset.items():
            if k not in self.widgets:
                continue
            p, w = self.widgets[k]
            if isinstance(w, QComboBox):
                i = w.findData(v) if p.kind.startswith("var") else w.findText(str(v))
                if i >= 0:
                    w.setCurrentIndex(i)
            elif isinstance(w, VarList):
                for i in range(w.count()):
                    w.item(i).setCheckState(Qt.Checked if w.item(i).text() in v else Qt.Unchecked)

    def values(self) -> dict:
        out = {}
        for name, (p, w) in self.widgets.items():
            if isinstance(w, VarList):
                v = w.values()
                out[name] = v if v else ([] if not p.optional else None)
            elif isinstance(w, QComboBox):
                out[name] = w.currentData() if p.kind.startswith("var") else w.currentText()
            elif isinstance(w, (QDoubleSpinBox, QSpinBox)):
                out[name] = w.value()
            elif isinstance(w, QCheckBox):
                out[name] = w.isChecked()
            else:
                out[name] = w.text()
        return out


# --------------------------------------------------------------------------- smart analyze
class SmartDialog(QDialog):
    def __init__(self, df, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🧠 " + tr("smart"))
        lay = QVBoxLayout(self)
        h = QLabel("🧠 " + tr("smart")); h.setObjectName("h1"); lay.addWidget(h)
        d = QLabel(tr("smart_desc")); d.setWordWrap(True); d.setObjectName("hint"); lay.addWidget(d)
        f = QFormLayout()
        self.out = QComboBox(); self.fac = QComboBox()
        self.fac.addItem(tr("none"), None)
        for c in df.columns:
            self.out.addItem(f"{c}   [{var_kind(df[c])}]", c)
            self.fac.addItem(f"{c}   [{var_kind(df[c])}]", c)
        f.addRow(tr("outcome_q"), self.out); f.addRow(tr("factor_q"), self.fac)
        lay.addLayout(f)
        bb = QDialogButtonBox()
        b = bb.addButton(tr("run"), QDialogButtonBox.AcceptRole); b.setObjectName("primary")
        bb.addButton(tr("cancel"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(520, 220)

    def values(self):
        return self.out.currentData(), self.fac.currentData()


class WizardDialog(QDialog):
    """Interactive decision tree that recommends the right analysis."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("wizard"))
        self.choice = None
        self.stack = ["start"]
        self.lay = QVBoxLayout(self)
        self.title = QLabel(); self.title.setObjectName("h1"); self.title.setWordWrap(True)
        self.lay.addWidget(self.title)
        self.body = QVBoxLayout(); self.lay.addLayout(self.body)
        self.lay.addStretch(1)
        nav = QHBoxLayout()
        self.back = QPushButton(tr("back")); self.back.clicked.connect(self.go_back)
        nav.addWidget(self.back); nav.addStretch(1)
        self.lay.addLayout(nav)
        self.resize(620, 480)
        self.render()

    def _clear(self):
        while self.body.count():
            w = self.body.takeAt(0).widget()
            if w:
                w.hide(); w.setParent(None); w.deleteLater()

    def render(self):
        self._clear()
        node = self.stack[-1]
        ar = SETTINGS.language == "ar"
        if isinstance(node, tuple):  # result
            _, aid, en, a_ = node
            self.title.setText("✅ " + tr("recommend") + ": " + lbl(REGISTRY[aid]))
            t = QLabel(a_ if ar else en); t.setWordWrap(True); self.body.addWidget(t)
            b = QPushButton(tr("open_analysis")); b.setObjectName("primary")
            b.clicked.connect(lambda: self._finish(aid)); self.body.addWidget(b)
        else:
            (qen, qar), opts = WIZARD[node]
            self.title.setText(qar if ar else qen)
            for (oen, oar), nxt in opts:
                b = QPushButton(oar if ar else oen); b.setObjectName("choice")
                b.clicked.connect(lambda _=False, n=nxt: self._go(n))
                self.body.addWidget(b)
        self.back.setEnabled(len(self.stack) > 1)

    def _go(self, nxt):
        self.stack.append(nxt); self.render()

    def go_back(self):
        if len(self.stack) > 1:
            self.stack.pop(); self.render()

    def _finish(self, aid):
        self.choice = aid; self.accept()


# --------------------------------------------------------------------------- settings
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings"))
        lay = QVBoxLayout(self)
        g1 = QGroupBox(tr("style")); f1 = QFormLayout(g1)
        self.style = QComboBox(); self.style.addItems(FIG_STYLES); self.style.setCurrentText(SETTINGS.fig_style)
        self.pal = QComboBox(); self.pal.addItems(list(PALETTES)); self.pal.setCurrentText(SETTINGS.palette)
        self.plot = QComboBox(); self.plot.addItems(GROUP_PLOT_TYPES); self.plot.setCurrentText(SETTINGS.group_plot)
        self.err = QComboBox(); self.err.addItems(["SD", "SEM", "95% CI"]); self.err.setCurrentText(SETTINGS.error_bar)
        self.font = QComboBox(); self.font.addItems(["Arial", "Helvetica", "Times New Roman", "Calibri", "Segoe UI"]); self.font.setEditable(True)
        self.font.setCurrentText(SETTINGS.font_family)
        self.fs = QDoubleSpinBox(); self.fs.setRange(6, 24); self.fs.setValue(SETTINGS.font_size)
        self.w = QDoubleSpinBox(); self.w.setRange(30, 400); self.w.setValue(SETTINGS.fig_width_mm)
        self.h = QDoubleSpinBox(); self.h.setRange(30, 400); self.h.setValue(SETTINGS.fig_height_mm)
        self.dpi = QComboBox(); self.dpi.addItems(["300", "600", "1200"]); self.dpi.setCurrentText(str(SETTINGS.export_dpi))
        self.sig = QCheckBox(); self.sig.setChecked(SETTINGS.show_significance)
        for k, w in [("style", self.style), ("palette", self.pal), ("plot_type", self.plot), ("error_bar", self.err), ("font", self.font),
                     ("font_size", self.fs), ("width", self.w), ("height", self.h), ("dpi", self.dpi), ("show_sig", self.sig)]:
            f1.addRow(tr(k), w)
        self.preview = QLabel(); self.preview.setMinimumHeight(28)
        f1.addRow("", self.preview)
        self.pal.currentTextChanged.connect(self._preview); self._preview(self.pal.currentText())
        lay.addWidget(g1)
        g2 = QGroupBox(tr("ui_lang")); f2 = QFormLayout(g2)
        self.lang = QComboBox(); self.lang.addItem("العربية", "ar"); self.lang.addItem("English", "en")
        self.lang.setCurrentIndex(0 if SETTINGS.language == "ar" else 1)
        self.theme = QComboBox(); self.theme.addItem("Light ☀", "light"); self.theme.addItem("Dark ☾", "dark")
        self.theme.setCurrentIndex(0 if SETTINGS.theme == "light" else 1)
        f2.addRow(tr("ui_lang"), self.lang); f2.addRow(tr("theme"), self.theme)
        lay.addWidget(g2)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _preview(self, name):
        cols = PALETTES.get(name, [])
        self.preview.setText("".join(f'<span style="background:{c};">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>&nbsp;' for c in cols))

    def apply(self):
        SETTINGS.fig_style = self.style.currentText(); SETTINGS.palette = self.pal.currentText()
        SETTINGS.group_plot = self.plot.currentText(); SETTINGS.error_bar = self.err.currentText()
        SETTINGS.font_family = self.font.currentText(); SETTINGS.font_size = self.fs.value()
        SETTINGS.fig_width_mm = self.w.value(); SETTINGS.fig_height_mm = self.h.value()
        SETTINGS.export_dpi = int(self.dpi.currentText()); SETTINGS.show_significance = self.sig.isChecked()
        SETTINGS.language = self.lang.currentData(); SETTINGS.theme = self.theme.currentData()


# --------------------------------------------------------------------------- simple form dialog
class FormDialog(QDialog):
    """Generic small form: fields = [(key, label, widget)]."""
    def __init__(self, title, fields, parent=None, help_text=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        if help_text:
            hl = QLabel(help_text); hl.setWordWrap(True); hl.setObjectName("hint"); lay.addWidget(hl)
        f = QFormLayout()
        self.fields = {}
        for key, label, w in fields:
            f.addRow(label, w); self.fields[key] = w
        lay.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(520, 120 + 40 * len(fields))

    def get(self, key):
        w = self.fields[key]
        if isinstance(w, VarList):
            return w.values()
        if isinstance(w, QComboBox):
            return w.currentText()
        return w.text()


def combo(items, current=None):
    c = QComboBox(); c.addItems([str(i) for i in items])
    if current:
        c.setCurrentText(current)
    return c


class AboutDialog(QDialog):
    def __init__(self, html, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("about"))
        lay = QVBoxLayout(self)
        tb = QTextBrowser(); tb.setHtml(html); tb.setOpenExternalLinks(True)
        lay.addWidget(tb)
        bb = QDialogButtonBox(QDialogButtonBox.Ok); bb.accepted.connect(self.accept)
        lay.addWidget(bb)
        self.resize(720, 560)
