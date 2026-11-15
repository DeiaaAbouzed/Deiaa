"""Scale-bar dialog: calibration (pixel size, saved objective calibrations, or the bar already drawn on the image),
length, position and style. The bar is added as one movable item that is exported with the annotations."""
from __future__ import annotations

import json

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGraphicsItem, QGraphicsRectItem, QGraphicsSimpleTextItem, QHBoxLayout, QLabel,
                               QPushButton, QSpinBox, QVBoxLayout)

from ..core.settings import SETTINGS
from ..imaging import core as IC

OBJECTIVES = ["4×", "10×", "20×", "40×", "60×", "100×"]
POS_UI = {"bottom-right": ("Bottom right", "أسفل اليمين"), "bottom-left": ("Bottom left", "أسفل اليسار"),
          "top-right": ("Top right", "أعلى اليمين"), "top-left": ("Top left", "أعلى اليسار")}
STYLE_UI = {"black on white box": ("Black bar on a white box", "شريط أسود على مربع أبيض"), "black": ("Black bar", "شريط أسود"),
            "white": ("White bar", "شريط أبيض"), "white on black box": ("White bar on a black box", "شريط أبيض على مربع أسود")}


def T(en, ar):
    return ar if SETTINGS.language == "ar" else en


def load_calibrations() -> dict:
    try:
        return {k: float(v) for k, v in json.loads(QSettings("MedStatix", "MedStatixPro").value("objective_calibrations", "{}") or "{}").items()}
    except (ValueError, TypeError):
        return {}


def save_calibration(objective: str, um_per_px: float):
    d = load_calibrations(); d[objective] = float(um_per_px)
    QSettings("MedStatix", "MedStatixPro").setValue("objective_calibrations", json.dumps(d))


