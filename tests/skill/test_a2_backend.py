"""A2 complete, 단계 0 (the backend the screens build on). Run: python tests/skill/test_a2_backend.py
C3 restate (the user rewrites a criterion: same id, kind, strength, scope; history "사용자가 고침"), A13 report --sections /
--format html / --preview, D3 promoted candidates and D4 every plan in the view model, D9 spec progress from a streaming
provider. The ui_fixture's state and the CLI, stub judges only; no network.
"""
import contextlib
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))
sys.path.insert(0, HERE)

import pablo_v2.__main__ as cli  # noqa: E402
from pablo_v2.intent.engine import IntentEngine  # noqa: E402
from pablo_v2.skill import mdhtml  # noqa: E402
from pablo_v2.skill.judge import LLMJudge  # noqa: E402
from pablo_v2.skill.skill import PabloSkill  # noqa: E402
from pablo_v2.skill.viewer import model  # noqa: E402
import ui_fixture  # noqa: E402


class Out(io.StringIO):  # main() reconfigures stdout to UTF-8
    def reconfigure(self, **kw):
        pass


def run(*argv):
    buf = Out()
    with contextlib.redirect_stdout(buf):
        code = cli.main(list(argv))
    return code, json.loads(buf.getvalue())


def load(d):
    return PabloSkill.load(os.path.join(d, "skill.json"), IntentEngine.load(os.path.join(d, "intent.json")))


def test_restate():
    """C3: the same criterion with the user's words; strength and scope stay, the history keeps the old sentence."""
    with tempfile.TemporaryDirectory() as d:
        run("task", "T1 작업", "--checks", "[]", "--json", "--dir", d)
        run("task", "T2 작업", "--checks", "[]", "--json", "--dir", d)
        _, r = run("say", "결과는 3번 돌려서 평균 내", "--scope", "task", "--task", "T1", "--rule", "soft", "--json", "--dir", d)
        cid = r["added"][0]["id"]
        code, r = run("restate", cid, "  결과는   5번 돌려서 평균 내 ", "--json", "--dir", d)
        assert code == 0 and r["before"] == "결과는 3번 돌려서 평균 내" and r["item"]["statement"] == "결과는 5번 돌려서 평균 내"
        s = load(d)
        it = s.intent.get_item(cid)
        assert (it.id, it.kind, it.strength, it.status) == (cid, "constraint", "soft", "active")
        ids = lambda t: [c.id for c in s.get_applicable_intent(t)["constraints"]]  # noqa: E731
        assert ids("T1") == [cid] and ids("T2") == []  # still this task's only
        last = s.intent.get_intent_history()[-1]
        assert (last.reason, last.source.type, last.source.note, last.before["statement"], last.after["statement"]) == \
            ("사용자가 고침", "user", "직접", "결과는 3번 돌려서 평균 내", "결과는 5번 돌려서 평균 내")
        n = len(s.intent.get_intent_history())
        run("restate", cid, "결과는 5번 돌려서 평균 내", "--json", "--dir", d)  # the same words: nothing to record
        assert len(load(d).intent.get_intent_history()) == n
        assert run("restate", cid, "   ", "--json", "--dir", d)[0] == 1  # empty
        assert run("restate", cid, "x" * 501, "--json", "--dir", d)[0] == 1  # too long
        run("drop", cid, "--json", "--dir", d)
        code, r = run("restate", cid, "다시", "--json", "--dir", d)
        assert code == 1 and r["message"].startswith("no active criterion")  # main.js: "이미 바뀌었거나 지운 기준입니다."


