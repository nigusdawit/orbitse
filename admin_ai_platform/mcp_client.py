"""
admin_ai_platform.mcp_client
===========================

Minimal MCP (Model Context Protocol) client over Streamable HTTP (JSON-RPC 2.0).
Used to discover a connected server's tools (``tools/list``) and to invoke one
mid-conversation (``tools/call``). URLs are SSRF-validated before every call.

This is a pragmatic subset: ``http`` transport + ``none|bearer|header`` auth.
OAuth-driven blueprints (Linear/GitHub/etc.) are a later enhancement.
"""

from __future__ import annotations

import json

import httpx

from .custom_skills import _url_is_safe  # reuse the SSRF guard

_PROTOCOL_VERSION = "2025-03-26"


def _headers(server):
    h = {"content-type": "application/json", "accept": "application/json"}
    auth_type = (server.get("auth_type") or "none").lower()
    # Stored credential is encrypted at rest (M19); decrypt at the point of use.
    # decrypt() returns legacy plaintext unchanged, so this is safe pre-migration.
    from . import crypto
    cred = crypto.decrypt(server.get("auth_credential") or "")
    if auth_type == "bearer" and cred:
        h["authorization"] = f"Bearer {cred}"
    elif auth_type == "header" and cred and server.get("auth_header_name"):
        h[server["auth_header_name"]] = cred
    return h


def _rpc(url, headers, method, params, timeout=15):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    # Streamable HTTP may return JSON or an SSE-framed body; handle both.
    ctype = resp.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                try:
                    obj = json.loads(line[5:].strip())
                    if isinstance(obj, dict) and ("result" in obj or "error" in obj):
                        return obj
                except Exception:
                    continue
        raise RuntimeError("no JSON-RPC result in SSE stream")
    return resp.json()


def list_tools(server):
    """Return ``(ok, tools_or_error)``. tools = [{name, description, input_schema}]."""
    url = server.get("url") or ""
    if not _url_is_safe(url):
        return False, "url failed SSRF safety check"
    headers = _headers(server)
    try:
        # Best-effort initialize handshake (some servers require it).
        try:
            _rpc(url, headers, "initialize", {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {}, "clientInfo": {"name": "admin_ai_platform", "version": "0"}})
        except Exception:
            pass
        out = _rpc(url, headers, "tools/list", {})
        if "error" in out:
            return False, json.dumps(out["error"])[:300]
        tools = (out.get("result") or {}).get("tools") or []
        norm = [{"name": t.get("name", ""), "description": t.get("description", ""),
                 "input_schema": t.get("inputSchema") or t.get("input_schema")
                 or {"type": "object", "properties": {}}}
                for t in tools if t.get("name")]
        return True, norm
    except Exception as e:
        return False, str(e)[:300]


def call_tool(server, tool_name, args):
    """Invoke one tool. Returns a result dict (or {"error": ...})."""
    url = server.get("url") or ""
    if not _url_is_safe(url):
        return {"error": "url failed SSRF safety check"}
    try:
        out = _rpc(url, _headers(server), "tools/call",
                   {"name": tool_name, "arguments": args or {}}, timeout=30)
        if "error" in out:
            return {"error": json.dumps(out["error"])[:300]}
        return {"result": out.get("result")}
    except Exception as e:
        return {"error": str(e)[:300]}
