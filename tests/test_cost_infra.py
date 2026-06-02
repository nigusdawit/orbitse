"""Pins the cost/billing infrastructure (Track B, task 078, piece #2) BEFORE it
is relocated from app.py into core.py and its routes into a blueprint.

Covered:
  * _to_float coercion;
  * get_model_price value, case-insensitivity, unknown->falsy, and the 60s
    in-process cache + _invalidate_price_cache() busting it (the cache whose
    accessor/invalidator move together);
  * compute_mtd_spend / get_tenant_cost_cap shape + defaults;
  * the /admin/api/cost/* HTTP routes (summary, prices GET/PATCH, cap GET/PUT)
    incl. the PATCH-busts-the-price-cache behavior. This last one is the safety
    net for the LOGIC CHANGE that swaps the route's direct `_PRICE_CACHE.clear()`
    for a call to the core invalidator -- the observable behavior (a price edit
    is visible to the very next get_model_price) must stay identical.

Every assertion goes through the `app.` namespace, exactly how live call sites
resolve these names, so the re-export from core is proven to keep them resolving.
Runs under the embedded-Postgres harness; model_prices is seeded by init_db().
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")


# ---- unit-level infra -------------------------------------------------------

def test_to_float():
    assert app._to_float("3.5") == 3.5
    assert app._to_float(None) == 0.0
    assert app._to_float("not-a-number", -1) == -1
    assert app._to_float(7) == 7.0


def test_get_model_price_value_and_case_insensitivity():
    row = app.get_model_price("openai", "gpt-4o-mini", "chat")
    assert row, "seeded price row should exist"
    assert float(row["input_price_per_million_tokens"]) == 0.150
    assert float(row["output_price_per_million_tokens"]) == 0.600
    # provider + surface compared case-insensitively; model exact.
    assert app.get_model_price("OpenAI", "gpt-4o-mini", "CHAT") is not None


def test_get_model_price_unknown_is_falsy():
    assert not app.get_model_price("no-such-provider", "no-such-model", "chat")


def test_price_cache_staleness_and_invalidation():
    """A direct DB edit is NOT seen until _invalidate_price_cache() runs —
    proves the cache is live and the invalidator is the way to bust it."""
    rid = app.query_db(
        "SELECT id FROM model_prices WHERE provider='openai' "
        "AND model='gpt-4o-mini' AND surface='chat'", fetchone=True)["id"]
    try:
        app._invalidate_price_cache()
        baseline = float(app.get_model_price("openai", "gpt-4o-mini", "chat")
                         ["input_price_per_million_tokens"])  # caches it
        app.execute_db(
            "UPDATE model_prices SET input_price_per_million_tokens = 0.999 "
            "WHERE id = %s", (rid,))
        # Still cached at the old value (cache not busted yet).
        assert float(app.get_model_price("openai", "gpt-4o-mini", "chat")
                     ["input_price_per_million_tokens"]) == baseline
        # Invalidation makes the edit visible.
        app._invalidate_price_cache()
        assert float(app.get_model_price("openai", "gpt-4o-mini", "chat")
                     ["input_price_per_million_tokens"]) == 0.999
    finally:
        app.execute_db(
            "UPDATE model_prices SET input_price_per_million_tokens = 0.150 "
            "WHERE id = %s", (rid,))
        app._invalidate_price_cache()


def test_compute_mtd_spend_shape():
    out = app.compute_mtd_spend()
    assert set(out.keys()) == {"chat_usd", "voice_usd", "sms_usd", "total_usd"}
    for v in out.values():
        assert isinstance(v, float)
    assert out["total_usd"] == out["chat_usd"] + out["voice_usd"] + out["sms_usd"]


def test_get_tenant_cost_cap_returns_row_or_defaults():
    cap = dict(app.get_tenant_cost_cap())
    # init_db seeds a row; either way these keys must be present.
    for k in ("tenant_id", "monthly_cap_usd", "warn_at_percent", "cap_behavior"):
        assert k in cap


# ---- HTTP routes ------------------------------------------------------------

def _login(c, pw):
    return c.post("/admin/login", data={"password": pw})


def _csrf(c):
    with c.session_transaction() as s:
        s["_csrf_token"] = "tok"
    return {"X-CSRF-Token": "tok"}


def test_cost_summary_route():
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    r = c.get("/admin/api/cost/summary")
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert "spend" in body or "mtd" in body or isinstance(body, dict)


def test_cost_prices_get_route():
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    r = c.get("/admin/api/cost/prices")
    assert r.status_code == 200
    rows = r.get_json()["rows"]
    assert any(x["provider"] == "openai" and x["model"] == "gpt-4o-mini" for x in rows)


def test_cost_prices_patch_busts_cache():
    """The PATCH endpoint must make the new unit price visible to the very
    next get_model_price() call (cache busted). This is the LOGIC-CHANGE
    safety net: it holds whether the route clears _PRICE_CACHE directly or
    calls the core invalidator."""
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    hdr = _csrf(c)
    rid = app.query_db(
        "SELECT id FROM model_prices WHERE provider='openai' "
        "AND model='gpt-4o-mini' AND surface='chat'", fetchone=True)["id"]
    try:
        # Warm the cache at the seeded value.
        app._invalidate_price_cache()
        assert float(app.get_model_price("openai", "gpt-4o-mini", "chat")
                     ["input_price_per_million_tokens"]) == 0.150
        # PATCH a new price through the route.
        r = c.patch(f"/admin/api/cost/prices/{rid}",
                    json={"input_price_per_million_tokens": 1.234}, headers=hdr)
        assert r.status_code == 200, r.get_data(as_text=True)
        # The very next price lookup reflects the edit (cache was busted).
        assert float(app.get_model_price("openai", "gpt-4o-mini", "chat")
                     ["input_price_per_million_tokens"]) == 1.234
    finally:
        app.execute_db(
            "UPDATE model_prices SET input_price_per_million_tokens = 0.150 "
            "WHERE id = %s", (rid,))
        app._invalidate_price_cache()


def test_cost_cap_get_and_put_roundtrip():
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    hdr = _csrf(c)
    before = c.get("/admin/api/cost/cap")
    assert before.status_code == 200
    orig = before.get_json()
    try:
        r = c.put("/admin/api/cost/cap",
                  json={"monthly_cap_usd": 42.5, "warn_at_percent": 70,
                        "cap_behavior": "throttle"}, headers=hdr)
        assert r.status_code == 200, r.get_data(as_text=True)
        body = r.get_json()
        assert float(body["monthly_cap_usd"]) == 42.5
        assert body["warn_at_percent"] == 70
        assert body["cap_behavior"] == "throttle"
        # Validation: bad behavior rejected.
        bad = c.put("/admin/api/cost/cap",
                    json={"cap_behavior": "nonsense"}, headers=hdr)
        assert bad.status_code == 400
    finally:
        # Restore the original cap config.
        app.execute_db(
            "INSERT INTO tenant_cost_caps (tenant_id, monthly_cap_usd, "
            "  warn_at_percent, cap_behavior, alert_email, digest_email, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,NOW()) "
            "ON CONFLICT (tenant_id) DO UPDATE SET "
            "  monthly_cap_usd = EXCLUDED.monthly_cap_usd, "
            "  warn_at_percent = EXCLUDED.warn_at_percent, "
            "  cap_behavior = EXCLUDED.cap_behavior",
            (1, orig.get("monthly_cap_usd"), orig.get("warn_at_percent") or 80,
             orig.get("cap_behavior") or "alert_only",
             orig.get("alert_email") or "", orig.get("digest_email") or ""))
