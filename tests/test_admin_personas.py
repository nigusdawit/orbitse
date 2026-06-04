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
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")  # runner sets "client" → super-admin gating tests run

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


# --------------------------------------------------------------------------- #
# Phase 1 — read-site behaviour: _admin_apply_persona honors DB edits, custom  #
# keys validate, and persona edits cannot escalate privilege.                  #
# --------------------------------------------------------------------------- #
def _insert_custom_persona(key, tool_prefixes, extra_tools, enabled=True):
    """Insert/replace a CUSTOM (is_builtin FALSE) persona row directly, the way
    the phase-2 CRUD will, then invalidate the cache so the accessor reloads."""
    import json
    app.execute_db(
        "INSERT INTO admin_chat_personas "
        "(tenant_id, persona_key, label, prompt_suffix, tool_prefixes, extra_tools, "
        " enabled, is_builtin, sort_order, updated_by) "
        "VALUES (1, %s, %s, '', %s::jsonb, %s::jsonb, %s, FALSE, 99, 'test') "
        "ON CONFLICT (tenant_id, persona_key) DO UPDATE SET "
        "  tool_prefixes = EXCLUDED.tool_prefixes, extra_tools = EXCLUDED.extra_tools, "
        "  enabled = EXCLUDED.enabled, updated_by = 'test'",
        (key, key.replace("_", " ").title(),
         json.dumps(tool_prefixes) if tool_prefixes is not None else None,
         json.dumps(extra_tools or []), enabled),
    )
    core._invalidate_admin_persona_cache()


def _delete_persona(key):
    app.execute_db(
        "DELETE FROM admin_chat_personas WHERE tenant_id = 1 AND persona_key = %s",
        (key,))
    core._invalidate_admin_persona_cache()


def test_apply_persona_honors_db_edited_persona():
    """_admin_apply_persona reads the LIVE persona (DB → cache): a custom persona's
    tool_prefixes + extra_tools drive the filter; tool_prefixes None → every tool.
    Always-keep set (admin_list_tables/admin_describe_table/spawn_agents) survives."""
    key = "t5_sqlonly"
    fake_tools = [
        {"function": {"name": "admin_run_sql"}},
        {"function": {"name": "admin_list_tables"}},      # always-keep
        {"function": {"name": "admin_describe_table"}},   # always-keep
        {"function": {"name": "spawn_agents"}},           # always-keep
        {"function": {"name": "lookup_business_info"}},   # via extra_tools
        {"function": {"name": "admin_web_search"}},        # should be filtered OUT
        {"function": {"name": "admin_create_dashboard"}},  # should be filtered OUT
    ]
    all_names = {t["function"]["name"] for t in fake_tools}
    try:
        _insert_custom_persona(key, ["admin_run_sql"], ["lookup_business_info"])
        kept = {t["function"]["name"] for t in app._admin_apply_persona(fake_tools, key)}
        assert "admin_run_sql" in kept                      # prefix match
        assert {"admin_list_tables", "admin_describe_table", "spawn_agents"} <= kept
        assert "lookup_business_info" in kept               # extra_tools
        assert "admin_web_search" not in kept               # filtered
        assert "admin_create_dashboard" not in kept         # filtered

        # tool_prefixes None (every tool) — the tri-state's permissive end.
        _insert_custom_persona(key, None, [])
        kept_all = {t["function"]["name"] for t in app._admin_apply_persona(fake_tools, key)}
        assert kept_all == all_names
    finally:
        _delete_persona(key)


def test_custom_persona_membership_drives_validation():
    """The four persona validators (pin/request/spawn/classify) all gate on
    `key in get_admin_personas()`. So an ENABLED custom key is accepted; a DISABLED
    one (enabled-only accessor) and an unknown one are not (→ coerced to general)."""
    enabled_key, disabled_key = "t6_enabled", "t6_disabled"
    try:
        _insert_custom_persona(enabled_key, ["admin_run_sql"], [])
        _insert_custom_persona(disabled_key, ["admin_run_sql"], [], enabled=False)
        personas = app.get_admin_personas()
        assert enabled_key in personas
        assert disabled_key not in personas
        assert "__no_such_persona__" not in personas
    finally:
        _delete_persona(enabled_key)
        _delete_persona(disabled_key)


