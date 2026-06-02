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

import json  # used by _vp_as_list (relocated data utility, Track B)
import os
import sys
import threading
import time as _time  # used by tenant_has_feature TTL (feature subsystem)
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


# =============================================================================
# TENANCY  (moved verbatim from app.py - Track B / B1)
# =============================================================================
# Every tenant-scoped query goes through this resolver rather than hard-coding 1,
# so blueprints need it too. Self-contained (no deps); re-exported by app.py.
def current_tenant_id():
    """Return the active tenant id for this request.

    For now there is exactly one tenant (id=1); later we'll resolve from
    the request host or admin session. All call-sites should use this
    rather than hard-coding 1.
    """
    return 1


# =============================================================================
# DATA UTILITIES  (moved verbatim from app.py - Track B helper relocation)
# =============================================================================
# Pure leaf helpers (no app/DB/AI deps) that admin-CRUD blueprints share. Moved
# here so a blueprint route can import them without `from app` (circular). The
# many app.py call sites keep resolving via app.py's `from core import` re-export.
def _vp_as_list(v):
    """JSONB may come back as a parsed list (psycopg2) or, defensively, a JSON
    string. Always return a list."""
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v:
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


# ---- service serializers (Track B helper relocation; shared by admin/commerce.py
# AND the public service/booking routes that remain in app.py, so they live in
# core and are re-exported via app.py's `from core import` block). Clean leaves:
# only dict/isoformat (pure) and query_db (core). ----
def _service_to_dict(row):
    """Coerce DB row to a JSON-friendly dict (keeps int cents, ISO times)."""
    if not row:
        return None
    d = dict(row)
    for k, v in list(d.items()):
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


def _addon_rows(service_id: int):
    return query_db(
        "SELECT * FROM service_addons WHERE service_id = %s "
        "AND is_active = TRUE ORDER BY sort_order ASC, id ASC",
        (service_id,),
    ) or []


def _hydrate_service(svc_row):
    """Attach the active addon list to a single service dict."""
    if not svc_row:
        return None
    d = _service_to_dict(svc_row)
    d["addons"] = [_service_to_dict(a) for a in _addon_rows(d["id"])]
    return d


# ---- row ISO-date coercer (Track B helper relocation; pure leaf, shared by the
# admin/crm.py read APIs AND ~8 other app.py routes, so it lives in core and is
# re-exported via app.py's `from core import` block). dict + isoformat only. ----
def _iso_row(r, *date_cols):
    d = dict(r)
    for k in date_cols:
        if d.get(k):
            d[k] = d[k].isoformat()
    return d

# =============================================================================
# FEATURE-FLAG SUBSYSTEM  (moved verbatim from app.py - Track B)
# =============================================================================
# The per-tenant capability registry + its tiny TTL cache + the lookup/flip
# functions + the route-prefix gate. Moved here so admin blueprints (tenant/
# features management) and the cost gate can import them without `from app`
# (circular). app.py re-exports every name below via its `from core import`
# block, so init_db()'s seed loop, velo_handlers' lazy `from app import
# _FEATURE_REGISTRY/_FEATURE_NAMES/list_tenant_features/set_tenant_feature`,
# the health/catalog readers, and _compose_scope_paragraph (still in app.py)
# all keep resolving unchanged.
#
# MUTABLE CACHE: _FEATURE_CACHE is read AND rebound (invalidate_* sets it to a
# fresh dict). Both readers (tenant_has_feature) and the rebinder (invalidate_
# tenant_features_cache) live HERE together, so the rebind is always seen. No
# code outside core reads the raw dict.
#
# The @app.before_request registration STAYS in app.py (it binds to `app`);
# only its body lives here as enforce_feature_flags(), called by the thin
# wrapper left behind in app.py.
# =============================================================================

