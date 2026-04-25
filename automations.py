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
        "config_fields": [],
    },
    {
        "kind": "manual",
        "label": "Manual only (run from the editor)",
        "config_fields": [],
    },
]


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
    try:
        result = messaging.send_sms(to_phone=to, body=body)
        return {
            "ok": True,
            "message_sid": result.get("sid") or "",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}


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


_ACTION_DISPATCH: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = {
    "send_email": _action_send_email,
    "send_sms": _action_send_sms,
    "ai_draft": _action_ai_draft,
    "http_request": _action_http_request,
    "save_to_table": _action_save_to_table,
    "delay": _action_delay,
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


def register_with_scheduler(messaging_module: Any) -> None:
    """Hook our tick into messaging.py's existing scheduler so we share one
    background thread."""
    try:
        messaging_module.register_tick(_scheduler_tick)
    except Exception as e:
        print(f"[automations] could not register scheduler tick: {e}")


# =============================================================================
# REGISTRY ACCESSORS for the admin UI
# =============================================================================

def trigger_metadata() -> List[Dict[str, Any]]:
    return TRIGGER_TYPES


def action_metadata() -> List[Dict[str, Any]]:
    return ACTION_TYPES


def status_summary() -> Dict[str, Any]:
    return {
        "max_concurrent_runs": MAX_CONCURRENT_RUNS,
        "in_flight": in_flight_count(),
        "max_runs_per_hour": MAX_RUNS_PER_HOUR_PER_AUTOMATION,
        "max_run_seconds": MAX_RUN_SECONDS,
        "http_step_timeout": HTTP_STEP_TIMEOUT_SECONDS,
        "ai_step_timeout": AI_STEP_TIMEOUT_SECONDS,
        "delay_max_seconds": DELAY_STEP_MAX_SECONDS,
    }
