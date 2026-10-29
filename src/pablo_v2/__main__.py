"""pablo_v2 CLI. Host agents add --json and read stdout; humans read the default text.

Account   login [--device] | logout | status
Intent    say "<msg>" [--agent] [--llm] | show | candidates | history | promote K4 | reject K4 | demo [--llm]
          promote K4 --as hard|soft | strength C2 hard|soft | drop C2 [--reason R] | restore C2   (the user's own edits)
          restate C2 "<new text>"                  C3: the user rewrites a criterion (same id, kind, strength, scope)
Skill     task "<task>" [--checks JSON] [--repro]  start task; no --checks -> Codex analyzer decides checks
          search SC1 "<target>" "<query>" --tier 1 --found|--not-found
          check SC1 VERIFIED "<conclusion>" [--sources JSON] [--stop-reason R]
          plan T1 --steps JSON                    [{"action": "...", "basis": ["SC1", "C1"]}]
          waive SC3 --reason "<why this check is not needed>"
          act T1 "<action>" [--step P1.1] [--why "<justification>"]   -> ALLOW | WARN | BLOCK
          gate T1 "<action>"                      act on the current plan step; + a plain-language reason (desktop host)
          decide ACT6 proceed|defer|reject [--reason "<why>"]
          record ACT6 "<what you did>" [--not-executed] [--files a.py b.py] [--test "<name>=pass|fail|skip"]...
                 [--observe "<fact>"]... [--error "<error>"]...      -> EX1
          review EX1                              -> PostReview (observations + proposals, changes nothing)
          view T1 [--html]                        --html: snapshot evidence viewer file
          brief T1                                what the desktop agent is told: criteria + located facts (+ basis ids)
          audit T1                                the 재현 점검 turn for the desktop agent: prompt + output schema + items
Evidence  source <url> [--title T]                Pablo fetches + snapshots the page -> SRC1 (version = content hash)
          source <file.pdf> [--title T] [--arxiv ID]   M3.3: copies the PDF + its page text -> SRC1 (version = bytes hash)
                                                  (C2 --arxiv: title and arXiv version read from the PDF)
          anchor SRC1 "<exact quote>" [--near "<text next to it>"] [--page N]   -> E1 (refused if missing or ambiguous)
          link E1 SC2 supports|contradicts|verifies|implements|derived_from [--note ...]
          resolve E1 | --all | --source SRC1      re-fetch live source -> VALID | STALE | UNRESOLVED
          evidence E1                             quote in context, status, links
          ask T1 "<question>" [--source SRC1]...  M3.3: answer from a captured PDF, quotes anchored -> SC + [n] citations
                                                  (C1: several --source, each quote anchored in its own paper)
          spec T1 [--source SRC1]                 the paper's reproduction conditions -> anchored VERIFIED checks
                                                  (+ pending checks for what the paper does not state; replaces the
                                                  task's conditions from any paper: one paper is reproduced)
          add-spec T1 --source SRC1 --quote Q --page N --category C --statement S [--value V]   one condition by hand
          drop-spec SC5 --reason R | restore-spec SC5   take a condition out (kept, with why) / back
          deviate SC5 --reason R [--scope runs|task] | undeviate SC5   ⑦ differ from it on purpose / back
          rename-source SRC2 --title "HippoRAG 2"  ⑧ the name the user knows a paper by
          compare T1 --source SRC1 --source SRC2 [--columns JSON]   C3: a table, one judge call per paper, each cell
                                                  anchored or left empty -> M1 + cells
JSON args accept inline JSON or @file.json. State lives in --dir (default .pablo/).
Exit codes: 0 ok, 2 refused by Pablo (research gate etc.), 1 other error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
from dataclasses import asdict

from pablo_v2 import auth
from pablo_v2.intent.engine import IntentEngine
from pablo_v2.intent.extract import HeuristicExtractor, LLMExtractor, reads_like_rule, standing_criteria
from pablo_v2.intent.render import render_candidates, render_history, render_intent
from pablo_v2.llm import ProviderError, provider
from pablo_v2.skill.judge import LLMJudge
from pablo_v2.skill import mdhtml
from pablo_v2.skill.viewer import REPORT_SECTIONS, model, render_html, render_report, report_counts, workspace
from pablo_v2.skill.evidence import AnchorRejected, similar
from pablo_v2.skill.skill import (AUDIT_SCHEMA, REPRO_CRITERIA, SPEC_LABEL, DecisionRejected, PabloSkill,
                                  ResearchIncomplete, ResearchRejected, render_audit, render_brief, render_evidence, render_task)

# M1.1 acceptance conversation: (role, text)
ACCEPTANCE = [
    ("user", "논문 X의 baseline을 Dataset Y에서 재현해줘."),
    ("user", "공식 구현이 있으면 가능하면 그걸 우선해."),
    ("user", "evaluation split은 반드시 그대로 유지해야 해."),
    ("user", "README 먼저 보고 와."),
    ("user", "나는 PyTorch 쪽이 좀 편하긴 해."),
    ("agent", "공식 repo 구조가 복잡해서, 제가 custom implementation을 새로 작성하는 쪽으로 진행하겠습니다."),
    ("user", "아니 공식 repo 쓰라고 했잖아."),
    ("user", "그냥 이번에는 random split으로 바꾸자."),
]

SCENARIO = [
    "논문 X의 baseline을 Dataset Y에서 재현해줘.",
    "공식 코드 있으면 그거 써.",
    "일단 README부터 읽어봐.",
    "PyTorch가 좀 편할 것 같긴 한데.",
    "논문에 나온 평가 방식은 그대로 유지해야 돼.",
    "아니 공식 repo 쓰라고 했잖아.",
]


def _json_arg(v: str):
    if v.startswith("@"):
        with open(v[1:], encoding="utf-8") as f:
            return json.load(f)
    return json.loads(v)


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output for host agents")
    common.add_argument("--dir", default=".pablo", help="state directory (intent.json, skill.json)")
    common.add_argument("--model", help="Codex model override")
    common.add_argument("--llm", action="store_true", help="say/demo: classify with Codex (heuristic otherwise)")

    p = argparse.ArgumentParser(prog="pablo_v2")  # options go after the subcommand
    sub = p.add_subparsers(dest="cmd", required=True)
    add = lambda name, *args: sub.add_parser(name, parents=[common])  # noqa: E731
    add("login").add_argument("--device", action="store_true", help="device-code sign-in for headless machines")
    for name in ("logout", "status", "show", "candidates", "history", "demo"):
        add(name)
    s = add("similar")  # S8 the places in a page's text (stdin) most like a quote that was not found there
    s.add_argument("--quote", required=True)
    s.add_argument("--k", type=int, default=3)
    s = add("say")
    s.add_argument("text")
    s.add_argument("--agent", action="store_true", help="agent message: context only, never intent")
    s.add_argument("--scope", choices=["task"], help="said as part of the current (latest) task, e.g. desktop new-task criteria: "
                   "project-scope candidates become task-scoped")
    s.add_argument("--request", action="store_true", help="a chat message to the desktop agent: one sentence at a time, its "
                   "criteria become task-scoped intent; the request itself is the plan step, never a goal")
    s.add_argument("--task", help="the task this was said in (--scope task / --request): its task-scoped intent applies "
                   "to that task only, also when other tasks were made later")
    s.add_argument("--rule", choices=["hard", "soft"], help="the user picked this text as a rule of the task (desktop: a "
                   "message -> 기준으로): read as a constraint of that strength, never a goal or a question")
    s = add("promote")
    s.add_argument("id")
    s.add_argument("--as", dest="as_", choices=["hard", "soft"], help="③ make an unread / held line a rule of its task")
    add("reject").add_argument("id")
    s = add("strength")  # ④ the user changes a criterion's strength
    s.add_argument("id"), s.add_argument("level", choices=["hard", "soft"])
    s = add("drop")  # ④ the user removes a criterion (kept in the history, status removed)
    s.add_argument("id")
    s.add_argument("--reason", default="", help="required for a reproduction task's default criterion")
    add("restore").add_argument("id")  # ④ a removed criterion back
    s = add("restate")  # C3 the user rewrites a criterion's sentence (history: 사용자가 고침)
    s.add_argument("id"), s.add_argument("text")
    s = add("add-spec")  # ⑩ a sentence the user picked in the paper -> a reproduction condition, anchored
    s.add_argument("task_id"), s.add_argument("--source", required=True), s.add_argument("--quote", required=True)
    s.add_argument("--page", type=int), s.add_argument("--category", required=True, choices=list(SPEC_LABEL))
    s.add_argument("--statement", required=True), s.add_argument("--value", default="")
    s = add("drop-spec")  # ⑩ a condition taken out by the user (with why; restorable)
    s.add_argument("check_id"), s.add_argument("--reason", required=True)
    add("restore-spec").add_argument("check_id")
    s = add("rename-task")  # ⑭ the name a task goes by in the list (its text stays the goal)
    s.add_argument("task_id"), s.add_argument("--name", required=True)
    s = add("rename-source")  # ⑧ the name the user knows a paper by
    s.add_argument("source_id"), s.add_argument("--title", required=True)
    s = add("deviate")  # ⑦ differ from a paper condition on purpose (why required)
    s.add_argument("check_id"), s.add_argument("--reason", required=True)
    s.add_argument("--scope", choices=["runs", "task"], default="runs",
                   help="runs (default): separate runs only, the base run stays as the paper says; task: the whole task")
    add("undeviate").add_argument("check_id")  # ⑦ back to the paper's condition
    s = add("view")
    s.add_argument("id", nargs="?", help="task to show first (--html: default the latest)")
    s.add_argument("--html", action="store_true", help="write <dir>/view-T1.html (export/debug snapshot of every task)")
    add("state")  # the desktop's live workspace model (read-only)
    add("brief").add_argument("task_id")
    add("audit").add_argument("task_id")
    s = add("summarize")  # UI renewal P6 단계별: the model's summary of one stage, from the messages the desktop groups under it
    s.add_argument("task_id"), s.add_argument("--stage", required=True)
    s.add_argument("--messages", type=_json_arg, required=True, help='[{"who": "You" | "Pablo", "text"}, ...], or @file')
    s = add("set-goal")  # the user rewrites the task's goal (its text)
    s.add_argument("task_id"), s.add_argument("goal")
    s = add("drift")  # a chat message judged against its task's goal: same / sub / different (the desktop asks first)
    s.add_argument("task_id"), s.add_argument("text")
    s.add_argument("--recent", type=_json_arg, default=[], help="the task's last user messages, oldest first")
    s = add("report")  # ⑫ the reproduction report (Markdown)
    s.add_argument("task_id")
    s.add_argument("--now", type=_json_arg, default=None, help='desktop: {"tree", "git": {head, dirty}, "recheck": {at, placed, gone}}')
    s.add_argument("--sections", type=_sections, help="A13 the parts to keep, comma separated: " + ",".join(REPORT_SECTIONS)
                   + " (default: all but conversation)")
    s.add_argument("--format", choices=["md", "html"], default="md", help="A13 html: the Markdown as one self-contained page")
    s.add_argument("--preview", action="store_true", help="A13 the export dialog's numbers only (no text)")

    s = add("task")
    s.add_argument("text")
    s.add_argument("--checks", type=_json_arg, help='[{"requirement", "necessity", "why"}]; [] = no research')
    s.add_argument("--repro", action="store_true", help="a reproduction task: the output lists the criteria it starts "
                   "with (say them with --scope task --task T)")
    s = add("search")
    s.add_argument("check_id"), s.add_argument("target"), s.add_argument("query")
    s.add_argument("--tier", type=int, required=True, help="authority of what you searched, 1 official docs .. 6 web")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--found", dest="found", action="store_true")
    g.add_argument("--not-found", dest="found", action="store_false")
    s = add("check")
    s.add_argument("check_id"), s.add_argument("outcome"), s.add_argument("conclusion")
    s.add_argument("--sources", type=_json_arg, default=[], help="[{tier, type, title, url, supports}]")
    s.add_argument("--stop-reason")
    s = add("waive")
    s.add_argument("check_id")
    s.add_argument("--reason", required=True)
    s = add("plan")
    s.add_argument("task_id")
    s.add_argument("--steps", type=_json_arg, required=True)
    s = add("act")
    s.add_argument("task_id"), s.add_argument("description")
    s.add_argument("--step")
    s.add_argument("--why", help="justification when the action departs from the plan, a constraint or a source")
    s = add("gate")
    s.add_argument("task_id"), s.add_argument("description")
    s.add_argument("--rewrites", type=_json_arg, default=[], help='file edits measured by the host: [{"path", "lines", "removed"}]')
    s = add("decide")
    s.add_argument("action_id"), s.add_argument("decision", choices=["proceed", "defer", "reject"])
    s.add_argument("--reason", default="")
    s = add("record")
    s.add_argument("action_id"), s.add_argument("summary")
    s.add_argument("--not-executed", dest="executed", action="store_false", help="deferred / rejected / skipped")
    s.add_argument("--files", nargs="*", default=[], help="changed file paths (no diffs)")
    s.add_argument("--test", dest="tests", action="append", default=[], type=_test_arg, help='"<name>=pass|fail|skip"')
    s.add_argument("--observe", dest="observations", action="append", default=[])
    s.add_argument("--error", dest="errors", action="append", default=[])
    add("review").add_argument("execution_id")
    s = add("source")
    s.add_argument("url"), s.add_argument("--title", default="")
    s.add_argument("--arxiv", help="C2: the arXiv id the PDF was downloaded as (title + version from the PDF itself)")
    s.add_argument("--openreview", help="⑬ the OpenReview forum id the PDF was downloaded as (title from the PDF itself)")
    s.add_argument("--doi", help="⑬ with --arxiv: the publisher DOI this arXiv version was found by")
    s = add("anchor")
    s.add_argument("source_id"), s.add_argument("exact")
    s.add_argument("--near", default="", help="text next to the intended occurrence when the quote repeats")
    s.add_argument("--page", type=int, help="PDF sources: the page the quote is on")
    s = add("link")
    s.add_argument("evidence_id"), s.add_argument("target_id")
    s.add_argument("relation", choices=["supports", "contradicts", "verifies", "implements", "derived_from"])
    s.add_argument("--note", default="")
    s = add("resolve")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("evidence_id", nargs="?")
    g.add_argument("--all", action="store_true")
    g.add_argument("--source", dest="source_id", help="C2: every anchor of one source (a newer version saved over its file)")
    add("evidence").add_argument("evidence_id")
    s = add("ask")
    s.add_argument("task_id"), s.add_argument("question")
    s.add_argument("--source", action="append", help="PDF source id, repeat for several papers (default: the latest PDF)")
    s = add("spec")
    s.add_argument("task_id")
    s.add_argument("--source", help="PDF source id (default: the latest captured PDF)")
    s = add("compare")
    s.add_argument("task_id")
    s.add_argument("--source", action="append", required=True, help="PDF source id, two or more")
    s.add_argument("--columns", type=_json_arg, help='["데이터셋", "평가 지표", ...] (default: skill.COLUMNS)')
    s.add_argument("--into", help="⑧ a table that is there (M1): its new columns only, the same matrix id")
    return p


def _sections(v: str) -> list[str]:
    xs = [x.strip() for x in v.split(",") if x.strip()]
    if not xs or any(x not in REPORT_SECTIONS for x in xs):
        raise argparse.ArgumentTypeError("expected some of: " + ",".join(REPORT_SECTIONS))
    return xs


def _test_arg(v: str) -> dict:
    name, _, result = v.rpartition("=")
    if not name or result not in ("pass", "fail", "skip"):
        raise argparse.ArgumentTypeError('expected "<name>=pass|fail|skip"')
    return {"name": name, "result": result}


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    a = _parser().parse_args(argv)

    def out(data, text):
        print(json.dumps({"ok": True, **data}, ensure_ascii=False, indent=2) if a.json else text)

    try:
        return _run(a, out)
    except (ResearchIncomplete, ResearchRejected, DecisionRejected, AnchorRejected) as e:
        code, err = 2, e
    except (KeyError, ValueError, auth.AuthError, ProviderError) as e:
        code, err = 1, e
    msg = str(err.args[0]) if err.args else str(err)  # KeyError's str() adds quotes
    print(json.dumps({"ok": False, "error": type(err).__name__, "message": msg}, ensure_ascii=False)
          if a.json else f"{type(err).__name__}: {msg}")
    return code


def _run(a, out) -> int:
    if a.cmd == "login":
        return auth.login(device=a.device)
    if a.cmd == "logout":
        return auth.logout()
    if a.cmd == "status":
        ok, msg = auth.status()
        out({"signed_in": ok, "message": msg}, msg)
        return 0 if ok else 1
    if a.cmd == "similar":  # no state: the text comes on stdin (a page can be longer than a command line)
        sys.stdin.reconfigure(encoding="utf-8")
        hits = similar(sys.stdin.read(), a.quote, max(1, min(a.k, 10)))
        out({"hits": hits}, "\n".join(f"{h['score']:.2f} {h['text']}" for h in hits) or "(none)")
        return 0

    intent_path = os.path.join(a.dir, "intent.json")
    if a.cmd == "demo" and os.path.exists(intent_path):
        os.remove(intent_path)
    extractor = LLMExtractor(provider(a.model)) if a.llm else HeuristicExtractor()
    e = IntentEngine.load(intent_path, extractor)
    s = PabloSkill.load(os.path.join(a.dir, "skill.json"), e, LLMJudge(provider(a.model)))

    if a.cmd == "say":
        if a.rule:  # the reader keeps the words, topics and relation; what it is (a rule, how strong) the user said
            ex0 = e.extractor.extract
            e.extractor.extract = lambda *x: [dict(f, candidate=True, type="constraint", strength=a.rule, scope="task",
                                                   persistence="high", impact="high") for f in ex0(*x)]
        if a.scope or a.request:  # same task scope the extractor gives "이번 작업에서는 ..."; the M1 policy/relations are unchanged
            ex = e.extractor.extract
            e.extractor.extract = lambda *x: [dict(f, scope="task") if f.get("scope") == "project" else f for f in ex(*x)]
            if a.task:
                s.get_task(a.task)
                ex1 = e.extractor.extract
                e.extractor.extract = lambda *x: [dict(f, task=a.task) if f.get("scope") in ("task", "action") else f
                                                  for f in ex1(*x)]
        if a.request:  # "X 해줘. Y는 건드리지 마." -> the request is the step; only its criteria (Y) are intent
            ex2 = e.extractor.extract
            e.extractor.extract = lambda *x: [dict(f, type="other") if f.get("type") == "goal" else f for f in ex2(*x)]
            ks = [k for p in standing_criteria(a.text) for k in e.process_message(p)]
        else:
            ks = e.process_message(a.text, role="agent" if a.agent else "user")
        added = [e.get_item(k.item_id) for k in ks if k.status == "committed" and k.item_id]
        # ③ never dropped without a word: a criterion line the reader could not classify comes back for the user to
        # decide (a new task's lines always; a chat sentence when it ends like an instruction)
        unread = [{"id": k.id, "text": k.text} for k in ks if k.status == "ignored" and (not a.request or reads_like_rule(k.text))]
        out({"candidates": [asdict(k) for k in ks], "unread": unread,
             "added": [{"id": i.id, "kind": i.kind, "strength": i.strength, "text": i.statement} for i in added if i]},
            "\n".join(f"{k.id} {k.action} -> {k.status} {k.item_id or ''} ({k.policy_reason})" for k in ks)
            or "(agent message stored as context)")
    elif a.cmd == "show":
        out(_intent_json(e), render_intent(e))
    elif a.cmd == "candidates":
        out({"candidates": [asdict(k) for k in e.state.candidates]}, render_candidates(e))
    elif a.cmd == "history":
        out({"history": [asdict(c) for c in e.get_intent_history()]}, render_history(e))
    elif a.cmd == "promote":
        item = e.promote_as(a.id, a.as_) if a.as_ else e.promote_candidate(a.id)
        out({"item": asdict(item)}, item.id)
    elif a.cmd == "strength":
        item = e.set_strength(a.id, a.level)
        out({"item": asdict(item)}, f"{item.id} -> {item.strength}")
    elif a.cmd == "drop":
        item = s.drop_criterion(a.id, a.reason)
        out({"item": asdict(item)}, f"{item.id} removed")
    elif a.cmd == "restore":
        item = e.restore_item(a.id)
        out({"item": asdict(item)}, f"{item.id} restored")
    elif a.cmd == "restate":
        before = (e.get_item(a.id) or argparse.Namespace(statement=None)).statement
        item = e.restate_item(a.id, a.text)
        out({"item": asdict(item), "before": before}, f"{item.id} -> {item.statement}")
    elif a.cmd == "reject":
        e.reject_candidate(a.id)
        out({}, f"{a.id} rejected")
    elif a.cmd == "demo":
        _demo(e)

    elif a.cmd == "task":
        t = s.start_task(a.text, a.checks)
        out({**_task_json(s, t.id), **({"repro": list(REPRO_CRITERIA)} if a.repro else {})}, render_task(s, t.id))
    elif a.cmd == "search":
        s.record_search(a.check_id, a.target, a.query, a.tier, a.found)
        c = s.get_check(a.check_id)
        out({"check": asdict(c)}, f"{c.id}: {len(c.searched)} searches recorded")
    elif a.cmd == "check":
        c = s.complete_check(a.check_id, a.outcome, a.conclusion, a.sources, a.stop_reason)
        out({"check": asdict(c)}, f"{c.id} completed: {c.outcome}")
    elif a.cmd == "waive":
        c = s.waive(a.check_id, a.reason)
        out({"check": asdict(c)}, f"{c.id} waived")
    elif a.cmd == "plan":
        p = s.create_plan(a.task_id, a.steps)
        out({"plan": asdict(p)}, render_task(s, a.task_id))
    elif a.cmd == "act":
        act = s.propose_action(a.task_id, a.description, a.step, a.why)
        out({"action": asdict(act)}, "\n".join([f"{act.id} {act.verdict}"] +
                                              [f"  {r['rule']} {r['verdict']}: {r['reason']}" for r in act.reasons]))
    elif a.cmd == "gate":
        step = current_step(s, a.task_id)
        act = s.propose_action(a.task_id, a.description, step, rewrites=a.rewrites)
        v = next(x for x in model(s, a.task_id)["actions"] if x["id"] == act.id)
        reason = plain(v["problems"][0], {c["id"]: c["text"] for c in v["criteria"]}) \
            if v["problems"] and act.verdict != "ALLOW" else ""
        ai = s.get_applicable_intent(a.task_id)
        out({"action": asdict(act), "step": step, "reason": reason,
             "intent": [i.id for i in ai["constraints"]], "excluded": ai["other"]}, f"{act.id} {act.verdict} {reason}")
    elif a.cmd == "decide":
        act = s.decide_action(a.action_id, a.decision, a.reason)
        out({"action": asdict(act)}, f"{act.id} {act.verdict} -> host {act.host_decision}")
    elif a.cmd == "record":
        x = s.record_execution(a.action_id, a.executed, a.summary, a.files, a.tests, a.observations, a.errors)
        out({"execution": asdict(x)}, f"{x.id} recorded for {x.action_id}")
    elif a.cmd == "review":
        r = s.review_execution(a.execution_id)
        out({"review": asdict(r), "research_issues": [asdict(i) for i in s.state.issues if i.review_id == r.id]},
            render_task(s, s.get_action(r.action_id).task_id))
    elif a.cmd == "source":
        x = s.capture_pdf(a.url, a.title, a.arxiv, a.openreview, a.doi) if a.url.lower().endswith(".pdf") and os.path.isfile(a.url) \
            else s.capture_source(a.url, a.title)
        out({"source": asdict(x)}, f"{x.id} {x.title} {x.version['content_hash'][:19]} -> {x.snapshot}")
    elif a.cmd == "anchor":
        x = s.add_anchor(a.source_id, a.exact, a.near, a.page)
        out({"anchor": asdict(x)}, render_evidence(s, x.id))
    elif a.cmd == "link":
        x = s.link_evidence(a.evidence_id, a.target_id, a.relation, a.note)
        out({"link": asdict(x)}, f"{x.id}: {x.evidence_id} {x.relation} {x.target_id}")
    elif a.cmd == "resolve":
        xs = s.resolve_source(a.source_id) if a.source_id else \
            [s.resolve_anchor(i) for i in ([x.id for x in s.state.anchors] if a.all else [a.evidence_id])]
        out({"anchors": [asdict(x) for x in xs]}, "\n".join(render_evidence(s, x.id) for x in xs))
    elif a.cmd == "evidence":
        out({"anchor": asdict(s.get_anchor(a.evidence_id)),
             "links": [asdict(x) for x in s.state.links if x.evidence_id == a.evidence_id]},
            render_evidence(s, a.evidence_id))
    elif a.cmd == "ask":
        sc, dropped = s.ask(a.task_id, a.question, a.source)
        v = model(s, a.task_id)  # the desktop appends this answer to the conversation without a reload
        ids = v["checks"][sc.id]["evidence"]
        out({"check": v["checks"][sc.id], "dropped": dropped, "anchors": {e: v["anchors"][e] for e in ids},
             "sources": {x: v["sources"][x] for x in {v["anchors"][e]["source"] for e in ids}}},
            "\n".join([sc.conclusion, *(render_evidence(s, e) for e in ids),
                       *(f"dropped p.{d['page']}: {d['quote']} ({d['why']})" for d in dropped)]))
    elif a.cmd == "compare":
        mid, cells, empty = s.compare(a.task_id, a.source, a.columns, a.into)
        v = model(s, a.task_id)  # the desktop shows the table without a reload
        ids = [e for c in cells for e in v["checks"][c.id]["evidence"]]
        out({"matrix": mid, "cells": [v["checks"][c.id] for c in cells], "empty": empty,
             "anchors": {e: v["anchors"][e] for e in ids},
             "sources": {x: v["sources"][x] for x in {v["anchors"][e]["source"] for e in ids}}},
            "\n".join([f"{mid}: {len(cells)} cells anchored, {len(empty)} empty"]
                      + [f"{c.id} [{c.matrix['source_id']} · {c.matrix['column']}] {c.conclusion}" for c in cells]
                      + [f"empty [{x['source_id']} · {x['column']}] {x['why']}" for x in empty]))
    elif a.cmd == "spec":
        # D9: how far the model has read, one JSON line on stderr each time it grows (the desktop shows "9 / 20쪽")
        tell = lambda page, pages: print(json.dumps({"progress": {"page": page, "pages": pages}}), file=sys.stderr, flush=True)  # noqa: E731
        stated, missing, dropped = s.spec(a.task_id, a.source, progress=tell)
        v = model(s, a.task_id)
        ids = [e for c in stated for e in v["checks"][c.id]["evidence"]]
        out({"stated": [v["checks"][c.id] for c in stated], "missing": [v["checks"][c.id] for c in missing],
             "dropped": dropped, "diff": s.spec_diff, "anchors": {e: v["anchors"][e] for e in ids},
             "sources": {x: v["sources"][x] for x in {v["anchors"][e]["source"] for e in ids}}},
            "\n".join([f"{c.id} [{c.spec['category']}] {c.conclusion}" for c in stated]
                      + [f"{c.id} [{c.spec['category']}] 논문에 없음: {c.requirement}" for c in missing]
                      + [f"dropped p.{d['page']}: {d['quote']} ({d['why']})" for d in dropped]))
    elif a.cmd == "add-spec":
        sc = s.add_spec(a.task_id, a.source, a.quote, a.page, a.category, a.statement, a.value)
        v = model(s, a.task_id)
        ids = v["checks"][sc.id]["evidence"]
        out({"check": v["checks"][sc.id], "anchors": {e: v["anchors"][e] for e in ids},
             "sources": {x: v["sources"][x] for x in {v["anchors"][e]["source"] for e in ids}}},
            f"{sc.id} [{sc.spec['category']}] {sc.conclusion}")
    elif a.cmd in ("drop-spec", "restore-spec"):
        sc = s.drop_spec(a.check_id, a.reason) if a.cmd == "drop-spec" else s.restore_spec(a.check_id)
        out({"check": asdict(sc)}, f"{sc.id} {sc.research_state}")
    elif a.cmd == "rename-task":
        t = s.rename_task(a.task_id, a.name)
        out({"task": asdict(t)}, f"{t.id} -> {t.name or t.text}")
    elif a.cmd == "rename-source":
        src = s.rename_source(a.source_id, a.title)
        out({"source": asdict(src)}, f"{src.id} -> {src.title}")
    elif a.cmd in ("deviate", "undeviate"):
        sc = s.deviate_spec(a.check_id, a.reason, a.scope) if a.cmd == "deviate" else s.undeviate_spec(a.check_id)
        out({"check": asdict(sc)}, f"{sc.id} {'differs on purpose' if a.cmd == 'deviate' else 'back to the paper'}")
    elif a.cmd == "view" and a.html:
        path = os.path.abspath(os.path.join(a.dir, f"view-{a.id}.html" if a.id else "pablo.html"))
        with open(path, "w", encoding="utf-8") as f:
            f.write(render_html(s, a.id))
        uri = pathlib.Path(path).as_uri()
        out({"path": path, "uri": uri}, f"{uri}\n(append #E1 to open an evidence directly)")
    elif a.cmd == "view" and a.id:
        out(_task_json(s, a.id), render_task(s, a.id))
    elif a.cmd == "view":
        raise SystemExit("view: task id required (or --html)")
    elif a.cmd == "state":
        # A12 the criteria a reproduction task starts with (the new-task dialog lists them before the task exists)
        out({**workspace(s), "reproCriteria": list(REPRO_CRITERIA)}, f"{len(s.state.tasks)} tasks")
    elif a.cmd == "audit":
        prompt, items = render_audit(s, a.task_id)
        out({"prompt": prompt, "schema": AUDIT_SCHEMA, "items": items}, prompt)
    elif a.cmd == "summarize":
        r = s.judge.summarize_stage(s.get_task(a.task_id).text, a.stage, a.messages)
        out({"summary": r["summary"].strip()}, r["summary"].strip())
    elif a.cmd == "set-goal":
        t = s.set_goal(a.task_id, a.goal)
        out({"task": asdict(t)}, f"{t.id} -> {t.text}")
    elif a.cmd == "drift":
        r = s.judge.drift(s.get_task(a.task_id).text, a.text, [str(m) for m in a.recent])
        out(r, f"{r['verdict']} {r['reason']}")
    elif a.cmd == "report" and a.preview:
        c = report_counts(s, a.task_id, a.now)
        out({"counts": {k: v for k, v in c.items() if k != "stale"}, "stale": c["stale"], "title": s.get_task(a.task_id).text},
            json.dumps(c, ensure_ascii=False))
    elif a.cmd == "report":
        md, title = render_report(s, a.task_id, a.now, a.sections), s.get_task(a.task_id).text
        text = mdhtml.page(md, f"재현 보고서: {title}") if a.format == "html" else md
        out({"text": text, "title": title, "format": a.format}, text)
    elif a.cmd == "brief":
        text, basis = render_brief(s, a.task_id)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] if text else ""
        out({"text": text, "basis": basis, "hash": digest}, text or "(nothing to tell the agent)")
    return 0


def plain(text: str, labels: dict) -> str:
    """Judge note for the conversation: an id becomes its text once, then is dropped (no rule/ACT/intent ids in the UI)."""
    seen = set()

    def sub(m):
        if m[0] in labels and m[0] not in seen:
            seen.add(m[0])
            return f"'{labels[m[0]]}'"
        return ""
    text = re.sub(r"(?<![A-Za-z])[A-Z]{1,3}\d+(?:\.\d+)?", sub, text)
    return re.sub(r"\s*\(\s*[,\s]*\)|\s+(?=[.,])", "", text).strip()


def current_step(s: PabloSkill, task_id: str) -> str | None:
    """First step of the active plan that no PostReview has marked completed; when every step is, the last one: the
    agent is still working on that request (follow-up edits, a test run), not acting without a plan. None without a plan."""
    plans = [p for p in s.plans(task_id) if p.status == "active"]
    done = {r.action_id for r in s.state.reviews if r.plan_step_status == "completed"}
    done = {s.get_action(i).plan_step for i in done}
    if not plans or not plans[-1].steps:
        return None
    return next((st["id"] for st in plans[-1].steps if st["id"] not in done), plans[-1].steps[-1]["id"])


def _intent_json(e: IntentEngine) -> dict:
    items = lambda xs: [asdict(i) for i in xs]  # noqa: E731
    return {"version": e.state.version, "goals": items(e.get_active_goals()),
            "constraints": items(e.get_active_constraints()), "success_criteria": items(e.get_success_criteria()),
            "decisions": items(e.get_decisions()), "assumptions": items(e.get_assumptions()),
            "open_questions": items(e.get_open_questions()), "pending": items(e.get_pending_candidates()),
            "deviations": items(e.get_deviations())}


def _task_json(s: PabloSkill, task_id: str) -> dict:
    checks = s.checks(task_id)
    return {"task": asdict(s.get_task(task_id)), "necessity": s.necessity(task_id),
            "required_count": sum(c.necessity == "REQUIRED" for c in checks),
            "pending_required": s.pending_required(task_id), "checks": [asdict(c) for c in checks],
            "plans": [asdict(p) for p in s.plans(task_id)], "actions": [asdict(x) for x in s.actions(task_id)]}


def _demo(e: IntentEngine) -> None:
    for role, text in ACCEPTANCE:
        print(f"> [{role}] {text}")
        for k in e.process_message(text, role=role):
            f = k.features
            print(f"  {k.id}: {f['type']}/{f['strength'] or '-'} rel={f['relation']['type']}"
                  f"->{f['relation']['target_id'] or '-'} | {k.action} -> {k.status} {k.item_id or ''}"
                  f" ({k.policy_reason})")
    # agent-side items, to show they stay separate from user intent
    e.add_assumption("Dataset Y는 v2를 의미한다고 추정", note="dataset 이름 모호")
    e.add_open_question("논문과 대응되는 repository commit은 무엇인가?", blocking=True)
    print("\n" + render_intent(e) + "\n\n" + render_candidates(e) + "\n\n" + render_history(e))


if __name__ == "__main__":
    sys.exit(main())
