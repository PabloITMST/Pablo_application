"""Read-only Pablo workspace (`view T1 --html`): one self-contained HTML file with every task of the state dir.

  sidebar        tasks
  conversation   the task as a user message; research, research issues, plan and guard verdicts as Pablo replies,
                 with citations [n] that point at the existing EvidenceAnchor ids
  context panel  one at a time, replaced in place: Source (captured snapshot + highlight; the live page opens in a
                 new tab with a #:~:text= fragment) | Intent | Plan | Trace ("왜?")

Python builds one JSON model; the page renders it with textContent only (no HTML from data).
Evidence is always the captured snapshot with the anchor's stored start/end (M3.1 offsets); a source's display
file (M3.2.1) only gives it blocks. STALE / UNRESOLVED keep their snapshot evidence, with a status line.
Internal ids are not shown as labels; they stay on elements (title / data-id / data-e).
"""
from __future__ import annotations

import json
import os
import re
from html import escape

from . import evidence, pdf
from .guard import SYSTEM_POLICIES
from .mascot import ART

STATUS = {
    ("VALID", None): "현재 원문에서도 같은 버전으로 확인됩니다.",
    ("VALID", "relocated"): "현재 원문에서 위치만 바뀌었고 같은 문맥으로 남아 있습니다.",
    ("STALE", "context_changed"): "현재 원문에서 앞뒤 문맥이 바뀌었습니다. 아래는 캡처 당시 원문입니다.",
    ("STALE", "ambiguous"): "현재 원문에 같은 문구가 여러 곳 있습니다. 아래는 캡처 당시 원문입니다.",
    ("UNRESOLVED", "not_found"): "현재 원문에서 이 구절을 확인할 수 없습니다. 아래는 캡처 당시 원문입니다.",
    ("UNRESOLVED", "fetch_failed"): "현재 원문을 가져오지 못했습니다. 아래는 캡처 당시 원문입니다.",
}
UNCHECKED = "아직 현재 원문과 대조하지 않았습니다."
# Pablo's own policies as the user reads them on a card (guard.SYSTEM_POLICIES is what the judge reads)
POLICY_TEXT = {"SP1": "꼭 필요한 외부 사실은 계획하기 전에 확인한다.",
               "SP2": "확인된 공식 방식을 근거 없이 비공식 방식으로 바꾸지 않는다.",
               "SP3": "토큰, API 키, 비밀번호 같은 자격 증명은 그 주인 구성 요소 밖에서 읽거나 옮기거나 저장하지 않는다."}


def model(s, task_id: str) -> dict:
    t = s.get_task(task_id)
    eng = s.intent
    prev = {i.superseded_by: i.statement for i in eng.get_current_intent().items if i.superseded_by}

    def items(xs):  # all: a project-wide criterion (changing it changes every task's); repro: removed only with a reason
        return [{"id": x.id, "text": x.statement, "prev": prev.get(x.id), "all": s.everywhere(x), "repro": s.is_repro_default(x)}
                for x in xs]

    def label(ref):  # intent item or system policy -> text
        it = eng.get_item(ref)
        return it.statement if it else POLICY_TEXT.get(ref, SYSTEM_POLICIES.get(ref, ref))

    anchors, sources, checks = {}, {}, {}

    def check(sc_id):
        if sc_id in checks:
            return checks[sc_id]
        c = s._find_check(sc_id)
        if not c:
            return None
        ev = []
        for link, a in s.evidence_for(c.id):
            ev.append(a.id)
            src = s.get_source(a.source_id)
            if src.id not in sources:
                text = s.snapshot_text(src)
                sources[src.id] = {"title": src.title, "url": src.locator, "captured_at": src.captured_at,
                                   "hash": src.version["content_hash"], "text": text,
                                   "intact": evidence.content_hash(text) == src.version["content_hash"],
                                   "display": s.snapshot_display(src)}
                if src.kind == "pdf":  # M3.3: the copied PDF is the version; text is its pages joined by \f
                    sources[src.id].update(kind="pdf", file=f"{src.id}.pdf", pages=text.count("\f") + 1,
                                           intact=pdf.content_hash(s.snapshot_pdf(src)) == src.version["content_hash"])
            r = a.resolution or {}
            at = pdf.offset(s.snapshot_text(src).split("\f"), a.selector["page"]) if src.kind == "pdf" else 0
            anchors[a.id] = {"source": src.id, "start": at + a.selector["start"], "end": at + a.selector["end"],
                             "page": a.selector.get("page"),
                             "exact": a.quote["exact"], "prefix": a.quote.get("prefix", ""),
                             "suffix": a.quote.get("suffix", ""), "status": a.status, "checked": r.get("at"),
                             "message": STATUS.get((a.status, r.get("reason")), UNCHECKED) if r else UNCHECKED,
                             "claim": link.note or c.conclusion or c.requirement, "check": c.id,
                             "relation": link.relation}
        of = (c.spec or c.matrix or {}).get("source_id")  # C1: which paper a condition / table cell is from, by title
        paper = next((x.title for x in s.state.sources if x.id == of), None) if of else None
        checks[sc_id] = {"id": c.id, "title": c.requirement, "state": c.research_state, "outcome": c.outcome,
                         "conclusion": c.conclusion, "necessity": c.necessity, "evidence": ev, "spec": c.spec,
                         "matrix": c.matrix, "paper": paper, "waived_by": c.waived_by, "waive_reason": c.waive_reason,
                         "sources": [{"tier": x.get("tier"), "title": x.get("title", "")} for x in c.sources],
                         "issues": []}
        return checks[sc_id]

    research = [check(c.id)["id"] for c in s.checks(task_id)]
    for i in s.issues(task_id):
        if i.source_check_id and check(i.source_check_id):
            checks[i.source_check_id]["issues"].append({"id": i.id, "type": i.type, "note": i.note})

    plan = None
    if plans := s.plans(task_id):
        p = plans[-1]
        steps = []
        for st in p.steps:
            scs = [b for b in st["basis"] if check(b)]
            steps.append({"id": st["id"], "action": st["action"], "checks": scs,
                          "intent": [{"id": b, "text": label(b)} for b in st["basis"] if b not in scs]})
        plan = {"id": p.id, "steps": steps, "unverified": p.unverified}

    actions = []
    for a in s.actions(task_id):
        an = a.analysis or {}
        problems = [x["note"] for x in an.get("intent_conflicts", []) + an.get("source_conflicts", []) if x.get("note")]
        pa, ju = an.get("plan_alignment") or {}, an.get("justification") or {}
        if pa and not pa.get("follows_step", True) and pa.get("note"):
            problems.append(pa["note"])
        if ju.get("present") and not ju.get("relevant") and ju.get("note"):
            problems.append(ju["note"])
        if not problems:
            problems = [r["reason"] for r in a.reasons if r["verdict"] != "ALLOW"]
        else:  # a host-measured rule (W01 rewrite, ⑦ S07 separate runs) explains itself; it goes first when it is what warned
            problems = [r["reason"] for r in a.reasons if (r["rule"].startswith("W") or r["rule"] == "S07") and r["verdict"] != "ALLOW"] + problems
        criteria = [{"id": x["intent_id"], "text": label(x["intent_id"])} for x in an.get("intent_conflicts", [])]
        criteria += [{"id": x["source_check_id"], "text": check(x["source_check_id"])["conclusion"] or ""}
                     for x in an.get("source_conflicts", []) if check(x["source_check_id"])]
        runs = []
        for x in s.executions(a.id):
            rv = s.reviews(x.id)
            runs.append({"id": x.id, "executed": x.executed, "summary": x.summary, "files": x.changed_files,
                         "tests": x.tests, "alignment": rv[-1].action_alignment if rv else None,
                         "step_status": rv[-1].plan_step_status if rv else None})
        actions.append({"id": a.id, "at": a.created_at, "step": a.plan_step, "text": a.description, "why": a.justification,
                        "verdict": a.verdict, "rules": [r["rule"] for r in a.reasons], "problems": problems,
                        "criteria": criteria, "decision": a.host_decision, "decision_reason": a.decision_reason,
                        "runs": runs})

    ai = s.get_applicable_intent(task_id)  # the same current-task intent the judge and Guard get
    intent = {
        "goals": [{"id": t.id, "text": t.text, "prev": None}] + items(ai["goals"]),
        "must": items([c for c in ai["constraints"] if c.strength == "hard"]),
        "prefer": items([c for c in ai["constraints"] if c.strength != "hard"]),
        "success": items(ai["success"]), "decisions": items(ai["decisions"]),
        "questions": items(ai["questions"]) + [{"id": c.id, "text": c.text, "prev": None} for c in ai["pending"]],
        "other": ai["other"],
    }

    done = sum(checks[c]["state"] != "pending" for c in research)
    stage = ("Review" if any(r for a in actions for r in a["runs"]) else "Implement" if actions
             else "Plan" if plan else "Research")
    chat = chat_log(s).get(t.id, [])
    for c in chat:
        if c.get("check"):
            check(c["check"])  # an ask answered from a reused or earlier check still needs its record
    # ③ lines the reader could not classify that the user has not decided yet (their buttons stay until then)
    by_id = {k.id: k for k in eng.state.candidates}
    shown = [u["id"] for c in chat for u in (c.get("unread") or []) if u["id"] in by_id]
    intent["unread"] = [i for i in shown if by_id[i].status == "ignored"]
    decided = {}  # what the user made of each: hard | soft | skip (the row says so after a reload)
    for i in shown:
        k = by_id[i]
        if k.status == "promoted" and (it := eng.get_item(k.item_id or "")) is not None:
            decided[i] = it.strength if it.kind == "constraint" else "rule"
        elif k.status == "rejected":
            decided[i] = "skip"
    intent["decided"] = decided
    # ④ a removed criterion stays in view: when and why, until it is restored (to). An audit says which it did not check.
    gone = []
    for c in eng.get_intent_history():
        b, a = c.before or {}, c.after or {}
        if c.change_type != "status" or (it := eng.get_item(c.item_id)) is None or not s.intent_applies(task_id, it):
            continue
        if (b.get("status"), a.get("status")) == ("active", "removed"):
            gone.append({"id": it.id, "text": a["statement"], "strength": a.get("strength"), "all": s.everywhere(it),
                         "from": c.at, "to": None, "why": c.reason.partition(": ")[2]})
        elif (b.get("status"), a.get("status")) == ("removed", "active"):
            for g in gone:
                if g["id"] == it.id and g["to"] is None:
                    g["to"] = c.at
    intent["removed"] = gone
    return {"task": {"id": t.id, "text": t.text}, "stage": stage, "progress": [done, len(research)],
            "intent": intent, "research": research, "checks": checks, "plan": plan, "actions": actions,
            "chat": chat, "anchors": anchors, "sources": sources}


# ---- ⑫ the reproduction report: what a supervisor or a reviewer reads, with every condition's page in the paper ------
REPORT_KIND = {"fact": "논문의 서술", "scope": "실험 범위"}
VERDICT = {"differs": "✗ 다름", "pairing": "? 열 짝 확인 필요", "chosen": "• 코드가 정함", "intended": "◇ 의도한 차이", "missing": "○ 아직 없음",
           "unclear": "? 판단 못 함", "followed": "✓ 따름"}
CHECKED = {"verified": "Pablo가 파일에서 확인", "moved": "다른 줄에서 확인", "not_found": "⚠ 그 자리에 없음",
           "no_file": "⚠ 파일 없음", "value_mismatch": "⚠ 판정과 논문 값이 어긋남"}


def _day(iso: str | None) -> str:
    return (iso or "")[:10]


def _when(iso: str | None) -> str:
    """review: to the minute, in the reader's local time (several things happen on one day)."""
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return _day(iso)


def _span(spans: list, at: str):
    """The deviation / removal span holding at `at` (ISO strings sort in time order)."""
    return next((d for d in spans or [] if d.get("from", "") < at and (not d.get("to") or d["to"] > at)), None)


def render_report(s, task_id: str, now: dict | None = None) -> str:
    """⑫ Markdown: the task's papers, conditions (with pages), what differs on purpose, what was taken out and why, the
    criteria, the last audit, what Pablo stopped or asked about, and what changed. Pages instead of [n]: a report is
    read apart from the app."""
    from .skill import SPEC_LABEL, deviation, unpaired
    v, t = model(s, task_id), s.get_task(task_id)
    checks = {c.id: c for c in s.checks(task_id)}
    where = {}  # check id -> "LinearRAG p.5"
    for cid in v["research"]:
        for e in v["checks"][cid]["evidence"]:
            a = v["anchors"].get(e)
            if a:
                where.setdefault(cid, f"{v['sources'][a['source']]['title']} p.{a['page']}" if a.get("page") else v["sources"][a["source"]]["title"])
    spec = [checks[c] for c in v["research"] if checks[c].spec]
    live = [c for c in spec if c.research_state != "waived"]
    stated = [c for c in live if not c.spec.get("missing") and c.spec.get("kind") not in REPORT_KIND]
    aside = [c for c in live if c.spec.get("kind") in REPORT_KIND]
    open_ = [c for c in live if c.spec.get("missing")]
    text = lambda c: re.sub(r"\s*\[\d+\]", "", c.conclusion or c.requirement).strip()  # noqa: E731
    audits = [c for c in v["chat"] if c.get("role") == "audit" and c.get("items")]
    last = audits[-1] if audits else None
    out = [f"# 재현 보고서: {t.text}", "", f"Pablo가 {_when(now_iso())}에 만든 보고서입니다. 조건마다 논문의 쪽을 적었습니다. 시각은 이 컴퓨터의 시간대입니다.", ""]
    # papers
    srcs = list(dict.fromkeys(c.spec["source_id"] for c in spec))
    out += ["## 논문", ""]
    named = 0
    for sid in srcs:
        src = next((x for x in s.state.sources if x.id == sid), None)
        if not src:
            continue
        named += 1
        ver = src.version or {}
        bits = [f"**{src.title}**" + (f" {ver['arxiv_version']}" if ver.get("arxiv_version") else ""),
                f"arXiv {ver['arxiv']}" if ver.get("arxiv") else None, f"OpenReview {ver['openreview']}" if ver.get("openreview") else None,
                f"DOI {ver['doi']}로 찾은 arXiv 판 (출판본과 다를 수 있음)" if ver.get("doi") else None,
                f"파일 해시 `{ver.get('content_hash', '')}`"]  # whole: a reader checks the PDF outside the app with it
        code = next((x for x in s.code_links(src) if x["official"]), None)
        if code:
            bits.append(f"공식 코드 {code['url']} (p.{code['page']})")
        out.append("- " + " · ".join(b for b in bits if b))
    if not named:
        out.append("- 재현 조건을 뽑은 논문의 기록이 없습니다." if srcs else "- 재현 조건을 뽑은 논문이 없습니다.")
    # conditions
    out += ["", f"## 재현 조건 ({len(stated)}개)", ""]
    for cat, label in SPEC_LABEL.items():
        xs = [c for c in stated if c.spec["category"] == cat]
        if not xs:
            continue
        out += [f"### {label}", ""]
        for c in xs:
            notes = [n for n in ["사용자가 직접 더함" if c.spec.get("by") == "user" else None,
                                 "되살림" if c.spec.get("kept") else None,
                                 f"값({c.spec.get('value')})이 인용 안에 없음" if c.spec.get("value_in_quote") is False else None,
                                 "표의 열 짝 미확인" if c.spec.get("header_missing") else None] if n]
            out.append(f"- {text(c)} — {where.get(c.id, '쪽 없음')}" + (f" ({'; '.join(notes)})" if notes else ""))
        out.append("")
    if open_:
        out += ["### 논문에 없는 설정", ""]
        for c in open_:
            chosen = next((x for x in (last or {}).get("items", []) if x.get("id") == c.id and x.get("status") == "chosen"), None)
            out.append(f"- {c.requirement.strip()}" + (f" — 코드가 정함: `{chosen.get('found', '')}` ({chosen.get('where', '')})" if chosen else " — 아직 정하지 않음"))
        out.append("")
    # what differs on purpose (fixed section)
    out += ["## 논문과 다르게 한 것 (의도한 차이)", ""]
    devs = [(c, d) for c in spec for d in c.spec.get("deviations", [])]
    out += [f"- {text(c)} — 이유: {d['why']} · 범위: {'별도 실행에서만' if (d.get('scope') or 'task') == 'runs' else '작업 전체'}"
            f" · {_when(d['from'])}부터" + (f" {_when(d['to'])}까지 (되돌림)" if d.get("to") else " (지금도)") for c, d in devs] or ["- 없음"]
    # what was taken out (fixed section)
    out += ["", "## 뺀 조건과 지운 기준", ""]
    outs = [(c, d) for c in spec for d in c.spec.get("dropped", [])]
    gone = [g for g in v["intent"].get("removed", [])]
    out += [f"- 뺀 조건: {text(c)} — 이유: {d['why']} · {_when(d['from'])}" + (f" (되살림 {_when(d['to'])})" if d.get("to") else "") for c, d in outs]
    out += [f"- 지운 기준: {g['text']} — " + (f"이유: {g['why']}" if g.get("why") else "이유를 적지 않음") + f" · {_when(g['from'])}"
            + (f" (되살림 {_when(g['to'])})" if g.get("to") else "") for g in gone]
    if not outs and not gone:
        out.append("- 없음")
    # criteria
    out += ["", "## 작업 기준", ""]
    out += [f"- 반드시: {x['text']}" for x in v["intent"]["must"]] + [f"- 가능하면: {x['text']}" for x in v["intent"]["prefer"]]
    if not v["intent"]["must"] and not v["intent"]["prefer"]:
        out.append("- 없음")
    # P5: messages a person pinned as a decision (✎ 태그 → 결정으로 고정); the app sends their keys (role@time)
    decided = []
    for d in (now or {}).get("decisions") or []:
        key = str((d or {}).get("key", ""))
        role, _, at = key.partition("@")
        if key == "start":
            said, who, when = t.text, "나", None
        elif key.startswith("act:"):
            a = next((x for x in v["actions"] if x["id"] == key[4:]), None)
            said, who, when = (a or {}).get("text"), "Pablo", (a or {}).get("at")
        else:
            c = next((x for x in v["chat"] if x.get("role") == role and x.get("at") == at), None) or {}
            said, who, when = c.get("text") or c.get("summary"), "나" if role == "user" else "Pablo", c.get("at")
        if said:
            stage = f"[{d['stage']}] " if d.get("stage") else ""
            decided.append(f"- {stage}{who}: {' '.join(str(said).split())[:400]}" + (f" · {_when(when)}" if when else ""))
    if decided:
        out += ["", "## 대화에서 정한 결정", ""] + decided
    # the last audit
    out += ["", "## 재현 점검", ""]
    if not last:
        out.append("아직 재현 점검을 하지 않았습니다.")
    else:
        changed = [x for x in v["chat"] if x.get("role") in ("changes", "undo") and x.get("at", "") > last["at"]]
        rc = (now or {}).get("recheck") if ((now or {}).get("recheck") or {}).get("at") == last["at"] else None
        line = f"마지막 점검: {_when(last['at'])}."
        if rc and rc.get("gone"):  # the app's card says the same (its confirmed places checked again)
            line += f" 점검 때 Pablo가 확인한 {rc['placed']}곳 중 {len(rc['gone'])}곳이 지금은 그대로가 아닙니다({', '.join(rc['gone'][:3])}). 판정이 지금 파일과 다를 수 있습니다."
        elif rc and changed:
            line += f" 그 뒤 파일이 바뀐 기록이 {len(changed)}번 있지만, 점검 때 Pablo가 확인한 {rc['placed']}곳은 지금도 그대로입니다."
        elif changed:
            line += f" 그 뒤 파일이 바뀐 기록이 {len(changed)}번 있어, 지금 파일과 다를 수 있습니다."
        out.append(line)
        # which code the verdicts are about (review): the folder's snapshot at the audit, and now
        code = []
        if last.get("tree"):
            code.append(f"점검한 작업 폴더: 스냅숏 `{last['tree'][:12]}`" + (f", git HEAD `{last['git']['head'][:12]}`" + (f" (커밋 안 한 변경 {last['git']['dirty']}개)" if last['git'].get('dirty') else "") if last.get("git") else ""))
        if (now or {}).get("tree") and last.get("tree"):
            code.append("보고서를 만든 지금도 같은 폴더 상태입니다." if now["tree"] == last["tree"] else f"지금 폴더는 그 뒤 바뀌었습니다(스냅숏 `{now['tree'][:12]}`).")
        elif not last.get("tree"):
            code.append("이 점검은 작업 폴더의 판을 기록하기 전(0.8 이전)에 했습니다.")
        if last.get("shell") == "powershell":  # ⑤ no pwsh 7: the agent may have read 한글 and symbols wrongly
            code.append("이 점검은 Windows PowerShell 5.1에서 했습니다(PowerShell 7 없음). 에이전트가 한글 주석이나 기호를 깨진 채 "
                        "읽었다면 그 줄의 판정이 틀릴 수 있습니다.")
        out += [" ".join(code)] if code else []
        if last.get("summary"):
            out += ["", last["summary"]]
        out += ["", "| 항목 | 판정 | 자리 | Pablo 확인 |", "|---|---|---|---|"]
        paired = 0
        later = lambda spans, what: [f"이 점검 뒤 {what}, {_when(z['from'])}" for z in spans or [] if z.get("from", "") > last["at"]]  # noqa: E731
        for x in last["items"]:
            c = checks.get(x.get("id"))
            d = _span(c.spec.get("deviations"), last["at"]) if c and c.spec else None
            after = (later(c.spec.get("deviations"), "의도한 차이로 둠") + later(c.spec.get("dropped"), "뺌")) if c and c.spec else \
                later([g for g in gone if g["id"] == x.get("id")], "지움")  # review: a row changed since says so (the order of events)
            st = "intended" if x.get("status") == "differs" and d and (d.get("scope") or "task") == "task" else x.get("status")
            row = None
            if st != "intended" and c and unpaired(c.spec, x.get("status")):  # e2e3: not a verdict until the columns are checked
                st, paired = "pairing", paired + 1
                row = next((v["anchors"][e]["exact"] for e in v["checks"][c.id]["evidence"] if e in v["anchors"]), "")
            what = text(c) if c else next((i["text"] for i in v["intent"]["must"] + v["intent"]["prefer"] if i["id"] == x.get("id")), x.get("id", ""))
            mark = "값은 설정 파일에서 확인" if x.get("check") == "value_mismatch" and (x.get("via") or {}).get("agrees") else CHECKED.get(x.get("check"), "")
            place = f"`{x['where']}` {x.get('found', '')}".strip() if x.get("where") else ""
            if x.get("seen"):
                place += f" (모델은 없다고 했지만 `{x['seen']['where']}`에 있음)"
            cell = lambda s_: str(s_).replace("|", "\\|").replace("\n", " ")  # noqa: E731
            out.append(f"| {cell(what)}{' — ' + cell(where[c.id]) if c and c.id in where else ''}{' (' + '; '.join(after) + ')' if after else ''}"
                       f" | {VERDICT.get(st, st)}{' (이유: ' + cell(d['why']) + ')' if st == 'intended' else ''}"
                       + (f" (판단 못 함. 에이전트 판정: {VERDICT.get(x.get('status'))}" + (f"; 논문 표 행: “{cell(row)}”" if row else "") + ")" if st == "pairing" else "")
                       + f" | {cell(place)} | {cell(mark)} |")
        if paired:
            out += ["", "열 짝 확인 필요: 논문 표의 한 행에서 열 이름 없이 읽은 값이라, 어느 숫자가 이 조건의 데이터셋·지표인지 확인되지 "
                    "않았습니다. 에이전트의 판정은 그 짝을 믿은 것이어서 판정으로 세지 않았습니다. 논문 표에서 열을 확인하고 '자리'의 값과 대조하세요."]
        if last.get("outside"):
            out += ["", "조건 밖에서 본 차이:", ""] + [f"- {x['what']}" + (f" (`{x['where']}`)" if x.get("where") else "") for x in last["outside"]]
        skipped = [g for g in gone if _span([g], last["at"])] + [c for c in spec if _span(c.spec.get("dropped"), last["at"])]
        if skipped:
            out += ["", f"이 점검 전에 지우거나 뺀 것 {len(skipped)}개는 대조하지 않았습니다."]
    # what Pablo stopped or asked about
    acts = [a for a in v["actions"] if a["verdict"] in ("BLOCK", "WARN")]
    out += ["", "## Pablo가 막거나 확인을 받은 작업", ""]
    if not acts:
        out.append("- 없음")
    for a in acts:
        decided = {"proceed": "사용자가 진행", "reject": "취소", "defer": "보류"}.get(a.get("decision") or "", "결정 전")
        why = (a["problems"] or [""])[0]
        out.append(f"- {'막음' if a['verdict'] == 'BLOCK' else '확인'}: {a['text'].splitlines()[0][:120]}"
                   + (f" — {why}" if why else "") + ("" if a["verdict"] == "BLOCK" else f" · {decided}"))
    # what changed
    ch = [x for x in v["chat"] if x.get("role") == "changes"]
    undone = {x.get("of") for x in v["chat"] if x.get("role") == "undo"}
    out += ["", "## 바뀐 파일", ""]
    out += [f"- {_when(x['at'])} 파일 {len(x.get('files', []))}개: " + ", ".join(f"{f['path']}" for f in x.get("files", [])[:12])
            + (" (되돌림)" if x.get("to") in undone else "") for x in ch] or ["- 에이전트가 바꾼 파일이 없습니다."]
    if aside:
        out += ["", "## 참고 (따를 조건이 아닌 논문의 서술과 실험 범위)", ""]
        out += [f"- [{REPORT_KIND[c.spec['kind']]}] {text(c)} — {where.get(c.id, '쪽 없음')}" for c in aside]
    return "\n".join(out).rstrip() + "\n"


def now_iso() -> str:
    from pablo_v2.intent.models import now
    return now()


def chat_log(s) -> dict:
    """The desktop's conversation per task (<state dir>/chat.json, written by desktop/main.js only): what the user said,
    the agent's replies and which check answered a PDF question. Pablo's own records stay in skill.json."""
    if not s.path:
        return {}
    try:
        with open(os.path.join(os.path.dirname(s.path), "chat.json"), encoding="utf-8") as f:
            log = json.load(f)
    except (OSError, ValueError):
        return {}
    return log if isinstance(log, dict) else {}


def workspace(s, current: str | None = None) -> dict:
    """Every task of the state dir (the desktop's live state; render_html embeds the same model)."""
    views = {t.id: model(s, t.id) for t in s.state.tasks}
    anchors, sources = {}, {}
    for v in views.values():
        anchors.update(v.pop("anchors"))
        sources.update(v.pop("sources"))
    # ⑩ every captured PDF, so one opens without a citation (to pick a sentence as a condition): what the PDF panel needs
    papers = {x.id: {k: sources[x.id][k] for k in ("title", "url", "captured_at", "hash", "kind", "file", "pages", "intact")}
              if x.id in sources else paper_entry(s, x) for x in s.state.sources if x.kind == "pdf"}
    for x in s.state.sources:  # ⑪ the code each paper links, its own first
        if x.kind == "pdf":
            papers[x.id]["code"] = s.code_links(x)
    return {"current": current or (s.state.tasks[-1].id if s.state.tasks else None),
            "tasks": [{"id": t.id, "text": t.text, "at": t.created_at, "name": t.name} for t in s.state.tasks],
            "views": views, "anchors": anchors, "sources": sources, "papers": papers,
            "pdf": any(x.kind == "pdf" for x in s.state.sources)}  # M3.3: the static page's composer asks the PDF


def paper_entry(s, src) -> dict:
    try:
        pages, intact = s.snapshot_text(src).count("\f") + 1, pdf.content_hash(s.snapshot_pdf(src)) == src.version["content_hash"]
    except (OSError, KeyError):  # the copy is gone: the panel says it cannot open it
        pages, intact = 0, False
    return {"title": src.title, "url": src.locator, "captured_at": src.captured_at, "hash": src.version["content_hash"],
            "kind": "pdf", "file": f"{src.id}.pdf", "pages": pages, "intact": intact}


def render_html(s, task_id: str | None = None) -> str:
    """All tasks in one file (the sidebar switches between them); task_id is the one shown first."""
    m = workspace(s, task_id)
    data = json.dumps(m, ensure_ascii=False).replace("</", "<\\/")
    title = f"Pablo · {m['views'][m['current']]['task']['text']}" if m["current"] else "Pablo"
    return PAGE.replace("{{ART}}", json.dumps(ART)).replace("{{TITLE}}", escape(title)).replace("{{DATA}}", data)


PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title>
<style>
/* UI renewal, concept A (정밀 계측), light only: the tokens of the Figma collection "Pablo · 시안 토큰" (mode A).
   One signal colour (orange) for what needs a person's judgement; everything else is ink on cool grey. */
:root { color-scheme:light;
        --canvas:#E3E7EB; --surface:#F3F5F7; --raised:#D3D9DF; --ink:#0D0E10; --ink-2:#4A515C; --ink-3:#8A929D;
        --line-soft:rgba(13,14,16,.16); --primary:#0D0E10; --on-primary:#fff; --signal:#FF4D00; --signal-soft:#FFE1D2;
        --sans:"Geist", "Pretendard", system-ui, "Segoe UI", "Malgun Gothic", sans-serif;
        --mono:"Geist Mono", "Pretendard", ui-monospace, Consolas, monospace;  /* Geist Mono has no Hangul */
        --bg:var(--surface); --side:var(--canvas); --fg:var(--ink); --muted:var(--ink-2); --faint:var(--ink-3); --line:#1C1F23;
        --hover:var(--raised); --accent:var(--ink); --ok:var(--ink-2); --warn:var(--signal); --warnbg:var(--signal-soft);
        --warnline:var(--signal); --bad:var(--ink); --badbg:var(--raised); --badline:var(--ink); --hl:var(--signal-soft);
        --code:var(--raised); --shade:rgba(13,14,16,.45); --lineon:var(--signal-soft); }
* { box-sizing:border-box; }
html, body { height:100%; margin:0; }
body { background:var(--bg); color:var(--fg); font:15px/1.65 system-ui, "Segoe UI", "Malgun Gothic", sans-serif;
       display:grid; grid-template-columns:220px minmax(0, 1fr); }
body.panel { grid-template-columns:220px minmax(0, 1fr) 480px; }
button, input { font:inherit; color:inherit; }
button { cursor:pointer; background:none; border:0; padding:0; }
button:disabled { cursor:default; opacity:.4; }
code { font:0.88em ui-monospace, SFMono-Regular, Consolas, monospace; background:var(--code); border-radius:4px;
       padding:1px 5px; }
/* sidebar */
#side { background:var(--side); border-right:1px solid var(--line); padding:14px 10px; overflow:auto; }
#side .brand { display:flex; justify-content:space-between; align-items:center; padding:0 6px 14px; }
#side .brand b { font-size:18px; display:flex; align-items:center; gap:6px; }
#side .new { font-size:13px; color:var(--muted); border:1px solid var(--line); border-radius:8px; padding:3px 9px; }
#side h4 { font-size:12px; color:var(--muted); font-weight:600; margin:6px 6px 4px; }
#side .t { display:block; width:100%; text-align:left; padding:7px 8px; border-radius:8px; font-size:14px;
           line-height:1.4; }
#side .t:hover { background:var(--hover); } #side .t.on { background:var(--hover); font-weight:600; }
#side .t small { display:block; color:var(--faint); font-size:11px; font-weight:400; }
#task-search { width:100%; box-sizing:border-box; margin:0 0 6px; border:1px solid var(--line); border-radius:8px; padding:5px 9px;
  background:var(--bg); color:var(--fg); font:inherit; font-size:13px; }
#side details.away summary, #side details.done summary { font-size:12px; color:var(--muted); cursor:pointer; margin:10px 6px 4px; }
#bar .quiet { font-size:12px; color:var(--faint); } #bar h1 .rn-in { font-size:15px; width:min(320px, 50vw); }
#bar h1:hover + .rn, #bar .rn:focus-visible { opacity:1; }
/* conversation */
#chat { display:flex; flex-direction:column; min-width:0; height:100vh; }
#bar { display:flex; align-items:center; gap:8px; padding:10px 20px; border-bottom:1px solid var(--line); }
#bar h1 { flex:1; min-width:0; font-size:16px; margin:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.pill { border:1px solid var(--line); border-radius:999px; padding:4px 12px; font-size:13px; }
.pill:hover:not(:disabled) { background:var(--hover); } .pill.on { background:var(--fg); color:var(--bg); border-color:var(--fg); }
#menu { display:none; font-size:18px; padding:0 6px; }
#log { flex:1; overflow:auto; padding:24px 20px 40px; }
.msg { max-width:720px; margin:0 auto 28px; display:grid; grid-template-columns:32px minmax(0, 1fr); gap:12px; }
.av { width:30px; height:30px; border-radius:50%; display:grid; place-items:center; font-size:13px; font-weight:700;
      background:var(--hover); color:var(--muted); }
.msg.pablo .av { background:var(--accent); color:#fff; }
.who { font-weight:700; } .who small { font-weight:400; color:var(--faint); font-size:12px; margin-left:8px; }
.msg p { margin:4px 0 10px; }
.call { border-left:3px solid var(--warnline); background:var(--warnbg); border-radius:0 8px 8px 0; padding:10px 14px;
        margin:12px 0; }
.call.block { border-left-color:var(--bad); background:var(--badbg); }
.call .head { font-weight:700; color:var(--warn); margin:0 0 4px; } .call.block .head { color:var(--bad); }
.call p { margin:4px 0; } .muted { color:var(--muted); font-size:13px; }
.cite { color:var(--accent); font-size:13px; font-weight:600; margin-left:2px; vertical-align:1px; }
.cite:hover, .cite.on { text-decoration:underline; }
.link { color:var(--accent); font-size:13px; } .link:hover { text-decoration:underline; }
.composer { max-width:760px; width:calc(100% - 40px); margin:0 auto 18px; display:flex; gap:8px; align-items:center;
            border:1px solid var(--line); border-radius:14px; padding:8px 8px 8px 16px; }
.composer input { flex:1; border:0; background:none; outline:none; min-width:0; }
.composer button { width:30px; height:30px; border-radius:50%; background:var(--fg); color:var(--bg); }
/* context panel */
#panel { display:none; border-left:1px solid var(--line); height:100vh; flex-direction:column; min-width:0;
         background:var(--bg); }
