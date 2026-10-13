"""③④ (0.8 review): a criterion the user writes is never dropped without a word, and criteria can be changed.
Run: python tests/skill/test_criteria.py
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
from pablo_v2.intent.extract import HeuristicExtractor  # noqa: E402
from pablo_v2.skill.skill import PabloSkill  # noqa: E402


def load(d):
    return PabloSkill.load(os.path.join(d, "skill.json"), IntentEngine.load(os.path.join(d, "intent.json")))

MARKERS = [  # (a line a user writes as a criterion, what the offline reader makes of it)
    ("test 셋은 튜닝에 쓰면 안 됨", ("constraint", "hard")),        # "안 됨", not only "안 돼"
    ("평가 데이터는 학습에 쓰지 않는다", ("constraint", "hard")),
    ("데이터 누수 없게 해줘", ("constraint", "hard")),               # "~없게" is a rule, not a goal
    ("GPU 메모리는 24GB 안에서만 써", ("constraint", "hard")),       # "~만 써" is a limit, not a wish
    ("가능하면 PyTorch만 써", ("constraint", "soft")),               # ... unless softened
    ("결과는 3번 돌려서 평균 낼 것", ("constraint", "hard")),        # written-instruction style
    ("원본 데이터 폴더는 건드리지 마", ("constraint", "hard")),
    ("결과는 3번 돌려서 평균 내", ("other", None)),                  # no marker: shown to the user, not guessed
    ("고마워", ("other", None)),
]


def cli(d, *args):
    r = subprocess.run([sys.executable, "-m", "pablo_v2", *args, "--json", "--dir", d], capture_output=True, encoding="utf-8",
                       env={**os.environ, "PYTHONPATH": SRC, "PYTHONIOENCODING": "utf-8"})
    return r.returncode, json.loads(r.stdout) if r.stdout.strip() else None  # argparse refusals print no JSON


def test_markers():
    """The offline reader knows the common Korean ways to write a rule; what it cannot read stays 'other'."""
    x = HeuristicExtractor()
    got = [(t, (f["type"], f["strength"])) for t in [m for m, _ in MARKERS] for f in x.extract(t, "M1", "", "")[:1]]
    assert got == MARKERS, [g for g, m in zip(got, MARKERS) if g != m]


def test_unread_lines_are_shown_and_decided():
    """A new task's criterion line the reader could not classify comes back as `unread` (never dropped silently); the
    user makes it a rule of that task (반드시 / 가능하면) or lets it go (괜찮음). A chat sentence is unread only when it
    reads like a rule ("~내", "~할 것"), so "고마워" is not."""
    with tempfile.TemporaryDirectory() as d:
        cli(d, "task", "LinearRAG 재현", "--checks", "[]")
        cli(d, "task", "다른 작업", "--checks", "[]")
        unread, added = [], []
        for line in ["test 셋은 튜닝에 쓰면 안 됨", "결과는 3번 돌려서 평균 내", "시드는 여러 개로 돌려서 표에 정리해"]:
            _, r = cli(d, "say", line, "--scope", "task", "--task", "T1")
            unread += r["unread"]
            added += r["added"]
        assert [a["strength"] for a in added] == ["hard"]
        assert [u["text"] for u in unread] == ["결과는 3번 돌려서 평균 내", "시드는 여러 개로 돌려서 표에 정리해"], unread
        code, p = cli(d, "promote", unread[0]["id"], "--as", "hard")
        assert code == 0 and (p["item"]["kind"], p["item"]["strength"]) == ("constraint", "hard"), p
        code, _ = cli(d, "reject", unread[1]["id"])
        s = load(d)
        rules = lambda t: [c.statement for c in s.get_applicable_intent(t)["constraints"]]  # noqa: E731
        assert "결과는 3번 돌려서 평균 내" in rules("T1") and "시드는 여러 개로 돌려서 표에 정리해" not in rules("T1")
        assert "결과는 3번 돌려서 평균 내" not in rules("T2")  # said for T1: T1's rule only
        _, chat = cli(d, "say", "앞으로 결과는 3번 돌려서 평균 내", "--request", "--task", "T1")
        assert [u["text"] for u in chat["unread"]] == ["앞으로 결과는 3번 돌려서 평균 내"], chat
        _, thanks = cli(d, "say", "고마워", "--request", "--task", "T1")
        assert thanks["unread"] == [], thanks
        code, bad = cli(d, "promote", unread[0]["id"], "--as", "both")
        assert code != 0


def test_edit_criteria():
    """④ a criterion's strength can be changed and a criterion removed, by the user, with the change in the history;
    the Guard reads the task's intent as it is after the change."""
    with tempfile.TemporaryDirectory() as d:
        cli(d, "task", "정리", "--checks", "[]")
        _, r = cli(d, "say", "keep.txt는 절대 지우지 마", "--scope", "task", "--task", "T1")
        cid = r["added"][0]["id"]
        code, s = cli(d, "strength", cid, "soft")
        assert code == 0 and s["item"]["strength"] == "soft", s
        assert [c.strength for c in load(d).get_applicable_intent("T1")["constraints"]] == ["soft"]
        code, s = cli(d, "drop", cid, "--reason", "필요 없어졌음")
        assert code == 0 and s["item"]["status"] == "removed", s
        assert load(d).get_applicable_intent("T1")["constraints"] == []  # the Guard no longer has it
        _, h = cli(d, "history")
        mine = [x for x in h["history"] if x["item_id"] == cid]
        assert [x["reason"] for x in mine][-2:] == ["사용자가 세기를 가능하면으로 바꿈", "사용자가 지움: 필요 없어졌음"], mine
        assert all(x["source"]["type"] == "user" for x in mine)
        assert cli(d, "strength", "C99", "hard")[0] != 0 and cli(d, "strength", cid, "loud")[0] != 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
