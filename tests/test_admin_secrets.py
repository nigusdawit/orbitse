"""
Tests for the admin Secrets routes (``/admin/api/secrets/*``).

Two layers:

1. **Auth + CSRF gates** — anon callers get 401 on every route, POSTs
   without a valid CSRF token are rejected.
2. **Happy paths** — GET status returns the expected shape, POST set /
   POST unset round-trip through the .env file, sensitive values are
   never returned in clear, the whitelist is enforced, and a key
   currently provided by Replit Secrets cannot be overwritten.

Every test redirects ``env_manager.ENV_FILE_PATH`` at a tmp file and
snapshots/restores the keys it touches in ``os.environ`` so the real
.env / environment is never modified.
"""

import os

import pytest

import env_manager


# ---------------------------------------------------------------------------
# Login + CSRF helpers (same pattern as tests/test_admin_stripe.py)
# ---------------------------------------------------------------------------

def _login(client):
    pw = os.environ.get("ADMIN_PASSWORD")
    if not pw:
        return None
    return client.post("/admin/login", data={"password": pw}, follow_redirects=False)


def _require_admin_login(client):
    r = _login(client)
    if r is None:
        pytest.skip("ADMIN_PASSWORD not set in env — skipping authed admin route tests")
    if r.status_code not in (200, 302):
        pytest.skip(f"admin login returned {r.status_code} — wrong ADMIN_PASSWORD?")


