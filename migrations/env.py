"""Alembic environment.

The app does NOT use SQLAlchemy declarative models — it talks to Postgres
through raw psycopg2. So every migration in `migrations/versions/` is
hand-written using `op.execute()`, `op.add_column()`, `op.create_table()`,
etc., and `target_metadata` stays `None` (autogenerate would have nothing
to compare against).

SQLAlchemy is still imported here because Alembic uses its engine plumbing
to open the connection and run the migrations inside a transaction.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# Alembic Config object — gives access to the values within the .ini file.
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No SQLAlchemy models, no autogenerate — every revision is hand-written.
target_metadata = None


def _database_url() -> str:
    """Return the live DATABASE_URL, normalised for SQLAlchemy 2.x.

    Some hosting platforms (Heroku, older Replit images) still emit the
    legacy `postgres://` scheme; SQLAlchemy 2.x requires `postgresql://`,
    so we rewrite it here. Falling back to the alembic.ini placeholder is
    deliberately disabled — running migrations without a real DATABASE_URL
    would either no-op silently or, worse, hit a stub host."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set — required to run Alembic migrations")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def run_migrations_offline() -> None:
    """Render SQL to stdout without opening a DB connection.

    Useful for reviewing what an upgrade WOULD do, e.g.
    `alembic upgrade head --sql > pending.sql`."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the live database.

    Uses NullPool so we don't leave a long-lived connection around after
    the upgrade finishes — the app's own ThreadedConnectionPool handles
    request-time connections separately."""
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
