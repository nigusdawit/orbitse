"""Generalized section templates + custom-section bridge. Embedded Postgres (no DB mocks).

Goal 1 — every built-in LIST section is B-ready: it has a generic loader, a <!-- SECTION_INJECT:slug -->
placeholder in public/index.html, and a [data-ssr-section] client-skip. Proven on a NON-team section
(faq/cards) end-to-end: option-driven, server-rendered into the page source, with its scoped CSS asset.

Goal 2 — custom sections are bridged into the ONE manifest (the "__custom__" block), which describes
each custom template's admin item-field schema, including optional fields routed to extra_data; the
extra_data round-trips through the real item APIs.
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


# ── Goal 1: generalized built-in wiring ──────────────────────────────────────

def test_all_list_sections_have_callable_loaders():
    """Every list section in the registry can load its view-model (so an Option-B variant works with
    only a partial + a variant entry — no per-section loader wiring)."""
    for slug in ("team", "testimonials", "faq", "blog", "services", "events", "experiences"):
        reg = app.SECTION_TEMPLATE_REGISTRY.get(slug)
        assert reg and callable(reg.get("loader")), "%s should have a callable loader" % slug


def test_all_list_placeholders_present_in_index_source():
    """The generic injection point exists in the static page source for every wired list section."""
    with open(os.path.join(app.app.static_folder, "index.html"), encoding="utf-8") as f:
        html = f.read()
    for slug in ("team", "testimonials", "faq", "blog", "services", "events", "experiences"):
        assert ("<!-- SECTION_INJECT:%s -->" % slug) in html, "missing placeholder for %s" % slug
    # pricing is a sub-block of experiences, not an independent section → must NOT have one.
    assert "<!-- SECTION_INJECT:pricing -->" not in html


def test_generic_loader_returns_rows():
    app.execute_db("DELETE FROM faqs WHERE question='Gen Q?'")
    app.execute_db("INSERT INTO faqs (question, answer, sort_order) VALUES ('Gen Q?','Gen A.',0)")
    try:
        items = app._section_items("faq")
        assert any(r.get("question") == "Gen Q?" for r in items)
    finally:
        app.execute_db("DELETE FROM faqs WHERE question='Gen Q?'")


def test_faq_cards_server_rendered_into_homepage():
    """The proof variant on a NON-team section: faq/cards renders SERVER-SIDE into the page source,
    applies its option (default columns=2), and injects its scoped CSS asset."""
    app.execute_db("DELETE FROM faqs WHERE question='SSR FAQ?'")
    app.execute_db("INSERT INTO faqs (question, answer, sort_order) VALUES ('SSR FAQ?','Yes, server-side.',0)")
    app.execute_db("UPDATE page_sections SET enabled=TRUE, settings='{\"variant\":\"cards\"}'::jsonb WHERE slug='faq'")
    try:
        html = app.app.test_client().get("/").get_data(as_text=True)
        assert 'data-ssr-section="faq"' in html          # marker → client renderFAQ() skips it
        assert "tpl-faq-cards" in html                   # the Jinja partial rendered
        assert "SSR FAQ?" in html and "Yes, server-side." in html   # the view-model data, server-side
        assert "--tpl-faq-cols: 2" in html               # default option applied
        assert "/sections/faq/cards.css" in html         # per-template CSS asset injected
    finally:
        app.execute_db("UPDATE page_sections SET enabled=FALSE, settings='{}'::jsonb WHERE slug='faq'")
        app.execute_db("DELETE FROM faqs WHERE question='SSR FAQ?'")


def test_faq_cards_option_columns_applied():
    app.execute_db("DELETE FROM faqs WHERE question='Opt FAQ?'")
    app.execute_db("INSERT INTO faqs (question, answer, sort_order) VALUES ('Opt FAQ?','A.',0)")
    app.execute_db("UPDATE page_sections SET enabled=TRUE, "
                   "settings='{\"variant\":\"cards\",\"variant_options\":{\"columns\":\"3\"}}'::jsonb "
                   "WHERE slug='faq'")
    try:
        html = app.app.test_client().get("/").get_data(as_text=True)
        assert "--tpl-faq-cols: 3" in html   # option override flows to the partial
    finally:
        app.execute_db("UPDATE page_sections SET enabled=FALSE, settings='{}'::jsonb WHERE slug='faq'")
        app.execute_db("DELETE FROM faqs WHERE question='Opt FAQ?'")


def test_faq_default_not_server_rendered():
    app.execute_db("UPDATE page_sections SET enabled=FALSE, settings='{}'::jsonb WHERE slug='faq'")
    html = app.app.test_client().get("/").get_data(as_text=True)
    assert 'data-ssr-section="faq"' not in html
    assert "<!-- SECTION_INJECT:faq -->" not in html   # placeholder consumed (replaced with ''), not leaked


def test_faq_failsafe_on_unknown_variant():
    app.execute_db("UPDATE page_sections SET enabled=TRUE, settings='{\"variant\":\"nope\"}'::jsonb WHERE slug='faq'")
    try:
        r = app.app.test_client().get("/")
        assert r.status_code == 200
        assert 'data-ssr-section="faq"' not in r.get_data(as_text=True)
        assert app._render_section_partial("faq") == ""
    finally:
        app.execute_db("UPDATE page_sections SET enabled=FALSE, settings='{}'::jsonb WHERE slug='faq'")


def test_faq_cards_in_manifest():
    d = _sa().get("/admin/api/section-templates").get_json()
    assert "faq" in d
    keys = [v["key"] for v in d["faq"]]
    assert "cards" in keys
    cards = next(v for v in d["faq"] if v["key"] == "cards")
    assert any(o["key"] == "columns" for o in cards["options"])


# ── Goal 2: custom-section bridge (the __custom__ manifest block) ─────────────

def test_manifest_has_custom_block():
    """Custom templates are described by the SAME manifest under a collision-proof key (slugs can't
    contain underscores). Each carries its admin item-field schema."""
    d = _sa().get("/admin/api/section-templates").get_json()
    assert "__custom__" in d
    cust = d["__custom__"]
    for t in ("cards_grid", "text_content", "image_gallery", "cta_banner", "stats_counter",
              "icon_features", "events", "video_gallery", "podcast", "products", "services"):
        assert t in cust, "custom template %s missing from manifest" % t
    # data-showcase templates are flagged (no per-item editor)
    assert cust["events"]["data_driven"] is True
    assert cust["cards_grid"]["data_driven"] is False


def test_custom_cards_grid_has_extra_badge_field():
    """A registry-declared per-item custom field, routed to extra_data via the `extra` flag."""
    d = _sa().get("/admin/api/section-templates").get_json()
    fields = d["__custom__"]["cards_grid"]["item_fields"]
    badge = next((f for f in fields if f["id"] == "badge"), None)
    assert badge is not None and badge.get("extra") is True
    # standard columns are NOT flagged extra (they map to top-level columns)
    title = next(f for f in fields if f["id"] == "title")
    assert not title.get("extra")


def test_custom_item_extra_data_roundtrips_through_apis():
    """End-to-end: a custom-section item's extra_data persists via the admin API and comes back on the
    PUBLIC items API (the data the client renderer reads for the badge)."""
    sec = app.execute_db(
        "INSERT INTO page_sections (slug, title, section_type, template, sort_order, enabled, settings) "
        "VALUES ('custom-gen-test','Gen Test','cards_grid','cards_grid',99,TRUE,'{}'::jsonb) "
        "ON CONFLICT (slug) DO UPDATE SET enabled=TRUE RETURNING id")
    sid = sec["id"] if isinstance(sec, dict) else sec[0]
    c = _sa()
    try:
        r = c.post("/admin/api/custom-sections/%d/items" % sid, headers=_CSRF,
                   json={"title": "Badged", "extra_data": {"badge": "NEW"}})
        assert r.status_code == 201
        pub = app.app.test_client().get("/api/custom-section/%d/items" % sid).get_json()
        item = next((i for i in pub if i.get("title") == "Badged"), None)
        assert item is not None
        ex = item.get("extra_data")
        if isinstance(ex, str):
            ex = json.loads(ex or "{}")
        assert (ex or {}).get("badge") == "NEW"
    finally:
        app.execute_db("DELETE FROM custom_section_items WHERE section_id=%s", (sid,))
        app.execute_db("DELETE FROM page_sections WHERE id=%s", (sid,))
