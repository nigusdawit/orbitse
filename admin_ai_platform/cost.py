"""
admin_ai_platform.cost
======================

Cost ledger write helpers + monthly-cap enforcement (independent copy of the
cost block in app.py ~4228-4640). Used package-wide: every paid surface
(chat, voice, SMS) stamps a ledger row here, and gateway code calls
``enforce_cost_cap`` (HTTP) / ``cost_cap_blocks_send`` (background) before
paying a provider.

Unit prices are stamped at write time so a later price edit can never shift
historical totals. Missing usage → ``cost_usd = NULL`` (an "uncosted call"),
never a fabricated $0 — honest accounting.

The cost *dashboard blueprint* (read endpoints, prices editor, digest) lands in
M3. The warn-line email send is wired to messaging in M3/M5; until then
``_async_warn_check`` records the idempotent alert row and logs (no email).
"""

from __future__ import annotations

import threading
import time as _time
from datetime import datetime

from .db import query_db, execute_db
from .tenancy import current_tenant_id, tenant_has_feature

try:  # Sentry optional — never let its absence break cost writes.
    import sentry_sdk
except Exception:  # pragma: no cover
    sentry_sdk = None

# 60s in-process price cache.
_PRICE_CACHE: dict = {}
_PRICE_CACHE_EXP: dict = {}
_PRICE_CACHE_TTL_SEC = 60


def _capture(e):
    if sentry_sdk is not None:
        try:
            sentry_sdk.capture_exception(e)
        except Exception:
            pass


def _to_float(x, default=0.0):
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def _current_period():
    """The 'YYYY-MM' string used to bucket monthly spend (UTC)."""
    return datetime.utcnow().strftime("%Y-%m")


def get_model_price(provider, model, surface="chat"):
    """Active price row for (provider, model, surface) or None. 60s cached."""
    key = ((provider or "").lower(), (model or "").strip(), (surface or "chat").lower())
    now = _time.time()
    if _PRICE_CACHE_EXP.get(key, 0) > now and key in _PRICE_CACHE:
        return _PRICE_CACHE[key]
    try:
        row = query_db(
            "SELECT * FROM model_prices "
            "WHERE LOWER(provider) = %s AND model = %s AND LOWER(surface) = %s "
            "  AND active = TRUE LIMIT 1",
            (key[0], key[1], key[2]), fetchone=True,
        )
    except Exception as e:
        _capture(e)
        print(f"[cost] price lookup failed for {key}: {e}")
        row = None
    _PRICE_CACHE[key] = row
    _PRICE_CACHE_EXP[key] = now + _PRICE_CACHE_TTL_SEC
    return row


# --- Ledger writes (never raise) ------------------------------------------
def record_chat_cost(*, tenant_id=None, session_id="", visitor_id="",
                     surface="visitor_chat", provider="", model="",
                     prompt_tokens=0, completion_tokens=0,
                     total_tokens=None, usage_known=True):
    """Write one api_cost_events row with stamped unit prices. NEVER raises."""
    try:
        tid = tenant_id if tenant_id is not None else current_tenant_id()
        prompt = int(prompt_tokens or 0)
        completion = int(completion_tokens or 0)
        total = int(total_tokens) if total_tokens is not None else (prompt + completion)
        price_row = get_model_price(provider, model, "chat")
        unit_in = unit_out = cost = None
        if price_row:
            unit_in = price_row.get("input_price_per_million_tokens")
            unit_out = price_row.get("output_price_per_million_tokens")
        if (usage_known and (prompt > 0 or completion > 0)
                and unit_in is not None and unit_out is not None):
            cost = (prompt * _to_float(unit_in) +
                    completion * _to_float(unit_out)) / 1_000_000.0
        execute_db(
            "INSERT INTO api_cost_events "
            "  (tenant_id, session_id, visitor_id, surface, provider, model, "
            "   prompt_tokens, completion_tokens, total_tokens, "
            "   unit_input_price_usd, unit_output_price_usd, cost_usd) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (tid, (session_id or "")[:100], (visitor_id or "")[:100],
             (surface or "")[:40], (provider or "")[:40], (model or "")[:120],
             prompt, completion, total, unit_in, unit_out, cost),
        )
        _async_warn_check(tid)
    except Exception as e:
        _capture(e)
        print(f"[cost] record_chat_cost failed: {e}")


