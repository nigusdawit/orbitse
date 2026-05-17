# Campaign Manager (Bulk Email + SMS with Scheduler)

**Category:** Messaging
**Related:** `messaging/01-unified-send-helper.md`, `messaging/02-merge-tag-templates.md`, `messaging/05-stop-keyword-optout.md`

## When to use
The admin needs to compose one message (subject + body + merge tags), pick a recipient filter (all subscribers, tagged segment, manually selected), optionally schedule it for later, and have the platform fan it out across hundreds/thousands of recipients with a per-recipient log row, opt-out enforcement, and resumable status.

## Architecture
- **Two tables**: one row per campaign (`messaging_campaigns`), one row per send attempt (`messaging_log`, see skill #1). They're joined by `messaging_log.campaign_id`.
- **Status state machine** on the campaign row: `draft → queued → sending → sent` (or `failed`/`cancelled`). The `sent_at` / `started_at` / `finished_at` timestamps gate UI behavior (you can't edit a campaign once it's `sending`).
- **An in-process scheduler thread** (from skill — see `messaging.start_scheduler`) ticks every 30 seconds and calls registered tick callbacks. One of those callbacks is `_dispatch_due_campaigns` which finds any campaign where `status='queued' AND send_at <= now()` and starts processing.
- **Per-recipient loop** snapshots subject+body (with merge tags rendered), enforces opt-out (`subscribers.opt_in_email` / `opt_in_sms`), calls the unified send helper, and writes one `messaging_log` row per attempt. Counts (`sent_count`, `failed_count`) are updated incrementally so the admin sees live progress.
- **Single-start scheduler guard** (`_SCHEDULER_STARTED` module global + threading lock) keeps the Flask debug reloader from spawning two scheduler threads.

## Data model
Table `messaging_campaigns` (`app.py:~2767`):

| Column | Purpose |
|---|---|
| `id` SERIAL PK | |
| `name` | Admin-visible label |
| `template_id` FK NULL | Optional reference to a saved template |
| `channel` | `'email'` or `'sms'` |
| `subject_snapshot`, `body_snapshot` | Pre-merge-tag template text |
| `recipient_kind` | `'all'` \| `'tagged'` \| `'manual'` etc. |
| `recipient_filter` JSONB | Free-form selector (tag id, manual id list, ...) |
| `status` | `draft` \| `queued` \| `sending` \| `sent` \| `failed` \| `cancelled` |
| `send_at` | NULL = send-now-on-queue; future timestamp = scheduled |
| `started_at`, `finished_at` | Stamped by dispatcher |
| `total_recipients`, `sent_count`, `failed_count` | Live progress |
| `error_text` | Top-level failure (recipient enumeration crashed, etc.) |
| `created_at` | |

Per-recipient log lives in `messaging_log` — see skill #1.

## API surface
- `GET  /admin/api/messaging/campaigns` — list (`app.py:~37930`)
- `POST /admin/api/messaging/campaigns` — create (`app.py:~37935`)
- `PUT  /admin/api/messaging/campaigns/<id>` — edit (only while `draft`)
- `POST /admin/api/messaging/campaigns/<id>/send-now` — flip `draft → queued` for immediate dispatch (`app.py:~38017`)
- `POST /admin/api/messaging/campaigns/<id>/cancel` — flip `queued → cancelled` (no-op once sending) (`app.py:~38002`)

Scheduler:
- `messaging.register_tick(fn)` — register a periodic callback (`messaging.py:448`)
- `messaging.start_scheduler()` — idempotent thread start (`messaging.py:466`)
- `_dispatch_due_campaigns` — the registered tick (`app.py:~32989`, registered at `~33062`)
- `_send_campaign(campaign_id)` — the per-campaign worker (`app.py:~33028`)

## Key files
- `messaging.py:442-481` — scheduler primitives
- `app.py:~2767` — `messaging_campaigns` DDL
- `app.py:~37930..38050` — admin CRUD endpoints (under `/admin/api/messaging/campaigns`)
- `app.py:~32989` — `_dispatch_due_campaigns` tick
- `app.py:~33028` — `_send_campaign` dispatcher
- `app.py:~33062` — `messaging.register_tick(_dispatch_due_campaigns)` registration

## External dependencies
- Whatever the leaf helpers need (Resend / Twilio)
- No queue server — the in-process scheduler is intentional for single-VM deployments

## Pitfalls
- **The scheduler is in-process.** Two web workers = two schedulers = two sends per campaign. Mitigate with `SELECT ... FOR UPDATE SKIP LOCKED` when claiming the campaign row, OR run the scheduler only in a dedicated worker process. The current code uses a fast `UPDATE ... WHERE status='queued' RETURNING` claim pattern; verify before scaling out.
- **Long campaigns block the tick.** If a 5000-recipient send takes 20 minutes, the next tick can't fire for 20 minutes (single thread, sequential callbacks). Either spawn a background thread per campaign or shard recipients across multiple ticks (current code does the former — verify).
- **No retries on per-recipient failure** by default. A transient Resend 5xx becomes a permanent `failed` row. If you need retries, add a `retry_count` column and re-queue rows where `status='failed' AND retry_count < N`.
- **Opt-out check happens at send time, not enqueue time.** A subscriber who unsubscribes after a campaign is queued but before their row is sent will be skipped — which is correct, but means `total_recipients` may exceed `sent_count + failed_count` (skipped doesn't increment either).
- **Webhook race**: provider webhooks for `delivered`/`opened` can arrive before the in-process `sent` write commits if the worker is slow. The webhook handler must `INSERT ... ON CONFLICT DO UPDATE` keyed on `provider_message_id` to be safe.

## Adaptation notes
- To add A/B testing, store two `body_snapshot` columns and a `variant` field on each `messaging_log` row.
- To support drip / sequence campaigns, add a parent `sequence_id` and a per-step `delay_after_previous_seconds`. The scheduler tick already runs every 30s, which is granular enough for typical drip cadences (hourly/daily).
- To move off the in-process scheduler, replace `register_tick` with a cron / k8s CronJob hitting a `POST /admin/api/scheduler/tick` endpoint that calls the same callbacks. Keep `register_tick` as a debug-only fallback.
- The same scheduler primitive (`register_tick` / `start_scheduler`) is reused by Scrape Schedules, Review-Ask sweeps, and the Weekly Digest — any periodic "find due rows and process them" job belongs here.
