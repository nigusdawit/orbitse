"""Task 044 — offers/deals engine. Embedded Postgres.

Covers:
  * lookup_offers is gated (knob off → []; master switch off → []);
  * only active, in-window offers are returned;
  * trigger_tags targeting: tagged offers need a matching interest, untagged
    (general) offers are always eligible; no interest → everything active;
  * targeted offers sort ahead of general ones;
  * super-admin CRUD (create/list/update/delete), tenant-scoped, client 403'd.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _enable():
    app.set_ai_setting("offers_enabled", True)
    app._invalidate_ai_control()


def _reset():
    for k in ("offers_enabled", "ai_enhancements_enabled"):
        app.reset_ai_setting(k)
    app._invalidate_ai_control()


def _wipe():
    app.execute_db("DELETE FROM offers WHERE tenant_id=%s", (app.current_tenant_id(),))


def _mk(title, *, tags=None, active=True, priority=0, starts=None, ends=None):
    import json as _j
    tid = app.current_tenant_id()
    row = app.execute_db(
        "INSERT INTO offers (tenant_id, title, description, trigger_tags, active, "
        " starts_at, ends_at, priority) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (tid, title, title + " desc", _j.dumps(tags or []), active, starts, ends, priority))
    return row["id"]


# ---- gating -----------------------------------------------------------------

def test_disabled_returns_empty():
    _reset(); _wipe()
    _mk("General Promo")
    try:
        assert app.lookup_offers() == []
    finally:
        _wipe()


def test_master_switch_forces_empty():
    _wipe()
    _mk("General Promo")
    app.set_ai_setting("offers_enabled", True)
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    try:
        assert app.get_ai_setting("offers_enabled") is False
        assert app.lookup_offers() == []
    finally:
        _wipe(); _reset()


# ---- eligibility ------------------------------------------------------------

def test_only_active_in_window():
    _wipe(); _enable()
    try:
        _mk("Active General")
        _mk("Inactive", active=False)
        _mk("Expired", ends="2000-01-01T00:00:00Z")
        _mk("Future", starts="2999-01-01T00:00:00Z")
        titles = {o["title"] for o in app.lookup_offers(limit=10)}
        assert titles == {"Active General"}
    finally:
        _wipe(); _reset()


def test_tag_targeting():
    _wipe(); _enable()
    try:
        _mk("General")                         # untagged → always eligible
        _mk("Catering Deal", tags=["catering", "events"])
        _mk("SEO Deal", tags=["seo"])
        # Interest in catering → general + catering, NOT seo.
        titles = {o["title"] for o in app.lookup_offers(interest="catering", limit=10)}
        assert titles == {"General", "Catering Deal"}
        # No interest → everything active is eligible.
        titles_all = {o["title"] for o in app.lookup_offers(limit=10)}
        assert titles_all == {"General", "Catering Deal", "SEO Deal"}
    finally:
        _wipe(); _reset()


def test_targeted_sorts_first():
    _wipe(); _enable()
    try:
        _mk("General High", priority=100)      # untagged, high priority
        _mk("Catering Match", tags=["catering"], priority=1)
        offers = app.lookup_offers(interest="catering", limit=10)
        # The targeted (tag-matched) offer should come first despite lower priority.
        assert offers[0]["title"] == "Catering Match"
    finally:
        _wipe(); _reset()


# ---- super-admin CRUD -------------------------------------------------------

def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    return c


def _csrf():
    return {"X-CSRF-Token": "t"}


def test_crud_lifecycle():
    _wipe()
    c = _sa()
    try:
        # Create
        r = c.post("/admin/api/offers", json={"title": "Spring Sale", "code": "SPRING",
                   "trigger_tags": ["pricing"], "priority": 5}, headers=_csrf())
        assert r.status_code == 201, r.get_data(as_text=True)
        oid = r.get_json()["offer"]["id"]
        assert r.get_json()["offer"]["trigger_tags"] == ["pricing"]
        # List
        r = c.get("/admin/api/offers")
        assert r.status_code == 200
        assert any(o["id"] == oid for o in r.get_json()["offers"])
        # Update
        r = c.put(f"/admin/api/offers/{oid}", json={"title": "Spring Sale 2",
                  "active": False}, headers=_csrf())
        assert r.status_code == 200 and r.get_json()["offer"]["title"] == "Spring Sale 2"
        assert r.get_json()["offer"]["active"] is False
        # Delete
        r = c.delete(f"/admin/api/offers/{oid}", headers=_csrf())
        assert r.status_code == 200
        # Gone
        r = c.put(f"/admin/api/offers/{oid}", json={"title": "x"}, headers=_csrf())
        assert r.status_code == 404
    finally:
        _wipe()


def test_create_requires_title():
    c = _sa()
    r = c.post("/admin/api/offers", json={"description": "no title"}, headers=_csrf())
    assert r.status_code == 400


def test_client_session_blocked():
    if not CLIENT_PW:
        return
    c = app.app.test_client()
    c.post("/admin/login", data={"password": CLIENT_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    assert c.get("/admin/api/offers").status_code == 403
    assert c.post("/admin/api/offers", json={"title": "x"},
                  headers={"X-CSRF-Token": "t"}).status_code == 403


# ---- registry ---------------------------------------------------------------

def test_tool_and_knob_registered():
    assert "lookup_offers" in app.CHAT_LOOKUP_FUNCTIONS
    names = {t["function"]["name"] for t in app.CHAT_TOOLS}
    assert "lookup_offers" in names
    keys = {e["key"] for e in app._ai_control_registry()}
    assert "offers_enabled" in keys
