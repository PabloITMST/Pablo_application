"""Product-polish tests (chat log, ...). Run: python tests/skill/test_product.py
Stub judges only; no network.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "..", "src")
sys.path.insert(0, SRC)
sys.path.insert(0, HERE)

from pablo_v2.__main__ import current_step  # noqa: E402
from pablo_v2.intent.engine import IntentEngine  # noqa: E402
from pablo_v2.skill.models import ActionProposal, ExecutionRecord, PostReview  # noqa: E402
from pablo_v2.skill.skill import PabloSkill, render_brief  # noqa: E402
from pablo_v2.skill.viewer import model, workspace  # noqa: E402
import ui_fixture  # noqa: E402

PDF = os.path.join(HERE, "..", "..", "LinearRAG.pdf")


def load(d):
    return PabloSkill.load(os.path.join(d, "skill.json"), IntentEngine.load(os.path.join(d, "intent.json")))


def test_chat_log():
    """The desktop's chat.json reaches the view model per task; its PDF answer keeps the check that answered it."""
    with tempfile.TemporaryDirectory() as d:
        ui_fixture.build(d)
        v = model(load(d), "T1")
        assert [c["role"] for c in v["chat"]] == ["user", "intent", "agent", "user", "agent", "ask", "spec"]
        assert v["chat"][4]["status"] == "interrupted" and v["chat"][5]["check"] in v["checks"]
        assert [a["at"] for a in v["actions"]] == [ui_fixture.at(20), ui_fixture.at(40)]
        with open(os.path.join(d, "chat.json"), "w", encoding="utf-8") as f:
            f.write("{broken")  # a damaged log costs the conversation, never the records
        assert model(load(d), "T1")["chat"] == [] and workspace(load(d))["views"]["T1"]["actions"]
        json.dump(["not", "a", "map"], open(os.path.join(d, "chat.json"), "w", encoding="utf-8"))
        assert model(load(d), "T1")["chat"] == []


def test_brief():
    """What the desktop agent is told: the task's criteria + located facts with their page, and the basis ids."""
    s = PabloSkill(IntentEngine(), None)
    t = s.start_task("LinearRAG 재현", [])
    assert render_brief(s, t.id) == ("", [])  # nothing to tell -> nothing is sent
    s.intent.process_message("test split은 절대 학습에 쓰지 마.")
    s.intent.process_message("가능하면 PyTorch로 짜줘.")
    if os.path.exists(PDF):  # LinearRAG.pdf is not in the repo (see README)
        from test_pdf import Judge
        s.judge = Judge()
        src = s.capture_pdf(PDF)
        sc, dropped = s.ask(t.id, "LinearRAG가 더 효율적인 근거는?", src.id)
        text, basis = render_brief(s, t.id)
        assert basis == [sc.id] and len(dropped) == 1
        assert "(LinearRAG p.2)" in text and "(LinearRAG p.9)" in text and "[1]" not in text, text
        assert "(일부만 확인됨)" in text  # one quote was not found: PARTIALLY_VERIFIED
    text, _ = render_brief(s, t.id)
    assert "반드시: test split은 절대 학습에 쓰지 마" in text and "가능하면: 가능하면 PyTorch로 짜줘" in text, text


class SpecJudge:  # extract_spec stub on LinearRAG.pdf: two results, a method step on a wrong page, one quote not in the paper
    def extract_spec(self, pages):
        assert len(pages) > 9
        return {"items": [
            {"category": "result", "statement": "LinearRAG의 색인 시간은 249.78초이다", "value": "249.78",
             "quote": "LinearRAG (Ours) 249.78 0.093 0 0 66.95", "page": 9},
            {"category": "result", "statement": "2Wiki에서 GPT 정확도는 63.70%이다", "value": "63.70%",
             "quote": "LinearRAG achieves 63.70% GPT-based accuracy on 2Wiki", "page": 8},
            {"category": "model", "statement": "문서 중요도는 personalized PageRank로 계산한다", "value": "PageRank",
             "quote": "In the second Stage, the model uses personalized PageRank algorithms", "page": 4},
            {"category": "dataset", "statement": "없는 데이터셋", "value": "X", "quote": "a dataset this paper never names", "page": 6}],
            "missing": [{"category": "training", "statement": "난수 시드가 적혀 있지 않다"}]}

    def analyze_action(self, action, justification, step, constraints, checks):
        sc = checks.split()[0]  # the first fact the judge was shown: the 249.78 s result
        return {"intent_conflicts": [], "plan_alignment": {"follows_step": True, "note": ""},
                "justification": {"present": False, "relevant": False, "supported_by": [], "note": ""},
                "source_conflicts": [{"source_check_id": sc, "kind": "contradicts", "note": "보고값을 바꿔 쓴다"}]}


def test_spec():
    """A paper's reproduction conditions: anchored on their page (or dropped), VERIFIED facts the Guard enforces (S01),
    in the agent's brief; what the paper does not state stays open; extracting again replaces the old set."""
    if not os.path.exists(PDF):
        print("skip test_spec: LinearRAG.pdf not here")
        return
    s = PabloSkill(IntentEngine(), SpecJudge())
    t = s.start_task("LinearRAG 재현", [])
    src = s.capture_pdf(PDF)
    stated, missing, dropped = s.spec(t.id, src.id)
    assert [c.spec["category"] for c in stated] == ["result", "result", "model"] and len(dropped) == 1
    pages = [s.evidence_for(c.id)[0][1].selector["page"] for c in stated]
    assert pages == [9, 8, 9]  # the method step's page was wrong: found where it is
    assert all(c.outcome == "VERIFIED" and c.sources[0]["tier"] == 4 for c in stated)
    assert len(missing) == 1 and missing[0].research_state == "pending" and missing[0].spec["missing"]
    text, basis = render_brief(s, t.id)
    assert "[보고된 결과] LinearRAG의 색인 시간은 249.78초이다 (LinearRAG p.9)" in text, text
    assert "근거 없이 바꾸지 마세요" in text and "[학습] 난수 시드가 적혀 있지 않다" in text
    assert basis == [c.id for c in stated]
    act = s.propose_action(t.id, "eval.py에서 색인 시간 249.78을 120으로 고쳐 쓴다")
    assert act.verdict == "BLOCK" and "S01" in [r["rule"] for r in act.reasons]  # against a verified paper condition
    s.spec(t.id, src.id)  # again: the earlier set is replaced, not doubled
    live = [c for c in s.checks(t.id) if c.spec and c.research_state != "waived"]
    assert len(live) == 4 and all(c.id not in {x.id for x in stated + missing} for c in live)
    v = model(s, t.id)
    assert v["checks"][live[0].id]["spec"]["category"] == "result"


