"""Visitor-facing "Talk to us" voice button. Embedded Postgres (Vapi HTTP boundary monkeypatched).

The phone-callback path is an anonymous-triggered auto-dialer, so the tests pin every guardrail:
the public config never leaks keys when off; the super-admin config round-trips + is gated; and the
public callback enforces enable -> OUTBOUND_CALLING_ENABLED -> E.164 -> per-number / per-IP / global
rate limits -> honeypot, places a context-tagged call on success, and logs it.
"""
import os

import app
import admin.vapi as vapi_mod

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
_CSRF = {"X-CSRF-Token": "t"}


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    return c


def _client_session():
    c = _sa()
    with c.session_transaction() as s:
        s["admin_role"] = "client"
    return c


def _reset_webvoice():
    app.execute_db("UPDATE site_settings SET web_voice='{}'::jsonb WHERE id=1")


def _clear_requests():
    app.execute_db("DELETE FROM web_call_requests")


def _enable_phone(cap=50, otp=False):
    # default otp=False so the direct-dial guardrail tests below exercise the no-OTP path
    vapi_mod._web_voice_save({"enabled": True, "mode": "both", "assistant_id": "asst_x",
                              "phone_number_id": "pn_x", "button_label": "Talk to us",
                              "daily_call_cap": cap, "otp_required": otp})


def _sms_env(on):
    if on:
        os.environ["TWILIO_ACCOUNT_SID"] = "ac"
        os.environ["TWILIO_AUTH_TOKEN"] = "tok"
        os.environ["TWILIO_FROM_NUMBER"] = "+15550000000"
    else:
        for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"):
            os.environ.pop(k, None)


# ---- E.164 normalization (unit) --------------------------------------------

def test_normalize_e164():
    assert vapi_mod._normalize_e164("+1 (555) 123-4567") == "+15551234567"
    assert vapi_mod._normalize_e164("5551234567") == ""   # no country code → rejected
    assert vapi_mod._normalize_e164("+123") == ""         # too short
    assert vapi_mod._normalize_e164("") == ""


# ---- public web-config (what the widget reads) ------------------------------

def test_web_config_disabled_by_default():
    _reset_webvoice()
    assert app.app.test_client().get("/api/voice/web-config").get_json() == {"enabled": False}


def test_web_config_browser_exposes_public_key_only_when_on():
    os.environ["VAPI_PUBLIC_KEY"] = "pk_test"
    vapi_mod._web_voice_save({"enabled": True, "mode": "browser", "assistant_id": "asst_x"})
    try:
        d = app.app.test_client().get("/api/voice/web-config").get_json()
        assert d["enabled"] is True and d["browser"] is True
        assert d["public_key"] == "pk_test" and d["assistant_id"] == "asst_x"
        assert d.get("phone") is False   # phone mode not selected → not offered
    finally:
        os.environ.pop("VAPI_PUBLIC_KEY", None)
        _reset_webvoice()


# ---- admin config gating + round-trip --------------------------------------

def test_web_voice_admin_requires_super():
    cc = _client_session()
    assert cc.get("/admin/api/vapi/web-voice").status_code == 403
    assert cc.post("/admin/api/vapi/web-voice", headers=_CSRF, json={}).status_code == 403


def test_web_voice_admin_roundtrip():
    try:
        c = _sa()
        r = c.post("/admin/api/vapi/web-voice", headers=_CSRF,
                   json={"enabled": True, "mode": "phone", "assistant_id": "a1",
                         "phone_number_id": "n1", "button_label": "Call us", "daily_call_cap": 7})
        assert r.status_code == 200 and r.get_json()["success"] is True
        d = c.get("/admin/api/vapi/web-voice").get_json()
        assert d["enabled"] is True and d["mode"] == "phone" and d["daily_call_cap"] == 7
        assert d["button_label"] == "Call us"
    finally:
        _reset_webvoice()


# ---- public callback guardrails --------------------------------------------

def test_callback_disabled_404():
    _reset_webvoice()
    r = app.app.test_client().post("/api/voice/callback", json={"phone": "+15551234567"})
    assert r.status_code == 404


def test_callback_honeypot_silent_ok():
    _enable_phone()
    os.environ["OUTBOUND_CALLING_ENABLED"] = "1"
    os.environ["VAPI_PRIVATE_KEY"] = "vp"
    called = {"n": 0}
    orig = vapi_mod._vapi_post
    vapi_mod._vapi_post = lambda p, b: (called.update({"n": called["n"] + 1}) or {"id": "x"})
    try:
        r = app.app.test_client().post("/api/voice/callback",
                                       json={"phone": "+15551234567", "_hp": "i-am-a-bot"})
        assert r.status_code == 200 and r.get_json()["ok"] is True
        assert called["n"] == 0   # honeypot tripped → dialed nobody
    finally:
        vapi_mod._vapi_post = orig
        os.environ.pop("OUTBOUND_CALLING_ENABLED", None)
        os.environ.pop("VAPI_PRIVATE_KEY", None)
        _reset_webvoice()