body.panel #panel { display:flex; }
.phead { display:flex; align-items:center; gap:10px; padding:12px 16px; border-bottom:1px solid var(--line); }
.phead h2 { flex:1; font-size:15px; margin:0; }
.x { font-size:20px; line-height:1; color:var(--muted); padding:2px 4px; }
.nav { font-size:17px; color:var(--muted); padding:0 3px; }
.url { flex:1; min-width:0; background:var(--side); border-radius:999px; padding:4px 12px; font-size:13px;
       color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ext { color:var(--accent); text-decoration:none; font-size:16px; }
#pbody { flex:1; overflow:auto; padding:16px 20px 28px; }
#pbody.live { padding:0; overflow:hidden; display:flex; } #pbody.live webview { flex:1; background:#fff; }  /* a page without its own background stays readable in dark mode */
.info { font-size:12px; color:var(--muted); padding:6px 16px; border-bottom:1px solid var(--line); background:var(--side); }
.info.STALE, .info.UNRESOLVED, .info.broken { background:var(--warnbg); color:var(--warn); }
.info a { color:var(--accent); }
.pfoot { padding:10px 14px; border-top:1px solid var(--line); }
.pfoot .composer { width:100%; margin:0; }
#acct { max-width:760px; width:calc(100% - 40px); margin:0 auto 8px; font-size:13px; }
#model { font:inherit; font-size:12px; max-width:150px; }
#acct p { margin:2px 0; } #acct .call { margin:0; }
#pbody h3 { font-size:13px; color:var(--muted); margin:18px 0 6px; font-weight:600; }
#pbody h3:first-child { margin-top:0; }
ul.ck { list-style:none; margin:0; padding:0; } ul.ck li { padding:3px 0 3px 26px; position:relative; }
ul.ck .edits { font-size:12px; white-space:nowrap; } ul.ck .all { color:var(--warn); font-size:11px; } ul.ck .edits .link { font-size:12px; }
ul.ck .edits .why { border:1px solid var(--line); border-radius:6px; padding:1px 6px; background:none; width:170px; font-size:12px; }
ul.ck .edits .why.need { border-color:var(--bad); } #panel details.gone { margin-top:14px; } #panel details.gone summary { cursor:pointer; font-size:13px; color:var(--muted); }
#panel details.gone s { color:var(--muted); } #panel details.gone .muted { font-size:12px; }
#panel h4.kind { font-size:12px; color:var(--muted); font-weight:600; margin:8px 0 0; }
ul.ck li::before { position:absolute; left:2px; content:"•"; color:var(--faint); }
ul.ck.must li::before { content:"✓"; color:var(--ok); font-weight:700; } ul.ck.q li::before { content:"○"; }
.ck .note { display:block; color:var(--muted); font-size:13px; }
.prev { display:block; color:var(--faint); font-size:12px; text-decoration:line-through; }
ol.steps { list-style:none; margin:0; padding:0; } ol.steps li { display:grid; grid-template-columns:22px 1fr; gap:2px 8px;
           padding:9px 0; border-bottom:1px solid var(--line); }
ol.steps .i { font-weight:700; } ol.steps .done .i { color:var(--ok); } ol.steps .doing .i { color:var(--accent); }
ol.steps .todo .i { color:var(--faint); } ol.steps .sub { grid-column:2; font-size:12px; color:var(--muted); }
/* trace */
.tl { position:relative; margin:0; padding:0; list-style:none; }
.tl li { position:relative; padding:0 0 18px 26px; }
.tl li::before { content:""; position:absolute; left:6px; top:8px; bottom:-8px; border-left:2px solid var(--line); }
.tl li:last-child::before { display:none; }
.tl li::after { content:""; position:absolute; left:1px; top:6px; width:12px; height:12px; border-radius:50%;
                background:var(--bg); border:2px solid var(--faint); }
.tl li.ev::after { border-color:var(--ok); } .tl li.warn::after { border-color:var(--warn); }
.tl li.stop::after { border-color:var(--bad); background:var(--bad); }
.tl .k { font-weight:700; font-size:14px; } .tl .v { color:var(--muted); font-size:14px; }
.tl li.ev .v { cursor:pointer; } .tl li.ev .v:hover { color:var(--fg); }
/* snapshot page */
#doc { overflow-wrap:anywhere; font-size:14px; line-height:1.6; }
#doc .title { font-size:22px; font-weight:700; margin:4px 0 18px; line-height:1.3; }
#doc .b { margin:0 0 9px; } #doc .hide { display:none; } #doc .hide.shown { display:block; }
#doc .h1, #doc .h2 { font-size:19px; font-weight:700; margin-top:22px; }
#doc .h3 { font-size:16px; font-weight:700; margin-top:16px; } #doc .h4, #doc .h5, #doc .h6 { font-weight:700; }
#doc .li { padding-left:18px; position:relative; } #doc .li::before { content:"•"; position:absolute; left:4px; }
#doc .pre { font:12.5px/1.5 ui-monospace, Consolas, monospace; background:var(--code); border-radius:6px; padding:8px 10px; }
#doc .quote { border-left:3px solid var(--line); padding-left:10px; color:var(--muted); }
/* M3.3 PDF panel (desktop): the captured PDF page (pdf.js canvas) + evidence boxes */
body.panel.pdf { grid-template-columns:220px minmax(0, 1fr) min(760px, 48vw); }
#pbody.pdf { background:var(--side); padding:12px; scrollbar-gutter:stable; overflow-x:hidden; }
.pg { position:relative; margin:0 auto; background:#fff; box-shadow:0 1px 4px rgba(0,0,0,.25); }
.pg canvas { display:block; }
.pg .hl { position:absolute; background:rgba(250,204,21,.45); mix-blend-mode:multiply; border-radius:2px; pointer-events:none; }
/* ⑩ the page's text over the canvas, transparent and selectable (pdf.js TextLayer; rules from its pdf_viewer.css) */
.pg .textLayer { position:absolute; text-align:initial; inset:0; overflow:clip; opacity:1; line-height:1; text-size-adjust:none;
  forced-color-adjust:none; transform-origin:0 0; caret-color:CanvasText; z-index:0;
  --min-font-size:1; --text-scale-factor:calc(var(--total-scale-factor) * var(--min-font-size)); --min-font-size-inv:calc(1 / var(--min-font-size)); }
.pg .textLayer :is(span,br) { color:transparent; position:absolute; white-space:pre; cursor:text; transform-origin:0% 0%; }
.pg .textLayer > :not(.markedContent), .pg .textLayer .markedContent span:not(.markedContent) { z-index:1; --font-height:0;
  font-size:calc(var(--text-scale-factor) * var(--font-height)); --scale-x:1; --rotate:0deg;
  transform:rotate(var(--rotate)) scaleX(var(--scale-x)) scale(var(--min-font-size-inv)); }
.pg .textLayer .markedContent { display:contents; }
.pg .textLayer ::selection { background:rgba(37,99,235,.28); } .pg .textLayer br::selection { background:transparent; }
.pg .textLayer .endOfContent { display:block; position:absolute; inset:100% 0 0; z-index:0; cursor:default; user-select:none; }
.pg .textLayer.selecting .endOfContent { top:0; }
#pick { border-top:1px solid var(--line); padding:8px 14px; background:var(--bg); font-size:13px; display:flex; flex-direction:column; gap:6px; }
#pick[hidden] { display:none; } #pick .q { color:var(--muted); overflow-wrap:anywhere; max-height:5.6em; overflow:auto; }
#pick .row { display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
#pick input, #pick select { border:1px solid var(--line); border-radius:6px; padding:3px 6px; background:var(--bg); color:var(--fg); font:inherit; }
#pick [data-statement] { flex:1 1 220px; min-width:0; } #pick [data-value] { width:120px; }
.pnum { font-size:13px; color:var(--muted); white-space:nowrap; }
/* M5.1 app: new task form, task tools, technical details */
#goal { width:100%; border:1px solid var(--line); border-radius:10px; padding:10px 12px; background:none; color:inherit;
        font:inherit; resize:vertical; }
#tools { max-width:760px; width:calc(100% - 40px); margin:0 auto 6px; font-size:13px; color:var(--muted);
         display:flex; gap:12px; flex-wrap:wrap; align-items:center; }
#tools:empty { display:none; }
details.tech { margin:6px 0; font-size:12px; color:var(--muted); } details.tech summary { cursor:pointer; }
details.tech pre { white-space:pre-wrap; overflow-wrap:anywhere; background:var(--code); border-radius:6px; padding:6px 8px;
                   margin:4px 0; font:12px/1.5 ui-monospace, Consolas, monospace; }
/* the change a WARN / BLOCK card is about: the diff, or the command without its shell wrapper */
pre.diff, pre.cmd { font:12px/1.5 ui-monospace, Consolas, monospace; background:var(--code); border-radius:6px; padding:6px 0;
                    margin:6px 0; max-height:260px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; }
pre.cmd { padding:6px 10px; }
pre.diff span { display:block; padding:0 10px; min-height:1.5em; } pre.diff .add { background:rgba(22,163,74,.14); }
pre.diff .del { background:rgba(220,38,38,.13); } pre.diff .hunk { color:var(--muted); } pre.diff .file { font-weight:700; }
.composer[data-running="1"] button { background:var(--bad); }
.spec { border-left:3px solid var(--accent); background:var(--side); border-radius:0 8px 8px 0; padding:8px 14px; margin:8px 0; }
.spec .head { font-weight:700; margin:0 0 4px; } .spec h4 { font-size:12px; color:var(--muted); margin:10px 0 2px; }
.spec ul { margin:0; padding-left:18px; } .spec li { margin:2px 0; } .spec ul.open li { color:var(--warn); }
.audit { border-left:3px solid var(--accent); background:var(--side); border-radius:0 8px 8px 0; padding:8px 14px; margin:8px 0; }
.audit .head { font-weight:700; margin:0 0 4px; } .audit ul { list-style:none; margin:4px 0; padding:0; }
.audit li { padding:5px 0; border-top:1px solid var(--line); font-size:14px; } .audit .at { font-size:13px; overflow-wrap:anywhere; }
.audit .st-intended b, .chk.dev { color:var(--accent); } .call .offer { margin-top:6px; } .call .offer ul { margin:2px 0; }
.audit .st-differs b { color:var(--bad); } .audit .st-followed b { color:var(--ok); } .audit .st-missing b, .audit .st-unclear b, .audit .st-pairing b { color:var(--warn); }
.audit .pair { font-size:13px; margin:2px 0; overflow-wrap:anywhere; }
.audit details summary { cursor:pointer; font-size:13px; color:var(--muted); margin-top:6px; }
.audit .stale { background:var(--warnbg); border:1px solid var(--warnline); border-radius:6px; padding:5px 10px; font-size:13px; margin:4px 0 6px; }
.audit .stale.same { background:none; border-color:var(--line); }
.audit .ps51 { background:var(--warnbg); border:1px solid var(--warnline); border-radius:6px; padding:5px 10px; font-size:13px; margin:4px 0 6px; }
#shell-note { max-width:760px; width:calc(100% - 40px); margin:0 auto; font-size:13px; } #shell-note:empty { display:none; }
#shell-note p { margin:2px 0; } #shell-note .call { margin:0 0 8px; } #shell-note code { font-size:12px; }
.audit .via { color:var(--muted); }
.audit .outside h4 { font-size:12px; color:var(--muted); margin:10px 0 0; } .audit .st-outside b { color:var(--warn); }
.chk { font-size:12px; color:var(--ok); margin-left:6px; white-space:nowrap; } .chk.moved { color:var(--muted); }
.chk.warn { color:var(--warn); font-weight:600; }
/* A3: a work-folder path that opens the code panel (audit where, change and WARN / BLOCK cards) */
button.file { color:var(--accent); } button.file:hover code, button.file:hover { text-decoration:underline; }
body.panel.code { grid-template-columns:220px minmax(0, 1fr) min(760px, 48vw); }
#pbody.code { padding:0; font:12.5px/1.55 ui-monospace, SFMono-Regular, Consolas, monospace; }
.src { min-width:max-content; padding:8px 0 24px; }
.src .ln { display:grid; grid-template-columns:7ch auto; white-space:pre; }
.src .n { color:var(--faint); text-align:right; padding-right:14px; user-select:none; }
.src .t { padding-right:16px; } .src .ln.on { background:var(--lineon); } .src .ln.on .n { color:var(--fg); font-weight:700; }
.phead .open { font-size:12px; white-space:nowrap; }
.changes { border-left:3px solid var(--line); background:var(--side); border-radius:0 8px 8px 0; padding:8px 14px; margin:8px 0; }
/* C3 comparison table; C1 the task's papers */
.matrix { border-left:3px solid var(--accent); background:var(--side); border-radius:0 8px 8px 0; padding:8px 14px; margin:8px 0; }
.matrix .head { font-weight:700; margin:0 0 4px; } .matrix .scroll { overflow-x:auto; margin:6px 0; }
.matrix table { border-collapse:collapse; font-size:13px; line-height:1.45; min-width:100%; }
.matrix th, .matrix td { border:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; min-width:110px; }
.matrix thead th { background:var(--bg); font-weight:600; } .matrix tbody th { min-width:90px; }
.matrix th small { color:var(--muted); font-weight:400; } .matrix td.none { color:var(--faint); cursor:help; }
.matrix .metric { display:block; font-size:11px; color:var(--muted); } .matrix .metric.differ, .matrix th .differ { color:var(--warn); } .matrix th .differ { white-space:nowrap; }
.matrix .common { font-size:13px; } .rn { background:none; border:0; color:var(--faint); cursor:pointer; padding:0 2px; font-size:12px; opacity:0; }
.paper:hover .rn, th:hover .rn, .rn:focus-visible { opacity:1; }
.rn-in { border:1px solid var(--line); border-radius:6px; padding:1px 6px; background:var(--bg); color:var(--fg); font:inherit; width:160px; }
.matrix.wide { border:0; background:none; padding:0; margin:0; } .matrix.wide table { font-size:14px; }
body.panel.wide { grid-template-columns:220px minmax(0, 1fr) min(900px, 58vw); }
#src .paper { white-space:nowrap; } #src .rm { color:var(--faint); padding:0 3px; } #src .rm:hover { color:var(--bad); }
#adder { max-width:760px; width:calc(100% - 40px); margin:0 auto 6px; font-size:13px; color:var(--muted); display:flex; gap:8px;
         flex-wrap:wrap; align-items:center; }
#adder[hidden], #arxiv-lines[hidden], #arxiv-hits[hidden], #src .plist[hidden] { display:none; }
#arxiv-lines, #arxiv-hits { flex-basis:100%; } #arxiv-lines { margin:0; padding-left:18px; } #arxiv-lines .bad { color:var(--warn); }
#arxiv-hits .hit { padding:3px 0; } #arxiv-hits .have { color:var(--ok); }
#arxiv-hits .sum { margin-left:22px; font-size:12px; color:var(--faint); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
#src.many { flex-basis:100%; } #src.many .plist { display:flex; flex-direction:column; gap:2px; margin:4px 0 2px 18px; }
body.dropping #log { outline:3px dashed var(--accent); outline-offset:-8px; }
body.dropping #log::before { content:"PDF를 놓으면 이 작업의 자료로 추가합니다"; display:block; text-align:center; padding:10px;
  color:var(--accent); font-weight:700; } #adder #arxiv { min-width:240px; border:1px solid var(--line); border-radius:8px; padding:3px 8px;
         background:none; } .ask-pick { display:flex; gap:8px; flex-wrap:wrap; margin-top:6px; }
.cols { width:100%; border:1px solid var(--line); border-radius:8px; padding:6px 10px; background:none; margin:6px 0; }
.changes p { margin:2px 0; font-size:14px; overflow-wrap:anywhere; }
.empty { max-width:560px; margin:18vh auto 0; text-align:center; color:var(--muted); }
.empty b { display:block; font-size:22px; color:var(--fg); margin-bottom:6px; }
/* mascot: only where a state means something (never on WARN / BLOCK / errors); black-and-white, as drawn */
.mascot { display:block; user-select:none; pointer-events:none; }
.mascot.ico { display:inline-block; width:22px; height:22px; } #acct .mascot.ico { width:16px; height:16px; vertical-align:-3px; margin-right:4px; }
.empty .mascot { height:170px; margin:0 auto 12px; }
.mascot.pose { height:96px; margin:2px 0 6px; } .call .mascot.pose { float:right; height:72px; margin:0 0 4px 10px; }
#agent .mascot { display:inline-block; height:22px; vertical-align:middle; margin-right:4px; animation:bob 1.6s ease-in-out infinite; }
@keyframes bob { 50% { transform:translateY(-2px); } }
@media (prefers-reduced-motion: reduce) { #agent .mascot { animation:none; } }
::highlight(evidence) { background-color:var(--hl); color:var(--fg); }
/* concept A: hard structural lines, soft inner dividers, 2px corners, Geist / Geist Mono for Latin (Pretendard for Hangul) */
body { font-family:var(--sans); }
code, pre.diff, pre.cmd, details.tech pre, #doc .pre, #pbody.code, .who small, .pnum, #side .t small, .cite { font-family:var(--mono); }
#side .new, #side .t, #task-search, .pill, .composer, .composer button, .call, .spec, .audit, .changes, .matrix, .audit .stale,
.audit .ps51, #goal, .cols, #adder #arxiv, .rn-in, code, pre.diff, pre.cmd, details.tech pre, #doc .pre, .url, ul.ck .edits .why,
#pick input, #pick select, .pg .hl { border-radius:2px; }
.audit li, ol.steps li, .matrix th, .matrix td, .cols, ul.ck .edits .why, .rn-in, #pick input, #pick select { border-color:var(--line-soft); }
.tl li::before { border-left-color:var(--raised); }
.link, .cite, button.file, .ext, .info a { color:var(--ink); text-decoration:underline; text-underline-offset:2px;
  text-decoration-color:var(--ink-3); }
.link:hover, .cite:hover, .cite.on, button.file:hover { text-decoration-color:var(--ink); }
.pill.on, .msg.pablo .av { background:var(--primary); color:var(--on-primary); border-color:var(--primary); }
#side .t.on { background:var(--surface); box-shadow:inset 2px 0 var(--ink); }
.call { border:1px dashed var(--signal); border-left:3px solid var(--signal); background:var(--surface); border-radius:2px; }
.call .head { color:var(--signal); }
.call.block { border:1px solid var(--ink); border-left:3px solid var(--ink); background:var(--raised); }
.call.block .head { color:var(--ink); }
.call.lock .head::before { content:"막음"; background:var(--signal); color:#fff; font:600 11px/1.6 var(--sans); padding:1px 6px;
  margin-right:8px; border-radius:2px; vertical-align:1px; }
.spec, .audit, .matrix, .changes { border:1px solid var(--line-soft); border-left:3px solid var(--ink); background:var(--surface); }
.audit .st-differs b, .audit .st-pairing b { color:var(--signal); } .audit .st-missing b, .audit .st-unclear b { color:var(--ink-2); }
.spec ul.open li { color:var(--ink-2); } .chk { color:var(--ink-2); }
.pg .hl { background:rgba(255,77,0,.28); }
.pg .textLayer ::selection { background:rgba(255,77,0,.25); }
body.dropping #log { outline-color:var(--signal); } body.dropping #log::before { color:var(--signal); }
.info.STALE, .info.UNRESOLVED, .info.broken { color:var(--ink); }
/* P3: the right column: tabs on top of the panel; closed, a 72px rail of the same tabs */
#right { display:none; min-width:0; }
body.rail #right, body.panel #right { display:flex; flex-direction:column; height:100vh; border-left:1px solid var(--line); background:var(--surface); }
body.rail:not(.panel) { grid-template-columns:220px minmax(0, 1fr) 72px; }
#right #panel { height:auto; flex:1; min-height:0; border-left:0; }
#ptabs { display:flex; flex:none; border-bottom:1px solid var(--line); }
.ptab { flex:1 1 0; min-width:0; display:flex; flex-direction:column; align-items:center; gap:1px; padding:9px 6px 7px;
  border-bottom:3px solid transparent; line-height:1.3; }
.ptab b { font-size:14px; } .ptab small { font:11px/1.4 var(--mono); color:var(--ink-2); white-space:nowrap; overflow:hidden;
  text-overflow:ellipsis; max-width:100%; } .ptab .short { display:none; }
.ptab.on { background:var(--raised); border-bottom-color:var(--signal); } .ptab:hover:not(:disabled) { background:var(--raised); }
body:not(.panel) #ptabs { flex-direction:column; gap:4px; padding:12px 6px; border-bottom:0; }
body:not(.panel) .ptab { border-bottom:0; border-radius:2px; padding:8px 2px; } body:not(.panel) .ptab b { font-size:13px; }
body:not(.panel) .ptab .long { display:none; } body:not(.panel) .ptab .short { display:block; }
/* P5 / P6: tag editing, the view bar, stage and target groups */
.tg.manual { background:none; border:1px solid var(--signal); color:var(--ink); } .tg.stage.mine { box-shadow:inset 0 0 0 1px var(--signal); }
.tagbtn { font-size:11px; color:var(--ink-3); padding:0 4px; } .tagbtn:hover { color:var(--ink); text-decoration:underline; }
.tagedit { flex-basis:100%; margin-top:6px; padding:12px 14px; border:1px solid var(--signal); border-radius:2px; background:var(--surface);
  display:flex; flex-direction:column; gap:8px; font-size:13px; } .te-st { display:flex; flex-wrap:wrap; gap:4px 14px; }
.te-st small { color:var(--ink-3); } .te-foot { display:flex; gap:8px; justify-content:flex-end; }
.ce-text { width:100%; box-sizing:border-box; resize:vertical; padding:6px 8px; border:1px solid var(--line-soft); border-radius:2px;
  background:var(--canvas); color:var(--ink); font:inherit; }
#viewbar { display:flex; gap:4px; align-items:center; margin-top:6px; font-size:12px; }
#viewbar .vtab { padding:2px 10px; border-radius:2px; font-size:12px; color:var(--ink-2); } #viewbar .vtab.on { background:var(--primary); color:var(--on-primary); }
#viewbar .vtab:hover:not(.on):not(:disabled) { background:var(--raised); }
.stagegroup, .targetgroup { max-width:760px; margin:0 auto 16px; padding:12px 16px; border:1px solid var(--line-soft); border-radius:2px; background:var(--surface); }
.stagegroup.st-now { border-color:var(--ink); } .stagegroup.st-later { border-style:dashed; color:var(--ink-3); } .stagegroup.st-past { background:var(--canvas); }
.sg-head { display:flex; gap:8px; align-items:baseline; } .sg-head small, .targetgroup summary small { color:var(--ink-3); font:11px/1.4 var(--mono); }
.sg-sum { margin:8px 0 0; font-size:14px; } .sg-dec { list-style:none; margin:8px 0 0; padding:0; font-size:13px; } .sg-dec li { margin:3px 0; }
.sg-msgs { margin-top:10px; } .sg-msgs > summary, .targetgroup > summary { cursor:pointer; font-size:12px; color:var(--ink-2); display:flex; gap:8px; align-items:center; }
.sg-msgs[open] > summary, .targetgroup[open] > summary { margin-bottom:14px; }
.sg-edit { width:100%; border:1px solid var(--line-soft); border-radius:2px; padding:8px 10px; background:var(--surface); font:inherit; }
/* P7: kinds in the new task form, the settings dialog */
.kinds { display:flex; gap:8px; flex-wrap:wrap; margin:10px 0 4px; }
.kind { flex:1 1 180px; display:grid; grid-template-columns:auto 1fr; gap:2px 8px; align-items:center; padding:10px 12px;
  border:1px solid var(--line-soft); border-radius:2px; cursor:pointer; } .kind:has(input:checked) { border-color:var(--ink); background:var(--raised); }
.kind small { grid-column:2; color:var(--ink-2); font-size:12px; line-height:1.4; }
#settings { position:fixed; inset:0; z-index:20; background:rgba(13,14,16,.45); display:grid; place-items:center; }
.set-box { width:min(560px, 92vw); max-height:86vh; overflow:auto; background:var(--surface); border:1px solid var(--line); border-radius:2px;
  padding:20px 24px; display:flex; flex-direction:column; gap:14px; }
.set-head { display:flex; justify-content:space-between; align-items:center; font-size:17px; }
.set-row { display:flex; gap:16px; justify-content:space-between; align-items:flex-start; padding-top:12px; border-top:1px solid var(--line-soft); }
.set-row small { display:block; color:var(--ink-2); font-size:12px; } .set-opts { display:flex; flex-direction:column; gap:4px; font-size:13px; white-space:nowrap; }
.set-foot { display:flex; gap:8px; justify-content:flex-end; }
/* P4: stage tags and dividers, the stage filter, the model as a text button */
.tags { display:flex; flex-wrap:wrap; gap:4px; align-items:center; margin:8px 0 0; }
.tg { font:500 11px/1.6 var(--sans); padding:0 6px; border-radius:2px; background:var(--raised); color:var(--ink-2); white-space:nowrap; }
.tg.stage { background:var(--primary); color:var(--on-primary); } .tags .more { font-size:11px; color:var(--ink-3); }
.divider { max-width:720px; margin:0 auto 20px; display:flex; align-items:center; gap:10px; }
.divider::after { content:""; flex:1; height:1px; background:var(--line-soft); }
#log > .filtered { display:none; }
#filter-banner { max-width:720px; margin:0 auto 20px; padding:8px 12px; border:1px dashed var(--ink-3); border-radius:2px; font-size:13px;
  display:flex; gap:8px; justify-content:space-between; align-items:center; }
#stages .stage { cursor:pointer; } #stages .stage.picked { outline:2px solid var(--ink); outline-offset:-2px; }
.composer { position:relative; } #model { position:absolute; width:1px; height:1px; opacity:0; pointer-events:none; }
.composer > button.modelbtn { order:1; width:auto; height:auto; border-radius:2px; background:none; color:var(--ink);
  font:500 13px/1.4 var(--sans); padding:4px 8px; white-space:nowrap; } .composer > button.modelbtn:hover { background:var(--raised); }
.composer > button.modelbtn[hidden] { display:none; } .composer > #agent { order:2; } .composer > button:not(.modelbtn) { order:3; }
.composer > .mmenu { position:absolute; right:44px; bottom:calc(100% + 6px); z-index:6; min-width:220px; display:flex; flex-direction:column;
  padding:4px; background:var(--surface); border:1px solid var(--line); border-radius:2px; box-shadow:0 8px 24px rgba(13,14,16,.16); }
.composer > .mmenu[hidden] { display:none; }
.composer .mmenu button.mopt { width:auto; height:auto; border-radius:2px; background:none; color:var(--ink); text-align:left;
  padding:7px 10px; font-size:13px; } .composer .mmenu button.mopt.on, .composer .mmenu button.mopt:hover { background:var(--raised); }
/* P2: header state chip + source card, stage bar, 보낼 곳 inside the composer */
#tools { max-width:none; width:auto; margin:0; padding:8px 20px; border-bottom:1px solid var(--line); background:var(--surface);
  color:var(--ink); display:block; }
#stages { display:flex; align-items:center; gap:4px; overflow-x:auto; }
#stages .st-line { flex:0 0 12px; height:2px; background:var(--raised); } #stages .st-line.on { background:var(--ink); }
#stages .stage { display:flex; gap:8px; align-items:flex-start; padding:5px 10px 5px 8px; border:1px solid transparent; border-radius:2px;
  min-width:0; flex:0 1 auto; }
#stages .st-n { flex:none; width:20px; height:20px; border-radius:50%; display:grid; place-items:center; margin-top:1px;
  font:600 11px/1 var(--mono); border:1.5px solid var(--ink-3); color:var(--ink-2); }
#stages .st-t { display:flex; flex-direction:column; min-width:0; line-height:1.3; }
#stages .st-t b { font-size:13px; white-space:nowrap; } #stages .st-t small { font:11px/1.4 var(--mono); color:var(--ink-2); white-space:nowrap; }
#stages .st-t > span[id] { display:block; } #stages .st-t .link, #stages .st-more .link { font-size:11px; white-space:nowrap;
  max-width:190px; overflow:hidden; text-overflow:ellipsis; display:block; text-align:left; }
#stages .st-done .st-n { background:var(--ink); border-color:var(--ink); color:var(--on-primary); }
#stages .st-current { background:var(--raised); border-color:var(--signal); } #stages .st-current .st-n { border-color:var(--signal); color:var(--ink); }
#stages .st-stale { border:1px dashed var(--signal); } #stages .st-stale .st-n { border:1.5px dashed var(--signal); color:var(--signal); }
#stages .st-blocked { opacity:.55; } #stages .st-blocked .st-n { border-style:dashed; }
#stages .st-todo b { color:var(--ink-2); font-weight:600; }
#stages .st-more { display:flex; gap:10px; align-items:center; margin-left:auto; padding-left:12px; }
#chips { position:relative; flex:none; }
.statechip { border:1px solid var(--line); border-radius:2px; padding:3px 10px; font:500 12px/1.6 var(--sans); background:var(--surface);
  white-space:nowrap; } .statechip:hover, .statechip[aria-expanded="true"] { background:var(--raised); }
.srccard { position:absolute; right:0; top:calc(100% + 6px); z-index:5; width:min(440px, 80vw); max-height:70vh; overflow:auto;
  background:var(--surface); border:1px solid var(--line); border-radius:2px; box-shadow:0 8px 24px rgba(13,14,16,.16); }
.srccard[hidden] { display:none; }
.sc-sec { padding:12px 16px; border-top:1px solid var(--line-soft); font-size:13px; color:var(--ink-2); } .sc-sec:first-child { border-top:0; }
.srccard #src .plist { display:flex; flex-direction:column; gap:0; margin:8px 0 6px; }
.srccard #src .paper { display:flex; align-items:center; gap:8px; padding:7px 4px; white-space:normal; color:var(--ink);
  border-top:1px solid var(--line-soft); } .srccard #src .paper:first-child { border-top:0; }
.srccard #src .paper::before { content:"PDF"; flex:none; font:600 9px/1 var(--mono); padding:4px 3px; border:1px solid var(--ink);
  border-radius:2px; } .srccard #src .paper[data-kind="web"]::before { content:"WEB"; }
.srccard #src .paper b { font-weight:500; } .srccard #src .paper .link { color:var(--ink); }
.srccard #src.many .plist { margin-left:0; }
.composer #route { order:-1; display:flex; gap:2px; align-items:center; font-size:12px; color:var(--ink-2); white-space:nowrap; }
.composer #route button, .composer #route b { width:auto; height:auto; border-radius:2px; background:none; color:var(--ink);
  padding:2px 8px; font-size:12px; text-decoration:none; }
.composer #route b[data-route] { background:var(--primary); color:var(--on-primary); font-weight:500; }
/* ==== A2 (최종 디자인, Figma "Pablo UI" 페이지 '디자인 · 최종 A2' / 'Kit · A2 컴포넌트와 기초') ====
   The same A colours; modern form: hairlines of ink at low opacity instead of black rules, floating panels on the
   canvas, radii 6–16, soft shadows. Later rules win over the concept-A layer above. */
:root { --a4:rgba(13,14,16,.04); --a5:rgba(13,14,16,.05); --a6:rgba(13,14,16,.06); --a8:rgba(13,14,16,.08);
        --a12:rgba(13,14,16,.12); --white:#fff; --line:var(--a8); --line-soft:var(--a8);
        --r-tag:6px; --r-ctl:8px; --r-in:10px; --r-card:12px; --r-panel:14px; --r-dlg:16px; --side-w:232px;
        --sh-sm:0 1px 2px rgba(13,14,16,.06); --sh-md:0 1px 2px rgba(13,14,16,.05), 0 4px 12px rgba(13,14,16,.06);
        --sh-lg:0 2px 6px rgba(13,14,16,.06), 0 16px 40px rgba(13,14,16,.14); }
/* A2 · shell: the sidebar sits on the canvas; the conversation and the right column float as panels */
body { background:var(--canvas); padding:8px; gap:8px; grid-template-columns:var(--side-w) minmax(0, 1fr); }
body.panel { grid-template-columns:var(--side-w) minmax(0, 1fr) 480px; }
body.rail:not(.panel) { grid-template-columns:var(--side-w) minmax(0, 1fr) 64px; }
body.panel.pdf, body.panel.code { grid-template-columns:var(--side-w) minmax(0, 1fr) min(760px, 48vw); }
body.panel.wide { grid-template-columns:var(--side-w) minmax(0, 1fr) min(900px, 58vw); }
#side { background:none; border:0; padding:6px 6px 8px; height:calc(100vh - 16px); }
#chat, body.rail #right, body.panel #right { height:calc(100vh - 16px); background:var(--surface); border:1px solid var(--a6);
  border-radius:var(--r-panel); box-shadow:var(--sh-sm); overflow:hidden; }
#right #panel, #panel { background:none; }
.ico { display:inline-block; flex:none; width:16px; height:16px; vertical-align:-3px; }
.ico.s12 { width:12px; height:12px; vertical-align:-1px; } .ico.s14 { width:14px; height:14px; vertical-align:-2px; }
code { background:var(--a6); border-radius:var(--r-tag); }
pre.diff, pre.cmd, details.tech pre, #doc .pre { background:var(--a4); border-radius:var(--r-ctl); }
.link, .cite, button.file, .ext, .info a { text-decoration:none; font-weight:600; }
.link:hover, .cite:hover, .cite.on, button.file:hover { text-decoration:underline; text-decoration-color:var(--ink-3); }
.pill { border:1px solid var(--a12); border-radius:var(--r-ctl); background:var(--white); padding:5px 14px; font-weight:500; }
.pill:hover:not(:disabled) { background:var(--a4); }
.pill.on { background:var(--primary); color:var(--on-primary); border-color:var(--primary); }
::-webkit-scrollbar { width:10px; height:10px; } ::-webkit-scrollbar-button { display:none; height:0; width:0; }
::-webkit-scrollbar-track { background:none; } ::-webkit-scrollbar-corner { background:none; }
::-webkit-scrollbar-thumb { background:var(--a12); border-radius:999px; border:3px solid transparent; background-clip:padding-box; }
::-webkit-scrollbar-thumb:hover { background-color:rgba(13,14,16,.24); }
/* A2 · sidebar, header, state chips, stage bar, view bar  (agent A) */
/* sidebar: the brand mark, 새 작업 as the one filled button, the search field, task rows as soft cards */
#side { padding:12px 8px 8px; }
#side .brand { flex-direction:column; align-items:stretch; gap:14px; padding:2px 4px 12px; }
#side .brand b { gap:8px; padding:0 4px; font:600 16px/24px var(--sans); letter-spacing:-0.02em; color:var(--ink); }
#side .brand b::before { content:"P"; flex:none; width:24px; height:24px; border-radius:7px; display:grid; place-items:center;
  background:var(--primary); color:var(--on-primary); font:600 13px/1 var(--sans); letter-spacing:0; }
#side .new { display:flex; align-items:center; gap:8px; width:100%; height:36px; padding:0 12px; border:0; border-radius:var(--r-in);
  background:var(--primary); color:var(--on-primary); font:600 13px/1 var(--sans); box-shadow:var(--sh-sm); }
#side .new:hover:not(:disabled) { background:#26292E; }
#side .searchbox { position:relative; margin:0 4px 10px; }
#side .searchbox > .ico { position:absolute; left:11px; top:11px; color:var(--ink-3); pointer-events:none; }
#task-search { display:block; height:36px; margin:0; padding:0 10px 0 32px; border:1px solid var(--a12); border-radius:var(--r-in);
  background:var(--white); color:var(--ink); font:400 13px/1 var(--sans); }
#task-search::placeholder { color:var(--ink-3); }
#task-search:focus { outline:none; border-color:var(--ink-3); box-shadow:0 0 0 3px var(--a6); }
#side h4 { margin:8px 8px 6px; font:500 12px/1.4 var(--sans); color:var(--ink-3); }
#task-list { padding:0 4px; }
#side .t { margin:0 0 2px; padding:10px; border:1px solid transparent; border-radius:var(--r-in); color:var(--ink-2);
  font:500 13px/1.4 var(--sans); }
#side .t:hover { background:var(--a4); }
#side .t.on { background:var(--white); border-color:var(--a5); box-shadow:var(--sh-sm); color:var(--ink); font-weight:600; }
#side .t small { margin-top:3px; font:400 12px/1.4 var(--sans); color:var(--ink-3); overflow:hidden; text-overflow:ellipsis;
  white-space:nowrap; }
#side details.done, #side details.away { margin-top:8px; padding-top:8px; border-top:1px solid var(--a8); }
#side details.done + details.away { margin-top:0; padding-top:0; border-top:0; }
#side details.away summary, #side details.done summary { list-style:none; display:flex; align-items:center; gap:6px; margin:0 0 4px;
  padding:6px 8px; border-radius:var(--r-ctl); font:500 12px/1.4 var(--sans); color:var(--ink-2); }
#side details > summary::-webkit-details-marker { display:none; }
#side details > summary:hover { background:var(--a4); }
#side details > summary > .ico { color:var(--ink-3); transition:transform .15s ease; }
#side details[open] > summary > .ico { transform:rotate(90deg); }
#side summary .cnt { padding:3px 7px; border-radius:999px; background:var(--a6); color:var(--ink-2); font:500 11px/1 var(--mono); }
/* header: no rule under it (the stage bar draws the hairline); icon buttons for rename and the mobile menu */
/* a narrow header wraps: the state chip goes to its own line, right-aligned, instead of the name and the chip both
   cut to "…" (QA 10/26: "LinearRAG 논문 재현 (Q…" and "r…" once 완료 풀기 joined the row) */
#bar { min-height:56px; padding:8px 16px 8px 20px; gap:8px; row-gap:6px; flex-wrap:wrap; border-bottom:0; }
#bar h1 { flex:0 1 auto; min-width:min(7em, 30%); font:600 17px/1.3 var(--sans); letter-spacing:-0.015em; color:var(--ink); }
#bar h1 .rn-in { height:32px; padding:0 10px; border:1px solid var(--a12); border-radius:var(--r-ctl); background:var(--white);
  font:500 15px/1 var(--sans); letter-spacing:0; }
#bar .grow { flex:1 1 0; min-width:8px; }
#bar .rn { opacity:1; flex:none; width:28px; height:28px; padding:0; display:grid; place-items:center; border-radius:var(--r-ctl);
  color:var(--ink-3); }
