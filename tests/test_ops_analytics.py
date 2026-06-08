"""Task 099 — Growth & ops analytics. Embedded Postgres (no mocks).

Dev-health KPIs (§6.4), CSV export (§6.5), campaign analytics (§5.1/5.2). Super-admin only.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    return c


def test_dev_health_shape():
    j = _sa().get("/admin/api/dev-health").get_json()
    for k in ("error_24h", "db_size_bytes", "uptime_seconds", "p95_latency_ms"):
        assert k in j
    assert j["db_size_bytes"] is None or j["db_size_bytes"] > 0   # a real PG db has size
    assert j["uptime_seconds"] is None or j["uptime_seconds"] >= 0


def test_csv_export_whitelist_and_download():
    c = _sa()
    app.execute_db("INSERT INTO leads (tenant_id, name) VALUES (1, 'CSV Person')")
    try:
        r = c.get("/admin/api/export/leads.csv")
        assert r.status_code == 200 and "text/csv" in r.headers.get("Content-Type", "")
        body = r.get_data(as_text=True)
        assert "name" in body.splitlines()[0]   # header row
        assert "CSV Person" in body
        # non-whitelisted tables are rejected (incl. anything sensitive)
        assert c.get("/admin/api/export/secrets.csv").status_code == 400
        assert c.get("/admin/api/export/pg_user.csv").status_code == 400
    finally:
        app.execute_db("DELETE FROM leads WHERE name='CSV Person'")


def test_campaign_stats_shape_and_rates():
    c = _sa()
    camp = app.execute_db("INSERT INTO messaging_campaigns (name, channel, status) "
                          "VALUES ('CS Test','email','sent') RETURNING id")
    cid = camp["id"]
    app.execute_db("INSERT INTO messaging_log (campaign_id, status, opened_at, clicked_at) "
                   "VALUES (%s,'sent',NOW(),NOW())", (cid,))
    app.execute_db("INSERT INTO messaging_log (campaign_id, status) VALUES (%s,'sent')", (cid,))
    try:
        j = c.get("/admin/api/campaign-stats").get_json()
        assert "kpis" in j and "campaigns" in j
        row = next((x for x in j["campaigns"] if x["id"] == cid), None)
        assert row and row["sent"] == 2 and row["opens"] == 1 and row["clicks"] == 1
        assert row["open_rate"] == 50.0 and row["click_rate"] == 50.0
    finally:
        app.execute_db("DELETE FROM messaging_log WHERE campaign_id=%s", (cid,))
        app.execute_db("DELETE FROM messaging_campaigns WHERE id=%s", (cid,))


def test_ops_super_gate():
    if not CLIENT_PW:
        return
    cc = app.app.test_client()
    cc.post("/admin/login", data={"password": CLIENT_PW})
    assert cc.get("/admin/api/dev-health").status_code == 403
    assert cc.get("/admin/api/export/leads.csv").status_code == 403
    assert cc.get("/admin/api/campaign-stats").status_code == 403
