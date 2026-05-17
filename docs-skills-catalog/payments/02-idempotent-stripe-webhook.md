# Idempotent Stripe Webhook Router

**Category:** Payments · Webhooks
**Status:** Production

## When to use
You accept Stripe Checkout for more than one thing (events, services,
orders, donations) and need one webhook endpoint to fulfil all of
them safely. "Safely" here means three things at once:

1. The same Stripe event can be delivered more than once (Stripe
   retries on any non-2xx, and sometimes for no reason at all) —
   processing it twice must not double-fulfil anything.
2. Two concurrent webhook deliveries for the same payment must not
   race the database into an inconsistent state.
3. A webhook delivered for a completely unrelated kind of payment
   must not corrupt an unrelated table.

## Architecture
- Single Flask route `POST /api/stripe/webhook` (see `app.py` around
  line 31042). The signed payload is verified with
  `stripe.Webhook.construct_event(payload, sig_header, secret)`
  before anything else runs — invalid signatures get an immediate
  400.
- Dispatch is on **`metadata.kind`** of the inner object
  (`event_rsvp`, `service_booking`, `product_order`, `donation`,
  `service_balance`, ...). Each branch reads the matching local id
  (`metadata.rsvp_id`, `metadata.booking_id`, etc.) and never
  touches a row from a different kind.
- Row-level locking + status pre-check is what gives the handler its
  idempotency. The handler always:
  1. `SELECT id, payment_status FROM <table> WHERE id = %s FOR UPDATE`
  2. If `payment_status` is already `paid` (or already in the
     terminal state for this event), commit and 200 immediately —
     this is the redelivery branch.
  3. Otherwise update the row to the new state, stamp
     `stripe_session_id` / `amount_paid_cents`, and commit.
- Companion events handled the same way:
  - `checkout.session.completed` → `paid`.
  - `checkout.session.expired` → `expired` (releases the reserved
    seat/slot from the dispatcher).
  - `payment_intent.payment_failed` → keep `pending` but stamp the
    last error for the admin UI.
- All work happens inside a single DB transaction per branch so the
  `FOR UPDATE` lock survives until the row update commits.

## Data model
The webhook owns no table of its own; it mutates the same per-surface
tables the dispatcher wrote (`event_rsvps`, `service_bookings`,
`orders`). The contract with each table:
- `payment_status` is the single source of truth for fulfilment.
- `stripe_session_id` is stamped on `completed`.
- `amount_paid_cents` is stamped from `session.amount_total` (not
  from the request body that originally created the session).

## API surface
- `POST /api/stripe/webhook` — single endpoint for ALL events.

## Key files
- `app.py` — the route at line 31042 and per-kind handlers
  immediately below it (search for `metadata.get("kind")`).
- `stripe_client.py` — `get_webhook_secret()` picks the right signing
  secret for the current mode.

## External dependencies
- Stripe Python SDK.
- A configured `STRIPE_WEBHOOK_SECRET` (or test-mode equivalent) so
  signature verification works.

## Pitfalls
- **Verify the signature first, parse second.** Doing it in the
  other order opens you to a forgery attack where someone POSTs a
  fake `checkout.session.completed` and marks an unpaid order as
  paid. `construct_event` does both checks together.
- **FOR UPDATE is mandatory.** Without it, two concurrent
  redeliveries each read `payment_status='pending'`, each insert a
  fulfilment side-effect, and both commit. The lock serialises the
  reads.
- **Pre-check the terminal state.** Even with `FOR UPDATE`, you
  still need the `if payment_status == 'paid': return 200` guard —
  the second delivery acquires the lock *after* the first one
  commits, and you don't want to send a second receipt email.
- **Discriminate on `metadata.kind`, not on the URL.** All payment
  surfaces share one webhook endpoint; Stripe doesn't know which
  table to touch. If `kind` is missing or unknown, log and 200
  (don't 500 — Stripe retries forever on non-2xx).
- **Stamp `amount_paid_cents` from the payload.** If you stamp from
  the local row, partial refunds and donation flows will look wrong
  forever.
- **Return 2xx on duplicates.** A 400/500 makes Stripe retry, which
  amplifies the very problem you're trying to dedupe.

## Adaptation notes
- If you add a new surface, add a new `metadata.kind` and a new
  branch. Resist the urge to make the dispatcher data-driven from a
  table — the per-branch SQL is short and the branch makes the
  fulfilment side-effects (emails, capacity release, contract token
  generation) obvious in code review.
- For ledger-style tables (no mutable payment_status — every payment
  becomes a new row), use a UNIQUE constraint on
  `stripe_event_id` instead of `FOR UPDATE` to dedupe.

## Related skills
- `01-stripe-checkout-dispatcher.md` — the call-site that creates
  the pending row this webhook flips to `paid`.
- `03-stripe-product-price-sync.md` — Price ids referenced by
  `line_items` must still exist when the webhook arrives; the sync
  engine never deletes Prices, only deactivates them.