class ScaleBarDialog(QDialog):
    def __init__(self, parent, img, px_um=0.0):
        super().__init__(parent)
        self.img = img
        self.setWindowTitle(T("Scale bar", "مقياس الرسم"))
        lay = QVBoxLayout(self); f = QFormLayout()
        self.px = QDoubleSpinBox(); self.px.setDecimals(4); self.px.setRange(0, 100); self.px.setSuffix(" µm/px"); self.px.setValue(px_um)
        f.addRow(T("Pixel size", "حجم البكسل"), self.px)
        row = QHBoxLayout()
        self.obj = QComboBox(); self.obj.addItem(T("— objective —", "— العدسة الشيئية —"), "")
        cal = load_calibrations()
        for o in OBJECTIVES:
            self.obj.addItem(o + (f"  ({cal[o]:g} µm/px)" if o in cal else "  " + T("(not calibrated)", "(غير معايَرة)")), o)
        self.obj.currentIndexChanged.connect(self._objective)
        self.save_obj = QCheckBox(T("remember this pixel size for the objective", "احفظ حجم البكسل لهذه العدسة"))
        row.addWidget(self.obj); row.addWidget(self.save_obj)
        f.addRow(T("Objective", "العدسة"), row)
        rd = QPushButton(T("Read from the scale bar already on the image", "اقرأ من مقياس الرسم الموجود على الصورة"))
        rd.clicked.connect(self._read); f.addRow(rd)
        self.msg = QLabel(""); self.msg.setWordWrap(True); self.msg.setObjectName("hint"); f.addRow(self.msg)
        self.len = QDoubleSpinBox(); self.len.setDecimals(0); self.len.setRange(1, 20000); self.len.setSuffix(" µm")
        self.auto = QCheckBox(T("automatic round length", "طول تلقائي مناسب")); self.auto.setChecked(True)
        self.auto.toggled.connect(lambda on: self.len.setEnabled(not on)); self.len.setEnabled(False)
        r2 = QHBoxLayout(); r2.addWidget(self.len); r2.addWidget(self.auto); f.addRow(T("Length", "الطول"), r2)
        self.pos = QComboBox(); [self.pos.addItem(T(*POS_UI[k]), k) for k in IC.SCALE_BAR_POSITIONS]
        self.style = QComboBox(); [self.style.addItem(T(*STYLE_UI[k]), k) for k in IC.SCALE_BAR_STYLES]
        f.addRow(T("Position", "الموضع"), self.pos); f.addRow(T("Style", "الشكل"), self.style)
        self.label = QCheckBox(T("write the length under the bar", "كتابة الطول تحت الشريط")); self.label.setChecked(True); f.addRow(self.label)
        H, W = img.shape[:2]
        self.fs = QSpinBox(); self.fs.setRange(8, 400); self.fs.setValue(max(12, round(min(H, W) / 22)))
        self.th = QSpinBox(); self.th.setRange(1, 200); self.th.setValue(max(3, round(min(H, W) / 110)))
        r3 = QHBoxLayout(); r3.addWidget(QLabel(T("text", "النص"))); r3.addWidget(self.fs); r3.addWidget(QLabel(T("bar", "الشريط"))); r3.addWidget(self.th)
        f.addRow(T("Size (px)", "الحجم (بكسل)"), r3)
        lay.addLayout(f)
        hint = QLabel(T("Calibrate each objective once: photograph a stage micrometer (or open an image that already has a "
                        "scale bar and press Read), then tick 'remember'. The pixel size depends on the camera and the "
                        "adapter, so typical values from the internet are not reliable.",
                        "عاير كل عدسة مرة واحدة: صوّر شريحة الميكرومتر (أو افتح صورة عليها مقياس رسم واضغط «اقرأ») ثم فعّل «احفظ». "
                        "حجم البكسل يعتمد على الكاميرا والوصلة، لذلك لا يُعتمد على القيم المنشورة على الإنترنت."))
        hint.setWordWrap(True); hint.setObjectName("hint"); lay.addWidget(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); bb.accepted.connect(self._ok); bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._sync_len()
        self.px.valueChanged.connect(self._sync_len)

    def _sync_len(self):
        if self.px.value() > 0:
            self.len.setValue(IC.nice_bar_um(self.img.shape[1], self.px.value()))

    def _objective(self):
        o = self.obj.currentData()
        cal = load_calibrations()
        if o and o in cal:
            self.px.setValue(cal[o]); self.msg.setText(T(f"Saved calibration for {o}.", f"المعايرة المحفوظة للعدسة {o}."))

    def _read(self):
        from ..imaging import marks as MK
        sb = MK.scale_bar(self.img)
        if not sb:
            self.msg.setText(T("No scale bar was found on this image.", "لم يُعثر على مقياس رسم في هذه الصورة.")); return
        if sb["um"]:
            self.px.setValue(sb["um_per_px"])
            self.msg.setText(T(f"Found a {sb['um']} µm bar of {sb['px']} px → {sb['um_per_px']:.4f} µm/px.",
                               f"وُجد شريط {sb['um']} ميكرومتر طوله {sb['px']} بكسل ← {sb['um_per_px']:.4f} ميكرومتر/بكسل."))
        else:
            self.msg.setText(T(f"Found a bar of {sb['px']} px but could not read its label: enter its length in µm and divide.",
                               f"وُجد شريط طوله {sb['px']} بكسل لكن تعذرت قراءة الرقم: اقسم طوله بالميكرومتر على {sb['px']}."))

    def _ok(self):
        if self.px.value() <= 0:
            self.msg.setText(T("Enter the pixel size, choose a calibrated objective, or read it from the image.",
                               "أدخل حجم البكسل أو اختر عدسة معايَرة أو اقرأه من الصورة.")); return
        if self.save_obj.isChecked() and self.obj.currentData():
            save_calibration(self.obj.currentData(), self.px.value())
        self.accept()

    def values(self):
        return dict(um_per_px=self.px.value(), length_um=None if self.auto.isChecked() else self.len.value(),
                    position=self.pos.currentData(), style=self.style.currentData(), label=self.label.isChecked(),
                    thickness=self.th.value(), font_px=self.fs.value())


def scale_bar_item(scene, shape, v):
    """One movable item (box + bar + text) matching IC.draw_scale_bar."""
    g = IC.scale_bar_geometry(shape, v["um_per_px"], v["length_um"], v["position"], v["thickness"], v["font_px"])
    white_fg = v["style"].startswith("white")
    fg = QColor("#FFFFFF" if white_fg else "#000000")
    items = []
    if "box" in v["style"]:
        bx, by, bw, bh = g["box"]
        if not v["label"]:
            bh = g["th"] + 2 * g["pad"]
        box = QGraphicsRectItem(bx, by, bw, bh); box.setBrush(QBrush(QColor("#000000" if white_fg else "#FFFFFF"))); box.setPen(QPen(Qt.NoPen))
        items.append(box)
    x, y, L, th = g["bar"]
    bar = QGraphicsRectItem(x, y, L, th); bar.setBrush(QBrush(fg)); bar.setPen(QPen(Qt.NoPen)); items.append(bar)
    if v["label"]:
        t = QGraphicsSimpleTextItem(IC.scale_bar_label(g["um"]))
        f = QFont("Arial"); f.setPixelSize(int(g["fs"])); f.setBold(True); t.setFont(f); t.setBrush(QBrush(fg))
        cx, cy = g["label_center"]; br = t.boundingRect()
        t.setPos(cx - br.width() / 2, cy - br.height() / 2); items.append(t)
    for it in items:
        scene.addItem(it)
    grp = scene.createItemGroup(items)
    grp.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable)
    grp.setToolTip(f"Scale bar {IC.scale_bar_label(g['um'])} ({v['um_per_px']:.4f} µm/px)")
    return grp, g["um"]
