// The only script Pablo runs inside a source page: find the evidence quote, highlight it, scroll to it, report.
// It reads text nodes only. No inputs, forms, cookies, storage or network; it never clicks or navigates.
// Runs in an isolated world, so the page cannot call it and it cannot call the page.
function locate(q) {
  // same text model as evidence.normalize (M3.1): skip these subtrees, a space at every non-inline tag, \s+ -> " "
  const SKIP = new Set(["script", "style", "noscript", "template", "svg", "head"]);
  const INLINE = new Set(["a", "abbr", "b", "code", "em", "i", "kbd", "mark", "s", "samp", "small", "span", "strong",
    "sub", "sup", "u", "var"]);
  const chars = [], map = [];  // map[i] = [text node, offset], or null for a tag boundary space
  const add = (ch, node, off) => {
    if (/\s/.test(ch)) { if (!chars.length || chars[chars.length - 1] === " ") return; ch = " "; }
    chars.push(ch); map.push(node ? [node, off] : null);
  };
  const walk = n => {
    for (let c = n.firstChild; c; c = c.nextSibling) {
      if (c.nodeType === 3) { for (let i = 0; i < c.data.length; i++) add(c.data[i], c, i); continue; }
      if (c.nodeType !== 1 || SKIP.has(c.localName)) continue;
      const block = !INLINE.has(c.localName);
      if (block) add(" ");
      walk(c);
      if (block) add(" ");
    }
  };
  walk(document.documentElement);
  const T = chars.join(""), ex = q.exact.replace(/\s+/g, " ").trim();
  const hits = [];
  for (let i = ex ? T.indexOf(ex) : -1; i >= 0; i = T.indexOf(ex, i + 1)) hits.push(i);
  if (!hits.length) return { status: "NOT_FOUND", count: 0 };

  // several hits: the stored prefix / suffix decide; whitespace-insensitive, never "the first one"
  const sq = s => (s || "").replace(/\s+/g, ""), P = sq(q.prefix), S = sq(q.suffix);
  const before = i => sq(T.slice(Math.max(0, i - 2 * P.length - 2), i)).endsWith(P);
  const after = i => sq(T.slice(i + ex.length, i + ex.length + 2 * S.length + 2)).startsWith(S);
  let how = "unique", pick = hits;
  if (hits.length > 1) {
    how = "context"; pick = hits.filter(i => before(i) && after(i));
    if (!pick.length) { how = "partial_context"; pick = hits.filter(i => before(i) || after(i)); }
  }
  if (pick.length !== 1) return { status: "AMBIGUOUS", count: hits.length, matched: pick.length };

  const i = pick[0];
  let s = i, e = i + ex.length - 1;
  while (s < e && !map[s]) s++;
  while (e > s && !map[e]) e--;
  const r = document.createRange();
  r.setStart(map[s][0], map[s][1]); r.setEnd(map[e][0], map[e][1] + 1);
  CSS.highlights.set("pablo", new Highlight(r));
  const visible = r.getClientRects().length > 0;
  if (visible) r.startContainer.parentElement.scrollIntoView({ block: "center", behavior: "instant" });
  return { status: "FOUND", count: hits.length, index: hits.indexOf(i), how, visible, text: r.toString() };
}

const WORLD = 1717;  // isolated world id
const CSS_TEXT = "::highlight(pablo) { background-color: #fde68a; color: #111; }";

// guest: a <webview> WebContents. NOT_FOUND gets a short bounded retry for pages that render after load.
async function run(guest, q, tries = 6, wait = 500) {
  const code = `(${locate})(${JSON.stringify({ exact: q.exact, prefix: q.prefix, suffix: q.suffix })})`;
  for (let k = 1; ; k++) {
    const r = await guest.executeJavaScriptInIsolatedWorld(WORLD, [{ code }]);
    if (r.status !== "NOT_FOUND" || k >= tries) {
      if (r.status === "FOUND") await guest.insertCSS(CSS_TEXT);
      return { ...r, tries: k };
    }
    await new Promise(res => setTimeout(res, wait));
  }
}

module.exports = { locate, run };
