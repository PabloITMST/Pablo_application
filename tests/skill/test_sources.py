"""0.8 Phase C: several papers per task, arXiv metadata, a comparison table. Run: python tests/skill/test_sources.py
Stub judges and small generated PDFs (ui_fixture.tiny_pdf) only; no network, no LinearRAG.pdf needed.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))
sys.path.insert(0, HERE)

from pablo_v2.intent.engine import IntentEngine  # noqa: E402
from pablo_v2.skill import skill as skill_mod  # noqa: E402
from pablo_v2.skill.skill import PabloSkill, TooMuchText, render_audit, render_brief  # noqa: E402
from pablo_v2.skill.viewer import model  # noqa: E402
from ui_fixture import TINY_A, TINY_B, tiny_pdf  # noqa: E402

PAPERS_JS = os.path.join(HERE, "..", "..", "desktop", "papers.js")
SAME = "We evaluate on HotpotQA and MuSiQue with 1,000 questions each."  # page 1 of both papers


def two(d, judge):
    """A task with both tiny papers captured (A as arXiv 2501.00001, B as a local file)."""
    s = PabloSkill(IntentEngine(), judge)
    t = s.start_task("TinyRAG 재현", [])
    pa, pb = os.path.join(d, "a.pdf"), os.path.join(d, "OtherRAG.pdf")
    open(pa, "wb").write(tiny_pdf(TINY_A, "TinyRAG: A Tiny Graph RAG"))
    open(pb, "wb").write(tiny_pdf(TINY_B, "OtherRAG"))
    return s, t, s.capture_pdf(pa, arxiv="2501.00001"), s.capture_pdf(pb)


def test_arxiv_capture():
    """An arXiv PDF's title and version come from the PDF itself; a local file keeps its name."""
    with tempfile.TemporaryDirectory() as d:
        s, _, a, b = two(d, None)
        assert (a.title, a.version["arxiv"], a.version["arxiv_version"]) == ("TinyRAG", "2501.00001", "v2")
        assert b.title == "OtherRAG" and "arxiv" not in b.version


class AskJudge:  # cites the shared sentence from B, A's result on a wrong page, and a paper that is not there
    def __init__(self):
        self.seen = None

    def answer_from_sources(self, question, papers):
        self.seen = papers
        return {"answer": "TinyRAG는 61.5입니다 [1]. OtherRAG도 같은 데이터로 평가합니다 [2]. 셋째 [3].", "citations": [
            {"n": 1, "paper": "A", "page": 1, "quote": "TinyRAG reaches 61.5 accuracy on HotpotQA", "role": "table"},
            {"n": 2, "paper": "B", "page": 1, "quote": SAME, "role": "text"},
            {"n": 3, "paper": "C", "page": 1, "quote": SAME, "role": "text"}]}


def test_ask_several_papers():
    """One question over two papers: each quote is anchored in the paper the answer names (a sentence both papers have
    goes to B when B is cited), a wrong page is found elsewhere in that paper, a paper that is not there is dropped."""
    with tempfile.TemporaryDirectory() as d:
        j = AskJudge()
        s, t, a, b = two(d, j)
        sc, dropped = s.ask(t.id, "두 논문의 HotpotQA 결과는?", [a.id, b.id])
        assert [(x["label"], x["title"]) for x in j.seen] == [("A", "TinyRAG"), ("B", "OtherRAG")]
        where = [(x.source_id, x.selector["page"]) for _, x in s.evidence_for(sc.id)]
        assert where == [(a.id, 2), (b.id, 1)], where
        assert [x["paper"] for x in dropped] == ["C"] and sc.outcome == "PARTIALLY_VERIFIED"
        assert "[1]" in sc.conclusion and "[2]" in sc.conclusion and "[3]" not in sc.conclusion, sc.conclusion
        assert {x["title"] for x in sc.sources} == {"TinyRAG", "OtherRAG"}
        text, _ = render_brief(s, t.id)
        assert "(TinyRAG p.2" in text and "OtherRAG p.1" in text, text
        old = skill_mod.ASK_CHARS
        skill_mod.ASK_CHARS = 100  # too much text for one question: the user is asked to pick papers
        try:
            s.ask(t.id, "x", [a.id, b.id])
            raise AssertionError("TooMuchText expected")
        except TooMuchText as e:
            assert "물어볼 자료를 골라" in str(e)
        finally:
            skill_mod.ASK_CHARS = old


WEB = ("<html><head><title>TinyRAG notes</title></head><body><h1>Notes</h1>"
       "<p>The default run uses a top-k of 5 in the retrieval step.</p><p>Indexing is fast.</p>"
       "<p>The cached run uses a top-k of 5 in the retrieval step as well.</p></body></html>")
