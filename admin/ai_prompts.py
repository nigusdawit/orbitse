"""admin/ai_prompts.py - super-admin editable AI prompts API, as a Flask blueprint.

Part of the app.py de-monolith (Track B / task 078, piece #1), mirroring
admin/personas.py. These four routes manage the DB-backed, super-admin-editable
system prompts surfaced in the dashboard's "AI Prompts" editor:

  GET  /admin/api/ai-prompts            - list every editable prompt + its
                                          current text, hardcoded default, and
                                          whether the two still match
  PUT  /admin/api/ai-prompts/<key>      - save new text for one prompt
  POST /admin/api/ai-prompts/<key>/reset- restore one prompt to its default
  GET  /admin/api/default-system-prompt - read the hardcoded visitor system
                                          prompt (for the editor pre-fill)

SUPER-ADMIN ONLY: @admin_required only proves "an admin is logged in", so each
handler enforces the super-admin gate IN THE BODY (via _require_super_admin_role()
or _is_super_admin(), both from core) exactly as it did in app.py - a plain client
session is 403'd. Prompt text is part of the operator's IP, hence the gate even on
the read endpoints.

The prompt registry/defaults (_ai_prompt_registry / _ai_prompt_defaults), the
in-memory cache invalidator (_invalidate_prompt_cache), and the SYSTEM_PROMPT
constant all live in core (Track B / task 078, piece #1), so this blueprint imports
them cleanly - never `from app` (which would be circular).

URLs keep their absolute /admin/api/* paths, so the route table is unchanged - only
the Flask endpoint name gains an "ai_prompts." prefix (admin JS calls these by URL,
not url_for). CSRF / feature-flag enforcement runs in app.py's global before_request
hooks, which apply to blueprint routes too, so nothing extra is needed here.

Registered in app.py via app.register_blueprint(ai_prompts_bp), after tenancy_bp.
"""
from flask import Blueprint, request, jsonify, session

from core import (
    query_db,
    execute_db,
    admin_required,
    _require_super_admin_role,
    _is_super_admin,
    _ai_prompt_registry,
    _ai_prompt_defaults,
    _invalidate_prompt_cache,
    SYSTEM_PROMPT,
)

ai_prompts_bp = Blueprint("ai_prompts", __name__)


@ai_prompts_bp.route("/admin/api/ai-prompts", methods=["GET"])
@admin_required
def admin_list_ai_prompts():
    """Return every editable prompt with its current text, its hardcoded
    default, and whether the stored text still matches that default."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    # Current stored values (keyed by prompt_key).
    stored = {}
    try:
        for r in (query_db("SELECT prompt_key, content, updated_at, updated_by "
                           "FROM ai_prompts") or []):
            stored[r["prompt_key"]] = r
    except Exception as e:
        print(f"[ai-prompts] list read failed: {e}")
    defaults = _ai_prompt_defaults()
    items = []
    for meta in _ai_prompt_registry():
        key = meta["key"]
        default_text = defaults.get(key, "")
        row = stored.get(key) or {}
        content = row.get("content")
        if content is None or not str(content).strip():
            # Not seeded yet (brand-new DB before the boot seed ran) — show the
            # default so the editor is never empty.
            content = default_text
        updated_at = row.get("updated_at")
        items.append({
            "key": key,
            "label": meta["label"],
            "category": meta["category"],
            "description": meta["description"],
            "content": content,
            "is_default": (str(content).strip() == str(default_text).strip()),
            "updated_at": updated_at.isoformat() if updated_at else None,
            "updated_by": row.get("updated_by"),
        })
    return jsonify({"prompts": items})


@ai_prompts_bp.route("/admin/api/ai-prompts/<key>", methods=["PUT"])
@admin_required
def admin_update_ai_prompt(key):
    """Save new text for one prompt. Upserts the row and refreshes the cache so
    the change is live everywhere on the very next AI call."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    valid_keys = {m["key"] for m in _ai_prompt_registry()}
    if key not in valid_keys:
        return jsonify({"error": "unknown_prompt_key"}), 404
    data = request.get_json(silent=True) or {}
    content = data.get("content")
    if content is None:
        return jsonify({"error": "missing_content"}), 400
    content = str(content)
    if not content.strip():
        return jsonify({"error": "empty_content",
                        "message": "Prompt text cannot be blank. Use Reset to "
                                   "restore the default."}), 400
    who = session.get("admin_username") or session.get("admin_role") or "super_admin"
    try:
        execute_db(
            "INSERT INTO ai_prompts (prompt_key, content, updated_at, updated_by) "
            "VALUES (%s, %s, NOW(), %s) "
            "ON CONFLICT (prompt_key) DO UPDATE SET "
            "content = EXCLUDED.content, updated_at = NOW(), "
            "updated_by = EXCLUDED.updated_by",
            (key, content, who),
        )
    except Exception as e:
        print(f"[ai-prompts] save failed for {key}: {e}")
        return jsonify({"error": "save_failed"}), 500
    _invalidate_prompt_cache()
    default_text = _ai_prompt_defaults().get(key, "")
    return jsonify({"ok": True, "key": key,
                    "is_default": (content.strip() == str(default_text).strip())})


@ai_prompts_bp.route("/admin/api/ai-prompts/<key>/reset", methods=["POST"])
@admin_required
def admin_reset_ai_prompt(key):
    """Restore one prompt to its current hardcoded default and refresh cache."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    valid_keys = {m["key"] for m in _ai_prompt_registry()}
    if key not in valid_keys:
        return jsonify({"error": "unknown_prompt_key"}), 404
    default_text = _ai_prompt_defaults().get(key, "")
    who = session.get("admin_username") or session.get("admin_role") or "super_admin"
    try:
        execute_db(
            "INSERT INTO ai_prompts (prompt_key, content, updated_at, updated_by) "
            "VALUES (%s, %s, NOW(), %s) "
            "ON CONFLICT (prompt_key) DO UPDATE SET "
            "content = EXCLUDED.content, updated_at = NOW(), "
            "updated_by = EXCLUDED.updated_by",
            (key, default_text, who),
        )
    except Exception as e:
        print(f"[ai-prompts] reset failed for {key}: {e}")
        return jsonify({"error": "reset_failed"}), 500
    _invalidate_prompt_cache()
    return jsonify({"ok": True, "key": key, "content": default_text,
                    "is_default": True})


# --------------- Default System Prompt (public read for admin pre-fill) ------

@ai_prompts_bp.route("/admin/api/default-system-prompt", methods=["GET"])
@admin_required
def admin_get_default_prompt():
    """GET the hardcoded default system prompt so the admin can pre-fill."""
    # Prompt privacy: the default prompt is part of the operator's IP too —
    # only the super-admin may read it.
    if not _is_super_admin():
        return jsonify({"error": "forbidden"}), 403
    return jsonify({"system_prompt": SYSTEM_PROMPT})
