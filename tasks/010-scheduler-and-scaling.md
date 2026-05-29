# Task 010 — M10: scheduler ticks + multi-worker safety + backed rate limit

## Goal
Make all recurring background work actually fire, safely under multiple workers,
and move the rate limiter off in-process memory.

## Acceptance criteria
- [ ] Register scheduler ticks in create_app: weekly cost digest, scrape-schedule
      dispatch (+ auto-pause/resume), review collector + auto-ask sweep, RAG
      reindex, messaging campaign `send_at` dispatch.
- [ ] Wire `cost.set_warn_email_sender` digest send via messaging; digest is
      idempotent per (tenant, week_start).
- [ ] Multi-worker safety: only ONE worker runs ticks (Postgres advisory lock or
      a `scheduler_leader` row with heartbeat).
- [ ] ProxyFix configured with a trusted-hop count; `_client_ip()` correct behind
      a proxy.
- [ ] Rate limiter backed by Postgres (or Redis if `REDIS_URL` set) so limits hold
      across workers; in-process stays as fallback.

## Test requirements
- Gate: invoking each tick fn directly performs its action (e.g. a due scrape
  schedule spawns a job; a due campaign sends/logs; digest writes one row).
- Gate: advisory-lock leader election (second acquire fails); rate limit holds
  with the backed store.

## Dependencies: none   ## Status: not_started   ## Branch: task/010-scheduler-and-scaling
