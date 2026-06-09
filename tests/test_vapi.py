"""Vapi integration slice 1 — plumbing. Embedded Postgres (no DB mocks).

Covers: the voice_calls Vapi columns (migration 0042); super-admin gating + not-configured
behavior on status/probe; and the public /webhooks/vapi endpoint — shared-secret verification
plus logging an end-of-call report into voice_calls + voice_cost_events (so Vapi calls land in
the existing Voice + Cost surfaces).
"""
import os

import app

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
