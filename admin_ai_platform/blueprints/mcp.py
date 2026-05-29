"""
admin_ai_platform.blueprints.mcp
===============================

MCP connector registry. Admins wire in external MCP servers; we discover their
tools (``tools/list``), cache them, and let the admin enable individual tools +
expose them to the visitor/admin agents.

  * ``GET/POST /admin/api/mcp/servers``            list (creds redacted) / create
  * ``PUT/DELETE /admin/api/mcp/servers/<id>``     edit / remove
  * ``POST /admin/api/mcp/servers/<id>/test``      probe connectivity (tools/list)
  * ``POST /admin/api/mcp/servers/<id>/refresh-tools``  re-sync the tool cache
  * ``GET  /admin/api/mcp/servers/<id>/tools``     cached tools
  * ``PUT  /admin/api/mcp/tools/<tool_id>``        enable/disable one tool

Credentials are never returned by the API (write-only); the column note in
schema.py flags that at-rest encryption is a follow-on hardening.
"""

from __future__ import annotations

from flask import Blueprint, request, jsonify

from ..db import query_db, execute_db
from ..auth import admin_required
from .. import mcp_client

bp = Blueprint("mcp", __name__)

_VALID_TRANSPORT = ("http", "sse")
_VALID_AUTH = ("none", "bearer", "header")


def _redact(row):
    if row and "auth_credential" in row:
        row = dict(row)
        row["auth_credential"] = "***" if row["auth_credential"] else ""
    return row


@bp.route("/admin/api/mcp/servers", methods=["GET"])
@admin_required
def list_servers():
    rows = query_db("SELECT * FROM mcp_servers ORDER BY name") or []
    return jsonify({"servers": [_redact(r) for r in rows]})


@bp.route("/admin/api/mcp/servers", methods=["POST"])
@admin_required
def create_server():
    d = request.get_json() or {}
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    if (d.get("transport") or "http") not in _VALID_TRANSPORT:
        return jsonify({"error": f"transport must be {_VALID_TRANSPORT}"}), 400
    if (d.get("auth_type") or "none") not in _VALID_AUTH:
        return jsonify({"error": f"auth_type must be {_VALID_AUTH}"}), 400
    row = execute_db(
        "INSERT INTO mcp_servers (name, description, transport, url, auth_type, "
        " auth_header_name, auth_credential, enabled, allowed_for_admin, allowed_for_velo) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (name) DO NOTHING RETURNING *",
        (name, d.get("description", ""), d.get("transport", "http"), d.get("url", ""),
         d.get("auth_type", "none"), d.get("auth_header_name", ""), d.get("auth_credential", ""),
         bool(d.get("enabled", True)), bool(d.get("allowed_for_admin", True)),
         bool(d.get("allowed_for_velo", False))))
    if not row:
        return jsonify({"error": "name already exists"}), 409
    return jsonify(_redact(row)), 201


@bp.route("/admin/api/mcp/servers/<int:sid>", methods=["PUT"])
@admin_required
def update_server(sid):
    d = request.get_json() or {}
    cols = ("name", "description", "transport", "url", "auth_type", "auth_header_name",
            "auth_credential", "enabled", "allowed_for_admin", "allowed_for_velo")
    sets, vals = [], []
    for c in cols:
        if c in d:
            # Don't overwrite a stored credential with a redaction placeholder.
            if c == "auth_credential" and d[c] in ("***", None):
                continue
            sets.append(f"{c}=%s")
            vals.append(d[c])
    if not sets:
        return jsonify({"error": "No fields"}), 400
    sets.append("updated_at=NOW()")
    vals.append(sid)
    row = execute_db(f"UPDATE mcp_servers SET {', '.join(sets)} WHERE id=%s RETURNING *", tuple(vals))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(_redact(row))


@bp.route("/admin/api/mcp/servers/<int:sid>", methods=["DELETE"])
@admin_required
def delete_server(sid):
    execute_db("DELETE FROM mcp_servers WHERE id=%s", (sid,))
    return jsonify({"success": True})


def _probe_and_store(sid):
    server = query_db("SELECT * FROM mcp_servers WHERE id=%s", (sid,), fetchone=True)
    if not server:
        return None, None
    ok, payload = mcp_client.list_tools(server)
    execute_db("UPDATE mcp_servers SET last_test_at=NOW(), last_test_ok=%s, last_test_error=%s "
               "WHERE id=%s", (ok, "" if ok else str(payload)[:300], sid))
    return ok, payload


@bp.route("/admin/api/mcp/servers/<int:sid>/test", methods=["POST"])
@admin_required
def test_server(sid):
    ok, payload = _probe_and_store(sid)
    if ok is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": ok, "tool_count": len(payload) if ok else 0,
                    "error": None if ok else payload})


@bp.route("/admin/api/mcp/servers/<int:sid>/refresh-tools", methods=["POST"])
@admin_required
def refresh_tools(sid):
    ok, payload = _probe_and_store(sid)
    if ok is None:
        return jsonify({"error": "Not found"}), 404
    if not ok:
        return jsonify({"ok": False, "error": payload}), 502
    for t in payload:
        execute_db(
            "INSERT INTO mcp_tools_cache (server_id, tool_name, description, input_schema_json, last_synced_at) "
            "VALUES (%s,%s,%s,%s::jsonb,NOW()) "
            "ON CONFLICT (server_id, tool_name) DO UPDATE SET "
            " description=EXCLUDED.description, input_schema_json=EXCLUDED.input_schema_json, "
            " last_synced_at=NOW()",
            (sid, t["name"], t.get("description", ""),
             __import__("json").dumps(t.get("input_schema") or {})))
    return jsonify({"ok": True, "synced": len(payload)})


@bp.route("/admin/api/mcp/servers/<int:sid>/tools", methods=["GET"])
@admin_required
def server_tools(sid):
    rows = query_db("SELECT * FROM mcp_tools_cache WHERE server_id=%s ORDER BY tool_name", (sid,))
    return jsonify({"tools": rows or []})


@bp.route("/admin/api/mcp/tools/<int:tool_id>", methods=["PUT"])
@admin_required
def toggle_tool(tool_id):
    d = request.get_json() or {}
    row = execute_db("UPDATE mcp_tools_cache SET enabled=%s WHERE id=%s RETURNING *",
                     (bool(d.get("enabled", True)), tool_id))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)
