"""Task 095 (gap §2.4) — Conversations inbox. Embedded Postgres (no mocks).

P1 backend: the conversation_takeover table (bootstrap + migration 0035), the additive
chat-history list columns, and the super-admin context endpoint.
(P2 takeover, P3 visitor delivery appended as built.)
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")

# State-changing admin requests need the CSRF header; _sa() seeds the session
# token to "t", so every admin POST in this module sends the matching header.
_CSRF = {"X-CSRF-Token": "t"}


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


# ============================ P2: human takeover ============================

def test_takeover_release_routes():
    c = _sa()
    conv = app.execute_db("INSERT INTO chat_conversations (session_id, visitor_id) VALUES (%s,%s) RETURNING id",
                          ("ci-sess-tk", "ci-vid-tk"))
    cid = conv["id"]
    try:
        r = c.post("/admin/api/conversations/%d/takeover" % cid, headers=_CSRF)
        assert r.status_code == 200 and r.get_json()["ai_paused"] is True
        row = app.query_db("SELECT ai_paused, taken_over_at FROM conversation_takeover WHERE conversation_id=%s",
                           (cid,), fetchone=True)
        assert row and row["ai_paused"] is True and row["taken_over_at"] is not None

        r = c.post("/admin/api/conversations/%d/release" % cid, headers=_CSRF)
        assert r.status_code == 200 and r.get_json()["ai_paused"] is False
        row = app.query_db("SELECT ai_paused, released_at FROM conversation_takeover WHERE conversation_id=%s",
                           (cid,), fetchone=True)
        assert row and row["ai_paused"] is False and row["released_at"] is not None
        # 404 for a non-existent conversation
        assert c.post("/admin/api/conversations/99999999/takeover", headers=_CSRF).status_code == 404
    finally:
        app.execute_db("DELETE FROM chat_conversations WHERE id=%s", (cid,))


def test_human_message_inserts_agent_human_and_pauses():
    c = _sa()
    conv = app.execute_db("INSERT INTO chat_conversations (session_id, visitor_id) VALUES (%s,%s) RETURNING id",
                          ("ci-sess-hm", "ci-vid-hm"))
    cid = conv["id"]
    try:
        r = c.post("/admin/api/conversations/%d/message" % cid, json={"content": "Hi, a human here."}, headers=_CSRF)
        assert r.status_code == 200
        j = r.get_json()
        assert j["ok"] is True and j["ai_paused"] is True and j["id"]
        msg = app.query_db("SELECT role, content FROM chat_messages WHERE conversation_id=%s ORDER BY id DESC LIMIT 1",
                           (cid,), fetchone=True)
        assert msg and msg["role"] == "agent_human" and msg["content"] == "Hi, a human here."
        tk = app.query_db("SELECT ai_paused FROM conversation_takeover WHERE conversation_id=%s", (cid,), fetchone=True)
        assert tk and tk["ai_paused"] is True
        # empty content is rejected (400, not a 5xx)
        assert c.post("/admin/api/conversations/%d/message" % cid, json={"content": "  "}, headers=_CSRF).status_code == 400
    finally:
        app.execute_db("DELETE FROM chat_conversations WHERE id=%s", (cid,))


def test_paused_conversation_gate_skips_ai():
    """The live /api/chat SSE gate: a paused conversation must NOT call the LLM —
    it records the visitor's message + returns paused/done. No API key is needed
    precisely because the gate short-circuits before any model call (so this test
    is hermetic)."""
    c = app.app.test_client()
    sess = "ci-sess-gate"
    conv = app.execute_db("INSERT INTO chat_conversations (session_id, visitor_id) VALUES (%s,%s) RETURNING id",
                          (sess, "ci-vid-gate"))
    cid = conv["id"]
    app.execute_db("INSERT INTO conversation_takeover (conversation_id, ai_paused, taken_over_by, taken_over_at, updated_at) "
                   "VALUES (%s, TRUE, 'test', NOW(), NOW())", (cid,))
    try:
        r = c.post("/api/chat", json={"message": "Are you a human?", "session_id": sess, "visitor_id": "ci-vid-gate"})
        body = r.get_data(as_text=True)
        assert '"paused"' in body, body[:400]
        assert '"done"' in body
        # the visitor's message was persisted by the gate...
        u = app.query_db("SELECT content FROM chat_messages WHERE conversation_id=%s AND role='user' "
                         "ORDER BY id DESC LIMIT 1", (cid,), fetchone=True)
        assert u and u["content"] == "Are you a human?"
        # ...and NO AI assistant message was generated for the gated turn.
        a = app.query_db("SELECT COUNT(*) AS n FROM chat_messages WHERE conversation_id=%s AND role='assistant'",
                         (cid,), fetchone=True)
        assert a["n"] == 0
    finally:
        app.execute_db("DELETE FROM chat_conversations WHERE id=%s", (cid,))
