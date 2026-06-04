"""admin/admin_ai.py — super-admin CRUD for the admin AI's dynamic config (task 088).

The admin chat's PERSONAS (and, in phase 3, its slash-command / capability /
starter PALETTE) are DB-backed and editable from the dashboard's "Admin AI" tab.
This blueprint is the management API; the code-default registries + the fail-open
cached accessor live in core (get_admin_personas / _admin_persona_registry), and
the boot seed (sync_admin_personas, preserve-edits) lives in app.py.

Routes (all absolute /admin/api/* paths so the route table is stable; the Flask
endpoint names gain an "admin_ai." prefix — admin JS calls these by URL):

  Personas — SUPER-ADMIN ONLY (each handler calls _require_super_admin_role()):
    GET    /admin/api/admin-ai/personas            list all (incl. disabled)
    POST   /admin/api/admin-ai/personas            create a CUSTOM persona
    PUT    /admin/api/admin-ai/personas/<key>      update one (built-in or custom)
    POST   /admin/api/admin-ai/personas/<key>/reset  restore a BUILT-IN to default
    DELETE /admin/api/admin-ai/personas/<key>      delete a CUSTOM persona

  Chat consumption — ANY admin (the chat fetches this to build the persona pill):
    GET    /admin/api/chat/personas                enabled personas (key/label/icon/desc)

Rules: built-ins (is_builtin TRUE, seeded from the registry) are RESET/DISABLE-only
— never hard-deleted; only custom personas are deletable. The 'general' persona is
protected (cannot be disabled or deleted) because it is the universal fallback used
by _admin_apply_persona(). A super-admin editing a persona's tool scope changes tool
VISIBILITY, not AUTHORITY — _admin_tool_superadmin_guard() still gates super-admin-only
tools at call time, so a persona edit can never escalate a normal admin.

@admin_required only proves "an admin is logged in", so the super-admin gate is
enforced in each body (mirrors admin/ai_prompts.py + admin/personas.py). CSRF runs
in app.py's global before_request hook. Registered via app.register_blueprint(admin_ai_bp).
"""
import json
import re

from flask import Blueprint, request, jsonify, session

from core import (
    query_db,
    execute_db,
    admin_required,
    _require_super_admin_role,
    _admin_persona_registry,
    _admin_persona_defaults,
    get_admin_personas,
    get_admin_personas_all,
    _invalidate_admin_persona_cache,
)

admin_ai_bp = Blueprint("admin_ai", __name__)

# admin_chat_personas is per-silo-global config (one DB per client; tenant_id 1),
# matching how sync_admin_personas() seeds it and how the cached accessor reads it.
_ADMIN_AI_TENANT = 1


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def _who():
    return session.get("admin_username") or session.get("admin_role") or "super_admin"


def _coerce_str_list(v, cap_item=80, cap_len=50):
    """Coerce a value into a clean list of short strings (comma-split a string)."""
    if isinstance(v, str):
        v = [x.strip() for x in v.split(",")]
    if not isinstance(v, list):
        return []
    return [str(x).strip()[:cap_item] for x in v if str(x).strip()][:cap_len]


def _row_admin_persona(r, builtin_keys):
    """Serialize an admin_chat_personas row for the editor: ISO timestamps, the
    tri-state tool_prefixes (None = all tools), the extra_tools list, and
    is_default (a built-in that has never been human-edited → updated_by NULL)."""
    def _jload(v, fallback):
        if v is None:
            return fallback
        if isinstance(v, (list, dict)):
            return v
        try:
            return json.loads(v)
        except Exception:
            return fallback

    tp = r.get("tool_prefixes")
    out = {
        "persona_key": r["persona_key"],
        "label": r.get("label") or "",
        "icon": r.get("icon") or "",
        "description": r.get("description") or "",
        "prompt_suffix": r.get("prompt_suffix") or "",
        "tool_prefixes": (None if tp is None else _jload(tp, None)),
        "extra_tools": _jload(r.get("extra_tools"), []) or [],
        "enabled": bool(r.get("enabled", True)),
        "is_builtin": bool(r.get("is_builtin", False)),
        "sort_order": r.get("sort_order") or 0,
        "updated_by": r.get("updated_by"),
        "is_default": bool(r.get("is_builtin", False)) and r.get("updated_by") is None,
        "protected": r["persona_key"] == "general",
    }
    ua = r.get("updated_at")
    out["updated_at"] = ua.isoformat() if hasattr(ua, "isoformat") else ua
    return out


