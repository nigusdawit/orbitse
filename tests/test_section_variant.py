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


# ---- Option B: server-rendered Jinja partial (team / spotlight) --------------

def test_team_spotlight_is_server_rendered_into_homepage():
    """Selecting the 'spotlight' Jinja variant renders the team section SERVER-SIDE into the homepage
    HTML — present in the initial source (SEO), no JS needed."""
    app.execute_db("DELETE FROM team_members WHERE name='SSR Tester'")
    app.execute_db("INSERT INTO team_members (name, title, bio, image_url, sort_order) "
                   "VALUES ('SSR Tester','Lead Engineer','Builds things.','',0)")
    app.execute_db("UPDATE page_sections SET enabled=TRUE, settings='{\"variant\":\"spotlight\"}'::jsonb "
                   "WHERE slug='team'")
    try:
        html = app.app.test_client().get("/").get_data(as_text=True)
        assert 'data-ssr-section="team"' in html        # server-render marker (client renderTeam skips it)
        assert "tpl-team-spotlight" in html             # the Jinja partial rendered
        assert "SSR Tester" in html and "Lead Engineer" in html   # the view-model data, server-side
    finally:
        app.execute_db("UPDATE page_sections SET settings='{}'::jsonb WHERE slug='team'")
        app.execute_db("DELETE FROM team_members WHERE name='SSR Tester'")


def test_team_default_is_not_server_rendered():
    """Default variant → no server render (client renders the grid); the placeholder is consumed."""
    app.execute_db("UPDATE page_sections SET settings='{}'::jsonb WHERE slug='team'")
    html = app.app.test_client().get("/").get_data(as_text=True)
    assert 'data-ssr-section="team"' not in html
    assert "<!-- SECTION_TEAM_INJECT -->" not in html   # placeholder replaced with '' (not leaked)


def test_section_partial_failsafe_on_unknown_variant():
    """An unknown variant (no Jinja partial) must NOT server-render and must NOT break the page."""
    app.execute_db("UPDATE page_sections SET enabled=TRUE, settings='{\"variant\":\"does-not-exist\"}'::jsonb "
                   "WHERE slug='team'")
    try:
        r = app.app.test_client().get("/")
        assert r.status_code == 200
        assert 'data-ssr-section="team"' not in r.get_data(as_text=True)
        assert app._render_section_partial("team") == ""   # early-returns '' (variant not registered)
    finally:
        app.execute_db("UPDATE page_sections SET settings='{}'::jsonb WHERE slug='team'")
