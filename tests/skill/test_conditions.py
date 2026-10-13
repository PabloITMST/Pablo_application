"""⑩ (0.8 review): the user's own hand on the reproduction conditions. Run: python tests/skill/test_conditions.py
A sentence picked in the paper becomes a condition (anchored on its page, or refused); a condition is taken out with
why and put back. Small generated PDFs (ui_fixture.tiny_pdf), stub judges, no network.
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

from pablo_v2.intent.engine import IntentEngine  # noqa: E402
from pablo_v2.skill.evidence import AnchorRejected  # noqa: E402
from pablo_v2.skill.skill import PabloSkill, render_audit, render_brief  # noqa: E402
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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
