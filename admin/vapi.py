"""admin/vapi.py — Vapi (voice AI) integration, slice 1: plumbing.

Vapi handles the realtime voice plumbing (telephony/WebRTC, STT/TTS, interruptions) that the
Twilio <Stream> bridge deferred. This slice wires:
  - connection config via env (VAPI_PRIVATE_KEY for server calls, VAPI_PUBLIC_KEY for the web
    SDK, VAPI_WEBHOOK_SECRET to verify inbound webhooks) — key-optional, graceful when unset.
  - GET /admin/api/vapi/status + POST /admin/api/vapi/probe (super-admin) — config + a live
    connection test that also lists the account's assistants (used by slice 2's registry).
  - POST /webhooks/vapi (public, called by Vapi) — verifies the shared X-Vapi-Secret header
    (fail-closed when the secret is set, mirroring the Twilio webhook), then logs call status +
    end-of-call reports into voice_calls and the cost into voice_cost_events (so Vapi calls show
    up in the existing Voice + Cost surfaces). Tool/function-call handling is slice 3.

Registered in app.py via app.register_blueprint(vapi_bp). The /webhooks prefix is already
CSRF-exempt + un-gated, so the webhook is reachable by Vapi's servers.
"""
import hmac
import os

import httpx
from flask import Blueprint, request, jsonify

from core import (
    query_db,
    execute_db,
    admin_required,
    _require_super_admin_role,
    current_tenant_id,
    capture_exc,
)

vapi_bp = Blueprint("vapi", __name__)

_VAPI_BASE = "https://api.vapi.ai"


# --- config helpers ----------------------------------------------------------

def _vapi_private_key():
    # accept VAPI_API_KEY as a fallback name for the server/private key
    return (os.environ.get("VAPI_PRIVATE_KEY") or os.environ.get("VAPI_API_KEY") or "").strip()


def _vapi_public_key():
    return (os.environ.get("VAPI_PUBLIC_KEY") or "").strip()


def _vapi_webhook_secret():
    return (os.environ.get("VAPI_WEBHOOK_SECRET") or "").strip()


def _vapi_configured():
    return bool(_vapi_private_key())


def _vapi_get(path):
    key = _vapi_private_key()
    with httpx.Client(timeout=20) as cl:
        r = cl.get(_VAPI_BASE + path, headers={"Authorization": "Bearer " + key})
        r.raise_for_status()
        return r.json()


# --- admin: status + connection test -----------------------------------------

@vapi_bp.route("/admin/api/vapi/status", methods=["GET"])
@admin_required
def vapi_status():
    g = _require_super_admin_role()
    if g is not None:
        return g
    return jsonify({
        "configured": _vapi_configured(),
        "public_key_set": bool(_vapi_public_key()),
        "webhook_secret_set": bool(_vapi_webhook_secret()),
    })


@vapi_bp.route("/admin/api/vapi/probe", methods=["POST"])
@admin_required
def vapi_probe():
    """Live connection test: list the account's assistants with the private key. Doubles as
    the data source for slice 2's assistant registry. A bad key returns 200 {ok:false}."""
    g = _require_super_admin_role()
    if g is not None:
        return g
    if not _vapi_configured():
        return jsonify({"ok": False, "error": "not_configured",
                        "message": "Add VAPI_PRIVATE_KEY to your environment to connect Vapi."}), 400
    try:
        data = _vapi_get("/assistant")
        items = data if isinstance(data, list) else (data.get("results") or data.get("data") or [])
        assistants = [{"id": a.get("id"), "name": a.get("name", "")} for a in items if isinstance(a, dict)]
        return jsonify({"ok": True, "count": len(assistants), "assistants": assistants[:50]})
    except Exception as e:
        print(f"[vapi] probe failed: {e}")
        return jsonify({"ok": False, "error": "probe_failed",
                        "message": "Vapi rejected the key or is unreachable. Check VAPI_PRIVATE_KEY."})


# --- inbound webhook (public; Vapi posts call events here) --------------------

