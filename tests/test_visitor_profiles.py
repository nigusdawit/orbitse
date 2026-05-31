"""Task 042 — visitor CRM profiles + needs capture. Embedded Postgres.

Covers:
  * the table exists (init_db + migration 0012);
  * signal normalization bounds/cleans the raw extraction;
  * upsert merges signals (union tags, max lead_score, sticky consent, turn++);
  * extraction via a stubbed OpenAI client returns a normalized dict;
  * the async updater is a no-op when the knob is off, persists when on, and is
    forced off by the master kill switch;
  * the super-admin read API gates a client out (403) and returns profiles.
"""
import json
import os
import time

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


# ---- stubbed OpenAI client for deterministic extraction --------------------

class _FakeMsg:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeMsg(content)]


class _FakeCompletions:
    def __init__(self, content):
        self._content = content

    def create(self, **kwargs):
        return _FakeResp(self._content)


class _FakeOpenAI:
    """Mimics the slice of the OpenAI client _extract_visitor_signals uses:
    client.with_options(...).chat.completions.create(...).choices[0].message.content"""
    def __init__(self, content):
        self.chat = type("C", (), {"completions": _FakeCompletions(content)})

    def with_options(self, **kwargs):
        return self


def _reset():
    for k in ("visitor_profiles_enabled", "visitor_profiles_model",
              "ai_enhancements_enabled"):
        app.reset_ai_setting(k)
    app._invalidate_ai_control()


def _wipe(vid):
    app.execute_db("DELETE FROM visitor_profiles WHERE visitor_id=%s", (vid,))


# ---- normalization ----------------------------------------------------------

def test_normalize_bounds_and_cleans():
    sig = app._vp_normalize_signals({
        "interests": ["  pricing ", "pricing", 123, ""] + [f"t{i}" for i in range(40)],
        "needs": "not a list",
        "lead_score": 999,
        "consent": "yes",
        "summary": "x" * 900,
    })
    assert "pricing" in sig["interests"]
    assert sig["interests"].count("pricing") == 1     # de-duped
    assert len(sig["interests"]) <= 25                # capped
    assert sig["needs"] == []                          # non-list → []
    assert sig["lead_score"] == 100                    # clamped 0..100
    assert sig["consent"] is True                      # truthy → bool
    assert len(sig["summary"]) <= 500


def test_normalize_handles_garbage():
    sig = app._vp_normalize_signals({"lead_score": "abc"})
    assert sig["lead_score"] == 0
    assert sig["interests"] == [] and sig["needs"] == []
    assert sig["consent"] is False and sig["summary"] == ""


# ---- upsert merge -----------------------------------------------------------

def test_upsert_inserts_then_merges():
    vid = "vp-merge-test"
    _wipe(vid)
    tid = app.current_tenant_id()
    try:
        app._visitor_profile_upsert(tid, vid, {
            "interests": ["pricing"], "needs": ["a demo"],
            "lead_score": 30, "consent": False, "summary": "first",
        })
        row = app.query_db(
            "SELECT * FROM visitor_profiles WHERE tenant_id=%s AND visitor_id=%s",
            (tid, vid), fetchone=True)
        assert row and row["lead_score"] == 30 and row["turns"] == 1
        assert app._vp_as_list(row["interests"]) == ["pricing"]
        assert row["consent"] is False

        # Second turn: new interest, lower score (max wins), consent becomes true.
        app._visitor_profile_upsert(tid, vid, {
            "interests": ["integrations"], "needs": ["a demo", "a quote"],
            "lead_score": 10, "consent": True, "summary": "second",
        })
        row = app.query_db(
            "SELECT * FROM visitor_profiles WHERE tenant_id=%s AND visitor_id=%s",
            (tid, vid), fetchone=True)
        assert row["turns"] == 2
        assert set(app._vp_as_list(row["interests"])) == {"pricing", "integrations"}
        assert set(app._vp_as_list(row["needs"])) == {"a demo", "a quote"}
        assert row["lead_score"] == 30      # MAX(30, 10)
        assert row["consent"] is True       # sticky once true
        assert row["summary"] == "second"   # latest
    finally:
        _wipe(vid)


