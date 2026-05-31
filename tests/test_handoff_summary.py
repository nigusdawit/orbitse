"""Task 048 — callback AI handoff summary (no-creds part of Epic F).
Embedded Postgres.

Covers:
  * the turn-context var round-trips and _handoff_summary reads it (stubbed
    OpenAI) / returns "" with no context;
  * request_callback stores + notifies WITH the summary only when
    handoff_summary_enabled is on (and default-off = task-045 behavior);
  * the master kill switch forces the summary off;
  * the callbacks read API exposes ai_summary.
"""
import os

import app
import messaging

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")


class _FakeMsg:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeMsg(content)]
        self.usage = None


class _FakeOpenAI:
    def __init__(self, content):
        self._content = content
        self.chat = type("C", (), {"completions": type("X", (), {
            "create": lambda _self, **kw: _FakeResp(content)})()})

    def with_options(self, **kw):
        return self


def _reset():
    for k in ("callback_requests_enabled", "handoff_summary_enabled",
              "handoff_summary_model", "team_notifications_enabled",
              "team_notify_email", "ai_enhancements_enabled"):
        app.reset_ai_setting(k)
    app._invalidate_ai_control()


def _wipe():
    app.execute_db("DELETE FROM callback_requests WHERE tenant_id=%s",
                   (app.current_tenant_id(),))


# ---- context var + summary helper ------------------------------------------

def test_handoff_summary_reads_context():
    saved = app.openai_client
    app.openai_client = _FakeOpenAI("Visitor wants a quote for catering for 40, next month.")
    tok = app._set_chat_turn_ctx(
        [{"role": "user", "content": "do you cater?"},
         {"role": "agent", "content": "Yes!"}],
        "I need catering for 40 people", "vis-1")
    try:
        s = app._handoff_summary()
        assert "catering" in s.lower()
    finally:
        app._CHAT_TURN_CTX.reset(tok)
        app.openai_client = saved


def test_handoff_summary_empty_without_context():
    # No context set → "".
    saved = app.openai_client
    app.openai_client = _FakeOpenAI("should not be used")
    try:
        assert app._handoff_summary() == ""
    finally:
        app.openai_client = saved


# ---- request_callback integration ------------------------------------------

def test_callback_no_summary_by_default():
    _reset(); _wipe()
    app.set_ai_setting("callback_requests_enabled", True)
    app._invalidate_ai_control()
    saved = app.openai_client
    app.openai_client = _FakeOpenAI("SHOULD NOT APPEAR")
    tok = app._set_chat_turn_ctx([], "call me", "v")
    try:
        r = app.request_callback(phone="555-1212")
        assert r["ok"] is True
        row = app.query_db("SELECT ai_summary FROM callback_requests "
                           "ORDER BY id DESC", fetchone=True)
        assert row["ai_summary"] == ""   # summary knob off → not generated
    finally:
        app._CHAT_TURN_CTX.reset(tok)
        app.openai_client = saved
        _wipe(); _reset()


def test_callback_stores_summary_when_enabled(monkeypatch):
    _reset(); _wipe()
    app.set_ai_setting("callback_requests_enabled", True)
    app.set_ai_setting("handoff_summary_enabled", True)
    app.set_ai_setting("team_notifications_enabled", True)
    app.set_ai_setting("team_notify_email", "team@biz.com")
    app._invalidate_ai_control()
    app._NOTIFY_RL_HITS.clear()
    saved = app.openai_client
    app.openai_client = _FakeOpenAI("Hot lead: wants a quote for 40, urgent.")
    notified = {}
    monkeypatch.setattr(messaging, "send_email",
                        lambda to, subj, html, **kw: notified.update(html=html) or {"id": "x"})
    tok = app._set_chat_turn_ctx(
        [{"role": "user", "content": "quote please"}], "for 40 people", "v")
    try:
        r = app.request_callback(name="Jo", phone="555-1212", reason="quote")
        assert r["ok"] is True
        row = app.query_db("SELECT ai_summary FROM callback_requests "
                           "ORDER BY id DESC", fetchone=True)
        assert "Hot lead" in row["ai_summary"]
        # The team email body includes the summary.
        assert "Hot lead" in notified.get("html", "")
    finally:
        app._CHAT_TURN_CTX.reset(tok)
        app.openai_client = saved
        app._NOTIFY_RL_HITS.clear()
        _wipe(); _reset()


def test_master_switch_disables_summary():
    _reset(); _wipe()
    app.set_ai_setting("callback_requests_enabled", True)
    app.set_ai_setting("handoff_summary_enabled", True)
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    saved = app.openai_client
    app.openai_client = _FakeOpenAI("SHOULD NOT APPEAR")
    tok = app._set_chat_turn_ctx([], "call me", "v")
    try:
        # callback_requests_enabled is also forced off by the master switch, so
        # the tool itself declines — assert it doesn't proceed.
        assert app.get_ai_setting("handoff_summary_enabled") is False
        assert app.request_callback(phone="555")["ok"] is False
    finally:
        app._CHAT_TURN_CTX.reset(tok)
        app.openai_client = saved
        _wipe(); _reset()


# ---- read API ---------------------------------------------------------------

def test_callbacks_api_includes_summary():
    _wipe()
    app.execute_db(
        "INSERT INTO callback_requests (tenant_id, name, phone, ai_summary) "
        "VALUES (%s,'Jo','555','wants a quote')", (app.current_tenant_id(),))
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    try:
        body = c.get("/admin/api/callbacks").get_json()
        assert body["callbacks"] and "ai_summary" in body["callbacks"][0]
        assert body["callbacks"][0]["ai_summary"] == "wants a quote"
    finally:
        _wipe()


# ---- registry ---------------------------------------------------------------

def test_knobs_registered():
    keys = {e["key"] for e in app._ai_control_registry()}
    assert {"handoff_summary_enabled", "handoff_summary_model"} <= keys
