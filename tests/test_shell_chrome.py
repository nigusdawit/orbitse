"""Task 093 (gap §0) — Workspaces shell chrome. Embedded Postgres (no mocks).

P1: GET /admin/api/nav-counts — live sub-nav badge counts keyed by tab data-testid.
Verifies: auth required; the shape is always {"counts": {...}}; counts mirror the DB
for non-PII domains; PII (leads → tab-crm) is super-admin-only; the 30s cache actually
serves without recompute.
"""
import os

import app
import admin.shell as _shell

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _sa():
    """Super-admin client (default admin password = super admin)."""
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    return c


def _bust():
    _shell._NAV_COUNTS_CACHE.clear()


def test_nav_counts_requires_auth():
    r = app.app.test_client().get("/admin/api/nav-counts")
    assert r.status_code in (401, 403, 302)


def test_nav_counts_shape_and_match_db():
    c = _sa()
    _bust()
    r = c.get("/admin/api/nav-counts")
    assert r.status_code == 200
    j = r.get_json()
    assert isinstance(j.get("counts"), dict)
    # API counts mirror DB truth for non-PII domains (cache was just busted).
    for testid, table in [("tab-pages", "pages"), ("tab-products", "products"),
                          ("tab-orders", "orders"), ("tab-chat-history", "chat_conversations")]:
        true_n = app.query_db("SELECT COUNT(*) AS n FROM " + table, fetchone=True)["n"]
        assert j["counts"].get(testid) == int(true_n), testid


def test_nav_counts_pii_super_only():
    # Super admin sees the leads/PII count under tab-crm.
    sc = _sa()
    _bust()
    js = sc.get("/admin/api/nav-counts").get_json()
    assert "tab-crm" in js["counts"]
    # A logged-in CLIENT (non-super) must NOT receive the PII count.
    if not CLIENT_PW:
        return
    cc = app.app.test_client()
    cc.post("/admin/login", data={"password": CLIENT_PW})
    with cc.session_transaction() as s:
        s["_csrf_token"] = "t"
    _bust()
    jc = cc.get("/admin/api/nav-counts").get_json()
    assert "tab-crm" not in (jc.get("counts") or {})


def test_nav_counts_served_from_cache():
    # Prime the cache, then poison the cached value; the next call within TTL must
    # return the poisoned value verbatim — proving it served from cache, not the DB.
    c = _sa()
    _bust()
    c.get("/admin/api/nav-counts")                       # populates cache[True]
    _shell._NAV_COUNTS_CACHE[True]["val"] = {"tab-sentinel": 4242}
    j = c.get("/admin/api/nav-counts").get_json()
    assert j["counts"] == {"tab-sentinel": 4242}
    _bust()                                              # leave cache clean for other tests


# ---- P2: GET /admin/api/search (record search) ----

def test_search_requires_auth():
    r = app.app.test_client().get("/admin/api/search?q=test")
    assert r.status_code in (401, 403, 302)


def test_search_short_query_returns_empty():
    c = _sa()
    assert c.get("/admin/api/search?q=a").get_json() == {"groups": []}   # <2 chars


def test_search_malformed_query_ok():
    # Pure-wildcard query ("%%") must not error — q is a bound ILIKE param.
    c = _sa()
    r = c.get("/admin/api/search?q=%25%25")
    assert r.status_code == 200
    assert isinstance(r.get_json().get("groups"), list)


def test_search_finds_records_super():
    c = _sa()
    app.execute_db("INSERT INTO leads (tenant_id, name, email) VALUES (1, %s, %s)",
                   ("Zorptastic Probe", "zorp@probe.test"))
    app.execute_db("INSERT INTO pages (slug, title) VALUES (%s, %s) ON CONFLICT (slug) DO NOTHING",
                   ("zorptastic-probe", "Zorptastic Probe Page"))
    try:
        j = c.get("/admin/api/search?q=zorptastic").get_json()
        types = {g["type"]: g for g in j["groups"]}
        assert "lead" in types, j                       # super sees the PII lead group
        assert any("Zorptastic" in (it["label"] or "") for it in types["lead"]["items"])
        assert types["lead"]["items"][0]["tabAction"] == "tab-crm"
        assert "page" in types
        assert types["page"]["items"][0]["tabAction"] == "tab-pages"
    finally:
        app.execute_db("DELETE FROM leads WHERE email=%s", ("zorp@probe.test",))
        app.execute_db("DELETE FROM pages WHERE slug=%s", ("zorptastic-probe",))


def test_search_pii_hidden_from_client():
    if not CLIENT_PW:
        return
    app.execute_db("INSERT INTO leads (tenant_id, name, email) VALUES (1, %s, %s)",
                   ("Zorptastic Probe", "zorp@probe.test"))
    app.execute_db("INSERT INTO pages (slug, title) VALUES (%s, %s) ON CONFLICT (slug) DO NOTHING",
                   ("zorptastic-probe", "Zorptastic Probe Page"))
    try:
        cc = app.app.test_client()
        cc.post("/admin/login", data={"password": CLIENT_PW})
        with cc.session_transaction() as s:
            s["_csrf_token"] = "t"
        j = cc.get("/admin/api/search?q=zorptastic").get_json()
        types = {g["type"] for g in j["groups"]}
        assert "lead" not in types                      # PII hidden from non-super
        assert "page" in types                          # non-PII still searchable
    finally:
        app.execute_db("DELETE FROM leads WHERE email=%s", ("zorp@probe.test",))
        app.execute_db("DELETE FROM pages WHERE slug=%s", ("zorptastic-probe",))


def test_search_settings_static_map():
    c = _sa()
    j = c.get("/admin/api/search?q=appearance").get_json()
    setting = [g for g in j["groups"] if g["type"] == "setting"]
    assert setting and any(it["tabAction"] == "tab-appearance" for it in setting[0]["items"])


# ---- P3: GET /admin/api/shell/health (status pill) ----

def _bust_health():
    app._HEALTH_PILL_CACHE["ts"] = 0.0


def _set_provider(p):
    app.execute_db(
        "INSERT INTO agent_provider_settings (id, provider, openai_model, claude_model) "
        "VALUES (1, %s, 'gpt-4o-mini', 'claude-sonnet-4-5') "
        "ON CONFLICT (id) DO UPDATE SET provider = EXCLUDED.provider", (p,))


def test_health_requires_auth():
    r = app.app.test_client().get("/admin/api/shell/health")
    assert r.status_code in (401, 403, 302)


def test_health_live_on_default_provider():
    c = _sa()
    _set_provider("openai")          # default; openai_client is always constructed
    _bust_health()
    try:
        j = c.get("/admin/api/shell/health").get_json()
        assert j["status"] == "live", j
        assert "provider" in j
    finally:
        _set_provider("openai")
        _bust_health()


def test_health_degraded_when_claude_without_key():
    c = _sa()
    _set_provider("claude")          # configured provider unusable (no ANTHROPIC key/client in tests)
    _bust_health()
    try:
        j = c.get("/admin/api/shell/health").get_json()
        assert j["status"] in ("degraded", "down"), j
        assert j.get("detail")       # explains why (Claude not initialized)
    finally:
        _set_provider("openai")      # restore so other tests/UX see a healthy default
        _bust_health()
