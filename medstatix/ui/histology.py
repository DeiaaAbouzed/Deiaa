"""Histology & IHC studio: integrity-safe enhancement, quantification, annotation and figure panels."""
from __future__ import annotations

import json
import math
import os

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QKeySequence,
                           QShortcut)
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGraphicsEllipseItem, QGraphicsItem, QGraphicsLineItem,
                               QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem,
                               QGraphicsView, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter,
                               QTextBrowser, QToolButton, QVBoxLayout, QWidget, QApplication)

from ..core.result import Result
from ..core.settings import SETTINGS
from ..imaging import core as IC

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "sample_images")

LABEL_PRESETS = ["Inflammatory cells", "Lymphocytic infiltrate", "Neutrophils", "Fibrosis", "Collagen deposition", "Congestion",
                 "Haemorrhage", "Necrosis", "Apoptotic body", "Vacuolation", "Fatty change (steatosis)", "Kupffer cell hyperplasia",
                 "Central vein", "Portal tract", "Bile duct proliferation", "Hyaline cast", "Glomerulus", "Degenerated tubule",
                 "Oedema", "Hyperplasia", "Mitotic figure", "Giant cell", "Granuloma", "Positive (DAB) cells", "Negative cells"]


def T(en, ar):
    return ar if SETTINGS.language == "ar" else en


def np_to_qimage(a: np.ndarray) -> QImage:
    a = np.ascontiguousarray(a)
    h, w, _ = a.shape
    return QImage(a.data, w, h, 3 * w, QImage.Format_RGB888).copy()


def qimage_to_np(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_RGB888)
    w, h = img.width(), img.height()
    ptr = img.constBits()
    arr = np.frombuffer(ptr, np.uint8, count=img.bytesPerLine() * h).reshape(h, img.bytesPerLine())
    return arr[:, :w * 3].reshape(h, w, 3).copy()


# ------------------------------------------------------------------ annotation items
class ArrowItem(QGraphicsPathItem):
    def __init__(self, p1: QPointF, p2: QPointF, color: QColor, width: float):
        super().__init__()
        self.p1, self.p2 = p1, p2
        self.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self.setBrush(QBrush(color))
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable)
        self.update_path(p2)

    def update_path(self, p2):
        self.p2 = p2
        path = QPainterPath(self.p1)
        path.lineTo(p2)
        ang = math.atan2(p2.y() - self.p1.y(), p2.x() - self.p1.x())
        L = max(10.0, self.pen().widthF() * 4.5)
        a1 = QPointF(p2.x() - L * math.cos(ang - 0.42), p2.y() - L * math.sin(ang - 0.42))
        a2 = QPointF(p2.x() - L * math.cos(ang + 0.42), p2.y() - L * math.sin(ang + 0.42))
        path.addPolygon(QPolygonF([p2, a1, a2, p2]))
        self.setPath(path)


class LabelItem(QGraphicsSimpleTextItem):
    def __init__(self, text, pos, color, size, box=True):
        super().__init__(text)
        f = QFont("Arial", int(size)); f.setBold(True)
        self.setFont(f)
        self.setBrush(QBrush(color))
        self.setPos(pos)
        self.box = box
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable)

    def paint(self, painter, option, widget=None):
        if self.box:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 200))
            painter.drawRoundedRect(self.boundingRect().adjusted(-4, -2, 4, 2), 3, 3)
        super().paint(painter, option, widget)


class HistoScene(QGraphicsScene):
    pass


