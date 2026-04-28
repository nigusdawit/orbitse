"""
Stripe client + key resolver.

This module supports three stacked sources for Stripe credentials, in
priority order, and routes through a runtime "mode" toggle (test/live)
persisted in the `stripe_settings` table:

1. Replit-managed Stripe connection (preferred when present): we read the
   secret + publishable key from the Replit Connectors API, using the
   REPL_IDENTITY / WEB_REPL_RENEWAL token Replit injects into the runtime.
   Tokens are short-lived, so we cache the resolved keys for ~10 minutes
   and refresh on the next call. (Connector keys are NOT mode-aware —
   whatever the connector hands us is what we get.)

2. Mode-specific env vars (the admin Stripe console relies on this layer
   to flip between test and live without touching anything else):
   - mode=live → STRIPE_SECRET_KEY / STRIPE_PUBLISHABLE_KEY / STRIPE_WEBHOOK_SECRET
   - mode=test → STRIPE_TEST_SECRET_KEY / STRIPE_TEST_PUBLISHABLE_KEY /
                 STRIPE_TEST_WEBHOOK_SECRET
   With a soft fallback: if mode=test and the test keys are unset, we
   accept the live env vars iff their content begins with "sk_test_" /
   "pk_test_" — covers the common single-pair-of-test-keys case during
   initial setup.

3. Legacy env-var fallback: if no mode is persisted yet (table not
   created, DB unreachable, fresh install) we fall back to the original
   STRIPE_SECRET_KEY / STRIPE_PUBLISHABLE_KEY behaviour so existing
   installs keep working without any config change.

Callers should ALWAYS use `get_stripe()` to construct a fresh client per
request rather than caching the module-level `stripe` import. The
`stripe.api_key` global is mutated by `get_stripe()` so any subsequent
SDK call inside the same request will use the right key.

The cache key includes the mode so a flip from test→live (or vice versa)
invalidates the cached secret immediately on the very next call — admins
should never see a "switched to live but still charging test cards"
window even with the 600s key TTL.
"""
import os
import time
import json
import urllib.request
import urllib.error

import stripe

# Cache keyed by mode — a mode flip invalidates the relevant entry on
# the next get_stripe() call. {"<mode>": {"secret":..., "publishable":...,
# "webhook":..., "fetched_at": float}}
_KEY_CACHE = {}
_CACHE_TTL = 600  # seconds


