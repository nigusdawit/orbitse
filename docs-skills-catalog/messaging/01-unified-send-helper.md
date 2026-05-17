# Unified Send Helper (Email + SMS)

**Category:** Messaging
**Related:** `messaging/02-merge-tag-templates.md`, `messaging/03-campaign-manager.md`, `payments/...` (cost ledger reuses the same per-call stamp pattern)

## When to use
You need one abstraction that can deliver either an email (Resend) or an SMS (Twilio) from anywhere in the app — campaigns, transactional notifications, password resets, review-ask blasts, scrape-change alerts, booking confirmations — and you want every send to land in a single audit log row that downstream features (webhooks, retries, cost dashboards) can update by id.

## Architecture
- **Two leaf helpers** that do exactly one thing: call the provider HTTP API with httpx, parse the response, raise `MessagingError` on any failure. No retries, no logging, no cost accounting — those are layered on top.
- **One log row per send attempt** is written by the caller before/after the leaf returns. Status is mutated later by provider webhooks (delivered / opened / clicked / bounced) keyed on the row's `provider_message_id`.
- **No provider SDKs.** Plain httpx keeps the dependency surface tiny and lets the same module work from Lambda, Cloud Run, or a Replit VM with no native build steps.
- **Provider key resolution is pluggable.** Resend prefers a managed connector (so secrets never touch the project), falls back to `RESEND_API_KEY` env var. Twilio is env-only.

## Data model
Table `messaging_log` (created in `app.py` init_db ~line 2795):

| Column | Purpose |
|---|---|
| `id` SERIAL PK | Stable handle for webhook updates |
| `campaign_id` FK NULL | NULL for transactional sends |
| `subscriber_id` FK NULL | NULL for ad-hoc sends to non-subscribers |
| `channel` | `'email'` or `'sms'` |
| `to_address` | Email address or E.164 phone |
| `subject_snapshot`, `body_snapshot` | Rendered, post-merge-tag content. Snapshotting means later edits to the template never change the historical row. |
| `status` | `queued` → `sent` → (`delivered` \| `opened` \| `clicked` \| `bounced` \| `complained` \| `failed` \| `unsubscribed`) |
| `provider` | `'resend'` \| `'twilio'` |
| `provider_message_id` | The provider's id — the key webhooks PATCH on |
| `error_text` | Provider error body, truncated |
| `sent_at`, `delivered_at`, `opened_at`, `clicked_at` | Stamped by either send or webhook |
| `open_count`, `click_count` | Incremented on each webhook hit |
| `is_test` | True for admin "send test" sends so analytics can exclude them |

## API surface
From `messaging.py`:
- `send_email(to_email, subject, html_body, *, text_body=None, from_override=None, reply_to=None, headers=None, tags=None) -> dict` (line 249)
- `send_sms(to_phone, body, *, from_override=None, status_callback_url=None) -> dict` (line 310)
- `resend_status() -> dict` and `twilio_status() -> dict` for admin "Are my creds set?" status badges
- `MessagingError(RuntimeError)` is the single exception type both helpers raise

## Key files
- `messaging.py:249` — `send_email`
- `messaging.py:310` — `send_sms`
- `messaging.py:114` — `resend_status`
- `messaging.py:123` — `twilio_status`
- `app.py:~2795` — `messaging_log` table DDL
- `app.py:~32884` — log row INSERT call site (inside `_send_one`)
- `app.py:~33028` — `_send_campaign` loop that wraps each send in INSERT-then-update pattern
- `app.py:~4401` — `record_sms_cost` writes one `sms_cost_events` row per send, stamping the unit price at write time so historical cost can never drift

## External dependencies
- `httpx` (already in requirements)
- Resend API key (env `RESEND_API_KEY` or managed connector)
- Twilio account SID + auth token + from-number (env-only; integration not used on this project)

## Pitfalls
- **Both helpers raise — never return failure.** Callers MUST wrap in try/except and write `status='failed'` + `error_text` to `messaging_log`, otherwise a transient 5xx will look like a successful send.
- **Resend's `from` must be a verified domain.** First-time setups will get HTTP 403; surface a friendly error in the admin status badge instead of silently failing the send.
- **Twilio SMS bodies > 160 chars become multi-segment** and you pay per segment. The cost helper only knows the segment count after the webhook fires, so re-price the row on `MessageStatus=delivered` rather than at send time.
- **Don't trust the response shape across providers.** Resend returns `{id: "..."}`, Twilio returns `{sid: "..."}`. Normalize into `provider_message_id` at the call site.
- **Per-call cost stamp.** Stamp the unit price on the log/cost row at write time. Editing the pricing table later must never re-price historical sends.

## Adaptation notes
- To swap providers (e.g. add SendGrid), add a third leaf helper with the same signature and bump `provider` to a string union. The log table doesn't need to change.
- To support attachments, add an `attachments=` kwarg to `send_email` — Resend takes a list of `{filename, content (base64)}` dicts.
- For high-volume use, queue the send (e.g. RQ / Celery / Postgres-backed job) and have the worker call these helpers — `messaging_log` already has `status='queued'` for this purpose.
- For multi-tenant SaaS, add `tenant_id` to `messaging_log` and to the connector lookup so each tenant ships from their own verified Resend domain.
