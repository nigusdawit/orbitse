"""Pins the AI editable-prompts subsystem (registry / defaults / cache /
get_prompt) BEFORE it is relocated from app.py into core.py (Track B, task 078,
piece #1).

This is the safety net for a NON-VERBATIM move: the prompt constants
(SYSTEM_PROMPT, ADMIN_CHAT_SYSTEM_PROMPT, ...), the in-memory prompt cache
(_PROMPT_CACHE + _load_prompt_cache + _invalidate_prompt_cache + get_prompt) and
the registry (_ai_prompt_registry / _ai_prompt_defaults) move to core and are
re-exported by app. Every assertion below goes through the `app.` namespace —
exactly how every live call site resolves these names — so it proves the
re-export keeps them resolving unchanged after the move.

Runs under the embedded-Postgres harness (_runner.py / conftest boots the app
once against a throwaway pgserver). No live LLM calls.
"""
import app


# The canonical, ordered set of editable-prompt keys. Stable contract: the
# admin UI, sync_ai_prompts() seeding, and every get_prompt(key, DEFAULT) call
# site depend on these keys not silently changing.
EXPECTED_KEYS = [
    "visitor_system",
    "admin_assistant",
    "presentation_narration",
    "seo_suggest",
    "persona_router",
    "scraper_url_intro",
    "scraper_objective_intro",
    "scraper_research",
]


def test_registry_keys_stable_and_ordered():
    keys = [m["key"] for m in app._ai_prompt_registry()]
    assert keys == EXPECTED_KEYS


def test_registry_entries_have_ui_metadata():
    """Each registry row must carry the metadata the editor renders."""
    for m in app._ai_prompt_registry():
        assert m["label"] and isinstance(m["label"], str)
        assert m["category"] and isinstance(m["category"], str)
        assert isinstance(m["description"], str)
        assert callable(m["default"])


def test_defaults_resolve_non_empty_for_every_key():
    """_ai_prompt_defaults() resolves a non-blank default for every key,
    including the three that come from the scraper module (proves the
    scraper.SCRAPER_* references still resolve after the move)."""
    defaults = app._ai_prompt_defaults()
    assert set(defaults.keys()) == set(EXPECTED_KEYS)
    for k in EXPECTED_KEYS:
        assert defaults[k].strip(), f"default for {k} resolved empty"


def test_module_constants_match_registry_defaults():
    """The big module-level prompt constants are what the registry hands back
    for their keys (pins the constants themselves through the registry)."""
    defaults = app._ai_prompt_defaults()
    assert defaults["visitor_system"] == app.SYSTEM_PROMPT
    assert defaults["admin_assistant"] == app.ADMIN_CHAT_SYSTEM_PROMPT
    assert defaults["presentation_narration"] == app.SLIDE_NARRATION_PROMPT
    assert defaults["seo_suggest"] == app.SEO_SUGGEST_PROMPT
    assert defaults["persona_router"] == app.PERSONA_ROUTER_PROMPT


def test_get_prompt_falls_back_to_passed_default():
    """The live call-site pattern get_prompt(key, CONSTANT): with no stored
    override, get_prompt returns the constant passed in."""
    assert app.get_prompt("visitor_system", app.SYSTEM_PROMPT) == app.SYSTEM_PROMPT
    assert app.get_prompt("seo_suggest", app.SEO_SUGGEST_PROMPT) == app.SEO_SUGGEST_PROMPT


def test_get_prompt_unknown_key_uses_arg_then_registry_default():
    # An unknown key with an explicit default returns that default verbatim.
    assert app.get_prompt("__no_such_prompt__", "FALLBACK_TEXT") == "FALLBACK_TEXT"
    # An unknown key with no default returns "" (registry has no entry for it).
    assert app.get_prompt("__no_such_prompt__") == ""


def test_get_prompt_reflects_db_override_and_invalidation():
    """A saved override wins over the hardcoded default; resetting the row +
    invalidating the cache restores the default. Pins the save->cache->read
    cycle the /admin/api/ai-prompts PUT + reset endpoints rely on."""
    key = "seo_suggest"
    original = app.get_prompt(key, app.SEO_SUGGEST_PROMPT)
    sentinel = "PINNED OVERRIDE TEXT for seo_suggest"
    try:
        app.execute_db(
            "INSERT INTO ai_prompts (prompt_key, content) VALUES (%s, %s) "
            "ON CONFLICT (prompt_key) DO UPDATE SET content = EXCLUDED.content",
            (key, sentinel),
        )
        app._invalidate_prompt_cache()
        # Override is returned even when a default is passed in.
        assert app.get_prompt(key, app.SEO_SUGGEST_PROMPT) == sentinel
    finally:
        # Restore the default text so the shared DB row is left as the seed.
        app.execute_db(
            "INSERT INTO ai_prompts (prompt_key, content) VALUES (%s, %s) "
            "ON CONFLICT (prompt_key) DO UPDATE SET content = EXCLUDED.content",
            (key, app.SEO_SUGGEST_PROMPT),
        )
        app._invalidate_prompt_cache()
    assert app.get_prompt(key, app.SEO_SUGGEST_PROMPT) == original


def test_blank_override_falls_through_to_default():
    """A stored row whose content is blank/whitespace must NOT shadow the
    default — get_prompt treats blank as 'no override'."""
    key = "persona_router"
    try:
        app.execute_db(
            "INSERT INTO ai_prompts (prompt_key, content) VALUES (%s, %s) "
            "ON CONFLICT (prompt_key) DO UPDATE SET content = EXCLUDED.content",
            (key, "   "),
        )
        app._invalidate_prompt_cache()
        assert app.get_prompt(key, app.PERSONA_ROUTER_PROMPT) == app.PERSONA_ROUTER_PROMPT
    finally:
        app.execute_db(
            "INSERT INTO ai_prompts (prompt_key, content) VALUES (%s, %s) "
            "ON CONFLICT (prompt_key) DO UPDATE SET content = EXCLUDED.content",
            (key, app.PERSONA_ROUTER_PROMPT),
        )
        app._invalidate_prompt_cache()
