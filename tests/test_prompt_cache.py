"""Task 041 — Anthropic prompt caching on the system prompt. Embedded Postgres.

Verifies the `prompt_cache_enabled` AI-Control knob changes the *shape* of the
`system` argument sent to Anthropic:
  * OFF (default) → system is a plain string (current request shape, no change);
  * ON → system is a [{type:text, cache_control:ephemeral}] block list;
  * the master kill switch forces it OFF even with a DB override.

We don't make a live API call — we stub `anthropic_client.messages.stream` to
capture the kwargs `_stream_round_claude` builds, then drain the generator.
"""
import contextlib
import app


class _FakeStream:
    """Captures the kwargs passed to messages.stream and yields no events,
    so draining _stream_round_claude exercises only the request-build path."""
    def __init__(self):
        self.captured = {}

    def __call__(self, **kwargs):
        self.captured = kwargs

        @contextlib.contextmanager
        def _cm():
            yield iter(())  # an empty, iterable "stream"
        return _cm()


class _FakeMessages:
    def __init__(self, stream_fn):
        self.stream = stream_fn


class _FakeAnthropic:
    def __init__(self):
        self._stream = _FakeStream()
        self.messages = _FakeMessages(self._stream)


def _run_round(system="You are a helpful concierge."):
    """Run one _stream_round_claude with a stubbed Anthropic client; return the
    kwargs that would have been sent to messages.stream."""
    fake = _FakeAnthropic()
    saved = app.anthropic_client
    app.anthropic_client = fake
    try:
        # Drain the generator fully so the `with ... stream(**kwargs)` runs.
        for _ in app._stream_round_claude(
                "claude-sonnet-4-5", system,
                [{"role": "user", "content": "hi"}], None):
            pass
        return fake._stream.captured
    finally:
        app.anthropic_client = saved


def _reset():
    for k in ("prompt_cache_enabled", "ai_enhancements_enabled"):
        app.reset_ai_setting(k)
    app._invalidate_ai_control()


def test_default_off_sends_plain_string_system():
    _reset()
    try:
        kwargs = _run_round()
        assert isinstance(kwargs.get("system"), str)
        assert kwargs["system"] == "You are a helpful concierge."
    finally:
        _reset()


def test_enabled_sends_cache_control_block():
    _reset()
    app.set_ai_setting("prompt_cache_enabled", True)
    app._invalidate_ai_control()
    try:
        kwargs = _run_round()
        sysarg = kwargs.get("system")
        assert isinstance(sysarg, list) and len(sysarg) == 1
        block = sysarg[0]
        assert block["type"] == "text"
        assert block["text"] == "You are a helpful concierge."
        assert block["cache_control"] == {"type": "ephemeral"}
    finally:
        _reset()


def test_master_switch_off_forces_plain_string():
    _reset()
    app.set_ai_setting("prompt_cache_enabled", True)
    app.set_ai_setting("ai_enhancements_enabled", False)
    app._invalidate_ai_control()
    try:
        assert app.get_ai_setting("prompt_cache_enabled") is False
        kwargs = _run_round()
        assert isinstance(kwargs.get("system"), str)
    finally:
        _reset()


def test_empty_system_omits_arg():
    """No system prompt → no system kwarg regardless of the cache setting."""
    _reset()
    app.set_ai_setting("prompt_cache_enabled", True)
    app._invalidate_ai_control()
    try:
        kwargs = _run_round(system="")
        assert "system" not in kwargs
    finally:
        _reset()


def test_prompt_cache_on_helper_fails_open():
    """The helper returns a bool and never raises."""
    _reset()
    try:
        assert app._prompt_cache_on() is False
        app.set_ai_setting("prompt_cache_enabled", True)
        app._invalidate_ai_control()
        assert app._prompt_cache_on() is True
    finally:
        _reset()


def test_knob_in_registry():
    keys = {e["key"] for e in app._ai_control_registry()}
    assert "prompt_cache_enabled" in keys
