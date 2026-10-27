// Per-turn checkpoints of a task's work folder, so the user can see what a turn changed and undo it.
// A shadow git repository under the Pablo state dir (state/checkpoints/<task>.git) with the work folder as its work tree:
// the user's own .git, index, HEAD and branches are never touched, and a folder without git works the same way.
// snapshot() -> tree id of the folder as it is (.gitignore'd files and big build/data artifacts excluded);
// changes(a, b) -> what differs; diff(a, b) -> unified diff text; restore(a, b) puts every file that changed from a to b
// back as it was in a (files that appeared are removed). Needs git on PATH; without it there are no checkpoints.
const { execFile } = require("child_process");
const fs = require("fs");
const path = require("path");

// never in a checkpoint: dependencies, caches, model weights and array data (big, and rebuilt rather than edited)
const EXCLUDE = ["node_modules/", ".venv/", "venv/", "env/", "__pycache__/", ".ipynb_checkpoints/", ".pytest_cache/",
  "*.pyc", "*.pt", "*.pth", "*.ckpt", "*.safetensors", "*.bin", "*.h5", "*.onnx", "*.npy", "*.npz", "*.parquet", "*.arrow"];
// bytes as they are: no line-ending conversion, no LFS / clean filters (diff drivers: --no-ext-diff --no-textconv below)
const ATTRIBUTES = "* -text -filter -ident -eol\n";
const CONFIG = ["-c", "core.autocrlf=false", "-c", "core.safecrlf=false", "-c", "core.quotepath=false", "-c", "gc.auto=0"];
const MAX_DIFF = 200000;

function run(args, { gitDir, work, input, buffer } = {}) {
  const env = { ...process.env, GIT_TERMINAL_PROMPT: "0" };
  if (gitDir) Object.assign(env, { GIT_DIR: gitDir, GIT_INDEX_FILE: path.join(gitDir, "pablo-index") });
  if (work) env.GIT_WORK_TREE = work;
  return new Promise((res, rej) => {
    const p = execFile("git", [...CONFIG, ...args], { env, cwd: work || undefined, windowsHide: true, maxBuffer: 1 << 28,
      encoding: buffer ? "buffer" : "utf8" }, (err, out, errOut) => err ? rej(new Error(String(errOut || err.message).trim())) : res(out));
    if (input != null) p.stdin.end(input);
  });
}

let available = null;
const has = () => available || (available = run(["--version"]).then(() => true, () => false));
const repo = (dir, task) => path.join(dir, "checkpoints", task.replace(/[^\w.-]/g, "_") + ".git");

async function init(gitDir) {
  if (!fs.existsSync(path.join(gitDir, "HEAD"))) await run(["init", "--bare", "-q", gitDir]);
  fs.mkdirSync(path.join(gitDir, "info"), { recursive: true });
  for (const [f, text] of [["exclude", EXCLUDE.join("\n") + "\n"], ["attributes", ATTRIBUTES]]) {  // kept current across versions
    const p = path.join(gitDir, "info", f);
    if (!fs.existsSync(p) || fs.readFileSync(p, "utf8") !== text) fs.writeFileSync(p, text);
  }
}

// the folder as it is now -> a tree id (kept reachable by a ref, so nothing prunes it)
async function snapshot(dir, task, work) {
  if (!(await has())) return null;
  const gitDir = repo(dir, task);
  await init(gitDir);
  await run(["add", "-A", "--ignore-errors", "."], { gitDir, work }).catch(() => {});  // unreadable files are skipped
  const tree = (await run(["write-tree"], { gitDir, work })).trim();
  const commit = (await run(["commit-tree", tree, "-m", "pablo checkpoint"], { gitDir, work })).trim();
  await run(["update-ref", `refs/pablo/${Date.now()}`, commit], { gitDir, work });
  return tree;
}

// [{status: A|M|D, path}] from tree a to tree b; D7 opts.lines: + {add, del} lines per file (null for a binary file)
async function changes(dir, task, work, a, b, opts = {}) {
  if (!a || !b || a === b) return [];
  const out = await run(["diff-tree", "-r", "--no-renames", "--name-status", "-z", a, b], { gitDir: repo(dir, task), work });
  const xs = out.split("\0").filter(Boolean), rows = [];
  for (let i = 0; i + 1 < xs.length; i += 2) rows.push({ status: xs[i][0], path: xs[i + 1] });
  if (opts.lines && rows.length) {
    const n = await numstat(dir, task, work, a, b);
    for (const r of rows) { const x = n.get(r.path); r.add = x ? x.add : null; r.del = x ? x.del : null; }
  }
  return rows;
}
// D7 path -> {add, del}: the lines a -> b added and removed in each file ("-" for a binary file -> null)
async function numstat(dir, task, work, a, b) {
  const out = await run(["diff-tree", "-r", "--no-renames", "--numstat", "--no-textconv", "--no-ext-diff", "-z", a, b], { gitDir: repo(dir, task), work });
  const m = new Map();
  for (const x of out.split("\0")) {
    const r = x.match(/^(\d+|-)\t(\d+|-)\t([\s\S]+)$/);
    if (r) m.set(r[3], { add: r[1] === "-" ? null : +r[1], del: r[2] === "-" ? null : +r[2] });
  }
  return m;
}

async function diff(dir, task, work, a, b) {
  const out = await run(["diff-tree", "-r", "-p", "--no-renames", "--no-textconv", "--no-ext-diff", "--no-color", a, b],
    { gitDir: repo(dir, task), work });
  return out.length > MAX_DIFF ? out.slice(0, MAX_DIFF) + "\n… (일부만 표시)" : out;
}

// put the folder back to tree a for every file that changed from a to b: written back, or removed if it appeared
async function restore(dir, task, work, a, b) {
  const gitDir = repo(dir, task), rows = await changes(dir, task, work, a, b), root = path.resolve(work);
  for (const r of rows) {
    const f = path.resolve(root, r.path);
    if (path.relative(root, f).startsWith("..")) throw new Error("bad path in checkpoint: " + r.path);
    if (r.status === "A") { fs.rmSync(f, { force: true }); continue; }
    const blob = await run(["cat-file", "blob", `${a}:${r.path}`], { gitDir, work, buffer: true });
    fs.mkdirSync(path.dirname(f), { recursive: true });
    fs.writeFileSync(f, blob);
  }
  return rows;
}

module.exports = { has, snapshot, changes, numstat, diff, restore, EXCLUDE };
