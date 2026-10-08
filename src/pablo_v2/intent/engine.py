"""IntentEngine: the module boundary Pablo Skill (M2) calls.

User messages -> extractor -> policy -> commit / pending / ignore -> relation handling.
The engine knows nothing about auth or which model runs; it only calls extractor.extract().
Agent-side knowledge (assumptions, open questions, agent decisions) enters only via
explicit add_* calls with source.type="agent", never through process_message.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict

from . import policy
from .extract import HeuristicExtractor
from .models import KINDS, USER_KINDS, Candidate, Change, IntentItem, IntentState, Source, now

CORRECTION_PRIORITY_BUMP = 2
REPEAT_PRIORITY_BUMP = 1
CONVERSATION_WINDOW = 8  # recent user/agent messages shown to the extractor


class IntentEngine:
    def __init__(self, state: IntentState | None = None, extractor=None, path: str | None = None):
        self.state = state or IntentState()
        self.extractor = extractor or HeuristicExtractor()
        self.path = path

    # --- persistence -------------------------------------------------------
    @classmethod
    def load(cls, path: str, extractor=None) -> "IntentEngine":
        state = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                state = IntentState.from_dict(json.load(f))
        return cls(state, extractor, path)

    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.state.to_dict(), f, ensure_ascii=False, indent=2)

    # --- queries -----------------------------------------------------------
    def get_current_intent(self) -> IntentState:
        return self.state

    def get_item(self, item_id: str) -> IntentItem | None:
        return next((i for i in self.state.items if i.id == item_id), None)

    def _active(self, kind: str) -> list[IntentItem]:
        return [i for i in self.state.items if i.kind == kind and i.status in ("active", "unverified", "verified")]

    def get_active_goals(self):
        return self._active("goal")

    def get_active_constraints(self):
        return sorted(self._active("constraint"), key=lambda i: (i.strength != "hard", -i.priority))

    def get_success_criteria(self):
        return self._active("success_criterion")

    def get_decisions(self):
        return self._active("decision")

    def get_assumptions(self):
        return self._active("assumption")

    def get_open_questions(self):
        return self._active("open_question")

    def get_pending_candidates(self) -> list[Candidate]:
        return [c for c in self.state.candidates if c.status == "pending"]

    def get_candidate(self, cid: str) -> Candidate | None:
        return next((c for c in self.state.candidates if c.id == cid), None)

    def get_deviations(self) -> list[Candidate]:
        """User requests that contradict a hard constraint, held unapplied (no approval flow yet)."""
        return [c for c in self.state.candidates if c.status == "deviation"]

    def get_intent_history(self) -> list[Change]:
        return self.state.history

    # --- main entry ----------------------------------------------------------
    def process_message(self, text: str, role: str = "user") -> list[Candidate]:
        mid = self._next_id("M")
        self.state.messages.append({"id": mid, "role": role, "text": text, "at": now()})
        if role != "user":
            self.save()
            return []  # agent text never becomes user intent; it is only conversation context

        out = []
        for f in self.extractor.extract(text, mid, self._context(), self._conversation(exclude=mid)):
            action, reason = policy.decide(f)
            status = {"commit": "committed", "ignore": "ignored"}.get(action, action)
            c = Candidate(self._next_id("K"), mid, text, self.extractor.name, f, action, reason, status)
            self.state.candidates.append(c)
            {"commit": self._commit, "pending": self._pending, "ignore": self._ignore}[action](c)
            out.append(c)
        self.save()
        return out

    def promote_candidate(self, cid: str, reason: str = "manual promotion") -> IntentItem:
        c = self._require_candidate(cid)
        item = self._add_item(c.features, Source("user", c.message_id), reason)
        c.status, c.item_id = "promoted", item.id
        self.save()
        return item

    def reject_candidate(self, cid: str) -> None:
        self._require_candidate(cid).status = "rejected"
        self.save()

    # --- agent-side API (source = agent, kept apart from user intent) --------
    def add_assumption(self, statement: str, note: str | None = None) -> IntentItem:
        return self._new(dict(type="assumption", statement=statement), Source("agent", note=note),
                         "agent assumption", change_type="annotation", status="unverified")

    def set_assumption_status(self, item_id: str, status: str, source: Source) -> None:
        assert status in ("verified", "rejected", "unverified")
        self._update(item_id, source, f"assumption {status}", status=status)

    def add_open_question(self, statement: str, blocking: bool = False, source: Source | None = None) -> IntentItem:
        return self._new(dict(type="open_question", statement=statement), source or Source("agent"),
                         "open question", change_type="annotation", blocking=blocking)

    def resolve_question(self, item_id: str, decision: str, rationale: str, source: Source) -> IntentItem:
        self._update(item_id, source, "question resolved", status="resolved")
        return self.record_decision(decision, rationale, source)

    def record_decision(self, statement: str, rationale: str, source: Source) -> IntentItem:
        return self._new(dict(type="decision", statement=statement), source, rationale, rationale=rationale)

    # --- handlers ------------------------------------------------------------
    def _commit(self, c: Candidate) -> None:
        f, src = c.features, Source("user", c.message_id)
        rtype, t = self._relation(f, c.id)

        if isinstance(t, Candidate):  # firmer version of a pending candidate
            item = self._add_item(f, src, c.policy_reason)
            t.status, t.item_id = "merged", item.id
            item.reinforced_by.append(t.message_id)
            c.item_id = item.id
        elif rtype == "conflict":
            c.item_id = t.id
            if t.kind == "constraint" and t.strength == "hard":
                # ponytail: hard constraints are never auto-replaced; held until an approval flow exists (M2+)
                c.status = "deviation"
                return
            if f.get("scope") in ("task", "action"):
                # task-local change: the target stays active for other tasks; the resolver drops it in this task only
                f["relation"]["target_id"] = t.id
                c.item_id = self._add_item(f, src, f"overrides {t.id} in its task only: {c.text}", change_type="deviation").id
                return
            item = self._add_item(f, src, f"replaces {t.id}: {c.text}", change_type="deviation")
            self._update(t.id, src, f"superseded by {item.id}", status="superseded", superseded_by=item.id)
            c.item_id = item.id
        elif rtype == "reinforcement":
            bump = CORRECTION_PRIORITY_BUMP if f["is_correction"] else REPEAT_PRIORITY_BUMP
            why = "user correction" if f["is_correction"] else "user repeated"
            self._reinforce(t, c.message_id, bump, f"{why}: {c.text}")
            c.status, c.item_id = "reinforced", t.id
        elif rtype == "refinement":
            self._update(t.id, src, f"refined: {c.text}", change_type="refinement", statement=f["statement"],
                         reinforced_by=t.reinforced_by + [c.message_id])
            c.status, c.item_id = "refined", t.id
        else:
            c.item_id = self._add_item(f, src, c.policy_reason).id

    def _pending(self, c: Candidate) -> None:
        rtype, t = self._relation(c.features, c.id)
        if isinstance(t, Candidate):  # same hedged wish twice -> promote both
            item = self._add_item(c.features, Source("user", c.message_id), "pending repeated")
            t.status, t.item_id = "promoted", item.id
            item.reinforced_by.append(t.message_id)
            c.status, c.item_id = "promoted", item.id
        elif t is not None and rtype != "conflict":  # hedged mention of something already committed
            c.status, c.item_id = "merged", t.id
        elif t is not None:
            c.item_id = t.id  # stays pending, but points at what it would contradict

    def _ignore(self, c: Candidate) -> None:
        pass  # kept in candidate log only

    # --- relation resolution ---------------------------------------------------
    def _relation(self, f: dict, exclude: str) -> tuple[str, IntentItem | Candidate | None]:
        """-> (relation type, target). Target is an active user-intent item or a pending candidate."""
        rtype, tid = f["relation"]["type"], f["relation"]["target_id"]
        if rtype == "none" and self.extractor.links_by_id:
            return "none", None
        if tid:
            t = self.get_item(tid) or next((p for p in self.get_pending_candidates()
                                            if p.id == tid and p.id != exclude), None)
            return (rtype, t) if t is not None and self._valid(rtype, f, t) else ("none", None)
        if self.extractor.links_by_id:
            return "none", None
        # ponytail: id-less extractors (heuristic) resolve targets by shared topic key; crude but deterministic
        topics = set(f["topics"])
        rtype = "reinforcement" if rtype == "none" else rtype
        for t in [i for i in self.state.items if topics & set(i.topics)] +                  [p for p in self.get_pending_candidates() if p.id != exclude and topics & set(p.features["topics"])]:
            if self._valid(rtype, f, t):
                return rtype, t
        return "none", None

    def _valid(self, rtype: str, f: dict, t) -> bool:
        if isinstance(t, Candidate):
            return t.status == "pending" and rtype in ("reinforcement", "refinement")
        if t.status != "active" or t.kind not in USER_KINDS:
            return False
        # a constraint that serves a goal is not the goal restated; corrections and conflicts may cross kinds
        return rtype == "conflict" or f["is_correction"] or t.kind == _kind(f)

    # --- mutation primitives (all versioned changes go through here) -----------
    def _add_item(self, f: dict, source: Source, reason: str, change_type: str | None = None) -> IntentItem:
        kind = _kind(f)
        change_type = change_type or ("extension" if kind == "goal" else "refinement")
        extra = dict(strength=f.get("strength") or "soft") if kind == "constraint" else {}
        if kind == "goal" and (parent := self.get_item(f.get("parent_goal_id") or "")) and parent.kind == "goal":
            extra["parent_id"] = parent.id
        if kind == "decision":
            extra["rationale"] = f.get("rationale") or "user directive"
        if f.get("is_correction"):
            extra["priority"] = 1 + CORRECTION_PRIORITY_BUMP
        return self._new(f, source, reason, change_type=change_type, **extra)

    def _new(self, f: dict, source: Source, reason: str, change_type: str = "refinement", **extra) -> IntentItem:
        kind = _kind(f)
        item = IntentItem(self._next_id(KINDS[kind]), kind, f["statement"], source, topics=list(f.get("topics", [])),
                          **extra)
        self.state.items.append(item)
        self._log(change_type, item.id, None, asdict(item), reason, source)
        return item

    def _update(self, item_id: str, source: Source, reason: str, change_type: str = "status", **changes) -> None:
        item = self.get_item(item_id)
        before = asdict(item)
        for k, v in changes.items():
            setattr(item, k, v)
        item.updated_at = now()
        self._log(change_type, item.id, before, asdict(item), reason, source)

    def _reinforce(self, item: IntentItem, mid: str, bump: int, reason: str) -> None:
        self._update(item.id, Source("user", mid), reason, change_type="reinforcement",
                     priority=item.priority + bump, reinforced_by=item.reinforced_by + [mid])

    def _log(self, change_type, item_id, before, after, reason, source) -> None:
        self.state.version += 1
        self.state.history.append(Change(self.state.version, change_type, item_id, before, after, reason, source))
        self.save()  # ponytail: rewrites whole file per change; append-only log if state grows large

    # --- helpers -----------------------------------------------------------
    def _next_id(self, prefix: str) -> str:
        n = self.state.counters.get(prefix, 0) + 1
        self.state.counters[prefix] = n
        return f"{prefix}{n}"

    def _require_candidate(self, cid: str) -> Candidate:
        c = self.get_candidate(cid)
        if not c or c.status not in ("pending", "ignored"):
            raise ValueError(f"{cid}: not a pending/ignored candidate")
        return c

    def _context(self) -> str:
        lines = [f"{i.id} [{i.kind}{'/' + i.strength if i.strength else ''}] {i.statement} topics={i.topics}"
                 for i in self.state.items if i.status == "active"]
        lines += [f"{c.id} [pending {c.features['type']}] {c.features['statement']} topics={c.features['topics']}"
                  for c in self.get_pending_candidates()]
        return "\n".join(lines)

    def _conversation(self, exclude: str, n: int = CONVERSATION_WINDOW) -> str:
        msgs = [m for m in self.state.messages if m["id"] != exclude][-n:]
        return "\n".join(f"[{m['id']} {m['role']}] {m['text']}" for m in msgs)


def _kind(f: dict) -> str:
    t = f["type"]
    return t if t in KINDS else "constraint"
