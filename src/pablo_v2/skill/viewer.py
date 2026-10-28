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
    # D4: every plan of the task, oldest first (each chat request supersedes the last): a step id (P3.1) in the chat log
    # and on an action finds its request and when it was made
    plans_all = [{"id": p.id, "created_at": p.created_at, "status": p.status,
                  "steps": [{"id": st["id"], "action": st["action"]} for st in p.steps]}
                 for p in s.state.plans if p.task_id == task_id]  # s.plans() is the active ones only

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
    # D3: a held-back (pending) or unread line the user made a criterion: K id -> the criterion's id, so the conversation
    # line and the criterion find each other
    kids = {u["id"] for c in chat for u in (c.get("unread") or []) + (c.get("pending") or []) if isinstance(u, dict) and u.get("id")}
    intent["promoted"] = {i: by_id[i].item_id for i in sorted(kids, key=lambda x: int(x[1:]) if x[1:].isdigit() else 0)
                          if i in by_id and by_id[i].status == "promoted" and by_id[i].item_id}
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
            "intent": intent, "research": research, "checks": checks, "plan": plan, "plans": plans_all, "actions": actions,
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


# A13 the report's parts the export dialog lists, in the order they are written ("conversation" only when asked for)
REPORT_SECTIONS = ("goal_criteria", "conditions", "audit", "deviations", "decisions", "changes", "refused", "conversation")


def render_report(s, task_id: str, now: dict | None = None, sections=None) -> str:
    """⑫ Markdown: the task's papers, conditions (with pages), what differs on purpose, what was taken out and why, the
    criteria, the last audit, what Pablo stopped or asked about, and what changed. Pages instead of [n]: a report is
    read apart from the app. A13 sections: the parts to keep (REPORT_SECTIONS); None = every part but the conversation."""
    out, cut, _ = _report(s, task_id, now, conversation=sections is not None and "conversation" in sections)
    if sections is None:
        return "\n".join(out).rstrip() + "\n"
    keep = set(sections)
    bounds = [b for _, b in cut] + [len(out)]
    lines = out[:cut[0][1]] + [ln for (key, a), b in zip(cut, bounds[1:]) if key in keep for ln in out[a:b]]
    tidy = []  # parts left out leave no double blank lines, and every heading has one blank line before it
    for ln in lines:
        if ln.startswith("#") and tidy and tidy[-1] != "":
            tidy.append("")
        if ln == "" and tidy and tidy[-1] == "":
            continue
        tidy.append(ln)
    return "\n".join(tidy).rstrip() + "\n"


def report_counts(s, task_id: str, now: dict | None = None) -> dict:
    """A13 what each part of the report holds (the export dialog's numbers), and whether the last audit is older than
    the last file change."""
    return _report(s, task_id, now)[2]


def _report(s, task_id: str, now: dict | None = None, conversation: bool = False) -> tuple[list, list, dict]:
    """-> (lines, [(section, index of its first line)], counts)"""
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
    cut = []
    sec = lambda key: cut.append((key, len(out)))  # noqa: E731
    # papers
    sec("conditions")
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
    sec("deviations")
    out += ["## 논문과 다르게 한 것 (의도한 차이)", ""]
    devs = [(c, d) for c in spec for d in c.spec.get("deviations", [])]
    out += [f"- {text(c)} — 이유: {d['why']} · 범위: {'별도 실행에서만' if (d.get('scope') or 'task') == 'runs' else '작업 전체'}"
            f" · {_when(d['from'])}부터" + (f" {_when(d['to'])}까지 (되돌림)" if d.get("to") else " (지금도)") for c, d in devs] or ["- 없음"]
    # what was taken out (fixed section)
    sec("decisions")
    out += ["", "## 뺀 조건과 지운 기준", ""]
    outs = [(c, d) for c in spec for d in c.spec.get("dropped", [])]
    gone = [g for g in v["intent"].get("removed", [])]
    out += [f"- 뺀 조건: {text(c)} — 이유: {d['why']} · {_when(d['from'])}" + (f" (되살림 {_when(d['to'])})" if d.get("to") else "") for c, d in outs]
    out += [f"- 지운 기준: {g['text']} — " + (f"이유: {g['why']}" if g.get("why") else "이유를 적지 않음") + f" · {_when(g['from'])}"
            + (f" (되살림 {_when(g['to'])})" if g.get("to") else "") for g in gone]
    if not outs and not gone:
        out.append("- 없음")
    # criteria
    sec("goal_criteria")
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
    n_dec = len(decided)
    if decided:
        sec("decisions")
        out += ["", "## 대화에서 정한 결정", ""] + decided
    # the last audit
    sec("audit")
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
    sec("refused")
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
    sec("changes")
    out += ["", "## 바뀐 파일", ""]
    out += [f"- {_when(x['at'])} 파일 {len(x.get('files', []))}개: " + ", ".join(f"{f['path']}" for f in x.get("files", [])[:12])
            + (" (되돌림)" if x.get("to") in undone else "") for x in ch] or ["- 에이전트가 바꾼 파일이 없습니다."]
    if aside:
        sec("conditions")
        out += ["", "## 참고 (따를 조건이 아닌 논문의 서술과 실험 범위)", ""]
        out += [f"- [{REPORT_KIND[c.spec['kind']]}] {text(c)} — {where.get(c.id, '쪽 없음')}" for c in aside]
    if conversation:
        sec("conversation")
        out += ["", "## 대화 전체", ""] + (_said_plainly(v, t) or ["- 대화가 없습니다."])
    counts = {"criteria": {"hard": len(v["intent"]["must"]), "soft": len(v["intent"]["prefer"])}, "conditions": len(stated),
              "audit": {"at": last["at"] if last else None}, "deviations": len(devs), "decisions": n_dec + len(outs) + len(gone),
              "changes": len(ch), "refused": len(acts), "conversation": len(v["chat"]),
              "stale": bool(last) and any(x.get("role") in ("changes", "undo") and x.get("at", "") > last["at"] for x in v["chat"])}
    return out, cut, counts


def _said_plainly(v: dict, t) -> list[str]:
    """A13 "대화 전체": every entry of the chat log as one line (who · when — what), no [n], no cards."""
    flat = lambda x, n=4000: " ".join(str(x or "").split())[:n]  # noqa: E731
    bare = lambda x: re.sub(r"\s*\[\d+\]", "", str(x or "")).strip()  # noqa: E731
    fact = lambda cid: bare((v["checks"].get(cid) or {}).get("conclusion") or (v["checks"].get(cid) or {}).get("title"))  # noqa: E731
    line = lambda who, at, what: f"- **{who}** · {_when(at)} — {flat(what)}" if at else f"- **{who}** — {flat(what)}"  # noqa: E731
    edit = {"hard": "반드시로 바꿈", "soft": "가능하면으로 바꿈", "drop": "지움", "restore": "되살림", "edit": "고침"}
    spec = {"spec-add": "재현 조건에 더함", "spec-drop": "재현 조건에서 뺌", "spec-restore": "뺀 재현 조건을 되살림",
            "spec-deviate": "의도한 차이로 둠", "spec-undeviate": "논문 조건으로 되돌림"}
    out = [line("나", t.created_at, t.text)]
    for c in v["chat"]:
        r, at = c.get("role"), c.get("at")
        if r == "user":
            out.append(line("나", at, c.get("text")))
        elif r == "agent":
            out.append(line("Pablo", at, (c.get("text") or "") + (" (중지함)" if c.get("status") == "interrupted" else "")
                            + (f" (오류: {c['error']})" if c.get("error") else "")))
        elif r == "ask":
            out.append(line("나 (논문 질문)", at, c.get("text")))
            out.append(line("Pablo", None, fact(c["check"]) if c.get("check") else f"답하지 못함: {c.get('error') or ''}"))
        elif r == "intent":
            bits = [f"작업 기준에 추가: {i.get('text')} ({'반드시' if i.get('strength') == 'hard' else '가능하면'})" for i in c.get("items") or []]
            bits += [f"기준으로 둘지 물음: {k.get('text')}" for k in c.get("pending") or []]
            bits += [f"기준으로 읽지 못함: {u.get('text')}" for u in c.get("unread") or []]
            out.append(line("Pablo", at, " · ".join(bits)))
        elif r == "criterion-edit":
            out.append(line("나", at, f"작업 기준을 {edit.get(c.get('action'), '바꿈')}: {c.get('text')}"
                            + (f" (이유: {c['reason']})" if c.get("reason") else "")))
        elif r == "spec":
            out.append(line("Pablo", at, f"재현 조건 {len(c.get('checks') or [])}개를 뽑았습니다"
                            + (f", 논문에 없는 설정 {len(c['missing'])}개" if c.get("missing") else "")
                            + (f", 위치를 못 찾아 뺀 것 {c['dropped']}개" if c.get("dropped") else "") + "."))
        elif r in spec:
            out.append(line("나", at, f"{spec[r]}: {fact(c.get('check'))}" + (f" (이유: {c['reason']})" if c.get("reason") else "")))
        elif r == "audit":
            out.append(line("Pablo", at, f"재현 점검: 항목 {len(c.get('items') or [])}개." + (f" {c['summary']}" if c.get("summary") else "")
                            + (f" (오류: {c['error']})" if c.get("error") else "")))
        elif r == "changes":
            fs = [f.get("path", "") for f in c.get("files") or []]
            out.append(line("Pablo", at, f"파일 {len(fs)}개가 바뀌었습니다: {', '.join(fs[:12])}"))
        elif r == "undo":
            out.append(line("나", at, f"되돌림: {', '.join((c.get('files') or [])[:12])}"))
        elif r == "compare":
            out.append(line("Pablo", at, f"비교표: 논문 {len(c.get('papers') or [])}편 × 항목 {len(c.get('columns') or [])}개 ({', '.join(c.get('columns') or [])})"))
        elif r == "report":
            out.append(line("Pablo", at, f"보고서를 저장했습니다: {c.get('name', '')}"))
    return out


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
.mascot.bob { display:inline-block; vertical-align:middle; animation:bob 1.6s ease-in-out infinite; transform-origin:50% 90%; }
@keyframes bob { 25% { transform:translateY(-2px) rotate(-4deg); } 50% { transform:translateY(0) rotate(0); } 75% { transform:translateY(-2px) rotate(4deg); } }
@media (prefers-reduced-motion: reduce) { .mascot.bob { animation:none; } }
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
#side .brand b .mascot.ico, .set-brand b .mascot.ico { flex:none; width:26px; height:26px; }  /* demo 10/28: the character, not a "P" square */
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
/* one size scale (10/27, Kit A2 the same): 32 for a control on a row, 24 for a choice inside a group, 20 for a label in a
   line of text. Heights are set, not left to padding + line-height + border, which gave 22 / 28 / 30 / 33 / 36 for one role */
:root { --h-ctl:32px; --h-in:24px; --h-tag:20px; }
.pill, #side .new, #task-search, #bar .rn, #bar h1 .rn-in, .x, .nav, .ext, .statechip, #adder #arxiv, #chat > .composer > button
  { height:var(--h-ctl); box-sizing:border-box; }
.pill, .empty .pill { display:inline-flex; align-items:center; justify-content:center; gap:6px; padding-top:0; padding-bottom:0; }
#bar .rn, .x, .nav, .ext { width:var(--h-ctl); }
#chat > .composer > button.modelbtn { padding-top:0; padding-bottom:0; }
.composer #route .seg, #viewbar .vseg { height:var(--h-ctl); box-sizing:border-box; padding:4px; align-items:center; }
.composer #route .seg > b, .composer #route .seg > button, #viewbar .vtab { height:var(--h-in); box-sizing:border-box; display:inline-flex;
  align-items:center; padding-top:0; padding-bottom:0; }
.tg, .tagbtn, .cite { height:var(--h-tag); box-sizing:border-box; padding-top:0; padding-bottom:0; }
.cite { display:inline-flex; align-items:center; }
/* A2 complete · A shell: sidebar, header chips and menus, stage bar, view bar, first run, dialogs, narrow window (agent A) */
/* sidebar: brand row with the fold button, 새 작업 / search with their shortcut, rows with the stage progress, the account
   card at the foot; folded (body.side-off) it is a 56px rail */
body.side-off { --side-w:56px; }
#side { display:flex; flex-direction:column; overflow:hidden; }
#side .brand { flex:none; }
#side .brow { display:flex; align-items:center; justify-content:space-between; }
#side .fold { flex:none; width:28px; height:28px; display:grid; place-items:center; border-radius:var(--r-ctl); color:var(--ink-3); }
#side .fold:hover, #side .fold:focus-visible { background:var(--a5); color:var(--ink); }
#side .new > span { flex:1; text-align:left; }
.kbd { font:500 10px/1 var(--mono); letter-spacing:0; color:inherit; opacity:.6; background:none; border:0; padding:0; white-space:nowrap; }
#side .searchbox { flex:none; }
#side .searchbox > .kbd { position:absolute; right:10px; top:50%; transform:translateY(-50%); color:var(--ink-3); opacity:1; pointer-events:none; }
#task-search { padding-right:52px; }
#task-search::-webkit-search-cancel-button { display:none; }
#task-list { flex:1 1 auto; min-height:0; overflow:auto; }
#side .t .tn { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
#side .t small { display:flex; align-items:center; gap:8px; }
#side .t .prog { flex:none; display:inline-flex; gap:2px; }
#side .t .prog i { width:8px; height:3px; border-radius:2px; background:var(--a12); }
#side .t .prog i.p-done { background:var(--ink); } #side .t .prog i.p-current { background:var(--signal); }
#side .t .prog i.p-stale { background:rgba(13,14,16,.35); }
#side b.hit { font-weight:700; color:var(--ink); }
#side .none, #side .shint { margin:4px 8px; font-size:12px; line-height:1.5; color:var(--ink-3); }
#side .shint { margin-top:12px; }
#side .nohit { margin:2px 8px; } #side .nohit b { display:block; font:600 13px/1.4 var(--sans); color:var(--ink); }
#side .nohit p { margin:4px 0 6px; font-size:12px; line-height:1.5; color:var(--ink-2); } #side .nohit .link { font-size:12px; }
#side .away-row { position:relative; }
#side .away-row .t { opacity:.62; } #side .away-row:hover .t, #side .away-row:focus-within .t { opacity:1; }
#side .away-row .unarch { position:absolute; right:10px; bottom:12px; font-size:12px; opacity:0; }
#side .away-row:hover .unarch, #side .away-row .unarch:focus-visible { opacity:1; }
/* the account card (#acct) at the sidebar's foot; one state at a time (B21, S1–S4, S32–S35) */
#side > #acct { flex:none; width:auto; max-width:none; margin:8px 4px 0; font-size:12px; color:var(--ink-2); }
#acct .acard { display:flex; flex-direction:column; gap:2px; padding:10px 12px; background:var(--white); border:1px solid var(--a8);
  border-radius:var(--r-card); box-shadow:var(--sh-sm); }
#acct .acard > b { display:flex; align-items:center; gap:6px; font:600 12px/1.45 var(--sans); color:var(--ink); }
#acct .acard > small { font-size:12px; line-height:1.45; color:var(--ink-2); }
#acct .acard.bad { border-left:3px solid var(--signal); }
#acct .acard .link { font-size:12px; }
#acct .aacts { display:flex; flex-wrap:wrap; align-items:center; gap:6px 10px; margin-top:8px; }
#acct .hello { display:flex; align-items:center; gap:10px; margin:0 0 8px; padding:10px 12px; background:var(--white); border:1px solid var(--a8);
  border-radius:var(--r-card); box-shadow:var(--sh-md); }
#acct .hello .mascot.pose { height:30px; margin:0; } #acct .hello p { margin:0; }
#acct .hello b { display:block; font:600 12px/1.4 var(--sans); color:var(--ink); } #acct .hello small { font-size:11px; color:var(--ink-3); }
.spin { flex:none; display:inline-block; width:12px; height:12px; border:2px solid var(--a12); border-top-color:var(--ink); border-radius:50%;
  animation:spin .8s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation:none; } }
/* F16: the rail */
body.side-off #side { padding:12px 4px 8px; }
body.side-off #side > #acct { display:none; }
#side .rail { flex:1; min-height:0; display:flex; flex-direction:column; align-items:center; gap:8px; }
#side .rail .fold { margin-bottom:6px; }
#side .rail .rnew, #side .rail .rbtn, #side .rail .rt { flex:none; width:32px; height:32px; display:grid; place-items:center; border-radius:var(--r-ctl); }
#side .rail .rnew { background:var(--primary); color:var(--on-primary); box-shadow:var(--sh-sm); }
#side .rail .rbtn { color:var(--ink-2); } #side .rail .rbtn:hover, #side .rail .rt:hover { background:var(--a5); color:var(--ink); }
#side .rail .rtasks { flex:1; min-height:0; overflow:auto; display:flex; flex-direction:column; align-items:center; gap:6px; margin-top:6px; }
#side .rail .rt { font:600 12px/1 var(--sans); color:var(--ink-2); }
#side .rail .rt.on { background:var(--white); color:var(--ink); box-shadow:var(--sh-sm); }
/* header: name · kind · chips · ⋯; the rename field (S17) */
#bar { position:relative; }
#bar #pnl { display:none; }
#bar #more { color:var(--ink-2); } #bar #more[aria-expanded="true"] { background:var(--a5); color:var(--ink); }
#bar h1.renaming { flex:0 1 auto; display:flex; flex-wrap:wrap; align-items:center; gap:6px; overflow:visible; white-space:normal; }
#bar .rn-box { position:relative; display:inline-flex; align-items:center; }
#bar h1 .rn-box .rn-in { width:min(380px, 52vw); padding-right:56px; }
#bar .rn-cnt { position:absolute; right:10px; font:500 11px/1 var(--mono); color:var(--ink-3); pointer-events:none; }
#bar .rn-box.over .rn-in { border-color:var(--signal); box-shadow:0 0 0 3px var(--signal-soft); } #bar .rn-box.over .rn-cnt { color:var(--signal); }
#bar .rn-note { flex-basis:100%; display:flex; align-items:center; gap:4px; font:400 12px/1.4 var(--sans); color:var(--ink-3); }
#bar .rn-note.bad { color:var(--ink); }
/* menus (Kit a2/menu-item: rows 32, frame r10, shadow-lg, padding 4) */
.hmenu { position:absolute; right:12px; top:calc(100% - 6px); z-index:9; min-width:240px; display:flex; flex-direction:column; padding:4px;
  background:var(--white); border:1px solid var(--a8); border-radius:var(--r-in); box-shadow:var(--sh-lg); }
.hmenu[hidden] { display:none; }
.mi { width:100%; height:var(--h-ctl); display:flex; align-items:center; gap:10px; padding:0 10px; border-radius:var(--r-ctl); text-align:left;
  font:500 13px/1 var(--sans); color:var(--ink); }
.mi > span { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.mi > .ico { color:var(--ink-2); } .mi > small { font:400 11px/1 var(--mono); color:var(--ink-3); }
.mi:hover, .mi:focus-visible, .mi.sel { background:var(--a5); outline:none; }
.mfoot { margin:4px 6px 2px; padding-top:6px; border-top:1px solid var(--a6); font-size:11px; line-height:1.5; color:var(--ink-3); }
/* the chips (A7) and the card each opens (F18, S13–S15) */
#chips { flex:0 1 auto; min-width:0; margin-left:0; position:relative; display:flex; flex-wrap:wrap; align-items:center; gap:6px; }
.hchip, .hchip.statechip { display:inline-flex; align-items:center; gap:6px; max-width:240px; height:var(--h-ctl); padding:0 10px; border:1px solid var(--a8);
  border-radius:var(--r-ctl); background:var(--white); color:var(--ink); font:500 12px/1 var(--sans); box-shadow:var(--sh-sm); }
.hchip > .ico, .hchip.statechip > .ico { margin:0; color:var(--ink-2); } .hchip > .ico:last-child { color:var(--ink-3); }
.hchip > span { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.hchip.none > span { color:var(--ink-3); }
.hchip:hover, .hchip[aria-expanded="true"] { background:linear-gradient(var(--a4), var(--a4)), var(--white); }
#chips .srccard { left:0; right:auto; top:calc(100% + 8px); width:460px; max-width:calc(100vw - 32px); padding:4px; z-index:9; border-radius:var(--r-in); }
#chips .srccard[data-sec="dir"], #chips .srccard[data-sec="net"] { width:300px; }
.srccard .sc-sec { display:none; padding:0; border:0; color:var(--ink-2); }
.srccard[data-sec="src"] .sc-sec[data-sec="src"], .srccard[data-sec="dir"] .sc-sec[data-sec="dir"], .srccard[data-sec="net"] .sc-sec[data-sec="net"] { display:block; }
.srccard .sc-lbl { display:none; }
.srccard .sc-head { display:flex; align-items:baseline; gap:8px; padding:8px 10px 6px; }
.srccard .sc-head b { font:600 13px/1.4 var(--sans); color:var(--ink); } .srccard .sc-head small { font-size:12px; color:var(--ink-3); }
.srccard #src { display:block; }
.srccard #src .plist { margin:0; gap:0; }
.srccard #src .paper { display:grid; grid-template-columns:auto minmax(0, 1fr) auto; column-gap:10px; align-items:center; padding:8px 10px; border:0;
  border-radius:var(--r-ctl); }
.srccard #src .paper:hover, .srccard #src .paper:focus-within { background:var(--a4); }
.srccard #src .paper::before { grid-row:1 / span 2; align-self:center; }
.srccard #src .ptitle { grid-column:2; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:13px; color:var(--ink); }
.srccard #src .ptitle .link { font-weight:500; color:var(--ink); } .srccard #src .ptitle b { font-weight:600; }
.srccard #src .ptitle small { font:400 11px/1 var(--mono); color:var(--ink-3); }
.srccard #src .ptag { margin-left:6px; padding:1px 6px; border-radius:var(--r-tag); background:var(--a6); font:500 11px/16px var(--sans); color:var(--ink-2); }
.srccard #src .pmeta { grid-column:2; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font:400 11px/1.5 var(--mono); color:var(--ink-3); }
.srccard #src .pacts { grid-column:3; grid-row:1 / span 2; display:flex; align-items:center; gap:4px; opacity:0; transition:opacity .12s; font-size:12px; }
.srccard #src .paper:hover .pacts, .srccard #src .pacts:focus-within, .srccard #src .pacts:has(input) { opacity:1; }
.srccard #src .pacts .rn { opacity:1; } .srccard #src .rm { font-size:16px; padding:0 6px; color:var(--ink-3); }
.srccard #src .sc-none { display:block; padding:4px 10px 8px; color:var(--ink-3); }
.srccard #src-toggle { display:block; margin:0 10px 6px; font-size:12px; }
.srccard .sc-add { display:flex; align-items:center; gap:10px; margin-top:4px; padding:8px 10px 6px; border-top:1px solid var(--a6); }
.srccard .sc-add .link { display:inline-flex; align-items:center; height:var(--h-in); padding:0 10px; border-radius:var(--r-ctl); background:var(--a5); color:var(--ink); font-size:12px; }
.srccard .sc-add small { font-size:12px; color:var(--ink-3); }
.srccard #dir .sc-path { padding:8px 10px 8px; margin-bottom:4px; border-bottom:1px solid var(--a6); }
.srccard #dir .sc-path small { display:block; font-size:11px; color:var(--ink-3); }
.srccard #dir .sc-path code { padding:0; background:none; font-size:12px; color:var(--ink); }
.srccard #dir > b { display:block; padding:10px 12px 0; font:600 13px/1.4 var(--sans); color:var(--ink); }
.srccard #dir > p { margin:4px 12px 10px; font-size:12px; line-height:1.5; color:var(--ink-2); }
.srccard #dir > .pill { margin:0 12px 12px; }
/* the stage bar's filtered stage (A9) and the view bar's filter state (A10) */
#stages .st-t small[data-filtering] { color:var(--ink); font-weight:600; }
#viewbar .grow { flex:1; }
#viewbar .fnone { font-size:12px; color:var(--ink-3); }
#viewbar .fchip { display:inline-flex; align-items:center; gap:6px; height:var(--h-in); padding:0 8px 0 10px; border-radius:999px; background:var(--a6);
  font:500 12px/1 var(--sans); color:var(--ink); max-width:280px; }
#viewbar .fchip:hover { background:var(--a8); }
/* a narrow conversation column (the wide panel, a narrow window): the chips go to their own line under the title */
#chat { position:relative; container-type:inline-size; }
@container (max-width:760px) { #bar .grow { display:none; } #bar h1 { flex:0 1 auto; } #bar .kindtag { margin-right:auto; } #bar h1:last-of-type:not(:has(+ .kindtag)) { flex:1 1 0; }
  #bar #chips { order:5; flex-basis:100%; } }
/* notices under the header (S24) and cards that ask (S20, S21): white + the orange edge (the .call card) */
#notice { padding:0 20px; } #notice:empty { display:none; }
#notice .call { max-width:680px; margin:10px auto 0; }
/* .call .acts: one definition with B's cards (finishing pass) */
.call .acts small { font-size:12px; color:var(--ink-3); }
.cmdline { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:8px 0 0; padding:8px 12px; border-radius:var(--r-ctl); background:var(--a5); }
.cmdline code { padding:0; background:none; font-size:12px; }
.pill.sel { border-color:var(--ink); box-shadow:inset 0 0 0 1px var(--ink); }
/* first run (A11): the mascot, the question, the two steps */
.empty .mascot { height:120px; }
.empty .fr-card { width:min(460px, 100%); margin:22px auto 0; padding:18px 20px; display:flex; flex-direction:column; gap:12px; text-align:left;
  background:var(--white); border:1px solid var(--a8); border-radius:var(--r-card); }
.empty .fr-step { display:flex; align-items:center; justify-content:space-between; gap:12px; min-height:var(--h-ctl); }
.empty .fr-step > b { display:flex; align-items:center; gap:6px; margin:0; font:600 14px/1.4 var(--sans); color:var(--ink); }
.empty .fr-step.later > b { font-weight:500; color:var(--ink-3); } .empty .fr-step.done > b { color:var(--ink-2); }
.empty .fr-wait { display:inline-flex; align-items:center; gap:8px; font-size:12px; color:var(--ink-2); }
.empty .fr-note { margin:0; font-size:12px; line-height:1.55; color:var(--ink-2); } .empty .fr-note.bad { color:var(--ink); }
/* dialogs: dim + card (새 작업, 보고서 내보내기, 설정) */
.dlg-dim { position:fixed; inset:0; z-index:40; display:grid; place-items:center; padding:16px; background:rgba(13,14,16,.45); }
.dlg { width:min(620px, 100%); max-height:calc(100vh - 32px); display:flex; flex-direction:column; overflow:hidden; background:var(--surface);
  border:1px solid var(--a8); border-radius:var(--r-dlg); box-shadow:var(--sh-lg); }
.dlg-head { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:20px 24px 6px; }
.dlg-head b { font:600 20px/1.3 var(--sans); letter-spacing:-0.015em; color:var(--ink); }
.dlg-body { flex:1 1 auto; min-height:0; overflow:auto; display:flex; flex-direction:column; gap:16px; padding:8px 24px 8px; }
.dlg-foot { display:flex; justify-content:flex-end; gap:8px; padding:12px 24px 20px; }
.dlg h4 { margin:0 0 8px; font:600 13px/1.4 var(--sans); color:var(--ink); }
.dlg-err { margin:0 24px; font-size:12px; color:var(--ink); } .dlg-err:empty { display:none; }
/* A12 새 작업 */
.dlg.nt { width:min(640px, 100%); }
.nt #goal { margin:0; min-height:var(--h-ctl); resize:none; overflow:hidden; }
.nt-hint { display:block; margin-top:6px; font-size:12px; line-height:1.5; color:var(--ink-2); }
.nt .kinds { margin:0; }
.nt .kinds .kind { flex:1 1 160px; }
.nt-kind { margin-top:8px; padding:12px 14px; border-radius:var(--r-in); background:var(--a5); font-size:12px; line-height:1.6; color:var(--ink-2); }
.nt-kind b { color:var(--ink); } .nt-kind ul { margin:2px 0 6px; padding:0; list-style:none; } .nt-kind li::before { content:"· "; }
.nt-kind p { margin:0; }
.nt-row { display:flex; flex-wrap:wrap; align-items:center; gap:8px; }
.nt-in { flex:1 1 200px; min-width:0; height:var(--h-ctl); padding:0 12px; border:1px solid var(--a12); border-radius:var(--r-in); background:var(--white);
  color:var(--ink); font:400 13px/1 var(--sans); outline:none; }
.nt-in:focus, #nt-crit:focus { border-color:var(--ink-3); box-shadow:0 0 0 3px var(--a5); }
#nt-crit { width:100%; padding:8px 12px; border:1px solid var(--a12); border-radius:var(--r-in); background:var(--white); color:var(--ink);
  font:400 13px/1.55 var(--sans); resize:vertical; outline:none; }
.nt-chips { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; } .nt-chips:empty { display:none; }
.nt-chip { display:inline-flex; align-items:center; height:var(--h-ctl); border:1px solid var(--a12); border-radius:var(--r-ctl); background:var(--white);
  font-size:12px; color:var(--ink-2); }
.nt-chip.main { border-color:var(--ink); box-shadow:inset 0 0 0 1px var(--ink); }
.nt-chip .nt-cname { height:100%; padding:0 4px 0 10px; color:var(--ink-2); font-size:12px; } .nt-chip .nt-cname b { font-weight:600; color:var(--ink); }
.nt-chip .nt-x { width:26px; height:100%; display:grid; place-items:center; color:var(--ink-3); } .nt-chip .nt-x:hover { color:var(--ink); }
.nt-chip.add { padding:0 10px; border-style:dashed; background:var(--a4); color:var(--ink-3); }
.nt-two { display:grid; grid-template-columns:minmax(0, 1fr) minmax(0, 1fr); gap:16px; }
.nt-state:empty { display:none; } .nt-wait { display:flex; align-items:center; gap:8px; margin:0; font-size:12px; color:var(--ink-2); }
.nt-state .call { margin:0; }
.nt-switch { position:relative; display:inline-flex; align-items:center; gap:8px; min-height:var(--h-in); cursor:pointer; font-size:13px; color:var(--ink); }
.nt-switch input { position:absolute; width:1px; height:1px; opacity:0; margin:0; }
.nt-switch .sw { flex:none; position:relative; width:32px; height:20px; border-radius:999px; background:var(--a12); transition:background .15s; }
.nt-switch .sw::after { content:""; position:absolute; left:2px; top:2px; width:16px; height:16px; border-radius:50%; background:var(--white);
  box-shadow:var(--sh-sm); transition:left .15s; }
.nt-switch input:checked + .sw { background:var(--ink); } .nt-switch input:checked + .sw::after { left:14px; }
.nt-switch input:focus-visible + .sw { outline:2px solid var(--ink-3); outline-offset:2px; }
/* A13 보고서 내보내기 */
.dlg.rp { width:min(580px, 100%); }
.rp-list { display:flex; flex-direction:column; gap:3px; }
.rp-row { display:flex; align-items:center; gap:10px; min-height:var(--h-in); cursor:pointer; font-size:13px; color:var(--ink); }
.rp-row span { flex:1; } .rp-row small { font:400 12px/1 var(--mono); color:var(--ink-3); }
.rp-row input, .set-radios input { flex:none; width:14px; height:14px; margin:0; accent-color:var(--ink); }
.rp-row:has(input:not(:checked)) span { color:var(--ink-2); }
.rp-auto { padding:10px 14px; border-radius:var(--r-in); background:var(--a5); }
.rp-auto b { display:block; font:600 12px/1.5 var(--sans); color:var(--ink); }
.rp-auto code { padding:0; background:none; font-size:11px; color:var(--ink-2); overflow-wrap:anywhere; }
.rp-stale { display:flex; align-items:center; gap:12px; padding:10px 14px; border-radius:var(--r-in); background:var(--a5); }
.rp-stale p { flex:1; margin:0; font-size:12px; line-height:1.5; color:var(--ink); }
.rp-opts { display:flex; flex-wrap:wrap; gap:16px 32px; }
.seg2, .rp-wrow { display:inline-flex; align-items:center; gap:8px; }
.rp-where { height:var(--h-ctl); display:inline-flex; align-items:center; padding:0 10px; border:1px solid var(--a12); border-radius:var(--r-ctl);
  background:var(--white); font-size:12px; }
/* A14 설정: the list (every item r8) and a page */
#settings .set-box { width:min(820px, 100%); height:min(700px, calc(100vh - 32px)); max-height:none; display:grid; grid-template-columns:190px minmax(0, 1fr);
  gap:0; padding:0; overflow:hidden; }
#settings .set-nav { display:flex; flex-direction:column; gap:2px; padding:20px 12px; background:rgba(13,14,16,.035); border-right:1px solid var(--a6); }
#settings .set-nav > b { padding:0 10px 12px; font:600 17px/1.4 var(--sans); color:var(--ink); }
#settings .set-item { height:var(--h-ctl); padding:0 12px; border-radius:var(--r-ctl); text-align:left; font:500 13px/1 var(--sans); color:var(--ink-2); }
#settings .set-item:hover { background:var(--a5); color:var(--ink); } #settings .set-item.on { background:var(--a8); color:var(--ink); font-weight:600; }
#settings .set-main { min-width:0; overflow:auto; display:flex; flex-direction:column; padding:20px 28px 24px; }
#settings .set-head { margin-bottom:6px; } #settings .set-head > b { font:600 20px/1.3 var(--sans); color:var(--ink); }
#settings .set-page .set-row { border-top:0; padding:12px 0; gap:24px; align-items:flex-start; }
#settings .set-row > div:first-child { flex:1; min-width:0; }
#settings .set-row b { display:flex; align-items:center; font-size:14px; }
#settings .set-opts { flex:none; align-items:flex-end; white-space:normal; }
#settings .set-opts code { font-size:12px; }
.set-radios { display:flex; flex-direction:column; } .set-radios label { display:flex; align-items:center; gap:8px; min-height:var(--h-in); font-size:13px; cursor:pointer; }
.set-tag { margin-left:6px; padding:1px 6px; border-radius:var(--r-tag); background:var(--a6); font:500 11px/16px var(--sans); color:var(--ink-2); }
.set-card { margin:4px 0 6px; padding:14px 16px; background:var(--white); border:1px solid var(--a8); border-radius:var(--r-card); }
.set-card b { display:flex; align-items:center; gap:6px; font:600 14px/1.4 var(--sans); color:var(--ink); }
.set-card small { display:block; margin-top:4px; font-size:12px; color:var(--ink-2); }
#settings .set-confirm { margin:4px 0 8px; } #settings .set-confirm[hidden] { display:none; }
.set-lead { margin:2px 0 6px; font-size:12px; line-height:1.55; color:var(--ink-2); }
.set-sub { margin:16px 0 8px; padding-top:16px; border-top:1px solid var(--a8); font:600 13px/1.4 var(--sans); color:var(--ink); }
.set-info { display:flex; align-items:center; gap:6px; margin:12px 0 0; padding:10px 14px; border-radius:var(--r-in); background:var(--a5); font-size:12px; line-height:1.5; color:var(--ink-2); }
.set-path { align-self:flex-start; margin:-6px 0 6px; font-size:11px; }
.set-brand { display:flex; align-items:center; gap:10px; margin:6px 0 4px; }
.set-brand b { display:flex; align-items:center; gap:8px; font:600 17px/1.4 var(--sans); color:var(--ink); }
.set-brand code { padding:0; background:none; color:var(--ink-2); }
.set-note { margin:10px 0 0; font-size:12px; color:var(--ink); } .set-note:empty { display:none; }
/* + 추가 (F19, S25): a white card above the composer */
#adder { flex-direction:column; align-items:stretch; flex-wrap:nowrap; gap:8px; margin:0 auto 10px; padding:12px 16px; color:var(--ink-2);
  background:var(--white); border:1px solid var(--a8); border-radius:var(--r-card); box-shadow:var(--sh-lg); }
#adder .ad-head { display:flex; align-items:baseline; gap:8px; }
#adder .ad-head b { font:600 14px/1.4 var(--sans); color:var(--ink); } #adder .ad-head small { font-size:12px; color:var(--ink-3); }
#adder .ad-head .x { margin-left:auto; align-self:center; }
#adder .ad-row { display:flex; flex-wrap:wrap; align-items:center; gap:8px; }
#adder .ad-pdf { display:inline-flex; align-items:center; gap:6px; height:var(--h-ctl); padding:0 12px; border:1px solid var(--a12); border-radius:var(--r-ctl);
  background:var(--white); color:var(--ink); font:500 13px/1 var(--sans); text-decoration:none; }
#adder .ad-pdf:hover { background:var(--a4); text-decoration:none; }
#adder .or { font-size:12px; color:var(--ink-3); }
#adder #arxiv { flex:1 1 200px; min-width:0; height:var(--h-ctl); }
#adder .ad-note { display:flex; flex-direction:column; gap:6px; font-size:12px; line-height:1.5; }
#adder #arxiv-note:empty { display:none; }
#adder.busy #arxiv-note::before { content:""; display:inline-block; width:10px; height:10px; margin-right:8px; vertical-align:-1px; border:2px solid var(--a12);
  border-top-color:var(--ink); border-radius:50%; animation:spin .8s linear infinite; }
#adder .ad-prog { display:block; height:3px; border-radius:2px; background:var(--a8); overflow:hidden; } #adder .ad-prog[hidden] { display:none; }
#adder .ad-prog i { display:block; height:100%; width:0; background:var(--ink); transition:width .3s; }
#adder #arxiv-lines { margin:0; padding-left:18px; font-size:12px; }
#adder #arxiv-hits { display:flex; flex-direction:column; gap:2px; }
#adder #arxiv-hits [data-sent] { margin:0 0 6px; font-size:12px; color:var(--ink-3); }
#adder #arxiv-hits .hit { padding:8px 10px; border-radius:var(--r-ctl); background:var(--a4); font-size:13px; color:var(--ink); }
#adder #arxiv-hits .hit:has([data-have]) { color:var(--ink-3); }
#adder #arxiv-hits .hit { display:grid; grid-template-columns:auto minmax(0, 1fr) auto; column-gap:10px; align-items:center; }
#adder #arxiv-hits .hit > input { grid-column:1; grid-row:1 / span 2; margin:0; accent-color:var(--ink); }
#adder #arxiv-hits .hit > b { grid-column:2; grid-row:1; font-weight:600; }
#adder #arxiv-hits .hit > small:not(.have) { grid-column:2; grid-row:2; font:400 11px/1.5 var(--mono); color:var(--ink-3); }
#adder #arxiv-hits .hit > .link, #adder #arxiv-hits .hit > .have { grid-column:3; grid-row:1 / span 2; font-size:12px; }
#adder #arxiv-hits .hit > .sum { grid-column:2; grid-row:3; margin:2px 0 0; }
#adder .ad-foot { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-top:8px; }
#adder .ad-foot small { font-size:12px; color:var(--ink-3); }
/* F20: the drop cover */
#drop-cover { display:none; position:absolute; left:12px; right:12px; z-index:6; place-items:center; pointer-events:none;
  border:1.5px dashed var(--signal); border-radius:var(--r-card); background:rgba(243,245,247,.88); }
body.dropping #drop-cover { display:grid; }
body.dropping #log { outline:0; } body.dropping #log::before { content:none; display:none; }
#drop-cover .dc-in { display:flex; flex-direction:column; align-items:center; gap:6px; padding:16px; text-align:center; }
#drop-cover .dc-ico { width:48px; height:48px; display:grid; place-items:center; border-radius:12px; background:var(--white); box-shadow:var(--sh-md); color:var(--signal); }
#drop-cover b { font:600 15px/1.4 var(--sans); color:var(--ink); } #drop-cover small { font-size:12px; color:var(--ink-2); }
#drop-cover .dc-n { margin-top:6px; padding:3px 10px; border-radius:999px; background:var(--a6); font-size:11px; color:var(--ink-2); }
#drop-cover .dc-n[hidden] { display:none; }
/* S16: the model menu's items and its note */
.composer .mmenu button.mopt { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.composer .mmenu .mfoot { max-width:260px; white-space:normal; }
/* F26 the narrow window (≤900px): no rail, the sidebar a 70% drawer, the header two lines (name · panel · ⋯ / chips), the
   right column an overlay over the conversation (html body: above the older narrow rules further down) */
@media (max-width:900px) {
  html body, html body.panel, html body.rail { display:block; padding:0; }
  html body #chat { height:100vh; border:0; border-radius:0; box-shadow:none; }
  html body #side { display:none; position:fixed; inset:0 auto 0 0; width:70%; height:100vh; z-index:30; padding:14px 12px 12px; background:var(--canvas);
    border-radius:0 var(--r-panel) var(--r-panel) 0; box-shadow:0 0 0 100vmax rgba(13,14,16,.45); }
  html body.side #side { display:flex; }
  html body #menu { display:grid; place-items:center; width:var(--h-ctl); height:var(--h-ctl); padding:0; order:0; }
  html body #bar { padding:10px 12px; }
  #bar h1 { order:1; flex:1 1 0; } #bar .grow { display:none; } #bar #pnl { display:grid; order:2; } #bar #more { order:3; }
  #bar #chips { order:5; flex-basis:100%; }
  #tools { padding:4px 12px 10px; } #viewbar { margin:0 -12px; padding:10px 12px 0; }
  html body #right, html body.rail #right { display:none; }
  html body.panel #right { display:flex; position:fixed; inset:0; z-index:25; height:100vh; border:0; border-radius:0; box-shadow:none; }
  html body #right #panel { position:static; inset:auto; }
  .nt-two { grid-template-columns:1fr; }
  #settings .set-box { grid-template-columns:1fr; grid-template-rows:auto minmax(0, 1fr); }
  #settings .set-nav { flex-direction:row; flex-wrap:wrap; align-items:center; padding:12px; border-right:0; border-bottom:1px solid var(--a6); }
  #settings .set-nav > b { padding:0 10px 0 4px; }
  #settings .set-main { padding:16px 18px 20px; }
}
/* end A2 complete · A */
/* A2 complete · B conversation: messages, cards, views, composer, state cards (agent B) */
/* B1 messages: the person's avatar ink 6%, name 13 / time mono 11 */
.msg.user .av { background:var(--a6); color:var(--ink-2); border-color:transparent; }
.who small { font:400 11px/1 var(--mono); color:var(--ink-3); }
/* B2 / B3 tags: targets white on a hairline; a suggestion orange soft with 맞음 / 아님 and its reason under the row */
.tags { position:relative; gap:6px; }
.tg.tgt { background:var(--white); border:1px solid var(--a12); color:var(--ink-2); }
.tg.sug { background:var(--signal-soft); border:1px solid transparent; color:var(--ink); font-weight:600; }
.tg.sug .ico { color:var(--signal); } button.tg.sug { cursor:pointer; }
.tags .tagbtn.yes, .tags .tagbtn.no { color:var(--ink); font-weight:600; }
.tags .tagbtn[data-tag-edit] { color:var(--ink-3); }
.msg .sugwhy { margin:4px 0 0; font-size:12px; line-height:18px; color:var(--ink-3); }
/* B15 the tag popover (320) */
.tagedit { position:absolute; z-index:30; top:calc(100% + 6px); left:0; width:320px; max-width:calc(100vw - 32px); box-sizing:border-box;
  margin:0; padding:14px 16px; background:var(--white); border:1px solid var(--a8); border-radius:var(--r-card); box-shadow:var(--sh-lg);
  display:flex; flex-direction:column; gap:6px; font-size:13px; line-height:20px; color:var(--ink); }
.tagedit > b { font:600 14px/20px var(--sans); }
.te-sec { margin-top:6px; font:500 12px/16px var(--sans); color:var(--ink-3); }
.tagedit .te-stage { flex-direction:column; gap:2px; }
.te-stage label { display:flex; align-items:center; gap:8px; height:var(--h-in); padding:0 8px; border-radius:var(--r-tag); cursor:pointer; }
.te-stage label:has(input:checked) { background:var(--a6); font-weight:600; }
.te-stage label small { margin-left:auto; font:400 11px/1 var(--sans); color:var(--ink-3); }
.tagedit input[type=radio], .tagedit input[type=checkbox] { accent-color:var(--ink); margin:0; }
.te-tg { display:flex; flex-wrap:wrap; gap:6px; }
.te-x { margin-left:2px; padding:0 2px; border:0; background:none; color:var(--ink-3); font-size:12px; line-height:1; cursor:pointer; }
.te-x:hover { color:var(--ink); }
.te-add { height:var(--h-ctl); box-sizing:border-box; padding:0 10px; border:1px solid var(--a12); border-radius:var(--r-ctl); background:var(--white);
  font-size:12px; outline:none; } .te-add:focus { border-color:var(--ink-3); }
.te-dec { display:flex; align-items:center; gap:8px; min-height:var(--h-in); cursor:pointer; }
.te-crit { display:flex; flex-direction:column; gap:6px; padding-left:22px; } .te-crit[hidden] { display:none; }
.tagedit .te-foot { align-items:center; margin-top:6px; } .te-foot .te-note { flex:1; margin:0; font-size:11px; line-height:16px; color:var(--ink-3); }
/* B4-B6 the criteria notes: no avatar; added = orange soft band, held back = a card that asks, not read = grey band */
.msg.note { grid-template-columns:minmax(0, 1fr); margin-bottom:16px; }
.msg.note > .av, .msg.note .who, .msg.note .tags { display:none; }
.msg .band { display:flex; align-items:center; flex-wrap:wrap; gap:4px 10px; margin:0 0 8px; padding:10px 16px; border-radius:var(--r-in);
  font-size:14px; line-height:22px; color:var(--ink); }
.band.ok { background:var(--signal-soft); } .band.ok > .ico { flex:none; color:var(--signal); }
.band.q { background:var(--a5); color:var(--ink-2); font-size:13px; } .band.q > .ico { flex:none; color:var(--ink-3); }
.band .bt { flex:1 1 240px; min-width:0; } .band .bt b { font-weight:500; color:var(--ink); }
.band .rt { margin-left:auto; flex:none; display:inline-flex; align-items:center; gap:8px; } .band .em { display:none; }
.band .link .ico { vertical-align:-2px; }
.hold { margin:0 0 8px; padding:16px 20px; background:var(--white); border-left:3px solid var(--signal); border-radius:var(--r-card); box-shadow:var(--sh-md); }
.msg .hold p { margin:0; } .hold .ttl { font:600 14px/22px var(--sans); margin-bottom:6px !important; }
.hold b { font-weight:500; } .hold .acts { display:flex; gap:8px; margin-top:12px !important; }
.asmenu { display:inline-flex; gap:2px; padding:2px; background:var(--white); border:1px solid var(--a8); border-radius:var(--r-ctl); }
.asmenu[hidden] { display:none; }
.asmenu button { height:var(--h-in); padding:0 10px; border-radius:var(--r-tag); font:500 12px/1 var(--sans); color:var(--ink); }
.asmenu button:hover { background:var(--a5); }
.call .band { margin:6px 0; padding:8px 12px; }
/* cards: only what waits on the person has the orange edge (WARN, 결정, 다시 뽑기 확인); a record is white on a hairline;
   a BLOCK or a failure is grey; badges head them (막음 orange, 확인 필요 orange soft) */
.msg .call { margin:8px 0; padding:14px 18px; border:1px solid var(--a8); border-left:1px solid var(--a8); border-radius:var(--r-card);
  background:var(--white); box-shadow:var(--sh-sm); }
.msg .call p { margin:4px 0; } .msg .call .head { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin:0 0 6px; color:var(--ink);
  font:600 14px/22px var(--sans); }
.msg .call.warn:not(.settled), .msg .call:not(.block):not(.issue):not(.guard):not(.fail):not(.rp-done):not(.dl-card) { border-left:3px solid var(--signal); box-shadow:var(--sh-md); }
.msg .call.block { background:var(--a4); border-color:var(--a8); box-shadow:none; }
.msg .call.fail { background:var(--white); box-shadow:var(--sh-sm); } .msg .call.fail .head .ico { color:var(--ink-2); }
.call.lock .head::before { content:"막음"; flex:none; height:var(--h-tag); box-sizing:border-box; display:inline-flex; align-items:center; padding:0 7px;
  border-radius:var(--r-tag); background:var(--signal); color:#fff; font:600 11px/1 var(--sans); }
.call.warn .head::before { content:"확인 필요"; flex:none; height:var(--h-tag); box-sizing:border-box; display:inline-flex; align-items:center; padding:0 7px;
  border-radius:var(--r-tag); background:var(--signal-soft); color:var(--signal); font:600 11px/1 var(--sans); }
.call.compact .head code { background:none; padding:0; font:500 13px/22px var(--mono); }
.call .crit b { font-weight:600; color:var(--ink); } .call .crit:empty { display:none; }
.call .acts { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin:12px 0 0 !important; }  /* areas A and B: the one rule */
.call .foot, .call .acts + .foot { display:flex; align-items:center; gap:14px; flex-wrap:wrap; margin-top:8px; }
.call .foot details.tech { margin:0; } .call .foot details.tech[open] { flex-basis:100%; order:2; }
details.tech > summary { list-style:none; font:600 12px/20px var(--sans); color:var(--ink); cursor:pointer; }
details.tech > summary::-webkit-details-marker { display:none; } details.tech > summary::after { content:" ▸"; } details.tech[open] > summary::after { content:" ▾"; }
.call.issue { box-shadow:var(--sh-sm); } .call.issue .mascot.pose { height:44px; }
.call.fail .why { color:var(--ink-2); font-size:13px; }
.rev { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin:4px 0; font-size:13px; color:var(--ink-2); }
.rev.dec .ico { color:var(--ink-2); }
.tg.rv { background:var(--a6); border-color:transparent; color:var(--ink-2); }
.tg.rv-aligned { background:var(--a6); color:var(--ink); } .tg.rv-partial, .tg.rv-deviated { background:var(--signal-soft); color:var(--ink); }
.tg.rv-failed { background:var(--ink); color:#fff; }
/* B9 the changed files: a grey band, the buttons on its right */
.msg .changes { padding:0; border:0; background:none; box-shadow:none; }
.changes .chg-row { display:flex; align-items:center; gap:10px; flex-wrap:wrap; padding:10px 12px 10px 16px; background:var(--a5); border-radius:var(--r-in); }
.changes .chg-row > .ico { flex:none; color:var(--ink-2); }
.msg .changes .chg-t { flex:1 1 220px; margin:0; font-size:14px; line-height:22px; color:var(--ink); }
.changes .nums { font:500 12px/1 var(--mono); color:var(--ink-2); } .changes .gone { text-decoration:line-through; color:var(--ink-3); }
.changes .chg-acts { display:inline-flex; gap:8px; margin-left:auto; align-items:center; }
.pill.soft, .pill.warn { background:var(--signal-soft); border-color:transparent; color:var(--ink); } .pill.soft:hover:not(:disabled), .pill.warn:hover:not(:disabled) { background:#ffd3bd; }
.changes > pre.diff { margin:8px 0 0; } .changes .undo-err { margin:8px 0 0; display:flex; gap:6px; align-items:center; }
/* B7 the verification bar under a paper answer; S42 a stopped answer */
.msg .verify { display:flex; align-items:center; gap:8px; margin:8px 0; padding:6px 12px; background:var(--a5); border-radius:var(--r-ctl);
  font-size:12px; line-height:18px; color:var(--ink-2); } .verify .ico { flex:none; color:var(--ink-3); }
[data-web-only] { display:flex; gap:6px; align-items:center; font-size:12px; }
.msg .stopped { display:flex; align-items:center; gap:6px; font-size:12px; } .stopped .ico { color:var(--ink-3); }
.ask-pick { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }
/* S53 작업을 마침 */
.done-card { display:flex; gap:14px; align-items:flex-start; padding:16px 18px; background:var(--white); border:1px solid var(--a8); border-radius:var(--r-card);
  box-shadow:var(--sh-sm); } .done-card .mascot.pose { height:56px; margin:0; } .done-card .ttl { font:600 14px/22px var(--sans); margin:0 0 4px; }
.done-card .pill { display:inline-flex; gap:6px; }
/* B10 the conditions card · F25 the re-extraction diff · B11 the audit · B12 the table */
.msg .spec, .msg .audit, .msg .matrix:not(.wide), .redo-card { margin:10px 0; padding:16px 18px; background:var(--white); border:1px solid var(--a8);
  border-radius:var(--r-card); box-shadow:var(--sh-sm); }
.sp-top, .au-top, .mx-top { display:flex; align-items:flex-start; gap:10px; flex-wrap:wrap; }
.sp-top .head, .au-top .head, .mx-top .head { flex:1 1 200px; margin:0 !important; font:600 16px/24px var(--sans); }
.sp-acts { display:inline-flex; align-items:center; gap:12px; margin-left:auto; } .sp-acts .pill { gap:6px; }
.msg .sp-sub, .msg .au-sub { margin:4px 0 10px; font-size:12px; color:var(--ink-3); }
.chips { display:flex; gap:6px; flex-wrap:wrap; margin:0 0 10px; }
.pill.chip { padding:0 12px; font-size:12px; } .pill.chip.on { background:var(--white); color:var(--ink); border:1.5px solid var(--ink); font-weight:600; }
.spec .sp-cat { margin:0 0 8px; border:1px solid var(--a8); border-radius:var(--r-in); overflow:hidden; }
.spec .sp-cat h4 { display:flex; align-items:center; gap:6px; margin:0; padding:8px 12px; border:0; background:var(--a6); color:var(--ink);
  font:600 13px/20px var(--sans); cursor:pointer; } .spec .sp-cat h4 small { font-weight:400; color:var(--ink-3); }
.spec .sp-cat h4 .car { font-size:9px; color:var(--ink-2); } .spec .sp-cat h4 .hint { margin-left:auto; font-weight:400; font-size:12px; color:var(--ink-3); }
.spec .sp-cat ul, .redo-card .rd-list { list-style:none; margin:0; padding:0; }
.spec .sp-cat li, .redo-card .rd-list li { position:relative; display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin:0; padding:9px 12px;
  border-top:1px solid var(--a6); font-size:14px; line-height:22px; color:var(--ink); }
.spec .sp-cat li:first-child, .redo-card .rd-list li:first-child { border-top:0; }
.spec li .sx, .redo-card li .sx { flex:1 1 200px; min-width:0; }
.tg.kd { background:var(--a6); border-color:transparent; color:var(--ink-2); } .tg.wv { background:var(--signal-soft); border-color:transparent; color:var(--ink); margin-left:6px; }
.spec .sp-shutline { display:flex; flex-wrap:wrap; gap:4px 16px; margin:0 0 8px; padding:8px 12px; background:var(--a6); border-radius:var(--r-in); }
.sp-shut { background:none; border:0; padding:0; font:500 13px/20px var(--sans); color:var(--ink); cursor:pointer; } .sp-shut small { color:var(--ink-3); font-weight:400; }
.racts { display:inline-flex; align-items:center; gap:4px; flex-wrap:wrap; font-size:12px; }
.spec li > .racts, .audit li > .racts { opacity:0; transition:opacity .12s; }
.spec li:hover > .racts, .spec li:focus-within > .racts, .audit li:hover > .racts, .audit li:focus-within > .racts,
.spec li > .racts:has(input, select, .muted), .audit li > .racts:has(input, select, .muted) { opacity:1; }
.racts .edits .link, .racts > .link { font-size:12px; color:var(--ink-2); } .racts .why { max-width:220px; height:28px; box-sizing:border-box;
  border:1px solid var(--a12); border-radius:var(--r-ctl); padding:0 8px; font-size:12px; background:var(--white); }
.racts .why.need { border-color:var(--signal); box-shadow:0 0 0 3px var(--signal-soft); }
.redo-card .head { display:flex; align-items:center; gap:8px; margin:0 0 4px; font:600 14px/22px var(--sans); }
.redo-card .rd-sec { margin:10px 0 4px; font:500 12px/16px var(--sans); color:var(--ink-3); }
.redo-card .rd-list li { background:var(--a4); border-radius:var(--r-ctl); border-top:0; margin-top:4px; font-size:13px; }
.redo-card s { font:400 12px/1 var(--mono); color:var(--ink-3); } .redo-card .nv { font:600 12px/1 var(--mono); }
.redo-card .rd-gone > summary { list-style:none; margin-top:10px; font-size:12px; color:var(--ink-2); cursor:pointer; }
.redo-card .rd-gone > summary::-webkit-details-marker { display:none; } .redo-card .rd-gone:not([open]) > summary .ico { transform:rotate(-90deg); }
.redo-card .rd-list .rt { margin-left:auto; } .redo-card .rd-new { display:flex; flex-wrap:wrap; align-items:center; gap:6px; margin:10px 0 0; }
.redo-card .rd-new .rd-sec { margin:0 4px 0 0; }
.spec.replaced { background:var(--a4); box-shadow:none; } .spec.replaced .head { display:flex; align-items:center; gap:6px; font-size:14px; }
.audit .chips { margin-top:10px; } .msg .audit li { position:relative; padding:12px 0; }
.audit li > b.vb { display:inline-flex; align-items:center; height:var(--h-tag); box-sizing:border-box; padding:0 7px; border-radius:var(--r-tag);
  background:var(--a6); color:var(--ink-2); font:600 11px/1 var(--sans); vertical-align:1px; }
.audit li > b.vb-differs { background:var(--signal); color:#fff; } .audit li > b.vb-pairing, .audit li > b.vb-unclear { background:var(--signal-soft); color:var(--signal); }
.audit li > b.vb-intended { background:var(--white); border:1px solid var(--a12); color:var(--ink); } .audit li > b.vb-followed { background:var(--a6); color:var(--ink); }
.audit li > b.vb-missing { background:var(--white); border:1px solid var(--a12); color:var(--ink-2); }
.audit .pv { font:400 12px/1 var(--mono); color:var(--ink-3); } .audit li[hidden], .audit .outside[hidden] { display:none; }
.audit li > .racts { position:absolute; right:0; top:10px; background:linear-gradient(90deg, transparent, var(--white) 14px); padding-left:18px; }
.audit .stale { display:flex; align-items:center; gap:12px; flex-wrap:wrap; padding:12px 16px !important; border-radius:var(--r-in) !important; font-size:13px; }
.audit .stale > .pill { margin-left:auto; flex:none; }
.audit.au-fail { background:var(--white); } .audit.au-fail .head { display:flex; align-items:center; gap:6px; }
.matrix .metric { display:block; margin-top:2px; font:400 11px/16px var(--mono); color:var(--ink-3); }
.matrix .metric.differ { color:var(--signal); }
.matrix td:has(.cite.on) { background:var(--a5); box-shadow:inset 0 0 0 1.5px var(--a12); }
.matrix .mx-foot, .matrix .common { display:flex; flex-wrap:wrap; gap:6px 14px; align-items:center; margin:10px 0 0; font-size:12px; }
/* B13 단계별 · B16 대상별 · F24 거르기 */
#log .filtered { display:none !important; }
.stagegroup .sg-head { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.sg-head .sg-tog { margin-left:auto; font-size:12px; color:var(--ink-2); }
.sg-sum .sum-k { font-weight:600; } .sg-sum .sg-own { display:flex; align-items:center; gap:8px; margin:8px 0 0; }
.sg-sum .sg-own small { font-size:11px; color:var(--ink-3); } .sg-sum .sg-tools { margin:6px 0 0; font-size:12px; }
.sg-sum .sg-tools .link { font-size:12px; color:var(--ink-2); }
.sg-dh { margin:10px 0 4px; font:500 12px/16px var(--sans); color:var(--ink-3); } .sg-dec small { color:var(--ink-3); font-family:var(--mono); }
.sg-msgs[hidden] { display:none; } .sg-msgs { margin-top:12px; }
.spin { display:inline-block; width:10px; height:10px; border:1.5px solid var(--a12); border-top-color:var(--ink-2); border-radius:50%; animation:spin .8s linear infinite; vertical-align:-1px; }
@keyframes spin { to { transform:rotate(360deg); } }
.targetgroup > summary { list-style:none; display:flex; align-items:center; gap:8px; } .targetgroup > summary::-webkit-details-marker { display:none; }
.targetgroup > summary small { font-size:12px; color:var(--ink-3); font-family:var(--sans); }
.targetgroup > summary .tog { margin-left:auto; font-size:12px; color:var(--ink-2); } .targetgroup > summary .tog::after { content:"펼치기 ▸"; }
.targetgroup[open] > summary .tog::after { content:"접기 ▾"; }
.targetgroup:not([open]) { background:var(--a4); border-color:transparent; }
.targetgroup .tg-band { margin:0 0 12px; padding:6px 12px; background:var(--a5); border-radius:var(--r-ctl); font-size:12px; line-height:20px; color:var(--ink-2); }
#filter-banner { display:flex; align-items:center; gap:14px; flex-wrap:wrap; margin:0 auto 16px; padding:8px 16px; font-size:13px; color:var(--ink-2); }
#filter-banner .fb-t { flex:1 1 auto; } #filter-banner .link { font-size:13px; color:var(--ink); } #filter-banner .link .ico { vertical-align:-2px; }
.hidnote { max-width:680px; margin:-12px auto 16px; padding-left:40px; } .hidnote .link { font-size:12px; font-weight:500; color:var(--ink-3); }
.fmenu { position:fixed; z-index:40; width:320px; max-width:calc(100vw - 16px); box-sizing:border-box; padding:4px; background:var(--white);
  border:1px solid var(--a8); border-radius:10px; box-shadow:var(--sh-lg); }
.fmenu .mi { display:flex; align-items:center; gap:10px; width:100%; height:var(--h-ctl); padding:0 10px; border-radius:var(--r-ctl); background:none;
  font:500 13px/1 var(--sans); color:var(--ink); text-align:left; } .fmenu .mi:hover, .fmenu .mi.on { background:var(--a5); }
.fmenu .mi .mi-t { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; } .fmenu .mi small { color:var(--ink-3); font:400 11px/1 var(--mono); }
.fmenu .mi .ico { flex:none; color:var(--ink-2); } .fmenu .mi-note, .fmenu .mi-none { margin:4px 0 0; padding:6px 10px; border-top:1px solid var(--a6); font-size:11px; line-height:16px; color:var(--ink-3); }
/* B17 the composer: 보낼 곳 always, the stage it is recorded in, the model chip (모델 · 생각 수준) on a hairline, status, send */
#chat > .composer[data-agent] > button:first-of-type { order:6; width:auto; min-width:64px; height:var(--h-ctl); padding:0 14px; gap:6px;
  display:inline-flex; align-items:center; justify-content:center; border-radius:var(--r-ctl); background:var(--primary); color:var(--on-primary);
  font:600 13px/1 var(--sans); }
#chat > .composer[data-agent] > button:first-of-type:disabled { background:var(--a12); color:var(--white); }
#chat > .composer[data-agent][data-running="1"] > button:first-of-type { background:var(--signal-soft); color:var(--ink); }
#chat > .composer[data-agent][data-running="1"] > button:first-of-type .ico { fill:currentColor; color:var(--ink); }
#chat > .composer > button.modelbtn { border:1px solid var(--a12); padding:0 10px; gap:6px; font-family:var(--sans); color:var(--ink); }
.composer #route .seg > button:disabled { color:var(--ink-3); opacity:.55; cursor:not-allowed; }
#chat > .composer > .stagehint { order:2; color:var(--ink-3); } #chat > .composer > .stagehint .tg.stage { margin:0 2px; border-radius:var(--r-tag); padding:0 6px; font-weight:500; }
#chat > .composer > .mmenu { width:260px; padding:4px; border-radius:10px; }
.composer .mmenu .mm-h { margin:6px 10px 4px; font:500 11px/16px var(--sans); color:var(--ink-3); }
.composer .mmenu button.mopt { display:flex; align-items:center; justify-content:space-between; width:100%; height:var(--h-ctl); padding:0 10px; }
.composer .mm-seg { display:flex; gap:2px; margin:0 6px; padding:2px; background:var(--a5); border-radius:var(--r-ctl); }
.composer .mm-seg .mlv { flex:1; height:var(--h-in); padding:0 6px; border-radius:var(--r-tag); font:500 12px/1 var(--sans); color:var(--ink-2); background:none; }
.composer .mm-seg .mlv.on { background:var(--white); color:var(--ink); font-weight:600; box-shadow:var(--sh-sm); }
.composer .mmenu .mm-note { margin:6px 10px 6px; font-size:11px; line-height:16px; color:var(--ink-3); }
/* B18 / B19 progress cards (S5 / S7) · S12 download · S22 nowhere to send */
.msg .prog { margin:8px 0; padding:14px 16px; background:var(--a4); border-radius:var(--r-card); }
.prog .pg-bar0 { width:100px; height:3px; margin:0 0 8px; border-radius:2px; background:var(--signal); }
.msg .prog p { margin:0; } .prog .pg-st { font:600 13px/20px var(--sans); color:var(--ink); } .prog .pg-n { font:600 11px/1 var(--mono); color:var(--signal); }
.prog .pg-sub { font-size:12px; color:var(--ink-3); } .msg .prog .pg-t { margin-top:6px; font:500 14px/22px var(--sans); color:var(--ink); }
.prog .pg-bar { height:4px; margin:8px 0 10px; border-radius:2px; background:var(--a8); overflow:hidden; }
.prog .pg-bar > i { display:block; height:100%; width:3%; background:var(--ink); border-radius:2px; transition:width .4s ease; }
.prog .pg-foot { display:flex; align-items:center; gap:12px; font-size:12px; color:var(--ink-2); }
.dl-card .dl-file { display:flex; flex-direction:column; gap:2px; margin:6px 0; padding:10px 12px; background:var(--white); border:1px solid var(--a8); border-radius:var(--r-in); }
.dl-card .dl-file code { background:none; padding:0; font:500 13px/20px var(--mono); } .dl-card .dl-file small { font-size:12px; color:var(--ink-3); }
.call[data-route="none"] .acts .pill { gap:6px; }
@media (max-width:900px) { .tagedit { left:-34px; } .audit li > .racts { position:static; background:none; padding:0; opacity:1; }
  .spec li > .racts { opacity:1; } #chat > .composer > .stagehint { display:none; } }
/* B1 the stage divider: a grey tag (the task's current stage keeps its orange dot), the time, a hairline */
.divider .tg.stage { border-radius:var(--r-tag); padding:0 7px; font-weight:500; gap:5px; }
.divider:not([data-now]) .dot { display:none; }
/* visual pass (10/27). The column fills the conversation area with 32px sides (01 03 16): no 680 centring */
#log { padding:28px 32px 40px; }
.msg, .divider, .stagegroup, .targetgroup, #filter-banner, .hidnote { max-width:none; }
#chat > .composer { max-width:none; width:calc(100% - 64px); }
#shell-note, #adder, #notice .call { max-width:none; width:calc(100% - 64px); }
.msg { margin-bottom:20px; } .tags { margin-top:6px; } .hidnote { padding-left:0; }
/* a record card (조건 · 점검 · 비교표 · 다시 뽑은 뒤) has its tags under the name, above the card (06 07 08 F25) */
.msg .tags.top { margin:0 0 2px; }
/* inline [n]: bold ink text in conversation text and cards (03 04 05 08); p.N (.pgc) and web cites stay chips */
#log .cite:not(.pgc):not(.web) { display:inline; height:auto; padding:0; margin-left:2px; border-radius:0; background:none; box-shadow:none;
  font-family:var(--sans); font-size:inherit; font-weight:700; line-height:inherit; color:var(--ink); vertical-align:baseline; }
#log .cite:not(.pgc):not(.web):hover { text-decoration:underline; text-decoration-color:var(--ink-3); }
#log .cite:not(.pgc):not(.web).on { background:none; color:var(--signal); text-decoration:underline; }
/* diff lines in the conversation are grey bands, not green / red (04, S50) */
#log pre.diff .add, #log pre.diff .del { margin:0 6px; padding:0 4px; border-radius:4px; background:var(--a6); }
/* 08 the compare table: a grey head band, rows split by hairlines only */
.msg .matrix:not(.wide) .scroll { border-color:var(--a8); }
.msg .matrix:not(.wide) th, .msg .matrix:not(.wide) td { border-left:0; border-right:0; padding:10px 12px; }
.msg .matrix:not(.wide) thead th { background:var(--a6); color:var(--ink); border-bottom:0; }
/* 07 the audit: rows in one hairline box; the category small grey, the condition 14 medium, its p.N on the right */
.msg .audit > ul { margin:0; padding:0 16px; list-style:none; border:1px solid var(--a8); border-radius:var(--r-in); }
.msg .audit > ul > li:first-child { border-top:0; }
.audit .au-cat { margin:0 4px; font-size:12px; color:var(--ink-3); } .audit .au-t { font-weight:500; color:var(--ink); }
.audit li .au-pg { float:right; margin:1px 0 0 8px; }
/* 06 the conditions row: its warnings on the row's right, before p.N */
.spec .sp-cat li > .tg.wv { margin-left:0; }
/* composer (03 04 06): [모델 · 수준] [준비됨] [보내기]; the status takes the free space when the model chip is hidden */
#chat > .composer > button.modelbtn { order:3; margin-left:auto; }
#chat > .composer > #agent { order:4; margin-left:0; }
#chat > .composer:has(> button.modelbtn[hidden]) > #agent { margin-left:auto; }
#chat > .composer[data-agent] > button:first-of-type { margin-left:0; }
/* end A2 complete · B */
/* A2 complete · C right column: tabs, panel, rail, evidence, wide table (agent C) */
#panel { position:relative; }
/* tabs: two lines each; the orange dot on the open tab and on a tab with something waiting; a tab with nothing yet is
   grey and says on hover when it opens (S67) */
.ptab { position:relative; }
.ptab.attn b::before { content:""; flex:none; width:6px; height:6px; border-radius:50%; background:var(--signal); }
.ptab:disabled { opacity:1; } .ptab:disabled b, .ptab:disabled small { color:var(--ink-3); }
.ptab[data-tip]:hover::after { content:attr(data-tip); position:absolute; left:2px; top:calc(100% + 8px); z-index:8; white-space:nowrap;
  padding:6px 10px; border-radius:var(--r-ctl); background:var(--primary); color:var(--on-primary); font:500 12px/1.4 var(--sans);
  box-shadow:var(--sh-md); pointer-events:none; }
body:not(.panel) .ptab[data-tip]:hover::after { left:auto; right:calc(100% + 8px); top:4px; }
#ptabs .unfold { display:none; }
body:not(.panel) #ptabs .unfold { display:flex; align-items:center; justify-content:center; gap:2px; height:var(--h-in); margin:0 0 4px;
  border-radius:var(--r-ctl); font:500 11px/1 var(--sans); color:var(--ink-2); }
body:not(.panel) #ptabs .unfold:hover { background:var(--a5); color:var(--ink); }
/* the head: the panel's name, "접기 ›" (a narrow window's overlay: "닫기 ×") */
.phead { padding:12px 14px 10px 20px; min-height:0; border-bottom:1px solid var(--a6); }
.phead h2 { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.phead .x.fold { width:auto; height:var(--h-in); padding:0 4px 0 6px; display:inline-flex; align-items:center; font:500 12px/1 var(--sans); color:var(--ink-2); }
.phead .x.fold > span { display:inline-flex; align-items:center; gap:2px; } .phead .x.fold > .n { display:none; }
.phead .widen { flex:none; background:none; border:0; cursor:pointer; border-radius:var(--r-ctl); width:auto; height:var(--h-in); padding:0 6px; font:500 12px/1 var(--sans); color:var(--ink-2); white-space:nowrap; }  /* demo 10/27 */
@media (max-width:900px) { .phead .widen { display:none; } }
@media (max-width:900px) { .phead .x.fold > .w { display:none; } .phead .x.fold > .n { display:inline-flex; } }
/* a row under the head: back / forward, the source or file picker, page turns or the folder line */
.ptool { display:flex; align-items:center; gap:4px; padding:12px 16px 0 18px; flex-wrap:wrap; }
.ptool .sp { flex:1; } .ptool .meta { font-size:12px; color:var(--ink-2); }
.ptool .pnum { font:600 13px/1 var(--mono); color:var(--ink); padding:0 4px; }
.ptool .nav.pg-t { width:24px; height:24px; }
.ptool.acts { gap:8px; padding-top:10px; }
.ptool .url.pick { margin:0 0 0 6px; height:var(--h-ctl); max-width:260px; display:inline-flex; align-items:center; gap:4px; padding:0 8px 0 10px;
  background:var(--white); border:1px solid var(--a12); border-radius:var(--r-ctl); font:500 12px/1 var(--sans); color:var(--ink); }
.ptool .url.pick:hover { background:var(--a4); }
.ptool .url.pick b { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:600; }
.ptool .url.pick > .ico:first-child { margin-right:2px; }
/* menus (a2/menu-item 32 · r10 frame · shadow-lg · padding 4) */
.mwrap { position:relative; display:inline-flex; min-width:0; }
.pmenu { position:absolute; top:calc(100% + 6px); left:0; z-index:9; width:290px; padding:4px; background:var(--white);
  border:1px solid var(--a8); border-radius:var(--r-in); box-shadow:var(--sh-lg); }
.pmenu.right { left:auto; right:0; } .pmenu[hidden] { display:none; }
.pmenu .mi { display:flex; align-items:center; gap:8px; width:100%; height:var(--h-ctl); padding:0 10px; border-radius:var(--r-ctl);
  font:500 13px/1 var(--sans); color:var(--ink); text-align:left; }
.pmenu .mi:hover:not(:disabled), .pmenu .mi.on { background:var(--a5); } .pmenu .mi.on span { font-weight:600; }
.pmenu .mi span { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.pmenu .mi small { font:11px/1 var(--mono); color:var(--ink-3); } .pmenu .mi .ico { color:var(--ink-2); flex:none; }
.pmenu .mi:disabled { opacity:1; color:var(--ink-3); } .pmenu p.mi { color:var(--ink-3); margin:0; }
.pmenu .note { margin:4px 0 0; padding:8px 10px 6px; border-top:1px solid var(--a6); font-size:11px; line-height:1.5; color:var(--ink-3); }
/* bands: who points at this (+ 대화로 거르기), the status line */
.band { display:flex; align-items:center; gap:8px; margin:10px 16px 0 18px; padding:6px 10px; border-radius:var(--r-ctl); background:var(--a5);
  font-size:12px; line-height:1.5; color:var(--ink-2); }
.band > span { flex:1; min-width:0; } .band .link { font:600 12px/1.4 var(--sans); color:var(--ink); white-space:nowrap; }
.band.warn { background:var(--signal-soft); color:var(--ink); }
#pbody .band { margin:12px 0 0; }
#panel > .info { margin:10px 16px 0 18px; } .info:empty { display:none; } .info .link { font-size:12px; }
#pbody { padding:12px 16px 18px 18px; }
.pfoot2 { display:flex; gap:16px; align-items:center; padding:10px 18px 14px; border-top:1px solid var(--a6); }
.pfoot2 a, .pfoot2 .link { font:600 12px/1.4 var(--sans); color:var(--ink); text-decoration:none; }
/* cards for an empty or failed place (S11, S64, S65, S67–S69, C7) */
.pcard { margin:4px 0 0; padding:14px 16px; border-radius:var(--r-card); background:var(--a5); }
.pcard.white { background:var(--white); border:1px solid var(--a8); }
.pcard > b { display:block; font:600 14px/1.45 var(--sans); color:var(--ink); }
.pcard > p { margin:4px 0 0; font-size:12px; line-height:1.6; color:var(--ink-2); }
.pcard .btns { display:flex; gap:12px; align-items:center; margin-top:10px; }
.pcard > .link { display:inline-block; margin:10px 12px 0 0; font:600 12px/1.4 var(--sans); }
.pcard .addrow { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-top:10px; }
.pcard .addrow input { flex:1 1 180px; height:var(--h-ctl); box-sizing:border-box; border:1px solid var(--a12); border-radius:var(--r-ctl);
  background:var(--white); padding:0 10px; font:13px/1 var(--sans); color:var(--ink); outline:none; }
.pcard .addrow input:focus { border-color:var(--ink-3); } .pcard .addrow .link { font-size:12px; }
/* 기준: the goal as words; headings with counts; rows with back-links; a picked row grey */
#pbody h3 { display:flex; align-items:baseline; gap:6px; }
#pbody h3 .n { font:500 12px/1 var(--mono); color:var(--ink-3); } #pbody h3 .paper { font:500 12px/1 var(--mono); color:var(--ink-3); }
#pbody .goal { position:relative; margin:0 2px 4px; font:500 15px/1.55 var(--sans); color:var(--ink); }
#pbody .goal > .edits { position:absolute; right:0; top:0; opacity:0; } #pbody .goal:hover > .edits, #pbody .goal > .edits:has(input) { opacity:1; position:static; display:block; }
#panel ul.ck > li { --row:var(--white); }
#panel ul.ck > li:has(> .meta), #panel ul.ck.dev > li { cursor:pointer; }
#panel ul.ck > li.sel { --row:#ECECED; background:var(--row); box-shadow:inset 0 0 0 1px var(--a12); }
#panel ul.ck > li > .edits, #panel ul.ck > li > .acts { background:linear-gradient(90deg, transparent, var(--row) 14px); }
#panel ul.ck .prev { font-size:12px; color:var(--ink-3); margin-top:2px; }
#panel ul.ck .meta { display:flex; flex-wrap:wrap; align-items:center; gap:4px; margin-top:6px; }
.backs { display:inline-flex; flex-wrap:wrap; gap:4px; }
.bk, .human { display:inline-flex; align-items:center; gap:4px; height:var(--h-tag); box-sizing:border-box; padding:0 6px; border-radius:var(--r-tag);
  background:var(--a5); font:500 11px/1 var(--sans); color:var(--ink-2); white-space:nowrap; }
.bk .ico { color:var(--ink-3); } .bk.wait { background:var(--signal-soft); color:var(--ink); }
.human { background:var(--white); border:1px solid var(--a12); color:var(--ink); }
#panel ul.ck .edits { display:inline-flex; align-items:center; gap:6px; }
#panel ul.ck .edits .link { display:inline-flex; align-items:center; gap:3px; }
#panel ul.ck .edits .link.ib { width:24px; height:24px; justify-content:center; border-radius:6px; }
#panel ul.ck .edits .link.ib:hover { background:var(--a5); }
/* a row's form (S56 고치기, S57 지우기, S58 의도한 차이, S59 빼기): the box, then the buttons; " · " between them goes */
#panel .edits:has(input, select), #panel ul.ck li .edits:has(input, select) { display:block !important; font-size:0; }
#panel .edits:has(input, select) > * { font-size:12px; }
#panel .edits:has(input, select) .why, #panel ul.ck li .edits:has(input, select) .why { display:block; width:100%; height:var(--h-ctl); box-sizing:border-box; margin:6px 0 8px; font-size:13px; }
#panel .edits:has(input, select) > .link, #panel .edits .ebtns .link { display:inline-flex; align-items:center; height:28px; padding:0 12px; margin-right:8px;
  border:1px solid var(--a12); border-radius:var(--r-ctl); background:var(--white); color:var(--ink); font:600 12px/1 var(--sans); }
#panel ul.ck .acts:has(input, select) { font-size:0; opacity:1; position:static; display:block; margin-top:6px; padding:0; background:none; }
#panel ul.ck .acts:has(input, select) > .edits:not(:has(input, select)) { display:none !important; }
#panel .edits .ebtns { display:flex; align-items:center; flex-wrap:wrap; gap:0; }
#panel .edits .ebtns small { font-size:11px; color:var(--ink-3); }
#panel .edits .link.dark, #panel [data-deviate-ok] { background:var(--primary) !important; color:var(--on-primary) !important; border-color:var(--primary) !important; }
#panel .edits .link.soft, #panel [data-spec-drop-ok] { background:var(--signal-soft) !important; border-color:transparent !important; }
/* 논문 조건: a count per kind, what is still open, 조건 보기 · 다시 뽑기; the list behind it */
.cond { background:var(--white); border:1px solid var(--a8); border-radius:var(--r-card); padding:12px; }
.cond .nums { display:flex; flex-wrap:wrap; gap:6px; }
.cnum { display:inline-flex; align-items:center; gap:6px; height:var(--h-ctl); padding:0 10px; border-radius:var(--r-ctl); background:var(--a5); }
.cnum:hover { background:var(--a8); } .cnum b { font:600 14px/1 var(--sans); color:var(--ink); } .cnum small { font-size:11px; color:var(--ink-3); }
.cond .open { display:flex; align-items:center; gap:6px; margin:10px 2px 0; font-size:12px; color:var(--ink-2); }
.cond .open::before { content:""; width:6px; height:6px; border-radius:50%; background:var(--signal); flex:none; }
.cond .links { display:flex; gap:16px; margin:8px 2px 0; } .cond .links .link { font:600 12px/1.4 var(--sans); color:var(--ink); }
.cond .condlist { margin-top:10px; border-top:1px solid var(--a6); } .cond .condlist[hidden] { display:none; }
.cond .condlist ul.ck { border:0; border-radius:0; } .cond h4.kopen { font:600 12px/1.4 var(--sans); color:var(--ink-2); margin:14px 2px 6px; }
#panel ul.ck.dev .ct { font-size:14px; }
/* 계획: rows; the current one grey */
#panel ol.steps.prow { background:none; border:0; border-radius:0; overflow:visible; display:flex; flex-direction:column; gap:4px; }
#panel ol.prow li { display:block; border:1px solid transparent; border-radius:var(--r-in); padding:9px 12px; cursor:pointer; }
#panel ol.prow li:hover { background:var(--a4); }
#panel ol.prow li.cur { background:var(--a8); border-color:var(--a12); }
#panel ol.prow li.sel { box-shadow:inset 0 0 0 1.5px var(--ink); }
#panel ol.prow .pr { display:flex; align-items:baseline; gap:8px; }
#panel ol.prow .pid, .tl .pid { font:500 12px/1.5 var(--mono); color:var(--ink-3); }
#panel ol.prow .pa { font:500 14px/1.5 var(--sans); color:var(--ink); } #panel ol.prow li.cur .pa { font-weight:600; }
#panel ol.prow li.old .pa { color:var(--ink-2); }
#panel ol.prow .mk { display:inline-grid; place-items:center; } #panel ol.prow .mk.now { width:7px; height:7px; border-radius:50%; background:var(--ink); align-self:center; }
#panel ol.prow .sub { display:block; margin-top:2px; font-size:12px; color:var(--ink-2); } #panel ol.prow .sub b { font-weight:600; color:var(--ink); }
#pbody [data-plan-how] { font-size:12px; line-height:1.6; color:var(--ink-2); margin:14px 2px 0; }
/* 왜?: where it stands now a filled dot; what has not happened yet grey */
.tl li::after { width:12px; height:12px; top:4px; left:-1px; border-color:var(--ink); }
.tl li.now::after { background:var(--ink); border-color:var(--ink); }
.tl li.wait .k, .tl li.wait .v { color:var(--ink-3); font-weight:500; }
.tl li.wait::after { border-color:var(--ink-3); }
.tl .v code { font-size:12px; }
/* evidence: the page as a white sheet; code on grey with the marked line; the web paragraph orange */
#pbody.pdf { background:none; padding:12px 16px 16px 18px; }
.pg { background:var(--white); border:1px solid var(--a8); border-radius:var(--r-card); overflow:hidden; box-shadow:none; }
#pbody.pdf.astext #doc, #doc { background:var(--white); border:1px solid var(--a8); border-radius:var(--r-card); padding:18px 20px; }
#pbody.pdf.astext #doc .b { white-space:pre-wrap; font-size:13px; line-height:1.6; }
#doc .b.shown { background:var(--signal-soft); border-left:3px solid var(--signal); padding:8px 12px; border-radius:4px; }
.urlrow { display:flex; align-items:center; gap:4px; margin:10px 16px 0 18px; height:36px; padding:0 4px 0 12px; border:1px solid var(--a8);
  border-radius:var(--r-ctl); background:var(--white); font-size:12px; color:var(--ink-2); min-width:0; }
.urlrow > .ico { color:var(--ink-3); margin-right:4px; flex:none; } .urlrow b { color:var(--ink); font-weight:600; white-space:nowrap; }
.urlrow > span { white-space:nowrap; } .urlrow small { flex:1; min-width:0; margin-left:8px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font:11px/1 var(--mono); color:var(--ink-3); }
#pbody.code { flex:0 1 auto; min-height:0; margin:12px 16px 0 18px; padding:8px 0; border:0; border-radius:var(--r-card); background:var(--a5); }
.src .ln.on { background:var(--a8); box-shadow:inset 0 0 0 1px var(--a12); border-radius:6px; }
.lnote { margin:10px 18px 0; font-size:12px; line-height:1.6; color:var(--ink-2); } .lnote[hidden] { display:none; }
/* F22: the floating button over a picked sentence, then the card */
#pick.float { position:absolute; z-index:7; padding:0; gap:0; background:none; border:0; display:block; }
#pick.float[hidden], #pick.form[hidden] { display:none; }
#pick .fbtn { height:var(--h-ctl); display:inline-flex; align-items:center; gap:6px; padding:0 12px; border-radius:var(--r-ctl);
  background:var(--primary); color:var(--on-primary); font:600 12px/1 var(--sans); box-shadow:var(--sh-md); white-space:nowrap; }
#pick .tip { display:inline-block; padding:6px 10px; border-radius:var(--r-ctl); background:var(--primary); color:var(--on-primary); font-size:12px; }
#pick.form { position:absolute; left:18px; right:16px; bottom:14px; z-index:7; display:flex; flex-direction:column; gap:10px; padding:14px 16px;
  background:var(--white); border:1px solid var(--a8); border-radius:var(--r-card); box-shadow:var(--sh-lg); font-size:13px; }
#pick.form .q { border-left:3px solid var(--signal); padding:2px 0 2px 12px; color:var(--ink); max-height:5.6em; overflow:auto; line-height:1.55; }
#pick.form .q small { color:var(--ink-3); }
#pick.form label { display:flex; flex-direction:column; gap:4px; font-size:12px; color:var(--ink-2); min-width:0; }
#pick.form [data-statement] { flex:none; }
#pick.form .grid { display:grid; grid-template-columns:minmax(0, 1fr) 104px; gap:8px; }
#pick.form input, #pick.form select { width:100%; height:var(--h-ctl); box-sizing:border-box; border:1px solid var(--a12); border-radius:var(--r-ctl);
  padding:0 10px; background:var(--white); font:13px/1 var(--sans); color:var(--ink); }
#pick .simnote { display:flex; gap:8px; align-items:flex-start; padding:8px 10px; border-radius:var(--r-ctl); background:var(--a5); font-size:12px; line-height:1.5; color:var(--ink-2); }
#pick .simnote > .ico { flex:none; margin-top:2px; } #pick .simnote:has([data-pick-note]:empty) { display:none; }
#pick .simnote .link.strong { font-weight:600; color:var(--ink); white-space:nowrap; }
#pick.form .row { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
#pick.form .row > .link { height:var(--h-ctl); padding:0 14px; display:inline-flex; align-items:center; border:1px solid var(--a12); border-radius:var(--r-ctl);
  background:var(--white); color:var(--ink); font:600 12px/1 var(--sans); }
#pick.form .row small { font-size:12px; color:var(--ink-3); }
#pick.form.done { flex-direction:row; align-items:center; justify-content:space-between; }
/* F21: the wide table (835): what it is and its buttons, the column form, a shared column, the way back */
body.panel.wide { grid-template-columns:var(--side-w) minmax(0, 1fr) min(835px, 58vw); }
#pbody.mx { padding:14px 16px 18px 18px; }
.mxtool { display:flex; align-items:flex-start; gap:8px; flex-wrap:wrap; }
.mxtool .t { flex:1 1 220px; min-width:0; } .mxtool .t b { display:block; font:600 14px/1.4 var(--sans); color:var(--ink); }
.mxtool .t small { font-size:12px; color:var(--ink-2); } .mxtool .pill { display:inline-flex; align-items:center; gap:6px; }
.colsform { margin-top:12px; background:var(--white); border:1px solid var(--a8); border-radius:var(--r-card); padding:12px 14px; }
.colsform .row { display:flex; align-items:center; gap:8px; flex-wrap:wrap; } .colsform .row > b { font:600 13px/1 var(--sans); }
.colsform input.cols { flex:1 1 220px; min-width:0; height:var(--h-ctl); box-sizing:border-box; margin:0; border:1px solid var(--a12); border-radius:var(--r-ctl);
  padding:0 10px; background:var(--white); font:13px/1 var(--sans); color:var(--ink); }
.colsform .cnt { font:12px/1 var(--mono); color:var(--ink-2); } .colsform .cnt.over { color:var(--signal); font-weight:600; }
.colsform small { display:block; margin-top:8px; font-size:12px; color:var(--ink-3); }
#panel .matrix.wide { margin-top:14px; } #panel .matrix.wide .scroll { background:var(--white); border:1px solid var(--a8); border-radius:var(--r-card); overflow:auto; }
#panel .matrix.wide th, #panel .matrix.wide td { font-size:13px; } #panel .matrix.wide .metric { font-family:var(--mono); }
#panel .matrix.wide td.picked { background:var(--a5); box-shadow:inset 0 0 0 1.5px var(--ink-3); }
.mxsug { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:12px; padding:8px 12px; border-radius:var(--r-ctl); background:var(--a5);
  font-size:12px; color:var(--ink-2); } .mxsug .link { display:inline-flex; align-items:center; gap:4px; font:600 12px/1.4 var(--sans); color:var(--ink); }
.mxfoot { display:flex; gap:16px; align-items:baseline; flex-wrap:wrap; margin-top:14px; font-size:12px; color:var(--ink-3); }
.mxfoot .link { font:600 12px/1.4 var(--sans); color:var(--ink); }
#log .matrix.flash { box-shadow:0 0 0 3px var(--signal-soft); transition:box-shadow .3s; }
/* visual pass (10/27) against 03–08, 10, V2–V4: every panel is 390 (only the wide table is 835); the tab summaries
   10px so "반드시 4 · 가능 1" fits; ✎ 고치기 puts the box in place of the row's words (S56), a form hides the chips (S57);
   the 왜? dots ink (only now filled); the live web page in the same white card as the snapshot (F23) */
body.panel:not(.wide) { grid-template-columns:var(--side-w) minmax(0, 1fr) 390px; }
body.panel .ptab { padding:7px 8px; } body.panel .ptab small { font-size:10px; letter-spacing:-.1px; }
#panel ul.ck > li:has([data-edit-in]) > :is(.ct, .prev, .meta) { display:none; }
#panel ul.ck > li:has(> .edits :is(input, select), > .acts :is(input, select)) > .meta { display:none; }
#panel ul.ck > li:has([data-edit-in]) [data-edit-in] { margin-top:0; }
.tl li.warn::after { border-color:var(--ink); }
#pbody.live { margin:12px 16px 16px 18px; border:1px solid var(--a8); border-radius:var(--r-card); background:var(--white); }
/* at 390 the code row keeps 작업 폴더 · 읽기 전용 · N줄 on the picker's line (07) */
body.panel #panel .ptool { gap:2px; } body.panel #panel .ptool .url.pick { margin-left:4px; } body.panel #panel .ptool .meta { font-size:11px; white-space:nowrap; }
/* end A2 complete · C */
/* A2 complete · finishing pass (S8 비슷한 문장, S12 내려받기 확인 자리, S52, merged card actions) */
/* 09 보고서 내보내기: the parts right under their heading; unpicked ones grey */
.dlg.rp .dlg-body > h4:first-child { margin-bottom:-10px; } .rp-row:has(input:not(:checked)) span { color:var(--ink-3); }
/* 13–15 values on the right are plain mono text; a path is a grey box */
#settings .set-opts code { padding:0; background:none; color:var(--ink-2); font:400 12px/1.5 var(--mono); }
.set-path { margin:-4px 0 8px; padding:7px 10px; border-radius:var(--r-ctl); background:var(--a5); font:400 12px/1.4 var(--mono); color:var(--ink-2); }
/* S2 · S3 · S34: a failed account card is a plain card (the orange edge is for cards that ask: S20 · S21 · S45) */
#acct .acard.bad { border-left:1px solid var(--a8); }
/* 26a 좁은 창: the conversation and the composer run 16 from the column's edges */
@media (max-width:900px) { #log { padding-left:16px; padding-right:16px; } .msg, .divider { max-width:none; }
  #chat > .composer, #shell-note, #adder, #notice .call { max-width:none; width:calc(100% - 32px); } }
/* S17: while the name is edited, the row is the field and its buttons (the kind tag waits) */
#bar:has(#task-name) .kindtag { display:none; }
/* 18 the source card rows: two tight lines, the second in the text font */
.srccard #src .ptitle { line-height:20px; } .srccard #src .pmeta { font:400 11px/16px var(--sans); }
/* 02 새 작업: one-line fields (32), kind cards on a light fill, the picked one filled and edged; 선택 안 함 when picked */
.nt #goal { min-height:var(--h-ctl); height:var(--h-ctl); padding:6px 12px; font:400 13px/18px var(--sans); box-sizing:border-box; }
#nt-crit { min-height:var(--h-ctl); height:var(--h-ctl); padding:6px 12px; line-height:18px; box-sizing:border-box; }
.nt .kinds .kind { background:var(--a4); border:1px solid var(--a8); padding:10px 14px; }
.nt .kinds .kind:has(input:checked) { background:var(--canvas); border:2px solid var(--a12); padding:9px 13px; }
.nt [data-folder-none].sel { background:var(--canvas); border-color:transparent; box-shadow:none; color:var(--ink-3); }
#viewbar .fchip { height:var(--h-ctl); gap:6px; padding:0 10px; border:1.5px solid var(--ink); border-radius:var(--r-ctl); background:var(--white); font:600 12px/1 var(--sans); max-width:320px; }
#viewbar .fchip:hover { background:var(--a4); } #viewbar .fchip .fc-t { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; }
.call.rp-done .head { display:flex; align-items:center; gap:8px; }
.call.rp-done .rp-file { margin-top:6px; font-size:12px; color:var(--ink-3); }
.call.rp-done .rp-file code { padding:0; background:none; font:12px/1.5 var(--mono); color:var(--ink-2); }
.call.rp-done .acts .link { font:600 12px/1.4 var(--sans); color:var(--ink); }
#arxiv-dl .dl-card, .nt-dl .dl-card { margin:8px 0 0; max-width:420px; }
.call.dl-card { background:var(--a5); border-left:0; box-shadow:none; }  /* S12 asks, but is not a Guard-like decision: grey, no orange edge */
.msg .call.rp-done { box-shadow:var(--sh-sm); }  /* S52: a result, not a question (no orange edge) */
.nt-dl:empty { display:none; }
#pbody.pdf.s8 { padding:12px 16px 16px 18px; }
.pcard.s8 { margin:0; }
.pcard.s8 .s8head { margin:-2px -4px 0; padding:8px 12px; border-radius:var(--r-ctl); background:var(--a8); font:600 12px/1.5 var(--sans); color:var(--ink); }
.pcard.s8 .s8hits { display:flex; flex-direction:column; gap:4px; margin-top:8px; }
.pcard.s8 .s8hit { display:flex; gap:8px; align-items:baseline; width:100%; min-height:var(--h-ctl); box-sizing:border-box; padding:6px 10px; text-align:left;
  border:1px solid var(--a8); border-radius:var(--r-ctl); background:var(--white); font:12px/1.5 var(--sans); color:var(--ink-2); cursor:pointer; }
.pcard.s8 .s8hit span { flex:1; min-width:0; overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; }
.pcard.s8 .s8hit small { flex:none; font:500 11px/1.5 var(--mono); color:var(--ink-3); }
.pcard.s8 .s8hit:hover { border-color:var(--a12); } .pcard.s8 .s8hit.on { border-color:var(--ink-3); color:var(--ink); }
.pcard.s8 > p { margin-top:10px; color:var(--ink-3); }
.pcard.s8 #doc { margin-top:6px; padding:0; background:none; border:0; }
.pcard.s8 #doc .b { white-space:pre-wrap; font-size:12px; line-height:1.7; color:var(--ink-2); }
.pcard.s8 .btns .link { font:600 12px/1.4 var(--sans); }
/* demo 10/27: the composer's message box wraps and grows (a textarea: 8 lines, then it scrolls) */
.composer textarea { flex:1; border:0; background:none; outline:none; min-width:0; resize:none; font:inherit; color:inherit; }
#chat > .composer > textarea { order:-5; flex:1 1 100%; font-size:14px; line-height:22px; padding:2px 0 4px; max-height:200px; overflow-y:auto; }
#chat > .composer > textarea::placeholder { color:var(--ink-3); }
#chat > .composer > textarea + button { margin-left:auto; }
/* demo 10/27: the conversation's foot while the agent works (working()) */
.msg.working .wk { display:flex; gap:12px; align-items:flex-start; padding:10px 14px; border-radius:10px; background:var(--a5); max-width:640px; }
.msg.working .wk .mascot.bob { flex:none; width:34px; height:auto; margin-top:2px; }
.msg.working .wk-b { min-width:0; flex:1; }
.msg.working .wk-h { margin:0; display:flex; align-items:center; gap:8px; font-size:13px; }
/* demo 10/28: what it is on now wraps (3 lines at most), it is not cut to one line */
.msg.working .wk-t { margin:4px 0 0; font-size:12px; line-height:18px; color:var(--ink-2); white-space:pre-wrap; overflow-wrap:anywhere;
  display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:3; overflow:hidden; }
/* demo 10/27: the right column is as wide as its left edge is dragged (--pw); the wide table at least as before */
body.panel:not(.wide) { grid-template-columns:var(--side-w) minmax(0, 1fr) var(--pw, 390px); }
body.panel.wide { grid-template-columns:var(--side-w) minmax(0, 1fr) max(var(--pw, 390px), min(835px, 58vw)); }
body.panel #right { position:relative; }
#pgrip { display:none; }
body.panel #pgrip { display:block; position:absolute; left:-6px; top:0; bottom:0; width:10px; cursor:col-resize; z-index:6; }
body.panel #pgrip:hover, body.panel #pgrip.on { background:linear-gradient(to right, transparent 4px, var(--a12) 4px, var(--a12) 6px, transparent 6px); }
body.dragging { cursor:col-resize; user-select:none; } body.dragging #panel { pointer-events:none; }
@media (max-width:900px) { body.panel #pgrip { display:none; } }
/* demo 10/28: every action in the conversation and the right column looks like a button, never bare text: in a card's
   action row (.acts …) a secondary 32px button beside the pills, elsewhere (a band's end, a row's hover actions, a card's
   foot, 기술 세부정보) a small 24px outlined one (.mini, the same look). 출처 [n] (.cite) and 파일:줄 (.file) stay links */
:is(#log, #panel) :is(button, a).link, :is(#log, #panel) details.tech > summary, .mini {
  display:inline-flex; align-items:center; gap:4px; height:var(--h-in); padding:0 10px; margin:2px 0; box-sizing:border-box; vertical-align:middle;
  border:1px solid var(--a12); border-radius:var(--r-ctl); background:var(--white); color:var(--ink); font:500 12px/1 var(--sans);
  text-decoration:none; white-space:nowrap; cursor:pointer; }
:is(#log, #panel) :is(button, a).link:hover, :is(#log, #panel) details.tech > summary:hover, .mini:hover { background:var(--a5); }
:is(#log, #panel) :is(.acts, .sp-acts, .btns, .ptool, .pfoot2) > :is(button, a).link { height:var(--h-ctl); padding:0 14px; font-size:13px; margin:0; }
:is(#log, #panel) :is(button, a).link:disabled { opacity:.5; cursor:default; }
#panel .ptool.acts { gap:8px; }
/* demo 10/28: the PDF is one scroll of pages fitted to the column; zoomed in, it scrolls sideways too */
#pbody.pdf { position:relative; overflow:auto; overflow-anchor:none; }
#pbody.pdf .pg { margin:0 auto 12px; flex:none; } #pbody.pdf .pg:last-child { margin-bottom:0; }
#pbody.pdf .pg canvas { width:100%; height:100%; }
.ptool .pctl { display:inline-flex; align-items:center; gap:2px; margin-left:auto; }  /* zoom and the page wrap as one */
.ptool .zoom { display:inline-flex; align-items:center; gap:2px; margin-right:6px; padding-right:8px; border-right:1px solid var(--a8); }
.ptool .zoom .zl { min-width:52px; text-align:center; font:500 12px/1 var(--mono); color:var(--ink-2); }
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
  minus: "M5 12h14", fit: "M3 4v16M21 4v16M7 12h10M10 9l-3 3 3 3M14 9l3 3-3 3", code: "m16 18 6-6-6-6M8 6l-6 6 6 6",  // demo 10/28: PDF zoom, 폭 맞춤, VS Code
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
// A2 complete (B1): a message's time is HH:mm (the stage dividers too); the day is the task's
const time = s => { if (!s) return ""; const d = new Date(s); return isNaN(d) ? "" : String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0"); };
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
// A2 complete (B7): under a paper answer, how its quotes were checked: all found in which source's own text; the ones
// Pablo could not place were left out of the answer
const verified = (k, dropped) => { const es = [...new Set((k.evidence || []).filter(e => M.anchors[e]))];
  if (!es.length && !dropped) return null;
  const ts = [...new Set(es.map(e => (M.sources[M.anchors[e].source] || {}).title).filter(Boolean))];
  return h("p", { class: "verify", "data-verify": String(es.length) }, ico("check-circle", 14), h("span", null, `인용 ${es.length}개`,
    es.length ? ` · 모두 ${ts.length === 1 ? ts[0] : "자료"} 원문에서 위치를 확인했습니다` : "",
    dropped ? ` · 위치를 못 찾은 인용 ${dropped}개는 답에서 뺐습니다` : "")); };
// S9 / S43 / S55: something did not work: what happened, then what to do (a grey card; .call.block: tests read it)
const failCard = (title, err, ...more) => h("div", { class: "call block fail" }, h("p", { class: "head" }, ico("info", 14), " ", title),
  err ? h("p", { class: "why" }, err) : null, ...more);
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
// put away (보관) folded at the bottom; nothing is deleted. A2 complete: the brand row folds the sidebar into a 56px rail
// (settings.side, any task); 새 작업 and the search show their shortcut (Ctrl N / Ctrl K, ⌘ on a Mac); a row has the task's
// stage progress (stagesOf) and "kind · stage"; a search names where it found the words, in bold; the account card
// (#acct, made by the desktop) stays at the bottom
const nameOf = t => (t && (t.name || t.text)) || "";
let taskQuery = "";
const MAC = /Mac/i.test(navigator.platform || ""), keyOf = k => MAC ? "⌘" + k : "Ctrl " + k;
const sideOff = () => !!(M.settings || {}).side;
function setSide(off) {
  M.settings = { ...(M.settings || {}), side: off }; sidebar();
  if (window.pabloHost && pabloHost.setUi) pabloHost.setUi(null, "settings", { side: off }).catch(() => {});
}
// Ctrl K: the search, from anywhere (the rail opens, the narrow window's drawer slides in)
function findTasks() {
  if (sideOff()) setSide(false);
  if (matchMedia("(max-width:900px)").matches) document.body.classList.add("side");
  const q = $("task-search"); if (q) { q.focus(); q.select(); }
}
// the words in bold, as found (any case)
function marked(text, words) {
  const s = String(text || ""), low = s.toLowerCase(), out = []; let i = 0;
  while (i < s.length) {
    let at = -1, w = "";
    for (const x of words) { const j = low.indexOf(x, i); if (j >= 0 && (at < 0 || j < at)) { at = j; w = x; } }
    if (at < 0) { out.push(s.slice(i)); break; }
    out.push(s.slice(i, at), h("b", { class: "hit" }, s.slice(at, at + w.length))); i = at + w.length;
  }
  return out;
}
function sidebar() {
  const side = $("side"), had = document.activeElement && document.activeElement.id === "task-search", acct = $("acct");
  const off = sideOff() && !matchMedia("(max-width:900px)").matches, app = !!(window.pabloHost && pabloHost.newTask), d = M.desk || {};  // a narrow window has a drawer, not a rail
  document.body.classList.toggle("side-off", off);
  side.textContent = "";
  const rowOf = (t, words = []) => {
    const k = kindFor(d[t.id]), v = (M.views || {})[t.id], st = v && M.desk ? stagesOf(v, d[t.id], k) : null;
    const now = st ? (st.current >= 0 ? st.steps[st.current].label : "끝") : null;
    const inName = words.some(w => nameOf(t).toLowerCase().includes(w));
    const src = words.length && !inName ? ((d[t.id] || {}).papers || []).find(p => words.some(w => String(p.title).toLowerCase().includes(w))) : null;
    const goal = words.length && !inName && !src && t.name && words.some(w => String(t.text).toLowerCase().includes(w));
    return h("button", { class: "t" + (V && t.id === V.task.id ? " on" : ""), title: t.name ? t.text : null, "data-task": t.id,
      on: () => { select(t.id); document.body.classList.remove("side"); } }, h("span", { class: "tn" }, words.length ? marked(nameOf(t), words) : nameOf(t)),
      h("small", null, st ? h("span", { class: "prog", "aria-hidden": "true" }, st.steps.map(s => h("i", { class: "p-" + s.state }))) : null,
        src ? ["자료 · ", marked(src.title, words)] : goal ? ["목표 · ", marked(t.text, words)]
          : M.desk ? `${KIND[k]}${now ? " · " + now : ""}` : `${day(t.at)} ${time(t.at)}`));
  };
  const ordered = [...M.tasks].reverse(), keptAll = ordered.filter(t => !(d[t.id] || {}).archived && !(d[t.id] || {}).done);
  const fold = h("button", { class: "fold", id: "side-fold", title: off ? "사이드바 펼치기" : "사이드바 접기", "aria-label": off ? "사이드바 펼치기" : "사이드바 접기",
    "aria-expanded": String(!off), on: () => setSide(!sideOff()) }, ico("panel-left"));
  if (off) {  // F16: the 56px rail (새 작업 · 찾기 · a task's first letter · 설정)
    side.append(h("div", { class: "rail" }, fold,
      h("button", { class: "rnew", title: `새 작업 (${keyOf("N")})`, "aria-label": "새 작업", disabled: !app, on: () => newTask() }, ico("plus")),
      h("button", { class: "rbtn", title: `작업 찾기 (${keyOf("K")})`, "aria-label": "작업 찾기", on: findTasks }, ico("search")),
      h("div", { class: "rtasks" }, keptAll.map(t => h("button", { class: "rt" + (V && t.id === V.task.id ? " on" : ""), "data-rail-task": t.id, title: nameOf(t),
        "aria-label": nameOf(t), on: () => select(t.id) }, [...nameOf(t).trim()][0] || "·"))),
      openSettings ? h("button", { class: "rbtn rset", title: "설정", "aria-label": "설정", on: () => openSettings() }, ico("settings")) : null));
    if (acct) side.append(acct);
    return;
  }
  const q = h("input", { id: "task-search", type: "search", placeholder: "작업·자료 찾기", value: taskQuery, "aria-label": "작업 찾기", autocomplete: "off", spellcheck: "false" });
  const kbd = h("kbd", { class: "kbd" }, taskQuery ? "esc" : keyOf("K"));
  const clear = () => { taskQuery = q.value = ""; kbd.textContent = keyOf("K"); list(); };
  q.addEventListener("input", () => { taskQuery = q.value; kbd.textContent = taskQuery ? "esc" : keyOf("K"); list(); });
  q.addEventListener("keydown", e => { if (e.key === "Escape" && !e.isComposing && q.value) { e.stopPropagation(); clear(); } });
  const box = h("div", { id: "task-list" });
  // A2: the brand mark is CSS (.brand b::before, an ink square with "P"); 새 작업 is the one filled button
  side.append(h("div", { class: "brand" }, h("div", { class: "brow" }, h("b", null, art("head", "ico"), "Pablo"), fold),
      h("button", { class: "new", id: "new", disabled: !app, title: `새 작업 (${keyOf("N")})`, on: () => newTask() }, ico("plus", 14), h("span", null, "새 작업"), h("kbd", { class: "kbd" }, keyOf("N")))),
    h("div", { class: "searchbox" }, ico("search", 14), q, kbd), box);
  if (acct) side.append(acct);
  function list() {
    const words = taskQuery.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const hit = t => !words.length || words.every(w => [t.name, t.text, t.id, ...((d[t.id] || {}).papers || []).map(p => p.title)]
      .some(x => String(x || "").toLowerCase().includes(w)));
    const ts = ordered.filter(hit), kept = ts.filter(t => !(d[t.id] || {}).archived && !(d[t.id] || {}).done), away = ts.filter(t => (d[t.id] || {}).archived);
    const done = ts.filter(t => (d[t.id] || {}).done && !(d[t.id] || {}).archived);  // P7: finished tasks fold into 완료
    // S19: a task put away is faint; 보관 풀기 shows on hover (the header's ⋯ menu has it too)
    const awayRow = t => h("div", { class: "trow away-row" }, rowOf(t, words), window.pabloHost && pabloHost.archiveTask
      ? h("button", { class: "link unarch", "data-unarchive": t.id, on: () => pabloHost.archiveTask(t.id, false).then(() => refresh()) }, "보관 풀기") : null);
    box.replaceChildren(...[h("h4", null, words.length ? `찾은 작업 ${ts.length}개` : "작업"),
      !M.tasks.length ? h("p", { class: "none", "data-no-tasks": "1" }, "아직 작업이 없습니다.") : null,
      ...kept.map(t => rowOf(t, words)),
      done.length ? h("details", { class: "done", "data-done": String(done.length), open: words.length ? true : null },
        h("summary", null, ico("chevron-right", 12), "완료 ", h("span", { class: "cnt" }, done.length)), ...done.map(t => rowOf(t, words))) : null,
      away.length ? h("details", { class: "away", "data-archived": String(away.length), open: words.length ? true : null },
        h("summary", null, ico("chevron-right", 12), "보관한 작업 ", h("span", { class: "cnt" }, away.length)), ...away.map(awayRow)) : null,
      words.length && !ts.length ? h("div", { class: "nohit", "data-no-hit": "1" }, h("b", null, "맞는 작업이 없습니다"),
        h("p", null, "작업 이름 · 목표 · 자료 제목에서 찾았습니다. 다른 낱말로 찾아보세요."), h("button", { class: "link", on: () => { clear(); q.focus(); } }, "검색 지우기")) : null,
      words.length && ts.length ? h("p", { class: "shint" }, "작업 이름 · 목표 · 자료 제목에서 찾습니다. 완료 · 보관 묶음은 찾는 동안 펼쳐집니다.") : null].filter(Boolean));
  }
  list();
  if (had) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
}
// A2 complete: the header is the task's name and kind, three chips (자료 · 폴더 · 인터넷; tools() makes them) and ⋯ (이름
// 바꾸기 F2 · 완료 · 보관 · 작업 폴더 열기 · 보고서 내보내기). The menu stays in the DOM, hidden, so its items keep working by id.
function header() {
  const chips = $("chips");  // P2: the chips + their card (tools() makes them); kept across a header redraw
  $("bar").textContent = ""; ptabs();
  $("bar").append(h("button", { id: "menu", title: "작업 목록", "aria-label": "작업 목록", on: () => document.body.classList.toggle("side") }, ico("panel-left")));
  if (!V) return $("bar").append(h("h1", null, "Pablo"));
  const t = M.tasks.find(x => x.id === V.task.id) || V.task, d = (M.desk || {})[V.task.id] || {}, host = window.pabloHost || {};
  const name = h("h1", { title: t.name ? `목표: ${V.task.text}` : null, "data-task-name": "1" }, nameOf(t));
  // S17: the name in place, n/80, Enter saves, Esc leaves it; empty = the goal's first line
  const rename = () => {
    const inp = h("input", { class: "rn-in", id: "task-name", value: nameOf(t), "aria-label": "작업 이름", spellcheck: "false" });
    const cnt = h("small", { class: "rn-cnt" }), note = h("small", { class: "rn-note" }, "Esc를 누르면 취소합니다. 비우면 목표 첫 줄을 이름으로 씁니다.");
    const count = () => { const n = [...inp.value.trim()].length; cnt.textContent = `${n}/80`; inp.parentNode && inp.parentNode.classList.toggle("over", n > 80); };
    const ok = () => { const v = inp.value.trim();
      if ([...v].length > 80) { note.replaceChildren(ico("info", 14), " 작업 이름은 80자까지입니다. 이름은 바뀌지 않았습니다."); note.classList.add("bad"); return inp.focus(); }
      pabloHost.renameTask(V.task.id, v === V.task.text ? "" : v).then(() => refresh(), e => { note.textContent = fail(e); note.classList.add("bad"); }); };
    inp.addEventListener("input", count);
    inp.addEventListener("keydown", e => { if (e.key === "Enter" && !e.isComposing) ok(); if (e.key === "Escape") { e.stopPropagation(); header(); } });
    name.classList.add("renaming");
    name.replaceChildren(h("span", { class: "rn-box" }, inp, cnt), h("button", { class: "pill on", "data-rename-task-ok": "1", on: ok }, "저장"),
      h("button", { class: "pill", "data-rename-task-cancel": "1", on: () => header() }, "취소"), note);
    count(); inp.select(); };
  // ⋯: what used to be the header's text links (✎ · 보관 · 완료 풀기), and the folder and the report
  const more = h("div", { class: "hmenu", id: "more-menu", role: "menu", hidden: true });
  const item = (icon, label, attrs, on, meta) => h("button", { class: "mi", role: "menuitem", ...attrs,
    on: e => { more.hidden = true; moreBtn && moreBtn.setAttribute("aria-expanded", "false"); on(e); } }, ico(icon), h("span", null, label), meta ? h("small", null, meta) : null);
  if (host.renameTask) more.append(item("pencil", "이름 바꾸기", { "data-rename-task": V.task.id }, rename, "F2"));
  if (host.setUi) more.append(item("check-circle", d.done ? "완료 풀기" : "완료로 옮기기", { "data-done": d.done ? "off" : "on" },
    () => pabloHost.setUi(V.task.id, "done", !d.done).then(() => refresh())));
  if (host.archiveTask) more.append(item("folder", d.archived ? "보관 풀기" : "보관", { "data-archive": d.archived ? "off" : "on",
    title: d.archived ? "작업 목록으로 되돌립니다" : "작업 목록 아래 '보관한 작업'으로 옮깁니다. 기록은 그대로 남습니다." },
    () => pabloHost.archiveTask(V.task.id, !d.archived).then(() => refresh())));
  if (d.folder && openWork) more.append(item("folder", "작업 폴더 열기", { "data-open-work": "1" }, () => openWork(V.task.id)));
  if (host.report && reportDlg) more.append(item("file", "보고서 내보내기", { "data-export": "1" }, () => reportDlg(V.task.id)));
  if (more.children.length) more.append(h("p", { class: "mfoot" }, "완료한 작업이면 '완료 풀기', 보관한 작업이면 '보관 풀기'로 바뀝니다."));
  const moreBtn = more.children.length ? h("button", { class: "rn hbtn", id: "more", title: "작업 메뉴", "aria-label": "작업 메뉴", "aria-haspopup": "menu", "aria-expanded": "false",
    on: () => { more.hidden = !more.hidden; moreBtn.setAttribute("aria-expanded", String(!more.hidden)); } }, ico("more")) : null;
  // the narrow window has no rail: this opens the right column over the conversation
  const pnl = h("button", { class: "rn hbtn", id: "pnl", title: "오른쪽 패널", "aria-label": "오른쪽 패널",
    on: () => document.body.classList.contains("panel") ? close() : show({ mode: "intent" }) }, ico("panel-right"));
  // A2: the task's kind as a small tag beside its name; a spacer puts the chips and ⋯ on the right
  const kindTag = M.desk ? h("span", { class: "kindtag", "data-kind-tag": deskKind(V.task.id) }, KIND[deskKind(V.task.id)]) : null;
  $("bar").append(...[name, kindTag, h("span", { class: "grow" }), chips, pnl, moreBtn, more].filter(Boolean));  // 기준 · 계획 · 왜? are the right column's tabs (ptabs)
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
  const v = { open, tab: !m ? (was.tab || "intent") : EVM.includes(m) ? "evidence" : m }, k = JSON.stringify(v);
  if (panelSaved[V.task.id] === k) return; panelSaved[V.task.id] = k;
  pabloHost.setUi(V.task.id, "panel", v).catch(() => {});
  // the page's copy too: select() reads M.desk when the task is opened again before the next state read (QA 10/26, D4)
  if (M.desk) M.desk[V.task.id] = { ...(M.desk[V.task.id] || {}), panel: v };
}
// A2 complete · C: the 근거 tab opens the evidence shown last, else this task's newest [n], else its papers (S69)
const EVM = ["source", "code", "paper", "matrix", "evhome"];
const evList = (v = V) => [...new Set(Object.values(v.checks).flatMap(c => c.evidence || []))].filter(e => M.anchors[e])
  .sort((a, b) => +a.replace(/\D/g, "") - +b.replace(/\D/g, ""));
// the number the user clicked ([1] of an answer has its own); else this chat's number
const citeSeen = {};
document.addEventListener("click", ev => { const b = ev.target.closest && ev.target.closest(".cite"); if (b && b.dataset.e) citeSeen[b.dataset.e] = b.textContent.replace(/\D/g, ""); }, true);
const numOf = e => +citeSeen[e] || cites[e] || evList().indexOf(e) + 1;
const cellOf = e => Object.values(V.checks).find(k => k.matrix && (k.evidence || []).includes(e)) || null;
function evidenceFor() {
  if (lastEv) return lastEv;
  const e = evList().at(-1);
  if (e) return { mode: "source", e };
  return (((M.desk || {})[V.task.id] || {}).papers || []).length ? { mode: "evhome" } : null;
}
// the action waiting for the user's [진행]/[취소]; the plan's rows (one plan per message: Pn.1), the current one
const waitingAct = (v = V) => v.actions.filter(a => a.verdict === "WARN" && !a.decision).at(-1) || null;
function planRows(v = V) {
  const plans = v.plans && v.plans.length ? v.plans : v.plan ? [{ id: v.plan.id, status: "active", steps: v.plan.steps }] : [];
  const rows = plans.flatMap(p => (p.steps || []).map(s => ({ id: s.id, action: s.action, old: p.status === "superseded" })));
  const w = waitingAct(v), wi = w ? rows.findIndex(r => r.id === w.step) : -1, k = wi >= 0 ? wi : rows.length - 1;
  return { rows, k: k + 1, cur: rows[k] || null };
}
const shortText = (t, n = 24) => { t = String(t || "").replace(/\s*\[\d+\]/g, "").replace(/\s+/g, " ").trim(); return t.length > n ? t.slice(0, n) + "…" : t; };
const hm = s => s ? new Date(s).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false }) : "";
// D2 back-links: the turns of the conversation and the Guard's verdicts that point at these refs
function backOf(refs, L) {
  const chat = new Set(), acts = new Map();
  [].concat(refs).filter(Boolean).forEach(r => { const x = L.get(r); if (!x) return; x.chat.forEach(k => chat.add(k)); x.verdicts.forEach(v => acts.set(v.act, v)); });
  return { chat: chat.size, keys: [...chat], verdicts: [...acts.values()] };
}
function backChips(b) {
  const vs = b.verdicts, block = vs.some(v => v.verdict === "BLOCK"), wait = vs.some(v => v.verdict === "WARN" && !v.decision);
  return h("span", { class: "backs" }, h("span", { class: "bk", "data-back-chat": String(b.chat), title: "이것을 가리킨 대화" }, ico("message", 12), `대화 ${b.chat}`),
    vs.length ? h("span", { class: "bk" + (wait ? " wait" : ""), "data-back-verdicts": String(vs.length), title: "이것으로 Pablo가 판정한 작업" }, ico("check-circle", 12),
      `판정 ${vs.length}` + (block ? " (막음)" : wait ? " (확인 필요)" : "")) : null);
}
// C6: a row picked in the panel -> the conversation keeps only what points at it (picked again: everything back)
const picked = label => !!$("log") && $("log").dataset.filter === "refs:" + label;
function pickRows(el, refs, label) {
  if (typeof filterBy !== "function") return;
  filterBy(refs, label);
  document.querySelectorAll("#panel .sel").forEach(x => x.classList.remove("sel"));
  if (el && picked(label)) el.classList.add("sel");
  document.querySelectorAll("#panel [data-filter-refs]").forEach(b => { b.textContent = picked(b.dataset.filterRefs) ? "전체 보기" : "대화로 거르기"; });
}
// a band under the panel's head: what points at this, and 대화로 거르기
const backBand = (text, refs, label, n) => h("div", { class: "band", "data-band": "1" }, h("span", null, text),
  n ? h("button", { class: "link", "data-filter-refs": label, on: () => pickRows(null, refs, label) }, picked(label) ? "전체 보기" : "대화로 거르기") : null);
// a small menu under a chip (자료 고르기 ▾, 파일 고르기 ▾, + 논문 추가): closes on a pick, a click outside, Esc
function menuChip(btn, rows, note, right) {
  const menu = h("div", { class: "pmenu" + (right ? " right" : ""), hidden: true, role: "menu" }, rows, note ? h("p", { class: "note" }, note) : null);
  btn.addEventListener("click", e => { e.stopPropagation(); const was = menu.hidden;
    document.querySelectorAll("#panel .pmenu").forEach(m => { m.hidden = true; }); menu.hidden = !was; btn.setAttribute("aria-expanded", String(was)); });
  menu.addEventListener("click", e => { if (e.target.closest(".mi")) menu.hidden = true; });
  return h("span", { class: "mwrap" }, btn, menu);
}
document.addEventListener("click", e => document.querySelectorAll("#panel .pmenu:not([hidden])").forEach(m => { if (!m.parentElement.contains(e.target)) m.hidden = true; }));
// what the 근거 tab says under its name: the place shown last ("config.yaml:5", "칸 [7]", "p.9"), else how many [n]
function evAt(st) {
  if (!st) return null;
  if (st.mode === "code") { const w = String(st.where).split(/[;,]\s/)[0].replace(/\s*\(.*$/, "");
    return w.replace(/(:\d+(?:[-,]\d+)*)+$/, "").split(/[\\/]/).pop() + (st.line ? ":" + st.line : (w.match(/:\d+/) || [""])[0]); }
  if (st.mode === "source") { const a = M.anchors[st.e]; if (!a) return null;
    return cellOf(st.e) ? `칸 [${numOf(st.e)}]` : a.page ? `p.${a.page}` : null; }
  if (st.mode === "paper") return `p.${st.page || 1}`;
  return st.mode === "matrix" ? "비교표" : null;
}
// P3 / C1: the right column's tabs, always there: 기준 · 계획 · 왜? · 근거 with a one-line summary each; an orange dot on
// the open tab and on any tab with something waiting; a tab with nothing yet is off and says when it opens (S67).
// With the panel closed they stay as a rail, "‹ 펼치기" on top.
function ptabs() {
  const nav = $("ptabs"); if (!nav) return; nav.textContent = "";
  document.body.classList.toggle("rail", !!V);
  if (!V) return;
  const open = document.body.classList.contains("panel"), mode = hi >= 0 && open ? hist[hi].mode : null;
  const on = EVM.includes(mode) ? "evidence" : mode;
  const I = V.intent, w = waitingAct(), P = planRows(), n = I.must.length + I.prefer.length, cited = evList().length, ev = evidenceFor();
  const tabs = [["intent", "기준", n ? `반드시 ${I.must.length} · 가능 ${I.prefer.length}` : "기준 없음", String(n), () => toggle({ mode: "intent" }), null,
      I.questions.some(q => /^K\d+$/.test(q.id))],
    ["plan", "계획", P.cur ? `${P.cur.id} · ${P.k}/${P.rows.length}` : "아직 없음", P.cur ? `${P.k}/${P.rows.length}` : "–", P.cur ? () => toggle({ mode: "plan" }) : null,
      "에이전트가 계획을 세우면 열립니다", !!(w && w.step)],
    ["trace", "왜?", w ? "확인 기다림" : V.actions.length ? `판정 ${V.actions.length}` : "판정 없음", w ? "!" : V.actions.length ? String(V.actions.length) : "–",
      () => toggle({ mode: "trace" }), null, !!w],
    ["evidence", "근거", evAt(lastEv) || (cited ? `인용 ${cited}` : "—"), cited ? String(cited) : "–", ev ? () => (on === "evidence" ? close() : show(evidenceFor())) : null,
      "자료를 추가하면 열립니다", false]];
  const unfold = () => { const was = ((M.desk || {})[V.task.id] || {}).panel || {};
    show((was.tab === "evidence" ? evidenceFor() : was.tab === "plan" && !P.cur ? null : was.tab && was.tab !== "evidence" ? { mode: was.tab } : null) || { mode: "intent" }); };
  nav.append(h("button", { class: "unfold", "data-unfold": "1", title: "오른쪽 패널 펼치기", on: unfold }, turned("chevron-right", 180, 12), "펼치기"),
    ...tabs.map(([k, label, long, short, go, tip, attn]) => h("button", { class: "ptab" + (on === k ? " on" : "") + (attn && on !== k ? " attn" : ""),
      "data-tab": k, disabled: !go, title: go ? long : null, "data-tip": go ? null : tip, on: go },
      h("b", null, label), h("small", { class: "long" }, long), h("small", { class: "short" }, short))));
}

// ---- conversation: built from the stored research / plan / guard / review records --------------------------
// B1: the person is "나"; a message without its own time (a live Pablo card) is stamped now (conversation() stamps the
// stored ones with their record's time)
const msg = (who, at, ...kids) => h("div", { class: "msg " + (who === "Pablo" ? "pablo" : "user") },
  h("div", { class: "av" }, who === "Pablo" ? "P" : "나"), h("div", null, h("div", { class: "who" }, who === "Pablo" ? "Pablo" : "나",
    h("small", null, time(at === null ? new Date().toISOString() : at))), kids));
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
const failed = a => a.verdict === "ALLOW" && a.runs.some(r => r.alignment === "failed") && h("div", { class: "call block fail", title: a.id, "data-id": a.id },
  h("p", { class: "head" }, ico("info", 14), " 작업을 실행하지 못했습니다"), h("p", null, "제안된 작업: ", h("b", null, meaning(a.text))),
  runRows(a), h("div", { class: "foot" }, tech(a.text), h("button", { class: "link", on: () => show({ mode: "trace", act: a.id }) }, "왜 그런가요?")));
// S40: a run and its review as a badge (계획대로 · 일부만 · 계획과 다르게 · 실패) and what happened
const BADGE = { aligned: "계획대로", partial: "일부만", deviated: "계획과 다르게", failed: "실패", not_executed: "실행하지 않음" };
const runRows = a => a.runs.map(r => h("p", { class: "rev" }, r.alignment ? h("span", { class: "tg rv rv-" + r.alignment }, BADGE[r.alignment] || r.alignment) : null,
  h("span", null, (r.executed ? "실행 결과: " : "") + done(r) + (r.alignment ? ` · ${ALIGN[r.alignment] || r.alignment}` : ""))));
const done = r => meaning(r.summary.replace(/^실행하지 않음: /, ""));
const runs = a => a.runs.map(r => (r.executed ? "실행 결과: " : "") + done(r) + (r.alignment ? ` · ${ALIGN[r.alignment] || r.alignment}` : ""));
// a BLOCK is Pablo's own decision (its card says so); a reason that only repeats who decided is not shown again
const decided = a => a.decision && a.verdict !== "BLOCK"
  ? (DECIDE[a.decision] || a.decision) + (a.decision_reason && !/^(사용자가|Guard )/.test(a.decision_reason) ? ` · ${a.decision_reason}` : "") : null;
function issues() {
  return V.research.flatMap(id => V.checks[id].issues.map(i => { const c = V.checks[id];
    return h("div", { class: "call issue", title: i.id, "data-id": i.id }, art("surprised", "pose"),
      h("p", { class: "head" }, ISSUE[i.type] || ISSUE.other), h("p", null, rich(i.note), c.evidence.map(cite)),
      c.evidence.length ? h("p", { class: "muted" }, "Pablo는 공식 원문을 기준으로 판단했습니다.") : null); }));
}
// B8 / S39: a WARN / BLOCK as recorded; a badge heads it (막음 / 확인 필요, CSS), 기술 세부정보 and 왜? at its foot; a WARN
// still waiting has the orange edge
function action(a) {
  const block = a.verdict === "BLOCK", ev = a.criteria.flatMap(c => V.checks[c.id] ? V.checks[c.id].evidence : []);
  const d = decided(a);
  return h("div", { class: "call guard" + (block ? " block lock" : " warn" + (a.decision ? " settled" : "")), title: a.id, "data-id": a.id },
    h("p", { class: "head" }, block ? "이 작업은 현재 기준과 충돌합니다" : "이 작업은 현재 기준과 충돌할 수 있습니다"),
    h("p", null, "제안된 작업: ", h("b", null, meaning(a.text))), preview(a.text), current(a.text, V.task.id),
    a.why ? h("p", { class: "muted" }, `제시한 이유: "${a.why}"`) : null,
    a.problems.length ? [reason(a.problems[0], block), [...new Set(ev)].map(cite)] : null,
    a.criteria.length ? h("p", { class: "muted crit" }, "관련 기준: ", h("b", null, a.criteria.map(c => c.text).join(" · "))) : null, offer(a),
    d ? h("p", { class: "rev dec" }, ico("check-circle", 14), h("span", null, d)) : null, runRows(a),
    block ? (runs(a).length ? null : h("p", { class: "muted" }, h("b", { "data-blocked": "1" }, "Pablo가 막아 실행하지 않았습니다. ")))
      : !d ? h("p", { class: "muted" }, h("b", null, "진행할지 결정이 필요합니다. ")) : null,
    h("div", { class: "foot" }, tech(a.text, ...a.problems.filter(x => !korean(x))), h("button", { class: "link", on: () => show({ mode: "trace", act: a.id }) }, "왜 그런가요?")));
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
// B9: a grey band "파일 N개가 바뀌었습니다 · path +42" with [변경 보기] [되돌리기]; the diff opens under it (S50), undone or
// refused says so under it (S51)
function changed(c, task) {
  const fs_ = c.files || [], nums = f => f.add == null || !(f.add || f.del) ? null : h("span", { class: "nums" }, f.add ? ` +${f.add}` : "", f.del ? ` −${f.del}` : "");
  const one = f => [f.status === "D" ? h("span", { class: "gone" }, f.path) : fileLink(f.path, task, f.path), f.status === "D" ? " (삭제)" : f.status === "A" ? " (새 파일)" : "", nums(f)];
  const box = h("div", { class: "changes", "data-to": c.to }, h("div", { class: "chg-row" }, ico("file", 14),
    h("p", { class: "chg-t" }, `파일 ${fs_.length}개가 바뀌었습니다 · `, fs_.slice(0, 3).map((f, i) => [i ? ", " : "", one(f)]), fs_.length > 3 ? ` 외 ${fs_.length - 3}개` : "")));
  if (!window.pabloHost || !pabloHost.undo) return box;
  const v = M.views[task], undone = v && (v.chat || []).some(x => x.role === "undo" && x.of === c.to), row = box.firstChild;
  let open = null;
  const look = h("button", { class: "pill", "data-look": "1", on: () => {
    if (open) { open.remove(); open = null; look.textContent = "변경 보기"; return; }
    pabloHost.diff(task, c.from, c.to).then(t => { open = preview("", t) || h("p", { class: "muted" }, "표시할 내용이 없습니다."); row.after(open); look.textContent = "변경 접기"; },
      e => row.after(h("p", { class: "muted" }, fail(e)))); } }, "변경 보기");
  const back = undone ? h("span", { class: "muted", "data-undone": "1" }, "되돌렸습니다.")
    : h("button", { class: "pill soft", "data-undo": "1", on: () => pabloHost.undo(task, c.from, c.to).then(() => {
        back.replaceWith(h("span", { class: "muted", "data-undone": "1" }, "되돌렸습니다. 다음 요청 때 에이전트에게도 알립니다.")); refresh(); },
        e => box.append(h("p", { class: "muted undo-err", "data-undo-error": "1" }, ico("info", 14), " 되돌리지 않았습니다. ", fail(e)))) }, ico("rotate", 14), "되돌리기");
  row.append(h("span", { class: "chg-acts" }, look, back));
  return box;
}
// A2: a paper's reproduction conditions (PabloSkill.spec), by category, each with its page [n]; what the paper leaves open
const SPEC = { dataset: "데이터셋", split: "데이터 분할", preprocessing: "전처리", model: "모델", method: "방법",
               hyperparameter: "하이퍼파라미터", training: "학습", metric: "평가 지표", baseline: "비교 대상", result: "보고된 결과",
               protocol: "평가 규칙" };
const fact = c => [rich((c.conclusion || c.title).replace(/\s*\[\d+\]/g, "")), c.evidence.length ? " " : null, c.evidence.map(e => cite(e))];  // [n] numbered in this chat
const ASIDE = { fact: "논문의 서술 (코드가 정하지 않음)", scope: "실험 범위 (이 재현 밖일 수 있는 실험)" };  // ⑥ not checked
// 0.8 review: a re-extraction of the same paper says what changed; what the last one had and this one did not find comes
// back with 되살리기 (extractions differ from run to run); what the user made of the conditions was kept.
// A2 complete (F25): its own card above the new list: 바뀜 (the same setting with another value: the old one struck
// through -> the new one, with its page), 빠짐 (되살리기), 새로. "The same setting": same category, the same words once
// the value and the numbers are taken out (a rule, no model call)
let specAgain = null, addSource = null;  // desktop: 다시 뽑기 (asks first), + 추가 (the add box)
const KIND_TAG = { setting: "설정", result: "결과", scope: "범위", fact: "서술" };
const pchip = k => { const e = ((k && k.evidence) || []).find(x => M.anchors[x]); if (!e) return null; const a = M.anchors[e];
  return h("button", { class: "cite pgc", "data-e": e, title: "근거 보기", on: () => show({ mode: "source", e }) }, a.page ? `p.${a.page}` : `[${cites[e] || 1}]`); };
const plain = k => String(k.conclusion || k.title || "").replace(/\s*\[\d+\]/g, "");
function redone(d) {
  const can = window.pabloHost && pabloHost.condition, task = V.task.id;
  const subj = k => { const v = String(k.spec.value || ""); return plain(k).replace(v, "").replace(/[\d.,%]+/g, "").replace(/\s+/g, "").slice(0, 40); };
  const gone = (d.gone || []).map(id => V.checks[id]).filter(k => k && k.spec), fresh = (d.new || []).map(id => V.checks[id]).filter(k => k && k.spec);
  const pairs = [], used = new Set();
  gone.forEach(g => { const n = fresh.find(x => !used.has(x.id) && x.spec.category === g.spec.category && subj(x) === subj(g) && String(x.spec.value) !== String(g.spec.value));
    if (n) { used.add(n.id); used.add(g.id); pairs.push([g, n]); } });
  const out = gone.filter(k => !used.has(k.id)), add = fresh.filter(k => !used.has(k.id));
  const lost = out.filter(k => k.state === "waived" && k.waived_by === "pablo");
  const back = k => { const at = h("span");
    return [at, h("button", { class: "link", "data-redo-restore": k.id, on: () => pabloHost.condition(task, "restore", { id: k.id }).then(() => {
      echo(task, { role: "spec-restore", check: k.id }); return refresh(); }, e => at.replaceChildren(h("span", { class: "muted" }, fail(e) + " "))) }, "되살리기")]; };
  const cat = k => h("span", { class: "tg kd" }, SPEC[k.spec.category] || k.spec.category);
  return h("div", { class: "redo-card", "data-redo": "1" },
    h("p", { class: "head" }, ico("rotate", 14), h("span", null, `다시 뽑았습니다: 이전 ${d.before}개 중 ${d.same}개 그대로 · 바뀜 ${pairs.length} · 빠짐 ${out.length} · 새로 ${add.length}`)),
    (d.kept || []).length || (d.out || []).length ? h("p", { class: "muted" }, (d.kept || []).length ? `직접 더하거나 되살리거나 의도한 차이로 둔 조건 ${d.kept.length}개는 그대로 두었습니다. ` : "",
      (d.out || []).length ? `이전에 뺀 조건 ${d.out.length}개는 다시 넣지 않았습니다. ` : "", "이전 목록은 위쪽 카드에 남습니다.") : null,
    pairs.length ? [h("p", { class: "rd-sec" }, `바뀜 ${pairs.length}`), h("ul", { class: "rd-list", "data-changed": String(pairs.length) }, pairs.map(([g, n]) =>
      h("li", { "data-id": n.id }, cat(n), h("span", { class: "sx" }, clip(plain(n).replace(String(n.spec.value), "").trim() || plain(n), 40)), " ",
        h("s", null, g.spec.value), " → ", h("b", { class: "nv" }, n.spec.value), " ", pchip(n))))] : null,
    out.length ? h("details", { class: "rd-gone", "data-gone": String(out.length) }, h("summary", null, ico("chevron-down", 12), ` 이번에 빠진 조건 ${out.length}개`),
      h("ul", { class: "rd-list" }, out.map(k => h("li", { "data-id": k.id }, cat(k), h("span", { class: "sx" }, plain(k)), h("small", { class: "muted" }, " 이번 추출에 없음"),
        can && lost.includes(k) ? h("span", { class: "rt" }, back(k)) : null)))) : null,
    add.length ? h("p", { class: "rd-new" }, h("span", { class: "rd-sec" }, `새로 ${add.length}`), add.slice(0, 4).map(k => h("span", { class: "tg tgt" },
      `${SPEC[k.spec.category] || k.spec.category} · ${clip(k.spec.value || plain(k), 20)}`)), add.length > 4 ? h("small", { class: "muted" }, ` 외 ${add.length - 4}`) : null) : null);
}
// B10: the conditions card. Its head (재현 조건 N개 · paper, 다시 뽑기, PDF에서 조건 더하기), how they were kept (located
// only, left out, seconds), kind chips (전체 · 설정 · 결과 · 범위 · 서술), a grey head per category (a long list folds all
// but two into one line "▸ 이름 N"), rows: kind · sentence · warnings · p.N · actions on hover; then 논문에 없는 설정
function conditions(ids, dropped, diff, secs) {
  const cs = ids.map(id => V.checks[id]).filter(c => c && c.state !== "waived"), all = cs.filter(c => !c.spec.missing);
  const open = cs.filter(c => c.spec.missing), task = V.task.id;
  const box = h("div", { class: "spec", "data-spec": "1" });
  const again = specAgain ? h("button", { class: "pill", "data-spec-again": "1", on: () => specAgain() }, "다시 뽑기") : null;  // 06: no icon
  if (!ids.length) return box.append(h("p", { class: "head" }, "위치를 확인한 조건이 없습니다"),  // S6
    h("p", { class: "muted" }, `PDF에서 글자를 거의 읽지 못했거나(스캔본일 수 있음) 모델이 낸 조건의 원문 위치를 찾지 못했습니다.${dropped ? ` 위치가 확인되지 않은 조건 ${dropped}개는 남기지 않았습니다.` : ""} 기준과 작업 폴더는 그대로입니다.`),
    again ? h("p", { class: "acts" }, again) : null), box;
  if (!cs.length) { box.classList.add("replaced");  // S46: an older list, replaced by a re-extraction
    box.append(h("p", { class: "head" }, ico("info", 14), " 이 조건 목록은 다시 뽑은 목록으로 바뀌었습니다"),
      h("p", { class: "muted" }, "이 목록은 기록으로만 남고, 기준 탭과 재현 점검은 새 목록을 씁니다."),
      h("p", null, h("button", { class: "link", "data-spec-newest": "1", on: () => { const x = [...document.querySelectorAll("#log [data-spec]:not(.replaced)")].at(-1); if (x) x.scrollIntoView({ block: "start" }); } }, "새 목록으로 가기")));
    return box; }
  const paper = (cs.find(c => c.paper) || {}).paper;  // C1: which of the task's papers they are from
  const pp = (((M.desk || {})[task] || {}).papers || []).find(p => p.primary && p.kind !== "web");
  const pick = pp && (M.papers || {})[pp.id] ? h("button", { class: "link", "data-spec-pick": "1", title: "PDF에서 문장을 골라 재현 조건으로 더합니다", on: () => show({ mode: "paper", src: pp.id }) }, "PDF에서 조건 더하기") : null;
  box.append(h("div", { class: "sp-top" }, h("p", { class: "head" }, `재현 조건 ${all.length}개 · ${paper || "논문"}${pp && paper === pp.title ? " (주 논문)" : ""}`),
      h("span", { class: "sp-acts" }, again, pick)),
    h("p", { class: "muted sp-sub" }, `원문에서 위치를 확인한 것만 남겼습니다 · 뺀 것 ${dropped || 0}개${secs ? ` · ${secs}초` : ""}`));
  const kinds = Object.keys(KIND_TAG).map(k => [k, all.filter(c => (c.spec.kind || "setting") === k).length]).filter(x => x[1]);
  let want = "";
  const chips = kinds.length > 1 ? h("div", { class: "chips", role: "group", "aria-label": "종류" }) : null;
  const cats = Object.keys(SPEC).map(k => [k, all.filter(c => c.spec.category === k)]).filter(x => x[1].length);
  const opened = new Set(all.length <= 8 ? cats.map(x => x[0]) : cats.slice(0, 2).map(x => x[0]));
  const row = c => h("li", { title: c.id, "data-id": c.id, "data-kind": c.spec.kind || "setting" },
    h("span", { class: "tg kd", title: ASIDE[c.spec.kind] ? ASIDE[c.spec.kind] + " · 재현 점검에서 대조하지 않음" : null }, KIND_TAG[c.spec.kind] || "설정"),
    h("span", { class: "sx" }, rich(plain(c)),
      devOf(c) ? h("span", { class: "chk dev", "data-dev": c.id }, ` ◇ 의도한 차이(${WHERE_DEV[scopeOf(devOf(c))]}): ${devOf(c).why}`) : null),
    c.spec.value_in_quote === false ? h("span", { class: "tg wv", "data-vq": "1", title: "모델이 읽은 값이 고정한 인용 문장 안에 없습니다. 원문에서 직접 확인하세요." }, `값(${c.spec.value})이 인용 안에 없음`) : null,
    c.spec.header_missing ? h("span", { class: "tg wv", "data-hm": "1", title: "PDF 글자에는 표의 머리가 따로 떨어져 있어, 어느 숫자가 어느 데이터셋·지표인지는 모델의 추측입니다. 원문 표에서 확인하세요." }, "표의 열 이름 없음") : null,
    pchip(c), window.pabloHost && pabloHost.condition ? h("span", { class: "racts" }, differ(c, task), takeOut(c)) : null);
  const body = h("div", { class: "sp-body" });
  const draw = () => { body.textContent = ""; const shut = [], pass = c => !want || (c.spec.kind || "setting") === want;
    if (chips) chips.replaceChildren(...[["", "전체", all.length], ...kinds.map(([k, n]) => [k, KIND_TAG[k], n])].map(([k, t, n]) =>
      h("button", { class: "pill chip" + (want === k ? " on" : ""), "data-kind-chip": k || "all", "aria-pressed": String(want === k), on: () => { want = k; draw(); } }, `${t} ${n}`)));
    cats.forEach(([k, xs]) => { const ys = xs.filter(pass); if (!ys.length) return;
      if (!opened.has(k) && !want) return shut.push(h("button", { class: "sp-shut", "data-cat-open": k, on: () => { opened.add(k); draw(); } }, "▸ ", h("b", null, SPEC[k]), " ", h("small", null, ys.length)));
      body.append(h("section", { class: "sp-cat", "data-cat": k }, h("h4", { title: "접기", on: () => { opened.delete(k); draw(); } },
        h("span", { class: "car" }, "▾"), h("span", { class: "nm" }, SPEC[k]), h("small", null, ys.length)), h("ul", null, ys.map(row)))); });
    if (shut.length) body.append(h("div", { class: "sp-shutline" }, shut)); };
  draw();
  box.append(...[chips, body].filter(Boolean));
  const own = codeOf((cs.find(c => c.spec.source_id) || { spec: {} }).spec.source_id).find(x => x.official);  // ⑪
  const decide = c => { if (!window.pabloHost || !pabloHost.makeCriterion) return null;  // B11 / B10: a setting the paper leaves open, decided = a criterion
    const at = h("span", { class: "racts" }), go = h("button", { class: "link", "data-decide": c.id, on: () => {
      const inp = h("input", { class: "why", "data-decide-in": c.id, value: plain(c).replace(/[가-힣\s]*(적혀|나와)\s*있지\s*않다\.?$/, "").trim() + " = " });
      const ok = () => inp.value.trim() && pabloHost.makeCriterion(task, inp.value.trim(), "hard").then(items => { at.replaceChildren(h("span", { class: "muted" }, items.length ? "기준으로 정했습니다." : "이미 같은 기준이 있습니다."));
        if (items.length) echo(task, { role: "intent", items }); return refresh(); }, e => at.append(h("span", { class: "muted" }, " " + fail(e))));
      inp.addEventListener("keydown", e => { if (e.key === "Enter" && !e.isComposing) ok(); });
      at.replaceChildren(inp, " ", h("button", { class: "link", "data-decide-ok": c.id, on: ok }, "정하기")); inp.focus(); } }, "정하기");
    at.append(go); return at; };
  if (open.length) box.append(h("section", { class: "sp-cat open-set" }, h("h4", null, h("span", { class: "car" }, "▾"), h("span", { class: "nm" }, "논문에 없는 설정"),
      h("small", null, open.length), h("span", { class: "hint" }, "정하면 이 작업의 기준이 됩니다")),
    h("ul", { class: "open" }, open.map(c => h("li", { title: c.id, "data-id": c.id }, h("span", { class: "tg kd" }, "정할 일"), h("span", { class: "sx" }, rich(c.title)), decide(c))))),
    h("p", { class: "muted" }, "정할 때는 무엇을 근거로 정했는지 남기세요. 에이전트에게도 그렇게 알립니다.",
      own ? [" 논문의 공식 코드(", h("a", { href: own.url, target: "_blank", rel: "noopener noreferrer", "data-code-hint": "1" }, short_(own.url) + " ↗"), ")에서 먼저 찾아보세요."] : null));
  box.append(h("p", { class: "muted" }, "에이전트는 이 조건을 알고 작업하고, 바꾸려 하면 Pablo가 근거와 함께 막습니다."));
  return diff && !diff.first ? h("div", { class: "specwrap" }, redone(diff), box) : box;
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
// B11: the audit card: 재현 점검 · folder (+ 보고서로), what it held the folder to and when, an old-result band with 다시 점검,
// chips by verdict (badges on the rows), "· 논문 값 X" beside what was found, and per row 의도한 차이로 / 논문 표 행 보기 /
// 정하기. S55: one that did not finish says why, that nothing changed, and 다시 점검
const VGROUP = { differs: "다름", pairing: "확인 필요", unclear: "확인 필요", chosen: "코드가 정함", intended: "의도한 차이", missing: "아직 없음", followed: "따름" };
function audited(c) {
  const box = h("div", { class: "audit", "data-audit": "1" }), task = c.task || V.task.id;
  const again = reAudit && V && V.task.id === task ? h("button", { class: "pill", "data-reaudit": "1", on: () => reAudit(task) }, ico("rotate", 14), "다시 점검") : null;
  if (c.error || c.status === "interrupted" || c.unreadable || !(c.items || []).length) {
    box.classList.add("au-fail");
    box.append(h("p", { class: "head" }, ico("info", 14), " 재현 점검을 마치지 못했습니다"), h("p", { class: "muted" },
      c.status === "interrupted" ? "중지했습니다." : c.error || (c.unreadable ? "에이전트의 답을 읽지 못했습니다." : "판정된 항목이 없습니다."),
      " 파일은 읽기만 했고 아무것도 바뀌지 않았습니다."), again ? h("p", { class: "acts" }, again) : null);
    return box;
  }
  // e2e3 (c86a409): a value read from a table row without its column names: the agent's 따름 / 다름 rests on which number
  // it took for this condition, so it is not counted as a verdict (열 짝 확인 필요, open); chat.json keeps the agent's status
  const unpaired = x => !!((V.checks[x.id] || {}).spec || {}).header_missing && (x.status === "followed" || x.status === "differs");
  const dev = x => devOf(V.checks[x.id], c.at), st = x => x.status === "differs" && dev(x) && scopeOf(dev(x)) === "task" ? "intended"
    : unpaired(x) ? "pairing" : x.status;
  const out = c.outside || [], d0 = (M.desk || {})[task] || {};
  const folder = d0.folder ? d0.folder.split(/[\\/]/).filter(Boolean).pop() : "작업 폴더", nCond = c.items.filter(x => V.checks[x.id]).length;
  const rep = document.querySelector("#reports .link");
  box.append(h("div", { class: "au-top" }, h("p", { class: "head" }, `재현 점검 · ${folder}`),
      rep ? h("button", { class: "pill", "data-to-report": "1", on: () => { const r = document.querySelector("#reports .link"); if (r) r.click(); } }, "보고서로") : null),
    h("p", { class: "muted au-sub" }, `조건 ${nCond} + 작업 기준 ${c.items.length - nCond} · 읽기 전용으로 실행 · ${time(c.at)}`));
  const GORDER = ["다름", "확인 필요", "코드가 정함", "의도한 차이", "아직 없음", "따름", "조건 밖"];
  const groups = [...new Set([...c.items.map(x => VGROUP[st(x)] || st(x)), ...(out.length ? ["조건 밖"] : [])])].sort((a, b) => GORDER.indexOf(a) - GORDER.indexOf(b));
  const count = g => g === "조건 밖" ? out.length : c.items.filter(x => (VGROUP[st(x)] || st(x)) === g).length;
  let want = "";
  const chips = h("div", { class: "chips", role: "group", "aria-label": "판정" }), filter = () => {
    chips.replaceChildren(...[["", `전체 ${c.items.length + out.length}`], ...groups.map(g => [g, `${g} ${count(g)}`])].map(([g, t]) =>
      h("button", { class: "pill chip" + (want === g ? " on" : ""), "data-verdict-chip": g || "all", "aria-pressed": String(want === g), on: () => { want = g; filter(); } }, t)));
    box.querySelectorAll("li[data-g]").forEach(li => { li.hidden = !!want && li.dataset.g !== want; });
    box.querySelectorAll("details").forEach(dt => { if (want) dt.open = !!dt.querySelector("li[data-g]:not([hidden])"); });
    const o = box.querySelector(".outside"); if (o) o.hidden = !!want && want !== "조건 밖"; };
  box.append(chips);
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
    if (k) return [k.evidence.filter(e => M.anchors[e]).slice(0, 1).map(e => M.anchors[e].page  // 07: p.N on the row's right
        ? h("button", { class: "cite pgc au-pg", "data-e": e, title: "근거 보기", on: () => show({ mode: "source", e }) }, `p.${M.anchors[e].page}`) : h("span", { class: "au-pg" }, cite(e))),
      h("span", { class: "muted au-cat" }, k.spec && k.spec.missing ? "논문에 없는 설정" : SPEC[(k.spec || {}).category] || "근거"),
      h("span", { class: "au-t" }, rich((k.conclusion || k.title).replace(/\s*\[\d+\]/g, ""))),
      (k.spec || {}).header_missing && st(x) !== "pairing" ? h("span", { class: "chk warn", "data-hm": "1" }, " ⚠ 논문 값의 열 짝 확인 필요") : null];
    const i = [...V.intent.must, ...V.intent.prefer].find(y => y.id === x.id);
    return [h("span", { class: "muted au-cat" }, "작업 기준"), h("span", { class: "au-t" }, i ? i.text : x.id)]; };
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
  // the row's own actions (hover / focus): a paper condition that differs -> 의도한 차이로; a value read from a table row
  // without its column names -> that row in the paper; a setting the paper leaves open -> 정하기 (a criterion)
  const acts = x => { const k = V.checks[x.id]; if (!k || !k.spec || !window.pabloHost) return null;
    const a = (k.evidence || []).find(e => M.anchors[e]);
    return h("span", { class: "racts" }, st(x) === "differs" && !k.spec.missing && pabloHost.condition ? differ(k, task) : null,
      st(x) === "pairing" && a ? h("button", { class: "link", "data-table-row": x.id, on: () => show({ mode: "source", e: a }) }, "논문 표 행 보기") : null,
      st(x) === "missing" && k.spec.missing && pabloHost.makeCriterion ? h("button", { class: "link", "data-decide": x.id, on: () => {
        const v0 = h("input", { class: "why", "data-decide-in": x.id, value: (k.title || "").replace(/[가-힣\s]*(적혀|나와)\s*있지\s*않다\.?$/, "").trim() + " = " });
        const ok = () => v0.value.trim() && pabloHost.makeCriterion(task, v0.value.trim(), "hard").then(items => { if (items.length) echo(task, { role: "intent", items }); return refresh(); },
          e => v0.after(h("span", { class: "muted" }, " " + fail(e))));
        v0.addEventListener("keydown", e => { if (e.key === "Enter" && !e.isComposing) ok(); });
        const li = box.querySelector(`li[data-id="${CSS.escape(x.id)}"] .racts`); if (li) li.replaceChildren(v0, " ", h("button", { class: "link", on: ok }, "정하기")); v0.focus(); } }, "정하기") : null); };
  const pv = x => { const k = V.checks[x.id] || {}, v0 = (k.spec || {}).value; return v0 && !(k.spec || {}).missing && x.found ? h("span", { class: "pv" }, ` · 논문 값 ${v0}`) : null; };
  const row = x => h("li", { class: "st-" + st(x), title: x.id, "data-id": x.id, "data-g": VGROUP[st(x)] || st(x) },
    h("b", { class: "vb vb-" + st(x) }, (AUDIT[st(x)] || ["", x.status])[1]), " ", what(x), acts(x),
    st(x) === "pairing" ? paired(x) : null,
    dev(x) ? h("div", { class: "muted", "data-dev-why": x.id }, st(x) === "intended" ? `이유: ${dev(x).why}`
      : x.status === "differs" ? `의도한 차이는 별도 실행에서만 두기로 했는데(이유: ${dev(x).why}), 기본 실행이 논문과 다릅니다.`
      : `의도한 차이로 두었지만(이유: ${dev(x).why}) 이 점검에서는 다르지 않았습니다.`) : null,
    x.where || x.found || mark(x) ? h("div", { class: "at" }, x.where ? fileLink(h("code", null, x.where), task, x.where, x.line_found, moved(x), seen(x)) : null,
      x.found ? [" ", h("span", null, x.found)] : null, pv(x), mark(x)) : null, via(x),
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
    const orow = x => h("li", { class: "st-outside", "data-g": "조건 밖" }, h("b", { class: "vb vb-outside" }, "△"), " ", x.what,
      x.where || x.found || mark(x) ? h("div", { class: "at" }, x.where ? fileLink(h("code", null, x.where), task, x.where, x.line_found, moved(x), seen(x)) : null,
        x.found ? [" ", h("span", null, x.found)] : null, mark(x)) : null);
    const m = out.filter(x => x.kind !== "scope").sort((a, b) => warned(b) - warned(a)), s = out.filter(x => x.kind === "scope");
    box.append(h("div", { class: "outside", "data-outside": "1" }, h("h4", null, `조건 밖에서 본 차이 ${out.length}개`),
      m.length ? h("ul", null, m.map(orow)) : null,
      s.length ? h("details", null, h("summary", null, `논문의 실험 가운데 이 폴더에 없는 것 ${s.length}개`), h("ul", null, s.map(orow))) : null,
      h("p", { class: "muted" }, "재현 조건 목록 밖이라 논문 쪽이 붙지 않습니다. 중요한 차이면 논문에서 확인하고 조건을 다시 뽑아 보세요.")));
  }
  filter();
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
  const again = () => reAudit && V && V.task.id === task ? [" ", h("button", { class: "pill on", "data-reaudit": "1", on: () => reAudit(task) }, "다시 점검")] : null;
  const put = line => { const old = box.querySelector(":scope > .stale"); if (old) old.replaceWith(line || ""); else if (line) (box.querySelector(":scope > .au-sub") || box.querySelector(".head")).after(line); };
  const changed = () => files.length ? h("p", { class: "stale", "data-stale": String(files.length) },
    `⚠ 이 점검 뒤 파일 ${files.length}개가 바뀌었습니다(${files.slice(0, 3).join(", ")}${files.length > 3 ? " 외" : ""}). 판정이 지금 파일과 다를 수 있습니다.`, again()) : null;
  // places, not rows: a condition and a criterion often point at the same line (rehearsal 10/27: "config.yaml:5, config.yaml:5")
  // a row on two places ("config.yaml:5; run.py:3") is named and counted by its first (demo 10/27); recheck still gets them all
  const at = x => x.line_found ? `${where0(x.where)}:${x.line_found}` : String(x.where).split(/;\s*/)[0], seen = new Set();
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
  const tsk = c.task || V.task.id;  // B12: 항목 바꾸기 (the 비교표 form with these columns) and 크게 보기 in the head
  if (!wide) box.append(h("div", { class: "mx-top" }, h("p", { class: "head" }, `비교표 · 논문 ${c.papers.length}편 × 항목 ${c.columns.length}개`),
      h("span", { class: "sp-acts" }, compareAgain ? h("button", { class: "pill", "data-columns": "1", on: () => compareAgain(tsk, c.columns) }, "항목 바꾸기") : null,
        h("button", { class: "link", "data-wide": "1", on: () => show({ mode: "matrix", c }) }, "크게 보기"))),
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
  if (!wide && addSource) box.append(h("p", { class: "mx-foot" }, h("button", { class: "link", "data-add-paper": "1", title: "자료에 논문을 더한 뒤 항목 바꾸기로 표를 다시 만듭니다", on: () => addSource() }, "+ 논문 추가")));
  return box;
}
// criteria the user said in a chat message, now this task's intent (Guard and the agent's brief use them).
// A2 complete (B4-B6): one band per kind, no avatar (.msg.note): added (orange soft), held back (a card that asks),
// not read (grey). [data-intent] keeps its words ("📌 작업 기준에 추가했습니다: …"); the pin is an icon on screen
const noted = c => { const task = c.task || (V && V.task.id), m = msg("Pablo", null,
  (c.items || []).length ? h("p", { class: "band ok", "data-intent": "1" }, ico("check-circle", 16), h("span", { class: "bt" }, h("span", { class: "em" }, "📌 "),
    "작업 기준에 추가했습니다: ", c.items.map(i => `${i.text} (${i.strength === "hard" ? "반드시" : "가능하면"})`).join(" · ")), " ",
    h("button", { class: "link rt", on: () => show({ mode: "intent" }) }, "기준 보기")) : null,
  (c.pending || []).map(k => held({ ...k, live: c.live }, task)),
  (c.unread || []).map(u => unreadRow({ ...u, live: c.live }, task)));
  m.classList.add("note"); return m; };
// ③ a line the reader could not classify is shown, never dropped: the user makes it a rule (반드시 / 가능하면) or lets it go.
// B6 / S48: a grey band; "기준으로 추가 ▾" opens the three choices (the buttons stay in the DOM: [data-as])
function unreadRow(u, task) {
  const open = u.live || (V && (V.intent.unread || []).includes(u.id));
  const row = h("div", { class: "band q", "data-unread": u.id }, ico("info", 14),
    h("span", { class: "bt" }, "기준으로 읽지 못했습니다 · “", h("b", null, u.text), "” — 요청으로만 처리했습니다"), " ");
  const was = { hard: "(반드시로 둠)", soft: "(가능하면으로 둠)", skip: "(넘김)", rule: "(기준으로 둠)" }[((V && V.intent.decided) || {})[u.id]] || "(처리함)";
  if (!open || !window.pabloHost || !pabloHost.intent) return row.append(h("span", { class: "rt muted" }, open ? "" : was)), row;
  const act = (a, done) => () => pabloHost.intent(task, u.id, a).then(() => {
    row.lastChild.replaceWith(h("span", { class: "rt muted", "data-decided": a }, done));
    // the new-task message counts what is still to decide, and stops asking once nothing is
    const left = document.querySelectorAll("[data-unread] [data-as]").length, ask = document.querySelector("[data-made] [data-ask]");
    if (ask) ask.textContent = left ? `아직 정하지 않은 줄 ${left}개가 위에 있습니다. ` : "읽지 못한 줄도 모두 정했습니다. ";
    refresh(); }, e => row.append(h("span", { class: "muted" }, " " + fail(e))));
  const menu = h("span", { class: "asmenu", role: "group", "aria-label": "기준으로 둘까요?", hidden: true },
    h("button", { type: "button", "data-as": "hard", on: act("hard", "반드시 지킬 기준으로 두었습니다.") }, "반드시"),
    h("button", { type: "button", "data-as": "soft", on: act("soft", "가능하면 지킬 기준으로 두었습니다.") }, "가능하면"),
    h("button", { type: "button", "data-as": "skip", on: act("reject", "기준으로 두지 않았습니다.") }, "괜찮음"));
  const tog = h("button", { class: "link", "data-as-open": "1", "aria-expanded": "false", on: () => { menu.hidden = !menu.hidden; tog.setAttribute("aria-expanded", String(!menu.hidden)); } },
    "기준으로 추가 ", ico("chevron-down", 12));
  row.append(h("span", { class: "rt" }, tog, menu));
  return row;
}
// B4: a criterion said in hedged words is held back until the user decides. B5: under its message a card that asks (an
// orange edge: it waits on the person); compact (S47) in the closing 결정 card and once decided
function held(k, task, compact) {
  const open = k.live || (V && V.intent.questions.some(q => q.id === k.id)), can = !k.done && open && window.pabloHost && pabloHost.intent;
  let el = null;
  const act = (a, done) => () => pabloHost.intent(task, k.id, a).then(() => { el.replaceWith(held({ ...k, live: false, done }, task, true)); refresh(); },
    e => el.append(h("span", { class: "muted" }, " " + fail(e))));
  if (can && !compact) return el = h("div", { class: "hold", "data-held": k.id }, h("p", { class: "ttl" }, "결정이 필요합니다"),
    h("p", null, "“", h("b", null, k.text), "” — 이 작업의 기준으로 남길까요?"),
    h("p", { class: "acts" }, h("button", { class: "pill on", "data-promote": k.id, on: act("promote", "기준에 추가했습니다.") }, "기준으로 추가 (가능하면)"),
      h("button", { class: "pill", "data-reject": k.id, on: act("reject", "무시했습니다.") }, "무시")));
  el = h("p", { class: "band q", "data-held": k.id }, ico("info", 14), h("span", { class: "bt" }, "기준으로 둘까요? ", h("b", null, k.text)), " ");
  if (!can) return el.append(h("span", { class: "rt muted" }, k.done || (open ? "" : "(처리함)"))), el;
  el.append(h("span", { class: "rt" }, h("button", { class: "link", "data-promote": k.id, on: act("promote", "기준에 추가했습니다.") }, "기준으로 추가"), " ",
    h("button", { class: "link", "data-reject": k.id, on: act("reject", "무시했습니다.") }, "무시")));
  return el;
}
function said(c) {
  if (c.role === "audit") return [msg("Pablo", null, audited(c))];
  if (c.role === "spec") return [msg("Pablo", null, conditions([...(c.checks || []), ...(c.missing || [])], c.dropped, c.diff, c.secs))];
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
    c.status === "interrupted" ? stopped() : null, c.error ? failCard("실행하지 못했습니다", c.error) : null)];
  if (c.role !== "ask") return [];
  const k = c.check && V.checks[c.check];
  return [msg("You", c.at, h("p", null, c.text)), msg("Pablo", null, h("div", { class: "asked", "data-check": c.check || "" },
    k ? [h("p", null, cited(k.conclusion || k.title, k.evidence)), webOnly(k), verified(k, c.dropped)]
      : failCard(c.error ? "답을 찾지 못했습니다" : ASKFAIL.replace(/\.$/, ""), c.error || null)))];
}
// B24 / S12: before an arXiv download, the file it is saved as, where from and how big: [받기] [취소] (peek =
// pabloHost.peekArxiv(text); nothing is downloaded until 받기). The add box and the new-task dialog put it where they ask
function downloadCard(peek, onGet, onCancel) {
  const size = b => b == null ? "크기 모름" : b >= 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB";
  const card = h("div", { class: "call dl-card", "data-download": peek.id || "" }, h("p", { class: "head" }, "arXiv에서 받을까요?"),
    h("div", { class: "dl-file" }, h("code", null, peek.filename), h("small", null, `출처 ${peek.source} · ${size(peek.bytes)} · 50 MB 상한 안`)),
    peek.title ? h("p", { class: "muted" }, peek.title + (peek.version ? " " + peek.version : "")) : null,
    h("p", { class: "acts" }, h("button", { class: "pill on", "data-dl-get": "1", on: () => { card.remove(); if (onGet) onGet(); } }, "받기"),
      h("button", { class: "pill", "data-dl-cancel": "1", on: () => { card.remove(); if (onCancel) onCancel(); } }, "취소")));
  return card;
}
// B18 / B19 (S5 / S7): a running extraction or audit is a card with its stage, how far it got (D9 progress), how long it
// usually takes or that it only reads, and 중지
function progCard(key, label, sub, what, foot, stop) {
  const s = stagesOf(V, (M.desk || {})[V.task.id]), i = s.steps.findIndex(x => x.key === key), bar = h("i"), line = h("p", { class: "pg-t" }, what);
  const box = h("div", { class: "prog" }, h("div", { class: "pg-bar0" }), h("p", { class: "pg-st" }, i >= 0 ? [h("span", { class: "pg-n" }, String(i + 1).padStart(2, "0")), " "] : null, label),
    h("p", { class: "pg-sub" }, sub), line, h("div", { class: "pg-bar" }, bar),
    h("p", { class: "pg-foot" }, h("span", null, foot), stop ? h("button", { class: "pill soft", "data-prog-stop": key, on: e => { e.currentTarget.disabled = true; stop(); } }, "중지") : null));
  box._set = (text, frac) => { line.textContent = text; bar.style.width = Math.round(Math.max(0.03, Math.min(1, frac)) * 100) + "%"; };
  box._set(what, 0.03); return box; }
// S42: a stopped answer keeps what came; said right under it
const stopped = () => h("p", { class: "muted stopped", "data-stopped": "1" }, ico("info", 14), " 중지했습니다. 여기까지 받은 답은 남겨 둡니다.");
// an edit made just now (panel, picked sentence): its line joins the conversation at once (chat.json has it for later)
function echo(task, c) {
  if (!V || V.task.id !== task) return;
  live(task).append(...said(c)); $("log").scrollTop = $("log").scrollHeight;
}
// one timeline: the task, its research, the chat log and the Guard cards, in the order they happened
// P4: each message's stage, from what the record is (a spec is 조건 확정, an audit 재현 점검, ...), a divider where
// the stage changes, and a tag row: the stage, then what it is about (files, [n]); the rest folds into "N개 더"
function kindOf() { return kindFor((M.desk || {})[V.task.id]); }
// any task's kind from its desk entry (M.desk[id]): the one it was made as, else what it has (folder + paper, paper, none)
function kindFor(d) { d = d || {}; const ps = d.papers || [];
  return d.kind || (d.folder && ps.length ? "repro" : ps.length ? "read" : "general"); }
// D1: a task's stages from its records alone, for any task (the stage bar; the sidebar's progress): v = M.views[id],
// d = M.desk[id], kind = kindFor(d) when not given. A step's state comes from what is recorded, nothing is enforced.
// -> {steps: [{key, label, state: done|current|todo|blocked|stale, sub}], current: index of the current step or -1,
//     can: {spec, compare, audit, report}: what the stage bar's actions need (#specs/#compares/#audits/#reports)}
function stagesOf(v, d, kind) {
  d = d || {}; kind = kind || kindFor(d);
  const ps = d.papers || [], pdfs = ps.filter(p => p.kind !== "web"), chat = v.chat || [], checks = v.checks || {};
  const intent = v.intent || {}, actions = v.actions || [];
  const specs = (v.research || []).map(id => checks[id]).filter(k => k && k.spec && k.state !== "waived"), hasSpec = specs.length > 0;
  const audits = chat.filter(c => c.role === "audit"), la = audits[audits.length - 1];
  const staleAudit = !!la && chat.some(c => (c.role === "changes" || c.role === "undo") && c.at > la.at);
  const differ = la ? (la.items || []).filter(x => x.status === "differs").length : 0;
  const toDecide = specs.filter(k => k.state === "pending").length + (intent.questions || []).length;
  const waiting = actions.some(a => a.verdict === "WARN" && !a.decision);
  const reported = chat.some(c => c.role === "report"), asked = chat.filter(c => c.role === "ask").length;
  const compared = chat.some(c => c.role === "compare");
  const changedFiles = chat.filter(c => c.role === "changes").reduce((n, c) => n + (c.files || []).length, 0);
  // an audit needs a folder and something to hold the code to; a report needs a record to report
  const can = { spec: ps.length > 0, compare: pdfs.length > 1,
    audit: !!d.folder && (hasSpec || (intent.must || []).length > 0 || (intent.prefer || []).length > 0),
    report: hasSpec || actions.length > 0 || audits.length > 0 };
  const step = (key, label, state, sub) => ({ key, label, state, sub });
  const steps = kind === "repro" ? [
    step("prep", "준비", ps.length && d.folder ? "done" : "todo", ps.length && d.folder ? `논문 ${pdfs.length} · 폴더` : !ps.length ? "논문 필요" : "폴더 필요"),
    step("spec", "조건 확정", !ps.length ? "blocked" : hasSpec && !toDecide ? "done" : "todo",
      !ps.length ? "주 논문 필요" : !hasSpec ? "조건 뽑기 전" : toDecide ? `정할 일 ${toDecide}` : `조건 ${specs.length}`),
    step("run", "구현·실행", !d.folder ? "blocked" : la && !waiting ? "done" : "todo",
      !d.folder ? "폴더 필요" : waiting ? "확인 기다림" : actions.length ? `행동 ${actions.length}` : "—"),
    step("audit", "재현 점검", !can.audit ? "blocked" : staleAudit ? "stale" : la ? "done" : "todo",
      !can.audit ? "폴더 · 조건 필요" : staleAudit ? "오래됨 · 다시 필요" : la ? (differ ? `다름 ${differ}` : "점검함") : "점검 전"),
    step("report", "보고서", reported ? "done" : "todo", reported ? "저장함" : can.report ? "할 수 있음" : "—")]
  : kind === "read" ? [
    step("prep", "준비", ps.length ? "done" : "todo", ps.length ? `논문 ${ps.length}` : "논문 필요"),
    step("ask", "질문", asked && compared ? "done" : "todo", asked ? `질문 ${asked}` : "질문 전"),
    step("compare", "비교표", pdfs.length < 2 ? "blocked" : compared ? "done" : "todo", pdfs.length < 2 ? "논문 2편 필요" : compared ? "만듦" : "할 수 있음"),
    step("wrap", "정리", reported ? "done" : "todo", reported ? "저장함" : "—")]
  : [step("prep", "준비", d.folder ? "done" : "todo", d.folder ? "폴더" : "폴더 필요"),
    step("work", "작업", reported ? "done" : "todo", waiting ? "확인 기다림" : changedFiles ? `바뀐 파일 ${changedFiles}` : "—"),
    // the audit of the folder against the task's criteria is part of 검토 (QA 10/26: it floated past the last stage)
    step("review", "검토", reported ? "done" : "todo", reported ? "저장함" : "—")];
  const current = steps.findIndex(s => s.state === "todo"); if (current >= 0) steps[current].state = "current";
  return { steps, current, can };
}
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
// A2 complete (B2): what a message is about, as [label, ref]: the criteria and paper conditions it names (D2 refs; only
// for what a person or the agent said, a Guard card, a criterion change: a conditions card or an audit names dozens), its
// work-folder files, the pages it quotes ("LinearRAG p.9", not the chat's running [n])
const clip = (s, n) => { s = String(s || "").replace(/\s*\[\d+\]/g, "").replace(/\s+/g, " ").trim(); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
let refMemo = null;
const refsFor = key => { if (!V || !key) return [];
  if (!refMemo || refMemo.v !== V || refMemo.n !== (V.chat || []).length) refMemo = { v: V, n: (V.chat || []).length, m: refsByKey(V) };
  return refMemo.m.get(key) || []; };
const critOf = id => V ? [...V.intent.must, ...V.intent.prefer].find(x => x.id === id) : null;
const RECORDS = ["spec", "spec-loose", "audit", "compare", "changes", "undo", "research", "start", "report"];
function targetsOf(el, key) {
  const out = [], seen = new Set(), put = (label, ref) => { if (!seen.has(label)) { seen.add(label); out.push([label, ref || null]); } };
  const role = !key ? "" : key.startsWith("act:") ? "act" : key.split("@")[0];
  if (key && !RECORDS.includes(role) && !role.startsWith("issue")) refsFor(key).forEach(r => {
    if (/^[CK]\d+$/.test(r)) { const c = critOf(r); if (c) put("기준 · " + clip(c.text, 18), r); }
    else if (/^SC\d+$/.test(r)) { const k = V.checks[r]; if (k && k.spec && !k.spec.missing && !k.matrix) put("조건 · " + clip(k.conclusion || k.title, 18), r); } });
  [...new Set([...el.querySelectorAll("button.file code, .at code")].map(c => c.textContent.split(":")[0]))].forEach(f => put("파일 · " + f, "file:" + f));
  el.querySelectorAll(".cite").forEach(c => { const a = M.anchors[c.dataset.e], s = a && M.sources[a.source];
    if (a && a.page && s && s.title) put(`근거 · ${clip(s.title, 24)} p.${a.page}`, a.source + ":p" + a.page); else put("근거 · " + c.textContent, c.dataset.e); });
  return out;
}
// every target label the conversation has drawn -> its ref (the popover's suggestions; a label added by hand finds its ref)
const knownTargets = () => { const m = new Map(); document.querySelectorAll("#log .msg[data-trefs]").forEach(x => {
  let t = {}; try { t = JSON.parse(x.dataset.trefs); } catch (e) {} Object.entries(t).forEach(([k, r]) => m.set(k, r)); });
  if (V) { [...V.intent.must, ...V.intent.prefer].forEach(c => m.has("기준 · " + clip(c.text, 18)) || m.set("기준 · " + clip(c.text, 18), c.id));
    V.research.map(id => V.checks[id]).filter(k => k && k.spec && !k.spec.missing && k.state !== "waived").forEach(k => m.set("조건 · " + clip(k.conclusion || k.title, 18), k.id)); }
  return m; };
// B3 (user decision 10/27: rules, no model call): a message whose words or refs belong to another stage than the one it
// was sent in gets "✦ 제안 · <stage>" with 맞음 / 아님 and why. 맞음 = the person's stage (tags[key] {stage, ok}); 아님 =
// {suggest: "no"}: not asked again
function suggestFor(el, key, stage) {
  const role = key && !key.startsWith("act:") ? key.split("@")[0] : "", kind = kindOf();
  if (role !== "user") return null;  // what the person said; a record's stage is what it is
  const text = msgWords(el, 2000), rs = refsFor(key);
  const paper = rs.some(r => /^SC\d+$/.test(r) && ((V.checks[r] || {}).spec)) || !!el.querySelector(".cite")
    || /논문|조건|부록|근거|원문|저자|\bp\.\s?\d|\d+\s?쪽|표\s?\d|Table\s?\d|appendix/i.test(text);
  const want = kind === "repro" ? (/보고서/.test(text) ? "보고서" : /점검|논문과\s*(같|다르|맞)|재현이?\s*(됐|되었|맞)/.test(text) ? "재현 점검" : paper ? "조건 확정" : null)
    : kind === "read" ? (/비교|표로|표에/.test(text) ? "비교표" : /정리|요약|보고서/.test(text) ? "정리" : null)
    : (/보고서|검토/.test(text) ? "검토" : null);
  if (!want || want === stage || !(STAGE_LIST[kind] || []).includes(want)) return null;
  const why = { "조건 확정": "논문 조건·근거를 가리키는 말", "재현 점검": "논문과 맞는지 보는 말", "보고서": "보고서에 대한 말", "비교표": "비교에 대한 말",
    "정리": "정리에 대한 말", "검토": "검토에 대한 말" }[want];
  return { stage: want, why: `${stage} 중에 보낸 말이지만 ${why}이라 ${want} 단계로 볼 수 있습니다.` };
}
// a person's tag for one message (P5), kept in desktop.json; then the view is drawn again
const setTag = (key, v) => { const task = V.task.id, tags = { ...(((M.desk || {})[task] || {}).tags || {}) };
  if (v && Object.keys(v).length) tags[key] = v; else delete tags[key];
  return pabloHost.setUi(task, "tags", tags).then(() => refresh()).then(() => V && V.task.id === task && conversation()); };
// held-back criteria of this message's turn that still wait: "✦ 제안 · 기준(가능하면)" on the message (B3)
const heldOf = key => { if (!V || !key || !key.startsWith("user@")) return [];
  const turn = turnsOf(V), open = new Set(V.intent.questions.map(q => q.id));
  return (V.chat || []).filter(c => c.role === "intent" && turn.get("intent@" + c.at) === key).flatMap(c => c.pending || []).filter(k => open.has(k.id)); };
// o: the person's override for this message (P5: {stage, decision, targets, ok, suggest}); auto: the stage Pablo computed
function tagRow(el, stage, key, o = {}, auto = stage, all = false) {
  const body = el.children && el.children[1]; if (!body || body.querySelector(":scope > .tags")) return;
  const found = targetsOf(el, key), refOf = new Map(found);
  const pairs = Array.isArray(o.targets) ? o.targets.map(t => [t, refOf.get(t) || knownTargets().get(t) || null]) : found;
  const targets = pairs.map(p => p[0]);
  el.dataset.targets = JSON.stringify(targets); el.dataset.trefs = JSON.stringify(Object.fromEntries(pairs.filter(p => p[1])));
  const shown = all ? targets : targets.slice(0, 2), more = targets.length - shown.length;
  const can = !!(key && window.pabloHost && pabloHost.setUi);
  const sug = can && !o.stage && !o.ok && o.suggest !== "no" ? suggestFor(el, key, stage) : null, wait = heldOf(key);
  const row = h("div", { class: "tags", "data-auto": auto }, h("span", { class: "tg stage" + (o.stage ? " mine" : ""), title: o.stage ? `사람이 고침 (자동: ${auto})` : null }, stage),
    o.decision ? h("span", { class: "tg manual", "data-decision": "1" }, "결정") : null, ...shown.map(t => h("span", { class: "tg tgt" }, t)),
    sug ? [h("span", { class: "tg sug", "data-suggest": sug.stage, title: sug.why }, ico("sparkle", 12), "제안 · " + sug.stage),
      h("button", { class: "tagbtn yes", "data-suggest-ok": "1", on: () => setTag(key, { ...o, stage: sug.stage, ok: true }) }, "맞음"),
      h("button", { class: "tagbtn no", "data-suggest-no": "1", on: () => setTag(key, { ...o, suggest: "no" }) }, "아님")] : null,
    wait.length ? h("button", { class: "tg sug", "data-suggest-crit": wait[0].id, title: "이 말에서 기준이 될 만한 줄을 찾았습니다. 아래에서 정해 주세요.",
      on: () => { const x = document.querySelector(`#log [data-held="${CSS.escape(wait[0].id)}"]`); if (x) x.scrollIntoView({ block: "center" }); } },
      ico("sparkle", 12), "제안 · 기준(가능하면)") : null,
    more ? h("small", { class: "more" }, `· ${more}개 더`) : null);
  // B2: one "+ 태그" for the stage, the targets, 결정 and 기준으로 만들기 (the popover, B15)
  if (can) row.append(h("button", { class: "tagbtn", "data-tag-edit": "1", title: "이 메시지의 태그 고치기 · 기준으로 만들기", on: () => tagEdit(row, key, stage, o, el) }, "+ 태그"));
  // 06 07 08 F25: a record card's tags sit under the name, above the card
  const who = body.querySelector(":scope > .who");
  if (who && body.querySelector(":scope > .spec, :scope > .specwrap, :scope > .audit, :scope > .matrix, :scope > .redo-card")) { row.classList.add("top"); who.after(row); }
  else body.append(row);
  if (sug) row.after(h("p", { class: "sugwhy", "data-suggest-why": "1" }, sug.why));
}
// a message's words made a criterion of this task by the person, in a sentence they trim: a rule (반드시 / 가능하면), never
// the goal. Guard, the brief and 재현 점검 follow at once; the conversation says so
const msgWords = (el, max) => [...el.children[1].children].filter(c => !c.classList.contains("who") && !c.classList.contains("tags") && !c.classList.contains("sugwhy"))
  .map(c => c.textContent).join(" ").replace(/\s+/g, " ").trim().slice(0, max);
// P5 + B15: the tag popover (320): the stage (the computed one says so), the targets (× / + 잇기), 결정으로 고정, and 기준으로
// 만들기 (the message's words, trimmed, 반드시 / 가능하면: makeCriterion). The person's tag wins over every redraw
function tagEdit(row, key, stage, o, el) {
  const old = document.querySelector(".tagedit"); if (old) { const mine = old.parentNode === row; old.remove(); if (mine) return; }
  const names = STAGE_LIST[kindOf()] || STAGE_LIST.general, task = V.task.id, auto = row.dataset.auto, id = key.replace(/[^\w]/g, "");
  const targets = JSON.parse(el.dataset.targets || "[]"), orig = JSON.stringify(targets);
  const chips = h("div", { class: "te-tg" }), draw = () => chips.replaceChildren(...(targets.length ? targets.map((t, i) => h("span", { class: "tg tgt" }, t,
    h("button", { class: "te-x", type: "button", title: "이 대상 빼기", "data-tag-drop": t, on: () => { targets.splice(i, 1); draw(); } }, "×"))) : [h("small", { class: "muted" }, "대상 없음")]));
  draw();
  const add = h("input", { class: "te-add", placeholder: "+ 조건 · 기준 · 파일 잇기", list: "te-dl-" + id, "data-tag-add": "1" });
  add.addEventListener("keydown", e => { if (e.key !== "Enter" || e.isComposing || !add.value.trim()) return; e.preventDefault();
    const t = add.value.trim(); if (!targets.includes(t)) targets.push(t); add.value = ""; draw(); });
  const dec = h("input", { type: "checkbox", "data-tag-dec": "1", checked: o.decision ? true : null });
  const mk = h("input", { type: "checkbox", "data-crit-on": "1" });
  const text = h("textarea", { class: "ce-text", "data-crit-text": "1", rows: 2, maxlength: 1000 }); text.value = msgWords(el, 300);
  const crit = h("div", { class: "te-crit", hidden: true }, text, h("div", { class: "te-st" }, [["hard", "반드시"], ["soft", "가능하면"]].map(([v, n]) =>
    h("label", null, h("input", { type: "radio", name: "ce-" + id, value: v, checked: v === "hard" ? true : null }), " ", n))));
  mk.addEventListener("change", () => { crit.hidden = !mk.checked; if (mk.checked) text.focus(); });
  const note = h("p", { class: "te-note" }, "사람이 고친 태그는 다시 계산해도 유지됩니다");
  const save = async () => {
    const st = (ed.querySelector(`input[name="te-${id}"]:checked`) || {}).value || stage, v = { ...o };
    delete v.stage; delete v.decision; delete v.targets;
    if (st !== auto) v.stage = st; if (dec.checked) v.decision = true;
    if (JSON.stringify(targets) !== orig) v.targets = targets; else if (Array.isArray(o.targets)) v.targets = o.targets;
    if (mk.checked) { const t = text.value.trim(); if (!t) return text.focus();
      try { const items = await pabloHost.makeCriterion(task, t, ed.querySelector(`input[name="ce-${id}"]:checked`).value);
        if (!items.length) return note.replaceChildren("이미 같은 기준이 있습니다."); echo(task, { role: "intent", items }); }
      catch (e) { return note.replaceChildren(fail(e)); } }
    ed.remove();
    return JSON.stringify(v) !== JSON.stringify(o) ? setTag(key, v) : mk.checked ? refresh() : null; };
  const ed = h("div", { class: "tagedit", role: "dialog", "aria-label": "이 메시지의 태그" }, h("b", null, "이 메시지의 태그"),
    h("div", { class: "te-sec" }, "단계"),
    h("div", { class: "te-st te-stage" }, names.map(n => h("label", null, h("input", { type: "radio", name: "te-" + id, value: n, checked: n === stage ? true : null }), " ", n,
      n === auto ? h("small", null, "자동 · 보낸 때 단계") : null))),
    h("div", { class: "te-sec" }, "대상"), chips, add, h("datalist", { id: "te-dl-" + id }, [...knownTargets().keys()].map(t => h("option", { value: t }))),
    h("div", { class: "te-sec" }, "표시"),
    h("label", { class: "te-dec" }, dec, " 결정으로 고정 — 결정 목록 · 보고서에 들어감"),
    h("label", { class: "te-dec" }, mk, " 기준으로 만들기"), crit,
    h("div", { class: "te-foot" }, note, h("button", { class: "pill on", "data-tag-save": "1", on: save }, "완료")));
  ed.addEventListener("keydown", e => { if (e.key === "Escape") { e.stopPropagation(); ed.remove(); } });
  row.append(ed);
}
// a click outside the tag popover closes it (Esc too)
addEventListener("mousedown", e => { const ed = document.querySelector(".tagedit"); if (ed && !e.target.closest(".tagedit, [data-tag-edit]")) ed.remove(); }, true);
const firstText = el => { const p = el.querySelector("p"); return (p ? p.textContent : el.textContent).replace(/\s+/g, " ").trim().slice(0, 90); };
// P6 단계별: one box per stage; past ones show a summary (the person's text wins over the record-based one) and the
// decisions, their messages folded; the current stage is open; stages not reached yet are placeholders.
// A2 complete (B13): the head says the stage, its state, "메시지 N · HH:mm–HH:mm" and 대화 펼치기 ▸ / 접기 ▾; the summary
// reads "모델 요약 — …" or "사람이 고친 요약 — …" (사람이 고침 · 다시 만들어도 이 글이 유지됩니다) with ✎ 요약 고치기 ·
// 다시 만들기; each decision has its time
function byStage(log, rows, kind, D) {
  const names = STAGE_LIST[kind] || STAGE_LIST.general, cur = (document.querySelector("#stages .st-current b") || {}).textContent;
  const ci = names.indexOf(cur), can = window.pabloHost && pabloHost.setUi;
  names.forEach((n, i) => {
    const mine = rows.filter(r => r[1] === n), msgs = mine.filter(r => r[0].classList && r[0].classList.contains("msg")), decs = mine.filter(r => r[2].decision);
    const files = new Set(mine.flatMap(r => [...r[0].querySelectorAll("button.file code, .at code")].map(c => c.textContent.split(":")[0]))).size;
    // a stage with messages is never 아직, whatever the stage bar computes from the material (진행: talked about, not done);
    // one the bar marks done (✓) is 완료 here too (QA 10/26: ✓ above, 진행 below for the same stage)
    const done = !!document.querySelector(`#stages .stage.st-done[data-stage="${STAGE_KEY[n] || ""}"]`);
    const state = i === ci ? "지금" : done || (ci >= 0 && i < ci) ? "완료" : !msgs.length ? "아직" : "진행", own = (D.summary || {})[n];
    const ts = msgs.map(r => r[3]).filter(Boolean), span = ts.length ? `${time(Math.min(...ts))}–${state === "지금" ? "" : time(Math.max(...ts))}` : "";
    const facts = msgs.length ? [`메시지 ${msgs.length}`, span, decs.length ? `결정 ${decs.length}` : null, files ? `파일 ${files}` : null].filter(Boolean).join(" · ") : "아직 대화가 없습니다";
    // the model's summary, written on request; behind once the stage has more messages than it read. A person's text wins
    const auto = (D.auto || {})[n], behind = auto ? msgs.length - auto.n : 0;
    const write = can && pabloHost.summarize && !own && msgs.length && ($("acct") || { dataset: {} }).dataset.state === "connected";
    // `x` in a summary is code, as in the cards (QA 10/26: the model's backticks showed as they are)
    const sum = h("div", { class: "sg-sum" }, own ? [h("b", { class: "sum-k" }, "사람이 고친 요약"), " — ", rich(own)]
      : auto ? [h("b", { class: "sum-k", "data-auto-summary": "1" }, "모델 요약"), " — ", rich(auto.text),
        behind > 0 ? h("small", { class: "muted", "data-behind": behind }, ` · 그 뒤 메시지 ${behind}개`) : null]
      : h("span", { class: "muted" }, "기록 요약 — " + facts),
      own ? h("p", { class: "sg-own" }, h("span", { class: "tg manual" }, "사람이 고침"), h("small", null, "다시 만들어도 이 글이 유지됩니다")) : null,
      can && msgs.length || write ? h("p", { class: "sg-tools" },
        can && msgs.length ? h("button", { class: "link", "data-summary-edit": n, on: () => summaryEdit(sum, n, own || (auto && auto.text) || "") }, ico("pencil", 12), " 요약 고치기") : null,
        write ? [can && msgs.length ? h("span", { class: "muted" }, " · ") : null, h("button", { class: "link", "data-summarize": n, on: () => summarize(sum, n, msgs) }, auto ? "다시 만들기" : "요약 쓰기")] : null) : null);
    const opened = state === "지금" || (ci < 0 && state === "진행");
    const box = h("div", { class: "sg-msgs", hidden: !opened }, mine.map(r => r[0]));
    const tog = mine.length ? h("button", { class: "link sg-tog", "data-sg-toggle": n, "aria-expanded": String(opened), on: () => {
      box.hidden = !box.hidden; tog.setAttribute("aria-expanded", String(!box.hidden)); tog.textContent = box.hidden ? "대화 펼치기 ▸" : "접기 ▾"; } }, opened ? "접기 ▾" : "대화 펼치기 ▸") : null;
    log.append(h("div", { class: "stagegroup st-" + (state === "지금" || state === "진행" ? "now" : state === "아직" ? "later" : "past"), "data-stage": n },
      h("div", { class: "sg-head" }, h("span", { class: "tg stage" }, n), h("b", null, state), h("small", null, facts), tog), sum,
      decs.length ? [h("p", { class: "sg-dh" }, `결정 ${decs.length}`), h("ul", { class: "sg-dec" }, decs.map(r => h("li", null, h("span", { class: "tg manual" }, "결정"), " ",
        firstText(r[0]), r[3] ? h("small", null, ` · ${time(r[3])}`) : null)))] : null,
      mine.length ? box : null));
  });
  rows.filter(r => !names.includes(r[1])).forEach(r => log.append(r[0]));
}
// one model call per click (not on every redraw): the stage's messages as the page groups them, oldest first
function summarize(sum, n, msgs) {
  const task = V.task.id, btn = sum.querySelector("[data-summarize]");
  if (btn) { btn.disabled = true; btn.replaceChildren(h("span", { class: "spin" }), " 요약 쓰는 중…"); }
  pabloHost.summarize(task, n, msgs.map(r => ({ who: r[0].classList.contains("pablo") ? "Pablo" : "You", text: msgWords(r[0], 4000) })))
    .then(() => refresh()).then(() => V && V.task.id === task && conversation(),
      e => { if (btn) btn.remove(); sum.append(h("span", { class: "muted" }, " " + fail(e))); });
}
// S54: the person's own summary; it stays when the model writes again
function summaryEdit(sum, n, cur) {
  const task = V.task.id, ta = h("textarea", { class: "sg-edit", rows: 3 }); ta.value = cur;
  sum.replaceChildren(ta, h("p", { class: "muted" }, "사람이 고친 요약은 다시 써도 바뀌지 않습니다."), h("div", { class: "te-foot" },
    h("button", { class: "pill on", "data-summary-save": n, on: () => { const all = { ...(((M.desk || {})[task] || {}).summary || {}) }, t = ta.value.trim();
      if (t) all[n] = t; else delete all[n];
      pabloHost.setUi(task, "summary", all).then(() => refresh()).then(() => V && V.task.id === task && conversation()); } }, "저장"),
    h("button", { class: "pill", on: () => conversation() }, "취소")));
  ta.focus();
}
// P6 대상별: grouped by what each message is about (its first target); the rest under 대상 없음.
// A2 complete (B16): kinds in order (조건 · 기준 · 근거 · 파일 · 대상 없음); a head with the target, "대화 N · 판정 N ·
// 점검 … · 변경 N" and 접기 ▾ / 펼치기 ▸; a condition's group starts with what is known now: the paper's value [p.N], the
// code the last audit found, requests to change it still waiting
function byTarget(log, rows) {
  // a message sits under its first target; each of its other targets gets a line that leads to it (QA 10/26: an audit
  // card about config.yaml, logs/2wiki.log and run.py showed under config.yaml only, the other two had no group)
  const groups = new Map(), also = new Map(), rest = [], add = (m, t, x) => { if (!m.has(t)) m.set(t, []); m.get(t).push(x); }, refOf = new Map();
  rows.forEach(r => { const x = r[0]; if (!(x.classList && x.classList.contains("msg"))) return rest.push(x);
    const ts = JSON.parse(x.dataset.targets || "[]"); let tr = {}; try { tr = JSON.parse(x.dataset.trefs || "{}"); } catch (e) {}
    Object.entries(tr).forEach(([k, ref]) => refOf.set(k, ref));
    add(groups, ts[0] || "대상 없음", r); ts.slice(1).forEach(t => add(also, t, x)); });
  also.forEach((_, t) => groups.has(t) || groups.set(t, []));
  const n = t => groups.get(t).length + (also.get(t) || []).length;
  const lead = (x, home) => h("p", { class: "muted", "data-also": home }, "↳ ", h("button", { class: "link", title: `'${home}' 묶음에서 보기`,
    on: () => { x.closest("details").open = true; x.scrollIntoView({ block: "center" }); } }, `${x.classList.contains("pablo") ? "Pablo" : "나"} · ${firstText(x).slice(0, 60)}`),
    h("small", null, ` — '${home}' 묶음에 있음`));
  const RANK = ["조건 · ", "기준 · ", "근거 · ", "파일 · "], rank = t => t === "대상 없음" ? 9 : (i => i < 0 ? 5 : i)(RANK.findIndex(p => t.startsWith(p)));
  const L = linksOf(V), chat = V.chat || [], audits = chat.filter(c => c.role === "audit"), la = audits[audits.length - 1];
  const itemOf = ref => la && [...(la.items || []), ...(la.outside || [])].find(x => x.id === ref || (ref.startsWith("file:") && placePaths(x.where).includes(ref.slice(5))));
  const facts = (t, ref) => { const k = (ref && L.get(ref)) || { chat: [], verdicts: [] }, vs = k.verdicts.filter(x => x.verdict !== "ALLOW");
    const it = ref && itemOf(ref), chg = ref && ref.startsWith("file:") ? chat.filter(c => c.role === "changes" && (c.files || []).some(f => (f.path || f) === ref.slice(5))).length : 0;
    return [`대화 ${n(t)}`, vs.length ? `판정 ${vs.length}${vs.some(x => x.verdict === "BLOCK") ? " (막음)" : ""}` : null,
      ref && ref.startsWith("SC") ? (it ? `점검 ${(AUDIT[it.status] || ["", it.status])[1]}` : "점검 아직") : null, chg ? `변경 ${chg}` : null].filter(Boolean).join(" · "); };
  const band = ref => { const k = ref && V.checks[ref]; if (!k || !k.spec || k.spec.missing) return null;
    const it = itemOf(ref), wait = V.actions.filter(a => a.verdict === "WARN" && !a.decision && (a.criteria || []).some(c => c.id === ref)).length;
    return h("p", { class: "tg-band", "data-cond-band": ref }, `논문 값 ${k.spec.value || clip(plain(k), 30)} `, pchip(k),
      it && it.where ? [` · 지금 코드 `, h("code", null, it.line_found ? `${where0(it.where)}:${it.line_found}` : it.where), it.found ? ` = ${clip(it.found, 40)}` : ""] : " · 점검 전",
      wait ? ` · 바꾸자는 요청 ${wait}건이 확인을 기다림` : ""); };
  [...groups.keys()].sort((a, b) => rank(a) - rank(b) || n(b) - n(a)).forEach((t, i) => {
    const rs = groups.get(t), more = (also.get(t) || []).map(x => lead(x, JSON.parse(x.dataset.targets)[0])), ref = refOf.get(t) || knownTargets().get(t) || null;
    log.append(h("details", { class: "targetgroup", "data-target": t, "data-ref": ref, open: i === 0 ? true : null },
      h("summary", null, h("span", { class: "tg" + (t === "대상 없음" ? "" : " tgt") }, t), h("small", null, facts(t, ref)), h("span", { class: "tog" })),
      band(ref), rs.map(r => r[0]), more)); });
  rest.forEach(x => log.append(x));
}
// D2 back-links. A ref is what a chat-log entry names: a criterion (C4; a held-back or unread line the user promoted
// counts as the criterion it became, V.intent.promoted), a check (SC5: a condition, a PDF answer, a table cell) with its
// anchors (E12) and their pages ("SRC1:p9"), a work-folder file ("file:config.yaml"), a plan step (P3.1).
// The audit's "where" ("config.yaml:5; run.py:10-11") -> the files (the same reading as where.js, without the lines)
function placePaths(raw) {
  return String(raw || "").split(/\s*;\s*|\s*,\s+(?=\S*(?:[\w-]\.[A-Za-z]|[\\/]))/).map(x => x.trim().replace(/^`+|`+$/g, "").trim()
    .replace(/\s+\((?!\s*(?:lines?|l\.)\s*\d)[^()]*\)$/i, "").replace(/#L?\d[\dLl\s,~–-]*$/, "")
    .replace(/[\s,(]+(?:lines?|l\.)\s*[\dLl\s,~–-]+\)?$/i, "").replace(/\s*[\d\s,~–-]+(?:행|번째\s*줄|줄)\)?$/, "")
    .replace(/:L?\d[\dL\s,~–-]*(?::\d+)?$/, "").replace(/^[`'"(]+|[`'"),:]+$/g, "").trim().replace(/\\/g, "/").replace(/^(\.\/)+/, ""))
    .filter(s => s && s.length <= 500 && !/^(?:-+|n\/?a|none|null|없음|해당\s*없음)$/i.test(s) && (!/\s/.test(s) || /\/|\.[A-Za-z0-9]{1,8}$/.test(s)));
}
function refsOf(c, v = V) {
  if (!c || !v) return [];
  const out = new Set(), add = x => { if (x) out.add(String(x)); }, promoted = (v.intent || {}).promoted || {};
  const check = id => { if (!id) return; add(id); const k = (v.checks || {})[id];
    ((k && k.evidence) || []).forEach(e => { add(e); const a = (M.anchors || {})[e]; if (a && a.page) add(a.source + ":p" + a.page); }); };
  const r = String(c.role || "");
  if (r === "intent") { (c.items || []).forEach(i => add(i.id)); [...(c.pending || []), ...(c.unread || [])].forEach(k => add(promoted[k.id])); }
  else if (r === "criterion-edit") add(c.id);
  else if (r === "spec") [...(c.checks || []), ...(c.missing || [])].forEach(check);
  else if (r === "ask" || r.startsWith("spec-")) check(c.check);
  else if (r === "audit") [...(c.items || []), ...(c.outside || [])].forEach(x => { add(x.id); placePaths(x.where).forEach(f => add("file:" + f)); });
  else if (r === "changes" || r === "undo") (c.files || []).forEach(f => add("file:" + (typeof f === "string" ? f : f.path)));
  else if (r === "compare") (c.cells || []).forEach(check);
  add(c.step);  // D4: the plan step a chat request / its reply was
  return [...out];
}
// an intent entry 1 ms after a user message is that message's turn (chatTurn logs them so): -> the user message's key
function turnsOf(v = V) {
  const chat = (v && v.chat) || [], users = new Map(chat.filter(x => x.role === "user").map(x => [Date.parse(x.at), "user@" + x.at])), t = new Map();
  chat.forEach(c => { if (c.role === "intent" && users.has(Date.parse(c.at) - 1)) t.set("intent@" + c.at, users.get(Date.parse(c.at) - 1)); });
  return t;
}
// every message key the conversation draws (role@time, act:ACT3) -> its refs; a user message also gets its turn's intent's
function refsByKey(v = V) {
  const m = new Map(), put = (k, xs) => { if (xs.length) m.set(k, [...new Set([...(m.get(k) || []), ...xs])]); }, turn = turnsOf(v);
  ((v && v.chat) || []).forEach(c => { const k = c.role + "@" + c.at, rs = refsOf(c, v); put(k, rs); if (turn.has(k)) put(turn.get(k), rs); });
  ((v && v.actions) || []).forEach(a => put("act:" + a.id, [...(a.criteria || []).map(x => x.id), a.step].filter(Boolean)));
  return m;
}
// ref -> {chat: [message keys, one per turn], verdicts: [{act, verdict, decision}]}: the "대화 N" / "판정 N" of a
// criterion, a condition, a page, a file, a plan step. Verdicts: the Guard's, by the criteria an action conflicted with
// (판정) and by its plan step
function linksOf(v = V) {
  const L = new Map(), get = r => { if (!L.has(r)) L.set(r, { chat: [], verdicts: [] }); return L.get(r); }, turn = turnsOf(v);
  ((v && v.chat) || []).forEach(c => { const k = c.role + "@" + c.at, key = turn.get(k) || k;
    refsOf(c, v).forEach(r => { const x = get(r); if (!x.chat.includes(key)) x.chat.push(key); }); });
  ((v && v.actions) || []).forEach(a => [...new Set([...(a.criteria || []).map(x => x.id), a.step].filter(Boolean))]
    .forEach(r => get(r).verdicts.push({ act: a.id, verdict: a.verdict, decision: a.decision || null })));
  return L;
}
// the drawn messages get data-refs (a JSON list) from their data-key; -> how many have some
function stampRefs(root = $("log"), v = V) {
  if (!root || !v) return 0;
  const by = refsByKey(v); let n = 0;
  root.querySelectorAll("[data-key]").forEach(el => { const rs = by.get(el.dataset.key);
    if (rs && rs.length) { el.dataset.refs = JSON.stringify(rs); n++; } else delete el.dataset.refs; });
  return n;
}
// "대화로 거르기": only the messages naming one of refs stay (the dividers above them too), as a stage filter does
// (.filtered, #filter-banner, #log[data-filter] = "refs:" + label); the same label again -> all. -> {kept, hid}
// A2 complete (F24): in 단계별 / 대상별 too (a group with nothing left goes, one with something opens); the banner says what
// kind of thing is kept ("이 기준과 이어진 대화만 보는 중 · 2개 · 다른 메시지 6개 숨김") with 거르기 ▾ (the menu) and 전체 보기;
// in 시간순 a run of hidden messages leaves one line "··· 숨긴 메시지 N개"
const refKind = r => /^[CK]\d+$/.test(r) ? ["기준", "과"] : /^SC\d+$/.test(r) ? (((V && V.checks[r]) || {}).spec ? ["조건", "과"] : ["근거", "와"])
  : /^E\d+$|:p\d+$/.test(r) ? ["근거", "와"] : /^file:/.test(r) ? ["파일", "과"] : /^P\d+/.test(r) ? ["계획 단계", "와"] : ["대상", "과"];
function filterUi(log) { const old = $("filter-banner"); if (old) old.remove(); log.querySelectorAll(".hidnote").forEach(x => x.remove());
  const m = $("filter-menu"); if (m) m.remove(); }
// groups of the 단계별 / 대상별 views follow the messages in them; a group with a kept message is opened
function filterGroups(log, on) {
  log.querySelectorAll(":scope > .stagegroup, :scope > .targetgroup").forEach(g => { const ms = g.querySelectorAll(".msg[data-key]");
    const left = [...ms].some(x => !x.classList.contains("filtered"));
    g.classList.toggle("filtered", !!on && ms.length > 0 && !left);
    if (on && left) { if (g.tagName === "DETAILS") g.open = true; const b = g.querySelector(".sg-msgs"); if (b) b.hidden = false; } });
}
function filterBy(refs, label) {
  const log = $("log"), want = new Set([].concat(refs || []).map(String)), tag = "refs:" + label;
  const on = log.dataset.filter === tag || !want.size ? "" : tag; log.dataset.filter = on;
  filterUi(log);
  let hid = 0, kept = 0;
  log.querySelectorAll(".msg[data-key]").forEach(x => { let rs = []; try { rs = JSON.parse(x.dataset.refs || "[]"); } catch (e) {}
    const hide = !!on && !rs.some(r => want.has(r)); x.classList.toggle("filtered", hide); if (hide) hid++; else kept++; });
  [...log.children].filter(x => x.classList.contains("divider")).forEach(dv => { let n = dv.nextElementSibling, any = false;
    for (; n && !n.classList.contains("divider"); n = n.nextElementSibling) if (n.matches(".msg[data-key]:not(.filtered)")) any = true;
    dv.classList.toggle("filtered", !!on && !any); });
  filterGroups(log, on);
  if (on) {
    let run = [];  // 시간순: one line where hidden messages were
    const flush = () => { if (run.length) run[0].before(h("div", { class: "hidnote", "data-hidden": String(run.length) },
      h("button", { class: "link", title: "전체 보기", on: () => filterBy(refs, label) }, `··· 숨긴 메시지 ${run.length}개`))); run = []; };
    [...log.children].forEach(x => { if (x.matches(".msg.filtered")) run.push(x); else if (x.matches(".msg[data-key], #live")) flush(); });
    flush();
    const [kind, j] = refKind([...want][0]);
    log.prepend(h("div", { id: "filter-banner", "data-refs": JSON.stringify([...want]), "data-label": label, title: label },
      h("span", { class: "fb-t" }, `이 ${kind}${j} 이어진 대화만 보는 중 · ${kept}개 · 다른 메시지 ${hid}개 숨김`),
      h("button", { class: "link", "data-filter-menu": "1", on: e => filterMenu(e.currentTarget) }, "거르기 ", ico("chevron-down", 12)),
      h("button", { class: "link", on: () => filterBy(refs, label) }, "전체 보기")));
  }
  document.querySelectorAll("#stages .stage.picked").forEach(x => x.classList.remove("picked"));
  if (gateHook) gateHook();
  return { kept, hid };
}
// F24 the 거르기 menu: what is being kept (✓), the targets the conversation names most (기준 · 근거 · 파일 · 조건, how many
// messages each), 거르기 풀기. The view bar's chip (A10) opens it the same way: filterMenu(anchor)
function filterMenu(anchor) {
  const old = $("filter-menu"); if (old) { old.remove(); return; }
  const log = $("log"), count = new Map(), refOf = new Map();
  log.querySelectorAll(".msg[data-trefs]").forEach(x => { let t = {}; try { t = JSON.parse(x.dataset.trefs); } catch (e) {}
    Object.entries(t).forEach(([k, r]) => { refOf.set(k, r); count.set(k, (count.get(k) || 0) + 1); }); });
  const cur = (log.dataset.filter || "").startsWith("refs:") ? log.dataset.filter.slice(5) : "", stage = cur ? "" : log.dataset.filter || "";
  const banner = $("filter-banner"), curRefs = banner && banner.dataset.refs ? JSON.parse(banner.dataset.refs) : [];
  const icon = t => t.startsWith("기준") ? "check-circle" : t.startsWith("파일") || t.startsWith("근거") ? "file" : "filter";
  const items = [...count.keys()].filter(k => k !== cur).sort((a, b) => count.get(b) - count.get(a)).slice(0, 7);
  const close = () => menu.remove();
  const item = (label, n, on, picked) => h("button", { class: "mi" + (picked ? " on" : ""), role: "menuitemradio", "aria-checked": String(!!picked), on: () => { close(); on(); } },
    ico(icon(label), 14), h("span", { class: "mi-t" }, label), n != null ? h("small", null, n) : null, picked ? ico("check", 14) : null);
  const menu = h("div", { id: "filter-menu", class: "fmenu", role: "menu" },
    cur ? item(cur, curRefs.length ? log.querySelectorAll(".msg[data-key]:not(.filtered)").length : null, () => filterBy(curRefs, cur), true) : null,
    stage ? item(`단계 · ${stage}`, null, () => stageFilter(stage), true) : null,
    items.map(k => item(k, count.get(k), () => { if (cur) filterBy(curRefs, cur); if (stage) stageFilter(stage); filterBy([refOf.get(k)], k); })),
    !items.length && !cur && !stage ? h("p", { class: "muted mi-none" }, "거를 대상이 아직 없습니다.") : null,
    cur || stage ? h("button", { class: "mi", "data-filter-off": "1", on: () => { close(); cur ? filterBy(curRefs, cur) : stageFilter(stage); } }, h("span", { class: "mi-t" }, "거르기 풀기")) : null,
    h("p", { class: "mi-note" }, "기준 · 근거 · 파일의 '대화 N'이나 근거 탭의 '대화로 거르기'를 누르면 이렇게 거릅니다. 단계로 거르기는 단계 막대에서 합니다."));
  document.body.append(menu);
  const r = (anchor || log).getBoundingClientRect();
  menu.style.top = Math.round(r.bottom + 6) + "px"; menu.style.left = Math.round(Math.max(8, Math.min(r.right - 320, innerWidth - 328))) + "px";
  setTimeout(() => addEventListener("mousedown", function off(e) { if (!e.target.closest("#filter-menu")) { menu.remove(); removeEventListener("mousedown", off, true); } }, true));
}
let gateHook = null;  // desktop: the composer says when its stage is the one filtered (B14)
// a stage in the stage bar: only that stage's messages (and its dividers) stay; again -> all. In 단계별 / 대상별 too
function stageFilter(label) {
  const log = $("log"), on = log.dataset.filter === label ? "" : label; log.dataset.filter = on;
  filterUi(log);
  let hid = 0, kept = 0;
  log.querySelectorAll(".msg[data-stage]").forEach(x => { const hide = !!on && x.dataset.stage !== on; x.classList.toggle("filtered", hide); hide ? hid++ : kept++; });
  [...log.children].forEach(x => { if (x.classList.contains("divider")) x.classList.toggle("filtered", !!on && x.dataset.stage !== on); });
  filterGroups(log, on);
  if (on) log.prepend(h("div", { id: "filter-banner", "data-stage": on }, h("span", { class: "fb-t" }, `${on} 단계 대화만 보는 중 · ${kept}개 · 다른 단계 ${hid}개 숨김`),
    h("button", { class: "link", on: () => stageFilter(on) }, "전체 보기")));
  document.querySelectorAll("#stages .stage").forEach(x => x.classList.toggle("picked", !!on && x.querySelector("b").textContent === on));
  if (gateHook) gateHook();
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
    const w = x.querySelector && x.querySelector(":scope > div > .who small"); if (w && t) w.textContent = time(t);  // B1
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
    h("p", { class: "head" }, "결정이 필요합니다"), h("p", { class: "muted" }, "정하기 전에는 기준으로 쓰지 않습니다."),
    V.intent.questions.map(q => /^K\d+$/.test(q.id) ? held(q, V.task.id, true) : h("p", { title: q.id, "data-id": q.id }, rich(q.text))),
    h("p", null, h("button", { class: "link", on: () => show({ mode: "intent" }) }, "작업 기준 보기")))));
  log.append(live());
  finish();
  stampRefs(log);  // D2: data-refs from each message's data-key
  log.scrollTop = chat.length ? log.scrollHeight : 0;  // a conversation reopens at its latest message
}
// every plan step done -> one closing message (in the live part, so a refresh can add it too)
function finish() {
  if (!V.plan || !V.plan.steps.length || V.plan.steps.some(st => stepState(st)[0] !== "done") || $("log").querySelector(".finish")) return;
  const rep = document.querySelector("#reports .link");  // S53: what can come next
  live().append(h("div", { class: "finish" }, msg("Pablo", null, h("div", { class: "done-card" }, art("confident", "pose"),
    h("div", null, h("p", { class: "ttl" }, "작업을 마쳤습니다."), h("p", { class: "muted" }, `계획 ${V.plan.steps.length}단계를 모두 마쳤습니다. 보고서를 내보내거나 완료로 옮길 수 있습니다.`),
      rep ? h("p", null, h("button", { class: "pill on", "data-finish-report": "1", on: () => { const r = document.querySelector("#reports .link"); if (r) r.click(); } },
        ico("file", 14), "보고서 내보내기")) : null)))));
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
  const rs = refsByKey(V).get(key); if (rs) el.dataset.refs = JSON.stringify(rs);  // D2
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
// M5.1: no task yet -> an empty Pablo screen; the desktop makes tasks in the app (+ 새 작업). A2 complete (A11): two
// steps, 1 the ChatGPT account (read from #acct's data-state, so it follows sign-in as it happens), 2 a new task
function empty() {
  const log = $("log"); log.textContent = ""; document.title = "Pablo";
  const app = !!(window.pabloHost && pabloHost.newTask), ac = $("acct"), st = ac ? ac.dataset.state : null, on = st === "connected";
  const wait = st === "signing_in" ? "브라우저에서 승인을 기다리는 중…" : st === "verifying" ? "플랜 사용 권한을 확인하는 중…" : null;
  const step1 = ac ? h("div", { class: "fr-step" + (on ? " done" : ""), "data-step": "account" },
    h("b", null, on ? [ico("check", 14), " ChatGPT 계정 연결됨"] : "1. ChatGPT 계정 연결"),
    on ? null : wait ? h("span", { class: "fr-wait" }, h("span", { class: "spin", "aria-hidden": "true" }), wait)
      : h("button", { class: "pill on", "data-signin": "1", on: () => pabloHost.login() }, "ChatGPT로 연결")) : null;
  const step2 = app ? h("div", { class: "fr-step" + (ac && !on ? " later" : ""), "data-step": "task" }, h("b", null, (ac ? "2. " : "") + "새 작업 만들기"),
    h("button", { class: "pill on", "data-first-task": "1", on: () => newTask() }, ico("plus", 14), "새 작업")) : null;
  const err = ac && !on && ac.dataset.error ? h("p", { class: "fr-note bad" }, "연결하지 못했습니다 · " + ac.dataset.error) : null;
  log.append(h("div", { class: "empty" }, art("default"), h("b", null, "무엇을 해볼까요?"),
    h("p", null, app ? "논문을 재현하고 점검하거나, 논문에 근거를 묻거나, 작업 폴더에서 에이전트와 일합니다." : "새 작업을 만들어 시작하세요."),
    app ? h("div", { class: "fr-card" }, step1, step2, err || (ac ? h("p", { class: "fr-note" }, "연결은 시스템 브라우저에서 승인합니다. 연결 중 · 실패 · 플랜 확인 결과도 이 자리에 보입니다.") : null)) : null));
}
let tools = () => {}, newTask = () => {}, refresh = () => Promise.resolve();  // desktop only (M5.1): task tools, new task form, live state
let reportDlg = null, openWork = null, openSettings = null, cardClose = () => {};  // A2 complete · A (desktop): the export dialog, the task's folder, 설정, the chips' card

// ---- one context panel: source | intent | plan | trace ---------------------------------------------------------
function toggle(st) { (hi >= 0 && document.body.classList.contains("panel") && hist[hi].mode === st.mode && !st.e && !st.act) ? close() : show(st); }
function show(st, push = true) {
  if (push) { hist = hist.slice(0, hi + 1); hist.push(st); hi = hist.length - 1; }
  if (["source", "code", "paper", "matrix"].includes(st.mode)) lastEv = st;
  document.body.classList.add("panel"); document.body.classList.remove("pdf", "code", "wide");
  CSS.highlights.clear();
  document.querySelectorAll(".cite").forEach(b => b.classList.toggle("on", st.mode === "source" && b.dataset.e === st.e));
  const p = $("panel"); p.textContent = ""; delete p.dataset.live; delete p.dataset.still; p.dataset.mode = st.mode;
  ({ source, intent, plan, trace, code: codeView, matrix: matrixView, paper, evhome })[st.mode](p, st);
  header(); rememberPanel();
}
function close() {
  document.body.classList.remove("panel", "pdf", "code", "wide"); CSS.highlights.clear(); hist = []; hi = -1;
  document.querySelectorAll(".cite.on").forEach(b => b.classList.remove("on"));
  if (V) { header(); rememberPanel(); }
}
const go = d => { if (hist[hi + d]) { hi += d; show(hist[hi], false); } };
// A2: back / forward and page turns are line icons; C2: the head is the panel's name and "접기 ›" (the panel folds into the
// rail). In a narrow window the panel is an overlay and the same button reads "닫기 ×" (both words are there, CSS picks).
const turned = (name, deg, size) => { const s = ico(name, size); s.style.transform = `rotate(${deg}deg)`; return s; };
const xbtn = (label = "접기", on = close) => h("button", { class: "x fold", title: label === "접기" ? "접기 (오른쪽 레일로)" : label, on },
  h("span", { class: "w" }, label, ico("chevron-right", 12)), h("span", { class: "n" }, "닫기", ico("x", 12)));
const navs = () => [h("button", { class: "nav", title: "뒤로", disabled: hi <= 0, on: () => go(-1) }, turned("arrow-up", -90)),
  h("button", { class: "nav", title: "앞으로", disabled: hi >= hist.length - 1, on: () => go(1) }, turned("arrow-up", 90))];
// .url keeps its emoji in textContent (tests read "📄 TinyRAG · PDF"); on screen the line icon stands for it
const urlIco = (name, emoji) => [ico(name, 14), h("span", { class: "em" }, emoji)];
// demo 10/27: the right column's width is the person's: drag its left edge (#pgrip), or 넓게 보기 in a panel's head
// (a PDF, the code) to about 60% of the window and back. Kept on this PC (localStorage), within what leaves the chat room
let widen = null;
(() => {
  const R = $("right"); if (!R) return;
  const KEY = "pablo.pw", MIN = 320, max = () => Math.max(MIN, innerWidth - 640);
  const set = (w, keep) => { w = Math.round(Math.min(max(), Math.max(MIN, w))); document.body.style.setProperty("--pw", w + "px");
    if (keep) try { localStorage.setItem(KEY, String(w)); } catch (e) {} };
  try { const w = +localStorage.getItem(KEY); if (w) set(w); } catch (e) {}
  const g = R.appendChild(h("div", { id: "pgrip", title: "끌어서 폭 바꾸기 · 두 번 누르면 넓게 / 원래대로", role: "separator", "aria-orientation": "vertical" }));
  g.addEventListener("pointerdown", e => { e.preventDefault(); g.setPointerCapture(e.pointerId); g.classList.add("on"); document.body.classList.add("dragging");
    const right = R.getBoundingClientRect().right, mv = ev => set(right - ev.clientX);
    const up = ev => { g.classList.remove("on"); document.body.classList.remove("dragging"); g.removeEventListener("pointermove", mv); g.removeEventListener("pointerup", up); set(right - ev.clientX, true); };
    g.addEventListener("pointermove", mv); g.addEventListener("pointerup", up); });
  widen = () => { const wide = R.getBoundingClientRect().width < innerWidth * 0.45; set(wide ? innerWidth * 0.6 : 390, true); return wide; };
  g.addEventListener("dblclick", () => widen());
})();
const wbtn = () => widen ? h("button", { class: "widen", "data-widen": "1", title: "오른쪽 칸 넓게 / 원래대로", on: e => {
  e.currentTarget.textContent = widen() ? "↔ 원래대로" : "↔ 넓게 보기"; } }, $("right") && $("right").getBoundingClientRect().width >= innerWidth * 0.45 ? "↔ 원래대로" : "↔ 넓게 보기") : null;
const phead = (title, x = xbtn()) => h("div", { class: "phead" }, h("h2", { title }, title), wbtn(), x);
const simple = (p, title, body) => p.append(phead(title), h("div", { id: "pbody" }, body));  // append(null) prints "null": never pass one
const pcard = (attrs, title, text, ...more) => h("div", { class: "pcard", ...attrs }, h("b", null, title), text ? h("p", null, text) : null, ...more);

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
  const ks = a.verdict === "BLOCK" || (a.verdict === "WARN" && !a.decision) ? a.criteria.map(x => v.checks[x.id]).filter(k => k && k.spec && !k.spec.missing && k.state !== "waived" && !devOf(k)) : [];
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
// ④ (desktop) a criterion's own buttons, shown on hover: ⇄ the other strength, ✎ its sentence (S56: the same strength and
// reach, the old sentence kept struck through), 🗑 지우기 with a why asked in place (S57: required for a reproduction default)
function edits(x, kind) {
  if (!kind || !window.pabloHost || !pabloHost.criterion || !/^[A-Z]\d+$/.test(x.id) || /^[TK]\d+$/.test(x.id)) return null;  // not the task itself
  const box = h("span", { class: "edits" }), task = V.task.id;
  const run = (action, reason) => pabloHost.criterion(task, x.id, action, reason).then(text => {
    echo(task, { role: "criterion-edit", action, text, reason: action === "drop" ? (reason || "").trim() : "", ...(action === "edit" ? { prev: x.text } : {}) });
    return refresh(); }, e => box.replaceChildren(h("span", { class: "muted" }, " " + fail(e))));
  const back = () => box.replaceWith(edits(x, kind));
  const keys = (inp, ok) => inp.addEventListener("keydown", e => { if (e.isComposing) return;
    if (e.key === "Enter") ok(); if (e.key === "Escape") { e.stopPropagation(); back(); } });
  const ask = () => { const why = h("input", { class: "why", "data-why": x.id, placeholder: x.repro ? "재현 기본 기준입니다. 지우는 이유 (필수)"
      : x.all ? "모든 작업에서 지워집니다. 왜? (선택)" : "왜 지우나요? (선택)" });
    const ok = () => x.repro && !why.value.trim() ? (why.classList.add("need"), why.focus()) : run("drop", why.value);
    keys(why, ok);
    box.replaceChildren(why, h("span", { class: "ebtns" }, h("button", { class: "link soft", "data-drop-ok": x.id, on: ok }, "지우기"),
      h("button", { class: "link", on: back }, "취소"), x.repro ? h("small", null, "이유를 적어야 지울 수 있습니다") : null));
    why.focus(); };
  const edit = () => { const inp = h("input", { class: "why", "data-edit-in": x.id, maxlength: 500, value: x.text });
    const ok = () => { const t = inp.value.trim(); return !t || t === x.text ? back() : run("edit", t); };
    keys(inp, ok);
    box.replaceChildren(inp, h("span", { class: "ebtns" }, h("button", { class: "link dark", "data-edit-ok": x.id, on: ok }, "저장"),
      h("button", { class: "link", on: back }, "취소"), h("small", null, "Esc 취소")));
    inp.focus(); inp.select(); };
  const two = kind === "must" || kind === "prefer";
  box.append(kind === "must" ? h("button", { class: "link", "data-to": "soft", title: "가능하면으로 바꾸기", on: () => run("soft") }, ico("swap", 12), "가능하면으로")
      : kind === "prefer" ? h("button", { class: "link", "data-to": "hard", title: "반드시로 바꾸기", on: () => run("hard") }, ico("swap", 12), "반드시로") : null,
    two ? h("button", { class: "link ib", "data-edit": x.id, title: "문장 고치기", "aria-label": "문장 고치기", on: edit }, ico("pencil", 13)) : null,
    h("button", { class: "link ib", "data-drop": x.id, title: "지우기", "aria-label": "지우기", on: ask }, ico("trash", 13)));
  return box;
}
// C3–C7: 현재 작업 기준. The goal as words; 반드시 / 가능하면 with their counts, each row with its back-links (대화 N ·
// 판정 N) and its buttons on hover; a row picked keeps only its conversation. The paper's conditions as a count per kind
// (the whole list behind 조건 보기), the intended differences on their own, then what was taken out or removed (되살리기).
const condOpen = {};  // task -> 조건 보기 open (kept across redraws of the panel)
function intent(p) {
  const I = V.intent, task = V.task.id, L = linksOf(V), hostOk = !!window.pabloHost;
  const d = (M.desk || {})[task] || {}, papers = d.papers || [], main = papers.find(x => x.primary), canEdit = hostOk && pabloHost.condition;
  const editOf = x => (V.chat || []).filter(c => c.role === "criterion-edit" && c.action === "edit" && c.text === x.text).at(-1);
  const crow = (x, kind) => { const ed = editOf(x), old = x.prev || (ed && ed.prev), label = "기준 · " + shortText(x.text);
    const li = h("li", { title: x.id, "data-id": x.id, class: picked(label) ? "sel" : null },
      h("div", { class: "ct" }, x.text, x.all && kind ? h("small", { class: "all", "data-all": "1", title: "이 기준은 모든 작업에 걸립니다. 바꾸면 다른 작업에도 바뀝니다." }, " 모든 작업") : null),
      old && old !== x.text ? h("div", { class: "prev" }, h("s", null, old)) : null,
      h("div", { class: "meta" }, ed ? h("span", { class: "human", "data-edited": "1" }, "사람이 고침") : null, backChips(backOf(x.id, L))),
      edits(x, kind));
    li.addEventListener("click", e => { if (!e.target.closest("button, a, input, select, textarea, .edits")) pickRows(li, [x.id], label); });
    return li; };
  const head = (t, n, ...more) => h("h3", null, t, n != null ? h("small", { class: "n" }, String(n)) : null, ...more);
  const sec = (t, cls, xs, kind, always) => xs.length || always ? [head(t, xs.length), xs.length ? h("ul", { class: "ck " + cls }, xs.map(x => crow(x, kind))) : null] : null;
  const goals = I.goals.length ? [h("h3", null, "목표"), I.goals.map(x => h("div", { class: "goal", title: x.id, "data-id": x.id }, x.text, edits(x, "goal")))] : null;
  const none = !I.must.length && !I.prefer.length;
  // S11: no criterion yet -> how one comes, and a line to write one here
  const addCrit = () => { if (!hostOk || !pabloHost.makeCriterion) return null;
    const inp = h("input", { class: "addcrit", "data-add-crit": "1", maxlength: 1000, placeholder: "+ 기준 더하기" }), note = h("small", { class: "muted" });
    const add = st => { const t = inp.value.trim(); if (!t) return inp.focus();
      pabloHost.makeCriterion(task, t, st).then(items => { if (!items.length) return note.replaceChildren("이미 같은 기준이 있습니다.");
        echo(task, { role: "intent", items }); return refresh(); }, e => note.replaceChildren(fail(e))); };
    inp.addEventListener("keydown", e => { if (e.key === "Enter" && !e.isComposing) add("hard"); });
    return h("div", { class: "addrow" }, inp, h("button", { class: "link", "data-add-crit-as": "hard", on: () => add("hard") }, "반드시"),
      h("button", { class: "link", "data-add-crit-as": "soft", on: () => add("soft") }, "가능하면"), note); };
  const s11 = none ? pcard({ "data-no-criteria": "1" }, "아직 이 작업의 기준이 없습니다",
    "대화에 \"절대 · 항상 · 가능하면\"으로 적으면 기준이 됩니다. 여기에 바로 적어도 됩니다.", addCrit()) : null;
  // the paper's conditions
  const all = V.research.map(id => V.checks[id]).filter(c => c && c.spec);
  const spec = all.filter(c => !c.spec.missing && c.state !== "waived");
  const open = all.filter(c => c.spec.missing && c.state !== "waived");
  const out = all.filter(c => c.state === "waived" && c.waived_by === "user");  // ⑩ taken out by the user, with why, restorable
  const pick = canEdit && main && (M.papers || {})[main.id] ? h("p", { class: "muted" }, h("button", { class: "link", "data-open-paper": main.id,
    on: () => show({ mode: "paper", src: main.id }) }, ico("file", 14), ` ${main.title} 열기`), " · 빠진 조건은 문장을 골라 더합니다.") : null;
  const code = main ? codeLine(main.id, task) : null;
  const row = c => h("li", { title: c.id, "data-id": c.id }, fact(c),
    c.spec.by === "user" ? h("small", { class: "muted", "data-by-user": "1" }, " 직접 더함") : null,
    ASIDE[c.spec.kind] ? h("small", { class: "muted", "data-aside": c.spec.kind }, c.spec.kind === "fact" ? " 서술 · 점검 안 함" : " 실험 범위 · 점검 안 함") : null,
    devOf(c) ? h("div", { class: "chk dev", "data-dev": c.id }, `◇ 의도한 차이(${WHERE_DEV[scopeOf(devOf(c))]}): ${devOf(c).why}`) : null,
    canEdit ? h("span", { class: "acts" }, differ(c), devOf(c) ? null : [" ·", takeOut(c)]) : null);  // A2: one group, shown on hover
  const kinds = [...Object.keys(SPEC), ...new Set(spec.map(c => c.spec.category).filter(k => !SPEC[k]))];  // grouped by kind, as in the card
  const shown = !!condOpen[task];
  const list = h("div", { class: "condlist", "data-cond-list": "1", hidden: !shown }, kinds.flatMap(k => { const xs = spec.filter(c => c.spec.category === k);
    return xs.length ? [h("h4", { class: "kind", "data-kind": k }, SPEC[k] || k), h("ul", { class: "ck must" }, xs.map(row))] : []; }),
    open.length ? [h("h4", { class: "kopen" }, "논문에 없는 설정"), h("ul", { class: "ck q" }, open.map(c => h("li", { title: c.id, "data-id": c.id }, rich(c.title))))] : null);
  const toggleList = k => { condOpen[task] = k ? true : !condOpen[task]; list.hidden = !condOpen[task];
    tgl.textContent = condOpen[task] ? "조건 접기" : "조건 보기";
    if (k) { const x = list.querySelector(`h4[data-kind="${CSS.escape(k)}"]`); if (x) x.scrollIntoView({ block: "start" }); } };
  const tgl = h("button", { class: "link", "data-cond-toggle": "1", on: () => toggleList() }, shown ? "조건 접기" : "조건 보기");
  const redo = $("specs") && $("specs").querySelector("button");
  const paperName = (main && main.title) || (spec.find(c => c.paper) || {}).paper;
  const conds = spec.length || open.length ? [head("논문 조건", spec.length, paperName ? h("small", { class: "paper" }, "· " + paperName) : null),
    h("div", { class: "cond", "data-conds": String(spec.length) },
      h("div", { class: "nums" }, kinds.map(k => { const n = spec.filter(c => c.spec.category === k).length;
        return n ? h("button", { class: "cnum", "data-cnum": k, title: `${SPEC[k] || k} 조건 보기`, on: () => toggleList(k) }, h("b", null, String(n)), h("small", null, SPEC[k] || k)) : null; })),
      open.length ? h("p", { class: "open", "data-open-settings": String(open.length) }, `논문에 없는 설정 ${open.length}개는 아직 정하지 않았습니다`) : null,
      h("div", { class: "links" }, tgl, redo ? h("button", { class: "link", "data-cond-redo": "1", title: "주 논문에서 재현 조건을 다시 뽑습니다(먼저 무엇이 바뀌는지 묻습니다)", on: () => redo.click() }, "다시 뽑기") : null),
      list), pick, code] : pick || code ? [pick, code] : null;
  // C7: a task without papers works by its criteria only; + 자료 추가 opens the source box (the shell's)
  const noPaper = !papers.length && !spec.length && !open.length ? pcard({ "data-no-paper": "1" }, "논문이 없는 작업입니다",
    "논문 조건 대신 기준만 씁니다. 근거가 필요하면 자료를 더할 수 있습니다.",
    $("adder") ? h("button", { class: "link", "data-add-source": "1", on: () => { const a = $("adder"); a.hidden = false; const i = $("arxiv"); if (i) i.focus(); } }, "+ 자료 추가") : null) : null;
  // C5: the intended differences on their own
  const devs = spec.filter(c => devOf(c));
  const devSec = devs.length ? [head("의도한 차이", devs.length), h("ul", { class: "ck dev" }, devs.map(c => { const dv = devOf(c), label = "조건 · " + shortText(c.conclusion || c.title);
    const li = h("li", { title: c.id, "data-deviation": c.id, class: picked(label) ? "sel" : null },
      h("div", { class: "ct" }, rich((c.conclusion || c.title).replace(/\s*\[\d+\]/g, "")), ` · 범위: ${WHERE_DEV[scopeOf(dv)]}`),
      h("div", { class: "meta" }, h("small", { class: "muted" }, `이유: ${dv.why}`), backChips(backOf(c.id, L))),
      canEdit ? h("span", { class: "acts" }, differ(c)) : null);
    li.addEventListener("click", e => { if (!e.target.closest("button, a, input, select, textarea, .acts")) pickRows(li, [c.id], label); });
    return li; }))] : null;
  const outEl = out.length ? h("details", { class: "gone", "data-spec-out": String(out.length) }, h("summary", null, ico("chevron-right", 12), `뺀 조건 ${out.length}개`),
    h("ul", { class: "ck" }, out.map(c => h("li", { title: c.id, "data-id": c.id }, h("s", null, (SPEC[c.spec.category] || c.spec.category) + " · " + (c.conclusion || c.title).replace(/\s*\[\d+\]/g, "")),
      h("div", { class: "muted" }, `${day(((c.spec.dropped || []).at(-1) || {}).from)} 뺌 · 이유: ${c.waive_reason}`, canEdit ? [" · ", putBack(c)] : null))))) : null;
  // ④ removed criteria stay in view: when, why, and 되살리기 (the same criterion back, as strong as it was)
  const gone = (I.removed || []).filter(x => !x.to), back = x => { const at = h("span");
    return [at, h("button", { class: "link", "data-restore": x.id, on: () => pabloHost.criterion(task, x.id, "restore").then(text => {
      echo(task, { role: "criterion-edit", action: "restore", text }); return refresh(); },
      e => at.replaceChildren(h("span", { class: "muted" }, fail(e) + " "))) }, "되살리기")]; };
  const removed = gone.length ? h("details", { class: "gone", "data-removed": String(gone.length) }, h("summary", null, ico("chevron-right", 12), `지운 기준 ${gone.length}개`),
    h("ul", { class: "ck" }, gone.map(x => h("li", { title: x.id, "data-id": x.id }, h("s", null, x.text), x.all ? h("small", { class: "all", title: "되살리면 모든 작업에 다시 걸립니다." }, " 모든 작업") : null,
      h("div", { class: "muted" }, `${day(x.from)} 지움 · `, x.why ? `이유: ${x.why}` : "이유를 적지 않음",
        hostOk && pabloHost.criterion ? [" · ", back(x)] : null))))) : null;
  const how = hostOk && pabloHost.criterion ? h("p", { class: "muted", "data-how": "1" },
    "행에 마우스를 올리면 세기 바꾸기 · 고치기 · 지우기가 나옵니다. 행을 누르면 그 기준을 가리킨 대화만 남습니다. 새 기준은 대화에 적어도 됩니다.") : null;
  simple(p, "현재 작업 기준", [goals, none ? s11 : [sec("반드시 지킬 것", "must", I.must, "must", true), sec("가능하면", "", I.prefer, "prefer", true)],
    noPaper, conds, devSec, sec("성공 조건", "q", I.success, "other"), sec("결정", "", I.decisions, "other"), sec("확인 필요", "q", I.questions),
    outEl, removed, how]);
}
function stepState(st) {
  const rs = V.actions.filter(a => a.step === st.id).flatMap(a => a.runs).map(r => r.step_status);
  return rs.includes("completed") ? ["done", "✓"] : rs.includes("partial") ? ["doing", "●"] : ["todo", "○"];
}
// C8: 계획 · N단계 중 k. One row per plan step of the task (one plan per message), its conversation, ✓ done, ● now (the one
// waiting, else the newest), the current plan's certainty, [n] and 왜?; a row picked keeps only its conversation
function plan(p) {
  const P = planRows(), L = linksOf(V), w = waitingAct();
  const detail = id => V.plan && V.plan.steps.find(s => s.id === id);
  const rows = h("ol", { class: "steps prow" }, P.rows.map(r => {
    const [cls] = stepState(r), now = !!P.cur && r.id === P.cur.id, st = detail(r.id), b = backOf(r.id, L), wait = !!w && w.step === r.id;
    const label = `${r.id} ${shortText(r.action, 20)}`;
    const ev = st ? st.checks.flatMap(id => (V.checks[id] || {}).evidence || []) : [];
    const sure = st ? (st.checks.length ? (st.checks.every(id => (V.checks[id] || {}).outcome === "VERIFIED") ? "공식 근거 확인" : "일부 추정") : "작업 기준에 따름") : null;
    const li = h("li", { class: [cls, now ? "cur" : "", r.old ? "old" : "", picked(label) ? "sel" : ""].filter(Boolean).join(" "), "data-id": r.id },
      h("div", { class: "pr" }, h("span", { class: "pid" }, r.id), h("span", { class: "pa" }, rich(r.action)),
        cls === "done" ? h("span", { class: "mk", title: "끝남" }, ico("check", 13)) : now ? h("span", { class: "mk now", title: "지금" }) : null),
      h("div", { class: "sub" }, h("b", null, `대화 ${b.chat}`), wait ? " · 확인 기다림" : "",
        st ? [" · ", sure, ev.length ? " " : "", ev.map(e => cite(e)), " · ", h("button", { class: "link", on: () => show({ mode: "trace", step: r.id }) }, "왜?")] : null));
    li.addEventListener("click", e => { if (!e.target.closest("button, a")) pickRows(li, [r.id], label); });
    return li; }));
  const more = V.plan && V.plan.unverified.length ? [h("h3", null, "확인되지 않은 부분"),
    h("ul", { class: "ck" }, V.plan.unverified.map(id => h("li", { title: id },
      rich((V.plan.steps.find(s => s.id === id) || { action: id }).action))))] : null;
  simple(p, P.rows.length ? `계획 · ${P.rows.length}단계 중 ${P.k}` : "계획", P.rows.length ? [rows,
    h("p", { class: "muted", "data-plan-how": "1" }, "계획 단계는 대화의 갈래 이름이기도 합니다. 누르면 그 단계의 대화만 남습니다."), more]
    : pcard({ "data-no-plan": "1" }, "아직 계획이 없습니다", "에이전트가 계획을 세우면 단계가 여기에 쌓입니다."));
}
// C9: 왜? — the way one action was judged, top to bottom: the request that led to it, the criteria, the evidence (with what
// the research corrected), the plan step, the action, Pablo's verdict, the user's decision (grey while waiting), the result.
// The tab opens on the action waiting for the user, else the newest; a filled dot marks where it stands now.
function trace(p, st) {
  const L = linksOf(V), I = V.intent;
  const act = st.act ? V.actions.find(a => a.id === st.act) : !st.step ? waitingAct() || V.actions.at(-1) || null : null;
  const stepId = act ? act.step : st.step, step = V.plan && V.plan.steps.find(s => s.id === stepId);
  const row = stepId && planRows().rows.find(r => r.id === stepId);
  const scoped = act || step || row;
  const checks = [...new Set(scoped ? [...(step ? step.checks : []), ...(act ? act.criteria.map(c => c.id) : [])].filter(id => V.checks[id])
    : V.research.filter(id => !V.checks[id].matrix))].sort((x, y) => V.checks[y].evidence.length - V.checks[x].evidence.length);
  const crit = scoped ? [...(step ? step.intent : []), ...(act ? act.criteria.filter(c => !V.checks[c.id]) : [])] : I.must;
  const li = (cls, k, ...v) => h("li", { class: cls }, h("div", { class: "k" }, k), h("div", { class: "v" }, v));
  const strength = x => I.must.some(y => y.id === x.id) ? " (반드시)" : I.prefer.some(y => y.id === x.id) ? " (가능하면)" : "";
  const said = (V.chat || []).filter(c => c.role === "user" && (stepId && c.step ? c.step === stepId : !act || !act.at || c.at <= act.at)).at(-1);
  const nodes = [li("", "사용자 요청", `"${said ? said.text : V.task.text}"`)];
  const seen = new Set(), crits = crit.filter(x => !seen.has(x.id) && seen.add(x.id));
  if (crits.length) nodes.push(li("", "적용된 기준", crits.map(x => h("div", { title: x.id }, rich(x.text), strength(x)))));
  for (const id of checks) { const c = V.checks[id];
    c.evidence.forEach(e => { const a = M.anchors[e], src = a && M.sources[a.source]; if (!src) return;
      const n = li("ev", ["근거 ", cite(e)], h("div", null, src.kind === "pdf" ? `${src.title} p.${a.page}` : host(src.url).split("/")[0] + " · " + src.title), h("code", null, a.exact));
      n.querySelector(".v").addEventListener("click", () => show({ mode: "source", e })); nodes.push(n); });
    c.issues.forEach(i => nodes.push(li("warn", "조사 중 바로잡은 점", rich(i.note))));
    if (c.conclusion) nodes.push(li("", "조사 결론", rich(c.conclusion.split(/(?<=[.?!])\s+/)[0]))); }
  if (step || row) nodes.push(li("", "계획 단계", h("span", { class: "pid" }, stepId), " ", rich((step || row).action)));
  else if (!act && V.plan) nodes.push(li("", "현재 계획", V.plan.steps.map((s, i) => h("div", null, `${i + 1}. `, rich(s.action)))));
  let now = nodes.length - 1;
  if (act) {
    const G = { BLOCK: ["stop", "막음 — 작업 기준과 충돌해 막았습니다"], WARN: ["warn", "확인 필요 — 현재 기준과 충돌할 수 있습니다"], ALLOW: ["", "통과 — 기준과 충돌하지 않습니다"] }[act.verdict] || ["", act.verdict];
    nodes.push(li("", "제안된 작업", meaning(act.text), preview(act.text), tech(act.text, ...act.problems.filter(x => !korean(x)))));
    const waiting = act.verdict === "WARN" && !act.decision; if (waiting) now = nodes.length - 1;
    nodes.push(li(G[0], "Guard 판정", G[1], act.problems.map(x => korean(x) ? h("div", null, "· ", rich(x)) : null)));
    if (act.verdict === "BLOCK") now = nodes.length - 1;
    nodes.push(li(act.decision ? "" : "wait", "사용자 결정", act.decision ? decided(act) || DECIDE[act.decision] : waiting ? "기다리는 중" : "—"));
    if (act.decision && act.verdict !== "BLOCK") now = nodes.length - 1;
    nodes.push(act.runs.length ? li("", "결과 · 검토", act.runs.map(r => h("div", null, done(r), r.alignment ? ` · ${ALIGN[r.alignment] || r.alignment}` : "")))
      : li("wait", "결과 · 검토", "—"));
    if (act.runs.length) now = nodes.length - 1;
  }
  if (nodes[now]) nodes[now].classList.add("now");
  let band = null;
  if (act) { const ids = act.criteria.map(c => c.id), refs = [act.step, ...ids].filter(Boolean);
    const from = Math.max(act.step ? backOf(act.step, L).chat : 0, said ? 1 : 0), same = backOf(ids, L).verdicts.length;
    band = backBand(`이 판단이 나온 대화 ${from} · 같은 기준의 판정 ${same}`, refs, "왜? · " + shortText(meaning(act.text), 20), refs.length && (from || same)); }
  // S68: nothing judged yet; what the research settled stays below it
  if (!act && !step && !row) return simple(p, "이 판단의 과정", [pcard({ "data-no-verdict": "1" }, "아직 판단한 것이 없습니다",
      "에이전트가 파일을 바꾸거나 명령을 실행하려 하면 Pablo가 기준과 대조한 과정이 여기에 쌓입니다. 대화의 '왜?'를 누르면 그 판단으로 바로 옵니다."),
    nodes.length > 1 ? [h("h3", null, "조사로 정한 것"), h("ol", { class: "tl" }, nodes)] : null]);
  simple(p, act ? "이 판단의 과정" : "이 단계가 계획에 들어간 과정", [h("ol", { class: "tl" }, nodes), band]);
}

// C3 / F21: the comparison table, wide (835): what it is, 항목 바꾸기 (the columns, n / 8, 다시 채우기: the conversation's own
// 비교표 form runs it, the table now stays there), + 논문 추가 (the task's sources not in it), a column the papers share, the way
// back to the card. A cell's [n] opens that paper's page here; ← comes back with that cell marked.
function matrixView(p, st) {
  document.body.classList.add("wide");
  if (st.since) { const nx = (V.chat || []).filter(c => c.role === "compare" && c.at && c.at > st.since).at(-1); if (nx) { st.c = nx; delete st.since; delete st.err; } }
  const c = st.c, task = c.task || V.task.id, can = !!(window.pabloHost && pabloHost.compare && compareAgain);
  const cells = (c.cells || []).map(id => V.checks[id]).filter(Boolean), all = c.papers.length * c.columns.length;
  const cell = (q, col) => cells.find(k => k.matrix && k.matrix.source_id === q.id && k.matrix.column === col);
  const name = nameOf(M.tasks.find(t => t.id === task) || V.task);
  // 다시 채우기: the conversation's 비교표 form with these columns, started; its card shows the progress and the result
  const again = cs => {
    if (!cs.length || !can) return;
    const before = document.querySelectorAll("#log [data-compare-form]").length;
    compareAgain(task, cs.slice(0, 8));
    const forms = document.querySelectorAll("#log [data-compare-form]"), f = forms.length > before ? forms[forms.length - 1] : null, go = f && f.querySelector("#compare-go");
    if (!go) { st.err = "지금은 다시 채울 수 없습니다. 진행 중인 답이 끝난 뒤에 다시 해 주세요."; return show(st, false); }
    st.since = new Date().toISOString(); st.form = false; delete st.err; go.click();
    const watch = setInterval(() => {
      if (!st.since || !f.isConnected) return clearInterval(watch);
      const bad = f.querySelector(".call.block"); if (!bad) return;
      clearInterval(watch); delete st.since; st.err = bad.textContent.replace(/^⚠\s*/, "");
      if (hist[hi] === st) show(st, false); }, 500);
    show(st, false);
  };
  const inp = h("input", { class: "cols", "data-cols-in": "1", value: c.columns.join(", "), "aria-label": "비교할 항목" }), cnt = h("span", { class: "cnt", "data-cols-n": "1" });
  const cols = () => [...new Set(inp.value.split(/[,，\n]/).map(x => x.trim()).filter(Boolean))];
  const refill = h("button", { class: "pill on", "data-refill": "1", on: () => again(cols()) }, "다시 채우기");
  const count = () => { const n = cols().length; cnt.textContent = `${n} / 8`; cnt.classList.toggle("over", n > 8); refill.disabled = !n || n > 8; };
  inp.addEventListener("input", count); count();
  inp.addEventListener("keydown", e => { if (e.isComposing) return; if (e.key === "Enter") refill.click();
    if (e.key === "Escape") { e.stopPropagation(); st.form = false; show(st, false); } });
  const form = can && st.form ? h("div", { class: "colsform", "data-cols-form": "1" },
    h("div", { class: "row" }, h("b", null, "항목"), inp, cnt, refill, h("button", { class: "pill", on: () => { st.form = false; show(st, false); } }, "취소")),
    h("small", null, "쉼표로 나눕니다. 다시 채우면 논문을 한 편씩 다시 읽어 새 표를 만듭니다. 지금 표는 대화에 그대로 남습니다.")) : null;
  const inTable = new Set(c.papers.map(x => x.id)), others = (((M.desk || {})[task] || {}).papers || []).filter(x => !inTable.has(x.id));
  const add = can ? menuChip(h("button", { class: "pill", "data-add-paper-menu": "1", "aria-haspopup": "menu" }, ico("plus", 14), "논문 추가"),
    others.length ? others.map(x => h("button", { class: "mi", "data-add-paper": x.id, disabled: x.kind === "web" ? true : null,
        title: x.kind === "web" ? "웹 문서는 표의 행이 되지 않습니다" : "이 자료까지 넣어 표를 다시 채웁니다", on: () => again(c.columns) },
        ico(x.kind === "web" ? "globe" : "file", 14), h("span", null, x.title + (x.version ? " " + x.version : "")), h("small", null, x.kind === "web" ? "WEB" : "PDF")))
      : h("p", { class: "mi none" }, "표에 없는 자료가 없습니다."),
    "표에 없는 이 작업의 자료만 보입니다. 새 PDF는 자료 칩에서 추가합니다.", true) : null;
  const tool = h("div", { class: "mxtool" }, h("div", { class: "t" }, h("b", null, `논문 ${c.papers.length}편 × 항목 ${c.columns.length}`),
      h("small", null, `칸 ${all}개 중 ${cells.length}개는 논문에서 위치를 찾은 값입니다.` + (cells.length < all ? " 나머지는 찾지 못해 비웠습니다." : ""))),
    can ? h("button", { class: "pill" + (st.form ? " on" : ""), "data-cols-edit": "1", "aria-expanded": String(!!st.form), on: () => { st.form = !st.form; show(st, false); } },
      ico("swap", 14), "항목 바꾸기") : null, add);
  const both = can ? common(c, cell).filter(x => !c.columns.some(col => col.includes(x))).slice(0, 3) : [];
  const who = c.papers.length === 2 ? "두" : c.papers.length === 3 ? "세" : "모든";
  const sug = both.length ? h("div", { class: "mxsug", "data-common-wide": both.join("|") }, ico("sparkle", 14),
    h("span", null, `${who} 논문이 ${both.join(", ")}을(를) 함께 씁니다.`),
    both.map(x => h("button", { class: "link", "data-add-column-wide": x, on: () => compareAgain(task, [...c.columns, `${x} 결과`].slice(-8), c, `${x} 결과`) },
      ico("plus", 12), `"${x} 결과" 열 더하기`))) : null;
  const card = () => $("log").querySelector(`[data-matrix="${CSS.escape(c.matrix || "")}"]`);
  const foot = h("div", { class: "mxfoot" }, h("button", { class: "link", "data-to-card": "1", on: () => { const k = card(); if (!k) return;
      k.scrollIntoView({ block: "center", behavior: "smooth" }); k.classList.add("flash"); setTimeout(() => k.classList.remove("flash"), 1400); } }, "대화의 비교표로 가기"),
    c.at ? h("small", null, `이 표는 ${hm(c.at)} 대화의 비교표를 넓게 연 것입니다.`) : null);
  const table = matrix(c, true);
  if (st.cell) { const td = table.querySelector(`[data-cell="${CSS.escape(st.cell)}"]`); if (td) td.classList.add("picked"); }
  table.addEventListener("click", e => { const b = e.target.closest(".cite"), td = b && b.closest("td"); if (td) st.cell = td.dataset.cell; }, true);
  p.append(phead(`비교표 · ${name}`, xbtn("좁게", () => hi > 0 ? go(-1) : close())), h("div", { id: "pbody", class: "mx" }, tool, form,
    st.since ? h("div", { class: "band", "data-refilling": "1" }, h("span", null, "논문을 한 편씩 다시 읽어 새 표를 만드는 중입니다. 진행은 대화의 비교표 카드에 보이고, 끝나면 여기 새 표가 열립니다.")) : null,
    st.err ? h("div", { class: "band warn", "data-refill-error": "1" }, h("span", null, "⚠ " + st.err)) : null,
    table, sug, foot));
}

// ---- A3 code (desktop): a work-folder file, read-only, line numbers, the lines the audit or a card names marked ----------
// st: {task, where: "config.yaml:5" | a path, line?: the line Pablo found it on (overrides where's), note?}. No editing here:
// changes go through the agent (Guard) or the user's own editor ("VS Code에서 열기").
// C11: 근거 · <file>; 파일 고르기 ▾ (S62: the files the conversation and the audits named, with how many audits); what
// points at it and 대화로 거르기; the marked line said in words under the code; S63 changed since the audit; S64 not shown
const fileOf = w => String(w).split(/[;,]\s/)[0].replace(/\s*\(.*$/, "").replace(/(:\d+(?:[-,]\d+)*)+$/, "").replace(/\\/g, "/");
function auditOf(where) {
  for (const c of [...(V.chat || [])].reverse()) if (c.role === "audit")
    for (const x of [...(c.items || []), ...(c.outside || [])]) if (x.where === where || (x.seen && x.seen.where === where)) return x;
  return null;
}
function refText(id) {
  const k = V.checks[id]; if (k) return shortText(k.conclusion || k.title, 40);
  const I = V.intent, x = [...I.must, ...I.prefer, ...I.goals, ...I.success, ...I.decisions].find(y => y.id === id);
  return x ? shortText(x.text, 40) : "";
}
function filePick(st, name, L) {
  const here = fileOf(st.where), files = [...new Set([here, ...[...L.keys()].filter(r => r.startsWith("file:")).map(r => r.slice(5))])];
  const audits = f => backOf("file:" + f, L).keys.filter(k => /^audit@/.test(k)).length;
  return menuChip(h("button", { class: "url pick", title: st.where, "aria-haspopup": "menu" }, urlIco("file", "📄 "), name, ico("chevron-down", 12)),
    files.map(f => h("button", { class: "mi" + (f === here ? " on" : ""), "data-pick-file": f, on: () => f !== here && show({ mode: "code", task: st.task, where: f }) },
      ico("file", 14), h("span", null, f), audits(f) ? h("small", null, `점검 ${audits(f)}`) : null, f === here ? ico("check", 13) : null)),
    "이 작업에서 인용 · 판정에 나온 파일만 보입니다. 읽기 전용입니다.");
}
function codeView(p, st) {
  document.body.classList.add("code");
  p.dataset.live = "LOADING";
  const L = linksOf(V), file = fileOf(st.where), ref = "file:" + file, b = backOf(ref, L), audits = b.keys.filter(k => /^audit@/.test(k)).length;
  const info = h("div", { class: "info" }), name = h("b", null, st.where), meta = h("span", { class: "meta" }, "작업 폴더의 파일을 읽는 중…");
  const title = h("h2", { title: st.where }, `근거 · ${st.where}`);
  const open = how => pabloHost.openFile(st.task, st.where, st.line || null, how).then(r => {
      if (hist[hi] === st) info.textContent = { vscode: "VS Code로 열었습니다.", app: "기본 프로그램으로 열었습니다.", folder: "파일이 있는 폴더를 열었습니다." }[r] || ""; },
    e => { if (hist[hi] === st) { info.className = "info broken"; info.textContent = "⚠ " + fail(e); } });
  const opens = (tag = true) => [h("button", { class: "pill open", "data-open": tag ? "vscode" : null, on: () => open("vscode") }, ico("code", 14), "VS Code"),
    h("button", { class: "pill open", "data-open": tag ? "folder" : null, on: () => open("folder") }, ico("folder", 14), "폴더")];  // demo 10/28: two equal buttons
  const lnote = h("p", { class: "lnote", hidden: true });
  p.append(...[h("div", { class: "phead" }, title, wbtn(), xbtn()),
    h("div", { class: "ptool" }, navs(), filePick(st, name, L), h("span", { class: "sp" }), meta),
    h("div", { class: "ptool acts" }, opens()),
    b.chat ? backBand(`이 파일을 가리킨 점검 ${audits} · 대화 ${b.chat - audits}`, [ref], "파일 · " + file, b.chat) : null,
    info, h("div", { id: "pbody", class: "code" }), lnote].filter(Boolean));
  pabloHost.readFile(st.task, st.where, st.line || null, st.expect || null).then(f => {
    if (hist[hi] !== st) return;
    const rs = st.line ? [[st.line, st.line]] : f.ranges || [], box = $("pbody");  // "a.py:6,15" marks both
    name.textContent = f.path + (rs.length ? ":" + rs.map(([a, b]) => b > a ? `${a}-${b}` : a).join(",") : "");
    title.textContent = "근거 · " + name.textContent; title.title = name.textContent;
    const src = box.appendChild(h("div", { class: "src" }, f.lines.map((l, i) => { const n = f.first + i;
      return h("div", { class: "ln" + (rs.some(([a, b]) => n >= a && n <= b) ? " on" : ""), "data-n": n }, h("span", { class: "n" }, n), h("span", { class: "t" }, l)); })));
    const on = src.querySelector(".ln.on");
    meta.textContent = `작업 폴더 · 읽기 전용 · ${f.total}줄`;
    info.textContent = [rs.length && !on ? `이 파일에는 ${rs[0][0]}줄이 없습니다` : null, st.note,
      f.truncated ? `긴 파일이라 ${f.first}–${f.first + f.lines.length - 1}줄만 보여 줍니다` : null].filter(Boolean).join(" · ");
    if (rs.length && !on) info.className = "info broken";
    // ⑤ / S63 what the audit saw on this line, checked again now: gone or moved since -> said, the row's verdict may be old
    const was = String(st.expect || "").split("\n")[0].slice(0, 60);
    if (f.still === "not_found" || f.still === "moved") {
      info.className = "info broken"; p.dataset.still = f.still;
      const j = was.trim() ? f.lines.findIndex(l => l.includes(was.trim())) : -1, at = j >= 0 ? f.first + j : 0;
      info.prepend(`⚠ 점검 때 이 자리에 있던 "${was}"이(가) 지금은 ${f.still === "moved" ? "다른 줄에 있습니다" : "없습니다"}. 점검 뒤 파일이 바뀌었습니다. 판정은 점검 때 파일 기준입니다. `,
        at && at !== st.line ? h("button", { class: "link", "data-goto-line": String(at), on: () => show({ ...st, line: at, expect: null }) }, `${at}줄로 가기`) : "", " ",
        reAudit && V && V.task.id === st.task ? h("button", { class: "link", "data-reaudit": "1", on: () => reAudit(st.task) }, ico("rotate", 12), "다시 점검") : "", info.textContent ? " · " : "");
    }
    if (on) { const n = +on.dataset.n, x = auditOf(st.where), what = x ? refText(x.id) : "";
      lnote.hidden = false;
      lnote.textContent = `${n}번째 줄: ${what ? `점검 항목 "${what}"이(가) 댄 자리입니다.` : "대화나 점검이 가리킨 자리입니다."} 고치는 일은 에이전트나 외부 편집기에서 합니다.`;
      box.scrollTop += on.getBoundingClientRect().top - box.getBoundingClientRect().top - box.clientHeight / 3; }
    p.dataset.live = on ? "FOUND" : "OPEN";
  }, e => { if (hist[hi] !== st) return; p.dataset.live = "ERROR"; meta.textContent = "";
    $("pbody").replaceChildren(pcard({ class: "pcard white", "data-cant-open": "1" }, "이 파일은 보여 드릴 수 없습니다",
      fail(e) + " 파일은 그대로이고, 다른 프로그램에서 열 수 있습니다.", h("div", { class: "btns" }, opens(false)))); });
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
// S61: 자료 고르기 ▾ — the task's sources, how many places this task cites in each; a pick opens its first cited place
function srcPick(sid, kind) {
  const d = (M.desk || {})[V.task.id] || {}, cur = M.sources[sid] || (M.papers || {})[sid] || {};
  const list = [...(d.papers || []).map(x => ({ id: x.id, title: x.title, kind: x.kind === "web" ? "WEB" : "PDF" }))];
  if (!list.some(x => x.id === sid)) list.unshift({ id: sid, title: cur.title || "", kind });
  const evs = evList(), of = id => evs.filter(e => M.anchors[e].source === id);
  const openIt = x => { const e = of(x.id)[0]; if (e) return show({ mode: "source", e });
    if (x.kind === "PDF" && (M.papers || {})[x.id]) show({ mode: "paper", src: x.id }); };
  const label = kind === "WEB" ? urlIco("globe", "🌐 ") : urlIco("file", "📄 ");
  return menuChip(h("button", { class: "url pick", title: cur.url || cur.title || "", "aria-haspopup": "menu" }, label, h("b", null, cur.title || ""), ` · ${kind}`, ico("chevron-down", 12)),
    list.map(x => { const n = of(x.id).length, can = n || (x.kind === "PDF" && (M.papers || {})[x.id]);
      return h("button", { class: "mi" + (x.id === sid ? " on" : ""), "data-pick-src": x.id, disabled: can ? null : true, on: () => x.id !== sid && openIt(x) },
        ico(x.kind === "WEB" ? "globe" : "file", 14), h("span", null, x.title), h("small", null, `${x.kind} · ${n}`), x.id === sid ? ico("check", 13) : null); }),
    "숫자는 이 작업에서 인용한 곳의 수입니다. 고르면 처음 인용한 쪽으로 엽니다.");
}
// C10 / C12: what points at this place (a table cell: the conversations citing it; a page: the conversations and decisions)
function evBand(e, a, page, L) {
  const cell = e ? cellOf(e) : null;
  if (cell) { const b = backOf(cell.id, L); return backBand(`이 칸을 인용한 대화 ${b.chat}`, [cell.id], `칸 [${numOf(e)}]`, b.chat); }
  const refs = e && page === (a || {}).page ? [e, `${a.source}:p${page}`] : [`${(a || {}).source}:p${page}`];
  const b = backOf(refs, L), dec = b.verdicts.filter(v => v.decision).length, src = M.sources[(a || {}).source] || (M.papers || {})[(a || {}).source] || {};
  return backBand(page ? `이 쪽을 인용한 대화 ${b.chat}` + (dec ? ` · 결정 ${dec}` : "") : `이 근거를 인용한 대화 ${b.chat}` + (dec ? ` · 이 근거로 한 결정 ${dec}` : ""),
    refs, page ? `${src.title || "자료"} p.${page}` : `근거 [${numOf(e)}]`, b.chat);
}
function source(p, st) {
  const a = M.anchors[st.e], src = M.sources[a.source];
  if (src.kind === "pdf" && window.pabloHost && !st.failed && src.intact) return pdfPanel(p, st, a, src);
  const ok = src.intact && src.text.slice(a.start, a.end) === a.exact, live = fragment(src, a), pdf = src.kind === "pdf", asText = st.failed === "TEXT";
  const inApp = window.pabloHost && !st.failed && (st.live || !["STALE", "UNRESOLVED"].includes(a.status));
  p.dataset.live = inApp ? "LOADING" : st.failed || "SNAPSHOT";
  // F23 / S66: one status line under the address: found live, the snapshot and how it compares, or why it fell back
  const info = inApp ? h("div", { class: "info" }, "현재 원문 · 근거 위치를 찾는 중…")
    : asText ? h("div", { class: "info" }, `PDF에서 추출한 본문입니다 · 근거 [${numOf(st.e)}]을 강조했습니다. `,
        h("button", { class: "link", on: () => show({ mode: "source", e: st.e }) }, "PDF로 보기"))
    : h("div", { class: "info " + (st.failed ? "STALE" : ok ? a.status : "broken"), title: src.hash },
      st.failed ? "⚠ " + (pdf ? PDF_FALLBACK : FALLBACK) : [`${ok && a.status === "VALID" ? "✓ " : "⚠ "}캡처한 원문 · ${day(src.captured_at)} ${time(src.captured_at)} · `,
        ok ? a.message : "캡처본이 이 근거와 맞지 않아 표시하지 않습니다."], " ",
      window.pabloHost && !st.failed && !pdf ? h("button", { class: "link", on: () => show({ mode: "source", e: st.e, live: true }) }, "현재 원문 열기")
        : h("a", { href: live, target: "_blank", rel: "noopener noreferrer" }, "원본에서 보기 ↗"));
  const page = pdf ? a.page : 0, u = (() => { try { return new URL(src.url); } catch { return null; } })();
  p.append(...[phead(`근거 · ${src.title}`),
    h("div", { class: "ptool" }, navs(), srcPick(a.source, pdf ? "PDF" : "WEB"), h("span", { class: "sp" }), pdf ? h("span", { class: "pnum" }, `p.${a.page}`) : null),
    evBand(st.e, a, page, linksOf(V)),
    pdf ? null : h("div", { class: "urlrow", title: src.url }, ico("lock", 14), h("b", null, src.title), h("span", null, " · " + (u ? u.host : host(src.url))),
      h("small", null, u ? u.pathname : ""), h("a", { class: "ext", href: live, target: "_blank", rel: "noopener noreferrer", title: "원본 페이지에서 이 문장 보기" }, ico("external", 14))),
    info, inApp ? h("div", { id: "pbody", class: "live" })
      : h("div", { id: "pbody" }, h("article", { id: "doc" }, h("div", { class: "title" }, src.title))),
    !inApp && !pdf && window.pabloHost && !st.failed ? h("div", { class: "pfoot2" },
      h("a", { href: live, target: "_blank", rel: "noopener noreferrer", "data-orig": "1" }, "원본에서 보기 ↗")) : null].filter(Boolean));
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
// S65: a PDF whose capture cannot be shown says so; the source itself is untouched
const cantPdf = (src, e) => pcard({ class: "pcard white", "data-cant-pdf": "1" }, "이 PDF의 캡처본을 열 수 없습니다",
  "자료는 그대로입니다. 원본 파일로 열어 보거나 추출 텍스트로 근거를 확인하세요.",
  h("div", { class: "btns" }, src && /^https?:/i.test(src.url || "") ? h("a", { class: "pill", href: src.url, target: "_blank", rel: "noopener noreferrer" }, "원본 열기 ↗") : null,
    e ? h("button", { class: "link", on: () => show({ mode: "source", e, failed: "TEXT" }) }, "추출 텍스트로 보기") : null));
function paper(p, st) {
  const src = (M.papers || {})[st.src];
  if (!src || !src.intact || !src.pages) { p.dataset.live = "ERROR"; return simple(p, "근거 · " + ((src || {}).title || "PDF"), cantPdf(src)); }
  return pdfPanel(p, st, null, src);
}
// S69: the 근거 tab before anything is cited: how a citation comes, and the task's papers to read meanwhile
function evhome(p) {
  const ps = (((M.desk || {})[V.task.id] || {}).papers || []).filter(x => x.kind !== "web" && (M.papers || {})[x.id]);
  simple(p, "근거", pcard({ "data-no-cites": "1" }, "아직 인용한 근거가 없습니다",
    "논문 질문을 하거나 재현 조건을 뽑으면 [1]처럼 인용이 붙고, 누르면 여기서 그 쪽을 엽니다.",
    ps.map(x => h("button", { class: "link", "data-read-paper": x.id, on: () => show({ mode: "paper", src: x.id }) }, `${x.title} 열어 보기`))));
}
// C10: 근거 · <paper>; 자료 고르기 ▾, zoom and the page; what cites the page in view (or this table cell) and 대화로 거르기;
// where the quote was found ("9쪽에서 근거 [1]을 찾아 표시했습니다"); under the pages 원본 열기 ↗ · 추출 텍스트로 보기.
// demo 10/28: one scroll of all pages (drawn when near the view), fitted to the column's width and fitted again when the
// column is dragged or widened; − / % / + / 폭 맞춤 and Ctrl+wheel; the page in view is said as "N / M" while scrolling,
// 이전 / 다음 쪽 scroll to a page. The quote's boxes are drawn on its page at every scale.
async function pdfPanel(p, st, a, src) {
  const t0 = performance.now(), sid = a ? a.source : st.src;
  let n = a ? a.page : st.page || 1;  // the page in view
  document.body.classList.add("pdf");
  p.dataset.live = "LOADING";
  const cell = a ? cellOf(st.e) : null, num = a ? numOf(st.e) : 0;
  const info = h("div", { class: "info", title: src.hash }, `캡처한 PDF · ${a ? "근거 위치를 찾는 중…" : "여는 중…"}`);
  const asText = h("button", { class: "mini", "data-as-text": "1", on: () => a && !st.text && n === a.page ? show({ mode: "source", e: st.e, failed: "TEXT" })
    : show({ ...st, page: n, text: !st.text }) }, st.text ? "PDF로 보기" : "추출 텍스트로 보기");
  let go = () => {}, zoomBy = () => {}, fitNow = () => {};
  const prev = h("button", { class: "nav pg-t", title: "이전 쪽", disabled: n <= 1, on: () => go(n - 1) }, turned("chevron-right", 180, 14));
  const next = h("button", { class: "nav pg-t", title: "다음 쪽", disabled: n >= src.pages, on: () => go(n + 1) }, ico("chevron-right", 14));
  const pnum = h("span", { class: "pnum" }, `${n} / ${src.pages}`);
  const zl = h("span", { class: "zl", title: "배율" }, "폭 맞춤");
  const zoom = st.text ? null : h("span", { class: "zoom", role: "group", "aria-label": "확대" },
    h("button", { class: "nav", title: "축소 (Ctrl + 휠)", "data-zoom": "out", on: () => zoomBy(1 / 1.2) }, ico("minus", 14)), zl,
    h("button", { class: "nav", title: "확대 (Ctrl + 휠)", "data-zoom": "in", on: () => zoomBy(1.2) }, ico("plus", 14)),
    h("button", { class: "nav", title: "폭 맞춤", "data-zoom": "fit", on: () => fitNow() }, ico("fit", 14)));
  const band = h("div", { class: "pband" });
  const drawBand = () => band.replaceChildren(...[evBand(st.e, a || { source: sid }, n, linksOf(V))].filter(Boolean));
  drawBand();
  p.append(phead(`근거 · ${src.title}`),
    h("div", { class: "ptool" }, navs(), srcPick(sid, "PDF"), h("span", { class: "sp" }), h("span", { class: "pctl" }, zoom, prev, pnum, next)),
    band, info, h("div", { id: "pbody", class: "pdf" }),
    h("div", { class: "pfoot2" }, /^https?:/i.test(src.url || "") ? h("a", { class: "mini", href: src.url, target: "_blank", rel: "noopener noreferrer", "data-orig": "1" }, "원본 열기 ↗") : null, asText));
  const fail = why => { if (hist[hi] !== st) return;
    if (!a) { p.dataset.live = "ERROR"; info.textContent = ""; const b = $("pbody"); if (b) b.replaceChildren(cantPdf(src)); return; }
    hist[hi] = { mode: "source", e: st.e, failed: why }; show(hist[hi], false); };
  try {
    const L = await pdfLib();
    const doc = await (pdfs[sid] = pdfs[sid] || L.getDocument({ url: "pablo://source/" + src.file,
      standardFontDataUrl: PDFJS + "standard_fonts/", cMapUrl: PDFJS + "cmaps/", wasmUrl: PDFJS + "wasm/" }).promise);
    const box = $("pbody");
    if (hist[hi] !== st || !box) return;
    if (st.text) {  // the page's own text (pdf.js), for a page without a quote to box
      const tc = await (await doc.getPage(n)).getTextContent();
      if (hist[hi] !== st) return;
      box.classList.add("astext");
      box.append(h("article", { id: "doc" }, h("div", { class: "b p" }, tc.items.map(i => i.str + (i.hasEOL ? "\n" : "")).join(""))));
      p.dataset.live = "TEXT"; info.textContent = `${n}쪽에서 추출한 본문입니다.`; return;
    }
    const total = doc.numPages, live = () => hist[hi] === st && box.isConnected;
    const sizes = await Promise.all(Array.from({ length: total }, (_, i) => doc.getPage(i + 1).then(pg => { const v = pg.getViewport({ scale: 1 }); return [v.width, v.height]; })));
    if (!live()) return;
    const sheets = sizes.map((_, i) => h("div", { class: "pg", "data-n": String(i + 1) }));
    box.append(...sheets);
    // the width the pages may take: #pbody's content box (its padding is not page; 2px for the page's border)
    const room = () => { const cs = getComputedStyle(box); return box.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 2; };
    const fitted = () => Math.max(0.2, room() / Math.max(...sizes.map(s => s[0])));
    let fit = true, scale = fitted(), hit = null;  // hit: the quote on its page {page, items, s, e}
    const size = () => { sheets.forEach((s, i) => { s.style.width = sizes[i][0] * scale + "px"; s.style.height = sizes[i][1] * scale + "px";
      s.style.setProperty("--total-scale-factor", scale); s.style.setProperty("--scale-round-x", "1px"); s.style.setProperty("--scale-round-y", "1px"); });
      zl.textContent = fit ? "폭 맞춤" : Math.round(scale * 100) + "%"; };
    size();
    const marks = (i, vp) => hit && hit.page === i ? boxes(hit.items, hit.s, hit.e, vp, L) : [];
    const draw = i => {  // page i at the current scale: canvas, then its text layer, then the quote's boxes
      const s = sheets[i - 1];
      if (!s || s._at === scale) return s && s._p;
      const want = s._at = scale;
      return s._p = (async () => {
        const pg = await doc.getPage(i), vp = pg.getViewport({ scale: want }), dpr = devicePixelRatio || 1;
        const cv = h("canvas", { width: Math.floor(vp.width * dpr), height: Math.floor(vp.height * dpr) });
        await pg.render({ canvasContext: cv.getContext("2d"), viewport: vp, transform: dpr === 1 ? null : [dpr, 0, 0, dpr, 0, 0] }).promise;
        if (s._at !== want || !live()) return;
        const tc = s._tc || (s._tc = await pg.getTextContent()), layer = h("div", { class: "textLayer" });
        // ⑩ the page's text over the canvas (selectable); a sentence picked there can become a reproduction condition
        await new L.TextLayer({ textContentSource: tc, container: layer, viewport: vp }).render().catch(e => console.error("[pdf] text", e));
        if (s._at !== want || !live()) return;
        s.replaceChildren(cv, layer, ...marks(i, vp).map(b => h("div", { class: "hl", style: `left:${b.l}px;top:${b.t}px;width:${b.r - b.l}px;height:${b.b - b.t}px` })));
      })().catch(e => { console.error("[pdf] page", i, e); s._at = null; });
    };
    const io = new IntersectionObserver(es => es.forEach(e => e.isIntersecting && live() && draw(+e.target.dataset.n)), { root: box, rootMargin: "100% 0px" });
    const watch = () => { io.disconnect(); sheets.forEach(s => io.observe(s)); };
    // the page in view: the one across the upper third of the panel (the last one once scrolled to the end)
    let paperInfo = () => {};
    const setPage = k => { if (k === n) return; n = k; if (!a) st.page = k;
      pnum.textContent = `${k} / ${total}`; prev.disabled = k <= 1; next.disabled = k >= total; drawBand(); paperInfo(); };
    const track = () => { if (!live()) return;
      if (box.scrollTop > 0 && box.scrollTop + box.clientHeight >= box.scrollHeight - 2) return setPage(total);
      const y = box.scrollTop + box.clientHeight / 3; let k = 1;
      for (const s of sheets) { if (s.offsetTop <= y) k = +s.dataset.n; else break; }
      setPage(k); };
    let tr = 0;
    box.addEventListener("scroll", () => { if (!tr) tr = requestAnimationFrame(() => { tr = 0; track(); }); }, { passive: true });
    go = k => { const s = sheets[k - 1]; if (!s) return; box.scrollTo({ top: s.offsetTop - 8, behavior: "smooth" }); setPage(k); };
    // a new scale keeps the same spot of the same page in view
    const rescale = s2 => { if (!live()) return;
      const s = sheets[n - 1], off = (box.scrollTop - s.offsetTop) / s.offsetHeight;
      scale = s2; size(); box.scrollTop = s.offsetTop + off * s.offsetHeight; watch(); };
    zoomBy = f => { fit = false; rescale(Math.min(4, Math.max(0.3, scale * f))); };
    fitNow = () => { fit = true; rescale(fitted()); };
    box.addEventListener("wheel", e => { if (!e.ctrlKey) return; e.preventDefault(); zoomBy(e.deltaY < 0 ? 1.1 : 1 / 1.1); }, { passive: false });
    // the column dragged or widened: fitted again once it rests (not on every pixel of a drag)
    let rt = 0, w0 = box.clientWidth;
    const ro = new ResizeObserver(() => { if (!live()) { ro.disconnect(); io.disconnect(); return; }
      if (!fit || box.clientWidth === w0) return;
      clearTimeout(rt); const again = () => { if (document.body.classList.contains("dragging")) { rt = setTimeout(again, 150); return; }
        w0 = box.clientWidth; rescale(fitted()); }; rt = setTimeout(again, 150); });
    ro.observe(box);
    const picks = picker(p, box, sid);
    if (!a) {
      paperInfo = () => { info.textContent = `캡처한 PDF · ${n}쪽` + (picks ? " · 문장을 끌어서 고르면 재현 조건으로 더할 수 있습니다." : ""); };
      await draw(n); if (!live()) return;
      box.scrollTop = sheets[n - 1].offsetTop - 8; watch();
      p.dataset.live = "PAPER"; paperInfo(); return;
    }
    const pg = await doc.getPage(a.page), tc = sheets[a.page - 1]._tc = await pg.getTextContent();
    if (!live()) return;
    const items = tc.items.filter(i => "str" in i), r = findIn(items, a);
    if (r.status !== "FOUND") { io.disconnect(); ro.disconnect(); return near(p, st, a, src, a.page, items, info, () => fail(r.status)); }
    hit = { page: a.page, items, s: r.start, e: r.end };
    const bs = boxes(items, r.start, r.end, pg.getViewport({ scale }), L);
    if (!bs.length) return fail("HIDDEN");
    await draw(a.page); if (!live()) return;
    box.scrollTop = Math.max(0, sheets[a.page - 1].offsetTop + Math.min(...bs.map(b => b.t)) - box.clientHeight / 3); watch();
    p.dataset.ms = Math.round(performance.now() - t0); p.dataset.live = "FOUND";
    info.textContent = cell ? `✓ ${a.page}쪽에서 칸 [${num}]의 근거를 찾아 표시했습니다.` : `✓ ${a.page}쪽에서 근거 [${num}]을 찾아 표시했습니다.`;
  } catch (err) { console.error("[pdf]", err); fail("ERROR"); }
}
// B20 / S8: the quote is not on its page as pdf.js reads it (or twice there): the places on the page most like it (Python
// evidence.similar over pdf.js's own text of the page), best first; a click marks one in the page's extracted text, which
// the card shows instead of the page. Nothing like it (or no host) -> the snapshot fallback as before.
async function near(p, st, a, src, n, items, info, otherwise) {
  const T = items.map(i => i.str + (i.hasEOL ? "\n" : "")).join("");
  let hits = [];
  if (window.pabloHost && pabloHost.similar && T.trim()) hits = await pabloHost.similar(T, a.exact).catch(e => { console.error("[pdf] similar", e.message); return []; });
  if (hist[hi] !== st) return;
  if (!hits.length) return otherwise();
  const box = $("pbody"), text = document.createTextNode(T), http = /^https?:/i.test(src.url || "");
  const mark = i => { const x = hits[i], r = new Range();
    r.setStart(text, x.start); r.setEnd(text, x.end); CSS.highlights.set("evidence", new Highlight(r));
    card.querySelectorAll("[data-hit]").forEach(b => b.classList.toggle("on", +b.dataset.hit === i));
    box.scrollTop += r.getBoundingClientRect().top - box.getBoundingClientRect().top - box.clientHeight / 3; };
  const card = h("div", { class: "pcard s8", "data-similar": String(hits.length) },
    h("div", { class: "s8head" }, `${n}쪽에서 위치를 찾지 못했습니다 — 비슷한 문장 ${hits.length}곳`),
    h("div", { class: "s8hits" }, hits.map((x, i) => h("button", { class: "s8hit", "data-hit": String(i), title: "추출 텍스트에서 이 문장을 표시합니다", on: () => mark(i) },
      h("span", null, x.text.replace(/\s+/g, " ")), h("small", null, `${Math.round(x.score * 100)}%`)))),
    h("p", null, "추출 텍스트로 보여 드립니다. 원본에서 직접 확인하세요."),
    h("article", { id: "doc" }, h("div", { class: "b p" }, text)),
    http ? h("div", { class: "btns" }, h("a", { class: "link", href: src.url, target: "_blank", rel: "noopener noreferrer", "data-orig": "1" }, "원본 열기 ↗")) : null);
  box.classList.add("s8"); box.replaceChildren(card);
  info.hidden = true; const foot = p.querySelector(".pfoot2"); if (foot) foot.remove();
  p.dataset.live = "SIMILAR";
}
// ⑩ / F22 (desktop) a sentence picked on a page of the task's paper -> a floating "재현 조건으로 더하기" over it -> a card:
// its kind, its value, the condition in one line, a condition already like it named first. Pablo anchors the sentence on that
// page like an extracted condition (main.js: only the 주 논문; not found -> refused).
function picker(p, box, sid) {
  const d = V && (M.desk || {})[V.task.id] || {};
  if (!window.pabloHost || !pabloHost.condition || !(d.papers || []).some(x => x.id === sid && x.kind !== "web")) return false;
  const bar = p.appendChild(h("div", { id: "pick", class: "float", hidden: true })), task = V.task.id, main = (d.papers || []).find(x => x.primary);
  let form = false, n = 0;  // n: the page the picked sentence is on (demo 10/28: all pages are in one scroll)
  // the text layer of one page that holds the whole selection, else null (a selection across pages is not a sentence)
  const pageOf = r => { const c = r.commonAncestorContainer, el = c.nodeType === 1 ? c : c.parentElement, sheet = el && el.closest(".pg");
    const layer = sheet && box.contains(sheet) && sheet.querySelector(".textLayer");
    return layer && layer.contains(c) ? +sheet.dataset.n : 0; };
  const place = () => { const sel = getSelection(); if (!sel.rangeCount) return;
    const r = sel.getRangeAt(0).getBoundingClientRect(), pr = p.getBoundingClientRect();
    bar.style.top = Math.max(8, r.top - pr.top - 40) + "px";
    bar.style.left = Math.max(8, Math.min(r.left - pr.left + r.width / 2 - 90, pr.width - 200)) + "px"; };
  const offer = () => {
    if (form) return;
    const sel = getSelection(), q = sel.toString().replace(/\s+/g, " ").trim();
    if (!q || !sel.rangeCount || !(n = pageOf(sel.getRangeAt(0)))) { bar.hidden = true; return; }
    bar.hidden = false; bar.className = "float";
    bar.replaceChildren(q.length > 600 ? h("span", { class: "tip" }, "한 문장만 골라 주세요.")
      : h("button", { class: "fbtn", "data-add-spec": "1", title: `“${q.length > 90 ? q.slice(0, 90) + "…" : q}”`, on: () => open(q) }, ico("plus", 14), "재현 조건으로 더하기"));
    place();
  };
  const open = q => {
    form = true; bar.className = "form"; bar.style.top = bar.style.left = "";
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
    const val = h("input", { "data-value": "1", placeholder: "예: 5" }), note = h("span", { "data-pick-note": "1" });
    const add = h("button", { class: "pill on", "data-add-ok": "1", disabled: true, on: () => {
      if (!say.value.trim()) return say.focus();
      const same = !sure && similar();
      if (same) return note.replaceChildren("비슷한 조건이 이미 있습니다: ", h("span", { "data-similar": same.id }, (SPEC[same.spec.category] || same.spec.category) + " · ", fact(same)),
        " ", h("button", { class: "link strong", "data-anyway": "1", on: () => { sure = true; add.click(); } }, "그래도 더하기"));
      add.disabled = true; note.textContent = "원문에서 위치를 찾는 중…";
      pabloHost.condition(task, "add", { src: sid, page: n, quote: q, category: cat.value, statement: say.value.trim(), value: val.value.trim() }).then(r => {
        Object.assign(M.anchors, r.anchors); Object.assign(M.sources, r.sources); M.views[task].checks[r.check.id] = r.check;
        form = false; getSelection().removeAllRanges();
        bar.className = "form done";
        bar.replaceChildren(h("span", { "data-added": r.check.id }, ico("check", 14), " 재현 조건에 더했습니다. 에이전트와 재현 점검이 이 조건도 봅니다."),
          h("button", { class: "mini", on: () => { bar.hidden = true; } }, "닫기"));
        echo(task, { role: "spec-add", check: r.check.id });
        return refresh();
      }, e => { add.disabled = false; note.textContent = fail(e); }); } }, "더하기");
    const cancel = h("button", { class: "pill", "data-pick-cancel": "1", on: () => { form = false; bar.hidden = true; } }, "취소");
    bar.replaceChildren(h("div", { class: "q" }, `“${q}”`, h("small", null, ` — p.${n}`)),
      h("div", { class: "grid" }, h("label", null, h("span", null, "종류"), cat), h("label", null, h("span", null, "값 (선택)"), val)),
      h("label", null, h("span", null, "조건 한 줄"), say),
      h("div", { class: "simnote" }, ico("info", 14), note),
      h("div", { class: "row" }, add, cancel, main ? h("small", null, `주 논문(${main.title})에서만 더합니다.`) : null));
    say.focus();
  };
  box.addEventListener("mouseup", () => setTimeout(offer, 0));
  box.addEventListener("scroll", () => { if (!form) bar.hidden = true; });
  return true;
}

// Esc closes a floating box first (a dialog, a menu, the chips' card), else the narrow window's drawer, else the right
// column; a click outside a menu or the card closes it (QA 10/26: they only closed from their own button). A2 complete:
// Ctrl N (⌘N) 새 작업, Ctrl K (⌘K) the task search, F2 renames the open task
const floating = () => [$("settings"), $("newtask"), $("report-dlg"), document.querySelector("#more-menu:not([hidden])"),
  document.querySelector(".composer > .mmenu:not([hidden])"), document.querySelector("#srccard:not([hidden])")].find(Boolean);
addEventListener("keydown", e => {
  if (e.isComposing) return;
  const mod = MAC ? e.metaKey : e.ctrlKey, k = (e.key || "").toLowerCase();
  if (mod && !e.shiftKey && !e.altKey && k === "n" && window.pabloHost && pabloHost.newTask) { e.preventDefault(); return newTask(); }
  if (mod && !e.shiftKey && !e.altKey && k === "k") { e.preventDefault(); return findTasks(); }
  if (e.key === "F2" && V && !floating()) { const b = document.querySelector("[data-rename-task]"); if (b) { e.preventDefault(); b.click(); } return; }
  if (e.key !== "Escape") return;
  const f = floating();
  if (!f) return document.body.classList.contains("side") ? document.body.classList.remove("side") : close();
  if (["settings", "newtask", "report-dlg"].includes(f.id)) f.remove();
  else if (f.id === "srccard") cardClose();
  else { f.hidden = true; if (f.id === "more-menu" && $("more")) $("more").setAttribute("aria-expanded", "false"); } });
matchMedia("(max-width:900px)").addEventListener("change", () => sidebar());
addEventListener("mousedown", e => {
  const m = document.querySelector(".composer > .mmenu:not([hidden])"), c = document.querySelector("#srccard:not([hidden])");
  const o = document.querySelector("#more-menu:not([hidden])");
  if (m && !e.target.closest(".mmenu, .modelbtn")) m.hidden = true;
  if (o && !e.target.closest("#more-menu, #more")) { o.hidden = true; if ($("more")) $("more").setAttribute("aria-expanded", "false"); }
  if (c && !e.target.closest("#srccard, .hchip")) cardClose();
}, true);

// ---- M4.0/M4.1 desktop host only: ChatGPT connection + composer -> persistent Codex app-server thread (desktop/) ----
if (window.pabloHost && pabloHost.chat) {
  // demo 10/27: a long message wraps; the box grows to 8 lines, then scrolls. Enter sends, Shift+Enter is a new line
  const box = document.querySelector("#chat > .composer"), inp = h("textarea", { rows: 1, "aria-label": "메시지" }), btn = box.querySelector("button");
  box.querySelector("input").replaceWith(inp);
  const grow = () => { inp.style.height = "auto"; inp.style.height = Math.min(inp.scrollHeight, 200) + "px"; };
  inp.addEventListener("input", grow);
  const st = box.insertBefore(h("small", { class: "muted", id: "agent" }), btn);
  const pick = box.insertBefore(h("select", { id: "model", title: "모델" }), st);  // the ChatGPT account's catalog (/v1/models, visibility "list")
  pick.addEventListener("change", () => pabloHost.setModel(pick.value));
  // team review: the model is a quiet text button with a menu; the <select> stays (hidden) and carries the same events.
  // Both come after the send button in the DOM (the first button stays send / stop) and CSS orders them on screen.
  const mbtn = box.appendChild(h("button", { class: "modelbtn", type: "button", title: "모델", hidden: true }));
  const mmenu = box.appendChild(h("div", { class: "mmenu", hidden: true }));
  // A2 complete · B (S16): the chip says "모델 · 생각 수준"; its menu lists the models, then the levels the model offers (24,
  // from the next message; locked while an answer comes)
  const LEVEL = { minimal: "최소", low: "낮음", medium: "보통", high: "높음", xhigh: "매우 높음" };
  let eff = { efforts: {}, effort: null };
  const effOf = () => { const e = eff.efforts[pick.value] || { levels: [], def: null }, lv = (e.levels || []).filter(x => LEVEL[x]);
    return { lv, cur: lv.includes(eff.effort) ? eff.effort : lv.includes(e.def) ? e.def : null }; };
  const mlabel = () => { const o = pick.options[pick.selectedIndex], { cur } = effOf();
    mbtn.replaceChildren(h("span", null, (o ? o.textContent : "모델") + (cur ? " · " + LEVEL[cur] : "")), ico("chevron-down", 12)); };
  // A2: where a new message is recorded, as the stage pill (it used to be the end of the placeholder)
  const hint = box.appendChild(h("span", { class: "stagehint", hidden: true }));
  const drawMenu = () => { mmenu.textContent = ""; const { lv, cur } = effOf();
    mmenu.append(h("p", { class: "mm-h" }, "모델"));
    [...pick.options].forEach(o => mmenu.append(h("button", { class: "mopt" + (o.value === pick.value ? " on" : ""), type: "button",
      on: () => { pick.value = o.value; pick.dispatchEvent(new Event("change")); mmenu.hidden = true; } }, h("span", null, o.textContent), o.value === pick.value ? ico("check", 14) : null)));
    if (lv.length && pabloHost.setEffort) mmenu.append(h("p", { class: "mm-h" }, "생각 수준"), h("div", { class: "mm-seg", role: "group", "aria-label": "생각 수준" },
      lv.map(x => h("button", { type: "button", class: "mlv" + (x === cur ? " on" : ""), "data-effort": x, "aria-pressed": String(x === cur),
        on: () => pabloHost.setEffort(x).then(() => { eff.effort = x; mlabel(); drawMenu(); }) }, LEVEL[x]))),
      h("p", { class: "mm-note" }, "다음 메시지부터 적용됩니다. 답을 받는 중에는 바꿀 수 없습니다."));
    else mmenu.append(h("p", { class: "mfoot" }, "계정에서 쓸 수 있는 모델입니다. 다음 메시지부터 이 모델로 보냅니다. 답을 받는 중에는 바꿀 수 없습니다.")); };
  mbtn.addEventListener("click", () => { mmenu.hidden = !mmenu.hidden; if (!mmenu.hidden) drawMenu(); });
  pick.addEventListener("change", mlabel);
  const models = () => Promise.all([pabloHost.models(), pabloHost.efforts ? pabloHost.efforts().catch(() => null) : null]).then(([r, e]) => {
    if (e) eff = e;
    pick.textContent = ""; r.models.forEach(m => pick.append(h("option", { value: m.slug }, m.name))); pick.value = r.model || ""; mlabel();
  });
  const acct = $("side").appendChild(h("div", { id: "acct" }));  // A2 complete (A6): the account card at the sidebar's foot (sidebar() keeps it)
  const LABEL = { Connecting: "연결 중…", Ready: "준비됨", Thinking: "생각 중…", Error: "오류" };
  let out = null, agentSt = "Connecting", authSt = { state: "signed_out" }, turning = false, stopping = false, wasReady = false;  // turning: an agent turn (a PDF ask cannot be stopped)
  let since = 0, tick = null, stick = true;  // working(): when the turn began, its clock; scroll(): the log follows its foot
  let talk = null;  // the task whose turn is running; its answer stays in that task's chat
  const gate = () => {
    const on = authSt.state === "connected", running = on && turning && agentSt === "Thinking";
    // B17: 연결 안 됨 / 준비됨 / 작업 중 · 확인 기다림 (a WARN card waits for the person)
    const waits = !!document.querySelector("#live [data-answer]");
    // demo 10/27: 작업 중 is said in the conversation (working()); the composer keeps only 중지하는 중…
    st.textContent = ""; st.append(...(!on ? ["연결 안 됨"] : agentSt === "Thinking" ? (stopping ? ["중지하는 중…"] : []) : [LABEL[agentSt] || agentSt]));
    working(waits);
    box.dataset.agent = agentSt;
    pick.hidden = !on || !pick.options.length; pick.disabled = agentSt === "Thinking";
    mbtn.hidden = pick.hidden; mbtn.disabled = pick.disabled; if (mbtn.hidden || mbtn.disabled) mmenu.hidden = true;
    inp.disabled = !on || !V || (agentSt !== "Ready" && agentSt !== "Error");  // Error: the next send restarts app-server
    btn.disabled = running ? stopping : inp.disabled;  // while the agent works, the send button is 중지
    // B17: a text button, 보내기 (black) / ■ 중지 (orange soft); it stays the composer's first button
    btn.replaceChildren(...(running ? [ico("stop", 12), "중지"] : ["보내기"])); btn.title = running ? "중지" : "보내기"; btn.setAttribute("aria-label", btn.title);
    box.dataset.running = running ? "1" : "";
    const d = V ? (M.desk || {})[V.task.id] || {} : {}, ps = d.papers || [], asks = ps.length && (!d.folder || d.route === "ask");
    if (agentSt === "Ready") wasReady = true;  // S4: connecting again after it was ready (a new token, a restart)
    inp.placeholder = !on ? (V ? "ChatGPT에 연결하면 대화할 수 있습니다" : "ChatGPT에 연결하고 작업을 만들면 대화할 수 있습니다") :  // 01: no task yet
      wasReady && agentSt === "Connecting" ? "다시 연결되면 보낼 수 있습니다"
      : !V ? "새 작업을 만들면 대화할 수 있습니다" : asks ? "논문에 묻기…" : "Pablo에게 요청하기…";
    hint.hidden = !on || !V || !box.dataset.stage;
    const filt = !hint.hidden && $("log").dataset.filter === box.dataset.stage;  // B14
    hint.replaceChildren(...(hint.hidden ? [] : ["· 이 메시지는 ", h("span", { class: "tg stage" }, box.dataset.stage), " 로 기록", filt ? " (거르는 중인 단계)" : ""]));
  };
  const status = (s, err) => { agentSt = s; st.title = err || ""; gate(); };
  gateHook = () => gate();
  const link = (text, on) => h("button", { class: "link", on }, text);
  // ⑤ a PC without PowerShell 7: Codex runs the agent's commands in Windows PowerShell 5.1, which reads 한글 and symbols
  // in a BOM-less UTF-8 file wrongly. Pablo tells the agent to read as UTF-8; this says so once, with how to install,
  // after the account is connected (review: nothing works before sign-in, so the sign-in card comes alone first)
  const shellBox = $("chat").insertBefore(h("div", { id: "shell-note" }), box);
  const copyLine = cmd => { const b = h("button", { class: "link", "data-copy": "1", on: () => {
      const ok = () => { b.textContent = "복사함"; setTimeout(() => { b.textContent = "복사"; }, 1500); };
      (navigator.clipboard ? navigator.clipboard.writeText(cmd) : Promise.reject()).then(ok, () => { const r = document.createRange(); r.selectNodeContents(c);
        getSelection().removeAllRanges(); getSelection().addRange(r); try { document.execCommand("copy"); ok(); } catch (e) {} }); } }, "복사"), c = h("code", null, cmd);
    return h("div", { class: "cmdline" }, c, b); };
  const PS7 = "https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows";
  const ps51 = (seen, title) => h("div", { class: "call", "data-shell": "5.1" }, h("p", { class: "head" }, title || "한글이 든 코드를 정확히 읽으려면 PowerShell 7이 필요합니다"),
    h("p", null, "지금은 Windows PowerShell 5.1로 실행합니다. 5.1은 한글이 든 코드를 다른 인코딩으로 읽어, 재현 점검에서 글자가 깨져 보일 수 있습니다. 작업과 대화는 그대로 할 수 있습니다."),
    copyLine("winget install Microsoft.PowerShell"),
    h("p", { class: "acts" }, seen, h("a", { class: "link", href: PS7, target: "_blank", rel: "noopener noreferrer" }, "설치 방법 ↗"),
      h("small", null, "설치한 뒤 Pablo를 다시 시작하면 7을 씁니다.")));
  // S20: once, above the composer, after the account is connected (nothing works before sign-in, so the sign-in card first)
  const shellNote = () => { const host = M.host || {}; shellBox.textContent = "";
    if (host.shell !== "powershell" || host.noticed || authSt.state !== "connected") return;
    shellBox.append(ps51(pabloHost.noticeSeen ? h("button", { class: "pill on", on: () => pabloHost.noticeSeen("shell").then(() => refresh()) }, "알겠습니다") : null)); };
  // B21 / S1–S4, S32–S35, S37: the account card, one state at a time in the same place. The second line of a connected card
  // is "플랜 사용 가능 · 설정"; 연결 해제 lives in 설정 · 계정. The words of a failure come from siwc.SAY (a.error), its title
  // and what to do next from its key (a.code)
  const PLAN = "https://openai.com/chatgpt/pricing/";
  const FAILS = { cancelled: ["로그인을 취소했습니다", "다시 시도"], access_denied: ["권한 승인을 거절했습니다", "다시 시도"],
    timeout: ["응답을 받지 못했습니다 · 시간이 지났습니다", "다시 시도"], state_mismatch: ["로그인 응답이 맞지 않습니다", "다시 시도"],
    callback_failed: ["로그인 응답을 받지 못했습니다", "다시 시도"], exchange_failed: ["로그인을 마치지 못했습니다", "다시 시도"],
    bad_id_token: ["로그인 응답을 검증하지 못했습니다", "다시 시도"], no_plan_permission: ["이 계정으로는 에이전트를 쓸 수 없습니다", "다른 계정으로 연결", 1],
    not_eligible: ["이 계정으로는 에이전트를 쓸 수 없습니다", "다른 계정으로 연결", 1], network: ["OpenAI에 연결하지 못했습니다", "인터넷 확인 뒤 다시 시도"],
    no_models: ["쓸 수 있는 모델이 없습니다", "다시 시도", 1], overloaded: ["모델이 지금 붐빕니다", "다시 시도"], usage_limit: ["사용 한도에 도달했습니다", "ChatGPT로 다시 연결"],
    refresh_failed: ["연결이 만료되었습니다", "ChatGPT로 다시 연결"], unauthorized: ["연결이 만료되었습니다", "ChatGPT로 다시 연결"],
    inference_failed: ["사용량 확인이 잠시 안 됩니다", "잠시 뒤 다시 시도"] };
  let rechecking = false, checkedAt = null, seenReady = false, hello = null, settingsDraw = null;
  const hhmm = d => new Date(d).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false });
  const paintAcct = () => {
    const a = authSt; acct.textContent = ""; acct.dataset.state = a.state; acct.dataset.error = a.error || "";
    const spin = () => h("span", { class: "spin", "aria-hidden": "true" });
    const card = (cls, title, sub, ...acts) => h("div", { class: "acard " + cls }, h("b", null, title), sub ? h("small", null, sub) : null,
      acts.filter(Boolean).length ? h("div", { class: "aacts" }, ...acts.filter(Boolean)) : null);
    const signin = (label, quiet) => h("button", { class: "pill" + (quiet ? "" : " on"), id: "signin", on: () => pabloHost.login() }, label);  // S3: 다른 계정으로 연결 is a plain pill
    if (hello) acct.append(hello);
    if (a.state === "connected" && box.dataset.agent === "Connecting" && seenReady)  // S4: the agent restarts (a fresh token, the same thread)
      acct.append(card("wait", [spin(), "ChatGPT · 다시 연결하는 중…"], "토큰을 갱신하고 같은 대화(thread)를 이어 갑니다. 보내려던 메시지는 입력창에 남아 있습니다."));
    else if (a.state === "connected") acct.append(card("on", "ChatGPT · 연결됨", ["플랜 사용 가능 · ",
      pabloHost.setUi ? h("button", { class: "link", "data-settings": "1", on: () => settings("account") }, "설정") : link("연결 해제", () => pabloHost.logout())]));
    else if (a.state === "signing_in") acct.append(card("wait", [spin(), "브라우저에서 승인을 기다리는 중…"],  // S1
      "시스템 브라우저 창에서 ChatGPT 로그인을 마치면 자동으로 돌아옵니다. 최대 5분.", h("button", { class: "pill", "data-login-cancel": "1", on: () => pabloHost.cancelLogin() }, "취소")));
    else if (a.state === "verifying") acct.append(card("wait", [spin(), rechecking ? "ChatGPT 플랜을 다시 확인하는 중…" : "ChatGPT 플랜 사용 권한을 확인하는 중…"],  // S32
      rechecking ? "몇 초 걸립니다. 그동안에도 작업은 그대로입니다." : "로그인은 끝났습니다. 몇 초 걸립니다."));
    else if (a.error && /세션 해제/.test(a.error) && !a.code)  // S35
      acct.append(card("off", "이 기기의 연결은 지웠습니다", a.error, signin("ChatGPT로 계속하기")));
    else if (a.error) { const f = FAILS[a.code] || ["연결하지 못했습니다", "다시 시도"];  // S2, S3, S34, S37
      acct.append(card("bad", f[0], a.error, signin(f[1], f[2]), f[2] ? h("a", { class: "link", href: PLAN, target: "_blank", rel: "noopener noreferrer" }, "플랜 안내 ↗") : null,
        a.state === "error" ? link("연결 해제", () => pabloHost.logout()) : null)); }
    else acct.append(card("off", "ChatGPT · 연결 안 됨", "연결해야 에이전트와 논문 질문을 쓸 수 있습니다", signin("ChatGPT로 연결")));
  };
  function account(a) {
    const was = authSt.state;
    if (a.state === "connected" && (was === "signing_in" || was === "verifying") && !rechecking) {  // S33: just signed in, said for 8 s
      const x = hello = h("div", { class: "hello", "data-hello": "1" }, h("span", { class: "hav" }, art("waving", "pose")),
        h("p", null, h("b", null, "ChatGPT에 연결되었습니다"), h("small", null, "이제 대화할 수 있습니다.")));
      setTimeout(() => { if (hello === x) { hello = null; x.remove(); } }, 8000); }
    if (a.state === "connected") checkedAt = new Date();
    if (a.state !== "verifying") rechecking = false;
    if (a.state !== "connected") seenReady = false;
    authSt = a; paintAcct();
    gate(); shellNote();
    if (!V && $("log").querySelector(".empty")) empty();  // the first-run steps follow the account
    if ($("settings") && settingsDraw) settingsDraw();
  }
  // S4 reads the agent's own state (the composer's data-agent), so the card follows a restart without touching gate()
  new MutationObserver(rs => { if (rs.every(r => r.oldValue === (box.dataset.agent || null))) return;
    if (box.dataset.agent === "Ready" && authSt.state === "connected") seenReady = true; paintAcct(); })
    .observe(box, { attributes: true, attributeFilter: ["data-agent"], attributeOldValue: true });
  // demo 10/27: the log follows new messages while it is at its foot; scrolled up, it stays where the person put it
  // until they come back down (or send something)
  // demo 10/28: only the person's own scrolling (wheel, keys, the scrollbar, touch) lets go of the foot; anything that
  // makes the log longer (a streamed word, a card, a re-render, the working line's clock) keeps it at the foot meanwhile
  const L0 = $("log"); let touched = 0, pinning = 0;
  const pin = () => { if (pinning) return; pinning = requestAnimationFrame(() => { pinning = 0; if (stick) L0.scrollTop = L0.scrollHeight; }); };
  ["wheel", "touchmove", "pointerdown"].forEach(t => L0.addEventListener(t, () => { touched = Date.now(); }, { passive: true }));
  L0.addEventListener("keydown", e => { if (/^(PageUp|PageDown|Home|End|ArrowUp|ArrowDown| )$/.test(e.key)) touched = Date.now(); });
  L0.addEventListener("scroll", () => { if (Date.now() - touched < 1200) stick = L0.scrollHeight - L0.scrollTop - L0.clientHeight < 60; }, { passive: true });
  new MutationObserver(pin).observe(L0, { childList: true, subtree: true, characterData: true });
  new ResizeObserver(pin).observe(L0);
  const scroll = force => { if (force === true) stick = true; working(); if (stick) L0.scrollTop = L0.scrollHeight; };
  // demo 10/27: while the agent works, the conversation's foot says so: 작업 중 · m:ss, and what it is on now (the last
  // line it wrote, or that a card waits for 진행 / 취소). It stays the last thing in the task's conversation
  function working(waits) {
    let w = $("working");
    if (!(turning && agentSt === "Thinking" && talk)) { if (w) w.remove(); clearInterval(tick); tick = null; since = 0; return; }
    if (waits === undefined) waits = !!document.querySelector("#live [data-answer]");
    if (!since) since = Date.now();
    if (!tick) tick = setInterval(() => working(), 1000);
    const l = live(talk);
    // demo 10/28: the thinking character beside the spinner (made once, so its motion is not restarted every second)
    if (!w) { w = msg("Pablo", null, h("div", { class: "wk" }, art("think", "bob"), h("div", { class: "wk-b" }))); w.id = "working"; w.classList.add("working"); }
    if (l.lastElementChild !== w) l.append(w);
    // what it said last: its last paragraph (wrapped, 3 lines at most on screen), not only the last line
    const s = Math.floor((Date.now() - since) / 1000), said = out ? out.textContent.trim().split(/\n\s*\n/).filter(x => x.trim()).pop() || "" : "";
    const pg = [...l.querySelectorAll(".prog .pg-t")].pop();  // 재현 점검 / 조건 뽑기: their progress card's line
    const now = waits ? "확인 카드에서 진행할지 기다립니다" : said ? said.trim().replace(/[`*]/g, "") : pg && pg.textContent ? pg.textContent : "요청을 읽고 계획하는 중…";
    w.querySelector(".wk-b").replaceChildren(h("p", { class: "wk-h" }, h("span", { class: "spin", "aria-hidden": "true" }),
      h("b", null, stopping ? "중지하는 중" : "작업 중"), h("span", { class: "muted" }, ` · ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`)),
      h("p", { class: "wk-t", title: now }, now));
  }
  pabloHost.onAuth(account);
  pabloHost.onAgent(ev => {
    if (ev.type === "model") { pick.value = ev.model; mlabel(); }
    if (ev.type === "progress") { const b = live(ev.task).querySelector(ev.what === "spec" ? "[data-specing]" : "[data-auditing]"); if (b && b._prog) b._prog(ev); }
    if (ev.type === "status") {
      if (ev.status === "Ready") models().then(gate);  // after a restart or another sign-in the list may change
      // a message is on its way (Pablo prepares it, or app-server restarts for a fresh token first): stay Thinking until done
      if (turning && (ev.status === "Ready" || ev.status === "Connecting")) return;
      status(ev.status, ev.error);
      if (ev.status === "Error" && ev.error && authSt.state === "connected") live(talk).append(msg("Pablo", null, failCard("실행하지 못했습니다", ev.error))), scroll();
    } else if (ev.type === "delta" && out) { out.textContent += ev.text; scroll(); }
    else if (ev.type === "done") {
      refresh(); turning = stopping = false; busy = null; gate();
      if (out && ev.status === "interrupted") out.after(stopped());
      const lg = ev.logged;  // the keys main just wrote: the turn's messages get their tag row now, not after the next state read
      if (lg && V && lg.task === V.task.id && lives[lg.task]) {
        if (lg.user) tagLive([...lives[lg.task].querySelectorAll(":scope > .msg.user")].at(-1), "user", lg.user);
        if (out) tagLive(out.closest(".msg"), "agent", lg.agent);
      }
      if (out) { out.title = `첫 토큰 ${ev.first ?? "-"} ms · 전체 ${ev.total} ms`; out = null; }
      // B22 / S9: 다른 모델로 다시 시도 on the error card itself (else on its own line)
      if (ev.retry) setTimeout(() => { const b = h("button", { class: "pill on", "data-retry": "1", on: () => { b.remove(); stream(talk); pabloHost.retry().catch(e => { status("Error", e.message); out = null; }); } }, "다른 모델로 다시 시도");
        const card = [...live(talk).querySelectorAll(".call.fail")].at(-1);
        if (card) card.append(h("p", { class: "acts" }, b, h("span", { class: "muted" }, "아무것도 실행되지 않았습니다.")));
        else live(talk).append(msg("Pablo", null, h("p", null, b)));
        scroll(); });  // after the Error card
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
      if (card) card.insertBefore(h("p", { class: "rev", "data-review": ev.alignment || "" }, ev.alignment ? h("span", { class: "tg rv rv-" + ev.alignment }, BADGE[ev.alignment] || ev.alignment) : null,
        h("span", null, "검토: " + (ALIGN[ev.alignment] || (ev.executed ? "실행했습니다" : "실행하지 않았습니다")))), card.querySelector(":scope > .foot"));
      refresh();  // Plan / 왜? follow the review without a reload
    }
  });
  // M4.2 Guard on the agent's actions: ALLOW stays silent; WARN asks, BLOCK and failures explain (no rule/action ids)
  const HEAD = { WARN: "이 작업은 현재 기준과 충돌할 수 있습니다", BLOCK: "Pablo가 이 작업을 막았습니다", ERROR: "작업을 실행하지 못했습니다" };
  // B8 / S38: the live card; a badge heads WARN (확인 필요) and BLOCK (막음, .lock); ERROR is a grey card with an info mark.
  // A WARN on a command in a task without a paper is compact: the command, why, [진행][취소]
  function guard(ev) {
    const cmd = ev.verdict === "WARN" && /^명령 실행: /.test(ev.text || "") && kindFor((M.desk || {})[ev.task]) === "general";
    const foot = h("div", { class: "foot" }, tech(ev.text, korean(ev.reason) ? null : ev.reason),
      ev.act ? h("button", { class: "link", on: () => show({ mode: "trace", act: ev.act }) }, "왜 그런가요?") : null);
    const card = h("div", { class: "call guard" + (ev.verdict === "WARN" ? " warn" + (cmd ? " compact" : "") : ev.verdict === "BLOCK" ? " block lock" : " block fail"),
        "data-verdict": ev.verdict, "data-act": ev.act || "" },
      h("p", { class: "head" }, ev.verdict === "ERROR" ? [ico("info", 14), " "] : null,
        cmd ? ["명령: ", h("code", null, shell((ev.text || "").split("\n")[0].replace(/^명령 실행: /, "")))] : HEAD[ev.verdict]),
      cmd ? null : h("p", null, "제안된 작업: ", h("b", null, meaning(ev.text))),
      cmd ? null : ev.verdict === "ERROR" ? preview((ev.text || "").split("\n")[0]) : preview(ev.text, ev.detail), ev.verdict === "ERROR" ? null : current(ev.text, ev.task),
      reason(ev.reason, ev.verdict === "BLOCK"), h("p", { class: "muted crit" }), foot);
    if (ev.verdict !== "WARN") return card;
    const row = h("p", { class: "acts" }), answer = yes => pabloHost.decide(ev.id, yes)
      .then(() => { row.textContent = yes ? "진행했습니다." : "취소했습니다."; }, () => { row.textContent = "이미 끝난 요청입니다."; });
    row.append(h("button", { class: "pill on", "data-answer": "proceed", on: () => answer(true) }, "진행"), " ",
      h("button", { class: "pill", "data-answer": "cancel", on: () => answer(false) }, "취소"));
    card.insertBefore(row, foot);
    return card;
  }
  const stream = t => { out = h("p", { class: "stream", style: "white-space:pre-wrap" }); live(t).append(msg("Pablo", null, out)); scroll(); };
  // Thinking (and 중지) from the moment it is sent: Pablo records the message's criteria and the brief before the agent starts
  const chat = (text, t) => { talk = busy = t; turning = true; stream(t); status("Thinking");
    pabloHost.chat(text, t).catch(e => { turning = false; busy = null; status("Error", fail(e)); out = null; }); };
  const stop = () => { stopping = true; gate(); pabloHost.stop().then(ok => { if (!ok) { stopping = false; gate(); } }); };
  // M5.1 one input box: the task's material and folder decide where a message goes; both -> the user picks, neither -> say so
  const send = async () => {
    const text = inp.value.trim(); if (!text || inp.disabled) return;
    talk = V.task.id;
    if (!M.desk) { inp.disabled = true; await refresh(); gate(); }  // the task's folder / PDF come with the first state read
    const d = (M.desk || {})[talk] || {}, pdf = (d.papers || []).length > 0 || (!M.desk && M.pdf), dir = !!d.folder;
    if (!pdf && !dir) {  // S22 (S10 for a paper-reading task): nowhere to send it; the words stay in the box
      live(talk).querySelectorAll("[data-route=none]").forEach(x => x.closest(".msg").remove());
      const read = kindFor(d) === "read";
      live(talk).append(msg("Pablo", null, h("div", { class: "call", "data-route": "none" }, h("p", { class: "head" }, read ? "먼저 자료를 추가하세요" : "먼저 자료나 작업 폴더를 정해 주세요"),
        h("p", { class: "muted" }, read ? "이 작업에는 논문이 없습니다. 질문은 입력창에 남아 있습니다." : "논문 질문은 자료가, 에이전트는 작업 폴더가 있어야 보낼 수 있습니다. 보내려던 글은 입력창에 남아 있습니다."),
        h("p", { class: "acts" }, h("button", { class: "pill" + (read ? " on" : ""), on: () => pickPdfs() }, ico("file", 14), read ? "PDF 고르기" : "PDF 추가"),
          read ? h("button", { class: "pill", on: () => addSource && addSource() }, "arXiv · DOI로 가져오기")
            : h("button", { class: "pill", on: () => attach("pickFolder") }, ico("folder", 14), "작업 폴더 고르기"))))); scroll(); return;
    }
    inp.value = ""; grow();
    live(talk).append(msg("You", new Date().toISOString(), h("p", { style: "white-space:pre-wrap" }, text))); scroll(true);
    if (pdf && !dir) return ask(text, talk);
    if (dir && !pdf) return chat(text, talk);
    if (pdf && dir) return (d.route === "ask" ? ask : chat)(text, talk);  // both: the task's 보낼 곳 (agent by default)
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
  let srcOpen = false, shownTask = null, cardOpen = null;  // cardOpen: the chip whose part of the card is open (src | dir | net)  // ② the source list, when it is folded into "자료 N개"; the task the box belongs to
  cardClose = () => { cardOpen = null; const c = $("srccard"); if (c) c.hidden = true; document.querySelectorAll(".hchip").forEach(x => x.setAttribute("aria-expanded", "false")); };
  // S24 and the like: a notice under the header (what happened, nothing changed, what to do next); one at a time
  const noticeBox = $("chat").insertBefore(h("div", { id: "notice" }), $("log"));
  const notice = el => noticeBox.replaceChildren(...(el ? [el] : []));
  const attach = kind => pabloHost[kind](V.task.id).then(name => { notice(null); return name && refresh(); },
    e => notice(h("div", { class: "call nb", "data-folder-refused": "1" },
      h("p", { class: "head" }, /겹치지 않는/.test(clean(e)) ? "이 폴더는 작업 폴더로 쓸 수 없습니다" : "작업 폴더를 바꾸지 못했습니다"),
      h("p", null, clean(e), " 작업 폴더는 바뀌지 않았습니다."),
      h("p", { class: "acts" }, h("button", { class: "pill", "data-pick-again": "1", on: () => attach(kind) }, ico("folder", 14), "다른 폴더 고르기"),
        h("button", { class: "link", on: () => notice(null) }, "닫기")))));
  // ⋯ / the folder chip: the task's own folder in the file manager
  openWork = pabloHost.openWork ? t => pabloHost.openWork(t).catch(e => notice(h("div", { class: "call nb" }, h("p", { class: "head" }, "작업 폴더를 열지 못했습니다"),
    h("p", null, clean(e)), h("p", { class: "acts" }, h("button", { class: "link", on: () => notice(null) }, "닫기"))))) : null;
  // C1/C2: + 추가 -> a PDF file, or an arXiv id / link that main downloads (one row under the tools)
  const adder = $("chat").insertBefore(h("div", { id: "adder", hidden: true }), box);
  // D1/D2: the same box takes an arXiv id or link (C2), a web page's address (D1), or words to find a paper (D2)
  const arx = h("input", { id: "arxiv", placeholder: "arXiv 번호·링크, OpenReview·DOI, 웹 문서 주소(여러 개 가능), 또는 찾을 말" }), note = h("span", { id: "arxiv-note" });
  const hits = h("div", { id: "arxiv-hits", hidden: true }), lines = h("ul", { id: "arxiv-lines", hidden: true }), dl = h("div", { id: "arxiv-dl", hidden: true });
  const ARXIV = /^(arxiv:|(https?:\/\/)?(www\.|export\.)?arxiv\.org\/)|^\d{4}\.\d{4,5}(v\d+)?$|^[a-z][a-z-]*(\.[A-Z]{2})?\/\d{7}(v\d+)?$|^(https?:\/\/(dx\.)?doi\.org\/|doi:\s*)?10\.48550\/arxiv\./i;  // ⑬ arXiv's own DOI too
  const moved = m => { const n = Object.values(m).reduce((a, b) => a + b, 0);
    return n ? ` 이전 버전에서 찾은 근거 ${n}개: 그대로 ${m.VALID || 0} · 문맥 바뀜 ${m.STALE || 0} · 찾을 수 없음 ${m.UNRESOLVED || 0}.` : ""; };
  const prog = h("span", { class: "ad-prog", hidden: true }, h("i"));
  const step = (i, n) => { prog.hidden = n < 2; prog.firstChild.style.width = Math.round(i / n * 100) + "%"; };
  const hold = on => { get.disabled = find.disabled = on; adder.classList.toggle("busy", on); if (!on) prog.hidden = true; };
  // ② several at once: one line per item (✓ added / ⚠ why not) under the box, and a count in the note
  const report = (rows, what) => {  // rows: [ok | same | bad, text]; one already there is not counted as added
    lines.textContent = ""; lines.hidden = !rows.length;
    rows.forEach(([st, text]) => lines.append(h("li", { class: st === "bad" ? "bad" : st === "same" ? "ok same" : "ok" }, text)));
    const n = rows.filter(([st]) => st === "ok").length, same = rows.filter(([st]) => st === "same").length;
    note.textContent = `${what} ${rows.length}개 중 ${n}개를 추가했습니다${same ? `(${same}개는 이미 있음)` : ""}.`;
  };
  const fresh = () => { lines.textContent = dl.textContent = ""; lines.hidden = hits.hidden = dl.hidden = true; };  // one action's result at a time
  // picked or dropped PDFs: one at a time, so the note says how far it got ("3개 중 2번째") and a slow one is visible
  async function addPaths(paths) {
    adder.hidden = false; fresh(); hold(true); const rows = [];
    for (const [i, p] of paths.entries()) { step(i, paths.length);
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
    for (const [i, v] of vs.entries()) { step(i, vs.length);
      note.textContent = `${vs.length}개 중 ${i + 1}번째를 가져오는 중…`;
      try { const r = await one(v, doi); rows.push([r.same ? "same" : "ok", `✓ ${label(r)}${r.same ? " (이미 있음)" : ""}${r.moved ? " ·" + moved(r.moved) : ""}`]); }
      catch (e) { rows.push(["bad", `⚠ ${v}: ${fail(e)}`]); }
    }
    hold(false); arx.value = ""; report(rows, "자료"); refresh();
  }
  const fetchArxiv = (v = arx.value.trim(), foundBy, sure) => {
    if (!v || get.disabled) return;
    const parts = v.replace(/arxiv:\s+/gi, "arxiv:").split(/[\s,;]+/).filter(Boolean);
    if (parts.length > 1 && parts.every(item)) return batch(parts);  // ② several ids / links / addresses
    if (!ARXIV.test(v) && DOI.test(v) && pabloHost.lookupDoi) return doi(v);
    const or = !ARXIV.test(v) && OPENREVIEW.test(v) && !!pabloHost.addOpenreview, web = !ARXIV.test(v) && !or && /^https?:\/\//i.test(v);
    if (!web && !or && !ARXIV.test(v)) return search();  // words: find the paper first
    if (!web && !or && !sure && pabloHost.peekArxiv) {  // B24 / S12: the file, where from and how big, then 받기 · 취소
      hold(true); fresh(); note.textContent = "arXiv에서 받을 파일을 확인하는 중…";
      return pabloHost.peekArxiv(v).then(p => { hold(false); note.textContent = ""; dl.hidden = false;
        dl.replaceChildren(downloadCard(p, () => { dl.hidden = true; fetchArxiv(v, foundBy, true); },
          () => { dl.hidden = true; note.textContent = "받지 않았습니다. 자료는 그대로입니다."; })); },
        e => { hold(false); note.textContent = "⚠ " + fail(e); });
    }
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
      const many = h("button", { class: "pill on", id: "arxiv-many", disabled: true, on: () => picked().length && batch(picked(), doi) }, "고른 논문 가져오기");
      const have = new Set((((M.desk || {})[V.task.id] || {}).papers || []).map(p => p.arxiv).filter(Boolean));  // already a source here
      hits.append(h("p", { class: "muted", "data-sent": "1" }, sent || "검색어를 arXiv(export.arxiv.org)로 보냈습니다. arXiv의 요청 제한 때문에 3초에 한 번까지 찾습니다."),
        ...rs.map(x => h("div", { class: "hit", "data-hit": x.id, title: x.summary || null },
          have.has(x.id) ? null : [h("input", { type: "checkbox", "data-pick": x.id, title: "여러 개 골라 한 번에 가져오기" }), " "],
          h("b", null, x.title), " ", h("small", { class: "muted" }, `${x.authors} · ${x.year} · arXiv ${x.id}${x.version || ""}`), " ",
          have.has(x.id) ? h("small", { class: "have", "data-have": "1" }, "✓ 자료에 있음")
            : h("button", { class: "link", "data-import": x.id, on: () => fetchArxiv(x.id, doi) }, "가져오기"),
          x.summary ? h("div", { class: "sum" }, x.summary) : null)), h("div", { class: "ad-foot" }, many,
          h("button", { class: "pill", "data-adder-close": "1", on: () => { adder.hidden = true; } }, "닫기"),
          h("small", null, "받은 PDF는 이 작업의 자료가 됩니다. 아무것도 고르지 않으면 바뀌는 것이 없습니다.")));
      hits.addEventListener("change", () => { const n = picked().length; many.disabled = !n; many.textContent = n ? `고른 ${n}개 가져오기` : "고른 논문 가져오기"; });
    }
  };
  const get = h("button", { class: "pill", id: "arxiv-get", on: () => fetchArxiv() }, "가져오기");
  const find = h("button", { class: "pill", id: "arxiv-find", title: "검색어가 arXiv(export.arxiv.org)로 보내집니다. 3초에 한 번까지 찾습니다.", on: search }, ico("search", 14), "arXiv에서 찾기");
  arx.addEventListener("keydown", e => { if (e.key === "Enter" && !e.isComposing) fetchArxiv(); });
  find.classList.add("on");
  adder.append(h("div", { class: "ad-head" }, h("b", null, "자료 추가"), h("small", null, "PDF · arXiv · DOI · OpenReview · 웹 문서"),
      h("button", { class: "x", title: "닫기", "aria-label": "닫기", on: () => { adder.hidden = true; } }, ico("x"))),
    h("div", { class: "ad-row" }, ...[h("button", { class: "link ad-pdf", title: "여러 개를 한 번에 고를 수 있습니다", on: pickPdfs }, ico("file", 14), "PDF 파일 고르기"),
      h("span", { class: "or" }, "또는"), arx, get, pabloHost.searchArxiv ? find : null].filter(Boolean)), h("span", { class: "ad-note" }, prog, note), dl, lines, hits);
  // ② PDFs dropped anywhere on the window become the open task's sources (preload gives each file's path; main checks it)
  if (pabloHost.addFiles && pabloHost.pathOf) {
    const files = e => [...((e.dataTransfer || {}).types || [])].includes("Files");
    const dn = h("span", { class: "dc-n" }), cover = $("chat").appendChild(h("div", { id: "drop-cover", "aria-hidden": "true" },
      h("div", { class: "dc-in" }, h("span", { class: "dc-ico" }, ico("file", 22)), h("b", null, "PDF를 놓으면 이 작업의 자료로 추가합니다"),
        h("small", null, "여러 개를 한 번에 놓을 수 있습니다 · PDF가 아닌 파일은 받지 않습니다 · 50 MB까지"), dn)));
    addEventListener("dragover", e => { if (!V || !files(e)) return; e.preventDefault();
      if (!document.body.classList.contains("dropping")) { const L = $("log"); cover.style.top = L.offsetTop + 8 + "px"; cover.style.height = Math.max(120, L.clientHeight - 16) + "px"; }
      const n = ((e.dataTransfer || {}).items || []).length; dn.textContent = n ? `${n}개 파일을 끌고 있음` : ""; dn.hidden = !n;
      document.body.classList.add("dropping"); });
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
    const t = V.task.id, card = h("div", { class: "call done-ask", "data-done-ask": "1" }, h("p", { class: "head" }, "이 작업을 완료로 옮길까요?"),
      h("p", null, "보고서를 저장했습니다. 완료로 옮기면 사이드바 '완료' 묶음으로 접힙니다. 대화와 기록은 그대로이고, ⋯ 메뉴의 '완료 풀기'로 되돌릴 수 있습니다."),
      h("p", { class: "acts" }, h("button", { class: "pill on", "data-done-go": "1", on: () => pabloHost.setUi(t, "done", true).then(() => { card.closest(".msg").remove(); return refresh(); }) }, ico("check-circle", 14), "완료로 옮기기"),
        h("button", { class: "pill", "data-done-later": "1", on: () => card.closest(".msg").remove() }, "나중에")));
    live(t).append(msg("Pablo", null, card)); scroll(); };
  // 0.8 review: 다시 뽑기 says first what it replaces and what it keeps (extractions differ from run to run)
  const redo = () => {
    const live = V.research.map(id => V.checks[id]).filter(k => k.spec && k.state !== "waived");
    const own = live.filter(k => k.spec.by === "user" || k.spec.kept).length, dev = live.filter(k => devOf(k)).length;
    const outn = V.research.map(id => V.checks[id]).filter(k => k.spec && k.state === "waived" && k.waived_by === "user").length;
    const box = h("div", { class: "call", "data-redo-ask": "1" }, h("p", { class: "head" }, "재현 조건을 다시 뽑을까요?"),
      h("p", { class: "muted" }, "Pablo가 뽑은 조건은 새로 뽑은 목록으로 바뀝니다. 뽑을 때마다 조금씩 다를 수 있어, 이번에 빠진 조건은 되살릴 수 있게 남겨 둡니다.",
        own || dev ? ` 직접 더하거나 되살린 조건 ${own}개와 의도한 차이로 둔 조건 ${dev}개는 그대로 둡니다.` : "",
        outn ? ` 이전에 뺀 조건 ${outn}개는 다시 넣지 않습니다.` : ""),
      h("p", null, h("button", { class: "pill on", "data-redo-go": "1", on: () => { box.closest(".msg").remove(); spec(V.task.id); } }, "다시 뽑기"), " ",
        h("button", { class: "link", on: () => box.closest(".msg").remove() }, "취소")));
    live_(V.task.id).append(msg("Pablo", null, box)); scroll(); };
  const live_ = t => live(t);
  specAgain = () => redo();  // B10: the conditions card's own 다시 뽑기 (asks first)
  // B17: 보낼 곳 is always in the composer (after the send button: it stays the first button). A side with nothing to send to
  // is off and says why; with both, the task's choice (agent by default)
  const route = () => { box.querySelectorAll("#route").forEach(x => x.remove()); if (!V || !pabloHost.setRoute) return;
    const d = (M.desk || {})[V.task.id] || {}, ps = d.papers || [], dir = !!d.folder, cur = ps.length && (!dir || d.route === "ask") ? "ask" : dir ? "agent" : "";
    const why = { agent: dir ? null : "작업 폴더를 고르면 에이전트에게 보낼 수 있습니다", ask: ps.length ? null : "자료를 추가하면 논문에 물을 수 있습니다" };
    box.append(h("span", { id: "route", title: "에이전트는 논문 조건과 확인된 근거를 알고 작업 폴더에서 일합니다. 논문 질문은 PDF에서 근거를 찾아 답합니다." },
      "보낼 곳 ", h("span", { class: "seg" }, ...[["agent", "에이전트"], ["ask", "논문 질문"]].map(([r, label]) => cur === r ? h("b", { "data-route": r }, label)
        : h("button", { class: "link", disabled: why[r] ? true : null, title: why[r], "data-route-to": r, on: () => pabloHost.setRoute(V.task.id, r).then(() => refresh()) }, label)))));
    gate(); };
  addSource = () => { adder.hidden = false; arx.focus(); };  // B12: + 논문 추가
  // A2 complete: the header's three chips (자료 · 폴더 · 인터넷), each opening its part of one card (#srccard: #src, #dir,
  // #net, same ids and contents as before); the stage bar (stagesOf; a filtered stage says "거르는 중 · N"); the view bar
  // with what the conversation is filtered by, or "거르기 없음"
  tools = () => {
    bar.textContent = "";
    if (!V) { adder.hidden = true; notice(null); return; }
    if (shownTask !== V.task.id) { shownTask = V.task.id; fresh(); note.textContent = ""; arx.value = ""; notice(null); cardOpen = null; }  // another task's results never stay
    const d = (M.desk || {})[V.task.id] || {}, ps = d.papers || [], main = ps.find(p => p.primary);
    const pdfs = ps.filter(p => p.kind !== "web"), several = pdfs.length > 1;  // D1: a web page is asked, never reproduced or a row
    const hasSpec = V.research.some(id => V.checks[id].spec && V.checks[id].state !== "waived");
    const kind = kindFor(d), st = stagesOf(V, d, kind);  // D1: the steps and what their actions need
    // ② more than 3 sources: one line "자료 N개 (주 논문 X) ▾", the list opens below it (one per line)
    const many = ps.length > 3, open = !many || srcOpen;
    // F18: a row is its PDF / WEB mark (CSS), the name and version, 주 논문, a line of what it is; its actions show on hover
    const pmeta = p => { const pg = ((M.papers || {})[p.id] || {}).pages, ev = Object.values(M.anchors || {}).filter(a => a.source === p.id).length;
      return [p.kind === "web" ? "웹 문서 · 캡처본" : p.arxiv ? `arXiv ${p.arxiv}` : "PDF", pg ? `${pg}쪽` : null, ev ? `근거 ${ev}` : null].filter(Boolean).join(" · "); };
    const chip = p => h("span", { class: "paper", "data-paper": p.id, "data-kind": p.kind || "pdf" },
        h("span", { class: "ptitle" }, p.kind === "web" ? h("span", { title: "웹 문서" }, "🌐 ") : null,
          ...(name => p.kind !== "web" && (M.papers || {})[p.id] ? [h("button", { class: "link", "data-open-paper": p.id,
            title: "PDF 열기 (문장을 골라 재현 조건으로 더할 수 있습니다)", on: () => { cardClose(); show({ mode: "paper", src: p.id }); } }, name)] : [h("span", { class: "pname" }, name)])(
            [h("b", null, p.title), p.version ? h("small", null, " " + p.version) : null]),
          several && p.kind !== "web" && p.primary ? h("small", { class: "ptag", "data-primary": "1" }, "주 논문") : null),
        h("span", { class: "pacts" }, p.kind !== "web" ? renamer(p.id, p.title, V.task.id) : null,
          ...codeOf(p.id).filter(x => x.official).map(x => [" ", h("a", { class: "code", href: x.url, target: "_blank", rel: "noopener noreferrer",
            "data-code": p.id, title: `논문의 공식 코드 (논문 p.${x.page}): ${x.url}` }, "코드 ↗")]),
          several && p.kind !== "web" && !p.primary ? [" ", h("button", { class: "link", title: "이 논문을 재현 대상으로 (재현 조건은 주 논문에서 뽑습니다)", "data-make-primary": p.id,
              on: () => pabloHost.setPrimary(V.task.id, p.id).then(() => refresh()) }, "주 논문으로")] : null,
          h("button", { class: "rm", title: "자료에서 빼기 (찾은 근거 기록은 남습니다)", "aria-label": "자료에서 빼기", "data-remove": p.id,
            on: () => pabloHost.removeSource(V.task.id, p.id).then(() => refresh()) }, "×")),
        h("small", { class: "pmeta" }, pmeta(p)));
    const srcEl = h("span", { id: "src", class: many ? "many" : null }, h("span", { class: "sc-lbl" }, "📎 자료: "),
        many ? h("button", { class: "link", id: "src-toggle", on: () => { srcOpen = !srcOpen; tools(); } },
          `${ps.length}개${main ? ` (주 논문 ${main.title})` : ""} ${open ? "▴" : "▾"}`) : null,
        ps.length ? h("span", { class: "plist", hidden: !open }, ps.map(p => chip(p))) : h("span", { class: "sc-none" }, "없음"), " ",
        h("span", { class: "sc-add" }, pabloHost.addArxiv ? h("button", { class: "link", "data-add-source": "1", on: () => { cardClose(); adder.hidden = false; arx.focus(); } }, "+ 추가")
          : link("PDF 추가", pickPdfs), h("small", null, "PDF · arXiv · DOI · OpenReview · 웹 주소")));
    const mi = (icon, label, on, attrs, ...tail) => h("button", { class: "mi", ...(attrs || {}), on }, ico(icon), h("span", null, label), ...tail);
    // S13 / S14: the folder (its first button picks one, as before)
    const dirEl = h("div", { id: "dir" }, h("span", { class: "sc-lbl" }, "📁 작업 폴더: "), d.folder
      ? [h("div", { class: "sc-path" }, h("small", null, "작업 폴더"), h("code", null, d.folder)),
         mi("swap", "폴더 바꾸기", () => { cardClose(); attach("pickFolder"); }, { "data-pick-folder": "1" }),
         openWork ? mi("folder", "탐색기에서 열기", () => { cardClose(); openWork(V.task.id); }, { "data-open-work": "1" }) : null,
         h("p", { class: "mfoot" }, "작업 폴더 밖의 파일은 읽지도 바꾸지도 않습니다. 체크포인트는 이 폴더만 저장합니다.")]
      : [h("b", null, "작업 폴더가 없습니다"), h("p", null, "논문 질문은 할 수 있습니다. 구현·실행과 재현 점검은 폴더가 있어야 열립니다."),
         h("button", { class: "pill on", "data-pick-folder": "1", on: () => { cardClose(); attach("pickFolder"); } }, ico("folder", 14), "작업 폴더 고르기")]);
    // S15: 인터넷 (with a folder: it is about the agent's commands); 기본 = the new tasks' default in 설정
    const netEl = d.folder && pabloHost.setNet ? h("div", { id: "net", "data-on": d.net ? "1" : "", role: "menu" }, h("span", { class: "sc-lbl" }, "🌐 인터넷: "),
        ...[[false, "globe-off", "차단"], [true, "globe", "허용"]].map(([on, icon, label]) => mi(icon, label,
          () => on === !!d.net ? cardClose() : pabloHost.setNet(V.task.id, on).then(() => refresh()),
          { class: "mi" + (on === !!d.net ? " sel" : ""), "data-net": on ? "on" : "off", role: "menuitemradio", "aria-checked": String(on === !!d.net) },
          !!(M.settings || {}).net === on ? h("small", null, "기본") : null, on === !!d.net ? ico("check", 14) : null)),
        h("p", { class: "mfoot" }, "허용해도 명령은 하나하나 Guard를 거칩니다. 이 작업에만 적용되고, 새 작업의 기본값은 설정에서 바꿉니다.")) : null;
    if (!netEl && cardOpen === "net") cardOpen = null;
    const specEl = st.can.spec && pabloHost.spec ? h("span", { id: "specs", title: several ? "재현 조건은 주 논문 한 편에서 뽑습니다. 다른 논문에서 다시 뽑으면 이전 조건을 대체합니다." : null },
        link((hasSpec ? "📋 재현 조건 다시 뽑기" : "📋 재현 조건 뽑기") + (several && main ? ` (${main.title})` : ""), () => hasSpec ? redo() : spec(V.task.id))) : null;
    const compEl = st.can.compare && pabloHost.compare ? h("span", { id: "compares" }, link("📊 비교표", () => compareForm(V.task.id))) : null;
    const routeEl = ps.length && d.folder && pabloHost.setRoute ? h("span", { id: "route", title: "에이전트는 논문 조건과 확인된 근거를 알고 작업 폴더에서 일합니다. 논문 질문은 PDF에서 근거를 찾아 답합니다." },
        "보낼 곳 ", h("span", { class: "seg" }, ...[["agent", "에이전트"], ["ask", "논문 질문"]].map(([r, label]) =>  // A2: a segmented control
          (d.route || "agent") === r ? h("b", { "data-route": r }, label) : link(label, () => pabloHost.setRoute(V.task.id, r).then(() => refresh()))))) : null;
    const auditEl = st.can.audit && pabloHost.audit ? h("span", { id: "audits" }, link("🔎 재현 점검", () => audit(V.task.id))) : null;
    // ⑫ / A13: the report opens the export dialog (parts, format, place) instead of saving at once
    const reportEl = pabloHost.report && st.can.report ? h("span", { id: "reports" }, link("📄 보고서", () => reportDlg(V.task.id))) : null;
    const card = h("div", { class: "srccard", id: "srccard", role: "dialog", "aria-label": "자료 · 작업 폴더 · 인터넷", hidden: !cardOpen, "data-sec": cardOpen || "src" },
      h("div", { class: "sc-sec", "data-sec": "src" }, h("div", { class: "sc-head" }, h("b", null, `자료 ${ps.length}`),
        main ? h("small", null, `주 논문: ${main.title}${main.version ? " " + main.version : ""}`) : null), srcEl),
      h("div", { class: "sc-sec", "data-sec": "dir" }, dirEl), netEl ? h("div", { class: "sc-sec", "data-sec": "net" }, netEl) : null);
    // the card sits under its chip, kept inside the conversation column
    const place = b => { const c = $("srccard"), w = $("chips"); if (!c || !b || !w) return;
      c.style.left = Math.max(-w.offsetLeft + 8, Math.min(b.offsetLeft, w.clientWidth - c.offsetWidth)) + "px"; };
    const chipEl = (sec, icon, text, cls, title) => { const b = h("button", { class: "hchip" + (sec === "src" ? " statechip" : "") + (cls ? " " + cls : ""),
        "data-chip": sec, title: title || null, "aria-haspopup": "dialog", "aria-expanded": String(cardOpen === sec),
        on: () => { if (cardOpen === sec) return cardClose(); cardOpen = sec; card.dataset.sec = sec; card.hidden = false;
          document.querySelectorAll(".hchip").forEach(x => x.setAttribute("aria-expanded", String(x === b))); place(b); } },
      ico(icon, 14), h("span", null, text), ico("chevron-down", 12)); return b; };
    const fname = d.folder ? d.folder.split(/[\\/]/).filter(Boolean).pop() || d.folder : null;
    const chips = h("span", { id: "chips" },
      chipEl("src", "file", main ? `${main.title}${main.version ? " " + main.version : ""} · 주` : ps.length ? `자료 ${ps.length}편` : "자료 없음", ps.length ? "" : "none",
        ps.length ? `자료 ${ps.length}${main ? " · 주 논문 " + main.title : ""}` : null),
      chipEl("dir", "folder", fname || "폴더 없음", d.folder ? "" : "none", d.folder || null),
      netEl ? chipEl("net", d.net ? "globe" : "globe-off", d.net ? "인터넷 허용" : "인터넷 차단", d.net ? "" : "off") : null, card);
    const oldChips = $("chips"); if (oldChips) oldChips.replaceWith(chips); else $("bar").insertBefore(chips, $("pnl") || null);
    if (cardOpen) place(chips.querySelector(`[data-chip="${cardOpen}"]`));
    // the stage bar: always visible; the steps come from stagesOf (D1). Each step carries its old action (#specs /
    // #audits / #compares / #reports, same ids, texts and conditions), by the step's key.
    const acts = { repro: { spec: specEl, audit: auditEl, report: reportEl }, read: { prep: specEl, compare: compEl, wrap: reportEl },
      general: { work: specEl, review: [auditEl, reportEl].filter(Boolean) } };
    const steps = st.steps.map(s => ({ ...s, act: (acts[kind] || acts.general)[s.key] }));
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
    // A9: the stage the conversation is filtered to says so, with how many of its messages are shown
    const filt = $("log").dataset.filter || "";
    const shownIn = label => [...$("log").children].filter(x => x.classList.contains("msg") && !x.classList.contains("filtered") && x.dataset.stage === label).length;
    bar.append(h("nav", { id: "stages", "data-kind": kind }, ...steps.map((s, i) =>
      h("div", { class: "stage st-" + s.state + (filt === s.label ? " picked" : ""), "data-stage": s.key,
        title: `${s.label} 단계의 대화만 보기`, on: e => { if (!e.target.closest("button, a")) stageFilter(s.label); } },
        h("span", { class: "st-n" }, stMark(s, i)),
        h("span", { class: "st-t" }, h("b", null, s.label), h("small", { "data-filtering": filt === s.label ? "1" : null }, filt === s.label ? `거르는 중 · ${shownIn(s.label)}` : s.sub),
          s.act || null))),
      more.length ? h("span", { class: "st-more" }, ...more) : null));
    // P6: how the conversation is grouped (the task's choice, else the settings'; 시간순 by default). A10: on the right, what
    // it is filtered by (a stage, or 대화로 거르기's label) as a chip that clears it, else "거르기 없음"
    const view = d.view || (M.settings || {}).view || "time";
    const fstate = !filt ? h("span", { class: "fnone", "data-filter-state": "" }, "거르기 없음")
      : filt.startsWith("refs:") ? h("button", { class: "fchip", "data-filter-state": filt, title: "거르기", "aria-haspopup": "menu", on: e => filterMenu(e.currentTarget) },
          ico("filter", 14), h("span", { class: "fc-t" }, filt.slice(5)), ico("chevron-down", 12))  // F24: 대화로 거르기 -> the 거르기 menu (풀기 is in it)
      : h("button", { class: "fchip", "data-filter-state": filt, title: "거르기 풀기", on: () => stageFilter(filt) }, h("span", { class: "fc-t" }, "단계 · " + filt), ico("x", 12));  // V3: a stage, ×
    bar.append(h("div", { id: "viewbar" }, h("span", { class: "muted" }, "보기"), h("span", { class: "vseg", role: "group", "aria-label": "보기" },
      ...[["time", "시간순"], ["stage", "단계별"], ["target", "대상별"]].map(([v, t]) =>
      h("button", { class: "vtab" + (view === v ? " on" : ""), "data-view": v, disabled: !pabloHost.setUi, "aria-pressed": String(view === v),
        on: () => view !== v && pabloHost.setUi(V.task.id, "view", v).then(() => refresh()).then(() => conversation()) }, t))),
      h("span", { class: "grow" }), fstate));
    box.querySelectorAll("#route").forEach(x => x.remove());  // 보낼 곳 lives in the composer, after the send button (it stays the first button)
    if (routeEl) box.append(routeEl);
  };
  { const tools0 = tools; tools = () => { tools0(); route(); }; }  // the stage bar's tools, then 보낼 곳 (B17)
  // a stage filter or 대화로 거르기 (stageFilter / filterBy set #log's data-filter): the stage bar and the view bar follow
  new MutationObserver(rs => { if (rs.some(r => r.oldValue !== $("log").getAttribute("data-filter"))) tools(); })
    .observe($("log"), { attributes: true, attributeFilter: ["data-filter"], attributeOldValue: true });
  // A12: 새 작업 is a dialog over the open task (#goal, #repro / #kind-*, #create as before). What is picked before the task
  // exists (PDFs, a folder: tokens from main; arXiv · OpenReview · DOI as text) is attached right after it is made
  newTask = () => {
    if ($("newtask")) return $("goal").focus();
    cardClose();
    const s = M.settings || {}, picks = { pdfs: [], folder: null, links: [] };
    let primary = 0, net = !!s.net;
    const ta = h("textarea", { id: "goal", rows: 1, placeholder: "예: LinearRAG baseline을 2WikiMultiHopQA에서 재현", "aria-label": "작업 목표" });
    ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 160) + "px"; });
    // P7: three kinds; 논문 재현 keeps id=repro (its criteria come with it); each shows the stages it will go through
    const kinds = [["repro", "논문 재현", "기본 기준 3개가 함께 들어갑니다", "준비 → 조건 확정 → 구현·실행 → 재현 점검 → 보고서"],
      ["read", "논문 읽기", "질문 · 비교표 중심, 폴더 없이", "준비 → 질문 → 비교표 → 정리"],
      ["general", "일반", "기준을 대화로 직접 정합니다", "준비 → 작업 → 검토"]];
    const radios = kinds.map(([k]) => h("input", { type: "radio", name: "kind", value: k, id: k === "repro" ? "repro" : "kind-" + k, checked: k === "general" ? true : null }));
    const repro = radios[0], pickedKind = () => (radios.find(r => r.checked) || radios[2]).value;
    const kindBox = h("div", { class: "nt-kind", "data-kind-stages": "1" });
    const showStages = () => { const k = pickedKind();
      kindBox.replaceChildren(...[k === "repro" && (M.reproCriteria || []).length ? h("b", null, "함께 들어가는 반드시 기준") : null,
        k === "repro" && (M.reproCriteria || []).length ? h("ul", null, M.reproCriteria.map(x => h("li", null, x))) : null,
        h("p", null, h("b", null, "이 작업의 단계: "), kinds.find(x => x[0] === k)[3])].filter(Boolean)); };
    radios.forEach(r => r.addEventListener("change", showStages)); showStages();
    // 자료: PDFs (picked now, copied once the task exists), arXiv · OpenReview · DOI lines; the first is the 주 논문 unless one is picked
    const srcNote = h("small", { class: "nt-hint" }, "여러 편을 둘 수 있고, 재현 조건은 주 논문 한 편에서만 뽑습니다. 내려받기 전에 파일 · 출처 · 크기를 보여 줍니다.");
    const chipsBox = h("div", { class: "nt-chips" });
    const items = () => [...picks.pdfs.map(p => ({ name: p.name, pdf: p })), ...picks.links.map(l => ({ name: l.label, link: l, title: l.title }))];
    const drop = x => { if (x.pdf) picks.pdfs.splice(picks.pdfs.indexOf(x.pdf), 1); else picks.links.splice(picks.links.indexOf(x.link), 1);
      primary = Math.min(primary, Math.max(0, items().length - 1)); drawChips(); };
    const drawChips = () => chipsBox.replaceChildren(...items().map((x, i) => h("span", { class: "nt-chip" + (i === primary ? " main" : ""), title: x.title || null },
        h("button", { class: "nt-cname", "data-nt-primary": String(i), on: () => { primary = i; drawChips(); } }, h("b", null, x.name), i === primary ? " · 주 논문" : " · 주 논문으로"),
        h("button", { class: "nt-x", title: "빼기", "aria-label": "빼기", on: () => drop(x) }, ico("x", 12)))),
      ...(items().length ? [h("button", { class: "nt-chip add", on: pickPdf }, "+ 추가")] : []));
    const pickPdf = () => pabloHost.pickPdfsFree().then(r => { if (r) { picks.pdfs.push(...r); drawChips(); } }, e => { srcNote.textContent = "⚠ " + clean(e); });
    const linkIn = h("input", { class: "nt-in", id: "nt-link", placeholder: "arXiv 번호·링크, OpenReview, DOI", spellcheck: "false" });
    const addLink = async () => {
      for (const v of linkIn.value.trim().split(/[\s,;]+/).filter(Boolean)) {
        const l = { text: v, label: v.length > 28 ? v.slice(0, 27) + "…" : v, title: null };
        if (ARXIV.test(v) && pabloHost.peekArxiv) {  // D10 / B24 (S12): the file, where from and how big; 받기 keeps it, 취소 drops it
          let p; try { p = await pabloHost.peekArxiv(v); } catch (e) { srcNote.textContent = `⚠ ${v}: ${clean(e)}`; continue; }
          l.label = p.title ? (p.title.length > 34 ? p.title.slice(0, 33) + "…" : p.title) + (p.version ? " " + p.version : "") : l.label;
          l.title = `${p.filename} · 출처 ${p.source}${p.bytes ? ` · ${(p.bytes / 1048576).toFixed(1)} MB` : ""}`;
          if (!await new Promise(res => dlSlot.replaceChildren(downloadCard(p, () => res(true), () => res(false))))) continue; }
        picks.links.push(l); drawChips(); }
      linkIn.value = ""; drawChips(); };
    const dlSlot = h("div", { class: "nt-dl", "data-nt-dl": "1" });
    linkIn.addEventListener("keydown", e => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); addLink(); } });
    // 작업 폴더: none, or one picked (refused at once when it overlaps Pablo's own folders)
    const folderNote = h("small", { class: "nt-hint" }, "에이전트는 이 폴더 안에서만 씁니다. 비워 두면 논문 질문만 합니다.");
    const noneB = h("button", { class: "pill", "data-folder-none": "1", on: () => { picks.folder = null; drawFolder(); } }, "선택 안 함");
    const pickB = h("button", { class: "pill", "data-folder-pick": "1", on: () => pabloHost.pickFolderFree().then(r => { if (r) { picks.folder = r; drawFolder(); } },
      e => { folderNote.textContent = "⚠ " + clean(e); }) }, "폴더 고르기");
    const drawFolder = () => { noneB.classList.toggle("sel", !picks.folder); pickB.classList.toggle("sel", !!picks.folder);
      pickB.replaceChildren(ico("folder", 14), picks.folder ? picks.folder.name : "폴더 고르기"); };
    drawFolder();
    const netIn = h("input", { type: "checkbox", role: "switch", id: "nt-net", checked: net ? true : null });
    const netLbl = h("span", null), drawNet = () => { netLbl.textContent = (net ? "허용" : "차단") + (net === !!s.net ? " (기본)" : ""); };
    netIn.addEventListener("change", () => { net = netIn.checked; drawNet(); }); drawNet();
    const crit = h("textarea", { id: "nt-crit", rows: 1, placeholder: "예: test 셋은 튜닝에 절대 쓰지 마.", "aria-label": "이 작업만의 기준" });
    const state = h("div", { class: "nt-state", "aria-live": "polite" });
    const make = h("button", { class: "pill on", id: "create", on: () => go() }, "만들기");
    const field = (label, ...kids) => h("div", { class: "nt-field" }, h("h4", null, label), ...kids);
    const dlg = h("div", { id: "newtask", class: "dlg-dim", role: "dialog", "aria-modal": "true", "aria-label": "새 작업" }, h("div", { class: "dlg nt" },
      h("div", { class: "dlg-head" }, h("b", null, "새 작업"), h("button", { class: "x", title: "닫기", "aria-label": "닫기", on: () => dlg.remove() }, ico("x"))),
      h("div", { class: "dlg-body" },
        field("작업 목표", ta, h("small", { class: "nt-hint" }, "첫 줄이 작업 이름이 됩니다.")),
        field("작업 종류", h("div", { class: "kinds" }, kinds.map(([k, label, what], i) => h("label", { class: "kind" }, radios[i], h("b", null, label), h("small", null, what)))), kindBox),
        field("자료 (논문)", h("div", { class: "nt-row" }, h("button", { class: "pill", "data-nt-pdf": "1", on: pickPdf }, ico("file", 14), "PDF 고르기"), linkIn,
          h("button", { class: "pill", "data-nt-link": "1", on: addLink }, "가져오기")), dlSlot, chipsBox, srcNote),
        h("div", { class: "nt-two" }, field("작업 폴더", h("div", { class: "nt-row" }, noneB, pickB), folderNote),
          field("인터넷", h("label", { class: "nt-switch" }, netIn, h("span", { class: "sw", "aria-hidden": "true" }), netLbl),
            h("small", { class: "nt-hint" }, "허용해도 명령은 하나하나 Guard를 거칩니다."))),
        field("이 작업만의 기준 (선택)", crit, h("small", { class: "nt-hint" }, "\"절대 · 항상 · 가능하면\"처럼 적으면 기준으로 남습니다. 나중에 대화로 더해도 됩니다.")),
        state),
      h("div", { class: "dlg-foot" }, h("button", { class: "pill", on: () => dlg.remove() }, "취소"), make)));
    dlg.addEventListener("mousedown", e => { if (e.target === dlg && !make.disabled) dlg.remove(); });
    document.body.append(dlg);
    // S23: while it is made, the reading of the criteria; a failure says nothing was lost and offers it again
    const go = () => {
      const goal = ta.value.trim(); if (!goal) return ta.focus();
      const text = [goal, crit.value.trim()].filter(Boolean).join("\n"), its = items();
      make.disabled = true; make.textContent = "작업을 만드는 중…";
      state.replaceChildren(h("p", { class: "nt-wait" }, h("span", { class: "spin", "aria-hidden": "true" }), "적은 기준을 읽고 있습니다"));
      pabloHost.newTask(text, { repro: repro.checked, kind: pickedKind() }).then(r => refresh(r.id).then(async () => {
        dlg.remove();
        const n = r.added, id = r.id;  // what this form's lines recorded (project-wide criteria are in 기준 보기)
        // ③ every criterion line is accounted for: recorded, or waiting above for the user to decide
        live(id).append(msg("Pablo", null, M.tasks.length === 1 ? art("waving", "pose") : null, h("p", { "data-made": "1" }, n ? `작업 기준 ${n}개를 기록했습니다. ` : "작업을 만들었습니다. ",
          r.unread ? h("b", { "data-ask": "1" }, `적은 기준 ${r.lines}줄 중 ${r.unread}줄은 기준으로 읽지 못해, 위에서 정해 주세요. `) : null,
          link("작업 기준 보기", () => show({ mode: "intent" }))),
          h("p", { class: "muted" }, "PDF를 추가하면 근거를 찾아 답하고, 작업 폴더를 고르면 그 폴더에서 작업합니다.")));
        const tokens = [...picks.pdfs.map(p => p.token), ...(picks.folder ? [picks.folder.token] : [])];
        if (!tokens.length && !picks.links.length && net === !!s.net) return;
        const wait = h("p", { class: "muted", "data-attaching": "1" }, "고른 자료와 폴더를 붙이는 중…"); live(id).append(msg("Pablo", null, wait)); scroll();
        const lines = [], titles = [];
        if (tokens.length) try { const a = await pabloHost.attachPicked(id, tokens);
            if (!a.failed.length) a.added.forEach(x => titles.push(x.title)); else picks.pdfs.forEach(() => titles.push(null));
            a.added.forEach(x => lines.push(`✓ ${x.title}${x.same ? " (이미 있음)" : ""}`)); a.failed.forEach(f => lines.push(`⚠ ${f.file}: ${f.error}`));
            if (a.folder) lines.push(`✓ 작업 폴더: ${a.folder}`); }
          catch (e) { lines.push("⚠ " + clean(e)); picks.pdfs.forEach(() => titles.push(null)); }
        for (const l of picks.links) {
          try { const x = await (!ARXIV.test(l.text) && DOI.test(l.text) && pabloHost.lookupDoi ? pabloHost.lookupDoi(l.text).then(r => {
                if (!r.hits.length) throw new Error(`"${r.title}": arXiv에서 같은 제목을 찾지 못했습니다. 출판사의 PDF를 받아 파일로 더하세요.`);
                return pabloHost.addArxiv(id, r.hits[0].id, { doi: r.doi }); })
              : (ARXIV.test(l.text) ? pabloHost.addArxiv : OPENREVIEW.test(l.text) && pabloHost.addOpenreview ? pabloHost.addOpenreview : pabloHost.addWeb)(id, l.text));
            titles.push(x.title); lines.push(`✓ ${label(x)}${x.same ? " (이미 있음)" : ""}`); }
          catch (e) { titles.push(null); lines.push(`⚠ ${l.text}: ${clean(e)}`); } }
        if (picks.folder && net !== !!s.net && pabloHost.setNet) await pabloHost.setNet(id, net).catch(e => lines.push("⚠ 인터넷: " + clean(e)));
        await refresh();
        const want = its.length > 1 ? titles[primary] : null, p = want && ((M.desk || {})[id] || {}).papers.find(x => x.title === want);
        if (p && !p.primary) await pabloHost.setPrimary(id, p.id).then(() => refresh()).catch(() => {});
        wait.replaceWith(h("div", { "data-attached": "1" }, h("p", null, "만들 때 고른 것을 붙였습니다."), h("ul", { class: "muted" }, lines.map(x => h("li", null, x)))));
      }), e => { make.disabled = false; make.textContent = "만들기";
        state.replaceChildren(h("div", { class: "call nb", "data-made-error": "1" }, h("p", { class: "head" }, "작업을 만들지 못했습니다"),
          h("p", null, clean(e), " 적은 목표와 기준은 그대로 있습니다."),
          h("p", { class: "acts" }, h("button", { class: "pill on", on: () => go() }, "다시 시도"), h("button", { class: "pill", on: () => dlg.remove() }, "닫기")))); });
    };
    ta.focus();
  };
  const clean = e => String(e.message || e).replace(/^Error invoking remote method '[^']*': (\w*Error: )?/, "");
  // A14 / F12–F15 설정: a list on the left (계정 · 기본값 · 셸 · 인코딩 · 저장 위치 · 정보), a page on the right. A choice applies
  // at once. The model and its thinking level are chosen in the composer (10/27)
  function settings(page) {
    const old = $("settings"); if (old) { old.remove(); if (!page) return; }
    page = page || "defaults";
    const PAGES = [["account", "계정"], ["defaults", "기본값"], ["shell", "셸 · 인코딩"], ["storage", "저장 위치"], ["about", "정보"]];
    const note = h("p", { class: "set-note", role: "status" }), main = h("div", { class: "set-main" });
    const nav = h("nav", { class: "set-nav" }, h("b", null, "설정"), ...PAGES.map(([k, l]) => h("button", { class: "set-item" + (k === page ? " on" : ""), "data-set-page": k,
      on: () => { page = k; nav.querySelectorAll(".set-item").forEach(b => b.classList.toggle("on", b.dataset.setPage === k)); draw(); } }, l)));
    const dlg = h("div", { id: "settings", class: "dlg-dim", role: "dialog", "aria-modal": "true", "aria-label": "설정" }, h("div", { class: "set-box" }, nav, main));
    const close_ = () => { dlg.remove(); settingsDraw = null; };
    const row = (title, help, right, attrs) => h("div", { class: "set-row", ...(attrs || {}) }, h("div", null, h("b", null, title), help ? h("small", null, help) : null),
      right ? h("div", { class: "set-opts" }, right) : null);
    const tag = t => h("span", { class: "set-tag" }, t);
    const save = v => { note.textContent = ""; return pabloHost.setUi(null, "settings", v).then(() => refresh()).then(() => V && conversation(), e => { note.textContent = "⚠ " + clean(e); }); };
    const radios = (name, opts, cur) => h("div", { class: "set-radios", role: "radiogroup" }, opts.map(([v, t]) => { const r = h("input", { type: "radio", name: "set-" + name, value: v, checked: v === cur ? true : null });
      r.addEventListener("change", () => save({ [name]: v })); return h("label", null, r, h("span", null, t)); }));
    const opener = (which, label) => h("button", { class: "pill", "data-open-path": which, on: () => pabloHost.openPath(which).then(() => { note.textContent = ""; }, e => { note.textContent = "⚠ " + clean(e); }) },
      ico("folder", 14), label || "폴더 열기");
    const size = b => b == null ? null : b >= 1048576 ? `${(b / 1048576).toFixed(b >= 104857600 ? 0 : 1)} MB` : `${Math.ceil(b / 1024)} KB`;
    const ext = (href, text) => h("a", { class: "link", href, target: "_blank", rel: "noopener noreferrer" }, text);
    const pages = {
      account: () => { const on = authSt.state === "connected", n = pick.options.length;
        const confirm = h("div", { class: "call set-confirm", hidden: true }, h("p", { class: "head" }, "연결을 해제할까요?"),
          h("p", null, "이 기기의 ChatGPT 토큰을 폐기하고, 작업마다 이어 가던 대화(thread) 연결을 지웁니다. 작업 · 기준 · 대화 기록은 그대로 남습니다. 다시 연결하면 새 대화로 이어 갑니다."),
          h("p", { class: "acts" }, h("button", { class: "pill warn", "data-logout-ok": "1", on: () => pabloHost.logout().then(() => draw(), e => { note.textContent = "⚠ " + clean(e); }) }, "연결 해제"),
            h("button", { class: "pill", on: () => { confirm.hidden = true; } }, "취소")));
        return [h("div", { class: "set-card", "data-account": authSt.state }, h("b", null, on ? "ChatGPT · 연결됨" : "ChatGPT · 연결 안 됨", on ? tag("플랜 사용 가능") : null),
            h("small", null, on ? `쓸 수 있는 모델 ${n}개${checkedAt ? " · 마지막 확인 " + hhmm(checkedAt) : ""}` : authSt.error || "연결해야 에이전트와 논문 질문을 쓸 수 있습니다.")),
          ...(on ? [row("플랜 확인", "ChatGPT 플랜으로 에이전트와 논문 질문을 씁니다. API 키는 쓰지 않습니다. 플랜이 바뀌었으면 다시 확인하세요.",
              pabloHost.recheckPlan ? h("button", { class: "pill", "data-recheck": "1", on: () => { rechecking = true; pabloHost.recheckPlan().catch(e => { rechecking = false; note.textContent = "⚠ " + clean(e); }); } },
                ico("rotate", 14), "다시 확인") : null),
            row("연결 해제", "이 기기에 저장된 로그인 토큰을 지웁니다.", h("button", { class: "pill warn", "data-logout": "1", on: () => { confirm.hidden = false; } }, "연결 해제")), confirm]
            : [row("연결", "시스템 브라우저에서 ChatGPT 로그인을 승인합니다.", authSt.state === "signing_in" || authSt.state === "verifying" ? h("small", null, "연결하는 중…")
              : h("button", { class: "pill on", "data-set-signin": "1", on: () => pabloHost.login() }, "ChatGPT로 연결"))])]; },
      defaults: () => { const s = M.settings || {};
        const sw = h("input", { type: "checkbox", role: "switch", "data-set-net": "1", checked: s.net ? true : null });
        sw.addEventListener("change", () => save({ net: sw.checked }));
        return [h("p", { class: "set-lead" }, "모델과 생각 수준은 입력창에서 고릅니다. 새 작업은 마지막에 고른 값으로 시작합니다."),
          row("새 작업의 인터넷", "작업마다 바꿀 수 있습니다. 허용해도 명령은 하나하나 Guard를 거칩니다.",
            h("label", { class: "nt-switch" }, sw, h("span", { class: "sw", "aria-hidden": "true" }), h("span", null, s.net ? "허용" : "차단"))),
          row("오른쪽 패널", "새 작업은 기준 탭이 열린 채 시작하고, 그 뒤에는 작업마다 마지막 상태를 기억합니다.",
            radios("panel", [["open", "열림 + 작업마다 기억"], ["rail", "레일(접힘)"]], s.panel === "rail" ? "rail" : "open")),
          row("기본 보기", "대화를 처음 열 때의 보기", radios("view", [["time", "시간순"], ["stage", "단계별"], ["target", "대상별"]], s.view || "time")),
          row("메시지 태그", "단계 · 대상만 보이고 나머지는 'N개 더'로 접습니다. 전부 보이기를 고를 수 있습니다.",
            radios("tags", [["main", "단계 · 대상만"], ["all", "전부"]], s.tags || "main"))]; },
      shell: () => { const sh = (M.host || {}).shell, five = sh === "powershell";
        return [row(["셸 ", tag("감지됨")], "에이전트가 명령을 실행하는 셸입니다. 시작할 때 한 번 찾습니다.",
            h("code", null, sh === "pwsh" ? "pwsh.exe · PowerShell 7" : five ? "powershell.exe · 5.1" : String(sh || "—"))),
          row(["출력 인코딩 ", tag("적용됨")], "한글이 든 파일과 명령 출력을 UTF-8로 읽습니다.", h("code", null, "UTF-8")),
          row("인코딩 규칙", five ? "에이전트에게 파일을 UTF-8로 읽으라는 규칙을 붙였습니다(재현 점검에도 같은 말을 덧붙입니다)."
            : "에이전트가 셸을 열 때 출력 인코딩을 UTF-8로 맞추는 규칙을 붙입니다. 바꿀 것은 없습니다."),
          h("h4", { class: "set-sub" }, "PowerShell 5.1만 있을 때"),
          five ? ps51(null, "Windows PowerShell 5.1 · 한글 깨짐 위험")
            : h("p", { class: "set-info" }, ico("info", 14), " 이 PC에는 PowerShell 7이 있어 해당하지 않습니다. 5.1만 있으면 여기와 입력창 위에 설치 안내가 보입니다.")]; },
      storage: () => { const host = M.host || {};
        return [row("앱 데이터", "작업 · 기준 · 대화 기록과 로그인 토큰이 있는 곳입니다.", opener("userData")),
          host.userData ? h("code", { class: "set-path" }, host.userData) : null,
          row("체크포인트", `되돌리기에 쓰는 파일 사본입니다.${size(host.checkpoints) ? " " + size(host.checkpoints) + "." : ""}`, opener("checkpoints")),
          row("보고서 기본 위치", "보고서 내보내기에서 작업마다 바꿀 수 있습니다.", h("code", null, "작업 폴더\\reports\\")),
          h("p", { class: "set-info" }, ico("info", 14), " 작업 폴더는 이 위치와 겹치지 않는 별도 폴더여야 합니다. 겹치는 폴더를 고르면 Pablo가 받지 않습니다.")].filter(Boolean); },
      about: () => { const host = M.host || {}, REPO = "https://github.com/PabloITMST/Pablo_application";
        return [h("div", { class: "set-brand" }, h("b", null, art("head", "ico"), "Pablo"), h("code", null, host.version || "")),
          h("p", { class: "set-lead" }, "논문 재현과 읽기를 돕는 데스크톱 앱. 에이전트가 하는 일을 작업 기준과 대조합니다."),
          row("버전", "에이전트는 Codex app-server로 실행합니다.", h("code", null, `Pablo ${host.version || "—"} · Codex ${host.codex || "—"}`)),
          row("로그", host.logs ? "문제를 알릴 때 이 폴더의 로그를 함께 보내 주세요." : "로그는 콘솔에만 남고 파일로 저장하지 않습니다.",
            host.logs ? opener("logs", "로그 폴더") : h("code", null, "없음")),
          row("제3자 고지", "Pablo가 쓰는 오픈 소스 구성 요소와 라이선스.", ext(REPO + "/blob/main/desktop/THIRD_PARTY_NOTICES.txt", "보기 ↗")),
          row("소스", "GitHub 저장소", ext(REPO, "PabloITMST/Pablo_application ↗"))]; } };
    const draw = () => { const title = PAGES.find(p => p[0] === page)[1];
      main.replaceChildren(h("div", { class: "set-head" }, h("b", null, title), h("button", { class: "x", title: "닫기", "aria-label": "닫기", on: close_ }, ico("x"))),
        h("div", { class: "set-page", "data-page": page }, ...pages[page]()), note); };
    settingsDraw = draw; draw();
    dlg.addEventListener("mousedown", e => { if (e.target === dlg) close_(); });
    document.body.append(dlg);
  }
  openSettings = () => settings("defaults");
  // A13: the report's export dialog: its parts with their counts (pablo:report-preview), the record that goes with it, a
  // warning when files changed after the last audit, HTML or Markdown, and where (<work folder>/reports by default, 바꾸기 =
  // the save dialog first); a task without a folder is asked where on export, as before
  const PARTS = [["goal_criteria", "작업 목표와 기준", c => `반드시 ${c.criteria.hard} · 가능하면 ${c.criteria.soft}`], ["conditions", "재현 조건과 원문 위치", c => `${c.conditions}개`],
    ["audit", "최근 재현 점검", c => { if (!c.audit || !c.audit.at) return "점검 전"; const d = new Date(c.audit.at), p = n => String(n).padStart(2, "0");
      return `${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; }],
    ["deviations", "의도한 차이", c => String(c.deviations)], ["decisions", "결정과 이유 (대화에서 고정)", c => String(c.decisions)],
    ["changes", "변경 기록 · 되돌리기", c => `${c.changes}건`], ["refused", "Pablo가 막거나 확인을 받은 작업", c => `${c.refused}건`], ["conversation", "대화 전체", c => `${c.conversation}개`]];
  reportDlg = t => {
    const old = $("report-dlg"); if (old) old.remove();
    cardClose();
    let fmt = "html", token = null, where = null;
    const body = h("div", { class: "dlg-body" }, h("p", { class: "muted" }, "보고서에 넣을 내용을 세는 중…"));
    const err = h("p", { class: "dlg-err", role: "alert" });
    const goB = h("button", { class: "pill on", "data-report-go": "1", disabled: true, on: () => exportIt() }, "내보내기");
    const dlg = h("div", { id: "report-dlg", class: "dlg-dim", role: "dialog", "aria-modal": "true", "aria-label": "보고서 내보내기" }, h("div", { class: "dlg rp" },
      h("div", { class: "dlg-head" }, h("b", null, kindFor((M.desk || {})[t]) === "repro" ? "재현 보고서 내보내기" : "보고서 내보내기"),
        h("button", { class: "x", title: "닫기", "aria-label": "닫기", on: () => dlg.remove() }, ico("x"))),
      body, err, h("div", { class: "dlg-foot" }, h("button", { class: "pill", on: () => dlg.remove() }, "취소"), goB)));
    dlg.addEventListener("mousedown", e => { if (e.target === dlg) dlg.remove(); });
    document.body.append(dlg);
    pabloHost.reportPreview(t).then(pv => {
      where = pv.where;
      const placeEl = h("code", { class: "rp-where", "data-report-place": "1" });
      const place = () => { placeEl.textContent = token ? token.display : where ? where + "/" : "내보낼 때 고릅니다"; };
      const seg = h("span", { class: "seg2", role: "group", "aria-label": "형식" }, ...[["html", "HTML"], ["md", "Markdown"]].map(([f, l]) =>
        h("button", { class: "pill" + (f === fmt ? " sel" : ""), "data-format": f, "aria-pressed": String(f === fmt), on: () => { fmt = f; token = null;
          seg.querySelectorAll("[data-format]").forEach(b => { b.classList.toggle("sel", b.dataset.format === f); b.setAttribute("aria-pressed", String(b.dataset.format === f)); }); place(); } }, l)));
      const change = h("button", { class: "link", "data-report-where": "1", on: () => pabloHost.pickReportPath(t, fmt).then(r => { if (r) { token = r; place(); } }, e => { err.textContent = "⚠ " + clean(e); }) }, "바꾸기");
      place();
      body.replaceChildren(h("h4", null, "포함할 내용"),
        h("div", { class: "rp-list" }, PARTS.map(([k, label, n]) => h("label", { class: "rp-row" }, h("input", { type: "checkbox", "data-section": k, checked: k !== "conversation" ? true : null }),
          h("span", null, label), h("small", null, n(pv.counts))))),
        h("div", { class: "rp-auto" }, h("b", null, "함께 남는 기록 (자동)"), h("code", null, pv.auto)),
        pv.stale ? h("div", { class: "rp-stale", "data-report-stale": "1" }, h("p", null, "점검 뒤 파일이 바뀌었습니다. 이대로 내보내면 점검 결과가 '오래됨'으로 표시됩니다."),
          reAudit && pabloHost.audit ? h("button", { class: "pill", "data-report-reaudit": "1", on: () => { dlg.remove(); reAudit(t); } }, "먼저 다시 점검") : null) : "",  // replaceChildren prints null as "null" (demo 10/27)
        h("div", { class: "rp-opts" }, h("div", null, h("h4", null, "형식"), seg), h("div", null, h("h4", null, "저장 위치"), h("span", { class: "rp-wrow" }, placeEl, change))));
      body.addEventListener("change", () => { goB.disabled = !body.querySelector("[data-section]:checked"); });
      goB.disabled = false;
    }, e => body.replaceChildren(h("p", { class: "muted" }, "⚠ " + clean(e))));
    const exportIt = () => {
      const sections = [...body.querySelectorAll("[data-section]:checked")].map(x => x.dataset.section); if (!sections.length) return;
      goB.disabled = true; err.textContent = "";
      saveReport(t, { sections, format: fmt, ...(token ? { token: token.token } : where ? { token: "default" } : {}) }, () => dlg.remove(), () => { goB.disabled = false; });
    };
  };
  // S52: after 내보내기, one card in the conversation: where it was saved (폴더에서 보기 · VS Code에서 열기 when it is in the
  // work folder), or why it was not and 다른 위치에 저장 (the save dialog, then the same parts and format again)
  const saveReport = (t, opts, done, back) => pabloHost.report(t, opts).then(r => {
    if (!r) return back(); done();
    const open = how => pabloHost.openFile(t, r.rel, null, how).catch(e => notice(h("div", { class: "call nb" }, h("p", { class: "head" }, "보고서를 열지 못했습니다"),
      h("p", null, clean(e)), h("p", { class: "acts" }, h("button", { class: "link", on: () => notice(null) }, "닫기")))));
    if (V && V.task.id === t) { live(t).append(msg("Pablo", null, h("div", { class: "call rp-done", "data-report": "1" },
      h("p", { class: "head" }, ico("file", 14), "보고서를 저장했습니다"),
      h("p", { class: "rp-file" }, h("code", null, r.rel || r.display || r.name), ` · ${r.lines}줄`),
      r.rel && pabloHost.openFile ? h("p", { class: "acts" }, h("button", { class: "pill open", "data-report-open": "folder", on: () => open("folder") }, ico("folder", 14), "폴더에서 보기"),
        h("button", { class: "pill open", "data-report-open": "vscode", on: () => open("vscode") }, ico("code", 14), "VS Code에서 열기")) : null))); scroll(); }
    askDone(); refresh();
  }, e => {
    done();
    if (!V || V.task.id !== t) return;
    const card = h("div", { class: "call rp-done fail", "data-report-fail": "1" }, h("p", { class: "head" }, ico("info", 14), "보고서를 저장하지 못했습니다"),
      h("p", null, clean(e)),
      h("p", { class: "acts" }, h("button", { class: "pill", "data-report-again": "1", on: () => pabloHost.pickReportPath(t, opts.format || "md").then(p => {
        if (!p) return; card.closest(".msg").remove(); saveReport(t, { ...opts, token: p.token }, () => {}, () => {}); }, x => notice(h("div", { class: "call nb" },
          h("p", { class: "head" }, "저장 위치를 고르지 못했습니다"), h("p", null, clean(x)), h("p", { class: "acts" }, h("button", { class: "link", on: () => notice(null) }, "닫기"))))) }, "다른 위치에 저장")));
    live(t).append(msg("Pablo", null, card)); scroll();
  });
  // A5/A6: 재현 점검 -> one read-only agent turn; its JSON answer comes back as an "audit" event (a table in the conversation)
  reAudit = t => audit(t);
  function audit(t) {
    if (agentSt === "Thinking") return;
    talk = busy = t; turning = true;
    const box = progCard("audit", "재현 점검", "점검 중", "작업 폴더를 읽는 중…", "읽기 전용 — 아무것도 바꾸지 않습니다", () => stop());
    box.dataset.auditing = "1";
    box._prog = ev => box._set(`파일 ${ev.files}개 읽음 · 조건 ${ev.judged} / ${ev.total} 판정`, ev.total ? ev.judged / ev.total : 0.05);
    live(t).append(msg("Pablo", null, box)); scroll(); gate();
    pabloHost.audit(t).catch(e => { turning = false; busy = null; status("Error", fail(e));
      const p = live(t).querySelector("[data-auditing]"); if (p) p.replaceWith(failCard("재현 점검을 시작하지 못했습니다", fail(e) + " 아무것도 바뀌지 않았습니다.")); });
  }
  // A2: the paper's reproduction conditions -> a card in the conversation (+ the 기준 panel); the agent's brief has them
  function spec(t) {
    if (agentSt === "Thinking") return;
    talk = busy = t;
    const pp = (((M.desk || {})[t] || {}).papers || []).find(p => p.primary && p.kind !== "web"), name = pp ? pp.title : "논문";
    const box = progCard("spec", "조건 확정", "뽑는 중", `${name}을(를) 읽고 있습니다`, "보통 1–3분 · 다른 일을 해도 됩니다", pabloHost.cancel ? () => pabloHost.cancel("spec") : null);
    box.dataset.specing = "1";
    box._prog = ev => box._set(`${name}을(를) 읽고 있습니다 · ${ev.page} / ${ev.pages}쪽`, ev.pages ? ev.page / ev.pages : 0.05);
    live(t).append(msg("Pablo", null, box)); scroll(); status("Thinking");
    pabloHost.spec(t).then(r => {
      Object.assign(M.anchors, r.anchors); Object.assign(M.sources, r.sources);
      for (const c of [...r.stated, ...r.missing]) M.views[t].checks[c.id] = c;
      box.replaceWith(conditions([...r.stated, ...r.missing].map(c => c.id), r.dropped.length, r.diff, r.secs));
      busy = null; status("Ready"); scroll(); refresh();
    }, e => { box.replaceWith(/중지했습니다/.test(fail(e)) ? failCard("조건 뽑기를 중지했습니다", "재현 조건과 기준은 그대로입니다.")
        : failCard("조건을 뽑지 못했습니다", fail(e))); busy = null; status("Ready"); });
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
      const vb = verified(r.check, r.dropped.length); if (vb) box.append(vb);  // B7
      busy = null; status("Ready"); scroll(); refresh();
    }, e => {
      const ps = ((M.desk || {})[t] || {}).papers || [];  // S43: what failed, then the papers to ask one at a time
      box.textContent = ""; box.append(failCard("답을 찾지 못했습니다", fail(e), /물어볼 (논문|자료)를 골라/.test(fail(e)) && ps.length > 1 ? h("div", { class: "ask-pick" },
        ps.map(p => h("button", { class: "pill", "data-ask-only": p.id, on: () => ask(text, t, [p.id]) }, `${p.title}에만 묻기`))) : null));
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
  inp.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
  account(authSt); pabloHost.authStatus().then(account); pabloHost.agentStatus().then(s => status(s)); models().then(gate);
}
const tag = decodeURIComponent(location.hash.slice(1));
select(M.views[tag] ? tag : M.anchors[tag] ? (Object.keys(M.views).find(t => Object.values(M.views[t].checks).some(c => c.evidence.includes(tag))) || M.current) : M.current);
if (M.anchors[tag] && cites[tag]) show({ mode: "source", e: tag });
if (window.pabloHost && pabloHost.state) refresh();  // the page was written at launch; read the live state once
</script>
</body></html>
"""
