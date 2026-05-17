# SMS-Segment Re-Pricing (Webhook Patches Quantity, Never Unit Price)

**Category:** Billing · Edge case
**Status:** Production

## When to use
Twilio bills SMS by **segment**, not by message. An SMS up to 160
GSM-7 chars is one segment; longer or non-GSM (emoji, Chinese,
Arabic) re-encodes to UCS-2 and packs into 70-char segments. The
final segment count is only known *after* Twilio queues the message:
the synchronous `client.messages.create` response sometimes returns
`num_segments`, sometimes returns nothing, and the authoritative
count arrives later via the status callback webhook.

That means your cost ledger has to do something unusual: insert a
row up-front with possibly-null `segments`, then patch the row when
the webhook lands — **without** ever changing the unit price you
stamped at insert time, even if an admin edited `model_prices`
between the send and the callback.

## Architecture
- At send time, `record_sms_cost(tenant_id, message_sid,
  segments_or_none)` inserts (upserts) into `sms_cost_events`:
  - Always stamps `unit_sms_price_usd` from the currently-active
    `model_prices` row (the per-segment unit price — the column
    name omits the `_per_segment` suffix, the surface implies it).
  - Sets `segments = NULL` if Twilio's POST didn't include it.
  - Computes `cost_usd = segments * unit_sms_price_usd` when
    segments is known, else NULL.
  - Uses `ON CONFLICT (tenant_id, message_sid) DO NOTHING` (the
    partial UNIQUE index covers `WHERE message_sid <> ''`).
- Twilio status callback POST hits the messaging webhook. When the
  payload contains `NumSegments`, the handler runs:
  ```sql
  UPDATE sms_cost_events
     SET segments = %s,
         cost_usd = %s::numeric * unit_sms_price_usd
   WHERE message_sid = %s
  ```
  The `unit_*` column is read straight off the existing row — it
  is **never recomputed** from `model_prices`. So a price change
  between send and callback has zero effect on this row.
- The same handler may also receive multiple callbacks for the
  same `MessageSid` (Twilio retries on non-2xx, and emits multiple
  status updates: queued, sent, delivered, failed). The UPDATE is
  idempotent — running it again with the same `NumSegments`
  produces the same row.

## Data model
- `sms_cost_events`:
  - `tenant_id`, `message_sid VARCHAR(80)`, `segments INTEGER`
    (nullable), `unit_sms_price_usd NUMERIC(14, 8)`
    (stamped at insert; this is the per-segment price), `cost_usd
    NUMERIC(14, 8)` (nullable), `created_at`.
  - Indexed `(tenant_id, created_at DESC)`.
  - Partial UNIQUE on `(tenant_id, message_sid) WHERE message_sid
    <> ''` — empty `message_sid` (immediate Twilio failures) gets
    its own row each time; real sends dedupe.
- Migration note: an early iteration declared `segments INTEGER NOT
  NULL DEFAULT 1`. The upgrade in `init_db()` runs `ALTER COLUMN
  segments DROP NOT NULL; ALTER COLUMN segments DROP DEFAULT`
  unconditionally — safe to re-run on already-correct schemas.

## API surface
- Python: `record_sms_cost(tenant_id, message_sid, segments=None)`
  — called from `messaging.send_sms` immediately after the Twilio
  API call returns.
- HTTP: the Twilio status callback URL (configured in the Twilio
  console) hits the messaging webhook handler; the segment-update
  block lives inside the same handler that records delivery
  status, opt-outs, etc.

## Key files
- `app.py` — `sms_cost_events` table create (around line 3608) and
  the segment-update branch in the Twilio status webhook.
- `messaging.py` — `send_sms` is the call site that records the
  initial cost row.

## External dependencies
- Twilio (sender + status callback). The callback URL must be
  publicly reachable and signed with `X-Twilio-Signature` so an
  attacker can't POST fake segment counts and inflate the ledger.

## Pitfalls
- **Never re-fetch `model_prices` on the webhook.** That's the
  entire failure mode this skill exists to prevent. Multiply
  `NumSegments` by the row's *own* `unit_sms_price_usd`.
- **Verify the Twilio signature.** Without it, a single forged POST
  can rewrite a tenant's spend total.
- **Make `segments` nullable.** A NOT NULL DEFAULT 1 column gives
  you cost rows that look correct for one-segment messages and
  silently undercount everything else.
- **The send-time row must exist before the callback.** If you
  insert lazily on the callback only, you have no record of
  messages that never deliver (Twilio errors at create time, opt-
  outs, etc.). Insert first, patch later.
- **Watch the `message_sid` empty case.** Twilio returns an empty
  SID when the create call hard-errors. The partial UNIQUE
  intentionally lets these accumulate as separate rows (they're
  failure receipts, not duplicates).

## Adaptation notes
- The same pattern fits any provider where the cost quantity
  arrives after the request: video transcoding (final minute
  count), email batch sends (final bounce-adjusted count), etc.
- For audit, never `DELETE` rows that get re-priced. If you need
  to revoke a duplicate, set `segments = 0, cost_usd = 0` and add
  a `void_reason` column — the audit trail stays intact.
- If you bill the tenant retail rather than passing the Twilio
  cost through, the stamped `unit_*` column is the *retail* price,
  not the wholesale Twilio price. The ledger is the source of
  truth for what the tenant owes.

## Related skills
- `05-unit-price-ledger.md` — explains why every event row stamps
  its own unit price.
- `04-three-tier-cost-caps.md` — the same `sms_cost_events.cost_usd`
  column drives the SMS-send pre-check via
  `cost_cap_blocks_send`.
- `06-weekly-cost-digest.md` — the per-surface breakdown rolls up
  this table under `sms_*`.