def test_callback_requires_outbound_enabled():
    _enable_phone()
    os.environ.pop("OUTBOUND_CALLING_ENABLED", None)
    os.environ["VAPI_PRIVATE_KEY"] = "vp"
    try:
        r = app.app.test_client().post("/api/voice/callback", json={"phone": "+15551234567"})
        assert r.status_code == 503
    finally:
        os.environ.pop("VAPI_PRIVATE_KEY", None)
        _reset_webvoice()


def test_callback_bad_number_400():
    _enable_phone()
    os.environ["OUTBOUND_CALLING_ENABLED"] = "1"
    os.environ["VAPI_PRIVATE_KEY"] = "vp"
    try:
        r = app.app.test_client().post("/api/voice/callback", json={"phone": "5551234567"})  # no +
        assert r.status_code == 400 and r.get_json()["error"] == "bad_number"
    finally:
        os.environ.pop("OUTBOUND_CALLING_ENABLED", None)
        os.environ.pop("VAPI_PRIVATE_KEY", None)
        _reset_webvoice()


def test_callback_success_places_logs_and_tags_context():
    _clear_requests()
    _enable_phone()
    os.environ["OUTBOUND_CALLING_ENABLED"] = "1"
    os.environ["VAPI_PRIVATE_KEY"] = "vp"
    phone = "+15557770001"
    captured = {}
    orig = vapi_mod._vapi_post
    vapi_mod._vapi_post = lambda p, b: (captured.update({"body": b}) or {"id": "vc_web_1"})
    try:
        r = app.app.test_client().post("/api/voice/callback",
                                       json={"phone": phone, "visitor_id": "v1", "session_id": "s1",
                                             "page_url": "https://x.test/pricing"})
        d = r.get_json()
        assert r.status_code == 200 and d["ok"] is True
        # call carries page/visitor context for the brain
        assert captured["body"]["metadata"]["source"] == "web_widget"
        assert captured["body"]["metadata"]["page_url"] == "https://x.test/pricing"
        assert captured["body"]["customer"]["number"] == phone
        assert app.query_db("SELECT COUNT(*) AS n FROM web_call_requests WHERE phone=%s",
                            (phone,), fetchone=True)["n"] == 1
        assert app.query_db("SELECT COUNT(*) AS n FROM voice_calls WHERE vapi_call_id='vc_web_1' "
                            "AND direction='outbound'", fetchone=True)["n"] >= 1
    finally:
        vapi_mod._vapi_post = orig
        os.environ.pop("OUTBOUND_CALLING_ENABLED", None)
        os.environ.pop("VAPI_PRIVATE_KEY", None)
        app.execute_db("DELETE FROM web_call_requests WHERE phone=%s", (phone,))
        app.execute_db("DELETE FROM voice_calls WHERE vapi_call_id='vc_web_1'")
        _reset_webvoice()


def test_callback_per_number_rate_limit():
    _clear_requests()
    _enable_phone()
    os.environ["OUTBOUND_CALLING_ENABLED"] = "1"
    os.environ["VAPI_PRIVATE_KEY"] = "vp"
    phone = "+15557770002"
    # pre-seed 2 recent requests to this number (per-number/day limit is 2); different IPs so the
    # per-IP check (from the test client's 127.0.0.1) passes and the per-NUMBER limit is what fires.
    app.execute_db("INSERT INTO web_call_requests (tenant_id, ip, phone, mode) "
                   "VALUES (1,'9.9.9.9',%s,'phone'),(1,'9.9.9.8',%s,'phone')", (phone, phone))
    called = {"n": 0}
    orig = vapi_mod._vapi_post
    vapi_mod._vapi_post = lambda p, b: (called.update({"n": called["n"] + 1}) or {"id": "x"})
    try:
        r = app.app.test_client().post("/api/voice/callback", json={"phone": phone})
        assert r.status_code == 429 and called["n"] == 0
    finally:
        vapi_mod._vapi_post = orig
        os.environ.pop("OUTBOUND_CALLING_ENABLED", None)
        os.environ.pop("VAPI_PRIVATE_KEY", None)
        app.execute_db("DELETE FROM web_call_requests WHERE phone=%s", (phone,))
        _reset_webvoice()


def test_callback_global_daily_cap():
    _clear_requests()
    _enable_phone(cap=1)
    os.environ["OUTBOUND_CALLING_ENABLED"] = "1"
    os.environ["VAPI_PRIVATE_KEY"] = "vp"
    # one request already today (distinct number + IP so per-* checks pass) → global cap of 1 hit
    app.execute_db("INSERT INTO web_call_requests (tenant_id, ip, phone, mode) "
                   "VALUES (1,'8.8.8.8','+15550009999','phone')")
    called = {"n": 0}
    orig = vapi_mod._vapi_post
    vapi_mod._vapi_post = lambda p, b: (called.update({"n": called["n"] + 1}) or {"id": "x"})
    try:
        r = app.app.test_client().post("/api/voice/callback", json={"phone": "+15557770003"})
        assert r.status_code == 503 and called["n"] == 0
    finally:
        vapi_mod._vapi_post = orig
        os.environ.pop("OUTBOUND_CALLING_ENABLED", None)
        os.environ.pop("VAPI_PRIVATE_KEY", None)
        _clear_requests()
        _reset_webvoice()


