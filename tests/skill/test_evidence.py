"""M3.1 evidence anchor tests. Run: python tests/skill/test_evidence.py
Offline pages simulate source changes. PABLO_NET=1 adds the live Codex app-server docs.
"""
import json
import os
import sys
import tempfile
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from pablo_v2.intent.engine import IntentEngine  # noqa: E402
from pablo_v2.skill.evidence import AnchorRejected  # noqa: E402
from pablo_v2.skill.skill import PabloSkill, render_evidence, render_task  # noqa: E402
from pablo_v2.skill.viewer import render_html  # noqa: E402

URL = "https://learn.chatgpt.com/docs/app-server"
LINE = "<li><code>account/rateLimits/read</code> - fetch ChatGPT rate limits.</li>"
PAGE = ("<html><head><title>Codex App Server</title><script>var build='a1'</script></head><body><ul>"
        "<li><code>account/logout</code> - sign out.</li>" + LINE +
        "</ul><pre>{\"method\": \"account/rateLimits/read\", \"id\": 6}</pre></body></html>")


class Web:
    def __init__(self, page):
        self.page = page

    def __call__(self, url):
        if self.page is None:
            raise urllib.error.URLError("offline")
        return self.page


def rejected(fn, *args):
    try:
        fn(*args)
    except AnchorRejected:
        return True
    return False


def skill(path=None, web=None):
    s = PabloSkill(IntentEngine(), path=path)
    s.fetch = web or Web(PAGE)
    return s


def test_anchor_core():
    path = os.path.join(tempfile.mkdtemp(), "skill.json")
    web = Web(PAGE)
    s = skill(path, web)
    src = s.capture_source(URL)
    assert src.title == "Codex App Server" and src.version["content_hash"].startswith("sha256:")
    assert "build=" not in s.snapshot_text(src)  # scripts are not evidence text
    web.page = PAGE.replace("'a1'", "'b2'")  # build noise only -> same visible text -> same version
    assert s.capture_source(URL).id == src.id

    # quote must exist, and be unambiguous
    assert rejected(s.add_anchor, src.id, "account/rateLimits/write")
    assert rejected(s.add_anchor, src.id, "account/rateLimits/read")
    assert rejected(s.add_anchor, src.id, "account/rateLimits/read", "no such context")
    e = s.add_anchor(src.id, "account/rateLimits/read", "fetch ChatGPT rate limits")
    assert e.quote["suffix"].startswith(" - fetch ChatGPT rate limits"), e.quote

    t = s.start_task("rate limit 표시", [{"requirement": "rateLimits 읽는 공식 메서드", "necessity": "REQUIRED",
                                          "why_blocking": "API 선택이 바뀜"}])
    sc = s.checks(t.id)[0].id
    link = s.link_evidence(e.id, sc, "supports")
    assert s.link_evidence(e.id, sc, "supports").id == link.id  # no duplicate links
    for bad in [(e.id, "SC99", "supports"), (e.id, sc, "proves"), ("E99", sc, "supports")]:
        try:
            s.link_evidence(*bad)
            raise AssertionError(f"accepted {bad}")
        except (KeyError, ValueError):
            pass

    # validity against the live source
    web.page = PAGE
    assert s.resolve_anchor(e.id).status == "VALID" and e.resolution["hash_changed"] is False
    web.page = PAGE.replace("<ul>", "<p>New intro paragraph.</p><ul>")
    r = s.resolve_anchor(e.id).resolution
    assert (e.status, r["reason"], r["start"]) == ("VALID", "relocated", e.selector["start"] + len("New intro paragraph. ")), r
    web.page = PAGE.replace(LINE, "<li><code>account/rateLimits/read</code> - deprecated.</li>")
    assert s.resolve_anchor(e.id).status == "STALE" and e.resolution["reason"] == "context_changed"
    web.page = PAGE.replace("account/rateLimits/read", "account/usage/read")
    assert s.resolve_anchor(e.id).status == "UNRESOLVED" and e.resolution["reason"] == "not_found"
    web.page = None
    assert s.resolve_anchor(e.id).status == "UNRESOLVED" and e.resolution["reason"] == "fetch_failed"
    assert e.selector == {"type": "web_text", "start": e.selector["start"], "end": e.selector["end"]}  # never moved

    # a changed page is a new source version; the old one and its anchor stay
    web.page = PAGE.replace("sign out", "log out")
    assert s.capture_source(URL).id != src.id and len(s.state.sources) == 2

    # persistence: anchor, link and snapshot survive a reload
    s2 = PabloSkill.load(path, IntentEngine())
    s2.fetch = Web(PAGE)
    assert s2.resolve_anchor(e.id).status == "VALID"
    assert [x.target_id for x, _ in s2.evidence_for(sc)] == [sc]
    assert f"evidence supports [{e.id} VALID]" in render_task(s2, t.id)
    print(render_evidence(s2, e.id))


