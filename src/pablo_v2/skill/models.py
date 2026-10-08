"""M2 Skill contracts: SourceCheck -> Plan -> ActionProposal (+ Guard verdict) -> ExecutionRecord -> PostReview.

All cross-references are IDs: intent items (C1..), checks (SC1..), plans (P1), steps (P1.1), actions (ACT1),
executions (EX1), reviews (REV1), research issues (RI1).
Nested records (searches, sources, steps, analysis, verdict) stay plain dicts in the JSON state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from pablo_v2.intent.models import now

NECESSITY = ("NONE", "USEFUL", "REQUIRED")
DECISIONS = ("proceed", "defer", "reject")
RELATIONS = ("supports", "contradicts", "verifies", "implements", "derived_from")
ISSUE_TYPES = ("source_tool_error", "source_changed", "source_conflict", "insufficient_coverage", "other")
OUTCOMES = ("VERIFIED", "PARTIALLY_VERIFIED", "NOT_FOUND", "CONFLICTING")
STOP_REASONS = ("authoritative_answer_found", "official_channels_exhausted", "conflict_unresolved", "budget_exhausted")
TIERS = {
    1: "official specification / documentation",
    2: "official repository / implementation",
    3: "official examples / changelog / release notes",
    4: "primary research paper / dataset documentation",
    5: "trusted secondary documentation",
    6: "community / general web",
}
AUTHORITATIVE_TIERS = (1, 2, 3, 4)  # can confirm an "officially supported" claim on their own


@dataclass
class Task:
    id: str
    text: str
    reused: list[str] = field(default_factory=list)  # completed checks of earlier tasks this task relies on
    created_at: str = field(default_factory=now)


@dataclass
class SourceCheck:
    id: str
    task_id: str
    requirement: str  # the external fact to establish
    necessity: str  # NONE | USEFUL | REQUIRED
    why: str = ""  # why_blocking: which decision changes if this fact is misunderstood
    research_state: str = "pending"  # pending | completed | waived  (gate looks only at this)
    outcome: str | None = None  # VERIFIED | PARTIALLY_VERIFIED | NOT_FOUND | CONFLICTING
    sources: list[dict] = field(default_factory=list)  # {tier, type, title, url, supports: [..]}
    searched: list[dict] = field(default_factory=list)  # {target, query, tier, result: found|not_found, at}
    stop_reason: str | None = None
    conclusion: str | None = None
    rejections: list[str] = field(default_factory=list)  # completion attempts the gate refused
    intent_refs: list[str] = field(default_factory=list)
    waived_by: str | None = None  # "host" when the host dropped an over-generated check
    waive_reason: str | None = None


@dataclass
class Plan:
    id: str
    task_id: str
    steps: list[dict]  # {id: "P1.1", action, basis: ["SC1", "C1"]}
    unverified: list[str] = field(default_factory=list)  # computed: steps resting on non-VERIFIED checks
    status: str = "active"  # active | superseded
    created_at: str = field(default_factory=now)


@dataclass
class ActionProposal:
    id: str
    task_id: str
    description: str
    plan_step: str | None = None
    justification: str | None = None
    analysis: dict = field(default_factory=dict)  # semantic judge output (no verdict in it)
    verdict: str = ""  # ALLOW | WARN | BLOCK, decided by guard.py rules
    reasons: list[dict] = field(default_factory=list)  # {rule, verdict, reason}
    host_decision: str | None = None  # proceed | defer | reject, recorded by the host after the verdict
    decision_reason: str | None = None
    created_at: str = field(default_factory=now)


@dataclass
class ExecutionRecord:
    """What the host actually did after a decision. Pablo stores paths and the host's summary, never diffs."""
    id: str
    action_id: str
    host_decision: str | None  # the action's decision when this was recorded
    executed: bool
    summary: str
    changed_files: list[str] = field(default_factory=list)
    tests: list[dict] = field(default_factory=list)  # {name, result: pass|fail|skip}
    observations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now)


