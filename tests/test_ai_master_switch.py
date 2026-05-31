"""Task 037 — master AI-enhancements kill switch. Embedded Postgres."""
import os
import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")


def _reset():
    for k in ("ai_enhancements_enabled", "llm_max_retries", "rate_limit_enabled",
              "activity_logging_enabled", "sqlguard_enabled", "visitor_llm_max_retries"):
        try: app.reset_ai_setting(k)
        except Exception: pass
    app._invalidate_ai_control()


def test_master_off_forces_inert_even_when_individually_enabled():
    _reset()
    # Individually enable several behavior knobs.
    app.set_ai_setting("llm_max_retries", 5)
    app.set_ai_setting("rate_limit_enabled", True)
    app.set_ai_setting("sqlguard_enabled", True)
    app.set_ai_setting("visitor_llm_max_retries", 3)
    app._invalidate_ai_control()
    assert app.get_ai_setting("llm_max_retries") == 5  # honored while master on
    # Now flip the master OFF.
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    try:
        assert app.get_ai_setting("llm_max_retries") == 0       # forced inert
        assert app.get_ai_setting("rate_limit_enabled") is False
        assert app.get_ai_setting("sqlguard_enabled") is False
        assert app.get_ai_setting("visitor_llm_max_retries") == 0
        assert app.get_ai_setting("activity_logging_enabled") is False
    finally:
        _reset()


def test_master_off_stops_activity_logging():
    _reset()
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    try:
        before = app.query_db("SELECT COUNT(*) AS n FROM ai_activity_log", fetchone=True)["n"]
        app.app.test_client().post("/api/chat", json={"session_id": "ks-1", "message": "hi"})
        after = app.query_db("SELECT COUNT(*) AS n FROM ai_activity_log", fetchone=True)["n"]
        assert after == before, "master off → no activity rows written"
    finally:
        _reset()


def test_master_on_restores_normal():
    _reset()
    # Default (master on) → activity logging works again.
    before = app.query_db("SELECT COUNT(*) AS n FROM ai_activity_log", fetchone=True)["n"]
    app.app.test_client().post("/api/chat", json={"session_id": "ks-2", "message": "hi"})
    after = app.query_db("SELECT COUNT(*) AS n FROM ai_activity_log", fetchone=True)["n"]
    assert after == before + 1
