"""Regression tests for the Replit re-import hardening (task 023).

These pin the six boot-time fixes so a future refactor that regresses one shows
up as a CI failure rather than a broken import on the next deploy:

  * main.py bootstraps the schema at import time (so gunicorn — not just
    `python app.py` — gets a migrated DB).
  * The OpenAI client constructs even with no API key (no import-time crash).
  * X-Forwarded-For is truncated to the first hop / 45 chars before it hits the
    ip_address VARCHAR(45) column.

We import `main` (not just `app`) so the bootstrap runs against whatever
DATABASE_URL points at. Requires a Postgres with pgvector available — the same
embedded-Postgres harness the rest of the DB-backed suite uses.
"""

import uuid

# Importing main triggers the bootstrap-on-import (init_db + Alembic + syncs).
# This is the behavior under test for issue #1 — do not change to `import app`.
import main
import app


def test_app_object_is_exposed_for_wsgi():
    """gunicorn main:app must find a Flask app object."""
    assert main.app is app.app


def test_openai_client_constructs_without_a_key():
    """Issue #2: the module-level OpenAI client must exist regardless of whether
    AI_INTEGRATIONS_OPENAI_API_KEY was set. If construction raised on an empty
    key, `import app` above would already have failed — but assert explicitly so
    the intent is documented and pinned."""
    assert app.openai_client is not None


def test_schema_bootstrapped_on_import():
    """Issue #1/#6: importing main must have created the historical schema
    (init_db) and the Alembic bookkeeping table."""
    pv = app.query_db("SELECT to_regclass('public.page_views') AS t", fetchone=True)
    assert pv and pv.get("t") is not None, "init_db did not create page_views"
    av = app.query_db("SELECT to_regclass('public.alembic_version') AS t", fetchone=True)
    assert av and av.get("t") is not None, "Alembic did not run on import"


def test_xforwarded_for_chain_is_truncated_to_first_hop():
    """Issue #3: a proxy IP chain must not overflow ip_address VARCHAR(45).
    Drive the public pageview tracker with a long chain and assert the stored
    value is the first (originating) hop, within 45 chars."""
    client = app.app.test_client()
    sid = "xfftest-" + uuid.uuid4().hex          # unique → dodges the 30s rate-limit cache
    chain = "203.0.113.7, 10.0.0.1, 172.16.0.1, 192.168.1.1, 198.51.100.23"
    assert len(chain) > 45                       # the raw header WOULD overflow

    resp = client.post(
        "/api/track/pageview",
        json={"session_id": sid, "page_url": "/xff-regression"},
        headers={"X-Forwarded-For": chain},
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)

    row = app.query_db(
        "SELECT ip_address FROM page_views WHERE session_id = %s ORDER BY id DESC LIMIT 1",
        (sid,), fetchone=True,
    )
    assert row is not None, "pageview row was not written"
    stored = row["ip_address"]
    assert stored == "203.0.113.7", f"expected first hop, got {stored!r}"
    assert len(stored) <= 45
