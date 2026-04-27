"""
Tests for Optimization #5 — CDN-fronting for /uploads/.

Covers:
  1. Origin redirect — when UPLOADS_PUBLIC_BASE_URL is set, /uploads/<file>
     returns 301 to the CDN URL (and the same for /uploads/voice/<file>).
  2. Origin-pull bypass — the X-CDN-Origin-Pull header skips the redirect
     so the CDN's own pulls don't loop forever.
  3. Cache-Control headers — applied to byte-serving responses for
     originals (1d) and variants (30d immutable) and to the redirects
     themselves (1d).
  4. /api/page-bundle exposes `uploads_public_base_url` so the frontend
     can mirror the same routing decision client-side.
  5. image_optimize.srcset_for honors both an explicit base_url param
     AND the env var.
  6. Frontend-backend parity drift guard — pin that public/script.js
     reads the same field name and uses the same trailing-slash
     normalization rule the Python side does. Catches the class of
     bugs where someone edits one side and forgets the other.

The tests use `monkeypatch.setenv` per-test so the session-scoped
`flask_app` fixture stays untouched. The CDN handlers in serve_upload /
serve_voice_file read the env var fresh on every request (via
`_uploads_public_base()`) precisely so monkeypatch works without an app
restart.
"""

import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# /uploads/<file> redirect behaviour
# ---------------------------------------------------------------------------

