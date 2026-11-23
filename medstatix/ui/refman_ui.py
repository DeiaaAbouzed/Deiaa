"""Reference library window: groups, references, online search (PubMed, Google Scholar, Scopus, OpenAlex, Crossref),
import/export, Zotero, journal styles and formatting of Word manuscripts."""
from __future__ import annotations

import os
import webbrowser

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QTextBrowser, QToolBar, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..core.settings import SETTINGS
from ..refman import formats as FM
from ..refman import sources as SR
from ..refman import styles as ST
from ..refman.library import Library

ALL, UNFILED, RECENT, ONLINE = "__all__", "__unfiled__", "__recent__", "__online__"


def T(en, ar):
    return ar if SETTINGS.language == "ar" else en


def _busy(parent, fn, label):
    import threading
    from PySide6.QtWidgets import QProgressDialog
    box = {}

    def work():
        try:
            box["v"] = fn()
        except Exception as e:      # noqa: BLE001
            box["e"] = e
    th = threading.Thread(target=work, daemon=True); th.start()
    pd = QProgressDialog(label, None, 0, 0, parent); pd.setWindowModality(Qt.WindowModal); pd.setMinimumDuration(300)
    while th.is_alive():
        QApplication.processEvents(); th.join(0.05)
    pd.close(); pd.deleteLater()
    if "e" in box:
        raise box["e"]
    return box.get("v")


