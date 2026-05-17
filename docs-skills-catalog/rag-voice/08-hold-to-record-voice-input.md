# Hold-to-Record Voice Input (Web Speech ↔ Whisper)

**Category:** Voice · STT
**Status:** Production

## When to use
You want a microphone button inside chat inputs that "just works"
across browsers and gives admins the option to pay for higher-accuracy
Whisper transcription on noisy / non-English audio without changing
the UX.

## Architecture
Two STT backends behind one button. The dispatcher
`effectiveSttProvider()` picks per click based on (a) the admin-
configured preference and (b) what the visitor's browser supports:

| Configured | Browser supports MediaRecorder? | SpeechRecognition? | Picks       |
| ---------- | ------------------------------- | ------------------ | ----------- |
| `whisper`  | yes                             | -                  | `whisper`   |
| `whisper`  | no                              | yes                | `webspeech` |
| `webspeech`| -                               | yes                | `webspeech` |
| any        | yes                             | no                 | `whisper`   |
| any        | no                              | no                 | `null` (no mic) |

**Web Speech path** uses `SpeechRecognition` with `continuous=true`
and `interimResults=true`, plus a 2-second silence watchdog that
calls `recognition.stop()` so the assistant doesn't sit waiting
mid-pause. Recognised text is written into the chat input live and
auto-sent on stop.

**Whisper path** records via `MediaRecorder`, posts the resulting
blob to `POST /api/voice/stt`, and pipes the returned transcript into
the chat input the same way. The server calls OpenAI Whisper with
`response_format="verbose_json"` so the returned `audio_seconds`
flows into `voice_cost_events` for accurate per-minute billing.

A mic-tap while audio is playing **interrupts the audio** (stops the
queue, cancels any in-progress TTS) — visitor intent is "let me talk",
not "shout over the AI".

## Data model
- `voice_settings.stt_provider TEXT NOT NULL DEFAULT 'webspeech'`.
- `voice_usage_log` row per Whisper call with `feature_type =
  'stt_whisper'`.

## API surface
- `POST /api/voice/stt` — multipart `audio` blob, returns
  `{transcript, audio_seconds, language}`. 5 MB cap.
- Client API (`public/voice.js`):
  - `effectiveSttProvider()` → `'whisper' | 'webspeech' | null`
  - `toggleVoiceInput(inputEl, sendEl, micBtn)` — single entry-point
    used by every mic button on the page.

## Key files
- `public/voice.js` — `injectMicButtons`, `toggleVoiceInput`,
  `toggleSpeechRecognition`, `toggleWhisperRecording`.
- `app.py` — `/api/voice/stt` route, Whisper call, cost logging.

## External deps
- `OPENAI_API_KEY` (direct) — Whisper isn't behind the Replit proxy.
- Browser: `MediaRecorder` + `getUserMedia` (Whisper path), or the
  `SpeechRecognition` Web Speech API (free, browser-native).

## Pitfalls
- **The Web Speech API is not in Firefox** (and is patchy in mobile
  Safari). Always have the dispatcher fall back gracefully — if
  `null` is returned, hide the mic button rather than render a broken
  one.
- **`continuous=true` runs forever** until the silence watchdog or the
  user clicks again. Without the watchdog a single forgotten click
  keeps the mic live for the rest of the session.
- **Audio formats from MediaRecorder vary** by browser (`audio/webm`,
  `audio/mp4`, …). Whisper accepts most; do not transcode client-side.
- **5 MB cap maps to ~5 minutes** of compressed audio. Reject larger
  blobs server-side or you'll burn quota silently.
- **`audio_seconds` requires `verbose_json`.** Plain `json` returns no
  duration and you'll under-bill by 100%.

## Adaptation notes
- Per-tenant STT provider: replace the singleton `voice_settings` read
  with a tenant-scoped lookup.
- Cheaper Whisper: route through `whisper-1` (default) or
  `gpt-4o-mini-transcribe` if cost matters more than accuracy.
- Push-to-talk vs toggle: change the mic button event from `click` to
  `mousedown` / `mouseup` / `touchstart` / `touchend` and call
  `start()` / `stop()` on those edges instead.

## Related skills
- `06-streaming-sentence-tts.md` — interruption logic shares the
  same `stopCurrentAudio()` plumbing.
- `10-per-ip-voice-cap.md` — separate `_stt_ip_budget` mirrors the
  TTS cap.
- `../ai-pipelines/08-multimodal-chat-attachments.md` — sibling pattern
  for non-text input.
