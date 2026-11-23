"""v2.3: reference library (formats, library, CSL styles, Word formatting, sources, Zotero) and its window."""
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from medstatix.refman.library import Library
    L = Library(str(tmp_path / "lib.sqlite"))
    yield L
    L.close()


A = {"type": "article-journal", "title": "Rosmarinic acid attenuates hepatic ischemia and reperfusion injury in rats",
     "container-title": "Food Chem Toxicol", "volume": "67", "page": "87-94", "DOI": "10.1016/j.fct.2014.02.014",
     "issued": {"date-parts": [[2014]]}, "author": [{"family": "Ramalho", "given": "L N"}, {"family": "Pasta", "given": "A A"},
                                                    {"family": "Terra", "given": "V A"}]}
B = {"type": "article-journal", "title": "Autophagy in hepatic ischemia-reperfusion injury", "container-title": "Cell Death Discov",
     "volume": "9", "page": "115", "issued": {"date-parts": [[2023]]}, "author": [{"family": "Mao", "given": "B"}, {"family": "Yuan", "given": "W"}]}


def test_formats_roundtrip_and_parsers():
    from medstatix.refman import formats as FM
    for name, (ext, fn) in FM.EXPORTERS.items():
        back = FM.parse(fn([A, B]), "x" + ext)
        assert len(back) == 2 and back[0]["author"][0]["family"] == "Ramalho" and FM.year_of(back[0]) == "2014", name
        assert back[0]["page"] in ("87-94", "87–94") and back[0].get("DOI") == A["DOI"], name
    enw = "%0 Journal Article\n%A Hassan, Ahmed M.\n%A Omar, S.\n%T Drug X protects\n%J Life Sci\n%V 12\n%P 1-9\n%D 2021\n%R 10.1/xyz\n\n"
    e = FM.parse(enw, "scholar.enw")[0]
    assert e["author"][0] == {"family": "Hassan", "given": "Ahmed M."} and e["DOI"] == "10.1/xyz" and FM.year_of(e) == "2021"
    nbib = "PMID- 123\nTI  - A long title that\n      continues here.\nFAU - Hassan, Ahmed M\nAU  - Hassan AM\nJT  - Life Sciences\nTA  - Life Sci\nVI  - 3\nPG  - 10-20\nDP  - 2020 Jan\nLID - 10.2/abc [doi]\nAB  - Abstract text.\n\n"
    m = FM.parse(nbib, "pubmed.nbib")[0]
    assert m["PMID"] == "123" and m["title"].endswith("continues here") and m["DOI"] == "10.2/abc" and m["author"][0]["family"] == "Hassan"
    csv = 'Authors,Author full names,Title,Year,Source title,Volume,Issue,Page start,Page end,DOI\n"Hassan A.M.; Omar S.","Hassan, Ahmed M. (123); Omar, Sara (456)",Scopus paper,2022,Toxicology,5,2,11,19,10.3/q\n'
    c = FM.parse(csv, "scopus.csv")[0]
    assert c["author"][1] == {"family": "Omar", "given": "Sara"} and c["page"] == "11-19" and c["container-title"] == "Toxicology"
    bib = "@article{x, author={Hassan, Ahmed and Omar, Sara}, title={{Bib} paper}, journal={Tox}, year={2019}, pages={1--5}}"
    b = FM.parse(bib, "s.bib")[0]
    assert b["title"] == "Bib paper" and b["page"] == "1-5" and len(b["author"]) == 2


def test_library_groups_duplicates_and_matching(lib):
    rid, new = lib.add(A, "IR paper")
    assert new and lib.add(dict(A, abstract="x"))[1] is False and lib.count() == 1
    assert lib.get(rid)["abstract"] == "x"                                   # merged into the stored copy
    rb, _ = lib.add(B)
    assert lib.groups() == [("IR paper", 1)] and lib.ids(unfiled=True) == [rb] and lib.ids(query="autophagy") == [rb]
    assert lib.match_citation("Ramalho et al.", "2014") == rid and lib.match_citation("", "", str(rb)) == rb
    assert lib.match_citation("Nobody", "2000") is None
    lib.db.execute("INSERT INTO refs (data, ukey) VALUES (?, ?)", (json.dumps(dict(B, DOI="")), "other"))
    assert lib.duplicates()


