// M4.2 Pablo Controller: Codex approval request -> runtime action -> Pablo Guard (python -m pablo_v2) -> accept | decline,
// then the finished item -> ExecutionRecord + PostReview. Orchestration only: verdicts, decisions and reviews stay in
// the M2 skill (gate / decide / record / review); nothing raw from the protocol reaches it, only a plain description.
// ALLOW: silent accept. BLOCK: decline + reason. WARN: wait for the user's [진행] / [취소] in the conversation.
// Events (ctl.on "ui"): {type:"guard", id?, act?, task, verdict: "WARN"|"BLOCK"|"ERROR", text, reason} | {type:"review", act, executed, alignment};
// "trace" for checks/logs.
const { execFile } = require("child_process");
const { app } = require("electron");
const { EventEmitter } = require("events");
const fs = require("fs");
const path = require("path");

const ctl = new EventEmitter();
ctl.root = null;  // agent.workspace: action paths are shown relative to it
ctl.dir = null;   // the opened viewer's state dir (skill.json, intent.json)
ctl.env = async () => ({});  // main: PABLO_ACCESS_TOKEN + PABLO_MODEL for the judge (this child only)
const SRC = path.join(__dirname, "..", "src");
// M6: the installed app runs the PyInstaller onedir backend from resources (no system Python); dev runs the source
const BACKEND = app.isPackaged ? [path.join(process.resourcesPath, "pablo-backend", "pablo-backend.exe")] : ["python", "-m", "pablo_v2"];
const KIND = { add: "파일 생성", delete: "파일 삭제", update: "파일 수정" };
const waiting = new Map(), ran = new Map();  // WARN id -> resolve; app-server item id -> {act, task}
let q = Promise.resolve(), n = 0;

// one python call at a time: skill.json has a single writer
function py(...args) {
  const run = async () => {
    const env = { ...process.env, ...(app.isPackaged ? {} : { PYTHONPATH: SRC }), ...await ctl.env() };
    return new Promise((res, rej) => execFile(BACKEND[0], [...BACKEND.slice(1), ...args, "--json", "--dir", ctl.dir],
      { env, encoding: "utf8", windowsHide: true, maxBuffer: 1 << 24 }, (err, out) => {
        let r; try { r = JSON.parse(out); } catch { return rej(err || new Error("bad output: " + out.slice(0, 200))); }
        r.ok ? res(r) : rej(new Error(r.message));
      }));
  };
  return (q = q.then(run, run));
}
const tasks = () => { try { return JSON.parse(fs.readFileSync(path.join(ctl.dir, "skill.json"), "utf8")).tasks.map(t => t.id); } catch { return []; } };
const ui = (t, ev) => ctl.emit("ui", { type: "guard", task: t.task.split("#").pop(), ...ev });
const trace = ev => { ctl.emit("trace", ev); console.log("[pablo]", JSON.stringify(ev)); };

// protocol request -> one plain action description (+ the short text the conversation shows)
function describe(m, t) {
  const p = m.params, rel = f => path.relative(ctl.root || "", f) || f;
  if (m.method === "item/commandExecution/requestApproval") return { text: `명령 실행: ${p.command}`, files: [] };
  if (m.method === "item/fileChange/requestApproval") {
    const cs = (t.items[p.itemId] || {}).changes || [];
    if (!cs.length) return null;
    const text = cs.map(c => `${KIND[c.kind.type] || "파일 변경"}: ${rel(c.path)}`).join(", ");
    const diff = cs.map(c => c.diff ? `--- ${rel(c.path)}\n${c.diff.slice(0, 1500)}` : "").filter(Boolean).join("\n");
    return { text, detail: diff, files: cs.map(c => rel(c.path)) };
  }
  return null;  // permissions escalation and anything else: not an action Pablo grants (sandbox stays as is)
}

