"""Canonical application entry point.

WHY THIS FILE EXISTS
--------------------
The whole app is the Flask monolith in ``app.py``. Historically the only way to
get a fully-bootstrapped instance was to run ``python app.py``, because the
schema bootstrap + one-time sync steps live in that file's
``if __name__ == "__main__":`` block. That block runs under ``python app.py`` but
**NOT** under a WSGI server like gunicorn (gunicorn imports the module and grabs
the ``app`` object — it never executes the ``__main__`` block).

Replit (and most production deploys) run the app via gunicorn, so on a fresh
import the database was never bootstrapped and the app served 500s against empty
tables. This module fixes that: it is the single canonical entry point for BOTH
gunicorn (``gunicorn main:app``) and direct execution (``python main.py``). The
bootstrap runs once, at import time, so it happens no matter how the process is
launched.

Everything here is idempotent — ``init_db`` uses ``CREATE TABLE IF NOT EXISTS``,
Alembic no-ops when already at head, and the sync/backfill helpers upsert. So
re-importing (e.g. multiple gunicorn workers) is safe.

ESCAPE HATCHES (env vars)
-------------------------
* ``SKIP_DB_BOOTSTRAP=1`` — skip the entire bootstrap (schema + migrations +
  syncs). Use when pointing the app at a DB you know is already current and you
  want the fastest possible boot.
* ``SKIP_ALEMBIC=1`` — run ``init_db`` + syncs but skip Alembic migrations.
  Honored inside ``app._run_alembic_upgrade`` itself; useful for emergency
  rollback while a bad revision is still in the tree, OR to boot without the
  RAG/semantic-cache features when pgvector is unavailable (see below).
"""

from __future__ import annotations

import os
import sys

# Importing app.py runs all module-level setup (route registration, client
# construction, DB pool init). The OpenAI client now constructs safely even with
# no API key, so this import can't crash on a freshly-provisioned host.
import app as _app

# The WSGI callable gunicorn/Replit look for: ``gunicorn main:app``.
app = _app.app


# Substrings that identify a boot failure caused by the pgvector extension not
# being available on the Postgres cluster (as opposed to the migration logic
# being wrong). Our migrations are correct and already guard with
# ``CREATE EXTENSION IF NOT EXISTS vector`` — but ``IF NOT EXISTS`` still errors
# if the extension's files aren't installed on the server at all, which aborts
# the migration mid-transaction with one of these signatures.
_PGVECTOR_ERROR_SIGNATURES = (
    "vector.control",                 # could not open extension control file .../vector.control
    'extension "vector"',             # ... "vector" is not available
    'type "vector" does not exist',   # a vector(...) column DDL ran before the extension
    "could not open extension control file",
)


def _looks_like_missing_pgvector(exc: BaseException) -> bool:
    """True if *exc* (or its cause chain) reads like a missing-pgvector failure."""
    seen = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        text = str(cur).lower()
        if any(sig.lower() in text for sig in _PGVECTOR_ERROR_SIGNATURES):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def _bootstrap() -> None:
    """Bring the database in line with the running code, exactly once at boot.

    Mirrors the steps ``app.py``'s ``__main__`` block runs, minus ``app.run``:
    create historical tables, apply Alembic migrations, sync skills, backfill
    chat sessions. Idempotent and safe to call on every import.

    Raises a clear, actionable RuntimeError if the only thing wrong is that
    pgvector isn't available on the cluster — that turns a cryptic
    mid-migration stack trace into a one-line "here's how to fix it" message.
    All other failures propagate unchanged (a stale schema must fail loudly
    rather than serve 500s mid-request).
    """
    if os.environ.get("SKIP_DB_BOOTSTRAP", "").strip().lower() in ("1", "true", "yes"):
        print("[boot] DB bootstrap skipped (SKIP_DB_BOOTSTRAP set)", file=sys.stderr)
        return

    try:
        # 1. Historical tables (CREATE TABLE IF NOT EXISTS — owns pre-Alembic schema).
        _app.init_db()
        # 2. Alembic migrations to head (honors SKIP_ALEMBIC internally; fatal on failure).
        _app._run_alembic_upgrade()
        # 3. Built-in skill catalog → DB rows.
        _app.sync_skills_to_db()
        # 4. Custom skills → agent_skills.
        _app.sync_custom_skills_to_agent_skills()
        # 5. Seed admin_chat_sessions for legacy message-only session ids.
        _app._backfill_admin_chat_sessions()
    except Exception as exc:  # noqa: BLE001 — we re-raise; this only reshapes the message.
        if _looks_like_missing_pgvector(exc):
            raise RuntimeError(
                "Database bootstrap failed because the PostgreSQL 'vector' "
                "(pgvector) extension is not available on this server. The RAG "
                "and semantic-cache features require it.\n"
                "  Fix: enable pgvector on your Postgres "
                "(on Replit: add the pgvector extension to the database, e.g. via "
                "the Agent's 'install pgvector' step / the Database pane), then "
                "restart.\n"
                "  Or: set SKIP_ALEMBIC=1 to boot without the RAG/semantic-cache "
                "migrations (those features stay off until pgvector is present)."
            ) from exc
        raise


# Run the bootstrap at import time so gunicorn (which never executes the
# __main__ block below) still gets a fully-migrated database.
_bootstrap()


if __name__ == "__main__":
    # Direct execution: dev server. Host/port are configurable; Replit sets PORT.
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "").strip().lower() in ("1", "true", "yes")
    app.run(host=host, port=port, debug=debug, use_reloader=False)
