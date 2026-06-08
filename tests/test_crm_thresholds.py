"""Task 100 (gap §2.7) — configurable CRM segment thresholds. Embedded PG (no mocks).

crm_hot_min / crm_warm_min are super-admin AI-Control knobs; the Contacts endpoint
returns them + uses crm_hot_min for the 'hot' KPI.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    return c


def test_thresholds_registered_and_applied():
    c = _sa()
    # registry knobs present with sane defaults
    assert app.get_ai_setting("crm_hot_min") == 80
    assert app.get_ai_setting("crm_warm_min") == 50
    # contacts endpoint echoes the thresholds
    j = c.get("/admin/api/contacts").get_json()
    assert j["thresholds"]["hot"] == 80 and j["thresholds"]["warm"] == 50
    # lower the hot cutoff → endpoint reflects it AND the hot KPI uses it
    app.execute_db("INSERT INTO visitor_profiles (tenant_id, visitor_id, lead_score) VALUES (1,'th-75',75) "
                   "ON CONFLICT (tenant_id, visitor_id) DO UPDATE SET lead_score=75")
    try:
        app.set_ai_setting("crm_hot_min", "70")
        j2 = c.get("/admin/api/contacts").get_json()
        assert j2["thresholds"]["hot"] == 70
        assert j2["stats"]["hot"] >= 1     # the 75-score profile now counts as hot (>=70)
    finally:
        app.reset_ai_setting("crm_hot_min")
        app.execute_db("DELETE FROM visitor_profiles WHERE visitor_id='th-75'")
    assert app.get_ai_setting("crm_hot_min") == 80
