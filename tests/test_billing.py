"""Task 103 (gap §6.2) — platform Billing. Embedded Postgres (no DB mocks).

The Billing view shows the tenant's subscription to THIS platform. It must build + run
WITHOUT a Stripe key (the operator adds PLATFORM_STRIPE_SECRET_KEY later) and degrade to a
clear 'not configured' state — never a 500. Stripe is an EXTERNAL HTTP API, not the DB, so
the live path is exercised by monkeypatching the stripe module (the no-mocks rule is about
the database, which here is real embedded Postgres). All three routes are super-admin only.
"""
import os

import app
import admin.tenancy as tenancy

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")

# Admin POSTs need the CSRF header; _sa() seeds the session token to "t".
_CSRF = {"X-CSRF-Token": "t"}


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    return c


def _client_session():
    # a logged-in but NON-super (client) session — role lives server-side in the session
    c = _sa()
    with c.session_transaction() as s:
        s["admin_role"] = "client"
    return c


def test_billing_columns_exist():
    # migration 0039 added these (SELECT errors if the columns are missing)
    app.query_db("SELECT stripe_customer_id, stripe_subscription_id FROM tenants LIMIT 1")
    app.query_db("SELECT price_display FROM plans LIMIT 1")


def test_billing_not_configured_returns_plan_no_crash():
    os.environ.pop("PLATFORM_STRIPE_SECRET_KEY", None)
    app.execute_db("UPDATE tenants SET stripe_customer_id='', stripe_subscription_id=''")
    j = _sa().get("/admin/api/billing").get_json()
    assert j["configured"] is False
    assert j["linked"] is False
    assert j["subscription"] is None and j["invoices"] == []
    assert j["portal_available"] is False
    assert "plan" in j and "name" in j["plan"]          # plan always present, straight from the DB


def test_billing_super_admin_only():
    cc = _client_session()
    assert cc.get("/admin/api/billing").status_code == 403
    assert cc.post("/admin/api/billing/portal", headers=_CSRF, json={}).status_code == 403
    assert cc.post("/admin/api/billing/link", headers=_CSRF,
                   json={"stripe_customer_id": "cus_x"}).status_code == 403


def test_billing_link_roundtrip_and_validation():
    c = _sa()
    try:
        # bad prefix → 400, no write
        assert c.post("/admin/api/billing/link", headers=_CSRF,
                      json={"stripe_customer_id": "nope"}).status_code == 400
        # good link → success; GET reflects it
        r = c.post("/admin/api/billing/link", headers=_CSRF,
                   json={"stripe_customer_id": "cus_test103", "stripe_subscription_id": "sub_test103"})
        assert r.status_code == 200 and r.get_json().get("success") is True
        j = c.get("/admin/api/billing").get_json()
        assert j["linked"] is True
        assert j["link"]["customer_id"] == "cus_test103"
        assert j["link"]["subscription_id"] == "sub_test103"
    finally:
        app.execute_db("UPDATE tenants SET stripe_customer_id='', stripe_subscription_id='' "
                       "WHERE stripe_customer_id='cus_test103'")


def test_billing_portal_not_configured_is_400_not_500():
    os.environ.pop("PLATFORM_STRIPE_SECRET_KEY", None)
    r = _sa().post("/admin/api/billing/portal", headers=_CSRF, json={})
    assert r.status_code == 400
    assert r.get_json().get("error") == "not_configured"


# --- live path via monkeypatched stripe (external API boundary, not the DB) -----------

class _FakeSub:
    @staticmethod
    def retrieve(sid, api_key=None, expand=None):
        return {"status": "active", "current_period_end": 1700000000, "cancel_at_period_end": False,
                "items": {"data": [{"price": {"unit_amount": 9900, "currency": "usd",
                                              "recurring": {"interval": "month"}}}]}}


class _FakeInv:
    @staticmethod
    def list(customer=None, limit=None, api_key=None):
        return {"data": [{"number": "INV-103", "created": 1699000000, "amount_paid": 9900,
                          "currency": "usd", "status": "paid", "hosted_invoice_url": "https://stripe.test/i"}]}


class _FakePortalSession:
    @staticmethod
    def create(customer=None, return_url=None, api_key=None):
        return {"url": "https://billing.stripe.com/p/session_test"}


class _FakeStripe:
    Subscription = _FakeSub
    Invoice = _FakeInv

    class billing_portal:
        Session = _FakePortalSession


def test_billing_live_path_with_fake_stripe():
    c = _sa()
    orig = tenancy._stripe
    os.environ["PLATFORM_STRIPE_SECRET_KEY"] = "sk_test_fake103"
    tenancy._stripe = _FakeStripe()
    try:
        c.post("/admin/api/billing/link", headers=_CSRF,
               json={"stripe_customer_id": "cus_live103", "stripe_subscription_id": "sub_live103"})
        j = c.get("/admin/api/billing").get_json()
        assert j["configured"] is True and j["linked"] is True
        assert j["subscription"]["status"] == "active"
        assert j["subscription"]["amount"] == 9900
        assert j["subscription"]["interval"] == "month"
        assert len(j["invoices"]) == 1 and j["invoices"][0]["status"] == "paid"
        assert j["portal_available"] is True
        pr = c.post("/admin/api/billing/portal", headers=_CSRF, json={})
        assert pr.status_code == 200
        assert pr.get_json()["url"].startswith("https://billing.stripe.com/")
    finally:
        tenancy._stripe = orig
        os.environ.pop("PLATFORM_STRIPE_SECRET_KEY", None)
        app.execute_db("UPDATE tenants SET stripe_customer_id='', stripe_subscription_id='' "
                       "WHERE stripe_customer_id='cus_live103'")
