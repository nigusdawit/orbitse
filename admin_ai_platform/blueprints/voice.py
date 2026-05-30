"""
admin_ai_platform.blueprints.voice
==================================

Voice subsystem — independent port of the app.py voice endpoints (~28040-28560),
adapted to a self-contained **local-filesystem MP3 cache** under
``UPLOADS_DIR/voice`` (served by the media blueprint at ``/uploads/voice/<f>``)
instead of the original pluggable storage abstraction.

Endpoints:
  * ``GET  /api/voice/settings``               public toggles + provider hints
  * ``GET  /api/voice/intro``                  UTM/referrer-matched welcome audio
  * ``POST /api/voice/tts/stream/prepare``     handshake step 1 (cache hit URL or token)
  * ``GET  /api/voice/tts/stream/consume``     handshake step 2 (pipe + tee to cache)
  * ``POST /api/voice/stt``                    Whisper STT (premium)

(The legacy non-streaming ``POST /api/voice/tts`` + admin voice-sample/intro
management endpoints land with the Voice admin tab in a later milestone; the
streaming prepare/consume pair above is what the widget uses.)

Streaming TTS keeps the synthesized text out of the URL the browser sees (a
one-shot opaque token), caches by ``(provider, model, voice, text)`` content
hash so repeats are free, and enforces a per-IP daily character cap. Fails open
when keys/flags are missing (feature disables, never crashes).
"""

from __future__ import annotations

import hashlib
import io
import os
import threading
import time
import secrets
from datetime import datetime

import httpx
from flask import Blueprint, request, jsonify, Response, stream_with_context, send_file

from .. import config, llm
from ..db import query_db, execute_db
from ..auth import admin_required
from ..cost import record_voice_cost, enforce_cost_cap, is_cost_throttled

bp = Blueprint("voice", __name__)

ALLOWED_TTS_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
ALLOWED_TTS_MODELS = {"tts-1", "tts-1-hd"}
STT_DAILY_REQUESTS_PER_IP = 100

# In-process per-IP budgets + one-shot stream tokens (single-worker scope; a
# multi-worker central deployment would back these with Redis/Postgres — noted
# in PLAN.md security section).
_tts_ip_budget: dict = {}
_stt_ip_budget: dict = {}
_TTS_STREAM_TOKENS: dict = {}
_TTS_TOKENS_LOCK = threading.Lock()
_TOKEN_TTL_SEC = 60


# --------------------------------------------------------------------------
# Cache + budget + token helpers
# --------------------------------------------------------------------------
def _voice_dir() -> str:
    d = os.path.join(os.path.abspath(config.UPLOADS_DIR), "voice")
    os.makedirs(d, exist_ok=True)
    return d


def _cache_filename(text, voice_id, model) -> str:
    key = f"{model}|{voice_id}|{text}".encode("utf-8")
    return f"{hashlib.sha1(key).hexdigest()}.mp3"


def _cache_path(filename) -> str:
    return os.path.join(_voice_dir(), filename)


def _cache_exists(filename) -> bool:
    return os.path.isfile(_cache_path(filename))


def _check_tts_ip_budget(client_ip, char_count) -> bool:
    today = datetime.now().strftime("%Y-%m-%d")
    entry = _tts_ip_budget.get(client_ip)
    if not entry or entry[0] != today:
        entry = (today, 0)
    if entry[1] + char_count > config.VOICE_DAILY_CHAR_CAP:
        return False
    _tts_ip_budget[client_ip] = (today, entry[1] + char_count)
    return True


def _put_token(payload) -> str:
    token = secrets.token_urlsafe(24)
    payload["expires_at"] = time.time() + _TOKEN_TTL_SEC
    with _TTS_TOKENS_LOCK:
        _TTS_STREAM_TOKENS[token] = payload
    return token


def _consume_token(token):
    if not token:
        return None
    with _TTS_TOKENS_LOCK:
        payload = _TTS_STREAM_TOKENS.pop(token, None)
    if not payload or payload["expires_at"] < time.time():
        return None
    return payload


def _log_voice_usage(feature_type, char_count=0, voice_id="", session_id="",
                     intro_id=None):
    try:
        execute_db(
            "INSERT INTO voice_usage_log (session_id, feature_type, char_count, "
            " voice_id, intro_id) VALUES (%s,%s,%s,%s,%s)",
            (session_id or "", feature_type, char_count, voice_id, intro_id),
        )
    except Exception as e:
        print(f"[voice] usage log error: {e}")


