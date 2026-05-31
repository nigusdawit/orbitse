---
name: Adding tables — _DDL vs Alembic
description: Why new tables must go in an Alembic migration, not just schema.py _DDL, on this AI Concierge platform
---

# New DB tables need an Alembic migration, not just the legacy `_DDL`

On the AI Concierge platform (Flask monolith), `admin_ai_platform/schema.py`
holds a big `_DDL` string run by `init_db()` on boot. It is the **legacy
fresh-install path only**. On any existing database it does **not** create
newly-added tables.

**Why:** `init_db()` runs the entire `_DDL` as a single `cur.execute(_DDL)` in
one transaction. That statement currently fails partway through with
`UndefinedColumn: column "tenant_id" does not exist` (a CREATE INDEX in the
string references a column that isn't present on the live DB). The error aborts
the whole transaction, so **nothing** in `_DDL` commits — including any table you
just appended. The failure is swallowed by a try/except in
`admin_ai_platform/__init__.py` (`schema init failed (continuing)`), so boot
looks healthy while your table silently never appears. The live schema is owned
by Alembic migrations under `migrations/versions/` (`alembic upgrade head` runs
at boot).

**How to apply:** When adding a table, add it to `_DDL` for fresh installs **and**
create a new Alembic migration (`migrations/versions/NNNN_*.py`) with the same
`CREATE TABLE IF NOT EXISTS`. Set `down_revision` to the current single head
(merge-revision if there are parallel branches — e.g. `0006_merge_rag_heads`
merged two `0005_` heads). Run `python -m alembic upgrade head` to apply, then
verify with `SELECT to_regclass('public.<table>')`.
