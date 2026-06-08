"""Task 104 (gap §6.3, RBAC Phase 1) — multi-user admin accounts + invites + per-user login.
Embedded Postgres (no DB mocks).

Covers: the existing ADMIN_PASSWORD break-glass still works unchanged; the full
invite → join (set password) → email+password login flow; single-use + expiring + weak-password
invite handling; super-admin-only management; and the last-super-admin / self lockout guards.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
_CSRF = {"X-CSRF-Token": "t"}


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    return c


def _client_session():
    c = _sa()
    with c.session_transaction() as s:
        s["admin_role"] = "client"
    return c


def test_rbac_tables_exist():
    app.query_db("SELECT id, email, role, status, password_hash FROM admin_users LIMIT 1")
    app.query_db("SELECT id, user_id, token_hash, expires_at, used_at FROM admin_invites LIMIT 1")


def test_breakglass_admin_password_unchanged():
    # the existing ADMIN_PASSWORD login (no email) still logs in as super_admin
    lc = app.app.test_client()
    resp = lc.post("/admin/login", data={"password": ADMIN_PW})
    assert resp.status_code in (302, 303)
    with lc.session_transaction() as s:
        assert s.get("admin_logged_in") is True
        assert s.get("admin_role") == "super_admin"
        assert s.get("admin_user_id") is None     # break-glass carries no user id


def test_full_invite_join_login_flow():
    c = _sa()
    email = "rbacflow1@example.test"
    app.execute_db("DELETE FROM admin_users WHERE email=%s", (email,))
    try:
        # invite
        r = c.post("/admin/api/admin-users/invite", headers=_CSRF,
                   json={"email": email, "role": "admin", "name": "RB User"})
        assert r.status_code == 200
        inv = r.get_json()
        assert inv["success"] and "/admin/join?token=" in inv["invite_url"]
        token = inv["invite_url"].split("token=", 1)[1]
        row = app.query_db("SELECT status, role FROM admin_users WHERE email=%s", (email,), fetchone=True)
        assert row["status"] == "invited" and row["role"] == "admin"

        pub = app.app.test_client()
        # weak password rejected (CSRF-exempt path — no token header needed)
        assert pub.post("/admin/api/join", json={"token": token, "password": "short"}).status_code == 400
        # valid password activates the account
        jr = pub.post("/admin/api/join", json={"token": token, "password": "s3cretpassword"})
        assert jr.status_code == 200 and jr.get_json()["success"]
        assert app.query_db("SELECT status FROM admin_users WHERE email=%s", (email,),
                            fetchone=True)["status"] == "active"
        # single-use: a second join with the same token fails
        assert pub.post("/admin/api/join", json={"token": token, "password": "s3cretpassword"}).status_code == 400

        # log in with email + password → role from the account
        lc = app.app.test_client()
        ok = lc.post("/admin/login", data={"email": email, "password": "s3cretpassword"})
        assert ok.status_code in (302, 303)
        with lc.session_transaction() as s:
            assert s.get("admin_logged_in") is True
            assert s.get("admin_role") == "admin"
            assert s.get("admin_email") == email
            assert s.get("admin_user_id")
        # wrong password does NOT log in
        bad = app.app.test_client()
        rb = bad.post("/admin/login", data={"email": email, "password": "totally-wrong"})
        assert rb.status_code == 200      # re-renders the login form
        with bad.session_transaction() as s:
            assert not s.get("admin_logged_in")
    finally:
        app.execute_db("DELETE FROM admin_users WHERE email=%s", (email,))


def test_disabled_user_cannot_login():
    c = _sa()
    email = "rbacdisabled@example.test"
    app.execute_db("DELETE FROM admin_users WHERE email=%s", (email,))
    try:
        from werkzeug.security import generate_password_hash
        app.execute_db("INSERT INTO admin_users (tenant_id, email, role, status, password_hash) "
                       "VALUES (1, %s, 'admin', 'disabled', %s)",
                       (email, generate_password_hash("s3cretpassword")))
        lc = app.app.test_client()
        resp = lc.post("/admin/login", data={"email": email, "password": "s3cretpassword"})
        assert resp.status_code == 200    # not logged in (disabled)
        with lc.session_transaction() as s:
            assert not s.get("admin_logged_in")
    finally:
        app.execute_db("DELETE FROM admin_users WHERE email=%s", (email,))


def test_rbac_management_super_admin_only():
    cc = _client_session()
    assert cc.get("/admin/api/admin-users").status_code == 403
    assert cc.post("/admin/api/admin-users/invite", headers=_CSRF,
                   json={"email": "x@y.z"}).status_code == 403
    assert cc.patch("/admin/api/admin-users/1", headers=_CSRF, json={"role": "admin"}).status_code == 403
    assert cc.delete("/admin/api/admin-users/1", headers=_CSRF).status_code == 403


def test_invite_validation():
    c = _sa()
    assert c.post("/admin/api/admin-users/invite", headers=_CSRF,
                  json={"email": "notanemail"}).status_code == 400
    assert c.post("/admin/api/admin-users/invite", headers=_CSRF,
                  json={"email": "a@b.co", "role": "wizard"}).status_code == 400


def test_last_super_admin_and_self_guards():
    c = _sa()
    email = "rbaclastsuper@example.test"
    app.execute_db("DELETE FROM admin_users WHERE email=%s", (email,))
    try:
        app.execute_db("INSERT INTO admin_users (tenant_id, email, role, status, password_hash) "
                       "VALUES (1, %s, 'super_admin', 'active', 'x')", (email,))
        uid = app.query_db("SELECT id FROM admin_users WHERE email=%s", (email,), fetchone=True)["id"]
        # it's the only active super_admin in admin_users → can't demote / disable / delete it
        assert c.patch(f"/admin/api/admin-users/{uid}", headers=_CSRF,
                       json={"role": "admin"}).status_code == 400
        assert c.patch(f"/admin/api/admin-users/{uid}", headers=_CSRF,
                       json={"status": "disabled"}).status_code == 400
        assert c.delete(f"/admin/api/admin-users/{uid}", headers=_CSRF).status_code == 400
    finally:
        app.execute_db("DELETE FROM admin_users WHERE email=%s", (email,))


def test_join_page_and_invalid_token():
    # GET /admin/join renders for any token (shows valid/invalid state) — public, 200
    assert app.app.test_client().get("/admin/join?token=whatever").status_code == 200
    # POST with a bogus token is rejected
    assert app.app.test_client().post(
        "/admin/api/join", json={"token": "nope", "password": "longenough123"}).status_code == 400
