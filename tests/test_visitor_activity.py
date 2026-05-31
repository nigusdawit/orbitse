"""Task 034 — visitor turns are tracked in ai_activity_log (surface='visitor').

Embedded Postgres. A visitor /api/chat turn (errors on the missing LLM key, but
the finally still logs it) writes a surface='visitor' row; the activity API
filters by surface; the surface column exists via the migration chain.
"""
import os
import json

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    return c


def test_surface_column_exists():
    row = app.query_db(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='ai_activity_log' AND column_name='surface'",
        fetchone=True)
    assert row is not None


def test_visitor_turn_logs_a_visitor_surface_row():
    before = app.query_db(
        "SELECT COUNT(*) AS n FROM ai_activity_log WHERE surface='visitor'",
        fetchone=True)["n"]
    c = app.app.test_client()
    # Public endpoint — no auth. Drains the SSE stream so generate() runs to its
    # finally (which logs the activity row).
    r = c.post("/api/chat", json={"session_id": "vis-1", "message": "hello there"})
    assert r.status_code == 200
    _ = r.get_data(as_text=True)  # drain the stream
    after = app.query_db(
        "SELECT COUNT(*) AS n FROM ai_activity_log WHERE surface='visitor'",
        fetchone=True)["n"]
    assert after == before + 1, (before, after)
    row = app.query_db(
        "SELECT surface, session_id, user_message FROM ai_activity_log "
        "WHERE surface='visitor' ORDER BY id DESC LIMIT 1", fetchone=True)
    assert row["surface"] == "visitor"
    assert row["session_id"] == "vis-1"
    assert row["user_message"]  # question captured (redacted if enabled)


def test_activity_api_surface_filter():
    sa = _sa()
    # 'visitor' filter returns only visitor rows.
    r = sa.get("/admin/api/ai-activity?surface=visitor&limit=50")
    assert r.status_code == 200
    for row in r.get_json()["activity"]:
        assert row["surface"] == "visitor"
    # 'admin' filter returns only admin rows (may be empty — that's fine).
    r2 = sa.get("/admin/api/ai-activity?surface=admin&limit=50")
    assert r2.status_code == 200
    for row in r2.get_json()["activity"]:
        assert row["surface"] == "admin"


def test_admin_and_visitor_both_logged_distinctly():
    # An admin turn → surface 'admin'; a visitor turn → surface 'visitor'.
    sa = _sa()
    with sa.session_transaction() as s:
        s["_csrf_token"] = "tok"
    sa.post("/admin/api/chat/send",
            json={"session_id": "adm-x", "message": "hi"},
            headers={"X-CSRF-Token": "tok"})
    app.app.test_client().post("/api/chat",
                               json={"session_id": "vis-x", "message": "hi"})
    counts = app.query_db(
        "SELECT surface, COUNT(*) AS n FROM ai_activity_log GROUP BY surface") or []
    by = {r["surface"]: r["n"] for r in counts}
    assert by.get("admin", 0) >= 1 and by.get("visitor", 0) >= 1, by