REPEAT = "uses a top-k of 5 in the retrieval step"  # twice on the page


class WebJudge:  # a paper's quote, the web page's repeated quote told apart by near, the same quote without near
    def __init__(self, only_web=False):
        self.seen, self.only_web = None, only_web

    def answer_from_sources(self, question, papers):
        self.seen = papers
        web = [{"n": 1, "paper": "B", "page": 0, "quote": REPEAT, "near": "The cached run", "role": "text"},
               {"n": 2, "paper": "B", "page": 0, "quote": REPEAT, "near": "", "role": "text"}]
        if self.only_web:  # the page alone: it is source A
            return {"answer": "캐시 실행도 top-k 5입니다 [1].", "citations": [{**web[0], "paper": "A"}]}
        return {"answer": "TinyRAG는 61.5입니다 [1]. 캐시 실행도 top-k 5입니다 [2]. 기본 실행도 같습니다 [3].", "citations": [
            {"n": 1, "paper": "A", "page": 2, "quote": "TinyRAG reaches 61.5 accuracy on HotpotQA", "near": "", "role": "table"},
            {**web[0], "n": 2}, {**web[1], "n": 3}]}


def test_ask_web_page():
    """D1: a web page is a source of an answer next to a paper. It has no pages; a quote it repeats is anchored at the
    occurrence next to the judge's near words, and without them it is dropped (never the first one by luck). An answer
    on web quotes alone is at most PARTIALLY_VERIFIED: Pablo cannot tell how authoritative a page the user picked is."""
    with tempfile.TemporaryDirectory() as d:
        j = WebJudge()
        s, t, a, _ = two(d, j)
        fetched = []
        s.fetch = lambda url: fetched.append(url) or WEB
        w = s.capture_source("https://example.org/tinyrag-notes")
        assert (w.kind, w.title) == ("web", "TinyRAG notes")
        sc, dropped = s.ask(t.id, "top-k는?", [a.id, w.id])
        assert [(x["kind"], len(x["pages"])) for x in j.seen] == [("pdf", 2), ("web", 1)]
        text = s.snapshot_text(w)
        cached = text.index(REPEAT, text.index("The cached run"))
        assert [(x.source_id, x.selector.get("page"), x.selector["start"]) for _, x in s.evidence_for(sc.id)] == \
            [(a.id, 2, s.evidence_for(sc.id)[0][1].selector["start"]), (w.id, None, cached)]
        assert len(dropped) == 1 and "2 times" in dropped[0]["why"]  # the repeated quote without near
        assert [(x["tier"], x["type"]) for x in sc.sources] == [(4, "pdf"), (5, "web")]
        s.judge = WebJudge(only_web=True)
        web_only, none = s.ask(t.id, "캐시 실행의 top-k는?", [w.id])
        assert not none and len(s.evidence_for(web_only.id)) == 1  # kept, and still not VERIFIED on a page alone
        assert web_only.outcome == "PARTIALLY_VERIFIED" and web_only.sources[0]["tier"] == 5
        # the page changed elsewhere: both anchors still there, found with one fetch of the page
        n = len(fetched)
        s.fetch = lambda url: fetched.append(url) or WEB.replace("The default run", "The base run")
        got = [(x.status, (x.resolution or {}).get("reason")) for x in s.resolve_source(w.id)]
        assert len(fetched) == n + 1 and got == [("VALID", "relocated")] * 2, got

        def down(url):
            fetched.append(url)
            raise OSError("offline")
        s.fetch = down  # unreachable: one try, recorded on every anchor
        got = [(x.status, x.resolution["reason"]) for x in s.resolve_source(w.id)]
        assert len(fetched) == n + 2 and got == [("UNRESOLVED", "fetch_failed")] * 2, got


class CompareJudge:  # A: two cells anchor, one quote is not in the paper, one column it does not state
    def compare_paper(self, columns, title, pages):
        assert columns == ["데이터셋", "주요 결과", "효율", "한계"] and len(pages) == 2
        if title == "TinyRAG":
            return {"cells": [
                {"column": "데이터셋", "value": "HotpotQA, MuSiQue", "quote": SAME, "page": 1},
                {"column": "주요 결과", "value": "HotpotQA 61.5", "metric": " accuracy ", "quote": "TinyRAG reaches 61.5 accuracy on HotpotQA", "page": 2},
                {"column": "효율", "value": "색인 3초", "quote": "Indexing takes 3 seconds", "page": 2},  # not what it says
                {"column": "한계", "value": "", "quote": "", "page": 0}]}
        return {"cells": [
            {"column": "데이터셋", "value": "HotpotQA, MuSiQue", "quote": SAME, "page": 1},
            {"column": "주요 결과", "value": "HotpotQA 58.2", "quote": "OtherRAG reaches 58.2 accuracy on HotpotQA", "page": 2},
            {"column": "효율", "value": "색인 95초", "quote": "Indexing takes 95 seconds on one GPU", "page": 2},
            {"column": "한계", "value": "효율은 색인 시간만", "quote": "We do not study efficiency beyond indexing time", "page": 2}]}

    def analyze_action(self, action, justification, step, constraints, checks):
        self.checks = checks
        return {"intent_conflicts": [], "source_conflicts": [], "plan_alignment": {"follows_step": True, "note": ""},
                "justification": {"present": False, "relevant": False, "supported_by": [], "note": ""}}


