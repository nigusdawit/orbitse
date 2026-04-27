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
