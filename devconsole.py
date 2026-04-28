"""
Developer Console — provider health probes + runbook backing data.

The admin "Developer" tab uses two backend endpoints:

  * GET  /admin/api/devconsole/snapshot     (no network calls)
  * POST /admin/api/devconsole/test-provider (one network call, by name)

This module owns the network probes for the second endpoint and the
"configured?" detection for the first. Each probe is intentionally
cheap so an operator can press "Test now" without burning quota:

  * openai        GET  /v1/models                   (free, lists models)
  * anthropic     GET  /v1/models                   (free)
  * twilio        GET  /Accounts/{SID}.json         (free, account fetch)
  * resend        GET  /domains                     (free)
  * elevenlabs    GET  /v1/user                     (free, account info)
  * brave_search  GET  /res/v1/web/search?q=test    (1 query unit, cheap)
  * yelp          GET  /v3/businesses/search?...    (1 API call)
  * google_places GET  /place/findplacefromtext     (1 SKU; cheapest read)
  * tripadvisor   GET  /location/search?...         (1 API call)

Every probe wraps in try/except so a network outage or quota error
becomes a structured `{configured, ok, latency_ms, error}` dict
rather than a 500 in the admin UI. 8s timeout per call — a slow
provider should surface as a failed probe, not as a hung tab.

Why a separate module: each probe is small but they add up to
~250 lines of httpx code with auth header variations, response
parsing, and graceful failure. Keeping them out of app.py means
adding a new provider doesn't touch the route layer.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional

import httpx


# Param-name allowlist for query-string secrets we will redact from any
# error message a probe returns. Two providers (Google Places + TripAdvisor)
# pass the API key in the URL via `?key=...`, so an `httpx.HTTPError`
# whose `str()` includes the failing URL — or a 401 response body that
# echoes the URL back — would otherwise leak the key into the JSON the
# admin browser receives. Header-based auth providers don't have this
# class of leak, but we still mask their tokens defensively in case a
# provider error body ever quotes a request header.
_SECRET_PARAM_KEYS = {"key", "api_key", "apikey", "token", "access_token", "auth"}
_SECRET_HEADER_KEYS = {"authorization", "x-api-key", "xi-api-key", "x-subscription-token"}


def _redact(text: str, secrets: List[str]) -> str:
    """Mask every occurrence of each secret in `text` with [REDACTED].

    Two layers of defence:
      1. Replace any literal occurrence of a known secret value (the
         API key, the bearer token, the basic-auth password) with
         [REDACTED].
      2. Belt-and-suspenders: strip the entire `?query` portion of any
         URL embedded in the message and replace it with `?[REDACTED]`.
         This way, even an unrecognised secret format (e.g. a future
         provider that uses a non-standard query param name) still
         doesn't leak via a URL embedding inside an httpx error.
    """
    out = text
    for s in secrets:
        # Only mask reasonably-long values to avoid accidentally
        # eating short common substrings.
        if s and len(s) >= 6:
            out = out.replace(s, "[REDACTED]")
    # Strip query strings from any URLs in the message. The pattern
    # matches http(s)://host/path?... and replaces the ?... portion.
    out = re.sub(
        r"(https?://[^\s'\"<>]+?)\?[^\s'\"<>]*",
        r"\1?[REDACTED]",
        out,
    )
    return out


# Per-probe network timeout. 8s is generous for a healthy provider but
# short enough that an outage doesn't make the admin tab feel hung.
_TIMEOUT_S = 8.0


# Canonical list of providers the Developer tab knows about.
# Order matters: this is the order they render in the UI.
PROVIDERS: List[str] = [
    "openai",
    "anthropic",
    "twilio",
    "resend",
    "elevenlabs",
    "brave_search",
    "yelp",
    "google_places",
    "tripadvisor",
]


def _is_configured(name: str) -> bool:
    """Return True iff the env vars / connector for `name` look ready.

    We accept either the canonical env var or a Replit-managed alias
    where one exists (currently OpenAI via AI_INTEGRATIONS_OPENAI_API_KEY,
    Resend via the connector handled inside messaging._resolve_resend).
    """
    if name == "openai":
        return bool(
            (os.environ.get("OPENAI_API_KEY") or "").strip()
            or (os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY") or "").strip()
        )
    if name == "anthropic":
        return bool((os.environ.get("ANTHROPIC_API_KEY") or "").strip())
    if name == "twilio":
        return bool(
            (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
            and (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
        )
    if name == "resend":
        # Resend may come via Replit Connector (handled in messaging) or
        # via a plain env var. We surface "configured" if either path
        # currently yields an api_key — defer to messaging.resend_status
        # so we don't duplicate the connector lookup logic here.
        try:
            import messaging
            return bool(messaging.resend_status().get("has_api_key"))
        except Exception:
            return bool((os.environ.get("RESEND_API_KEY") or "").strip())
    if name == "elevenlabs":
        return bool((os.environ.get("ELEVENLABS_API_KEY") or "").strip())
    if name == "brave_search":
        return bool((os.environ.get("BRAVE_SEARCH_API_KEY") or "").strip())
    if name == "yelp":
        return bool((os.environ.get("YELP_API_KEY") or "").strip())
    if name == "google_places":
        return bool((os.environ.get("GOOGLE_PLACES_API_KEY") or "").strip())
    if name == "tripadvisor":
        return bool((os.environ.get("TRIPADVISOR_API_KEY") or "").strip())
    return False


def provider_summary() -> List[Dict[str, Any]]:
    """Return one dict per known provider with `configured` only — NO
    network calls. Used by the GET /snapshot endpoint so opening the
    Developer tab never burns provider quota or waits on network."""
    return [
        {"name": name, "configured": _is_configured(name)}
        for name in PROVIDERS
    ]


# ---------------------------------------------------------------------------
# Probes — one per provider. Each returns a fully populated dict, never
# raises. Caller wraps the chosen probe with `probe(name)` for dispatch.
# ---------------------------------------------------------------------------

def _ok(latency_ms: float, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": True, "latency_ms": round(latency_ms), "error": None}
    if extra:
        out.update(extra)
    return out


def _err(latency_ms: float, msg: str) -> Dict[str, Any]:
    return {"ok": False, "latency_ms": round(latency_ms), "error": msg[:300]}


def _collect_secrets(
    headers: Optional[Dict[str, str]],
    auth: Optional[tuple],
    params: Optional[Dict[str, str]],
) -> List[str]:
    """Pull every secret-bearing value from the request inputs so we
    can redact it from any error message we return to the admin UI."""
    secrets: List[str] = []
    if params:
        for pk, pv in params.items():
            if pk.lower() in _SECRET_PARAM_KEYS and pv:
                secrets.append(str(pv))
    if headers:
        for hk, hv in headers.items():
            if hk.lower() in _SECRET_HEADER_KEYS and hv:
                secrets.append(hv)
                # Also mask the bare token half of "Bearer xxx" / "Basic xxx"
                # in case the response body echoes only the token portion.
                low = hv.lower()
                if low.startswith(("bearer ", "basic ")) and " " in hv:
                    secrets.append(hv.split(" ", 1)[1])
    if auth:
        # httpx basic auth tuple — both halves are sensitive.
        for v in auth:
            if v:
                secrets.append(str(v))
    return secrets


def _http_probe(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    auth: Optional[tuple] = None,
    params: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Generic probe runner. Times the request, classifies the response,
    and returns the standard `{ok, latency_ms, error}` shape with any
    embedded secrets stripped from the error string."""
    secrets = _collect_secrets(headers, auth, params)
    started = time.monotonic()
    try:
        with httpx.Client(timeout=_TIMEOUT_S) as client:
            resp = client.request(
                method, url,
                headers=headers or {},
                auth=auth,
                params=params,
            )
    except httpx.TimeoutException:
        return _err(
            (time.monotonic() - started) * 1000,
            _redact(f"timeout after {_TIMEOUT_S}s", secrets),
        )
    except httpx.HTTPError as e:
        # `str(e)` from httpx commonly includes the request URL — for
        # query-param providers (Google Places, TripAdvisor) that URL
        # carries the API key. Redact before returning.
        return _err(
            (time.monotonic() - started) * 1000,
            _redact(f"network error: {e}", secrets),
        )

    elapsed_ms = (time.monotonic() - started) * 1000
    if resp.status_code >= 400:
        # Provider error bodies sometimes echo the failing URL or the
        # offending header back at the caller. Redact defensively.
        snippet = (resp.text or "")[:200].replace("\n", " ")
        return _err(
            elapsed_ms,
            _redact(f"HTTP {resp.status_code}: {snippet}", secrets),
        )
    return _ok(elapsed_ms, {"status": resp.status_code})


