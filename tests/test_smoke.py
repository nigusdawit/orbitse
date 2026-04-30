"""
Smoke tests for customer-affecting paths.

Goal: catch the kind of regression where a refactor accidentally breaks a
public route (404, 500, malformed JSON shape) BEFORE the operator's visitors
hit it. These are not unit tests — they don't pin down business logic. They
ask: "is the route wired, does it return the right content type, does the
top-level shape look right?"

Anything that mutates real state is forbidden here — POSTs deliberately send
invalid payloads to exercise the validation path, and we accept any
non-5xx response code as evidence that "the route exists and validated".

Run with: `python -m pytest -q tests/`
"""

import os
import pytest


# =============================================================================
# Liveness + the public marketing site
# =============================================================================

def test_healthz_returns_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.data == b"ok"


def test_homepage_renders_html(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.data.lower()
    assert b"<html" in body or b"<!doctype html" in body


def test_sitemap_xml_serves(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "xml" in (r.content_type or "").lower()


def test_robots_txt_serves(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert b"user-agent" in r.data.lower() or b"sitemap" in r.data.lower()


# =============================================================================
# Public content APIs that return a single JSON object
# =============================================================================

PUBLIC_OBJECT_ENDPOINTS = [
    "/api/site-settings",
    "/api/business-info",
    "/api/seo",
    "/api/chatbot-settings",
    "/api/voice/settings",
    "/api/storefront-config",
    "/api/sphere-settings",
]


@pytest.mark.parametrize("path", PUBLIC_OBJECT_ENDPOINTS)
def test_public_object_endpoint_returns_json_dict(client, path):
    r = client.get(path)
    assert r.status_code == 200, f"{path} returned {r.status_code}"
    j = r.get_json()
    assert isinstance(j, dict), f"{path} returned non-dict body: {type(j).__name__}"


# =============================================================================
# Public content APIs that return a JSON list
# =============================================================================

PUBLIC_LIST_ENDPOINTS = [
    "/api/services",
    "/api/events",
    "/api/products",
    "/api/blog",
    "/api/faq",
    "/api/team",
    "/api/gallery-cards",
    "/api/video-gallery",
    "/api/podcast",
    "/api/experiences",
    "/api/pricing",
    "/api/testimonials",
    "/api/page-sections",
]


@pytest.mark.parametrize("path", PUBLIC_LIST_ENDPOINTS)
def test_public_list_endpoint_returns_json_list(client, path):
    r = client.get(path)
    assert r.status_code == 200, f"{path} returned {r.status_code}"
    j = r.get_json()
    assert isinstance(j, list), f"{path} returned non-list body: {type(j).__name__}"


# =============================================================================
# /api/page-bundle drift guard
# =============================================================================
# The bundle endpoint duplicates the SQL of 17 source endpoints into one
# request to collapse the homepage cold-load waterfall. If a contributor
# edits a source endpoint's query but forgets to mirror it in the bundle,
# this test fails — guaranteed.

# Maps the bundle key → the source endpoint that should produce identical JSON.
BUNDLE_KEY_TO_SOURCE_ENDPOINT = {
    "site_settings":     "/api/site-settings",
    "gallery_cards":     "/api/gallery-cards",
    "experiences":       "/api/experiences",
    "pricing":           "/api/pricing",
    "testimonials":      "/api/testimonials",
    "team":              "/api/team",
    "faq":               "/api/faq",
    "blog":              "/api/blog",
    "business_info":     "/api/business-info",
    "page_sections":     "/api/page-sections",
    "sphere_settings":   "/api/sphere-settings",
    "video_gallery":     "/api/video-gallery",
    "podcast":           "/api/podcast",
    "products":          "/api/products",
    "storefront_config": "/api/storefront-config",
    "events":            "/api/events",
    "services":          "/api/services",
}


def test_page_bundle_returns_all_expected_keys(client):
    """The bundle must always return every key the public homepage destructures."""
    r = client.get("/api/page-bundle")
    assert r.status_code == 200, f"/api/page-bundle returned {r.status_code}"
    bundle = r.get_json()
    assert isinstance(bundle, dict), "/api/page-bundle did not return a JSON dict"
    missing = [k for k in BUNDLE_KEY_TO_SOURCE_ENDPOINT if k not in bundle]
    assert not missing, f"/api/page-bundle is missing keys: {missing}"


@pytest.mark.parametrize(
    "bundle_key,source_path", list(BUNDLE_KEY_TO_SOURCE_ENDPOINT.items())
)
def test_page_bundle_matches_individual_endpoints(client, bundle_key, source_path):
    """Each bundle key must equal the body its source endpoint returns.

    Asserts both BODY parity (the JSON shape inside the bundle key matches
    the source endpoint's body) and CONTRACT parity (both source and
    bundle return HTTP 200 with application/json). If a contributor edits
    a source endpoint's query but forgets to mirror it in the bundle,
    this test fails.
    """
    src_resp = client.get(source_path)
    bundle_resp = client.get("/api/page-bundle")

    # Contract parity: both must return 200 + JSON. The bundle is allowed
    # to gracefully degrade keys to null (see api_page_bundle docstring's
    # "KNOWN INTENTIONAL DIVERGENCE" note for the site_settings 404→null
    # case), but in the seeded smoke DB every row exists, so the source
    # endpoint must also return 200 here.
    assert src_resp.status_code == 200, (
        f"{source_path} returned {src_resp.status_code}; "
        f"drift guard requires source endpoints be reachable."
    )
    assert bundle_resp.status_code == 200, (
        f"/api/page-bundle returned {bundle_resp.status_code}; "
        f"the homepage cold-load fast path is broken."
    )
    assert "json" in (bundle_resp.content_type or "").lower(), (
        f"/api/page-bundle content_type={bundle_resp.content_type!r}; "
        f"expected JSON."
    )

    # Body parity: the bundle slice must equal the source endpoint body.
    bundle = bundle_resp.get_json()
    src = src_resp.get_json()
    assert bundle.get(bundle_key) == src, (
        f"Drift detected: /api/page-bundle key '{bundle_key}' "
        f"does not match {source_path}. Update api_page_bundle() in app.py."
    )


# =============================================================================
# Admin auth boundary — anonymous callers should NOT get past admin_required
# =============================================================================

def test_admin_login_page_renders(client):
    r = client.get("/admin/login")
    assert r.status_code == 200
    body = r.data.lower()
    assert b"<form" in body or b"password" in body


def test_admin_dashboard_redirects_anon_to_login(client):
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code in (301, 302), f"expected redirect, got {r.status_code}"


def test_admin_api_endpoint_blocks_anon(client):
    """admin_required must run BEFORE the CSRF check and bounce anon callers
    via redirect-to-login or 401 — NOT 403, which would mean CSRF fired first
    on an unauthenticated session (a Tier 7 contract violation)."""
    r = client.post(
        "/admin/api/chat/clear",
        json={"session_id": "smoke-anon"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 401), f"expected auth-deny (302/401), got {r.status_code}"


# =============================================================================
# CSRF protection (Tier 7 regression)
# =============================================================================
#
# These three tests need to actually log in as admin, so they require the real
# ADMIN_PASSWORD in the env. We never default it to "admin" because (a) the
# real value rarely is "admin" and (b) silently falling through to a wrong
# password would mean the CSRF tests run under an anon session and the test
# for "logged in but missing token → 403" would pass for the wrong reason
# (CSRF middleware skips for anon callers — see Tier 7 docs).

def _login(client):
    """Perform an admin login. Returns (response, password) so callers can skip."""
    pw = os.environ.get("ADMIN_PASSWORD")
    if not pw:
        return None
    return client.post("/admin/login", data={"password": pw}, follow_redirects=False)


def _require_login(client):
    r = _login(client)
    if r is None:
        pytest.skip("ADMIN_PASSWORD not set in env — skipping authed CSRF tests")
    if r.status_code not in (200, 302):
        pytest.skip(f"admin login returned {r.status_code} — wrong ADMIN_PASSWORD?")


def test_csrf_blocks_authed_admin_post_without_token(client):
    _require_login(client)
    r = client.post("/admin/api/chat/clear", json={"session_id": "smoke-csrf"})
    assert r.status_code == 403, f"expected 403 csrf_failed, got {r.status_code}"
    j = r.get_json()
    assert j and j.get("csrf_failed") is True, f"expected csrf_failed body, got {j!r}"


def test_csrf_token_endpoint_returns_token_when_authed(client):
    _require_login(client)
    r = client.get("/admin/api/csrf-token")
    assert r.status_code == 200
    j = r.get_json()
    assert j and isinstance(j.get("csrf_token"), str)
    assert len(j["csrf_token"]) >= 20, "csrf token suspiciously short"


def test_csrf_pass_authed_admin_post_with_token(client):
    """Full happy path: log in, fetch token, POST through with the header set.

    NOTE: this DOES mutate state — it clears the chat history for the dummy
    session_id 'smoke-csrf-pass'. That id is intentionally never used by real
    visitors, so the impact is bounded to one row in the chat_messages table.
    """
    _require_login(client)
    tok = client.get("/admin/api/csrf-token").get_json()["csrf_token"]
    r = client.post(
        "/admin/api/chat/clear",
        json={"session_id": "smoke-csrf-pass"},
        headers={"X-CSRF-Token": tok},
    )
    assert r.status_code == 200, f"expected 200 with valid token, got {r.status_code}"
    j = r.get_json()
    assert j and j.get("ok") is True


# =============================================================================
# VELO master surface (no auth needed for /status)
# =============================================================================

def test_velo_status_responds(client):
    r = client.get("/api/velo/status")
    # When VELO_AGENT_KEY is set, /status may still require it, hence 401/403 OK.
    assert r.status_code in (200, 401, 403), f"velo status returned {r.status_code}"


# =============================================================================
# Route-mounting checks — pure URL-map introspection, never hits the handler
# =============================================================================
#
# We deliberately don't POST to /api/chat with a stub body — the chat route
# doesn't validate `message` up front, so an empty body falls through to
# the rate-limit + cost-cap path and could even reach the LLM.
#
# We also can't probe via `GET /api/chat` expecting 405, because there is
# a catch-all `@app.route("/<path:filename>")` near the bottom of app.py
# that swallows any GET that no specific rule matched.
#
# So we just walk app.url_map directly — proves the rule is registered on
# the right method without invoking the handler at all.

def test_chat_endpoint_is_mounted_post(flask_app):
    rules = [r for r in flask_app.url_map.iter_rules() if r.rule == "/api/chat"]
    assert rules, "/api/chat is not mounted"
    methods = set().union(*(r.methods or set() for r in rules))
    assert "POST" in methods, f"/api/chat must accept POST, got methods={methods}"


def test_event_rsvp_invalid_slug_rejected(client):
    """Bogus slug must return 400 or 404 — 405 would mean POST routing broke."""
    r = client.post("/api/events/__nonexistent_smoke_test__/rsvp", json={})
    assert r.status_code in (400, 404), f"got {r.status_code}"


def test_form_submit_invalid_slug_rejected(client):
    """Bogus slug must return 400 or 404 — 405 would mean POST routing broke."""
    r = client.post("/api/forms/__nonexistent_smoke_test__/submit", json={})
    assert r.status_code in (400, 404), f"got {r.status_code}"


# =============================================================================
# Public detail pages — bogus slug must hit the not-found path, not 500
# =============================================================================

@pytest.mark.parametrize("path", [
    "/blog/__nonexistent_smoke_test__",
    "/event/__nonexistent_smoke_test__",
])
def test_detail_page_bogus_slug_returns_not_found(client, path):
    r = client.get(path)
    assert r.status_code == 404, f"{path} should be 404, got {r.status_code}"


# =============================================================================
# Per-section pretty URLs (Task #67) — /<slug> deep-links to a homepage anchor
# =============================================================================
#
# serve_section() routes /<section_slug> to the homepage shell with
# data-initial-section pinned on <html>. Disabled rows redirect to "/",
# unknown slugs fall through to the static-file SPA path. We verify the
# happy path against an always-enabled built-in slug ("hero" is seeded
# enabled in init_db) and the redirect path against a slug we know is
# disabled by default ("podcast").

def test_section_route_serves_homepage_with_initial_section(client):
    """A valid enabled section slug must serve the homepage HTML and
    pin <html data-initial-section="..."> so script.js deep-links."""
    r = client.get("/hero")
    assert r.status_code == 200, f"/hero returned {r.status_code}"
    body = r.data.decode("utf-8", errors="replace")
    assert 'data-initial-section="section-hero"' in body, (
        "expected data-initial-section attr on <html> tag, got body that "
        "starts with: " + body[:200]
    )


def test_section_route_disabled_slug_redirects_to_root(client):
    """A known section that's disabled must NOT serve the homepage —
    redirect to '/' so visitors don't see a broken hidden anchor.

    We don't rely on whichever built-in slugs happen to be disabled in
    the smoke DB (they may have been toggled on by previous test runs
    or local admin work). Instead we insert a deliberately-disabled
    custom section, assert the redirect, then clean up — gives the
    test a fully deterministic input regardless of seeded state.
    """
    import secrets as _s
    from app import get_db

    test_slug = f"__smoke_disabled_{_s.token_hex(4)}"
    inserted_id = None
    try:
        # Insert disabled custom section directly so we don't depend on
        # any admin endpoint for setup. RETURNING id keeps cleanup
        # bulletproof even if the slug column gains a unique-collision
        # we didn't anticipate. get_db() returns a pooled connection
        # already in autocommit mode — close() returns it to the pool.
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO page_sections "
                    "  (slug, title, section_type, template, sort_order, enabled) "
                    "VALUES (%s, 'Smoke Test Disabled', 'custom', 'cards_grid', 9999, false) "
                    "RETURNING id",
                    (test_slug,),
                )
                inserted_id = cur.fetchone()[0]
        finally:
            conn.close()

        r = client.get(f"/{test_slug}", follow_redirects=False)
        assert r.status_code == 302, (
            f"/{test_slug} (disabled) must redirect, got {r.status_code}"
        )
        assert r.headers.get("Location", "").endswith("/"), (
            f"disabled section must redirect to '/', got "
            f"Location={r.headers.get('Location')!r}"
        )
    finally:
        if inserted_id is not None:
            try:
                conn = get_db()
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "DELETE FROM page_sections WHERE id = %s",
                            (inserted_id,),
                        )
                finally:
                    conn.close()
            except Exception:
                pass


def test_section_route_custom_section_resolves_to_section_custom_id(client):
    """Custom-section rows must resolve to '#section-custom-<id>' so
    the deep-link matches the DOM id pattern applySectionOrder() emits
    in public/script.js. Locks in the parity between server-side DOM
    id resolution and client-side rendering — if either side renames,
    this test catches it."""
    import secrets as _s
    from app import get_db

    test_slug = f"__smoke_custom_{_s.token_hex(4)}"
    inserted_id = None
    try:
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO page_sections "
                    "  (slug, title, section_type, template, sort_order, enabled) "
                    "VALUES (%s, 'Smoke Test Custom', 'custom', 'cards_grid', 9998, true) "
                    "RETURNING id",
                    (test_slug,),
                )
                inserted_id = cur.fetchone()[0]
        finally:
            conn.close()

        r = client.get(f"/{test_slug}")
        assert r.status_code == 200, (
            f"/{test_slug} (enabled custom) returned {r.status_code}"
        )
        body = r.data.decode("utf-8", errors="replace")
        expected = f'data-initial-section="section-custom-{inserted_id}"'
        assert expected in body, (
            f"expected {expected!r} in served HTML, got body that "
            f"starts with: {body[:200]}"
        )
    finally:
        if inserted_id is not None:
            try:
                conn = get_db()
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "DELETE FROM page_sections WHERE id = %s",
                            (inserted_id,),
                        )
                finally:
                    conn.close()
            except Exception:
                pass


