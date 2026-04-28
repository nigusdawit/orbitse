"""
Tests for the admin Performance tab — image-variant auto-cleanup
+ /admin/api/performance read-only stats + regenerate action.

Two layers:

1. **Pure helper** (`image_optimize.delete_variants`) — verifies the
   upload-time defense that prevents the 30-day-immutable footgun
   when an admin re-uploads a same-named image. Hits real storage
   (the local backend during tests) and cleans up its own files.

2. **Admin routes** (`/admin/api/performance`,
   `/admin/api/performance/regenerate-image-variants`) — verifies the
   auth gate (anon callers must NOT see stats) and the JSON shape
   (so the UI can rely on a stable contract). The bulk-regenerate
   round-trip is exercised end-to-end with a real synthetic image so
   the file-walk + delete + regenerate path is covered.

Tests share the dev `uploads/` directory with the running app, so
every test prefixes artifacts with `__perf_t__` and cleans up in a
try/finally — orphans would otherwise show up in the admin Media
Library and confuse the operator.
"""

import io
import os
import secrets

import pytest
from PIL import Image

import image_optimize
import storage


# ---- Helpers ----------------------------------------------------------------

def _unique_stem() -> str:
    return f"__perf_t__{secrets.token_hex(6)}"


def _make_jpeg_bytes(width: int = 2000, height: int = 1000) -> bytes:
    """Synthetic JPEG large enough to produce all three width variants."""
    img = Image.new("RGB", (width, height), color=(180, 60, 40))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _login(client):
    """Log into the admin with the env-provided ADMIN_PASSWORD. Returns
    the response or None if the password isn't set in the test env."""
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
    """Fetch a fresh CSRF token from the dedicated admin endpoint and
    return the header dict that the request middleware expects.
    Caller must already be logged in (admin_required gates the endpoint)."""
    r = client.get("/admin/api/csrf-token")
    assert r.status_code == 200, f"csrf-token endpoint returned {r.status_code} (login first?)"
    token = r.get_json()["csrf_token"]
    return {"X-CSRF-Token": token}


@pytest.fixture
def store():
    return storage.get_storage()


@pytest.fixture
def cleanup_stem(store):
    """Track stems written during a test and delete the source + every
    `<stem>-{400,800,1600}.webp` variant on exit, regardless of pass/fail."""
    stems: list[tuple[str, str]] = []  # (stem, ext)

    def _track(stem: str, ext: str = "jpg"):
        stems.append((stem, ext))

    yield _track

    for stem, ext in stems:
        for name in [f"{stem}.{ext}"] + [f"{stem}-{w}.webp" for w in (400, 800, 1600)]:
            try:
                store.delete(name)
            except Exception:
                pass


# ===========================================================================
# Layer 1 — image_optimize.delete_variants (the upload-time defense)
# ===========================================================================

