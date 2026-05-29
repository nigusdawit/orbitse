"""
admin_ai_platform.llm
=====================

LLM client factories + active-provider resolution — an independent copy of the
client-init block (app.py ~548-595) and ``get_active_llm_provider`` (~12043).

Three clients, all optional and fail-open:
  * ``openai_client``        — chat completions, possibly via the Replit AI proxy
    (``AI_INTEGRATIONS_OPENAI_*``); falls back to the public OpenAI base URL.
  * ``openai_direct_client`` — direct OpenAI key, REQUIRED for /audio/* (TTS,
    Whisper) which the proxy doesn't support. ``None`` when no direct key.
  * ``anthropic_client``     — Claude, selected per-tenant via
    ``agent_provider_settings``. ``None`` when no key / SDK.

The active provider is stored in the DB so admins can switch at runtime. If the
admin picked Claude but the client is unavailable we RAISE (explicit failure)
rather than silently routing to OpenAI — silent provider swaps are a debugging
nightmare.
"""

from __future__ import annotations

import sys

from openai import OpenAI

try:  # Anthropic SDK is optional
    from anthropic import Anthropic
except Exception:  # pragma: no cover
    Anthropic = None

from . import config
from .db import query_db


class LLMProviderUnavailable(RuntimeError):
    """Raised when the configured provider's client isn't initialized."""


# --- Client singletons, built once at import ------------------------------
# FAIL OPEN: construct a client ONLY when a key is present. The OpenAI SDK
# raises at construction time when the key is empty, so passing "" would crash
# import and (because blueprints import this module) silently prevent the chat
# / voice routes from mounting. With no key, openai_client stays None and the
# chat route returns a clean 503 instead.
openai_client = None
_chat_key = config.AI_INTEGRATIONS_OPENAI_API_KEY or config.OPENAI_API_KEY
if _chat_key:
    try:
        openai_client = OpenAI(api_key=_chat_key,
                               base_url=config.AI_INTEGRATIONS_OPENAI_BASE_URL)
    except Exception as e:  # pragma: no cover
        print(f"[llm] OpenAI chat client init error: {e}", file=sys.stderr)

openai_direct_client = None
if config.OPENAI_API_KEY:
    try:
        openai_direct_client = OpenAI(api_key=config.OPENAI_API_KEY)
    except Exception as e:  # pragma: no cover
        print(f"[llm] direct OpenAI client init error: {e}", file=sys.stderr)

anthropic_client = None
if config.ANTHROPIC_API_KEY and Anthropic is not None:
    try:
        anthropic_client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    except Exception as e:  # pragma: no cover
        print(f"[llm] Anthropic client init error: {e}", file=sys.stderr)


def get_active_llm_provider():
    """Return ``(provider, model)`` from ``agent_provider_settings``.

    On a DB error → ('openai', AI_MODEL) so chat keeps working through an
    outage. If the admin explicitly configured Claude but the client is
    unavailable, raise ``LLMProviderUnavailable`` instead of silently routing
    to OpenAI.
    """
    try:
        row = query_db(
            "SELECT provider, openai_model, claude_model "
            "FROM agent_provider_settings WHERE id = 1",
            fetchone=True,
        )
    except Exception as e:
        print(f"[llm] provider lookup DB error, falling back to openai: {e}",
              file=sys.stderr)
        return ("openai", config.AI_MODEL)
    if not row:
        return ("openai", config.AI_MODEL)
    provider = (row.get("provider") or "openai").strip().lower()
    if provider == "claude":
        if anthropic_client is None:
            raise LLMProviderUnavailable(
                "Claude is the configured provider but the Anthropic client is "
                "not initialized. Set ANTHROPIC_API_KEY and restart, or switch "
                "the AI Provider setting back to OpenAI."
            )
        return ("claude", row.get("claude_model") or "claude-sonnet-4-5")
    return ("openai", row.get("openai_model") or config.AI_MODEL)


def voice_client():
    """Return the client to use for TTS/Whisper (direct only), or None."""
    return openai_direct_client
