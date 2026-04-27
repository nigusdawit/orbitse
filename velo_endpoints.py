"""
VELO Command Receiver — inbound endpoints VELO Master calls to drive this app.

Two routes, mounted at /api/velo by app.py:
    POST /api/velo/command  — VELO sends {"command": "...", "params": {...}}
    GET  /api/velo/status   — VELO health-checks the agent

Adding a new capability is just writing a function decorated with
@velo_command. On next startup, register_with_velo() in app.py will
re-publish the full capability list to VELO master.

Auth: a single shared bearer token VELO_AGENT_KEY. If the env var is
empty, auth is disabled (dev convenience). Once set, every request must
carry "Authorization: Bearer <key>".

Every successful or failed command dispatch is written to the
velo_audit_log table for traceability.
"""

import os
import json
import traceback
from flask import Blueprint, request, jsonify

velo_bp = Blueprint("velo", __name__, url_prefix="/api/velo")
VELO_AGENT_KEY = os.environ.get("VELO_AGENT_KEY", "").strip()

# ---------------------------------------------------------------------------
# Dynamic command registry — handlers register themselves via @velo_command
# ---------------------------------------------------------------------------
_command_handlers = {}


def velo_command(name, description="", params_schema=None):
    """Decorator to register a callable as a VELO command handler."""
    def decorator(func):
        _command_handlers[name] = {
            "handler": func,
            "description": description,
            "params_schema": params_schema or {},
        }
        return func
    return decorator


def get_registered_capabilities():
    """Return all currently-registered capabilities for VELO registration."""
    return [
        {
            "name": name,
            "description": info["description"],
            "params_schema": info["params_schema"],
        }
        for name, info in _command_handlers.items()
    ]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def verify_velo_key():
    """Bearer-token check.

    Empty VELO_AGENT_KEY = auth disabled, but ONLY in dev. In production
    (REPLIT_DEPLOYMENT is set on the deployed instance) an unset key
    fails closed and every request is rejected — that way a missing key
    on deploy can never accidentally expose state-changing handlers like
    manage_features or update_faq to the public.
    """
    if not VELO_AGENT_KEY:
        if os.environ.get("REPLIT_DEPLOYMENT"):
            return False
        return True  # dev convenience
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    return auth[7:] == VELO_AGENT_KEY


# ---------------------------------------------------------------------------
# Audit logging — fail-soft: if we can't write the log row, the command
# still runs. We never block command execution on audit-log failure.
# ---------------------------------------------------------------------------
def _audit(command, params, status, result_summary="", error_msg=""):
    try:
        # Late import to avoid circular dependency with app.py.
        from app import execute_db
        execute_db(
            "INSERT INTO velo_audit_log "
            "(command, params, status, result_summary, error_msg, actor) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                command,
                json.dumps(params or {}),
                status,
                (result_summary or "")[:500],
                (error_msg or "")[:1000],
                "velo",
            ),
        )
    except Exception as e:
        print(f"[velo] audit log write failed: {e}")


# ---------------------------------------------------------------------------
# Single dynamic command endpoint
# ---------------------------------------------------------------------------
@velo_bp.route("/command", methods=["POST"])
def handle_command():
    """VELO posts a command + params here; we route to a registered handler."""
    if not verify_velo_key():
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    command = data.get("command", "")
    params = data.get("params", {}) or {}

    handler_info = _command_handlers.get(command)
    if not handler_info:
        _audit(command, params, "error", error_msg="unknown command")
        return jsonify({
            "error": f"Unknown command: {command}",
            "available_commands": sorted(_command_handlers.keys()),
        }), 400

    try:
        result = handler_info["handler"](params)
        # Compact, json-safe summary for the audit log.
        try:
            summary = json.dumps(result, default=str)
        except Exception:
            summary = str(result)
        _audit(command, params, "ok", result_summary=summary)
        return jsonify({"status": "ok", "result": result})
    except Exception as e:
        traceback.print_exc()
        _audit(command, params, "error", error_msg=str(e))
        return jsonify({"status": "error", "error": str(e)}), 500


@velo_bp.route("/status", methods=["GET"])
def app_status():
    """Lightweight health check VELO can poll."""
    if not verify_velo_key():
        return jsonify({"error": "unauthorized"}), 401
    # Late import for the runtime stats we expose.
    try:
        from app import VELO_APP_START_TIME
        import time as _time
        uptime_seconds = int(_time.time() - VELO_APP_START_TIME)
    except Exception:
        uptime_seconds = None
    return jsonify({
        "status": "ok",
        "available_commands": sorted(_command_handlers.keys()),
        "uptime_seconds": uptime_seconds,
    })
