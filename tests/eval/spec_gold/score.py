"""D3 (0.8): how well `spec` reads a paper's reproduction conditions, against a gold set a person confirmed.

  gold file  tests/eval/spec_gold/<key>.json
             {paper, arxiv, version, sha256, conditions: [{id, category, statement, value, quote, page, status, note}]}
             status: candidate (drafted by a session from the paper) | confirmed (a person checked it) | rejected
  score      python tests/eval/spec_gold/score.py <gold.json> <state dir> [--task T1] [--all]
             -> recall (confirmed gold conditions some extraction matches), precision (extractions that match a
                confirmed condition), and the lists behind both numbers. --all also counts candidates (a dry run
                before anyone confirmed the gold).

A match is deterministic, never a model's judgement:
  1. place: the extraction's anchor and the gold quote (anchored now in the same PDF, pdf.anchor) overlap on one page;
     a result must also agree on its value (review: a table row quoted right with its numbers paired wrong overlaps
     the gold too); a result that only overlaps is listed under place_only, for a person to read;
  2. value: same category, and each value is in the other (skill.has_value: numbers by value, words case-insensitive),
     for values that code has to spell out (skill.checkable).
An extraction that matches nothing is not wrong by definition: it is listed for review (the gold may miss it).
Precision counts what a reproduction is held to (setting, result, no kind); a fact or scope extraction is apart (⑥):
one that overlaps a gold condition is a kind miss (the gold holds only settings and results).
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "src"))

from pablo_v2.skill import pdf  # noqa: E402
from pablo_v2.skill.evidence import AnchorRejected  # noqa: E402
from pablo_v2.skill.skill import checkable, has_value  # noqa: E402


def gold_spans(gold: dict, pages: list[str], everything: bool = False) -> list[dict]:
    """The gold conditions to score, each with where its quote is in this PDF. A quote that no longer anchors (another
    version of the paper) is reported, never silently skipped."""
    out = []
    for g in gold["conditions"]:
        if g.get("status") == "rejected" or (g.get("status") != "confirmed" and not everything):
            continue
        try:
            _, sel = pdf.anchor(pages, g["quote"], g.get("page"))
            out.append({**g, "at": (sel["page"], sel["start"], sel["end"])})
        except AnchorRejected as e:
            out.append({**g, "at": None, "why": str(e)})
    return out


def extracted(state_dir: str, task: str) -> list[dict]:
    """The task's live stated conditions from a `spec` run, with their anchors (page, start, end)."""
    with open(os.path.join(state_dir, "skill.json"), encoding="utf-8") as f:
        st = json.load(f)
    anchors = {a["id"]: a for a in st.get("anchors", [])}
    out = []
    for c in st["checks"]:
        if c.get("task_id") != task or not c.get("spec") or c["spec"].get("missing") or c["research_state"] == "waived":
            continue
        link = next((x for x in st.get("links", []) if x["target_id"] == c["id"]), None)
        a = anchors.get(link["evidence_id"]) if link else None
        out.append({"id": c["id"], "category": c["spec"]["category"], "kind": c["spec"].get("kind"), "statement": c["requirement"],
                    "value": c["spec"].get("value", ""), "quote": a["quote"]["exact"] if a else "",
                    "at": (a["selector"]["page"], a["selector"]["start"], a["selector"]["end"]) if a else None})
    return out


def overlaps(e: dict, g: dict) -> bool:
    return bool(e["at"] and g["at"] and e["at"][0] == g["at"][0] and e["at"][1] < g["at"][2] and g["at"][1] < e["at"][2])


def agree(e: dict, g: dict) -> bool:
    return checkable(g["value"]) and checkable(e["value"]) and has_value(e["value"], g["value"]) and has_value(g["value"], e["value"])


def matches(e: dict, g: dict) -> str | None:
    """-> "place" | "value" | None."""
    if overlaps(e, g):
        result = g["category"] == "result" or g.get("kind") == "result" or e["category"] == "result"
        if not result or agree(e, g):
            return "place"
    if e["category"] == g["category"] and agree(e, g):
        return "value"
    return None


