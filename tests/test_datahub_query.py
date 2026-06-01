"""Task 054 — connection-aware introspection + read-only query for the AI.
Embedded Postgres (+ a SECOND instance acting as an 'external' database).

Verifies the assistant can inspect + query connection 0 (the app's own DB) and a
real external Postgres connection, that writes/DDL are rejected on BOTH, that the
decrypted URL is never returned, that the semantic layer is merged into inspect
output, and that the reviewed data-dictionary context is built for the prompt.
"""
import os

import app

EXT_URL = os.environ.get("EXT_TEST_DB_URL", "")


def _ext_connection_id():
    """Create (once) an external_data_connections row pointing at the second
    embedded Postgres, return its id. Skips if no external URL provided."""
    if not EXT_URL:
        return None
    row = app.query_db("SELECT id FROM external_data_connections WHERE name='ext-test'",
                       fetchone=True)
    if row:
        return row["id"]
    enc = app.encrypt_secret(EXT_URL)
    row = app.execute_db(
        "INSERT INTO external_data_connections (name, kind, encrypted_config) "
        "VALUES ('ext-test','postgres',%s) RETURNING id", (enc,))
    return row["id"]


# ---- app DB (connection 0) --------------------------------------------------

def test_inspect_app_db_overview():
    out = app._admin_tool_inspect_connection(0)
    assert "tables" in out
    names = {t["table"] for t in out["tables"]}
    assert "leads" in names      # a known app table
    assert "relationships" in out and "examples" in out


def test_inspect_app_db_table_columns():
    out = app._admin_tool_inspect_connection(0, table="leads")
    assert out.get("table") == "leads"
    cols = {c["column"] for c in out["columns"]}
    assert "email" in cols


def test_inspect_merges_annotations():
    app.execute_db("DELETE FROM db_table_annotations WHERE connection_id=0 AND table_name='leads'")
    app.execute_db(
        "INSERT INTO db_table_annotations (connection_id, table_name, description, reviewed) "
        "VALUES (0,'leads','Captured sales leads',TRUE)")
    try:
        out = app._admin_tool_inspect_connection(0)
        leads = [t for t in out["tables"] if t["table"] == "leads"][0]
        assert leads["description"] == "Captured sales leads"
    finally:
        app.execute_db("DELETE FROM db_table_annotations WHERE connection_id=0 AND table_name='leads'")


def test_query_app_db_readonly_ok():
    out = app._admin_tool_query_connection(0, sql="SELECT 1 AS x")
    assert out.get("row_count") == 1 or (out.get("rows") and out["rows"][0])


def test_query_app_db_rejects_write():
    out = app._admin_tool_query_connection(0, sql="DELETE FROM leads")
    assert "error" in out


# ---- external connection ----------------------------------------------------

def test_external_inspect_and_query():
    cid = _ext_connection_id()
    if cid is None:
        return  # no external URL in this run
    # The gate seeded a table `widgets(id, label)` in the external DB.
    ov = app._admin_tool_inspect_connection(cid)
    assert "tables" in ov
    names = {t["table"] for t in ov["tables"]}
    assert "widgets" in names
    detail = app._admin_tool_inspect_connection(cid, table="widgets")
    assert {c["column"] for c in detail["columns"]} >= {"id", "label"}
    # Read works...
    q = app._admin_tool_query_connection(cid, sql="SELECT count(*) AS n FROM widgets")
    assert "rows" in q and q["row_count"] >= 1
    # ...writes are rejected.
    w = app._admin_tool_query_connection(cid, sql="INSERT INTO widgets (label) VALUES ('x')")
    assert "error" in w


def test_query_unknown_connection_errors():
    out = app._admin_tool_query_connection(99999, sql="SELECT 1")
    assert "error" in out and "not found" in out["error"].lower()


def test_decrypted_url_never_returned():
    cid = _ext_connection_id()
    if cid is None:
        return
    out = app._admin_tool_query_connection(cid, sql="SELECT 1 AS x")
    blob = repr(out)
    assert "password" not in blob.lower() and "@" not in blob  # no DSN leakage


def test_external_secret_column_redacted():
    cid = _ext_connection_id()
    if cid is None:
        return
    # The gate seeded ext table `creds(id, password)`. The secret-named column
    # must come back masked, matching the app-DB path's redaction.
    out = app._admin_tool_query_connection(cid, sql="SELECT id, password FROM creds")
    assert "rows" in out and out["rows"]
    flat = repr(out["rows"])
    assert "topsecret" not in flat            # the real value never surfaces
    assert app._REDACTED_PLACEHOLDER in flat  # it's masked


def test_external_connect_error_has_no_dsn():
    # A connection whose URL points nowhere must NOT echo host/user/dbname.
    enc = app.encrypt_secret("postgresql://secretuser:pw@nonexistent-host-xyz:5432/hiddendb")
    row = app.execute_db(
        "INSERT INTO external_data_connections (name, kind, encrypted_config) "
        "VALUES ('ext-bad','postgres',%s) RETURNING id", (enc,))
    try:
        out = app._admin_tool_query_connection(row["id"], sql="SELECT 1")
        blob = repr(out).lower()
        assert "error" in out
        assert "nonexistent-host-xyz" not in blob and "secretuser" not in blob
        assert "hiddendb" not in blob
    finally:
        app.execute_db("DELETE FROM external_data_connections WHERE id=%s", (row["id"],))


# ---- reviewed data-dictionary context --------------------------------------

def test_admin_context_empty_then_populated():
    app.execute_db("DELETE FROM db_table_annotations WHERE connection_id=0")
    assert app._dh_admin_context() == ""        # nothing reviewed yet
    app.execute_db(
        "INSERT INTO db_table_annotations (connection_id, table_name, description, reviewed) "
        "VALUES (0,'orders','Customer orders',TRUE)")
    try:
        ctx = app._dh_admin_context()
        assert "orders" in ctx and "Customer orders" in ctx
        # An UNreviewed row must NOT appear (AI drafts aren't ground truth).
        app.execute_db(
            "INSERT INTO db_table_annotations (connection_id, table_name, description, "
            "ai_generated, reviewed) VALUES (0,'secret_draft','unreviewed',TRUE,FALSE)")
        assert "secret_draft" not in app._dh_admin_context()
    finally:
        app.execute_db("DELETE FROM db_table_annotations WHERE connection_id=0")


# ---- registry ---------------------------------------------------------------

def test_tools_registered():
    assert "admin_inspect_connection" in app.ADMIN_TOOL_FUNCTIONS
    assert "admin_query_connection" in app.ADMIN_TOOL_FUNCTIONS
    names = {t["function"]["name"] for t in app.ADMIN_TOOLS}
    assert {"admin_inspect_connection", "admin_query_connection"} <= names
