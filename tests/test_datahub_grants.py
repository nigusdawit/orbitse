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


# =============================================================================
# Phase 2 — visualize + persist for normal admins
# =============================================================================

def _wipe_dash(*names):
    for n in names:
        app.execute_db("DELETE FROM dashboards WHERE name=%s", (n,))


def test_normal_admin_can_save_static_chart_no_grants():
    """A static chart is numbers the AI already computed — always saveable, even
    with zero grants."""
    _clear_grants()
    _wipe_dash("P2 Static")
    ctx = _client_ctx()
    try:
        out = app._admin_tool_create_dashboard(name="P2 Static", widgets=[
            {"name": "Rev", "chart": {"type": "bar", "labels": ["Jan"], "values": [10]}}])
        assert out.get("ok") is True and out.get("widgets") == 1
    finally:
        ctx.pop()
        _wipe_dash("P2 Static")


def test_normal_admin_external_widget_requires_grant():
    """An external_postgres widget whose query touches an ungranted table is
    rejected (no dashboard left behind); the SAME widget on a granted table is
    accepted."""
    _clear_grants()
    _wipe_dash("P2 Ext")
    ctx = _client_ctx()
    try:
        # ungranted -> rejected, no dashboard created
        bad = app._admin_tool_create_dashboard(name="P2 Ext", widgets=[
            {"name": "W", "widget_type": "table", "source_type": "external_postgres",
             "source_config": {"connection_id": 0, "query": "SELECT * FROM orders"}}])
        assert "error" in bad
        assert not app.query_db("SELECT 1 FROM dashboards WHERE name='P2 Ext'",
                                fetchone=True)   # no dashboard left behind
        # grant orders -> accepted
        _grant("orders", connection_id=0)
        ok = app._admin_tool_create_dashboard(name="P2 Ext", widgets=[
            {"name": "W", "widget_type": "table", "source_type": "external_postgres",
             "source_config": {"connection_id": 0, "query": "SELECT id FROM orders"}}])
        assert ok.get("ok") is True
    finally:
        ctx.pop()
        _wipe_dash("P2 Ext")
        _clear_grants()


def test_normal_admin_internal_db_widget_requires_grant():
    _clear_grants()
    _wipe_dash("P2 Int")
    ctx = _client_ctx()
    try:
        bad = app._admin_tool_create_dashboard(name="P2 Int", widgets=[
            {"name": "K", "widget_type": "kpi", "source_type": "internal_db",
             "source_config": {"table": "orders", "agg_fn": "count"}}])
        assert "don't have access" in (bad.get("error") or "")
        _grant("orders", connection_id=0)
        ok = app._admin_tool_create_dashboard(name="P2 Int", widgets=[
            {"name": "K", "widget_type": "kpi", "source_type": "internal_db",
             "source_config": {"table": "orders", "agg_fn": "count"}}])
        assert ok.get("ok") is True
    finally:
        ctx.pop()
        _wipe_dash("P2 Int")
        _clear_grants()


def test_normal_admin_builtin_widget_denied():
    """builtin / external_rest sit outside the per-table grant model ⇒ denied
    for a normal admin (fail-closed)."""
    _clear_grants()
    _wipe_dash("P2 Builtin")
    ctx = _client_ctx()
    try:
        out = app._admin_tool_create_dashboard(name="P2 Builtin", widgets=[
            {"name": "V", "widget_type": "kpi", "source_type": "builtin",
             "source_config": {"metric": "visitors"}}])
        assert "error" in out
    finally:
        ctx.pop()
        _wipe_dash("P2 Builtin")


def test_superadmin_create_dashboard_unrestricted():
    """Super-admin keeps the old freedom: a builtin widget + an external query
    on any table both succeed."""
    _clear_grants()
    _wipe_dash("P2 SA")
    ctx = _super_ctx()
    try:
        out = app._admin_tool_create_dashboard(name="P2 SA", widgets=[
            {"name": "V", "widget_type": "kpi", "source_type": "builtin",
             "source_config": {"metric": "visitors"}},
            {"name": "Q", "widget_type": "table", "source_type": "external_postgres",
             "source_config": {"connection_id": 0, "query": "SELECT * FROM orders"}}])
        assert out.get("ok") is True and out.get("widgets") == 2
    finally:
        ctx.pop()
        _wipe_dash("P2 SA")


