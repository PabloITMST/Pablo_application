"""Human view of the same IntentState (Markdown-ish text). Raw JSON stays in the state file."""
from __future__ import annotations

from .engine import IntentEngine


def _src(i) -> str:
    s = i.source
    return {"user": f"user {s.ref}", "agent": "agent 추론", "evidence": f"evidence {s.ref}"}.get(s.type, s.type)


def _section(title: str, items, fmt) -> list[str]:
    return [f"\n## {title}"] + ([f"- {fmt(i)}" for i in items] or ["- (없음)"])


def render_intent(e: IntentEngine) -> str:
    def c(i):
        prio = f" ▲{i.priority}" if i.priority > 1 else ""
        return f"[{i.id}] {i.statement} ({i.strength}{prio}, {_src(i)})"

    def basic(i):
        return f"[{i.id}] {i.statement} ({_src(i)})"

    out = [f"# Current Intent  (v{e.state.version})"]
    out += _section("목표", e.get_active_goals(), basic)
    out += _section("반드시 지킬 것 (hard)", [i for i in e.get_active_constraints() if i.strength == "hard"], c)
    out += _section("가능하면 지킬 것 (soft)", [i for i in e.get_active_constraints() if i.strength != "hard"], c)
    out += _section("성공 조건", e.get_success_criteria(), basic)
    out += _section("현재 결정", e.get_decisions(), lambda i: f"[{i.id}] {i.statement} — 이유: {i.rationale} ({_src(i)})")
    out += _section("Agent 가정 (사용자 요구 아님)", e.get_assumptions(),
                    lambda i: f"[{i.id}] {i.statement} [{i.status}]")
    out += _section("확인이 필요한 내용", e.get_open_questions(),
                    lambda i: f"[{i.id}] {i.statement}{' [blocking]' if i.blocking else ''}")
    out += _section("Deviation (hard constraint와 충돌, 미적용)", e.get_deviations(),
                    lambda k: f"[{k.id}] {k.features['statement']} ↯ {k.item_id} ({k.message_id})")
    out += _section("Pending (아직 확정 안 됨)", e.get_pending_candidates(),
                    lambda k: f"[{k.id}] {k.features['statement']} — {k.policy_reason} ({k.message_id})")
    return "\n".join(out)


def render_candidates(e: IntentEngine) -> str:
    rows = ["# Candidate Log", "id  | msg | action  -> status     | item | type / relation / reason | text"]
    for k in e.state.candidates:
        f = k.features
        rows.append(f"{k.id:<3} | {k.message_id:<3} | {k.action:<7} -> {k.status:<10} | {k.item_id or '-':<4} | "
                    f"{f['type']}/{f.get('strength') or '-'} / {f['relation']['type']} / {k.policy_reason} | {k.text}")
    return "\n".join(rows)


def render_history(e: IntentEngine) -> str:
    rows = ["# Intent History"]
    for h in e.get_intent_history():
        after = h.after or {}
        detail = after.get("statement", "")
        if h.change_type == "reinforcement":
            detail += f"  priority {h.before['priority']} -> {after['priority']}"
        elif h.change_type == "status":
            detail += f"  status {h.before['status']} -> {after['status']}"
        rows.append(f"v{h.version:<3} {h.change_type:<13} {h.item_id:<4} {detail}  | {h.reason} "
                    f"[{h.source.type} {h.source.ref or ''}]".rstrip())
    return "\n".join(rows)