def _admin_persona_payload(body, *, for_create):
    """Validate + whitelist a persona create/update body (prevents mass-assignment
    of is_builtin / tenant_id / updated_by). Returns (fields, error).

    tool_prefixes is TRI-STATE: null/absent → None (every tool); a list/CSV → that
    list. extra_tools is always a list. On create, persona_key must be a fresh slug
    (built-in keys are reserved); on update the key comes from the URL, not the body."""
    fields = {
        "label": (body.get("label") or "").strip()[:120],
        "icon": (body.get("icon") or "").strip()[:16],
        "description": (body.get("description") or "").strip()[:400],
        "prompt_suffix": (body.get("prompt_suffix") or "").strip()[:8000],
        "extra_tools": json.dumps(_coerce_str_list(body.get("extra_tools"))),
        "enabled": bool(body.get("enabled", True)),
    }
    # tri-state tool_prefixes
    tp = body.get("tool_prefixes", None)
    if tp is None:
        fields["tool_prefixes"] = None            # SQL NULL → every tool
    else:
        fields["tool_prefixes"] = json.dumps(_coerce_str_list(tp))
    try:
        fields["sort_order"] = int(body.get("sort_order") or 0)
    except (TypeError, ValueError):
        fields["sort_order"] = 0

    if for_create:
        key = (body.get("persona_key") or "").strip().lower()
        if not re.match(r"^[a-z0-9_]{1,40}$", key or ""):
            return None, "persona_key must be 1-40 chars of a-z, 0-9, underscore"
        builtin_keys = {p["persona_key"] for p in _admin_persona_registry()}
        if key in builtin_keys:
            return None, f"'{key}' is reserved by a built-in persona"
        fields["persona_key"] = key
    return fields, ""


# --------------------------------------------------------------------------- #
# Personas CRUD (super-admin only)                                            #
# --------------------------------------------------------------------------- #
@admin_ai_bp.route("/admin/api/admin-ai/personas", methods=["GET"])
@admin_required
def admin_ai_list_personas():
    """List every admin-chat persona (incl. disabled) for the editor."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    builtin_keys = {p["persona_key"] for p in _admin_persona_registry()}
    rows = query_db(
        "SELECT persona_key, label, icon, description, prompt_suffix, tool_prefixes, "
        "extra_tools, enabled, is_builtin, sort_order, updated_at, updated_by "
        "FROM admin_chat_personas WHERE tenant_id=%s ORDER BY sort_order, persona_key",
        (_ADMIN_AI_TENANT,)) or []
    return jsonify({"personas": [_row_admin_persona(r, builtin_keys) for r in rows]})


@admin_ai_bp.route("/admin/api/admin-ai/personas", methods=["POST"])
@admin_required
def admin_ai_create_persona():
    """Create a CUSTOM persona (is_builtin FALSE)."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    fields, err = _admin_persona_payload(request.get_json(silent=True) or {}, for_create=True)
    if err:
        return jsonify({"error": err}), 400
    if query_db("SELECT 1 FROM admin_chat_personas WHERE tenant_id=%s AND persona_key=%s",
                (_ADMIN_AI_TENANT, fields["persona_key"]), fetchone=True):
        return jsonify({"error": "persona_key already exists"}), 409
    try:
        execute_db(
            "INSERT INTO admin_chat_personas "
            "(tenant_id, persona_key, label, icon, description, prompt_suffix, "
            " tool_prefixes, extra_tools, enabled, is_builtin, sort_order, updated_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,FALSE,%s,%s)",
            (_ADMIN_AI_TENANT, fields["persona_key"], fields["label"], fields["icon"],
             fields["description"], fields["prompt_suffix"], fields["tool_prefixes"],
             fields["extra_tools"], fields["enabled"], fields["sort_order"], _who()))
    except Exception as e:
        print(f"[admin-ai] create persona failed: {e}")
        return jsonify({"error": "create_failed"}), 500
    _invalidate_admin_persona_cache()
    return jsonify({"ok": True, "persona_key": fields["persona_key"]}), 201