# (feature_name, human_label, plan_tier_required, default_enabled, group)
_FEATURE_REGISTRY = [
    # Website builder (the public marketing-site editor surface). Turn this OFF
    # for "client" installs that only want the AI concierge + its admin — the
    # before_request hook then 403s every website-builder admin route. Defaults
    # ON so existing operator installs are completely unaffected.
    ("website_builder",      "Website builder (themes/pages/SEO/sections)", "solo", True, "Website"),
    # Core (always on for paid plans)
    ("site_themes",          "Site Themes",                  "solo",       True,  "Design"),
    ("site_designs",         "Multi-Homepage Designs",       "growth",     True,  "Design"),
    # AI capabilities
    ("deck_launch",          "Presentation deck launches",   "growth",     True,  "AI"),
    ("web_search",           "Web search tool",              "growth",     True,  "AI"),
    ("voice",                "Voice agent (TTS / STT)",      "growth",     True,  "AI"),
    ("generated_pages",      "AI-generated pages",           "growth",     True,  "AI"),
    ("agent_scope_slider",   "Agent scope tightness slider", "growth",     True,  "AI"),
    # Capabilities
    ("custom_forms",         "Custom forms",                 "solo",       True,  "Capabilities"),
    ("mcp",                  "MCP connectors",               "enterprise", True,  "Capabilities"),
    ("presentations",        "Presentations admin",          "growth",     True,  "Capabilities"),
    ("automations",          "Automations builder",          "growth",     True,  "Capabilities"),
    ("messaging",            "Email & SMS messaging",        "growth",     True,  "Capabilities"),
    ("chat_history",         "Chat history & transcripts",   "solo",       True,  "Capabilities"),
    # Analytics
    ("analytics",            "Analytics dashboard",          "growth",     True,  "Analytics"),
    ("cost_dashboard",       "Cost transparency dashboard",  "growth",     True,  "Analytics"),
    ("weekly_digest",        "Weekly AI activity digest",    "growth",     True,  "Analytics"),

    # ---- Per-tab visibility flags (added for super-admin/client tab control) ----
    # One on/off switch per admin tab that previously had no flag. These drive
    # which tabs a CLIENT login sees; the super admin bypasses gating and always
    # sees every tab. Defaults below apply ONLY to the client.
    #
    # Client-safe content/AI tabs — default ON (a client sees them unless the
    # super admin turns them off).
    ("business_info",        "Business info",                "solo",       True,  "Content"),
    ("gallery_cards",        "Gallery cards",                "solo",       True,  "Content"),
    ("experiences",          "Experiences",                  "solo",       True,  "Content"),
    ("pricing",              "Pricing",                      "solo",       True,  "Content"),
    ("testimonials",         "Testimonials",                 "solo",       True,  "Content"),
    ("team",                 "Team",                         "solo",       True,  "Content"),
    ("faq",                  "FAQ",                          "solo",       True,  "Content"),
    ("blog",                 "Blog",                         "solo",       True,  "Content"),
    ("events",               "Events",                       "solo",       True,  "Content"),
    ("services",             "Services",                     "solo",       True,  "Content"),
    ("media",                "Media library",                "solo",       True,  "Content"),
    ("scraper",              "Web scraper",                  "growth",     True,  "Content"),
    ("products",             "Products",                     "solo",       True,  "Store"),
    ("orders",               "Orders",                       "solo",       True,  "Store"),
    ("reviews",              "Reviews (destinations/requests/insights)", "growth", True, "Reviews"),
    ("dashboards",           "Custom dashboards",            "growth",     True,  "Insights"),
    ("marketing_insights",   "Marketing insights",           "growth",     True,  "Insights"),
    ("admin_chat",           "Admin AI chat",                "solo",       True,  "AI"),
    ("chatbot",              "Chatbot settings",             "solo",       True,  "AI"),
    ("knowledge_cache",      "Knowledge cache (RAG)",        "growth",     True,  "AI"),
    ("skills",               "Skills registry",              "growth",     True,  "AI"),
    ("custom_skills",        "Custom skills",                "growth",     True,  "AI"),
    ("recent_changes",       "Recent changes log",           "solo",       True,  "System"),
    #
    # Sensitive owner tabs — default OFF for clients (a client doesn't see them
    # until the super admin explicitly enables them). The super admin always
    # sees them. Several are ALSO behind the SUPER_ADMIN_KEY unlock-key step-up.
    ("secrets",              "Secrets / env vars",           "solo",       False, "System"),
    ("developer",            "Developer console",            "growth",     False, "System"),
    ("performance",          "Performance tools",            "growth",     False, "System"),
    ("snapshot",             "Snapshot / clone",             "growth",     False, "System"),
    ("fleet",                "Fleet sync / VELO",            "enterprise", False, "System"),
    ("llm_provider",         "LLM provider selector",        "growth",     False, "AI"),
    ("stripe",               "Stripe / billing config",      "growth",     False, "Billing"),
]
_FEATURE_NAMES = {row[0] for row in _FEATURE_REGISTRY}
_FEATURE_DEFAULTS = {row[0]: row[3] for row in _FEATURE_REGISTRY}

