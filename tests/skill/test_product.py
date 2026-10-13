"""Product-polish tests (chat log, ...). Run: python tests/skill/test_product.py
Stub judges only; no network.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "..", "src")
sys.path.insert(0, SRC)
sys.path.insert(0, HERE)

from pablo_v2.__main__ import current_step  # noqa: E402
from pablo_v2.intent.engine import IntentEngine  # noqa: E402
from pablo_v2.skill.models import ActionProposal, ExecutionRecord, PostReview  # noqa: E402
from pablo_v2.skill.skill import AUDIT_SCHEMA, PabloSkill, checkable, has_value, render_audit, render_brief  # noqa: E402
from pablo_v2.skill.viewer import model, workspace  # noqa: E402
import ui_fixture  # noqa: E402

PDF = os.path.join(HERE, "..", "..", "LinearRAG.pdf")


def load(d):
    return PabloSkill.load(os.path.join(d, "skill.json"), IntentEngine.load(os.path.join(d, "intent.json")))


def test_chat_log():
    """The desktop's chat.json reaches the view model per task; its PDF answer keeps the check that answered it."""
    with tempfile.TemporaryDirectory() as d:
        ui_fixture.build(d)
        v = model(load(d), "T1")
        assert [c["role"] for c in v["chat"]] == ["user", "intent", "agent", "user", "agent", "ask", "spec", "audit"]
        assert v["chat"][4]["status"] == "interrupted" and v["chat"][5]["check"] in v["checks"]
        assert [a["at"] for a in v["actions"]] == [ui_fixture.at(20), ui_fixture.at(40)]
        with open(os.path.join(d, "chat.json"), "w", encoding="utf-8") as f:
            f.write("{broken")  # a damaged log costs the conversation, never the records
        assert model(load(d), "T1")["chat"] == [] and workspace(load(d))["views"]["T1"]["actions"]
        json.dump(["not", "a", "map"], open(os.path.join(d, "chat.json"), "w", encoding="utf-8"))
        assert model(load(d), "T1")["chat"] == []


def test_brief():
    """What the desktop agent is told: the task's criteria + located facts with their page, and the basis ids."""
    s = PabloSkill(IntentEngine(), None)
    t = s.start_task("LinearRAG 재현", [])
    assert render_brief(s, t.id) == ("", [])  # nothing to tell -> nothing is sent
    s.intent.process_message("test split은 절대 학습에 쓰지 마.")
    s.intent.process_message("가능하면 PyTorch로 짜줘.")
    if os.path.exists(PDF):  # LinearRAG.pdf is not in the repo (see README)
        from test_pdf import Judge
        s.judge = Judge()
        src = s.capture_pdf(PDF)
        sc, dropped = s.ask(t.id, "LinearRAG가 더 효율적인 근거는?", src.id)
        text, basis = render_brief(s, t.id)
        assert basis == [sc.id] and len(dropped) == 1
        assert "(LinearRAG p.2)" in text and "(LinearRAG p.9)" in text and "[1]" not in text, text
        assert "(일부만 확인됨)" in text  # one quote was not found: PARTIALLY_VERIFIED
    text, _ = render_brief(s, t.id)
    assert "반드시: test split은 절대 학습에 쓰지 마" in text and "가능하면: 가능하면 PyTorch로 짜줘" in text, text


class SpecJudge:  # extract_spec stub on LinearRAG.pdf: two results, a method step on a wrong page, one quote not in the paper
    def extract_spec(self, pages):
        assert len(pages) > 9
        return {"items": [
            {"category": "result", "statement": "LinearRAG의 색인 시간은 249.78초이다", "value": "249.78",
             "quote": "LinearRAG (Ours) 249.78 0.093 0 0 66.95", "page": 9},
            {"category": "result", "statement": "2Wiki에서 GPT 정확도는 63.70%이다", "value": "63.70%",
             "quote": "LinearRAG achieves 63.70% GPT-based accuracy on 2Wiki", "page": 8},
            {"category": "model", "statement": "문서 중요도는 personalized PageRank로 계산한다", "value": "PageRank",
             "quote": "In the second Stage, the model uses personalized PageRank algorithms", "page": 4},
            {"category": "dataset", "statement": "없는 데이터셋", "value": "X", "quote": "a dataset this paper never names", "page": 6}],
            "missing": [{"category": "training", "statement": "난수 시드가 적혀 있지 않다"}]}

    def analyze_action(self, action, justification, step, constraints, checks):
        sc = checks.split()[0]  # the first fact the judge was shown: the 249.78 s result
        return {"intent_conflicts": [], "plan_alignment": {"follows_step": True, "note": ""},
                "justification": {"present": False, "relevant": False, "supported_by": [], "note": ""},
                "source_conflicts": [{"source_check_id": sc, "kind": "contradicts", "note": "보고값을 바꿔 쓴다"}]}


