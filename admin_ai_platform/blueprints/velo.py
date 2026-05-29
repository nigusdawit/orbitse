"""
admin_ai_platform.blueprints.velo
================================

VELO master-agent control channel: a single token-authed ``POST /api/velo/command``
surface so an agency's master server can drive each client install over HTTP.

This is a focused, dependency-light command set (ping, app_status, list_features,
set_feature, bootstrap_install) rather than a verbatim port of the upstream
30-handler surface — the heavy handlers (which reach deep into app internals)
are a follow-on. Auth is a constant-time shared-secret compare; if
``VELO_SHARED_SECRET`` is unset the surface is disabled (403) so it's never
open by default.

Request:  ``{"command": "...", "params": {...}, "secret": "..."}``
          (secret may also be sent as ``Authorization: Bearer <secret>``)
Response: ``{"ok": true, "result": {...}}`` or ``{"ok": false, "error": "..."}``
"""

from __future__ import annotations

import hmac
import time

from flask import Blueprint, request, jsonify

from .. import config, __version__
from ..db import execute_db
from ..tenancy import (current_tenant_id, list_tenant_features, tenant_has_feature,
                       invalidate_tenant_features_cache, _FEATURE_NAMES)

bp = Blueprint("velo", __name__)
_START = time.time()


def _authed(body):
    if not config.VELO_SHARED_SECRET:
        return False
    auth = request.headers.get("Authorization", "")
    supplied = auth[7:].strip() if auth.startswith("Bearer ") else (body.get("secret") or "")
    return bool(supplied) and hmac.compare_digest(str(supplied), str(config.VELO_SHARED_SECRET))


# ---- command handlers ---------------------------------------------------
def _cmd_ping(params):
    return {"pong": True, "ts": time.time()}


def _cmd_app_status(params):
    return {"version": __version__, "uptime_seconds": round(time.time() - _START, 1),
            "deploy_mode": config.DEPLOY_MODE, "admin_mode": config.ADMIN_MODE,
            "config": config.summary()}


def _cmd_list_features(params):
    return {"features": list_tenant_features()}


def _cmd_set_feature(params):
    name = params.get("name")
    if name not in _FEATURE_NAMES:
        return {"error": "unknown feature"}
    tid = current_tenant_id()
    execute_db(
        "INSERT INTO tenant_features (tenant_id, feature_name, enabled) VALUES (%s,%s,%s) "
        "ON CONFLICT (tenant_id, feature_name) DO UPDATE SET enabled=EXCLUDED.enabled, updated_at=NOW()",
        (tid, name, bool(params.get("enabled", True))))
    invalidate_tenant_features_cache(tid)
    return {"name": name, "enabled": tenant_has_feature(name, tid)}


def _cmd_bootstrap_install(params):
    """Apply a config snapshot's gallery cards (UPSERT by slug) — the common
    'clone one tuned install onto a fresh one' need."""
    import json as _json
    cards = (params.get("tables") or {}).get("gallery_cards", []) if params.get("tables") \
        else params.get("gallery_cards", [])
    n = 0
    for card in cards or []:
        try:
            execute_db(
                "INSERT INTO gallery_cards (slug, title, subtitle, image_url, category, "
                " description, details, price, sort_order) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s) "
                "ON CONFLICT (slug) DO UPDATE SET title=EXCLUDED.title, updated_at=NOW()",
                (card.get("slug"), card.get("title", ""), card.get("subtitle", ""),
                 card.get("image_url", ""), card.get("category", ""), card.get("description", ""),
                 _json.dumps(card.get("details", [])), card.get("price"),
                 int(card.get("sort_order", 0) or 0)))
            n += 1
        except Exception as e:
            print(f"[velo] bootstrap gallery upsert failed: {e}")
    return {"gallery_cards_applied": n}


_HANDLERS = {
    "ping": _cmd_ping,
    "app_status": _cmd_app_status,
    "list_features": _cmd_list_features,
    "set_feature": _cmd_set_feature,
    "bootstrap_install": _cmd_bootstrap_install,
}


@bp.route("/api/velo/command", methods=["POST"])
def velo_command():
    body = request.get_json(silent=True) or {}
    if not _authed(body):
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    command = body.get("command", "")
    handler = _HANDLERS.get(command)
    if not handler:
        return jsonify({"ok": False, "error": f"unknown command {command}",
                        "available": sorted(_HANDLERS)}), 400
    try:
        result = handler(body.get("params") or {})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 500
    return jsonify({"ok": True, "result": result})


@bp.route("/api/velo/status", methods=["GET"])
def velo_status():
    # Lightweight unauthenticated liveness ping (no secrets, no tenant data).
    return jsonify({"ok": True, "version": __version__,
                    "uptime_seconds": round(time.time() - _START, 1)})
