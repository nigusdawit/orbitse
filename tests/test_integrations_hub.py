"""Task 098 (gap §6.1) — Integrations hub. Embedded Postgres (no mocks).

The /admin/api/integrations endpoint aggregates each integration's configured/missing
state from the loaded env + the mcp_servers table; super-admin only.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    return c


def test_integrations_grid_shape():
    c = _sa()
    j = c.get("/admin/api/integrations").get_json()
    items = j["integrations"]
    keys = {i["key"] for i in items}
    assert {"anthropic", "openai", "stripe", "twilio", "resend", "mcp"} <= keys
    for i in items:
        assert i.get("label") and i.get("category") is not None
        assert isinstance(i["configured"], bool) and "hint" in i
    assert j["total"] == len(items) and 0 <= j["configured"] <= j["total"]


def test_integrations_reflects_env():
    c = _sa()
    os.environ["STRIPE_SECRET_KEY"] = "sk_test_xyz"
    try:
        j = c.get("/admin/api/integrations").get_json()
        stripe = next(i for i in j["integrations"] if i["key"] == "stripe")
        assert stripe["configured"] is True
    finally:
        os.environ.pop("STRIPE_SECRET_KEY", None)
    stripe2 = next(i for i in c.get("/admin/api/integrations").get_json()["integrations"]
                   if i["key"] == "stripe")
    assert stripe2["configured"] is False


def test_integrations_super_gate():
    if not CLIENT_PW:
        return
    cc = app.app.test_client()
    cc.post("/admin/login", data={"password": CLIENT_PW})
    assert cc.get("/admin/api/integrations").status_code == 403