def score(gold: dict, pages: list[str], ex: list[dict], everything: bool = False) -> dict:
    gs = gold_spans(gold, pages, everything)
    aside = [e for e in ex if e.get("kind") in ("fact", "scope")]
    ex = [e for e in ex if e not in aside]
    pairs = [(e, g, how) for e in ex for g in gs if (how := matches(e, g))]
    hit_g = {g["id"] for _, g, _ in pairs}
    hit_e = {e["id"] for e, _, _ in pairs}
    return {
        "gold": len(gs), "extracted": len(ex),
        "place_only": [{"gold": g["id"], "check": e["id"], "gold_value": g["value"], "value": e["value"], "statement": e["statement"]}
                       for e in ex for g in gs if overlaps(e, g) and not matches(e, g)],
        "aside": len(aside),
        "kind_misses": [{"check": e["id"], "kind": e["kind"], "gold": g["id"], "statement": e["statement"]}
                        for e in aside for g in gs if overlaps(e, g)],
        "recall": round(len(hit_g) / len(gs), 3) if gs else None,
        "precision": round(len(hit_e) / len(ex), 3) if ex else None,
        "matched": [{"gold": g["id"], "check": e["id"], "how": how, "statement": g["statement"]} for e, g, how in pairs],
        "missed": [{"gold": g["id"], "category": g["category"], "statement": g["statement"], "page": g.get("page"),
                    **({"why": g["why"]} if g.get("why") else {})} for g in gs if g["id"] not in hit_g],
        "unmatched": [{"check": e["id"], "category": e["category"], "statement": e["statement"],
                       "page": e["at"] and e["at"][0]} for e in ex if e["id"] not in hit_e],
        "unanchored_gold": [g["id"] for g in gs if not g["at"]],
    }


def markdown(name: str, r: dict) -> str:
    pct = lambda x: "-" if x is None else f"{100 * x:.0f}%"  # noqa: E731
    out = [f"### {name}", "",
           f"재현율 {pct(r['recall'])} (정답 {r['gold']}개 중 {r['gold'] - len(r['missed'])}개를 뽑음) · "
           f"정밀도 {pct(r['precision'])} (뽑은 {r['extracted']}개 중 {r['extracted'] - len(r['unmatched'])}개가 정답과 맞음)", ""]
    if r["missed"]:
        out += ["놓친 정답 조건:", ""] + [f"- [{x['category']}] {x['statement']} (p.{x['page']})" for x in r["missed"]] + [""]
    if r["unmatched"]:
        out += ["정답에 없는 추출 (틀린 것인지, 정답이 빠뜨린 것인지 사람이 볼 것):", ""] + \
               [f"- [{x['category']}] {x['statement']} (p.{x['page']})" for x in r["unmatched"]] + [""]
    if r["place_only"]:
        out += ["정답과 같은 자리를 인용했지만 값이 다른 결과 (숫자와 열의 짝을 사람이 볼 것):", ""] + \
               [f"- {x['statement']} (값 {x['value']}, 정답 {x['gold_value']})" for x in r["place_only"]] + [""]
    if r["kind_misses"]:
        out += [f"서술·실험 범위로 분류했지만 정답은 따를 조건인 것 {len(r['kind_misses'])}개 (정밀도 분모 밖, 따로 셈):", ""] + \
               [f"- [{x['kind']}] {x['statement']} (정답 {x['gold']})" for x in r["kind_misses"]] + [""]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    gold_path, state = argv[0], argv[1]
    task = argv[argv.index("--task") + 1] if "--task" in argv else "T1"
    with open(gold_path, encoding="utf-8") as f:
        gold = json.load(f)
    pdf_path = argv[argv.index("--pdf") + 1] if "--pdf" in argv else os.path.join(os.path.dirname(os.path.abspath(gold_path)), gold["pdf"])
    with open(pdf_path, "rb") as f:
        data = f.read()
    if gold.get("sha256") and pdf.content_hash(data).removeprefix("sha256:") != gold["sha256"].removeprefix("sha256:"):
        print(f"warning: {pdf_path} is not the version the gold was written on", file=sys.stderr)
    r = score(gold, pdf.pages(data), extracted(state, task), "--all" in argv)
    print(json.dumps(r, ensure_ascii=False, indent=1) if "--json" in argv else markdown(gold["paper"], r))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
