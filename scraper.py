"""
===============================================================================
AI WEB SCRAPER — fetch, clean, and AI-extract structured data
===============================================================================

This module powers the admin "Web Scraper" tab. Two input modes are supported:

  URL mode        Admin pastes a public URL. We fetch the page server-side
                  with a real browser User-Agent, a hard timeout, a response
                  size cap, and a content-type allowlist. Private/loopback
                  IP ranges are blocked to prevent SSRF. We strip scripts
                  and styles, then hand the cleaned text to OpenAI in
                  JSON mode along with the chosen target schema.

  Objective mode  Admin describes what they want (e.g. "find competitor
                  pricing for project management SaaS"). We hand the
                  objective to OpenAI's Responses API with the
                  web_search_preview tool so the model can browse and
                  summarize. Falls back to a knowledge-only answer with a
                  clear note if web search is not available on the
                  configured OpenAI client.

Rendered fetch (optional):
  Many marketing/booking sites are React/Vue SPAs that ship an empty
  HTML shell and assemble content client-side. Plain HTTP GETs return
  almost nothing useful. When the admin enables "rendered fetch" we
  retry through a headless-browser rendering provider (ScrapingBee or
  Browserless) configured via env vars. The same SSRF host validation
  and content-type allowlist still apply to the *target* URL — only
  the actual GET is delegated to the provider.

Out of scope (v1):
  - Crawling multiple pages or following links.
  - Authenticated pages.

The module exposes a small, opinionated API:

    fetch_url(url, disallowed_domains)        -> {ok, text, content_type, ...}
    fetch_url_rendered(url, disallowed_domains)
                                              -> same shape as fetch_url
    render_provider_status()                  -> {configured, provider, reason}
    research_objective(client, direct_client,
                       objective, target_shape, custom_schema)
                                              -> {ok, text, sources, ...}
    extract_with_ai(client, source_text,
                    target_shape, custom_schema, source_kind)
                                              -> dict (the structured record)
    TARGET_SHAPES                              -> dict of supported shapes
"""

from __future__ import annotations

import html as html_module
import ipaddress
import json
import os
import re
import socket
from typing import Any
from urllib.parse import urlparse

import httpx


# =============================================================================
# CONSTANTS
# =============================================================================

# Real-browser User-Agent so sites don't reject us as a bot before they even
# return the HTML. Many CDNs short-circuit obviously-headless clients.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

# Hard limits on the inbound response. The size cap stops a malicious or
# misconfigured server from streaming gigabytes through us; the timeout
# stops a slow server from tying up a worker thread forever.
_TIMEOUT_SECONDS = 15.0
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_MAX_REDIRECTS = 5

# Only these top-level types make sense for AI extraction. Anything else
# (images, video, binary blobs) is rejected upfront.
_ALLOWED_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "text/xml",
    "application/json",
    "application/xhtml+xml",
    "application/xml",
)

# Cap on the cleaned-text size handed to the model. ~50k characters is a
# generous chunk that keeps us under typical token budgets.
_CLEANED_TEXT_CAP = 50_000

# If the cleaned text is shorter than this it's almost certainly a JS-only
# shell page (think SPA boot HTML). We surface a clear hint in the UI.
_JS_ONLY_HINT_THRESHOLD = 120


# =============================================================================
# TARGET SHAPES — the structured-output contracts the AI must satisfy
# =============================================================================
# Each shape declares:
#   description    Free-form line shown to the model so it knows the intent.
#   fields         Ordered list of (name, description, required) tuples used
#                  both in the prompt and in post-extraction validation.
#   push_target    Optional name of a real table the extracted record can be
#                  copied into as a draft (None means "no push action").

