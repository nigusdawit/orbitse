"""Vapi slice 4 — provisioning, in-browser test-call config, compliance, and the cost caps.

Embedded Postgres (no DB mocks; the Vapi HTTP boundary + the cost summers are monkeypatched).
Covers: the public key + assistantOverrides exposed on /status for the browser test; the
compliance round-trip (recording toggle + consent first-message) and how it projects into Vapi
assistantOverrides; free-number provisioning (payload shape + gating); and the daily spend cap
guarding BOTH the outbound campaign and the Vapi custom-LLM voice brain.
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


def _reset_compliance():
    app.execute_db("UPDATE site_settings SET voice_compliance='{}'::jsonb WHERE id=1")


def _ctx(aid):
    return {"trigger": {}, "__deadline": 9e18, "__automation_id": aid, "__dry_run": False}


# ---- /status exposes the browser-test config --------------------------------

def test_status_exposes_public_key_and_overrides():
    os.environ.pop("VAPI_PUBLIC_KEY", None)
    _reset_compliance()
    d = _sa().get("/admin/api/vapi/status").get_json()
    assert "public_key" in d and d["public_key"] == ""
    assert d.get("assistant_overrides") == {}   # default (recording on, no consent) → no override


# ---- compliance round-trip + override projection ----------------------------

def test_compliance_roundtrip_becomes_overrides():
    try:
        c = _sa()
        r = c.post("/admin/api/vapi/compliance", headers=_CSRF,
                   json={"recording_enabled": False, "consent_message": "This call may be recorded."})
        assert r.status_code == 200 and r.get_json().get("success") is True
        got = c.get("/admin/api/vapi/compliance").get_json()
        assert got["recording_enabled"] is False
        assert got["consent_message"] == "This call may be recorded."
        # the helper + /status now project these as Vapi assistantOverrides
        ov = vapi_mod._vapi_assistant_overrides()
        assert ov.get("artifactPlan", {}).get("recordingEnabled") is False
        assert ov.get("firstMessage") == "This call may be recorded."
        assert c.get("/admin/api/vapi/status").get_json().get("assistant_overrides") == ov
    finally:
        _reset_compliance()


def test_compliance_requires_super():
    cc = _client_session()
    assert cc.get("/admin/api/vapi/compliance").status_code == 403
    assert cc.post("/admin/api/vapi/compliance", headers=_CSRF, json={}).status_code == 403


# ---- free-number provisioning -----------------------------------------------

def test_provision_number_success():
    os.environ["VAPI_PRIVATE_KEY"] = "vp"
    captured = {}
    orig = vapi_mod._vapi_post

    def _fake(path, body):
        captured["path"] = path
        captured["body"] = body
        return {"id": "pn_new_1", "number": "+14155550123"}

    vapi_mod._vapi_post = _fake
    try:
        r = _sa().post("/admin/api/vapi/phone-number", headers=_CSRF, json={"area_code": "415"})
        d = r.get_json()
        assert r.status_code == 200 and d.get("success") is True
        assert d.get("number") == "+14155550123"
        assert captured["path"] == "/phone-number"
        assert captured["body"].get("provider") == "vapi"
        assert captured["body"].get("numberDesiredAreaCode") == "415"
    finally:
        vapi_mod._vapi_post = orig
        os.environ.pop("VAPI_PRIVATE_KEY", None)


def test_provision_not_configured():
    os.environ.pop("VAPI_PRIVATE_KEY", None)
    os.environ.pop("VAPI_API_KEY", None)
    r = _sa().post("/admin/api/vapi/phone-number", headers=_CSRF, json={"area_code": "415"})
    assert r.status_code == 400 and r.get_json().get("error") == "not_configured"


def test_provision_requires_super():
    cc = _client_session()
    assert cc.post("/admin/api/vapi/phone-number", headers=_CSRF, json={}).status_code == 403


# ---- compliance overrides ride along on campaign calls ----------------------

def test_campaign_applies_compliance_overrides():
    os.environ["OUTBOUND_CALLING_ENABLED"] = "1"
    os.environ["VAPI_PRIVATE_KEY"] = "vp"
    aid = 778050
    status = "zzov_test"
    app.execute_db("DELETE FROM leads WHERE email='ovtest@example.test'")
    app.execute_db("DELETE FROM campaign_calls WHERE automation_id=%s", (aid,))
    lead = app.execute_db("INSERT INTO leads (tenant_id, name, email, phone, status) "
                          "VALUES (1,'OV','ovtest@example.test','+15551239000',%s) RETURNING id", (status,))
    lid = lead["id"]
    vapi_mod._voice_compliance_save({"recording_enabled": False, "consent_message": ""})
    captured = {}
    orig = vapi_mod._vapi_post
    vapi_mod._vapi_post = lambda path, body: (captured.update({"body": body}) or {"id": "vc_ov_1"})
    cfg = {"assistant_id": "asst", "phone_number_id": "pn", "audience_table": "leads",
           "status_filter": status, "call_start_hour": 0, "call_end_hour": 24, "max_calls_per_run": 5}
    try:
        out = vapi_mod._run_outbound_campaign(cfg, _ctx(aid))
        assert out["ok"] is True and out["calls_placed"] == 1
        assert captured["body"].get("assistantOverrides", {}).get("artifactPlan", {}).get("recordingEnabled") is False
    finally:
        vapi_mod._vapi_post = orig
        _reset_compliance()
        os.environ.pop("OUTBOUND_CALLING_ENABLED", None)
        os.environ.pop("VAPI_PRIVATE_KEY", None)
        app.execute_db("DELETE FROM campaign_calls WHERE automation_id=%s", (aid,))
        app.execute_db("DELETE FROM voice_calls WHERE vapi_call_id='vc_ov_1'")
        app.execute_db("DELETE FROM leads WHERE id=%s", (lid,))


# ---- daily spend cap guards the campaign ------------------------------------

def test_campaign_daily_cap_skip():
    os.environ["OUTBOUND_CALLING_ENABLED"] = "1"
    os.environ["VAPI_PRIVATE_KEY"] = "vp"
    aid = 778051
    status = "zzcap_test"
    app.execute_db("DELETE FROM leads WHERE email='captest@example.test'")
    app.execute_db("DELETE FROM campaign_calls WHERE automation_id=%s", (aid,))
    lead = app.execute_db("INSERT INTO leads (tenant_id, name, email, phone, status) "
                          "VALUES (1,'CAP','captest@example.test','+15551239100',%s) RETURNING id", (status,))
    lid = lead["id"]
    og, oc = vapi_mod.get_ai_setting, vapi_mod.compute_today_spend
    vapi_mod.get_ai_setting = lambda k=None: 5.0 if k == "daily_spend_cap_usd" else og(k)
    vapi_mod.compute_today_spend = lambda *a, **k: {"total_usd": 999.0}
    called = {"n": 0}
    orig = vapi_mod._vapi_post
    vapi_mod._vapi_post = lambda path, body: (called.update({"n": called["n"] + 1}) or {"id": "x"})
    cfg = {"assistant_id": "asst", "phone_number_id": "pn", "audience_table": "leads",
           "status_filter": status, "call_start_hour": 0, "call_end_hour": 24}
    try:
        out = vapi_mod._run_outbound_campaign(cfg, _ctx(aid))
        assert out["ok"] is True and out["calls_placed"] == 0 and "skipped" in out
        assert called["n"] == 0   # cap reached → not a single call placed
    finally:
        vapi_mod.get_ai_setting, vapi_mod.compute_today_spend = og, oc
        vapi_mod._vapi_post = orig
        os.environ.pop("OUTBOUND_CALLING_ENABLED", None)
        os.environ.pop("VAPI_PRIVATE_KEY", None)
        app.execute_db("DELETE FROM campaign_calls WHERE automation_id=%s", (aid,))
        app.execute_db("DELETE FROM leads WHERE id=%s", (lid,))


# ---- daily spend cap guards the voice brain (custom-LLM endpoint) -----------

def test_llm_endpoint_daily_cap_blocks():
    os.environ["VAPI_LLM_SECRET"] = "llmsecret"
    og, oc = app.get_ai_setting, app.compute_today_spend
    app.get_ai_setting = lambda k=None: 1.0 if k == "daily_spend_cap_usd" else og(k)
    app.compute_today_spend = lambda *a, **k: {"total_usd": 999.0}
    try:
        c = app.app.test_client()
        r = c.post("/api/vapi/llm/chat/completions",
                   headers={"Authorization": "Bearer llmsecret"},
                   json={"messages": [{"role": "user", "content": "hi"}], "stream": False})
        assert r.status_code == 402
        assert (r.get_json() or {}).get("error") == "cap_reached"
    finally:
        app.get_ai_setting, app.compute_today_spend = og, oc
        os.environ.pop("VAPI_LLM_SECRET", None)
