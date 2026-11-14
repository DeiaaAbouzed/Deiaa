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
                               QTextBrowser, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QComboBox)
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

    def _save_settings(self):
        for k, v in SETTINGS.as_dict().items():
            self.qs.setValue(k, v)

    # ------------------------------------------------------------------ UI construction
    def build(self):
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
        self.a_recs = self._act("⭐  " + ("التوصيات" if SETTINGS.language == "ar" else "Recommendations"),
                                lambda: self._need_data() and self.import_assistant([]), "Ctrl+R")
        self.a_word = self._act("📝  " + tr("export_word"), lambda: self.export("docx"), "Ctrl+E")
        self.a_excel = self._act("📗  " + tr("export_excel"), lambda: self.export("xlsx"))
        self.a_html = self._act("🌐  " + tr("export_html"), lambda: self.export("html"))
        self.a_settings = self._act("⚙  " + tr("settings"), self.open_settings, "Ctrl+,")
        self.a_lang = self._act("🌍  " + tr("language"), self.toggle_language, "Ctrl+L")
        self.a_clear = self._act("🧹  " + tr("clear_output"), self.clear_output)

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu(tr("file"))
        for a in (self.a_new, self.a_open, self.a_paste, self.a_save):
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
        a.addAction(self.a_smart); a.addAction(self.a_wizard); a.addAction(self.a_recs)
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
        v = mb.addMenu(tr("view"))
        v.addAction(self.a_settings); v.addAction(self.a_lang)
        h = mb.addMenu(tr("help"))
        h.addAction(self._act("✔  " + tr("validation"), self.show_validation))
        h.addAction(self._act("ℹ  " + tr("about"), self.about))

    def _build_toolbar(self):
        tb = QToolBar("main"); tb.setMovable(False); tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(tb)
        for a in (self.a_open, self.a_paste, self.a_save):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.a_smart)
        tb.widgetForAction(self.a_smart).setObjectName("primary")
        tb.addAction(self.a_wizard)
        tb.addAction(self.a_recs)
        tb.addSeparator()
        for a in (self.a_word, self.a_excel, self.a_settings, self.a_lang):
            tb.addAction(a)

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
                                              "Excel (*.xlsx);;CSV (*.csv);;SPSS (*.sav);;Stata (*.dta)")
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
            res = run(aid, df, **kw)
            self.entries.append({"result": res, "aid": aid, "kwargs": kw, "df": df})
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
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for e in self.entries:
                if e["aid"] == "__histo__":
                    continue
                if e["aid"] == "__smart__":
                    e["result"], _ = auto_analyze(e["df"], e["kwargs"]["outcome"], e["kwargs"]["factor"])
                else:
                    e["result"] = run(e["aid"], e["df"], **e["kwargs"])
                if e.get("edited"):
                    from ..plots.groupfig import render, caption_for
                    figs = e["result"].figures
                    for fi, spec in e["edited"].items():
                        if fi < len(figs):
                            figs[fi].content = render(spec); figs[fi].caption = caption_for(spec)
            self.png_cache.clear()
            self.refresh_output(); self.refresh_fig_list()
        finally:
            QApplication.restoreOverrideCursor()

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

    # ------------------------------------------------------------------ settings / language
    def open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            lang_before, theme_before = SETTINGS.language, SETTINGS.theme
            dlg.apply()
            self._save_settings()
            if (lang_before, theme_before) != (SETTINGS.language, SETTINGS.theme):
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
    def show_validation(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            import importlib.util
            here = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            path = os.path.join(here, "tests", "test_validation.py")
            if not os.path.exists(path):
                path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "validation", "test_validation.py")
            spec = importlib.util.spec_from_file_location("mval", path)
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            mod.RESULTS.clear()
            for name in dir(mod):
                if name.startswith("test_") and name != "test_all_analyses_run":
                    try:
                        getattr(mod, name)()
                    except AssertionError:
                        pass
            rows = "".join(f"<tr><td style='text-align:left'>{n}</td><td>{g:.5f}</td><td>{r:.5f}</td>"
                           f"<td style='color:{'#2E8B57' if s == 'PASS' else '#C0392B'}'><b>{s}</b></td><td>{src}</td></tr>"
                           for n, g, r, t, s, src in mod.RESULTS)
            npass = sum(1 for r in mod.RESULTS if r[4] == "PASS")
            html = (f"<h2>Validation against reference software</h2><p><b>{npass}/{len(mod.RESULTS)}</b> checks passed.</p>"
                    f"<table class='apa' cellpadding='4'><tr><th>Check</th><th>MedStatix</th><th>Reference</th><th>Result</th><th>Source</th></tr>{rows}</table>")
        except Exception as e:
            html = f"<p>Validation suite not available: {e}</p>"
        finally:
            QApplication.restoreOverrideCursor()
        AboutDialog(f"<style>{output_css()}</style>" + html, self).exec()

    def about(self):
        cats = "".join(f"<li><b>{(ar if SETTINGS.language == 'ar' else en)}</b>: " +
                       ", ".join(lbl(a) for a in REGISTRY.values() if a.category == cid) + "</li>" for cid, en, ar in CATEGORIES)
        html = (f"<h2>{APP_NAME} {APP_VERSION}</h2><p>{tr('app_tagline')}</p>"
                f"<p>Engine: SciPy, statsmodels, NumPy, pandas, Matplotlib (Python). Reporting: APA 7 tables; figure export up to 1200 dpi.</p>"
                f"<ul>{cats}</ul>")
        AboutDialog(f"<style>{output_css()}</style>" + html, self).exec()
