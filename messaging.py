"""
Messaging — Email (Resend) + SMS (Twilio) sending, scheduling, and webhooks.

This module is intentionally self-contained so that the rest of the app
only needs `import messaging` to use it. It owns:

  * Provider key resolution (Resend prefers a Replit Connector when one is
    authorized; Twilio is env-only because the Replit integration was
    declined for this project — see replit.md)
  * Low-level send_email / send_sms helpers that talk to each provider
    directly via httpx (no provider SDKs needed)
  * The merge-tag renderer used by templates and campaigns
  * Unsubscribe-token signing/verifying (HMAC over the subscriber id)
  * A tiny in-process scheduler that ticks every 30 seconds and dispatches
    any campaigns whose `send_at` has arrived (single-start guard so the
    Flask debug reloader does not start two copies)
  * Webhook signature verification helpers for Resend (Svix) and Twilio
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx


# =============================================================================
# PROVIDER KEY RESOLUTION
# =============================================================================
# Resend can be wired through a Replit Connector (preferred — keys never touch
# the project's secret store) or through plain RESEND_API_KEY env var.
# Twilio is env-only here: the Replit integration was dismissed during setup,
# so the admin pastes TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER
# into the Secrets pane.

_RESEND_CACHE = {"settings": None, "fetched_at": 0.0}
_RESEND_TTL = 600


def _fetch_replit_resend_settings() -> Optional[Dict[str, Any]]:
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
        f"include_secrets=true&connector_names=resend&environment={target_env}"
    )
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "X-Replit-Token": token},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
        return None
    items = data.get("items") or []
    if not items:
        return None
    return items[0].get("settings") or {}


def _resolve_resend(force_refresh: bool = False) -> Tuple[str, str]:
    """Return (api_key, from_email)."""
    now = time.time()
    if (
        not force_refresh
        and _RESEND_CACHE["settings"] is not None
        and (now - _RESEND_CACHE["fetched_at"]) < _RESEND_TTL
    ):
        s = _RESEND_CACHE["settings"]
    else:
        s = _fetch_replit_resend_settings() or {}
        _RESEND_CACHE["settings"] = s
        _RESEND_CACHE["fetched_at"] = now

    api_key = (
        (s.get("api_key") if isinstance(s, dict) else None)
        or (s.get("RESEND_API_KEY") if isinstance(s, dict) else None)
        or os.environ.get("RESEND_API_KEY")
        or ""
    ).strip()
    from_email = (
        (s.get("from_email") if isinstance(s, dict) else None)
        or (s.get("RESEND_FROM_EMAIL") if isinstance(s, dict) else None)
        or os.environ.get("RESEND_FROM_EMAIL")
        or ""
    ).strip()
    return api_key, from_email


def resend_status() -> Dict[str, Any]:
    api_key, from_email = _resolve_resend()
    return {
        "configured": bool(api_key and from_email),
        "has_api_key": bool(api_key),
        "from_email": from_email,
    }


def twilio_status() -> Dict[str, Any]:
    sid = (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
    token = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
    from_number = (os.environ.get("TWILIO_FROM_NUMBER") or "").strip()
    return {
        "configured": bool(sid and token and from_number),
        "has_credentials": bool(sid and token),
        "from_number": from_number,
    }


def admin_contact() -> Dict[str, str]:
    return {
        "email": (os.environ.get("ADMIN_EMAIL") or "").strip(),
        "phone": (os.environ.get("ADMIN_PHONE") or "").strip(),
    }


# =============================================================================
# MERGE TAGS — {{first_name}} / {{email}} / {{phone}} / {{unsubscribe_url}}
# =============================================================================

_MERGE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_\.]+)\s*\}\}")


def render_merge_tags(text: str, context: Dict[str, Any]) -> str:
    """Replace {{key}} tokens with values from `context`. Missing keys
    render as an empty string so a half-filled subscriber row never
    produces a literal '{{first_name}}' in the final message."""
    if not text:
        return ""
    if not isinstance(context, dict):
        context = {}

    def _flat_lookup(key: str) -> str:
        # Support dotted lookups like {{order.total}} for future use.
        parts = key.split(".")
        cursor: Any = context
        for p in parts:
            if isinstance(cursor, dict) and p in cursor:
                cursor = cursor[p]
            else:
                return ""
        if cursor is None:
            return ""
        return str(cursor)

    return _MERGE_RE.sub(lambda m: _flat_lookup(m.group(1)), text)


def subscriber_context(sub: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build the merge-tag context for a subscriber row."""
    full = (sub.get("full_name") or "").strip()
    first = full.split(" ", 1)[0] if full else ""
    last = full.split(" ", 1)[1] if " " in full else ""
    ctx = {
        "id": sub.get("id"),
        "email": sub.get("email") or "",
        "phone": sub.get("phone") or "",
        "full_name": full,
        "first_name": first,
        "last_name": last,
    }
    # Custom JSON fields stored on the subscriber become merge tags too.
    custom = sub.get("custom_fields") or {}
    if isinstance(custom, dict):
        for k, v in custom.items():
            if isinstance(k, str) and k not in ctx:
                ctx[k] = v
    if extra:
        ctx.update(extra)
    return ctx


