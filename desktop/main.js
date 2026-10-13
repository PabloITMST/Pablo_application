// Pablo desktop host: shows the viewer HTML; only the right Source panel embeds a live page (<webview>).
// Usage: npm start (the app's own state in userData/state) | npm start -- <path/to/view-T1.html>[#E1] (export/debug snapshot)
const { app, BrowserWindow, dialog, ipcMain, protocol, safeStorage, session, shell, webContents } = require("electron");
const fs = require("fs");
const path = require("path");
const { run } = require("./locate");
const agent = require("./agent");
const ctl = require("./controller");
const siwc = require("./siwc");
const checkpoint = require("./checkpoint");
const where = require("./where");

// M6 Squirrel installer events (Setup.exe runs the app with these): add/remove the shortcuts, then exit at once.
// The few lines Forge's template gets from electron-squirrel-startup.
const squirrel = (/^--squirrel-(install|updated|uninstall|obsolete)$/.exec(process.platform === "win32" && process.argv[1] || "") || [])[1];
if (squirrel) {
  const flag = { install: "--createShortcut", updated: "--createShortcut", uninstall: "--removeShortcut" }[squirrel];
  const update = path.join(path.dirname(process.execPath), "..", "Update.exe");
  if (flag) require("child_process").spawn(update, [`${flag}=${path.basename(process.execPath)}`], { detached: true }).on("close", () => app.quit());
  else app.quit();
}

const PARTITION = "pablo-source";  // in-memory: no cookies or logins kept between runs
const web = url => /^https?:\/\//i.test(url);

// M3.3 PDF panel: pablo://pdfjs/* (pdf.js files) and pablo://source/SRCn.pdf (the captured copy), read-only.
// Default session only, so the Source webview (own partition) cannot reach it.
protocol.registerSchemesAsPrivileged([{ scheme: "pablo", privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } }]);
const PDFJS = path.join(__dirname, "node_modules", "pdfjs-dist");
const TYPES = { ".mjs": "text/javascript", ".pdf": "application/pdf", ".wasm": "application/wasm", ".bcmap": "application/octet-stream",
  ".pfb": "application/octet-stream", ".ttf": "font/ttf" };
function served(u) {
  const { host, pathname } = new URL(u), p = decodeURIComponent(pathname);
  if (host === "pdfjs" && /^\/build\/pdf(\.worker)?\.mjs$/.test(p)) return path.join(PDFJS, p);
  if (host === "pdfjs" && /^\/(standard_fonts|cmaps|wasm)\/[\w.-]+$/.test(p)) return path.join(PDFJS, p);
  if (host === "source" && /^\/SRC\d+\.pdf$/.test(p) && ctl.dir) return path.join(ctl.dir, "sources", p);
  return null;
}
function serve(req) {
  const f = served(req.url);
  if (!f || !fs.existsSync(f)) return new Response("not found", { status: 404 });
  return new Response(fs.readFileSync(f), { headers: { "content-type": TYPES[path.extname(f)] || "application/octet-stream",
    "access-control-allow-origin": "*" } });
}

function open(arg) {
  const [file, hash] = arg.split("#");
  const win = new BrowserWindow({ width: 1440, height: 900, title: "Pablo",
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, sandbox: true,
      nodeIntegration: false, webviewTag: true } });
  win.removeMenu();
  ctl.dir = path.dirname(path.resolve(file));  // ponytail: one state dir per app; windows on other dirs would share it
  win.loadFile(path.resolve(file), hash ? { hash } : {});
  return win;
}

app.on("web-contents-created", (_, wc) => {
  // every new window (target=_blank, ↗) goes to the user's browser
  wc.setWindowOpenHandler(({ url }) => { if (web(url)) shell.openExternal(url); return { action: "deny" }; });
  if (wc.getType() === "window") {
    wc.on("will-navigate", e => e.preventDefault());  // the viewer page itself never navigates away
    wc.on("will-attach-webview", (e, prefs, params) => {
      delete prefs.preload;
      Object.assign(prefs, { nodeIntegration: false, contextIsolation: true, sandbox: true });
      if (!web(params.src) || params.partition !== PARTITION) e.preventDefault();
    });
  }
});

