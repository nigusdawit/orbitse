"""
Automations — no-code "if X then Y" workflow engine.

Owns the trigger publishers, the action runner, and the supporting
safety limits (per-automation rate limit, max concurrent runs,
overall run timeout). The runner is intentionally thread-based and
self-contained so the rest of the app only needs `import automations`.

Design notes
------------

* **Two paths into the runner.** Event-style triggers (form submit,
  new chat, webhook, manual test) call `dispatch_event()` which
  immediately spins a daemon thread (subject to a semaphore-style
  concurrency cap). If we're at the cap, the run is left in the
  `queued` state in the DB and the scheduler tick picks it up later.

* **One scheduler tick.** We register a callback with messaging's
  existing 30-second tick instead of standing up a second thread, so
  the dev reloader still only ever sees one scheduler. The tick does
  two things: (a) launch any due `schedule` triggers, (b) drain any
  runs left `queued` because we were over the concurrency cap.

* **Merge tags everywhere.** Action configs are JSON. We walk them
  recursively and replace `{{key}}` / `{{step1.field}}` tokens with
  values pulled from the run context. This is intentionally a
  superset of messaging.render_merge_tags so step outputs work too.

* **Strict per-step timeouts.** HTTP steps wrap httpx with an
  enforced timeout. The overall run is bounded by MAX_RUN_SECONDS
  (checked between steps) so a stuck delay step or a slow chain
  cannot pin a worker forever.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx


# =============================================================================
# CONFIG / LIMITS
# =============================================================================

MAX_CONCURRENT_RUNS = int(os.environ.get("AUTOMATIONS_MAX_CONCURRENT", "5"))
MAX_RUNS_PER_HOUR_PER_AUTOMATION = int(
    os.environ.get("AUTOMATIONS_MAX_PER_HOUR", "60")
)
MAX_RUN_SECONDS = int(os.environ.get("AUTOMATIONS_MAX_RUN_SECONDS", "120"))
HTTP_STEP_TIMEOUT_SECONDS = int(os.environ.get("AUTOMATIONS_HTTP_TIMEOUT", "15"))
DELAY_STEP_MAX_SECONDS = int(os.environ.get("AUTOMATIONS_DELAY_MAX", "300"))
AI_STEP_TIMEOUT_SECONDS = int(os.environ.get("AUTOMATIONS_AI_TIMEOUT", "30"))

# Run-history retention. The cleanup tick deletes any `automation_runs` row
# older than the effective retention-days value, but always keeps the most
# recent keep-recent-per-automation rows regardless of age — so a quiet
# automation never loses *all* its history. A busy webhook capped at
# 60 runs/hour writes ~525k rows/year per automation; this keeps the table
# (and the editor's "recent runs" panel) bounded.
#
# These two env vars are the *fallback* defaults. Admins can override them
# at runtime from the Automations UI; the override is stored in the
# `automation_settings` singleton row and read by `_effective_retention()`
# on each cleanup pass. When no override is set, the env-var values win,
# preserving the pre-existing behaviour of installs that never visit the
# settings panel.
RETENTION_DAYS = max(1, int(os.environ.get("AUTOMATIONS_RETENTION_DAYS", "30")))
RETENTION_KEEP_RECENT = max(
    0, int(os.environ.get("AUTOMATIONS_RETENTION_KEEP_RECENT", "100"))
)
# Hard upper bounds we apply to whatever the admin enters in the UI. The
# DB column is plain INTEGER, so we clamp here to keep absurd values (e.g.
# 10-year retention) from being silently accepted. These bounds also gate
# the `app.py` PUT route that writes to the table.
RETENTION_DAYS_MAX = 3650          # 10 years
RETENTION_KEEP_RECENT_MAX = 100000
# How often the cleanup pass actually does work (cheap NO-OP otherwise).
RETENTION_TICK_INTERVAL_SECONDS = max(
    60, int(os.environ.get("AUTOMATIONS_RETENTION_TICK_SECONDS", "86400"))
)


# =============================================================================
# CONCURRENCY GATE
# =============================================================================
# A simple counter + lock so we can both enforce a cap AND report how many
# runs are in flight (handy for the admin "Status" view).

_run_lock = threading.Lock()
_in_flight: int = 0


def _try_acquire_slot() -> bool:
    global _in_flight
    with _run_lock:
        if _in_flight >= MAX_CONCURRENT_RUNS:
            return False
        _in_flight += 1
        return True


def _release_slot() -> None:
    global _in_flight
    with _run_lock:
        _in_flight = max(0, _in_flight - 1)


def in_flight_count() -> int:
    with _run_lock:
        return _in_flight


# =============================================================================
# REGISTRY — set by app.py at import time so we can keep this module
# free of `from app import …` (which would create a circular import).
# =============================================================================

_DB: Dict[str, Callable[..., Any]] = {}
_ACTION_HOOKS: Dict[str, Callable[..., Any]] = {}

# Bridge to the chat-tool dispatcher in app.py. Set by `set_skill_executor`
# so the `call_skill` action can fan out to every enabled chat skill (built-ins,
# custom webhooks, custom SQL, knowledge, MCP tools) without `automations.py`
# needing to import from app.py. Returns a dict shaped like:
#     {"ok": bool, "result": Any, "error": Optional[str]}
_SKILL_EXECUTOR: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None


def set_skill_executor(fn: Callable[[str, Dict[str, Any]], Dict[str, Any]]) -> None:
    """Wire in the chat-tool dispatcher used by the `call_skill` action.
    Call once from app.py at startup, after `configure(...)`."""
    global _SKILL_EXECUTOR
    _SKILL_EXECUTOR = fn


def register_action(kind: str, impl: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
                    metadata: Optional[Dict[str, Any]] = None) -> None:
    """Register an external action implementation (called by app.py at startup).

    Purely additive — extends the dispatch table + the builder UI metadata
    WITHOUT this module importing app.py and WITHOUT touching the built-in
    actions. `impl` is callable(rendered_cfg, ctx) -> {"ok": bool, ...} (same
    contract as the built-in actions; merge tags in cfg are already rendered by
    the engine before impl is called). `metadata`, if given, is an ACTION_TYPES-
    shaped dict shown in the automation builder."""
    kind = (kind or "").strip()
    if not kind:
        return
    _ACTION_DISPATCH[kind] = impl
    if metadata:
        for i, a in enumerate(ACTION_TYPES):
            if a.get("kind") == kind:
                ACTION_TYPES[i] = metadata
                return
        ACTION_TYPES.append(metadata)


def configure(
    *,
    query_db: Callable[..., Any],
    execute_db: Callable[..., Any],
    database_url: Optional[str] = None,
    openai_client: Any = None,
    public_base_url_fn: Optional[Callable[[], str]] = None,
    schema_introspect_fn: Optional[Callable[[], Dict[str, Any]]] = None,
    table_blocklist: Optional[set] = None,
    qident_fn: Optional[Callable[[str], str]] = None,
    messaging_module: Any = None,
    cost_cap_blocks_send_fn: Optional[Callable[..., bool]] = None,
    record_sms_cost_fn: Optional[Callable[..., None]] = None,
) -> None:
    """Bind app-level helpers in. Called once from app.py at import time.
    `database_url` is required for the atomic rate-limit + queue path
    (which needs its own transactional connection)."""
    _DB["query_db"] = query_db
    _DB["execute_db"] = execute_db
    _DB["database_url"] = database_url or os.environ.get("DATABASE_URL")
    _DB["openai_client"] = openai_client
    _DB["public_base_url_fn"] = public_base_url_fn or (lambda: "")
    _DB["schema_introspect_fn"] = schema_introspect_fn or (lambda: {})
    _DB["table_blocklist"] = table_blocklist or set()
    _DB["qident_fn"] = qident_fn or (lambda n: '"' + n.replace('"', '""') + '"')
    _DB["messaging"] = messaging_module
    # Phase 2 cost-control hooks. Optional — when not wired (older
    # tests / callers) the SMS action falls back to send-without-ledger
    # so existing automations don't break.
    _DB["cost_cap_blocks_send"] = cost_cap_blocks_send_fn
    _DB["record_sms_cost"] = record_sms_cost_fn


def _query_db(*args, **kwargs):
    return _DB["query_db"](*args, **kwargs)


def _execute_db(*args, **kwargs):
    return _DB["execute_db"](*args, **kwargs)


# =============================================================================
# TRIGGER + ACTION REGISTRIES — declarative metadata for the UI
# =============================================================================

TRIGGER_TYPES = [
    {
        "kind": "form_submitted",
        "label": "When a form is submitted",
        "config_fields": [
            {
                "name": "form_slug",
                "label": "Form (leave blank for any form)",
                "kind": "form_picker",
            },
        ],
    },
    {
        "kind": "new_chat",
        "label": "When a new chat conversation starts",
        "config_fields": [],
    },
    {
        "kind": "schedule",
        "label": "On a schedule",
        "config_fields": [
            {
                "name": "mode",
                "label": "Schedule type",
                "kind": "select",
                "options": [
                    {"value": "interval", "label": "Every N minutes"},
                    {"value": "daily", "label": "Once a day at a fixed time"},
                ],
            },
            {
                "name": "interval_minutes",
                "label": "Every N minutes (interval mode)",
                "kind": "number",
                "min": 1,
                "max": 10080,  # one week
            },
            {
                "name": "daily_time",
                "label": "Time of day in HH:MM (daily mode, server timezone)",
                "kind": "text",
                "placeholder": "09:00",
            },
        ],
    },
    {
        "kind": "webhook",
        "label": "When an external service POSTs to our webhook URL",
        "config_fields": [
            {
                "name": "signature_scheme",
                "label": "Signature verification (optional — confirms the request really came from the source service)",
                "kind": "select",
                "options": [
                    {"value": "", "label": "None — accept any request that has the token"},
                    {"value": "hmac_sha256", "label": "HMAC-SHA256 (generic)"},
                    {"value": "stripe", "label": "Stripe-style (Stripe-Signature header)"},
                    {"value": "github", "label": "GitHub-style (X-Hub-Signature-256 header)"},
                ],
            },
            {
                "name": "signature_secret",
                "label": "Shared secret (paste from the source service — leave blank if verification is None)",
                "kind": "password",
                "placeholder": "whsec_…",
            },
            {
                "name": "signature_header",
                "label": "Header name to read (defaults: X-Signature for HMAC, Stripe-Signature for Stripe, X-Hub-Signature-256 for GitHub)",
                "kind": "text",
                "placeholder": "X-Signature",
            },
            {
                "name": "replay_protection_enabled",
                "label": "Reject replays older than the window below (Stripe scheme only — uses its built-in t= timestamp)",
                "kind": "checkbox",
            },
            {
                "name": "replay_max_age_seconds",
                "label": "Replay window in seconds (Stripe scheme)",
                "kind": "number",
                "min": 1,
                "max": 86400,
                "placeholder": "300",
            },
        ],
    },
    {
        "kind": "manual",
        "label": "Manual only (run from the editor)",
        "config_fields": [],
    },
]


# Operator catalogue shared by the `condition` action and the per-step
# `when` filter UI. Single source of truth: the dashboard reads this via
# /metadata, the action below references it directly for its operator
# select, and `_evaluate_condition` derives its valid-operator set from
# it — so adding/renaming an operator is a one-line change.
CONDITION_OPERATORS = [
    {"value": "eq", "label": "equals"},
    {"value": "neq", "label": "does not equal"},
    {"value": "contains", "label": "contains"},
    {"value": "not_contains", "label": "does not contain"},
    {"value": "starts_with", "label": "starts with"},
    {"value": "ends_with", "label": "ends with"},
    {"value": "blank", "label": "is blank"},
    {"value": "not_blank", "label": "is not blank"},
    {"value": "gt", "label": "is greater than (number)"},
    {"value": "gte", "label": "is at least (number)"},
    {"value": "lt", "label": "is less than (number)"},
    {"value": "lte", "label": "is at most (number)"},
]
_OPERATOR_LABELS = {o["value"]: o["label"] for o in CONDITION_OPERATORS}
_VALID_OPERATORS = set(_OPERATOR_LABELS.keys())


ACTION_TYPES = [
    {
        "kind": "send_email",
        "label": "Send an email",
        "config_fields": [
            {"name": "to", "label": "Recipient email", "kind": "text", "required": True},
            {"name": "subject", "label": "Subject", "kind": "text", "required": True},
            {"name": "body", "label": "Body (HTML)", "kind": "textarea", "required": True},
            {"name": "reply_to", "label": "Reply-to (optional)", "kind": "text"},
        ],
        "outputs": ["ok", "message_id", "error"],
    },
    {
        "kind": "send_sms",
        "label": "Send an SMS",
        "config_fields": [
            {"name": "to", "label": "Recipient phone (E.164 like +14155551234)", "kind": "text", "required": True},
            {"name": "body", "label": "Message body", "kind": "textarea", "required": True},
        ],
        "outputs": ["ok", "message_sid", "error"],
    },
    {
        "kind": "ai_draft",
        "label": "Draft text with AI",
        "config_fields": [
            {"name": "prompt", "label": "Prompt (use merge tags to inject earlier data)", "kind": "textarea", "required": True},
            {"name": "model", "label": "Model", "kind": "text", "placeholder": "gpt-4o-mini"},
            {"name": "max_tokens", "label": "Max tokens", "kind": "number", "min": 1, "max": 4000},
            {"name": "output_key", "label": "Save output under key", "kind": "text", "placeholder": "summary"},
        ],
        "outputs": ["text", "<output_key>"],
    },
    {
        "kind": "http_request",
        "label": "Call an external URL",
        "config_fields": [
            {"name": "url", "label": "URL", "kind": "text", "required": True},
            {"name": "method", "label": "Method", "kind": "select", "options": [
                {"value": "POST", "label": "POST"},
                {"value": "GET", "label": "GET"},
                {"value": "PUT", "label": "PUT"},
                {"value": "PATCH", "label": "PATCH"},
                {"value": "DELETE", "label": "DELETE"},
            ]},
            {"name": "headers_json", "label": "Headers (JSON object)", "kind": "textarea", "placeholder": '{"Content-Type":"application/json"}'},
            {"name": "body", "label": "Body (string or JSON)", "kind": "textarea"},
        ],
        "outputs": ["status", "body", "json"],
    },
    {
        "kind": "save_to_table",
        "label": "Save a row to a database table",
        "config_fields": [
            {"name": "table", "label": "Table", "kind": "table_picker", "required": True},
            {"name": "values_json", "label": "Column values (JSON object: column -> value with merge tags)", "kind": "textarea", "required": True,
             "placeholder": '{"name":"{{trigger.fields.name}}","email":"{{trigger.fields.email}}"}'},
        ],
        "outputs": ["id", "table"],
    },
    {
        "kind": "delay",
        "label": "Wait for a number of seconds",
        "config_fields": [
            {"name": "seconds", "label": "Seconds to wait", "kind": "number", "required": True, "min": 1, "max": DELAY_STEP_MAX_SECONDS},
        ],
        "outputs": ["slept"],
    },
    {
        "kind": "condition",
        "label": "Branch — only continue if a condition is true",
        # The dashboard renders its own AND/OR rule-builder for this
        # action when it sees `config_ui: rule_builder`, so no plain
        # config_fields are needed. The saved config is either a single
        # leaf {field, operator, value} or a {combinator, rules} group
        # with arbitrarily nested AND/OR sub-groups.
        "config_ui": "rule_builder",
        "config_fields": [],
        "outputs": ["passed", "summary"],
    },
    {
        # Generic action that calls ANY enabled chat skill — built-ins,
        # custom webhooks, custom SQL, knowledge, AND every MCP tool —
        # without needing a hard-coded action kind per skill. The list
        # of available skills is exposed via the metadata endpoint so
        # the frontend can render a category-grouped picker; new MCP
        # tools / custom skills become selectable the moment they're
        # enabled in `agent_skills`. The dashboard renders this action
        # with its own picker UI when it sees `config_ui: skill_picker`.
        "kind": "call_skill",
        "label": "Use a skill / tool",
        "config_ui": "skill_picker",
        "config_fields": [
            {"name": "skill_name", "label": "Skill", "kind": "text", "required": True,
             "placeholder": "lookup_gallery_cards"},
            {"name": "args_json", "label": "Arguments (JSON object, merge tags allowed)",
             "kind": "textarea",
             "placeholder": '{"slug":"{{trigger.fields.slug}}"}'},
            {"name": "output_key", "label": "Save result under key", "kind": "text",
             "placeholder": "skill_result"},
        ],
        "outputs": ["result", "<output_key>"],
    },
]


# =============================================================================
# MERGE-TAG RENDERER — recursive over dicts/lists
# =============================================================================

_MERGE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_\.]+)\s*\}\}")


def _lookup(ctx: Dict[str, Any], key: str) -> Any:
    parts = key.split(".")
    cursor: Any = ctx
    for p in parts:
        if isinstance(cursor, dict) and p in cursor:
            cursor = cursor[p]
        elif isinstance(cursor, list):
            try:
                cursor = cursor[int(p)]
            except (ValueError, IndexError):
                return ""
        else:
            return ""
    return cursor


def _render_str(text: str, ctx: Dict[str, Any]) -> str:
    if not text:
        return ""

    def _sub(m: re.Match) -> str:
        v = _lookup(ctx, m.group(1))
        if v is None:
            return ""
        if isinstance(v, (dict, list)):
            try:
                return json.dumps(v, default=str)
            except Exception:
                return str(v)
        return str(v)

    return _MERGE_RE.sub(_sub, text)


def render_deep(value: Any, ctx: Dict[str, Any]) -> Any:
    """Render merge tags through nested dicts and lists."""
    if isinstance(value, str):
        return _render_str(value, ctx)
    if isinstance(value, dict):
        return {k: render_deep(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [render_deep(v, ctx) for v in value]
    return value


# =============================================================================
# WEBHOOK TOKEN
# =============================================================================

def generate_webhook_token() -> str:
    """URL-safe random slug for /automations/hook/<token>."""
    return secrets.token_urlsafe(24)


# =============================================================================
# WEBHOOK SIGNATURE VERIFICATION
# =============================================================================
# Token-only auth means a leaked URL gives an attacker full impersonation.
# When admins connect a third party that signs its outbound webhooks
# (Stripe, GitHub, Typeform, generic HMAC) we re-compute the expected
# signature over the raw body and reject mismatches before queueing a run.
# Empty / unset scheme keeps the legacy "token is enough" behaviour so
# casual integrations don't break.

_SUPPORTED_SIGNATURE_SCHEMES = {"", "hmac_sha256", "stripe", "github"}


def _ci_header(headers: Dict[str, str], name: str) -> str:
    """Case-insensitive header lookup. `headers` is expected to already
    be lowercased by the caller, but we tolerate either."""
    if not name:
        return ""
    if name in headers:
        return headers[name] or ""
    return headers.get(name.lower(), "") or ""


def verify_webhook_signature(
    cfg: Dict[str, Any],
    raw_body: bytes,
    headers: Dict[str, str],
    *,
    now_ts: Optional[int] = None,
) -> Tuple[bool, str]:
    """Validate an incoming webhook against the per-automation signature
    config. Returns ``(ok, reason)``.

    ``ok=True`` is returned when the scheme is empty / "none" — that's the
    "no verification, token is enough" path. When a scheme is set but the
    secret is missing we fail closed: the admin clearly intended to
    require verification, so accepting unsigned requests would be worse
    than a 401.

    ``raw_body`` MUST be the exact bytes that came over the wire — the
    signature is computed over those bytes, so any JSON re-encoding would
    break the comparison.
    """
    scheme = (cfg.get("signature_scheme") or "").strip().lower()
    if scheme in ("", "none"):
        return True, ""
    if scheme not in _SUPPORTED_SIGNATURE_SCHEMES:
        return False, f"Unknown signature scheme {scheme!r}."
    secret = (cfg.get("signature_secret") or "").strip()
    if not secret:
        return False, "Signature scheme is set but no shared secret is configured."

    # Normalise to a lowercased dict once so the helper lookups are cheap.
    norm_headers = {k.lower(): v for k, v in (headers or {}).items()}

    if scheme == "hmac_sha256":
        header_name = (cfg.get("signature_header") or "X-Signature").strip() or "X-Signature"
        sent = _ci_header(norm_headers, header_name).strip()
        if not sent:
            return False, f"Missing signature header {header_name!r}."
        # Tolerate the common "sha256=<hex>" prefix some senders use.
        if sent.lower().startswith("sha256="):
            sent = sent.split("=", 1)[1]
        expected = hmac.new(
            secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sent.lower(), expected.lower()):
            return False, "Signature does not match expected HMAC-SHA256."
        return True, ""

    if scheme == "github":
        header_name = (cfg.get("signature_header") or "X-Hub-Signature-256").strip() or "X-Hub-Signature-256"
        sent = _ci_header(norm_headers, header_name).strip()
        if not sent:
            return False, f"Missing signature header {header_name!r}."
        if not sent.lower().startswith("sha256="):
            return False, "GitHub signature header must start with 'sha256='."
        sent_hex = sent.split("=", 1)[1]
        expected = hmac.new(
            secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sent_hex.lower(), expected.lower()):
            return False, "Signature does not match expected GitHub HMAC."
        return True, ""

    if scheme == "stripe":
        header_name = (cfg.get("signature_header") or "Stripe-Signature").strip() or "Stripe-Signature"
        sent = _ci_header(norm_headers, header_name).strip()
        if not sent:
            return False, f"Missing signature header {header_name!r}."
        # Stripe format: "t=1492774577,v1=abc...,v1=def..." — multiple v1
        # entries can appear during secret rotation, so collect all of them.
        parts: Dict[str, List[str]] = {}
        for piece in sent.split(","):
            piece = piece.strip()
            if "=" not in piece:
                continue
            k, v = piece.split("=", 1)
            parts.setdefault(k.strip(), []).append(v.strip())
        ts_values = parts.get("t") or []
        v1_values = parts.get("v1") or []
        if not ts_values or not v1_values:
            return False, "Stripe signature header missing 't=' timestamp or 'v1=' entry."
        ts = ts_values[0]
        try:
            ts_int = int(ts)
        except ValueError:
            return False, "Stripe signature timestamp is not an integer."
        signed_payload = ts.encode("ascii") + b"." + raw_body
        expected = hmac.new(
            secret.encode("utf-8"), signed_payload, hashlib.sha256
        ).hexdigest()
        match = any(
            hmac.compare_digest(v.lower(), expected.lower()) for v in v1_values
        )
        if not match:
            return False, "Signature does not match expected Stripe v1 HMAC."
        # Optional replay protection — only meaningful for schemes that
        # carry a timestamp, so we gate it here.
        if cfg.get("replay_protection_enabled"):
            try:
                max_age = int(cfg.get("replay_max_age_seconds") or 300)
            except (TypeError, ValueError):
                max_age = 300
            max_age = max(1, max_age)
            current = int(now_ts) if now_ts is not None else int(time.time())
            if current - ts_int > max_age:
                return False, "Webhook timestamp is older than the allowed replay window."
        return True, ""

    return False, f"Unknown signature scheme {scheme!r}."


# =============================================================================
# ACTION IMPLEMENTATIONS
# =============================================================================

def _action_send_email(cfg: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    messaging = _DB.get("messaging")
    if messaging is None:
        return {"ok": False, "error": "Messaging module not configured."}
    to = (cfg.get("to") or "").strip()
    subject = cfg.get("subject") or ""
    body = cfg.get("body") or ""
    if not to or "@" not in to:
        return {"ok": False, "error": f"Invalid recipient email: {to!r}"}
    try:
        result = messaging.send_email(
            to_email=to,
            subject=subject,
            html_body=body,
            reply_to=cfg.get("reply_to") or None,
        )
        return {
            "ok": True,
            "message_id": result.get("id") or result.get("message_id") or "",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}


def _action_send_sms(cfg: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    messaging = _DB.get("messaging")
    if messaging is None:
        return {"ok": False, "error": "Messaging module not configured."}
    to = (cfg.get("to") or "").strip()
    body = cfg.get("body") or ""
    if not to:
        return {"ok": False, "error": "Recipient phone is empty."}
    # Cap enforcement — keep automations from quietly racking up SMS
    # spend after the tenant has crossed their monthly limit. If the
    # hook isn't wired (older callers) we fall through and send.
    cap_blocks = _DB.get("cost_cap_blocks_send")
    if callable(cap_blocks):
        try:
            if cap_blocks("automation_sms"):
                return {"ok": False, "error": "cap_reached"}
        except Exception as e:
            print(f"[automation_sms cap check] {e}")
    try:
        result = messaging.send_sms(to_phone=to, body=body)
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}
    # Ledger the send. Twilio's reported num_segments is the source of
    # truth; when missing we record segments=NULL so the dashboard's
    # "uncosted_calls" tile surfaces the gap rather than guessing.
    rec = _DB.get("record_sms_cost")
    if callable(rec):
        raw_segs = (result or {}).get("num_segments")
        segs = None
        if raw_segs is not None:
            try:
                segs = int(raw_segs)
            except (TypeError, ValueError):
                segs = None
        try:
            rec(
                surface="automation_sms",
                to_number=to,
                message_sid=(result or {}).get("sid") or "",
                segments=segs,
            )
        except Exception as e:
            print(f"[automation_sms cost log] {e}")
    return {
        "ok": True,
        "message_sid": (result or {}).get("sid") or "",
    }


def _action_ai_draft(cfg: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    client = _DB.get("openai_client")
    if client is None:
        return {"ok": False, "error": "OpenAI client not configured."}
    prompt = (cfg.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error": "Prompt is empty."}
    model = (cfg.get("model") or "").strip() or "gpt-4o-mini"
    try:
        max_tokens = int(cfg.get("max_tokens") or 500)
    except (TypeError, ValueError):
        max_tokens = 500
    max_tokens = max(1, min(max_tokens, 4000))
    output_key = (cfg.get("output_key") or "").strip()

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            timeout=AI_STEP_TIMEOUT_SECONDS,
        )
        text = (resp.choices[0].message.content or "").strip() if resp.choices else ""
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}

    out: Dict[str, Any] = {"ok": True, "text": text}
    if output_key and output_key not in out:
        out[output_key] = text
    return out


def _action_http_request(cfg: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    url = (cfg.get("url") or "").strip()
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return {"ok": False, "error": "URL must start with http:// or https://"}
    method = (cfg.get("method") or "POST").upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        return {"ok": False, "error": f"Invalid method: {method}"}

    headers: Dict[str, str] = {}
    headers_json = cfg.get("headers_json") or cfg.get("headers")
    if headers_json:
        if isinstance(headers_json, dict):
            headers = {str(k): str(v) for k, v in headers_json.items()}
        else:
            try:
                parsed = json.loads(headers_json)
                if isinstance(parsed, dict):
                    headers = {str(k): str(v) for k, v in parsed.items()}
            except (TypeError, ValueError):
                return {"ok": False, "error": "Headers must be a JSON object."}

    body = cfg.get("body")
    json_body = None
    text_body = None
    if isinstance(body, (dict, list)):
        json_body = body
        headers.setdefault("Content-Type", "application/json")
    elif isinstance(body, str) and body.strip():
        # Try to parse as JSON if it looks like JSON, else send as text.
        s = body.strip()
        if s.startswith("{") or s.startswith("["):
            try:
                json_body = json.loads(s)
                headers.setdefault("Content-Type", "application/json")
            except ValueError:
                text_body = body
        else:
            text_body = body

    try:
        with httpx.Client(timeout=HTTP_STEP_TIMEOUT_SECONDS) as client:
            resp = client.request(
                method,
                url,
                headers=headers or None,
                json=json_body if json_body is not None else None,
                content=text_body if text_body is not None else None,
            )
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"HTTP error: {e}"}

    out: Dict[str, Any] = {
        "ok": resp.status_code < 400,
        "status": resp.status_code,
        "body": resp.text[:5000],
    }
    if not out["ok"]:
        out["error"] = f"HTTP {resp.status_code}"
    try:
        out["json"] = resp.json()
    except ValueError:
        pass
    return out


def _action_save_to_table(cfg: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    schema_fn = _DB.get("schema_introspect_fn")
    qident = _DB.get("qident_fn")
    if schema_fn is None or qident is None:
        return {"ok": False, "error": "Schema introspection not configured."}
    table = (cfg.get("table") or "").strip()
    if not table:
        return {"ok": False, "error": "Pick a table."}
    schema = schema_fn() or {}
    if table not in schema:
        return {"ok": False, "error": f"Table '{table}' is not available (blocklisted or doesn't exist)."}
    cols_by_name = {c["name"]: c["kind"] for c in schema[table]}

    values = cfg.get("values_json") or cfg.get("values") or {}
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except ValueError:
            return {"ok": False, "error": "Values must be a JSON object."}
    if not isinstance(values, dict) or not values:
        return {"ok": False, "error": "Provide at least one column value."}

    insert_cols: List[str] = []
    insert_vals: List[Any] = []
    for col, raw in values.items():
        if col not in cols_by_name:
            return {"ok": False, "error": f"Unknown column: {col}"}
        # JSON-shaped columns get JSON-encoded; everything else passes through.
        if cols_by_name[col] == "json" and not isinstance(raw, str):
            raw = json.dumps(raw, default=str)
        insert_cols.append(col)
        insert_vals.append(raw)

    col_sql = ", ".join(qident(c) for c in insert_cols)
    placeholders = ", ".join(["%s"] * len(insert_cols))
    sql = f"INSERT INTO {qident(table)} ({col_sql}) VALUES ({placeholders}) RETURNING id"
    try:
        result = _execute_db(sql, tuple(insert_vals))
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}
    return {"ok": True, "id": result.get("id") if result else None, "table": table}


# --- CONDITIONALS ----------------------------------------------------------
# Used both by the standalone `condition` action (which gates the rest of
# the run) and the per-step `when` filter (which gates a single step). The
# evaluator is intentionally string-shaped so merge tags drop in cleanly:
# anything coercible to a number is compared numerically for >/</>=, and
# everything else is compared as strings.

def _coerce_number(s: Any) -> Optional[float]:
    if isinstance(s, bool):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _evaluate_condition(left: Any, op: str, right: Any) -> bool:
    """Single leaf comparison. Used as the bottom of the rule-tree walker."""
    L = "" if left is None else str(left)
    R = "" if right is None else str(right)
    op = (op or "eq").strip().lower()
    if op == "blank":
        return L.strip() == ""
    if op == "not_blank":
        return L.strip() != ""
    if op == "eq":
        return L == R
    if op == "neq":
        return L != R
    if op == "contains":
        return R in L
    if op == "not_contains":
        return R not in L
    if op == "starts_with":
        return L.startswith(R)
    if op == "ends_with":
        return L.endswith(R)
    if op in ("gt", "gte", "lt", "lte"):
        ln, rn = _coerce_number(L), _coerce_number(R)
        if ln is None or rn is None:
            return False
        if op == "gt":
            return ln > rn
        if op == "gte":
            return ln >= rn
        if op == "lt":
            return ln < rn
        return ln <= rn
    return False


# -----------------------------------------------------------------------------
# RULE TREES — AND/OR groups of leaf comparisons
# -----------------------------------------------------------------------------
#
# A "rule node" is either a leaf or a group:
#
#   leaf:   {"field": "...", "operator": "eq", "value": "..."}
#   group:  {"combinator": "AND" | "OR", "rules": [<node>, ...]}
#
# Both the standalone `condition` action and the per-step `when` filter
# accept either shape. Legacy data (saved before AND/OR groups existed)
# is always a single leaf and continues to work unchanged — the walker
# treats a leaf as a one-rule group internally.

def _is_rule_group(node: Any) -> bool:
    """A node is a group if it carries a `rules` list."""
    return isinstance(node, dict) and isinstance(node.get("rules"), list)


def _has_meaningful_rules(node: Any) -> bool:
    """True if any leaf in the tree has a non-empty field, or uses a unary
    operator (blank / not_blank) which doesn't need a left-hand value."""
    if not isinstance(node, dict):
        return False
    if _is_rule_group(node):
        return any(_has_meaningful_rules(r) for r in node.get("rules") or [])
    field = node.get("field")
    op = (node.get("operator") or "").strip().lower()
    return bool(
        (isinstance(field, str) and field.strip())
        or op in ("blank", "not_blank")
    )


