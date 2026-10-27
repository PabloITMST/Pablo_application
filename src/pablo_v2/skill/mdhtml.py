"""A13 the report as one self-contained HTML page: the report's Markdown converted (headings, lists, tables, paragraphs,
**bold**, `code`, bare links), with the app's fonts (by family name, no files) and colours inline. Only the Markdown
render_report writes; not a general converter. Text is escaped before any tag is made."""
from __future__ import annotations

import re
from html import escape

CSS = """:root { --canvas:#E3E7EB; --surface:#F3F5F7; --raised:#D3D9DF; --ink:#0D0E10; --ink-2:#4A515C; --ink-3:#8A929D;
  --signal:#FF4D00; --signal-soft:#FFE1D2; --line:rgba(13,14,16,.08);
  --sans:"Geist", "Pretendard", system-ui, "Segoe UI", "Malgun Gothic", sans-serif;
  --mono:"Geist Mono", "Pretendard", ui-monospace, Consolas, monospace; }
* { box-sizing:border-box; }
body { margin:0; background:var(--canvas); color:var(--ink); font:15px/1.65 var(--sans); }
main { max-width:880px; margin:24px auto; padding:32px 40px; background:var(--surface); border:1px solid var(--line);
  border-radius:14px; box-shadow:0 1px 2px rgba(13,14,16,.06); }
h1 { font-size:24px; line-height:1.3; margin:0 0 12px; }
h2 { font-size:18px; margin:32px 0 8px; padding-top:16px; border-top:1px solid var(--line); }
h3 { font-size:15px; margin:20px 0 6px; color:var(--ink-2); }
p { margin:8px 0; }
ul { margin:8px 0; padding-left:22px; }
li { margin:3px 0; }
code { font-family:var(--mono); font-size:13px; background:var(--raised); border-radius:4px; padding:1px 4px; }
a { color:var(--ink); text-decoration-color:var(--signal); }
.scroll { overflow-x:auto; margin:12px 0; }
table { border-collapse:collapse; width:100%; font-size:13px; }
th, td { border:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }
th { background:rgba(13,14,16,.04); font-weight:600; }
@media print { body { background:#fff; } main { border:0; box-shadow:none; margin:0; max-width:none; } }"""


def inline(text: str) -> str:
    """`code` first (nothing inside it is read), then **bold** and bare http(s) links in the rest."""
    out = []
    for i, part in enumerate(re.split(r"`([^`]*)`", text)):
        if i % 2:
            out.append(f"<code>{escape(part)}</code>")
            continue
        s = escape(part)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(https?://[^\s<>&\"')]+[^\s<>&\"').,;:])", r'<a href="\1">\1</a>', s)
        out.append(s)
    return "".join(out)


def _cells(line: str) -> list[str]:
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", body)]


def to_html(md: str) -> str:
    """Markdown (as render_report writes it) -> HTML body."""
    lines, out, i = md.splitlines(), [], 0
    para: list[str] = []

    def flush():
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()
    while i < len(lines):
        ln = lines[i]
        m = re.match(r"^(#{1,3}) (.*)$", ln)
        if m:
            flush()
            n = len(m[1])
            out.append(f"<h{n}>{inline(m[2])}</h{n}>")
        elif ln.startswith("- "):
            flush()
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{inline(lines[i][2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|(\s*:?-+:?\s*\|)+\s*$", lines[i + 1]):
            flush()
            head = "".join(f"<th>{inline(c)}</th>" for c in _cells(ln))
            i += 2
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in _cells(lines[i])) + "</tr>")
                i += 1
            out.append(f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
            continue
        elif not ln.strip():
            flush()
        else:
            para.append(ln.strip())
        i += 1
    flush()
    return "\n".join(out)


def page(md: str, title: str) -> str:
    """One file the reader opens anywhere: no scripts, no outside files."""
    return (f'<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>{escape(title)}</title>\n'
            f"<style>\n{CSS}\n</style>\n</head>\n<body>\n<main>\n{to_html(md)}\n</main>\n</body>\n</html>\n")
