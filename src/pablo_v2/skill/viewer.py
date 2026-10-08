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


def model(s, task_id: str) -> dict:
    t = s.get_task(task_id)
    eng = s.intent
    prev = {i.superseded_by: i.statement for i in eng.get_current_intent().items if i.superseded_by}

    def items(xs):
        return [{"id": x.id, "text": x.statement, "prev": prev.get(x.id)} for x in xs]

    def label(ref):  # intent item or system policy -> text
        it = eng.get_item(ref)
        return it.statement if it else SYSTEM_POLICIES.get(ref, ref)

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
        checks[sc_id] = {"id": c.id, "title": c.requirement, "state": c.research_state, "outcome": c.outcome,
                         "conclusion": c.conclusion, "necessity": c.necessity, "evidence": ev,
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
        criteria = [{"id": x["intent_id"], "text": label(x["intent_id"])} for x in an.get("intent_conflicts", [])]
        criteria += [{"id": x["source_check_id"], "text": check(x["source_check_id"])["conclusion"] or ""}
                     for x in an.get("source_conflicts", []) if check(x["source_check_id"])]
        runs = []
        for x in s.executions(a.id):
            rv = s.reviews(x.id)
            runs.append({"id": x.id, "executed": x.executed, "summary": x.summary, "files": x.changed_files,
                         "tests": x.tests, "alignment": rv[-1].action_alignment if rv else None,
                         "step_status": rv[-1].plan_step_status if rv else None})
        actions.append({"id": a.id, "step": a.plan_step, "text": a.description, "why": a.justification,
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
    return {"task": {"id": t.id, "text": t.text}, "stage": stage, "progress": [done, len(research)],
            "intent": intent, "research": research, "checks": checks, "plan": plan, "actions": actions,
            "anchors": anchors, "sources": sources}


def workspace(s, current: str | None = None) -> dict:
    """Every task of the state dir (the desktop's live state; render_html embeds the same model)."""
    views = {t.id: model(s, t.id) for t in s.state.tasks}
    anchors, sources = {}, {}
    for v in views.values():
        anchors.update(v.pop("anchors"))
        sources.update(v.pop("sources"))
    return {"current": current or (s.state.tasks[-1].id if s.state.tasks else None),
            "tasks": [{"id": t.id, "text": t.text, "at": t.created_at} for t in s.state.tasks],
            "views": views, "anchors": anchors, "sources": sources,
            "pdf": any(x.kind == "pdf" for x in s.state.sources)}  # M3.3: the static page's composer asks the PDF


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
:root { --bg:#fff; --side:#f7f7f8; --fg:#1f2328; --muted:#6b7280; --faint:#9ca3af; --line:#ececf0; --hover:#f0f0f3;
        --accent:#2563eb; --ok:#16a34a; --warn:#b45309; --warnbg:#fffbeb; --warnline:#f5c46b; --bad:#b91c1c;
        --badbg:#fef2f2; --badline:#f3a4a4; --hl:#fde68a; --code:#f3f4f6; --shade:rgba(0,0,0,.35); }
@media (prefers-color-scheme: dark) { :root { --bg:#1e1f22; --side:#18191b; --fg:#e8e8ea; --muted:#9ca3af;
        --faint:#6b7280; --line:#2e3035; --hover:#2a2c30; --accent:#7aa7ff; --ok:#4ade80; --warn:#fbbf24;
        --warnbg:#2d2410; --warnline:#7a5b17; --bad:#f87171; --badbg:#2d1414; --badline:#7f2a2a; --hl:#8a6d10;
        --code:#2a2c30; --shade:rgba(0,0,0,.6); } }
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
/* conversation */
#chat { display:flex; flex-direction:column; min-width:0; height:100vh; }
#bar { display:flex; align-items:center; gap:8px; padding:10px 20px; border-bottom:1px solid var(--line); }
#bar h1 { flex:1; min-width:0; font-size:16px; margin:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.pill { border:1px solid var(--line); border-radius:999px; padding:4px 12px; font-size:13px; }
.pill:hover:not(:disabled) { background:var(--hover); } .pill.on { background:var(--fg); color:var(--bg); border-color:var(--fg); }
#menu { display:none; font-size:18px; padding:0 6px; }
#log { flex:1; overflow:auto; padding:24px 20px 40px; }
.msg { max-width:720px; margin:0 auto 28px; display:grid; grid-template-columns:32px 1fr; gap:12px; }
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
#pbody.live { padding:0; overflow:hidden; display:flex; } #pbody.live webview { flex:1; }
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
@media (max-width:900px) {
  body, body.panel { display:block; }
  #side { display:none; position:fixed; inset:0 30% 0 0; z-index:3; box-shadow:0 0 0 100vmax var(--shade); }
  body.side #side { display:block; } #menu { display:block; }
  #panel { position:fixed; inset:0; z-index:4; } #bar { padding:10px 12px; } #log { padding:18px 12px 32px; }
  .msg { grid-template-columns:26px 1fr; gap:8px; } .av { width:26px; height:26px; } }
</style></head>
<body>
<nav id="side"></nav>
<section id="chat"><header id="bar"></header><div id="log"></div>
  <div class="composer"><input disabled placeholder="Pablo에게 물어보세요… (읽기 전용 미리보기)"><button disabled>↑</button></div></section>
<aside id="panel"></aside>
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
const tech = (...xs) => xs.some(Boolean) ? h("details", { class: "tech" }, h("summary", null, "기술 세부정보"),
  xs.filter(Boolean).map(x => h("pre", null, x))) : null;
// an English judge note -> a Korean line in the card; the note itself goes under 기술 세부정보
const korean = t => /[가-힣]/.test((t || "").replace(/"[^"]*"/g, ""));
const reason = (t, block) => !t ? null : korean(t) ? h("p", null, rich(t))
  : h("p", null, block ? "작업 기준과 충돌해 막았습니다." : "현재 작업 기준과 맞는지 확인이 필요합니다.");
const host = u => { try { const x = new URL(u); return x.host + x.pathname; } catch { return u; } };
let V, cites = {}, hist = [], hi = -1;
const lives = {}, live = t => (t = t || V.task.id, lives[t] || (lives[t] = h("div", { id: "live" })));  // agent chat, one per task (own thread)

// ---- citations: [n] -> the existing EvidenceAnchor id (data-e); numbering is per task ---------------------
function cite(e, n) {  // n: the answer's own number (M3.3 ask); else one number per evidence in this chat
  if (!(e in cites)) cites[e] = Object.keys(cites).length + 1;
  return h("button", { class: "cite", "data-e": e, title: "근거 보기", on: () => show({ mode: "source", e }) }, `[${n || cites[e]}]`);
}
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
function sidebar() {
  $("side").textContent = "";
  $("side").append(h("div", { class: "brand" }, h("b", null, art("head", "ico"), "Pablo"),
      h("button", { class: "new", id: "new", disabled: !(window.pabloHost && pabloHost.newTask), on: () => newTask() }, "+ 새 작업")),
    h("h4", null, "작업"),
    ...[...M.tasks].reverse().map(t => h("button", { class: "t" + (V && t.id === V.task.id ? " on" : ""), title: t.id,
      on: () => { select(t.id); document.body.classList.remove("side"); } }, t.text, h("small", null, time(t.at)))));
}
function header() {
  const mode = hi >= 0 && document.body.classList.contains("panel") ? hist[hi].mode : null;
  $("bar").textContent = "";
  $("bar").append(h("button", { id: "menu", title: "작업 목록", on: () => document.body.classList.toggle("side") }, "☰"));
  if (!V) return $("bar").append(h("h1", null, "Pablo"));
  $("bar").append(h("h1", { title: V.task.id }, V.task.text),
    h("button", { class: "pill" + (mode === "intent" ? " on" : ""), on: () => toggle({ mode: "intent" }) }, "기준"),
    h("button", { class: "pill" + (mode === "plan" ? " on" : ""), disabled: !V.plan, on: () => toggle({ mode: "plan" }) }, "계획"),
    h("button", { class: "pill" + (mode === "trace" ? " on" : ""), on: () => toggle({ mode: "trace" }) }, "왜?"));
}

// ---- conversation: built from the stored research / plan / guard / review records --------------------------
const msg = (who, at, ...kids) => h("div", { class: "msg " + (who === "Pablo" ? "pablo" : "user") },
  h("div", { class: "av" }, who === "Pablo" ? "P" : "나"), h("div", null, h("div", { class: "who" }, who, h("small", null, time(at))), kids));
// Normal progress is one Pablo answer; only research issues, WARN/BLOCK and open decisions get their own message.
const SURE = { PARTIALLY_VERIFIED: "일부만 확인했습니다.", NOT_FOUND: "공식 근거를 찾지 못해 추정했습니다.",
               CONFLICTING: "출처끼리 내용이 다릅니다." };
function answer() {
  const out = [];
  for (const id of V.research) {
    const c = V.checks[id];
    if (c.state === "waived" || live().querySelector(`.asked[data-check="${CSS.escape(id)}"]`)) continue;  // shown live already
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
const decided = a => a.decision ? (DECIDE[a.decision] || a.decision) + (a.decision_reason ? ` · ${a.decision_reason}` : "") : null;
function issues() {
  return V.research.flatMap(id => V.checks[id].issues.map(i => { const c = V.checks[id];
    return h("div", { class: "call", title: i.id, "data-id": i.id }, art("surprised", "pose"),
      h("p", { class: "head" }, "⚠ " + (ISSUE[i.type] || ISSUE.other)), h("p", null, rich(i.note), c.evidence.map(cite)),
      c.evidence.length ? h("p", null, "Pablo는 공식 원문을 기준으로 판단했습니다.") : null); }));
}
function action(a) {
  const block = a.verdict === "BLOCK", ev = a.criteria.flatMap(c => V.checks[c.id] ? V.checks[c.id].evidence : []);
  const d = decided(a);
  return h("div", { class: "call" + (block ? " block" : ""), title: a.id, "data-id": a.id },
    h("p", { class: "head" }, block ? "⚠ 이 작업은 현재 기준과 충돌합니다." : "⚠ 이 작업은 확인이 필요합니다."),
    h("p", null, "제안된 작업: ", h("b", null, meaning(a.text))),
    a.why ? h("p", { class: "muted" }, `제시한 이유: "${a.why}"`) : null,
    a.problems.length ? [reason(a.problems[0], block), [...new Set(ev)].map(cite)] : null,
    a.criteria.length ? h("p", { class: "muted" }, "관련 기준: ", a.criteria.map(c => c.text).join(" · ")) : null,
    d ? h("p", { class: "muted" }, d) : null, runs(a).map(x => h("p", { class: "muted" }, x)),
    tech(a.text, ...a.problems.filter(x => !korean(x))),
    h("p", null, block ? h("b", null, "실행이 차단되었습니다. ") : !d ? h("b", null, "진행할지 결정이 필요합니다. ") : null,
      h("button", { class: "link", on: () => show({ mode: "trace", act: a.id }) }, "왜 그런가요?")));
}
function conversation() {
  cites = {};
  const log = $("log"); log.textContent = "";
  const said = answer();
  log.append(msg("You", V.task.at, h("p", null, V.task.text)), said.length ? msg("Pablo", null, said) : "");
  issues().forEach(x => log.append(msg("Pablo", null, x)));
  V.actions.forEach(a => { if (live().querySelector(`[data-act="${CSS.escape(a.id)}"]`)) return;  // its live card is below
    const x = a.verdict === "ALLOW" ? failed(a) : action(a); if (x) log.append(msg("Pablo", null, x)); });
  if (V.intent.questions.length) log.append(msg("Pablo", null, h("div", { class: "call" },
    h("p", { class: "head" }, "⚠ 결정이 필요합니다."),
    V.intent.questions.map(q => h("p", { title: q.id, "data-id": q.id }, rich(q.text))),
    h("p", null, h("button", { class: "link", on: () => show({ mode: "intent" }) }, "작업 기준 보기")))));
  log.append(live());
  finish();
  log.scrollTop = 0;
}
// every plan step done -> one closing message (in the live part, so a refresh can add it too)
function finish() {
  if (!V.plan || !V.plan.steps.length || V.plan.steps.some(st => stepState(st)[0] !== "done") || $("log").querySelector(".finish")) return;
  live().append(h("div", { class: "finish" }, msg("Pablo", null, art("confident", "pose"), h("p", null, "작업을 마쳤습니다."))));
}
function select(tid) {
  V = M.views[tid] || M.views[M.current] || null;
  close(); sidebar(); header(); tools();
  if (!V) return empty();
  V.task.at = (M.tasks.find(t => t.id === V.task.id) || {}).at;
  conversation();
  document.title = "Pablo · " + V.task.text;
}
// M5.1: no task yet -> an empty Pablo screen; the desktop makes tasks in the app (+ 새 작업)
function empty() {
  const log = $("log"); log.textContent = ""; document.title = "Pablo";
  log.append(h("div", { class: "empty" }, art("default"), h("b", null, "무엇을 해볼까요?"), h("p", null, "새 작업을 만들어 시작하세요."),
    window.pabloHost && pabloHost.newTask ? h("button", { class: "pill on", on: () => newTask() }, "+ 새 작업") : null));
}
let tools = () => {}, newTask = () => {}, refresh = () => Promise.resolve();  // desktop only (M5.1): task tools, new task form, live state

// ---- one context panel: source | intent | plan | trace ---------------------------------------------------------
function toggle(st) { (hi >= 0 && document.body.classList.contains("panel") && hist[hi].mode === st.mode && !st.e) ? close() : show(st); }
function show(st, push = true) {
  if (push) { hist = hist.slice(0, hi + 1); hist.push(st); hi = hist.length - 1; }
  document.body.classList.add("panel"); document.body.classList.remove("pdf");
  CSS.highlights.clear();
  document.querySelectorAll(".cite").forEach(b => b.classList.toggle("on", st.mode === "source" && b.dataset.e === st.e));
  const p = $("panel"); p.textContent = ""; delete p.dataset.live;
  ({ source, intent, plan, trace })[st.mode](p, st);
  header();
}
function close() {
  document.body.classList.remove("panel", "pdf"); CSS.highlights.clear(); hist = []; hi = -1;
  document.querySelectorAll(".cite.on").forEach(b => b.classList.remove("on"));
  if (V) header();
}
const go = d => { if (hist[hi + d]) { hi += d; show(hist[hi], false); } };
const xbtn = () => h("button", { class: "x", title: "닫기", on: close }, "×");
const simple = (p, title, body, foot) => p.append(h("div", { class: "phead" }, h("h2", null, title), xbtn()),
  h("div", { id: "pbody" }, body), foot ? h("div", { class: "pfoot" }, h("div", { class: "composer" },
    h("input", { disabled: true, placeholder: foot }), h("button", { disabled: true }, "↑"))) : "");  // append(null) prints "null"

function intent(p) {
  const I = V.intent, g = (t, cls, xs) => xs.length ? [h("h3", null, t), h("ul", { class: "ck " + cls },
    xs.map(x => h("li", { title: x.id, "data-id": x.id }, x.prev ? h("span", { class: "prev" }, x.prev) : null, x.text)))] : null;
  const body = [g("목표", "", I.goals), g("반드시 지킬 것", "must", I.must), g("선호", "", I.prefer),
    g("성공 조건", "q", I.success), g("결정", "", I.decisions), g("확인 필요", "q", I.questions)];
  simple(p, "현재 작업 기준", body.some(Boolean) ? body : h("p", { class: "muted" }, "기록된 기준이 없습니다."),
    "기준에 대해 물어보거나 수정해보세요… (곧 지원)");
}
function stepState(st) {
  const rs = V.actions.filter(a => a.step === st.id).flatMap(a => a.runs).map(r => r.step_status);
  return rs.includes("completed") ? ["done", "✓"] : rs.includes("partial") ? ["doing", "●"] : ["todo", "○"];
}
function plan(p) {
  const steps = h("ol", { class: "steps" }, V.plan.steps.map(st => { const [cls, mark] = stepState(st);
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
                                     .filter(id => V.checks[id]) : V.research)]
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
    const g = { BLOCK: ["stop", "Guard가 실행을 막았습니다"], WARN: ["warn", "Guard가 경고했습니다"], ALLOW: ["", "Guard를 통과했습니다"] }[act.verdict] || ["", ""];
    nodes.push(li(g[0], "제안된 작업", meaning(act.text), h("div", null, g[1]),
      act.problems.map(x => korean(x) ? h("div", null, "· ", rich(x)) : null), tech(act.text, ...act.problems.filter(x => !korean(x)))));
    if (act.decision) nodes.push(li("", "사용자 결정", decided(act)));
    act.runs.forEach(r => nodes.push(li("", "결과", done(r), r.alignment ? h("div", null, ALIGN[r.alignment] || r.alignment) : null)));
  }
  simple(p, act ? (act.verdict === "BLOCK" ? "이 작업이 막힌 과정" : "이 작업을 판단한 과정") : step ? "이 단계가 계획에 들어간 과정" : "이 판단이 나온 과정", h("ol", { class: "tl" }, nodes));
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
      h("button", { class: "nav", title: "뒤로", disabled: hi <= 0, on: () => go(-1) }, "←"),
      h("button", { class: "nav", title: "앞으로", disabled: hi >= hist.length - 1, on: () => go(1) }, "→"),
      h("div", { class: "url", title: src.url }, "🔒 ", h("b", null, src.title), " · ", host(src.url)),
      h("a", { class: "ext", href: live, target: "_blank", rel: "noopener noreferrer", title: "원본 페이지에서 이 문장 보기" }, "↗"), xbtn()),
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
async function pdfPanel(p, st, a, src) {
  const t0 = performance.now(), n = st.page || a.page;
  const turn = d => show({ mode: "source", e: st.e, page: n + d });
  document.body.classList.add("pdf");
  p.dataset.live = "LOADING";
  const info = h("div", { class: "info", title: src.hash }, `캡처한 PDF · ${day(src.captured_at)} · 근거 위치를 찾는 중…`);
  p.append(h("div", { class: "phead" },
      h("button", { class: "nav", title: "뒤로", disabled: hi <= 0, on: () => go(-1) }, "←"),
      h("button", { class: "nav", title: "앞으로", disabled: hi >= hist.length - 1, on: () => go(1) }, "→"),
      h("div", { class: "url", title: src.url }, "📄 ", h("b", null, src.title), ` · PDF`),
      h("button", { class: "nav", title: "이전 쪽", disabled: n <= 1, on: () => turn(-1) }, "‹"),
      h("span", { class: "pnum" }, `${n} / ${src.pages}`),
      h("button", { class: "nav", title: "다음 쪽", disabled: n >= src.pages, on: () => turn(1) }, "›"), xbtn()),
    info, h("div", { id: "pbody", class: "pdf" }));
  const fail = why => { if (hist[hi] !== st) return; hist[hi] = { mode: "source", e: st.e, failed: why }; show(hist[hi], false); };
  try {
    const L = await pdfLib();
    const doc = await (pdfs[a.source] = pdfs[a.source] || L.getDocument({ url: "pablo://source/" + src.file,
      standardFontDataUrl: PDFJS + "standard_fonts/", cMapUrl: PDFJS + "cmaps/", wasmUrl: PDFJS + "wasm/" }).promise);
    const pg = await doc.getPage(n), box = $("pbody");
    if (hist[hi] !== st || !box) return;
    const vp = pg.getViewport({ scale: (box.clientWidth - 24) / pg.getViewport({ scale: 1 }).width }), dpr = devicePixelRatio || 1;
    const cv = h("canvas", { width: Math.floor(vp.width * dpr), height: Math.floor(vp.height * dpr), style: `width:${vp.width}px;height:${vp.height}px` });
    const sheet = box.appendChild(h("div", { class: "pg", style: `width:${vp.width}px` }, cv));
    await pg.render({ canvasContext: cv.getContext("2d"), viewport: vp, transform: dpr === 1 ? null : [dpr, 0, 0, dpr, 0, 0] }).promise;
    if (hist[hi] !== st) return;
    if (n !== a.page) { p.dataset.live = "PAGE"; info.textContent = `캡처한 PDF · ${n}쪽 · 근거는 ${a.page}쪽에 있습니다.`; return; }
    const items = (await pg.getTextContent()).items.filter(i => "str" in i), r = findIn(items, a);
    if (r.status !== "FOUND") return fail(r.status);
    const bs = boxes(items, r.start, r.end, vp, L);
    if (!bs.length) return fail("HIDDEN");
    bs.forEach(b => sheet.append(h("div", { class: "hl", style: `left:${b.l}px;top:${b.t}px;width:${b.r - b.l}px;height:${b.b - b.t}px` })));
    box.scrollTop = Math.max(0, Math.min(...bs.map(b => b.t)) - box.clientHeight / 3);
    p.dataset.ms = Math.round(performance.now() - t0); p.dataset.live = "FOUND";
    info.textContent = `✓ 캡처한 PDF ${n}쪽에서 근거를 찾아 표시했습니다.`;
  } catch (err) { console.error("[pdf]", err); fail("ERROR"); }
}

addEventListener("keydown", e => { if (e.key === "Escape") close(); });

// ---- M4.0/M4.1 desktop host only: ChatGPT connection + composer -> persistent Codex app-server thread (desktop/) ----
if (window.pabloHost && pabloHost.chat) {
  const box = document.querySelector("#chat > .composer"), [inp, btn] = box.querySelectorAll("input, button");
  const st = box.insertBefore(h("small", { class: "muted", id: "agent" }), btn);
  const pick = box.insertBefore(h("select", { id: "model", title: "모델" }), st);  // the ChatGPT account's catalog (/v1/models, visibility "list")
  pick.addEventListener("change", () => pabloHost.setModel(pick.value));
  const models = () => pabloHost.models().then(r => {
    pick.textContent = ""; r.models.forEach(m => pick.append(h("option", { value: m.slug }, m.name))); pick.value = r.model || "";
  });
  const acct = $("chat").insertBefore(h("div", { id: "acct" }), box);  // sign-in card, then a one-line connection status
  const LABEL = { Connecting: "연결 중…", Ready: "준비됨", Thinking: "생각 중…", Error: "오류" };
  let out = null, agentSt = "Connecting", authSt = { state: "signed_out" };
  const gate = () => {
    const on = authSt.state === "connected";
    st.textContent = ""; if (on) st.append(agentSt === "Thinking" ? art("think") : "", LABEL[agentSt] || agentSt); box.dataset.agent = agentSt;
    pick.hidden = !on || !pick.options.length; pick.disabled = agentSt === "Thinking";
    inp.disabled = btn.disabled = !on || !V || (agentSt !== "Ready" && agentSt !== "Error");  // Error: the next send restarts app-server
    inp.placeholder = !on ? "ChatGPT에 연결하면 대화할 수 있습니다" : !V ? "새 작업을 만들면 대화할 수 있습니다" : "Pablo에게 물어보세요…";
  };
  const status = (s, err) => { agentSt = s; st.title = err || ""; gate(); };
  const link = (text, on) => h("button", { class: "link", on }, text);
  function account(a) {
    const hello = a.state === "connected" && (authSt.state === "signing_in" || authSt.state === "verifying");  // just signed in
    authSt = a; acct.dataset.state = a.state; acct.textContent = "";
    const err = a.error ? h("p", { class: "muted" }, a.error) : null;
    if (hello) { const x = h("div", { class: "hello" }, art("waving", "pose"), h("p", null, h("b", null, "ChatGPT에 연결되었습니다."))); acct.append(x); setTimeout(() => x.remove(), 8000); }
    if (a.state === "connected") acct.append(h("p", { class: "muted" }, art("head", "ico"), "ChatGPT · 연결됨 · 플랜 사용 가능 · ", link("연결 해제", () => pabloHost.logout())));
    else if (a.state === "signing_in") acct.append(h("div", { class: "call" }, h("p", { class: "head" }, "브라우저에서 ChatGPT 로그인을 마치세요."),
      h("p", null, link("취소", () => pabloHost.cancelLogin()))));
    else if (a.state === "verifying") acct.append(h("div", { class: "call" }, h("p", { class: "head" }, "ChatGPT 플랜 사용 권한을 확인하는 중…")));
    else acct.append(h("div", { class: "call" }, h("p", { class: "head" }, "ChatGPT 계정을 연결하세요"), err,
      h("p", null, h("button", { class: "pill on", id: "signin", on: () => pabloHost.login() }, "ChatGPT로 계속하기"),
        a.state === "error" ? [" ", link("연결 해제", () => pabloHost.logout())] : null)));
    gate();
  }
  const scroll = () => { $("log").scrollTop = $("log").scrollHeight; };
  pabloHost.onAuth(account);
  pabloHost.onAgent(ev => {
    if (ev.type === "model") pick.value = ev.model;
    if (ev.type === "status") {
      if (ev.status === "Ready") models().then(gate);  // after a restart or another sign-in the list may change
      status(ev.status, ev.error);
      if (ev.status === "Error" && ev.error && authSt.state === "connected") live(talk).append(msg("Pablo", null, h("div", { class: "call block" }, h("p", { class: "head" }, "⚠ " + ev.error)))), scroll();
    } else if (ev.type === "delta" && out) { out.textContent += ev.text; scroll(); }
    else if (ev.type === "done") {
      refresh();
      if (out) { out.title = `첫 토큰 ${ev.first ?? "-"} ms · 전체 ${ev.total} ms`; out = null; }
      if (ev.retry) setTimeout(() => { const b = link("다른 모델로 다시 시도", () => { b.remove(); stream(talk); pabloHost.retry().catch(e => { status("Error", e.message); out = null; }); });
        live(talk).append(msg("Pablo", null, h("p", null, b))); scroll(); });  // after the Error card
    } else if (ev.type === "guard") { live(ev.task).append(msg("Pablo", null, guard(ev))); scroll(); refresh(); }
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
    const card = h("div", { class: "call" + (ev.verdict === "WARN" ? "" : " block"), "data-verdict": ev.verdict, "data-act": ev.act || "" },
      h("p", { class: "head" }, HEAD[ev.verdict]), h("p", null, "제안된 작업: ", h("b", null, meaning(ev.text))),
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
  const chat = (text, t) => { talk = t; stream(t); pabloHost.chat(text, t).catch(e => { status("Error", e.message); out = null; }); };
  // M5.1 one input box: the task's material and folder decide where a message goes; both -> the user picks, neither -> say so
  const send = () => {
    const text = inp.value.trim(); if (!text || inp.disabled) return;
    inp.value = ""; talk = V.task.id;
    live(talk).append(msg("You", new Date().toISOString(), h("p", null, text)));
    const d = (M.desk || {})[talk] || {}, pdf = !!d.pdf || (!M.desk && M.pdf), dir = !!d.folder;
    if (pdf && !dir) return ask(text, talk);
    if (dir && !pdf) return chat(text, talk);
    const t = talk, row = h("p", null);
    const go = f => () => { row.textContent = ""; f(text, t); };
    if (pdf && dir) row.append(h("button", { class: "pill on", "data-route": "ask", on: go(ask) }, "PDF에서 답 찾기"), " ",
      h("button", { class: "pill", "data-route": "agent", on: go(chat) }, "작업 폴더에서 실행"));
    else row.append(link("📎 PDF 추가", () => attach("addSource")), " · ", link("📁 작업 폴더 선택", () => attach("pickFolder")));
    live(t).append(msg("Pablo", null, h("div", { class: "call", "data-route": pdf ? "choose" : "none" },
      h("p", { class: "head" }, pdf ? "어디에서 처리할까요?" : "먼저 자료나 작업 폴더를 정해 주세요."), row))); scroll();
  };
  // ---- M5.1 live state: after every Guard / review / answer the panels read the same records again (no view rebuild) ----
  let q = Promise.resolve();
  refresh = to => (q = q.then(() => pabloHost.state()).then(m => {
    const open = hi >= 0 && document.body.classList.contains("panel") ? hist[hi] : null;
    M = m;
    if (to === undefined && !V && $("goal")) return sidebar();  // the new task form stays
    if (to !== undefined || !V || !M.views[V.task.id]) return (select(to || (V && V.task.id)), gate());
    V = M.views[V.task.id]; V.task.at = (M.tasks.find(t => t.id === V.task.id) || {}).at;
    sidebar(); header(); tools(); gate(); finish();
    if (open && open.mode !== "source") show(open, false);  // Intent / Plan / 왜? stay open and show the new state
    Object.values(lives).forEach(l => l.querySelectorAll(".crit:empty").forEach(c => {  // the live card's criteria, once stored
      const a = Object.values(M.views).flatMap(v => v.actions).find(x => x.id === c.closest("[data-act]").dataset.act);
      if (a && a.criteria.length) c.textContent = "관련 기준: " + a.criteria.map(x => x.text).join(" · ");
    }));
  }).catch(e => console.error("[pablo] state", e)));
  const bar = $("chat").insertBefore(h("div", { id: "tools" }), box);
  const attach = kind => pabloHost[kind](V.task.id).then(name => name && refresh(),
    e => { live(V.task.id).append(msg("Pablo", null, h("div", { class: "call block" }, h("p", { class: "head" }, "⚠ " + clean(e))))); scroll(); });
  tools = () => {
    bar.textContent = "";
    if (!V) return;
    const d = (M.desk || {})[V.task.id] || {};
    bar.append(h("span", { id: "src" }, "📎 자료: ", d.pdf ? h("b", null, d.pdf) : "없음", " ", link(d.pdf ? "바꾸기" : "PDF 추가", () => attach("addSource"))),
      h("span", { id: "dir" }, "📁 작업 폴더: ", d.folder ? h("b", null, d.folder) : "없음", " ", link(d.folder ? "바꾸기" : "선택", () => attach("pickFolder"))));
  };
  newTask = () => {
    V = null; close(); sidebar(); header(); tools(); gate();
    const ta = h("textarea", { id: "goal", rows: 5,
      placeholder: "무엇을 할지 적어주세요.\n지켜야 할 조건은 한 줄에 하나씩 적으면 작업 기준이 됩니다." });
    const err = h("p", { class: "muted" }), make = h("button", { class: "pill on", id: "create", on: () => {
      const text = ta.value.trim(); if (!text) return;
      make.disabled = true; err.textContent = "작업을 만드는 중…";
      pabloHost.newTask(text).then(id => refresh(id).then(() => {
        const I = V.intent, n = I.must.length + I.prefer.length;
        live(id).append(msg("Pablo", null, M.tasks.length === 1 ? art("waving", "pose") : null, h("p", null, n ? `작업 기준 ${n}개를 기록했습니다. ` : "작업을 만들었습니다. ",
          link("작업 기준 보기", () => show({ mode: "intent" }))),
          h("p", { class: "muted" }, "PDF를 추가하면 근거를 찾아 답하고, 작업 폴더를 고르면 그 폴더에서 작업합니다.")));
      }), e => { make.disabled = false; err.textContent = clean(e); });
    } }, "작업 만들기");
    const log = $("log"); log.textContent = "";
    log.append(msg("Pablo", null, h("p", null, "새 작업을 시작합니다."), ta, h("p", null, make), err));
    ta.focus();
  };
  const clean = e => String(e.message || e).replace(/^Error invoking remote method [^:]+: (Error: )?/, "");
  // M3.3: with a captured PDF the question goes to Pablo (judge picks quotes, Pablo anchors them); [n] opens the page
  function ask(text, t) {
    talk = t;
    const box = h("div", { class: "asked" }, h("p", { class: "muted" }, "PDF에서 근거를 찾는 중…"));
    live(t).append(msg("Pablo", null, box)); scroll(); status("Thinking");
    pabloHost.ask(text, t).then(r => {
      Object.assign(M.anchors, r.anchors); Object.assign(M.sources, r.sources); M.views[t].checks[r.check.id] = r.check;
      box.textContent = ""; box.dataset.check = r.check.id;
      box.append(h("p", null, cited(r.check.conclusion, r.check.evidence)));
      if (r.dropped.length) box.append(h("p", { class: "muted" }, `PDF에서 찾지 못한 인용 ${r.dropped.length}개는 뺐습니다.`));
      status("Ready"); scroll(); refresh();
    }, e => { box.textContent = ""; box.append(h("div", { class: "call block" }, h("p", { class: "head" }, "⚠ " + e.message.replace(/^Error invoking remote method [^:]+: (Error: )?/, "")))); status("Ready"); });
  }
  btn.addEventListener("click", send);
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
