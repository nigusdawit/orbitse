"""
Cache-Control header tests for the public read-only /api/* endpoints
(Optimization #3 — April 2026).

These pin the contract that:

  1. Every endpoint in the explicit allowlist gets exactly the
     `public, max-age=60, stale-while-revalidate=300` header.
  2. Endpoints OUTSIDE the allowlist (admin paths, POST endpoints,
     /healthz, etc.) do NOT silently get the public cache header — even
     by accident if someone widens the hook's matcher.
  3. Existing explicit cache directives (the SSE `no-cache`, the TTS
     `no-store`) are NEVER overwritten by the hook.

The whole point of the allowlist over a denylist is blast radius: missing
a perf win is fine, accidentally caching a private endpoint at the CDN
layer is a session-bleed bug. These tests guard the second case.
"""
import pytest


# Mirrors the frozenset in app.py; if it drifts the parametrized test below
# fails. Keep this list updated in lock-step.
EXPECTED_CACHEABLE_PATHS = [
    "/api/page-bundle",
    "/api/site-settings",
    "/api/gallery-cards",
    "/api/experiences",
    "/api/pricing",
    "/api/testimonials",
    "/api/team",
    "/api/faq",
    "/api/blog",
    "/api/business-info",
    "/api/page-sections",
    "/api/sphere-settings",
    "/api/video-gallery",
    "/api/podcast",
    "/api/products",
    "/api/storefront-config",
    "/api/events",
    "/api/services",
    "/api/theme",
    "/api/chatbot-settings",
    "/api/voice/settings",
]
EXPECTED_HEADER = "public, max-age=60, stale-while-revalidate=300"


# ---------------------------------------------------------- positive tests
def test_allowlist_in_app_matches_test_expectation(flask_app):
    """If a contributor adds or removes a path in app.py's
    _CACHEABLE_API_PATHS, this test forces them to update the test list
    too — keeping the perf surface visible in code review."""
    from app import _CACHEABLE_API_PATHS  # noqa: WPS433
    assert set(_CACHEABLE_API_PATHS) == set(EXPECTED_CACHEABLE_PATHS), (
        "Cacheable allowlist drifted between app.py and the test file. "
        "Update EXPECTED_CACHEABLE_PATHS in tests/test_cache_headers.py."
    )


@pytest.mark.parametrize("path", EXPECTED_CACHEABLE_PATHS)
def test_cacheable_endpoint_sets_public_cache_header(client, path):
    """Every allowlisted endpoint returns the standard public cache header
    on a successful GET. This is the contract that lets browsers + a CDN
    skip re-asking the origin for content that changes weekly at most."""
    res = client.get(path)
    # The endpoint may legitimately 404 in a freshly-seeded DB (e.g.
    # /api/site-settings before the row is created), in which case the
    # hook intentionally does NOT set the cache header. That branch is
    # tested separately. Here we only assert the success path.
    if res.status_code != 200:
        pytest.skip(f"{path} returned {res.status_code}; cache header only applies to 200s")
    assert res.headers.get("Cache-Control") == EXPECTED_HEADER, (
        f"{path} returned Cache-Control={res.headers.get('Cache-Control')!r}; "
        f"expected {EXPECTED_HEADER!r}."
    )


# ---------------------------------------------------------- negative tests
def test_admin_endpoint_does_not_get_public_cache(client):
    """Admin endpoints (anonymous → 302 / 401 / 403) must never end up
    with `public` cache. The hook bails on status != 200, but this guards
    against a future refactor that loosens that check."""
    res = client.get("/admin/api/site-settings")
    cc = res.headers.get("Cache-Control", "")
    assert "public" not in cc, (
        f"/admin/api/site-settings leaked public cache header: {cc!r}. "
        f"This would let a CDN cache admin responses for anonymous users."
    )