def _fetch_replit_connection():
    """Look up an authorized Stripe connection via the Replit Connectors API.

    Returns a dict of settings or None if no connection is available.
    """
    hostname = os.environ.get("REPLIT_CONNECTORS_HOSTNAME")
    repl_identity = os.environ.get("REPL_IDENTITY")
    web_renewal = os.environ.get("WEB_REPL_RENEWAL")
    if not hostname:
        return None
    if repl_identity:
        token = "repl " + repl_identity
    elif web_renewal:
        token = "depl " + web_renewal
    else:
        return None

    # Production deployments should use the production environment.
    target_env = "production" if os.environ.get("REPLIT_DEPLOYMENT") == "1" else "development"
    url = (
        f"https://{hostname}/api/v2/connection?"
        f"include_secrets=true&connector_names=stripe&environment={target_env}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-Replit-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError):
        return None

    items = data.get("items") or []
    if not items:
        return None
    return items[0].get("settings") or {}


def _get_mode():
    """Return the current mode string ('test' or 'live'), with a hard
    fallback to 'live' if the settings layer is unavailable so existing
    installs (which only have STRIPE_SECRET_KEY set, not the test pair)
    keep working unchanged."""
    try:
        # Lazy import — avoid circular import with stripe_settings → app.
        import stripe_settings
        return stripe_settings.get_mode()
    except Exception:
        return "live"


def _env_keys_for_mode(mode):
    """Return (secret, publishable, webhook) read from the mode-specific
    env vars, with the test-key soft fallback described in the module
    docstring."""
    if mode == "test":
        secret = os.environ.get("STRIPE_TEST_SECRET_KEY") or None
        pub = os.environ.get("STRIPE_TEST_PUBLISHABLE_KEY") or None
        webhook = os.environ.get("STRIPE_TEST_WEBHOOK_SECRET") or None
        # Soft fallback: if the test pair is unset but the live env-var
        # actually contains a test key, accept it. Common during initial
        # setup when there's only one set of (test) keys configured.
        if not secret:
            live_secret = os.environ.get("STRIPE_SECRET_KEY") or ""
            if live_secret.startswith("sk_test_"):
                secret = live_secret
        if not pub:
            live_pub = os.environ.get("STRIPE_PUBLISHABLE_KEY") or ""
            if live_pub.startswith("pk_test_"):
                pub = live_pub
        if not webhook:
            webhook = os.environ.get("STRIPE_WEBHOOK_SECRET") or None
        return secret, pub, webhook

    # mode == "live"
    secret = os.environ.get("STRIPE_SECRET_KEY") or None
    pub = os.environ.get("STRIPE_PUBLISHABLE_KEY") or None
    webhook = os.environ.get("STRIPE_WEBHOOK_SECRET") or None
    return secret, pub, webhook


def _resolve_keys(force_refresh: bool = False, mode: str = None):
    """Return (secret, publishable, webhook) using cache + Replit + mode-aware env."""
    if mode is None:
        mode = _get_mode()
    now = time.time()
    cached = _KEY_CACHE.get(mode)
    if (
        not force_refresh
        and cached
        and cached.get("secret")
        and (now - cached.get("fetched_at", 0)) < _CACHE_TTL
    ):
        return cached["secret"], cached.get("publishable"), cached.get("webhook")

    secret = None
    publishable = None
    webhook = None

    # Layer 1: Replit Connectors (mode-blind — whatever the connector
    # hands us is what we get; the connector itself is configured by the
    # user as either test or live).
    settings = _fetch_replit_connection()
    if settings:
        secret = (
            settings.get("secret")
            or settings.get("secret_key")
            or settings.get("api_key")
            or settings.get("STRIPE_SECRET_KEY")
        )
        publishable = (
            settings.get("publishable")
            or settings.get("publishable_key")
            or settings.get("PUBLISHABLE_KEY")
            or settings.get("STRIPE_PUBLISHABLE_KEY")
        )
        webhook = (
            settings.get("webhook_secret")
            or settings.get("STRIPE_WEBHOOK_SECRET")
        )

    # Layer 2: mode-aware env vars. We OVERRIDE the connector value here
    # if the mode-specific env var is set, because the admin explicitly
    # chose a mode and we should honor it over a connector that may be
    # wired up to the other side.
    env_secret, env_pub, env_webhook = _env_keys_for_mode(mode)
    if env_secret:
        secret = env_secret
    if env_pub:
        publishable = env_pub
    if env_webhook:
        webhook = env_webhook

    _KEY_CACHE[mode] = {
        "secret": secret,
        "publishable": publishable,
        "webhook": webhook,
        "fetched_at": now,
    }
    return secret, publishable, webhook


def get_publishable_key() -> str:
    """Public-safe key for the storefront JS."""
    _, pub, _ = _resolve_keys()
    return pub or ""


def get_webhook_secret() -> str:
    """Webhook signing secret — first the mode-aware resolver, then the
    legacy env var as a final fallback so existing webhook handlers
    don't break for installs that haven't switched modes yet."""
    _, _, webhook = _resolve_keys()
    return webhook or os.environ.get("STRIPE_WEBHOOK_SECRET", "")


def is_configured() -> bool:
    secret, _, _ = _resolve_keys()
    return bool(secret)


def get_stripe():
    """Return the `stripe` module with `api_key` set for this request.

    Raises RuntimeError if no key is available so callers fail fast.
    """
    secret, _, _ = _resolve_keys()
    if not secret:
        # Try one forced refresh in case the connector was just authorized.
        secret, _, _ = _resolve_keys(force_refresh=True)
    if not secret:
        raise RuntimeError(
            "Stripe is not configured. Connect Stripe via the Replit "
            "integration or set STRIPE_SECRET_KEY (live mode) / "
            "STRIPE_TEST_SECRET_KEY (test mode)."
        )
    stripe.api_key = secret
    return stripe


def get_stripe_for_mode(mode: str):
    """Return the `stripe` module with `api_key` set for the EXPLICIT mode
    requested, without consulting OR mutating the persisted `stripe_settings.mode`.

    This is the safe entrypoint for callers that need to operate on a
    specific mode (e.g. archiving the test-mode mapping while the admin
    is currently in live mode). Using `get_stripe()` + `set_mode()` for
    the same job creates a race condition where concurrent requests see
    a temporarily-flipped global mode.

    Raises RuntimeError if no key is available for the requested mode.
    """
    if mode not in ("test", "live"):
        raise ValueError(f"mode must be 'test' or 'live', got {mode!r}")
    secret, _, _ = _resolve_keys(mode=mode)
    if not secret:
        secret, _, _ = _resolve_keys(force_refresh=True, mode=mode)
    if not secret:
        raise RuntimeError(
            f"Stripe {mode}-mode is not configured. Set "
            f"STRIPE_{'TEST_' if mode == 'test' else ''}SECRET_KEY."
        )
    stripe.api_key = secret
    return stripe


def detect_keys_present():
    """Returns a flat dict of which Stripe-related env vars are SET
    (truthy non-empty). Values are NEVER returned — only booleans —
    because this is consumed by the admin Stripe console UI which must
    never display secret values. Used to render the 'Keys detected'
    panel without leaking anything."""
    return {
        "live_secret":      bool(os.environ.get("STRIPE_SECRET_KEY")),
        "live_publishable": bool(os.environ.get("STRIPE_PUBLISHABLE_KEY")),
        "live_webhook":     bool(os.environ.get("STRIPE_WEBHOOK_SECRET")),
        "test_secret":      bool(os.environ.get("STRIPE_TEST_SECRET_KEY")),
        "test_publishable": bool(os.environ.get("STRIPE_TEST_PUBLISHABLE_KEY")),
        "test_webhook":     bool(os.environ.get("STRIPE_TEST_WEBHOOK_SECRET")),
        "replit_connector": bool(os.environ.get("REPLIT_CONNECTORS_HOSTNAME")),
    }


def detect_active_key_kind():
    """Returns 'test' / 'live' / 'unknown' based on the prefix of the
    secret key that get_stripe() WOULD use right now. Used by the admin
    UI to surface a 'mode mismatch' warning if the persisted mode says
    'live' but the resolved key actually starts with sk_test_."""
    try:
        secret, _, _ = _resolve_keys()
    except Exception:
        return "unknown"
    if not secret:
        return "unknown"
    if secret.startswith("sk_test_"):
        return "test"
    if secret.startswith("sk_live_"):
        return "live"
    return "unknown"


def invalidate_cache():
    """Drop all cached keys — call after a mode switch or env-var change
    so the next get_stripe() call re-resolves from scratch."""
    _KEY_CACHE.clear()