def record_chat_cost_from_response(response, *, surface="other", provider="openai",
                                   model="", session_id="", visitor_id=""):
    """Pull .usage off a non-streaming response and write a cost row."""
    try:
        u = getattr(response, "usage", None)
        prompt = int(getattr(u, "prompt_tokens", 0) or 0) if u else 0
        completion = int(getattr(u, "completion_tokens", 0) or 0) if u else 0
        total = int(getattr(u, "total_tokens", prompt + completion) or 0) if u else 0
        record_chat_cost(
            session_id=session_id, visitor_id=visitor_id, surface=surface,
            provider=provider, model=model or getattr(response, "model", "") or "",
            prompt_tokens=prompt, completion_tokens=completion,
            total_tokens=total, usage_known=bool(u),
        )
    except Exception as e:
        _capture(e)
        print(f"[cost] record_chat_cost_from_response failed: {e}")


def record_voice_cost(*, tenant_id=None, session_id="", surface="voice_tts",
                      provider="", model="", feature_type="", voice_id="",
                      char_count=0, audio_seconds=0):
    """Write one voice_cost_events row. NEVER raises."""
    try:
        tid = tenant_id if tenant_id is not None else current_tenant_id()
        chars = int(char_count or 0)
        secs = _to_float(audio_seconds, 0.0)
        price_row = get_model_price(provider, model,
                                    "stt" if surface == "voice_stt" else "tts")
        unit_tts = unit_stt = cost = None
        if price_row:
            unit_tts = price_row.get("tts_price_per_million_chars")
            unit_stt = price_row.get("stt_price_per_minute")
        ft_lower = (feature_type or "").lower()
        if ft_lower.startswith("tts_cached") or ft_lower == "intro_play":
            cost = 0.0
        elif chars > 0 and unit_tts is not None:
            cost = chars * _to_float(unit_tts) / 1_000_000.0
        elif secs > 0 and unit_stt is not None:
            cost = (secs / 60.0) * _to_float(unit_stt)
        execute_db(
            "INSERT INTO voice_cost_events "
            "  (tenant_id, session_id, surface, provider, model, feature_type, "
            "   voice_id, char_count, audio_seconds, unit_tts_price_usd, "
            "   unit_stt_price_usd, cost_usd) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (tid, (session_id or "")[:100], (surface or "")[:40],
             (provider or "")[:40], (model or "")[:120], (feature_type or "")[:40],
             (voice_id or "")[:200], chars, secs, unit_tts, unit_stt, cost),
        )
        _async_warn_check(tid)
    except Exception as e:
        _capture(e)
        print(f"[cost] record_voice_cost failed: {e}")


def record_sms_cost(*, tenant_id=None, surface="sms_outbound", provider="twilio",
                    to_number="", message_sid="", segments=None):
    """Write one sms_cost_events row (deduped by message_sid). NEVER raises."""
    try:
        tid = tenant_id if tenant_id is not None else current_tenant_id()
        seg_int = None
        try:
            if segments is not None and int(segments) > 0:
                seg_int = int(segments)
        except (TypeError, ValueError):
            seg_int = None
        price_row = get_model_price(provider, "sms-us", "sms")
        unit = price_row.get("sms_price_per_segment") if price_row else None
        cost = (seg_int * _to_float(unit)) if (seg_int is not None and unit is not None) else None
        execute_db(
            "INSERT INTO sms_cost_events "
            "  (tenant_id, surface, provider, to_number, message_sid, "
            "   segments, unit_sms_price_usd, cost_usd) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (tenant_id, message_sid) WHERE message_sid <> '' DO NOTHING",
            (tid, (surface or "")[:40], (provider or "")[:40],
             (to_number or "")[:40], (message_sid or "")[:80], seg_int, unit, cost),
        )
        _async_warn_check(tid)
    except Exception as e:
        _capture(e)
        print(f"[cost] record_sms_cost failed: {e}")