def test_spec():
    """A paper's reproduction conditions: anchored on their page (or dropped), VERIFIED facts the Guard enforces (S01),
    in the agent's brief; what the paper does not state stays open; extracting again replaces the old set."""
    if not os.path.exists(PDF):
        print("skip test_spec: LinearRAG.pdf not here")
        return
    s = PabloSkill(IntentEngine(), SpecJudge())
    t = s.start_task("LinearRAG 재현", [])
    src = s.capture_pdf(PDF)
    stated, missing, dropped = s.spec(t.id, src.id)
    assert [c.spec["category"] for c in stated] == ["result", "result", "model"] and len(dropped) == 1
    pages = [s.evidence_for(c.id)[0][1].selector["page"] for c in stated]
    assert pages == [9, 8, 9]  # the method step's page was wrong: found where it is
    assert all(c.outcome == "VERIFIED" and c.sources[0]["tier"] == 4 for c in stated)
    assert len(missing) == 1 and missing[0].research_state == "pending" and missing[0].spec["missing"]
    text, basis = render_brief(s, t.id)
    assert "[보고된 결과] LinearRAG의 색인 시간은 249.78초이다 (LinearRAG p.9)" in text, text
    assert "근거 없이 바꾸지 마세요" in text and "[학습] 난수 시드가 적혀 있지 않다" in text
    assert basis == [c.id for c in stated]
    act = s.propose_action(t.id, "eval.py에서 색인 시간 249.78을 120으로 고쳐 쓴다")
    assert act.verdict == "BLOCK" and "S01" in [r["rule"] for r in act.reasons]  # against a verified paper condition
    s.spec(t.id, src.id)  # again: the earlier set is replaced, not doubled
    live = [c for c in s.checks(t.id) if c.spec and c.research_state != "waived"]
    assert len(live) == 4 and all(c.id not in {x.id for x in stated + missing} for c in live)
    v = model(s, t.id)
    assert v["checks"][live[0].id]["spec"]["category"] == "result"


class CountingJudge:  # no conflicts; counts model calls
    calls = 0

    def analyze_action(self, *a):
        CountingJudge.calls += 1
        return {"intent_conflicts": [], "source_conflicts": [], "plan_alignment": {"follows_step": True, "note": ""},
                "justification": {"present": False, "relevant": False, "supported_by": [], "note": ""}}


def test_rewrite_and_cache():
    """W01: an edit that removes most of an existing file warns without the model. The same action, step, criteria and
    facts reuse the judge's analysis (no second model call); anything different asks again."""
    s = PabloSkill(IntentEngine(), CountingJudge())
    t = s.start_task("train.py 정리", [])
    s.create_plan(t.id, [{"action": "train.py를 고친다", "basis": []}])
    big = s.propose_action(t.id, "파일 수정: train.py", "P1.1", rewrites=[{"path": "train.py", "lines": 120, "removed": 90}])
    small = s.propose_action(t.id, "파일 수정: train.py (작게)", "P1.1", rewrites=[{"path": "train.py", "lines": 120, "removed": 10}])
    tiny = s.propose_action(t.id, "파일 수정: a.py", "P1.1", rewrites=[{"path": "a.py", "lines": 12, "removed": 12}])
    assert big.verdict == "WARN" and [r["rule"] for r in big.reasons] == ["W01"] and "90줄" in big.reasons[0]["reason"]
    assert small.verdict == "ALLOW" and tiny.verdict == "ALLOW"  # a small file rewritten whole is not drift
    v = next(a for a in model(s, t.id)["actions"] if a["id"] == big.id)
    assert v["problems"][0].startswith("train.py의 기존 120줄 중 90줄")  # the card says what the rule saw
    n = CountingJudge.calls
    again = s.propose_action(t.id, "명령 실행: Get-Content train.py", "P1.1")
    same = s.propose_action(t.id, "명령 실행: Get-Content train.py", "P1.1")
    assert CountingJudge.calls == n + 1 and same.analysis_from == again.id and same.verdict == again.verdict
    s.intent.process_message("train.py는 절대 지우지 마.")  # the criteria changed: the judge is asked again
    s.propose_action(t.id, "명령 실행: Get-Content train.py", "P1.1")
    assert CountingJudge.calls == n + 2


