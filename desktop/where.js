// A1/A2 (0.8): a file:line in the task's work folder, read safely, and the 재현 점검 answer checked against it.
// Pure Node (fs + path): main.js uses it for pablo:read-file / pablo:open-file and after an audit; tests run it with node.
//   where(raw)                  "config.yaml:5" | "a.py:10-11" | "a.py:6,15" | "logs\x.log:1" | "/abs/a.py:5" | "a.py#L5" | "a.py"
//                               -> {path, from, to, ranges: [[from, to], ...], also: [the other places of "a.py:3; b.py:7"]}
//   read(work, rel, around?)    -> {path, first, lines, total, truncated}: only inside work (after symlinks), text, <= 1 MB
//   verify(work, item, value?)  -> {check, line_found?}: the model says where and what; Pablo looks (guard.py's rule)
//   hasValue(text, value)       the paper's value in a text: numbers by value ("1,000" = 1000), words case-insensitive
//   follow(work, item, value?)  ⑤ a line that reads a setting (cfg["retrieval"]["top_k"]) -> {where, found, agrees}: the
//                               config line that sets it (a field of its own, `via`; the verdict's check is not changed)
const fs = require("fs");
const path = require("path");

const LIMIT = 1 << 20, MAX_LINES = 5000, SNIFF = 8192;
const NONE = /^(?:-+|n\/?a|none|null|없음|해당\s*없음)$/i;
const ONE = "L?\\d+(?:\\s*[-–~]\\s*L?\\d+)?", LIST = `(${ONE}(?:\\s*,\\s*${ONE})*)`;  // 5 | 10-11 | 6,15 | 5-6, 18
const FORMS = [  // [pattern on the end of the text, what is left is the path]
  new RegExp(`#${LIST}$`),                                                      // a.py#L5, a.py#L5-L7
  new RegExp(`[\\s,(]+(?:lines?|l\\.)\\s*${LIST}\\s*\\)?$`, "i"),               // a.py line 5, a.py (lines 10-11)
  new RegExp(`\\s*${LIST}\\s*(?:행|번째\\s*줄|줄)\\)?$`),                        // a.py 5행, a.py 10-11줄
  new RegExp(`:${LIST}(?::\\d+)?$`),                                             // a.py:5, :10-11, :6,15, :5:3 (column)
];