@admin_ai_bp.route("/admin/api/admin-ai/personas/<key>", methods=["PUT"])
@admin_required
def admin_ai_update_persona(key):
    """Update a persona (built-in or custom). persona_key is immutable; is_builtin
    is never changed from the body. Stamps updated_by so the boot sync preserves it.
    The 'general' fallback cannot be disabled."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    existing = query_db(
        "SELECT is_builtin FROM admin_chat_personas WHERE tenant_id=%s AND persona_key=%s",
        (_ADMIN_AI_TENANT, key), fetchone=True)
    if not existing:
        return jsonify({"error": "not_found"}), 404
    fields, err = _admin_persona_payload(request.get_json(silent=True) or {}, for_create=False)
    if err:
        return jsonify({"error": err}), 400
    if key == "general" and not fields["enabled"]:
        return jsonify({"error": "cannot disable the 'general' fallback persona"}), 400
    try:
        execute_db(
            "UPDATE admin_chat_personas SET label=%s, icon=%s, description=%s, "
            " prompt_suffix=%s, tool_prefixes=%s::jsonb, extra_tools=%s::jsonb, "
            " enabled=%s, sort_order=%s, updated_by=%s, updated_at=NOW() "
            "WHERE tenant_id=%s AND persona_key=%s",
            (fields["label"], fields["icon"], fields["description"], fields["prompt_suffix"],
             fields["tool_prefixes"], fields["extra_tools"], fields["enabled"],
             fields["sort_order"], _who(), _ADMIN_AI_TENANT, key))
    except Exception as e:
        print(f"[admin-ai] update persona {key} failed: {e}")
        return jsonify({"error": "update_failed"}), 500
    _invalidate_admin_persona_cache()
    return jsonify({"ok": True, "persona_key": key})


@admin_ai_bp.route("/admin/api/admin-ai/personas/<key>/reset", methods=["POST"])
@admin_required
def admin_ai_reset_persona(key):
    """Restore a BUILT-IN persona to its registry default and re-machine-own it
    (updated_by NULL) so future boot syncs manage it again. 400 for custom keys."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    defaults = _admin_persona_defaults()
    if key not in defaults:
        return jsonify({"error": "not a built-in persona; nothing to reset"}), 400
    p = defaults[key]
    tp = p.get("tool_prefixes")
    try:
        execute_db(
            "UPDATE admin_chat_personas SET label=%s, icon=%s, description=%s, "
            " prompt_suffix=%s, tool_prefixes=%s::jsonb, extra_tools=%s::jsonb, "
            " enabled=TRUE, is_builtin=TRUE, sort_order=%s, updated_by=NULL, updated_at=NOW() "
            "WHERE tenant_id=%s AND persona_key=%s",
            (p.get("label") or "", p.get("icon") or "", p.get("description") or "",
             p.get("prompt_suffix") or "",
             json.dumps(tp) if tp is not None else None,
             json.dumps(p.get("extra_tools") or []), int(p.get("sort_order") or 0),
             _ADMIN_AI_TENANT, key))
    except Exception as e:
        print(f"[admin-ai] reset persona {key} failed: {e}")
        return jsonify({"error": "reset_failed"}), 500
    _invalidate_admin_persona_cache()
    return jsonify({"ok": True, "persona_key": key, "is_default": True})


@admin_ai_bp.route("/admin/api/admin-ai/personas/<key>", methods=["DELETE"])
@admin_required
def admin_ai_delete_persona(key):
    """Delete a CUSTOM persona. Built-ins are reset/disable-only → 409."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    row = query_db(
        "SELECT is_builtin FROM admin_chat_personas WHERE tenant_id=%s AND persona_key=%s",
        (_ADMIN_AI_TENANT, key), fetchone=True)
    if not row:
        return jsonify({"error": "not_found"}), 404
    if row.get("is_builtin"):
        return jsonify({"error": "built-in personas cannot be deleted — disable it instead"}), 409
    execute_db("DELETE FROM admin_chat_personas WHERE tenant_id=%s AND persona_key=%s",
               (_ADMIN_AI_TENANT, key))
    _invalidate_admin_persona_cache()
    return jsonify({"ok": True, "deleted": key})


# --------------------------------------------------------------------------- #
# Chat consumption — any admin builds the persona pill from this               #
# --------------------------------------------------------------------------- #
@admin_ai_bp.route("/admin/api/chat/personas", methods=["GET"])
@admin_required
def admin_chat_personas_for_pill():
    """Enabled personas (ordered) for the chat's persona pill + ADMIN_PERSONA_META.
    Personas carry no role gate (they only shape behaviour; the real tool boundary
    is enforced at call time), so every admin sees the same enabled set."""
    personas = get_admin_personas()
    # Preserve sort order: get_admin_personas() returns a dict; re-order by sort_order.
    ordered = sorted(personas.values(), key=lambda p: (p.get("sort_order", 0), p.get("persona_key", "")))
    out = [{
        "key": p["persona_key"],
        "label": p.get("label") or p["persona_key"],
        "icon": p.get("icon") or "",
        "description": p.get("description") or "",
    } for p in ordered]
    return jsonify({"personas": out})