class ReferenceLibrary(QMainWindow):
    def __init__(self, parent=None, library: Library | None = None):
        super().__init__(parent)
        self.setWindowTitle(T("Reference library — MedStatix Pro", "مكتبة المراجع — MedStatix Pro"))
        self.qs = QSettings("MedStatix", "MedStatixPro")
        self.lib = library or Library()
        self.found: list[dict] = []
        self.mode = ALL
        self.setAcceptDrops(True)
        self._toolbar()
        split = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget(); self.tree.setHeaderHidden(True); self.tree.itemClicked.connect(self._pick_group)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu); self.tree.customContextMenuRequested.connect(self._group_menu)
        split.addWidget(self.tree)
        mid = QWidget(); mv = QVBoxLayout(mid); mv.setContentsMargins(0, 0, 0, 0)
        # online search bar
        self.online = QWidget(); ol = QHBoxLayout(self.online); ol.setContentsMargins(0, 0, 0, 0)
        self.src = QComboBox()
        for k, v in SR.SOURCES.items():
            self.src.addItem(v, k)
        self.oq = QLineEdit(); self.oq.setPlaceholderText(T("Search terms, author, title…", "كلمات البحث أو المؤلف أو العنوان…"))
        self.oq.returnPressed.connect(self.online_search)
        self.on = QSpinBox(); self.on.setRange(5, 200); self.on.setValue(25)
        b = QPushButton(T("Search", "بحث")); b.clicked.connect(self.online_search)
        b2 = QPushButton(T("Add selected to library", "أضف المحدد للمكتبة")); b2.clicked.connect(self.add_found)
        for w in (self.src, self.oq, self.on, b, b2):
            ol.addWidget(w, 1 if w is self.oq else 0)
        mv.addWidget(self.online)
        # quick search
        self.q = QLineEdit(); self.q.setPlaceholderText(T("🔍 Search the library (author, year, title, journal, keyword, #record)",
                                                          "🔍 ابحث في المكتبة (المؤلف، السنة، العنوان، المجلة، كلمة، #رقم)"))
        self.q.textChanged.connect(self.refresh); mv.addWidget(self.q)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["#", T("Author", "المؤلف"), T("Year", "السنة"), T("Title", "العنوان"),
                                              T("Journal", "المجلة"), T("Type", "النوع"), "PDF"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True); self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader(); hh.setMinimumSectionSize(34); hh.setSectionResizeMode(QHeaderView.Interactive); hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.show_selected)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu); self.table.customContextMenuRequested.connect(self._ref_menu)
        self.table.doubleClicked.connect(lambda *_: self.tabs.setCurrentIndex(1))
        mv.addWidget(self.table, 1)
        self.status = QLabel(); mv.addWidget(self.status)
        split.addWidget(mid)
        # right panel
        self.tabs = QTabWidget()
        self.preview = QTextBrowser(); self.preview.setOpenExternalLinks(True)
        self.tabs.addTab(self.preview, T("Preview", "المعاينة"))
        self.form = self._editor(); self.tabs.addTab(self.form, T("Reference", "المرجع"))
        split.addWidget(self.tabs)
        split.setSizes([210, 760, 430])
        self.setCentralWidget(split)
        self.resize(1450, 820)
        self.reload_tree(); self._set_mode(ALL)

    # ------------------------------------------------------------------ toolbar
    def _toolbar(self):
        tb = QToolBar(); tb.setMovable(False); tb.setToolButtonStyle(Qt.ToolButtonTextOnly); self.addToolBar(tb)

        def act(text, slot, tip=""):
            a = QAction(text, self); a.triggered.connect(slot); a.setToolTip(tip or text); tb.addAction(a); return a
        act("🌐 " + T("Online search", "بحث أونلاين"), lambda: self._set_mode(ONLINE))
        act("🔗 " + T("Add by DOI / PMID", "إضافة بـ DOI أو PMID"), self.add_by_id)
        act("➕ " + T("New reference", "مرجع جديد"), self.new_ref)
        act("📥 " + T("Import", "استيراد"), self.import_files,
            T("RIS, EndNote XML, ENW (Google Scholar), BibTeX, PubMed .nbib, Scopus CSV, CSL-JSON",
              "RIS وEndNote XML وENW (Google Scholar) وBibTeX وPubMed nbib وScopus CSV"))
        act("📤 " + T("Export", "تصدير"), self.export)
        act("🟥 Zotero", self.zotero)
        self.addToolBarBreak()
        tb = QToolBar(); tb.setMovable(False); tb.setToolButtonStyle(Qt.ToolButtonTextOnly); self.addToolBar(tb)
        tb.addWidget(QLabel(" " + T("Output style", "نمط المجلة") + " "))
        self.style = QComboBox(); self.style.setMinimumWidth(280); self.style.setMaxVisibleItems(25)
        self._fill_styles()
        self.style.currentIndexChanged.connect(self._style_changed); tb.addWidget(self.style)
        act("⬇ " + T("More styles…", "أنماط أخرى…"), self.more_styles)
        tb.addSeparator()
        act("📋 " + T("Copy citation", "نسخ الاستشهاد"), self.copy_temp,
            T("Copies {Author, Year #record} for your Word file", "ينسخ {المؤلف، السنة #رقم} لملف Word"))
        act("📄 " + T("Copy formatted", "نسخ منسّق"), self.copy_formatted)
        act("📝 " + T("Format Word paper…", "تنسيق ملف Word…"), self.format_word)
        tb.addSeparator()
        act("👥 " + T("Find duplicates", "التكرارات"), self.find_duplicates)
        act("⚙ " + T("Settings", "الإعدادات"), self.settings)

    def _fill_styles(self):
        cur = self.qs.value("ref_style", "elsevier-harvard")
        self.style.blockSignals(True); self.style.clear()
        for s in ST.list_styles():
            self.style.addItem(s["title"], s["id"])
        i = self.style.findData(cur); self.style.setCurrentIndex(max(i, 0))
        self.style.blockSignals(False)

    def _style_changed(self):
        self.qs.setValue("ref_style", self.style.currentData()); self.show_selected()

    # ------------------------------------------------------------------ groups
    def reload_tree(self):
        self.tree.clear()
        n = self.lib.count()
        for key, label in ((ALL, T(f"All references ({n})", f"كل المراجع ({n})")), (UNFILED, T("Unfiled", "بلا مجموعة")),
                           (RECENT, T("Recently added", "المضافة حديثًا")), (ONLINE, T("🌐 Online search", "🌐 بحث أونلاين"))):
            it = QTreeWidgetItem([label]); it.setData(0, Qt.UserRole, key); self.tree.addTopLevelItem(it)
        g = QTreeWidgetItem([T("My groups", "مجموعاتي")]); g.setData(0, Qt.UserRole, "__groups__"); self.tree.addTopLevelItem(g)
        for name, cnt in self.lib.groups():
            c = QTreeWidgetItem([f"{name} ({cnt})"]); c.setData(0, Qt.UserRole, "g:" + name); g.addChild(c)
        g.setExpanded(True)

    def _pick_group(self, item):
        k = item.data(0, Qt.UserRole)
        if k == "__groups__":
            return
        self._set_mode(k)

    def _set_mode(self, k):
        self.mode = k
        self.online.setVisible(k == ONLINE); self.q.setVisible(k != ONLINE)
        if k == ONLINE:
            self.oq.setFocus()
        self.refresh()

    def _group_menu(self, pos):
        it = self.tree.itemAt(pos)
        m = QMenu(self)
        m.addAction(T("New group…", "مجموعة جديدة…"), self.new_group)
        if it and str(it.data(0, Qt.UserRole)).startswith("g:"):
            name = it.data(0, Qt.UserRole)[2:]
            m.addAction(T("Rename…", "إعادة تسمية…"), lambda: self._rename_group(name))
            m.addAction(T("Delete group (keeps the references)", "حذف المجموعة (تبقى المراجع)"),
                        lambda: (self.lib.delete_group(name), self.reload_tree(), self._set_mode(ALL)))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def new_group(self):
        name, ok = QInputDialog.getText(self, "", T("Group name:", "اسم المجموعة:"))
        if ok and name.strip():
            self.lib.add_group(name.strip()); self.reload_tree()

    def _rename_group(self, old):
        name, ok = QInputDialog.getText(self, "", T("New name:", "الاسم الجديد:"), text=old)
        if ok and name.strip():
            self.lib.rename_group(old, name.strip()); self.reload_tree()

    # ------------------------------------------------------------------ table
    def _row_items(self):
        if self.mode == ONLINE:
            return [(None, it) for it in self.found]
        g = self.mode[2:] if str(self.mode).startswith("g:") else None
        ids = self.lib.ids(group=g, query=self.q.text().strip(), unfiled=self.mode == UNFILED,
                           recent_days=14 if self.mode == RECENT else 0)
        return [(i, self.lib.get(i)) for i in ids]

    def refresh(self):
        rows = self._row_items()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, (rid, it) in enumerate(rows):
            au = it.get("author") or []
            who = (FM.first_author(it) + (" et al." if len(au) > 2 else f" & {au[1].get('family', '')}" if len(au) == 2 else ""))
            meta = self.lib.meta(rid) if rid else {}
            vals = [rid if rid else "", who, FM.year_of(it), it.get("title", ""), it.get("container-title-short") or it.get("container-title", ""),
                    it.get("type", ""), "📎" if meta.get("pdf") else ""]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem()
                if c == 0 and rid:
                    cell.setData(Qt.DisplayRole, int(rid))
                else:
                    cell.setText(str(v))
                if c == 0:
                    cell.setData(Qt.UserRole, rid if rid else r)
                    if not rid:
                        cell.setFlags(cell.flags() | Qt.ItemIsUserCheckable); cell.setCheckState(Qt.Unchecked)
                self.table.setItem(r, c, cell)
        self.table.setSortingEnabled(True)
        for c, wdt in ((0, 46), (1, 140), (2, 52), (4, 150), (5, 105), (6, 40)):
            self.table.setColumnWidth(c, wdt)
        what = T("results", "نتيجة") if self.mode == ONLINE else T("references", "مرجع")
        self.status.setText(f"{len(rows)} {what}")
        self.reload_counts()

    def reload_counts(self):
        it = self.tree.topLevelItem(0)
        if it is not None:
            n = self.lib.count(); it.setText(0, T(f"All references ({n})", f"كل المراجع ({n})"))

    def selected(self) -> list:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows and 0 <= self.table.currentRow() < self.table.rowCount():
            rows = [self.table.currentRow()]
        out = []
        for r in rows:
            v = self.table.item(r, 0).data(Qt.UserRole)
            out.append(v)
        return out

    def selected_items(self) -> list[dict]:
        if self.mode == ONLINE:
            return [dict(self.found[i], id=f"o{i}") for i in self.selected() if i is not None and i < len(self.found)]
        return [self.lib.get(i) for i in self.selected()]

    def show_selected(self):
        items = self.selected_items()
        if not items:
            self.preview.setHtml(""); return
        try:
            cites, bib = ST.format_items(items[:30], self.style.currentData())
        except Exception as e:          # noqa: BLE001
            self.preview.setHtml(f"<p style='color:#b00'>{e}</p>"); return
        h = [f"<p><b>{T('In-text citation', 'الاستشهاد في النص')}:</b> " + " ".join(cites) + "</p>",
             f"<p><b>{T('Reference list', 'قائمة المراجع')}:</b></p>"] + [f"<p>{b}</p>" for b in bib]
        it = items[0]
        if it.get("abstract"):
            h.append(f"<hr><p><b>Abstract</b><br>{it['abstract']}</p>")
        links = []
        if it.get("DOI"):
            links.append(f"<a href='https://doi.org/{it['DOI']}'>DOI</a>")
        if it.get("PMID"):
            links.append(f"<a href='https://pubmed.ncbi.nlm.nih.gov/{it['PMID']}/'>PubMed</a>")
        if links:
            h.append("<p>" + " · ".join(links) + "</p>")
        self.preview.setHtml("".join(h))
        if self.mode != ONLINE and len(items) == 1:
            self._load_editor(int(str(it["id"])[1:]), it)

    def _ref_menu(self, pos):
        m = QMenu(self)
        if self.mode == ONLINE:
            m.addAction(T("Add to library", "أضف للمكتبة"), self.add_found)
        else:
            sub = m.addMenu(T("Add to group", "أضف إلى مجموعة"))
            for name, _ in self.lib.groups():
                sub.addAction(name, lambda n=name: (self.lib.assign(self.selected(), n), self.reload_tree()))
            sub.addAction(T("New group…", "مجموعة جديدة…"), self._assign_new)
            if str(self.mode).startswith("g:"):
                m.addAction(T("Remove from this group", "إزالة من هذه المجموعة"),
                            lambda: (self.lib.unassign(self.selected(), self.mode[2:]), self.reload_tree(), self.refresh()))
            m.addAction(T("Attach PDF…", "إرفاق PDF…"), self.attach_pdf)
            m.addAction(T("Open PDF", "فتح PDF"), self.open_pdf)
            m.addAction(T("Find full text (DOI)", "النص الكامل (DOI)"), self.open_doi)
            m.addSeparator()
            m.addAction(T("Delete", "حذف"), self.delete)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _assign_new(self):
        name, ok = QInputDialog.getText(self, "", T("Group name:", "اسم المجموعة:"))
        if ok and name.strip():
            self.lib.assign(self.selected(), name.strip()); self.reload_tree()

    # ------------------------------------------------------------------ editor
    def _editor(self):
        w = QWidget(); f = QFormLayout(w)
        self.ed = {}
        self.etype = QComboBox()
        for k in ("article-journal", "book", "chapter", "paper-conference", "thesis", "report", "webpage", "article"):
            self.etype.addItem(k, k)
        f.addRow(T("Type", "النوع"), self.etype)
        self.eauth = QPlainTextEdit(); self.eauth.setMaximumHeight(90)
        self.eauth.setPlaceholderText(T("One author per line: Family, Given", "مؤلف في كل سطر: العائلة، الاسم"))
        f.addRow(T("Authors", "المؤلفون"), self.eauth)
        for k, lab in (("year", T("Year", "السنة")), ("title", T("Title", "العنوان")), ("container-title", T("Journal", "المجلة")),
                       ("container-title-short", T("Journal abbreviation", "اختصار المجلة")), ("volume", T("Volume", "المجلد")),
                       ("issue", T("Issue", "العدد")), ("page", T("Pages", "الصفحات")), ("DOI", "DOI"), ("PMID", "PMID"),
                       ("URL", "URL"), ("keyword", T("Keywords (; separated)", "كلمات مفتاحية"))):
            e = QLineEdit(); self.ed[k] = e; f.addRow(lab, e)
        self.eabs = QPlainTextEdit(); self.eabs.setMaximumHeight(120); f.addRow(T("Abstract", "الملخص"), self.eabs)
        self.enotes = QPlainTextEdit(); self.enotes.setMaximumHeight(70); f.addRow(T("Notes", "ملاحظات"), self.enotes)
        b = QPushButton(T("Save changes", "حفظ التعديلات")); b.clicked.connect(self.save_editor); f.addRow(b)
        self.cur_id = None
        return w

    def _load_editor(self, rid, it):
        self.cur_id = rid
        self.etype.setCurrentIndex(max(0, self.etype.findData(it.get("type", "article-journal"))))
        self.eauth.setPlainText("\n".join(FM.person_text(a) for a in it.get("author", [])))
        for k, e in self.ed.items():
            e.setText(FM.year_of(it) if k == "year" else str(it.get(k, "")))
        self.eabs.setPlainText(it.get("abstract", ""))
        self.enotes.setPlainText(self.lib.meta(rid).get("notes", "") or "")

    def _editor_item(self):
        it = {"type": self.etype.currentData(),
              "author": [FM.person(x) for x in self.eauth.toPlainText().splitlines() if x.strip()],
              "abstract": self.eabs.toPlainText().strip()}
        for k, e in self.ed.items():
            if k == "year":
                FM.set_year(it, e.text())
            else:
                it[k] = e.text().strip()
        return it

    def save_editor(self):
        it = self._editor_item()
        if not it.get("title"):
            QMessageBox.information(self, "", T("Enter at least a title.", "اكتب العنوان على الأقل.")); return
        if self.cur_id:
            self.lib.update(self.cur_id, it)
        else:
            self.cur_id, _ = self.lib.add(it, self.mode[2:] if str(self.mode).startswith("g:") else None)
        self.lib.set_meta(self.cur_id, notes=self.enotes.toPlainText())
        self.refresh()

    def new_ref(self):
        if self.mode == ONLINE:
            self._set_mode(ALL)
        self.cur_id = None
        self.eauth.clear(); self.eabs.clear(); self.enotes.clear()
        for e in self.ed.values():
            e.clear()
        self.tabs.setCurrentIndex(1); self.ed["title"].setFocus()

    # ------------------------------------------------------------------ adding
    def _settings(self):
        return {"scopus_key": self.qs.value("scopus_key", "") or "", "scopus_token": self.qs.value("scopus_token", "") or ""}

    def online_search(self):
        q, src = self.oq.text().strip(), self.src.currentData()
        if not q:
            return
        if src == "scholar":
            webbrowser.open(SR.scholar_url(q))
            QMessageBox.information(self, "Google Scholar", T(
                "Google Scholar has no interface for programs, so the search opened in your browser.\n\n"
                "Once only: Scholar ☰ → Settings → Bibliography manager → \"Show links to import citations into EndNote\" → Save.\n"
                "Then under each result click \"Import into EndNote\" (or Cite → EndNote / RefMan) and drag the downloaded "
                "files onto this window, or use Import. They are added to the library with duplicates skipped.\n\n"
                "Tip: OpenAlex in the source list searches an index of similar breadth directly from here.",
                "لا يوفّر Google Scholar واجهة للبرامج، لذلك فُتح البحث في المتصفح.\n\n"
                "مرة واحدة فقط: ☰ ← الإعدادات ← مدير المراجع ← «إظهار روابط استيراد الاستشهادات إلى EndNote» ← حفظ.\n"
                "ثم اضغط «Import into EndNote» تحت كل نتيجة (أو اقتباس ← EndNote / RefMan)، واسحب الملفات المحمّلة إلى "
                "هذه النافذة أو استخدم «استيراد»، فتُضاف إلى المكتبة مع تجاهل المكرر.\n\n"
                "نصيحة: مصدر OpenAlex في القائمة يبحث في فهرس بنفس السعة تقريبًا مباشرة من هنا."))
            return
        try:
            self.found = _busy(self, lambda: SR.search(src, q, self.on.value(), self._settings()),
                               T(f"Searching {self.src.currentText()}…", f"جارٍ البحث في {self.src.currentText()}…"))
        except Exception as e:          # noqa: BLE001
            QMessageBox.warning(self, "", T(f"The search failed: {e}", f"تعذّر البحث: {e}")); return
        self.refresh()

    def add_found(self):
        rows = [self.table.item(r, 0) for r in range(self.table.rowCount())]
        idx = [it.data(Qt.UserRole) for it in rows if it and it.checkState() == Qt.Checked] or self.selected()
        if not idx:
            QMessageBox.information(self, "", T("Tick or select the results to add.", "حدّد النتائج المطلوب إضافتها.")); return
        group = self._ask_group()
        a, d = self.lib.add_many([self.found[i] for i in idx if i is not None and i < len(self.found)], group)
        self.reload_tree()
        self.status.setText(T(f"{a} added, {d} already in the library.", f"أضيف {a}، و{d} موجودة من قبل."))

    def _ask_group(self):
        names = [T("(no group)", "(بلا مجموعة)")] + [n for n, _ in self.lib.groups()] + [T("New group…", "مجموعة جديدة…")]
        name, ok = QInputDialog.getItem(self, "", T("Add to group:", "أضف إلى مجموعة:"), names, 0, False)
        if not ok or name == names[0]:
            return None
        if name == names[-1]:
            name, ok = QInputDialog.getText(self, "", T("Group name:", "اسم المجموعة:"))
            return name.strip() if ok and name.strip() else None
        return name

    def add_by_id(self):
        t, ok = QInputDialog.getText(self, "", T("DOI or PubMed ID (several separated by spaces):", "DOI أو PMID (يمكن عدة قيم بمسافات):"))
        if not ok or not t.strip():
            return
        added, errs = 0, []
        for tok in t.replace(",", " ").split():
            try:
                it = _busy(self, lambda tok=tok: SR.lookup(tok), T("Looking up…", "جارٍ البحث…"))
                _, new = self.lib.add(it, self.mode[2:] if str(self.mode).startswith("g:") else None); added += new
            except Exception as e:      # noqa: BLE001
                errs.append(f"{tok}: {e}")
        self.reload_tree(); self.refresh()
        QMessageBox.information(self, "", T(f"{added} added.", f"أضيف {added}.") + ("\n" + "\n".join(errs) if errs else ""))

    def import_files(self, paths=None):
        if not paths:
            paths, _ = QFileDialog.getOpenFileNames(self, "", "", T("References", "المراجع")
                                                    + " (*.ris *.enw *.nbib *.txt *.xml *.bib *.csv *.json);;All (*)")
        if not paths:
            return
        group = self._ask_group()
        tot_a = tot_d = 0; errs = []
        for p in paths:
            try:
                a, d = self.lib.add_many(FM.read_file(p), group); tot_a += a; tot_d += d
            except Exception as e:      # noqa: BLE001
                errs.append(f"{os.path.basename(p)}: {e}")
        self.reload_tree(); self.refresh()
        QMessageBox.information(self, "", T(f"{tot_a} references imported, {tot_d} duplicates skipped.",
                                            f"استُورد {tot_a} مرجعًا، وتُجوهل {tot_d} مكررًا.") + ("\n\n" + "\n".join(errs) if errs else ""))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.import_files([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    # ------------------------------------------------------------------ export / copy
    def export(self):
        items = self.selected_items() if self.selected() else [self.lib.get(i) for i in self.lib.ids(
            group=self.mode[2:] if str(self.mode).startswith("g:") else None)]
        if not items:
            return
        fmt, ok = QInputDialog.getItem(self, "", T("Format:", "الصيغة:"), list(FM.EXPORTERS), 0, False)
        if not ok:
            return
        ext, fn = FM.EXPORTERS[fmt]
        p, _ = QFileDialog.getSaveFileName(self, "", "references" + ext, f"{fmt} (*{ext})")
        if p:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(fn([{k: v for k, v in it.items() if k != "id"} for it in items]))
            self.status.setText(T(f"{len(items)} references exported.", f"صُدِّر {len(items)} مرجعًا."))

    def copy_temp(self):
        out = []
        for rid in self.selected():
            if rid is None or self.mode == ONLINE:
                continue
            it = self.lib.get(rid)
            out.append(f"{FM.first_author(it)}, {FM.year_of(it)} #{rid}")
        if out:
            QGuiApplication.clipboard().setText("{" + "; ".join(out) + "}")
            self.status.setText(T("Citation copied: paste it in Word, then use Format Word paper.",
                                  "نُسخ الاستشهاد: الصقه في Word ثم استخدم «تنسيق ملف Word»."))

    def copy_formatted(self):
        items = self.selected_items()
        if not items:
            return
        _, bib = ST.format_items(items, self.style.currentData())
        from PySide6.QtCore import QMimeData
        md = QMimeData(); md.setHtml("".join(f"<p>{b}</p>" for b in bib)); md.setText("\n".join(ST.plain(b) for b in bib))
        QGuiApplication.clipboard().setMimeData(md)
        self.status.setText(T("Formatted references copied.", "نُسخت المراجع منسّقة."))

    def format_word(self):
        src, _ = QFileDialog.getOpenFileName(self, T("Your manuscript", "ملف البحث"), "", "Word (*.docx)")
        if not src:
            return
        dst = src[:-5] + "_formatted.docx"
        from ..refman import word as WD
        try:
            r = _busy(self, lambda: WD.format_document(src, dst, self.lib, self.style.currentData()),
                      T("Formatting citations and the reference list…", "جارٍ تنسيق الاستشهادات وقائمة المراجع…"))
        except Exception as e:          # noqa: BLE001
            QMessageBox.critical(self, "", str(e)); return
        if not r["citations"]:
            QMessageBox.information(self, "", T(
                "No temporary citations were found. Write them in Word as {Author, Year} or {Author, Year #record} "
                "(Copy citation puts them on the clipboard), then run this again.",
                "لم توجد استشهادات مؤقتة. اكتبها في Word بالشكل {المؤلف، السنة} أو {Author, Year #رقم} "
                "(زر «نسخ الاستشهاد» ينسخها لك)، ثم أعد التشغيل.") + ("\n\n" + "\n".join(r["unmatched"]) if r["unmatched"] else ""))
            return
        msg = T(f"Saved: {dst}\n\n{r['citations']} citations formatted, {r['references']} references in the list "
                f"({self.style.currentText()}).", f"تم الحفظ: {dst}\n\nنُسِّق {r['citations']} استشهادًا، و{r['references']} "
                f"مرجعًا في القائمة ({self.style.currentText()}).")
        if r["unmatched"]:
            msg += "\n\n" + T("Not found in the library (left as they are):", "غير موجودة في المكتبة (تُركت كما هي):") + "\n" + "\n".join(r["unmatched"][:20])
        QMessageBox.information(self, "", msg)
        if QMessageBox.question(self, "", T("Open the formatted file?", "فتح الملف المنسّق؟")) == QMessageBox.Yes:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(dst))

    # ------------------------------------------------------------------ styles
    def more_styles(self):
        t, ok = QInputDialog.getText(self, "", T(
            "Journal style id from zotero.org/styles (e.g. toxicology-reports, journal-of-applied-toxicology),\n"
            "or leave empty to load a .csl file:",
            "معرّف نمط المجلة من zotero.org/styles (مثل toxicology-reports)،\nأو اتركه فارغًا لتحميل ملف .csl:"))
        if not ok:
            return
        try:
            if t.strip():
                inf = _busy(self, lambda: ST.download(t.strip()), T("Downloading the style…", "جارٍ تحميل النمط…"))
            else:
                p, _ = QFileDialog.getOpenFileName(self, "", "", "CSL (*.csl)")
                if not p:
                    return
                inf = ST.add_file(p)
        except Exception as e:          # noqa: BLE001
            QMessageBox.warning(self, "", str(e)); return
        self.qs.setValue("ref_style", inf["id"]); self._fill_styles()

    # ------------------------------------------------------------------ misc
    def delete(self):
        ids = [i for i in self.selected() if i]
        if ids and QMessageBox.question(self, "", T(f"Delete {len(ids)} reference(s)?", f"حذف {len(ids)} مرجعًا؟")) == QMessageBox.Yes:
            self.lib.delete(ids); self.reload_tree(); self.refresh()

    def attach_pdf(self):
        ids = self.selected()
        if len(ids) != 1:
            return
        p, _ = QFileDialog.getOpenFileName(self, "", "", "PDF (*.pdf)")
        if p:
            self.lib.set_meta(ids[0], pdf=p); self.refresh()

    def open_pdf(self):
        ids = self.selected()
        if ids:
            p = self.lib.meta(ids[0]).get("pdf")
            if p and os.path.exists(p):
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def open_doi(self):
        for it in self.selected_items()[:5]:
            if it.get("DOI"):
                webbrowser.open("https://doi.org/" + it["DOI"])

    def find_duplicates(self):
        groups = self.lib.duplicates()
        if not groups:
            QMessageBox.information(self, "", T("No duplicates found.", "لا توجد مراجع مكررة.")); return
        txt = "\n".join(", ".join(f"#{i}" for i in g) for g in groups[:40])
        if QMessageBox.question(self, "", T(f"{len(groups)} sets of duplicates:\n{txt}\n\nKeep the first of each set and delete the rest?",
                                            f"{len(groups)} مجموعات مكررة:\n{txt}\n\nالإبقاء على الأول وحذف الباقي؟")) == QMessageBox.Yes:
            self.lib.delete([i for g in groups for i in g[1:]]); self.reload_tree(); self.refresh()

    def zotero(self):
        from ..refman import zotero as ZT
        opts = [T("Zotero database file (zotero.sqlite)", "ملف قاعدة بيانات Zotero (zotero.sqlite)"),
                T("Zotero 7 running on this computer (local API)", "Zotero 7 المفتوح على هذا الجهاز"),
                T("Zotero web library (user ID + API key)", "مكتبة Zotero على الإنترنت (المعرّف + مفتاح API)")]
        choice, ok = QInputDialog.getItem(self, "Zotero", T("Import from:", "الاستيراد من:"), opts, 0, False)
        if not ok:
            return
        try:
            if choice == opts[0]:
                p, _ = QFileDialog.getOpenFileName(self, "zotero.sqlite", ZT.default_sqlite() or "", "Zotero (zotero.sqlite)")
                if not p:
                    return
                rows = _busy(self, lambda: ZT.read_sqlite(p), T("Reading Zotero…", "جارٍ قراءة Zotero…"))
                a = d = 0
                for it, cols in rows:
                    rid, new = self.lib.add(it, "Zotero")
                    for c in cols:
                        self.lib.assign([rid], "Zotero: " + c)
                    a += new; d += not new
            elif choice == opts[1]:
                items = _busy(self, lambda: ZT.read_api("0", "", True), T("Reading Zotero…", "جارٍ قراءة Zotero…"))
                a, d = self.lib.add_many(items, "Zotero")
            else:
                uid, ok = QInputDialog.getText(self, "Zotero", T("User ID (zotero.org/settings/keys):", "معرّف المستخدم:"),
                                               text=self.qs.value("zotero_uid", "") or "")
                if not ok:
                    return
                key, ok = QInputDialog.getText(self, "Zotero", T("API key:", "مفتاح API:"), QLineEdit.Password,
                                               self.qs.value("zotero_key", "") or "")
                if not ok:
                    return
                self.qs.setValue("zotero_uid", uid.strip()); self.qs.setValue("zotero_key", key.strip())
                items = _busy(self, lambda: ZT.read_api(uid.strip(), key.strip(), False), T("Reading Zotero…", "جارٍ قراءة Zotero…"))
                a, d = self.lib.add_many(items, "Zotero")
        except Exception as e:          # noqa: BLE001
            QMessageBox.warning(self, "Zotero", T(f"Zotero could not be read: {e}", f"تعذّرت قراءة Zotero: {e}")); return
        self.reload_tree(); self.refresh()
        QMessageBox.information(self, "Zotero", T(f"{a} references imported, {d} already in the library.",
                                                  f"استُورد {a} مرجعًا، و{d} موجودة من قبل."))

    def settings(self):
        d = QDialog(self); d.setWindowTitle(T("Library settings", "إعدادات المكتبة")); f = QFormLayout(d)
        k = QLineEdit(self.qs.value("scopus_key", "") or ""); k.setEchoMode(QLineEdit.Password)
        t = QLineEdit(self.qs.value("scopus_token", "") or ""); t.setEchoMode(QLineEdit.Password)
        f.addRow(T("Scopus API key", "مفتاح Scopus API"), k)
        f.addRow(T("Scopus institution token (optional)", "رمز المؤسسة لـ Scopus (اختياري)"), t)
        lab = QLabel(T("Get a free key at dev.elsevier.com (\"I want an API key\") with your university e-mail. Scopus "
                       "answers only if your university subscribes; off campus an institution token is needed.",
                       "احصل على مفتاح مجاني من dev.elsevier.com ببريد الجامعة. يعمل Scopus فقط إذا كانت جامعتك مشتركة، "
                       "وخارج الجامعة يلزم رمز المؤسسة."))
        lab.setWordWrap(True); f.addRow(lab)
        f.addRow(QLabel(T("Library file:", "ملف المكتبة:") + " " + self.lib.path))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); bb.accepted.connect(d.accept); bb.rejected.connect(d.reject)
        f.addRow(bb)
        if d.exec():
            self.qs.setValue("scopus_key", k.text().strip()); self.qs.setValue("scopus_token", t.text().strip())


