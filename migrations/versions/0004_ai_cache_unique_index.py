"""ai_response_cache — add unique index on (query_text, content_version).

Revision ID: 0004_ai_cache_unique_index
Revises: 0003_ai_response_cache
Create Date: 2026-04-30

Why this migration exists
-------------------------
The original 0003 migration created the cache table without a uniqueness
constraint.  Code review flagged a real concurrency hazard:

  * Two visitors ask the same novel question in the same second.
  * Both /api/chat workers miss the lookup, generate fresh replies,
    and call save_to_cache(). Two duplicate rows for the same question
    end up in the table — wasted bytes, and worse, the IVFFlat index
    can return either depending on order, polluting recall stats.

A unique key on (query_text, content_version) makes save_to_cache safe to
race against itself.  Combined with `ON CONFLICT (query_text,
content_version) DO NOTHING` in semantic_cache.save_to_cache, the loser
of any race silently drops its insert and the winner's row gets the
hit_count bump on the very next lookup.

Why (query_text, content_version) and not just query_text?
A bumped content_version legitimately wants a fresh row for the SAME
question (so the admin can see Top Questions across versions and so a
post-Backfill table contains the new answer).  Including version in the
key allows that while still preventing within-version duplicates.

Safety
------
- IF NOT EXISTS guard so re-running the migration on a DB that already
  has the index is a no-op.
- Builds without CONCURRENTLY because alembic wraps each migration in
  a transaction and CONCURRENTLY can't run inside one.  The cache table
  is small (admin-bounded — usually <10k rows) so a brief AccessExclusive
  lock at index creation is fine.
- The 0003 baseline has only just shipped, so the cache is empty when
  this runs — no chance of "could not create unique index, duplicate
  key value violates" failures.
"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "0004_ai_cache_unique_index"
down_revision = "0003_ai_response_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
            ai_response_cache_query_version_uidx
        ON ai_response_cache (query_text, content_version);
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ai_response_cache_query_version_uidx;"
    )
