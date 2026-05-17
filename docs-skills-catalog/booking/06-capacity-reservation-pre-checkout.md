# Capacity Reservation Pre-Checkout (No Double-Sell During Stripe Round-Trip)

**Category:** Booking · Concurrency
**Status:** Production

## When to use
The instant a paid booking flow hands the visitor to Stripe Checkout,
the seat needs to be off the market — for everyone else, for the
entire time the visitor is staring at the Stripe page. Without that,
two visitors competing for the last seat both hit Checkout, both
succeed, and you're one chair short. The classic anti-pattern is
"don't decrement capacity until the webhook lands"; that's the bug.
The fix is to insert a `pending` row *inside a row lock on the
parent* before the redirect, and let the availability resolver
treat `pending` as taken.

## Architecture
- Both flows (event RSVP, service booking) follow the same shape:
  1. `BEGIN`.
  2. `SELECT ... FOR UPDATE` on the parent row
     (`events` for RSVPs, `services` for service bookings)
     (~app.py:7458 and ~30652).
  3. Count current `pending`/`confirmed` rows for this
     event/service-slot.
  4. If `count + requested > capacity`, ROLLBACK and return
     `{"ok": false, "error": "capacity_full"}`.
  5. Otherwise INSERT the new row with
     `payment_status='pending'` (~app.py:7523, 30676).
  6. `COMMIT`.
  7. Create the Stripe Checkout Session (outside the transaction)
     and return `{checkout_url}` to the client.
- The availability resolver (`_compute_availability` ~app.py:29799)
  and the RSVP-count helper both INCLUDE pending rows in their
  "taken" count, so no other visitor can pass the capacity check
  while this one is in Checkout.
- Three terminal transitions release or confirm the seat:
  - `checkout.session.completed` → `payment_status='paid'`,
    `status='confirmed'`. Seat stays consumed.
    Handled in the webhook with `SELECT ... FOR UPDATE` on the
    booking/RSVP row to dedupe redeliveries.
  - `checkout.session.expired` →
    `_handle_service_booking_checkout_expired` (~app.py:30964)
    and `_handle_event_checkout_expired` (~app.py:31126) flip
    `payment_status='expired'`, `status='cancelled'`. Seat
    released; next visitor passes the capacity check.
  - Manual admin cancel → same effect via the admin endpoint.

## Data model
- Parent row lockable via `id` PK: `events`, `services`.
- Reservation rows: `event_rsvps`, `service_bookings`.
  - `payment_status TEXT` in
    `{none, pending, paid, expired, refunded}`.
  - `status TEXT` (service bookings only) tracks workflow state
    independently — `pending`, `confirmed`, `cancelled`,
    `pending_review` (contract flow).
- Both reservation tables MUST be queried with
  `payment_status NOT IN ('expired', 'refunded')` when counting
  consumption — see the availability engine.

## API surface
- `POST /api/events/<slug>/rsvp` — pending insert + Checkout
  Session.
- `POST /api/services/<slug>/book` — same shape, returns
  `{action: 'redirect', url}` (dispatcher envelope).
- `POST /api/stripe/webhook` — flips the row state via
  `checkout.session.completed` / `.expired`.

## Key files
- `app.py` — `api_events_rsvp` (~7423), `api_book_service`
  (~30586), webhook router (~31046), expired handlers (~30964,
  ~31126).

## External dependencies
- Postgres `FOR UPDATE` row locks (no advisory locks, no Redis).
- Stripe — both the Checkout Session create and the expired
  webhook.

## Pitfalls
- **Lock the parent, not the reservation table.** A `FOR UPDATE`
  on `events.id` serialises all RSVPs for *that* event without
  blocking RSVPs for other events. Locking the entire RSVP table
  would kill throughput.
- **Stripe Session create happens OUTSIDE the transaction.** The
  Stripe API call is slow (hundreds of ms) and might fail; you do
  not want to hold a row lock during that. Commit the pending row
  first; if Stripe create fails, the next visitor sees the
  pending row and bounces, and an admin can mark it expired or
  the `checkout.session.expired` webhook eventually does — at
  worst the seat is held for the Stripe Session TTL (24 h
  default).
- **Pending must count as taken.** The availability resolver
  (skill 01) and the RSVP-count query in skill 05 both rely on
  this. Drop it and you re-introduce the double-sell.
- **Expired webhook must release the seat.** Without the expired
  branch, abandoned Stripe sessions hold seats forever. Stripe
  fires `checkout.session.expired` 24 h after Session creation
  (or sooner if you set a custom `expires_at`).
- **Idempotency on the webhook.** Both `completed` and `expired`
  can deliver more than once. Use `SELECT ... FOR UPDATE` on the
  row and check the current `payment_status` before mutating — see
  `../payments/02-idempotent-stripe-webhook.md`.
- **Multi-guest RSVPs consume multiple seats.** A row with
  `guests = 4` counts as 4 toward capacity; the count must SUM
  guests, not COUNT rows.
- **Don't shorten the lock by reading capacity outside the
  transaction.** "Read capacity, then `FOR UPDATE` insert" lets
  two concurrent transactions both pass the pre-check.
  Read capacity inside the locked region.

## Adaptation notes
- The same pattern is the right answer for any "hold inventory
  while the customer pays" problem: hotel rooms, concert tickets,
  workshop seats, equipment rentals.
- If you can't use Postgres `FOR UPDATE` (e.g. SQLite, MySQL with
  a different isolation level), the alternatives in order of
  preference are: serializable transactions with retry, advisory
  locks keyed on the parent id, or a single-writer queue. Each
  has worse throughput properties than `FOR UPDATE`.
- For very high contention (a flash-sale event with 100k
  visitors), shard the parent row into N "buckets" and assign
  each visitor a bucket on arrival — turns one hot row into N
  warm rows. Overkill for normal SaaS use.

## Related skills
- `01-weekly-availability-engine.md` — consumer of pending-state
  rows.
- `05-tri-mode-event-rsvps.md` — the canonical caller for events.
- `03-offline-contract-upload.md` — same reservation, different
  release condition (admin review timeout instead of Stripe TTL).
- `../payments/01-stripe-checkout-dispatcher.md` — what runs
  outside the transaction after the pending row commits.
- `../payments/02-idempotent-stripe-webhook.md` — the deduped
  state transitions.
