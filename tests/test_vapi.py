"""Vapi integration slice 1 — plumbing. Embedded Postgres (no DB mocks).

Covers: the voice_calls Vapi columns (migration 0042); super-admin gating + not-configured
behavior on status/probe; and the public /webhooks/vapi endpoint — shared-secret verification
plus logging an end-of-call report into voice_calls + voice_cost_events (so Vapi calls land in
the existing Voice + Cost surfaces).
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


def test_voice_calls_vapi_columns_exist():
    app.query_db("SELECT provider, vapi_call_id, assistant_id, duration_seconds, cost_usd, "
                 "transcript, recording_url, ended_reason FROM voice_calls LIMIT 1")


def test_vapi_status_and_probe_super_admin_only():
    cc = _client_session()
    assert cc.get("/admin/api/vapi/status").status_code == 403
    assert cc.post("/admin/api/vapi/probe", headers=_CSRF, json={}).status_code == 403


def test_vapi_status_not_configured():
    os.environ.pop("VAPI_PRIVATE_KEY", None)
    os.environ.pop("VAPI_API_KEY", None)
    assert _sa().get("/admin/api/vapi/status").get_json()["configured"] is False


def test_vapi_probe_not_configured_is_400():
    os.environ.pop("VAPI_PRIVATE_KEY", None)
    os.environ.pop("VAPI_API_KEY", None)
    r = _sa().post("/admin/api/vapi/probe", headers=_CSRF, json={})
    assert r.status_code == 400 and r.get_json().get("error") == "not_configured"


def test_vapi_webhook_secret_enforced():
    os.environ["VAPI_WEBHOOK_SECRET"] = "tops3cret"
    try:
        pub = app.app.test_client()
        assert pub.post("/webhooks/vapi", json={"message": {"type": "status-update"}}).status_code == 401
        assert pub.post("/webhooks/vapi", headers={"X-Vapi-Secret": "wrong"},
                        json={"message": {"type": "status-update"}}).status_code == 401
        r = pub.post("/webhooks/vapi", headers={"X-Vapi-Secret": "tops3cret"},
                     json={"message": {"type": "status-update", "call": {"id": "vc_secret_ok"}}})
        assert r.status_code == 200
    finally:
        os.environ.pop("VAPI_WEBHOOK_SECRET", None)
        app.execute_db("DELETE FROM voice_calls WHERE vapi_call_id='vc_secret_ok'")


def test_vapi_webhook_logs_call_and_cost():
    os.environ.pop("VAPI_WEBHOOK_SECRET", None)   # dev: no secret → fail-open
    cid = "vc_eocr_test_1"
    app.execute_db("DELETE FROM voice_calls WHERE vapi_call_id=%s", (cid,))
    app.execute_db("DELETE FROM voice_cost_events WHERE session_id=%s", (cid,))
    payload = {"message": {
        "type": "end-of-call-report",
        "endedReason": "customer-ended-call",
        "cost": 0.18,
        "durationSeconds": 120,
        "transcript": "Hello, I'd like a quote.",
        "recordingUrl": "https://rec.example/x.wav",
        "summary": "Lead asked for a quote.",
        "call": {"id": cid, "assistantId": "asst_123", "type": "inboundPhoneCall"},
        "customer": {"number": "+15551112222"},
        "phoneNumber": {"number": "+15559998888"},
    }}
    try:
        assert app.app.test_client().post("/webhooks/vapi", json=payload).status_code == 200
        row = app.query_db("SELECT * FROM voice_calls WHERE vapi_call_id=%s", (cid,), fetchone=True)
        assert isinstance(row, dict)
        assert row["provider"] == "vapi" and row["status"] == "ended"
        assert row["assistant_id"] == "asst_123"
        assert float(row["cost_usd"]) == 0.18
        assert float(row["duration_seconds"]) == 120
        assert "quote" in (row["transcript"] or "")
        assert row["from_number"] == "+15551112222"        # inbound: from = customer
        assert row["recording_url"] == "https://rec.example/x.wav"
        cost = app.query_db("SELECT cost_usd, provider, surface FROM voice_cost_events WHERE session_id=%s",
                            (cid,), fetchone=True)
        assert isinstance(cost, dict) and float(cost["cost_usd"]) == 0.18
        assert cost["provider"] == "vapi" and cost["surface"] == "voice_call"
        # a later status-update updates the SAME row (no duplicate)
        app.app.test_client().post("/webhooks/vapi", json={"message": {
            "type": "status-update", "status": "ended", "call": {"id": cid}}})
        n = app.query_db("SELECT COUNT(*) AS n FROM voice_calls WHERE vapi_call_id=%s", (cid,), fetchone=True)["n"]
        assert n == 1
    finally:
        app.execute_db("DELETE FROM voice_calls WHERE vapi_call_id=%s", (cid,))
        app.execute_db("DELETE FROM voice_cost_events WHERE session_id=%s", (cid,))


# --- slice 2: assistant registry + outbound/inbound calling ------------------

def test_vapi_assistants_numbers_not_configured():
    os.environ.pop("VAPI_PRIVATE_KEY", None)
    os.environ.pop("VAPI_API_KEY", None)
    c = _sa()
    assert c.get("/admin/api/vapi/assistants").get_json()["configured"] is False
    assert c.get("/admin/api/vapi/phone-numbers").get_json()["configured"] is False


def test_vapi_call_gating_and_validation():
    cc = _client_session()
    assert cc.post("/admin/api/vapi/call", headers=_CSRF, json={}).status_code == 403  # super-admin only
    os.environ.pop("VAPI_PRIVATE_KEY", None)
    os.environ.pop("VAPI_API_KEY", None)
    c = _sa()
    assert c.post("/admin/api/vapi/call", headers=_CSRF, json={}).status_code == 400  # not_configured
    os.environ["VAPI_PRIVATE_KEY"] = "vp_test"
    try:
        assert c.post("/admin/api/vapi/call", headers=_CSRF,
                      json={"assistant_id": "a"}).status_code == 400  # missing fields
        assert c.post("/admin/api/vapi/call", headers=_CSRF,
                      json={"assistant_id": "a", "phone_number_id": "p",
                            "customer_number": "5551234"}).status_code == 400  # not E.164
    finally:
        os.environ.pop("VAPI_PRIVATE_KEY", None)


def test_vapi_outbound_call_logs_row():
    os.environ["VAPI_PRIVATE_KEY"] = "vp_test"
    orig = vapi_mod._vapi_post
    vapi_mod._vapi_post = lambda path, body: {"id": "vc_outbound_1"}
    app.execute_db("DELETE FROM voice_calls WHERE vapi_call_id='vc_outbound_1'")
    try:
        r = _sa().post("/admin/api/vapi/call", headers=_CSRF,
                       json={"assistant_id": "asst_x", "phone_number_id": "pn_x",
                             "customer_number": "+15551234567"})
        assert r.status_code == 200 and r.get_json()["success"] is True
        row = app.query_db("SELECT * FROM voice_calls WHERE vapi_call_id='vc_outbound_1'", fetchone=True)
        assert isinstance(row, dict)
        assert row["provider"] == "vapi" and row["direction"] == "outbound"
        assert row["assistant_id"] == "asst_x" and row["to_number"] == "+15551234567"
    finally:
        vapi_mod._vapi_post = orig
        os.environ.pop("VAPI_PRIVATE_KEY", None)
        app.execute_db("DELETE FROM voice_calls WHERE vapi_call_id='vc_outbound_1'")


def test_vapi_assign_number():
    cc = _client_session()
    assert cc.patch("/admin/api/vapi/phone-number", headers=_CSRF,
                    json={"phone_number_id": "p"}).status_code == 403
    os.environ["VAPI_PRIVATE_KEY"] = "vp_test"
    orig = vapi_mod._vapi_patch
    vapi_mod._vapi_patch = lambda path, body: {"id": "pn_x"}
    try:
        c = _sa()
        assert c.patch("/admin/api/vapi/phone-number", headers=_CSRF, json={}).status_code == 400  # missing
        r = c.patch("/admin/api/vapi/phone-number", headers=_CSRF,
                    json={"phone_number_id": "pn_x", "assistant_id": "asst_x"})
        assert r.status_code == 200 and r.get_json()["success"] is True
    finally:
        vapi_mod._vapi_patch = orig
        os.environ.pop("VAPI_PRIVATE_KEY", None)


# --- slice 4: function-call tools routed to the concierge tool executor -------

def test_vapi_webhook_function_call_routes_to_tool():
    os.environ.pop("VAPI_WEBHOOK_SECRET", None)   # dev: no secret → fail-open
    orig = getattr(app, "execute_chat_tool", None)
    app.execute_chat_tool = lambda name, args_json, session_id="": ("RAN:" + (name or ""), {})
    try:
        # newer toolCalls shape → {"results": [{toolCallId, result}]}
        r = app.app.test_client().post("/webhooks/vapi", json={"message": {
            "type": "tool-calls", "call": {"id": "vc_tool_1"},
            "toolCalls": [{"id": "tc_1", "function": {"name": "book_meeting", "arguments": "{}"}}]}})
        assert r.status_code == 200
        d = r.get_json()
        assert d["results"][0]["toolCallId"] == "tc_1"
        assert d["results"][0]["result"] == "RAN:book_meeting"
        # legacy functionCall shape → {"result": ...}
        r2 = app.app.test_client().post("/webhooks/vapi", json={"message": {
            "type": "function-call", "call": {"id": "vc_tool_2"},
            "functionCall": {"name": "capture_lead", "parameters": {"email": "x@y.z"}}}})
        assert r2.status_code == 200
        assert r2.get_json()["result"] == "RAN:capture_lead"
    finally:
        if orig is not None:
            app.execute_chat_tool = orig
