"""One task per conversation: a chat message read against its task's goal (same / sub / different), and the goal the
user rewrites when the message showed the goal was wrong. Run: python tests/skill/test_drift.py  (stub provider)
"""
import contextlib
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))

import pablo_v2.__main__ as cli  # noqa: E402
from pablo_v2.skill.judge import DRIFT_SCHEMA, LLMJudge  # noqa: E402


class Provider:
    def __init__(self):
        self.calls = []

    def complete_json(self, prompt, schema):
        self.calls.append((prompt, schema))
        return {"verdict": "different", "reason": "목표는 인사말 정리인데 이 메시지는 웹 크롤러를 요청합니다"}


class Out(io.StringIO):
    def reconfigure(self, **kw):
        pass


def run(argv):
    buf = Out()
    with contextlib.redirect_stdout(buf):
        cli.main(argv)
    return json.loads(buf.getvalue())


def test_prompt():
    p = Provider()
    LLMJudge(p).drift("인사말 파일 정리", "웹 크롤러 하나 만들어줘", [f"메시지 {i}" for i in range(10)] + ["x" * 900])
    prompt, schema = p.calls[0]
    assert schema is DRIFT_SCHEMA and schema["properties"]["verdict"]["enum"] == ["same", "sub", "different"]
    assert "TASK GOAL: 인사말 파일 정리" in prompt and "NEW MESSAGE: 웹 크롤러 하나 만들어줘" in prompt
    assert "- 메시지 5\n" in prompt and "- 메시지 4\n" not in prompt  # the last 6
    assert "x" * 500 in prompt and "x" * 501 not in prompt


def test_cli():
    p = Provider()
    cli.provider = lambda model=None: p
    with tempfile.TemporaryDirectory() as d:
        run(["task", "인사말 파일 정리", "--checks", "[]", "--json", "--dir", d])
        r = run(["drift", "T1", "웹 크롤러 하나 만들어줘", "--recent", '["hello.txt 정리해줘"]', "--json", "--dir", d])
        assert r["verdict"] == "different" and "크롤러" in r["reason"], r
        assert "- hello.txt 정리해줘" in p.calls[0][0]
        g = run(["set-goal", "T1", "  인사말 파일과   크롤러 정리 ", "--json", "--dir", d])
        assert g["task"]["text"] == "인사말 파일과 크롤러 정리", g
        run(["drift", "T1", "크롤러 결과도 정리해줘", "--json", "--dir", d])
        assert "TASK GOAL: 인사말 파일과 크롤러 정리" in p.calls[1][0]  # the new goal is what the judge reads
        bad = run(["set-goal", "T1", "   ", "--json", "--dir", d])
        assert bad["ok"] is False, bad


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
