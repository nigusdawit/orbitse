# Unit-Price Ledger (Stamped-at-Write Historical Pricing)

**Category:** Billing · Financial-correctness invariants
**Status:** Production

## When to use
You bill (or want to surface internal cost for) paid third-party
APIs whose prices the admin can edit. The naive design — store
quantity in the event row, multiply by `model_prices.unit_price` at
read time — silently rewrites history every time an admin updates
a price. A row for a chat completion from three months ago suddenly
costs $0.02 instead of the $0.012 it actually cost. The fix is to
**stamp the unit price at the moment of the write** and never
recompute it at read time. The price table tells the future what to
charge; the event row tells the past what it actually cost.

## Architecture
- One pricing table `model_prices`:
  - `provider`, `model`, `surface` — the lookup key
    (`openai`, `gpt-4o-mini`, `visitor_chat`).
  - Per-unit columns appropriate to the surface:
    `input_price_per_million_tokens`,
    `output_price_per_million_tokens`,
    `tts_price_per_million_chars`,
    `stt_price_per_minute`,
    `sms_price_per_segment`.
  - `active BOOLEAN`, `notes TEXT`.
- Three ledger tables, one per "shape" of cost:
  - `api_cost_events` — chat completions
    (`prompt_tokens`, `completion_tokens`, plus the **stamped**
    `unit_input_price_usd`, `unit_output_price_usd`, `cost_usd`).
  - `voice_cost_events` — TTS by character
    (`char_count` × stamped `unit_tts_price_usd`) OR STT by minute
    (`audio_seconds` ÷ 60 × stamped `unit_stt_price_usd`).
  - `sms_cost_events` — `segments` × stamped `unit_sms_price_usd`,
    with a partial UNIQUE on `(tenant_id, message_sid) WHERE
    message_sid <> ''` for webhook dedupe and re-pricing (see
    `07-sms-segment-repricing.md`).

  (Naming convention on this branch: the stamped column is just
  `unit_<surface>_price_usd` — no `_per_million` / `_per_segment`
  suffix even though the *meaning* of the unit varies by surface.
  The surface itself disambiguates.)
- Every write path is the same shape:
  1. Look up the current row in `model_prices`.
  2. Insert the event row with the unit price copied into the
     stamped columns AND the computed `cost_usd`.
- Reads aggregate `SUM(cost_usd)` — they never re-multiply.
- Admins editing `model_prices` affects only **future** writes. The
  edit UI surfaces this explicitly so nobody expects historical
  rows to shift.

## Data model
Defined in `app.py` `init_db()` around lines 3500–3700. Key
invariants:
- Every event row carries `tenant_id` and `created_at` indexed
  `(tenant_id, created_at DESC)` — that's what the cost cap and
  digest aggregations scan.
- `sms_cost_events.segments` is **nullable** by design: Twilio's
  POST response doesn't always include `num_segments`, and the
  status-callback webhook later patches it in. Re-pricing
  multiplies the stamped unit price by the corrected segment count
  (see `07-sms-segment-repricing.md`).
- Money columns use `NUMERIC` with sub-cent precision (this branch
  uses `NUMERIC(14, 8)` for unit prices and stamped costs) — never
  `FLOAT`. Floating point silently destroys cent-level totals.

## API surface (Python)
- `record_chat_cost(tenant_id, surface, provider, model,
  prompt_tokens, completion_tokens)` — inserts into
  `api_cost_events` and returns `cost_usd`.
- `record_voice_cost(tenant_id, surface, provider, model, *,
  char_count=None, audio_seconds=None)` — inserts into
  `voice_cost_events`, picks the right unit price column based on
  surface.
- `record_sms_cost(tenant_id, message_sid, segments)` — inserts (or
  upserts) into `sms_cost_events`.
- `get_model_price(provider, model, surface)` — fetches the active
  row; used only by the record_* helpers, never by readers.

## Key files
- `app.py` `init_db()` (lines 3500–3700) — schema.
- `app.py` cost recording helpers (search `INSERT INTO api_cost_events`
  / `voice_cost_events` / `sms_cost_events`).
- `app.py` admin endpoints `/admin/api/cost/{summary, series,
  by-surface, by-model, prices}` — admin-facing reads + the price
  editor.

## External dependencies
- The provider you are billing for must return the quantities you
  multiply by. OpenAI returns token counts in the response; Whisper
  with `response_format="verbose_json"` returns `duration` so you
  get true `audio_seconds` (not a 5MB-cap proxy); Twilio's status
  webhook returns `NumSegments`.

## Pitfalls
- **Never JOIN the price table at read time.** That defeats the
  whole point. Reads sum `cost_usd`.
- **NUMERIC, not FLOAT.** Many SaaS bills die to float rounding;
  Postgres NUMERIC is exact.
- **Stamp on the WRITE, not on the queue.** If you stamp at the
  background-worker dequeue moment, an admin who edits the price
  mid-queue gets the new price applied to old work. Stamp inline
  at the moment the API call returns.
- **Watch your STT shape.** Charging Whisper "per request" is
  ~free for short clips and ~free for long clips alike — until
  someone uploads a 4-minute clip every 30 seconds. Per-minute is
  the right unit and `response_format="verbose_json"` is the only
  reliable way to get the duration without round-tripping ffprobe.
- **Don't `UPDATE api_cost_events` after the fact.** It's an
  append-only ledger by design. The only exception is SMS, where
  the same `message_sid` row is updated to correct `segments` —
  but never `unit_*_price_usd`.

## Adaptation notes
- This pattern is the right answer for *any* edit-the-price-of-an-
  immutable-historical-event problem: invoices, time tracking,
  taxi fares, etc. Five tables and two rules cover the surface.
- If you need multi-currency, add `currency` to both `model_prices`
  and the ledger, and stamp the FX rate too.
- For huge volumes, partition the ledger tables by month and drop
  the oldest partition on a retention policy instead of DELETE.

## Related skills
- `04-three-tier-cost-caps.md` — the cap helper sums these rows.
- `06-weekly-cost-digest.md` — the digest groups these rows by
  surface and tops by spend.
- `07-sms-segment-repricing.md` — the one ledger row in the system
  that is intentionally mutated, in a tightly-scoped way.