def _validate_rule_operators(node: Any) -> Optional[str]:
    """Walk the tree; return the first unknown-operator error, else None."""
    if not isinstance(node, dict):
        return None
    if _is_rule_group(node):
        combinator = (node.get("combinator") or "AND").strip().upper()
        if combinator not in ("AND", "OR"):
            return f"Unknown combinator: {node.get('combinator')!r}"
        for r in node.get("rules") or []:
            err = _validate_rule_operators(r)
            if err:
                return err
        return None
    op = (node.get("operator") or "eq").strip().lower()
    if op not in _VALID_OPERATORS:
        return f"Unknown operator: {op!r}"
    return None


def _describe_rule_leaf(cfg: Dict[str, Any]) -> str:
    field = cfg.get("field")
    op = (cfg.get("operator") or "eq").strip().lower()
    value = cfg.get("value")
    op_label = _OPERATOR_LABELS.get(op, op)
    field_str = "" if field is None else str(field)
    if op in ("blank", "not_blank"):
        return f"{field_str!r} {op_label}"
    value_str = "" if value is None else str(value)
    return f"{field_str!r} {op_label} {value_str!r}"


def _describe_rule_node(node: Any) -> str:
    """Human-readable rendering used in run-log skip reasons. Renders
    groups like `(A AND B)` so admins can see exactly which sub-rule
    short-circuited the branch."""
    if not isinstance(node, dict):
        return "(empty rule)"
    if _is_rule_group(node):
        combinator = (node.get("combinator") or "AND").strip().upper()
        if combinator not in ("AND", "OR"):
            combinator = "AND"
        rules = node.get("rules") or []
        if not rules:
            return "(empty group)"
        parts = [_describe_rule_node(r) for r in rules]
        if len(parts) == 1:
            return parts[0]
        return "(" + f" {combinator} ".join(parts) + ")"
    return _describe_rule_leaf(node)