function place(chunk) {
  let s = chunk.trim().replace(/^`+|`+$/g, "").trim().replace(/\s+\((?!\s*(?:lines?|l\.)\s*\d)[^()]*\)$/i, "");  // "a.py:5 (top_k)": a note
  let ranges = [];
  for (const re of FORMS) {
    const m = s.match(re);
    if (!m) continue;
    ranges = m[1].split(/\s*,\s*/).map(r => { const [a, b] = r.replace(/L/gi, "").split(/\s*[-–~]\s*/).map(Number), f = Math.max(1, a);
      return [f, Math.max(f, b || f)]; });
    s = s.slice(0, m.index);
    break;
  }
  s = s.replace(/^[`'"(]+|[`'"),:]+$/g, "").trim().replace(/\\/g, "/").replace(/^(\.\/)+/, "");
  // a sentence is not a path ("코드 전체"); a file name with spaces still is ("run notes.txt", "my data/x.py")
  if (!s || s.length > 500 || NONE.test(s) || /[\n<>|*?]/.test(s.replace(/^[A-Za-z]:/, "")) || (/\s/.test(s) && !/\/|\.[A-Za-z0-9]{1,8}$/.test(s))) return null;
  return { path: s, from: ranges.length ? ranges[0][0] : null, to: ranges.length ? ranges[0][1] : null, ranges };
}
// several places ("config.yaml:3; run.py:16,25", "a.py:3, b.py:7"): the first is the place, the rest are also there
function where(raw) {
  const ps = String(raw || "").trim().split(/\s*;\s*|\s*,\s+(?=\S*(?:[\w-]\.[A-Za-z]|[\\/]))/).map(place).filter(Boolean);
  return ps.length ? { ...ps[0], also: ps.slice(1) } : null;
}

class ReadError extends Error { constructor(code, message) { super(message); this.code = code; } }
const inside = (root, p) => { const r = path.relative(root, p); return !!r && r !== ".." && !r.startsWith(".." + path.sep) && !path.isAbsolute(r); };
// the real file for rel (relative to work, or absolute), never outside work: checked as written, then after symlinks
function locate(work, rel) {
  const root = fs.realpathSync(work), p = path.resolve(root, rel);
  if (!inside(root, p)) throw new ReadError("outside", "작업 폴더 밖의 파일은 열지 않습니다.");
  let real;
  try { real = fs.realpathSync(p); } catch { throw new ReadError("missing", "작업 폴더에 이 파일이 없습니다."); }
  if (!inside(root, real)) throw new ReadError("outside", "작업 폴더 밖을 가리키는 링크는 열지 않습니다.");
  if (!fs.statSync(real).isFile()) throw new ReadError("missing", "파일이 아닙니다.");
  return { root, real };
}
function load(work, rel) {
  const { root, real } = locate(work, rel);
  if (fs.statSync(real).size > LIMIT) throw new ReadError("large", "1 MB가 넘는 파일은 열지 않습니다.");
  const data = fs.readFileSync(real);
  if (data.subarray(0, SNIFF).includes(0)) throw new ReadError("binary", "텍스트 파일이 아닙니다.");
  const lines = data.toString("utf8").replace(/^﻿/, "").split(/\r?\n/);
  if (lines.length > 1 && lines.at(-1) === "") lines.pop();
  return { path: path.relative(root, real).split(path.sep).join("/"), abs: real, lines };
}
// a long file: the MAX_LINES around the line asked for (first = the line number of lines[0])
function read(work, rel, around) {
  const f = load(work, rel), n = f.lines.length;
  const first = n <= MAX_LINES || !around ? 1 : Math.max(1, Math.min(n - MAX_LINES + 1, around - MAX_LINES / 2));
  return { path: f.path, first, lines: f.lines.slice(first - 1, first - 1 + MAX_LINES), total: n, truncated: n > MAX_LINES };
}

// ---- A2: the audit answer, checked by Pablo ----
// quote style is not a different code: models write cfg['x'] for cfg["x"] (0.8 bench: 4 of 4 false not_found)
const norm = s => String(s || "").normalize("NFKC").toLowerCase().replace(/[‘’“”']/g, '"').replace(/\s+/g, " ").trim();
// found as the model wrote it -> the pieces that must be there in order ("a / b", "a; b", "a ... b", several lines).
// A piece ends on a token boundary ("llm: gpt-4o" is not in "llm: gpt-4o-mini", "top_k: 1" not in "top_k: 10"), except
// where the text was cut: before "..." / "…", or at the end of a found that reached FOUND chars (main.js cuts it there).
const FOUND = 300, TOKEN = /[a-z0-9_-]/;
function pieces(found) {
  const s = String(found || ""), parts = s.replace(/^`+|`+$/g, "").split(/(\n|\s\/\s|;\s+|\.\.\.|…)/), out = [];
  for (let i = 0; i < parts.length; i += 2) {
    const text = norm(parts[i]), next = parts[i + 1];
    if (text) out.push({ text, cut: next === "..." || next === "…" || (next === undefined && s.length >= FOUND) });
  }
  return out;
}
const goesOn = (t, j) => TOKEN.test(t[j] || "") || (t[j] === "." && TOKEN.test(t[j + 1] || ""));  // "gpt-4o|-mini", "0|.01"
function within(text, ps) {
  const t = norm(text);
  let at = 0;
  for (const p of ps) {
    const strict = !p.cut && TOKEN.test(p.text.at(-1));
    let i = t.indexOf(p.text, at);
    while (i >= 0 && strict && goesOn(t, i + p.text.length)) i = t.indexOf(p.text, i + 1);  // a later whole one still counts
    if (i < 0) return false;
    at = i + p.text.length;
  }
  return true;
}
const NUM = /(?<![A-Za-z0-9_.])\d+(?:,\d{3})*(?:\.\d+)?(?:e[-+]?\d+)?(?![A-Za-z0-9_])/gi;
const number = v => { const m = String(v).trim().match(/^[~≈]?\s*(\d+(?:,\d{3})*(?:\.\d+)?(?:e[-+]?\d+)?)\s*%?$/i); return m ? +m[1].replace(/,/g, "") : null; };
const same = (a, b) => Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a));
// a value code has to spell out: a number ("5", "0.85", "1,000", "63.70%") or one identifier with a digit in it
// ("GPT-4o-mini", "all-mpnet-base-v2"). A concept ("punctuation", "Personalized PageRank", "GPT-ACC") is implemented,
// not written: re.split(...), nx.pagerank(...) follow it without its name (0.8 bench: 29 false warnings).
function checkable(value) {
  const v = String(value || "").trim();
  return !!v && (number(v) !== null || (v.length <= 60 && /^\S+$/.test(v) && /\d/.test(v) && /[A-Za-z]/.test(v)));
}
function hasValue(text, value) {
  const nums = [...String(text || "").matchAll(NUM)].map(m => +m[0].replace(/,/g, "")), flat = norm(text).replace(/ /g, "");
  const n = number(value);
  if (n !== null) return nums.some(x => same(x, n));
  const ts = norm(value).split(/[\s()[\]]+/).filter(Boolean);
  return ts.length > 0 && ts.every(t => number(t) !== null ? nums.some(x => same(x, number(t))) : flat.includes(t));
}
// verified | moved (line_found) | not_found | no_file | value_mismatch | unchecked. Read-only, never throws.
function verify(work, item, value) {
  const w = where(item && item.where);
  if (!w || !work) return { check: "unchecked" };
  const files = [];  // the places Pablo could open, in the order given
  let skipped = false;
  for (const p of [w, ...w.also]) {
    try { files.push({ p, lines: load(work, p.path).lines }); }
    catch (e) { skipped = skipped || e.code === "large" || e.code === "binary"; }
  }
  if (!files.length) return { check: skipped ? "unchecked" : "no_file" };
  const ps = pieces(item.found), main = files[0].p === w ? files[0].lines : null;
  if (!ps.length) return { check: main && w.from && w.from > main.length ? "not_found" : "unchecked" };
  // every range of every place (+-2 lines), in order: "a.py:10,13,16" with found "x; y; z" is one text
  const near = files.flatMap(({ p, lines }) => { const keep = new Set();
    for (const [a, b] of p.ranges) for (let i = Math.max(0, a - 3); i < Math.min(lines.length, b + 2); i++) keep.add(i);
    return [...keep].sort((x, y) => x - y).map(i => lines[i]); });
  let out = null;
  if (near.length && within(near.join("\n"), ps)) out = { check: "verified" };
  else {  // the lines where it starts (the window from i has it, the one from i + 1 to the same end does not): the nearest
    if (!main) return { check: "not_found" };  // only the first place's file can say "it is on line n" (the panel opens it)
    const lines = main, span = String(item.found).split("\n").length + 2, at = [];
    for (let i = 0; i < lines.length; i++)
      if (within(lines.slice(i, i + span).join("\n"), ps) && !within(lines.slice(i + 1, i + span).join("\n"), ps)) at.push(i + 1);
    if (!at.length) return { check: "not_found" };
    const line = at.reduce((a, b) => Math.abs(b - (w.from || 0)) < Math.abs(a - (w.from || 0)) ? b : a);
    out = { check: w.from ? "moved" : "verified", line_found: line };
  }
  // the paper's value against the verdict: followed must show it there, differs must not (one value only, see checkable)
  const s = item.status;
  if ((s === "followed" || s === "differs") && checkable(value) && hasValue(item.found, value) !== (s === "followed"))
    return { ...out, check: "value_mismatch" };
  return out;
}

// ---- ⑤ the setting a line reads, in the config file that sets it ----
// 0.8 hard set: on a clean folder the model named the line that reads a value (cfg["llm"]), not the one that sets it, and
// the value check warned (value_mismatch) 3 times. follow() finds the setting's own line: the last key of the path
// (cfg["retrieval"]["top_k"], cfg.get("retrieval").get("top_k"), args.top_k) set in one config file of the folder, under
// its parent key when the path has one. Two places that both set it, or none: null (Pablo does not guess).
const CONFIG = /\.(ya?ml|json|toml|ini|cfg|conf)$/i;
const SKIP = /^(\.git|\.hg|\.svn|node_modules|\.?venv|env|__pycache__|\.pablo|\.idea|\.vscode|site-packages|wandb|outputs?)$/i;
function keysOf(found) {
  const s = String(found || "");
  let m = s.match(/[A-Za-z_]\w*((?:\s*\[\s*["'][\w.-]+["']\s*\])+)/);
  if (m) return [...m[1].matchAll(/["']([\w.-]+)["']/g)].map(x => x[1]);
  const gets = [...s.matchAll(/\.get\(\s*["']([\w.-]+)["']/g)].map(x => x[1]);
  if (gets.length) return gets;
  m = s.match(/\b(?:cfg|cfgs|config|configs|conf|args|opt|opts|hparams|hp|params|settings)((?:\.[A-Za-z_]\w*)+)/i);
  return m ? m[1].slice(1).split(".") : [];
}
function configs(dir, depth = 0, out = []) {  // the folder's config files (links are not followed: they stay inside)
  let ents = [];
  try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch { return out; }
  for (const e of ents) {
    if (out.length >= 200) break;
    if (e.isDirectory() && depth < 4 && !SKIP.test(e.name)) configs(path.join(dir, e.name), depth + 1, out);
    else if (e.isFile() && CONFIG.test(e.name)) out.push(path.join(dir, e.name));
  }
  return out;
}
const indent = l => l.match(/^\s*/)[0].length;
function parentOf(lines, i) {  // the key line i is under: the nearest line above with less indent, else the [section] above
  const d = indent(lines[i]);
  for (let j = i - 1; j >= 0; j--) {
    const l = lines[j];
    if (!l.trim() || /^\s*(#|\/\/|;)/.test(l)) continue;
    if (indent(l) < d) { const m = l.match(/^\s*["']?([\w.-]+)["']?\s*[:=]/); return m ? m[1] : null; }
    const s = d === 0 && l.match(/^\s*\[\s*([\w.-]+)\s*\]\s*$/);
    if (s) return s[1].split(".").at(-1);
  }
  return null;
}
function follow(work, item, value) {
  try {
    const s = item && item.status, keys = keysOf(item && item.found);
    if (!work || !keys.length || !(s === "followed" || s === "differs") || !checkable(value) || hasValue(item.found, value)) return null;
    const last = keys.at(-1), parent = keys.at(-2), root = fs.realpathSync(work);
    const set = new RegExp(`^\\s*(?:-\\s+)?["']?${last.replace(/[.-]/g, "\\$&")}["']?\\s*[:=]\\s*(\\S.*)$`), hits = [];
    for (const f of configs(root)) {
      let lines;
      try { if (fs.statSync(f).size > LIMIT) continue; lines = fs.readFileSync(f, "utf8").replace(/^﻿/, "").split(/\r?\n/); } catch { continue; }
      lines.forEach((l, i) => { const m = l.match(set);  // "retrieval:" / "retrieval": { hold keys, they do not set one
        if (m && !/^[{[]\s*,?$/.test(m[1].trim())) hits.push({ f, i, line: l, score: parent && parentOf(lines, i) === parent ? 1 : 0 }); });
    }
    const top = Math.max(...hits.map(x => x.score)), best = hits.filter(x => x.score === top);
    if (best.length !== 1) return null;
    const b = best[0], found = b.line.trim().slice(0, FOUND), bare = found.replace(/\s+(#|\/\/|;).*$/, "");  // a comment's numbers are not the value
    return { where: `${path.relative(root, b.f).split(path.sep).join("/")}:${b.i + 1}`, found, agrees: hasValue(bare, value) === (s === "followed") };
  } catch { return null; }
}

module.exports = { where, read, locate, verify, follow, hasValue, checkable, ReadError, LIMIT, MAX_LINES, FOUND };