// the viewer asks: find this quote in that webview. Only that request, only for its own webview.
const str = (x, n) => typeof x === "string" && x.length <= n;
ipcMain.handle("pablo:locate", (e, id, q) => {
  const g = webContents.fromId(id);
  if (!g || g.getType() !== "webview" || g.hostWebContents !== e.sender) throw new Error("not this window's webview");
  if (!q || !str(q.exact, 2000) || !q.exact.trim() || !str(q.prefix, 200) || !str(q.suffix, 200)) throw new Error("bad quote");
  return run(g, q);
});

// M4.0 chat: only top-level Pablo windows talk to the agent; events go to every window
const fromWindow = e => { if (e.sender.getType() !== "window") throw new Error("not a Pablo window"); };
const broadcast = (ch, ev) => BrowserWindow.getAllWindows().forEach(w => w.webContents.send(ch, ev));
const known = task => { if (!ctl.tasks().includes(task)) throw new Error("unknown task"); };
ipcMain.handle("pablo:chat", async (e, text, task) => {
  fromWindow(e); if (!str(text, 20000) || !text.trim()) throw new Error("bad message");
  known(task);
  if (auth.state !== "connected") throw new Error("ChatGPT에 먼저 연결하세요.");
  if (agent.busy() || preparing) throw new Error("이전 요청이 아직 진행 중입니다.");
  const prep = preparing = { task };  // until the agent's turn starts: 중지 now means "do not start it"
  try { return await chatTurn(text, task, prep); } finally { if (preparing === prep) preparing = null; }
});
let preparing = null;
async function chatTurn(text, task, prep) {
  const at = Date.now();
  logChat(task, { role: "user", text, at: new Date(at).toISOString() });
  reply = { task, at: new Date(at + 2).toISOString(), text: "" };  // the agent's answer sorts right after the message
  // criteria said in the message ("..., X는 건드리지 마") become this task's intent before the agent starts: Guard and
  // the brief below already use them. The request itself is the plan step, never a goal.
  const said = await ctl.py("say", text, "--request", "--task", task).catch(err => { console.error("[pablo] say", err.message); return null; });
  // hedged ones the policy held back ("~것 같긴 한데") wait for the user's click: [기준으로 추가] / [무시]
  const held = said ? said.candidates.filter(k => k.status === "pending").map(k => ({ id: k.id, text: k.features.statement || k.text })) : [];
  if (said && (said.added.length || held.length)) {
    const entry = { role: "intent", at: new Date(at + 1).toISOString(), items: said.added, ...(held.length ? { pending: held } : {}) };
    logChat(task, entry);
    broadcast("pablo:agent", { type: "intent", task, ...entry });
  }
  const d = desk(), own = d.workspace[task];
  agent.workspace = ctl.root = own || envWorkspace;  // the task's folder (M5.1), else PABLO_WORKSPACE, else read-only
  agent.network = !!d.net[task];  // 인터넷: off unless the user turned it on for this task
  // D4: the work folder as it is before this turn; after it, what changed becomes a card with 보기 / 되돌리기
  const work = agent.workspace;
  turnCp = work ? { task, work, tree: await checkpoint.snapshot(ctl.dir, task, work).catch(err => { console.error("[pablo] checkpoint", err.message); return null; }) } : null;
  // the task's criteria and the facts Pablo located (PDF answers, research) go to the agent, and become the step's basis
  const brief = process.env.PABLO_BRIEF === "0" ? null  // checks of the Guard as a safety net turn it off
    : await ctl.py("brief", task).catch(err => { console.error("[pablo] brief", err.message); return null; });
  // M5.1: a task made in the app has no CLI plan; the request itself is its one step (wiring only, Guard unchanged)
  if (own) await ctl.py("plan", task, "--steps", JSON.stringify([{ action: text.slice(0, 500), basis: brief ? brief.basis : [] }]))
    .catch(err => console.error("[pablo] plan", err.message));  // no plan -> Guard warns on every action (fail safe)
  saveDesk(x => { x.last = task; });
  const undone = (d.undone || {})[task];  // the user undid a change since the last message: the agent hears it once
  if (undone) saveDesk(x => { delete x.undone[task]; });
  const note = undone ? `[Pablo] 사용자가 앞선 변경을 되돌렸습니다: ${undone.join(", ")}. 이 파일들은 그 변경 전 상태입니다. 필요하면 다시 확인하세요.` : null;
  if (prep.stop) {  // 중지 before it started: the same ending as an interrupted turn (log, UI), then the real status again
    agent.emit("event", { type: "done", status: "interrupted", first: null, total: Date.now() - at });
    return agent.emit("event", { type: "status", status: agent.status });
  }
  return agent.send(text, ctl.dir + "#" + task, brief && brief.text ? { text: brief.text, hash: brief.hash } : null, note);  // each task talks on its own thread
}
// ---- M5.1 app-first workflow: live state, new task, folder and material per task (userData/state/desktop.json) ----
let envWorkspace = null;
const desk = () => { try { return { workspace: {}, pdf: {}, net: {}, ...JSON.parse(fs.readFileSync(path.join(ctl.dir, "desktop.json"), "utf8")) }; }
  catch { return { workspace: {}, pdf: {}, net: {} }; } };
