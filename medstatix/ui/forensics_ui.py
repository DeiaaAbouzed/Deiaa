"""Dialogs for image-integrity screening: duplicate / re-used image detector and the Photopea round-trip check."""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QMessageBox,
                               QProgressDialog, QPushButton, QSplitter, QVBoxLayout)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

from ..core.result import Result
from ..core.settings import SETTINGS
from ..imaging import core as IC
from ..imaging import forensics as FO

IMG_EXT = (".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp")


def T(en, ar):
    return ar if SETTINGS.language == "ar" else en


def _small(img, max_side=1600):
    s = max(img.shape[:2]) / max_side
    if s <= 1:
        return img
    from skimage import transform
    return (transform.rescale(img, 1 / s, channel_axis=2, anti_aliasing=True) * 255).round().astype(np.uint8)


class DuplicateDialog(QDialog):
    """Screen a folder (or a set of files) for duplicated, flipped, rotated, cropped or cloned image regions."""

    def __init__(self, parent=None, on_result=None):
        super().__init__(parent)
        self.on_result = on_result
        self.setWindowTitle(T("Duplicate / re-used image detector", "كاشف الصور المكررة والمعاد استخدامها"))
        self.images, self.findings = {}, []
        lay = QVBoxLayout(self)
        hint = QLabel(T("Screens every pair of images for whole-image re-use (also rotated or mirrored), partial overlap "
                        "(cropped or rescaled fields) and copy-move cloning inside one image. A flagged pair must be checked by eye.",
                        "يفحص كل زوج من الصور بحثاً عن إعادة استخدام الصورة كاملة (حتى لو دُوّرت أو عُكست)، أو تداخل جزئي "
                        "(حقل مقصوص أو مكبّر)، أو نسخ ولصق داخل الصورة نفسها. أي نتيجة يجب مراجعتها بالعين."))
        hint.setWordWrap(True); hint.setObjectName("hint"); lay.addWidget(hint)
        row = QHBoxLayout()
        for txt, fn in [(T("Choose folder…", "اختيار مجلد…"), self.pick_folder), (T("Choose files…", "اختيار ملفات…"), self.pick_files)]:
            b = QPushButton(txt); b.clicked.connect(fn); row.addWidget(b)
        self.run_btn = QPushButton(T("Run screen", "ابدأ الفحص")); self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self.run); row.addWidget(self.run_btn)
        self.rep_btn = QPushButton(T("Send report to Results", "إرسال التقرير إلى النتائج")); self.rep_btn.clicked.connect(self.report)
        row.addWidget(self.rep_btn); row.addStretch(1)
        lay.addLayout(row)
        self.status = QLabel(""); lay.addWidget(self.status)
        sp = QSplitter(Qt.Horizontal)
        self.list = QListWidget(); self.list.currentRowChanged.connect(self.show_finding)
        sp.addWidget(self.list)
        self.canvas_holder = QVBoxLayout(); self.canvas = None
        from PySide6.QtWidgets import QWidget
        right = QWidget(); right.setLayout(self.canvas_holder); sp.addWidget(right)
        sp.setSizes([320, 700])
        lay.addWidget(sp, 1)
        self.resize(1100, 700)

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "")
        if d:
            files = [os.path.join(r, f) for r, _, fs in os.walk(d) for f in sorted(fs) if f.lower().endswith(IMG_EXT)]
            self._load(files)

    def pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "", "", "Images (*.tif *.tiff *.png *.jpg *.jpeg *.bmp)")
        if files:
            self._load(files)

    def _load(self, files):
        self.images = {}
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for f in files[:200]:
                try:
                    self.images[os.path.relpath(f, os.path.dirname(files[0])) if len(files) > 1 else os.path.basename(f)] = _small(IC.load_image(f))
                except Exception:
                    pass
        finally:
            QApplication.restoreOverrideCursor()
        self.status.setText(T(f"{len(self.images)} images loaded.", f"تم تحميل {len(self.images)} صورة."))

    def run(self):
        if len(self.images) < 1:
            return
        pd_ = QProgressDialog(T("Screening images…", "جارٍ فحص الصور…"), None, 0, 0, self)
        pd_.setWindowModality(Qt.WindowModal); pd_.show(); QApplication.processEvents()
        try:
            self.findings = FO.find_duplicates(self.images)
        finally:
            pd_.close()
        self.list.clear()
        for f in self.findings:
            self.list.addItem(f"⚠ {f['type']}: {f['a']}" + (f" ↔ {f['b']}" if f['a'] != f['b'] else "") + f"  ({f['transform']})")
        n = len(self.images)
        self.status.setText(T(f"{n} images, {n * (n - 1) // 2} pairs screened: {len(self.findings)} finding(s).",
                              f"تم فحص {n} صورة و{n * (n - 1) // 2} زوجاً: {len(self.findings)} نتيجة مشتبه بها."))
        if self.findings:
            self.list.setCurrentRow(0)
        else:
            QMessageBox.information(self, "", T("No duplicated or cloned regions were found.", "لم يُعثر على صور أو مناطق مكررة."))

    def show_finding(self, i):
        if i < 0 or i >= len(self.findings):
            return
        f = self.findings[i]
        fig = FO.match_figure(self.images[f["a"]], self.images[f["b"]], f)
        if self.canvas is not None:
            self.canvas.setParent(None); self.canvas.deleteLater()
        self.canvas = FigureCanvasQTAgg(fig); self.canvas_holder.addWidget(self.canvas)

    def report(self):
        if self.on_result is None:
            return
        res = Result("Image duplication screen", f"{len(self.images)} images")
        rows = [{"Finding": f["type"], "Image A": f["a"], "Image B": f["b"] if f["b"] != f["a"] else "(same image)",
                 "Transform": f["transform"], "Evidence": f["detail"]} for f in self.findings]
        res.table(pd.DataFrame(rows) if rows else pd.DataFrame([{"Finding": "None", "Evidence": "No duplicated or cloned regions"}]),
                  "Duplicate and copy-move screen")
        for f in self.findings[:12]:
            res.figure(FO.match_figure(self.images[f["a"]], self.images[f["b"]], f), f"{f['a']} ↔ {f['b']}: {f['type']}")
        res.interpret(f"{len(self.findings)} potential duplication(s) among {len(self.images)} images. Each must be checked visually; "
                      f"legitimate re-use (e.g. the same control shown twice) must be stated in the legend.",
                      f"{len(self.findings)} حالة تكرار محتملة بين {len(self.images)} صورة. يجب مراجعة كل حالة بالعين، "
                      f"وأي إعادة استخدام مشروعة (مثل عرض نفس صورة الضابطة مرتين) يجب ذكرها في وسيلة الإيضاح.")
        res.methods(FO.METHOD_TEXT)
        self.on_result(res)
        QMessageBox.information(self, "", T("Report sent to Results.", "تم إرسال التقرير إلى النتائج."))