class TestUploadsCDNRedirect:
    """When UPLOADS_PUBLIC_BASE_URL is set, /uploads/<file> returns 301."""

    def test_redirect_when_env_set(self, client, monkeypatch):
        monkeypatch.setenv("UPLOADS_PUBLIC_BASE_URL", "https://cdn.example.com")
        # Filename doesn't have to exist on disk — the redirect is decided
        # before any storage lookup, so a clean nonexistent name keeps the
        # test independent of the dev uploads/ contents.
        resp = client.get("/uploads/__t5__redirect.jpg",
                          follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers["Location"] == "https://cdn.example.com/uploads/__t5__redirect.jpg"
        cache = resp.headers.get("Cache-Control", "")
        assert "public" in cache
        assert "max-age=86400" in cache

    def test_redirect_target_preserves_filename_unchanged(self, client, monkeypatch):
        monkeypatch.setenv("UPLOADS_PUBLIC_BASE_URL", "https://cdn.example.com")
        # Variant naming convention with a hyphen — must round-trip exactly.
        resp = client.get("/uploads/some-stem-800.webp", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers["Location"] == "https://cdn.example.com/uploads/some-stem-800.webp"

    def test_trailing_slashes_in_base_are_normalized(self, client, monkeypatch):
        # An operator who copy-pastes their CDN URL with a trailing slash
        # shouldn't get `https://cdn.example.com//uploads/x.jpg`.
        monkeypatch.setenv("UPLOADS_PUBLIC_BASE_URL", "https://cdn.example.com///")
        resp = client.get("/uploads/__t5__slashes.jpg", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers["Location"] == "https://cdn.example.com/uploads/__t5__slashes.jpg"

    def test_no_redirect_when_env_unset(self, client, monkeypatch):
        # Backward-compat: if the env var isn't set, behaviour is identical
        # to pre-Opt-5 (serve bytes, or 404 if missing).
        monkeypatch.delenv("UPLOADS_PUBLIC_BASE_URL", raising=False)
        resp = client.get("/uploads/__t5__nonexistent__.jpg",
                          follow_redirects=False)
        assert resp.status_code == 404

    def test_no_redirect_when_origin_pull_header_set(self, client, monkeypatch):
        # The CDN reaching back to fill its cache must NOT be redirected
        # back to itself, which would loop forever.
        monkeypatch.setenv("UPLOADS_PUBLIC_BASE_URL", "https://cdn.example.com")
        resp = client.get("/uploads/__t5__nonexistent__.jpg",
                          follow_redirects=False,
                          headers={"X-CDN-Origin-Pull": "1"})
        # Bypass header → falls through to normal serve → 404 because the
        # file genuinely doesn't exist on disk. The important thing is
        # status != 301 (no redirect).
        assert resp.status_code != 301
        assert resp.status_code == 404

    def test_origin_pull_header_only_active_when_value_is_1(self, client, monkeypatch):
        # Be strict: only `X-CDN-Origin-Pull: 1` triggers the bypass. A
        # garbage value is treated as a normal browser request → redirect.
        monkeypatch.setenv("UPLOADS_PUBLIC_BASE_URL", "https://cdn.example.com")
        monkeypatch.delenv("UPLOADS_CDN_PULL_SECRET", raising=False)
        resp = client.get("/uploads/__t5__strict.jpg",
                          follow_redirects=False,
                          headers={"X-CDN-Origin-Pull": "yes-please"})
        assert resp.status_code == 301


class TestUploadsCDNPullSecret:
    """Hardening: when UPLOADS_CDN_PULL_SECRET is set, the bypass header
    value must equal the secret. Defends against malicious clients that
    would otherwise force origin-serving by faking `X-CDN-Origin-Pull: 1`
    (a performance-degradation / DoS-amplification attack)."""

    def test_secret_unset_falls_back_to_value_1(self, client, monkeypatch):
        monkeypatch.setenv("UPLOADS_PUBLIC_BASE_URL", "https://cdn.example.com")
        monkeypatch.delenv("UPLOADS_CDN_PULL_SECRET", raising=False)
        resp = client.get("/uploads/__t5__fallback.jpg",
                          follow_redirects=False,
                          headers={"X-CDN-Origin-Pull": "1"})
        assert resp.status_code != 301  # bypass active

    def test_secret_set_requires_exact_match(self, client, monkeypatch):
        monkeypatch.setenv("UPLOADS_PUBLIC_BASE_URL", "https://cdn.example.com")
        monkeypatch.setenv("UPLOADS_CDN_PULL_SECRET", "s3cr3t-token")
        # Wrong value (the previously-valid "1") → no bypass → redirect.
        resp = client.get("/uploads/__t5__secret_wrong.jpg",
                          follow_redirects=False,
                          headers={"X-CDN-Origin-Pull": "1"})
        assert resp.status_code == 301
        # Right value → bypass active → falls through to serve (404 here).
        resp = client.get("/uploads/__t5__secret_right.jpg",
                          follow_redirects=False,
                          headers={"X-CDN-Origin-Pull": "s3cr3t-token"})
        assert resp.status_code != 301
        assert resp.status_code == 404

    def test_secret_set_no_header_means_no_bypass(self, client, monkeypatch):
        monkeypatch.setenv("UPLOADS_PUBLIC_BASE_URL", "https://cdn.example.com")
        monkeypatch.setenv("UPLOADS_CDN_PULL_SECRET", "s3cr3t-token")
        resp = client.get("/uploads/__t5__no_header.jpg", follow_redirects=False)
        assert resp.status_code == 301


class TestSelfLoopGuard:
    """When UPLOADS_PUBLIC_BASE_URL points at the SAME host as the
    request (operator pasted their own Flask URL by mistake), redirecting
    would 301 back to the same app forever. The guard detects host
    equality and falls through to serve bytes — degraded perf but
    working site, instead of an unrecoverable redirect loop."""

    def test_same_host_does_not_redirect(self, client, monkeypatch):
        # The Flask test client uses Host: localhost by default.
        monkeypatch.setenv("UPLOADS_PUBLIC_BASE_URL", "http://localhost")
        resp = client.get("/uploads/__t5__selfloop.jpg", follow_redirects=False)
        # Self-loop guard fires → falls through to normal serve → 404.
        assert resp.status_code != 301
        assert resp.status_code == 404

    def test_same_host_with_port_does_not_redirect(self, client, monkeypatch):
        # Test client sets `localhost` (no port) on Host. The guard does a
        # case-insensitive netloc-equality check; an http://localhost base
        # matches.
        monkeypatch.setenv("UPLOADS_PUBLIC_BASE_URL", "https://LOCALHOST")
        resp = client.get("/uploads/__t5__selfloop_case.jpg", follow_redirects=False)
        assert resp.status_code != 301

    def test_different_host_still_redirects(self, client, monkeypatch):
        monkeypatch.setenv("UPLOADS_PUBLIC_BASE_URL", "https://cdn.example.com")
        resp = client.get("/uploads/__t5__different_host.jpg",
                          follow_redirects=False)
        assert resp.status_code == 301


class TestVoiceCDNRedirect:
    """Voice cache files get the same CDN treatment as image originals."""

    def test_voice_redirect_when_env_set(self, client, monkeypatch):
        monkeypatch.setenv("UPLOADS_PUBLIC_BASE_URL", "https://cdn.example.com")
        resp = client.get("/uploads/voice/__t5__voice.mp3",
                          follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers["Location"] == "https://cdn.example.com/uploads/voice/__t5__voice.mp3"
        cache = resp.headers.get("Cache-Control", "")
        assert "max-age=86400" in cache

    def test_voice_no_redirect_when_origin_pull(self, client, monkeypatch):
        monkeypatch.setenv("UPLOADS_PUBLIC_BASE_URL", "https://cdn.example.com")
        resp = client.get("/uploads/voice/__t5__nonexistent__.mp3",
                          follow_redirects=False,
                          headers={"X-CDN-Origin-Pull": "1"})
        assert resp.status_code != 301
        assert resp.status_code == 404


class TestContractsRouteUnchanged:
    """Contracts deliberately stay on origin (operator business docs).
    This test pins that no future edit accidentally CDN-fronts them."""

    def test_contracts_route_does_not_redirect_even_when_env_set(self, client, monkeypatch):
        monkeypatch.setenv("UPLOADS_PUBLIC_BASE_URL", "https://cdn.example.com")
        resp = client.get("/uploads/contracts/__t5__contract.pdf",
                          follow_redirects=False)
        # File doesn't exist → 404. Important: not 301.
        assert resp.status_code != 301


# ---------------------------------------------------------------------------
# Cache-Control on byte-serving path
# ---------------------------------------------------------------------------

class TestUploadsCacheControl:
    """Long Cache-Control on actual byte responses (sets up the CDN cache
    even before the operator points anything at it)."""

    def _find_existing_upload(self, exts):
        uploads = Path(__file__).resolve().parents[1] / "uploads"
        if not uploads.exists():
            return None
        for p in sorted(uploads.iterdir()):
            if not p.is_file():
                continue
            if p.suffix.lower() not in exts:
                continue
            # Skip variant filenames (they pattern-match `*-NNN.webp` and
            # would test the variant cache header instead).
            stem = p.stem
            if any(stem.endswith(f"-{w}") for w in (400, 800, 1600)):
                continue
            return p
        return None

    def test_cache_control_on_existing_original_upload(self, client, monkeypatch):
        monkeypatch.delenv("UPLOADS_PUBLIC_BASE_URL", raising=False)
        sample = self._find_existing_upload({".jpg", ".jpeg", ".png", ".gif", ".webp"})
        if sample is None:
            pytest.skip("No upload files present to test against")
        resp = client.get(f"/uploads/{sample.name}")
        assert resp.status_code == 200
        cache = resp.headers.get("Cache-Control", "")
        assert "public" in cache, f"expected `public` in Cache-Control, got: {cache!r}"
        assert "max-age=86400" in cache, f"expected 1-day max-age, got: {cache!r}"
        # Originals are NOT marked immutable (admin re-upload of same hash
        # is rare but legal — variants get the immutable treatment).
        assert "immutable" not in cache

    def test_cache_control_on_variant(self, client, monkeypatch):
        monkeypatch.delenv("UPLOADS_PUBLIC_BASE_URL", raising=False)
        sample = self._find_existing_upload({".jpg", ".jpeg", ".png"})
        if sample is None:
            pytest.skip("No source image present to test variant against")
        variant_name = f"{sample.stem}-800.webp"
        resp = client.get(f"/uploads/{variant_name}")
        if resp.status_code != 200:
            # On-demand generation declined (e.g. animated PNG, broken file).
            # That's fine — the variant cache header is what we're testing,
            # which only applies on a successful serve.
            pytest.skip(f"Variant generation declined for {sample.name}")
        cache = resp.headers.get("Cache-Control", "")
        assert "public" in cache
        assert "max-age=2592000" in cache, f"expected 30-day max-age, got: {cache!r}"
        assert "immutable" in cache, f"expected `immutable` for variants, got: {cache!r}"


# ---------------------------------------------------------------------------
# /api/page-bundle exposes the CDN base
# ---------------------------------------------------------------------------

class TestPageBundleExposesCDN:

    def test_field_present_when_unset(self, client, monkeypatch):
        monkeypatch.delenv("UPLOADS_PUBLIC_BASE_URL", raising=False)
        resp = client.get("/api/page-bundle")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "uploads_public_base_url" in body, \
            "page-bundle must always include the field so the frontend can read it unconditionally"
        assert body["uploads_public_base_url"] == ""

    def test_field_present_and_normalized_when_set(self, client, monkeypatch):
        # Operator pastes a URL with a trailing slash → server strips it.
        monkeypatch.setenv("UPLOADS_PUBLIC_BASE_URL", "https://cdn.example.com/")
        resp = client.get("/api/page-bundle")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["uploads_public_base_url"] == "https://cdn.example.com"


# ---------------------------------------------------------------------------
# image_optimize.srcset_for honors the CDN base
# ---------------------------------------------------------------------------

class TestSrcsetForCDN:

    def test_no_base_returns_relative(self, monkeypatch):
        from image_optimize import srcset_for
        monkeypatch.delenv("UPLOADS_PUBLIC_BASE_URL", raising=False)
        result = srcset_for("/uploads/abc.jpg")
        assert result.count("400w") == 1
        assert "/uploads/abc-400.webp 400w" in result
        assert "/uploads/abc-800.webp 800w" in result
        assert "/uploads/abc-1600.webp 1600w" in result
        assert "https://" not in result

    def test_explicit_base_param(self, monkeypatch):
        from image_optimize import srcset_for
        monkeypatch.delenv("UPLOADS_PUBLIC_BASE_URL", raising=False)
        result = srcset_for("/uploads/abc.jpg", base_url="https://cdn.example.com")
        assert "https://cdn.example.com/uploads/abc-400.webp 400w" in result
        assert "https://cdn.example.com/uploads/abc-800.webp 800w" in result
        assert "https://cdn.example.com/uploads/abc-1600.webp 1600w" in result

    def test_env_base_picked_up_when_param_omitted(self, monkeypatch):
        from image_optimize import srcset_for
        monkeypatch.setenv("UPLOADS_PUBLIC_BASE_URL", "https://cdn.example.com")
        result = srcset_for("/uploads/abc.jpg")
        assert "https://cdn.example.com/uploads/abc-800.webp" in result

    def test_explicit_empty_param_overrides_env(self, monkeypatch):
        # Pass `base_url=""` to force the relative form even when the env
        # var is set — used by tests / debug renderers that want to compare.
        from image_optimize import srcset_for
        monkeypatch.setenv("UPLOADS_PUBLIC_BASE_URL", "https://cdn.example.com")
        result = srcset_for("/uploads/abc.jpg", base_url="")
        assert "https://" not in result
        assert "/uploads/abc-800.webp 800w" in result

    def test_trailing_slashes_stripped(self, monkeypatch):
        from image_optimize import srcset_for
        monkeypatch.delenv("UPLOADS_PUBLIC_BASE_URL", raising=False)
        result = srcset_for("/uploads/abc.jpg",
                            base_url="https://cdn.example.com///")
        assert "https://cdn.example.com/uploads/abc-800.webp" in result
        # Make sure we didn't produce `cdn.example.com//uploads/...`.
        assert "com//uploads" not in result

    def test_ineligible_url_returns_empty_with_or_without_base(self, monkeypatch):
        from image_optimize import srcset_for
        # Subpath uploads aren't eligible for variants — base shouldn't
        # change that decision.
        for base in ("", "https://cdn.example.com"):
            assert srcset_for("/uploads/voice/x.mp3", base_url=base) == ""
            assert srcset_for("/uploads/contracts/x.pdf", base_url=base) == ""
            assert srcset_for("https://other.com/x.jpg", base_url=base) == ""
            assert srcset_for("/uploads/x.gif", base_url=base) == ""


# ---------------------------------------------------------------------------
# Frontend / backend parity drift guard
# ---------------------------------------------------------------------------

class TestFrontendBackendCDNParity:
    """Pin the CDN handling in JS to the same shape the Python side emits.
    These tests catch the class of bugs where someone edits one side and
    forgets the other (which would silently break the perf optimization
    without breaking any functional behaviour)."""

    @pytest.fixture(scope="class")
    def script_js(self):
        return (Path(__file__).resolve().parents[1] / "public" / "script.js").read_text()

    def test_js_declares_img_uploads_base(self, script_js):
        assert "IMG_UPLOADS_BASE" in script_js, \
            "frontend must declare the IMG_UPLOADS_BASE module global"

    def test_js_reads_uploads_public_base_url_field(self, script_js):
        # The exact key the Python side puts into /api/page-bundle.
        assert "uploads_public_base_url" in script_js, (
            "frontend must read `uploads_public_base_url` from the bundle "
            "(same field name the Python side emits in api_page_bundle)"
        )

    def test_js_strips_trailing_slashes_like_python(self, script_js):
        # Python uses `.rstrip("/")` in _uploads_public_base. JS does the
        # same with the regex /\/+$/. Pin both.
        assert "/\\/+$/" in script_js or "/\\/+$/," in script_js or ".replace(/\\/+$/" in script_js, \
            "frontend must strip trailing slashes from the CDN base"

    def test_js_assigns_before_any_render(self, script_js):
        # The assignment must come BEFORE the first render call so every
        # imgAttrs/imgSrcset call sees the populated value. We verify by
        # ordering: IMG_UPLOADS_BASE = ... must appear before the
        # `siteSettings = bundle.site_settings` line (the first piece of
        # render data being unpacked).
        idx_assign = script_js.find("IMG_UPLOADS_BASE = ")
        idx_render_start = script_js.find("siteSettings = bundle.site_settings")
        assert idx_assign != -1, "IMG_UPLOADS_BASE must be assigned somewhere"
        assert idx_render_start != -1, "loadAllData must unpack site_settings"
        assert idx_assign < idx_render_start, (
            "IMG_UPLOADS_BASE assignment must come BEFORE site_settings unpack "
            "so the first render call sees a populated value"
        )
