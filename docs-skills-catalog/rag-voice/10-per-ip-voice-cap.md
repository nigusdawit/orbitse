# Per-IP Voice Daily Character Cap

**Category:** Voice · abuse prevention
**Status:** Production

## When to use
TTS bills per character and STT bills per minute. Anonymous visitors
can hit the public endpoints; without a cap one bad actor with a
script can run up a provider bill overnight. You need a cheap,
dependency-free speed bump that lets normal use through and stops
runaway abuse.

The two surfaces use different units: TTS is metered by **characters
spent today** (because cost scales with text length); STT is metered
by **requests today** (each request is already size-capped at 5 MB and
counting per-minute would require parsing the audio before deciding
whether to allow it).

## Architecture
- Two in-process dicts, one per surface, keyed by client IP:
  ```python
  _tts_ip_budget = {}   # ip -> ("YYYY-MM-DD", chars_used_today)
  _stt_ip_budget = {}   # ip -> ("YYYY-MM-DD", requests_today)
  ```
- Every paid call site (`/api/voice/tts`, `/api/voice/tts/stream/prepare`,
  `/api/voice/stt`, intro miss path) calls
  `_check_tts_ip_budget(ip, char_count)` (or the STT equivalent)
  BEFORE billing the provider. The helper returns `False` if today's
  spend + `char_count` would exceed `TTS_DAILY_CHARS_PER_IP` and the
  route returns `429 Too Many Requests`.
- Trusted IP source is `request.remote_addr` (the TCP peer), not
  `X-Forwarded-For` — anyone can spoof the header and trivially evade
  per-IP throttles by rotating values. See the auth skill on rate
  limiting for the same reasoning.
- Cache hits (`feature_type='tts_cached'`, `intro_play`) DO NOT consume
  budget — they didn't cost anything to serve.
- TTS and STT trackers are deliberately separate so STT abuse doesn't
  starve TTS for the same IP and vice versa.

## Data model
None on disk. The dicts live in process memory and reset on restart,
which is fine for a coarse anti-abuse signal (a restart loses at most
24 h of attribution and a determined attacker has to wait until UTC
midnight either way).

If you need cross-worker enforcement, the upgrade is a Redis hash
keyed by `tts:<ip>:<YYYY-MM-DD>` with `INCRBY` + 25-hour TTL.

## API surface
- `_check_tts_ip_budget(client_ip, char_count) -> bool` — mutates the
  tracker as a side-effect on success.
- (mirrored) `_check_stt_ip_budget(client_ip) -> bool` — counts
  requests, not characters.
- Constants in `app.py`: `TTS_DAILY_CHARS_PER_IP = 30_000` (≈ 20–30
  minutes of speech), `STT_DAILY_REQUESTS_PER_IP = 100`.

## Key files
- `app.py` — `_tts_ip_budget`, `_stt_ip_budget`, `_check_*` helpers,
  `_client_ip()`, every voice route's pre-check.

## External deps
None.

## Pitfalls
- **Behind a reverse proxy** every visitor collapses to the proxy's
  IP. The README explicitly accepts this trade-off ("a coarse
  anti-abuse cap that may false-share is better than trusting a
  forgeable header"). If you need real per-visitor caps, terminate
  proxy headers with `werkzeug.middleware.proxy_fix.ProxyFix` AND
  attest that the proxy you trust is the one setting them.
- **In-process state ≠ multi-worker enforcement.** With N gunicorn
  workers the effective cap is N × `TTS_DAILY_CHARS_PER_IP`. Move to
  Redis if that matters.
- **Don't decrement on cache hits.** Caching is the whole point — if
  cache hits consumed budget you'd punish legitimate repeat users.
- **Tie this cap into the broader cost-cap behaviour.** When tenant-
  level `cap_behavior='throttle'` is on, also downgrade ElevenLabs to
  OpenAI for the same request. See the cost-cap skill (Batch 4 —
  forward reference) for the `g._cost_throttled` pattern.
- **Date string `"YYYY-MM-DD"` is in server local time.** Switch to
  UTC explicitly (`datetime.utcnow().strftime(...)`) if your server
  could move time zones.

## Adaptation notes
- Per-tenant caps in addition to per-IP: layer a second dict keyed by
  `tenant_id` with a higher ceiling. Fail the call if EITHER cap is
  exceeded.
- Soft cap vs hard cap: at 80% spent, set a response header
  `X-Voice-Budget-Remaining: <chars>` so the client can show a
  warning before the 429 hits.
- Allowlist: skip the check entirely when
  `request.headers.get("X-Internal-Key") == os.environ["VOICE_BYPASS_KEY"]`
  for monitoring / pre-warm scripts.

## Related skills
- `06-streaming-sentence-tts.md` — `prepare` is the primary gated
  endpoint.
- `07-dual-provider-tts.md` — provider downgrade on throttle.
- `08-hold-to-record-voice-input.md` — separate STT bucket.
- `../auth/` — `_client_ip()` and the IP-trust rationale are shared
  with the login throttle.
