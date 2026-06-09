"""Vapi slice 3 — concierge custom-LLM bridge. Embedded Postgres (no DB mocks).

/api/vapi/llm/chat/completions wraps the concierge brain in an OpenAI-compatible shape for Vapi
custom-LLM. It is FAIL-CLOSED (requires a bearer secret — never an open LLM proxy). The LLM round
is monkeypatched (Anthropic is an external API, not the DB) to assert the OpenAI wrapping +
streaming format; the prompt assembly (get_prompt + paragraphs + KB) runs for real (KB fails open).
"""
import os

import app

_URL = "/api/vapi/llm/chat/completions"


def _fake_round(*a, **k):
    yield ("token", "Hi ")
    yield ("token", "there")
    yield ("usage", {"provider": "claude", "model": "claude-test", "prompt_tokens": 10, "completion_tokens": 3})
    yield ("finish", "stop")


def test_llm_not_configured_503():
    os.environ.pop("VAPI_LLM_SECRET", None)
    os.environ.pop("VAPI_WEBHOOK_SECRET", None)
    r = app.app.test_client().post(_URL, json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 503


def test_llm_requires_bearer():
    os.environ["VAPI_LLM_SECRET"] = "llmsecret"
    try:
        c = app.app.test_client()
        assert c.post(_URL, json={"messages": []}).status_code == 401
        assert c.post(_URL, headers={"Authorization": "Bearer wrong"}, json={"messages": []}).status_code == 401
    finally:
        os.environ.pop("VAPI_LLM_SECRET", None)


def test_llm_non_streaming_openai_shape():
    os.environ["VAPI_LLM_SECRET"] = "llmsecret"
    orig_round, orig_prov = app._stream_round_claude, app.get_active_llm_provider
    app._stream_round_claude = _fake_round
    app.get_active_llm_provider = lambda: ("claude", "claude-test")
    try:
        r = app.app.test_client().post(_URL, headers={"Authorization": "Bearer llmsecret"},
                                       json={"messages": [{"role": "user", "content": "hello"}], "stream": False})
        assert r.status_code == 200
        d = r.get_json()
        assert d["object"] == "chat.completion"
        assert d["choices"][0]["message"]["content"] == "Hi there"
        assert d["choices"][0]["finish_reason"] == "stop"
    finally:
        app._stream_round_claude, app.get_active_llm_provider = orig_round, orig_prov
        os.environ.pop("VAPI_LLM_SECRET", None)


def test_llm_streaming_chunks():
    os.environ["VAPI_LLM_SECRET"] = "llmsecret"
    orig_round, orig_prov = app._stream_round_claude, app.get_active_llm_provider
    app._stream_round_claude = _fake_round
    app.get_active_llm_provider = lambda: ("claude", "claude-test")
    try:
        r = app.app.test_client().post(_URL, headers={"Authorization": "Bearer llmsecret"},
                                       json={"messages": [{"role": "user", "content": "hello"}], "stream": True})
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "chat.completion.chunk" in body
        assert "Hi " in body and "there" in body
        assert "data: [DONE]" in body
    finally:
        app._stream_round_claude, app.get_active_llm_provider = orig_round, orig_prov
        os.environ.pop("VAPI_LLM_SECRET", None)
