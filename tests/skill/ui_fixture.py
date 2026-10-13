"""Offline UI fixture for `npm --prefix desktop run check -- --ui`: one task whose records and chat log interleave
(a WARN file change, a BLOCK command, a stopped agent reply, a PDF question) -> <dir>/view-T1.html.
Run: python tests/skill/ui_fixture.py <state dir>   (prints {"view": path})
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from pablo_v2.intent.engine import IntentEngine  # noqa: E402
from pablo_v2.skill.skill import PabloSkill  # noqa: E402
from pablo_v2.skill.viewer import render_html  # noqa: E402

EDIT = "파일 수정: hello.txt\n--- hello.txt\n@@ -1 +1,2 @@\n hello\n+안녕하세요"
CMD = '명령 실행: "C:\\Program Files\\PowerShell\\7\\pwsh.exe" -NoProfile -Command "Remove-Item keep.txt"'
CALM = {"source_conflicts": [], "plan_alignment": {"follows_step": True},
        "justification": {"present": False, "relevant": False, "supported_by": []}}


class Judge:  # C2 soft clear conflict without a reason -> WARN; C1 hard clear conflict -> BLOCK
    def analyze_action(self, action, justification, step, constraints, checks):
        cid, note = ("C2", "hello.txt에 한국어 줄을 더한다.") if action == EDIT else ("C1", "keep.txt를 지운다.")
        return {**CALM, "intent_conflicts": [{"intent_id": cid, "level": "clear", "note": note}]}


def at(sec: int) -> str:
    return f"2026-10-13T01:00:{sec:02d}+00:00"


def build(d: str) -> str:
    os.makedirs(d, exist_ok=True)
    e = IntentEngine.load(os.path.join(d, "intent.json"))
    e.process_message("keep.txt는 절대 삭제하면 안 돼.")
    e.process_message("hello.txt는 가능하면 영어로만 유지해줘.")
    assert (e.get_item("C1").strength, e.get_item("C2").strength) == ("hard", "soft")
    s = PabloSkill.load(os.path.join(d, "skill.json"), e, Judge())
    t = s.start_task("인사말 파일 정리", [])
    t.created_at = at(0)
    hedged = e.process_message("PyTorch가 좀 편할 것 같긴 한데")[0]  # B4: held back (pending) until the user decides
    assert hedged.status == "pending"
    s.create_plan(t.id, [{"action": "hello.txt에 인사말을 더한다", "basis": []}])
    warn = s.propose_action(t.id, EDIT, "P1.1")
    s.decide_action(warn.id, "proceed", "사용자가 대화에서 진행을 선택했습니다.")
    s.record_execution(warn.id, True, "파일 수정: hello.txt", ["hello.txt"])
    block = s.propose_action(t.id, CMD, "P1.1")
    s.decide_action(block.id, "reject", "Guard BLOCK: 실행하지 않았습니다.")
    warn.created_at, block.created_at = at(20), at(40)
    sc = s.add_check(t.id, "LinearRAG가 더 효율적이라는 근거는?", "USEFUL")
    s.complete_check(sc.id, "VERIFIED", "저자는 색인 시간을 77% 넘게 줄였다고 씁니다.",
                     [{"tier": 4, "type": "pdf", "title": "LinearRAG", "url": "LinearRAG.pdf", "supports": []}])
    specs = []  # A2: two stated reproduction conditions and one the paper leaves open (no PDF here: no anchors)
    for cat, text in [("hyperparameter", "검색 단계의 top-k는 5이다"), ("result", "2Wiki 정확도는 63.70%이다")]:
        c = s.add_check(t.id, text, "USEFUL")
        c.spec = {"category": cat, "value": "", "source_id": "SRC1"}
        s.complete_check(c.id, "VERIFIED", text, [{"tier": 4, "type": "pdf", "title": "LinearRAG", "url": "x", "supports": []}])
        specs.append(c.id)
    gap = s.add_check(t.id, "난수 시드가 적혀 있지 않다", "USEFUL")
    gap.spec = {"category": "training", "value": "", "source_id": "SRC1", "missing": True}
    s.save()
    e.save()
    chat = {t.id: [
        {"role": "user", "text": "hello.txt에 인사말을 넣어줘. 다른 파일은 건드리지 마.", "at": at(10)},
        {"role": "intent", "at": at(10), "items": [{"id": "C3", "kind": "constraint", "strength": "hard",
                                                   "text": "다른 파일은 건드리지 마"}],
         "pending": [{"id": hedged.id, "text": "PyTorch가 좀 편할 것 같긴 한데"}]},
        {"role": "agent", "text": "hello.txt에 줄을 더하겠습니다.", "at": at(11), "status": "completed"},
        {"role": "user", "text": "keep.txt도 정리해줘", "at": at(30)},
        {"role": "agent", "text": "keep.txt를 지우려", "at": at(31), "status": "interrupted"},
        {"role": "ask", "text": "효율 근거가 어디 있어?", "at": at(50), "check": sc.id},
        {"role": "spec", "at": at(55), "checks": specs, "missing": [gap.id], "dropped": 1},
        {"role": "audit", "at": at(58), "status": "completed", "summary": "top-k가 논문과 다릅니다.", "items": [
            {"id": "C1", "status": "followed", "where": "", "found": "", "note": "keep.txt는 그대로다"},
            {"id": specs[0], "status": "differs", "where": "config.yaml:5", "found": "top_k: 10", "note": "논문은 5"},
            {"id": specs[1], "status": "followed", "where": "logs/2wiki.log:1", "found": "acc=63.70", "note": ""},
            {"id": gap.id, "status": "chosen", "where": "config.yaml:12", "found": "seed: 42", "note": ""}]},
    ]}
    with open(os.path.join(d, "chat.json"), "w", encoding="utf-8") as f:
        json.dump(chat, f, ensure_ascii=False)
    path = os.path.join(d, "view-T1.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(s, t.id))
    return path


if __name__ == "__main__":
    print(json.dumps({"view": os.path.abspath(build(sys.argv[1]))}))
