"""R console: run R code on the current data set (as data frame `d`) and see R's own output."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSplitter,
                               QVBoxLayout)

from ..core import rbridge
from ..core.settings import SETTINGS


def T(en, ar):
    return ar if SETTINGS.language == "ar" else en


class RConsole(QDialog):
    def __init__(self, df=None, code="", parent=None, title=None):
        super().__init__(parent)
        self.df = df
        self.setWindowTitle(title or T("R console", "وحدة R"))
        lay = QVBoxLayout(self)
        rs = rbridge.find_rscript()
        info = QLabel((T("R found: ", "تم العثور على R: ") + rs) if rs else
                      T("R is not installed. Install it free from https://cran.r-project.org, then reopen this window.",
                        "برنامج R غير مثبت. ثبّته مجاناً من https://cran.r-project.org ثم افتح هذه النافذة من جديد."))
        info.setWordWrap(True); info.setObjectName("hint"); info.setOpenExternalLinks(True)
        lay.addWidget(info)
        lay.addWidget(QLabel(T("The current data set is available in R as the data frame  d", "البيانات الحالية متاحة داخل R باسم  d")))
        mono = QFont("Consolas"); mono.setStyleHint(QFont.Monospace)
        sp = QSplitter(Qt.Vertical)
        self.code = QPlainTextEdit(code or "str(d)\nsummary(d)\n"); self.code.setFont(mono)
        self.out = QPlainTextEdit(); self.out.setReadOnly(True); self.out.setFont(mono)
        sp.addWidget(self.code); sp.addWidget(self.out); sp.setSizes([220, 420])
        lay.addWidget(sp, 1)
        row = QHBoxLayout()
        b = QPushButton(T("Run in R  (Ctrl+Enter)", "تشغيل في R  (Ctrl+Enter)")); b.setObjectName("primary"); b.clicked.connect(self.run)
        b.setShortcut("Ctrl+Return"); b.setEnabled(bool(rs))
        row.addWidget(b); row.addStretch(1)
        lay.addLayout(row)
        self.resize(900, 700)

    def run(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok, txt = rbridge.run_r(self.code.toPlainText() + "\n", self.df)
        finally:
            QApplication.restoreOverrideCursor()
        self.out.setPlainText(txt)
