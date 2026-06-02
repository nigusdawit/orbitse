"""admin/crm.py - super-admin read APIs for concierge-captured CRM data, as a blueprint.

Part of the app.py de-monolith (Track B), mirroring admin/offers.py. These four GET
routes surface what the concierge captured for the operator: visitor CRM profiles
(interests/needs/lead-score/consent), leads, callback requests, and meeting requests.
They hold visitor PII (the operator's sales data), so every route is SUPER-ADMIN-only:
each calls _require_super_admin_role() (from core) up front, exactly as it did in app.py
- the @admin_required decorator only proves "an admin is logged in", so the super-admin
gate is enforced in the body and is preserved verbatim here. A plain client session is
403'd.

URLs keep their absolute /admin/api/* paths, so the route table is unchanged - only the
Flask endpoint name gains a "crm." prefix (admin JS calls these by URL, not url_for).
CSRF / feature-flag enforcement runs in app.py's global before_request hooks, which
apply to blueprint routes too, so nothing extra is needed here.

Imports come from core (never app - that would be circular). The shared leaf helpers
_vp_as_list (JSONB->list) and _iso_row (row ISO-date coercer) live in core - both have
many other app.py call sites - and are imported from there. current_tenant_id scopes
every query to the active tenant.

Registered in app.py via app.register_blueprint(crm_bp), after dashboards_bp.
"""
from flask import Blueprint, request, jsonify

from core import (
    query_db,
    admin_required,
    _require_super_admin_role,
    current_tenant_id,
    _vp_as_list,
    _iso_row,
)

crm_bp = Blueprint("crm", __name__)


@crm_bp.route("/admin/api/visitor-profiles", methods=["GET"])
@admin_required
def admin_list_visitor_profiles():
    """Visitor CRM profiles (task 042), highest lead-score first. Super-admin
    only — these accumulate visitor signals (interests/needs/lead/consent).
    ?limit=N (default 100, max 500). Empty until the 'Visitor CRM' knob is on."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    try:
        limit = int(request.args.get("limit", 100) or 100)
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, 500))
    tid = current_tenant_id()
    rows = query_db(
        "SELECT id, visitor_id, interests, needs, lead_score, consent, summary, "
        "turns, created_at, updated_at FROM visitor_profiles "
        "WHERE tenant_id=%s ORDER BY lead_score DESC, updated_at DESC LIMIT %s",
        (tid, limit)) or []
    out = []
    for r in rows:
        d = dict(r)
        d["interests"] = _vp_as_list(d.get("interests"))
        d["needs"] = _vp_as_list(d.get("needs"))
        for k in ("created_at", "updated_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        out.append(d)
    stats = query_db(
        "SELECT COUNT(*) AS n, COALESCE(MAX(lead_score),0) AS top "
        "FROM visitor_profiles WHERE tenant_id=%s", (tid,), fetchone=True) or {}
    return jsonify({
        "profiles": out,
        "stats": {
            "count": int(stats.get("n") or 0),
            "top_lead_score": int(stats.get("top") or 0),
        },
    })


@crm_bp.route("/admin/api/leads", methods=["GET"])
@admin_required
def admin_list_leads():
    """Leads captured by the concierge (super-admin only). ?limit=N (max 500)."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    try:
        limit = max(1, min(int(request.args.get("limit", 100) or 100), 500))
    except (TypeError, ValueError):
        limit = 100
    tid = current_tenant_id()
    rows = query_db(
        "SELECT id, name, email, phone, interest, message, source, status, "
        "created_at FROM leads WHERE tenant_id=%s ORDER BY id DESC LIMIT %s",
        (tid, limit)) or []
    return jsonify({"leads": [_iso_row(r, "created_at") for r in rows]})


@crm_bp.route("/admin/api/callbacks", methods=["GET"])
@admin_required
def admin_list_callbacks():
    """Callback requests taken by the concierge (super-admin only)."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    try:
        limit = max(1, min(int(request.args.get("limit", 100) or 100), 500))
    except (TypeError, ValueError):
        limit = 100
    tid = current_tenant_id()
    rows = query_db(
        "SELECT id, name, phone, preferred_time, reason, ai_summary, status, "
        "created_at FROM callback_requests WHERE tenant_id=%s ORDER BY id DESC LIMIT %s",
        (tid, limit)) or []
    return jsonify({"callbacks": [_iso_row(r, "created_at") for r in rows]})


@crm_bp.route("/admin/api/meetings", methods=["GET"])
@admin_required
def admin_list_meetings():
    """Meeting requests/bookings taken by the concierge (super-admin only)."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    try:
        limit = max(1, min(int(request.args.get("limit", 100) or 100), 500))
    except (TypeError, ValueError):
        limit = 100
    tid = current_tenant_id()
    rows = query_db(
        "SELECT id, name, email, phone, requested_time, start_iso, duration_minutes, "
        "notes, status, calendar_event_id, created_at FROM meetings "
        "WHERE tenant_id=%s ORDER BY id DESC LIMIT %s", (tid, limit)) or []
    return jsonify({"meetings": [_iso_row(r, "created_at") for r in rows]})
