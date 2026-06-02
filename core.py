"""core.py - shared infrastructure extracted from app.py (Track B / B1).

WHY THIS FILE EXISTS
  app.py is being de-monolithed into Flask blueprints (admin/*.py). Those
  blueprints need the shared plumbing (DB access; later: auth, the feature
  subsystem, the LLM clients) but they MUST NOT `import app` - app.py imports
  THEM, so that would be a circular import. core.py is the bottom layer they
  can all import safely:

      state.py  ->  core.py  ->  admin/*.py  ->  app.py (registers blueprints)

  RULE: core.py must never import app. Keep it free of any app dependency.
  app.py re-exports every public name defined here, so `app.query_db(...)`, the
  lazy `from app import query_db` used by velo_handlers/velo_endpoints/scraper,
  and the test suite all keep resolving unchanged.

WHAT'S HERE (B1, first slice)
  The process-wide PostgreSQL connection pool + the three helpers every route
  uses: get_db() / query_db() / execute_db(). Moved verbatim from app.py
  (comments intact) - no behaviour change. init_db() and the migrations stay in
  app.py and are explicitly out of scope (see the refactor plan's DB guardrail).
"""

import os
import sys
import threading
from functools import wraps

import psycopg2
import psycopg2.extras
import psycopg2.extensions  # _PooledConnection subclasses psycopg2.extensions.connection
from flask import session, request, jsonify, redirect, url_for  # used by the auth gates (below)

# Database connection string. core reads it straight from the environment - the
# same value app.py reads into its own DATABASE_URL - so the DB helpers below are
# fully self-contained and importable by blueprints without touching app.py.
DATABASE_URL = os.environ.get("DATABASE_URL")


# =============================================================================
# DATABASE HELPERS  (moved verbatim from app.py - Track B / B1)
# =============================================================================
# -----------------------------------------------------------------------------
# Connection pool (Tier 7)
# -----------------------------------------------------------------------------
# Process-wide pool so we don't pay TCP+auth setup on every request. Each
# gunicorn worker gets its own pool. Defaults are tuned for Replit autoscale
# under bursty traffic (see _resolve_pool_sizes); operators on managed
# Postgres with low max_connections should override DB_POOL_MAX to keep
# total in-flight connections (= max * num_app_instances) under their cap.
# Falls back to a direct connection if the pool is unavailable or exhausted,
# so a misconfiguration never breaks the app — it just degrades to the
# pre-pool behaviour.
import psycopg2.pool as _psql_pool

_DB_POOL = None
_DB_POOL_LOCK = threading.Lock()
_DB_POOL_DISABLED = False


def _resolve_pool_sizes(env=None):
    """Resolve (min, max) Postgres pool sizes from env vars with sensible
    defaults for an autoscale Flask deployment.

    Defaults: min=2, max=20.
      - min=2 (vs the old min=1): keeps a warm spare connection so a
        traffic burst doesn't pay TCP+TLS+auth handshake (~30-150 ms on
        managed Postgres) on the FIRST request of every cold worker.
        On Replit autoscale, instances are spun up on demand and serve
        traffic in waves — a min=1 pool means every wave's first request
        eats the cold-connection tax. Two warm conns covers the common
        case of a page request firing two queries in parallel without
        any wait.
      - max=20 (vs the old max=10): the app fans out per request — a
        single page-bundle response can run 8-12 queries, and concurrent
        users multiply that. A 10-cap was hitting `_psql_pool.PoolError`
        on bursty traffic and falling back to direct-connect (which is
        slower than just having had a bigger pool to begin with). 20 is
        well under managed-Postgres caps for a single app instance.

    Validation: min is clamped to >= 1 (psycopg2 requires it); max is
    clamped to >= min so a misconfig like DB_POOL_MAX=5 with the new
    default min=2 doesn't error at construction. Empty strings (the
    common operator mistake of `export DB_POOL_MAX=` with no value)
    fall back to the documented defaults via `or "<default>"`. Truly
    invalid values (DB_POOL_MIN=banana) raise a ValueError at startup
    with a message naming the offending var and value — silent
    fallback to the default would hide the misconfiguration for
    weeks, fail-loud is the right policy for an infra knob."""
    env = env if env is not None else os.environ
    min_val = max(1, _parse_pool_int(env, "DB_POOL_MIN", "2"))
    max_val = max(min_val, _parse_pool_int(env, "DB_POOL_MAX", "20"))
    return min_val, max_val


