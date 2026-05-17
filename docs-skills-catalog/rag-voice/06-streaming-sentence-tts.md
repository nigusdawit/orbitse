# Streaming Sentence-by-Sentence TTS

**Category:** Voice · latency
**Status:** Production

## When to use
A user is reading streamed LLM tokens AND you want them to hear the
reply at the same time. Naively waiting for the full message before
calling TTS adds 3–5 s of dead air; this pattern lets the first words
land within ~0.7–1.6 s of the LLM's first period.

## Architecture
The pipeline has three layers, each one decoupled from the next:

1. **Sentence splitter (client).** As LLM tokens arrive, a small
   helper scans the accumulated text for sentence terminators
   (`.!?` + whitespace) with abbreviation guards (`Mr.`, `Dr.`,
   `e.g.`, `etc.`). Each completed sentence is pushed onto a FIFO
   queue and the streaming text continues into the next bubble.
2. **Per-sentence prepare (HTTP).** For each sentence, POST
   `/api/voice/tts/stream/prepare` with `{text, voice_id, model}`.
   The server hashes `(provider, voice, model, text)` to a cache key
   and returns either:
   - `{cached: true,  audio_url: "/uploads/voice/<hash>.mp3"}` on a
     cache hit (free, instant), or
   - `{cached: false, audio_url: "/api/voice/tts/stream/consume?token=…"}`
     on a miss — a single-use, short-TTL signed token.
3. **Tokenised consume (HTTP).** The browser `<audio>` element GETs the
   consume URL. The server validates the token, calls the provider
   (OpenAI or ElevenLabs) in streaming mode, and tees the bytes: one
   copy is yielded to the HTTP response, the other is buffered in
   memory and — only on a clean stream end — uploaded to the storage
   backend at `voice/<hash>.mp3`. A partial download (client
   disconnect, provider error) leaves no cache artefact, so the next
   request retries from scratch.

A sequential audio queue on the client plays the resulting `<audio>`
elements in reading order, so sentence 2 never overlaps sentence 1.

## Data model
- Cache lives on the storage backend at `voice/<sha1>.mp3` (where
  `sha1 = hashlib.sha1(f"{model}|{voice_id}|{text}").hexdigest()`).
- `voice_usage_log` row per call (`feature_type` in
  `tts_generate_openai | tts_generate_elevenlabs | tts_cached`).
- `voice_cost_events` row stamped with the unit price at write time
  (see `../cost-cap/` for the broader cost-ledger pattern; cache hits
  log `cost_usd = 0`).

## API surface
- `POST /api/voice/tts/stream/prepare`
  → `{cached, audio_url, voice_id, model, char_count}`
- `GET  /api/voice/tts/stream/consume?token=…`
  → `audio/mpeg` (streamed, `Content-Type: audio/mpeg`,
  `Cache-Control: no-store`)
- `POST /api/voice/tts` — legacy non-streaming endpoint, kept for
  admin pre-generation of intros.

Client API (in `public/voice.js`):
- `VoiceAgent.streamSpeakBegin()` — reset queue, cancel any prior playback.
- `VoiceAgent.streamSpeakFeed(accumDisplayText)` — feed accumulated
  text; emits any new complete sentences.
- `VoiceAgent.streamSpeakEnd(finalText, bubbles)` — speak any
  non-terminated tail and mark bubbles `__voiceStreamSpoken = true`.
- `VoiceAgent.streamSpeakCancel()` — hard-stop (mute, new user msg).

## Key files
- `app.py` — `_stream_tts_openai`, `_stream_tts_elevenlabs`, the
  `/api/voice/tts/stream/{prepare,consume}` routes.
- `public/voice.js` — sentence splitter + queue (`streamSpeakBegin/
  Feed/End/Cancel`).
- `public/script.js` — `chatSendStreaming` calls `streamSpeakFeed`
  after each token chunk; `chat:agent-message` handler skips already-
  spoken bubbles via `__voiceStreamSpoken`.

## External deps
- Provider with a streaming TTS endpoint. OpenAI's
  `audio.speech.create` and ElevenLabs' `text-to-speech/<voice_id>`
  both expose chunked-MP3 streams.

## Pitfalls
- **Tee carefully.** A naive "buffer the whole MP3 then send" serialises
  the bytes and gives up the latency win. The implementation yields
  each provider chunk to the client and only commits the cached MP3
  after the stream completes successfully.
- **Concurrent misses for the same key are fine** — each request
  produces an independent buffered copy and the last successful write
  wins. Never lock around the cache key; that re-introduces head-of-
  line blocking. (If you need stricter atomicity than "last writer
  wins", switch to a per-request `.part` file and `os.replace` on
  success — the public storage backend would need a rename primitive.)
- **Tokens are one-shot.** Re-using a consume URL must 401. Otherwise
  any scraper can resurrect any cached message indefinitely.
- **Abbreviation guards matter.** Without them "see Dr." flushes a
  one-word sentence and the queue gets noisy. Test with addresses
  (`123 Main St.`), titles (`Mr.`, `Mrs.`), Latin (`e.g.`, `i.e.`),
  and decimals (`v3.14`).
- **Double-speak hazard.** The legacy "speak the whole message after it
  finishes" hook will replay the same text unless bubbles are tagged
  (`__voiceStreamSpoken = true`).

## Adaptation notes
- Add per-user mute by checking a localStorage flag inside
  `streamSpeakBegin` and skipping the queue entirely.
- Swap the provider by adding `_stream_tts_<name>` and routing on the
  configured `tts_provider`.
- For longer pauses between sentences (more "natural" cadence), insert
  a `setTimeout` between queue items.

## Related skills
- `07-dual-provider-tts.md` — provider selection + voice-list logic.
- `09-utm-voice-intros.md` — uses the same cache shape and `_log_voice_usage`.
- `10-per-ip-voice-cap.md` — abuse cap that gates `prepare`.
- `../ai-pipelines/01-streaming-tool-call-loop.md` — the LLM source
  whose tokens drive `streamSpeakFeed`.