class HistoView(QGraphicsView):
    status = Signal(str)

    def __init__(self):
        super().__init__()
        self.scene_ = HistoScene(self)
        self.setScene(self.scene_)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#2B2F36"))
        self.pix_item = QGraphicsPixmapItem()
        self.pix_item.setZValue(-10)
        self.scene_.addItem(self.pix_item)
        self.mode = "pan"
        self.color = QColor("#000000")
        self.width_ = 3.0
        self.font_size = 18
        self.label_text = "Inflammatory cells"
        self._tmp = None
        self._start = None
        self.overlay_items = []
        self.candidate_items = []

    def set_image(self, arr: np.ndarray, keep_view=False):
        self.pix_item.setPixmap(QPixmap.fromImage(np_to_qimage(arr)))
        self.scene_.setSceneRect(QRectF(0, 0, arr.shape[1], arr.shape[0]))
        if not keep_view:
            self.fitInView(self.pix_item, Qt.KeepAspectRatio)

    def wheelEvent(self, e):
        f = 1.18 if e.angleDelta().y() > 0 else 1 / 1.18
        self.scale(f, f)

    def set_mode(self, m):
        self.mode = m
        self.setDragMode(QGraphicsView.ScrollHandDrag if m == "pan" else (QGraphicsView.RubberBandDrag if m == "select" else QGraphicsView.NoDrag))

    def mousePressEvent(self, e):
        if self.mode in ("pan", "select") or e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        p = self.mapToScene(e.position().toPoint())
        self._start = p
        pen = QPen(self.color, self.width_)
        if self.mode == "arrow":
            self._tmp = ArrowItem(p, p, self.color, self.width_)
            self.scene_.addItem(self._tmp)
        elif self.mode in ("circle", "rect"):
            self._tmp = (QGraphicsEllipseItem if self.mode == "circle" else QGraphicsRectItem)(QRectF(p, p))
            self._tmp.setPen(pen)
            self._tmp.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable)
            self.scene_.addItem(self._tmp)
        elif self.mode == "label":
            it = LabelItem(self.label_text, p, self.color, self.font_size)
            self.scene_.addItem(it)
            self._tmp = None
        elif self.mode == "freehand":
            path = QPainterPath(p)
            self._tmp = QGraphicsPathItem(path)
            self._tmp.setPen(QPen(self.color, self.width_, Qt.DashLine, Qt.RoundCap, Qt.RoundJoin))
            self._tmp.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable)
            self.scene_.addItem(self._tmp)

    def mouseMoveEvent(self, e):
        if self._tmp is None or self._start is None:
            return super().mouseMoveEvent(e)
        p = self.mapToScene(e.position().toPoint())
        if isinstance(self._tmp, ArrowItem):
            self._tmp.update_path(p)
        elif isinstance(self._tmp, (QGraphicsEllipseItem, QGraphicsRectItem)):
            self._tmp.setRect(QRectF(self._start, p).normalized())
        elif isinstance(self._tmp, QGraphicsPathItem):
            path = self._tmp.path(); path.lineTo(p); self._tmp.setPath(path)

    def mouseReleaseEvent(self, e):
        if self._tmp is not None and isinstance(self._tmp, QGraphicsPathItem) and not isinstance(self._tmp, ArrowItem):
            path = self._tmp.path(); path.closeSubpath(); self._tmp.setPath(path)
        self._tmp = None
        self._start = None
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            for it in self.scene_.selectedItems():
                if it is not self.pix_item:
                    self.scene_.removeItem(it)
                    if it in self.candidate_items:
                        self.candidate_items.remove(it)
        else:
            super().keyPressEvent(e)

    def annotation_items(self):
        return [i for i in self.scene_.items() if i is not self.pix_item and i not in self.overlay_items and i.parentItem() is None]

    def clear_overlays(self):
        for it in self.overlay_items:
            if it.scene():
                self.scene_.removeItem(it)
        self.overlay_items = []

    def clear_candidates(self):
        for it in self.candidate_items:
            if it.scene():
                self.scene_.removeItem(it)
        self.candidate_items = []

    def render_image(self, include_overlays=True) -> np.ndarray:
        hidden = []
        if not include_overlays:
            for it in self.overlay_items:
                if it.isVisible():
                    it.hide(); hidden.append(it)
        for it in self.scene_.selectedItems():
            it.setSelected(False)
        r = self.scene_.sceneRect()
        img = QImage(int(r.width()), int(r.height()), QImage.Format_RGB888)
        img.fill(Qt.white)
        p = QPainter(img)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.scene_.render(p, QRectF(0, 0, r.width(), r.height()), r)
        p.end()
        for it in hidden:
            it.show()
        return qimage_to_np(img)


