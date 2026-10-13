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
HARD = (r"반드시|꼭 |그대로 유지|해야 (돼|해|한다|합니다)|절대|무조건|하지 마|지 ?마(?:세요|라)?(?![가-힣])|지 말(?:고|아)|안 ?돼|금지|\bmust\b|\bnever\b"
        # 0.8 review: the usual ways a researcher writes a rule ("~면 안 됨", "~없게", "~만 써", "~할 것", "~지 않는다")
        r"|안 ?(됨|된다|됩니다)|(없|않)(게|도록)|만 (써|쓰|사용)|[가-힣] 것\.?$|지 않(는다|음|습니다)")
SOFTEN = r"가능하면|되도록|선호|웬만하면|할 수 있으면"  # "가능하면 PyTorch만 써": a wish, even with a rule's ending
SUCCESS = r"성공|비교 가능|달성하면"
DECISION = r"말고 .*(하자|가자)|(으로|로) (하자|가자|결정)"
PREFERENCE = r"있으면|가능하면|우선|선호|되도록|써\.?$|사용해"
REQUEST = r"해\s?줘|해주세요|해 주세요"


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


# a chat message to the desktop agent: "X 해줘/알려줘" + "파일은 읽지 마" -> the prohibition qualifies this request only.
# It stays a criterion of the task when it says it lasts ("절대", "앞으로", ...) or when the message is only criteria.
ASKING = r"줘|주세요|줄래|할래|설명해|\?\s*$"
MARKED = r"절대|반드시|항상|앞으로|계속|무조건|언제나|매번|이 작업 (내내|동안|전체)|가능하면|되도록|선호"


RULE_LIKE = r"(해|내|써|둬|라|것|돼|됨|된다|한다|함|하자|지켜|유지해|맞춰)\s*[.!]?$"


def reads_like_rule(text: str) -> bool:
    """③ a chat sentence the reader could not classify is shown to the user only when it ends like an instruction
    ("평균 내", "~할 것"), so "고마워" or a question is not."""
    return _has(RULE_LIKE, text.strip())


def standing_criteria(text: str) -> list[str]:
    """The sentences of a chat message that are the task's criteria (not the request, not a one-off qualifier)."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?。])\s+|\n+", text) if p.strip()]
    asks = [p for p in parts if _has(ASKING, p) and not _has(MARKED, p)]  # plain requests ("가능하면 ~로 짜줘" is a wish)
    if not asks:
        return parts
    return [p for p in parts if p not in asks and _has(MARKED, p)]


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
        if _has(HARD, t) and not _has(SOFTEN, t):
            return hit("obligation/prohibition marker", **constraint, strength="hard")
        if _has(HARD, t):
            return hit("softened rule", **constraint, strength="soft")
        if _has(SUCCESS, t):
            return hit("success marker", type="success_criterion", persistence="high", impact="high")
        if _has(DECISION, t):
            return hit("decision marker", type="decision", scope="project", persistence="high", impact="high")
        if _has(PREFERENCE, t):
            return hit("preference / condition marker", **constraint, strength="soft")
        if _has(REQUEST, t):
            return hit("task request", type="goal", scope="project", persistence="high", impact="high")
        return hit("no intent marker", candidate=False)
