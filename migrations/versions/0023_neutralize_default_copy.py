"""neutralize default copy — one-time data update for industry-neutral wording.

Revision ID: 0023_neutralize_default_copy
Revises: 0022_site_chat_only_mode
Create Date: 2026-06-01

Task #9 (industry-agnostic public copy). The code seeds/defaults are now
neutral (no "Gallery"/"Concierge"/"Marco"/"Seasonal" framing), but the RUNNING
database still holds rows seeded under the old hospitality-flavored defaults.
This data migration rewrites ONLY rows that still match an old default, so a
client's intentional customizations are never clobbered, and it's a no-op on a
fresh fork (init_db already seeds the neutral values). No schema changes.

The visitor_system prompt is neutralized with the SAME targeted phrase swaps the
code default uses, so the live row and a fresh install read identically.
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401


revision = "0023_neutralize_default_copy"
down_revision = "0022_site_chat_only_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Page-section nav labels (only if still the old defaults).
    op.execute("UPDATE page_sections SET title='Highlights' "
               "WHERE title='Gallery Highlights'")
    op.execute("UPDATE page_sections SET title='Offerings & Pricing' "
               "WHERE title='Experiences & Pricing'")

    # 2) Chat assistant persona defaults (Marco / Concierge / 'M' avatar) +
    #    the gallery-flavored quick prompt. Each guarded to the old value.
    op.execute("UPDATE chatbot_settings SET agent_name='AI Assistant' "
               "WHERE agent_name='Marco'")
    op.execute("UPDATE chatbot_settings SET agent_role='Assistant' "
               "WHERE agent_role='Concierge'")
    op.execute("UPDATE chatbot_settings SET agent_avatar='A' "
               "WHERE agent_avatar='M'")
    op.execute("UPDATE chatbot_settings "
               "SET quick_prompts = REPLACE(quick_prompts::text, "
               "'Browse our gallery', 'Browse our offerings')::jsonb "
               "WHERE quick_prompts::text LIKE '%Browse our gallery%'")

    # 3) Visitor system prompt — neutralize the persona phrasing with the exact
    #    same swaps applied to the code default (so live == fresh). Scoped to the
    #    one prompt key; only rewrites the phrases if they're still present.
    op.execute(
        """
        UPDATE ai_prompts SET content =
          REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
            content,
            'knowledgeable concierge for this website',
            'knowledgeable assistant for this website'),
            'You are a concierge for THIS specific business',
            'You are an assistant for THIS specific business'),
            'as a great human concierge or front-desk expert. A great concierge',
            'as a great human assistant or knowledgeable expert. A great assistant'),
            'If a real concierge would',
            'If a real assistant would'),
            'A great concierge would also share',
            'A great assistant would also share'),
            'anything a concierge would',
            'anything a helpful assistant would'),
            'This is core concierge territory',
            'This is core territory'),
            'Standard concierge questions',
            'Standard questions')
        WHERE prompt_key = 'visitor_system'
        """
    )

    # 4) Seeded sample blog post — drop the hospitality lead example.
    op.execute(
        "UPDATE blog_posts SET content = REPLACE(content, "
        "'welcoming a guest into a boutique hotel, greeting a client at your office', "
        "'greeting a customer in person, meeting a client at your office') "
        "WHERE slug = 'the-art-of-first-impressions'"
    )


def downgrade() -> None:
    # Copy-wording data migration — not meaningfully reversible. No-op.
    pass
