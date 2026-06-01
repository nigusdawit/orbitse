---
name: OpenAI client key wiring (chat vs voice)
description: Why adding OPENAI_API_KEY alone may not fix AI chat — chat/embeddings use the Replit AI proxy var, voice uses the direct key.
---

# OpenAI client key wiring

The chat/embeddings OpenAI client and the voice OpenAI client read DIFFERENT
env vars:

- chat + embeddings (semantic_cache) → Replit AI Integrations **proxy** key
  `AI_INTEGRATIONS_OPENAI_API_KEY` (+ `AI_INTEGRATIONS_OPENAI_BASE_URL`).
- voice (`/audio/speech` TTS, `/audio/transcriptions` Whisper) → **direct**
  `OPENAI_API_KEY`.

**Why this matters:** if only `OPENAI_API_KEY` is set (no proxy var), AI chat can
still 401 with "Incorrect API key ... sk-not-c*****ured" — the sentinel the chat
client uses when the proxy key is empty. A real key being present is NOT proof
chat will work; the proxy-vs-direct split is the usual cause.

**How to apply:** to enable chat without the Replit proxy, the chat client must
fall back to the direct `OPENAI_API_KEY` against `api.openai.com` (or configure
the Replit OpenAI integration so the proxy var is populated). Anthropic chat uses
`ANTHROPIC_API_KEY` directly; Brave AI web search uses `BRAVE_SEARCH_API_KEY`
(falls back to Anthropic web search when unset).