#bar .rn:hover, #bar .rn:focus-visible { background:var(--a5); color:var(--ink); }
#bar .kindtag { flex:none; padding:4px 8px; border:1px solid var(--a12); border-radius:var(--r-tag); background:var(--white);
  color:var(--ink-2); font:500 11px/1 var(--sans); white-space:nowrap; }
#bar .quiet { flex:none; padding:6px 6px; border-radius:var(--r-ctl); color:var(--ink-3); font:500 12px/1 var(--sans); }
#bar .quiet:hover { background:var(--a4); color:var(--ink); text-decoration:none; }
#menu { padding:6px; border-radius:var(--r-ctl); line-height:0; color:var(--ink-2); }
#menu:hover { background:var(--a5); color:var(--ink); }
/* the state chip (자료 · 폴더 · 인터넷 as segments) and the source card it opens */
#chips { flex:0 1 auto; min-width:0; margin-left:auto; }
.statechip { display:inline-flex; align-items:center; max-width:100%; height:30px; padding:0 10px; border:1px solid var(--a8);
  border-radius:var(--r-ctl); background:var(--white); color:var(--ink); font:500 12px/1 var(--sans); box-shadow:var(--sh-sm); }
.statechip:hover, .statechip[aria-expanded="true"] { background:linear-gradient(var(--a4), var(--a4)), var(--white); }
.statechip .sc-seg { display:inline-flex; align-items:center; gap:6px; min-width:0; max-width:180px; }
.statechip .sc-seg > span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.statechip .sc-seg + .sc-seg { margin-left:10px; padding-left:10px; border-left:1px solid var(--a8); }
.statechip .sc-seg .ico { color:var(--ink-2); } .statechip .sc-none { color:var(--ink-3); } .statechip .sc-src { flex:none; }
.statechip > .ico { margin-left:8px; color:var(--ink-3); }
.srccard { top:calc(100% + 8px); background:var(--white); border:1px solid var(--a8); border-radius:var(--r-card); box-shadow:var(--sh-lg); }
.sc-sec { padding:12px 16px; border-top-color:var(--a6); }
.srccard #src .paper { border-top-color:var(--a6); }
.srccard #src .paper::before { padding:4px 6px; border:0; border-radius:var(--r-tag); background:var(--a6); color:var(--ink-2);
  font:600 10px/1 var(--mono); }
/* the stage bar: a column per stage under a 3px progress bar (done ink, now orange, left ink 10%) */
#tools { padding:4px 20px 10px; border-bottom:1px solid var(--a8); background:none; }
#stages { align-items:stretch; gap:8px; margin:0 -6px; padding:6px 6px 12px; }
#stages .st-line { display:none; }
#stages .stage { flex:1 1 0; min-width:96px; display:grid; grid-template-columns:auto minmax(0, 1fr); column-gap:6px; row-gap:2px;
  align-content:start; align-items:center; padding:0 0 2px; border:0; border-radius:var(--r-ctl); background:none; opacity:1; }
#stages .stage::before { content:""; grid-column:1 / -1; height:3px; margin-bottom:8px; border-radius:2px; background:rgba(13,14,16,.1); }
#stages .stage:hover { background:var(--a4); box-shadow:0 0 0 4px var(--a4); }
#stages .stage.picked, #stages .stage.picked:hover { outline:0; background:var(--a5); box-shadow:0 0 0 4px var(--a5); }
#stages .st-done::before { background:var(--ink); } #stages .st-current::before { background:var(--signal); }
#stages .st-stale::before { background:rgba(13,14,16,.35); }
#stages .st-t { display:contents; }
#stages .st-n { grid-column:1; width:auto; height:auto; margin:0; border:0; border-radius:0; background:none; display:inline-flex;
  align-items:center; font:500 11px/1 var(--mono); color:var(--ink-3); }
#stages .st-done .st-n { background:none; color:var(--ink); }
#stages .st-current .st-n { color:var(--signal); font-weight:600; }
#stages .st-stale .st-n { border:0; color:var(--signal); }
#stages .st-blocked .st-n { color:var(--ink-3); }
#stages .st-t b { grid-column:2; min-width:0; overflow:hidden; text-overflow:ellipsis; font:600 13px/1.35 var(--sans); color:var(--ink); }
#stages .st-todo b { font-weight:500; color:var(--ink-2); } #stages .st-blocked b { font-weight:500; color:var(--ink-3); }
#stages .st-t small { grid-column:1 / -1; min-width:0; overflow:hidden; text-overflow:ellipsis; font:400 12px/1.4 var(--sans);
  color:var(--ink-3); }
#stages .st-current .st-t small { font-weight:500; color:var(--ink-2); }
#stages .st-t > span[id] { grid-column:1 / -1; min-width:0; margin-top:2px; }
#stages .st-t .link, #stages .st-more .link { max-width:100%; font-size:12px; font-weight:600; }
#stages .st-more { flex:none; align-self:center; flex-direction:column; align-items:flex-end; gap:4px; padding-left:8px; }
/* the view bar: a segmented control under a hairline */
#viewbar { gap:10px; margin:0 -20px; padding:10px 20px 0; border-top:1px solid var(--a8); }
#viewbar > .muted { color:var(--ink-3); font-size:12px; }
#viewbar .vseg { display:inline-flex; gap:2px; padding:3px; border-radius:9px; background:var(--a5); }
#viewbar .vtab { padding:5px 12px; border-radius:7px; background:none; color:var(--ink-2); font:500 12px/1.2 var(--sans); }
#viewbar .vtab.on { background:var(--white); color:var(--ink); font-weight:600; box-shadow:var(--sh-sm); }
#viewbar .vtab:hover:not(.on):not(:disabled) { background:none; color:var(--ink); }
@media (max-width:900px) { #side { height:auto; background:var(--canvas); } #bar .kindtag { display:none; } }
/* end A2 · sidebar */
/* A2 · conversation, cards, composer  (agent B) */
/* messages: a 680 column, 28px avatars (Pablo is the one black fill), name 13 / time mono 11, body 14/22 */
#log { padding:28px 24px 40px; }
.msg { max-width:680px; grid-template-columns:28px minmax(0, 1fr); gap:12px; margin:0 auto 24px; font-size:14px; line-height:22px; }
.av { width:28px; height:28px; font:600 11px/1 var(--sans); background:var(--a8); color:var(--ink-2); }
.msg.pablo .av { background:var(--primary); color:var(--on-primary); border-color:var(--primary); font-size:12px; }
.who { display:flex; align-items:center; gap:8px; min-height:28px; font-size:13px; font-weight:600; line-height:20px; color:var(--ink); }
.who small { margin-left:0; font:400 11px/1 var(--mono); color:var(--ink-3); }
.msg p { margin:2px 0 8px; } .msg .muted { font-size:13px; line-height:20px; }
/* tags: stage on ink 6%, targets white with a hairline, a person's 결정 orange-edged, Pablo's suggestion on signal-soft */
.tags { gap:6px; margin:10px 0 0; }
.tg { display:inline-flex; align-items:center; gap:4px; font:500 11px/16px var(--sans); padding:2px 7px; border-radius:var(--r-tag);
  background:var(--white); color:var(--ink-2); border:1px solid var(--a12); vertical-align:1px; }
.tg.stage { background:var(--a6); color:var(--ink-2); border-color:transparent; }
.tg.stage.mine { border-color:var(--signal); box-shadow:none; }
.tg.manual { background:var(--white); border-color:var(--signal); color:var(--ink); font-weight:600; }
.tg[data-auto-summary] { background:var(--signal-soft); border-color:transparent; color:var(--ink); }
.tg[data-auto-summary] .ico { color:var(--signal); }
.tagbtn, .tags .more { font-size:11px; line-height:16px; color:var(--ink-3); }
.tagbtn { display:inline-flex; align-items:center; gap:3px; padding:3px 5px; border-radius:var(--r-tag); }
.tagbtn:hover { color:var(--ink); background:var(--a5); text-decoration:none; }
/* the stage divider: a pill with a dot (orange = the task's current stage), the time, a hairline */
.divider { max-width:680px; gap:8px; margin:4px auto 20px; }
.divider .tg.stage { gap:6px; border-radius:999px; padding:2px 10px 2px 8px; font-weight:600; }
.divider .dot, .stagehint .dot { flex:none; width:6px; height:6px; border-radius:50%; background:var(--ink-3); }
.divider[data-now] .dot { background:var(--signal); }
.divider small { font:400 11px/1 var(--mono); color:var(--ink-3); white-space:nowrap; }
.divider::after { background:var(--a8); }
/* WARN cards (확인 필요 · 결정이 필요): white, an orange 3px left edge, no dashes; BLOCK (막음): ink 4%, no border */
.call { background:var(--white); border:0; border-left:3px solid var(--signal); border-radius:var(--r-card); box-shadow:var(--sh-md);
  padding:12px 16px; margin:10px 0; }
.call .head { color:var(--ink); font-size:13px; font-weight:600; line-height:20px; margin:0 0 6px; }
.call.block { background:var(--a4); border:0; box-shadow:none; }
.call.block .head { color:var(--ink); }
.call.lock .head::before { border-radius:var(--r-tag); padding:2px 7px; font:600 11px/16px var(--sans); vertical-align:1px; }
#acct .call, #shell-note .call { margin:0 0 8px; }
/* records: conditions, 재현 점검, 비교표, changed files — white cards, hairline rows */
.spec, .audit, .matrix, .changes { background:var(--white); border:1px solid var(--a8); border-radius:var(--r-card); box-shadow:var(--sh-sm);
  padding:12px 16px; margin:10px 0; }
.spec .head, .audit .head, .matrix .head { font-size:14px; font-weight:600; line-height:22px; margin:0 0 6px; }
.spec h4 { font-size:11px; font-weight:600; color:var(--ink-3); margin:10px 0 4px; padding-top:10px; border-top:1px solid var(--a6); }
.spec li { margin:3px 0; }
.audit li { padding:8px 0; border-top:1px solid var(--a6); }
.audit .stale, .audit .ps51 { background:var(--signal-soft); border:0; border-radius:var(--r-in); padding:8px 12px; margin:6px 0 8px; }
.audit .stale.same { background:var(--a4); }
.audit .outside h4 { font-size:11px; font-weight:600; color:var(--ink-3); }
.changes p { font-size:13px; }
.matrix.wide { box-shadow:none; border:0; background:none; padding:0; margin:0; }
.matrix .scroll { border:1px solid var(--a6); border-radius:var(--r-card); margin:8px 0; }
.matrix table { border-style:hidden; }
.matrix th, .matrix td { border:1px solid var(--a6); padding:7px 10px; }
.matrix thead th { background:var(--a4); font-weight:600; color:var(--ink-2); }
/* 단계별 · 대상별 views, the stage filter banner, the tag editor */
.stagegroup, .targetgroup { max-width:680px; margin:0 auto 12px; padding:14px 16px; background:var(--white); border:1px solid var(--a8);
  border-radius:var(--r-card); }
.stagegroup.st-now { border-color:var(--a12); box-shadow:var(--sh-sm); }
.stagegroup.st-later, .stagegroup.st-past { background:var(--a4); border-style:solid; border-color:transparent; }
.sg-head { align-items:center; } .sg-head b { font-size:13px; font-weight:600; }
.sg-sum { line-height:22px; } .sg-msgs > summary, .targetgroup > summary { color:var(--ink-2); }
.stagegroup .msg { margin-bottom:16px; }
.sg-edit, .ce-text { background:var(--white); border:1px solid var(--a12); border-radius:var(--r-in); padding:8px 10px; }
#filter-banner { max-width:680px; background:var(--a4); border:0; border-radius:var(--r-in); padding:8px 14px; }
.tagedit { background:var(--white); border:1px solid var(--a8); border-radius:var(--r-card); box-shadow:var(--sh-lg); padding:14px 16px; }
.tagedit > b { font-size:13px; font-weight:600; }
/* [n]: a small orange-soft pill */
.cite { background:var(--signal-soft); border-radius:5px; padding:1px 5px; font:600 11px/16px var(--mono); color:var(--ink);
  text-decoration:none; margin-left:2px; vertical-align:1px; }
.cite:hover { text-decoration:none; box-shadow:inset 0 0 0 1px var(--signal); }
.cite.on { text-decoration:none; background:var(--signal); color:var(--white); }
pre.diff, pre.cmd { background:var(--a4); border-radius:var(--r-ctl); }
/* the composer: a white floating box; the text on top, 보낼 곳 · stage · model · send below */
#chat > .composer { max-width:680px; width:calc(100% - 48px); margin:0 auto 16px; flex-wrap:wrap; gap:8px; align-items:center;
  background:var(--white); border:1px solid var(--a12); border-radius:var(--r-panel); box-shadow:var(--sh-lg); padding:12px 12px 10px 16px; }
#chat > .composer > input { order:-5; flex:1 1 100%; font-size:14px; line-height:22px; padding:2px 0 4px; }
#chat > .composer > input::placeholder { color:var(--ink-3); }
#chat > .composer > button:not(.modelbtn) { order:5; flex:none; width:32px; height:32px; border-radius:50%; display:grid; place-items:center;
  background:var(--primary); color:var(--on-primary); }
#chat > .composer > input + button { margin-left:auto; }
#chat > .composer[data-running="1"] > button:not(.modelbtn) .ico { fill:currentColor; }
#chat > .composer #route { order:1; display:inline-flex; align-items:center; gap:8px; font-size:12px; color:var(--ink-3); }
.composer #route .seg { display:inline-flex; gap:2px; padding:2px; background:var(--a5); border-radius:var(--r-ctl); }
.composer #route .seg > b, .composer #route .seg > button { border-radius:var(--r-tag); padding:4px 10px; font:500 12px/16px var(--sans);
  color:var(--ink-2); background:none; text-decoration:none; }
.composer #route .seg > button:hover { color:var(--ink); background:var(--a5); }
.composer #route .seg > b[data-route] { background:var(--white); color:var(--ink); box-shadow:var(--sh-sm); font-weight:600; }
#chat > .composer > .stagehint { order:2; flex:1 1 0; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
  font-size:12px; line-height:22px; color:var(--ink-3); }  /* basis 0: the hint never pushes send onto a third row */
#chat > .composer > .stagehint[hidden] { display:none; }
.stagehint .tg.stage { gap:5px; border-radius:999px; padding:2px 8px 2px 7px; font-weight:600; }
.stagehint .dot { width:5px; height:5px; background:var(--signal); }
#chat > .composer > #agent { order:3; margin-left:auto; display:inline-flex; align-items:center; font-size:12px; color:var(--ink-3); }
#chat > .composer > button.modelbtn { order:4; display:inline-flex; align-items:center; gap:4px; border-radius:var(--r-ctl); padding:5px 8px;
  font:500 12px/16px var(--mono); color:var(--ink-2); background:none; }
#chat > .composer > button.modelbtn:hover { background:var(--a5); color:var(--ink); }
#chat > .composer > button.modelbtn[hidden] { display:none; }
#chat > .composer > .mmenu { right:52px; bottom:calc(100% + 8px); padding:4px; background:var(--white); border:1px solid var(--a8);
  border-radius:var(--r-card); box-shadow:var(--sh-lg); }
.composer .mmenu button.mopt { border-radius:var(--r-ctl); padding:8px 10px; font:500 12px/16px var(--mono); color:var(--ink); }
.composer .mmenu button.mopt.on, .composer .mmenu button.mopt:hover { background:var(--a5); }
.composer .mmenu button.mopt.on { font-weight:600; }
/* above the composer: the account card, the PowerShell note, the + 추가 box */
#acct, #shell-note, #adder { max-width:680px; width:calc(100% - 48px); }
#acct { margin:0 auto 8px; font-size:12px; color:var(--ink-3); }
#adder #arxiv { border:1px solid var(--a12); border-radius:var(--r-in); background:var(--white); padding:6px 10px; }
#adder #arxiv:focus { outline:none; border-color:var(--ink-3); }
/* end A2 · conversation */
/* A2 · right column, panels, dialogs, empty state  (agent C) */
/* tabs, open: a segmented bar (ink 5% frame, the open tab a white cell with an orange dot) */
#ptabs { margin:10px 10px 0; padding:4px; gap:2px; background:var(--a5); border-radius:12px; border-bottom:0; }
.ptab { border-bottom:0; border-radius:9px; padding:7px 10px; align-items:flex-start; text-align:left; gap:0; line-height:1.35; }
.ptab b { display:flex; align-items:center; gap:6px; font:500 13px/1.4 var(--sans); color:var(--ink-2); }
.ptab small { font:11px/1.4 var(--sans); color:var(--ink-3); }
.ptab:hover:not(:disabled) { background:var(--a5); }
.ptab.on, .ptab.on:hover:not(:disabled) { background:var(--white); box-shadow:var(--sh-sm); }
.ptab.on b { font-weight:600; color:var(--ink); }
.ptab.on b::before { content:""; flex:none; width:6px; height:6px; border-radius:50%; background:var(--signal); }
.ptab.on small { color:var(--ink-2); }
/* tabs, closed: the rail */
body:not(.panel) #ptabs { margin:0; padding:10px 6px; gap:4px; background:none; border-radius:0; }
body:not(.panel) .ptab { flex:none; border-radius:10px; padding:8px 2px; align-items:center; text-align:center; }
body:not(.panel) .ptab b { font-size:12px; font-weight:600; color:var(--ink); justify-content:center; }
body:not(.panel) .ptab small { font:11px/1.4 var(--mono); color:var(--ink-3); }
/* panel head: no rule; icon buttons for close, back / forward, page turns */
.phead { border-bottom:0; padding:14px 12px 6px 18px; gap:4px; min-height:48px; }
.phead h2 { font:600 15px/1.4 var(--sans); color:var(--ink); }
.x, .nav, .ext { flex:none; width:28px; height:28px; padding:0; display:inline-grid; place-items:center; border-radius:var(--r-ctl);
  color:var(--ink-3); font-size:16px; line-height:1; text-decoration:none; }
.nav, .ext { color:var(--ink-2); }
.x:hover, .nav:hover:not(:disabled), .ext:hover { background:var(--a5); color:var(--ink); text-decoration:none; }
.url { margin:0 4px; background:var(--a5); border-radius:var(--r-ctl); padding:5px 10px; font-size:12px; line-height:1.5; color:var(--ink-2); }
.url .ico { color:var(--ink-3); margin-right:6px; } .url .em { display:none; } .url b { font-weight:600; color:var(--ink); }
.phead .open { font:600 12px/1.4 var(--sans); padding:5px 6px; border-radius:var(--r-ctl); }
.phead .open:hover { background:var(--a5); text-decoration:none; }
.pnum { font:11px/1.4 var(--mono); color:var(--ink-2); padding:0 2px; }
#pbody { padding:6px 14px 16px; }
#pbody h3 { font:600 12px/1.4 var(--sans); color:var(--ink-2); margin:18px 2px 8px; }
#pbody h3:first-child { margin-top:6px; }
#pbody > p.muted, #pbody > .muted { font-size:12px; color:var(--ink-2); margin:12px 2px; }
/* info line under the head: a soft bar; stale / unresolved / broken in the signal tint */
.info { margin:0 14px 8px; padding:7px 12px; border:0; border-radius:var(--r-ctl); background:var(--a4); color:var(--ink-2); font-size:12px; line-height:1.5; }
.info.STALE, .info.UNRESOLVED, .info.broken { background:var(--signal-soft); color:var(--ink); }
/* 기준: each list a white card, rows on hairlines, no markers; a row's buttons show on hover / focus */
#panel ul.ck { background:var(--white); border:1px solid var(--a8); border-radius:var(--r-card); overflow:hidden; }
#panel ul.ck > li { padding:10px 12px; border-top:1px solid var(--a6); font-size:14px; line-height:1.55; }
#panel ul.ck > li:first-child { border-top:0; }
#panel ul.ck > li::before { content:none; }
#panel ul.ck .all { font:500 11px/1.6 var(--sans); color:var(--signal); background:var(--signal-soft); border-radius:var(--r-tag);
  padding:0 6px 0 3px; margin-left:4px; white-space:nowrap; vertical-align:1px; }
#panel ul.ck .muted { font-size:12px; color:var(--ink-2); }
#panel ul.ck .chk.dev { display:block; margin:4px 0 0; font-size:12px; color:var(--ink-2); white-space:normal; }
.ck .note { display:flex; flex-wrap:wrap; gap:4px; margin-top:4px; font-size:12px; color:var(--ink-2); }
/* (opacity, not display: tests .click() them; out of the flow so a hidden group takes no width from the text) */
#panel ul.ck > li { position:relative; }
#panel ul.ck .edits, #panel ul.ck .acts { font-size:12px; color:var(--ink-3); opacity:0; transition:opacity .12s; }
#panel ul.ck > li > .edits, #panel ul.ck > li > .acts { position:absolute; right:6px; bottom:6px; padding:2px 6px 2px 18px;
  background:linear-gradient(90deg, transparent, var(--white) 14px); border-radius:0 var(--r-ctl) var(--r-ctl) 0; }
#panel ul.ck li:hover .edits, #panel ul.ck li:hover .acts, #panel ul.ck li:focus-within .edits, #panel ul.ck li:focus-within .acts,
#panel ul.ck .edits:has(input, select, .muted), #panel ul.ck .acts:has(input, select, .muted) { opacity:1; }
#panel ul.ck > li > .edits:has(input, select, .muted), #panel ul.ck > li > .acts:has(input, select, .muted) { position:static; display:block;
  margin-top:6px; padding:0; background:none; white-space:normal; }
#panel ul.ck .edits:has(input, select) { white-space:normal; }
#panel ul.ck .edits .link { font-size:12px; font-weight:600; color:var(--ink-3); } #panel ul.ck .edits .link:hover { color:var(--ink); }
#panel ul.ck .edits .why { border:1px solid var(--a12); border-radius:var(--r-ctl); padding:3px 8px; background:var(--white); color:var(--ink);
  width:min(250px, 100%); font-size:12px; outline:none; margin:2px 0; } #panel ul.ck .edits select.why { width:auto; max-width:100%; }
#panel ul.ck .edits .why:focus { border-color:var(--ink-3); }
#panel ul.ck .edits .why.need { border-color:var(--signal); box-shadow:0 0 0 3px var(--signal-soft); }
#panel h4.kind { display:block; border:0; border-radius:0; padding:0; margin:14px 2px 6px; background:none; cursor:auto;
  font:600 12px/1.4 var(--sans); color:var(--ink-2); }
#panel details.gone { margin-top:14px; }
#panel details.gone > summary { list-style:none; display:flex; align-items:center; gap:4px; padding:4px 2px; margin-bottom:6px;
  font:500 12px/1.4 var(--sans); color:var(--ink-2); }
#panel details.gone > summary::-webkit-details-marker { display:none; }
#panel details.gone > summary .ico { color:var(--ink-3); transition:transform .12s; } #panel details.gone[open] > summary .ico { transform:rotate(90deg); }
#panel details.gone s { color:var(--ink-3); }
#pbody [data-how], #pbody p.muted:has([data-open-paper]) { font-size:12px; color:var(--ink-2); margin:12px 2px 0; }
#pbody [data-open-paper] .ico { margin-right:2px; }
.pfoot { border-top:0; padding:8px 14px 14px; }
#panel .pfoot .composer { width:100%; max-width:none; margin:0; background:var(--white); border:1px solid var(--a12); border-radius:var(--r-in);
  padding:6px 6px 6px 12px; box-shadow:none; }
#panel .pfoot .composer button { width:28px; height:28px; border-radius:var(--r-ctl); background:var(--primary); color:var(--on-primary);
  display:grid; place-items:center; }
/* 계획: a card of steps; done a check, the current step orange, the rest their number */
#panel ol.steps { background:var(--white); border:1px solid var(--a8); border-radius:var(--r-card); overflow:hidden; }
#panel ol.steps li { grid-template-columns:20px 1fr; gap:2px 10px; padding:10px 12px; border-bottom:0; border-top:1px solid var(--a6); font-size:14px; line-height:1.55; }
#panel ol.steps li:first-child { border-top:0; }
#panel ol.steps .i { display:grid; place-items:center; height:22px; font:500 11px/1 var(--mono); color:var(--ink-3); }
#panel ol.steps .done .i { color:var(--ink); } #panel ol.steps .doing .i { color:var(--signal); font-weight:700; }
#panel ol.steps .sub { font-size:12px; color:var(--ink-2); }
/* 왜?: the timeline */
.tl li { padding:0 0 18px 24px; }
.tl li::before { left:4px; top:12px; bottom:-6px; border-left:2px solid var(--a8); }
.tl li::after { left:0; top:5px; width:10px; height:10px; background:var(--white); border:2px solid var(--ink-3); }
.tl li.ev::after { border-color:var(--ink); } .tl li.warn::after { border-color:var(--signal); }
.tl li.stop::after { border-color:var(--ink); background:var(--ink); }
.tl .k { font:600 13px/1.5 var(--sans); color:var(--ink); } .tl .v { font-size:13px; line-height:1.55; color:var(--ink-2); }
.tl li.ev .v:hover { color:var(--ink); }
/* evidence views: the PDF page on the canvas, code on white, the sentence picker */
#pbody.pdf { background:var(--canvas); }
.pg { border-radius:4px; box-shadow:var(--sh-md); } .pg canvas { border-radius:4px; }
#pbody.code { background:var(--white); border-top:1px solid var(--a6); }
.src .n { color:var(--ink-3); } .src .ln.on { background:var(--signal-soft); }
#pick { background:var(--white); border-top:1px solid var(--a8); padding:10px 14px; gap:8px; }
#pick input, #pick select { border:1px solid var(--a12); border-radius:var(--r-ctl); padding:4px 8px; background:var(--white); }
#pick .q { color:var(--ink-2); }
/* new task form */
#goal { display:block; margin:8px 0 0; background:var(--white); border:1px solid var(--a12); border-radius:var(--r-in); padding:10px 12px;
  line-height:1.55; outline:none; }
#goal:focus { border-color:var(--ink-3); box-shadow:0 0 0 3px var(--a5); }
.kinds { gap:8px; margin:12px 0 6px; }
.kinds .kind { border:1px solid var(--a8); border-radius:var(--r-card); background:var(--white); padding:12px 14px; }
.kinds .kind:hover { border-color:var(--a12); }
.kinds .kind:has(input:checked) { border:1.5px solid var(--ink); background:var(--white); padding:11.5px 13.5px; }
.kinds .kind input { accent-color:var(--ink); margin:0; }
.kinds .kind b { font:600 14px/1.4 var(--sans); } .kinds .kind small { color:var(--ink-2); font-size:12px; }
[data-kind-stages] { font-size:12px; color:var(--ink-2); }
/* settings dialog */
#settings { background:rgba(13,14,16,.45); }
.set-box { background:var(--surface); border:1px solid var(--a8); border-radius:var(--r-dlg); box-shadow:var(--sh-lg); padding:20px 24px; gap:14px; }
.set-head { font:600 17px/1.4 var(--sans); }
.set-row { border-top:1px solid var(--a6); padding-top:14px; }
.set-row b { font-size:14px; font-weight:600; } .set-row small { color:var(--ink-2); font-size:12px; margin-top:2px; }
.set-opts label { display:flex; align-items:center; gap:6px; cursor:pointer; }
#settings input[type=radio], #settings input[type=checkbox] { accent-color:var(--ink); margin:0; }
.set-foot { padding-top:4px; }
/* first run */
.empty { margin:16vh auto 0; padding:0 16px; text-align:center; color:var(--ink-2); }
.empty b { font:700 22px/1.35 var(--sans); color:var(--ink); margin-bottom:6px; }
.empty p { margin:0 0 18px; font-size:14px; }
.empty .pill { display:inline-flex; align-items:center; gap:6px; padding:8px 16px; }
.empty .card { background:var(--white); border:1px solid var(--a8); border-radius:var(--r-card); }
/* end A2 · right column */
@media (max-width:900px) {
  body { padding:0; } #chat { height:100vh; border-radius:0; border:0; }
  body, body.panel { display:block; }
  #side { display:none; position:fixed; inset:0 30% 0 0; z-index:3; box-shadow:0 0 0 100vmax var(--shade); }
  body.side #side { display:block; } #menu { display:block; }
  #panel { position:fixed; inset:0; z-index:4; } #bar { padding:10px 12px; } #log { padding:18px 12px 32px; }
  .msg { grid-template-columns:26px minmax(0, 1fr); gap:8px; } .av { width:26px; height:26px; } }
</style></head>
<body>
<nav id="side"></nav>
<section id="chat"><header id="bar"></header><div id="log"></div>
  <div class="composer"><input disabled placeholder="Pablo에게 물어보세요… (읽기 전용 미리보기)"><button disabled title="보내기" aria-label="보내기"><svg class="ico" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 7-7 7 7M12 19V5"/></svg></button></div></section>
<div id="right"><nav id="ptabs"></nav><aside id="panel"></aside></div>
<script type="application/json" id="data">{{DATA}}</script>
<script>
let M = JSON.parse(document.getElementById("data").textContent);  // M5.1: replaced by the desktop's live state
const $ = id => document.getElementById(id);
const ART = {{ART}}, art = (k, cls) => h("img", { class: "mascot" + (cls ? " " + cls : ""), src: ART[k], alt: "" });
function h(tag, attrs, ...kids) {  // text only: data never becomes HTML
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "on") el.addEventListener("click", v); else if (v != null && v !== false) el.setAttribute(k, v);
  }
  for (const c of kids.flat(Infinity)) if (c != null && c !== false) el.append(c instanceof Node ? c : String(c));
  return el;
}
// A2: line icons (24 grid, stroke = currentColor), the set of the Figma Kit a2/icon. ico("plus", 14) -> <svg class="ico s14">
const ICONS = { plus: "M12 5v14M5 12h14", search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zm9 2-3.5-3.5", "chevron-down": "m6 9 6 6 6-6",
  "chevron-right": "m9 18 6-6-6-6", file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6",
  folder: "M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z",
  globe: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM2 12h20M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20",
  "globe-off": "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM2 12h20m-17.1-7.1 14.2 14.2", check: "M20 6 9 17l-5-5",
  "check-circle": "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zm-3-10 2 2 4-4", info: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zm0-6v-4m0-4h.01",
  message: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z", more: "M5 12h.01M12 12h.01M19 12h.01",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  "panel-left": "M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zm4 0v18",
  "panel-right": "M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zm10 0v18", filter: "M3 6h18M7 12h10M10 18h4",
  "arrow-up": "m5 12 7-7 7 7M12 19V5", stop: "M7 7h10v10H7z", pencil: "M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z",
  trash: "M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2", swap: "m16 3 4 4-4 4M20 7H4m4 14-4-4 4-4M4 17h16",
  lock: "M6 11h12a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2zm2 0V7a4 4 0 0 1 8 0v4", rotate: "M21 12a9 9 0 1 1-3-6.7L21 8m0-5v5h-5",
  sparkle: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z", x: "M18 6 6 18M6 6l12 12", external: "M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6",
  pin: "M12 17v5M9 10.8V4h6v6.8l2 3.2H7z", paperclip: "m21.4 11.1-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5" };
