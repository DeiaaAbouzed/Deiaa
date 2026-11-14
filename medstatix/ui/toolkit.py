"""Animal-study toolkit (randomisation, sample size, outliers, ARRIVE 2.0) and study templates."""
from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..core import animal as AN
from ..core.settings import SETTINGS


def T(en, ar):
    return ar if SETTINGS.language == "ar" else en


def fill_table(tbl: QTableWidget, df: pd.DataFrame):
    tbl.clear(); tbl.setRowCount(len(df)); tbl.setColumnCount(len(df.columns))
    tbl.setHorizontalHeaderLabels([str(c) for c in df.columns])
    for i in range(len(df)):
        for j in range(len(df.columns)):
            v = df.iat[i, j]
            tbl.setItem(i, j, QTableWidgetItem(f"{v:.4g}" if isinstance(v, float) else str(v)))
    tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)


class AnimalToolkit(QDialog):
    """Tabs: randomisation, sample size, outliers, ARRIVE 2.0 checklist."""

    def __init__(self, parent=None, df: pd.DataFrame | None = None):
        super().__init__(parent)
        self.df = df.reset_index(drop=True) if df is not None else pd.DataFrame()
        self.result_df = None
        self.excluded = None
        self.log = []
        self.setWindowTitle(T("Animal-study toolkit", "أدوات دراسات الحيوان"))
        self.resize(940, 640)
        lay = QVBoxLayout(self)
        tabs = QTabWidget(); lay.addWidget(tabs, 1)
        tabs.addTab(self._rand_tab(), T("Randomisation", "التوزيع العشوائي"))
        tabs.addTab(self._size_tab(), T("Sample size", "حجم العينة"))
        tabs.addTab(self._outlier_tab(), T("Outliers (Grubbs / ROUT)", "القيم الشاذة (Grubbs / ROUT)"))
        tabs.addTab(self._arrive_tab(), "ARRIVE 2.0")
        bb = QDialogButtonBox(QDialogButtonBox.Close); bb.rejected.connect(self.reject); lay.addWidget(bb)

    # ---- randomisation
    def _rand_tab(self):
        w = QWidget(); v = QVBoxLayout(w); f = QFormLayout()
        self.r_groups = QLineEdit(", ".join(AN.DEFAULT_GROUPS))
        self.r_n = QSpinBox(); self.r_n.setRange(1, 200); self.r_n.setValue(6)
        self.r_seed = QSpinBox(); self.r_seed.setRange(0, 999999); self.r_seed.setValue(2026)
        self.r_w = QLineEdit(); self.r_w.setPlaceholderText(T("optional: body weights in animal order, comma-separated",
                                                              "اختياري: أوزان الحيوانات بالترتيب مفصولة بفواصل"))
        f.addRow(T("Groups", "المجموعات"), self.r_groups); f.addRow(T("Animals per group", "عدد الحيوانات في كل مجموعة"), self.r_n)
        f.addRow(T("Random seed (reproducible)", "البذرة العشوائية (لإعادة النتيجة)"), self.r_seed)
        f.addRow(T("Body weights → stratified", "الأوزان ← توزيع طبقي"), self.r_w)
        v.addLayout(f)
        row = QHBoxLayout()
        b = QPushButton(T("Randomise", "توزيع عشوائي")); b.setObjectName("primary"); b.clicked.connect(self.do_rand); row.addWidget(b)
        b2 = QPushButton(T("Save as Excel…", "حفظ Excel…")); b2.clicked.connect(lambda: self._save(self.rand_df)); row.addWidget(b2)
        row.addStretch(1); v.addLayout(row)
        self.r_info = QLabel(); self.r_info.setWordWrap(True); self.r_info.setObjectName("hint"); v.addWidget(self.r_info)
        self.r_tbl = QTableWidget(); v.addWidget(self.r_tbl, 1)
        self.rand_df = None
        return w

    def do_rand(self):
        groups = [g.strip() for g in self.r_groups.text().split(",") if g.strip()]
        n = self.r_n.value()
        weights = None
        if self.r_w.text().strip():
            try:
                weights = [float(x) for x in self.r_w.text().replace("،", ",").split(",") if x.strip()]
            except ValueError:
                QMessageBox.warning(self, "", T("Weights must be numbers.", "الأوزان يجب أن تكون أرقامًا.")); return
            if len(weights) != n * len(groups):
                QMessageBox.warning(self, "", T(f"Enter {n * len(groups)} weights.", f"أدخل {n * len(groups)} وزنًا.")); return
        self.rand_df = AN.randomize({g: n for g in groups}, seed=self.r_seed.value(), weights=weights)
        fill_table(self.r_tbl, self.rand_df)
        txt = T(f"{len(self.rand_df)} animals allocated with seed {self.r_seed.value()} ", f"تم توزيع {len(self.rand_df)} حيوانًا بالبذرة {self.r_seed.value()} ")
        if weights:
            m = self.rand_df.groupby("Group", observed=True)["Body weight"].mean().round(1).to_dict()
            txt += T("(stratified by body weight; group means: ", "(توزيع طبقي حسب الوزن؛ متوسط كل مجموعة: ") + ", ".join(f"{k} {v}" for k, v in m.items()) + ")"
        txt += T(". Methods: 'Animals were randomly allocated to groups using a computer-generated sequence (MedStatix Pro, seed "
                 f"{self.r_seed.value()}).'", f". للطرق: 'Animals were randomly allocated to groups using a computer-generated sequence "
                 f"(MedStatix Pro, seed {self.r_seed.value()}).'")
        self.r_info.setText(txt)

    # ---- sample size
    def _size_tab(self):
        w = QWidget(); v = QVBoxLayout(w); f = QFormLayout()
        self.s_k = QSpinBox(); self.s_k.setRange(2, 20); self.s_k.setValue(5)
        self.s_b = QSpinBox(); self.s_b.setRange(1, 20); self.s_b.setValue(1)
        self.s_d = QDoubleSpinBox(); self.s_d.setRange(0.1, 5); self.s_d.setValue(1.2); self.s_d.setSingleStep(0.1)
        self.s_pow = QDoubleSpinBox(); self.s_pow.setRange(0.5, 0.99); self.s_pow.setValue(0.8); self.s_pow.setSingleStep(0.05)
        f.addRow(T("Number of groups", "عدد المجموعات"), self.s_k); f.addRow(T("Blocks (e.g. batches)", "عدد الكتل (الدفعات)"), self.s_b)
        f.addRow(T("Expected effect (Cohen's d)", "الأثر المتوقع (Cohen's d)"), self.s_d); f.addRow(T("Power", "القوة"), self.s_pow)
        v.addLayout(f)
        b = QPushButton(T("Calculate", "احسب")); b.setObjectName("primary"); b.clicked.connect(self.do_size); v.addWidget(b)
        self.s_out = QLabel(); self.s_out.setWordWrap(True); self.s_out.setTextFormat(Qt.RichText); v.addWidget(self.s_out)
        v.addStretch(1)
        return w

    def do_size(self):
        k = self.s_k.value()
        lo, hi = AN.mead(k, self.s_b.value())
        n = AN.n_for_power(self.s_d.value(), k, SETTINGS.alpha, self.s_pow.value())
        self.s_out.setText(T(
            f"<b>Mead's resource equation:</b> {lo}–{hi} animals per group (E = N − B − T between 10 and 20).<br>"
            f"<b>Power analysis:</b> about {n} animals per group for d = {self.s_d.value():g}, power {self.s_pow.value():.0%}, α = {SETTINGS.alpha:g}.<br>"
            "Use the power analysis when you have a prior estimate of the effect; Mead's equation is accepted for exploratory studies. "
            "Report the method used (ARRIVE item 2).",
            f"<b>معادلة Mead:</b> من {lo} إلى {hi} حيوانات في كل مجموعة (E = N − B − T بين 10 و20).<br>"
            f"<b>تحليل القوة:</b> حوالي {n} حيوانات في كل مجموعة لأثر d = {self.s_d.value():g} وقوة {self.s_pow.value():.0%} و α = {SETTINGS.alpha:g}.<br>"
            "استخدم تحليل القوة إذا كان لديك تقدير مسبق للأثر، ومعادلة Mead مقبولة للدراسات الاستكشافية. اذكر الطريقة المستخدمة (بند ARRIVE رقم 2)."))

    # ---- outliers
    def _outlier_tab(self):
        w = QWidget(); v = QVBoxLayout(w); f = QFormLayout()
        num = [c for c in self.df.columns if pd.api.types.is_numeric_dtype(self.df[c])]
        cat = [c for c in self.df.columns if c not in num]
        self.o_val = QComboBox(); self.o_val.addItems(num)
        self.o_grp = QComboBox(); self.o_grp.addItem(T("(no groups)", "(بدون مجموعات)"), ""); [self.o_grp.addItem(c, c) for c in cat]
        if cat:
            self.o_grp.setCurrentIndex(1)
        self.o_m = QComboBox(); self.o_m.addItem("ROUT (Q = 1%) — GraphPad", "ROUT"); self.o_m.addItem("Grubbs (α = 0.05)", "Grubbs")
        f.addRow(T("Variable", "المتغير"), self.o_val); f.addRow(T("Within groups", "داخل المجموعات"), self.o_grp); f.addRow(T("Method", "الطريقة"), self.o_m)
        v.addLayout(f)
        row = QHBoxLayout()
        b = QPushButton(T("Find outliers", "ابحث عن القيم الشاذة")); b.setObjectName("primary"); b.clicked.connect(self.do_out); row.addWidget(b)
        self.o_excl = QPushButton(T("Exclude flagged values (logged) → new dataset", "استبعاد القيم المحددة (مع تسجيلها) ← بيانات جديدة"))
        self.o_excl.setEnabled(False); self.o_excl.clicked.connect(self.do_exclude); row.addWidget(self.o_excl); row.addStretch(1)
        v.addLayout(row)
        self.o_info = QLabel(); self.o_info.setWordWrap(True); self.o_info.setObjectName("hint"); v.addWidget(self.o_info)
        self.o_tbl = QTableWidget(); v.addWidget(self.o_tbl, 1)
        self.out_df = None
        return w

    def do_out(self):
        if self.df.empty or not self.o_val.currentText():
            return
        self.out_df = AN.outlier_report(self.df, self.o_val.currentText(), self.o_grp.currentData() or None, self.o_m.currentData())
        fill_table(self.o_tbl, self.out_df)
        self.o_excl.setEnabled(len(self.out_df) > 0)
        self.o_info.setText(T(f"{len(self.out_df)} value(s) flagged. Exclude only with a documented reason (ARRIVE item 3); "
                              "report the number excluded per group.",
                              f"تم تحديد {len(self.out_df)} قيمة. لا تستبعد إلا بسبب موثق (بند ARRIVE رقم 3)، واذكر عدد المستبعد في كل مجموعة."))

    def do_exclude(self):
        if self.out_df is None or not len(self.out_df):
            return
        d = self.df.copy()
        col = self.o_val.currentText()
        rows = [r - 1 for r in self.out_df["Row"]]
        d.loc[d.index[rows], col] = float("nan")
        self.excluded = d
        self.log.append(f"{len(rows)} value(s) of {col} set to missing by {self.o_m.currentData()} "
                        f"(rows {', '.join(str(r) for r in self.out_df['Row'])}).")
        QMessageBox.information(self, "", T("Done. The new dataset (with the exclusions logged) is opened when you close this window.",
                                            "تم. ستُفتح البيانات الجديدة (مع تسجيل الاستبعاد) عند إغلاق هذه النافذة."))

    # ---- ARRIVE
    def _arrive_tab(self):
        w = QWidget(); v = QVBoxLayout(w)
        hint = QLabel(T("ARRIVE 2.0 (Percie du Sert et al., 2020). The Essential 10 (E) are the minimum for any manuscript; "
                        "tick each item, note where it is reported, and export the checklist for submission.",
                        "قائمة ARRIVE 2.0. البنود العشرة الأساسية (E) هي الحد الأدنى لأي بحث؛ علّم كل بند واكتب مكانه في البحث ثم صدّر القائمة."))
        hint.setWordWrap(True); hint.setObjectName("hint"); v.addWidget(hint)
        self.a_tbl = QTableWidget(len(AN.ARRIVE), 4)
        self.a_tbl.setHorizontalHeaderLabels(["✓", T("Item", "البند"), T("What to report", "ما يجب ذكره"), T("Where reported (page/section)", "مكانه في البحث")])
        for i, (kind, en, ar, desc) in enumerate(AN.ARRIVE):
            c = QTableWidgetItem(kind); c.setFlags(c.flags() | Qt.ItemIsUserCheckable); c.setCheckState(Qt.Unchecked)
            self.a_tbl.setItem(i, 0, c)
            it = QTableWidgetItem(f"{en}" + (f" — {ar}" if SETTINGS.language == "ar" else "")); it.setFlags(Qt.ItemIsEnabled)
            self.a_tbl.setItem(i, 1, it)
            d = QTableWidgetItem(desc); d.setFlags(Qt.ItemIsEnabled); self.a_tbl.setItem(i, 2, d)
            self.a_tbl.setItem(i, 3, QTableWidgetItem(""))
        self.a_tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.a_tbl.resizeColumnToContents(1); self.a_tbl.setWordWrap(True); self.a_tbl.resizeRowsToContents()
        v.addWidget(self.a_tbl, 1)
        b = QPushButton(T("Export checklist (Word)…", "تصدير القائمة (Word)…")); b.clicked.connect(self.export_arrive); v.addWidget(b)
        return w

    def arrive_df(self):
        rows = []
        for i, (kind, en, ar, desc) in enumerate(AN.ARRIVE):
            rows.append({"Item": en, "Set": "Essential 10" if kind == "E" else "Recommended set",
                         "Reported": "Yes" if self.a_tbl.item(i, 0).checkState() == Qt.Checked else "No",
                         "Where": self.a_tbl.item(i, 3).text() if self.a_tbl.item(i, 3) else ""})
        return pd.DataFrame(rows)

    def export_arrive(self):
        path, _ = QFileDialog.getSaveFileName(self, "", "ARRIVE_checklist.docx", "Word (*.docx)")
        if not path:
            return
        from docx import Document
        doc = Document(); doc.add_heading("ARRIVE 2.0 checklist", 1)
        df = self.arrive_df()
        t = doc.add_table(rows=len(df) + 1, cols=4); t.style = "Table Grid"
        for j, c in enumerate(df.columns):
            t.cell(0, j).text = c
        for i in range(len(df)):
            for j in range(4):
                t.cell(i + 1, j).text = str(df.iat[i, j])
        doc.add_paragraph("Percie du Sert N, et al. The ARRIVE guidelines 2.0. PLoS Biol 2020;18:e3000410.")
        doc.save(path)

    def _save(self, df):
        if df is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "", "randomisation.xlsx", "Excel (*.xlsx)")
        if path:
            df.to_excel(path, index=False)


