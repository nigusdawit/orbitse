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


# ---- Full system: manifest, options, per-item custom fields, assets ----------

def test_section_templates_manifest():
    """The manifest endpoint is the single source: variants + labels + options + item_fields."""
    d = _sa().get("/admin/api/section-templates").get_json()
    assert "team" in d
    keys = [v["key"] for v in d["team"]]
    assert "spotlight" in keys and "showcase" in keys
    showcase = next(v for v in d["team"] if v["key"] == "showcase")
    assert any(o["key"] == "columns" for o in showcase["options"])
    assert any(f["key"] == "video_url" for f in showcase["item_fields"])


def test_team_extra_roundtrips_and_is_preserved():
    """Per-member custom fields: create stores `extra`; an update WITHOUT extra preserves it; an
    update WITH extra replaces it. (The additivity is what stops the existing form wiping it.)"""
    c = _sa()
    r = c.post("/admin/api/team", headers=_CSRF,
               json={"name": "Extra Tester", "title": "QA",
                     "extra": {"video_url": "https://x.test/v.mp4", "tagline": "ships it"}})
    assert r.status_code == 201
    mid = r.get_json()["id"]

    def _extra():
        row = app.query_db("SELECT name, extra FROM team_members WHERE id=%s", (mid,), fetchone=True)
        ex = row["extra"]
        return (row["name"], json.loads(ex) if isinstance(ex, str) else ex)

    try:
        _, ex = _extra()
        assert ex.get("video_url") == "https://x.test/v.mp4" and ex.get("tagline") == "ships it"
        c.put("/admin/api/team/%d" % mid, headers=_CSRF, json={"name": "Extra Tester 2"})  # no extra
        name2, ex2 = _extra()
        assert name2 == "Extra Tester 2" and ex2.get("tagline") == "ships it"               # preserved
        c.put("/admin/api/team/%d" % mid, headers=_CSRF, json={"extra": {"tagline": "new"}})  # replace
        _, ex3 = _extra()
        assert ex3.get("tagline") == "new" and "video_url" not in ex3
    finally:
        app.execute_db("DELETE FROM team_members WHERE id=%s", (mid,))


def test_showcase_renders_options_fields_and_assets_in_source():
    """The rich variant: options (columns/reveal), per-item custom fields (tagline/video), and the
    per-template CSS/JS assets all land in the server source."""
    app.execute_db("DELETE FROM team_members WHERE name='Showcase Member'")
    app.execute_db(
        "INSERT INTO team_members (name, title, bio, image_url, sort_order, extra) "
        "VALUES ('Showcase Member','Director','Bio.','',0,"
        "'{\"video_url\":\"https://x.test/clip.mp4\",\"tagline\":\"makes magic\"}'::jsonb)")
    app.execute_db(
        "UPDATE page_sections SET enabled=TRUE, "
        "settings='{\"variant\":\"showcase\",\"variant_options\":{\"columns\":\"4\",\"reveal\":true}}'::jsonb "
        "WHERE slug='team'")
    try:
        html = app.app.test_client().get("/").get_data(as_text=True)
        assert "tpl-team-showcase" in html                # the showcase partial server-rendered
        assert 'data-tpl-init="teamShowcase"' in html     # JS init hook wired
        assert "--tpl-cols: 4" in html                    # OPTION applied (columns)
        assert "makes magic" in html                      # per-item CUSTOM FIELD (tagline)
        assert "https://x.test/clip.mp4" in html          # per-item VIDEO field
        assert "fade-in-view" in html                     # reveal option → animation class
        assert "/sections/team/showcase.css" in html      # per-template CSS asset injected
        assert "/sections/team/showcase.js" in html       # per-template JS asset injected
    finally:
        app.execute_db("UPDATE page_sections SET settings='{}'::jsonb WHERE slug='team'")
        app.execute_db("DELETE FROM team_members WHERE name='Showcase Member'")


def test_variant_options_defaults_merge():
    app.execute_db("UPDATE page_sections SET settings='{}'::jsonb WHERE slug='team'")
    opts = app._section_variant_options("team", "showcase")
    assert opts.get("columns") == "3" and opts.get("reveal") is True   # declared defaults applied


def test_variant_options_persist_via_put():
    """The admin options form saves {variant_options} → merged into settings (variant preserved)."""
    c = _sa()
    tid = app.query_db("SELECT id FROM page_sections WHERE slug='team'", fetchone=True)["id"]
    try:
        c.put("/admin/api/page-sections/%d" % tid, headers=_CSRF, json={"variant": "showcase"})
        r = c.put("/admin/api/page-sections/%d" % tid, headers=_CSRF,
                  json={"variant_options": {"columns": "4", "reveal": False}})
        assert r.status_code == 200
        st = _settings_of(tid)
        assert st.get("variant") == "showcase"                          # variant preserved
        assert st.get("variant_options", {}).get("columns") == "4"      # options stored
    finally:
        c.put("/admin/api/page-sections/%d" % tid, headers=_CSRF, json={"settings": {}})


def test_manifest_includes_client_variant_flag():
    """The single manifest also lists Option-A (client-rendered) variants, flagged client:true."""
    d = _sa().get("/admin/api/section-templates").get_json()
    assert "testimonials" in d
    car = next((v for v in d["testimonials"] if v["key"] == "carousel"), None)
    assert car and car.get("client") is True