function ico(name, size) {
  const NS = "http://www.w3.org/2000/svg", s = document.createElementNS(NS, "svg"), p = document.createElementNS(NS, "path");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("class", "ico" + (size && size !== 16 ? " s" + size : "")); s.setAttribute("aria-hidden", "true");
  for (const [k, v] of [["fill", "none"], ["stroke", "currentColor"], ["stroke-width", "2"], ["stroke-linecap", "round"], ["stroke-linejoin", "round"]]) s.setAttribute(k, v);
  p.setAttribute("d", ICONS[name] || ICONS.more); s.append(p); return s;
}
// `code`, paths (a/b/c) and camelCase identifiers render as code
function rich(text) {
  const out = [], re = /`([^`]+)`|([A-Za-z_~][\w.~-]*\/[\w./-]*\w|\b[a-z]+[A-Z][A-Za-z]*\b)/g;
  let p = 0;
  for (const m of text.matchAll(re)) { out.push(text.slice(p, m.index), h("code", null, m[1] || m[2])); p = m.index + m[0].length; }
  out.push(text.slice(p));
  return out;
}
const ISSUE = { source_tool_error: "초기 검색 결과와 공식 원문이 달랐습니다.", source_changed: "원문이 바뀌었습니다.",
                source_conflict: "출처끼리 내용이 다릅니다.", insufficient_coverage: "처음 조사가 부족했습니다.",
                other: "조사 과정에서 문제가 있었습니다." };
const ALIGN = { aligned: "계획대로 실행했습니다", partial: "일부만 실행했습니다", deviated: "계획과 다르게 실행했습니다",
                failed: "실행에 실패했습니다", not_executed: "실행하지 않았습니다" };
const DECIDE = { proceed: "사용자가 진행을 승인했습니다", defer: "사용자가 보류했습니다", reject: "사용자가 취소했습니다" };
// stored times are UTC ISO; shown in the user's local time
const time = s => s ? new Date(s).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) : "";
const day = s => new Date(s).toLocaleDateString("ko-KR");
// M5.1 presentation only: the stored action text (raw command / full path) -> what it does; raw stays in 기술 세부정보
const base = p => p.trim().replace(/["']/g, "").split(/[\\/]/).pop();
const VERB = { "파일 생성": "생성", "파일 삭제": "삭제", "파일 수정": "수정", "파일 변경": "변경" };
function meaning(text) {
  const first = (text || "").split("\n")[0];
  const fc = [...first.matchAll(/(파일 생성|파일 삭제|파일 수정|파일 변경): ([^,]+)/g)];
  if (fc.length) return fc.map(m => `${base(m[2])} ${VERB[m[1]]}`).join(", ");
  if (!/^(명령 실행|실행 결과): /.test(first)) return first;
  const cmd = first.replace(/^[^:]+:\s*/, "");
  // ponytail: first file-like token that is not the shell itself; a real command parser if this misnames often
  const f = (cmd.match(/[\w-]+\.[A-Za-z]\w{0,7}\b/g) || []).filter(x => !/\.exe$/i.test(x))[0] || "";
  const at = what => f ? `${f} ${what}` : what;
  if (/\b(pytest|unittest|npm( run)? test|jest|vitest)\b/i.test(cmd)) return "테스트 실행";
  if (/\b(Remove-Item|rm|del|erase)\b/i.test(cmd)) return at("삭제");
  if (/\b(Set-Content|Add-Content|Out-File|WriteAll(Text|Lines|Bytes)|AppendAll(Text|Lines))\b/i.test(cmd)) return at("수정");
  if (/\b(Get-Content|cat|type|ReadAll(Text|Lines|Bytes))\b/i.test(cmd)) return at("읽기");
  if (/\b(Get-ChildItem|ls|dir)\b/i.test(cmd)) return "폴더 목록 보기";
  return "명령 실행";
}
// the command without the shell wrapper the agent runs it in ("...pwsh.exe" -NoProfile -Command "<this>")
function shell(cmd) {
  const m = cmd.match(/^"?[^"\n]*?(?:pwsh|powershell|cmd)(?:\.exe)?"?\s+(?:-\w+\s+)*?(?:-Command|-c|\/c)\s+([\s\S]+)$/i);
  let x = (m ? m[1] : cmd).trim();
  if (x.length > 1 && (x[0] === '"' || x[0] === "'") && x.at(-1) === x[0]) x = x.slice(1, -1).replaceAll(x[0] + x[0], x[0]);
  return x;
}
// what the card is about, shown as is: a file change's diff (detail, or the stored text after its first line), else the command
function preview(text, detail) {
  const [first, ...rest] = (text || "").split("\n"), diff = detail || rest.join("\n");
  if (/^명령 실행: /.test(first)) return h("pre", { class: "cmd" }, shell((text || "").replace(/^명령 실행: /, "")));
  if (!diff.trim()) return null;
  const kind = l => /^(---|\+\+\+) |^diff --git /.test(l) ? "file" : /^@@/.test(l) ? "hunk" : /^\+/.test(l) ? "add" : /^-/.test(l) ? "del" : "";
  return h("pre", { class: "diff" }, diff.split("\n").map(l => h("span", { class: kind(l) }, l)));
}
const tech = (...xs) => xs.some(Boolean) ? h("details", { class: "tech" }, h("summary", null, "기술 세부정보"),
  xs.filter(Boolean).map(x => h("pre", null, x))) : null;
// an English judge note -> a Korean line in the card; the note itself goes under 기술 세부정보
const korean = t => /[가-힣]/.test((t || "").replace(/"[^"]*"/g, ""));
const reason = (t, block) => !t ? null : korean(t) ? h("p", null, rich(t))
  : h("p", null, block ? "작업 기준과 충돌해 막았습니다." : "현재 작업 기준과 맞는지 확인이 필요합니다.");
const host = u => { try { const x = new URL(u); return x.host + x.pathname; } catch { return u; } };
let V, cites = {}, hist = [], hi = -1, busy = null, lastEv = null;  // lastEv: the last source / code / paper / table shown (the 근거 tab reopens it)  // busy: the task whose agent turn or PDF question is running
const lives = {}, live = t => (t = t || V.task.id, lives[t] || (lives[t] = h("div", { id: "live" })));  // agent chat, one per task (own thread)

// ---- citations: [n] -> the existing EvidenceAnchor id (data-e); numbering is per task ---------------------
const onWeb = e => (M.sources[(M.anchors[e] || {}).source] || {}).kind !== "pdf";  // D1: a web page's quote, not a paper's
function cite(e, n) {  // n: the answer's own number (M3.3 ask); else one number per evidence in this chat
  if (!(e in cites)) cites[e] = Object.keys(cites).length + 1;
  const web = onWeb(e);
  return h("button", { class: "cite" + (web ? " web" : ""), "data-e": e, title: web ? "근거 보기 (웹 문서)" : "근거 보기",
    on: () => show({ mode: "source", e }) }, `[${web ? "🌐" : ""}${n || cites[e]}]`);
}
// D1: an answer whose every quote is from a web page says so: Pablo did not find it in a paper (it stays PARTIALLY_VERIFIED)
const webOnly = k => k.evidence.length > 0 && k.evidence.every(onWeb)
  ? h("p", { class: "muted", "data-web-only": "1" }, "🌐 웹 문서에만 근거한 답입니다. 논문에서 확인되지 않았습니다.") : null;
// ponytail: a citation goes after the sentence that contains its quote, else after the text; no claim-level matching
function cited(text, eids) {
  const ns = [...text.matchAll(/\[(\d+)\]/g)].map(m => +m[1]);  // M3.3 ask: the answer already says where [n] goes
  if (ns.length && ns.every(n => n >= 1 && n <= eids.length))
    return text.split(/\[(\d+)\]/).map((x, i) => i % 2 ? cite(eids[x - 1], +x) : rich(x));
  const left = new Set(eids);
  const out = text.split(/(?<=[.?!])\s+/).map(sen => {
    const here = eids.filter(e => left.has(e) && sen.includes(M.anchors[e].exact));
    here.forEach(e => left.delete(e));
    return [rich(sen), here.map(cite), " "];
  });
  return [out, [...left].map(cite)];
}

// ---- sidebar + header ------------------------------------------------------------------------------------
// ⑭ the task list: a name the user gave it (else its goal), a search over names, goals and source titles, and the tasks
// put away (보관) folded at the bottom; nothing is deleted
const nameOf = t => (t && (t.name || t.text)) || "";
let taskQuery = "";
function sidebar() {
  const side = $("side"), had = document.activeElement && document.activeElement.id === "task-search";
  side.textContent = "";
  const q = h("input", { id: "task-search", type: "search", placeholder: "작업·자료 찾기", value: taskQuery, "aria-label": "작업 찾기" });
  q.addEventListener("input", () => { taskQuery = q.value; list(); });
  const box = h("div", { id: "task-list" });
  // A2: the brand mark is CSS (.brand b::before, an ink square with "P"); 새 작업 is the one filled button
  side.append(h("div", { class: "brand" }, h("b", null, "Pablo"),
      h("button", { class: "new", id: "new", disabled: !(window.pabloHost && pabloHost.newTask), on: () => newTask() }, ico("plus", 14), "새 작업")),
    ...[M.tasks.length > 1 ? h("div", { class: "searchbox" }, ico("search", 14), q) : null, box].filter(Boolean));  // append(null) prints "null"
  const row = t => h("button", { class: "t" + (V && t.id === V.task.id ? " on" : ""), title: t.name ? t.text : t.id, "data-task": t.id,
    on: () => { select(t.id); document.body.classList.remove("side"); } }, nameOf(t),
    h("small", null, M.desk ? `${KIND[deskKind(t.id)]} · ${time(t.at)}` : time(t.at)));
  function list() {
    const words = taskQuery.trim().toLowerCase().split(/\s+/).filter(Boolean), d = M.desk || {};
    const hit = t => !words.length || words.every(w => [t.name, t.text, t.id, ...((d[t.id] || {}).papers || []).map(p => p.title)]
      .some(x => String(x || "").toLowerCase().includes(w)));
    const ts = [...M.tasks].reverse().filter(hit), kept = ts.filter(t => !(d[t.id] || {}).archived && !(d[t.id] || {}).done), away = ts.filter(t => (d[t.id] || {}).archived);
    const done = ts.filter(t => (d[t.id] || {}).done && !(d[t.id] || {}).archived);  // P7: finished tasks fold into 완료
    box.replaceChildren(...[h("h4", null, words.length ? `찾은 작업 ${ts.length}개` : "작업"), ...kept.map(row),
      done.length ? h("details", { class: "done", "data-done": String(done.length), open: words.length ? true : null },
        h("summary", null, ico("chevron-right", 12), "완료 ", h("span", { class: "cnt" }, done.length)), ...done.map(row)) : null,
      away.length ? h("details", { class: "away", "data-archived": String(away.length), open: words.length ? true : null },
        h("summary", null, ico("chevron-right", 12), "보관한 작업 ", h("span", { class: "cnt" }, away.length)), ...away.map(row)) : null,
      words.length && !ts.length ? h("p", { class: "muted", style: "padding:0 8px;font-size:13px" }, "맞는 작업이 없습니다.") : null].filter(Boolean));
  }
  list();
  if (had) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
}
function header() {
  const chips = $("chips");  // P2: the state chip + source card (tools() makes it); kept across a header redraw
  $("bar").textContent = ""; ptabs();
  $("bar").append(h("button", { id: "menu", title: "작업 목록", "aria-label": "작업 목록", on: () => document.body.classList.toggle("side") }, ico("panel-left")));
  if (!V) return $("bar").append(h("h1", null, "Pablo"));
  // ⑭ the task's own name (✎) and 보관 / 보관 풀기, beside it
  const t = M.tasks.find(x => x.id === V.task.id) || V.task, d = (M.desk || {})[V.task.id] || {};
  const name = h("h1", { title: t.name ? `목표: ${V.task.text}` : V.task.id, "data-task-name": "1" }, nameOf(t));
  const edit = window.pabloHost && pabloHost.renameTask ? h("button", { class: "rn", "data-rename-task": V.task.id, title: "작업 이름 바꾸기 (목표 문장은 그대로)", on: () => {
    const inp = h("input", { class: "rn-in", id: "task-name", value: nameOf(t) }), note = h("small", { class: "muted" });
    const ok = () => pabloHost.renameTask(V.task.id, inp.value.trim() === V.task.text ? "" : inp.value.trim()).then(() => refresh(), e => { note.textContent = " " + fail(e); });
    inp.addEventListener("keydown", e => { if (e.key === "Enter" && !e.isComposing) ok(); if (e.key === "Escape") { e.stopPropagation(); header(); } });
    name.replaceChildren(inp, " ", h("button", { class: "link", "data-rename-task-ok": "1", on: ok }, "저장"), note); inp.select(); },
    "aria-label": "작업 이름 바꾸기" }, ico("pencil", 14)) : null;
  const away = window.pabloHost && pabloHost.archiveTask ? h("button", { class: "link quiet", "data-archive": d.archived ? "off" : "on",
    title: d.archived ? "작업 목록으로 되돌립니다" : "작업 목록 아래 '보관한 작업'으로 옮깁니다. 기록은 그대로 남습니다.",
    on: () => pabloHost.archiveTask(V.task.id, !d.archived).then(() => refresh()) }, d.archived ? "보관 풀기" : "보관") : null;
  const unDone = d.done && window.pabloHost && pabloHost.setUi ? h("button", { class: "link quiet", "data-done": "off",
    title: "작업 목록으로 되돌립니다", on: () => pabloHost.setUi(V.task.id, "done", false).then(() => refresh()) }, "완료 풀기") : null;
  // A2: the task's kind as a small tag beside its name; a spacer puts 보관 and the state chip on the right
  const kindTag = M.desk ? h("span", { class: "kindtag", "data-kind-tag": deskKind(V.task.id) }, KIND[deskKind(V.task.id)]) : null;
  $("bar").append(...[name, edit, kindTag, h("span", { class: "grow" }), away, unDone, chips].filter(Boolean));  // 기준 · 계획 · 왜? are the right column's tabs (ptabs)
}
// P7: the task's kind decides its stages; one stored at creation wins, else what its material says
const KIND = { repro: "논문 재현", read: "논문 읽기", general: "일반" };
function deskKind(id) { const d = (M.desk || {})[id] || {}, ps = d.papers || [];
  return d.kind || (d.folder && ps.length ? "repro" : ps.length ? "read" : "general"); }
// P7: the right column is remembered per task (open or rail, and the tab); a task switch's own close() is not a choice
let panelSaved = {}, panelQuiet = false;
function rememberPanel() {
  if (!V || panelQuiet || !window.pabloHost || !pabloHost.setUi) return;
  const open = document.body.classList.contains("panel"), m = open && hi >= 0 ? hist[hi].mode : null;
  const was = ((M.desk || {})[V.task.id] || {}).panel || {};
  const v = { open, tab: !m ? (was.tab || "intent") : ["source", "code", "paper", "matrix"].includes(m) ? "evidence" : m }, k = JSON.stringify(v);
  if (panelSaved[V.task.id] === k) return; panelSaved[V.task.id] = k;
  pabloHost.setUi(V.task.id, "panel", v).catch(() => {});
  // the page's copy too: select() reads M.desk when the task is opened again before the next state read (QA 10/26, D4)
  if (M.desk) M.desk[V.task.id] = { ...(M.desk[V.task.id] || {}), panel: v };
}
function evidenceFor() { const d = (M.desk || {})[V.task.id] || {}, pp = (d.papers || []).find(p => p.primary && p.kind !== "web");
  return lastEv || (pp && (M.papers || {})[pp.id] ? { mode: "paper", src: pp.id } : null); }
// P3: the right column's tabs, always there: 기준 · 계획 · 왜? · 근거 with a one-line summary each; with the panel
// closed they stay as a rail
function ptabs() {
  const nav = $("ptabs"); if (!nav) return; nav.textContent = "";
  document.body.classList.toggle("rail", !!V);
  if (!V) return;
  const mode = hi >= 0 && document.body.classList.contains("panel") ? hist[hi].mode : null;
  const EV = ["source", "code", "paper", "matrix"], on = EV.includes(mode) ? "evidence" : mode;
  const I = V.intent, P = V.plan, done = P ? P.steps.filter(s => stepState(s)[0] === "done").length : 0;
  const cited = new Set(Object.values(V.checks).flatMap(c => c.evidence || [])).size;
  const waiting = V.actions.some(a => a.verdict === "WARN" && !a.decision);
  const d = (M.desk || {})[V.task.id] || {}, pp = (d.papers || []).find(p => p.primary && p.kind !== "web");
  const ev = lastEv || (pp && (M.papers || {})[pp.id] ? { mode: "paper", src: pp.id } : null);
  const tabs = [["intent", "기준", `반드시 ${I.must.length} · 가능 ${I.prefer.length}`, String(I.must.length + I.prefer.length), () => toggle({ mode: "intent" })],
    ["plan", "계획", P ? `${done} / ${P.steps.length} 단계` : "없음", P ? `${done}/${P.steps.length}` : "—", P ? () => toggle({ mode: "plan" }) : null],
    ["trace", "왜?", waiting ? "확인 기다림" : `판정 ${V.actions.length}`, waiting ? "!" : String(V.actions.length), () => toggle({ mode: "trace" })],
    ["evidence", "근거", `인용 ${cited}`, String(cited), ev ? () => (on === "evidence" ? close() : show(ev)) : null]];
  nav.append(...tabs.map(([k, label, long, short, go]) => h("button", { class: "ptab" + (on === k ? " on" : ""), "data-tab": k, disabled: !go,
    title: long, on: go }, h("b", null, label), h("small", { class: "long" }, long), h("small", { class: "short" }, short))));
}

// ---- conversation: built from the stored research / plan / guard / review records --------------------------
const msg = (who, at, ...kids) => h("div", { class: "msg " + (who === "Pablo" ? "pablo" : "user") },
  h("div", { class: "av" }, who === "Pablo" ? "P" : "나"), h("div", null, h("div", { class: "who" }, who, h("small", null, time(at))), kids));
// Normal progress is one Pablo answer; only research issues, WARN/BLOCK and open decisions get their own message.
const SURE = { PARTIALLY_VERIFIED: "일부만 확인했습니다.", NOT_FOUND: "공식 근거를 찾지 못해 추정했습니다.",
               CONFLICTING: "출처끼리 내용이 다릅니다." };
function answer(asked) {
  const out = [];
  for (const id of V.research) {
    const c = V.checks[id];
    if (c.state === "waived" || c.spec || c.matrix || asked.has(id) || live().querySelector(`.asked[data-check="${CSS.escape(id)}"]`)) continue;  // shown as its question's answer / in the conditions card / in its table
    const note = c.state === "pending" ? "아직 조사 중입니다." : SURE[c.outcome];
    out.push(h("p", { title: c.id, "data-id": c.id }, cited(c.conclusion || c.title, c.evidence),
               note ? h("span", { class: "muted" }, " · " + note) : null));
  }
  return out;  // M5.0: plan, ALLOW actions and their runs are lifecycle -> Plan / 왜? panels only
}
// an ALLOW action whose run failed: the one ALLOW outcome the conversation shows
const failed = a => a.verdict === "ALLOW" && a.runs.some(r => r.alignment === "failed") && h("div", { class: "call block", title: a.id, "data-id": a.id },
  h("p", { class: "head" }, "⚠ 작업을 실행하지 못했습니다."), h("p", null, "제안된 작업: ", h("b", null, meaning(a.text))),
  runs(a).map(x => h("p", { class: "muted" }, x)), tech(a.text),
  h("p", null, h("button", { class: "link", on: () => show({ mode: "trace", act: a.id }) }, "왜 그런가요?")));
const done = r => meaning(r.summary.replace(/^실행하지 않음: /, ""));
const runs = a => a.runs.map(r => (r.executed ? "실행 결과: " : "") + done(r) + (r.alignment ? ` · ${ALIGN[r.alignment] || r.alignment}` : ""));
// a BLOCK is Pablo's own decision (its card says so); a reason that only repeats who decided is not shown again
const decided = a => a.decision && a.verdict !== "BLOCK"
  ? (DECIDE[a.decision] || a.decision) + (a.decision_reason && !/^(사용자가|Guard )/.test(a.decision_reason) ? ` · ${a.decision_reason}` : "") : null;
function issues() {
  return V.research.flatMap(id => V.checks[id].issues.map(i => { const c = V.checks[id];
    return h("div", { class: "call", title: i.id, "data-id": i.id }, art("surprised", "pose"),
      h("p", { class: "head" }, "⚠ " + (ISSUE[i.type] || ISSUE.other)), h("p", null, rich(i.note), c.evidence.map(cite)),
      c.evidence.length ? h("p", null, "Pablo는 공식 원문을 기준으로 판단했습니다.") : null); }));
}
function action(a) {
  const block = a.verdict === "BLOCK", ev = a.criteria.flatMap(c => V.checks[c.id] ? V.checks[c.id].evidence : []);
  const d = decided(a);
  return h("div", { class: "call" + (block ? " block lock" : ""), title: a.id, "data-id": a.id },
    h("p", { class: "head" }, block ? "⚠ 이 작업은 현재 기준과 충돌합니다." : "⚠ 이 작업은 확인이 필요합니다."),
    h("p", null, "제안된 작업: ", h("b", null, meaning(a.text))), preview(a.text), current(a.text, V.task.id),
    a.why ? h("p", { class: "muted" }, `제시한 이유: "${a.why}"`) : null,
    a.problems.length ? [reason(a.problems[0], block), [...new Set(ev)].map(cite)] : null,
    a.criteria.length ? h("p", { class: "muted" }, "관련 기준: ", a.criteria.map(c => c.text).join(" · ")) : null, offer(a),
    d ? h("p", { class: "muted" }, d) : null, runs(a).map(x => h("p", { class: "muted" }, x)),
    tech(a.text, ...a.problems.filter(x => !korean(x))),
    h("p", null, block ? (runs(a).length ? null : h("b", { "data-blocked": "1" }, "Pablo가 막아 실행하지 않았습니다. ")) : !d ? h("b", null, "진행할지 결정이 필요합니다. ") : null,
      h("button", { class: "link", on: () => show({ mode: "trace", act: a.id }) }, "왜 그런가요?")));
}
// the desktop's chat log (chat.json): what the user said, the agent's replies, PDF questions and the check that answered
const ASKFAIL = "답을 찾지 못했습니다.";
// D4: what one agent turn changed in the work folder (a checkpoint before it, one after); 변경 보기 / 되돌리기 on the desktop
const CHANGE = { A: "새 파일", M: "수정", D: "삭제" };
const fail = e => String(e.message || e).replace(/^Error invoking remote method '[^']*': (\w*Error: )?/, "");
// A3 (desktop): a path in the task's work folder opens the code panel (read-only); the static page shows it as it is
const fileLink = (label, task, at, line, note, expect) => window.pabloHost && pabloHost.readFile
  ? h("button", { class: "file", "data-file": at, title: "코드 보기", on: () => show({ mode: "code", task, where: at, line, note, expect }) }, label) : label;
// a WARN / BLOCK card's files as they are now (a new file is not there yet; a command names none Pablo can trust)
function current(text, task) {
  const ps = [...new Set([...(text || "").split("\n")[0].matchAll(/(?:파일 삭제|파일 수정|파일 변경): ([^,]+)/g)].map(m => m[1].trim()))];
  return ps.length && window.pabloHost && pabloHost.readFile
    ? h("p", { class: "muted" }, "📄 지금 파일 보기: ", ps.map((p, i) => [i ? " · " : "", fileLink(h("code", null, p), task, p)])) : null;
}
function changed(c, task) {
  const list = [c.files.slice(0, 8).map((f, i) => [i ? ", " : "", f.status === "D" ? f.path : fileLink(f.path, task, f.path),
    ` (${CHANGE[f.status] || f.status})`]), c.files.length > 8 ? ` 외 ${c.files.length - 8}개` : ""];
  const box = h("div", { class: "changes", "data-to": c.to }, h("p", null, `📝 파일 ${c.files.length}개가 바뀌었습니다: `, list));
  if (!window.pabloHost || !pabloHost.undo) return box;
  const v = M.views[task], undone = v && (v.chat || []).some(x => x.role === "undo" && x.of === c.to), row = h("p", null);
  let open = null;
  const look = h("button", { class: "link", "data-look": "1", on: () => {
    if (open) { open.remove(); open = null; return; }
    pabloHost.diff(task, c.from, c.to).then(t => { open = preview("", t) || h("p", { class: "muted" }, "표시할 내용이 없습니다."); row.after(open); },
      e => row.after(h("p", { class: "muted" }, fail(e)))); } }, "변경 보기");
  const back = undone ? h("span", { class: "muted", "data-undone": "1" }, "되돌렸습니다.")
    : h("button", { class: "link", "data-undo": "1", on: () => pabloHost.undo(task, c.from, c.to).then(() => {
        back.replaceWith(h("span", { class: "muted", "data-undone": "1" }, "되돌렸습니다. 다음 요청 때 에이전트에게도 알립니다.")); refresh(); },
        e => row.after(h("p", { class: "muted", "data-undo-error": "1" }, fail(e)))) }, "되돌리기");
  row.append(look, " · ", back);
  box.append(row);
  return box;
}
// A2: a paper's reproduction conditions (PabloSkill.spec), by category, each with its page [n]; what the paper leaves open
const SPEC = { dataset: "데이터셋", split: "데이터 분할", preprocessing: "전처리", model: "모델", method: "방법",
               hyperparameter: "하이퍼파라미터", training: "학습", metric: "평가 지표", baseline: "비교 대상", result: "보고된 결과",
               protocol: "평가 규칙" };
const fact = c => [rich((c.conclusion || c.title).replace(/\s*\[\d+\]/g, "")), c.evidence.length ? " " : null, c.evidence.map(e => cite(e))];  // [n] numbered in this chat
const ASIDE = { fact: "논문의 서술 (코드가 정하지 않음)", scope: "실험 범위 (이 재현 밖일 수 있는 실험)" };  // ⑥ not checked
// 0.8 review: a re-extraction of the same paper says what changed; what the last one had and this one did not find comes
// back with 되살리기 (extractions differ from run to run); what the user made of the conditions was kept
function redone(d) {
  const gone = (d.gone || []).map(id => V.checks[id]).filter(k => k && k.state === "waived" && k.waived_by === "pablo");
  const can = window.pabloHost && pabloHost.condition, task = V.task.id;
  const back = k => { const at = h("span");
    return [at, h("button", { class: "link", "data-redo-restore": k.id, on: () => pabloHost.condition(task, "restore", { id: k.id }).then(() => {
      echo(task, { role: "spec-restore", check: k.id }); return refresh(); }, e => at.replaceChildren(h("span", { class: "muted" }, fail(e) + " "))) }, "되살리기")]; };
  return h("div", { class: "muted", "data-redo": "1" },
    h("p", null, `다시 뽑았습니다: 이전 ${d.before}개 중 ${d.same}개는 이번에도 나왔고, 새로 생긴 것 ${(d.new || []).length}개, 이번에 빠진 것 ${(d.gone || []).length}개입니다.`,
      (d.kept || []).length ? ` 직접 더하거나 되살리거나 의도한 차이로 둔 조건 ${d.kept.length}개는 그대로 두었습니다.` : "",
      (d.out || []).length ? ` 이전에 뺀 조건 ${d.out.length}개는 다시 넣지 않았습니다.` : ""),
    gone.length ? h("details", { "data-gone": String(gone.length) }, h("summary", null, `이번에 빠진 조건 ${gone.length}개`),
      h("ul", null, gone.map(k => h("li", { "data-id": k.id }, h("span", null, (SPEC[k.spec.category] || k.spec.category) + " · "), fact(k), can ? [" · ", back(k)] : null)))) : null);
}
function conditions(ids, dropped, diff) {
  const cs = ids.map(id => V.checks[id]).filter(c => c && c.state !== "waived"), all = cs.filter(c => !c.spec.missing);
  const stated = all.filter(c => !ASIDE[c.spec.kind]);
  const open = cs.filter(c => c.spec.missing);
  const box = h("div", { class: "spec", "data-spec": "1" });
  if (!cs.length) return box.appendChild(h("p", { class: "muted" }, "이 조건 목록은 다시 뽑은 목록으로 바뀌었습니다.")), box;
  const paper = (cs.find(c => c.paper) || {}).paper;  // C1: which of the task's papers they are from
  box.append(h("p", { class: "head" }, `📋 ${paper ? paper + "에서" : "논문에서"} 재현 조건 ${stated.length}개를 찾았습니다.`));
  if (diff && !diff.first) box.append(redone(diff));
  for (const k of Object.keys(SPEC)) {
    const xs = stated.filter(c => c.spec.category === k);
    if (xs.length) box.append(h("h4", null, SPEC[k]), h("ul", null, xs.map(c => h("li", { title: c.id, "data-id": c.id },
      fact(c), c.spec.value_in_quote === false ? h("span", { class: "chk warn", "data-vq": "1", title: "모델이 읽은 값이 고정한 인용 문장 안에 없습니다. 원문에서 직접 확인하세요." },
        ` ⚠ 값(${c.spec.value})이 인용 안에 없음`) : null,
      c.spec.header_missing ? h("span", { class: "chk warn", "data-hm": "1", title: "PDF 글자에는 표의 머리가 따로 떨어져 있어, 어느 숫자가 어느 데이터셋·지표인지는 모델의 추측입니다." },
        " ⚠ 인용에 표의 열 이름이 없습니다. 숫자와 데이터셋 짝을 원문 표에서 확인하세요") : null,
      devOf(c) ? h("span", { class: "chk dev", "data-dev": c.id }, ` ◇ 의도한 차이(${WHERE_DEV[scopeOf(devOf(c))]}): ${devOf(c).why}`) : null))));
  }
  for (const [k, label] of Object.entries(ASIDE)) { const xs = all.filter(c => c.spec.kind === k);
    if (xs.length) box.append(h("details", { "data-aside": k }, h("summary", null, `${label} ${xs.length}개 · 재현 점검에서 대조하지 않음`),
      h("ul", null, xs.map(c => h("li", { title: c.id, "data-id": c.id }, h("span", { class: "muted" }, (SPEC[c.spec.category] || c.spec.category) + " · "), fact(c))))));
  }
  const own = codeOf((cs.find(c => c.spec.source_id) || { spec: {} }).spec.source_id).find(x => x.official);  // ⑪
  if (open.length) box.append(h("h4", null, "논문에 없는 설정"), h("ul", { class: "open" }, open.map(c => h("li", { title: c.id }, rich(c.title)))),
    h("p", { class: "muted" }, "정할 때는 무엇을 근거로 정했는지 남기세요. 에이전트에게도 그렇게 알립니다.",
      own ? [" 논문의 공식 코드(", h("a", { href: own.url, target: "_blank", rel: "noopener noreferrer", "data-code-hint": "1" }, short_(own.url) + " ↗"), ")에서 먼저 찾아보세요."] : null));
  if (dropped) box.append(h("p", { class: "muted" }, `원문에서 위치를 찾지 못한 조건 ${dropped}개는 뺐습니다.`));
  box.append(h("p", { class: "muted" }, "에이전트는 이 조건을 알고 작업하고, 바꾸려 하면 Pablo가 근거와 함께 막습니다."));
  return box;
}
// A5/A6 재현 점검: each paper condition / open setting / task criterion against the work folder (code line or log value)
const AUDIT = { differs: ["✗", "다름"], pairing: ["?", "열 짝 확인 필요"], chosen: ["•", "코드가 정함"], intended: ["◇", "의도한 차이"], missing: ["○", "아직 없음"],
                unclear: ["?", "판단 못 함"], followed: ["✓", "따름"] };
// ⑦ the user's intended deviation from a paper condition: the one holding now, or the one that held at a time (an audit's)
const WHERE_DEV = { runs: "별도 실행에서만", task: "작업 전체" }, scopeOf = d => (d && d.scope) || "task";  // a span before 10/14: task
function devOf(k, at) {
  const ds = ((k || {}).spec || {}).deviations || [];
  if (at === undefined) { const d = ds.at(-1); return d && !d.to ? d : null; }
  const t = Date.parse(at);
  return ds.find(d => Date.parse(d.from) < t && (!d.to || Date.parse(d.to) > t)) || null;
}
// A2: what Pablo saw at the file:line the model named (main.js -> desktop/where.js verify); nothing for unchecked / 0.7 answers
// ⑤ via: the model named a line that reads the setting (cfg["retrieval"]["top_k"]); Pablo found the config line that sets
// it (desktop/where.js follow). Its value agrees with the verdict: the value check's warning was about the reading line.
const WARNED = new Set(["not_found", "no_file", "value_mismatch"]), eased = x => x.check === "value_mismatch" && !!x.via && x.via.agrees === true;
const warned = x => (WARNED.has(x.check) && !eased(x)) || (!!x.via && x.via.agrees === false) || (x.status === "missing" && !!x.seen);
const LOGISH = /\.(log|txt|out|csv|tsv|jsonl?|md)(:|$)|(^|\/)logs?\//i;  // ⑤ a run log or a data file is not code
function mark(x) {
  const v = ((V.checks[x.id] || {}).spec || {}).value;
  if (eased(x)) return h("span", { class: "chk verified", "data-check": "via" }, "✓ 값은 설정 파일에서 확인");
  const t = { verified: `✓ Pablo가 ${LOGISH.test(String(x.where || "").replace(/\\/g, "/")) ? "파일" : "코드"}에서 확인`, moved: `위치 보정: ${x.line_found}줄`, not_found: "⚠ 모델이 댄 위치에서 찾지 못함",
    no_file: "⚠ 모델이 댄 위치에서 찾지 못함",
    value_mismatch: `⚠ 논문 값(${v})이 이 자리에 ${x.status === "followed" ? "없음" : "그대로 있음"}` }[x.check];
  return t ? h("span", { class: "chk " + (warned(x) ? "warn" : x.check), "data-check": x.check }, t) : null;
}
function audited(c) {
  const box = h("div", { class: "audit", "data-audit": "1" });
  if (c.error || c.status === "interrupted" || c.unreadable || !(c.items || []).length) {
    box.append(h("p", { class: "head" }, "🔎 재현 점검을 마치지 못했습니다."), h("p", { class: "muted" },
      c.status === "interrupted" ? "중지했습니다." : c.error || (c.unreadable ? "에이전트의 답을 읽지 못했습니다." : "판정된 항목이 없습니다.")));
    return box;
  }
  // e2e3 (c86a409): a value read from a table row without its column names: the agent's 따름 / 다름 rests on which number
  // it took for this condition, so it is not counted as a verdict (열 짝 확인 필요, open); chat.json keeps the agent's status
  const unpaired = x => !!((V.checks[x.id] || {}).spec || {}).header_missing && (x.status === "followed" || x.status === "differs");
  const dev = x => devOf(V.checks[x.id], c.at), st = x => x.status === "differs" && dev(x) && scopeOf(dev(x)) === "task" ? "intended"
    : unpaired(x) ? "pairing" : x.status;
  const n = k => c.items.filter(x => st(x) === k).length, task = c.task || V.task.id, out = c.outside || [];
  box.append(h("p", { class: "head" }, "🔎 재현 점검: ", [...Object.keys(AUDIT).filter(n).map(k => `${AUDIT[k][1]} ${n(k)}`),
    ...(out.length ? [`조건 밖 ${out.length}`] : [])].join(" · ")));
  box._c = c; aged(box);  // ⑤ files changed after it: said at the top (again after every refresh)
  if (c.shell === "powershell") box.append(h("p", { class: "ps51", "data-shell": "5.1" }, "⚠ 이 점검은 Windows PowerShell 5.1에서 했습니다. "
    + "에이전트가 한글 주석이나 λ 같은 기호를 깨진 채 읽었다면 그 줄의 판정이 틀릴 수 있습니다. PowerShell 7을 설치하면 정확히 읽습니다."));
  if (c.summary) box.append(h("p", null, rich(c.summary)));
  // ④ criteria the user removed before this audit ran were not checked: said here, with why, never left out silently
  const t = Date.parse(c.at), during = x => Date.parse(x.from) < t && (!x.to || Date.parse(x.to) > t);
  const skipped = (V.intent.removed || []).filter(during);
  if (skipped.length) box.append(h("p", { class: "muted", "data-skipped": String(skipped.length) }, `이 점검 전에 지운 기준 ${skipped.length}개는 대조하지 않았습니다: `,
    skipped.map((x, i) => [i ? " · " : "", x.text, x.why ? ` (이유: ${x.why})` : " (이유를 적지 않음)"])));
  // ⑩ and the paper conditions the user took out before it ran (each with its why)
  const outs = V.research.map(id => V.checks[id]).flatMap(k => ((k.spec || {}).dropped || []).filter(during).map(x => [k, x]));
  if (outs.length) box.append(h("p", { class: "muted", "data-skipped-spec": String(outs.length) }, `이 점검 전에 뺀 재현 조건 ${outs.length}개는 대조하지 않았습니다: `,
    outs.map(([k, x], i) => [i ? " · " : "", (k.conclusion || k.title).replace(/\s*\[\d+\]/g, ""), ` (이유: ${x.why})`])));
  const placed = c.items.filter(x => x.check && x.check !== "unchecked"), lost = placed.filter(x => x.check === "not_found" || x.check === "no_file").length;
  const off = placed.filter(x => (x.check === "value_mismatch" && !eased(x)) || (x.via && x.via.agrees === false)).length;
  if (placed.length) box.append(h("p", { class: "muted", "data-checked": "1" },
    `📍 모델이 댄 위치 ${placed.length}곳 중 ${placed.length - lost}곳을 Pablo가 파일에서 직접 확인했습니다.`,
    lost ? ` ${lost}곳은 그 자리에서 찾지 못했습니다.` : "", off ? ` ${off}곳은 판정과 논문 값이 어긋납니다.` : "",
    lost || off ? " 이 항목은 위에 따로 둡니다." : ""));
  const what = x => { const k = V.checks[x.id];  // ⑤ [5쪽]: a page in the table, not the chat's running number (rows are sorted)
    if (k) return [h("span", { class: "muted" }, (k.spec && k.spec.missing ? "논문에 없는 설정" : SPEC[(k.spec || {}).category] || "근거") + " · "),
      rich((k.conclusion || k.title).replace(/\s*\[\d+\]/g, "")), " ", k.evidence.map(e => cite(e, (M.anchors[e] || {}).page ? `${M.anchors[e].page}쪽` : undefined)),
      (k.spec || {}).header_missing && st(x) !== "pairing" ? h("span", { class: "chk warn", "data-hm": "1" }, " ⚠ 논문 값의 열 짝 확인 필요") : null];
    const i = [...V.intent.must, ...V.intent.prefer].find(y => y.id === x.id);
    return [h("span", { class: "muted" }, "작업 기준 · "), i ? i.text : x.id]; };
  const moved = x => x.check === "moved" ? `모델이 댄 위치(${x.where})에는 없고 ${x.line_found}줄에 있습니다.` : null;
  // the paper's row (where the number was read) and the agent's own verdict, beside the place it named: the user compares
  const paired = x => { const a = (V.checks[x.id].evidence || []).map(e => M.anchors[e]).find(Boolean), src = a && M.sources[a.source];
    return h("div", { class: "pair", "data-pairing": x.status },
      a ? h("div", null, `논문 표 행 (${[src && src.title, a.page && "p." + a.page].filter(Boolean).join(" ")}): `, h("span", null, `“${a.exact}”`)) : null,
      h("div", { class: "muted" }, `판단 못 함: 열 이름이 PDF 글자에서 떨어져 있어, 어느 숫자가 이 조건의 값인지 확인되지 않았습니다. `
        + `에이전트 판정(${AUDIT[x.status].join(" ")})은 그 짝을 믿은 것입니다. 표에서 열을 확인하고 아래 자리의 값과 대조하세요.`)); };
  const seen = x => x.check === "verified" || x.check === "moved" ? x.found : null;  // ⑤ the code panel says if it is still there
  const via = x => { const s = x.via, v = ((V.checks[x.id] || {}).spec || {}).value;
    return s ? h("div", { class: "at via", "data-via": s.where }, "↳ 값을 정하는 곳: ", fileLink(h("code", null, s.where), task, s.where, null, null, s.found), " ",
      h("span", null, s.found), s.agrees === false ? h("span", { class: "chk warn", "data-via-warn": "1" }, ` ⚠ 논문 값(${v})이 여기에 ${x.status === "followed" ? "없음" : "그대로 있음"}`) : null) : null; };
  const row = x => h("li", { class: "st-" + st(x), title: x.id, "data-id": x.id }, h("b", null, (AUDIT[st(x)] || ["", x.status]).join(" ")), " ", what(x),
    st(x) === "pairing" ? paired(x) : null,
    dev(x) ? h("div", { class: "muted", "data-dev-why": x.id }, st(x) === "intended" ? `이유: ${dev(x).why}`
      : x.status === "differs" ? `의도한 차이는 별도 실행에서만 두기로 했는데(이유: ${dev(x).why}), 기본 실행이 논문과 다릅니다.`
      : `의도한 차이로 두었지만(이유: ${dev(x).why}) 이 점검에서는 다르지 않았습니다.`) : null,
    x.where || x.found || mark(x) ? h("div", { class: "at" }, x.where ? fileLink(h("code", null, x.where), task, x.where, x.line_found, moved(x), seen(x)) : null,
      x.found ? [" ", h("span", null, x.found)] : null, mark(x)) : null, via(x),
    x.status === "missing" && x.seen ? h("div", { class: "at seen", "data-seen": x.seen.where }, h("span", { class: "chk warn" }, "⚠ 모델은 아직 없다고 했지만 Pablo가 찾았습니다: "),
      fileLink(h("code", null, x.seen.where), task, x.seen.where, null, null, x.seen.found), " ", h("span", null, x.seen.found)) : null,
    x.note ? h("div", { class: "muted" }, x.note) : null);
  const order = Object.keys(AUDIT), xs = [...c.items].sort((a, b) => warned(b) - warned(a) || order.indexOf(st(a)) - order.indexOf(st(b)));
  // what needs attention stays open (Pablo could not confirm it, 다름, 코드가 정함, 의도한 차이, 아직 없음); 판단 못 함 and 따름
  // fold away. ⑥ review + e2e: an 아직 없음 is mostly work left to do once facts left the list by their kind (folding it hid
  // 2 of 17 drifts the audit found), so only a condition from an extraction before kinds folds it, named on its line.
  const folds = x => st(x) === "unclear" || st(x) === "followed"
    || (st(x) === "missing" && !!(V.checks[x.id] || {}).spec && !V.checks[x.id].spec.missing && !V.checks[x.id].spec.kind);
  const fold = { missing: "아직 없는 항목", unclear: "판단 못 한 항목", followed: "따르는 항목" };
  const short = x => { const k = V.checks[x.id] || {}, v = (k.spec || {}).value; const t = v || (k.title || x.id);
    return t.length > 22 ? t.slice(0, 21) + "…" : t; };
  box.append(h("ul", null, xs.filter(x => warned(x) || !folds(x)).map(row)));
  for (const [k, label] of Object.entries(fold)) { const ys = xs.filter(x => st(x) === k && folds(x) && !warned(x));
    if (ys.length) box.append(h("details", null, h("summary", null, `${label} ${ys.length}개`,
      k === "missing" ? `: ${ys.slice(0, 6).map(short).join(", ")}${ys.length > 6 ? " …" : ""}` : ""), h("ul", null, ys.map(row)))); }
  // what no item covers (main.js audited): how the method is done stays open, the paper's experiments the folder does not
  // have fold away. The model wrote them from the code and the items, not from the paper: no page is attached.
  if (out.length) {
    const orow = x => h("li", { class: "st-outside" }, h("b", null, "△"), " ", x.what,
      x.where || x.found || mark(x) ? h("div", { class: "at" }, x.where ? fileLink(h("code", null, x.where), task, x.where, x.line_found, moved(x), seen(x)) : null,
        x.found ? [" ", h("span", null, x.found)] : null, mark(x)) : null);
    const m = out.filter(x => x.kind !== "scope").sort((a, b) => warned(b) - warned(a)), s = out.filter(x => x.kind === "scope");
    box.append(h("div", { class: "outside", "data-outside": "1" }, h("h4", null, `조건 밖에서 본 차이 ${out.length}개`),
      m.length ? h("ul", null, m.map(orow)) : null,
      s.length ? h("details", null, h("summary", null, `논문의 실험 가운데 이 폴더에 없는 것 ${s.length}개`), h("ul", null, s.map(orow))) : null,
      h("p", { class: "muted" }, "재현 조건 목록 밖이라 논문 쪽이 붙지 않습니다. 중요한 차이면 논문에서 확인하고 조건을 다시 뽑아 보세요.")));
  }
  return box;
}
// ⑤ an audit card is a moment: the files its rows name may have changed since (an agent turn, an undo). Said at its top.
let reAudit = null;  // desktop: run 재현 점검 again
// ⑤ review: the desktop also looks at the places Pablo confirmed in this audit, as the files are now (the code panel's rule,
// for the whole card): a change undone since is not old, an edit outside any turn (no change record) is.
function aged(box) {  // (not fresh(): the desktop's add box has its own)
  const c = box._c, task = c.task || V.task.id, v = M.views[task] || V, t = Date.parse(c.at);
  const files = [...new Set((v.chat || []).filter(x => (x.role === "changes" || x.role === "undo") && Date.parse(x.at) > t)
    .flatMap(x => (x.files || []).map(f => typeof f === "string" ? f : f.path)))];
  const again = () => reAudit && V && V.task.id === task ? [" ", h("button", { class: "link", "data-reaudit": "1", on: () => reAudit(task) }, "다시 점검")] : null;
  const put = line => { const old = box.querySelector(":scope > .stale"); if (old) old.replaceWith(line || ""); else if (line) box.querySelector(".head").after(line); };
  const changed = () => files.length ? h("p", { class: "stale", "data-stale": String(files.length) },
    `⚠ 이 점검 뒤 파일 ${files.length}개가 바뀌었습니다(${files.slice(0, 3).join(", ")}${files.length > 3 ? " 외" : ""}). 판정이 지금 파일과 다를 수 있습니다.`, again()) : null;
  // places, not rows: a condition and a criterion often point at the same line (rehearsal 10/27: "config.yaml:5, config.yaml:5")
  const at = x => x.line_found ? `${where0(x.where)}:${x.line_found}` : x.where, seen = new Set();
  const placed = window.pabloHost && pabloHost.recheck
    ? [...c.items, ...(c.outside || [])].filter(x => ["verified", "moved", "value_mismatch"].includes(x.check) && x.where && x.found)
      .filter(x => !seen.has(at(x)) && seen.add(at(x))) : [];
  if (!placed.length) return put(changed());
  pabloHost.recheck(task, placed.map(x => ({ where: x.where, found: x.found, line: x.line_found || null }))).then(r => {
    const gone = placed.filter((x, i) => r[i] === "not_found" || r[i] === "no_file");
    put(gone.length ? h("p", { class: "stale", "data-stale": String(files.length), "data-gone": String(gone.length) },
        `⚠ 점검 때 Pablo가 확인한 ${placed.length}곳 중 ${gone.length}곳이 지금은 그대로가 아닙니다(${gone.slice(0, 3).map(at).join(", ")}${gone.length > 3 ? " 외" : ""}). 판정이 지금 파일과 다를 수 있습니다.`, again())
      : files.length ? h("p", { class: "stale same muted", "data-same": String(placed.length) },
        `이 점검 뒤 파일 ${files.length}개가 바뀌었지만, 점검 때 Pablo가 확인한 ${placed.length}곳은 지금도 그대로입니다.`, again()) : null);
  }, () => put(changed()));
}
const where0 = w => String(w).split(/[;,]\s/)[0].replace(/(:\d+(?:[-,]\d+)*)+$/, "");  // "config.yaml:2" -> "config.yaml"
// C3 비교표 (chat.json "compare"): the task's papers (rows) by columns. A cell is a value with its place in that paper
// ([n] -> the PDF on that page), or 근거 없음: Pablo did not find where the paper says it, so nothing is filled in.
// ⑪ the code repositories a paper links (its PDF's links), the paper's own first ("Our code is available at …")
const codeOf = id => ((M.papers || {})[id] || {}).code || [];
const short_ = u => u.replace(/^https?:\/\/(www\.)?/, "");
function codeLine(id, task) {
  const cs = codeOf(id), own = cs.find(x => x.official), more = cs.filter(x => !x.official);
  if (!cs.length) return null;
  const at = x => h("button", { class: "link", title: "논문의 그 쪽 열기", on: () => show({ mode: "paper", src: id, page: x.page }) }, `논문 p.${x.page}`);
  return h("p", { class: "muted", "data-code-line": id }, own ? ["📦 공식 코드: ", h("a", { href: own.url, target: "_blank", rel: "noopener noreferrer" }, short_(own.url) + " ↗"), " (", at(own), ")"] : null,
    more.length ? [own ? " · " : "", `논문이 링크한 다른 저장소 ${more.length}개: `, more.map((x, i) => [i ? ", " : "", h("a", { href: x.url, target: "_blank", rel: "noopener noreferrer" }, short_(x.url))])] : null);
}
// ⑧ a paper's name as the user calls it now (✎ renames it everywhere); the table keeps its rows' ids
const titleOf = p => ((M.papers || {})[p.id] || {}).title || p.title;
let compareAgain = null, renameHook = null;  // desktop: the 비교표 form with these columns; ✎
function renamer(id, title, task) {
  if (!window.pabloHost || !pabloHost.renameSource) return null;
  const btn = h("button", { class: "rn", "data-rename": id, title: "이름 바꾸기 (예: HippoRAG 2)", on: () => {
    const inp = h("input", { class: "rn-in", "data-rename-in": id, value: title }), note = h("span", { class: "muted" });
    const ok = () => inp.value.trim() && inp.value.trim() !== title ? pabloHost.renameSource(task, id, inp.value.trim()).then(() => renameHook && renameHook(task),
      e => { note.textContent = " " + fail(e); }) : form.replaceWith(btn);
    inp.addEventListener("keydown", e => { if (e.key === "Enter" && !e.isComposing) ok(); if (e.key === "Escape") { e.stopPropagation(); form.replaceWith(btn); } });
    const form = h("span", null, " ", inp, " ", h("button", { class: "link", "data-rename-ok": id, on: ok }, "저장"), note);
    btn.replaceWith(form); inp.select(); } }, "✎");
  return btn;
}
// ⑧ the datasets every paper of the table names (its 데이터셋 column): "2Wiki" and "2WikiMultiHopQA" are one
function common(c, cell) {
  const col = c.columns.find(x => /데이터셋|dataset/i.test(x));
  if (!col || c.papers.length < 2) return [];
  const sets = c.papers.map(p => { const k = cell(p, col);
    return k ? k.conclusion.replace(/\s*\[\d+\]/g, "").replace(/\([^)]*\)/g, "").split(/[,，、;/]|\s+(?:및|and|와|과)\s+/).map(x => x.trim()).filter(x => x.length > 1) : []; });
  const key = x => x.toLowerCase().replace(/[^a-z0-9가-힣]/g, ""), same = (a, b) => a === b || (Math.min(a.length, b.length) >= 4 && (a.startsWith(b) || b.startsWith(a)));
  return sets[0].filter(x => sets.slice(1).every(s => s.some(y => same(key(x), key(y)))) && key(x));
}
function matrix(c, wide) {
  const box = h("div", { class: "matrix" + (wide ? " wide" : ""), "data-matrix": c.matrix || "" });
  const cells = (c.cells || []).map(id => V.checks[id]).filter(Boolean), all = c.papers.length * c.columns.length;
  const cell = (p, col) => cells.find(k => k.matrix && k.matrix.source_id === p.id && k.matrix.column === col);
  // ⑧ what each number measures: one column with two different metrics is not a comparison, said on the column
  const norm = m => String(m || "").toLowerCase().replace(/[^a-z0-9@]/g, "");
  const mixed = col => new Set(c.papers.map(p => norm(((cell(p, col) || {}).matrix || {}).metric)).filter(Boolean)).size > 1;
  const why = (p, col) => { const x = (c.empty || []).find(y => y.source === p.id && y.column === col);
    return x && x.value ? `모델은 "${x.value}"라고 했지만 논문에서 그 문장을 찾지 못해 비웠습니다.` : "이 논문에서 찾지 못했습니다."; };
  if (!wide) box.append(h("p", { class: "head" }, `📊 비교표: 논문 ${c.papers.length}편 × 항목 ${c.columns.length}개`),
    h("p", { class: "muted" }, `칸 ${all}개 중 ${cells.length}개는 논문에서 위치를 찾은 값입니다.`,
      cells.length < all ? ` 나머지 ${all - cells.length}개는 근거를 찾지 못해 비웠습니다.` : ""));
  box.append(h("div", { class: "scroll" }, h("table", null,
    h("thead", null, h("tr", null, h("th", null, "논문"), c.columns.map(col => h("th", null, col,
      mixed(col) ? h("small", { class: "differ", "data-mixed": "1", title: "이 열의 숫자는 논문마다 다른 지표입니다. 그대로 비교하지 마세요." }, " ⚠ 지표 다름") : null)))),
    h("tbody", null, c.papers.map(p => h("tr", { "data-paper": p.id }, h("th", { scope: "row" }, titleOf(p), p.version ? h("small", null, " " + p.version) : null,
        renamer(p.id, titleOf(p), c.task || V.task.id)),
      c.columns.map(col => { const k = cell(p, col), m = k && k.matrix.metric;
        return k ? h("td", { "data-cell": k.id }, rich(k.conclusion.replace(/\s*\[\d+\]/g, "")), " ", k.evidence.map(e => cite(e)),
            m ? h("span", { class: "metric" + (mixed(col) ? " differ" : ""), "data-metric": m }, m) : null)
          : h("td", { class: "none", title: why(p, col) }, "근거 없음"); })))))));
  // ⑧ the datasets all the papers name: their results side by side is the comparison a reader wants
  const both = common(c, cell).filter(x => !c.columns.some(col => col.includes(x))).slice(0, 3);
  if (!wide && both.length && compareAgain) box.append(h("p", { class: "muted common", "data-common": both.join("|") },
    `${c.papers.length === 2 ? "두" : "모든"} 논문이 ${both.join(", ")}을(를) 함께 씁니다. 같은 데이터셋의 결과를 나란히 보려면: `,
    both.map(x => [h("button", { class: "link", "data-add-column": x, on: () => compareAgain(c.task || V.task.id, [...c.columns, `${x} 결과`].slice(-8), c, `${x} 결과`) }, `+ "${x} 결과" 열`), " "])));
  if (!wide) box.append(h("p", null, h("button", { class: "link", "data-wide": "1", on: () => show({ mode: "matrix", c }) }, "크게 보기")));
  return box;
}
// criteria the user said in a chat message, now this task's intent (Guard and the agent's brief use them)
const noted = c => msg("Pablo", null, (c.items || []).length ? h("p", { class: "muted", "data-intent": "1" }, "📌 작업 기준에 추가했습니다: ",
  c.items.map(i => `${i.text} (${i.strength === "hard" ? "반드시" : "가능하면"})`).join(" · "), " ",
  h("button", { class: "link", on: () => show({ mode: "intent" }) }, "기준 보기")) : null,
  (c.pending || []).map(k => held({ ...k, live: c.live }, c.task || (V && V.task.id))),
  (c.unread || []).map(u => unreadRow({ ...u, live: c.live }, c.task || (V && V.task.id))));
// ③ a line the reader could not classify is shown, never dropped: the user makes it a rule (반드시 / 가능하면) or lets it go
function unreadRow(u, task) {
  const open = u.live || (V && (V.intent.unread || []).includes(u.id));
  const row = h("p", { class: "muted", "data-unread": u.id }, "❔ 기준으로 읽지 못했습니다: ", h("b", null, u.text), " ");
  const was = { hard: "(반드시로 둠)", soft: "(가능하면으로 둠)", skip: "(넘김)", rule: "(기준으로 둠)" }[((V && V.intent.decided) || {})[u.id]] || "(처리함)";
  if (!open || !window.pabloHost || !pabloHost.intent) return row.append(open ? "" : was), row;
  const act = (a, done) => () => pabloHost.intent(task, u.id, a).then(() => {
    row.lastChild.replaceWith(h("span", { "data-decided": a }, done));
    // the new-task message counts what is still to decide, and stops asking once nothing is
    const left = document.querySelectorAll("[data-unread] [data-as]").length, ask = document.querySelector("[data-made] [data-ask]");
    if (ask) ask.textContent = left ? `아직 정하지 않은 줄 ${left}개가 위에 있습니다. ` : "읽지 못한 줄도 모두 정했습니다. ";
    refresh(); }, e => row.append(h("span", null, " " + fail(e))));
  row.append(h("span", null, h("button", { class: "link", "data-as": "hard", on: act("hard", "반드시 지킬 기준으로 두었습니다.") }, "반드시"), " · ",
    h("button", { class: "link", "data-as": "soft", on: act("soft", "가능하면 지킬 기준으로 두었습니다.") }, "가능하면"), " · ",
    h("button", { class: "link", "data-as": "skip", on: act("reject", "기준으로 두지 않았습니다.") }, "괜찮음")));
  return row;
}
// B4: a criterion said in hedged words is held back until the user decides; decided ones show what was decided
function held(k, task) {
  const open = k.live || (V && V.intent.questions.some(q => q.id === k.id)), row = h("p", { class: "muted", "data-held": k.id }, "❔ 기준으로 둘까요? ", h("b", null, k.text), " ");
  if (!open || !window.pabloHost || !pabloHost.intent) return row.append(open ? "" : "(처리함)"), row;
  const act = (a, done) => () => pabloHost.intent(task, k.id, a).then(() => { row.lastChild.replaceWith(h("span", null, done)); refresh(); },
    e => row.append(h("span", null, " " + fail(e))));
  row.append(h("span", null, h("button", { class: "link", "data-promote": k.id, on: act("promote", "기준에 추가했습니다.") }, "기준으로 추가"), " · ",
    h("button", { class: "link", "data-reject": k.id, on: act("reject", "무시했습니다.") }, "무시")));
  return row;
}
function said(c) {
  if (c.role === "audit") return [msg("Pablo", null, audited(c))];
  if (c.role === "spec") return [msg("Pablo", null, conditions([...(c.checks || []), ...(c.missing || [])], c.dropped, c.diff))];
  const said1 = { "spec-drop": "📋 재현 조건에서 뺐습니다: ", "spec-restore": "📋 뺀 재현 조건을 되살렸습니다: ",  // ⑩ taken out / back
    "spec-deviate": `◇ 논문 조건을 의도한 차이(${WHERE_DEV[c.scope || "task"]})로 두었습니다: `, "spec-undeviate": "📋 의도한 차이를 거두고 논문 조건으로 되돌렸습니다: " }[c.role];  // ⑦
  if (said1) { const k = V.checks[c.check];
    return k ? [msg("Pablo", null, h("p", { class: "muted", "data-spec-edit": c.role.slice(5) }, said1,
      (SPEC[k.spec.category] || k.spec.category) + " · ", fact(k), c.reason ? ` (이유: ${c.reason})` : "",
      c.role !== "spec-deviate" ? "" : (c.scope || "task") === "runs" ? ". 기본 실행은 논문대로 두고, 새 파일이나 실행 옵션으로 따로 돌릴 때만 막지 않습니다. 기존 파일의 이 값을 바꾸면 확인을 받습니다."
        : ". Pablo는 이 작업에서 이 조건으로 막지 않고, 에이전트에게 이 차이와 이유를 알립니다."))] : []; }
  if (c.role === "criterion-edit") return [msg("Pablo", null, h("p", { class: "muted", "data-criterion-edit": c.action },  // ④ a criterion changed in the panel
    { hard: "📌 작업 기준을 '반드시'로 바꿨습니다: ", soft: "📌 작업 기준을 '가능하면'으로 바꿨습니다: ", drop: "📌 작업 기준을 지웠습니다: ",
      restore: "📌 지운 작업 기준을 되살렸습니다: " }[c.action] || "📌 작업 기준을 바꿨습니다: ", c.text, c.reason ? ` (이유: ${c.reason})` : ""))];
  if (c.role === "spec-add") { const k = V.checks[c.check];  // ⑩ a sentence the user picked in the paper
    return k ? [msg("Pablo", null, h("p", { class: "muted", "data-spec-add": k.id }, "📋 고른 문장을 재현 조건에 더했습니다: ",
      (SPEC[k.spec.category] || k.spec.category) + " · ", fact(k), k.state === "waived" ? " (나중에 뺌)" : ""))] : []; }
  if (c.role === "compare") return [msg("Pablo", null, matrix(c))];
  if (c.role === "intent") return [noted(c)];
  if (c.role === "changes") return [msg("Pablo", null, changed(c, V.task.id))];
  if (c.role === "user") return [msg("You", c.at, h("p", null, c.text))];
  if (c.role === "agent") return [msg("Pablo", null, h("p", { class: "stream", style: "white-space:pre-wrap" }, c.text || ""),
    c.status === "interrupted" ? h("p", { class: "muted", "data-stopped": "1" }, "중지했습니다.") : null,
    c.error ? h("div", { class: "call block" }, h("p", { class: "head" }, "⚠ " + c.error)) : null)];
  if (c.role !== "ask") return [];
  const k = c.check && V.checks[c.check];
  return [msg("You", c.at, h("p", null, c.text)), msg("Pablo", null, h("div", { class: "asked", "data-check": c.check || "" },
    k ? [h("p", null, cited(k.conclusion || k.title, k.evidence)), webOnly(k),
         c.dropped ? h("p", { class: "muted" }, `자료에서 찾지 못한 인용 ${c.dropped}개는 뺐습니다.`) : null]
      : h("div", { class: "call block" }, h("p", { class: "head" }, "⚠ " + (c.error || ASKFAIL)))))];
}
// an edit made just now (panel, picked sentence): its line joins the conversation at once (chat.json has it for later)
function echo(task, c) {
  if (!V || V.task.id !== task) return;
  live(task).append(...said(c)); $("log").scrollTop = $("log").scrollHeight;
}
// one timeline: the task, its research, the chat log and the Guard cards, in the order they happened
// P4: each message's stage, from what the record is (a spec is 조건 확정, an audit 재현 점검, ...), a divider where
// the stage changes, and a tag row: the stage, then what it is about (files, [n]); the rest folds into "N개 더"
function kindOf() { const d = (M.desk || {})[V.task.id] || {}, ps = d.papers || [];
  return d.kind || (d.folder && ps.length ? "repro" : ps.length ? "read" : "general"); }
function stageOfRole(role, kind) {
  const r = String(role || "");
  if (kind === "repro") return r === "start" ? "준비" : /^(spec|criterion|intent)/.test(r) || r === "ask" ? "조건 확정"
    : r === "audit" ? "재현 점검" : r === "report" ? "보고서" : "구현·실행";
  if (kind === "read") return r === "start" || /^spec/.test(r) ? "준비" : r === "compare" ? "비교표" : r === "report" ? "정리" : "질문";
  return r === "start" ? "준비" : r === "report" ? "검토" : "작업";
}
const STAGE_LIST = { repro: ["준비", "조건 확정", "구현·실행", "재현 점검", "보고서"], read: ["준비", "질문", "비교표", "정리"], general: ["준비", "작업", "검토"] };
const STAGE_KEY = { "준비": "prep", "조건 확정": "spec", "구현·실행": "run", "재현 점검": "audit", "보고서": "report",  // the stage bar's data-stage
  "질문": "ask", "비교표": "compare", "정리": "wrap", "작업": "work", "검토": "review" };
// o: the person's override for this message (P5: {stage, decision}); auto: the stage Pablo computed
function tagRow(el, stage, key, o = {}, auto = stage, all = false) {
  const body = el.children && el.children[1]; if (!body || body.querySelector(":scope > .tags")) return;
  const files = [...new Set([...el.querySelectorAll("button.file code, .at code")].map(c => c.textContent.split(":")[0]))];
  // a quote by its paper and page ("LinearRAG p.9"), not the chat's running [n] (QA 10/26: 대상별 grouped by "[1]")
  const refName = c => { const a = M.anchors[c.dataset.e], s = a && M.sources[a.source];
    return a && a.page && s && s.title ? `${s.title.length > 24 ? s.title.slice(0, 23) + "…" : s.title} p.${a.page}` : c.textContent; };
  const refs = [...new Set([...el.querySelectorAll(".cite")].map(refName))];
  const targets = [...files.map(f => "파일 · " + f), ...refs.map(r => "근거 · " + r)]; el.dataset.targets = JSON.stringify(targets);
  const shown = all ? targets : [...files.slice(0, 2).map(f => "파일 · " + f), ...refs.slice(0, 2).map(r => "근거 · " + r)];
  const more = all ? 0 : Math.max(0, files.length - 2) + Math.max(0, refs.length - 2);
  const row = h("div", { class: "tags", "data-auto": auto }, h("span", { class: "tg stage" + (o.stage ? " mine" : ""), title: o.stage ? `사람이 고침 (자동: ${auto})` : null }, stage),
    o.decision ? h("span", { class: "tg manual", "data-decision": "1" }, "결정") : null, ...shown.map(t => h("span", { class: "tg tgt" }, t)),
    more ? h("small", { class: "more" }, `· ${more}개 더`) : null);
  if (key && window.pabloHost && pabloHost.setUi) row.append(h("button", { class: "tagbtn", "data-tag-edit": "1", title: "이 메시지의 태그 고치기",
    on: () => tagEdit(row, key, stage, o) }, ico("pencil", 12), "태그"));
  if (window.pabloHost && pabloHost.makeCriterion && el.classList.contains("msg")) row.append(h("button", { class: "tagbtn", "data-crit-make": "1",
    title: "이 메시지의 글을 작업 기준으로", on: () => critMake(row, el) }, ico("pin", 12), "기준으로"));
  body.append(row);
}
// a message's words made a criterion of this task by the person, in a sentence they trim: a rule (반드시 / 가능하면), never
// the goal. Guard, the brief and 재현 점검 follow at once; the conversation says so
const msgWords = (el, max) => [...el.children[1].children].filter(c => !c.classList.contains("who") && !c.classList.contains("tags"))
  .map(c => c.textContent).join(" ").replace(/\s+/g, " ").trim().slice(0, max);
function critMake(row, el) {
  const old = row.querySelector(".tagedit"); if (old) return old.remove();
  const task = V.task.id, words = msgWords(el, 300);
  const text = h("textarea", { class: "ce-text", "data-crit-text": "1", rows: 3, maxlength: 1000 }); text.value = words;
  const note = h("p", { class: "muted" }, "이 작업에만 적용됩니다. 지킬 내용만 한 문장으로 남겨 주세요.");
  const ed = h("div", { class: "tagedit" }, h("b", null, "이 글을 작업 기준으로"), text,
    h("div", { class: "te-st" }, [["hard", "반드시"], ["soft", "가능하면"]].map(([v, n]) =>
      h("label", null, h("input", { type: "radio", name: "ce-" + task, value: v, checked: v === "hard" ? true : null }), " ", n))), note,
    h("div", { class: "te-foot" }, h("button", { class: "pill", on: () => ed.remove() }, "취소"), h("button", { class: "pill on", "data-crit-save": "1", on: () => {
      const t = text.value.trim(), st = ed.querySelector("input[type=radio]:checked").value;
      if (!t) return text.focus();
      pabloHost.makeCriterion(task, t, st).then(items => {
        if (!items.length) return note.replaceChildren("이미 같은 기준이 있습니다.");
        ed.remove(); echo(task, { role: "intent", items }); return refresh(); }, e => note.replaceChildren(fail(e))); } }, "기준으로 추가")));
  row.append(ed); text.focus();
}
// P5: the person changes a message's stage or pins it as a decision; that wins over what Pablo computes, on every redraw
function tagEdit(row, key, stage, o) {
  const old = row.querySelector(".tagedit"); if (old) return old.remove();
  const names = STAGE_LIST[kindOf()] || STAGE_LIST.general, task = V.task.id;
  const ed = h("div", { class: "tagedit" }, h("b", null, "이 메시지의 태그"),
    h("div", { class: "te-st" }, names.map(n => h("label", null, h("input", { type: "radio", name: "te-" + key, value: n, checked: n === stage ? true : null }), " ", n,
      n === row.dataset.auto ? h("small", null, " (자동)") : null))),
    h("label", { class: "te-dec" }, h("input", { type: "checkbox", checked: o.decision ? true : null }), " 결정으로 고정 — 단계별 보기의 결정 목록과 보고서의 근거가 됩니다"),
    h("p", { class: "muted" }, "사람이 고친 태그는 다시 계산해도 바뀌지 않습니다."),
    h("div", { class: "te-foot" }, h("button", { class: "pill", on: () => ed.remove() }, "취소"), h("button", { class: "pill on", "data-tag-save": "1", on: () => {
      const st = (ed.querySelector("input[type=radio]:checked") || {}).value || stage, dec = ed.querySelector("input[type=checkbox]").checked;
      const tags = { ...(((M.desk || {})[task] || {}).tags || {}) }, v = { ...(st !== row.dataset.auto ? { stage: st } : {}), ...(dec ? { decision: true } : {}) };
      if (Object.keys(v).length) tags[key] = v; else delete tags[key];
      pabloHost.setUi(task, "tags", tags).then(() => refresh()).then(() => V && V.task.id === task && conversation()); } }, "저장")));
  row.append(ed);
}
const firstText = el => { const p = el.querySelector("p"); return (p ? p.textContent : el.textContent).replace(/\s+/g, " ").trim().slice(0, 90); };
// P6 단계별: one box per stage; past ones show a summary (the person's text wins over the record-based one) and the
// decisions, their messages folded; the current stage is open; stages not reached yet are placeholders
function byStage(log, rows, kind, D) {
  const names = STAGE_LIST[kind] || STAGE_LIST.general, cur = (document.querySelector("#stages .st-current b") || {}).textContent;
  const ci = names.indexOf(cur), can = window.pabloHost && pabloHost.setUi;
  names.forEach((n, i) => {
    const mine = rows.filter(r => r[1] === n), msgs = mine.filter(r => r[0].classList && r[0].classList.contains("msg")), decs = mine.filter(r => r[2].decision);
    const files = new Set(mine.flatMap(r => [...r[0].querySelectorAll("button.file code, .at code")].map(c => c.textContent.split(":")[0]))).size;
    const facts = msgs.length ? [`메시지 ${msgs.length}`, decs.length ? `결정 ${decs.length}` : null, files ? `파일 ${files}` : null].filter(Boolean).join(" · ") : "아직 대화가 없습니다";
    // a stage with messages is never 아직, whatever the stage bar computes from the material (진행: talked about, not done);
    // one the bar marks done (✓) is 완료 here too (QA 10/26: ✓ above, 진행 below for the same stage)
    const done = !!document.querySelector(`#stages .stage.st-done[data-stage="${STAGE_KEY[n] || ""}"]`);
    const state = i === ci ? "지금" : done || (ci >= 0 && i < ci) ? "완료" : !msgs.length ? "아직" : "진행", own = (D.summary || {})[n];
    // the model's summary, written on request; behind once the stage has more messages than it read. A person's text wins
    const auto = (D.auto || {})[n], behind = auto ? msgs.length - auto.n : 0;
    const write = can && pabloHost.summarize && !own && msgs.length && ($("acct") || { dataset: {} }).dataset.state === "connected";
    // `x` in a summary is code, as in the cards (QA 10/26: the model's backticks showed as they are)
    const sum = h("div", { class: "sg-sum" }, own ? [h("span", { class: "tg manual" }, "사람이 고침"), " ", rich(own)]
      : auto ? [h("span", { class: "tg", "data-auto-summary": "1" }, ico("sparkle", 12), "모델 요약"), " ", rich(auto.text),
        behind > 0 ? h("small", { class: "muted", "data-behind": behind }, ` · 그 뒤 메시지 ${behind}개`) : null]
      : h("span", { class: "muted" }, "기록 요약 — " + facts),
      write ? [" ", h("button", { class: "link", "data-summarize": n, on: () => summarize(sum, n, msgs) }, ico("sparkle", 12), auto ? " 다시 쓰기" : " 요약 쓰기")] : null,
      can && msgs.length ? [" ", h("button", { class: "link", "data-summary-edit": n, on: () => summaryEdit(sum, n, own || (auto && auto.text) || "") }, ico("pencil", 12), " 요약 고치기")] : null);
    log.append(h("div", { class: "stagegroup st-" + (state === "지금" || state === "진행" ? "now" : state === "아직" ? "later" : "past"), "data-stage": n },
      h("div", { class: "sg-head" }, h("span", { class: "tg stage" }, n), h("b", null, state), h("small", null, facts)), sum,
      decs.length ? h("ul", { class: "sg-dec" }, decs.map(r => h("li", null, h("span", { class: "tg manual" }, "결정"), " ", firstText(r[0])))) : null,
      mine.length ? h("details", { class: "sg-msgs", open: state === "지금" || state === "진행" ? true : null }, h("summary", null, `대화 ${msgs.length}`), mine.map(r => r[0])) : null));
  });
  rows.filter(r => !names.includes(r[1])).forEach(r => log.append(r[0]));
}
// one model call per click (not on every redraw): the stage's messages as the page groups them, oldest first
function summarize(sum, n, msgs) {
  const task = V.task.id, btn = sum.querySelector("[data-summarize]");
  if (btn) { btn.disabled = true; btn.textContent = "요약 쓰는 중…"; }
  pabloHost.summarize(task, n, msgs.map(r => ({ who: r[0].classList.contains("pablo") ? "Pablo" : "You", text: msgWords(r[0], 4000) })))
    .then(() => refresh()).then(() => V && V.task.id === task && conversation(),
      e => { if (btn) btn.remove(); sum.append(h("span", { class: "muted" }, " " + fail(e))); });
}
function summaryEdit(sum, n, cur) {
  const task = V.task.id, ta = h("textarea", { class: "sg-edit", rows: 3 }); ta.value = cur;
  sum.replaceChildren(ta, h("div", { class: "te-foot" }, h("button", { class: "pill", on: () => conversation() }, "취소"),
    h("button", { class: "pill on", "data-summary-save": n, on: () => { const all = { ...(((M.desk || {})[task] || {}).summary || {}) }, t = ta.value.trim();
      if (t) all[n] = t; else delete all[n];
      pabloHost.setUi(task, "summary", all).then(() => refresh()).then(() => V && V.task.id === task && conversation()); } }, "저장")));
  ta.focus();
}
// P6 대상별: grouped by what each message is about (its first file or [n]); the rest under 대상 없음
function byTarget(log, rows) {
  // a message sits under its first target; each of its other targets gets a line that leads to it (QA 10/26: an audit
  // card about config.yaml, logs/2wiki.log and run.py showed under config.yaml only, the other two had no group)
  const groups = new Map(), also = new Map(), rest = [], add = (m, t, x) => { if (!m.has(t)) m.set(t, []); m.get(t).push(x); };
  rows.forEach(r => { const x = r[0]; if (!(x.classList && x.classList.contains("msg"))) return rest.push(x);
    const ts = JSON.parse(x.dataset.targets || "[]"); add(groups, ts[0] || "대상 없음", r); ts.slice(1).forEach(t => add(also, t, x)); });
  also.forEach((_, t) => groups.has(t) || groups.set(t, []));
  const n = t => groups.get(t).length + (also.get(t) || []).length;
  const lead = (x, home) => h("p", { class: "muted", "data-also": home }, "↳ ", h("button", { class: "link", title: `'${home}' 묶음에서 보기`,
    on: () => { x.closest("details").open = true; x.scrollIntoView({ block: "center" }); } }, `${x.classList.contains("pablo") ? "Pablo" : "나"} · ${firstText(x).slice(0, 60)}`),
    h("small", null, ` — '${home}' 묶음에 있음`));
  // files first, then quotes by page, then 대상 없음 (one conditions card can quote a dozen pages: they would push the
  // files down), each by how many messages it has
  const rank = t => t === "대상 없음" ? 2 : t.startsWith("파일 · ") ? 0 : 1;
  [...groups.keys()].sort((a, b) => rank(a) - rank(b) || n(b) - n(a)).forEach((t, i) => {
    const rs = groups.get(t), more = (also.get(t) || []).map(x => lead(x, JSON.parse(x.dataset.targets)[0]));
    log.append(h("details", { class: "targetgroup", "data-target": t, open: i === 0 ? true : null },
      h("summary", null, h("span", { class: "tg" + (t === "대상 없음" ? "" : " tgt") }, t), h("small", null, `대화 ${n(t)}`)), rs.map(r => r[0]), more)); });
  rest.forEach(x => log.append(x));
}
// a stage in the stage bar: only that stage's messages (and its dividers) stay; again -> all
function stageFilter(label) {
  const log = $("log"), on = log.dataset.filter === label ? "" : label; log.dataset.filter = on;
  const old = $("filter-banner"); if (old) old.remove();
  let hid = 0, kept = 0;
  [...log.children].forEach(x => { const s = x.dataset && x.dataset.stage; if (!s) return;
    const hide = !!on && s !== on; x.classList.toggle("filtered", hide); if (x.classList.contains("msg")) hide ? hid++ : kept++; });
  if (on) log.prepend(h("div", { id: "filter-banner" }, h("span", null, `${on} 단계 대화만 보는 중 · ${kept}개 · 다른 단계 ${hid}개 숨김`),
    h("button", { class: "link", on: () => stageFilter(on) }, "전체 보기")));
  document.querySelectorAll("#stages .stage").forEach(x => x.classList.toggle("picked", !!on && x.querySelector("b").textContent === on));
}
function conversation() {
  cites = {};  // ⑩ review: [n] by when the evidence was found, so "[16]" is the same live and after a reload
  [...new Set(Object.values(V.checks).flatMap(c => c.evidence))].filter(e => M.anchors[e])
    .sort((a, b) => +a.replace(/\D/g, "") - +b.replace(/\D/g, "")).forEach((e, i) => { cites[e] = i + 1; });
  const log = $("log"); log.textContent = ""; log.dataset.filter = "";  // a redraw shows every stage again
  if (busy !== V.task.id) delete lives[V.task.id];  // what was said is in the chat log; only a running turn stays live
  const chat = V.chat || [], asked = new Set(chat.map(c => c.check).filter(Boolean)), research = answer(asked);
  const kind = kindOf(), sg = r => stageOfRole(r, kind);
  const at = x => new Date(x || 0).getTime(), t0 = at(V.task.at), items = [[t0, msg("You", V.task.at, h("p", null, V.task.text)), sg("start"), "start"]];
  if (research.length) items.push([t0, msg("Pablo", null, research), sg("start"), "research"]);
  const inLog = new Set(chat.flatMap(c => c.role === "spec" ? [...(c.checks || []), ...(c.missing || [])] : c.role === "spec-add" ? [c.check] : []));
  const loose = V.research.filter(id => V.checks[id].spec && V.checks[id].state !== "waived" && !inLog.has(id));
  if (loose.length) items.push([t0, msg("Pablo", null, conditions(loose, 0)), sg("spec"), "spec-loose"]);
  issues().forEach((x, i) => items.push([t0, msg("Pablo", null, x), sg("start"), "issue@" + i]));
  chat.forEach(c => said(c).forEach(x => items.push([at(c.at), x, sg(c.role), c.role + "@" + c.at])));  // a message's key: role@time
  V.actions.forEach(a => { if (live().querySelector(`[data-act="${CSS.escape(a.id)}"]`)) return;  // its live card is below
    const x = a.verdict === "ALLOW" ? failed(a) : action(a); if (x) items.push([at(a.at), msg("Pablo", null, x), sg("action"), "act:" + a.id]); });
  // P5: the person's tags win; P6: the view (시간순 by default; the task's choice, else the settings')
  const D = (M.desk || {})[V.task.id] || {}, over = D.tags || {}, view = D.view || (M.settings || {}).view || "time";
  const allTags = (M.settings || {}).tags === "all";
  const rows = items.sort((x, y) => x[0] - y[0]).map(([t, x, s, key]) => {  // stable sort: same time keeps the order above
    const o = over[key] || {}, st = o.stage || s;
    if (st && x.classList && x.classList.contains("msg")) { x.dataset.stage = st; x.dataset.key = key; tagRow(x, st, key, o, s, allTags); }
    return [x, st, o, t]; });
  if (view === "stage") byStage(log, rows, kind, D);
  else if (view === "target") byTarget(log, rows);
  else { let prev = null; const now = (document.querySelector("#stages .st-current b") || {}).textContent;  // A2: its dot is orange
    rows.forEach(([x, s, , t]) => {
      if (s && x.classList && x.classList.contains("msg")) {
        if (s !== prev) log.append(h("div", { class: "divider", "data-stage": s, "data-now": s === now ? "1" : null },
          h("span", { class: "tg stage" }, h("span", { class: "dot" }), s), t ? h("small", null, time(t)) : null));
        prev = s;
      }
      log.append(x); }); }
  if (V.intent.questions.length) log.append(msg("Pablo", null, h("div", { class: "call" },
    h("p", { class: "head" }, "⚠ 결정이 필요합니다."),
    V.intent.questions.map(q => /^K\d+$/.test(q.id) ? held(q, V.task.id) : h("p", { title: q.id, "data-id": q.id }, rich(q.text))),
    h("p", null, h("button", { class: "link", on: () => show({ mode: "intent" }) }, "작업 기준 보기")))));
  log.append(live());
  finish();
  log.scrollTop = chat.length ? log.scrollHeight : 0;  // a conversation reopens at its latest message
}
// every plan step done -> one closing message (in the live part, so a refresh can add it too)
function finish() {
  if (!V.plan || !V.plan.steps.length || V.plan.steps.some(st => stepState(st)[0] !== "done") || $("log").querySelector(".finish")) return;
  live().append(h("div", { class: "finish" }, msg("Pablo", null, art("confident", "pose"), h("p", null, "작업을 마쳤습니다."))));
}
// QA 10/26 (D3): a finished turn's live messages (what was said, the agent's reply) get their tag row (✎ 태그, 📌 기준으로)
// once the log has them, paired from the end with the log entries not drawn yet; the live part itself stays (the checks
// read its stream). In 단계별 / 대상별 the view is drawn again so they join their group
function settleLive() {
  if (!V || busy === V.task.id) return;
  const L = lives[V.task.id]; if (!L || !L.isConnected) return;
  const mine = [...L.querySelectorAll(":scope > .msg.user")], replies = [...L.querySelectorAll(":scope > .msg.pablo")].filter(m => m.querySelector(".stream"));
  if (![...mine, ...replies].some(m => !m.dataset.key)) return;
  const D = (M.desk || {})[V.task.id] || {};
  if ((D.view || (M.settings || {}).view || "time") !== "time") return conversation();
  const drawn = new Set([...document.querySelectorAll("#log .msg[data-key]")].map(m => m.dataset.key));
  const fresh = roles => (V.chat || []).filter(c => roles.includes(c.role) && !drawn.has(c.role + "@" + c.at));
  const put = (els, cs) => els.slice().reverse().forEach((el, i) => { const c = cs[cs.length - 1 - i]; if (c) tagLive(el, c.role, c.at); });
  put(mine, fresh(["user", "ask"])); put(replies, fresh(["agent"]));
}
// one live message as the log will draw it: its key (role@time), its stage, the person's tag if any
function tagLive(el, role, at) {
  if (!el || el.dataset.key || !V) return;
  const key = role + "@" + at, s = stageOfRole(role, kindOf()), o = (((M.desk || {})[V.task.id] || {}).tags || {})[key] || {};
  el.dataset.stage = o.stage || s; el.dataset.key = key; tagRow(el, o.stage || s, key, o, s, (M.settings || {}).tags === "all");
}
function select(tid) {
  V = M.views[tid] || M.views[M.current] || null; lastEv = null;
  panelQuiet = true; close(); panelQuiet = false; sidebar(); header(); tools();
  if (!V) return empty();
  V.task.at = (M.tasks.find(t => t.id === V.task.id) || {}).at;
  conversation(); panelBack();
  document.title = "Pablo · " + nameOf(M.tasks.find(x => x.id === V.task.id) || V.task);
}
// P7: the right column as this task left it (on opening the task, and on the app's first state read, which brings the
// desktop.json the first select() did not have yet)
function panelBack() {
  const pp = ((M.desk || {})[V.task.id] || {}).panel;
  panelSaved[V.task.id] = JSON.stringify(pp || { open: false, tab: "intent" });
  if (pp && pp.open) { const st = pp.tab === "evidence" ? evidenceFor() : pp.tab === "plan" && !V.plan ? null : { mode: pp.tab }; if (st) show(st); }
}
// M5.1: no task yet -> an empty Pablo screen; the desktop makes tasks in the app (+ 새 작업)
function empty() {
  const log = $("log"); log.textContent = ""; document.title = "Pablo";
  log.append(h("div", { class: "empty" }, art("default"), h("b", null, "무엇을 해볼까요?"), h("p", null, "새 작업을 만들어 시작하세요."),
    window.pabloHost && pabloHost.newTask ? h("button", { class: "pill on", on: () => newTask() }, ico("plus", 14), "새 작업") : null));
}
let tools = () => {}, newTask = () => {}, refresh = () => Promise.resolve();  // desktop only (M5.1): task tools, new task form, live state

