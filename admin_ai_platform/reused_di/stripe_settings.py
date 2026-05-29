"""
admin_ai_platform.reused_di.stripe_settings
============================================

DB-backed runtime settings for the admin Stripe console (relocated + DI-refactored
from the monolith's ``stripe_settings.py``).

State on the single-row ``stripe_settings`` table (id=1):

1. ``mode`` — "test" or "live". Tells ``stripe_client`` which env-var pair to use.
   Defaults to "test" so a fresh install can't accidentally charge real cards.
2. ``autosync_products`` — when True, product CRUD mirrors into the active mode's
   Stripe catalog. Defaults OFF so a broken/missing key doesn't fail the first
   product create.

Plus per-mode health + backfill snapshots for the admin UI.

**Package change vs the monolith original:** instead of ``import app as _app`` the
DB helpers are injected once via :func:`configure` at app startup. Every function
stays exception-safe — a DB outage degrades to sensible defaults.
"""
import json

# Injected by create_app() via configure(); None until then.
_query_db = None
_execute_db = None


def configure(*, query_db, execute_db):
    """Bind the package DB helpers. Called once from create_app()."""
    global _query_db, _execute_db
    _query_db = query_db
    _execute_db = execute_db


_VALID_MODES = ("test", "live")
_DEFAULTS = {
    "mode": "test",
    "autosync_products": False,
    "last_health_check_at": None,
    "last_health_ok": None,
    "last_health_error": "",
    "last_backfill_at": None,
    "last_backfill_summary": {},
}


def _ensure_row():
    """Insert the singleton id=1 row if missing. Never raises."""
    if _execute_db is None:
        return
    try:
        _execute_db(
            "INSERT INTO stripe_settings (id, mode, autosync_products) "
            "VALUES (1, %s, FALSE) ON CONFLICT (id) DO NOTHING",
            (_DEFAULTS["mode"],))
    except Exception as e:
        print(f"[stripe_settings] ensure_row failed: {e}")


def _coerce(row):
    """Normalize a DB row into a stable shape for callers."""
    out = dict(_DEFAULTS)
    if not row:
        return out
    out["mode"] = (row.get("mode") or "test").lower()
    if out["mode"] not in _VALID_MODES:
        out["mode"] = "test"
    out["autosync_products"] = bool(row.get("autosync_products"))
    out["last_health_check_at"] = (row["last_health_check_at"].isoformat()
                                   if row.get("last_health_check_at") else None)
    if row.get("last_health_ok") is None:
        out["last_health_ok"] = None
    else:
        out["last_health_ok"] = bool(row["last_health_ok"])
    out["last_health_error"] = row.get("last_health_error") or ""
    out["last_backfill_at"] = (row["last_backfill_at"].isoformat()
                               if row.get("last_backfill_at") else None)
    raw = row.get("last_backfill_summary")
    if isinstance(raw, dict):
        out["last_backfill_summary"] = raw
    elif isinstance(raw, str):
        try:
            out["last_backfill_summary"] = json.loads(raw)
        except Exception:
            out["last_backfill_summary"] = {}
    else:
        out["last_backfill_summary"] = {}
    return out


def get_settings():
    """Current settings dict; always usable even if the DB is unreachable."""
    if _query_db is None:
        return dict(_DEFAULTS)
    try:
        _ensure_row()
        row = _query_db(
            "SELECT mode, autosync_products, last_health_check_at, last_health_ok, "
            "       last_health_error, last_backfill_at, last_backfill_summary "
            "FROM stripe_settings WHERE id = 1", fetchone=True)
        return _coerce(row)
    except Exception as e:
        print(f"[stripe_settings] get_settings failed: {e}")
        return dict(_DEFAULTS)


def get_mode():
    """Just the current mode string ('test' or 'live')."""
    return get_settings()["mode"]


def set_mode(mode):
    """Persist the mode toggle. Raises ValueError on an invalid mode."""
    mode = (mode or "").lower().strip()
    if mode not in _VALID_MODES:
        raise ValueError(f"mode must be one of {_VALID_MODES}, got {mode!r}")
    _ensure_row()
    _execute_db("UPDATE stripe_settings SET mode = %s, updated_at = NOW() WHERE id = 1",
                (mode,))
    return mode


def set_autosync(enabled):
    """Persist the auto-sync toggle. Returns the new bool."""
    flag = bool(enabled)
    _ensure_row()
    _execute_db("UPDATE stripe_settings SET autosync_products = %s, updated_at = NOW() "
                "WHERE id = 1", (flag,))
    return flag


def record_health(ok, error=""):
    """Stamp the last health-check result. Never raises."""
    if _execute_db is None:
        return
    try:
        _ensure_row()
        _execute_db(
            "UPDATE stripe_settings SET last_health_check_at = NOW(), last_health_ok = %s, "
            "last_health_error = %s, updated_at = NOW() WHERE id = 1",
            (bool(ok), (error or "")[:1000]))
    except Exception as e:
        print(f"[stripe_settings] record_health failed: {e}")


def record_backfill(summary):
    """Stamp the last backfill summary dict. Never raises."""
    if _execute_db is None:
        return
    try:
        _ensure_row()
        _execute_db(
            "UPDATE stripe_settings SET last_backfill_at = NOW(), "
            "last_backfill_summary = %s::jsonb, updated_at = NOW() WHERE id = 1",
            (json.dumps(summary or {}),))
    except Exception as e:
        print(f"[stripe_settings] record_backfill failed: {e}")