def test_styles_and_word_formatting(lib, tmp_path):
    from docx import Document
    from medstatix.refman import styles as ST, word as WD
    ids = [lib.add(A)[0], lib.add(B)[0]]
    assert len(ST.list_styles()) > 60
    cites, bib = ST.format_items(lib.items(ids), "food-and-chemical-toxicology")          # dependent → elsevier-harvard
    assert cites[0] == "(Ramalho et al., 2014)" and bib[0].startswith("Ramalho, L.N., Pasta, A.A., Terra, V.A., 2014.")
    d = Document(); d.add_paragraph("Injury {Ramalho, 2014} and autophagy {Mao, 2023 #%d; Ramalho, 2014}." % ids[1])
    d.add_paragraph("References", style="Heading 1"); d.add_paragraph("Appendix")
    src, dst = str(tmp_path / "m.docx"), str(tmp_path / "m_f.docx"); d.save(src)
    r = WD.format_document(src, dst, lib, "american-medical-association")
    paras = [p for p in Document(dst).paragraphs]
    assert r["citations"] == 2 and r["references"] == 2 and not r["unmatched"]
    assert paras[0].text == "Injury1 and autophagy1,2." and any(x.font.superscript for x in paras[0].runs)
    assert paras[2].text.startswith("1. Ramalho LN") and paras[3].text.startswith("2. Mao B") and paras[4].text == "Appendix"
    r2 = WD.format_document(src, dst, lib, "elsevier-harvard")
    assert Document(dst).paragraphs[0].text == "Injury (Ramalho et al., 2014) and autophagy (Mao and Yuan, 2023; Ramalho et al., 2014)."


def test_paper_with_journal_style(tmp_path):
    from docx import Document
    from medstatix.analyses import run
    from medstatix.report import paper as PP, refs as RF
    from test_v16 import _apo_like
    r = run("journal_table", _apo_like(), variables=["Bax", "Bcl2"], group="Group")
    refs = [RF.Ref(["Hassan AM", "Omar S", "Zaki K"], "2021", "Toxin-induced apoptosis and Bax in rats", "Life Sci", "12", "3", "1-9", "10.1/a", "9")]
    p = str(tmp_path / "p.docx")
    out = PP.build_paper(p, {"title": "T", "model": "toxin-induced injury", "drug": "Drug X"}, [r], refs, "csl:elsevier-harvard")
    txt = "\n".join(x.text for x in Document(p).paragraphs)
    assert "(Hassan et al., 2021)" in txt and "Hassan, A.M., Omar, S., Zaki, K., 2021. Toxin-induced apoptosis" in txt
    assert "⟦CIT" not in txt and out["cited"] == 1


def test_sources_with_fixtures():
    from medstatix.refman import sources as SR
    cr = json.dumps({"message": {"items": [{"type": "journal-article", "title": ["T1"], "container-title": ["J"], "DOI": "10.9/x",
                                            "author": [{"family": "Ali", "given": "B"}], "issued": {"date-parts": [[2020, 5]]}}]}})
    it = SR.crossref("q", getter=lambda u: cr)[0]
    assert it["title"] == "T1" and it["issued"]["date-parts"] == [[2020, 5]] and it["author"][0]["family"] == "Ali"
    oa = json.dumps({"results": [{"title": "W", "publication_year": 2019, "doi": "https://doi.org/10.5/y",
                                  "abstract_inverted_index": {"Hello": [0], "world": [1]},
                                  "authorships": [{"author": {"display_name": "Sara Omar"}}],
                                  "primary_location": {"source": {"display_name": "Tox"}}, "biblio": {"first_page": "3", "last_page": "9"}}]})
    o = SR.openalex("q", getter=lambda u: oa)[0]
    assert o["DOI"] == "10.5/y" and o["abstract"] == "Hello world" and o["author"][0]["family"] == "Omar" and o["page"] == "3-9"
    sc = json.dumps({"search-results": {"entry": [{"dc:title": "S", "prism:publicationName": "Life Sci", "prism:coverDate": "2018-02-01",
                                                   "prism:doi": "10.7/z", "dc:creator": "Hassan A.M."}]}})
    s = SR.scopus("q", api_key="k", getter=lambda u: sc)[0]
    assert s["DOI"] == "10.7/z" and s["issued"]["date-parts"][0][0] == 2018
    with pytest.raises(ValueError):
        SR.scopus("q")
    assert "scholar.google.com" in SR.scholar_url("x y")