def _settings():
    return query_db("SELECT * FROM voice_settings WHERE id = 1", fetchone=True)


def _client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or "unknown"


# --------------------------------------------------------------------------
# TTS synthesis generators (tee provider bytes to the FS cache)
# --------------------------------------------------------------------------
def _stream_tts_openai(text, voice_id, model, filename):
    if llm.openai_direct_client is None:
        raise RuntimeError("OPENAI_API_KEY not configured — required for OpenAI TTS")
    ctx = llm.openai_direct_client.audio.speech.with_streaming_response.create(
        model=model, voice=voice_id, input=text, response_format="mp3")

    def gen():
        buf = io.BytesIO()
        with ctx as response:
            for chunk in response.iter_bytes(chunk_size=4096):
                if chunk:
                    buf.write(chunk)
                    yield chunk
        _write_cache(filename, buf.getvalue())
    return gen()


def _stream_tts_elevenlabs(text, voice_id, model, filename):
    if not config.ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY not configured")
    if not voice_id:
        raise RuntimeError("ElevenLabs voice_id is empty")
    url = f"{config.ELEVENLABS_API_BASE}/text-to-speech/{voice_id}/stream"
    headers = {"xi-api-key": config.ELEVENLABS_API_KEY, "accept": "audio/mpeg",
               "content-type": "application/json"}
    body = {"text": text, "model_id": model or "eleven_turbo_v2_5",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75,
                               "style": 0.0, "use_speaker_boost": True}}

    def gen():
        buf = io.BytesIO()
        with httpx.stream("POST", url, headers=headers, json=body, timeout=60.0) as r:
            if r.status_code != 200:
                raise RuntimeError(f"ElevenLabs API error {r.status_code}")
            for chunk in r.iter_bytes():
                if chunk:
                    buf.write(chunk)
                    yield chunk
        _write_cache(filename, buf.getvalue())
    return gen()


def _write_cache(filename, data):
    """Atomically promote a completed MP3 buffer to the cache (best-effort)."""
    try:
        tmp = _cache_path(filename) + f".{os.getpid()}.part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, _cache_path(filename))
    except Exception as e:
        print(f"[voice] cache write failed (playback unaffected): {e}")


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@bp.route("/api/voice/settings", methods=["GET"])
def voice_settings():
    s = _settings()
    if not s:
        return jsonify({"enabled_intros": False, "enabled_visitor_voice": False,
                        "enabled_ai_voice": False, "default_voice": "alloy",
                        "autoplay_strategy": "gesture", "tts_provider": "openai",
                        "stt_provider": "webspeech"})
    return jsonify({
        "enabled_intros": s.get("enabled_intros", False),
        "enabled_visitor_voice": s.get("enabled_visitor_voice", False),
        "enabled_ai_voice": s.get("enabled_ai_voice", False),
        "default_voice": s.get("default_voice", "alloy"),
        "autoplay_strategy": s.get("autoplay_strategy", "gesture"),
        "tts_provider": s.get("tts_provider", "openai"),
        "stt_provider": s.get("stt_provider", "webspeech"),
    })


@bp.route("/api/voice/intro", methods=["GET"])
def voice_intro():
    s = _settings()
    if not s or not s.get("enabled_intros"):
        return jsonify({"intro": None})
    utm_source = (request.args.get("utm_source") or "").strip().lower()
    utm_medium = (request.args.get("utm_medium") or "").strip().lower()
    utm_campaign = (request.args.get("utm_campaign") or "").strip().lower()
    referrer = (request.args.get("referrer") or "").strip().lower()
    session_id = (request.args.get("session_id") or "").strip()
    intros = query_db(
        "SELECT * FROM voice_intros WHERE enabled = true AND audio_url <> '' "
        "ORDER BY priority DESC, id ASC") or []
    chosen = None
    for it in intros:
        if (it.get("utm_source") or "").strip().lower() and (it["utm_source"]).strip().lower() != utm_source:
            continue
        if (it.get("utm_medium") or "").strip().lower() and (it["utm_medium"]).strip().lower() != utm_medium:
            continue
        if (it.get("utm_campaign") or "").strip().lower() and (it["utm_campaign"]).strip().lower() != utm_campaign:
            continue
        ref = (it.get("referrer_match") or "").strip().lower()
        if ref and ref not in referrer:
            continue
        chosen = it
        break
    if not chosen:
        return jsonify({"intro": None})
    try:
        execute_db("UPDATE voice_intros SET play_count = play_count + 1 WHERE id = %s",
                   (chosen["id"],))
    except Exception:
        pass
    _log_voice_usage("intro_play", len(chosen.get("message_text") or ""),
                     chosen.get("voice_id") or "", session_id, chosen["id"])
    return jsonify({"intro": {
        "id": chosen["id"], "name": chosen.get("name") or "",
        "audio_url": chosen.get("audio_url") or "",
        "message_text": chosen.get("message_text") or "",
        "voice_id": chosen.get("voice_id") or ""}})


