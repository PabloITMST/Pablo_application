"""Scoring generated answers."""
from statistics import mean


def contain_acc(pred: str, gold: str) -> float:
    return float(gold.lower() in pred.lower())


def gpt_acc(pred: str, gold: str, client, model: str) -> float:
    q = f"Does the answer match the ground truth?\nAnswer: {pred}\nGround truth: {gold}\nReply yes or no."
    r = client.chat.completions.create(model=model, messages=[{"role": "user", "content": q}])
    return float(r.choices[0].message.content.strip().lower().startswith("yes"))


def score(dataset: str, preds: list[str], golds: list[str], client, cfg: dict) -> dict:
    out = {"gpt_acc": 100 * mean(gpt_acc(p, g, client, cfg["llm"]) for p, g in zip(preds, golds))}
    if dataset != "medical":  # Medical answers are long descriptions: GPT-ACC only
        out["contain_acc"] = 100 * mean(contain_acc(p, g) for p, g in zip(preds, golds))
    return out
