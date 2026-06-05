"""admin/observability.py — Sentry → app webhook intake + super-admin read API (task 092 P2).

WHY THIS EXISTS: the SENTRY_DSN is WRITE-ONLY — the app ships events TO Sentry but
can't read issues back. The owner runs error-fixing agents that need to KNOW what
Sentry caught. So we accept Sentry's Issue-Alert webhook, verify it, and store one
row per issue in `sentry_alerts`. Agents + the super-admin Developer tab then read
from that table / GET /admin/api/sentry/alerts — no Sentry API credentials needed.

SECURITY — POST /api/sentry/webhook is PUBLIC by nature (Sentry's servers call it,
not a logged-in admin), so it defends itself:
  * HMAC-SHA256 signature verification of the RAW body against SENTRY_WEBHOOK_SECRET
    using hmac.compare_digest (constant-time). No secret configured → 503; bad or
    absent signature → 401. We NEVER accept an unsigned/unverifiable request.
  * Body size hard-capped (_MAX_WEBHOOK_BYTES) far below the app's global
    MAX_CONTENT_LENGTH, rejected 413 BEFORE we parse — bounds the DoS surface.
  * The payload is fully UNTRUSTED: every field is coerced to str + length-capped
    before storage; timestamps are parsed in Python (never cast in SQL, so a bad
    value can't break the upsert); it's stored as JSONB and only ever rendered via
    HTML-escaping in the admin UI, so a malicious title can't XSS.
  * Optional fan-out to AGENT_WEBHOOK_URL is a FIXED env-configured URL only (never
    a URL from the payload) → no SSRF. Best-effort, off the response path (daemon
    thread), so it never delays the 200 we owe Sentry.

The read/triage routes are @admin_required AND self-gate on _require_super_admin_role
(the admin surface is only @admin_required, so super-admin tools must self-gate — a
plain client session is 403'd, independent of the hidden UI tab). CSRF on the POST
status route is enforced by app.py's global before_request hook (all /admin/* state
changes) + the admin fetch wrapper; the public webhook is correctly outside that
/admin scope and uses signature auth instead.

Imports come from core (never app — that would be circular). Registered in app.py
via app.register_blueprint(observability_bp).
"""
import os
import hmac
import hashlib
import json
import threading
from datetime import datetime

from flask import Blueprint, request, jsonify

from core import (
    capture_exc,
    query_db,
    execute_db,
    admin_required,
    _require_super_admin_role,
)

observability_bp = Blueprint("observability", __name__)

# Hard cap on the webhook body — Sentry issue alerts are a few KB; 512KB is a
# generous ceiling that still bounds abuse far below the app's 100MB global cap.
_MAX_WEBHOOK_BYTES = 512 * 1024

# Allowed triage states for an alert row.
_ALERT_STATUSES = ("new", "ack", "fixed")

# Field length caps (defensive — every field in the payload is attacker-influenced).
_CAP_SHORT = 512
_CAP_LONG = 2000


def _cap(val, n):
    """Coerce to a trimmed str of at most n chars (untrusted-input hygiene)."""
    try:
        s = "" if val is None else str(val)
    except Exception:
        s = ""
    return s[:n]


def _parse_ts(val):
    """Best-effort parse of a Sentry ISO8601 timestamp → datetime, or None.

    UNTRUSTED input: any parse failure returns None (never raises) so a weird or
    malicious timestamp string can't break the upsert. We parse in Python and
    hand psycopg2 a real datetime/None rather than casting a raw string to
    ::timestamptz in SQL (which WOULD raise on bad input and fail the insert)."""
    if not val:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        # Sentry emits ISO8601, usually with a trailing 'Z'; fromisoformat wants
        # an explicit offset, so normalize 'Z' → '+00:00'.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _verify_signature(raw_body, secret):
    """Constant-time HMAC-SHA256 check of the RAW body against the configured
    secret. Sentry signs the webhook with the integration's Client Secret in the
    `Sentry-Hook-Signature` header (hex digest). Returns True only on an exact
    match; any missing piece (no header, no secret) → False. Never raises."""
    if not secret:
        return False
    try:
        sig = request.headers.get("Sentry-Hook-Signature", "") or ""
        if not sig:
            return False
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(str(sig), str(expected))
    except Exception:
        return False


