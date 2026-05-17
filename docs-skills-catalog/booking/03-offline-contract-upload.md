# Offline Contract Upload (Tokenized Public Page)

**Category:** Booking · Document workflow
**Status:** Production

## When to use
Some services need a paper-style agreement signed before the
booking is "real" — venue rentals, photography sessions, legal
work, anything where Stripe Checkout isn't the right primitive
because the operator wants a counter-signed PDF on file. You want
the client to download a template from the admin, sign it on their
own time (in person, DocuSign, scanner), and upload the signed
copy back — all without giving them an admin login.

## Architecture
- Each service can opt into the contract workflow by setting
  `services.pricing_model = 'contract'` and uploading a template
  to `services.contract_template_url`.
- On booking, the dispatcher returns
  `{action: 'contract_upload', url: '/booking/<token>/contract'}`
  instead of redirecting to Stripe. The token is
  `service_bookings.booking_token VARCHAR(64) UNIQUE` minted at
  insert time (`secrets.token_urlsafe` or similar).
- The public route `GET /booking/<token>/contract` (~app.py:31018)
  renders an upload page that:
  - Validates the token against the booking row.
  - Surfaces the template download link
    (`services.contract_template_url` plus the original filename
    in `services.contract_template_name`).
  - Accepts a multipart upload that writes
    `service_bookings.signed_contract_url`.
- On this branch the upload endpoint flips
  `service_bookings.status` straight to `confirmed` — the
  workflow is "trust + verify after the fact" rather than
  "queue for admin approval". An admin who wants explicit review
  can either change the auto-flip to a `pending_review` state or
  rely on the email notification + manual status flip from the
  bookings table.

## Data model
- `services.pricing_model TEXT` — `'rsvp' | 'deposit' | 'full' |
  'contract'`.
- `services.contract_template_url TEXT` — admin-uploaded PDF/DOC.
- `services.contract_template_name TEXT` — original filename for
  download display.
- `service_bookings.booking_token VARCHAR(64) UNIQUE NOT NULL` —
  the per-booking secret.
- `service_bookings.signed_contract_url TEXT` — populated by the
  upload.
- `service_bookings.status TEXT` — drives the workflow state.

## API surface
- `POST /api/services/<slug>/book` — dispatcher; returns the
  contract upload URL when `pricing_model = 'contract'`.
- `GET /booking/<token>/contract` (~app.py:31018) — public upload
  page.
- `POST /api/service-bookings/<token>/contract` (~app.py:30878) —
  multipart endpoint that writes `signed_contract_url` and
  advances `status` to `confirmed`.
- Admin: `/admin/api/service-bookings/<id>/status` for the review
  flip and `/admin/api/service-bookings/<id>/signed-contract` to
  download the signed copy.

## Key files
- `app.py` — the public token route, the upload endpoint, the
  dispatcher branch that returns `action: 'contract_upload'`.
- `templates/` — Jinja template for the upload page.
- The storage layer (`storage.py` / `image_optimize.py` adjacent
  helpers) handles the actual file write.

## External dependencies
- A storage backend (local `/uploads/`, S3, R2, etc.) for both
  template and signed copy.
- A PDF viewer client-side is *not* required — the link is just a
  download.

## Pitfalls
- **Token, not booking-id, in the URL.** A booking id is
  enumerable; a 64-char URL-safe token is not. The token is the
  entire access control for this page.
- **One token per booking.** Don't rotate it — the URL needs to
  stay valid for as long as the booking takes to sign. If you must
  rotate (suspected leak), invalidate the row and re-issue.
- **Validate content type on upload.** PDF / DOC / DOCX only; size
  cap matching your storage layer. Browsers happily upload `.exe`
  if you let them.
- **Auto-confirm is the current behaviour, not necessarily the
  right one.** This branch flips straight to `confirmed` on upload
  — fast for the client, but means a forged or wrong PDF still
  counts as "booked" until an admin notices. If you adapt this,
  consider a `pending_review` intermediate state and an admin-side
  approval flip; the trade-off is "fast confirmation" vs "verified
  signature on file".
- **Capacity is held the whole time.** A contract booking sits in
  a `pending` payment state for as long as the client takes to
  sign — that may be days. The availability engine (skill 01)
  must keep the slot reserved while this is happening. If you
  want a timeout, add a scheduler that expires un-signed bookings
  after N days and releases the slot the same way the Stripe
  `checkout.session.expired` webhook does (see skill 06).
- **Don't email the template as an attachment.** Email gateways
  rewrite PDFs and strip fields. Always link to the
  `contract_template_url` so the client downloads the canonical
  copy.

## Adaptation notes
- The same tokenized-public-page primitive works for any "fill
  this out without an account" surface: client questionnaires,
  feedback forms, post-event review asks (see the review-collector
  workflow). Keep the token-in-path, body-is-multipart shape.
- For e-signature, swap the upload endpoint for a DocuSign /
  HelloSign integration that webhooks back with the signed URL.
  The token in the URL becomes the correlation id.

## Related skills
- `01-weekly-availability-engine.md` — the slot stays reserved
  until the admin confirms.
- `06-capacity-reservation-pre-checkout.md` — same reservation
  model, different release condition (timeout vs Stripe expiry).
- `../payments/01-stripe-checkout-dispatcher.md` — the dispatcher
  returns `action: 'contract_upload'` instead of `action:
  'redirect'`.