def test_section_route_falls_back_for_static_assets(client):
    """Slug-with-dot must NOT be treated as a section — must reach the
    static-file handler so /styles.css, /favicon.ico etc still serve."""
    r = client.get("/styles.css")
    # Either 200 (file exists) or 304 (cached) is fine; what matters is
    # that we DIDN'T 302→/ or 500 — both of which would mean the new
    # serve_section route ate the request.
    assert r.status_code in (200, 304), (
        f"/styles.css must reach serve_static, got {r.status_code}"
    )


def test_sitemap_includes_enabled_section_urls(client):
    """The sitemap must list enabled sections so search engines can
    discover them. We don't pin the exact slug list (it depends on
    what's seeded) — just assert the sitemap mentions at least one
    /<slug> entry beyond the canonical "/" entry."""
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    body = r.data.decode("utf-8", errors="replace")
    # 'highlights' is seeded enabled by init_db and survives every
    # default install, so it's a safe canary for this assertion.
    assert "/highlights" in body, (
        "sitemap.xml is missing per-section URLs (Task #67). Body "
        "preview: " + body[:400]
    )


# =============================================================================
# Setup wizard — state-dependent, both responses are valid in their own context
# =============================================================================

def test_setup_route_responds_in_either_state(client):
    """/setup is 200 on a fresh install, 404 once bootstrapped — both fine."""
    r = client.get("/setup")
    assert r.status_code in (200, 404), f"got {r.status_code}"


