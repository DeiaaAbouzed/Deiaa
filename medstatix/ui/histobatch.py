"""Batch histology: enhance and quantify a whole folder with one preset, then send the results to statistics."""
from __future__ import annotations

import json
import os
import re

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..core.settings import SETTINGS
from ..imaging import core as IC

IMG_EXT = (".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp")


def T(en, ar):
    return ar if SETTINGS.language == "ar" else en


def guess_group(path: str, root: str, mode: str) -> str:
    """Group of an image: its sub-folder name, or the filename prefix before '_', '-' or a space."""
    if mode == "folder":
        rel = os.path.relpath(os.path.dirname(path), root)
        return "" if rel == "." else rel.split(os.sep)[0]
    if mode == "prefix":
        base = os.path.splitext(os.path.basename(path))[0]
        return re.split(r"[_\- ]", base)[0]
    return ""


def list_images(root: str) -> list[str]:
    out = []
    for d, _, files in os.walk(root):
        for f in sorted(files):
            if f.lower().endswith(IMG_EXT) and "_processed" not in f and "_before_after" not in f:
                out.append(os.path.join(d, f))
    return sorted(out)


def process_one(path, stain, source, level, kind, px, out_dir, fmt, dpi, save_ba, scale_bar=None):
    """Enhance one image (publication-ready), save it, and quantify on the native-colour measurement image.
    scale_bar: None, or dict(position, style, length_um) to burn a calibrated bar into the saved images (the pixel
    size is px, or the bar already on the image when px is 0)."""
    img = IC.load_image(path)
    from ..imaging import marks as MK
    existing = MK.scale_bar(img)
    if not px and existing and existing.get("um_per_px"):
        px = existing["um_per_px"]
    if existing:
        scale_bar = None if scale_bar is None else "existing"            # never draw a second bar
    out, done, rep, steps, info = IC.publication_ready(img, stain, source, level)
    base = IC.apply_pipeline(img, [s for s in steps if s["op"] == "crop"])[0]
    name = os.path.splitext(os.path.basename(path))[0]
    if out_dir:
        so, sb_ = out, base
        if isinstance(scale_bar, dict) and px:
            so = IC.draw_scale_bar(out, px, **scale_bar)
            sb_ = IC.draw_scale_bar(base, px, **scale_bar)
        IC.save_image(so, os.path.join(out_dir, f"{name}_processed.{fmt}"), dpi)
        if save_ba:
            IC.save_image(IC.compose_panels([sb_, so], 2, ["A  Original", "B  Processed"]),
                          os.path.join(out_dir, f"{name}_before_after.{fmt}"), dpi)
        log = IC.EditLog(os.path.basename(path), done)
        with open(os.path.join(out_dir, f"{name}_edit_log.json"), "w", encoding="utf-8") as f:
            d = json.loads(log.to_json()); d["integrity"] = rep; d["methods_text"] = log.methods_text()
            json.dump(d, f, indent=2, ensure_ascii=False, default=str)
    q = IC.quantify(IC.measurement_image(img, steps), kind, px) if kind and not kind.startswith("None") else {}
    qs = "IHC" if info["stain"] == "IHC-DAB" else "H&E"
    return {"quality_before": IC.image_qc(base, qs)["score"], "quality_after": IC.image_qc(out, qs)["score"],
            "integrity": "passed" if rep.get("passed") else "CHECK", "um_per_px": round(px, 4) if px else None,
            "scale_bar": "already on image" if scale_bar == "existing" else ("added" if px else "no calibration") if scale_bar else "",
            **q}, done


class BatchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(T("Batch: enhance and quantify a folder", "معالجة دفعة كاملة من الصور"))
        self.resize(1000, 640)
        self.rows = None
        self.last_steps = []
        lay = QVBoxLayout(self)
        hint = QLabel(T("Put each group's images in its own sub-folder (e.g. Control, Drug 10, Drug 20) or start file names with "
                        "the group name (Control_1.tif). Every image gets the same publication-ready preset; measurements use the "
                        "native-colour image. Results go straight to the dataset for statistics.",
                        "ضع صور كل مجموعة في مجلد فرعي باسمها (مثل Control وDrug 10) أو ابدأ اسم الملف باسم المجموعة "
                        "(Control_1.tif). كل الصور تُجهز للنشر بنفس الإعدادات، والقياس يتم على الألوان الأصلية، "
                        "والنتائج تُرسل مباشرة للبيانات لعمل الإحصاء."))
        hint.setWordWrap(True); hint.setObjectName("hint"); lay.addWidget(hint)
        f = QFormLayout()
        row = QHBoxLayout(); self.folder = QLineEdit(); b = QPushButton(T("Choose…", "اختيار…")); b.clicked.connect(self.pick)
        row.addWidget(self.folder, 1); row.addWidget(b); f.addRow(T("Images folder", "مجلد الصور"), row)
        self.group_mode = QComboBox()
        for k, en, ar in [("folder", "Sub-folder name", "اسم المجلد الفرعي"), ("prefix", "File-name prefix", "بداية اسم الملف"),
                          ("none", "No groups", "بدون مجموعات")]:
            self.group_mode.addItem(T(en, ar), k)
        f.addRow(T("Groups from", "المجموعات من"), self.group_mode)
        self.stain = QComboBox(); self.stain.addItem(T("Auto-detect", "تحديد تلقائي"), "auto")
        for k, pv in IC.STAIN_PRESETS.items():
            self.stain.addItem(pv["ar"] if SETTINGS.language == "ar" else k, k)
        self.source = QComboBox()
        for k, (en, ar) in IC.SOURCES.items():
            self.source.addItem(T(en, ar), k)
        self.level = QComboBox()
        for k, (_, en, ar) in IC.LEVELS.items():
            self.level.addItem(T(en, ar), k)
        self.level.setCurrentIndex(1)
        r2 = QHBoxLayout(); r2.addWidget(self.stain); r2.addWidget(self.source); r2.addWidget(self.level)
        f.addRow(T("Preset", "الإعدادات"), r2)
        self.kind = QComboBox(); self.kind.addItems(IC.QUANT_KINDS); f.addRow(T("Measure", "القياس"), self.kind)
        self.px = QDoubleSpinBox(); self.px.setDecimals(4); self.px.setRange(0, 100); self.px.setSuffix(" µm/px")
        f.addRow(T("Pixel size", "حجم البكسل"), self.px)
        r3 = QHBoxLayout()
        self.fmt = QComboBox(); [self.fmt.addItem(n, e) for n, e in [("TIFF", "tiff"), ("PNG", "png"), ("JPEG", "jpg")]]
        self.dpi = QComboBox(); [self.dpi.addItem(f"{d} dpi", d) for d in (300, 600, 1200)]; self.dpi.setCurrentIndex(1)
        self.ba = QCheckBox(T("also save before/after", "حفظ مقارنة قبل/بعد أيضًا")); self.ba.setChecked(True)
        r3.addWidget(self.fmt); r3.addWidget(self.dpi); r3.addWidget(self.ba); r3.addStretch(1)
        f.addRow(T("Save processed images", "حفظ الصور المحسنة"), r3)
        r4 = QHBoxLayout()
        self.sbar = QCheckBox(T("add a scale bar", "إضافة مقياس رسم")); self.sbar.setChecked(True)
        self.sbar.setToolTip(T("Uses the pixel size above; when it is 0, the scale bar already drawn on each image is read.",
                               "يستخدم حجم البكسل أعلاه؛ وإذا كان صفرًا يُقرأ مقياس الرسم الموجود على كل صورة."))
        self.sb_pos = QComboBox(); [self.sb_pos.addItem(k, k) for k in IC.SCALE_BAR_POSITIONS]
        self.sb_style = QComboBox(); [self.sb_style.addItem(k, k) for k in IC.SCALE_BAR_STYLES]
        self.sb_len = QSpinBox(); self.sb_len.setRange(0, 5000); self.sb_len.setSuffix(" µm")
        self.sb_len.setSpecialValueText(T("auto length", "طول تلقائي"))
        self.sb_len.setToolTip(T("Use one fixed length for every image at the same magnification.", "استخدم طولًا واحدًا لكل الصور بنفس التكبير."))
        for w_ in (self.sbar, self.sb_pos, self.sb_style, self.sb_len):
            r4.addWidget(w_)
        r4.addStretch(1)
        f.addRow(T("Scale bar", "مقياس الرسم"), r4)
        lay.addLayout(f)
        self.bar = QProgressBar(); lay.addWidget(self.bar)
        self.tbl = QTableWidget(0, 0); lay.addWidget(self.tbl, 1)
        bb = QDialogButtonBox()
        self.run_b = bb.addButton("▶ " + T("Run", "تشغيل"), QDialogButtonBox.ActionRole); self.run_b.setObjectName("primary")
        self.run_b.clicked.connect(self.run)
        self.send_b = bb.addButton(T("Send to dataset → statistics", "إرسال للبيانات ← الإحصاء"), QDialogButtonBox.AcceptRole)
        self.send_b.setEnabled(False)
        bb.addButton(T("Close", "إغلاق"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def pick(self):
        d = QFileDialog.getExistingDirectory(self, "", self.folder.text())
        if d:
            self.folder.setText(d)

    def run(self):
        root = self.folder.text().strip()
        if not root or not os.path.isdir(root):
            QMessageBox.information(self, "", T("Choose the images folder first.", "اختر مجلد الصور أولًا.")); return
        files = list_images(root)
        if not files:
            QMessageBox.information(self, "", T("No images found.", "لم يتم العثور على صور.")); return
        out_dir = os.path.join(root, "MedStatix_processed")
        os.makedirs(out_dir, exist_ok=True)
        self.bar.setRange(0, len(files)); self.run_b.setEnabled(False)
        rows = []
        for i, p in enumerate(files):
            self.bar.setValue(i); self.bar.setFormat(f"{i}/{len(files)}  {os.path.basename(p)}")
            QApplication.processEvents()
            try:
                res, done = self._run_one(p, out_dir)
                self.last_steps = done
                rows.append({"image": os.path.relpath(p, root), "group": guess_group(p, root, self.group_mode.currentData()), **res})
            except Exception as e:  # keep going; report the file
                rows.append({"image": os.path.relpath(p, root), "group": guess_group(p, root, self.group_mode.currentData()),
                             "error": str(e)})
        self.bar.setValue(len(files)); self.bar.setFormat(T("Done", "تم") + f"  {len(files)}")
        self.rows = pd.DataFrame(rows)
        self.rows.to_csv(os.path.join(out_dir, "batch_results.csv"), index=False, encoding="utf-8-sig")
        with open(os.path.join(out_dir, "methods.txt"), "w", encoding="utf-8") as f:
            f.write(IC.EditLog("batch", self.last_steps).methods_text())
        self.show_table(self.rows)
        self.run_b.setEnabled(True); self.send_b.setEnabled(True)
        QMessageBox.information(self, "", T("Saved processed images, edit logs and batch_results.csv in:",
                                            "تم حفظ الصور المحسنة وسجلات التعديل وملف النتائج في:") + f"\n{out_dir}")

    def _run_one(self, p, out_dir):
        import concurrent.futures, time
        with concurrent.futures.ThreadPoolExecutor(1) as ex:
            fut = ex.submit(process_one, p, self.stain.currentData(), self.source.currentData(), self.level.currentData(),
                            self.kind.currentText(), self.px.value(), out_dir, self.fmt.currentData(), self.dpi.currentData(),
                            self.ba.isChecked(),
                            dict(position=self.sb_pos.currentData(), style=self.sb_style.currentData(),
                                 length_um=self.sb_len.value() or None) if self.sbar.isChecked() else None)
            while not fut.done():
                QApplication.processEvents(); time.sleep(0.03)
        return fut.result()

    def show_table(self, df):
        self.tbl.setRowCount(len(df)); self.tbl.setColumnCount(len(df.columns))
        self.tbl.setHorizontalHeaderLabels([str(c) for c in df.columns])
        for i, (_, r) in enumerate(df.iterrows()):
            for j, v in enumerate(r.values):
                txt = f"{v:.3f}" if isinstance(v, float) else ("" if v is None else str(v))
                self.tbl.setItem(i, j, QTableWidgetItem(txt))
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

    def numeric_rows(self):
        if self.rows is None:
            return None
        df = self.rows.copy()
        keep = ["image", "group"] + [c for c in df.columns if c not in ("image", "group", "integrity", "error")
                                     and pd.api.types.is_numeric_dtype(df[c])]
        return df[keep]
