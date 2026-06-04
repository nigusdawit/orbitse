"""admin_ai_config — super-admin-editable admin-chat personas + slash/capability/starter palette.

Revision ID: 0032_admin_ai_config
Revises: 0031_datahub_table_grants
Create Date: 2026-06-04

Task 088 — make the admin AI's PERSONAS and its slash-command / capabilities-tray
/ empty-state-starter PALETTE dynamic and super-admin-editable from a new
"Admin AI" tab, instead of being hardcoded (the personas in app.py's
ADMIN_CHAT_PERSONAS dict, the palette in public/admin/csrf.js consts).

Four tables, all sharing the same editable-config shape (mirrors the
`ai_prompts` machinery and the `datahub_table_grants` (0031) migration style):

  * tenant_id  — FK to tenants(id) ON DELETE CASCADE (silo default 1).
  * enabled    — soft on/off (hide without deleting).
  * is_builtin — TRUE for the rows seeded from code defaults. Built-ins are
                 reset/disable-only (never hard-deleted); only custom rows
                 created in the UI are deletable. Keeps the shipped surface
                 always restorable.
  * sort_order — display order in both the editor and the chat.
  * updated_by — NULL = machine-seeded (never human-edited). This is the
                 PRESERVE-EDITS hinge: the boot-time sync_* upserts only refresh
                 rows whose updated_by IS NULL, so a super-admin's saved edit
                 survives restarts and future code-default changes (identical to
                 sync_ai_prompts()).

NOT added to the frozen in-code init_db() DDL — Alembic owns all post-0030
schema. Idempotent CREATE IF NOT EXISTS + a precise downgrade() that drops all
four, so the migration round-trips.
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0032_admin_ai_config"
down_revision = "0031_datahub_table_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) PERSONAS — the backend-critical table. tool_prefixes is JSONB and
    #    NULLABLE on purpose: SQL NULL means "every tool" (tri-state), distinct
    #    from a JSON '[]' which means "only the always-keep set". extra_tools is
    #    a JSON array of exact tool names always kept for that persona.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_chat_personas (
            id            SERIAL PRIMARY KEY,
            tenant_id     INTEGER NOT NULL DEFAULT 1
                          REFERENCES tenants(id) ON DELETE CASCADE,
            persona_key   VARCHAR(40) NOT NULL,
            label         TEXT    NOT NULL DEFAULT '',
            icon          TEXT    NOT NULL DEFAULT '',
            description   TEXT    NOT NULL DEFAULT '',
            prompt_suffix TEXT    NOT NULL DEFAULT '',
            tool_prefixes JSONB,                       -- NULL = all tools
            extra_tools   JSONB   NOT NULL DEFAULT '[]'::jsonb,
            enabled       BOOLEAN NOT NULL DEFAULT TRUE,
            is_builtin    BOOLEAN NOT NULL DEFAULT FALSE,
            sort_order    INTEGER NOT NULL DEFAULT 0,
            updated_at    TIMESTAMP DEFAULT NOW(),
            updated_by    TEXT,                          -- NULL = machine-seeded
            created_at    TIMESTAMP DEFAULT NOW(),
            UNIQUE (tenant_id, persona_key)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS admin_chat_personas_tenant_enabled_idx "
        "ON admin_chat_personas (tenant_id, enabled, sort_order)"
    )

    # 2) SLASH-COMMANDS — one row per "/cmd" in the palette. All cosmetic: the
    #    backend never reads these; they only seed the composer (+ optional
    #    persona) client-side. `super` hides the row from non-super admins.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_chat_commands (
            id            SERIAL PRIMARY KEY,
            tenant_id     INTEGER NOT NULL DEFAULT 1
                          REFERENCES tenants(id) ON DELETE CASCADE,
            cmd           VARCHAR(40) NOT NULL,          -- e.g. "/sql"
            icon          TEXT    NOT NULL DEFAULT '',
            group_label   TEXT    NOT NULL DEFAULT '',
            tool          TEXT    NOT NULL DEFAULT '',   -- display-only hint
            description   TEXT    NOT NULL DEFAULT '',
            seed          TEXT    NOT NULL DEFAULT '',    -- prompt seeded on pick
            arg           TEXT    NOT NULL DEFAULT '',
            tail          BOOLEAN NOT NULL DEFAULT FALSE, -- leave caret to type arg
            persona       VARCHAR(40) NOT NULL DEFAULT '',
            super         BOOLEAN NOT NULL DEFAULT FALSE,
            enabled       BOOLEAN NOT NULL DEFAULT TRUE,
            is_builtin    BOOLEAN NOT NULL DEFAULT FALSE,
            sort_order    INTEGER NOT NULL DEFAULT 0,
            updated_at    TIMESTAMP DEFAULT NOW(),
            updated_by    TEXT,
            created_at    TIMESTAMP DEFAULT NOW(),
            UNIQUE (tenant_id, cmd)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS admin_chat_commands_tenant_enabled_idx "
        "ON admin_chat_commands (tenant_id, enabled, sort_order)"
    )

    # 3) CAPABILITY GROUPS — one row per tray card. lines = JSON array of bullet
    #    strings; examples = JSON array of {label, seed, persona?, action?}.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_chat_capabilities (
            id            SERIAL PRIMARY KEY,
            tenant_id     INTEGER NOT NULL DEFAULT 1
                          REFERENCES tenants(id) ON DELETE CASCADE,
            cap_key       VARCHAR(60) NOT NULL,
            icon          TEXT    NOT NULL DEFAULT '',
            title         TEXT    NOT NULL DEFAULT '',
            super         BOOLEAN NOT NULL DEFAULT FALSE,
            grant_aware   BOOLEAN NOT NULL DEFAULT FALSE, -- shows data-access badge
            lines         JSONB   NOT NULL DEFAULT '[]'::jsonb,
            examples      JSONB   NOT NULL DEFAULT '[]'::jsonb,
            enabled       BOOLEAN NOT NULL DEFAULT TRUE,
            is_builtin    BOOLEAN NOT NULL DEFAULT FALSE,
            sort_order    INTEGER NOT NULL DEFAULT 0,
            updated_at    TIMESTAMP DEFAULT NOW(),
            updated_by    TEXT,
            created_at    TIMESTAMP DEFAULT NOW(),
            UNIQUE (tenant_id, cap_key)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS admin_chat_capabilities_tenant_enabled_idx "
        "ON admin_chat_capabilities (tenant_id, enabled, sort_order)"
    )

    # 4) STARTERS — empty-state chips. Simplest shape: icon/label/seed/persona.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_chat_starters (
            id            SERIAL PRIMARY KEY,
            tenant_id     INTEGER NOT NULL DEFAULT 1
                          REFERENCES tenants(id) ON DELETE CASCADE,
            starter_key   VARCHAR(60) NOT NULL,
            icon          TEXT    NOT NULL DEFAULT '',
            label         TEXT    NOT NULL DEFAULT '',
            seed          TEXT    NOT NULL DEFAULT '',
            persona       VARCHAR(40) NOT NULL DEFAULT '',
            super         BOOLEAN NOT NULL DEFAULT FALSE,
            enabled       BOOLEAN NOT NULL DEFAULT TRUE,
            is_builtin    BOOLEAN NOT NULL DEFAULT FALSE,
            sort_order    INTEGER NOT NULL DEFAULT 0,
            updated_at    TIMESTAMP DEFAULT NOW(),
            updated_by    TEXT,
            created_at    TIMESTAMP DEFAULT NOW(),
            UNIQUE (tenant_id, starter_key)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS admin_chat_starters_tenant_enabled_idx "
        "ON admin_chat_starters (tenant_id, enabled, sort_order)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS admin_chat_starters")
    op.execute("DROP TABLE IF EXISTS admin_chat_capabilities")
    op.execute("DROP TABLE IF EXISTS admin_chat_commands")
    op.execute("DROP TABLE IF EXISTS admin_chat_personas")