def _evaluate_rule_node(node: Any) -> Tuple[bool, str]:
    """Evaluate a rule tree. Returns (passed, summary).

    `summary` always describes the sub-rule(s) that determined the
    outcome — the first false rule under AND, the first true rule under
    OR, or the whole group otherwise — so run-log skip reasons point
    admins straight at the failing branch.

    Short-circuits: AND stops on the first false, OR stops on the first
    true. An empty group (no leaves at all) evaluates to True so a
    half-built filter doesn't accidentally block every run."""
    if not isinstance(node, dict):
        return True, "(no condition)"
    if _is_rule_group(node):
        combinator = (node.get("combinator") or "AND").strip().upper()
        if combinator not in ("AND", "OR"):
            combinator = "AND"
        rules = node.get("rules") or []
        if not rules:
            return True, "(empty group)"
        if combinator == "AND":
            for r in rules:
                ok, summary = _evaluate_rule_node(r)
                if not ok:
                    # Surface the first failing sub-rule so the skip
                    # reason names the actual culprit, not the whole tree.
                    return False, summary
            return True, _describe_rule_node(node)
        # OR
        for r in rules:
            ok, summary = _evaluate_rule_node(r)
            if ok:
                return True, summary
        # Every branch failed — describe the whole OR group so admins
        # see all the alternatives that came up false.
        return False, _describe_rule_node(node)
    # leaf
    op = (node.get("operator") or "eq").strip().lower()
    if op not in _VALID_OPERATORS:
        op = "eq"
    passed = _evaluate_condition(node.get("field"), op, node.get("value"))
    return passed, _describe_rule_leaf(node)


