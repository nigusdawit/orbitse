"""Pins the dynamic admin-chat PALETTE subsystem (task 088 phase 3): the
slash-command palette, the capability-tray groups, and the empty-state starter
chips — formerly hardcoded JS consts in public/admin/csrf.js, now DB-backed +
super-admin-editable (registries → sync → CRUD → /admin/api/chat/palette).

Covers: registry contracts (counts + the KB action survives the port), the
preserve-edits seed, the JSONB round-trip (capability lines/examples), the
generic CRUD (super-admin gating, delete/reset rules, validation, dup), and the
role-filtered consumption endpoint (shapes match the old consts so the chat
renderers are unchanged). Embedded-Postgres harness; the tables exist (alembic
0032) but start empty, so seed tests call app.sync_admin_ai_config() explicitly.
"""
import json
import os

import app
import core  # noqa: F401 — imported for parity with the persona suite

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _login(c, pw):
    return c.post("/admin/login", data={"password": pw})


def _csrf(c):
    with c.session_transaction() as s:
        s["_csrf_token"] = "tok"
    return {"X-CSRF-Token": "tok"}


def _row(table, keycol, keyval):
    return app.query_db(
        f"SELECT * FROM {table} WHERE tenant_id=1 AND {keycol}=%s",
        (keyval,), fetchone=True)


def _jlist(v):
    if isinstance(v, str):
        return json.loads(v)
    return v


# --------------------------------------------------------------------------- #
# Registry contracts                                                          #
# --------------------------------------------------------------------------- #
def test_registry_counts_match_ported_consts():
    assert len(app._admin_command_registry()) == 22
    assert len(app._admin_capability_registry()) == 10
    assert len(app._admin_starter_registry()) == 9


def test_command_keys_unique_and_slashed():
    cmds = [c["cmd"] for c in app._admin_command_registry()]
    assert len(cmds) == len(set(cmds))
    assert all(c.startswith("/") for c in cmds)


def test_capability_kb_action_survived_port():
    caps = {c["cap_key"]: c for c in app._admin_capability_registry()}
    actions = [ex.get("action") for ex in caps["kb"]["examples"]]
    assert "kb" in actions  # the "Manage KB docs" action chip survived


# --------------------------------------------------------------------------- #
# Seed / refresh / preserve-edits                                             #
# --------------------------------------------------------------------------- #
def test_sync_seeds_all_palette_tables_machine_owned():
    app.sync_admin_ai_config()
    assert _row("admin_chat_commands", "cmd", "/sql")["is_builtin"] is True
    assert _row("admin_chat_commands", "cmd", "/sql")["updated_by"] is None
    assert _row("admin_chat_capabilities", "cap_key", "data")["is_builtin"] is True
    assert _row("admin_chat_starters", "starter_key", "run_sql")["is_builtin"] is True


def test_sync_capability_jsonb_roundtrip():
    app.sync_admin_ai_config()
    row = _row("admin_chat_capabilities", "cap_key", "data")
    lines = _jlist(row["lines"])
    examples = _jlist(row["examples"])
    assert isinstance(lines, list) and len(lines) >= 1
    assert isinstance(examples, list) and examples[0]["label"]


def test_sync_preserves_edited_command():
    app.sync_admin_ai_config()
    default_seed = {c["cmd"]: c for c in app._admin_command_registry()}["/tables"]["seed"]
    try:
        app.execute_db(
            "UPDATE admin_chat_commands SET seed=%s, updated_by=%s WHERE tenant_id=1 AND cmd=%s",
            ("EDITED SEED", "super_admin", "/tables"))
        app.sync_admin_ai_config()
        assert _row("admin_chat_commands", "cmd", "/tables")["seed"] == "EDITED SEED"
    finally:
        app.execute_db(
            "UPDATE admin_chat_commands SET seed=%s, updated_by=NULL WHERE tenant_id=1 AND cmd=%s",
            (default_seed, "/tables"))


# --------------------------------------------------------------------------- #
# Generic CRUD                                                                #
# --------------------------------------------------------------------------- #
def test_palette_crud_super_admin_gating():
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    for entity in ("commands", "capabilities", "starters"):
        assert c.get(f"/admin/api/admin-ai/{entity}").status_code == 200
    assert c.get("/admin/api/admin-ai/bogus").status_code == 404      # unknown entity
    assert app.app.test_client().get("/admin/api/admin-ai/commands").status_code == 401  # anon
    if CLIENT_PW:
        cc = app.app.test_client()
        assert _login(cc, CLIENT_PW).status_code in (200, 302)
        hdr = _csrf(cc)
        assert cc.get("/admin/api/admin-ai/commands").status_code == 403
        assert cc.post("/admin/api/admin-ai/commands",
                       json={"cmd": "/x"}, headers=hdr).status_code == 403


