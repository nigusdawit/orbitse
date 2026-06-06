"""admin/shell.py — Workspaces shell chrome: cross-cutting read APIs (task 093, gap §0).

P1 = GET /admin/api/nav-counts: live badge counts for the Workspaces sub-nav, keyed by
each tab's data-testid so the front-end (workspaces.js `navItem`) maps straight onto its
items.

Strictly additive + FAIL-OPEN: every count is its own try/except (a missing/unmigrated
table → that key is simply omitted, never a 500), and the route returns {"counts": {...}}
even on total failure. A 30s in-process TTL cache (one slot per privilege level) keeps the
header poll off the DB. PII domains (leads / CRM) are counted ONLY for a super-admin
session — the route is `@admin_required` (which only proves "an admin is logged in"), so
the PII gate is enforced IN-BODY via `_is_super_admin()`, mirroring admin/crm.py's
super-admin discipline.

Silo deploy (one DB per tenant; all rows tenant_id=1) → a plain COUNT(*) already IS the
tenant's count, so no tenant filter is needed for these aggregates.

Imports come from core (never app — that would be circular). Registered in app.py via
app.register_blueprint(shell_bp), right after crm_bp.
"""
import time

from flask import Blueprint, jsonify

from core import query_db, admin_required, _is_super_admin

shell_bp = Blueprint("shell", __name__)

# (testid, table, pii). Table names are HARD-CODED here (never user input), so they're
# safe to interpolate into the COUNT query. pii=True domains hold visitor PII and are
# counted only for a super-admin (same boundary admin/crm.py enforces on the full rows).
_COUNT_SOURCES = (
    ("tab-crm",           "leads",              True),
    ("tab-chat-history",  "chat_conversations", False),
    ("tab-orders",        "orders",             False),
    ("tab-products",      "products",           False),
    ("tab-pages",         "pages",              False),
    ("tab-offers",        "offers",             False),
    ("tab-forms",         "form_submissions",   False),
    ("tab-messaging",     "subscribers",        False),
    ("tab-blog",          "blog_posts",         False),
    ("tab-events",        "events",             False),
    ("tab-automations",   "automations",        False),
)

# 30s TTL cache, one slot per privilege level (super vs not — the PII domains differ).
# Mirrors app.py's _CHAT_ONLY_CACHE val/ts idiom; 30s is our deliberate choice (the
# chat-only precedent is 10s).
_NAV_COUNTS_TTL_SEC = 30.0
_NAV_COUNTS_CACHE = {}  # bool(is_super) -> {"val": dict, "ts": float}


def _count_table(table):
    """COUNT(*) for one HARD-CODED table name; None on any error (fail-open)."""
    try:
        row = query_db("SELECT COUNT(*) AS n FROM " + table, fetchone=True)
        if isinstance(row, dict):
            return int(row.get("n") or 0)
    except Exception:
        return None
    return None


def _compute_counts(is_super):
    """Build the testid->count map, skipping PII domains for non-super sessions and
    omitting any domain whose count errored (fail-open)."""
    out = {}
    for testid, table, pii in _COUNT_SOURCES:
        if pii and not is_super:
            continue
        n = _count_table(table)
        if n is not None:
            out[testid] = n
    return out


@shell_bp.route("/admin/api/nav-counts", methods=["GET"])
@admin_required
def admin_nav_counts():
    """Live sub-nav badge counts keyed by tab data-testid. 30s-cached per privilege
    level; fully fail-open (always returns {"counts": {...}})."""
    try:
        is_super = bool(_is_super_admin())
    except Exception:
        is_super = False
    now = time.time()
    slot = _NAV_COUNTS_CACHE.get(is_super)
    if slot and slot.get("val") is not None and (now - slot["ts"]) < _NAV_COUNTS_TTL_SEC:
        return jsonify({"counts": slot["val"]})
    try:
        counts = _compute_counts(is_super)
    except Exception:
        counts = {}
    _NAV_COUNTS_CACHE[is_super] = {"val": counts, "ts": now}
    return jsonify({"counts": counts})
