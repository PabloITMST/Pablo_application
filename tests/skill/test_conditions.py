"""⑩ (0.8 review): the user's own hand on the reproduction conditions. Run: python tests/skill/test_conditions.py
A sentence picked in the paper becomes a condition (anchored on its page, or refused); a condition is taken out with
why and put back. Small generated PDFs (ui_fixture.tiny_pdf), stub judges, no network.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "..", "src")
sys.path.insert(0, SRC)
sys.path.insert(0, HERE)

from pablo_v2.intent.engine import IntentEngine  # noqa: E402
from pablo_v2.skill.evidence import AnchorRejected  # noqa: E402
from pablo_v2.skill.skill import PabloSkill, deviation, render_audit, render_brief  # noqa: E402
from pablo_v2.skill.viewer import model, workspace  # noqa: E402
from ui_fixture import TINY_A, TINY_B, tiny_pdf  # noqa: E402

PICKED = "Indexing takes 12\nseconds on one  GPU."  # as a selection in the PDF panel comes: a line break, two spaces


class SpecJudge:  # each paper's conditions: one result from that paper, one setting it does not state
    def extract_spec(self, pages):
        own = "TinyRAG reaches 61.5 accuracy on HotpotQA" if "TinyRAG" in pages[1] else "OtherRAG reaches 58.2 accuracy on HotpotQA"
        return {"items": [{"category": "result", "statement": "HotpotQA 정확도", "value": own.split()[2], "quote": own, "page": 2}],
                "missing": [{"category": "training", "statement": "시드가 없다"}]}


def two(d):
    s = PabloSkill(IntentEngine(), SpecJudge())
    t = s.start_task("TinyRAG 재현", [])
    pa, pb = os.path.join(d, "a.pdf"), os.path.join(d, "OtherRAG.pdf")
    open(pa, "wb").write(tiny_pdf(TINY_A, "TinyRAG: A Tiny Graph RAG"))
    open(pb, "wb").write(tiny_pdf(TINY_B, "OtherRAG"))
    return s, t, s.capture_pdf(pa, arxiv="2501.00001"), s.capture_pdf(pb)


def refused(fn, kind, says=""):
    try:
        fn()
    except kind as e:
        assert says in str(e), e
        return
    raise AssertionError(f"not refused: {kind.__name__}")


def held(s, t):  # what the brief tells the agent and what 재현 점검 checks
    return render_brief(s, t)[0], [x["value"] for x in render_audit(s, t)[1] if x["kind"] == "condition"]


def test_add_a_picked_sentence():
    """A sentence the extraction missed, picked on its page: anchored like an extracted condition, so the brief and
    재현 점검 hold it; a sentence that is not in the paper, another paper's sentence or no kind is refused."""
    with tempfile.TemporaryDirectory() as d:
        s, t, a, b = two(d)
        assert set(workspace(s)["papers"]) == {a.id, b.id}  # a PDF opens before any citation of it
        assert workspace(s)["papers"][b.id]["pages"] == 2
        s.spec(t.id, a.id)
        sc = s.add_spec(t.id, a.id, PICKED, 2, "result", "색인 시간은 GPU 한 장에서 12초", "12")
        assert sc.research_state == "completed" and sc.outcome == "VERIFIED" and sc.spec["by"] == "user"
        v = model(s, t.id)
        (e,) = v["checks"][sc.id]["evidence"]
        assert v["anchors"][e]["page"] == 2 and v["anchors"][e]["exact"].startswith("Indexing takes 12"), v["anchors"][e]
        brief, values = held(s, t.id)
        assert "색인 시간은 GPU 한 장에서 12초" in brief and values == ["61.5", "12"], (brief, values)
        assert s.add_spec(t.id, a.id, PICKED, 1, "result", "같은 문장, 쪽을 잘못 앎", "12").outcome == "VERIFIED"  # found elsewhere
        assert s.add_spec(t.id, a.id, PICKED, 2, "result", "값이 인용에 없음", "99").spec["value_in_quote"] is False
        refused(lambda: s.add_spec(t.id, a.id, "Indexing takes 3 seconds", 2, "result", "없는 문장"), AnchorRejected, "찾지 못했습니다")
        refused(lambda: s.add_spec(t.id, b.id, "OtherRAG reaches 58.2 accuracy", 2, "result", "다른 논문"), ValueError, "TinyRAG")
        refused(lambda: s.add_spec(t.id, a.id, PICKED, 2, "gpu", "종류 없음"), ValueError)
        refused(lambda: s.add_spec(t.id, a.id, PICKED, 2, "result", "  "), ValueError)


