"""Pins the dynamic admin-chat PERSONAS subsystem (task 088).

Personas were a hardcoded dict (app.ADMIN_CHAT_PERSONAS). They now live in
core._admin_persona_registry() as built-in DEFAULTS, are seeded into the
super-admin-editable admin_chat_personas table by sync_admin_personas() (with
the same preserve-edits semantics as sync_ai_prompts), and are read on the hot
path through the FAIL-OPEN cached accessor get_admin_personas().

Phase 0 (this file, foundations) pins: the registry contract, the seed/refresh/
preserve-edits semantics, the JSONB tri-state (tool_prefixes None = all tools),
fail-open to code defaults, the 'general' guarantee, and that migration 0032
created the four tables. The read-site-rewrite behaviour (_admin_apply_persona,
classifier, spawn validation) and the CRUD routes are pinned in phase 1/2.

Runs under the embedded-Postgres harness (_runner.py): init_db + alembic head
(so admin_chat_personas EXISTS) but NOT the boot seed — so the table starts
empty and seed tests call app.sync_admin_personas() explicitly, mirroring
tests/test_ai_prompts.py's sync tests.
"""
import os

import app
import core

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")

# The canonical, ordered built-in persona keys. Stable contract: the persona
# pill, the router {options}, spawn_agents validation, and _admin_apply_persona
# all depend on these not silently changing.
EXPECTED_PERSONA_KEYS = [
    "general", "research", "data_analyst", "code", "creative", "ops",
]


# --------------------------------------------------------------------------- #
# Registry contract                                                           #
# --------------------------------------------------------------------------- #
def test_registry_keys_stable_and_ordered():
    keys = [p["persona_key"] for p in app._admin_persona_registry()]
    assert keys == EXPECTED_PERSONA_KEYS


def test_registry_entries_have_required_fields():
    """Every built-in carries the fields the seed + UI + tool-filter need."""
    for p in app._admin_persona_registry():
        assert p["persona_key"] and isinstance(p["persona_key"], str)
        assert isinstance(p["label"], str) and p["label"]
        assert isinstance(p["icon"], str)
        assert isinstance(p["description"], str)
        assert isinstance(p["prompt_suffix"], str)
        # tool_prefixes is tri-state: None (= all tools) or a list of prefixes.
        assert p["tool_prefixes"] is None or isinstance(p["tool_prefixes"], list)
        assert isinstance(p["extra_tools"], list)
        assert isinstance(p["sort_order"], int)


def test_general_is_unfiltered_and_first():
    """'general' must be the all-tools persona (tool_prefixes None) — it is the
    universal fallback used by _admin_apply_persona()."""
    reg = {p["persona_key"]: p for p in app._admin_persona_registry()}
    assert reg["general"]["tool_prefixes"] is None
    assert reg["general"]["prompt_suffix"] == ""


def test_derived_module_dict_matches_registry():
    """The legacy ADMIN_CHAT_PERSONAS module dict is now DERIVED from the
    registry — same keys, and each entry exposes the fields the old dict did
    (label/prompt_suffix/tool_prefixes/extra_tools) so existing reads are
    behaviour-preserving."""
    assert set(app.ADMIN_CHAT_PERSONAS.keys()) == set(EXPECTED_PERSONA_KEYS)
    for key, p in app.ADMIN_CHAT_PERSONAS.items():
        assert set(("label", "prompt_suffix", "tool_prefixes", "extra_tools")).issubset(p.keys())


# --------------------------------------------------------------------------- #
# Seed / refresh / preserve-edits (mirror test_ai_prompts sync tests)         #
# --------------------------------------------------------------------------- #
def _persona_row(key):
    return app.query_db(
        "SELECT persona_key, label, prompt_suffix, tool_prefixes, extra_tools, "
        "enabled, is_builtin, sort_order, updated_by "
        "FROM admin_chat_personas WHERE tenant_id = 1 AND persona_key = %s",
        (key,), fetchone=True,
    )


def test_sync_seeds_all_builtins_machine_owned():
    """sync_admin_personas() seeds all 6 built-ins with updated_by NULL (machine
    owned) and is_builtin TRUE. Idempotent: a second call is a no-op."""
    app.sync_admin_personas()
    for key in EXPECTED_PERSONA_KEYS:
        row = _persona_row(key)
        assert row is not None, f"{key} not seeded"
        assert row["is_builtin"] is True
        assert row["updated_by"] is None
    # Idempotent — running again does not raise / duplicate.
    app.sync_admin_personas()
    for key in EXPECTED_PERSONA_KEYS:
        assert _persona_row(key) is not None


def test_sync_roundtrips_jsonb_tristate():
    """tool_prefixes survives the JSONB round-trip as the right tri-state:
    'general' stores SQL NULL (= all tools), a filtered persona stores its list;
    extra_tools is a JSON array. Proven via the live accessor (DB → cache → dict)."""
    app.sync_admin_personas()
    core._invalidate_admin_persona_cache()
    personas = app.get_admin_personas()
    # general: NULL JSONB → None (every tool)
    assert personas["general"]["tool_prefixes"] is None
    # research: list survives intact
    reg = {p["persona_key"]: p for p in app._admin_persona_registry()}
    assert personas["research"]["tool_prefixes"] == reg["research"]["tool_prefixes"]
    assert personas["research"]["extra_tools"] == ["spawn_agents"]