# CLIENT_MODE — a one-switch "this install is a client, not the operator" flag.
# When truthy, operator-only features default OFF, so a fresh client install has
# the website-builder surface disabled with no manual toggling. Operators leave
# CLIENT_MODE unset → every default stays exactly as before (fully unaffected).
# Per-tenant overrides in the Plans & Features tab still win over these defaults.
_OPERATOR_ONLY_FEATURES = ("website_builder",)
_CLIENT_MODE = os.environ.get("CLIENT_MODE", "").strip().lower() in ("1", "true", "yes", "on")
if _CLIENT_MODE:
    for _f in _OPERATOR_ONLY_FEATURES:
        _FEATURE_DEFAULTS[_f] = False

# Per-process cache of {(tenant_id, feature_name): enabled_bool, expires_at}.
# Tiny TTL so flag flips become visible quickly across requests without
# hammering the DB on every tool dispatch.
_FEATURE_CACHE = {}
_FEATURE_CACHE_TTL_SEC = 30

def invalidate_tenant_features_cache(tenant_id=None):
    """Drop cached feature lookups so flag flips take effect immediately."""
    global _FEATURE_CACHE
    if tenant_id is None:
        _FEATURE_CACHE = {}
    else:
        _FEATURE_CACHE = {k: v for k, v in _FEATURE_CACHE.items() if k[0] != tenant_id}


def _ensure_tenant_feature_row(tenant_id, feature_name):
    """Lazy-seed a tenant_features row using the registry default.

    Idempotent: ON CONFLICT DO NOTHING. Called from tenant_has_feature
    when the row is missing so we never have to bulk-seed on startup.
    """
    default_enabled = _FEATURE_DEFAULTS.get(feature_name, True)
    try:
        execute_db(
            "INSERT INTO tenant_features (tenant_id, feature_name, enabled) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (tenant_id, feature_name) DO NOTHING",
            (tenant_id, feature_name, default_enabled),
        )
    except Exception as e:
        print(f"[features] could not lazy-seed {feature_name}: {e}")


def tenant_has_feature(name, tenant_id=None):
    """Return True if `name` is enabled for the given tenant.

    Unknown feature names default to True so adding a new gate to the
    code without an immediate registry update never breaks production.
    The first lookup of a known feature for a tenant inserts the
    enabled=registry-default row, so the Plans & Features tab can then
    flip it.
    """
    if tenant_id is None:
        tenant_id = current_tenant_id()
    cache_key = (tenant_id, name)
    cached = _FEATURE_CACHE.get(cache_key)
    now = _time.time()
    if cached is not None and cached[1] > now:
        return cached[0]

    if name not in _FEATURE_NAMES:
        # Unknown gate — fail OPEN so we never silently break something.
        _FEATURE_CACHE[cache_key] = (True, now + _FEATURE_CACHE_TTL_SEC)
        return True

    try:
        row = query_db(
            "SELECT enabled FROM tenant_features "
            "WHERE tenant_id = %s AND feature_name = %s",
            (tenant_id, name),
            fetchone=True,
        )
        if row is None:
            _ensure_tenant_feature_row(tenant_id, name)
            enabled = _FEATURE_DEFAULTS.get(name, True)
        else:
            enabled = bool(row.get("enabled"))
    except Exception as e:
        print(f"[features] tenant_has_feature({name}) failed: {e}; failing open")
        enabled = True

    _FEATURE_CACHE[cache_key] = (enabled, now + _FEATURE_CACHE_TTL_SEC)
    return enabled

