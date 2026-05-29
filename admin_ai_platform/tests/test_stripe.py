"""Unit tests for the M11 Stripe pure helpers (no DB / no live SDK).

The full checkout/webhook/sync flows run against a real Postgres + fake SDK in
the gate runner; here we pin the env-key resolution and the product→Stripe
field mapping, which are pure functions and easy to regress.
"""

from admin_ai_platform.reused import stripe_client as sc
from admin_ai_platform.reused_di import stripe_sync as ss


def test_env_keys_live_mode(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_abc")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_live_abc")
    secret, pub, _ = sc._env_keys_for_mode("live")
    assert secret == "sk_live_abc" and pub == "pk_live_abc"


def test_env_keys_test_mode_soft_fallback(monkeypatch):
    # Only a live env var is set, but it actually holds a TEST key — accepted.
    monkeypatch.delenv("STRIPE_TEST_SECRET_KEY", raising=False)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_xyz")
    secret, _, _ = sc._env_keys_for_mode("test")
    assert secret == "sk_test_xyz"


def test_env_keys_test_mode_rejects_live_secret(monkeypatch):
    # A live secret must NOT be picked up in test mode (no sk_test_ prefix).
    monkeypatch.delenv("STRIPE_TEST_SECRET_KEY", raising=False)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_xyz")
    secret, _, _ = sc._env_keys_for_mode("test")
    assert secret is None


def test_detect_active_key_kind(monkeypatch):
    sc.invalidate_cache()
    monkeypatch.setattr(sc, "_resolve_keys", lambda *a, **k: ("sk_test_q", None, None))
    assert sc.detect_active_key_kind() == "test"
    monkeypatch.setattr(sc, "_resolve_keys", lambda *a, **k: ("sk_live_q", None, None))
    assert sc.detect_active_key_kind() == "live"
    monkeypatch.setattr(sc, "_resolve_keys", lambda *a, **k: (None, None, None))
    assert sc.detect_active_key_kind() == "unknown"


def test_normalize_currency():
    assert ss._normalize_currency("USD") == "usd"
    assert ss._normalize_currency("") == "usd"
    assert ss._normalize_currency(None) == "usd"


def test_gallery_to_image_list_dedup_and_cap():
    product = {"image_url": "a.jpg",
               "gallery_images": ["a.jpg", "b.jpg", "c.jpg"]}
    out = ss._gallery_to_image_list(product)
    assert out == ["a.jpg", "b.jpg", "c.jpg"]  # main not duplicated

    many = {"image_url": "0.jpg",
            "gallery_images": [f"{i}.jpg" for i in range(1, 20)]}
    assert len(ss._gallery_to_image_list(many)) == 8  # Stripe's 8-image cap


def test_gallery_handles_json_string():
    product = {"image_url": "", "gallery_images": '["x.jpg", "y.jpg"]'}
    assert ss._gallery_to_image_list(product) == ["x.jpg", "y.jpg"]