def test_take_out_and_put_back():
    """A condition taken out needs why; the brief and 재현 점검 stop holding it, the record keeps when and why, and it
    comes back as it was, unless another paper's conditions were extracted since."""
    with tempfile.TemporaryDirectory() as d:
        s, t, a, b = two(d)
        stated, missing, _ = s.spec(t.id, a.id)
        res, seed = stated[0], missing[0]
        refused(lambda: s.drop_spec(res.id, " "), ValueError, "이유")
        s.drop_spec(res.id, "표의 다른 설정에서 나온 값")
        s.drop_spec(seed.id, "학습하지 않는 방법")
        assert (res.research_state, res.waived_by) == ("waived", "user")
        brief, values = held(s, t.id)
        assert values == [] and "61.5" not in brief and "시드" not in brief, brief
        c = model(s, t.id)["checks"][res.id]
        assert (c["waived_by"], c["waive_reason"]) == ("user", "표의 다른 설정에서 나온 값") and c["spec"]["dropped"][0]["to"] is None
        refused(lambda: s.drop_spec(res.id, "다시"), KeyError)
        s.restore_spec(res.id), s.restore_spec(seed.id)
        assert (res.research_state, res.outcome, seed.research_state) == ("completed", "VERIFIED", "pending")
        assert res.spec["dropped"][0]["to"] and res.waived_by is None and held(s, t.id)[1] == ["61.5"]
        refused(lambda: s.restore_spec(res.id), KeyError)
        s.drop_spec(res.id, "다시 뺌")
        s.spec(t.id, b.id)  # B's conditions now: A's cannot come back over them
        refused(lambda: s.restore_spec(res.id), ValueError, "다른 논문")
        assert len(res.spec["dropped"]) == 2


class GuardJudge(SpecJudge):  # the judge says an action contradicts the result condition, when it is given that fact
    def analyze_action(self, description, justification, step, constraints, facts):
        sid = next((ln.split()[0] for ln in facts.splitlines() if "HotpotQA 정확도" in ln), None)
        return {"intent_conflicts": [], "justification": {"present": False, "relevant": False, "supported_by": []},
                "source_conflicts": [{"source_check_id": sid, "kind": "contradicts", "note": ""}] if sid else [],
                "plan_alignment": {"follows_step": True}}


def test_intended_deviation():
    """⑦ the user differs from a paper condition on purpose, with why: the Guard no longer blocks on it (S01), the brief
    says it apart with the reason, the condition stays a cited fact; back to the paper, the Guard holds it again."""
    with tempfile.TemporaryDirectory() as d:
        s, t, a, _ = two(d)
        s.judge = GuardJudge()
        (res,), (seed,), _ = s.spec(t.id, a.id)
        rules = lambda d="평가 정확도를 70으로 맞춘다": [  # noqa: E731 (G02: no plan in this test)
            r["rule"] for r in s.propose_action(t.id, d).reasons if r["rule"] != "G02"]
        assert "S01" in rules()
        refused(lambda: s.deviate_spec(res.id, "  "), ValueError, "이유")
        refused(lambda: s.deviate_spec(seed.id, "x"), KeyError)  # what the paper does not state: nothing to differ from
        s.deviate_spec(res.id, "ablation: 다른 모델로 비교")  # the user's default (10/14): in separate runs only
        refused(lambda: s.deviate_spec(res.id, "again"), ValueError, "이미")
        assert rules() == ["S06"] and res.outcome == "VERIFIED"  # a command / a new file: the separate run is allowed
        edit = rules("파일 수정: config.yaml\n-acc: 61.5\n+acc: 70")
        assert edit == ["S07"], edit  # the base run's file: asked about (WARN), not blocked, not let through
        brief = render_brief(s, t.id)[0]
        assert "일부러 논문과 다르게 두는 조건" in brief and "이유: ablation: 다른 모델로 비교 (기본 실행은 논문대로" in brief, brief
        assert "확인된 근거:" not in brief  # its only fact is the one differed from
        assert held(s, t.id)[1] == ["61.5"]  # 재현 점검 still compares it (the card shows the difference as intended)
        s.undeviate_spec(res.id)
        assert "S01" in rules() and "일부러" not in render_brief(s, t.id)[0]
        assert [x["why"] for x in res.spec["deviations"]] == ["ablation: 다른 모델로 비교"] and res.spec["deviations"][0]["to"]
        refused(lambda: s.undeviate_spec(res.id), KeyError)
        s.deviate_spec(res.id, "GPU가 달라 이 작업 전체를 다르게", "task")  # the whole task: the Guard is not given it at all
        assert rules() == [] and rules("파일 수정: config.yaml") == []
        assert "(이 작업 전체에서 다르게)" in render_brief(s, t.id)[0]
        refused(lambda: s.undeviate_spec(res.id) and s.deviate_spec(res.id, "x", "everywhere"), ValueError)