// ---- one context panel: source | intent | plan | trace ---------------------------------------------------------
function toggle(st) { (hi >= 0 && document.body.classList.contains("panel") && hist[hi].mode === st.mode && !st.e) ? close() : show(st); }
function show(st, push = true) {
  if (push) { hist = hist.slice(0, hi + 1); hist.push(st); hi = hist.length - 1; }
  if (["source", "code", "paper", "matrix"].includes(st.mode)) lastEv = st;
  document.body.classList.add("panel"); document.body.classList.remove("pdf", "code", "wide");
  CSS.highlights.clear();
  document.querySelectorAll(".cite").forEach(b => b.classList.toggle("on", st.mode === "source" && b.dataset.e === st.e));
  const p = $("panel"); p.textContent = ""; delete p.dataset.live; delete p.dataset.still;
  ({ source, intent, plan, trace, code: codeView, matrix: matrixView, paper })[st.mode](p, st);
  header(); rememberPanel();
}
function close() {
  document.body.classList.remove("panel", "pdf", "code", "wide"); CSS.highlights.clear(); hist = []; hi = -1;
  document.querySelectorAll(".cite.on").forEach(b => b.classList.remove("on"));
  if (V) { header(); rememberPanel(); }
}
const go = d => { if (hist[hi + d]) { hi += d; show(hist[hi], false); } };
// A2: the panel's chrome is line icons; closing folds the panel into the rail (panel-right). An icon has no text.
const turned = (name, deg, size) => { const s = ico(name, size); s.style.transform = `rotate(${deg}deg)`; return s; };
const xbtn = () => h("button", { class: "x", title: "닫기", on: close }, ico("panel-right"));
const navs = () => [h("button", { class: "nav", title: "뒤로", disabled: hi <= 0, on: () => go(-1) }, turned("arrow-up", -90)),
  h("button", { class: "nav", title: "앞으로", disabled: hi >= hist.length - 1, on: () => go(1) }, turned("arrow-up", 90))];