def _parse_pool_int(env, var_name, default):
    """Parse an integer from env with an operator-friendly error message.
    Wraps `int()` so a typo like `DB_POOL_MAX=banana` produces a
    diagnostic that says exactly which var and which value, rather than
    psycopg2's bare `invalid literal for int()` traceback at startup."""
    raw = env.get(var_name, default) or default
    try:
        return int(raw)
    except (ValueError, TypeError) as e:
        raise ValueError(
            f"[db pool] env var {var_name}={raw!r} is not a valid integer. "
            f"Set it to a positive integer (e.g. {var_name}={default}) or "
            f"unset it to use the default ({default})."
        ) from e


_DB_POOL_MIN, _DB_POOL_MAX = _resolve_pool_sizes()


def _direct_connect():
    """Un-pooled connection. Used by the get_db() fallback path only.
    Closes for real (no pool involvement) so a fallback under pool exhaustion
    doesn't accumulate."""
    return psycopg2.connect(DATABASE_URL)


class _PooledConnection(psycopg2.extensions.connection):
    """psycopg2 connection subclass whose `.close()` returns to the pool.

    psycopg2's C-level connection forbids reassigning `.close` as an
    instance attribute, so we override it via a subclass and pass the
    subclass to the pool via `connection_factory=`. This way every
    existing `conn.close()` call site returns the connection to the pool
    instead of closing it.

    Re-entrancy guard: ThreadedConnectionPool.putconn() *itself* calls
    `conn.close()` internally to discard a connection when the pool is
    full or the conn is in an unknown txn state. Without the
    `_closing_directly` flag we'd recurse into putconn forever — close
    is the very symptom that brought us in. When that flag is set we
    fall straight through to the real close().
    """
    _pool = None  # set right after pool construction in _init_db_pool()

    def close(self):
        # Re-entrancy guard: pool internally calls .close() on overflow/discard.
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
                # Already dead — tell the pool to discard cleanly.
                try:
                    pool.putconn(self, close=True)
                    return
                except Exception:
                    pass
            else:
                # Reset state so a handler that left autocommit=False or
                # an open transaction cannot poison the next borrower.
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
            # putconn raised — fall through to real close so we don't leak.
            super().close()
        finally:
            self._closing_directly = False


def _init_db_pool():
    """Lazily initialise the process-wide pool. Returns the pool or None on failure."""
    global _DB_POOL, _DB_POOL_DISABLED
    if _DB_POOL_DISABLED:
        return None
    if _DB_POOL is not None:
        return _DB_POOL
    with _DB_POOL_LOCK:
        if _DB_POOL is None and not _DB_POOL_DISABLED:
            try:
                _DB_POOL = _psql_pool.ThreadedConnectionPool(
                    _DB_POOL_MIN, _DB_POOL_MAX, DATABASE_URL,
                    connection_factory=_PooledConnection,
                )
                # Wire the subclass back to the pool so close() can find it.
                _PooledConnection._pool = _DB_POOL
                print(
                    f"[db pool] initialised (min={_DB_POOL_MIN}, max={_DB_POOL_MAX})",
                    file=sys.stderr,
                )
            except Exception as e:
                print(
                    f"[db pool] init failed, falling back to per-request connections: {e}",
                    file=sys.stderr,
                )
                _DB_POOL_DISABLED = True
                return None
    return _DB_POOL


def get_db():
    """
    Borrow a Postgres connection from the process-wide pool.

    The returned connection is a `_PooledConnection` whose `.close()`
    returns it to the pool — every existing `try: ... finally: conn.close()`
    call site works unchanged. Falls back to a fresh direct connection if
    the pool is unavailable or exhausted, so the app never hard-fails on
    a pool misconfiguration.

    Callers create cursors with `cursor_factory=psycopg2.extras.RealDictCursor`
    explicitly (matches the pre-pool convention used throughout this file).
    """
    pool = _init_db_pool()
    if pool is not None:
        try:
            conn = pool.getconn()
            # Defence: if Postgres killed the conn while it was idle in the
            # pool, discard it and grab another rather than handing the
            # caller a dead handle that errors on first use.
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
            print(f"[db pool] exhausted, falling back to direct connect: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[db pool] borrow error, falling back to direct connect: {e}", file=sys.stderr)
    # Fallback: behave exactly like the pre-pool implementation.
    fallback = _direct_connect()
    fallback.autocommit = True
    return fallback


