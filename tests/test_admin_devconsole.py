"""
Tests for the admin Developer Console — runbook snapshot + provider
probes + test-send actions + agent re-registration.

Two layers:

1. **Pure helpers** (`devconsole.PROVIDERS` / `provider_summary` /
   `_is_configured` / `probe`) — verifies the catalog is what the UI
   expects, that env-var detection follows the documented rules, that
   probes return the standard `{ok, latency_ms, error}` shape on both
   success and failure, and that an unknown provider name surfaces as
   a structured error rather than a crash.

2. **Admin routes** (`/admin/api/devconsole/*`) — verifies the auth
   gate (anon callers must NOT see snapshots or fire actions), the
   CSRF gate on every POST, the unknown-provider rejection contract,
   the env-var prerequisite contract for test-email / test-sms /
   reregister-velo, and the success path with mocked outbound
   helpers so no real Resend / Twilio / OpenAI calls fire from CI.

Provider probes never run for real here — every test that exercises a
probe path replaces the relevant `devconsole._probe_*` or `messaging.*`
helper via monkeypatch so the test cost is zero.
"""

import os

import httpx
import pytest

import devconsole
import messaging


# ---- Helpers ----------------------------------------------------------------

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
    return {"X-CSRF-Token": token}


# ---------------------------------------------------------------------------
# Layer 1 — pure helpers (no Flask, no network)
# ---------------------------------------------------------------------------

class TestProviderCatalog:
    """The PROVIDERS list is the contract between backend + frontend
    for which cards render in the Service Health panel — pin it."""

    def test_known_providers(self):
        assert set(devconsole.PROVIDERS) == {
            "openai", "anthropic", "twilio", "resend", "elevenlabs",
            "brave_search", "yelp", "google_places", "tripadvisor",
        }

    def test_provider_summary_returns_one_per_provider(self):
        summary = devconsole.provider_summary()
        assert isinstance(summary, list)
        assert len(summary) == len(devconsole.PROVIDERS)
        names = [p["name"] for p in summary]
        assert names == devconsole.PROVIDERS  # order preserved
        for entry in summary:
            assert set(entry.keys()) == {"name", "configured"}
            assert isinstance(entry["configured"], bool)


