"""PabloSkill: governance middleware between a host agent (Claude Code / Codex) and its actions.

  start_task -> reused + new SourceChecks (Task Analysis); waive drops an over-generated check, with a trace
  record_search / complete_check  (Authoritative Research; the host agent does the actual searching)
  create_plan   (refused until every REQUIRED check is completed; NOT_FOUND is completed, not verified)
  propose_action -> ALLOW | WARN | BLOCK  (judge facts vs intent, system policies, the task's sources, the plan)
  decide_action   host records proceed | defer | reject
  record_execution -> ExecutionRecord  (what the host actually did; paths + summary, no diffs)
  review_execution -> PostReview  (judge observations + review.py rules; proposals only, nothing is changed)
  capture_source / add_anchor / link_evidence / resolve_anchor  (M3.1 evidence anchors, see evidence.py)
  capture_pdf / add_anchor(page=) / resolve_anchor  (M3.3 PDF evidence, same anchors, see pdf.py)
  ask -> check + cited anchors  (M3.3: the judge picks quotes from a captured PDF; Pablo anchors them)
Pablo never executes anything; the host agent does, depending on the verdict.
"""
from __future__ import annotations

import http.client
import json
import os
import re

from pablo_v2.intent.engine import IntentEngine
from pablo_v2.intent.models import now

from . import evidence, guard, pdf, review
from .models import (DECISIONS, NECESSITY, OUTCOMES, RELATIONS, STOP_REASONS, TIERS, ActionProposal, EvidenceAnchor,
                     EvidenceLink, EvidenceSource, ExecutionRecord, Plan, PostReview, ResearchIssue, SkillState,
                     SourceCheck, Task)


class ResearchIncomplete(RuntimeError):
    """create_plan before every REQUIRED SourceCheck is completed."""


class ResearchRejected(ValueError):
    """complete_check whose outcome the evidence recorded so far does not justify."""


class DecisionRejected(ValueError):
    """decide_action the verdict does not allow (proceed on BLOCK, proceed on WARN without a reason)."""


