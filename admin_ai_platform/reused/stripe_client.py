"""
admin_ai_platform.reused.stripe_client
=======================================

Stripe client + key resolver (relocated from the monolith's ``stripe_client.py``).

Credentials stack in priority order, routed through a runtime mode toggle
(test/live) persisted in ``stripe_settings`` (id=1):

1. Replit-managed Stripe connection (when the runtime exposes it).
2. Mode-specific env vars:
   - mode=live → STRIPE_SECRET_KEY / STRIPE_PUBLISHABLE_KEY / STRIPE_WEBHOOK_SECRET
   - mode=test → STRIPE_TEST_SECRET_KEY / STRIPE_TEST_PUBLISHABLE_KEY /
                 STRIPE_TEST_WEBHOOK_SECRET
   With a soft fallback: in test mode an ``sk_test_``/``pk_test_`` live env var is
   accepted (covers the common single-test-pair setup).
3. Legacy env-var fallback when no mode row exists yet.

Always call ``get_stripe()`` to construct a fresh client per request (it mutates
``stripe.api_key``). The cache key includes the mode so a test→live flip
invalidates immediately on the next call.

**Package change vs the monolith original:** ``import stripe`` is guarded so the
package boots even when the Stripe SDK isn't installed (``get_stripe()`` then
fails loud with a clear message), and ``stripe_settings`` is imported from the
package's ``reused_di`` instead of the top-level monolith module.
"""
import os
import time
import json
import urllib.request
import urllib.error

try:  # The SDK is an optional dependency — the package must import without it.
    import stripe
except Exception:  # pragma: no cover - exercised only in SDK-less environments
    stripe = None

# Cache keyed by mode — a mode flip invalidates the relevant entry on the next
# get_stripe() call.
_KEY_CACHE = {}
_CACHE_TTL = 600  # seconds


def _fetch_replit_connection():
    """Look up an authorized Stripe connection via the Replit Connectors API.
    Returns a settings dict or None when no connection is available."""
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

    target_env = "production" if os.environ.get("REPLIT_DEPLOYMENT") == "1" else "development"
    url = (
        f"https://{hostname}/api/v2/connection?"
        f"include_secrets=true&connector_names=stripe&environment={target_env}"
    )
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "X-Replit-Token": token})
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
    """Current mode ('test'/'live'); hard fallback to 'live' if settings are
    unavailable so legacy single-key installs keep working."""
    try:
        from ..reused_di import stripe_settings
        return stripe_settings.get_mode()
    except Exception:
        return "live"


def _env_keys_for_mode(mode):
    """(secret, publishable, webhook) from the mode-specific env vars, with the
    test-key soft fallback described in the module docstring."""
    if mode == "test":
        secret = os.environ.get("STRIPE_TEST_SECRET_KEY") or None
        pub = os.environ.get("STRIPE_TEST_PUBLISHABLE_KEY") or None
        webhook = os.environ.get("STRIPE_TEST_WEBHOOK_SECRET") or None
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

    secret = os.environ.get("STRIPE_SECRET_KEY") or None
    pub = os.environ.get("STRIPE_PUBLISHABLE_KEY") or None
    webhook = os.environ.get("STRIPE_WEBHOOK_SECRET") or None
    return secret, pub, webhook


