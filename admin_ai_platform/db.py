"""
admin_ai_platform.db
====================

PostgreSQL access layer for the package — an *independent copy* of the
connection-pool + ``query_db``/``execute_db`` helpers from the original
``app.py`` (~lines 603-862). It does not import from ``app.py``; the package
owns its own pool so it can run as a standalone process.

Design (carried over verbatim in behaviour):
  * One process-wide ``ThreadedConnectionPool`` per worker.
  * ``_PooledConnection.close()`` returns the connection to the pool instead of
    closing it, so every ``try/finally: conn.close()`` call site works.
  * Falls back to a direct connection if the pool can't be built or is
    exhausted, so a misconfiguration degrades rather than hard-fails.
  * Cursors use ``RealDictCursor`` so rows come back as dicts.
"""

from __future__ import annotations

import sys
import threading

import psycopg2
import psycopg2.extras
import psycopg2.pool as _psql_pool

from . import config

# Module-global pool state (mirrors the original app.py globals).
_DB_POOL = None
_DB_POOL_LOCK = threading.Lock()
_DB_POOL_DISABLED = False


def _database_url() -> str:
    """Resolve the DSN at call time so tests can monkeypatch ``config``."""
    url = config.DATABASE_URL
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not configured. Set it in the environment before "
            "using the database layer."
        )
    return url


def _direct_connect():
    """Un-pooled connection used only by the get_db() fallback path. Closes for
    real (no pool involvement) so a fallback under pool exhaustion doesn't
    accumulate."""
    return psycopg2.connect(_database_url())


class _PooledConnection(psycopg2.extensions.connection):
    """psycopg2 connection subclass whose ``.close()`` returns to the pool.

    psycopg2's C connection forbids reassigning ``.close`` per-instance, so we
    override via a subclass passed as ``connection_factory=``. The
    ``_closing_directly`` re-entrancy guard prevents infinite recursion when
    ``ThreadedConnectionPool.putconn()`` internally calls ``.close()`` to
    discard a connection.
    """

    _pool = None  # wired right after pool construction in _init_db_pool()

    def close(self):
        if getattr(self, "_closing_directly", False):
            super().close()
            return
        pool = type(self)._pool
        if pool is None:
            super().close()
            return
        try:
            self._closing_directly = True
            if self.closed:
                try:
                    pool.putconn(self, close=True)
                    return
                except Exception:
                    pass
            else:
                # Reset txn state so a handler that left autocommit=False or an
                # open transaction cannot poison the next borrower.
                try:
                    if not self.autocommit:
                        self.rollback()
                except Exception:
                    pass
                try:
                    self.autocommit = True
                except Exception:
                    pass
                try:
                    pool.putconn(self)
                    return
                except Exception:
                    pass
            super().close()
        finally:
            self._closing_directly = False


def _init_db_pool():
    """Lazily initialise the process-wide pool. Returns the pool or None on
    failure (in which case callers fall back to direct connections)."""
    global _DB_POOL, _DB_POOL_DISABLED
    if _DB_POOL_DISABLED:
        return None
    if _DB_POOL is not None:
        return _DB_POOL
    with _DB_POOL_LOCK:
        if _DB_POOL is None and not _DB_POOL_DISABLED:
            try:
                _DB_POOL = _psql_pool.ThreadedConnectionPool(
                    config.DB_POOL_MIN,
                    max(config.DB_POOL_MIN, config.DB_POOL_MAX),
                    _database_url(),
                    connection_factory=_PooledConnection,
                )
                _PooledConnection._pool = _DB_POOL
                print(
                    f"[db pool] initialised (min={config.DB_POOL_MIN}, "
                    f"max={config.DB_POOL_MAX})",
                    file=sys.stderr,
                )
            except Exception as e:
                print(
                    f"[db pool] init failed, falling back to per-request "
                    f"connections: {e}",
                    file=sys.stderr,
                )
                _DB_POOL_DISABLED = True
                return None
    return _DB_POOL


def get_db():
    """Borrow a connection from the pool (autocommit on), with a direct-connect
    fallback so the app never hard-fails on a pool misconfiguration."""
    pool = _init_db_pool()
    if pool is not None:
        try:
            conn = pool.getconn()
            if getattr(conn, "closed", 0):
                try:
                    pool.putconn(conn, close=True)
                except Exception:
                    pass
                conn = pool.getconn()
            try:
                conn.autocommit = True
            except Exception:
                pass
            return conn
        except _psql_pool.PoolError as e:
            print(f"[db pool] exhausted, direct connect: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[db pool] borrow error, direct connect: {e}", file=sys.stderr)
    fallback = _direct_connect()
    fallback.autocommit = True
    return fallback


def query_db(sql, params=None, fetchone=False):
    """Run a SELECT and return list[dict] (or a single dict when ``fetchone``)."""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                rows = cur.fetchall()
                result = [dict(row) for row in rows]
                if fetchone:
                    # Return the single row or None (never [] — callers rely on
                    # `if row is None` / truthiness to detect "no row").
                    return result[0] if result else None
                return result
            return None
    finally:
        conn.close()


def execute_db(sql, params=None):
    """Run an INSERT/UPDATE/DELETE. Returns the RETURNING row (dict) if present,
    else the affected row count. Returns None for RETURNING with zero rows."""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                row = cur.fetchone()
                return dict(row) if row is not None else None
            return cur.rowcount
    finally:
        conn.close()


def reset_pool_for_tests():
    """Test hook: drop pool state so a new DATABASE_URL takes effect."""
    global _DB_POOL, _DB_POOL_DISABLED
    with _DB_POOL_LOCK:
        if _DB_POOL is not None:
            try:
                _DB_POOL.closeall()
            except Exception:
                pass
        _DB_POOL = None
        _DB_POOL_DISABLED = False
        _PooledConnection._pool = None
