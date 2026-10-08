"""M2 Skill tests. Run: python tests/skill/test_skill.py
Stub judges return fixed semantic facts, so these test Pablo's own rules. PABLO_LLM=1 adds the Codex judge.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from pablo_v2.intent.engine import IntentEngine  # noqa: E402
from pablo_v2.intent.models import Source  # noqa: E402
from pablo_v2.skill.skill import (DecisionRejected, PabloSkill, ResearchIncomplete, ResearchRejected,  # noqa: E402
                                  render_task)

SIWC = dict(tier=1, type="documentation", title="Sign in with ChatGPT: Codex app-server",
            url="https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server",
            supports=["browser OAuth", "ChatGPT plan usage", "Codex app-server integration"])
NO_CONFLICT = {"intent_conflicts": [], "source_conflicts": [], "plan_alignment": {"follows_step": True},
               "justification": {"present": False, "relevant": False, "supported_by": []}}


class StubJudge:
    def __init__(self, analyses=None, checks=None, reuse=(), observed=None):
        self.analyses, self.task_checks, self.reuse, self.observed = analyses or {}, checks or [], reuse, observed or {}

    def analyze_task(self, task, intent, existing=""):
        return {"reuse": [{"source_check_id": r, "why": ""} for r in self.reuse], "checks": self.task_checks}

    def analyze_action(self, action, justification, step, constraints, checks):
        return self.analyses.get(action, NO_CONFLICT)

    def analyze_execution(self, context, execution):
        return next(v for k, v in self.observed.items() if f"summary: {k}\n" in execution)


def observed(relation="same", progress="all", succeeded=True, consistent=True, unapproved=(), new_facts=(),
             contradicted=(), assumptions=(), questions=(), issues=()):
    """Stub post-review observations. issues: [(type, SC id)], contradicted: [ids], questions: [(text, blocking)]"""
    return {"scope": {"relation": relation, "note": relation}, "unapproved_files": list(unapproved),
            "outcome": {"succeeded": succeeded, "note": ""}, "step_progress": {"progress": progress, "note": ""},
            "decision_consistent": {"consistent": consistent, "note": "reason said hint only"},
            "new_facts": [{"statement": f, "source_check_id": "SC1"} for f in new_facts],
            "contradicted": [{"ref_id": i, "note": "observed otherwise"} for i in contradicted],
            "new_assumptions": list(assumptions),
            "new_questions": [{"statement": q, "blocking": b} for q, b in questions],
            "research_issues": [{"type": t, "source_check_id": i, "note": "summary said absent"} for t, i in issues]}


def conflict(cid, level="clear", present=False, relevant=False, supported_by=()):
    return {**NO_CONFLICT, "intent_conflicts": [{"intent_id": cid, "level": level, "note": ""}],
            "justification": {"present": present, "relevant": relevant, "supported_by": list(supported_by)}}


def facts(sources=(), follows=True, present=False, relevant=False, supported_by=()):
    """sources: [(SC id, contradicts|bypasses|possible)]"""
    return {**NO_CONFLICT, "source_conflicts": [{"source_check_id": i, "kind": k, "note": ""} for i, k in sources],
            "plan_alignment": {"follows_step": follows},
            "justification": {"present": present, "relevant": relevant, "supported_by": list(supported_by)}}


def codex_intent():
    e = IntentEngine()
    e.process_message("Codex 로그인 기능 구현해줘.")
    e.process_message("공식 지원 방식이 있으면 가능하면 임의 구현보다 그걸 우선해.")
    e.process_message("토큰은 절대 평문으로 저장하지 마.")
    assert (e.get_item("C1").strength, e.get_item("C2").strength) == ("soft", "hard")
    return e


def test_acceptance_codex_oauth():
    """Partial official search -> 'not found' refused -> SIWC found -> plan built on it -> actions guarded."""
    judge = StubJudge(
        analyses={
            "custom OAuth wrapper 구현": conflict("C1", present=True, relevant=False),
            "access token을 config.json에 평문 저장": conflict("C2"),
        },
        checks=[{"requirement": "Codex 연동에서 공식 지원하는 인증 방식은?", "necessity": "REQUIRED",
                 "why_blocking": "틀리면 인증 구조가 바뀜"}])
    s = PabloSkill(codex_intent(), judge)
    t = s.start_task("Codex 로그인 구현")
    assert s.necessity(t.id) == "REQUIRED"

    # plan-first / act-first is refused while research is pending
    try:
        s.create_plan(t.id, [{"action": "OAuth 직접 구현", "basis": ["C1"]}])
        raise AssertionError("plan before research must be refused")
    except ResearchIncomplete:
        pass
    a = s.propose_action(t.id, "custom OAuth wrapper 구현")
    assert a.verdict == "BLOCK" and a.reasons[0]["rule"] == "G01"

    # the real M1.1 mistake: two doc pages, no hit, "officially not documented"
    s.record_search("SC1", "OpenAI Codex auth docs", "Codex OAuth authentication", 1, found=False)
    s.record_search("SC1", "OpenAI Codex app-server docs", "app-server auth methods", 1, found=False)
    try:
        s.complete_check("SC1", "NOT_FOUND", "공식 auth 설명 없음", stop_reason="official_channels_exhausted")
        raise AssertionError("NOT_FOUND without tier 2 search must be refused")
    except ResearchRejected as err:
        assert "R03" in str(err)
    assert s.get_check("SC1").research_state == "pending" and s.get_check("SC1").rejections

    s.record_search("SC1", "OpenAI SIWC docs", "Codex app-server OAuth", 1, found=True)
    sc = s.complete_check("SC1", "VERIFIED", "공식 OAuth 기반 app-server 연동 방식이 있습니다.", [SIWC])
    assert (sc.research_state, sc.outcome, sc.stop_reason) == ("completed", "VERIFIED", "authoritative_answer_found")

    p = s.create_plan(t.id, [{"action": "SIWC OAuth + codex app-server 연동", "basis": ["SC1", "C1"]}])
    assert p.unverified == []

    assert s.propose_action(t.id, "codex app-server 연동 구현", "P1.1").verdict == "ALLOW"
    a = s.propose_action(t.id, "custom OAuth wrapper 구현", "P1.1", "이게 더 쉬울 것 같아서")
    assert (a.verdict, [r["rule"] for r in a.reasons]) == ("WARN", ["G08"])
    a = s.propose_action(t.id, "access token을 config.json에 평문 저장", "P1.1")
    assert (a.verdict, a.reasons[0]["rule"]) == ("BLOCK", "G04")
    print(render_task(s, t.id))


def test_soft_conflict_justification():
    s = PabloSkill(codex_intent(), StubJudge(analyses={
        "no reason": conflict("C1"),
        "cites pending": conflict("C1", present=True, relevant=True, supported_by=["SC2"]),
        "cites verified": conflict("C1", present=True, relevant=True, supported_by=["SC1"]),
        "possible": conflict("C1", level="possible"),
        "hard possible": conflict("C2", level="possible"),
    }))
    t = s.start_task("Python 3.13 호환", [{"requirement": "공식 repo의 3.13 지원 여부", "necessity": "REQUIRED"},
                                        {"requirement": "커뮤니티 우회법", "necessity": "USEFUL"}])
    s.record_search("SC1", "official repo issues", "python 3.13", 2, found=True)
    s.complete_check("SC1", "VERIFIED", "공식 repo가 3.13에서 실행 불가 (공식 issue)",
                     [dict(tier=2, type="issue", title="3.13 unsupported", supports=["incompatible"])])
    rules = {d: [(r["rule"], r["verdict"]) for r in s.propose_action(t.id, d).reasons if r["rule"] != "G02"]
             for d in ["no reason", "cites pending", "cites verified", "possible", "hard possible"]}
    assert rules == {"no reason": [("G07", "WARN")], "cites pending": [("G09", "WARN")],
                     "cites verified": [("G10", "ALLOW")], "possible": [("G06", "ALLOW")],
                     "hard possible": [("G05", "WARN")]}


def test_not_found_completes_research():
    s = PabloSkill(codex_intent(), StubJudge())
    t = s.start_task("라이브러리 X의 Y 지원", [{"requirement": "X가 Y를 공식 지원하는가?", "necessity": "REQUIRED"}])
    s.record_search("SC1", "X docs", "Y support", 1, found=False)
    s.record_search("SC1", "X repo", "Y", 2, found=False)
    try:
        s.complete_check("SC1", "NOT_FOUND", "공식 근거 없음")  # no stop_reason
        raise AssertionError
    except ResearchRejected as err:
        assert "R02" in str(err)
    s.complete_check("SC1", "NOT_FOUND", "공식 근거 없음", stop_reason="official_channels_exhausted")
    p = s.create_plan(t.id, [{"action": "Y를 우회 구현", "basis": ["SC1"]}])
    assert p.unverified == ["P1.1: SC1 NOT_FOUND"]
    a = s.propose_action(t.id, "Y 우회 구현", "P1.1")
    assert a.verdict == "ALLOW" and a.reasons[0]["rule"] == "G03"


def test_source_aware_guard():
    """M2.1: the two host-test false negatives (token read, self-made device polling) and plan deviation."""
    s = PabloSkill(IntentEngine(), StubJudge(analyses={
        "auth.json token 직접 읽기": facts([("SC1", "contradicts")], follows=False, present=True),
        "device polling 직접 구현, 빨라서": facts([("SC2", "bypasses")], present=True),
        "device polling 직접 구현, SC1 근거": facts([("SC2", "bypasses")], present=True, relevant=True,
                                               supported_by=["SC1"]),
        "부분 근거와 반대": facts([("SC3", "contradicts")]),
        "다른 task 근거 인용": facts([("SC9", "contradicts")]),
        "plan 밖 작업": facts(follows=False),
        "plan 밖 작업, 이유 있음": facts(follows=False, present=True, relevant=True),
        "plan 그대로, 이유 엉뚱": facts(present=True),
    }))
    t = s.start_task("status에 한도 표시", [{"requirement": r, "necessity": "REQUIRED"} for r in "abc"])
    s.complete_check("SC1", "VERIFIED", "Codex가 토큰을 소유한다. host는 직접 읽지 않는다.", [SIWC])
    s.complete_check("SC2", "VERIFIED", "codex login --device-auth가 공식 방식이다.", [SIWC])
    s.complete_check("SC3", "PARTIALLY_VERIFIED", "창 매핑은 문서에 없다.", [SIWC], "budget_exhausted")
    s.create_plan(t.id, [{"action": "app-server로 한도 조회", "basis": ["SC1", "SC2"]}])
    got = {d: (s.propose_action(t.id, d, "P1.1", "why").verdict,
               sorted(r["rule"] for r in s.actions(t.id)[-1].reasons)) for d in s.judge.analyses}
    assert got == {
        "auth.json token 직접 읽기": ("BLOCK", ["D01", "S01"]),
        "device polling 직접 구현, 빨라서": ("WARN", ["S03"]),
        "device polling 직접 구현, SC1 근거": ("ALLOW", ["S04"]),
        "부분 근거와 반대": ("WARN", ["S02"]),
        "다른 task 근거 인용": ("ALLOW", []),
        "plan 밖 작업": ("WARN", ["D01"]),
        "plan 밖 작업, 이유 있음": ("ALLOW", ["D02"]),
        "plan 그대로, 이유 엉뚱": ("ALLOW", []),
    }, got


def test_reuse_waive_decide():
    s = PabloSkill(IntentEngine(), StubJudge(analyses={"risky": conflict("SP3"), "odd": facts(follows=False)}))
    t1 = s.start_task("A", [{"requirement": "credential 소유자", "necessity": "REQUIRED"}])
    s.complete_check("SC1", "VERIFIED", "Codex가 소유", [SIWC])
    s.judge.reuse, s.judge.task_checks = ["SC1", "SC404"], [
        {"requirement": "한도 API", "necessity": "REQUIRED", "why_blocking": "틀리면 연동 방식이 바뀜"},
        {"requirement": "polling 간격", "necessity": "REQUIRED", "why_blocking": " "},
        {"requirement": "만료 규칙", "necessity": "REQUIRED", "why_blocking": "틀리면 재로그인 처리가 바뀜"}]
    t2 = s.start_task("C")
    assert t2.reused == ["SC1"], "only existing completed checks are reused"
    assert [(c.id, c.necessity) for c in s.checks(t2.id)] == [
        ("SC1", "REQUIRED"), ("SC2", "REQUIRED"), ("SC3", "USEFUL"), ("SC4", "REQUIRED")]
    try:
        s.waive("SC1", "x")
        raise AssertionError("completed checks cannot be waived")
    except ValueError:
        pass
    s.waive("SC4", "codex CLI가 맡는 부분")
    s.complete_check("SC2", "VERIFIED", "rateLimits/read", [SIWC])
    assert s.pending_required(t2.id) == []
    assert s.create_plan(t2.id, [{"action": "x", "basis": ["SC1", "SC4"]}]).unverified == ["P1.1: SC4 waived"]

    block, warn = s.propose_action(t2.id, "risky", "P1.1"), s.propose_action(t2.id, "odd", "P1.1")
    assert (block.verdict, block.reasons[-1]["rule"], warn.verdict) == ("BLOCK", "G04", "WARN"), "SP3 is hard"
    for act, reason in [(block, "꼭 필요"), (warn, "")]:
        try:
            s.decide_action(act.id, "proceed", reason)
            raise AssertionError(act.verdict)
        except DecisionRejected:
            pass
    s.decide_action(warn.id, "defer", "backlog와 함께")
    assert (warn.host_decision, warn.decision_reason) == ("defer", "backlog와 함께")
    assert t1.reused == []
    print(render_task(s, t2.id))


def device_login_task(judge, path=None):
    """T1 with one VERIFIED check, plan P1.1 (failure hint), and agent assumption A1."""
    e = IntentEngine()
    s = PabloSkill(e, judge, path=path)
    t = s.start_task("login --device 맞추기", [{"requirement": "공식 device 로그인", "necessity": "REQUIRED"}])
    e.add_assumption("사용자 환경에서 브라우저 로그인이 가능하다")  # raised during T1 -> belongs to T1
    s.complete_check("SC1", "VERIFIED", "codex login --device-auth. CLI가 polling과 저장을 맡는다.", [SIWC])
    s.create_plan(t.id, [{"action": "device 로그인 실패 시 활성화 안내와 공식 문서 URL을 stderr에 출력",
                          "basis": ["SC1"]}])
    return s, t


def test_post_review():
    """M2.2 acceptance A-F + deviation kinds, with stub observations; nothing in Intent/Plan changes."""
    path = os.path.join(tempfile.mkdtemp(), "skill.json")
    judge = StubJudge(analyses={"warn": facts(follows=False), "block": conflict("SP3")}, observed={
        "A": observed(), "B": observed("subset", "part"), "C": observed("superset", unapproved=["llm.py", "x.py"]),
        "E": observed(issues=[("source_tool_error", "SC1"), ("weird", "SC404")]),
        "F": observed(assumptions=["CI에는 브라우저가 없어 device 로그인만 쓴다"],
                      questions=[("CI 로그인을 지원해야 하나?", True)], contradicted=["A1"]),
        "G": observed(consistent=False), "H": observed(), "I": observed(progress="none"),
    })
    s, t = device_login_task(judge, path)
    act = lambda d="ok": s.propose_action(t.id, d, "P1.1")  # noqa: E731
    plans_before = len(s.plans(t.id))

    def run(a, summary, executed=True, files=("auth.py",), tests=(), errors=()):
        x = s.record_execution(a.id, executed, summary, files if executed else (), tests, (), errors)
        r = s.review_execution(x.id)
        return r.action_alignment, r.plan_step_status, sorted(d["kind"] for d in r.deviations), r

    assert run(act(), "A", tests=[{"name": "test_auth", "result": "pass"}])[:3] == ("aligned", "completed", [])
    al, st, kinds, r = run(act(), "B")
    assert (al, st, kinds) == ("partial", "partial", ["partial"])
    assert [p["kind"] for p in r.plan_update_proposals] == ["add_step"]
    al, st, kinds, r = run(act(), "C", files=("auth.py", "llm.py"))
    assert (al, kinds) == ("deviated", ["scope_expanded", "unapproved_files"]), kinds
    assert r.deviations[1]["note"] == "llm.py", "only files the record actually changed"
    assert [p["kind"] for p in r.plan_update_proposals] == ["revise_step"]

    w = act("warn")
    assert w.verdict == "WARN"
    s.decide_action(w.id, "defer", "app-server auth backlog와 함께 처리")
    al, st, kinds, r = run(w, "D", executed=False)  # no judge call: "D" has no stub
    assert (al, st, kinds, r.facts, r.plan_update_proposals) == ("not_executed", "unchanged", [], {}, [])

    al, st, kinds, r = run(act(), "E")
    assert [(i.type, i.source_check_id) for i in s.state.issues] == [("source_tool_error", "SC1"), ("other", None)]
    assert r.research_issues == ["RI1", "RI2"] and r.plan_update_proposals[0]["target"] == "SC1"

    al, st, kinds, r = run(act(), "F")
    assert [p["api"] for p in r.intent_update_proposals] == ["add_assumption", "add_open_question",
                                                             "set_assumption_status"]
    assert [i.id for i in s.intent.get_assumptions()] == ["A1"] and s.intent.get_item("A1").status == "unverified"
    assert s.intent.get_open_questions() == [], "proposals only, Intent untouched"

    w2 = act("warn")
    s.decide_action(w2.id, "proceed", "안내 문구만 바꿈")
    assert run(w2, "G")[2] == ["decision_mismatch"]
    assert run(act("block"), "H")[:3] == ("deviated", "completed", ["unapproved_execution"])
    al, st, kinds, _ = run(act(), "I", tests=[{"name": "test_auth", "result": "fail"}], errors=["exit 1"])
    assert (al, st, kinds) == ("failed", "blocked", ["failed"])
    b = act("block")
    assert run(b, "J", executed=False)[:2] == ("not_executed", "blocked")
    try:
        s.record_execution(b.id, False, "x", ["a.py"])
        raise AssertionError("not executed + changed files")
    except ValueError:
        pass

    assert len(s.plans(t.id)) == plans_before and s.plans(t.id)[0].id == "P1", "Plan untouched"
    assert PabloSkill.load(path, s.intent).state.to_dict() == s.state.to_dict()
    print(render_task(s, t.id))


def test_review_intent_scope():
    """Review sees only the task's applicable assumptions/questions (get_applicable_intent), even if asked for more."""
    class Spy(StubJudge):
        def analyze_execution(self, context, execution):
            self.context = context
            return observed()

    judge = Spy()
    s, t1 = device_login_task(judge)  # A1 raised during T1
    e = s.intent
    e.process_message("새 프레임워크는 도입하지 마")
    proj = e.add_assumption("CI 러너는 Linux다")  # agent annotation made project-wide by a project candidate
    e.state.candidates[-1].item_id = proj.id
    t2 = s.start_task("CI 로그인", [])
    cur = e.add_assumption("CI에는 브라우저가 없다")
    q = e.add_open_question("headless 모드도 지원하나?")
    for x, at in [(t1, "2026-01-01T00:00:00"), (e.get_item("A1"), "2026-01-01T00:00:01"), (proj, "2026-01-01T00:00:02"),
                  (t2, "2026-01-01T00:01:00"), (cur, "2026-01-01T00:01:01"), (q, "2026-01-01T00:01:02")]:
        x.created_at = at + "+00:00"
    s.complete_check("SC1", "VERIFIED", "ok", [SIWC])
    a = s.propose_action(t2.id, "ok")

    def seen(ids=None):
        s.review_execution(s.record_execution(a.id, True, "A", ["auth.py"]).id, ids)
        return {x for x in ("A1", proj.id, cur.id, q.id) if f"{x} [" in judge.context.split("ASSUMPTIONS")[1]}

    assert seen() == {proj.id, cur.id, q.id}, "past-task A1 out; current-task and project-scoped in"
    assert seen(["A1", cur.id]) == {cur.id}, "a caller cannot pull a non-applicable item in"
    assert "A1" not in {i.id for i in s.get_applicable_intent(t2.id)["assumptions"]}
    assert "A1" in {i.id for i in s.get_applicable_intent(t1.id)["assumptions"]}
    d = e.record_decision("Codex CLI가 credential을 관리한다", "T1 결정", Source("agent"))
    d.created_at = "2026-01-01T00:00:03+00:00"  # recorded during T1 -> not T2's decision
    assert [x.id for x in s.get_applicable_intent(t1.id)["decisions"]] == [d.id]
    assert s.get_applicable_intent(t2.id)["decisions"] == []


