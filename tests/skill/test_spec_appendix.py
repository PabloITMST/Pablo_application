"""D3 (0.8): conditions the extraction kept missing on the pages after the references. Run: python tests/skill/test_spec_appendix.py
A second pass reads the appendix with what the first found and may answer what it called missing; a quote the model
shortened by a number group or a bracketed aside is anchored on the page's whole span. Stub providers, no network.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))
sys.path.insert(0, HERE)

from pablo_v2.intent.engine import IntentEngine  # noqa: E402
from pablo_v2.skill import pdf  # noqa: E402
from pablo_v2.skill.evidence import AnchorRejected  # noqa: E402
from pablo_v2.skill.judge import SPEC_APPENDIX_SCHEMA, SPEC_SCHEMA, LLMJudge, appendix_start  # noqa: E402
from pablo_v2.skill.skill import PabloSkill  # noqa: E402
from ui_fixture import tiny_pdf  # noqa: E402

REFS = ("References Smith, J. and Lee, K. Tiny retrieval. In ICML, 2021. Park, H. Graphs, 2019. Kim, A. Masks, 2022. "
        "Cho, B. Prompts, 2020. Han, C. Labels, 2023.")
MORE_REFS = "Moon, D. Patterns, 2018. Yoo, E. Heads, 2021. Jang, F. Seeds, 2020. Oh, G. Losses, 2022."
PAPER = ["TinyMask: sample-specific masks. We follow Chen et al. (2023) to split the datasets.",
         "We evaluate by computing the relative errors of the posterior mean and standard deviation (SD) estimates "
         "with respect to HMC samples. AVERAGE 43.91 43.48 45.04 46.85 52.53 49.15 46.76 49.39 52.10 56.35 Note that",
         "Conclusion. We thank the reviewers. " + REFS,
         MORE_REFS,
         "Appendix C. Training details. We use a batch size of 256 for all datasets except DTD. "
         "The mask generator is initialized randomly and the pattern is set to a zero matrix before training."]


def test_gapped_anchor():
    """Only numbers (the other column group of a row the text runs into one line) or a short bracketed aside may be
    left out, at most twice; never a word, so 'we use dropout' never anchors on 'we do not use dropout'."""
    ps = PAPER[:2] + ["We do not use dropout in any layer. CIFAR10 256 0.01 0.1 DTD 64 0.01 0.1 GTSRB 256 0.01 0.1"]
    row = "AVERAGE 49.15 46.76 49.39 52.10 56.35"  # the ResNet-50 half, rebuilt with the row's label (D3, SSM G28)
    try:
        pdf.anchor(ps, row, 2)
        raise AssertionError("not verbatim: the exact match refuses it")
    except AnchorRejected:
        pass
    q, sel = pdf.anchor(ps, row, 2, gapped=True)
    assert q["exact"] == "AVERAGE 43.91 43.48 45.04 46.85 52.53 49.15 46.76 49.39 52.10 56.35" and sel["page"] == 2, q
    sd = "the relative errors of the posterior mean and standard deviation estimates with respect to HMC samples"
    q, _ = pdf.anchor(ps, sd, None, gapped=True)  # D3, BaM G21: "(SD)" left out
    assert q["exact"].startswith("the relative errors") and "deviation (SD) estimates" in q["exact"], q
    for bad, page in [("We use dropout in any layer.", 3),     # a word left out: never
                      ("AVERAGE 43.91 56.35", 2),              # too short to match with gaps
                      ("CIFAR10 256 0.1 DTD 64 0.1 GTSRB 256 0.1", 3),  # three stretches left out
                      ("CIFAR10 25 0.01 0.1 DTD 64", 3),        # '25' is not a part of '256'
                      ("dropout in any layer. CIFAR10 256 0.01", 3),  # verbatim: the exact match's job, never a gapped place
                      ("256 0.01 0.1 64", 3)]:                 # short and ambiguous
        try:
            pdf.anchor(ps, bad, page, gapped=True)
            raise AssertionError(bad)
        except AnchorRejected:
            pass
    try:  # two rows fit the same gapped quote: refused, never a guess
        pdf.anchor(["X 1 2 3 4 a b c d", "X 1 9 3 4 a b c d"], "X 1 3 4 a b", None, gapped=True)
        raise AssertionError("ambiguous")
    except AnchorRejected:
        pass


def test_appendix_start():
    """The appendix starts after the references heading, past the pages dense with years; none without references,
    with nothing after them, or with the word only on the first two pages."""
    assert appendix_start(PAPER) == 5
    assert appendix_start(PAPER[:4]) is None  # the paper ends with its references
    assert appendix_start(PAPER[:2] + ["Conclusion.", "Appendix A. Details."]) is None  # no references heading
    assert appendix_start([REFS, "Body.", "Appendix A. Details."]) is None  # a heading-like line on page 1 only
    assert appendix_start(PAPER[:3] + PAPER[4:]) == 4  # the appendix right after the references page


class Provider:  # records each call, answers the first pass and the appendix pass
    def __init__(self):
        self.calls = []

    def complete_json(self, prompt, schema):
        self.calls.append((prompt, schema))
        if schema is SPEC_SCHEMA:
            return {"items": [{"category": "split", "kind": "setting", "statement": "분할은 Chen et al. (2023)을 따른다",
                               "value": "Chen et al. (2023)", "quote": "We follow Chen et al. (2023) to split the datasets.",
                               "page": 1}],
                    "missing": [{"category": "training", "statement": "δ의 초기화가 없다"},
                                {"category": "training", "statement": "시드가 없다"}]}
        return {"items": [{"category": "training", "kind": "setting", "statement": "δ는 0 행렬로 초기화한다", "value": "0",
                           "quote": "the pattern is set to a zero matrix before training", "page": 5, "fills": 1}]}


def test_two_passes():
    """With an appendix: the first pass is told the pages from [p.5] on are read again; the second reads only those
    pages, with the first pass's conditions and its numbered missing settings; its items come back marked. Without
    one: a single pass, as before. The frozen answer (PABLO_SPEC_DUMP) says where the appendix started."""
    p, j = Provider(), None
    j = LLMJudge(p)
    with tempfile.TemporaryDirectory() as d:
        os.environ["PABLO_SPEC_DUMP"] = os.path.join(d, "dump.json")
        try:
            r = j.extract_spec(PAPER)
            dump = json.load(open(os.environ["PABLO_SPEC_DUMP"], encoding="utf-8"))
        finally:
            del os.environ["PABLO_SPEC_DUMP"]
    (first, s1), (second, s2) = p.calls
    assert s1 is SPEC_SCHEMA and s2 is SPEC_APPENDIX_SCHEMA
    assert "The pages from [p.5] on (after the references) are read again" in first and "[p.1] TinyMask" in first
    assert "[p.5] Appendix C." in second and "[p.4]" not in second and "TinyMask" not in second, second
    assert "- [split] 분할은 Chen et al. (2023)을 따른다 (p.1)" in second and "1. [training] δ의 초기화가 없다" in second
    assert [(x.get("from"), x.get("fills")) for x in r["items"]] == [(None, None), ("appendix", 1)], r
    assert len(r["missing"]) == 2 and dump["appendix"] == 5 and len(dump["items"]) == 2
    p = Provider()
    LLMJudge(p).extract_spec(PAPER[:2])
    assert len(p.calls) == 1 and "read again" not in p.calls[0][0] and "{appendix}" not in p.calls[0][0]


class Judge:  # the two passes as LLMJudge merges them
    def extract_spec(self, pages):
        return {"items": [
            {"category": "split", "kind": "setting", "statement": "분할은 Chen et al. (2023)을 따른다", "value": "Chen et al. (2023)",
             "quote": "We follow Chen et al. (2023) to split the datasets.", "page": 1},
            {"category": "result", "kind": "result", "statement": "ResNet-50 평균 정확도는 56.35이다", "value": "56.35",
             "quote": "AVERAGE 49.15 46.76 49.39 52.10 56.35", "page": 2},
            {"category": "hyperparameter", "kind": "setting", "statement": "배치 크기는 256이다", "value": "256",
             "quote": "We use a batch size of 256 for all datasets except DTD.", "page": 5},
            # the appendix pass: one the first pass has (same value), one new that answers missing #1, one paraphrased
            {"category": "hyperparameter", "kind": "setting", "statement": "DTD를 뺀 배치 크기는 256", "value": "256",
             "quote": "a batch size of 256 for all datasets", "page": 5, "from": "appendix", "fills": 0},
            {"category": "training", "kind": "setting", "statement": "δ는 0 행렬로 초기화한다", "value": "0",
             "quote": "the pattern is set to a zero matrix before training", "page": 5, "from": "appendix", "fills": 1},
            {"category": "training", "kind": "setting", "statement": "생성기는 무작위 초기화", "value": "",
             "quote": "the generator starts from random weights", "page": 5, "from": "appendix", "fills": 0}],
            "missing": [{"category": "training", "statement": "δ의 초기화가 없다"},
                        {"category": "training", "statement": "시드가 없다"}]}


def test_spec_merges_the_appendix_pass():
    """spec(): the rebuilt table row anchors on the whole row; an appendix item the first pass has is not added twice;
    a new one is a condition like any other; the missing setting it answers is not listed; a paraphrase is dropped."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "tiny.pdf")
        open(path, "wb").write(tiny_pdf(PAPER, "TinyMask"))
        s = PabloSkill(IntentEngine(), Judge())
        t = s.start_task("TinyMask 재현", [])
        stated, missing, dropped = s.spec(t.id, s.capture_pdf(path).id)
        assert [c.requirement for c in stated] == ["분할은 Chen et al. (2023)을 따른다", "ResNet-50 평균 정확도는 56.35이다",
                                                   "배치 크기는 256이다", "δ는 0 행렬로 초기화한다"], stated
        row = next(a for _, a in s.evidence_for(stated[1].id))
        assert row.quote["exact"].startswith("AVERAGE 43.91") and row.quote["exact"].endswith("56.35"), row.quote
        assert [c.requirement for c in missing] == ["시드가 없다"]
        assert [x["statement"] for x in dropped] == ["생성기는 무작위 초기화"]
        assert len(s.state.anchors) == 4  # the duplicate's anchor is not left behind


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
