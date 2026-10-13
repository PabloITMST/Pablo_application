"""Offline UI fixture for `npm --prefix desktop run check -- --ui`: one task whose records and chat log interleave
(a WARN file change, a BLOCK command, a stopped agent reply, a PDF question, a 재현 점검 that Pablo checked against
<dir>/repro, the 0.7.0 demo folder) -> <dir>/view-T1.html.
Run: python tests/skill/ui_fixture.py <state dir>   (prints {"view": path, "repro": folder})
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from pablo_v2.intent.engine import IntentEngine  # noqa: E402
from pablo_v2.skill.skill import PabloSkill  # noqa: E402
from pablo_v2.skill.viewer import render_html  # noqa: E402

DEMO = os.path.join(os.path.dirname(__file__), "..", "..", "release", "0.7.0", "demo-repro")
EDIT = "파일 수정: hello.txt\n--- hello.txt\n@@ -1 +1,2 @@\n hello\n+안녕하세요"
CMD = '명령 실행: "C:\\Program Files\\PowerShell\\7\\pwsh.exe" -NoProfile -Command "Remove-Item keep.txt"'
CALM = {"source_conflicts": [], "plan_alignment": {"follows_step": True},
        "justification": {"present": False, "relevant": False, "supported_by": []}}


class Judge:  # C2 soft clear conflict without a reason -> WARN; C1 hard clear conflict -> BLOCK
    def analyze_action(self, action, justification, step, constraints, checks):
        cid, note = ("C2", "hello.txt에 한국어 줄을 더한다.") if action == EDIT else ("C1", "keep.txt를 지운다.")
        return {**CALM, "intent_conflicts": [{"intent_id": cid, "level": "clear", "note": note}]}


def tiny_pdf(pages: list[str], title: str = "") -> bytes:
    """A small real PDF (Helvetica, about 80 characters a line) that pypdf and pdf.js both read: offline papers for the
    C1-C3 tests. ASCII text only."""
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")  # noqa: E731
    objs, kids, n = {1: "<< /Type /Catalog /Pages 2 0 R >>", 3: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"}, [], 4
    for text in pages:
        lines, line = [], ""
        for w in text.split():
            if line and len(line) + 1 + len(w) > 80:
                lines.append(line)
                line = w
            else:
                line = f"{line} {w}" if line else w
        lines.append(line)
        stream = "BT /F1 11 Tf 50 750 Td 14 TL " + " ".join(f"({esc(x)}) Tj T*" for x in lines) + " ET"
        objs[n] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
                   f"/Contents {n + 1} 0 R >>")
        objs[n + 1] = f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"
        kids.append(n)
        n += 2
    objs[2] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    objs[n] = f"<< /Title ({esc(title)}) >>"
    out, offs = b"%PDF-1.4\n", {}
    for k in sorted(objs):
        offs[k] = len(out)
        out += f"{k} 0 obj\n{objs[k]}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {n + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{offs[k]:010d} 00000 n \n".encode() for k in range(1, n + 1))
    return out + f"trailer\n<< /Size {n + 1} /Root 1 0 R /Info {n} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


# two small papers for C1-C3: one sentence is in both (it must anchor in the paper the answer names)
TINY_A = ["arXiv:2501.00001v2 [cs.CL] 1 Jan 2025. TinyRAG: a tiny graph retrieval method. We evaluate on HotpotQA and "
          "MuSiQue with 1,000 questions each.",
          "TinyRAG reaches 61.5 accuracy on HotpotQA. Indexing takes 12 seconds on one GPU. A limitation is that "
          "entity linking ignores synonyms."]
TINY_B = ["OtherRAG: retrieval with dense passages. We evaluate on HotpotQA and MuSiQue with 1,000 questions each.",
          "OtherRAG reaches 58.2 accuracy on HotpotQA. Indexing takes 95 seconds on one GPU. We do not study efficiency "
          "beyond indexing time."]


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
    specs = []  # A2: four stated reproduction conditions (one a method step) and one the paper leaves open (no PDF: no anchors)
    for cat, text, value in [("hyperparameter", "검색 단계의 top-k는 5이다", "5"), ("result", "2Wiki 정확도는 63.70%이다", "63.70%"),
                             ("model", "임베딩 모델은 all-mpnet-base-v2이다", "all-mpnet-base-v2"),
                             ("method", "검색된 passage의 본문이 생성 단계의 문맥으로 들어간다", "")]:
        c = s.add_check(t.id, text, "USEFUL")
        c.spec = {"category": cat, "value": value, "source_id": "SRC1"}
        s.complete_check(c.id, "VERIFIED", text, [{"tier": 4, "type": "pdf", "title": "LinearRAG", "url": "x", "supports": []}])
        specs.append(c.id)
    s._find_check(specs[2]).spec["value_in_quote"] = False  # the model's value is not in its own quote
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
        # as main.js stores it: the model's answer + what Pablo saw at each place in repro/ (desktop/where.js verify)
        {"role": "audit", "at": at(58), "status": "completed", "summary": "top-k가 논문과 다릅니다.", "items": [
            {"id": "C1", "status": "followed", "where": "", "found": "", "note": "keep.txt는 그대로다", "check": "unchecked"},
            {"id": specs[0], "status": "differs", "where": "config.yaml:5", "found": "top_k: 10", "note": "논문은 5",
             "check": "verified"},
            {"id": specs[1], "status": "followed", "where": "logs/2wiki.log:3", "found": "gpt_acc=63.70", "note": "",
             "check": "not_found"},  # a place the model made up: the log has one line, and 61.20 on it
            {"id": specs[2], "status": "differs", "where": "config.yaml:2", "found": "embedding_model: all-mpnet-base-v2",
             "note": "", "check": "value_mismatch"},  # says differs, but the paper's value is right there
            {"id": gap.id, "status": "chosen", "where": "config.yaml:2", "found": "seed: 42", "note": "",
             "check": "moved", "line_found": 12},
            {"id": specs[3], "status": "missing", "where": "run.py:3", "found": "print('top_k', cfg['retrieval']['top_k'])",
             "note": "검색도 생성도 하지 않고 설정만 출력한다", "check": "verified"}],
         # what no item covers: a method difference Pablo found there, one at a place the model made up, an experiment
         "outside": [
             {"kind": "method", "what": "설정한 임베딩 모델을 불러 쓰는 코드가 없습니다.", "where": "run.py:1-3",
              "found": "cfg = yaml.safe_load(open('config.yaml'))", "check": "verified"},
             {"kind": "scope", "what": "논문의 baseline 비교 실험이 이 폴더에 없습니다.", "where": "", "found": "", "check": "unchecked"},
             {"kind": "method", "what": "PageRank 대신 차수로 순위를 매깁니다.", "where": "retrieve.py:22",
              "found": "scores = sub.degree()", "check": "no_file"}]},
    ]}
    repro = os.path.join(d, "repro")
    shutil.copytree(DEMO, repro, dirs_exist_ok=True)
    with open(os.path.join(d, "chat.json"), "w", encoding="utf-8") as f:
        json.dump(chat, f, ensure_ascii=False)
    path = os.path.join(d, "view-T1.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(s, t.id))
    return path


class PapersJudge:  # C1/C3 stubs: one answer over both papers, each paper's row of the table
    def answer_from_sources(self, question, papers):
        return {"answer": "TinyRAG는 HotpotQA에서 61.5입니다 [1]. 두 논문 모두 HotpotQA와 MuSiQue로 평가합니다 [2].", "citations": [
            {"n": 1, "paper": "A", "page": 2, "quote": "TinyRAG reaches 61.5 accuracy on HotpotQA", "role": "table"},
            {"n": 2, "paper": "B", "page": 1, "quote": "We evaluate on HotpotQA and MuSiQue with 1,000 questions each", "role": "text"}]}

    def compare_paper(self, columns, title, pages):
        rows = {"TinyRAG": [("HotpotQA, MuSiQue", "We evaluate on HotpotQA and MuSiQue with 1,000 questions each", 1),
                            ("HotpotQA 61.5", "TinyRAG reaches 61.5 accuracy on HotpotQA", 2),
                            ("색인 3초", "Indexing takes 3 seconds", 2), ("", "", 0)],  # 효율: not what it says; 한계: not stated
                "OtherRAG": [("HotpotQA, MuSiQue", "We evaluate on HotpotQA and MuSiQue with 1,000 questions each", 1),
                             ("HotpotQA 58.2", "OtherRAG reaches 58.2 accuracy on HotpotQA", 2),
                             ("색인 95초", "Indexing takes 95 seconds on one GPU", 2),
                             ("효율은 색인 시간만 다룸", "We do not study efficiency beyond indexing time", 2)]}[title]
        return {"cells": [{"column": c, "value": v, "quote": q, "page": p} for c, (v, q, p) in zip(columns, rows)]}


THIRD = ["arXiv:2502.00002v1 [cs.IR] 2 Feb 2025. ThirdRAG: hypergraph retrieval for long documents.",
         "ThirdRAG reaches 63.0 accuracy on HotpotQA."]


def build_papers(d: str) -> dict:
    """C1-C3 offline: task T1 with two papers (TinyRAG from "arXiv", its file where the desktop keeps arXiv papers, and
    OtherRAG from a file), an answer over both, a comparison table. <d>/arxiv/ holds what a fake arxiv.org serves:
    TinyRAG v2 (the same bytes) and v3 (one sentence changed), and a third paper."""
    os.makedirs(os.path.join(d, "papers"), exist_ok=True)
    os.makedirs(os.path.join(d, "arxiv"), exist_ok=True)
    e = IntentEngine.load(os.path.join(d, "intent.json"))
    s = PabloSkill.load(os.path.join(d, "skill.json"), e, PapersJudge())
    t = s.start_task("TinyRAG 재현", [])
    t.created_at = at(0)
    a_v2 = tiny_pdf(TINY_A, "TinyRAG: A Tiny Graph RAG")
    pa, pb = os.path.join(d, "papers", "arxiv-2501.00001.pdf"), os.path.join(d, "OtherRAG.pdf")
    open(pa, "wb").write(a_v2)
    open(pb, "wb").write(tiny_pdf(TINY_B, "OtherRAG"))
    a, b = s.capture_pdf(pa, arxiv="2501.00001"), s.capture_pdf(pb)
    sc, _ = s.ask(t.id, "두 논문은 무엇으로 평가해?", [a.id, b.id])
    mid, cells, empty = s.compare(t.id, [a.id, b.id], ["데이터셋", "주요 결과", "효율", "한계"])
    e.save()
    s.save()
    papers = [{"id": a.id, "title": a.title, "arxiv": "2501.00001", "version": "v2", "sha256": a.version["content_hash"]},
              {"id": b.id, "title": b.title}]
    chat = {t.id: [{"role": "ask", "text": "두 논문은 무엇으로 평가해?", "at": at(10), "check": sc.id},
                   {"role": "compare", "at": at(20), "matrix": mid, "columns": ["데이터셋", "주요 결과", "효율", "한계"],
                    "papers": [{k: p[k] for k in ("id", "title")} | {"version": p.get("version")} for p in papers],
                    "cells": [c.id for c in cells],
                    "empty": [{"source": x["source_id"], "column": x["column"], **({"value": x["value"]} if x.get("value") else {})}
                              for x in empty]}]}
    with open(os.path.join(d, "chat.json"), "w", encoding="utf-8") as f:
        json.dump(chat, f, ensure_ascii=False)
    with open(os.path.join(d, "desktop.json"), "w", encoding="utf-8") as f:
        json.dump({"pdf": {t.id: papers}}, f, ensure_ascii=False)
    v3 = [TINY_A[0].replace("v2", "v3"), TINY_A[1].replace("ignores synonyms", "ignores aliases")]
    for name, data in [("2501.00001", tiny_pdf([TINY_A[0].replace("v2", "v3"), v3[1]], "TinyRAG: A Tiny Graph RAG")),
                       ("2501.00001v2", a_v2), ("2502.00002", tiny_pdf(THIRD, "ThirdRAG: Hypergraph Retrieval"))]:
        open(os.path.join(d, "arxiv", name), "wb").write(data)
    path = os.path.join(d, "view-T1.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(s, t.id))
    return {"view": os.path.abspath(path), "arxiv": os.path.abspath(os.path.join(d, "arxiv")), "a": a.id, "b": b.id}


if __name__ == "__main__":
    if sys.argv[1:2] == ["--papers"]:
        print(json.dumps(build_papers(sys.argv[2])))
    else:
        print(json.dumps({"view": os.path.abspath(build(sys.argv[1])), "repro": os.path.abspath(os.path.join(sys.argv[1], "repro"))}))