# ------------------------------------------------------------------ panel composer
class PanelComposer(QDialog):
    def __init__(self, parent, current_getter):
        super().__init__(parent)
        self.setWindowTitle(T("Figure panel composer (A, B, C…)", "تركيب لوحة الصور (A وB وC…)"))
        self.images = []
        self.current_getter = current_getter
        lay = QVBoxLayout(self)
        self.list = QListWidget(); self.list.setIconSize(QPixmap(120, 90).size()); lay.addWidget(self.list)
        row = QHBoxLayout()
        b1 = QPushButton(T("Add current (annotated) image", "إضافة الصورة الحالية بالوسوم")); b1.clicked.connect(self.add_current)
        b2 = QPushButton(T("Add image files…", "إضافة ملفات صور…")); b2.clicked.connect(self.add_files)
        b3 = QPushButton(T("Remove", "حذف")); b3.clicked.connect(self.remove)
        b4 = QPushButton("▲"); b4.clicked.connect(lambda: self.move(-1)); b5 = QPushButton("▼"); b5.clicked.connect(lambda: self.move(1))
        for b in (b1, b2, b3, b4, b5):
            row.addWidget(b)
        lay.addLayout(row)
        f = QFormLayout()
        self.cols = QSpinBox(); self.cols.setRange(1, 6); self.cols.setValue(2)
        self.lbls = QLineEdit(""); self.lbls.setPlaceholderText("A, B, C, D …")
        self.dpi = QComboBox(); self.dpi.addItems(["300", "600", "1200"]); self.dpi.setCurrentText("600")
        f.addRow(T("Columns", "عدد الأعمدة"), self.cols); f.addRow(T("Panel labels", "حروف اللوحات"), self.lbls); f.addRow("DPI", self.dpi)
        lay.addLayout(f)
        bb = QDialogButtonBox()
        ex = bb.addButton(T("Export panel figure…", "تصدير اللوحة…"), QDialogButtonBox.AcceptRole); ex.setObjectName("primary")
        bb.addButton(QDialogButtonBox.Close)
        bb.accepted.connect(self.export); bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(640, 520)

    def _add(self, arr, name):
        self.images.append(arr)
        it = QListWidgetItem(QPixmap.fromImage(np_to_qimage(arr)).scaled(120, 90, Qt.KeepAspectRatio), name)
        self.list.addItem(it)

    def add_current(self):
        arr = self.current_getter()
        if arr is not None:
            self._add(arr, f"Current #{len(self.images) + 1}")

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "", "", "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp)")
        for p in paths:
            self._add(IC.load_image(p), os.path.basename(p))

    def remove(self):
        r = self.list.currentRow()
        if r >= 0:
            self.list.takeItem(r); self.images.pop(r)

    def move(self, d):
        r = self.list.currentRow(); n = r + d
        if 0 <= r < len(self.images) and 0 <= n < len(self.images):
            self.images[r], self.images[n] = self.images[n], self.images[r]
            it = self.list.takeItem(r); self.list.insertItem(n, it); self.list.setCurrentRow(n)

    def export(self):
        if not self.images:
            return
        labels = [s.strip() for s in self.lbls.text().split(",") if s.strip()] or None
        fig = IC.compose_panels(self.images, ncols=self.cols.value(), labels=labels)
        path, _ = QFileDialog.getSaveFileName(self, "", "Figure_panel.tiff", "TIFF (*.tiff);;PNG (*.png);;JPEG (*.jpg)")
        if path:
            IC.save_image(fig, path, int(self.dpi.currentText()))
            QMessageBox.information(self, "", path)


