"""Full-paper builder: study details, groups, references (PubMed / RIS for EndNote) and output options."""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QCheckBox, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..core.settings import SETTINGS
from ..report import paper as PP
from ..report import refs as RF
from ..report.journals import JOURNALS

FIELDS = [("title", "Title of the paper", "عنوان البحث"), ("authors", "Authors and affiliations", "المؤلفون وجهات العمل"),
          ("model", "Disease model (e.g. cisplatin-induced nephrotoxicity)", "النموذج المرضي"),
          ("model_short", "Short name / search term of the model", "اسم مختصر للنموذج (للبحث)"),
          ("drug", "Test compound (e.g. modified citrus pectin (MCP))", "الدواء / المادة المختبرة"),
          ("drug_source", "Supplier of the compound", "مصدر المادة"), ("organ", "Organ studied", "العضو"),
          ("species", "Animals", "الحيوانات"), ("weight", "Body weight", "الوزن"),
          ("ethics", "Ethics committee", "لجنة الأخلاقيات"), ("approval", "Approval number", "رقم الموافقة"),
          ("anaesthesia", "Anaesthesia", "التخدير"), ("samples", "Samples assayed", "العينات"),
          ("kits", "Kit manufacturers", "مصنّعو الكواشف"), ("keywords", "Keywords (; separated)", "الكلمات المفتاحية")]


def T(en, ar):
    return ar if SETTINGS.language == "ar" else en


