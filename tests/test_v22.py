"""v2.2: paper fixes (summary-first results, supplementary tables, one statistics paragraph), automatic PubMed
references, optional Claude writer with number and citation checks (mocked client)."""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from medstatix.report import ai_writer as AW  # noqa: E402
from medstatix.report import paper as PP  # noqa: E402
from medstatix.report import refs as RF  # noqa: E402
from test_v16 import _apo_like  # noqa: E402


def _results():
    from medstatix.analyses import run
    from medstatix.core.advisor import auto_analyze
    df = _apo_like()
    return [auto_analyze(df.copy(), "Bax", "Group")[0], run("journal_table", df, variables=["Bax", "Bcl2"], group="Group")]


def _text(p):
    from docx import Document
    return "\n".join(x.text for x in Document(p).paragraphs)


def test_template_paper_structure(tmp_path):
    p = str(tmp_path / "p.docx")
    refs = [RF.Ref(["Hassan AM"], "2021", "Toxin-induced apoptosis and Bax in rats", "Life Sci", "1", "", "1", "", "9")]
    out = PP.build_paper(p, {"title": "T", "model": "toxin-induced injury", "drug": "Drug X", "organ": "liver"},
                         _results(), refs, "endnote", "Elsevier")
    txt = _text(p)
    assert "3.1. Biochemical findings" in txt and "3.2." not in txt          # no per-analysis 'Kruskal-Wallis test' sections
    assert "Supplementary material" in txt and out["supplementary"] > 0 and out["tables"] <= 2
    assert txt.count("For each marker") <= 1 and "Data are presented as mean ± SD." not in txt
    assert "Hassan AM (2021)" in txt                                           # provisional list in EndNote mode
    assert "-induced injury-induced" not in txt


def test_auto_references():
    xml = open(os.path.join(os.path.dirname(__file__), "test_v21.py"), encoding="utf-8").read().split('XML = """')[1].split('"""')[0]
    calls = []

    def getter(url):
        calls.append(url)
        return '{"esearchresult": {"idlist": ["123"]}}' if "esearch" in url else xml
    qs = RF.auto_queries({"model": "liver ischemia reperfusion injury", "drug": "modified citrus pectin (MCP)"}, ["MDA", "MPO"])
    assert any("modified citrus pectin" in q and "(MCP)" not in q for q, _ in qs)
    refs = RF.auto_references({"model": "x injury", "drug": "Drug X"}, ["MDA"], getter=getter)
    assert len(refs) == 1 and calls                                            # de-duplicated


class _Msg:
    def __init__(self, text):
        self.stop_reason = "end_turn"
        self.content = [type("B", (), {"type": "text", "text": text})()]


class _Client:
    def __init__(self, payload):
        self.payload = payload; self.kw = None
        outer = self

        class S:
            def __init__(self, **kw):
                outer.kw = kw

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get_final_message(self):
                return _Msg(json.dumps(outer.payload))
        self.beta = type("Beta", (), {"messages": type("M", (), {"stream": staticmethod(lambda **kw: S(**kw))})()})()
        self.messages = self.beta.messages


def test_ai_writer_checks_and_paper(tmp_path):
    res = _results()
    refs = [RF.Ref(["Hassan AM"], "2021", "Toxin-induced apoptosis", "Life Sci", "1", "", "1", "", "9", "Drug X reduced Bax.")]
    st = {"title": "T", "model": "toxin-induced injury", "drug": "Drug X"}
    ctx = PP.paper_context(st, res, refs)
    assert ctx["references"][0]["id"] == "R1" and ctx["markers"] and ctx["results_text"]
    payload = {"title": "T", "highlights": ["Bax rose"], "keywords": ["a", "b"],
               "abstract": {"background": "B.", "methods": "M.", "results": "Bax rose 987.6-fold.", "conclusion": "C."},
               "introduction": ["Apoptosis matters [R1].", "Unknown study [R7]."],
               "results": [{"heading": "Apoptosis", "paragraphs": ["As shown in Table 1, Bax changed."]}],
               "discussion": ["Drug X reduced Bax in earlier work [R1]."], "conclusion": "Drug X protected."}
    cl = _Client(payload)
    sec, rep = AW.write_sections(ctx, "k", client=cl)
    assert cl.kw["model"] == AW.DEFAULT_MODEL and cl.kw["output_config"]["format"]["type"] == "json_schema"
    assert "[check: 987.6]" in sec["abstract"]["results"] and "987.6" in rep["numbers"] and "R7" in rep["bad_citations"]
    p = str(tmp_path / "ai.docx")
    PP.build_paper(p, st, res, refs, "vancouver", "", ai_sections=sec, ai_model="Claude Opus 5.5")
    txt = _text(p)
    assert "Apoptosis matters [1]." in txt and "Unknown study [ref]." in txt
    assert "Declaration of generative AI" in txt and "Claude Opus 5.5" in txt and "Highlights" in txt


def test_caption_median_iqr_and_refs():
    import numpy as np
    from medstatix.plots.groupfig import GroupFigSpec, auto_caption
    sp = GroupFigSpec(groups={"A": np.arange(5.0), "B": np.arange(5.0) + 3}, ylabel="Y", center="median",
                      plot_type="Bar + points", error_bar="SD", ref1="B", ref2="B",
                      comparisons=[("A", "B", 0.01)], sig_layout="Symbols above groups", sig_mode="Versus reference group")
    c = auto_caption(sp)
    assert "median with interquartile range" in c and "± SD" not in c and "# versus" not in c
