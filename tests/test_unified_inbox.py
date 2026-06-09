"""Unified inbox — chat + SMS + voice in one Conversations inbox. Embedded Postgres (no DB mocks;
Twilio send + the inbound signature are stubbed at the boundary).

Covers: the core find-or-create + append helpers; SMS inbound ingestion (and that STOP doesn't
create a thread); Vapi voice ingestion (transcript → messages, idempotent on retry); the list
endpoint's channel filter + per-channel counts; and operator-reply routing (voice read-only, SMS
sends back over SMS, chat keeps the human-takeover behavior).
"""
import os

import app
import core
import admin.vapi as vapi_mod  # noqa: F401  (ensures the blueprint + webhook are registered)

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
_CSRF = {"X-CSRF-Token": "t"}


def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    return c


def _cleanup_conv(session_id):
    row = app.query_db("SELECT id FROM chat_conversations WHERE session_id=%s", (session_id,), fetchone=True)
    if isinstance(row, dict):
        app.execute_db("DELETE FROM chat_messages WHERE conversation_id=%s", (row["id"],))
        app.execute_db("DELETE FROM conversation_takeover WHERE conversation_id=%s", (row["id"],))
        app.execute_db("DELETE FROM chat_conversations WHERE id=%s", (row["id"],))


# ---- core ingestion helpers -------------------------------------------------

def test_core_get_or_create_and_append():
    sid = "test:helper1"
    _cleanup_conv(sid)
    try:
        cid, created = core.inbox_get_or_create_conversation(sid, channel="sms", contact="+15551110000")
        assert cid and created is True
        cid2, created2 = core.inbox_get_or_create_conversation(sid, channel="sms", contact="+15551110000")
        assert cid2 == cid and created2 is False   # idempotent by session_id
        core.inbox_append_message(cid, "user", "hi there")
        row = app.query_db("SELECT channel, contact FROM chat_conversations WHERE id=%s", (cid,), fetchone=True)
        assert row["channel"] == "sms" and row["contact"] == "+15551110000"
        n = app.query_db("SELECT COUNT(*) AS n FROM chat_messages WHERE conversation_id=%s", (cid,), fetchone=True)["n"]
        assert n == 1
    finally:
        _cleanup_conv(sid)


# ---- SMS inbound ingestion --------------------------------------------------

def test_sms_inbound_creates_conversation():
    os.environ.pop("TWILIO_AUTH_TOKEN", None)   # no token → inbound signature verify fail-opens
    phone = "+15552223333"
    _cleanup_conv("sms:" + phone)
    try:
        pub = app.app.test_client()
        r = pub.post("/webhooks/twilio/inbound-sms",
                     data={"From": phone, "Body": "Hi, do you have availability?"})
        assert r.status_code == 200
        conv = app.query_db("SELECT id, channel, contact FROM chat_conversations WHERE session_id=%s",
                            ("sms:" + phone,), fetchone=True)
        assert conv and conv["channel"] == "sms" and conv["contact"] == phone
        msgs = app.query_db("SELECT role, content FROM chat_messages WHERE conversation_id=%s", (conv["id"],))
        assert any(m["role"] == "user" and "availability" in m["content"] for m in (msgs or []))
    finally:
        _cleanup_conv("sms:" + phone)


def test_sms_inbound_stop_does_not_create_conversation():
    os.environ.pop("TWILIO_AUTH_TOKEN", None)
    phone = "+15552224444"
    _cleanup_conv("sms:" + phone)
    try:
        pub = app.app.test_client()
        r = pub.post("/webhooks/twilio/inbound-sms", data={"From": phone, "Body": "STOP"})
        assert r.status_code == 200
        conv = app.query_db("SELECT id FROM chat_conversations WHERE session_id=%s", ("sms:" + phone,), fetchone=True)
        assert not conv   # STOP → opt-out only, no conversation thread (no-row → falsy)
    finally:
        _cleanup_conv("sms:" + phone)


# ---- voice ingestion via the Vapi webhook -----------------------------------

