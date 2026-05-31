"""Integration tests for the AI Control settings layer (task 030).

Runs against embedded Postgres (via the role-gate harness). Verifies:
  * settings precedence DB > env > default + typed coercion;
  * super-admin can GET/PUT/reset; a client session is 403'd;
  * live tuning: flipping rate_limit on via the API makes a flood 429
    WITHOUT a restart (proves the DB-backed live config path).
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


# ---- precedence (unit-ish, hits the DB getter) ------------------------------

def test_default_then_db_override_then_reset():
    # Default for llm_max_retries is 0 (env unset in the harness).
    assert app.get_ai_setting("llm_max_retries") == 0
    assert app._ai_setting_source("llm_max_retries") == "default"
    # DB override wins.
    app.set_ai_setting("llm_max_retries", 3, by="test")
    assert app.get_ai_setting("llm_max_retries") == 3
    assert app._ai_setting_source("llm_max_retries") == "db"
    # Reset reverts to default.
    app.reset_ai_setting("llm_max_retries")
    assert app.get_ai_setting("llm_max_retries") == 0


def test_typed_coercion_and_bad_value_rejected():
    app.set_ai_setting("rate_limit_max", "25", by="test")  # string coerces to int
    assert app.get_ai_setting("rate_limit_max") == 25
    app.set_ai_setting("provider_fallback", "yes", by="test")  # bool coercion
    assert app.get_ai_setting("provider_fallback") is True
    try:
        app.set_ai_setting("rate_limit_max", "not-a-number", by="test")
        assert False, "expected ValueError"
    except ValueError:
        pass
    finally:
        app.reset_ai_setting("rate_limit_max")
        app.reset_ai_setting("provider_fallback")


def test_unknown_key_rejected():
    try:
        app.set_ai_setting("does_not_exist", "1")
        assert False
    except ValueError:
        pass


# ---- routes + role gate -----------------------------------------------------

def test_super_admin_can_list_and_client_cannot():
    sa = app.app.test_client(); _login(sa, ADMIN_PW)
    r = sa.get("/admin/api/ai-control")
    assert r.status_code == 200
    keys = {s["key"] for s in r.get_json()["settings"]}
    assert {"llm_timeout", "rate_limit_enabled", "sqlguard_enabled"} <= keys

    cl = app.app.test_client(); _login(cl, CLIENT_PW)
    assert cl.get("/admin/api/ai-control").status_code == 403
    h = _csrf(cl)
    assert cl.put("/admin/api/ai-control/llm_timeout", json={"value": 30},
                  headers=h).status_code == 403


# ---- live tuning: no restart ------------------------------------------------

def test_rate_limit_toggle_takes_effect_without_restart():
    sa = app.app.test_client(); _login(sa, ADMIN_PW)
    h = _csrf(sa)
    # Configure a tiny limit and turn it on — all via the API.
    assert sa.put("/admin/api/ai-control/rate_limit_max", json={"value": 1}, headers=h).status_code == 200
    assert sa.put("/admin/api/ai-control/rate_limit_window", json={"value": 60}, headers=h).status_code == 200
    assert sa.put("/admin/api/ai-control/rate_limit_enabled", json={"value": True}, headers=h).status_code == 200
    app._invalidate_ai_control()  # simulate cache expiry immediately (TTL would do this in ≤30s)
    try:
        c = app.app.test_client(); _login(c, ADMIN_PW); ch = _csrf(c)
        s1 = c.post("/admin/api/chat/send", json={"session_id": "rl-x", "message": "a"}, headers=ch).status_code
        s2 = c.post("/admin/api/chat/send", json={"session_id": "rl-x", "message": "b"}, headers=ch).status_code
        assert s1 != 429 and s2 == 429, (s1, s2)
    finally:
        app.reset_ai_setting("rate_limit_enabled")
        app.reset_ai_setting("rate_limit_max")
        app.reset_ai_setting("rate_limit_window")
        app._invalidate_ai_control()


def test_tables_exist_via_init_db():
    for t in ("ai_control_settings", "ai_activity_log"):
        row = app.query_db("SELECT to_regclass(%s) AS t", (f"public.{t}",), fetchone=True)
        assert row and row.get("t") is not None, t