def _resolve_tts_provider(s, body):
    """Return (provider, voice, model) or raises ValueError(message, status)."""
    provider = (s.get("tts_provider") or "openai").lower()
    if is_cost_throttled() and provider == "elevenlabs":
        provider = "openai"
    if provider == "elevenlabs":
        if not s.get("premium_enabled"):
            raise ValueError(("Premium TTS providers are disabled", 403))
        voice = (s.get("elevenlabs_voice_id") or "").strip()
        model = (s.get("elevenlabs_model") or "eleven_turbo_v2_5").strip()
        if not voice:
            raise ValueError(("ElevenLabs voice not configured", 503))
    else:
        provider = "openai"
        voice = (body.get("voice") or s.get("default_voice") or "alloy").strip()
        if voice not in ALLOWED_TTS_VOICES:
            voice = "alloy"
        model = (s.get("tts_model") or "tts-1").strip()
        if model not in ALLOWED_TTS_MODELS:
            model = "tts-1"
    return provider, voice, model


@bp.route("/api/voice/tts/stream/prepare", methods=["POST"])
def tts_stream_prepare():
    s = _settings()
    if not s or not s.get("enabled_ai_voice"):
        return jsonify({"error": "AI voice is disabled"}), 403
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    session_id = (body.get("session_id") or "").strip()
    if not text:
        return jsonify({"error": "Missing text"}), 400
    if len(text) > config.TTS_MAX_CHARS:
        text = text[:config.TTS_MAX_CHARS]
    capped = enforce_cost_cap("voice_tts")
    if capped is not None:
        return capped
    try:
        provider, voice, model = _resolve_tts_provider(s, body)
    except ValueError as ve:
        msg, status = ve.args[0]
        return jsonify({"error": msg}), status

    filename = _cache_filename(text, voice, model)
    if _cache_exists(filename):
        _log_voice_usage("tts_cached", len(text), voice, session_id)
        return jsonify({"audio_url": f"/uploads/voice/{filename}",
                        "cached": True, "provider": provider})

    if not _check_tts_ip_budget(_client_ip(), len(text)):
        return jsonify({"error": "Daily voice quota exceeded"}), 429
    token = _put_token({"text": text, "voice": voice, "model": model,
                        "provider": provider, "filename": filename,
                        "session_id": session_id})
    return jsonify({"stream_url": f"/api/voice/tts/stream/consume?token={token}",
                    "cached": False, "provider": provider})


@bp.route("/api/voice/tts/stream/consume", methods=["GET"])
def tts_stream_consume():
    capped = enforce_cost_cap("voice_tts")
    if capped is not None:
        return capped
    payload = _consume_token(request.args.get("token"))
    if not payload:
        return Response("Invalid or expired token", status=410, mimetype="text/plain")
    text, voice, model = payload["text"], payload["voice"], payload["model"]
    provider, filename, session_id = payload["provider"], payload["filename"], payload["session_id"]

    if _cache_exists(filename):  # another client may have generated it
        _log_voice_usage("tts_cached", len(text), voice, session_id)
        return send_file(_cache_path(filename), mimetype="audio/mpeg")

    try:
        if provider == "elevenlabs":
            byte_iter = _stream_tts_elevenlabs(text, voice, model, filename)
        else:
            byte_iter = _stream_tts_openai(text, voice, model, filename)
    except RuntimeError as e:
        return Response(str(e), status=503, mimetype="text/plain")
    except Exception as e:
        print(f"[voice] TTS open error: {e}")
        return Response("TTS generation failed", status=500, mimetype="text/plain")

    record_voice_cost(session_id=session_id, surface="voice_tts", provider=provider,
                      model=model, feature_type=f"tts_generate_{provider}",
                      voice_id=voice, char_count=len(text))
    _log_voice_usage(f"tts_generate_{provider}", len(text), voice, session_id)
    return Response(stream_with_context(byte_iter), mimetype="audio/mpeg",
                    headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no",
                             "X-TTS-Provider": provider})