class PabloSkill:
    def __init__(self, intent: IntentEngine, judge=None, state: SkillState | None = None, path: str | None = None):
        self.intent, self.judge, self.state, self.path = intent, judge, state or SkillState(), path
        self.fetch = evidence.fetch  # tests swap in a fake
        self._snapshots = {}  # in-memory snapshots when there is no state path

    @classmethod
    def load(cls, path: str, intent: IntentEngine, judge=None) -> "PabloSkill":
        state = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                state = SkillState.from_dict(json.load(f))
        return cls(intent, judge, state, path)

    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.state.to_dict(), f, ensure_ascii=False, indent=2)

    # --- Task Analysis ---------------------------------------------------------
    def start_task(self, text: str, checks: list[dict] | None = None) -> Task:
        """checks: [{"requirement", "necessity", "why_blocking"?}] from the host, or None to ask the judge,
        which may also reuse completed checks of earlier tasks instead of creating new ones."""
        task = Task(self._next_id("T"), text)
        self.state.tasks.append(task)
        if checks is None and self.judge:
            done = {c.id: c for c in self.state.checks if c.research_state == "completed"}
            r = self.judge.analyze_task(text, self._intent_text(task.id), "\n".join(
                f"{c.id} [{c.outcome}] {c.requirement} -> {c.conclusion}" for c in done.values()))
            task.reused = [x["source_check_id"] for x in r["reuse"] if x["source_check_id"] in done]
            checks = [c if c["necessity"] != "REQUIRED" or c["why_blocking"].strip() else
                      {**c, "necessity": "USEFUL", "why_blocking": "downgraded: REQUIRED without why_blocking"}
                      for c in r["checks"]]
        for c in checks or []:
            self.add_check(task.id, c["requirement"], c["necessity"], c.get("why_blocking", c.get("why", "")))
        self.save()
        return task

    def add_check(self, task_id: str, requirement: str, necessity: str = "REQUIRED", why: str = "") -> SourceCheck:
        assert necessity in NECESSITY, necessity
        self.get_task(task_id)
        sc = SourceCheck(self._next_id("SC"), task_id, requirement, necessity, why)
        self.state.checks.append(sc)
        self.save()
        return sc

    def necessity(self, task_id: str) -> str:
        """Task-level source requirement = strongest check (NONE when there are no checks)."""
        return max((c.necessity for c in self.checks(task_id)), key=NECESSITY.index, default="NONE")

    # --- Authoritative Research ------------------------------------------------
    def record_search(self, sc_id: str, target: str, query: str, tier: int, found: bool) -> None:
        assert tier in TIERS, tier
        self.get_check(sc_id).searched.append(
            dict(target=target, query=query, tier=tier, result="found" if found else "not_found", at=now()))
        self.save()

    def complete_check(self, sc_id: str, outcome: str, conclusion: str, sources: list[dict] = (),
                       stop_reason: str | None = None) -> SourceCheck:
        """sources: [{tier, type, title, url, supports: [..]}]. Raises ResearchRejected (and logs why)."""
        assert outcome in OUTCOMES, outcome
        assert stop_reason in STOP_REASONS + (None,), stop_reason
        sc, sources = self.get_check(sc_id), list(sources)
        if outcome == "VERIFIED":
            stop_reason = stop_reason or "authoritative_answer_found"
        errs = guard.completion_errors(sc, outcome, sources, stop_reason)
        if errs:
            sc.rejections.append(f"{outcome}: " + "; ".join(errs))
            self.save()
            raise ResearchRejected(f"{sc_id}: " + "; ".join(errs))
        sc.research_state, sc.outcome, sc.conclusion, sc.stop_reason = "completed", outcome, conclusion, stop_reason
        sc.sources = sources
        self.save()
        return sc

    def waive(self, sc_id: str, reason: str) -> SourceCheck:
        """Host drops a check the analyzer over-generated. Kept with a trace, never deleted."""
        sc = self.get_check(sc_id)
        if sc.research_state != "pending":
            raise ValueError(f"{sc_id} is {sc.research_state}; only pending checks can be waived")
        if not reason.strip():
            raise ValueError("waive needs a reason")
        sc.research_state, sc.waived_by, sc.waive_reason = "waived", "host", reason
        self.save()
        return sc

    def pending_required(self, task_id: str) -> list[str]:
        return [c.id for c in self.checks(task_id) if c.necessity == "REQUIRED" and c.research_state == "pending"]

    # --- Plan ------------------------------------------------------------------
    def create_plan(self, task_id: str, steps: list[dict]) -> Plan:
        """steps: [{"action", "basis": [SC/intent ids]}]. Supersedes the task's previous plan."""
        if pending := self.pending_required(task_id):
            raise ResearchIncomplete(f"{task_id}: REQUIRED research not completed: {pending}")
        for s in steps:
            unknown = [b for b in s["basis"] if not (self._find_check(b) or self.intent.get_item(b))]
            if unknown:
                raise ValueError(f"unknown basis ids: {unknown}")
        for old in self.plans(task_id):
            old.status = "superseded"
        pid = self._next_id("P")
        steps = [dict(id=f"{pid}.{n}", action=s["action"], basis=list(s["basis"])) for n, s in enumerate(steps, 1)]
        plan = Plan(pid, task_id, steps, unverified=[u for s in steps for u in self._unverified(s)])
        self.state.plans.append(plan)
        self.save()
        return plan

    def _unverified(self, step: dict) -> list[str]:
        return [f"{step['id']}: {c.id} {c.outcome or c.research_state}"
                for c in map(self._find_check, step["basis"]) if c and c.outcome != "VERIFIED"]

    # --- Action Proposal + Guard -------------------------------------------------
    def propose_action(self, task_id: str, description: str, plan_step: str | None = None,
                       justification: str | None = None) -> ActionProposal:
        self.get_task(task_id)
        step = self._step(task_id, plan_step)
        constraints = {i.id: (i.strength or "soft", i.statement) for i in self.get_applicable_intent(task_id)["constraints"]}
        constraints |= {k: (v, guard.SYSTEM_POLICIES[k]) for k, v in guard.JUDGED_POLICIES.items()}
        basis = set(step["basis"]) if step else set()
        sources = {c.id: c for c in self.checks(task_id)}
        sources |= {c.id: c for c in map(self._find_check, basis) if c}
        done = [c for c in sources.values() if c.research_state == "completed"]
        analysis = self.judge.analyze_action(
            description, justification, step and step["action"],
            "\n".join(f"{k} [{st}] {text}" for k, (st, text) in constraints.items()),
            "\n".join(f"{'*' if c.id in basis else ''}{c.id} [{c.outcome}] {c.requirement} -> {c.conclusion}"
                      for c in done))
        cited = (analysis.get("justification") or {}).get("supported_by", [])
        verdict, reasons = guard.decide(
            pending_required=self.pending_required(task_id), step=step,
            unverified=self._unverified(step) if step else [], analysis=analysis,
            constraints={k: st for k, (st, _) in constraints.items()},
            sources={c.id: c.outcome for c in sources.values()},
            valid_support=[c.id for c in done if c.id in cited and c.outcome in guard.SUPPORTING_OUTCOMES])
        act = ActionProposal(self._next_id("ACT"), task_id, description, step and step["id"], justification,
                             analysis, verdict, reasons)
        self.state.actions.append(act)
        self.save()
        return act

    def decide_action(self, act_id: str, decision: str, reason: str = "") -> ActionProposal:
        """The host's answer to a verdict. BLOCK can only be deferred or rejected; proceeding on WARN needs a reason."""
        assert decision in DECISIONS, decision
        act = self.get_action(act_id)
        if act.verdict == "BLOCK" and decision == "proceed":
            raise DecisionRejected(f"{act_id} is BLOCK; it can only be deferred or rejected")
        if act.verdict == "WARN" and decision == "proceed" and not reason.strip():
            raise DecisionRejected(f"{act_id} is WARN; proceeding needs a reason")
        act.host_decision, act.decision_reason = decision, reason or None
        self.save()
        return act

    # --- Execution + Post-action Review --------------------------------------------
    def record_execution(self, act_id: str, executed: bool, summary: str, changed_files=(), tests=(),
                         observations=(), errors=()) -> ExecutionRecord:
        """tests: [{name, result: pass|fail|skip}]. Recorded even when it breaks the verdict; review flags that."""
        act = self.get_action(act_id)
        if not executed and changed_files:
            raise ValueError("a not-executed record cannot have changed files")
        if bad := [t for t in tests if t.get("result") not in ("pass", "fail", "skip")]:
            raise ValueError(f"test result must be pass|fail|skip: {bad}")
        ex = ExecutionRecord(self._next_id("EX"), act_id, act.host_decision, executed, summary, list(changed_files),
                             list(tests), list(observations), list(errors))
        self.state.executions.append(ex)
        self.save()
        return ex

    def review_execution(self, ex_id: str, intent_ids: list[str] | None = None) -> PostReview:
        """intent_ids: optional assumption/question ids the review should look at; only applicable ones are kept."""
        ex = next((x for x in self.state.executions if x.id == ex_id), None)
        if not ex:
            raise KeyError(ex_id)
        act = self.get_action(ex.action_id)
        step = self._step(act.task_id, act.plan_step)
        checks = {c.id: c for c in self.checks(act.task_id)}
        checks |= {c.id: c for c in map(self._find_check, step["basis"] if step else []) if c}
        ai = self.get_applicable_intent(act.task_id)
        notes = [i for i in ai["assumptions"] + ai["open_questions"] if intent_ids is None or i.id in intent_ids]
        facts = {}
        if ex.executed or ex.observations or ex.errors:  # defer / reject with nothing to say needs no judge
            facts = self.judge.analyze_execution(self._review_context(act, ex, step, checks, notes),
                                                 "\n".join(
                [f"executed: {ex.executed}", f"summary: {ex.summary}",
                 f"changed files: {', '.join(ex.changed_files) or '(none)'}",
                 "tests: " + (", ".join(f"{t['name']}={t['result']}" for t in ex.tests) or "(none)")]
                + [f"observation: {o}" for o in ex.observations] + [f"error: {e}" for e in ex.errors]))
        r = review.review(verdict=act.verdict, decision=ex.host_decision, step=step, executed=ex.executed,
                          changed_files=ex.changed_files, tests=ex.tests, errors=ex.errors, facts=facts,
                          check_ids=set(checks), assumption_ids={i.id for i in notes if i.kind == "assumption"})
        rid = self._next_id("REV")
        issues = [ResearchIssue(self._next_id("RI"), i["type"], i["note"], i["source_check_id"], rid)
                  for i in r.pop("issues")]
        self.state.issues += issues
        rev = PostReview(rid, ex.id, act.id, facts, research_issues=[i.id for i in issues], **r)
        self.state.reviews.append(rev)
        self.save()
        return rev

    # --- Evidence anchors (M3.1) ----------------------------------------------------
    def capture_source(self, url: str, title: str = "") -> EvidenceSource:
        """Pablo fetches the page itself; the host never supplies the text. Same URL + same hash -> same SRC."""
        try:
            html = self.fetch(url)
        except (OSError, http.client.HTTPException) as e:
            raise ValueError(f"fetch failed for {url}: {e}") from e
        text, page_title = evidence.normalize(html)
        btext, disp = evidence.display(html)
        h = evidence.content_hash(text)
        old = next((x for x in self.state.sources if x.locator == url and x.version["content_hash"] == h), None)
        if old:
            if btext == text and self.snapshot_display(old) is None:  # backfill for sources captured before M3.2.1
                self._write_snapshot(_display_path(old), json.dumps(disp))
            return old
        sid = self._next_id("SRC")
        src = EvidenceSource(sid, "web", title or page_title or url, url, {"content_hash": h}, f"sources/{sid}.txt")
        self._write_snapshot(src.snapshot, text)
        if btext == text:  # display structure is optional; the viewer falls back to plain text
            self._write_snapshot(_display_path(src), json.dumps(disp))
        self.state.sources.append(src)
        self.save()
        return src

    def capture_pdf(self, path: str, title: str = "") -> EvidenceSource:
        """M3.3: a local PDF. The bytes are copied into the state dir (the version the anchors point at); the
        snapshot is its pypdf page text joined by \f. Same path + same bytes -> same SRC."""
        path = os.path.abspath(path)
        with open(path, "rb") as f:
            data = f.read()
        h = pdf.content_hash(data)
        old = next((x for x in self.state.sources if x.locator == path and x.version["content_hash"] == h), None)
        if old:
            return old
        sid = self._next_id("SRC")
        src = EvidenceSource(sid, "pdf", title or os.path.splitext(os.path.basename(path))[0], path,
                             {"content_hash": h}, f"sources/{sid}.txt")
        self._write_snapshot(src.snapshot, "\f".join(pdf.pages(data)))
        self._write_snapshot(_pdf_path(src), data)
        self.state.sources.append(src)
        self.save()
        return src

    def add_anchor(self, src_id: str, exact: str, near: str = "", page: int | None = None) -> EvidenceAnchor:
        """Raises evidence.AnchorRejected if the quote is missing or ambiguous in the captured version.
        PDF sources: page narrows the search (near is for web pages)."""
        src = self.get_source(src_id)
        text = self.snapshot_text(src)
        if src.kind == "pdf":
            quote, selector = pdf.anchor(text.split("\f"), exact, page)
        else:
            start, end = evidence.locate(text, exact, near)
            quote, selector = evidence.context(text, start, end), {"type": "web_text", "start": start, "end": end}
        a = EvidenceAnchor(self._next_id("E"), src.id, quote, selector)
        self.state.anchors.append(a)
        self.save()
        return a

    def link_evidence(self, e_id: str, target_id: str, relation: str, note: str = "") -> EvidenceLink:
        if relation not in RELATIONS:
            raise ValueError(f"relation must be one of {RELATIONS}")
        self.get_anchor(e_id)
        if not self._known(target_id):
            raise KeyError(target_id)
        old = next((x for x in self.state.links
                    if (x.evidence_id, x.target_id, x.relation) == (e_id, target_id, relation)), None)
        if old:
            return old
        link = EvidenceLink(self._next_id("EL"), e_id, target_id, relation, note)
        self.state.links.append(link)
        self.save()
        return link

    def ask(self, task_id: str, question: str, src_id: str | None = None) -> tuple[SourceCheck, list[dict]]:
        """M3.3: answer a question from a captured PDF (default: the latest one). The judge picks the quotes; Pablo
        anchors each one in the captured text, drops the ones it cannot find once, renumbers the [n] markers, and
        stores the answer as a completed check whose supports links are in citation order. -> (check, dropped)"""
        src = self.get_source(src_id) if src_id else next((x for x in reversed(self.state.sources) if x.kind == "pdf"), None)
        if not src or src.kind != "pdf":
            raise KeyError("no captured PDF to answer from")
        r = self.judge.answer_from_pdf(question, self.snapshot_text(src).split("\f"))
        kept, dropped, new = [], [], {}
        for c in sorted(r["citations"], key=lambda c: c["n"]):
            try:
                try:
                    a = self.add_anchor(src.id, c["quote"], page=c["page"])
                except evidence.AnchorRejected:  # wrong page from the judge: unique anywhere is still exact
                    a = self.add_anchor(src.id, c["quote"])
            except evidence.AnchorRejected as e:
                dropped.append({**c, "why": str(e)})
                continue
            kept.append((a, c["role"]))
            new[c["n"]] = len(kept)
        answer = re.sub(r"\[(\d+(?:\s*,\s*\d+)+)\]", lambda m: "".join(f"[{x.strip()}]" for x in m[1].split(",")),
                        r["answer"])
        answer = re.sub(r"\s?\[(\d+)\]", lambda m: f"[{new[int(m[1])]}]" if int(m[1]) in new else "", answer)
        sc = self.add_check(task_id, question, "USEFUL")
        self.complete_check(sc.id, "VERIFIED" if kept and not dropped else "PARTIALLY_VERIFIED", answer,
                            [{"tier": 4, "type": "pdf", "title": src.title, "url": src.locator,
                              "supports": [a.id for a, _ in kept]}],
                            None if kept and not dropped else "budget_exhausted")
        for a, role in kept:
            self.link_evidence(a.id, sc.id, "supports", role)
        return sc, dropped

    def resolve_anchor(self, e_id: str) -> EvidenceAnchor:
        """Re-fetch the live source and find the anchor in it. Never moves the anchor; records where it is now."""
        a = self.get_anchor(e_id)
        src = self.get_source(a.source_id)
        try:
            if src.kind == "pdf":  # the file at the captured path, as it is now
                with open(src.locator, "rb") as f:
                    r = pdf.resolve(a.quote, a.selector, src.version["content_hash"], f.read())
            else:
                text, _ = evidence.normalize(self.fetch(src.locator))
                r = evidence.resolve(a.quote, a.selector, src.version["content_hash"], text)
        except (OSError, http.client.HTTPException) as e:
            r = {"status": "UNRESOLVED", "reason": "fetch_failed", "hash_changed": None, "start": None, "end": None,
                 "content_hash": None, "error": str(e)}
        a.status, a.resolution = r["status"], {**r, "at": now()}
        self.save()
        return a

    def get_source(self, src_id: str) -> EvidenceSource:
        src = next((x for x in self.state.sources if x.id == src_id), None)
        if not src:
            raise KeyError(src_id)
        return src

    def get_anchor(self, e_id: str) -> EvidenceAnchor:
        a = next((x for x in self.state.anchors if x.id == e_id), None)
        if not a:
            raise KeyError(e_id)
        return a

    def evidence_for(self, target_id: str) -> list[tuple[EvidenceLink, EvidenceAnchor]]:
        return [(x, self.get_anchor(x.evidence_id)) for x in self.state.links if x.target_id == target_id]

    def snapshot_text(self, src: EvidenceSource) -> str:
        if not self.path:
            return self._snapshots[src.snapshot]
        with open(os.path.join(os.path.dirname(self.path), src.snapshot), encoding="utf-8") as f:
            return f.read()

    def snapshot_display(self, src: EvidenceSource) -> dict | None:
        """Display-only {"blocks", "code"} (M3.2.1). Not evidence identity; None if never captured."""
        rel = _display_path(src)
        if not self.path:
            raw = self._snapshots.get(rel)
        else:
            p = os.path.join(os.path.dirname(self.path), rel)
            raw = open(p, encoding="utf-8").read() if os.path.exists(p) else None
        return json.loads(raw) if raw else None

    def snapshot_pdf(self, src: EvidenceSource) -> bytes:
        if not self.path:
            return self._snapshots[_pdf_path(src)]
        with open(os.path.join(os.path.dirname(self.path), _pdf_path(src)), "rb") as f:
            return f.read()

    def _write_snapshot(self, rel: str, text: str | bytes) -> None:
        if not self.path:
            self._snapshots[rel] = text
            return
        p = os.path.join(os.path.dirname(self.path), rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if isinstance(text, bytes):
            with open(p, "wb") as f:
                f.write(text)
            return
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)

    def _known(self, any_id: str) -> bool:
        st = self.state
        return (any(x.id == any_id for x in [*st.tasks, *st.checks, *st.plans, *st.actions, *st.executions,
                                              *st.reviews, *st.issues, *st.anchors])
                or any(step["id"] == any_id for p in st.plans for step in p.steps)
                or self.intent.get_item(any_id) is not None)

    def _review_context(self, act, ex, step, checks, notes) -> str:
        decision = (ex.host_decision or "(none)") + (f" - {act.decision_reason}" if act.decision_reason else "")
        return "\n".join(
            [f"PROPOSED ACTION: {act.description}", f"JUSTIFICATION: {act.justification or '(none)'}",
             f"GUARD VERDICT: {act.verdict} " + "; ".join(f"{r['rule']} {r['reason']}" for r in act.reasons),
             f"HOST DECISION: {decision}", f"PLAN STEP: {step['action'] if step else '(none)'}", "SOURCE CHECKS:"]
            + [f"{c.id} [{c.outcome or c.research_state}] {c.requirement} -> {c.conclusion}" for c in checks.values()]
            + ["USER INTENT:", self._intent_text(act.task_id), "ASSUMPTIONS / OPEN QUESTIONS:"]
            + [f"{i.id} [{i.kind}] {i.statement}" for i in notes])

    # --- queries -------------------------------------------------------------------
    def checks(self, task_id: str) -> list[SourceCheck]:
        """The task's own checks plus the earlier checks it reuses."""
        reused = self.get_task(task_id).reused
        return [c for c in self.state.checks if c.task_id == task_id or c.id in reused]

    def get_check(self, sc_id: str) -> SourceCheck:
        c = self._find_check(sc_id)
        if not c:
            raise KeyError(sc_id)
        return c

    def plans(self, task_id: str) -> list[Plan]:
        return [p for p in self.state.plans if p.task_id == task_id and p.status == "active"]

    def actions(self, task_id: str) -> list[ActionProposal]:
        return [a for a in self.state.actions if a.task_id == task_id]

    def get_action(self, act_id: str) -> ActionProposal:
        act = next((a for a in self.state.actions if a.id == act_id), None)
        if not act:
            raise KeyError(act_id)
        return act

    def executions(self, act_id: str) -> list[ExecutionRecord]:
        return [x for x in self.state.executions if x.action_id == act_id]

    def reviews(self, ex_id: str) -> list[PostReview]:
        return [r for r in self.state.reviews if r.execution_id == ex_id]

    def issues(self, task_id: str) -> list[ResearchIssue]:
        revs = {r.id for a in self.actions(task_id) for x in self.executions(a.id) for r in self.reviews(x.id)}
        return [i for i in self.state.issues if i.review_id in revs]

    # --- helpers -------------------------------------------------------------------
    def _find_check(self, sc_id: str) -> SourceCheck | None:
        return next((c for c in self.state.checks if c.id == sc_id), None)

    def get_task(self, task_id: str) -> Task:
        t = next((t for t in self.state.tasks if t.id == task_id), None)
        if not t:
            raise KeyError(task_id)
        return t

    def _step(self, task_id: str, step_id: str | None) -> dict | None:
        return next((s for p in self.plans(task_id) for s in p.steps if s["id"] == step_id), None)

    def intent_applies(self, task_id: str, x) -> bool:
        """The one rule for "intent of this task" (judge, Guard, review and viewer all use it).
        Explicitly referenced by this task's checks/actions: yes. Scope comes from the Candidate that created it.
        project: every task. task/action: only if said while this task was the current one (said before any task:
        none). No candidate (agent assumptions / open questions / decisions): the task they were made in.
        A task-local item that conflicts with another item overrides it in that task only."""
        return self._in_scope(task_id, x) and x.id not in self._overridden(task_id)

    def _overridden(self, task_id: str) -> set:
        eng = self.intent
        return {c.features["relation"]["target_id"] for c in eng.get_current_intent().candidates
                if c.status == "committed" and c.features["relation"]["type"] == "conflict"
                and c.features.get("scope") in ("task", "action")
                and (i := eng.get_item(c.item_id or "")) is not None and i.status == "active" and self._in_scope(task_id, i)}

    def _in_scope(self, task_id: str, x) -> bool:
        if x.id in self._intent_refs(task_id):
            return True
        if hasattr(x, "features"):
            scope = x.features.get("scope", "project")
        else:
            c = next((c for c in self.intent.get_current_intent().candidates if c.item_id == x.id), None)
            scope = (c.features.get("scope", "project") if c
                     else "task" if x.kind in ("assumption", "open_question", "decision") else "project")
        if scope not in ("task", "action"):
            return True
        # ponytail: time window, breaks if tasks overlap; backlog: store scope_ref/task_id on the intent
        t = self.get_task(task_id)
        end = min((o.created_at for o in self.state.tasks if o.created_at > t.created_at), default=None)
        return t.created_at <= x.created_at and (end is None or x.created_at < end)

    def _intent_refs(self, task_id: str) -> set:
        refs = {r for c in self.checks(task_id) for r in c.intent_refs}
        refs |= {b for p in self.plans(task_id) if p.status == "active" for st in p.steps for b in st["basis"]}
        return refs | {x.get("intent_id") for a in self.actions(task_id)
                       for x in (a.analysis or {}).get("intent_conflicts", [])}

    def task_intent(self, task_id: str, xs: list) -> list:
        return [x for x in xs if self.intent_applies(task_id, x)]

    def get_applicable_intent(self, task_id: str) -> dict:
        """The current-task intent: task goal + applicable items. Judge, Guard, review and viewer all read this."""
        eng, f = self.intent, lambda xs: self.task_intent(task_id, xs)
        ai = {"task": self.get_task(task_id), "goals": f(eng.get_active_goals()),
                "constraints": f(eng.get_active_constraints()), "success": f(eng.get_success_criteria()),
                "decisions": f(eng.get_decisions()),
                "assumptions": f(eng.get_assumptions()), "open_questions": f(eng.get_open_questions()),
                "pending": f(eng.get_pending_candidates()),
                "other": [i.id for i in eng.get_current_intent().items
                          if i.status == "active" and not self.intent_applies(task_id, i)]}
        ai["questions"] = ai["open_questions"] + [a for a in ai["assumptions"] if a.status == "unverified"]
        return ai

    def _intent_text(self, task_id: str) -> str:
        ai = self.get_applicable_intent(task_id)
        return "\n".join([f"{ai['task'].id} [task goal] {ai['task'].text}"]
                         + [f"{i.id} [{i.kind}{'/' + i.strength if i.strength else ''}] {i.statement}"
                            for i in ai["goals"] + ai["constraints"]])

    def _next_id(self, prefix: str) -> str:
        n = self.state.counters.get(prefix, 0) + 1
        self.state.counters[prefix] = n
        return f"{prefix}{n}"


