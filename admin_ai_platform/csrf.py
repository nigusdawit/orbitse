"""
admin_ai_platform.csrf
======================

CSRF protection for cookie-authenticated admin mutations (M19).

CSRF only affects requests the browser authenticates **automatically** — i.e. the
session cookie. So we enforce a token ONLY when:

  * the request mutates state (POST/PUT/PATCH/DELETE), AND
  * it targets an ``/admin/api`` route, AND
  * it is authenticated by the **session cookie** (not the ``Authorization:
    Bearer`` admin API key — programmatic clients aren't CSRF-able and send no
    ambient cookie).

Exempt surfaces (their own auth, not cookie-ambient): the embed/public endpoints
(``/api``), provider webhooks (``/webhooks``), VELO (``/api/velo``), the SSO
handshake (``/admin/sso``), and login itself.

The dashboard fetches the token from ``GET /admin/api/csrf-token`` (or reads the
``<meta name="csrf-token">`` the dashboard injects) and echoes it in the
``X-CSRF-Token`` header on every mutation. Enabling this is what makes
``SESSION_COOKIE_SAMESITE=None`` (cross-site WP embed) safe.
"""

from __future__ import annotations

import secrets

from flask import session, request, jsonify, g

_SESSION_KEY = "csrf_token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
# Path prefixes that authenticate themselves and must NOT require a CSRF token.
_EXEMPT_PREFIXES = ("/admin/login", "/admin/sso")


def get_csrf_token() -> str:
    """Return the session's CSRF token, minting one on first use."""
    tok = session.get(_SESSION_KEY)
    if not tok:
        tok = secrets.token_urlsafe(32)
        session[_SESSION_KEY] = tok
    return tok


def _authed_by_api_key() -> bool:
    """True when this request is authenticated by the Bearer/admin API key rather
    than the session cookie — such requests are not CSRF-susceptible."""
    from . import config
    auth = request.headers.get("Authorization", "")
    key = auth[7:].strip() if auth.startswith("Bearer ") else request.args.get("key", "")
    return bool(config.ADMIN_API_KEY) and key == config.ADMIN_API_KEY


def register_csrf(app):
    """Install the before_request CSRF gate + the token-issuing route."""

    @app.before_request
    def _csrf_protect():
        if request.method in _SAFE_METHODS:
            return None
        path = request.path
        if not path.startswith("/admin/api"):
            return None
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return None
        # Only cookie-authed sessions need CSRF; API-key callers are exempt.
        if _authed_by_api_key():
            return None
        if not session.get("is_admin"):
            # Not an authenticated admin session — the admin_required decorator
            # will 401 it; no CSRF needed (nothing ambient to abuse).
            return None
        sent = (request.headers.get("X-CSRF-Token", "")
                or (request.form.get("csrf_token") if request.form else "") or "").strip()
        expected = session.get(_SESSION_KEY, "")
        if not expected or not secrets.compare_digest(sent, expected):
            return jsonify({"error": "CSRF token missing or invalid"}), 403
        return None

    @app.route("/admin/api/csrf-token", methods=["GET"])
    def _csrf_token_route():
        # Readable by the dashboard (same-origin, cookie-authed) to bootstrap the
        # header. Returns the token for the current session.
        return jsonify({"csrf_token": get_csrf_token()})

    # Expose the token to templates/handlers that want to inline it.
    @app.before_request
    def _stash_csrf():
        try:
            g.csrf_token = session.get(_SESSION_KEY, "")
        except Exception:
            g.csrf_token = ""

    return app