# --- Spend + caps ---------------------------------------------------------
def compute_mtd_spend(tenant_id=None):
    """Sum the three ledgers for the current month. All floats, never None."""
    tid = tenant_id if tenant_id is not None else current_tenant_id()
    out = {"chat_usd": 0.0, "voice_usd": 0.0, "sms_usd": 0.0, "total_usd": 0.0}
    try:
        for table, key in (("api_cost_events", "chat_usd"),
                           ("voice_cost_events", "voice_usd"),
                           ("sms_cost_events", "sms_usd")):
            r = query_db(
                f"SELECT COALESCE(SUM(cost_usd), 0) AS s FROM {table} "
                "WHERE tenant_id = %s AND created_at >= DATE_TRUNC('month', NOW())",
                (tid,), fetchone=True)
            out[key] = _to_float((r or {}).get("s"))
        out["total_usd"] = out["chat_usd"] + out["voice_usd"] + out["sms_usd"]
    except Exception as e:
        _capture(e)
        print(f"[cost] compute_mtd_spend failed: {e}")
    return out


def get_tenant_cost_cap(tenant_id=None):
    """Read the tenant_cost_caps row, with sane defaults if no row exists."""
    tid = tenant_id if tenant_id is not None else current_tenant_id()
    try:
        row = query_db("SELECT * FROM tenant_cost_caps WHERE tenant_id = %s",
                       (tid,), fetchone=True)
        if row:
            return row
    except Exception as e:
        _capture(e)
        print(f"[cost] get_tenant_cost_cap failed: {e}")
    return {
        "tenant_id": tid, "monthly_cap_usd": None, "warn_at_percent": 80,
        "cap_behavior": "alert_only", "alert_email": "", "digest_email": "",
        "digest_send_hour_utc": 9, "last_warned_period": "", "last_capped_period": "",
    }


def enforce_cost_cap(surface="chat"):
    """HTTP-path cap check. Returns None to proceed, or a (response, status)
    tuple to short-circuit. Sets ``g._cost_throttled`` in throttle mode."""
    from flask import jsonify, g  # local import: cost.py is import-safe w/o flask ctx
    if not tenant_has_feature("cost_dashboard"):
        return None
    cap_row = get_tenant_cost_cap()
    behavior = (cap_row.get("cap_behavior") or "alert_only").lower()
    if behavior == "alert_only":
        return None
    cap = cap_row.get("monthly_cap_usd")
    if cap is None:
        return None
    spend = compute_mtd_spend().get("total_usd", 0.0)
    if spend < _to_float(cap):
        return None
    if behavior == "throttle":
        try:
            g._cost_throttled = True
            g._cost_throttled_reason = {
                "spent_usd": round(spend, 4), "cap_usd": _to_float(cap),
                "surface": surface,
            }
        except Exception as e:
            _capture(e)
        return None
    msg = (f"Monthly AI spend cap reached ({spend:.2f} of {_to_float(cap):.2f} USD). "
           "Service resumes on the 1st of next month, or raise the cap in "
           "Admin → Cost.")
    return jsonify({"error": "cap_reached", "message": msg,
                    "spent": round(spend, 4), "cap": _to_float(cap)}), 402


def is_cost_throttled():
    """True if enforce_cost_cap flagged this request throttle-degraded."""
    try:
        from flask import g
        return bool(getattr(g, "_cost_throttled", False))
    except Exception:
        return False


