"""Task 100 (gap §2.6) — cross-form submissions inbox + convert-to-lead. Embedded PG (no mocks)."""
import json
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


def test_submissions_inbox_and_convert_to_lead():
    c = _sa()
    form = app.execute_db("INSERT INTO custom_forms (name, slug) VALUES ('Inbox Form','inbox-form-t') RETURNING id")
    fid = form["id"]
    sub = app.execute_db(
        "INSERT INTO form_submissions (form_id, submission_data) VALUES (%s, %s::jsonb) RETURNING id",
        (fid, json.dumps({"Full Name": "Inbox Lead", "Email": "inbox@x.co", "Phone": "+15551234567"})))
    sid = sub["id"]
    try:
        # cross-form inbox lists it with form name + preview
        j = c.get("/admin/api/submissions").get_json()
        row = next((x for x in j["submissions"] if x["id"] == sid), None)
        assert row and row["form_name"] == "Inbox Form" and row["preview"]
        # convert → lead
        r = c.post("/admin/api/submissions/%d/to-lead" % sid, headers=_CSRF, json={})
        assert r.status_code == 200
        lid = r.get_json()["lead_id"]
        assert lid
        lead = app.query_db("SELECT name, email, phone, source FROM leads WHERE id=%s", (lid,), fetchone=True)
        assert lead["email"] == "inbox@x.co" and lead["name"] == "Inbox Lead" and lead["source"] == "form"
        # submission marked converted
        st = app.query_db("SELECT status FROM form_submissions WHERE id=%s", (sid,), fetchone=True)
        assert st["status"] == "converted"
    finally:
        app.execute_db("DELETE FROM form_submissions WHERE id=%s", (sid,))
        app.execute_db("DELETE FROM leads WHERE email='inbox@x.co'")
        app.execute_db("DELETE FROM custom_forms WHERE id=%s", (fid,))
