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


def test_crlf_checkout():
    """A Windows checkout gives the base CRLF line ends: every drift still applies, on the same line."""
    with tempfile.TemporaryDirectory() as d:
        base = os.path.join(d, "base")
        shutil.copytree(B.BASE, base)
        for root, _, files in os.walk(base):
            for f in files:
                p = os.path.join(root, f)
                t = open(p, encoding="utf-8", newline="").read().replace("\r\n", "\n").replace("\n", "\r\n")
                open(p, "w", encoding="utf-8", newline="").write(t)
        for drift in B.CATALOG:
            lf, crlf = os.path.join(d, "lf-" + drift["id"]), os.path.join(d, "crlf-" + drift["id"])
            shutil.copytree(B.BASE, lf)
            shutil.copytree(base, crlf)
            assert B.plant(crlf, drift) == B.plant(lf, drift), drift["id"]


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


def test_locs():
    assert B.locs("config.yaml:5 (top_k)") == [("config.yaml", 5, 5)]
    assert B.locs("preprocess.py:6,15, graph.py:3") == [("preprocess.py", 6, 6), ("preprocess.py", 15, 15), ("graph.py", 3, 3)]
    assert B.locs("retrieve.py line 16; graph.py#L10-12") == [("retrieve.py", 16, 16), ("graph.py", 10, 12)]
    assert B.locs("logs\\2wikimultihopqa.log:1") == [("logs/2wikimultihopqa.log", 1, 1)]
    assert B.locs("evaluate.py (함수가 없음)") == [("evaluate.py", None, None)] and B.locs("") == []


def test_compare():
    """The comparison group's scoring: the drift's place and what changed there, the same rule for both systems."""
    assert set(B.SAYS) == {x["id"] for x in B.CATALOG}
    with tempfile.TemporaryDirectory() as d:
        truth = B.variants(d, n=8, seed=7, clean=1)
        at = lambda p: f"{p['file']}:{p['line']}" if p["line"] else p["file"]  # noqa: E731

        def said(v, p):  # a report quoting the drifted line and naming the change (a removal shows only in words)
            line = open(os.path.join(v["dir"], p["file"]), encoding="utf-8").read().splitlines()[p["line"] - 1] if p["line"] else ""
            return line + " / " + p["id"].replace("_", " ")

        sys_ = lambda f: [{"variant": v["name"], "ms": 1, "items": f(v)} for v in truth["variants"]]  # noqa: E731
        c = B.compare({
            "one": sys_(lambda v: [{"what": "differs", "code": said(v, p), "where": at(p)} for p in v["planted"]]),
            "bundled": sys_(lambda v: [{"what": "all", "code": " / ".join(said(v, p) for p in v["planted"]),
                                        "where": "; ".join(at(p) for p in v["planted"])}] if v["planted"] else []),
            "wide": sys_(lambda v: [{"what": said(v, p), "where": f"{p['file']}:1-80"} for p in v["planted"]]),
            "offtopic": sys_(lambda v: [{"what": "no retrieval-quality metrics", "where": at(p)} for p in v["planted"]]),
            "noisy": sys_(lambda v: [{"what": "baselines not run", "where": "run.py:1"}]),
        }, truth)
        assert (c["one"]["found"], c["one"]["extra"], c["one"]["clean_extra"], c["one"]["missed"]) == (18, 0, 0, [])
        assert (c["bundled"]["found"], c["bundled"]["extra"]) == (18, 0)  # one report may name several places
        assert c["wide"]["found"] == sum(1 for v in truth["variants"] for p in v["planted"] if p["line"] is None)
        o = c["offtopic"]  # on the drift's line, about something else there: not found, and outside the benchmark
        assert (o["found"], o["found_loc"], o["extra"], len(o["missed"])) == (0, 18, 18, 18)
        assert c["noisy"]["clean_extra"] == 1 and c["noisy"]["extras"][0]["what"] == "baselines not run"
        md = B.markdown_compare(c, {"date": "test", "model": "x", "seed": 7, "variants": 9})
        assert "| one | 18/18 (100.0%) | 18/18 |" in md and "## noisy: 심은 것 밖의 보고 9건" in md
    # Korean particles follow values: "delta=2를", "500개", "lam=0.5로" still say the value
    p = lambda i: {"id": i}  # noqa: E731
    assert B.about({"code": "delta=2를 사용"}, p("delta")) and B.about({"what": "질문 500개"}, p("questions_500"))
    assert B.about({"code": "lam=0.5로 설정"}, p("lambda")) and not B.about({"code": "1000개"}, p("topk_config"))


def test_recheck():
    """Pablo's check recomputed by desktop/where.js: a drift claim quoting its line holds in its own folder, and mostly
    not in another variant's folder (the control)."""
    with tempfile.TemporaryDirectory() as d:
        truth = B.variants(d, n=8, seed=7, clean=1)
        keys = {k: f"SC{i}" for i, k in enumerate(list(truth["variants"][0]["expect"]), 1)}
        runs = [{"variant": v["name"], "ms": 1, "items": [
            {"id": keys[p["key"]], "status": p["expect"], "where": f"{p['file']}:{p['line']}", "note": "",
             "found": open(os.path.join(v["dir"], p["file"]), encoding="utf-8").read().splitlines()[p["line"] - 1].strip()}
            for p in v["planted"] if p["line"]]} for v in truth["variants"]]
        own = B.recheck(runs, truth, keys)
        if own is None:
            print("skip test_recheck: no node or desktop/where.js")
            return
        n = sum(len(r["items"]) for r in runs)
        assert B.tally(own, truth, keys)["drift"] == {"verified": n}
        other = B.tally(B.recheck(runs, truth, keys, shift=1), truth, keys)["drift"]
        assert sum(other.values()) == n and other.get("verified", 0) < n / 2, other
        assert "check" not in runs[1]["items"][0]  # the saved answers stay as they were


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