def test_audit_prompt():
    """재현 점검 asks about every stated condition (with its page), every open setting and every task criterion, by id;
    the answer's shape is a strict schema (status from a fixed set)."""
    with tempfile.TemporaryDirectory() as d:
        ui_fixture.build(d)
        s = load(d)
        prompt, items = render_audit(s, "T1")
        kinds = {x["kind"] for x in items}
        assert kinds == {"condition", "open", "criterion"}, items
        assert [x["label"] for x in items if x["kind"] == "condition"] == ["하이퍼파라미터", "보고된 결과", "모델"]
        assert all(f"{x['id']} | " in prompt for x in items) and "읽기만 하세요" in prompt
        assert {x["id"] for x in items if x["kind"] == "criterion"} == {"C1", "C2"}
        assert AUDIT_SCHEMA["properties"]["items"]["items"]["properties"]["status"]["enum"] ==             ["followed", "differs", "missing", "unclear", "chosen"]
        # the paper's value goes to the desktop with each condition: Pablo checks the verdict against it (desktop/where.js)
        assert [x["value"] for x in items if x["kind"] == "condition"] == ["5", "63.70%", "all-mpnet-base-v2"]


# ---- A1/A2 (0.8): desktop/where.js, run with node on the same tables the Python rule uses ----
WHERE_JS = os.path.join(HERE, "..", "..", "desktop", "where.js")
NODE = """const w = require(process.argv[1]);
const calls = JSON.parse(require("fs").readFileSync(0, "utf8"));
console.log(JSON.stringify(calls.map(([f, ...a]) => { try { return w[f](...a); } catch (e) { return { error: e.code || e.message }; } })));"""


def node(calls):
    r = subprocess.run(["node", "-e", NODE, WHERE_JS], input=json.dumps(calls), capture_output=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout)


def no_node(name):
    if shutil.which("node"):
        return False
    print(f"skip {name}: no node")
    return True


WHERE = [  # what models write for a place in the work folder -> (path, from, to)
    ("config.yaml:5", ("config.yaml", 5, 5)),
    ("config.yaml:10-11", ("config.yaml", 10, 11)),
    ("logs\\2wiki.log:1", ("logs/2wiki.log", 1, 1)),                       # Windows separators
    ("C:\\work\\repro\\config.yaml:5", ("C:/work/repro/config.yaml", 5, 5)),  # absolute (the folder check is read's)
    ("/home/u/repro/config.yaml:5", ("/home/u/repro/config.yaml", 5, 5)),
    ("src/run.py#L5", ("src/run.py", 5, 5)),
    ("src/run.py#L5-L7", ("src/run.py", 5, 7)),
    ("config.yaml", ("config.yaml", None, None)),                           # no line
    ("config.yaml:5:3", ("config.yaml", 5, 5)),                             # line:column
    ("`config.yaml` (line 5)", ("config.yaml", 5, 5)),
    ("config.yaml, lines 10-11", ("config.yaml", 10, 11)),
    ("config.yaml 12행", ("config.yaml", 12, 12)),
    ("./config.yaml:5, run.py:3", ("config.yaml", 5, 5)),                   # several: the first
    ("config.yaml:5 (top_k)", ("config.yaml", 5, 5)),
    ("run notes.txt", ("run notes.txt", None, None)),
    ("preprocess.py:6,15", ("preprocess.py", 6, 6)),                        # several lines (0.8 bench): the first range
    ("evaluate.py:5-6, 18", ("evaluate.py", 5, 6)),
    ("config.yaml:3; run.py:16,25; evaluate.py:11", ("config.yaml", 3, 3)),  # several files: the first
    ("", None), ("없음", None), ("(none)", None), ("코드 전체", None),       # no place
]
VALUES = [  # (text, the paper's value, is it there) — numbers by value, never inside a word
    ("top_k: 10", "5", False), ("top_k: 5", "5", True), ("lr: 0.5", "5", False), ("epochs: 15", "5", False),
    ("questions_per_dataset: 1000", "1,000", True), ("gpt_acc=63.70", "63.70%", True), ("acc 63.7", "63.70%", True),
    ("dataset=2wikimultihopqa", "2", False), ("embedding_model: all-mpnet-base-v2", "2", False),
    ("llm: gpt-4o-mini", "GPT-4o-mini", True), ("uses Personalized  PageRank", "personalized pagerank", True),
    ("lr = 0.0001", "1e-4", True), ("LinearRAG (Ours) 249.78 0.093", "249.78", True), ("split: test", "validation", False),
]
CHECKABLE = [("5", True), ("1,000", True), ("63.70%", True), ("GPT-4o-mini", True), ("all-mpnet-base-v2", True),
             ("Personalized PageRank", False), ("punctuation", False), ("GPT-ACC", False), ("SpaCy", False),  # concepts
             ("HotpotQA; MuSiQue", False), ("entity, sentence, and passage", False),
             ("NVIDIA GeForce RTX 4090 D (24GB VRAM)", False), ("", False)]