def _describe_condition(cfg: Dict[str, Any]) -> str:
    """Backwards-compatible alias used by older call sites.
    Accepts either a legacy leaf `{field, operator, value}` or a group
    `{combinator, rules}`."""
    return _describe_rule_node(cfg)


def _action_condition(cfg: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate the condition. Always succeeds; the run engine inspects
    `passed` afterward to decide whether to skip the rest of the run.

    Accepts either a legacy single-rule cfg `{field, operator, value}`
    or a rule-group cfg `{combinator, rules: [...]}` with arbitrarily
    nested AND/OR sub-groups."""
    op_err = _validate_rule_operators(cfg)
    if op_err:
        return {"ok": False, "error": op_err}
    if not _has_meaningful_rules(cfg):
        return {"ok": False, "error": "Condition has no rules to evaluate."}
    passed, summary = _evaluate_rule_node(cfg)
    return {
        "ok": True,
        "passed": passed,
        "summary": summary,
    }


def _action_delay(cfg: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    try:
        seconds = int(cfg.get("seconds") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "seconds must be a number."}
    seconds = max(0, min(seconds, DELAY_STEP_MAX_SECONDS))
    # Honor the run's overall deadline. If the requested delay would push us
    # past it, clamp to whatever time is left so the next per-step deadline
    # check trips and the run is marked `timeout` cleanly.
    deadline = ctx.get("__deadline")
    if deadline is not None:
        remaining = max(0, int(deadline - time.time()))
        if seconds > remaining:
            seconds = remaining
    if seconds:
        time.sleep(seconds)
    return {"ok": True, "slept": seconds}


def _action_call_skill(cfg: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Execute any enabled chat skill via the registered dispatcher.

    cfg keys:
        skill_name  — the `agent_skills.name` to invoke (required).
        args_json   — JSON object string (merge tags already rendered by
                      the engine before this is called); optional, defaults to {}.
        output_key  — key under which to expose the result to later steps;
                      defaults to "skill_result".

    Returns:
        On success:  {ok: True, result: <skill payload>, <output_key>: <skill payload>}
        On failure:  {ok: False, error: "..."}
    """
    if _SKILL_EXECUTOR is None:
        return {"ok": False, "error": (
            "Skill dispatcher is not wired up. The host app must call "
            "automations.set_skill_executor(...) at startup."
        )}
    skill_name = (cfg.get("skill_name") or "").strip()
    if not skill_name:
        return {"ok": False, "error": "skill_name is required."}
    raw_args = cfg.get("args_json")
    if raw_args is None or raw_args == "":
        args_dict: Dict[str, Any] = {}
    elif isinstance(raw_args, dict):
        args_dict = raw_args
    else:
        try:
            parsed = json.loads(str(raw_args))
        except (TypeError, ValueError) as e:
            return {"ok": False, "error": f"args_json is not valid JSON: {e}"}
        if not isinstance(parsed, dict):
            return {"ok": False, "error": "args_json must be a JSON object."}
        args_dict = parsed
    try:
        outcome = _SKILL_EXECUTOR(skill_name, args_dict)
    except Exception as e:  # noqa: BLE001 — surface any executor crash
        return {"ok": False, "error": f"Skill {skill_name!r} crashed: {e}"}
    if not isinstance(outcome, dict):
        return {"ok": False, "error": (
            f"Skill executor returned {type(outcome).__name__}, expected dict."
        )}
    if not outcome.get("ok", True):
        # Surface the dispatcher's own error string if it gave one.
        return {"ok": False, "error": outcome.get("error") or "Skill failed."}
    payload = outcome.get("result")
    output_key = (cfg.get("output_key") or "skill_result").strip() or "skill_result"
    return {"ok": True, "result": payload, output_key: payload}


_ACTION_DISPATCH: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = {
    "send_email": _action_send_email,
    "send_sms": _action_send_sms,
    "ai_draft": _action_ai_draft,
    "http_request": _action_http_request,
    "save_to_table": _action_save_to_table,
    "delay": _action_delay,
    "condition": _action_condition,
    "call_skill": _action_call_skill,
}


# =============================================================================
# RATE LIMIT — runs in the last hour for a given automation
# =============================================================================

def _rate_limit_exceeded(automation_id: int) -> bool:
    """Read-only check used by callers that just want a "would this be
    blocked?" signal. The real rate-limit gate is `_atomic_queue_insert`
    below, which holds an advisory lock so concurrent inserts can't race."""
    row = _query_db(
        """
        SELECT COUNT(*) AS n FROM automation_runs
         WHERE automation_id = %s
           AND queued_at > NOW() - INTERVAL '1 hour'
           AND is_dry_run = FALSE
        """,
        (automation_id,),
        fetchone=True,
    ) or {"n": 0}
    return int(row.get("n") or 0) >= MAX_RUNS_PER_HOUR_PER_AUTOMATION


# Arbitrary namespace ID for pg_advisory_xact_lock so we don't collide with
# any other advisory lock in the app (none today, but future-proof).
_RATE_LIMIT_LOCK_NAMESPACE = 91234


def _atomic_queue_insert(
    automation_id: int,
    triggered_by: str,
    trigger_data: Dict[str, Any],
    is_dry_run: bool,
) -> Optional[int]:
    """Insert a queued run row, gated by an atomic per-automation rate-limit
    check. Returns the new run id, or None if the limit was exceeded.

    We hold a transactional advisory lock keyed by automation_id, do the
    COUNT, then INSERT, then commit. Two concurrent calls for the same
    automation are serialized by the lock, so we can't go over the cap.
    Calls for *different* automations don't block each other."""
    import psycopg2  # local import — avoids polluting module-level deps
    import psycopg2.extras

    db_url = _DB.get("database_url")
    if not db_url:
        # Fall back to the non-atomic path if configure() wasn't given a
        # URL. Not great, but better than failing to queue at all.
        if not is_dry_run and _rate_limit_exceeded(automation_id):
            return None
        row = _execute_db(
            """
            INSERT INTO automation_runs
                (automation_id, status, triggered_by, trigger_data, is_dry_run)
            VALUES (%s, 'queued', %s, %s::jsonb, %s)
            RETURNING id
            """,
            (automation_id, triggered_by,
             json.dumps(trigger_data or {}, default=str), bool(is_dry_run)),
        )
        return row["id"] if row else None

    conn = psycopg2.connect(db_url)
    try:
        conn.autocommit = False
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Per-automation transactional lock — released on commit/rollback.
            cur.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)",
                (_RATE_LIMIT_LOCK_NAMESPACE, int(automation_id)),
            )
            if not is_dry_run:
                cur.execute(
                    """
                    SELECT COUNT(*) AS n FROM automation_runs
                     WHERE automation_id = %s
                       AND queued_at > NOW() - INTERVAL '1 hour'
                       AND is_dry_run = FALSE
                    """,
                    (automation_id,),
                )
                count_row = cur.fetchone() or {"n": 0}
                if int(count_row["n"] or 0) >= MAX_RUNS_PER_HOUR_PER_AUTOMATION:
                    conn.rollback()
                    return None
            cur.execute(
                """
                INSERT INTO automation_runs
                    (automation_id, status, triggered_by, trigger_data, is_dry_run)
                VALUES (%s, 'queued', %s, %s::jsonb, %s)
                RETURNING id
                """,
                (automation_id, triggered_by,
                 json.dumps(trigger_data or {}, default=str), bool(is_dry_run)),
            )
            row = cur.fetchone()
        conn.commit()
        return int(row["id"]) if row else None
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


