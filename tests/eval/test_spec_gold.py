"""D3 (0.8) the spec gold-set scorer, offline: a small generated paper, a stub extraction, a hand-made gold.
Run: python tests/eval/test_spec_gold.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))
sys.path.insert(0, os.path.join(HERE, "..", "skill"))
sys.path.insert(0, os.path.join(HERE, "spec_gold"))

from pablo_v2.intent.engine import IntentEngine  # noqa: E402
from pablo_v2.skill import pdf  # noqa: E402
from pablo_v2.skill.skill import PabloSkill  # noqa: E402
from ui_fixture import TINY_A, tiny_pdf  # noqa: E402
import score  # noqa: E402


class Judge:  # three conditions: one where the gold is, one with the gold's value elsewhere, one the gold does not have
    def extract_spec(self, pages):
        return {"items": [
            {"category": "result", "statement": "HotpotQA 정확도는 61.5이다", "value": "61.5",
             "quote": "TinyRAG reaches 61.5 accuracy on HotpotQA", "page": 2},
            {"category": "dataset", "statement": "데이터셋마다 1,000문항", "value": "1,000",
             "quote": "MuSiQue with 1,000 questions each", "page": 1},
            {"category": "training", "statement": "색인은 GPU 한 장에서 12초", "value": "12",
             "quote": "Indexing takes 12 seconds on one GPU", "page": 2}],
            "missing": [{"category": "training", "statement": "시드가 없다"}]}


GOLD = {"paper": "TinyRAG", "pdf": "tiny.pdf", "conditions": [
    {"id": "G1", "category": "result", "statement": "HotpotQA 61.5", "value": "61.5", "quote": "reaches 61.5 accuracy", "page": 2,
     "status": "confirmed"},
    {"id": "G2", "category": "dataset", "statement": "문항 1000개", "value": "1000", "quote": "We evaluate on HotpotQA", "page": 1,
     "status": "confirmed"},
    {"id": "G3", "category": "protocol", "statement": "개체 연결은 동의어를 무시한다", "value": "",
     "quote": "entity linking ignores synonyms", "page": 2, "status": "confirmed"},
    {"id": "G4", "category": "result", "statement": "틀린 후보", "value": "99", "quote": "Indexing takes 12 seconds", "page": 2,
     "status": "rejected"},
    {"id": "G5", "category": "training", "statement": "아직 확인 전", "value": "12", "quote": "Indexing takes 12 seconds", "page": 2,
     "status": "candidate"}]}


def test_score():
    """recall over confirmed gold conditions, precision over extractions; a place match (the anchors overlap) and a
    value match (same category, the same number written differently) both count; rejected never, candidates only with
    --all; what matches nothing is listed, with the page, for a person to look at."""
    with tempfile.TemporaryDirectory() as d:
        data = tiny_pdf(TINY_A, "TinyRAG: A Tiny Graph RAG")
        open(os.path.join(d, "tiny.pdf"), "wb").write(data)
        s = PabloSkill.load(os.path.join(d, "skill.json"), IntentEngine(), Judge())
        t = s.start_task("TinyRAG 재현", [])
        s.spec(t.id, s.capture_pdf(os.path.join(d, "tiny.pdf")).id)
        ex = score.extracted(d, t.id)
        assert [e["category"] for e in ex] == ["result", "dataset", "training"] and all(e["at"] for e in ex)
        r = score.score(GOLD, pdf.pages(data), ex)
        assert (r["gold"], r["extracted"], r["recall"], r["precision"]) == (3, 3, 0.667, 0.667), r
        assert sorted((m["gold"], m["how"]) for m in r["matched"]) == [("G1", "place"), ("G2", "value")]
        assert [m["gold"] for m in r["missed"]] == ["G3"] and [u["page"] for u in r["unmatched"]] == [2]
        dry = score.score(GOLD, pdf.pages(data), ex, everything=True)  # the candidate G5 counts too (the 12 s extraction)
        assert (dry["gold"], dry["recall"], dry["precision"]) == (4, 0.75, 1.0), dry
        moved = json.loads(json.dumps(GOLD))
        moved["conditions"][0]["quote"] = "not in this paper at all"  # a quote from another version: reported, and
        r2 = score.score(moved, pdf.pages(data), ex)                     # the condition still matches by its value
        assert r2["unanchored_gold"] == ["G1"] and ("G1", "value") in [(m["gold"], m["how"]) for m in r2["matched"]]
        json.dump(GOLD, open(os.path.join(d, "gold.json"), "w", encoding="utf-8"), ensure_ascii=False)
        md = score.markdown("TinyRAG", r)
        assert "재현율 67%" in md and "정밀도 67%" in md and "개체 연결은 동의어를 무시한다 (p.2)" in md, md


def test_review_rules():
    """review: a result quoted at the gold's place but with another value is no match (listed place_only for a person);
    a fact or scope extraction is outside the precision denominator, and one at a gold condition's place is a kind miss."""
    pages = pdf.pages(tiny_pdf(TINY_A, "TinyRAG: A Tiny Graph RAG"))
    at = {g["id"]: g["at"] for g in score.gold_spans(GOLD, pages)}
    ex = [{"id": "SC1", "category": "result", "kind": "result", "statement": "HotpotQA는 58.2", "value": "58.2", "at": at["G1"]},
          {"id": "SC2", "category": "dataset", "kind": "fact", "statement": "HotpotQA로 평가", "value": "", "at": at["G2"]},
          {"id": "SC3", "category": "protocol", "kind": "setting", "statement": "동의어 무시", "value": "", "at": at["G3"]}]
    r = score.score(GOLD, pages, ex)
    assert (r["extracted"], r["aside"], r["recall"], r["precision"]) == (2, 1, 0.333, 0.5), r
    assert [(x["gold"], x["check"]) for x in r["place_only"]] == [("G1", "SC1")]
    assert [(x["check"], x["gold"]) for x in r["kind_misses"]] == [("SC2", "G2")]
    md = score.markdown("TinyRAG", r)
    assert "값이 다른 결과" in md and "(값 58.2, 정답 61.5)" in md and "정밀도 분모 밖" in md, md


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