def test_persona_edit_cannot_escalate_privilege():
    """Security (T8): editing a persona's tool scope changes tool VISIBILITY, not
    AUTHORITY. A real super-admin-only tool still rejects a non-super caller at
    call time via _admin_tool_superadmin_guard() — even though a persona can
    surface it. The guard is exercised for real (not mocked)."""
    # The guard + a real privileged tool, in a NON-super request context.
    with app.app.test_request_context("/"):
        from flask import session
        session["admin_logged_in"] = True
        session["admin_role"] = "client"
        assert app._admin_tool_superadmin_guard() == {
            "error": "This action requires the super-admin role."}
        # _admin_tool_run_research early-returns the guard error before doing work.
        res = app._admin_tool_run_research(question="anything")
        assert isinstance(res, dict) and "super-admin" in (res.get("error") or "")
        # Super-admin clears the guard.
        session["admin_role"] = "super_admin"
        assert app._admin_tool_superadmin_guard() is None

    # A persona CAN surface a privileged-named tool (visibility) ...
    key = "t8_escalate"
    fake_tools = [{"function": {"name": "run_research"}},
                  {"function": {"name": "admin_run_sql"}}]
    try:
        _insert_custom_persona(key, ["run_research", "admin_run_sql"], [])
        kept = {t["function"]["name"] for t in app._admin_apply_persona(fake_tools, key)}
        assert "run_research" in kept  # ... but the call-time guard above blocks USE.
    finally:
        _delete_persona(key)


# --------------------------------------------------------------------------- #
# Phase 2 — CRUD routes (super-admin gating, delete/reset rules, validation)   #
# + the /admin/api/chat/personas consumption endpoint.                         #
# --------------------------------------------------------------------------- #
def _login(c, pw):
    return c.post("/admin/login", data={"password": pw})


def _csrf(c):
    with c.session_transaction() as s:
        s["_csrf_token"] = "tok"
    return {"X-CSRF-Token": "tok"}


def test_admin_ai_personas_super_admin_gating():
    """Every /admin/api/admin-ai/personas* route is super-admin only; a client
    admin is 403'd and an anonymous caller 401'd (T9)."""
    # super-admin can list
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    assert c.get("/admin/api/admin-ai/personas").status_code == 200
    # anonymous → 401
    an = app.app.test_client()
    assert an.get("/admin/api/admin-ai/personas").status_code == 401
    # client admin → 403 on read AND every mutation
    if CLIENT_PW:
        cc = app.app.test_client()
        assert _login(cc, CLIENT_PW).status_code in (200, 302)
        hdr = _csrf(cc)
        assert cc.get("/admin/api/admin-ai/personas").status_code == 403
        assert cc.post("/admin/api/admin-ai/personas",
                       json={"persona_key": "x"}, headers=hdr).status_code == 403
        assert cc.put("/admin/api/admin-ai/personas/general",
                      json={}, headers=hdr).status_code == 403
        assert cc.post("/admin/api/admin-ai/personas/research/reset",
                       headers=hdr).status_code == 403
        assert cc.delete("/admin/api/admin-ai/personas/x",
                         headers=hdr).status_code == 403


