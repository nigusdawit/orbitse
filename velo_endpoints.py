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
import hmac
import hashlib
import time
import threading
import traceback
from flask import Blueprint, request, jsonify

velo_bp = Blueprint("velo", __name__, url_prefix="/api/velo")
VELO_AGENT_KEY = os.environ.get("VELO_AGENT_KEY", "").strip()

# ---------------------------------------------------------------------------
# Dynamic command registry — handlers register themselves via @velo_command
# ---------------------------------------------------------------------------
_command_handlers = {}


# Capability-discovery aliases. VELO Master (and any modern tool gateway —
# LangChain Tools API, MCP servers, OpenAPI tool routers) doesn't necessarily
# know our capability list ahead of time; on first contact it probes by
# sending one of these strings as the `command` field, expecting back the
# tool catalogue. Without this mapping, those probes hit the unknown-command
# branch and the master's UI shows "no tools discovered" even though we
# have 30+ registered handlers — exactly the regression that motivated the
# audit-log entries `cmd=''` and `cmd='list'` returning 400 in late April.
# Both lower-cased before lookup; an empty string is the most common probe.
_DISCOVERY_ALIASES = frozenset({
    "", "list", "list_commands", "list_tools", "tools",
    "discover", "discovery", "capabilities", "help",
    "describe", "?", "ls", "show",
})


# Single source of truth for agent IDs. Used by _discovery_payload, by the
# wildcard 404 hint, and as the default for /chat (POST). Centralised so a
# future addition (e.g. a third logical agent) only needs to land in one
# place; previously the same list was duplicated across three response
# bodies and at least one boot-time registration block, an obvious drift
# magnet flagged in code review.
AGENT_IDS = ["admin_ai", "visitor_ai"]


def velo_command(name, description="", params_schema=None, requires_confirmation=False):
    """Decorator to register a callable as a VELO command handler.

    requires_confirmation=True opts a handler into a stateless two-step
    confirm flow. The first call returns {"status": "confirmation_required",
    "confirm_token": "..."}; the master must echo the token back inside
    `params.confirm_token` within ~2 minutes for the handler to actually run.
    Use this for any destructive write (delete, refund, send-to-customers,
    plan/pricing changes) so a master-side bug or stale automation can't
    immediately wipe state.
    """
    def decorator(func):
        _command_handlers[name] = {
            "handler": func,
            "description": description,
            "params_schema": params_schema or {},
            "requires_confirmation": bool(requires_confirmation),
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
            "requires_confirmation": info.get("requires_confirmation", False),
        }
        for name, info in _command_handlers.items()
    ]


