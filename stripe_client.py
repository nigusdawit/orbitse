"""
Stripe client + key resolver.

This module supports two ways to authenticate Stripe:

1. Replit-managed Stripe connection (preferred when present): we read the
   secret + publishable key from the Replit Connectors API, using the
   REPL_IDENTITY / WEB_REPL_RENEWAL token Replit injects into the runtime.
   Tokens are short-lived, so we cache the resolved keys for ~10 minutes
   and refresh on the next call.

2. Raw env vars (fallback for local / non-Replit / production publishing):
   STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_WEBHOOK_SECRET.

Callers should ALWAYS use `get_stripe()` to construct a fresh client per
request rather than caching the module-level `stripe` import. The
`stripe.api_key` global is mutated by `get_stripe()` so any subsequent
SDK call inside the same request will use the right key.
"""
import os
import time
import json
import urllib.request
import urllib.error

import stripe

_KEY_CACHE = {"secret": None, "publishable": None, "fetched_at": 0.0}
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


def _resolve_keys(force_refresh: bool = False):
    """Return (secret_key, publishable_key) using cache + Replit + env fallback."""
    now = time.time()
    if (
        not force_refresh
        and _KEY_CACHE["secret"]
        and (now - _KEY_CACHE["fetched_at"]) < _CACHE_TTL
    ):
        return _KEY_CACHE["secret"], _KEY_CACHE["publishable"]

    secret = None
    publishable = None

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

    if not secret:
        secret = os.environ.get("STRIPE_SECRET_KEY") or None
    if not publishable:
        publishable = os.environ.get("STRIPE_PUBLISHABLE_KEY") or None

    _KEY_CACHE["secret"] = secret
    _KEY_CACHE["publishable"] = publishable
    _KEY_CACHE["fetched_at"] = now
    return secret, publishable


def get_publishable_key() -> str:
    """Public-safe key for the storefront JS."""
    _, pub = _resolve_keys()
    return pub or ""


def get_webhook_secret() -> str:
    """Webhook signing secret from env (set in Stripe dashboard → Webhooks)."""
    return os.environ.get("STRIPE_WEBHOOK_SECRET", "")


def is_configured() -> bool:
    secret, _ = _resolve_keys()
    return bool(secret)


def get_stripe():
    """Return the `stripe` module with `api_key` set for this request.

    Raises RuntimeError if no key is available so callers fail fast.
    """
    secret, _ = _resolve_keys()
    if not secret:
        # Try one forced refresh in case the connector was just authorized.
        secret, _ = _resolve_keys(force_refresh=True)
    if not secret:
        raise RuntimeError(
            "Stripe is not configured. Connect Stripe via the Replit "
            "integration or set STRIPE_SECRET_KEY."
        )
    stripe.api_key = secret
    return stripe