def test_non_allowlisted_public_endpoint_does_not_get_public_cache(client):
    """Endpoints outside the allowlist (here: /healthz) must not silently
    pick up the public cache header. Guards against the hook's matcher
    accidentally being broadened."""
    res = client.get("/healthz")
    cc = res.headers.get("Cache-Control", "")
    assert "public, max-age=60" not in cc, (
        f"/healthz unexpectedly got public cache header: {cc!r}. "
        f"Did the hook switch from allowlist to denylist by mistake?"
    )


def test_post_to_cacheable_path_does_not_cache(client):
    """The bundle endpoint accepts GET only — a POST must not get the
    public cache header (writes are never cacheable)."""
    res = client.post("/api/page-bundle", json={})
    # Will be 405 Method Not Allowed since /api/page-bundle is GET-only.
    cc = res.headers.get("Cache-Control", "")
    assert "public, max-age=60" not in cc, (
        f"POST to /api/page-bundle unexpectedly got public cache: {cc!r}."
    )


def test_existing_no_cache_headers_are_preserved(flask_app):
    """The SSE chat / voice streams set Cache-Control: no-cache and the
    TTS prepare endpoint sets no-store. The hook MUST NOT overwrite these
    — a public cache on a streaming endpoint would buffer the entire
    stream and break live token rendering.

    We verify the contract by inspecting the hook's logic directly: it
    bails when `Cache-Control` is already in response.headers.
    """
    import inspect

    from app import _add_public_api_cache_headers

    src = inspect.getsource(_add_public_api_cache_headers)
    assert '"Cache-Control" in response.headers' in src, (
        "Cache-header hook lost its respect-existing-Cache-Control guard. "
        "SSE streams and TTS-prepare would now be incorrectly overwritten."
    )


def test_set_cookie_response_skips_cache(flask_app):
    """If a response carries Set-Cookie (e.g. session refresh), the hook
    must NOT add `public` cache — a CDN sharing one cached entry could
    replay another user's session cookie. Verified by inspecting the
    hook's logic so we don't have to fake a session-cookie-minting
    response in the test client."""
    import inspect

    from app import _add_public_api_cache_headers

    src = inspect.getsource(_add_public_api_cache_headers)
    assert 'response.headers.get("Set-Cookie")' in src, (
        "Cache-header hook lost its anti-session-bleed Set-Cookie guard."
    )


def test_session_cookie_presence_skips_cache(client, flask_app):
    """If the request carries a Flask session cookie, the hook MUST skip
    caching — an admin might be logged in and editing content. Verified
    behaviorally by planting a session cookie in the test client's cookie
    jar (Werkzeug 3.x API) and asserting the response is uncached.

    Note: passing `Cookie:` in `headers={...}` or `HTTP_COOKIE` via
    `environ_overrides` does NOT work here — Flask's test_client always
    rebuilds the Cookie header from its own cookie jar, overriding both.
    `set_cookie()` is the only way to populate that jar."""
    name = flask_app.config.get("SESSION_COOKIE_NAME", "session")
    client.set_cookie(name, "fake-session-value")
    try:
        res = client.get("/api/page-bundle")
        assert res.status_code == 200
        cc = res.headers.get("Cache-Control", "")
        assert "public" not in cc, (
            f"Cacheable endpoint returned public cache even though the "
            f"request carried a session cookie: {cc!r}. Admins editing "
            f"content would see stale data for up to 60s."
        )
    finally:
        # Clear the cookie so it doesn't leak into other tests sharing
        # this client (the conftest gives us a per-test client, but a
        # belt-and-braces clear is cheap insurance).
        client.delete_cookie(name)


