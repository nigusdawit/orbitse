"""Section template-variant POC. Embedded Postgres (no DB mocks).

Pins the backend half of the per-section template system: the section PUT records the chosen
`variant` into page_sections.settings.variant, clears it on empty, and — crucially — does so
ADDITIVELY (a later non-variant update doesn't drop it, and setting the variant doesn't clobber
other settings keys). The DB data + section behavior are untouched; only the display choice is stored.
"""
import json
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
_CSRF = {"X-CSRF-Token": "t"}


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    return c


def _testimonials_section_id():
    row = app.query_db("SELECT id FROM page_sections WHERE slug='testimonials'", fetchone=True)
    assert isinstance(row, dict), "testimonials section should be seeded by init_db"
    return row["id"]


def _settings_of(sid):
    row = app.query_db("SELECT settings FROM page_sections WHERE id=%s", (sid,), fetchone=True)
    st = row.get("settings") if isinstance(row, dict) else None
    if isinstance(st, str):
        try:
            st = json.loads(st or "{}")
        except ValueError:
            st = {}
    return st or {}


def test_set_variant_persists():
    c = _sa()
    sid = _testimonials_section_id()
    try:
        r = c.put("/admin/api/page-sections/%d" % sid, headers=_CSRF, json={"variant": "carousel"})
        assert r.status_code == 200
        assert _settings_of(sid).get("variant") == "carousel"
    finally:
        c.put("/admin/api/page-sections/%d" % sid, headers=_CSRF, json={"variant": ""})


def test_clear_variant():
    c = _sa()
    sid = _testimonials_section_id()
    c.put("/admin/api/page-sections/%d" % sid, headers=_CSRF, json={"variant": "carousel"})
    r = c.put("/admin/api/page-sections/%d" % sid, headers=_CSRF, json={"variant": ""})
    assert r.status_code == 200
    assert not _settings_of(sid).get("variant")   # cleared → falls back to default


def test_variant_survives_a_non_variant_update():
    # The additivity guarantee: setting the variant, then a title-only update, must NOT drop it.
    c = _sa()
    sid = _testimonials_section_id()
    try:
        c.put("/admin/api/page-sections/%d" % sid, headers=_CSRF, json={"variant": "carousel"})
        r = c.put("/admin/api/page-sections/%d" % sid, headers=_CSRF, json={"title": "Testimonials"})
        assert r.status_code == 200
        assert _settings_of(sid).get("variant") == "carousel"
    finally:
        c.put("/admin/api/page-sections/%d" % sid, headers=_CSRF, json={"variant": ""})


def test_variant_does_not_clobber_other_settings():
    c = _sa()
    sid = _testimonials_section_id()
    try:
        c.put("/admin/api/page-sections/%d" % sid, headers=_CSRF, json={"settings": {"foo": "bar"}})
        c.put("/admin/api/page-sections/%d" % sid, headers=_CSRF, json={"variant": "carousel"})
        st = _settings_of(sid)
        assert st.get("variant") == "carousel" and st.get("foo") == "bar"
    finally:
        c.put("/admin/api/page-sections/%d" % sid, headers=_CSRF, json={"settings": {}})