def test_viewer():
    web = Web(PAGE.replace("sign out", "sign out &lt;/script&gt;"))  # page text that would close a <script>
    s = skill(web=web)
    s.intent.process_message("Host Integration을 구현해줘")  # G1: an earlier task's goal (scope task, said before T1)
    s.intent.process_message("새 프레임워크는 도입하지 마")  # C1: project scope, applies to every task
    s.intent.state.candidates[0].features["scope"] = "task"
    s.intent.get_item("G1").created_at = "2000-01-01T00:00:00+00:00"
    src = s.capture_source(URL)
    e = s.add_anchor(src.id, "account/rateLimits/read", "fetch ChatGPT rate limits")
    t = s.start_task("rate limit", [{"requirement": "rateLimits", "necessity": "REQUIRED", "why_blocking": "API"}])
    sc = s.checks(t.id)[0].id
    s.link_evidence(e.id, sc, "supports")
    web.page = None
    s.resolve_anchor(e.id)  # UNRESOLVED fetch_failed: the snapshot evidence must still be shown
    page = render_html(s, t.id)
    data = page.split('id="data">', 1)[1].split("</script>", 1)[0]
    assert "</script>" not in data
    d = json.loads(data)
    a, snap = d["anchors"][e.id], d["sources"][src.id]
    assert snap["intact"] and snap["text"][a["start"]:a["end"]] == a["exact"] == "account/rateLimits/read"
    assert a["status"] == "UNRESOLVED" and "가져오지 못했습니다" in a["message"]
    v = d["views"][t.id]  # every task of the state is in the page; the conversation cites the anchor ids
    assert d["current"] == t.id and [x["id"] for x in d["tasks"]] == [t.id]
    assert v["research"] == [sc] and v["checks"][sc]["evidence"] == [e.id] and a["check"] == sc
    assert v["stage"] == "Research" and v["plan"] is None and v["actions"] == []
    i = v["intent"]  # the current-task view shows only intent that applies to this task; G1 is kept, not shown
    assert [x["text"] for x in i["goals"]] == ["rate limit"] and [x["id"] for x in i["must"]] == ["C1"]
    assert i["other"] == ["G1"] and s.intent.get_item("G1").status == "active"
    # the judge / Guard get the same scope (skill.task_intent), not every active item
    assert "G1" not in s._intent_text(t.id) and "C1" in s._intent_text(t.id) and "[task goal] rate limit" in s._intent_text(t.id)
    assert s.get_applicable_intent(t.id)["other"] == i["other"]  # viewer and judge read one resolver
    s.intent.get_item("G1").created_at = t.created_at  # task scope said during this task -> applies
    assert "G1" in s._intent_text(t.id)
    s.intent.get_item("G1").created_at = "2000-01-01T00:00:00+00:00"
    s.intent.state.candidates[1].features["scope"] = "action"  # action scope: said during this task -> applies
    s.intent.get_item("C1").created_at = t.created_at
    assert "C1" in s._intent_text(t.id)
    s.intent.state.candidates[1].features["scope"] = "project"
    s.checks(t.id)[0].intent_refs = ["G1"]  # explicitly referenced by this task -> applies despite scope
    assert "G1" in s._intent_text(t.id)
    s.checks(t.id)[0].intent_refs = []
    s.checks(t.id)[0].research_state = "completed"
    p = s.create_plan(t.id, [{"action": "x", "basis": ["G1"]}])  # referenced by the current Plan -> applies
    assert "G1" in s._intent_text(t.id)
    p.status = "superseded"
    assert "G1" not in s._intent_text(t.id)
    disp = snap["display"]  # presentation only, same canonical offsets as the anchor
    li = [b for b in disp["blocks"] if b[1] <= a["start"] and a["end"] <= b[2]]
    assert li and li[0][0] == "li" and snap["text"][li[0][1]:li[0][2]].startswith("account/rateLimits/read - fetch")
    assert [a["start"], a["end"]] in disp["code"]
    s._snapshots[src.snapshot] =snap["text"].replace("sign", "SIGN")  # tampered snapshot -> no highlight
    assert json.loads(render_html(s, t.id).split('id="data">', 1)[1].split("</script>", 1)[0])["sources"][src.id]["intact"] is False


def test_live_app_server():
    if os.environ.get("PABLO_NET") != "1":
        return
    s = PabloSkill(IntentEngine(), path=os.path.join(tempfile.mkdtemp(), "skill.json"))
    src = s.capture_source(URL)
    assert s.capture_source(URL).id == src.id, "content hash not stable between two fetches"
    assert rejected(s.add_anchor, src.id, "account/rateLimits/read")
    e = s.add_anchor(src.id, "account/rateLimits/read", "fetch ChatGPT rate limits")
    assert s.resolve_anchor(e.id).status == "VALID" and e.resolution["start"] == e.selector["start"]
    print(render_evidence(s, e.id))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
