# Stripe Checkout Dispatcher

**Category:** Payments · Checkout
**Status:** Production

## When to use
You have several pay-for-this surfaces (event RSVPs, service bookings,
product orders) that each have multiple pricing modes — some flows
charge nothing, some charge a fixed amount, some let the visitor type
the amount, some charge only a deposit. You want one consistent
contract: the backend decides what should happen and returns a small
JSON envelope; the frontend dispatches on a single `action` field
instead of branching on prices/flags itself.

## Architecture
- Every booking/order endpoint returns one of three shapes:
  - `{"action": "rsvp_confirmed", ...}` — free path; the row is saved
    immediately with `payment_status='none'` and the success view
    renders inline.
  - `{"action": "redirect", "url": "<stripe-session-url>"}` — paid
    path; the row is inserted with `payment_status='pending'`,
    a Stripe Checkout Session is created, and the visitor is sent
    to it. The success/cancel URLs include
    `?session_id={CHECKOUT_SESSION_ID}` so the success page can
    confirm fulfilment client-side without trusting the URL alone.
  - `{"action": "contract_upload", "url": "/booking/<token>/contract"}`
    — services with a contract template that the client signs and
    re-uploads (offline payment).
- Capacity is reserved at the moment the pending row is created so
  the seat/slot can't be double-sold while the visitor is still in
  Checkout. The webhook later flips it to `paid` or `expired`.
- Every Checkout Session sets a `metadata.kind` discriminator
  (`event_rsvp`, `service_booking`, `product_order`, `donation`,
  `service_balance`, ...) plus the local row id (`rsvp_id`,
  `booking_id`, `order_id`). The webhook router uses **only** these
  two fields to dispatch — see `02-idempotent-stripe-webhook.md`.

## Data model
No table is owned by the dispatcher itself; it writes into whichever
domain table the surface uses (`event_rsvps`, `service_bookings`,
`orders`). Every such table needs at least:

- `payment_status TEXT` in {`none`, `pending`, `paid`, `expired`,
  `refunded`}.
- `stripe_session_id TEXT` (nullable).
- `amount_paid_cents INTEGER` (stamped from the webhook payload, not
  trusted from the request body).

## API surface
The dispatcher pattern is per-surface, not centralised. Examples in
this codebase:

- `POST /api/events/<slug>/rsvp` — free / paid / donation.
- `POST /api/services/<slug>/book` — rsvp / deposit / full / contract.
- The product-order and balance-payment paths follow the same shape;
  exact route names vary by branch — search for
  `Checkout.Session.create` to enumerate them.

Each one wraps the same primitive: `stripe.checkout.Session.create(
  mode="payment", line_items=[...], metadata={"kind": "...", "<id>":
  <int>}, success_url=..., cancel_url=...)`.

## Key files
- `app.py` — the four endpoints listed above (see grep for
  `Checkout.Session.create`).
- `stripe_client.py` — `get_stripe()` resolves the right key for the
  current mode (test/live).

## External dependencies
- Stripe Python SDK.
- A configured Stripe key (live or test) via the auth/secrets layer.

## Pitfalls
- **Reserve the seat at row-create time.** A naive "save on webhook"
  loses races: two visitors hit Checkout for the last seat, both
  succeed, only one has a chair. The pending row pre-claims the seat;
  the `expired` webhook releases it on abandonment.
- **Never trust the request body for amounts.** Read the price from
  the local row at Session.create time and stamp `amount_paid_cents`
  from the webhook payload on completion. A client can edit any
  number in DevTools.
- **Don't reuse one Checkout Session.** Each booking attempt should
  create a new Session; reusing one across retries makes the success
  URL ambiguous about which attempt completed.
- **`?session_id={CHECKOUT_SESSION_ID}` is a Stripe template** — keep
  the literal `{CHECKOUT_SESSION_ID}` in the success_url string. The
  Stripe SDK substitutes it at redirect time.

## Adaptation notes
- The three-action envelope is the only piece worth porting verbatim;
  the surface-specific create paths are short and clearer when
  written per-resource than threaded through a single mega-function.
- If you add a new pricing mode (e.g. instalments), add a new
  `metadata.kind` rather than overloading an existing one — the
  webhook router branches on this string.

## Related skills
- `02-idempotent-stripe-webhook.md` — the other half of the contract.
- `03-stripe-product-price-sync.md` — keeps catalog Prices in sync
  so `line_items[].price` references stay valid.
- `04-three-tier-cost-caps.md` — the chat/voice equivalent of "don't
  let one surface run up unlimited spend".
