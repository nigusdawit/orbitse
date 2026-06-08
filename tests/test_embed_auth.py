"""
Embed authorization lock-down tests.

These verify that the embeddable concierge (`/embed/concierge`) cannot be
iframed + used by unauthorized sites:

  - no key            -> 200 + `frame-ancestors 'self'` (own origin only)
  - explicit bad key  -> 403 (fail closed)
  - disabled key      -> 403 (fail closed)
  - valid key         -> 200 + frame-ancestors includes the key's allow-listed
                         origins + the key is injected into the shell so the
                         iframe's same-origin /api/* calls carry X-Embed-Key
  - wildcard allowlist -> `frame-ancestors *`

Plus a check that `_embed_auth` bypasses the per-key origin allowlist for the
iframe's SAME-ORIGIN keyed calls while still enforcing it for genuine
cross-origin keyed traffic.

The dev database is shared (see conftest), so each test inserts a uniquely
named key and removes it again in a finally block — no real data is touched.
"""

import json

import pytest

from app import execute_db, query_db


def _make_key(embed_key, allowlist, enabled=True):
    execute_db(
        "INSERT INTO tenant_embed_keys (tenant_id, embed_key, label, "
        "origin_allowlist, enabled) VALUES (1, %s, %s, %s, %s) "
        "ON CONFLICT (embed_key) DO UPDATE SET "
        "origin_allowlist = EXCLUDED.origin_allowlist, enabled = EXCLUDED.enabled",
        (embed_key, "pytest", json.dumps(allowlist), enabled),
    )


def _drop_key(embed_key):
    execute_db("DELETE FROM tenant_embed_keys WHERE embed_key = %s", (embed_key,))


def _csp(resp):
    return resp.headers.get("Content-Security-Policy", "")


def test_embed_no_key_self_only(client):
    resp = client.get("/embed/concierge")
    assert resp.status_code == 200
    assert "frame-ancestors 'self'" in _csp(resp)
    # No key injected — the embed stays keyless until a valid key is supplied.
    assert b"__AAP_EMBED_KEY__" not in resp.data


def test_embed_bogus_key_forbidden(client):
    resp = client.get("/embed/concierge?embed_key=pk_pytest_does_not_exist")
    assert resp.status_code == 403


def test_embed_disabled_key_forbidden(client):
    key = "pk_pytest_disabled"
    _make_key(key, ["https://client.example.com"], enabled=False)
    try:
        resp = client.get(f"/embed/concierge?embed_key={key}")
        assert resp.status_code == 403
    finally:
        _drop_key(key)


def test_embed_valid_key_frames_and_injects(client):
    key = "pk_pytest_valid"
    _make_key(key, ["https://client.example.com"])
    try:
        resp = client.get(f"/embed/concierge?embed_key={key}")
        assert resp.status_code == 200
        csp = _csp(resp)
        assert "frame-ancestors" in csp
        assert "'self'" in csp
        assert "https://client.example.com" in csp
        # The validated key is injected so same-origin /api/* calls carry it.
        assert key.encode() in resp.data
        assert b"__AAP_EMBED_KEY__" in resp.data
    finally:
        _drop_key(key)


def test_embed_wildcard_allowlist(client):
    key = "pk_pytest_wildcard"
    _make_key(key, ["*"])
    try:
        resp = client.get(f"/embed/concierge?embed_key={key}")
        assert resp.status_code == 200
        assert "frame-ancestors *" in _csp(resp)
    finally:
        _drop_key(key)


def test_homepage_has_no_embed_csp_or_key(client):
    """The first-party homepage stays keyless / first-party — no embed CSP
    header and no injected key (behavior must be unchanged)."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "frame-ancestors" not in _csp(resp)
    assert b"__AAP_EMBED_KEY__" not in resp.data


def test_embed_auth_same_origin_keyed_bypasses_allowlist(client):
    """A keyed API call whose Origin is OUR OWN origin (the iframe's same-origin
    /api/* calls) must pass even though that origin isn't in the key's allowlist
    — the host origin was already gated at iframe-load time via frame-ancestors.
    A genuine cross-origin keyed call with a disallowed origin must still 403."""
    key = "pk_pytest_sameorigin"
    _make_key(key, ["https://client.example.com"])
    try:
        # Same-origin keyed GET to an embeddable read endpoint: should NOT be
        # rejected by the origin allowlist (the key is enabled).
        same = client.get(
            "/api/gallery-cards",
            headers={"X-Embed-Key": key, "Origin": "http://localhost"},
        )
        assert same.status_code != 403

        # Cross-origin keyed call from an origin NOT in the allowlist → 403.
        cross = client.get(
            "/api/gallery-cards",
            headers={"X-Embed-Key": key, "Origin": "https://evil.example.com"},
        )
        assert cross.status_code == 403
    finally:
        _drop_key(key)
