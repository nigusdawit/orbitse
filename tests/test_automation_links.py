"""Task 068 — Automation links. Embedded Postgres.

The RCE pipeline (research → generate → publish) is exposed as automation
actions. Verifies the actions are registered (dispatch + builder metadata), the
register_action seam is additive, the impls map cfg → the _rce_* helpers
correctly (stubbed), and that the feature gates propagate as a clean step
failure when a knob is off.
"""
import app
import automations


def _reset():
    for k in ("research_hub_enabled", "content_studio_enabled",
              "autopublish_enabled", "ai_enhancements_enabled"):
        app.reset_ai_setting(k)
    app._invalidate_ai_control()


# ---- registration -----------------------------------------------------------

def test_actions_registered():
    for k in ("rce_research", "rce_generate_content", "rce_publish"):
        assert k in automations._ACTION_DISPATCH
    kinds = {a["kind"] for a in automations.action_metadata()}
    assert {"rce_research", "rce_generate_content", "rce_publish"} <= kinds


def test_register_action_is_additive():
    before = len(automations._ACTION_DISPATCH)
    sentinel = {"x": 0}

    def _impl(cfg, ctx):
        return {"ok": True}

    automations.register_action("rce_test_tmp", _impl,
                                {"kind": "rce_test_tmp", "label": "tmp",
                                 "config_fields": []})
    try:
        assert automations._ACTION_DISPATCH["rce_test_tmp"] is _impl
        assert any(a["kind"] == "rce_test_tmp" for a in automations.action_metadata())
        # built-ins are untouched
        assert "send_email" in automations._ACTION_DISPATCH
        assert len(automations._ACTION_DISPATCH) == before + 1
    finally:
        automations._ACTION_DISPATCH.pop("rce_test_tmp", None)
        automations.ACTION_TYPES[:] = [a for a in automations.ACTION_TYPES
                                       if a.get("kind") != "rce_test_tmp"]
        _ = sentinel


# ---- impl cfg → helper mapping (stubbed) -----------------------------------

def test_research_action_maps(monkeypatch):
    seen = {}

    def fake(q, **kw):
        seen["q"] = q
        seen["topic"] = kw.get("topic")
        return {"report_id": 9, "status": "ready", "sources": 3}

    monkeypatch.setattr(app, "_rce_run_research", fake)
    out = app._rce_action_research({"question": "What is X?", "topic": "X"}, {})
    assert out["ok"] is True and out["report_id"] == 9 and out["sources"] == 3
    assert seen["q"] == "What is X?" and seen["topic"] == "X"


def test_research_action_requires_question():
    assert app._rce_action_research({}, {})["ok"] is False


def test_generate_action_parses_comma_types(monkeypatch):
    seen = {}

    def fake(rid, types, **kw):
        seen["rid"] = rid
        seen["types"] = types
        return {"drafts": [{"draft_id": 1}, {"draft_id": 2}]}

    monkeypatch.setattr(app, "_rce_generate_from_report", fake)
    out = app._rce_action_generate(
        {"report_id": "7", "content_types": "blog, social ,email"}, {})
    assert out["ok"] is True and len(out["drafts"]) == 2
    assert seen["rid"] == "7" and seen["types"] == ["blog", "social", "email"]


def test_generate_action_requires_inputs():
    assert app._rce_action_generate({"report_id": 1}, {})["ok"] is False
    assert app._rce_action_generate({"content_types": "blog"}, {})["ok"] is False


def test_publish_action_maps_ok_and_error(monkeypatch):
    monkeypatch.setattr(app, "_rce_publish_draft",
                        lambda d, c, **kw: {"ok": True, "status": 200})
    out = app._rce_action_publish({"draft_id": 1, "capability_id": 2}, {})
    assert out["ok"] is True

    monkeypatch.setattr(app, "_rce_publish_draft",
                        lambda d, c, **kw: {"error": "Auto-publish is turned off."})
    out2 = app._rce_action_publish({"draft_id": 1, "capability_id": 2}, {})
    assert out2["ok"] is False and "off" in out2["error"]


def test_publish_action_requires_inputs():
    assert app._rce_action_publish({"draft_id": 1}, {})["ok"] is False


# ---- gates propagate (no stub, no network — knobs short-circuit) -----------

def test_gates_propagate_as_step_failure():
    _reset()  # all RCE knobs off
    try:
        r = app._rce_action_research({"question": "q"}, {})
        assert r["ok"] is False and "off" in r["error"].lower()
        g = app._rce_action_generate({"report_id": 1, "content_types": "blog"}, {})
        assert g["ok"] is False and "off" in g["error"].lower()
        p = app._rce_action_publish({"draft_id": 1, "capability_id": 1}, {})
        assert p["ok"] is False and "off" in p["error"].lower()
    finally:
        _reset()
