"""Task 043 — newsletter signup tool + self-service preferences portal.
Embedded Postgres.

Covers:
  * scoped prefs token round-trips and is NOT interchangeable with the
    unsubscribe token (and rejects tampering);
  * subscribe_newsletter is gated (knob off → declines; master switch off →
    declines), validates email, inserts once, is idempotent for an existing
    subscriber, and NEVER silently re-opts-in someone who unsubscribed;
  * the public /preferences portal: bad token → 400, valid → 200, save flips
    opt-ins, unsubscribe clears them + stamps unsubscribed_at, re-opt-in clears
    the timestamp.
"""
import os

import app
import messaging

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")


def _enable():
    app.set_ai_setting("newsletter_signup_enabled", True)
    app._invalidate_ai_control()


def _reset():
    for k in ("newsletter_signup_enabled", "ai_enhancements_enabled"):
        app.reset_ai_setting(k)
    app._invalidate_ai_control()


def _wipe(addr):
    app.execute_db("DELETE FROM subscribers WHERE LOWER(email)=%s", (addr.lower(),))


# ---- tokens -----------------------------------------------------------------

def test_prefs_token_roundtrip():
    t = messaging.make_prefs_token(4242)
    assert messaging.parse_prefs_token(t) == 4242


def test_prefs_and_unsub_tokens_not_interchangeable():
    # An unsubscribe token must NOT validate as a prefs token (scope separation).
    unsub = messaging.make_unsubscribe_token(7)
    assert messaging.parse_prefs_token(unsub) is None
    # ...and a prefs token is not a valid unsubscribe token either.
    prefs = messaging.make_prefs_token(7)
    assert messaging.parse_unsubscribe_token(prefs) is None


def test_prefs_token_rejects_tamper():
    t = messaging.make_prefs_token(99)
    assert messaging.parse_prefs_token(t + "x") is None
    assert messaging.parse_prefs_token("") is None
    assert messaging.parse_prefs_token("garbage.token") is None


# ---- subscribe_newsletter ---------------------------------------------------

def test_declines_when_disabled():
    _reset()
    r = app.subscribe_newsletter(email="a@b.com")
    assert r["ok"] is False


def test_declines_on_bad_email():
    _enable()
    try:
        r = app.subscribe_newsletter(email="not-an-email")
        assert r["ok"] is False
    finally:
        _reset()


def test_subscribes_new_email_once():
    addr = "newsub@example.com"
    _wipe(addr)
    _enable()
    try:
        r = app.subscribe_newsletter(email=addr, full_name="New Sub")
        assert r["ok"] is True and r.get("subscribed") is True
        assert "/preferences?token=" in r["manage_url"]
        rows = app.query_db("SELECT opt_in, opt_in_email, source FROM subscribers "
                            "WHERE LOWER(email)=%s", (addr,))
        assert len(rows) == 1
        assert rows[0]["opt_in"] is True and rows[0]["source"] == "ai_chat"

        # Idempotent: a second call doesn't create a duplicate row.
        r2 = app.subscribe_newsletter(email=addr)
        assert r2.get("already") is True
        rows2 = app.query_db("SELECT id FROM subscribers WHERE LOWER(email)=%s", (addr,))
        assert len(rows2) == 1
    finally:
        _wipe(addr); _reset()


def test_does_not_resubscribe_unsubscribed_person():
    addr = "optout@example.com"
    _wipe(addr)
    _enable()
    try:
        # Seed an already-unsubscribed subscriber.
        app.execute_db(
            "INSERT INTO subscribers (email, list_name, source, opt_in, opt_in_email, "
            " unsubscribed_at) VALUES (%s,'newsletter','manual',FALSE,FALSE,NOW())", (addr,))
        r = app.subscribe_newsletter(email=addr)
        assert r.get("resubscribe") is True
        # Critically: still opted OUT (not silently flipped back on).
        row = app.query_db("SELECT opt_in FROM subscribers WHERE LOWER(email)=%s",
                           (addr,), fetchone=True)
        assert row["opt_in"] is False
    finally:
        _wipe(addr); _reset()


