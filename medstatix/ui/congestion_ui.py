"""Teach congestion detection: paint red cells and 'not red cells' with a brush, then train the pixel classifier."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView,
                               QHBoxLayout, QLabel, QMessageBox, QProgressDialog, QPushButton, QRadioButton, QSpinBox,
                               QVBoxLayout)

from ..core.settings import SETTINGS
from ..imaging import rbc_learn as RL


def T(en, ar):
    return ar if SETTINGS.language == "ar" else en


MODES = [("rbc", "Red cells (congestion / haemorrhage)", "كرات دم حمراء (احتقان / نزف)", (229, 57, 53)),
         ("bg", "Not red cells (muscle, collagen, cytoplasm…)", "ليست كرات دم (عضلات، كولاجين، سيتوبلازم…)", (30, 136, 229)),
         ("erase", "Eraser", "ممحاة", (0, 0, 0))]


class _View(QGraphicsView):
    def __init__(self, dlg):
        super().__init__()
        self.dlg = dlg
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._paint = False

    def wheelEvent(self, e):
        f = 1.25 if e.angleDelta().y() > 0 else 0.8
        self.scale(f, f)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not (e.modifiers() & Qt.ControlModifier):
            self._paint = True
            p = self.mapToScene(e.position().toPoint()); self.dlg.dab(p.x(), p.y())
        else:
            self.setDragMode(QGraphicsView.ScrollHandDrag); super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._paint:
            p = self.mapToScene(e.position().toPoint()); self.dlg.dab(p.x(), p.y())
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._paint:
            self._paint = False; self.dlg.stroke_done()
        else:
            super().mouseReleaseEvent(e); self.setDragMode(QGraphicsView.NoDrag)


class CongestionTeachDialog(QDialog):
    def __init__(self, parent, img, image_name, qimage_fn):
        super().__init__(parent)
        self.img, self.name = img[..., :3], image_name
        H, W = self.img.shape[:2]
        self.rbc = np.zeros((H, W), bool); self.bg = np.zeros((H, W), bool)
        self.setWindowTitle(T("Teach congestion detection", "تعليم كشف الاحتقان"))
        lay = QVBoxLayout(self)
        hint = QLabel(T("Paint over red cells inside congested vessels or haemorrhage, and paint 'not red cells' over the "
                        "structures that look similar in colour (muscle fibres, collagen, eosinophilic cytoplasm). A few "
                        "strokes of each per image are enough; do this on about 10 images. Ctrl+drag moves the image, the "
                        "wheel zooms. Labels and the model stay on this computer.",
                        "لوّن فوق كرات الدم الحمراء داخل الأوعية المحتقنة أو النزف، ولوّن «ليست كرات دم» فوق ما يشبهها في اللون "
                        "(ألياف العضلات، الكولاجين، السيتوبلازم الحمضي). بضع ضربات من كل نوع في الصورة تكفي، على نحو 10 صور. "
                        "Ctrl مع السحب لتحريك الصورة، والعجلة للتكبير. التسميات والنموذج تبقى على جهازك فقط."))
        hint.setWordWrap(True); hint.setObjectName("hint"); lay.addWidget(hint)
        row = QHBoxLayout(); self.grp = QButtonGroup(self)
        for i, (k, en, ar, c) in enumerate(MODES):
            rb = QRadioButton(T(en, ar)); rb.setStyleSheet(f"color:rgb{c}; font-weight:600;" if k != "erase" else "")
            self.grp.addButton(rb, i); row.addWidget(rb)
            rb.setChecked(i == 0)
        row.addWidget(QLabel(T("Brush", "الفرشاة")))
        self.size = QSpinBox(); self.size.setRange(2, 200); self.size.setValue(max(4, round(min(H, W) / 70))); self.size.setSuffix(" px")
        row.addWidget(self.size); row.addStretch(1); lay.addLayout(row)
        self.scene = QGraphicsScene(self)
        self.scene.addPixmap(QPixmap.fromImage(qimage_fn(self.img)))
        self.overlay = QImage(W, H, QImage.Format_ARGB32_Premultiplied); self.overlay.fill(Qt.transparent)
        self.ov_item = QGraphicsPixmapItem(QPixmap.fromImage(self.overlay)); self.scene.addItem(self.ov_item)
        self.pred_item = QGraphicsPixmapItem(); self.scene.addItem(self.pred_item)
        self.view = _View(self); self.view.setScene(self.scene); lay.addWidget(self.view, 1)
        self.count = QLabel(); lay.addWidget(self.count)
        self.store = QLabel(); self.store.setObjectName("hint"); lay.addWidget(self.store)
        row = QHBoxLayout()
        for txt, fn in [(T("Save this image", "حفظ هذه الصورة"), self.save), (T("Train now", "درّب الآن"), self.train),
                        (T("Show what the model finds", "اعرض ما يكتشفه النموذج"), self.preview),
                        (T("Delete my congestion labels", "حذف تسميات الاحتقان"), self.reset)]:
            b = QPushButton(txt); b.clicked.connect(fn); row.addWidget(b)
        row.addStretch(1)
        c = QPushButton(T("Close", "إغلاق")); c.clicked.connect(self.accept); row.addWidget(c)
        lay.addLayout(row)
        self._refresh()
        self.resize(1150, 850)
        self.view.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_fitted", False):
            self._fitted = True
            self.view.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)

    # painting -----------------------------------------------------------------
    def dab(self, x, y):
        from skimage.draw import disk
        r = self.size.value() / 2
        rr, cc = disk((y, x), r, shape=self.rbc.shape)
        mode = MODES[self.grp.checkedId()][0]
        if mode == "rbc":
            self.rbc[rr, cc] = True; self.bg[rr, cc] = False
        elif mode == "bg":
            self.bg[rr, cc] = True; self.rbc[rr, cc] = False
        else:
            self.rbc[rr, cc] = False; self.bg[rr, cc] = False
        p = QPainter(self.overlay)
        if mode == "erase":
            p.setCompositionMode(QPainter.CompositionMode_Clear); p.setBrush(Qt.black)
        else:
            col = QColor(*MODES[self.grp.checkedId()][3], 110)
            p.setCompositionMode(QPainter.CompositionMode_Source); p.setBrush(col)
        p.setPen(Qt.NoPen); p.drawEllipse(int(x - r), int(y - r), int(2 * r), int(2 * r)); p.end()
        self.ov_item.setPixmap(QPixmap.fromImage(self.overlay))

    def stroke_done(self):
        self._refresh()

    def _refresh(self):
        self.count.setText(T(f"This image: red cells {int(self.rbc.sum())} px · background {int(self.bg.sum())} px",
                             f"هذه الصورة: كرات دم {int(self.rbc.sum())} بكسل · خلفية {int(self.bg.sum())} بكسل"))
        s = RL.summary()
        act = RL.active()
        self.store.setText(T(f"Saved: {s['images']} images. Congestion detector in use: "
                             f"{'trained on your slides' if act else 'built-in colour rule'}.",
                             f"المحفوظ: {s['images']} صورة. كاشف الاحتقان المستخدم: "
                             f"{'المدرَّب على شرائحك' if act else 'قاعدة اللون الأصلية'}."))

    # actions ------------------------------------------------------------------
    def save(self, quiet=False):
        if not self.rbc.any() and not self.bg.any():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            RL.add_examples(self.img, self.rbc, self.bg, self.name)
        finally:
            QApplication.restoreOverrideCursor()
        self._refresh()
        if not quiet:
            QMessageBox.information(self, "", T(f"Labels of {self.name} saved.", f"حُفظت تسميات {self.name}."))

    def train(self):
        self.save(quiet=True)
        pd_ = QProgressDialog(T("Training and validating image by image…", "جارٍ التدريب والتحقق صورةً بصورة…"), None, 0, 100, self)
        pd_.setWindowModality(Qt.WindowModal); pd_.setMinimumDuration(0)

        def prog(i, n):
            pd_.setValue(int(100 * i / n)); QApplication.processEvents()
        try:
            r = RL.train(progress=prog)
        except ValueError:
            pd_.close()
            QMessageBox.warning(self, "", T("Paint red cells and background on at least 3 images (ideally about 10).",
                                            "لوّن كرات الدم والخلفية على 3 صور على الأقل (والأفضل نحو 10 صور).")); return
        pd_.close()
        rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in r["f1_per_image"].items())
        html = (f"<p><b>{T('Validation', 'التحقق')}:</b> {r['cv']}</p>"
                f"<p>{T('Pixel F1, learned model', 'F1 للنموذج المتعلَّم')}: <b>{r['f1']}</b> (AUC {r['auc']}) · "
                f"{T('colour rule', 'قاعدة اللون')}: <b>{r['f1_rule']}</b></p>"
                f"<table border='1' cellpadding='3'>{rows}</table>"
                + (T("<p>The learned detector is now used for congestion.</p>", "<p>أصبح الكاشف المتعلَّم يُستخدم للاحتقان.</p>")
                   if r["activated"] else
                   T("<p>It did not beat the colour rule on held-out images, so the colour rule is kept. Paint more images.</p>",
                     "<p>لم يتفوق على قاعدة اللون في الصور المحجوزة، فبقيت قاعدة اللون. لوّن صورًا أكثر.</p>")))
        box = QMessageBox(self); box.setWindowTitle(T("Training result", "نتيجة التدريب")); box.setTextFormat(Qt.RichText)
        box.setText(html); box.exec()
        self._refresh()

    def preview(self):
        if not RL.active():
            QMessageBox.information(self, "", T("No trained congestion model yet.", "لا يوجد نموذج احتقان مدرَّب بعد.")); return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            m = RL.predict_mask(self.img)
        finally:
            QApplication.restoreOverrideCursor()
        H, W = m.shape
        rgba = np.zeros((H, W, 4), np.uint8); rgba[m] = (255, 214, 0, 120)
        q = QImage(rgba.data, W, H, 4 * W, QImage.Format_RGBA8888).copy()
        self.pred_item.setPixmap(QPixmap.fromImage(q))

    def reset(self):
        if QMessageBox.question(self, "", T("Delete all your congestion labels and the learned model?",
                                            "حذف كل تسميات الاحتقان والنموذج المتعلَّم؟")) == QMessageBox.Yes:
            RL.clear(); self._refresh()
