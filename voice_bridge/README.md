# voice_bridge — live AI phone call media bridge

A small, **standalone** service that gives the AI concierge a real phone voice.
It is the missing piece for task 049: the Flask app already emits the Twilio
TwiML and logs calls, but Twilio **Media Streams** need a public WebSocket
server to stream audio to/from a realtime voice model. That server is this.

It is **not** imported by the Flask app — it runs as its own process (so it can
host a long-lived WebSocket, which a request/response WSGI app can't).

```
Caller ──PSTN──▶ Twilio Voice ──TwiML <Connect><Stream>──▶  voice_bridge  ──▶ VoiceProvider
                                   (wss://your-bridge)        (this service)    (OpenAI Realtime / …)
```

Audio is 8 kHz mono **G.711 μ-law** end to end — the same format OpenAI's
Realtime API speaks natively (`g711_ulaw`), so there's **no transcoding**.

## Why a provider abstraction (not OpenAI-only)

The bridge is provider-agnostic on purpose — you shouldn't be locked to one
vendor. It speaks Twilio on one side and a tiny `VoiceProvider` interface on the
other (`providers/base.py`). Backends included:

| Provider (`VOICE_PROVIDER`) | Needs | Notes |
|---|---|---|
| `echo` (default) | nothing | Plays your voice back. Proves the whole pipe with **no API key**. |
| `openai` | `OPENAI_API_KEY` | Reference realtime brain (OpenAI Realtime API). |
| _deepgram, gemini, self-hosted…_ | — | Slots reserved — see **Adding a provider**. |

## Run it

```bash
pip install -r voice_bridge/requirements.txt

# Credential-free smoke test (echoes the caller):
VOICE_PROVIDER=echo python -m voice_bridge.bridge

# Real AI voice:
VOICE_PROVIDER=openai OPENAI_API_KEY=sk-... \
  VOICE_MODEL=gpt-4o-realtime-preview VOICE_NAME=alloy \
  VOICE_INSTRUCTIONS="You are the concierge for Acme Co. Be warm and concise." \
  python -m voice_bridge.bridge
```

Env vars: `PORT` (default 8080), `VOICE_PROVIDER`, `OPENAI_API_KEY`,
`VOICE_MODEL`, `VOICE_NAME`, `VOICE_INSTRUCTIONS`.

## Wire it to the app

1. Deploy this service somewhere with a **public `wss://` URL** (Replit, Render,
   Fly, or `ngrok http 8080` for testing).
2. In the admin app → **AI Control → Live Call**:
   - `voice_wss_url` = your bridge URL (e.g. `wss://your-bridge.example.com`)
   - set `live_call_enabled` ON
3. Set `TWILIO_AUTH_TOKEN` in the app (the voice webhooks **fail closed** without
   it) and point your Twilio **Voice** number's webhook at
   `https://your-app/webhooks/twilio/voice`.

The app's TwiML then dials `<Connect><Stream url="{voice_wss_url}"/>` and the
caller is talking to the AI.

## Adding a provider

1. Create `providers/yourprovider.py` implementing `VoiceProvider`
   (`open`, `send_caller_audio`, `audio_out`, `close`) — all audio is 8 kHz
   μ-law; convert internally if your vendor needs another format.
2. Register it in `providers/__init__.py` `_PROVIDERS`.
3. Select it with `VOICE_PROVIDER=yourprovider`.

Keep implementations **fail-safe**: on an upstream error, end `audio_out()`
cleanly rather than raising into the relay loop.

## Tests

```bash
python -m pytest voice_bridge/tests/test_bridge.py
```

Covers the Twilio frame codec, the provider registry/fallback, the Echo relay
round-trip, and that the OpenAI provider degrades cleanly with no API key. The
live websocket server + a real Twilio call are verified manually (operator
runbook above).
