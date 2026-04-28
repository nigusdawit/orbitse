"""
Tests for the admin Stripe console — settings, mode toggle, autosync,
product sync engine, and the read-only routes (sync-status,
recent-checkouts, probe).

Three layers, mirroring the structure of test_admin_devconsole.py:

1. **Pure helpers** (`stripe_settings.*`, `stripe_client._env_keys_for_mode`,
   `stripe_client.detect_active_key_kind`) — mode toggle round-trip,
   key resolver mode-awareness, soft fallback for sk_test_ keys held
   in the live env var slot. No Flask, no network.

2. **Sync engine** (`stripe_sync.*`) — create / update / update-with-
   price-change / archive / backfill paths, with a fully-mocked Stripe
   SDK (no quota burned). Verifies the mapping table is written
   correctly and that ALL Stripe failures are captured into
   `last_error` — never raised out — so a Stripe outage cannot break
   local product CRUD.

3. **Admin routes** (`/admin/api/stripe/*`) — auth gate (anon → 401),
   CSRF gate on every POST, settings GET shape, mode/autosync toggles
   round-trip, probe handles SDK error gracefully, recent-checkouts
   passes through the SDK list. The product CRUD hooks are also
   covered here (autosync ON fires sync_product, autosync OFF skips,
   Stripe SDK exception inside the hook still returns 200/201).

ZERO real Stripe API calls — every test that touches the SDK does
`monkeypatch.setattr(stripe_client, "get_stripe", lambda: <fake>)`.
"""

import os
import json
import types

import pytest

import app as _app
import stripe_settings
import stripe_client
import stripe_sync


# ---------------------------------------------------------------------------
# Helpers
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


class _FakeStripeProduct:
    """Stand-in for stripe.Product class — call list of records what
    happened during a test for assertions."""
    def __init__(self, log):
        self.log = log

    def create(self, **kw):
        self.log.append(("Product.create", kw))
        return {"id": "prod_fake_" + str(len(self.log))}

    def modify(self, sid, **kw):
        self.log.append(("Product.modify", sid, kw))
        return {"id": sid}


class _FakeStripePrice:
    def __init__(self, log):
        self.log = log

    def create(self, **kw):
        self.log.append(("Price.create", kw))
        return {"id": "price_fake_" + str(len(self.log))}

    def modify(self, sid, **kw):
        self.log.append(("Price.modify", sid, kw))
        return {"id": sid}


class _FakeStripe:
    """Top-level fake mirroring the `stripe` module surface used by
    sync code: `Product`, `Price`, `Account`, `checkout.Session`."""
    def __init__(self, log=None):
        self.log = log if log is not None else []
        self.Product = _FakeStripeProduct(self.log)
        self.Price = _FakeStripePrice(self.log)
        self.Account = types.SimpleNamespace(
            retrieve=lambda: {"id": "acct_fake_test"}
        )
        self.checkout = types.SimpleNamespace(
            Session=types.SimpleNamespace(
                list=lambda limit=50: {"data": []}
            )
        )


