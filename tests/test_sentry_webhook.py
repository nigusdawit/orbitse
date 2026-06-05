"""Task 092 P2 — Sentry webhook intake + super-admin read/triage API. Embedded Postgres.

The webhook (POST /api/sentry/webhook) is PUBLIC by nature, so these tests pin its
self-defense: HMAC signature required (bad/missing → 401), no-secret → 503, body
size-capped (→ 413), idempotent upsert on issue_id, and a verified non-issue
payload stored-nothing. Plus the read API is super-admin-gated and the status
toggle round-trips. Real DB (no mocks) so the ON CONFLICT upsert is exercised for real.
"""
import os
import json
import hmac
import hashlib

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
SECRET = "test-sentry-webhook-secret"

# Request-time read in the route, so setting it here (before any request) is enough.
os.environ["SENTRY_WEBHOOK_SECRET"] = SECRET


def _sa():
    """Super-admin test client (the default admin password is the super admin)."""
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    return c


def _sign(body_bytes, secret=SECRET):
    return hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()


def _issue_payload(issue_id, *, count=1, title="KeyError: foo", level="error",
                   permalink="https://sentry.io/org/proj/issues/1/"):
    """A modern Sentry Integration issue-alert shaped body (data.issue.*)."""
    return {
        "action": "triggered",
        "data": {"issue": {
            "id": str(issue_id),
            "title": title,
            "culprit": "app.views.do_thing",
            "level": level,
            "permalink": permalink,
            "count": count,
            "firstSeen": "2026-06-05T10:00:00Z",
            "lastSeen": "2026-06-05T12:00:00Z",
            "project": {"slug": "proj", "name": "Proj"},
        }},
    }


def _post(client, payload, *, sign=True, secret=SECRET, sig=None):
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if sig is not None:
        headers["Sentry-Hook-Signature"] = sig
    elif sign:
        headers["Sentry-Hook-Signature"] = _sign(body, secret)
    return client.post("/api/sentry/webhook", data=body, headers=headers)


def test_table_exists():
    # A SELECT proves migration 0034 ran (no error).
    app.query_db("SELECT id, issue_id, status, event_count, payload FROM sentry_alerts LIMIT 1")


def test_valid_signature_upserts_row():
    c = app.app.test_client()
    r = _post(c, _issue_payload("sig-ok-1", title="ValueError: boom"))
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j["ok"] is True and j["stored"] is True and j["id"]
    row = app.query_db("SELECT title, level, status, event_count FROM sentry_alerts "
                       "WHERE issue_id=%s", ("sig-ok-1",), fetchone=True)
    assert row is not None
    assert row["title"] == "ValueError: boom"
    assert row["status"] == "new"            # fresh issue starts as 'new'
    assert row["level"] == "error"


def test_missing_signature_rejected():
    c = app.app.test_client()
    r = _post(c, _issue_payload("nosig"), sign=False)
    assert r.status_code == 401
    # nothing stored (query_db returns [] for no rows)
    assert not app.query_db("SELECT id FROM sentry_alerts WHERE issue_id=%s", ("nosig",))


def test_bad_signature_rejected():
    c = app.app.test_client()
    r = _post(c, _issue_payload("badsig"), sig="deadbeef" * 8)
    assert r.status_code == 401
    assert not app.query_db("SELECT id FROM sentry_alerts WHERE issue_id=%s", ("badsig",))


def test_signature_over_tampered_body_rejected():
    # Sign one body, send a different one → mismatch → 401 (no replay/tamper).
    c = app.app.test_client()
    good = json.dumps(_issue_payload("tamper")).encode()
    sig = _sign(good)
    bad = json.dumps(_issue_payload("tamper", title="DIFFERENT")).encode()
    r = c.post("/api/sentry/webhook", data=bad,
               headers={"Content-Type": "application/json", "Sentry-Hook-Signature": sig})
    assert r.status_code == 401


def test_no_secret_configured_returns_503():
    c = app.app.test_client()
    saved = os.environ.pop("SENTRY_WEBHOOK_SECRET", None)
    try:
        r = _post(c, _issue_payload("nosecret"), secret="whatever")
        assert r.status_code == 503
    finally:
        if saved is not None:
            os.environ["SENTRY_WEBHOOK_SECRET"] = saved


