"""Semantic judge: LLM reports facts only. No verdicts here; guard.py decides.

Judge contract (duck-typed; tests inject stubs):
    analyze_task(task, intent, existing) -> {"reuse": [{"source_check_id", "why"}],
                                             "checks": [{"requirement", "necessity", "why_blocking"}]}
    analyze_action(action, justification, step, constraints, checks)
        -> {"intent_conflicts": [...], "source_conflicts": [...], "plan_alignment": {...}, "justification": {...}}
    analyze_execution(context, execution) -> REVIEW_SCHEMA facts (scope, outcome, step progress, new facts ...)
    answer_from_pdf(question, pages) -> {"answer" with [n] markers, "citations": [{n, page, quote, role}]}  (M3.3)
"""
from __future__ import annotations

TASK_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["reuse", "checks"],
    "properties": {
        "reuse": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["source_check_id", "why"],
            "properties": {"source_check_id": {"type": "string"}, "why": {"type": "string"}}}},
        "checks": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["requirement", "necessity", "why_blocking"],
            "properties": {"requirement": {"type": "string"}, "necessity": {"enum": ["USEFUL", "REQUIRED"]},
                           "why_blocking": {"type": "string"}}}},
    },
}

_note = {"type": "string"}
ACTION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["intent_conflicts", "source_conflicts", "plan_alignment", "justification"],
    "properties": {
        "intent_conflicts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["intent_id", "level", "note"],
            "properties": {"intent_id": {"type": "string"}, "level": {"enum": ["clear", "possible", "none"]},
                           "note": _note}}},
        "source_conflicts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["source_check_id", "kind", "note"],
            "properties": {"source_check_id": {"type": "string"},
                           "kind": {"enum": ["contradicts", "bypasses", "possible", "none"]}, "note": _note}}},
        "plan_alignment": {
            "type": "object", "additionalProperties": False, "required": ["follows_step", "note"],
            "properties": {"follows_step": {"type": "boolean"}, "note": _note}},
        "justification": {
            "type": "object", "additionalProperties": False,
            "required": ["present", "relevant", "supported_by", "note"],
            "properties": {"present": {"type": "boolean"}, "relevant": {"type": "boolean"},
                           "supported_by": {"type": "array", "items": {"type": "string"}}, "note": _note}},
    },
}

def _obj(**props):
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


_str, _bool = {"type": "string"}, {"type": "boolean"}
REVIEW_SCHEMA = _obj(
    scope=_obj(relation={"enum": ["same", "subset", "superset", "different"]}, note=_str),
    unapproved_files={"type": "array", "items": _str},
    outcome=_obj(succeeded=_bool, note=_str),
    step_progress=_obj(progress={"enum": ["all", "part", "none"]}, note=_str),
    decision_consistent=_obj(consistent=_bool, note=_str),
    new_facts={"type": "array", "items": _obj(statement=_str, source_check_id=_str)},
    contradicted={"type": "array", "items": _obj(ref_id=_str, note=_str)},
    new_assumptions={"type": "array", "items": _str},
    new_questions={"type": "array", "items": _obj(statement=_str, blocking=_bool)},
    research_issues={"type": "array", "items": _obj(
        type={"enum": ["source_tool_error", "source_changed", "source_conflict", "insufficient_coverage", "other"]},
        source_check_id=_str, note=_str)},
)

ASK_SCHEMA = _obj(answer=_str, citations={"type": "array", "items": _obj(
    n={"type": "integer"}, page={"type": "integer"}, quote=_str, role={"enum": ["claim", "table", "text"]})})

ASK_PROMPT = """You answer a question about one paper, using only the paper's text below. Pablo will locate every
quote you give in the PDF and highlight it; a quote it cannot find verbatim is dropped.

Rules:
- Answer in the question's language, in 2-5 short sentences. Use only what the paper says. Never invent numbers,
  metrics or claims. If the paper does not answer the question, say so and give no citations.
- Put citation markers [1], [2], ... in the answer right after the sentence they support. At most 4 citations,
  numbered n = 1, 2, ... in order of first use.
- quote: copied verbatim from that page's text (same words and numbers, in order), 5-30 words, one contiguous
  span that appears only once in the paper. page: the [p.N] it is on.
- A table: quote ONE row only, its row label followed by the numbers you rely on, exactly as they appear in the
  text (e.g. "MethodName 12.3 4.5"). Never quote a whole table or a caption as table evidence. role = table.
- What the authors claim in prose (role = claim) and what a table actually shows (role = table) are separate
  citations. If they differ, or a claim does not say what it is compared with, say so in the answer.
- Before citing a quantitative claim (a percentage, a ratio, "fastest", "best") together with table or result
  numbers, check the numbers against the claim yourself, row by row, using numbers on those pages. If the claim
  holds only for some rows, the numbers do not match it exactly, or its comparison basis is unclear, say that in
  the answer, with the numbers that show it. Never merge disagreeing sources into one statement.
- If the evidence is an analysis (e.g. complexity, O(...)) rather than a measurement, say it is an analysis. Do not
  present a measurement of one quantity (e.g. time, tokens) as evidence measured for another (e.g. memory).
- If the paper contains evidence against the question's premise or against the authors' own claim, report it.
- Other quoted prose: role = text.

PAPER (page text from the PDF, [p.N] = page N):
{pages}

QUESTION:
{question}
"""

