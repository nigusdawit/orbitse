"""
admin_ai_platform.config
========================

Central configuration for the standalone Admin/AI Platform package.

This module is the ONE place that reads the process environment. Everything
else in the package imports values/helpers from here so there are no scattered
``os.environ.get`` calls and no hardcoded literals in business logic.

Two flags decide the four deployment shapes from a single codebase (see
PLAN.md → "Deployment & distribution"):

* ``DEPLOY_MODE``  — ``central`` (multi-tenant SaaS; tenant resolved per request
  from the embed key / admin session) or ``self_host`` (everything pinned to
  ``tenant_id = 1``; the original single-tenant fast path).
* ``ADMIN_MODE``   — ``self_serve`` (per-tenant admin login) or ``agency_only``
  (only the operator reaches admin; clients only get the embedded widget).

The package is an *independent copy* of the original app's infrastructure — it
deliberately does not import anything from the legacy ``app.py``.
"""

from __future__ import annotations

import os


# ---------------------------------------------------------------------------
# Small typed env helpers — fail loud on genuinely invalid infra values, but
# treat empty strings (the common ``export VAR=`` mistake) as "unset".
# ---------------------------------------------------------------------------
def env_str(name: str, default: str = "") -> str:
    """Return a stripped string env var, or ``default`` when unset/empty."""
    val = os.environ.get(name)
    if val is None:
        return default
    val = val.strip()
    return val if val else default


def env_int(name: str, default: int) -> int:
    """Return an int env var. Raises ValueError naming the offending var on a
    non-integer value, because a silently-defaulted infra knob hides
    misconfiguration for weeks."""
    raw = os.environ.get(name, "")
    raw = raw.strip() if raw else ""
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"[config] env var {name}={raw!r} is not a valid integer "
            f"(default {default})."
        ) from e


