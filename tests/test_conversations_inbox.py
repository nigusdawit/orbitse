"""Task 095 (gap §2.4) — Conversations inbox. Embedded Postgres (no mocks).

P1 backend: the conversation_takeover table (bootstrap + migration 0035), the additive
chat-history list columns, and the super-admin context endpoint.
(P2 takeover, P3 visitor delivery appended as built.)
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


def test_takeover_table_exists():
    # proves the bootstrap + migration created it (SELECT errors if missing)
    app.query_db("SELECT conversation_id, ai_paused, taken_over_by FROM conversation_takeover LIMIT 1")


def test_chat_history_has_additive_columns():
    c = _sa()
    conv = app.execute_db("INSERT INTO chat_conversations (session_id, visitor_id) VALUES (%s, %s) RETURNING id",
                          ("ci-sess-1", "ci-vid-1"))
    cid = conv["id"]
    app.execute_db("INSERT INTO chat_messages (conversation_id, role, content) VALUES (%s, 'user', 'hi')", (cid,))
    try:
        j = c.get("/admin/api/chat-history").get_json()
        row = next((r for r in (j.get("conversations") or []) if r.get("id") == cid), None)
        assert row is not None
        assert "ai_paused" in row and row["ai_paused"] in (False, True)   # additive
        assert "last_role" in row and "last_message_at" in row
        assert "message_count" in row and "first_message" in row          # legacy keys intact
    finally:
        app.execute_db("DELETE FROM chat_conversations WHERE id=%s", (cid,))


def test_context_endpoint_shape_and_super_gate():
    c = _sa()
    conv = app.execute_db("INSERT INTO chat_conversations (session_id, visitor_id) VALUES (%s, %s) RETURNING id",
                          ("ci-sess-ctx", "ci-vid-ctx"))
    cid = conv["id"]
    app.execute_db("INSERT INTO visitor_profiles (tenant_id, visitor_id, lead_score, summary) VALUES (1, %s, 77, %s) "
                   "ON CONFLICT (tenant_id, visitor_id) DO UPDATE SET lead_score=77",
                   ("ci-vid-ctx", "Interested visitor"))
    app.execute_db("INSERT INTO leads (tenant_id, name, visitor_id) VALUES (1, %s, %s)", ("Ctx Lead", "ci-vid-ctx"))
    app.execute_db("INSERT INTO page_views (session_id, visitor_id, page_url, utm_source) VALUES (%s, %s, '/', 'google')",
                   ("ci-sess-ctx", "ci-vid-ctx"))
    try:
        j = c.get("/admin/api/conversations/%d/context" % cid).get_json()
        assert j["ok"] is True
        assert j["profile"] and j["profile"]["lead_score"] == 77
        assert "UTM: google" in j["source"]
        assert j["lead"] and j["lead"]["name"] == "Ctx Lead"
        if CLIENT_PW:
            cc = app.app.test_client()
            cc.post("/admin/login", data={"password": CLIENT_PW})
            with cc.session_transaction() as s:
                s["_csrf_token"] = "t"
            assert cc.get("/admin/api/conversations/%d/context" % cid).status_code == 403
    finally:
        app.execute_db("DELETE FROM chat_conversations WHERE id=%s", (cid,))
        app.execute_db("DELETE FROM visitor_profiles WHERE visitor_id=%s", ("ci-vid-ctx",))
        app.execute_db("DELETE FROM leads WHERE visitor_id=%s", ("ci-vid-ctx",))
        app.execute_db("DELETE FROM page_views WHERE visitor_id=%s", ("ci-vid-ctx",))
