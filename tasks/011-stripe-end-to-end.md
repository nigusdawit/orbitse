# Task 011 — M11: Stripe end-to-end (orders, bookings, webhook, sync)

## Goal
Real payments: product checkout, paid/deposit service bookings, an idempotent
webhook, and product→Stripe sync. Test-mode keys.

## Acceptance criteria
- [x] Relocate `stripe_client.py` (Tier-1, lazy SDK import) + DI-refactor
      `stripe_sync.py` / `stripe_settings.py` (was `import app`) into the package.
- [x] Products: `POST /api/checkout/create-payment-intent` (Checkout Session)
      → order row (`pending`); public `GET /api/orders/<order_number>`.
- [x] Services: deposit/full booking → Stripe Checkout redirect (replaces the
      M6 "payment_unavailable" stub) with `metadata.kind`.
- [x] `POST /api/stripe/webhook`: real signature verify (`STRIPE_WEBHOOK_SECRET`),
      idempotent `checkout.session.completed`/`expired` routing — flip orders +
      bookings to paid/confirmed (FOR UPDATE), decrement tracked stock, record
      session/PI ids. Claim released on handler failure so a retry reprocesses.
- [x] Product sync: create/update Stripe product+price on product CRUD when
      `autosync_products`; health-check + backfill + sync-status endpoints.
- [x] Orders admin: detail, status, refund (locked + amount-validated + partial);
      customers upsert.

## Test requirements
- Gate (no live Stripe): webhook signature rejection on bad sig; idempotent
  routing via a synthesized verified event (monkeypatch verify); order/booking
  state transitions; sync row upsert logic.
- M21 does the real Stripe test-mode purchase.

## Dependencies: 010   ## Status: done   ## Branch: task/011-stripe-end-to-end

## Notes
Merged to main (--no-ff). Gate: 205/205 green incl. webhook sig-reject/503/
idempotent-replay/expire, order+booking flips, stock decrement, sync upsert
(created/updated/new-price), and refund hardening (over/zero reject, partial,
balance). Unit: `test_stripe.py` pins env-key resolution + product field
mapping. security-review (agent) found 3 real issues — all fixed in a
follow-up commit: webhook claim-release on handler failure (M1), refund FOR
UPDATE + amount validation + idempotency key (H1/H2). Drift: added
`stripe_events` (webhook dedupe) + `orders.refunded_cents`; added stock
decrement on paid + `partially_refunded` status (correctness, in scope). Live
test-mode purchase deferred to M21 (no keys in sandbox).
