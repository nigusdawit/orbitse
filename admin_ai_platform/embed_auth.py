"""
admin_ai_platform.embed_auth
===========================

Cross-origin trust boundary for the embeddable widget (M7).

The widget runs on third-party sites and calls the platform's *embeddable*
public endpoints (chat, voice, forms, public content reads). Those requests
carry a **publishable embed key** (``X-Embed-Key`` header or ``embed_key``
query param). For any embeddable request that presents a key, we:

  1. resolve the key → tenant (enabled keys only),
  2. validate the request ``Origin`` (or ``Referer`` host) against that key's
     **origin allowlist** — reject with 403 otherwise,
  3. set ``g.tenant_id`` so downstream code is scoped to the right tenant,
  4. echo CORS headers for the (allowlisted) origin — never ``*``,
  5. apply a per-(tenant, ip) rate limit on the heavy endpoints.

A request with NO embed key is treated as first-party / same-origin and passes
through unchanged (so the bundled demo and the hosted admin keep working). This
means cross-origin embeds MUST send the key (the loader always does), while the
operator's own same-origin pages don't need one.

Single-worker note: the rate limiter is in-process. A multi-worker central
deployment should back it with Redis/Postgres (see PLAN.md security section).
"""

from __future__ import annotations

import time
import threading
from urllib.parse import urlparse

from flask import request, g, jsonify, make_response

from . import config
from .db import query_db

# Public endpoints the widget may call cross-origin. Prefix match.
EMBEDDABLE_PREFIXES = (
    "/api/chat", "/api/chatbot-settings", "/api/voice/", "/api/forms/",
    "/api/gallery-cards", "/api/products", "/api/services", "/api/presentations/",
    "/api/review-snapshots",
)
# Heavier endpoints that get the per-tenant rate limit.
RATE_LIMITED_PREFIXES = ("/api/chat", "/api/voice/")

_RATE_LOCK = threading.Lock()
_RATE_BUCKETS: dict = {}   # (tenant_id, ip) -> [window_start_epoch, count]
_RATE_WINDOW_SEC = 60
_RATE_MAX = 40             # requests per window per (tenant, ip) on heavy endpoints


def _is_embeddable(path):
    return any(path.startswith(p) for p in EMBEDDABLE_PREFIXES)


def _is_rate_limited(path):
    return any(path.startswith(p) for p in RATE_LIMITED_PREFIXES)


def _request_origin():
    """The browser-asserted origin: the Origin header, or the scheme://host of
    the Referer. Empty for non-browser / same-origin GETs."""
    origin = request.headers.get("Origin", "").strip()
    if origin:
        return origin
    ref = request.headers.get("Referer", "").strip()
    if ref:
        try:
            p = urlparse(ref)
            if p.scheme and p.netloc:
                return f"{p.scheme}://{p.netloc}"
        except Exception:
            pass
    return ""


def _resolve_key(embed_key):
    """Return the embed-key row (with tenant + allowlist) if enabled, else None."""
    if not embed_key:
        return None
    try:
        return query_db(
            "SELECT tenant_id, origin_allowlist, enabled FROM tenant_embed_keys "
            "WHERE embed_key=%s", (embed_key,), fetchone=True)
    except Exception:
        return None


def _origin_allowed(origin, allowlist):
    """An origin is allowed if it's in the key's allowlist, or the global
    EMBED_ALLOWED_ORIGINS fallback. ``*`` in a list allows any (opt-in only)."""
    if not origin:
        # No browser origin (server-to-server / curl). Allowed — the key itself
        # is the credential; origin checks only constrain *browser* embeds.
        return True
    al = list(allowlist or [])
    al += list(config.EMBED_ALLOWED_ORIGINS)
    if "*" in al:
        return True
    return origin in al


def _rate_ok(tenant_id, ip):
    now = time.time()
    key = (tenant_id, ip)
    with _RATE_LOCK:
        bucket = _RATE_BUCKETS.get(key)
        if not bucket or now - bucket[0] >= _RATE_WINDOW_SEC:
            _RATE_BUCKETS[key] = [now, 1]
            return True
        if bucket[1] >= _RATE_MAX:
            return False
        bucket[1] += 1
        return True


def register_embed_middleware(app):
    """Install the before/after request hooks for embed auth + CORS."""

    @app.before_request
    def _embed_before():
        path = request.path
        if not _is_embeddable(path):
            return None

        embed_key = (request.headers.get("X-Embed-Key", "")
                     or request.args.get("embed_key", "")).strip()

        # CORS preflight: answer here so the browser proceeds to the real call.
        if request.method == "OPTIONS":
            resp = make_response("", 204)
            _apply_cors(resp, embed_key)
            return resp

        if not embed_key:
            # First-party / same-origin: no key, pass through (tenant = default).
            return None

        row = _resolve_key(embed_key)
        if not row or not row.get("enabled"):
            return jsonify({"error": "invalid embed key"}), 403
        origin = _request_origin()
        if not _origin_allowed(origin, row.get("origin_allowlist")):
            return jsonify({"error": "origin not allowed for this embed key"}), 403

        g.tenant_id = row["tenant_id"]
        g.embed_origin = origin
        g.embed_keyed = True

        if _is_rate_limited(path):
            ip = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                  or request.remote_addr or "unknown")
            if not _rate_ok(row["tenant_id"], ip):
                return jsonify({"error": "rate limit exceeded"}), 429
        return None

    @app.after_request
    def _embed_after(resp):
        if _is_embeddable(request.path) and getattr(g, "embed_keyed", False):
            _apply_cors(resp, request.headers.get("X-Embed-Key", "")
                        or request.args.get("embed_key", ""))
        return resp

    return app


def _apply_cors(resp, embed_key):
    """Echo CORS headers for the allowlisted origin only (never ``*``)."""
    origin = _request_origin()
    if not origin:
        return
    row = _resolve_key((embed_key or "").strip())
    allowlist = row.get("origin_allowlist") if row else []
    if _origin_allowed(origin, allowlist):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Embed-Key"
        resp.headers["Access-Control-Max-Age"] = "600"
