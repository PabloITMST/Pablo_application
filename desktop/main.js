// Pablo desktop host: shows the viewer HTML; only the right Source panel embeds a live page (<webview>).
// Usage: npm start (the app's own state in userData/state) | npm start -- <path/to/view-T1.html>[#E1] (export/debug snapshot)
const { app, BrowserWindow, dialog, ipcMain, protocol, safeStorage, session, shell, webContents } = require("electron");
const fs = require("fs");
const path = require("path");
const { run } = require("./locate");
const agent = require("./agent");
const ctl = require("./controller");
const siwc = require("./siwc");

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
  const d = desk(), own = d.workspace[task];
  agent.workspace = ctl.root = own || envWorkspace;  // the task's folder (M5.1), else PABLO_WORKSPACE, else read-only
  // M5.1: a task made in the app has no CLI plan; the request itself is its one step (wiring only, Guard unchanged)
  if (own) await ctl.py("plan", task, "--steps", JSON.stringify([{ action: text.slice(0, 500), basis: [] }]))
    .catch(err => console.error("[pablo] plan", err.message));  // no plan -> Guard warns on every action (fail safe)
  saveDesk(x => { x.last = task; });
  return agent.send(text, ctl.dir + "#" + task);  // each task talks on its own thread
});
// ---- M5.1 app-first workflow: live state, new task, folder and material per task (userData/state/desktop.json) ----
let envWorkspace = null;
const desk = () => { try { return { workspace: {}, pdf: {}, ...JSON.parse(fs.readFileSync(path.join(ctl.dir, "desktop.json"), "utf8")) }; }
  catch { return { workspace: {}, pdf: {} }; } };
const saveDesk = f => { const d = desk(); f(d); fs.writeFileSync(path.join(ctl.dir, "desktop.json"), JSON.stringify(d, null, 1)); };
const pick = (e, opts) => dialog.showOpenDialog(BrowserWindow.fromWebContents(e.sender), opts).then(r => r.canceled ? null : r.filePaths[0]);
ipcMain.handle("pablo:state", async e => {
  fromWindow(e);
  const m = await ctl.py("state"), d = desk();
  m.desk = Object.fromEntries(m.tasks.map(t => { const w = d.workspace[t.id] || envWorkspace, p = d.pdf[t.id];
    return [t.id, { folder: w ? path.basename(w) : null, pdf: p ? p.title : null }]; }));  // names only, no paths
  m.last = d.last;
  return m;
});
ipcMain.handle("pablo:new-task", async (e, text) => {
  fromWindow(e); if (!str(text, 4000) || !text.trim()) throw new Error("bad task");
  const lines = text.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
  const t = await ctl.py("task", lines[0], "--checks", "[]");  // first line = the goal; no research loop in the app
  // the other lines are this task's criteria: task scope, so they never reach other tasks
  for (const l of lines.slice(1)) await ctl.py("say", l, "--scope", "task");
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
  return ctl.ask(task, text, (desk().pdf[task] || {}).id).catch(err => { console.error("[pablo] ask", err.message); throw new Error(short(err.message)); });  // no raw API text in the UI
});
// M4.2 the user's answers: WARN [진행]/[취소], and "다른 모델로 다시 시도" after a capacity failure
ipcMain.handle("pablo:decide", (e, id, proceed) => { fromWindow(e); if (!str(id, 20)) throw new Error("bad id"); ctl.decide(id, proceed === true); });
ipcMain.handle("pablo:retry", e => { fromWindow(e); return agent.retry(); });
ipcMain.handle("pablo:agent-status", e => { fromWindow(e); return agent.status; });
ipcMain.handle("pablo:models", e => { fromWindow(e); // the account's catalog (docs: not app-server's bundled list), shown by display_name
  const name = s => ((account && account.models.find(m => m.slug === s)) || {}).name || s;
  return { models: agent.models.map(s => ({ slug: s, name: name(s) })), model: agent.model };
});
ipcMain.handle("pablo:set-model", (e, m) => { fromWindow(e); if (!str(m, 100)) throw new Error("bad model"); agent.setModel(m); });
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
