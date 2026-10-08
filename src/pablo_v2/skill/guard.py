"""Deterministic Pablo policy: research gate for completing checks, and the action verdict.

The semantic judge (judge.py) only reports facts (conflict level, justification relevance, cited checks).
Every ALLOW / WARN / BLOCK here comes from a numbered rule, so a verdict is always explainable as
"C1 clear conflict + hard -> G04 BLOCK", never "the model said so".
"""
from __future__ import annotations

from .models import AUTHORITATIVE_TIERS

SEVERITY = {"ALLOW": 0, "WARN": 1, "BLOCK": 2}
SUPPORTING_OUTCOMES = ("VERIFIED", "PARTIALLY_VERIFIED")
# ponytail: "official channels exhausted" = at least docs (tier 1) and official repo (tier 2) were searched.
# Per-requirement channel lists (e.g. "OpenAI SIWC docs") would be stricter; add when tier coverage proves too weak.
NOT_FOUND_REQUIRED_TIERS = (1, 2)

# Pablo's own governance, active whenever the skill is on; it does not depend on intent extraction.
# SP1 is the research gate (G01), SP2 is the bypass rule (S03/S04). SP3 is judged like a hard constraint.
SYSTEM_POLICIES = {
    "SP1": "REQUIRED external facts must be researched before planning.",
    "SP2": "Verified official mechanisms are not replaced with undocumented alternatives without justification.",
    "SP3": "Credentials and tokens are not read, copied or stored outside the component the documentation "
           "names as their owner.",
}
JUDGED_POLICIES = {"SP3": "hard"}


def completion_errors(check, outcome: str, sources: list[dict], stop_reason: str | None) -> list[str]:
    """Why this SourceCheck may not be completed with this outcome. Empty list = OK."""
    errs = []
    if outcome == "VERIFIED" and not any(s["tier"] in AUTHORITATIVE_TIERS for s in sources):
        errs.append("R01 VERIFIED needs a tier 1-4 source; tier 5-6 alone is at most PARTIALLY_VERIFIED")
    if outcome == "NOT_FOUND":
        if stop_reason != "official_channels_exhausted":
            errs.append(f"R02 NOT_FOUND needs stop_reason=official_channels_exhausted (got {stop_reason})")
        missing = sorted(set(NOT_FOUND_REQUIRED_TIERS) - {s["tier"] for s in check.searched})
        if missing:
            errs.append(f"R03 NOT_FOUND before searching official tier(s) {missing}: not found is not 'does not exist'")
    if outcome == "CONFLICTING" and len(sources) < 2:
        errs.append("R04 CONFLICTING needs the disagreeing sources (>= 2)")
    return errs


def decide(*, pending_required: list[str], step: dict | None, unverified: list[str], analysis: dict,
           constraints: dict[str, str], sources: dict[str, str | None],
           valid_support: list[str]) -> tuple[str, list[dict]]:
    """-> (verdict, rule hits). constraints: active constraint / system policy id -> hard|soft.
    sources: the task's source checks, id -> outcome (None = waived / pending).
    valid_support: checks the judge cited that are completed with a supporting outcome."""
    hits = []

    def hit(rule, verdict, reason):
        hits.append({"rule": rule, "verdict": verdict, "reason": reason})

    if pending_required:
        hit("G01", "BLOCK", f"REQUIRED research not completed: {pending_required}")
    if step is None:
        hit("G02", "WARN", "no plan step behind this action")
    elif unverified:
        hit("G03", "ALLOW", f"basis not officially verified, treat as estimate/workaround: {unverified}")

    j = analysis.get("justification") or {}
    justified = bool(j.get("present") and j.get("relevant"))
    for c in analysis.get("intent_conflicts", []):
        cid, level = c["intent_id"], c["level"]
        strength = constraints.get(cid)
        if strength is None or level == "none":
            continue  # judge cited something that is not an active constraint
        if strength == "hard":
            # ponytail: no exception / approval path for hard constraints in M2 (M1 deviation hold is the hook)
            if level == "clear":
                hit("G04", "BLOCK", f"{cid} hard constraint, clear conflict")
            else:
                hit("G05", "WARN", f"{cid} hard constraint, possible conflict")
        elif level == "possible":
            hit("G06", "ALLOW", f"{cid} soft constraint, possible conflict")
        elif not j.get("present"):
            hit("G07", "WARN", f"{cid} soft constraint, clear conflict, no justification")
        elif not j.get("relevant"):
            hit("G08", "WARN", f"{cid} soft constraint, justification does not address it")
        elif not valid_support:
            hit("G09", "WARN", f"{cid} soft constraint, justification not backed by a completed SourceCheck")
        else:
            hit("G10", "ALLOW", f"{cid} soft constraint, justified by {valid_support}")

    for c in analysis.get("source_conflicts", []):
        sid, kind = c["source_check_id"], c["kind"]
        if sid not in sources or kind == "none":
            continue  # judge cited a check outside this task
        outcome = sources[sid]
        if kind == "contradicts":
            # ponytail: no exception path, like hard constraints; a wrong conclusion is fixed by redoing the check
            if outcome == "VERIFIED":
                hit("S01", "BLOCK", f"contradicts the VERIFIED conclusion of {sid}")
            else:
                hit("S02", "WARN", f"contradicts {sid} ({outcome or 'unresearched'})")
        elif kind == "bypasses":
            if justified and valid_support:
                hit("S04", "ALLOW", f"bypasses the mechanism in {sid}, justified by {valid_support}")
            else:
                hit("S03", "WARN", f"bypasses the mechanism documented in {sid} without a source-backed reason")
        else:
            hit("S05", "ALLOW", f"possible conflict with {sid}")

    if step is not None and not (analysis.get("plan_alignment") or {}).get("follows_step", True):
        if justified:
            hit("D02", "ALLOW", f"departs from {step['id']}, reason given")
        else:
            hit("D01", "WARN", f"departs from {step['id']} without a relevant reason")

    verdict = max((h["verdict"] for h in hits), key=SEVERITY.get, default="ALLOW")
    return verdict, hits
