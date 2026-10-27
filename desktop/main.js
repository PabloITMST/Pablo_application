// Pablo desktop host: shows the viewer HTML; only the right Source panel embeds a live page (<webview>).
// Usage: npm start (the app's own state in userData/state) | npm start -- <path/to/view-T1.html>[#E1] (export/debug snapshot)
const { app, BrowserWindow, dialog, ipcMain, protocol, safeStorage, session, shell, webContents } = require("electron");
const crypto = require("crypto");
const fs = require("fs");
const { execFile, execFileSync } = require("child_process");
const path = require("path");
const { run } = require("./locate");
const agent = require("./agent");
const ctl = require("./controller");
const siwc = require("./siwc");
const checkpoint = require("./checkpoint");
const where = require("./where");
const papers = require("./papers");

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
  ".pfb": "application/octet-stream", ".ttf": "font/ttf", ".woff2": "font/woff2" };
const FONTS = path.join(__dirname, "assets", "fonts");  // UI renewal: Pretendard, Geist, Geist Mono (SIL OFL 1.1)
const fontFiles = () => { try { return fs.readdirSync(FONTS).filter(f => /^[\w.-]+\.woff2$/.test(f)); } catch { return []; } };
function served(u) {
  const { host, pathname } = new URL(u), p = decodeURIComponent(pathname);
  if (host === "pdfjs" && /^\/build\/pdf(\.worker)?\.mjs$/.test(p)) return path.join(PDFJS, p);
  if (host === "pdfjs" && /^\/(standard_fonts|cmaps|wasm)\/[\w.-]+$/.test(p)) return path.join(PDFJS, p);
  if (host === "source" && /^\/SRC\d+\.pdf$/.test(p) && ctl.dir) return path.join(ctl.dir, "sources", p);
  if (host === "fonts" && /^\/[\w.-]+\.woff2$/.test(p)) return path.join(FONTS, p);
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
  reply = { task, at: new Date(at + 2).toISOString(), user: new Date(at).toISOString(), text: "" };  // the agent's answer sorts right after the message
  // criteria said in the message ("..., X는 건드리지 마") become this task's intent before the agent starts: Guard and
  // the brief below already use them. The request itself is the plan step, never a goal.
  const said = await ctl.py("say", text, "--request", "--task", task).catch(err => { console.error("[pablo] say", err.message); return null; });
  // hedged ones the policy held back ("~것 같긴 한데") wait for the user's click: [기준으로 추가] / [무시]
  const held = said ? said.candidates.filter(k => k.status === "pending").map(k => ({ id: k.id, text: k.features.statement || k.text })) : [];
  const unread = said ? said.unread || [] : [];  // ③ a rule-like sentence the reader could not classify: the user decides
  if (said && (said.added.length || held.length || unread.length)) {
    const entry = { role: "intent", at: new Date(at + 1).toISOString(), items: said.added, ...(held.length ? { pending: held } : {}),
      ...(unread.length ? { unread } : {}) };
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
  const plan = own ? await ctl.py("plan", task, "--steps", JSON.stringify([{ action: text.slice(0, 500), basis: brief ? brief.basis : [] }]))
    .catch(err => { console.error("[pablo] plan", err.message); return null; }) : null;  // no plan -> Guard warns on every action (fail safe)
  // D4: the request's plan step (P3.1) on its chat entry and on the reply: a plan row finds its conversation
  const step = plan && plan.plan && plan.plan.steps.length ? plan.plan.steps[0].id : null;
  if (step) { patchChat(task, x => x.role === "user" && x.at === new Date(at).toISOString(), { step }); if (reply && reply.task === task) reply.step = step; }
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
// C1: pdf[task] is a list of papers (0.7's one {id, title} reads as a list of one, written back as one on the next save)
const desk = () => { try { return papers.migrate({ workspace: {}, pdf: {}, net: {}, ...JSON.parse(fs.readFileSync(path.join(ctl.dir, "desktop.json"), "utf8")) }); }
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
// fields added to an entry already logged (the last one that matches): D4 a request's plan step, known after it is logged
function patchChat(task, match, fields) {
  const f = path.join(ctl.dir, "chat.json");
  try {
    const log = JSON.parse(fs.readFileSync(f, "utf8")), x = (log[task] || []).filter(match).at(-1);
    if (x) { Object.assign(x, fields); fs.writeFileSync(f, JSON.stringify(log, null, 1)); }
  } catch (err) { console.error("[pablo] chat log", err.message); }
}
const pick = (e, opts) => dialog.showOpenDialog(BrowserWindow.fromWebContents(e.sender), opts).then(r => r.canceled ? null : r.filePaths[0]);
ipcMain.handle("pablo:state", async e => {
  fromWindow(e);
  const m = await ctl.py("state"), d = desk();
  m.desk = Object.fromEntries(m.tasks.map(t => { const w = d.workspace[t.id] || envWorkspace, p = papers.primary(d, t.id);
    return [t.id, { folder: w ? path.basename(w) : null, net: !!(d.net || {})[t.id],
      papers: papers.list(d, t.id).map(x => ({ id: x.id, title: x.title, version: x.version || null, kind: x.kind === "web" ? "web" : "pdf",
        arxiv: x.arxiv || null, primary: !!p && x.id === p.id })),  // arxiv: a search result already here says so
      route: (d.route || {})[t.id] === "ask" ? "ask" : "agent", archived: !!(d.archived || {})[t.id],
      // UI renewal: what the screen remembers per task (set through pablo:set-ui); a missing key has a default
      kind: (d.kind || {})[t.id] || null, done: !!(d.done || {})[t.id], panel: (d.panel || {})[t.id] || null,
      view: (d.view || {})[t.id] || null, tags: (d.tags || {})[t.id] || {}, summary: (d.summary || {})[t.id] || {},
      auto: (d.auto || {})[t.id] || {} }]; }));  // names only, no paths
  m.last = d.last; m.settings = d.settings || {};
  m.host = { shell: agent.shell(), noticed: !!(d.noticed || {}).shell, fonts: fontFiles(),  // ⑤ 5.1: the notice, once
    // D6 the settings' 저장 위치 · 정보: versions, where the app keeps its data, the checkpoints' size (bytes)
    version: VERSION, codex: await codexVersion(), userData: app.getPath("userData"), logs: null, checkpoints: await checkpointBytes() };
  return m;
});
// D6: logs only go to the console (no log files), so there is no log folder to show or open
const VERSION = require("./package.json").version;
let codexVer = null;  // the pinned Codex, read once: its package (dev), else `codex --version` (installed app)
function codexVersion() {
  if (codexVer) return codexVer;
  try { return (codexVer = Promise.resolve(require("@openai/codex-win32-x64/package.json").version.replace(/-win32-x64$/, ""))); } catch {}
  return (codexVer = new Promise(res => execFile(agent.codexBin(), ["--version"], { timeout: 10000, windowsHide: true, encoding: "utf8" },
    (err, out) => res(err ? null : (String(out).match(/\d+\.\d+\.\d+\S*/) || [null])[0]))));
}
let cpSize = { at: 0, bytes: null };  // the checkpoint folder's bytes, measured at most every 30 s (pablo:state runs often)
async function checkpointBytes() {
  if (Date.now() - cpSize.at < 30000) return cpSize.bytes;
  const walk = async d => { let n = 0;
    for (const x of await fs.promises.readdir(d, { withFileTypes: true }).catch(() => [])) {
      const p = path.join(d, x.name);
      n += x.isDirectory() ? await walk(p) : x.isFile() ? (await fs.promises.stat(p).catch(() => ({ size: 0 }))).size : 0;
    }
    return n; };
  cpSize = { at: Date.now(), bytes: ctl.dir ? await walk(path.join(ctl.dir, "checkpoints")) : null };
  return cpSize.bytes;
}
// D6 a folder of the app opened in the file manager: only these, never a path from the page
ipcMain.handle("pablo:open-path", async (e, which) => {
  fromWindow(e);
  const dir = { userData: app.getPath("userData"), checkpoints: ctl.dir && path.join(ctl.dir, "checkpoints"), logs: null }[which];
  if (!["userData", "checkpoints", "logs"].includes(which)) throw new Error("bad folder");
  if (!dir) throw new Error("로그 폴더가 없습니다. 로그는 파일로 남기지 않습니다.");
  fs.mkdirSync(dir, { recursive: true });
  const err = await shell.openPath(dir);
  if (err) throw new Error(`폴더를 열지 못했습니다: ${err}`);
  return true;
});
// A3: a reproduction task starts with the research-integrity criteria (task scope, editable like any other; Python
// keeps the list, and removing one of them needs a reason)
ipcMain.handle("pablo:new-task", async (e, text, opts) => {
  fromWindow(e); if (!str(text, 4000) || !text.trim()) throw new Error("bad task");
  const own = text.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
  const t = await ctl.py("task", own[0], "--checks", "[]", ...(opts && opts.repro === true ? ["--repro"] : []));  // first line = the goal; no research loop in the app
  const lines = [...own, ...(t.repro || [])];
  // the other lines are this task's criteria: task scope, so they never reach other tasks. ③ A line the reader could
  // not classify is never dropped without a word: the conversation keeps every line, read or not, for the user to decide.
  const items = [], unread = [], pending = [];
  for (const l of lines.slice(1)) {
    const r = await ctl.py("say", l, "--scope", "task", "--task", t.task.id);
    items.push(...r.added); unread.push(...(r.unread || []));
    pending.push(...r.candidates.filter(k => k.status === "pending").map(k => ({ id: k.id, text: k.features.statement || k.text })));
  }
  if (items.length || unread.length || pending.length)
    logChat(t.task.id, { role: "intent", at: new Date().toISOString(), items, ...(pending.length ? { pending } : {}), ...(unread.length ? { unread } : {}) });
  // UI renewal P7: the task's kind (its stages), and a new task opens on its criteria unless settings say rail
  const kind = opts && ["repro", "read", "general"].includes(opts.kind) ? opts.kind : opts && opts.repro === true ? "repro" : null;
  saveDesk(x => { x.last = t.task.id; const s = x.settings || {};
    if (kind) x.kind = { ...(x.kind || {}), [t.task.id]: kind };
    x.panel = { ...(x.panel || {}), [t.task.id]: { open: s.panel !== "rail", tab: "intent" } };
    if (s.net === true) x.net = { ...(x.net || {}), [t.task.id]: true }; });
  return { id: t.task.id, lines: lines.length - 1, added: items.length, unread: unread.length + pending.length };
});
// A12 the new-task dialog picks PDFs and a folder before the task exists: main keeps what was picked, the page gets an
// opaque token and the name only; pablo:attach-picked adds them to the task made (as add-files / pick-folder would)
const picked = new Map();  // token -> {kind: "pdf" | "folder", path}
const hold = (kind, p) => { const t = crypto.randomUUID(); picked.set(t, { kind, path: p }); return t; };
ipcMain.handle("pablo:pick-pdfs-free", async e => {
  fromWindow(e);
  const r = await dialog.showOpenDialog(BrowserWindow.fromWebContents(e.sender),
    { title: "자료 추가", properties: ["openFile", "multiSelections"], filters: [{ name: "PDF", extensions: ["pdf"] }] });
  return r.canceled || !r.filePaths.length ? null : r.filePaths.slice(0, 20).map(f => ({ token: hold("pdf", f), name: path.basename(f) }));
});
ipcMain.handle("pablo:pick-folder-free", async e => {
  fromWindow(e);
  const dir = await pick(e, { title: "작업 폴더 선택", properties: ["openDirectory"] });
  if (!dir) return null;
  const w = workspace(dir);  // refused at once when it overlaps Pablo's own folders
  return { token: hold("folder", w), name: path.basename(w) };
});
ipcMain.handle("pablo:attach-picked", async (e, task, tokens) => {
  fromWindow(e); known(task);
  if (!Array.isArray(tokens) || !tokens.length || tokens.length > 21 || !tokens.every(t => str(t, 64) && picked.has(t))) throw new Error("bad picks");
  const xs = tokens.map(t => picked.get(t)), pdfs = xs.filter(x => x.kind === "pdf").map(x => x.path), dirs = xs.filter(x => x.kind === "folder");
  if (pdfs.length > 20 || dirs.length > 1) throw new Error("bad picks");
  tokens.forEach(t => picked.delete(t));
  const out = { added: [], failed: [], folder: null };
  if (pdfs.length) {
    const ok = pdfs.filter(isPdf), r = await captureAll(task, ok);
    out.added = r.added;
    out.failed = [...r.failed, ...pdfs.filter(f => !ok.includes(f)).map(f => ({ file: path.basename(f), error: "PDF 파일이 아닙니다." }))];
  }
  if (dirs.length) {
    const w = workspace(dirs[0].path);
    saveDesk(x => { x.workspace[task] = w; x.last = task; });
    out.folder = path.basename(w);
  }
  return out;
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
// UI renewal: what the screen remembers (desktop.json), one whitelisted key at a time; task null = the app's settings
const plain = (v, max) => !!v && typeof v === "object" && !Array.isArray(v) && JSON.stringify(v).length <= max;
const UI = { kind: v => ["repro", "read", "general"].includes(v), done: v => typeof v === "boolean",
  panel: v => plain(v, 200) && typeof v.open === "boolean" && ["intent", "plan", "trace", "evidence"].includes(v.tab),
  view: v => ["time", "stage", "target"].includes(v), tags: v => plain(v, 200000), summary: v => plain(v, 50000) };
const SETTINGS = { view: v => ["time", "stage", "target"].includes(v), tags: v => ["main", "all"].includes(v),
  panel: v => ["open", "rail", "always"].includes(v), net: v => typeof v === "boolean",
  side: v => typeof v === "boolean" };  // A14 panel "always": the right column stays open; A1 side: the sidebar folded
ipcMain.handle("pablo:set-ui", (e, task, key, value) => {
  fromWindow(e);
  if (task === null && key === "settings") {
    if (!plain(value, 500) || Object.entries(value).some(([k, v]) => !SETTINGS[k] || !SETTINGS[k](v))) throw new Error("bad settings");
    saveDesk(x => { x.settings = { ...(x.settings || {}), ...value }; }); return true;
  }
  known(task); if (!UI[key] || !UI[key](value)) throw new Error("bad ui: " + key);
  saveDesk(x => { x[key] = { ...(x[key] || {}), [task]: value }; }); return true;
});
// UI renewal P6: the model writes a stage's summary on request, from that stage's messages (the page sends them: the
// stage is the page's own grouping, a person's tags included). Kept per task and stage with how many messages it read
ipcMain.handle("pablo:summarize", async (e, task, stage, messages) => {
  fromWindow(e); known(task);
  if (auth.state !== "connected") throw new Error("ChatGPT에 먼저 연결하세요.");
  if (!str(stage, 40) || !Array.isArray(messages) || !messages.length || messages.length > 300
    || !messages.every(m => plain(m, 5000) && ["You", "Pablo"].includes(m.who) && str(m.text, 4000))) throw new Error("bad summary");
  const f = path.join(ctl.dir, `summary-${Date.now()}.json`);
  fs.writeFileSync(f, JSON.stringify(messages));
  try {
    const r = await ctl.py("summarize", task, "--stage", stage, "--messages", "@" + f)
      .catch(err => { console.error("[pablo] summarize", err.message); throw new Error(short(err.message)); });
    const v = { text: r.summary, n: messages.length, at: new Date().toISOString() };
    saveDesk(x => { x.auto = { ...(x.auto || {}), [task]: { ...((x.auto || {})[task] || {}), [stage]: v } }; });
    return v;
  } finally { fs.rmSync(f, { force: true }); }
});
// C1: a paper joins the task's list (one PDF per task until 0.7); the same file again is the same paper
const join = (task, entry, replaces) => saveDesk(d => {
  const ps = papers.list(d, task), at = ps.findIndex(p => p.id === replaces || p.id === entry.id);
  d.pdf[task] = at < 0 ? [...ps, entry] : ps.map((p, i) => i === at ? entry : p).filter((p, i) => i === at || p.id !== entry.id);
  if (replaces && (d.primary || {})[task] === replaces) d.primary[task] = entry.id;  // a newer version stays the 주 논문
  d.last = task;
});
// several PDFs at once (the dialog takes many; a drop on the window gives their paths): one capture each, in order;
// one that fails does not stop the rest -> {added: [titles], failed: [{file, error}]}
async function captureAll(task, files) {
  const out = { added: [], failed: [] };
  for (const f of files) {
    try {
      const x = (await ctl.py("source", f)).source;  // M3.3 capture: copied to state/sources/SRCn.pdf
      const same = papers.list(desk(), task).some(p => p.id === x.id);  // the same file again: said, not added twice
      join(task, { id: x.id, title: x.title });
      out.added.push({ title: x.title, same });
    } catch (err) {
      console.error("[pablo] source", err.message);
      out.failed.push({ file: path.basename(f), error: /pypdf|PdfRead|EOF|xref|startxref/i.test(err.message) ? "PDF를 읽지 못했습니다." : short(err.message) });
    }
  }
  return out;
}
// the dialog only picks (so the page can show "N개 중 i번째" while each is added through pablo:add-files)
ipcMain.handle("pablo:pick-pdfs", async (e, task) => {
  fromWindow(e); known(task);
  const r = await dialog.showOpenDialog(BrowserWindow.fromWebContents(e.sender),
    { title: "자료 추가", properties: ["openFile", "multiSelections"], filters: [{ name: "PDF", extensions: ["pdf"] }] });
  return r.canceled || !r.filePaths.length ? null : r.filePaths;
});
// PDFs dropped on the window (preload turns each File into its path): only real PDF files, as the dialog would allow
const isPdf = f => { try {
  if (!str(f, 1000) || !path.isAbsolute(f) || !/\.pdf$/i.test(f) || !fs.statSync(f).isFile() || fs.statSync(f).size > arxiv.max) return false;
  const fd = fs.openSync(f, "r"), head = Buffer.alloc(5); fs.readSync(fd, head, 0, 5, 0); fs.closeSync(fd);
  return head.toString("latin1") === "%PDF-";
} catch { return false; } };
ipcMain.handle("pablo:add-files", async (e, task, files) => {
  fromWindow(e); known(task);
  if (!Array.isArray(files) || !files.length || files.length > 20) throw new Error("bad files");
  const ok = files.filter(isPdf), r = await captureAll(task, ok);
  r.failed.push(...files.filter(f => !ok.includes(f)).map(f => ({ file: path.basename(String(f)), error: "PDF 파일이 아닙니다." })));
  return r;
});
// C2 arXiv: "arXiv:2510.10114", an abs/pdf link. main downloads it (the agent never does): https://arxiv.org/pdf/<id> only,
// <= 50 MB, <= 60 s, then the usual capture. One file per paper (state/papers/arxiv-<id>.pdf): a newer version saved over
// it is a new source, and the old one's anchors are resolved against it (VALID / STALE / UNRESOLVED) so the user hears
// whether the evidence moved. The version and the bytes' sha256 stay with the paper.
const arxiv = { base: "https://arxiv.org/pdf/", api: "https://export.arxiv.org/api/query", max: 50 << 20, ms: 60000 };
const openreview = { base: "https://openreview.net/", max: 50 << 20, ms: 60000 }, crossref = { api: "https://api.crossref.org/" };  // ⑬  // check.js points both at a local server
ipcMain.handle("pablo:add-arxiv", async (e, task, text, via) => {
  fromWindow(e); known(task); if (!str(text, 300)) throw new Error("bad arXiv id");
  const byDoi = via && str(via.doi, 300) && papers.doi(via.doi) ? papers.doi(via.doi).doi : null;  // ⑬ found by a publisher DOI
  const a = papers.arxiv(text);
  if (!a) throw new Error("arXiv 번호나 링크를 읽지 못했습니다. 예: arXiv:2510.10114, https://arxiv.org/abs/2510.10114v4");
  const data = await papers.fetchPdf(arxiv.base + a.id + (a.version || ""), { origin: new URL(arxiv.base).origin, max: arxiv.max, ms: arxiv.ms })
    .catch(err => { throw new Error(err.name === "TimeoutError" ? "arXiv가 60초 안에 답하지 않았습니다."
      : /[가-힣]/.test(err.message) ? err.message : "arXiv에 연결하지 못했습니다. 인터넷 연결을 확인하세요."); });
  const file = path.join(ctl.dir, "papers", `arxiv-${a.id.replace("/", "_")}.pdf`);
  const before = papers.list(desk(), task).find(p => p.arxiv === a.id);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, data);
  const x = (await ctl.py("source", file, "--arxiv", a.id, ...(byDoi ? ["--doi", byDoi] : []))).source;
  let moved = null;
  if (before && before.id !== x.id) {  // another version of a paper already here: did its evidence move?
    const r = await ctl.py("resolve", "--source", before.id);
    moved = r.anchors.reduce((m, y) => ({ ...m, [y.status]: (m[y.status] || 0) + 1 }), {});
  }
  const version = x.version.arxiv_version || a.version || null;
  join(task, { id: x.id, title: x.title, arxiv: a.id, version, sha256: x.version.content_hash, ...(byDoi ? { doi: byDoi } : {}) }, before && before.id);
  return { title: x.title, version, same: !!before && before.id === x.id, moved };
});
// D10 what an arXiv import would download, before it does: the title (arXiv API), the file name it is saved as, where
// from, and its size (a HEAD on the PDF, redirects followed only inside arxiv.org; null when the server does not say)
ipcMain.handle("pablo:peek-arxiv", async (e, text) => {
  fromWindow(e); if (!str(text, 300)) throw new Error("bad arXiv id");
  const a = papers.arxiv(text);
  if (!a) throw new Error("arXiv 번호나 링크를 읽지 못했습니다. 예: arXiv:2510.10114, https://arxiv.org/abs/2510.10114v4");
  const id = a.id + (a.version || ""), origin = new URL(arxiv.base).origin;
  const meta = (async () => {
    const wait = searched + 3000 - Date.now();
    searched = Date.now() + Math.max(0, wait);
    if (wait > 0) await new Promise(r => setTimeout(r, wait));
    const r = await fetch(`${arxiv.api}?id_list=${encodeURIComponent(id)}&max_results=1`, { signal: AbortSignal.timeout(30000), redirect: "error" });
    return r.ok ? papers.atom((await r.text()).slice(0, 4 << 20)).find(x => x.id === a.id) || null : null;
  })().catch(() => null);
  const size = (async () => {
    let at = new URL(arxiv.base + id), r;
    const signal = AbortSignal.timeout(30000);
    for (let hop = 0; hop < 6; hop++) {
      if (at.origin !== origin) return { bytes: null };
      r = await fetch(at, { method: "HEAD", signal, redirect: "manual", headers: { accept: "application/pdf" } });
      if (r.status < 300 || r.status >= 400 || !r.headers.get("location")) break;
      at = new URL(r.headers.get("location"), at);
    }
    if (r.status === 404) return { missing: true };
    const n = +(r.headers.get("content-length") || 0);
    return { bytes: r.ok && n > 0 ? n : null };
  })().catch(() => null);
  const [m, s] = await Promise.all([meta, size]);
  if (s && s.missing) throw new Error("arXiv에 그 번호의 논문이 없습니다.");
  if (!m && !s) throw new Error("arXiv에 연결하지 못했습니다. 인터넷 연결을 확인하세요.");
  return { id: a.id, version: (m && m.version) || a.version || null, title: m ? m.title.replace(/\s+/g, " ").trim() : null,
    filename: `arxiv-${a.id.replace("/", "_")}.pdf`, source: new URL(arxiv.base).host, bytes: s ? s.bytes : null };
});
// C1: a paper leaves the task's list; what was located in it (answers, conditions, table cells) stays in the records
// D1 a web page as a source: Pablo fetches it itself (Python, evidence.fetch: http(s), a text page, <= 5 MB) and keeps the
// snapshot; questions over the task's sources read it, quotes are anchored with the words next to them. The same address
// again with other text is a new source; its earlier anchors are resolved against the page as it is now.
const webSay = m => /not a web page/.test(m) ? "웹 문서가 아닙니다. PDF는 파일이나 arXiv 번호로 추가하세요."
  : /larger than/.test(m) ? "5 MB가 넘는 문서는 받지 않습니다." : /HTTP Error 404/.test(m) ? "그 주소에 문서가 없습니다(404)."
  : /HTTP Error (\d+)/.test(m) ? `웹 문서를 가져오지 못했습니다(HTTP ${m.match(/HTTP Error (\d+)/)[1]}).` : "웹 문서를 가져오지 못했습니다. 주소와 인터넷 연결을 확인하세요.";
ipcMain.handle("pablo:add-web", async (e, task, text) => {
  fromWindow(e); known(task);
  const url = papers.web(text);
  if (!url) throw new Error("웹 문서 주소(http:// 또는 https://)를 읽지 못했습니다.");
  const before = papers.list(desk(), task).find(p => p.kind === "web" && p.url === url);
  const x = (await ctl.py("source", url).catch(err => { console.error("[pablo] web", err.message); throw new Error(webSay(err.message)); })).source;
  let moved = null;
  if (before && before.id !== x.id) {
    const r = await ctl.py("resolve", "--source", before.id);
    moved = r.anchors.reduce((m, y) => ({ ...m, [y.status]: (m[y.status] || 0) + 1 }), {});
  }
  join(task, { id: x.id, title: x.title, kind: "web", url }, before && before.id);
  return { title: x.title, same: !!before && before.id === x.id, moved };
});
// D2 논문 검색: the words the user typed go to the arXiv API (no key); the user picks a result and it is imported as
// above. arXiv asks for at most one request every 3 seconds: searches wait their turn here.
let searched = 0;
// ⑬ OpenReview: the PDF from openreview.net only (its title from the PDF itself, the forum id kept)
ipcMain.handle("pablo:add-openreview", async (e, task, text) => {
  fromWindow(e); known(task); if (!str(text, 300)) throw new Error("bad link");
  const o = papers.openreview(text);
  if (!o) throw new Error("OpenReview 링크를 읽지 못했습니다. 예: https://openreview.net/forum?id=AbCd1234");
  const data = await papers.fetchPdf(`${openreview.base}pdf?id=${encodeURIComponent(o.id)}`, { origin: new URL(openreview.base).origin,
    max: openreview.max, ms: openreview.ms, site: "OpenReview", missing: "OpenReview에 그 논문의 PDF가 없습니다(비공개이거나 지운 글일 수 있습니다)." })
    .catch(err => { throw new Error(err.name === "TimeoutError" ? "OpenReview가 60초 안에 답하지 않았습니다."
      : /[가-힣]/.test(err.message) ? err.message : "OpenReview에 연결하지 못했습니다. 인터넷 연결을 확인하세요."); });
  const file = path.join(ctl.dir, "papers", `openreview-${o.id}.pdf`);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, data);
  const x = (await ctl.py("source", file, "--openreview", o.id)).source;
  const before = papers.list(desk(), task).find(p => p.id === x.id);
  join(task, { id: x.id, title: x.title, openreview: o.id, sha256: x.version.content_hash });
  return { title: x.title, version: null, same: !!before };
});
// ⑬ a DOI: arXiv's own DOI is an arXiv id (add-arxiv). Another publisher's PDF is rarely free to fetch, so its title
// (Crossref) is looked up on arXiv: the user picks the arXiv version, or adds the PDF they have as a file.
ipcMain.handle("pablo:lookup-doi", async (e, text) => {
  fromWindow(e); if (!str(text, 300)) throw new Error("bad DOI");
  const d = papers.doi(text);
  if (!d) throw new Error("DOI를 읽지 못했습니다. 예: 10.1145/3580305.3599256");
  const r = await fetch(`${crossref.api}works/${encodeURIComponent(d.doi)}`, { signal: AbortSignal.timeout(30000), redirect: "error",
    headers: { accept: "application/json" } }).catch(() => { throw new Error("DOI 정보(Crossref)에 연결하지 못했습니다. 인터넷 연결을 확인하세요."); });
  if (r.status === 404) throw new Error("그 DOI를 Crossref에서 찾지 못했습니다.");
  if (!r.ok) throw new Error(`DOI 정보를 가져오지 못했습니다(HTTP ${r.status}).`);
  const m = ((await r.json().catch(() => ({}))).message) || {}, title = String((m.title || [])[0] || "").replace(/\s+/g, " ").trim();
  if (!title) throw new Error("그 DOI의 제목을 읽지 못했습니다.");
  const q = papers.searchQuery(title.split(" ").slice(0, 12).join(" "));
  const wait = searched + 3000 - Date.now();
  searched = Date.now() + Math.max(0, wait);
  if (wait > 0) await new Promise(res => setTimeout(res, wait));
  const s = await fetch(`${arxiv.api}?search_query=${encodeURIComponent(q)}&start=0&max_results=5&sortBy=relevance`,
    { signal: AbortSignal.timeout(30000), redirect: "error" }).catch(() => null);
  const hits = s && s.ok ? papers.atom((await s.text()).slice(0, 4 << 20)) : [];
  return { doi: d.doi, title, year: (((m.issued || {})["date-parts"] || [[]])[0] || [])[0] || null, hits };
});
ipcMain.handle("pablo:search-arxiv", async (e, text) => {
  fromWindow(e); if (!str(text, 300)) throw new Error("bad query");
  const q = papers.searchQuery(text);
  if (!q) throw new Error("검색어를 읽지 못했습니다.");
  const wait = searched + 3000 - Date.now();
  searched = Date.now() + Math.max(0, wait);
  if (wait > 0) await new Promise(r => setTimeout(r, wait));
  const r = await fetch(`${arxiv.api}?search_query=${encodeURIComponent(q)}&start=0&max_results=8&sortBy=relevance`,
    { signal: AbortSignal.timeout(30000), redirect: "error" }).catch(err => {
    throw new Error(err.name === "TimeoutError" ? "arXiv 검색이 30초 안에 답하지 않았습니다." : "arXiv 검색에 연결하지 못했습니다. 인터넷 연결을 확인하세요."); });
  if (!r.ok) throw new Error(`arXiv 검색에 실패했습니다(HTTP ${r.status}).`);
  return papers.atom((await r.text()).slice(0, 4 << 20));
});
ipcMain.handle("pablo:remove-source", (e, task, id) => {
  fromWindow(e); known(task); if (!str(id, 20)) throw new Error("bad source");
  saveDesk(d => { d.pdf[task] = papers.list(d, task).filter(p => p.id !== id); if ((d.primary || {})[task] === id) delete d.primary[task]; });
  return true;
});
// ⑤ a notice the user has read (the PowerShell 7 one): not shown again
ipcMain.handle("pablo:notice-seen", (e, what) => {
  fromWindow(e); if (what !== "shell") throw new Error("bad notice");
  saveDesk(d => { d.noticed = { ...(d.noticed || {}), [what]: true }; });
});
// ⑭ a task's own name (the list, the header; its text stays the goal) and 보관 (folded at the list's bottom, kept whole)
ipcMain.handle("pablo:rename-task", async (e, task, name) => {
  fromWindow(e); known(task); if (!str(name, 80)) throw new Error("작업 이름은 80자까지입니다.");
  return (await ctl.py("rename-task", task, "--name", name).catch(err => { throw new Error(short(err.message)); })).task.name;
});
ipcMain.handle("pablo:archive-task", (e, task, on) => {
  fromWindow(e); known(task);
  saveDesk(d => { d.archived = { ...(d.archived || {}) }; if (on === true) d.archived[task] = true; else delete d.archived[task]; });
  return on === true;
});
// ⑧ the name the user knows a paper by: Pablo's records (cards, brief, panels) and the task lists that hold it
ipcMain.handle("pablo:rename-source", async (e, task, id, title) => {
  fromWindow(e); known(task);
  if (!str(id, 20) || !/^SRC\d+$/.test(id) || !papers.list(desk(), task).some(p => p.id === id) || !str(title, 120) || !title.trim()) throw new Error("bad name");
  const r = await ctl.py("rename-source", id, "--title", title.trim()).catch(err => { throw new Error(short(err.message)); });
  saveDesk(d => { for (const t of Object.keys(d.pdf || {})) for (const p of papers.list(d, t)) if (p.id === id) p.title = r.source.title; });
  return r.source.title;
});
// C1: the 주 논문, the paper this task reproduces: 재현 조건 뽑기 reads it (and replaces any other paper's conditions)
ipcMain.handle("pablo:set-primary", (e, task, id) => {
  fromWindow(e); known(task);
  if (!papers.list(desk(), task).some(p => p.id === id && p.kind !== "web")) throw new Error("이 작업의 논문이 아닙니다.");
  saveDesk(d => { d.primary = { ...(d.primary || {}), [task]: id }; });
  return id;
});
// M3.3 a question about the captured PDF -> Pablo ask (judge picks quotes, Pablo anchors them) -> answer + citations.
// C1: every paper of the task, or the ones the user picked when they are too long for one question (only)
ipcMain.handle("pablo:ask", (e, text, task, only) => {
  fromWindow(e); if (!str(text, 2000) || !text.trim()) throw new Error("bad question");
  known(task);
  if (auth.state !== "connected") throw new Error("ChatGPT에 먼저 연결하세요.");
  const ids = papers.list(desk(), task).map(p => p.id).filter(id => !Array.isArray(only) || only.includes(id));
  if (!ids.length) throw new Error("먼저 논문 PDF를 추가하세요.");
  saveDesk(x => { x.last = task; });
  const at = new Date().toISOString();
  return ctl.ask(task, text, ids).then(r => {
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
  if (!str(id, 20) || !/^K\d+$/.test(id) || !["promote", "reject", "hard", "soft"].includes(action)) throw new Error("bad candidate");
  // ③ hard / soft: a line the reader could not classify becomes this task's rule (반드시 / 가능하면)
  const r = await ctl.py(...(action === "hard" || action === "soft" ? ["promote", id, "--as", action] : [action, id]));
  return action === "reject" ? null : r.item.statement;
});
// ④ the user changes a criterion: 반드시 <-> 가능하면, removes it (with why) or restores a removed one. The Guard and the
// brief read the change at once; the history keeps the old one and says the user did it.
// C3 edit: the 4th argument is the new sentence (<= 500); the same criterion (strength, scope) with the user's words
ipcMain.handle("pablo:criterion", async (e, task, id, action, reason) => {
  fromWindow(e); known(task);
  if (!str(id, 20) || !/^[A-Z]\d+$/.test(id) || !["hard", "soft", "drop", "restore", "edit"].includes(action)
    || (reason != null && !str(reason, action === "edit" ? 500 : 300)) || (action === "edit" && !(reason || "").trim()))
    throw new Error("bad criterion");
  const r = await ctl.py(...(action === "drop" ? ["drop", id, "--reason", (reason || "").trim()] : action === "restore" ? ["restore", id]
    : action === "edit" ? ["restate", id, reason.trim()] : ["strength", id, action]))
    .catch(err => { throw new Error(/no (active|removed) /.test(err.message) ? "이미 바뀌었거나 지운 기준입니다." : short(err.message)); });
  // ⑩ review: whoever reads only the conversation (a supervisor, oneself later) sees what changed and why
  logChat(task, { role: "criterion-edit", at: new Date().toISOString(), action, id, text: r.item.statement,
    ...(action === "drop" && reason && reason.trim() ? { reason: reason.trim() } : {}),
    ...(action === "edit" && r.before && r.before !== r.item.statement ? { prev: r.before } : {}) });
  return r.item.statement;
});
// UI renewal: words from a message made a criterion of the task by the user (📌 기준으로): always a rule of the strength
// they chose, never the goal; one the policy would hold back (hedged words) is promoted at once, the user already decided
ipcMain.handle("pablo:make-criterion", async (e, task, text, strength) => {
  fromWindow(e); known(task);
  if (!str(text, 1000) || !text.trim() || !["hard", "soft"].includes(strength)) throw new Error("bad criterion");
  const r = await ctl.py("say", text.trim(), "--scope", "task", "--task", task, "--rule", strength).catch(err => { throw new Error(short(err.message)); });
  const items = [...r.added];
  for (const k of r.candidates.filter(k => k.status === "pending" || k.status === "ignored")) {
    const x = (await ctl.py("promote", k.id, "--as", strength)).item;
    items.push({ id: x.id, kind: x.kind, strength: x.strength, text: x.statement });
  }
  if (items.length) logChat(task, { role: "intent", at: new Date().toISOString(), items });
  return items;
});
// ⑩ the user's own hand on the reproduction conditions: add one from a sentence picked in the 주 논문 (Pablo anchors it on
// that page, or refuses), take one out with why, or put it back. The Guard, the brief and 재현 점검 follow at once.
ipcMain.handle("pablo:condition", async (e, task, action, o) => {
  fromWindow(e); known(task); o = o || {};
  if (action === "add") {
    const main = papers.primary(desk(), task);
    if (!str(o.src, 20) || !/^SRC\d+$/.test(o.src) || !Number.isInteger(o.page) || o.page < 1 || o.page > 5000 || !str(o.quote, 600) || !o.quote.trim()
      || !str(o.category, 20) || !/^[a-z]+$/.test(o.category) || !str(o.statement, 300) || !o.statement.trim() || (o.value != null && !str(o.value, 100)))
      throw new Error("bad condition");
    if (!main || main.id !== o.src) throw new Error(main ? `재현 조건은 주 논문(${main.title})에서만 더합니다.` : "먼저 논문 PDF를 추가하세요.");
    const at = new Date().toISOString();
    const r = await ctl.py("add-spec", task, "--source", o.src, "--page", String(o.page), "--quote", o.quote, "--category", o.category,
      "--statement", o.statement.trim(), "--value", (o.value || "").trim()).catch(err => { throw new Error(short(err.message)); });
    logChat(task, { role: "spec-add", at, check: r.check.id });
    return r;
  }
  // ⑦ deviate (why required) / undeviate: the user differs from the condition on purpose, or goes back to the paper
  const why = ["drop", "deviate"].includes(action), scope = o.scope == null ? "runs" : o.scope;  // ⑦ runs: separate runs only (default)
  if (!["drop", "restore", "deviate", "undeviate"].includes(action) || !str(o.id, 20) || !/^SC\d+$/.test(o.id) || (why && (!str(o.reason, 300) || !o.reason.trim()))
    || !["runs", "task"].includes(scope)) throw new Error("bad condition");
  const cmd = { drop: "drop-spec", restore: "restore-spec", deviate: "deviate", undeviate: "undeviate" }[action];
  const r = await ctl.py(cmd, o.id, ...(why ? ["--reason", o.reason.trim()] : []), ...(action === "deviate" ? ["--scope", scope] : []))
    .catch(err => { throw new Error(/^no (live condition|condition|intended deviation)/.test(err.message) ? "이미 빠졌거나 바뀐 조건입니다." : short(err.message)); });
  logChat(task, { role: "spec-" + action, at: new Date().toISOString(), check: o.id, ...(why ? { reason: o.reason.trim() } : {}),
    ...(action === "deviate" ? { scope } : {}) });
  return r.check.id;
});
// A2 the paper's reproduction conditions -> anchored checks; the conversation gets a card (chat.json "spec")
ipcMain.handle("pablo:spec", async (e, task) => {
  fromWindow(e); known(task);
  if (auth.state !== "connected") throw new Error("ChatGPT에 먼저 연결하세요.");
  const src = (papers.primary(desk(), task) || {}).id;  // C1: the 주 논문
  if (!src) throw new Error("먼저 논문 PDF를 추가하세요.");
  const at = new Date().toISOString(), t0 = Date.now();
  // D9: how far the model has read (pablo:agent {type: "progress", what: "spec", page, pages}); pablo:cancel("spec") stops it
  const r = await ctl.pyx({ what: "spec", progress: p => broadcast("pablo:agent", { type: "progress", task, what: "spec", page: p.page, pages: p.pages }) },
    "spec", task, "--source", src).catch(err => { console.error("[pablo] spec", err.message); throw new Error(err.cancelled ? err.message : short(err.message)); });
  r.secs = Math.round((Date.now() - t0) / 1000);  // D8: how long it took ("· 42초")
  logChat(task, { role: "spec", at, checks: r.stated.map(c => c.id), missing: r.missing.map(c => c.id), dropped: r.dropped.length,
    ...(r.diff && !r.diff.first ? { diff: r.diff } : {}), secs: r.secs });  // 0.8 review: a re-extraction says what changed and what it kept
  return r;
});
// C3 비교표: the task's papers (rows) by columns; one judge call per paper, every cell anchored or left empty
ipcMain.handle("pablo:compare", async (e, task, columns) => {
  fromWindow(e); known(task);
  if (auth.state !== "connected") throw new Error("ChatGPT에 먼저 연결하세요.");
  if (!Array.isArray(columns) || !columns.length || columns.length > 8 || !columns.every(c => str(c, 40) && c.trim())) throw new Error("bad columns");
  const ps = papers.list(desk(), task).filter(p => p.kind !== "web");  // a table of papers; web pages are not rows
  if (ps.length < 2) throw new Error("비교하려면 논문이 두 편 이상 있어야 합니다.");
  const at = new Date().toISOString();
  const r = await ctl.pyx({ what: "compare" }, "compare", task, ...ps.flatMap(p => ["--source", p.id]), "--columns", JSON.stringify(columns))
    .catch(err => { console.error("[pablo] compare", err.message); throw new Error(err.cancelled ? err.message : short(err.message)); });
  const entry = { role: "compare", at, matrix: r.matrix, columns, papers: ps.map(p => ({ id: p.id, title: p.title, version: p.version || null })),
    cells: r.cells.map(c => c.id), empty: r.empty.map(x => ({ source: x.source_id, column: x.column, ...(x.value ? { value: x.value } : {}) })) };
  logChat(task, entry);
  return { ...r, entry };
});
// ⑧ review: one column added to a table that is there (a dataset both papers use): only that column is asked of each of the
// table's papers, and the table's entry in the conversation grows by it (not the whole table again: 1-2 minutes, usage)
ipcMain.handle("pablo:compare-column", async (e, task, mid, column) => {
  fromWindow(e); known(task);
  if (auth.state !== "connected") throw new Error("ChatGPT에 먼저 연결하세요.");
  if (!str(mid, 20) || !/^M\d+$/.test(mid) || !str(column, 40) || !column.trim()) throw new Error("bad column");
  const f = path.join(ctl.dir, "chat.json"), log = JSON.parse(fs.readFileSync(f, "utf8"));
  const entry = (log[task] || []).find(x => x.role === "compare" && x.matrix === mid);
  if (!entry) throw new Error("그 비교표를 찾지 못했습니다.");
  if (entry.columns.length >= 8) throw new Error("비교표의 열은 8개까지입니다.");
  const col = column.trim(), r = await ctl.pyx({ what: "compare" }, "compare", task, ...entry.papers.flatMap(p => ["--source", p.id]), "--columns", JSON.stringify([col]), "--into", mid)
    .catch(err => { console.error("[pablo] compare-column", err.message); throw new Error(err.cancelled ? err.message : short(err.message)); });
  const now = JSON.parse(fs.readFileSync(f, "utf8")), x = now[task].find(y => y.role === "compare" && y.matrix === mid);  // read again: a turn may have logged meanwhile
  x.columns = [...x.columns, col]; x.cells = [...x.cells, ...r.cells.map(c => c.id)];
  x.empty = [...(x.empty || []), ...r.empty.map(y => ({ source: y.source_id, column: y.column, ...(y.value ? { value: y.value } : {}) }))];
  fs.writeFileSync(f, JSON.stringify(now, null, 1));
  return { ...r, entry: x };
});
// ⑫ the work folder's version: HEAD and uncommitted changes when it is a git repo (fsmonitor off: reading runs nothing)
function gitState(work) {
  if (!work || !fs.existsSync(path.join(work, ".git"))) return null;
  const git = (...a) => execFileSync("git", ["-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", "-C", work, ...a],
    { encoding: "utf8", timeout: 5000, windowsHide: true }).trim();
  try { return { head: git("rev-parse", "HEAD"), dirty: git("status", "--porcelain", "--untracked-files=no").split("\n").filter(Boolean).length }; }
  catch { return null; }
}
// ⑫ the reproduction report: Markdown (A13: or one HTML page), saved where the user picks (nothing leaves the computer)
const REPORT_SECTIONS = ["goal_criteria", "conditions", "audit", "deviations", "decisions", "changes", "refused", "conversation"];
const reportTo = new Map();  // A13 token -> {file, format}: the place the user chose in the save dialog before exporting
const taskTitle = task => { try { const t = JSON.parse(fs.readFileSync(path.join(ctl.dir, "skill.json"), "utf8")).tasks.find(x => x.id === task);
  return (t && t.text) || task; } catch { return task; } };
const reportName = (title, format) => String(title).replace(/[\\/:*?"<>|\r\n]+/g, " ").trim().slice(0, 60) + " 재현 보고서." + (format === "html" ? "html" : "md");
const reportFilter = format => format === "html" ? { name: "HTML", extensions: ["html"] } : { name: "Markdown", extensions: ["md"] };
const shownPath = f => path.basename(path.dirname(f)) + "/" + path.basename(f);  // the folder and the name, not the whole path
// A13 the save dialog first (the export dialog's 저장 위치 · 바꾸기): -> {token, display}; default <work folder>/reports
ipcMain.handle("pablo:pick-report-path", async (e, task, format) => {
  fromWindow(e); known(task); if (!["md", "html"].includes(format)) throw new Error("bad format");
  const work = workOf(task), name = reportName(taskTitle(task), format), dir = work && path.join(work, "reports");
  const res = await dialog.showSaveDialog(BrowserWindow.fromWebContents(e.sender), { title: "재현 보고서 저장",
    defaultPath: dir ? path.join(fs.existsSync(dir) ? dir : work, name) : name, filters: [reportFilter(format)] });
  if (res.canceled || !res.filePath) return null;
  const token = crypto.randomUUID();
  reportTo.set(token, { file: res.filePath, format });
  return { token, display: shownPath(res.filePath) };
});
// A13 what the export dialog shows before exporting: each part's count, whether the last audit is older than the last
// change, and the record that goes with the report (audit time · git HEAD · Pablo version)
ipcMain.handle("pablo:report-preview", async (e, task) => {
  fromWindow(e); known(task);
  const r = await ctl.py("report", task, "--preview", "--now", JSON.stringify({ decisions: pinned(task) }));
  const work = workOf(task), g = gitState(work), at = r.counts.audit.at;
  const local = iso => { const d = new Date(iso), p = n => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; };
  return { counts: r.counts, stale: r.stale, auto: [at ? `점검 시각 ${local(at)}` : "점검 전", g ? `git HEAD ${g.head.slice(0, 7)}` : null, `Pablo ${VERSION}`].filter(Boolean).join(" · "),
    where: work ? path.basename(work) + "/reports" : null };
});
// the messages a person pinned as a decision (✎ 태그): the report lists them, as the tag editor says
const pinned = task => Object.entries((desk().tags || {})[task] || {}).filter(([, o]) => o && o.decision).map(([key, o]) => ({ key, stage: o.stage || null }));
// opts (A13, all optional): {sections: [REPORT_SECTIONS], format: "md" | "html", token: from pablo:pick-report-path, or
// "default" = <work folder>/reports/<name>}; no token -> the save dialog, as before
ipcMain.handle("pablo:report", async (e, task, opts) => {
  fromWindow(e); known(task); opts = opts || {};
  const format = opts.format == null ? "md" : opts.format, sections = opts.sections == null ? null : opts.sections;
  if (!["md", "html"].includes(format) || (sections && (!Array.isArray(sections) || !sections.length || !sections.every(x => REPORT_SECTIONS.includes(x))))
    || (opts.token != null && !(str(opts.token, 64) && (opts.token === "default" || reportTo.has(opts.token))))) throw new Error("bad report");
  // the folder now, and the last audit's confirmed places checked again (the card's rule), so the report says what the app says
  const work = workOf(task), log = (() => { try { return JSON.parse(fs.readFileSync(path.join(ctl.dir, "chat.json"), "utf8"))[task] || []; } catch { return []; } })();
  const last = log.filter(x => x.role === "audit" && (x.items || []).length).at(-1);
  // places, not rows (the card counts the same way): two rows on one line are one place
  const at = x => { const w = where.where(x.where); return x.line_found && w ? `${w.path}:${x.line_found}` : x.where; }, seen = new Set();
  const placed = last ? [...last.items, ...(last.outside || [])].filter(x => ["verified", "moved", "value_mismatch"].includes(x.check) && x.where && x.found)
    .filter(x => !seen.has(at(x)) && seen.add(at(x))) : [];
  const gone = work ? placed.filter(x => { if (!where.where(x.where)) return false;
    const c = where.verify(work, { where: at(x), found: x.found }).check;
    return c === "not_found" || c === "no_file"; }).map(at) : [];
  const now = { tree: work ? await checkpoint.snapshot(ctl.dir, task, work).catch(() => null) : null, git: gitState(work),
    recheck: last && work ? { at: last.at, placed: placed.length, gone } : null, decisions: pinned(task) };
  const r = await ctl.py("report", task, "--now", JSON.stringify(now), ...(sections ? ["--sections", sections.join(",")] : []), "--format", format);
  const name = reportName(r.title || task, format);
  let file = null;
  if (opts.token === "default") {
    if (!work) throw new Error("작업 폴더가 없어 기본 위치에 저장할 수 없습니다. 저장 위치를 골라 주세요.");
    file = path.join(work, "reports", name);
    fs.mkdirSync(path.dirname(file), { recursive: true });
  } else if (opts.token) file = reportTo.get(opts.token).file;
  else {
    const res = await dialog.showSaveDialog(BrowserWindow.fromWebContents(e.sender), { title: "재현 보고서 저장", defaultPath: name,
      filters: [reportFilter(format)] });
    if (res.canceled || !res.filePath) return null;
    file = res.filePath;
  }
  const res = { filePath: file };
  try { fs.writeFileSync(res.filePath, r.text, "utf8"); if (opts.token && opts.token !== "default") reportTo.delete(opts.token); }
  catch (err) {  // review: OneDrive folders answer EBUSY; say it in the user's words
    const why = { ENOENT: "폴더가 없습니다", EACCES: "쓰기 권한이 없습니다", EPERM: "쓰기 권한이 없습니다", EBUSY: "다른 프로그램(동기화 등)이 쓰고 있습니다", EROFS: "읽기 전용입니다" }[err.code];
    throw new Error(`그 폴더에 저장하지 못했습니다(${why || err.code || "알 수 없는 이유"}). 다른 폴더를 골라 주세요.`);
  }
  logChat(task, { role: "report", at: new Date().toISOString(), name: path.basename(res.filePath),  // the stage bar's 보고서 step
    ...(format !== "md" ? { format } : {}), ...(sections ? { sections } : {}) });
  return { name: path.basename(res.filePath), lines: r.text.split("\n").length, format, display: shownPath(res.filePath) };
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
  // ⑫ review: which code the verdicts are about — the folder's snapshot (shadow git tree) and, when it is a git repo, its HEAD
  const tree = await checkpoint.snapshot(ctl.dir, task, work).catch(() => null), git = gitState(work);
  reply = { task, at: new Date().toISOString(), text: "", audit: a.items.map(x => x.id), work, tree, git, shell: agent.shell(),
    values: Object.fromEntries(a.items.filter(x => x.value).map(x => [x.id, x.value])),  // A2: the paper's value per condition
    read: new Set(), judged: 0 };  // D9: the files the agent read, the verdicts its answer has so far
  saveDesk(x => { x.last = task; });
  return agent.send(forShell(a.prompt), ctl.dir + "#" + task, null, null, { readOnly: true, outputSchema: a.schema });
});
// D9 a long Python call stopped by the user (재현 조건 뽑기, 비교표): its child is killed, the call rejects "중지했습니다."
ipcMain.handle("pablo:cancel", (e, what) => { fromWindow(e); if (!["spec", "compare"].includes(what)) throw new Error("bad cancel"); return ctl.cancel(what); });
// D9 재현 점검's progress (an agent turn; pablo:stop stops it): files read (the commands' read actions) and verdicts the
// answer has written so far, of total -> pablo:agent {type: "progress", what: "audit", task, files, judged, total}
const auditProgress = r => broadcast("pablo:agent", { type: "progress", task: r.task, what: "audit", files: r.read.size, judged: r.judged, total: r.audit.length });
agent.on("item", it => {
  const r = reply; if (!r || !r.audit || it.type !== "commandExecution") return;
  const n = r.read.size;
  for (const x of it.commandActions || []) if (x && x.type === "read" && x.path) r.read.add(String(x.path));
  if (r.read.size !== n) auditProgress(r);
});
agent.on("event", ev => {
  const r = reply; if (!r || !r.audit || ev.type !== "delta") return;
  const n = Math.min(r.audit.length, ((r.text + (ev.text || "")).match(/"status"\s*:/g) || []).length);
  if (n !== r.judged) { r.judged = n; auditProgress(r); }
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
    const files = await checkpoint.changes(ctl.dir, c.task, c.work, c.tree, to, { lines: true });  // D7: + add / del per file
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
// ⑤ expect: what an audit saw there (its found). Is it still at that line now? (the same rule as the audit's check)
ipcMain.handle("pablo:read-file", (e, task, raw, around, expect) => {
  fromWindow(e); known(task); if (expect != null && !str(expect, where.FOUND + 10)) throw new Error("bad expect");
  const { w, work } = located(task, raw), at = Number.isInteger(around) && around > 0 ? around : w.from;
  const still = expect ? where.verify(work, { where: at ? `${w.path}:${at}` : w.path, found: expect }).check : undefined;
  return { ...where.read(work, w.path, at), ranges: w.ranges, ...(still ? { still } : {}) };
});
// ⑤ review: an audit card's confirmed places, each looked at again now (the same rule as the audit's check): verified |
// moved | not_found | no_file | unchecked. Read-only; nothing outside the task's folder is read.
ipcMain.handle("pablo:recheck", (e, task, places) => {
  fromWindow(e); known(task);
  if (!Array.isArray(places) || places.length > 100 || !places.every(p => p && str(p.where, 1000) && str(p.found, where.FOUND + 10)
    && (p.line == null || (Number.isInteger(p.line) && p.line > 0)))) throw new Error("bad places");
  const work = workOf(task);
  return places.map(p => { const w = where.where(p.where);
    return !w || !work ? "unchecked" : where.verify(work, { where: p.line ? `${w.path}:${p.line}` : p.where, found: p.found }).check; });
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
      const entry = { role: "audit", at: r.at, status: ev.status, ...(r.tree ? { tree: r.tree } : {}), ...(r.git ? { git: r.git } : {}), ...(r.shell ? { shell: r.shell } : {}), ...audited(r) };
      if (ev.error) entry.error = short(ev.error);
      logChat(r.task, entry);
      broadcast("pablo:agent", { type: "audit", task: r.task, ...entry });
    } else {
      logChat(r.task, { role: "agent", text: r.text, at: r.at, status: ev.status, ...(ev.error ? { error: short(ev.error) } : {}),
        ...(r.step ? { step: r.step } : {}) });  // D4: the plan step it answered
      // the page tags the turn's live messages right away with these keys (role@time) instead of after the next state
      // read, which waits behind the turn's reviews (QA 10/26: ~7 s without ✎ 태그 / 📌 기준으로); the broadcast below sends ev
      ev.logged = { task: r.task, user: r.user || null, agent: r.at };
    }
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
    // ⑤ a line that reads the setting (cfg["retrieval"]["top_k"]): the config line that sets it, in a field of its own
    for (const x of items) { const v = where.follow(r.work, x, (r.values || {})[x.id]); if (v) x.via = v; }
    // ⑥ an item the model called missing whose value is a name: Pablo looks for it in the folder's code and config
    for (const x of items) { const s = where.scan(r.work, x, (r.values || {})[x.id]); if (s) x.seen = s; }
    // what no item covers: kept apart from the verdicts, its place checked the same way (no paper value to hold it to)
    const outside = (Array.isArray(j.outside) ? j.outside : []).filter(x => x && String(x.what || "").trim()).slice(0, 12)
      .map(x => ({ kind: x.kind === "scope" ? "scope" : "method", what: String(x.what).slice(0, 300), where: String(x.where || ""),
                   found: String(x.found || "").slice(0, where.FOUND) }));
    for (const x of outside) Object.assign(x, where.verify(r.work, x, ""));
    const n = items.reduce((m, x) => ({ ...m, [x.check]: (m[x.check] || 0) + 1 }), {});
    console.log("[pablo] audit checked:", JSON.stringify(n), outside.length ? `+ ${outside.length} outside the items` : "");
    return { items, outside, summary: String(j.summary || "").slice(0, 1000) };
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
// D5 code: siwc.SAY's key of what went wrong (no_plan_permission, not_eligible, timeout, ...), never a token or raw text
const setAuth = (state, error, code) => { auth = { state, error: error || undefined, code: code || undefined }; broadcast("pablo:auth", auth); };
const P = "openai_chatgpt_plan";  // https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server
const PROVIDER = [["model_provider", `"${P}"`], [`model_providers.${P}.name`, '"ChatGPT plan"'], [`model_providers.${P}.base_url`, '"https://api.openai.com/v1"'],
  [`model_providers.${P}.env_key`, '"ACCESS_TOKEN"'], [`model_providers.${P}.wire_api`, '"responses"'],
  [`model_providers.${P}.requires_openai_auth`, "false"], [`model_providers.${P}.supports_websockets`, "false"]].flatMap(([k, v]) => ["-c", `${k}=${v}`]);
// app-server failures -> the same short messages as sign-in
function short(err) {
  const k = sayKey(err), m = String(err);
  if (k) return siwc.SAY[k];
  return m.length > 200 ? m.slice(0, 200) + "…" : m;
}
// which of siwc.SAY an app-server / API failure is (null: none, its own words are shown)
function sayKey(err) {
  if (/server_?overloaded|at capacity/i.test(err)) return "overloaded";
  const m = String(err), code = (m.match(/subscription_sharing_\w+|chatpass_v2_\w+/) || [""])[0];
  const status = +((m.match(/\b(401|403|429|503)\b/) || [])[1] || 0);
  if (code || status) return siwc.classify(code, status);
  if (/^responses\b/.test(m)) return "inference_failed";  // the judge's own API call (llm.py), other failures
  return null;
}
function fail(e) {
  console.error("[auth]", e.code || "", e.detail || e.message);
  setAuth(siwc.has() ? "error" : "signed_out", e instanceof siwc.AuthError ? e.message : short(e.message),
    e instanceof siwc.AuthError ? e.code : sayKey(e.message));
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
  // ⑤ PYTHONUTF8: Python the agent runs prints UTF-8 (Windows: cp949 by default; Codex reads UTF-8, so λ became U+FFFD)
  env: { ACCESS_TOKEN: await siwc.token(), CODEX_HOME: path.join(app.getPath("userData"), "codex"), PYTHONUTF8: "1" } });  // own CODEX_HOME: no codex login, no user config.toml

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

// ⑤ a PC without PowerShell 7 (Codex then runs the agent's commands in Windows PowerShell 5.1): the agent is told to read
// files as UTF-8. Pablo's own CODEX_HOME, so its global AGENTS.md reaches the threads Pablo starts and nothing of the
// user's changes; with pwsh 7 there is no such file. A 재현 점검 turn says it again (a thread may predate the file).
const RULE_51 = `# Pablo: 이 PC의 PowerShell

이 PC에는 PowerShell 7이 없어, 명령이 Windows PowerShell 5.1에서 실행됩니다. 5.1의 Get-Content와 Import-Csv는 BOM 없는 UTF-8 파일을 ANSI 코드 페이지로 읽어서, 한글 주석과 λ 같은 기호가 깨집니다.

- 파일을 읽는 PowerShell 명령은 맨 앞에 \`$PSDefaultParameterValues['Get-Content:Encoding']='UTF8';\`를 두거나, Get-Content와 Import-Csv에 \`-Encoding UTF8\`을 붙이세요.
- rg와 Select-String은 그대로 써도 됩니다.
- 깨진 글자(�, 엉뚱한 한자)가 보이면 그 파일을 UTF-8로 다시 읽은 뒤에 판단하세요.
`;
const READ_51 = "이 PC는 Windows PowerShell 5.1입니다. 파일은 Get-Content -Encoding UTF8로 읽거나 명령 앞에 "
  + "$PSDefaultParameterValues['Get-Content:Encoding']='UTF8'; 를 두세요(그냥 읽으면 한글과 기호가 깨집니다). rg는 그대로 써도 됩니다.";
function agentRules(home) {
  const f = path.join(home, "AGENTS.md");
  if (agent.shell() === "powershell") fs.writeFileSync(f, RULE_51); else fs.rmSync(f, { force: true });
}
const forShell = prompt => agent.shell() === "powershell" ? prompt + "\n" + READ_51 : prompt;

function boot() {
  const data = app.getPath("userData");
  siwc.init(data, safeStorage);
  fs.mkdirSync(path.join(data, "codex"), { recursive: true });
  // Pablo's own CODEX_HOME config. Windows: without a sandbox mode every shell command is "blocked by policy" (agent can't read files).
  // unelevated = restricted-token sandbox, no admin setup; read-only still blocks writes. (-c windows.sandbox did not take effect.)
  if (process.platform === "win32") fs.writeFileSync(path.join(data, "codex", "config.toml"), '[windows]\nsandbox = "unelevated"\n');
  agentRules(path.join(data, "codex"));
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

module.exports = { open, boot, launch, auth: () => auth, arxiv, openreview, crossref, agentRules, forShell };