class PaperDialog(QDialog):
    def __init__(self, parent, groups=(), histo_text="", histo_methods=""):
        super().__init__(parent)
        self.setWindowTitle(T("Write the full paper", "كتابة البحث كاملًا"))
        self.qs = QSettings("MedStatix", "MedStatixPro")
        saved = json.loads(self.qs.value("paper_study", "{}") or "{}")
        self.refs: list[RF.Ref] = [RF.Ref(**d) for d in json.loads(self.qs.value("paper_refs", "[]") or "[]")]
        self.found: list[RF.Ref] = []
        lay = QVBoxLayout(self)
        note = QLabel(T("Templates mode: every sentence is built from your data, fixed academic templates and your references; what "
                        "only you can write is left as [yellow prompts]. Claude mode (Output tab): the narrative sections are "
                        "written by Claude from the same data, checked against your numbers and references, and declared.",
                        "وضع القوالب: كل جملة مبنية من بياناتك وقوالب أكاديمية ثابتة ومراجعك، وما لا يكتبه إلا أنت يُترك كتلميحات "
                        "[صفراء]. وضع Claude (تبويب الإخراج): يكتب Claude الأقسام السردية من البيانات نفسها، مع مطابقتها "
                        "بأرقامك ومراجعك، وإقرار باستخدامه."))
        note.setWordWrap(True); note.setObjectName("hint"); lay.addWidget(note)
        tabs = QTabWidget(); lay.addWidget(tabs, 1)
        # study
        w = QWidget(); f = QFormLayout(w); self.ed = {}
        for k, en, ar in FIELDS:
            e = QLineEdit(str(saved.get(k, PP.DEFAULT_STUDY.get(k, "")) or "")); self.ed[k] = e; f.addRow(T(en, ar), e)
        self.n = QSpinBox(); self.n.setRange(2, 100); self.n.setValue(int(saved.get("n_per_group", 8))); f.addRow(T("Animals per group", "عدد الحيوانات في المجموعة"), self.n)
        tabs.addTab(w, T("Study", "الدراسة"))
        # groups
        w = QWidget(); v = QVBoxLayout(w)
        v.addWidget(QLabel(T("Describe what each group received (dose, route, duration).", "اكتب ما أخذته كل مجموعة (الجرعة، الطريق، المدة).")))
        gd = saved.get("group_desc", {})
        self.gt = QTableWidget(len(groups), 2); self.gt.setHorizontalHeaderLabels([T("Group", "المجموعة"), T("Treatment", "المعاملة")])
        for i, g in enumerate(groups):
            it = QTableWidgetItem(g); it.setFlags(it.flags() & ~Qt.ItemIsEditable); self.gt.setItem(i, 0, it)
            self.gt.setItem(i, 1, QTableWidgetItem(gd.get(g, "")))
        self.gt.horizontalHeader().setStretchLastSection(True); v.addWidget(self.gt)
        tabs.addTab(w, T("Groups", "المجموعات"))
        # references
        w = QWidget(); v = QVBoxLayout(w)
        r = QHBoxLayout(); self.q = QLineEdit(); self.q.setPlaceholderText(T("PubMed search, e.g. cisplatin nephrotoxicity rats Nrf2", "بحث PubMed"))
        b = QPushButton(T("Search PubMed", "ابحث في PubMed")); b.clicked.connect(self.search); r.addWidget(self.q, 1); r.addWidget(b)
        b = QPushButton(T("Suggest searches", "اقترح كلمات البحث")); b.clicked.connect(self.suggest); r.addWidget(b)
        v.addLayout(r)
        self.res = QListWidget(); v.addWidget(self.res, 1)
        r = QHBoxLayout()
        for txt, fn in [(T("Add ticked", "أضف المحدد"), self.add_ticked), (T("Import RIS / EndNote export…", "استيراد RIS من EndNote…"), self.import_ris),
                        (T("📖 Add from the reference library…", "📖 أضف من مكتبة المراجع…"), self.from_library),
                        (T("Remove selected", "حذف المحدد"), self.remove_sel), (T("Save RIS for EndNote…", "حفظ RIS لـ EndNote…"), self.save_ris)]:
            b = QPushButton(txt); b.clicked.connect(fn); r.addWidget(b)
        v.addLayout(r)
        v.addWidget(QLabel(T("References of this paper:", "مراجع البحث:")))
        self.lib = QListWidget(); v.addWidget(self.lib, 1)
        tabs.addTab(w, T("References", "المراجع"))
        # histology + output
        w = QWidget(); f = QFormLayout(w)
        self.histo = QPlainTextEdit(histo_text); self.histo.setPlaceholderText(T("Histopathology findings (filled from the image reader when available)", "نتائج الهستوباثولوجي"))
        self.histo.setMaximumHeight(110); f.addRow(T("Histopathology results", "نتائج الهستو"), self.histo)
        self.hmeth = QPlainTextEdit(histo_methods); self.hmeth.setMaximumHeight(80); f.addRow(T("Image methods", "طرق الصور"), self.hmeth)
        self.journal = QComboBox(); self.journal.addItem(T("— general —", "— عام —"), "")
        for k, d in JOURNALS.items():
            self.journal.addItem(T(k, d.get("ar", k)), k)
        f.addRow(T("Publisher", "الناشر"), self.journal)
        self.style = QComboBox()
        for k, en in RF.STYLES.items():
            self.style.addItem(en, k)
        self.style.insertSeparator(self.style.count())
        try:
            from ..refman.styles import list_styles
            for sdef in list_styles():          # every journal style of the reference library (CSL)
                self.style.addItem(T("Journal style: ", "نمط مجلة: ") + sdef["title"], "csl:" + sdef["id"])
        except Exception:       # noqa: BLE001
            pass
        i = self.style.findData(self.qs.value("paper_style", "endnote")); self.style.setCurrentIndex(max(i, 0))
        f.addRow(T("Citations", "الاستشهادات"), self.style)
        # writing mode
        self.mode = QComboBox()
        self.mode.addItem(T("Templates only (no AI, author prompts left in yellow)", "قوالب فقط (بدون ذكاء اصطناعي، مع تلميحات صفراء)"), "templates")
        self.mode.addItem(T("Claude writes Abstract, Introduction, Results text, Discussion, Conclusion (AI, disclosed)",
                            "Claude يكتب الملخص والمقدمة ونص النتائج والمناقشة والخاتمة (ذكاء اصطناعي مع إفصاح)"), "ai")
        self.mode.setCurrentIndex(1 if self.qs.value("paper_mode", "templates") == "ai" else 0)
        f.addRow(T("Writing", "طريقة الكتابة"), self.mode)
        self.key = QLineEdit(str(self.qs.value("anthropic_key", "") or "")); self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText(T("Anthropic API key (sk-ant-…), or set ANTHROPIC_API_KEY", "مفتاح Anthropic API (sk-ant-…)"))
        f.addRow(T("API key", "مفتاح API"), self.key)
        from ..report.ai_writer import MODELS
        self.model = QComboBox()
        for k, v in MODELS.items():
            self.model.addItem(v, k)
        i = self.model.findData(self.qs.value("ai_model", "claude-opus-5-5")); self.model.setCurrentIndex(max(i, 0))
        f.addRow(T("Model", "النموذج"), self.model)
        ai_note = QLabel(T("Claude receives only your study data, results and the references (with abstracts). Numbers that are "
                           "not in your data are flagged [check: …] and citations come only from your reference list. The "
                           "Methods stay exactly as built from your data. An AI-use declaration is added for the journal. "
                           "Usage is billed to your Anthropic account (a paper costs well under one US dollar).",
                           "يستلم Claude بيانات دراستك ونتائجها والمراجع (مع ملخصاتها) فقط. أي رقم غير موجود في بياناتك يُعلَّم "
                           "[check: …] والاستشهادات من قائمة مراجعك فقط. قسم الطرق يبقى كما بُني من بياناتك. يُضاف إقرار "
                           "استخدام الذكاء الاصطناعي الذي تطلبه المجلات. التكلفة على حسابك في Anthropic (أقل من دولار للبحث)."))
        ai_note.setWordWrap(True); ai_note.setObjectName("hint"); f.addRow(ai_note)
        self.auto_refs = QCheckBox(T("Search PubMed automatically and add references when the list has fewer than 15",
                                     "ابحث في PubMed تلقائيًا وأضف مراجع إذا كانت القائمة أقل من 15"))
        self.auto_refs.setChecked(self.qs.value("paper_auto_refs", "true") in (True, "true"))
        f.addRow(self.auto_refs)
        f.addRow(QLabel(T("EndNote: import the RIS file saved next to the Word file into your library, then in Word press "
                          "EndNote → Update Citations and Bibliography and pick the journal style.",
                          "EndNote: استورد ملف RIS المحفوظ بجوار ملف Word إلى مكتبتك، ثم في Word اضغط EndNote ← "
                          "Update Citations and Bibliography واختر نمط المجلة.")))
        tabs.addTab(w, T("Output", "الإخراج"))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(T("Write the paper (Word)…", "اكتب البحث (Word)…"))
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject); lay.addWidget(bb)
        self._show_lib(); self.resize(900, 720)

    # references -------------------------------------------------------------
    def _label(self, r):
        return f"{r.first_surname} {r.year}. {r.title}. {r.journal}" + (f" (PMID {r.pmid})" if r.pmid else "")

    def _show_lib(self):
        self.lib.clear()
        for r in self.refs:
            self.lib.addItem(self._label(r))

    def suggest(self):
        s = self.study()
        q = " ".join(x for x in (s.get("model_short") or s.get("model"), s.get("drug"), "rats") if x)
        self.q.setText(q)

    def search(self):
        if not self.q.text().strip():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.found = RF.pubmed_search(self.q.text().strip(), 25)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "", T(f"PubMed could not be reached: {e}", f"تعذر الاتصال بـ PubMed: {e}")); return
        QApplication.restoreOverrideCursor()
        self.res.clear()
        for r in self.found:
            it = QListWidgetItem(self._label(r)); it.setFlags(it.flags() | Qt.ItemIsUserCheckable); it.setCheckState(Qt.Unchecked)
            it.setToolTip(r.abstract[:800]); self.res.addItem(it)

    def add_ticked(self):
        keys = {r.key() for r in self.refs}
        for i in range(self.res.count()):
            if self.res.item(i).checkState() == Qt.Checked and self.found[i].key() not in keys:
                self.refs.append(self.found[i])
        self._show_lib()

    def import_ris(self):
        p, _ = QFileDialog.getOpenFileName(self, "", "", "RIS (*.ris *.txt *.enw)")
        if p:
            with open(p, encoding="utf-8", errors="replace") as fh:
                new = RF.from_ris(fh.read())
            keys = {r.key() for r in self.refs}
            self.refs += [r for r in new if r.key() not in keys]; self._show_lib()

    def from_library(self):
        from ..refman import formats as FM
        from .refman_ui import LibraryPicker
        d = LibraryPicker(self)
        if d.exec():
            keys = {r.key() for r in self.refs}
            for it in d.chosen():
                r = FM.to_ref(it)
                if r.key() not in keys:
                    self.refs.append(r); keys.add(r.key())
            self._show_lib()

    def remove_sel(self):
        for it in sorted(self.lib.selectedIndexes(), key=lambda i: -i.row()):
            self.refs.pop(it.row())
        self._show_lib()

    def save_ris(self):
        p, _ = QFileDialog.getSaveFileName(self, "", "references.ris", "RIS (*.ris)")
        if p:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(RF.to_ris(self.refs))

    # values -------------------------------------------------------------------
    def study(self):
        d = {k: e.text().strip() for k, e in self.ed.items()}
        d["n_per_group"] = self.n.value()
        d["group_desc"] = {self.gt.item(i, 0).text(): (self.gt.item(i, 1).text() if self.gt.item(i, 1) else "")
                           for i in range(self.gt.rowCount())}
        return d

    def remember(self):
        self.qs.setValue("paper_study", json.dumps(self.study(), ensure_ascii=False))
        self.qs.setValue("paper_refs", json.dumps([r.to_dict() for r in self.refs], ensure_ascii=False))
        self.qs.setValue("paper_style", self.style.currentData())
        self.qs.setValue("paper_mode", self.mode.currentData()); self.qs.setValue("anthropic_key", self.key.text().strip())
        self.qs.setValue("ai_model", self.model.currentData()); self.qs.setValue("paper_auto_refs", "true" if self.auto_refs.isChecked() else "false")
