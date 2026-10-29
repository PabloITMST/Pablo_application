"""10/29: a 논문 질문 knows the task it is asked in, keeps the paper's answer apart from it, and "의논하자" is no criterion.
Run: python tests/skill/test_ask_context.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "..", "src")
sys.path.insert(0, SRC)

from pablo_v2.intent.engine import IntentEngine  # noqa: E402
from pablo_v2.intent.extract import HeuristicExtractor, asks_discussion  # noqa: E402
from pablo_v2.skill.skill import NO_PAPER_ANSWER, PabloSkill, render_brief, setting_name, task_context  # noqa: E402

PDF = os.path.join(HERE, "..", "..", "LinearRAG.pdf")


def cli(d, *args):
    r = subprocess.run([sys.executable, "-m", "pablo_v2", *args, "--json", "--dir", d], capture_output=True, encoding="utf-8",
                       env={**os.environ, "PYTHONPATH": SRC, "PYTHONIOENCODING": "utf-8"})
    return r.returncode, json.loads(r.stdout) if r.stdout.strip() else None


def test_discussion_is_no_criterion():
    """C2-C6 (10/29) were "의논해" typed into 정하기: 정하기 (say --decide) now refuses a value that asks to talk it over and
    stores nothing; the setting's name stays. Any other way to add or edit a criterion is not held to it."""
    for t in ["어떤 게 적절해보이는지 의논 해보자", "이것도 좀 의논이 필요해보이는데", "얘네도 의논해", "의논해", "같이 정하자", "어떻게 할까?"]:
        assert asks_discussion(t), t
    for t in ["가장 최신 버전으로 하자", "en_core_web_sm 3.7", "문장 단위?", "top_k는 반드시 5로 둬"]:
        assert not asks_discussion(t), t
    name = "사용할 spaCy 모델과 버전"
    with tempfile.TemporaryDirectory() as d:
        cli(d, "task", "LinearRAG 재현", "--checks", "[]")
        rule = ["--scope", "task", "--task", "T1", "--rule", "hard"]
        code, r = cli(d, "say", f"{name} = 얘네도 의논해", *rule, "--decide")
        assert code != 0 and "의논" in r["message"], r
        assert IntentEngine.load(os.path.join(d, "intent.json")).get_active_constraints() == []
        made = []
        for text, how in [(f"{name} = en_core_web_sm 3.7", ["--decide"]), ("청킹 규칙 = 문장 단위?", ["--decide"]),
                          ("결과가 논문과 다르면 왜 다른지 설명할 것?", []), ("팀과 상의한 하이퍼파라미터만 사용한다", []),
                          ("어떤 게 좋은지 실험으로 비교한다", [])]:  # 정하기 with a "?" value, then 기준 tab / 태그 additions
            code, r = cli(d, "say", text, *rule, *how)
            assert code == 0 and r["added"], (text, r)
            made.append(r["added"][0]["id"])
        code, r = cli(d, "restate", made[3], "논의된 데이터셋 외에는 쓰지 않는다?")  # 기준 tab: 고치기
        assert code == 0, r
        said = [c.statement for c in IntentEngine.load(os.path.join(d, "intent.json")).get_active_constraints()]
        assert said[0] == f"{name} = en_core_web_sm 3.7" and "논의된 데이터셋 외에는 쓰지 않는다?" in said, said


def test_setting_name():
    assert setting_name("사용할 정확한 spaCy 모델과 버전이 명시되지 않았다.") == "사용할 정확한 spaCy 모델과 버전"
    assert setting_name("생성 단계에서 사용할 구체적인 프롬프트 템플릿은 명시되지 않았다.") == "생성 단계에서 사용할 구체적인 프롬프트 템플릿"
    assert setting_name("난수 시드가 적혀 있지 않다") == "난수 시드"


class Judge:  # a 의논 request: the paper part unquoted, the task part (decided / open / suggestion) with a stray [1] to lose
    def __init__(self, answer="저자는 청킹을 문장 단위로 했다고 씁니다."):
        self.context, self.answer = None, answer

    def answer_from_pdf(self, question, pages, context=""):
        self.context = context
        return {"answer": self.answer, "citations": [],
                "task_note": "정함: spaCy 모델과 버전 [1].\n미정: 청킹 규칙.\n선택지: 문장 단위는 경계가 깔끔하고, 고정 길이는 길이가 고르다.\n제안: 문장 단위."}