@bp.route("/api/voice/tts", methods=["POST"])
def tts_legacy():
    """Legacy non-streaming TTS: synthesize the whole clip, cache it, and return
    its URL in one call. The streaming prepare/consume handshake is preferred for
    latency, but some clients want a single request → single URL. Same caps +
    per-IP daily budget as the streaming path."""
    s = _settings()
    if not s or not s.get("enabled_ai_voice"):
        return jsonify({"error": "AI voice is disabled"}), 403
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    session_id = (body.get("session_id") or "").strip()
    if not text:
        return jsonify({"error": "Missing text"}), 400
    if len(text) > config.TTS_MAX_CHARS:
        text = text[:config.TTS_MAX_CHARS]
    capped = enforce_cost_cap("voice_tts")
    if capped is not None:
        return capped
    try:
        provider, voice, model = _resolve_tts_provider(s, body)
    except ValueError as ve:
        msg, status = ve.args[0]
        return jsonify({"error": msg}), status

    filename = _cache_filename(text, voice, model)
    if _cache_exists(filename):
        _log_voice_usage("tts_cached", len(text), voice, session_id)
        return jsonify({"audio_url": f"/uploads/voice/{filename}", "cached": True,
                        "provider": provider})
    if not _check_tts_ip_budget(_client_ip(), len(text)):
        return jsonify({"error": "Daily voice quota exceeded"}), 429
    try:
        url = _synthesize_to_cache(text, voice, model, provider)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        print(f"[voice] legacy tts failed: {e}")
        return jsonify({"error": "TTS generation failed"}), 502
    record_voice_cost(session_id=session_id, surface="voice_tts", provider=provider,
                      model=model, feature_type=f"tts_generate_{provider}",
                      voice_id=voice, char_count=len(text))
    _log_voice_usage(f"tts_generate_{provider}", len(text), voice, session_id)
    return jsonify({"audio_url": url, "cached": False, "provider": provider}), 201


@bp.route("/api/voice/stt", methods=["POST"])
def voice_stt():
    s = _settings()
    if not s or not s.get("enabled_visitor_voice"):
        return jsonify({"error": "Visitor voice is disabled"}), 403
    if (s.get("stt_provider") or "webspeech") != "whisper":
        return jsonify({"error": "Whisper STT is not the configured provider"}), 403
    if not s.get("premium_enabled"):
        return jsonify({"error": "Premium STT is disabled"}), 403
    if llm.openai_direct_client is None:
        return jsonify({"error": "OPENAI_API_KEY not configured"}), 503
    capped = enforce_cost_cap("voice_stt")
    if capped is not None:
        return capped

    ip = _client_ip()
    today = datetime.now().strftime("%Y-%m-%d")
    entry = _stt_ip_budget.get(ip)
    if not entry or entry[0] != today:
        entry = (today, 0)
    if entry[1] >= STT_DAILY_REQUESTS_PER_IP:
        return jsonify({"error": "Daily voice-input quota exceeded"}), 429
    _stt_ip_budget[ip] = (today, entry[1] + 1)

    if "audio" not in request.files:
        return jsonify({"error": "Missing audio file"}), 400
    blob = request.files["audio"].read()
    if len(blob) > 5 * 1024 * 1024:
        return jsonify({"error": "Audio file too large (max 5 MB)"}), 413
    if not blob:
        return jsonify({"error": "Empty audio file"}), 400
    session_id = (request.form.get("session_id") or "").strip()
    try:
        bio = io.BytesIO(blob)
        bio.name = request.files["audio"].filename or "audio.webm"
        result = llm.openai_direct_client.audio.transcriptions.create(
            model="whisper-1", file=bio, response_format="verbose_json")
        text = (getattr(result, "text", None) or "").strip()
        try:
            duration = float(getattr(result, "duration", 0) or 0)
        except (TypeError, ValueError):
            duration = 0.0
    except Exception as e:
        print(f"[voice] Whisper STT error: {e}")
        return jsonify({"error": "Transcription failed"}), 500
    record_voice_cost(session_id=session_id, surface="voice_stt", provider="openai",
                      model="whisper-1", feature_type="stt_whisper",
                      char_count=len(text), audio_seconds=duration)
    _log_voice_usage("stt_whisper", len(text), "", session_id)
    return jsonify({"text": text})


