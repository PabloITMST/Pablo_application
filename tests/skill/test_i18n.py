"""0.11 English mode: every Korean string the screen can show has an English entry in skill/en.py.

The page translates text by its Korean source (viewer.py tr()): exact keys, and keys whose {0} {1} stand for what the
code interpolates there (JS ${...}, Python f-string {...}). This collects the keys from the code the screen shows: the page
(viewer.py PAGE and its model), the desktop's errors and card reasons, the Guard's own reasons, the intent engine's
notes and skill.py's errors. The report export, the CLI and the prompts stay Korean, so they are not collected.

  python tests/skill/test_i18n.py            check
  python tests/skill/test_i18n.py --missing  the keys en.py lacks, as JSON (a translation worklist)
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
from pablo_v2.skill.en import EN  # noqa: E402

HANGUL = re.compile(r"[가-힣]")
PH = re.compile(r"\{(\d)\}")
REPORT = {"REPORT_KIND", "VERDICT", "CHECKED", "_day", "_when", "_span", "REPORT_SECTIONS", "render_report",
          "report_counts", "_report", "_said_plainly", "PAGE"}
JS = ["desktop/main.js", "desktop/controller.js", "desktop/agent.js", "desktop/siwc.js", "desktop/where.js", "desktop/papers.js"]


def _unescape(s: str) -> str:
    return re.sub(r"\\(u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", lambda m: (
        chr(int(m[1].strip("u{}x"), 16)) if m[1][0] in "ux" and len(m[1]) > 1 else {"n": "\n", "t": "\t"}.get(m[1], m[1])), s)


def js_strings(src: str) -> list[str]:
    """String and template literals of JS source (comments and regex literals skipped); ${...} -> {0}, {1}, ...
    Literals joined by + ("a " + `b ${x}`) are one string on screen, so one key."""
    out, n = [], len(src)

    def literal(i):  # src[i] is the opening quote or backtick -> (text, holes, end)
        q, buf, k, i = src[i], [], 0, i + 1
        while src[i] != q:
            if src[i] == "\\":
                buf.append(src[i:i + 2]); i += 2
            elif q == "`" and src.startswith("${", i):
                buf.append("{%d}" % k); k += 1; i = code(i + 2, True)
            else:
                buf.append(src[i]); i += 1
        return _unescape("".join(buf)), k, i + 1

    def joined(i):  # a literal and the literals added to it
        text, k, i = literal(i)
        while True:
            j = i
            while j < n and src[j].isspace():
                j += 1
            if not (src.startswith("+", j) and not src.startswith("++", j)):
                return text, i
            j += 1
            while j < n and src[j].isspace():
                j += 1
            if j >= n or src[j] not in "\"'`":
                return text, i
            more, m, i = literal(j)
            text += PH.sub(lambda x: "{%d}" % (int(x[1]) + k), more); k += m

    def code(i, inner=False):
        depth, prev = 0, "("
        while i < n:
            c = src[i]
            if c.isspace():
                i += 1
            elif src.startswith("//", i):
                j = src.find("\n", i); i = n if j < 0 else j
            elif src.startswith("/*", i):
                i = src.index("*/", i) + 2
            elif c in "\"'`":
                text, i = joined(i); out.append(text); prev = "a"
            elif c == "/" and prev in "(,=:[!&|?{};+-*%<>~^r":  # a regex literal (r: after return / typeof / case)
                j, cls = i + 1, False
                while cls or src[j] != "/":
                    cls = (cls or src[j] == "[") and src[j] != "]"
                    j += 2 if src[j] == "\\" else 1
                i, prev = j + 1, "a"
            elif c.isalnum() or c in "_$":
                j = i
                while j < n and (src[j].isalnum() or src[j] in "_$"):
                    j += 1
                prev = "r" if src[i:j] in ("return", "typeof", "case", "else", "in", "of") else "a"; i = j
            else:
                if c == "{":
                    depth += 1
                elif c == "}":
                    if inner and depth == 0:
                        return i + 1
                    depth -= 1
                prev = "a" if c in ")]" else c; i += 1
        return i

    code(0)
    return out


def py_strings(tree, keep=lambda node: True) -> list[str]:
    """Python string constants and f-strings ({x} -> {0}, ...), without docstrings, under the top-level nodes kept."""
    out = []

    def visit(node):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            return  # a docstring
        if isinstance(node, ast.JoinedStr):
            k = 0; parts = []
            for v in node.values:
                if isinstance(v, ast.FormattedValue):
                    parts.append("{%d}" % k); k += 1; visit(v.value)
                else:
                    parts.append(v.value)
            out.append("".join(parts)); return
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value); return
        for child in ast.iter_child_nodes(node):
            visit(child)

    for node in tree.body:
        if keep(node):
            visit(node)
    return out


def _name(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    return None


def _raises(tree) -> list[str]:
    return [s for node in ast.walk(tree) if isinstance(node, ast.Raise) and node.exc is not None
            for s in py_strings(ast.Module(body=[ast.Return(value=node.exc)], type_ignores=[]))]


def read(p):
    with open(os.path.join(ROOT, p), encoding="utf-8") as f:
        return f.read()


def keys() -> dict[str, str]:
    """{key: where it was found}"""
    found = {}

    def add(strings, where):
        for s in strings:
            s = s.strip(" \t\r\n·")  # as tr() looks it up: the separators at its ends are not words
            if HANGUL.search(s):
                found.setdefault(s, where)

    viewer = read("src/pablo_v2/skill/viewer.py")
    page = viewer[viewer.index('PAGE = r"""'):]
    a, b = page.index("<script>\n" if "<script>\n" in page else "<script>\r\n"), page.rindex("</script>")
    add(js_strings(page[a + len("<script>"):b]), "viewer.py PAGE script")
    html = page[page.index("</style>"):a]
    add(re.findall(r">([^<>{}]*[가-힣][^<>{}]*)<", html), "viewer.py PAGE html")
    add(re.findall(r'(?:title|placeholder|aria-label|alt)="([^"]*[가-힣][^"]*)"', html), "viewer.py PAGE html")
    add(py_strings(ast.parse(viewer), lambda node: _name(node) not in REPORT), "viewer.py model")
    add(py_strings(ast.parse(read("src/pablo_v2/skill/guard.py"))), "guard.py")
    add(py_strings(ast.parse(read("src/pablo_v2/intent/engine.py"))), "intent/engine.py")
    sk = ast.parse(read("src/pablo_v2/skill/skill.py"))
    add(_raises(sk) + py_strings(sk, lambda node: _name(node) == "NO_PAPER_ANSWER"), "skill.py raise")
    for p in JS:
        add(js_strings(read(p)), p)
    return found