ctl.request = async (m, t) => {
  const d = describe(m, t), task = t.task.split("#").pop();
  if (!d) {
    ui(t, { verdict: "ERROR", text: "권한 요청", reason: "작업 폴더 밖의 권한은 주지 않습니다. 요청을 거절했습니다." });
    return "decline";
  }
  let g;
  try { g = await py("gate", task, d.detail ? `${d.text}\n${d.detail}` : d.text); }
  catch (e) {
    console.error("[pablo] gate", e.message);
    ui(t, { verdict: "ERROR", text: d.text, reason: "Pablo가 이 작업을 검토하지 못했습니다. 실행하지 않았습니다." });
    return "decline";
  }
  const act = g.action.id, verdict = g.action.verdict;
  let ok = verdict === "ALLOW", why = "";
  if (verdict === "BLOCK") ui(t, { act, verdict, text: d.text, reason: g.reason });
  if (verdict === "WARN") {  // never auto-approved: the item waits for the user
    const id = String(++n);
    ok = await new Promise(r => { waiting.set(id, r); ui(t, { id, act, verdict, text: d.text, reason: g.reason }); });
    why = ok ? "사용자가 대화에서 진행을 선택했습니다." : "사용자가 대화에서 취소했습니다.";
  }
  if (verdict === "BLOCK") why = "Guard BLOCK: 실행하지 않았습니다.";
  await py("decide", act, ok ? "proceed" : "reject", "--reason", why).catch(e => console.error("[pablo] decide", e.message));
  trace({ task, act, step: g.step, intent: g.intent, excluded: g.excluded, action: d.text, verdict, decision: ok ? "accept" : "decline" });
  if (ok) ran.set(m.params.itemId, { act, task });
  else review(act, ["--not-executed"], `실행하지 않음: ${d.text}`);
  return ok ? "accept" : "decline";
};

// WARN answer from the conversation
ctl.decide = (id, proceed) => {
  const r = waiting.get(id);
  if (!r) throw new Error("이미 처리된 요청입니다.");
  waiting.delete(id); r(!!proceed);
};
// app-server stopped or the turn ended: open WARN questions are cancelled (fail closed)
ctl.cancelAll = () => { for (const r of waiting.values()) r(false); waiting.clear(); };

// an accepted item finished -> ExecutionRecord -> PostReview
ctl.item = (it, t) => {
  const a = ran.get(it.id);
  if (!a) return;
  ran.delete(it.id);
  const rel = f => path.relative(ctl.root || "", f) || f, args = [], cmd = it.type === "commandExecution";
  const executed = it.status === "completed" || (cmd && it.exitCode != null);
  const summary = cmd ? `명령 실행: ${it.command}` : (it.changes || []).map(c => `${KIND[c.kind.type] || "파일 변경"}: ${rel(c.path)}`).join(", ");
  if (!executed) args.push("--not-executed");
  else if (!cmd) args.push("--files", ...(it.changes || []).map(c => rel(c.path)));
  if (cmd) args.push("--observe", `exit code ${it.exitCode}; output: ${(it.aggregatedOutput || "").slice(0, 500)}`);
  const failed = it.status !== "completed" || (cmd && it.exitCode !== 0);
  if (failed) {
    args.push("--error", `${it.status}${cmd ? ` (exit code ${it.exitCode})` : ""}`);
    ui(t, { verdict: "ERROR", text: summary, reason: "실행에 실패했습니다." });
  }
  review(a.act, args, summary);
};
function review(act, args, summary) {
  py("record", act, summary, ...args)
    .then(r => py("review", r.execution.id).then(v => {
      ctl.emit("ui", { type: "review", act, executed: r.execution.executed, alignment: v.review.action_alignment });  // under the action's card, if any
      trace({ act, execution: r.execution.id, executed: r.execution.executed,
        files: r.execution.changed_files, review: v.review.id, alignment: v.review.action_alignment, step_status: v.review.plan_step_status }); }))
    .catch(e => console.error("[pablo] record/review", e.message));
}
// resolves once queued records and reviews are written
ctl.idle = async () => { for (let p; p !== q;) { p = q; await p.catch(() => {}); await new Promise(r => setTimeout(r, 50)); } };

// M3.3: answer from the captured PDF -> {check, anchors, sources, dropped} (the judge runs with the same account)
ctl.ask = (task, question, src) => py("ask", task, question, ...(src ? ["--source", src] : []));

Object.assign(ctl, { tasks, py });
module.exports = ctl;
