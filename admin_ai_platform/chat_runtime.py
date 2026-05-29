"""
admin_ai_platform.chat_runtime
==============================

Provider-agnostic streaming primitives for the chat tool-loop — independent
copies of the helpers in app.py (~9091 parse_command_from_text, ~12075
_tools_for_claude / _messages_for_claude, ~12138 _stream_round_openai, ~12216
_stream_round_claude).

Each ``_stream_round_*`` yields a uniform event protocol so the loop in
``blueprints/visitor_chat.py`` is provider-neutral:

    ("token", str)                 — a visible text delta
    ("tool_call", {id,name,args})  — a completed function/tool call
    ("usage", {provider,model,prompt_tokens,completion_tokens,total_tokens,usage_known})
    ("finish", reason)             — "stop" | "tool_calls" | "length"
"""

from __future__ import annotations

import json
import re

from . import llm


# --------------------------------------------------------------------------
# Command extraction from the model's reply text.
# --------------------------------------------------------------------------
def parse_command_from_text(text):
    """Extract the first ``{"action": ...}`` JSON object from the reply,
    returning ``(clean_text, command_dict|None)``. Robust to ``` fencing,
    bare JSON, and adjacent backticks."""
    action_pos = text.find('{"action"')
    if action_pos == -1:
        action_pos = text.find('{ "action"')
    if action_pos == -1:
        return text.strip(), None

    json_str = text[action_pos:]
    depth = 0
    end_pos = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(json_str):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end_pos = i + 1
                break
    if end_pos == 0:
        return text.strip(), None

    raw_json = json_str[:end_pos].strip().replace("\\\n", "").replace("\\ \n", "")
    try:
        cmd = json.loads(raw_json)
    except json.JSONDecodeError:
        return text.strip(), None

    before = text[:action_pos]
    after = text[action_pos + end_pos:]
    before = re.sub(r"`{1,3}\s*command\s*`{0,3}\s*$", "", before, flags=re.IGNORECASE).strip()
    after = re.sub(r"^\s*`{1,3}", "", after).strip()
    clean = re.sub(r"`{1,3}", "", (before + " " + after).strip()).strip()
    return clean, cmd


# --------------------------------------------------------------------------
# OpenAI <-> Claude conversion.
# --------------------------------------------------------------------------
def tools_for_claude(openai_tools):
    """Convert OpenAI-shaped tool schemas to Claude's input_schema shape."""
    out = []
    for t in (openai_tools or []):
        fn = t.get("function") or {}
        out.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", "") or "",
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


def messages_for_claude(openai_messages):
    """Convert an OpenAI messages array into ``(system_str, claude_messages)``."""
    system_parts = []
    out = []
    for m in (openai_messages or []):
        role = m.get("role")
        content = m.get("content")
        if role == "system":
            if content:
                system_parts.append(content)
        elif role == "user":
            out.append({"role": "user", "content": content or ""})
        elif role == "assistant":
            blocks = []
            if content:
                blocks.append({"type": "text", "text": content})
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function") or {}
                try:
                    inp = json.loads(fn.get("arguments") or "{}")
                    if not isinstance(inp, dict):
                        inp = {}
                except Exception:
                    inp = {}
                blocks.append({
                    "type": "tool_use", "id": tc.get("id") or "",
                    "name": fn.get("name") or "", "input": inp,
                })
            if not blocks:
                blocks = [{"type": "text", "text": ""}]
            out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            out.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": m.get("tool_call_id") or "",
                    "content": content or "",
                }],
            })
    return ("\n\n".join(system_parts), out)


