---
name: Dual boot entrypoints — seed in both
description: Boot-time seeding/sync must be added to BOTH main._bootstrap() and app.py __main__, not just one.
---

This Flask app has two startup paths that each run their own boot sequence:

- **Production/dev (gunicorn `main:app`)** → `main.py` `_bootstrap()` runs the
  init/seed steps (init_db, alembic upgrade, skill syncs, backfills, prompt sync, etc.).
- **Direct (`python app.py`)** → the `if __name__ == "__main__":` block at the
  bottom of `app.py` runs its OWN near-duplicate sequence.

**Rule:** any new boot-time seeding/sync (e.g. `sync_ai_prompts()`) must be added
to BOTH places, or it silently won't run on whichever path you forgot.

**Why:** the two sequences drifted before — a sync added only to `_bootstrap()`
never ran under `python app.py`. The active workflow uses gunicorn, so the gap is
invisible until someone runs the app directly.

**How to apply:** when adding a boot step, grep for the matching call in
`main.py` `_bootstrap()` and the `__main__` block in `app.py` and add to both.

Related: in-memory caches that are invalidated on write (e.g. the prompt cache)
must take the SAME lock the loader uses inside `_invalidate`, or a load that is
mid-DB-read can set loaded=True with stale data and swallow the invalidation.