MARK = {"VERIFIED": "✓", "PARTIALLY_VERIFIED": "△", "NOT_FOUND": "?", "CONFLICTING": "!"}


def _display_path(src: EvidenceSource) -> str:
    return src.snapshot.removesuffix(".txt") + ".display.json"


def _pdf_path(src: EvidenceSource) -> str:
    return src.snapshot.removesuffix(".txt") + ".pdf"


def render_task(s: PabloSkill, task_id: str) -> str:
    t = s.get_task(task_id)
    out = [f"# {t.id} {t.text}  (source requirement: {s.necessity(task_id)})", "\n## Source checks"]
    for c in s.checks(task_id):
        mark = MARK.get(c.outcome, "-" if c.research_state == "waived" else "…")
        out.append(f"- {mark} [{c.id}] {c.requirement} ({c.necessity}, {c.research_state}"
                   f"{', ' + c.outcome if c.outcome else ''}{', ' + c.stop_reason if c.stop_reason else ''}"
                   f"{', reused from ' + c.task_id if c.task_id != task_id else ''})")
        if c.why:
            out.append(f"    why: {c.why}")
        if c.waive_reason:
            out.append(f"    waived by {c.waived_by}: {c.waive_reason}")
        out += [f"    searched T{x['tier']} {x['target']}: {x['result']}" for x in c.searched]
        out += [f"    source T{x['tier']} {x['title']} {x.get('url', '')}" for x in c.sources]
        out += [f"    rejected: {r}" for r in c.rejections]
        out += [f"    evidence {x.relation} [{a.id} {a.status}] \"{a.quote['exact']}\" ({a.source_id})"
                for x, a in s.evidence_for(c.id)]
        if c.conclusion:
            out.append(f"    → {c.conclusion}")
    for p in s.plans(task_id):
        out.append(f"\n## Plan {p.id}")
        out += [f"- [{st['id']}] {st['action']}  ← {', '.join(st['basis'])}" for st in p.steps]
        out += [f"- ? unverified {u}" for u in p.unverified]
    out.append("\n## Actions")
    for a in s.actions(task_id):
        out.append(f"- [{a.id}] {a.verdict}  {a.description} (step {a.plan_step or '-'})")
        out += [f"    {r['rule']} {r['verdict']}: {r['reason']}" for r in a.reasons]
        if a.host_decision:
            out.append(f"    host: {a.host_decision}{' - ' + a.decision_reason if a.decision_reason else ''}")
        for x in s.executions(a.id):
            out.append(f"    [{x.id}] {'executed' if x.executed else 'not executed'}: {x.summary}"
                       f"{' (' + ', '.join(x.changed_files) + ')' if x.changed_files else ''}")
            for r in s.reviews(x.id):
                out.append(f"      [{r.id}] {r.action_alignment}, step {r.plan_step_status or '-'}")
                out += [f"        deviation {d['kind']}: {d['note']}" for d in r.deviations]
                out += [f"        fact: {f['statement']}" for f in r.new_facts]
                out += [f"        propose {p['api']} {p['args']}" for p in r.intent_update_proposals]
                out += [f"        propose {p['kind']} {p['target']}: {p['note']}" for p in r.plan_update_proposals]
    issues = s.issues(task_id)
    if issues:
        out.append("\n## Research issues")
        out += [f"- [{i.id}] {i.type} {i.source_check_id or '-'}: {i.note} ({i.review_id})" for i in issues]
    return "\n".join(out)


def render_evidence(s: PabloSkill, e_id: str) -> str:
    a = s.get_anchor(e_id)
    src = s.get_source(a.source_id)
    q, r = a.quote, a.resolution or {}
    out = [f"[{a.id}] {a.status}{' (' + r['reason'] + ')' if r.get('reason') else ''}",
           f"  source {src.id}: {src.title} <{src.locator}>  captured {src.captured_at}",
           f"  ...{q['prefix']}[[{q['exact']}]]{q['suffix']}...",
           f"  at {'p.' + str(a.selector['page']) + ' ' if 'page' in a.selector else ''}{a.selector['start']}-{a.selector['end']} in {src.version['content_hash'][:19]}"]
    if r:
        out.append(f"  last resolve {r['at']}: hash_changed={r['hash_changed']}"
                   f"{', now at ' + str(r['start']) if r.get('start') is not None else ''}")
    out += [f"  {x.relation} -> {x.target_id}{': ' + x.note if x.note else ''}"
            for x in s.state.links if x.evidence_id == a.id]
    return "\n".join(out)
