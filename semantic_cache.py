"""Semantic response cache for the visitor concierge.

Sits in front of /api/chat: embed the visitor's question, look up the
nearest past Q&A by cosine similarity, and if it's a close match
(>= the admin-tunable threshold) return the cached text immediately
WITHOUT calling the LLM.  The frontend then asks the existing
/api/voice/tts/* endpoints to speak that cached text — and because
those endpoints already key MP3s by sha256(text), the audio is reused
for free too.

So a "cache hit" saves both the LLM completion AND the ElevenLabs TTS
render — that's the whole point of the feature.

Public API (used by app.py):

    init_module(app_globals)
        Pass the app module's globals so we can grab `openai_client`,
        `query_db`, `execute_db` without a circular import.

    find_cached_response(question, threshold=None) -> dict | None
        Returns {"id", "response_text", "similarity"} on hit, None on miss.

    record_hit(cache_id, response_text)
        Bump hit_count + last_hit_at and update the chatbot_settings
        running totals.  Best-effort.

    save_to_cache(question, response_text, source_message_id=None) -> int | None
        Embed the question and INSERT a new row.  Returns row id, or
        None if PII filtering refused or the embedding call failed.

    should_cache_response(reply, has_tools, has_command, presentation_active)
        Cheap pre-flight check: skip caching when the answer was tool-
        driven, command-bearing, or contextual to a deck the visitor was
        watching.

    bump_content_version()
        Move the global content_version forward; existing rows become
        stale and the read path skips them until the admin backfills
        or new entries land.

    get_cache_settings() -> dict
        Read enable flag + threshold + version + lifetime counters.

    list_entries(limit, sort)  / get_entry_count()  / delete_entry(id)
    purge(scope)  /  backfill_from_history(limit)
        Admin-side helpers used by the dashboard routes.

The module deliberately swallows every exception inside read/write
hooks so a failing cache (DB down, embedding API down, pgvector glitch)
NEVER breaks visitor chat — we just fall through to the live LLM.
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional

# These are populated by init_module() to avoid a circular import with app.py
# (app.py imports this module at startup; this module needs app.py's openai
# client + DB helpers).
_openai_client = None
_query_db = None
_execute_db = None


# OpenAI text-embedding-3-small: 1536-dim, ~$0.02 per 1M tokens, ~30ms p50.
# Cheapest reasonable model and dimension matches the VECTOR(1536) column.
_EMBED_MODEL = "text-embedding-3-small"
_EMBED_DIM = 1536

# Tiny in-process embedding cache keyed by exact-string hash so repeated
# identical questions in the same process don't re-hit the embedding API.
# Bounded; FIFO eviction.
_EMBED_CACHE_MAX = 512
_embed_cache: dict[str, list[float]] = {}
_embed_cache_order: list[str] = []


def init_module(openai_client: Any, query_db_fn: Any, execute_db_fn: Any) -> None:
    """Wire up the dependencies app.py owns.

    Called once at app.py import time.  Storing references rather than
    re-importing app.py here avoids a circular import (app.py -> this
    module -> app.py).
    """
    global _openai_client, _query_db, _execute_db
    _openai_client = openai_client
    _query_db = query_db_fn
    _execute_db = execute_db_fn


# ---------------------------------------------------------------------------
# PII heuristic
# ---------------------------------------------------------------------------
#
# We share cache rows GLOBALLY across visitors (per the user's product
# decision: "Global - share cache across all visitors. I'll add a
# heuristic that refuses to cache responses containing visitor PII").
# So we MUST refuse to cache any response that quotes a visitor-specific
# detail — otherwise visitor B asking "what time is my reservation?"
# could get visitor A's cached answer back.
#
# Conservative: we'd rather refuse a legit cacheable answer than ever
# leak someone's email/phone/booking.  False negatives (didn't cache a
# safe answer) cost nothing; false positives (cached a leak) are the
# whole risk of a global cache.

_RE_EMAIL = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)

# US-style + international-ish phone numbers.  Permissive; we're optimising
# for recall (catch anything that LOOKS like a phone) over precision.
_RE_PHONE = re.compile(
    r"(?:\+?\d{1,3}[\s.\-]?)?"           # optional country code
    r"\(?\d{3}\)?[\s.\-]?"               # area code
    r"\d{3}[\s.\-]?\d{4}"                # exchange + line
    r"(?:\s*(?:ext\.?|x)\s*\d+)?"        # optional extension
)

# Any standalone digit run of 4+ digits is suspect (booking IDs, order
# numbers, confirmation codes, etc.).  Yes, this also nukes legit numbers
# like "$1500" or "1998" — but for the concierge those almost always
# benefit from a fresh answer anyway (price changed?  year context?).
_RE_LONG_NUMBER = re.compile(r"(?<!\d)\d{4,}(?!\d)")

# Possessive / referential phrasing that strongly implies the answer
# is talking ABOUT this specific visitor.  Catches BOTH directions:
#   • "your booking is..."  — the AI is addressing the visitor
#   • "my booking..."       — the AI is quoting/echoing the visitor
# Either way, the answer is personalised and unsafe for a global cache.
_PERSONAL_NOUNS = (
    r"name|email|phone|booking|reservation|order|account|"
    r"deposit|confirmation|appointment|invoice|receipt|address|"
    r"card|payment|details|profile|stay|trip|itinerary|table"
)
_RE_POSSESSIVE = re.compile(
    rf"\byour\s+(?:{_PERSONAL_NOUNS})\b"
    rf"|\bmy\s+(?:{_PERSONAL_NOUNS})\b"
    rf"|\bfor\s+you,?\s+\w+\b"            # "for you, John,"
    r"|\b(?:you\s+(?:said|told|mentioned|asked|booked|ordered|signed))\b"
    r"|\b(?:as\s+you\s+mentioned|per\s+your\s+(?:request|message))\b",
    re.IGNORECASE,
)


def _contains_pii(text: str) -> Optional[str]:
    """Return the rule name that fired, or None if the text is safe to cache."""
    if not text:
        return None
    if _RE_EMAIL.search(text):
        return "email"
    if _RE_PHONE.search(text):
        return "phone"
    if _RE_LONG_NUMBER.search(text):
        return "long_number"
    if _RE_POSSESSIVE.search(text):
        return "possessive_phrasing"
    return None


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def _embed(text: str) -> Optional[list[float]]:
    """Return a 1536-dim embedding for `text`, or None on failure.

    Cheap process-local cache by exact-string match so the second
    /api/chat call from the SAME visitor (who often retypes the same
    question to test) doesn't re-hit the embedding API.
    """
    if not text or _openai_client is None:
        return None

    # Trim and lowercase for the cache key only — we still embed the
    # original casing so retrieval matches what users actually typed.
    key = (text or "").strip().lower()[:1024]
    if not key:
        return None
    if key in _embed_cache:
        return _embed_cache[key]

    try:
        resp = _openai_client.embeddings.create(
            model=_EMBED_MODEL,
            input=text,
        )
        vec = resp.data[0].embedding
    except Exception as e:  # noqa: BLE001 — never let cache outages break chat
        print(f"[semantic_cache] embed failed: {e}")
        return None

    if not isinstance(vec, list) or len(vec) != _EMBED_DIM:
        print(
            f"[semantic_cache] embed returned unexpected shape: "
            f"len={len(vec) if isinstance(vec, list) else 'N/A'}"
        )
        return None

    # FIFO evict.
    if len(_embed_cache) >= _EMBED_CACHE_MAX:
        oldest = _embed_cache_order.pop(0)
        _embed_cache.pop(oldest, None)
    _embed_cache[key] = vec
    _embed_cache_order.append(key)

    return vec


def _to_pgvector(vec: list[float]) -> str:
    """pgvector accepts a string literal like "[0.1,0.2,...]" cast to vector."""
    # Round to 6dp to keep the SQL payload reasonable (~9KB instead of 30KB
    # of full-precision floats); pgvector cosine search is unaffected by
    # that rounding at this scale.
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


# ---------------------------------------------------------------------------
# Settings (cached for ~30s so we don't query chatbot_settings on every chat)
# ---------------------------------------------------------------------------

_SETTINGS_TTL_S = 30
_settings_cache: dict[str, Any] = {}
_settings_cache_at: float = 0.0


def get_cache_settings(force_refresh: bool = False) -> dict[str, Any]:
    """Return the relevant cache tunables from chatbot_settings (id=1)."""
    global _settings_cache_at
    now = time.time()
    if (
        not force_refresh
        and _settings_cache
        and (now - _settings_cache_at) < _SETTINGS_TTL_S
    ):
        return _settings_cache

    defaults = {
        "cache_enabled": True,
        "cache_threshold": 0.93,
        "cache_content_version": 1,
        "cache_total_hits": 0,
        "cache_tokens_saved": 0,
        "cache_tts_chars_saved": 0,
    }
    if _query_db is None:
        return defaults
    try:
        row = _query_db(
            "SELECT cache_enabled, cache_threshold, cache_content_version, "
            "cache_total_hits, cache_tokens_saved, cache_tts_chars_saved "
            "FROM chatbot_settings WHERE id = 1",
            fetchone=True,
        ) or {}
    except Exception as e:  # noqa: BLE001
        print(f"[semantic_cache] settings read failed: {e}")
        return defaults

    out = dict(defaults)
    out.update({k: v for k, v in row.items() if v is not None})
    # Clamp threshold to a sane band — admin UI also clamps but defence in depth.
    try:
        out["cache_threshold"] = max(0.80, min(0.99, float(out["cache_threshold"])))
    except (TypeError, ValueError):
        out["cache_threshold"] = 0.93
    _settings_cache.clear()
    _settings_cache.update(out)
    _settings_cache_at = now
    return out


def _invalidate_settings_cache() -> None:
    global _settings_cache_at
    _settings_cache_at = 0.0


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------

def find_cached_response(
    question: str,
    threshold: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    """Return the best matching cache entry, or None.

    On hit returns {"id", "response_text", "similarity"}.  Caller is
    responsible for invoking record_hit() to bump counters; we keep
    that separate so the read can be a pure SELECT (and so callers can
    decide not to count e.g. internal probes).
    """
    if not question or _query_db is None:
        return None
    settings = get_cache_settings()
    if not settings.get("cache_enabled"):
        return None

    vec = _embed(question)
    if vec is None:
        return None

    cur_version = int(settings.get("cache_content_version") or 1)
    eff_threshold = float(threshold if threshold is not None
                          else settings.get("cache_threshold", 0.93))

    # pgvector cosine DISTANCE = 1 - cosine_similarity, so similarity is
    # 1 - distance.  We sort ASC by distance and pick the first row.
    try:
        row = _query_db(
            "SELECT id, response_text, "
            "       (1 - (query_embedding <=> %s::vector)) AS similarity "
            "FROM ai_response_cache "
            "WHERE content_version = %s "
            "ORDER BY query_embedding <=> %s::vector "
            "LIMIT 1",
            (_to_pgvector(vec), cur_version, _to_pgvector(vec)),
            fetchone=True,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[semantic_cache] lookup failed: {e}")
        return None

    if not row:
        return None
    sim = float(row.get("similarity") or 0.0)
    if sim < eff_threshold:
        return None
    return {
        "id": int(row["id"]),
        "response_text": row["response_text"],
        "similarity": sim,
    }


def record_hit(cache_id: int, response_text: str) -> None:
    """Bump hit counters + lifetime totals.  Best-effort, never raises."""
    if _execute_db is None or cache_id is None:
        return
    # Rough token estimate: ~4 chars/token for English (OpenAI's own rule
    # of thumb).  This is what the admin sees as "tokens saved".
    tokens = max(1, len(response_text or "") // 4)
    chars = len(response_text or "")
    try:
        _execute_db(
            "UPDATE ai_response_cache "
            "SET hit_count = hit_count + 1, last_hit_at = NOW() "
            "WHERE id = %s RETURNING id",
            (cache_id,),
        )
        _execute_db(
            "UPDATE chatbot_settings SET "
            "cache_total_hits = cache_total_hits + 1, "
            "cache_tokens_saved = cache_tokens_saved + %s, "
            "cache_tts_chars_saved = cache_tts_chars_saved + %s "
            "WHERE id = 1 RETURNING id",
            (tokens, chars),
        )
        _invalidate_settings_cache()
    except Exception as e:  # noqa: BLE001
        print(f"[semantic_cache] record_hit failed: {e}")


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------

# Skip caching answers shorter than this — too short almost always means
# "I'm not sure", "Sure!", "Yes.", which give zero token savings on reuse
# but pollute the index.
_MIN_CACHEABLE_REPLY_CHARS = 60


def should_cache_response(
    reply: str,
    has_tools: bool,
    has_command: bool,
    presentation_active: bool,
) -> tuple[bool, str]:
    """Pre-flight: is this answer worth caching?

    Returns (ok, reason).  Reason is logged so an operator can sanity
    check why their cache isn't growing.
    """
    if not reply or not reply.strip():
        return False, "empty_reply"
    if len(reply.strip()) < _MIN_CACHEABLE_REPLY_CHARS:
        return False, "too_short"
    if has_tools:
        # Tool-driven answers depend on live data (availability, gallery,
        # service catalogue) that changes — caching them would freeze a
        # snapshot of yesterday's calendar.
        return False, "tool_driven"
    if has_command:
        # The reply is paired with a UI action (navigate, generatePage,
        # showSlide…).  Action targets often depend on live state too.
        return False, "command_attached"
    if presentation_active:
        # Side-question during a deck — heavily contextual to the slide
        # currently on screen, would mislead a different visitor.
        return False, "presentation_context"
    rule = _contains_pii(reply)
    if rule:
        return False, f"pii:{rule}"
    return True, "ok"


def save_to_cache(
    question: str,
    response_text: str,
    source_message_id: Optional[int] = None,
) -> Optional[int]:
    """INSERT a new cache entry.  Returns row id, or None on refusal/failure."""
    if not question or not response_text or _execute_db is None:
        return None
    # Re-check PII at write time (callers usually called should_cache_response
    # first, but the guard here means nothing slips through accidentally).
    if _contains_pii(response_text):
        return None
    vec = _embed(question)
    if vec is None:
        return None
    settings = get_cache_settings()
    cur_version = int(settings.get("cache_content_version") or 1)
    try:
        # ON CONFLICT silently drops a duplicate insert when two
        # concurrent /api/chat workers race to cache the same novel
        # question (see migration 0004 for the unique index this
        # relies on).  The loser's row is discarded; the winner's row
        # is the one future lookups hit.  RETURNING id may be NULL on
        # a conflict — that's fine, the caller treats None as "saved
        # but no id" and just doesn't log the new id anywhere.
        row = _execute_db(
            "INSERT INTO ai_response_cache "
            "(query_text, query_embedding, response_text, "
            " source_message_id, content_version) "
            "VALUES (%s, %s::vector, %s, %s, %s) "
            "ON CONFLICT (query_text, content_version) DO NOTHING "
            "RETURNING id",
            (question, _to_pgvector(vec), response_text,
             source_message_id, cur_version),
        )
        return int(row["id"]) if row and row.get("id") else None
    except Exception as e:  # noqa: BLE001
        print(f"[semantic_cache] save failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Admin operations (called from /admin/api/ai-cache/* routes)
# ---------------------------------------------------------------------------

def bump_content_version() -> int:
    """Increment chatbot_settings.cache_content_version.

    Called whenever the underlying site content / system prompt changes
    in a way that could change what the AI should answer.  Existing
    cache rows are preserved (so the admin can still see their previous
    Top Questions list) but read path filters them out — nothing is
    served from a stale version.

    Returns the new version number.
    """
    if _execute_db is None:
        return 0
    try:
        row = _execute_db(
            "UPDATE chatbot_settings "
            "SET cache_content_version = COALESCE(cache_content_version, 1) + 1 "
            "WHERE id = 1 "
            "RETURNING cache_content_version",
        )
        _invalidate_settings_cache()
        return int(row["cache_content_version"]) if row else 0
    except Exception as e:  # noqa: BLE001
        print(f"[semantic_cache] bump_content_version failed: {e}")
        return 0


def list_entries(limit: int = 100, sort: str = "hits") -> list[dict[str, Any]]:
    """Return the top-N cached entries for the admin UI."""
    if _query_db is None:
        return []
    limit = max(1, min(500, int(limit)))
    settings = get_cache_settings()
    cur_version = int(settings.get("cache_content_version") or 1)
    if sort == "recent":
        order = "ORDER BY created_at DESC"
    elif sort == "stale":
        order = "ORDER BY last_hit_at ASC NULLS FIRST"
    else:
        order = "ORDER BY hit_count DESC, last_hit_at DESC NULLS LAST"
    try:
        rows = _query_db(
            f"SELECT id, query_text, response_text, hit_count, "
            f"       last_hit_at, created_at, content_version, "
            f"       (content_version = %s) AS is_current "
            f"FROM ai_response_cache "
            f"{order} "
            f"LIMIT %s",
            (cur_version, limit),
        ) or []
    except Exception as e:  # noqa: BLE001
        print(f"[semantic_cache] list_entries failed: {e}")
        return []
    return [dict(r) for r in rows]


def get_stats() -> dict[str, Any]:
    """Aggregate stats for the admin banner."""
    settings = get_cache_settings(force_refresh=True)
    out = {
        "enabled": bool(settings.get("cache_enabled")),
        "threshold": float(settings.get("cache_threshold", 0.93)),
        "content_version": int(settings.get("cache_content_version") or 1),
        "lifetime_hits": int(settings.get("cache_total_hits") or 0),
        "lifetime_tokens_saved": int(settings.get("cache_tokens_saved") or 0),
        "lifetime_tts_chars_saved": int(settings.get("cache_tts_chars_saved") or 0),
        "entries_total": 0,
        "entries_current": 0,
        "entries_stale": 0,
    }
    if _query_db is None:
        return out
    try:
        row = _query_db(
            "SELECT COUNT(*)::int AS total, "
            "       COUNT(*) FILTER (WHERE content_version = %s)::int AS current_n "
            "FROM ai_response_cache",
            (out["content_version"],),
            fetchone=True,
        ) or {}
        out["entries_total"] = int(row.get("total") or 0)
        out["entries_current"] = int(row.get("current_n") or 0)
        out["entries_stale"] = max(0, out["entries_total"] - out["entries_current"])
    except Exception as e:  # noqa: BLE001
        print(f"[semantic_cache] stats count failed: {e}")
    return out


def delete_entry(cache_id: int) -> bool:
    if _execute_db is None:
        return False
    try:
        row = _execute_db(
            "DELETE FROM ai_response_cache WHERE id = %s RETURNING id",
            (int(cache_id),),
        )
        return row is not None
    except Exception as e:  # noqa: BLE001
        print(f"[semantic_cache] delete failed: {e}")
        return False


def purge(scope: str = "stale") -> int:
    """Bulk delete.  scope='stale' drops anything not at current version;
    scope='all' empties the table."""
    if _execute_db is None:
        return 0
    settings = get_cache_settings(force_refresh=True)
    cur_version = int(settings.get("cache_content_version") or 1)
    if scope == "all":
        sql, params = ("DELETE FROM ai_response_cache RETURNING id", ())
    else:
        sql = "DELETE FROM ai_response_cache WHERE content_version <> %s RETURNING id"
        params = (cur_version,)
    try:
        # execute_db returns the FIRST row; we want a count, so use a CTE.
        rows = _query_db(
            f"WITH deleted AS ({sql}) SELECT COUNT(*)::int AS n FROM deleted",
            params,
            fetchone=True,
        )
        return int((rows or {}).get("n") or 0)
    except Exception as e:  # noqa: BLE001
        print(f"[semantic_cache] purge failed: {e}")
        return 0


def backfill_from_history(limit: int = 200) -> dict[str, int]:
    """Walk chat_messages, embed every (user → assistant) pair we don't
    already have cached, and INSERT them.

    Strategy: pull the most recent N user→assistant pairs ordered by
    conversation/created_at; for each pair, if the assistant message had
    NO tool_calls and NO command_json (indicating a clean text reply) AND
    PII filter passes, insert it.  Cheap dedup: skip if the exact-string
    user question already exists in cache (skips re-embedding).
    """
    if _query_db is None or _execute_db is None:
        return {"inserted": 0, "skipped": 0, "scanned": 0}
    limit = max(1, min(2000, int(limit)))

    # Pull recent messages in groups of 2 (user + following assistant).
    # We can't trivially window in SQL because messages from different
    # conversations interleave; do it conversation by conversation.
    try:
        convs = _query_db(
            "SELECT DISTINCT conversation_id FROM chat_messages "
            "ORDER BY conversation_id DESC LIMIT %s",
            (limit,),
        ) or []
    except Exception as e:  # noqa: BLE001
        print(f"[semantic_cache] backfill conv list failed: {e}")
        return {"inserted": 0, "skipped": 0, "scanned": 0}

    inserted = 0
    skipped = 0
    scanned = 0

    for c in convs:
        conv_id = c["conversation_id"]
        if conv_id is None:
            continue
        try:
            msgs = _query_db(
                "SELECT id, role, content, command_json, tool_calls_json "
                "FROM chat_messages WHERE conversation_id = %s "
                "ORDER BY id ASC",
                (conv_id,),
            ) or []
        except Exception:
            continue
        # Walk pairs.
        for i in range(len(msgs) - 1):
            u, a = msgs[i], msgs[i + 1]
            if (u.get("role") != "user") or (a.get("role") != "assistant"):
                continue
            scanned += 1
            user_q = (u.get("content") or "").strip()
            asst = (a.get("content") or "").strip()
            has_tools = bool(a.get("tool_calls_json"))
            has_cmd = bool(a.get("command_json"))
            ok, _reason = should_cache_response(asst, has_tools, has_cmd, False)
            if not (user_q and ok):
                skipped += 1
                continue
            # Skip if this exact user_q is already cached AT THE CURRENT
            # content_version.  The version filter matters: after the admin
            # clicks "Invalidate All", every existing row becomes stale,
            # and the operator immediately runs Backfill to repopulate
            # under the new version.  Without the version filter, dedupe
            # would skip every question whose stale row still exists,
            # leaving the cache permanently empty.
            cur_v = int(get_cache_settings().get("cache_content_version") or 1)
            try:
                existing = _query_db(
                    "SELECT id FROM ai_response_cache "
                    "WHERE query_text = %s AND content_version = %s LIMIT 1",
                    (user_q, cur_v),
                    fetchone=True,
                )
            except Exception:
                existing = None
            if existing:
                skipped += 1
                continue
            row_id = save_to_cache(user_q, asst, source_message_id=a.get("id"))
            if row_id:
                inserted += 1
            else:
                skipped += 1

    return {"inserted": inserted, "skipped": skipped, "scanned": scanned}


def set_settings(enabled: Optional[bool] = None,
                 threshold: Optional[float] = None) -> dict[str, Any]:
    """Update enable flag / threshold.  Returns the fresh settings."""
    if _execute_db is None:
        return get_cache_settings()
    if enabled is not None:
        try:
            _execute_db(
                "UPDATE chatbot_settings SET cache_enabled = %s "
                "WHERE id = 1 RETURNING id",
                (bool(enabled),),
            )
        except Exception as e:  # noqa: BLE001
            print(f"[semantic_cache] set enabled failed: {e}")
    if threshold is not None:
        try:
            t = max(0.80, min(0.99, float(threshold)))
            _execute_db(
                "UPDATE chatbot_settings SET cache_threshold = %s "
                "WHERE id = 1 RETURNING id",
                (t,),
            )
        except Exception as e:  # noqa: BLE001
            print(f"[semantic_cache] set threshold failed: {e}")
    _invalidate_settings_cache()
    return get_cache_settings(force_refresh=True)
