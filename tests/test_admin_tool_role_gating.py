"""Follow-up to the Phase-8 security review — extend the super-admin AI-tool
boundary to the Datahub tools and the pending-action APPROVE endpoint.

The admin chat is only @admin_required, and WordPress-SSO logins are the lower-
trust 'client' role. Tools/endpoints that mirror super-admin-only surfaces must
self-gate so a client can't reach them through the assistant.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def test_datahub_write_tools_block_client_role():
    """AI-driven Datahub semantic-layer + SQL-skill WRITES stay super-admin-only.

    NOTE (task 085): admin_create_dashboard is NO LONGER blanket super-admin —
    it was relaxed so a normal admin can save a chart built from its GRANTED
    data, with per-widget grant validation (see tests/test_datahub_grants.py).
    define_schema (drafts the data dictionary) and save_query (creates a SQL
    skill that later runs with DB access) remain super-admin-only."""
    with app.app.test_request_context("/"):
        from flask import session as s
        s["admin_logged_in"] = True
        s["admin_role"] = "client"
        for fn, kw in (
            (app._admin_tool_define_schema, {"connection_id": 0}),
            (app._admin_tool_save_query, {"name": "q1", "sql": "SELECT 1"}),
        ):
            out = fn(**kw)
            assert "super-admin" in (out.get("error") or ""), f"{fn.__name__} not gated"
        # a super-admin session is NOT blocked by the role guard
        s["admin_role"] = "super_admin"
        out = app._admin_tool_define_schema(connection_id=0)
        assert "super-admin" not in (out.get("error") or "")


def test_external_connection_reads_bounded_by_grants_for_client():
    """Task 085 inverted the Datahub read boundary to default-DENY per-table
    grants. A normal admin no longer gets a "super-admin only" refusal — instead
    inspect/query are BOUNDED by datahub_table_grants (cid 0 included). With no
    grants the overview is empty and a specific-table inspect/query is refused
    with the friendly "ask your administrator" message (NOT the role-guard
    string). See tests/test_datahub_grants.py for the full grant matrix."""
    app.execute_db("DELETE FROM datahub_table_grants")
    with app.app.test_request_context("/"):
        from flask import session as s
        s["admin_logged_in"] = True
        s["admin_role"] = "client"
        # No grants → app-DB overview is empty (deny-all), not a role refusal.
        ov = app._admin_tool_inspect_connection(connection_id=0)
        assert ov.get("tables") == []
        assert "super-admin" not in (ov.get("error") or "")
        # A specific ungranted table → the friendly grant refusal.
        ins = app._admin_tool_inspect_connection(connection_id=0, table="leads")
        assert "don't have access" in (ins.get("error") or "")
        q = app._admin_tool_query_connection(connection_id=0, sql="SELECT 1 AS one FROM leads")
        assert (q.get("error") or "")   # refused (no grant on leads)
        assert "super-admin" not in (q.get("error") or "")


def test_datahub_tools_allowed_outside_request_context():
    """System/automation/test callers (no request context) are trusted — the
    guard must not block direct calls (so existing Datahub tests still work)."""
    out = app._admin_tool_define_schema(connection_id=0)
    assert "super-admin" not in (out.get("error") or "")


def test_approve_endpoint_requires_super_admin():
    if not CLIENT_PW:
        return
    # client → 403 (cannot execute a queued write)
    c = app.app.test_client()
    c.post("/admin/login", data={"password": CLIENT_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    r = c.post("/admin/api/chat/action/123456/approve", headers={"X-CSRF-Token": "t"})
    assert r.status_code == 403
    # super-admin → NOT 403 (action doesn't exist, so 404/409 — but past the gate)
    a = app.app.test_client()
    a.post("/admin/login", data={"password": ADMIN_PW})
    with a.session_transaction() as s:
        s["_csrf_token"] = "t"
    r2 = a.post("/admin/api/chat/action/123456/approve", headers={"X-CSRF-Token": "t"})
    assert r2.status_code != 403


def test_external_connections_routes_require_super_admin():
    """External DB connections are a super-admin domain (consumed by the
    super-admin-only Datahub tab)."""
    if not CLIENT_PW:
        return
    c = app.app.test_client()
    c.post("/admin/login", data={"password": CLIENT_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    assert c.get("/admin/api/external-connections").status_code == 403
    assert c.post("/admin/api/external-connections",
                  json={"name": "x", "kind": "postgres", "config": "postgres://h/db"},
                  headers={"X-CSRF-Token": "t"}).status_code == 403
    assert c.delete("/admin/api/external-connections/1",
                    headers={"X-CSRF-Token": "t"}).status_code == 403
    assert c.post("/admin/api/external-connections/1/test",
                  headers={"X-CSRF-Token": "t"}).status_code == 403
    # super-admin passes the gate (empty list is fine)
    a = app.app.test_client()
    a.post("/admin/login", data={"password": ADMIN_PW})
    assert a.get("/admin/api/external-connections").status_code == 200


def test_ungated_read_tool_no_role_guard_for_client():
    """admin_run_sql has no super-admin ROLE guard (its boundary is sqlguard +,
    now, the task-085 per-table grant check). A literal `SELECT 1` references NO
    table, so the grant check finds nothing to deny — a client session runs it.
    (A query that DID touch an ungranted table would be refused with the
    'ask your administrator' message — covered in test_datahub_grants.py.)"""
    app.execute_db("DELETE FROM datahub_table_grants")
    with app.app.test_request_context("/"):
        from flask import session as s
        s["admin_logged_in"] = True
        s["admin_role"] = "client"
        out = app._admin_tool_run_sql(sql="SELECT 1 AS one")
        # No role-guard refusal AND no grant refusal (no table referenced).
        assert "super-admin" not in (out.get("error") or "")
        assert "don't have access" not in (out.get("error") or "")
        assert out.get("row_count") == 1 or out.get("rows")
