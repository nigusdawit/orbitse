"""Task 096 (gap §3.3 + §3.4) — AI guardrails. Embedded Postgres (no mocks).

Both knobs are registry-driven AI Control settings (so the UI/API are inherited);
the new logic under test is: compute_today_spend (day-scoped ledger sum), the
DAILY-cap branch in enforce_cost_cap (block when exceeded, fail-open on error),
and _compose_safety_paragraph (prompt-side softening toggle).
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    return c


def _raise(*a, **k):
    raise RuntimeError("boom")


def test_new_knobs_in_registry_and_roundtrip():
    c = _sa()
    j = c.get("/admin/api/ai-control").get_json()
    keys = {s["key"] for s in (j.get("settings") or [])}
    assert "daily_spend_cap_usd" in keys          # §3.3 knob auto-surfaced
    assert "safety_filter_enabled" in keys         # §3.4 knob auto-surfaced
    # defaults (inert / off)
    assert app.get_ai_setting("daily_spend_cap_usd") == 0.0
    assert app.get_ai_setting("safety_filter_enabled") is False
    # typed round-trip via the generic setter
    try:
        assert app.set_ai_setting("daily_spend_cap_usd", "12.5") == 12.5
        assert app.get_ai_setting("daily_spend_cap_usd") == 12.5
        assert app.set_ai_setting("safety_filter_enabled", "yes") is True
        assert app.get_ai_setting("safety_filter_enabled") is True
    finally:
        app.reset_ai_setting("daily_spend_cap_usd")
        app.reset_ai_setting("safety_filter_enabled")
    assert app.get_ai_setting("daily_spend_cap_usd") == 0.0
    assert app.get_ai_setting("safety_filter_enabled") is False
    # a non-super (client) admin cannot read the AI Control surface
    if CLIENT_PW:
        cc = app.app.test_client()
        cc.post("/admin/login", data={"password": CLIENT_PW})
        assert cc.get("/admin/api/ai-control").status_code == 403


def test_compute_today_spend_is_day_scoped():
    before = app.compute_today_spend()["total_usd"]
    app.execute_db("INSERT INTO api_cost_events (tenant_id, session_id, cost_usd, created_at) "
                   "VALUES (1, 'guardrail-today', 1.50, NOW())")
    app.execute_db("INSERT INTO api_cost_events (tenant_id, session_id, cost_usd, created_at) "
                   "VALUES (1, 'guardrail-today', 2.00, NOW() - INTERVAL '2 days')")
    try:
        after = app.compute_today_spend()["total_usd"]
        # only the row dated today counts toward today's spend
        assert round(after - before, 2) == 1.50
    finally:
        app.execute_db("DELETE FROM api_cost_events WHERE session_id='guardrail-today'")


def test_daily_cap_blocks_only_when_exceeded_and_fails_open():
    # 5.00 of spend dated today
    app.execute_db("INSERT INTO api_cost_events (tenant_id, session_id, cost_usd, created_at) "
                   "VALUES (1, 'guardrail-cap', 5.00, NOW())")
    try:
        with app.app.test_request_context("/"):
            # cap OFF (0) → no daily block (falls through to the monthly path → None here)
            app.reset_ai_setting("daily_spend_cap_usd")
            assert app.enforce_cost_cap("visitor_chat") is None

            # cap BELOW today's spend → blocked with a 402 scoped 'daily'
            app.set_ai_setting("daily_spend_cap_usd", "0.01")
            res = app.enforce_cost_cap("visitor_chat")
            assert res is not None
            body, status = res
            assert status == 402
            payload = body.get_json()
            assert payload.get("scope") == "daily" and payload.get("error") == "cap_reached"

            # cap ABOVE today's spend → not blocked
            app.set_ai_setting("daily_spend_cap_usd", "999999")
            assert app.enforce_cost_cap("visitor_chat") is None

            # FAIL-OPEN: if the spend query raises, the request proceeds (no block)
            app.set_ai_setting("daily_spend_cap_usd", "0.01")
            _orig = app.compute_today_spend
            app.compute_today_spend = _raise
            try:
                assert app.enforce_cost_cap("visitor_chat") is None
            finally:
                app.compute_today_spend = _orig
    finally:
        app.reset_ai_setting("daily_spend_cap_usd")
        app.execute_db("DELETE FROM api_cost_events WHERE session_id='guardrail-cap'")


def test_safety_paragraph_toggle():
    app.reset_ai_setting("safety_filter_enabled")
    assert app._compose_safety_paragraph() == ""        # off by default → prompt unchanged
    try:
        app.set_ai_setting("safety_filter_enabled", "yes")
        para = app._compose_safety_paragraph()
        assert para.strip() and "SAFETY" in para         # on → softening paragraph appended
    finally:
        app.reset_ai_setting("safety_filter_enabled")
    assert app._compose_safety_paragraph() == ""