@dataclass
class ResearchIssue:
    id: str
    type: str  # one of ISSUE_TYPES
    note: str
    source_check_id: str | None = None
    review_id: str | None = None
    created_at: str = field(default_factory=now)


@dataclass
class EvidenceSource:
    """One captured version of a source. A re-capture with a different hash is a new EvidenceSource."""
    id: str
    kind: str  # web | pdf (M3.3) (git later)
    title: str
    locator: str  # URL, or the PDF's absolute path
    version: dict  # {content_hash: "sha256:..."} of the normalized text
    snapshot: str  # normalized text file, relative to the state dir
    captured_at: str = field(default_factory=now)


@dataclass
class EvidenceAnchor:
    id: str
    source_id: str
    quote: dict  # {exact, prefix, suffix} - primary locator
    selector: dict  # {type: web_text, start, end} - offsets in the source version's normalized text
    #                 {type: pdf_text, page, start, end} - offsets in that page's text (pdf.pages)
    status: str = "VALID"  # VALID | STALE | UNRESOLVED (validity only; relevance is not judged here)
    resolution: dict | None = None  # last resolve: {status, reason, hash_changed, start, end, content_hash, at}
    created_at: str = field(default_factory=now)


@dataclass
class EvidenceLink:
    id: str
    evidence_id: str
    target_id: str  # any Pablo id: SC, C/A/.., P1.1, ACT, EX, REV
    relation: str  # one of RELATIONS
    note: str = ""
    created_at: str = field(default_factory=now)


@dataclass
class PostReview:
    """Observations + update proposals. Never changes Intent or Plan itself."""
    id: str
    execution_id: str
    action_id: str
    facts: dict  # semantic judge observations ({} when no judge was needed)
    action_alignment: str  # aligned | partial | deviated | failed | not_executed
    plan_step_status: str | None  # completed | partial | unchanged | blocked; None without a plan step
    deviations: list[dict] = field(default_factory=list)  # {kind, note}
    new_facts: list[dict] = field(default_factory=list)  # {statement, source_check_id}
    new_assumptions: list[str] = field(default_factory=list)
    new_questions: list[dict] = field(default_factory=list)  # {statement, blocking}
    research_issues: list[str] = field(default_factory=list)  # RI ids
    intent_update_proposals: list[dict] = field(default_factory=list)  # {api, args, note}
    plan_update_proposals: list[dict] = field(default_factory=list)  # {api, kind, target, note}
    created_at: str = field(default_factory=now)


@dataclass
class SkillState:
    tasks: list[Task] = field(default_factory=list)
    checks: list[SourceCheck] = field(default_factory=list)
    plans: list[Plan] = field(default_factory=list)
    actions: list[ActionProposal] = field(default_factory=list)
    counters: dict = field(default_factory=dict)
    executions: list[ExecutionRecord] = field(default_factory=list)
    reviews: list[PostReview] = field(default_factory=list)
    issues: list[ResearchIssue] = field(default_factory=list)
    sources: list[EvidenceSource] = field(default_factory=list)
    anchors: list[EvidenceAnchor] = field(default_factory=list)
    links: list[EvidenceLink] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SkillState":
        return cls([Task(**x) for x in d["tasks"]], [SourceCheck(**x) for x in d["checks"]],
                   [Plan(**x) for x in d["plans"]], [ActionProposal(**x) for x in d["actions"]], d["counters"],
                   [ExecutionRecord(**x) for x in d.get("executions", [])],
                   [PostReview(**x) for x in d.get("reviews", [])],
                   [ResearchIssue(**x) for x in d.get("issues", [])],
                   [EvidenceSource(**x) for x in d.get("sources", [])],
                   [EvidenceAnchor(**x) for x in d.get("anchors", [])],
                   [EvidenceLink(**x) for x in d.get("links", [])])