def _resolve_keys(force_refresh: bool = False, mode: str = None):
    """(secret, publishable, webhook) using cache + Replit + mode-aware env."""
    if mode is None:
        mode = _get_mode()
    now = time.time()
    cached = _KEY_CACHE.get(mode)
    if (not force_refresh and cached and cached.get("secret")
            and (now - cached.get("fetched_at", 0)) < _CACHE_TTL):
        return cached["secret"], cached.get("publishable"), cached.get("webhook")

    secret = publishable = webhook = None
    settings = _fetch_replit_connection()
    if settings:
        secret = (settings.get("secret") or settings.get("secret_key")
                  or settings.get("api_key") or settings.get("STRIPE_SECRET_KEY"))
        publishable = (settings.get("publishable") or settings.get("publishable_key")
                       or settings.get("PUBLISHABLE_KEY") or settings.get("STRIPE_PUBLISHABLE_KEY"))
        webhook = settings.get("webhook_secret") or settings.get("STRIPE_WEBHOOK_SECRET")

    env_secret, env_pub, env_webhook = _env_keys_for_mode(mode)
    if env_secret:
        secret = env_secret
    if env_pub:
        publishable = env_pub
    if env_webhook:
        webhook = env_webhook

    _KEY_CACHE[mode] = {"secret": secret, "publishable": publishable,
                        "webhook": webhook, "fetched_at": now}
    return secret, publishable, webhook


def get_publishable_key() -> str:
    """Public-safe key for the storefront JS."""
    _, pub, _ = _resolve_keys()
    return pub or ""


def get_webhook_secret() -> str:
    """Webhook signing secret — mode-aware resolver then legacy env fallback."""
    _, _, webhook = _resolve_keys()
    return webhook or os.environ.get("STRIPE_WEBHOOK_SECRET", "")


def is_configured() -> bool:
    if stripe is None:
        return False
    secret, _, _ = _resolve_keys()
    return bool(secret)


def get_stripe():
    """Return the ``stripe`` module with ``api_key`` set for this request. Raises
    RuntimeError if the SDK is missing or no key is available (fail fast)."""
    if stripe is None:
        raise RuntimeError("The 'stripe' package is not installed.")
    secret, _, _ = _resolve_keys()
    if not secret:
        secret, _, _ = _resolve_keys(force_refresh=True)
    if not secret:
        raise RuntimeError(
            "Stripe is not configured. Set STRIPE_SECRET_KEY (live) / "
            "STRIPE_TEST_SECRET_KEY (test).")
    stripe.api_key = secret
    return stripe


def get_stripe_for_mode(mode: str):
    """Return ``stripe`` with ``api_key`` for the EXPLICIT mode, without reading
    or mutating the persisted mode (race-safe for cross-mode operations)."""
    if mode not in ("test", "live"):
        raise ValueError(f"mode must be 'test' or 'live', got {mode!r}")
    if stripe is None:
        raise RuntimeError("The 'stripe' package is not installed.")
    secret, _, _ = _resolve_keys(mode=mode)
    if not secret:
        secret, _, _ = _resolve_keys(force_refresh=True, mode=mode)
    if not secret:
        raise RuntimeError(
            f"Stripe {mode}-mode is not configured. Set "
            f"STRIPE_{'TEST_' if mode == 'test' else ''}SECRET_KEY.")
    stripe.api_key = secret
    return stripe


def detect_keys_present():
    """Booleans only (never values) of which Stripe env vars are set — for the
    admin console 'keys detected' panel."""
    return {
        "live_secret":      bool(os.environ.get("STRIPE_SECRET_KEY")),
        "live_publishable": bool(os.environ.get("STRIPE_PUBLISHABLE_KEY")),
        "live_webhook":     bool(os.environ.get("STRIPE_WEBHOOK_SECRET")),
        "test_secret":      bool(os.environ.get("STRIPE_TEST_SECRET_KEY")),
        "test_publishable": bool(os.environ.get("STRIPE_TEST_PUBLISHABLE_KEY")),
        "test_webhook":     bool(os.environ.get("STRIPE_TEST_WEBHOOK_SECRET")),
        "replit_connector": bool(os.environ.get("REPLIT_CONNECTORS_HOSTNAME")),
        "sdk_installed":    stripe is not None,
    }


def detect_active_key_kind():
    """'test'/'live'/'unknown' from the prefix of the secret get_stripe() WOULD
    use — surfaces a mode-mismatch warning in the admin UI."""
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
    """Drop all cached keys — call after a mode switch or env change."""
    _KEY_CACHE.clear()
