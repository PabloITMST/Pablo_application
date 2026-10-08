"""Deterministic promotion policy: extractor features -> commit | pending | ignore.

Ordered rules, first match wins. Edit here to change promotion behaviour.
"""


def _conflict(f):
    return f["relation"]["type"] == "conflict"


RULES = [
    (lambda f: not f["candidate"], "ignore", "not a durable intent"),
    # a conflict must surface even when phrased as one-off ("이번에는 ~로 바꾸자")
    (lambda f: _conflict(f) and f["explicitness"] == "explicit", "commit", "explicit change against existing intent"),
    (lambda f: _conflict(f), "pending", "hedged change against existing intent"),
    (lambda f: f["type"] in ("instruction", "other"), "ignore", "not a durable intent"),
    (lambda f: f["scope"] == "action" or f["persistence"] == "low", "ignore", "temporary / action-scoped"),
    (lambda f: f["is_correction"], "commit", "user correction"),
    (lambda f: f["explicitness"] != "explicit", "pending", "not explicit (hedged or inferred)"),
    (lambda f: f["impact"] == "low", "pending", "low impact"),
]
DEFAULT = ("commit", "explicit + persistent + impactful")


def decide(f: dict) -> tuple[str, str]:
    for cond, action, reason in RULES:
        if cond(f):
            return action, reason
    return DEFAULT
