# Task 010 — M10: scheduler ticks + multi-worker safety + backed rate limit

## Goal
Make all recurring background work actually fire, safely under multiple workers,
and move the rate limiter off in-process memory.

## Acceptance criteria
- [x] Register scheduler ticks in create_app: weekly cost digest, scrape-schedule
      dispatch (+ auto-pause/resume), review collector + auto-ask sweep, RAG
      reindex, messaging campaign `send_at` dispatch.
- [x] Wire `cost.set_warn_email_sender` digest send via messaging; digest is
      idempotent per (tenant, week_start).
- [x] Multi-worker safety: only ONE worker runs ticks (Postgres advisory lock in
      `scheduler.py` leader election).
- [x] ProxyFix configured with a trusted-hop count (`TRUSTED_PROXY_HOPS`);
      `_client_ip()` uses the proxy-resolved `remote_addr`.
- [x] Rate limiter backed by Postgres (`rate_buckets`, atomic UPSERT) so limits
      hold across workers; in-process stays as fallback. (Redis hook deferred —
      `REDIS_URL` reserved; Postgres path satisfies the multi-worker requirement.)

## Test requirements
- Gate: invoking each tick fn directly performs its action (e.g. a due scrape
  schedule spawns a job; a due campaign sends/logs; digest writes one row).
- Gate: advisory-lock leader election (second acquire fails); rate limit holds
  with the backed store.

## Dependencies: none   ## Status: done   ## Branch: task/010-scheduler-and-scaling

## Notes
Merged to main (--no-ff, merge commit `1123af1`). Gate: 175/175 green incl. new
M10 checks (Postgres rate limiter cap/persist, scrape/campaign/review tick
dispatch + skip-not-due, all ticks registered). Unit: `test_scheduler_ticks.py`
pins `_compute_next_run` (interval/daily/weekly/fallback). Drift: also added a
`/admin/api/messaging/campaigns/<id>/schedule` route (needed a way to set
`send_at`/queue a campaign so the dispatch tick has work) and fixed a
falsy-zero bug coercing `weekly_dow=0` (Monday) → Tuesday.