def test_ask_gets_the_task_and_keeps_it_apart():
    d = tempfile.mkdtemp()
    j = Judge()
    s = PabloSkill(IntentEngine(), judge=j, path=os.path.join(d, "skill.json"))
    s.capture_pdf(PDF)
    t = s.start_task("LinearRAG 재현", checks=[])
    for req in ["사용할 spaCy 모델과 버전이 명시되지 않았다.", "청킹 규칙이 명시되지 않았다."]:
        c = s.add_check(t.id, req, "USEFUL")
        c.spec = {"category": "preprocessing", "value": "", "source_id": "SRC1", "missing": True}
    s.intent.extractor = HeuristicExtractor()  # as `say --rule hard --task T1` (정하기) reads it
    ex = s.intent.extractor.extract
    s.intent.extractor.extract = lambda *x: [dict(f, candidate=True, type="constraint", strength="hard", scope="task",
                                                  task=t.id, persistence="high", impact="high") for f in ex(*x)]
    s.intent.process_message("사용할 spaCy 모델과 버전 = en_core_web_sm 3.7")
    ctx = task_context(s, t.id, [{"role": "user", "text": "청킹은 같이 의논하자"}])
    assert "목표: LinearRAG 재현" in ctx and "반드시: 사용할 spaCy 모델과 버전 = en_core_web_sm 3.7" in ctx, ctx
    assert "- 사용할 spaCy 모델과 버전: 정함" in ctx and "- 청킹 규칙: 아직 정하지 않음" in ctx, ctx
    assert "사용자: 청킹은 같이 의논하자" in ctx, ctx
    sc, dropped, note = s.ask(t.id, "청킹 규칙을 같이 의논하자", None, ctx)
    assert j.context == ctx
    # the paper part as written, but never a fact: no quote, PARTIALLY_VERIFIED (the viewer says 인용 없음)
    assert sc.conclusion == j.answer and sc.outcome == "PARTIALLY_VERIFIED" and not s.evidence_for(sc.id), sc.conclusion
    assert note.startswith("정함: spaCy 모델과 버전.\n미정: 청킹 규칙.") and "제안: 문장 단위." in note, note  # the 의논 stays
    text, basis = render_brief(s, t.id)
    assert sc.id not in basis and j.answer not in text, text  # an uncited paper claim is no fact for the agent
    ctx2 = task_context(s, t.id, [{"role": "ask", "text": "청킹 규칙을 같이 의논하자", "check": sc.id, "note": note}])
    assert f"논문 질문: 청킹 규칙을 같이 의논하자 → (인용 없음) {j.answer} → 정함" in ctx2, ctx2
    s.judge = Judge(answer="")  # a task-only question: the paper part says the paper gave nothing, the note stays
    sc, _, note = s.ask(t.id, "지금 정한 설정이 뭐야?", None, ctx)
    assert sc.conclusion == NO_PAPER_ANSWER and "제안: 문장 단위." in note, sc.conclusion



def test_chat_request_is_no_criterion():
    """C7 (10/30): "작업 기준에 반드시 지킬 것 내용 확인해봐" said to the agent became a hard criterion. A chat request
    about the criteria, or to talk something over, stores nothing; a chat rule still does."""
    for t in ["다시 작업 기준에 반드시 지킬 것 내용 확인해봐", "기준 보여줘", "반드시 지킬 것 목록 알려줘",
              "청킹 규칙은 어떻게 하면 좋을지 같이 보자", "결과 다시 확인해봐"]:
        with tempfile.TemporaryDirectory() as d:
            cli(d, "task", "LinearRAG 재현", "--checks", "[]")
            rc, said = cli(d, "say", t, "--request", "--task", "T1")
            assert rc == 0 and not said["added"] and not said["unread"], (t, said)
    for t in ["앞으로 반드시 F1로 평가해", "평가 지표는 반드시 F1로 통일. 표 만들어줘"]:
        with tempfile.TemporaryDirectory() as d:
            cli(d, "task", "LinearRAG 재현", "--checks", "[]")
            rc, said = cli(d, "say", t, "--request", "--task", "T1")
            assert rc == 0 and [a["strength"] for a in said["added"]] == ["hard"], (t, said)



