"""admin/tenancy.py - super-admin Plans & Features management API, as a blueprint.

Part of the app.py de-monolith (Track B), mirroring admin/crm.py. These two routes
back the "Plans & Features" tab: list every feature in the registry with its on/off
state + plan tier, and flip one feature on/off. They are the REAL security boundary
for feature visibility, so each calls _require_super_admin_role() (from core) up front
- exactly as it did in app.py. The @admin_required decorator only proves "an admin is
logged in"; the super-admin gate is enforced in the body and is preserved verbatim. A
plain client session is 403'd, which is what stops a client from re-granting itself
tabs by hitting the API directly (independent of the hidden UI tab).

URLs keep their absolute /admin/api/* paths, so the route table is unchanged - only the
Flask endpoint name gains a "tenancy." prefix (admin JS calls these by URL, not url_for).
CSRF / feature-flag enforcement runs in app.py's global before_request hooks, which apply
to blueprint routes too, so nothing extra is needed here.

Imports come from core (never app - that would be circular). The feature subsystem now
lives in core (Track B): list_tenant_features / set_tenant_feature do the read + flip
(the flip busts the in-process cache), and current_tenant_id scopes to the active tenant.

Registered in app.py via app.register_blueprint(tenancy_bp), after crm_bp.
"""
from flask import Blueprint, request, jsonify

from core import (
    capture_exc,
    query_db,
    admin_required,
    _require_super_admin_role,
    current_tenant_id,
    list_tenant_features,
    set_tenant_feature,
)

tenancy_bp = Blueprint("tenancy", __name__)


@tenancy_bp.route("/admin/api/tenant/features", methods=["GET"])
@admin_required
def admin_list_tenant_features():
    """Return every known feature + on/off state + plan tier + addon flag."""
    # HARD boundary: only the super admin manages feature visibility. A client
    # session is logged-in (passes @admin_required) but must never read or change
    # the feature roster — this is what stops a client from re-granting itself
    # tabs by hitting the API directly, independent of the hidden UI tab.
    _guard = _require_super_admin_role()
    if _guard is not None:
        return _guard
    try:
        tid = current_tenant_id()
        # Pull plan + tenant info so the UI can show "you're on the Growth plan".
        # NOTE: the plans table has columns (id, slug, name, description,
        # sort_order). We expose `slug` as `plan_code` for UI back-compat.
        tenant = query_db(
            "SELECT t.id, t.name AS tenant_name, t.plan_id, "
            "       p.slug AS plan_code, p.name AS plan_name "
            "FROM tenants t LEFT JOIN plans p ON p.id = t.plan_id "
            "WHERE t.id = %s",
            (tid,), fetchone=True,
        ) or {}
        features = list_tenant_features(tid)
        plans = query_db(
            "SELECT id, slug AS code, name, description, sort_order "
            "FROM plans ORDER BY sort_order, id"
        ) or []
        return jsonify({
            "tenant": dict(tenant) if tenant else {"id": tid},
            "features": features,
            "plans": [dict(p) for p in plans],
        })
    except Exception as e:
        capture_exc(e, "tenancy.admin_list_tenant_features")
        print(f"[plans] list_tenant_features failed: {e}")
        return jsonify({"error": "failed_to_list_features", "detail": str(e)}), 500


@tenancy_bp.route("/admin/api/tenant/features/<name>", methods=["PATCH"])
@admin_required
def admin_toggle_tenant_feature(name):
    """Flip one feature on/off. Body: {"enabled": bool, "note"?: str}."""
    # HARD boundary: super admin only (see admin_list_tenant_features). Without
    # this in-handler check a client could PATCH its own flags via curl.
    _guard = _require_super_admin_role()
    if _guard is not None:
        return _guard
    body = request.get_json(silent=True) or {}
    if "enabled" not in body:
        return jsonify({"error": "missing_field", "field": "enabled"}), 400
    try:
        new_val = set_tenant_feature(
            name,
            bool(body.get("enabled")),
            note=str(body.get("note") or ""),
        )
        return jsonify({"feature": name, "enabled": new_val})
    except ValueError as ve:
        return jsonify({"error": "unknown_feature", "feature": name, "detail": str(ve)}), 400
    except Exception as e:
        capture_exc(e, "tenancy.admin_toggle_tenant_feature")
        print(f"[plans] toggle feature {name} failed: {e}")
        return jsonify({"error": "toggle_failed", "detail": str(e)}), 500