def test_task_local_override():
    """A task-scoped conflict overrides a project soft item in that task only; project hard items are never overridden."""
    class Scripted:  # text -> (scope, strength, conflict target)
        links_by_id, name = True, "scripted"
        rows = {"hello.txt는 영어로만": ("project", "soft", None), "keep.txt 삭제 금지": ("project", "hard", None),
                "이번 작업은 hello.txt에 한국어 허용": ("task", "soft", "C1"), "이번 작업은 keep.txt 삭제": ("task", "soft", "C2")}

        def extract(self, text, message_id, context, conversation):
            scope, strength, target = self.rows[text]
            return [dict(candidate=True, type="constraint", statement=text, scope=scope, persistence="high", impact="high",
                         explicitness="explicit", strength=strength, is_correction=False, parent_goal_id=None, topics=[],
                         relation={"type": "conflict" if target else "none", "target_id": target}, rationale="")]

    e = IntentEngine(extractor=Scripted())
    s = PabloSkill(e, StubJudge())
    at = lambda x, sec: setattr(x, "created_at", f"2026-01-01T00:00:{sec:02d}+00:00")
    for sec, text in [(0, "hello.txt는 영어로만"), (1, "keep.txt 삭제 금지")]:
        e.process_message(text); at(e.state.items[-1], sec)
    t1 = s.start_task("A", []); at(t1, 10)
    t2 = s.start_task("B", []); at(t2, 20)
    e.process_message("이번 작업은 hello.txt에 한국어 허용"); at(e.state.items[-1], 21)  # C3, said during T2
    k = e.process_message("이번 작업은 keep.txt 삭제")[0]
    t3 = s.start_task("C", []); at(t3, 30)
    ids = lambda t: sorted(i.id for i in s.get_applicable_intent(t.id)["constraints"])
    assert ids(t1) == ["C1", "C2"] and ids(t3) == ["C1", "C2"], "other tasks keep the project item"
    assert ids(t2) == ["C2", "C3"] and "C1" in s.get_applicable_intent(t2.id)["other"], "C3 overrides C1 in T2 only"
    assert e.get_item("C1").status == "active" and e.get_item("C1").superseded_by is None, "no global supersede"
    assert (k.status, k.item_id, e.get_item("C2").status) == ("deviation", "C2", "active"), "hard: held, not overridden"


