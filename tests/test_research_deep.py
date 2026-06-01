"""Task 064 — Deep Research. Embedded Postgres; web search, network, and the
LLM are all stubbed (no spend, no network).

Covers: sub-question planning fallback, web-search discovery, end-to-end run
(plan → fetch → cited synthesis) writing a ready report, the anti-hallucination
citation filter (a cited URL we never fetched is dropped), the master gate,
the no-key path, and the tool + route (happy path, 400, client-403).
"""
import json
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


# ---- fakes ------------------------------------------------------------------

def _fake_fetch(pages):
    def _f(url, disallowed_domains=None):
        if url in pages:
            return {"ok": True, "body": pages[url], "content_type": "text/html",
                    "final_url": url}
        return {"ok": False, "error": "not found"}
    return _f


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]
        self.usage = None


class _Completions:
    """Branch on the system prompt: planning vs synthesis."""
    def create(self, **kw):
        sysmsg = ""
        for m in kw.get("messages", []):
            if m.get("role") == "system":
                sysmsg = m.get("content", "")
        if "sub-question" in sysmsg:
            return _Resp(json.dumps({"subquestions": ["angle one", "angle two"]}))
        # synthesis — cite one real source + one hallucinated URL (must be dropped)
        return _Resp(json.dumps({
            "summary": "A synthesized answer grounded in the sources.",
            "key_points": ["finding one", "finding two", "finding three"],
            "citations": [{"title": "Page A", "url": "https://a.com"},
                          {"title": "Made up", "url": "https://hallucination.invalid"}],
        }))


class _Chat:
    completions = _Completions()


class _FakeOpenAI:
    chat = _Chat()

    def with_options(self, **kw):
        return self


def _fake_research_objective(_oc, _odc, objective):
    # Always surfaces the same two real sources we have stub pages for.
    return {"ok": True, "web_used": True, "note": "",
            "text": f"notes for {objective}",
            "sources": [{"title": "Page A", "url": "https://a.com"},
                        {"title": "Page B", "url": "https://b.com"}]}


def _patch_world(monkeypatch):
    monkeypatch.setattr(app, "openai_client", _FakeOpenAI())
    monkeypatch.setattr(app, "openai_direct_client", _FakeOpenAI())
    monkeypatch.setattr(app.scraper, "research_objective", _fake_research_objective)
    monkeypatch.setattr(app.scraper, "fetch_url", _fake_fetch({
        "https://a.com": "<title>Page A</title><p>alpha body content</p>",
        "https://b.com": "<title>Page B</title><p>beta body content</p>"}))
    monkeypatch.setattr(app, "_scrape_get_render_enabled", lambda: False)


def _enable():
    app.set_ai_setting("research_hub_enabled", True)
    app._invalidate_ai_control()


def _reset():
    for k in ("research_hub_enabled", "research_max_sources", "research_model",
              "ai_enhancements_enabled"):
        app.reset_ai_setting(k)
    app._invalidate_ai_control()


def _wipe():
    app.execute_db("DELETE FROM research_sources WHERE tenant_id=1")
    app.execute_db("DELETE FROM research_reports WHERE tenant_id=1")


# ---- planning ---------------------------------------------------------------

def test_plan_fallback_without_llm(monkeypatch):
    monkeypatch.setattr(app, "openai_client", None)
    assert app._rce_plan_subquestions("What is X?") == ["What is X?"]


def test_plan_with_llm(monkeypatch):
    _patch_world(monkeypatch)
    subs = app._rce_plan_subquestions("What is X?", max_q=4)
    assert subs[0] == "What is X?" and "angle one" in subs and len(subs) <= 4


# ---- discovery --------------------------------------------------------------

def test_discover_collects_urls(monkeypatch):
    _patch_world(monkeypatch)
    urls, notes = app._rce_discover_sources(["q1", "q2"], max_sources=8)
    assert set(urls) == {"https://a.com", "https://b.com"} and notes


# ---- citation hygiene (anti-hallucination) ---------------------------------