# ---- OTP (SMS verification before we dial) ----------------------------------

def test_otp_send_texts_code_and_logs():
    phone = "+15558880001"
    app.execute_db("DELETE FROM web_call_otps WHERE phone=%s", (phone,))
    vapi_mod._web_voice_save({"enabled": True, "mode": "both", "assistant_id": "a",
                              "phone_number_id": "n", "otp_required": True})
    os.environ["OUTBOUND_CALLING_ENABLED"] = "1"
    _sms_env(True)
    sent = {}
    orig = vapi_mod.messaging.send_sms
    vapi_mod.messaging.send_sms = lambda to, b, **kw: (sent.update({"to": to, "body": b}) or {"sid": "SM1"})
    try:
        r = app.app.test_client().post("/api/voice/otp", json={"phone": phone})
        assert r.status_code == 200 and r.get_json().get("sent") is True
        assert sent["to"] == phone and "code" in sent["body"].lower()
        # a hashed code row is stored (never plaintext)
        row = app.query_db("SELECT code_hash FROM web_call_otps WHERE phone=%s", (phone,), fetchone=True)
        assert row and row["code_hash"] and len(row["code_hash"]) >= 40
    finally:
        vapi_mod.messaging.send_sms = orig
        os.environ.pop("OUTBOUND_CALLING_ENABLED", None)
        _sms_env(False)
        app.execute_db("DELETE FROM web_call_otps WHERE phone=%s", (phone,))
        _reset_webvoice()


def test_otp_send_unavailable_without_sms():
    vapi_mod._web_voice_save({"enabled": True, "mode": "both", "assistant_id": "a",
                              "phone_number_id": "n", "otp_required": True})
    os.environ["OUTBOUND_CALLING_ENABLED"] = "1"
    _sms_env(False)
    try:
        r = app.app.test_client().post("/api/voice/otp", json={"phone": "+15558880002"})
        assert r.status_code == 503
    finally:
        os.environ.pop("OUTBOUND_CALLING_ENABLED", None)
        _reset_webvoice()


def test_web_config_phone_hidden_when_otp_without_sms():
    vapi_mod._web_voice_save({"enabled": True, "mode": "phone", "assistant_id": "a",
                              "phone_number_id": "n", "otp_required": True})
    os.environ["OUTBOUND_CALLING_ENABLED"] = "1"
    os.environ["VAPI_PRIVATE_KEY"] = "vp"
    _sms_env(False)
    try:
        d = app.app.test_client().get("/api/voice/web-config").get_json()
        assert d["enabled"] is True and d["phone"] is False and d["otp_required"] is True
    finally:
        os.environ.pop("OUTBOUND_CALLING_ENABLED", None)
        os.environ.pop("VAPI_PRIVATE_KEY", None)
        _reset_webvoice()


def test_callback_requires_valid_code_when_otp_on():
    _clear_requests()
    phone = "+15558880003"
    app.execute_db("DELETE FROM web_call_otps WHERE phone=%s", (phone,))
    vapi_mod._web_voice_save({"enabled": True, "mode": "both", "assistant_id": "a",
                              "phone_number_id": "n", "otp_required": True})
    os.environ["OUTBOUND_CALLING_ENABLED"] = "1"
    os.environ["VAPI_PRIVATE_KEY"] = "vp"
    _sms_env(True)
    called = {"n": 0}
    orig = vapi_mod._vapi_post
    vapi_mod._vapi_post = lambda p, b: (called.update({"n": called["n"] + 1}) or {"id": "vc_otp_1"})
    try:
        # no code → refused, nobody dialed
        r1 = app.app.test_client().post("/api/voice/callback", json={"phone": phone})
        assert r1.status_code == 400 and r1.get_json()["error"] == "bad_code" and called["n"] == 0
        # seed a known, unexpired code → the matching call goes through
        app.execute_db("INSERT INTO web_call_otps (tenant_id, phone, ip, code_hash, expires_at) "
                       "VALUES (1,%s,'1.1.1.1',%s, NOW() + INTERVAL '10 minutes')",
                       (phone, vapi_mod._otp_hash("123456", phone)))
        r2 = app.app.test_client().post("/api/voice/callback", json={"phone": phone, "code": "123456"})
        assert r2.status_code == 200 and r2.get_json()["ok"] is True and called["n"] == 1
        # the code is single-use (now verified) → replay is rejected
        r3 = app.app.test_client().post("/api/voice/callback", json={"phone": phone, "code": "123456"})
        assert r3.status_code == 400
    finally:
        vapi_mod._vapi_post = orig
        os.environ.pop("OUTBOUND_CALLING_ENABLED", None)
        os.environ.pop("VAPI_PRIVATE_KEY", None)
        _sms_env(False)
        app.execute_db("DELETE FROM web_call_otps WHERE phone=%s", (phone,))
        app.execute_db("DELETE FROM web_call_requests WHERE phone=%s", (phone,))
        app.execute_db("DELETE FROM voice_calls WHERE vapi_call_id='vc_otp_1'")
        _reset_webvoice()