class TemplatesDialog(QDialog):
    """Create an empty data-entry sheet for a common pharmacology / toxicology design."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(T("Study templates", "قوالب الدراسات"))
        self.resize(620, 420)
        lay = QVBoxLayout(self)
        hint = QLabel(T("Pick a design: an entry sheet with the groups and the usual measures is created. Fill in the values (or save it as "
                        "Excel, fill it and open it again), then press ⭐ Recommendations or 🧠 Smart analyze.",
                        "اختر التصميم: يتم إنشاء جدول إدخال بالمجموعات والمؤشرات المعتادة. أدخل القيم (أو احفظه Excel واملأه ثم افتحه)، "
                        "ثم اضغط ⭐ التوصيات أو 🧠 التحليل الذكي."))
        hint.setWordWrap(True); hint.setObjectName("hint"); lay.addWidget(hint)
        f = QFormLayout()
        self.kind = QComboBox()
        for k, t in AN.TEMPLATES.items():
            self.kind.addItem(t["ar"] if SETTINGS.language == "ar" else t["en"], k)
        self.groups = QLineEdit(", ".join(AN.DEFAULT_GROUPS))
        self.n = QSpinBox(); self.n.setRange(1, 100); self.n.setValue(6)
        self.measures = QPlainTextEdit(); self.measures.setMaximumHeight(110)
        self.kind.currentIndexChanged.connect(self._upd); self._upd()
        f.addRow(T("Design", "التصميم"), self.kind); f.addRow(T("Groups", "المجموعات"), self.groups)
        f.addRow(T("Animals per group", "عدد الحيوانات في كل مجموعة"), self.n)
        f.addRow(T("Measures (one per line)", "المؤشرات (كل سطر مؤشر)"), self.measures)
        lay.addLayout(f)
        self.xl = QCheckBox(T("Also save as an Excel entry sheet", "حفظه أيضًا كملف Excel للإدخال")); lay.addWidget(self.xl)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _upd(self):
        t = AN.TEMPLATES[self.kind.currentData()]
        self.measures.setPlainText("\n".join(t.get("measures", [])))
        self.measures.setEnabled("measures" in t); self.groups.setEnabled("measures" in t)

    def make(self):
        key = self.kind.currentData()
        groups = [g.strip() for g in self.groups.text().replace("،", ",").split(",") if g.strip()]
        t = AN.TEMPLATES[key]
        if "measures" in t:
            ms = [m.strip() for m in self.measures.toPlainText().splitlines() if m.strip()]
            old = t["measures"]; t = dict(t); t["measures"] = ms
            AN.TEMPLATES["_custom"] = t
            df = AN.make_template("_custom", groups, self.n.value())
            AN.TEMPLATES.pop("_custom", None)
        else:
            df = AN.make_template(key, groups, self.n.value())
        name = (AN.TEMPLATES[key]["en"])
        if self.xl.isChecked():
            path, _ = QFileDialog.getSaveFileName(self, "", f"{name}.xlsx", "Excel (*.xlsx)")
            if path:
                df.to_excel(path, index=False)
        return df, name
