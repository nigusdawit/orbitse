"""Integration tests for AI Activity persistence (task 031), embedded Postgres.

A turn (even one that errors on a missing LLM key) writes an ai_activity_log row
via the obs DB sink; the super-admin can list it; a client is 403'd.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _login(c, pw):
    return c.post("/admin/login", data={"password": pw})


def _csrf(c):
    with c.session_transaction() as s:
        s["_csrf_token"] = "tok"
    return {"X-CSRF-Token": "tok"}


def test_turn_writes_activity_row_and_super_admin_can_list():
    before = app.query_db("SELECT COUNT(*) AS n FROM ai_activity_log", fetchone=True)["n"]
    c = app.app.test_client(); _login(c, ADMIN_PW); h = _csrf(c)
    # Drive one admin turn (it will error on the missing key, but the obs sink
    # still records the turn — that's the point: every turn is logged).
    c.post("/admin/api/chat/send",
           json={"session_id": "act-1", "message": "what tables exist?"}, headers=h)
    after = app.query_db("SELECT COUNT(*) AS n FROM ai_activity_log", fetchone=True)["n"]
    assert after == before + 1, (before, after)

    r = c.get("/admin/api/ai-activity?limit=10")
    assert r.status_code == 200
    body = r.get_json()
    assert body["activity"], "expected at least one activity row"
    row = body["activity"][0]
    assert row["session_id"] == "act-1"
    assert "user_message" in row and row["user_message"]
    assert "stats" in body and body["stats"]["count"] >= 1


def test_client_cannot_view_activity():
    cl = app.app.test_client(); _login(cl, CLIENT_PW)
    assert cl.get("/admin/api/ai-activity").status_code == 403


def test_activity_logging_can_be_disabled_live():
    sa = app.app.test_client(); _login(sa, ADMIN_PW); h = _csrf(sa)
    sa.put("/admin/api/ai-control/activity_logging_enabled",
           json={"value": False}, headers=h)
    app._invalidate_ai_control()
    try:
        before = app.query_db("SELECT COUNT(*) AS n FROM ai_activity_log", fetchone=True)["n"]
        c = app.app.test_client(); _login(c, ADMIN_PW); ch = _csrf(c)
        c.post("/admin/api/chat/send",
               json={"session_id": "act-off", "message": "hi"}, headers=ch)
        after = app.query_db("SELECT COUNT(*) AS n FROM ai_activity_log", fetchone=True)["n"]
        assert after == before, "logging disabled → no new row"
    finally:
        app.reset_ai_setting("activity_logging_enabled")
        app._invalidate_ai_control()
