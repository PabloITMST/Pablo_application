"""PDF evidence (M3.3): the same anchor model as web evidence (M3.1), on a captured PDF file. Deterministic only.

  pages(data) -> [page text]     pypdf text per page, whitespace collapsed; offsets are per page
  locate(pages, exact, page)     -> (page, start, end); refuses missing or ambiguous quotes
  resolve(quote, selector, old_hash, data) -> {status VALID | STALE | UNRESOLVED, reason, ...}

Text extractors disagree on spaces ("over77%") and on line-end hyphens ("exist-ing"), so quotes are matched on a
key that drops whitespace and hyphens (NFKC, so ligatures match too). The desktop PDF panel (pdf.js) uses the
same key on its own text items, so a quote found here is found there.
Version = sha256 of the PDF bytes. Relevance (does the quote support the claim) is not decided here.
"""
from __future__ import annotations

import hashlib
import io
import re
import unicodedata

from .evidence import AnchorRejected, context

DROP = set("-­‐‑")  # hyphens, plus every whitespace char (str.isspace)
PYPDF = "6.19.0"  # pinned in requirements.txt


def content_hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def pages(data: bytes) -> list[str]:
    import pypdf  # M3.3 dependency; web evidence does not need it
    if pypdf.__version__ != PYPDF:  # page text (and so every pdf offset) depends on the pypdf version
        raise RuntimeError(f"pypdf {PYPDF} required, found {pypdf.__version__}: pip install -r requirements.txt")
    from pypdf import PdfReader
    return [re.sub(r"\s+", " ", p.extract_text() or "").strip() for p in PdfReader(io.BytesIO(data)).pages]


def key(text: str) -> tuple[str, list[int]]:
    """-> (key, idx): key[i] comes from text[idx[i]]."""
    out, idx = [], []
    for i, ch in enumerate(text):
        if ch.isspace() or ch in DROP:
            continue
        for c in unicodedata.normalize("NFKC", ch):
            out.append(c), idx.append(i)
    return "".join(out), idx


def _hits(text: str, k: str) -> list[tuple[int, int]]:
    tk, idx = key(text)
    out, i = [], tk.find(k)
    while i >= 0:
        out.append((idx[i], idx[i + len(k) - 1] + 1))
        i = tk.find(k, i + 1)
    return out


def locate(ps: list[str], exact: str, page: int | None = None) -> tuple[int, int, int]:
    k = key(exact)[0]
    if not k:
        raise AnchorRejected("empty quote")
    if page is not None and not 1 <= page <= len(ps):
        raise AnchorRejected(f"page {page} is not in this PDF (1-{len(ps)})")
    hits = [(n, s, e) for n, t in enumerate(ps, 1) if page in (None, n) for s, e in _hits(t, k)]
    if not hits:
        raise AnchorRejected(f"quote not found in the captured PDF{f' page {page}' if page else ''}: {exact!r}")
    if len(hits) > 1:
        where = sorted({n for n, _, _ in hits})
        raise AnchorRejected(f"quote appears {len(hits)} times (pages {where}); add --page or a longer quote")
    return hits[0]


def resolve(quote: dict, selector: dict, old_hash: str, data: bytes) -> dict:
    """Find the anchor in the current file at the source's path."""
    new_hash = content_hash(data)
    out = {"page": selector["page"], "start": selector["start"], "end": selector["end"], "content_hash": new_hash}
    if new_hash == old_hash:
        return {**out, "status": "VALID", "reason": None, "hash_changed": False}
    out = {**out, "hash_changed": True, "page": None, "start": None, "end": None}
    ps = pages(data)
    full = key(quote["prefix"] + quote["exact"] + quote["suffix"])[0]
    found = [(n, t) for n, t in enumerate(ps, 1) if full in key(t)[0]]
    if len(found) == 1:
        n, t = found[0]
        for s, e in _hits(t, key(quote["exact"])[0]):  # the one with the stored context around it
            if full in key(t[max(0, s - 3 * len(quote["prefix"]) - 8):e + 3 * len(quote["suffix"]) + 8])[0]:
                return {**out, "status": "VALID", "reason": "relocated", "page": n, "start": s, "end": e}
    if n := sum(len(_hits(t, key(quote["exact"])[0])) for t in ps):
        return {**out, "status": "STALE", "reason": "context_changed" if not found else "ambiguous", "occurrences": n}
    return {**out, "status": "UNRESOLVED", "reason": "not_found"}


def anchor(ps: list[str], exact: str, page: int | None = None) -> tuple[dict, dict]:
    """-> (quote {exact, prefix, suffix} from the page text, selector {type: pdf_text, page, start, end})."""
    n, s, e = locate(ps, exact, page)
    return context(ps[n - 1], s, e), {"type": "pdf_text", "page": n, "start": s, "end": e}


def offset(ps: list[str], page: int) -> int:
    """Where a page starts in the snapshot text ("\\f".join(pages))."""
    return sum(len(t) + 1 for t in ps[:page - 1])


if __name__ == "__main__":  # self-check, no PDF needed
    ps = ["Intro. We reduce indexing time by over77%. Next, exist- ing work.", "Table 2 LinearRAG (Ours) 249.78 0.093 0 0 66.95",
          "LinearRAG again."]
    q, sel = anchor(ps, "reduces indexing time by over 77%".replace("reduces", "reduce"))
    assert sel["page"] == 1 and q["exact"] == "reduce indexing time by over77%", q
    assert anchor(ps, "existing work")[0]["exact"] == "exist- ing work"
    assert anchor(ps, "LinearRAG (Ours) 249.78 0.093 0 0 66.95")[1]["page"] == 2
    for bad in ("not there", "LinearRAG"):
        try:
            anchor(ps, bad)
            raise AssertionError(bad)
        except AnchorRejected:
            pass
    assert anchor(ps, "LinearRAG", page=3)[1]["page"] == 3
    assert offset(ps, 2) == len(ps[0]) + 1 and "\f".join(ps)[offset(ps, 2):].startswith("Table 2")
    assert key("ﬁle­-name")[0] == "filename"
    print("ok")
