// M4.0: one persistent `codex app-server` child (JSON-RPC, one JSON per line on stdio).
// initialize -> thread/start once -> turn/start per message on the same thread.
// M4.1: agent.launch (set by main) supplies the SIWC access token + ChatGPT-plan provider + account models;
// without it, app-server falls back to the existing `codex login`.
// M4.2: one thread per Pablo task (key = state dir + task id), saved in agent.stateFile so it survives app restarts.
// Project threads: read-only, approvalPolicy never. agent.workspace (a disposable folder) instead: workspace-write +
// untrusted, and every approval request goes to agent.onRequest (the Controller) -> "accept" | "decline".
// Events: {type:"status", status:"Connecting"|"Ready"|"Thinking"|"Error", error?} | {type:"delta", text}
//         | {type:"done", first, total, status, error?, retry?}; "item" (item, turn) for each finished turn item
const { spawn, execFile } = require("child_process");
const { EventEmitter } = require("events");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { app } = require("electron");

const agent = new EventEmitter();
// npm sets INIT_CWD to where the user ran it (the project). The installed app has no project: agent work there always
// has a workspace, so this read-only fallback only needs to be somewhere harmless.
const cwd = app.isPackaged ? os.tmpdir() : process.env.INIT_CWD || process.cwd();
let proc = null, pend = {}, id = 0, buf = "", threadId = null, key = null, turn = null, ready = null, loaded = new Set(), failed = null;
agent.status = "Connecting"; agent.spawns = 0; agent.launch = null; agent.stateFile = null; agent.model = null;
agent.workspace = null; agent.onRequest = null;
agent.network = false;  // the task's 인터넷 switch: Codex's workspace sandbox has no network unless this turn says so

const set = (status, error) => { agent.status = status; agent.emit("event", { type: "status", status, error }); };
const write = m => proc.stdin.write(JSON.stringify(m) + "\n");
const call = (method, params) => new Promise((res, rej) => { const i = ++id; pend[i] = { res, rej }; write({ id: i, method, params }); });

function onLine(line) {
  const m = JSON.parse(line);
  if (m.id != null && !m.method) {  // response
    const p = pend[m.id]; delete pend[m.id];
    return p && (m.error ? p.rej(new Error(m.error.message || JSON.stringify(m.error))) : p.res(m.result));
  }
  if (m.id != null) {  // server request: approvals -> Controller (fails closed: decline); anything else unsupported
    const P = proc, t = turn, answer = r => P === proc && write({ id: m.id, ...r });
    if (!/[Aa]pproval$/.test(m.method)) return answer({ error: { code: -32601, message: "not supported by Pablo" } });
    return Promise.resolve(agent.onRequest && t ? agent.onRequest(m, t) : "decline")
      .catch(e => { console.error("[agent] approval", e.message); return "decline"; })
      .then(decision => { if (decision === "accept") t.acted = true; answer({ result: { decision } }); });
  }
  const p = m.params || {};
  if (!turn || (p.threadId && p.threadId !== threadId)) return;
  if (m.method === "item/started" || m.method === "item/completed") {  // fileChange approvals carry no paths: keep the started item
    turn.items[p.item.id] = p.item;
    if (m.method === "item/completed") agent.emit("item", p.item, turn);
  }
  if (m.method === "item/agentMessage/delta") {
    if (turn.first == null) turn.first = Date.now() - turn.t0;
    const sep = turn.item && turn.item !== p.itemId ? "\n\n" : "";  // several agent messages in one turn -> paragraphs
    turn.item = p.itemId;
    agent.emit("event", { type: "delta", text: sep + p.delta });
  } else if (m.method === "error" && !p.willRetry) {
    const e = p.error || {};
    turn.error = [e.message, e.additionalDetails, JSON.stringify(e.codexErrorInfo || "")].filter(Boolean).join(" ");
  } else if (m.method === "turn/completed") {
    finish(p.turn.status, p.turn.error && p.turn.error.message);
  }
}