PHOTOPEA_WARNING_EN = ("Photopea is a free online editor (www.photopea.com). Use it ONLY to arrange panels and add text, "
                       "arrows and scale bars. Do not paint, clone, heal, blur or brighten any part of the tissue: journals "
                       "treat local edits as image manipulation.\n\nThe image was saved to:\n{path}\nand copied to the clipboard "
                       "(paste it with Ctrl+V in Photopea, or use File › Open).\n\nWhen you have finished, export a PNG or TIFF "
                       "from Photopea and press “Check image returned from Photopea” here: MedStatix will find your image "
                       "inside the figure and confirm that only labels were added.")
PHOTOPEA_WARNING_AR = ("Photopea محرر صور مجاني على الإنترنت (www.photopea.com). استخدمه فقط لترتيب اللوحات وإضافة النصوص "
                       "والأسهم ومقياس الرسم. لا ترسم ولا تنسخ ولا تُصلح ولا تطمس ولا تفتّح أي جزء من النسيج، فالمجلات تعدّ "
                       "التعديل الموضعي تلاعباً بالصورة.\n\nحُفظت الصورة في:\n{path}\nونُسخت إلى الحافظة (الصقها في Photopea بـ "
                       "Ctrl+V أو افتحها من File › Open).\n\nبعد الانتهاء صدّر الصورة من Photopea بصيغة PNG أو TIFF ثم اضغط هنا "
                       "«فحص الصورة العائدة من Photopea»: سيبحث البرنامج عن صورتك داخل اللوحة ويتأكد أن الإضافات تسميات فقط.")
