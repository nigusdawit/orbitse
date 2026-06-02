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

The HTTP-route tests at the bottom additionally pin the /admin/api/ai-prompts*
endpoints (super-admin gating + the GET / PUT / reset cycle) before those routes
are relocated from app.py into the ai_prompts blueprint (piece #1, part B). The
route-snapshot test guards the URL surface; these guard the behavior.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


# The canonical, ordered set of editable-prompt keys. Stable contract: the
# admin UI, sync_ai_prompts() seeding, and every get_prompt(key, DEFAULT) call
# site depend on these keys not silently changing.
EXPECTED_KEYS = [
    "visitor_system",
    "admin_assistant",
    "presentation_narration",
    "seo_suggest",
    "persona_router",
    # Visitor specialist router (task 079 Phase 2) — registered right after the
    # admin persona_router, in this exact order.
    "visitor_specialist_booking",
    "visitor_specialist_pricing",
    "visitor_specialist_general",
    "visitor_specialist_leadcap",
    "visitor_specialist_router_prompt",
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


# =============================================================================
# sync_ai_prompts() seed/refresh semantics (task 082 — prompt seed fix)
# =============================================================================
# The fresh-DB harness MASKS the bug under test: on a brand-new pgserver the
# rows are seeded straight from the current defaults, so a stale-row scenario
# never arises naturally. These tests force that scenario by pre-inserting a
# row with deliberately stale / human-edited content, THEN calling
# sync_ai_prompts(), and asserting the refresh-vs-preserve behavior.

def test_sync_refreshes_auto_seeded_stale_row():
    """A machine-seeded row (updated_by IS NULL) with stale content is REFRESHED
    by sync_ai_prompts() to the current code default, so a later change to a
    default prompt constant propagates on the next boot. Also pins that
    get_prompt() then serves the refreshed default (the bug was: the stale DB
    row shadowed the constant forever)."""
    key = "scraper_research"
    default = app._ai_prompt_defaults()[key]
    assert default.strip(), "precondition: default for key must be non-empty"
    try:
        # Pre-seed a STALE row exactly as an old auto-seed would have left it:
        # content from a previous code version, updated_by NULL (never human-edited).
        app.execute_db(
            "INSERT INTO ai_prompts (prompt_key, content, updated_by) "
            "VALUES (%s, %s, NULL) "
            "ON CONFLICT (prompt_key) DO UPDATE SET content = EXCLUDED.content, "
            "updated_by = NULL",
            (key, "STALE-OLD-CONTENT"),
        )
        app._invalidate_prompt_cache()
        # Sanity: the stale row is in place before the sync.
        row = app.query_db(
            "SELECT content, updated_by FROM ai_prompts WHERE prompt_key = %s",
            (key,), fetchone=True,
        )
        assert row["content"] == "STALE-OLD-CONTENT"
        assert row["updated_by"] is None

        app.sync_ai_prompts()

        # The auto-seeded row was REFRESHED to the current code default.
        row = app.query_db(
            "SELECT content, updated_by FROM ai_prompts WHERE prompt_key = %s",
            (key,), fetchone=True,
        )
        assert row["content"] != "STALE-OLD-CONTENT", "stale row was not refreshed"
        assert row["content"] == default
        assert row["updated_by"] is None  # still machine-owned
        # And get_prompt now serves the refreshed default, not the stale text.
        assert app.get_prompt(key, default) == default
    finally:
        # Leave the shared row as the clean code-default seed (updated_by NULL).
        app.execute_db(
            "INSERT INTO ai_prompts (prompt_key, content, updated_by) "
            "VALUES (%s, %s, NULL) "
            "ON CONFLICT (prompt_key) DO UPDATE SET content = EXCLUDED.content, "
            "updated_by = NULL",
            (key, default),
        )
        app._invalidate_prompt_cache()


def test_sync_preserves_admin_edited_row():
    """A human-edited row (updated_by set non-null by the admin save/reset
    endpoints) is PRESERVED untouched by sync_ai_prompts() — the WHERE clause
    skips any row whose updated_by IS NOT NULL, so super-admin edits survive a
    code default change + reboot."""
    key = "presentation_narration"
    default = app._ai_prompt_defaults()[key]
    try:
        # Pre-seed a HUMAN-EDITED row: distinct content + non-null updated_by,
        # exactly how a super-admin save lands.
        app.execute_db(
            "INSERT INTO ai_prompts (prompt_key, content, updated_by) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (prompt_key) DO UPDATE SET content = EXCLUDED.content, "
            "updated_by = EXCLUDED.updated_by",
            (key, "HUMAN-EDITED", "super_admin"),
        )
        app._invalidate_prompt_cache()

        app.sync_ai_prompts()

        # The human edit is untouched — neither content nor updated_by changed.
        row = app.query_db(
            "SELECT content, updated_by FROM ai_prompts WHERE prompt_key = %s",
            (key,), fetchone=True,
        )
        assert row["content"] == "HUMAN-EDITED", "admin edit was clobbered by sync"
        assert row["updated_by"] == "super_admin"
        # get_prompt serves the human edit, not the code default.
        assert app.get_prompt(key, default) == "HUMAN-EDITED"
    finally:
        # Reset the shared row back to the clean code-default seed (updated_by NULL).
        app.execute_db(
            "INSERT INTO ai_prompts (prompt_key, content, updated_by) "
            "VALUES (%s, %s, NULL) "
            "ON CONFLICT (prompt_key) DO UPDATE SET content = EXCLUDED.content, "
            "updated_by = NULL",
            (key, default),
        )
        app._invalidate_prompt_cache()


# =============================================================================
# HTTP routes: /admin/api/ai-prompts* + /admin/api/default-system-prompt
# =============================================================================
# These pin the route behavior (super-admin gating + GET/PUT/reset cycle) so the
# blueprint relocation (piece #1, part B) is proven non-behavior-changing.

def _login(c, pw):
    return c.post("/admin/login", data={"password": pw})


def _csrf(c):
    with c.session_transaction() as s:
        s["_csrf_token"] = "tok"
    return {"X-CSRF-Token": "tok"}


def test_list_ai_prompts_super_admin_ok():
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    r = c.get("/admin/api/ai-prompts")
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    keys = [p["key"] for p in body["prompts"]]
    assert keys == EXPECTED_KEYS
    # Every item carries the editor fields.
    for p in body["prompts"]:
        assert set(("key", "label", "category", "description", "content",
                    "is_default", "updated_at", "updated_by")).issubset(p.keys())


def test_list_ai_prompts_client_forbidden():
    """A client session (not super-admin) is 403'd by _require_super_admin_role."""
    if not CLIENT_PW:
        return  # client role not enabled in this harness env
    c = app.app.test_client()
    assert _login(c, CLIENT_PW).status_code in (200, 302)
    r = c.get("/admin/api/ai-prompts")
    assert r.status_code == 403
    assert r.get_json().get("error") == "super_admin_role_required"


def test_list_ai_prompts_anon_blocked():
    """No session at all → @admin_required returns 401 for the JSON API path."""
    c = app.app.test_client()
    r = c.get("/admin/api/ai-prompts")
    assert r.status_code == 401


def test_update_then_reset_ai_prompt_roundtrip():
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    hdr = _csrf(c)
    key = "seo_suggest"
    try:
        # PUT a new value.
        r = c.put(f"/admin/api/ai-prompts/{key}",
                  json={"content": "ROUTE-TEST seo prompt"}, headers=hdr)
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()["is_default"] is False
        assert app.get_prompt(key, app.SEO_SUGGEST_PROMPT) == "ROUTE-TEST seo prompt"
        # Reset restores the hardcoded default.
        r2 = c.post(f"/admin/api/ai-prompts/{key}/reset", headers=hdr)
        assert r2.status_code == 200, r2.get_data(as_text=True)
        assert r2.get_json()["is_default"] is True
        assert r2.get_json()["content"] == app.SEO_SUGGEST_PROMPT
        assert app.get_prompt(key, app.SEO_SUGGEST_PROMPT) == app.SEO_SUGGEST_PROMPT
    finally:
        app.execute_db(
            "INSERT INTO ai_prompts (prompt_key, content) VALUES (%s, %s) "
            "ON CONFLICT (prompt_key) DO UPDATE SET content = EXCLUDED.content",
            (key, app.SEO_SUGGEST_PROMPT),
        )
        app._invalidate_prompt_cache()


def test_update_then_reset_visitor_specialist_prompt_roundtrip():
    """Task 079 P2: one of the new visitor-specialist keys is editable through
    the same PUT + reset cycle (pins the new registry rows end-to-end)."""
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    hdr = _csrf(c)
    key = "visitor_specialist_booking"
    default = app.VISITOR_SPECIALIST_BOOKING_PROMPT
    try:
        # PUT a new value.
        r = c.put(f"/admin/api/ai-prompts/{key}",
                  json={"content": "ROUTE-TEST booking specialist"}, headers=hdr)
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()["is_default"] is False
        assert app.get_prompt(key, default) == "ROUTE-TEST booking specialist"
        # Reset restores the hardcoded default.
        r2 = c.post(f"/admin/api/ai-prompts/{key}/reset", headers=hdr)
        assert r2.status_code == 200, r2.get_data(as_text=True)
        assert r2.get_json()["is_default"] is True
        assert r2.get_json()["content"] == default
        assert app.get_prompt(key, default) == default
    finally:
        app.execute_db(
            "INSERT INTO ai_prompts (prompt_key, content) VALUES (%s, %s) "
            "ON CONFLICT (prompt_key) DO UPDATE SET content = EXCLUDED.content",
            (key, default),
        )
        app._invalidate_prompt_cache()


def test_update_ai_prompt_validation():
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    hdr = _csrf(c)
    # Unknown key → 404.
    r = c.put("/admin/api/ai-prompts/__nope__",
              json={"content": "x"}, headers=hdr)
    assert r.status_code == 404
    assert r.get_json().get("error") == "unknown_prompt_key"
    # Blank content → 400 empty_content.
    r2 = c.put("/admin/api/ai-prompts/seo_suggest",
               json={"content": "   "}, headers=hdr)
    assert r2.status_code == 400
    assert r2.get_json().get("error") == "empty_content"
    # Missing content → 400 missing_content.
    r3 = c.put("/admin/api/ai-prompts/seo_suggest", json={}, headers=hdr)
    assert r3.status_code == 400
    assert r3.get_json().get("error") == "missing_content"


def test_default_system_prompt_route():
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    r = c.get("/admin/api/default-system-prompt")
    assert r.status_code == 200
    assert r.get_json().get("system_prompt") == app.SYSTEM_PROMPT