def env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean env var. Accepts 1/true/yes/on (case-insensitive)."""
    raw = env_str(name)
    if not raw:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def env_choice(name: str, choices: tuple[str, ...], default: str) -> str:
    """Return an env var constrained to ``choices``; falls back to ``default``
    (and warns) on an unrecognised value rather than crashing — mode flags
    should degrade to a safe default, not take down boot."""
    val = env_str(name, default).lower()
    if val not in choices:
        import sys
        print(
            f"[config] {name}={val!r} not in {choices}; using default {default!r}",
            file=sys.stderr,
        )
        return default
    return val


# ---------------------------------------------------------------------------
# Deployment & admin modes
# ---------------------------------------------------------------------------
DEPLOY_MODE_CENTRAL = "central"
DEPLOY_MODE_SELF_HOST = "self_host"
DEPLOY_MODES = (DEPLOY_MODE_CENTRAL, DEPLOY_MODE_SELF_HOST)

ADMIN_MODE_SELF_SERVE = "self_serve"
ADMIN_MODE_AGENCY_ONLY = "agency_only"
ADMIN_MODES = (ADMIN_MODE_SELF_SERVE, ADMIN_MODE_AGENCY_ONLY)

DEPLOY_MODE = env_choice("DEPLOY_MODE", DEPLOY_MODES, DEPLOY_MODE_SELF_HOST)
ADMIN_MODE = env_choice("ADMIN_MODE", ADMIN_MODES, ADMIN_MODE_SELF_SERVE)

# In self_host every request resolves to this single tenant.
DEFAULT_TENANT_ID = env_int("DEFAULT_TENANT_ID", 1)


def is_central() -> bool:
    return DEPLOY_MODE == DEPLOY_MODE_CENTRAL


def is_self_host() -> bool:
    return DEPLOY_MODE == DEPLOY_MODE_SELF_HOST


def admin_is_self_serve() -> bool:
    return ADMIN_MODE == ADMIN_MODE_SELF_SERVE


# ---------------------------------------------------------------------------
# Core infrastructure
# ---------------------------------------------------------------------------
DATABASE_URL = env_str("DATABASE_URL")
DB_POOL_MIN = env_int("DB_POOL_MIN", 2)
DB_POOL_MAX = env_int("DB_POOL_MAX", 20)

FLASK_SECRET_KEY = env_str("FLASK_SECRET_KEY") or env_str("SESSION_SECRET")
# Cross-site iframe embedding (the WordPress-embedded admin) needs the session
# cookie to be SameSite=None; Secure — otherwise the browser won't send it
# inside a cross-origin iframe and the embedded admin appears logged-out. That
# combination requires HTTPS + CSRF protection on state-changing routes, so it's
# OPT-IN. Default Lax (same-site only).
SESSION_COOKIE_SAMESITE = env_choice("SESSION_COOKIE_SAMESITE", ("Lax", "Strict", "None"), "Lax")
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
ADMIN_PASSWORD = env_str("ADMIN_PASSWORD", "admin")
ADMIN_API_KEY = env_str("ADMIN_API_KEY")
ADMIN_EMAIL = env_str("ADMIN_EMAIL")

PORT = env_int("PORT", 5000)
PUBLIC_BASE_URL = env_str("PUBLIC_BASE_URL")
UPLOADS_DIR = env_str("UPLOADS_DIR", "uploads")

# ---------------------------------------------------------------------------
# LLM providers
# ---------------------------------------------------------------------------
# Chat completions may go through the Replit AI proxy (AI_INTEGRATIONS_*) or a
# direct OpenAI key. Audio endpoints (/audio/*) are NOT proxied — they need a
# direct OPENAI_API_KEY.
AI_INTEGRATIONS_OPENAI_API_KEY = env_str("AI_INTEGRATIONS_OPENAI_API_KEY")
AI_INTEGRATIONS_OPENAI_BASE_URL = env_str(
    "AI_INTEGRATIONS_OPENAI_BASE_URL", "https://api.openai.com/v1"
)
OPENAI_API_KEY = env_str("OPENAI_API_KEY")          # direct (TTS / Whisper)
ANTHROPIC_API_KEY = env_str("ANTHROPIC_API_KEY")
AI_MODEL = env_str("AI_MODEL", "gpt-4o-mini")

ELEVENLABS_API_KEY = env_str("ELEVENLABS_API_KEY")
ELEVENLABS_API_BASE = env_str("ELEVENLABS_API_BASE", "https://api.elevenlabs.io/v1")

# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------
TTS_MAX_CHARS = env_int("TTS_MAX_CHARS", 800)
VOICE_DAILY_CHAR_CAP = env_int("VOICE_DAILY_CHAR_CAP", 30000)

# ---------------------------------------------------------------------------
# Distribution / embedding (cross-origin trust boundary — used from M7)
# ---------------------------------------------------------------------------
# Comma-separated global allowlist used as a fallback in self_host; in central
# mode the per-tenant allowlist in the DB takes precedence.
EMBED_ALLOWED_ORIGINS = tuple(
    o.strip() for o in env_str("EMBED_ALLOWED_ORIGINS").split(",") if o.strip()
)
EMBED_KEY_SIGNING_SECRET = env_str("EMBED_KEY_SIGNING_SECRET") or FLASK_SECRET_KEY
# SSO secret must be DISTINCT and explicit — NO fallback to the session key.
# Reusing the cookie-signing key to also mint admin-granting tokens would widen
# the blast radius of a leak. When unset, SSO is disabled (mint raises, verify
# returns None) — fail closed, never silently weak.
SSO_SIGNING_SECRET = env_str("SSO_SIGNING_SECRET")
# Where loader.js / widget assets are served from (defaults to same origin).
WIDGET_CDN_BASE = env_str("WIDGET_CDN_BASE")
# The WordPress site origin permitted to frame the admin (SSO iframe). When set,
# the admin allows framing by 'self' + this origin; otherwise framing is denied.
CSP_FRAME_ANCESTORS = env_str("CSP_FRAME_ANCESTORS")

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
SCHEDULER_TICK_SECONDS = env_int("SCHEDULER_TICK_SECONDS", 30)
# Only the worker that wins a Postgres advisory lock runs the ticks, so multiple
# gunicorn workers don't all fire the same scheduled jobs.
SCHEDULER_ADVISORY_LOCK_KEY = env_int("SCHEDULER_ADVISORY_LOCK_KEY", 947213001)
# Number of trusted reverse-proxy hops (for ProxyFix → correct client IP). 0 =
# no proxy (use the direct peer). Set to 1 behind a single proxy/LB.
TRUSTED_PROXY_HOPS = env_int("TRUSTED_PROXY_HOPS", 0)
# Optional Redis for shared rate limiting; when unset, a Postgres table is used.
REDIS_URL = env_str("REDIS_URL")
# Per-(tenant, ip) request cap per window on the heavy embeddable endpoints.
RATE_LIMIT_MAX = env_int("RATE_LIMIT_MAX", 40)
RATE_LIMIT_WINDOW_SEC = env_int("RATE_LIMIT_WINDOW_SEC", 60)

# ---------------------------------------------------------------------------
# Optional integrations (all fail-open — feature disables, app still boots)
# ---------------------------------------------------------------------------
STRIPE_SECRET_KEY = env_str("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = env_str("STRIPE_WEBHOOK_SECRET")
RESEND_API_KEY = env_str("RESEND_API_KEY")
RESEND_FROM_EMAIL = env_str("RESEND_FROM_EMAIL")
RESEND_WEBHOOK_SECRET = env_str("RESEND_WEBHOOK_SECRET")
TWILIO_ACCOUNT_SID = env_str("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = env_str("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = env_str("TWILIO_FROM_NUMBER")
BRAVE_SEARCH_API_KEY = env_str("BRAVE_SEARCH_API_KEY")
GOOGLE_PLACES_API_KEY = env_str("GOOGLE_PLACES_API_KEY")
YELP_API_KEY = env_str("YELP_API_KEY")
TRIPADVISOR_API_KEY = env_str("TRIPADVISOR_API_KEY")
SENTRY_DSN = env_str("SENTRY_DSN")

SKIP_ALEMBIC = env_bool("SKIP_ALEMBIC", False)

# Secrets-at-rest (M19). Fernet key for encrypting DB-stored credentials
# (mcp_servers.auth_credential, etc.). When unset, the crypto layer derives a key
# from FLASK_SECRET_KEY so encryption still works in dev — but set an explicit,
# rotated SECRETS_ENCRYPTION_KEY in production (a urlsafe-base64 32-byte key).
SECRETS_ENCRYPTION_KEY = env_str("SECRETS_ENCRYPTION_KEY")
# HSTS is opt-in (you may terminate TLS at a proxy and not want HSTS from Flask).
ENABLE_HSTS = env_bool("ENABLE_HSTS", False)

# VELO master agent shared secret (agency multi-install control channel).
VELO_SHARED_SECRET = env_str("VELO_SHARED_SECRET")
# Fleet-sync (M22): a signed managed-defaults bundle must carry an ``issued_at``
# epoch within this many seconds of now, so a captured valid bundle can't be
# replayed indefinitely (it's only good for this window).
FLEET_BUNDLE_MAX_AGE_SEC = env_int("FLEET_BUNDLE_MAX_AGE_SEC", 3600)


def summary() -> dict:
    """Non-secret snapshot of the active configuration, for health/diagnostics.
    Never includes key VALUES — only presence booleans."""
    return {
        "deploy_mode": DEPLOY_MODE,
        "admin_mode": ADMIN_MODE,
        "database_configured": bool(DATABASE_URL),
        "openai_proxy_configured": bool(AI_INTEGRATIONS_OPENAI_API_KEY),
        "openai_direct_configured": bool(OPENAI_API_KEY),
        "anthropic_configured": bool(ANTHROPIC_API_KEY),
        "elevenlabs_configured": bool(ELEVENLABS_API_KEY),
        "resend_configured": bool(RESEND_API_KEY),
        "twilio_configured": bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN),
    }
