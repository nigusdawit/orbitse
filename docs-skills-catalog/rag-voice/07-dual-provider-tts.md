# Dual-Provider TTS (OpenAI + ElevenLabs)

**Category:** Voice · provider abstraction
**Status:** Production

## When to use
You want the cheap, fast option (OpenAI TTS, six fixed voices) as the
default, and a premium ultra-realistic option (ElevenLabs, dynamic
per-account voice list) that can be flipped on per tenant. Admins must
be able to preview voices before committing, and billing must be
attributed to the right provider.

## Architecture
- A singleton `voice_settings` row holds `tts_provider` (`openai` |
  `elevenlabs`), `tts_voice` (OpenAI voice id), `elevenlabs_voice_id`,
  `elevenlabs_model`, and a master `premium_enabled` flag that gates
  ElevenLabs entirely (so a trial/billing tier can disable it
  instantly).
- Two synthesiser functions with identical signatures:
  `_generate_tts_openai(text, voice_id, model, cache_subpath)` and
  `_generate_tts_elevenlabs(...)`. The route picks which one to call
  based on `tts_provider` and writes the resulting MP3 to the same
  cache layout.
- Streaming counterparts (`_stream_tts_openai`, `_stream_tts_elevenlabs`)
  feed `06-streaming-sentence-tts.md`.
- The admin "Voice Agent" tab calls
  `GET /admin/api/voice/elevenlabs-voices` to populate a fresh dropdown
  from the customer's ElevenLabs account (their voices, not ours);
  each voice has a ▶ Listen button that POSTs `/api/voice/sample` to
  audition a fixed phrase.
- `_voice_provider_status()` returns `{openai_tts, openai_whisper,
  elevenlabs, webspeech}` booleans for the admin dashboard to render
  "Active" vs "Missing API key" badges.

## Data model
```sql
ALTER TABLE voice_settings
  ADD COLUMN tts_provider          TEXT    NOT NULL DEFAULT 'openai',
  ADD COLUMN premium_enabled       BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN elevenlabs_voice_id   TEXT    NOT NULL DEFAULT '',
  ADD COLUMN elevenlabs_model      TEXT    NOT NULL DEFAULT 'eleven_turbo_v2_5';
```

## API surface
- `GET  /api/voice/settings`             — public read used by `voice.js`.
- `GET  /admin/api/voice-settings`       — admin read.
- `PUT  /admin/api/voice-settings`       — update toggles.
- `GET  /admin/api/voice/elevenlabs-voices` — dynamic voice list.
- `POST /api/voice/sample`               — audition a voice with a
  fixed test phrase (admin-only).

## Key files
- `app.py` — `_generate_tts_openai`, `_generate_tts_elevenlabs`,
  `_stream_tts_*`, `_voice_provider_status`, the voice routes.
- `templates/admin/dashboard.html` — Voice Agent tab UI.

## External deps
- `OPENAI_API_KEY` (direct — the Replit AI proxy does not support
  `/audio/speech` or `/audio/transcriptions`).
- `ELEVENLABS_API_KEY` (optional).
- `httpx` for streaming over to ElevenLabs.

## Pitfalls
- **`premium_enabled` is the safety switch.** Routes must check it
  before calling ElevenLabs, regardless of what `tts_provider` says.
  Otherwise a tenant can downgrade and still ring up bills.
- **Dynamic voice list is per API key** — different tenants share keys
  only if you intend them to. Cache the list briefly (60–300 s) but
  invalidate when the admin clicks "Refresh voices".
- **Provider failure handling.** If ElevenLabs returns a 4xx for the
  configured `voice_id`, fall back to OpenAI (or surface a clear
  error) rather than throwing an opaque 500.
- **Billing must record the provider.** Both `voice_usage_log.feature_type`
  (`tts_generate_openai` vs `tts_generate_elevenlabs`) and
  `voice_cost_events.provider` need to be set or the cost dashboard
  shows "unknown".
- **OpenAI's binary response** exposes both `.read()` and `.content` —
  prefer `.read()` so the code works against streamed and buffered
  bodies.

## Adaptation notes
- Add a third provider (e.g. Azure) by writing `_generate_tts_azure`
  with the same `(text, voice_id, model, cache_subpath)` signature,
  adding `'azure'` to the `tts_provider` enum, and listing it in
  `_voice_provider_status`.
- For per-tenant API keys, replace the env-var read with a lookup on
  a `tenant_secrets` row before each call.
- For cost-cap throttling, see `../ai-pipelines/04-semantic-response-
  cache.md` and the cost-cap skills (Batch 4 — forward ref): the
  pattern is `if g._cost_throttled and tts_provider == 'elevenlabs':
  tts_provider = 'openai'`.

## Related skills
- `06-streaming-sentence-tts.md` — uses the streaming variant.
- `09-utm-voice-intros.md` — pre-generates MP3s via the non-streaming
  variant.
- `10-per-ip-voice-cap.md` — caller-side abuse cap.