# =============================================================================
# Storage backend (Tier 9 — April 2026)
#
# These run against whatever backend is configured for the test session
# (default `local`; set UPLOADS_BACKEND=s3 + the S3_* vars in CI to also
# exercise the boto3 path). The dummy key lives under `__smoke__/` so it
# can't collide with any real /uploads/<file> URL the app might produce.
# =============================================================================

def test_storage_singleton_returns_known_backend():
    """get_storage() must return one of the two known backends so the
    test environment fails loud if a third one is wired in by accident."""
    from storage import get_storage
    name = get_storage().name
    assert name in ("local", "s3"), f"unexpected backend: {name!r}"


def test_storage_write_read_delete_roundtrip():
    """write_bytes -> read_bytes -> exists -> delete -> exists must be
    transactional from the caller's POV. Hits the same code path that the
    deck-import, admin-upload, and TTS-cache call sites all rely on."""
    import secrets as _s
    from storage import get_storage
    store = get_storage()
    key = f"__smoke__/{_s.token_hex(8)}.bin"
    payload = b"tier-9-storage-roundtrip-" + _s.token_bytes(8)
    try:
        store.write_bytes(key, payload, content_type="application/octet-stream")
        assert store.exists(key) is True, "exists() should report True after write"
        assert store.read_bytes(key) == payload, "read_bytes() must round-trip exact bytes"
    finally:
        # Always clean up so a test crash doesn't leave litter for the next run.
        try:
            store.delete(key)
        except Exception:
            pass
    assert store.exists(key) is False, "exists() should report False after delete"