def test_llm_review():
    """M2.2 acceptance A-F against the Codex judge (observations only; rules are tested above)."""
    if os.environ.get("PABLO_LLM") != "1":
        return
    from pablo_v2.llm import CodexProvider
    from pablo_v2.skill.judge import LLMJudge

    s, t = device_login_task(LLMJudge(CodexProvider()))
    desc = ("auth.py: device 로그인 실패 시 ChatGPT 보안 설정에서 device code login을 켜라는 안내와 "
            "공식 문서 URL을 stderr에 출력")
    cases = {
        "A": (desc, dict(summary="auth.py의 login(device=True) 실패 분기에 활성화 안내와 공식 문서 URL 출력 추가",
                         files=["src/pablo_v2/auth.py"], tests=[{"name": "tests/auth", "result": "pass"}])),
        "B": (desc, dict(summary="실패 시 활성화 안내만 추가했다. 공식 문서 URL 출력은 아직 넣지 않았다.",
                         files=["src/pablo_v2/auth.py"])),
        "C": (desc, dict(summary="auth.py에 안내를 추가하고, 김에 llm.py의 CodexProvider 재시도 로직과 timeout도 바꿨다.",
                         files=["src/pablo_v2/auth.py", "src/pablo_v2/llm.py"])),
        "E": (desc, dict(summary="auth.py에 안내 추가", files=["src/pablo_v2/auth.py"], observations=[
            "SC1 조사 때 WebFetch 요약은 auth 문서에 device-auth 설명이 없다고 했다. 원문 HTML을 grep하니 "
            "codex login --device-auth 절이 있었다. 요약 도구가 틀렸다."])),
        "F": (desc, dict(summary="auth.py에 안내 추가", files=["src/pablo_v2/auth.py"], observations=[
            "테스트 중 이 머신(CI runner)에는 브라우저가 없어 브라우저 로그인이 불가능했다. device 로그인만 쓸 수 있다.",
            "CI에서 Pablo 로그인을 지원해야 하는지는 정해진 적이 없다."])),
    }
    got = {}
    for k, (d, ex) in cases.items():
        a = s.propose_action(t.id, d, "P1.1")
        x = s.record_execution(a.id, True, ex["summary"], ex["files"], ex.get("tests", ()), ex.get("observations", ()))
        got[k] = s.review_execution(x.id)
    w = s.propose_action(t.id, "device polling을 Pablo가 직접 구현", "P1.1", "빨라서")
    s.decide_action(w.id, "defer" if w.verdict == "WARN" else "reject", "공식 CLI 유지")
    got["D"] = s.review_execution(s.record_execution(w.id, False, "실행하지 않음").id)
    print(render_task(s, t.id))
    summary = {k: (r.action_alignment, r.plan_step_status) for k, r in got.items()}
    assert summary["A"] == ("aligned", "completed"), summary
    assert summary["B"][0] == "partial" and summary["B"][1] == "partial", summary
    assert summary["C"][0] == "deviated", summary
    assert summary["D"] == ("not_executed", "unchanged"), summary
    assert any(s.state.issues[int(i[2:]) - 1].type == "source_tool_error" for i in got["E"].research_issues), \
        got["E"].facts
    apis = {p["api"] for p in got["F"].intent_update_proposals}
    assert apis & {"add_assumption", "add_open_question", "set_assumption_status"}, got["F"].facts
    assert s.intent.get_open_questions() == [] and len(s.intent.get_assumptions()) == 1