def test_master_switch_forces_decline():
    addr = "masteroff@example.com"
    _wipe(addr)
    app.set_ai_setting("newsletter_signup_enabled", True)
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    try:
        assert app.get_ai_setting("newsletter_signup_enabled") is False
        r = app.subscribe_newsletter(email=addr)
        assert r["ok"] is False
        assert not app.query_db("SELECT 1 FROM subscribers WHERE LOWER(email)=%s",
                                (addr,), fetchone=True)
    finally:
        _wipe(addr); _reset()


# ---- /preferences portal ----------------------------------------------------

def _seed(addr, **cols):
    app.execute_db("DELETE FROM subscribers WHERE LOWER(email)=%s", (addr.lower(),))
    row = app.execute_db(
        "INSERT INTO subscribers (email, phone, list_name, source, opt_in, "
        " opt_in_email, opt_in_sms) VALUES (%s,%s,'newsletter','manual',TRUE,TRUE,TRUE) "
        "RETURNING id", (addr, cols.get("phone", "")))
    return row["id"]


def test_portal_bad_token_400():
    c = app.app.test_client()
    r = c.get("/preferences?token=bogus")
    assert r.status_code == 400


def test_portal_get_shows_email():
    addr = "portal@example.com"
    sid = _seed(addr)
    try:
        c = app.app.test_client()
        tok = messaging.make_prefs_token(sid)
        r = c.get(f"/preferences?token={tok}")
        assert r.status_code == 200
        assert addr in r.get_data(as_text=True)
    finally:
        _wipe(addr)


def test_portal_unsubscribe_then_resubscribe():
    addr = "toggle@example.com"
    sid = _seed(addr)
    try:
        c = app.app.test_client()
        tok = messaging.make_prefs_token(sid)
        # Unsubscribe from everything.
        r = c.post("/preferences", data={"token": tok, "action": "unsubscribe"})
        assert r.status_code == 200
        row = app.query_db("SELECT opt_in, opt_in_email, unsubscribed_at FROM subscribers "
                           "WHERE id=%s", (sid,), fetchone=True)
        assert row["opt_in"] is False and row["opt_in_email"] is False
        assert row["unsubscribed_at"] is not None
        # Re-opt-in to email only → master on, timestamp cleared.
        r2 = c.post("/preferences", data={"token": tok, "action": "save",
                                          "opt_in_email": "on"})
        assert r2.status_code == 200
        row2 = app.query_db("SELECT opt_in, opt_in_email, unsubscribed_at FROM subscribers "
                            "WHERE id=%s", (sid,), fetchone=True)
        assert row2["opt_in"] is True and row2["opt_in_email"] is True
        assert row2["unsubscribed_at"] is None
    finally:
        _wipe(addr)


def test_portal_fails_closed_on_insecure_secret(monkeypatch):
    """If no real signing secret is configured, the portal must fail CLOSED
    (503) rather than serve a surface whose tokens are forgeable."""
    addr = "failclosed@example.com"
    sid = _seed(addr)
    try:
        monkeypatch.setattr(messaging, "signing_secret_is_insecure", lambda: True)
        c = app.app.test_client()
        tok = messaging.make_prefs_token(sid)
        assert c.get(f"/preferences?token={tok}").status_code == 503
        assert c.post("/preferences", data={"token": tok, "action": "unsubscribe"}).status_code == 503
    finally:
        _wipe(addr)


# ---- registry / skills ------------------------------------------------------

def test_tool_registered():
    assert "subscribe_newsletter" in app.CHAT_LOOKUP_FUNCTIONS
    names = {t["function"]["name"] for t in app.CHAT_TOOLS}
    assert "subscribe_newsletter" in names
    keys = {e["key"] for e in app._ai_control_registry()}
    assert "newsletter_signup_enabled" in keys