const saveDesk = f => { const d = desk(); f(d); fs.writeFileSync(path.join(ctl.dir, "desktop.json"), JSON.stringify(d, null, 1)); };
// the conversation per task (state/chat.json; this file is its only writer, viewer.py reads it): the user's messages, the
// agent's finished replies, PDF questions with the check that answered them. A reopened app shows the same conversation.
let reply = null;  // the running turn's answer: {task, at, text}
function logChat(task, entry) {
  const f = path.join(ctl.dir, "chat.json");
  let log = {};
  try { log = JSON.parse(fs.readFileSync(f, "utf8")); } catch {}
  (log[task] = Array.isArray(log[task]) ? log[task] : []).push(entry);
  fs.writeFileSync(f, JSON.stringify(log, null, 1));
}
const pick = (e, opts) => dialog.showOpenDialog(BrowserWindow.fromWebContents(e.sender), opts).then(r => r.canceled ? null : r.filePaths[0]);
ipcMain.handle("pablo:state", async e => {
  fromWindow(e);
  const m = await ctl.py("state"), d = desk();
  m.desk = Object.fromEntries(m.tasks.map(t => { const w = d.workspace[t.id] || envWorkspace, p = d.pdf[t.id];
    return [t.id, { folder: w ? path.basename(w) : null, pdf: p ? p.title : null, net: !!(d.net || {})[t.id],
      route: (d.route || {})[t.id] === "ask" ? "ask" : "agent" }]; }));  // names only, no paths
  m.last = d.last;
  return m;
});
// A3: a reproduction task starts with the research-integrity criteria (task scope, editable like any other)
const REPRO = ["평가(test) 데이터는 학습, 튜닝, 모델 선택에 절대 쓰지 마.", "논문에 적힌 설정값은 근거 없이 바꾸지 마.",
  "결과 수치는 직접 써 넣지 말고 실행한 결과에서만 가져와."];
