# AI review-ask drafter + template wrap

## When to use
Post-purchase / post-booking review requests have a quality tension: a fully personalised AI-written message is on-brand for nothing, but a generic template lands flat. Wrap an LLM-personalised core inside an admin-curated template envelope: the LLM gets a 1–2 sentence "what you bought + first-name greeting" hook, the rest of the message (logo, footer, opt-out, brand voice cues) comes from the template.

Trigger paths:
- Manual: a button on the order or form-submission detail view.
- Automatic: a scheduler sweep that auto-queues an ask N days after `orders.status='paid'` or `event_rsvps.payment_status='paid'`.

## Architecture
Pipeline per request:
1. Resolve recipient (name, email, phone) and `purchased_item` (free-text snapshot — what the AI personalises around).
2. Pick channel (`email`/`sms`) and the matching `review_settings` template (`email_template_id` or `sms_template_id`).
3. Call `gpt-4o-mini` with a small prompt: "Write 1–2 friendly sentences asking {name} how their {purchased_item} went. Match the tone: {brand_tone}."
4. Substitute the model output into the template body (`{{ai_message}}` placeholder) along with the recipient name and the tokenised review link (`/r/<short_token>`).
5. Snapshot the rendered `subject` + `body` onto the `review_requests` row so post-hoc inspection sees what was actually sent.
6. Enqueue via the standard Resend / Twilio sender (Messaging catalog).

The same `review_requests` table is read by:
- The short-link redirect (sets `clicked_at`).
- The internal review form submit (sets `converted_at`).
- The dashboard funnel widget (counts at each stage).

## Data model
- `review_requests` — `id`, `destination_id` (FK to `review_destinations`), `channel` (`email`|`sms`), `recipient_name`, `recipient_email`, `recipient_phone`, `purchased_item TEXT`, `source_kind` (`order`|`submission`|`manual`), `source_id INT`, `status`, `short_token TEXT UNIQUE`, `subject_snapshot`, `body_snapshot`, `send_at`, `clicked_at`, `converted_at`.
- `review_settings` (singleton) — `email_template_id`, `sms_template_id`, `auto_send_days`.
- `messaging_templates` (existing, see Messaging catalog) — body with `{{ai_message}}` placeholder.

## API surface
- `POST /admin/api/reviews/requests` — create + (optionally) immediately send.
- Buttons on order details (`app.py:37262`) and submission details (`app.py:37296`) call the same endpoint.
- Scheduler tick claims paid-N-days-ago rows and creates requests automatically.

## Key files
- `app.py:36314` — gpt-4o-mini personalisation prompt.
- `app.py:36366` — `_create_review_request()` core (template wrap + snapshot + send).
- `app.py:37118` — `POST /admin/api/reviews/requests`.
- `app.py:37262` — order-detail auto-trigger.
- `app.py:37296` — submission-detail auto-trigger.

## External deps
- OpenAI `gpt-4o-mini` (cheap, fast, plenty good for one-sentence personalisation).
- Resend + Twilio for delivery (Messaging catalog).

## Pitfalls
- **Snapshot the rendered body at send time.** Templates and AI drafts change; the audit trail needs the exact text that went out.
- Cap the personalised core to a short character budget. LLMs left to themselves write paragraphs that break SMS segmentation and dilute the call-to-action.
- Strip emoji from SMS bodies unless your template explicitly supports them — SMS encoding flips to UCS-2 on first emoji and the cost doubles.
- Pass `purchased_item` as plain text, not as a row reference. The LLM doesn't need (or want) JSON.
- For SMS, always include opt-out (`STOP to unsubscribe`) — many carriers reject otherwise. The template should own this, not the AI core.
- Trigger idempotency: keep a `UNIQUE (source_kind, source_id)` partial index (where `source_kind != 'manual'`) so the auto-sweep can never double-queue the same order.

## Adaptation notes
- For multi-destination businesses (e.g. multiple hotel properties), key the template lookup by destination so each location can have its own voice.
- Add an A/B test column (`variant`) and tie it to a tiny `messaging_template_variants` table to measure conversion per draft style.
- Replace `gpt-4o-mini` with any cheap chat model — the prompt is tiny.
- Persist the LLM prompt + model + token counts to your cost-events ledger so review-ask spend is visible in the Cost dashboard.

## Adoption checklist
- [ ] Create `review_requests`, `review_settings`, and `review_destinations` tables.
- [ ] Wire an `{{ai_message}}` placeholder convention into your templates.
- [ ] Add the manual trigger button on order + submission detail views.
- [ ] Stand up the auto-sweep scheduler tick keyed on `paid + N days`.
- [ ] Snapshot rendered subject/body on send and prove it via an audit query.
- [ ] Stamp a cost-event row per AI call.
