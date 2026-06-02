"""Task 046 — visitor persona router. Embedded Postgres.

Covers:
  * _visitor_apply_persona is a no-op when the router is off / no personas /
    master switch off (returns inputs unchanged, persona 'general');
  * when on, the chosen persona constrains the tool list, appends its
    prompt_suffix to the system message, and can pin a model (only if its
    provider client is available);
  * the classifier is stubbed (monkeypatched) so routing is deterministic;
  * super-admin CRUD (create/list/update/delete), tenant-scoped, key
    validation + reserved 'general' + duplicate handling, client 403'd.
"""
import json
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")


def _reset():
    for k in ("visitor_persona_router_enabled", "visitor_persona_router_model",
              "ai_enhancements_enabled"):
        app.reset_ai_setting(k)
    app._invalidate_ai_control()


def _wipe():
    app.execute_db("DELETE FROM visitor_personas WHERE tenant_id=%s",
                   (app.current_tenant_id(),))


def _seed(key, *, tools=None, suffix="", model="", enabled=True):
    tid = app.current_tenant_id()
    app.execute_db(
        "INSERT INTO visitor_personas (tenant_id, persona_key, label, prompt_suffix, "
        " tool_names, model, enabled) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (tid, key, key.title(), suffix, json.dumps(tools or []), model, enabled))


def _tools(*names):
    return [{"type": "function", "function": {"name": n}} for n in names]


def _sysmsgs():
    return [{"role": "system", "content": "BASE PROMPT"},
            {"role": "user", "content": "hi"}]


# ---- gating -----------------------------------------------------------------

def test_disabled_is_noop():
    _reset(); _wipe()
    tools = _tools("lookup_faq", "capture_lead")
    msgs = _sysmsgs()
    m, p, t, key = app._visitor_apply_persona("I want a quote", "gpt-4o", "openai", tools, msgs)
    assert (m, p) == ("gpt-4o", "openai")
    assert t == tools and key == "general"
    assert msgs[0]["content"] == "BASE PROMPT"  # unchanged


def test_enabled_but_no_personas_is_noop():
    _reset(); _wipe()
    app.set_ai_setting("visitor_persona_router_enabled", True); app._invalidate_ai_control()
    try:
        tools = _tools("lookup_faq")
        m, p, t, key = app._visitor_apply_persona("hi", "gpt-4o", "openai", tools, _sysmsgs())
        assert key == "general" and t == tools
    finally:
        _reset(); _wipe()


def test_master_switch_forces_noop(monkeypatch):
    _reset(); _wipe()
    _seed("sales", tools=["capture_lead"], suffix="Be salesy")
    app.set_ai_setting("visitor_persona_router_enabled", True)
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    monkeypatch.setattr(app, "_visitor_classify_persona", lambda *a, **k: "sales")
    try:
        assert app.get_ai_setting("visitor_persona_router_enabled") is False
        tools = _tools("lookup_faq", "capture_lead")
        m, p, t, key = app._visitor_apply_persona("buy", "gpt-4o", "openai", tools, _sysmsgs())
        assert key == "general" and t == tools
    finally:
        _reset(); _wipe()


# ---- apply ------------------------------------------------------------------

def test_persona_constrains_tools_and_prompt(monkeypatch):
    _reset(); _wipe()
    _seed("sales", tools=["capture_lead", "lookup_offers"], suffix="PERSONA: Sales.")
    app.set_ai_setting("visitor_persona_router_enabled", True); app._invalidate_ai_control()
    monkeypatch.setattr(app, "_visitor_classify_persona", lambda *a, **k: "sales")
    try:
        tools = _tools("lookup_faq", "capture_lead", "lookup_offers", "lookup_team")
        msgs = _sysmsgs()
        m, p, t, key = app._visitor_apply_persona("I'd like to buy", "gpt-4o", "openai", tools, msgs)
        assert key == "sales"
        names = {x["function"]["name"] for x in t}
        assert names == {"capture_lead", "lookup_offers"}   # constrained
        # Task 079 cache fix: the suffix is inserted as a SEPARATE adjacent system
        # message (after the cacheable prefix), NOT concatenated into messages[0].
        # messages[0] stays byte-stable (cache prefix preserved); the model still
        # reads the same suffix text in the same array order.
        assert msgs[0]["content"] == "BASE PROMPT"            # prefix unchanged
        assert msgs[1]["role"] == "system"
        assert "PERSONA: Sales." in msgs[1]["content"]        # prompt augmented (adjacent)
    finally:
        _reset(); _wipe()


def test_empty_tool_names_means_all(monkeypatch):
    _reset(); _wipe()
    _seed("support", tools=[], suffix="Help them.")
    app.set_ai_setting("visitor_persona_router_enabled", True); app._invalidate_ai_control()
    monkeypatch.setattr(app, "_visitor_classify_persona", lambda *a, **k: "support")
    try:
        tools = _tools("lookup_faq", "capture_lead")
        m, p, t, key = app._visitor_apply_persona("help", "gpt-4o", "openai", tools, _sysmsgs())
        assert key == "support"
        assert len(t) == 2   # no tool filtering when tool_names is empty
    finally:
        _reset(); _wipe()


def test_model_override_when_provider_available(monkeypatch):
    _reset(); _wipe()
    _seed("sales", tools=[], model="gpt-4o-mini-sales")
    app.set_ai_setting("visitor_persona_router_enabled", True); app._invalidate_ai_control()
    monkeypatch.setattr(app, "_visitor_classify_persona", lambda *a, **k: "sales")
    try:
        m, p, t, key = app._visitor_apply_persona("buy", "gpt-4o", "openai", _tools("x"), _sysmsgs())
        assert m == "gpt-4o-mini-sales" and p == "openai"
    finally:
        _reset(); _wipe()


def test_model_override_skipped_when_provider_unavailable(monkeypatch):
    _reset(); _wipe()
    _seed("sales", tools=[], model="claude-3-5-haiku")
    app.set_ai_setting("visitor_persona_router_enabled", True); app._invalidate_ai_control()
    monkeypatch.setattr(app, "_visitor_classify_persona", lambda *a, **k: "sales")
    saved = app.anthropic_client
    app.anthropic_client = None  # claude model can't be honored
    try:
        m, p, t, key = app._visitor_apply_persona("buy", "gpt-4o", "openai", _tools("x"), _sysmsgs())
        assert m == "gpt-4o" and p == "openai"   # kept the default
    finally:
        app.anthropic_client = saved
        _reset(); _wipe()


def test_unknown_classification_falls_back_to_general(monkeypatch):
    _reset(); _wipe()
    _seed("sales", tools=["capture_lead"], suffix="Sales")
    app.set_ai_setting("visitor_persona_router_enabled", True); app._invalidate_ai_control()
    monkeypatch.setattr(app, "_visitor_classify_persona", lambda *a, **k: "general")
    try:
        tools = _tools("lookup_faq", "capture_lead")
        msgs = _sysmsgs()
        m, p, t, key = app._visitor_apply_persona("hi", "gpt-4o", "openai", tools, msgs)
        assert key == "general" and t == tools
        assert msgs[0]["content"] == "BASE PROMPT"
    finally:
        _reset(); _wipe()


# ---- classifier validation --------------------------------------------------

def test_classifier_returns_general_without_client():
    saved = app.openai_client
    app.openai_client = None
    try:
        assert app._visitor_classify_persona("buy", {"sales"}) == "general"
    finally:
        app.openai_client = saved


# ---- super-admin CRUD -------------------------------------------------------

def _sa():
    c = app.app.test_client()
    c.post("/admin/login", data={"password": ADMIN_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    return c


def _csrf():
    return {"X-CSRF-Token": "t"}


def test_crud_lifecycle():
    _wipe()
    c = _sa()
    try:
        r = c.post("/admin/api/visitor-personas", json={
            "persona_key": "sales", "label": "Sales", "prompt_suffix": "Be helpful",
            "tool_names": ["capture_lead", "lookup_offers"], "model": ""}, headers=_csrf())
        assert r.status_code == 201, r.get_data(as_text=True)
        pid = r.get_json()["persona"]["id"]
        assert r.get_json()["persona"]["tool_names"] == ["capture_lead", "lookup_offers"]
        # Duplicate key → 409
        r = c.post("/admin/api/visitor-personas", json={"persona_key": "sales"}, headers=_csrf())
        assert r.status_code == 409
        # Reserved key → 400
        r = c.post("/admin/api/visitor-personas", json={"persona_key": "general"}, headers=_csrf())
        assert r.status_code == 400
        # Bad key → 400
        r = c.post("/admin/api/visitor-personas", json={"persona_key": "Bad Key!"}, headers=_csrf())
        assert r.status_code == 400
        # List
        assert any(p["id"] == pid for p in c.get("/admin/api/visitor-personas").get_json()["personas"])
        # Update
        r = c.put(f"/admin/api/visitor-personas/{pid}", json={
            "persona_key": "sales", "enabled": False}, headers=_csrf())
        assert r.status_code == 200 and r.get_json()["persona"]["enabled"] is False
        # Delete
        assert c.delete(f"/admin/api/visitor-personas/{pid}", headers=_csrf()).status_code == 200
        assert c.delete(f"/admin/api/visitor-personas/{pid}", headers=_csrf()).status_code == 404
    finally:
        _wipe()


def test_crud_blocks_client():
    if not CLIENT_PW:
        return
    c = app.app.test_client()
    c.post("/admin/login", data={"password": CLIENT_PW})
    with c.session_transaction() as s:
        s["_csrf_token"] = "t"
    assert c.get("/admin/api/visitor-personas").status_code == 403
    assert c.post("/admin/api/visitor-personas", json={"persona_key": "x"},
                  headers={"X-CSRF-Token": "t"}).status_code == 403


# ---- registry ---------------------------------------------------------------

def test_knobs_registered():
    keys = {e["key"] for e in app._ai_control_registry()}
    assert {"visitor_persona_router_enabled", "visitor_persona_router_model"} <= keys


# =============================================================================
# Task 079 Phase 2 — visitor SPECIALIST router (independent fast path)
# =============================================================================
# These pin the OWNER's hard guarantee: default-OFF == today (the routed branch
# is never entered → _visitor_apply_persona returns its inputs UNCHANGED:
# identity model/provider/active_tools, persona_key 'general', messages[0]
# byte-stable). And when fully ON, tool narrowing keeps custom/MCP skills and the
# specialist sub-prompt is inserted as a SEPARATE adjacent system message.

def _spec_reset():
    for k in ("visitor_persona_router_enabled",
              "visitor_specialist_router_enabled",
              "visitor_specialist_router_model",
              "visitor_specialist_embed_threshold",
              "ai_enhancements_enabled"):
        app.reset_ai_setting(k)
    app._invalidate_ai_control()
    try:
        app.set_tenant_feature("visitor_specialist_router", False)
    except Exception:
        pass


def test_specialist_default_off_is_identity_noop():
    """The default for EVERY existing tenant: operator master OFF + feature OFF.
    _visitor_apply_persona must return its inputs UNCHANGED (proves flag-OFF ==
    today). Asserts object identity for model/provider/active_tools + an
    untouched messages[0]."""
    _spec_reset(); _wipe()
    try:
        tools = _tools("lookup_faq", "capture_lead", "lookup_offers")
        msgs = _sysmsgs()
        m, p, t, key = app._visitor_apply_persona(
            "I want to book an appointment", "gpt-4o", "openai", tools, msgs)
        assert (m, p) == ("gpt-4o", "openai")
        assert t is tools                       # SAME list object — no narrowing
        assert key == "general"
        assert len(msgs) == 2                    # no extra system message inserted
        assert msgs[0]["content"] == "BASE PROMPT"
    finally:
        _spec_reset(); _wipe()


def test_specialist_master_on_but_feature_off_is_noop():
    """Operator master ON but the per-client feature flag OFF → still today's
    flow (BOTH are required)."""
    _spec_reset(); _wipe()
    app.set_ai_setting("visitor_specialist_router_enabled", True)
    app._invalidate_ai_control()
    app.set_tenant_feature("visitor_specialist_router", False)
    try:
        tools = _tools("lookup_faq", "lookup_offers")
        msgs = _sysmsgs()
        m, p, t, key = app._visitor_apply_persona(
            "how much does it cost", "gpt-4o", "openai", tools, msgs)
        assert key == "general" and t is tools
        assert msgs[0]["content"] == "BASE PROMPT" and len(msgs) == 2
    finally:
        _spec_reset(); _wipe()


def test_specialist_feature_on_but_master_off_is_noop():
    """Per-client feature ON but operator master OFF → still today's flow."""
    _spec_reset(); _wipe()
    app.set_tenant_feature("visitor_specialist_router", True)
    # master left OFF (default)
    try:
        tools = _tools("lookup_faq", "lookup_offers")
        m, p, t, key = app._visitor_apply_persona(
            "how much does it cost", "gpt-4o", "openai", tools, _sysmsgs())
        assert key == "general" and t is tools
    finally:
        _spec_reset(); _wipe()


def test_specialist_master_kill_forces_noop(monkeypatch):
    """With the AI master kill OFF, get_ai_setting forces the operator master to
    its inert False, so even with the feature flag on the router never runs."""
    _spec_reset(); _wipe()
    app.set_ai_setting("visitor_specialist_router_enabled", True)
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    app.set_tenant_feature("visitor_specialist_router", True)
    # If the branch were wrongly entered, this keyword would route to booking.
    try:
        assert app.get_ai_setting("visitor_specialist_router_enabled") is False
        tools = _tools("lookup_faq", "lookup_offers")
        m, p, t, key = app._visitor_apply_persona(
            "book an appointment", "gpt-4o", "openai", tools, _sysmsgs())
        assert key == "general" and t is tools
    finally:
        _spec_reset(); _wipe()


def test_specialist_on_narrows_builtins_keeps_custom_and_inserts_prompt(monkeypatch):
    """Fully ON (master + feature). The booking specialist narrows to its builtin
    subset BUT keeps a custom (non-CHAT_TOOLS) skill (risk R4), and inserts the
    sub-prompt as a separate adjacent system message after the cacheable prefix
    (risk R1/R6)."""
    _spec_reset(); _wipe()
    app.set_ai_setting("visitor_specialist_router_enabled", True)
    app._invalidate_ai_control()
    app.set_tenant_feature("visitor_specialist_router", True)
    # Deterministic classification → booking.
    monkeypatch.setattr(app, "_visitor_classify_specialist", lambda *a, **k: "booking")
    try:
        # lookup_services + book_meeting are in the booking subset; lookup_blog is
        # a builtin NOT in the subset (should be pruned); my_custom_webhook is a
        # custom skill (NOT a CHAT_TOOLS builtin → must be kept).
        tools = _tools("lookup_services", "book_meeting", "lookup_blog", "my_custom_webhook")
        msgs = _sysmsgs()
        m, p, t, key = app._visitor_apply_persona(
            "book an appointment", "gpt-4o", "openai", tools, msgs)
        assert key == "booking"
        names = {x["function"]["name"] for x in t}
        assert "lookup_services" in names and "book_meeting" in names  # subset kept
        assert "lookup_blog" not in names                              # builtin pruned
        assert "my_custom_webhook" in names                           # custom retained
        # Separate adjacent system message; prefix byte-stable; reminder-position
        # safe (the user msg — the original messages[1] — is now last).
        assert msgs[0]["content"] == "BASE PROMPT"
        assert msgs[1]["role"] == "system" and "SPECIALIST CONTEXT" in msgs[1]["content"]
        assert msgs[-1] == {"role": "user", "content": "hi"}
    finally:
        _spec_reset(); _wipe()


def test_specialist_classifier_failure_fails_open(monkeypatch):
    """If the classifier raises, the turn falls open to 'general' (full tools,
    no specialist block) — chat never breaks."""
    _spec_reset(); _wipe()
    app.set_ai_setting("visitor_specialist_router_enabled", True)
    app._invalidate_ai_control()
    app.set_tenant_feature("visitor_specialist_router", True)

    def _boom(*a, **k):
        raise RuntimeError("classifier down")
    monkeypatch.setattr(app, "_visitor_classify_specialist", _boom)
    try:
        tools = _tools("lookup_faq", "lookup_offers")
        msgs = _sysmsgs()
        m, p, t, key = app._visitor_apply_persona(
            "anything", "gpt-4o", "openai", tools, msgs)
        assert key == "general" and t is tools
        assert msgs[0]["content"] == "BASE PROMPT" and len(msgs) == 2
    finally:
        _spec_reset(); _wipe()


def test_specialist_keyword_classifier_is_deterministic():
    """The keyword stage (no LLM needed) maps clear messages to the right lane."""
    assert app._visitor_classify_specialist("I want to book an appointment") == "booking"
    assert app._visitor_classify_specialist("how much does this cost?") == "pricing"
    assert app._visitor_classify_specialist("please call me back") == "leadcap"


def test_specialist_knobs_registered():
    keys = {e["key"] for e in app._ai_control_registry()}
    assert {"visitor_specialist_router_enabled", "visitor_specialist_router_model",
            "visitor_specialist_embed_threshold"} <= keys
    assert "visitor_specialist_router" in app._FEATURE_NAMES
