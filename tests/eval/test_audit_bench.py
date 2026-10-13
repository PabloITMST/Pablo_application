"""재현 점검 benchmark, offline: the planted drifts, the variants and the scoring (no model calls).
Run: python tests/eval/test_audit_bench.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import audit_bench as B  # noqa: E402


def test_drifts_apply_to_the_base():
    """Every drift edits text that occurs once in the base, and leaves its mark on a line the truth can point at."""
    keys = {c["key"] for c in B.conditions()["conditions"]}
    with tempfile.TemporaryDirectory() as d:
        for drift in B.CATALOG:
            folder = os.path.join(d, drift["id"])
            shutil.copytree(B.BASE, folder)
            line = B.plant(folder, drift)
            assert drift["key"] in keys and all(k in keys for k in drift.get("affects", []))
            assert (line is None) == (drift["mark"] is None) and drift["expect"] in B.DETECTED
            base = open(os.path.join(B.BASE, drift["file"]), encoding="utf-8").read()
            if drift["mark"]:
                assert not any(B.marked(x, drift["mark"]) for x in base.splitlines()), f"{drift['id']}: its mark is in the base"


def test_variants():
    with tempfile.TemporaryDirectory() as d:
        t = B.variants(d, n=8, seed=7, clean=1)
        names = [v["name"] for v in t["variants"]]
        assert names[0] == "v00-clean" and len(names) == 9
        planted = [p for v in t["variants"] for p in v["planted"]]
        assert sorted(p["id"] for p in planted) == sorted(x["id"] for x in B.CATALOG)  # each drift once
        for v in t["variants"]:
            ks = [p["key"] for p in v["planted"]]
            assert len(ks) == len(set(ks)) and 0 <= len(ks) <= 3
            for p in v["planted"]:
                assert v["expect"][p["key"]] == p["expect"]
            assert v["expect"]["seed"] == "chosen"
        clean = t["variants"][0]
        assert set(clean["expect"].values()) == {"followed", "chosen"}
        again = B.variants(os.path.join(d, "again"), n=8, seed=7, clean=1)  # same seed, same benchmark
        assert [[p["id"] for p in v["planted"]] for v in again["variants"]] == [[p["id"] for p in v["planted"]] for v in t["variants"]]


def test_where():
    assert B.where("config.yaml:10-11") == ("config.yaml", 10, 11)
    assert B.where("logs\\2wikimultihopqa.log:1") == ("logs/2wikimultihopqa.log", 1, 1)
    assert B.where("retrieve.py#L16") == ("retrieve.py", 16, 16)
    assert B.where("C:\\w\\v01\\config.yaml:9") == ("C:/w/v01/config.yaml", 9, 9)
    assert B.where("evaluate.py") == ("evaluate.py", None, None) and B.where("") == ("", None, None)


def _answers(truth, keys, how):
    """Fake audit runs: how(variant, key, expected) -> (status, where)."""
    runs = []
    for v in truth["variants"]:
        items = []
        for k, exp in v["expect"].items():
            st, w = how(v, k, exp)
            items.append({"id": keys[k], "status": st, "where": w, "found": "", "note": ""})
        runs.append({"variant": v["name"], "items": items, "ms": 1000})
    return runs


def test_score():
    with tempfile.TemporaryDirectory() as d:
        truth = B.variants(d, n=8, seed=7, clean=1)
        keys = {k: f"SC{i}" for i, k in enumerate(list(truth["variants"][0]["expect"]), 1)}

        def perfect(v, k, exp):
            p = next((p for p in v["planted"] if p["key"] == k), None)
            return (exp if exp != "ambiguous" else "unclear"), (f"{p['file']}:{p['line']}" if p and p["line"] else p["file"] if p else "")

        s = B.score(_answers(truth, keys, perfect), truth, keys)["summary"]
        assert (s["recall"], s["exact_status"], s["false_alarm_rate"], s["file_accuracy"], s["line_accuracy"], s["open_chosen"]) == \
            (100.0, 100.0, 0.0, 100.0, 100.0, 100.0), s

        blind = B.score(_answers(truth, keys, lambda v, k, exp: ("followed", "")), truth, keys)
        assert blind["summary"]["recall"] == 0.0 and blind["summary"]["false_alarm_rate"] == 0.0
        assert blind["planted"]["missed_as"] == {"followed": 18}

        alarmist = B.score(_answers(truth, keys, lambda v, k, exp: ("differs", "config.yaml:1")), truth, keys)
        a = alarmist["summary"]
        assert a["recall"] == 100.0 and a["false_alarm_rate"] == 100.0 and a["line_accuracy"] < 50
        assert alarmist["false_alarms"]["topk"] == 7  # followed in 7 of the 9 variants (two have a top-k drift)
        md = B.markdown(alarmist, {"date": "test", "model": "x", "avg_ms": 1})
        assert "| 오탐률 | 100.0%" in md and "## 어긋남별" in md


def test_state():
    if not os.path.exists(os.path.join(B.ROOT, "LinearRAG.pdf")):
        print("skip test_state: LinearRAG.pdf not here")
        return
    with tempfile.TemporaryDirectory() as d:
        r = B.state(d)
        assert set(r["keys"]) == {c["key"] for c in B.conditions()["conditions"]} | {"seed"}
        assert os.path.exists(r["view"])
        s = json.load(open(os.path.join(d, "skill.json"), encoding="utf-8"))
        specs = [c for c in s["checks"] if c.get("spec")]
        assert len([c for c in specs if c["outcome"] == "VERIFIED"]) == 17 and len(s["anchors"]) == 17


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