ipcMain.handle("pablo:new-task", async (e, text, opts) => {
  fromWindow(e); if (!str(text, 4000) || !text.trim()) throw new Error("bad task");
  const lines = [...text.split(/\r?\n/).map(x => x.trim()).filter(Boolean), ...(opts && opts.repro === true ? REPRO : [])];
  const t = await ctl.py("task", lines[0], "--checks", "[]");  // first line = the goal; no research loop in the app
  // the other lines are this task's criteria: task scope, so they never reach other tasks
  for (const l of lines.slice(1)) await ctl.py("say", l, "--scope", "task", "--task", t.task.id);
  saveDesk(x => { x.last = t.task.id; });
  return t.task.id;
});
ipcMain.handle("pablo:pick-folder", async (e, task) => {
  fromWindow(e); known(task);
  const dir = await pick(e, { title: "작업 폴더 선택", properties: ["openDirectory"] });
  if (!dir) return null;
  const w = workspace(dir);
  saveDesk(x => { x.workspace[task] = w; x.last = task; });
  return path.basename(w);
});
// a task with both a paper and a work folder: where the composer sends (the agent by default; it knows the paper's facts)
ipcMain.handle("pablo:set-route", (e, task, route) => {
  fromWindow(e); known(task); if (!["agent", "ask"].includes(route)) throw new Error("bad route");
  saveDesk(x => { x.route = { ...(x.route || {}), [task]: route }; });
  return route;
});
// D1 인터넷 per task: package installs, dataset downloads, git clone. Each command still goes through the Guard.
ipcMain.handle("pablo:set-net", (e, task, on) => {
  fromWindow(e); known(task);
  saveDesk(x => { x.net = { ...(x.net || {}), [task]: on === true }; });
  return on === true;
});
ipcMain.handle("pablo:add-source", async (e, task) => {
  fromWindow(e); known(task);
  const f = await pick(e, { title: "자료 추가", properties: ["openFile"], filters: [{ name: "PDF", extensions: ["pdf"] }] });
  if (!f) return null;
  const x = (await ctl.py("source", f)).source;  // M3.3 capture: copied to state/sources/SRCn.pdf
  saveDesk(d => { d.pdf[task] = { id: x.id, title: x.title }; d.last = task; });
  return x.title;
});
// M3.3 a question about the captured PDF -> Pablo ask (judge picks quotes, Pablo anchors them) -> answer + citations
ipcMain.handle("pablo:ask", (e, text, task) => {
  fromWindow(e); if (!str(text, 2000) || !text.trim()) throw new Error("bad question");
  known(task);
  if (auth.state !== "connected") throw new Error("ChatGPT에 먼저 연결하세요.");
  saveDesk(x => { x.last = task; });
  const at = new Date().toISOString();
  return ctl.ask(task, text, (desk().pdf[task] || {}).id).then(r => {
    logChat(task, { role: "ask", text, at, check: r.check.id, ...(r.dropped.length ? { dropped: r.dropped.length } : {}) });
    return r;
  }, err => {
    console.error("[pablo] ask", err.message);
    logChat(task, { role: "ask", text, at, error: short(err.message) });
    throw new Error(short(err.message));  // no raw API text in the UI
  });
});
// B4 a held-back criterion: promote it to the task's intent, or drop it (the candidate stays, with its status)
ipcMain.handle("pablo:intent", async (e, task, id, action) => {
  fromWindow(e); known(task);
  if (!str(id, 20) || !/^K\d+$/.test(id) || !["promote", "reject"].includes(action)) throw new Error("bad candidate");
  const r = await ctl.py(action, id);
  return action === "promote" ? r.item.statement : null;
});
// A2 the paper's reproduction conditions -> anchored checks; the conversation gets a card (chat.json "spec")
ipcMain.handle("pablo:spec", async (e, task) => {
  fromWindow(e); known(task);
  if (auth.state !== "connected") throw new Error("ChatGPT에 먼저 연결하세요.");
  const src = (desk().pdf[task] || {}).id;
  if (!src) throw new Error("먼저 논문 PDF를 추가하세요.");
  const at = new Date().toISOString();
  const r = await ctl.py("spec", task, "--source", src).catch(err => { console.error("[pablo] spec", err.message); throw new Error(short(err.message)); });
  logChat(task, { role: "spec", at, checks: r.stated.map(c => c.id), missing: r.missing.map(c => c.id), dropped: r.dropped.length });
  return r;
});
// A5/A6 재현 점검: the agent reads the work folder (read-only sandbox, nothing can change, so no Guard per read) and
// judges every paper condition, open setting and task criterion against the code, configs and run logs -> a table
ipcMain.handle("pablo:audit", async (e, task) => {
  fromWindow(e); known(task);
  if (auth.state !== "connected") throw new Error("ChatGPT에 먼저 연결하세요.");
  if (agent.busy()) throw new Error("이전 요청이 아직 진행 중입니다.");
  const work = desk().workspace[task] || envWorkspace;
  if (!work) throw new Error("먼저 작업 폴더를 선택하세요.");
  const a = await ctl.py("audit", task);
  if (!a.items.length) throw new Error("대조할 논문 조건이나 작업 기준이 없습니다. 먼저 재현 조건을 뽑거나 기준을 적어 주세요.");
  agent.workspace = ctl.root = work; agent.network = false;
  reply = { task, at: new Date().toISOString(), text: "", audit: a.items.map(x => x.id), work,
    values: Object.fromEntries(a.items.filter(x => x.value).map(x => [x.id, x.value])) };  // A2: the paper's value per condition
  saveDesk(x => { x.last = task; });
  return agent.send(a.prompt, ctl.dir + "#" + task, null, null, { readOnly: true, outputSchema: a.schema });
});
// M4.2 the user's answers: WARN [진행]/[취소], and "다른 모델로 다시 시도" after a capacity failure
ipcMain.handle("pablo:decide", (e, id, proceed) => { fromWindow(e); if (!str(id, 20)) throw new Error("bad id"); ctl.decide(id, proceed === true); });
ipcMain.handle("pablo:retry", e => {
  fromWindow(e);
  if (agent.task()) reply = { task: agent.task().split("#").pop(), at: new Date().toISOString(), text: "" };
  return agent.retry();
});
ipcMain.handle("pablo:stop", e => {  // 중지: the running turn (open WARN cards decline), or the one about to start
  fromWindow(e); ctl.cancelAll();
  if (!agent.busy() && preparing) { preparing.stop = true; return true; }
  return agent.interrupt();
});
ipcMain.handle("pablo:agent-status", e => { fromWindow(e); return agent.status; });
ipcMain.handle("pablo:models", e => { fromWindow(e); // the account's catalog (docs: not app-server's bundled list), shown by display_name
  const name = s => ((account && account.models.find(m => m.slug === s)) || {}).name || s;
  return { models: agent.models.map(s => ({ slug: s, name: name(s) })), model: agent.model };
});
ipcMain.handle("pablo:set-model", (e, m) => { fromWindow(e); if (!str(m, 100)) throw new Error("bad model"); agent.setModel(m); });
// D4 after the turn: the folder against its checkpoint; any change -> chat log + a 변경 card in the conversation
let turnCp = null;  // {task, work, tree}
agent.on("event", ev => {
  if (ev.type !== "done" || !turnCp) return;
  const c = turnCp; turnCp = null;
  if (!c.tree) return;
  checkpoint.snapshot(ctl.dir, c.task, c.work).then(async to => {
    const files = await checkpoint.changes(ctl.dir, c.task, c.work, c.tree, to);
    if (!files.length) return;
    const entry = { role: "changes", at: new Date().toISOString(), from: c.tree, to, files };
    logChat(c.task, entry);
    broadcast("pablo:agent", { type: "changes", task: c.task, ...entry });
  }).catch(err => console.error("[pablo] checkpoint", err.message));
});
const SHA = x => typeof x === "string" && /^[0-9a-f]{40}$/.test(x);
const workOf = task => desk().workspace[task] || envWorkspace;
ipcMain.handle("pablo:diff", (e, task, from, to) => {
  fromWindow(e); known(task); if (!SHA(from) || !SHA(to) || !workOf(task)) throw new Error("bad change");
  return checkpoint.diff(ctl.dir, task, workOf(task), from, to);
});
// 되돌리기: the files that changed from -> to go back to from, unless something changed them again since
ipcMain.handle("pablo:undo", async (e, task, from, to) => {
  fromWindow(e); known(task); if (!SHA(from) || !SHA(to) || !workOf(task)) throw new Error("bad change");
  if (agent.busy()) throw new Error("에이전트가 작업하는 중에는 되돌릴 수 없습니다.");
  const work = workOf(task), now = await checkpoint.snapshot(ctl.dir, task, work);
  const mine = await checkpoint.changes(ctl.dir, task, work, from, to), later = await checkpoint.changes(ctl.dir, task, work, to, now);
  const both = mine.filter(m => later.some(l => l.path === m.path)).map(m => m.path);
  if (both.length) throw new Error(`그 뒤에 다시 바뀐 파일이 있어 되돌리지 않았습니다: ${both.join(", ")}`);
  const files = await checkpoint.restore(ctl.dir, task, work, from, to);
  logChat(task, { role: "undo", at: new Date().toISOString(), of: to, files: files.map(f => f.path) });
  saveDesk(x => { x.undone = { ...(x.undone || {}), [task]: [...new Set([...((x.undone || {})[task] || []), ...files.map(f => f.path)])] }; });
  return files.length;
});
// A3 code panel: a file of the task's work folder, read-only ("config.yaml:5", a change card's path). where.js keeps it
// inside the folder after symlinks, text only, <= 1 MB. The page gets the path relative to the folder, never where it is.
const located = (task, raw) => {
  if (!str(raw, 1000)) throw new Error("bad path");
  const w = where.where(raw), work = workOf(task);
  if (!w) throw new Error("파일 위치를 읽지 못했습니다.");
  if (!work) throw new Error("작업 폴더가 없습니다.");
  return { w, work };
};
ipcMain.handle("pablo:read-file", (e, task, raw, around) => {
  fromWindow(e); known(task);
  const { w, work } = located(task, raw);
  return { ...where.read(work, w.path, Number.isInteger(around) && around > 0 ? around : w.from), ranges: w.ranges };
});
// "VS Code에서 열기" (vscode://file/<abs>:<line>; no VS Code -> the file's own app, else its folder) | "폴더에서 보기"
ipcMain.handle("pablo:open-file", async (e, task, raw, line, how) => {
  fromWindow(e); known(task); if (!["vscode", "folder"].includes(how)) throw new Error("bad open");
  const { w, work } = located(task, raw), abs = where.locate(work, w.path).real;
  if (how === "folder") { shell.showItemInFolder(abs); return "folder"; }
  const at = Number.isInteger(line) && line > 0 ? line : w.from || 1;
  const url = "vscode://file/" + encodeURI(abs.replace(/\\/g, "/")).replace(/#/g, "%23").replace(/\?/g, "%3F") + ":" + at;
  try { await shell.openExternal(url); return "vscode"; }
  catch {
    if (!(await shell.openPath(abs))) return "app";
    shell.showItemInFolder(abs); return "folder";
  }
});
// before the broadcast below: the reply is in chat.json when the window hears "done" and reads the state again
agent.on("event", ev => {
  if (!reply) return;
  if (ev.type === "delta") reply.text += ev.text;
  if (ev.type !== "done") return;
  const r = reply; reply = null;
  try {
    if (r.audit) {  // 재현 점검: the answer is JSON (outputSchema); only the asked ids are kept
      const entry = { role: "audit", at: r.at, status: ev.status, ...audited(r) };
      if (ev.error) entry.error = short(ev.error);
      logChat(r.task, entry);
      broadcast("pablo:agent", { type: "audit", task: r.task, ...entry });
    } else logChat(r.task, { role: "agent", text: r.text, at: r.at, status: ev.status, ...(ev.error ? { error: short(ev.error) } : {}) });
  } catch (err) { console.error("[pablo] chat log", err.message); }
});
// the turn's last agent message is the answer (outputSchema shapes only that one; earlier ones are progress notes)
agent.on("item", it => { if (reply && it.type === "agentMessage") reply.last = it.text; });
function audited(r) {
  try {
    const j = JSON.parse((r.last || r.text).trim().replace(/^```(?:json)?\s*|\s*```$/g, "")), asked = new Set(r.audit);
    const items = (j.items || []).filter(x => x && asked.has(x.id)).map(x => ({ id: x.id, status: String(x.status),
      where: String(x.where || ""), found: String(x.found || "").slice(0, where.FOUND), note: String(x.note || "").slice(0, 300) }));
    // A2: the model says where and what is there; Pablo opens that file and looks (the line, the text, the paper's value)
    for (const x of items) Object.assign(x, where.verify(r.work, x, (r.values || {})[x.id]));
    const n = items.reduce((m, x) => ({ ...m, [x.check]: (m[x.check] || 0) + 1 }), {});
    console.log("[pablo] audit checked:", JSON.stringify(n));
    return { items, summary: String(j.summary || "").slice(0, 1000) };
  } catch { return r.text.trim() ? { items: [], summary: "", unreadable: true } : { items: [], summary: "" }; }
}
agent.on("event", ev => broadcast("pablo:agent", ev.type === "status" && ev.error ? { ...ev, error: short(ev.error) } : ev));
agent.onRequest = ctl.request;
agent.on("item", ctl.item);
ctl.on("ui", ev => broadcast("pablo:agent", ev));
agent.on("event", ev => ev.type === "done" && ctl.cancelAll());  // a WARN left open when the turn ends is a cancel
agent.on("event", ev => ev.type === "done" && console.log(`[agent] turn ${ev.status}: first token ${ev.first} ms, total ${ev.total} ms`));

// ---- M4.1 ChatGPT connection (Sign in with ChatGPT). Tokens live here and in siwc.js only; the renderer gets {state, error}.
// state: signed_out | signing_in | verifying | connected | error
let auth = { state: "signed_out" }, account = null, timer = null;
const setAuth = (state, error) => { auth = { state, error: error || undefined }; broadcast("pablo:auth", auth); };
const P = "openai_chatgpt_plan";  // https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server
const PROVIDER = [["model_provider", `"${P}"`], [`model_providers.${P}.name`, '"ChatGPT plan"'], [`model_providers.${P}.base_url`, '"https://api.openai.com/v1"'],
  [`model_providers.${P}.env_key`, '"ACCESS_TOKEN"'], [`model_providers.${P}.wire_api`, '"responses"'],
  [`model_providers.${P}.requires_openai_auth`, "false"], [`model_providers.${P}.supports_websockets`, "false"]].flatMap(([k, v]) => ["-c", `${k}=${v}`]);
// app-server failures -> the same short messages as sign-in
function short(err) {
  if (/server_?overloaded|at capacity/i.test(err)) return siwc.SAY.overloaded;
  const m = String(err), code = (m.match(/subscription_sharing_\w+|chatpass_v2_\w+/) || [""])[0];
  const status = +((m.match(/\b(401|403|429|503)\b/) || [])[1] || 0);
  if (code || status) return siwc.SAY[siwc.classify(code, status)];
  if (/^responses\b/.test(m)) return siwc.SAY.inference_failed;  // the judge's own API call (llm.py), other failures
  return m.length > 200 ? m.slice(0, 200) + "…" : m;
}
function fail(e) {
  console.error("[auth]", e.code || "", e.detail || e.message);
  setAuth(siwc.has() ? "error" : "signed_out", e instanceof siwc.AuthError ? e.message : short(e.message));
}
// saved or fresh credentials -> plan usage proven (models + one inference) -> app-server with that token
async function connect() {
  setAuth("verifying");
  try {
    const v = await siwc.verify();
    if (!v) return setAuth("signed_out");
    account = { models: v.models };  // [{slug, name}] from /v1/models
    console.log("[auth] account models:", v.models.map(m => m.slug).join(", "));  // account catalog: limits app-server models and the picker
  } catch (e) { return fail(e); }
  setAuth("connected"); schedule();
  agent.start().catch(() => {});  // agent errors show as agent status
}
// refresh 5 min before expiry: new token -> restart app-server -> thread/resume (M4.0 restart path)
function schedule() {
  clearTimeout(timer);
  timer = setTimeout(refresh, Math.max(10000, siwc.expiresAt() - Date.now() - 5 * 60 * 1000));
}
async function refresh() {
  if (agent.busy()) return agent.once("event", function wait(ev) { ev.type === "done" ? refresh() : agent.once("event", wait); });
  try { await siwc.token(true); } catch (e) { await agent.stop(); return fail(e); }
  schedule();
  if (auth.state === "connected") agent.restart().catch(() => {});
}
agent.on("event", ev => ev.type === "done" && /\b401\b|Unauthorized/i.test(ev.error || "") && auth.state === "connected" && refresh());
// the Guard judge, same account. No token (expired / signed out) must not stop the non-LLM calls (view, record):
// the auth card shows the error, and the window has to open for the user to sign in again.
ctl.env = async () => {
  const t = await siwc.token().catch(() => null);
  return t ? { PABLO_ACCESS_TOKEN: t, PABLO_MODEL: agent.model } : { PABLO_MODEL: agent.model };
};
agent.launch = async () => ({ args: PROVIDER, models: account && account.models.map(m => m.slug),
  env: { ACCESS_TOKEN: await siwc.token(), CODEX_HOME: path.join(app.getPath("userData"), "codex") } });  // own CODEX_HOME: no codex login, no user config.toml

ipcMain.handle("pablo:auth-status", e => { fromWindow(e); return auth; });
ipcMain.handle("pablo:login", async e => {
  fromWindow(e);
  if (auth.state === "signing_in" || auth.state === "verifying") return;
  setAuth("signing_in");
  try {
    const r = await siwc.login(url => shell.openExternal(url));
    if (r.changed) agent.forget();  // another account: do not resume its thread
  } catch (err) { return fail(err); }
  await agent.stop();
  return connect();
});
ipcMain.handle("pablo:login-cancel", e => { fromWindow(e); siwc.cancelLogin(); });
ipcMain.handle("pablo:logout", async e => {
  fromWindow(e);
  clearTimeout(timer); account = null;
  await agent.stop(); agent.forget();
  const { revoked } = await siwc.logout();
  setAuth("signed_out", revoked ? null : "ChatGPT 쪽 세션 해제는 실패했습니다. 이 기기의 연결은 지웠습니다.");
});

// M4.2: writes only in a disposable folder the user names (PABLO_WORKSPACE); never the Pablo repo or the project
function workspace(dir) {
  if (!dir) return null;
  const w = fs.realpathSync(path.resolve(dir)), inside = (a, b) => !path.relative(a, b).startsWith("..") && !path.isAbsolute(path.relative(a, b));
  // dev: the repo and the project; installed: the app's own files. Both: userData (tokens, state).
  const own = app.isPackaged ? [path.dirname(process.execPath)] : [path.join(__dirname, ".."), process.env.INIT_CWD || process.cwd()];
  for (const p of [...own, app.getPath("userData")].map(x => fs.realpathSync(x)))
    if (inside(p, w) || inside(w, p)) throw new Error("작업 폴더는 Pablo 폴더와 겹치지 않는 별도 폴더여야 합니다.");
  return w;
}

function boot() {
  const data = app.getPath("userData");
  siwc.init(data, safeStorage);
  fs.mkdirSync(path.join(data, "codex"), { recursive: true });
  // Pablo's own CODEX_HOME config. Windows: without a sandbox mode every shell command is "blocked by policy" (agent can't read files).
  // unelevated = restricted-token sandbox, no admin setup; read-only still blocks writes. (-c windows.sandbox did not take effect.)
  if (process.platform === "win32") fs.writeFileSync(path.join(data, "codex", "config.toml"), '[windows]\nsandbox = "unelevated"\n');
  agent.stateFile = path.join(data, "thread.json");
  agent.workspace = ctl.root = envWorkspace = workspace(process.env.PABLO_WORKSPACE);
  return siwc.has() ? connect() : setAuth("signed_out");
}

app.whenReady().then(() => {
  if (squirrel) return;
  session.fromPartition(PARTITION).setPermissionRequestHandler((wc, p, cb) => cb(false));
  protocol.handle("pablo", serve);
  if (!global.pabloCheck) {  // Electron leaves require.main unset for the app entry; check.js sets this
    const arg = process.argv.slice(1).reverse().find(a => /\.html(#.*)?$/i.test(a));
    boot();
    if (arg) open(arg);
    else launch().catch(e => { console.error("[pablo] launch", e.message); app.quit(); });
  }
});
// M5.1 standalone: the app's own state dir; the page is written from it once, then kept live through pablo:state
async function launch(dir = path.join(app.getPath("userData"), "state")) {
  ctl.dir = dir;
  fs.mkdirSync(ctl.dir, { recursive: true });
  const r = await ctl.py("view", "--html");
  return open(r.path + "#" + (desk().last || ""));
}
app.on("window-all-closed", () => app.quit());
app.on("will-quit", () => { clearTimeout(timer); agent.stop(); });

module.exports = { open, boot, launch, auth: () => auth };