# =============================================================================
# RUN EXECUTOR
# =============================================================================

def _claim_run(run_id: int) -> Optional[Dict[str, Any]]:
    """Atomically transition queued -> running. Returns the run row on
    success, or None if the run was already claimed / cancelled."""
    return _execute_db(
        """
        UPDATE automation_runs
           SET status='running', started_at=NOW()
         WHERE id=%s AND status='queued'
        RETURNING *
        """,
        (run_id,),
    )


def _finish_run(run_id: int, status: str, step_results: List[Dict[str, Any]],
                error_text: str = "") -> None:
    _execute_db(
        """
        UPDATE automation_runs
           SET status=%s, finished_at=NOW(),
               step_results=%s::jsonb,
               error_text=%s
         WHERE id=%s
        """,
        (status, json.dumps(step_results, default=str), error_text[:1000], run_id),
    )
    # Mirror onto the parent automation for the list view.
    run = _query_db(
        "SELECT automation_id, is_dry_run FROM automation_runs WHERE id=%s",
        (run_id,), fetchone=True,
    )
    if run and not run.get("is_dry_run"):
        _execute_db(
            "UPDATE automations SET last_run_at=NOW(), last_run_status=%s, updated_at=NOW() WHERE id=%s",
            (status, run["automation_id"]),
        )


