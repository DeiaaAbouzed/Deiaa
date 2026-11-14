"""Prism-style figure editor with live preview (for group-comparison figures)."""
from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QSplitter, QTabWidget, QTextEdit, QToolButton, QVBoxLayout, QWidget)

from ..core.settings import SETTINGS
from ..plots import groupfig as G
from ..plots.figures import PALETTES

FONTS = ["Arial", "Helvetica", "Calibri", "Times New Roman", "DejaVu Sans", "Liberation Sans"]


def T(en, ar):
    return ar if SETTINGS.language == "ar" else en


class FigureEditorDialog(QDialog):
    def __init__(self, spec: G.GroupFigSpec, parent=None):
        super().__init__(parent)
        self.spec = spec.copy()
        if not self.spec.plot_type:
            self.spec.plot_type = SETTINGS.group_plot
        if not self.spec.error_bar:
            self.spec.error_bar = SETTINGS.error_bar
        self.setWindowTitle(T("Figure editor (Prism style)", "محرر الرسم (نمط Prism)"))
        self.resize(1250, 780)
        self._timer = QTimer(self); self._timer.setSingleShot(True); self._timer.setInterval(180)
        self._timer.timeout.connect(self.redraw)
        lay = QVBoxLayout(self)
        split = QSplitter(Qt.Horizontal)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_chart(), T("Chart", "الرسم"))
        self.tabs.addTab(self._tab_points(), T("Points", "النقاط"))
        self.tabs.addTab(self._tab_axes(), T("Axes", "المحاور"))
        self.tabs.addTab(self._tab_sig(), T("Significance", "الدلالة"))
        self.tabs.addTab(self._tab_caption(), T("Caption", "التعليق"))
        self.tabs.setMinimumWidth(470)
        split.addWidget(self.tabs)
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0, 0, 0, 0)
        self.canvas_holder = QVBoxLayout(); rl.addLayout(self.canvas_holder, 1)
        self.cap_preview = QLabel(); self.cap_preview.setWordWrap(True); self.cap_preview.setObjectName("hint")
        self.cap_preview.setLayoutDirection(Qt.LeftToRight); self.cap_preview.setAlignment(Qt.AlignLeft)
        rl.addWidget(self.cap_preview)
        split.addWidget(right)
        split.setSizes([440, 800])
        lay.addWidget(split, 1)
        bb = QDialogButtonBox()
        ok = bb.addButton(T("Apply to figure", "تطبيق على الرسم"), QDialogButtonBox.AcceptRole); ok.setObjectName("primary")
        bb.addButton(T("Cancel", "إلغاء"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.canvas = None
        self.redraw()

    # ------------------------------------------------------------------ helpers
    def _changed(self, *_):
        self._read()
        self._timer.start()

    def _combo(self, items, current, data=None):
        c = QComboBox()
        for i, it in enumerate(items):
            c.addItem(it, (data[i] if data else it))
        idx = c.findData(current)
        c.setCurrentIndex(max(idx, 0))
        c.currentIndexChanged.connect(self._changed)
        return c

    def _dspin(self, lo, hi, val, step=0.5, dec=1):
        s = QDoubleSpinBox(); s.setRange(lo, hi); s.setDecimals(dec); s.setSingleStep(step); s.setValue(val)
        s.valueChanged.connect(self._changed)
        return s

    def _check(self, txt, val):
        c = QCheckBox(txt); c.setChecked(val); c.toggled.connect(self._changed)
        return c

    def _line(self, val):
        e = QLineEdit(val); e.textChanged.connect(self._changed)
        return e

    # ------------------------------------------------------------------ tabs
    def _tab_chart(self):
        w = QWidget(); f = QFormLayout(w)
        ar = SETTINGS.language == "ar"
        self.c_type = self._combo(G.PLOT_TYPES_AR if ar else G.PLOT_TYPES, self.spec.plot_type, G.PLOT_TYPES)
        self.c_err = self._combo(G.ERROR_TYPES, self.spec.error_bar)
        self.c_center = self._combo([T("Mean", "المتوسط"), T("Median", "الوسيط")], self.spec.center, ["mean", "median"])
        f.addRow(T("Chart type", "نوع الرسم"), self.c_type)
        f.addRow(T("Error bars", "أشرطة الخطأ"), self.c_err)
        f.addRow(T("Centre line", "الخط المركزي"), self.c_center)
        self.c_pal = QComboBox(); self.c_pal.addItem(T("— apply a palette —", "— تطبيق لوحة ألوان —"), None)
        for name in PALETTES:
            self.c_pal.addItem(name, name)
        self.c_pal.currentIndexChanged.connect(self._apply_palette)
        f.addRow(T("Journal palette", "ألوان المجلة"), self.c_pal)
        self.color_grid = QGridLayout()
        box = QWidget(); box.setLayout(self.color_grid)
        f.addRow(T("Colour per group", "لون كل مجموعة"), box)
        self._build_color_buttons()
        self.c_fill = self._dspin(0, 1, self.spec.fill_alpha, 0.05, 2)
        f.addRow(T("Fill transparency (bars/boxes)", "شفافية التعبئة"), self.c_fill)
        # group order
        self.order = QListWidget(); self.order.setDragDropMode(QListWidget.InternalMove); self.order.setMaximumHeight(140)
        for l in self.spec.groups:
            self.order.addItem(l)
        self.order.model().rowsMoved.connect(self._changed)
        f.addRow(T("Group order (drag)", "ترتيب المجموعات (اسحب)"), self.order)
        return w

    def _build_color_buttons(self):
        while self.color_grid.count():
            it = self.color_grid.takeAt(0)
            if it.widget():
                it.widget().setParent(None)
        from ..plots.figures import palette
        pal = palette(len(self.spec.groups))
        for i, l in enumerate(self.spec.groups):
            col = self.spec.colors.get(l, pal[i])
            b = QToolButton(); b.setFixedSize(30, 22)
            b.setStyleSheet(f"background:{QColor(col).name()}; border:1px solid #555; border-radius:4px;")
            b.clicked.connect(lambda _=False, lab=l, btn=b: self._pick_color(lab, btn))
            lab = QLabel(l if len(l) < 28 else l[:26] + "…")
            self.color_grid.addWidget(b, i, 0); self.color_grid.addWidget(lab, i, 1)

    def _pick_color(self, label, btn):
        from ..plots.figures import palette
        pal = palette(len(self.spec.groups))
        cur = self.spec.colors.get(label, pal[list(self.spec.groups).index(label)])
        c = QColorDialog.getColor(QColor(cur), self)
        if c.isValid():
            self.spec.colors[label] = c.name()
            btn.setStyleSheet(f"background:{c.name()}; border:1px solid #555; border-radius:4px;")
            self._timer.start()

    def _apply_palette(self):
        name = self.c_pal.currentData()
        if not name:
            return
        cols = PALETTES[name]
        self.spec.colors = {l: cols[i % len(cols)] for i, l in enumerate(self.spec.groups)}
        self._build_color_buttons()
        self._timer.start()

    def _tab_points(self):
        w = QWidget(); f = QFormLayout(w)
        self.p_size = self._dspin(1, 20, self.spec.point_size, 0.5)
        names = list(G.MARKERS)
        cur = next((n for n, m in G.MARKERS.items() if m == self.spec.marker), names[0])
        self.p_marker = self._combo(names, cur)
        self.p_edge = self._check(T("Dark outline around points", "حد داكن حول النقاط"), self.spec.point_edge)
        self.p_lw = self._dspin(0.5, 4, self.spec.line_width, 0.1, 1)
        self.p_bw = self._dspin(0.2, 0.95, self.spec.bar_width, 0.05, 2)
        f.addRow(T("Point size", "حجم النقطة"), self.p_size)
        f.addRow(T("Point shape", "شكل النقطة"), self.p_marker)
        f.addRow("", self.p_edge)
        f.addRow(T("Line width", "سُمك الخطوط"), self.p_lw)
        f.addRow(T("Bar / box width", "عرض العمود/الصندوق"), self.p_bw)
        return w

    def _tab_axes(self):
        w = QWidget(); f = QFormLayout(w)
        self.a_title = self._line(self.spec.title)
        self.a_x = self._line(self.spec.xlabel)
        self.a_y = self._line(self.spec.ylabel)
        self.a_font = self._combo(FONTS, self.spec.font_family or SETTINGS.font_family)
        self.a_fs = self._dspin(6, 24, self.spec.font_size or SETTINGS.font_size, 0.5)
        self.a_auto_y = self._check(T("Automatic Y range", "مدى Y تلقائي"), self.spec.y_min is None and self.spec.y_max is None)
        self.a_ymin = self._dspin(-1e9, 1e9, self.spec.y_min or 0, 1, 3)
        self.a_ymax = self._dspin(-1e9, 1e9, self.spec.y_max or 0, 1, 3)
        self.a_log = self._check(T("Logarithmic Y axis", "محور Y لوغاريتمي"), self.spec.y_log)
        ar = SETTINGS.language == "ar"
        self.a_lab = self._combo(G.LABEL_MODES_AR if ar else G.LABEL_MODES, self.spec.label_mode, G.LABEL_MODES)
        self.a_w = self._dspin(0, 300, self.spec.width_mm, 5, 0)
        self.a_h = self._dspin(0, 300, self.spec.height_mm, 5, 0)
        self.a_w.setSpecialValueText(T("auto", "تلقائي")); self.a_h.setSpecialValueText(T("auto", "تلقائي"))
        f.addRow(T("Title", "العنوان"), self.a_title)
        f.addRow(T("X-axis title", "عنوان المحور السيني"), self.a_x)
        f.addRow(T("Y-axis title", "عنوان المحور الصادي"), self.a_y)
        f.addRow(T("Font", "الخط"), self.a_font)
        f.addRow(T("Font size (pt)", "حجم الخط"), self.a_fs)
        f.addRow("", self.a_auto_y)
        f.addRow(T("Y minimum", "أدنى Y"), self.a_ymin)
        f.addRow(T("Y maximum", "أعلى Y"), self.a_ymax)
        f.addRow("", self.a_log)
        f.addRow(T("Group labels", "أسماء المجموعات"), self.a_lab)
        f.addRow(T("Width (mm)", "العرض (مم)"), self.a_w)
        f.addRow(T("Height (mm)", "الارتفاع (مم)"), self.a_h)
        return w

    def _tab_sig(self):
        w = QWidget(); f = QFormLayout(w)
        ar = SETTINGS.language == "ar"
        self.s_mode = self._combo(G.SIG_MODES_AR if ar else G.SIG_MODES, self.spec.sig_mode, G.SIG_MODES)
        self.s_layout = self._combo(G.SIG_LAYOUTS_AR if ar else G.SIG_LAYOUTS, self.spec.sig_layout, G.SIG_LAYOUTS)
        self.s_style = self._combo(G.SIG_STYLES_AR if ar else G.SIG_STYLES, self.spec.sig_style, G.SIG_STYLES)
        self.s_scheme = self._combo(G.STAR_SCHEMES, self.spec.star_scheme)
        self.s_ns = self._check(T("Show non-significant (ns)", "إظهار غير الدال (ns)"), self.spec.show_ns)
        labels = list(self.spec.groups)
        self.s_ref1 = self._combo(labels, self.spec.ref1 or labels[0])
        self.s_ref2 = self._combo([T("— none —", "— لا يوجد —")] + labels, self.spec.ref2 or None, [None] + labels)
        f.addRow(T("Which comparisons", "المقارنات المعروضة"), self.s_mode)
        f.addRow(T("Layout", "طريقة العرض"), self.s_layout)
        f.addRow(T("Label", "الصيغة"), self.s_style)
        f.addRow(T("Star thresholds", "حدود النجوم"), self.s_scheme)
        f.addRow("", self.s_ns)
        f.addRow(T("Reference group (*)", "المجموعة المرجعية (*)"), self.s_ref1)
        f.addRow(T("Second reference (#)", "مرجع ثانٍ (#)"), self.s_ref2)
        self.s_list = QListWidget(); self.s_list.setMinimumHeight(170)
        sel = set(self.spec.selected)
        for a, b, p in self.spec.comparisons:
            it = QListWidgetItem(f"{a}  vs  {b}    ({G.p_text(p)} {G.star_text(p, self.spec.star_scheme)})")
            it.setData(Qt.UserRole, G.pair_key(a, b))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            on = G.pair_key(a, b) in sel or (not sel and G.star_text(p) != "ns")
            it.setCheckState(Qt.Checked if on else Qt.Unchecked)
            self.s_list.addItem(it)
        self.s_list.itemChanged.connect(self._custom_changed)
        f.addRow(T("Custom selection (tick pairs)", "اختيار يدوي (حدد الأزواج)"), self.s_list)
        hint = QLabel(T("Tip: with many groups, 'Versus reference group' + 'Symbols above groups' gives a clean figure "
                        "(* vs control, # vs disease model), as in GraphPad Prism.",
                        "نصيحة: مع كثرة المجموعات اختر «مقارنة بمجموعة مرجعية» مع «رموز فوق المجموعات» لرسم نظيف "
                        "(* مقابل الضابطة، # مقابل مجموعة المرض) كما في GraphPad Prism."))
        hint.setWordWrap(True); hint.setObjectName("hint"); f.addRow(hint)
        return w

    def _custom_changed(self, _item):
        if self.s_mode.currentData() != "Custom selection":
            self.s_mode.setCurrentIndex(self.s_mode.findData("Custom selection"))
        self._changed()

    def _tab_caption(self):
        w = QWidget(); v = QVBoxLayout(w)
        self.c_auto = QCheckBox(T("Automatic caption (updates with the figure)", "تعليق تلقائي (يتحدث مع الرسم)"))
        self.c_auto.setChecked(not self.spec.caption)
        self.c_auto.toggled.connect(self._caption_mode)
        self.c_text = QTextEdit(); self.c_text.setPlainText(self.spec.caption or G.auto_caption(self.spec))
        self.c_text.setEnabled(bool(self.spec.caption))
        self.c_text.textChanged.connect(self._changed)
        ar_lbl = QLabel(T("Arabic version (for reference):", "النسخة العربية (للاسترشاد):"))
        self.c_ar = QTextEdit(); self.c_ar.setReadOnly(True); self.c_ar.setMaximumHeight(110)
        v.addWidget(self.c_auto); v.addWidget(self.c_text, 1); v.addWidget(ar_lbl); v.addWidget(self.c_ar)
        return w

    def _caption_mode(self, auto):
        self.c_text.setEnabled(not auto)
        if auto:
            self.c_text.blockSignals(True); self.c_text.setPlainText(G.auto_caption(self.spec)); self.c_text.blockSignals(False)
        self._changed()

    # ------------------------------------------------------------------ read & draw
    def _read(self):
        s = self.spec
        s.plot_type = self.c_type.currentData(); s.error_bar = self.c_err.currentData(); s.center = self.c_center.currentData()
        s.fill_alpha = self.c_fill.value()
        order = [self.order.item(i).text() for i in range(self.order.count())]
        if order and set(order) == set(s.groups) and order != list(s.groups):
            s.groups = {l: s.groups[l] for l in order}
            self._build_color_buttons()
        s.point_size = self.p_size.value(); s.marker = G.MARKERS[self.p_marker.currentData()]; s.point_edge = self.p_edge.isChecked()
        s.line_width = self.p_lw.value(); s.bar_width = self.p_bw.value()
        s.title = self.a_title.text(); s.xlabel = self.a_x.text(); s.ylabel = self.a_y.text()
        s.font_family = self.a_font.currentData(); s.font_size = self.a_fs.value()
        if self.a_auto_y.isChecked():
            s.y_min = s.y_max = None
        else:
            s.y_min, s.y_max = self.a_ymin.value(), self.a_ymax.value()
        s.y_log = self.a_log.isChecked(); s.label_mode = self.a_lab.currentData()
        s.width_mm = self.a_w.value(); s.height_mm = self.a_h.value()
        s.sig_mode = self.s_mode.currentData(); s.sig_layout = self.s_layout.currentData(); s.sig_style = self.s_style.currentData()
        s.star_scheme = self.s_scheme.currentData(); s.show_ns = self.s_ns.isChecked()
        s.ref1 = self.s_ref1.currentData(); s.ref2 = self.s_ref2.currentData() or ""
        s.selected = [self.s_list.item(i).data(Qt.UserRole) for i in range(self.s_list.count())
                      if self.s_list.item(i).checkState() == Qt.Checked]
        s.caption = "" if self.c_auto.isChecked() else self.c_text.toPlainText().strip()

    def redraw(self):
        try:
            fig = G.render(self.spec)
        except Exception as e:  # keep the editor alive on odd settings (e.g. log axis with zeros)
            self.cap_preview.setText(f"⚠ {e}")
            return
        if self.canvas is not None:
            self.canvas.setParent(None)
        self.canvas = FigureCanvasQTAgg(fig)
        self.canvas.setMinimumSize(520, 380)
        self.canvas_holder.addWidget(self.canvas)
        self.canvas.draw()
        self.fig = fig
        if self.c_auto.isChecked():
            self.c_text.blockSignals(True); self.c_text.setPlainText(G.auto_caption(self.spec)); self.c_text.blockSignals(False)
        self.c_ar.setPlainText(G.auto_caption(self.spec, "ar"))
        self.cap_preview.setText("<b>" + T("Caption: ", "التعليق: ") + "</b>" + G.caption_for(self.spec))

    def final(self):
        self._read()
        return G.render(self.spec), G.caption_for(self.spec)
