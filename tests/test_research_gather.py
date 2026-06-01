"""Task 063 — Research Hub Gather. Embedded Postgres, network stubbed.

Verifies multi-URL gathering into research_sources (dedup by content hash),
the master gate, the admin tool + route, and that the real SSRF guard rejects a
private URL.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _fake_fetch(pages):
    """Return a fetch_url stub serving canned pages by url."""
    def _f(url, disallowed_domains=None):
        if url in pages:
            return {"ok": True, "body": pages[url], "content_type": "text/html",
                    "final_url": url}
        return {"ok": False, "error": "not found"}
    return _f


def _enable():
    app.set_ai_setting("research_hub_enabled", True)
    app._invalidate_ai_control()


def _reset():
    for k in ("research_hub_enabled", "research_max_sources", "ai_enhancements_enabled"):
        app.reset_ai_setting(k)
    app._invalidate_ai_control()


def _wipe():
    app.execute_db("DELETE FROM research_sources WHERE tenant_id=1")
    app.execute_db("DELETE FROM research_reports WHERE tenant_id=1")


# ---- single-url fetch + extract --------------------------------------------

def test_gather_url_extracts_title_and_text(monkeypatch):
    monkeypatch.setattr(app.scraper, "fetch_url",
                        _fake_fetch({"https://a.com": "<title>Page A</title><p>Hello world body</p>"}))
    monkeypatch.setattr(app, "_scrape_get_render_enabled", lambda: False)
    r = app._rce_gather_url("https://a.com", disallowed=[])
    assert r["ok"] is True and r["title"] == "Page A"
    assert "Hello world" in r["text"]


def test_gather_url_ssrf_rejects_private():
    # No stub — the real scraper.fetch_url must reject a loopback/private host.
    r = app._rce_gather_url("http://127.0.0.1:5432/", disallowed=[])
    assert r["ok"] is False


# ---- multi-url gather + dedup ----------------------------------------------

def test_gather_writes_sources_and_dedups(monkeypatch):
    _wipe(); _enable()
    monkeypatch.setattr(app.scraper, "fetch_url", _fake_fetch({
        "https://a.com": "<title>A</title><p>unique alpha text</p>",
        "https://b.com": "<title>B</title><p>unique beta text</p>",
        "https://dup.com": "<title>A</title><p>unique alpha text</p>",  # same text as a.com
    }))
    monkeypatch.setattr(app, "_scrape_get_render_enabled", lambda: False)
    try:
        rid = app.execute_db("INSERT INTO research_reports (tenant_id, topic, status) "
                             "VALUES (1,'t','draft') RETURNING id")["id"]
        summary = app._rce_gather(["https://a.com", "https://b.com", "https://dup.com"],
                                  report_id=rid)
        assert summary["gathered"] == 2 and summary["skipped"] == 1
        n = app.query_db("SELECT COUNT(*) AS n FROM research_sources WHERE report_id=%s",
                         (rid,), fetchone=True)["n"]
        assert n == 2
    finally:
        _wipe(); _reset()


def test_gather_respects_max_sources(monkeypatch):
    _wipe()
    app.set_ai_setting("research_hub_enabled", True)
    app.set_ai_setting("research_max_sources", 1)
    app._invalidate_ai_control()
    monkeypatch.setattr(app.scraper, "fetch_url", _fake_fetch({
        "https://a.com": "<p>aaa</p>", "https://b.com": "<p>bbb</p>"}))
    monkeypatch.setattr(app, "_scrape_get_render_enabled", lambda: False)
    try:
        rid = app.execute_db("INSERT INTO research_reports (tenant_id, topic, status) "
                             "VALUES (1,'t','draft') RETURNING id")["id"]
        summary = app._rce_gather(["https://a.com", "https://b.com"], report_id=rid)
        assert summary["gathered"] == 1   # capped at research_max_sources=1
    finally:
        _wipe(); _reset()


# ---- gate -------------------------------------------------------------------

def test_gather_into_report_gated():
    _reset()  # hub off by default
    assert "error" in app._rce_gather_into_report(["https://a.com"], topic="x")


def test_master_switch_disables(monkeypatch):
    _wipe()
    app.set_ai_setting("research_hub_enabled", True)
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    try:
        assert "error" in app._rce_gather_into_report(["https://a.com"])
    finally:
        _reset()


# ---- tool + route -----------------------------------------------------------

def test_gather_tool_and_route(monkeypatch):
    _wipe(); _enable()
    monkeypatch.setattr(app.scraper, "fetch_url", _fake_fetch({
        "https://a.com": "<title>A</title><p>alpha</p>"}))
    monkeypatch.setattr(app, "_scrape_get_render_enabled", lambda: False)
    try:
        out = app._admin_tool_gather_sources(urls=["https://a.com"], topic="Tool test")
        assert out.get("gathered") == 1 and out.get("report_id")
        c = app.app.test_client()
        c.post("/admin/login", data={"password": ADMIN_PW})
        with c.session_transaction() as s:
            s["_csrf_token"] = "t"
        r = c.post("/admin/api/research/gather",
                   json={"urls": ["https://a.com"], "topic": "Route test"},
                   headers={"X-CSRF-Token": "t"})
        assert r.status_code == 200 and r.get_json().get("report_id")
        # Missing urls → 400.
        assert c.post("/admin/api/research/gather", json={},
                      headers={"X-CSRF-Token": "t"}).status_code == 400
    finally:
        _wipe(); _reset()


def test_gather_route_client_blocked():
    if not CLIENT_PW:
        return
    c = app.app.test_client()
    c.post("/admin/login", data={"password": CLIENT_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    assert c.post("/admin/api/research/gather", json={"urls": ["https://a.com"]},
                  headers={"X-CSRF-Token": "t"}).status_code == 403


def test_tool_registered():
    assert "gather_sources" in app.ADMIN_TOOL_FUNCTIONS
    names = {t["function"]["name"] for t in app.ADMIN_TOOLS}
    assert "gather_sources" in names
