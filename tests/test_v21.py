"""v2.1: full-paper builder (templates, no language model), PubMed parsing, RIS/EndNote, citation styles."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from medstatix.report import refs as RF  # noqa: E402
from medstatix.report import paper as PP  # noqa: E402
from test_v16 import _apo_like  # noqa: E402

XML = """<?xml version="1.0"?><PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article>
<Journal><JournalIssue><Volume>12</Volume><Issue>3</Issue><PubDate><Year>2021</Year></PubDate></JournalIssue>
<ISOAbbreviation>Life Sci</ISOAbbreviation></Journal><ArticleTitle>Drug X attenuates toxin-induced apoptosis via Bax/Bcl-2.</ArticleTitle>
<Pagination><MedlinePgn>100-110</MedlinePgn></Pagination><Abstract><AbstractText>Drug X reduced Bax.</AbstractText></Abstract>
<AuthorList><Author><LastName>Hassan</LastName><Initials>AM</Initials></Author><Author><LastName>Omar</LastName><Initials>S</Initials></Author></AuthorList>
</Article><KeywordList><Keyword>apoptosis</Keyword></KeywordList></MedlineCitation><PubmedData><ArticleIdList>
<ArticleId IdType="doi">10.1/abc</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""


def test_pubmed_parse_and_ris_roundtrip():
    def getter(url):
        return '{"esearchresult": {"idlist": ["123"]}}' if "esearch" in url else XML
    refs = RF.pubmed_search("x", getter=getter)
    r = refs[0]
    assert (r.first_surname, r.year, r.journal, r.doi, r.pmid, r.pages) == ("Hassan", "2021", "Life Sci", "10.1/abc", "123", "100-110")
    back = RF.from_ris(RF.to_ris(refs))[0]
    assert back.title == r.title and back.authors == r.authors and back.pages == "100-110" and back.pmid == "123"


def test_citation_styles():
    a = RF.Ref(["Hassan AM", "Omar S"], "2021", "T1", "J", "1", "", "1-2", "", "1")
    b = RF.Ref(["Zaki K", "Ali B", "Nour C"], "2019", "Nephro T2", "J", "2", "", "3-4", "", "2")
    e = RF.Citer([a, b], "endnote")
    assert e.cite([a, b]) == "{Hassan, 2021}{Zaki, 2019}" and e.bibliography() == []
    v = RF.Citer([a, b], "vancouver"); v.cite([b]); assert v.cite([a, b]) == "[1,2]"
    assert v.bibliography()[0].startswith("1. Zaki K, Ali B, Nour C. Nephro T2.")
    assert RF.Citer([a, b], "apa").cite([a, b]) == "(Hassan and Omar, 2021; Zaki et al., 2019)"
    assert RF.best([a, b], ["nephro"], 1) == [b]


def test_build_paper(tmp_path):
    from docx import Document
    from medstatix.analyses import run
    r = run("journal_table", _apo_like(), variables=["Bax", "Bcl2"], group="Group")
    refs = [RF.Ref(["Hassan AM"], "2021", "Toxin-induced apoptosis and Bax in rats", "Life Sci", "1", "", "1", "", "9")]
    st = {"title": "Drug protects against toxin", "model": "toxin-induced injury", "drug": "Drug X", "organ": "liver"}
    p = str(tmp_path / "paper.docx")
    out = PP.build_paper(p, st, [r], refs, "endnote", "Elsevier", "", "Sections showed mild inflammation.")
    txt = "\n".join(x.text for x in Document(p).paragraphs)
    for h in ("Abstract", "1. Introduction", "2. Materials and methods", "2.3. Experimental design", "3. Results",
              "4. Discussion", "5. Conclusion", "Declarations"):
        assert h in txt
    assert "Bax/Bcl-2" in txt and "{Hassan, 2021}" in txt and "Group 2 (Toxin)" in txt
    assert "Histopathological findings" in txt and "Toxin + Drug 100" in txt
    assert out["prompts"] > 5 and out["cited"] == 1 and os.path.exists(str(tmp_path / "paper_references.ris"))


def test_marker_pathways():
    from medstatix.report import markers_kb as KB
    assert KB.pathway_of("MDA (nmol/g)") == "oxidative" and KB.pathway_of("Caspase-3") == "apoptosis"
    assert KB.pathway_of("TNF-α (pg/mL)") == "inflammation" and KB.pathway_of("Serum creatinine") == "kidney"
    assert KB.pathway_of("CK-MB") == "cardiac" and KB.pathway_of("Galectin-9") == "other"


def test_paper_dialog_offscreen():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from medstatix.ui.paper_ui import PaperDialog
    d = PaperDialog(None, ["Control", "Toxin"], "histo", "")
    d.ed["model"].setText("toxin injury"); d.ed["drug"].setText("Drug X"); d.suggest()
    assert "toxin injury" in d.q.text() and d.study()["group_desc"] == {"Control": "", "Toxin": ""}
    d.close(); d.deleteLater(); app.processEvents()
    del d
