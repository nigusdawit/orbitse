"""Schema bootstrap tests.

Requires a reachable Postgres via DATABASE_URL; skipped otherwise so the suite
stays green on machines without a DB (honest skip, not a silent pass).
"""

import os
import pytest

DATABASE_URL = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="DATABASE_URL not set; schema test needs a live Postgres"
)


def _table_exists(name):
    from admin_ai_platform.db import query_db
    row = query_db("SELECT to_regclass(%s) AS t", (f"public.{name}",), fetchone=True)
    return bool(row and row.get("t"))


def test_init_db_creates_in_tables_and_is_idempotent():
    from admin_ai_platform import schema
    from admin_ai_platform.db import reset_pool_for_tests

    reset_pool_for_tests()
    schema.init_db()
    schema.init_db()  # second run must not raise (idempotent)

    # A representative IN table exists...
    assert _table_exists("gallery_cards")
    assert _table_exists("chat_messages")
    assert _table_exists("tenant_cost_caps")
    # ...and a public-web-only table is NOT created by this package.
    for out in schema.OUT_TABLES:
        assert not _table_exists(out), f"package created OUT table {out}"


def test_seed_singletons_present():
    from admin_ai_platform import schema
    from admin_ai_platform.db import query_db

    schema.init_db()
    assert query_db("SELECT id FROM chatbot_settings WHERE id=1", fetchone=True)
    assert query_db("SELECT id FROM agent_provider_settings WHERE id=1", fetchone=True)
    assert query_db(
        "SELECT id FROM model_prices WHERE provider='openai' AND model='gpt-4o-mini'",
        fetchone=True,
    )
