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


def run_busy(parent, text, fn):
    """Run fn() in a worker thread while showing a small busy dialog; returns fn's result (re-raises errors)."""
    import concurrent.futures, time
    from PySide6.QtWidgets import QProgressDialog
    dlg = QProgressDialog(text, None, 0, 0, parent)
    dlg.setWindowTitle("MedStatix Pro"); dlg.setWindowModality(Qt.WindowModal); dlg.setMinimumDuration(300)
    dlg.setCancelButton(None)
    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        fut = ex.submit(fn)
        while not fut.done():
            QApplication.processEvents()
            time.sleep(0.03)
    dlg.close()
    return fut.result()


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
        f.addRow(T("Columns", "عدد الأعمدة"), self.cols); f.addRow(T("Panel labels", "حروف اللوحات"), self.lbls)
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
        from .widgets import ExportOptionsDialog
        dlg = ExportOptionsDialog(self, allow_width=True, raster=True)
        if dlg.exec() != QDialog.Accepted:
            return
        ext, dpi, width_mm = dlg.values()
        path, _ = QFileDialog.getSaveFileName(self, "", f"Figure_panel.{ext}", f"{ext.upper()} (*.{ext})")
        if path:
            if not path.lower().endswith("." + ext):
                path += "." + ext
            IC.save_image(fig, path, dpi, width_mm)
            QMessageBox.information(self, "", path)


# ------------------------------------------------------------------ image quality control
STATUS_COL = {"ok": ("#E8F5E9", "#2E7D32"), "warn": ("#FFF4E5", "#B26A00"), "bad": ("#FDECEA", "#C62828"), "na": ("#F1F3F6", "#5B6B82")}
STATUS_TXT = {"ok": ("Good", "جيد"), "warn": ("Needs attention", "يحتاج انتباه"), "bad": ("Problem", "مشكلة"), "na": ("N/A", "غير متاح")}


def score_colour(sc):
    return "#2E7D32" if sc >= 85 else "#B26A00" if sc >= 65 else "#C62828"


def qc_html(before, after=None):
    A = SETTINGS.language == "ar"
    d = " dir='rtl'" if A else ""
    sb = before["score"]
    head = T("Image quality", "جودة الصورة")
    score = f"<span style='color:{score_colour(sb)};font-size:18px'><b>{sb}</b></span>/100"
    if after:
        sa = after["score"]
        score += f" &nbsp;→&nbsp; <span style='color:{score_colour(sa)};font-size:18px'><b>{sa}</b></span>/100"
    html = f"<div{d}><h4>{head}: {score}</h4><table cellpadding='3' cellspacing='0' width='100%'>"
    cur = after or before
    for c in cur["checks"]:
        if c["status"] == "na":
            continue
        bg, fg = STATUS_COL[c["status"]]
        nm = c["name_ar"] if A else c["name_en"]
        st = STATUS_TXT[c["status"]][1 if A else 0]
        html += f"<tr><td bgcolor='{bg}'>{nm}</td><td bgcolor='{bg}'>{c['value']}</td><td bgcolor='{bg}' style='color:{fg}'><b>{st}</b></td></tr>"
    html += "</table>"
    if after:
        html += "<p style='color:#5B6B82;font-size:11px'>" + T("Table shows the image after correction.", "الجدول يعرض حالة الصورة بعد التصحيح.") + "</p>"
    return html + "</div>"


