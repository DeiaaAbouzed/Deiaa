"""Teach the AI reader: label nuclei on your own slides and fine-tune the nucleus-type classifier."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QGraphicsPathItem, QGraphicsScene, QGraphicsView,
                               QHBoxLayout, QLabel, QMessageBox, QProgressDialog, QPushButton, QRadioButton, QVBoxLayout)

from ..core.settings import SETTINGS
from ..imaging import training as TR
from ..imaging import cellclass as CC


def T(en, ar):
    return ar if SETTINGS.language == "ar" else en


CLASS_UI = [("inflammatory", "Inflammatory", "التهابية", "#E53935"), ("epithelial", "Epithelial / parenchymal", "طلائية / برنشيمية", "#1E88E5"),
            ("spindle", "Spindle (fibroblast, endothelial, muscle)", "مغزلية (ليفية، بطانية، عضلية)", "#43A047"),
            ("other", "Other", "أخرى", "#8E24AA")]


class _View(QGraphicsView):
    def __init__(self, dlg):
        super().__init__()
        self.dlg = dlg
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    def wheelEvent(self, e):
        f = 1.25 if e.angleDelta().y() > 0 else 0.8
        self.scale(f, f)

    def mousePressEvent(self, e):
        p = self.mapToScene(e.position().toPoint())
        if e.button() in (Qt.LeftButton, Qt.RightButton):
            self.dlg.click(p.x(), p.y(), remove=e.button() == Qt.RightButton)
        else:
            super().mousePressEvent(e)


class TeachDialog(QDialog):
    def __init__(self, parent, img, reading, image_name, qimage_fn):
        super().__init__(parent)
        self.r, self.name = reading, image_name
        self.cells = reading["cells"]
        self.X = reading.get("X")
        self.labels = {}
        self.items = {}
        self.setWindowTitle(T("Teach the AI reader on your slides", "تعليم قارئ الصور على شرائحك"))
        lay = QVBoxLayout(self)
        hint = QLabel(T("Choose a cell type, then click on nuclei of that type (right-click removes a label). Label 20–50 nuclei of "
                        "each type per image, on 10–20 images of your tissue. Labels are kept only on this computer.",
                        "اختر نوع الخلية ثم اضغط على الأنوية من هذا النوع (الزر الأيمن يزيل التسمية). سمِّ 20–50 نواة من كل نوع في "
                        "كل صورة، على 10–20 صورة من نسيجك. التسميات تُحفظ على جهازك فقط."))
        hint.setWordWrap(True); hint.setObjectName("hint"); lay.addWidget(hint)
        row = QHBoxLayout()
        self.grp = QButtonGroup(self)
        for i, (key, en, ar, col) in enumerate(CLASS_UI):
            rb = QRadioButton(T(en, ar)); rb.setStyleSheet(f"color:{col}; font-weight:600;")
            self.grp.addButton(rb, i); row.addWidget(rb)
            if i == 0:
                rb.setChecked(True)
        row.addStretch(1)
        lay.addLayout(row)
        self.scene = QGraphicsScene(self)
        self.scene.addPixmap(QPixmap.fromImage(qimage_fn(img)))
        pen = QPen(QColor(255, 255, 255, 150), max(1.0, img.shape[1] / 1400))
        for i, c in enumerate(self.cells):
            it = QGraphicsPathItem(self._path(c)); it.setPen(pen); self.scene.addItem(it); self.items[i] = it
        self.view = _View(self); self.view.setScene(self.scene)
        lay.addWidget(self.view, 1)
        self.count = QLabel(); lay.addWidget(self.count)
        self.store = QLabel(); self.store.setObjectName("hint"); lay.addWidget(self.store)
        row = QHBoxLayout()
        for txt, fn in [(T("Save labels of this image", "حفظ تسميات هذه الصورة"), self.save),
                        (T("Train the model now", "درّب النموذج الآن"), self.train),
                        (T("Back to the built-in model", "العودة للنموذج الأصلي"), self.reset)]:
            b = QPushButton(txt); b.clicked.connect(fn); row.addWidget(b)
        row.addStretch(1)
        close = QPushButton(T("Close", "إغلاق")); close.clicked.connect(self.accept); row.addWidget(close)
        lay.addLayout(row)
        self._refresh()
        self.resize(1150, 850)
        self.view.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)

    @staticmethod
    def _path(c):
        path = QPainterPath(QPointF(c["poly"][0][1], c["poly"][0][0]))
        for y, x in c["poly"][1:]:
            path.lineTo(QPointF(x, y))
        path.closeSubpath()
        return path

    def click(self, x, y, remove=False):
        if not self.cells:
            return
        pts = np.array([[c["x"], c["y"]] for c in self.cells])
        d = np.hypot(pts[:, 0] - x, pts[:, 1] - y)
        i = int(d.argmin())
        rad = max(6.0, (self.cells[i]["area_px"] / np.pi) ** 0.5 * 1.5)
        if d[i] > rad:
            return
        it = self.items[i]
        if remove:
            self.labels.pop(i, None)
            it.setPen(QPen(QColor(255, 255, 255, 150), it.pen().widthF())); it.setBrush(QBrush(Qt.NoBrush))
        else:
            k = self.grp.checkedId()
            self.labels[i] = CLASS_UI[k][0]
            col = QColor(CLASS_UI[k][3])
            it.setPen(QPen(col, it.pen().widthF() * 1.0 + 1)); col.setAlpha(70); it.setBrush(QBrush(col))
        self._refresh()

    def _refresh(self):
        n = {k: sum(v == k for v in self.labels.values()) for k, *_ in CLASS_UI}
        self.count.setText(T("This image: ", "هذه الصورة: ") + " · ".join(f"{T(en, ar)} {n[k]}" for k, en, ar, _ in CLASS_UI))
        s = TR.summary()
        self.store.setText(T(f"Saved so far: {s['nuclei']} nuclei from {s['images']} images. Active model: {CC.active_source()}.",
                             f"المحفوظ حتى الآن: {s['nuclei']} نواة من {s['images']} صورة. النموذج المستخدم: "
                             f"{'المدرَّب على شرائحك' if CC.active_source() == 'user' else 'الأصلي'}."))

    def save(self):
        if self.X is None or not self.labels:
            return
        idx = sorted(self.labels)
        TR.add_examples(self.X[idx], [TR.LABELS.index(self.labels[i]) for i in idx], self.name)
        self._refresh()
        QMessageBox.information(self, "", T(f"{len(idx)} labelled nuclei saved for {self.name}.", f"حُفظت {len(idx)} نواة مسمّاة للصورة {self.name}."))

    def train(self):
        if self.labels:
            self.save()
        pd_ = QProgressDialog(T("Training and cross-validating…", "جارٍ التدريب والتحقق المتقاطع…"), None, 0, 100, self)
        pd_.setWindowModality(Qt.WindowModal); pd_.setMinimumDuration(0)

        def prog(i, n):
            pd_.setValue(int(100 * i / n)); QApplication.processEvents()
        try:
            r = TR.train(progress=prog)
        except ValueError as e:
            pd_.close(); QMessageBox.warning(self, "", T(str(e), "سمِّ 40 نواة على الأقل من نوعين على الأقل (والأفضل 10–20 صورة و30 نواة أو أكثر من كل نوع).")); return
        pd_.close()
        rows = "".join(f"<tr><td>{k}</td><td>{r['f1_builtin'].get(k, '—')}</td><td>{r['f1_finetuned'].get(k, '—')}</td><td>{r['per_class_n'][k]}</td></tr>"
                       for k in TR.LABELS)
        html = (f"<p><b>{T('Validation', 'التحقق')}:</b> {r['cv']}</p><table border='1' cellpadding='4'>"
                f"<tr><th></th><th>F1 {T('built-in', 'الأصلي')}</th><th>F1 {T('fine-tuned', 'بعد التدريب')}</th><th>n</th></tr>{rows}"
                f"<tr><td><b>macro F1</b></td><td>{r['macro_f1_builtin']}</td><td>{r['macro_f1_finetuned']}</td><td>{r['nuclei']}</td></tr></table>"
                + (T("<p>The fine-tuned model is now used by the AI reader.</p>", "<p>أصبح القارئ يستخدم النموذج المدرَّب على شرائحك.</p>")
                   if r["activated"] else
                   T("<p>The fine-tuned model was not better on held-out images, so the built-in model is kept. Label more nuclei.</p>",
                     "<p>النموذج المدرَّب لم يتفوق على الصور المحجوزة للاختبار، لذلك بقي النموذج الأصلي. سمِّ أنوية أكثر.</p>")))
        box = QMessageBox(self); box.setWindowTitle(T("Training result", "نتيجة التدريب")); box.setTextFormat(Qt.RichText); box.setText(html)
        box.exec()
        self._refresh()

    def reset(self):
        if QMessageBox.question(self, "", T("Delete all your labels and the fine-tuned model?", "حذف كل تسمياتك والنموذج المدرَّب؟")) == QMessageBox.Yes:
            TR.clear_examples(); self._refresh()
