---
name: query_db fetchone gotcha
description: query_db() returns a LIST by default; callers using row.get(...) must pass fetchone=True or the .get() raises and may be silently swallowed.
---

# query_db() returns a list unless fetchone=True

`query_db(sql, params=None, fetchone=False)` in app.py returns `list[dict]` by
default and only returns a single `dict` when `fetchone=True` is passed.

**Why this bites:** several call sites do `cs = query_db("SELECT ... WHERE id=1")`
then `cs.get("col")`. On a list that raises `AttributeError`. When the call is
wrapped in `try/except Exception: pass` (common in prompt-assembly code), the
failure is silent — the feature just never applies and there is no log line.

**How to apply:** any `query_db(...)` whose result you treat as a single row
MUST pass `fetchone=True`. When adding columns to such a SELECT, re-check that
the existing call already has `fetchone=True` — a missing one is a latent bug
that swallows the whole block, not just your new column.
