"""Candidate extraction: user message -> list of feature dicts (see FEATURE_SCHEMA).

Two extractors share one output shape:
- LLMExtractor: structured classification through any provider with complete_json(prompt, schema).
- HeuristicExtractor: offline, deterministic, Korean marker rules. Used for tests / no sign-in.
Edit PROMPT / markers here; the commit/pending/ignore decision lives in policy.py.
"""
from __future__ import annotations

import re

RELATION_TYPES = ["reinforcement", "refinement", "conflict", "none"]

FEATURE = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidate", "type", "statement", "scope", "persistence", "impact", "explicitness",
                 "strength", "is_correction", "relation", "parent_goal_id", "topics", "rationale"],
    "properties": {
        "candidate": {"type": "boolean"},
        "type": {"enum": ["goal", "constraint", "success_criterion", "decision", "instruction", "other"]},
        "statement": {"type": "string"},
        "scope": {"enum": ["action", "task", "project"]},
        "persistence": {"enum": ["low", "medium", "high"]},
        "impact": {"enum": ["low", "medium", "high"]},
        "explicitness": {"enum": ["explicit", "implicit", "inferred"]},
        "strength": {"type": ["string", "null"], "enum": ["hard", "soft", None]},
        "is_correction": {"type": "boolean"},
        "relation": {
            "type": "object",
            "additionalProperties": False,
            "required": ["type", "target_id"],
            "properties": {"type": {"enum": RELATION_TYPES}, "target_id": {"type": ["string", "null"]}},
        },
        "parent_goal_id": {"type": ["string", "null"]},
        "topics": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
}
FEATURE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidates"],
    "properties": {"candidates": {"type": "array", "items": FEATURE}},
}

PROMPT = """You are the Intent Extractor of Pablo. Pablo keeps the user's durable intent
(goals, constraints, success criteria, decisions) separate from one-off instructions,
plans, and the agent's own guesses.

Classify the NEW USER MESSAGE. Return 0..n candidates (usually 1). For each:
- type: goal | constraint | success_criterion | decision | instruction (one-off action) | other
- statement: short normalized statement in the user's language, no hedging words.
  Resolve references ("그거", "아까 말한 것", "원래대로") using the conversation, but state only
  what the USER wants; never copy the agent's proposal as a requirement.
- scope: action (this step only) | task | project
- persistence: will this still apply after the current action? low | medium | high
- impact: if forgotten, does the result change meaningfully? low | medium | high
- explicitness: explicit (user said it clearly) | implicit (hedged, "~것 같은데", "~긴 해") | inferred (your guess)
- strength (constraints only, else null):
  hard = explicit obligation or prohibition ("반드시", "꼭", "절대", "~해야 해", "~하지 마", "must", "never")
  soft = preference or condition ("가능하면", "우선", "선호", "~있으면", "되도록", "편하다")
  If unsure, choose soft. A correction alone does NOT make something hard.
- is_correction: user corrects the agent or repeats an earlier demand ("아니 ~라고 했잖아",
  "그거 말고", "내가 아까 말했잖아", "원래대로 해", "그 방식 쓰지 말라고 했잖아")
- relation: how this candidate relates to ONE existing intent item or pending candidate (K..):
  reinforcement = the SAME requirement restated, repeated, or corrected-back-to
                  (also: a firmer version of a pending candidate)
  refinement    = the same requirement made more specific (narrows it, does not change direction)
  conflict      = asks for something that contradicts / replaces an existing item, even "just this once"
  none          = new subject. A constraint that merely SERVES a goal is "none" with that goal
  target_id     = the related item / candidate id, null when type is none
- parent_goal_id: for type=goal only, the id of the broader goal this one is a sub-goal of; else null.
  Goal dependency is NOT a relation.
- topics: 1-2 short lowercase English keys naming THIS requirement's own subject
  (e.g. official-code, eval-protocol), never the project/goal context
- rationale: one line, why you classified it so

Do NOT invent requirements. Plans and step orders are not intent.

CURRENT INTENT AND PENDING CANDIDATES:
{context}

RECENT CONVERSATION (only for resolving references; agent lines are NOT user intent):
{conversation}

NEW USER MESSAGE ({message_id}):
{text}
"""


