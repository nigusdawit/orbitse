"""Task 067 — Publish capabilities + auto-post. Embedded Postgres.

Network (HTTP) and MCP are stubbed; the python path runs a REAL subprocess to
prove shell=False + the deployment env gate. SSRF rejection is tested against a
literal loopback IP (no DNS/network). Covers CRUD + redaction (no secret leak),
the four dispatchers, the autopublish gate, the audit log, routes, and 403s.
"""
import json
import os
import sys

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _mk_cap(kind, cfg, *, enabled=True, name="cap"):
    return app.execute_db(
        "INSERT INTO publish_capabilities (tenant_id, name, kind, "
        "encrypted_config, enabled) VALUES (1,%s,%s,%s,%s) RETURNING id",
        (name, kind, app.encrypt_secret(json.dumps(cfg)), enabled))["id"]


def _seed_draft(title="A Post", body="Body text."):
    return app.execute_db(
        "INSERT INTO content_drafts (tenant_id, content_type, title, body, status) "
        "VALUES (1,'blog',%s,%s,'approved') RETURNING id", (title, body))["id"]


def _wipe():
    for t in ("publish_log", "content_drafts", "publish_capabilities"):
        app.execute_db(f"DELETE FROM {t} WHERE tenant_id=1")


def _reset():
    for k in ("autopublish_enabled", "ai_enhancements_enabled"):
        app.reset_ai_setting(k)
    app._invalidate_ai_control()


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    return c


# ---- schema -----------------------------------------------------------------

def test_schema_exists():
    app.query_db("SELECT COUNT(*) AS n FROM publish_log", fetchone=True)
    app.query_db("SELECT COUNT(*) AS n FROM publish_capabilities", fetchone=True)


# ---- CRUD + redaction -------------------------------------------------------

def test_create_capability_no_secret_leak():
    _wipe()
    try:
        out = app._rce_create_capability("MCP cap", "mcp",
                                         {"server_id": 5, "tool": "post_status"})
        assert "encrypted_config" not in out
        assert out["config_summary"]["tool"] == "post_status"
        # webhook headers must never appear in a redacted view
        cid = _mk_cap("webhook", {"url": "https://hooks.example/x",
                                  "headers": {"Authorization": "SECRET123"}})
        row = app.query_db("SELECT * FROM publish_capabilities WHERE id=%s",
                           (cid,), fetchone=True)
        red = app._rce_cap_redacted(row)
        assert "SECRET123" not in json.dumps(red)
        assert red["config_summary"]["has_headers"] is True
        assert red["config_summary"]["host"] == "hooks.example"
    finally:
        _wipe()


def test_create_rejects_ssrf():
    # literal loopback IP → rejected without any network/DNS
    out = app._rce_create_capability("bad", "webhook", {"url": "http://127.0.0.1/x"})
    assert "error" in out


def test_create_python_validates_command():
    bad = app._rce_create_capability("py", "python", {"command": "not-a-list"})
    assert "error" in bad
    good = app._rce_create_capability("py", "python",
                                      {"command": ["echo", "hi"]})
    assert good.get("kind") == "python" and good["config_summary"]["argc"] == 2
    _wipe()


def test_update_and_delete():
    _wipe()
    try:
        cid = _mk_cap("webhook", {"url": "https://hooks.example/x"}, enabled=False)
        upd = app._rce_update_capability(cid, enabled=True, description="now on")
        assert upd["enabled"] is True and upd["description"] == "now on"
        app.execute_db("DELETE FROM publish_capabilities WHERE id=%s", (cid,))
        assert not app.query_db("SELECT 1 FROM publish_capabilities WHERE id=%s",
                                (cid,), fetchone=True)
    finally:
        _wipe()


# ---- publish flow (HTTP stubbed) -------------------------------------------

def test_publish_webhook_logs_and_marks_published(monkeypatch):
    _wipe()
    monkeypatch.setattr(app, "_rce_safe_http_send",
                        lambda *a, **k: {"ok": True, "status": 200, "detail": "posted"})
    app.set_ai_setting("autopublish_enabled", True)
    app._invalidate_ai_control()
    try:
        cid = _mk_cap("webhook", {"url": "https://hooks.example/x"}, enabled=True)
        did = _seed_draft()
        out = app._rce_publish_draft(did, cid, via="auto")
        assert out["ok"] is True
        d = app.query_db("SELECT status, target_id FROM content_drafts WHERE id=%s",
                         (did,), fetchone=True)
        assert d["status"] == "published" and d["target_id"] == cid
        log = app.query_db("SELECT status FROM publish_log WHERE draft_id=%s",
                           (did,), fetchone=True)
        assert log["status"] == "ok"
    finally:
        _wipe(); _reset()


def test_publish_disabled_capability_refused():
    _wipe()
    try:
        cid = _mk_cap("webhook", {"url": "https://hooks.example/x"}, enabled=False)
        did = _seed_draft()
        assert "error" in app._rce_publish_draft(did, cid, via="manual")
    finally:
        _wipe()


def test_autopublish_gate_blocks_auto():
    _wipe(); _reset()   # autopublish off
    try:
        cid = _mk_cap("webhook", {"url": "https://hooks.example/x"}, enabled=True)
        did = _seed_draft()
        assert "error" in app._rce_publish_draft(did, cid, via="auto")
    finally:
        _wipe()


# ---- python dispatcher (REAL subprocess) -----------------------------------

def test_python_requires_deployment_env(monkeypatch):
    monkeypatch.delenv("RCE_PYTHON_CAPABILITY_ENABLED", raising=False)
    res = app._rce_dispatch_python({"command": [sys.executable, "-c", "print(1)"]}, {})
    assert res["ok"] is False and "disabled" in res["detail"]