// .url keeps its emoji in textContent (tests read "📄 TinyRAG · PDF"); on screen the line icon stands for it
const urlIco = (name, emoji) => [ico(name, 14), h("span", { class: "em" }, emoji)];
const simple = (p, title, body, foot) => p.append(h("div", { class: "phead" }, h("h2", null, title), xbtn()),
  h("div", { id: "pbody" }, body), foot ? h("div", { class: "pfoot" }, h("div", { class: "composer" },
    h("input", { disabled: true, placeholder: foot }), h("button", { disabled: true }, ico("arrow-up", 14)))) : "");  // append(null) prints "null"

// ⑩ (desktop) a paper condition's 빼기: why first (whoever reads the audit or the report sees it), then the Guard, the
// brief and 재현 점검 stop holding it; 되살리기 puts it back
function takeOut(c) {
  const box = h("span", { class: "edits" }), task = V.task.id;
  const ask = () => { const why = h("input", { class: "why", "data-spec-why": c.id, placeholder: "빼는 이유 (필수)" });
    const ok = () => !why.value.trim() ? (why.classList.add("need"), why.focus())
      : pabloHost.condition(task, "drop", { id: c.id, reason: why.value.trim() }).then(() => {
          echo(task, { role: "spec-drop", check: c.id, reason: why.value.trim() }); return refresh(); }, e => box.replaceChildren(h("span", { class: "muted" }, " " + fail(e))));
    why.addEventListener("keydown", e => { if (e.key === "Enter" && !e.isComposing) ok(); });
    box.replaceChildren(" ", why, " ", h("button", { class: "link", "data-spec-drop-ok": c.id, on: ok }, "빼기"), " · ",
      h("button", { class: "link", on: () => box.replaceWith(takeOut(c)) }, "취소"));
    why.focus(); };
  box.append(" ", h("button", { class: "link", "data-spec-drop": c.id, title: "잘못 뽑혔거나 이 재현과 상관없는 조건을 뺍니다", on: ask }, "빼기"));
  return box;
}
// ⑦ (desktop) differ from a paper condition on purpose (ablation, other hardware): why first; the Guard then stops holding
// the work to it, the agent is told the difference and why, 재현 점검 shows it as 의도한 차이. 논문대로 되돌리기 ends it.
function differ(c, task = V.task.id) {
  const box = h("span", { class: "edits" }), oops = e => box.replaceChildren(h("span", { class: "muted" }, " " + fail(e)));
  if (devOf(c)) return box.append(" ", h("button", { class: "link", "data-undeviate": c.id, on: () => pabloHost.condition(task, "undeviate", { id: c.id })
    .then(() => { echo(task, { role: "spec-undeviate", check: c.id }); return refresh(); }, oops) }, "논문대로 되돌리기")), box;
  const ask = () => { const why = h("input", { class: "why", "data-dev-why-in": c.id, placeholder: "왜 일부러 다르게 하나요? (필수, 예: ablation)" });
    const scope = h("select", { class: "why", "data-dev-scope": c.id, title: "어디에서 다르게 하나요?" },
      h("option", { value: "runs" }, "별도 실행에서만 (기본 실행은 논문대로)"), h("option", { value: "task" }, "이 작업 전체"));
    const ok = () => !why.value.trim() ? (why.classList.add("need"), why.focus())
      : pabloHost.condition(task, "deviate", { id: c.id, reason: why.value.trim(), scope: scope.value }).then(() => {
          echo(task, { role: "spec-deviate", check: c.id, reason: why.value.trim(), scope: scope.value });
          box.replaceChildren(h("span", { class: "muted", "data-deviated": c.id }, scope.value === "runs"
            ? " ◇ 별도 실행에서만 다르게 두었습니다. 새 파일이나 실행 옵션으로 다르게 하면 막지 않고, 기존 파일의 이 값을 바꾸면 확인을 받습니다."
            : " ◇ 이 작업 전체에서 의도한 차이로 두었습니다. 같은 요청을 다시 보내면 이 조건으로 막지 않습니다."));
          return refresh(); }, oops);
    why.addEventListener("keydown", e => { if (e.key === "Enter" && !e.isComposing) ok(); });
    box.replaceChildren(" ", why, " ", scope, " ", h("button", { class: "link", "data-deviate-ok": c.id, on: ok }, "두기"), " · ",
      h("button", { class: "link", on: () => box.replaceWith(differ(c, task)) }, "취소"));
    why.focus(); };
  box.append(" ", h("button", { class: "link", "data-deviate": c.id, title: "일부러 논문과 다르게 합니다(이유 필수). 그 뒤로는 이 조건으로 막지 않습니다.", on: ask }, "의도한 차이로 두기"));
  return box;
}
// ⑦ a BLOCK on a paper condition: the way forward when the difference is on purpose, on the card itself
function offer(a, v = V) {
  const ks = a.verdict === "BLOCK" ? a.criteria.map(x => v.checks[x.id]).filter(k => k && k.spec && !k.spec.missing && k.state !== "waived" && !devOf(k)) : [];
  return ks.length && window.pabloHost && pabloHost.condition ? h("div", { class: "offer", "data-offer": a.id },
    h("p", { class: "muted" }, "일부러 논문과 다르게 하려는 것이라면 이유를 남기고 의도한 차이로 둘 수 있습니다. 그 뒤로는 이 조건으로 막지 않습니다:"),
    h("ul", { class: "ck" }, ks.map(k => h("li", { "data-id": k.id }, (SPEC[k.spec.category] || k.spec.category) + " · ",
      rich((k.conclusion || k.title).replace(/\s*\[\d+\]/g, "")), differ(k, a.task || V.task.id))))) : null;
}
function putBack(c) {
  const at = h("span");
  return [at, h("button", { class: "link", "data-spec-restore": c.id, on: () => pabloHost.condition(V.task.id, "restore", { id: c.id }).then(() => {
    echo(V.task.id, { role: "spec-restore", check: c.id }); return refresh(); },
    e => at.replaceChildren(h("span", { class: "muted" }, fail(e) + " "))) }, "되살리기")];
}
// ④ (desktop) a criterion's own buttons: the other strength, and 지우기 with an optional why, asked in place
function edits(x, kind) {
  if (!kind || !window.pabloHost || !pabloHost.criterion || !/^[A-Z]\d+$/.test(x.id) || /^[TK]\d+$/.test(x.id)) return null;  // not the task itself
  const box = h("span", { class: "edits" }), task = V.task.id;
  const run = (action, reason) => pabloHost.criterion(task, x.id, action, reason).then(text => {
    echo(task, { role: "criterion-edit", action, text, reason: action === "drop" ? (reason || "").trim() : "" }); return refresh(); },
    e => box.replaceChildren(h("span", { class: "muted" }, " " + fail(e))));
  const ask = () => { const why = h("input", { class: "why", "data-why": x.id, placeholder: x.repro ? "재현 기본 기준입니다. 지우는 이유 (필수)"
      : x.all ? "모든 작업에서 지워집니다. 왜? (선택)" : "왜 지우나요? (선택)" });
    const ok = () => x.repro && !why.value.trim() ? (why.classList.add("need"), why.focus()) : run("drop", why.value);
    why.addEventListener("keydown", e => { if (e.key === "Enter" && !e.isComposing) ok(); });
    box.replaceChildren(" ", why, " ", h("button", { class: "link", "data-drop-ok": x.id, on: ok }, "지우기"), " · ",
      h("button", { class: "link", on: () => box.replaceWith(edits(x, kind)) }, "취소"));
    why.focus(); };
  box.append(" ", kind === "must" ? h("button", { class: "link", "data-to": "soft", on: () => run("soft") }, "가능하면으로")
    : kind === "prefer" ? h("button", { class: "link", "data-to": "hard", on: () => run("hard") }, "반드시로") : null,
    kind === "must" || kind === "prefer" ? " · " : null, h("button", { class: "link", "data-drop": x.id, on: ask }, "지우기"));
  return box;
}
function intent(p) {
  const I = V.intent, g = (t, cls, xs, kind) => xs.length ? [h("h3", null, t), h("ul", { class: "ck " + cls },
    xs.map(x => h("li", { title: x.id, "data-id": x.id }, x.prev ? h("span", { class: "prev" }, x.prev) : null, x.text,
      x.all && kind ? h("small", { class: "all", "data-all": "1", title: "이 기준은 모든 작업에 걸립니다. 바꾸면 다른 작업에도 바뀝니다." }, " 모든 작업") : null,
      edits(x, kind))))] : null;
  const spec = V.research.map(id => V.checks[id]).filter(c => c.spec && !c.spec.missing && c.state !== "waived");
  // ⑩ a condition taken out by the user (extracted wrongly, not part of this reproduction): with why, restorable
  const out = V.research.map(id => V.checks[id]).filter(c => c.spec && c.state === "waived" && c.waived_by === "user");
  const d = (M.desk || {})[V.task.id] || {}, main = (d.papers || []).find(x => x.primary), canEdit = window.pabloHost && pabloHost.condition;
  const pick = canEdit && main && (M.papers || {})[main.id] ? h("p", { class: "muted" }, h("button", { class: "link", "data-open-paper": main.id,
    on: () => show({ mode: "paper", src: main.id }) }, ico("file", 14), ` ${main.title} 열기`), " · 빠진 조건은 문장을 골라 더합니다.") : null;
  const code = main ? codeLine(main.id, V.task.id) : null;
  const row = c => h("li", { title: c.id, "data-id": c.id }, fact(c),
    c.spec.by === "user" ? h("small", { class: "muted", "data-by-user": "1" }, " 직접 더함") : null,
    ASIDE[c.spec.kind] ? h("small", { class: "muted", "data-aside": c.spec.kind }, c.spec.kind === "fact" ? " 서술 · 점검 안 함" : " 실험 범위 · 점검 안 함") : null,
    devOf(c) ? h("div", { class: "chk dev", "data-dev": c.id }, `◇ 의도한 차이(${WHERE_DEV[scopeOf(devOf(c))]}): ${devOf(c).why}`) : null,
    canEdit ? h("span", { class: "acts" }, differ(c), devOf(c) ? null : [" ·", takeOut(c)]) : null);  // A2: one group, shown on hover
  const kinds = [...Object.keys(SPEC), ...new Set(spec.map(c => c.spec.category).filter(k => !SPEC[k]))];  // grouped by kind, as in the card
  const paper = spec.length || out.length || pick ? [h("h3", null, "논문 조건"), kinds.flatMap(k => { const xs = spec.filter(c => c.spec.category === k);
      return xs.length ? [h("h4", { class: "kind" }, SPEC[k] || k), h("ul", { class: "ck must" }, xs.map(row))] : []; }),
    out.length ? h("details", { class: "gone", "data-spec-out": String(out.length) }, h("summary", null, ico("chevron-right", 12), `뺀 조건 ${out.length}개`),
      h("ul", { class: "ck" }, out.map(c => h("li", { title: c.id, "data-id": c.id }, h("s", null, (SPEC[c.spec.category] || c.spec.category) + " · " + (c.conclusion || c.title).replace(/\s*\[\d+\]/g, "")),
        h("div", { class: "muted" }, `${day(((c.spec.dropped || []).at(-1) || {}).from)} 뺌 · 이유: ${c.waive_reason}`, canEdit ? [" · ", putBack(c)] : null))))) : null, pick, code] : null;
  const body = [g("목표", "", I.goals, "goal"), g("반드시 지킬 것", "must", I.must, "must"), paper, g("선호", "", I.prefer, "prefer"),
    g("성공 조건", "q", I.success, "other"), g("결정", "", I.decisions, "other"), g("확인 필요", "q", I.questions)];
  const how = window.pabloHost && pabloHost.criterion
    ? h("p", { class: "muted", "data-how": "1" }, "기준은 항목 옆 버튼으로 고칩니다. 문장을 고치려면 지우고 대화에 다시 적으세요. 새 기준은 대화에 적으면 이 작업의 기준이 됩니다.") : null;
  // ④ removed criteria stay in view: when, why, and 되살리기 (the same criterion back, as strong as it was)
  const gone = (I.removed || []).filter(x => !x.to), back = x => { const at = h("span");
    return [at, h("button", { class: "link", "data-restore": x.id, on: () => pabloHost.criterion(V.task.id, x.id, "restore").then(text => {
      echo(V.task.id, { role: "criterion-edit", action: "restore", text }); return refresh(); },
      e => at.replaceChildren(h("span", { class: "muted" }, fail(e) + " "))) }, "되살리기")]; };
  const removed = gone.length ? h("details", { class: "gone", "data-removed": String(gone.length) }, h("summary", null, ico("chevron-right", 12), `지운 기준 ${gone.length}개`),
    h("ul", { class: "ck" }, gone.map(x => h("li", { title: x.id, "data-id": x.id }, h("s", null, x.text), x.all ? h("small", { class: "all", title: "되살리면 모든 작업에 다시 걸립니다." }, " 모든 작업") : null,
      h("div", { class: "muted" }, `${day(x.from)} 지움 · `, x.why ? `이유: ${x.why}` : "이유를 적지 않음",
        window.pabloHost && pabloHost.criterion ? [" · ", back(x)] : null))))) : null;
  simple(p, "현재 작업 기준", body.some(Boolean) ? [body, removed, how] : [h("p", { class: "muted" }, "기록된 기준이 없습니다."), removed, how]);
}
function stepState(st) {
  const rs = V.actions.filter(a => a.step === st.id).flatMap(a => a.runs).map(r => r.step_status);
  return rs.includes("completed") ? ["done", "✓"] : rs.includes("partial") ? ["doing", "●"] : ["todo", "○"];
}
function plan(p) {
  const steps = h("ol", { class: "steps" }, V.plan.steps.map((st, i) => { const [cls] = stepState(st);
    const mark = cls === "done" ? ico("check", 14) : String(i + 1);  // A2: done is a check, the rest their number
    const ev = st.checks.flatMap(id => V.checks[id].evidence);
    const sure = st.checks.length ? (st.checks.every(id => V.checks[id].outcome === "VERIFIED") ? "공식 근거 확인" : "일부 추정") : "작업 기준에 따름";
    return h("li", { class: cls, title: st.id, "data-id": st.id }, h("span", { class: "i" }, mark), h("span", null, rich(st.action)),
      h("span", { class: "sub" }, sure, " ", ev.map(cite), " · ",
        h("button", { class: "link", on: () => show({ mode: "trace", step: st.id }) }, "왜?"))); }));
  const more = V.plan.unverified.length ? [h("h3", null, "확인되지 않은 부분"),
    h("ul", { class: "ck" }, V.plan.unverified.map(id => h("li", { title: id },
      rich((V.plan.steps.find(s => s.id === id) || { action: id }).action))))] : null;
  simple(p, "작업 계획", [steps, more], "계획에 대해 물어보거나 수정해보세요… (곧 지원)");
}
function trace(p, st) {
  const act = st.act && V.actions.find(a => a.id === st.act);
  const stepId = act ? act.step : st.step, step = V.plan && V.plan.steps.find(s => s.id === stepId);
  const scoped = act || step;
  const checks = [...new Set(scoped ? [...(step ? step.checks : []), ...(act ? act.criteria.map(c => c.id) : [])]
                                     .filter(id => V.checks[id]) : V.research.filter(id => !V.checks[id].matrix))]
    .sort((x, y) => V.checks[y].evidence.length - V.checks[x].evidence.length);
  const crit = scoped ? [...(step ? step.intent : []), ...(act ? act.criteria.filter(c => !V.checks[c.id]) : [])] : V.intent.must;
  const li = (cls, k, ...v) => h("li", { class: cls }, h("div", { class: "k" }, k), h("div", { class: "v" }, v));
  const nodes = [li("", "사용자 요청", `"${V.task.text}"`)];
  const seen = new Set(), crits = crit.filter(x => !seen.has(x.id) && seen.add(x.id));
  if (crits.length) nodes.push(li("", "작업 기준", crits.map(x => h("div", { title: x.id }, rich(x.text)))));
  for (const id of checks) { const c = V.checks[id];
    c.evidence.forEach(e => { const a = M.anchors[e], src = M.sources[a.source];
      const n = li("ev", ["공식 원문 ", cite(e)], h("div", null, host(src.url).split("/")[0], " · ", src.title), h("code", null, a.exact));
      n.querySelector(".v").addEventListener("click", () => show({ mode: "source", e })); nodes.push(n); });
    c.issues.forEach(i => nodes.push(li("warn", "조사 중 바로잡은 점", rich(i.note))));
    if (c.conclusion) nodes.push(li("", "조사 결론", rich(c.conclusion.split(/(?<=[.?!])\s+/)[0]))); }
  if (step) nodes.push(li("", "계획 단계", rich(step.action)));
  else if (V.plan) nodes.push(li("", "현재 계획", V.plan.steps.map((s, i) => h("div", null, `${i + 1}. `, rich(s.action)))));
  if (act) {
    const g = { BLOCK: ["stop", "Pablo가 실행을 막았습니다"], WARN: ["warn", "Pablo가 확인을 요청했습니다"], ALLOW: ["", "Pablo의 검토를 통과했습니다"] }[act.verdict] || ["", ""];
    nodes.push(li(g[0], "제안된 작업", meaning(act.text), preview(act.text), h("div", null, g[1]),
      act.problems.map(x => korean(x) ? h("div", null, "· ", rich(x)) : null), tech(act.text, ...act.problems.filter(x => !korean(x)))));
    if (act.decision) nodes.push(li("", "사용자 결정", decided(act)));
    act.runs.forEach(r => nodes.push(li("", "결과", done(r), r.alignment ? h("div", null, ALIGN[r.alignment] || r.alignment) : null)));
  }
  simple(p, act ? (act.verdict === "BLOCK" ? "이 작업이 막힌 과정" : "이 작업을 판단한 과정") : step ? "이 단계가 계획에 들어간 과정" : "이 판단이 나온 과정", h("ol", { class: "tl" }, nodes));
}

// C3: the comparison table, wide; a cell's [n] opens that paper's page here and ← comes back to the table
function matrixView(p, st) {
  document.body.classList.add("wide");
  p.append(h("div", { class: "phead" },
      navs(),
      h("h2", null, "비교표"), xbtn()),
    h("div", { id: "pbody" }, matrix(st.c, true)));
}

// ---- A3 code (desktop): a work-folder file, read-only, line numbers, the lines the audit or a card names marked ----------
// st: {task, where: "config.yaml:5" | a path, line?: the line Pablo found it on (overrides where's), note?}. No editing here:
// changes go through the agent (Guard) or the user's own editor ("VS Code에서 열기").
function codeView(p, st) {
  document.body.classList.add("code");
  p.dataset.live = "LOADING";
  const info = h("div", { class: "info" }, "작업 폴더의 파일을 읽는 중…"), name = h("b", null, st.where);
  const open = how => pabloHost.openFile(st.task, st.where, st.line || null, how).then(r => {
      if (hist[hi] === st) info.textContent = { vscode: "VS Code로 열었습니다.", app: "기본 프로그램으로 열었습니다.", folder: "파일이 있는 폴더를 열었습니다." }[r] || ""; },
    e => { if (hist[hi] === st) { info.className = "info broken"; info.textContent = "⚠ " + fail(e); } });
  p.append(h("div", { class: "phead" },
      navs(),
      h("div", { class: "url", title: st.where }, urlIco("file", "📄 "), name),
      h("button", { class: "link open", "data-open": "vscode", on: () => open("vscode") }, "VS Code에서 열기"),
      h("button", { class: "link open", "data-open": "folder", on: () => open("folder") }, "폴더에서 보기"), xbtn()),
    info, h("div", { id: "pbody", class: "code" }));
  pabloHost.readFile(st.task, st.where, st.line || null, st.expect || null).then(f => {
    if (hist[hi] !== st) return;
    const rs = st.line ? [[st.line, st.line]] : f.ranges || [], box = $("pbody");  // "a.py:6,15" marks both
    name.textContent = f.path + (rs.length ? ":" + rs.map(([a, b]) => b > a ? `${a}-${b}` : a).join(",") : "");
    const src = box.appendChild(h("div", { class: "src" }, f.lines.map((l, i) => { const n = f.first + i;
      return h("div", { class: "ln" + (rs.some(([a, b]) => n >= a && n <= b) ? " on" : ""), "data-n": n }, h("span", { class: "n" }, n), h("span", { class: "t" }, l)); })));
    const on = src.querySelector(".ln.on");
    info.textContent = [`작업 폴더 · 읽기 전용 · ${f.total}줄`, rs.length && !on ? `이 파일에는 ${rs[0][0]}줄이 없습니다` : null, st.note,
      f.truncated ? `긴 파일이라 ${f.first}–${f.first + f.lines.length - 1}줄만 보여 줍니다` : null].filter(Boolean).join(" · ");
    if (rs.length && !on) info.className = "info broken";
    // ⑤ what the audit saw on this line, checked again now: gone or moved since -> said, the row's verdict may be old
    const was = String(st.expect || "").split("\n")[0].slice(0, 60);
    if (f.still === "not_found" || f.still === "moved") {
      info.className = "info broken"; p.dataset.still = f.still;
      info.prepend(`⚠ 점검 때 이 자리에 있던 "${was}"이(가) 지금은 ${f.still === "moved" ? "다른 줄에 있습니다" : "없습니다"}. 점검 뒤 파일이 바뀌었습니다. `,
        reAudit && V && V.task.id === st.task ? h("button", { class: "link", "data-reaudit": "1", on: () => reAudit(st.task) }, "다시 점검") : "", " · ");
    }
    if (on) box.scrollTop += on.getBoundingClientRect().top - box.getBoundingClientRect().top - box.clientHeight / 3;
    p.dataset.live = on ? "FOUND" : "OPEN";
  }, e => { if (hist[hi] !== st) return; p.dataset.live = "ERROR"; info.className = "info broken"; info.textContent = "⚠ " + fail(e); });
}

// ---- source: captured snapshot (in panel) + the original page with a text fragment (new tab) ---------------------
function blocksOf(src) {
  const d = src.display || {}, n = src.text.length, b = d.blocks;
  const sorted = xs => Array.isArray(xs) && xs.every(([s, e], i) => s < e && (!i || xs[i - 1][1] <= s));
  if (Array.isArray(b) && b.length && sorted(b.map(x => x.slice(1))) && b[0][1] >= 0 && b.at(-1)[2] <= n)
    return [b, sorted(d.code) ? d.code : []];
  const out = [];  // no display file: plain 400-char chunks of the snapshot
  for (let i = 0; i < n; i += 400) out.push(["p", i, Math.min(n, i + 400)]);
  return [out, []];
}
// browser-native scroll + highlight on the live page (#:~:text=prefix-,exact,-suffix); words cut at the edges are dropped
function fragment(src, a) {
  const enc = s => encodeURIComponent(s).replace(/-/g, "%2D"), W = 40;
  const pre = src.text.slice(Math.max(0, a.start - W), a.start).trim().split(/\s+/).slice(a.start > W ? 1 : 0).slice(-3).join(" ");
  const suf = src.text.slice(a.end, a.end + W).trim().split(/\s+/);
  if (a.end + W < src.text.length) suf.pop();
  const s = suf.slice(0, 3).join(" ");
  return src.url.split("#")[0] + "#:~:text=" + (pre ? enc(pre) + "-," : "") + enc(a.exact) + (s ? ",-" + enc(s) : "");
}
// desktop host (window.pabloHost): the live page in a <webview>, located by exact + prefix/suffix (desktop/locate.js).
// Off anchors (STALE / UNRESOLVED) start on the snapshot; a failed live locate falls back to it, keeping why in st.failed.
const FALLBACK = "현재 원문에서 근거 위치를 복원하지 못했습니다. 캡처 당시 원문을 보여드립니다.";
const PDF_FALLBACK = "PDF에서 근거 위치를 표시하지 못했습니다. PDF에서 추출한 본문을 보여드립니다.";
function source(p, st) {
  const a = M.anchors[st.e], src = M.sources[a.source];
  if (src.kind === "pdf" && window.pabloHost && !st.failed && src.intact) return pdfPanel(p, st, a, src);
  const ok = src.intact && src.text.slice(a.start, a.end) === a.exact, live = fragment(src, a);
  const inApp = window.pabloHost && !st.failed && (st.live || !["STALE", "UNRESOLVED"].includes(a.status));
  p.dataset.live = inApp ? "LOADING" : st.failed || "SNAPSHOT";
  const info = inApp ? h("div", { class: "info" }, "현재 원문 · 근거 위치를 찾는 중…")
    : h("div", { class: "info " + (st.failed ? "STALE" : ok ? a.status : "broken"), title: src.hash },
      st.failed ? "⚠ " + (src.kind === "pdf" ? PDF_FALLBACK : FALLBACK) : [`캡처한 원문 · ${day(src.captured_at)} · `,
        ok ? (a.status === "VALID" ? "✓ " : "⚠ ") + a.message : "⚠ 캡처본이 이 근거와 맞지 않아 표시하지 않습니다."], " ",
      window.pabloHost && !st.failed ? h("button", { class: "link", on: () => show({ mode: "source", e: st.e, live: true }) }, "현재 원문 열기")
        : h("a", { href: live, target: "_blank", rel: "noopener noreferrer" }, "원본에서 보기 ↗"));
  p.append(h("div", { class: "phead" },
      navs(),
      h("div", { class: "url", title: src.url }, urlIco("lock", "🔒 "), h("b", null, src.title), " · ", host(src.url)),
      h("a", { class: "ext", href: live, target: "_blank", rel: "noopener noreferrer", title: "원본 페이지에서 이 문장 보기" }, ico("external", 14)), xbtn()),
    info, inApp ? h("div", { id: "pbody", class: "live" })
      : h("div", { id: "pbody" }, h("article", { id: "doc" }, h("div", { class: "title" }, src.title))));
  if (inApp) {
    const wv = $("pbody").appendChild(h("webview", { src: src.url.split("#")[0], partition: "pablo-source" }));
    let done = false;
    const end = r => { if (done || hist[hi] !== st || !wv.isConnected) return; done = true; st.result = r;
      if (r.status === "FOUND" && r.visible) { p.dataset.live = "FOUND"; info.textContent = "✓ 현재 원문에서 근거 문장을 찾아 표시했습니다."; }
      else { hist[hi] = { mode: "source", e: st.e, failed: r.status === "FOUND" ? "HIDDEN" : r.status }; show(hist[hi], false); } };
    wv.addEventListener("did-finish-load", () => pabloHost.locate(wv.getWebContentsId(),
      { exact: a.exact, prefix: a.prefix, suffix: a.suffix }).then(end, () => end({ status: "ERROR" })), { once: true });
    wv.addEventListener("did-fail-load", ev => ev.isMainFrame && ev.errorCode !== -3 && end({ status: "LOAD_FAILED" }));
    setTimeout(() => end({ status: "TIMEOUT" }), 20000);
    return;
  }
  if (!ok) return;
  const [blocks, code] = blocksOf(src), doc = $("doc"), nodes = [];
  let c = 0, focus = null;
  for (const [kind, s, e] of blocks) {
    const hit = s < a.end && a.start < e;
    const el = doc.appendChild(h("div", { class: `b ${kind}${hit ? " shown" : ""}` }));
    if (hit && !focus) focus = el;
    let q = s;
    const put = (end, wrap) => { if (end <= q) return;
      const t = document.createTextNode(src.text.slice(q, end));
      (wrap ? el.appendChild(document.createElement("code")) : el).appendChild(t); nodes.push([t, q]); q = end; };
    while (c < code.length && code[c][1] <= s) c++;
    for (let k = c; k < code.length && code[k][0] < e; k++) { put(Math.max(code[k][0], s)); put(Math.min(code[k][1], e), true); }
    put(e);
  }
  const at = (off, isEnd) => { for (const [n, s] of nodes) if (isEnd ? off <= s + n.length : off < s + n.length) return [n, Math.max(0, off - s)];
    const [n] = nodes.at(-1); return [n, n.length]; };
  const r = new Range(), [sn, so] = at(a.start, false), [en, eo] = at(a.end, true);
  r.setStart(sn, so); r.setEnd(en, eo);
  CSS.highlights.set("evidence", new Highlight(r));
  const pb = $("pbody");
  pb.scrollTop += r.getBoundingClientRect().top - pb.getBoundingClientRect().top - pb.clientHeight / 3;
}

