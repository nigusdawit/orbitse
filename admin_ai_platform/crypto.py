"""
admin_ai_platform.crypto
========================

Secrets-at-rest (M19). Symmetric authenticated encryption (Fernet / AES-128-CBC +
HMAC) for credentials we must store in the DB and later use in cleartext — e.g.
``mcp_servers.auth_credential`` (the bearer token sent to an MCP server). This is
NOT for passwords (those are one-way hashed in auth.py); it's for secrets the app
has to recover the plaintext of to make outbound calls.

Key resolution:
  1. ``SECRETS_ENCRYPTION_KEY`` (a urlsafe-base64 32-byte Fernet key) if set.
  2. Otherwise a key DERIVED from ``FLASK_SECRET_KEY`` (sha256 → urlsafe-base64),
     so encryption works out-of-the-box in dev. Set an explicit key in prod and
     rotate it deliberately (rotating either source makes old ciphertext
     undecryptable — decrypt() fails closed to '').

Stored values are tagged with a ``enc:v1:`` prefix so we can tell encrypted
values from legacy plaintext and migrate idempotently (encrypt_if_plaintext).
"""

from __future__ import annotations

import base64
import hashlib

from . import config

_PREFIX = "enc:v1:"
_fernet = None


def _derive_key() -> bytes:
    """Return a 32-byte urlsafe-base64 Fernet key from config (explicit or
    derived from FLASK_SECRET_KEY)."""
    explicit = (config.SECRETS_ENCRYPTION_KEY or "").strip()
    if explicit:
        # Accept a ready Fernet key as-is; otherwise hash it to the right shape.
        try:
            if len(base64.urlsafe_b64decode(explicit)) == 32:
                return explicit.encode()
        except Exception:
            pass
        digest = hashlib.sha256(explicit.encode()).digest()
        return base64.urlsafe_b64encode(digest)
    secret = (config.FLASK_SECRET_KEY or "dev-insecure").encode()
    return base64.urlsafe_b64encode(hashlib.sha256(secret).digest())


def _get_fernet():
    """Lazily build the Fernet instance. Returns None if the cryptography lib is
    unavailable (the package still imports; callers degrade to plaintext)."""
    global _fernet
    if _fernet is not None:
        return _fernet
    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(_derive_key())
    except Exception as e:  # pragma: no cover
        print(f"[crypto] Fernet unavailable, secrets stored in cleartext: {e}")
        _fernet = None
    return _fernet


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(_PREFIX)


def encrypt(plaintext) -> str:
    """Encrypt a string → ``enc:v1:<token>``. Empty/None passes through unchanged
    (nothing to protect). If crypto is unavailable, returns the plaintext (logged
    once) so the feature still functions in a degraded dev environment."""
    if not plaintext:
        return plaintext or ""
    if is_encrypted(plaintext):
        return plaintext
    f = _get_fernet()
    if f is None:
        return plaintext
    return _PREFIX + f.encrypt(str(plaintext).encode()).decode()


def decrypt(value) -> str:
    """Decrypt an ``enc:v1:`` value → plaintext. A non-encrypted value is returned
    as-is (legacy plaintext / already-decrypted). Fails CLOSED to '' on a bad
    token or wrong key, never raising into the caller."""
    if not value or not is_encrypted(value):
        return value or ""
    f = _get_fernet()
    if f is None:
        return ""
    try:
        return f.decrypt(value[len(_PREFIX):].encode()).decode()
    except Exception as e:
        print(f"[crypto] decrypt failed (wrong key or corrupt token): {e}")
        return ""


def encrypt_if_plaintext(value) -> str:
    """Idempotent: encrypt only if not already encrypted. Used by the migration
    that encrypts existing cleartext rows."""
    return value if is_encrypted(value) else encrypt(value)
