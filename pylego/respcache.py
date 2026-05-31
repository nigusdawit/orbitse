"""pylego.respcache — semantic response cache, ported from
@altay/semantic-response-cache.

Embeds the QUESTION, stores the ANSWER as text. A near-duplicate question
(cosine >= threshold, same content-version) reuses the stored answer instead of
calling the LLM again.

WHY IT'S SAFE FOR THE ADMIN AI (the staleness concern):
  * The CALLER decides what to store. The Admin AI wiring stores an answer ONLY
    when the turn used NO tools — i.e. a pure-LLM, non-data-dependent answer
    (e.g. "how do I write a good system prompt?"). Data-dependent admin queries
    always invoke a tool, so they are never stored and therefore never served
    from cache. This makes the cache self-limiting to safe, static answers.
  * `content_version` is part of the key: bump it (e.g. when the prompt/catalog
    changes) and the whole cache becomes invisible — no manual purge.
  * A PII/secret check runs on the ANSWER before storing; anything flagged is
    refused (a global-ish cache must not leak one context's data to another).
  * `enabled=False` (default) → lookup/store are no-ops. Every error is
    swallowed (fail-open): a cache problem can never break or alter a turn.
"""

from __future__ import annotations

import math
import re
import threading
import time
from typing import Callable, List, Optional, Tuple

# A conservative PII/secret heuristic for the ANSWER. Refuse to cache responses
# that look like they contain an email, a long digit run (card/phone/id), or an
# obvious secret token. Better to skip caching than to risk a cross-context leak.
_PII_PATTERNS = [
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),         # email
    re.compile(r"\b\d[\d ()+-]{8,}\d\b"),             # long digit run (phone/card/id)
    re.compile(r"\b(sk|pk|rk)[-_][A-Za-z0-9]{8,}\b"),  # api-key-ish token
    re.compile(r"(?i)\b(password|secret|api[_-]?key|token)\b\s*[:=]"),
]


def default_pii_check(text: str) -> bool:
    """Return True if the text looks like it contains PII/secrets (=> don't cache)."""
    if not text:
        return False
    return any(p.search(text) for p in _PII_PATTERNS)


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class InMemoryStore:
    """Per-process cosine store. Bounded; oldest entries evicted past max_rows.
    (Cross-worker sharing is a future swap-in — same interface, pgvector-backed.)"""

    def __init__(self, max_rows: int = 2000) -> None:
        self._rows: List[Tuple[List[float], str, str, float]] = []  # (vec, answer, version, ts)
        self._max = max_rows
        self._lock = threading.Lock()

    def search(self, vec: List[float], version: str) -> Optional[Tuple[str, float]]:
        best: Optional[Tuple[str, float]] = None
        with self._lock:
            rows = list(self._rows)
        for v, ans, ver, _ts in rows:
            if ver != version:
                continue
            sim = _cosine(vec, v)
            if best is None or sim > best[1]:
                best = (ans, sim)
        return best

    def put(self, vec: List[float], answer: str, version: str) -> None:
        with self._lock:
            self._rows.append((vec, answer, version, time.time()))
            if len(self._rows) > self._max:
                self._rows = self._rows[-self._max:]


class ResponseCache:
    def __init__(self, *, embed_fn: Callable[[str], List[float]], store,
                 enabled: bool = False, threshold: float = 0.93,
                 content_version: str = "v1",
                 pii_check: Callable[[str], bool] = default_pii_check) -> None:
        self.embed_fn = embed_fn
        self.store = store
        self.enabled = enabled
        # Clamp threshold to a sane band (mirrors the TS package).
        self.threshold = min(0.99, max(0.80, float(threshold)))
        self.content_version = content_version
        self.pii_check = pii_check

    def lookup(self, question: str) -> Optional[str]:
        """Return a cached answer for a near-duplicate question, else None.
        Never raises."""
        if not self.enabled or not question:
            return None
        try:
            vec = self.embed_fn(question)
            if not vec:
                return None
            hit = self.store.search(vec, self.content_version)
            if hit and hit[1] >= self.threshold:
                return hit[0]
        except Exception:
            return None
        return None

    def store_answer(self, question: str, answer: str) -> bool:
        """Cache an answer for a question. Returns True if stored. Refuses to
        cache empty answers or anything that looks like it contains PII/secrets.
        Never raises."""
        if not self.enabled or not question or not answer:
            return False
        try:
            if self.pii_check and self.pii_check(answer):
                return False
            vec = self.embed_fn(question)
            if not vec:
                return False
            self.store.put(vec, answer, self.content_version)
            return True
        except Exception:
            return False
