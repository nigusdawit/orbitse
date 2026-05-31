"""Task 040 — per-request model routing (Epic C / speed). Embedded Postgres.

Verifies the `_route_turn_model` helper and its AI-Control knobs:
  * default-off → identity (every turn keeps its default model);
  * when enabled, short messages route to the fast model, long ones don't;
  * routing only fires when the fast model's provider client is available;
  * the master kill switch forces routing inert even with a DB override set.

All routing logic is exercised directly against the live config/registry so we
don't need a real LLM call — routing is a pure pre-flight model selection.
"""
import app

# A fast model whose provider client is (almost) always available in tests:
# OpenAI is constructed unconditionally at import (no live key needed to exist).
FAST_OPENAI = "gpt-4o-mini-fast"


def _reset_routing():
    """Return all routing knobs + the master switch to their defaults."""
    for k in ("model_routing_enabled", "fast_model",
              "routing_simple_max_chars", "ai_enhancements_enabled"):
        app.reset_ai_setting(k)
    app._invalidate_ai_control()


def test_default_off_is_identity():
    """With routing off (default), the helper returns the caller's defaults."""
    _reset_routing()
    try:
        model, provider = app._route_turn_model("gpt-4o", "openai", "hi")
        assert model == "gpt-4o" and provider == "openai"
        # A long message is likewise untouched.
        model, provider = app._route_turn_model("claude-sonnet-4-5", "claude", "x" * 9000)
        assert model == "claude-sonnet-4-5" and provider == "claude"
    finally:
        _reset_routing()


def test_short_turn_routes_to_fast_model():
    """Enabled + fast model set + short message → routed to the fast model."""
    _reset_routing()
    app.set_ai_setting("model_routing_enabled", True)
    app.set_ai_setting("fast_model", FAST_OPENAI)
    app.set_ai_setting("routing_simple_max_chars", 280)
    app._invalidate_ai_control()
    try:
        model, provider = app._route_turn_model("gpt-4o", "openai", "what are your hours?")
        assert model == FAST_OPENAI
        assert provider == "openai"  # inferred from the model-name prefix
    finally:
        _reset_routing()


def test_long_turn_keeps_default_model():
    """A message longer than the simple-turn limit is NOT routed."""
    _reset_routing()
    app.set_ai_setting("model_routing_enabled", True)
    app.set_ai_setting("fast_model", FAST_OPENAI)
    app.set_ai_setting("routing_simple_max_chars", 50)
    app._invalidate_ai_control()
    try:
        model, provider = app._route_turn_model("gpt-4o", "openai", "y" * 200)
        assert model == "gpt-4o" and provider == "openai"
    finally:
        _reset_routing()


def test_blank_fast_model_is_noop():
    """Routing enabled but no fast model configured → identity."""
    _reset_routing()
    app.set_ai_setting("model_routing_enabled", True)
    app.set_ai_setting("fast_model", "")
    app._invalidate_ai_control()
    try:
        model, provider = app._route_turn_model("gpt-4o", "openai", "hi")
        assert model == "gpt-4o" and provider == "openai"
    finally:
        _reset_routing()


def test_unavailable_provider_falls_back_to_default():
    """A fast Claude model is skipped when the Anthropic client isn't initialized."""
    _reset_routing()
    app.set_ai_setting("model_routing_enabled", True)
    app.set_ai_setting("fast_model", "claude-3-5-haiku-latest")
    app.set_ai_setting("routing_simple_max_chars", 280)
    app._invalidate_ai_control()
    saved = app.anthropic_client
    app.anthropic_client = None  # simulate "no Anthropic key"
    try:
        model, provider = app._route_turn_model("gpt-4o", "openai", "hi")
        assert model == "gpt-4o" and provider == "openai"
    finally:
        app.anthropic_client = saved
        _reset_routing()


def test_master_switch_off_forces_identity():
    """The master kill switch forces routing inert even with a DB override on."""
    _reset_routing()
    app.set_ai_setting("model_routing_enabled", True)
    app.set_ai_setting("fast_model", FAST_OPENAI)
    app.set_ai_setting("routing_simple_max_chars", 280)
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    try:
        # get_ai_setting must report the inert (False) value despite the DB row.
        assert app.get_ai_setting("model_routing_enabled") is False
        model, provider = app._route_turn_model("gpt-4o", "openai", "hi")
        assert model == "gpt-4o" and provider == "openai"
    finally:
        _reset_routing()


def test_provider_inference():
    """Model-name prefix maps to the serving provider."""
    assert app._provider_for_model("claude-sonnet-4-5") == "claude"
    assert app._provider_for_model("gpt-4o-mini") == "openai"
    assert app._provider_for_model("o3-mini") == "openai"
    assert app._provider_for_model("") == "openai"


def test_routing_knobs_in_registry():
    """The three knobs are registered so the AI Control tab can manage them."""
    keys = {e["key"] for e in app._ai_control_registry()}
    assert {"model_routing_enabled", "fast_model", "routing_simple_max_chars"} <= keys
