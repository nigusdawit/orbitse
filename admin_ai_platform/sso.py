"""
admin_ai_platform.sso
====================

Single-use, short-lived SSO tokens that let the WordPress plugin embed the
hosted per-tenant admin in a wp-admin iframe WITHOUT the operator re-entering a
password. The plugin and the platform share a confidential ``SSO_SIGNING_SECRET``
(never exposed to the browser); the plugin signs a token server-side (PHP), the
platform verifies it here.

Token format (so the PHP and Python agree exactly):

    payload  = {"tid": <tenant_id>, "exp": <unix_seconds>, "jti": <random hex>}
    b64      = base64url(json(payload))            # no padding
    sig      = base64url(HMAC-SHA256(b64, secret)) # no padding
    token    = b64 + "." + sig

Verification: constant-time signature check, ``exp`` in the future, lifetime
≤ MAX_TTL (rejects long-lived tokens even if signed), and ``jti`` unused
(single-use; in-process replay cache with TTL). All failures return None.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time

from . import config

MAX_TTL_SECONDS = 60
_USED_JTIS: dict = {}          # jti -> expiry epoch (replay cache)
_USED_LOCK = threading.Lock()


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(b64_payload: str, secret: str) -> str:
    return _b64u(hmac.new(secret.encode("utf-8"), b64_payload.encode("ascii"),
                          hashlib.sha256).digest())


def mint_sso_token(tenant_id: int, *, ttl_seconds: int = 45,
                   secret: str | None = None) -> str:
    """Mint a token (used by tests + any server-side mint helper). PHP mints its
    own with the identical scheme; this exists so we can verify round-trips."""
    secret = secret or config.SSO_SIGNING_SECRET
    if not secret:
        raise RuntimeError("SSO_SIGNING_SECRET is not configured")
    payload = {"tid": int(tenant_id), "exp": int(time.time()) + int(ttl_seconds),
               "jti": secrets.token_hex(16)}
    b64 = _b64u(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{b64}.{_sign(b64, secret)}"


def verify_sso_token(token: str):
    """Return the tenant_id if the token is valid + unused, else None. Marks the
    token's jti used (single-use)."""
    secret = config.SSO_SIGNING_SECRET
    if not secret or not token or "." not in token:
        return None
    b64, _, sig = token.partition(".")
    expected = _sign(b64, secret)
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64u_decode(b64))
    except Exception:
        return None
    now = time.time()
    exp = payload.get("exp", 0)
    if not isinstance(exp, (int, float)) or exp <= now:
        return None
    if exp - now > MAX_TTL_SECONDS + 5:   # reject over-long tokens (+small skew)
        return None
    jti = payload.get("jti")
    tid = payload.get("tid")
    if not jti or tid is None:
        return None
    if not _claim_jti(jti, exp):
        return None                         # replay (already consumed)
    return int(tid)


def _claim_jti(jti, exp):
    """Atomically claim a jti so it can be used exactly once — ACROSS workers.
    Primary store is the DB (INSERT ON CONFLICT DO NOTHING); the in-process set
    is a fast path + a fallback if the DB is briefly unavailable. Returns True
    if THIS call claimed it (i.e. it was unused)."""
    now = time.time()
    with _USED_LOCK:
        if len(_USED_JTIS) > 5000:
            for k in [k for k, e in _USED_JTIS.items() if e < now]:
                _USED_JTIS.pop(k, None)
        if jti in _USED_JTIS:
            return False
        _USED_JTIS[jti] = exp
    try:
        from .db import execute_db
        row = execute_db(
            "INSERT INTO sso_used_jtis (jti, expires_at) "
            "VALUES (%s, to_timestamp(%s)) ON CONFLICT (jti) DO NOTHING RETURNING jti",
            (jti, exp))
        # row is None when the jti already existed (another worker claimed it).
        return row is not None
    except Exception as e:
        # DB unavailable — fall back to the in-process claim we already made.
        print(f"[sso] DB jti claim failed, using in-process only: {e}")
        return True
