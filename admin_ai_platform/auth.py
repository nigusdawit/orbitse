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


def check_admin_password(password: str) -> bool:
    """Constant-time-ish password check against ``ADMIN_PASSWORD``. Used by the
    M2 login route. Empty submitted password always fails."""
    import hmac
    if not password:
        return False
    return hmac.compare_digest(str(password), str(config.ADMIN_PASSWORD))
