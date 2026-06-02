"""admin/personas.py - admin CRUD routes for visitor personas, as a Flask blueprint.

Part of the app.py de-monolith (Track B), mirroring admin/offers.py. These four
/admin/api/visitor-personas* routes are SUPER-ADMIN-only: each calls
_require_super_admin_role() (from core) up front, exactly as it did in app.py - the
@admin_required decorator only proves "an admin is logged in", so the super-admin gate
is enforced in the body and is preserved verbatim here. A plain client session is 403'd.

A persona is a row of CONFIG the visitor concierge can route to (persona_key, label,
prompt_suffix, tool_names, model). The two helpers moved here with the routes are pure
data utilities: _row_persona serializes a row (ISO timestamps + parsed tool_names) and
_persona_payload coerces/whitelists the create-update body (slug-shaped persona_key,
length-capped strings, list-coerced tool_names) to prevent mass-assignment. Neither
helper makes a DB/AI/cache call - they only do string/list/dict transforms - so they
are safe to import-free of `from app` (which would be circular). The shared JSONB->list
coercion _vp_as_list lives in core (many app.py call sites) and is imported from there.
re is needed by _persona_payload's slug regex.

URLs keep their absolute /admin/api/visitor-personas* paths, so the route table is
unchanged - only the Flask endpoint name gains a "personas." prefix (admin JS calls
these by URL, not url_for). CSRF / feature-flag enforcement runs in app.py's global
before_request hooks, which apply to blueprint routes too, so nothing extra is needed.

Registered in app.py via app.register_blueprint(personas_bp), after offers_bp.
"""
import json
import re

from flask import Blueprint, request, jsonify

from core import (
    query_db,
    execute_db,
    current_tenant_id,
    admin_required,
    _require_super_admin_role,
    _vp_as_list,
)

personas_bp = Blueprint("personas", __name__)


# ---- visitor-persona helpers + CRUD routes (Track B, verbatim from app.py) ----
# _row_persona / _persona_payload are pure data utilities (serialize row / coerce
# whitelisted create-update fields). The 4 routes are super-admin-gated in-body.

def _row_persona(r):
    d = dict(r)
    d["tool_names"] = _vp_as_list(d.get("tool_names"))
    for k in ("created_at", "updated_at"):
        if d.get(k):
            d[k] = d[k].isoformat()
    return d


def _persona_payload(body):
    """Validate + coerce a persona create/update body. Returns (fields, error).
    persona_key is a slug; 'general' is reserved (it's the implicit fallback)."""
    key = (body.get("persona_key") or "").strip().lower()
    if not re.match(r"^[a-z0-9_]{1,40}$", key or ""):
        return None, "persona_key must be 1-40 chars of a-z, 0-9, underscore"
    if key == "general":
        return None, "'general' is reserved (it is the implicit fallback persona)"
    tools = body.get("tool_names")
    if isinstance(tools, str):
        tools = [t.strip() for t in tools.split(",")]
    if not isinstance(tools, list):
        tools = []
    tools = [str(t).strip()[:80] for t in tools if str(t).strip()][:50]
    try:
        sort_order = int(body.get("sort_order") or 0)
    except (TypeError, ValueError):
        sort_order = 0
    return {
        "persona_key": key,
        "label": (body.get("label") or "").strip()[:120],
        "prompt_suffix": (body.get("prompt_suffix") or "").strip()[:8000],
        "tool_names": json.dumps(tools),
        "model": (body.get("model") or "").strip()[:120],
        "enabled": bool(body.get("enabled", True)),
        "sort_order": sort_order,
    }, ""


@personas_bp.route("/admin/api/visitor-personas", methods=["GET"])
@admin_required
def admin_list_visitor_personas():
    """List the tenant's visitor personas (super-admin only)."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    tid = current_tenant_id()
    rows = query_db(
        "SELECT * FROM visitor_personas WHERE tenant_id=%s "
        "ORDER BY sort_order, id", (tid,)) or []
    return jsonify({"personas": [_row_persona(r) for r in rows]})


@personas_bp.route("/admin/api/visitor-personas", methods=["POST"])
@admin_required
def admin_create_visitor_persona():
    """Create a visitor persona (super-admin only)."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    fields, err = _persona_payload(request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    tid = current_tenant_id()
    # Reject a duplicate key for this tenant (the UNIQUE constraint would 500).
    if query_db("SELECT 1 FROM visitor_personas WHERE tenant_id=%s AND persona_key=%s",
                (tid, fields["persona_key"]), fetchone=True):
        return jsonify({"error": "persona_key already exists"}), 409
    row = execute_db(
        "INSERT INTO visitor_personas (tenant_id, persona_key, label, prompt_suffix, "
        " tool_names, model, enabled, sort_order) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
        "RETURNING *",
        (tid, fields["persona_key"], fields["label"], fields["prompt_suffix"],
         fields["tool_names"], fields["model"], fields["enabled"], fields["sort_order"]))
    return jsonify({"persona": _row_persona(row)}), 201


@personas_bp.route("/admin/api/visitor-personas/<int:persona_id>", methods=["PUT"])
@admin_required
def admin_update_visitor_persona(persona_id):
    """Update a visitor persona (super-admin only). Tenant-scoped."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    fields, err = _persona_payload(request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    tid = current_tenant_id()
    row = execute_db(
        "UPDATE visitor_personas SET persona_key=%s, label=%s, prompt_suffix=%s, "
        " tool_names=%s, model=%s, enabled=%s, sort_order=%s, updated_at=NOW() "
        "WHERE id=%s AND tenant_id=%s RETURNING *",
        (fields["persona_key"], fields["label"], fields["prompt_suffix"],
         fields["tool_names"], fields["model"], fields["enabled"],
         fields["sort_order"], persona_id, tid))
    if not row:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"persona": _row_persona(row)})


@personas_bp.route("/admin/api/visitor-personas/<int:persona_id>", methods=["DELETE"])
@admin_required
def admin_delete_visitor_persona(persona_id):
    """Delete a visitor persona (super-admin only). Tenant-scoped."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    tid = current_tenant_id()
    row = execute_db(
        "DELETE FROM visitor_personas WHERE id=%s AND tenant_id=%s RETURNING id",
        (persona_id, tid))
    if not row:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"ok": True, "deleted": persona_id})
