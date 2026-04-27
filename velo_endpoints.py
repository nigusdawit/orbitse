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


@velo_bp.route("/chat", methods=["POST"])
def handle_chat():
    """Natural-language channel for VELO Master.

    VELO posts {"message": "...", "from": "...", "agent_id": "admin_ai"}
    and we run the message through this install's Claude client. The
    structured /command endpoint is for data-heavy operations; this is
    for conversational queries ("what MCP servers do you have running?")
    where the AI itself decides how to answer using its own context.
    """
    if not verify_velo_key():
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    from_agent = data.get("from", "unknown")
    agent_id = data.get("agent_id", "admin_ai")

    if not message:
        return jsonify({"error": "message required"}), 400

    audit_params = {
        "agent_id": agent_id,
        "from": from_agent,
        "message": message[:500],
    }
    try:
        response_text = process_ai_message(
            message, agent_id=agent_id, context={"from": from_agent}
        )
        _audit("chat", audit_params, "ok", result_summary=response_text[:500])
        return jsonify({
            "status": "ok",
            "agent_id": agent_id,
            "response": response_text,
        })
    except Exception as e:
        traceback.print_exc()
        _audit("chat", audit_params, "error", error_msg=str(e))
        return jsonify({"status": "error", "error": str(e)}), 500


def process_ai_message(message: str, agent_id: str, context: dict) -> str:
    """Send `message` through Claude as `agent_id` and return its reply.

    The system prompt seeds the model with (a) which logical agent it is,
    (b) who it is talking to, and (c) the live list of structured /command
    capabilities so it can describe itself accurately and steer the
    operator toward /command for data-heavy actions. We deliberately do
    NOT give the model any tools here — keeping this endpoint to a single
    one-shot LLM call means VELO's chat traffic can never trigger
    side-effects, only structured /command can.
    """
    # Late import — avoids circular dependency at module load time and
    # also lets us pick up a client that's been re-initialized on reload.
    from app import anthropic_client

    if anthropic_client is None:
        # Fail explicit, not silent: the operator should know AI is off
        # on this install rather than getting back a vague placeholder.
        cmds = ", ".join(sorted(_command_handlers.keys())) or "(none)"
        return (
            "AI chat is not configured on this install "
            "(ANTHROPIC_API_KEY missing). Use the structured /api/velo/command "
            f"endpoint instead. Registered commands: {cmds}."
        )

    # Build a compact capability listing so the model can answer
    # "what can you do?" honestly without us hard-coding a description.
    cap_lines = [
        f"  - {name}: {info['description'] or '(no description)'}"
        for name, info in sorted(_command_handlers.items())
    ]
    cap_block = "\n".join(cap_lines) if cap_lines else "  (none registered)"

    role_hint = {
        "admin_ai": "the admin/ops agent (full backend access)",
        "visitor_ai": "the visitor-facing agent (public site experience)",
    }.get(agent_id, f"the '{agent_id}' agent")

    system_prompt = (
        f"You are {agent_id}, {role_hint} embedded inside an AI Concierge "
        "platform (Flask + Postgres) that is bridged to VELO Master. "
        f"VELO Master is relaying a message on behalf of '{context.get('from', 'unknown')}'. "
        "Reply concisely — a few sentences unless detail is explicitly requested. "
        "You may describe the platform, your role, and your capabilities. For "
        "data-heavy or state-changing actions, instruct the operator to call "
        "your structured /api/velo/command endpoint. Your registered "
        "structured commands are:\n"
        f"{cap_block}\n"
        "Do not invent capabilities you do not have. If the operator asks for "
        "something you cannot do from this conversational channel, say so and "
        "point them at the structured command (or note that the capability "
        "isn't available)."
    )

    # 25s timeout matches the existing _websearch_anthropic budget — long
    # enough for a real answer, short enough that VELO never hangs on us.
    resp = anthropic_client.with_options(timeout=25.0).messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": message}],
    )

    # Record token usage in the cost ledger so VELO chat traffic shows up
    # in the same admin dashboard tile as the rest of the app's Anthropic
    # spend. Mirrors the pattern in app.py's _websearch_anthropic; never
    # raises — a ledger failure must not break the chat reply itself.
    try:
        from app import record_chat_cost
        u = getattr(resp, "usage", None)
        if u is not None:
            record_chat_cost(
                surface="velo_chat",
                provider="anthropic",
                model="claude-sonnet-4-5",
                prompt_tokens=getattr(u, "input_tokens", 0),
                completion_tokens=getattr(u, "output_tokens", 0),
            )
    except Exception as _ce:
        print(f"[velo] cost ledger write failed: {_ce}")

    parts = []
    for block in (resp.content or []):
        if getattr(block, "type", None) == "text":
            txt = getattr(block, "text", "") or ""
            if txt:
                parts.append(txt)
    return " ".join(parts).strip() or "(no response)"


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