function finish(status, error) {
  const t = turn; turn = null;
  if (!t) return;
  const err = status === "completed" || status === "interrupted" ? undefined : [t.error, error].filter(Boolean).join(" ") || status;
  // model at capacity: no automatic resend (it would repeat the message, and maybe its actions). The user may retry
  // on the next model, offered only when nothing ran. ponytail: the failed message stays in the thread history.
  const next = agent.models[agent.models.indexOf(agent.model) + 1];
  failed = status === "failed" && t.first == null && !t.acted && next && /serverOverloaded|at capacity/i.test(err) ? t : null;
  agent.emit("event", { type: "done", status, first: t.first, total: Date.now() - t.t0, error: err, retry: !!failed });
  err ? set("Error", err) : set("Ready");
}
// the user's "다른 모델로 다시 시도": the failed message once more, on the account's next model
async function retry() {
  const t = failed; failed = null;
  if (!t || turn) throw new Error("다시 시도할 메시지가 없습니다.");
  setModel(agent.models[agent.models.indexOf(agent.model) + 1]);
  agent.emit("event", { type: "model", model: agent.model });
  return send(t.input.at(-1).text, t.task, t.brief);
}

// task -> thread, kept across app restarts; a thread made for another folder or sandbox is not reused
function state() { try { return JSON.parse(fs.readFileSync(agent.stateFile, "utf8")); } catch { return {}; } }
const where = () => agent.workspace ? { cwd: agent.workspace, sandbox: "workspace-write", approvalPolicy: "untrusted" }
                                    : { cwd, sandbox: "read-only", approvalPolicy: "never" };
function save() {
  if (!agent.stateFile) return;
  const threads = state().threads || {}, old = threads[key];
  if (key && threadId) threads[key] = { threadId, cwd: where().cwd, sandbox: where().sandbox,
    ...(old && old.threadId === threadId && old.brief ? { brief: old.brief } : {}) };  // the brief this thread was last given
  fs.writeFileSync(agent.stateFile, JSON.stringify({ model: agent.model, threads }));
}
// Pablo's brief (criteria + located facts) goes before the message when this thread has not been given that version yet
function told(hash) {
  if (!agent.stateFile || !key || !threadId) return;
  const st = state(), th = (st.threads || {})[key];
  if (th && th.threadId === threadId) { th.brief = hash; fs.writeFileSync(agent.stateFile, JSON.stringify(st)); }
}
const given = () => ((state().threads || {})[key] || {}).brief;
// user's pick from the account's models; used from the next turn on (turn/start model sticks to the thread)
function setModel(m) { if (!agent.models.includes(m)) throw new Error("unknown model"); agent.model = m; save(); }
function forget() { threadId = key = null; loaded.clear(); if (agent.stateFile) fs.rmSync(agent.stateFile, { force: true }); }

// switch to a task's own thread: loaded in this process -> as is; saved -> thread/resume; else thread/start
// The open thread is tied to a work folder and sandbox: a task whose folder changed while the app runs gets the thread
// of the new folder (saved -> resume, else a new one), never keeps working in the old folder.
let place = null;
async function open(task) {
  const th = { model: agent.model, ...where() }, here = th.cwd + "|" + th.sandbox, s = (state().threads || {})[task];
  if (task === key && loaded.has(threadId) && place === here) return;
  const old = s && s.cwd === th.cwd && s.sandbox === th.sandbox ? s.threadId : null;
  key = task; threadId = null; place = here;
  if (old && loaded.has(old)) { threadId = old; return; }
  const r = old ? await call("thread/resume", { threadId: old, ...th }).catch(() => call("thread/start", th)) : await call("thread/start", th);
  agent.resumed = !!old && r.thread.id === old;
  threadId = r.thread.id; loaded.add(threadId); save();
}

// M6: the pinned native codex.exe (devDependency @openai/codex-win32-x64, copied to resources by Forge), never a global
// codex on PATH. No cmd shim, so -c values keep their quotes and kill reaches the real process.
const CODEX = path.join(app.isPackaged ? process.resourcesPath : path.join(__dirname, "node_modules/@openai/codex-win32-x64/vendor"),
  "x86_64-pc-windows-msvc", "bin", "codex.exe");