class TestDeleteVariants:
    def test_returns_zero_when_no_variants_exist(self, store, cleanup_stem):
        """Calling delete_variants on a name that never had variants is a
        cheap no-op — 3 exists() probes that all return False, count 0.
        This is the dominant case (every fresh token_hex(8) upload)."""
        stem = _unique_stem()
        cleanup_stem(stem)
        assert image_optimize.delete_variants(f"{stem}.jpg") == 0

    def test_deletes_existing_variants_and_reports_count(self, store, cleanup_stem):
        """End-to-end: create variants via the real generator, then
        delete_variants must remove them all and return 3."""
        stem = _unique_stem()
        cleanup_stem(stem)
        source_name = f"{stem}.jpg"
        store.write_bytes(source_name, _make_jpeg_bytes(), content_type="image/jpeg")

        # Pre-warm produces variants at 400/800/1600 widths.
        generated = image_optimize.generate_webp_variants(source_name)
        assert len(generated) == 3, f"expected 3 variants, got {generated!r}"
        for w in (400, 800, 1600):
            assert store.exists(f"{stem}-{w}.webp"), f"variant {w} missing after pre-warm"

        # The defense — exactly 3 deletions, all variants gone, source untouched.
        assert image_optimize.delete_variants(source_name) == 3
        for w in (400, 800, 1600):
            assert not store.exists(f"{stem}-{w}.webp"), f"variant {w} survived delete"
        assert store.exists(source_name), "source must NOT be deleted by variant cleanup"

    def test_is_idempotent(self, store, cleanup_stem):
        """A second call after a successful cleanup returns 0 and never
        raises — important so the upload handler can call it
        unconditionally on every upload."""
        stem = _unique_stem()
        cleanup_stem(stem)
        source_name = f"{stem}.jpg"
        store.write_bytes(source_name, _make_jpeg_bytes(), content_type="image/jpeg")
        image_optimize.generate_webp_variants(source_name)

        assert image_optimize.delete_variants(source_name) == 3
        assert image_optimize.delete_variants(source_name) == 0
        assert image_optimize.delete_variants(source_name) == 0

    def test_only_touches_matching_stem_variants(self, store, cleanup_stem):
        """Deleting variants for stem-A must not touch variants for stem-B.
        Filename-collision-without-this-bug regression test."""
        stem_a = _unique_stem()
        stem_b = _unique_stem()
        cleanup_stem(stem_a)
        cleanup_stem(stem_b)
        for s in (stem_a, stem_b):
            store.write_bytes(f"{s}.jpg", _make_jpeg_bytes(), content_type="image/jpeg")
            image_optimize.generate_webp_variants(f"{s}.jpg")

        assert image_optimize.delete_variants(f"{stem_a}.jpg") == 3
        # stem_b variants still present
        for w in (400, 800, 1600):
            assert store.exists(f"{stem_b}-{w}.webp"), \
                f"unrelated stem_b variant {w} was deleted"

    @pytest.mark.parametrize("name", [
        "abc.gif",         # excluded format
        "abc.webp",        # already webp — no derived variants exist
        "abc.svg",         # vector
        "no_extension",    # malformed filename
    ])
    def test_skips_non_image_extensions(self, store, name):
        """delete_variants short-circuits on non-{jpg,jpeg,png} so it
        never tries to delete keys that couldn't have been generated."""
        assert image_optimize.delete_variants(name) == 0

    def test_survives_storage_delete_failure_and_reports_partial(
        self, store, cleanup_stem, monkeypatch
    ):
        """If the storage backend errors on one width's delete, the
        function logs and continues to the next width rather than
        bubbling — partial cleanup is strictly better than blocking
        the upload over a transient backend error."""
        stem = _unique_stem()
        cleanup_stem(stem)
        source_name = f"{stem}.jpg"
        store.write_bytes(source_name, _make_jpeg_bytes(), content_type="image/jpeg")
        image_optimize.generate_webp_variants(source_name)

        original_delete = store.delete
        target = f"{stem}-800.webp"
        calls = {"raised": False}

        def flaky_delete(subpath):
            if subpath == target and not calls["raised"]:
                calls["raised"] = True
                raise RuntimeError("simulated transient backend failure")
            return original_delete(subpath)

        monkeypatch.setattr(store, "delete", flaky_delete)

        deleted = image_optimize.delete_variants(source_name)
        # 400 + 1600 succeed; 800 raised, was logged + skipped, count = 2.
        assert deleted == 2
        assert calls["raised"] is True
        # Recover by calling without the patch — orphan 800 still present
        # so cleanup_stem can wipe it; assert presence so we know what
        # state the test left behind for the fixture to mop up.
        monkeypatch.setattr(store, "delete", original_delete)
        assert store.exists(target), \
            "the 800 variant should have survived the simulated failure"


# ===========================================================================
# Layer 2 — Admin routes
# ===========================================================================

class TestPerformanceStatsRoute:
    def test_anon_caller_blocked(self, client):
        """admin_required must bounce unauthenticated GET to login or 401
        — never serve perf stats to the public."""
        r = client.get("/admin/api/performance", follow_redirects=False)
        assert r.status_code in (302, 401), \
            f"expected auth-deny (302/401), got {r.status_code}"

    def test_returns_expected_shape(self, client):
        _require_admin_login(client)
        r = client.get("/admin/api/performance")
        assert r.status_code == 200, f"expected 200, got {r.status_code} body={r.data!r}"
        body = r.get_json()
        assert isinstance(body, dict)
        # Top-level sections — the UI relies on every key being present.
        for key in ("bundle", "images", "db_pool", "cdn_uploads",
                    "api_cache", "preconnect"):
            assert key in body, f"missing top-level section {key!r} in {body!r}"

    def test_bundle_section_has_size_fields(self, client):
        _require_admin_login(client)
        r = client.get("/admin/api/performance")
        body = r.get_json()
        b = body["bundle"]
        if "error" in b:
            pytest.skip(f"bundle stats errored on this host: {b['error']}")
        # If the bundle section loaded, these MUST be numbers, not None.
        assert isinstance(b.get("raw_size_bytes"), int)
        assert isinstance(b.get("min_size_bytes"), int)
        assert b["raw_size_bytes"] > 0
        assert b["min_size_bytes"] > 0
        assert b["min_size_bytes"] <= b["raw_size_bytes"], "minified must be smaller"

    def test_db_pool_section_reports_configured_sizes(self, client):
        _require_admin_login(client)
        body = client.get("/admin/api/performance").get_json()
        p = body["db_pool"]
        if "error" in p:
            pytest.skip(f"db_pool stats errored on this host: {p['error']}")
        assert isinstance(p["configured_min"], int) and p["configured_min"] >= 1
        assert isinstance(p["configured_max"], int) and p["configured_max"] >= p["configured_min"]

    def test_api_cache_section_lists_endpoints(self, client):
        _require_admin_login(client)
        body = client.get("/admin/api/performance").get_json()
        a = body["api_cache"]
        if "error" in a:
            pytest.skip(f"api_cache stats errored: {a['error']}")
        # Must include at least the bundle endpoint (which is the
        # central one Optimization #3 was built around).
        assert "/api/page-bundle" in a["endpoints"]
        assert a["endpoint_count"] == len(a["endpoints"])