def test_clean_citations_drops_unfetched():
    srows = [{"url": "https://a.com", "title": "Page A"}]
    raw = [{"title": "Page A", "url": "https://a.com"},
           {"title": "Fake", "url": "https://nope.invalid"}]
    out = app._rce_clean_citations(raw, srows)
    assert out == [{"title": "Page A", "url": "https://a.com"}]


def test_clean_citations_fallback_to_sources():
    srows = [{"url": "https://a.com", "title": "Page A"}]
    out = app._rce_clean_citations([], srows)   # model gave none → cite what we have
    assert out and out[0]["url"] == "https://a.com"


# ---- end-to-end run ---------------------------------------------------------

def test_run_research_end_to_end(monkeypatch):
    _wipe(); _enable(); _patch_world(monkeypatch)
    try:
        res = app._rce_run_research("What is X?", topic="Topic X")
        assert res.get("status") == "ready"
        assert res.get("sources") == 2 and res.get("key_points") == 3
        rid = res["report_id"]
        rep = app.query_db("SELECT topic, question, summary, key_points, citations, "
                           "status, model FROM research_reports WHERE id=%s",
                           (rid,), fetchone=True)
        assert rep["status"] == "ready"
        assert "synthesized" in rep["summary"]
        kp = rep["key_points"] if isinstance(rep["key_points"], list) else json.loads(rep["key_points"])
        cites = rep["citations"] if isinstance(rep["citations"], list) else json.loads(rep["citations"])
        assert len(kp) == 3
        urls = {c["url"] for c in cites}
        assert "https://hallucination.invalid" not in urls   # dropped
        assert "https://a.com" in urls
        # the fetched sources are linked to the report
        n = app.query_db("SELECT COUNT(*) AS n FROM research_sources WHERE report_id=%s",
                         (rid,), fetchone=True)["n"]
        assert n == 2
    finally:
        _wipe(); _reset()


def test_run_research_respects_max_sources(monkeypatch):
    _wipe()
    app.set_ai_setting("research_hub_enabled", True)
    app.set_ai_setting("research_max_sources", 1)
    app._invalidate_ai_control()
    _patch_world(monkeypatch)
    try:
        res = app._rce_run_research("What is X?")
        assert res.get("sources") == 1   # capped
    finally:
        _wipe(); _reset()


# ---- gate + no-key ----------------------------------------------------------

def test_run_gated_off():
    _reset()
    assert "error" in app._rce_run_research("What is X?")


def test_run_requires_key(monkeypatch):
    _enable()
    monkeypatch.setattr(app, "openai_client", None)
    try:
        assert "error" in app._rce_run_research("What is X?")
    finally:
        _reset()


def test_master_switch_disables(monkeypatch):
    app.set_ai_setting("research_hub_enabled", True)
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    _patch_world(monkeypatch)
    try:
        assert "error" in app._rce_run_research("What is X?")
    finally:
        _reset()


# ---- tool + route -----------------------------------------------------------

def test_run_route(monkeypatch):
    _wipe(); _enable(); _patch_world(monkeypatch)
    try:
        c = app.app.test_client()
        c.post("/admin/login", data={"password": ADMIN_PW})
        with c.session_transaction() as s:
            s["_csrf_token"] = "t"
        r = c.post("/admin/api/research/run",
                   json={"question": "What is X?", "topic": "X"},
                   headers={"X-CSRF-Token": "t"})
        assert r.status_code == 200 and r.get_json().get("report_id")
        assert c.post("/admin/api/research/run", json={},
                      headers={"X-CSRF-Token": "t"}).status_code == 400
    finally:
        _wipe(); _reset()


def test_run_route_client_blocked():
    if not CLIENT_PW:
        return
    c = app.app.test_client()
    c.post("/admin/login", data={"password": CLIENT_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    assert c.post("/admin/api/research/run", json={"question": "X"},
                  headers={"X-CSRF-Token": "t"}).status_code == 403


def test_tool_registered():
    assert "run_research" in app.ADMIN_TOOL_FUNCTIONS
    names = {t["function"]["name"] for t in app.ADMIN_TOOLS}
    assert "run_research" in names
