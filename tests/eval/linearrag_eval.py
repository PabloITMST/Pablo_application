"""M3.3 B eval (evidence selection) on LinearRAG.pdf: a keyword baseline vs Pablo's ask, scored against the gold spans.
Run: python tests/eval/linearrag_eval.py [<state_dir> <asks.json>]   (no args: the baseline only)
     python tests/eval/linearrag_eval.py fixture <state_dir> [--gold]   (state for check.js --pdf)
asks.json = [{id: "Q1", check: "SC1", ms}] from `check.js --pdf --ask`; the cited anchors are read from <state_dir>/skill.json.

Rules (fixed before running):
- Page Hit 1: a citation is on a gold page.  Evidence Hit 1: a citation overlaps a gold span (same page, char ranges meet).
- Noise: share of cited characters outside every gold span; <= 1/3 low, <= 2/3 medium, else high.
- Relevance: correct (1) = Evidence Hit and every `must` and `consistency` regex matches and no `forbid` matches;
  partial (0.5) = Page Hit or Evidence Hit or all `must`; else miss (0). `need_all`: a gold span not cited -> miss
  (e.g. a claim checked against a table needs both). `consistency` = the answer states where the sources disagree.
  A gold span's `alt` exacts (another row of the same table it is compared with) count as that span (M3.3.1). The text checked is the answer (Pablo) or the cited text (baseline: extractive).
- Baseline: page text split into sentences/lines; score = number of the question's gold keywords present (pdf.key, no case);
  the top 2 segments are its citations (gold has 1-2 spans per question).
"""
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from pablo_v2.skill import pdf  # noqa: E402

GOLD = json.load(open(os.path.join(ROOT, "tests", "eval", "linearrag_gold.json"), encoding="utf-8"))
PS = pdf.pages(open(os.path.join(ROOT, GOLD["pdf"]), "rb").read())
REL = {"correct": 1, "partial": 0.5, "miss": 0}


def spans(q, alt=False):
    return [[pdf.locate(PS, x, g["page"]) for x in [g["exact"]] + (g.get("alt", []) if alt else [])] for g in q["gold"]]         if alt else [pdf.locate(PS, g["exact"], g["page"]) for g in q["gold"]]


def baseline(q, k=2):
    segs = [(n, m.start(), m.end()) for n, t in enumerate(PS, 1)
            for m in re.finditer(r"[^\n]+?(?:[.!?](?=\s|[A-Z(]|$)|\n|$)", t) if m.end() > m.start()]
    kws = [pdf.key(w.lower())[0] for w in q["keywords"]]
    score = lambda s: sum(w in pdf.key(PS[s[0] - 1][s[1]:s[2]].lower())[0] for w in kws)  # noqa: E731
    top = sorted(segs, key=lambda s: -score(s))[:k]
    return top, " ".join(PS[n - 1][s:e] for n, s, e in top)


def score(q, cites, text):
    alts = spans(q, alt=True)
    gold = [x for a in alts for x in a]
    meet = lambda c, g: c[0] == g[0] and c[1] < g[2] and g[1] < c[2]  # noqa: E731
    page = int(any(c[0] in {g[0] for g in gold} for c in cites))
    hits = [any(meet(c, g) for c in cites for g in a) for a in alts]
    hit = int(any(hits))
    total = sum(e - s for _, s, e in cites) or 1
    inside = sum(max(0, min(e, g[2]) - max(s, g[1])) for n, s, e in cites for g in gold if g[0] == n)
    out = 1 - min(inside, total) / total
    noise = "low" if out <= 1 / 3 else "medium" if out <= 2 / 3 else "high"
    must = all(re.search(r, text, re.I) for r in q.get("must", []))
    bad = any(re.search(r, text) for r in q.get("forbid", []))
    con = all(re.search(r, text) for r in q.get("consistency", []))
    rel = ("miss" if q.get("need_all") and not all(hits) else "correct" if hit and must and con and not bad
           else "partial" if page or hit or must else "miss")
    note = "recall 1위 단정" if q["id"] == "Q10" and re.search(r"recall.{0,30}(가장|최고|1위|highest|best)", text, re.I) else ""
    return {"page": page, "evidence": hit, "relevance": rel, "noise": noise, "outside": round(out, 2), "must": must,
            "forbid": bad, "consistency": con, "note": note}