def test_completion_rules_and_persistence():
    path = os.path.join(tempfile.mkdtemp(), "skill.json")
    s = PabloSkill(codex_intent(), StubJudge(), path=path)
    t = s.start_task("x", [{"requirement": "q", "necessity": "REQUIRED"}])
    blog = dict(tier=6, type="blog", title="someone's post", supports=["yes"])
    for outcome, src in [("VERIFIED", [blog]), ("CONFLICTING", [blog])]:
        try:
            s.complete_check("SC1", outcome, "c", src)
            raise AssertionError(outcome)
        except ResearchRejected:
            pass
    s.complete_check("SC1", "PARTIALLY_VERIFIED", "커뮤니티 자료만 있음", [blog], "budget_exhausted")
    s.create_plan(t.id, [{"action": "a", "basis": ["SC1"]}])
    s.create_plan(t.id, [{"action": "b", "basis": ["SC1"]}])
    assert [p.id for p in s.plans(t.id)] == ["P2"], "new plan supersedes old"
    assert PabloSkill.load(path, s.intent).state.to_dict() == s.state.to_dict()


def test_llm_judge():
    if os.environ.get("PABLO_LLM") != "1":
        return
    from pablo_v2.llm import CodexProvider
    from pablo_v2.skill.judge import LLMJudge

    s = PabloSkill(codex_intent(), LLMJudge(CodexProvider()))
    t = s.start_task("Codex(ChatGPT 계정) 로그인 기능 구현")
    assert s.necessity(t.id) == "REQUIRED", [c.requirement for c in s.checks(t.id)]
    for c in s.checks(t.id):
        s.complete_check(c.id, "VERIFIED", "공식 Sign in with ChatGPT + codex app-server 연동 방식이 있습니다.", [SIWC])
    cred = s.add_check(t.id, "ChatGPT 토큰은 누가 관리하는가?", "REQUIRED", "틀리면 보안 구조가 바뀜")
    s.complete_check(cred.id, "VERIFIED", "ChatGPT managed 모드에서는 Codex가 토큰을 소유한다. 호스트 도구는 "
                     "저장된 토큰을 직접 읽지 않고 codex CLI / app-server를 통해서만 쓴다.", [SIWC])
    s.create_plan(t.id, [{"action": "SIWC OAuth + codex app-server 연동", "basis": [s.checks(t.id)[0].id, "C1"]}])
    # Regression case only. Known semantic-judge variance (M2 freeze): the custom wrapper can come back BLOCK when
    # the judge reads "new wrapper" as a clear C1-type conflict; its source side alone is S03 WARN. Do not tune.
    got = {d: s.propose_action(t.id, d, "P1.1", j).verdict for d, j in [
        ("공식 SIWC OAuth로 codex app-server 연동 구현", None),
        ("공식 방식 대신 자체 OAuth wrapper를 새로 구현", "이게 더 쉬울 것 같아서"),
        ("access token을 config.json에 평문으로 저장", None),
        ("~/.codex/auth.json의 access token을 읽어 사용량 endpoint를 직접 호출", "app-server보다 빨라서"),
    ]}
    assert list(got.values()) == ["ALLOW", "WARN", "BLOCK", "BLOCK"], got
    print(render_task(s, t.id))