def test_admin_ai_persona_delete_and_reset_rules():
    """Built-ins are reset/disable-only (delete → 409); custom personas delete OK;
    reset restores a built-in to its default + re-machine-owns it (updated_by NULL);
    resetting a non-built-in → 400 (T10)."""
    app.sync_admin_personas()  # ensure built-ins exist
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    hdr = _csrf(c)
    reg = {p["persona_key"]: p for p in app._admin_persona_registry()}

    # delete a built-in → 409
    assert c.delete("/admin/api/admin-ai/personas/research", headers=hdr).status_code == 409

    # create + delete a custom → 201 then 200
    key = "t10_custom"
    try:
        assert c.post("/admin/api/admin-ai/personas",
                      json={"persona_key": key, "label": "T10"},
                      headers=hdr).status_code == 201
        assert c.delete(f"/admin/api/admin-ai/personas/{key}", headers=hdr).status_code == 200
        # reset a non-built-in key → 400
        assert c.post(f"/admin/api/admin-ai/personas/{key}/reset",
                      headers=hdr).status_code == 400
    finally:
        _delete_persona(key)

    # dirty a built-in (stamps updated_by), then reset → back to default + NULL
    try:
        c.put("/admin/api/admin-ai/personas/ops",
              json={"label": "Dirty Ops", "prompt_suffix": "x"}, headers=hdr)
        assert _persona_row("ops")["updated_by"] is not None
        assert c.post("/admin/api/admin-ai/personas/ops/reset", headers=hdr).status_code == 200
        row = _persona_row("ops")
        assert row["updated_by"] is None
        assert row["label"] == reg["ops"]["label"]
    finally:
        # leave 'ops' clean for downstream tests regardless
        app.sync_admin_personas()
        core._invalidate_admin_persona_cache()


def test_admin_ai_persona_validation_and_mass_assignment():
    """Bad slug → 400; reserved built-in key → 400; duplicate → 409; bogus
    is_builtin/tenant_id in the body are IGNORED (whitelist) (T11)."""
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    hdr = _csrf(c)
    assert c.post("/admin/api/admin-ai/personas",
                  json={"persona_key": "Bad Key!"}, headers=hdr).status_code == 400
    assert c.post("/admin/api/admin-ai/personas",
                  json={"persona_key": "general"}, headers=hdr).status_code == 400
    key = "t11_custom"
    try:
        r = c.post("/admin/api/admin-ai/personas",
                   json={"persona_key": key, "label": "T11", "is_builtin": True,
                         "tenant_id": 999, "tool_prefixes": ["admin_run_sql"],
                         "extra_tools": ["spawn_agents"]},
                   headers=hdr)
        assert r.status_code == 201, r.get_data(as_text=True)
        row = app.query_db(
            "SELECT tenant_id, is_builtin, updated_by FROM admin_chat_personas "
            "WHERE persona_key=%s", (key,), fetchone=True)
        assert row["is_builtin"] is False     # bogus is_builtin ignored
        assert row["tenant_id"] == 1          # bogus tenant_id ignored
        assert row["updated_by"] is not None  # custom rows are human-stamped
        # duplicate key → 409
        assert c.post("/admin/api/admin-ai/personas",
                      json={"persona_key": key}, headers=hdr).status_code == 409
    finally:
        _delete_persona(key)


def test_chat_personas_consumption_endpoint():
    """/admin/api/chat/personas returns the enabled personas (key/label/icon/desc)
    for the chat's persona pill. Personas carry no role gate, so a client admin
    sees the same enabled set (T13)."""
    app.sync_admin_personas()
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    r = c.get("/admin/api/chat/personas")
    assert r.status_code == 200
    items = r.get_json()["personas"]
    keys = [p["key"] for p in items]
    assert set(EXPECTED_PERSONA_KEYS) <= set(keys)
    assert keys[0] == "general"  # sort_order 0 → first
    for p in items:
        assert set(("key", "label", "icon", "description")).issubset(p.keys())
    if CLIENT_PW:
        cc = app.app.test_client()
        assert _login(cc, CLIENT_PW).status_code in (200, 302)
        rr = cc.get("/admin/api/chat/personas")
        assert rr.status_code == 200
        assert "general" in [p["key"] for p in rr.get_json()["personas"]]


def test_admin_dashboard_renders_admin_ai_tab():
    """The dashboard renders for a super-admin with the new Admin AI tab wired
    end-to-end (Jinja {% include %} of _admin-ai.html + nav button + loader).
    Catches a template syntax error in the new partial."""
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    r = c.get("/admin")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="tab-admin-ai"' in html              # partial included
    assert 'data-testid="tab-admin-ai"' in html     # nav button present
    assert "loadAdminAI()" in html                  # loader wired