def test_zotero_sqlite(tmp_path):
    from medstatix.refman import zotero as ZT
    p = str(tmp_path / "zotero.sqlite")
    db = sqlite3.connect(p)
    db.executescript("""
    CREATE TABLE itemTypes (itemTypeID INT, typeName TEXT); INSERT INTO itemTypes VALUES (1,'journalArticle'),(2,'attachment');
    CREATE TABLE items (itemID INT, itemTypeID INT); INSERT INTO items VALUES (10,1),(11,2);
    CREATE TABLE fields (fieldID INT, fieldName TEXT); INSERT INTO fields VALUES (1,'title'),(2,'publicationTitle'),(3,'date'),(4,'DOI');
    CREATE TABLE itemDataValues (valueID INT, value TEXT);
    INSERT INTO itemDataValues VALUES (1,'Zotero paper'),(2,'Toxicology'),(3,'2017-03-00 March 2017'),(4,'10.8/zz');
    CREATE TABLE itemData (itemID INT, fieldID INT, valueID INT); INSERT INTO itemData VALUES (10,1,1),(10,2,2),(10,3,3),(10,4,4);
    CREATE TABLE creators (creatorID INT, firstName TEXT, lastName TEXT); INSERT INTO creators VALUES (1,'Ahmed','Hassan');
    CREATE TABLE creatorTypes (creatorTypeID INT, creatorType TEXT); INSERT INTO creatorTypes VALUES (1,'author');
    CREATE TABLE itemCreators (itemID INT, creatorID INT, creatorTypeID INT, orderIndex INT); INSERT INTO itemCreators VALUES (10,1,1,0);
    CREATE TABLE collections (collectionID INT, collectionName TEXT); INSERT INTO collections VALUES (1,'Liver');
    CREATE TABLE collectionItems (collectionID INT, itemID INT); INSERT INTO collectionItems VALUES (1,10);
    CREATE TABLE deletedItems (itemID INT);
    """); db.commit(); db.close()
    rows = ZT.read_sqlite(p)
    assert len(rows) == 1
    it, cols = rows[0]
    assert it["title"] == "Zotero paper" and it["DOI"] == "10.8/zz" and it["issued"]["date-parts"][0][:2] == [2017, 3] and cols == ["Liver"]
    api = ZT.read_api(getter=lambda u: json.dumps([{"id": "x", "type": "article-journal", "title": "Z"}]))
    assert api == [{"type": "article-journal", "title": "Z"}]


def test_library_window_offscreen(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from medstatix.refman.library import Library
    from medstatix.ui.refman_ui import LibraryPicker, ReferenceLibrary
    L = Library(str(tmp_path / "w.sqlite")); L.add(A, "G"); L.add(B)
    w = ReferenceLibrary(None, L)
    try:
        assert w.table.rowCount() == 2 and w.style.count() > 60
        from PySide6.QtCore import QItemSelectionModel
        w.table.selectionModel().select(w.table.model().index(0, 0), QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        w.show_selected()
        assert "In-text" in w.preview.toPlainText() or "الاستشهاد" in w.preview.toPlainText()
        w._set_mode("g:G"); assert w.table.rowCount() == 1
        w._set_mode("__online__"); assert w.online.isVisibleTo(w)
        p = LibraryPicker(None, L); assert p.t.rowCount() == 2; p.close(); p.deleteLater()
    finally:
        w.close(); w.deleteLater(); app.processEvents(); L.close()
