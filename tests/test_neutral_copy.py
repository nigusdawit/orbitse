"""Task #9 — industry-neutral public copy. Embedded Postgres.

Asserts the DB seeds, the code default system prompt, the served public HTML,
and the static frontend files all read industry-neutral (no Gallery / Concierge
/ Marco / Seasonal / "Plan Your Visit" framing). The migration's live-DB
data-update is exercised separately in the gate (old values injected before the
Alembic run, then asserted neutral).
"""
import pathlib

import app

ROOT = pathlib.Path(__file__).resolve().parent.parent
OLD_TERMS_HTML = ["Explore Gallery", "Plan Your Visit", "Seasonal Rates",
                  "Curated For You", "View All Gallery Items", "AI Concierge"]


# ---- DB seeds (fresh install reads neutral) --------------------------------

def test_sections_seed_neutral():
    titles = {r["title"] for r in (app.query_db(
        "SELECT title FROM page_sections") or [])}
    assert "Highlights" in titles and "Offerings & Pricing" in titles
    assert "Gallery Highlights" not in titles
    assert "Experiences & Pricing" not in titles


def test_chatbot_persona_neutral():
    row = app.query_db("SELECT agent_name, agent_role, agent_avatar, "
                       "quick_prompts::text AS qp FROM chatbot_settings WHERE id=1",
                       fetchone=True)
    assert row["agent_name"] != "Marco"
    assert row["agent_role"] != "Concierge"
    assert "Browse our gallery" not in (row["qp"] or "")


def test_visitor_system_prompt_neutral():
    txt = app.get_prompt("visitor_system", app.SYSTEM_PROMPT).lower()
    assert "concierge" not in txt
    assert "front-desk" not in txt


def test_blog_seed_neutral():
    row = app.query_db("SELECT content FROM blog_posts "
                       "WHERE slug='the-art-of-first-impressions'", fetchone=True)
    if row:  # seeded only on a fresh init; tolerate absence
        assert "boutique hotel" not in (row["content"] or "")


# ---- code default ----------------------------------------------------------

def test_code_system_prompt_neutral():
    blk = app.SYSTEM_PROMPT.lower()
    assert "concierge" not in blk and "front-desk" not in blk


# ---- static frontend files -------------------------------------------------

def test_index_html_neutral():
    html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    for term in OLD_TERMS_HTML:
        assert term not in html, f"old term still in index.html: {term!r}"
    assert "Browse Highlights" in html
    assert 'alt="AI Assistant"' in html


def test_script_js_neutral():
    js = (ROOT / "public" / "script.js").read_text(encoding="utf-8")
    # User-facing fallbacks neutralized (comments may still say 'concierge').
    assert "|| 'Marco'" not in js
    assert "|| 'Concierge'" not in js
    assert 'alt="AI Concierge"' not in js


# ---- served public HTML ----------------------------------------------------

def test_public_homepage_renders_neutral():
    c = app.app.test_client()
    body = c.get("/").get_data(as_text=True)
    # The page should render (200-class) with neutral hero copy.
    assert "Browse Highlights" in body
    for term in ["Explore Gallery", "Plan Your Visit", "Seasonal Rates",
                 "Curated For You"]:
        assert term not in body, f"old term served in homepage: {term!r}"
