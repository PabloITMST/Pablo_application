"""Evidence anchors (M3.1): pin a quote in a captured source version, find it again later. Deterministic only.

  normalize(html) -> text   visible text, whitespace collapsed; the hash and every offset refer to this text
  locate(text, exact, near) -> (start, end)   refuses missing or ambiguous quotes
  resolve(anchor, old_hash, text) -> {status VALID | STALE | UNRESOLVED, reason, hash_changed, start, end}
Relevance (does the quote support the claim) is not decided here.
"""
from __future__ import annotations

import hashlib
import re
import urllib.request
from html.parser import HTMLParser

CONTEXT = 32  # prefix / suffix length
NEAR_WINDOW = 300  # how far --near text may be from the quote
SKIP = {"script", "style", "noscript", "template", "svg", "head"}
INLINE = {"a", "abbr", "b", "code", "em", "i", "kbd", "mark", "s", "samp", "small", "span", "strong", "sub", "sup",
          "u", "var"}


class AnchorRejected(ValueError):
    """The quote is not in the source, or appears more than once without a --near disambiguation."""


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip, self.title, self._in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        self.skip += tag in SKIP
        self._in_title |= tag == "title"
        if tag not in INLINE:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        self.skip -= tag in SKIP and self.skip > 0
        self._in_title &= tag != "title"
        if tag not in INLINE:
            self.parts.append(" ")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def normalize(html: str) -> tuple[str, str]:
    """-> (visible text, title)."""
    p = _Text()
    p.feed(html)
    p.close()
    return ws("".join(p.parts)), ws(p.title)


DISPLAY = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "blockquote"}
HIDE = {"nav", "footer", "aside"}  # site chrome: kept in the canonical text, hidden in the viewer


class _Blocks(_Text):
    """Same text as _Text, plus events at every block boundary and inline <code> edge, as parts indexes."""

    def __init__(self):
        super().__init__()
        self.stack, self.code = [], False
        self.events = [(0, "cut", "div")]

    def _kind(self):
        if HIDE & set(self.stack):
            return "hide"
        return next((t for t in reversed(self.stack) if t in DISPLAY), "div")

    def handle_starttag(self, tag, attrs):
        if tag in DISPLAY or tag in HIDE:
            self.stack.append(tag)
        if tag == "code" and not self.code and "pre" not in self.stack:
            self.code = True
            self.events.append((len(self.parts), "code", None))
        super().handle_starttag(tag, attrs)
        if tag not in INLINE:
            self.events.append((len(self.parts), "cut", self._kind()))

    def handle_endtag(self, tag):
        if tag in self.stack:  # also closes unclosed <p>/<li> inside it
            del self.stack[len(self.stack) - 1 - self.stack[::-1].index(tag):]
        super().handle_endtag(tag)
        if tag == "code" and self.code:
            self.code = False
            self.events.append((len(self.parts), "/code", None))
        if tag not in INLINE:
            self.events.append((len(self.parts), "cut", self._kind()))


def display(html: str) -> tuple[str, dict]:
    """Presentation only: (canonical text, {"blocks": [[kind, start, end]], "code": [[start, end]]}).
    Offsets point into the same canonical text as normalize(); never used for hashing or anchoring."""
    p = _Blocks()
    p.feed(html)
    p.close()
    text, out, gap, i, pos = ws("".join(p.parts)), 0, False, 0, []
    for k, _, _ in p.events:  # canonical (end of text so far, where the next visible char lands)
        for m in re.finditer(r"(\s+)|\S+", "".join(p.parts[i:k])):
            if m.group(1):
                gap = True
            else:
                out, gap = out + (gap and out > 0) + len(m.group()), False
        pos.append((out, min(out + (gap and out > 0), len(text))))
        i = k
    cuts = [(kind, pos[j]) for j, (_, ev, kind) in enumerate(p.events) if ev == "cut"]
    blocks = [[kind, s, e] for (kind, (_, s)), (_, (e, _)) in zip(cuts, cuts[1:] + [("", (len(text), 0))]) if e > s]
    code, start = [], None
    for (_, ev, _), (end, nxt) in zip(p.events, pos):
        if ev == "code":
            start = nxt
        elif ev == "/code" and start is not None:
            if end > start:
                code.append([start, end])
            start = None
    return text, {"blocks": blocks, "code": code}