def test_compare_table():
    """Each cell is anchored in its own paper or left empty (never a value without a place); the cells are records
    the user reads, not facts the Guard or the agent's brief use."""
    with tempfile.TemporaryDirectory() as d:
        j = CompareJudge()
        s, t, a, b = two(d, j)
        mid, cells, empty = s.compare(t.id, [a.id, b.id], ["데이터셋", "주요 결과", "효율", "한계"])
        assert mid == "M1" and len(cells) == 6
        assert sorted((x["source_id"], x["column"]) for x in empty) == [(a.id, "한계"), (a.id, "효율")]
        assert "not found" in next(x for x in empty if x["column"] == "효율")["why"]
        assert len([c for c in s.state.checks if c.matrix]) == 6  # no record for an empty cell
        for c in cells:
            ev = s.evidence_for(c.id)
            assert len(ev) == 1 and ev[0][1].source_id == c.matrix["source_id"] and c.outcome == "VERIFIED"
        same = [s.evidence_for(c.id)[0][1].source_id for c in cells if c.matrix["column"] == "데이터셋"]
        assert same == [a.id, b.id]  # the sentence both papers have: anchored in each row's own paper
        v = model(s, t.id)["checks"][cells[0].id]
        assert v["matrix"] == {"id": "M1", "column": "데이터셋", "source_id": a.id} and v["paper"] == "TinyRAG"
        # ⑧ what a number measures is kept with its cell (trimmed); a cell that is not a measurement has none
        assert [c.matrix.get("metric") for c in cells if c.matrix["source_id"] == a.id] == [None, "accuracy"]
        assert render_brief(s, t.id) == ("", [])  # nothing for the agent
        s.propose_action(t.id, "명령 실행: python eval.py")
        assert not any(c.id in j.checks for c in cells)  # nor for the Guard
        for bad in ([a.id], [a.id, a.id]):
            try:
                s.compare(t.id, bad)
                raise AssertionError("two papers needed")
            except ValueError:
                pass
        # ⑧ the name the user knows a paper by: the model and the brief use it; its anchors stay
        s.rename_source(b.id, "  Other  RAG ")
        assert s.get_source(b.id).title == "Other RAG" and model(s, t.id)["checks"][cells[-1].id]["paper"] == "Other RAG"
        for bad in ("", " ", "x" * 121):
            try:
                s.rename_source(b.id, bad)
                raise AssertionError("a name is 1-120 characters")
            except ValueError:
                pass
        # ⑧ review: one more column of this table, asked alone (one call per paper, that column only), same table id
        asked = []

        class OneColumn:
            def compare_paper(self, columns, title, pages):
                asked.append(columns)
                q = "TinyRAG reaches 61.5 accuracy on HotpotQA" if title == "TinyRAG" else "OtherRAG reaches 58.2 accuracy on HotpotQA"
                return {"cells": [{"column": columns[0], "value": q.split()[2], "metric": "accuracy", "quote": q, "page": 2}]}
        s.judge = OneColumn()
        mid2, more, none = s.compare(t.id, [a.id, b.id], ["HotpotQA 결과"], into="M1")
        assert mid2 == "M1" and asked == [["HotpotQA 결과"], ["HotpotQA 결과"]] and none == []
        assert [(c.matrix["id"], c.matrix["column"], c.conclusion) for c in more] == [("M1", "HotpotQA 결과", "61.5 [1]"), ("M1", "HotpotQA 결과", "58.2 [1]")]
        for bad, err in ((["HotpotQA 결과"], ValueError), (["x"], KeyError)):  # already there; no such table
            try:
                s.compare(t.id, [a.id, b.id], bad, into="M1" if err is ValueError else "M9")
                raise AssertionError(f"{bad} refused")
            except err:
                pass