def test_vapi_webhook_ingests_voice_conversation():
    os.environ.pop("VAPI_WEBHOOK_SECRET", None)   # no secret → webhook fail-opens
    call_id = "vc_inbox_test_1"
    sid = "vapi:" + call_id
    _cleanup_conv(sid)
    app.execute_db("DELETE FROM voice_calls WHERE vapi_call_id=%s", (call_id,))
    try:
        pub = app.app.test_client()
        payload = {"message": {"type": "end-of-call-report",
                               "call": {"id": call_id, "type": "inboundPhoneCall"},
                               "customer": {"number": "+15556667777"},
                               "transcript": "User: Hi\nAI: Hello, how can I help?",
                               "summary": "Greeting", "recordingUrl": "https://example.test/rec.mp3"}}
        r = pub.post("/webhooks/vapi", json=payload)
        assert r.status_code == 200
        conv = app.query_db("SELECT id, channel, contact, recording_url FROM chat_conversations "
                            "WHERE session_id=%s", (sid,), fetchone=True)
        assert conv and conv["channel"] == "voice" and conv["contact"] == "+15556667777"
        assert conv["recording_url"] == "https://example.test/rec.mp3"
        msgs = app.query_db("SELECT role, content FROM chat_messages WHERE conversation_id=%s ORDER BY id",
                            (conv["id"],)) or []
        assert len(msgs) >= 3   # summary note + 2 transcript turns
        assert any("Greeting" in m["content"] for m in msgs)
        assert any(m["role"] == "user" and "Hi" in m["content"] for m in msgs)
        # idempotent: a webhook retry must NOT duplicate the transcript
        r2 = pub.post("/webhooks/vapi", json=payload)
        assert r2.status_code == 200
        n2 = app.query_db("SELECT COUNT(*) AS n FROM chat_messages WHERE conversation_id=%s",
                          (conv["id"],), fetchone=True)["n"]
        assert n2 == len(msgs)
    finally:
        _cleanup_conv(sid)
        app.execute_db("DELETE FROM voice_calls WHERE vapi_call_id=%s", (call_id,))
        app.execute_db("DELETE FROM voice_cost_events WHERE session_id=%s", (call_id,))


# ---- list endpoint: channel filter + counts ---------------------------------

def test_list_channel_filter_and_counts():
    seeds = [("test:flt_chat", "chat", ""), ("test:flt_sms", "sms", "+15550001"),
             ("test:flt_voice", "voice", "+15550002")]
    for sid, ch, ct in seeds:
        _cleanup_conv(sid)
        core.inbox_get_or_create_conversation(sid, channel=ch, contact=ct)
    try:
        c = _sa()
        d = c.get("/admin/api/chat-history?channel=sms").get_json()
        assert all(cv.get("channel") == "sms" for cv in d["conversations"])
        assert any(cv.get("session_id") == "test:flt_sms" for cv in d["conversations"])
        st = d.get("stats", {})
        assert st.get("count_sms", 0) >= 1 and st.get("count_voice", 0) >= 1 and st.get("count_chat", 0) >= 1
    finally:
        for sid, _, _ in seeds:
            _cleanup_conv(sid)


# ---- operator reply routing by channel --------------------------------------

def test_reply_voice_is_read_only():
    sid = "test:reply_voice"
    _cleanup_conv(sid)
    cid, _ = core.inbox_get_or_create_conversation(sid, channel="voice", contact="+15550003")
    try:
        r = _sa().post("/admin/api/conversations/%d/message" % cid, headers=_CSRF, json={"content": "hello"})
        assert r.status_code == 400 and r.get_json().get("error") == "no_text_reply"
    finally:
        _cleanup_conv(sid)


def test_reply_sms_sends_sms_and_logs():
    sid = "test:reply_sms"
    phone = "+15550004"
    _cleanup_conv(sid)
    cid, _ = core.inbox_get_or_create_conversation(sid, channel="sms", contact=phone)
    import messaging
    sent = {}
    orig = messaging.send_sms
    messaging.send_sms = lambda to, body, **kw: (sent.update({"to": to, "body": body}) or {"sid": "SM1"})
    try:
        r = _sa().post("/admin/api/conversations/%d/message" % cid, headers=_CSRF,
                       json={"content": "Thanks for reaching out!"})
        assert r.status_code == 200 and r.get_json().get("channel") == "sms"
        assert sent["to"] == phone and sent["body"] == "Thanks for reaching out!"
        n = app.query_db("SELECT COUNT(*) AS n FROM chat_messages WHERE conversation_id=%s "
                         "AND role='agent_human'", (cid,), fetchone=True)["n"]
        assert n == 1
    finally:
        messaging.send_sms = orig
        _cleanup_conv(sid)


def test_reply_chat_still_takes_over():
    sid = "test:reply_chat"
    _cleanup_conv(sid)
    cid, _ = core.inbox_get_or_create_conversation(sid, channel="chat")
    try:
        r = _sa().post("/admin/api/conversations/%d/message" % cid, headers=_CSRF,
                       json={"content": "hi from a human"})
        assert r.status_code == 200 and r.get_json().get("ai_paused") is True
    finally:
        _cleanup_conv(sid)
