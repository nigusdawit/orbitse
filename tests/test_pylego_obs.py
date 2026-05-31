"""Tests for pylego.obs — the observability wrapper for the Admin AI.

The headline guarantee under test: observe_admin_turn is STRICTLY ADDITIVE.
It yields exactly the events it receives, in order, whether enabled or not, and
it never swallows the wrapped generator's own errors. These pin the
"only enhance, never disturb" contract.
"""
import os

import pytest

from pylego import config, obs


def _set(enabled: bool):
    os.environ["PYLEGO_OBS_ENABLED"] = "1" if enabled else "0"
    # No Langfuse keys → local-logging path only (no external calls in tests).
    os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
    os.environ.pop("LANGFUSE_SECRET_KEY", None)
    config.reload_config()


SAMPLE = [
    {"type": "token", "content": "Hel"},
    {"type": "token", "content": "lo"},
    {"type": "tool_start", "tool": {"id": "1", "name": "admin_list_tables"}},
    {"type": "tool_end", "tool": {"id": "1", "rows": 3, "ms": 12}},
    {"type": "usage", "prompt_tokens": 100, "completion_tokens": 20},
    {"type": "done", "content": "Hello"},
]


@pytest.mark.parametrize("enabled", [True, False])
def test_passthrough_is_byte_identical(enabled):
    _set(enabled)
    out = list(obs.observe_admin_turn({"session_id": "s1"}, iter(SAMPLE)))
    assert out == SAMPLE  # same objects, same order, nothing added/removed


def test_disabled_is_pure_passthrough_even_with_garbage_events():
    _set(False)
    weird = [{"type": "token"}, 42, None, {"no_type": 1}, {"type": "done", "content": "x"}]
    out = list(obs.observe_admin_turn({"session_id": "s"}, iter(weird)))
    assert out == weird


def test_enabled_tally_never_breaks_on_malformed_events():
    _set(True)
    # Non-dict events must pass through untouched and not raise.
    weird = [{"type": "usage", "prompt_tokens": "notanint"}, "raw-string",
             {"type": "done", "content": "ok"}]
    out = list(obs.observe_admin_turn({"session_id": "s"}, iter(weird)))
    assert out == weird


def test_underlying_generator_error_is_reraised_not_swallowed():
    _set(True)

    def boom():
        yield {"type": "token", "content": "hi"}
        raise RuntimeError("loop exploded")

    seen = []
    with pytest.raises(RuntimeError, match="loop exploded"):
        for evt in obs.observe_admin_turn({"session_id": "s"}, boom()):
            seen.append(evt)
    # The pre-error event still streamed through (no buffering/blocking).
    assert seen == [{"type": "token", "content": "hi"}]


def test_early_consumer_close_does_not_raise_out_of_obs():
    _set(True)
    gen = obs.observe_admin_turn({"session_id": "s"}, iter(SAMPLE))
    assert next(gen) == SAMPLE[0]
    gen.close()  # simulate client disconnect; must not raise


def test_persist_fn_receives_record_and_is_failopen():
    _set(True)
    got = {}

    def persist(record):
        got.update(record)

    events = [
        {"type": "tool_start", "tool": {"id": "1"}},
        {"type": "usage", "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                                    "model": "gpt-4o-mini", "provider": "openai",
                                    "cost_usd": 0.001}},
        {"type": "done", "content": "the answer"},
    ]
    out = list(obs.observe_admin_turn(
        {"session_id": "s9", "user_message": "the question"}, iter(events),
        persist_fn=persist))
    assert out == events                       # pass-through intact
    # The record carries the FIXED nested-usage tally + content.
    assert got["tokens_in"] == 100 and got["tokens_out"] == 20
    assert got["model"] == "gpt-4o-mini" and got["provider"] == "openai"
    assert got["tool_calls"] == 1 and got["rounds"] == 1
    assert got["user_message"] == "the question"
    assert got["final_answer"] == "the answer"
    assert abs(got["cost_usd"] - 0.001) < 1e-9


def test_persist_fn_failure_never_breaks_stream():
    _set(True)

    def boom(record):
        raise RuntimeError("db down")

    out = list(obs.observe_admin_turn({"session_id": "s"}, iter(SAMPLE),
                                      persist_fn=boom))
    assert out == SAMPLE                        # persist error swallowed


def test_redact_disabled_keeps_content_verbatim():
    _set(True)
    got = {}
    events = [{"type": "done", "content": "email me at a@b.com"}]
    list(obs.observe_admin_turn(
        {"session_id": "s", "user_message": "ping a@b.com"}, iter(events),
        persist_fn=lambda r: got.update(r), redact_enabled=False))
    assert "a@b.com" in got["final_answer"]     # redaction off → verbatim
    list(obs.observe_admin_turn(
        {"session_id": "s", "user_message": "ping a@b.com"},
        iter([{"type": "done", "content": "email me at a@b.com"}]),
        persist_fn=lambda r: got.update(r), redact_enabled=True))
    assert "a@b.com" not in got["final_answer"]  # redaction on → masked


def test_backend_failure_inside_emit_is_swallowed(monkeypatch):
    _set(True)
    # Make the logging backend blow up. _emit must swallow it so the chat
    # stream still completes normally — observability can never break a turn.
    def boom(*a, **k):
        raise ValueError("backend down")
    monkeypatch.setattr(obs._log, "info", boom)
    out = list(obs.observe_admin_turn({"session_id": "s"}, iter(SAMPLE)))
    assert out == SAMPLE  # stream unaffected despite the backend error
