"""재현 점검 benchmark: how often 🔎 재현 점검 finds a planted drift from the paper, and how often it flags one that is not there.

  state <dir>                       a Pablo state with LinearRAG.pdf and the frozen conditions (linearrag_conditions.json),
                                    each anchored on its page -> {view, task, keys: {condition key: check id}}
  variants <dir> [--n 8] [--seed 7] [--clean 1] [--set base|hard]
                                    copies of repro_base/ (a folder that follows every condition) with 1-3 planted drifts
                                    each, plus clean copies -> <dir>/<name>/ and <dir>/truth.json
  score <results.json> <truth.json> <keys.json> [--out <prefix>] [--saved-checks]
                                    the audit results (check.js --audit-bench) against the truth -> markdown + json;
                                    Pablo's check of each answer is recomputed with desktop/where.js (needs node) on
                                    regenerated variants, plus a control in the wrong folders (--saved-checks: as saved)
  baseline-prompt                   the comparison group's prompt and answer schema (paper text + "find the departures")
  compare <pablo results> <plain results> <truth.json> [--out <prefix>]
                                    the two on the same variants, scored by location -> markdown + json

Truth per variant and condition: the planted drift's expected status (differs | missing); "followed" for a condition the
base folder follows and no drift touched; "ambiguous" (not scored) when a drift makes another condition moot (e.g. no
PageRank -> its damping factor is unused). Two drifts in one variant never share a condition or a code region.
Run: python tests/eval/audit_bench.py <command> ...   (state needs LinearRAG.pdf at the repo root)
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
BASE = os.path.join(HERE, "repro_base")
CONDITIONS = os.path.join(HERE, "linearrag_conditions.json")
WHERE_JS = os.path.join(ROOT, "desktop", "where.js")
DETECTED = ("differs", "missing")

# one planted drift: edits (old -> new, each old exactly once in the file); mark = text on the drifted line (None: removed)
# affects: conditions the drift makes moot (not scored in its variant); sets: method conditions it changes ({key: status})
CATALOG = [
    dict(id="topk_config", key="topk", region="cfg.topk", file="config.yaml", expect="differs", mark="top_k: 10",
         affects=["m_rank"], edits=[("  top_k: 5\n", "  top_k: 10\n")]),
    dict(id="topk_hardcoded", key="topk", region="retrieve.k", file="retrieve.py", expect="differs", mark="k = 10",
         affects=["m_rank"], edits=[('    k = cfg["retrieval"]["top_k"]\n', "    k = 10  # more context helps\n")]),
    dict(id="embedding", key="embedding", region="cfg.embedding", file="config.yaml", expect="differs", mark="all-MiniLM-L6-v2",
         edits=[("embedding_model: all-mpnet-base-v2\n", "embedding_model: all-MiniLM-L6-v2\n")]),
    dict(id="llm", key="llm", region="cfg.llm", file="config.yaml", expect="differs", mark="llm: gpt-4o\n",
         edits=[("llm: gpt-4o-mini\n", "llm: gpt-4o\n")]),
    dict(id="damping", key="damping", region="cfg.damping", file="config.yaml", expect="differs", mark="damping: 0.5",
         edits=[("  damping: 0.85\n", "  damping: 0.5\n")]),
    dict(id="delta", key="delta", region="cfg.delta", file="config.yaml", expect="differs", mark="delta: 2",
         edits=[("  delta: 4\n", "  delta: 2\n")]),
    dict(id="lambda", key="lambda", region="cfg.lam", file="config.yaml", expect="differs", mark="lam: 0.5",
         edits=[("  lam: 0.05\n", "  lam: 0.5\n")]),
    dict(id="datasets_drop", key="datasets", region="cfg.datasets", file="config.yaml", expect="differs", mark="musique]",
         edits=[("datasets: [hotpotqa, 2wikimultihopqa, musique, medical]\n", "datasets: [hotpotqa, 2wikimultihopqa, musique]\n")]),
    dict(id="questions_500", key="questions", region="cfg.questions", file="config.yaml", expect="differs",
         mark="questions_per_dataset: 500", edits=[("  questions_per_dataset: 1000\n", "  questions_per_dataset: 500\n")]),
    dict(id="split_test", key="questions", region="cfg.split", file="config.yaml", expect="differs", mark="split: test",
         edits=[("  split: validation\n", "  split: test\n")]),
    dict(id="segment_window", key="segment", region="pre.split", file="preprocess.py", expect="differs", mark="words[i:i + 50]",
         edits=[('    # sentence boundaries: periods, exclamation and question marks\n'
                 '    return [s.strip() for s in re.split(r"(?<=[.!?])\\s+", passage) if s.strip()]\n',
                 "    words = passage.split()\n"
                 '    return [" ".join(words[i:i + 50]) for i in range(0, len(words), 50)]\n')]),
    dict(id="ner_regex", key="ner", region="pre.ner", file="preprocess.py", expect="differs", mark="re.findall",
         edits=[('import spacy\n\nNLP = spacy.load("en_core_web_sm")\n\n\n', "\n"),
                ("    return [ent.text for ent in NLP(sentence).ents]\n",
                 '    return re.findall(r"\\b[A-Z][a-z]+(?: [A-Z][a-z]+)*\\b", sentence)\n')]),
    dict(id="graph_no_sentences", key="graph", region="graph.body", file="graph.py", expect="differs", mark="entities(text)",
         affects=["segment"],
         edits=[("        for i, sent in enumerate(split_sentences(text)):\n"
                 '            sid = f"{pid}#s{i}"\n'
                 '            g.add_node(sid, kind="sentence")\n'
                 "            g.add_edge(pid, sid)\n"
                 "            for ent in entities(sent):\n"
                 '                g.add_node(ent, kind="entity")\n'
                 "                g.add_edge(sid, ent)\n"
                 "                g.add_edge(ent, pid)\n",
                 "        for ent in entities(text):\n"
                 '            g.add_node(ent, kind="entity")\n'
                 "            g.add_edge(ent, pid)\n")]),
    dict(id="ppr_degree", key="ppr", region="retrieve.rank", file="retrieve.py", expect="differs", mark="sub.degree",
         affects=["damping"], sets={"m_seed_ppr": "differs", "m_rank": "differs"},
         edits=[('    scores = nx.pagerank(sub, alpha=cfg["pagerank"]["damping"], personalization=personalization)\n',
                 "    scores = {n: sub.degree(n) * personalization[n] for n in sub}  # faster than PageRank\n")]),
    dict(id="contain_missing", key="contain_acc", region="eval.contain", file="evaluate.py", expect="missing", mark=None,
         affects=["medical_gpt_only", "result_contain"],
         edits=[("def contain_acc(pred: str, gold: str) -> float:\n    return float(gold.lower() in pred.lower())\n\n\n", ""),
                ('    if dataset != "medical":  # Medical answers are long descriptions: GPT-ACC only\n'
                 '        out["contain_acc"] = 100 * mean(contain_acc(p, g) for p, g in zip(preds, golds))\n', "")]),
    dict(id="medical_both", key="medical_gpt_only", region="eval.contain", file="evaluate.py", expect="differs",
         mark='    out["contain_acc"]',
         edits=[('    if dataset != "medical":  # Medical answers are long descriptions: GPT-ACC only\n'
                 '        out["contain_acc"]', '    out["contain_acc"]')]),
    dict(id="result_gpt_low", key="result_gpt", region="log.gpt", file="logs/2wikimultihopqa.log", expect="differs",
         mark="gpt_acc=58.10", edits=[("gpt_acc=63.70", "gpt_acc=58.10")]),
    dict(id="result_contain_low", key="result_contain", region="log.contain", file="logs/2wikimultihopqa.log",
         expect="differs", mark="contain_acc=64.35", edits=[("contain_acc=70.20", "contain_acc=64.35")]),
]
# held out (2026-10-13): drift types the audit prompt was never revised on. The obvious place stays right (the config,
# a plain line) and the change hides elsewhere: an off-by-one, an override, a literal in a path, a swapped argument.
HARD = [
    dict(id="topk_offbyone", key="topk", region="retrieve.return", file="retrieve.py", expect="differs", mark="[:k + 1]",
         affects=["m_rank"], edits=[("reverse=True)[:k]\n", "reverse=True)[:k + 1]\n")]),
    dict(id="topk_cli", key="topk", region="run.cli", file="run.py", expect="differs", mark="default=10", affects=["m_rank"],
         edits=[("import json\n", "import argparse\nimport json\n"),
                ('cfg = yaml.safe_load(open("config.yaml"))\n',
                 'cfg = yaml.safe_load(open("config.yaml"))\nap = argparse.ArgumentParser()\n'
                 'ap.add_argument("--top-k", type=int, default=10)\n'
                 'cfg["retrieval"]["top_k"] = ap.parse_args().top_k  # the command line wins over the file\n')]),
    dict(id="split_hardcoded", key="questions", region="run.data", file="run.py", expect="differs", mark="/test.json",
         edits=[("open(f\"data/{name}/{cfg['eval']['split']}.json\"))", 'open(f"data/{name}/test.json"))')]),
    dict(id="questions_offbyone", key="questions", region="run.data", file="run.py", expect="differs",
         mark='"questions_per_dataset"] - 1]', edits=[('[: cfg["eval"]["questions_per_dataset"]]\n',
                                                       '[: cfg["eval"]["questions_per_dataset"] - 1]\n')]),
    dict(id="log_questions", key="questions", region="log.questions", file="logs/2wikimultihopqa.log", expect="differs",
         mark="questions=500", affects=["result_gpt", "result_contain"], edits=[("questions=1000", "questions=500")]),
    dict(id="damping_inverted", key="damping", region="retrieve.alpha", file="retrieve.py", expect="differs",
         mark="alpha=1 - cfg", affects=["m_seed_ppr"],
         edits=[('alpha=cfg["pagerank"]["damping"]', 'alpha=1 - cfg["pagerank"]["damping"]')]),
    dict(id="contain_swapped", key="contain_acc", region="eval.contain", file="evaluate.py", expect="differs",
         mark="contain_acc(g, p)", edits=[("contain_acc(p, g) for p, g", "contain_acc(g, p) for p, g")]),
    dict(id="medical_case", key="medical_gpt_only", region="eval.medical", file="evaluate.py", expect="differs",
         mark='!= "Medical"', edits=[('if dataset != "medical":', 'if dataset != "Medical":')]),
    dict(id="judge_model", key="llm", region="eval.judge", file="evaluate.py", expect="differs", mark='client, "gpt-4o")',
         affects=["gpt_acc"], edits=[('gpt_acc(p, g, client, cfg["llm"])', 'gpt_acc(p, g, client, "gpt-4o")')]),
    dict(id="embedding_env", key="embedding", region="run.encoder", file="run.py", expect="differs", mark="all-MiniLM-L6-v2",
         edits=[("import sys\n", "import os\nimport sys\n"),
                ('SentenceTransformer(cfg["embedding_model"])',
                 'SentenceTransformer(os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))')]),
    dict(id="seed_unused", key="seed", region="run.seed", file="run.py", expect="missing", mark=None,
         edits=[('random.seed(cfg["seed"])\n', "")]),  # seed: 42 stays in the config; nothing applies it
    dict(id="lambda_comment", key="lambda", region="cfg.lam", file="config.yaml", expect="differs", mark="lam: 0.5",
         edits=[("  lam: 0.05\n", "  lam: 0.5  # the paper's λ\n")]),
]
SETS = {"base": CATALOG, "hard": HARD}
OPEN_EXPECT = {"seed": "chosen", "prompt": "chosen"}  # the base fixes seed: 42 and a prompt; the paper names neither
# what a report about the drift says (regex, any case): in the comparison, a report that lands on the drift's line but
# talks about something else there (e.g. "no retrieval-quality metrics" at evaluate.py:15-18) has not found it
SAYS = {
    "topk_config": r"\b10\b", "topk_hardcoded": r"\b10\b|하드코딩|hard.?cod", "embedding": r"MiniLM",
    "llm": r"gpt-4o(?!-mini)", "damping": r"\b0\.5\b", "delta": r"(delta|δ)\W{0,3}2\b", "lambda": r"\b0\.5\b",
    "datasets_drop": r"medical|의학|musique\]", "questions_500": r"\b500\b", "split_test": r"\btest\b",
    "segment_window": r"\b50\b|고정.{0,4}(창|단어|길이)|window", "ner_regex": r"정규|regex|re\.findall|대문자|capitali",
    "graph_no_sentences": r"sentence|문장", "ppr_degree": r"degree|차수", "contain_missing": r"contain",
    "medical_both": r"medical|의학", "result_gpt_low": r"58\.1", "result_contain_low": r"64\.35",
    # HARD
    "topk_offbyone": r"k ?\+ ?1|\b6\b|하나 더|one more|off.?by.?one|여섯", "topk_cli": r"\b10\b|argparse|명령행|command.?line|CLI|--top-k",
    "split_hardcoded": r"\btest\b", "questions_offbyone": r"\b999\b|- ?1\b|하나 (적|빠|모자)|off.?by.?one",
    "log_questions": r"\b500\b", "damping_inverted": r"1 ?- ?(cfg|damping|d\b|0\.85)|0\.15|반대|뒤집|invert|complement|보수",
    "contain_swapped": r"순서|뒤바|바뀌|swap|revers|반대로|인자|argument|자리", "medical_case": r"대소문자|대문자|소문자|case|\"Medical\"",
    "judge_model": r"gpt-4o(?!-mini)", "embedding_env": r"MiniLM|환경 ?변수|environ|EMBEDDING_MODEL",
    "seed_unused": r"(random\.seed|난수|랜덤 ?시드|random seed|seed: ?42|시드 ?42|시드 값).{0,60}(않|없|안 ?(쓰|씀|됨)|빠|unused|never)|seed (is )?(never )?(unused|not used|not applied)",  # the random seed, not "seed entities"
    "lambda_comment": r"\b0\.5\b",
}


def conditions() -> dict:
    return json.load(open(CONDITIONS, encoding="utf-8"))


def plant(folder: str, drift: dict) -> int | None:
    """Apply one drift in place -> the 1-based line its mark is on now (None when the drift removes code)."""
    path = os.path.join(folder, drift["file"])
    text = open(path, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in text else "\n"  # a Windows checkout (core.autocrlf) has CRLF; the edits are written with \n
    for old, new in drift["edits"]:
        old, new = old.replace("\n", nl), new.replace("\n", nl)
        if text.count(old) != 1:
            raise ValueError(f"{drift['id']}: {old!r} occurs {text.count(old)} times in {drift['file']}")
        text = text.replace(old, new)
    open(path, "w", encoding="utf-8", newline="").write(text)
    if drift["mark"] is None:
        return None
    for n, line in enumerate(text.splitlines(), 1):
        if marked(line, drift["mark"]):
            return n
    raise ValueError(f"{drift['id']}: mark {drift['mark']!r} not found after the edit")


def marked(line: str, mark: str) -> bool:
    """A mark ending in a newline is the whole line; one starting with spaces starts the line at exactly that indent;
    any other mark is anywhere in the line."""
    if mark.endswith("\n"):
        return line == mark[:-1]
    if mark.startswith(" "):
        return line.startswith(mark)
    return mark in line


def assign(n: int, seed: int, catalog: list[dict] | None = None) -> list[list[dict]]:
    """Deal the catalog into n variants of 1-3 drifts; never two drifts on one condition or one code region."""
    rng = random.Random(seed)
    pool = (catalog or CATALOG)[:]
    rng.shuffle(pool)
    ok = lambda d, x: (x["key"] != d["key"] and x["region"] != d["region"]  # noqa: E731
                       and d["key"] not in x.get("affects", []) and x["key"] not in d.get("affects", []))
    out: list[list[dict]] = [[] for _ in range(n)]
    for d in pool:  # each drift once, into the emptiest variant it fits (so variants hold 1-3)
        fits = [v for v in out if len(v) < 3 and all(ok(d, x) for x in v)]
        if fits:
            min(fits, key=len).append(d)
    return [v for v in out if v]


def variants(out_dir: str, n: int = 8, seed: int = 7, clean: int = 1, set: str = "base") -> dict:
    """set: which catalog the drifts come from (SETS: base, the one the audit prompt was revised on; hard, held out)."""
    os.makedirs(out_dir, exist_ok=True)
    base = {c["key"]: c.get("base", "followed") for c in conditions()["conditions"]}  # a method step the base only sketches
    keys = list(base)
    truth = {"seed": seed, "n": n, "clean": clean, "set": set, "variants": []}
    plans = [[] for _ in range(clean)] + assign(n, seed, SETS[set])
    for i, drifts in enumerate(plans):
        name = f"v{i:02d}" + ("-clean" if not drifts else "")
        folder = os.path.join(out_dir, name)
        shutil.rmtree(folder, ignore_errors=True)
        shutil.copytree(BASE, folder)
        planted = [{"id": d["id"], "key": d["key"], "file": d["file"], "line": plant(folder, d), "expect": d["expect"]}
                   for d in drifts]
        for p, d in zip(planted, drifts):  # a later drift may add or remove lines above an earlier one in the same file
            if d["mark"]:
                lines = open(os.path.join(folder, d["file"]), encoding="utf-8").read().splitlines()
                p["line"] = next(n for n, x in enumerate(lines, 1) if marked(x, d["mark"]))
        moot = {k for d in drifts for k in d.get("affects", [])}
        sets = {k: st for d in drifts for k, st in d.get("sets", {}).items()}
        expect = {k: next((p["expect"] for p in planted if p["key"] == k), sets.get(k, "ambiguous" if k in moot else base[k]))
                  for k in keys}
        expect.update({k: next((p["expect"] for p in planted if p["key"] == k), e) for k, e in OPEN_EXPECT.items()})
        truth["variants"].append({"name": name, "dir": os.path.abspath(folder), "planted": planted, "expect": expect})
    json.dump(truth, open(os.path.join(out_dir, "truth.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return truth


def state(out_dir: str) -> dict:
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from pablo_v2.intent.engine import IntentEngine
    from pablo_v2.skill.skill import PabloSkill
    from pablo_v2.skill.viewer import render_html
    spec = conditions()
    os.makedirs(out_dir, exist_ok=True)
    s = PabloSkill(IntentEngine.load(os.path.join(out_dir, "intent.json")), path=os.path.join(out_dir, "skill.json"))
    src = s.capture_pdf(os.path.abspath(os.path.join(ROOT, spec["pdf"])))
    t = s.start_task("LinearRAG 재현 (점검 벤치마크)", checks=[])
    keys = {}
    for c in spec["conditions"]:
        a = s.add_anchor(src.id, c["quote"], page=c["page"])
        sc = s.add_check(t.id, c["statement"], "USEFUL")
        sc.spec = {"category": c["category"], "value": c["value"], "source_id": src.id, "key": c["key"]}
        s.complete_check(sc.id, "VERIFIED", c["statement"] + " [1]",
                         [{"tier": 4, "type": "pdf", "title": src.title, "url": src.locator, "supports": [a.id]}])
        s.link_evidence(a.id, sc.id, "supports", c["category"])
        keys[c["key"]] = sc.id
    for c in spec["open"]:
        sc = s.add_check(t.id, c["statement"], "USEFUL", "논문에 없는 설정")
        sc.spec = {"category": c["category"], "value": "", "source_id": src.id, "missing": True, "key": c["key"]}
        keys[c["key"]] = sc.id
    s.save()
    view = os.path.join(out_dir, f"view-{t.id}.html")
    open(view, "w", encoding="utf-8").write(render_html(s, t.id))
    json.dump(keys, open(os.path.join(out_dir, "keys.json"), "w", encoding="utf-8"), indent=1)
    return {"view": os.path.abspath(view), "task": t.id, "source": src.id, "keys": keys}


# ---- scoring ----------------------------------------------------------------------------------------------------
def where(raw: str) -> tuple[str, int | None, int | None]:
    """'config.yaml:10-11' / 'logs\\a.log:1' / 'x.py#L5' / 'x.py' -> (path with /, first line, last line)."""
    raw = (raw or "").strip().strip("`").replace("\\", "/")
    m = re.match(r"^(.*?)(?::(\d+)(?:-(\d+))?|#L(\d+)(?:-L?(\d+))?)?$", raw)
    path, a, b = m.group(1), m.group(2) or m.group(4), m.group(3) or m.group(5)
    return path, int(a) if a else None, int(b) if b else (int(a) if a else None)


def located(item: dict, planted: dict) -> tuple[bool, bool | None]:
    """(right file, right line) for a detected drift; line is None when the drift removed code (file only). A where that
    names several places ("config.yaml:7; run.py:19") is right when one of them is."""
    places = [p for p in locs(item.get("where", "")) if p[0].lower().endswith(planted["file"].lower())]
    if planted["line"] is None:
        return bool(places), None
    return bool(places), any(a is not None and a - 1 <= planted["line"] <= (b or a) + 1 for _, a, b in places)


def score(results: list[dict], truth: dict, keys: dict) -> dict:
    by_check = {v: k for k, v in keys.items()}
    rows, per_drift, alarms = [], {}, {}
    inj = dict(n=0, detected=0, exact=0, file=0, line=0, line_n=0, missed_as={})
    fol = dict(n=0, followed=0, false_alarm=0, unclear=0, other=0)
    opn = dict(n=0, exact=0)
    # method steps, apart from the value conditions: a gap the base (or a drift) has, and a step the code does follow
    meth = dict(gap=0, found=0, missed_as={}, ok=0, false_alarm=0, unclear=0, per={})
    for v in truth["variants"]:
        r = next((x for x in results if x["variant"] == v["name"]), None)
        got = {by_check.get(i["id"]): i for i in (r or {}).get("items", []) if by_check.get(i["id"])}
        row = {"variant": v["name"], "planted": [p["id"] for p in v["planted"]], "found": [], "missed": [], "false": [],
               "ms": (r or {}).get("ms"), "error": (r or {}).get("error")}
        for p in v["planted"]:
            it = got.get(p["key"]) or {}
            st = it.get("status", "absent")
            inj["n"] += 1
            d = per_drift.setdefault(p["id"], dict(n=0, detected=0, exact=0, file=0, line=0))
            d["n"] += 1
            if st in DETECTED:
                inj["detected"] += 1; d["detected"] += 1
                f, ln = located(it, p)
                inj["file"] += f; d["file"] += f
                if ln is not None:
                    inj["line_n"] += 1; inj["line"] += ln; d["line"] += ln
                row["found"].append(p["id"])
            else:  # missed: what the audit said instead (followed / unclear / chosen / absent)
                inj["missed_as"][st] = inj["missed_as"].get(st, 0) + 1
                row["missed"].append(f"{p['id']}({st})")
            if st == p["expect"]:
                inj["exact"] += 1; d["exact"] += 1
        for k, exp in v["expect"].items():
            if k in OPEN_EXPECT:
                opn["n"] += 1
                opn["exact"] += (got.get(k) or {}).get("status") == exp
                continue
            if k in METHOD():
                st = (got.get(k) or {}).get("status", "absent")
                p = meth["per"].setdefault(k, dict(gap=0, found=0, ok=0, false_alarm=0))
                if exp in DETECTED:
                    meth["gap"] += 1; p["gap"] += 1
                    if st in DETECTED:
                        meth["found"] += 1; p["found"] += 1
                    else:
                        meth["missed_as"][st] = meth["missed_as"].get(st, 0) + 1
                elif exp == "followed":
                    meth["ok"] += 1; p["ok"] += 1
                    meth["false_alarm"] += st in DETECTED; p["false_alarm"] += st in DETECTED
                    meth["unclear"] += st == "unclear"
                    if st in DETECTED:
                        row["false"].append(f"{k}({st})")
                continue
            if exp != "followed":
                continue
            st = (got.get(k) or {}).get("status", "absent")
            fol["n"] += 1
            if st == "followed":
                fol["followed"] += 1
            elif st in DETECTED:
                fol["false_alarm"] += 1
                alarms[k] = alarms.get(k, 0) + 1
                row["false"].append(f"{k}({st})")
            elif st == "unclear":
                fol["unclear"] += 1
            else:
                fol["other"] += 1
        rows.append(row)
    pct = lambda a, b: round(100 * a / b, 1) if b else None  # noqa: E731
    summary = {
        "recall": pct(inj["detected"], inj["n"]), "exact_status": pct(inj["exact"], inj["n"]),
        "false_alarm_rate": pct(fol["false_alarm"], fol["n"]), "followed_confirmed": pct(fol["followed"], fol["n"]),
        "unclear_on_followed": pct(fol["unclear"], fol["n"]), "file_accuracy": pct(inj["file"], inj["detected"]),
        "line_accuracy": pct(inj["line"], inj["line_n"]), "open_chosen": pct(opn["exact"], opn["n"]),
        "planted": inj["n"], "followed_items": fol["n"], "variants": len(truth["variants"]),
        "method_recall": pct(meth["found"], meth["gap"]), "method_false_alarm_rate": pct(meth["false_alarm"], meth["ok"]),
    }
    return {"summary": summary, "planted": inj, "followed": fol, "open": opn, "method": meth, "per_drift": per_drift,
            "false_alarms": alarms, "rows": rows, "verify": tally(results, truth, keys)}


def METHOD() -> set[str]:
    """The method steps (spec category method): judged by what the code does, scored apart from the value conditions."""
    return {c["key"] for c in conditions()["conditions"] if c["category"] == "method"}


def tally(results: list[dict], truth: dict, keys: dict) -> dict:
    """Pablo's own check of each answer (0.8 Phase A, desktop/where.js verify): on the drifts found, on followed items,
    and on the method steps (any verdict: a place the model names for a step is checked the same way)."""
    by_check, method = {v: k for k, v in keys.items()}, METHOD()
    out = {"drift": {}, "followed": {}, "method": {}}
    for v in truth["variants"]:
        r = next((x for x in results if x["variant"] == v["name"]), None) or {}
        got = {by_check.get(i["id"]): i for i in r.get("items", []) if by_check.get(i["id"])}
        for k, exp in v["expect"].items():
            it = got.get(k)
            if not it or "check" not in it:
                continue
            side = "method" if k in method else "drift" if exp in DETECTED and it.get("status") in DETECTED \
                else "followed" if exp == "followed" == it.get("status") else None
            if side:
                out[side][it["check"]] = out[side].get(it["check"], 0) + 1
    return out


_VERIFY = """const w = require(process.argv[1]);
const calls = JSON.parse(require("fs").readFileSync(0, "utf8"));
console.log(JSON.stringify(calls.map(([work, item, value]) => w.verify(work, item, value))));"""


def recheck(results: list[dict], truth: dict, keys: dict, n: int | None = None, shift: int = 0) -> list[dict] | None:
    """The answers with Pablo's check recomputed by desktop/where.js as it is now, on the variants regenerated from the
    seed (the saved check followed the rule of the day the answers came). shift: each answer checked in another
    variant's folder, a control for what the check makes of a claim about a folder it was not made in.
    None without node or where.js."""
    if not shutil.which("node") or not os.path.exists(WHERE_JS):
        return None
    clean = truth.get("clean", sum(v["name"].endswith("-clean") for v in truth["variants"]))
    n = truth.get("n", n)
    value = {c["key"]: c["value"] for c in conditions()["conditions"]}
    by_check = {v: k for k, v in keys.items()}
    out = json.loads(json.dumps(results))
    with tempfile.TemporaryDirectory() as d:
        vs = variants(d, n=n, seed=truth["seed"], clean=clean, set=truth.get("set", "base"))["variants"]
        same = lambda t: [[(p["id"], p["line"]) for p in v["planted"]] for v in t]  # noqa: E731
        assert same(vs) == same(truth["variants"]), "the variants do not regenerate from this truth's seed"
        calls, items = [], []
        for i, v in enumerate(vs):
            r = next((x for x in out if x["variant"] == v["name"]), None)
            for it in (r or {}).get("items", []):
                calls.append([vs[(i + shift) % len(vs)]["dir"], it, value.get(by_check.get(it["id"]))])
                items.append(it)
        p = subprocess.run(["node", "-e", _VERIFY, WHERE_JS], input=json.dumps(calls), capture_output=True, encoding="utf-8")
        if p.returncode:
            raise RuntimeError(p.stderr[-800:])
    for it, c in zip(items, json.loads(p.stdout)):
        it.pop("line_found", None)
        it.update(c)
    return out


# ---- comparison group: the same model, asked plainly (no condition list, no anchors, no status scheme) -------------
BASELINE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items", "summary"],
    "properties": {
        "summary": {"type": "string"},
        "items": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["what", "where", "paper", "code"],
            "properties": {"what": {"type": "string"}, "where": {"type": "string"}, "paper": {"type": "string"},
                           "code": {"type": "string"}}}}}}


def baseline_prompt() -> str:
    """What a researcher would do with a general coding agent: paste the paper, ask where the repo departs from it."""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from pablo_v2.skill import pdf
    pages = pdf.pages(open(os.path.join(ROOT, conditions()["pdf"]), "rb").read())
    paper = "\n\n".join(f"[p.{n}] {p}" for n, p in enumerate(pages, 1))
    return ("이 작업 폴더는 아래 논문의 실험을 재현하려는 코드입니다. 코드, 설정 파일, 실행 로그를 읽고 논문에 적힌 실험 조건과 "
            "다르게 구현되었거나 빠진 곳을 모두 찾아 주세요. 파일을 고치거나 프로그램을 실행하지 말고 읽기만 하세요. "
            "항목마다 what(무엇이 다른가), where(파일:줄), paper(논문이 말하는 것), code(코드가 하는 것)를 적고, "
            "다른 곳이 없으면 빈 목록을 주세요.\n\n[논문 본문]\n" + paper)


_LOC = re.compile(r"([\w./\\-]+\.(?:py|ya?ml|log|json|txt|md))(?:\s*(?::|#L|\s|line\s*)\s*(\d+)(?:\s*[-–]\s*L?(\d+))?)?", re.I)


def locs(raw: str) -> list[tuple[str, int | None, int | None]]:
    """Every file[:line[-line]] in a free-form location ("config.yaml:5 (top_k)", "a.py:6,15", "a.py line 3")."""
    raw = (raw or "").replace("\\", "/")
    ms, out = list(_LOC.finditer(raw)), []
    for m, nxt in zip(ms, ms[1:] + [None]):
        a = int(m.group(2)) if m.group(2) else None
        out.append((m.group(1), a, int(m.group(3)) if m.group(3) else a))
        more = re.match(r"(?:\s*,\s*\d+(?:\s*[-–]\s*\d+)?)+", raw[m.end():nxt.start() if nxt else len(raw)]) if a else None
        for x, y in re.findall(r"(\d+)(?:\s*[-–]\s*(\d+))?", more.group(0) if more else ""):  # "a.py:6,15": same file
            out.append((m.group(1), int(x), int(y or x)))
    return out


def hits(loc: tuple, planted: dict) -> bool:
    """One location against one planted drift: its file, and its line +-2 (a drift that deletes code: the file).
    A span over 10 lines names a region, not the drift's line."""
    path, a, b = loc
    if not path.lower().endswith(planted["file"].lower().split("/")[-1]):
        return False
    return planted["line"] is None or (a is not None and (b or a) - a <= 10 and a - 2 <= planted["line"] <= (b or a) + 2)