# ==========================================================================
# Voice admin (M14): settings, intros CRUD + audio pre-render, sample preview,
# ElevenLabs voice list, usage stats. All @admin_required.
# ==========================================================================
_VOICE_SETTINGS_FIELDS = (
    "enabled_intros", "enabled_visitor_voice", "enabled_ai_voice", "default_voice",
    "tts_model", "autoplay_strategy", "tts_provider", "stt_provider", "premium_enabled",
    "elevenlabs_voice_id", "elevenlabs_model")


@bp.route("/admin/api/voice/settings", methods=["GET"])
@admin_required
def admin_get_voice_settings():
    return jsonify(_settings() or {})


@bp.route("/admin/api/voice/settings", methods=["PUT"])
@admin_required
def admin_put_voice_settings():
    d = request.get_json() or {}
    execute_db("INSERT INTO voice_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    sets, vals = [], []
    for k in _VOICE_SETTINGS_FIELDS:
        if k in d:
            sets.append(f"{k}=%s")
            vals.append(d[k])
    if not sets:
        return jsonify({"error": "no fields"}), 400
    sets.append("updated_at=NOW()")
    row = execute_db(f"UPDATE voice_settings SET {', '.join(sets)} WHERE id=1 RETURNING *",
                     tuple(vals))
    return jsonify(row)


@bp.route("/admin/api/voice/intros", methods=["GET"])
@admin_required
def admin_list_intros():
    return jsonify({"intros": query_db(
        "SELECT * FROM voice_intros ORDER BY priority DESC, id") or []})


_INTRO_FIELDS = ("name", "message_text", "voice_id", "utm_source", "utm_medium",
                 "utm_campaign", "referrer_match", "priority", "enabled", "audio_url")


@bp.route("/admin/api/voice/intros", methods=["POST"])
@admin_required
def admin_create_intro():
    d = request.get_json() or {}
    row = execute_db(
        "INSERT INTO voice_intros (name, message_text, voice_id, utm_source, utm_medium, "
        " utm_campaign, referrer_match, priority, enabled) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (d.get("name", ""), d.get("message_text", ""), d.get("voice_id", "alloy"),
         d.get("utm_source", ""), d.get("utm_medium", ""), d.get("utm_campaign", ""),
         d.get("referrer_match", ""), int(d.get("priority", 0) or 0),
         bool(d.get("enabled", True))))
    return jsonify(row), 201


@bp.route("/admin/api/voice/intros/<int:iid>", methods=["PUT"])
@admin_required
def admin_update_intro(iid):
    d = request.get_json() or {}
    sets, vals = [], []
    for k in _INTRO_FIELDS:
        if k in d:
            sets.append(f"{k}=%s")
            vals.append(d[k])
    if not sets:
        return jsonify({"error": "no fields"}), 400
    vals.append(iid)
    row = execute_db(f"UPDATE voice_intros SET {', '.join(sets)} WHERE id=%s RETURNING *",
                     tuple(vals))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/voice/intros/<int:iid>", methods=["DELETE"])
@admin_required
def admin_delete_intro(iid):
    execute_db("DELETE FROM voice_intros WHERE id=%s", (iid,))
    return jsonify({"success": True})


def _synthesize_to_cache(text, voice, model, provider):
    """Generate the full MP3 for ``text`` and write it to the FS cache, returning
    the public URL. Used by intro pre-render + sample preview. Raises on failure
    (caller maps to a 503)."""
    filename = _cache_filename(text, voice, model)
    if not _cache_exists(filename):
        if provider == "elevenlabs":
            gen = _stream_tts_elevenlabs(text, voice, model, filename)
        else:
            gen = _stream_tts_openai(text, voice, model, filename)
        for _ in gen:  # drain the generator; it tees to the cache on completion
            pass
    return f"/uploads/voice/{filename}"