TARGET_SHAPES: dict[str, dict[str, Any]] = {
    "free_form": {
        "label": "Free-form notes",
        "description": "A free-form summary plus key highlights — useful for general research.",
        "fields": [
            ("summary", "1–2 sentence summary of the page", True),
            ("highlights", "list of 3–8 short bullet strings capturing the most useful facts", True),
            ("notes", "any extra context that didn't fit into a highlight", False),
        ],
        "list_fields": {"highlights"},
        "push_target": None,
    },
    "gallery_card": {
        "label": "Gallery card",
        "description": "A single visual card with title, subtitle, image, and a few details.",
        "fields": [
            ("title", "short headline (max ~80 chars)", True),
            ("subtitle", "supporting one-liner under the title", True),
            ("category", "one or two word category label", True),
            ("description", "1–3 sentence description", True),
            ("image_url", "absolute URL to a hero image found on the page (or empty if none)", False),
            ("price", "price as a short string like '$199' or '' if none", False),
            ("details", "list of 3–6 short bullet strings of notable features", False),
        ],
        "list_fields": {"details"},
        "push_target": "gallery_card",
    },
    "pricing_tier": {
        "label": "Pricing tier",
        "description": "A single named pricing season/tier with date range and price range.",
        "fields": [
            ("label", "short tier name like 'Standard', 'Peak Season', 'Pro Plan'", True),
            ("date_range", "human-readable date range or season string (or '' if not applicable)", False),
            ("price_range", "human-readable price range like '$99–$149/mo'", True),
        ],
        "list_fields": set(),
        "push_target": "pricing_tier",
    },
    "blog_post": {
        "label": "Blog post draft",
        "description": "A draft blog post derived from an article on the page.",
        "fields": [
            ("title", "post title", True),
            ("subtitle", "post subtitle (or '' if not applicable)", False),
            ("excerpt", "1–2 sentence preview shown on cards", True),
            ("content", "the full body, well-formatted Markdown or plain text", True),
            ("author", "author's display name (or '' if unknown)", False),
            ("category", "one-word category (or '' if unknown)", False),
            ("tags", "comma-separated tags (or '' if none)", False),
            ("cover_image", "absolute URL to a cover image found on the page (or '')", False),
        ],
        "list_fields": set(),
        "push_target": "blog_post",
    },
    "contact_details": {
        "label": "Contact details",
        "description": "Public contact information for a business or person.",
        "fields": [
            ("company", "business or person name", False),
            ("email", "primary email address (or '')", False),
            ("phone", "primary phone number (or '')", False),
            ("address", "mailing address as a single line (or '')", False),
            ("website", "primary website URL (or '')", False),
            ("social", "object mapping platform → handle/url (e.g. {\"twitter\":\"@x\"}); use {} if none", False),
        ],
        "list_fields": set(),
        "push_target": None,
    },
    "custom": {
        "label": "Custom JSON schema",
        "description": "An admin-supplied JSON schema describing the desired output.",
        "fields": [],
        "list_fields": set(),
        "push_target": None,
    },
}


# =============================================================================
# SSRF PROTECTION
# =============================================================================

def _normalize_domain(d: str) -> str:
    """Lowercase + strip; drop leading dots / wildcards. Empty stays empty."""
    d = (d or "").strip().lower()
    if d.startswith("*."):
        d = d[2:]
    if d.startswith("."):
        d = d[1:]
    return d


def parse_disallowed_domains(raw: str) -> list[str]:
    """Parse the comma/newline-separated admin setting into a clean list.

    We accept commas and newlines so the admin can keep one entry per line
    in a textarea or paste a comma list — both feel natural. We strip
    leading dots and ``*.`` wildcards so ``*.evil.com`` and ``evil.com``
    are equivalent (any subdomain match).
    """
    if not raw:
        return []
    parts = re.split(r"[,\n]+", raw)
    return [d for d in (_normalize_domain(p) for p in parts) if d]


def _host_is_disallowed(host: str, disallowed: list[str]) -> bool:
    """Check whether ``host`` is on the admin's blocklist (with subdomain match)."""
    h = _normalize_domain(host)
    for blocked in disallowed:
        if h == blocked or h.endswith("." + blocked):
            return True
    return False


def _is_private_ip(ip_str: str) -> bool:
    """Return True if the IP is one we must refuse to talk to.

    We block: private (RFC1918), loopback, link-local, multicast,
    reserved, and unspecified (0.0.0.0 / ::). This is the standard
    SSRF defense — it stops a malicious URL from making the server
    open a connection to internal services like the metadata endpoint
    (169.254.169.254) or a local Postgres on 127.0.0.1.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        # If it doesn't parse, treat it as unsafe rather than guessing.
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_host(host: str, disallowed: list[str]) -> str | None:
    """Resolve ``host`` and confirm every IP it points to is publicly routable.

    Returns ``None`` when the host is safe to fetch from, or a short error
    message describing why it was refused.
    """
    if not host:
        return "Missing hostname."
    if _host_is_disallowed(host, disallowed):
        return f"Host '{host}' is on the admin disallowed list."
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return f"Could not resolve hostname '{host}'."
    seen: set[str] = set()
    for entry in infos:
        ip_str = entry[4][0]
        if ip_str in seen:
            continue
        seen.add(ip_str)
        if _is_private_ip(ip_str):
            return (
                f"Host '{host}' resolves to a private/loopback address "
                f"({ip_str}); refusing to fetch."
            )
    if not seen:
        return f"Could not resolve hostname '{host}'."
    return None


# =============================================================================
# SAFE HTTP FETCH
# =============================================================================

def _content_type_allowed(content_type: str) -> bool:
    """True if the response's content-type top-half is in our allowlist."""
    if not content_type:
        # Some servers (rarely) omit it; default to allowing — we'll cap by size.
        return True
    head = content_type.split(";", 1)[0].strip().lower()
    return head in _ALLOWED_CONTENT_TYPES


