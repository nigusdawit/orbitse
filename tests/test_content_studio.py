"""Task 065 — Content Studio (text). Embedded Postgres; LLM stubbed (no spend).

Covers: content-type registry (+ unknown fallback), report→drafts generation
(review-gated status='draft'), the content_studio gate + master switch, the
no-summary guard, the tool + routes (types, generate, get-one, review update),
and client-403s.
"""
import json
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


class _Msg:
    def __init__(self, c):
        self.content = c


class _Choice:
    def __init__(self, c):
        self.message = _Msg(c)


class _Resp:
    def __init__(self, c):
        self.choices = [_Choice(c)]
        self.usage = None


class _Completions:
    def create(self, **kw):
        return _Resp(json.dumps({"title": "Generated Title",
                                 "body": "Generated body about the topic."}))


class _Chat:
    completions = _Completions()


class _FakeOpenAI:
    chat = _Chat()

    def with_options(self, **kw):
        return self


def _enable(monkeypatch=None):
    app.set_ai_setting("content_studio_enabled", True)
    app._invalidate_ai_control()
    if monkeypatch is not None:
        monkeypatch.setattr(app, "openai_client", _FakeOpenAI())


def _reset():
    for k in ("content_studio_enabled", "content_model", "ai_enhancements_enabled"):
        app.reset_ai_setting(k)
    app._invalidate_ai_control()


def _wipe():
    app.execute_db("DELETE FROM content_drafts WHERE tenant_id=1")
    app.execute_db("DELETE FROM research_reports WHERE tenant_id=1")


def _seed_report(summary="A real synthesized summary."):
    return app.execute_db(
        "INSERT INTO research_reports (tenant_id, topic, question, summary, "
        "key_points, citations, status) VALUES (1,'Topic T','What is T?',%s,"
        "'[\"key point one\"]'::jsonb,'[{\"title\":\"A\",\"url\":\"https://a.com\"}]'::jsonb,"
        "'ready') RETURNING id", (summary,))["id"]


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    return c


# ---- content-type registry --------------------------------------------------

def test_content_type_spec_known_and_fallback():
    k, spec = app._rce_content_type_spec("blog")
    assert k == "blog" and spec["label"] == "Blog post"
    k2, spec2 = app._rce_content_type_spec("Weird_Custom")
    assert k2 == "weird_custom" and "instruction" in spec2 and spec2["max_tokens"] > 0


# ---- generation -------------------------------------------------------------

def test_generate_creates_review_gated_drafts(monkeypatch):
    _wipe(); _enable(monkeypatch)
    try:
        rid = _seed_report()
        out = app._rce_generate_from_report(rid, ["blog", "social"])
        assert out.get("errors") == 0 and len(out["drafts"]) == 2
        rows = app.query_db("SELECT content_type, status, title, body FROM content_drafts "
                            "WHERE source_report_id=%s ORDER BY id", (rid,))
        assert {r["content_type"] for r in rows} == {"blog", "social"}
        assert all(r["status"] == "draft" for r in rows)        # review-gated
        assert all(r["title"] and r["body"] for r in rows)
    finally:
        _wipe(); _reset()


def test_generate_gated_off():
    _reset()  # content studio off
    assert "error" in app._rce_generate_from_report(1, ["blog"])


def test_generate_master_switch(monkeypatch):
    app.set_ai_setting("content_studio_enabled", True)
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    monkeypatch.setattr(app, "openai_client", _FakeOpenAI())
    try:
        assert "error" in app._rce_generate_from_report(1, ["blog"])
    finally:
        _reset()


def test_generate_requires_summary(monkeypatch):
    _wipe(); _enable(monkeypatch)
    try:
        rid = _seed_report(summary="")   # no synthesis yet
        assert "error" in app._rce_generate_from_report(rid, ["blog"])
    finally:
        _wipe(); _reset()


def test_generate_requires_types(monkeypatch):
    _wipe(); _enable(monkeypatch)
    try:
        rid = _seed_report()
        assert "error" in app._rce_generate_from_report(rid, [])
    finally:
        _wipe(); _reset()


# ---- routes -----------------------------------------------------------------

def test_types_route():
    c = _sa()
    types = c.get("/admin/api/content/types").get_json()["types"]
    assert any(t["key"] == "blog" for t in types)


def test_generate_and_review_routes(monkeypatch):
    _wipe(); _enable(monkeypatch)
    try:
        rid = _seed_report()
        c = _sa()
        r = c.post("/admin/api/content/generate",
                   json={"report_id": rid, "content_types": ["blog"]},
                   headers={"X-CSRF-Token": "t"})
        assert r.status_code == 200
        did = r.get_json()["drafts"][0]["draft_id"]
        # get one (with body)
        one = c.get(f"/admin/api/content/drafts/{did}").get_json()
        assert one["body"] and one["status"] == "draft"
        # review: approve + edit body
        upd = c.post(f"/admin/api/content/drafts/{did}",
                     json={"status": "approved", "body": "edited body"},
                     headers={"X-CSRF-Token": "t"}).get_json()
        assert upd["status"] == "approved" and upd["body"] == "edited body"
        # invalid status → 400
        assert c.post(f"/admin/api/content/drafts/{did}", json={"status": "bogus"},
                      headers={"X-CSRF-Token": "t"}).status_code == 400
        # missing fields on generate → 400
        assert c.post("/admin/api/content/generate", json={"report_id": rid},
                      headers={"X-CSRF-Token": "t"}).status_code == 400
        # unknown draft → 404
        assert c.get("/admin/api/content/drafts/999999").status_code == 404
    finally:
        _wipe(); _reset()


def test_routes_client_blocked():
    if not CLIENT_PW:
        return
    c = app.app.test_client()
    c.post("/admin/login", data={"password": CLIENT_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    assert c.get("/admin/api/content/types").status_code == 403
    assert c.post("/admin/api/content/generate", json={"report_id": 1,
                  "content_types": ["blog"]}, headers={"X-CSRF-Token": "t"}).status_code == 403
    assert c.get("/admin/api/content/drafts/1").status_code == 403


def test_tool_registered():
    assert "generate_content" in app.ADMIN_TOOL_FUNCTIONS
    names = {t["function"]["name"] for t in app.ADMIN_TOOLS}
    assert "generate_content" in names