class SpecJudge:  # each paper's conditions, quotes from that paper
    def extract_spec(self, pages):
        own = "TinyRAG reaches 61.5 accuracy on HotpotQA" if "TinyRAG" in pages[1] else "OtherRAG reaches 58.2 accuracy on HotpotQA"
        return {"items": [{"category": "result", "statement": "HotpotQA 정확도", "value": own.split()[2], "quote": own, "page": 2}],
                "missing": [{"category": "training", "statement": "시드가 없다"}]}


def test_one_paper_reproduced():
    """Conditions come from one paper at a time: extracting from B waives A's (kept, with why), so the Guard, the brief
    and 재현 점검 never hold two papers' settings."""
    with tempfile.TemporaryDirectory() as d:
        s, t, a, b = two(d, SpecJudge())
        s.spec(t.id, a.id)
        s.spec(t.id, b.id)
        live = [c for c in s.checks(t.id) if c.spec and c.research_state != "waived"]
        assert {c.spec["source_id"] for c in live} == {b.id} and len(live) == 2
        old = [c for c in s.checks(t.id) if c.spec and c.spec["source_id"] == a.id]
        assert old and all(c.research_state == "waived" and b.id in c.waive_reason for c in old)
        _, items = render_audit(s, t.id)
        assert [x["value"] for x in items if x["kind"] == "condition"] == ["58.2"]
        assert model(s, t.id)["checks"][live[0].id]["paper"] == "OtherRAG"


def test_new_version_resolves():
    """C2: a newer version saved over the paper's file is a new source; the old source's anchors are resolved against it
    (a sentence that stayed, with what is around it: VALID; one that changed: UNRESOLVED)."""
    with tempfile.TemporaryDirectory() as d:
        s, t, a, _ = two(d, None)
        keep = s.add_anchor(a.id, "TinyRAG reaches 61.5 accuracy on HotpotQA", page=2)
        gone = s.add_anchor(a.id, "entity linking ignores synonyms", page=2)
        v3 = [TINY_A[0].replace("v2", "v3"), TINY_A[1].replace("ignores synonyms", "ignores aliases")]
        open(a.locator, "wb").write(tiny_pdf(v3, "TinyRAG: A Tiny Graph RAG"))
        a3 = s.capture_pdf(a.locator, arxiv="2501.00001")
        assert a3.id != a.id and a3.version["arxiv_version"] == "v3"
        got = {x.id: x.status for x in s.resolve_source(a.id)}
        assert got == {keep.id: "VALID", gone.id: "UNRESOLVED"}, got


def node(calls):
    r = subprocess.run(["node", "-e", """const p = require(process.argv[1]);
const calls = JSON.parse(require("fs").readFileSync(0, "utf8"));
console.log(JSON.stringify(calls.map(([f, ...a]) => { try { const x = p[f](...a); return x === undefined ? null : x; }
  catch (e) { return { error: e.message }; } })));""", PAPERS_JS], input=json.dumps(calls), capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout)


def test_desk_papers():
    """desktop.json: 0.7's one PDF per task reads as a list of one; the 주 논문 is the one picked while it is still a
    paper of the task, else the first; arXiv ids in the forms people paste."""
    import shutil
    if not shutil.which("node"):
        print("skip test_desk_papers: no node")
        return
    old = {"pdf": {"T1": {"id": "SRC1", "title": "LinearRAG"}, "T2": [{"id": "SRC2", "title": "A"}, {"id": "SRC3", "title": "B"}]},
           "primary": {"T2": "SRC3"}}
    got = node([["list", old, "T1"], ["list", old, "T2"], ["list", old, "T9"], ["list", {}, "T1"],
                ["primary", old, "T1"], ["primary", old, "T2"], ["primary", {**old, "primary": {"T2": "SRC9"}}, "T2"],
                ["migrate", old]])
    assert got[:4] == [[{"id": "SRC1", "title": "LinearRAG"}], old["pdf"]["T2"], [], []]
    assert [x and x["id"] for x in got[4:7]] == ["SRC1", "SRC3", "SRC2"]
    assert got[7]["pdf"]["T1"] == [{"id": "SRC1", "title": "LinearRAG"}]
    ids = node([["arxiv", x] for x in ["2510.10114", "arXiv:2510.10114v4", "https://arxiv.org/abs/2510.10114v4",
                                         "https://arxiv.org/pdf/2510.10114v2.pdf", "arxiv.org/abs/2502.14802", " hep-th/9901001 ",
                                         "https://example.com/2510.10114", "LinearRAG", "2510.1011"]])
    assert ids == [{"id": "2510.10114", "version": None}, {"id": "2510.10114", "version": "v4"},
                   {"id": "2510.10114", "version": "v4"}, {"id": "2510.10114", "version": "v2"},
                   {"id": "2502.14802", "version": None}, {"id": "hep-th/9901001", "version": None}, None, None, None], ids


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