def test_gate_cli():
    """M4.2 desktop gate: current plan step, plain reason without ids, only this task's intent in the Guard context."""
    import contextlib
    import io
    import json
    import pablo_v2.__main__ as cli
    d = tempfile.mkdtemp()

    class Out(io.StringIO):
        def reconfigure(self, **_):
            pass

    def call(*a):
        buf = Out()
        with contextlib.redirect_stdout(buf):
            assert cli.main([*a, "--json", "--dir", d]) == 0, buf.getvalue()
        return json.loads(buf.getvalue())
    call("say", "keep.txt는 절대 삭제하면 안 돼.")  # C1 hard, project scope
    call("task", "fixture 정리", "--checks", "[]")
    call("plan", "T1", "--steps", '[{"action": "hello.txt에 줄 추가", "basis": ["C1"]}, {"action": "정리", "basis": []}]')
    bad = {**conflict("C1"), "intent_conflicts": [{"intent_id": "C1", "level": "clear", "note": "C1을 어깁니다 (C1)."}]}
    cli.LLMJudge = lambda _: StubJudge(analyses={"keep.txt 삭제": bad}, observed={"ok": observed()})
    g = call("gate", "T1", "keep.txt 삭제")
    assert (g["action"]["verdict"], g["step"]) == ("BLOCK", "P1.1"), g
    assert g["reason"] == "'keep.txt는 절대 삭제하면 안 돼'을 어깁니다.", g["reason"]
    assert g["intent"] == ["C1"] and call("gate", "T1", "hello.txt 수정")["reason"] == ""
    x = call("record", "ACT2", "ok", "--files", "hello.txt")["execution"]
    call("review", x["id"])  # P1.1 completed -> the next action is on P1.2
    assert call("gate", "T1", "hello.txt 수정")["step"] == "P1.2"


