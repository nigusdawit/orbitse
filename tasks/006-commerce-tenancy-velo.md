# Task 006 — M6: Commerce + Tenancy + VELO

## Goal
Commerce (services/bookings + products/orders + Stripe checkout/webhook); tenancy (plans/features,
snapshot/clone, dev console, secrets/env UI, per-tenant embed-key + origin-allowlist management); VELO
master blueprint (DI-wired).

## Acceptance criteria (to expand on first touch)
- [ ] `blueprints/commerce.py` (services/bookings/products/orders + `/api/stripe/webhook`).
- [ ] `blueprints/tenancy.py` (plans/features, snapshot/clone, dev console, secrets, embed-key CRUD +
      per-tenant origin allowlist — feeds M7 auth).
- [ ] `blueprints/velo.py` registers DI-wired `velo_bp`.

## Test requirements (to expand)
- pytest: booking availability computation, Stripe webhook idempotency, embed-key generation +
  allowlist storage, snapshot redaction of secrets.

## Dependencies: 005   ## Parallel-with: —
## Status: not_started   ## Branch: task/006-commerce-tenancy-velo
