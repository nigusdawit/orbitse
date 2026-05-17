# Three-Tier AI Cost Caps (alert_only / throttle / strict_block)

**Category:** Billing · Spend governance
**Status:** Production

## When to use
You proxy paid APIs (OpenAI chat, OpenAI/ElevenLabs voice, Whisper
STT, Twilio SMS) on behalf of tenants and need to bound monthly
spend per tenant. "Bound" means different things in different
contexts: a free-trial tenant should hit a hard wall when they
exceed quota; a paying tenant should keep working but degrade to
cheaper providers; an enterprise tenant should never see an outage
but the admin should be paged at 80%. One ladder, three rungs.

## Architecture
- One row per tenant in `tenant_cost_caps`:
  - `monthly_cap_usd NUMERIC` — the ceiling.
  - `cap_behavior TEXT` in `{alert_only, throttle, strict_block}` —
    what happens at the ceiling.
  - `warn_at_percent INTEGER DEFAULT 80` — when to email the warn-
    line.
  - `alert_email`, `digest_email` — who hears about it.
- A single helper `enforce_cost_cap(tenant_id, surface)` is called
  at the **top** of every paid HTTP route. It computes month-to-date
  spend from the ledger tables (see `05-unit-price-ledger.md`) and
  branches on `cap_behavior`:
  - `alert_only` — never blocks. Returns `(ok=True, throttled=False)`.
  - `throttle` — never blocks the request, but sets a request-scoped
    flag `g._cost_throttled = True`. Call sites read that flag and
    degrade: chat drops to 5 req/window instead of 30; voice TTS
    falls back from ElevenLabs to OpenAI; KB retrieval lowers `k`.
  - `strict_block` — returns HTTP 402 with body
    `{"error": "cap_reached", "spent": <usd>, "cap": <usd>,
    "message": "..."}` (the message text is admin-facing copy).
- A sibling helper `cost_cap_blocks_send(tenant_id, surface)` is the
  background-job equivalent (no request context, no `g`). Returns
  `True` if the job should skip. Used by the SMS campaign sender,
  the scrape-notify SMS path, the review-request SMS path.
- After every successful paid call, a warn-line check runs async:
  if MTD spend just crossed `warn_at_percent`, insert into
  `cost_alerts (tenant_id, period, kind)` with a UNIQUE constraint
  so the email goes out at most once per period, then email the
  configured recipient.

## Data model
- `tenant_cost_caps (tenant_id PK, monthly_cap_usd, cap_behavior,
  warn_at_percent, alert_email, digest_email, digest_send_hour_utc,
  tz_name, updated_at)`.
- `cost_alerts (id, tenant_id, period TEXT, kind TEXT, sent_at,
  UNIQUE(tenant_id, period, kind))` — `period` is the month in
  `YYYY-MM`, `kind` in `{warn, cap_reached}`.

## API surface
- Python: `enforce_cost_cap(tenant_id, surface) -> (ok, throttled)`
  in `app.py` (around line 4499) for HTTP call sites.
- Python: `cost_cap_blocks_send(tenant_id, surface) -> bool`
  (around line 4561) for background jobs.
- HTTP admin: `GET/PATCH /admin/api/cost/cap` — read or update the
  cap row.
- HTTP visitor: paid routes return `402 {"error": "cap_reached", ...}`
  when `strict_block` fires.

## Key files
- `app.py` — the two helpers and the per-surface call sites
  (`/api/chat`, `/api/voice/tts/stream/prepare`,
  `/api/voice/tts/stream/consume`, `/api/voice/stt`, plus internal
  SMS campaign and scrape-notify paths).
- `messaging.py` — `send_sms` consults `cost_cap_blocks_send` before
  hitting Twilio.

## External dependencies
- The ledger tables in `05-unit-price-ledger.md` — without them the
  MTD spend total is meaningless.
- Resend (or any transactional email provider) for the warn-line
  email.

## Pitfalls
- **`alert_only` must never delay the request.** The email side
  effect should be fire-and-forget (thread or task queue).
- **`throttle` is request-scoped, not tenant-scoped.** A throttled
  TTS request degrades to OpenAI; a fresh request from the same
  tenant a millisecond later re-evaluates `g._cost_throttled` from
  scratch. That's the point — as soon as spend drops back below the
  cap (month rollover, refund), the degradation lifts on its own.
- **`strict_block` returns 402, not 429.** 429 is "you're going too
  fast"; 402 is "payment required". Different remediation, different
  retry behaviour from clients. Don't conflate.
- **Warn-line dedupe must be per-period.** The UNIQUE
  `(tenant_id, period, kind)` constraint is doing the heavy lifting;
  without it, every request after the threshold sends a fresh email.
- **Don't read the ledger inside the lock.** `enforce_cost_cap` runs
  on every paid request — keep the MTD query indexed
  (`(tenant_id, created_at DESC)` on each ledger table) and consider
  caching the total for a few seconds per tenant if call volume is
  high.

## Adaptation notes
- The three behaviours map cleanly to trial / standard / enterprise
  tiers. You don't need more rungs; if you want "block at $X, then
  alert", layer a `warn_at_percent` low (e.g. 50) with
  `strict_block` at the cap.
- For multi-currency, pin the cap in one base currency and convert
  ledger writes at the time of write (the ledger stamps the rate
  too — see `05-unit-price-ledger.md`). Don't try to convert at
  read time; live FX makes the cap drift.

## Related skills
- `05-unit-price-ledger.md` — where MTD spend comes from.
- `06-weekly-cost-digest.md` — the "what did your AI do this week"
  email, also gated by feature flag + cap.
- `07-sms-segment-repricing.md` — the SMS-specific case where the
  ledger row is *updated* (segments revised by webhook) but the
  unit price is held constant.
