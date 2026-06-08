"""Task 100 (gap §2.5) — Subscribers Lists view + opt-in KPIs. Embedded Postgres (no mocks)."""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    return c


def test_subscriber_lists_shape_and_rates():
    c = _sa()
    app.execute_db("INSERT INTO subscribers (email, list_name, opt_in_email, opt_in_sms) "
                   "VALUES ('sl1@x.co','sltest',TRUE,FALSE)")
    app.execute_db("INSERT INTO subscribers (email, list_name, opt_in_email, opt_in_sms, unsubscribed_at) "
                   "VALUES ('sl2@x.co','sltest',FALSE,TRUE,NOW())")
    try:
        j = c.get("/admin/api/subscriber-lists").get_json()
        assert "lists" in j and "kpis" in j
        vip = next((L for L in j["lists"] if L["name"] == "sltest"), None)
        assert vip and vip["total"] >= 2
        # one of two opted into email / sms / unsubscribed → rates are present + sane
        for key in ("email_pct", "sms_pct", "unsub_pct"):
            assert key in vip and 0.0 <= vip[key] <= 100.0
        assert j["kpis"]["total"] >= 2
    finally:
        app.execute_db("DELETE FROM subscribers WHERE email IN ('sl1@x.co','sl2@x.co')")
