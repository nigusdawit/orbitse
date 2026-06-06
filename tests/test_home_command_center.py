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
