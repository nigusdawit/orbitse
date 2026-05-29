"""
admin_ai_platform.blueprints.skills
===================================

Skills admin: the agent_skills registry (toggle builtins, edit labels) plus
admin-defined **custom SQL** and **HTTP/webhook** skills the visitor AI can call.

  * ``GET    /admin/api/skills``            registry (builtins + custom)
  * ``PUT    /admin/api/skills/<id>``       edit display/description/category/enabled
  * ``DELETE /admin/api/skills/<id>``       delete a custom agent_skill (builtins refuse)
  * ``GET    /admin/api/skills/usage``      recent skill_usage_log + 7-day summary
  * ``GET/POST /admin/api/custom-sql`` + ``PUT/DELETE /admin/api/custom-sql/<id>``
  * ``GET/POST /admin/api/custom-webhooks`` + ``PUT/DELETE /admin/api/custom-webhooks/<id>``
"""

from __future__ import annotations

import json

from flask import Blueprint, request, jsonify

from ..db import query_db, execute_db
from ..auth import admin_required
from ..custom_skills import valid_skill_name
from ..tools import SKILL_METADATA

bp = Blueprint("skills", __name__)

_BUILTIN_NAMES = set(SKILL_METADATA)


# ---- agent_skills registry ---------------------------------------------
@bp.route("/admin/api/skills", methods=["GET"])
@admin_required
def list_skills():
    rows = query_db("SELECT * FROM agent_skills ORDER BY builtin DESC, category, name")
    return jsonify({"skills": rows or []})


@bp.route("/admin/api/skills/<int:sid>", methods=["PUT"])
@admin_required
def edit_skill(sid):
    data = request.get_json() or {}
    sets, vals = [], []
    for k in ("display_name", "description", "category"):
        if k in data:
            sets.append(f"{k}=%s")
            vals.append(data[k])
    if "enabled" in data:
        sets.append("enabled=%s")
        vals.append(bool(data["enabled"]))
    if "config_json" in data:
        sets.append("config_json=%s::jsonb")
        vals.append(json.dumps(data["config_json"]))
    if not sets:
        return jsonify({"error": "No fields"}), 400
    vals.append(sid)
    row = execute_db(f"UPDATE agent_skills SET {', '.join(sets)} WHERE id=%s RETURNING *", tuple(vals))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/skills", methods=["POST"])
@admin_required
def create_skill():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip().lower()
    if not valid_skill_name(name):
        return jsonify({"error": "name must match ^[a-z][a-z0-9_]{1,59}$"}), 400
    if name in _BUILTIN_NAMES:
        return jsonify({"error": "name collides with a builtin skill"}), 400
    row = execute_db(
        "INSERT INTO agent_skills (name, display_name, description, category, builtin, enabled, config_json) "
        "VALUES (%s,%s,%s,%s,FALSE,%s,%s::jsonb) "
        "ON CONFLICT (name) DO NOTHING RETURNING *",
        (name, data.get("display_name", name), data.get("description", ""),
         data.get("category", "custom"), bool(data.get("enabled", True)),
         json.dumps(data.get("config_json", {}))))
    if not row:
        return jsonify({"error": "name already exists"}), 409
    return jsonify(row), 201


@bp.route("/admin/api/skills/<int:sid>", methods=["DELETE"])
@admin_required
def delete_skill(sid):
    row = query_db("SELECT builtin FROM agent_skills WHERE id=%s", (sid,), fetchone=True)
    if not row:
        return jsonify({"error": "Not found"}), 404
    if row["builtin"]:
        return jsonify({"error": "builtin skills cannot be deleted — disable it instead"}), 400
    execute_db("DELETE FROM agent_skills WHERE id=%s", (sid,))
    return jsonify({"success": True})


