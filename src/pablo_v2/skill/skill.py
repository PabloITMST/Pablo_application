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

import hashlib
import http.client
import json
import os
import re
import unicodedata

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


class TooMuchText(ValueError):
    """ask over several papers whose text is more than one question can carry: the user picks fewer."""


ASK_PAGES, ASK_CHARS = 40, 250_000  # C1: per paper, and in all, for one question over several papers
COMPARE_PAGES = 40  # C3: one paper's pages for its row of a comparison table
COLUMNS = ["데이터셋", "평가 지표", "주요 결과", "효율", "한계"]
# A3: the research-integrity criteria a reproduction task starts with (desktop "논문 재현 작업"). 0.8 ④: removing one
# needs a reason, so whoever reads the audit or the report sees why it was not checked.
REPRO_CRITERIA = ("평가(test) 데이터는 학습, 튜닝, 모델 선택에 절대 쓰지 마.", "논문에 적힌 설정값은 근거 없이 바꾸지 마.",
                  "결과 수치는 직접 써 넣지 말고 실행한 결과에서만 가져와.")


# A2 (0.8): a paper's value in a text, with the same rule as desktop/where.js (tests run both on one table): numbers by
# value ("1,000" = 1000, "63.70%" = 63.7, never inside "2wiki" or "v2"), words case-insensitive and ignoring spaces.
_NUM = re.compile(r"(?<![A-Za-z0-9_.])\d+(?:,\d{3})*(?:\.\d+)?(?:e[-+]?\d+)?(?![A-Za-z0-9_])", re.I)
_ONE_NUM = re.compile(r"^[~≈]?\s*(\d+(?:,\d{3})*(?:\.\d+)?(?:e[-+]?\d+)?)\s*%?$", re.I)


def _number(v: str) -> float | None:
    m = _ONE_NUM.match(str(v).strip())
    return float(m[1].replace(",", "")) if m else None


def _norm(s: str) -> str:  # the twin of desktop/where.js norm(): quote style is not a different text
    return re.sub(r"\s+", " ", re.sub(r"[‘’“”']", '"', unicodedata.normalize("NFKC", str(s or "")).lower())).strip()


def checkable(value: str) -> bool:
    """A value text has to spell out: a number ("5", "1,000", "63.70%") or one identifier with a digit ("GPT-4o-mini").
    A concept ("punctuation", "Personalized PageRank") is implemented, not written (0.8 bench: 29 false warnings)."""
    v = str(value or "").strip()
    return bool(v) and (_number(v) is not None or (len(v) <= 60 and re.fullmatch(r"\S+", v) is not None
                                                     and re.search(r"\d", v) is not None and re.search(r"[A-Za-z]", v) is not None))


def has_value(text: str, value: str) -> bool:
    nums = [float(m[0].replace(",", "")) for m in _NUM.finditer(str(text or ""))]
    same = lambda a, b: abs(a - b) <= 1e-9 * max(1, abs(a))  # noqa: E731
    flat = _norm(text).replace(" ", "")
    n = _number(value)
    if n is not None:
        return any(same(x, n) for x in nums)
    ts = [t for t in re.split(r"[\s()\[\]]+", _norm(value)) if t]
    return bool(ts) and all(any(same(x, _number(t)) for x in nums) if _number(t) is not None else t in flat for t in ts)


