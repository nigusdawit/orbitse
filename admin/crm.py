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
    execute_db,
    admin_required,
    _require_super_admin_role,
    current_tenant_id,
    _vp_as_list,
    _iso_row,
)

crm_bp = Blueprint("crm", __name__)

# ---------------------------------------------------------------------------
# Allowed status values per CRM entity. Admin write routes validate against
# these so a stray payload can't poke arbitrary text into the status column.
# Kept deliberately small + human-friendly; extend here if the pipeline grows.
# ---------------------------------------------------------------------------
_LEAD_STATUSES = {"new", "contacted", "qualified", "won", "lost", "archived"}
_CALLBACK_STATUSES = {"new", "contacted", "done", "cancelled"}
_MEETING_STATUSES = {
    "requested", "booked", "confirmed", "completed", "cancelled", "declined",
}


def _json_body():
    """Parse the JSON request body, tolerating an empty/blank body."""
    return request.get_json(silent=True) or {}


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


# ===========================================================================
# CRM WRITE actions — let the operator ACT on what the concierge captured
# (change status, add a manual lead, delete an entry). Every route is
# super-admin-only (same gate as the read routes above) and tenant-scoped, so
# one operator can never touch another's CRM data. CSRF is enforced globally
# by app.py's before_request hook, so nothing extra is needed here.
# ===========================================================================

# ---- Leads --------------------------------------------------------------
@crm_bp.route("/admin/api/leads", methods=["POST"])
@admin_required
def admin_create_lead():
    """Manually add a lead (e.g. one that came in by phone/email off-site).
    Needs at least a name, email, or phone. Stored with source='manual'."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    body = _json_body()
    name = (body.get("name") or "").strip()[:200]
    email = (body.get("email") or "").strip().lower()[:320]
    phone = (body.get("phone") or "").strip()[:50]
    interest = (body.get("interest") or "").strip()[:300]
    message = (body.get("message") or "").strip()[:4000]
    if not (name or email or phone):
        return jsonify({"error": "Provide at least a name, email, or phone."}), 400
    row = execute_db(
        "INSERT INTO leads (tenant_id, name, email, phone, interest, message, source) "
        "VALUES (%s,%s,%s,%s,%s,%s,'manual') RETURNING id",
        (current_tenant_id(), name, email, phone, interest, message))
    if not row:
        return jsonify({"error": "Could not save the lead."}), 500
    return jsonify({"ok": True, "id": row["id"]})


@crm_bp.route("/admin/api/leads/<int:lead_id>", methods=["PATCH"])
@admin_required
def admin_update_lead(lead_id):
    """Update a lead's pipeline status (new/contacted/qualified/won/lost/archived)."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    status = (_json_body().get("status") or "").strip().lower()
    if status not in _LEAD_STATUSES:
        return jsonify({"error": "Invalid status."}), 400
    n = execute_db(
        "UPDATE leads SET status=%s WHERE id=%s AND tenant_id=%s",
        (status, lead_id, current_tenant_id()))
    if not n:
        return jsonify({"error": "Lead not found."}), 404
    return jsonify({"ok": True, "status": status})


@crm_bp.route("/admin/api/leads/<int:lead_id>", methods=["DELETE"])
@admin_required
def admin_delete_lead(lead_id):
    """Delete a lead (super-admin only)."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    n = execute_db("DELETE FROM leads WHERE id=%s AND tenant_id=%s",
                   (lead_id, current_tenant_id()))
    if not n:
        return jsonify({"error": "Lead not found."}), 404
    return jsonify({"ok": True})


# ---- Callbacks ----------------------------------------------------------
@crm_bp.route("/admin/api/callbacks/<int:cb_id>", methods=["PATCH"])
@admin_required
def admin_update_callback(cb_id):
    """Update a callback request's status (new/contacted/done/cancelled)."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    status = (_json_body().get("status") or "").strip().lower()
    if status not in _CALLBACK_STATUSES:
        return jsonify({"error": "Invalid status."}), 400
    n = execute_db(
        "UPDATE callback_requests SET status=%s WHERE id=%s AND tenant_id=%s",
        (status, cb_id, current_tenant_id()))
    if not n:
        return jsonify({"error": "Callback not found."}), 404
    return jsonify({"ok": True, "status": status})


@crm_bp.route("/admin/api/callbacks/<int:cb_id>", methods=["DELETE"])
@admin_required
def admin_delete_callback(cb_id):
    """Delete a callback request (super-admin only)."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    n = execute_db("DELETE FROM callback_requests WHERE id=%s AND tenant_id=%s",
                   (cb_id, current_tenant_id()))
    if not n:
        return jsonify({"error": "Callback not found."}), 404
    return jsonify({"ok": True})


# ---- Meetings -----------------------------------------------------------
@crm_bp.route("/admin/api/meetings/<int:mt_id>", methods=["PATCH"])
@admin_required
def admin_update_meeting(mt_id):
    """Update a meeting's status and/or notes. Status must be one of
    requested/booked/confirmed/completed/cancelled/declined."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    body = _json_body()
    sets, params = [], []
    if "status" in body:
        status = (body.get("status") or "").strip().lower()
        if status not in _MEETING_STATUSES:
            return jsonify({"error": "Invalid status."}), 400
        sets.append("status=%s")
        params.append(status)
    if "notes" in body:
        sets.append("notes=%s")
        params.append((body.get("notes") or "").strip()[:2000])
    if not sets:
        return jsonify({"error": "Nothing to update."}), 400
    params.extend([mt_id, current_tenant_id()])
    n = execute_db(
        "UPDATE meetings SET " + ", ".join(sets) + " WHERE id=%s AND tenant_id=%s",
        tuple(params))
    if not n:
        return jsonify({"error": "Meeting not found."}), 404
    return jsonify({"ok": True})


@crm_bp.route("/admin/api/meetings/<int:mt_id>", methods=["DELETE"])
@admin_required
def admin_delete_meeting(mt_id):
    """Delete a meeting request (super-admin only)."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    n = execute_db("DELETE FROM meetings WHERE id=%s AND tenant_id=%s",
                   (mt_id, current_tenant_id()))
    if not n:
        return jsonify({"error": "Meeting not found."}), 404
    return jsonify({"ok": True})


# ---- Visitor profiles (PII — delete only) -------------------------------
@crm_bp.route("/admin/api/visitor-profiles/<int:vp_id>", methods=["DELETE"])
@admin_required
def admin_delete_visitor_profile(vp_id):
    """Delete a visitor profile (super-admin only). Profiles are PII, so this
    gives the operator a clean way to honour an erase request."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    n = execute_db("DELETE FROM visitor_profiles WHERE id=%s AND tenant_id=%s",
                   (vp_id, current_tenant_id()))
    if not n:
        return jsonify({"error": "Profile not found."}), 404
    return jsonify({"ok": True})
