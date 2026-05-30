"""Unit tests for M17 onboarding/auth pure bits (no DB / no network).

The /setup → provision → self-close flow and agency provisioning run against a
real Postgres in the gate; here we pin the password hashing + the env-fallback
branch of check_admin_password, and the preset registry shape.
"""

from admin_ai_platform import auth
from admin_ai_platform import config
from admin_ai_platform.blueprints.onboarding import PRESETS


def test_hash_is_deterministic_per_salt():
    salt = "00112233445566778899aabbccddeeff"
    h1 = auth._hash_password("secret", salt)
    h2 = auth._hash_password("secret", salt)
    assert h1 == h2 and len(h1) == 64           # sha256 hex


def test_hash_changes_with_salt_and_password():
    s1, s2 = "aa" * 16, "bb" * 16
    assert auth._hash_password("secret", s1) != auth._hash_password("secret", s2)
    assert auth._hash_password("secret", s1) != auth._hash_password("other", s1)


def test_check_admin_password_env_fallback(monkeypatch):
    # No DB password configured → fall back to env ADMIN_PASSWORD.
    monkeypatch.setattr(auth, "_db_admin_password_ok", lambda pw: None)
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "envpass")
    assert auth.check_admin_password("envpass") is True
    assert auth.check_admin_password("nope") is False
    assert auth.check_admin_password("") is False


def test_check_admin_password_prefers_db(monkeypatch):
    # When a DB password is set, env is ignored.
    monkeypatch.setattr(auth, "_db_admin_password_ok", lambda pw: pw == "dbpass")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "envpass")
    assert auth.check_admin_password("dbpass") is True
    assert auth.check_admin_password("envpass") is False


def test_presets_have_required_shape():
    assert "generic" in PRESETS
    for name, cfg in PRESETS.items():
        assert cfg["greeting"]
        assert isinstance(cfg["experiences"], list) and cfg["experiences"]
        for exp in cfg["experiences"]:
            assert len(exp) == 2   # (name, description)