def _upsert_call(tid, vid, assistant_id, cust, phone, direction, *, status=None, ended_reason=None,
                 duration=None, cost=None, transcript=None, recording=None, summary=None):
    """Insert or update a voice_calls row keyed by vapi_call_id."""
    existing = query_db("SELECT id FROM voice_calls WHERE vapi_call_id=%s", (vid,), fetchone=True)
    if isinstance(existing, dict):
        sets, params = ["updated_at=NOW()"], []
        for col, val in (("status", status), ("ended_reason", ended_reason),
                         ("duration_seconds", duration), ("cost_usd", cost),
                         ("transcript", transcript), ("recording_url", recording),
                         ("summary", summary), ("assistant_id", assistant_id or None)):
            if val is not None:
                sets.append(f"{col}=%s")
                params.append(val)
        params.append(existing["id"])
        execute_db(f"UPDATE voice_calls SET {', '.join(sets)} WHERE id=%s", tuple(params))
    else:
        # inbound: from=caller, to=our number; outbound: from=our number, to=caller
        frm = cust if direction == "inbound" else phone
        to = phone if direction == "inbound" else cust
        execute_db(
            "INSERT INTO voice_calls (tenant_id, provider, vapi_call_id, assistant_id, call_sid, "
            "from_number, to_number, direction, status, ended_reason, duration_seconds, cost_usd, "
            "transcript, recording_url, summary) "
            "VALUES (%s,'vapi',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (tid, vid, assistant_id or "", vid, frm or "", to or "", direction,
             status or "in-progress", ended_reason or "", duration or 0, cost or 0,
             transcript or "", recording or "", summary or ""),
        )


def _log_cost(tid, vid, assistant_id, duration, cost):
    """Log the Vapi-reported call cost into voice_cost_events so it appears on the Cost tab."""
    if not cost or cost <= 0:
        return
    try:
        execute_db(
            "INSERT INTO voice_cost_events (tenant_id, session_id, surface, provider, model, "
            "feature_type, audio_seconds, cost_usd) "
            "VALUES (%s,%s,'voice_call','vapi',%s,'vapi_call',%s,%s)",
            (tid, vid, assistant_id or "vapi", duration or 0, cost),
        )
    except Exception as e:
        print(f"[vapi] cost log failed: {e}")


@vapi_bp.route("/webhooks/vapi", methods=["POST"])
def vapi_webhook():
    """Vapi posts call lifecycle + end-of-call reports here. Verifies the shared secret header
    (fail-closed when VAPI_WEBHOOK_SECRET is set). Always returns 200 so Vapi doesn't retry-storm;
    errors are captured. Tool/function-call handling is slice 3."""
    secret = _vapi_webhook_secret()
    if secret:
        got = request.headers.get("X-Vapi-Secret", "") or request.headers.get("x-vapi-secret", "")
        if not hmac.compare_digest(got or "", secret):
            return jsonify({"error": "unauthorized"}), 401
    try:
        body = request.get_json(silent=True) or {}
        msg = body.get("message") or {}
        mtype = msg.get("type") or ""
        call = msg.get("call") or {}
        vid = call.get("id") or msg.get("callId") or ""
        if not vid:
            return jsonify({"received": True})
        assistant_id = call.get("assistantId") or msg.get("assistantId") or ""
        cust = ((msg.get("customer") or call.get("customer") or {}) or {}).get("number") or ""
        phone = ((msg.get("phoneNumber") or call.get("phoneNumber") or {}) or {}).get("number") or ""
        ctype = (call.get("type") or "").lower()
        direction = ("inbound" if "inbound" in ctype else
                     "outbound" if "outbound" in ctype else
                     "web" if "web" in ctype else "")
        tid = current_tenant_id()

        if mtype == "end-of-call-report":
            art = msg.get("artifact") or {}
            ended = msg.get("endedReason") or ""
            try:
                cost = float(msg.get("cost") or 0)
            except (TypeError, ValueError):
                cost = 0.0
            try:
                dur = float(msg.get("durationSeconds") or msg.get("duration") or art.get("durationSeconds") or 0)
            except (TypeError, ValueError):
                dur = 0.0
            transcript = msg.get("transcript") or art.get("transcript") or ""
            recording = msg.get("recordingUrl") or art.get("recordingUrl") or ""
            summary = msg.get("summary") or ((msg.get("analysis") or {}) or {}).get("summary") or ""
            _upsert_call(tid, vid, assistant_id, cust, phone, direction, status="ended",
                         ended_reason=ended, duration=dur, cost=cost, transcript=transcript,
                         recording=recording, summary=summary)
            _log_cost(tid, vid, assistant_id, dur, cost)
        elif mtype in ("status-update", "call.started", "call.ended"):
            status = msg.get("status") or call.get("status") or "in-progress"
            _upsert_call(tid, vid, assistant_id, cust, phone, direction, status=status)
        # function-call / tool-calls handled in slice 3.
        return jsonify({"received": True})
    except Exception as e:
        capture_exc(e, "vapi.webhook")
        print(f"[vapi] webhook error: {e}")
        return jsonify({"received": True})