def test_where_and_value_rule():
    """where() takes the forms models write; the value rule is the same in Python (spec) and JS (audit)."""
    if no_node("test_where_and_value_rule"):
        return
    got = node([["where", raw] for raw, _ in WHERE])
    assert [None if g is None else (g["path"], g["from"], g["to"]) for g in got] == [w for _, w in WHERE], got
    many = {raw: g for (raw, _), g in zip(WHERE, got) if g and (len(g["ranges"]) > 1 or g["also"])}
    assert {raw: (g["ranges"], [(x["path"], x["ranges"]) for x in g["also"]]) for raw, g in many.items()} == {
        "./config.yaml:5, run.py:3": ([[5, 5]], [("run.py", [[3, 3]])]),
        "preprocess.py:6,15": ([[6, 6], [15, 15]], []), "evaluate.py:5-6, 18": ([[5, 6], [18, 18]], []),
        "config.yaml:3; run.py:16,25; evaluate.py:11": ([[3, 3]], [("run.py", [[16, 16], [25, 25]]), ("evaluate.py", [[11, 11]])])}
    js = node([["hasValue", t, v] for t, v, _ in VALUES] + [["checkable", v] for v, _ in CHECKABLE])
    assert js == [x for *_, x in VALUES] + [x for _, x in CHECKABLE], js
    assert [has_value(t, v) for t, v, _ in VALUES] == [x for *_, x in VALUES]
    assert [checkable(v) for v, _ in CHECKABLE] == [x for _, x in CHECKABLE]


