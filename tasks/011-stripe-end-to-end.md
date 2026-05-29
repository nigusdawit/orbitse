# Task 011 — M11: Stripe end-to-end (orders, bookings, webhook, sync)

## Goal
Real payments: product checkout, paid/deposit service bookings, an idempotent
webhook, and product→Stripe sync. Test-mode keys.

## Acceptance criteria
- [ ] Relocate `stripe_client.py` (Tier-1) + DI-refactor `stripe_sync.py` /
      `stripe_settings.py` (currently `import app`) into the package.
- [ ] Products: `POST /api/checkout/create-payment-intent` (or Checkout Session)
      → order row (`pending`); public `GET /api/orders/<order_number>`.
- [ ] Services: deposit/full booking → Stripe Checkout redirect (replaces the
      M6 "payment_unavailable" stub) with `metadata.kind`.
- [ ] `POST /api/stripe/webhook`: real signature verify (`STRIPE_WEBHOOK_SECRET`),
      idempotent `checkout.session.completed`/`expired` routing — flip orders +
      bookings to paid/confirmed (FOR UPDATE), record charge/session ids.
- [ ] Product sync: create/update Stripe product+price on product CRUD when
      `stripe_settings.autosync_products`; health-check + backfill endpoints.
- [ ] Orders admin: detail, status, refund; customers upsert.

## Test requirements
- Gate (no live Stripe): webhook signature rejection on bad sig; idempotent
  routing via a synthesized verified event (monkeypatch verify); order/booking
  state transitions; sync row upsert logic.
- M21 does the real Stripe test-mode purchase.

## Dependencies: 010   ## Status: not_started   ## Branch: task/011-stripe-end-to-end
