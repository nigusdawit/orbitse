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

import json
import secrets
from urllib.parse import urlencode

from flask import Blueprint, request, jsonify, redirect

from .. import config
from ..db import query_db, execute_db
from ..auth import admin_required
from .. import mcp_client

bp = Blueprint("mcp", __name__)

_VALID_TRANSPORT = ("http", "sse")
_VALID_AUTH = ("none", "bearer", "header", "oauth")

# Known OAuth connector blueprints. An admin picks one (or "custom" and fills the
# endpoints manually); oauth/start reads these defaults. authorize_url/token_url
# are the provider's standard OAuth2 endpoints.
CONNECTOR_BLUEPRINTS = {
    "notion": {"label": "Notion", "authorize_url": "https://api.notion.com/v1/oauth/authorize",
               "token_url": "https://api.notion.com/v1/oauth/token", "scopes": ""},
    "github": {"label": "GitHub", "authorize_url": "https://github.com/login/oauth/authorize",
               "token_url": "https://github.com/login/oauth/access_token", "scopes": "repo read:user"},
    "google_drive": {"label": "Google Drive",
                     "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
                     "token_url": "https://oauth2.googleapis.com/token",
                     "scopes": "https://www.googleapis.com/auth/drive.readonly"},
    "slack": {"label": "Slack", "authorize_url": "https://slack.com/oauth/v2/authorize",
              "token_url": "https://slack.com/api/oauth.v2.access", "scopes": "channels:read"},
}


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


# ==========================================================================
# OAuth (M14): connect an OAuth2 MCP connector. oauth_state JSONB holds the
# in-flight CSRF state + the provider's OAuth config + (after callback) tokens.
# auth_credential stores the bearer token the client sends per request.
# ==========================================================================
@bp.route("/admin/api/mcp/connectors", methods=["GET"])
@admin_required
def list_connectors():
    """Available OAuth connector blueprints for the 'Connect…' picker."""
    return jsonify({"connectors": [
        {"type": k, "label": v["label"], "scopes": v["scopes"]}
        for k, v in CONNECTOR_BLUEPRINTS.items()]})


def _redirect_uri():
    base = (config.PUBLIC_BASE_URL or request.host_url.rstrip("/")).rstrip("/")
    return f"{base}/admin/oauth/mcp/callback"


@bp.route("/admin/api/mcp/servers/<int:sid>/oauth/start", methods=["POST"])
@admin_required
def oauth_start(sid):
    """Begin the OAuth2 Authorization Code flow. Body (or the connector blueprint)
    supplies client_id/secret/authorize_url/token_url/scopes. Returns the
    authorize_url the admin's browser should visit; a single-use ``state`` is
    stored on the server row to defend the callback against CSRF."""
    server = query_db("SELECT * FROM mcp_servers WHERE id=%s", (sid,), fetchone=True)
    if not server:
        return jsonify({"error": "Not found"}), 404
    d = request.get_json() or {}
    bp_cfg = CONNECTOR_BLUEPRINTS.get((server.get("connector_type") or "").lower(), {})
    authorize_url = (d.get("authorize_url") or bp_cfg.get("authorize_url") or "").strip()
    token_url = (d.get("token_url") or bp_cfg.get("token_url") or "").strip()
    client_id = (d.get("client_id") or "").strip()
    client_secret = (d.get("client_secret") or "").strip()
    scopes = (d.get("scopes") or bp_cfg.get("scopes") or "").strip()
    if not (authorize_url and token_url and client_id):
        return jsonify({"error": "authorize_url, token_url and client_id are required"}), 400

    state = secrets.token_urlsafe(24)
    oauth_cfg = {"state": state, "token_url": token_url, "client_id": client_id,
                 "client_secret": client_secret, "scopes": scopes,
                 "redirect_uri": _redirect_uri(), "connected": False}
    execute_db("UPDATE mcp_servers SET oauth_state=%s::jsonb, auth_type='oauth' WHERE id=%s",
               (json.dumps(oauth_cfg), sid))
    params = {"response_type": "code", "client_id": client_id,
              "redirect_uri": _redirect_uri(), "state": state}
    if scopes:
        params["scope"] = scopes
    return jsonify({"authorize_url": f"{authorize_url}?{urlencode(params)}", "state": state})


@bp.route("/admin/oauth/mcp/callback", methods=["GET"])
@admin_required
def oauth_callback():
    """OAuth2 redirect target. Matches the ``state`` back to a server row (CSRF
    guard), exchanges the code for an access token, and stores it. Token exchange
    needs network; on failure we record the error and still redirect so the admin
    sees the result in the UI."""
    code = (request.args.get("code") or "").strip()
    state = (request.args.get("state") or "").strip()
    if not (code and state):
        return jsonify({"error": "missing code/state"}), 400
    server = query_db("SELECT * FROM mcp_servers WHERE oauth_state->>'state' = %s",
                      (state,), fetchone=True)
    if not server:
        return jsonify({"error": "unknown or expired state"}), 400
    cfg = server.get("oauth_state") or {}
    if isinstance(cfg, str):
        cfg = json.loads(cfg)

    token, err = None, None
    try:
        import httpx
        r = httpx.post(cfg["token_url"], data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": cfg.get("redirect_uri", ""), "client_id": cfg.get("client_id", ""),
            "client_secret": cfg.get("client_secret", "")},
            headers={"Accept": "application/json"}, timeout=15.0)
        r.raise_for_status()
        token = (r.json() or {}).get("access_token")
    except Exception as e:
        err = str(e)[:300]

    # Rotate the state (single-use) regardless of outcome.
    cfg["state"] = ""
    cfg["connected"] = bool(token)
    cfg["last_error"] = err or ""
    sets = ["oauth_state=%s::jsonb"]
    vals = [json.dumps(cfg)]
    if token:
        sets += ["auth_credential=%s", "auth_header_name=%s", "auth_type='bearer'"]
        vals += [token, "Authorization"]
    vals.append(server["id"])
    execute_db(f"UPDATE mcp_servers SET {', '.join(sets)} WHERE id=%s", tuple(vals))
    return redirect(f"/admin?mcp_oauth={'connected' if token else 'failed'}")


@bp.route("/admin/api/mcp/servers/<int:sid>/oauth/disconnect", methods=["POST"])
@admin_required
def oauth_disconnect(sid):
    """Clear stored OAuth tokens + state for a server (revokes our copy)."""
    row = execute_db(
        "UPDATE mcp_servers SET auth_credential='', oauth_state='{}'::jsonb, auth_type='none' "
        "WHERE id=%s RETURNING id", (sid,))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"success": True})