def _make_local_product(name="Test Mug", price_cents=2500, currency="USD"):
    """Insert a real product row, return its dict. Tests clean up by
    deleting via the same DB layer to keep the row count stable."""
    row = _app.query_db(
        """
        INSERT INTO products
          (slug, name, description, price_cents, currency, image_url,
           gallery_images, stock, track_inventory, active, sort_order)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            "stripe-test-" + os.urandom(4).hex(),
            name, "Test product for stripe sync tests",
            price_cents, currency, "",
            json.dumps([]),
            10, True, True, 0,
        ),
        fetchone=True,
    )
    return dict(row)


def _delete_local_product(pid):
    try:
        _app.query_db("DELETE FROM products WHERE id = %s", (pid,))
    except Exception:
        pass


# ===========================================================================
# Layer 1 — pure helpers
# ===========================================================================

class TestStripeSettings:

    def test_get_settings_returns_defaults_shape(self):
        s = stripe_settings.get_settings()
        # Required keys present + correct types regardless of DB state.
        assert isinstance(s["mode"], str)
        assert s["mode"] in ("test", "live")
        assert isinstance(s["autosync_products"], bool)
        assert "last_health_check_at" in s
        assert "last_health_ok" in s
        assert "last_health_error" in s
        assert "last_backfill_at" in s
        assert isinstance(s["last_backfill_summary"], dict)

    def test_set_mode_round_trip(self):
        original = stripe_settings.get_mode()
        try:
            stripe_settings.set_mode("test")
            assert stripe_settings.get_mode() == "test"
            stripe_settings.set_mode("live")
            assert stripe_settings.get_mode() == "live"
        finally:
            stripe_settings.set_mode(original)

    def test_set_mode_rejects_invalid(self):
        with pytest.raises(ValueError):
            stripe_settings.set_mode("bogus")

    def test_set_autosync_round_trip(self):
        original = stripe_settings.get_settings()["autosync_products"]
        try:
            stripe_settings.set_autosync(True)
            assert stripe_settings.get_settings()["autosync_products"] is True
            stripe_settings.set_autosync(False)
            assert stripe_settings.get_settings()["autosync_products"] is False
        finally:
            stripe_settings.set_autosync(original)

    def test_record_health_never_raises(self):
        # Should be a no-op even if everything is missing — important.
        stripe_settings.record_health(True, "")
        stripe_settings.record_health(False, "x" * 5000)


class TestStripeKeyResolver:

    def test_env_keys_for_test_mode_picks_test_pair(self, monkeypatch):
        monkeypatch.setenv("STRIPE_TEST_SECRET_KEY", "sk_test_abc")
        monkeypatch.setenv("STRIPE_TEST_PUBLISHABLE_KEY", "pk_test_xyz")
        monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
        s, p, _ = stripe_client._env_keys_for_mode("test")
        assert s == "sk_test_abc"
        assert p == "pk_test_xyz"

    def test_env_keys_for_test_mode_soft_fallback_to_live_if_test_key(self, monkeypatch):
        monkeypatch.delenv("STRIPE_TEST_SECRET_KEY", raising=False)
        monkeypatch.delenv("STRIPE_TEST_PUBLISHABLE_KEY", raising=False)
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_real_test_key")
        monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_real_pub")
        s, p, _ = stripe_client._env_keys_for_mode("test")
        assert s == "sk_test_real_test_key"
        assert p == "pk_test_real_pub"

    def test_env_keys_for_test_mode_no_fallback_to_live_real_key(self, monkeypatch):
        monkeypatch.delenv("STRIPE_TEST_SECRET_KEY", raising=False)
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_real_live_key")
        s, _, _ = stripe_client._env_keys_for_mode("test")
        # Must NOT silently grant live key in test mode.
        assert s is None

    def test_env_keys_for_live_mode_picks_live_pair(self, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_xxx")
        s, _, _ = stripe_client._env_keys_for_mode("live")
        assert s == "sk_live_xxx"

    def test_detect_active_key_kind_categorises_by_prefix(self, monkeypatch):
        # Bypass connector + cache to make this purely env-driven.
        monkeypatch.setattr(stripe_client, "_fetch_replit_connection", lambda: None)
        stripe_client.invalidate_cache()
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_abc")
        monkeypatch.delenv("STRIPE_TEST_SECRET_KEY", raising=False)
        # Force live mode but the live env-var holds a test key.
        monkeypatch.setattr(stripe_client, "_get_mode", lambda: "live")
        stripe_client.invalidate_cache()
        assert stripe_client.detect_active_key_kind() == "test"

        stripe_client.invalidate_cache()
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_xyz")
        assert stripe_client.detect_active_key_kind() == "live"

    def test_detect_keys_present_returns_booleans_only(self):
        d = stripe_client.detect_keys_present()
        for k, v in d.items():
            assert isinstance(v, bool), f"{k} -> {v!r} is not bool"
        assert "live_secret" in d
        assert "test_secret" in d
        assert "replit_connector" in d


# ===========================================================================
# Layer 2 — sync engine (mocked Stripe SDK)
# ===========================================================================

class TestStripeSyncEngine:

    def test_sync_product_create_path(self, monkeypatch):
        prod = _make_local_product(name="Sync Mug", price_cents=1234)
        try:
            log = []
            fake = _FakeStripe(log)
            monkeypatch.setattr(stripe_client, "get_stripe", lambda: fake)
            stripe_settings.set_mode("test")

            # Wipe any pre-existing mapping for cleanliness.
            _app.query_db(
                "DELETE FROM stripe_product_sync WHERE local_product_id = %s",
                (prod["id"],),
            )

            res = stripe_sync.sync_product(prod["id"])
            assert res["ok"] is True
            assert res["action"] == "created"
            assert res["stripe_product_id"].startswith("prod_fake_")
            assert res["stripe_price_id"].startswith("price_fake_")
            # Both create calls happened.
            kinds = [r[0] for r in log]
            assert "Product.create" in kinds
            assert "Price.create" in kinds
            # Mapping persisted with the right cents.
            mapping = _app.query_db(
                "SELECT * FROM stripe_product_sync "
                "WHERE local_product_id = %s AND mode = %s",
                (prod["id"], "test"), fetchone=True,
            )
            assert mapping is not None
            assert mapping["synced_price_cents"] == 1234
            assert mapping["last_error"] == ""
        finally:
            _delete_local_product(prod["id"])

    def test_sync_product_price_change_creates_new_price(self, monkeypatch):
        prod = _make_local_product(name="Drift Mug", price_cents=1000)
        try:
            log = []
            fake = _FakeStripe(log)
            monkeypatch.setattr(stripe_client, "get_stripe", lambda: fake)
            stripe_settings.set_mode("test")
            _app.query_db(
                "DELETE FROM stripe_product_sync WHERE local_product_id = %s",
                (prod["id"],),
            )

            # First sync = create.
            r1 = stripe_sync.sync_product(prod["id"])
            assert r1["ok"] and r1["action"] == "created"
            old_price_id = r1["stripe_price_id"]

            # Bump the local price.
            _app.query_db(
                "UPDATE products SET price_cents = %s WHERE id = %s",
                (1500, prod["id"]),
            )

            r2 = stripe_sync.sync_product(prod["id"])
            assert r2["ok"] and r2["action"] == "updated_with_new_price"
            assert r2["stripe_price_id"] != old_price_id
            # Old price was archived.
            archived = [
                e for e in log
                if e[0] == "Price.modify" and e[1] == old_price_id
                and e[2].get("active") is False
            ]
            assert archived, f"expected old price to be flipped inactive — log={log!r}"
        finally:
            _delete_local_product(prod["id"])

    def test_sync_product_no_op_when_unchanged(self, monkeypatch):
        prod = _make_local_product(name="Stable Mug", price_cents=999)
        try:
            log = []
            fake = _FakeStripe(log)
            monkeypatch.setattr(stripe_client, "get_stripe", lambda: fake)
            stripe_settings.set_mode("test")
            _app.query_db(
                "DELETE FROM stripe_product_sync WHERE local_product_id = %s",
                (prod["id"],),
            )

            stripe_sync.sync_product(prod["id"])
            log.clear()
            r = stripe_sync.sync_product(prod["id"])
            assert r["ok"] and r["action"] == "updated"  # not _with_new_price
            # No new Price.create call — only Product.modify (mutable fields).
            assert not any(e[0] == "Price.create" for e in log)
        finally:
            _delete_local_product(prod["id"])

    def test_sync_product_captures_stripe_error(self, monkeypatch):
        prod = _make_local_product(name="Broken Mug", price_cents=500)
        try:
            class _Boom:
                def __getattr__(self, name):
                    raise RuntimeError("boom: " + name)
            monkeypatch.setattr(stripe_client, "get_stripe", lambda: _Boom())
            stripe_settings.set_mode("test")

            res = stripe_sync.sync_product(prod["id"])
            assert res["ok"] is False
            assert "boom" in (res.get("error") or "").lower() \
                or "RuntimeError" in (res.get("error") or "")
            mapping = _app.query_db(
                "SELECT last_error FROM stripe_product_sync "
                "WHERE local_product_id = %s AND mode = %s",
                (prod["id"], "test"), fetchone=True,
            )
            assert mapping is not None
            assert mapping["last_error"] != ""
        finally:
            _delete_local_product(prod["id"])

    def test_archive_product_skips_when_no_mapping(self, monkeypatch):
        prod = _make_local_product(name="Lone Mug", price_cents=100)
        try:
            # No mapping => archive returns the skipped marker, no SDK call.
            called = []
            monkeypatch.setattr(
                stripe_client, "get_stripe",
                lambda: (_ for _ in ()).throw(AssertionError("must not be called")),
            )
            res = stripe_sync.archive_product(prod["id"])
            assert "skipped" in res
        finally:
            _delete_local_product(prod["id"])

    def test_archive_product_flips_active_false(self, monkeypatch):
        prod = _make_local_product(name="Doomed Mug", price_cents=200)
        try:
            log = []
            fake = _FakeStripe(log)
            # archive_product uses get_stripe_for_mode (not get_stripe) so
            # it can target an arbitrary mode without mutating the global
            # setting. sync_product uses get_stripe.
            monkeypatch.setattr(stripe_client, "get_stripe", lambda: fake)
            monkeypatch.setattr(
                stripe_client, "get_stripe_for_mode", lambda mode: fake,
            )
            stripe_settings.set_mode("test")
            _app.query_db(
                "DELETE FROM stripe_product_sync WHERE local_product_id = %s",
                (prod["id"],),
            )
            stripe_sync.sync_product(prod["id"])  # create mapping
            log.clear()

            res = stripe_sync.archive_product(prod["id"])
            assert "test" in res and res["test"].get("ok") is True
            assert any(
                e[0] == "Product.modify" and e[2].get("active") is False
                for e in log
            )
        finally:
            _delete_local_product(prod["id"])

    def test_archive_product_does_not_mutate_global_mode(self, monkeypatch):
        """Regression test: archive_product must NEVER write the persisted
        global mode while iterating over per-mode mappings — doing so
        would race with concurrent requests and could leave the process
        in the wrong mode if we crash mid-loop. See get_stripe_for_mode."""
        prod = _make_local_product(name="Race-test Mug", price_cents=300)
        try:
            log = []
            fake = _FakeStripe(log)
            monkeypatch.setattr(stripe_client, "get_stripe", lambda: fake)
            monkeypatch.setattr(
                stripe_client, "get_stripe_for_mode", lambda mode: fake,
            )

            # Trip-wire: any call to set_mode during archive is a bug.
            real_set_mode = stripe_settings.set_mode
            calls = []

            def _tripwire(m):
                calls.append(m)
                return real_set_mode(m)

            stripe_settings.set_mode("live")  # arbitrary starting mode
            # Build mappings for BOTH modes so the loop iterates twice.
            stripe_settings.set_mode("test")
            stripe_sync.sync_product(prod["id"])
            stripe_settings.set_mode("live")
            stripe_sync.sync_product(prod["id"])

            calls.clear()
            monkeypatch.setattr(stripe_settings, "set_mode", _tripwire)
            mode_before = stripe_settings.get_mode()
            res = stripe_sync.archive_product(prod["id"])
            mode_after = stripe_settings.get_mode()

            assert calls == [], (
                f"archive_product mutated global mode: {calls}"
            )
            assert mode_before == mode_after
            assert "test" in res and "live" in res
        finally:
            _delete_local_product(prod["id"])

    def test_backfill_returns_counts(self, monkeypatch):
        log = []
        fake = _FakeStripe(log)
        monkeypatch.setattr(stripe_client, "get_stripe", lambda: fake)
        stripe_settings.set_mode("test")

        result = stripe_sync.backfill_all()
        assert "synced" in result
        assert "failed" in result
        assert "errors" in result
        assert isinstance(result["synced"], int)
        assert isinstance(result["failed"], int)


# ===========================================================================
# Layer 3 — admin routes
# ===========================================================================

class TestStripeAdminRoutesAuth:

    def test_settings_requires_admin(self, client):
        r = client.get("/admin/api/stripe/settings")
        assert r.status_code in (302, 401, 403)

    def test_mode_requires_admin(self, client):
        r = client.post(
            "/admin/api/stripe/mode",
            json={"mode": "test"},
        )
        assert r.status_code in (302, 401, 403)

    def test_autosync_requires_admin(self, client):
        r = client.post(
            "/admin/api/stripe/autosync",
            json={"enabled": True},
        )
        assert r.status_code in (302, 401, 403)

    def test_sync_status_requires_admin(self, client):
        r = client.get("/admin/api/stripe/sync-status")
        assert r.status_code in (302, 401, 403)


class TestStripeAdminRoutesAuthed:

    def test_settings_get_shape(self, client):
        _require_admin_login(client)
        r = client.get("/admin/api/stripe/settings")
        assert r.status_code == 200
        body = r.get_json()
        assert body["mode"] in ("test", "live")
        assert isinstance(body["autosync_products"], bool)
        assert isinstance(body["keys_present"], dict)
        assert "live_secret" in body["keys_present"]
        assert "test_secret" in body["keys_present"]
        assert body["active_key_kind"] in ("test", "live", "unknown")
        assert "health" in body
        assert "last_backfill" in body
        assert "mode_mismatch" in body and isinstance(body["mode_mismatch"], bool)

    def test_settings_mode_mismatch_is_symmetric(self, client, monkeypatch):
        """mode_mismatch must flag BOTH directions: test→live (charges
        sandbox while admin thinks they're charging real cards) AND
        live→test (real cards charged while admin thinks they're in
        sandbox). The earlier one-way check missed the test→live case."""
        _require_admin_login(client)
        original = stripe_settings.get_mode()
        try:
            # Case A: persisted mode=live, resolved key=test  → mismatch.
            stripe_settings.set_mode("live")
            monkeypatch.setattr(
                stripe_client, "detect_active_key_kind", lambda: "test",
            )
            r = client.get("/admin/api/stripe/settings")
            assert r.get_json()["mode_mismatch"] is True

            # Case B: persisted mode=test, resolved key=live  → ALSO mismatch
            # (the inverse case the original implementation missed).
            stripe_settings.set_mode("test")
            monkeypatch.setattr(
                stripe_client, "detect_active_key_kind", lambda: "live",
            )
            r = client.get("/admin/api/stripe/settings")
            assert r.get_json()["mode_mismatch"] is True

            # Case C: persisted mode=test, resolved key=test → no mismatch.
            monkeypatch.setattr(
                stripe_client, "detect_active_key_kind", lambda: "test",
            )
            r = client.get("/admin/api/stripe/settings")
            assert r.get_json()["mode_mismatch"] is False

            # Case D: resolved key=unknown (no key configured) → no mismatch.
            monkeypatch.setattr(
                stripe_client, "detect_active_key_kind", lambda: "unknown",
            )
            r = client.get("/admin/api/stripe/settings")
            assert r.get_json()["mode_mismatch"] is False
        finally:
            stripe_settings.set_mode(original)

    def test_mode_round_trip(self, client, monkeypatch):
        _require_admin_login(client)
        # Don't burn quota — fake the probe out.
        fake = _FakeStripe([])
        monkeypatch.setattr(stripe_client, "get_stripe", lambda: fake)

        original = stripe_settings.get_mode()
        try:
            headers = _csrf_headers(client)
            r = client.post(
                "/admin/api/stripe/mode",
                data=json.dumps({"mode": "test"}),
                headers=headers,
            )
            assert r.status_code == 200
            body = r.get_json()
            assert body["ok"] is True
            assert body["mode"] == "test"
            assert "probe" in body
            assert stripe_settings.get_mode() == "test"
        finally:
            stripe_settings.set_mode(original)

    def test_mode_rejects_invalid(self, client):
        _require_admin_login(client)
        headers = _csrf_headers(client)
        r = client.post(
            "/admin/api/stripe/mode",
            data=json.dumps({"mode": "bogus"}),
            headers=headers,
        )
        assert r.status_code == 400

    def test_autosync_round_trip(self, client):
        _require_admin_login(client)
        original = stripe_settings.get_settings()["autosync_products"]
        try:
            headers = _csrf_headers(client)
            r = client.post(
                "/admin/api/stripe/autosync",
                data=json.dumps({"enabled": True}),
                headers=headers,
            )
            assert r.status_code == 200
            assert r.get_json()["autosync_products"] is True
            assert stripe_settings.get_settings()["autosync_products"] is True

            r2 = client.post(
                "/admin/api/stripe/autosync",
                data=json.dumps({"enabled": False}),
                headers=headers,
            )
            assert r2.get_json()["autosync_products"] is False
        finally:
            stripe_settings.set_autosync(original)

    def test_probe_handles_sdk_failure_gracefully(self, client, monkeypatch):
        _require_admin_login(client)
        # get_stripe raises => probe returns ok=false, NOT a 500.
        def _broken():
            raise RuntimeError("not configured")
        monkeypatch.setattr(stripe_client, "get_stripe", _broken)
        headers = _csrf_headers(client)
        r = client.post("/admin/api/stripe/probe", headers=headers)
        assert r.status_code == 200, r.data
        body = r.get_json()
        assert body["ok"] is False
        assert "error" in body

    def test_sync_status_returns_rows(self, client):
        _require_admin_login(client)
        r = client.get("/admin/api/stripe/sync-status")
        assert r.status_code == 200
        body = r.get_json()
        assert "rows" in body
        assert "mode" in body
        assert isinstance(body["rows"], list)

    def test_recent_checkouts_handles_failure(self, client, monkeypatch):
        _require_admin_login(client)
        def _broken():
            raise RuntimeError("no key")
        monkeypatch.setattr(stripe_client, "get_stripe", _broken)
        r = client.get("/admin/api/stripe/recent-checkouts")
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is False
        assert body["sessions"] == []


# ===========================================================================
# Layer 3b — product CRUD hook integration
# ===========================================================================

class TestProductCrudHook:

    def test_create_product_skips_sync_when_autosync_off(self, client, monkeypatch):
        _require_admin_login(client)
        stripe_settings.set_autosync(False)

        called = {"n": 0}
        def _spy(pid):
            called["n"] += 1
            return {"ok": True}
        monkeypatch.setattr(stripe_sync, "sync_product", _spy)

        headers = _csrf_headers(client)
        r = client.post(
            "/admin/api/products",
            data=json.dumps({
                "name": "Hook test (autosync off)",
                "price_cents": 100,
            }),
            headers=headers,
        )
        assert r.status_code == 201, r.data
        body = r.get_json()
        try:
            assert body["stripe_sync"]["skipped"] == "autosync_off"
            assert called["n"] == 0
        finally:
            _delete_local_product(body["id"])

    def test_create_product_fires_sync_when_autosync_on(self, client, monkeypatch):
        _require_admin_login(client)
        original = stripe_settings.get_settings()["autosync_products"]
        stripe_settings.set_autosync(True)
        try:
            called = {"n": 0, "id": None}
            def _spy(pid):
                called["n"] += 1
                called["id"] = pid
                return {"ok": True, "stripe_product_id": "prod_spy"}
            monkeypatch.setattr(stripe_sync, "sync_product", _spy)

            headers = _csrf_headers(client)
            r = client.post(
                "/admin/api/products",
                data=json.dumps({
                    "name": "Hook test (autosync on)",
                    "price_cents": 200,
                }),
                headers=headers,
            )
            assert r.status_code == 201, r.data
            body = r.get_json()
            try:
                assert called["n"] == 1
                assert called["id"] == body["id"]
                assert body["stripe_sync"]["ok"] is True
            finally:
                _delete_local_product(body["id"])
        finally:
            stripe_settings.set_autosync(original)

    def test_create_product_stripe_error_does_not_500(self, client, monkeypatch):
        """The whole point of the design: a Stripe failure must NOT
        block the local INSERT. Route still returns 201."""
        _require_admin_login(client)
        original = stripe_settings.get_settings()["autosync_products"]
        stripe_settings.set_autosync(True)
        try:
            def _boom(pid):
                raise RuntimeError("stripe down")
            monkeypatch.setattr(stripe_sync, "sync_product", _boom)

            headers = _csrf_headers(client)
            r = client.post(
                "/admin/api/products",
                data=json.dumps({
                    "name": "Hook test (stripe down)",
                    "price_cents": 50,
                }),
                headers=headers,
            )
            # Local INSERT succeeded — that's the contract.
            assert r.status_code == 201, r.data
            body = r.get_json()
            try:
                assert body["stripe_sync"]["ok"] is False
                assert "stripe down" in body["stripe_sync"]["error"]
            finally:
                _delete_local_product(body["id"])
        finally:
            stripe_settings.set_autosync(original)
