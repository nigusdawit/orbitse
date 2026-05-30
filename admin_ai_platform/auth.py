"""
admin_ai_platform.auth
=====================

Admin authentication for the package.

Two mechanisms, both honored by ``admin_required``:
  * **Session cookie** — set by the admin login route (M2) after a password
    check; used by the hosted admin dashboard (``ADMIN_MODE=self_serve``).
  * **API key** — ``Authorization: Bearer <key>`` or ``?key=`` matching
    ``ADMIN_API_KEY``; used by programmatic access and the M2 admin SPA before
    the login UI lands.

``ADMIN_MODE=agency_only`` doesn't change the gate itself — it governs whether
per-tenant self-serve login is *exposed* (M2). The decorator is the same.

This is intentionally minimal for the M1 slice; the full login flow + password
hashing + per-tenant admin users land in M2.
"""

from __future__ import annotations

from functools import wraps

from flask import session, request, jsonify

from . import config


def is_admin_authenticated() -> bool:
    """True if the current request carries a valid admin session or API key."""
    try:
        if session.get("is_admin"):
            return True
    except Exception:
        pass
    auth = request.headers.get("Authorization", "")
    key = auth[7:].strip() if auth.startswith("Bearer ") else request.args.get("key", "")
    # Only accept the API key when one is actually configured — an empty
    # ADMIN_API_KEY must never authenticate (that would be an open door).
    return bool(config.ADMIN_API_KEY) and key == config.ADMIN_API_KEY


def admin_required(f):
    """Protect an admin route. 401 JSON when unauthenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_admin_authenticated():
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def _hash_password(password: str, salt_hex: str) -> str:
    """pbkdf2-hmac-sha256 of a password with a per-install salt. Hex digest."""
    import hashlib
    return hashlib.pbkdf2_hmac(
        "sha256", str(password).encode(), bytes.fromhex(salt_hex), 200_000).hex()


def set_admin_password(password: str) -> None:
    """Persist a DB admin password (overrides env ADMIN_PASSWORD). Generates a
    fresh random salt each time. Used by the /setup wizard."""
    import os
    from .db import execute_db
    salt = os.urandom(16).hex()
    digest = _hash_password(password, salt)
    execute_db("INSERT INTO platform_setup (id, admin_password_hash, admin_password_salt) "
               "VALUES (1,%s,%s) ON CONFLICT (id) DO UPDATE SET "
               "admin_password_hash=EXCLUDED.admin_password_hash, "
               "admin_password_salt=EXCLUDED.admin_password_salt", (digest, salt))


def _db_admin_password_ok(password: str):
    """Return True/False if a DB password is configured and matches, else None
    (meaning 'no DB password set — fall back to env')."""
    import hmac
    try:
        from .db import query_db
        row = query_db("SELECT admin_password_hash, admin_password_salt "
                       "FROM platform_setup WHERE id=1", fetchone=True)
    except Exception:
        return None
    if not row or not row.get("admin_password_hash") or not row.get("admin_password_salt"):
        return None
    expected = row["admin_password_hash"]
    actual = _hash_password(password, row["admin_password_salt"])
    return hmac.compare_digest(actual, expected)


def check_admin_password(password: str) -> bool:
    """Constant-time-ish password check. Prefers a DB-stored password (set via
    the /setup wizard); falls back to the env ``ADMIN_PASSWORD`` when none is
    persisted. Empty submitted password always fails."""
    import hmac
    if not password:
        return False
    db_result = _db_admin_password_ok(password)
    if db_result is not None:
        return db_result
    return hmac.compare_digest(str(password), str(config.ADMIN_PASSWORD))
