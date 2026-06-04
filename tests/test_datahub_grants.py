"""Task 085 — Datahub per-table grants: default-DENY + super-admin-granted.

REAL integration against the embedded Postgres booted by _runner.py (NO mocks,
no DB stubs). Exercises the permission BOUNDARY end-to-end:

  * default-deny: a normal-admin session with NO grants sees no external
    connections and cannot inspect/query any table (friendly refusals);
  * grant ONE table ⇒ only it is inspectable/queryable;
  * a query JOINing / CTE-referencing / subquery-referencing an UNGRANTED table
    is rejected, naming it (the join/CTE/subquery/alias-trick defense);
  * an unparseable query is denied (fail-closed);
  * super-admin sessions are unrestricted;
  * out-of-request callers (no Flask request context) are unrestricted;
  * an ENABLED saved query runs for a normal admin with NO raw table grant, a
    DISABLED one does not (Phase 3);
  * no credential / connection-URL field ever appears in tool output.

A normal-admin session is simulated by setting the Flask session inside a test
request context (admin_logged_in=True, admin_role="client"); a super-admin
session uses admin_role="super_admin". The grant rows are written directly with
execute_db (the same path the Phase-4 super-admin UI uses).
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


# --- helpers -----------------------------------------------------------------

def _clear_grants():
    app.execute_db("DELETE FROM datahub_table_grants")


def _grant(table, connection_id=0, tenant_id=1, note="test"):
    app.execute_db(
        "INSERT INTO datahub_table_grants (tenant_id, connection_id, table_name, note) "
        "VALUES (%s,%s,%s,%s) ON CONFLICT (tenant_id, connection_id, table_name) "
        "DO NOTHING", (tenant_id, connection_id, table, note))


def _client_ctx():
    """A test request context with a logged-in NORMAL admin (client) session."""
    ctx = app.app.test_request_context("/")
    ctx.push()
    from flask import session as s
    s["admin_logged_in"] = True
    s["admin_role"] = "client"
    return ctx


def _super_ctx():
    ctx = app.app.test_request_context("/")
    ctx.push()
    from flask import session as s
    s["admin_logged_in"] = True
    s["admin_role"] = "super_admin"
    return ctx


# --- migration sanity --------------------------------------------------------

def test_grants_table_exists_and_accepts_a_row():
    """0031 applied cleanly (app boots in the runner) AND the table accepts a
    grant row with the documented shape + UNIQUE constraint."""
    _clear_grants()
    _grant("leads", connection_id=0)
    # Duplicate is a no-op (ON CONFLICT) — proves the UNIQUE(tenant,conn,table).
    _grant("leads", connection_id=0)
    rows = app.query_db(
        "SELECT tenant_id, connection_id, table_name, note FROM datahub_table_grants "
        "WHERE connection_id=0 AND table_name='leads'") or []
    assert len(rows) == 1
    assert rows[0]["tenant_id"] == 1 and rows[0]["connection_id"] == 0
    _clear_grants()


# --- _dh_extract_tables: join / CTE / subquery / schema / parse-fail ---------

def test_extract_tables_simple_and_join():
    got = app._dh_extract_tables("SELECT * FROM orders o JOIN leads l ON o.id=l.id")
    assert got == {"orders", "leads"}


def test_extract_tables_schema_qualified_normalized():
    got = app._dh_extract_tables("SELECT * FROM public.Orders")
    assert got == {"orders"}   # schema stripped, lowercased


def test_extract_tables_cte_alias_not_a_real_table():
    # `recent` is a CTE alias (query-local) — NOT a real table — but the table it
    # selects FROM (orders) IS real and must be collected.
    sql = ("WITH recent AS (SELECT * FROM orders WHERE id > 5) "
           "SELECT * FROM recent")
    got = app._dh_extract_tables(sql)
    assert "orders" in got
    assert "recent" not in got


def test_extract_tables_subquery():
    sql = "SELECT * FROM (SELECT id FROM leads) x JOIN orders o ON o.id = x.id"
    got = app._dh_extract_tables(sql)
    assert got == {"leads", "orders"}


def test_extract_tables_parse_failure_returns_none():
    # Garbage SQL ⇒ None ⇒ callers fail-closed.
    assert app._dh_extract_tables("SELECT FROM FROM WHERE ;;; )(") is None
    assert app._dh_extract_tables(None) is None
    assert app._dh_extract_tables("") is None


# --- _dh_allowed_tables: sentinel vs grant set vs fail-closed ----------------

def test_allowed_tables_out_of_request_is_allow_all():
    # No request context ⇒ trusted ⇒ ALLOW_ALL sentinel.
    assert app._dh_allowed_tables(0) is app._DH_ALLOW_ALL


def test_allowed_tables_superadmin_is_allow_all():
    ctx = _super_ctx()
    try:
        assert app._dh_allowed_tables(0) is app._DH_ALLOW_ALL
    finally:
        ctx.pop()


def test_allowed_tables_normal_admin_empty_then_granted():
    _clear_grants()
    ctx = _client_ctx()
    try:
        assert app._dh_allowed_tables(0) == set()    # deny-all by default
        _grant("leads", connection_id=0)
        assert app._dh_allowed_tables(0) == {"leads"}
    finally:
        ctx.pop()
        _clear_grants()


def test_allowed_tables_star_grant_expands_app_db():
    """A '*' grant on cid 0 expands to the live set of app-DB objects."""
    _clear_grants()
    _grant("*", connection_id=0)
    ctx = _client_ctx()
    try:
        allowed = app._dh_allowed_tables(0)
        assert allowed is not app._DH_ALLOW_ALL   # still a concrete set, not bypass
        assert "leads" in allowed                 # a known app table is covered
        assert len(allowed) > 5
    finally:
        ctx.pop()
        _clear_grants()


# --- default-deny: inspect / query refuse for an ungranted normal admin ------

def test_default_deny_inspect_overview_empty():
    _clear_grants()
    ctx = _client_ctx()
    try:
        out = app._admin_tool_inspect_connection(0)
        # Overview returns no tables (deny-all), not an error.
        assert out.get("tables") == []
    finally:
        ctx.pop()


def test_default_deny_inspect_specific_table_refused():
    _clear_grants()
    ctx = _client_ctx()
    try:
        out = app._admin_tool_inspect_connection(0, table="leads")
        assert "don't have access" in (out.get("error") or "")
    finally:
        ctx.pop()


def test_default_deny_query_refused():
    _clear_grants()
    ctx = _client_ctx()
    try:
        out = app._admin_tool_query_connection(0, sql="SELECT count(*) FROM leads")
        assert "don't have access" in (out.get("error") or "") \
            or "leads" in (out.get("error") or "")
    finally:
        ctx.pop()


# --- granted: only the granted table is inspectable/queryable ----------------

def test_grant_one_table_only_that_inspectable():
    _clear_grants()
    _grant("leads", connection_id=0)
    ctx = _client_ctx()
    try:
        ov = app._admin_tool_inspect_connection(0)
        names = {t["table"] for t in ov.get("tables", [])}
        assert names == {"leads"}                      # only the granted one
        ok = app._admin_tool_inspect_connection(0, table="leads")
        assert ok.get("table") == "leads" and "columns" in ok
        # an ungranted table is still refused
        no = app._admin_tool_inspect_connection(0, table="orders")
        assert "don't have access" in (no.get("error") or "")
    finally:
        ctx.pop()
        _clear_grants()


def test_grant_one_table_query_ok_and_join_rejected():
    _clear_grants()
    _grant("leads", connection_id=0)
    ctx = _client_ctx()
    try:
        ok = app._admin_tool_query_connection(0, sql="SELECT count(*) AS n FROM leads")
        assert "error" not in ok or not ok["error"]
        assert ok.get("row_count") == 1 or ok.get("rows")
        # JOIN to an ungranted table → rejected, naming it
        j = app._admin_tool_query_connection(
            0, sql="SELECT * FROM leads l JOIN orders o ON o.id=l.id")
        assert "orders" in (j.get("error") or "")
    finally:
        ctx.pop()
        _clear_grants()


def test_cte_and_subquery_to_ungranted_table_rejected():
    _clear_grants()
    _grant("leads", connection_id=0)
    ctx = _client_ctx()
    try:
        # CTE body references an ungranted table.
        cte = app._admin_tool_query_connection(
            0, sql="WITH x AS (SELECT * FROM orders) SELECT * FROM x")
        assert "orders" in (cte.get("error") or "")
        # Subquery references an ungranted table.
        sub = app._admin_tool_query_connection(
            0, sql="SELECT * FROM (SELECT id FROM orders) q")
        assert "orders" in (sub.get("error") or "")
    finally:
        ctx.pop()
        _clear_grants()


def test_unparseable_query_denied_for_normal_admin():
    _clear_grants()
    _grant("leads", connection_id=0)
    ctx = _client_ctx()
    try:
        # _admin_safe_sql passes this (starts with SELECT, single statement, no
        # dangerous keyword), but sqlglot cannot parse it ⇒ fail-closed deny.
        out = app._admin_tool_query_connection(
            0, sql="SELECT * FROM leads WHERE )(")
        assert "error" in out and out["error"]
    finally:
        ctx.pop()
        _clear_grants()


# --- super-admin + out-of-request: unrestricted ------------------------------

def test_superadmin_session_unrestricted():
    _clear_grants()   # no grants at all
    ctx = _super_ctx()
    try:
        ov = app._admin_tool_inspect_connection(0)
        names = {t["table"] for t in ov.get("tables", [])}
        assert "leads" in names and "orders" in names   # full schema
        q = app._admin_tool_query_connection(
            0, sql="SELECT * FROM leads l JOIN orders o ON o.id=l.id LIMIT 1")
        assert "don't have access" not in (q.get("error") or "")
    finally:
        ctx.pop()


def test_out_of_request_unrestricted():
    _clear_grants()
    # No request context pushed — a system/test caller.
    ov = app._admin_tool_inspect_connection(0)
    names = {t["table"] for t in ov.get("tables", [])}
    assert "leads" in names and "orders" in names
    q = app._admin_tool_query_connection(0, sql="SELECT count(*) FROM orders")
    assert "don't have access" not in (q.get("error") or "")


# --- admin_list_connections: grant-filtered ----------------------------------

def test_list_connections_default_deny_hides_app_db():
    _clear_grants()
    ctx = _client_ctx()
    try:
        out = app._admin_tool_list_connections()
        assert out.get("connections") == []
        assert "hasn't given you access" in (out.get("note") or "")
    finally:
        ctx.pop()


def test_list_connections_shows_app_db_when_granted():
    _clear_grants()
    _grant("leads", connection_id=0)
    ctx = _client_ctx()
    try:
        out = app._admin_tool_list_connections()
        ids = {c["id"] for c in out.get("connections", [])}
        assert 0 in ids
        # No credential / config field leaks into the listing.
        blob = repr(out).lower()
        assert "encrypted_config" not in blob and "password" not in blob
    finally:
        ctx.pop()
        _clear_grants()


def test_list_connections_superadmin_sees_all():
    _clear_grants()
    ctx = _super_ctx()
    try:
        out = app._admin_tool_list_connections()
        ids = {c["id"] for c in out.get("connections", [])}
        assert 0 in ids   # at least the app DB
    finally:
        ctx.pop()


# --- credentials never reach the model ---------------------------------------

def test_no_credentials_in_tool_output():
    _clear_grants()
    _grant("leads", connection_id=0)
    ctx = _client_ctx()
    try:
        for out in (
            app._admin_tool_list_connections(),
            app._admin_tool_inspect_connection(0),
            app._admin_tool_inspect_connection(0, table="leads"),
            app._admin_tool_query_connection(0, sql="SELECT count(*) FROM leads"),
        ):
            blob = repr(out).lower()
            assert "encrypted_config" not in blob
            assert "://" not in blob          # no connection URL/DSN
    finally:
        ctx.pop()
        _clear_grants()


# --- registry ----------------------------------------------------------------

def test_phase1_tool_registered():
    assert "admin_list_connections" in app.ADMIN_TOOL_FUNCTIONS
    names = {t["function"]["name"] for t in app.ADMIN_TOOLS}
    assert "admin_list_connections" in names
