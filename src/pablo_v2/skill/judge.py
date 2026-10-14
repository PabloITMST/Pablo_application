"""Semantic judge: LLM reports facts only. No verdicts here; guard.py decides.

Judge contract (duck-typed; tests inject stubs):
    analyze_task(task, intent, existing) -> {"reuse": [{"source_check_id", "why"}],
                                             "checks": [{"requirement", "necessity", "why_blocking"}]}
    analyze_action(action, justification, step, constraints, checks)
        -> {"intent_conflicts": [...], "source_conflicts": [...], "plan_alignment": {...}, "justification": {...}}
    analyze_execution(context, execution) -> REVIEW_SCHEMA facts (scope, outcome, step progress, new facts ...)
    answer_from_pdf(question, pages) -> {"answer" with [n] markers, "citations": [{n, page, quote, role}]}  (M3.3)
    answer_from_sources(question, papers [{label, title, pages}]) -> same, each citation also has its paper's label (C1)
    extract_spec(pages) -> {"items": [{category, statement, value, quote, page}], "missing": [{category, statement}]}
    compare_paper(columns, title, pages) -> {"cells": [{column, value, quote, page}]}  one paper's row of a table (C3)
"""
from __future__ import annotations

import json
import os

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

ASK_SOURCES_SCHEMA = _obj(answer=_str, citations={"type": "array", "items": _obj(
    n={"type": "integer"}, paper=_str, page={"type": "integer"}, quote=_str, near=_str,
    role={"enum": ["claim", "table", "text"]})})

ASK_SOURCES_PROMPT = """You answer a question about several sources (papers, and web pages the user added), using only
their text below. Each source has a label (A, B, ...). A paper's text is split by page: [A p.N] is page N of paper A. A web
page has no pages: [B] is its whole text. Pablo will locate every quote you give in that source and highlight it; a quote
it cannot find verbatim in that source is dropped.

Rules:
- Write the whole answer in the language of the QUESTION (a Korean question gets a Korean answer), although the sources
  are in another language; names, metrics and numbers stay as the sources write them. 2-6 short sentences. Name the
  source each statement is about by the title given after "Paper A:", "Web page B:".
  Use only what the sources say. Never invent numbers, metrics or claims, and never carry a number from one source to
  another. If the sources do not answer the question, say so and give no citations.
- Put citation markers [1], [2], ... right after the sentence they support. At most 6 citations, numbered
  n = 1, 2, ... in order of first use. paper: the label of the source the quote is from.
- quote: copied verbatim from that source's text (same words and numbers, in order), 5-30 words, one contiguous span
  that appears only once in that source. page: the N of its [label p.N] for a paper, 0 for a web page.
- near: for a web page, 3-8 words copied verbatim from the text right before or after the quote (they tell two equal
  quotes apart); "" for a paper.
- A table: quote ONE row only, its row label followed by the numbers you rely on, exactly as in the text. role = table.
  Claims in prose: role = claim. Other prose: role = text.
- When sources report the same thing differently (other datasets, metrics, settings or numbers), say so instead of
  merging them. A number one paper reports about another method is that paper's measurement; say whose it is.

SOURCES (page text from each PDF, the text of each web page):
{papers}

QUESTION (answer in its language):
{question}
"""

COMPARE_SCHEMA = _obj(cells={"type": "array", "items": _obj(column=_str, value=_str, metric=_str, quote=_str,
                                                              page={"type": "integer"})})

COMPARE_PROMPT = """You fill one row of a table that compares several papers: the row for the paper below. Other papers
get the same columns in separate calls, so answer about this paper only. Pablo locates every quote in the PDF and
highlights it; a cell whose quote it cannot find verbatim is left empty.

For each column, one cell, in the order given:
- column: the column name exactly as given.
- value: a short answer in Korean (at most 20 words; keep names, metrics and numbers as the paper writes them), or ""
  when this paper does not state it. Never infer, estimate or carry a value from another paper.
- metric: when the value is a measured number (a score, a time, a size), what it measures as the paper names it,
  e.g. "EM", "F1", "GPT-Acc", "Recall@5", "seconds"; "" when the value is not a measurement. A reader compares
  numbers across papers only when this is the same.
- quote: copied verbatim from one page's text (same words and numbers, in order), 5-30 words, one contiguous span that
  appears only once in the paper and supports the value. For a number from a table: ONE row, its label followed by
  the numbers, exactly as in the text. "" when value is "".
- page: the [p.N] the quote is on (0 when value is "").

COLUMNS:
{columns}

PAPER: {title}
(page text from the PDF, [p.N] = page N)
{pages}
"""

SPEC_CATEGORIES = ["dataset", "split", "preprocessing", "model", "method", "hyperparameter", "training", "metric",
                   "baseline", "result", "protocol"]
SPEC_KINDS = ["setting", "result", "fact", "scope"]  # ⑥ what a reproduction does with a condition
SPEC_SCHEMA = _obj(
    items={"type": "array", "items": _obj(category={"enum": SPEC_CATEGORIES}, kind={"enum": SPEC_KINDS}, statement=_str,
                                          value=_str, quote=_str, page={"type": "integer"})},
    missing={"type": "array", "items": _obj(category={"enum": SPEC_CATEGORIES}, statement=_str)})

