"""Publishing tools: journal presets, manuscript builder, reviewer report and the multi-panel figure builder."""
from __future__ import annotations

import io
import os

import numpy as np
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QVBoxLayout)

from ..core.result import fig_to_png_bytes
from ..core.settings import SETTINGS
from ..report.journals import JOURNALS, apply_journal, summary


def T(en, ar):
    return ar if SETTINGS.language == "ar" else en


def journal_combo(with_none=True):
    c = QComboBox()
    if with_none:
        c.addItem(T("— no journal preset —", "— بدون مجلة محددة —"), "")
    for k, j in JOURNALS.items():
        c.addItem(j["ar"] if SETTINGS.language == "ar" else k, k)
    i = c.findData(getattr(SETTINGS, "journal", ""))
    if i >= 0:
        c.setCurrentIndex(i)
    return c


class JournalDialog(QDialog):
    """Choose the target journal: figure size, font and export resolution follow its author guidelines."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(T("Target journal", "المجلة المستهدفة"))
        self.resize(560, 300)
        lay = QVBoxLayout(self); f = QFormLayout()
        self.j = journal_combo(); self.w = QComboBox()
        f.addRow(T("Journal / publisher", "المجلة / الناشر"), self.j); f.addRow(T("Figure width", "عرض الرسم"), self.w)
        lay.addLayout(f)
        self.info = QLabel(); self.info.setWordWrap(True); self.info.setObjectName("hint"); lay.addWidget(self.info)
        self.j.currentIndexChanged.connect(self._upd); self._upd()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _upd(self):
        k = self.j.currentData(); self.w.clear()
        if k:
            for wk, mm in JOURNALS[k]["widths"].items():
                self.w.addItem(f"{wk} ({mm} mm)", wk)
            self.info.setText(summary(k, SETTINGS.language == "ar"))
        else:
            self.info.setText(T("Figures use your own settings (Settings → figure size, font, dpi).",
                                "الرسوم تستخدم إعداداتك الخاصة (الإعدادات ← حجم الرسم والخط والدقة)."))

    def apply(self):
        k = self.j.currentData()
        if k:
            apply_journal(k, SETTINGS, self.w.currentData() or "single")
        else:
            SETTINGS.journal = ""
        return k


class ManuscriptDialog(QDialog):
    def __init__(self, parent=None, has_histo=False):
        super().__init__(parent)
        self.setWindowTitle(T("Build manuscript sections (Word)", "بناء أقسام المخطوطة (Word)"))
        self.resize(560, 330)
        lay = QVBoxLayout(self)
        hint = QLabel(T("Creates a Word file with the Statistical analysis paragraph (Methods), a Results section citing the numbered "
                        "tables and figures, APA tables, figure legends and figures sized for the journal.",
                        "ينشئ ملف Word يحتوي فقرة التحليل الإحصائي (الطرق)، وقسم النتائج مع الإشارة للجداول والرسوم المرقمة، "
                        "وجداول بنمط APA، وتعليقات الرسوم، والرسوم بمقاس المجلة."))
        hint.setWordWrap(True); hint.setObjectName("hint"); lay.addWidget(hint)
        f = QFormLayout()
        self.j = journal_combo(); self.w = QComboBox()
        self.j.currentIndexChanged.connect(self._upd); self._upd()
        self.lang = QComboBox()
        for k, en, ar in [("en", "English (for the paper)", "الإنجليزية (للبحث)"), ("both", "English + Arabic (for a thesis)", "إنجليزي + عربي (للرسالة)")]:
            self.lang.addItem(T(en, ar), k)
        self.inline = QCheckBox(T("Tables inside the Results (otherwise at the end)", "الجداول داخل النتائج (وإلا في النهاية)"))
        self.aux = QCheckBox(T("Leave assumption-check tables out (put them in the reviewer report)",
                               "استبعاد جداول فحص الافتراضات (توضع في تقرير المحكّمين)")); self.aux.setChecked(True)
        self.histo = QCheckBox(T("Add image-processing methods (histology)", "إضافة طرق معالجة الصور (الهستو)")); self.histo.setChecked(has_histo)
        self.histo.setEnabled(has_histo)
        f.addRow(T("Journal", "المجلة"), self.j); f.addRow(T("Figure width", "عرض الرسوم"), self.w); f.addRow(T("Language", "اللغة"), self.lang)
        f.addRow(self.inline); f.addRow(self.aux); f.addRow(self.histo)
        lay.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _upd(self):
        k = self.j.currentData(); self.w.clear()
        if k:
            for wk, mm in JOURNALS[k]["widths"].items():
                self.w.addItem(f"{wk} ({mm} mm)", wk)
        else:
            self.w.addItem("160 mm", "single")


class PanelBuilder(QDialog):
    """Multi-panel figure: statistics charts and histology images on one page with A, B, C… labels."""

    def __init__(self, parent, figures, histo_getter=None):
        super().__init__(parent)
        self.setWindowTitle(T("Multi-panel figure builder", "بناء لوحة رسوم متعددة"))
        self.resize(820, 600)
        self.figures = figures          # list of (title, matplotlib Figure)
        self.histo_getter = histo_getter
        self.items = []                 # list of (kind, payload, label)
        lay = QVBoxLayout(self)
        hint = QLabel(T("Add charts from the results and histology images, order them, and export one figure page "
                        "(e.g. A: bar chart, B: H&E control, C: H&E treated).",
                        "أضف رسومًا من النتائج وصورًا من الهستو ورتّبها ثم احفظها كلوحة واحدة "
                        "(مثلًا A: رسم بياني، B: صورة المجموعة الضابطة، C: صورة المجموعة المعالجة)."))
        hint.setWordWrap(True); hint.setObjectName("hint"); lay.addWidget(hint)
        row = QHBoxLayout()
        self.src = QComboBox()
        for i, (t, _) in enumerate(figures):
            self.src.addItem(f"📊 {t}", i)
        row.addWidget(self.src, 1)
        b = QPushButton(T("Add chart", "إضافة رسم")); b.clicked.connect(self.add_chart); row.addWidget(b)
        b = QPushButton(T("Add current histology image", "إضافة صورة الهستو الحالية")); b.clicked.connect(self.add_histo); row.addWidget(b)
        b = QPushButton(T("Add image files…", "إضافة ملفات صور…")); b.clicked.connect(self.add_files); row.addWidget(b)
        lay.addLayout(row)
        self.list = QListWidget(); self.list.setIconSize(QSize(140, 100)); self.list.setDragDropMode(QListWidget.InternalMove)
        lay.addWidget(self.list, 1)
        r2 = QHBoxLayout()
        rm = QPushButton(T("Remove", "حذف")); rm.clicked.connect(self.remove); r2.addWidget(rm)
        r2.addWidget(QLabel(T("Columns", "الأعمدة"))); self.cols = QSpinBox(); self.cols.setRange(1, 6); self.cols.setValue(2); r2.addWidget(self.cols)
        r2.addWidget(QLabel(T("Width", "العرض"))); self.width = QComboBox()
        jn = getattr(SETTINGS, "journal", "")
        widths = JOURNALS[jn]["widths"].items() if jn in JOURNALS else [("single", 85), ("1.5 column", 114), ("double", 174)]
        for k, mm in widths:
            self.width.addItem(f"{k} ({mm} mm)", mm)
        self.width.setCurrentIndex(self.width.count() - 1)
        r2.addWidget(self.width); r2.addStretch(1)
        lay.addLayout(r2)
        bb = QDialogButtonBox()
        ex = bb.addButton("💾 " + T("Export…", "حفظ…"), QDialogButtonBox.AcceptRole); ex.setObjectName("primary")
        bb.addButton(T("Close", "إغلاق"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.export); bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _add(self, kind, payload, label, png=None):
        self.items.append((kind, payload))
        pm = QPixmap()
        if png is not None:
            pm.loadFromData(png)
        it = QListWidgetItem(QIcon(pm), label); it.setData(Qt.UserRole, len(self.items) - 1)
        self.list.addItem(it)

    def add_chart(self):
        i = self.src.currentData()
        if i is None:
            return
        t, fig = self.figures[i]
        self._add("fig", fig, t, fig_to_png_bytes(fig, dpi=60))

    def add_histo(self):
        arr = self.histo_getter() if self.histo_getter else None
        if arr is None:
            QMessageBox.information(self, "", T("Open an image in the histology studio first.", "افتح صورة في استوديو الهستو أولًا.")); return
        self._add("img", arr, T("Histology image", "صورة هستو"), _png(arr))

    def add_files(self):
        from ..imaging import core as IC
        paths, _ = QFileDialog.getOpenFileNames(self, "", "", "Images (*.tif *.tiff *.png *.jpg *.jpeg)")
        for p in paths:
            arr = IC.load_image(p)
            self._add("img", arr, os.path.basename(p), _png(arr))

    def remove(self):
        r = self.list.currentRow()
        if r >= 0:
            self.list.takeItem(r)

    def ordered(self):
        return [self.items[self.list.item(i).data(Qt.UserRole)] for i in range(self.list.count())]

    def compose(self, dpi):
        from ..imaging import core as IC
        items = self.ordered()
        if not items:
            return None
        width_mm = self.width.currentData()
        cols = min(self.cols.value(), len(items))
        panel_px = int(width_mm / 25.4 * dpi / cols)
        arrs = []
        for kind, payload in items:
            if kind == "fig":
                from PIL import Image
                im = Image.open(io.BytesIO(fig_to_png_bytes(payload, dpi=dpi))).convert("RGB")
            else:
                from PIL import Image
                im = Image.fromarray(payload)
            h = int(round(im.height * panel_px / im.width))
            arrs.append(np.asarray(im.resize((panel_px, h), Image.LANCZOS)))
        # pad every panel to the same height so rows line up (white space, no stretching)
        H = max(a.shape[0] for a in arrs)
        padded = []
        for a in arrs:
            pad = np.full((H, a.shape[1], 3), 255, np.uint8); pad[:a.shape[0]] = a; padded.append(pad)
        return IC.compose_panels(padded, ncols=cols, gap_px=max(6, panel_px // 60), label_size=max(16, int(dpi * 0.14)))

    def export(self):
        from .widgets import ExportOptionsDialog
        from ..imaging import core as IC
        if not self.list.count():
            return
        dlg = ExportOptionsDialog(self, allow_width=False, raster=True)
        if dlg.exec() != QDialog.Accepted:
            return
        ext, dpi, _ = dlg.values()
        path, _ = QFileDialog.getSaveFileName(self, "", f"Figure_panel.{ext}", f"{ext.upper()} (*.{ext})")
        if not path:
            return
        if not path.lower().endswith("." + ext):
            path += "." + ext
        arr = self.compose(dpi)
        IC.save_image(arr, path, dpi)
        QMessageBox.information(self, "", T("Saved:", "تم الحفظ:") + f"\n{path}\n{arr.shape[1]}×{arr.shape[0]} px, {dpi} dpi")


def _png(arr):
    from PIL import Image
    im = Image.fromarray(arr); im.thumbnail((240, 180))
    b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()
