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


# ---- P2: GET /admin/api/activity-feed ----

def test_activity_feed_merges_sources_and_hides_secrets():
    c = _sa()
    app.execute_db("INSERT INTO orders (order_number, total_cents, customer_email, status) "
                   "VALUES (%s, 8400, %s, 'paid') ON CONFLICT (order_number) DO NOTHING",
                   ("AF-PROBE-1", "af@probe.test"))
    app.execute_db("INSERT INTO leads (tenant_id, name) VALUES (1, %s)", ("AF Probe Lead",))
    app.execute_db("INSERT INTO meetings (tenant_id, name) VALUES (1, %s)", ("AF Probe Meeting",))
    app.execute_db("INSERT INTO admin_setting_snapshots (table_name, row_id, snapshot_json) "
                   "VALUES ('pages', 1, %s::jsonb)", ('{"secret":"SNAPSHOT_SENTINEL"}',))
    app.execute_db("INSERT INTO ai_activity_log (tenant_id, status, model, final_answer, user_message) "
                   "VALUES (1, 'error', 'gpt-4o', %s, %s)", ("ANSWER_SENTINEL", "USERMSG_SENTINEL"))
    try:
        r = c.get("/admin/api/activity-feed?limit=50")
        assert r.status_code == 200
        raw = r.get_data(as_text=True)
        evs = r.get_json()["events"]
        kinds = set(e["kind"] for e in evs)
        for k in ("order", "lead", "meeting", "page_edit", "ai_event"):
            assert k in kinds, (k, kinds)
        ts = [e["ts"] for e in evs if e.get("ts")]
        assert ts == sorted(ts, reverse=True)            # reverse-chron
        # secret/PII blobs must NOT be echoed
        assert "SNAPSHOT_SENTINEL" not in raw
        assert "ANSWER_SENTINEL" not in raw
        assert "USERMSG_SENTINEL" not in raw
        assert "snapshot_json" not in raw and "final_answer" not in raw
        # ?kinds filter
        jf = c.get("/admin/api/activity-feed?kinds=order").get_json()
        assert jf["events"] and all(e["kind"] == "order" for e in jf["events"])
    finally:
        app.execute_db("DELETE FROM orders WHERE order_number=%s", ("AF-PROBE-1",))
        app.execute_db("DELETE FROM leads WHERE name=%s", ("AF Probe Lead",))
        app.execute_db("DELETE FROM meetings WHERE name=%s", ("AF Probe Meeting",))
        app.execute_db("DELETE FROM admin_setting_snapshots "
                       "WHERE table_name='pages' AND snapshot_json->>'secret' = 'SNAPSHOT_SENTINEL'")
        app.execute_db("DELETE FROM ai_activity_log WHERE final_answer=%s", ("ANSWER_SENTINEL",))


def test_activity_feed_requires_super_admin():
    r = app.app.test_client().get("/admin/api/activity-feed")
    assert r.status_code in (401, 403, 302)
    if not CLIENT_PW:
        return
    cc = app.app.test_client()
    cc.post("/admin/login", data={"password": CLIENT_PW})
    with cc.session_transaction() as s:
        s["_csrf_token"] = "t"
    assert cc.get("/admin/api/activity-feed").status_code == 403


# ---- P3: GET /admin/api/overview/revenue-by-source ----

def test_revenue_by_source_real_modules():
    c = _sa()
    app.execute_db("INSERT INTO orders (order_number, total_cents, status) VALUES (%s, 10000, 'paid') "
                   "ON CONFLICT (order_number) DO NOTHING", ("REV-PROBE-1",))
    app.execute_db("INSERT INTO service_bookings (booking_token, client_name, client_email, "
                   "amount_paid_cents, payment_status) VALUES (%s, %s, %s, 20000, 'paid') "
                   "ON CONFLICT (booking_token) DO NOTHING", ("rev-tok-1", "Rev Client", "rev@probe.test"))
    try:
        j = c.get("/admin/api/overview/revenue-by-source?range=7d").get_json()
        assert j["ok"] is True
        by_key = {s["key"]: s for s in j["sources"]}
        assert {"store", "bookings", "events"} <= set(by_key.keys()), by_key   # real modules only
        assert by_key["store"]["revenue"] >= 100.0
        assert by_key["bookings"]["revenue"] >= 200.0
        assert abs(j["total"] - round(sum(s["revenue"] for s in j["sources"]), 2)) < 0.01  # total == sum
        assert c.get("/admin/api/overview/revenue-by-source?range=all").status_code == 200
        assert c.get("/admin/api/overview/revenue-by-source?range=30d").status_code == 200
    finally:
        app.execute_db("DELETE FROM orders WHERE order_number=%s", ("REV-PROBE-1",))
        app.execute_db("DELETE FROM service_bookings WHERE booking_token=%s", ("rev-tok-1",))


def test_revenue_requires_super_admin():
    r = app.app.test_client().get("/admin/api/overview/revenue-by-source")
    assert r.status_code in (401, 403, 302)
    if not CLIENT_PW:
        return
    cc = app.app.test_client()
    cc.post("/admin/login", data={"password": CLIENT_PW})
    with cc.session_transaction() as s:
        s["_csrf_token"] = "t"
    assert cc.get("/admin/api/overview/revenue-by-source").status_code == 403