def test_agreed_change_is_a_card():
    """10/30 "동의해. 기준 내용 그렇게 수정해줘": no criterion is made of the message; propose-criteria reads the edits the
    conversation agreed on, keeps only edits of this task's criteria (with their old words), and changes nothing itself."""
    import contextlib
    import io
    import pablo_v2.__main__ as main
    from pablo_v2.intent.extract import asks_criteria_change
    for t in ["동의해. 기준 내용 그렇게 수정해줘봐", "그거 기준에 반영해줘", "반드시 지킬 것에 추가해줘"]:
        assert asks_criteria_change(t), t
    for t in ["다시 작업 기준에 반드시 지킬 것 내용 확인해봐", "코드 수정해줘", "앞으로 반드시 F1로 평가해"]:
        assert not asks_criteria_change(t), t
    d = tempfile.mkdtemp()
    cli(d, "task", "LinearRAG 재현", "--checks", "[]")
    rule = ["--scope", "task", "--task", "T1", "--rule", "hard"]
    c1 = cli(d, "say", "가장 최신 버전을 쓴다", *rule)[1]["added"][0]["id"]
    c2 = cli(d, "say", "청킹 규칙은 상의해서 정한다", *rule)[1]["added"][0]["id"]
    code, said = cli(d, "say", "동의해. 기준 내용 그렇게 수정해줘", "--request", "--task", "T1")
    assert code == 0 and said["change_request"] and not said["added"] and not said["unread"], said
    assert "기준 파일을 따로 만들지 말고" in render_brief(PabloSkill.load(os.path.join(d, "skill.json"),
                                                                IntentEngine.load(os.path.join(d, "intent.json"))), "T1")[0]

    class Proposer:
        def propose_criteria(self, goal, criteria, recent, message):
            assert [c["id"] for c in criteria] == [c1, c2] and recent[0]["text"] == "문장 단위로 하자", (criteria, recent)
            x = lambda op, i, text, why="": {"op": op, "id": i, "text": text, "strength": "soft", "reason": why}
            return {"changes": [x("restate", c2, "청킹은 문장 단위로 한다", "문장 단위에 동의함"), x("drop", c1, ""),
                                x("add", "", "평가 지표는 F1로 한다"), x("add", "", "가장 최신 버전을 쓴다"),
                                x("restate", "C99", "없는 기준"), x("restate", c1, "가장 최신 버전을 쓴다")]}
    was, main.LLMJudge = main.LLMJudge, lambda _: Proposer()
    class Out(io.StringIO):
        def reconfigure(self, **_):
            pass
    try:
        buf = Out()
        with contextlib.redirect_stdout(buf):
            assert main.main(["propose-criteria", "T1", "기준 내용 그렇게 수정해줘", "--recent",
                              json.dumps([{"role": "user", "text": "문장 단위로 하자"}]), "--json", "--dir", d]) == 0
    finally:
        main.LLMJudge = was
    got = json.loads(buf.getvalue())["changes"]
    assert got == [{"op": "restate", "id": c2, "before": "청킹 규칙은 상의해서 정한다", "text": "청킹은 문장 단위로 한다",
                    "strength": "hard", "reason": "문장 단위에 동의함"},
                   {"op": "drop", "id": c1, "before": "가장 최신 버전을 쓴다", "strength": "hard", "reason": "대화에서 정한 대로 뺌"},
                   {"op": "add", "text": "평가 지표는 F1로 한다", "strength": "soft", "reason": ""}], got
    left = [c.statement for c in IntentEngine.load(os.path.join(d, "intent.json")).get_active_constraints()]
    assert left == ["가장 최신 버전을 쓴다", "청킹 규칙은 상의해서 정한다"], left  # nothing changes before 반영


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
