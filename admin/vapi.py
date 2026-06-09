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
import json
import os
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - py<3.9 only
    ZoneInfo = None

import httpx
from flask import Blueprint, request, jsonify

from core import (
    query_db,
    execute_db,
    admin_required,
    _require_super_admin_role,
    current_tenant_id,
    capture_exc,
    get_ai_setting,
    compute_today_spend,
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


def _vapi_post(path, body):
    key = _vapi_private_key()
    with httpx.Client(timeout=30) as cl:
        r = cl.post(_VAPI_BASE + path,
                    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                    json=body)
        r.raise_for_status()
        return r.json()


def _vapi_patch(path, body):
    key = _vapi_private_key()
    with httpx.Client(timeout=30) as cl:
        r = cl.patch(_VAPI_BASE + path,
                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                     json=body)
        r.raise_for_status()
        return r.json()


# --- voice compliance settings (recording + consent disclosure) --------------
# Stored as a JSONB blob on the singleton site_settings row (id=1; migration 0044), mirroring the
# appearance customizer's admin_theme_extra. Turned into Vapi `assistantOverrides` on every call WE
# initiate (campaign, manual outbound, in-browser test) so the operator can centrally disable
# recording or speak a consent disclosure without editing each assistant in Vapi.

_VOICE_COMPLIANCE_DEFAULTS = {"recording_enabled": True, "consent_message": ""}


def _voice_compliance_get():
    """Read the compliance blob. Fail-OPEN to defaults — never block a call on a settings read."""
    out = dict(_VOICE_COMPLIANCE_DEFAULTS)
    try:
        row = query_db("SELECT voice_compliance FROM site_settings WHERE id=1", fetchone=True)
        raw = (row or {}).get("voice_compliance") if isinstance(row, dict) else None
        blob = json.loads(raw) if isinstance(raw, str) else (raw or {})
        if isinstance(blob, dict):
            if "recording_enabled" in blob:
                out["recording_enabled"] = bool(blob.get("recording_enabled"))
            if "consent_message" in blob:
                out["consent_message"] = str(blob.get("consent_message") or "")[:2000]
    except Exception:
        pass
    return out


def _voice_compliance_save(blob):
    """Persist the compliance blob to the singleton site_settings row. Returns the cleaned blob."""
    clean = {"recording_enabled": bool(blob.get("recording_enabled", True)),
             "consent_message": str(blob.get("consent_message") or "")[:2000]}
    execute_db("UPDATE site_settings SET voice_compliance=%s::jsonb WHERE id=1", (json.dumps(clean),))
    return clean


def _vapi_assistant_overrides():
    """Build assistantOverrides from compliance settings, or {} when there's nothing to override.
    We only override to ENFORCE a non-default (recording OFF or a consent first-message), so a
    default config sends no override and the assistant's own full settings apply unchanged.
    `artifactPlan.recordingEnabled` + `firstMessage` are the documented Vapi override fields; both
    are valid on POST /call and the web SDK start()."""
    c = _voice_compliance_get()
    ov = {}
    if not c["recording_enabled"]:
        ov["artifactPlan"] = {"recordingEnabled": False}
    if c.get("consent_message"):
        ov["firstMessage"] = c["consent_message"]
    return ov


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
        # the PUBLIC key is publishable (it's designed to ship to browsers); the super-admin panel
        # uses it for the in-browser "Talk to assistant" test. assistant_overrides carries the
        # compliance settings the web test should apply (recording off / consent first-message).
        "public_key": _vapi_public_key(),
        "assistant_overrides": _vapi_assistant_overrides(),
        "webhook_secret_set": bool(_vapi_webhook_secret()),
        "llm_secret_set": bool((os.environ.get("VAPI_LLM_SECRET")
                                or os.environ.get("VAPI_WEBHOOK_SECRET") or "").strip()),
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


# --- assistant registry + calling (slice 2; super-admin) ---------------------

@vapi_bp.route("/admin/api/vapi/assistants", methods=["GET"])
@admin_required
def vapi_assistants():
    """List the account's Vapi assistants (live from Vapi). Both kinds show up here: managed
    (Vapi-brained, e.g. Cold Lead Qualifier) and concierge (custom-llm, slice 3)."""
    g = _require_super_admin_role()
    if g is not None:
        return g
    if not _vapi_configured():
        return jsonify({"configured": False, "assistants": []})
    try:
        data = _vapi_get("/assistant")
        items = data if isinstance(data, list) else (data.get("results") or data.get("data") or [])
        out = [{"id": a.get("id"), "name": a.get("name", ""),
                "model": ((a.get("model") or {}) or {}).get("provider") or ""}
               for a in items if isinstance(a, dict)]
        return jsonify({"configured": True, "assistants": out})
    except Exception as e:
        print(f"[vapi] list assistants failed: {e}")
        return jsonify({"configured": True, "assistants": [], "error": "Could not list assistants."})


@vapi_bp.route("/admin/api/vapi/phone-numbers", methods=["GET"])
@admin_required
def vapi_phone_numbers():
    """List the account's Vapi phone numbers (for outbound 'call from' + inbound assignment)."""
    g = _require_super_admin_role()
    if g is not None:
        return g
    if not _vapi_configured():
        return jsonify({"configured": False, "phone_numbers": []})
    try:
        data = _vapi_get("/phone-number")
        items = data if isinstance(data, list) else (data.get("results") or data.get("data") or [])
        out = [{"id": p.get("id"), "number": p.get("number", ""), "name": p.get("name", ""),
                "assistant_id": p.get("assistantId", "")}
               for p in items if isinstance(p, dict)]
        return jsonify({"configured": True, "phone_numbers": out})
    except Exception as e:
        print(f"[vapi] list numbers failed: {e}")
        return jsonify({"configured": True, "phone_numbers": [], "error": "Could not list phone numbers."})


@vapi_bp.route("/admin/api/vapi/call", methods=["POST"])
@admin_required
def vapi_place_call():
    """Place an OUTBOUND call: dial customer_number from phone_number_id with assistant_id.
    Logs an outbound voice_calls row; the webhook later fills status/cost/transcript."""
    g = _require_super_admin_role()
    if g is not None:
        return g
    if not _vapi_configured():
        return jsonify({"error": "not_configured", "message": "Add VAPI_PRIVATE_KEY to place calls."}), 400
    body = request.get_json(silent=True) or {}
    assistant_id = (body.get("assistant_id") or "").strip()
    phone_number_id = (body.get("phone_number_id") or "").strip()
    customer = (body.get("customer_number") or "").strip()
    if not assistant_id or not phone_number_id or not customer:
        return jsonify({"error": "missing",
                        "message": "assistant_id, phone_number_id, and customer_number are required."}), 400
    if not customer.startswith("+"):
        return jsonify({"error": "bad_number", "message": "Use E.164 format, e.g. +15551234567."}), 400
    try:
        _body = {"assistantId": assistant_id, "phoneNumberId": phone_number_id,
                 "customer": {"number": customer}}
        _ov = _vapi_assistant_overrides()
        if _ov:
            _body["assistantOverrides"] = _ov
        res = _vapi_post("/call", _body)
        call_id = res.get("id") or "" if isinstance(res, dict) else ""
        if call_id:
            try:
                execute_db(
                    "INSERT INTO voice_calls (tenant_id, provider, vapi_call_id, assistant_id, call_sid, "
                    "to_number, direction, status) VALUES (%s,'vapi',%s,%s,%s,%s,'outbound','initiated')",
                    (current_tenant_id(), call_id, assistant_id, call_id, customer),
                )
            except Exception as e:
                print(f"[vapi] outbound log failed: {e}")
        return jsonify({"success": True, "call_id": call_id})
    except Exception as e:
        capture_exc(e, "vapi.place_call")
        print(f"[vapi] place call failed: {e}")
        return jsonify({"error": "call_failed", "message": "Vapi rejected the call request."}), 502


@vapi_bp.route("/admin/api/vapi/phone-number", methods=["PATCH"])
@admin_required
def vapi_assign_number():
    """Assign (or clear) an assistant on a phone number for INBOUND calls, via Vapi partial-update."""
    g = _require_super_admin_role()
    if g is not None:
        return g
    if not _vapi_configured():
        return jsonify({"error": "not_configured", "message": "Add VAPI_PRIVATE_KEY."}), 400
    body = request.get_json(silent=True) or {}
    pid = (body.get("phone_number_id") or "").strip()
    assistant_id = (body.get("assistant_id") or "").strip()
    if not pid:
        return jsonify({"error": "missing", "message": "phone_number_id is required."}), 400
    try:
        _vapi_patch("/phone-number/" + pid, {"assistantId": assistant_id or None})
        return jsonify({"success": True})
    except Exception as e:
        capture_exc(e, "vapi.assign_number")
        print(f"[vapi] assign number failed: {e}")
        return jsonify({"error": "assign_failed", "message": "Could not update the phone number."}), 502


@vapi_bp.route("/admin/api/vapi/phone-number", methods=["POST"])
@admin_required
def vapi_provision_number():
    """Provision a FREE Vapi-managed phone number (provider=vapi). US-only, max 10 per wallet.
    Optionally attach an assistant (inbound) + a desired area code, and wire this number's events
    to our /webhooks/vapi so inbound calls + reports land in the Voice/Cost surfaces."""
    g = _require_super_admin_role()
    if g is not None:
        return g
    if not _vapi_configured():
        return jsonify({"error": "not_configured", "message": "Add VAPI_PRIVATE_KEY to provision a number."}), 400
    body = request.get_json(silent=True) or {}
    area = "".join(ch for ch in str(body.get("area_code") or "") if ch.isdigit())[:3]
    assistant_id = (body.get("assistant_id") or "").strip()
    name = (body.get("name") or "").strip()[:80]
    payload = {"provider": "vapi"}
    if area:
        payload["numberDesiredAreaCode"] = area
    if assistant_id:
        payload["assistantId"] = assistant_id
    if name:
        payload["name"] = name
    try:  # route the number's events to our webhook (best-effort; operator can fix it in Vapi)
        payload["server"] = {"url": request.url_root.rstrip("/") + "/webhooks/vapi"}
    except Exception:
        pass
    try:
        res = _vapi_post("/phone-number", payload)
        return jsonify({"success": True,
                        "id": (res.get("id") if isinstance(res, dict) else "") or "",
                        "number": (res.get("number") if isinstance(res, dict) else "") or ""})
    except Exception as e:
        capture_exc(e, "vapi.provision_number")
        print(f"[vapi] provision number failed: {e}")
        return jsonify({"error": "provision_failed",
                        "message": "Vapi could not provision a number (free numbers are US-only, max 10 per wallet)."}), 502


@vapi_bp.route("/admin/api/vapi/compliance", methods=["GET"])
@admin_required
def vapi_compliance_get():
    """Read voice compliance settings (recording toggle + consent disclosure)."""
    g = _require_super_admin_role()
    if g is not None:
        return g
    return jsonify(_voice_compliance_get())


@vapi_bp.route("/admin/api/vapi/compliance", methods=["POST"])
@admin_required
def vapi_compliance_save():
    """Save voice compliance settings. Applied as assistantOverrides on calls we initiate."""
    g = _require_super_admin_role()
    if g is not None:
        return g
    body = request.get_json(silent=True) or {}
    saved = _voice_compliance_save(body)
    return jsonify({"success": True, **saved})


# --- visitor-facing "Talk to us" voice button (public; super-admin configured) -------------------
# The embed widget can show a voice button with two modes: an in-browser call (web SDK + the
# publishable public key) and an outbound phone callback (we dial a number the visitor enters).
# The phone callback is an ANONYMOUS-triggered auto-dialer, so it is the most security-sensitive
# surface in the integration. It is guarded, in order, by: super-admin enable -> the
# OUTBOUND_CALLING_ENABLED deployment switch -> per-IP / per-number / global-per-day rate limits
# (the limiter FAILS CLOSED) -> the daily spend cap (fails open) -> E.164 validation (must carry a
# country code) -> a honeypot field. Context comes from the configured CONCIERGE assistant (its
# custom-LLM brain injects KB + brand voice every turn); each call is also tagged with page +
# visitor metadata. We never expose the private key or the phone_number_id to the browser.

_WEB_VOICE_DEFAULTS = {"enabled": False, "mode": "both", "assistant_id": "",
                       "phone_number_id": "", "button_label": "Talk to us", "daily_call_cap": 50}
_WEB_VOICE_MODES = ("browser", "phone", "both")
_WEB_CALL_PER_IP_HOUR = 3       # max callbacks one IP can request per hour (best-effort; IP isn't trusted)
_WEB_CALL_PER_PHONE_DAY = 2     # max callbacks to a single number per day (anti-harassment — the real cap)


def _normalize_e164(raw):
    """Return a '+<digits>' E.164 number, or '' if it doesn't look valid. We REQUIRE an explicit
    leading '+' (country code) rather than guessing one — guessing risks dialing the wrong country."""
    s = "".join(ch for ch in str(raw or "") if ch.isdigit() or ch == "+").strip()
    if not s.startswith("+"):
        return ""
    digits = s[1:]
    if not digits.isdigit() or not (8 <= len(digits) <= 15):
        return ""
    return "+" + digits


def _web_voice_get():
    """Read the visitor-voice config blob. Fail-OPEN to defaults (feature simply stays off)."""
    out = dict(_WEB_VOICE_DEFAULTS)
    try:
        row = query_db("SELECT web_voice FROM site_settings WHERE id=1", fetchone=True)
        raw = (row or {}).get("web_voice") if isinstance(row, dict) else None
        blob = json.loads(raw) if isinstance(raw, str) else (raw or {})
        if isinstance(blob, dict):
            out["enabled"] = bool(blob.get("enabled"))
            m = str(blob.get("mode") or "both")
            out["mode"] = m if m in _WEB_VOICE_MODES else "both"
            out["assistant_id"] = str(blob.get("assistant_id") or "")[:120]
            out["phone_number_id"] = str(blob.get("phone_number_id") or "")[:120]
            out["button_label"] = (str(blob.get("button_label") or "").strip()[:60]) or "Talk to us"
            try:
                out["daily_call_cap"] = max(0, min(int(blob.get("daily_call_cap", 50)), 1000))
            except (TypeError, ValueError):
                out["daily_call_cap"] = 50
    except Exception:
        pass
    return out


def _web_voice_save(blob):
    m = str(blob.get("mode") or "both")
    clean = {"enabled": bool(blob.get("enabled")),
             "mode": m if m in _WEB_VOICE_MODES else "both",
             "assistant_id": str(blob.get("assistant_id") or "")[:120],
             "phone_number_id": str(blob.get("phone_number_id") or "")[:120],
             "button_label": (str(blob.get("button_label") or "").strip()[:60]) or "Talk to us"}
    try:
        clean["daily_call_cap"] = max(0, min(int(blob.get("daily_call_cap", 50)), 1000))
    except (TypeError, ValueError):
        clean["daily_call_cap"] = 50
    execute_db("UPDATE site_settings SET web_voice=%s::jsonb WHERE id=1", (json.dumps(clean),))
    return clean


@vapi_bp.route("/admin/api/vapi/web-voice", methods=["GET"])
@admin_required
def vapi_web_voice_get():
    g = _require_super_admin_role()
    if g is not None:
        return g
    return jsonify(_web_voice_get())


@vapi_bp.route("/admin/api/vapi/web-voice", methods=["POST"])
@admin_required
def vapi_web_voice_save():
    g = _require_super_admin_role()
    if g is not None:
        return g
    return jsonify({"success": True, **_web_voice_save(request.get_json(silent=True) or {})})


@vapi_bp.route("/api/voice/web-config", methods=["GET"])
def vapi_web_voice_config():
    """PUBLIC: the embed widget reads this to decide whether to show the voice button + in which
    modes. Exposes ONLY the publishable public key + assistant id (browser mode) — never the
    private key or the phone_number_id (the phone call is placed server-side)."""
    cfg = _web_voice_get()
    if not cfg["enabled"]:
        return jsonify({"enabled": False})
    out = {"enabled": True, "mode": cfg["mode"], "button_label": cfg["button_label"]}
    pk = _vapi_public_key()
    out["browser"] = bool(cfg["mode"] in ("browser", "both") and pk and cfg["assistant_id"])
    if out["browser"]:
        out["public_key"] = pk
        out["assistant_id"] = cfg["assistant_id"]
    out["phone"] = bool(cfg["mode"] in ("phone", "both") and _outbound_enabled()
                        and _vapi_configured() and cfg["phone_number_id"] and cfg["assistant_id"])
    return jsonify(out)


@vapi_bp.route("/api/voice/callback", methods=["POST"])
def vapi_web_voice_callback():
    """PUBLIC: a visitor asks us to call their phone. Anonymous-triggered outbound → fully guarded
    (see the section header). Returns {ok} without ever echoing the number back."""
    body = request.get_json(silent=True) or {}
    if (str(body.get("_hp") or "")).strip():
        return jsonify({"ok": True})   # honeypot tripped → look successful, dial nobody
    cfg = _web_voice_get()
    if not (cfg["enabled"] and cfg["mode"] in ("phone", "both")):
        return jsonify({"ok": False, "error": "unavailable"}), 404
    if not _outbound_enabled():
        return jsonify({"ok": False, "error": "unavailable",
                        "message": "Phone callbacks aren't available right now."}), 503
    if not (_vapi_configured() and cfg["assistant_id"] and cfg["phone_number_id"]):
        return jsonify({"ok": False, "error": "unavailable"}), 503
    phone = _normalize_e164(body.get("phone") or "")
    if not phone:
        return jsonify({"ok": False, "error": "bad_number",
                        "message": "Enter your number in international format, e.g. +15551234567."}), 400
    ip = (request.remote_addr or "unknown")[:45]   # XFF deliberately not trusted (see app._client_ip)
    # Rate limits — the limiter FAILS CLOSED: a DB hiccup must never open the auto-dialer.
    try:
        n_ip = (query_db("SELECT COUNT(*) AS n FROM web_call_requests WHERE ip=%s "
                         "AND created_at >= NOW() - INTERVAL '1 hour'", (ip,), fetchone=True) or {}).get("n", 0)
        if n_ip >= _WEB_CALL_PER_IP_HOUR:
            return jsonify({"ok": False, "error": "rate_limited",
                            "message": "Too many requests — please try again later."}), 429
        n_phone = (query_db("SELECT COUNT(*) AS n FROM web_call_requests WHERE phone=%s "
                            "AND created_at >= NOW() - INTERVAL '1 day'", (phone,), fetchone=True) or {}).get("n", 0)
        if n_phone >= _WEB_CALL_PER_PHONE_DAY:
            return jsonify({"ok": False, "error": "rate_limited",
                            "message": "This number has reached today's callback limit."}), 429
        cap = cfg["daily_call_cap"]
        if cap > 0:
            n_day = (query_db("SELECT COUNT(*) AS n FROM web_call_requests "
                              "WHERE created_at >= CURRENT_DATE", fetchone=True) or {}).get("n", 0)
            if n_day >= cap:
                return jsonify({"ok": False, "error": "unavailable",
                                "message": "Callbacks are paused for today."}), 503
    except Exception as e:
        capture_exc(e, "vapi.web_callback.ratelimit")
        return jsonify({"ok": False, "error": "unavailable"}), 503
    # Daily spend cap (cost) — fail-OPEN, consistent with the campaign.
    try:
        scap = float(get_ai_setting("daily_spend_cap_usd") or 0)
        if scap > 0 and compute_today_spend().get("total_usd", 0.0) >= scap:
            return jsonify({"ok": False, "error": "unavailable",
                            "message": "Callbacks are paused for today."}), 503
    except Exception:
        pass
    # Place the call: concierge assistant (context-rich brain) + page/visitor metadata + compliance.
    tid = current_tenant_id()
    meta = {"source": "web_widget",
            "visitor_id": str(body.get("visitor_id") or "")[:80],
            "session_id": str(body.get("session_id") or "")[:80],
            "page_url": str(body.get("page_url") or "")[:300]}
    cbody = {"assistantId": cfg["assistant_id"], "phoneNumberId": cfg["phone_number_id"],
             "customer": {"number": phone}, "metadata": meta}
    ov = _vapi_assistant_overrides()
    if ov:
        cbody["assistantOverrides"] = ov
    try:
        res = _vapi_post("/call", cbody)
        cid = (res.get("id") or "") if isinstance(res, dict) else ""
    except Exception as e:
        capture_exc(e, "vapi.web_callback.place")
        print(f"[vapi] web callback failed: {e}")
        return jsonify({"ok": False, "error": "call_failed",
                        "message": "We couldn't place the call. Please try again later."}), 502
    try:
        execute_db("INSERT INTO web_call_requests (tenant_id, ip, phone, mode, vapi_call_id) "
                   "VALUES (%s,%s,%s,'phone',%s)", (tid, ip, phone, cid))
        execute_db("INSERT INTO voice_calls (tenant_id, provider, vapi_call_id, assistant_id, call_sid, "
                   "to_number, direction, status) VALUES (%s,'vapi',%s,%s,%s,%s,'outbound','initiated')",
                   (tid, cid, cfg["assistant_id"], cid, phone))
    except Exception as e:
        print(f"[vapi] web callback log failed: {e}")
    return jsonify({"ok": True, "message": "Calling you now — please answer your phone."})


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


def _vapi_handle_tool_call(msg, call_id):
    """Run a Vapi tool/function call against the concierge's tools and return Vapi's expected
    result shape. Routes to the SAME executor the website chat uses (execute_chat_tool), so
    managed assistants reuse book_meeting / capture_lead / lookups with no rewrite. Handles both
    the newer toolCalls and the legacy functionCall shapes. Lazy app import (app imports this
    blueprint, so import at call time to avoid a cycle)."""
    try:
        from app import execute_chat_tool
    except Exception as e:
        print(f"[vapi] tool executor import failed: {e}")
        return jsonify({"results": []})
    sess = str(call_id or "vapi")

    def _run(name, args):
        args_json = args if isinstance(args, str) else json.dumps(args or {})
        try:
            out, _log = execute_chat_tool(name or "", args_json, session_id=sess)
            return out if isinstance(out, str) else json.dumps(out)
        except Exception as e:
            print(f"[vapi] tool '{name}' failed: {e}")
            return json.dumps({"error": "tool_failed"})

    tcs = msg.get("toolCalls") or msg.get("toolCallList") or []
    if isinstance(tcs, list) and tcs:
        results = []
        for tc in tcs:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            results.append({"toolCallId": tc.get("id") or "",
                            "result": _run(fn.get("name"), fn.get("arguments"))})
        return jsonify({"results": results})

    fc = msg.get("functionCall") or {}
    if isinstance(fc, dict) and fc.get("name"):
        return jsonify({"result": _run(fc.get("name"), fc.get("parameters"))})
    return jsonify({"results": []})


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

        # Tool/function calls need a synchronous result back to Vapi.
        if mtype in ("function-call", "tool-calls"):
            return _vapi_handle_tool_call(msg, vid)

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
        # (function-call / tool-calls handled above.)
        return jsonify({"received": True})
    except Exception as e:
        capture_exc(e, "vapi.webhook")
        print(f"[vapi] webhook error: {e}")
        return jsonify({"received": True})


# --- Outbound-call automation action (Vapi + automations) --------------------
# A scheduled automation action that places outbound Vapi calls to people matching a status
# filter. It auto-dials REAL people, so it is heavily guarded:
#   * ENV kill-switch OUTBOUND_CALLING_ENABLED (off by default; owner-armed, not admin-toggleable
#     — a compromised admin can't start mass-dialing) AND requires VAPI_PRIVATE_KEY.
#   * calling-hours window (fail-safe: any tz/hour error → skip, never dial off-hours).
#   * skips do-not-call statuses; only dials E.164 numbers.
#   * deduped per campaign via campaign_calls (each person called once per automation).
#   * dry-run aware (a test run reports who it WOULD call, dials no one).
# Audience tables are ALLOWLISTED (no arbitrary SQL); the phone column is fixed; status is a bound
# parameter. Registered into the automations engine via register_action (additive).

_VAPI_CAMPAIGN_TABLES = {"leads", "meetings"}   # both have a `phone` + `status` column
_VAPI_DNC = ("dnc", "do_not_call", "do-not-call", "unsubscribed", "opted_out")


def _outbound_enabled():
    return (os.environ.get("OUTBOUND_CALLING_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


def _tenant_tz():
    try:
        r = query_db("SELECT timezone FROM tenants WHERE id=%s", (current_tenant_id(),), fetchone=True)
        return (r.get("timezone") or "UTC").strip() if isinstance(r, dict) else "UTC"
    except Exception:
        return "UTC"


def _within_hours(tzname, start_h, end_h):
    """True only if the current local time in tzname is within [start_h, end_h). If the timezone
    db is unavailable (e.g. no IANA tzdata) we fall back to UTC rather than skipping outright, so
    a window is still enforced. start_h == end_h means 'no window' → never within."""
    try:
        hour = None
        if ZoneInfo and tzname:
            try:
                hour = datetime.now(ZoneInfo(tzname)).hour
            except Exception:
                hour = None   # missing tzdata / bad tz → fall back to UTC below
        if hour is None:
            hour = datetime.utcnow().hour
        if start_h == end_h:
            return False
        if start_h < end_h:
            return start_h <= hour < end_h
        return hour >= start_h or hour < end_h     # overnight window
    except Exception:
        return False


def _run_outbound_campaign(cfg, ctx):
    """automations action 'vapi_outbound_campaign'. cfg keys: assistant_id, phone_number_id,
    audience_table, status_filter, max_calls_per_run, call_start_hour, call_end_hour, timezone."""
    if not _outbound_enabled():
        return {"ok": False, "skipped": "OUTBOUND_CALLING_ENABLED is not set"}
    if not _vapi_configured():
        return {"ok": False, "error": "VAPI_PRIVATE_KEY is not set"}
    assistant_id = (cfg.get("assistant_id") or "").strip()
    phone_number_id = (cfg.get("phone_number_id") or "").strip()
    if not assistant_id or not phone_number_id:
        return {"ok": False, "error": "assistant_id and phone_number_id are required"}
    table = (cfg.get("audience_table") or "leads").strip()
    if table not in _VAPI_CAMPAIGN_TABLES:
        return {"ok": False, "error": "audience_table must be one of " + ", ".join(sorted(_VAPI_CAMPAIGN_TABLES))}
    status_filter = (cfg.get("status_filter") or "").strip()
    try:
        max_calls = max(1, min(int(cfg.get("max_calls_per_run") or 10), 100))
    except (TypeError, ValueError):
        max_calls = 10
    tzname = (cfg.get("timezone") or "").strip() or _tenant_tz()
    try:
        start_h = int(cfg.get("call_start_hour"))
    except (TypeError, ValueError):
        start_h = 9
    try:
        end_h = int(cfg.get("call_end_hour"))
    except (TypeError, ValueError):
        end_h = 18
    if not _within_hours(tzname, start_h, end_h):
        return {"ok": True, "calls_placed": 0,
                "skipped": "outside calling hours (%d-%d %s)" % (start_h, end_h, tzname)}
    aid = ctx.get("__automation_id") or 0
    tid = current_tenant_id()
    # Scope to this tenant explicitly: even in the single-tenant silo deployment, never let an
    # auto-dialer reach rows it doesn't own. `table` is allowlisted above (no SQL injection); every
    # other value below is a bound parameter.
    where = ["t.tenant_id = %s", "t.phone <> ''",
             "(t.status IS NULL OR LOWER(t.status) NOT IN ('dnc','do_not_call','do-not-call','unsubscribed','opted_out'))"]
    params = [tid]
    if status_filter:
        where.append("t.status = %s")
        params.append(status_filter)
    sql = ("SELECT t.id AS aid, t.phone AS phone FROM " + table + " t WHERE " + " AND ".join(where)
           + " AND NOT EXISTS (SELECT 1 FROM campaign_calls c WHERE c.automation_id=%s "
           + "AND c.audience_table=%s AND c.audience_id=t.id) ORDER BY t.id LIMIT %s")
    try:
        rows = query_db(sql, tuple(params + [aid, table, max_calls])) or []
    except Exception as e:
        return {"ok": False, "error": "audience query failed: " + str(e)[:200]}
    targets = [r for r in rows if str((r or {}).get("phone") or "").strip().startswith("+")]  # E.164 only
    if ctx.get("__dry_run"):
        return {"ok": True, "dry_run": True, "would_call": len(targets),
                "table": table, "status_filter": status_filter}
    # Daily spend cap (AI Control knob, shared with chat + the voice brain): never let a scheduled
    # campaign blow the budget. Checked once before the batch. Fail-OPEN (a glitch won't stall ops).
    try:
        _cap = float(get_ai_setting("daily_spend_cap_usd") or 0)
        if _cap > 0 and compute_today_spend().get("total_usd", 0.0) >= _cap:
            return {"ok": True, "calls_placed": 0, "skipped": "daily spend cap reached"}
    except Exception:
        pass
    overrides = _vapi_assistant_overrides()   # recording-off / consent first-message, if configured
    placed = 0
    for r in targets:
        num = str(r["phone"]).strip()
        try:
            _cbody = {"assistantId": assistant_id, "phoneNumberId": phone_number_id,
                      "customer": {"number": num}}
            if overrides:
                _cbody["assistantOverrides"] = overrides
            res = _vapi_post("/call", _cbody)
            cid = (res.get("id") or "") if isinstance(res, dict) else ""
            execute_db(
                "INSERT INTO campaign_calls (tenant_id, automation_id, audience_table, audience_id, phone, vapi_call_id) "
                "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (automation_id, audience_table, audience_id) DO NOTHING",
                (tid, aid, table, r["aid"], num, cid))
            execute_db(
                "INSERT INTO voice_calls (tenant_id, provider, vapi_call_id, assistant_id, call_sid, to_number, direction, status) "
                "VALUES (%s,'vapi',%s,%s,%s,%s,'outbound','initiated')",
                (tid, cid, assistant_id, cid, num))
            placed += 1
        except Exception as e:
            print(f"[vapi campaign] call to {num} failed: {e}")
    return {"ok": True, "calls_placed": placed, "targets": len(targets), "table": table}


_VAPI_CAMPAIGN_METADATA = {
    "kind": "vapi_outbound_campaign",
    "label": "Outbound call campaign (Vapi)",
    "description": ("On each scheduled run, call people matching a status with a Vapi assistant. "
                    "Requires OUTBOUND_CALLING_ENABLED=1 + VAPI_PRIVATE_KEY. Deduped per campaign, "
                    "respects calling hours, skips do-not-call. Pair with a 'schedule' trigger."),
    "config_fields": [
        {"name": "assistant_id", "label": "Vapi assistant ID", "kind": "text", "required": True,
         "placeholder": "asst_… (see Voice → Vapi → Load assistants)"},
        {"name": "phone_number_id", "label": "Vapi phone number ID (call from)", "kind": "text", "required": True,
         "placeholder": "the number's id"},
        {"name": "audience_table", "label": "Audience table", "kind": "text", "placeholder": "leads or meetings"},
        {"name": "status_filter", "label": "Only call where status =", "kind": "text", "placeholder": "cold"},
        {"name": "max_calls_per_run", "label": "Max calls per run", "kind": "number", "placeholder": "10"},
        {"name": "call_start_hour", "label": "Calling window start hour (0-23)", "kind": "number", "placeholder": "9"},
        {"name": "call_end_hour", "label": "Calling window end hour (0-23)", "kind": "number", "placeholder": "18"},
        {"name": "timezone", "label": "Timezone (blank = tenant default)", "kind": "text", "placeholder": "America/New_York"},
    ],
}

try:
    import automations as _automations
    _automations.register_action("vapi_outbound_campaign", _run_outbound_campaign, _VAPI_CAMPAIGN_METADATA)
except Exception as _e:  # pragma: no cover - never block blueprint import
    print(f"[vapi] campaign action registration failed: {_e}")