class TestRegenerateVariantsRoute:
    def test_anon_caller_blocked(self, client):
        """The bulk-regenerate POST is admin-only — anon callers must
        not be able to trigger a CPU-heavy walk over /uploads."""
        r = client.post(
            "/admin/api/performance/regenerate-image-variants",
            follow_redirects=False,
        )
        assert r.status_code in (302, 401), \
            f"expected auth-deny (302/401), got {r.status_code}"

    def test_authed_post_without_csrf_token_blocked(self, client):
        """Admin caller still must send a CSRF token — the regenerate
        endpoint inherits the same Tier 7 contract as every other
        authed admin POST. Pinning here so a future "let's exempt
        the perf endpoint" refactor is caught immediately."""
        _require_admin_login(client)
        r = client.post(
            "/admin/api/performance/regenerate-image-variants",
            follow_redirects=False,
        )
        assert r.status_code == 403, \
            f"expected 403 csrf_failed, got {r.status_code} body={r.data!r}"
        body = r.get_json()
        assert body and body.get("csrf_failed") is True, \
            f"expected csrf_failed body, got {body!r}"

    def test_non_local_backend_returns_400_with_backend_marker(self, client, monkeypatch):
        """S3 (and any future non-local backend) must NOT enumerate the
        bucket from a single request — the contract is a 400 with the
        offending backend name in the body so the admin UI can render
        the right "use a script instead" hint."""
        _require_admin_login(client)
        # Patch the backend NAME without touching the backend itself —
        # the route only inspects .name to gate the operation.
        import storage as _storage
        real_store = _storage.get_storage()
        monkeypatch.setattr(real_store, "name", "s3", raising=False)
        try:
            r = client.post(
                "/admin/api/performance/regenerate-image-variants",
                headers=_csrf_headers(client),
            )
        finally:
            # monkeypatch teardown restores the original .name
            pass
        assert r.status_code == 400, f"expected 400, got {r.status_code} body={r.data!r}"
        body = r.get_json()
        assert isinstance(body, dict)
        assert body.get("backend") == "s3", \
            f"expected backend marker 's3' in body, got {body!r}"
        assert "error" in body and "local" in body["error"].lower(), \
            f"error message should mention local-only constraint, got {body!r}"

    def test_local_backend_returns_counts(self, client, store, cleanup_stem):
        """End-to-end on the local backend: drop a synthetic source
        image into uploads, hit the regenerate endpoint, verify the
        variants appear and the response counts are sane."""
        if store.name != "local":
            pytest.skip("regenerate is local-storage-only by design")
        _require_admin_login(client)

        # Seed one source image — the regenerate walk should pick it up.
        stem = _unique_stem()
        cleanup_stem(stem)
        source_name = f"{stem}.jpg"
        store.write_bytes(source_name, _make_jpeg_bytes(), content_type="image/jpeg")

        # Pre-condition: variants don't exist yet.
        for w in (400, 800, 1600):
            assert not store.exists(f"{stem}-{w}.webp")

        r = client.post(
            "/admin/api/performance/regenerate-image-variants",
            headers=_csrf_headers(client),
        )
        assert r.status_code == 200, f"got {r.status_code} body={r.data!r}"
        body = r.get_json()
        assert isinstance(body, dict)
        for k in ("regenerated", "skipped", "errors", "total_scanned"):
            assert k in body and isinstance(body[k], int), \
                f"missing or non-int counter {k!r} in {body!r}"

        # Our seeded image must have been regenerated; total_scanned is
        # >= 1 because the dev uploads dir has many real images too.
        assert body["total_scanned"] >= 1
        assert body["regenerated"] >= 1
        assert body["errors"] == 0

        # Variants for our seed image now exist.
        for w in (400, 800, 1600):
            assert store.exists(f"{stem}-{w}.webp"), \
                f"variant {w} should exist after regenerate"