def main():
    found = keys()
    missing = {k: w for k, w in found.items() if k not in EN}
    if "--missing" in sys.argv:
        print(json.dumps(missing, ensure_ascii=False, indent=1)); return
    bad = [k for k, v in EN.items() if sorted(PH.findall(k)) != sorted(PH.findall(v))]
    assert not bad, f"placeholders differ between key and English: {bad[:5]}"
    assert all(not HANGUL.search(v) for v in EN.values()), [v for v in EN.values() if HANGUL.search(v)][:5]
    # the lexer itself: comments and regex literals are not strings; templates number their holes
    # CSS writes some words itself (content:"막음"): each such rule has an English twin under html[lang=en]
    page = read("src/pablo_v2/skill/viewer.py"); css = page[page.index("<style>"):page.index("</style>")]
    words = {m[1].split(",")[-1].strip() for m in re.finditer(r'([^{}]+)\{[^{}]*content:\s*"[^"]*[가-힣][^"]*"', css)}
    alone = sorted(s for s in words if not s.startswith("html[lang=en]") and "html[lang=en] " + s not in css)
    assert not alone, f"CSS words with no English: {alone}"
    got = js_strings('// "주석"\nconst a = /"[가-힣]"/.test(x) ? `인용 ${n}개 ${m ? `안 ${k}` : ""}` : \'끝\';')
    assert got == ["안 {0}", "", "인용 {0}개 {1}", "끝"], got
    got = js_strings('h("p", null, "가나 " +\n  `다 ${x}` + "라", a + "마", "바" + y);')
    assert got == ["p", "가나 다 {0}라", "마", "바"], got
    # what Pablo writes for the person follows the desktop's language: the prompts ask for English (every example
    # swapped too: renaming one in a prompt fails here), and a new reproduction task starts with English criteria
    from pablo_v2.skill import judge, skill
    prompts = [getattr(judge, n) for n in ("SPEC_PROMPT", "SPEC_APPENDIX_PROMPT", "COMPARE_PROMPT", "SUMMARY_PROMPT",
                                           "DRIFT_PROMPT", "CRITERIA_CHANGE_PROMPT", "ASK_PROMPT", "ASK_SOURCES_PROMPT")]
    assert all(any(ko in p for p in prompts) for ko, _ in judge.EN_PROMPT), "an EN_PROMPT example no prompt has"
    was = os.environ.get("PABLO_LANG")
    try:
        os.environ["PABLO_LANG"] = "en"
        assert all(not any(ko in judge.lang(p) for ko, _ in judge.EN_PROMPT) for p in prompts)
        assert skill.repro_criteria() == skill.REPRO_CRITERIA_EN and skill.english()
        assert skill.setting_name("The chunk size is not stated in the paper.") == "The chunk size"
    finally:
        os.environ.pop("PABLO_LANG") if was is None else os.environ.update(PABLO_LANG=was)
    assert skill.repro_criteria() == skill.REPRO_CRITERIA if was != "en" else True
    assert not missing, f"{len(missing)} Korean strings without English (run with --missing): {list(missing)[:8]}"
    stale = [k for k in EN if k not in found]
    assert not stale, f"en.py keys no code shows any more: {stale[:8]}"
    print(f"i18n: {len(found)} keys, all in en.py")


if __name__ == "__main__":
    main()