def test_add_widget_grant_enforced():
    _clear_grants()
    _wipe_dash("P2 Add")
    # out-of-request: create the dashboard unrestricted
    base = app._admin_tool_create_dashboard(name="P2 Add", widgets=[])
    did = base["dashboard_id"]
    ctx = _client_ctx()
    try:
        # static chart appends fine with no grants
        a = app._admin_tool_add_widget(dashboard_id=did, widget={
            "name": "S", "chart": {"type": "kpi", "value": 1, "label": "x"}})
        assert a.get("ok") is True and a.get("widget_id")
        # external query on an ungranted table is refused
        b = app._admin_tool_add_widget(dashboard_id=did, widget={
            "name": "Q", "widget_type": "table", "source_type": "external_postgres",
            "source_config": {"connection_id": 0, "query": "SELECT * FROM leads"}})
        assert "leads" in (b.get("error") or "")
        # unknown dashboard
        assert "not found" in (app._admin_tool_add_widget(
            dashboard_id=999999, widget={"chart": {"type": "kpi", "value": 1}}
        ).get("error") or "")
    finally:
        ctx.pop()
        _wipe_dash("P2 Add")


def test_admin_context_playbook_and_grant_gating():
    """The playbook is always present; for a normal admin the data dictionary is
    grant-gated and the no-grants case says so plainly."""
    app.execute_db("DELETE FROM db_table_annotations WHERE connection_id=0")
    app.execute_db(
        "INSERT INTO db_table_annotations (connection_id, table_name, description, reviewed) "
        "VALUES (0,'orders','Customer orders',TRUE),(0,'leads','Sales leads',TRUE)")
    _clear_grants()
    try:
        # No grants → no-access message (+ playbook), no schema leak.
        ctx = _client_ctx()
        try:
            no = app._dh_admin_context()
            assert "PLAYBOOK" in no and "hasn't given you access" in no
            assert "Customer orders" not in no and "Sales leads" not in no
        finally:
            ctx.pop()
        # Grant orders only → dictionary shows orders, NOT leads.
        _grant("orders", connection_id=0)
        ctx = _client_ctx()
        try:
            one = app._dh_admin_context()
            assert "orders" in one and "Customer orders" in one
            assert "leads" not in one.lower().split("playbook")[-1] or "Sales leads" not in one
            assert "Sales leads" not in one
        finally:
            ctx.pop()
        # Super-admin → full dictionary.
        ctx = _super_ctx()
        try:
            full = app._dh_admin_context()
            assert "Customer orders" in full and "Sales leads" in full
        finally:
            ctx.pop()
    finally:
        app.execute_db("DELETE FROM db_table_annotations WHERE connection_id=0")
        _clear_grants()


# =============================================================================
# Phase 3 — authorized saved queries runnable by normal admins
# =============================================================================

def _cleanup_skill(name):
    row = app.query_db("SELECT id FROM custom_sql_skills WHERE name=%s", (name,),
                       fetchone=True)
    if row:
        app.execute_db("DELETE FROM custom_sql_skills WHERE id=%s", (row["id"],))
    app.execute_db("DELETE FROM agent_skills WHERE name=%s", (name,))


def _make_saved_query(name, sql, enabled):
    """Create a saved SQL skill (out-of-request = trusted), optionally enabling
    it. Enabling mirrors the super-admin authorizing it in the Skills tab."""
    _cleanup_skill(name)
    app._admin_tool_save_query(name=name, sql=sql, description=name + " report")
    if enabled:
        app.execute_db("UPDATE custom_sql_skills SET enabled=TRUE WHERE name=%s", (name,))
        app.execute_db("UPDATE agent_skills SET enabled=TRUE WHERE name=%s", (name,))


def test_enabled_saved_query_runs_for_normal_admin_without_grant():
    """An ENABLED saved query reads data the normal admin has NO raw grant for —
    the super-admin vetted the exact SQL by enabling it."""
    _clear_grants()                       # no table grants at all
    _make_saved_query("g_enabled", "SELECT count(*) AS n FROM leads", enabled=True)
    ctx = _client_ctx()
    try:
        out = app._admin_tool_run_saved_query(name="g_enabled")
        assert "error" not in out or not out["error"]
        # Sanity: the same table via raw query IS refused (proves the bypass is
        # the saved-query path, not a stray grant).
        raw = app._admin_tool_query_connection(0, sql="SELECT count(*) FROM leads")
        assert (raw.get("error") or "")
    finally:
        ctx.pop()
        _cleanup_skill("g_enabled")


def test_disabled_saved_query_refused_for_normal_admin():
    _clear_grants()
    _make_saved_query("g_disabled", "SELECT count(*) AS n FROM leads", enabled=False)
    ctx = _client_ctx()
    try:
        out = app._admin_tool_run_saved_query(name="g_disabled")
        assert "error" in out
        assert "authorized" in out["error"].lower()
    finally:
        ctx.pop()
        _cleanup_skill("g_disabled")


def test_list_saved_queries_only_enabled_for_normal_admin():
    _clear_grants()
    _make_saved_query("g_on", "SELECT 1 AS x", enabled=True)
    _make_saved_query("g_off", "SELECT 2 AS y", enabled=False)
    ctx = _client_ctx()
    try:
        out = app._admin_tool_list_saved_queries()
        names = {q["name"] for q in out.get("saved_queries", [])}
        assert "g_on" in names
        assert "g_off" not in names
    finally:
        ctx.pop()
        _cleanup_skill("g_on")
        _cleanup_skill("g_off")


