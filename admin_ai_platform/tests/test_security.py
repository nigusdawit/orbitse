"""Unit tests for M19 secrets-at-rest crypto (pure, no DB/network).

CSRF enforcement + the DB-stored-credential round-trip run against a real app +
Postgres in the gate; here we pin the encryption primitives.
"""

import importlib

from admin_ai_platform import crypto


def _fresh_crypto(monkeypatch, key):
    """Reload the crypto module with a given SECRETS_ENCRYPTION_KEY so the cached
    Fernet instance is rebuilt from that key."""
    from admin_ai_platform import config
    monkeypatch.setattr(config, "SECRETS_ENCRYPTION_KEY", key)
    importlib.reload(crypto)
    return crypto


def test_roundtrip_and_tagging(monkeypatch):
    c = _fresh_crypto(monkeypatch, "unit-test-key")
    ct = c.encrypt("hunter2")
    assert ct.startswith("enc:v1:")
    assert "hunter2" not in ct
    assert c.decrypt(ct) == "hunter2"


def test_empty_passthrough(monkeypatch):
    c = _fresh_crypto(monkeypatch, "k")
    assert c.encrypt("") == ""
    assert c.encrypt(None) == ""
    assert c.decrypt("") == ""


def test_legacy_plaintext_passthrough(monkeypatch):
    c = _fresh_crypto(monkeypatch, "k")
    # A value that was never encrypted decrypts to itself.
    assert c.decrypt("legacy-token") == "legacy-token"
    assert c.is_encrypted("legacy-token") is False


def test_encrypt_if_plaintext_idempotent(monkeypatch):
    c = _fresh_crypto(monkeypatch, "k")
    once = c.encrypt_if_plaintext("abc")
    twice = c.encrypt_if_plaintext(once)
    assert once == twice and c.decrypt(twice) == "abc"


def test_wrong_key_fails_closed(monkeypatch):
    c = _fresh_crypto(monkeypatch, "key-A")
    ct = c.encrypt("secret")
    # Re-key: the old ciphertext must NOT decrypt — fails closed to ''.
    c2 = _fresh_crypto(monkeypatch, "key-B")
    assert c2.decrypt(ct) == ""


def test_corrupt_token_fails_closed(monkeypatch):
    c = _fresh_crypto(monkeypatch, "k")
    assert c.decrypt("enc:v1:not-a-real-token") == ""
