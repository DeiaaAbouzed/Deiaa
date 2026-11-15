"""Chat window for the offline analysis assistant."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser, QVBoxLayout

from ..core import assistant as AS
from ..core.settings import SETTINGS


def T(en, ar):
    return ar if SETTINGS.language == "ar" else en


EXAMPLES = [("compare MDA between groups", "قارن MDA بين المجموعات"), ("correlation between ALT and AST", "الارتباط بين ALT و AST"),
            ("heatmap of all markers", "ارسم خريطة حرارية لكل المؤشرات"), ("describe all variables by group", "وصف كل المتغيرات حسب المجموعة")]


class AssistantDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle(T("Analysis assistant", "المساعد الإحصائي"))
        self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
        lay = QVBoxLayout(self)
        self.view = QTextBrowser(); self.view.setOpenExternalLinks(False)
        lay.addWidget(self.view, 1)
        ex = QHBoxLayout()
        for en, ar in EXAMPLES:
            b = QPushButton(T(en, ar)); b.setFlat(True); b.clicked.connect(lambda _=False, q=T(en, ar): self.ask(q)); ex.addWidget(b)
        lay.addLayout(ex)
        row = QHBoxLayout()
        self.inp = QLineEdit(); self.inp.setPlaceholderText(T("Ask in Arabic or English, e.g. compare MDA between groups",
                                                               "اكتب طلبك بالعربية أو الإنجليزية، مثل: قارن MDA بين المجموعات"))
        self.inp.returnPressed.connect(lambda: self.ask(self.inp.text()))
        send = QPushButton(T("Send", "إرسال")); send.setObjectName("primary"); send.clicked.connect(lambda: self.ask(self.inp.text()))
        row.addWidget(self.inp, 1); row.addWidget(send)
        lay.addLayout(row)
        note = QLabel(T("Runs on this computer: your data and questions are not sent anywhere.",
                        "يعمل على جهازك: لا تُرسل بياناتك أو أسئلتك إلى أي مكان."))
        note.setObjectName("hint"); lay.addWidget(note)
        self.history = []
        self._say("bot", AS.parse(T("help", "مساعدة"), None)[T("say_en", "say_ar")])
        self.resize(760, 600)

    def _say(self, who, text):
        rtl = SETTINGS.language == "ar"
        align = ("right" if rtl else "left") if who == "user" else ("left" if rtl else "right")
        bg = "#DCEBFF" if who == "user" else "#EEF3EA"
        self.history.append(f"<div dir='{'rtl' if rtl else 'ltr'}' style='margin:6px; padding:8px 12px; background:{bg}; "
                            f"border-radius:10px; color:#1D2433; text-align:{'right' if rtl else 'left'}'>"
                            f"<b>{'🧑' if who == 'user' else '🤖'}</b> {text}</div>")
        self.view.setHtml("".join(self.history))
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def ask(self, q):
        q = (q or "").strip()
        if not q:
            return
        self.inp.clear()
        self._say("user", html.escape(q))
        df = self.main.df if self.main.df is not None and not self.main.df.empty else None
        plan = AS.parse(q, df)
        say = plan[T("say_en", "say_ar")]
        if not plan["actions"]:
            self._say("bot", html.escape(say)); return
        n0 = len(self.main.entries)
        for kind, aid, kw in plan["actions"]:
            if kind == "open":
                self._say("bot", html.escape(say)); self.main.open_analysis(aid); return
            if kind == "smart":
                self.main.run_smart(kw["outcomes"], kw["factor"])
            else:
                self.main.execute(aid, kw)
        new = self.main.entries[n0:]
        if not new:
            self._say("bot", html.escape(say) + "<br>" + T("The analysis could not be run (see the message).", "تعذّر تنفيذ التحليل (انظر الرسالة)."))
            return
        parts = [f"<b>{html.escape(say)}</b>"]
        for e in new:
            r = e["result"]
            interp = [b.content for b in r.blocks if b.kind == "interpret"]
            meth = [b.content for b in r.blocks if b.kind == "methods"]
            figs = sum(1 for b in r.blocks if b.kind == "figure")
            parts.append(f"<u>{html.escape(r.title)}</u>")
            for i in interp:
                parts.append(html.escape(i.get("ar" if SETTINGS.language == "ar" else "en", "") if isinstance(i, dict) else str(i)))
            if meth:
                parts.append("<i>" + T("Methods text: ", "نص الطرق: ") + html.escape(str(meth[0])) + "</i>")
            if figs:
                parts.append(T(f"{figs} figure(s) added to the Figures tab.", f"أُضيف {figs} رسم إلى تبويب الرسوم."))
        parts.append(T("Full tables are in the Results tab; export to Word from the File menu.",
                       "الجداول الكاملة في تبويب النتائج، ويمكن تصديرها إلى Word من قائمة ملف."))
        self._say("bot", "<br>".join(parts))
