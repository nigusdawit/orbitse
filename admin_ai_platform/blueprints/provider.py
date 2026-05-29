"""
admin_ai_platform.blueprints.provider
=====================================

Admin settings surfaces for the AI:
  * ``GET/PUT /admin/api/llm-provider``      active provider + per-provider model
  * ``GET/PUT /admin/api/chatbot-settings``  visitor chatbot config (incl. prompt)
  * ``GET     /admin/api/default-system-prompt``  the built-in default prompt

These drive the visitor chat (provider switch + system prompt) and the Chatbot
admin tab.
"""

from __future__ import annotations

import json

from flask import Blueprint, request, jsonify

from ..db import query_db, execute_db
from ..auth import admin_required
from ..prompts import BASE_SYSTEM_PROMPT
from ..tenancy import invalidate_tenant_features_cache  # noqa: F401 (future use)

bp = Blueprint("provider", __name__)

_VALID_PROVIDERS = ("openai", "claude")


@bp.route("/admin/api/llm-provider", methods=["GET"])
@admin_required
def get_provider():
    row = query_db("SELECT provider, openai_model, claude_model FROM agent_provider_settings WHERE id=1",
                   fetchone=True)
    return jsonify(row or {"provider": "openai", "openai_model": "gpt-4o-mini",
                           "claude_model": "claude-sonnet-4-5"})


@bp.route("/admin/api/llm-provider", methods=["PUT"])
@admin_required
def set_provider():
    data = request.get_json() or {}
    provider = (data.get("provider") or "openai").lower()
    if provider not in _VALID_PROVIDERS:
        return jsonify({"error": f"provider must be one of {_VALID_PROVIDERS}"}), 400
    row = execute_db(
        "UPDATE agent_provider_settings SET provider=%s, openai_model=%s, "
        " claude_model=%s, updated_at=NOW() WHERE id=1 RETURNING *",
        (provider, data.get("openai_model") or "gpt-4o-mini",
         data.get("claude_model") or "claude-sonnet-4-5"),
    )
    return jsonify(row or {"error": "settings row missing"})


@bp.route("/admin/api/chatbot-settings", methods=["GET"])
@admin_required
def get_chatbot():
    row = query_db("SELECT * FROM chatbot_settings WHERE id=1", fetchone=True)
    return jsonify(row or {})


@bp.route("/admin/api/chatbot-settings", methods=["PUT"])
@admin_required
def set_chatbot():
    data = request.get_json() or {}
    row = execute_db(
        "UPDATE chatbot_settings SET enabled=%s, mode=%s, agent_name=%s, "
        " agent_role=%s, agent_avatar=%s, greeting=%s, quick_prompts=%s::jsonb, "
        " api_endpoint=%s, embed_code=%s, system_prompt=%s, updated_at=NOW() "
        "WHERE id=1 RETURNING *",
        (bool(data.get("enabled", False)), data.get("mode", "builtin"),
         data.get("agent_name", "AI Assistant"), data.get("agent_role", "Assistant"),
         data.get("agent_avatar", "A"), data.get("greeting", ""),
         json.dumps(data.get("quick_prompts", [])), data.get("api_endpoint", "/api/chat"),
         data.get("embed_code", ""), data.get("system_prompt", "")),
    )
    return jsonify(row or {})


@bp.route("/admin/api/default-system-prompt", methods=["GET"])
@admin_required
def default_prompt():
    return jsonify({"system_prompt": BASE_SYSTEM_PROMPT})
