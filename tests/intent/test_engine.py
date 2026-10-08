"""Intent Engine tests. Run: python tests/intent/test_engine.py
PABLO_LLM=1 also runs the acceptance case through the signed-in Codex account (slow, ~10s/message).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from pablo_v2.__main__ import ACCEPTANCE, SCENARIO  # noqa: E402
from pablo_v2.intent.engine import IntentEngine  # noqa: E402
from pablo_v2.intent.extract import HeuristicExtractor  # noqa: E402


def run_acceptance(extractor):
    e = IntentEngine(extractor=extractor)
    r = {}
    for role, text in ACCEPTANCE:
        ks = e.process_message(text, role=role)
        r[e.state.messages[-1]["id"]] = ks[0] if ks else None
    return e, r


def check_acceptance(e, r):
    assert r["M1"].item_id == "G1"
    c_official = e.get_item(r["M2"].item_id)
    assert c_official.kind == "constraint" and c_official.strength == "soft", "가능하면/우선/있으면 -> soft"
    c_split = e.get_item(r["M3"].item_id)
    assert c_split.kind == "constraint" and c_split.strength == "hard", "반드시 -> hard"
    assert r["M4"].status == "ignored", "README 먼저 -> ignore"
    assert r["M5"].status == "pending", "편하긴 해 -> pending"
    assert r["M6"] is None, "agent message produces no candidate"
    assert all(i.source.type == "user" for i in e.state.items), "agent text never becomes intent"
    k = r["M7"]
    assert (k.status, k.item_id) == ("reinforced", c_official.id), "correction -> reinforce existing"
    assert c_official.priority > 1 and c_official.strength == "soft", "correction raises priority, not hard"
    k = r["M8"]
    assert k.features["relation"]["type"] == "conflict" and k.item_id == c_split.id
    assert k.status == "deviation" and c_split.status == "active", "hard constraint held, not replaced"
    assert e.get_deviations() == [k]


def test_acceptance_heuristic():
    check_acceptance(*run_acceptance(HeuristicExtractor()))


def test_acceptance_llm():
    if os.environ.get("PABLO_LLM") != "1":
        return
    from pablo_v2.intent.extract import LLMExtractor
    from pablo_v2.llm import CodexProvider

    check_acceptance(*run_acceptance(LLMExtractor(CodexProvider())))


def test_soft_conflict_supersedes():
    e = IntentEngine()
    e.process_message("공식 코드 있으면 그거 써.")
    k = e.process_message("공식 구현 대신 custom으로 바꾸자.")[0]
    old, new = e.get_item("C1"), e.get_item(k.item_id)
    assert old.status == "superseded" and old.superseded_by == new.id
    assert e.get_intent_history()[-2].change_type == "deviation"


def test_m1_scenario_and_persistence():
    path = os.path.join(tempfile.mkdtemp(), "intent.json")
    e = IntentEngine(path=path)
    r = [e.process_message(t)[0] for t in SCENARIO]
    assert [k.status for k in r] == ["committed", "committed", "ignored", "pending", "committed", "reinforced"]
    assert e.get_item("C1").priority == 3 and e.get_item("C1").strength == "soft"

    k = e.process_message("TensorFlow 말고 PyTorch로 하자.")[0]  # firmer version of pending K4
    assert k.status == "committed" and r[3].status == "merged" and r[3].item_id == k.item_id

    e.add_assumption("Dataset Y는 v2라고 추정")
    assert IntentEngine.load(path).state.to_dict() == e.state.to_dict()


def test_repeated_pending_promotes():
    e = IntentEngine()
    k1 = e.process_message("PyTorch가 좀 편할 것 같긴 한데.")[0]
    k2 = e.process_message("PyTorch로 하면 좋을 것 같은데.")[0]
    assert k1.status == k2.status == "promoted" and k1.item_id == k2.item_id


def test_manual_promote_reject():
    e = IntentEngine()
    k = e.process_message("PyTorch가 좀 편할 것 같긴 한데.")[0]
    assert e.promote_candidate(k.id).id == "C1" and k.status == "promoted"
    k2 = e.process_message("JAX도 괜찮을 것 같은데.")[0]
    e.reject_candidate(k2.id)
    assert e.get_pending_candidates() == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
