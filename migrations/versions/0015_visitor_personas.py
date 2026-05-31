"""visitor_personas — super-admin-defined specialist agents for the concierge.

Revision ID: 0015_visitor_personas
Revises: 0014_leads_callbacks
Create Date: 2026-05-31

Phase 6 / Epic E (task 046). A multi-agent intent router for the visitor
concierge: each persona augments the system prompt, constrains the tool set
(tool_names jsonb; [] = all), and may pin a model. A cheap classifier routes
each turn to a persona ONLY when the 'visitor_persona_router_enabled' knob is
on; off = single-agent behavior (unchanged). Mirrors the CREATE TABLE in
init_db().
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0015_visitor_personas"
down_revision = "0014_leads_callbacks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS visitor_personas (
            id            BIGSERIAL PRIMARY KEY,
            tenant_id     INTEGER NOT NULL DEFAULT 1,
            persona_key   VARCHAR(40) NOT NULL,
            label         TEXT NOT NULL DEFAULT '',
            prompt_suffix TEXT NOT NULL DEFAULT '',
            tool_names    JSONB NOT NULL DEFAULT '[]'::jsonb,
            model         TEXT NOT NULL DEFAULT '',
            enabled       BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order    INTEGER NOT NULL DEFAULT 0,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, persona_key)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS visitor_personas_enabled_idx "
        "ON visitor_personas (tenant_id, enabled, sort_order);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS visitor_personas")