def _execute_run(run_id: int) -> None:
    """Run an already-claimed run. Wrapped by callers that hold the
    concurrency slot."""
    run = _query_db(
        "SELECT * FROM automation_runs WHERE id=%s",
        (run_id,), fetchone=True,
    )
    if not run:
        return
    automation = _query_db(
        "SELECT * FROM automations WHERE id=%s",
        (run["automation_id"],), fetchone=True,
    )
    if not automation:
        _finish_run(run_id, "failed", [], "Automation deleted before run started.")
        return
    # Honor "disabled while queued" — don't run actions for an automation
    # that the admin turned off after the run was queued. Test runs and
    # dry-runs are explicit user actions, so they bypass this check.
    if (not automation.get("enabled")
            and not run.get("is_dry_run")
            and (run.get("triggered_by") or "") not in ("admin_test", "manual")):
        _finish_run(run_id, "failed", [],
                    "Automation was disabled before this run started.")
        return

    steps = automation.get("action_steps") or []
    if not isinstance(steps, list):
        steps = []
    trigger_data = run.get("trigger_data") or {}
    if not isinstance(trigger_data, dict):
        trigger_data = {}

    deadline = time.time() + MAX_RUN_SECONDS
    # `__deadline` is read by actions like `delay` so they can clamp their
    # blocking time and surface as a `timeout` instead of overshooting.
    ctx: Dict[str, Any] = {"trigger": trigger_data, "__deadline": deadline}
    step_results: List[Dict[str, Any]] = []
    final_status = "succeeded"
    error_text = ""

    for idx, step in enumerate(steps, start=1):
        if time.time() > deadline:
            step_results.append({
                "step": idx,
                "kind": (step.get("kind") if isinstance(step, dict) else ""),
                "name": (step.get("name") if isinstance(step, dict) else ""),
                "skipped": True,
                "reason": "Run exceeded overall timeout.",
            })
            final_status = "timeout"
            error_text = f"Run exceeded {MAX_RUN_SECONDS}s before step {idx}."
            break

        if not isinstance(step, dict):
            step_results.append({"step": idx, "error": "Invalid step shape."})
            final_status = "failed"
            error_text = f"Step {idx} is not an object."
            break

        kind = step.get("kind") or ""

        # Per-step "Only run when…" filter. If present and false, skip
        # this single step and move on. The filter mirrors a condition
        # action's config (a leaf rule or a {combinator, rules} group)
        # and runs through the same merge-tag rendering + tree
        # evaluator so behavior is identical to a standalone condition
        # step.
        when = step.get("when")
        if isinstance(when, dict) and _has_meaningful_rules(when):
            rendered_when = render_deep(when, ctx)
            passed, summary = _evaluate_rule_node(rendered_when)
            if not passed:
                step_results.append({
                    "step": idx,
                    "kind": kind,
                    "name": step.get("name") or "",
                    "skipped": True,
                    "ok": True,
                    "reason": "Only-run-when condition was false: " + summary,
                })
                continue

        impl = _ACTION_DISPATCH.get(kind)
        if not impl:
            step_results.append({
                "step": idx, "kind": kind,
                "name": step.get("name") or "",
                "error": f"Unknown action kind: {kind!r}",
            })
            final_status = "failed"
            error_text = f"Step {idx} uses unknown action kind {kind!r}."
            break

        rendered_cfg = render_deep(step.get("config") or {}, ctx)
        started = time.time()
        try:
            output = impl(rendered_cfg, ctx)
        except Exception as e:
            output = {"ok": False, "error": f"{e}\n{traceback.format_exc()[:1000]}"}
        elapsed_ms = int((time.time() - started) * 1000)

        result_row = {
            "step": idx,
            "kind": kind,
            "name": step.get("name") or "",
            "config": rendered_cfg,
            "output": output,
            "elapsed_ms": elapsed_ms,
            "ok": bool(output.get("ok", False)),
        }
        step_results.append(result_row)
        # Expose this step's output under stepN AND stepN_<name> for easier
        # merge-tag references downstream.
        ctx[f"step{idx}"] = output
        nm = (step.get("name") or "").strip()
        if nm:
            slug = re.sub(r"[^a-zA-Z0-9_]+", "_", nm).strip("_").lower()
            if slug and slug not in ctx:
                ctx[slug] = output

        if not output.get("ok", False):
            final_status = "failed"
            error_text = f"Step {idx} ({kind}) failed: {output.get('error') or 'unknown error'}"
            break

        # Standalone "condition" step: if it evaluated false, mark all
        # remaining steps as skipped (with a reason that points back to
        # this gate) and finish the run successfully.
        if kind == "condition" and not output.get("passed", True):
            summary = output.get("summary") or "(condition was false)"
            for j_off, j_step in enumerate(steps[idx:], start=idx + 1):
                if not isinstance(j_step, dict):
                    continue
                step_results.append({
                    "step": j_off,
                    "kind": j_step.get("kind") or "",
                    "name": j_step.get("name") or "",
                    "skipped": True,
                    "ok": True,
                    "reason": f"Skipped because the branch at step {idx} was false ({summary}).",
                })
            break

    _finish_run(run_id, final_status, step_results, error_text)


