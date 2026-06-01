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
    """AI-driven Datahub WRITES (semantic layer / SQL skill / dashboard) are
    super-admin-only, regardless of connection."""
    with app.app.test_request_context("/"):
        from flask import session as s
        s["admin_logged_in"] = True
        s["admin_role"] = "client"
        for fn, kw in (
            (app._admin_tool_define_schema, {"connection_id": 0}),
            (app._admin_tool_save_query, {"name": "q1", "sql": "SELECT 1"}),
            (app._admin_tool_create_dashboard, {"name": "D", "widgets": []}),
        ):
            out = fn(**kw)
            assert "super-admin" in (out.get("error") or ""), f"{fn.__name__} not gated"
        # a super-admin session is NOT blocked by the role guard
        s["admin_role"] = "super_admin"
        out = app._admin_tool_define_schema(connection_id=0)
        assert "super-admin" not in (out.get("error") or "")


def test_external_connection_reads_block_client_but_app_db_open():
    """Reading an EXTERNAL connection (cid != 0) is super-admin-only; the app's
    own DB (cid 0) stays open to the client business assistant — same boundary
    as the already-open admin_run_sql / admin_describe_table."""
    with app.app.test_request_context("/"):
        from flask import session as s
        s["admin_logged_in"] = True
        s["admin_role"] = "client"
        # external connection → blocked
        assert "super-admin" in (
            app._admin_tool_inspect_connection(connection_id=999).get("error") or "")
        assert "super-admin" in (
            app._admin_tool_query_connection(connection_id=999, sql="SELECT 1").get("error") or "")
        # app DB (cid 0) → NOT a role refusal
        assert "super-admin" not in (
            app._admin_tool_query_connection(connection_id=0, sql="SELECT 1 AS one").get("error") or "")
        assert "super-admin" not in (
            app._admin_tool_inspect_connection(connection_id=0).get("error") or "")


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


def test_ungated_read_tool_still_open_to_client():
    """Sanity: we did NOT broaden the gate to admin_run_sql (the established
    admin read-SQL boundary) — a client session still passes the role guard for
    it (its own sqlguard remains the boundary)."""
    with app.app.test_request_context("/"):
        from flask import session as s
        s["admin_logged_in"] = True
        s["admin_role"] = "client"
        out = app._admin_tool_run_sql(sql="SELECT 1 AS one")
        # whatever it returns, it must NOT be the role-guard refusal
        assert "super-admin" not in (out.get("error") or "")
