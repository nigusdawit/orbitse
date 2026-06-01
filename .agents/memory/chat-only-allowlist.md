---
name: Public-site gating must exempt machine endpoints
description: When a before_request hook hides public pages by allowlist, webhook/automation/plugin routes must be exempt or deliveries are silently swallowed.
---

Any `before_request` gate that hides the public marketing site by an
allowlist (e.g. chat-only mode) and returns an HTML placeholder for
everything else will, by default, also shadow machine-to-machine routes.

**Why:** Returning a 200 HTML placeholder to a webhook caller makes the
upstream (Stripe/Twilio/Resend/automation) think delivery succeeded, so the
real handler never runs and the event is lost silently — no error anywhere.

**How to apply:** The allowlist must exempt, beyond `/admin` `/api` `/embed`
`/widget` `/uploads` `/static` and the fingerprinted `/bundle.`:
- `/webhooks` (Resend + Twilio), `/automations` (inbound hooks), `/plugin`
  (update.json / download / onboarding distribution).
Stripe webhook + checkout live under `/api`, and SSO under `/admin`, so those
are already covered. Also pass OPTIONS preflight through untouched (embed CORS
relies on it), and fail OPEN if the flag read errors so a DB blip can never
hide the whole site.