def test_python_runs_with_env_and_no_shell_injection(monkeypatch):
    _wipe()
    monkeypatch.setenv("RCE_PYTHON_CAPABILITY_ENABLED", "1")
    try:
        # command echoes a fixed token; the (malicious) payload goes to stdin and
        # must NOT be interpreted as a shell command.
        cmd = [sys.executable, "-c",
               "import sys; d=sys.stdin.read(); print('SAFE', len(d))"]
        cid = _mk_cap("python", {"command": cmd, "pass_as": "stdin"}, enabled=True)
        did = _seed_draft(title="; rm -rf / #", body="$(whoami)")
        out = app._rce_publish_draft(did, cid, via="manual")
        assert out["ok"] is True and "SAFE" in out["detail"]
    finally:
        _wipe()


def test_python_command_must_be_list(monkeypatch):
    monkeypatch.setenv("RCE_PYTHON_CAPABILITY_ENABLED", "1")
    res = app._rce_dispatch_python({"command": "rm -rf /"}, {})
    assert res["ok"] is False


# ---- mcp dispatcher (no server row needed) ---------------------------------

def test_mcp_needs_config_and_handles_missing_server():
    assert app._rce_dispatch_mcp({}, {})["ok"] is False
    miss = app._rce_dispatch_mcp({"server_id": 999999, "tool": "x"}, {})
    assert miss["ok"] is False and "not found" in miss["detail"]


# ---- routes -----------------------------------------------------------------

def test_capability_routes(monkeypatch):
    _wipe()
    try:
        c = _sa()
        r = c.post("/admin/api/publish/capabilities",
                   json={"name": "Py", "kind": "python",
                         "config": {"command": ["echo", "hi"]}},
                   headers={"X-CSRF-Token": "t"})
        assert r.status_code == 200
        cid = r.get_json()["id"]
        lst = c.get("/admin/api/publish/capabilities").get_json()
        assert any(x["id"] == cid for x in lst["capabilities"])
        assert "python_allowed" in lst
        one = c.get(f"/admin/api/publish/capabilities/{cid}").get_json()
        assert one["kind"] == "python"
        upd = c.post(f"/admin/api/publish/capabilities/{cid}",
                     json={"enabled": True}, headers={"X-CSRF-Token": "t"})
        assert upd.get_json()["enabled"] is True
        d = c.delete(f"/admin/api/publish/capabilities/{cid}",
                     headers={"X-CSRF-Token": "t"})
        assert d.status_code == 200
        # bad create → 400
        assert c.post("/admin/api/publish/capabilities",
                      json={"name": "x", "kind": "nope", "config": {}},
                      headers={"X-CSRF-Token": "t"}).status_code == 400
    finally:
        _wipe()


def test_publish_and_log_routes(monkeypatch):
    _wipe()
    monkeypatch.setattr(app, "_rce_safe_http_send",
                        lambda *a, **k: {"ok": True, "status": 200, "detail": "posted"})
    try:
        cid = _mk_cap("webhook", {"url": "https://hooks.example/x"}, enabled=True)
        did = _seed_draft()
        c = _sa()
        r = c.post(f"/admin/api/content/drafts/{did}/publish",
                   json={"capability_id": cid}, headers={"X-CSRF-Token": "t"})
        assert r.status_code == 200 and r.get_json()["ok"] is True
        log = c.get("/admin/api/publish/log").get_json()["log"]
        assert any(e["draft_id"] == did for e in log)
        # missing capability_id → 400
        assert c.post(f"/admin/api/content/drafts/{did}/publish", json={},
                      headers={"X-CSRF-Token": "t"}).status_code == 400
    finally:
        _wipe()


def test_routes_client_blocked():
    if not CLIENT_PW:
        return
    c = app.app.test_client()
    c.post("/admin/login", data={"password": CLIENT_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    assert c.get("/admin/api/publish/capabilities").status_code == 403
    assert c.post("/admin/api/publish/capabilities", json={"name": "x", "kind": "webhook",
                  "config": {}}, headers={"X-CSRF-Token": "t"}).status_code == 403
    assert c.get("/admin/api/publish/log").status_code == 403


# ---- tool -------------------------------------------------------------------

def test_tool_registered_and_gated():
    assert "publish_content" in app.ADMIN_TOOL_FUNCTIONS
    names = {t["function"]["name"] for t in app.ADMIN_TOOLS}
    assert "publish_content" in names
    _reset()  # autopublish off → the AI tool must refuse
    out = app._admin_tool_publish_content(draft_id=1, capability_id=1)
    assert "error" in out


def test_ai_tools_block_client_role():
    """SECURITY: a client-role session must NOT be able to fire the super-admin-
    only Research/Content AI tools (the admin chat is only @admin_required)."""
    with app.app.test_request_context("/"):
        from flask import session as _sess
        _sess["admin_logged_in"] = True
        _sess["admin_role"] = "client"
        for fn, kw in (
            (app._admin_tool_publish_content, {"draft_id": 1, "capability_id": 1}),
            (app._admin_tool_gather_sources, {"urls": ["https://a.com"]}),
            (app._admin_tool_run_research, {"question": "q"}),
            (app._admin_tool_generate_content, {"report_id": 1, "content_types": ["blog"]}),
            (app._admin_tool_generate_visual, {"draft_id": 1, "asset_type": "image"}),
        ):
            out = fn(**kw)
            assert "super-admin" in (out.get("error") or ""), f"{fn.__name__} not gated"
        # a super-admin session in the same context is NOT blocked by the role guard
        _sess["admin_role"] = "super_admin"
        out = app._admin_tool_gather_sources(urls=["https://a.com"])
        assert "super-admin" not in (out.get("error") or "")