# the method-level gaps of repro_base the comparison group named (docs/eval/README.md): it follows every value and only
# sketches the method. A regex over what a report says (not its code quote), per theme; ASCII \b like SAYS.
THEMES = {
    "hybrid passage 초기화 없음": r"hybrid|하이브리드|초기화|initiali[sz]",
    "그래프 구조(희소 행렬·passage-sentence 간선)": r"passage.?sentence|패시지.?문장|sparse|희소|NetworkX|인접 ?행렬|adjacency",
    "δ를 임계값이 아니라 hop 수로": r"hop|홉|순회 횟수|확장 횟수|반복 횟수|(delta|δ)\S{0,3} ?(횟수|만큼)|고정 반복",
    "LLM에 passage 본문 대신 ID": r"\bID\b|본문 대신|원문 대신|text 속성|본문이 (없|저장)",
    "의미 기반 entity 활성화 없음": r"semantic (bridging|propagation)|의미 기반|활성화 점수|activation score|질문-문장|query-sentence|문장 유사도|전파",
    "질의 entity를 유사 entity에 매칭하지 않음": r"ex\[.entities.\]|가장 유사한|nearest|유사(한)? ?(entity|엔티티)|(entity|엔티티) ?매칭|matching",
    "임베딩 모델을 쓰지 않음": r"(encoder|SentenceTransformer|임베딩|embedding).{0,40}(쓰지 않|사용하지 않|사용되지 않|쓰이지 않|unused|never|호출.{0,4}않)|encode.{0,10}(없|않)",
    "생성 프롬프트": r"프롬프트|prompt",
}