def list_tenant_features(tenant_id=None):
    """Return the full feature roster for the Plans & Features UI.

    Walks _FEATURE_REGISTRY (canonical order/grouping) and joins each
    with the tenant_features.enabled value (lazy-seeding any missing
    rows). Returns a list of dicts ready to render.
    """
    if tenant_id is None:
        tenant_id = current_tenant_id()
    out = []
    for name, label, plan_tier, default_enabled, group in _FEATURE_REGISTRY:
        enabled = tenant_has_feature(name, tenant_id)
        out.append({
            "name": name,
            "label": label,
            "plan_tier": plan_tier,
            "default_enabled": default_enabled,
            "group": group,
            "enabled": enabled,
        })
    return out

def set_tenant_feature(name, enabled, tenant_id=None, note=""):
    """Flip a feature on/off for a tenant. Returns the new value."""
    if tenant_id is None:
        tenant_id = current_tenant_id()
    if name not in _FEATURE_NAMES:
        raise ValueError(f"Unknown feature: {name}")
    execute_db(
        "INSERT INTO tenant_features (tenant_id, feature_name, enabled, note) "
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (tenant_id, feature_name) DO UPDATE "
        "SET enabled = EXCLUDED.enabled, note = EXCLUDED.note, updated_at = NOW()",
        (tenant_id, name, bool(enabled), note or ""),
    )
    invalidate_tenant_features_cache(tenant_id)
    return bool(enabled)

# Route-prefix → feature_name map. The before_request hook below blocks
# any HTTP request whose path starts with one of these prefixes when
# the tenant doesn't have the feature enabled. Order matters — more
# specific prefixes should come before broader ones, but here the
# prefixes don't overlap so the order is alphabetic for clarity.
_FEATURE_ROUTE_PREFIXES = [
    ("/admin/api/analytics",       "analytics"),
    ("/admin/api/automations",     "automations"),
    ("/admin/api/chat-history",    "chat_history"),
    ("/admin/api/forms",           "custom_forms"),
    ("/admin/api/generated-pages", "generated_pages"),
    ("/admin/api/mcp/",            "mcp"),
    ("/admin/api/messaging",       "messaging"),
    ("/admin/api/presentations",   "presentations"),
    ("/admin/api/site-designs",    "site_designs"),
    ("/admin/api/site-themes",     "site_themes"),
    ("/admin/api/voice",           "voice"),
    ("/api/forms/",                "custom_forms"),
    ("/api/generated-pages",       "generated_pages"),
    ("/api/presentations/",        "presentations"),
    ("/api/voice/",                "voice"),
    # Website-builder (marketing-site editor) admin routes — gated as a unit by
    # the `website_builder` flag so a client install has the whole site-builder
    # surface disabled at the route layer while keeping the AI concierge admin.
    # NOTE: deliberately EXCLUDES AI-referenced content the concierge reads
    # (blog/team/faq/testimonials/experiences/pricing/business-info) and
    # /admin/api/marketing (= Marketing Insights, an AI feature).
    ("/admin/api/theme",             "website_builder"),
    ("/admin/api/curated-font-pairs", "website_builder"),
    ("/admin/api/site-settings",     "website_builder"),
    ("/admin/api/page-sections",     "website_builder"),
    ("/admin/api/pages",             "website_builder"),
    ("/admin/api/custom-sections",   "website_builder"),
    ("/admin/api/section-visibility", "website_builder"),
    ("/admin/api/seo",               "website_builder"),
    ("/admin/api/social-links",      "website_builder"),
    ("/admin/api/sphere-images",     "website_builder"),
    ("/admin/api/sphere-settings",   "website_builder"),
    ("/admin/api/video-gallery",     "website_builder"),
    ("/admin/api/podcast",           "website_builder"),
    ("/admin/api/reorder",           "website_builder"),
    # ---- Per-tab content/store/AI/system gating (super-admin/client control) ----
    # One entry per tab flag added to the registry above, so a CLIENT whose flag
    # is off gets the standard feature_disabled response on the tab's admin API.
    # The super admin bypasses all of this (see _enforce_feature_flags). Prefixes
    # are exact enough to avoid startswith collisions (note the trailing slash on
    # /admin/api/chat/ so it does NOT catch chat-history or chatbot-settings).
    ("/admin/api/business-info",   "business_info"),
    ("/admin/api/gallery-cards",   "gallery_cards"),
    ("/admin/api/experiences",     "experiences"),
    ("/admin/api/pricing",         "pricing"),
    ("/admin/api/testimonials",    "testimonials"),
    ("/admin/api/team",            "team"),
    ("/admin/api/faq",             "faq"),
    ("/admin/api/blog",            "blog"),
    ("/admin/api/events",          "events"),
    ("/admin/api/event-rsvps",     "events"),
    ("/admin/api/services",        "services"),
    ("/admin/api/media",           "media"),
    ("/admin/api/scrape",          "scraper"),   # scrape-jobs / scrape-schedules / scraper-settings
    ("/admin/api/products",        "products"),
    ("/admin/api/orders",          "orders"),
    ("/admin/api/reviews",         "reviews"),
    ("/admin/api/dashboards",      "dashboards"),
    ("/admin/api/marketing",       "marketing_insights"),
    ("/admin/api/chat/",           "admin_chat"),     # trailing slash: admin AI chat only
    ("/admin/api/chatbot-settings", "chatbot"),
    ("/admin/api/kb/",             "knowledge_cache"),
    ("/admin/api/skills",          "skills"),
    ("/admin/api/llm-provider",    "llm_provider"),
    ("/admin/api/stripe",          "stripe"),
    ("/admin/api/snapshots",       "snapshot"),
    # Sensitive owner tabs that ALSO sit behind the SUPER_ADMIN_KEY unlock-key.
    # The feature flag (default OFF for clients) gates tab visibility + gives a
    # clean feature_disabled before the unlock check; the unlock-key remains the
    # second factor for the super admin.
    ("/admin/api/secrets",         "secrets"),
    ("/admin/api/devconsole",      "developer"),
    ("/admin/api/performance",     "performance"),

    # Public ingress for the automations webhook trigger. We DO gate this
    # one — if a tenant turns Automations off, third-party services hitting
    # the saved hook URL should get a 404 (not silently consume the post).
    ("/automations/hook/",         "automations"),
]

