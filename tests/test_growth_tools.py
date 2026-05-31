"""Task 045 — agentic growth tools (capture_lead / request_callback /
notify_team). Embedded Postgres.

Covers gating (+ master switch), validation, DB writes, and — critically —
that notify_team only ever sends to the OPERATOR-configured destination, never
to a visitor/agent-supplied recipient. Outbound providers are stubbed.
"""
import os

import app
import messaging

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _reset():
    for k in ("lead_capture_enabled", "callback_requests_enabled",
              "team_notifications_enabled", "team_notify_email",
              "team_notify_sms", "ai_enhancements_enabled"):
        app.reset_ai_setting(k)
    app._invalidate_ai_control()


def _wipe():
    tid = app.current_tenant_id()
    app.execute_db("DELETE FROM leads WHERE tenant_id=%s", (tid,))
    app.execute_db("DELETE FROM callback_requests WHERE tenant_id=%s", (tid,))


# ---- capture_lead -----------------------------------------------------------

def test_capture_lead_disabled():
    _reset(); _wipe()
    r = app.capture_lead(email="a@b.com")
    assert r["ok"] is False
    assert not app.query_db("SELECT 1 FROM leads", fetchone=True)


def test_capture_lead_requires_contact():
    _reset()
    app.set_ai_setting("lead_capture_enabled", True); app._invalidate_ai_control()
    try:
        assert app.capture_lead(name="No Contact")["ok"] is False
        assert app.capture_lead(email="bad-email")["ok"] is False
    finally:
        _reset(); _wipe()


def test_capture_lead_inserts():
    _reset(); _wipe()
    app.set_ai_setting("lead_capture_enabled", True); app._invalidate_ai_control()
    try:
        r = app.capture_lead(name="Jane", email="jane@example.com",
                             interest="catering", message="party of 40")
        assert r["ok"] is True
        row = app.query_db("SELECT name, email, interest FROM leads "
                           "ORDER BY id DESC", fetchone=True)
        assert row["email"] == "jane@example.com" and row["interest"] == "catering"
    finally:
        _reset(); _wipe()


# ---- request_callback -------------------------------------------------------

def test_callback_disabled_and_requires_phone():
    _reset(); _wipe()
    assert app.request_callback(phone="555")["ok"] is False  # disabled
    app.set_ai_setting("callback_requests_enabled", True); app._invalidate_ai_control()
    try:
        assert app.request_callback(name="NoPhone")["ok"] is False
        r = app.request_callback(name="Al", phone="415-555-0000",
                                 preferred_time="tomorrow am", reason="quote")
        assert r["ok"] is True
        row = app.query_db("SELECT phone, reason FROM callback_requests "
                           "ORDER BY id DESC", fetchone=True)
        assert row["phone"] == "415-555-0000" and row["reason"] == "quote"
    finally:
        _reset(); _wipe()


# ---- notify_team (outbound, stubbed) ---------------------------------------

def test_notify_team_disabled():
    _reset()
    assert app.notify_team(subject="hi", message="x")["ok"] is False


def test_notify_team_sends_only_to_configured_dest(monkeypatch):
    _reset()
    app.set_ai_setting("team_notifications_enabled", True)
    app.set_ai_setting("team_notify_email", "team@business.com")
    app._invalidate_ai_control()
    sent = {}

    def fake_send_email(to, subject, html, **kw):
        sent["to"] = to
        sent["subject"] = subject
        return {"id": "stub"}
    monkeypatch.setattr(messaging, "send_email", fake_send_email)
    try:
        # The agent tries to smuggle a recipient via extra kwargs — must be ignored.
        r = app.notify_team(subject="Urgent", message="call back",
                            to="attacker@evil.com", email="attacker@evil.com")
        assert r["ok"] is True and "email" in r["channels"]
        assert sent["to"] == "team@business.com"  # configured dest, NOT the smuggled one
    finally:
        _reset()


def test_notify_team_no_destination_configured():
    _reset()
    app.set_ai_setting("team_notifications_enabled", True)  # on, but no dest set
    app._invalidate_ai_control()
    try:
        r = app.notify_team(subject="hi", message="x")
        assert r["ok"] is False
    finally:
        _reset()


def test_capture_lead_notifies_team(monkeypatch):
    _reset(); _wipe()
    app.set_ai_setting("lead_capture_enabled", True)
    app.set_ai_setting("team_notifications_enabled", True)
    app.set_ai_setting("team_notify_email", "team@business.com")
    app._invalidate_ai_control()
    calls = []
    monkeypatch.setattr(messaging, "send_email",
                        lambda to, subj, html, **kw: calls.append(to) or {"id": "x"})
    try:
        app.capture_lead(email="lead@example.com", interest="x")
        assert calls == ["team@business.com"]
    finally:
        _reset(); _wipe()


# ---- master switch ----------------------------------------------------------

def test_master_switch_forces_all_off():
    _reset(); _wipe()
    for k in ("lead_capture_enabled", "callback_requests_enabled",
              "team_notifications_enabled"):
        app.set_ai_setting(k, True)
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    try:
        assert app.capture_lead(email="a@b.com")["ok"] is False
        assert app.request_callback(phone="555")["ok"] is False
        assert app.notify_team(message="x")["ok"] is False
    finally:
        _reset(); _wipe()


# ---- super-admin read APIs --------------------------------------------------

def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    return c


def test_read_apis_super_admin_ok():
    c = _sa()
    assert c.get("/admin/api/leads").status_code == 200
    assert c.get("/admin/api/callbacks").status_code == 200


def test_read_apis_block_client():
    if not CLIENT_PW:
        return
    c = app.app.test_client()
    c.post("/admin/login", data={"password": CLIENT_PW})
    assert c.get("/admin/api/leads").status_code == 403
    assert c.get("/admin/api/callbacks").status_code == 403


# ---- registry ---------------------------------------------------------------

def test_tools_and_knobs_registered():
    for fn in ("capture_lead", "request_callback", "notify_team"):
        assert fn in app.CHAT_LOOKUP_FUNCTIONS
    names = {t["function"]["name"] for t in app.CHAT_TOOLS}
    assert {"capture_lead", "request_callback", "notify_team"} <= names
    keys = {e["key"] for e in app._ai_control_registry()}
    assert {"lead_capture_enabled", "callback_requests_enabled",
            "team_notifications_enabled", "team_notify_email", "team_notify_sms"} <= keys