def said(run: dict) -> list[str]:
    """What a run says differs, as text: its reports' what / code prose / note (not the quoted code), outside the items too."""
    rep = [i for i in run.get("items", []) if i.get("status", "differs") in DETECTED]
    return [" ".join(str(i.get(f, "")) for f in ("what", "code", "note")) for i in rep] + \
           [str(o.get("what", "")) for o in run.get("outside", [])]


def themes(runs: list[dict], truth: dict) -> dict:
    """{theme: variants whose run names it}: the base has every one of these gaps in every variant."""
    out = {t: [] for t in THEMES}
    for v in truth["variants"]:
        text = " ".join(said(next((x for x in runs if x["variant"] == v["name"]), None) or {}))
        for t, rx in THEMES.items():
            if re.search(rx, text, re.I | re.A):
                out[t].append(v["name"])
    return out


def about(report: dict, planted: dict) -> bool:
    # what it says the code does (not "paper": the paper's side may name the same thing for another reason)
    text = " ".join(str(report.get(f, "")) for f in ("what", "code", "found", "note"))
    return bool(re.search(SAYS[planted["id"]], text, re.I | re.A))  # ASCII \b: "delta=2를" ends a word at 2


def compare(systems: dict, truth: dict) -> dict:
    """systems: {name: runs}; a run's reports = its items that claim a departure (Pablo: differs/missing; plain: all).
    A planted drift is found when a location in a report points at its file and line and the report says what changed
    there (SAYS); each location finds at most one drift (a report may list several places). found_loc: by location
    alone. A report about no planted drift is outside the benchmark: often a true gap the conditions do not cover
    (e.g. baselines not run), so they are kept for reading (one more word on a found drift is not one of them).
    Pablo's outside list (what no condition covers) is read like reports. themes: of the base's method-level gaps
    (THEMES), in how many variants a system names each."""
    out = {}
    for name, runs in systems.items():
        found = found_loc = planted_n = clean_extra = reports = 0
        ms, extras, missed = [], [], []
        for v in truth["variants"]:
            r = next((x for x in runs if x["variant"] == v["name"]), None) or {}
            rep = [i for i in r.get("items", []) if i.get("status", "differs") in DETECTED] + \
                [{"what": o.get("what", ""), "where": o.get("where", ""), "found": o.get("found", "")} for o in r.get("outside", [])]
            reports += len(rep)
            ms.append(r.get("ms") or 0)
            places = [(j, loc) for j, i in enumerate(rep) for loc in locs(i.get("where", ""))]
            for strict in (True, False):
                used = set()
                for p in sorted(v["planted"], key=lambda p: p["line"] is None):  # a line before a whole file
                    k = next((k for k, (j, loc) in enumerate(places)
                              if k not in used and hits(loc, p) and (not strict or about(rep[j], p))), None)
                    if k is not None:
                        used.add(k)
                    elif strict:
                        missed.append(f"{v['name']} {p['id']}")
                found += strict * len(used); found_loc += (not strict) * len(used)
            planted_n += len(v["planted"])
            near = {j for j, loc in places if any(hits(loc, p) and about(rep[j], p) for p in v["planted"])}
            for j, i in enumerate(rep):
                if j not in near:
                    extras.append({"variant": v["name"], "where": i.get("where", ""),
                                   "what": i.get("what") or i.get("note") or i.get("found") or ""})
            if not v["planted"]:
                clean_extra += len(rep)
        out[name] = {"recall": round(100 * found / planted_n, 1) if planted_n else None, "found": found,
                     "found_loc": found_loc, "planted": planted_n, "missed": missed, "reports": reports,
                     "extra": len(extras), "extra_per_variant": round(len(extras) / len(truth["variants"]), 1),
                     "clean_extra": clean_extra, "avg_ms": round(sum(ms) / len(ms)) if ms else None, "extras": extras,
                     "themes": {t: len(vs) for t, vs in themes(runs, truth).items()}}
    return out