# Startup safety net: every feature referenced by a route-prefix gate MUST exist
# in the registry. tenant_has_feature() fails OPEN on unknown names, so a typo in
# a prefix→feature mapping would silently leave a (possibly sensitive) tab's API
# reachable by clients. Fail loudly at import instead.
_unknown_prefix_features = sorted(
    {feature for _prefix, feature in _FEATURE_ROUTE_PREFIXES if feature not in _FEATURE_NAMES}
)
if _unknown_prefix_features:
    raise RuntimeError(
        "_FEATURE_ROUTE_PREFIXES references features not in _FEATURE_REGISTRY: "
        + ", ".join(_unknown_prefix_features)
        + " — add them to the registry (they would otherwise fail OPEN and leave "
        "the tab's API reachable by clients)."
    )

def enforce_feature_flags():
    """Reject requests to disabled-feature endpoints with a 403.

    Runs before every Flask-handled request. If the path starts with
    a prefix in _FEATURE_ROUTE_PREFIXES and the tenant doesn't have
    that feature, we return a small JSON 403 explaining which flag
    is off — the admin can re-enable it from the Plans & Features tab.

    GET requests get a friendlier 404 so we don't expose feature
    structure to public visitors poking at the site.
    """
    # The super admin (platform owner) manages everything and is never gated by
    # feature flags — they see and use every tab regardless of flag state. This
    # bypass is SAFE for anon/public traffic because _is_super_admin() requires a
    # logged-in session (anonymous visitors and client sessions fall through to
    # the normal gating below).
    if _is_super_admin():
        return None
    try:
        path = request.path or ""
    except Exception:
        return None
    for prefix, feature in _FEATURE_ROUTE_PREFIXES:
        if path.startswith(prefix):
            if not tenant_has_feature(feature):
                if request.method == "GET" and not path.startswith("/admin/"):
                    # Don't leak feature names to anonymous visitors.
                    return jsonify({"error": "not_found"}), 404
                return jsonify({
                    "error": "feature_disabled",
                    "feature": feature,
                    "message": f"This feature ({feature}) is currently turned off for this site. "
                                "Enable it in Admin → Plans & Features.",
                }), 403
            break
    return None