def _execute_run_safely(run_id: int) -> None:
    """Wrapper: ensures the slot is released even if execute_run blows up."""
    try:
        _execute_run(run_id)
    except Exception as e:
        _finish_run(run_id, "failed", [], f"Engine error: {e}\n{traceback.format_exc()[:1000]}")
    finally:
        _release_slot()


def _spawn_run_thread(run_id: int) -> None:
    t = threading.Thread(
        target=_execute_run_safely,
        args=(run_id,),
        name=f"automation-run-{run_id}",
        daemon=True,
    )
    t.start()


def _try_dispatch_now(run_id: int) -> bool:
    """If a slot is available, mark the run as running and spawn the
    worker thread. Returns True if dispatched; False if the run was left
    queued for the scheduler tick to pick up."""
    if not _try_acquire_slot():
        return False
    claimed = _claim_run(run_id)
    if not claimed:
        _release_slot()
        return False
    _spawn_run_thread(run_id)
    return True


# =============================================================================
# PUBLIC API — what the rest of the app calls
# =============================================================================

def queue_run(
    automation_id: int,
    trigger_data: Dict[str, Any],
    *,
    triggered_by: str = "event",
    is_dry_run: bool = False,
    dispatch_immediately: bool = True,
) -> Optional[int]:
    """Insert a new run row and (optionally) try to dispatch it right away.
    Returns the run id, or None if the automation is rate-limited."""
    run_id = _atomic_queue_insert(
        automation_id, triggered_by, trigger_data or {}, bool(is_dry_run),
    )
    if run_id is None:
        return None
    if dispatch_immediately:
        _try_dispatch_now(run_id)
    return run_id


def dispatch_event(event_type: str, data: Dict[str, Any]) -> List[int]:
    """Find every enabled automation whose trigger matches `event_type`
    and queue a run for each. Called from the request path (form
    submission, chat conversation start, webhook receive). Never raises."""
    try:
        rows = _query_db(
            """
            SELECT id, trigger_type, trigger_config FROM automations
             WHERE enabled = TRUE AND trigger_type = %s
            """,
            (event_type,),
        ) or []
    except Exception as e:
        print(f"[automations] dispatch_event lookup error: {e}")
        return []

    queued: List[int] = []
    for r in rows:
        try:
            cfg = r.get("trigger_config") or {}
            if not _trigger_matches(event_type, cfg, data):
                continue
            rid = queue_run(r["id"], data, triggered_by=event_type)
            if rid is not None:
                queued.append(rid)
        except Exception as e:
            print(f"[automations] queue error for automation {r.get('id')}: {e}")
    return queued


def _trigger_matches(event_type: str, cfg: Dict[str, Any], data: Dict[str, Any]) -> bool:
    """Filter applied to event-style triggers. Only `form_submitted`
    has a useful filter today (form_slug). Everything else fires for
    any event of its kind."""
    if not isinstance(cfg, dict):
        return True
    if event_type == "form_submitted":
        wanted = (cfg.get("form_slug") or "").strip().lower()
        if not wanted:
            return True
        actual = (str(data.get("form_slug") or "")).strip().lower()
        return wanted == actual
    return True


# =============================================================================
# SCHEDULER TICK — drains queued runs and fires due schedule triggers
# =============================================================================

def _scheduler_tick() -> None:
    # 1) Drain queued runs that didn't get an immediate slot.
    drained = _query_db(
        """
        SELECT id FROM automation_runs
         WHERE status = 'queued'
         ORDER BY queued_at ASC
         LIMIT 25
        """
    ) or []
    for r in drained:
        if not _try_dispatch_now(r["id"]):
            break  # at-cap; let the next tick try again

    # 2) Fire due schedule triggers.
    schedules = _query_db(
        """
        SELECT id, trigger_config, next_scheduled_at FROM automations
         WHERE enabled = TRUE AND trigger_type = 'schedule'
        """
    ) or []
    now = datetime.utcnow()
    for s in schedules:
        try:
            cfg = s.get("trigger_config") or {}
            next_at = s.get("next_scheduled_at")
            # Compute the upcoming target.
            target = _next_schedule_target(cfg, last_known=next_at, now=now)
            if target is None:
                continue
            if next_at is None:
                # First time we see this schedule — anchor `next_at` so we
                # don't immediately fire on enable (avoids "I just turned it
                # on and it ran instantly" surprise).
                _execute_db(
                    "UPDATE automations SET next_scheduled_at=%s WHERE id=%s",
                    (target, s["id"]),
                )
                continue
            if next_at <= now:
                # Fire and advance the cursor.
                queue_run(s["id"], {"scheduled_at": now.isoformat()},
                          triggered_by="schedule")
                advanced = _next_schedule_target(cfg, last_known=now, now=now)
                _execute_db(
                    "UPDATE automations SET next_scheduled_at=%s WHERE id=%s",
                    (advanced, s["id"]),
                )
        except Exception as e:
            print(f"[automations] schedule tick error for {s.get('id')}: {e}")


def _next_schedule_target(cfg: Dict[str, Any], *, last_known: Optional[datetime],
                          now: datetime) -> Optional[datetime]:
    """Compute the next time this schedule should fire (>= now)."""
    if not isinstance(cfg, dict):
        return None
    mode = (cfg.get("mode") or "").lower()
    if mode == "interval":
        try:
            minutes = max(1, int(cfg.get("interval_minutes") or 0))
        except (TypeError, ValueError):
            return None
        anchor = last_known or now
        from datetime import timedelta
        nxt = anchor
        # Advance until strictly greater than `now`.
        while nxt <= now:
            nxt = nxt + timedelta(minutes=minutes)
        return nxt
    if mode == "daily":
        raw = (cfg.get("daily_time") or "").strip()
        m = re.match(r"^([0-2]?\d):([0-5]\d)$", raw)
        if not m:
            return None
        hh, mm = int(m.group(1)), int(m.group(2))
        if hh > 23:
            return None
        from datetime import timedelta
        candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        return candidate
    return None


# =============================================================================
# RUN-HISTORY RETENTION — daily cleanup tick
# =============================================================================
# The scheduler fires every 30 seconds, but we only want to actually run the
# DELETE roughly once a day (it's a single statement, but it scans the whole
# table). We keep a module-level timestamp of the last successful pass and
# no-op early until RETENTION_TICK_INTERVAL_SECONDS has elapsed.

