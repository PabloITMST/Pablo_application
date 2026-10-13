// A1/A2 (0.8): a file:line in the task's work folder, read safely, and the 재현 점검 answer checked against it.
// Pure Node (fs + path): main.js uses it for pablo:read-file / pablo:open-file and after an audit; tests run it with node.
//   where(raw)                  "config.yaml:5" | "a.py:10-11" | "logs\x.log:1" | "/abs/a.py:5" | "a.py#L5" | "a.py" -> {path, from, to}
//   read(work, rel, around?)    -> {path, first, lines, total, truncated}: only inside work (after symlinks), text, <= 1 MB
//   verify(work, item, value?)  -> {check, line_found?}: the model says where and what; Pablo looks (guard.py's rule)
//   hasValue(text, value)       the paper's value in a text: numbers by value ("1,000" = 1000), words case-insensitive
const fs = require("fs");
const path = require("path");

const LIMIT = 1 << 20, MAX_LINES = 5000, SNIFF = 8192;
const NONE = /^(?:-+|n\/?a|none|null|없음|해당\s*없음)$/i;
const RANGE = "(\\d+)(?:\\s*[-–~]\\s*L?(\\d+))?";
const FORMS = [  // [pattern on the end of the text, what is left is the path]
  new RegExp(`#L${RANGE}$`),                                                    // a.py#L5, a.py#L5-L7
  new RegExp(`[\\s,(]+(?:lines?|l\\.)\\s*${RANGE}\\s*\\)?$`, "i"),              // a.py line 5, a.py (lines 10-11)
  new RegExp(`\\s*${RANGE}\\s*(?:행|번째\\s*줄|줄)\\)?$`),                       // a.py 5행, a.py 10-11줄
  new RegExp(`:L?${RANGE}(?::\\d+)?$`),                                          // a.py:5, a.py:10-11, a.py:5:3 (column)
];

function where(raw) {
  let s = String(raw || "").trim().split(/\s*[;,]\s+(?=\S*(?:[\w-]\.[A-Za-z]|[\\/]))/)[0];  // "a.py:3, b.py:7" -> the first
  s = s.replace(/^`+|`+$/g, "").trim().replace(/\s+\((?!\s*(?:lines?|l\.)\s*\d)[^()]*\)$/i, "");  // "a.py:5 (top_k)": a note
  let from = null, to = null;
  for (const re of FORMS) {
    const m = s.match(re);
    if (!m) continue;
    from = Math.max(1, +m[1]); to = Math.max(from, m[2] ? +m[2] : from);
    s = s.slice(0, m.index);
    break;
  }
  s = s.replace(/^[`'"(]+|[`'"),:]+$/g, "").trim().replace(/\\/g, "/").replace(/^(\.\/)+/, "");
  // a sentence is not a path ("코드 전체"); a file name with spaces still is ("run notes.txt", "my data/x.py")
  if (!s || s.length > 500 || NONE.test(s) || /[\n<>|*?]/.test(s.replace(/^[A-Za-z]:/, "")) || (/\s/.test(s) && !/\/|\.[A-Za-z0-9]{1,8}$/.test(s))) return null;
  return { path: s, from, to };
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
const norm = s => String(s || "").normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim();
// found as the model wrote it -> the pieces that must be there in order ("a / b", "a ... b", several lines)
const pieces = found => String(found || "").replace(/^`+|`+$/g, "").split(/\n|\s\/\s|\.\.\.|…/).map(norm).filter(Boolean);
function within(text, ps) {
  const t = norm(text);
  let at = 0;
  for (const p of ps) { const i = t.indexOf(p, at); if (i < 0) return false; at = i + p.length; }
  return true;
}
const NUM = /(?<![A-Za-z0-9_.])\d+(?:,\d{3})*(?:\.\d+)?(?:e[-+]?\d+)?(?![A-Za-z0-9_])/gi;
const number = v => { const m = String(v).trim().match(/^[~≈]?\s*(\d+(?:,\d{3})*(?:\.\d+)?(?:e[-+]?\d+)?)\s*%?$/i); return m ? +m[1].replace(/,/g, "") : null; };
const same = (a, b) => Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a));
// one value ("5", "0.85", "1,000", "63.70%", "GPT-4o-mini", "Personalized PageRank"), not a list or a description
function checkable(value) {
  const v = String(value || "").trim();
  return !!v && (number(v) !== null || (!/[,;]/.test(v) && v.length <= 60 && v.split(/\s+/).length <= 3));
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
  let lines;
  try { lines = load(work, w.path).lines; }
  catch (e) { return { check: e.code === "large" || e.code === "binary" ? "unchecked" : "no_file" }; }
  const ps = pieces(item.found);
  if (!ps.length) return { check: w.from && w.from > lines.length ? "not_found" : "unchecked" };
  let out = null;
  if (w.from && w.from <= lines.length && within(lines.slice(Math.max(0, w.from - 3), w.to + 2).join("\n"), ps)) out = { check: "verified" };
  else {  // the lines where it starts (the window from i has it, the one from i + 1 to the same end does not): the nearest
    const span = String(item.found).split("\n").length + 2, at = [];
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

module.exports = { where, read, locate, verify, hasValue, checkable, ReadError, LIMIT, MAX_LINES };