# ---- extraction (stubbed) ---------------------------------------------------

def test_extract_visitor_signals_parses_openai_json():
    saved = app.openai_client
    app.openai_client = _FakeOpenAI(json.dumps({
        "interests": ["catering"], "needs": ["book an event"],
        "lead_score": 70, "consent": False, "summary": "wants catering",
    }))
    try:
        sig = app._extract_visitor_signals("do you cater?", "Yes we do!", "gpt-4o-mini")
        assert sig["interests"] == ["catering"]
        assert sig["lead_score"] == 70
    finally:
        app.openai_client = saved


def test_extract_returns_none_without_client():
    saved = app.openai_client
    app.openai_client = None
    try:
        assert app._extract_visitor_signals("hi", "hello", "gpt-4o-mini") is None
    finally:
        app.openai_client = saved


# ---- async gating -----------------------------------------------------------

def test_async_noop_when_disabled():
    _reset()  # knob off (default)
    vid = "vp-disabled"
    _wipe(vid)
    saved = app.openai_client
    app.openai_client = _FakeOpenAI(json.dumps({"interests": ["x"], "lead_score": 5}))
    try:
        app._visitor_profile_update_async(app.current_tenant_id(), vid, "q", "a")
        time.sleep(0.4)
        row = app.query_db("SELECT 1 FROM visitor_profiles WHERE visitor_id=%s",
                           (vid,), fetchone=True)
        assert not row  # nothing written — knob off
    finally:
        app.openai_client = saved
        _wipe(vid); _reset()


def test_async_persists_when_enabled():
    _reset()
    app.set_ai_setting("visitor_profiles_enabled", True)
    app._invalidate_ai_control()
    vid = "vp-enabled"
    _wipe(vid)
    saved = app.openai_client
    app.openai_client = _FakeOpenAI(json.dumps({
        "interests": ["pricing"], "needs": ["a quote"],
        "lead_score": 55, "consent": True, "summary": "hot lead",
    }))
    try:
        app._visitor_profile_update_async(app.current_tenant_id(), vid,
                                          "what does it cost?", "Here's pricing...")
        ok = False
        for _ in range(40):  # up to ~4s
            row = app.query_db("SELECT lead_score FROM visitor_profiles "
                               "WHERE visitor_id=%s", (vid,), fetchone=True)
            if row:
                assert row["lead_score"] == 55
                ok = True
                break
            time.sleep(0.1)
        assert ok, "background updater did not write the profile"
    finally:
        app.openai_client = saved
        _wipe(vid); _reset()


def test_master_switch_forces_off():
    _reset()
    app.set_ai_setting("visitor_profiles_enabled", True)
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    vid = "vp-master-off"
    _wipe(vid)
    saved = app.openai_client
    app.openai_client = _FakeOpenAI(json.dumps({"interests": ["x"], "lead_score": 9}))
    try:
        assert app.get_ai_setting("visitor_profiles_enabled") is False
        app._visitor_profile_update_async(app.current_tenant_id(), vid, "q", "a")
        time.sleep(0.4)
        row = app.query_db("SELECT 1 FROM visitor_profiles WHERE visitor_id=%s",
                           (vid,), fetchone=True)
        assert not row
    finally:
        app.openai_client = saved
        _wipe(vid); _reset()


# ---- super-admin route gating ----------------------------------------------

def _login(c, pw):
    return c.post("/admin/login", data={"password": pw})


def test_route_super_admin_ok():
    c = app.app.test_client()
    _login(c, ADMIN_PW)
    r = c.get("/admin/api/visitor-profiles")
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert "profiles" in body and "stats" in body


def test_route_blocks_client_session():
    if not CLIENT_PW:
        # No client password configured in this harness → skip the negative case.
        return
    c = app.app.test_client()
    _login(c, CLIENT_PW)
    r = c.get("/admin/api/visitor-profiles")
    assert r.status_code == 403


# ---- registry ---------------------------------------------------------------

def test_knobs_in_registry():
    keys = {e["key"] for e in app._ai_control_registry()}
    assert {"visitor_profiles_enabled", "visitor_profiles_model"} <= keys
