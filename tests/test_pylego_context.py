"""Tests for pylego.history (token-trim) and pylego.respcache (task 028)."""
from pylego import history as H
from pylego import respcache as RC


# ---- history.trim_to_budget -------------------------------------------------

def _msgs():
    return [
        {"role": "system", "content": "SYS " * 50},          # keep (head)
        {"role": "user", "content": "old q1 " * 50},
        {"role": "assistant", "content": "old a1 " * 50},
        {"role": "user", "content": "old q2 " * 50},
        {"role": "assistant", "content": "old a2 " * 50},
        {"role": "user", "content": "CURRENT question"},      # keep (tail)
    ]


def test_budget_zero_is_identity():
    m = _msgs()
    assert H.trim_to_budget(m, 0) is m


def test_already_fits_is_unchanged():
    m = [{"role": "user", "content": "hi"}]
    assert H.trim_to_budget(m, 100000) is m


def test_trim_drops_oldest_keeps_system_and_current():
    m = _msgs()
    out = H.trim_to_budget(m, 120)  # small budget forces trimming
    assert out[0]["role"] == "system"                 # head preserved
    assert out[-1]["content"] == "CURRENT question"   # current turn preserved
    assert H.total_tokens(out) <= H.total_tokens(m)
    assert len(out) < len(m)                          # something was dropped


def test_trim_never_leaves_a_leading_tool_message():
    m = [
        {"role": "system", "content": "s"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "result " * 80},
        {"role": "user", "content": "now"},
    ]
    out = H.trim_to_budget(m, 20)
    # The middle (assistant+tool) should be dropped together; no orphan tool.
    middle = out[1:-1]
    assert all(x.get("role") != "tool" for x in middle) or not middle


def test_estimate_tokens_monotonic():
    assert H.estimate_tokens("") == 0
    assert H.estimate_tokens("a" * 400) >= H.estimate_tokens("a" * 40)


def test_summarize_fn_replaces_dropped_block():
    m = _msgs()
    calls = {"dropped": None}

    def summarize(dropped):
        calls["dropped"] = dropped
        return "- recap point one\n- recap point two"

    out = H.trim_to_budget(m, 120, summarize_fn=summarize)
    assert calls["dropped"], "summarize_fn should receive the dropped messages"
    # A summary system note is present in place of the dropped middle.
    joined = " ".join(str(x.get("content", "")) for x in out)
    assert "Summary of earlier conversation" in joined
    assert "recap point one" in joined
    assert out[0]["role"] == "system" and out[-1]["content"] == "CURRENT question"


def test_summarize_fn_failure_falls_back_to_plain_drop():
    m = _msgs()

    def boom(dropped):
        raise RuntimeError("summarizer down")

    out = H.trim_to_budget(m, 120, summarize_fn=boom)
    joined = " ".join(str(x.get("content", "")) for x in out)
    assert "Summary of earlier conversation" not in joined   # fell back to drop
    assert out[0]["role"] == "system" and out[-1]["content"] == "CURRENT question"
    assert H.total_tokens(out) <= H.total_tokens(m)


def test_summarize_none_is_identical_to_plain_drop():
    m = _msgs()
    assert H.trim_to_budget(m, 120) == H.trim_to_budget(m, 120, summarize_fn=None)


# ---- respcache --------------------------------------------------------------

def _embed(text):
    # Tiny deterministic "embedding": bag-of-3-buckets by char code. Identical
    # text → identical vector; similar text → similar vector. Enough for tests.
    v = [0.0, 0.0, 0.0]
    for ch in text.lower():
        v[ord(ch) % 3] += 1.0
    return v


def test_disabled_cache_is_noop():
    c = RC.ResponseCache(embed_fn=_embed, store=RC.InMemoryStore(), enabled=False)
    assert c.store_answer("q", "a") is False
    assert c.lookup("q") is None


def test_store_then_lookup_hit():
    c = RC.ResponseCache(embed_fn=_embed, store=RC.InMemoryStore(),
                         enabled=True, threshold=0.99)
    assert c.store_answer("how do I write a good prompt?", "Be specific.") is True
    assert c.lookup("how do I write a good prompt?") == "Be specific."


def test_lookup_miss_below_threshold():
    c = RC.ResponseCache(embed_fn=_embed, store=RC.InMemoryStore(),
                         enabled=True, threshold=0.999)
    c.store_answer("aaaaaa", "answer-A")
    # A very different question should not meet the high threshold.
    assert c.lookup("zzzzzzzzzz bbb ccc") is None


def test_pii_answers_are_not_cached():
    c = RC.ResponseCache(embed_fn=_embed, store=RC.InMemoryStore(),
                         enabled=True, threshold=0.9)
    assert c.store_answer("contact?", "Email me at a@b.com") is False
    assert c.store_answer("key?", "use sk-ABCDEF12345 as the token") is False
    assert c.lookup("contact?") is None


def test_content_version_isolates_cache():
    store = RC.InMemoryStore()
    v1 = RC.ResponseCache(embed_fn=_embed, store=store, enabled=True,
                          threshold=0.99, content_version="v1")
    v1.store_answer("q", "old answer")
    v2 = RC.ResponseCache(embed_fn=_embed, store=store, enabled=True,
                          threshold=0.99, content_version="v2")
    assert v2.lookup("q") is None          # version bump hides old rows
    assert v1.lookup("q") == "old answer"


def test_threshold_is_clamped():
    c = RC.ResponseCache(embed_fn=_embed, store=RC.InMemoryStore(),
                         enabled=True, threshold=2.0)
    assert 0.80 <= c.threshold <= 0.99


def test_embed_failure_fails_open():
    def boom(_):
        raise RuntimeError("embeddings down")
    c = RC.ResponseCache(embed_fn=boom, store=RC.InMemoryStore(), enabled=True)
    assert c.lookup("q") is None          # no crash
    assert c.store_answer("q", "a") is False