# ------------------------------------------------------------------ main studio widget
class HistologyStudio(QWidget):
    send_result = Signal(object)        # Result → main output
    send_rows = Signal(object)          # DataFrame rows → dataset

    def __init__(self, parent=None):
        super().__init__(parent)
        self.original = None
        self.processed = None
        self.name = ""
        self.steps_done = []
        self.last_quant = None
        lay = QHBoxLayout(self); lay.setContentsMargins(4, 4, 4, 4)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._controls())
        center = QWidget(); cl = QVBoxLayout(center); cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self._annot_bar())
        self.view = HistoView()
        cl.addWidget(self.view, 1)
        self.info_lbl = QLabel(T("Open an image (or a sample) to begin.", "افتح صورة (أو صورة نموذجية) للبدء.")); self.info_lbl.setObjectName("hint")
        cl.addWidget(self.info_lbl)
        split.addWidget(center)
        self.report = QTextBrowser(); self.report.setMinimumWidth(300)
        split.addWidget(self.report)
        split.setSizes([330, 800, 330])
        lay.addWidget(split)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo_last_annotation)

    # ---------------- controls
    def _controls(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(2, 2, 2, 2)
        sc = QScrollArea(); sc.setWidgetResizable(True); inner = QWidget(); il = QVBoxLayout(inner)
        # image
        g = QGroupBox(T("1 · Image", "١ · الصورة")); f = QFormLayout(g)
        b = QPushButton(T("Open image…", "فتح صورة…")); b.setObjectName("primary"); b.clicked.connect(self.open_image); f.addRow(b)
        self.samples = QComboBox(); self.samples.addItem(T("— sample images —", "— صور نموذجية —"))
        if os.path.isdir(SAMPLE_DIR):
            for fn in sorted(os.listdir(SAMPLE_DIR)):
                if fn.lower().endswith((".png", ".jpg", ".tif")):
                    self.samples.addItem(fn)
        self.samples.currentIndexChanged.connect(self.open_sample); f.addRow(self.samples)
        self.px = QDoubleSpinBox(); self.px.setDecimals(4); self.px.setRange(0, 100); self.px.setValue(0.0); self.px.setSuffix(" µm/px")
        self.px.setToolTip(T("Calibration from your microscope/camera (e.g. 0.25 µm/px at 40×). 0 = uncalibrated.",
                             "معايرة من المجهر/الكاميرا (مثلًا 0.25 ميكرومتر/بكسل عند 40×). صفر = بدون معايرة."))
        f.addRow(T("Pixel size", "حجم البكسل"), self.px)
        self.show_orig = QCheckBox(T("Show original", "عرض الأصل")); self.show_orig.toggled.connect(self.refresh_view); f.addRow(self.show_orig)
        il.addWidget(g)
        # enhance
        g = QGroupBox(T("2 · Enhance (global, journal-safe)", "٢ · تحسين الجودة (كلي ومقبول في المجلات)")); f = QFormLayout(g)
        self.c_wb = QCheckBox(T("White balance", "توازن الأبيض")); f.addRow(self.c_wb)
        self.c_auto = QCheckBox(T("Auto contrast stretch", "تمديد تباين تلقائي")); f.addRow(self.c_auto)
        self.s_bright = self._slider(-25, 25, 0); f.addRow(T("Brightness", "الإضاءة"), self.s_bright)
        self.s_contrast = self._slider(60, 160, 100); f.addRow(T("Contrast", "التباين"), self.s_contrast)
        self.s_gamma = self._slider(60, 160, 100); f.addRow(T("Gamma", "جاما"), self.s_gamma)
        self.s_sat = self._slider(60, 150, 100); f.addRow(T("Saturation", "التشبع"), self.s_sat)
        self.norm = QComboBox(); self.norm.addItems([T("No stain normalization", "بدون توحيد صبغة"), "Reinhard (any stain)", "Macenko (H&E only)"])
        f.addRow(T("Stain", "الصبغة"), self.norm)
        self.s_denoise = self._slider(0, 100, 0); f.addRow(T("Denoise", "إزالة الضوضاء"), self.s_denoise)
        row = QHBoxLayout()
        ap = QPushButton(T("Apply", "تطبيق")); ap.setObjectName("primary"); ap.clicked.connect(self.apply_enhance)
        rs = QPushButton(T("Reset", "إعادة")); rs.clicked.connect(self.reset_enhance)
        row.addWidget(ap); row.addWidget(rs); f.addRow(row)
        il.addWidget(g)
        # quantify
        g = QGroupBox(T("3 · Quantify / detect", "٣ · القياس الكمي / الكشف")); f = QFormLayout(g)
        self.qtype = QComboBox()
        self.qtype.addItems(["IHC — DAB (H-score, % positive)", "Fibrosis — Masson trichrome", "Fibrosis — Sirius red",
                             "Fibrosis — Van Gieson", "H&E — inflammatory cell candidates", "H&E — congestion / RBC areas"])
        f.addRow(self.qtype)
        self.t1 = QDoubleSpinBox(); self.t1.setDecimals(3); self.t1.setRange(0, 2); self.t1.setValue(0.08); self.t1.setSingleStep(0.01)
        self.t2 = QDoubleSpinBox(); self.t2.setDecimals(3); self.t2.setRange(0, 2); self.t2.setValue(0.15); self.t2.setSingleStep(0.01)
        self.t3 = QDoubleSpinBox(); self.t3.setDecimals(3); self.t3.setRange(0, 2); self.t3.setValue(0.22); self.t3.setSingleStep(0.01)
        f.addRow(T("DAB weak ≥", "DAB ضعيف ≥"), self.t1); f.addRow(T("moderate ≥", "متوسط ≥"), self.t2); f.addRow(T("strong ≥", "قوي ≥"), self.t3)
        self.group_lbl = QLineEdit(); self.group_lbl.setPlaceholderText(T("Group (e.g. Control, Drug 10 mg/kg)", "المجموعة (مثل Control)"))
        f.addRow(T("Group", "المجموعة"), self.group_lbl)
        rq = QPushButton(T("Run", "تشغيل")); rq.setObjectName("primary"); rq.clicked.connect(self.run_quant); f.addRow(rq)
        self.c_overlay = QCheckBox(T("Show detection outlines", "إظهار حدود الكشف")); self.c_overlay.setChecked(True)
        self.c_overlay.toggled.connect(lambda on: [i.setVisible(on) for i in self.view.overlay_items]); f.addRow(self.c_overlay)
        row = QHBoxLayout()
        acc = QPushButton(T("Accept suggestions", "اعتماد الاقتراحات")); acc.clicked.connect(self.accept_candidates)
        rej = QPushButton(T("Discard", "تجاهل")); rej.clicked.connect(self.discard_detections)
        row.addWidget(acc); row.addWidget(rej); f.addRow(row)
        sd = QPushButton(T("Add measurements to dataset → statistics", "إضافة القياسات للبيانات ← الإحصاء")); sd.clicked.connect(self.add_to_dataset)
        f.addRow(sd)
        il.addWidget(g)
        # export
        g = QGroupBox(T("5 · Export", "٥ · التصدير")); f = QFormLayout(g)
        for txt, fn in [(T("Save processed image (no annotations)…", "حفظ الصورة المحسّنة (بدون وسوم)…"), self.save_processed),
                        (T("Save annotated figure…", "حفظ الصورة بالوسوم…"), self.save_annotated),
                        (T("Save edit log + Methods text…", "حفظ سجل التعديلات ونص الطرق…"), self.save_log),
                        (T("Send report to Results / Word", "إرسال التقرير إلى النتائج / Word"), self.send_report),
                        (T("Figure panel composer (A, B, C…)", "تركيب لوحة صور (A وB وC…)"), self.composer)]:
            bt = QPushButton(txt); bt.clicked.connect(fn); f.addRow(bt)
        il.addWidget(g)
        il.addStretch(1)
        sc.setWidget(inner); v.addWidget(sc)
        w.setMinimumWidth(320)
        return w

    def _slider(self, lo, hi, val):
        s = QSlider(Qt.Horizontal); s.setRange(lo, hi); s.setValue(val)
        return s

    def _annot_bar(self):
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0)
        grp = QButtonGroup(self)
        for key, txt in [("pan", "✋"), ("select", "⬚"), ("arrow", "➚"), ("label", "T"), ("circle", "◯"), ("rect", "▭"), ("freehand", "✎")]:
            b = QToolButton(); b.setText(txt); b.setCheckable(True); b.setMinimumWidth(34)
            b.setToolTip({"pan": T("Pan / zoom (wheel)", "تحريك / تكبير"), "select": T("Select (Delete to remove)", "تحديد (Delete للحذف)"),
                          "arrow": T("Arrow", "سهم"), "label": T("Text label", "تسمية نصية"), "circle": T("Circle", "دائرة"),
                          "rect": T("Rectangle", "مستطيل"), "freehand": T("Outline a region", "تحديد منطقة")}[key])
            b.clicked.connect(lambda _=False, k=key: self.view.set_mode(k))
            grp.addButton(b); h.addWidget(b)
            if key == "pan":
                b.setChecked(True)
        self.preset = QComboBox(); self.preset.setEditable(True); self.preset.addItems(LABEL_PRESETS); self.preset.setMinimumWidth(190)
        self.preset.currentTextChanged.connect(lambda t: setattr(self.view, "label_text", t))
        h.addWidget(self.preset)
        cb = QToolButton(); cb.setText("🎨"); cb.setToolTip(T("Colour", "اللون")); cb.clicked.connect(self.pick_color); h.addWidget(cb)
        self.lw = QSpinBox(); self.lw.setRange(1, 20); self.lw.setValue(3); self.lw.setPrefix("W ")
        self.lw.valueChanged.connect(lambda v: setattr(self.view, "width_", float(v))); h.addWidget(self.lw)
        self.fs = QSpinBox(); self.fs.setRange(6, 120); self.fs.setValue(18); self.fs.setPrefix("A ")
        self.fs.valueChanged.connect(lambda v: setattr(self.view, "font_size", v)); h.addWidget(self.fs)
        sb = QToolButton(); sb.setText("⟷ " + T("Scale bar", "مقياس الرسم")); sb.clicked.connect(self.add_scale_bar); h.addWidget(sb)
        cl = QToolButton(); cl.setText("🗑"); cl.setToolTip(T("Clear annotations", "مسح الوسوم")); cl.clicked.connect(self.clear_annotations); h.addWidget(cl)
        fit = QToolButton(); fit.setText("⤢"); fit.setToolTip(T("Fit", "ملاءمة")); fit.clicked.connect(lambda: self.view.fitInView(self.view.pix_item, Qt.KeepAspectRatio)); h.addWidget(fit)
        h.addStretch(1)
        return w

    # ---------------- image
    def load(self, arr, name):
        self.original = arr
        self.processed = arr.copy()
        self.name = name
        self.steps_done = []
        self.last_quant = None
        for it in list(self.view.annotation_items()):
            self.view.scene_.removeItem(it)
        self.view.clear_overlays(); self.view.candidate_items = []
        self.view.set_image(arr)
        self.info_lbl.setText(f"{name} — {arr.shape[1]}×{arr.shape[0]} px")
        self.report.setHtml(f"<h3>{name}</h3><p>{arr.shape[1]} × {arr.shape[0]} px</p>")

    def open_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "", "", "Images (*.tif *.tiff *.png *.jpg *.jpeg *.bmp)")
        if path:
            try:
                self.load(IC.load_image(path), os.path.basename(path))
            except Exception as e:
                QMessageBox.critical(self, "", str(e))

    def open_sample(self, i):
        if i > 0:
            fn = self.samples.itemText(i)
            self.load(IC.load_image(os.path.join(SAMPLE_DIR, fn)), fn)

    def refresh_view(self):
        if self.original is None:
            return
        self.view.set_image(self.original if self.show_orig.isChecked() else self.processed, keep_view=True)

    # ---------------- enhance
    def build_steps(self):
        st = []
        if self.c_wb.isChecked():
            st.append({"op": "white_balance"})
        if self.c_auto.isChecked():
            st.append({"op": "auto_levels"})
        b, c = self.s_bright.value() / 100, self.s_contrast.value() / 100
        if b != 0 or c != 1:
            st.append({"op": "levels", "params": {"brightness": b, "contrast": c}})
        if self.s_gamma.value() != 100:
            st.append({"op": "gamma", "params": {"gamma": self.s_gamma.value() / 100}})
        if self.s_sat.value() != 100:
            st.append({"op": "saturation", "params": {"factor": self.s_sat.value() / 100}})
        if self.norm.currentIndex() == 1:
            st.append({"op": "reinhard"})
        elif self.norm.currentIndex() == 2:
            st.append({"op": "macenko"})
        if self.s_denoise.value() > 0:
            st.append({"op": "denoise", "params": {"strength": self.s_denoise.value() / 100}})
        return st

    def apply_enhance(self):
        if self.original is None:
            return
        steps = self.build_steps()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.processed, self.steps_done = IC.apply_pipeline(self.original, steps)
            rep = IC.integrity_report(self.original, self.processed) if steps else None
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "", str(e)); return
        QApplication.restoreOverrideCursor()
        self.show_orig.setChecked(False)
        self.refresh_view()
        self.integrity = rep
        self.render_report()

    def reset_enhance(self):
        for s, v in [(self.s_bright, 0), (self.s_contrast, 100), (self.s_gamma, 100), (self.s_sat, 100), (self.s_denoise, 0)]:
            s.setValue(v)
        self.c_wb.setChecked(False); self.c_auto.setChecked(False); self.norm.setCurrentIndex(0)
        if self.original is not None:
            self.processed = self.original.copy(); self.steps_done = []; self.integrity = None
            self.refresh_view(); self.render_report()

    def render_report(self):
        log = IC.EditLog(self.name, self.steps_done)
        html = f"<h3>{self.name}</h3>"
        rep = getattr(self, "integrity", None)
        if rep:
            ok = rep["passed"]
            col = "#2E8B57" if ok else "#C0392B"
            html += (f"<table width='100%' cellpadding='6'><tr><td bgcolor='{col}' style='color:white'><b>"
                     f"{'✔ ' + T('Structure preserved — cell details unchanged', 'التفاصيل الخلوية محفوظة — لم يتغير أي تركيب') if ok else '⚠ ' + T('Structural change detected — revise settings', 'تم رصد تغيير في التركيب — راجع الإعدادات')}"
                     "</b></td></tr></table><table cellpadding='3'>")
            for k, v in rep.items():
                if k not in ("passed", "Verdict"):
                    html += f"<tr><td>{k}</td><td><b>{v}</b></td></tr>"
            html += "</table>"
            html += ("<p style='color:#5B6B82;font-size:11px'>" + T(
                "Structure is compared after removing global colour/intensity differences (rank-normalised SSIM, edge correlation, "
                "nuclear-mask Dice). The local-edit score fits the global colour mapping and measures clustered departures from it "
                "(cloning, painting or erasing cells score > 6).",
                "تتم المقارنة بعد إزالة فروق اللون والإضاءة الكلية. مؤشر التعديل الموضعي يكشف أي نسخ أو رسم أو مسح لخلايا (قيمة أكبر من 6).") + "</p>")
        if self.steps_done:
            html += "<h4>" + T("Edit log", "سجل التعديلات") + "</h4><ol>"
            for s in self.steps_done:
                html += f"<li>{s['name']}" + (f" — {json.dumps(s['params'])}" if s['params'] else "") + "</li>"
            html += "</ol>"
        html += "<h4>Methods</h4><p>" + log.methods_text() + "</p>"
        if self.last_quant:
            html += "<h4>" + T("Measurements", "القياسات") + "</h4><table cellpadding='3'>"
            for k, v in self.last_quant.items():
                html += f"<tr><td>{k}</td><td><b>{v:.3f}</b></td></tr>" if isinstance(v, float) else f"<tr><td>{k}</td><td><b>{v}</b></td></tr>"
            html += "</table>"
        self.report.setHtml(html)

    # ---------------- quantification
    def _add_contours(self, mask, color, width=1.5):
        for c in IC.outline_mask(mask):
            if len(c) < 6:
                continue
            path = QPainterPath(QPointF(c[0][1], c[0][0]))
            for y, x in c[1:]:
                path.lineTo(QPointF(x, y))
            it = QGraphicsPathItem(path); it.setPen(QPen(QColor(color), width)); it.setZValue(5)
            self.view.scene_.addItem(it); self.view.overlay_items.append(it)

    def run_quant(self):
        if self.original is None:
            return
        img = self.processed
        q = self.qtype.currentText()
        quant_note = None
        if any(st["op"] in ("reinhard", "macenko") for st in self.steps_done):
            # stain normalisation re-maps stain colours to a reference: fine for display, but measurements
            # must use the native stain colours (only white balance is kept)
            wb = [{"op": "white_balance"}] if any(st["op"] == "white_balance" for st in self.steps_done) else []
            img = IC.apply_pipeline(self.original, wb)[0] if wb else self.original
            quant_note = T("Measured on the native-colour image (stain normalisation is for display only).",
                           "تم القياس على الصورة بألوانها الأصلية (توحيد الصبغة للعرض فقط).")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.view.clear_overlays(); self.view.clear_candidates()
            px = self.px.value()
            if q.startswith("IHC"):
                res, masks, cells = IC.ihc_dab(img, self.t1.value(), self.t2.value(), self.t3.value())
                for k, col in [("weak", "#F1C40F"), ("moderate", "#E67E22"), ("strong", "#C0392B")]:
                    self._add_contours(masks[k], col, 1.2)
            elif q.startswith("Fibrosis"):
                stain = q.split("— ")[1]
                res, mask = IC.fibrosis_area(img, stain)
                self._add_contours(mask, "#00C853" if "Masson" not in stain else "#FFD600", 1.5)
                if px:
                    res["Collagen area (µm²)"] = res["Collagen area (px)"] * px ** 2
            elif "inflammatory" in q:
                cands = IC.inflammatory_candidates(img)
                for c in cands:
                    it = QGraphicsEllipseItem(c["x"] - c["r"], c["y"] - c["r"], 2 * c["r"], 2 * c["r"])
                    it.setPen(QPen(QColor("#00E5FF"), 2, Qt.DashLine))
                    it.setFlags(QGraphicsItem.ItemIsSelectable); it.setZValue(6)
                    it.setToolTip(T("Suggestion — select + Delete to reject", "اقتراح — حدده واضغط Delete للرفض"))
                    self.view.scene_.addItem(it); self.view.candidate_items.append(it)
                area_mm2 = img.shape[0] * img.shape[1] * (px / 1000) ** 2 if px else 0
                res = {"Candidate mononuclear inflammatory cells": len(cands)}
                if area_mm2:
                    res["Cells per mm²"] = len(cands) / area_mm2
                res["Note"] = T("Suggestions only: review each (select + Delete to reject), then Accept.",
                                "اقتراحات فقط: راجع كل خلية (حدد واضغط Delete للرفض) ثم اعتمد.")
            else:
                res, mask = IC.congestion_area(img)
                self._add_contours(mask, "#00E5FF", 1.5)
            self.c_overlay.setChecked(True)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "", str(e)); return
        QApplication.restoreOverrideCursor()
        if quant_note:
            res["Measured on"] = quant_note
        self.last_quant = res
        self.last_quant_type = q
        self.render_report()

    def accept_candidates(self):
        """Convert reviewed suggestions into permanent circle annotations and update the count."""
        n = len(self.view.candidate_items)
        for it in self.view.candidate_items:
            it.setPen(QPen(self.view.color if self.view.color != QColor("#000000") else QColor("#000000"), self.view.width_))
            it.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable)
        self.view.candidate_items = []
        if self.last_quant is not None and "Candidate mononuclear inflammatory cells" in self.last_quant:
            self.last_quant = {"Confirmed inflammatory cells": n, **({"Cells per mm²": n / (self.original.shape[0] * self.original.shape[1] * (self.px.value() / 1000) ** 2)} if self.px.value() else {})}
            self.render_report()

    def discard_detections(self):
        self.view.clear_overlays(); self.view.clear_candidates()

    def add_to_dataset(self):
        if not self.last_quant:
            return
        row = {"image": self.name, "group": self.group_lbl.text() or "", "analysis": getattr(self, "last_quant_type", "")}
        row.update({k: v for k, v in self.last_quant.items() if not isinstance(v, str)})
        self.send_rows.emit(pd.DataFrame([row]))

    # ---------------- annotations
    def pick_color(self):
        c = QColorDialog.getColor(self.view.color, self)
        if c.isValid():
            self.view.color = c

    def add_scale_bar(self):
        if self.original is None:
            return
        px = self.px.value()
        if px <= 0:
            QMessageBox.information(self, "", T("Enter the pixel size (µm/px) first — from your microscope calibration.",
                                                "أدخل حجم البكسل (ميكرومتر/بكسل) أولًا من معايرة المجهر."))
            return
        um, ok = QInputDialog.getDouble(self, T("Scale bar", "مقياس الرسم"), T("Length (µm)", "الطول (ميكرومتر)"), 50, 1, 5000, 0)
        if not ok:
            return
        L = um / px
        H, W = self.original.shape[:2]
        th = max(4, H / 120)
        x, y = W - L - W * 0.04, H - H * 0.06
        bar = QGraphicsRectItem(x, y, L, th); bar.setBrush(QBrush(self.view.color)); bar.setPen(QPen(Qt.NoPen))
        bar.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable)
        self.view.scene_.addItem(bar)
        lab = LabelItem(f"{um:g} µm", QPointF(x, y - self.view.font_size * 1.9), self.view.color, self.view.font_size, box=False)
        self.view.scene_.addItem(lab)
        lab.setPos(x + L / 2 - lab.boundingRect().width() / 2, y - lab.boundingRect().height() - 4)

    def clear_annotations(self):
        for it in list(self.view.annotation_items()):
            if it not in self.view.candidate_items:
                self.view.scene_.removeItem(it)

    def undo_last_annotation(self):
        items = [i for i in self.view.annotation_items() if i not in self.view.candidate_items]
        if items:
            self.view.scene_.removeItem(items[0])

    # ---------------- export
    def save_processed(self):
        if self.processed is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "", os.path.splitext(self.name)[0] + "_processed.tiff", "TIFF (*.tiff);;PNG (*.png)")
        if path:
            IC.save_image(self.processed, path, SETTINGS.export_dpi)

    def save_annotated(self):
        if self.processed is None:
            return
        self.show_orig.setChecked(False)
        path, _ = QFileDialog.getSaveFileName(self, "", os.path.splitext(self.name)[0] + "_annotated.tiff", "TIFF (*.tiff);;PNG (*.png);;JPEG (*.jpg)")
        if path:
            arr = self.view.render_image(include_overlays=self.c_overlay.isChecked())
            IC.save_image(arr, path, SETTINGS.export_dpi)

    def save_log(self):
        if self.original is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "", os.path.splitext(self.name)[0] + "_edit_log.json", "JSON (*.json)")
        if path:
            log = IC.EditLog(self.name, self.steps_done)
            data = json.loads(log.to_json())
            data["integrity"] = getattr(self, "integrity", None)
            data["methods_text"] = log.methods_text()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            with open(os.path.splitext(path)[0] + "_methods.txt", "w", encoding="utf-8") as f:
                f.write(log.methods_text())

    def send_report(self):
        if self.original is None:
            return
        from ..plots.figures import styled
        from matplotlib.figure import Figure
        res = Result("Histology image report", self.name)
        rep = getattr(self, "integrity", None)
        if self.steps_done:
            res.table(pd.DataFrame([{"Step": i + 1, "Operation": s["name"], "Parameters": json.dumps(s["params"]) if s["params"] else "—"} for i, s in enumerate(self.steps_done)]),
                      "Image processing log (global operations only)")
        if rep:
            res.table(pd.DataFrame([{"Metric": k, "Value": v} for k, v in rep.items() if k != "passed"]), "Image integrity check")
        if self.last_quant:
            res.table(pd.DataFrame([{"Measurement": k, "Value": v} for k, v in self.last_quant.items()]), "Quantification")
        with styled():
            fig = Figure(figsize=(9, 4.5))
            ax1, ax2 = fig.subplots(1, 2)
            ax1.imshow(self.original); ax1.set_title("Original"); ax1.axis("off")
            ax2.imshow(self.view.render_image(True) if self.view.annotation_items() or self.view.overlay_items else self.processed)
            ax2.set_title("Processed / annotated"); ax2.axis("off")
            fig.tight_layout()
        res.figure(fig, "Original and processed image (global adjustments only).")
        res.methods(IC.EditLog(self.name, self.steps_done).methods_text())
        self.send_result.emit(res)

    def composer(self):
        PanelComposer(self, lambda: self.view.render_image(self.c_overlay.isChecked()) if self.original is not None else None).exec()
