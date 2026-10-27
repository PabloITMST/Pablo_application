// Local CI: what .github/workflows/test.yml runs, plus the offline UI checks, in one command (from the repo root).
//   npm --prefix desktop run ci              python tests, then check.js --ui and --auth (signed in against a fake server)
//   npm --prefix desktop run ci -- --python  only the python tests (the same loop as the workflow)
//   npm --prefix desktop run ci -- --ui      only the two UI checks
// build/venv goes first on PATH when it exists (check.js and the tests call `python`). The workflow uses Python 3.11;
// another version is reported, not refused. LinearRAG.pdf (not in the repo) is fetched from arXiv when missing and
// checked by sha256, as the workflow does. Stops at the first failure; exit code 1.
const { spawnSync } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const PDF = path.join(ROOT, "LinearRAG.pdf"), PDF_URL = "https://arxiv.org/pdf/2510.10114v4";
const PDF_SHA = "1df0bd67b590f331d7928c65bbdc0a086ce6c41195428a8f3670683dcd3de533";

const args = process.argv.slice(2);
const only = args.includes("--python") ? "python" : args.includes("--ui") ? "ui" : null;

const venv = path.join(ROOT, "build", "venv", process.platform === "win32" ? "Scripts" : "bin");
const env = { ...process.env, PYTHONIOENCODING: "utf-8" };
const key = Object.keys(env).find(k => k.toUpperCase() === "PATH") || "PATH";
if (fs.existsSync(venv)) env[key] = venv + path.delimiter + env[key];

const run = (cmd, argv, cwd = ROOT) => spawnSync(cmd, argv, { cwd, env, stdio: "inherit" }).status === 0;
const fail = msg => { console.error(`\nFAIL ${msg}`); process.exit(1); };
const sha = file => crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");

async function paper() {
  if (fs.existsSync(PDF) && sha(PDF) === PDF_SHA) return;
  console.log(`== LinearRAG.pdf: fetching ${PDF_URL}`);
  const res = await fetch(PDF_URL);
  if (!res.ok) fail(`LinearRAG.pdf: HTTP ${res.status}`);
  fs.writeFileSync(PDF, Buffer.from(await res.arrayBuffer()));
  if (sha(PDF) !== PDF_SHA) fail("LinearRAG.pdf: sha256 differs from the workflow's");
}

function python() {
  const v = spawnSync("python", ["--version"], { env, encoding: "utf8" });
  if (v.status !== 0) fail("python not found (build/venv or PATH)");
  const version = (v.stdout || v.stderr).trim();
  console.log(`== ${version}${fs.existsSync(venv) ? " (build/venv)" : ""}${/ 3\.11\./.test(version) ? "" : "  -- the workflow uses 3.11"}`);
  const tests = fs.readdirSync(path.join(ROOT, "tests"), { withFileTypes: true }).filter(d => d.isDirectory())
    .flatMap(d => fs.readdirSync(path.join(ROOT, "tests", d.name)).filter(f => /^test_.*\.py$/.test(f)).map(f => `tests/${d.name}/${f}`))
    .sort();
  for (const t of tests) {
    console.log(`== ${t}`);
    if (!run("python", [t])) fail(t);
  }
  return tests.length;
}

function ui() {
  console.log("== check.js --ui");
  if (!run(require("electron"), ["check.js", "--ui"], __dirname)) fail("check.js --ui");
  // --auth opens a fixture's page (its first argument) and signs in: the screen only a connected app shows
  const dir = fs.mkdtempSync(path.join(require("os").tmpdir(), "pablo-ci-auth-"));
  const fx = spawnSync("python", [path.join(ROOT, "tests", "skill", "ui_fixture.py"), dir], { env, encoding: "utf8" });
  if (fx.status !== 0) fail("ui_fixture.py: " + (fx.stderr || "").slice(-300));
  console.log("== check.js --auth");
  if (!run(require("electron"), ["check.js", JSON.parse(fx.stdout).view, "--auth"], __dirname)) fail("check.js --auth");
}

(async () => {
  const t0 = Date.now(), done = [];
  if (only !== "ui") { await paper(); done.push(`python tests ${python()}`); }
  if (only !== "python") { ui(); done.push("check --ui, --auth"); }
  console.log(`\nLOCAL CI OK: ${done.join(", ")} (${Math.round((Date.now() - t0) / 1000)}s)`);
})();
