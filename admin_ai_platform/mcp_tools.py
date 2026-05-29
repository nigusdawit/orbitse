"""
admin_ai_platform.mcp_tools
=========================

Bridges enabled MCP server tools into the chat tool loop. Each cached tool is
exposed under a namespaced function name ``mcp__<server_id>__<sanitized_tool>``
so it can't collide with builtins/custom skills, and dispatch maps it back to
the real tool via the cache.

Audience gating: the visitor agent only sees tools from servers flagged
``allowed_for_velo`` (default FALSE) — a freshly added server never leaks tools
to visitors without an explicit opt-in. The admin agent sees ``allowed_for_admin``.
"""

from __future__ import annotations

import re

from .db import query_db
from . import mcp_client

_PREFIX = "mcp__"
_SANITIZE = re.compile(r"[^a-zA-Z0-9_-]")


def _fn_name(server_id, tool_name):
    return f"{_PREFIX}{server_id}__{_SANITIZE.sub('_', tool_name)}"[:64]


def mcp_tool_schemas(audience="visitor"):
    """OpenAI tool schemas for enabled MCP tools visible to ``audience``."""
    col = "allowed_for_velo" if audience == "visitor" else "allowed_for_admin"
    out = []
    try:
        rows = query_db(
            f"SELECT t.server_id, t.tool_name, t.description, t.input_schema_json "
            f"FROM mcp_tools_cache t JOIN mcp_servers s ON s.id = t.server_id "
            f"WHERE s.enabled = TRUE AND t.enabled = TRUE AND s.{col} = TRUE") or []
    except Exception as e:
        print(f"[mcp_tools] schema build failed: {e}")
        return out
    for r in rows:
        out.append({"type": "function", "function": {
            "name": _fn_name(r["server_id"], r["tool_name"]),
            "description": r.get("description") or "",
            "parameters": r.get("input_schema_json") or {"type": "object", "properties": {}}}})
    return out


def is_mcp_tool(name):
    return bool(name) and name.startswith(_PREFIX)


def execute_mcp_tool(name, args):
    """Map a namespaced tool name back to its server + real tool and call it."""
    try:
        rest = name[len(_PREFIX):]
        server_id_str, sanitized = rest.split("__", 1)
        server_id = int(server_id_str)
    except (ValueError, AttributeError):
        return {"error": f"malformed mcp tool name {name}"}
    server = query_db("SELECT * FROM mcp_servers WHERE id=%s AND enabled=TRUE",
                      (server_id,), fetchone=True)
    if not server:
        return {"error": "mcp server not found or disabled"}
    # Resolve the real tool name from the cache (sanitization isn't reversible).
    tools = query_db("SELECT tool_name FROM mcp_tools_cache WHERE server_id=%s AND enabled=TRUE",
                     (server_id,)) or []
    real = next((t["tool_name"] for t in tools
                 if _SANITIZE.sub("_", t["tool_name"]) == sanitized), None)
    if not real:
        return {"error": "mcp tool not found in cache"}
    return mcp_client.call_tool(server, real, args)