def link_out(link, target):
    """A directory link inside the work folder to one outside it (Windows without privilege: a junction)."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True, check=True)


def test_read_and_verify():
    """read: only text files inside the task's folder (also after links); verify: the six states of the audit check."""
    if no_node("test_read_and_verify"):
        return
    with tempfile.TemporaryDirectory() as d:
        w, out = os.path.join(d, "work"), os.path.join(d, "outside")
        shutil.copytree(ui_fixture.DEMO, w)
        os.makedirs(out)
        open(os.path.join(out, "secret.txt"), "w").write("token\n")
        open(os.path.join(w, "model.bin"), "wb").write(b"\x00\x01weights")
        open(os.path.join(w, "big.log"), "w").write("x" * (1 << 20) + "\n")
        open(os.path.join(w, "long.py"), "w").write("".join(f"line {i}\n" for i in range(1, 6001)))
        link = os.path.join(w, "link")
        link_out(link, out)
        try:
            r = node([["read", w, "config.yaml"], ["read", w, "long.py", 5800], ["read", w, "../outside/secret.txt"],
                      ["read", w, os.path.join(out, "secret.txt")], ["read", w, "link/secret.txt"], ["read", w, "model.bin"],
                      ["read", w, "big.log"], ["read", w, "nope.txt"], ["read", w, "logs"]])
            cfg, long = r[0], r[1]
            assert (cfg["path"], cfg["first"], cfg["total"], cfg["truncated"], cfg["lines"][4]) == ("config.yaml", 1, 12, False, "  top_k: 10")
            assert (long["first"], len(long["lines"]), long["total"], long["truncated"], long["lines"][0]) == (1001, 5000, 6000, True, "line 1001")
            assert [x["error"] for x in r[2:]] == ["outside", "outside", "outside", "binary", "large", "missing", "missing"], r[2:]
            V = lambda status, where, found, value="": ["verify", w, {"status": status, "where": where, "found": found}, value]  # noqa: E731
            got = node([
                V("differs", "config.yaml:5", "top_k: 10", "5"),                                       # verified
                V("followed", "config.yaml:10-11", "split: validation / questions_per_dataset: 1000", "1,000"),
                V("differs", "logs\\2wiki.log:1", "gpt_acc=61.20", "63.70%"),
                V("differs", "logs/2wiki.log:1", "dataset=2wikimultihopqa", "2"),                      # not "2" of 2wiki
                V("followed", "config.yaml:3,12", "llm: gpt-4o-mini; seed: 42"),                       # several lines
                V("followed", "config.yaml:3; run.py:3", "llm: gpt-4o-mini; print('top_k'"),           # several files
                V("followed", "run.py:2", "cfg = yaml.safe_load(open('config.yaml'))", "Personalized PageRank"),  # a concept
                V("chosen", "config.yaml:2", "seed: 42"),                                              # moved
                V("chosen", "config.yaml", "seed: 42"),                                                # no line: where it is
                V("followed", "logs/2wiki.log:3", "gpt_acc=63.70", "63.70%"),                          # not_found
                V("followed", "config.yaml:40", ""),
                V("followed", "missing.py:1", "x"), V("followed", "../outside/secret.txt:1", "token"),  # no_file
                V("followed", "link/secret.txt:1", "token"), V("followed", "missing.py:6,15", "x"),
                V("followed", "config.yaml:5", "top_k: 10", "5"),                                      # value_mismatch
                V("differs", "config.yaml:9", "damping: 0.85", "0.85"),
                V("missing", "", ""), V("followed", "model.bin:1", "weights"), V("followed", "config.yaml:5", "")])  # unchecked
            assert got == [{"check": "verified"}] * 7 + [{"check": "moved", "line_found": 12}, {"check": "verified", "line_found": 12}] + \
                [{"check": "not_found"}] * 2 + [{"check": "no_file"}] * 4 + [{"check": "value_mismatch"}] * 2 + [{"check": "unchecked"}] * 3, got
        finally:
            try:
                os.unlink(link)
            except OSError:
                os.rmdir(link)  # a junction: the link only, never what it points to


def test_audit_fixture_is_what_main_stores():
    """The UI fixture's audit checks are exactly what where.verify gives on its repro folder (no hand-made states)."""
    if no_node("test_audit_fixture_is_what_main_stores"):
        return
    with tempfile.TemporaryDirectory() as d:
        ui_fixture.build(d)
        s = load(d)
        audit = json.load(open(os.path.join(d, "chat.json"), encoding="utf-8"))["T1"][-1]
        values = {c.id: c.spec.get("value", "") for c in s.checks("T1") if c.spec}
        got = node([["verify", os.path.join(d, "repro"), x, values.get(x["id"], "")] for x in audit["items"]])
        assert got == [{k: x[k] for k in ("check", "line_found") if k in x} for x in audit["items"]], got
        assert {x["check"] for x in audit["items"]} == {"unchecked", "verified", "not_found", "value_mismatch", "moved"}


class QuoteJudge:  # one value in its quote, one the model read wrong (70.20 is the paper's other number)
    def extract_spec(self, pages):
        return {"items": [
            {"category": "result", "statement": "LinearRAG의 색인 시간은 249.78초이다", "value": "249.78",
             "quote": "LinearRAG (Ours) 249.78 0.093 0 0 66.95", "page": 9},
            {"category": "result", "statement": "2Wiki에서 GPT 정확도는 70.20%이다", "value": "70.20%",
             "quote": "LinearRAG achieves 63.70% GPT-based accuracy on 2Wiki", "page": 8}], "missing": []}


