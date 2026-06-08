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
    capture_exc,
    get_ai_setting,
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


# ===========================================================================
# CONTACTS — unified scored PEOPLE view (task 097, gap §2.1/2.2/2.3/2.8).
# Merges leads (each enriched with its visitor_profiles lead_score) with
# profile-only people (scored visitors who never became a lead), deduped by
# visitor_id, + headline KPIs. Convert flips/creates a 'won' lead ("customer").
# Super-admin only (visitor PII); each section fail-open so a glitch never 500s
# the list. Reuses the existing leads/profiles tables — no migration.
# ===========================================================================
@crm_bp.route("/admin/api/contacts", methods=["GET"])
@admin_required
def admin_list_contacts():
    """Unified scored people list + KPIs. Super-admin only. ?limit=N (max 1000)."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    try:
        limit = max(1, min(int(request.args.get("limit", 500) or 500), 1000))
    except (TypeError, ValueError):
        limit = 500
    tid = current_tenant_id()
    contacts = []
    seen_vids = set()
    # 1) Leads, each LEFT JOINed to its visitor_profile for the lead_score.
    try:
        leads = query_db(
            "SELECT l.id, l.name, l.email, l.phone, l.interest, l.source, l.status, "
            "       l.visitor_id, l.created_at, l.updated_at, "
            "       COALESCE(vp.lead_score, 0) AS lead_score "
            "FROM leads l "
            "LEFT JOIN visitor_profiles vp "
            "  ON vp.tenant_id = l.tenant_id AND vp.visitor_id = l.visitor_id "
            "WHERE l.tenant_id = %s "
            "ORDER BY COALESCE(vp.lead_score,0) DESC, l.id DESC LIMIT %s",
            (tid, limit)) or []
        for r in leads:
            vid = (r.get("visitor_id") or "").strip()
            if vid:
                seen_vids.add(vid)
            la = r.get("updated_at") or r.get("created_at")
            contacts.append({
                "kind": "lead", "lead_id": r["id"], "visitor_id": vid,
                "name": r.get("name") or "", "email": r.get("email") or "",
                "phone": r.get("phone") or "", "interest": r.get("interest") or "",
                "source": r.get("source") or "", "status": r.get("status") or "new",
                "lead_score": int(r.get("lead_score") or 0),
                "last_activity": la.isoformat() if la else None,
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            })
    except Exception as e:
        capture_exc(e, "admin_list_contacts.leads")
    # 2) Profile-only people: a scored visitor with no lead yet (chase candidates).
    try:
        profs = query_db(
            "SELECT id, visitor_id, interests, lead_score, summary, created_at, updated_at "
            "FROM visitor_profiles WHERE tenant_id = %s "
            "ORDER BY lead_score DESC, updated_at DESC LIMIT %s",
            (tid, limit)) or []
        for r in profs:
            vid = (r.get("visitor_id") or "").strip()
            if not vid or vid in seen_vids:
                continue
            seen_vids.add(vid)
            ints = _vp_as_list(r.get("interests"))
            la = r.get("updated_at") or r.get("created_at")
            contacts.append({
                "kind": "profile", "lead_id": None, "visitor_id": vid,
                "name": "", "email": "", "phone": "",
                "interest": (ints[0] if ints else ""), "source": "visitor",
                "status": "visitor", "lead_score": int(r.get("lead_score") or 0),
                "last_activity": la.isoformat() if la else None,
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            })
    except Exception as e:
        capture_exc(e, "admin_list_contacts.profiles")
    # Merge sort: hottest first, then most-recent activity.
    contacts.sort(key=lambda c: (c["lead_score"], c.get("last_activity") or ""), reverse=True)
    contacts = contacts[:limit]
    # 2.7 — super-admin lead-score thresholds (configurable via AI Control → CRM group).
    try:
        hot_min = int(get_ai_setting("crm_hot_min") or 80)
        warm_min = int(get_ai_setting("crm_warm_min") or 50)
    except Exception:
        hot_min, warm_min = 80, 50
    # 3) KPIs (§2.8) — each guarded, fail-open to 0.
    stats = {"open": 0, "hot": 0, "avg_age_days": 0, "won_this_month": 0}
    try:
        s = query_db(
            "SELECT "
            " COUNT(*) FILTER (WHERE status IN ('new','contacted','qualified')) AS open_n, "
            " ROUND(AVG(EXTRACT(EPOCH FROM (NOW()-created_at))/86400.0) "
            "       FILTER (WHERE status IN ('new','contacted','qualified')))::int AS avg_age, "
            " COUNT(*) FILTER (WHERE status='won' AND updated_at >= date_trunc('month', NOW())) AS won_m "
            "FROM leads WHERE tenant_id=%s", (tid,), fetchone=True) or {}
        stats["open"] = int(s.get("open_n") or 0)
        stats["avg_age_days"] = int(s.get("avg_age") or 0)
        stats["won_this_month"] = int(s.get("won_m") or 0)
    except Exception as e:
        capture_exc(e, "admin_list_contacts.stats")
    try:
        h = query_db("SELECT COUNT(*) AS n FROM visitor_profiles "
                     "WHERE tenant_id=%s AND lead_score >= %s", (tid, hot_min), fetchone=True) or {}
        stats["hot"] = int(h.get("n") or 0)
    except Exception as e:
        capture_exc(e, "admin_list_contacts.hot")
    return jsonify({"contacts": contacts, "stats": stats,
                    "thresholds": {"hot": hot_min, "warm": warm_min}})


@crm_bp.route("/admin/api/contacts/convert", methods=["POST"])
@admin_required
def admin_convert_contact():
    """One-click Convert→customer (§2.3). Body {lead_id} OR {visitor_id}. A lead_id
    flips that lead to status='won'; a visitor_id with no lead creates a 'won' lead
    seeded from its visitor_profile. 'Customer' == status 'won' (no new table)."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    body = _json_body()
    tid = current_tenant_id()
    raw_lead = body.get("lead_id")
    visitor_id = (body.get("visitor_id") or "").strip()[:100]
    lead_id = None
    if raw_lead not in (None, ""):
        try:
            lead_id = int(raw_lead)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid lead_id."}), 400
    try:
        if lead_id is not None:
            n = execute_db("UPDATE leads SET status='won', updated_at=NOW() WHERE id=%s AND tenant_id=%s",
                           (lead_id, tid))
            if not n:
                return jsonify({"error": "Lead not found."}), 404
            return jsonify({"ok": True, "lead_id": lead_id, "status": "won"})
        if visitor_id:
            existing = query_db(
                "SELECT id FROM leads WHERE tenant_id=%s AND visitor_id=%s ORDER BY id DESC LIMIT 1",
                (tid, visitor_id), fetchone=True)
            if existing:
                execute_db("UPDATE leads SET status='won', updated_at=NOW() WHERE id=%s AND tenant_id=%s",
                           (existing["id"], tid))
                return jsonify({"ok": True, "lead_id": existing["id"], "status": "won"})
            prof = query_db(
                "SELECT interests, summary FROM visitor_profiles WHERE tenant_id=%s AND visitor_id=%s",
                (tid, visitor_id), fetchone=True) or {}
            ints = _vp_as_list(prof.get("interests"))
            row = execute_db(
                "INSERT INTO leads (tenant_id, name, interest, message, source, visitor_id, status) "
                "VALUES (%s, '', %s, %s, 'converted', %s, 'won') RETURNING id",
                (tid, (ints[0] if ints else "")[:300], (prof.get("summary") or "")[:4000], visitor_id))
            if not row:
                return jsonify({"error": "Could not convert."}), 500
            return jsonify({"ok": True, "lead_id": row["id"], "status": "won", "created": True})
        return jsonify({"error": "Provide lead_id or visitor_id."}), 400
    except Exception as e:
        capture_exc(e, "admin_convert_contact")
        return jsonify({"error": "convert_failed"}), 500


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
    sets.append("updated_at=NOW()")   # task 101 §5.4: track when status changed (review auto-trigger uses it)
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