class KindJudge(SpecJudge):  # ⑥ a setting, a result, a fact about the data and a baseline's own setting
    def extract_spec(self, pages):
        return {"items": [
            {"category": "result", "kind": "result", "statement": "HotpotQA 정확도는 61.5", "value": "61.5",
             "quote": "TinyRAG reaches 61.5 accuracy on HotpotQA", "page": 2},
            {"category": "dataset", "kind": "fact", "statement": "질문은 1,000개씩", "value": "1,000",
             "quote": "We evaluate on HotpotQA and MuSiQue with 1,000 questions each", "page": 1},
            {"category": "training", "kind": "scope", "statement": "색인에 GPU 한 장, 12초", "value": "12",
             "quote": "Indexing takes 12 seconds on one GPU", "page": 2},
            {"category": "method", "statement": "엔티티 링킹은 동의어를 무시한다", "value": "",  # no kind: a setting (before ⑥)
             "quote": "entity linking ignores synonyms", "page": 2}], "missing": []}


def test_table_row_without_its_columns():
    """review: a result quoted as a table row with no column names is flagged (which number is which dataset is the
    model's guess); a sentence that names them, or a row that does, is not; a baseline is the paper's scope."""
    from pablo_v2.skill.skill import header_missing
    row = "LinearRAG (Ours) 64.30 66.50 70.20 63.70 33.90 37.00 63.72"
    assert header_missing("LinearRAG는 HotpotQA, 2Wiki, MuSiQue, Medical에서 각각 64.30, 66.50, 70.20, 63.70을 보고한다", row, "result")
    assert header_missing("LinearRAG의 전체 파이프라인 정확도는 66.95이다", "LinearRAG (Ours) 249.78 0.093 0 0 66.95", "result")
    assert not header_missing("2Wiki의 GPT-Acc는 63.70이다", "LinearRAG achieves 63.70% GPT-based accuracy on 2Wiki", "result")
    assert not header_missing("HotpotQA 61.5, MuSiQue 40.2, 2Wiki 55.0", "HotpotQA 61.5 MuSiQue 40.2 2Wiki 55.0", "result")
    assert not header_missing("x", row, "setting")
    with tempfile.TemporaryDirectory() as d:
        s, t, a, _ = two(d)

        class Rows(SpecJudge):
            def extract_spec(self, pages):
                return {"items": [
                    {"category": "baseline", "kind": "setting", "statement": "비교 대상은 OtherRAG", "value": "",
                     "quote": "We evaluate on HotpotQA and MuSiQue with 1,000 questions each", "page": 1}], "missing": []}
        s.judge = Rows()
        (c,), _, _ = s.spec(t.id, a.id)
        assert c.spec["kind"] == "scope"


def test_kinds():
    """⑥ what a reproduction does with each condition: facts and the paper's other experiments are kept (cited, in the
    card, as background in the brief) but 재현 점검 and the Guard leave them out; a condition without a kind is a setting."""
    with tempfile.TemporaryDirectory() as d:
        s, t, a, _ = two(d)
        s.judge = KindJudge()
        stated, _, dropped = s.spec(t.id, a.id)
        assert not dropped and [c.spec.get("kind") for c in stated] == ["result", "fact", "scope", None]
        _, items = render_audit(s, t.id)
        assert [x["text"].split(" (")[0] for x in items if x["kind"] == "condition"] == ["HotpotQA 정확도는 61.5", "엔티티 링킹은 동의어를 무시한다"]
        brief = render_brief(s, t.id)[0]
        assert "참고 (논문의 서술과 이 재현 밖의 실험, 따를 조건은 아님):\n- [서술] 질문은 1,000개씩" in brief, brief
        assert "- [실험 범위] 색인에 GPU 한 장, 12초" in brief and brief.index("확인된 근거:") < brief.index("참고 (")
        s.judge = GuardJudge()  # cites the result line it is given; the fact and the scope are not given at all
        act = s.propose_action(t.id, "x")
        assert "S01" in [r["rule"] for r in act.reasons]


