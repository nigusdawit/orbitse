# Tri-Mode Event RSVPs (Free / Paid / Pay-What-You-Wish)

**Category:** Events · RSVP
**Status:** Production

## When to use
You run events that span every revenue model at once: a free
community meetup, a $40-a-seat workshop, a donation-based fundraiser
with a $10 suggested minimum. You don't want three different
endpoints, three different RSVP tables, and three different success
pages — one event row + one `price_mode` discriminator handles all
three.

## Architecture
- Events table carries a `price_mode TEXT` column in
  `{free, paid, donation}` plus:
  - `price_amount INTEGER` (cents) — used by `paid` mode.
  - `min_donation INTEGER` (cents) — used by `donation` mode as the
    floor; the visitor enters the actual amount.
  - `capacity INTEGER` — total seats; nullable for uncapped events.
- Single endpoint `POST /api/events/<slug>/rsvp` (~app.py:7423)
  branches on `event.price_mode`:
  - **free** — INSERT into `event_rsvps` with
    `payment_status='none'`, return success inline.
    `{"ok": true, "rsvp_id": ..., "status": "confirmed"}`.
  - **paid** — INSERT pending row (`payment_status='pending'`),
    create Stripe Checkout Session with line items
    `price_amount * guests`, return
    `{"ok": true, "checkout_url": "..."}`.
  - **donation** — same as paid but `unit_amount` is the
    visitor-entered amount (validated `>= min_donation`).
- Capacity is enforced at insert time with `SELECT ... FOR UPDATE`
  on the events row (~app.py:7458) — see
  `06-capacity-reservation-pre-checkout.md`.
- Pending rows count against capacity until the webhook flips
  them to `paid` (confirmed seat) or `expired` (seat released).
- Stripe metadata: `kind='event_rsvp', rsvp_id=<int>` so the
  webhook router can dispatch (see
  `../payments/02-idempotent-stripe-webhook.md`).

## Data model
- `events (..., price_mode, price_amount, min_donation, capacity,
  ...)` (~ app.py:1519+).
- `event_rsvps (id, event_id, name, email, guests,
  payment_status, payment_amount, stripe_session_id, ...)`
  (~ app.py:1542+).
  - `payment_status TEXT` in `{none, pending, paid, expired,
    failed, refunded}`. The capacity-count query in
    `api_event_rsvp` excludes `expired` and `failed` (a failed
    Stripe attempt frees the seat); `refunded` is handled by the
    admin-cancel path.
  - `payment_amount INTEGER` (cents) — stamped at insert for paid/
    donation, 0 for free.

## API surface
- `POST /api/events/<slug>/rsvp` body:
  `{name, email, guests, donation_amount?}`.
- Response is one of:
  - `{ok: true, rsvp_id, status: "confirmed"}` (free)
  - `{ok: true, rsvp_id, checkout_url}` (paid / donation)
  - `{ok: false, error: "..."}` (validation or capacity full)

## Key files
- `app.py` — `api_events_rsvp` (~7423), events schema (~1519),
  rsvps schema (~1542).

## External dependencies
- Stripe (for paid + donation).

## Pitfalls
- **Validate `donation_amount >= min_donation` server-side.** The
  visitor can type "1" in DevTools. Refuse with 422 (not 200) so
  the UI can show the error.
- **Don't accept `payment_amount` from the client.** Stamp it from
  the validated input (paid mode) or from
  `session.amount_total` on the webhook (after Stripe collects it
  in donation mode). A client can't be trusted to say what they
  paid.
- **Free path should not create a Checkout Session.** Skipping
  Stripe entirely avoids a needless Stripe API call (and a
  needless seat-held-during-Checkout window).
- **Cap is per-event, not per-RSVP.** A single RSVP for 4 guests
  consumes 4 capacity. Validate `guests <= remaining_capacity`
  inside the `FOR UPDATE` block, not before it.
- **Donation min is a floor, not the default.** The UI should pre-
  fill the suggested minimum but let the visitor override upward;
  the server validates only the floor.
- **`price_mode` change after RSVPs exist is a foot-gun.** Either
  freeze the field once any RSVP exists, or document that
  changing it after the fact only affects future RSVPs (existing
  rows keep their stamped `payment_amount`).

## Adaptation notes
- The three-mode pattern is the right shape for any "give me money,
  maybe": pricing tiers, podcast subscriptions, anything tipped.
  The key column is `price_mode` as a discriminator, not a per-
  feature boolean (`is_free`, `accepts_donations`) which fan out
  into illegal combinations.
- For "pay later" mode (invoice the visitor later), add `'invoice'`
  to the enum and dispatch to a tokenized-invoice page like the
  contract-upload flow.
- If you want recurring events (every Wednesday), the simpler
  approach is to keep one row per occurrence and let the admin
  duplicate; trying to model recurrence on one row makes capacity
  and per-occurrence pricing painful.

## Related skills
- `06-capacity-reservation-pre-checkout.md` — how the pending row
  holds the seat during Stripe Checkout.
- `../payments/01-stripe-checkout-dispatcher.md` — the same
  three-action envelope this endpoint uses to reply.
- `../payments/02-idempotent-stripe-webhook.md` — flips
  `payment_status` to `paid` / `expired`.
