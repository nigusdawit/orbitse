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

Multi-worker note: the rate limiter is **Postgres-backed** (the ``rate_buckets``
table) so all gunicorn workers share one counter via an atomic UPSERT. If the DB
is unreachable it degrades to a per-process in-memory bucket (fail-open to the
local counter rather than letting traffic through unbounded).
"""

from __future__ import annotations

import time
import threading
from urllib.parse import urlparse

from flask import request, g, jsonify, make_response

from . import config
from .db import query_db, execute_db

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


def _rate_window_sec():
    return max(1, config.RATE_LIMIT_WINDOW_SEC)


def _rate_max():
    return max(1, config.RATE_LIMIT_MAX)


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


def _is_same_origin(origin):
    """True for genuine first-party requests: no asserted origin, or an origin
    whose host matches the platform's own Host. Used only in self_host, where
    the operator's site is same-origin with the platform."""
    if not origin:
        return True
    try:
        return urlparse(origin).netloc == request.host
    except Exception:
        return False


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
    """True only for a NON-EMPTY origin present in the key's allowlist (or the
    global fallback). ``*`` is an explicit opt-in wildcard. An empty origin is
    NOT allowed here — callers decide whether a missing origin is acceptable
    for a given endpoint (it never is for the cost-bearing ones)."""
    if not origin:
        return False
    al = list(allowlist or []) + list(config.EMBED_ALLOWED_ORIGINS)
    if "*" in al:
        return True
    return origin in al


def _client_ip():
    """Client IP for rate limiting. Uses the WSGI-resolved remote_addr (set
    correctly by ProxyFix when a trusted-proxy hop count is configured). We do
    NOT parse raw X-Forwarded-For here — it's attacker-controlled and would let
    a client mint unlimited buckets."""
    return (request.remote_addr or "unknown")


def _rate_ok(tenant_id, ip):
    """True if the (tenant, ip) is under the per-window cap. Shared across workers
    via the ``rate_buckets`` table: one atomic UPSERT that resets the counter on a
    new fixed window or increments within the current one. Falls back to the local
    in-memory counter if the DB write fails."""
    window = _rate_window_sec()
    now = int(time.time())
    win_start = (now // window) * window
    if config.DATABASE_URL:
        bucket_key = f"{tenant_id}:{ip}"[:180]
        try:
            row = execute_db(
                "INSERT INTO rate_buckets (bucket_key, window_start, count) VALUES (%s,%s,1) "
                "ON CONFLICT (bucket_key) DO UPDATE SET "
                "  count = CASE WHEN rate_buckets.window_start = EXCLUDED.window_start "
                "               THEN rate_buckets.count + 1 ELSE 1 END, "
                "  window_start = EXCLUDED.window_start "
                "RETURNING count, window_start",
                (bucket_key, win_start))
            if row:
                return int(row["count"]) <= _rate_max()
        except Exception as e:
            print(f"[embed_auth] rate-limit DB write failed, using local fallback: {e}")
    return _rate_ok_local(tenant_id, ip, window, now)


def _rate_ok_local(tenant_id, ip, window, now):
    key = (tenant_id, ip)
    with _RATE_LOCK:
        # Opportunistic eviction so the bucket map can't grow unbounded.
        if len(_RATE_BUCKETS) > 10000:
            for k in [k for k, v in _RATE_BUCKETS.items() if now - v[0] >= window]:
                _RATE_BUCKETS.pop(k, None)
        bucket = _RATE_BUCKETS.get(key)
        if not bucket or now - bucket[0] >= window:
            _RATE_BUCKETS[key] = [now, 1]
            return True
        if bucket[1] >= _rate_max():
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

        heavy = _is_rate_limited(path)           # cost-bearing: chat / voice
        origin = _request_origin()
        embed_key = (request.headers.get("X-Embed-Key", "")
                     or request.args.get("embed_key", "")).strip()

        # CORS preflight: answer here so the browser proceeds to the real call.
        if request.method == "OPTIONS":
            resp = make_response("", 204)
            _apply_cors(resp, embed_key)
            return resp

        rl_tenant = config.DEFAULT_TENANT_ID

        if embed_key:
            row = _resolve_key(embed_key)
            if not row or not row.get("enabled"):
                return jsonify({"error": "invalid embed key"}), 403
            # A keyed BROWSER request must carry an allowlisted origin. For the
            # cost-bearing endpoints we additionally REQUIRE a real origin — a
            # publishable key with no asserted origin (curl/server) must not be
            # able to spend the tenant's budget.
            if origin:
                if not _origin_allowed(origin, row.get("origin_allowlist")):
                    return jsonify({"error": "origin not allowed for this embed key"}), 403
            elif heavy:
                return jsonify({"error": "origin required"}), 403
            g.tenant_id = row["tenant_id"]
            g.embed_origin = origin
            g.embed_keyed = True
            rl_tenant = row["tenant_id"]
        else:
            # No key. Cost-bearing endpoints require one unless this is a
            # genuine first-party (same-origin) request in self_host. In central
            # (SaaS) every legitimate caller is a keyed cross-origin embed, so
            # no-key heavy requests are always rejected.
            if heavy:
                if config.is_central() or not _is_same_origin(origin):
                    return jsonify({"error": "embed key required"}), 403
            # Cross-origin no-key reads of PUBLIC content are harmless (the data
            # is public anyway) and get no CORS headers, so a browser can't read
            # them cross-origin regardless.

        if heavy and not _rate_ok(rl_tenant, _client_ip()):
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
        # Append (don't clobber) Vary so a handler's existing Vary survives —
        # important for shared caches not to cross-serve origins.
        existing_vary = resp.headers.get("Vary", "")
        if "origin" not in existing_vary.lower():
            resp.headers["Vary"] = (existing_vary + ", Origin").lstrip(", ") if existing_vary else "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Embed-Key"
        resp.headers["Access-Control-Max-Age"] = "600"
