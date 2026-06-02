"""admin/offers.py - admin CRUD routes for promotional offers, as a Flask blueprint.

Part of the app.py de-monolith (Track B), mirroring admin/content.py. These four
/admin/api/offers* routes are SUPER-ADMIN-only: each calls _require_super_admin_role()
(from core) up front, exactly as it did in app.py - the @admin_required decorator only
proves "an admin is logged in", so the super-admin gate is enforced in the body and is
preserved verbatim here. Offers hold operator marketing data, so a plain client session
is 403'd.

Imports come from core (never app - that would be circular). The two helpers
_row_offer (row serializer) and _offer_payload (whitelist coercion of the create/update
body) are pure data utilities and were moved here verbatim with the routes. The shared
JSONB->list coercion _vp_as_list lives in core (it has many other call sites in app.py)
and is imported from there.

URLs keep their absolute /admin/api/offers* paths, so the route table is unchanged -
only the Flask endpoint name gains an "offers." prefix (admin JS calls these by URL,
not url_for). CSRF / feature-flag enforcement runs in app.py's global before_request
hooks, which apply to blueprint routes too, so nothing extra is needed here.

Registered in app.py via app.register_blueprint(offers_bp), after content_bp/forms_bp.
"""
import json

from flask import Blueprint, request, jsonify

from core import (
    query_db,
    execute_db,
    current_tenant_id,
    admin_required,
    _require_super_admin_role,
    _vp_as_list,
)

offers_bp = Blueprint("offers", __name__)


# ---- offers helpers + CRUD routes (Track B, verbatim from app.py) ----
# _row_offer / _offer_payload are pure data utilities (serialize row / coerce
# whitelisted create-update fields). The 4 routes are super-admin-gated in-body.

def _row_offer(r):
    """Serialize an offers row for the admin API (ISO timestamps, parsed tags)."""
    d = dict(r)
    d["trigger_tags"] = _vp_as_list(d.get("trigger_tags"))
    for k in ("starts_at", "ends_at", "created_at", "updated_at"):
        if d.get(k):
            d[k] = d[k].isoformat()
    return d


def _offer_payload(body):
    """Validate + coerce an offer create/update body. Returns (fields, error).
    Only whitelisted columns are accepted (no mass-assignment)."""
    title = (body.get("title") or "").strip()
    if not title:
        return None, "title is required"
    tags = body.get("trigger_tags")
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    if not isinstance(tags, list):
        tags = []
    tags = [str(t).strip()[:80] for t in tags if str(t).strip()][:25]
    try:
        priority = int(body.get("priority") or 0)
    except (TypeError, ValueError):
        priority = 0
    return {
        "title": title[:300],
        "description": (body.get("description") or "").strip()[:4000],
        "code": (body.get("code") or "").strip()[:80],
        "cta_url": (body.get("cta_url") or "").strip()[:1000],
        "trigger_tags": json.dumps(tags),
        "active": bool(body.get("active", True)),
        "starts_at": (body.get("starts_at") or None),
        "ends_at": (body.get("ends_at") or None),
        "priority": priority,
    }, ""


@offers_bp.route("/admin/api/offers", methods=["GET"])
@admin_required
def admin_list_offers():
    """List all offers for the tenant (super-admin only)."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    tid = current_tenant_id()
    rows = query_db(
        "SELECT * FROM offers WHERE tenant_id=%s ORDER BY priority DESC, id DESC",
        (tid,)) or []
    return jsonify({"offers": [_row_offer(r) for r in rows]})


@offers_bp.route("/admin/api/offers", methods=["POST"])
@admin_required
def admin_create_offer():
    """Create an offer (super-admin only)."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    fields, err = _offer_payload(request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    tid = current_tenant_id()
    row = execute_db(
        "INSERT INTO offers (tenant_id, title, description, code, cta_url, "
        " trigger_tags, active, starts_at, ends_at, priority) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (tid, fields["title"], fields["description"], fields["code"],
         fields["cta_url"], fields["trigger_tags"], fields["active"],
         fields["starts_at"], fields["ends_at"], fields["priority"]))
    return jsonify({"offer": _row_offer(row)}), 201


@offers_bp.route("/admin/api/offers/<int:offer_id>", methods=["PUT"])
@admin_required
def admin_update_offer(offer_id):
    """Update an offer (super-admin only). Scoped to the tenant."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    fields, err = _offer_payload(request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    tid = current_tenant_id()
    row = execute_db(
        "UPDATE offers SET title=%s, description=%s, code=%s, cta_url=%s, "
        " trigger_tags=%s, active=%s, starts_at=%s, ends_at=%s, priority=%s, "
        " updated_at=NOW() WHERE id=%s AND tenant_id=%s RETURNING *",
        (fields["title"], fields["description"], fields["code"], fields["cta_url"],
         fields["trigger_tags"], fields["active"], fields["starts_at"],
         fields["ends_at"], fields["priority"], offer_id, tid))
    if not row:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"offer": _row_offer(row)})


@offers_bp.route("/admin/api/offers/<int:offer_id>", methods=["DELETE"])
@admin_required
def admin_delete_offer(offer_id):
    """Delete an offer (super-admin only). Scoped to the tenant."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    tid = current_tenant_id()
    row = execute_db(
        "DELETE FROM offers WHERE id=%s AND tenant_id=%s RETURNING id",
        (offer_id, tid))
    if not row:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"ok": True, "deleted": offer_id})