def content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def fetch(url: str) -> str:
    """Raw HTML. Raises OSError (URLError, timeouts) on failure."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (pablo-evidence)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")


def _all(text: str, s: str) -> list[int]:
    return [m.start() for m in re.finditer(re.escape(s), text)] if s else []


def locate(text: str, exact: str, near: str = "") -> tuple[int, int]:
    exact, near = ws(exact), ws(near)
    hits = _all(text, exact)
    if not hits:
        raise AnchorRejected(f"quote not found in the captured source: {exact!r}")
    if near:  # keep the occurrence(s) closest to the --near text
        nears = _all(text, near)
        gap = {h: min((max(n - (h + len(exact)), h - (n + len(near)), 0) for n in nears), default=NEAR_WINDOW + 1)
               for h in hits}
        best = min(gap.values())
        if best > NEAR_WINDOW:
            raise AnchorRejected(f"no occurrence of the quote has {near!r} within {NEAR_WINDOW} chars")
        hits = [h for h in hits if gap[h] == best]
    if len(hits) > 1:
        raise AnchorRejected(f"quote appears {len(hits)} times; add --near with text next to the one you mean")
    return hits[0], hits[0] + len(exact)


def context(text: str, start: int, end: int) -> dict:
    return {"exact": text[start:end], "prefix": text[max(0, start - CONTEXT):start], "suffix": text[end:end + CONTEXT]}


def resolve(quote: dict, selector: dict, old_hash: str, text: str) -> dict:
    """Find the anchor in the current text of its source."""
    new_hash = content_hash(text)
    if new_hash == old_hash:
        return {"status": "VALID", "reason": None, "hash_changed": False, "start": selector["start"],
                "end": selector["end"], "content_hash": new_hash}
    out = {"hash_changed": True, "start": None, "end": None, "content_hash": new_hash}
    full = quote["prefix"] + quote["exact"] + quote["suffix"]
    if len(hits := _all(text, full)) == 1:
        start = hits[0] + len(quote["prefix"])
        return {**out, "status": "VALID", "reason": "relocated", "start": start, "end": start + len(quote["exact"])}
    if n := len(_all(text, quote["exact"])):
        return {**out, "status": "STALE", "reason": "context_changed" if not hits else "ambiguous",
                "occurrences": n}
    return {**out, "status": "UNRESOLVED", "reason": "not_found"}


if __name__ == "__main__":  # self-check
    html = ("<html><head><title>Doc</title><script>x=1</script></head><body><h1>API</h1>"
            "<p>Call <code>account/rateLimits/read</code> to read limits.</p><p>See account/rateLimits/read.</p></body>")
    t, title = normalize(html)
    assert title == "Doc" and "x=1" not in t and "Call account/rateLimits/read to read" in t, t
    try:
        locate(t, "account/rateLimits/read")
        raise AssertionError("ambiguous quote accepted")
    except AnchorRejected:
        pass
    s, e = locate(t, "account/rateLimits/read", near="to read limits")
    q, sel, h = context(t, s, e), {"start": s, "end": e}, content_hash(t)
    assert resolve(q, sel, h, t)["status"] == "VALID"
    moved = resolve(q, sel, h, "New intro. " + t)
    assert moved["reason"] == "relocated" and moved["start"] == s + 11, moved
    assert resolve(q, sel, h, t.replace("to read limits", "for quotas"))["status"] == "STALE"
    assert resolve(q, sel, h, t.replace("account/rateLimits/read", "x"))["status"] == "UNRESOLVED"
    extra = "<nav><a>Home</a></nav><ul><li>one<p>  two </p>three<li>four</ul><pre>a\n  b</pre><h2>End</h2>"
    bt, d = display(html + extra)
    assert bt == normalize(html + extra)[0]
    assert [(k, bt[s:e]) for k, s, e in d["blocks"]] == [
        ("h1", "API"), ("p", "Call account/rateLimits/read to read limits."), ("p", "See account/rateLimits/read."),
        ("hide", "Home"), ("li", "one"), ("p", "two"), ("li", "three"), ("li", "four"), ("pre", "a b"), ("h2", "End")], d
    assert [bt[s:e] for s, e in d["code"]] == ["account/rateLimits/read"], d
    print("ok")
