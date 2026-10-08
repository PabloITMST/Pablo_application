"""M3.3 PDF evidence tests on LinearRAG.pdf. Run: python tests/skill/test_pdf.py
Gold spans (tests/eval/linearrag_gold.json) must anchor on their page; ask() runs on a stub judge (no network).
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from pablo_v2.intent.engine import IntentEngine  # noqa: E402
from pablo_v2.skill import pdf  # noqa: E402
from pablo_v2.skill.evidence import AnchorRejected  # noqa: E402
from pablo_v2.skill.skill import PabloSkill  # noqa: E402
from pablo_v2.skill.viewer import model, render_html  # noqa: E402

PDF = os.path.join(ROOT, "LinearRAG.pdf")
GOLD = json.load(open(os.path.join(ROOT, "tests", "eval", "linearrag_gold.json"), encoding="utf-8"))


class Judge:  # answer_from_pdf stub: a claim [1], a table row [2], and one quote that is not in the paper
    def answer_from_pdf(self, question, pages):
        assert len(pages) > 9 and "249.78" in pages[8]
        return {"answer": "저자는 77% 이상 줄였다고 씁니다 [1]. Table 2는 249.78 s입니다 [3]. 없는 문장 [2].",
                "citations": [{"n": 1, "page": 2, "quote": "reduces indexing time by over 77%", "role": "claim"},
                              {"n": 2, "page": 3, "quote": "a sentence that is not in this paper", "role": "text"},
                              {"n": 3, "page": 4, "quote": "LinearRAG (Ours) 249.78 0.093 0 0 66.95", "role": "table"}]}


def test_gold_and_resolve():
    d = tempfile.mkdtemp()
    s = PabloSkill(IntentEngine(), path=os.path.join(d, "skill.json"))
    src = s.capture_pdf(PDF)
    assert src.kind == "pdf" and s.capture_pdf(PDF).id == src.id  # same bytes -> same source
    assert pdf.content_hash(s.snapshot_pdf(src)) == src.version["content_hash"]
    ps = s.snapshot_text(src).split("\f")
    for q in GOLD["questions"]:
        for g in q["gold"]:
            a = s.add_anchor(src.id, g["exact"])  # unique in the whole paper, no page hint needed
            assert a.selector["page"] == g["page"], (q["id"], g["exact"], a.selector)
            assert pdf.key(ps[g["page"] - 1][a.selector["start"]:a.selector["end"]])[0] == pdf.key(g["exact"])[0]
    try:
        s.add_anchor(src.id, "LinearRAG")
        raise AssertionError("ambiguous quote accepted")
    except AnchorRejected:
        pass
    e = s.add_anchor(src.id, "reduces indexing time by over 77%")
    assert s.resolve_anchor(e.id).status == "VALID"
    moved = os.path.join(d, "copy.pdf")  # same bytes elsewhere: VALID; different bytes: not VALID
    shutil.copy(PDF, moved)
    s2 = PabloSkill(IntentEngine(), path=os.path.join(d, "s2", "skill.json"))
    src2 = s2.capture_pdf(moved)
    e2 = s2.add_anchor(src2.id, "reduces indexing time by over 77%")
    with open(moved, "ab") as f:
        f.write(b"\n% appended\n")
    r = s2.resolve_anchor(e2.id)
    assert r.status == "VALID" and r.resolution["reason"] == "relocated", r.resolution
    os.remove(moved)
    assert s2.resolve_anchor(e2.id).resolution["reason"] == "fetch_failed"


def test_ask_and_viewer():
    d = tempfile.mkdtemp()
    s = PabloSkill(IntentEngine(), judge=Judge(), path=os.path.join(d, "skill.json"))
    s.capture_pdf(PDF)
    t = s.start_task("LinearRAG 논문 읽기", checks=[])
    sc, dropped = s.ask(t.id, "LinearRAG가 baseline보다 효율적이라는 실험 근거가 어디 있어?")
    assert [x["n"] for x in dropped] == [2]
    assert sc.outcome == "PARTIALLY_VERIFIED" and sc.conclusion == \
        "저자는 77% 이상 줄였다고 씁니다[1]. Table 2는 249.78 s입니다[2]. 없는 문장.", sc.conclusion
    links = [(x.note, s.get_anchor(x.evidence_id).selector["page"]) for x in s.state.links if x.target_id == sc.id]
    assert links == [("claim", 2), ("table", 9)], links  # the judge's wrong page 4 is corrected by the unique quote
    m = model(s, t.id)
    a = m["anchors"][m["checks"][sc.id]["evidence"][1]]
    src = m["sources"][a["source"]]
    assert src["kind"] == "pdf" and src["intact"] and src["pages"] == len(s.snapshot_text(s.state.sources[0]).split("\f"))
    assert a["page"] == 9 and src["text"][a["start"]:a["end"]] == a["exact"]  # global offsets: snapshot fallback works
    html = render_html(s, t.id)
    assert '"pdf": true' in html and "pdfPanel" in html


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
