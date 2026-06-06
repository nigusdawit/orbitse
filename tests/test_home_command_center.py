"""Task 094 (gap §1) — Home command center. Embedded Postgres (no mocks).

P0: avg_lead_score surfaced on /admin/api/overview/stats.
(P1 needs-attention, P2 activity-feed, P3 revenue-by-source appended as built.)
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    return c


def test_stats_includes_avg_lead_score():
    c = _sa()
    app.execute_db(
        "INSERT INTO visitor_profiles (tenant_id, visitor_id, lead_score) "
        "VALUES (1, %s, 40), (1, %s, 80) "
        "ON CONFLICT (tenant_id, visitor_id) DO UPDATE SET lead_score = EXCLUDED.lead_score",
        ("hc-avg-a", "hc-avg-b"))
    try:
        true_avg = app.query_db(
            "SELECT AVG(lead_score) AS a FROM visitor_profiles WHERE lead_score > 0",
            fetchone=True)["a"]
        j = c.get("/admin/api/overview/stats").get_json()
        assert "avg_lead_score" in j
        assert j["avg_lead_score"] == int(round(float(true_avg)))
        assert j["avg_lead_score"] > 0          # we just seeded scored profiles
    finally:
        app.execute_db("DELETE FROM visitor_profiles WHERE visitor_id IN (%s,%s)",
                       ("hc-avg-a", "hc-avg-b"))


# ---- P1: GET /admin/api/overview/attention ----

def test_attention_lists_items_for_super():
    c = _sa()
    # hot uncontacted lead: >1h old, profile lead_score >= threshold
    app.execute_db("INSERT INTO leads (tenant_id, name, status, visitor_id, created_at) "
                   "VALUES (1, %s, 'new', %s, NOW() - INTERVAL '2 hours')",
                   ("Attn Hot Lead", "attn-hot-vid"))
    app.execute_db("INSERT INTO visitor_profiles (tenant_id, visitor_id, lead_score) VALUES (1, %s, 85) "
                   "ON CONFLICT (tenant_id, visitor_id) DO UPDATE SET lead_score=85", ("attn-hot-vid",))
    app.execute_db("INSERT INTO pages (slug, title, enabled) VALUES (%s, %s, FALSE) "
                   "ON CONFLICT (slug) DO UPDATE SET enabled=FALSE", ("attn-draft-page", "Attn Draft"))
    try:
        j = c.get("/admin/api/overview/attention").get_json()
        assert j["ok"] is True and isinstance(j["items"], list)
        kinds = {it["kind"]: it for it in j["items"]}
        assert "hot_leads_uncontacted" in kinds and kinds["hot_leads_uncontacted"]["count"] >= 1
        assert kinds["hot_leads_uncontacted"]["tab"] == "crm"
        assert "draft_content" in kinds and kinds["draft_content"]["count"] >= 1
    finally:
        app.execute_db("DELETE FROM leads WHERE visitor_id=%s", ("attn-hot-vid",))
        app.execute_db("DELETE FROM visitor_profiles WHERE visitor_id=%s", ("attn-hot-vid",))
        app.execute_db("DELETE FROM pages WHERE slug=%s", ("attn-draft-page",))


def test_attention_requires_super_admin():
    r = app.app.test_client().get("/admin/api/overview/attention")
    assert r.status_code in (401, 403, 302)
    if not CLIENT_PW:
        return
    cc = app.app.test_client()
    cc.post("/admin/login", data={"password": CLIENT_PW})
    with cc.session_transaction() as s:
        s["_csrf_token"] = "t"
    assert cc.get("/admin/api/overview/attention").status_code == 403
