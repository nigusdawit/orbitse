"""Regression tests for the super-admin / client two-role admin (task 024).

Pins the privilege boundary so a future change can't quietly let a client
re-grant itself tabs or let the super-admin flag-bypass leak to anonymous
traffic. Runs against a real (embedded) Postgres — the harness sets
ADMIN_PASSWORD / CLIENT_PASSWORD / SSO_SIGNING_SECRET before importing app, so
the role machinery is exercised end-to-end.
"""
import base64
import hashlib
import hmac
import json
import os
import time
import secrets as _secrets

import app  # importing also exercises the startup assertion (test_registry_prefixes_all_known)

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _login(client, password):
    return client.post("/admin/login", data={"password": password})


def _mint_sso(tid=1):
    secret = os.environ["SSO_SIGNING_SECRET"]
    payload = {"tid": tid, "exp": int(time.time()) + 45, "jti": _secrets.token_hex(16)}
    b64 = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), b64.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return b64 + "." + sig


# 1 -------------------------------------------------------------------------
def test_super_admin_can_list_features():
    c = app.app.test_client()
    assert _login(c, ADMIN_PW).status_code in (200, 302)
    r = c.get("/admin/api/tenant/features")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert "features" in r.get_json()


# 2 -------------------------------------------------------------------------
def test_client_cannot_list_or_toggle_features():
    c = app.app.test_client()
    assert _login(c, CLIENT_PW).status_code in (200, 302)
    g = c.get("/admin/api/tenant/features")
    assert g.status_code == 403
    assert g.get_json().get("error") == "super_admin_role_required"
    # PATCH with a valid CSRF token is STILL rejected — the role is the boundary.
    with c.session_transaction() as s:
        s["_csrf_token"] = "tok"
    p = c.patch("/admin/api/tenant/features/events",
                json={"enabled": False}, headers={"X-CSRF-Token": "tok"})
    assert p.status_code == 403
    assert p.get_json().get("error") == "super_admin_role_required"


# 3 -------------------------------------------------------------------------
def test_super_admin_bypasses_flag_while_client_is_gated():
    app.set_tenant_feature("events", False, tenant_id=1)
    app.invalidate_tenant_features_cache(1)
    try:
        cc = app.app.test_client(); _login(cc, CLIENT_PW)
        rc = cc.get("/admin/api/events")
        assert rc.status_code == 403
        assert rc.get_json().get("error") == "feature_disabled"

        sc = app.app.test_client(); _login(sc, ADMIN_PW)
        rs = sc.get("/admin/api/events")
        body = rs.get_json(silent=True) or {}
        assert not (rs.status_code == 403 and body.get("error") == "feature_disabled"), \
            "super admin must bypass the events flag"
    finally:
        app.set_tenant_feature("events", True, tenant_id=1)
        app.invalidate_tenant_features_cache(1)


# 4 — the review's R2: the super-admin bypass must NOT leak to anonymous traffic
def test_anonymous_is_not_super_admin_and_stays_gated():
    with app.app.test_request_context("/"):
        assert app._is_super_admin() is False
    app.set_tenant_feature("voice", False, tenant_id=1)
    app.invalidate_tenant_features_cache(1)
    try:
        ac = app.app.test_client()
        r = ac.get("/api/voice/voices")        # gated prefix /api/voice/
        assert r.status_code in (403, 404), \
            "anonymous request to a disabled public feature must still be gated"
    finally:
        app.set_tenant_feature("voice", True, tenant_id=1)
        app.invalidate_tenant_features_cache(1)


# 5 -------------------------------------------------------------------------
def test_sso_establishes_client_role():
    c = app.app.test_client()
    r = c.get("/admin/sso?token=" + _mint_sso(1))
    assert r.status_code in (301, 302)
    # Client role → the feature-control endpoint is forbidden.
    g = c.get("/admin/api/tenant/features")
    assert g.status_code == 403


# 6 -------------------------------------------------------------------------
def test_registry_prefixes_all_known():
    unknown = {f for _p, f in app._FEATURE_ROUTE_PREFIXES if f not in app._FEATURE_NAMES}
    assert not unknown, f"route-prefix features missing from registry: {unknown}"
