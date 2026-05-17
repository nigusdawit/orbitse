# STOP-Keyword SMS Opt-Out

**Category:** Messaging
**Related:** `messaging/01-unified-send-helper.md`, `messaging/03-campaign-manager.md`

## When to use
You send SMS to subscribers and you need to honor (and be legally required to honor — TCPA, GDPR, CTIA) the recipient's reply of `STOP` (or `CANCEL`, `UNSUBSCRIBE`, `END`, `QUIT`, `STOPALL`) by flipping them to opt-out so no further messages reach their phone.

## Architecture
- **Twilio configured to POST inbound SMS** to a webhook on your domain (`POST /webhooks/twilio/inbound-sms`).
- **Signature verification** (`verify_twilio_signature`) confirms the request actually came from Twilio (HMAC-SHA1 of URL + sorted form params, base64'd, compared against the `X-Twilio-Signature` header). Fail-open in dev when `TWILIO_AUTH_TOKEN` is empty so local testing works.
- **Body normalization** — uppercase, strip whitespace and punctuation — then membership-check against a small set of known opt-out keywords.
- **On match**, flip `subscribers.opt_in_sms = FALSE` for any subscriber whose phone matches the inbound `From` number. The campaign send loop checks this column at dispatch time (see skill #3) so the opt-out takes effect immediately for any queued or future campaigns.
- **Always return 200 + empty TwiML** — Twilio retries with exponential backoff on 5xx, and a stuck retry loop will spam your logs.

## Data model
No dedicated opt-out table. The flag lives on the subscriber row:
- `subscribers.opt_in_sms BOOLEAN DEFAULT TRUE`
- Optionally `subscribers.opt_in_email` for the email equivalent (handled by the unsubscribe-link flow, not by this skill).

If you need an auditable history (when did they opt out, via what message), add a `subscriber_optout_events` table and INSERT a row from the webhook handler — but the boolean alone is enough to be compliant.

## API surface
- `POST /webhooks/twilio/inbound-sms` (`app.py:~38262`) — Twilio webhook receiver, public, signature-verified.

From `messaging.py`:
- `verify_twilio_signature(url, params, header_signature) -> bool` (line 379) — pure function, no I/O.

## Key files
- `messaging.py:379` — signature verification
- `app.py:~38262` — inbound SMS webhook
- `app.py:~38281` — keyword match: `{'stop', 'stopall', 'unsubscribe', 'cancel', 'end', 'quit'}`
- `app.py:~38284` — opt-out flip (`UPDATE subscribers SET opt_in_sms = FALSE WHERE phone = ...`)

## External dependencies
- `TWILIO_AUTH_TOKEN` env var (for signature verification)
- Twilio webhook configured to the public URL of this endpoint

## Pitfalls
- **Phone normalization is essential.** Subscribers may be stored as `+15551234567` while Twilio's `From` arrives as `15551234567` or vice-versa. Normalize both sides to E.164 before comparing.
- **Fail-open on missing auth token is a footgun in production.** The current code does this intentionally so local dev works without Twilio creds (replit.md flags these as placeholders). For production, add a hard env-flag check that refuses to start if `TWILIO_AUTH_TOKEN` is empty AND `FLASK_ENV != "development"`.
- **Reply with `STOP` confirmation.** CTIA requires a single confirmation SMS ("You have been unsubscribed and will receive no further messages"). Twilio's "Advanced Opt-Out" feature handles this on the carrier side — turn it ON in the Twilio console rather than rolling your own, or you'll double-send on the next campaign anyway.
- **`START` / `UNSTOP` re-opt-in must also be handled** — same webhook, opposite flip. CTIA mandates this round-trip.
- **The webhook handler must be idempotent.** Twilio retries on any non-2xx within 15s. If the opt-out flip takes 3 seconds, you might see the same `STOP` twice — the boolean flip is naturally idempotent, but if you log an audit row, dedupe on `(from_number, body, twilio_message_sid)`.
- **Don't trust the body for free-text replies.** Some recipients type "stop spamming me" — that won't match the keyword set. Document that explicit `STOP` is required, or fuzzy-match on word boundaries (`re.search(r"\bstop\b", body, re.I)`).

## Adaptation notes
- The same signature-verification helper is reused for the SMS **status callback** webhook (`MessageStatus=delivered/failed/...`) — different endpoint, same `verify_twilio_signature` call.
- For email opt-out, use the HMAC-signed token (`messaging.make_unsubscribe_token`) embedded in a List-Unsubscribe header + visible footer link, and POST that token to a `/u/<token>` handler that does the equivalent flip on `opt_in_email`.
- If you add WhatsApp via Twilio, the same webhook path receives those inbound messages — discriminate on `From` prefix (`whatsapp:+...`) and flip a separate `opt_in_whatsapp` column.
- For carriers / countries with their own keyword conventions (e.g. some EU networks use `ARRET`), extend the keyword set rather than localizing per-country — the union set is short and free-text matching is more forgiving.