class TestIsConfigured:
    """`_is_configured` is the basis for both the summary endpoint and
    the probe gate — every provider must be detectable purely from env."""

    @pytest.mark.parametrize("provider,env_var", [
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("elevenlabs", "ELEVENLABS_API_KEY"),
        ("brave_search", "BRAVE_SEARCH_API_KEY"),
        ("yelp", "YELP_API_KEY"),
        ("google_places", "GOOGLE_PLACES_API_KEY"),
        ("tripadvisor", "TRIPADVISOR_API_KEY"),
    ])
    def test_single_env_var_provider(self, provider, env_var, monkeypatch):
        monkeypatch.setenv(env_var, "test-key-xyz")
        assert devconsole._is_configured(provider) is True
        monkeypatch.delenv(env_var, raising=False)
        assert devconsole._is_configured(provider) is False

    def test_twilio_needs_both_sid_and_token(self, monkeypatch):
        monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
        monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
        assert devconsole._is_configured("twilio") is False
        monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACxxxx")
        assert devconsole._is_configured("twilio") is False  # token still missing
        monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret")
        assert devconsole._is_configured("twilio") is True

    def test_openai_accepts_either_canonical_or_replit_alias(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AI_INTEGRATIONS_OPENAI_API_KEY", raising=False)
        assert devconsole._is_configured("openai") is False
        monkeypatch.setenv("AI_INTEGRATIONS_OPENAI_API_KEY", "sk-xxx")
        assert devconsole._is_configured("openai") is True

    def test_unknown_provider_returns_false(self):
        assert devconsole._is_configured("definitely-not-a-real-provider") is False


class TestRedaction:
    """`_redact` is the sole defence preventing API keys from leaking into
    probe error strings (which are returned in the JSON the admin browser
    receives). Two providers (Google Places + TripAdvisor) pass keys via
    query params, so an httpx error whose `str()` includes the URL would
    otherwise expose the secret. Pin both layers of defence."""

    def test_masks_literal_secret(self):
        out = devconsole._redact(
            "network error: 401 from key=SECRETKEY123ABC",
            ["SECRETKEY123ABC"],
        )
        assert "SECRETKEY123ABC" not in out
        assert "[REDACTED]" in out

    def test_strips_query_string_from_embedded_url(self):
        # No literal secret given — only the URL query-strip layer fires.
        out = devconsole._redact(
            "network error: GET https://maps.googleapis.com/foo?key=ABCDEF123 failed",
            [],
        )
        assert "ABCDEF123" not in out
        assert "[REDACTED]" in out
        # Host + path before the ? must survive (operator needs to know
        # WHICH provider failed, just not the key).
        assert "maps.googleapis.com" in out

    def test_short_strings_not_masked(self):
        # 5-char "value" is below the 6-char masking floor — masking it
        # would risk eating common substrings of error messages.
        out = devconsole._redact("hello value world", ["value"])
        assert "value" in out

    def test_empty_secret_list_still_strips_query_strings(self):
        out = devconsole._redact("see https://api.example.com/x?y=1&z=2", [])
        assert "y=1" not in out
        assert "z=2" not in out
        assert "[REDACTED]" in out


class TestProbeDoesNotLeakKey:
    """Integration: a probe whose underlying httpx call fails (network
    error or 401) must NOT surface the API key in the returned `error`.
    Covers the two real-world leak vectors: query-param providers
    (Google Places, TripAdvisor) where the key is in the URL, and
    header providers where a 401 body might echo the auth header back."""

    def _install_failing_httpx(self, monkeypatch, *, mode, leak_string):
        """Patch httpx.Client so the next request either raises an
        HTTPError whose str() contains `leak_string`, or returns a 401
        whose body contains `leak_string`."""
        class _FakeResp:
            def __init__(self, body):
                self.status_code = 401
                self.text = body

        class _FakeClient:
            def __init__(self, *a, **kw): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def request(self, method, url, **kw):
                if mode == "raise":
                    # Mimic the way httpx surfaces a real connect error
                    # (the URL — including any query string — appears
                    # in the str() form of the exception).
                    raise httpx.HTTPError(
                        f"connect error to {url} (and key seen as: {leak_string})"
                    )
                return _FakeResp(
                    f"Provider error body that helpfully echoes key={leak_string}"
                )

        import httpx as _httpx_module
        monkeypatch.setattr(_httpx_module, "Client", _FakeClient)

    def test_google_places_query_param_key_redacted_on_network_error(self, monkeypatch):
        leak = "GP_LIVE_KEY_ABC12345XYZ"
        monkeypatch.setenv("GOOGLE_PLACES_API_KEY", leak)
        self._install_failing_httpx(monkeypatch, mode="raise", leak_string=leak)
        result = devconsole.probe("google_places")
        assert result["ok"] is False
        assert leak not in result["error"], (
            f"API key leaked into probe error: {result['error']!r}"
        )

    def test_tripadvisor_query_param_key_redacted_on_4xx_body(self, monkeypatch):
        leak = "TA_LIVE_KEY_ZZ987654321Q"
        monkeypatch.setenv("TRIPADVISOR_API_KEY", leak)
        self._install_failing_httpx(monkeypatch, mode="resp401", leak_string=leak)
        result = devconsole.probe("tripadvisor")
        assert result["ok"] is False
        assert leak not in result["error"], (
            f"API key leaked into probe error: {result['error']!r}"
        )

    def test_header_provider_token_redacted_on_4xx_body(self, monkeypatch):
        # Resend header path — provider 401 body sometimes echoes the
        # offending Authorization header back. Verify token is masked.
        leak = "RESEND_BEARER_TOKEN_QWERTYUIOP123"
        monkeypatch.setenv("RESEND_API_KEY", leak)
        # Make sure the Resend module isn't shadowing the env-var path.
        monkeypatch.setattr(messaging, "_resolve_resend",
                            lambda: ("", "noreply@example.com"))
        self._install_failing_httpx(monkeypatch, mode="resp401", leak_string=leak)
        result = devconsole.probe("resend")
        assert result["ok"] is False
        assert leak not in result["error"], (
            f"Bearer token leaked into probe error: {result['error']!r}"
        )


class TestProbe:
    """The probe dispatcher — never raises, always returns the standard
    dict, and short-circuits cleanly on unknown / unconfigured providers."""

    def test_unknown_provider_returns_structured_error(self):
        result = devconsole.probe("not-a-provider")
        assert result["ok"] is False
        assert "unknown provider" in result["error"]
        assert result["latency_ms"] == 0

    def test_unconfigured_provider_short_circuits(self, monkeypatch):
        # Make sure brave's env var is not set, then probe — should NOT
        # touch the network and should return a clean configured-false err.
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
        result = devconsole.probe("brave_search")
        assert result["ok"] is False
        assert "not configured" in result["error"]

    def test_probe_catches_inner_exception(self, monkeypatch):
        # If the underlying probe function itself raises (rare — http_probe
        # already catches network errors), the dispatcher must still
        # return a structured failure.
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test")

        def _boom():
            raise RuntimeError("synthetic crash")

        monkeypatch.setitem(devconsole._PROBES, "elevenlabs", _boom)
        result = devconsole.probe("elevenlabs")
        assert result["ok"] is False
        assert "probe crashed" in result["error"]


# ---------------------------------------------------------------------------
# Layer 2 — admin routes
# ---------------------------------------------------------------------------

class TestSnapshotRoute:
    """GET /admin/api/devconsole/snapshot — auth + shape contract."""

    def test_anon_blocked(self, client):
        r = client.get("/admin/api/devconsole/snapshot")
        assert r.status_code in (302, 401, 403)

    def test_authed_returns_expected_shape(self, client):
        _require_admin_login(client)
        r = client.get("/admin/api/devconsole/snapshot")
        assert r.status_code == 200
        body = r.get_json()
        assert "providers" in body
        assert "runbook_state" in body
        assert isinstance(body["providers"], list)
        assert len(body["providers"]) == len(devconsole.PROVIDERS)

        state = body["runbook_state"]
        for key in [
            "image_variants_supported", "originals_on_disk", "variants_on_disk",
            "preconnect_count", "bundle_source_count", "cacheable_endpoint_count",
            "feature_flag_count", "admin_email_set", "admin_phone_set",
            "velo_master_url_set", "velo_agent_key_set", "scheduler_loaded",
            "site_url",
        ]:
            assert key in state, f"runbook_state missing key {key!r}"

    def test_admin_email_flag_tracks_env_var(self, client, monkeypatch):
        _require_admin_login(client)
        monkeypatch.setenv("ADMIN_EMAIL", "ops@example.com")
        r = client.get("/admin/api/devconsole/snapshot")
        assert r.get_json()["runbook_state"]["admin_email_set"] is True
        monkeypatch.delenv("ADMIN_EMAIL", raising=False)
        r = client.get("/admin/api/devconsole/snapshot")
        assert r.get_json()["runbook_state"]["admin_email_set"] is False

    def test_snapshot_does_not_leak_provider_secret_values(self, client, monkeypatch):
        """The snapshot is supposed to surface booleans + counts, NOT
        secret values. Plant a uniquely-recognisable fake key in every
        provider env var, hit the endpoint, and assert no value matches
        anywhere in the serialised JSON. Catches a future refactor that
        accidentally starts including the actual key in the response."""
        import json
        _require_admin_login(client)
        canary = "CANARY_SECRET_VALUE_XYZ_98765"
        for ev in [
            "OPENAI_API_KEY", "AI_INTEGRATIONS_OPENAI_API_KEY",
            "ANTHROPIC_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
            "RESEND_API_KEY", "ELEVENLABS_API_KEY", "BRAVE_SEARCH_API_KEY",
            "YELP_API_KEY", "GOOGLE_PLACES_API_KEY", "TRIPADVISOR_API_KEY",
            "VELO_AGENT_KEY",
        ]:
            monkeypatch.setenv(ev, canary)
        r = client.get("/admin/api/devconsole/snapshot")
        assert r.status_code == 200
        body_text = json.dumps(r.get_json())
        assert canary not in body_text, (
            f"snapshot leaked a secret value into the JSON response: {body_text[:300]}..."
        )


class TestTestProviderRoute:
    """POST /admin/api/devconsole/test-provider — CSRF, payload validation,
    and probe-dispatch (with mocked probe so no real network call fires)."""

    def test_anon_blocked(self, client):
        r = client.post(
            "/admin/api/devconsole/test-provider",
            json={"provider": "openai"},
        )
        assert r.status_code in (302, 401, 403)

    def test_csrf_required(self, client):
        _require_admin_login(client)
        r = client.post(
            "/admin/api/devconsole/test-provider",
            json={"provider": "openai"},
        )
        assert r.status_code == 403, f"expected CSRF rejection, got {r.status_code}"

    def test_missing_provider_field(self, client):
        _require_admin_login(client)
        h = _csrf_headers(client)
        r = client.post(
            "/admin/api/devconsole/test-provider",
            json={}, headers=h,
        )
        assert r.status_code == 400
        assert "provider" in (r.get_json() or {}).get("error", "").lower()

    def test_unknown_provider_returns_400_with_known_list(self, client):
        _require_admin_login(client)
        h = _csrf_headers(client)
        r = client.post(
            "/admin/api/devconsole/test-provider",
            json={"provider": "definitely-not-real"}, headers=h,
        )
        assert r.status_code == 400
        body = r.get_json()
        assert "unknown provider" in body["error"]
        assert set(body["known"]) == set(devconsole.PROVIDERS)

    def test_known_provider_dispatches_to_probe(self, client, monkeypatch):
        _require_admin_login(client)
        h = _csrf_headers(client)

        # Mock the probe so no real network call fires AND the test
        # is independent of whether the env actually has a real key.
        monkeypatch.setattr(devconsole, "probe",
                            lambda name: {"ok": True, "latency_ms": 42, "error": None})
        r = client.post(
            "/admin/api/devconsole/test-provider",
            json={"provider": "openai"}, headers=h,
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True
        assert body["latency_ms"] == 42
        assert body["provider"] == "openai"  # route adds this for UI convenience


class TestTestEmailRoute:
    """POST /admin/api/devconsole/test-email — fixed-recipient safety net
    (only ever sends to ADMIN_EMAIL, never an arbitrary address)."""

    def test_anon_blocked(self, client):
        assert client.post("/admin/api/devconsole/test-email").status_code in (302, 401, 403)

    def test_csrf_required(self, client):
        _require_admin_login(client)
        assert client.post("/admin/api/devconsole/test-email").status_code == 403

    def test_admin_email_unset_returns_400(self, client, monkeypatch):
        _require_admin_login(client)
        h = _csrf_headers(client)
        monkeypatch.delenv("ADMIN_EMAIL", raising=False)
        r = client.post("/admin/api/devconsole/test-email", headers=h)
        assert r.status_code == 400
        assert "ADMIN_EMAIL" in (r.get_json() or {}).get("error", "")

    def test_success_path_uses_messaging_send_email(self, client, monkeypatch):
        _require_admin_login(client)
        h = _csrf_headers(client)
        monkeypatch.setenv("ADMIN_EMAIL", "ops@example.com")
        sent = {}

        def _fake_send_email(to, subject, html, **kw):
            sent["to"] = to
            sent["subject"] = subject
            return {"id": "msg_test123"}

        # Patch the binding inside app.py's module namespace so the
        # route picks up the fake — it imports `messaging` at module
        # load and calls `messaging.send_email(...)` from inside the
        # request handler, so the attribute on the messaging module
        # is what matters.
        monkeypatch.setattr(messaging, "send_email", _fake_send_email)
        r = client.post("/admin/api/devconsole/test-email", headers=h)
        assert r.status_code == 200, r.data
        body = r.get_json()
        assert body["ok"] is True
        assert body["to"] == "ops@example.com"
        assert body["provider_id"] == "msg_test123"
        # Recipient lock-in: route must use ADMIN_EMAIL, never a body field.
        assert sent["to"] == "ops@example.com"

    def test_provider_failure_returns_502(self, client, monkeypatch):
        _require_admin_login(client)
        h = _csrf_headers(client)
        monkeypatch.setenv("ADMIN_EMAIL", "ops@example.com")

        def _fake_boom(*a, **kw):
            raise messaging.MessagingError("Resend HTTP 401: invalid api key")

        monkeypatch.setattr(messaging, "send_email", _fake_boom)
        r = client.post("/admin/api/devconsole/test-email", headers=h)
        assert r.status_code == 502
        body = r.get_json()
        assert body["ok"] is False
        assert "invalid api key" in body["error"]

    def test_body_recipient_field_is_ignored(self, client, monkeypatch):
        """The route MUST NOT accept a recipient from the request body —
        the whole point of the fixed-recipient design is that a hijacked
        admin session can't be used as an outbound spam relay. If a
        future refactor accidentally starts honouring `to` from JSON,
        this test catches it."""
        _require_admin_login(client)
        h = _csrf_headers(client)
        monkeypatch.setenv("ADMIN_EMAIL", "ops@example.com")
        sent = {}

        def _fake_send_email(to, subject, html, **kw):
            sent["to"] = to
            return {"id": "msg_x"}

        monkeypatch.setattr(messaging, "send_email", _fake_send_email)
        r = client.post(
            "/admin/api/devconsole/test-email",
            json={"to": "attacker@evil.example.com",
                  "recipient": "also-attacker@evil.example.com",
                  "email": "still-attacker@evil.example.com"},
            headers=h,
        )
        assert r.status_code == 200, r.data
        assert sent["to"] == "ops@example.com"
        assert "attacker" not in sent["to"]
        assert r.get_json()["to"] == "ops@example.com"


class TestTestSmsRoute:
    """POST /admin/api/devconsole/test-sms — same fixed-recipient safety
    net pinned to ADMIN_PHONE."""

    def test_anon_blocked(self, client):
        assert client.post("/admin/api/devconsole/test-sms").status_code in (302, 401, 403)

    def test_csrf_required(self, client):
        _require_admin_login(client)
        assert client.post("/admin/api/devconsole/test-sms").status_code == 403

    def test_admin_phone_unset_returns_400(self, client, monkeypatch):
        _require_admin_login(client)
        h = _csrf_headers(client)
        monkeypatch.delenv("ADMIN_PHONE", raising=False)
        r = client.post("/admin/api/devconsole/test-sms", headers=h)
        assert r.status_code == 400
        assert "ADMIN_PHONE" in (r.get_json() or {}).get("error", "")

    def test_success_path_uses_messaging_send_sms(self, client, monkeypatch):
        _require_admin_login(client)
        h = _csrf_headers(client)
        monkeypatch.setenv("ADMIN_PHONE", "+15551234567")
        sent = {}

        def _fake_send_sms(to, body, **kw):
            sent["to"] = to
            sent["body"] = body
            return {"sid": "SM_test123", "num_segments": "1"}

        monkeypatch.setattr(messaging, "send_sms", _fake_send_sms)
        r = client.post("/admin/api/devconsole/test-sms", headers=h)
        assert r.status_code == 200, r.data
        body = r.get_json()
        assert body["ok"] is True
        assert body["to"] == "+15551234567"
        assert body["provider_sid"] == "SM_test123"
        assert body["segments"] == "1"
        assert sent["to"] == "+15551234567"

    def test_body_recipient_field_is_ignored(self, client, monkeypatch):
        """Mirror of the email test — the SMS route must also ignore
        any recipient field in the request body so a hijacked admin
        session can't be repurposed as an outbound SMS spam relay."""
        _require_admin_login(client)
        h = _csrf_headers(client)
        monkeypatch.setenv("ADMIN_PHONE", "+15551234567")
        sent = {}

        def _fake_send_sms(to, body, **kw):
            sent["to"] = to
            return {"sid": "SM_x", "num_segments": "1"}

        monkeypatch.setattr(messaging, "send_sms", _fake_send_sms)
        r = client.post(
            "/admin/api/devconsole/test-sms",
            json={"to": "+19998887777",
                  "phone": "+18887776666",
                  "recipient": "+17776665555"},
            headers=h,
        )
        assert r.status_code == 200, r.data
        assert sent["to"] == "+15551234567"
        assert "+1999" not in sent["to"]
        assert r.get_json()["to"] == "+15551234567"

    def test_success_path_writes_sms_cost_ledger_row(self, client, monkeypatch):
        """Even though the recipient is fixed to ADMIN_PHONE, the test
        send still bills against Twilio — confirm a ledger row is
        written so the cost dashboard accounts for it. Pinned in
        response to a code-review comment that admin utility paths
        bypassing the cost ledger create silent under-counting."""
        import app as app_module
        _require_admin_login(client)
        h = _csrf_headers(client)
        monkeypatch.setenv("ADMIN_PHONE", "+15551234567")

        def _fake_send_sms(to, body, **kw):
            return {"sid": "SM_ledger_test", "num_segments": "2"}

        monkeypatch.setattr(messaging, "send_sms", _fake_send_sms)
        recorded = {}

        def _fake_record_sms_cost(**kw):
            recorded.update(kw)

        monkeypatch.setattr(app_module, "record_sms_cost", _fake_record_sms_cost)
        r = client.post("/admin/api/devconsole/test-sms", headers=h)
        assert r.status_code == 200, r.data
        assert recorded.get("surface") == "sms_devconsole_test"
        assert recorded.get("provider") == "twilio"
        assert recorded.get("to_number") == "+15551234567"
        assert recorded.get("message_sid") == "SM_ledger_test"
        assert recorded.get("segments") == "2"


class TestReregisterVeloRoute:
    """POST /admin/api/devconsole/reregister-velo — env prerequisite
    + delegates to the existing register_with_velo helper."""

    def test_anon_blocked(self, client):
        assert client.post("/admin/api/devconsole/reregister-velo").status_code in (302, 401, 403)

    def test_csrf_required(self, client):
        _require_admin_login(client)
        assert client.post("/admin/api/devconsole/reregister-velo").status_code == 403

    def test_velo_master_url_unset_returns_400(self, client, monkeypatch):
        _require_admin_login(client)
        h = _csrf_headers(client)
        monkeypatch.delenv("VELO_MASTER_URL", raising=False)
        r = client.post("/admin/api/devconsole/reregister-velo", headers=h)
        assert r.status_code == 400
        assert "VELO_MASTER_URL" in (r.get_json() or {}).get("error", "")

    def test_success_path_calls_register_with_velo(self, client, monkeypatch):
        _require_admin_login(client)
        h = _csrf_headers(client)
        monkeypatch.setenv("VELO_MASTER_URL", "https://velo.example.com")

        import app as app_module
        called = {"force": None}

        def _fake_register(force=False):
            called["force"] = force

        monkeypatch.setattr(app_module, "register_with_velo", _fake_register)
        r = client.post("/admin/api/devconsole/reregister-velo", headers=h)
        assert r.status_code == 200, r.data
        body = r.get_json()
        assert body["ok"] is True
        # The route is documented to call with force=True so a stale
        # in-process "already registered" flag doesn't suppress the call.
        assert called["force"] is True
