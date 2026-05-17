# Once-Per-Period Idempotency (Claim Before You Act)

## When to use
A background job runs more than once per period (because the scheduler ticks frequently, multiple workers race, or a crash retries it) but the *side effect* must happen exactly once per period — sending the weekly digest, charging a monthly bill, posting a daily summary, dispatching a one-shot SMS for a unique event id.

The wrong fix is "set a `last_sent_at` column and check it before sending." That's a TOCTOU race — two workers both read `NULL`, both send, both write. The right fix is to let Postgres decide the winner with one atomic statement.

## Architecture
1. Define a tracking table whose UNIQUE constraint encodes "the slot." Common shapes: `(tenant_id, period_start)`, `(message_sid)`, `(event_id, action_id)`.
2. The job's first action is `INSERT ... ON CONFLICT (...) DO NOTHING RETURNING id`.
3. If `RETURNING` gives a row, *this* caller won the claim — do the side effect.
4. If it gives no row, another caller already claimed it — exit silently.
5. Optionally update the claim row with `status='success'` / `error_text` after the side effect completes, so retries and audits can distinguish "claimed but crashed" from "claimed and done."

This works because `INSERT ... ON CONFLICT DO NOTHING RETURNING` is atomic at the row level: exactly one concurrent caller gets the row back, every other gets nothing — no `SELECT FOR UPDATE`, no advisory lock, no application-level mutex needed.

## Data model
Canonical example in this codebase: `weekly_digest_sends` — `(id, tenant_id, week_start, sent_at, status)` with `UNIQUE (tenant_id, week_start)`.

Other instances:
- `sms_cost_events` — `UNIQUE (tenant_id, message_sid)` so the Twilio status webhook firing twice can't double-bill.
- VELO confirm-token consumption — `_consume_confirm_token` (in `velo_endpoints.py`) deletes the token in one statement and checks `rowcount` to decide whether the caller won.
- Review-ask creation — `UNIQUE (order_id, ask_kind)` so two scheduler passes can't queue two asks for the same purchase.

## API surface
None — it's a SQL pattern, not a library. The shape is always:
```
INSERT INTO claims_table (slot_key_col, ...) VALUES (...)
ON CONFLICT (slot_key_col) DO NOTHING
RETURNING id
```
Followed by `if cur.fetchone() is None: return` (or equivalent).

## Key files
- `app.py` — `_weekly_digest_tick` (claim-then-send pattern, near `weekly_digest_sends` writes).
- `velo_endpoints.py` — `_consume_confirm_token` (atomic delete-and-check variant, ~line 193).
- Cost / SMS write sites — `INSERT ... ON CONFLICT` on `(tenant_id, message_sid)`.

## External deps
PostgreSQL ≥ 9.5 (when `ON CONFLICT` shipped). Every supported Postgres has it.

## Pitfalls
- **Don't pre-check existence first.** `SELECT ... ; if not exists: INSERT` is the bug you're trying to avoid. The whole point is making the existence check and the write one statement.
- **Crash after claim, before side effect.** You've claimed the slot but the email didn't go out. Either (a) accept the loss (often fine for digests), (b) write the side effect first and the claim row second only on success (good for non-idempotent external calls where double-fire is worse than no-fire), or (c) add a `status` column and a separate retry sweep for `claimed-but-not-finished` rows older than N minutes.
- **Index size.** If the slot key is `(tenant_id, event_id)` and events churn, the table grows forever. Add a retention sweep (older than 90 days → DELETE) or partition.
- **Wrong UNIQUE granularity.** `UNIQUE (tenant_id)` would let you send the digest once, ever. Always include the time-bucket column.

## Adaptation notes
- For "exactly once per N seconds, regardless of period boundary," use a lease pattern instead: a single-row table holding `lease_owner`, `lease_expires_at`, updated with `UPDATE ... WHERE lease_expires_at < NOW() RETURNING id`.
- For cross-process coordination without a tracking table, use `pg_try_advisory_lock(hash)`.
- This pattern composes cleanly with the IFTTT engine's `requires_confirmation` (the confirm token's `DELETE ... WHERE token=%s RETURNING id` is the same shape).

## Adoption checklist
- [ ] Identify the smallest slot key that encodes "exactly one of these side effects per period."
- [ ] Create the tracking table with the UNIQUE constraint and a `status` / `sent_at` column.
- [ ] Make the job: claim → bail-if-not-claimed → side effect → mark-status.
- [ ] Add a retention sweep if rows accumulate.
- [ ] Test by spinning up 5 concurrent calls to the job — exactly one side effect should occur.