def test_new_task_criteria_scope():
    """M5.1.1 desktop + 새 작업: the extra lines are that task's criteria (say --scope task after the task exists),
    never project-wide; an explicit project item still applies to every task."""
    import contextlib
    import time
    from pablo_v2.__main__ import main
    d = tempfile.mkdtemp()
    run = lambda *a: main([*a, "--json", "--dir", d])  # noqa: E731
    with open(os.devnull, "w", encoding="utf-8") as null, contextlib.redirect_stdout(null):
        run("say", "README.md는 절대 삭제하면 안 돼.")  # project criterion, said before any task
        run("task", "인사말 파일 정리", "--checks", "[]")
        run("say", "keep.txt는 절대 수정하거나 삭제하면 안 돼.", "--scope", "task")
        run("say", "hello.txt는 가능하면 영어로만 유지해줘.", "--scope", "task")
        time.sleep(1.1)  # created_at has 1 s resolution; the task window is [created_at, next task)
        run("task", "LinearRAG 논문 읽기", "--checks", "[]")
    s = PabloSkill.load(os.path.join(d, "skill.json"), IntentEngine.load(os.path.join(d, "intent.json")))
    seen = lambda t: sorted(i.statement for i in s.get_applicable_intent(t)["constraints"])  # noqa: E731
    assert seen("T1") == ["README.md는 절대 삭제하면 안 돼", "hello.txt는 가능하면 영어로만 유지해줘",
                          "keep.txt는 절대 수정하거나 삭제하면 안 돼"], seen("T1")
    assert seen("T2") == ["README.md는 절대 삭제하면 안 돼"], seen("T2")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
