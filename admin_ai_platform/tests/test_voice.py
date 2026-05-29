"""Unit tests for voice cache-key + per-IP budget (no DB / no network)."""

from admin_ai_platform.blueprints import voice as v


def test_cache_filename_deterministic_and_keyed():
    a = v._cache_filename("hello world", "alloy", "tts-1")
    b = v._cache_filename("hello world", "alloy", "tts-1")
    assert a == b and a.endswith(".mp3")
    # Different voice/model/text → different file.
    assert v._cache_filename("hello world", "echo", "tts-1") != a
    assert v._cache_filename("hello world", "alloy", "tts-1-hd") != a
    assert v._cache_filename("different", "alloy", "tts-1") != a


def test_ip_budget_enforced(monkeypatch):
    from admin_ai_platform import config
    monkeypatch.setattr(config, "VOICE_DAILY_CHAR_CAP", 100)
    v._tts_ip_budget.clear()
    assert v._check_tts_ip_budget("1.2.3.4", 60) is True   # 60/100
    assert v._check_tts_ip_budget("1.2.3.4", 30) is True   # 90/100
    assert v._check_tts_ip_budget("1.2.3.4", 20) is False  # would exceed
    # A different IP has its own budget.
    assert v._check_tts_ip_budget("5.6.7.8", 90) is True


def test_token_roundtrip_and_single_use():
    tok = v._put_token({"text": "hi", "voice": "alloy", "model": "tts-1",
                        "provider": "openai", "filename": "x.mp3", "session_id": ""})
    payload = v._consume_token(tok)
    assert payload and payload["text"] == "hi"
    # One-shot: a second consume returns None.
    assert v._consume_token(tok) is None
    # Unknown token → None.
    assert v._consume_token("nope") is None