function codexBin() {
  if (process.platform !== "win32") return "codex";
  if (!fs.existsSync(CODEX)) throw new Error("Codex 실행 파일이 없습니다 (desktop에서 npm install)");
  return CODEX;
}

// ⑤ hard2 (10/14): the agent's shell commands (pwsh) wrote their output in the console's code page (cp949 on a Korean
// Windows) and Codex reads it as UTF-8, so λ and Korean comments came back as U+FFFD (PYTHONUTF8 only covers Python).
// Inside Codex's sandbox a command cannot change the code page ([Console]::OutputEncoding is refused there, silently),
// but the sandboxed shells inherit app-server's console: start it in one set to UTF-8. cmd only sets the code page and
// runs codex.exe on the same stdio; stop() ends its stdin (codex exits, then cmd) and its taskkill /T takes both. A line
// cmd would read itself (% ^ & | < > !) is started as before.
function spawnUtf8(bin, args, opts) {
  const q = a => !a || /[\s"]/.test(a) ? `"${a.replace(/(\\*)"/g, '$1$1\\"').replace(/(\\+)$/, "$1$1")}"` : a;
  const line = [bin, ...args].map(q).join(" ");
  if (process.platform !== "win32" || /[%^&|<>!]/.test(line)) return spawn(bin, args, opts);
  return spawn(process.env.ComSpec || "cmd.exe", ["/d", "/s", "/v:off", "/c", `"chcp 65001 >nul & ${line}"`], { ...opts, windowsVerbatimArguments: true });
}

// ⑤ which PowerShell Codex runs the agent's commands in: pwsh 7 where it is installed (the path Codex itself looks at, or
// on PATH), else Windows PowerShell 5.1, which every Windows 10/11 has (pwsh 7 is a separate install). 5.1's Get-Content
// reads a BOM-less UTF-8 file as the ANSI code page: a UTF-8 console cannot fix that, a session default can (main.js).
const PWSH7 = path.join(process.env.ProgramFiles || "C:\\Program Files", "PowerShell", "7", "pwsh.exe");
function shell() {
  if (process.platform !== "win32") return null;
  if (["pwsh", "powershell"].includes(process.env.PABLO_SHELL)) return process.env.PABLO_SHELL;  // check.js: a PC without pwsh 7
  const onPath = (process.env.PATH || "").split(path.delimiter).some(d => d && fs.existsSync(path.join(d, "pwsh.exe")));
  return fs.existsSync(PWSH7) || onPath ? "pwsh" : "powershell";
}

function start() {
  if (ready) return ready;
  set("Connecting"); agent.spawns++;
  ready = (async () => {
    const L = agent.launch ? await agent.launch() : null;
    const p = proc = L ? spawnUtf8(codexBin(), ["app-server", "--listen", "stdio://", ...L.args], { cwd, env: { ...process.env, ...L.env }, windowsHide: true })
                       : spawn("codex app-server", { cwd, shell: true, windowsHide: true });  // M4.0 fallback: `codex login`, npm .cmd shim
    buf = "";
    p.stdout.setEncoding("utf8");
    p.stdout.on("data", d => {
      buf += d; let k;
      while ((k = buf.indexOf("\n")) >= 0) { const line = buf.slice(0, k); buf = buf.slice(k + 1); if (line.trim()) try { onLine(line); } catch (e) { console.error("[agent] bad line", e.message); } }
    });
    p.stderr.on("data", d => process.env.PABLO_AGENT_LOG && process.stderr.write("[app-server] " + d));
    p.on("exit", code => {
      p.exited = true; p.emit("gone");
      if (proc !== p) return;
      proc = null; ready = null;
      const err = new Error(`app-server가 종료되었습니다 (code ${code})`);
      Object.values(pend).forEach(x => x.rej(err)); pend = {};
      if (turn) finish("failed", err.message); else set("Error", err.message);
    });
    p.on("error", e => console.error("[agent] spawn", e.message));

    await call("initialize", { clientInfo: { name: "pablo", title: "Pablo", version: require("./package.json").version }, capabilities: null });
    write({ method: "initialized" });
    // never trust the user's config.toml model; prefer app-server's default if the account offers it
    const ms = (await call("model/list", {})).data;
    // candidates: the account's catalog (any slug works on turn/start), app-server's default first; no launch -> app-server's list
    const def = (ms.find(m => m.isDefault) || ms[0]).model, all = L && L.models && L.models.length ? L.models : ms.map(m => m.model);
    agent.models = [...all.filter(m => m === def), ...all.filter(m => m !== def)];
    agent.model = agent.model || state().model;
    if (!agent.models.includes(agent.model)) agent.model = agent.models[0];
    loaded = new Set();  // after a crash, a token refresh or an app restart: the current task's thread is resumed
    if (key) await open(key);
    set("Ready");
  })();
  ready.catch(e => { set("Error", e.message); stop(); });
  return ready;
}

// brief: {text, hash} from `pablo brief` (or null): sent before the message once per thread and version.
// note: a one-off line from Pablo for this turn (e.g. the user undid a change).
// opts.readOnly: this turn reads only (재현 점검): read-only sandbox, no approvals; opts.outputSchema: its answer's JSON shape
async function send(text, task, brief, note, opts = {}) {
  if (turn) throw new Error("busy");
  await start();
  const t = turn = { t0: Date.now(), first: null, item: null, task, items: {}, acted: false, brief,
                     input: [{ type: "text", text, text_elements: [] }] };
  set("Thinking");
  try {
    await open(task); t.threadId = threadId;
    const tell = brief && brief.text && brief.hash !== given();
    if (tell) t.input = [{ type: "text", text: brief.text, text_elements: [] }, ...t.input];
    if (note) t.input = [{ type: "text", text: note, text_elements: [] }, ...t.input];
    // a work folder: sandbox and approvals on every turn. app-server keeps a turn's overrides for the turns after it, so
    // a read-only 점검 turn must never leave "no approvals" behind for a writing turn (writes always reach the Guard).
    // 인터넷 takes effect on the next message.
    const policy = !agent.workspace ? {} : opts.readOnly ? { sandboxPolicy: { type: "readOnly" }, approvalPolicy: "never" }
      : { sandboxPolicy: { type: "workspaceWrite", networkAccess: !!agent.network }, approvalPolicy: "untrusted" };
    t.id = (await call("turn/start", { threadId, input: t.input, model: agent.model, ...policy,
      ...(opts.outputSchema ? { outputSchema: opts.outputSchema } : {}) })).turn.id;
    if (tell) told(brief.hash);
    if (t.stop && turn === t) interrupt();  // 중지 pressed before app-server named the turn
  } catch (e) { finish("failed", e.message); }
}
// the user's 중지: app-server ends the turn with status "interrupted" (turn/completed), open WARN cards are cancelled
function interrupt() {
  const t = turn;
  if (!t) return Promise.resolve(false);
  if (!t.id) { t.stop = true; return Promise.resolve(true); }
  return call("turn/interrupt", { threadId: t.threadId, turnId: t.id }).then(() => true, e => { console.error("[agent] interrupt", e.message); return false; });
}

// stdin EOF ends app-server cleanly; taskkill /T after 1.5 s. Resolves once the process is gone.
function stop() {
  const p = proc; ready = null;
  if (!p) return Promise.resolve();
  proc = null;
  Object.values(pend).forEach(x => x.rej(new Error("stopped"))); pend = {};
  if (turn) finish("interrupted");
  const gone = p.exited || p.exitCode != null ? Promise.resolve() : new Promise(r => p.once("gone", r));
  p.stdin.end();
  const t = setTimeout(() => { if (!p.exited) process.platform === "win32" ? execFile("taskkill", ["/pid", String(p.pid), "/T", "/F"], { windowsHide: true }, () => {}) : p.kill(); }, 1500);
  return gone.finally(() => clearTimeout(t));
}
// new access token: same thread, fresh process
const restart = () => stop().then(start);

agent.models = [];
Object.assign(agent, { start, send, retry, interrupt, stop, restart, forget, setModel, spawnUtf8, shell, codexBin, busy: () => !!turn, thread: () => threadId, task: () => key, pid: () => proc && proc.pid });
module.exports = agent;
