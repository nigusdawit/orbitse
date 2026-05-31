"""pylego.ratelimit — per-key fixed-window rate limiter, ported from
@altay/rate-limit. Zero hard deps; pluggable store.

Used to protect the Admin AI endpoints from runaway / abusive request floods
once it's live for busy clients. Two stores:
  * MemoryStore — per-process counters (fine for single-worker / dev / tests).
  * PostgresStore — cluster-wide counters in a `pylego_rate_limits` table, so a
    multi-worker / autoscaled gunicorn deploy enforces ONE shared limit.

NON-DISRUPTION:
  * `enabled=False` → `check()` always returns allowed (no DB, no work). This is
    the default, so wiring the limiter changes nothing until an operator opts in.
  * FAIL-OPEN: any store error (DB down, table missing, etc.) is swallowed and
    treated as ALLOWED. A limiter problem must never block a legitimate request.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple


@dataclass
class Decision:
    allowed: bool
    remaining: int
    reset_seconds: int


class MemoryStore:
    """In-process fixed-window counter. Not shared across workers."""

    def __init__(self) -> None:
        self._counts: Dict[Tuple[str, int], int] = {}
        self._lock = threading.Lock()

    def incr(self, key: str, window_start: int, window_seconds: int) -> int:
        with self._lock:
            # Opportunistic prune of old windows to bound memory.
            if len(self._counts) > 10000:
                self._counts = {k: v for k, v in self._counts.items()
                                if k[1] >= window_start - window_seconds}
            ck = (key, window_start)
            self._counts[ck] = self._counts.get(ck, 0) + 1
            return self._counts[ck]


class PostgresStore:
    """Cluster-wide fixed-window counter backed by a tiny table.

    Lazily creates `pylego_rate_limits` on first use (CREATE TABLE IF NOT
    EXISTS — additive, no migration needed). `query_db`/`execute_db` are the
    monolith's helpers, injected so this module has no DB import of its own.
    Every DB error is allowed to propagate to the caller, which fails OPEN.
    """

    def __init__(self, query_db: Callable, execute_db: Callable) -> None:
        self._q = query_db
        self._x = execute_db
        self._ensured = False
        self._lock = threading.Lock()

    def _ensure(self) -> None:
        if self._ensured:
            return
        with self._lock:
            if self._ensured:
                return
            self._x(
                "CREATE TABLE IF NOT EXISTS pylego_rate_limits ("
                " key TEXT NOT NULL, window_start BIGINT NOT NULL, count INT NOT NULL DEFAULT 0,"
                " PRIMARY KEY (key, window_start))")
            self._ensured = True

    def incr(self, key: str, window_start: int, window_seconds: int) -> int:
        self._ensure()
        row = self._x(
            "INSERT INTO pylego_rate_limits (key, window_start, count) "
            "VALUES (%s, %s, 1) "
            "ON CONFLICT (key, window_start) DO UPDATE SET count = pylego_rate_limits.count + 1 "
            "RETURNING count",
            (key, window_start))
        # execute_db returns the RETURNING row (dict) in this codebase.
        if isinstance(row, dict):
            return int(row.get("count") or 1)
        return 1


class RateLimiter:
    """Fixed-window limiter. `check(key)` returns a Decision."""

    def __init__(self, *, limit: int, window_seconds: int, store,
                 enabled: bool = True) -> None:
        self.limit = max(1, int(limit))
        self.window_seconds = max(1, int(window_seconds))
        self.store = store
        self.enabled = enabled

    def check(self, key: str) -> Decision:
        if not self.enabled:
            return Decision(True, self.limit, 0)
        now = int(time.time())
        window_start = now - (now % self.window_seconds)
        reset = window_start + self.window_seconds - now
        try:
            count = self.store.incr(key, window_start, self.window_seconds)
        except Exception:
            # FAIL OPEN — never block a request because the limiter broke.
            return Decision(True, self.limit, reset)
        remaining = max(0, self.limit - count)
        return Decision(count <= self.limit, remaining, reset)


# ---- Process-wide limiter factory ------------------------------------------
# Built once from pylego.config; reused across requests. Postgres store needs
# the monolith's db helpers, so the host wires it via configure().
_LIMITER: Optional[RateLimiter] = None
_LIMITER_LOCK = threading.Lock()
_DB_HELPERS: Optional[Tuple[Callable, Callable]] = None


def configure(query_db: Callable, execute_db: Callable) -> None:
    """Host injects DB helpers (call once at boot). Until called, a postgres-
    store limiter falls back to memory so it can never crash on missing deps."""
    global _DB_HELPERS, _LIMITER
    _DB_HELPERS = (query_db, execute_db)
    _LIMITER = None  # rebuild lazily with the real store


def get_admin_chat_limiter() -> RateLimiter:
    """Return the shared Admin AI limiter built from pylego.config."""
    global _LIMITER
    if _LIMITER is not None:
        return _LIMITER
    with _LIMITER_LOCK:
        if _LIMITER is not None:
            return _LIMITER
        from . import config
        cfg = config.get_config()
        store = None
        if cfg.admin_rate_limit_store == "postgres" and _DB_HELPERS is not None:
            store = PostgresStore(*_DB_HELPERS)
        if store is None:
            store = MemoryStore()
        _LIMITER = RateLimiter(
            limit=cfg.admin_rate_limit_max,
            window_seconds=cfg.admin_rate_limit_window_seconds,
            store=store,
            enabled=cfg.admin_rate_limit_enabled,
        )
        return _LIMITER


def reset_for_tests() -> None:
    global _LIMITER
    _LIMITER = None
