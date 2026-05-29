"""Unit tests for M13 lookup parity bits that don't need a DB.

The data-returning lookups are exercised against real rows in the gate; here we
pin (1) the web-search fail-closed behavior when no provider key is set, and
(2) that the full expected tool surface is registered and consistent across the
schema list, the executor map, and the skill metadata.
"""

from admin_ai_platform import tools
from admin_ai_platform import config


_EXPECTED = {
    "lookup_gallery_cards", "lookup_forms", "lookup_generated_page", "lookup_presentation",
    "lookup_knowledge_base", "lookup_events", "lookup_services",
    "lookup_service_availability", "lookup_products", "lookup_experiences", "lookup_pricing",
    "lookup_blog", "lookup_team", "lookup_faq", "lookup_testimonials", "lookup_business_info",
    "lookup_custom_section_items", "lookup_web_search",
}


def test_all_expected_lookups_registered():
    assert _EXPECTED <= set(tools.CHAT_LOOKUP_FUNCTIONS)
    # Every executor has a CHAT_TOOLS schema and skill metadata entry.
    schema_names = {t["function"]["name"] for t in tools.CHAT_TOOLS}
    for name in tools.CHAT_LOOKUP_FUNCTIONS:
        assert name in schema_names, f"{name} missing CHAT_TOOLS schema"
        assert name in tools.SKILL_METADATA, f"{name} missing SKILL_METADATA"


def test_web_search_requires_query():
    assert tools.lookup_web_search(query="").get("error") == "query required"


def test_web_search_degrades_without_keys(monkeypatch):
    monkeypatch.setattr(config, "BRAVE_SEARCH_API_KEY", "")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    out = tools.lookup_web_search(query="weather today")
    assert out.get("error") == "web search not configured"