def _read_capped(response: httpx.Response, cap: int = _MAX_BYTES) -> tuple[bytes, bool]:
    """Stream the body in chunks, stopping at ``cap`` bytes.

    Returns ``(body_bytes, truncated)``. ``truncated=True`` means we hit
    the cap and threw away the rest; the caller should treat that as a
    failure (we don't want a half-document going to the model).
    """
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes(chunk_size=64 * 1024):
        chunks.append(chunk)
        total += len(chunk)
        if total > cap:
            return b"".join(chunks)[:cap], True
    return b"".join(chunks), False


def fetch_url(url: str, disallowed_domains: list[str] | None = None) -> dict[str, Any]:
    """Fetch a public URL safely and return the body + metadata.

    Returns a dict with at least ``ok`` (bool). On success: ``status``,
    ``content_type``, ``body`` (str), ``final_url``. On failure:
    ``error`` (short user-facing message).

    Redirects are followed manually (up to ``_MAX_REDIRECTS``) so we can
    re-validate the host on every hop — without that, a public URL could
    302 us into ``http://127.0.0.1/`` and bypass the SSRF check.
    """
    disallowed = disallowed_domains or []

    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        return {"ok": False, "error": "URL must start with http:// or https://."}
    if not parsed.hostname:
        return {"ok": False, "error": "URL is missing a hostname."}

    # Validate the initial host before opening any sockets.
    err = _validate_host(parsed.hostname, disallowed)
    if err:
        return {"ok": False, "error": err}

    current_url = url
    try:
        with httpx.Client(
            follow_redirects=False,
            timeout=_TIMEOUT_SECONDS,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        ) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                with client.stream("GET", current_url) as response:
                    # Follow redirects ourselves so we can re-validate hosts.
                    if response.is_redirect:
                        next_url = response.headers.get("location", "")
                        if not next_url:
                            return {"ok": False, "error": "Redirect with no Location header."}
                        # Resolve relative redirects against the current URL.
                        next_parsed = urlparse(next_url)
                        if not next_parsed.scheme:
                            from urllib.parse import urljoin
                            next_url = urljoin(current_url, next_url)
                            next_parsed = urlparse(next_url)
                        if next_parsed.scheme not in ("http", "https"):
                            return {"ok": False, "error": f"Refusing redirect to non-http(s) URL: {next_url}"}
                        err = _validate_host(next_parsed.hostname or "", disallowed)
                        if err:
                            return {"ok": False, "error": f"Redirect blocked: {err}"}
                        current_url = next_url
                        continue

                    if response.status_code >= 400:
                        return {
                            "ok": False,
                            "error": f"Server returned HTTP {response.status_code}.",
                            "status": response.status_code,
                        }

                    content_type = response.headers.get("content-type", "")
                    if not _content_type_allowed(content_type):
                        return {
                            "ok": False,
                            "error": (
                                f"Unsupported content type '{content_type}'. "
                                "We only handle HTML, plain text, and JSON."
                            ),
                        }

                    # Some servers advertise a giant Content-Length up front
                    # — reject early instead of reading the body.
                    declared = response.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > _MAX_BYTES:
                        return {
                            "ok": False,
                            "error": (
                                f"Response is {int(declared):,} bytes, which exceeds "
                                f"our {_MAX_BYTES:,}-byte cap. Try a smaller page."
                            ),
                        }

                    body_bytes, truncated = _read_capped(response, _MAX_BYTES)
                    if truncated:
                        return {
                            "ok": False,
                            "error": (
                                f"Response exceeded our {_MAX_BYTES:,}-byte cap. "
                                "Try a smaller page."
                            ),
                        }

                    # Decode using the response's declared charset, falling
                    # back to UTF-8 with replacement so we never crash here.
                    encoding = response.charset_encoding or "utf-8"
                    try:
                        body_text = body_bytes.decode(encoding, errors="replace")
                    except LookupError:
                        body_text = body_bytes.decode("utf-8", errors="replace")

                    return {
                        "ok": True,
                        "status": response.status_code,
                        "content_type": content_type,
                        "body": body_text,
                        "final_url": str(response.url),
                    }
            return {"ok": False, "error": f"Too many redirects (>{_MAX_REDIRECTS})."}
    except httpx.TimeoutException:
        return {"ok": False, "error": f"Request timed out after {_TIMEOUT_SECONDS:.0f}s."}
    except httpx.ConnectError as e:
        return {"ok": False, "error": f"Could not connect: {e}"}
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"HTTP error: {e}"}
    except Exception as e:  # noqa: BLE001 — surface anything unexpected to the UI
        return {"ok": False, "error": f"Unexpected fetch error: {e}"}


