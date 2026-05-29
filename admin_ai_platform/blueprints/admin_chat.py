"""
admin_ai_platform.blueprints.admin_chat
=======================================

The admin AI assistant — an elevated, state-aware agent for the dashboard.
Reads run immediately; writes are parked as pending actions the owner approves.

  * ``POST /admin/api/chat/stream``            SSE admin chat (tool loop)
  * ``GET  /admin/api/chat/history``           messages for a session
  * ``POST /admin/api/chat/clear``             clear a session's messages
  * ``GET  /admin/api/chat/action/<id>``       pending-action detail
  * ``POST /admin/api/chat/action/<id>/approve`` execute the parked write
  * ``POST /admin/api/chat/action/<id>/reject``  discard it

All routes are @admin_required.
"""

from __future__ import annotations

import json

from flask import Blueprint, request, jsonify, Response, stream_with_context

from .. import llm
from ..db import query_db, execute_db
from ..cost import record_chat_cost
from ..auth import admin_required
from ..admin_tools import (ADMIN_TOOLS, execute_admin_tool, approve_action,
                           reject_action)
from ..chat_runtime import (parse_command_from_text, stream_round_openai,
                            stream_round_claude, messages_for_claude, tools_for_claude)

bp = Blueprint("admin_chat", __name__)

MAX_ROUNDS = 5
HISTORY_TURNS = 30

ADMIN_SYSTEM_PROMPT = """\
You are the admin assistant for this AI-concierge platform — an expert operator
helping the owner manage their site's data and configuration.

Use the READ tools (admin_list_tables, admin_describe_table, admin_run_sql,
admin_overview_stats) freely to answer questions about the site's data. Always
admin_describe_table before proposing a write so your column names are correct.

For ANY change to the data, you MUST use the admin_propose_* tools. They DO NOT
write anything — they park a preview the owner approves with a button. NEVER
claim a change was made until it is approved; instead say you've proposed it and
it's awaiting their approval. Be concise, accurate, and never invent data —
query for it. Format replies with markdown.
"""


