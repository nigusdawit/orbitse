"""
admin_ai_platform.blueprints.visitor_chat
=========================================

``POST /api/chat`` — the streaming visitor concierge. Independent port of the
app.py tool-loop (~18819): compact site index + function-calling lookup tools
in a capped tool-call loop, ``generatePage``-first command model, SSE events,
per-round cost stamping, and conversation persistence with per-turn tool logs.

SSE events emitted:
  {"type":"token","content":...}     streamed text delta
  {"type":"text","content":...}      final clean reply (command stripped)
  {"type":"command","command":{...}} parsed action command for the widget
  {"type":"done"}                    stream complete
  {"type":"error","content":...}     failure

Also serves ``GET /api/chatbot-settings`` (public widget config).
"""

from __future__ import annotations

import json

from flask import Blueprint, request, jsonify, Response, stream_with_context

from .. import llm
from ..db import query_db, execute_db
from ..cost import record_chat_cost, enforce_cost_cap
from ..util import parse_ua, client_ip
from ..prompts import assemble_system_prompt
from ..tools import get_active_chat_tools, execute_chat_tool
from ..chat_runtime import (
    parse_command_from_text, stream_round_openai, stream_round_claude,
    messages_for_claude, tools_for_claude,
)

bp = Blueprint("visitor_chat", __name__)

MAX_ROUNDS = 4
HISTORY_TURNS = 20


@bp.route("/api/chatbot-settings", methods=["GET"])
def chatbot_settings():
    row = query_db("SELECT * FROM chatbot_settings WHERE id = 1", fetchone=True)
    return jsonify(row or {"enabled": False})


@bp.route("/api/chat", methods=["POST"])
def chat():
    if llm.openai_client is None and llm.anthropic_client is None:
        return jsonify({"error": "No LLM provider configured"}), 503

    data = request.get_json() or {}
    message = (data.get("message") or "").strip()
    history = data.get("history") or []
    session_id = data.get("session_id") or ""
    visitor_id = data.get("visitor_id") or ""
    if not message:
        return jsonify({"error": "Message is required"}), 400

    # Cap gate (402 short-circuit in strict_block mode; throttle sets a flag).
    capped = enforce_cost_cap(surface="visitor_chat")
    if capped is not None:
        return capped

    try:
        provider, model = llm.get_active_llm_provider()
    except Exception as e:
        return jsonify({"error": str(e)}), 503

    active_tools = get_active_chat_tools()

    # Build the messages array: system + recent history + this user turn.
    messages = [{"role": "system", "content": assemble_system_prompt()}]
    for h in history[-HISTORY_TURNS:]:
        role = "assistant" if h.get("role") in ("assistant", "agent") else "user"
        messages.append({"role": role, "content": h.get("content", "")})
    messages.append({"role": "user", "content": message})

    ua = request.headers.get("User-Agent", "")
    ip = client_ip()
    _, _, device = parse_ua(ua)

    def generate():
        full_text = ""
        tool_logs = []
        try:
            for _round in range(MAX_ROUNDS):
                round_text = ""
                tcs = []
                finish_reason = None

                if provider == "claude":
                    sys_str, cmsgs = messages_for_claude(messages)
                    it = stream_round_claude(model, sys_str, cmsgs,
                                             tools_for_claude(active_tools))
                else:
                    it = stream_round_openai(model, messages, active_tools)

                for event in it:
                    kind = event[0]
                    if kind == "token":
                        round_text += event[1]
                        yield f"data: {json.dumps({'type': 'token', 'content': event[1]})}\n\n"
                    elif kind == "tool_call":
                        tcs.append(event[1])
                    elif kind == "usage":
                        u = event[1] or {}
                        record_chat_cost(
                            session_id=session_id, visitor_id=visitor_id,
                            surface="visitor_chat",
                            provider=u.get("provider", provider),
                            model=u.get("model", model),
                            prompt_tokens=u.get("prompt_tokens", 0),
                            completion_tokens=u.get("completion_tokens", 0),
                            total_tokens=u.get("total_tokens"),
                            usage_known=u.get("usage_known", True),
                        )
                    elif kind == "finish":
                        finish_reason = event[1]

                full_text += round_text

                if finish_reason == "tool_calls" and tcs:
                    messages.append({
                        "role": "assistant",
                        "content": round_text or None,
                        "tool_calls": [{
                            "id": tc["id"], "type": "function",
                            "function": {"name": tc["name"], "arguments": tc["args"]},
                        } for tc in tcs],
                    })
                    for tc in tcs:
                        result_str, log_entry = execute_chat_tool(
                            tc["name"], tc["args"], session_id=session_id)
                        tool_logs.append(log_entry)
                        messages.append({"role": "tool", "tool_call_id": tc["id"],
                                         "content": result_str})
                    continue
                break

            reply, cmd = parse_command_from_text(full_text)
            if reply:
                yield f"data: {json.dumps({'type': 'text', 'content': reply})}\n\n"
            if cmd:
                yield f"data: {json.dumps({'type': 'command', 'command': cmd})}\n\n"

            _persist(session_id, visitor_id, ip, device, ua, message,
                     reply or full_text, cmd, tool_logs)

            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'content': 'Connection issue. Please try again.'})}\n\n"
            print(f"[chat] stream error: {e}")

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _persist(session_id, visitor_id, ip, device, ua, user_msg, reply, cmd, tool_logs):
    """Save the user + assistant messages with per-turn tool logs. Best-effort."""
    if not session_id:
        return
    try:
        conv = query_db(
            "SELECT id FROM chat_conversations WHERE session_id = %s ORDER BY id DESC LIMIT 1",
            (session_id,), fetchone=True)
        if not conv:
            conv = execute_db(
                "INSERT INTO chat_conversations (session_id, visitor_id, visitor_ip, "
                " device_type, user_agent) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (session_id, visitor_id, ip, device, ua[:500]))
        conv_id = conv["id"]
        execute_db("UPDATE chat_conversations SET updated_at = NOW() WHERE id = %s",
                   (conv_id,))
        execute_db("INSERT INTO chat_messages (conversation_id, role, content) "
                   "VALUES (%s,'user',%s)", (conv_id, user_msg))
        execute_db(
            "INSERT INTO chat_messages (conversation_id, role, content, command_json, "
            " tool_calls_json) VALUES (%s,'assistant',%s,%s,%s)",
            (conv_id, reply, json.dumps(cmd) if cmd else None,
             json.dumps(tool_logs) if tool_logs else None))
    except Exception as e:
        print(f"[chat] persist failed: {e}")