@bp.route("/admin/api/voice/intros/<int:iid>/generate", methods=["POST"])
@admin_required
def admin_generate_intro_audio(iid):
    """Pre-render an intro's audio so the public /api/voice/intro can serve a
    cached URL with zero latency. Requires a TTS key for the chosen provider."""
    intro = query_db("SELECT * FROM voice_intros WHERE id=%s", (iid,), fetchone=True)
    if not intro:
        return jsonify({"error": "Not found"}), 404
    text = (intro.get("message_text") or "").strip()
    if not text:
        return jsonify({"error": "intro has no message_text"}), 400
    s = _settings() or {}
    provider = (s.get("tts_provider") or "openai").lower()
    voice = (intro.get("voice_id") or s.get("default_voice") or "alloy").strip()
    model = (s.get("elevenlabs_model") if provider == "elevenlabs"
             else s.get("tts_model")) or ("eleven_turbo_v2_5" if provider == "elevenlabs"
                                          else "tts-1")
    try:
        url = _synthesize_to_cache(text, voice, model, provider)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        print(f"[voice] intro generate failed: {e}")
        return jsonify({"error": "audio generation failed"}), 502
    row = execute_db("UPDATE voice_intros SET audio_url=%s WHERE id=%s RETURNING *", (url, iid))
    return jsonify(row)


@bp.route("/admin/api/voice/sample", methods=["POST"])
@admin_required
def admin_voice_sample():
    """Generate a short preview clip for a voice so the admin can audition it."""
    d = request.get_json() or {}
    text = (d.get("text") or "Hello! This is a preview of the selected voice.").strip()[:200]
    s = _settings() or {}
    provider = (d.get("provider") or s.get("tts_provider") or "openai").lower()
    if provider == "elevenlabs":
        voice = (d.get("voice") or s.get("elevenlabs_voice_id") or "").strip()
        model = s.get("elevenlabs_model") or "eleven_turbo_v2_5"
        if not voice:
            return jsonify({"error": "ElevenLabs voice not configured"}), 503
    else:
        provider = "openai"
        voice = (d.get("voice") or s.get("default_voice") or "alloy").strip()
        if voice not in ALLOWED_TTS_VOICES:
            voice = "alloy"
        model = s.get("tts_model") or "tts-1"
    try:
        url = _synthesize_to_cache(text, voice, model, provider)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        print(f"[voice] sample failed: {e}")
        return jsonify({"error": "audio generation failed"}), 502
    return jsonify({"audio_url": url, "provider": provider, "voice": voice})


@bp.route("/admin/api/voice/elevenlabs-voices", methods=["GET"])
@admin_required
def admin_elevenlabs_voices():
    """Live ElevenLabs voice list for the settings dropdown. Fail-closed (empty
    list + reason) when the key is missing or the API errors."""
    if not config.ELEVENLABS_API_KEY:
        return jsonify({"voices": [], "error": "ELEVENLABS_API_KEY not configured"}), 200
    try:
        r = httpx.get(f"{config.ELEVENLABS_API_BASE}/voices",
                      headers={"xi-api-key": config.ELEVENLABS_API_KEY}, timeout=10.0)
        r.raise_for_status()
        voices = [{"voice_id": v.get("voice_id"), "name": v.get("name"),
                   "category": v.get("category")} for v in (r.json().get("voices") or [])]
        return jsonify({"voices": voices})
    except Exception as e:
        return jsonify({"voices": [], "error": str(e)[:200]}), 200


@bp.route("/admin/api/voice/usage", methods=["GET"])
@admin_required
def admin_voice_usage():
    """Aggregate voice usage for the admin dashboard (counts + chars by feature,
    last 30 days, plus a recent-rows tail)."""
    by_feature = query_db(
        "SELECT feature_type, COUNT(*) AS events, COALESCE(SUM(char_count),0) AS chars "
        "FROM voice_usage_log WHERE created_at > NOW() - INTERVAL '30 days' "
        "GROUP BY feature_type ORDER BY events DESC") or []
    recent = query_db("SELECT * FROM voice_usage_log ORDER BY id DESC LIMIT 50") or []
    return jsonify({"by_feature": by_feature, "recent": recent})