class LLMExtractor:
    name = "llm"
    links_by_id = True  # engine trusts relation.target_id, ignores topic overlap

    def __init__(self, provider):
        self.provider = provider

    def extract(self, text: str, message_id: str, context: str, conversation: str) -> list[dict]:
        prompt = PROMPT.format(context=context or "(empty)", conversation=conversation or "(none)",
                               message_id=message_id, text=text)
        return self.provider.complete_json(prompt, FEATURE_SCHEMA)["candidates"]


# --- heuristic -------------------------------------------------------------
# ponytail: regex markers tuned on the M1/M1.1 cases only; LLMExtractor is the real classifier.
# Relation targets are left null; the engine resolves them by topic overlap for this extractor.

TOPIC_RULES = [
    (r"공식.*(코드|repo|레포|구현|implementation)|official", "official-impl"),
    (r"pytorch|파이토치", "framework-pytorch"),
    (r"tensorflow|텐서플로", "framework-tensorflow"),
    (r"평가|evaluation|protocol|metric|split", "eval-protocol"),
    (r"baseline|재현", "baseline-repro"),
    (r"readme", "readme"),
]
CORRECTION = r"^아니|했잖아|라고 했|말했잖|하랬잖|그거 말고|원래대로"
CHANGE = r"바꾸자|바꿔|으로 변경|대신 .*(하자|쓰자)"
ONE_OFF = r"^(일단|먼저|지금)|부터 |먼저 .*(보고|읽|확인)"
HEDGE = r"것 같|긴 한데|긴 해|좋을 것|아마|면 좋겠|싶은데|나을 듯"
HARD = r"반드시|꼭 |그대로 유지|해야 (돼|해|한다|합니다)|절대|무조건|하지 마|\bmust\b|\bnever\b"
SUCCESS = r"성공|비교 가능|달성하면"
DECISION = r"말고 .*(하자|가자)|(으로|로) (하자|가자|결정)"
PREFERENCE = r"있으면|가능하면|우선|선호|되도록|써\.?$|사용해"
REQUEST = r"해\s?줘|해주세요|해 주세요"


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


class HeuristicExtractor:
    name = "heuristic"
    links_by_id = False

    def extract(self, text: str, message_id: str, context: str, conversation: str) -> list[dict]:
        t = text.strip()
        topics = [k for p, k in TOPIC_RULES if _has(p, t)]
        f = dict(candidate=True, type="other", statement=t.rstrip("."), scope="task", persistence="medium",
                 impact="medium", explicitness="explicit", strength=None, is_correction=False,
                 relation={"type": "none", "target_id": None}, parent_goal_id=None, topics=topics, rationale="")

        def hit(rationale, relation="none", **kw):
            f.update(kw, rationale=rationale, relation={"type": relation, "target_id": None})
            return [f]

        constraint = dict(type="constraint", scope="project", persistence="high", impact="high")
        if _has(CORRECTION, t):
            return hit("correction marker", "reinforcement", **constraint, is_correction=True, strength="soft")
        if _has(CHANGE, t):
            return hit("change marker", "conflict", **constraint, strength="soft")
        if _has(ONE_OFF, t) and not _has(HARD, t):
            return hit("one-off step marker", type="instruction", scope="action", persistence="low", impact="low")
        if _has(HEDGE, t):
            return hit("hedged wording", **{**constraint, "persistence": "medium"}, explicitness="implicit",
                       strength="soft")
        if _has(HARD, t):
            return hit("obligation/prohibition marker", **constraint, strength="hard")
        if _has(SUCCESS, t):
            return hit("success marker", type="success_criterion", persistence="high", impact="high")
        if _has(DECISION, t):
            return hit("decision marker", type="decision", scope="project", persistence="high", impact="high")
        if _has(PREFERENCE, t):
            return hit("preference / condition marker", **constraint, strength="soft")
        if _has(REQUEST, t):
            return hit("task request", type="goal", scope="project", persistence="high", impact="high")
        return hit("no intent marker", candidate=False)
