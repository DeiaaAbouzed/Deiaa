"""Professional histopathology comment and figure legend for the current AI reading (editable, copyable)."""
from __future__ import annotations

from PySide6.QtWidgets import (QApplication, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QTextEdit, QVBoxLayout)

from ..core.settings import SETTINGS
from ..report import histo_comment as HC


def T(en, ar):
    return ar if SETTINGS.language == "ar" else en


class CommentDialog(QDialog):
    def __init__(self, parent, reading, group="", organ=""):
        super().__init__(parent)
        self.r = reading
        self.setWindowTitle(T("Comment and figure legend", "التعليق ووصف الصورة"))
        lay = QVBoxLayout(self); f = QFormLayout()
        self.organ = QLineEdit(organ); self.organ.setPlaceholderText(T("e.g. kidney, liver, skeletal muscle", "مثل: kidney, liver"))
        self.group = QLineEdit(group); self.group.setPlaceholderText(T("e.g. Toxin + Drug 100", "مثل: G2"))
        self.mag = QLineEdit("×400"); self.fig = QLineEdit("Figure 1")
        self.stain = QLineEdit("IHC" if reading.get("stain") == "IHC" else "H&E")
        for lab, w in [(T("Organ", "العضو"), self.organ), (T("Group", "المجموعة"), self.group), (T("Stain", "الصبغة"), self.stain),
                       (T("Magnification", "التكبير"), self.mag), (T("Figure number", "رقم الشكل"), self.fig)]:
            f.addRow(lab, w); w.textChanged.connect(self.refresh)
        lay.addLayout(f)
        self.boxes = {}
        for key, en, ar in [("comment_en", "Comment (English)", "التعليق (إنجليزي)"), ("legend_en", "Figure legend (English)", "وصف الصورة (إنجليزي)"),
                            ("comment_ar", "Comment (Arabic)", "التعليق (عربي)"), ("legend_ar", "Figure legend (Arabic)", "وصف الصورة (عربي)")]:
            row = QHBoxLayout(); row.addWidget(QLabel("<b>" + T(en, ar) + "</b>")); row.addStretch(1)
            b = QPushButton(T("Copy", "نسخ")); b.clicked.connect(lambda _=False, k=key: QApplication.clipboard().setText(self.boxes[k].toPlainText()))
            row.addWidget(b); lay.addLayout(row)
            t = QTextEdit(); t.setMinimumHeight(70); self.boxes[key] = t; lay.addWidget(t)
        note = QLabel(T("Grades: " + HC.GRADING_TEXT, "الدرجات: " + HC.GRADING_TEXT)); note.setWordWrap(True); note.setObjectName("hint")
        lay.addWidget(note)
        c = QPushButton(T("Close", "إغلاق")); c.clicked.connect(self.accept); lay.addWidget(c)
        self.resize(820, 760)
        self.refresh()

    def texts(self):
        o, g, st, m, fg = self.organ.text(), self.group.text(), self.stain.text(), self.mag.text(), self.fig.text()
        return {"comment_en": HC.image_comment(self.r, o, g), "legend_en": HC.legend(self.r, o, g, st, m, fg),
                "comment_ar": HC.image_comment(self.r, o, g, ar=True), "legend_ar": HC.legend(self.r, o, g, st, m, fg, ar=True)}

    def refresh(self, *a):
        for k, v in self.texts().items():
            self.boxes[k].setPlainText(v)
