"""admin/ai_control.py - super-admin AI Control + AI Activity API, as a Flask blueprint.

Part of the app.py de-monolith (Track B / task 078), mirroring admin/ai_prompts.py.
These four routes back the dashboard's "AI Control" + "AI Activity" tabs:

  GET  /admin/api/ai-control          - list every AI-Control knob with its
                                        effective value, where it comes from
                                        (db override / env / default), and the
                                        pylego.config default
  PUT  /admin/api/ai-control/<key>    - persist an override for one knob
  POST /admin/api/ai-control/<key>/reset - delete an override -> revert to env/default
  GET  /admin/api/ai-activity         - recent admin/visitor AI turns (metadata +
                                        redacted question/answer) + light totals

SUPER-ADMIN ONLY: @admin_required only proves "an admin is logged in", so each
handler enforces the super-admin gate IN THE BODY (via _require_super_admin_role(),
from core) exactly as it did in app.py - a plain client session is 403'd. These
knobs tune the whole AI layer (kill switch, models, rate limits), so the gate is
the real boundary; hiding the tab in the template is only cosmetic.

The AI-Control settings subsystem these routes call - the knob registry
(_ai_control_registry), the DB>env>default getter get_ai_setting, set_ai_setting /
reset_ai_setting, and the source resolver _ai_setting_source - lives in core
(Track B / task 078), so this blueprint imports it cleanly, never `from app`
(which would be circular). The pylego.config default shown per knob is read via
pylego.config directly (stdlib-only, no app import), matching how app.py read it.

URLs keep their absolute /admin/api/* paths, so the route table is unchanged - only
the Flask endpoint name gains an "ai_control." prefix (admin JS calls these by URL,
not url_for). CSRF / feature-flag enforcement runs in app.py's global before_request
hooks, which apply to blueprint routes too, so nothing extra is needed here.

Registered in app.py via app.register_blueprint(ai_control_bp), after products_bp.
"""
from flask import Blueprint, request, jsonify

from core import (
    query_db,
    admin_required,
    _require_super_admin_role,
    _ai_control_registry,
    get_ai_setting,
    set_ai_setting,
    reset_ai_setting,
    _ai_setting_source,
)

# pylego.config supplies the env->default value shown alongside each knob's
# effective value. pylego is stdlib-only and never imports app, so this is a clean
# leaf import (no circular dependency) - same module app.py read this default from.
from pylego import config as _pylego_config

ai_control_bp = Blueprint("ai_control", __name__)


@ai_control_bp.route("/admin/api/ai-control", methods=["GET"])
@admin_required
def admin_list_ai_control():
    """Return every AI Control knob with its effective value + where it comes
    from (db override / env / default). Super-admin only."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    items = []
    for spec in _ai_control_registry():
        key = spec["key"]
        try:
            effective = get_ai_setting(key)
        except Exception:
            effective = None
        items.append({
            "key": key, "label": spec["label"], "group": spec["group"],
            "type": spec["type"], "description": spec["description"],
            "env": spec["env"],
            "value": effective,
            "default": getattr(_pylego_config.get_config(), spec["attr"]),
            "source": _ai_setting_source(key),
        })
    return jsonify({"settings": items})


@ai_control_bp.route("/admin/api/ai-control/<key>", methods=["PUT"])
@admin_required
def admin_set_ai_control(key):
    """Persist an AI Control override. Body: {"value": ...}. Super-admin only."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    body = request.get_json(silent=True) or {}
    if "value" not in body:
        return jsonify({"error": "missing_field", "field": "value"}), 400
    try:
        by = "super_admin"
        new_val = set_ai_setting(key, body.get("value"), by=by)
        return jsonify({"key": key, "value": new_val, "source": _ai_setting_source(key)})
    except ValueError as ve:
        return jsonify({"error": "invalid", "detail": str(ve)}), 400
    except Exception as e:
        print(f"[ai-control] set {key} failed: {e}")
        return jsonify({"error": "save_failed", "detail": str(e)}), 500


@ai_control_bp.route("/admin/api/ai-control/<key>/reset", methods=["POST"])
@admin_required
def admin_reset_ai_control(key):
    """Delete an override → revert the knob to its env/default. Super-admin only."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    try:
        reset_ai_setting(key)
        return jsonify({"key": key, "value": get_ai_setting(key),
                        "source": _ai_setting_source(key)})
    except ValueError as ve:
        return jsonify({"error": "invalid", "detail": str(ve)}), 400
    except Exception as e:
        print(f"[ai-control] reset {key} failed: {e}")
        return jsonify({"error": "reset_failed", "detail": str(e)}), 500


@ai_control_bp.route("/admin/api/ai-activity", methods=["GET"])
@admin_required
def admin_list_ai_activity():
    """Recent admin-AI turns (metadata + redacted question/answer) + light
    totals. Super-admin only. ?limit=N (default 100, max 500)."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    try:
        limit = int(request.args.get("limit", 100) or 100)
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, 500))
    # Optional surface filter: admin | visitor | (anything else = all).
    surface = (request.args.get("surface") or "").strip().lower()
    where, params = "", []
    if surface in ("admin", "visitor"):
        where = "WHERE surface = %s "
        params = [surface]
    rows = query_db(
        "SELECT id, surface, session_id, model, provider, rounds, tool_calls, "
        "tokens_in, tokens_out, cost_usd, duration_ms, status, error_text, "
        "user_message, final_answer, created_at FROM ai_activity_log "
        + where + "ORDER BY id DESC LIMIT %s",
        tuple(params + [limit])) or []
    out = []
    for r in rows:
        d = dict(r)
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        out.append(d)
    stats = query_db(
        "SELECT COUNT(*) AS n, COALESCE(SUM(cost_usd),0) AS cost, "
        "COALESCE(SUM(tokens_in+tokens_out),0) AS tokens FROM ai_activity_log "
        + where, tuple(params), fetchone=True) or {}
    return jsonify({
        "activity": out,
        "stats": {
            "count": int(stats.get("n") or 0),
            "cost_usd": round(float(stats.get("cost") or 0), 6),
            "tokens": int(stats.get("tokens") or 0),
        },
    })
