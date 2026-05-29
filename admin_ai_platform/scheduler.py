"""
admin_ai_platform.scheduler
===========================

A tiny, self-contained background tick loop — an independent copy of the
``messaging.py`` scheduler pattern (30s loop, single-start guard). Subsystems
register a callback via ``register_tick`` and the loop calls each one every
``SCHEDULER_TICK_SECONDS``. Used from M3 onward for cost digest, scrape
schedules, automations runner, review collector, RAG reindex.

Kept independent so M0 doesn't depend on relocating ``messaging.py`` yet — when
``messaging`` moves into ``reused/`` (M5) its ``register_tick`` simply delegates
here, so there's one loop per worker.
"""

from __future__ import annotations

import threading
import time as _time

from . import config

_TICK_CALLBACKS: list = []
_started = False
_start_lock = threading.Lock()


def register_tick(fn):
    """Register a zero-arg callback fired every tick. Exceptions are swallowed
    (logged) so one bad job can't kill the loop or the others."""
    if fn not in _TICK_CALLBACKS:
        _TICK_CALLBACKS.append(fn)
    return fn


def _loop():
    interval = max(5, config.SCHEDULER_TICK_SECONDS)
    while True:
        for cb in list(_TICK_CALLBACKS):
            try:
                cb()
            except Exception as e:  # never let one job kill the loop
                print(f"[scheduler] tick callback {getattr(cb, '__name__', cb)} "
                      f"failed: {e}")
        _time.sleep(interval)


def start_scheduler():
    """Start the single background tick thread (idempotent)."""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    t = threading.Thread(target=_loop, name="aap-scheduler", daemon=True)
    t.start()
    print("[scheduler] started", flush=True)
