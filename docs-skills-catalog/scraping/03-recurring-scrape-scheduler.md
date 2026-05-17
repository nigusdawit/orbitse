# Recurring scrape scheduler (change-only notify)

## When to use
You have a small but valuable set of pages an admin wants to monitor on a cadence (competitor pricing, supplier inventory, partner site copy). You want:
- multiple cadence modes (hourly/daily/weekly/every-N-minutes),
- per-schedule delivery via email and/or SMS,
- a "notify only when content changed" mode so admins aren't paged for identical fetches.

## Architecture
A `scrape_schedules` table stores one row per recurring job. A daemon-thread tick (registered via the messaging scheduler hub — see the messaging catalog's tick-scheduler skill) wakes every minute, claims schedules whose `next_run_at <= NOW()`, runs them via the same `scrape_jobs` pipeline, and recomputes `next_run_at` from the cadence.

Cadence modes (`schedule_mode`):
- `interval` — every `interval_minutes` minutes (lower bound enforced server-side).
- `daily` — at `daily_time` (UTC; pair with a TZ-aware variant if needed).
- `weekly` — `weekly_dow` (0–6) at `daily_time`.

Change detection:
1. After a successful run, `_scrape_compute_signature` produces a SHA-1 of the canonicalised JSON result.
2. If `notify_only_on_change` is true, compare against the previous row's `signature_hash`. Equal → skip notification; different (or first run) → notify and persist the new hash.
3. Plain `notify_email` / `notify_phone` settings drive Resend / Twilio sends through the existing messaging path so the cost+log surfaces apply (see Messaging catalog).

## Data model
`scrape_schedules`:
- `id`, `name`, `enabled BOOLEAN`, `auto_paused BOOLEAN` (see auto-pause skill)
- `input_mode`, `url`, `objective`, `target_shape`, `custom_schema JSONB`
- `schedule_mode` ENUM, `interval_minutes INT`, `daily_time TIME`, `weekly_dow INT`
- `notify_email TEXT`, `notify_phone TEXT`, `notify_only_on_change BOOLEAN`
- `failure_threshold INT` (default 5; 0 disables auto-pause)
- `consecutive_failures INT`, `last_run_at`, `next_run_at`, `signature_hash`

Child `scrape_jobs` rows are created per run with `schedule_id` pointing back.

## API surface
- `GET /admin/api/scrape-schedules` — list.
- `POST /admin/api/scrape-schedules` — create.
- `PATCH /admin/api/scrape-schedules/<id>` — edit / pause / resume (also see auto-pause skill for the dedicated resume endpoint).
- `DELETE /admin/api/scrape-schedules/<id>`.

Programmatic:
- `_scrape_schedule_tick()` — daemon tick body.
- `_scrape_compute_signature(result_dict) -> str` — SHA-1 of canonical JSON.
- `_scrape_send_change_notification(schedule, prev_hash, new_hash, result)` — fan-out to Resend/Twilio.

## Key files
- `app.py:34401` — `_scrape_compute_signature()`.
- `app.py:35065` — `_scrape_after_schedule_run()` (writes hash + reschedules + handles failures).
- `app.py:35188` — `_scrape_send_change_notification()`.
- `app.py:35355` — `_scrape_schedule_tick()` daemon body.
- `app.py:35911` / `35921` — list / create routes.

## External deps
Same as the URL+Objective scraper, plus the messaging tick scheduler hub for the recurring fire.

## Pitfalls
- **Canonicalise before hashing.** `json.dumps(..., sort_keys=True)` so dict key order doesn't produce false-change notifications.
- Strip volatile fields (`scraped_at`, request IDs) from the signature input — they change on every run and would defeat change detection.
- Run schedules in a worker pool with a small concurrency cap. One bad target (slow site, ScrapingBee outage) shouldn't starve the tick.
- Always `SELECT … FOR UPDATE SKIP LOCKED` (or equivalent) when claiming due rows so multi-worker deployments don't double-run a schedule.
- For interval mode, enforce a minimum (e.g. 5 minutes) — admins type "1" expecting "once a day" surprisingly often.
- Time-zone: store `daily_time` and `weekly_dow` in a consistent zone (UTC is simplest; document it). Mixed-zone schedules are a debugging nightmare.

## Adaptation notes
- Add a `cron_expression` mode with `croniter` if admins ask for complex cadences.
- Per-tenant timezone column unlocks "Monday 9am their time" without a CRON DSL.
- Optional `keep_last_n_runs` retention policy on `scrape_jobs` keeps the table small.
- For "diff me the changes" UX, store the prior cleaned text alongside the signature and render a unified diff in the notification email.

## Adoption checklist
- [ ] Create the `scrape_schedules` table and a `signature_hash` column on `scrape_jobs`.
- [ ] Register the tick with your scheduler hub (1-minute cadence is fine).
- [ ] Implement `_scrape_compute_signature` with sorted-keys JSON.
- [ ] Wire notify-on-change into the same Resend/Twilio sender used elsewhere.
- [ ] Add admin UI for cadence + email/phone + "notify only on change" toggle.
- [ ] Enforce a minimum interval and document the storage timezone.
