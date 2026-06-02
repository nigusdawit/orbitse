"""admin/dashboards.py - admin CRUD routes for custom dashboards, as a Flask blueprint.

Part of the app.py de-monolith (Track B), mirroring admin/content.py. This blueprint
owns the dashboard + widget CRUD the "Dashboards" tab uses to build no-code analytics
boards: create/rename/delete a dashboard and add/edit/remove its widgets. These are all
plain query_db/execute_db CRUD gated by @admin_required (from core).

Deliberately NOT moved (they stay in app.py):
  - the widget EXECUTION route (/admin/api/dashboards/widgets/<id>/run) — it dispatches
    into the BUILTIN_METRICS registry + the multi-DB / REST connector + secret-decrypt
    layer, none of which are clean leaves.
  - /admin/api/dashboards/builtin-metrics and /db-tables — they read the BUILTIN_METRICS
    registry / introspect the live schema, infra shared with the run route above.
  - all /admin/api/datahub/* routes — they call the AI-tool-surface helpers
    (_admin_tool_inspect_connection / _dh_ai_define) that pull in the AI client.

URLs keep their absolute /admin/api/* paths, so the route table is unchanged - only the
Flask endpoint name gains a "dashboards." prefix (admin JS calls these by URL, not
url_for). The two row serializers (_serialize_dashboard / _serialize_widget) are used
only by the routes below, so they moved here verbatim with them. CSRF / feature-flag
enforcement runs in app.py's global before_request hooks, which apply to blueprint
routes too, so nothing extra is needed here.

Registered in app.py via app.register_blueprint(dashboards_bp), after reporting_bp.
Imports come from core (never app - that would be circular).
"""
import json

from flask import Blueprint, request, jsonify

from core import query_db, execute_db, admin_required

dashboards_bp = Blueprint("dashboards", __name__)


# ----- Dashboards CRUD -----------------------------------------------------

def _serialize_dashboard(row, widgets=None):
    out = {
        "id": row["id"],
        "name": row["name"],
        "description": row.get("description") or "",
        "sort_order": row.get("sort_order", 0),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
    }
    if widgets is not None:
        out["widgets"] = widgets
    return out


def _serialize_widget(row):
    return {
        "id": row["id"],
        "dashboard_id": row["dashboard_id"],
        "name": row["name"],
        "widget_type": row["widget_type"],
        "source_type": row["source_type"],
        "source_config": row.get("source_config") or {},
        "sort_order": row.get("sort_order", 0),
    }


@dashboards_bp.route("/admin/api/dashboards", methods=["GET"])
@admin_required
def admin_list_dashboards():
    rows = query_db(
        "SELECT id, name, description, sort_order, created_at "
        "FROM dashboards ORDER BY sort_order, id"
    ) or []
    return jsonify([_serialize_dashboard(r) for r in rows])


@dashboards_bp.route("/admin/api/dashboards", methods=["POST"])
@admin_required
def admin_create_dashboard():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()
    if not name:
        return jsonify({"error": "Name is required."}), 400
    row = execute_db(
        "INSERT INTO dashboards (name, description) VALUES (%s, %s) "
        "RETURNING id, name, description, sort_order, created_at",
        (name, description),
    )
    return jsonify(_serialize_dashboard(row)), 201


@dashboards_bp.route("/admin/api/dashboards/<int:did>", methods=["GET"])
@admin_required
def admin_get_dashboard(did):
    row = query_db(
        "SELECT id, name, description, sort_order, created_at "
        "FROM dashboards WHERE id = %s",
        (did,), fetchone=True,
    )
    if not row:
        return jsonify({"error": "Not found"}), 404
    widget_rows = query_db(
        "SELECT id, dashboard_id, name, widget_type, source_type, source_config, sort_order "
        "FROM dashboard_widgets WHERE dashboard_id = %s ORDER BY sort_order, id",
        (did,),
    ) or []
    return jsonify(_serialize_dashboard(row, [_serialize_widget(w) for w in widget_rows]))


@dashboards_bp.route("/admin/api/dashboards/<int:did>", methods=["PUT"])
@admin_required
def admin_update_dashboard(did):
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()
    if not name:
        return jsonify({"error": "Name is required."}), 400
    execute_db(
        "UPDATE dashboards SET name = %s, description = %s WHERE id = %s",
        (name, description, did),
    )
    return jsonify({"success": True})


@dashboards_bp.route("/admin/api/dashboards/<int:did>", methods=["DELETE"])
@admin_required
def admin_delete_dashboard(did):
    execute_db("DELETE FROM dashboards WHERE id = %s", (did,))
    return jsonify({"success": True})


# ----- Widget CRUD ---------------------------------------------------------

@dashboards_bp.route("/admin/api/dashboards/<int:did>/widgets", methods=["POST"])
@admin_required
def admin_create_widget(did):
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    widget_type = (body.get("widget_type") or "kpi").strip()
    source_type = (body.get("source_type") or "builtin").strip()
    source_config = body.get("source_config") or {}
    if widget_type not in ("kpi", "table", "line", "bar"):
        return jsonify({"error": "Invalid widget type."}), 400
    if source_type not in ("builtin", "internal_db", "external_postgres", "external_rest", "static"):
        return jsonify({"error": "Invalid source type."}), 400
    if not name:
        return jsonify({"error": "Name is required."}), 400
    # Determine sort_order — append to end.
    last = query_db(
        "SELECT COALESCE(MAX(sort_order), -1) AS m FROM dashboard_widgets "
        "WHERE dashboard_id = %s", (did,), fetchone=True,
    ) or {"m": -1}
    sort_order = int(last["m"]) + 1
    row = execute_db(
        "INSERT INTO dashboard_widgets (dashboard_id, name, widget_type, "
        "source_type, source_config, sort_order) "
        "VALUES (%s, %s, %s, %s, %s::jsonb, %s) "
        "RETURNING id, dashboard_id, name, widget_type, source_type, source_config, sort_order",
        (did, name, widget_type, source_type, json.dumps(source_config), sort_order),
    )
    return jsonify(_serialize_widget(row)), 201


@dashboards_bp.route("/admin/api/dashboards/<int:did>/widgets/<int:wid>", methods=["PUT"])
@admin_required
def admin_update_widget(did, wid):
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    widget_type = (body.get("widget_type") or "kpi").strip()
    source_type = (body.get("source_type") or "builtin").strip()
    source_config = body.get("source_config") or {}
    if widget_type not in ("kpi", "table", "line", "bar"):
        return jsonify({"error": "Invalid widget type."}), 400
    if source_type not in ("builtin", "internal_db", "external_postgres", "external_rest", "static"):
        return jsonify({"error": "Invalid source type."}), 400
    execute_db(
        "UPDATE dashboard_widgets SET name = %s, widget_type = %s, "
        "source_type = %s, source_config = %s::jsonb "
        "WHERE id = %s AND dashboard_id = %s",
        (name, widget_type, source_type, json.dumps(source_config), wid, did),
    )
    return jsonify({"success": True})


@dashboards_bp.route("/admin/api/dashboards/<int:did>/widgets/<int:wid>", methods=["DELETE"])
@admin_required
def admin_delete_widget(did, wid):
    execute_db(
        "DELETE FROM dashboard_widgets WHERE id = %s AND dashboard_id = %s",
        (wid, did),
    )
    return jsonify({"success": True})