def test_palette_command_lifecycle_and_validation():
    app.sync_admin_ai_config()
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    hdr = _csrf(c)

    def find(cmd):
        lst = c.get("/admin/api/admin-ai/commands").get_json()["commands"]
        return next((x for x in lst if x["cmd"] == cmd), None)

    builtin = find("/sql")
    assert builtin and builtin["is_builtin"] is True

    # delete a built-in → 409
    assert c.delete(f"/admin/api/admin-ai/commands/{builtin['id']}", headers=hdr).status_code == 409
    # reserved key on create → 400; bad slug → 400
    assert c.post("/admin/api/admin-ai/commands", json={"cmd": "/sql"}, headers=hdr).status_code == 400
    assert c.post("/admin/api/admin-ai/commands", json={"cmd": "noslash"}, headers=hdr).status_code == 400

    # create a custom command → 201
    assert c.post("/admin/api/admin-ai/commands",
                  json={"cmd": "/mycmd", "icon": "⭐", "group_label": "Custom",
                        "seed": "do the thing", "persona": "data_analyst"},
                  headers=hdr).status_code == 201
    try:
        custom = find("/mycmd")
        assert custom and custom["is_builtin"] is False
        # duplicate custom key → 409
        assert c.post("/admin/api/admin-ai/commands",
                      json={"cmd": "/mycmd"}, headers=hdr).status_code == 409
        # reset a CUSTOM → 400 (only built-ins reset)
        assert c.post(f"/admin/api/admin-ai/commands/{custom['id']}/reset",
                      headers=hdr).status_code == 400
        # update custom → 200
        assert c.put(f"/admin/api/admin-ai/commands/{custom['id']}",
                     json={"cmd": "/mycmd", "icon": "⭐", "seed": "do it better"},
                     headers=hdr).status_code == 200
        assert _row("admin_chat_commands", "cmd", "/mycmd")["seed"] == "do it better"
        # delete custom → 200
        assert c.delete(f"/admin/api/admin-ai/commands/{custom['id']}", headers=hdr).status_code == 200
        assert find("/mycmd") is None
    finally:
        cm = find("/mycmd")
        if cm:
            c.delete(f"/admin/api/admin-ai/commands/{cm['id']}", headers=hdr)


def test_palette_reset_builtin_restores_default():
    app.sync_admin_ai_config()
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    hdr = _csrf(c)
    lst = c.get("/admin/api/admin-ai/commands").get_json()["commands"]
    sql = next(x for x in lst if x["cmd"] == "/sql")
    default_seed = {x["cmd"]: x for x in app._admin_command_registry()}["/sql"]["seed"]
    # dirty it (stamps updated_by), then reset → default + machine-owned again
    c.put(f"/admin/api/admin-ai/commands/{sql['id']}",
          json={"cmd": "/sql", "icon": "🧮", "group_label": "Data & SQL",
                "tool": "admin_run_sql", "seed": "DIRTY", "tail": True,
                "persona": "data_analyst"}, headers=hdr)
    assert _row("admin_chat_commands", "cmd", "/sql")["updated_by"] is not None
    assert c.post(f"/admin/api/admin-ai/commands/{sql['id']}/reset", headers=hdr).status_code == 200
    row = _row("admin_chat_commands", "cmd", "/sql")
    assert row["updated_by"] is None
    assert row["seed"] == default_seed


def test_palette_capability_create_jsonb_roundtrip():
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    hdr = _csrf(c)
    body = {"cap_key": "mycap", "title": "My Cap", "icon": "⭐",
            "lines": ["line one", "line two"],
            "examples": [{"label": "Ex1", "seed": "do x", "persona": "data_analyst"}]}
    assert c.post("/admin/api/admin-ai/capabilities", json=body, headers=hdr).status_code == 201

    def find():
        lst = c.get("/admin/api/admin-ai/capabilities").get_json()["capabilities"]
        return next((x for x in lst if x["cap_key"] == "mycap"), None)
    try:
        mc = find()
        assert mc is not None
        assert mc["lines"] == ["line one", "line two"]
        assert mc["examples"][0]["label"] == "Ex1"
        assert mc["examples"][0]["persona"] == "data_analyst"
    finally:
        mc = find()
        if mc:
            c.delete(f"/admin/api/admin-ai/capabilities/{mc['id']}", headers=hdr)


# --------------------------------------------------------------------------- #
# Consumption endpoint (role-filtered; chat-shaped)                            #
# --------------------------------------------------------------------------- #
def test_chat_palette_shape_and_role_filter():
    app.sync_admin_ai_config()
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    data = c.get("/admin/api/chat/palette").get_json()
    assert set(("commands", "capabilities", "starters")).issubset(data.keys())
    # command shape matches the old csrf const (group/desc, not group_label/description)
    sql = next(x for x in data["commands"] if x["cmd"] == "/sql")
    assert "group" in sql and "desc" in sql and sql["persona"] == "data_analyst" and sql["tail"] is True
    # capability shape: key/grant + lists
    datacap = next(x for x in data["capabilities"] if x["key"] == "data")
    assert "grant" in datacap and isinstance(datacap["lines"], list)
    # super-admin sees super-only rows
    assert any(x["cmd"] == "/research" for x in data["commands"])
    assert any(x["key"] == "research" for x in data["capabilities"])

    if CLIENT_PW:
        cc = app.app.test_client()
        assert _login(cc, CLIENT_PW).status_code in (200, 302)
        cdata = cc.get("/admin/api/chat/palette").get_json()
        cmds = [x["cmd"] for x in cdata["commands"]]
        assert "/sql" in cmds                       # normal command visible
        assert "/research" not in cmds              # super-only command hidden
        assert "/design" not in cmds
        capkeys = [x["key"] for x in cdata["capabilities"]]
        assert "data" in capkeys
        assert "research" not in capkeys            # super-only group hidden
        starters = [s["label"] for s in cdata["starters"]]
        assert all("Research a topic" != s for s in starters)  # super starter hidden
