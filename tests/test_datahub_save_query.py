"""Task 056 — save SQL as a (connection-aware) skill. Embedded Postgres (+ ext).

Verifies admin_save_query creates a DISABLED skill (review gate), the skill
executes against the app DB and against an external connection, and the
custom-sql route accepts connection_id.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
EXT_URL = os.environ.get("EXT_TEST_DB_URL", "")


def _cleanup(name):
    row = app.query_db("SELECT id FROM custom_sql_skills WHERE name=%s", (name,), fetchone=True)
    if row:
        app.execute_db("DELETE FROM custom_sql_skills WHERE id=%s", (row["id"],))
    app.execute_db("DELETE FROM agent_skills WHERE name=%s", (name,))


def _ext_id():
    if not EXT_URL:
        return None
    row = app.query_db("SELECT id FROM external_data_connections WHERE name='ext-sq'", fetchone=True)
    if row:
        return row["id"]
    return app.execute_db(
        "INSERT INTO external_data_connections (name, kind, encrypted_config) "
        "VALUES ('ext-sq','postgres',%s) RETURNING id", (app.encrypt_secret(EXT_URL),))["id"]


# ---- save_query creates a disabled skill -----------------------------------

def test_save_query_creates_disabled_skill():
    _cleanup("lead_count")
    try:
        out = app._admin_tool_save_query(name="lead_count",
                                         sql="SELECT count(*) AS n FROM leads",
                                         description="Total leads")
        assert out.get("ok") is True and out.get("enabled") is False
        row = app.query_db("SELECT enabled, connection_id FROM custom_sql_skills "
                           "WHERE name='lead_count'", fetchone=True)
        assert row["enabled"] is False and row["connection_id"] == 0
        # An agent_skills wrapper exists (disabled) so it's reviewable in Skills.
        assert app.query_db("SELECT 1 FROM agent_skills WHERE name='lead_count'", fetchone=True)
    finally:
        _cleanup("lead_count")


def test_save_query_rejects_writes_and_bad_names():
    assert "error" in app._admin_tool_save_query(name="bad", sql="DELETE FROM leads")
    assert "error" in app._admin_tool_save_query(name="Has Space", sql="SELECT 1")


def test_save_query_duplicate_name():
    _cleanup("dup_skill")
    try:
        app._admin_tool_save_query(name="dup_skill", sql="SELECT 1 AS x")
        assert "error" in app._admin_tool_save_query(name="dup_skill", sql="SELECT 2 AS y")
    finally:
        _cleanup("dup_skill")


# ---- execution: app DB + external ------------------------------------------

def test_saved_skill_executes_app_db():
    _cleanup("app_one")
    try:
        app._admin_tool_save_query(name="app_one", sql="SELECT 1 AS x")
        # Enable it so the dispatcher will run it.
        app.execute_db("UPDATE custom_sql_skills SET enabled=TRUE WHERE name='app_one'")
        app.execute_db("UPDATE agent_skills SET enabled=TRUE WHERE name='app_one'")
        res, rows = app._exec_custom_sql("app_one", {})
        assert "error" not in res
    finally:
        _cleanup("app_one")


def test_saved_skill_executes_external():
    cid = _ext_id()
    if cid is None:
        return
    _cleanup("ext_widgets")
    try:
        app._admin_tool_save_query(name="ext_widgets",
                                   sql="SELECT count(*) AS n FROM widgets",
                                   connection_id=cid)
        app.execute_db("UPDATE custom_sql_skills SET enabled=TRUE WHERE name='ext_widgets'")
        app.execute_db("UPDATE agent_skills SET enabled=TRUE WHERE name='ext_widgets'")
        res, rows = app._exec_custom_sql("ext_widgets", {})
        assert "error" not in res and res.get("count", 0) >= 1
    finally:
        _cleanup("ext_widgets")


# ---- manual route accepts connection_id ------------------------------------

def test_custom_sql_route_accepts_connection_id():
    _cleanup("route_skill")
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    try:
        r = c.post("/admin/api/custom-sql",
                   json={"name": "route_skill", "description": "d",
                         "sql_template": "SELECT 1 AS x", "connection_id": 0},
                   headers={"X-CSRF-Token": "t"})
        assert r.status_code == 201, r.get_data(as_text=True)
        assert r.get_json().get("connection_id") == 0
    finally:
        _cleanup("route_skill")


def test_tool_registered():
    assert "admin_save_query" in app.ADMIN_TOOL_FUNCTIONS
    names = {t["function"]["name"] for t in app.ADMIN_TOOLS}
    assert "admin_save_query" in names