_last_cleanup_at: float = 0.0
_cleanup_lock = threading.Lock()


def _effective_retention() -> Dict[str, Any]:
    """Resolve the *current* retention values, preferring the singleton
    `automation_settings` row over the env-var defaults so admin saves take
    effect on the very next tick without a redeploy.

    Both columns are nullable; a NULL means "no override, fall back to the
    env var". We also clamp DB values into the same sane bounds the UI
    enforces so a hand-edited row can't make the cleanup loop misbehave.
    `db_overrides` reports which fields are coming from the DB so callers
    (the admin status panel) can show a clear "(default)" vs "(custom)"
    label."""
    days = RETENTION_DAYS
    keep = RETENTION_KEEP_RECENT
    overrides = {"retention_days": False, "keep_recent_per_automation": False}
    try:
        row = _query_db(
            "SELECT retention_days, keep_recent_per_automation "
            "FROM automation_settings WHERE id = 1",
            fetchone=True,
        )
    except Exception as e:
        # Don't let a transient DB hiccup crash the scheduler tick — fall
        # back to env-var defaults silently and log so it shows up in the
        # logs without spamming.
        print(f"[automations] could not read automation_settings: {e}")
        row = None
    if row:
        rd = row.get("retention_days") if isinstance(row, dict) else row["retention_days"]
        if rd is not None:
            try:
                days = max(1, min(RETENTION_DAYS_MAX, int(rd)))
                overrides["retention_days"] = True
            except (TypeError, ValueError):
                pass
        kr = (row.get("keep_recent_per_automation")
              if isinstance(row, dict) else row["keep_recent_per_automation"])
        if kr is not None:
            try:
                keep = max(0, min(RETENTION_KEEP_RECENT_MAX, int(kr)))
                overrides["keep_recent_per_automation"] = True
            except (TypeError, ValueError):
                pass
    return {
        "retention_days": days,
        "keep_recent_per_automation": keep,
        "db_overrides": overrides,
    }


def _cleanup_runs_tick() -> None:
    """Delete terminal `automation_runs` older than the effective retention
    horizon, but always keep the most recent N rows per automation (where
    N is the effective keep-recent value). Idempotent and safe to call
    frequently — internally rate-limited to once per
    RETENTION_TICK_INTERVAL_SECONDS. Reads its two knobs through
    `_effective_retention()` on every pass so admin edits to the
    `automation_settings` singleton take effect without a restart."""
    global _last_cleanup_at
    now = time.time()
    with _cleanup_lock:
        if now - _last_cleanup_at < RETENTION_TICK_INTERVAL_SECONDS:
            return
        _last_cleanup_at = now
    eff = _effective_retention()
    days = eff["retention_days"]
    keep = eff["keep_recent_per_automation"]
    try:
        # Two safety rules baked into the SQL:
        #
        # 1. Only *terminal* runs are eligible for deletion or counted in the
        #    keep-recent rank. The task spec says "keep the most recent N
        #    successes/failures", so 'queued' / 'running' rows are completely
        #    excluded from the cleanup — we'd never want to delete a row a
        #    worker is mid-flight on, and short-lived non-terminal states
        #    shouldn't push real history out of the keep-recent window.
        #
        # 2. We delete a row only when it's BOTH outside the per-automation
        #    keep-recent window AND older than the retention horizon — so a
        #    low-volume automation always retains its last N terminal runs,
        #    and a high-volume one drops everything past 30 days.
        #
        # No RETURNING — `_execute_db` then returns `cur.rowcount` directly,
        # which is what we want for the log line.
        deleted = _execute_db(
            """
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY automation_id
                           ORDER BY queued_at DESC, id DESC
                       ) AS rn
                  FROM automation_runs
                 WHERE status IN ('succeeded', 'failed', 'timeout', 'cancelled')
            )
            DELETE FROM automation_runs r
             USING ranked
             WHERE r.id = ranked.id
               AND ranked.rn > %s
               AND r.queued_at < NOW() - (INTERVAL '1 day' * %s)
            """,
            (keep, days),
        )
        n = int(deleted) if isinstance(deleted, int) else 0
        if n:
            print(
                f"[automations] retention cleanup deleted {n} old run(s) "
                f"(keep_recent={keep}, retention_days={days})"
            )
        # Prune the rejected-webhook breadcrumb log on the same horizon
        # as runs. We DON'T apply a per-automation keep-recent floor here
        # because rejections are diagnostic noise, not history — once a
        # row is older than the retention horizon it has no practical
        # value and would just bloat the table on a noisy endpoint that
        # gets sprayed with bad signatures. The list is also bounded at
        # the read side (ORDER BY created_at DESC LIMIT 20), so the UI
        # is fine even if a chunk of the table is briefly above the
        # threshold between ticks.
        try:
            rejections_deleted = _execute_db(
                "DELETE FROM automation_webhook_rejections "
                "WHERE created_at < NOW() - (INTERVAL '1 day' * %s)",
                (days,),
            )
            rn = int(rejections_deleted) if isinstance(rejections_deleted, int) else 0
            if rn:
                print(
                    f"[automations] retention cleanup deleted {rn} old "
                    f"webhook rejection(s) (retention_days={days})"
                )
        except Exception as rej_err:
            # Don't roll back the runs cleanup on a rejection-prune
            # failure — runs cleanup already succeeded above and is the
            # bigger of the two tables.
            print(f"[automations] webhook-rejection prune error: {rej_err}")
    except Exception as e:
        # Roll back the cooldown so the next tick will retry instead of
        # silently waiting another full day on transient DB errors.
        with _cleanup_lock:
            _last_cleanup_at = 0.0
        print(f"[automations] retention cleanup error: {e}")


def retention_settings() -> Dict[str, Any]:
    """Exposed via `status_summary` for the admin "Status" view, and also
    consumed by the GET handler that backs the settings form. Returns the
    *effective* values (DB override or env-var fallback) plus the env-var
    defaults and the per-field override flags so the UI can render a
    "default vs custom" indicator and offer a one-click "reset to default"
    by clearing the override."""
    eff = _effective_retention()
    return {
        "retention_days": eff["retention_days"],
        "keep_recent_per_automation": eff["keep_recent_per_automation"],
        "tick_interval_seconds": RETENTION_TICK_INTERVAL_SECONDS,
        "default_retention_days": RETENTION_DAYS,
        "default_keep_recent_per_automation": RETENTION_KEEP_RECENT,
        "max_retention_days": RETENTION_DAYS_MAX,
        "max_keep_recent_per_automation": RETENTION_KEEP_RECENT_MAX,
        "db_overrides": eff["db_overrides"],
    }


def register_with_scheduler(messaging_module: Any) -> None:
    """Hook our ticks into messaging.py's existing scheduler so we share one
    background thread."""
    try:
        messaging_module.register_tick(_scheduler_tick)
    except Exception as e:
        print(f"[automations] could not register scheduler tick: {e}")
    try:
        messaging_module.register_tick(_cleanup_runs_tick)
    except Exception as e:
        print(f"[automations] could not register retention tick: {e}")


# =============================================================================
# REGISTRY ACCESSORS for the admin UI
# =============================================================================

def trigger_metadata() -> List[Dict[str, Any]]:
    return TRIGGER_TYPES


def action_metadata() -> List[Dict[str, Any]]:
    return ACTION_TYPES


def condition_operator_metadata() -> List[Dict[str, Any]]:
    """Operator catalogue for the per-step "Only run when…" picker."""
    return CONDITION_OPERATORS


def status_summary() -> Dict[str, Any]:
    return {
        "max_concurrent_runs": MAX_CONCURRENT_RUNS,
        "in_flight": in_flight_count(),
        "max_runs_per_hour": MAX_RUNS_PER_HOUR_PER_AUTOMATION,
        "max_run_seconds": MAX_RUN_SECONDS,
        "http_step_timeout": HTTP_STEP_TIMEOUT_SECONDS,
        "ai_step_timeout": AI_STEP_TIMEOUT_SECONDS,
        "delay_max_seconds": DELAY_STEP_MAX_SECONDS,
        "retention": retention_settings(),
    }