// ---- M3.3 PDF panel (desktop): the captured PDF (pablo://source/SRCn.pdf) rendered by pdf.js, evidence boxed on its page.
// The quote is found in pdf.js's own text items with the same key as pdf.py (no whitespace, no hyphens, NFKC); a quote
// that repeats on the page is told apart by its stored prefix/suffix, a tie fails closed. Boxes: the matched part of each
// text item, one union per line (a table row = its cells, never the whole table). Failures fall back to the snapshot.
const PDFJS = "pablo://pdfjs/", pdfs = {};
let pdfjs = null;
async function pdfLib() {  // fake worker: a pablo:// Worker is cross-origin for this file:// page
  if (!pdfjs) { globalThis.pdfjsWorker = await import(PDFJS + "build/pdf.worker.mjs"); pdfjs = await import(PDFJS + "build/pdf.mjs"); }
  return pdfjs;
}
function keyed(text) {  // -> [key, idx]: key[i] comes from text[idx[i]] (pdf.key in Python)
  let k = ""; const idx = [];
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (/\s/.test(ch) || "-\u00ad\u2010\u2011".includes(ch)) continue;
    const n = ch.normalize("NFKC"); k += n; for (let j = 0; j < n.length; j++) idx.push(i);
  }
  return [k, idx];
}
function findIn(items, a) {
  const T = items.map(i => i.str).join(""), [k, idx] = keyed(T), q = keyed(a.exact)[0];
  const pk = keyed(a.prefix)[0], sk = keyed(a.suffix)[0], hits = [];
  for (let i = q ? k.indexOf(q) : -1; i >= 0; i = k.indexOf(q, i + 1)) hits.push(i);
  if (!hits.length) return { status: "NOT_FOUND" };
  const score = i => (k.slice(Math.max(0, i - pk.length), i) === pk) + (k.slice(i + q.length, i + q.length + sk.length) === sk);
  const best = Math.max(...hits.map(score)), top = hits.filter(i => score(i) === best);
  if (top.length > 1) return { status: "AMBIGUOUS" };
  return { status: "FOUND", start: idx[top[0]], end: idx[top[0] + q.length - 1] + 1 };
}
function boxes(items, s, e, vp, L) {
  const out = []; let at = 0;
  for (const it of items) {
    const n = it.str.length, a0 = at; at += n;
    if (!n || at <= s || a0 >= e) continue;
    const tx = L.Util.transform(vp.transform, it.transform), fh = Math.hypot(tx[2], tx[3]), w = it.width * vp.scale;
    const r = { l: tx[4] + w * (Math.max(s, a0) - a0) / n, r: tx[4] + w * (Math.min(e, at) - a0) / n, t: tx[5] - fh, b: tx[5] + fh * 0.25 };
    const line = out.find(o => Math.abs(o.t - r.t) < fh / 2);
    if (line) Object.assign(line, { l: Math.min(line.l, r.l), r: Math.max(line.r, r.r), t: Math.min(line.t, r.t), b: Math.max(line.b, r.b) });
    else out.push(r);
  }
  return out;
}
// ⑩ (desktop) a paper of the task opened without a citation (its name in 📎 자료, 기준 panel): read it, pick a sentence
function paper(p, st) {
  const src = (M.papers || {})[st.src];
  if (!src || !src.intact || !src.pages) return simple(p, "PDF", h("p", { class: "muted" }, "이 PDF의 캡처본을 열 수 없습니다."));
  return pdfPanel(p, st, null, src);
}
async function pdfPanel(p, st, a, src) {
  const t0 = performance.now(), n = st.page || (a ? a.page : 1), sid = a ? a.source : st.src;
  const turn = d => show({ ...st, page: n + d });
  document.body.classList.add("pdf");
  p.dataset.live = "LOADING";
  const info = h("div", { class: "info", title: src.hash }, `캡처한 PDF · ${day(src.captured_at)} · ${a ? "근거 위치를 찾는 중…" : "여는 중…"}`);
  p.append(h("div", { class: "phead" },
      navs(),
      h("div", { class: "url", title: src.url }, urlIco("file", "📄 "), h("b", null, src.title), ` · PDF`),
      h("button", { class: "nav", title: "이전 쪽", disabled: n <= 1, on: () => turn(-1) }, turned("chevron-right", 180, 14)),
      h("span", { class: "pnum" }, `${n} / ${src.pages}`),
      h("button", { class: "nav", title: "다음 쪽", disabled: n >= src.pages, on: () => turn(1) }, ico("chevron-right", 14)), xbtn()),
    info, h("div", { id: "pbody", class: "pdf" }));
  const fail = why => { if (hist[hi] !== st) return;
    if (!a) { p.dataset.live = "ERROR"; info.textContent = "⚠ PDF를 열지 못했습니다."; return; }
    hist[hi] = { mode: "source", e: st.e, failed: why }; show(hist[hi], false); };
  try {
    const L = await pdfLib();
    const doc = await (pdfs[sid] = pdfs[sid] || L.getDocument({ url: "pablo://source/" + src.file,
      standardFontDataUrl: PDFJS + "standard_fonts/", cMapUrl: PDFJS + "cmaps/", wasmUrl: PDFJS + "wasm/" }).promise);
    const pg = await doc.getPage(n), box = $("pbody");
    if (hist[hi] !== st || !box) return;
    const vp = pg.getViewport({ scale: (box.clientWidth - 24) / pg.getViewport({ scale: 1 }).width }), dpr = devicePixelRatio || 1;
    const cv = h("canvas", { width: Math.floor(vp.width * dpr), height: Math.floor(vp.height * dpr), style: `width:${vp.width}px;height:${vp.height}px` });
    const sheet = box.appendChild(h("div", { class: "pg", style: `width:${vp.width}px;--total-scale-factor:${vp.scale};--scale-round-x:1px;--scale-round-y:1px` }, cv));
    await pg.render({ canvasContext: cv.getContext("2d"), viewport: vp, transform: dpr === 1 ? null : [dpr, 0, 0, dpr, 0, 0] }).promise;
    if (hist[hi] !== st) return;
    // ⑩ the page's text over the canvas (selectable); a sentence picked there can become a reproduction condition
    const tc = await pg.getTextContent(), layer = sheet.appendChild(h("div", { class: "textLayer" }));
    await new L.TextLayer({ textContentSource: tc, container: layer, viewport: vp }).render().catch(e => console.error("[pdf] text", e));
    if (hist[hi] !== st) return;
    const picks = picker(p, box, layer, sid, n);
    if (!a) { p.dataset.live = "PAPER"; info.textContent = `캡처한 PDF · ${n}쪽` + (picks ? " · 문장을 끌어서 고르면 재현 조건으로 더할 수 있습니다." : ""); return; }
    if (n !== a.page) { p.dataset.live = "PAGE"; info.textContent = `캡처한 PDF · ${n}쪽 · 근거는 ${a.page}쪽에 있습니다.`; return; }
    const items = tc.items.filter(i => "str" in i), r = findIn(items, a);
    if (r.status !== "FOUND") return fail(r.status);
    const bs = boxes(items, r.start, r.end, vp, L);
    if (!bs.length) return fail("HIDDEN");
    bs.forEach(b => sheet.append(h("div", { class: "hl", style: `left:${b.l}px;top:${b.t}px;width:${b.r - b.l}px;height:${b.b - b.t}px` })));
    box.scrollTop = Math.max(0, Math.min(...bs.map(b => b.t)) - box.clientHeight / 3);
    p.dataset.ms = Math.round(performance.now() - t0); p.dataset.live = "FOUND";
    info.textContent = `✓ 캡처한 PDF ${n}쪽에서 근거를 찾아 표시했습니다.`;
  } catch (err) { console.error("[pdf]", err); fail("ERROR"); }
}
// ⑩ (desktop) a sentence picked on a page of the task's paper -> 재현 조건으로 더하기: its kind, what it says, its value.
// Pablo anchors the sentence on that page like an extracted condition (main.js: only the 주 논문; not found -> refused).
function picker(p, box, layer, sid, n) {
  const d = V && (M.desk || {})[V.task.id] || {};
  if (!window.pabloHost || !pabloHost.condition || !(d.papers || []).some(x => x.id === sid && x.kind !== "web")) return false;
  const bar = p.appendChild(h("div", { id: "pick", hidden: true })), task = V.task.id;
  let form = false;
  const offer = () => {
    if (form) return;
    const sel = getSelection(), q = sel.toString().replace(/\s+/g, " ").trim();
    if (!q || !sel.rangeCount || !layer.contains(sel.getRangeAt(0).commonAncestorContainer)) { bar.hidden = true; return; }
    bar.hidden = false;
    bar.replaceChildren(h("div", { class: "row" }, h("span", { class: "q" }, `“${q.length > 90 ? q.slice(0, 90) + "…" : q}”`),
      q.length > 600 ? h("span", { class: "muted" }, "한 문장만 골라 주세요.")
        : h("button", { class: "pill on", "data-add-spec": "1", on: () => open(q) }, "📋 재현 조건으로 더하기")));
  };
  const open = q => {
    form = true;
    const cat = h("select", { "data-cat": "1", title: "조건의 종류" }, h("option", { value: "" }, "종류 고르기"),
      Object.entries(SPEC).map(([k, v]) => h("option", { value: k }, v)));
    cat.addEventListener("change", () => { add.disabled = !cat.value; });
    // a condition already there: the same kind and value, or the same sentence (one contains the other) of this paper
    const kq = keyed(q)[0], similar = () => { const v = val.value.trim().toLowerCase();
      return Object.values(M.views[task].checks).find(c => c.spec && !c.spec.missing && c.state !== "waived" && (
        (v && c.spec.category === cat.value && String(c.spec.value || "").toLowerCase() === v) ||
        c.evidence.some(e => { const a = M.anchors[e], ka = a && a.source === sid ? keyed(a.exact)[0] : "";
          return ka.length >= 12 && (ka.includes(kq) || kq.includes(ka)); }))); };
    let sure = false;
    const say = h("input", { "data-statement": "1", value: q.slice(0, 200), placeholder: "조건을 한 줄로 (예: 검색 단계의 top-k는 5)" });
    const val = h("input", { "data-value": "1", placeholder: "값 (선택, 예: 5)" }), note = h("span", { class: "muted", "data-pick-note": "1" });
    const add = h("button", { class: "pill on", "data-add-ok": "1", disabled: true, on: () => {
      if (!say.value.trim()) return say.focus();
      const same = !sure && similar();
      if (same) return note.replaceChildren("비슷한 조건이 이미 있습니다: ", h("span", { "data-similar": same.id }, (SPEC[same.spec.category] || same.spec.category) + " · ", fact(same)),
        " · ", h("button", { class: "link", "data-anyway": "1", on: () => { sure = true; add.click(); } }, "그래도 더하기"));
      add.disabled = true; note.textContent = "원문에서 위치를 찾는 중…";
      pabloHost.condition(task, "add", { src: sid, page: n, quote: q, category: cat.value, statement: say.value.trim(), value: val.value.trim() }).then(r => {
        Object.assign(M.anchors, r.anchors); Object.assign(M.sources, r.sources); M.views[task].checks[r.check.id] = r.check;
        form = false; getSelection().removeAllRanges();
        bar.replaceChildren(h("span", { "data-added": r.check.id }, "✓ 재현 조건에 더했습니다. 에이전트와 재현 점검이 이 조건도 봅니다."));
        echo(task, { role: "spec-add", check: r.check.id });
        return refresh();
      }, e => { add.disabled = false; note.textContent = fail(e); }); } }, "더하기");
    const cancel = h("button", { class: "link", on: () => { form = false; bar.hidden = true; } }, "취소");
    bar.replaceChildren(h("div", { class: "q" }, `“${q}”`), h("div", { class: "row" }, cat, say, val),
      h("div", { class: "row" }, add, cancel, note));
    say.focus();
  };
  box.addEventListener("mouseup", () => setTimeout(offer, 0));
  return true;
}

// Esc closes a floating box first (설정, the model menu, the source card), else the right column; a click outside the
// model menu or the source card closes it (QA 10/26: they only closed from their own button)
const floating = () => [$("settings"), document.querySelector(".composer > .mmenu:not([hidden])"), document.querySelector("#srccard:not([hidden])")].find(Boolean);
addEventListener("keydown", e => { if (e.key !== "Escape" || e.isComposing) return;
  const f = floating(); if (!f) return close();
  if (f.id === "settings") f.remove(); else if (f.id === "srccard") document.querySelector(".statechip").click(); else f.hidden = true; });
addEventListener("mousedown", e => {
  const m = document.querySelector(".composer > .mmenu:not([hidden])"), c = document.querySelector("#srccard:not([hidden])");
  if (m && !e.target.closest(".mmenu, .modelbtn")) m.hidden = true;
  if (c && !e.target.closest("#srccard, .statechip")) document.querySelector(".statechip").click();
}, true);