class CountingJudge:  # no conflicts; counts model calls
    calls = 0

    def analyze_action(self, *a):
        CountingJudge.calls += 1
        return {"intent_conflicts": [], "source_conflicts": [], "plan_alignment": {"follows_step": True, "note": ""},
                "justification": {"present": False, "relevant": False, "supported_by": [], "note": ""}}


def test_rewrite_and_cache():
    """W01: an edit that removes most of an existing file warns without the model. The same action, step, criteria and
    facts reuse the judge's analysis (no second model call); anything different asks again."""
    s = PabloSkill(IntentEngine(), CountingJudge())
    t = s.start_task("train.py 정리", [])
    s.create_plan(t.id, [{"action": "train.py를 고친다", "basis": []}])
    big = s.propose_action(t.id, "파일 수정: train.py", "P1.1", rewrites=[{"path": "train.py", "lines": 120, "removed": 90}])
    small = s.propose_action(t.id, "파일 수정: train.py (작게)", "P1.1", rewrites=[{"path": "train.py", "lines": 120, "removed": 10}])
    tiny = s.propose_action(t.id, "파일 수정: a.py", "P1.1", rewrites=[{"path": "a.py", "lines": 12, "removed": 12}])
    assert big.verdict == "WARN" and [r["rule"] for r in big.reasons] == ["W01"] and "90줄" in big.reasons[0]["reason"]
    assert small.verdict == "ALLOW" and tiny.verdict == "ALLOW"  # a small file rewritten whole is not drift
    v = next(a for a in model(s, t.id)["actions"] if a["id"] == big.id)
    assert v["problems"][0].startswith("train.py의 기존 120줄 중 90줄")  # the card says what the rule saw
    n = CountingJudge.calls
    again = s.propose_action(t.id, "명령 실행: Get-Content train.py", "P1.1")
    same = s.propose_action(t.id, "명령 실행: Get-Content train.py", "P1.1")
    assert CountingJudge.calls == n + 1 and same.analysis_from == again.id and same.verdict == again.verdict
    s.intent.process_message("train.py는 절대 지우지 마.")  # the criteria changed: the judge is asked again
    s.propose_action(t.id, "명령 실행: Get-Content train.py", "P1.1")
    assert CountingJudge.calls == n + 2


def cli(d, *args):
    r = subprocess.run([sys.executable, "-m", "pablo_v2", *args, "--json", "--dir", d], capture_output=True, encoding="utf-8",
                       env={**os.environ, "PYTHONPATH": SRC, "PYTHONIOENCODING": "utf-8"})
    return r.returncode, json.loads(r.stdout)


def test_chat_criteria():
    """A chat message's criteria become intent of the task it was said in (not of the latest task); the request is no goal."""
    with tempfile.TemporaryDirectory() as d:
        cli(d, "task", "T1 작업", "--checks", "[]")
        cli(d, "task", "T2 작업", "--checks", "[]")
        _, r = cli(d, "say", "hello.txt에 world를 추가해줘. 다른 파일은 건드리지 마.", "--request", "--task", "T1")
        assert [(x["kind"], x["strength"], x["text"]) for x in r["added"]] == [("constraint", "hard", "다른 파일은 건드리지 마")]
        _, r2 = cli(d, "say", "이 프로젝트 구조 설명해줘", "--request", "--task", "T1")
        assert r2["added"] == [] and all(c["status"] == "ignored" for c in r2["candidates"])  # a request is not a goal
        s = load(d)
        ids = lambda t: [c.id for c in s.get_applicable_intent(t)["constraints"]]  # noqa: E731
        assert ids("T1") == [r["added"][0]["id"]] and ids("T2") == []  # said in T1 after T2 was made: still T1's
        assert s.intent.get_active_goals() == []
        code, _ = cli(d, "say", "x", "--request", "--task", "T9")
        assert code == 1  # unknown task


def test_current_step_after_done():
    """Follow-up actions on a finished request keep its step (no 'no plan step' WARN for every later edit)."""
    with tempfile.TemporaryDirectory() as d:
        cli(d, "task", "T1 작업", "--checks", "[]")
        cli(d, "plan", "T1", "--steps", json.dumps([{"action": "hello.txt에 줄 추가", "basis": []}]))
        s = load(d)
        assert current_step(s, "T1") == "P1.1"
        # the step is completed by a review (records written directly: no judge needed for this rule)
        s.state.actions.append(ActionProposal("ACT1", "T1", "파일 수정: hello.txt", "P1.1", verdict="ALLOW"))
        s.state.executions.append(ExecutionRecord("EX1", "ACT1", "proceed", True, "파일 수정: hello.txt"))
        s.state.reviews.append(PostReview("REV1", "EX1", "ACT1", {}, "aligned", "completed"))
        assert current_step(s, "T1") == "P1.1"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