def test_anonymous_response_has_no_vary_cookie(client):
    """The cache hook MUST NOT touch the session object — doing so makes
    Flask auto-emit `Vary: Cookie`, which fragments any shared CDN cache
    across every cookie value clients send (analytics, locale, A/B
    buckets, etc.) and largely defeats the `public` cache.

    Anonymous responses on cacheable endpoints should Vary only on
    `Accept-Encoding` (set by flask-compress), never on `Cookie`.
    """
    res = client.get("/api/page-bundle")
    assert res.status_code == 200
    vary = res.headers.get("Vary", "")
    assert "cookie" not in vary.lower(), (
        f"/api/page-bundle has Vary={vary!r} including 'Cookie' — the "
        f"cache hook is reading session, which fragments CDN cache "
        f"across cookie values. Use request.cookies.get() instead."
    )
    # Sanity: the cache header should still be set on the anonymous request.
    assert "public, max-age=60" in res.headers.get("Cache-Control", "")


def test_non_session_cookies_still_get_public_cache(client, flask_app):
    """The CDN-sharing guarantee: when a client carries unrelated cookies
    (Google Analytics `_ga`, locale `lang`, A/B test bucket, etc.) but
    NOT the Flask session cookie, the response MUST still be cacheable.

    This is the actual reason we went out of our way to avoid `Vary:
    Cookie` in the first place. If a CDN saw `Vary: Cookie`, every
    distinct cookie value across analytics IDs would fragment the cache
    into one entry per visitor — defeating the `public` cache entirely.
    Here we prove that a visitor with realistic third-party cookies
    still hits the same cacheable response as a cookie-less visitor."""
    name = flask_app.config.get("SESSION_COOKIE_NAME", "session")
    # Plant a few realistic non-session cookies. The session-cookie name
    # is intentionally NOT among them — that's the whole point.
    client.set_cookie("_ga", "GA1.2.1234567890.1234567890")
    client.set_cookie("_ga_ABC123", "GS1.1.1234567890")
    client.set_cookie("lang", "en-US")
    client.set_cookie("ab_bucket", "treatment_b")
    try:
        # Sanity: we did NOT plant the session cookie.
        # (If a future refactor renames SESSION_COOKIE_NAME to one of
        # the analytics cookies above, this test must fail loudly so we
        # notice the collision.)
        assert name not in {"_ga", "_ga_ABC123", "lang", "ab_bucket"}, (
            f"Session cookie name {name!r} collides with the analytics "
            f"cookies this test plants — pick different test cookies."
        )
        res = client.get("/api/page-bundle")
        assert res.status_code == 200
        cc = res.headers.get("Cache-Control", "")
        assert cc == EXPECTED_HEADER, (
            f"Cacheable endpoint dropped its public cache header even "
            f"though the request only carried unrelated cookies: {cc!r}. "
            f"This kills the CDN-sharing optimization for any visitor "
            f"with analytics cookies."
        )
        vary = res.headers.get("Vary", "")
        assert "cookie" not in vary.lower(), (
            f"Anonymous-with-tracker response has Vary={vary!r} "
            f"including 'Cookie' — fragments the CDN cache."
        )
    finally:
        for k in ("_ga", "_ga_ABC123", "lang", "ab_bucket"):
            client.delete_cookie(k)


def test_session_cookie_skip_uses_request_cookies_not_session(flask_app):
    """Source-level guard against the Vary: Cookie regression. The hook
    MUST inspect request.cookies (no session access) to detect possibly-
    logged-in callers — calling session.get() pollutes Vary: Cookie."""
    import inspect

    from app import _add_public_api_cache_headers

    src = inspect.getsource(_add_public_api_cache_headers)
    assert "request.cookies" in src, (
        "Cache-header hook lost its request-cookie skip guard."
    )
    assert "session.get(" not in src, (
        "Cache-header hook is reading session, which marks it as accessed "
        "and forces Flask to add Vary: Cookie to every response — "
        "fragmenting shared CDN cache. Inspect request.cookies instead."
    )
    assert "session[" not in src, (
        "Cache-header hook is subscripting session, which marks it as "
        "accessed and pollutes Vary: Cookie. Inspect request.cookies."
    )