# =============================================================================
# UNSUBSCRIBE TOKEN — HMAC over the subscriber id
# =============================================================================

def _signing_secret() -> bytes:
    secret = os.environ.get("FLASK_SECRET_KEY", "").strip()
    if not secret:
        try:
            with open(".flask_secret", "r") as f:
                secret = f.read().strip()
        except FileNotFoundError:
            secret = ""
    if not secret:
        secret = "dev-fallback-secret-replace-me"
    return hashlib.sha256(secret.encode("utf-8")).digest()


def make_unsubscribe_token(subscriber_id: int) -> str:
    payload = f"{int(subscriber_id)}".encode("utf-8")
    sig = hmac.new(_signing_secret(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload + b"." + sig).decode("ascii").rstrip("=")


def parse_unsubscribe_token(token: str) -> Optional[int]:
    if not token:
        return None
    try:
        # Re-pad before decoding.
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode((token + pad).encode("ascii"))
    except Exception:
        return None
    if b"." not in raw:
        return None
    payload, sig = raw.split(b".", 1)
    expected = hmac.new(_signing_secret(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        return int(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


# Preferences-portal token (task 043). Same HMAC construction as the unsubscribe
# token, but the signed payload carries a distinct `prefs:` scope prefix so the
# two token types are NOT interchangeable: an unsubscribe link (which only flips
# opt_in off) can never be replayed to reach the broader prefs-edit surface, and
# vice-versa. Both are unguessable capability tokens keyed to one subscriber id.
_PREFS_SCOPE = b"prefs:"


def make_prefs_token(subscriber_id: int) -> str:
    payload = _PREFS_SCOPE + f"{int(subscriber_id)}".encode("utf-8")
    sig = hmac.new(_signing_secret(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload + b"." + sig).decode("ascii").rstrip("=")


def parse_prefs_token(token: str) -> Optional[int]:
    """Return the subscriber id for a valid prefs token, else None. Rejects a
    token whose payload lacks the `prefs:` scope (e.g. an unsubscribe token)."""
    if not token:
        return None
    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode((token + pad).encode("ascii"))
    except Exception:
        return None
    if b"." not in raw:
        return None
    payload, sig = raw.split(b".", 1)
    expected = hmac.new(_signing_secret(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    if not payload.startswith(_PREFS_SCOPE):
        return None
    try:
        return int(payload[len(_PREFS_SCOPE):].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


# =============================================================================
# LOW-LEVEL SEND HELPERS
# =============================================================================

class MessagingError(RuntimeError):
    """Raised when a provider call fails."""


def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    *,
    text_body: Optional[str] = None,
    from_override: Optional[str] = None,
    reply_to: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    tags: Optional[Iterable[Tuple[str, str]]] = None,
) -> Dict[str, Any]:
    """Send a single email through Resend. Returns the provider response
    (which includes the message id) on success; raises MessagingError on
    failure so the caller can mark the log row 'failed' with a reason."""
    api_key, default_from = _resolve_resend()
    if not api_key:
        raise MessagingError("Resend API key is not configured.")
    sender = (from_override or default_from or "").strip()
    if not sender:
        raise MessagingError("Resend sender (from_email) is not configured.")
    if not to_email or "@" not in to_email:
        raise MessagingError(f"Invalid recipient email: {to_email!r}")

    payload: Dict[str, Any] = {
        "from": sender,
        "to": [to_email],
        "subject": subject or "(no subject)",
        "html": html_body or "",
    }
    if text_body:
        payload["text"] = text_body
    if reply_to:
        payload["reply_to"] = reply_to
    if headers:
        payload["headers"] = headers
    if tags:
        payload["tags"] = [{"name": k, "value": v} for k, v in tags]

    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as e:
        raise MessagingError(f"Resend network error: {e}") from e

    if resp.status_code >= 400:
        body = resp.text[:500]
        raise MessagingError(f"Resend HTTP {resp.status_code}: {body}")
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text[:500]}
    return data


def send_sms(to_phone: str, body: str, *, from_override: Optional[str] = None,
             status_callback_url: Optional[str] = None) -> Dict[str, Any]:
    """Send a single SMS through Twilio's REST API."""
    sid = (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
    token = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
    sender = (from_override or os.environ.get("TWILIO_FROM_NUMBER") or "").strip()
    if not sid or not token:
        raise MessagingError("Twilio credentials are not configured.")
    if not sender:
        raise MessagingError("Twilio from-number is not configured.")
    if not to_phone:
        raise MessagingError("Invalid recipient phone (empty).")

    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    form: Dict[str, str] = {"To": to_phone, "From": sender, "Body": body or ""}
    if status_callback_url:
        form["StatusCallback"] = status_callback_url

    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(url, data=form, auth=(sid, token))
    except httpx.HTTPError as e:
        raise MessagingError(f"Twilio network error: {e}") from e

    if resp.status_code >= 400:
        body_txt = resp.text[:500]
        raise MessagingError(f"Twilio HTTP {resp.status_code}: {body_txt}")
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text[:500]}
    return data


# =============================================================================
# WEBHOOK SIGNATURE VERIFICATION
# =============================================================================

def verify_resend_signature(headers: Dict[str, str], raw_body: bytes) -> bool:
    """Resend uses Svix to sign webhooks. The signing secret is set in the
    Resend dashboard and provided to us via RESEND_WEBHOOK_SECRET. If the
    secret is not configured, we fail open with a warning so admins can
    still wire up webhooks before pasting the secret."""
    secret = (os.environ.get("RESEND_WEBHOOK_SECRET") or "").strip()
    if not secret:
        return True  # fail-open: caller logs a warning
    msg_id = headers.get("svix-id") or headers.get("Svix-Id") or ""
    timestamp = headers.get("svix-timestamp") or headers.get("Svix-Timestamp") or ""
    signature_header = headers.get("svix-signature") or headers.get("Svix-Signature") or ""
    if not (msg_id and timestamp and signature_header):
        return False
    # Svix secrets look like "whsec_<base64>"
    secret_value = secret.split("_", 1)[1] if secret.startswith("whsec_") else secret
    try:
        secret_bytes = base64.b64decode(secret_value)
    except Exception:
        secret_bytes = secret.encode("utf-8")
    signed_payload = f"{msg_id}.{timestamp}.".encode("utf-8") + raw_body
    expected = base64.b64encode(
        hmac.new(secret_bytes, signed_payload, hashlib.sha256).digest()
    ).decode("ascii")
    # Header looks like "v1,<sig> v1,<sig2>" — any match is fine.
    for entry in signature_header.split():
        parts = entry.split(",", 1)
        if len(parts) == 2 and hmac.compare_digest(parts[1], expected):
            return True
    return False


def verify_twilio_signature(url: str, params: Dict[str, str], header_signature: str) -> bool:
    """Verify Twilio's X-Twilio-Signature header. Twilio computes:
        HMAC-SHA1(auth_token, url + sorted(k+v for k,v in form_params))
    base64-encoded. If TWILIO_AUTH_TOKEN is missing we fail open so the
    handler can still log inbound STOP keywords during local dev."""
    token = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
    if not token:
        return True  # fail-open in dev / before config
    if not header_signature:
        return False
    data = url
    for key in sorted(params.keys()):
        data += key + (params[key] or "")
    expected = base64.b64encode(
        hmac.new(token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    ).decode("ascii")
    return hmac.compare_digest(expected, header_signature)


# =============================================================================
# CSV PARSING for subscriber import
# =============================================================================

def parse_subscriber_csv(text: str) -> List[Dict[str, Any]]:
    """Parse a CSV string into subscriber dicts. Recognizes any case-insensitive
    header among: email, phone, name/full_name/first_name+last_name. Any extra
    columns are stashed into custom_fields."""
    if not text:
        return []
    reader = csv.DictReader(io.StringIO(text))
    out: List[Dict[str, Any]] = []
    for raw in reader:
        if not raw:
            continue
        norm = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        email = norm.pop("email", "") or norm.pop("e-mail", "")
        phone = norm.pop("phone", "") or norm.pop("mobile", "") or norm.pop("phone_number", "")
        full_name = norm.pop("full_name", "") or norm.pop("name", "")
        if not full_name:
            first = norm.pop("first_name", "") or norm.pop("first", "")
            last = norm.pop("last_name", "") or norm.pop("last", "")
            full_name = (first + " " + last).strip()
        if not (email or phone):
            continue
        # Anything left over becomes a custom merge tag.
        custom = {k: v for k, v in norm.items() if v}
        out.append({
            "email": email,
            "phone": phone,
            "full_name": full_name,
            "custom_fields": custom,
        })
    return out


# =============================================================================
# BACKGROUND SCHEDULER — fires due campaigns
# =============================================================================
# A single daemon thread that wakes every 30 seconds and asks the registered
# tick callback to do its work. Module-level guard prevents the Flask debug
# reloader (which forks / re-execs) from starting two copies in the same
# process.

_SCHEDULER_LOCK = threading.Lock()
_SCHEDULER_STARTED = False
_TICK_INTERVAL = 30  # seconds; short enough that schedule-for-now feels instant
_TICK_CALLBACKS: List[Any] = []


def register_tick(fn) -> None:
    """Register a function that the scheduler should call on each tick."""
    _TICK_CALLBACKS.append(fn)


def _scheduler_loop():
    while True:
        try:
            for cb in list(_TICK_CALLBACKS):
                try:
                    cb()
                except Exception as e:  # never let one tick kill the loop
                    print(f"[messaging scheduler] tick error: {e}")
        except Exception as e:
            print(f"[messaging scheduler] outer error: {e}")
        time.sleep(_TICK_INTERVAL)


def start_scheduler() -> bool:
    """Start the background scheduler thread (idempotent). Returns True if
    we actually started a thread, False if one was already running.

    The caller (app.py) only invokes this from a Flask before_request hook,
    which guarantees we're inside the actual serving process — so we don't
    have to disambiguate the dev-reloader parent from the child here."""
    global _SCHEDULER_STARTED
    with _SCHEDULER_LOCK:
        if _SCHEDULER_STARTED:
            return False
        t = threading.Thread(target=_scheduler_loop, name="messaging-scheduler", daemon=True)
        t.start()
        _SCHEDULER_STARTED = True
        print("[messaging] background scheduler started")
        return True
