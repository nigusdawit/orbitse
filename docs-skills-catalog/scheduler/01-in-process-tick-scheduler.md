# In-Process Tick Scheduler

## When to use
You need recurring background work (every N seconds/minutes) but don't want to add Celery, RQ, Redis, or any external worker process. Examples: poll for queued SMS to send, sweep expired sessions, send weekly digests, claim auto-review-ask rows N days after purchase, re-embed changed KB documents every 6 hours.

## Architecture
A **single daemon thread** runs inside the Flask app process. It wakes every ~30 seconds and calls each registered tick function in sequence, swallowing exceptions so one broken tick can't stop the loop. The thread is spawned lazily on the first incoming HTTP request via a `before_request` hook — that guarantees the scheduler doesn't run inside Flask's dev-mode reloader parent process (which would give you two threads doing the same work) and starts cleanly under both `python app.py` and Gunicorn.

Ticks themselves are responsible for:
- Their own "is it time to run yet?" gate (compare `last_run_at` to `interval_seconds`).
- Their own idempotency (see `03-once-per-period-idempotency.md`) — at-least-once is the only guarantee.
- Their own DB connection acquire/release.

## Data model
None of its own. Each tick owns its scheduling state — typically a `last_run_at TIMESTAMPTZ` column on a config row, or a dedicated `..._sends` / `..._runs` table with a UNIQUE constraint for slot claiming.

## API surface
```
messaging.register_tick(name: str, fn: Callable, interval_seconds: int)
messaging.start_scheduler()   # called by the before_request hook, idempotent
```
Modules register their ticks at import time. `start_scheduler()` uses a module-level flag + lock so concurrent first-requests don't double-spawn.

## Key files
- `messaging.py` — `register_tick`, `start_scheduler`, the daemon loop.
- `app.py` — `before_request` hook that calls `messaging.start_scheduler()`.
- `automations.py`, every scheduler-consuming module — call `messaging.register_tick(...)` at import time.

## External deps
None. Pure `threading.Thread(daemon=True)` + `time.sleep()`.

## Pitfalls
- **Gunicorn multi-worker** runs one scheduler thread *per worker*. For coarse polling (every 30s) this is fine; for once-per-period work, rely on the DB-claim idempotency pattern, never on "only one thread will run this."
- **Long ticks block the loop.** A tick that takes 45s delays every other tick by 45s. Keep tick bodies short or fan out work into the same thread but cap per-iteration batch sizes.
- **No persistence across restart.** If the process dies between two 30s wakeups, the missed wakeups are simply skipped — your "every 6 hours" tick may slide by up to 30s per cycle. That's almost always acceptable; if it isn't, you need a real job queue.
- **Dev reloader.** Flask's debug reloader forks twice. The `before_request` lazy start avoids that by only spawning inside the worker process that actually handles requests.
- **Exception logging is on the tick.** The loop catches and ignores; the tick must log its own errors or you'll never know they failed.

## Adaptation notes
- For sub-second precision, this isn't your tool — use APScheduler or a real queue.
- For multi-process coordination (you NEED exactly one runner), pair this with a Postgres advisory lock at the top of the tick body, or with the once-per-period claim pattern.
- Replace the 30s constant with a per-tick wake schedule only if you actually need it; the current "everyone wakes together every 30s" is dead simple and easy to reason about.

## Adoption checklist
- [ ] Copy `register_tick` + `start_scheduler` + the daemon loop from `messaging.py`.
- [ ] Add a `before_request` hook (or equivalent for your framework) that calls `start_scheduler()`.
- [ ] For each recurring job: write a tick function, give it its own "is it time?" gate, register at module import.
- [ ] Verify under `flask run --debug` that only one thread runs (check logs for double-emit).
- [ ] Pair with the idempotency pattern for any tick that sends email/SMS/money.
