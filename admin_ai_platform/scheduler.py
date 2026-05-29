"""
admin_ai_platform.scheduler
===========================

Background tick loop. Subsystems register a zero-arg callback via
``register_tick``; the loop calls each every ``SCHEDULER_TICK_SECONDS``.

**Multi-worker safety:** under gunicorn every worker would otherwise run every
tick. So the loop only fires callbacks when this process holds a Postgres
**session advisory lock** (`pg_try_advisory_lock`). Exactly one worker becomes
the leader; the others idle and re-try the lock each cycle, so leadership fails
over automatically if the leader dies. The lock connection is dedicated (not
pooled) so the session — and thus the lock — stays held.
"""

from __future__ import annotations

import threading
import time as _time

import psycopg2

from . import config

_TICK_CALLBACKS: list = []
_started = False
_start_lock = threading.Lock()


def register_tick(fn):
    """Register a zero-arg callback fired every tick (when this worker is the
    scheduler leader). Exceptions are swallowed so one bad job can't kill the
    loop or the others."""
    if fn not in _TICK_CALLBACKS:
        _TICK_CALLBACKS.append(fn)
    return fn


def _acquire_leader_conn():
    """Open a dedicated connection and try to grab the advisory lock. Returns the
    connection if WE are the leader, else closes it and returns None."""
    if not config.DATABASE_URL:
        return None
    try:
        conn = psycopg2.connect(config.DATABASE_URL)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (config.SCHEDULER_ADVISORY_LOCK_KEY,))
            got = cur.fetchone()[0]
        if got:
            return conn
        conn.close()
        return None
    except Exception as e:
        print(f"[scheduler] leader lock attempt failed: {e}")
        return None


def _loop():
    interval = max(5, config.SCHEDULER_TICK_SECONDS)
    leader_conn = None
    while True:
        if leader_conn is None:
            leader_conn = _acquire_leader_conn()
        if leader_conn is not None:
            # Verify the connection/lock is still alive; drop leadership if not.
            try:
                with leader_conn.cursor() as cur:
                    cur.execute("SELECT 1")
            except Exception:
                try:
                    leader_conn.close()
                except Exception:
                    pass
                leader_conn = None
        if leader_conn is not None:
            for cb in list(_TICK_CALLBACKS):
                try:
                    cb()
                except Exception as e:
                    print(f"[scheduler] tick {getattr(cb, '__name__', cb)} failed: {e}")
        _time.sleep(interval)


def start_scheduler():
    """Start the single background tick thread (idempotent)."""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, name="aap-scheduler", daemon=True).start()
    print("[scheduler] started (leader-elected via advisory lock)", flush=True)