@bp.route("/admin/api/skills/usage", methods=["GET"])
@admin_required
def usage():
    recent = query_db("SELECT skill_name, args_json, row_count, duration_ms, error, created_at "
                      "FROM skill_usage_log ORDER BY created_at DESC LIMIT 50")
    summary = query_db(
        "SELECT skill_name, COUNT(*) AS calls, SUM(CASE WHEN error<>'' THEN 1 ELSE 0 END) AS errors, "
        " ROUND(AVG(duration_ms)) AS avg_ms FROM skill_usage_log "
        "WHERE created_at >= NOW() - INTERVAL '7 days' GROUP BY skill_name ORDER BY calls DESC")
    return jsonify({"recent": recent or [], "summary": summary or []})


# ---- custom SQL skills --------------------------------------------------
def _crud(table, fields):
    """Build list/create/update/delete handlers for a custom-skill table."""
    def lst():
        return jsonify({"skills": query_db(f"SELECT * FROM {table} ORDER BY name") or []})

    def create():
        data = request.get_json() or {}
        name = (data.get("name") or "").strip().lower()
        if not valid_skill_name(name):
            return jsonify({"error": "name must match ^[a-z][a-z0-9_]{1,59}$"}), 400
        if name in _BUILTIN_NAMES:
            return jsonify({"error": "name collides with a builtin"}), 400
        cols = ["name"] + fields + ["enabled"]
        vals = [name] + [_coerce(data.get(f)) for f in fields] + [bool(data.get("enabled", False))]
        ph = ",".join(["%s"] * len(cols))
        row = execute_db(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({ph}) "
                         f"ON CONFLICT (name) DO NOTHING RETURNING *", tuple(vals))
        if not row:
            return jsonify({"error": "name already exists"}), 409
        return jsonify(row), 201

    def update(rid):
        data = request.get_json() or {}
        sets, vals = [], []
        for f in fields + ["enabled"]:
            if f in data:
                sets.append(f"{f}=%s")
                vals.append(_coerce(data[f]))
        if not sets:
            return jsonify({"error": "No fields"}), 400
        sets.append("updated_at=NOW()")
        vals.append(rid)
        row = execute_db(f"UPDATE {table} SET {', '.join(sets)} WHERE id=%s RETURNING *", tuple(vals))
        if not row:
            return jsonify({"error": "Not found"}), 404
        return jsonify(row)

    def delete(rid):
        execute_db(f"DELETE FROM {table} WHERE id=%s", (rid,))
        return jsonify({"success": True})

    return lst, create, update, delete


def _coerce(v):
    """JSON-encode dict/list values for ::jsonb columns; pass through others."""
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return v


_sql_list, _sql_create, _sql_update, _sql_delete = _crud(
    "custom_sql_skills", ["description", "sql_template", "args_schema_json"])
_web_list, _web_create, _web_update, _web_delete = _crud(
    "custom_webhook_skills", ["description", "url", "method", "headers_json",
                              "args_schema_json", "timeout_seconds"])

bp.add_url_rule("/admin/api/custom-sql", "sql_list", admin_required(_sql_list), methods=["GET"])
bp.add_url_rule("/admin/api/custom-sql", "sql_create", admin_required(_sql_create), methods=["POST"])
bp.add_url_rule("/admin/api/custom-sql/<int:rid>", "sql_update", admin_required(_sql_update), methods=["PUT"])
bp.add_url_rule("/admin/api/custom-sql/<int:rid>", "sql_delete", admin_required(_sql_delete), methods=["DELETE"])
bp.add_url_rule("/admin/api/custom-webhooks", "web_list", admin_required(_web_list), methods=["GET"])
bp.add_url_rule("/admin/api/custom-webhooks", "web_create", admin_required(_web_create), methods=["POST"])
bp.add_url_rule("/admin/api/custom-webhooks/<int:rid>", "web_update", admin_required(_web_update), methods=["PUT"])
bp.add_url_rule("/admin/api/custom-webhooks/<int:rid>", "web_delete", admin_required(_web_delete), methods=["DELETE"])