def pablo(state_dir, ask):
    st = json.load(open(os.path.join(state_dir, "skill.json"), encoding="utf-8"))
    anchors = {a["id"]: a["selector"] for a in st["anchors"]}
    check = next(c for c in st["checks"] if c["id"] == ask["check"])
    cites = [(anchors[x["evidence_id"]]["page"], anchors[x["evidence_id"]]["start"], anchors[x["evidence_id"]]["end"])
             for x in st["links"] if x["target_id"] == ask["check"]]
    return cites, check["conclusion"] or ""


def table(name, rows):
    print(f"\n{name}\n| Q | Page | Evidence | Relevance | Noise (outside) | ms | note |\n|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['id']} | {r['page']} | {r['evidence']} | {r['relevance']} | {r['noise']} ({r['outside']}) | "
              f"{r.get('ms', '-')} | {r['note'] or ('forbid' if r['forbid'] else '')} |")
    n = len(rows)
    print(f"| 합계 | {sum(r['page'] for r in rows)}/{n} | {sum(r['evidence'] for r in rows)}/{n} | "
          f"{sum(REL[r['relevance']] for r in rows) / n:.0%} | low {sum(r['noise'] == 'low' for r in rows)}/{n} | | |")


def fixture(state_dir, gold):
    """A fresh state with the captured PDF and task T1; gold: one check per question citing its gold spans (A eval)."""
    from pablo_v2.intent.engine import IntentEngine
    from pablo_v2.skill.skill import PabloSkill
    from pablo_v2.skill.viewer import render_html
    s = PabloSkill(IntentEngine(), path=os.path.join(state_dir, "skill.json"))
    src = s.capture_pdf(os.path.abspath(os.path.join(ROOT, GOLD["pdf"])))
    t = s.start_task("LinearRAG 논문 읽기", checks=[])
    out = []
    for q in GOLD["questions"] if gold else []:
        es = [s.add_anchor(src.id, g["exact"], page=g["page"]) for g in q["gold"]]
        sc = s.add_check(t.id, q["question"], "USEFUL")
        s.complete_check(sc.id, "VERIFIED", q["expected"] + "".join(f"[{i}]" for i in range(1, len(es) + 1)),
                         [{"tier": 4, "type": "pdf", "title": src.title, "url": src.locator, "supports": [a.id for a in es]}])
        for a, g in zip(es, q["gold"]):
            s.link_evidence(a.id, sc.id, "supports", g.get("role", g["kind"]))
            out.append({"q": q["id"], "e": a.id, "page": g["page"], "kind": g["kind"], "exact": g["exact"]})
    view = os.path.join(state_dir, f"view-{t.id}.html")
    open(view, "w", encoding="utf-8").write(render_html(s, t.id))
    print(json.dumps({"view": view, "gold": out}, ensure_ascii=False))


def main(argv):
    if argv[:1] == ["fixture"]:
        return fixture(argv[1], "--gold" in argv)
    qs = {q["id"]: q for q in GOLD["questions"]}
    base = [{"id": q["id"], **score(q, *baseline(q))} for q in qs.values()]
    table("keyword baseline", base)
    out = {"baseline": base}
    if len(argv) == 2:
        asks = json.load(open(argv[1], encoding="utf-8"))
        out["pablo"] = [{"id": a["id"], "ms": a.get("ms"), **score(qs[a["id"]], *pablo(argv[0], a))} for a in asks]
        table("Pablo ask", out["pablo"])
        json.dump(out, open(os.path.join(argv[0], "eval.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    q = GOLD["questions"][2]  # self-check (Q3): both spans + the disagreement stated -> correct; silent -> partial
    g = spans(q)
    ok = "논문은 over 77% 줄였다고 주장한다 [1]. Table 2에서 249.78초는 E2GraphRAG 대비 약 53%라 모든 baseline 대비 77%로 해석할 수 없다 [2]."
    assert score(q, g, ok)["relevance"] == "correct" and score(q, g, "")["noise"] == "low"
    assert score(q, g, "77% 줄였다 [1]. 249.78초로 모든 baseline(534.60–4933.22초)보다 낮다 [2].")["relevance"] == "partial"
    assert score(q, [g[0], spans(q, alt=True)[1][1]], ok)["relevance"] == "correct"  # the compared row counts
    assert score(q, g[:1], ok)["relevance"] == "miss" and score(q, [(1, 0, 10)], "")["relevance"] == "miss"
    q9 = GOLD["questions"][8]
    assert score(q9, spans(q9), "메모리·계산 효율 근거에는 복잡도 분석 O(|P|)과 실측이 모두 포함됩니다.")["relevance"] == "partial"
    assert score(q9, spans(q9), "복잡도 분석 O(|P|·T)이다. 메모리 실측은 없다.")["relevance"] == "correct"
    main(sys.argv[1:])
