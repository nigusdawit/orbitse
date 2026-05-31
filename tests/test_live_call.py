"""Task 049 — live AI phone call scaffolding (Epic F). Embedded Postgres.

Covers the Twilio Voice webhooks + gating + TwiML shape (the live media bridge
to a realtime voice model is the deferred operator-runbook leg):
  * signature failure → reject (no processing);
  * disabled → spoken decline, no <Stream>, no row logged;
  * enabled + wss configured → <Connect><Stream> TwiML + a logged call;
  * enabled, no wss → spoken fallback (no <Stream>);
  * status callback updates the call;
  * super-admin read API; client 403.
"""
import os

import app
import messaging

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _reset():
    for k in ("live_call_enabled", "voice_wss_url", "voice_greeting",
              "ai_enhancements_enabled"):
        app.reset_ai_setting(k)
    app._invalidate_ai_control()


def _wipe():
    app.execute_db("DELETE FROM voice_calls WHERE tenant_id=%s", (app.current_tenant_id(),))


def _post_voice(c, **form):
    return c.post("/webhooks/twilio/voice", data=form)


# ---- signature --------------------------------------------------------------

def test_bad_signature_rejected(monkeypatch):
    _reset()
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")  # auth configured
    monkeypatch.setattr(messaging, "verify_twilio_signature", lambda *a, **k: False)
    c = app.app.test_client()
    r = _post_voice(c, CallSid="CA1", From="+15551112222", To="+15553334444")
    assert "<Reject" in r.get_data(as_text=True)


def test_fail_closed_without_auth_token(monkeypatch):
    """When TWILIO_AUTH_TOKEN is unset, the voice webhook must FAIL CLOSED
    (reject) even with the feature enabled — the signature check fails open."""
    _reset()
    app.set_ai_setting("live_call_enabled", True)
    app.set_ai_setting("voice_wss_url", "wss://bridge.example.com/media")
    app._invalidate_ai_control()
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(messaging, "verify_twilio_signature", lambda *a, **k: True)
    try:
        c = app.app.test_client()
        body = _post_voice(c, CallSid="CA-noauth", From="+1", To="+2").get_data(as_text=True)
        assert "<Reject" in body and "<Stream" not in body
    finally:
        _reset()


# ---- gating -----------------------------------------------------------------

def test_disabled_declines(monkeypatch):
    _reset(); _wipe()
    monkeypatch.setattr(messaging, "verify_twilio_signature", lambda *a, **k: True)
    c = app.app.test_client()
    r = _post_voice(c, CallSid="CA-disabled", From="+1", To="+2")
    body = r.get_data(as_text=True)
    assert "<Say>" in body and "<Stream" not in body
    # No call row logged when the feature is off.
    assert not app.query_db("SELECT 1 FROM voice_calls WHERE call_sid='CA-disabled'",
                            fetchone=True)


def test_master_switch_forces_off(monkeypatch):
    _reset(); _wipe()
    app.set_ai_setting("live_call_enabled", True)
    app.set_ai_setting("voice_wss_url", "wss://example.com/stream")
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    monkeypatch.setattr(messaging, "verify_twilio_signature", lambda *a, **k: True)
    try:
        assert app.get_ai_setting("live_call_enabled") is False
        c = app.app.test_client()
        body = _post_voice(c, CallSid="CA-m", From="+1", To="+2").get_data(as_text=True)
        assert "<Stream" not in body
    finally:
        _reset(); _wipe()


# ---- enabled paths ----------------------------------------------------------

def test_enabled_with_wss_streams(monkeypatch):
    _reset(); _wipe()
    app.set_ai_setting("live_call_enabled", True)
    app.set_ai_setting("voice_wss_url", "wss://bridge.example.com/media")
    app._invalidate_ai_control()
    monkeypatch.setattr(messaging, "verify_twilio_signature", lambda *a, **k: True)
    try:
        c = app.app.test_client()
        r = _post_voice(c, CallSid="CA-live", From="+15551112222", To="+15553334444")
        body = r.get_data(as_text=True)
        assert "<Connect>" in body and "wss://bridge.example.com/media" in body
        row = app.query_db("SELECT from_number, status FROM voice_calls "
                           "WHERE call_sid='CA-live'", fetchone=True)
        assert row and row["from_number"] == "+15551112222"
    finally:
        _reset(); _wipe()


def test_enabled_without_wss_fallback(monkeypatch):
    _reset(); _wipe()
    app.set_ai_setting("live_call_enabled", True)  # no wss configured
    app._invalidate_ai_control()
    monkeypatch.setattr(messaging, "verify_twilio_signature", lambda *a, **k: True)
    try:
        c = app.app.test_client()
        body = _post_voice(c, CallSid="CA-fb", From="+1", To="+2").get_data(as_text=True)
        assert "<Stream" not in body and "<Hangup" in body
        assert app.query_db("SELECT 1 FROM voice_calls WHERE call_sid='CA-fb'",
                            fetchone=True)  # still logged
    finally:
        _reset(); _wipe()


# ---- status callback --------------------------------------------------------

def test_status_callback_updates(monkeypatch):
    _reset(); _wipe()
    monkeypatch.setattr(messaging, "verify_twilio_signature", lambda *a, **k: True)
    app.execute_db(
        "INSERT INTO voice_calls (tenant_id, call_sid, status) VALUES (%s,'CA-st','in-progress')",
        (app.current_tenant_id(),))
    try:
        c = app.app.test_client()
        c.post("/webhooks/twilio/voice-status", data={"CallSid": "CA-st", "CallStatus": "completed"})
        row = app.query_db("SELECT status FROM voice_calls WHERE call_sid='CA-st'", fetchone=True)
        assert row["status"] == "completed"
    finally:
        _wipe()


# ---- read API ---------------------------------------------------------------

def test_voice_calls_api_super_admin():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    r = c.get("/admin/api/voice-calls")
    assert r.status_code == 200 and "calls" in r.get_json()


def test_voice_calls_api_blocks_client():
    if not CLIENT_PW:
        return
    c = app.app.test_client()
    c.post("/admin/login", data={"password": CLIENT_PW})
    assert c.get("/admin/api/voice-calls").status_code == 403


# ---- registry ---------------------------------------------------------------

def test_knobs_registered():
    keys = {e["key"] for e in app._ai_control_registry()}
    assert {"live_call_enabled", "voice_wss_url", "voice_greeting"} <= keys