def _csrf_headers(client):
    r = client.get("/admin/api/csrf-token")
    assert r.status_code == 200, f"csrf-token endpoint returned {r.status_code} (login first?)"
    token = r.get_json()["csrf_token"]
    return {"X-CSRF-Token": token, "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Fixture: redirect ENV_FILE_PATH at a tmp file and isolate env mutations.
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    """Point env_manager at a fresh tmp .env file and clean up the
    handful of os.environ keys these tests mutate, so a passing test
    doesn't leave the global env in a weird state for the next one."""
    path = tmp_path / ".env"
    monkeypatch.setattr(env_manager, "ENV_FILE_PATH", str(path))
    saved_keys = set(env_manager._env_file_keys)
    env_manager._env_file_keys = set()
    touched = (
        "PUBLIC_BASE_URL", "ADMIN_EMAIL", "ADMIN_PHONE",
        "RESEND_FROM_EMAIL", "OPENAI_API_KEY", "BRAVE_SEARCH_API_KEY",
        "FORCE_SECURE_COOKIES", "SITE_URL",
    )
    saved_env = {k: os.environ.get(k) for k in touched}
    for k in touched:
        os.environ.pop(k, None)

    yield path

    env_manager._env_file_keys = saved_keys
    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------

class TestAuthGate:
    """Anon callers MUST be rejected on every route."""

    def test_status_blocked_for_anon(self, client, tmp_env):
        r = client.get("/admin/api/secrets/status")
        # admin_required redirects unauthenticated callers (302) or
        # returns 401 for JSON endpoints depending on the dispatcher.
        assert r.status_code in (302, 401, 403), f"got {r.status_code}"

    def test_set_blocked_for_anon(self, client, tmp_env):
        r = client.post(
            "/admin/api/secrets/set",
            json={"key": "PUBLIC_BASE_URL", "value": "https://x.test"},
        )
        assert r.status_code in (302, 401, 403)
        # And of course the .env file should NOT have been written.
        assert not tmp_env.exists()

    def test_unset_blocked_for_anon(self, client, tmp_env):
        r = client.post("/admin/api/secrets/unset", json={"key": "PUBLIC_BASE_URL"})
        assert r.status_code in (302, 401, 403)
        assert not tmp_env.exists()


# ---------------------------------------------------------------------------
# CSRF gate (POSTs only)
# ---------------------------------------------------------------------------

class TestCsrfGate:
    """POSTs must carry an X-CSRF-Token header (or fail with 403)."""

    def test_set_without_csrf_token_rejected(self, client, tmp_env):
        _require_admin_login(client)
        r = client.post(
            "/admin/api/secrets/set",
            json={"key": "PUBLIC_BASE_URL", "value": "https://x.test"},
        )
        # Global before_request middleware enforces CSRF on POST/PUT/PATCH/DELETE.
        assert r.status_code in (400, 403), f"got {r.status_code}"
        assert not tmp_env.exists()

    def test_unset_without_csrf_token_rejected(self, client, tmp_env):
        _require_admin_login(client)
        r = client.post("/admin/api/secrets/unset", json={"key": "PUBLIC_BASE_URL"})
        assert r.status_code in (400, 403)


# ---------------------------------------------------------------------------
# Status route — shape + sensitive masking
# ---------------------------------------------------------------------------

class TestStatusRoute:
    def test_returns_ok_and_rows(self, client, tmp_env):
        _require_admin_login(client)
        r = client.get("/admin/api/secrets/status")
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True
        assert isinstance(body["rows"], list)
        # Every row carries the expected keys.
        keys_per_row = {"key", "category", "level", "description",
                        "sensitive", "restart", "url", "set", "source",
                        "masked", "value"}
        for row in body["rows"]:
            assert keys_per_row.issubset(row.keys()), \
                f"row missing keys: {keys_per_row - row.keys()}"

    def test_platform_field_present_and_valid(self, client, tmp_env):
        """The status payload includes a top-level ``platform`` field
        so the UI can label platform-managed env vars correctly across
        hosts (Replit vs Heroku/Railway/Fly/Docker/etc). Value is one
        of {'replit', 'other'} — never null, never absent."""
        _require_admin_login(client)
        r = client.get("/admin/api/secrets/status")
        assert r.status_code == 200
        body = r.get_json()
        assert "platform" in body, "missing top-level platform field"
        assert body["platform"] in ("replit", "other"), \
            f"platform must be 'replit' or 'other', got: {body['platform']!r}"

    def test_platform_reflects_repl_id_env(self, client, tmp_env, monkeypatch):
        """When REPL_ID is set the platform reports 'replit'; when both
        Replit env vars are absent it reports 'other'. When only
        REPLIT_DEPLOYMENT is set (Reserved-VM / Autoscale deploys
        sometimes ship without REPL_ID), the platform still reports
        'replit' — the fallback signal exists so deployed instances
        keep the right label."""
        _require_admin_login(client)
        # Signal A: REPL_ID only → 'replit'.
        monkeypatch.setenv("REPL_ID", "test-repl-id")
        monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
        assert client.get("/admin/api/secrets/status").json["platform"] == "replit"
        # Signal B: REPLIT_DEPLOYMENT only → 'replit'.
        monkeypatch.delenv("REPL_ID", raising=False)
        monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
        assert client.get("/admin/api/secrets/status").json["platform"] == "replit"
        # Neither signal → 'other'.
        monkeypatch.delenv("REPL_ID", raising=False)
        monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
        assert client.get("/admin/api/secrets/status").json["platform"] == "other"

    def test_sensitive_values_never_returned_in_clear(self, client, tmp_env):
        _require_admin_login(client)
        # Plant a sensitive value in os.environ → it'd be source=replit_secret.
        os.environ["OPENAI_API_KEY"] = "sk-SUPERSECRET1234ABCD"
        try:
            r = client.get("/admin/api/secrets/status")
            assert r.status_code == 200
            body = r.get_json()
            row = next(x for x in body["rows"] if x["key"] == "OPENAI_API_KEY")
            assert row["set"] is True
            assert row["sensitive"] is True
            # Never returns the clear sensitive value — only masked last 4.
            assert "SUPERSECRET1234" not in str(body)
            assert row["value"] == ""
            assert row["masked"].endswith("ABCD")
            # And source must be replit_secret (not in _env_file_keys).
            assert row["source"] == "replit_secret"
        finally:
            os.environ.pop("OPENAI_API_KEY", None)


# ---------------------------------------------------------------------------
# Set / unset round-trip
# ---------------------------------------------------------------------------

class TestSetUnsetRoundTrip:
    def test_set_writes_to_env_file_and_environ(self, client, tmp_env):
        _require_admin_login(client)
        headers = _csrf_headers(client)
        r = client.post(
            "/admin/api/secrets/set",
            data='{"key": "PUBLIC_BASE_URL", "value": "https://hello.test"}',
            headers=headers,
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        body = r.get_json()
        assert body["ok"] is True
        assert body["row"]["set"] is True
        assert body["row"]["source"] == "env_file"
        # File written
        assert tmp_env.exists()
        assert env_manager._parse_env_file(str(tmp_env)) == {"PUBLIC_BASE_URL": "https://hello.test"}
        # In-process env updated
        assert os.environ["PUBLIC_BASE_URL"] == "https://hello.test"
        # Restart-required is False for PUBLIC_BASE_URL
        assert body["restart_required"] is False

    def test_set_restart_required_flag_propagates(self, client, tmp_env):
        _require_admin_login(client)
        headers = _csrf_headers(client)
        # SITE_URL is NOT restart=True, but FORCE_SECURE_COOKIES is.
        r = client.post(
            "/admin/api/secrets/set",
            data='{"key": "FORCE_SECURE_COOKIES", "value": "1"}',
            headers=headers,
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        body = r.get_json()
        assert body["restart_required"] is True

    def test_set_rejects_unknown_key_with_400(self, client, tmp_env):
        _require_admin_login(client)
        headers = _csrf_headers(client)
        r = client.post(
            "/admin/api/secrets/set",
            data='{"key": "TOTALLY_NOT_A_REAL_KEY", "value": "x"}',
            headers=headers,
        )
        assert r.status_code == 400
        body = r.get_json()
        assert body["ok"] is False
        assert "Unknown key" in body["error"]

    def test_set_rejects_replit_secret_shadowed_key(self, client, tmp_env):
        _require_admin_login(client)
        # Plant a Replit Secret (in os.environ but NOT in _env_file_keys).
        os.environ["ADMIN_EMAIL"] = "from-replit@example.test"
        try:
            headers = _csrf_headers(client)
            r = client.post(
                "/admin/api/secrets/set",
                data='{"key": "ADMIN_EMAIL", "value": "from-app@example.test"}',
                headers=headers,
            )
            assert r.status_code == 400
            body = r.get_json()
            assert body["ok"] is False
            assert "Replit Secrets" in body["error"]
            # Underlying value must NOT have changed.
            assert os.environ["ADMIN_EMAIL"] == "from-replit@example.test"
        finally:
            os.environ.pop("ADMIN_EMAIL", None)

    def test_set_missing_key_returns_400(self, client, tmp_env):
        _require_admin_login(client)
        headers = _csrf_headers(client)
        r = client.post(
            "/admin/api/secrets/set",
            data='{"value": "x"}',
            headers=headers,
        )
        assert r.status_code == 400
        assert r.get_json()["error"] == "Missing 'key'."

    def test_unset_removes_from_file_and_environ(self, client, tmp_env):
        _require_admin_login(client)
        headers = _csrf_headers(client)
        # First set, then unset.
        r1 = client.post(
            "/admin/api/secrets/set",
            data='{"key": "PUBLIC_BASE_URL", "value": "https://x.test"}',
            headers=headers,
        )
        assert r1.status_code == 200
        r2 = client.post(
            "/admin/api/secrets/unset",
            data='{"key": "PUBLIC_BASE_URL"}',
            headers=_csrf_headers(client),  # fresh headers (CSRF is per-session, but defensive)
        )
        assert r2.status_code == 200
        body = r2.get_json()
        assert body["ok"] is True
        assert body["row"]["set"] is False
        assert "PUBLIC_BASE_URL" not in os.environ
        assert env_manager._parse_env_file(str(tmp_env)) == {}

    def test_unset_rejects_replit_secret(self, client, tmp_env):
        _require_admin_login(client)
        os.environ["ADMIN_EMAIL"] = "from-replit@example.test"
        try:
            headers = _csrf_headers(client)
            r = client.post(
                "/admin/api/secrets/unset",
                data='{"key": "ADMIN_EMAIL"}',
                headers=headers,
            )
            assert r.status_code == 400
            body = r.get_json()
            assert "Replit Secrets" in body["error"]
            assert os.environ["ADMIN_EMAIL"] == "from-replit@example.test"
        finally:
            os.environ.pop("ADMIN_EMAIL", None)