def test_extract_again_keeps_the_users_work():
    """0.8 review: extracting the same paper again replaced everything, the user's own work included. Now what the user
    added, differs from on purpose or took out stays as they left it (not twice, not back); what the last extraction had
    and this one did not find is said, and can be restored (kept like the user's own from then on)."""
    R = ("result", "result", "HotpotQA 정확도는 61.5", "61.5", "TinyRAG reaches 61.5 accuracy on HotpotQA", 2)
    I = ("training", "setting", "색인은 GPU 한 장에서 12초", "12", "Indexing takes 12 seconds on one GPU", 2)
    D = ("dataset", "fact", "질문은 1,000개씩", "1,000", "We evaluate on HotpotQA and MuSiQue with 1,000 questions each", 1)
    U = ("method", "setting", "엔티티 링킹은 동의어를 무시한다", "", "entity linking ignores synonyms", 2)
    N = ("method", "setting", "TinyRAG는 작은 그래프 검색 방법이다", "", "TinyRAG: a tiny graph retrieval method", 1)

    class Runs(SpecJudge):
        runs = [[R, I, D], [R, D, U, N]]

        def extract_spec(self, pages):
            items = self.runs.pop(0)
            return {"items": [dict(zip(("category", "kind", "statement", "value", "quote", "page"), x)) for x in items], "missing": []}
    with tempfile.TemporaryDirectory() as d:
        s, t, a, _ = two(d)
        s.judge = Runs()
        (r, i, dd), _, _ = s.spec(t.id, a.id)
        assert s.spec_diff["first"]
        s.deviate_spec(r.id, "ablation: 다른 모델로 비교")
        s.drop_spec(dd.id, "데이터 설명이라 조건이 아님")
        u = s.add_spec(t.id, a.id, U[4], 2, "method", U[2])
        (n,), _, _ = s.spec(t.id, a.id)  # R, D and U came again: the user's versions stay, nothing twice
        diff = s.spec_diff
        assert (n.spec["value"], diff["before"], diff["same"], diff["new"], diff["gone"]) == ("", 1, 0, [n.id], [i.id]), diff
        assert sorted(diff["kept"]) == sorted([r.id, u.id]) and sorted(diff["again"]) == sorted([r.id, u.id]) and diff["out"] == [dd.id]
        assert r.research_state == "completed" and deviation(r)["why"] == "ablation: 다른 모델로 비교"  # the ablation still holds
        assert u.research_state == "completed" and (dd.research_state, dd.waived_by) == ("waived", "user")
        assert (i.research_state, i.waive_reason) == ("waived", "replaced by a new extraction")
        live = [c.id for c in s.checks(t.id) if c.spec and c.research_state != "waived"]
        assert sorted(live) == sorted([r.id, u.id, n.id]), live
        s.restore_spec(i.id)  # the one this extraction missed, back, and kept from now on
        assert i.research_state == "completed" and i.spec["kept"] is True


def test_report():
    """⑫ the report: papers with their official code, conditions with their pages, the fixed sections (what differs on
    purpose, what was taken out and why) and the criteria; [n] never appears (a report is read apart from the app)."""
    from pablo_v2.skill.viewer import render_report
    with tempfile.TemporaryDirectory() as d:
        s, t, a, _ = two(d)
        (res,), (seed,), _ = s.spec(t.id, a.id)
        s.deviate_spec(res.id, "ablation: 다른 모델로 비교")
        s.drop_spec(seed.id, "학습하지 않는 방법")
        md = render_report(s, t.id)
        assert md.startswith("# 재현 보고서: TinyRAG 재현\n") and "**TinyRAG** v2 · arXiv 2501.00001" in md, md[:400]
        assert "- HotpotQA 정확도 — TinyRAG p.2" in md
        assert "## 논문과 다르게 한 것 (의도한 차이)\n\n- HotpotQA 정확도 — 이유: ablation: 다른 모델로 비교 · 범위: 별도 실행에서만" in md
        assert "- 뺀 조건: 시드가 없다 — 이유: 학습하지 않는 방법" in md and "아직 재현 점검을 하지 않았습니다." in md
        assert not re.search(r"\[\d+\]", md)


