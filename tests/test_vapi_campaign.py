"""Vapi outbound-call automation. Embedded Postgres (no DB mocks; Vapi POST monkeypatched).

The vapi_outbound_campaign action auto-dials people, so the tests pin every guardrail:
ENV kill-switch, VAPI key requirement, audience allowlist, calling-hours skip, dry-run (no
dials), a real run that places + logs calls, and per-campaign dedup (no re-dialing).
"""
import os

import app
import admin.vapi as vapi_mod


def _ctx(aid, dry=False):
    return {"trigger": {}, "__deadline": 9e18, "__automation_id": aid, "__dry_run": dry}


def test_campaign_calls_table_exists():
    app.query_db("SELECT automation_id, audience_table, audience_id, phone, vapi_call_id FROM campaign_calls LIMIT 1")


def test_campaign_killswitch_off():
    os.environ.pop("OUTBOUND_CALLING_ENABLED", None)
    out = vapi_mod._run_outbound_campaign({"assistant_id": "a", "phone_number_id": "p"}, _ctx(0))
    assert out["ok"] is False and "skipped" in out


def test_campaign_requires_key_and_allowlists_table():
    os.environ["OUTBOUND_CALLING_ENABLED"] = "1"
    os.environ.pop("VAPI_PRIVATE_KEY", None)
    os.environ.pop("VAPI_API_KEY", None)
    try:
        out = vapi_mod._run_outbound_campaign({"assistant_id": "a", "phone_number_id": "p"}, _ctx(0))
        assert out["ok"] is False and "VAPI_PRIVATE_KEY" in out["error"]
        os.environ["VAPI_PRIVATE_KEY"] = "vp"
        bad = vapi_mod._run_outbound_campaign(
            {"assistant_id": "a", "phone_number_id": "p", "audience_table": "secrets",
             "call_start_hour": 0, "call_end_hour": 24}, _ctx(0))
        assert bad["ok"] is False and "audience_table" in bad["error"]
    finally:
        os.environ.pop("OUTBOUND_CALLING_ENABLED", None)
        os.environ.pop("VAPI_PRIVATE_KEY", None)


def test_campaign_outside_hours_skips():
    os.environ["OUTBOUND_CALLING_ENABLED"] = "1"
    os.environ["VAPI_PRIVATE_KEY"] = "vp"
    try:
        out = vapi_mod._run_outbound_campaign(
            {"assistant_id": "a", "phone_number_id": "p", "audience_table": "leads",
             "call_start_hour": 0, "call_end_hour": 0}, _ctx(0))   # start==end → never within
        assert out["ok"] is True and "skipped" in out and out["calls_placed"] == 0
    finally:
        os.environ.pop("OUTBOUND_CALLING_ENABLED", None)
        os.environ.pop("VAPI_PRIVATE_KEY", None)


def test_campaign_dry_run_real_and_dedup():
    os.environ["OUTBOUND_CALLING_ENABLED"] = "1"
    os.environ["VAPI_PRIVATE_KEY"] = "vp"
    aid = 778001
    status = "zzcamptest"   # unique status so ONLY our lead matches (dedup assertions stay exact)
    app.execute_db("DELETE FROM leads WHERE email='campaigntest@example.test'")
    app.execute_db("DELETE FROM campaign_calls WHERE automation_id=%s", (aid,))
    lead = app.execute_db("INSERT INTO leads (tenant_id, name, email, phone, status) "
                          "VALUES (1,'CT','campaigntest@example.test','+15551230000',%s) RETURNING id", (status,))
    lid = lead["id"]
    orig = vapi_mod._vapi_post
    vapi_mod._vapi_post = lambda path, body: {"id": "vc_camp_1"}
    cfg = {"assistant_id": "asst", "phone_number_id": "pn", "audience_table": "leads",
           "status_filter": status, "call_start_hour": 0, "call_end_hour": 24, "max_calls_per_run": 50}
    try:
        # dry run → reports the target, dials no one, writes no campaign_calls row
        dry = vapi_mod._run_outbound_campaign(cfg, _ctx(aid, dry=True))
        assert dry["ok"] is True and dry.get("dry_run") is True and dry["would_call"] == 1
        assert app.query_db("SELECT COUNT(*) AS n FROM campaign_calls WHERE automation_id=%s",
                            (aid,), fetchone=True)["n"] == 0
        # real run → places the call + logs campaign_calls + voice_calls
        real = vapi_mod._run_outbound_campaign(cfg, _ctx(aid))
        assert real["ok"] is True and real["calls_placed"] == 1
        assert app.query_db("SELECT COUNT(*) AS n FROM campaign_calls WHERE automation_id=%s AND audience_id=%s",
                            (aid, lid), fetchone=True)["n"] == 1
        assert app.query_db("SELECT COUNT(*) AS n FROM voice_calls WHERE vapi_call_id='vc_camp_1' AND direction='outbound'",
                            fetchone=True)["n"] >= 1
        # second run → deduped (already called → not re-dialed)
        again = vapi_mod._run_outbound_campaign(cfg, _ctx(aid))
        assert again["calls_placed"] == 0
    finally:
        vapi_mod._vapi_post = orig
        os.environ.pop("OUTBOUND_CALLING_ENABLED", None)
        os.environ.pop("VAPI_PRIVATE_KEY", None)
        app.execute_db("DELETE FROM campaign_calls WHERE automation_id=%s", (aid,))
        app.execute_db("DELETE FROM voice_calls WHERE vapi_call_id='vc_camp_1'")
        app.execute_db("DELETE FROM leads WHERE id=%s", (lid,))