def test_report_sections_and_html():
    """A13: the default report is the parts it always had; --sections keeps some (in the same order, conversation only when
    asked); --format html is that Markdown as one page; --preview gives the dialog's counts."""
    with tempfile.TemporaryDirectory() as d:
        ui_fixture.build(d)
        _, full = run("report", "T1", "--json", "--dir", d)
        heads = [ln for ln in full["text"].splitlines() if ln.startswith("## ")]
        assert heads == ["## 논문", "## 재현 조건 (4개)", "## 논문과 다르게 한 것 (의도한 차이)", "## 뺀 조건과 지운 기준", "## 작업 기준",
                         "## 재현 점검", "## Pablo가 막거나 확인을 받은 작업", "## 바뀐 파일", "## 참고 (따를 조건이 아닌 논문의 서술과 실험 범위)"]
        assert full["format"] == "md"
        _, part = run("report", "T1", "--sections", "refused,goal_criteria,conversation", "--json", "--dir", d)
        md = part["text"]
        assert [ln for ln in md.splitlines() if ln.startswith("## ")] == ["## 작업 기준", "## Pablo가 막거나 확인을 받은 작업", "## 대화 전체"]
        assert "\n\n\n" not in md and md.startswith("# 재현 보고서: 인사말 파일 정리\n")
        talk = md.split("## 대화 전체\n\n", 1)[1].splitlines()
        assert talk[0].startswith("- **나** · ") and talk[0].endswith("— 인사말 파일 정리")
        assert any(x.startswith("- **나 (논문 질문)**") for x in talk) and any("재현 조건 5개를 뽑았습니다" in x for x in talk)
        assert not any("[1]" in x for x in talk)  # no [n] apart from the app
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                cli.main(["report", "T1", "--sections", "nope", "--json", "--dir", d])
                raise AssertionError("an unknown part was taken")
            except SystemExit as e:
                assert e.code == 2
        _, h = run("report", "T1", "--sections", "audit", "--format", "html", "--json", "--dir", d)
        page = h["text"]
        assert h["format"] == "html" and page.startswith("<!doctype html>") and "<script" not in page
        assert "<h2>재현 점검</h2>" in page and "<table>" in page and "<h2>작업 기준</h2>" not in page
        assert "Geist" in page and "#FF4D00" in page  # the app's fonts by name and its colours, inline
        assert "<code>run.py:3</code>" in page and "&#x27;top_k&#x27;" in page  # code spans, text escaped
        _, p = run("report", "T1", "--preview", "--json", "--dir", d)
        assert p["counts"] == {"criteria": {"hard": 1, "soft": 1}, "conditions": 4, "audit": {"at": "2026-10-13T01:00:58.500+00:00"},
                               "deviations": 1, "decisions": 2, "changes": 0, "refused": 2, "conversation": 9}
        assert p["stale"] is False


def test_markdown_to_html():
    page = mdhtml.to_html("# T <x>\n\n- **b** `a|b` https://example.org/x.\n\n| 항목 | 판정 |\n|---|---|\n| a \\| b | `c` |\n\n끝 줄\n이어짐")
    assert page.splitlines() == ["<h1>T &lt;x&gt;</h1>",
                                 '<ul><li><strong>b</strong> <code>a|b</code> <a href="https://example.org/x">https://example.org/x</a>.</li></ul>',
                                 '<div class="scroll"><table><thead><tr><th>항목</th><th>판정</th></tr></thead><tbody><tr><td>a | b</td>'
                                 "<td><code>c</code></td></tr></tbody></table></div>",
                                 "<p>끝 줄 이어짐</p>"]


def test_view_model_plans_and_promoted():
    """D4 every plan (oldest first, with when and its step ids); D3 a held-back line the user promoted -> its criterion."""
    with tempfile.TemporaryDirectory() as d:
        ui_fixture.build(d)
        run("plan", "T1", "--steps", json.dumps([{"action": "첫 요청", "basis": []}]), "--json", "--dir", d)
        run("plan", "T1", "--steps", json.dumps([{"action": "둘째 요청", "basis": []}]), "--json", "--dir", d)
        v = model(load(d), "T1")
        assert [(p["status"], [st["id"] for st in p["steps"]], p["steps"][0]["action"]) for p in v["plans"]][-2:] == \
            [("superseded", [v["plans"][-2]["id"] + ".1"], "첫 요청"), ("active", [v["plans"][-1]["id"] + ".1"], "둘째 요청")]
        assert all(p["created_at"] for p in v["plans"]) and v["plan"]["id"] == v["plans"][-1]["id"]
        assert v["intent"]["promoted"] == {}
        held = next(u["id"] for c in v["chat"] for u in c.get("pending") or [])
        _, r = run("promote", held, "--json", "--dir", d)
        assert model(load(d), "T1")["intent"]["promoted"] == {held: r["item"]["id"]}


class Streaming:  # D9: answers as the desktop's provider does, a few characters at a time through on_text
    def __init__(self, answer):
        self.answer, self.on_text, self.seen = answer, None, []

    def complete_json(self, prompt, schema):
        text = json.dumps(self.answer)
        for i in range(0, len(text), 7):
            if self.on_text:
                self.on_text(text[:i + 7])
        return self.answer


def test_spec_progress():
    """D9: the furthest page the streamed answer cites, growing only, then every page; none without a streaming provider."""
    items = [{"category": "model", "statement": "s", "value": "v", "quote": "q", "page": p, "kind": "setting"} for p in (2, 1, 5, 3)]
    pages = ["page"] * 6
    heard = []
    j = LLMJudge(Streaming({"items": items, "missing": []}))
    r = j.extract_spec(pages, progress=lambda p, n: heard.append((p, n)))
    assert len(r["items"]) == 4 and heard == [(0, 6), (2, 6), (5, 6), (6, 6)] and j.provider.on_text is None

    class Plain:
        def complete_json(self, prompt, schema):
            return {"items": items, "missing": []}
    heard.clear()
    LLMJudge(Plain()).extract_spec(pages, progress=lambda p, n: heard.append((p, n)))
    assert heard == [(0, 6), (6, 6)]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