class LibraryPicker(QDialog):
    """Pick references from the library for the paper writer."""

    def __init__(self, parent=None, library: Library | None = None):
        super().__init__(parent)
        self.setWindowTitle(T("Add references from the library", "إضافة مراجع من المكتبة"))
        self.lib = library or Library()
        v = QVBoxLayout(self)
        r = QHBoxLayout()
        self.group = QComboBox(); self.group.addItem(T("All references", "كل المراجع"), "")
        for name, n in self.lib.groups():
            self.group.addItem(f"{name} ({n})", name)
        self.q = QLineEdit(); self.q.setPlaceholderText(T("Search…", "بحث…"))
        r.addWidget(self.group); r.addWidget(self.q, 1); v.addLayout(r)
        self.t = QTableWidget(0, 4); self.t.setHorizontalHeaderLabels(["#", T("Author", "المؤلف"), T("Year", "السنة"), T("Title", "العنوان")])
        self.t.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch); self.t.verticalHeader().setVisible(False)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows); self.t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        v.addWidget(self.t, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.group.currentIndexChanged.connect(self.fill); self.q.textChanged.connect(self.fill)
        self.fill(); self.resize(900, 600)

    def fill(self):
        ids = self.lib.ids(group=self.group.currentData() or None, query=self.q.text().strip())
        self.t.setRowCount(len(ids))
        for r, i in enumerate(ids):
            it = self.lib.get(i)
            for c, val in enumerate([i, FM.first_author(it), FM.year_of(it), it.get("title", "")]):
                cell = QTableWidgetItem(str(val))
                if c == 0:
                    cell.setFlags(cell.flags() | Qt.ItemIsUserCheckable); cell.setCheckState(Qt.Unchecked); cell.setData(Qt.UserRole, i)
                self.t.setItem(r, c, cell)

    def chosen(self) -> list[dict]:
        ids = [self.t.item(r, 0).data(Qt.UserRole) for r in range(self.t.rowCount()) if self.t.item(r, 0).checkState() == Qt.Checked]
        ids = ids or [self.t.item(i.row(), 0).data(Qt.UserRole) for i in self.t.selectionModel().selectedRows()]
        return [self.lib.get(i) for i in ids]
