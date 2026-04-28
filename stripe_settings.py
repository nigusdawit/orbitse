"""
DB-backed runtime settings for the admin Stripe console.

Two pieces of state live here, both keyed off the single-row
`stripe_settings` table (id=1):

1. `mode` — "test" or "live". Tells stripe_client which env-var pair
   to consult when constructing the Stripe SDK client. Defaults to
   "test" so a fresh install can never accidentally charge real cards
   before the operator has explicitly flipped to live.

2. `autosync_products` — when True, POST/PUT/DELETE on the local
   /admin/api/products routes also mirrors the change into the active
   mode's Stripe Product+Price catalog. Defaults to OFF so a fresh
   install with broken / missing Stripe keys doesn't fail the admin's
   first product create.

Plus per-mode health snapshot (`last_health_*`) and per-mode backfill
summary so the admin UI can show "last checked OK 12s ago" / "last
backfill: 14 ok, 1 failed, 28 minutes ago" without re-probing.

EVERY function here is exception-safe. A DB outage / missing table /
malformed row degrades to a sensible default — admins can still hit
the Stripe tab even if this layer is broken.
"""
import json
from datetime import datetime, timezone

import app as _app


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
    try:
        _app.execute_db(
            "INSERT INTO stripe_settings (id, mode, autosync_products) "
            "VALUES (1, %s, FALSE) "
            "ON CONFLICT (id) DO NOTHING",
            (_DEFAULTS["mode"],),
        )
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
    out["last_health_check_at"] = (
        row["last_health_check_at"].isoformat()
        if row.get("last_health_check_at") else None
    )
    if row.get("last_health_ok") is None:
        out["last_health_ok"] = None
    else:
        out["last_health_ok"] = bool(row["last_health_ok"])
    out["last_health_error"] = row.get("last_health_error") or ""
    out["last_backfill_at"] = (
        row["last_backfill_at"].isoformat()
        if row.get("last_backfill_at") else None
    )
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
    """Return the current settings dict. Always returns a usable dict
    even if the table is missing, the row hasn't been seeded yet, or
    the DB is unreachable — falls back to the defaults in that case."""
    try:
        _ensure_row()
        row = _app.query_db(
            "SELECT mode, autosync_products, last_health_check_at, "
            "       last_health_ok, last_health_error, last_backfill_at, "
            "       last_backfill_summary "
            "FROM stripe_settings WHERE id = 1",
            fetchone=True,
        )
        return _coerce(row)
    except Exception as e:
        print(f"[stripe_settings] get_settings failed: {e}")
        return dict(_DEFAULTS)


def get_mode():
    """Convenience: just the current mode string ('test' or 'live')."""
    return get_settings()["mode"]


def set_mode(mode):
    """Persist the mode toggle. Returns the new mode string. Raises
    ValueError on an invalid mode (callers validate user input first
    to surface a clean 400)."""
    mode = (mode or "").lower().strip()
    if mode not in _VALID_MODES:
        raise ValueError(f"mode must be one of {_VALID_MODES}, got {mode!r}")
    _ensure_row()
    _app.execute_db(
        "UPDATE stripe_settings "
        "SET mode = %s, updated_at = NOW() "
        "WHERE id = 1",
        (mode,),
    )
    return mode


def set_autosync(enabled):
    """Persist the auto-sync toggle. Returns the new bool."""
    flag = bool(enabled)
    _ensure_row()
    _app.execute_db(
        "UPDATE stripe_settings "
        "SET autosync_products = %s, updated_at = NOW() "
        "WHERE id = 1",
        (flag,),
    )
    return flag


def record_health(ok, error=""):
    """Stamp the last health-check result. Never raises."""
    try:
        _ensure_row()
        _app.execute_db(
            "UPDATE stripe_settings "
            "SET last_health_check_at = NOW(), "
            "    last_health_ok = %s, "
            "    last_health_error = %s, "
            "    updated_at = NOW() "
            "WHERE id = 1",
            (bool(ok), (error or "")[:1000]),
        )
    except Exception as e:
        print(f"[stripe_settings] record_health failed: {e}")


def record_backfill(summary):
    """Stamp the last backfill summary dict. Never raises."""
    try:
        _ensure_row()
        _app.execute_db(
            "UPDATE stripe_settings "
            "SET last_backfill_at = NOW(), "
            "    last_backfill_summary = %s::jsonb, "
            "    updated_at = NOW() "
            "WHERE id = 1",
            (json.dumps(summary or {}),),
        )
    except Exception as e:
        print(f"[stripe_settings] record_backfill failed: {e}")
