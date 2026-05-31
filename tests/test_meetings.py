"""Task 047 — book_meeting (Epic F scaffolding). Embedded Postgres.

Covers gating (+ master switch), validation, store-only vs. calendar-booked
paths (calendar push monkeypatched — the live MCP call is the deferred leg),
team notification, and the super-admin read API.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _reset():
    for k in ("meetings_enabled", "meeting_default_duration_minutes",
              "meeting_calendar_mcp_server", "meeting_calendar_tool",
              "team_notifications_enabled", "team_notify_email",
              "ai_enhancements_enabled"):
        app.reset_ai_setting(k)
    app._invalidate_ai_control()


def _wipe():
    app.execute_db("DELETE FROM meetings WHERE tenant_id=%s", (app.current_tenant_id(),))


# ---- gating + validation ----------------------------------------------------

def test_disabled():
    _reset(); _wipe()
    assert app.book_meeting(email="a@b.com", requested_time="tue 2pm")["ok"] is False
    assert not app.query_db("SELECT 1 FROM meetings", fetchone=True)


def test_requires_email_and_time():
    _reset(); _wipe()
    app.set_ai_setting("meetings_enabled", True); app._invalidate_ai_control()
    try:
        assert app.book_meeting(requested_time="tue 2pm")["ok"] is False        # no email
        assert app.book_meeting(email="bad")["ok"] is False                     # bad email + no time
        assert app.book_meeting(email="a@b.com")["ok"] is False                 # no time
    finally:
        _reset(); _wipe()


def test_master_switch_forces_off():
    _reset(); _wipe()
    app.set_ai_setting("meetings_enabled", True)
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    try:
        assert app.get_ai_setting("meetings_enabled") is False
        assert app.book_meeting(email="a@b.com", requested_time="tue")["ok"] is False
    finally:
        _reset(); _wipe()


# ---- store-only path (no calendar configured) -------------------------------

def test_store_only_requested():
    _reset(); _wipe()
    app.set_ai_setting("meetings_enabled", True); app._invalidate_ai_control()
    try:
        r = app.book_meeting(name="Jo", email="jo@example.com",
                             requested_time="Tue Jun 3 2pm", notes="demo")
        assert r["ok"] is True and r.get("requested") is True
        row = app.query_db("SELECT status, calendar_event_id, duration_minutes "
                           "FROM meetings ORDER BY id DESC", fetchone=True)
        assert row["status"] == "requested" and row["calendar_event_id"] == ""
        assert row["duration_minutes"] == 30   # default
    finally:
        _reset(); _wipe()


def test_default_duration_setting():
    _reset(); _wipe()
    app.set_ai_setting("meetings_enabled", True)
    app.set_ai_setting("meeting_default_duration_minutes", 45)
    app._invalidate_ai_control()
    try:
        app.book_meeting(email="x@y.com", requested_time="now")
        row = app.query_db("SELECT duration_minutes FROM meetings ORDER BY id DESC", fetchone=True)
        assert row["duration_minutes"] == 45
    finally:
        _reset(); _wipe()


# ---- calendar-booked path (push monkeypatched) ------------------------------

def test_calendar_push_marks_booked(monkeypatch):
    _reset(); _wipe()
    app.set_ai_setting("meetings_enabled", True); app._invalidate_ai_control()
    monkeypatch.setattr(app, "_meeting_calendar_push",
                        lambda *a, **k: "evt_12345")
    try:
        r = app.book_meeting(email="jo@example.com", requested_time="Tue 2pm")
        assert r["ok"] is True and r.get("booked") is True
        row = app.query_db("SELECT status, calendar_event_id FROM meetings "
                           "ORDER BY id DESC", fetchone=True)
        assert row["status"] == "booked" and row["calendar_event_id"] == "evt_12345"
    finally:
        _reset(); _wipe()


def test_calendar_push_storeonly_when_unconfigured():
    # _meeting_calendar_push returns "" when no server configured → 'requested'.
    _reset(); _wipe()
    app.set_ai_setting("meetings_enabled", True); app._invalidate_ai_control()
    try:
        assert app._meeting_calendar_push("n", "e@x.com", "t", 30, "") == ""
    finally:
        _reset(); _wipe()


def test_notifies_team(monkeypatch):
    _reset(); _wipe()
    app.set_ai_setting("meetings_enabled", True)
    app.set_ai_setting("team_notifications_enabled", True)
    app.set_ai_setting("team_notify_email", "team@biz.com")
    app._invalidate_ai_control()
    app._NOTIFY_RL_HITS.clear()
    import messaging
    calls = []
    monkeypatch.setattr(messaging, "send_email",
                        lambda to, subj, html, **kw: calls.append(to) or {"id": "x"})
    try:
        app.book_meeting(email="jo@example.com", requested_time="Tue 2pm")
        assert calls == ["team@biz.com"]
    finally:
        app._NOTIFY_RL_HITS.clear()
        _reset(); _wipe()


# ---- read API ---------------------------------------------------------------

def test_meetings_api_super_admin():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    r = c.get("/admin/api/meetings")
    assert r.status_code == 200 and "meetings" in r.get_json()


def test_meetings_api_blocks_client():
    if not CLIENT_PW:
        return
    c = app.app.test_client()
    c.post("/admin/login", data={"password": CLIENT_PW})
    assert c.get("/admin/api/meetings").status_code == 403


# ---- registry ---------------------------------------------------------------

def test_tool_and_knobs_registered():
    assert "book_meeting" in app.CHAT_LOOKUP_FUNCTIONS
    names = {t["function"]["name"] for t in app.CHAT_TOOLS}
    assert "book_meeting" in names
    keys = {e["key"] for e in app._ai_control_registry()}
    assert {"meetings_enabled", "meeting_default_duration_minutes",
            "meeting_calendar_mcp_server", "meeting_calendar_tool"} <= keys