@bp.route("/admin/api/chat/stream", methods=["POST"])
@admin_required
def admin_chat_stream():
    if llm.openai_client is None and llm.anthropic_client is None:
        return jsonify({"error": "No LLM provider configured"}), 503
    data = request.get_json() or {}
    message = (data.get("message") or "").strip()
    session_id = (data.get("session_id") or "admin_default").strip()
    if not message:
        return jsonify({"error": "Message is required"}), 400

    try:
        provider, model = llm.get_active_llm_provider()
    except Exception as e:
        return jsonify({"error": str(e)}), 503

    # Build messages: system + persisted history for this session + new turn.
    messages = [{"role": "system", "content": ADMIN_SYSTEM_PROMPT}]
    prior = query_db(
        "SELECT role, content FROM admin_chat_messages "
        "WHERE session_id=%s AND mode='admin' AND role IN ('user','assistant') "
        "ORDER BY created_at DESC, id DESC LIMIT %s", (session_id, HISTORY_TURNS)) or []
    for m in reversed(prior):
        messages.append({"role": m["role"], "content": m["content"] or ""})
    messages.append({"role": "user", "content": message})

    execute_db("INSERT INTO admin_chat_messages (session_id, mode, role, content) "
               "VALUES (%s,'admin','user',%s)", (session_id, message))

    def generate():
        full_text = ""
        pending = []
        try:
            for _round in range(MAX_ROUNDS):
                round_text = ""
                tcs = []
                finish_reason = None
                if provider == "claude":
                    sys_str, cmsgs = messages_for_claude(messages)
                    it = stream_round_claude(model, sys_str, cmsgs, tools_for_claude(ADMIN_TOOLS))
                else:
                    it = stream_round_openai(model, messages, ADMIN_TOOLS)
                for event in it:
                    kind = event[0]
                    if kind == "token":
                        round_text += event[1]
                        yield f"data: {json.dumps({'type': 'token', 'content': event[1]})}\n\n"
                    elif kind == "tool_call":
                        tcs.append(event[1])
                    elif kind == "usage":
                        u = event[1] or {}
                        record_chat_cost(session_id=session_id, surface="admin_chat",
                                         provider=u.get("provider", provider),
                                         model=u.get("model", model),
                                         prompt_tokens=u.get("prompt_tokens", 0),
                                         completion_tokens=u.get("completion_tokens", 0),
                                         total_tokens=u.get("total_tokens"),
                                         usage_known=u.get("usage_known", True))
                    elif kind == "finish":
                        finish_reason = event[1]
                full_text += round_text

                if finish_reason == "tool_calls" and tcs:
                    messages.append({"role": "assistant", "content": round_text or None,
                                     "tool_calls": [{"id": tc["id"], "type": "function",
                                       "function": {"name": tc["name"], "arguments": tc["args"]}}
                                      for tc in tcs]})
                    for tc in tcs:
                        result_str, _entry = execute_admin_tool(tc["name"], tc["args"],
                                                                session_id=session_id)
                        messages.append({"role": "tool", "tool_call_id": tc["id"],
                                         "content": result_str})
                        # Surface a parked write so the UI can render Approve/Reject.
                        try:
                            parsed = json.loads(result_str)
                            if isinstance(parsed, dict) and parsed.get("awaiting_approval"):
                                pending.append(parsed)
                                yield ("data: " + json.dumps({"type": "pending_action",
                                       "action_id": parsed.get("action_id"),
                                       "preview": parsed.get("preview")}) + "\n\n")
                        except Exception:
                            pass
                    continue
                break

            reply, _cmd = parse_command_from_text(full_text)
            reply = reply or full_text
            if reply:
                yield f"data: {json.dumps({'type': 'text', 'content': reply})}\n\n"
            execute_db("INSERT INTO admin_chat_messages (session_id, mode, role, content) "
                       "VALUES (%s,'admin','assistant',%s)", (session_id, reply))
            execute_db("UPDATE admin_chat_sessions SET last_message_at=NOW() WHERE session_id=%s",
                       (session_id,))
            yield f"data: {json.dumps({'type': 'done', 'pending': pending})}\n\n"
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'content': 'Admin chat error.'})}\n\n"
            print(f"[admin_chat] stream error: {e}")

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@bp.route("/admin/api/chat/history", methods=["GET"])
@admin_required
def admin_chat_history():
    session_id = request.args.get("session_id", "admin_default")
    msgs = query_db(
        "SELECT role, content, tool_calls_json, created_at FROM admin_chat_messages "
        "WHERE session_id=%s AND mode='admin' ORDER BY created_at, id", (session_id,))
    return jsonify({"messages": msgs or []})


@bp.route("/admin/api/chat/clear", methods=["POST"])
@admin_required
def admin_chat_clear():
    session_id = (request.get_json(silent=True) or {}).get("session_id", "admin_default")
    execute_db("DELETE FROM admin_chat_messages WHERE session_id=%s AND mode='admin'",
               (session_id,))
    return jsonify({"success": True})


@bp.route("/admin/api/chat/action/<int:action_id>", methods=["GET"])
@admin_required
def get_action(action_id):
    act = query_db("SELECT * FROM admin_pending_actions WHERE id=%s", (action_id,), fetchone=True)
    if not act:
        return jsonify({"error": "Not found"}), 404
    return jsonify(act)


@bp.route("/admin/api/chat/action/<int:action_id>/approve", methods=["POST"])
@admin_required
def approve(action_id):
    body, status = approve_action(action_id)
    return jsonify(body), status


@bp.route("/admin/api/chat/action/<int:action_id>/reject", methods=["POST"])
@admin_required
def reject(action_id):
    body, status = reject_action(action_id)
    return jsonify(body), status