# --------------------------------------------------------------------------
# Streaming rounds.
# --------------------------------------------------------------------------
def stream_round_openai(model, messages, tools, max_tokens=4096, temperature=0.7):
    """One OpenAI streaming round, yielding the uniform event protocol."""
    stream = llm.openai_client.chat.completions.create(
        model=model, messages=messages, tools=tools or None,
        tool_choice="auto" if tools else "none",
        max_tokens=max_tokens, temperature=temperature,
        stream=True, stream_options={"include_usage": True},
    )
    tool_calls_acc = {}
    finish_reason = None
    usage_info = None
    for chunk in stream:
        u = getattr(chunk, "usage", None)
        if u is not None:
            usage_info = {
                "provider": "openai", "model": model,
                "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
                "total_tokens": getattr(u, "total_tokens", 0) or 0,
            }
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        delta = choice.delta
        if delta and getattr(delta, "content", None):
            yield ("token", delta.content)
        if delta and getattr(delta, "tool_calls", None):
            for tc in delta.tool_calls:
                idx = tc.index
                slot = tool_calls_acc.setdefault(idx, {"id": "", "name": "", "args": ""})
                if tc.id:
                    slot["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["args"] += fn.arguments
        if choice.finish_reason:
            finish_reason = choice.finish_reason
    for idx in sorted(tool_calls_acc.keys()):
        slot = tool_calls_acc[idx]
        if not slot["name"]:
            continue
        yield ("tool_call", {"id": slot["id"] or f"call_{idx}",
                             "name": slot["name"], "args": slot["args"] or "{}"})
    if usage_info is not None:
        usage_info["usage_known"] = True
        yield ("usage", usage_info)
    else:
        yield ("usage", {"provider": "openai", "model": model, "prompt_tokens": 0,
                         "completion_tokens": 0, "total_tokens": 0, "usage_known": False})
    yield ("finish", finish_reason or "stop")


def stream_round_claude(model, system, claude_messages, claude_tools,
                        max_tokens=4096, temperature=0.7):
    """One Claude streaming round, yielding the same uniform event protocol."""
    kwargs = {"model": model, "max_tokens": max_tokens, "temperature": temperature,
              "messages": claude_messages}
    if system:
        kwargs["system"] = system
    if claude_tools:
        kwargs["tools"] = claude_tools

    tool_blocks = {}
    finish_reason = "stop"
    in_tokens = 0
    out_tokens = 0
    with llm.anthropic_client.messages.stream(**kwargs) as stream:
        for event in stream:
            etype = getattr(event, "type", "")
            if etype == "message_start":
                msg = getattr(event, "message", None)
                u = getattr(msg, "usage", None) if msg is not None else None
                if u is not None:
                    in_tokens = getattr(u, "input_tokens", 0) or 0
                    out_tokens = getattr(u, "output_tokens", 0) or out_tokens
            elif etype == "content_block_start":
                block = getattr(event, "content_block", None)
                if block is not None and getattr(block, "type", "") == "tool_use":
                    tool_blocks[event.index] = {
                        "id": getattr(block, "id", "") or "",
                        "name": getattr(block, "name", "") or "", "args_str": ""}
            elif etype == "content_block_delta":
                delta = getattr(event, "delta", None)
                if delta is None:
                    continue
                dtype = getattr(delta, "type", "")
                if dtype == "text_delta":
                    text = getattr(delta, "text", "") or ""
                    if text:
                        yield ("token", text)
                elif dtype == "input_json_delta":
                    partial = getattr(delta, "partial_json", "") or ""
                    if event.index in tool_blocks and partial:
                        tool_blocks[event.index]["args_str"] += partial
            elif etype == "message_delta":
                delta = getattr(event, "delta", None)
                if delta is not None:
                    sr = getattr(delta, "stop_reason", None)
                    if sr:
                        finish_reason = ("tool_calls" if sr == "tool_use"
                                         else "length" if sr == "max_tokens" else "stop")
                u = getattr(event, "usage", None)
                if u is not None:
                    out_tokens = getattr(u, "output_tokens", 0) or out_tokens
    for idx in sorted(tool_blocks.keys()):
        slot = tool_blocks[idx]
        if not slot["name"]:
            continue
        yield ("tool_call", {"id": slot["id"] or f"call_{idx}",
                             "name": slot["name"], "args": slot["args_str"] or "{}"})
    if in_tokens or out_tokens:
        yield ("usage", {"provider": "anthropic", "model": model,
                         "prompt_tokens": int(in_tokens), "completion_tokens": int(out_tokens),
                         "total_tokens": int(in_tokens) + int(out_tokens), "usage_known": True})
    else:
        yield ("usage", {"provider": "anthropic", "model": model, "prompt_tokens": 0,
                         "completion_tokens": 0, "total_tokens": 0, "usage_known": False})
    yield ("finish", finish_reason)