// ---- M4.0/M4.1 desktop host only: ChatGPT connection + composer -> persistent Codex app-server thread (desktop/) ----
if (window.pabloHost && pabloHost.chat) {
  const box = document.querySelector("#chat > .composer"), [inp, btn] = box.querySelectorAll("input, button");
  const st = box.insertBefore(h("small", { class: "muted", id: "agent" }), btn);
  const pick = box.insertBefore(h("select", { id: "model", title: "모델" }), st);  // the ChatGPT account's catalog (/v1/models, visibility "list")
  pick.addEventListener("change", () => pabloHost.setModel(pick.value));
  // team review: the model is a quiet text button with a menu; the <select> stays (hidden) and carries the same events.
  // Both come after the send button in the DOM (the first button stays send / stop) and CSS orders them on screen.
  const mbtn = box.appendChild(h("button", { class: "modelbtn", type: "button", title: "모델", hidden: true }));
  const mmenu = box.appendChild(h("div", { class: "mmenu", hidden: true }));
  const mlabel = () => { const o = pick.options[pick.selectedIndex]; mbtn.replaceChildren(o ? o.textContent : "모델", ico("chevron-down", 12)); };
  // A2: where a new message is recorded, as the stage pill (it used to be the end of the placeholder)
  const hint = box.appendChild(h("span", { class: "stagehint", hidden: true }));
  mbtn.addEventListener("click", () => { mmenu.hidden = !mmenu.hidden; if (mmenu.hidden) return; mmenu.textContent = "";
    [...pick.options].forEach(o => mmenu.append(h("button", { class: "mopt" + (o.value === pick.value ? " on" : ""), type: "button",
      on: () => { pick.value = o.value; pick.dispatchEvent(new Event("change")); mmenu.hidden = true; } }, o.textContent))); });
  pick.addEventListener("change", mlabel);
  const models = () => pabloHost.models().then(r => {
    pick.textContent = ""; r.models.forEach(m => pick.append(h("option", { value: m.slug }, m.name))); pick.value = r.model || ""; mlabel();
  });
  const acct = $("chat").insertBefore(h("div", { id: "acct" }), box);  // sign-in card, then a one-line connection status
  const LABEL = { Connecting: "연결 중…", Ready: "준비됨", Thinking: "생각 중…", Error: "오류" };
  let out = null, agentSt = "Connecting", authSt = { state: "signed_out" }, turning = false, stopping = false;  // turning: an agent turn (a PDF ask cannot be stopped)
  const gate = () => {
    const on = authSt.state === "connected", running = on && turning && agentSt === "Thinking";
    st.textContent = ""; if (on) st.append(agentSt === "Thinking" ? art("think") : "", stopping ? "중지하는 중…" : LABEL[agentSt] || agentSt); box.dataset.agent = agentSt;
    pick.hidden = !on || !pick.options.length; pick.disabled = agentSt === "Thinking";
    mbtn.hidden = pick.hidden; mbtn.disabled = pick.disabled; if (mbtn.hidden || mbtn.disabled) mmenu.hidden = true;
    inp.disabled = !on || !V || (agentSt !== "Ready" && agentSt !== "Error");  // Error: the next send restarts app-server
    btn.disabled = running ? stopping : inp.disabled;  // while the agent works, the send button is 중지
    btn.replaceChildren(ico(running ? "stop" : "arrow-up", 16)); btn.title = running ? "중지" : "보내기"; btn.setAttribute("aria-label", btn.title);
    box.dataset.running = running ? "1" : "";
    inp.placeholder = !on ? "ChatGPT에 연결하면 대화할 수 있습니다" : !V ? "새 작업을 만들면 대화할 수 있습니다" : "Pablo에게 물어보세요…";
    hint.hidden = !on || !V || !box.dataset.stage;
    hint.replaceChildren(...(hint.hidden ? [] : ["이 메시지는 ", h("span", { class: "tg stage" }, h("span", { class: "dot" }), box.dataset.stage), " 단계로 기록"]));
  };
  const status = (s, err) => { agentSt = s; st.title = err || ""; gate(); };
  const link = (text, on) => h("button", { class: "link", on }, text);
  // ⑤ a PC without PowerShell 7: Codex runs the agent's commands in Windows PowerShell 5.1, which reads 한글 and symbols
  // in a BOM-less UTF-8 file wrongly. Pablo tells the agent to read as UTF-8; this says so once, with how to install,
  // after the account is connected (review: nothing works before sign-in, so the sign-in card comes alone first)
  const shellBox = $("chat").insertBefore(h("div", { id: "shell-note" }), acct);
  const shellNote = () => { const host = M.host || {}; shellBox.textContent = "";
    if (host.shell !== "powershell" || host.noticed || authSt.state !== "connected") return;
    shellBox.append(h("div", { class: "call", "data-shell": "5.1" }, h("p", { class: "head" }, "한글이 든 코드를 정확히 읽으려면 PowerShell 7이 필요합니다"),
      h("p", null, "이 PC에는 Windows PowerShell 5.1만 있어, 에이전트가 한글 주석이나 λ 같은 기호를 깨진 채 읽을 수 있습니다. "
        + "Pablo가 에이전트에게 UTF-8로 읽으라고 일러 두었지만, 지키지 않으면 재현 점검의 판정이 틀릴 수 있습니다."),
      h("p", null, "설치: 명령 프롬프트에서 ", h("code", null, "winget install Microsoft.PowerShell"), " · ",
        h("a", { href: "https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows", target: "_blank", rel: "noopener noreferrer" }, "설치 방법 ↗"),
        ". 설치한 뒤 Pablo를 다시 시작하세요."),
      pabloHost.noticeSeen ? h("p", null, link("알겠습니다", () => pabloHost.noticeSeen("shell").then(() => refresh()))) : null)); };
  function account(a) {
    const hello = a.state === "connected" && (authSt.state === "signing_in" || authSt.state === "verifying");  // just signed in
    authSt = a; acct.dataset.state = a.state; acct.textContent = "";
    const err = a.error ? h("p", { class: "muted" }, a.error) : null;
    if (hello) { const x = h("div", { class: "hello" }, art("waving", "pose"), h("p", null, h("b", null, "ChatGPT에 연결되었습니다."))); acct.append(x); setTimeout(() => x.remove(), 8000); }
    if (a.state === "connected") acct.append(h("p", { class: "muted" }, art("head", "ico"), "ChatGPT · 연결됨 · 플랜 사용 가능 · ", link("연결 해제", () => pabloHost.logout()),
      pabloHost.setUi ? [" · ", h("button", { class: "link", "data-settings": "1", on: settings }, "설정")] : null));
    else if (a.state === "signing_in") acct.append(h("div", { class: "call" }, h("p", { class: "head" }, "브라우저에서 ChatGPT 로그인을 마치세요."),
      h("p", null, link("취소", () => pabloHost.cancelLogin()))));
    else if (a.state === "verifying") acct.append(h("div", { class: "call" }, h("p", { class: "head" }, "ChatGPT 플랜 사용 권한을 확인하는 중…")));
    else acct.append(h("div", { class: "call" }, h("p", { class: "head" }, "ChatGPT 계정을 연결하세요"), err,
      h("p", null, h("button", { class: "pill on", id: "signin", on: () => pabloHost.login() }, "ChatGPT로 계속하기"),
        a.state === "error" ? [" ", link("연결 해제", () => pabloHost.logout())] : null)));
    gate(); shellNote();
  }
  const scroll = () => { $("log").scrollTop = $("log").scrollHeight; };
  pabloHost.onAuth(account);
  pabloHost.onAgent(ev => {
    if (ev.type === "model") { pick.value = ev.model; mlabel(); }
    if (ev.type === "status") {
      if (ev.status === "Ready") models().then(gate);  // after a restart or another sign-in the list may change
      // a message is on its way (Pablo prepares it, or app-server restarts for a fresh token first): stay Thinking until done
      if (turning && (ev.status === "Ready" || ev.status === "Connecting")) return;
      status(ev.status, ev.error);
      if (ev.status === "Error" && ev.error && authSt.state === "connected") live(talk).append(msg("Pablo", null, h("div", { class: "call block" }, h("p", { class: "head" }, "⚠ " + ev.error)))), scroll();
    } else if (ev.type === "delta" && out) { out.textContent += ev.text; scroll(); }
    else if (ev.type === "done") {
      refresh(); turning = stopping = false; busy = null; gate();
      if (out && ev.status === "interrupted") out.after(h("p", { class: "muted", "data-stopped": "1" }, "중지했습니다."));
      const lg = ev.logged;  // the keys main just wrote: the turn's messages get their tag row now, not after the next state read
      if (lg && V && lg.task === V.task.id && lives[lg.task]) {
        if (lg.user) tagLive([...lives[lg.task].querySelectorAll(":scope > .msg.user")].at(-1), "user", lg.user);
        if (out) tagLive(out.closest(".msg"), "agent", lg.agent);
      }
      if (out) { out.title = `첫 토큰 ${ev.first ?? "-"} ms · 전체 ${ev.total} ms`; out = null; }
      if (ev.retry) setTimeout(() => { const b = link("다른 모델로 다시 시도", () => { b.remove(); stream(talk); pabloHost.retry().catch(e => { status("Error", e.message); out = null; }); });
        live(talk).append(msg("Pablo", null, h("p", null, b))); scroll(); });  // after the Error card
    } else if (ev.type === "guard") { live(ev.task).append(msg("Pablo", null, guard(ev))); scroll(); refresh(); }
    else if (ev.type === "audit") {
      const p = live(ev.task).querySelector("[data-auditing]"), card = audited(ev);
      p ? p.replaceWith(card) : live(ev.task).append(msg("Pablo", null, card)); scroll(); refresh();
    }
    else if (ev.type === "changes") { live(ev.task).append(msg("Pablo", null, changed(ev, ev.task))); scroll(); refresh(); }
    else if (ev.type === "intent") {  // right under the user's message, before the reply that is already streaming
      const s = [...live(ev.task).querySelectorAll(".stream")].at(-1), m = noted({ ...ev, live: true });
      s ? s.closest(".msg").before(m) : live(ev.task).append(m); refresh();
    }
    else if (ev.type === "review") {  // PostReview of a WARN/BLOCK action, under its card (ALLOW has no card: stays silent)
      const card = Object.values(lives).map(l => l.querySelector(`[data-act="${CSS.escape(ev.act)}"]`)).find(Boolean);
      if (card) card.append(h("p", { class: "muted", "data-review": ev.alignment || "" },
        "검토: " + (ALIGN[ev.alignment] || (ev.executed ? "실행했습니다" : "실행하지 않았습니다"))));
      refresh();  // Plan / 왜? follow the review without a reload
    }
  });
  // M4.2 Guard on the agent's actions: ALLOW stays silent; WARN asks, BLOCK and failures explain (no rule/action ids)
  const HEAD = { WARN: "⚠ 이 작업은 현재 기준과 충돌할 가능성이 있습니다.", BLOCK: "⚠ 이 작업은 현재 기준과 충돌해 실행하지 않았습니다.",
                 ERROR: "⚠ 작업을 실행하지 못했습니다." };
  function guard(ev) {
    // "막음" heads Guard's own BLOCK only (.lock); a command that failed shares the grey box, not the word (rehearsal 10/27)
    const card = h("div", { class: "call" + (ev.verdict === "WARN" ? "" : ev.verdict === "BLOCK" ? " block lock" : " block"), "data-verdict": ev.verdict, "data-act": ev.act || "" },
      h("p", { class: "head" }, HEAD[ev.verdict]), h("p", null, "제안된 작업: ", h("b", null, meaning(ev.text))),
      ev.verdict === "ERROR" ? null : preview(ev.text, ev.detail), ev.verdict === "ERROR" ? null : current(ev.text, ev.task),
      reason(ev.reason, ev.verdict === "BLOCK"), h("p", { class: "muted crit" }), tech(ev.text, korean(ev.reason) ? null : ev.reason),
      ev.act ? h("p", null, h("button", { class: "link", on: () => show({ mode: "trace", act: ev.act }) }, "왜 그런가요?")) : null);
    if (ev.verdict !== "WARN") return card;
    const row = h("p", null), answer = yes => pabloHost.decide(ev.id, yes)
      .then(() => { row.textContent = yes ? "진행했습니다." : "취소했습니다."; }, () => { row.textContent = "이미 끝난 요청입니다."; });
    row.append(h("button", { class: "pill on", "data-answer": "proceed", on: () => answer(true) }, "진행"), " ",
      h("button", { class: "pill", "data-answer": "cancel", on: () => answer(false) }, "취소"));
    card.insertBefore(row, card.querySelector("details"));
    return card;
  }
  let talk = null;  // the task whose turn is running; its answer stays in that task's chat
  const stream = t => { out = h("p", { class: "stream", style: "white-space:pre-wrap" }); live(t).append(msg("Pablo", null, out)); scroll(); };
  // Thinking (and 중지) from the moment it is sent: Pablo records the message's criteria and the brief before the agent starts
  const chat = (text, t) => { talk = busy = t; turning = true; stream(t); status("Thinking");
    pabloHost.chat(text, t).catch(e => { turning = false; busy = null; status("Error", fail(e)); out = null; }); };
  const stop = () => { stopping = true; gate(); pabloHost.stop().then(ok => { if (!ok) { stopping = false; gate(); } }); };
  // M5.1 one input box: the task's material and folder decide where a message goes; both -> the user picks, neither -> say so
  const send = async () => {
    const text = inp.value.trim(); if (!text || inp.disabled) return;
    inp.value = ""; talk = V.task.id;
    live(talk).append(msg("You", new Date().toISOString(), h("p", null, text)));
    if (!M.desk) { inp.disabled = true; await refresh(); gate(); }  // the task's folder / PDF come with the first state read
    const d = (M.desk || {})[talk] || {}, pdf = (d.papers || []).length > 0 || (!M.desk && M.pdf), dir = !!d.folder;
    if (pdf && !dir) return ask(text, talk);
    if (dir && !pdf) return chat(text, talk);
    if (pdf && dir) return (d.route === "ask" ? ask : chat)(text, talk);  // both: the task's 보낼 곳 (agent by default)
    const t = talk, row = h("p", null, link("📎 PDF 추가", () => pickPdfs()), " · ", link("📁 작업 폴더 선택", () => attach("pickFolder")));
    live(t).append(msg("Pablo", null, h("div", { class: "call", "data-route": "none" }, h("p", { class: "head" }, "먼저 자료나 작업 폴더를 정해 주세요."), row))); scroll();
  };
  // ---- M5.1 live state: after every Guard / review / answer the panels read the same records again (no view rebuild) ----
  let q = Promise.resolve();
  refresh = to => (q = q.then(() => pabloHost.state()).then(m => {
    const open = hi >= 0 && document.body.classList.contains("panel") ? hist[hi] : null, firstDesk = !M.desk && !!m.desk;
    M = m; shellNote(); webFonts();
    if (to === undefined && !V && $("goal")) return sidebar();  // the new task form stays
    if (to !== undefined || !V || !M.views[V.task.id]) return (select(to || (V && V.task.id)), gate());
    V = M.views[V.task.id]; V.task.at = (M.tasks.find(t => t.id === V.task.id) || {}).at;
    sidebar(); header(); tools(); gate(); finish();
    if (firstDesk && !open) panelBack();  // the app reopened this task before it knew the task's panel (QA 10/26, D4)
    document.querySelectorAll("#log [data-audit]").forEach(b => b._c && aged(b));  // ⑤ a turn changed files since an audit
    if (open && !["source", "code", "paper"].includes(open.mode)) show(open, false);  // Intent / Plan / 왜? stay open and show the new state
    Object.values(lives).forEach(l => l.querySelectorAll(".crit:empty").forEach(c => {  // the live card's criteria, once stored
      const v = Object.values(M.views).find(v => v.actions.some(x => x.id === c.closest("[data-act]").dataset.act));
      const a = v && v.actions.find(x => x.id === c.closest("[data-act]").dataset.act);
      if (!a || !a.criteria.length) return;
      c.textContent = "관련 기준: " + a.criteria.map(x => x.text).join(" · ");  // + where a source says so: [n] opens it
      c.append(" ", ...[...new Set(a.criteria.flatMap(x => (v.checks[x.id] || {}).evidence || []))].filter(e => M.anchors[e]).map(e => cite(e)));
      const o = offer({ ...a, task: v.task.id }, v); if (o) c.after(o);  // ⑦ a BLOCK on a paper condition: 의도한 차이로 두기
    }));
    settleLive();
  }).catch(e => console.error("[pablo] state", e)));
  // UI renewal: the bundled fonts (desktop/assets/fonts, served as pablo://fonts/*), only the files main says exist,
  // so a missing file never becomes a console error; without them the stacks fall back to system fonts
  let fontsAdded = false;
  const webFonts = () => { if (fontsAdded || !M.host || !Array.isArray(M.host.fonts)) return; fontsAdded = true;
    const want = { "PretendardVariable.woff2": ["Pretendard", { weight: "45 920" }],
      "Geist-Variable.woff2": ["Geist", { weight: "100 900", unicodeRange: "U+0000-024F, U+2000-206F, U+20A0-20CF, U+2190-21FF" }],
      "GeistMono-Variable.woff2": ["Geist Mono", { weight: "100 900" }] };
    M.host.fonts.forEach(f => { const w = want[f]; if (!w) return;
      new FontFace(w[0], "url(pablo://fonts/" + f + ")", w[1]).load().then(x => document.fonts.add(x), () => {}); }); };
  // UI renewal P2: #tools is now the stage bar under the header (it used to sit above the composer)
  const bar = $("chat").insertBefore(h("div", { id: "tools" }), $("log"));
  let srcOpen = false, shownTask = null, cardOpen = false;  // cardOpen: the header's source card (자료 · 폴더 · 인터넷)  // ② the source list, when it is folded into "자료 N개"; the task the box belongs to
  const attach = kind => pabloHost[kind](V.task.id).then(name => name && refresh(),
    e => { live(V.task.id).append(msg("Pablo", null, h("div", { class: "call block" }, h("p", { class: "head" }, "⚠ " + clean(e))))); scroll(); });
  // C1/C2: + 추가 -> a PDF file, or an arXiv id / link that main downloads (one row under the tools)
  const adder = $("chat").insertBefore(h("div", { id: "adder", hidden: true }), box);
  // D1/D2: the same box takes an arXiv id or link (C2), a web page's address (D1), or words to find a paper (D2)
  const arx = h("input", { id: "arxiv", placeholder: "arXiv 번호·링크, OpenReview·DOI, 웹 문서 주소(여러 개 가능), 또는 찾을 말" }), note = h("span", { id: "arxiv-note" });
  const hits = h("div", { id: "arxiv-hits", hidden: true }), lines = h("ul", { id: "arxiv-lines", hidden: true });
  const ARXIV = /^(arxiv:|(https?:\/\/)?(www\.|export\.)?arxiv\.org\/)|^\d{4}\.\d{4,5}(v\d+)?$|^[a-z][a-z-]*(\.[A-Z]{2})?\/\d{7}(v\d+)?$|^(https?:\/\/(dx\.)?doi\.org\/|doi:\s*)?10\.48550\/arxiv\./i;  // ⑬ arXiv's own DOI too
  const moved = m => { const n = Object.values(m).reduce((a, b) => a + b, 0);
    return n ? ` 이전 버전에서 찾은 근거 ${n}개: 그대로 ${m.VALID || 0} · 문맥 바뀜 ${m.STALE || 0} · 찾을 수 없음 ${m.UNRESOLVED || 0}.` : ""; };
  const hold = on => { get.disabled = find.disabled = on; };
  // ② several at once: one line per item (✓ added / ⚠ why not) under the box, and a count in the note
  const report = (rows, what) => {  // rows: [ok | same | bad, text]; one already there is not counted as added
    lines.textContent = ""; lines.hidden = !rows.length;
    rows.forEach(([st, text]) => lines.append(h("li", { class: st === "bad" ? "bad" : st === "same" ? "ok same" : "ok" }, text)));
    const n = rows.filter(([st]) => st === "ok").length, same = rows.filter(([st]) => st === "same").length;
    note.textContent = `${what} ${rows.length}개 중 ${n}개를 추가했습니다${same ? `(${same}개는 이미 있음)` : ""}.`;
  };
  const fresh = () => { lines.textContent = ""; lines.hidden = hits.hidden = true; };  // one action's result at a time
  // picked or dropped PDFs: one at a time, so the note says how far it got ("3개 중 2번째") and a slow one is visible
  async function addPaths(paths) {
    adder.hidden = false; fresh(); hold(true); const rows = [];
    for (const [i, p] of paths.entries()) {
      note.textContent = `PDF ${paths.length}개 중 ${i + 1}번째를 추가하는 중…`;
      try { const r = await pabloHost.addFiles(V.task.id, [p]);
        rows.push(...r.added.map(t => [t.same ? "same" : "ok", `✓ ${t.title}${t.same ? " (이미 있음)" : ""}`]), ...r.failed.map(f => ["bad", `⚠ ${f.file}: ${f.error}`])); }
      catch (e) { rows.push(["bad", `⚠ ${p.split(/[\\/]/).pop()}: ${fail(e)}`]); }
    }
    hold(false); report(rows, "PDF"); refresh();
    // all added: the box goes (the header chip and the source card show them); a failure keeps it open with its reason
    // (QA 10/26: it stayed over the conversation after every pick)
    if (rows.length && rows.every(r => r[0] !== "bad")) adder.hidden = true;
  }
  const pickPdfs = () => pabloHost.pickPdfs(V.task.id).then(ps => ps && addPaths(ps), e => { adder.hidden = false; note.textContent = "⚠ " + fail(e); });
  // ⑬ an OpenReview link is a paper (its PDF); a DOI is looked up (arXiv's own DOI is an arXiv id: ARXIV takes it)
  const OPENREVIEW = /^(?:https?:\/\/)?(?:www\.)?openreview\.net\/(?:forum|pdf)\?/i, DOI = /^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)?10\.\d{4,9}\//i;
  const item = v => ARXIV.test(v) || /^https?:\/\//i.test(v) || OPENREVIEW.test(v);
  const one = (v, doi) => (ARXIV.test(v) ? pabloHost.addArxiv : OPENREVIEW.test(v) && pabloHost.addOpenreview ? pabloHost.addOpenreview : pabloHost.addWeb)(V.task.id, v, doi ? { doi } : undefined);
  const label = r => `${r.title}${r.version ? " " + r.version : ""}`;
  async function batch(vs, doi) {
    hold(true); fresh(); const rows = [];
    for (const [i, v] of vs.entries()) {
      note.textContent = `${vs.length}개 중 ${i + 1}번째를 가져오는 중…`;
      try { const r = await one(v, doi); rows.push([r.same ? "same" : "ok", `✓ ${label(r)}${r.same ? " (이미 있음)" : ""}${r.moved ? " ·" + moved(r.moved) : ""}`]); }
      catch (e) { rows.push(["bad", `⚠ ${v}: ${fail(e)}`]); }
    }
    hold(false); arx.value = ""; report(rows, "자료"); refresh();
  }
  const fetchArxiv = (v = arx.value.trim(), foundBy) => {
    if (!v || get.disabled) return;
    const parts = v.replace(/arxiv:\s+/gi, "arxiv:").split(/[\s,;]+/).filter(Boolean);
    if (parts.length > 1 && parts.every(item)) return batch(parts);  // ② several ids / links / addresses
    if (!ARXIV.test(v) && DOI.test(v) && pabloHost.lookupDoi) return doi(v);
    const or = !ARXIV.test(v) && OPENREVIEW.test(v) && !!pabloHost.addOpenreview, web = !ARXIV.test(v) && !or && /^https?:\/\//i.test(v);
    if (!web && !or && !ARXIV.test(v)) return search();  // words: find the paper first
    hold(true); fresh(); note.textContent = or ? "OpenReview에서 받는 중…" : web ? "웹 문서를 가져오는 중…" : "arXiv에서 받는 중…";
    (or ? pabloHost.addOpenreview : web ? pabloHost.addWeb : pabloHost.addArxiv)(V.task.id, v, foundBy ? { doi: foundBy } : undefined).then(r => {
      hold(false); arx.value = "";
      note.textContent = `${r.same ? "이미 있는 자료입니다" : "추가했습니다"}: ${r.title}${r.version ? " " + r.version : ""}.` + (r.moved ? moved(r.moved) : "");
      refresh();
    }, e => { hold(false); note.textContent = "⚠ " + fail(e); });
  };
  // ⑬ a DOI: its title (Crossref), then the same title on arXiv; a publisher's PDF is added as a file
  const doi = v => {
    hold(true); fresh(); note.textContent = "DOI의 제목을 찾고, 같은 제목을 arXiv에서 찾는 중…";
    pabloHost.lookupDoi(v).then(r => { hold(false);
      if (!r.hits.length) { note.textContent = `DOI ${r.doi}: "${r.title}". 출판사의 PDF는 바로 받을 수 없고, arXiv에서 같은 제목을 찾지 못했습니다. PDF를 받아 "📄 PDF 파일 고르기"로 추가하세요. (DOI를 Crossref로, 그 제목을 arXiv로 보냈습니다.)`; return; }
      show_(r.hits, `DOI ${r.doi}: "${r.title}"${r.year ? ` (${r.year})` : ""}. 출판사의 PDF는 바로 받을 수 없어 arXiv에서 같은 제목을 찾았습니다. 맞는 판을 가져오세요.`,
        r.doi, "DOI를 Crossref(api.crossref.org)로, 그 제목을 arXiv(export.arxiv.org)로 보냈습니다. arXiv 판은 출판본과 다를 수 있습니다(표의 숫자 포함). 재현 대상이 출판본이면 그 PDF를 파일로 넣으세요.");
    }, e => { hold(false); note.textContent = "⚠ " + fail(e); });
  };
  const search = () => {
    const v = arx.value.trim(); if (!v || find.disabled || !pabloHost.searchArxiv) return;
    hold(true); fresh(); note.textContent = "arXiv에서 찾는 중…";
    pabloHost.searchArxiv(v).then(rs => show_(rs), e => { hold(false); note.textContent = "⚠ " + fail(e); });
  };
  const show_ = (rs, intro, doi, sent) => {
    {
      hold(false); note.textContent = rs.length ? (intro || "") : "arXiv에서 찾은 논문이 없습니다."; hits.textContent = ""; hits.hidden = !rs.length;
      const picked = () => [...hits.querySelectorAll("[data-pick]:checked")].map(c => c.dataset.pick);
      const many = h("button", { class: "pill", id: "arxiv-many", disabled: true, on: () => picked().length && batch(picked(), doi) }, "고른 논문 가져오기");
      const have = new Set((((M.desk || {})[V.task.id] || {}).papers || []).map(p => p.arxiv).filter(Boolean));  // already a source here
      hits.append(h("p", { class: "muted", "data-sent": "1" }, sent || "검색어를 arXiv(export.arxiv.org)로 보냈습니다. arXiv의 요청 제한 때문에 3초에 한 번까지 찾습니다."),
        ...rs.map(x => h("div", { class: "hit", "data-hit": x.id, title: x.summary || null },
          have.has(x.id) ? null : [h("input", { type: "checkbox", "data-pick": x.id, title: "여러 개 골라 한 번에 가져오기" }), " "],
          h("b", null, x.title), " ", h("small", { class: "muted" }, `${x.authors} · ${x.year} · arXiv ${x.id}${x.version || ""}`), " ",
          have.has(x.id) ? h("small", { class: "have", "data-have": "1" }, "✓ 자료에 있음")
            : h("button", { class: "link", "data-import": x.id, on: () => fetchArxiv(x.id, doi) }, "가져오기"),
          x.summary ? h("div", { class: "sum" }, x.summary) : null)), h("p", null, many));
      hits.addEventListener("change", () => { const n = picked().length; many.disabled = !n; many.textContent = n ? `고른 ${n}개 가져오기` : "고른 논문 가져오기"; });
    }
  };
  const get = h("button", { class: "pill", id: "arxiv-get", on: () => fetchArxiv() }, "가져오기");
  const find = h("button", { class: "pill", id: "arxiv-find", title: "검색어가 arXiv(export.arxiv.org)로 보내집니다. 3초에 한 번까지 찾습니다.", on: search }, "🔎 arXiv에서 찾기");
  arx.addEventListener("keydown", e => { if (e.key === "Enter" && !e.isComposing) fetchArxiv(); });
  adder.append(...[link("📄 PDF 파일 고르기 (여러 개 가능)", pickPdfs), "또는", arx, get, pabloHost.searchArxiv ? find : null, note, lines, hits].filter(Boolean));
  // ② PDFs dropped anywhere on the window become the open task's sources (preload gives each file's path; main checks it)
  if (pabloHost.addFiles && pabloHost.pathOf) {
    const files = e => [...((e.dataTransfer || {}).types || [])].includes("Files");
    addEventListener("dragover", e => { if (!V || !files(e)) return; e.preventDefault(); document.body.classList.add("dropping"); });
    addEventListener("dragleave", e => { if (!e.relatedTarget) document.body.classList.remove("dropping"); });
    addEventListener("drop", e => {
      document.body.classList.remove("dropping");
      if (!V || !files(e)) return;
      e.preventDefault();
      const paths = [...e.dataTransfer.files].map(f => pabloHost.pathOf(f)).filter(Boolean);
      adder.hidden = false; fresh();
      if (!paths.length) { note.textContent = "놓은 것 중에 PDF 파일이 없습니다."; return; }
      addPaths(paths);
    });
  }
  const say = (text, tag) => { live(V.task.id).append(msg("Pablo", null, h("p", { class: "muted", [tag]: "1" }, text))); scroll(); };
  // P7: the last stage is done -> ask once whether the task moves into 완료 (sidebar); reopening it always works
  const askDone = () => { const d = (M.desk || {})[V.task.id] || {}; if (d.done || !pabloHost.setUi) return;
    const t = V.task.id, card = h("div", { class: "changes", "data-done-ask": "1" }, h("p", null, h("b", null, "이 작업을 완료로 옮길까요?")),
      h("p", { class: "muted" }, "사이드바 아래 '완료'로 접힙니다. 다시 열면 언제든 이어서 할 수 있습니다."),
      h("p", null, h("button", { class: "pill on", "data-done-go": "1", on: () => pabloHost.setUi(t, "done", true).then(() => { card.closest(".msg").remove(); return refresh(); }) }, "완료로 옮기기"),
        " ", link("나중에", () => card.closest(".msg").remove())));
    live(t).append(msg("Pablo", null, card)); scroll(); };
  // 0.8 review: 다시 뽑기 says first what it replaces and what it keeps (extractions differ from run to run)
  const redo = () => {
    const live = V.research.map(id => V.checks[id]).filter(k => k.spec && k.state !== "waived");
    const own = live.filter(k => k.spec.by === "user" || k.spec.kept).length, dev = live.filter(k => devOf(k)).length;
    const outn = V.research.map(id => V.checks[id]).filter(k => k.spec && k.state === "waived" && k.waived_by === "user").length;
    const box = h("div", { class: "call", "data-redo-ask": "1" }, h("p", { class: "head" }, "📋 재현 조건을 다시 뽑을까요?"),
      h("p", { class: "muted" }, "Pablo가 뽑은 조건은 새로 뽑은 목록으로 바뀝니다. 뽑을 때마다 조금씩 다를 수 있어, 이번에 빠진 조건은 되살릴 수 있게 남겨 둡니다.",
        own || dev ? ` 직접 더하거나 되살린 조건 ${own}개와 의도한 차이로 둔 조건 ${dev}개는 그대로 둡니다.` : "",
        outn ? ` 이전에 뺀 조건 ${outn}개는 다시 넣지 않습니다.` : ""),
      h("p", null, h("button", { class: "pill on", "data-redo-go": "1", on: () => { box.closest(".msg").remove(); spec(V.task.id); } }, "다시 뽑기"), " ",
        h("button", { class: "link", on: () => box.closest(".msg").remove() }, "취소")));
    live_(V.task.id).append(msg("Pablo", null, box)); scroll(); };
  const live_ = t => live(t);
  tools = () => {
    bar.textContent = "";
    if (!V) { adder.hidden = true; return; }
    if (shownTask !== V.task.id) { shownTask = V.task.id; fresh(); note.textContent = ""; arx.value = ""; }  // another task's results never stay
    const d = (M.desk || {})[V.task.id] || {}, ps = d.papers || [], main = ps.find(p => p.primary);
    const pdfs = ps.filter(p => p.kind !== "web"), several = pdfs.length > 1;  // D1: a web page is asked, never reproduced or a row
    const hasSpec = V.research.some(id => V.checks[id].spec && V.checks[id].state !== "waived");
    // ② more than 3 sources: one line "자료 N개 (주 논문 X) ▾", the list opens below it (one per line)
    const many = ps.length > 3, open = !many || srcOpen;
    const chip = p => h("span", { class: "paper", "data-paper": p.id, "data-kind": p.kind || "pdf" },
        p.kind === "web" ? h("span", { title: "웹 문서" }, "🌐 ") : null,
        ...(name => p.kind !== "web" && (M.papers || {})[p.id] ? [h("button", { class: "link", "data-open-paper": p.id,
          title: "PDF 열기 (문장을 골라 재현 조건으로 더할 수 있습니다)", on: () => show({ mode: "paper", src: p.id }) }, name)] : name)(
          [h("b", null, p.title), p.version ? h("small", null, " " + p.version) : null]),
        p.kind !== "web" ? renamer(p.id, p.title, V.task.id) : null,
        ...codeOf(p.id).filter(x => x.official).map(x => [" ", h("a", { class: "code", href: x.url, target: "_blank", rel: "noopener noreferrer",
          "data-code": p.id, title: `논문의 공식 코드 (논문 p.${x.page}): ${x.url}` }, "코드 ↗")]),
        several && p.kind !== "web" ? (p.primary ? h("small", { class: "muted", "data-primary": "1" }, " (주 논문)")
          : [" ", h("button", { class: "link", title: "이 논문을 재현 대상으로 (재현 조건은 주 논문에서 뽑습니다)", "data-make-primary": p.id,
              on: () => pabloHost.setPrimary(V.task.id, p.id).then(() => refresh()) }, "주 논문으로")]) : null,
        h("button", { class: "rm", title: "자료에서 빼기 (찾은 근거 기록은 남습니다)", "data-remove": p.id,
          on: () => pabloHost.removeSource(V.task.id, p.id).then(() => refresh()) }, "×"));
    const srcEl = h("span", { id: "src", class: many ? "many" : null }, "📎 자료: ",
        many ? h("button", { class: "link", id: "src-toggle", on: () => { srcOpen = !srcOpen; tools(); } },
          `${ps.length}개${main ? ` (주 논문 ${main.title})` : ""} ${open ? "▴" : "▾"}`) : null,
        ps.length ? h("span", { class: "plist", hidden: !open }, ps.map(p => chip(p))) : "없음", " ",
        pabloHost.addArxiv ? link("+ 추가", () => { adder.hidden = !adder.hidden; if (!adder.hidden) arx.focus(); }) : link("PDF 추가", pickPdfs));
    const dirEl = h("span", { id: "dir" }, "📁 작업 폴더: ", d.folder ? h("b", null, d.folder) : "없음", " ", link(d.folder ? "바꾸기" : "선택", () => attach("pickFolder")));
    const specEl = ps.length && pabloHost.spec ? h("span", { id: "specs", title: several ? "재현 조건은 주 논문 한 편에서 뽑습니다. 다른 논문에서 다시 뽑으면 이전 조건을 대체합니다." : null },
        link((hasSpec ? "📋 재현 조건 다시 뽑기" : "📋 재현 조건 뽑기") + (several && main ? ` (${main.title})` : ""), () => hasSpec ? redo() : spec(V.task.id))) : null;
    const compEl = several && pabloHost.compare ? h("span", { id: "compares" }, link("📊 비교표", () => compareForm(V.task.id))) : null;
    const routeEl = ps.length && d.folder && pabloHost.setRoute ? h("span", { id: "route", title: "에이전트는 논문 조건과 확인된 근거를 알고 작업 폴더에서 일합니다. 논문 질문은 PDF에서 근거를 찾아 답합니다." },
        "보낼 곳 ", h("span", { class: "seg" }, ...[["agent", "에이전트"], ["ask", "논문 질문"]].map(([r, label]) =>  // A2: a segmented control
          (d.route || "agent") === r ? h("b", { "data-route": r }, label) : link(label, () => pabloHost.setRoute(V.task.id, r).then(() => refresh()))))) : null;
    const auditEl = d.folder && pabloHost.audit && (V.research.some(id => V.checks[id].spec && V.checks[id].state !== "waived") || V.intent.must.length || V.intent.prefer.length)
        ? h("span", { id: "audits" }, link("🔎 재현 점검", () => audit(V.task.id))) : null;
    const reportEl = pabloHost.report && (hasSpec || V.actions.length || V.chat.some(c => c.role === "audit")) ? h("span", { id: "reports" },  // ⑫
        link("📄 보고서", () => pabloHost.report(V.task.id).then(r => r && (say(`📄 보고서를 저장했습니다: ${r.name} (${r.lines}줄). 조건마다 논문의 쪽, 의도한 차이와 뺀 것의 이유, 마지막 점검을 담았습니다.`, "data-report"), askDone(), refresh()),
          e => say("⚠ " + fail(e), "data-report-error")))) : null;
    const netEl = d.folder && pabloHost.setNet ? h("span", { id: "net", "data-on": d.net ? "1" : "", title: "패키지 설치, 데이터 내려받기, git clone에 필요합니다. 켜도 명령마다 Pablo가 검토합니다." },
        "🌐 인터넷: ", h("b", null, d.net ? "허용" : "차단"), " ",
        link(d.net ? "차단하기" : "허용하기", () => pabloHost.setNet(V.task.id, !d.net).then(() => refresh()))) : null;
    // the header: one chip with the task's state (자료 · 폴더 · 인터넷) that opens the source card (team review: the
    // sources read as a sentence before; now a list with a PDF / WEB mark per item)
    const card = h("div", { class: "srccard", id: "srccard", hidden: !cardOpen },
      ...[srcEl, dirEl, netEl].filter(Boolean).map(x => h("div", { class: "sc-sec" }, x)));
    // A2: one chip, a segment (icon + words) per part of the state; the folder by its last name, the whole path in its title
    const seg = (icon, text, cls, title) => h("span", { class: "sc-seg" + (cls ? " " + cls : ""), title }, ico(icon, 14), h("span", null, text));
    const chipBtn = h("button", { class: "statechip", "aria-expanded": String(cardOpen), title: "자료 · 작업 폴더 · 인터넷",
      "aria-label": [`자료 ${ps.length}`, d.folder || "폴더 없음", d.folder ? (d.net ? "인터넷 허용" : "인터넷 차단") : null].filter(Boolean).join(" · "),
      on: () => { cardOpen = !cardOpen; card.hidden = !cardOpen; chipBtn.setAttribute("aria-expanded", String(cardOpen)); } },
      seg("file", `자료 ${ps.length}`, "sc-src"),
      seg("folder", d.folder ? d.folder.split(/[\\/]/).filter(Boolean).pop() || d.folder : "폴더 없음", "sc-dir" + (d.folder ? "" : " sc-none"), d.folder || null),
      d.folder ? seg(d.net ? "globe" : "globe-off", d.net ? "인터넷 허용" : "인터넷 차단", "sc-net") : null, ico("chevron-down", 12));
    const oldChips = $("chips"); if (oldChips) oldChips.remove();
    $("bar").append(h("span", { id: "chips" }, chipBtn, card));
    // the stage bar: always visible; a step's state comes from what is already recorded, nothing is enforced.
    // Each step carries its old action (#specs / #audits / #compares / #reports, same ids, texts and conditions).
    const chat = V.chat || [], audits = chat.filter(c => c.role === "audit"), la = audits[audits.length - 1];
    const staleAudit = !!la && chat.some(c => (c.role === "changes" || c.role === "undo") && c.at > la.at);
    const differ = la ? (la.items || []).filter(x => x.status === "differs").length : 0;
    const specs = V.research.map(id => V.checks[id]).filter(k => k.spec && k.state !== "waived");
    const toDecide = specs.filter(k => k.state === "pending").length + (V.intent.questions || []).length;
    const waiting = V.actions.some(a => a.verdict === "WARN" && !a.decision);
    const reported = chat.some(c => c.role === "report"), asked = chat.filter(c => c.role === "ask").length;
    const compared = chat.some(c => c.role === "compare");
    const changedFiles = chat.filter(c => c.role === "changes").reduce((n, c) => n + (c.files || []).length, 0);
    const kind = d.kind || (d.folder && ps.length ? "repro" : ps.length ? "read" : "general");
    const step = (key, label, state, sub, act) => ({ key, label, state, sub, act });
    const steps = kind === "repro" ? [
      step("prep", "준비", ps.length && d.folder ? "done" : "todo", ps.length && d.folder ? `논문 ${pdfs.length} · 폴더` : !ps.length ? "논문 필요" : "폴더 필요"),
      step("spec", "조건 확정", !ps.length ? "blocked" : hasSpec && !toDecide ? "done" : "todo",
        !ps.length ? "주 논문 필요" : !hasSpec ? "조건 뽑기 전" : toDecide ? `정할 일 ${toDecide}` : `조건 ${specs.length}`, specEl),
      step("run", "구현·실행", !d.folder ? "blocked" : la && !waiting ? "done" : "todo",
        !d.folder ? "폴더 필요" : waiting ? "확인 기다림" : V.actions.length ? `행동 ${V.actions.length}` : "—"),
      step("audit", "재현 점검", !auditEl ? "blocked" : staleAudit ? "stale" : la ? "done" : "todo",
        !auditEl ? "폴더 · 조건 필요" : staleAudit ? "오래됨 · 다시 필요" : la ? (differ ? `다름 ${differ}` : "점검함") : "점검 전", auditEl),
      step("report", "보고서", reported ? "done" : "todo", reported ? "저장함" : reportEl ? "할 수 있음" : "—", reportEl)]
    : kind === "read" ? [
      step("prep", "준비", ps.length ? "done" : "todo", ps.length ? `논문 ${ps.length}` : "논문 필요", specEl),
      step("ask", "질문", asked && compared ? "done" : "todo", asked ? `질문 ${asked}` : "질문 전"),
      step("compare", "비교표", pdfs.length < 2 ? "blocked" : compared ? "done" : "todo", pdfs.length < 2 ? "논문 2편 필요" : compared ? "만듦" : "할 수 있음", compEl),
      step("wrap", "정리", reported ? "done" : "todo", reported ? "저장함" : "—", reportEl)]
    : [step("prep", "준비", d.folder ? "done" : "todo", d.folder ? "폴더" : "폴더 필요"),
      step("work", "작업", reported ? "done" : "todo", waiting ? "확인 기다림" : changedFiles ? `바뀐 파일 ${changedFiles}` : "—", specEl),
      // the audit of the folder against the task's criteria is part of 검토 (QA 10/26: it floated past the last stage)
      step("review", "검토", reported ? "done" : "todo", reported ? "저장함" : "—", [auditEl, reportEl].filter(Boolean))];
    const cur = steps.find(s => s.state === "todo"); if (cur) cur.state = "current";
    // the composer says which stage a new message will be tagged with: its record's role, read as the tags read it (QA
    // 10/26: it showed the stage bar's current step, so "조건 확정" for a message the log then tagged 구현·실행). A message
    // goes to the paper question (ask) or the agent (user) as send() decides; with neither, it is not recorded
    const next = ps.length && (!d.folder || d.route === "ask") ? "ask" : "user";
    box.dataset.stage = ps.length || d.folder ? stageOfRole(next, kind) : ""; gate();
    const used = new Set(steps.flatMap(s => [].concat(s.act || []))), more = [specEl, compEl, auditEl, reportEl].filter(x => x && !used.has(x));
    // A2: each stage is a column under a 3px progress bar (.stage::before); no connector lines. The mark: a check when
    // done, ↻ when stale, a lock when blocked, else the number as "01"
    const stMark = (s, i) => s.state === "done" ? ico("check", 12) : s.state === "stale" ? ico("rotate", 12) : s.state === "blocked" ? ico("lock", 12)
      : String(i + 1).padStart(2, "0");
    bar.append(h("nav", { id: "stages", "data-kind": kind }, ...steps.map((s, i) =>
      h("div", { class: "stage st-" + s.state + ($("log").dataset.filter === s.label ? " picked" : ""), "data-stage": s.key,
        title: `${s.label} 단계의 대화만 보기`, on: e => { if (!e.target.closest("button, a")) stageFilter(s.label); } },
        h("span", { class: "st-n" }, stMark(s, i)),
        h("span", { class: "st-t" }, h("b", null, s.label), h("small", null, s.sub), s.act || null))),
      more.length ? h("span", { class: "st-more" }, ...more) : null));
    // P6: how the conversation is grouped (the task's choice, else the settings'; 시간순 by default)
    const view = d.view || (M.settings || {}).view || "time";
    bar.append(h("div", { id: "viewbar" }, h("span", { class: "muted" }, "보기"), h("span", { class: "vseg", role: "group", "aria-label": "보기" },
      ...[["time", "시간순"], ["stage", "단계별"], ["target", "대상별"]].map(([v, t]) =>
      h("button", { class: "vtab" + (view === v ? " on" : ""), "data-view": v, disabled: !pabloHost.setUi, "aria-pressed": String(view === v),
        on: () => view !== v && pabloHost.setUi(V.task.id, "view", v).then(() => refresh()).then(() => conversation()) }, t)))));
    box.querySelectorAll("#route").forEach(x => x.remove());  // 보낼 곳 lives in the composer, after the send button (it stays the first button)
    if (routeEl) box.append(routeEl);
  };
  newTask = () => {
    V = null; close(); sidebar(); header(); tools(); gate();
    const ta = h("textarea", { id: "goal", rows: 5,
      placeholder: "무엇을 할지 적어주세요.\n지켜야 할 조건은 한 줄에 하나씩 적으면 작업 기준이 됩니다." });
    // P7: three kinds; 논문 재현 keeps id=repro (its criteria come with it); each shows the stages it will go through
    const kinds = [["repro", "논문 재현", "데이터 누수와 결과 맞추기를 막는 기준 3개를 함께 넣습니다", "준비 → 조건 확정 → 구현·실행 → 재현 점검 → 보고서"],
      ["read", "논문 읽기", "질문과 비교표 중심, 작업 폴더 없이도 됩니다", "준비 → 질문 → 비교표 → 정리"],
      ["general", "일반", "기준을 대화로 직접 정합니다", "준비 → 작업 → 검토"]];
    const radios = kinds.map(([k]) => h("input", { type: "radio", name: "kind", value: k, id: k === "repro" ? "repro" : "kind-" + k, checked: k === "general" ? true : null }));
    const repro = radios[0], pickedKind = () => (radios.find(r => r.checked) || radios[2]).value;
    const stagesLine = h("p", { class: "muted", "data-kind-stages": "1" });
    const showStages = () => { stagesLine.textContent = "이 작업의 단계: " + kinds.find(k => k[0] === pickedKind())[3]; };
    radios.forEach(r => r.addEventListener("change", showStages)); showStages();
    const err = h("p", { class: "muted" }), make = h("button", { class: "pill on", id: "create", on: () => {
      const text = ta.value.trim(); if (!text) return;
      make.disabled = true; err.textContent = "작업을 만드는 중…";
      pabloHost.newTask(text, { repro: repro.checked, kind: pickedKind() }).then(r => refresh(r.id).then(() => {
        const n = r.added, id = r.id;  // what this form's lines recorded (project-wide criteria are in 기준 보기)
        // ③ every criterion line is accounted for: recorded, or waiting above for the user to decide
        live(id).append(msg("Pablo", null, M.tasks.length === 1 ? art("waving", "pose") : null, h("p", { "data-made": "1" }, n ? `작업 기준 ${n}개를 기록했습니다. ` : "작업을 만들었습니다. ",
          r.unread ? h("b", { "data-ask": "1" }, `적은 기준 ${r.lines}줄 중 ${r.unread}줄은 기준으로 읽지 못해, 위에서 정해 주세요. `) : null,
          link("작업 기준 보기", () => show({ mode: "intent" }))),
          h("p", { class: "muted" }, "PDF를 추가하면 근거를 찾아 답하고, 작업 폴더를 고르면 그 폴더에서 작업합니다.")));
      }), e => { make.disabled = false; err.textContent = clean(e); });
    } }, "작업 만들기");
    const log = $("log"); log.textContent = "";
    log.append(msg("Pablo", null, h("p", null, "새 작업을 시작합니다."), ta,
      h("div", { class: "kinds" }, kinds.map(([k, label, what], i) => h("label", { class: "kind" }, radios[i], h("b", null, label), h("small", null, what)))),
      stagesLine,
      h("p", null, make), err));
    ta.focus();
  };
  const clean = e => String(e.message || e).replace(/^Error invoking remote method '[^']*': (\w*Error: )?/, "");
  // P7 설정: the app's defaults (the model is chosen in the composer)
  function settings() {
    const old = $("settings"); if (old) return old.remove();
    const s = M.settings || {}, group = (name, label, help, opts, cur) => h("div", { class: "set-row" },
      h("div", null, h("b", null, label), h("small", null, help)),
      h("div", { class: "set-opts" }, opts.map(([v, t]) => h("label", null, h("input", { type: "radio", name: "set-" + name, value: v, checked: v === cur ? true : null }), " ", t))));
    const pickedOf = name => (document.querySelector(`#settings input[name="set-${name}"]:checked`) || {}).value;
    const err = h("p", { class: "muted" });
    const dlg = h("div", { id: "settings", role: "dialog" }, h("div", { class: "set-box" },
      h("div", { class: "set-head" }, h("b", null, "설정"), h("button", { class: "x", title: "닫기", on: () => dlg.remove() }, ico("x"))),
      group("view", "기본 보기", "대화를 처음 열 때의 보기", [["time", "시간순"], ["stage", "단계별"], ["target", "대상별"]], s.view || "time"),
      group("tags", "메시지 태그", "단계 · 대상만 보이고 나머지는 'N개 더'로 접습니다", [["main", "단계 · 대상만"], ["all", "전부"]], s.tags || "main"),
      group("panel", "새 작업의 오른쪽 패널", "그 뒤에는 작업마다 마지막 상태를 기억합니다", [["open", "열림 (기준)"], ["rail", "접힘 (레일)"]], s.panel || "open"),
      group("net", "새 작업의 인터넷", "허용해도 명령은 하나하나 Guard를 거칩니다", [["off", "차단"], ["on", "허용"]], s.net ? "on" : "off"),
      h("p", { class: "muted" }, "모델은 입력창에서 고릅니다."), err,
      h("div", { class: "set-foot" }, h("button", { class: "pill", on: () => dlg.remove() }, "취소"),
        h("button", { class: "pill on", "data-settings-save": "1", on: () => pabloHost.setUi(null, "settings", { view: pickedOf("view"), tags: pickedOf("tags"),
          panel: pickedOf("panel"), net: pickedOf("net") === "on" }).then(() => { dlg.remove(); return refresh(); }).then(() => V && conversation(), e => { err.textContent = clean(e); }) }, "저장"))));
    dlg.addEventListener("click", e => { if (e.target === dlg) dlg.remove(); });
    document.body.append(dlg);
  }
  // A5/A6: 재현 점검 -> one read-only agent turn; its JSON answer comes back as an "audit" event (a table in the conversation)
  reAudit = t => audit(t);
  function audit(t) {
    if (agentSt === "Thinking") return;
    talk = busy = t; turning = true;
    live(t).append(msg("Pablo", null, h("div", { class: "audit", "data-auditing": "1" },
      h("p", { class: "muted" }, "작업 폴더를 논문 조건·작업 기준과 대조하는 중… (파일을 읽기만 합니다)")))); scroll(); gate();
    pabloHost.audit(t).catch(e => { turning = false; busy = null; status("Error", fail(e));
      const p = live(t).querySelector("[data-auditing]"); if (p) p.replaceWith(h("div", { class: "call block" }, h("p", { class: "head" }, "⚠ " + fail(e)))); });
  }
  // A2: the paper's reproduction conditions -> a card in the conversation (+ the 기준 panel); the agent's brief has them
  function spec(t) {
    if (agentSt === "Thinking") return;
    talk = busy = t;
    const box = h("div", { class: "spec" }, h("p", { class: "muted" }, "논문에서 재현 조건을 찾는 중…"));
    live(t).append(msg("Pablo", null, box)); scroll(); status("Thinking");
    pabloHost.spec(t).then(r => {
      Object.assign(M.anchors, r.anchors); Object.assign(M.sources, r.sources);
      for (const c of [...r.stated, ...r.missing]) M.views[t].checks[c.id] = c;
      box.replaceWith(conditions([...r.stated, ...r.missing].map(c => c.id), r.dropped.length, r.diff));
      busy = null; status("Ready"); scroll(); refresh();
    }, e => { box.textContent = ""; box.append(h("div", { class: "call block" }, h("p", { class: "head" }, "⚠ " + fail(e)))); busy = null; status("Ready"); });
  }
  // M3.3: with a captured PDF the question goes to Pablo (judge picks quotes, Pablo anchors them); [n] opens the page.
  // C1: every paper of the task at once; when that is too much text, the user picks which papers (only) to ask
  function ask(text, t, only) {
    talk = busy = t;
    const box = h("div", { class: "asked" }, h("p", { class: "muted" }, "PDF에서 근거를 찾는 중…"));
    live(t).append(msg("Pablo", null, box)); scroll(); status("Thinking");
    pabloHost.ask(text, t, only).then(r => {
      Object.assign(M.anchors, r.anchors); Object.assign(M.sources, r.sources); M.views[t].checks[r.check.id] = r.check;
      box.textContent = ""; box.dataset.check = r.check.id;
      box.append(h("p", null, cited(r.check.conclusion, r.check.evidence)));
      const w = webOnly(r.check); if (w) box.append(w);
      if (r.dropped.length) box.append(h("p", { class: "muted" }, `자료에서 찾지 못한 인용 ${r.dropped.length}개는 뺐습니다.`));
      busy = null; status("Ready"); scroll(); refresh();
    }, e => {
      box.textContent = ""; box.append(h("div", { class: "call block" }, h("p", { class: "head" }, "⚠ " + fail(e))));
      const ps = ((M.desk || {})[t] || {}).papers || [];
      if (/물어볼 (논문|자료)를 골라/.test(fail(e)) && ps.length > 1) box.firstChild.append(h("div", { class: "ask-pick" },
        ps.map(p => h("button", { class: "pill", "data-ask-only": p.id, on: () => ask(text, t, [p.id]) }, `${p.title}에만 묻기`))));
      busy = null; status("Ready");
    });
  }
  // C3 비교표: the columns (editable, default as skill.COLUMNS) -> one judge call per paper -> the table card
  const COLUMNS = ["데이터셋", "평가 지표", "주요 결과", "효율", "한계"];
  // ⑧ a suggested column goes into its table (only that column is asked); without one, the 비교표 form with these columns
  compareAgain = (t, columns, table, column) => table && pabloHost.compareColumn ? addColumn(t, table, column) : compareForm(t, columns);
  function addColumn(t, c, column) {
    if (agentSt === "Thinking") return;
    const card = document.querySelector(`#log [data-matrix="${CSS.escape(c.matrix)}"]`), wait = h("p", { class: "muted", "data-adding": column },
      `"${column}" 열만 논문 ${c.papers.length}편에서 찾는 중… (논문마다 한 번, 표 전체를 다시 만들지 않습니다)`);
    if (card) card.append(wait);
    talk = busy = t; status("Thinking");
    pabloHost.compareColumn(t, c.matrix, column).then(r => {
      Object.assign(M.anchors, r.anchors); Object.assign(M.sources, r.sources);
      for (const k of r.cells) M.views[t].checks[k.id] = k;
      Object.assign(c, r.entry); if (card) card.replaceWith(matrix(c));
      busy = null; status("Ready"); refresh();
    }, e => { wait.replaceWith(h("p", { class: "muted", "data-add-error": "1" }, "⚠ " + fail(e))); busy = null; status("Ready"); });
  }
  renameHook = t => refresh(t);  // a new name: the conversation is drawn again (the tables, the cards, the source list)
  function compareForm(t, columns) {
    if (agentSt === "Thinking") return;
    const ps = ((M.desk || {})[t] || {}).papers || [], cols = h("input", { class: "cols", id: "columns", value: (columns || COLUMNS).join(", ") });
    const box = h("div", { class: "matrix", "data-compare-form": "1" }, h("p", { class: "head" }, `📊 ${ps.map(p => p.title).join(" · ")} 비교`),
      h("p", { class: "muted" }, "비교할 항목을 쉼표로 적어 주세요(8개까지). 논문마다 따로 읽고, 논문에서 위치를 찾은 값만 칸에 넣습니다.",
        ` 논문 ${ps.filter(p => p.kind !== "web").length}편을 한 편씩 읽어 표 전체를 만듭니다(논문마다 30–40초쯤).`), cols);
    const make = h("button", { class: "pill on", id: "compare-go", on: () => {
      const cs = [...new Set(cols.value.split(/[,，\n]/).map(x => x.trim()).filter(Boolean))].slice(0, 8);
      if (!cs.length) return;
      make.disabled = true; talk = busy = t; status("Thinking");
      const wait = h("p", { class: "muted" }, `논문 ${ps.length}편을 한 편씩 읽고 표를 채우는 중…`); box.append(wait); scroll();
      pabloHost.compare(t, cs).then(r => {
        Object.assign(M.anchors, r.anchors); Object.assign(M.sources, r.sources);
        for (const c of r.cells) M.views[t].checks[c.id] = c;
        box.replaceWith(matrix(r.entry)); busy = null; status("Ready"); scroll(); refresh();
      }, e => { wait.replaceWith(h("div", { class: "call block" }, h("p", { class: "head" }, "⚠ " + fail(e)))); make.disabled = false; busy = null; status("Ready"); });
    } }, "비교표 만들기");
    box.append(h("p", null, make));
    live(t).append(msg("Pablo", null, box)); scroll(); cols.focus();
  }
  btn.addEventListener("click", () => box.dataset.running ? stop() : send());
  inp.addEventListener("keydown", e => { if (e.key === "Enter" && !e.isComposing) send(); });
  account(authSt); pabloHost.authStatus().then(account); pabloHost.agentStatus().then(s => status(s)); models().then(gate);
}
const tag = decodeURIComponent(location.hash.slice(1));
select(M.views[tag] ? tag : M.anchors[tag] ? (Object.keys(M.views).find(t => Object.values(M.views[t].checks).some(c => c.evidence.includes(tag))) || M.current) : M.current);
if (M.anchors[tag] && cites[tag]) show({ mode: "source", e: tag });
if (window.pabloHost && pabloHost.state) refresh();  // the page was written at launch; read the live state once
</script>
</body></html>
"""
