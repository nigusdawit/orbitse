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
