"""UI renewal P6 단계별: the model's summary of one stage, written on request. Run: python tests/skill/test_summary.py
The prompt carries the task's goal, the stage and its messages oldest first (the newest 80, each cut at 2,000
characters); the CLI reads the messages from a file (@path) and returns the summary trimmed. Stub provider, no network.
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
from pablo_v2.skill.judge import SUMMARY_SCHEMA, LLMJudge  # noqa: E402


class Provider:  # records each call
    def __init__(self):
        self.calls = []

    def complete_json(self, prompt, schema):
        self.calls.append((prompt, schema))
        return {"summary": "  top-k를 10으로 두기로 했고, 2Wiki 열 짝은 아직 확인하지 않았다.  "}


class Out(io.StringIO):  # main() reconfigures stdout to UTF-8
    def reconfigure(self, **kw):
        pass


def run(argv):
    buf = Out()
    with contextlib.redirect_stdout(buf):
        cli.main(argv)
    return json.loads(buf.getvalue())


def test_prompt():
    p = Provider()
    msgs = [{"who": "You", "text": f"메시지 {i}"} for i in range(100)] + [{"who": "Pablo", "text": "x" * 3000}]
    LLMJudge(p).summarize_stage("인사말 파일 정리", "작업", msgs)
    prompt, schema = p.calls[0]
    assert schema is SUMMARY_SCHEMA
    assert "TASK: 인사말 파일 정리" in prompt and "STAGE: 작업" in prompt
    assert "[You] 메시지 21\n" in prompt and "[You] 메시지 20\n" not in prompt  # the newest 80
    assert prompt.index("메시지 21") < prompt.index("메시지 99") < prompt.index("[Pablo]")  # oldest first
    assert "x" * 2000 in prompt and "x" * 2001 not in prompt


def test_cli():
    p = Provider()
    cli.provider = lambda model=None: p
    with tempfile.TemporaryDirectory() as d:
        run(["task", "인사말 파일 정리", "--checks", "[]", "--json", "--dir", d])
        f = os.path.join(d, "messages.json")
        with open(f, "w", encoding="utf-8") as fh:
            json.dump([{"who": "You", "text": "top-k는 10으로 두자"}, {"who": "Pablo", "text": "config.yaml:5를 10으로 두었습니다."}], fh)
        r = run(["summarize", "T1", "--stage", "작업", "--messages", "@" + f, "--json", "--dir", d])
    assert r == {"ok": True, "summary": "top-k를 10으로 두기로 했고, 2Wiki 열 짝은 아직 확인하지 않았다."}, r
    assert "[You] top-k는 10으로 두자\n[Pablo] config.yaml:5를 10으로 두었습니다." in p.calls[0][0]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