def markdown_compare(c: dict, meta: dict) -> str:
    rows = ["# 비교군: Pablo 재현 점검 vs 같은 모델에 그냥 묻기 — " + meta.get("date", ""), "",
            f"- 같은 변형 {meta.get('variants')}개(씨앗 {meta.get('seed')}), 같은 모델 {meta.get('model')}, 둘 다 읽기 전용 + JSON 답",
            "- Pablo: 고정 조건 17개 + 원문 쪽을 받고 조건마다 판정. 그냥 묻기: 논문 본문 전체를 받고 \"논문과 다른 곳을 모두 찾아줘\"",
            "- 찾음 = 심은 어긋남의 파일:줄(±2)을 짚고 무엇이 바뀌었는지 말함(`SAYS`). 위치만 = 줄만 맞음",
            "- 심은 것 밖의 보고 = 어느 심은 어긋남에 대한 것도 아닌 보고. 틀린 말이라는 뜻이 아니다: 조건 목록 밖의 실제 차이일 수 있다", "",
            "| 시스템 | 찾음 | 위치만 | 보고 수 | 심은 것 밖의 보고 | 변형당 | 깨끗한 변형의 보고 | 1회 시간 |",
            "|---|---|---|---|---|---|---|---|"]
    for name, s in c.items():
        rows.append(f"| {name} | {s['found']}/{s['planted']} ({s['recall']}%) | {s['found_loc']}/{s['planted']} | "
                    f"{s['reports']} | {s['extra']} | {s['extra_per_variant']} | {s['clean_extra']} | {s['avg_ms']} ms |")
    n = meta.get("variants")
    rows += ["", f"## 방법 수준 차이: 바탕 폴더가 가진 {len(THEMES)}가지를 변형 {n}개에서 몇 번 짚었나", "",
             "보고가 하는 말(코드 인용은 빼고)에 주제별 표현(`THEMES`)이 나오면 짚은 것으로 셉니다.", "",
             "| 주제 | " + " | ".join(c) + " |", "|---|" + "---|" * len(c)]
    for t in THEMES:
        rows.append(f"| {t} | " + " | ".join(f"{s['themes'][t]}/{n}" for s in c.values()) + " |")
    rows.append("| 합 | " + " | ".join(f"{sum(s['themes'].values())}/{n * len(THEMES)}" for s in c.values()) + " |")
    for name, s in c.items():
        rows += ["", f"## {name}: 놓친 어긋남 {len(s['missed'])}건", ""] + ([f"- {m}" for m in s["missed"]] or ["- 없음"])
    for name, s in c.items():  # for reading: a true gap outside the benchmark, or noise
        rows += ["", f"## {name}: 심은 것 밖의 보고 {s['extra']}건", ""]
        rows += [f"- {e['variant']} `{e['where']}`: {' '.join(e['what'].split())[:160]}" for e in s["extras"]] or ["- 없음"]
    return "\n".join(rows) + "\n"