def test_run_saved_query_unknown_name():
    ctx = _client_ctx()
    try:
        out = app._admin_tool_run_saved_query(name="does_not_exist_xyz")
        assert "error" in out and "no saved query" in out["error"].lower()
    finally:
        ctx.pop()


def test_saved_query_output_has_no_credentials():
    _clear_grants()
    _make_saved_query("g_secret", "SELECT count(*) AS n FROM leads", enabled=True)
    ctx = _client_ctx()
    try:
        out = app._admin_tool_run_saved_query(name="g_secret")
        blob = repr(out).lower()
        assert "encrypted_config" not in blob and "://" not in blob
    finally:
        ctx.pop()
        _cleanup_skill("g_secret")


# --- registry ----------------------------------------------------------------

def test_phase1_tool_registered():
    assert "admin_list_connections" in app.ADMIN_TOOL_FUNCTIONS
    names = {t["function"]["name"] for t in app.ADMIN_TOOLS}
    assert "admin_list_connections" in names


def test_phase2_tools_registered():
    assert "admin_add_widget" in app.ADMIN_TOOL_FUNCTIONS
    names = {t["function"]["name"] for t in app.ADMIN_TOOLS}
    assert "admin_add_widget" in names


def test_phase3_tools_registered():
    for t in ("admin_run_saved_query", "admin_list_saved_queries"):
        assert t in app.ADMIN_TOOL_FUNCTIONS
    names = {t["function"]["name"] for t in app.ADMIN_TOOLS}
    assert {"admin_run_saved_query", "admin_list_saved_queries"} <= names


# =============================================================================
# Phase 4 — super-admin grant-management routes
# =============================================================================

def _super_client():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    return c


def test_grant_routes_require_super_admin():
    """The grant CRUD is super-admin-only (a client gets 403 on every verb)."""
    if not CLIENT_PW:
        return
    c = app.app.test_client()
    c.post("/admin/login", data={"password": CLIENT_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    assert c.get("/admin/api/datahub/grants").status_code == 403
    assert c.post("/admin/api/datahub/grants",
                  json={"connection_id": 0, "table_name": "leads"},
                  headers={"X-CSRF-Token": "t"}).status_code == 403
    assert c.delete("/admin/api/datahub/grants/1",
                    headers={"X-CSRF-Token": "t"}).status_code == 403
    assert c.get("/admin/api/datahub/0/grantable-tables").status_code == 403


def test_grant_route_crud_roundtrip_super_admin():
    _clear_grants()
    c = _super_client()
    try:
        # add
        r = c.post("/admin/api/datahub/grants",
                   json={"connection_id": 0, "table_name": "Leads", "note": "ok"},
                   headers={"X-CSRF-Token": "t"})
        assert r.status_code == 201, r.get_data(as_text=True)
        gid = r.get_json()["id"]
        assert r.get_json()["table_name"] == "leads"   # normalized lowercase
        # list
        lst = c.get("/admin/api/datahub/grants").get_json()
        assert any(g["id"] == gid and g["table_name"] == "leads"
                   for g in lst["grants"])
        # the grant is live for a normal admin
        ctx = _client_ctx()
        try:
            assert app._dh_allowed_tables(0) == {"leads"}
        finally:
            ctx.pop()
        # remove
        assert c.delete("/admin/api/datahub/grants/" + str(gid),
                        headers={"X-CSRF-Token": "t"}).status_code == 200
        lst2 = c.get("/admin/api/datahub/grants").get_json()
        assert not any(g["id"] == gid for g in lst2["grants"])
    finally:
        _clear_grants()


def test_grantable_tables_route_flags_granted():
    _clear_grants()
    c = _super_client()
    try:
        c.post("/admin/api/datahub/grants",
               json={"connection_id": 0, "table_name": "leads"},
               headers={"X-CSRF-Token": "t"})
        j = c.get("/admin/api/datahub/0/grantable-tables").get_json()
        assert j["connection_id"] == 0 and j["all_granted"] is False
        by_name = {t["table"]: t["granted"] for t in j["tables"]}
        assert by_name.get("leads") is True
        assert by_name.get("orders") is False
        # no credential/url leakage in the picker payload
        blob = repr(j).lower()
        assert "encrypted_config" not in blob and "://" not in blob
    finally:
        _clear_grants()


def test_grant_star_then_grantable_shows_all_granted():
    _clear_grants()
    c = _super_client()
    try:
        c.post("/admin/api/datahub/grants",
               json={"connection_id": 0, "table_name": "*"},
               headers={"X-CSRF-Token": "t"})
        j = c.get("/admin/api/datahub/0/grantable-tables").get_json()
        assert j["all_granted"] is True
        assert all(t["granted"] for t in j["tables"])   # '*' covers everything
    finally:
        _clear_grants()
