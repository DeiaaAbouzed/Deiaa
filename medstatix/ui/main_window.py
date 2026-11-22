"""MedStatix Pro main window."""
from __future__ import annotations

import io
import os
import traceback

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, QSettings, QSize, QUrl, QByteArray
from PySide6.QtGui import QAction, QIcon, QImage, QKeySequence, QPixmap, QTextDocument
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSplitter, QTableView, QTabWidget,
                               QTextBrowser, QToolBar, QToolButton, QMenu, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QComboBox, QDialog)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT

from ..analyses import REGISTRY, CATEGORIES, run
from ..core.advisor import auto_analyze
from ..core.data import IMPORT_FILTER, load_file, save_file, make_sample_datasets, is_numeric
from ..core.result import AnalysisError, APP_NAME, APP_VERSION, fig_to_png_bytes
from ..core.settings import SETTINGS
from ..report.export import results_to_docx, results_to_xlsx, results_to_html, export_figure
from .i18n import tr, lbl
from .theme import stylesheet, output_css
from ..core.errors import friendly
from ..core import smartimport as SI
from .widgets import (AboutDialog, AnalysisDialog, FormDialog, ImportAssistant, PandasModel, SettingsDialog, SmartDialog, VarList,
                      WizardDialog, combo, variables_frame)

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.qs = QSettings("MedStatix", "MedStatixPro")
        self._load_settings()
        self.df = pd.DataFrame()
        self.df_full = None
        self.dataset_name = ""
        self.entries = []   # list of dicts: {result, aid, kwargs, df}
        self.png_cache = {}
        self.current_fig = None
        self.setAcceptDrops(True)
        icon = os.path.join(ICON_DIR, "icon.png")
        if os.path.exists(icon):
            self.setWindowIcon(QIcon(icon))
        self.resize(1440, 900)
        self.build()
        self.load_df(make_sample_datasets()["Clinical trial (simulated)"], "Clinical trial (simulated)")

    # ------------------------------------------------------------------ settings persistence
    def _load_settings(self):
        for k, v in SETTINGS.as_dict().items():
            stored = self.qs.value(k)
            if stored is not None:
                try:
                    if isinstance(v, bool):
                        stored = str(stored).lower() in ("true", "1")
                    else:
                        stored = type(v)(stored)
                    setattr(SETTINGS, k, stored)
                except (TypeError, ValueError):
                    pass
        # 1.7: the MedStatix Signature house style becomes the default once (it can be changed back in Settings)
        if str(self.qs.value("style_version", "0")) < "2":
            SETTINGS.fig_style, SETTINGS.palette, SETTINGS.table_style = "Signature", "MedStatix Signature", "Signature"
            self.qs.setValue("style_version", "2")

    def _save_settings(self):
        for k, v in SETTINGS.as_dict().items():
            self.qs.setValue(k, v)

    # ------------------------------------------------------------------ UI construction
    def build(self):
        if getattr(self, "_assistant", None) is not None:
            self._assistant.close(); self._assistant.deleteLater(); self._assistant = None
        rtl = SETTINGS.language == "ar"
        QApplication.instance().setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        QApplication.instance().setStyleSheet(stylesheet(SETTINGS.theme, rtl))
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION} — {tr('app_tagline')}")
        self.menuBar().clear()
        for tb in self.findChildren(QToolBar):
            self.removeToolBar(tb); tb.deleteLater()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_sidebar())
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_data_tab(), "▦  " + tr("tab_data"))
        self.tabs.addTab(self._build_vars_tab(), "≡  " + tr("tab_vars"))
        self.tabs.addTab(self._build_output_tab(), "📊  " + tr("tab_output"))
        self.tabs.addTab(self._build_fig_tab(), "🎨  " + tr("tab_figs"))
        from .histology import HistologyStudio
        self.histo = HistologyStudio(self)
        self.histo.send_result.connect(self._histo_result)
        self.histo.send_rows.connect(self._histo_rows)
        self.tabs.addTab(self.histo, "🔬  " + tr("tab_histo"))
        from .figure_studio import FigureStudio
        self.figstudio = FigureStudio(self)
        self.tabs.addTab(self.figstudio, "🖼  " + tr("tab_images"))
        wrap = QWidget(); wl = QVBoxLayout(wrap); wl.setContentsMargins(8, 8, 8, 8); wl.addWidget(self.tabs)
        splitter.addWidget(wrap)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 1140])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage(tr("status_ready"))
        if not self.df.empty:
            self.model.set_df(self.df)
            self.refresh_vars()
        self.refresh_output()
        self.refresh_fig_list()

    def _act(self, text, slot, shortcut=None, tip=None):
        a = QAction(text, self)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setToolTip(tip)
        return a

    def _build_actions(self):
        self.a_open = self._act("📂  " + tr("open"), self.open_file, "Ctrl+O")
        self.a_save = self._act("💾  " + tr("save"), self.save_file, "Ctrl+S")
        self.a_new = self._act("🗋  " + tr("new"), self.new_data, "Ctrl+N")
        self.a_paste = self._act("📋  " + tr("paste"), self.paste_data, "Ctrl+Shift+V")
        self.a_smart = self._act("🧠  " + tr("smart"), self.smart_analyze, "Ctrl+M")
        self.a_wizard = self._act("🧭  " + tr("wizard"), self.wizard, "Ctrl+W")
        self.a_assist = self._act("🤖  " + ("المساعد الإحصائي" if SETTINGS.language == "ar" else "Assistant"), self.open_assistant, "Ctrl+K")
        self.a_recs = self._act("⭐  " + ("التوصيات" if SETTINGS.language == "ar" else "Recommendations"),
                                lambda: self._need_data() and self.import_assistant([]), "Ctrl+R")
        self.a_word = self._act("📝  " + tr("export_word"), lambda: self.export("docx"), "Ctrl+E")
        self.a_excel = self._act("📗  " + tr("export_excel"), lambda: self.export("xlsx"))
        self.a_html = self._act("🌐  " + tr("export_html"), lambda: self.export("html"))
        self.a_settings = self._act("⚙  " + tr("settings"), self.open_settings, "Ctrl+,")
        self.a_lang = self._act("🌍  " + tr("language"), self.toggle_language, "Ctrl+L")
        self.a_clear = self._act("🧹  " + tr("clear_output"), self.clear_output)
        A = SETTINGS.language == "ar"
        self.a_psave = self._act("🗂  " + ("حفظ المشروع" if A else "Save project"), self.save_project, "Ctrl+Shift+S")
        self.a_popen = self._act("📁  " + ("فتح مشروع" if A else "Open project"), lambda: self.open_project(), "Ctrl+Shift+O")
        self.a_rerun = self._act("🔁  " + ("إعادة تشغيل كل التحليلات على البيانات الحالية" if A else "Re-run all analyses on current data"),
                                 self.rerun_all_current, "Ctrl+Shift+R")
        self.a_journal = self._act("📰  " + ("المجلة المستهدفة (مقاسات الرسوم)…" if A else "Target journal (figure specs)…"), self.choose_journal)
        self.a_paper = self._act("📚  " + ("كتابة البحث كاملًا (Word + EndNote)…" if A else "Write the full paper (Word + EndNote)…"),
                                 self.write_paper, "Ctrl+Shift+P")
        self.a_ms = self._act("📄  " + ("بناء المخطوطة (Word)…" if A else "Build manuscript (Word)…"), self.build_manuscript, "Ctrl+Shift+M")
        self.a_rev = self._act("🧾  " + ("تقرير المحكّمين الإحصائي…" if A else "Statistical report for reviewers…"), self.reviewer_report)
        self.a_panel = self._act("🧩  " + ("لوحة رسوم متعددة (A, B, C)…" if A else "Multi-panel figure (A, B, C)…"), self.panel_builder)
        self.a_animal = self._act("🐀  " + ("أدوات دراسات الحيوان (عشوائية، حجم عينة، شواذ، ARRIVE)…" if A
                                         else "Animal-study toolkit (randomise, sample size, outliers, ARRIVE)…"), self.animal_toolkit)
        # quick access to the newest tools (toolbar, next to Recommendations)
        self.a_q_paper = self._act("📚  " + ("البحث الكامل" if A else "Full paper"), self.write_paper,
                                   tip="كتابة البحث كاملًا (Word + EndNote) — Ctrl+Shift+P" if A else "Write the full paper (Word + EndNote) — Ctrl+Shift+P")
        self.a_q_images = self._act("🖼  " + ("تحسين الصور" if A else "Improve images"), self.open_images_tab, "Ctrl+Shift+I",
                                    tip="تحسين صور البحث: الجودة والدقة و dpi" if A else "Research images: quality, resolution and dpi")
        self.a_q_comment = self._act("📝  " + ("تعليق احترافي" if A else "Pro comment"), self.quick_comment, "Ctrl+Shift+C",
                                     tip="تعليق هستوباثولوجي احترافي ووصف الصورة (بعد قراءة الصورة)" if A
                                     else "Professional histopathology comment and figure legend (after reading the image)")
        self.a_q_batch = self._act("🗂  " + ("تقرير هستو لمجلد صور…" if A else "Histopathology report for a folder…"), self.quick_batch)
        self.a_q_cong = self._act("🩸  " + ("تعليم الاحتقان بالفرشاة…" if A else "Teach congestion (brush)…"), self.quick_congestion)
        self.a_q_expert = QAction("🛠  " + ("وضع الخبير" if A else "Expert mode"), self)
        self.a_q_expert.setCheckable(True); self.a_q_expert.setChecked(bool(SETTINGS.expert_mode))
        self.a_q_expert.toggled.connect(self.set_expert_mode)
        self.a_tmpl = self._act("🧪  " + ("قوالب دراسات الأدوية والسموم…" if A else "Pharmacology / toxicology study templates…"), self.study_templates)

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu(tr("file"))
        for a in (self.a_new, self.a_open, self.a_paste, self.a_save):
            m.addAction(a)
        m.addSeparator()
        for a in (self.a_popen, self.a_psave, self.a_rerun):
            m.addAction(a)
        sm = m.addMenu("🧪  " + tr("samples"))
        for name in make_sample_datasets():
            sm.addAction(name, lambda n=name: (self.load_df(make_sample_datasets()[n], n), self.import_assistant([])))
        m.addSeparator(); m.addAction(self.a_word); m.addAction(self.a_excel); m.addAction(self.a_html)
        m.addSeparator(); m.addAction(self._act(tr("exit"), self.close, "Ctrl+Q"))
        d = mb.addMenu(tr("data"))
        d.addAction(self._act("ƒ  " + tr("compute"), self.compute_var))
        d.addAction(self._act("⤳  " + tr("transform"), self.transform_var))
        d.addAction(self._act("▤  " + tr("recode"), self.recode_var))
        d.addAction(self._act("⧩  " + tr("filter"), self.filter_cases))
        d.addAction(self._act("↺  " + tr("reset_filter"), self.reset_filter))
        d.addAction(self._act("⇅  " + tr("wide_long"), self.wide_to_long))
        d.addSeparator()
        d.addAction(self._act(tr("add_row"), self.add_row)); d.addAction(self._act(tr("del_row"), self.del_rows))
        d.addAction(self._act(tr("add_col"), self.add_col)); d.addAction(self._act(tr("del_col"), self.del_col))
        a = mb.addMenu(tr("analyze"))
        a.addAction(self.a_smart); a.addAction(self.a_assist); a.addAction(self.a_wizard); a.addAction(self.a_recs)
        a.addSeparator()
        for cid, en, ar in CATEGORIES:
            sub = a.addMenu(ar if SETTINGS.language == "ar" else en)
            for aid, an in REGISTRY.items():
                if an.category == cid:
                    sub.addAction(lbl(an), lambda x=aid: self.open_analysis(x))
        o = mb.addMenu(tr("output"))
        for x in (self.a_word, self.a_excel, self.a_html, self.a_clear):
            o.addAction(x)
        o.addAction(self._act("🎨  " + tr("restyle"), self.restyle_all))
        o.addAction(self._act("🖼  " + tr("export_all_figs"), self.export_all_figs))
        p = mb.addMenu("📰  " + ("النشر" if SETTINGS.language == "ar" else "Publish"))
        for x in (self.a_journal, self.a_paper, self.a_ms, self.a_rev, self.a_panel):
            p.addAction(x)
        t = mb.addMenu("🧰  " + ("أدوات" if SETTINGS.language == "ar" else "Tools"))
        for x in (self.a_tmpl, self.a_animal):
            t.addAction(x)
        t.addSeparator()
        t.addAction(self._act("🧬  " + ("كاشف الصور المكررة والمعاد استخدامها…" if SETTINGS.language == "ar"
                                        else "Duplicate / re-used image detector…"), self.duplicate_detector))
        t.addSeparator()
        t.addAction(self._act("Ⓡ  " + ("تحقق من آخر تحليل في R…" if SETTINGS.language == "ar" else "Verify last analysis in R…"),
                              self.verify_in_r))
        t.addAction(self._act("Ⓡ  " + ("وحدة R (تشغيل كود R على البيانات)…" if SETTINGS.language == "ar" else "R console (run R code on the data)…"),
                              self.r_console))
        v = mb.addMenu(tr("view"))
        v.addAction(self.a_settings); v.addAction(self.a_lang)
        h = mb.addMenu(tr("help"))
        h.addAction(self._act("✔  " + tr("validation"), self.show_validation))
        h.addAction(self._act("⬆  " + ("البحث عن تحديثات…" if SETTINGS.language == "ar" else "Check for updates…"),
                              lambda: self.check_updates(silent=False)))
        h.addAction(self._act("ℹ  " + tr("about"), self.about))

    def _build_toolbar(self):
        tb = QToolBar("main"); tb.setMovable(False); tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(tb)
        tb.addAction(self.a_smart)
        tb.widgetForAction(self.a_smart).setObjectName("primary")
        tb.addAction(self.a_assist)
        tb.addAction(self.a_wizard)
        tb.addAction(self.a_recs)
        tb.addSeparator()
        for a in (self.a_q_paper, self.a_q_images, self.a_q_comment):
            tb.addAction(a)
        A = SETTINGS.language == "ar"
        more = QToolButton(); more.setText("✨  " + ("الجديد" if A else "New tools")); more.setPopupMode(QToolButton.InstantPopup)
        more.setToolTip("كل الإضافات الأخيرة في مكان واحد" if A else "All the latest additions in one place")
        mm = QMenu(more)
        for a in (self.a_q_paper, self.a_q_images, self.a_q_comment, self.a_q_batch, self.a_q_cong):
            mm.addAction(a)
        mm.addSeparator(); mm.addAction(self.a_q_expert)
        more.setMenu(mm); tb.addWidget(more); self._new_menu_btn = more
        # second row: output, settings and language (the first row is full, and these used to hide in the » overflow)
        self.addToolBarBreak()
        tb2 = QToolBar("output"); tb2.setMovable(False); tb2.setIconSize(QSize(18, 18))
        tb2.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(tb2)
        for a in (self.a_open, self.a_paste, self.a_save, self.a_psave):
            tb2.addAction(a)
        tb2.addSeparator()
        for a in (self.a_word, self.a_ms, self.a_excel):
            tb2.addAction(a)
        tb2.addSeparator()
        for a in (self.a_settings, self.a_lang):
            tb2.addAction(a)

    def _build_sidebar(self):
        w = QWidget(); w.setObjectName("sidebar")
        lay = QVBoxLayout(w); lay.setContentsMargins(8, 6, 8, 8)
        b = QLabel("MedStatix<span style='color:#2BC4CF'> Pro</span>"); b.setObjectName("brand"); b.setTextFormat(Qt.RichText)
        lay.addWidget(b)
        t = QLabel(tr("app_tagline")); t.setObjectName("tagline"); t.setWordWrap(True); lay.addWidget(t)
        self.search = QLineEdit(); self.search.setObjectName("navsearch"); self.search.setPlaceholderText("🔍  " + tr("search"))
        self.search.textChanged.connect(self.filter_nav)
        lay.addWidget(self.search)
        self.nav = QTreeWidget(); self.nav.setObjectName("nav"); self.nav.setHeaderHidden(True)
        self.nav.setIndentation(14)
        top = QTreeWidgetItem(["🧠  " + tr("smart")]); top.setData(0, Qt.UserRole, "__smart__")
        wiz = QTreeWidgetItem(["🧭  " + tr("wizard")]); wiz.setData(0, Qt.UserRole, "__wizard__")
        self.nav.addTopLevelItem(top); self.nav.addTopLevelItem(wiz)
        icons = {"describe": "📋", "compare": "⚖", "repeated": "⏱", "categorical": "▦", "correlation": "↗", "regression": "📈",
                 "survival": "⛑", "diagnostic": "🎯", "agreement": "🤝", "pharmtox": "💊", "multivariate": "🧬", "meta": "🌲", "power": "🔢"}
        for cid, en, ar in CATEGORIES:
            it = QTreeWidgetItem([f"{icons.get(cid, '•')}  " + (ar if SETTINGS.language == "ar" else en)])
            f = it.font(0); f.setBold(True); it.setFont(0, f)
            for aid, an in REGISTRY.items():
                if an.category == cid:
                    ch = QTreeWidgetItem([lbl(an)]); ch.setData(0, Qt.UserRole, aid)
                    ch.setToolTip(0, an.desc_ar if SETTINGS.language == "ar" else an.desc_en)
                    it.addChild(ch)
            self.nav.addTopLevelItem(it)
        self.nav.itemActivated.connect(self._nav_clicked)
        self.nav.itemClicked.connect(self._nav_clicked)
        lay.addWidget(self.nav, 1)
        w.setMinimumWidth(260)
        return w

    def filter_nav(self, text):
        text = text.strip().lower()
        for i in range(self.nav.topLevelItemCount()):
            top = self.nav.topLevelItem(i)
            any_vis = False
            for j in range(top.childCount()):
                ch = top.child(j)
                an = REGISTRY.get(ch.data(0, Qt.UserRole))
                hay = (an.en + " " + an.ar + " " + an.desc_en).lower() if an else ch.text(0).lower()
                vis = not text or text in hay
                ch.setHidden(not vis)
                any_vis |= vis
            top.setHidden(bool(text) and top.childCount() > 0 and not any_vis)
            top.setExpanded(bool(text) and any_vis)

    def _nav_clicked(self, item, _col=0):
        aid = item.data(0, Qt.UserRole)
        if aid == "__smart__":
            self.smart_analyze()
        elif aid == "__wizard__":
            self.wizard()
        elif aid:
            self.open_analysis(aid)
        else:
            item.setExpanded(not item.isExpanded())

    def _build_data_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(4, 4, 4, 4)
        self.data_info = QLabel(); self.data_info.setObjectName("hint")
        lay.addWidget(self.data_info)
        self.model = PandasModel(self.df)
        self.model.edited.connect(self.refresh_vars)
        self.table = QTableView(); self.table.setModel(self.model); self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(110)
        self.table.verticalHeader().setDefaultSectionSize(24)
        lay.addWidget(self.table)
        return w

    def _build_vars_tab(self):
        self.vars_model = PandasModel(pd.DataFrame())
        v = QTableView(); v.setModel(self.vars_model); v.setEditTriggers(QAbstractItemView.NoEditTriggers)
        v.horizontalHeader().setStretchLastSection(True); v.setAlternatingRowColors(True)
        v.doubleClicked.connect(self._rename_var)
        self.vars_view = v
        return v

    def _build_output_tab(self):
        A = SETTINGS.language == "ar"
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(2, 2, 2, 2)
        bar = QHBoxLayout()
        b1 = QPushButton("📝  " + ("تعديل التعليقات (Captions)" if A else "Edit captions")); b1.clicked.connect(self.edit_captions)
        b2 = QPushButton("✏️  " + ("محرر الرسم (نمط Prism)" if A else "Figure editor (Prism style)")); b2.setObjectName("primary")
        b2.clicked.connect(lambda: (self.tabs.setCurrentIndex(3), self.edit_current_fig()))
        b3 = QPushButton("💾  " + ("حفظ كل الرسوم…" if A else "Save all figures…")); b3.clicked.connect(self.export_all_figs)
        for b in (b2, b1, b3):
            bar.addWidget(b)
        bar.addStretch(1)
        v.addLayout(bar)
        self.out = QTextBrowser(); self.out.setOpenExternalLinks(True)
        v.addWidget(self.out, 1)
        return w

    def _build_fig_tab(self):
        w = QWidget(); lay = QHBoxLayout(w)
        self.fig_list = QListWidget(); self.fig_list.setViewMode(QListView.IconMode); self.fig_list.setIconSize(QSize(150, 115))
        self.fig_list.setResizeMode(QListView.Adjust); self.fig_list.setFixedWidth(190); self.fig_list.setSpacing(6)
        self.fig_list.setFlow(QListView.TopToBottom); self.fig_list.setWrapping(False)
        self.fig_list.currentRowChanged.connect(self.show_figure)
        lay.addWidget(self.fig_list)
        self.canvas_box = QVBoxLayout()
        cw = QWidget(); cw.setLayout(self.canvas_box)
        lay.addWidget(cw, 1)
        panel = QGroupBox(tr("tab_figs")); f = QFormLayout(panel)
        A = SETTINGS.language == "ar"
        be = QPushButton("✏️  " + ("محرر الرسم الاحترافي (Prism)" if A else "Full figure editor (Prism)")); be.setObjectName("primary")
        be.setToolTip("نوع الرسم، الألوان، النقاط، الخطوط، المحاور، علامات الدلالة، التعليق" if A else
                      "Chart type, colours, points, fonts, axes, significance marks, caption")
        be.clicked.connect(self.edit_current_fig); f.addRow(be)
        self.e_title, self.e_x, self.e_y = QLineEdit(), QLineEdit(), QLineEdit()
        self.e_ymin, self.e_ymax = QLineEdit(), QLineEdit()
        for k, wdg in [("fig_title", self.e_title), ("fig_x", self.e_x), ("fig_y", self.e_y), ("fig_ymin", self.e_ymin), ("fig_ymax", self.e_ymax)]:
            f.addRow(tr(k), wdg)
        b = QPushButton(tr("apply")); b.setObjectName("primary"); b.clicked.connect(self.apply_fig_edits); f.addRow(b)
        self.q_pal = combo(__import__("medstatix.plots.figures", fromlist=["PALETTES"]).PALETTES, SETTINGS.palette)
        self.q_style = combo(__import__("medstatix.plots.figures", fromlist=["FIG_STYLES"]).FIG_STYLES, SETTINGS.fig_style)
        self.q_plot = combo(__import__("medstatix.plots.figures", fromlist=["GROUP_PLOT_TYPES"]).GROUP_PLOT_TYPES, SETTINGS.group_plot)
        self.q_err = combo(["SD", "SEM", "95% CI"], SETTINGS.error_bar)
        f.addRow(tr("palette"), self.q_pal); f.addRow(tr("style"), self.q_style); f.addRow(tr("plot_type"), self.q_plot); f.addRow(tr("error_bar"), self.q_err)
        b2 = QPushButton("🎨  " + tr("restyle")); b2.clicked.connect(self.quick_restyle); f.addRow(b2)
        b3 = QPushButton("🖼  " + tr("export_fig")); b3.setObjectName("primary"); b3.clicked.connect(self.export_current_fig); f.addRow(b3)
        b4 = QPushButton(tr("export_all_figs")); b4.clicked.connect(self.export_all_figs); f.addRow(b4)
        panel.setFixedWidth(300)
        lay.addWidget(panel)
        return w

    def _histo_result(self, res):
        self.entries.append({"result": res, "aid": "__histo__", "kwargs": {}, "df": None})
        self.refresh_output(scroll_end=True); self.refresh_fig_list(); self.tabs.setCurrentIndex(2)

    def _histo_rows(self, rows):
        if self.dataset_name == "Histology measurements":
            self.df = pd.concat([self.df, rows], ignore_index=True)
            self.model.set_df(self.df); self.refresh_vars()
        else:
            self.load_df(rows, "Histology measurements")
            self.tabs.setCurrentIndex(4)
        self.statusBar().showMessage(f"Histology measurements: {len(self.df)} rows", 5000)

    # ------------------------------------------------------------------ data
    def load_df(self, df, name=""):
        self.df = df.copy()
        self.df_full = None
        self.dataset_name = name
        self.model.set_df(self.df)
        self.refresh_vars()
        self.tabs.setCurrentIndex(0)

    def refresh_vars(self):
        self.df = self.model.df()
        self.vars_model.set_df(variables_frame(self.df) if not self.df.empty else pd.DataFrame())
        flt = " (filtered)" if self.df_full is not None else ""
        self.data_info.setText(f"<b>{self.dataset_name}</b>{flt} — " + tr("rows_cols", r=len(self.df), c=self.df.shape[1]))

    def open_file(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, tr("open"), "", IMPORT_FILTER)
        if not path:
            return
        A = SETTINGS.language == "ar"
        ext = os.path.splitext(path)[1].lower()
        if ext == ".msx":
            self.open_project(path); return
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            if ext in (".xlsx", ".xlsm", ".xls"):
                sheets = SI.sheet_names(path)
                sheet = sheets[0] if sheets else 0
                if len(sheets) > 1:
                    QApplication.restoreOverrideCursor()
                    sizes = {}
                    for sh in sheets:
                        try:
                            sizes[sh] = int(pd.read_excel(path, sheet_name=sh, header=None).notna().to_numpy().sum())
                        except Exception:
                            sizes[sh] = 0
                    best = max(sheets, key=lambda x: sizes[x])
                    items = [f"{sh}   ({sizes[sh]} " + ("خلية" if A else "cells") + ")" for sh in sheets]
                    it, ok = QInputDialog.getItem(self, "Excel", "اختر ورقة البيانات (Sheet):" if A else "Choose the data sheet:",
                                                  items, sheets.index(best), False)
                    if not ok:
                        return
                    sheet = sheets[items.index(it)]
                    QApplication.setOverrideCursor(Qt.WaitCursor)
                df, report = SI.smart_read_excel(path, sheet)
            elif ext in (".csv", ".txt", ".tsv"):
                df, report = SI.smart_read_csv(path)
            elif ext == ".pzfx":
                from ..core.pzfx import list_tables, read_pzfx
                tabs = list_tables(path); idx = 0
                if len(tabs) > 1:
                    QApplication.restoreOverrideCursor()
                    items = [f"{t[1]}  ({t[2]})" for t in tabs]
                    it, ok = QInputDialog.getItem(self, "Prism", "اختر جدول البيانات:" if A else "Choose the data table:", items, 0, False)
                    if not ok:
                        return
                    idx = items.index(it); QApplication.setOverrideCursor(Qt.WaitCursor)
                df, _ = read_pzfx(path, idx); report = []
            else:
                df, _ = load_file(path)
                report = []
            QApplication.restoreOverrideCursor()
            if df.empty:
                raise AnalysisError("No data table was found in this file.", "لم يتم العثور على جدول بيانات في هذا الملف.")
            self.load_df(df, os.path.basename(path))
            self.import_assistant(report)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.show_error(e)

    def show_error(self, e):
        msg, details = friendly(e)
        box = QMessageBox(QMessageBox.Warning, tr("error"), msg, parent=self)
        box.setDetailedText(details)
        from PySide6.QtWidgets import QSpacerItem, QSizePolicy
        lay = box.layout()
        lay.addItem(QSpacerItem(520, 0, QSizePolicy.Minimum, QSizePolicy.Expanding), lay.rowCount(), 0, 1, lay.columnCount())
        for b in box.buttons():
            if box.buttonRole(b) == QMessageBox.ActionRole:
                b.setText("التفاصيل الفنية…" if SETTINGS.language == "ar" else "Technical details…")
        box.exec()

    def import_assistant(self, report):
        dlg = ImportAssistant(self.df, report, self.dataset_name, self)
        dlg.exec()
        c = dlg.choice
        if not c:
            return
        if c[0] == "to_groups":
            title = self.df.attrs.get("title") or "Value"
            self.load_df(SI.columns_to_groups(self.df, value_name=title), self.dataset_name)
            self.import_assistant([{"en": "Columns were converted to a Group / Value table.",
                                    "ar": "تم تحويل الأعمدة إلى جدول (المجموعة / القيمة).", "level": "info"}])
        elif c[0] == "rec":
            kind = c[1]
            if kind == "smart":
                self.run_smart(c[2], c[3])
            elif kind == "run":
                self.execute(c[2], {k: v for k, v in c[3].items() if v is not None})
            else:
                self.open_analysis(c[2], {k: v for k, v in c[3].items() if v is not None})
        elif c[0] == "smart_all":
            self.run_smart(c[2], c[1])
        elif c[0] == "describe":
            self.execute("descriptives", {"variables": c[2], "group": c[1]} if c[1] else {"variables": c[2]})
        elif c[0] == "corr":
            self.execute("correlation", {"variables": c[1]})
        elif c[0] == "repeated":
            aid = "ttest_paired" if len(c[1]) == 2 else "rmanova"
            preset = {"var1": c[1][0], "var2": c[1][1]} if aid == "ttest_paired" else {"measures": c[1]}
            self.open_analysis(aid, preset)

    def save_file(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("save"), self.dataset_name.rsplit(".", 1)[0] or "data",
                                              "Excel (*.xlsx);;CSV (*.csv);;SPSS (*.sav);;GraphPad Prism (*.pzfx);;Stata (*.dta)")
        if path:
            try:
                save_file(self.model.df(), path)
                self.statusBar().showMessage(path, 5000)
            except Exception as e:
                QMessageBox.critical(self, tr("error"), str(e))

    def new_data(self):
        self.load_df(pd.DataFrame({"V1": [np.nan] * 20, "V2": [np.nan] * 20}), "Untitled")

    def paste_data(self):
        text = QApplication.clipboard().text()
        if not text.strip():
            return
        try:
            grid = pd.read_csv(io.StringIO(text), sep="\t" if "\t" in text else None, engine="python", header=None, dtype=object)
            df, report = SI.tidy_grid(grid)
            self.load_df(df, "Pasted data")
            self.import_assistant(report)
        except Exception as e:
            self.show_error(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            self.open_file(u.toLocalFile())
            break

    def _cols_combo(self, numeric_only=False):
        return combo([c for c in self.df.columns if not numeric_only or is_numeric(self.df[c])])

    def compute_var(self):
        name = QLineEdit("new_var"); expr = QLineEdit()
        dlg = FormDialog(tr("compute"), [("name", tr("new_name"), name), ("expr", tr("expression"), expr)], self, tr("expr_help"))
        if dlg.exec():
            ns = {c: self.df[c] for c in self.df.columns}
            ns.update({"log": np.log, "ln": np.log, "log10": np.log10, "sqrt": np.sqrt, "exp": np.exp, "abs": np.abs,
                       "mean": lambda *a: pd.concat(a, axis=1).mean(1), "where": np.where, "np": np})
            try:
                val = eval(expr.text(), {"__builtins__": {}}, ns)  # user's own expression on their own data
                self.df[name.text()] = val
                self.model.set_df(self.df); self.refresh_vars()
            except Exception as e:
                QMessageBox.critical(self, tr("error"), str(e))

    def transform_var(self):
        var = self._cols_combo(True)
        meth = combo(["log10", "ln", "sqrt", "z-score", "rank", "reciprocal (1/x)", "square"])
        dlg = FormDialog(tr("transform"), [("var", tr("variable"), var), ("m", tr("method"), meth)], self)
        if dlg.exec():
            v, m = var.currentText(), meth.currentText()
            x = pd.to_numeric(self.df[v], errors="coerce")
            fn = {"log10": np.log10, "ln": np.log, "sqrt": np.sqrt, "z-score": lambda s: (s - s.mean()) / s.std(),
                  "rank": lambda s: s.rank(), "reciprocal (1/x)": lambda s: 1 / s, "square": lambda s: s ** 2}[m]
            self.df[f"{m.split(' ')[0]}_{v}"] = fn(x)
            self.model.set_df(self.df); self.refresh_vars()

    def recode_var(self):
        var = self._cols_combo(True); cuts = QLineEdit(); labs = QLineEdit()
        dlg = FormDialog(tr("recode"), [("v", tr("variable"), var), ("c", tr("cutoffs"), cuts), ("l", tr("labels"), labs)], self)
        if dlg.exec():
            try:
                c = [float(x) for x in cuts.text().split(",") if x.strip()]
                bins = [-np.inf] + c + [np.inf]
                labels = [x.strip() for x in labs.text().split(",")] if labs.text().strip() else None
                self.df[f"{var.currentText()}_grp"] = pd.cut(pd.to_numeric(self.df[var.currentText()], errors="coerce"), bins,
                                                             labels=labels, right=False).astype(str).replace("nan", np.nan)
                self.model.set_df(self.df); self.refresh_vars()
            except Exception as e:
                QMessageBox.critical(self, tr("error"), str(e))

    def filter_cases(self):
        cond, ok = QInputDialog.getText(self, tr("filter"), tr("condition"))
        if ok and cond.strip():
            try:
                full = self.df_full if self.df_full is not None else self.df
                sub = full.query(cond, engine="python").reset_index(drop=True)
                self.df_full = full
                self.df = sub
                self.model.set_df(self.df); self.refresh_vars()
            except Exception as e:
                QMessageBox.critical(self, tr("error"), str(e))

    def reset_filter(self):
        if self.df_full is not None:
            self.df = self.df_full; self.df_full = None
            self.model.set_df(self.df); self.refresh_vars()

    def wide_to_long(self):
        idv = self._cols_combo(); meas = VarList(list(self.df.columns))
        dlg = FormDialog(tr("wide_long"), [("id", tr("id_var"), idv), ("m", tr("measures"), meas)], self)
        if dlg.exec() and meas.values():
            keep = [c for c in self.df.columns if c not in meas.values()]
            long = self.df.melt(id_vars=keep, value_vars=meas.values(), var_name="time", value_name="value")
            self.load_df(long, self.dataset_name + " (long)")

    def add_row(self):
        self.df.loc[len(self.df)] = [np.nan] * self.df.shape[1]
        self.model.set_df(self.df); self.refresh_vars()

    def del_rows(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if rows:
            self.df = self.df.drop(self.df.index[rows]).reset_index(drop=True)
            self.model.set_df(self.df); self.refresh_vars()

    def add_col(self):
        name, ok = QInputDialog.getText(self, tr("add_col"), tr("new_name"))
        if ok and name:
            self.df[name] = np.nan
            self.model.set_df(self.df); self.refresh_vars()

    def del_col(self):
        name, ok = QInputDialog.getItem(self, tr("del_col"), tr("variable"), list(map(str, self.df.columns)), 0, False)
        if ok:
            self.df = self.df.drop(columns=[name])
            self.model.set_df(self.df); self.refresh_vars()

    def _rename_var(self, index):
        old = self.df.columns[index.row()]
        new, ok = QInputDialog.getText(self, tr("name"), tr("new_name"), text=str(old))
        if ok and new and new != old:
            self.df = self.df.rename(columns={old: new})
            self.model.set_df(self.df); self.refresh_vars()

    # ------------------------------------------------------------------ analyses
    def _need_data(self, aid=None):
        if aid and not REGISTRY[aid].needs_data:
            return True
        if self.df.empty:
            QMessageBox.information(self, APP_NAME, tr("no_data"))
            return False
        return True

    def open_analysis(self, aid, preset=None):
        if not self._need_data(aid):
            return
        an = REGISTRY[aid]
        dlg = AnalysisDialog(aid, self.df if an.needs_data else None, self, preset)
        if dlg.exec():
            self.execute(aid, dlg.values())

    def execute(self, aid, kwargs):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            optional = {p.name for p in REGISTRY[aid].params if p.optional}
            kw = {k: v for k, v in kwargs.items() if not (k in optional and (v is None or v == []))}
            df = self.df.copy()
            if SETTINGS.auto_fallback:
                from ..core.fallback import run_with_fallback, suggest
                results = run_with_fallback(aid, df, kw, run)
                self.entries.append({"result": results[0], "aid": aid, "kwargs": kw, "df": df})
                if len(results) > 1:
                    aid2, kw2 = suggest(aid, df, kw)[:2]
                    self.entries.append({"result": results[1], "aid": aid2, "kwargs": kw2, "df": df})
            else:
                self.entries.append({"result": run(aid, df, **kw), "aid": aid, "kwargs": kw, "df": df})
            self.after_result()
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.show_error(e); return
        QApplication.restoreOverrideCursor()

    def after_result(self):
        self.refresh_output(scroll_end=True)
        self.refresh_fig_list()
        self.tabs.setCurrentIndex(2)
        self.statusBar().showMessage(tr("done"), 4000)

    def smart_analyze(self):
        if not self._need_data():
            return
        dlg = SmartDialog(self.df, self)
        if dlg.exec():
            o, f = dlg.values()
            self.run_smart(dlg.outcomes(), f)

    def run_smart(self, outcomes, factor):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        errors, done = [], 0
        for o in outcomes:
            try:
                res, aid = auto_analyze(self.df.copy(), o, factor)
                self.entries.append({"result": res, "aid": "__smart__", "kwargs": {"outcome": o, "factor": factor}, "df": self.df.copy()})
                done += 1
            except Exception as e:
                errors.append((o, e))
        if len(outcomes) >= 2 and factor:
            try:   # several markers compared across the same groups: add the one-table summary journals ask for
                from ..analyses import run as _run
                from ..core.data import var_kind
                nums = [o for o in outcomes if var_kind(self.df[o]) == "continuous"]
                if len(nums) >= 2 and var_kind(self.df[factor]) in ("categorical", "binary"):
                    kw = {"variables": nums, "group": factor}
                    self.entries.append({"result": _run("journal_table", self.df.copy(), **kw), "aid": "journal_table",
                                         "kwargs": kw, "df": self.df.copy()})
                    done += 1
            except Exception as e:
                errors.append(("summary table", e))
        QApplication.restoreOverrideCursor()
        if done:
            self.after_result()
        if errors:
            if len(errors) == 1 and not done:
                self.show_error(errors[0][1])
            else:
                msg = "\n".join(f"• {o}: {friendly(e)[0]}" for o, e in errors)
                QMessageBox.warning(self, tr("error"), msg)

    def wizard(self):
        dlg = WizardDialog(self)
        if dlg.exec() and dlg.choice:
            self.open_analysis(dlg.choice)

    # ------------------------------------------------------------------ output rendering
    def _png(self, fig, dpi=160):
        key = id(fig)
        if key not in self.png_cache:
            self.png_cache[key] = fig_to_png_bytes(fig, dpi=dpi)
        return self.png_cache[key]

    def refresh_output(self, scroll_end=False):
        doc = QTextDocument()
        doc.setDefaultStyleSheet(output_css(SETTINGS.theme))
        ids = {}
        for e in self.entries:
            for b in e["result"].figures:
                url = f"fig://{id(b.content)}"
                img = QImage.fromData(QByteArray(self._png(b.content)))
                doc.addResource(QTextDocument.ImageResource, QUrl(url), img)
                ids[id(b.content)] = url
        if self.entries:
            cnt = {"t": 0, "f": 0}
            body = "".join(e["result"].to_html(fig_ids=ids, counters=cnt) for e in self.entries)
        else:
            body = self._welcome_html()
        doc.setHtml(f"<html><body>{body}</body></html>")
        self.out.setDocument(doc)
        if scroll_end and self.entries:
            # scroll to the beginning of the latest result
            self.out.scrollToAnchor("last")
            sb = self.out.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _welcome_html(self):
        ar = SETTINGS.language == "ar"
        n = len(REGISTRY)
        if ar:
            return (f"<div dir='rtl'><h2>مرحبًا بك في MedStatix Pro</h2><p>منصة متكاملة للإحصاء الحيوي الطبي والصيدلي تضم <b>{n} تحليلًا</b> "
                    "تم التحقق من دقتها مقابل R وSPSS وmetafor.</p><ul>"
                    "<li><b>🧠 التحليل الذكي:</b> اختر المتغيرات فقط، ويحدد البرنامج الاختبار الصحيح بعد فحص الافتراضات ويفسّر النتيجة.</li>"
                    "<li><b>🧭 أي اختبار أستخدم؟</b> معالج أسئلة يرشدك حسب تصميم الدراسة.</li>"
                    "<li><b>🎨 استوديو الرسوم:</b> أنماط GraphPad Prism وألوان مجلات Nature وLancet وNEJM وJAMA، وتصدير TIFF/PNG/SVG/PDF بدقة 600–1200 dpi.</li>"
                    "<li><b>📝 تصدير Word وExcel:</b> جداول بنمط APA ونص Methods/Results جاهز للنشر.</li></ul>"
                    "<p>تم تحميل بيانات تجربة سريرية نموذجية للتجربة. ابدأ من القائمة الجانبية.</p></div>")
        return (f"<h2>Welcome to MedStatix Pro</h2><p>An integrated medical & pharmaceutical biostatistics platform with <b>{n} analyses</b>, "
                "validated against R, SPSS and metafor reference values.</p><ul>"
                "<li><b>🧠 Smart Analyze:</b> pick variables; assumptions are checked, the correct test is chosen, run and interpreted.</li>"
                "<li><b>🧭 Which test?</b> a design-based decision wizard.</li>"
                "<li><b>🎨 Figures studio:</b> Prism-style plots, Nature/Lancet/NEJM/JAMA palettes, TIFF/PNG/SVG/PDF export at 600–1200 dpi.</li>"
                "<li><b>📝 Word & Excel export:</b> APA tables plus ready-to-paste Methods/Results text.</li></ul>"
                "<p>A simulated clinical-trial dataset is loaded so you can try everything immediately.</p>")

    def clear_output(self):
        self.entries.clear(); self.png_cache.clear()
        self.refresh_output(); self.refresh_fig_list()

    # ------------------------------------------------------------------ figures studio
    def all_figs(self):
        out = []
        for ei, e in enumerate(self.entries):
            for fi, b in enumerate(e["result"].figures):
                out.append((ei, fi, b))
        return out

    def refresh_fig_list(self):
        if not hasattr(self, "fig_list"):
            return
        self.fig_list.blockSignals(True)
        self.fig_list.clear()
        for ei, fi, b in self.all_figs():
            pm = QPixmap(); pm.loadFromData(self._png(b.content))
            it = QListWidgetItem(QIcon(pm), f"{ei+1}.{fi+1} {self.entries[ei]['result'].title[:22]}")
            self.fig_list.addItem(it)
        self.fig_list.blockSignals(False)
        if self.fig_list.count():
            self.fig_list.setCurrentRow(self.fig_list.count() - 1)
            self.show_figure(self.fig_list.count() - 1)

    def show_figure(self, row):
        while self.canvas_box.count():
            w = self.canvas_box.takeAt(0).widget()
            if w:
                w.setParent(None)
        figs = self.all_figs()
        if row < 0 or row >= len(figs):
            self.current_fig = None
            return
        fig = figs[row][2].content
        self.current_fig = (row, fig)
        canvas = FigureCanvasQTAgg(fig)
        self.canvas_box.addWidget(NavigationToolbar2QT(canvas, self))
        self.canvas_box.addWidget(canvas, 1)
        canvas.draw()
        ax = fig.axes[0] if fig.axes else None
        if ax:
            self.e_title.setText(ax.get_title()); self.e_x.setText(ax.get_xlabel()); self.e_y.setText(ax.get_ylabel())
            lo, hi = ax.get_ylim(); self.e_ymin.setText(f"{lo:.4g}"); self.e_ymax.setText(f"{hi:.4g}")

    def apply_fig_edits(self):
        if not self.current_fig:
            return
        row, fig = self.current_fig
        spec = getattr(fig, "_mx_spec", None)
        if spec is not None:
            spec = spec.copy()
            spec.title, spec.xlabel, spec.ylabel = self.e_title.text(), self.e_x.text(), self.e_y.text()
            try:
                spec.y_min, spec.y_max = float(self.e_ymin.text()), float(self.e_ymax.text())
            except ValueError:
                pass
            self._replace_fig(row, spec)
            return
        ax = fig.axes[0]
        ax.set_title(self.e_title.text()); ax.set_xlabel(self.e_x.text()); ax.set_ylabel(self.e_y.text())
        try:
            ax.set_ylim(float(self.e_ymin.text()), float(self.e_ymax.text()))
        except ValueError:
            pass
        fig.canvas.draw()
        self.png_cache.pop(id(fig), None)
        self.refresh_output()

    def _replace_fig(self, row, spec, caption=None):
        from ..plots.groupfig import render, caption_for
        ei, fi, b = self.all_figs()[row]
        self.png_cache.pop(id(b.content), None)
        b.content = render(spec)
        b.caption = caption or caption_for(spec)
        self.entries[ei].setdefault("edited", {})[fi] = spec
        self.refresh_output()
        self.refresh_fig_list()
        if 0 <= row < self.fig_list.count():
            self.fig_list.setCurrentRow(row)

    def edit_current_fig(self):
        A = SETTINGS.language == "ar"
        if not self.current_fig:
            QMessageBox.information(self, APP_NAME, "لا توجد رسوم بعد. شغّل تحليلًا أولًا." if A else "No figure yet. Run an analysis first.")
            return
        row, fig = self.current_fig
        spec = getattr(fig, "_mx_spec", None)
        if spec is None:
            QMessageBox.information(self, APP_NAME,
                                    "المحرر الكامل متاح لرسوم مقارنة المجموعات. لهذا الرسم استخدم الحقول الجانبية والألوان العامة."
                                    if A else "The full editor is available for group-comparison figures. For this figure use the side panel.")
            return
        from .figeditor import FigureEditorDialog
        dlg = FigureEditorDialog(spec, self)
        if dlg.exec():
            _fig, cap = dlg.final()
            self._replace_fig(row, dlg.spec, cap)

    def edit_captions(self):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTableWidget, QTableWidgetItem
        A = SETTINGS.language == "ar"
        items = []
        t = f = 0
        for e in self.entries:
            for b in e["result"].blocks:
                if b.kind == "table":
                    t += 1; items.append((f"Table {t}", b))
                elif b.kind == "figure":
                    f += 1; items.append((f"Figure {f}", b))
        if not items:
            return
        dlg = QDialog(self); dlg.setWindowTitle("تعديل التعليقات" if A else "Edit captions"); dlg.resize(980, 620)
        v = QVBoxLayout(dlg)
        hint = QLabel("عدّل نص أي تعليق مباشرة (الترقيم تلقائي). تُستخدم التعليقات في النتائج وملفات Word وHTML وExcel."
                      if A else "Edit any caption directly (numbering is automatic). Captions are used in Results and in Word/HTML/Excel exports.")
        hint.setWordWrap(True); hint.setObjectName("hint"); v.addWidget(hint)
        tw = QTableWidget(len(items), 2); tw.setHorizontalHeaderLabels(["#", "التعليق" if A else "Caption"])
        tw.horizontalHeader().setStretchLastSection(True); tw.setColumnWidth(0, 90); tw.setWordWrap(True)
        for i, (lab, b) in enumerate(items):
            it = QTableWidgetItem(lab); it.setFlags(Qt.ItemIsEnabled); tw.setItem(i, 0, it)
            tw.setItem(i, 1, QTableWidgetItem(b.caption))
        tw.resizeRowsToContents()
        v.addWidget(tw, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec():
            for i, (lab, b) in enumerate(items):
                txt = tw.item(i, 1).text().strip()
                if txt != b.caption:
                    b.caption = txt
                    spec = getattr(b.content, "_mx_spec", None) if b.kind == "figure" else None
                    if spec is not None:
                        spec.caption = txt
            self.refresh_output()

    def quick_restyle(self):
        SETTINGS.palette = self.q_pal.currentText(); SETTINGS.fig_style = self.q_style.currentText()
        SETTINGS.group_plot = self.q_plot.currentText(); SETTINGS.error_bar = self.q_err.currentText()
        self._save_settings()
        row = self.fig_list.currentRow()
        self.restyle_all()
        if 0 <= row < self.fig_list.count():
            self.fig_list.setCurrentRow(row)
        self.tabs.setCurrentIndex(3)

    def restyle_all(self):
        self.rerun_entries(use_current_df=False)

    @staticmethod
    def _captions(res):
        return [b.caption for b in res.blocks if b.kind in ("table", "figure")]

    def rerun_entries(self, use_current_df=False):
        """Re-run every analysis (on its own data, or on the current data after it changed), keeping the user's figure
        edits and edited captions. Returns a list of (title, error) for analyses that could not be re-run."""
        from ..plots.groupfig import render, caption_for
        from ..core.project import restyle
        errors = []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for e in self.entries:
                if e["aid"] == "__histo__":
                    continue
                old_caps = self._captions(e["result"]) if e.get("result") is not None else e.get("captions", [])
                if use_current_df:
                    e["df"] = self.df.copy()
                try:
                    if e["aid"] == "__smart__":
                        e["result"], _ = auto_analyze(e["df"], e["kwargs"]["outcome"], e["kwargs"]["factor"])
                    else:
                        e["result"] = run(e["aid"], e["df"], **e["kwargs"])
                except Exception as ex:
                    errors.append((e.get("title") or e["aid"], ex)); continue
                figs = e["result"].figures
                for fi, spec in list((e.get("edited") or {}).items()):
                    if fi < len(figs):
                        new_spec = getattr(figs[fi].content, "_mx_spec", None)
                        spec2 = restyle(new_spec, spec) if (use_current_df and new_spec is not None) else spec
                        e["edited"][fi] = spec2
                        figs[fi].content = render(spec2); figs[fi].caption = spec2.caption or caption_for(spec2)
                caps = e.pop("captions", None) or old_caps
                blocks = [b for b in e["result"].blocks if b.kind in ("table", "figure")]
                if caps and len(caps) == len(blocks):
                    for b, c in zip(blocks, caps):
                        b.caption = c
            self.png_cache.clear()
            self.refresh_output(); self.refresh_fig_list()
        finally:
            QApplication.restoreOverrideCursor()
        return errors

    # ------------------------------------------------------------------ project files
    def _project_state(self):
        st = {"dataset_name": self.dataset_name, "df": self.df, "entries": [], "settings": SETTINGS.as_dict()}
        for e in self.entries:
            item = {"aid": e["aid"], "kwargs": e["kwargs"], "df": e.get("df"), "edited": e.get("edited") or {},
                    "title": e["result"].title, "captions": self._captions(e["result"])}
            if e["aid"] == "__histo__":
                item["html"] = e["result"].to_html(embed_figures=True)
            st["entries"].append(item)
        h = self.histo
        if h.original is not None:
            st["histology"] = {"original": h.original, "name": h.name, "px": h.px.value(),
                               "steps": [{"op": s_["op"], "params": s_["params"]} for s_ in h.steps_done],
                               "quant": {k: v for k, v in (h.last_quant or {}).items() if not isinstance(v, str)}}
        return st

    def save_project(self):
        from ..core.project import save_project
        A = SETTINGS.language == "ar"
        path, _ = QFileDialog.getSaveFileName(self, "حفظ المشروع" if A else "Save project",
                                              getattr(self, "project_path", "") or "MedStatix_project.msx",
                                              "MedStatix project (*.msx)")
        if not path:
            return
        if not path.lower().endswith(".msx"):
            path += ".msx"
        try:
            save_project(path, self._project_state())
        except Exception as e:
            self.show_error(e); return
        self.project_path = path
        self.statusBar().showMessage(("تم حفظ المشروع: " if A else "Project saved: ") + path, 6000)

    def open_project(self, path=None):
        from ..core.project import load_project
        from ..core.result import Result, Block
        A = SETTINGS.language == "ar"
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "فتح مشروع" if A else "Open project", "", "MedStatix project (*.msx)")
        if not path:
            return
        try:
            st = load_project(path)
        except Exception as e:
            self.show_error(e); return
        if st["df"] is not None:
            self.load_df(st["df"], st["dataset_name"] or os.path.basename(path))
        self.entries = []
        for e in st["entries"]:
            if e["aid"] == "__histo__":
                r = Result(e.get("title") or "Histology image report"); r.blocks.append(Block("html", e.get("html") or ""))
                self.entries.append({"result": r, "aid": "__histo__", "kwargs": {}, "df": None})
            else:
                self.entries.append({"result": None, "aid": e["aid"], "kwargs": e["kwargs"], "df": e["df"] if e["df"] is not None else self.df.copy(),
                                     "edited": e["edited"], "captions": e["captions"], "title": e.get("title", "")})
        errors = self.rerun_entries(use_current_df=False)
        self.entries = [e for e in self.entries if e.get("result") is not None]
        h = st.get("histology")
        if h:
            self.histo.load(h["original"], h["name"]); self.histo.px.setValue(float(h.get("px") or 0))
            if h.get("steps"):
                self.histo.set_controls(h["steps"]); self.histo.apply_enhance()
        self.project_path = path
        self.refresh_output(); self.refresh_fig_list()
        self.tabs.setCurrentIndex(2 if self.entries else 0)
        if errors:
            QMessageBox.warning(self, APP_NAME, "\n".join(f"• {t}: {friendly(x)[0]}" for t, x in errors))
        self.statusBar().showMessage(("تم فتح المشروع: " if A else "Project opened: ") + path, 6000)

    def rerun_all_current(self):
        A = SETTINGS.language == "ar"
        if not self.entries:
            return
        if QMessageBox.question(self, APP_NAME, "إعادة تشغيل كل التحليلات على البيانات الحالية؟ ستُحفظ تعديلات الرسوم والتعليقات."
                                if A else "Re-run every analysis on the current data? Figure edits and captions are kept.") != QMessageBox.Yes:
            return
        errors = self.rerun_entries(use_current_df=True)
        if errors:
            QMessageBox.warning(self, APP_NAME, "\n".join(f"• {t}: {friendly(x)[0]}" for t, x in errors))
        self.tabs.setCurrentIndex(2)

    FIG_FILTER = "TIFF 600 dpi (*.tiff);;PNG (*.png);;SVG vector (*.svg);;PDF vector (*.pdf);;EPS (*.eps)"

    def _export_fig_to(self, fig, path, dpi, width_mm):
        h = None
        if width_mm:
            w0, h0 = fig.get_size_inches()
            h = width_mm * h0 / w0
        export_figure(fig, path, dpi, width_mm, h)

    def export_current_fig(self):
        if not self.current_fig:
            return
        from .widgets import ExportOptionsDialog
        dlg = ExportOptionsDialog(self)
        if not dlg.exec():
            return
        ext, dpi, width = dlg.values()
        path, _ = QFileDialog.getSaveFileName(self, tr("export_fig"), f"Figure.{ext}", f"{ext.upper()} (*.{ext})")
        if path:
            if not path.lower().endswith("." + ext) and not (ext == "tiff" and path.lower().endswith(".tif")):
                path += "." + ext
            self._export_fig_to(self.current_fig[1], path, dpi, width)
            self.statusBar().showMessage(path, 5000)

    def export_all_figs(self):
        figs = self.all_figs()
        if not figs:
            return
        from .widgets import ExportOptionsDialog
        dlg = ExportOptionsDialog(self, multiple=True)
        if not dlg.exec():
            return
        ext, dpi, width = dlg.values()
        folder = QFileDialog.getExistingDirectory(self, tr("export_all_figs"))
        if not folder:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for n, (ei, fi, b) in enumerate(figs, 1):
                self._export_fig_to(b.content, os.path.join(folder, f"Figure_{n}.{ext}"), dpi, width)
        finally:
            QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(f"{len(figs)} → {folder}", 6000)

    # ------------------------------------------------------------------ export
    # ------------------------------------------------------------------ publishing & tools (v1.3)
    def _A(self, en, ar):
        return ar if SETTINGS.language == "ar" else en

    def choose_journal(self):
        from .publish import JournalDialog
        dlg = JournalDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        k = dlg.apply(); self._save_settings()
        if k and self.entries and QMessageBox.question(
                self, "", self._A("Redraw the existing figures with the journal's size and font?",
                                  "إعادة رسم الرسوم الحالية بمقاس وخط المجلة؟")) == QMessageBox.Yes:
            self.restyle_all()
        self.statusBar().showMessage(self._A("Journal preset: ", "المجلة: ") + (k or "—"), 6000)

    def _histo_methods(self):
        h = getattr(self, "histo", None)
        if h is None or not getattr(h, "steps_done", None):
            return ""
        from ..imaging import core as IC
        try:
            return IC.EditLog(h.name, h.steps_done).methods_text()
        except Exception:
            return ""

    def write_paper(self):
        if not self.entries:
            QMessageBox.information(self, "", self._A("Run the analyses first (Smart Analyze on your markers).",
                                                      "قم بإجراء التحليلات أولًا (التحليل الذكي على مؤشراتك).")); return
        from .paper_ui import PaperDialog
        from ..report.paper import build_paper
        results = [e["result"] for e in self.entries]
        groups = []
        for res in results:
            for b in res.blocks:
                if b.kind == "results" and isinstance(b.content, dict) and b.content.get("facts"):
                    groups = b.content["facts"].get("levels") or groups
        h = getattr(self, "histo", None); htxt = ""
        if h is not None and getattr(h, "ai", None):
            from ..report import histo_comment as HC
            c = getattr(h, "comment_fields", {})
            htxt = HC.image_comment(h.ai, c.get("organ", ""), c.get("group", ""))
        dlg = PaperDialog(self, groups, htxt, self._histo_methods())
        if dlg.exec() != QDialog.Accepted:
            return
        dlg.remember()
        st = dlg.study()
        name = (st.get("title") or "Paper")[:60].replace("/", "-").replace(":", "")
        path, _ = QFileDialog.getSaveFileName(self, "", f"{name}.docx", "Word (*.docx)")
        if not path:
            return
        if not path.lower().endswith(".docx"):
            path += ".docx"
        from ..report import refs as RF
        from ..report import ai_writer as AW
        from ..report.paper import paper_context
        refs = list(dlg.refs)
        hm, hr = dlg.hmeth.toPlainText().strip(), dlg.histo.toPlainText().strip()
        journal = dlg.journal.currentData() or ""
        markers = [m["label"] for res in results for b in res.blocks
                   if b.kind == "results" and isinstance(b.content, dict) and b.content.get("facts")
                   for m in b.content["facts"].get("markers", [])]
        added = 0
        if dlg.auto_refs.isChecked() and len(refs) < 15:
            try:
                found = self._busy(lambda: RF.auto_references(st, markers), self._A("Searching PubMed for references…",
                                                                                    "جارٍ البحث في PubMed عن المراجع…"))
                keys = {r.key() for r in refs}
                new = [r for r in found if r.key() not in keys]
                refs += new; added = len(new)
                if new:        # keep them for the next paper on the same study
                    dlg.refs = refs; dlg.remember()
            except Exception as e:
                QMessageBox.warning(self, "", self._A(f"PubMed could not be reached ({e}); the paper is written with your own references only.",
                                                      f"تعذر الوصول إلى PubMed ({e})؛ سيُكتب البحث بمراجعك فقط."))
        ai, rep, model = None, {}, ""
        if dlg.mode.currentData() == "ai":
            model = dlg.model.currentData()
            ctx = paper_context(st, results, refs, journal, hm, hr)
            try:
                ai, rep = self._busy(lambda: AW.write_sections(ctx, AW.api_key(dlg.key.text()), model),
                                     self._A("Claude is writing the paper (1–3 minutes)…", "Claude يكتب البحث (1–3 دقائق)…"))
            except Exception as e:
                if QMessageBox.question(self, tr("error"), self._A(f"{e}\n\nWrite the paper with the templates instead?",
                                                                   f"{e}\n\nهل تكتب البحث بالقوالب بدلًا من ذلك؟")) != QMessageBox.Yes:
                    return
                ai = None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            out = build_paper(path, st, results, refs, dlg.style.currentData(), journal, hm, hr,
                              ai_sections=ai, ai_model=AW.MODELS.get(model, model).split(" (")[0] if ai else "")
        except Exception as e:
            QApplication.restoreOverrideCursor(); QMessageBox.critical(self, tr("error"), str(e)); return
        QApplication.restoreOverrideCursor()
        flags = len(rep.get("numbers", [])) + len(rep.get("bad_citations", []))
        QMessageBox.information(self, "", self._A(
            f"Saved: {path}\n\n{out['words']} words, {out['cited']} references cited" + (f" ({added} found on PubMed)" if added else "")
            + f", {out['tables']} tables, {out['figures']} figures" + (f", {out['supplementary']} supplementary items" if out.get('supplementary') else "") + ".\n"
            + (f"Written by Claude; {flags} item(s) flagged [check: …] for you to verify.\n" if ai else "")
            + f"{out['prompts']} [yellow prompts] are left for you to complete." + ("\nThe RIS file for EndNote was saved next to it." if refs else ""),
            f"تم الحفظ: {path}\n\n{out['words']} كلمة، {out['cited']} مرجعًا مستشهدًا به" + (f" (منها {added} من PubMed)" if added else "")
            + f"، {out['tables']} جداول، {out['figures']} أشكال" + (f"، {out['supplementary']} عناصر تكميلية" if out.get('supplementary') else "") + ".\n"
            + (f"كتبه Claude؛ عُلِّم {flags} عنصرًا [check: …] لتتحقق منه.\n" if ai else "")
            + f"بقي {out['prompts']} تلميحًا [أصفر] لتكملها أنت." + ("\nوحُفظ ملف RIS لـ EndNote بجواره." if refs else "")))

    def _busy(self, fn, label):
        """Run fn in a worker thread while a progress dialog keeps the window responsive; re-raise its error."""
        import threading
        from PySide6.QtWidgets import QProgressDialog
        box = {}

        def work():
            try:
                box["v"] = fn()
            except Exception as e:          # noqa: BLE001 — shown to the user by the caller
                box["e"] = e
        th = threading.Thread(target=work, daemon=True); th.start()
        pd_ = QProgressDialog(label, None, 0, 0, self); pd_.setWindowModality(Qt.WindowModal); pd_.setMinimumDuration(0)
        pd_.show()
        while th.is_alive():
            QApplication.processEvents(); th.join(0.05)
        pd_.close(); pd_.deleteLater()
        if "e" in box:
            raise box["e"]
        return box.get("v")

    def build_manuscript(self):
        if not self.entries:
            QMessageBox.information(self, "", self._A("Run some analyses first.", "قم بإجراء بعض التحليلات أولًا.")); return
        from .publish import ManuscriptDialog
        from ..report.manuscript import build_manuscript
        hm = self._histo_methods()
        dlg = ManuscriptDialog(self, has_histo=bool(hm))
        if dlg.exec() != QDialog.Accepted:
            return
        path, _ = QFileDialog.getSaveFileName(self, "", "Manuscript_sections.docx", "Word (*.docx)")
        if not path:
            return
        if not path.lower().endswith(".docx"):
            path += ".docx"
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            build_manuscript([e["result"] for e in self.entries], path, journal=dlg.j.currentData() or "",
                             width_key=dlg.w.currentData() or "single", lang=dlg.lang.currentData(),
                             tables_inline=dlg.inline.isChecked(), histology_methods=hm if dlg.histo.isChecked() else "",
                             main_tables_only=dlg.aux.isChecked())
            self.statusBar().showMessage(path, 8000)
            QMessageBox.information(self, "", self._A("Saved:", "تم الحفظ:") + "\n" + path)
        except Exception as e:
            QMessageBox.critical(self, tr("error"), str(e))
        finally:
            QApplication.restoreOverrideCursor()

    def reviewer_report(self):
        if not self.entries:
            QMessageBox.information(self, "", self._A("Run some analyses first.", "قم بإجراء بعض التحليلات أولًا.")); return
        from ..report.manuscript import build_reviewer_report
        path, _ = QFileDialog.getSaveFileName(self, "", "Statistical_report_for_reviewers.docx", "Word (*.docx)")
        if not path:
            return
        if not path.lower().endswith(".docx"):
            path += ".docx"
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            build_reviewer_report([e["result"] for e in self.entries], path)
            self.statusBar().showMessage(path, 8000)
            QMessageBox.information(self, "", self._A("Saved:", "تم الحفظ:") + "\n" + path)
        except Exception as e:
            QMessageBox.critical(self, tr("error"), str(e))
        finally:
            QApplication.restoreOverrideCursor()

    def _all_figures(self):
        out = []
        for ei, e in enumerate(self.entries):
            for fi, b in enumerate([b for b in e["result"].blocks if b.kind == "figure"]):
                out.append((f"{ei + 1}.{fi + 1} {e['result'].title[:40]}", b.content))
        return out

    def panel_builder(self):
        from .publish import PanelBuilder
        def histo():
            h = getattr(self, "histo", None)
            if h is None or getattr(h, "original", None) is None:
                return None
            return h.render_annotated(True)
        PanelBuilder(self, self._all_figures(), histo).exec()

    def animal_toolkit(self):
        from .toolkit import AnimalToolkit
        dlg = AnimalToolkit(self, self.df if not self.df.empty else None)
        dlg.exec()
        if dlg.excluded is not None:
            self.load_df(dlg.excluded, (self.dataset_name or "data") + self._A(" (outliers excluded)", " (بعد استبعاد الشواذ)"))
            self.statusBar().showMessage(" ".join(dlg.log), 10000)

    def study_templates(self):
        from .toolkit import TemplatesDialog
        dlg = TemplatesDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        df, name = dlg.make()
        self.load_df(df, name)
        self.tabs.setCurrentIndex(0)

    def export(self, kind):
        if not self.entries:
            return
        filt = {"docx": "Word (*.docx)", "xlsx": "Excel (*.xlsx)", "html": "HTML (*.html)"}[kind]
        path, _ = QFileDialog.getSaveFileName(self, "Export", f"MedStatix_results.{kind}", filt)
        if not path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            results = [e["result"] for e in self.entries]
            if kind == "docx":
                A = SETTINGS.language == "ar"
                opts = [("same", "نفس لغة البرنامج" if A else "Same as the interface"), ("en", "English"),
                        ("ar", "العربية"), ("both", "الاثنان (إنجليزي + عربي) — للرسائل العلمية" if A else "Both (English + Arabic) — for theses")]
                QApplication.restoreOverrideCursor()
                it, ok = QInputDialog.getItem(self, "Word", "لغة التفسير في الملف:" if A else "Interpretation language in the file:",
                                              [o[1] for o in opts], [o[0] for o in opts].index(getattr(SETTINGS, "interp_lang", "same")), False)
                QApplication.setOverrideCursor(Qt.WaitCursor)
                if ok:
                    SETTINGS.interp_lang = opts[[o[1] for o in opts].index(it)][0]; self._save_settings()
                results_to_docx(results, path)
            elif kind == "xlsx":
                results_to_xlsx(results, path)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(results_to_html(results))
            self.statusBar().showMessage(path, 6000)
        except Exception as e:
            QMessageBox.critical(self, tr("error"), str(e))
        finally:
            QApplication.restoreOverrideCursor()

    # ------------------------------------------------------------------ quick access to the newest tools
    def open_images_tab(self):
        self.tabs.setCurrentWidget(self.figstudio)

    def quick_comment(self):
        self.tabs.setCurrentWidget(self.histo)
        if getattr(self.histo, "ai", None) is None:
            QMessageBox.information(self, "", "افتح صورة في تبويب الهستولوجي واضغط قراءة الصورة (AI) أولًا، ثم اضغط تعليق احترافي."
                                    if SETTINGS.language == "ar" else
                                    "Open an image in the Histology tab and run the AI reader first, then press Pro comment.")
            return
        self.histo.ai_comment()

    def quick_batch(self):
        self.tabs.setCurrentWidget(self.histo)
        self.histo.batch()

    def quick_congestion(self):
        self.tabs.setCurrentWidget(self.histo)
        if self.histo.original is None:
            QMessageBox.information(self, "", "افتح صورة في تبويب الهستولوجي أولًا." if SETTINGS.language == "ar"
                                    else "Open an image in the Histology tab first.")
            return
        self.histo.ai_teach_congestion()

    def set_expert_mode(self, on):
        if bool(on) == bool(SETTINGS.expert_mode):
            return
        SETTINGS.expert_mode = bool(on)
        self._save_settings()
        self.statusBar().showMessage(("وضع الخبير مفعّل" if on else "وضع الخبير متوقف") if SETTINGS.language == "ar"
                                     else ("Expert mode on" if on else "Expert mode off"), 5000)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.build)           # rebuild after the menu closes so the sliders widen

    # ------------------------------------------------------------------ settings / language
    def open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            before = (SETTINGS.language, SETTINGS.theme, SETTINGS.expert_mode)
            dlg.apply()
            self._save_settings()
            if before != (SETTINGS.language, SETTINGS.theme, SETTINGS.expert_mode):   # expert mode widens the image sliders
                self.build()
            self.restyle_all()

    def toggle_language(self):
        SETTINGS.language = "en" if SETTINGS.language == "ar" else "ar"
        self._save_settings()
        self.build()

    def closeEvent(self, e):
        self._save_settings()
        super().closeEvent(e)

    # ------------------------------------------------------------------ help
    def open_assistant(self):
        from .assistant_ui import AssistantDialog
        if getattr(self, "_assistant", None) is None:
            self._assistant = AssistantDialog(self)
        self._assistant.show(); self._assistant.raise_(); self._assistant.activateWindow()

    # ------------------------------------------------------------------ updates
    def startup_update_check(self):
        if SETTINGS.check_updates and not os.environ.get("MEDSTATIX_NO_UPDATE"):
            from PySide6.QtCore import QTimer
            QTimer.singleShot(4000, lambda: self.check_updates(silent=True))

    def check_updates(self, silent=False):
        """Ask GitHub for the newest release in a worker thread; offer to download and install it."""
        import threading
        from PySide6.QtCore import QObject, Signal

        class _Bridge(QObject):
            done = Signal(object, object)
        self._upd_bridge = _Bridge()
        self._upd_bridge.done.connect(lambda info, err: self._update_found(info, err, silent))

        def work():
            from ..core import updater
            try:
                self._upd_bridge.done.emit(updater.check_latest(), None)
            except Exception as e:  # offline, proxy, rate limit
                self._upd_bridge.done.emit(None, e)
        threading.Thread(target=work, daemon=True).start()
        if not silent:
            self.statusBar().showMessage("…", 3000)

    def _update_found(self, info, err, silent):
        from ..core import updater
        A = SETTINGS.language == "ar"
        if err is not None or info is None:
            if not silent:
                QMessageBox.information(self, "MedStatix", ("تعذّر الاتصال بخادم التحديثات. تأكد من الإنترنت ثم أعد المحاولة."
                                                            if A else "Could not reach the update server. Check the internet connection.")
                                        + (f"\n\n{err}" if err else ""))
            return
        if not updater.is_newer(info["version"], APP_VERSION):
            if not silent:
                QMessageBox.information(self, "MedStatix", (f"لديك أحدث إصدار ({APP_VERSION})." if A
                                                            else f"You have the latest version ({APP_VERSION})."))
            return
        size = f" ({info['size'] / 1e6:.0f} MB)" if info.get("size") else ""
        msg = (f"يتوفر إصدار جديد: {info['version']} (الإصدار الحالي {APP_VERSION}).\n\nهل تريد تنزيله{size} وتثبيته الآن؟ "
               f"سيُغلق البرنامج أثناء التثبيت، ولن تتأثر ملفاتك وإعداداتك." if A else
               f"A new version is available: {info['version']} (installed {APP_VERSION}).\n\nDownload{size} and install it now? "
               f"MedStatix will close during installation; your files and settings are kept.")
        box = QMessageBox(QMessageBox.Information, "MedStatix", msg, QMessageBox.Yes | QMessageBox.No, self)
        if info.get("notes"):
            box.setDetailedText(info["notes"])
        if box.exec() != QMessageBox.Yes:
            return
        if not info.get("url") or os.name != "nt":
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(info["page"])); return
        from PySide6.QtWidgets import QProgressDialog
        dlg = QProgressDialog(("جارٍ تنزيل التحديث…" if A else "Downloading update…"), ("إلغاء" if A else "Cancel"), 0, 100, self)
        dlg.setWindowModality(Qt.WindowModal); dlg.setMinimumDuration(0)

        def prog(done, total):
            if total:
                dlg.setValue(int(100 * done / total))
            QApplication.processEvents()
            return not dlg.wasCanceled()
        try:
            path = updater.download(info["url"], info.get("asset"), prog)
        except Exception as e:
            dlg.close(); QMessageBox.warning(self, "MedStatix", str(e)); return
        dlg.close()
        if not path:
            return
        import subprocess
        self._save_settings()
        subprocess.Popen([path, "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"], close_fds=True)
        QApplication.quit()

    def r_console(self, code="", df=None, title=None):
        from .rconsole import RConsole
        RConsole(self.df if df is None else df, code, self, title).exec()

    def verify_in_r(self):
        from ..core import rbridge
        A = SETTINGS.language == "ar"
        for e in reversed(self.entries):
            if e.get("df") is not None and not str(e.get("aid", "")).startswith("__"):
                code = rbridge.r_code(e["aid"], e["kwargs"])
                if code:
                    self.r_console(code, e["df"], ("التحقق في R: " if A else "Verify in R: ") + e["result"].title)
                    return
                break
        QMessageBox.information(self, "R", "آخر تحليل غير مدعوم بعد في جسر R. المدعوم: اختبارات t، مان-ويتني، ويلكوكسون، "
                                "ANOVA، كروسكال-واليس، الارتباط، الانحدار الخطي واللوجستي، النماذج المختلطة وGEE." if A else
                                "The last analysis is not yet covered by the R bridge. Supported: t-tests, Mann–Whitney, Wilcoxon, "
                                "ANOVA, Kruskal–Wallis, correlation, linear/logistic regression, mixed models and GEE.")

    def duplicate_detector(self):
        from .forensics_ui import DuplicateDialog
        DuplicateDialog(self, self._histo_result).exec()

    def show_validation(self):
        from ..report import validation as V
        QApplication.setOverrideCursor(Qt.WaitCursor)
        rows = []
        try:
            rows = V.run_checks()
            html = V.results_html(rows)
        except Exception as e:
            html = f"<p>Validation suite not available: {e}</p>"
        finally:
            QApplication.restoreOverrideCursor()
        AboutDialog(f"<style>{output_css()}</style>" + html, self).exec()
        if rows:
            A = SETTINGS.language == "ar"
            if QMessageBox.question(self, "Validation", "حفظ تقرير التحقق كملف Word؟" if A else "Save the validation report as a Word file?") \
                    == QMessageBox.Yes:
                path, _ = QFileDialog.getSaveFileName(self, "Word", "MedStatix_validation_report.docx", "Word (*.docx)")
                if path:
                    V.export_docx(path, rows)
                    self.statusBar().showMessage(path, 6000)

    def about(self):
        cats = "".join(f"<li><b>{(ar if SETTINGS.language == 'ar' else en)}</b>: " +
                       ", ".join(lbl(a) for a in REGISTRY.values() if a.category == cid) + "</li>" for cid, en, ar in CATEGORIES)
        html = (f"<h2>{APP_NAME} {APP_VERSION}</h2><p>{tr('app_tagline')}</p>"
                f"<p>Engine: SciPy, statsmodels, NumPy, pandas, Matplotlib (Python). Reporting: APA 7 tables; figure export up to 1200 dpi.</p>"
                f"<ul>{cats}</ul>")
        AboutDialog(f"<style>{output_css()}</style>" + html, self).exec()