def _probe_openai() -> Dict[str, Any]:
    key = (
        (os.environ.get("OPENAI_API_KEY") or "").strip()
        or (os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY") or "").strip()
    )
    if not key:
        return _err(0, "OPENAI_API_KEY not set")
    base = (
        os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    ).rstrip("/")
    return _http_probe("GET", f"{base}/models", headers={
        "Authorization": f"Bearer {key}",
    })


def _probe_anthropic() -> Dict[str, Any]:
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        return _err(0, "ANTHROPIC_API_KEY not set")
    return _http_probe("GET", "https://api.anthropic.com/v1/models", headers={
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    })


def _probe_twilio() -> Dict[str, Any]:
    sid = (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
    token = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
    if not (sid and token):
        return _err(0, "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN not set")
    return _http_probe(
        "GET",
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json",
        auth=(sid, token),
    )


def _probe_resend() -> Dict[str, Any]:
    # Try the connector path first (preferred), then env var fallback.
    api_key = ""
    try:
        import messaging
        api_key, _from = messaging._resolve_resend()
    except Exception:
        pass
    if not api_key:
        api_key = (os.environ.get("RESEND_API_KEY") or "").strip()
    if not api_key:
        return _err(0, "Resend API key not configured (connector or RESEND_API_KEY)")
    return _http_probe("GET", "https://api.resend.com/domains", headers={
        "Authorization": f"Bearer {api_key}",
    })


def _probe_elevenlabs() -> Dict[str, Any]:
    key = (os.environ.get("ELEVENLABS_API_KEY") or "").strip()
    if not key:
        return _err(0, "ELEVENLABS_API_KEY not set")
    return _http_probe("GET", "https://api.elevenlabs.io/v1/user", headers={
        "xi-api-key": key,
    })


def _probe_brave_search() -> Dict[str, Any]:
    key = (os.environ.get("BRAVE_SEARCH_API_KEY") or "").strip()
    if not key:
        return _err(0, "BRAVE_SEARCH_API_KEY not set")
    # 1-result query keeps this well under the cheapest plan tier.
    return _http_probe(
        "GET",
        "https://api.search.brave.com/res/v1/web/search",
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
        params={"q": "ping", "count": "1"},
    )


def _probe_yelp() -> Dict[str, Any]:
    key = (os.environ.get("YELP_API_KEY") or "").strip()
    if not key:
        return _err(0, "YELP_API_KEY not set")
    return _http_probe(
        "GET",
        "https://api.yelp.com/v3/businesses/search",
        headers={"Authorization": f"Bearer {key}"},
        params={"location": "New York, NY", "limit": "1"},
    )


def _probe_google_places() -> Dict[str, Any]:
    key = (os.environ.get("GOOGLE_PLACES_API_KEY") or "").strip()
    if not key:
        return _err(0, "GOOGLE_PLACES_API_KEY not set")
    # Find Place is the cheapest Places SKU. Empty results are still
    # a valid 200 OK from the API's perspective.
    return _http_probe(
        "GET",
        "https://maps.googleapis.com/maps/api/place/findplacefromtext/json",
        params={
            "input": "Eiffel Tower",
            "inputtype": "textquery",
            "fields": "name",
            "key": key,
        },
    )


def _probe_tripadvisor() -> Dict[str, Any]:
    key = (os.environ.get("TRIPADVISOR_API_KEY") or "").strip()
    if not key:
        return _err(0, "TRIPADVISOR_API_KEY not set")
    return _http_probe(
        "GET",
        "https://api.content.tripadvisor.com/api/v1/location/search",
        params={"key": key, "searchQuery": "Eiffel Tower", "language": "en"},
    )


_PROBES = {
    "openai": _probe_openai,
    "anthropic": _probe_anthropic,
    "twilio": _probe_twilio,
    "resend": _probe_resend,
    "elevenlabs": _probe_elevenlabs,
    "brave_search": _probe_brave_search,
    "yelp": _probe_yelp,
    "google_places": _probe_google_places,
    "tripadvisor": _probe_tripadvisor,
}


def probe(name: str) -> Dict[str, Any]:
    """Run the probe for `name` and return the standard result dict.
    Returns an `{error: 'unknown provider'}` dict for an unknown name
    so the route handler can 400 cleanly without raising."""
    fn = _PROBES.get(name)
    if fn is None:
        return {"ok": False, "latency_ms": 0, "error": f"unknown provider: {name}"}
    if not _is_configured(name):
        return _err(0, f"{name} is not configured (missing env var or connector)")
    try:
        return fn()
    except Exception as e:
        return _err(0, f"probe crashed: {e!r}")