def test_reads_are_not_departures():
    """real --guard (10/14): reading a file to do the step was warned as leaving the plan (D01) 3 times in one run. A
    command that only reads is part of any step; one that writes, deletes or runs code is judged as before."""
    class Wanders(SpecJudge):  # the judge says every action departs from the step
        def analyze_action(self, *_):
            return {"intent_conflicts": [], "source_conflicts": [], "plan_alignment": {"follows_step": False},
                    "justification": {"present": False, "relevant": False, "supported_by": []}}
    s = PabloSkill(IntentEngine(), Wanders())
    t = s.start_task("hello.txt에 줄 더하기", [])
    s.create_plan(t.id, [{"action": "hello.txt 끝에 world 줄을 더한다", "basis": []}])
    pwsh = '명령 실행: "C:\\Program Files\\PowerShell\\7\\pwsh.exe" -Command '
    verdict = lambda d: (lambda a: (a.verdict, [r["rule"] for r in a.reasons]))(s.propose_action(t.id, d, "P1.1"))  # noqa: E731
    for read in ['"Get-Content -LiteralPath .\\hello.txt -Tail 5"', "'git diff -- hello.txt; git status --short'",
                 '"Get-Item -LiteralPath .\\keep.txt | Select-Object FullName,Length"']:
        assert verdict(pwsh + read) == ("ALLOW", []), read
    assert verdict(pwsh + '"git branch -a"') == ("ALLOW", [])
    for change in ['"Remove-Item keep.txt"', '"Get-Content a.txt > b.txt"', '"python run.py"', '"git checkout -- hello.txt"',
                   '"git branch exp"', '"git branch --set-upstream-to=origin/main"', '"git diff --output=d.patch"']:
        assert verdict(pwsh + change) == ("WARN", ["D01"]), change
    assert verdict("파일 수정: hello.txt") == ("WARN", ["D01"])


def cli(d, *args):
    r = subprocess.run([sys.executable, "-m", "pablo_v2", *args, "--json", "--dir", d], capture_output=True, encoding="utf-8",
                       env={**os.environ, "PYTHONPATH": SRC, "PYTHONIOENCODING": "utf-8"})
    return r.returncode, json.loads(r.stdout) if r.stdout.strip() else None


def test_cli():
    """What the desktop runs: add-spec (the check with its anchor, for the conversation), drop-spec (why required), restore-spec."""
    with tempfile.TemporaryDirectory() as d:
        pa = os.path.join(d, "a.pdf")
        open(pa, "wb").write(tiny_pdf(TINY_A, "TinyRAG: A Tiny Graph RAG"))
        cli(d, "task", "TinyRAG 재현", "--checks", "[]")
        _, src = cli(d, "source", pa)
        sid = src["source"]["id"]
        code, r = cli(d, "add-spec", "T1", "--source", sid, "--page", "2", "--quote", PICKED, "--category", "result",
                      "--statement", "색인 시간은 12초", "--value", "12")
        assert code == 0 and r["check"]["spec"]["by"] == "user", r
        (e,) = r["check"]["evidence"]
        assert r["anchors"][e]["page"] == 2 and r["sources"][sid]["kind"] == "pdf"
        code, r2 = cli(d, "add-spec", "T1", "--source", sid, "--page", "2", "--quote", "not in the paper at all",
                       "--category", "result", "--statement", "x")
        assert code == 2 and "찾지 못했습니다" in r2["message"], r2
        assert cli(d, "drop-spec", r["check"]["id"])[0] != 0  # argparse: --reason is required
        code, r3 = cli(d, "drop-spec", r["check"]["id"], "--reason", "잘못 고름")
        assert code == 0 and r3["check"]["research_state"] == "waived", r3
        code, r4 = cli(d, "restore-spec", r["check"]["id"])
        assert code == 0 and r4["check"]["research_state"] == "completed", r4
        assert cli(d, "deviate", r["check"]["id"])[0] != 0  # argparse: --reason is required
        code, r5 = cli(d, "deviate", r["check"]["id"], "--reason", "GPU가 달라 색인 시간은 비교만 함")
        assert code == 0 and r5["check"]["spec"]["deviations"][-1]["to"] is None, r5
        code, r6 = cli(d, "undeviate", r["check"]["id"])
        assert code == 0 and r6["check"]["spec"]["deviations"][-1]["to"], r6


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