# =============================================================================
# RENDERED FETCH (headless-browser path for JS-only pages)
# =============================================================================
#
# Plain `fetch_url` is a single HTTP GET. Modern SPA marketing/booking sites
# render their content with React/Vue after the initial HTML loads, so a GET
# returns a near-empty shell. When the admin opts in to "rendered fetch" we
# delegate the GET to a hosted headless-browser provider that runs the JS
# and returns the post-render HTML.
#
# Two providers are supported, selected by the SCRAPER_RENDER_PROVIDER env
# var (default: "scrapingbee"):
#
#   scrapingbee   GET https://app.scrapingbee.com/api/v1/?api_key=…&url=…
#                 Requires SCRAPINGBEE_API_KEY.
#   browserless   POST {BROWSERLESS_URL}/content?token=…  with {"url": …}
#                 Requires BROWSERLESS_TOKEN. BROWSERLESS_URL defaults to
#                 https://chrome.browserless.io.
#
# We deliberately keep this provider-agnostic and side-effect-free at import
# time so the worker can call render_provider_status() to surface a clear
# message in the admin UI when nothing is configured.
#
# A rendered fetch typically takes 5-30 seconds (browser launch + JS run)
# so we use a generous timeout but still keep the size cap and content-type
# allowlist that protect the model from binary blobs and the worker thread
# from runaway responses.

# Rendering is slower than a plain GET — give it a longer budget. Hosted
# providers usually return within 10-20s; we pad a bit so a busy provider
# doesn't tip into a false timeout error.
_RENDER_TIMEOUT_SECONDS = 45.0


def _render_provider_config() -> dict[str, Any]:
    """Resolve the rendering provider + credentials from env vars.

    Returns a dict with at least ``provider`` (str) and ``configured`` (bool).
    On failure, ``reason`` explains what's missing so the admin UI can
    show an actionable message (e.g. "set SCRAPINGBEE_API_KEY").
    """
    provider = (os.getenv("SCRAPER_RENDER_PROVIDER") or "scrapingbee").strip().lower()
    if provider == "scrapingbee":
        api_key = (os.getenv("SCRAPINGBEE_API_KEY") or "").strip()
        if not api_key:
            return {
                "provider": provider,
                "configured": False,
                "reason": "Set SCRAPINGBEE_API_KEY to enable rendered fetch.",
            }
        return {
            "provider": provider,
            "configured": True,
            "api_key": api_key,
            "endpoint": "https://app.scrapingbee.com/api/v1/",
        }
    if provider == "browserless":
        token = (os.getenv("BROWSERLESS_TOKEN") or "").strip()
        base = (os.getenv("BROWSERLESS_URL") or "https://chrome.browserless.io").strip()
        if not token:
            return {
                "provider": provider,
                "configured": False,
                "reason": "Set BROWSERLESS_TOKEN to enable rendered fetch.",
            }
        return {
            "provider": provider,
            "configured": True,
            "token": token,
            "endpoint": base.rstrip("/") + "/content",
        }
    return {
        "provider": provider,
        "configured": False,
        "reason": (
            f"Unknown SCRAPER_RENDER_PROVIDER '{provider}'. "
            "Supported: scrapingbee, browserless."
        ),
    }


def render_provider_status() -> dict[str, Any]:
    """Public, secret-free view of the rendering config for the admin UI."""
    cfg = _render_provider_config()
    return {
        "provider": cfg.get("provider", ""),
        "configured": bool(cfg.get("configured")),
        "reason": cfg.get("reason", ""),
    }


