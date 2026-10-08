"""Deterministic post-action review: judge observations -> alignment, step status, deviations, proposals.

Like guard.py, every status comes from a rule here, never from the model. Nothing here mutates Intent or
Plan: proposals name the existing API (IntentEngine.add_assumption / add_open_question /
set_assumption_status, PabloSkill.create_plan / add_check) the host may call after reading them.
"""
from __future__ import annotations

from .models import ISSUE_TYPES

PROGRESS = {"all": "completed", "part": "partial", "none": "unchanged"}


def review(*, verdict: str, decision: str | None, step: dict | None, executed: bool, changed_files: list[str],
           tests: list[dict], errors: list[str], facts: dict, check_ids: set[str], assumption_ids: set[str]) -> dict:
    """-> PostReview fields (minus ids). facts = judge observations, {} when there was nothing to observe."""
    devs = []

    def dev(kind, note):
        devs.append({"kind": kind, "note": note})

    if not executed:
        if decision == "proceed":
            dev("not_executed", "host decided proceed but did not execute")
        # defer / reject / BLOCK leave the step as it was; that is a decision, not a failure
        alignment = "not_executed"
        status = None if step is None else "blocked" if verdict == "BLOCK" else "unchanged"
    else:
        if verdict != "ALLOW" and decision != "proceed":
            dev("unapproved_execution", f"executed although the verdict was {verdict} and host decision {decision}")
        scope = facts["scope"]
        if scope["relation"] in ("superset", "different"):
            dev("scope_expanded" if scope["relation"] == "superset" else "different_action", scope["note"])
        extra = [f for f in facts["unapproved_files"] if f in changed_files]
        if extra:
            dev("unapproved_files", ", ".join(extra))
        if scope["relation"] == "subset":
            dev("partial", scope["note"])
        if decision and not facts["decision_consistent"]["consistent"]:
            dev("decision_mismatch", facts["decision_consistent"]["note"])
        failing = [t["name"] for t in tests if t["result"] == "fail"]
        failed = failing or not facts["outcome"]["succeeded"]
        if failed:
            dev("failed", "; ".join(failing + errors) or facts["outcome"]["note"])
        kinds = {d["kind"] for d in devs}
        alignment = ("failed" if failed else
                     "deviated" if kinds - {"partial"} else
                     "partial" if kinds else "aligned")
        progress = facts["step_progress"]["progress"]
        if step is None:
            status = None
        elif failed:
            status = "blocked" if progress == "none" else "partial"
        else:
            status = PROGRESS[progress]

    sc = lambda i: i if i in check_ids else None  # noqa: E731  judge may cite ids that do not exist
    issues = [{"type": x["type"] if x["type"] in ISSUE_TYPES else "other", "note": x["note"],
               "source_check_id": sc(x["source_check_id"])} for x in facts.get("research_issues", [])]

    intent_props = [{"api": "add_assumption", "args": {"statement": a}, "note": "found during execution"}
                    for a in facts.get("new_assumptions", [])]
    intent_props += [{"api": "add_open_question", "args": {"statement": q["statement"], "blocking": q["blocking"]},
                      "note": "found during execution"} for q in facts.get("new_questions", [])]
    plan_props = []
    for c in facts.get("contradicted", []):
        if c["ref_id"] in assumption_ids:
            intent_props.append({"api": "set_assumption_status", "args": {"item_id": c["ref_id"],
                                 "status": "rejected"}, "note": c["note"]})
        elif c["ref_id"] in check_ids:
            plan_props.append({"api": "add_check", "kind": "recheck_source", "target": c["ref_id"], "note": c["note"]})
    for i in issues:
        if i["source_check_id"] and i["source_check_id"] not in {p["target"] for p in plan_props}:
            plan_props.append({"api": "add_check", "kind": "recheck_source", "target": i["source_check_id"],
                               "note": f"research issue {i['type']}: {i['note']}"})
    if step is not None and executed:
        if status == "partial":
            plan_props.append({"api": "create_plan", "kind": "add_step", "target": step["id"],
                               "note": "remaining part of the step"})
        if alignment in ("deviated", "failed"):
            plan_props.append({"api": "create_plan", "kind": "revise_step", "target": step["id"],
                               "note": "; ".join(f"{d['kind']}: {d['note']}" for d in devs)})

    return dict(action_alignment=alignment, plan_step_status=status, deviations=devs,
                new_facts=[{"statement": f["statement"], "source_check_id": sc(f["source_check_id"])}
                           for f in facts.get("new_facts", [])],
                new_assumptions=list(facts.get("new_assumptions", [])),
                new_questions=list(facts.get("new_questions", [])),
                issues=issues, intent_update_proposals=intent_props, plan_update_proposals=plan_props)
