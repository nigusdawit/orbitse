# UTM-Targeted Welcome Voice Intros

**Category:** Voice · personalisation
**Status:** Production

## When to use
You want visitors to be greeted by a short personalised audio message
that varies by where they came from — Instagram ad, Google search,
specific campaign, a known referrer — without making them wait for
TTS to render on each visit.

## Architecture
- An admin creates N intros in `voice_intros`. Each row carries
  optional `utm_source`, `utm_medium`, `utm_campaign`, `referrer`
  match patterns (blank means "match anything"), a `priority`, and a
  pre-generated MP3 cached on disk (`/uploads/voice/intros/<id>.mp3`).
- On page load, `voice.js` reads URL `utm_*` params + `document.referrer`
  and `GET /api/voice/intro?utm_source=…&utm_medium=…&utm_campaign=…
  &referrer=…&session_id=…`.
- The server scores each enabled intro: blank filter = wildcard match;
  any explicit filter must match. The highest-priority winner is
  returned with its cached `audio_url`. Tie-break is `priority DESC, id ASC`.
- The client then plays the MP3 either via autoplay or via a small
  "Tap to hear welcome" floating card (chosen by the admin's
  `autoplay_strategy` setting). Browser autoplay policies almost always
  reject the very first `audio.play()` before any gesture, so the card
  is the reliable cross-browser path — the autoplay attempt is just an
  optimisation.
- `sessionStorage["voiceIntroPlayed"]="1"` after success so the intro
  doesn't replay on every navigation in the same tab. `?intro=force`
  bypasses the gate for QA.
- Each play (cache hit OR miss) records a row in `voice_usage_log` with
  `feature_type='intro_play'` so the admin can see which intros land.

## Data model
```sql
CREATE TABLE voice_intros (
  id           SERIAL PRIMARY KEY,
  name         TEXT NOT NULL,
  text         TEXT NOT NULL,
  voice_id     TEXT NOT NULL,
  utm_source   TEXT NOT NULL DEFAULT '',
  utm_medium   TEXT NOT NULL DEFAULT '',
  utm_campaign TEXT NOT NULL DEFAULT '',
  referrer     TEXT NOT NULL DEFAULT '',
  priority     INTEGER NOT NULL DEFAULT 0,
  enabled      BOOLEAN NOT NULL DEFAULT true,
  audio_url    TEXT,                     -- URL or relative path to the cached MP3
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_voice_intros_priority ON voice_intros (priority DESC, id);
CREATE INDEX idx_voice_intros_enabled  ON voice_intros (enabled);
```

## API surface
- `GET  /api/voice/intro?utm_source=…&utm_medium=…&utm_campaign=…&referrer=…&session_id=…`
  → `{intro: {id, name, audio_url}}` or `{intro: null}` when nothing matches.
- `GET    /admin/api/voice-intros`               — list.
- `POST   /admin/api/voice-intros`               — create.
- `PUT    /admin/api/voice-intros/<id>`          — update.
- `DELETE /admin/api/voice-intros/<id>`          — delete.
- `POST   /admin/api/voice-intros/<id>/generate` — render the MP3 via
  the configured TTS provider and persist `audio_url`.

## Key files
- `app.py` — intro routes + match scoring.
- `public/voice.js` — `maybePlayIntro`, `showIntroCard`, `markIntroPlayed`.
- `templates/admin/dashboard.html` — Voice Agent → Intros tab.

## External deps
- A TTS provider (see `07-dual-provider-tts.md`) for the
  `/generate` step.
- Local disk or object storage for the MP3 cache.

## Pitfalls
- **Autoplay is unreliable.** The `audio.play()` promise resolves
  `false` when blocked; treat that as "intro not played" and leave the
  Tap-to-hear card visible.
- **Match every filter that's set; ignore blanks.** Don't fall into
  the trap of requiring all fields to match exactly — that's why
  blank = wildcard.
- **Pre-generation matters.** Generating TTS on every first-visit adds
  latency right where you don't want it. The admin's `/generate`
  button (or a scheduler tick after editing) keeps `audio_url`
  populated.
- **Session storage is per-tab.** Visitors who open multiple tabs hear
  the intro multiple times — by design, but worth knowing.
- **No PII in `text`.** Intros are cached on disk; treat them as
  publicly-fetchable content.

## Adaptation notes
- Time-of-day intros: add `start_hour` / `end_hour` columns and an
  extra match step.
- Geo-targeting: derive a country from the request IP (or the
  visitor's `Accept-Language` for a softer cue) and add a `country`
  filter column.
- A/B testing: store two `audio_path`s per intro and pick randomly,
  recording which one was played.

## Related skills
- `06-streaming-sentence-tts.md` — same cache layout for free
  visitor-triggered replays.
- `07-dual-provider-tts.md` — provider used by `/generate`.
- `10-per-ip-voice-cap.md` — cap also applies to intros that miss
  the on-disk cache.