def cost_cap_blocks_send(surface="sms_outbound", tenant_id=None):
    """Background-job cap check. True ONLY for strict_block over cap. Fail-open."""
    try:
        if not tenant_has_feature("cost_dashboard", tenant_id=tenant_id):
            return False
        cap_row = get_tenant_cost_cap(tenant_id)
        if (cap_row.get("cap_behavior") or "alert_only").lower() != "strict_block":
            return False
        cap = cap_row.get("monthly_cap_usd")
        if cap is None:
            return False
        return compute_mtd_spend(tenant_id).get("total_usd", 0.0) >= _to_float(cap)
    except Exception as e:
        _capture(e)
        print(f"[cost] cost_cap_blocks_send failed: {e}")
        return False


# Optional email sender injected by create_app() once messaging is wired (M3/M5).
_warn_email_sender = None


def set_warn_email_sender(fn):
    """Inject a ``fn(to_email, subject, html)`` used by the warn-line alert."""
    global _warn_email_sender
    _warn_email_sender = fn


def weekly_digest_tick():
    """Scheduler tick: once per ISO-week per tenant, send a 'what your AI did this
    week' email. Idempotent via weekly_digest_sends (tenant_id, week_start). Only
    fires Mon 09:00–10:00 UTC to avoid mid-week sends. Best-effort."""
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    if now.weekday() != 0 or now.hour != 9:   # Monday, 09:00–09:59 UTC
        return
    if not tenant_has_feature("weekly_digest"):
        return
    week_start = (now - timedelta(days=now.weekday())).date()
    tid = current_tenant_id()
    try:
        claimed = execute_db(
            "INSERT INTO weekly_digest_sends (tenant_id, week_start) VALUES (%s,%s) "
            "ON CONFLICT (tenant_id, week_start) DO NOTHING RETURNING id", (tid, week_start))
        if not claimed:
            return                              # already sent this week
        mtd = compute_mtd_spend(tid)
        cap = get_tenant_cost_cap(tid)
        to_email = (cap.get("digest_email") or cap.get("alert_email") or "").strip()
        if to_email and _warn_email_sender is not None:
            html = (f"<h2>What your AI did this week</h2>"
                    f"<p>Month-to-date spend ${mtd['total_usd']:.2f} "
                    f"(chat ${mtd['chat_usd']:.2f}, voice ${mtd['voice_usd']:.2f}, "
                    f"sms ${mtd['sms_usd']:.2f}).</p>")
            _warn_email_sender(to_email, "Your AI — weekly digest", html)
    except Exception as e:
        _capture(e)
        print(f"[cost] weekly_digest_tick failed: {e}")


def _async_warn_check(tenant_id):
    """Fire-and-forget: on first crossing of warn-at-percent this period, record
    an idempotent cost_alerts row (and email if a sender is wired). Never raises."""
    def _run():
        try:
            cap_row = get_tenant_cost_cap(tenant_id)
            cap = cap_row.get("monthly_cap_usd")
            if cap is None:
                return
            cap_f = _to_float(cap)
            if cap_f <= 0:
                return
            warn_pct = int(cap_row.get("warn_at_percent") or 80)
            spend = compute_mtd_spend(tenant_id).get("total_usd", 0.0)
            if spend < (cap_f * warn_pct / 100.0):
                return
            period = _current_period()
            # Idempotent: (tenant_id, period, kind) UNIQUE → one alert per period.
            inserted = execute_db(
                "INSERT INTO cost_alerts (tenant_id, period, kind) "
                "VALUES (%s, %s, 'warn') "
                "ON CONFLICT (tenant_id, period, kind) DO NOTHING RETURNING id",
                (tenant_id, period),
            )
            if inserted and _warn_email_sender is not None:
                to_email = (cap_row.get("alert_email") or "").strip()
                if to_email:
                    _warn_email_sender(
                        to_email,
                        "AI spend warning",
                        f"<p>Month-to-date AI spend is ${spend:.2f} of your "
                        f"${cap_f:.2f} cap ({warn_pct}% threshold crossed).</p>",
                    )
        except Exception as e:
            _capture(e)
            print(f"[cost] _async_warn_check failed: {e}")

    try:
        threading.Thread(target=_run, daemon=True).start()
    except Exception:
        _run()
