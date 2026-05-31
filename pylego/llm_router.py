"""pylego.llm_router — reliability for the LLM round call, ported from
@altay/llm-router (the *logic*, not the LiteLLM proxy the TS client talks to).

The Admin AI streams each round from one provider. The two reliability gaps:
  * a transient failure (429 / 5xx / timeout / connection reset) while OPENING
    the stream kills the whole turn;
  * if the configured provider is down, there's no fallback.

`reliable_round` addresses both — but ONLY before the first event is yielded.
Once any token has streamed to the user we are committed to that stream (you
can't un-send tokens), so there is no mid-stream retry/fallback. This makes the
wrapper safe: in the common case it behaves exactly like iterating the provider
generator directly.

NON-DISRUPTION: with `max_retries == 0` and a single opener (no fallback), this
is behaviorally identical to `yield from openers[0]()` — same events, same
exception on failure. It only does more when explicitly configured.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Iterable, Iterator, Sequence

# A round "opener" is a zero-arg callable returning a fresh event iterator for
# one provider attempt. We re-call it to retry / fall back.
Opener = Callable[[], Iterable[Any]]


# Substrings / attributes that mark an error as worth retrying. We classify by
# duck-typing (status code) + name, so we don't import any provider SDK here.
_TRANSIENT_NAMES = (
    "timeout", "connection", "apiconnection", "ratelimit", "serviceunavailable",
    "internalserver", "overloaded", "tryagain", "temporarilyunavailable",
)
_TRANSIENT_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}


def is_transient(exc: BaseException) -> bool:
    """Heuristic: is this exception worth a retry / fallback? Conservative —
    unknown errors are treated as NON-transient (we don't retry on, e.g., a 401
    bad-key or a 400 bad-request, which would just fail again)."""
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status, int) and status in _TRANSIENT_STATUS:
        return True
    name = type(exc).__name__.lower()
    if any(tok in name for tok in _TRANSIENT_NAMES):
        return True
    # Some SDKs nest the real error; check the cause chain shallowly.
    cause = getattr(exc, "__cause__", None)
    if cause is not None and cause is not exc:
        cname = type(cause).__name__.lower()
        if any(tok in cname for tok in _TRANSIENT_NAMES):
            return True
    return False


def reliable_round(openers: Sequence[Opener], *,
                   max_retries: int = 0,
                   backoff_base: float = 0.5,
                   sleep: Callable[[float], None] = time.sleep) -> Iterator[Any]:
    """Yield events from the first opener that successfully opens its stream.

    Order of attempts: `openers[0]` is tried `1 + max_retries` times (transient
    failures only, with exponential backoff), then each remaining opener once.
    The first successful `next()` commits us to that stream — all subsequent
    events pass straight through with no further retry/fallback.

    Raises the last exception if every attempt fails. With one opener and
    max_retries=0 this is exactly `yield from openers[0]()`.
    """
    if not openers:
        return
    n = len(openers)
    last_exc: BaseException | None = None
    for oi, opener in enumerate(openers):
        # Primary gets 1 + max_retries attempts; each fallback opener gets one.
        attempts = (1 + max(0, max_retries)) if oi == 0 else 1
        for attempt in range(attempts):
            is_last_overall = (oi == n - 1) and (attempt == attempts - 1)
            try:
                it = iter(opener())
                first = next(it)
            except StopIteration:
                return  # empty stream — treat as a clean, done turn
            except BaseException as e:  # noqa: BLE001 — re-raise or fall through deliberately
                last_exc = e
                if is_last_overall:
                    raise
                if not is_transient(e):
                    break  # non-transient: stop retrying THIS provider, try next opener
                sleep(max(0.0, backoff_base * (2 ** attempt)))
                continue
            # Opened successfully — stream everything, committed (no more retry).
            yield first
            yield from it
            return
    if last_exc is not None:
        raise last_exc
