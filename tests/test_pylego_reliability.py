"""Tests for pylego.llm_router and pylego.ratelimit (task 027).

Headline guarantees:
  * llm_router.reliable_round with one opener + 0 retries == iterating that
    opener directly (the non-disruptive identity case).
  * retry happens only on TRANSIENT failures, only before the first event.
  * fallback switches openers when the primary exhausts.
  * the rate limiter is OFF by default behavior (allows) and FAILS OPEN.
"""
import pytest

from pylego import llm_router as router
from pylego import ratelimit as rl


# ---- llm_router -------------------------------------------------------------

class _Transient(Exception):
    status_code = 503


class _Fatal(Exception):
    status_code = 401  # e.g. bad API key — not retryable


def _gen(*events):
    def _open():
        def g():
            for e in events:
                yield e
        return g()
    return _open


def test_identity_single_opener_no_retries():
    out = list(router.reliable_round([_gen(("token", "a"), ("token", "b"))],
                                     max_retries=0))
    assert out == [("token", "a"), ("token", "b")]


def test_single_opener_failure_propagates_unchanged():
    def _boom():
        raise _Fatal("bad key")
    with pytest.raises(_Fatal):
        list(router.reliable_round([_boom], max_retries=0))


def test_retry_on_transient_then_succeed():
    calls = {"n": 0}
    sleeps = []

    def opener():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Transient("503")
        def g():
            yield ("token", "ok")
        return g()

    out = list(router.reliable_round([opener], max_retries=3,
                                     sleep=sleeps.append))
    assert out == [("token", "ok")]
    assert calls["n"] == 3          # failed twice, succeeded on 3rd
    assert len(sleeps) == 2          # backoff between the two retries


def test_no_retry_on_non_transient():
    calls = {"n": 0}

    def opener():
        calls["n"] += 1
        raise _Fatal("401")

    with pytest.raises(_Fatal):
        list(router.reliable_round([opener], max_retries=5, sleep=lambda s: None))
    assert calls["n"] == 1           # non-transient → no retries wasted


def test_fallback_used_when_primary_fails():
    def primary():
        raise _Transient("primary down")
    out = list(router.reliable_round([primary, _gen(("token", "fb"))],
                                     max_retries=0, sleep=lambda s: None))
    assert out == [("token", "fb")]


def test_no_retry_after_first_event_committed():
    # Once an event is yielded, a later error must propagate (no restart).
    def opener():
        def g():
            yield ("token", "first")
            raise _Transient("mid-stream")
        return g()
    seen = []
    with pytest.raises(_Transient):
        for e in router.reliable_round([opener], max_retries=3, sleep=lambda s: None):
            seen.append(e)
    assert seen == [("token", "first")]


def test_is_transient_classification():
    assert router.is_transient(_Transient()) is True
    assert router.is_transient(_Fatal()) is False
    assert router.is_transient(TimeoutError("x")) is True


# ---- ratelimit --------------------------------------------------------------

def test_memory_limiter_allows_then_blocks():
    lim = rl.RateLimiter(limit=3, window_seconds=60, store=rl.MemoryStore(),
                         enabled=True)
    results = [lim.check("k").allowed for _ in range(5)]
    assert results == [True, True, True, False, False]


def test_disabled_limiter_always_allows():
    lim = rl.RateLimiter(limit=1, window_seconds=60, store=rl.MemoryStore(),
                         enabled=False)
    assert all(lim.check("k").allowed for _ in range(10))


def test_limiter_fails_open_on_store_error():
    class BrokenStore:
        def incr(self, *a, **k):
            raise RuntimeError("db down")
    lim = rl.RateLimiter(limit=1, window_seconds=60, store=BrokenStore(),
                         enabled=True)
    # Even over the limit, a broken store must ALLOW (never block on our bug).
    assert lim.check("k").allowed is True


def test_separate_keys_have_separate_budgets():
    lim = rl.RateLimiter(limit=1, window_seconds=60, store=rl.MemoryStore(),
                         enabled=True)
    assert lim.check("a").allowed is True
    assert lim.check("b").allowed is True
    assert lim.check("a").allowed is False