def _extract_issue(payload):
    """Normalize a Sentry webhook payload into our row shape, or None when no
    stable issue identifier is present (we need one to dedup).

    Tolerant of the several shapes Sentry emits: the modern Integration
    `data.issue`, the legacy project-webhook top-level fields, and event-shaped
    bodies. Every value is capped; timestamps are parsed (→ datetime/None)."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    issue = data.get("issue") if isinstance(data.get("issue"), dict) else {}
    event = data.get("event") if isinstance(data.get("event"), dict) else (
        payload.get("event") if isinstance(payload.get("event"), dict) else {}
    )

    # issue_id — the dedup key. Try the most specific locations first.
    issue_id = (
        issue.get("id")
        or payload.get("id")
        or event.get("issue_id")
        or event.get("group_id")
        or issue.get("shortId")
    )
    issue_id = _cap(issue_id, _CAP_SHORT).strip()
    if not issue_id:
        return None

    title = (
        issue.get("title") or event.get("title") or payload.get("message")
        or event.get("message") or "(untitled)"
    )
    culprit = issue.get("culprit") or event.get("culprit") or payload.get("culprit") or ""
    level = issue.get("level") or event.get("level") or payload.get("level") or "error"
    permalink = (
        issue.get("permalink") or issue.get("web_url") or payload.get("url")
        or event.get("web_url") or ""
    )
    proj = issue.get("project")
    if isinstance(proj, dict):
        project = proj.get("slug") or proj.get("name") or ""
    else:
        project = proj or payload.get("project") or payload.get("project_name") or ""

    try:
        event_count = int(issue.get("count") or 1)
    except Exception:
        event_count = 1
    if event_count < 1:
        event_count = 1

    return {
        "issue_id": issue_id,
        "title": _cap(title, _CAP_LONG),
        "culprit": _cap(culprit, _CAP_LONG),
        "level": _cap(level, 32),
        "permalink": _cap(permalink, _CAP_LONG),
        "project": _cap(project, _CAP_SHORT),
        "event_count": event_count,
        "first_seen": _parse_ts(issue.get("firstSeen")),
        "last_seen": _parse_ts(issue.get("lastSeen")),
    }


def _fan_out_to_agent(normalized):
    """Best-effort push to a FIXED env-configured agent URL (no SSRF — the URL is
    never taken from the payload). Runs in a daemon thread so it never delays the
    200 we owe Sentry. All failures are swallowed (+ reported to Sentry)."""
    url = (os.environ.get("AGENT_WEBHOOK_URL") or "").strip()
    if not url:
        return

    def _send():
        try:
            import httpx
            httpx.post(url, json=normalized, timeout=5.0)
        except Exception as e:
            capture_exc(e, "observability.fan_out_to_agent")

    try:
        threading.Thread(target=_send, daemon=True).start()
    except Exception as e:
        capture_exc(e, "observability.fan_out_spawn")


@observability_bp.route("/api/sentry/webhook", methods=["POST"])
def sentry_webhook():
    """Inbound Sentry issue-alert webhook. PUBLIC but HMAC-verified. Upserts one
    row per issue_id (idempotent). Returns 200 fast on success."""
    secret = (os.environ.get("SENTRY_WEBHOOK_SECRET") or "").strip()
    if not secret:
        # Owner hasn't configured the secret yet — refuse rather than accept an
        # unsigned request. (Distinct 503 so the owner can tell setup from a bad
        # signature; reveals no sensitive state.)
        return jsonify({"error": "webhook_not_configured"}), 503

    # Size guard BEFORE reading/parsing — bound the DoS surface.
    clen = request.content_length
    if clen is not None and clen > _MAX_WEBHOOK_BYTES:
        return jsonify({"error": "payload_too_large"}), 413
    raw = request.get_data(cache=False, as_text=False) or b""
    if len(raw) > _MAX_WEBHOOK_BYTES:
        return jsonify({"error": "payload_too_large"}), 413

    # Verify the signature over the RAW bytes (NOT the parsed JSON).
    if not _verify_signature(raw, secret):
        return jsonify({"error": "invalid_signature"}), 401

    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        return jsonify({"error": "invalid_json"}), 400

    normalized = _extract_issue(payload)
    if not normalized:
        # Verified, but not an issue-shaped payload (e.g. an installation ping).
        # Acknowledge so Sentry doesn't retry; store nothing.
        return jsonify({"ok": True, "stored": False}), 200

    try:
        row = execute_db(
            """
            INSERT INTO sentry_alerts
                (issue_id, title, culprit, level, project, permalink,
                 event_count, payload, first_seen, last_seen, status, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, 'new', NOW())
            ON CONFLICT (issue_id) DO UPDATE SET
                title       = EXCLUDED.title,
                culprit     = EXCLUDED.culprit,
                level       = EXCLUDED.level,
                project     = EXCLUDED.project,
                permalink   = EXCLUDED.permalink,
                event_count = GREATEST(sentry_alerts.event_count, EXCLUDED.event_count),
                payload     = EXCLUDED.payload,
                last_seen   = COALESCE(EXCLUDED.last_seen, sentry_alerts.last_seen),
                updated_at  = NOW()
            RETURNING id
            """,
            (
                normalized["issue_id"], normalized["title"], normalized["culprit"],
                normalized["level"], normalized["project"], normalized["permalink"],
                normalized["event_count"], json.dumps(payload),
                normalized["first_seen"], normalized["last_seen"],
            ),
        )
    except Exception as e:
        capture_exc(e, "observability.sentry_webhook")
        print(f"[sentry-webhook] upsert failed: {e}")
        return jsonify({"error": "store_failed"}), 500

    # NOTE on status: ON CONFLICT does NOT reset status — a recurring issue keeps
    # the human's ack/fixed triage; event_count + last_seen show it's recurring.

    # Best-effort push to the agent queue (daemon thread; never blocks the 200).
    _fan_out_to_agent(normalized)

    new_id = row.get("id") if isinstance(row, dict) else None
    return jsonify({"ok": True, "stored": True, "id": new_id}), 200


@observability_bp.route("/admin/api/sentry/alerts", methods=["GET"])
@admin_required
def admin_sentry_alerts():
    """Super-admin: list recent Sentry alerts (newest activity first). Optional
    ?status=new|ack|fixed filter and ?limit=N (1..500). The raw payload blob is
    intentionally NOT included in the list (kept lean; read the table directly
    for full payloads)."""
    guard = _require_super_admin_role()
    if guard is not None:
        return guard
    try:
        status = (request.args.get("status") or "").strip().lower()
        try:
            limit = int(request.args.get("limit") or 100)
        except Exception:
            limit = 100
        limit = max(1, min(limit, 500))

        cols = (
            "id, issue_id, title, culprit, level, project, permalink, "
            "event_count, status, first_seen, last_seen, received_at, updated_at"
        )
        if status in _ALERT_STATUSES:
            rows = query_db(
                "SELECT " + cols + " FROM sentry_alerts WHERE status = %s "
                "ORDER BY last_seen DESC NULLS LAST, received_at DESC LIMIT %s",
                (status, limit),
            ) or []
        else:
            rows = query_db(
                "SELECT " + cols + " FROM sentry_alerts "
                "ORDER BY last_seen DESC NULLS LAST, received_at DESC LIMIT %s",
                (limit,),
            ) or []

        # Status counts for the tab badges (best-effort).
        counts = {}
        try:
            for r in (query_db("SELECT status, COUNT(*) AS n FROM sentry_alerts GROUP BY status") or []):
                counts[str(r["status"])] = int(r["n"])
        except Exception:
            counts = {}

        return jsonify({"ok": True, "alerts": [dict(r) for r in rows], "counts": counts})
    except Exception as e:
        capture_exc(e, "observability.admin_sentry_alerts")
        return jsonify({"ok": False, "error": "list_failed", "detail": str(e)}), 500


@observability_bp.route("/admin/api/sentry/alerts/<int:alert_id>/status", methods=["POST"])
@admin_required
def admin_set_sentry_alert_status(alert_id):
    """Super-admin: set an alert's triage status (new|ack|fixed). Shared queue
    so humans and the fix-agents see the same state."""
    guard = _require_super_admin_role()
    if guard is not None:
        return guard
    body = request.get_json(silent=True) or {}
    new_status = (str(body.get("status") or "")).strip().lower()
    if new_status not in _ALERT_STATUSES:
        return jsonify({"error": "invalid_status", "allowed": list(_ALERT_STATUSES)}), 400
    try:
        affected = execute_db(
            "UPDATE sentry_alerts SET status = %s, updated_at = NOW() WHERE id = %s",
            (new_status, alert_id),
        )
        if not affected:
            return jsonify({"error": "not_found", "id": alert_id}), 404
        return jsonify({"ok": True, "id": alert_id, "status": new_status})
    except Exception as e:
        capture_exc(e, "observability.admin_set_sentry_alert_status")
        return jsonify({"error": "update_failed", "detail": str(e)}), 500
