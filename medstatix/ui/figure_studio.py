"""Research-image studio: enhance any figure of the paper (photographs, blots/gels, graphs, scans, fluorescence) and
export it at the size and dpi the journal asks for. Global, logged operations only (imaging.general)."""
from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QListWidget, QMessageBox, QPushButton, QScrollArea, QSlider,
                               QSplitter, QVBoxLayout, QWidget)

from ..core.settings import SETTINGS
from ..imaging import general as GN
from .histology import np_to_qimage

PREVIEW_SIDE = 1400


def T(en, ar):
    return ar if SETTINGS.language == "ar" else en


def _small(img, side=PREVIEW_SIDE):
    s = min(1.0, side / max(img.shape[:2]))
    if s >= 1:
        return img
    from PIL import Image
    return np.asarray(Image.fromarray(img).resize((round(img.shape[1] * s), round(img.shape[0] * s)), Image.LANCZOS))


class FigureStudio(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.paths, self.images = [], {}
        self.cur = None            # path
        self.preview_in = self.preview_out = None
        self.log = None
        self._timer = QTimer(self); self._timer.setSingleShot(True); self._timer.timeout.connect(self._update)
        root = QHBoxLayout(self)
        split = QSplitter(Qt.Horizontal); root.addWidget(split)
        # ---- left: list
        left = QWidget(); ll = QVBoxLayout(left)
        b = QPushButton("📂 " + T("Open images…", "فتح صور…")); b.setObjectName("primary"); b.clicked.connect(self.open); ll.addWidget(b)
        self.list = QListWidget(); self.list.currentRowChanged.connect(self._select); ll.addWidget(self.list, 1)
        hint = QLabel(T("For photographs, blots and gels, graphs, scans and fluorescence images. Histology and IHC slides "
                        "have their own studio.", "للصور الفوتوغرافية والبلوت والجل والرسوم البيانية والصفحات الممسوحة "
                        "وصور الفلورسنت. شرائح الهستو والمناعية لها قسمها الخاص."))
        hint.setWordWrap(True); hint.setObjectName("hint"); ll.addWidget(hint)
        split.addWidget(left)
        # ---- centre: before/after
        mid = QWidget(); ml = QVBoxLayout(mid)
        mid.setLayoutDirection(Qt.LeftToRight)       # before is always on the left of the comparison
        self.view = QLabel(T("Open an image to begin.", "افتح صورة للبدء.")); self.view.setAlignment(Qt.AlignCenter)
        self.view.setMinimumSize(500, 400); self.view.setStyleSheet("background:#1E2330; color:#C9D1E0;")
        ml.addWidget(self.view, 1)
        r = QHBoxLayout(); r.addWidget(QLabel(T("Before", "قبل")))
        self.split = QSlider(Qt.Horizontal); self.split.setRange(0, 100); self.split.setValue(50)
        self.split.valueChanged.connect(self._show); r.addWidget(self.split, 1); r.addWidget(QLabel(T("After", "بعد")))
        ml.addLayout(r)
        self.qual = QLabel(""); self.qual.setTextFormat(Qt.RichText); ml.addWidget(self.qual)
        split.addWidget(mid)
        # ---- right: controls
        panel = QWidget(); pl = QVBoxLayout(panel)
        g = QGroupBox(T("1 · Image type and one-click enhancement", "١ · نوع الصورة والتحسين بضغطة")); f = QFormLayout(g)
        self.kind = QComboBox(); self.kind.addItem(T("Detect automatically", "تحديد تلقائي"), "auto")
        for k, (en, ar) in GN.KINDS.items():
            self.kind.addItem(T(en, ar), k)
        self.kind.currentIndexChanged.connect(self._changed); f.addRow(T("Type", "النوع"), self.kind)
        self.enh = QCheckBox(T("Apply the recommended enhancement for this type", "طبّق التحسين المقترح لهذا النوع"))
        self.enh.setChecked(True); self.enh.toggled.connect(self._changed); f.addRow(self.enh)
        self.kind_note = QLabel(""); self.kind_note.setWordWrap(True); self.kind_note.setObjectName("hint")
        self.kind_note.setMinimumHeight(self.kind_note.fontMetrics().height() * 4); f.addRow(self.kind_note)
        pl.addWidget(g)
        g = QGroupBox(T("2 · Fine adjustments (whole image)", "٢ · ضبط دقيق (للصورة كلها)")); f = QFormLayout(g)
        self.sl = {}
        for key, en, ar, lo, hi, v in [("brightness", "Brightness", "الإضاءة", -20, 20, 0), ("contrast", "Contrast", "التباين", 70, 140, 100),
                                       ("saturation", "Saturation", "التشبع", 70, 140, 100), ("denoise", "Noise reduction", "إزالة التشويش", 0, 100, 0),
                                       ("sharpen", "Sharpness", "الحدة", 0, 80, 0), ("clahe", "Local contrast", "تباين موضعي", 0, 50, 0)]:
            s = QSlider(Qt.Horizontal); s.setRange(lo, hi); s.setValue(v); s.valueChanged.connect(self._changed)
            self.sl[key] = s; f.addRow(T(en, ar), s)
        self.cb = {}
        for key, en, ar in [("straighten", "Straighten automatically", "تعديل الميل تلقائيًا"), ("autocrop", "Remove empty borders", "إزالة الحواف الفارغة"),
                            ("grayscale", "Greyscale", "رمادي"), ("invert", "Invert (dark bands on light)", "عكس الألوان")]:
            c = QCheckBox(T(en, ar)); c.toggled.connect(self._changed); self.cb[key] = c; f.addRow(c)
        rs = QPushButton(T("Reset adjustments", "إعادة الضبط")); rs.clicked.connect(self.reset); f.addRow(rs)
        pl.addWidget(g)
        g = QGroupBox(T("3 · Size in print and resolution (dpi)", "٣ · المقاس في الطباعة والدقة (dpi)")); f = QFormLayout(g)
        self.width = QComboBox()
        for k, (en, ar) in GN.WIDTH_UI.items():
            self.width.addItem(T(en, ar), GN.WIDTHS_MM[k])
        self.width.addItem(T("Custom width", "عرض مخصص"), 0.0)
        self.width.currentIndexChanged.connect(self._plan)
        self.custom = QDoubleSpinBox(); self.custom.setRange(10, 500); self.custom.setValue(85); self.custom.setSuffix(" mm")
        self.custom.valueChanged.connect(self._plan)
        rw = QHBoxLayout(); rw.addWidget(self.width, 1); rw.addWidget(self.custom); f.addRow(T("Width", "العرض"), rw)
        self.dpi = QComboBox()
        for d, en, ar in [(300, "300 dpi (photographs)", "300 (صور فوتوغرافية)"), (600, "600 dpi (combination, blots)", "600 (صور مع نص، بلوت)"),
                          (1000, "1000 dpi (line art, graphs)", "1000 (رسوم خطية وبيانية)"), (1200, "1200 dpi", "1200")]:
            self.dpi.addItem(T(en, ar), d)
        self.dpi_auto = QCheckBox(T("choose for the image type", "اختر حسب نوع الصورة")); self.dpi_auto.setChecked(True)
        self.dpi_auto.toggled.connect(lambda on: (self.dpi.setEnabled(not on), self._plan()))
        self.dpi.setEnabled(False); self.dpi.currentIndexChanged.connect(self._plan)
        rd = QHBoxLayout(); rd.addWidget(self.dpi, 1); rd.addWidget(self.dpi_auto); f.addRow("DPI", rd)
        self.up = QComboBox()
        self.up.addItem(T("Sharp enlargement (faithful to the original)", "تكبير حاد (أمين على الأصل)"), "sharp")
        self.up.addItem(T("Smooth enlargement (Lanczos)", "تكبير ناعم (Lanczos)"), "lanczos")
        self.up.addItem(T("Pixel-exact (masks, pixel art)", "بكسل بكسل (أقنعة)"), "pixel")
        self.up.currentIndexChanged.connect(self._plan)
        f.addRow(T("Enlarging", "التكبير"), self.up)
        self.allow_up = QCheckBox(T("Enlarge when the image has fewer pixels than needed", "كبّر الصورة إذا كانت بكسلاتها أقل من المطلوب"))
        self.allow_up.setChecked(True); self.allow_up.toggled.connect(self._plan); f.addRow(self.allow_up)
        self.plan_lbl = QLabel(""); self.plan_lbl.setWordWrap(True); self.plan_lbl.setTextFormat(Qt.RichText); f.addRow(self.plan_lbl)
        pl.addWidget(g)
        g = QGroupBox(T("4 · Save", "٤ · الحفظ")); f = QFormLayout(g)
        self.fmt = QComboBox(); [self.fmt.addItem(x) for x in ("TIFF", "PNG", "JPEG", "PDF")]; f.addRow(T("Format", "الصيغة"), self.fmt)
        self.mode = QComboBox()
        self.mode.addItem("RGB", "RGB"); self.mode.addItem(T("Greyscale", "رمادي"), "L"); self.mode.addItem("CMYK", "CMYK")
        f.addRow(T("Colour", "الألوان"), self.mode)
        for txt, fn in [("💾 " + T("Save this image…", "حفظ هذه الصورة…"), self.save_one),
                        ("🗂 " + T("Process all images into a folder…", "معالجة كل الصور إلى مجلد…"), self.save_all),
                        ("📋 " + T("Copy the methods text", "نسخ فقرة الطرق"), self.copy_methods)]:
            b = QPushButton(txt); b.clicked.connect(fn); f.addRow(b)
        pl.addWidget(g)
        pl.addStretch(1)
        sc = QScrollArea(); sc.setWidget(panel); sc.setWidgetResizable(True); sc.setMinimumWidth(380)
        split.addWidget(sc)
        split.setSizes([220, 800, 400])

    # ------------------------------------------------------------------ data
    def open(self):
        paths, _ = QFileDialog.getOpenFileNames(self, T("Open images", "فتح صور"), "",
                                                "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp)")
        self.add_paths(paths)

    def add_paths(self, paths):
        from ..imaging.core import load_image
        for p in paths:
            if p in self.images:
                continue
            try:
                self.images[p] = load_image(p)
            except Exception as e:
                QMessageBox.warning(self, "", f"{os.path.basename(p)}: {e}"); continue
            self.paths.append(p); self.list.addItem(os.path.basename(p))
        if self.paths and self.list.currentRow() < 0:
            self.list.setCurrentRow(0)

    def _select(self, i):
        if 0 <= i < len(self.paths):
            self.cur = self.paths[i]
            self._changed(immediate=True)

    def reset(self):
        for k, s in self.sl.items():
            s.blockSignals(True); s.setValue(100 if k in ("contrast", "saturation") else 0); s.blockSignals(False)
        for c in self.cb.values():
            c.blockSignals(True); c.setChecked(False); c.blockSignals(False)
        self._changed()

    # ------------------------------------------------------------------ recipe
    def kind_of(self, img):
        k = self.kind.currentData()
        return GN.detect_kind(img) if k == "auto" else k

    def steps_for(self, img, kind):
        st = GN.preset(kind, img) if self.enh.isChecked() else []
        have = {s["op"] for s in st}
        for key in ("straighten", "autocrop"):
            if self.cb[key].isChecked() and key not in have:
                st.insert(0, {"op": key, "params": {}})
        if self.cb["grayscale"].isChecked() and "grayscale" not in have:
            st.append({"op": "grayscale", "params": {}})
        if self.cb["invert"].isChecked():
            st.append({"op": "invert", "params": {}})
        b, c = self.sl["brightness"].value() / 100, self.sl["contrast"].value() / 100
        if b or c != 1:
            st.append({"op": "brightness_contrast", "params": {"brightness": b, "contrast": c}})
        if self.sl["saturation"].value() != 100:
            st.append({"op": "saturation", "params": {"factor": self.sl["saturation"].value() / 100}})
        if self.sl["clahe"].value():
            st.append({"op": "clahe", "params": {"strength": self.sl["clahe"].value() / 100}})
        if self.sl["denoise"].value():
            st.append({"op": "denoise", "params": {"strength": self.sl["denoise"].value() / 100}})
        if self.sl["sharpen"].value():
            st.append({"op": "sharpen", "params": {"amount": self.sl["sharpen"].value() / 100, "radius": 1.0}})
        return st

    def width_mm(self):
        w = self.width.currentData()
        return self.custom.value() if not w else w

    def dpi_value(self, kind):
        return GN.DPI_FOR[kind] if self.dpi_auto.isChecked() else self.dpi.currentData()

    # ------------------------------------------------------------------ preview
    def _changed(self, *a, immediate=False):
        if immediate:
            self._update()
        else:
            self._timer.start(350)

    def _update(self):
        if not self.cur:
            return
        img = self.images[self.cur]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            small = _small(img)
            kind = self.kind_of(img)
            out, done = GN.apply(small, self.steps_for(small, kind), kind)
            self.preview_in, self.preview_out, self.cur_kind = small, out, kind
            self.log = GN.FigureLog(source=os.path.basename(self.cur), kind=kind, steps=done)
        finally:
            QApplication.restoreOverrideCursor()
        notes = {"blot": T("Blots and gels: only linear changes are allowed (greyscale, rotation, levels); keep the raw file for "
                           "quantification.", "البلوت والجل: يُسمح بالتعديلات الخطية فقط (رمادي، تدوير، مستويات)، واحتفظ بالملف "
                           "الأصلي للقياس الكمي."),
                 "chart": T("Best: re-export the graph from its source program as vector (PDF/SVG/EMF) or at 1000 dpi; "
                            "this cleans and enlarges a bitmap copy.", "الأفضل: صدّر الرسم من برنامجه الأصلي كملف متجهي أو بدقة 1000؛ "
                            "هنا تُنظَّف النسخة النقطية وتُكبَّر."),
                 "photo": "", "scan": "", "fluorescence": T("Levels are applied identically to all channels.", "تُطبَّق المستويات بالتساوي على كل القنوات.")}
        self.kind_note.setText(T("Detected: ", "النوع: ") + T(*GN.KINDS[kind]) + (" — " + notes[kind] if notes[kind] else ""))
        q0, q1 = GN.quality(self.preview_in), GN.quality(self.preview_out)
        rows = "".join(f"<td style='padding:0 8px'>{k}<br><b>{q0[k]}</b> → <b>{q1[k]}</b></td>"
                       for k in ("sharpness", "noise", "contrast (SD)", "clipped bright %"))
        self.qual.setText(f"<table><tr>{rows}</tr></table>")
        self._show(); self._plan()

    def _show(self, *a):
        if self.preview_out is None:
            return
        a, b = self.preview_in, self.preview_out
        if a.shape != b.shape:          # cropped / rotated: show the processed image only on the right part
            from PIL import Image
            a = np.asarray(Image.fromarray(a).resize((b.shape[1], b.shape[0])))
        x = int(b.shape[1] * self.split.value() / 100)
        comp = b.copy(); comp[:, :x] = a[:, :x]
        if 0 < x < b.shape[1]:
            comp[:, max(0, x - 1):x + 1] = (200, 54, 75)
        pm = QPixmap.fromImage(np_to_qimage(comp))
        self.view.setPixmap(pm.scaled(self.view.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e); self._show()

    def _plan(self, *a):
        if not self.cur or self.preview_out is None:
            return
        img = self.images[self.cur]
        # cropping changes the size: scale the full-resolution size by what the preview lost
        shape = (round(img.shape[0] * self.preview_out.shape[0] / self.preview_in.shape[0]),
                 round(img.shape[1] * self.preview_out.shape[1] / self.preview_in.shape[1]))
        if self.dpi_auto.isChecked():
            i = self.dpi.findData(GN.DPI_FOR[self.cur_kind])
            self.dpi.blockSignals(True); self.dpi.setCurrentIndex(max(i, 0)); self.dpi.blockSignals(False)
        p = GN.print_plan(shape, self.width_mm(), self.dpi_value(self.cur_kind))
        col = {"ok": "#1B7F3B", "upscale": "#B26A00", "low": "#C8364B"}[p["verdict"]]
        msg = {"ok": T("Enough pixels: the image will be saved at this size without enlarging.",
                       "البكسلات كافية: ستُحفظ الصورة بهذا المقاس دون تكبير."),
               "upscale": T(f"Needs enlarging ×{p['factor']}. This is acceptable for print, but no new detail is created.",
                            f"تحتاج تكبيرًا ×{p['factor']}، وهذا مقبول للطباعة لكنه لا يضيف تفاصيل جديدة."),
               "low": T(f"Needs ×{p['factor']}: the original is small for this size. Use a narrower width or the original "
                        f"file/camera image if you have it; enlargement is limited to ×4.",
                        f"تحتاج ×{p['factor']}: الأصل صغير على هذا المقاس. استخدم عرضًا أصغر أو الملف الأصلي من الكاميرا إن وُجد؛ "
                        f"أقصى تكبير ×4.")}[p["verdict"]]
        self.plan_lbl.setText(
            f"{T('Now', 'الآن')}: {p['have_px'][0]} × {p['have_px'][1]} px = <b>{p['effective_dpi']} dpi</b> "
            f"{T('at', 'عند')} {p['width_mm']:.0f} mm · {T('needed', 'المطلوب')}: {p['need_px'][0]} × {p['need_px'][1]} px "
            f"({p['dpi']} dpi, {p['width_mm']:.0f} × {p['height_mm']} mm)<br><span style='color:{col}'><b>{msg}</b></span>")

    # ------------------------------------------------------------------ export
    def render_full(self, path):
        img = self.images[path]
        kind = self.kind_of(img)
        dpi = self.dpi_value(kind)
        out, log, plan = GN.process(img, kind, self.steps_for(img, kind), self.width_mm(), dpi,
                                    self.up.currentData(), self.allow_up.isChecked())
        log.source = os.path.basename(path)
        return out, log, log.output.get("dpi", dpi)

    def _ext(self):
        return {"TIFF": "tif", "PNG": "png", "JPEG": "jpg", "PDF": "pdf"}[self.fmt.currentText()]

    def save_one(self):
        if not self.cur:
            return
        base = os.path.splitext(os.path.basename(self.cur))[0] + "_enhanced." + self._ext()
        path, _ = QFileDialog.getSaveFileName(self, T("Save image", "حفظ الصورة"), base)
        if not path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            out, log, dpi = self.render_full(self.cur)
            GN.save(out, path, dpi, self.mode.currentData())
            with open(os.path.splitext(path)[0] + "_edit-log.json", "w", encoding="utf-8") as fh:
                fh.write(log.to_json())
        finally:
            QApplication.restoreOverrideCursor()
        self.log = log
        QMessageBox.information(self, "", T(f"Saved {out.shape[1]} × {out.shape[0]} px at {dpi} dpi.\n\n{log.methods_text()}",
                                            f"حُفظت الصورة {out.shape[1]} × {out.shape[0]} بكسل بدقة {dpi} dpi.\n\n{log.methods_text()}"))

    def save_all(self):
        if not self.paths:
            return
        d = QFileDialog.getExistingDirectory(self, T("Output folder", "مجلد الحفظ"))
        if not d:
            return
        texts = []
        for i, p in enumerate(self.paths):
            QApplication.processEvents()
            out, log, dpi = self.render_full(p)
            name = os.path.splitext(os.path.basename(p))[0]
            GN.save(out, os.path.join(d, f"{name}_enhanced.{self._ext()}"), dpi, self.mode.currentData())
            with open(os.path.join(d, f"{name}_edit-log.json"), "w", encoding="utf-8") as fh:
                fh.write(log.to_json())
            texts.append(f"{name}: {log.methods_text()}")
        with open(os.path.join(d, "methods.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n\n".join(texts))
        QMessageBox.information(self, "", T(f"{len(self.paths)} images saved with their edit logs and methods.txt.",
                                            f"حُفظت {len(self.paths)} صورة مع سجلات التعديل وملف methods.txt."))

    def copy_methods(self):
        if self.log is None:
            return
        log = self.log
        log.output = {"dpi": self.dpi_value(log.kind), "width_mm": self.width_mm()}
        QApplication.clipboard().setText(log.methods_text())