def test_sync_refreshes_machine_seeded_stale_row():
    """A machine-seeded row (updated_by NULL) with stale content is REFRESHED to
    the current code default on the next sync — so editing a registry default
    propagates on reboot (same contract as sync_ai_prompts)."""
    key = "ops"
    default_suffix = {p["persona_key"]: p for p in app._admin_persona_registry()}[key]["prompt_suffix"]
    app.sync_admin_personas()  # ensure row exists
    try:
        app.execute_db(
            "UPDATE admin_chat_personas SET prompt_suffix = %s, updated_by = NULL "
            "WHERE tenant_id = 1 AND persona_key = %s",
            ("STALE OPS SUFFIX", key),
        )
        assert _persona_row(key)["prompt_suffix"] == "STALE OPS SUFFIX"

        app.sync_admin_personas()

        row = _persona_row(key)
        assert row["prompt_suffix"] == default_suffix, "stale machine row not refreshed"
        assert row["updated_by"] is None
    finally:
        app.execute_db(
            "UPDATE admin_chat_personas SET prompt_suffix = %s, updated_by = NULL "
            "WHERE tenant_id = 1 AND persona_key = %s",
            (default_suffix, key),
        )
        core._invalidate_admin_persona_cache()


def test_sync_preserves_human_edited_row():
    """A human-edited row (updated_by set non-null by the CRUD save) is PRESERVED
    untouched by sync_admin_personas() — its label survives a reseed + reboot."""
    key = "creative"
    default_label = {p["persona_key"]: p for p in app._admin_persona_registry()}[key]["label"]
    app.sync_admin_personas()
    try:
        app.execute_db(
            "UPDATE admin_chat_personas SET label = %s, updated_by = %s "
            "WHERE tenant_id = 1 AND persona_key = %s",
            ("HUMAN LABEL", "super_admin", key),
        )

        app.sync_admin_personas()

        row = _persona_row(key)
        assert row["label"] == "HUMAN LABEL", "human edit clobbered by sync"
        assert row["updated_by"] == "super_admin"
    finally:
        # Restore the clean machine-owned default for downstream tests.
        app.execute_db(
            "UPDATE admin_chat_personas SET label = %s, updated_by = NULL "
            "WHERE tenant_id = 1 AND persona_key = %s",
            (default_label, key),
        )
        core._invalidate_admin_persona_cache()


# --------------------------------------------------------------------------- #
# Fail-open accessor + 'general' guarantee                                    #
# --------------------------------------------------------------------------- #
def test_get_admin_personas_fail_open_on_db_error(monkeypatch):
    """If the persona query errors (table missing / DB down), get_admin_personas()
    degrades to the built-in registry defaults rather than breaking the chat."""
    def _boom(*_a, **_k):
        raise RuntimeError("simulated DB failure")
    monkeypatch.setattr(core, "query_db", _boom)
    try:
        core._invalidate_admin_persona_cache()
        personas = app.get_admin_personas()
        assert set(personas.keys()) == set(EXPECTED_PERSONA_KEYS)
        assert "general" in personas
        assert personas["general"]["tool_prefixes"] is None
    finally:
        monkeypatch.undo()
        core._invalidate_admin_persona_cache()


def test_get_admin_personas_always_includes_general():
    """Even if the live cache somehow lost 'general', the accessor re-adds it from
    the registry — _admin_apply_persona() depends on it always being present."""
    core._load_admin_persona_cache()
    try:
        core._ADMIN_PERSONA_CACHE.clear()
        core._ADMIN_PERSONA_CACHE.update(
            {"research": app._admin_persona_defaults()["research"]})
        core._ADMIN_PERSONA_CACHE_LOADED = True  # block a reload
        out = app.get_admin_personas()
        assert "general" in out
    finally:
        core._invalidate_admin_persona_cache()


# --------------------------------------------------------------------------- #
# Migration 0032 created the four editable-config tables                      #
# --------------------------------------------------------------------------- #
def _table_exists(name):
    row = app.query_db(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = %s",
        (name,), fetchone=True,
    )
    return row is not None


def test_migration_created_all_four_tables():
    for t in ("admin_chat_personas", "admin_chat_commands",
              "admin_chat_capabilities", "admin_chat_starters"):
        assert _table_exists(t), f"{t} missing — migration 0032 did not run"


def test_personas_tool_prefixes_is_nullable():
    """The tri-state hinges on tool_prefixes being NULLABLE (NULL = all tools)."""
    row = app.query_db(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name = 'admin_chat_personas' AND column_name = 'tool_prefixes'",
        fetchone=True,
    )
    assert row is not None
    assert row["is_nullable"] == "YES"


def test_migration_revision_linkage():
    """0032 chains onto 0031 (the prior head)."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(app.__file__)),
                        "migrations", "versions", "0032_admin_ai_config.py")
    spec = importlib.util.spec_from_file_location("_m0032", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.revision == "0032_admin_ai_config"
    assert m.down_revision == "0031_datahub_table_grants"