class QCDialog(QDialog):
    """Shows the quality checks; the user ticks which suggested global corrections to apply."""

    def __init__(self, parent, qc):
        super().__init__(parent)
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
        A = SETTINGS.language == "ar"
        self.qc = qc
        self.show_areas = False
        self.setWindowTitle(T("Image inspection", "فحص الصورة"))
        self.resize(1040, 620)
        lay = QVBoxLayout(self)
        sc = qc["score"]
        top = QLabel(f"<span style='font-size:22px;color:{score_colour(sc)}'><b>{sc}/100</b></span> &nbsp; "
                     + T("Image quality score", "درجة جودة الصورة") + f" &nbsp;·&nbsp; {T('Stain', 'الصبغة')}: {qc.get('stain', '')}")
        lay.addWidget(top)
        hint = QLabel(T("Tick the corrections to apply. All are global (same operation on every pixel), recorded in the edit log, "
                        "and verified afterwards with the integrity check. Folds, debris, clipping and severe blur are flagged only: "
                        "they cannot be honestly corrected.",
                        "اختر التصحيحات المطلوبة. كلها تعديلات كلية (نفس العملية على كل بكسل) تُسجّل في سجل التعديلات ويُتحقق بعدها "
                        "من سلامة التركيب. الطيات والشوائب وقص الإضاءة والضبابية الشديدة يتم التنبيه عليها فقط لأنها لا تُصحح بأمانة."))
        hint.setWordWrap(True); hint.setObjectName("hint"); lay.addWidget(hint)
        rows = [c for c in qc["checks"] if c["status"] != "na"]
        self.tbl = QTableWidget(len(rows), 4)
        self.tbl.setHorizontalHeaderLabels([T("Check", "الفحص"), T("Value", "القيمة"), T("Status", "الحالة"),
                                            T("Finding / suggested correction", "النتيجة / التصحيح المقترح")])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setWordWrap(True)
        self.rows = rows
        for i, c in enumerate(rows):
            bg, fg = STATUS_COL[c["status"]]
            it = QTableWidgetItem(c["name_ar"] if A else c["name_en"])
            if c["fix"] is not None and c["status"] in ("warn", "bad"):
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if c["default_on"] else Qt.Unchecked)
            vals = [it, QTableWidgetItem(str(c["value"])), QTableWidgetItem(STATUS_TXT[c["status"]][1 if A else 0]),
                    QTableWidgetItem((c["detail_ar"] if A else c["detail_en"]) + self._fix_text(c))]
            for j, v in enumerate(vals):
                v.setBackground(QColor(bg))
                if j == 2:
                    v.setForeground(QColor(fg)); f = v.font(); f.setBold(True); v.setFont(f)
                self.tbl.setItem(i, j, v)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents); hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents); hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.tbl.resizeRowsToContents()
        lay.addWidget(self.tbl, 1)
        bb = QDialogButtonBox()
        ok = bb.addButton("✨ " + T("Apply selected corrections", "تطبيق التصحيحات المختارة"), QDialogButtonBox.AcceptRole); ok.setObjectName("primary")
        ar = bb.addButton("🟧 " + T("Show problem areas", "إظهار المناطق المشكلة"), QDialogButtonBox.ActionRole)
        ar.setEnabled(bool(qc.get("problem_mask") is not None and qc["problem_mask"].any()))
        ar.clicked.connect(self._areas)
        bb.addButton(T("Close", "إغلاق"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    @staticmethod
    def _fix_text(c):
        if c["fix"] is None or c["status"] not in ("warn", "bad"):
            return ""
        nm = IC.OPS[c["fix"]["op"]][1 if SETTINGS.language == "ar" else 0]
        p = c["fix"].get("params") or {}
        ps = ", ".join(f"{k} {v}" for k, v in p.items() if not (k == "strength" and v == 1.0))
        return "\n→ " + T("Fix: ", "التصحيح: ") + nm + (f" ({ps})" if ps else "")

    def _areas(self):
        self.show_areas = True
        self.reject()

    def selected_steps(self):
        steps = []
        for i, c in enumerate(self.rows):
            it = self.tbl.item(i, 0)
            if c["fix"] is not None and it.flags() & Qt.ItemIsUserCheckable and it.checkState() == Qt.Checked:
                steps.append(c["fix"])
        steps.sort(key=lambda s: IC.QC_ORDER.index(s["op"]) if s["op"] in IC.QC_ORDER else 99)
        return steps


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
        baw = QWidget(); baw.setLayoutDirection(Qt.LeftToRight); ba = QHBoxLayout(baw); ba.setContentsMargins(0, 0, 0, 0)
        ba.addWidget(QLabel(T("Before", "قبل")))
        self.ba = QSlider(Qt.Horizontal); self.ba.setRange(0, 100); self.ba.setValue(0); self.ba.setLayoutDirection(Qt.LeftToRight)
        self.ba.setToolTip(T("Drag to compare the original (left) with the processed image (right)",
                             "اسحب للمقارنة بين الأصل (يسار) والصورة المحسنة (يمين)"))
        self.ba.valueChanged.connect(self.refresh_view)
        ba.addWidget(self.ba, 1); ba.addWidget(QLabel(T("After", "بعد")))
        cl.addWidget(baw)
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
        self.show_orig = QCheckBox(T("Show original", "عرض الأصل")); self.show_orig.toggled.connect(self.refresh_view); self.show_orig.toggled.connect(self._sync_annot_on); f.addRow(self.show_orig)
        il.addWidget(g)
        # one-click publication-ready
        g = QGroupBox(T("2 · Publication-ready in one click", "٢ · تجهيز للنشر بضغطة واحدة")); f = QFormLayout(g)
        self.pr_stain = QComboBox(); self.pr_stain.addItem(T("Auto-detect", "تحديد تلقائي"), "auto")
        for k, pv in IC.STAIN_PRESETS.items():
            self.pr_stain.addItem(pv["ar"] if SETTINGS.language == "ar" else k, k)
        self.pr_source = QComboBox()
        for k, (en, ar) in IC.SOURCES.items():
            self.pr_source.addItem(T(en, ar), k)
        self.pr_level = QComboBox()
        for k, (_, en, ar) in IC.LEVELS.items():
            self.pr_level.addItem(T(en, ar), k)
        self.pr_level.setCurrentIndex(1)
        f.addRow(T("Stain", "الصبغة"), self.pr_stain); f.addRow(T("Taken with", "طريقة التصوير"), self.pr_source)
        f.addRow(T("Strength", "الدرجة"), self.pr_level)
        go = QPushButton("✨ " + T("Make publication-ready", "تجهيز الصورة للنشر")); go.setObjectName("primary"); go.setMinimumHeight(40)
        go.clicked.connect(self.publication_ready); f.addRow(go)
        self.pr_badge = QLabel(""); self.pr_badge.setWordWrap(True); f.addRow(self.pr_badge)
        il.addWidget(g)
        # manual / advanced
        g = QGroupBox(T("Advanced: inspect and adjust manually", "متقدم: فحص الصورة والتعديل اليدوي")); f = QFormLayout(g)
        g.setCheckable(True); g.setChecked(False)
        adv_inner = QWidget(); f2 = QFormLayout(adv_inner); f2.setContentsMargins(0, 0, 0, 0)
        g.toggled.connect(adv_inner.setVisible); adv_inner.setVisible(False); f.addRow(adv_inner)
        f = f2
        row = QHBoxLayout()
        qb = QPushButton("🔍 " + T("Inspect image", "فحص الصورة")); qb.setObjectName("primary"); qb.clicked.connect(self.inspect_image)
        qb.setToolTip(T("Detect blur, uneven illumination, colour cast, exposure, noise, faded stain and folds, and suggest fixes",
                        "يكشف الضبابية والإضاءة غير المتساوية والانحراف اللوني والتعريض والضوضاء وبهتان الصبغة والطيات ويقترح التصحيح"))
        ab = QPushButton("✨ " + T("Auto-enhance", "تحسين تلقائي")); ab.clicked.connect(self.auto_enhance)
        ab.setToolTip(T("Apply the suggested global corrections and verify that structure is unchanged",
                        "تطبيق التصحيحات الكلية المقترحة مع التحقق من عدم تغير التركيب"))
        row.addWidget(qb); row.addWidget(ab); f.addRow(row)
        self.c_crop = QCheckBox(T("Crop to the eyepiece field (phone photos)", "قص دائرة العدسة (صور الموبايل)")); f.addRow(self.c_crop)
        self.c_flat = QCheckBox(T("Correct uneven illumination (flat-field)", "تصحيح الإضاءة غير المتساوية (Flat-field)")); f.addRow(self.c_flat)
        self.c_bgw = QCheckBox(T("Whiten background (neutral white slide)", "تبييض الخلفية (خلفية بيضاء محايدة)")); f.addRow(self.c_bgw)
        self.c_haze = QCheckBox(T("Remove haze (black point)", "إزالة الضبابية (نقطة الأسود)")); f.addRow(self.c_haze)
        self.c_wb = QCheckBox(T("White balance", "توازن الأبيض")); f.addRow(self.c_wb)
        self.c_auto = QCheckBox(T("Auto contrast stretch", "تمديد تباين تلقائي")); f.addRow(self.c_auto)
        self.s_bright = self._slider(-25, 25, 0); f.addRow(T("Brightness", "الإضاءة"), self.s_bright)
        self.s_contrast = self._slider(60, 160, 100); f.addRow(T("Contrast", "التباين"), self.s_contrast)
        self.s_gamma = self._slider(60, 160, 100); f.addRow(T("Gamma", "جاما"), self.s_gamma)
        self.s_sat = self._slider(60, 150, 100); f.addRow(T("Saturation", "التشبع"), self.s_sat)
        self.norm = QComboBox(); self.norm.addItems([T("No stain normalization", "بدون توحيد صبغة"), "Reinhard (any stain)", "Macenko (H&E only)"])
        f.addRow(T("Stain", "الصبغة"), self.norm)
        self.s_denoise = self._slider(0, 100, 0); f.addRow(T("Denoise", "إزالة الضوضاء"), self.s_denoise)
        self.s_clahe = self._slider(0, 50, 0); f.addRow(T("Local contrast", "تباين موضعي"), self.s_clahe)
        self.s_sharpen = self._slider(0, 80, 0); f.addRow(T("Sharpen", "زيادة الحدة"), self.s_sharpen)
        self._sharpen_radius = 1.0
        self._extra = {}
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
        g = QGroupBox(T("4 · AI image reader", "٤ · قارئ الصورة بالذكاء الاصطناعي")); f = QFormLayout(g)
        hint = QLabel(T("A deep-learning model finds the nuclei, a second network types them (inflammatory, epithelial, "
                        "spindle) and the reader proposes labels: inflammatory cells and foci, congestion, vacuoles, DAB-positive "
                        "cells. Everything is a suggestion: delete wrong ones (select + Delete), then accept.",
                        "نموذج تعلّم عميق يحدد الأنوية، وشبكة ثانية تصنّفها (التهابية، طلائية، مغزلية)، ثم يقترح القارئ التسميات: "
                        "خلايا وبؤر التهابية، احتقان، فجوات، خلايا موجبة لـ DAB. كلها اقتراحات: احذف الخاطئ (تحديد ثم Delete) ثم اعتمد."))
        hint.setWordWrap(True); hint.setObjectName("hint"); f.addRow(hint)
        self.ai_profile = QComboBox()
        for lab, key in [(T("Rat / mouse kidney", "كلى فأر / جرذ"), "rodent kidney"),
                         (T("Other rodent tissue (muscle, liver…)", "نسيج قوارض آخر (عضلات، كبد…)"), "rodent"),
                         (T("Human / other (built-in model)", "بشري / آخر (النموذج الأصلي)"), "general")]:
            self.ai_profile.addItem(lab, key)
        self.ai_profile.setCurrentIndex(1)
        self.ai_profile.setToolTip(T("Rodent profiles add a calibrated inflammatory-cell filter trained on rat kidney and muscle, "
                                     "and (kidney) exclude glomerular nuclei.",
                                     "ملفات القوارض تضيف مرشّحًا معايَرًا للخلايا الالتهابية مدرَّبًا على كلى وعضلات الجرذ، "
                                     "وفي الكلى تستبعد أنوية الكبيبات."))
        f.addRow(T("Tissue", "النسيج"), self.ai_profile)
        self.ai_conf = QSpinBox(); self.ai_conf.setRange(30, 95); self.ai_conf.setValue(65); self.ai_conf.setSuffix(" %")
        self.ai_conf.setToolTip(T("Minimum confidence of a suggestion", "أقل درجة ثقة لعرض الاقتراح"))
        f.addRow(T("Minimum confidence", "أقل ثقة"), self.ai_conf)
        self.ai_types = QCheckBox(T("Also outline all nuclei by type", "تحديد كل الأنوية حسب نوعها أيضًا")); f.addRow(self.ai_types)
        self.ai_vac = QCheckBox(T("Look for vacuoles / fat droplets (experimental)", "البحث عن الفجوات / قطرات الدهون (تجريبي)")); f.addRow(self.ai_vac)
        rb = QPushButton("🤖 " + T("Read the image and suggest labels", "اقرأ الصورة واقترح التسميات")); rb.setObjectName("primary")
        rb.clicked.connect(self.ai_read); f.addRow(rb)
        self.ai_text = QLabel(""); self.ai_text.setWordWrap(True); self.ai_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        f.addRow(self.ai_text)
        row = QHBoxLayout()
        acc = QPushButton("✔ " + T("Accept (with labels)", "اعتماد مع التسميات")); acc.clicked.connect(self.ai_accept)
        rej = QPushButton("✖ " + T("Discard", "تجاهل")); rej.clicked.connect(self.discard_detections)
        row.addWidget(acc); row.addWidget(rej); f.addRow(row)
        rp = QPushButton(T("Add the reading to the results / Word", "إضافة القراءة إلى النتائج / Word")); rp.clicked.connect(self.ai_report)
        f.addRow(rp)
        tb = QPushButton("🎓 " + T("Teach the AI on my slides…", "علّم القارئ على شرائحي…")); tb.clicked.connect(self.ai_teach)
        tb.setToolTip(T("Label nuclei on your own tissue and fine-tune the cell-type classifier", "سمِّ الأنوية على نسيجك ودرّب مصنِّف أنواع الخلايا"))
        f.addRow(tb)
        il.addWidget(g)
        g = QGroupBox(T("5 · Export", "٥ · التصدير")); f = QFormLayout(g)
        self.annot_on = QComboBox()
        self.annot_on.addItem(T("Enhanced image", "الصورة المحسّنة"), "processed")
        self.annot_on.addItem(T("Original image (no enhancement)", "الصورة الأصلية (بدون تحسين)"), "original")
        self.annot_on.setToolTip(T("Which image the labels and arrows are drawn on when saving, in the report and in the panel composer",
                                   "الصورة التي تُرسم عليها الأسهم والتسميات عند الحفظ وفي التقرير ولوحة الصور"))
        self.annot_on.currentIndexChanged.connect(lambda i: self.show_orig.setChecked(self.annot_on.currentData() == "original"))
        f.addRow(T("Labels on", "الوسوم على"), self.annot_on)
        for txt, fn in [(T("Save processed image (no annotations)…", "حفظ الصورة المحسّنة (بدون وسوم)…"), self.save_processed),
                        (T("Save annotated figure…", "حفظ الصورة بالوسوم…"), self.save_annotated),
                        (T("Save before / after comparison…", "حفظ مقارنة قبل / بعد…"), self.save_before_after),
                        (T("Save edit log + Methods text…", "حفظ سجل التعديلات ونص الطرق…"), self.save_log),
                        (T("Send report to Results / Word", "إرسال التقرير إلى النتائج / Word"), self.send_report),
                        (T("Figure panel composer (A, B, C…)", "تركيب لوحة صور (A وB وC…)"), self.composer),
                        ("🖌 " + T("Open in Photopea (panels and text only)…", "فتح في Photopea (لوحات ونصوص فقط)…"), self.photopea_open),
                        ("🔎 " + T("Check image returned from Photopea…", "فحص الصورة العائدة من Photopea…"), self.photopea_check),
                        ("🧬 " + T("Duplicate / re-used image detector…", "كاشف الصور المكررة والمعاد استخدامها…"), self.duplicates),
                        ("📂 " + T("Batch: a whole folder → statistics…", "معالجة مجلد كامل ← الإحصاء…"), self.batch)]:
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
        self.qc_before = self.qc_after = None
        self.integrity = None
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

    @property
    def base(self):
        """The original image, cropped like the processed one (so the two can be compared pixel for pixel)."""
        crops = [s for s in (self.steps_done or []) if s["op"] == "crop"]
        if not crops or self.original is None:
            return self.original
        return IC.apply_pipeline(self.original, [{"op": "crop", "params": crops[0]["params"]}])[0]

    def _sync_annot_on(self, on):
        if hasattr(self, "annot_on"):
            i = self.annot_on.findData("original" if on else "processed")
            if i != self.annot_on.currentIndex():
                self.annot_on.blockSignals(True); self.annot_on.setCurrentIndex(i); self.annot_on.blockSignals(False)

    def refresh_view(self):
        if self.original is None:
            return
        if self.show_orig.isChecked():
            self.view.set_image(self.base, keep_view=True); return
        v = self.ba.value()
        if v > 0 and self.steps_done:
            base, pr = self.base, self.processed
            if base.shape == pr.shape:
                x = int(pr.shape[1] * v / 100)
                comp = pr.copy(); comp[:, :x] = base[:, :x]
                lw = max(2, pr.shape[1] // 400)
                comp[:, max(0, x - lw // 2):x + (lw + 1) // 2] = 255
                self.view.set_image(comp, keep_view=True); return
        self.view.set_image(self.processed, keep_view=True)

    # ---------------- enhance
    def build_steps(self):
        """Manual controls → pipeline, in the standard order (denoise first so later contrast changes do not amplify
        noise; sharpen last)."""
        st = []
        if self.c_crop.isChecked():
            box = self._extra.get("crop") or (IC.eyepiece_crop_box(self.original) if self.original is not None else None)
            if box:
                st.append({"op": "crop", "params": {"box": box}})
        if self.s_denoise.value() > 0:
            st.append({"op": "denoise", "params": {"strength": self.s_denoise.value() / 100}})
        if self.c_flat.isChecked():
            st.append({"op": "flatfield", "params": {"strength": 1.0}})
        if self.c_bgw.isChecked():
            st.append({"op": "background_white", "params": {"target": 0.955, "strength": 1.0}})
        if self.c_haze.isChecked():
            st.append({"op": "black_point", "params": self._extra.get("black_point", {"pct": 0.3, "target": 0.12, "max_slope": 2.5})})
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
        if self.s_clahe.value() > 0:
            st.append({"op": "clahe", "params": {"strength": self.s_clahe.value() / 100}})
            if self.c_bgw.isChecked():
                st.append({"op": "background_white", "params": {"target": 0.96, "strength": 1.0}})
        if self.s_sharpen.value() > 0:
            st.append({"op": "sharpen", "params": {"amount": self.s_sharpen.value() / 100, "radius": self._sharpen_radius}})
        return st

    def set_controls(self, steps):
        """Show a pipeline (e.g. the automatic suggestions) in the manual controls, so it can be fine-tuned."""
        self.reset_controls()
        for stp in steps:
            op, p = stp["op"], stp.get("params", {})
            if op == "crop":
                self.c_crop.setChecked(True); self._extra["crop"] = p.get("box")
            elif op == "background_white":
                self.c_bgw.setChecked(True)
            elif op == "black_point":
                self.c_haze.setChecked(True); self._extra["black_point"] = dict(p)
            elif op == "clahe":
                self.s_clahe.setValue(int(round(p.get("strength", 0.25) * 100)))
            elif op == "flatfield":
                self.c_flat.setChecked(True)
            elif op == "white_balance":
                self.c_wb.setChecked(True)
            elif op == "auto_levels":
                self.c_auto.setChecked(True)
            elif op == "levels":
                self.s_bright.setValue(int(round(p.get("brightness", 0) * 100))); self.s_contrast.setValue(int(round(p.get("contrast", 1) * 100)))
            elif op == "gamma":
                self.s_gamma.setValue(int(round(p.get("gamma", 1) * 100)))
            elif op == "saturation":
                self.s_sat.setValue(int(round(p.get("factor", 1) * 100)))
            elif op == "denoise":
                self.s_denoise.setValue(int(round(p.get("strength", 0.5) * 100)))
            elif op == "sharpen":
                self.s_sharpen.setValue(int(round(p.get("amount", 0.4) * 100))); self._sharpen_radius = float(p.get("radius", 1.0))
            elif op == "reinhard":
                self.norm.setCurrentIndex(1)
            elif op == "macenko":
                self.norm.setCurrentIndex(2)

    def reset_controls(self):
        for sl, v in [(self.s_bright, 0), (self.s_contrast, 100), (self.s_gamma, 100), (self.s_sat, 100), (self.s_denoise, 0),
                      (self.s_sharpen, 0), (self.s_clahe, 0)]:
            sl.setValue(v)
        for c in (self.c_wb, self.c_auto, self.c_flat, self.c_crop, self.c_bgw, self.c_haze):
            c.setChecked(False)
        self.norm.setCurrentIndex(0)
        self._sharpen_radius = 1.0
        self._extra = {}

    def _stain_kind(self):
        return "auto"

    def inspect_image(self):
        if self.original is None:
            QMessageBox.information(self, "", T("Open an image first.", "افتح صورة أولًا.")); return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            qc = IC.image_qc(self.base, self._stain_kind())
        finally:
            QApplication.restoreOverrideCursor()
        self.qc_before = qc
        dlg = QCDialog(self, qc)
        if dlg.exec() == QDialog.Accepted:
            steps = dlg.selected_steps()
            if dlg.show_areas:
                self.show_problem_areas(qc)
            if steps:
                self.set_controls(steps)
                self.apply_enhance()
            else:
                self.render_report()
        elif dlg.show_areas:
            self.show_problem_areas(qc)

    def show_problem_areas(self, qc):
        self.view.clear_overlays()
        m = qc.get("problem_mask")
        if m is not None and m.any():
            self._add_contours(m, QColor("#FF8C00"), 3)
            self.c_overlay.setChecked(True)

    def auto_enhance(self):
        if self.original is None:
            QMessageBox.information(self, "", T("Open an image first.", "افتح صورة أولًا.")); return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            qc = IC.image_qc(self.original, self._stain_kind())
            self.qc_before = qc
            out, done, rep, steps = IC.auto_enhance(self.original, qc["steps"])
        except Exception as e:
            QApplication.restoreOverrideCursor(); QMessageBox.critical(self, "", str(e)); return
        QApplication.restoreOverrideCursor()
        if not steps:
            QMessageBox.information(self, "", T(f"Quality score {qc['score']}/100: no global correction is needed.",
                                                f"درجة الجودة {qc['score']}/100: الصورة لا تحتاج تصحيحًا كليًا.")
                                    + self._unfixable_note(qc))
            self.render_report(); return
        self.set_controls(steps)
        self.apply_enhance()
        note = self._unfixable_note(self.qc_after or qc)
        if note:
            QMessageBox.information(self, "", note.strip())

    def _unfixable_note(self, qc):
        bad = [c for c in qc["checks"] if c["key"] in ("clipping", "artefacts", "focus") and c["status"] in ("warn", "bad")]
        if not bad:
            return ""
        return "\n\n" + T("Not correctable by honest global editing (re-acquire or choose another field):",
                           "لا يمكن تصحيحه بتعديل كلي أمين (أعد التصوير أو اختر حقلًا آخر):") + "\n" + "\n".join(
            "• " + (c["name_ar"] if SETTINGS.language == "ar" else c["name_en"]) for c in bad)

    def apply_enhance(self):
        if self.original is None:
            return
        steps = self.build_steps()
        orig = self.original

        def work():
            processed, done = IC.apply_pipeline(orig, steps)
            rep = IC.pipeline_integrity(orig, steps) if steps else None
            crops = [s_ for s_ in steps if s_["op"] == "crop"]
            base = IC.apply_pipeline(orig, crops)[0] if crops else orig
            qb = IC.image_qc(base)
            qa = IC.image_qc(processed) if steps else None
            return processed, done, rep, qb, qa
        try:
            self.processed, self.steps_done, rep, self.qc_before, self.qc_after = run_busy(
                self, T("Processing and verifying the image…", "جارٍ المعالجة والتحقق من سلامة الصورة…"), work)
        except Exception as e:
            QMessageBox.critical(self, "", str(e)); return
        self.marks_kept = 0
        self.show_orig.setChecked(False)
        self.integrity = rep
        self.ba.setValue(0)
        self.refresh_view()
        self.render_report()
        self._badge()

    def publication_ready(self):
        if self.original is None:
            QMessageBox.information(self, "", T("Open an image first.", "افتح صورة أولًا.")); return
        orig = self.original
        stain, source, level = self.pr_stain.currentData(), self.pr_source.currentData(), self.pr_level.currentData()

        def work():
            out, done, rep, steps, info = IC.publication_ready(orig, stain, source, level)
            crops = [s_ for s_ in steps if s_["op"] == "crop"]
            base = IC.apply_pipeline(orig, crops)[0] if crops else orig
            qs = "IHC" if info["stain"] == "IHC-DAB" else "H&E"
            return out, done, rep, steps, info, IC.image_qc(base, qs), IC.image_qc(out, qs)
        try:
            out, done, rep, steps, info, qb, qa = run_busy(
                self, T("Preparing the image for publication (enhance + integrity check)…",
                        "جارٍ تجهيز الصورة للنشر (تحسين + فحص السلامة)…"), work)
        except Exception as e:
            QMessageBox.critical(self, "", str(e)); return
        self.set_controls(steps)
        self.processed, self.steps_done, self.integrity, self.qc_before, self.qc_after = out, done, rep, qb, qa
        self.marks_kept = info.get("marks_kept_px", 0)
        self.show_orig.setChecked(False)
        self.ba.setValue(0)
        self.refresh_view(); self.render_report(); self._badge(info)

    def _badge(self, info=None):
        qb, qa, rep = self.qc_before, self.qc_after, self.integrity
        if not qb or not qa:
            self.pr_badge.setText(""); return
        ok = rep is None or rep.get("passed")
        txt = (f"<span style='font-size:15px'><b style='color:{score_colour(qb['score'])}'>{qb['score']}</b> → "
               f"<b style='color:{score_colour(qa['score'])}'>{qa['score']}</b>/100</span> &nbsp; "
               + ("<b style='color:#2E7D32'>✔ " + T("structure unchanged", "التركيب لم يتغير") + "</b>" if ok else
                  "<b style='color:#C62828'>⚠ " + T("check settings", "راجع الإعدادات") + "</b>"))
        if info:
            st = IC.STAIN_PRESETS[info["stain"]]["ar"] if SETTINGS.language == "ar" else info["stain"]
            txt += "<br><span style='color:#5B6B82'>" + T("Stain", "الصبغة") + f": {st}" + (
                " · " + T("eyepiece field cropped", "تم قص دائرة العدسة") if info.get("cropped") else "") + (
                " · " + T("drawn arrows / scale bar kept unchanged", "الأسهم ومقياس الرسم المرسومة بقيت كما هي")
                if info.get("marks_kept_px") else "") + "</span>"
        txt += "<br><span style='color:#5B6B82'>" + T("Drag the Before/After slider under the image to compare.",
                                                      "اسحب شريط قبل/بعد أسفل الصورة للمقارنة.") + "</span>"
        self.pr_badge.setText(txt)

    def reset_enhance(self):
        self.reset_controls()
        if self.original is not None:
            self.processed = self.original.copy(); self.steps_done = []; self.integrity = None; self.qc_after = None
            self.refresh_view(); self.render_report(); self.pr_badge.setText("")

    def render_report(self):
        log = IC.EditLog(self.name, self.steps_done, marks_kept=getattr(self, "marks_kept", 0) if self.steps_done else 0)
        html = f"<h3>{self.name}</h3>"
        qb, qa = getattr(self, "qc_before", None), getattr(self, "qc_after", None)
        if qb:
            html += qc_html(qb, qa)
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
                "(cloning, painting or erasing cells score > 6; > 10 when flat-field correction is used). With denoising or sharpening "
                "each filter is verified separately against its own input.",
                "تتم المقارنة بعد إزالة فروق اللون والإضاءة الكلية. مؤشر التعديل الموضعي يكشف أي نسخ أو رسم أو مسح لخلايا "
                "(قيمة أكبر من 6، أو 10 عند تصحيح الإضاءة). عند إزالة الضوضاء أو زيادة الحدة يُفحص كل مرشح على حدة.") + "</p>")
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
        if any(st["op"] not in IC.MEASURE_SAFE_OPS for st in self.steps_done):
            # cosmetic steps (levels, gamma, saturation, CLAHE, sharpening, stain normalisation) change optical
            # densities: measure on the native-colour image with only illumination / white-reference corrections
            img = IC.measurement_image(self.original, self.steps_done)
            quant_note = T("Measured on the native-colour image (illumination and white reference corrected only; "
                           "display adjustments are not used for measurement).",
                           "تم القياس على الصورة بألوانها الأصلية (بعد تصحيح الإضاءة والأبيض فقط؛ تعديلات العرض لا تدخل في القياس).")
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

    # ---------------- AI reader
    def _ai_stain(self):
        st = self.pr_stain.currentData() if hasattr(self, "pr_stain") else "auto"
        return "IHC" if st and str(st).startswith("IHC") else ("H&E" if st and st != "auto" else "auto")

    def _suggest(self, item, kind, conf, tip):
        item.setFlags(QGraphicsItem.ItemIsSelectable); item.setZValue(6)
        item.setData(0, kind); item.setData(1, float(conf))
        item.setToolTip(f"{tip} — {T('confidence', 'الثقة')} {conf * 100:.0f}% · " + T("select + Delete to reject", "حدده واضغط Delete للرفض"))
        self.view.scene_.addItem(item); self.view.candidate_items.append(item)

    def ai_read(self):
        from ..imaging import reader as RD
        if self.original is None:
            return
        img = IC.measurement_image(self.original, self.steps_done) if self.steps_done else self.original
        try:
            r = run_busy(self, T("Reading the image (AI)…", "جاري قراءة الصورة بالذكاء الاصطناعي…"),
                         lambda: RD.read_image(img, self.px.value(), self._ai_stain(), self.ai_conf.value() / 100, vacuoles=self.ai_vac.isChecked(),
                                                  profile=self.ai_profile.currentData()))
        except Exception as e:
            QMessageBox.critical(self, "", str(e)); return
        self.view.clear_overlays(); self.view.clear_candidates()
        self.ai = r
        H, W = img.shape[:2]
        lw = max(1.5, W / 700)
        if self.ai_types.isChecked():
            for c in r["cells"]:
                col = RD.COLOURS.get(c["type"], "#9E9E9E")
                path = QPainterPath(QPointF(c["poly"][0][1], c["poly"][0][0]))
                for y, x in c["poly"][1:]:
                    path.lineTo(QPointF(x, y))
                path.closeSubpath()
                it = QGraphicsPathItem(path); it.setPen(QPen(QColor(col), lw * 0.6)); it.setZValue(4)
                self.view.scene_.addItem(it); self.view.overlay_items.append(it)
        if r["stain"] == "IHC":
            cols = ["#2962FF", "#FFD600", "#FF6D00", "#D50000"]
            for c in r["cells"]:
                if c["grade"] == 0 and not self.ai_types.isChecked():
                    continue
                path = QPainterPath(QPointF(c["poly"][0][1], c["poly"][0][0]))
                for y, x in c["poly"][1:]:
                    path.lineTo(QPointF(x, y))
                path.closeSubpath()
                it = QGraphicsPathItem(path); it.setPen(QPen(QColor(cols[c["grade"]]), lw, Qt.DashLine))
                self._suggest(it, "dab%d" % c["grade"], c["det"], T(["Negative", "Weak +", "Moderate ++", "Strong +++"][c["grade"]],
                                                                     ["سالب", "ضعيف +", "متوسط ++", "قوي +++"][c["grade"]]))
        for c in r["inflammatory"]:
            rr = max(3.0, (c["area_px"] / math.pi) ** 0.5 * 1.6)
            it = QGraphicsEllipseItem(c["x"] - rr, c["y"] - rr, 2 * rr, 2 * rr)
            it.setPen(QPen(QColor(RD.COLOURS["inflammatory"]), lw, Qt.DashLine))
            self._suggest(it, "inflammatory", c["p"], T("Inflammatory cell", "خلية التهابية"))
        for fo in r["foci"]:
            if fo["hull"] is None:
                continue
            path = QPainterPath(QPointF(*fo["hull"][0]))
            for x, y in fo["hull"][1:]:
                path.lineTo(QPointF(x, y))
            path.closeSubpath()
            it = QGraphicsPathItem(path); it.setPen(QPen(QColor(RD.COLOURS["focus"]), lw * 1.5, Qt.DashLine))
            self._suggest(it, "focus", fo["conf"], T(f"Inflammatory infiltrate ({fo['n']} cells)", f"ارتشاح التهابي ({fo['n']} خلية)"))
        for cg in r["congestion"]:
            y0, x0 = cg["bbox"][:2]
            for cnt in cg["contours"]:
                if len(cnt) < 6:
                    continue
                path = QPainterPath(QPointF(x0 + cnt[0][1] - 1, y0 + cnt[0][0] - 1))
                for y, x in cnt[1:]:
                    path.lineTo(QPointF(x0 + x - 1, y0 + y - 1))
                it = QGraphicsPathItem(path); it.setPen(QPen(QColor(RD.COLOURS["congestion"]), lw, Qt.DashLine))
                self._suggest(it, "congestion", cg["conf"], T("Congestion (RBC-rich)", "احتقان (غني بكرات الدم الحمراء)"))
        for gl in r.get("glomeruli", []):
            cnt = gl.get("contour")
            if cnt is None or len(cnt) < 6:
                continue
            path = QPainterPath(QPointF(cnt[0][1], cnt[0][0]))
            for y, x in cnt[1:]:
                path.lineTo(QPointF(x, y))
            path.closeSubpath()
            it = QGraphicsPathItem(path); it.setPen(QPen(QColor(RD.COLOURS["glomerulus"]), lw, Qt.DashLine))
            self._suggest(it, "glomerulus", gl.get("conf", 0.8), T("Glomerulus", "كبيبة"))
        for v in r["vacuoles"]:
            it = QGraphicsEllipseItem(v["x"] - v["r"], v["y"] - v["r"], 2 * v["r"], 2 * v["r"])
            it.setPen(QPen(QColor(RD.COLOURS["vacuole"]), lw, Qt.DashLine))
            self._suggest(it, "vacuole", v["conf"], T("Vacuole", "فجوة"))
        self.c_overlay.setChecked(True)
        self.ai_text.setText(RD.describe(r, SETTINGS.language == "ar"))
        self.last_quant = {k: v for k, v in r["summary"].items()}
        self.last_quant_type = "AI image reader"
        self.render_report()

    def ai_teach(self):
        from .teach_ui import TeachDialog
        if self.original is None:
            return
        r = getattr(self, "ai", None)
        if r is None or r.get("X") is None:
            self.ai_read(); r = getattr(self, "ai", None)
            if r is None:
                return
        img = IC.measurement_image(self.original, self.steps_done) if self.steps_done else self.original
        TeachDialog(self, img, r, self.name, np_to_qimage).exec()

    def ai_accept(self):
        """Keep the reviewed suggestions as ordinary annotations, add one label per finding, and recount."""
        from ..imaging import reader as RD
        r = getattr(self, "ai", None)
        items = [it for it in self.view.candidate_items if it.scene()]
        if r is None or not items:
            self.accept_candidates(); return
        W = self.processed.shape[1]
        fs = max(10, int(W / 45))
        kinds = {}
        for it in items:
            kinds.setdefault(it.data(0), []).append(it)
            pen = it.pen(); pen.setStyle(Qt.SolidLine); it.setPen(pen)
            it.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable)
        self.view.candidate_items = []
        black = QColor("#000000")
        labels = {"inflammatory": "Inflammatory cells", "focus": "Inflammatory infiltrate", "congestion": "Congestion",
                  "vacuole": "Vacuolation", "glomerulus": "Glomerulus", "dab3": "Strong positive (DAB)", "dab2": "Moderate positive", "dab1": "Weak positive"}
        H = self.processed.shape[0]
        placed = []
        order = ["focus", "inflammatory", "congestion", "vacuole", "glomerulus", "dab3", "dab2", "dab1"]
        for kind in [k for k in order if k in kinds]:
            its = kinds[kind]
            if kind == "focus":
                targets = sorted(its, key=lambda i: -i.sceneBoundingRect().width() * i.sceneBoundingRect().height())[:3]
            elif kind == "congestion":
                targets = [max(its, key=lambda i: i.sceneBoundingRect().width() * i.sceneBoundingRect().height())]
            else:   # one label pointing at the densest group of cells of this kind
                targets = [max(its, key=lambda i: sum(1 for j in its if (j.sceneBoundingRect().center() - i.sceneBoundingRect().center()).manhattanLength() < W / 8))]
            for t in targets:
                tip = t.sceneBoundingRect().center()
                lab = LabelItem(labels[kind], QPointF(0, 0), black, fs)
                bw, bh = lab.boundingRect().width(), lab.boundingRect().height()
                # place the label toward the image centre, inside the frame, without overlapping earlier labels
                dx = 1.0 if tip.x() < W * 0.6 else -1.0
                dy = -1.0 if tip.y() > H * 0.3 else 1.0
                nrm = 2 ** 0.5
                L = 0.13 * max(W, H)
                end = QPointF(tip.x() + dx / nrm * L, tip.y() + dy / nrm * L)
                pos = QPointF(min(max(4, end.x() - bw / 2), W - bw - 4), min(max(4, end.y() - bh / 2), H - bh - 4))
                for _ in range(12):
                    box = QRectF(pos, lab.boundingRect().size()).adjusted(-6, -4, 6, 4)
                    if not any(box.intersects(q) for q in placed):
                        break
                    pos = QPointF(pos.x(), min(H - bh - 4, pos.y() + bh * 1.3) if pos.y() + bh * 1.3 < H - bh else max(4, pos.y() - bh * 2.6))
                placed.append(QRectF(pos, lab.boundingRect().size()))
                lab.setPos(pos); self.view.scene_.addItem(lab)
                anchor = QPointF(pos.x() + bw / 2, pos.y() + (bh if pos.y() < tip.y() else 0))
                self.view.scene_.addItem(ArrowItem(anchor, tip, black, max(2.0, W / 450)))
        n = {k: len(v) for k, v in kinds.items()}
        q = {"Confirmed inflammatory cells": n.get("inflammatory", 0), "Confirmed inflammatory foci": n.get("focus", 0),
             "Confirmed congestion areas": n.get("congestion", 0), "Confirmed vacuoles": n.get("vacuole", 0)}
        if r["stain"] == "IHC":
            g = [int(k[3]) for k, v in kinds.items() if k.startswith("dab") for _ in v]
            tot = len(r["cells"])
            pos = sum(1 for x in g if x > 0)
            q = {"Nuclei": tot, "Confirmed positive nuclei": pos, "Positive nuclei %": 100 * pos / max(tot, 1),
                 "Cell H-score (0–300)": 100 * sum(g) / max(tot, 1)}
        else:
            q = {k: v for k, v in q.items() if v or k == "Confirmed inflammatory cells"}
            q["Nuclei"] = len(r["cells"])
            q["Inflammatory cells % of nuclei"] = 100 * n.get("inflammatory", 0) / max(len(r["cells"]), 1)
            if self.px.value():
                q["Inflammatory cells per mm²"] = n.get("inflammatory", 0) / max(r["summary"].get("Tissue area (mm²)", 0), 1e-9)
        self.last_quant = q; self.last_quant_type = "AI image reader (confirmed)"
        self.render_report()

    def ai_report(self):
        from ..imaging import reader as RD
        r = getattr(self, "ai", None)
        if r is None:
            QMessageBox.information(self, "", T("Read the image first.", "اقرأ الصورة أولًا.")); return
        from ..plots.figures import styled
        from matplotlib.figure import Figure
        res = Result(T("AI image reading: ", "قراءة الصورة بالذكاء الاصطناعي: ") + self.name)
        res.text(RD.describe(r, False) + ("\n\n" + RD.describe(r, True) if SETTINGS.language == "ar" else ""))
        rows = [{"Measure": k, "Value": v} for k, v in (self.last_quant or r["summary"]).items()]
        res.table(pd.DataFrame(rows), "AI-assisted image reading (suggestions reviewed by the investigator)")
        with styled():
            fig = Figure(figsize=(9, 4.5)); ax1, ax2 = fig.subplots(1, 2)
            ax1.imshow(self.base); ax1.set_title("Original"); ax1.axis("off")
            ax2.imshow(self.render_annotated(True)); ax2.set_title("Labels"); ax2.axis("off"); fig.tight_layout()
        res.figure(fig, "Image with the confirmed labels.")
        from ..imaging import nuclei as NUm, cellclass as CCm
        res.methods(r["methods"] + " References: " + NUm.CITATION + " " + CCm.CITATION)
        self.send_result.emit(res)

    def accept_candidates(self):
        """Convert reviewed suggestions into permanent circle annotations and update the count."""
        n = len(self.view.candidate_items)
        for it in self.view.candidate_items:
            it.setPen(QPen(self.view.color if self.view.color != QColor("#000000") else QColor("#000000"), self.view.width_))
            it.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable)
        self.view.candidate_items = []
        if self.last_quant is not None and "Candidate mononuclear inflammatory cells" in self.last_quant:
            self.last_quant = {"Confirmed inflammatory cells": n, **({"Cells per mm²": n / (self.processed.shape[0] * self.processed.shape[1] * (self.px.value() / 1000) ** 2)} if self.px.value() else {})}
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
        H, W = self.processed.shape[:2]
        raw = W * 0.18 * px
        nice = min([1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000], key=lambda v: abs(v - raw))
        um, ok = QInputDialog.getDouble(self, T("Scale bar", "مقياس الرسم"), T("Length (µm)", "الطول (ميكرومتر)"), nice, 1, 5000, 0)
        if not ok:
            return
        L = um / px
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
    def _ask_export(self, default_name, arr_getter):
        from .widgets import ExportOptionsDialog
        dlg = ExportOptionsDialog(self, allow_width=True, raster=True)
        if dlg.exec() != QDialog.Accepted:
            return
        ext, dpi, width_mm = dlg.values()
        flt = {"tiff": "TIFF (*.tiff *.tif)", "png": "PNG (*.png)", "jpg": "JPEG (*.jpg)", "pdf": "PDF (*.pdf)",
               "svg": "SVG (*.svg)", "eps": "EPS (*.eps)"}[ext]
        path, _ = QFileDialog.getSaveFileName(self, "", f"{default_name}.{ext}", flt)
        if path:
            if not path.lower().endswith("." + ext) and not (ext == "tiff" and path.lower().endswith(".tif")):
                path += "." + ext
            try:
                IC.save_image(arr_getter(), path, dpi, width_mm)
            except Exception as e:
                QMessageBox.critical(self, "", str(e)); return
            QMessageBox.information(self, "", T("Saved:", "تم الحفظ:") + f"\n{path}\n{dpi} dpi")

    def save_processed(self):
        if self.processed is None:
            return
        self._ask_export(os.path.splitext(self.name)[0] + "_processed", lambda: self.processed)

    def render_annotated(self, include_overlays=True, which=None):
        """Labels/arrows drawn on the chosen image (original or enhanced, never the before/after split view)."""
        if self.original is None:
            return None
        which = which or self.annot_on.currentData()
        self.view.set_image(self.base if which == "original" else self.processed, keep_view=True)
        try:
            return self.view.render_image(include_overlays=include_overlays)
        finally:
            self.refresh_view()

    def save_annotated(self):
        if self.processed is None:
            return
        suffix = "_annotated_original" if self.annot_on.currentData() == "original" else "_annotated"
        self._ask_export(os.path.splitext(self.name)[0] + suffix,
                         lambda: self.render_annotated(self.c_overlay.isChecked()))

    def save_before_after(self):
        if self.processed is None:
            return
        self._ask_export(os.path.splitext(self.name)[0] + "_before_after",
                         lambda: IC.compose_panels([self.base, self.processed], ncols=2,
                                                   labels=[T("A  Original", "A  Original"), "B  Processed"]))

    def save_log(self):
        if self.original is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "", os.path.splitext(self.name)[0] + "_edit_log.json", "JSON (*.json)")
        if path:
            log = IC.EditLog(self.name, self.steps_done, marks_kept=getattr(self, "marks_kept", 0) if self.steps_done else 0)
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
        qb, qa = getattr(self, "qc_before", None), getattr(self, "qc_after", None)
        if qb:
            rows = []
            for c in qb["checks"]:
                if c["status"] == "na":
                    continue
                r = {"Check": c["name_en"], "Before": f"{c['value']} ({c['status']})"}
                if qa:
                    ca = next((x for x in qa["checks"] if x["key"] == c["key"]), None)
                    r["After"] = f"{ca['value']} ({ca['status']})" if ca else "—"
                rows.append(r)
            rows.append({"Check": "Overall quality score (0–100)", "Before": str(qb["score"]), **({"After": str(qa["score"])} if qa else {})})
            res.table(pd.DataFrame(rows), "Image quality control (automatic inspection)")
        if rep:
            res.table(pd.DataFrame([{"Metric": k, "Value": v} for k, v in rep.items() if k != "passed"]), "Image integrity check")
        if self.last_quant:
            res.table(pd.DataFrame([{"Measurement": k, "Value": v} for k, v in self.last_quant.items()]), "Quantification")
        with styled():
            fig = Figure(figsize=(9, 4.5))
            ax1, ax2 = fig.subplots(1, 2)
            ax1.imshow(self.base); ax1.set_title("Original"); ax1.axis("off")
            ax2.imshow(self.render_annotated(True, "processed") if self.view.annotation_items() or self.view.overlay_items else self.processed)
            ax2.set_title("Processed / annotated"); ax2.axis("off")
            fig.tight_layout()
        res.figure(fig, "Original and processed image (global adjustments only).")
        res.methods(IC.EditLog(self.name, self.steps_done, marks_kept=getattr(self, "marks_kept", 0) if self.steps_done else 0).methods_text())
        self.send_result.emit(res)

    def batch(self):
        from .histobatch import BatchDialog
        dlg = BatchDialog(self)
        dlg.px.setValue(self.px.value())
        if dlg.exec() == QDialog.Accepted:
            rows = dlg.numeric_rows()
            if rows is not None and len(rows):
                self.send_rows.emit(rows)

    def _photopea_source(self):
        return self.base if self.annot_on.currentData() == "original" else self.processed

    def photopea_open(self):
        if self.processed is None:
            return
        from PySide6.QtCore import QStandardPaths, QUrl
        from PySide6.QtGui import QDesktopServices
        from .forensics_ui import PHOTOPEA_WARNING_EN, PHOTOPEA_WARNING_AR
        arr = self._photopea_source()
        d = os.path.join(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or os.path.expanduser("~"),
                         "MedStatix", "Photopea")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, os.path.splitext(self.name)[0] + "_for_photopea.png")
        IC.save_image(arr, path, 300)
        self._pp_sent = arr.copy()
        QApplication.clipboard().setImage(np_to_qimage(arr))
        QMessageBox.warning(self, "Photopea", T(PHOTOPEA_WARNING_EN, PHOTOPEA_WARNING_AR).format(path=path))
        QDesktopServices.openUrl(QUrl("https://www.photopea.com"))

    def photopea_check(self):
        if self.processed is None:
            return
        from ..imaging import forensics as FO
        sent = getattr(self, "_pp_sent", None)
        if sent is None:
            sent = self._photopea_source()
        path, _ = QFileDialog.getOpenFileName(self, T("Figure exported from Photopea", "اللوحة المصدَّرة من Photopea"), "",
                                              "Images (*.png *.tif *.tiff *.jpg *.jpeg *.bmp)")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            r = FO.external_edit_check(sent, IC.load_image(path))
        except Exception as e:
            QApplication.restoreOverrideCursor(); QMessageBox.critical(self, "", str(e)); return
        QApplication.restoreOverrideCursor()
        verdict = T(r["verdict"], r["verdict_ar"])
        if not r["found"]:
            QMessageBox.warning(self, "Photopea", verdict); return
        res = Result("Photopea round-trip integrity check", os.path.basename(path))
        res.table(pd.DataFrame([
            {"Metric": "Image located in figure (normalised cross-correlation)", "Value": r["match"]},
            {"Metric": "Panel position (x, y, width, height px)", "Value": f"{r['box'][1]}, {r['box'][0]}, {r['box'][3]}, {r['box'][2]}"},
            {"Metric": "Added marks (labels, arrows, lines)", "Value": r["marks"]},
            {"Metric": "Local tissue changes (regions)", "Value": r["tissue_regions"]},
            {"Metric": "Area changed in tissue (%)", "Value": r["tissue_pct"]},
            {"Metric": "Verdict", "Value": r["verdict"]}]), "Comparison of the returned figure with the image sent to Photopea")
        from matplotlib.figure import Figure
        fig = Figure(figsize=(9, 4.5)); a1, a2 = fig.subplots(1, 2)
        a1.imshow(r["panel"]); a1.set_title("Returned panel"); a1.axis("off")
        a2.imshow(FO.overlay_flags(r["panel"], r["tissue_flag"]) if r["tissue_regions"] else FO.overlay_flags(r["panel"], r["flag"], (0, 160, 255)))
        a2.set_title("Tissue changes (red)" if r["tissue_regions"] else "Added marks (blue)"); a2.axis("off")
        fig.tight_layout()
        res.figure(fig, "Flagged areas in the returned panel.")
        res.interpret(r["verdict"], r["verdict_ar"])
        self.send_result.emit(res)
        (QMessageBox.information if not r["tissue_regions"] else QMessageBox.warning)(self, "Photopea", verdict)

    def duplicates(self):
        from .forensics_ui import DuplicateDialog
        DuplicateDialog(self, self.send_result.emit).exec()

    def composer(self):
        PanelComposer(self, lambda: self.render_annotated(self.c_overlay.isChecked())).exec()