class PabloSkill:
    def __init__(self, intent: IntentEngine, judge=None, state: SkillState | None = None, path: str | None = None):
        self.intent, self.judge, self.state, self.path = intent, judge, state or SkillState(), path
        self.fetch = evidence.fetch  # tests swap in a fake
        self._snapshots = {}  # in-memory snapshots when there is no state path
        self.spec_diff = None  # what the last spec() changed against the previous extraction of the same paper

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
                       justification: str | None = None, rewrites: list[dict] = ()) -> ActionProposal:
        self.get_task(task_id)
        step = self._step(task_id, plan_step)
        constraints = {i.id: (i.strength or "soft", i.statement) for i in self.get_applicable_intent(task_id)["constraints"]}
        constraints |= {k: (v, guard.SYSTEM_POLICIES[k]) for k, v in guard.JUDGED_POLICIES.items()}
        basis = set(step["basis"]) if step else set()
        # a comparison table compares, it does not bind; ⑦ nor does a condition the whole task differs from on purpose.
        # One differed from in separate runs only stays a fact: the Guard decides by what the action touches.
        # ⑥ a description (fact) or another experiment of the paper (scope) is no rule for the work either
        sources = {c.id: c for c in self.checks(task_id) if not c.matrix and scope_of(c) != "task" and not aside(c)}
        runs = [c.id for c in sources.values() if scope_of(c) == "runs"]
        sources |= {c.id: c for c in map(self._find_check, basis) if c}
        done = [c for c in sources.values() if c.research_state == "completed"]
        said = (description, justification, step and step["action"],
                "\n".join(f"{k} [{st}] {text}" for k, (st, text) in constraints.items()),
                "\n".join(f"{'*' if c.id in basis else ''}{c.id} [{c.outcome}] {c.requirement} -> {c.conclusion}"
                          for c in done))
        # the judge already answered exactly this (same action, step, criteria and facts): its facts are reused, the
        # verdict is decided again by the rules. Saves a model call on repeated reads; never skips the Guard.
        key = hashlib.sha256(json.dumps(said, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]
        prev = next((a for a in reversed(self.state.actions) if a.analysis_key == key and a.analysis), None)
        analysis = dict(prev.analysis) if prev else self.judge.analyze_action(*said)
        cited = (analysis.get("justification") or {}).get("supported_by", [])
        verdict, reasons = guard.decide(
            pending_required=self.pending_required(task_id), step=step,
            unverified=self._unverified(step) if step else [], analysis=analysis,
            constraints={k: st for k, (st, _) in constraints.items()},
            sources={c.id: c.outcome for c in sources.values()},
            valid_support=[c.id for c in done if c.id in cited and c.outcome in guard.SUPPORTING_OUTCOMES],
            rewrites=list(rewrites), separate=runs, edits_existing=edits_existing(description), reads=reads_only(description))
        act = ActionProposal(self._next_id("ACT"), task_id, description, step and step["id"], justification,
                             analysis, verdict, reasons, analysis_key=key, analysis_from=prev and prev.id)
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

    def capture_pdf(self, path: str, title: str = "", arxiv: str | None = None) -> EvidenceSource:
        """M3.3: a local PDF. The bytes are copied into the state dir (the version the anchors point at); the
        snapshot is its pypdf page text joined by \f. Same path + same bytes -> same SRC.
        C2 arxiv (the id it was downloaded as): the title comes from the PDF itself, the version from arXiv's stamp
        on page 1 (version = {content_hash, arxiv, arxiv_version})."""
        path = os.path.abspath(path)
        with open(path, "rb") as f:
            data = f.read()
        h = pdf.content_hash(data)
        old = next((x for x in self.state.sources if x.locator == path and x.version["content_hash"] == h), None)
        if old:
            return old
        ps, version = pdf.pages(data), {"content_hash": h}
        if arxiv:
            m = pdf.meta(data, ps)
            title = title or m["short"] or f"arXiv {arxiv}"
            version.update(arxiv=m["arxiv"] or arxiv, arxiv_version=m["version"])
        sid = self._next_id("SRC")
        src = EvidenceSource(sid, "pdf", title or os.path.splitext(os.path.basename(path))[0], path,
                             version, f"sources/{sid}.txt")
        self._write_snapshot(src.snapshot, "\f".join(ps))
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

    def _pdf(self, src_id: str | None) -> EvidenceSource:
        src = self.get_source(src_id) if src_id else next((x for x in reversed(self.state.sources) if x.kind == "pdf"), None)
        if not src or src.kind != "pdf":
            raise KeyError("no captured PDF to answer from")
        return src

    def _doc(self, src_id: str | None) -> EvidenceSource:
        """D1: what a question can be asked of: a captured PDF or web page (default: the latest PDF)."""
        src = self.get_source(src_id) if src_id else next((x for x in reversed(self.state.sources) if x.kind == "pdf"), None)
        if not src or src.kind not in ("pdf", "web"):
            raise KeyError("no captured PDF or web page to answer from")
        return src

    def ask(self, task_id: str, question: str, src_id: str | list[str] | None = None) -> tuple[SourceCheck, list[dict]]:
        """M3.3: answer a question from a captured PDF (default: the latest one). The judge picks the quotes; Pablo
        anchors each one in the captured text, drops the ones it cannot find once, renumbers the [n] markers, and
        stores the answer as a completed check whose supports links are in citation order. -> (check, dropped)
        C1: several PDFs (a list of ids) are asked together; each quote is anchored in the paper it names, on its page.
        Too much text for one question (ASK_PAGES a paper, ASK_CHARS in all) raises TooMuchText: ask fewer sources.
        D1: a web page is a source too. It has no pages: the judge gives the words next to a quote (near) and Pablo
        anchors it in the captured text (evidence.locate), the occurrence near those words when the quote repeats.
        Pablo cannot tell how authoritative a page the user picked is (tier 5): an answer resting on web quotes alone
        is PARTIALLY_VERIFIED (R01), one with a paper's quote can be VERIFIED."""
        ids = [src_id] if isinstance(src_id, str) or src_id is None else list(dict.fromkeys(src_id))
        srcs = [self._doc(i) for i in ids]
        if len(srcs) == 1 and srcs[0].kind == "pdf":
            src = srcs[0]
            r = self.judge.answer_from_pdf(question, self.snapshot_text(src).split("\f"))
            of = {}
        else:
            papers = [{"label": chr(65 + i), "title": x.title, "kind": x.kind,
                       "pages": self.snapshot_text(x).split("\f")[:ASK_PAGES] if x.kind == "pdf" else [self.snapshot_text(x)]}
                      for i, x in enumerate(srcs)]
            size = sum(len(p) for x in papers for p in x["pages"])
            if size > ASK_CHARS:
                raise TooMuchText(f"자료 {len(srcs)}개를 한 번에 묻기에는 본문이 너무 깁니다({size:,}자, 상한 {ASK_CHARS:,}자). "
                                  "물어볼 자료를 골라 주세요.")
            r = self.judge.answer_from_sources(question, papers)
            of = {x["label"]: s for x, s in zip(papers, srcs)}
        kept, dropped, new = [], [], {}
        for c in sorted(r["citations"], key=lambda c: c["n"]):
            src = of.get(str(c.get("paper", "")).strip().upper()[:1]) if of else srcs[0]
            try:
                if not src:
                    raise evidence.AnchorRejected(f"no source {c.get('paper')!r} among {sorted(of)}")
                if src.kind == "web":
                    try:
                        a = self.add_anchor(src.id, c["quote"], near=c.get("near") or "")
                    except evidence.AnchorRejected:  # near not where the judge said: a quote unique on the page still is
                        a = self.add_anchor(src.id, c["quote"])
                else:
                    try:
                        a = self.add_anchor(src.id, c["quote"], page=c["page"])
                    except evidence.AnchorRejected:  # wrong page from the judge: unique anywhere in that paper is still exact
                        a = self.add_anchor(src.id, c["quote"])
            except evidence.AnchorRejected as e:
                dropped.append({**c, "why": str(e)})
                continue
            kept.append((a, c["role"], src))
            new[c["n"]] = len(kept)
        answer = re.sub(r"\[(\d+(?:\s*,\s*\d+)+)\]", lambda m: "".join(f"[{x.strip()}]" for x in m[1].split(",")),
                        r["answer"])
        answer = re.sub(r"\s?\[(\d+)\]", lambda m: f"[{new[int(m[1])]}]" if int(m[1]) in new else "", answer)
        sc = self.add_check(task_id, question, "USEFUL")
        whole = kept and not dropped and any(x.kind == "pdf" for *_, x in kept)
        self.complete_check(sc.id, "VERIFIED" if whole else "PARTIALLY_VERIFIED", answer,
                            [{"tier": 4 if s.kind == "pdf" else 5, "type": s.kind, "title": s.title, "url": s.locator,
                              "supports": [a.id for a, _, x in kept if x is s]}
                             for s in [s for s in srcs if any(x is s for *_, x in kept)] or srcs],
                            None if whole else "budget_exhausted")
        for a, role, _ in kept:
            self.link_evidence(a.id, sc.id, "supports", role)
        return sc, dropped

    def spec(self, task_id: str, src_id: str | None = None) -> tuple[list[SourceCheck], list[SourceCheck], list[dict]]:
        """The paper's reproduction conditions (data, split, model, hyperparameters, metrics, baselines, results,
        evaluation rules), each a completed check whose evidence is its verbatim quote anchored on its page: the Guard
        reads them like any verified fact (an action against one is S01), the agent gets them in its brief.
        A quote Pablo cannot find is dropped, never kept unanchored. Settings the paper does not state become pending
        checks ("decide, and say on what basis"). Extracting again replaces the task's earlier conditions.
        C1: a task with several papers reproduces one of them (the 주 논문). Extracting from a paper replaces the
        conditions of every paper of the task, so the Guard, the brief and 재현 점검 never hold two papers' settings
        at once (a baseline's top-k would block the reproduction's). The old ones stay, waived.
        -> (stated, missing, dropped)"""
        src = self.get_source(src_id) if src_id else next((x for x in reversed(self.state.sources) if x.kind == "pdf"), None)
        if not src or src.kind != "pdf":
            raise KeyError("no captured PDF to read the conditions from")
        self.get_task(task_id)
        r = self.judge.extract_spec(self.snapshot_text(src).split("\f"))
        # 0.8 review: extracting the same paper again keeps what the user made of its conditions: one they added (⑩),
        # restored after a re-extraction (kept) or differ from on purpose (⑦) stays; one they took out stays out
        def own(c):
            return c.spec.get("source_id") == src.id and (c.spec.get("by") == "user" or c.spec.get("kept") or deviation(c))
        mine = [c for c in self.checks(task_id) if c.spec and c.task_id == task_id]
        kept = [c for c in mine if c.research_state != "waived" and own(c)]
        out = [c for c in mine if c.research_state == "waived" and c.waived_by == "user" and c.spec.get("source_id") == src.id]
        prev = [c for c in mine if c.research_state != "waived" and not own(c) and c.spec.get("source_id") == src.id
                and not c.spec.get("missing")]  # the previous extraction, to say what changed
        for c in mine:
            if c.research_state != "waived" and not own(c):
                c.research_state, c.waived_by = "waived", "pablo"
                c.waive_reason = "replaced by a new extraction" if c.spec.get("source_id") == src.id \
                    else f"replaced by the conditions of {src.id} ({src.title})"
        stated, missing, dropped, again, still_out = [], [], [], [], []
        for it in r["items"]:
            try:
                try:
                    a = self.add_anchor(src.id, it["quote"], page=it["page"])
                except evidence.AnchorRejected:  # wrong page: unique anywhere in the paper is still exact
                    a = self.add_anchor(src.id, it["quote"])
            except evidence.AnchorRejected as e:
                dropped.append({**it, "why": str(e)})
                continue
            hit = next((c for c in kept + out if not c.spec.get("missing") and self._same_condition(c, it["category"], it["value"], a)), None)
            if hit:  # the user's own version of it is there (or they took it out): not twice, not back
                (again if hit in kept else still_out).append(hit.id)
                self.state.anchors.remove(a)
                continue
            sc = self.add_check(task_id, it["statement"], "USEFUL")
            sc.spec = {"category": it["category"], "value": it["value"], "source_id": src.id}
            if it.get("kind") in SPEC_KINDS:  # ⑥ none (an answer from before) reads as setting
                # review: a baseline is another experiment of the paper (its scope), whatever kind the model gave it
                sc.spec["kind"] = "scope" if it["kind"] == "setting" and it["category"] == "baseline" else it["kind"]
            if header_missing(it["statement"], a.quote["exact"], sc.spec.get("kind")):
                sc.spec["header_missing"] = True  # review: a table row without its column names; the pairing is the model's guess
            if checkable(it["value"]) and not has_value(a.quote["exact"], it["value"]):
                sc.spec["value_in_quote"] = False  # the quote is anchored, the value the model read from it is not in it
            self.complete_check(sc.id, "VERIFIED", it["statement"] + " [1]",
                                [{"tier": 4, "type": "pdf", "title": src.title, "url": src.locator, "supports": [a.id]}])
            self.link_evidence(a.id, sc.id, "supports", it["category"])
            stated.append(sc)
        anchor = lambda c: next((x for _, x in self.evidence_for(c.id)), None)  # noqa: E731
        same = [p for p in prev if any(anchor(n) and self._same_condition(p, n.spec["category"], n.spec["value"], anchor(n)) for n in stated)]
        self.spec_diff = {"first": not prev, "before": len(prev), "same": len(same),
                          "new": [n.id for n in stated if not any(anchor(n) and self._same_condition(p, n.spec["category"], n.spec["value"], anchor(n)) for p in prev)],
                          "gone": [p.id for p in prev if p not in same], "kept": [c.id for c in kept],
                          "again": sorted(set(again)), "out": sorted(set(still_out))}
        for it in r["missing"]:
            sc = self.add_check(task_id, it["statement"], "USEFUL",
                                "논문에 없는 설정: 정하면 그 근거(저자 저장소, 관례, 실험)를 남긴다")
            sc.spec = {"category": it["category"], "value": "", "source_id": src.id, "missing": True}
            missing.append(sc)
        self.save()
        return stated, missing, dropped

    # --- 0.8 ⑩ the user's own hand on the conditions: a sentence picked in the PDF, a condition taken out (with why) ----
    def add_spec(self, task_id: str, src_id: str, quote: str, page: int | None, category: str, statement: str,
                 value: str = "") -> SourceCheck:
        """A condition the extraction missed: the sentence the user picked on a page of the paper, anchored like an
        extracted one (a quote Pablo cannot find there is refused, never kept unanchored). Only the paper whose
        conditions the task holds now: the Guard and the brief never mix two papers' settings."""
        src, statement, value = self._pdf(src_id), " ".join(statement.split()), " ".join(value.split())
        self.get_task(task_id)
        if category not in SPEC_LABEL or not statement or not quote.strip():
            raise ValueError("a condition needs its kind, what it says and the sentence it rests on")
        other = {c.spec["source_id"] for c in self.checks(task_id) if c.spec and c.research_state != "waived"} - {src.id}
        if other:
            raise ValueError(f"이 작업의 재현 조건은 {self.get_source(other.pop()).title}에서 뽑았습니다. 다른 논문의 조건은 "
                             "그 논문에서 재현 조건을 다시 뽑은 뒤에 더하세요.")
        try:
            try:
                a = self.add_anchor(src.id, quote, page=page)
            except evidence.AnchorRejected:  # the picked sentence runs onto the next page, or the page is off by one
                a = self.add_anchor(src.id, quote)
        except evidence.AnchorRejected as e:
            raise evidence.AnchorRejected(f"고른 문장을 논문에서 찾지 못했습니다 ({e}). 한 문장만 다시 골라 보세요.") from e
        sc = self.add_check(task_id, statement, "USEFUL")
        sc.spec = {"category": category, "value": value, "source_id": src.id, "by": "user", "at": now()}
        if checkable(value) and not has_value(a.quote["exact"], value):
            sc.spec["value_in_quote"] = False
        self.complete_check(sc.id, "VERIFIED", statement + " [1]",
                            [{"tier": 4, "type": "pdf", "title": src.title, "url": src.locator, "supports": [a.id]}])
        self.link_evidence(a.id, sc.id, "supports", category)
        self.save()
        return sc

    def drop_spec(self, sc_id: str, reason: str) -> SourceCheck:
        """A condition taken out by the user (extracted wrongly, not part of this reproduction): the Guard, the brief and
        재현 점검 stop holding it. Kept with why and when (spec["dropped"]: one span per removal), restorable."""
        sc = self._find_check(sc_id)
        if not sc or not sc.spec or sc.research_state == "waived":
            raise KeyError(f"no live condition {sc_id} to take out")
        if not reason.strip():
            raise ValueError("재현 조건을 빼는 이유를 적어야 합니다.")
        sc.research_state, sc.waived_by, sc.waive_reason = "waived", "user", reason.strip()
        sc.spec["dropped"] = sc.spec.get("dropped", []) + [{"from": now(), "to": None, "why": reason.strip()}]
        self.save()
        return sc

    def restore_spec(self, sc_id: str) -> SourceCheck:
        """A condition the user took out, back as it was; or (0.8 review) one the last extraction of the same paper did
        not find again, kept from then on like the user's own. Never over another paper's conditions extracted since."""
        sc = self._find_check(sc_id)
        replaced = bool(sc) and sc.waived_by == "pablo" and sc.waive_reason == "replaced by a new extraction"
        if not sc or not sc.spec or sc.research_state != "waived" or not (sc.waived_by == "user" or replaced):
            raise KeyError(f"no condition {sc_id} taken out by the user to restore")
        if {c.spec["source_id"] for c in self.checks(sc.task_id) if c.spec and c.research_state != "waived"} - {sc.spec["source_id"]}:
            raise ValueError("그 뒤로 다른 논문의 재현 조건을 뽑아서 되살리지 않습니다.")
        sc.research_state = "pending" if sc.spec.get("missing") else "completed"
        sc.waived_by = sc.waive_reason = None
        if replaced:
            sc.spec["kept"] = True
        else:
            sc.spec["dropped"][-1]["to"] = now()
        self.save()
        return sc

    def _same_condition(self, c, category: str, value: str, a) -> bool:
        """The same condition of the same paper: their quotes overlap on a page, or one kind with one value."""
        for _, b in self.evidence_for(c.id):
            if b.source_id == a.source_id and b.selector.get("page") == a.selector.get("page") \
                    and b.selector["start"] < a.selector["end"] and a.selector["start"] < b.selector["end"]:
                return True
        v = c.spec.get("value", "")
        return c.spec["category"] == category and checkable(v) and checkable(value) and has_value(v, value) and has_value(value, v)

    # --- 0.8 ⑦ an intended deviation: the user differs from the paper on purpose (ablation, hardware), with why -------
    def deviate_spec(self, sc_id: str, reason: str, scope: str = "runs") -> SourceCheck:
        """The paper's condition stays a fact (VERIFIED, cited) and the brief tells the agent it differs on purpose and
        why. One span per decision (spec["deviations"]: from, to, why, scope), so a report says when it held.
        scope (user decision, 10/14): "runs" (default) = an ablation: the base run stays as the paper says; a new file or
        a command may differ, an edit of an existing file is asked about (S07 WARN), and 재현 점검 still calls a
        different base run 다름. "task" = the whole task differs: the Guard no longer holds the work to it, and 재현 점검
        shows a difference as 의도한 차이. A span without scope (before 10/14) is "task"."""
        if scope not in ("runs", "task"):
            raise ValueError(f"scope is runs or task, not {scope}")
        sc = self._find_check(sc_id)
        if not sc or not sc.spec or sc.spec.get("missing") or sc.research_state != "completed":
            raise KeyError(f"no live condition {sc_id} to differ from")
        if deviation(sc):
            raise ValueError("이미 의도한 차이로 둔 조건입니다.")
        if not reason.strip():
            raise ValueError("의도한 차이로 두려면 이유를 적어야 합니다.")
        sc.spec["deviations"] = sc.spec.get("deviations", []) + [{"from": now(), "to": None, "why": reason.strip(), "scope": scope}]
        self.save()
        return sc

    def undeviate_spec(self, sc_id: str) -> SourceCheck:
        """Back to the paper: the Guard holds the work to this condition again."""
        sc = self._find_check(sc_id)
        if not sc or not sc.spec or not deviation(sc):
            raise KeyError(f"no intended deviation on {sc_id} to end")
        sc.spec["deviations"][-1]["to"] = now()
        self.save()
        return sc

    def compare(self, task_id: str, src_ids: list[str], columns: list[str] | None = None, into: str | None = None
                ) -> tuple[str, list[SourceCheck], list[dict]]:
        """C3: a table of the task's papers (rows) by columns (default COLUMNS). The judge fills one paper's row per
        call, the same columns each time and no other paper in view (no value crosses between rows, no paper is cut to
        fit). Each cell's quote is anchored on its page, or the cell stays empty: a value never stands without its place
        in the paper. A cell is a completed check with matrix {id, column, source_id} and its anchor, like a spec
        condition; it is not a fact the Guard enforces nor in the agent's brief (the table compares, it does not bind).
        -> (matrix id, cells, empty [{source_id, column, why}])"""
        self.get_task(task_id)
        srcs = [self._pdf(i) for i in dict.fromkeys(src_ids)]
        if len(srcs) < 2:
            raise ValueError("a comparison table needs two or more papers")
        columns = list(dict.fromkeys(c.strip() for c in (columns or COLUMNS) if c and c.strip()))[:8]
        if not columns:
            raise ValueError("a comparison table needs at least one column")
        if into:  # ⑧ review: one more column of a table that is there (one judge call per paper for that column only)
            have = {(c.matrix["source_id"], c.matrix["column"]) for c in self.checks(task_id) if c.matrix and c.matrix["id"] == into}
            if not any(c.matrix and c.matrix["id"] == into for c in self.checks(task_id)):
                raise KeyError(f"no table {into} in {task_id}")
            columns = [c for c in columns if not any(col == c for _, col in have)]
            if not columns:
                raise ValueError("그 열은 이미 표에 있습니다.")
        mid, cells, empty = into or self._next_id("M"), [], []
        for src in srcs:
            r = self.judge.compare_paper(columns, src.title, self.snapshot_text(src).split("\f")[:COMPARE_PAGES])
            row = {}
            for x in r["cells"]:
                row.setdefault(str(x.get("column", "")).strip(), x)
            for col in columns:
                x = row.get(col) or {}
                if not str(x.get("value", "")).strip() or not str(x.get("quote", "")).strip():
                    empty.append({"source_id": src.id, "column": col, "why": "the paper does not state it"})
                    continue
                try:
                    try:
                        a = self.add_anchor(src.id, x["quote"], page=x.get("page") or None)
                    except evidence.AnchorRejected:  # wrong page: unique anywhere in the paper is still exact
                        a = self.add_anchor(src.id, x["quote"])
                except evidence.AnchorRejected as e:
                    empty.append({"source_id": src.id, "column": col, "why": str(e), "value": x["value"]})
                    continue
                sc = self.add_check(task_id, f"{src.title} · {col}", "USEFUL")
                sc.matrix = {"id": mid, "column": col, "source_id": src.id}
                if metric := " ".join(str(x.get("metric") or "").split())[:40]:  # ⑧ what the number measures (EM, F1, …)
                    sc.matrix["metric"] = metric
                self.complete_check(sc.id, "VERIFIED", x["value"].strip() + " [1]",
                                    [{"tier": 4, "type": "pdf", "title": src.title, "url": src.locator, "supports": [a.id]}])
                self.link_evidence(a.id, sc.id, "supports", col)
                cells.append(sc)
        self.save()
        return mid, cells, empty

    def resolve_source(self, src_id: str) -> list[EvidenceAnchor]:
        """C2: every anchor of one source against the file at its path now (a newer arXiv version saved over it).
        D1: a web page is fetched once for all its anchors."""
        src, text = self.get_source(src_id), None
        mine = [a for a in self.state.anchors if a.source_id == src.id]
        if src.kind == "web":
            try:
                text = evidence.normalize(self.fetch(src.locator))[0]
            except (OSError, http.client.HTTPException) as e:  # one failed fetch, recorded on every anchor
                for a in mine:
                    a.status, a.resolution = "UNRESOLVED", {"status": "UNRESOLVED", "reason": "fetch_failed", "hash_changed": None,
                                                            "start": None, "end": None, "content_hash": None, "error": str(e), "at": now()}
                self.save()
                return mine
        return [self.resolve_anchor(a.id, text) for a in mine]

    def resolve_anchor(self, e_id: str, text: str | None = None) -> EvidenceAnchor:
        """Re-fetch the live source and find the anchor in it. Never moves the anchor; records where it is now.
        text: the web page's current text when the caller fetched it already (resolve_source)."""
        a = self.get_anchor(e_id)
        src = self.get_source(a.source_id)
        try:
            if src.kind == "pdf":  # the file at the captured path, as it is now
                with open(src.locator, "rb") as f:
                    r = pdf.resolve(a.quote, a.selector, src.version["content_hash"], f.read())
            else:
                if text is None:
                    text, _ = evidence.normalize(self.fetch(src.locator))
                r = evidence.resolve(a.quote, a.selector, src.version["content_hash"], text)
        except (OSError, http.client.HTTPException) as e:
            r = {"status": "UNRESOLVED", "reason": "fetch_failed", "hash_changed": None, "start": None, "end": None,
                 "content_hash": None, "error": str(e)}
        a.status, a.resolution = r["status"], {**r, "at": now()}
        self.save()
        return a

    def rename_source(self, src_id: str, title: str) -> EvidenceSource:
        """⑧ the name the user knows a paper by ("HippoRAG 2", not its long title): every card, the brief and the panels
        use it from now on; its file, anchors and evidence stay as they are."""
        src, title = self.get_source(src_id), " ".join(title.split())
        if not title or len(title) > 120:
            raise ValueError("이름은 1~120자로 적어 주세요.")
        src.title = title
        self.save()
        return src

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

    def everywhere(self, x) -> bool:
        """④ does this intent item apply to every task (project scope) rather than the one it was said in? The same
        reading of its candidate as _in_scope; the viewer marks such a criterion "모든 작업" before the user changes it."""
        c = next((c for c in self.intent.get_current_intent().candidates if c.item_id == x.id), None)
        f = c.features if c else {"scope": "task" if x.kind in ("assumption", "open_question", "decision") else "project"}
        return f.get("scope", "project") not in ("task", "action")

    def is_repro_default(self, x) -> bool:
        """Is this criterion one of REPRO_CRITERIA (by the line said, whatever statement the extractor made of it)?"""
        c = next((c for c in self.intent.get_current_intent().candidates if c.item_id == x.id), None)
        return bool(c) and c.text.strip() in REPRO_CRITERIA

    def drop_criterion(self, item_id: str, reason: str = ""):
        """④ the user removes a criterion; a reproduction task's default one only with a reason."""
        x = self.intent.get_item(item_id)
        if x and x.status == "active" and self.is_repro_default(x) and not reason.strip():
            raise ValueError("재현 작업의 기본 기준은 지우는 이유를 적어야 합니다.")
        return self.intent.remove_item(item_id, reason.strip())

    def _in_scope(self, task_id: str, x) -> bool:
        if x.id in self._intent_refs(task_id):
            return True
        if hasattr(x, "features"):
            f = x.features
        else:
            c = next((c for c in self.intent.get_current_intent().candidates if c.item_id == x.id), None)
            f = c.features if c else {"scope": "task" if x.kind in ("assumption", "open_question", "decision") else "project"}
        scope = f.get("scope", "project")
        if scope not in ("task", "action"):
            return True
        if f.get("task"):  # said in a named task (desktop chat, new-task criteria): that task only, whatever the time
            return f["task"] == task_id
        # no task named (CLI say): said while this task was the latest one. The window ends where the next task in the
        # list starts (list order, so two tasks made in the same instant do not share a window).
        t = self.get_task(task_id)
        i = self.state.tasks.index(t)
        end = self.state.tasks[i + 1].created_at if i + 1 < len(self.state.tasks) else None
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


def deviation(c) -> dict | None:
    """⑦ the user's intended deviation from this paper condition, while it holds ({from, to: None, why}), else None."""
    d = ((c.spec or {}).get("deviations") or [None])[-1]
    return d if d and d.get("to") is None else None


def scope_of(c) -> str | None:
    """⑦ "runs" | "task" while an intended deviation holds, else None (a span from before 10/14 has no scope: task)."""
    d = deviation(c)
    return (d.get("scope") or "task") if d else None


SPEC_KINDS = ("setting", "result", "fact", "scope")
_NUMS = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*%?(?![\w])")
_NAMES = re.compile(r"[A-Za-z][A-Za-z0-9.+-]{2,}")


def header_missing(statement: str, quote: str, kind: str | None) -> bool:
    """review (0.8): a result quoted as a table row ("LinearRAG (Ours) 64.30 66.50 70.20 63.70 …") whose text has no
    column names: which number is which dataset and metric is the model's guess (it paired 2Wiki with the wrong column).
    True when the row has 3+ numbers and none of the names the statement gives (datasets, metrics; the row's own label
    aside) is in the quote."""
    if kind != "result" or len(_NUMS.findall(quote)) < 3:
        return False
    first = _NUMS.search(quote)
    label, rest = quote[:first.start()].lower(), quote[first.start():].lower()
    names = [n for n in _NAMES.findall(statement) if n.lower() not in label]
    return not any(n.lower() in rest for n in names)


def aside(c) -> bool:
    """⑥ a paper condition kept for the reader, not held to: a fact (dataset size, the authors' GPU) or the paper's
    scope (a baseline's settings, an ablation). 재현 점검, the Guard and the brief's rules leave it out."""
    return bool(c.spec) and c.spec.get("kind") in ("fact", "scope")


_READ_CMDS = {"get-content", "gc", "cat", "type", "get-item", "gi", "get-childitem", "gci", "ls", "dir", "select-string",
              "sls", "rg", "grep", "findstr", "head", "tail", "wc", "select-object", "select", "format-table", "ft",
              "format-list", "fl", "measure-object", "measure", "sort-object", "sort", "where-object", "where", "?",
              "test-path", "resolve-path", "get-location", "pwd", "get-filehash", "out-string", "more"}
_READ_GIT = {"diff", "status", "log", "show", "ls-files", "grep", "blame", "rev-parse", "branch"}
_LIST_BRANCH = {"--list", "-l", "-a", "--all", "-r", "--remotes", "-v", "-vv", "--verbose", "--show-current"}  # review: only listing


def reads_only(description: str) -> bool:
    """real --guard (10/14): reading a file to do a step (Get-Content, git diff, git status, Get-Item) was warned as a
    plan departure (D01) three times in one run. A command made only of read commands, with no redirection and no
    script block, changes nothing: it is part of doing the step, whatever step it is."""
    head = description.split("\n")[0]
    if not head.startswith("명령 실행:"):
        return False
    m = re.search(r"-Command\s+(['\"])(.*)\1\s*$", head)  # pwsh -Command "…" / '…': the command inside the wrapper
    cmd = m.group(2) if m else head.split(":", 1)[1].strip()
    if re.search(r">|\{|\$\(|`|Set-|Out-File|Add-Content|Remove-|New-|Move-|Copy-|Rename-|Invoke-|Start-|--output", cmd, re.I):
        return False
    for part in re.split(r"\s*(?:;|\|\||&&|\|)\s*", cmd.strip()):
        words = part.strip().strip("&").split()
        if not words:
            continue
        name = words[0].strip("'\"").lower()
        if name == "git":
            sub = next((w for w in words[1:] if not w.startswith("-")), "")
            if sub not in _READ_GIT or (sub == "branch" and not all(w in _LIST_BRANCH for w in words[words.index(sub) + 1:])):
                return False  # review: `git branch name` makes one; only listing reads
        elif name not in _READ_CMDS:
            return False
    return True


def edits_existing(description: str) -> bool:
    """⑦ does the action change or delete a file that is there (desktop: "파일 수정: x, 파일 삭제: y")? Creating a file or
    running a command leaves the base run as it is."""
    return bool(re.search(r"(파일 수정|파일 삭제|파일 변경):", description.split("\n")[0]))


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


BRIEF_FACT_CHARS = 400
SPEC_LABEL = {"dataset": "데이터셋", "split": "데이터 분할", "preprocessing": "전처리", "model": "모델", "method": "방법",
              "hyperparameter": "하이퍼파라미터", "training": "학습", "metric": "평가 지표", "baseline": "비교 대상",
              "result": "보고된 결과", "protocol": "평가 규칙"}


def render_brief(s: PabloSkill, task_id: str) -> tuple[str, list[str]]:
    """What the desktop agent is told before it works on the task: the user's criteria for it and the facts Pablo has
    located in a source, each citation [n] replaced by where it is ("LinearRAG p.9") so the agent can say where.
    -> (text, basis): basis = the completed supporting checks, for the plan step the request becomes. Empty text when
    there is nothing to tell."""
    ai = s.get_applicable_intent(task_id)
    must = [c.statement for c in ai["constraints"] if c.strength == "hard"]
    prefer = [c.statement for c in ai["constraints"] if c.strength != "hard"]
    facts, basis, open_, paper, differ, aside_ = [], [], [], False, [], []
    for c in s.checks(task_id):
        if c.matrix:  # C3 a comparison-table cell: the user reads it; the agent is not bound by another paper's row
            continue
        if c.spec and c.spec.get("missing") and c.research_state == "pending":
            open_.append(f"- [{SPEC_LABEL.get(c.spec['category'], c.spec['category'])}] {c.requirement.strip()}")
            continue
        if c.research_state != "completed" or c.outcome not in guard.SUPPORTING_OUTCOMES or not c.conclusion:
            continue
        where = []
        for _, a in s.evidence_for(c.id):
            src = s.get_source(a.source_id)
            where.append(f"{src.title} p.{a.selector['page']}" if "page" in a.selector else src.title)
        text = re.sub(r"\[(\d+)\]", lambda m: f"({where[int(m[1]) - 1]})" if 0 < int(m[1]) <= len(where) else "",
                      c.conclusion)
        if not re.search(r"\[\d+\]", c.conclusion) and where:
            text += f" ({', '.join(dict.fromkeys(where))})"
        text = text if len(text) <= BRIEF_FACT_CHARS else text[:BRIEF_FACT_CHARS] + "…"
        if c.spec and deviation(c):  # ⑦ the user differs from it on purpose: not a rule for the agent, said with why
            differ.append(f"- [{SPEC_LABEL.get(c.spec['category'], c.spec['category'])}] {text} → 이유: {deviation(c)['why']}"
                          + (" (기본 실행은 논문대로 두고, 새 파일이나 실행 옵션으로 따로 돌릴 때만 다르게)" if scope_of(c) == "runs"
                             else " (이 작업 전체에서 다르게)"))
            continue
        if c.spec and aside(c):  # ⑥ background for the agent, not a condition to follow
            aside_.append(f"- [{'실험 범위' if c.spec['kind'] == 'scope' else '서술'}] {text}")
            continue
        if c.spec:  # a paper's reproduction condition: the statement is the fact
            paper = True
            facts.append(f"- [{SPEC_LABEL.get(c.spec['category'], c.spec['category'])}] {text}")
        else:
            facts.append(f"- {c.requirement.strip()} → {text}" + (" (일부만 확인됨)" if c.outcome != "VERIFIED" else ""))
        basis.append(c.id)
    if not (must or prefer or facts or open_ or differ or aside_):
        return "", []
    out = ["[Pablo] 이 작업에서 사용자가 정한 기준과 확인된 근거입니다. 기준과 어긋나는 일은 하기 전에 말하고, "
           "근거를 쓸 때는 괄호 안의 출처와 쪽을 함께 밝히세요."]
    out += [f"반드시: {x}" for x in must] + [f"가능하면: {x}" for x in prefer]
    if facts:
        out += ["확인된 근거:"] + facts
    if paper:
        out.append("논문에 적힌 조건은 근거 없이 바꾸지 마세요. 결과를 맞추려고 바꾸면 재현이 아닙니다.")
    if open_:
        out += ["논문에 없는 설정 (정하면 무엇을 근거로 정했는지 밝히세요):"] + open_
    if differ:
        out += ["사용자가 이유와 함께 일부러 논문과 다르게 두는 조건 (줄마다 적힌 범위 안에서만 막지 않습니다. 결과를 말할 때 "
                "이 차이를 밝히세요):"] + differ
    if aside_:
        out += ["참고 (논문의 서술과 이 재현 밖의 실험, 따를 조건은 아님):"] + aside_
    return "\n".join(out), basis


AUDIT_STATUS = ["followed", "differs", "missing", "unclear", "chosen"]
AUDIT_OUTSIDE = ["method", "scope"]  # a difference no item covers: how the method is done | an experiment not in the folder
AUDIT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items", "outside", "summary"],
    "properties": {
        "summary": {"type": "string"},
        "items": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "status", "where", "found", "note"],
            "properties": {"id": {"type": "string"}, "status": {"enum": AUDIT_STATUS}, "where": {"type": "string"},
                           "found": {"type": "string"}, "note": {"type": "string"}}}},
        "outside": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["kind", "what", "where", "found"],
            "properties": {"kind": {"enum": AUDIT_OUTSIDE}, "what": {"type": "string"}, "where": {"type": "string"},
                           "found": {"type": "string"}}}}}}