def test_oversized_body_rejected_413():
    c = app.app.test_client()
    # >512KB body with a valid-format (but irrelevant) signature: the size guard
    # runs BEFORE signature verification, so this is 413 regardless.
    big = b"{\"junk\":\"" + (b"x" * (520 * 1024)) + b"\"}"
    r = c.post("/api/sentry/webhook", data=big,
               headers={"Content-Type": "application/json",
                        "Sentry-Hook-Signature": _sign(big)})
    assert r.status_code == 413


def test_verified_non_issue_payload_stored_nothing():
    # A correctly-signed body with no issue identifier (e.g. an install ping) is
    # acknowledged (200) but stores nothing.
    c = app.app.test_client()
    r = _post(c, {"action": "installed", "data": {"installation": {"uuid": "x"}}})
    assert r.status_code == 200
    assert r.get_json()["stored"] is False


def test_idempotent_upsert_on_issue_id():
    c = app.app.test_client()
    r1 = _post(c, _issue_payload("dedup-1", count=3))
    assert r1.status_code == 200
    r2 = _post(c, _issue_payload("dedup-1", count=5, title="updated title"))
    assert r2.status_code == 200
    rows = app.query_db("SELECT event_count, title FROM sentry_alerts WHERE issue_id=%s",
                        ("dedup-1",))
    assert len(rows) == 1                      # one row, not two
    assert rows[0]["event_count"] == 5         # GREATEST(3, 5)
    assert rows[0]["title"] == "updated title"


def test_upsert_preserves_human_triage_status():
    # Recurrence must NOT clobber an admin's ack/fixed triage.
    c = app.app.test_client()
    _post(c, _issue_payload("triage-1"))
    app.execute_db("UPDATE sentry_alerts SET status='fixed' WHERE issue_id=%s", ("triage-1",))
    _post(c, _issue_payload("triage-1", count=9))   # issue recurs
    row = app.query_db("SELECT status, event_count FROM sentry_alerts WHERE issue_id=%s",
                       ("triage-1",), fetchone=True)
    assert row["status"] == "fixed"            # triage preserved
    assert row["event_count"] == 9             # but recurrence is visible


def test_malicious_title_is_stored_raw_not_executed():
    # The payload is untrusted; we store it verbatim (escaping happens at render).
    c = app.app.test_client()
    xss = "<img src=x onerror=alert(1)>"
    _post(c, _issue_payload("xss-1", title=xss))
    row = app.query_db("SELECT title FROM sentry_alerts WHERE issue_id=%s", ("xss-1",),
                       fetchone=True)
    assert row["title"] == xss                 # stored raw; UI renders via _escAuditCell


def test_alerts_api_requires_auth():
    c = app.app.test_client()           # anonymous
    r = c.get("/admin/api/sentry/alerts")
    assert r.status_code in (401, 403, 302)


def test_alerts_api_lists_for_super_admin():
    c = _sa()
    # seed one so the list is non-empty
    _post(app.app.test_client(), _issue_payload("list-1"))
    r = c.get("/admin/api/sentry/alerts?limit=50")
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] is True
    assert isinstance(j["alerts"], list)
    assert any(a["issue_id"] == "list-1" for a in j["alerts"])


def test_status_toggle_round_trips():
    c = _sa()
    _post(app.app.test_client(), _issue_payload("toggle-1"))
    row = app.query_db("SELECT id FROM sentry_alerts WHERE issue_id=%s", ("toggle-1",),
                       fetchone=True)
    aid = row["id"]
    r = c.post(f"/admin/api/sentry/alerts/{aid}/status",
               json={"status": "ack"}, headers={"X-CSRF-Token": "t"})
    assert r.status_code == 200 and r.get_json()["status"] == "ack"
    again = app.query_db("SELECT status FROM sentry_alerts WHERE id=%s", (aid,), fetchone=True)
    assert again["status"] == "ack"
    # invalid status rejected
    bad = c.post(f"/admin/api/sentry/alerts/{aid}/status",
                 json={"status": "bogus"}, headers={"X-CSRF-Token": "t"})
    assert bad.status_code == 400


def test_status_toggle_unknown_id_404():
    c = _sa()
    r = c.post("/admin/api/sentry/alerts/999999/status",
               json={"status": "fixed"}, headers={"X-CSRF-Token": "t"})
    assert r.status_code == 404