def query_db(sql, params=None, fetchone=False):
    """
    Execute a SQL query and return results as a list of dicts (or a single dict).

    Args:
        sql (str): The SQL query to execute.
        params (tuple, optional): Parameters to safely inject into the query.
        fetchone (bool): If True, return only the first row.

    Returns:
        list[dict] or dict or None: Query results.
    """
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                rows = cur.fetchall()
                result = [dict(row) for row in rows]
                return result[0] if fetchone and result else result
            return None
    finally:
        conn.close()


def execute_db(sql, params=None):
    """
    Execute a SQL statement that modifies data (INSERT, UPDATE, DELETE).
    Returns the number of rows affected, or the new row for INSERT...RETURNING.

    Args:
        sql (str): The SQL statement to execute.
        params (tuple, optional): Parameters to safely inject.

    Returns:
        dict or int: The returned row (if RETURNING is used) or affected row count.
    """
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                # RETURNING with zero affected rows yields no row — return None
                # so callers can use a simple `if not result:` guard instead of
                # crashing with TypeError on dict(None). Existing callers
                # already treat the value as truthy/falsy.
                row = cur.fetchone()
                return dict(row) if row is not None else None
            return cur.rowcount
    finally:
        conn.close()


# =============================================================================
# AUTH GATES  (moved verbatim from app.py - Track B / B1)
# Self-contained: only Flask session/request primitives. url_for("admin_login")
# resolves at REQUEST time against whatever app the route is registered on, so
# admin_login staying in app.py is fine. The LOGIN handlers + lockout caches
# (_LOGIN_ATTEMPTS / _SUPER_ADMIN_ATTEMPTS) remain in app.py.
# =============================================================================
def admin_required(f):
    """
    Decorator that protects a route with admin authentication.

    For HTML page routes: redirects to the login page if not logged in
    (so the user sees the familiar password form).

    For JSON API routes (anything under /admin/api/* or any request that
    explicitly accepts JSON / sends JSON / is XHR): returns a JSON 401
    instead of a redirect. Without this the browser fetch silently
    follows the 302 to /admin/login, the response body is HTML, and the
    dashboard JS shows a generic "Could not save settings" error after
    the admin's session expires — extremely confusing for the user.
    Returning a real 401 lets the dashboard prompt for re-login cleanly.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin_logged_in"):
            wants_json = (
                request.path.startswith("/admin/api/")
                or request.is_json
                or "application/json" in (request.headers.get("Accept") or "")
                or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            )
            if wants_json:
                return jsonify({"error": "Admin session expired. Please log in again.", "auth_required": True}), 401
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated_function


def _is_super_admin():
    """True only for a logged-in session whose role is super_admin.

    The role lives server-side in the signed Flask session (set at login /
    SSO), so it can't be forged client-side. Two non-obvious rules:

    * MUST be logged-in. We deliberately AND on `admin_logged_in` so that an
      anonymous/public request (which has no session role) returns False — the
      `"super_admin"` default below is only ever reached by a session that is
      already logged in. This matters because `_enforce_feature_flags` early-
      returns for super-admins; if anon callers defaulted to super_admin the
      feature gates (incl. the anon-GET 404-leak guard and the public
      automations-webhook gate) would stop applying to the public.
    * Missing role defaults to super_admin — back-compat for sessions that were
      established before roles existed (those are the operator's own).

    Drives: feature-flag bypass (super admin sees/uses everything), the
    Plans & Features tab, and the feature-toggle endpoint guard. Distinct from
    the SUPER_ADMIN_KEY unlock-key step-up, which stays as-is.
    """
    if not session.get("admin_logged_in"):
        return False
    return session.get("admin_role", "super_admin") == "super_admin"


def _require_super_admin_role():
    """Return a 403 JSON response if the session is not the super-admin role,
    else None. Used to hard-gate the feature-control endpoints so a client
    session can never change what it was granted (the template hiding the tab
    is cosmetic; THIS is the real boundary)."""
    if not _is_super_admin():
        return jsonify({
            "error": "super_admin_role_required",
            "message": "Only the super admin can manage feature visibility.",
        }), 403
    return None