def render_audit(s: PabloSkill, task_id: str) -> tuple[str, list[dict]]:
    """The 재현 점검 the desktop agent runs read-only over the work folder: every stated paper condition, every setting
    the paper leaves open and every criterion of the task, each to be judged against the code, configs and run logs
    (a reported result against the value a log shows). A value is judged by its value and a method step (방법) by what
    the code does; what no item covers comes back apart (outside), so the verdicts stay one per item.
    -> (prompt, items [{id, kind, label, text}])."""
    items = []
    for c in s.checks(task_id):
        if not c.spec or c.research_state == "waived" or aside(c):  # ⑥ a fact or the paper's scope: nothing to check
            continue
        label = SPEC_LABEL.get(c.spec["category"], c.spec["category"])
        if c.spec.get("missing"):
            items.append({"id": c.id, "kind": "open", "label": "논문에 없는 설정", "text": c.requirement.strip()})
            continue
        pages = [a.selector.get("page") for _, a in s.evidence_for(c.id)]
        where = f" (논문 p.{pages[0]})" if pages and pages[0] else ""
        text = re.sub(r"\s*\[\d+\]", "", c.conclusion or c.requirement).strip() + where
        if c.spec.get("header_missing"):  # review/e2e2: the column pairing is the extraction's guess; a mismatch may be it
            text += " [주의: 논문 표 한 행에서 읽은 값이라 숫자와 데이터셋·지표의 짝이 틀렸을 수 있음. 다르면 그 가능성을 note에 쓰세요]"
        items.append({"id": c.id, "kind": "condition", "label": label, "text": text,
                      "value": c.spec.get("value", "")})  # the desktop checks the verdict against it (desktop/where.js)
    for i in s.get_applicable_intent(task_id)["constraints"]:
        items.append({"id": i.id, "kind": "criterion", "label": "작업 기준" + (" (반드시)" if i.strength == "hard" else ""),
                      "text": i.statement})
    prompt = "\n".join([
        "[Pablo 재현 점검] 작업 폴더의 코드, 설정 파일, 실행 로그를 읽고 아래 항목마다 지금 상태를 판정하세요. "
        "파일을 고치거나 프로그램을 실행하지 말고 읽기만 하세요. 항목마다 하나씩, id를 그대로 써서 답하세요.",
        "status:",
        "- followed: 코드나 설정이 이 조건(기준)을 그대로 따른다. 보고된 결과라면 실행 로그의 값이 논문 값과 같다.",
        "- differs: 다르게 되어 있다(기준이라면 어긴다). 보고된 결과라면 로그의 값이 논문 값과 다르다.",
        "- missing: 아직 구현되거나 실행되지 않았다.",
        "- unclear: 읽은 것만으로는 판단할 수 없다.",
        "- chosen: 논문에 없는 설정에만 쓴다. 코드가 정해 둔 값이 있다.",
        "where: 근거가 된 파일과 줄(예: configs/base.yaml:12). 값 항목이면 그 값이 적힌 자리. 없으면 빈 문자열.",
        "found: 그 자리에 실제로 있는 값이나 코드 한 줄(짧게, 바꾸지 말고 그대로).",
        "note: 판단 이유 한 문장. summary: 전체를 두세 문장으로.",
        "값 항목(하이퍼파라미터, 모델 이름, 데이터셋 등)은 실행에서 실제로 쓰이는 값이 논문 값과 같은지로 판정하세요. "
        "설정에 있어도 코드가 다른 값으로 덮어쓰면 differs입니다. 한 항목에 조건이 여럿이면(예: 검증 세트에서 1,000개) "
        "모두 맞아야 followed입니다. 값은 같은데 그 값을 다른 일에 쓰는 것(예: 임계값을 반복 횟수로 씀, 모델을 불러 놓고 "
        "쓰지 않음)은 값 항목에서 followed로 두고, 그 단계의 '방법' 항목이나 outside에 한 번만 쓰세요.",
        "'방법' 항목은 코드가 실제로 그 일을 그렇게 하는지로 판정하세요. 값이 맞아도 다른 용도로 쓰거나(예: 임계값을 반복 "
        "횟수로 씀) 계산을 줄였으면 differs, 그 단계가 없으면 missing입니다.",
        "outside: 아래 항목이 다루지 않는데 결과가 달라질 만한 차이. 예: 설정한 값이나 모델을 불러 놓고 실제로 쓰지 않음, "
        "단계 사이에 넘겨야 할 것을 넘기지 않음. kind는 method(구현이 다름) 또는 scope(논문의 실험 가운데 이 폴더에 "
        "없는 것)입니다. what은 한 문장, where와 found는 위와 같습니다. 많아야 8개, 결과에 큰 것부터 쓰세요. 항목과 "
        "겹치는 것은 쓰지 말고, 없으면 빈 목록을 주세요.",
        "항목 (id | 분류 | 내용):",
        *[f"{x['id']} | {x['label']} | {x['text']}" for x in items]])
    return prompt, items


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
