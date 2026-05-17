# Weekly Cost Digest (Claim-Then-Send Idempotency)

**Category:** Billing · Reporting
**Status:** Production

## When to use
You want to email each tenant a once-a-week "here's what your AI did
this week + here's what it cost" recap without ever sending the same
digest twice. The hard part is not the rendering — it's making the
scheduler safe across:

- Multiple worker processes (which may fire at the same minute).
- Crashes mid-send (where retries must not re-send).
- Long-running renders (where a slow first attempt must not be
  superseded by a fresh attempt that double-sends).

## Architecture
- A scheduler tick `_weekly_digest_tick()` (in `app.py` around line
  5057) fires every Monday 09:00–09:30 UTC and iterates every
  tenant with the `weekly_digest` feature flag enabled.
- For each tenant:
  1. Compute the tenant-local week boundary (Monday 00:00 in
     `tenant_cost_caps.tz_name`) — see `_tenant_local_now`. Only
     fire when "now" sits in the configured local hour on Monday.
  2. **Claim the slot before doing any work**:
     ```sql
     INSERT INTO weekly_digest_sends (tenant_id, week_start, payload_json)
     VALUES (%s, %s, %s::jsonb)
     ON CONFLICT (tenant_id, week_start) DO NOTHING
     RETURNING id
     ```
     The UNIQUE index on `(tenant_id, week_start)` plus
     `RETURNING id` is the linchpin: only the worker that gets a
     row back proceeds. Every other concurrent worker (and every
     subsequent crash-restart this week) sees `None` and skips.
  3. Only AFTER the claim succeeds, render the HTML and send via
     Resend. The recipient address falls back through
     `cap.digest_email` → `cap.alert_email` → `ADMIN_EMAIL`.
- The render pulls from the ledger tables (see
  `05-unit-price-ledger.md`): MTD spend, per-surface breakdown,
  week-over-week delta, top conversations, top forms.

## Data model
`weekly_digest_sends (id, tenant_id, week_start DATE, payload_json
JSONB, sent_at, UNIQUE (tenant_id, week_start))`. The UNIQUE
constraint is the entire idempotency mechanism — no row-locking,
no advisory locks, no Redis.

## API surface (Python)
- `_weekly_digest_tick()` — entry point called by the scheduler.
- `_digest_render_html(tenant_id, week_start) -> str` — pure
  rendering, safe to call repeatedly.
- `_tenant_local_now(tz_name) -> datetime` — IANA tz aware "now".

## Key files
- `app.py` — `_weekly_digest_tick` (line 5057) and friends.
- `app.py` — table create in `init_db()` (around line 3690).
- `messaging.py` — `send_email` actually delivers the rendered HTML.

## External dependencies
- Resend (or any provider) for the actual email send.
- `zoneinfo` (stdlib on py3.9+) for IANA timezone handling.
- The ledger tables — without them, the digest body is empty.

## Pitfalls
- **Claim before send, not after.** If you send the email and then
  insert, a crash between those two ops resends on retry. The
  inverse — insert then send — at worst sends zero emails (the
  next week's tick will note the row exists for last week and skip
  re-sending). Zero is better than two for a billing email.
- **Render must be deterministic and side-effect-free.** If the
  scheduler retries a failed send by re-running the render, the
  numbers must be stable for the same `week_start`.
- **Time zones bite.** "Monday 09:00" in Tokyo is "Monday 00:00" in
  London. The scheduler runs in UTC; the per-tenant guard converts.
  If you store `tz_name` as IANA strings (`Asia/Tokyo`), `zoneinfo`
  handles DST automatically.
- **Don't reuse `week_start = today_monday()` blindly.** A tick at
  Tuesday 00:01 must compute *last* week's Monday, not the
  upcoming one. The query helper should always anchor to "the
  Monday on or before the configured local fire time".
- **Send failures must not poison the slot.** If Resend errors, you
  have two safe choices: (a) leave the row in place and accept
  "this week's digest didn't go" until next week, or (b) DELETE
  the row inside a retry window so a manual operator can re-fire
  it. We do (a) — silent failure is preferable to a wrong digest.

## Adaptation notes
- The `INSERT ... ON CONFLICT DO NOTHING RETURNING id` pattern is
  the most underrated idempotency primitive in Postgres. Use it
  anywhere you'd otherwise reach for an advisory lock or a Redis
  SETNX.
- If you want richer "did we send this and was it opened",
  pair the row with a Resend webhook (see the messaging skill) and
  patch a `delivered_at` / `opened_at` onto the same row.
- For very large fleets, shard the tick by `tenant_id % N` so each
  worker only touches 1/N of the tenants — the UNIQUE index still
  guarantees safety if shards overlap.

## Related skills
- `04-three-tier-cost-caps.md` — same `tenant_cost_caps` row drives
  recipient + warn-line.
- `05-unit-price-ledger.md` — the data the digest aggregates.
- `02-idempotent-stripe-webhook.md` — uses the same pre-check
  trick (read terminal state inside FOR UPDATE before mutating).