def _discovery_payload():
    """Build the canonical capability-discovery payload that VELO Master
    (or any tool gateway) uses to learn what this client can do.

    Centralised so every discovery surface — POST /command with an empty
    or list-style command, GET /command, GET /tools, GET /capabilities,
    and the wildcard 404 hint — returns the SAME shape. Drift between
    those surfaces is exactly how clients end up "knowing" about a tool
    on one endpoint but not another, which is what bit us originally.

    Includes fully-qualified URLs (using request.host_url) for every
    velo endpoint so the master never has to guess base paths or
    auto-derive per-agent URLs that don't exist on this app.
    """
    base = request.host_url.rstrip("/") if request else ""
    return {
        "client_name": "AI Concierge Platform",
        "agent_ids": list(AGENT_IDS),
        "command_endpoint": f"{base}/api/velo/command",
        "chat_endpoint": f"{base}/api/velo/chat",
        "status_endpoint": f"{base}/api/velo/status",
        "tools_endpoint": f"{base}/api/velo/tools",
        "total": len(_command_handlers),
        "commands": [
            {
                "name": name,
                "description": info.get("description", ""),
                "requires_confirmation": info.get("requires_confirmation", False),
                "params_schema": info.get("params_schema", {}),
            }
            for name, info in sorted(_command_handlers.items())
        ],
        "usage": {
            "structured_command": (
                f'POST {base}/api/velo/command with body '
                '{"command": "<name>", "params": {...}}'
            ),
            "free_text_chat": (
                f'POST {base}/api/velo/chat with body '
                '{"message": "<text>", "agent_id": "admin_ai" or "visitor_ai"}'
            ),
            "discovery": (
                "Re-fetch this payload anytime via "
                f"GET {base}/api/velo/tools, GET {base}/api/velo/capabilities, "
                f"GET {base}/api/velo/command, or POST {base}/api/velo/command "
                "with an empty/list-style command field. All require the "
                "same Authorization: Bearer <VELO_AGENT_KEY> header."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Stateless confirmation tokens
# ---------------------------------------------------------------------------
# We sign HMAC(VELO_AGENT_KEY, command + sorted_params + window_bucket).
# `window_bucket` is the current 60-second slot, so a token is good for
# 60–120 seconds depending on when it was minted. Two minutes is plenty
# for an operator/master round-trip and short enough that an intercepted
# token can't be replayed days later.
_CONFIRM_WINDOW_SECONDS = 60


def _confirm_signing_key():
    """Falls back to a fixed dev string when VELO_AGENT_KEY is unset so
    confirm-tokens still work in local dev. The real security bound here
    is the bearer-auth check in verify_velo_key()."""
    return (VELO_AGENT_KEY or "velo-dev-confirm-key").encode("utf-8")


def _params_for_signing(params):
    """Strip confirm_token before hashing so the token from call #1 still
    verifies on call #2 when the master adds it back into params."""
    p = dict(params or {})
    p.pop("confirm_token", None)
    return json.dumps(p, sort_keys=True, default=str)


def _make_confirm_token(command, params, bucket=None):
    if bucket is None:
        bucket = int(time.time() // _CONFIRM_WINDOW_SECONDS)
    msg = f"{command}|{_params_for_signing(params)}|{bucket}".encode("utf-8")
    return hmac.new(_confirm_signing_key(), msg, hashlib.sha256).hexdigest()


# Single-use token cache. Without it, the same valid confirm_token could
# be replayed multiple times within the 60–120s window — e.g. a master-side
# retry loop firing send_email twice. We keep `(token → expires_at)` and
# evict opportunistically; the cache is bounded by `_CONFIRM_LIFETIME` so
# it can never grow unbounded.
_USED_CONFIRM_TOKENS = {}
_USED_CONFIRM_LOCK = threading.Lock()
_CONFIRM_LIFETIME = _CONFIRM_WINDOW_SECONDS * 2  # matches verify window


def _consume_confirm_token(token):
    """Return True if this is the first time we've seen `token`. Mark it
    used so subsequent verifications fail. Called only after the HMAC
    check has already succeeded — replay defence for outbound/destructive
    commands like send_email and refund_order."""
    now = time.time()
    with _USED_CONFIRM_LOCK:
        # Evict expired entries while we hold the lock; cheap because the
        # cache is small (≤ a few entries per minute under normal load).
        for k in [t for t, exp in _USED_CONFIRM_TOKENS.items() if exp <= now]:
            _USED_CONFIRM_TOKENS.pop(k, None)
        if token in _USED_CONFIRM_TOKENS:
            return False
        _USED_CONFIRM_TOKENS[token] = now + _CONFIRM_LIFETIME
        return True


def _verify_confirm_token(command, params, token):
    if not token:
        return False
    now_bucket = int(time.time() // _CONFIRM_WINDOW_SECONDS)
    # Accept current OR previous bucket → effective lifetime 60–120s.
    for bucket in (now_bucket, now_bucket - 1):
        expected = _make_confirm_token(command, params, bucket=bucket)
        if hmac.compare_digest(token, expected):
            # Single-use guard: a token verifies only once. Subsequent
            # presentations get treated as expired/invalid.
            return _consume_confirm_token(token)
    return False


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
@velo_bp.route("/command", methods=["POST", "GET"])
def handle_command():
    """VELO posts a command + params here; we route to a registered handler.

    GET on this URL returns the same discovery payload as /tools — needed
    because some master gateways probe with GET to test connectivity, and
    without this they'd fall through to the homepage catch-all (which would
    return HTML 200 and look like "no velo here"). The GET branch is auth-
    gated like the POST branch; nothing leaks that wasn't already in the
    capability registration payload sent at boot.
    """
    if not verify_velo_key():
        return jsonify({"error": "unauthorized"}), 401

    if request.method == "GET":
        return jsonify({"status": "ok", "result": _discovery_payload()}), 200

    data = request.get_json(silent=True) or {}
    raw_command = data.get("command", "")
    command = raw_command if isinstance(raw_command, str) else ""
    params = data.get("params", {}) or {}

    # Capability-discovery fast-path. VELO Master probes for tools by
    # sending command="" or command="list"/"tools"/"capabilities"/etc.
    # Without this, those probes hit the unknown-command branch and the
    # master concludes the client has no tools at all — even though we
    # have 30+ registered handlers. The audit log proved this was the
    # actual failure mode in production.
    #
    # NOT audited: discovery is high-frequency master polling whose
    # response is fully deterministic from the registry (zero per-call
    # context), so logging every hit only adds bloat. If a per-poll
    # audit ever becomes useful (rate-limit triage, master fingerprint
    # tracking) it can be re-added here under a synthetic command name
    # so it stays filterable from real-command history.
    if command.strip().lower() in _DISCOVERY_ALIASES:
        return jsonify({"status": "ok", "result": _discovery_payload()}), 200

    handler_info = _command_handlers.get(command)
    if not handler_info:
        _audit(command, params, "error", error_msg="unknown command")
        base = request.host_url.rstrip("/")
        return jsonify({
            "error": f"Unknown command: {command!r}",
            "hint": (
                "For free-text or conversational requests, POST "
                f'{{"message": "...", "agent_id": "admin_ai"}} to {base}/api/velo/chat. '
                "To list available structured commands, POST "
                f'{{"command": "list"}} to {base}/api/velo/command, '
                f"or GET {base}/api/velo/tools."
            ),
            "available_commands": sorted(_command_handlers.keys()),
            "command_endpoint": f"{base}/api/velo/command",
            "chat_endpoint": f"{base}/api/velo/chat",
        }), 400

    # Two-step confirmation gate for destructive handlers. The handler is
    # only invoked when the master echoes back a freshly-minted token; the
    # first call returns the token + a short preview so the master can
    # show its operator what is about to happen.
    if handler_info.get("requires_confirmation"):
        confirm_token = (params or {}).get("confirm_token")
        if not confirm_token:
            new_token = _make_confirm_token(command, params)
            preview_params = {k: v for k, v in (params or {}).items() if k != "confirm_token"}
            _audit(command, params, "ok", result_summary="confirmation_token_issued")
            return jsonify({
                "status": "confirmation_required",
                "command": command,
                "confirm_token": new_token,
                "expires_in_seconds": _CONFIRM_WINDOW_SECONDS * 2,
                "preview_params": preview_params,
                "message": (
                    "This command is destructive and requires confirmation. "
                    "Re-send the same call with `confirm_token` included in params."
                ),
            }), 200
        if not _verify_confirm_token(command, params, confirm_token):
            _audit(command, params, "error", error_msg="invalid or expired confirm_token")
            return jsonify({
                "status": "error",
                "error": (
                    "invalid or expired confirm_token — request a new one by "
                    "calling this command without confirm_token"
                ),
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


@velo_bp.route("/chat", methods=["POST", "GET"])
def handle_chat():
    """Natural-language channel for VELO Master.

    VELO posts {"message": "...", "from": "...", "agent_id": "admin_ai"}
    and we run the message through this install's Claude client. The
    structured /command endpoint is for data-heavy operations; this is
    for conversational queries ("what MCP servers do you have running?")
    where the AI itself decides how to answer using its own context.

    GET returns a usage hint instead of 405, so master gateways probing
    this URL for connectivity get a self-describing response.
    """
    if not verify_velo_key():
        return jsonify({"error": "unauthorized"}), 401

    if request.method == "GET":
        base = request.host_url.rstrip("/")
        return jsonify({
            "status": "ok",
            "endpoint": "chat",
            "method": "POST",
            "url": f"{base}/api/velo/chat",
            "body_schema": {
                "message": "string (required, the user's natural-language text)",
                "agent_id": "'admin_ai' (default) or 'visitor_ai'",
                "from": "string (optional, identifier of who is speaking on the master side)",
            },
            "agent_ids": list(AGENT_IDS),
            "discovery_endpoint": f"{base}/api/velo/tools",
        }), 200

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
    gated = sorted(
        name for name, info in _command_handlers.items()
        if info.get("requires_confirmation")
    )
    return jsonify({
        "status": "ok",
        "available_commands": sorted(_command_handlers.keys()),
        "command_count": len(_command_handlers),
        "gated_commands": gated,
        "uptime_seconds": uptime_seconds,
    })


@velo_bp.route("/tools", methods=["GET"])
@velo_bp.route("/capabilities", methods=["GET"])
def list_tools():
    """Discovery-by-GET aliases.

    Some master gateways probe with GET /tools or GET /capabilities
    (the OpenAPI / MCP convention) instead of the POST /command empty-
    discovery path. Without these routes, those probes fall through
    to the homepage catch-all which serves HTML 200 — the gateway
    parses HTML as garbage and reports "no tools at this URL".
    Returning the canonical discovery payload here lets the gateway
    self-orient on first contact.

    Auth-gated like /status because the descriptions of confirmation-
    gated commands (refund, send-to-customers) hint at the destructive
    surface of the app and shouldn't be enumerable by unauthenticated
    callers — and the master always carries the bearer token anyway.
    """
    if not verify_velo_key():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"status": "ok", "result": _discovery_payload()})


@velo_bp.route("/", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@velo_bp.route("/<path:rest>",
               methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def velo_unmatched(rest=""):
    """Catch-all for any /api/velo/<unrecognised path>.

    Without this, two annoying failure modes happen on probe traffic:
      1. GET /api/velo/admin_ai (or any other unknown path) falls
         through to the homepage catch-all serve_index() and returns
         HTML 200. The master parses HTML as garbage and reports
         "no tools at this URL" or similar.
      2. POST /api/velo/admin_ai (master auto-derives per-agent URLs
         that don't exist on this app) hits the GET-only homepage
         catch-all and returns HTTP 405. The master surfaces "405 —
         that command isn't supported that way" with no hint about
         what URL it SHOULD be using. This was the literal failure
         a real master operator saw on April 28.

    Returning a structured 404 JSON with the canonical endpoint URLs
    and method hints lets the master self-correct on the next probe
    instead of giving up. NOT auth-gated because the response carries
    no sensitive info — it's a self-describing routing hint identical
    in principle to a 404 page on a public website.

    Routing precedence: Flask prefers the more specific route, so
    exact matches like /command, /chat, /status, /tools, /capabilities,
    and /refresh-registration still win against this wildcard for
    every method registered on those routes. The wildcard only fires
    for paths NONE of the named routes recognise.

    Pinned by TestVeloUnmatchedRoutes in tests/test_velo_master_communication.py.
    """
    base = request.host_url.rstrip("/")
    return jsonify({
        "error": f"No such VELO endpoint: /api/velo/{rest}",
        "hint": (
            "This URL isn't a recognised VELO endpoint on this client. "
            "The canonical endpoints are listed below — note the methods. "
            "For tool discovery, GET /tools. For structured commands, "
            "POST /command with {command, params}. For free-text chat, "
            "POST /chat with {message, agent_id}."
        ),
        "endpoints": {
            "tools":          {"method": "GET",  "url": f"{base}/api/velo/tools"},
            "capabilities":   {"method": "GET",  "url": f"{base}/api/velo/capabilities"},
            "status":         {"method": "GET",  "url": f"{base}/api/velo/status"},
            "command":        {"method": "POST", "url": f"{base}/api/velo/command"},
            "chat":           {"method": "POST", "url": f"{base}/api/velo/chat"},
            "refresh_registration": {"method": "POST", "url": f"{base}/api/velo/refresh-registration"},
        },
        "agent_ids": list(AGENT_IDS),
    }), 404


@velo_bp.route("/refresh-registration", methods=["POST"])
def refresh_registration():
    """Re-publish this install's full capability list to VELO Master.

    The "dynamic" piece of the dynamic registry. Adding a new command is
    just dropping a `@velo_command(...)` function — but until the master
    is told, it doesn't know the command exists. Hitting this endpoint
    re-runs the registration flow without restarting Flask or waiting
    for the boot-time `_VELO_REGISTRATION_TRIGGERED` flag to flip.

    Useful after deploying a new handler, after an admin enables/disables
    a feature group, or as a recovery path if the master lost state.
    """
    if not verify_velo_key():
        return jsonify({"error": "unauthorized"}), 401
    try:
        from app import register_with_velo
        result = register_with_velo(force=True) or {}
        return jsonify({
            "status": "ok",
            "command_count": len(_command_handlers),
            "commands": sorted(_command_handlers.keys()),
            "registration": result,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "error": str(e)}), 500