SPEC_PROMPT = """You extract what a faithful reproduction of this paper's main experiments must follow, from the paper's
text below. Pablo locates every quote in the PDF and highlights it; an item whose quote it cannot find verbatim is dropped.

items: concrete conditions the paper states.
- category: dataset (benchmarks, versions, sizes) | split (what is used for training / validation / testing, sizes) |
  preprocessing | model (architecture, backbone, embedding or language model names) | method (how the method works,
  where code can keep every value right and still differ: what a named value controls, how a score is computed or
  combined, which model computes what, what one stage hands to the next) | hyperparameter (named values: learning rate,
  top-k, thresholds, dimensions, ...) | training (steps, epochs, hardware, seeds when stated) | metric (how results are
  scored) | baseline (methods compared against) | result (a main reported number) | protocol (evaluation rules a
  reproduction must not break, e.g. data used only for testing).
- kind: what a reproduction does with it.
  setting = what the code or its config fixes: data and split, preprocessing, the model, a method step, a
            hyperparameter, the metric, an evaluation rule, a training setting. 재현 점검 holds the folder to it.
  result  = a number the paper reports for the main experiments; a run should come close to it.
  fact    = a description no code sets: a dataset's size or origin, the hardware or runtime the authors had, what
            other work did. Kept for the reader; never checked in the folder.
  scope   = another experiment of the paper: a baseline's own settings, an ablation, an extra dataset or analysis a
            reproduction of the main result may leave out. Kept as the paper's scope; never checked in the folder.
- statement: one short Korean sentence stating the condition with its exact value (e.g. "검색 단계의 top-k는 5이다").
  For method: what the code has to do, so that reading the code can tell (e.g. "δ는 엔티티 활성 점수의 pruning
  임계값이다", not "δ는 4이다"; "검색된 passage의 본문이 생성 단계의 문맥으로 들어간다").
- value: the value alone ("5", "GPT-4o-mini", "Contriever"), or "" when it is not one value (always "" for method).
- quote: copied verbatim from that page's text (same words and numbers, in order), 5-30 words, one contiguous span that
  appears only once in the paper and contains the value. For a result from a table: ONE row, its label followed by the
  numbers, exactly as in the text (e.g. "MethodName 12.3 4.5"); never a whole table or a caption. For method: the
  sentence that says it in words, never a formula's symbols (formulas do not survive PDF text extraction).
  For a result: pair every number with its dataset and metric in the statement (e.g. "2Wiki의 GPT-Acc는 63.70이다").
  A table row's text rarely carries its column names (the header is lost in the PDF text), so prefer the sentence of
  the text that states the number with those names; quote a row only when you are sure which column each number is.
- page: the [p.N] it is on.
At most 24 items besides method, and at most 10 method items. Prefer what changes results: data and splits, the
model, key hyperparameters, metrics, the main baselines and main results. Method items: one per step of the main
method that a reproduction could simplify or get wrong; never restate a value item. Never invent a value. Never
paraphrase inside quote.

missing: settings a reproduction must decide that the paper does NOT state (e.g. random seed, learning rate schedule,
number of runs, prompt templates, hardware), at most 6, each with a Korean statement naming what is missing. List
only what a reader would actually have to decide; never list something the paper states. A method that trains nothing
(training-free, zero-shot, retrieval only) has no training settings to decide: never list epochs, learning rate,
optimizer or batch size for it.

PAPER (page text from the PDF, [p.N] = page N):
{pages}
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
  SP3 is about secrets only: tokens, API keys, passwords, credential stores (.env, auth.json, credentials files,
  keychains). Reading, listing or searching a project's ordinary code, config, data or log files is not a conflict
  with SP3 unless the action targets such a secret.

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

    def answer_from_sources(self, question: str, papers: list[dict]) -> dict:
        text = "\n\n".join(
            f"=== Web page {x['label']}: {x['title']} ===\n[{x['label']}] " + " ".join(x["pages"]) if x.get("kind") == "web"
            else f"=== Paper {x['label']}: {x['title']} ===\n" + "\n\n".join(
                f"[{x['label']} p.{n}] {p}" for n, p in enumerate(x["pages"], 1)) for x in papers)
        return self.provider.complete_json(ASK_SOURCES_PROMPT.format(papers=text, question=question), ASK_SOURCES_SCHEMA)

    def extract_spec(self, pages: list[str]) -> dict:
        text = "\n\n".join(f"[p.{n}] {p}" for n, p in enumerate(pages, 1))
        r = self.provider.complete_json(SPEC_PROMPT.format(pages=text), SPEC_SCHEMA)
        if dump := os.environ.get("PABLO_SPEC_DUMP"):  # tests/eval: the answer as it came, frozen for later runs
            with open(dump, "w", encoding="utf-8") as f:
                json.dump({"items": r["items"], "missing": r["missing"]}, f, ensure_ascii=False, indent=1)
        return r

    def compare_paper(self, columns: list[str], title: str, pages: list[str]) -> dict:
        text = "\n\n".join(f"[p.{n}] {p}" for n, p in enumerate(pages, 1))
        return self.provider.complete_json(COMPARE_PROMPT.format(columns="\n".join(f"- {c}" for c in columns),
                                                                 title=title, pages=text), COMPARE_SCHEMA)