TASK_PROMPT = """You are Pablo's task analyst. Decide which EXTERNAL facts / specifications this task depends on.

First reuse: if an EXISTING SOURCE CHECK below already answers a fact this task needs, list it in reuse
and do NOT create a new check for it.

Then create checks only for facts still missing.
- Generate as few checks as possible. If one check is needed, generate exactly one.
  Do NOT fill up to three. Zero is a valid answer.
- REQUIRED only if getting this external fact wrong would change the implementation direction,
  the API / mechanism chosen, the security approach, the evaluation protocol, or the core result.
  why_blocking must name that decision ("if wrong, the authentication architecture changes").
  If you cannot name such a decision, the check is USEFUL, not REQUIRED.
- Do not create checks for details a component the task delegates to already owns
  (e.g. polling / token handling inside a CLI the task just calls).
- Merge overlapping questions into one.
Tasks that only touch local code (renames, refactors, internal restructuring) need no checks.
Phrase each requirement as a question about the official mechanism, not about a solution you already picked.

USER INTENT:
{intent}

EXISTING SOURCE CHECKS (completed earlier):
{existing}

TASK:
{task}
"""

ACTION_PROMPT = """You are Pablo's semantic judge. Report facts; do NOT decide allow/warn/block.

The proposed action is done by the host coding agent working on the user's project.
Constraints are the user's requirements for that project and how the work is done. A constraint about
what the product must not do (e.g. "X must not edit files") is violated by building that capability
into the product, not by the agent editing project files to do its task. Likewise, the product starting a
fixed program it depends on (e.g. a CLI or server it calls for data) is not executing shell commands or
code changes on the user's behalf.

1. intent_conflicts: for each constraint below, does the action conflict with it?
  clear = the action does what the constraint forbids, or skips what it prefers/requires
  possible = could conflict depending on details
  List only clear or possible.

2. source_conflicts: for each source check below, compare the action with its CONCLUSION.
  contradicts = the action relies on something the conclusion says is wrong, unsupported, or owned by
                another component (e.g. reading credentials the conclusion says Codex owns)
  bypasses    = the action replaces the mechanism the conclusion documents with a custom or
                undocumented alternative (e.g. reimplementing a flow the official CLI already provides)
  possible    = could do either depending on details
  List only contradicts, bypasses or possible; at most one entry per source check (the stronger kind).

3. plan_alignment.follows_step: true if the action carries out the plan step or a part of it
   (or there is no plan step). Doing only part of the step is NOT a departure.
   false only if it does something else or takes a different approach than the step.

4. justification (the agent's reason, if any):
  present  = a reason was given
  relevant = the reason addresses why the action departs from the plan step, the constraint, or the
             source conclusion it conflicts with ("faster", "easier", "simpler" are NOT relevant to
             following an official mechanism or a source conclusion)
  supported_by = ids of source checks below whose conclusion actually backs the reason; [] if none

CONSTRAINTS:
{constraints}

SOURCE CHECKS (* = basis of the plan step):
{checks}

PLAN STEP: {step}
PROPOSED ACTION: {action}
JUSTIFICATION: {justification}
"""

REVIEW_PROMPT = """You are Pablo's post-action reviewer. Report facts about what the host agent actually did.
Do NOT decide alignment or status, and do NOT propose changes; Pablo's rules do that.

Compare the EXECUTION with the PROPOSED ACTION (what was approved) and the PLAN STEP.
1. scope.relation: same = did what the action describes; subset = did only part of it;
   superset = did it plus meaningful extra work; different = did something else instead.
   Edits the action obviously needs (imports, a test or doc for the same change) are not extra work.
2. unapproved_files: changed files whose changes go meaningfully beyond the action. [] if none.
3. outcome.succeeded: false only if what was done broke: errors, failing tests, or the change could not be
   applied. Doing less than the action is scope "subset", not a failure.
4. step_progress.progress: how much of the PLAN STEP is now done: all | part | none.
5. decision_consistent.consistent: does the execution match the host decision and its reason
   (e.g. the reason limits the work, the record shows more)? true when there is no decision.
6. new_facts: external facts (API, tool or environment behaviour) learned during execution that the
   source checks do not already state. source_check_id = the related check, or "".
7. contradicted: assumptions (ids in ASSUMPTIONS) or source checks (SC ids) whose content the
   observations show to be wrong. [] if none.
8. new_assumptions: things the host now relies on without verification that are not listed yet.
9. new_questions: questions only the user can answer. blocking = work cannot continue without the answer.
10. research_issues: problems with how research was done, not with the product.
  source_tool_error = a research tool misreported a source (e.g. a summary said a feature is absent,
                      the raw page has it)
  source_changed = the source changed since the check; source_conflict = sources disagree;
  insufficient_coverage = the check missed a channel or case that mattered; other.
  source_check_id = the affected check, or "".
List only what the record supports. Empty lists are normal.

{context}

EXECUTION:
{execution}
"""


class LLMJudge:
    def __init__(self, provider):
        self.provider = provider

    def analyze_task(self, task: str, intent: str, existing: str = "") -> dict:
        return self.provider.complete_json(
            TASK_PROMPT.format(task=task, intent=intent or "(none)", existing=existing or "(none)"), TASK_SCHEMA)

    def analyze_action(self, action, justification, step, constraints, checks) -> dict:
        prompt = ACTION_PROMPT.format(action=action, justification=justification or "(none)",
                                      step=step or "(none)", constraints=constraints or "(none)",
                                      checks=checks or "(none)")
        return self.provider.complete_json(prompt, ACTION_SCHEMA)

    def analyze_execution(self, context: str, execution: str) -> dict:
        return self.provider.complete_json(REVIEW_PROMPT.format(context=context, execution=execution),
                                           REVIEW_SCHEMA)

    def answer_from_pdf(self, question: str, pages: list[str]) -> dict:
        text = "\n\n".join(f"[p.{n}] {p}" for n, p in enumerate(pages, 1))
        return self.provider.complete_json(ASK_PROMPT.format(pages=text, question=question), ASK_SCHEMA)
