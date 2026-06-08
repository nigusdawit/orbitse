"""Task 097 (gap §2.1–2.3, 2.8) — CRM People cluster. Embedded Postgres (no mocks).

Covers the unified Contacts endpoint (leads ⋈ visitor_profiles + profile-only people,
deduped), the headline KPIs, and the Convert→customer action (both the lead_id and the
profile-only visitor_id paths). Super-admin gating asserted.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")
_CSRF = {"X-CSRF-Token": "t"}


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    return c


def test_contacts_merge_dedup_and_shape():
    c = _sa()
    # visitor A: has BOTH a lead and a profile → ONE merged row (kind=lead, score from profile)
    app.execute_db("INSERT INTO leads (tenant_id, name, visitor_id, status) VALUES (1,'Alice','cc-a','new')")
    app.execute_db("INSERT INTO visitor_profiles (tenant_id, visitor_id, lead_score) VALUES (1,'cc-a',85) "
                   "ON CONFLICT (tenant_id, visitor_id) DO UPDATE SET lead_score=85")
    # visitor B: profile only (no lead) → a profile contact, interest from interests[0]
    app.execute_db("INSERT INTO visitor_profiles (tenant_id, visitor_id, lead_score, interests) "
                   "VALUES (1,'cc-b',60,%s::jsonb) ON CONFLICT (tenant_id, visitor_id) DO UPDATE SET lead_score=60",
                   ('["pricing"]',))
    # lead C: no profile → lead_score 0
    app.execute_db("INSERT INTO leads (tenant_id, name, visitor_id, status) VALUES (1,'Carol','cc-c','contacted')")
    try:
        j = c.get("/admin/api/contacts").get_json()
        by_vid = {r.get("visitor_id"): r for r in j["contacts"]}
        a, b, cc = by_vid.get("cc-a"), by_vid.get("cc-b"), by_vid.get("cc-c")
        assert a and a["kind"] == "lead" and a["lead_score"] == 85 and a["name"] == "Alice"
        assert b and b["kind"] == "profile" and b["lead_score"] == 60 and b["interest"] == "pricing"
        assert cc and cc["kind"] == "lead" and cc["lead_score"] == 0
        # dedup: a visitor with both a lead AND a profile appears exactly once
        assert sum(1 for r in j["contacts"] if r.get("visitor_id") == "cc-a") == 1
    finally:
        app.execute_db("DELETE FROM leads WHERE visitor_id IN ('cc-a','cc-c')")
        app.execute_db("DELETE FROM visitor_profiles WHERE visitor_id IN ('cc-a','cc-b')")


def test_contacts_stats_shape():
    c = _sa()
    app.execute_db("INSERT INTO leads (tenant_id, name, visitor_id, status) VALUES (1,'Open1','cc-st-open','new')")
    app.execute_db("INSERT INTO leads (tenant_id, name, status, updated_at) VALUES (1,'WonNow','won', NOW())")
    app.execute_db("INSERT INTO visitor_profiles (tenant_id, visitor_id, lead_score) VALUES (1,'cc-st-hot',90) "
                   "ON CONFLICT (tenant_id, visitor_id) DO UPDATE SET lead_score=90")
    try:
        st = c.get("/admin/api/contacts").get_json()["stats"]
        for k in ("open", "hot", "avg_age_days", "won_this_month"):
            assert k in st and isinstance(st[k], int)
        assert st["open"] >= 1            # the open lead we seeded
        assert st["hot"] >= 1             # the lead_score>=80 profile
        assert st["won_this_month"] >= 1  # the won-now lead
    finally:
        app.execute_db("DELETE FROM leads WHERE visitor_id='cc-st-open' OR (name='WonNow' AND status='won')")
        app.execute_db("DELETE FROM visitor_profiles WHERE visitor_id='cc-st-hot'")


def test_convert_lead_to_customer():
    c = _sa()
    row = app.execute_db("INSERT INTO leads (tenant_id, name, status) VALUES (1,'Conv','new') RETURNING id")
    lid = row["id"]
    try:
        r = c.post("/admin/api/contacts/convert", json={"lead_id": lid}, headers=_CSRF)
        assert r.status_code == 200 and r.get_json()["status"] == "won"
        assert app.query_db("SELECT status FROM leads WHERE id=%s", (lid,), fetchone=True)["status"] == "won"
        # 404 for a missing lead
        assert c.post("/admin/api/contacts/convert", json={"lead_id": 99999999}, headers=_CSRF).status_code == 404
    finally:
        app.execute_db("DELETE FROM leads WHERE id=%s", (lid,))


def test_convert_profile_creates_won_lead():
    c = _sa()
    app.execute_db("INSERT INTO visitor_profiles (tenant_id, visitor_id, lead_score, interests, summary) "
                   "VALUES (1,'cc-conv',70,%s::jsonb,%s) ON CONFLICT (tenant_id, visitor_id) DO UPDATE SET lead_score=70",
                   ('["demo"]', "wants a demo"))
    try:
        r = c.post("/admin/api/contacts/convert", json={"visitor_id": "cc-conv"}, headers=_CSRF)
        assert r.status_code == 200
        j = r.get_json()
        assert j["status"] == "won" and j.get("created") is True and j["lead_id"]
        lead = app.query_db("SELECT status, visitor_id, interest FROM leads WHERE id=%s", (j["lead_id"],), fetchone=True)
        assert lead["status"] == "won" and lead["visitor_id"] == "cc-conv" and lead["interest"] == "demo"
        # empty body → 400 (not a 5xx)
        assert c.post("/admin/api/contacts/convert", json={}, headers=_CSRF).status_code == 400
    finally:
        app.execute_db("DELETE FROM leads WHERE visitor_id='cc-conv'")
        app.execute_db("DELETE FROM visitor_profiles WHERE visitor_id='cc-conv'")


def test_contacts_super_admin_gated():
    if not CLIENT_PW:
        return
    cc = app.app.test_client()
    cc.post("/admin/login", data={"password": CLIENT_PW})
    with cc.session_transaction() as s:
        s["_csrf_token"] = "t"
    assert cc.get("/admin/api/contacts").status_code == 403
    assert cc.post("/admin/api/contacts/convert", json={"lead_id": 1}, headers=_CSRF).status_code == 403