def test_spec_value_in_quote():
    """A condition whose value is not in the quote Pablo anchored is kept, and marked (the card says so)."""
    if not os.path.exists(PDF):
        print("skip test_spec_value_in_quote: LinearRAG.pdf not here")
        return
    s = PabloSkill(IntentEngine(), QuoteJudge())
    t = s.start_task("LinearRAG 재현", [])
    stated, _, dropped = s.spec(t.id, s.capture_pdf(PDF).id)
    assert not dropped and [c.spec.get("value_in_quote", True) for c in stated] == [True, False]
    assert model(s, t.id)["checks"][stated[1].id]["spec"]["value_in_quote"] is False


def test_page_script_parses():
    """The page's script is one big string in viewer.py: a typo there blanks the whole app. node --check catches it here."""
    import shutil
    if not shutil.which("node"):
        print("skip test_page_script_parses: no node")
        return
    with tempfile.TemporaryDirectory() as d:
        ui_fixture.build(d)
        page = open(os.path.join(d, "view-T1.html"), encoding="utf-8").read()
        js = page.split("<script>", 1)[1].rsplit("</script>", 1)[0]
        f = os.path.join(d, "page.js")
        open(f, "w", encoding="utf-8").write(js)
        r = subprocess.run(["node", "--check", f], capture_output=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr[-800:]


def cli(d, *args):
    r = subprocess.run([sys.executable, "-m", "pablo_v2", *args, "--json", "--dir", d], capture_output=True, encoding="utf-8",
                       env={**os.environ, "PYTHONPATH": SRC, "PYTHONIOENCODING": "utf-8"})
    return r.returncode, json.loads(r.stdout)


def test_chat_criteria():
    """A chat message's criteria become intent of the task it was said in (not of the latest task); the request is no goal."""
    with tempfile.TemporaryDirectory() as d:
        cli(d, "task", "T1 작업", "--checks", "[]")
        cli(d, "task", "T2 작업", "--checks", "[]")
        _, r = cli(d, "say", "hello.txt에 world를 추가해줘. 앞으로 다른 파일은 절대 건드리지 마.", "--request", "--task", "T1")
        assert [(x["kind"], x["strength"], x["text"]) for x in r["added"]] == [("constraint", "hard", "앞으로 다른 파일은 절대 건드리지 마")]
        _, once = cli(d, "say", "방금 추가한 줄을 한 줄로만 알려줘. 파일은 읽지 마.", "--request", "--task", "T1")
        assert once["added"] == [] and once["candidates"] == []  # qualifies this request only: never a lasting criterion
        _, r2 = cli(d, "say", "이 프로젝트 구조 설명해줘", "--request", "--task", "T1")
        assert r2["added"] == [] and all(c["status"] == "ignored" for c in r2["candidates"])  # a request is not a goal
        s = load(d)
        ids = lambda t: [c.id for c in s.get_applicable_intent(t)["constraints"]]  # noqa: E731
        assert ids("T1") == [r["added"][0]["id"]] and ids("T2") == []  # said in T1 after T2 was made: still T1's
        assert s.intent.get_active_goals() == []
        code, _ = cli(d, "say", "x", "--request", "--task", "T9")
        assert code == 1  # unknown task
        _, r3 = cli(d, "say", "PyTorch가 좀 편할 것 같긴 한데", "--request", "--task", "T1")  # hedged: held back
        k = r3["candidates"][0]
        assert k["status"] == "pending" and r3["added"] == []
        _, p = cli(d, "promote", k["id"])  # the desktop's [기준으로 추가]
        s = load(d)
        assert p["item"]["id"] in ids("T1") and p["item"]["id"] not in ids("T2")


def test_current_step_after_done():
    """Follow-up actions on a finished request keep its step (no 'no plan step' WARN for every later edit)."""
    with tempfile.TemporaryDirectory() as d:
        cli(d, "task", "T1 작업", "--checks", "[]")
        cli(d, "plan", "T1", "--steps", json.dumps([{"action": "hello.txt에 줄 추가", "basis": []}]))
        s = load(d)
        assert current_step(s, "T1") == "P1.1"
        # the step is completed by a review (records written directly: no judge needed for this rule)
        s.state.actions.append(ActionProposal("ACT1", "T1", "파일 수정: hello.txt", "P1.1", verdict="ALLOW"))
        s.state.executions.append(ExecutionRecord("EX1", "ACT1", "proceed", True, "파일 수정: hello.txt"))
        s.state.reviews.append(PostReview("REV1", "EX1", "ACT1", {}, "aligned", "completed"))
        assert current_step(s, "T1") == "P1.1"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
