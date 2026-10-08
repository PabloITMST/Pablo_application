"""Intent Spec data model. Plain dataclasses, serialized as JSON.

Intent = Why / What / Boundary. Plans, execution state and evidence anchors
do not live here; Evidence is referenced only by an opaque `ref` string.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

# kind -> stable ID prefix
KINDS = {
    "goal": "G",
    "constraint": "C",
    "success_criterion": "S",
    "assumption": "A",
    "open_question": "Q",
    "decision": "D",
}

# Kinds a user utterance can produce. Assumptions / open questions are agent-side.
USER_KINDS = ("goal", "constraint", "success_criterion", "decision")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Source:
    type: str  # "user" | "agent" | "evidence"
    ref: str | None = None  # user -> message id, evidence -> evidence id (M3), agent -> None
    note: str | None = None


@dataclass
class IntentItem:
    id: str
    kind: str
    statement: str
    source: Source
    status: str = "active"  # active | superseded | removed; assumption: unverified|verified|rejected
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    topics: list[str] = field(default_factory=list)  # match keys for reinforcement / pending merge
    strength: str | None = None  # constraint: hard | soft
    priority: int = 1  # bumped by reinforcement / correction
    reinforced_by: list[str] = field(default_factory=list)  # message ids
    parent_id: str | None = None  # goal hierarchy
    rationale: str | None = None  # decision: why
    blocking: bool | None = None  # open_question
    superseded_by: str | None = None  # set when a user change replaces this item (deviation)


@dataclass
class Candidate:
    """One extraction result per user message. Kept forever for debugging."""

    id: str
    message_id: str
    text: str
    extractor: str
    features: dict  # raw structured classification
    action: str  # commit | pending | ignore (policy output)
    policy_reason: str
    status: str  # committed | pending | ignored | promoted | merged | rejected | reinforced | refined | deviation
    item_id: str | None = None  # resulting / related intent item
    created_at: str = field(default_factory=now)


@dataclass
class Change:
    version: int
    change_type: str  # extension | refinement | deviation | reinforcement | status | annotation (agent-side)
    item_id: str
    before: dict | None
    after: dict | None
    reason: str
    source: Source
    at: str = field(default_factory=now)


@dataclass
class IntentState:
    version: int = 0
    items: list[IntentItem] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    history: list[Change] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)  # {id, role, text, at}
    counters: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "IntentState":
        def item(x):
            return IntentItem(**{**x, "source": Source(**x["source"])})

        def change(x):
            return Change(**{**x, "source": Source(**x["source"])})

        return cls(
            version=d["version"],
            items=[item(x) for x in d["items"]],
            candidates=[Candidate(**x) for x in d["candidates"]],
            history=[change(x) for x in d["history"]],
            messages=d["messages"],
            counters=d["counters"],
        )
