// C1/C2 (0.8): a task's papers in desktop.json, and arXiv ids. Pure Node (main.js uses it; tests run it with node).
//   list(desk, task)      -> [{id, title, version?, arxiv?, sha256?}]  (0.7 kept one {id, title} per task: a list of one)
//   primary(desk, task)   -> the 주 논문 (the paper being reproduced): desk.primary[task] while it is still one of the
//                            task's papers, else the first one, else null
//   migrate(desk)         -> desk with every pdf[task] a list (written back on the next save)
//   arxiv(text)           -> {id, version} for "2510.10114", "arXiv:2510.10114v4", "https://arxiv.org/abs/2510.10114v4",
//                            ".../pdf/2510.10114v2.pdf", "hep-th/9901001"; null for anything else (another site, a name)
//   fetchPdf(url, opts)   -> Buffer: one PDF from opts.origin only, at most opts.max bytes, within opts.ms
//   web(text)             -> D1: the http(s) address of a web page (not arXiv: that is a paper), else null
//   openreview(text)      -> ⑬ {id} for "https://openreview.net/forum?id=…" / "…/pdf?id=…", else null
//   doi(text)             -> ⑬ {doi} for "10.1145/…", "doi:10.…", "https://doi.org/10.…" (an arXiv DOI is arxiv()'s), else null
//   searchQuery(text)     -> D2: the arXiv API's search_query for the words a user typed ("graph rag" -> all:graph AND all:rag)
//   atom(xml)             -> D2: [{id, version, title, authors, year, summary}] from the arXiv API's Atom feed
// A task's sources are one list (pdf[task]); a web page's entry has kind "web". Only papers (PDFs) can be the 주 논문.
const list = (desk, task) => { const p = ((desk || {}).pdf || {})[task]; return Array.isArray(p) ? p : p && p.id ? [p] : []; };
function primary(desk, task) {
  const ps = list(desk, task).filter(p => p.kind !== "web"), id = ((desk || {}).primary || {})[task];
  return ps.find(p => p.id === id) || ps[0] || null;
}
const migrate = desk => ({ ...desk, pdf: Object.fromEntries(Object.keys((desk || {}).pdf || {}).map(t => [t, list(desk, t)])) });

const ID = "(\\d{4}\\.\\d{4,5}|[a-z][a-z-]*(?:\\.[A-Z]{2})?\\/\\d{7})(v\\d+)?";
const FORMS = [new RegExp(`^(?:arxiv:\\s*)?${ID}$`, "i"),
  new RegExp(`^(?:https?:\\/\\/)?(?:www\\.|export\\.)?arxiv\\.org\\/(?:abs|pdf)\\/${ID}(?:\\.pdf)?\\/?$`, "i"),
  new RegExp(`^(?:https?:\\/\\/(?:dx\\.)?doi\\.org\\/|doi:\\s*)?10\\.48550\\/arxiv\\.${ID}$`, "i")];  // ⑬ arXiv's own DOIs
// YYMM.NNNN until 2014, YYMM.NNNNN from 2015 (arXiv's own rule): "2510.1011" is a typo, not a paper
const real = id => { const m = id.match(/^(\d\d)(\d\d)\.(\d+)$/);
  return !m || (+m[2] >= 1 && +m[2] <= 12 && m[3].length === (+(m[1] + m[2]) >= 1501 ? 5 : 4)); };
function arxiv(text) {
  const s = String(text || "").trim();
  for (const re of FORMS) { const m = s.match(re); if (m && real(m[1])) return { id: m[1], version: m[2] || null }; }
  return null;
}

// the download itself: redirects followed by hand and only within the origin (no request ever leaves it), size checked
// as it streams, "%PDF" at the start
async function fetchPdf(url, { origin, max = 50 << 20, ms = 60000, site = "arXiv", missing } = {}) {
  let at = new URL(url), r;
  const signal = AbortSignal.timeout(ms);
  for (let hop = 0; ; hop++) {
    if (origin && at.origin !== origin) throw new Error(hop ? `${site} 밖으로 넘겨져 받지 않았습니다.` : `${site} 밖의 주소는 받지 않습니다.`);
    r = await fetch(at, { signal, redirect: "manual", headers: { accept: "application/pdf" } });
    if (r.status < 300 || r.status >= 400 || !r.headers.get("location")) break;
    if (hop >= 5) throw new Error(`${site}가 너무 여러 번 다른 주소로 넘겼습니다.`);
    at = new URL(r.headers.get("location"), at);
  }
  if (r.status === 404) throw new Error(missing || `${site}에 그 번호의 논문이 없습니다.`);
  if (!r.ok) throw new Error(`${site}에서 받지 못했습니다(HTTP ${r.status}).`);
  if (+(r.headers.get("content-length") || 0) > max) throw new Error(`PDF가 ${max >> 20} MB보다 큽니다.`);
  const parts = [];
  let n = 0;
  for await (const c of r.body) {
    n += c.length;
    if (n > max) throw new Error(`PDF가 ${max >> 20} MB보다 큽니다.`);
    parts.push(Buffer.from(c));
  }
  const data = Buffer.concat(parts);
  if (data.subarray(0, 5).toString("latin1") !== "%PDF-") throw new Error("받은 파일이 PDF가 아닙니다.");
  return data;
}

function openreview(text) {
  const m = String(text || "").trim().match(/^(?:https?:\/\/)?(?:www\.)?openreview\.net\/(?:forum|pdf)\?(?:[^#\s]*&)?id=([A-Za-z0-9_-]{4,40})(?:[&#][^\s]*)?$/i);
  return m ? { id: m[1] } : null;
}
function doi(text) {
  const s = String(text || "").trim(), m = s.match(/^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)?(10\.\d{4,9}\/[^\s"<>]{1,200})$/i);
  return m && !arxiv(s) ? { doi: m[1].replace(/[.,;)]+$/, "") } : null;
}
function web(text) {
  const s = String(text || "").trim();
  if (!/^https?:\/\/[^\s/?#]+[^\s]*$/i.test(s) || s.length > 2000 || arxiv(s) || openreview(s) || doi(s)) return null;
  try { return new URL(s).href; } catch { return null; }
}

// D2: words -> all:w1 AND all:w2 (letters, digits, "-" and "." kept; at most 8 words); "" when nothing is left
const searchQuery = text => String(text || "").normalize("NFKC").split(/\s+/).map(w => w.replace(/[^\p{L}\p{N}.-]/gu, ""))
  .filter(Boolean).slice(0, 8).map(w => "all:" + w).join(" AND ");
const unxml = s => String(s || "").replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
  .replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'").replace(/&amp;/g, "&").replace(/\s+/g, " ").trim();
function atom(xml) {
  return [...String(xml || "").matchAll(/<entry>([\s\S]*?)<\/entry>/g)].map(([, e]) => {
    const tag = t => unxml((e.match(new RegExp(`<${t}(?:\\s[^>]*)?>([\\s\\S]*?)</${t}>`)) || [])[1]);
    const a = arxiv(tag("id"));  // http://arxiv.org/abs/2502.14802v2
    if (!a) return null;
    const names = [...e.matchAll(/<author>\s*<name>([\s\S]*?)<\/name>/g)].map(m => unxml(m[1]));
    return { id: a.id, version: a.version, title: tag("title"), year: tag("published").slice(0, 4),
      authors: names.slice(0, 3).join(", ") + (names.length > 3 ? " 외" : ""), summary: tag("summary").slice(0, 240) };
  }).filter(Boolean);
}

module.exports = { list, primary, migrate, arxiv, openreview, doi, fetchPdf, web, searchQuery, atom };