def fetch_url_rendered(
    url: str,
    disallowed_domains: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch ``url`` through a headless-browser rendering provider.

    Same return shape as :func:`fetch_url` so callers can swap one for the
    other. The target host is SSRF-validated before we hand the URL to the
    provider — this stops an admin (or a redirect chain) from asking the
    rendering API to fetch private/loopback addresses on our behalf.

    The actual provider call goes to a known hosted endpoint
    (``app.scrapingbee.com`` or ``chrome.browserless.io``) so the outbound
    leg of the request can't be redirected somewhere unexpected.
    """
    disallowed = disallowed_domains or []

    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        return {"ok": False, "error": "URL must start with http:// or https://."}
    if not parsed.hostname:
        return {"ok": False, "error": "URL is missing a hostname."}

    err = _validate_host(parsed.hostname, disallowed)
    if err:
        return {"ok": False, "error": err}

    cfg = _render_provider_config()
    if not cfg.get("configured"):
        return {
            "ok": False,
            "error": cfg.get("reason", "Rendered fetch is not configured."),
        }

    provider = cfg["provider"]

    # Build the streaming request the same way the plain-fetch path does so
    # we can enforce the same hard in-flight byte cap (rather than buffering
    # the whole provider response and only checking its size after the fact).
    if provider == "scrapingbee":
        method = "GET"
        endpoint = cfg["endpoint"]
        request_kwargs: dict[str, Any] = {
            "params": {
                "api_key": cfg["api_key"],
                "url": url,
                "render_js": "true",
                # Block ads/trackers so the provider returns the page body
                # faster and we don't pay for noise.
                "block_ads": "true",
                "block_resources": "false",
            },
            "headers": {"User-Agent": _USER_AGENT},
        }
    elif provider == "browserless":
        method = "POST"
        endpoint = cfg["endpoint"]
        request_kwargs = {
            "params": {"token": cfg["token"]},
            "json": {
                "url": url,
                "gotoOptions": {"waitUntil": "networkidle2"},
            },
            "headers": {
                "User-Agent": _USER_AGENT,
                "Content-Type": "application/json",
            },
        }
    else:
        return {
            "ok": False,
            "error": f"Unsupported rendering provider '{provider}'.",
        }

    try:
        with httpx.Client(timeout=_RENDER_TIMEOUT_SECONDS) as client:
            with client.stream(method, endpoint, **request_kwargs) as response:
                if response.status_code >= 400:
                    # Read a small slice of the error body so we can surface
                    # the provider's actual reason ("Invalid API key", "Render
                    # limit reached", etc.) instead of a bare status code.
                    err_bytes, _ = _read_capped(response, 4096)
                    body_excerpt = err_bytes.decode("utf-8", errors="replace")[:200].strip()
                    msg = (
                        f"Rendered fetch provider returned HTTP {response.status_code}"
                        + (f": {body_excerpt}" if body_excerpt else ".")
                    )
                    return {
                        "ok": False, "error": msg,
                        "status": response.status_code,
                    }

                # Reject early on declared-too-large responses, then enforce
                # the cap during the actual stream as a defense in depth.
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > _MAX_BYTES:
                    return {
                        "ok": False,
                        "error": (
                            f"Rendered response is {int(declared):,} bytes, "
                            f"which exceeds our {_MAX_BYTES:,}-byte cap. "
                            "Try a smaller page."
                        ),
                    }

                body_bytes, truncated = _read_capped(response, _MAX_BYTES)
                if truncated:
                    return {
                        "ok": False,
                        "error": (
                            f"Rendered response exceeded our {_MAX_BYTES:,}-byte cap. "
                            "Try a smaller page."
                        ),
                    }

                # Both providers return rendered HTML, but the provider's
                # own content-type may be missing or generic — fall back to
                # text/html so clean_html() takes the HTML path.
                content_type = response.headers.get("content-type", "") or "text/html"
                if not _content_type_allowed(content_type):
                    content_type = "text/html"

                encoding = response.charset_encoding or "utf-8"
                try:
                    body_text = body_bytes.decode(encoding, errors="replace")
                except LookupError:
                    body_text = body_bytes.decode("utf-8", errors="replace")

                return {
                    "ok": True,
                    "status": response.status_code,
                    "content_type": content_type,
                    "body": body_text,
                    "final_url": url,
                    "rendered": True,
                    "render_provider": provider,
                }
    except httpx.TimeoutException:
        return {
            "ok": False,
            "error": (
                f"Rendered fetch timed out after {_RENDER_TIMEOUT_SECONDS:.0f}s. "
                "Try a smaller page or disable rendered fetch."
            ),
        }
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"Rendered fetch HTTP error: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Unexpected rendered-fetch error: {e}"}


# =============================================================================
# HTML CLEANER
# =============================================================================

# Pre-compiled patterns so we don't pay regex-compile cost per-job.
_RE_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script\s*>", flags=re.IGNORECASE | re.DOTALL)
_RE_STYLE = re.compile(r"<style\b[^>]*>.*?</style\s*>", flags=re.IGNORECASE | re.DOTALL)
_RE_NOSCRIPT = re.compile(r"<noscript\b[^>]*>.*?</noscript\s*>", flags=re.IGNORECASE | re.DOTALL)
_RE_COMMENT = re.compile(r"<!--.*?-->", flags=re.DOTALL)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_WHITESPACE = re.compile(r"[ \t\r\f\v]+")
_RE_BLANK_LINES = re.compile(r"\n{3,}")


def clean_html(body: str, content_type: str = "", cap: int = _CLEANED_TEXT_CAP) -> str:
    """Turn raw HTML/JSON/text into the plain text we hand to the model.

    For HTML/XML we strip scripts, styles, noscript, comments, then drop
    every tag and decode entities. For JSON/plain text we leave the body
    as-is so the model sees the structure verbatim. Output is whitespace-
    collapsed and capped at ``cap`` characters.
    """
    if not body:
        return ""

    head = (content_type or "").split(";", 1)[0].strip().lower()

    if head in ("application/json", "text/plain") or "json" in head:
        text = body
    else:
        text = _RE_SCRIPT.sub(" ", body)
        text = _RE_STYLE.sub(" ", text)
        text = _RE_NOSCRIPT.sub(" ", text)
        text = _RE_COMMENT.sub(" ", text)
        # Replace block-level closes with newlines so paragraphs survive.
        text = re.sub(r"</(p|div|li|h[1-6]|tr|br)\s*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = _RE_TAG.sub(" ", text)
        text = html_module.unescape(text)

    # Normalize whitespace without flattening paragraph breaks.
    text = _RE_WHITESPACE.sub(" ", text)
    text = _RE_BLANK_LINES.sub("\n\n", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = text.strip()

    if len(text) > cap:
        text = text[:cap]
    return text


def looks_js_only(cleaned_text: str) -> bool:
    """Heuristic: very short cleaned text usually means a JS-only SPA shell."""
    return len(cleaned_text) < _JS_ONLY_HINT_THRESHOLD


# =============================================================================
# AI EXTRACTION
# =============================================================================

# --- Editable system prompts (defaults; overridable from the admin UI) -------
# These mirror the wording used below and are registered in app.py's prompt
# registry. They are resolved at call time via _get_prompt() so a super-admin
# can edit them without touching code. Defined here (not imported from app) to
# avoid a circular import — app imports scraper at module load time.
SCRAPER_OBJECTIVE_INTRO = (
    "You are extracting structured data to satisfy an objective. "
    "Use the research notes provided. Stay strictly factual."
)
SCRAPER_URL_INTRO = (
    "You are extracting structured data from a public web page's text content. "
    "Stay strictly factual — never invent values."
)
SCRAPER_RESEARCH_PROMPT = (
    "You are a research assistant. Web browsing is unavailable, "
    "so answer from training knowledge. Be concise and factual. "
    "If you don't know something, say so."
)


def _get_prompt(key, default):
    """Resolve an admin-editable prompt by key, falling back to *default*.
    Imports app lazily so this module stays import-safe (app imports scraper)."""
    try:
        from app import get_prompt as _gp
        return _gp(key, default)
    except Exception:
        return default


def _build_schema_prompt(target_shape: str, custom_schema: dict | None) -> str:
    """Render the per-shape contract into a compact instruction the model can follow."""
    shape = TARGET_SHAPES.get(target_shape)
    if not shape:
        return "Return a JSON object with reasonable keys for the source content."

    if target_shape == "custom":
        if custom_schema:
            return (
                "Return a JSON object that strictly matches the schema below. "
                "Use empty strings, empty arrays, or null for missing values.\n\n"
                "SCHEMA:\n"
                + json.dumps(custom_schema, indent=2)
            )
        return (
            "Return a JSON object with whatever keys best capture the source content."
        )

    field_lines = []
    for name, desc, required in shape["fields"]:
        req_label = "REQUIRED" if required else "optional"
        field_lines.append(f'  "{name}": {desc} [{req_label}]')

    return (
        f"Target shape: {shape['label']}.\n"
        f"Goal: {shape['description']}\n"
        "Return a JSON object with EXACTLY these keys (no extras, no markdown):\n"
        + "\n".join(field_lines)
        + "\nUse empty string '' for missing string values. "
        "Use empty array [] for missing list values."
    )


def _strip_json_fences(text: str) -> str:
    """Remove ```json ... ``` fences a model sometimes wraps the JSON in."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


_SCHEMA_TYPE_CHECKERS: dict[str, Any] = {
    "string": lambda v: isinstance(v, str),
    "str": lambda v: isinstance(v, str),
    "text": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "float": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "bool": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "list": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "dict": lambda v: isinstance(v, dict),
}


def _validate_custom_schema(data: dict, custom_schema: dict) -> None:
    """Lightweight validator for the custom-schema mode.

    The admin's schema is just ``{key: type-name-or-example}``. We require
    every key to be present and, when the value is a recognised type name
    string, that the model's value matches that type. Unknown type strings
    are treated as documentation-only and skipped — we still require the
    key to exist. Raises ValueError with a single concise message listing
    every problem so the admin sees them all at once.
    """
    problems: list[str] = []
    for key, type_hint in custom_schema.items():
        if key not in data:
            problems.append(f"missing key '{key}'")
            continue
        if isinstance(type_hint, str):
            checker = _SCHEMA_TYPE_CHECKERS.get(type_hint.strip().lower())
            if checker is not None and not checker(data[key]):
                problems.append(
                    f"'{key}' should be {type_hint} but got {type(data[key]).__name__}"
                )
    if problems:
        raise ValueError(
            "AI output did not match your custom schema: " + "; ".join(problems)
        )


def _coerce_to_shape(target_shape: str, data: Any, custom_schema: dict | None = None) -> dict:
    """Best-effort coercion of the model's JSON into the declared shape.

    Models occasionally return strings where lists are expected (or vice
    versa) — we try to repair the simple cases instead of failing the
    whole job. Anything truly broken is bubbled up as a ValueError to
    the worker so the job lands in a 'failed' state with a clear error.
    """
    if not isinstance(data, dict):
        raise ValueError("Model did not return a JSON object.")

    shape = TARGET_SHAPES.get(target_shape)
    if target_shape == "custom":
        # For custom shapes, trust the admin's schema as the contract and
        # fail loudly if the model didn't honour it.
        if custom_schema:
            _validate_custom_schema(data, custom_schema)
        return data
    if not shape:
        return data

    out: dict[str, Any] = {}
    list_fields = shape["list_fields"]
    for name, _desc, required in shape["fields"]:
        value = data.get(name, "" if name not in list_fields else [])
        if name in list_fields:
            if isinstance(value, str):
                # Some models return a comma-separated string for arrays.
                value = [v.strip() for v in value.split(",") if v.strip()]
            if not isinstance(value, list):
                value = [str(value)] if value else []
        else:
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            elif isinstance(value, dict):
                # Pass dicts through for "social"-style fields, otherwise stringify.
                if name == "social":
                    pass
                else:
                    value = json.dumps(value)
            elif value is None:
                value = ""
            else:
                value = str(value)
        if required and not value and name not in list_fields:
            # Soft-required: leave empty rather than failing — the admin
            # will see the gap in the result viewer and can rerun.
            value = ""
        out[name] = value
    return out


def extract_with_ai(
    openai_client,
    source_text: str,
    target_shape: str,
    custom_schema: dict | None,
    source_kind: str = "url",
    source_label: str = "",
) -> dict:
    """Call OpenAI in JSON mode and return a validated structured record.

    ``source_text``  the cleaned page text (URL mode) OR an objective +
                     research notes (objective mode).
    ``source_kind``  'url' or 'objective' — used only for prompt phrasing.
    """
    schema_prompt = _build_schema_prompt(target_shape, custom_schema)

    if source_kind == "objective":
        intro = _get_prompt("scraper_objective_intro", SCRAPER_OBJECTIVE_INTRO)
        user_prompt = (
            f"OBJECTIVE: {source_label}\n\n"
            f"RESEARCH NOTES (from web search):\n{source_text}\n\n"
            f"{schema_prompt}"
        )
    else:
        intro = _get_prompt("scraper_url_intro", SCRAPER_URL_INTRO)
        user_prompt = (
            f"SOURCE URL: {source_label}\n\n"
            f"PAGE TEXT (already stripped of scripts and styles):\n{source_text}\n\n"
            f"{schema_prompt}"
        )

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": intro + " Respond with ONLY a JSON object — no markdown, no code fences."},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=2000,
    )

    raw = (response.choices[0].message.content or "").strip()
    raw = _strip_json_fences(raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model returned invalid JSON: {e}") from e

    return _coerce_to_shape(target_shape, data, custom_schema=custom_schema)


# =============================================================================
# OBJECTIVE-MODE RESEARCH (web search via OpenAI Responses API)
# =============================================================================

def research_objective(
    openai_client,
    openai_direct_client,
    objective: str,
) -> dict[str, Any]:
    """Use OpenAI's web_search_preview tool to research an objective.

    Tries the direct OpenAI client first (the Responses API + built-in
    web_search_preview tool needs the official endpoint, not the
    integrations proxy). If that's not configured or the tool isn't
    available, falls back to a plain chat completion using the model's
    training knowledge — and adds a clear note so the admin knows the
    answer wasn't actually web-sourced.

    Returns a dict with:
      ok        bool
      text      research notes the extractor will read
      sources   list of {title, url} when available
      web_used  True if real web search ran
      note      optional human-readable caveat
    """
    objective = (objective or "").strip()
    if not objective:
        return {"ok": False, "error": "Objective is empty."}

    client = openai_direct_client or openai_client
    if client is None:
        return {"ok": False, "error": "OpenAI client is not configured."}

    instruction = (
        "Research the following objective by browsing the web. Produce a concise "
        "set of research notes (bullet list, ~10–25 lines) that captures the most "
        "useful facts, names, prices, and links. End with a short 'Sources:' "
        "section listing the URLs you used. Stay strictly factual.\n\n"
        f"OBJECTIVE: {objective}"
    )

    # 1) Try the Responses API with web_search_preview.
    try:
        resp = client.responses.create(
            model="gpt-4o-mini",
            tools=[{"type": "web_search_preview"}],
            input=instruction,
        )
        text = getattr(resp, "output_text", "") or ""
        sources = _extract_response_sources(resp)
        if text.strip():
            return {
                "ok": True,
                "text": text.strip(),
                "sources": sources,
                "web_used": True,
                "note": "",
            }
    except Exception as e:  # noqa: BLE001 — fall through to the plain-chat fallback
        fallback_reason = f"web search unavailable ({e.__class__.__name__})"
    else:
        fallback_reason = "web search returned no text"

    # 2) Plain chat completion fallback. We make the limitation obvious so
    # the admin doesn't mistake the model's training knowledge for a fresh
    # web search.
    try:
        completion = (openai_direct_client or openai_client).chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": _get_prompt("scraper_research", SCRAPER_RESEARCH_PROMPT),
                },
                {"role": "user", "content": objective},
            ],
            temperature=0.3,
            max_tokens=1200,
        )
        text = (completion.choices[0].message.content or "").strip()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Research failed: {e}"}

    return {
        "ok": True,
        "text": text,
        "sources": [],
        "web_used": False,
        "note": (
            "Live web search wasn't available for this run "
            f"({fallback_reason}); answer is based on the model's training "
            "knowledge and may be out of date."
        ),
    }


def _extract_response_sources(resp) -> list[dict[str, str]]:
    """Best-effort: pull URLs the Responses API surfaced as citations.

    The Responses API shape varies across model/tool versions; we walk
    everything defensively and never let a parse error kill the job.
    """
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    try:
        output = getattr(resp, "output", None) or []
        for item in output:
            content = getattr(item, "content", None) or []
            for c in content:
                annots = getattr(c, "annotations", None) or []
                for a in annots:
                    url = getattr(a, "url", "") or ""
                    title = getattr(a, "title", "") or url
                    if url and url not in seen:
                        seen.add(url)
                        sources.append({"title": title, "url": url})
    except Exception:  # noqa: BLE001
        pass
    return sources


__all__ = [
    "TARGET_SHAPES",
    "fetch_url",
    "clean_html",
    "looks_js_only",
    "extract_with_ai",
    "research_objective",
    "parse_disallowed_domains",
]