def markdown(s: dict, meta: dict) -> str:
    m = s["summary"]
    out = [f"# 재현 점검 벤치마크 — {meta.get('date', '')}", "",
           f"- 변형 {m['variants']}개 (씨앗 {meta.get('seed')}, 깨끗한 변형 포함), 심은 어긋남 {m['planted']}개, "
           f"채점한 '따름' 조건 {m['followed_items']}개",
           f"- 모델: {meta.get('model', '?')}, 점검 1회 평균 {meta.get('avg_ms', '?')} ms", "",
           "| 지표 | 값 | 뜻 |", "|---|---|---|",
           f"| 탐지율 | {m['recall']}% ({s['planted']['detected']}/{s['planted']['n']}) | 심은 어긋남을 다름·없음으로 짚은 비율 |",
           f"| 판정 정확도 | {m['exact_status']}% | 심은 어긋남의 상태(다름/없음)까지 맞힌 비율 |",
           f"| 오탐률 | {m['false_alarm_rate']}% ({s['followed']['false_alarm']}/{s['followed']['n']}) | 따르는 조건을 다름·없음으로 짚은 비율 |",
           f"| 따름 확인 | {m['followed_confirmed']}% | 따르는 조건을 '따름'으로 본 비율 |",
           f"| 판단 보류 | {m['unclear_on_followed']}% | 따르는 조건을 '판단 못 함'으로 둔 비율 |",
           f"| 위치(파일) | {m['file_accuracy']}% | 짚은 어긋남 중 파일이 맞은 비율 |",
           f"| 위치(줄 ±1) | {m['line_accuracy']}% | 짚은 어긋남 중 줄까지 맞은 비율 (코드를 지운 어긋남 제외) |",
           f"| 논문에 없는 설정 | {m['open_chosen']}% | 시드를 '코드가 정함'으로 본 비율 |", "",
           "## 어긋남별", "", "| 어긋남 | 심은 수 | 탐지 | 상태 일치 | 파일 | 줄 |", "|---|---|---|---|---|---|"]
    for k, d in sorted(s["per_drift"].items()):
        out.append(f"| {k} | {d['n']} | {d['detected']} | {d['exact']} | {d['file']} | {d['line']} |")
    mt = s.get("method") or {}
    if mt.get("gap") or mt.get("ok"):
        said = {c["key"]: c["statement"] for c in conditions()["conditions"]}
        out += ["", "## 방법 조건 (값이 아니라 코드가 하는 일)", "",
                f"- 바탕 폴더(또는 어긋남)가 논문과 다르게 하는 단계: {mt['found']}/{mt['gap']} 짚음 ({m['method_recall']}%)"
                + (f", 놓친 판정 {mt['missed_as']}" if mt["missed_as"] else ""),
                f"- 논문대로 하는 단계를 다르다고 함: {mt['false_alarm']}/{mt['ok']} ({m['method_false_alarm_rate']}%), "
                f"판단 못 함 {mt['unclear']}", "",
                "| 조건 | 다른 단계 짚음 | 따르는 단계 오탐 |", "|---|---|---|"]
        for k, d in mt["per"].items():
            out.append(f"| {said.get(k, k)} | {d['found']}/{d['gap']} | {d['false_alarm']}/{d['ok']} |")
    if s["verify"]["drift"] or s["verify"]["followed"]:
        fmt = lambda d: ", ".join(f"{k} {n}" for k, n in sorted(d.items(), key=lambda x: -x[1])) or "-"  # noqa: E731
        out += ["", "## Pablo 확인 (점검 답의 파일:줄을 Pablo가 직접 읽은 결과)", "",
                f"- 규칙: {s['verify'].get('rule', '답을 받을 때 저장한 값')}",
                f"- 짚은 어긋남: {fmt(s['verify']['drift'])}",
                f"- 따르는 조건: {fmt(s['verify']['followed'])} (verified 외에는 Pablo 쪽의 거짓 경고)"]
        if s["verify"].get("method"):
            out.append(f"- 방법 조건(판정 무관): {fmt(s['verify']['method'])}")
        if s["verify"].get("control"):
            out.append(f"- 대조 (각 답을 다음 변형의 폴더에서 확인): 짚은 어긋남 {fmt(s['verify']['control'])}. "
                       "verified 외에는 옛 폴더·지어낸 위치를 잡은 것")
    out += ["", "## 오탐 (따르는데 다름·없음으로 짚은 조건)", ""]
    out += [f"- {k}: {n}회" for k, n in sorted(s["false_alarms"].items(), key=lambda x: -x[1])] or ["- 없음"]
    out += ["", "## 변형별", "", "| 변형 | 심은 것 | 찾음 | 놓침 | 오탐 |", "|---|---|---|---|---|"]
    for r in s["rows"]:
        out.append(f"| {r['variant']} | {', '.join(r['planted']) or '-'} | {', '.join(r['found']) or '-'} | "
                   f"{', '.join(r['missed']) or '-'} | {', '.join(r['false']) or '-'}{' ⚠ ' + r['error'] if r.get('error') else ''} |")
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> None:
    cmd = argv[0]
    opt = lambda name, d: argv[argv.index(name) + 1] if name in argv else d  # noqa: E731
    if cmd == "state":
        print(json.dumps(state(argv[1]), ensure_ascii=False))
    elif cmd == "variants":
        t = variants(argv[1], int(opt("--n", 8)), int(opt("--seed", 7)), int(opt("--clean", 1)), opt("--set", "base"))
        print(json.dumps({"truth": os.path.join(os.path.abspath(argv[1]), "truth.json"),
                          "variants": [{"name": v["name"], "dir": v["dir"]} for v in t["variants"]]}, ensure_ascii=False))
    elif cmd == "score":
        results = json.load(open(argv[1], encoding="utf-8"))
        truth = json.load(open(argv[2], encoding="utf-8"))
        keys = json.load(open(argv[3], encoding="utf-8"))
        n = results.get("meta", {}).get("n")
        runs = None if "--saved-checks" in argv else recheck(results["runs"], truth, keys, n)
        s = score(runs or results["runs"], truth, keys)
        if runs:
            s["verify"]["rule"] = "desktop/where.js로 다시 계산 (변형을 씨앗에서 다시 만들어)"
            s["verify"]["control"] = tally(recheck(results["runs"], truth, keys, n, shift=1), truth, keys)["drift"]
        md = markdown(s, {**results.get("meta", {}), "seed": truth.get("seed")})
        prefix = opt("--out", None)
        if prefix:
            open(prefix + ".md", "w", encoding="utf-8").write(md)
            json.dump({"meta": results.get("meta", {}), **s}, open(prefix + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        sys.stdout.reconfigure(encoding="utf-8")
        print(md)
    elif cmd == "baseline-prompt":
        print(json.dumps({"prompt": baseline_prompt(), "schema": BASELINE_SCHEMA}, ensure_ascii=False))
    elif cmd == "compare":  # compare <pablo results> <plain results> <truth> | <truth> <label>=<results>... [--out prefix]
        args = [a for a in argv[1:] if a != "--out" and a != opt("--out", None)]
        if any("=" in a for a in args):  # labelled: as many systems as given, in order
            truth = json.load(open(args[0], encoding="utf-8"))
            runs = {a.split("=", 1)[0]: json.load(open(a.split("=", 1)[1], encoding="utf-8")) for a in args[1:]}
        else:
            truth = json.load(open(args[2], encoding="utf-8"))
            runs = {"Pablo 재현 점검": json.load(open(args[0], encoding="utf-8")),
                    "그냥 묻기": json.load(open(args[1], encoding="utf-8"))}
        c = compare({k: r["runs"] for k, r in runs.items()}, truth)
        last = list(runs.values())[-1]
        md = markdown_compare(c, {**last.get("meta", {}), "seed": truth.get("seed"), "variants": len(truth["variants"])})
        prefix = opt("--out", None)
        if prefix:
            open(prefix + ".md", "w", encoding="utf-8").write(md)
            json.dump(c, open(prefix + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        sys.stdout.reconfigure(encoding="utf-8")
        print(md)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
