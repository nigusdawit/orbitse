# Auto-pause scheduled jobs on consecutive failures

## When to use
Any recurring background job (scrapes, syncs, polls) that talks to an external service which can break in ways the operator should *notice but not be paged for forever*: the target domain dies, an API key gets revoked, a page layout changes and extraction fails. Without auto-pause:
- the scheduler keeps firing forever,
- the admin gets a notification on every run,
- provider/API costs leak indefinitely.

You want: count consecutive failures, auto-pause after N, surface a clear "paused: repeated failures" state with the last error, and a one-click resume.

## Architecture
Three small columns on the scheduled-job table do all the work:
- `consecutive_failures INT DEFAULT 0` — incremented on each failed run, **reset to 0 on a successful run**.
- `failure_threshold INT DEFAULT 5` — per-schedule, `0` disables auto-pause.
- `auto_paused BOOLEAN DEFAULT FALSE` — set when threshold is hit.

After every run, a single hook (`_scrape_after_schedule_run`) does:
1. If the run failed and `failure_threshold > 0`, `consecutive_failures += 1`. If `new_count >= failure_threshold`, flip `enabled=FALSE`, `auto_paused=TRUE`, `next_run_at=NULL`. Store the error in `last_error`.
2. If the run succeeded, set `consecutive_failures=0`, `auto_paused=FALSE`, recompute `next_run_at`.

The list endpoint surfaces `auto_paused=TRUE` rows with a coloured badge and the `last_error` text. A dedicated resume route clears the failure trail and re-arms the schedule in one shot.

The pattern generalises beyond scrapes — apply it to any scheduled work (scheduled emails, recurring imports, periodic exports).

## Data model
Added to `scrape_schedules` (or whichever scheduled-job table you have):
- `consecutive_failures INT NOT NULL DEFAULT 0`
- `failure_threshold INT NOT NULL DEFAULT 5`
- `auto_paused BOOLEAN NOT NULL DEFAULT FALSE`
- `last_error TEXT NULL`
- `enabled BOOLEAN NOT NULL DEFAULT TRUE`

## API surface
- `POST /admin/api/scrape-schedules/<id>/resume` — atomic reset: `consecutive_failures=0`, `auto_paused=FALSE`, `enabled=TRUE`, `next_run_at=NOW()` (or the next cadence point), `last_error=NULL`.
- Existing list endpoint exposes the three fields so the UI can render the badge.
- Admin edit form lets operators tweak `failure_threshold` per schedule (set to 0 to disable).

## Key files
- `app.py:35065` — `_scrape_after_schedule_run()` (failure increment + auto-pause decision).
- `app.py:36071` — `POST /admin/api/scrape-schedules/<id>/resume`.

## External deps
None.

## Pitfalls
- **Reset on success, not on every run.** A run that succeeds after 4 failures should bring `consecutive_failures` back to 0; a run that fails after a success should start the counter at 1, not increment from an old value.
- A successful run should also clear `last_error` so the badge UI doesn't show stale text after recovery.
- Make the threshold per-schedule, not global. Different targets fail for different reasons (a stable competitor's site might warrant 3, a flaky one 10).
- `failure_threshold=0` must mean "never auto-pause" — implement as `if threshold > 0 and new_count >= threshold`. Off-by-one here means everything pauses at zero failures.
- Don't re-fire on resume immediately if the failure cause is global (auth outage) — small initial backoff (e.g. `next_run_at = NOW() + 60 s`) prevents thundering herd.
- Send exactly one "now paused" notification (on transition), never one per subsequent skipped tick. Idempotency hinges on the `auto_paused` flag flipping from false to true.

## Adaptation notes
- Pair with a "see paused jobs at a glance" admin index — flat row count drives operator triage.
- Optional `paused_at TIMESTAMPTZ` + `resumed_at TIMESTAMPTZ` columns enable a small history widget without a full audit log.
- For very flaky targets, swap a fixed threshold for an exponential-backoff schedule (`next_run_at = NOW() + base * 2 ** failures`) instead of pausing.
- The same three columns work for cron-job scheduling libraries (Celery beat, APScheduler) — wrap their task body in the same failure-counting hook.

## Adoption checklist
- [ ] Add the four columns to your schedule table.
- [ ] Implement the post-run hook with the reset-on-success rule.
- [ ] Add the resume endpoint and a "Paused" badge + Resume button in the admin UI.
- [ ] Emit exactly one notification on the false→true `auto_paused` transition.
- [ ] Document `failure_threshold=0` semantics in the admin tooltip.
- [ ] Consider a small initial backoff on resume to avoid thundering herd.
