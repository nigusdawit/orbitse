"""Task 101 leftovers — Concierge/Grow. Embedded Postgres (no mocks).

Covers three additive, fail-open features:
  §3.5 handoff escalation  — the escalation_enabled AI Control knob + the
                             _compose_escalation_paragraph prompt addition (off by default).
  §3.2 greeting auto-open  — chatbot_settings.auto_open_seconds (migration 0038): the
                             column round-trips, both the admin GET and the public GET
                             surface it, and the admin PUT clamps the value to 0..600.
  §5.4 review auto-trigger — a 'completed' meeting older than auto_send_days gets a queued
                             review_request, and re-running the sweep does NOT duplicate it.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")

# State-changing admin requests need the CSRF header; _sa() seeds the session
# token to "t", so every admin PUT in this module sends the matching header.
_CSRF = {"X-CSRF-Token": "t"}


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    return c


# --- §3.5 handoff escalation -------------------------------------------------

def test_escalation_knob_in_registry_and_paragraph_toggle():
    c = _sa()
    keys = {s["key"] for s in (c.get("/admin/api/ai-control").get_json().get("settings") or [])}
    assert "escalation_enabled" in keys                 # registry-driven knob auto-surfaced
    assert app.get_ai_setting("escalation_enabled") is False   # off by default

    app.reset_ai_setting("escalation_enabled")
    assert app._compose_escalation_paragraph() == ""    # off → visitor prompt unchanged
    try:
        app.set_ai_setting("escalation_enabled", "yes")
        para = app._compose_escalation_paragraph()
        assert para.strip() and "HUMAN HANDOFF" in para  # on → handoff guidance appended
    finally:
        app.reset_ai_setting("escalation_enabled")
    assert app._compose_escalation_paragraph() == ""


# --- §3.2 greeting auto-open -------------------------------------------------

def test_auto_open_column_exposed_admin_and_public():
    # The migration added the column; set it directly and confirm both read paths surface it.
    app.execute_db(
        "INSERT INTO chatbot_settings (id, enabled, auto_open_seconds) VALUES (1, TRUE, 9) "
        "ON CONFLICT (id) DO UPDATE SET enabled=TRUE, auto_open_seconds=9"
    )
    try:
        # admin GET (full row)
        assert _sa().get("/admin/api/chatbot-settings").get_json().get("auto_open_seconds") == 9
        # public GET (unauthenticated widget config)
        pub = app.app.test_client().get("/api/chatbot-settings").get_json()
        assert pub.get("auto_open_seconds") == 9
    finally:
        app.execute_db("UPDATE chatbot_settings SET auto_open_seconds=0 WHERE id=1")


def test_auto_open_admin_save_clamps():
    c = _sa()
    app.execute_db("INSERT INTO chatbot_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    # Echo the current row back so the full-row PUT changes ONLY auto_open_seconds.
    cur = app.query_db("SELECT * FROM chatbot_settings WHERE id=1", fetchone=True) or {}
    payload = {
        "enabled": cur.get("enabled", True),
        "mode": cur.get("mode") or "builtin",
        "agent_name": cur.get("agent_name") or "",
        "agent_role": cur.get("agent_role") or "",
        "agent_avatar": cur.get("agent_avatar") or "",
        "greeting": cur.get("greeting") or "",
        "quick_prompts": cur.get("quick_prompts") or [],
        "api_endpoint": cur.get("api_endpoint") or "/api/chat",
        "embed_code": cur.get("embed_code") or "",
        "agent_scope_tightness": cur.get("agent_scope_tightness") or "balanced",
        "system_prompt": cur.get("system_prompt") or "",
        "brand_voice": cur.get("brand_voice") or "",
        "theme": cur.get("theme") or {},
    }
    try:
        # over the ceiling → clamped to 600
        assert c.put("/admin/api/chatbot-settings", headers=_CSRF,
                     json={**payload, "auto_open_seconds": 9999}).status_code == 200
        assert app.query_db("SELECT auto_open_seconds FROM chatbot_settings WHERE id=1",
                            fetchone=True)["auto_open_seconds"] == 600
        # a valid value stores as-is
        c.put("/admin/api/chatbot-settings", headers=_CSRF, json={**payload, "auto_open_seconds": 8})
        assert app.query_db("SELECT auto_open_seconds FROM chatbot_settings WHERE id=1",
                            fetchone=True)["auto_open_seconds"] == 8
        # garbage coerces to 0 (never raises)
        c.put("/admin/api/chatbot-settings", headers=_CSRF, json={**payload, "auto_open_seconds": "abc"})
        assert app.query_db("SELECT auto_open_seconds FROM chatbot_settings WHERE id=1",
                            fetchone=True)["auto_open_seconds"] == 0
    finally:
        app.execute_db("UPDATE chatbot_settings SET auto_open_seconds=0 WHERE id=1")


# --- §5.4 review auto-trigger for completed meetings -------------------------

def test_completed_meeting_queues_review_once():
    dest = app.execute_db(
        "INSERT INTO review_destinations (name, kind, auto_send, auto_send_days) "
        "VALUES ('Test Dest', 'internal', TRUE, 3) RETURNING id"
    )
    did = dest["id"]
    mt = app.execute_db(
        "INSERT INTO meetings (name, email, phone, status, notes, updated_at) "
        "VALUES ('Pat', 'pat@example.com', '', 'completed', 'kitchen consult', NOW() - INTERVAL '10 days') "
        "RETURNING id"
    )
    mid = mt["id"]

    def _count():
        return app.query_db(
            "SELECT COUNT(*) AS n FROM review_requests "
            "WHERE source_kind='meeting' AND source_id=%s AND destination_id=%s",
            (mid, did), fetchone=True,
        )["n"]

    try:
        app._auto_trigger_completed_orders()
        assert _count() == 1                       # queued for the completed meeting
        app._auto_trigger_completed_orders()
        assert _count() == 1                       # idempotent — the NOT EXISTS guard holds
        # a meeting that is NOT completed is never queued
        open_mt = app.execute_db(
            "INSERT INTO meetings (name, email, status, updated_at) "
            "VALUES ('Open', 'open@example.com', 'requested', NOW() - INTERVAL '10 days') RETURNING id"
        )
        app._auto_trigger_completed_orders()
        assert app.query_db(
            "SELECT COUNT(*) AS n FROM review_requests WHERE source_kind='meeting' AND source_id=%s",
            (open_mt["id"],), fetchone=True,
        )["n"] == 0
    finally:
        app.execute_db("DELETE FROM review_requests WHERE source_kind='meeting' AND source_id IN "
                       "(SELECT id FROM meetings WHERE email IN ('pat@example.com','open@example.com'))")
        app.execute_db("DELETE FROM meetings WHERE email IN ('pat@example.com','open@example.com')")
        app.execute_db("DELETE FROM review_destinations WHERE id=%s", (did,))
