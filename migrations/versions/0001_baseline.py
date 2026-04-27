"""baseline — Alembic adopted on top of the legacy init_db() bootstrap.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-04-27

This migration is intentionally empty. It exists so that:

  * fresh installs have a non-empty migration history to "upgrade" to,
    which causes Alembic to create its `alembic_version` table and
    stamp the starting revision (turning the upgrade into a one-time
    bookkeeping no-op);
  * existing deployments with no Alembic state get the same treatment
    on their next boot — the upgrade walks from `None` to
    `0001_baseline`, runs this empty `upgrade()`, and stamps the row.

After this baseline, every new column or table goes into a fresh
revision file in `migrations/versions/`. The historical tables created
by `init_db()` are NOT redeclared here — they remain owned by the
legacy bootstrap path.
"""

from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401


# revision identifiers, used by Alembic.
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op. See module docstring."""
    pass


def downgrade() -> None:
    """No-op — there is nothing for the baseline to roll back to."""
    pass
