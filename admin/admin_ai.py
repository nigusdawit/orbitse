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
    _is_super_admin,
    _admin_persona_registry,
    _admin_persona_defaults,
    get_admin_personas,
    get_admin_personas_all,
    _invalidate_admin_persona_cache,
    # task 088 phase 3: palette default registries (commands/capabilities/starters)
    _admin_command_registry,
    _admin_capability_registry,
    _admin_starter_registry,
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


def _row_admin_persona(r):
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
    rows = query_db(
        "SELECT persona_key, label, icon, description, prompt_suffix, tool_prefixes, "
        "extra_tools, enabled, is_builtin, sort_order, updated_at, updated_by "
        "FROM admin_chat_personas WHERE tenant_id=%s ORDER BY sort_order, persona_key",
        (_ADMIN_AI_TENANT,)) or []
    return jsonify({"personas": [_row_admin_persona(r) for r in rows]})


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


# =========================================================================== #
# PALETTE (task 088 phase 3) — slash-commands / capability groups / starters.  #
# Front-end-only config (the chat just seeds the composer from these). One     #
# generic CRUD, parametrized by <entity>, keyed by ROW ID (slash-commands hold #
# a '/' so a key in the URL won't path-match). Built-ins reset/disable-only.   #
# =========================================================================== #
def _jload(v, fallback):
    if v is None:
        return fallback
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return fallback


# Per-entity config. `fields` = (column, kind); kind drives coercion. `jsonb`
# columns get a ::jsonb cast. Column names match both the table and the registry
# dict keys, so the same list seeds, validates, serializes, and resets.
_PALETTE = {
    "commands": {
        "table": "admin_chat_commands", "key_col": "cmd", "key_kind": "cmd",
        "registry": _admin_command_registry, "jsonb": (),
        "fields": [("icon", "str"), ("group_label", "str"), ("tool", "str"),
                   ("description", "str"), ("seed", "str"), ("arg", "str"),
                   ("tail", "bool"), ("persona", "str"), ("super", "bool")],
    },
    "capabilities": {
        "table": "admin_chat_capabilities", "key_col": "cap_key", "key_kind": "slug",
        "registry": _admin_capability_registry, "jsonb": ("lines", "examples"),
        "fields": [("icon", "str"), ("title", "str"), ("super", "bool"),
                   ("grant_aware", "bool"), ("lines", "jsonlist_str"),
                   ("examples", "jsonlist_obj")],
    },
    "starters": {
        "table": "admin_chat_starters", "key_col": "starter_key", "key_kind": "slug",
        "registry": _admin_starter_registry, "jsonb": (),
        "fields": [("icon", "str"), ("label", "str"), ("seed", "str"),
                   ("persona", "str"), ("super", "bool")],
    },
}
_PALETTE_STR_CAPS = {"icon": 16, "persona": 40, "group_label": 80, "tool": 120, "arg": 120}


def _palette_cols(cfg):
    return [c for c, _t in cfg["fields"]]


def _coerce_example_list(v):
    """Coerce a capability group's `examples` into [{label, seed, persona?, action?}]."""
    if not isinstance(v, list):
        return []
    out = []
    for ex in v[:20]:
        if not isinstance(ex, dict):
            continue
        o = {"label": str(ex.get("label") or "").strip()[:120],
             "seed": str(ex.get("seed") or "").strip()[:2000]}
        if ex.get("persona"):
            o["persona"] = str(ex.get("persona")).strip()[:40]
        if ex.get("action"):
            o["action"] = str(ex.get("action")).strip()[:40]
        if o["label"] or o["seed"]:
            out.append(o)
    return out


def _validate_palette_key(cfg, key):
    """Validate a create key. Commands look like '/name'; cap/starter keys are
    slugs. Built-in keys are reserved."""
    if cfg["key_kind"] == "cmd":
        if not re.match(r"^/[a-z0-9_-]{1,38}$", key or ""):
            return "command must look like /name (lowercase a-z, 0-9, _, -)"
    else:
        if not re.match(r"^[a-z0-9_]{1,58}$", key or ""):
            return "key must be 1-58 chars of a-z, 0-9, underscore"
    builtin_keys = {d[cfg["key_col"]] for d in cfg["registry"]()}
    if key in builtin_keys:
        return "'%s' is reserved by a built-in" % key
    return ""


def _palette_coerce(cfg, body, for_create):
    """Whitelist + coerce a create/update body (prevents mass-assignment of
    is_builtin/tenant_id/updated_by). Returns (fields, error)."""
    fields = {"enabled": bool(body.get("enabled", True))}
    try:
        fields["sort_order"] = int(body.get("sort_order") or 0)
    except (TypeError, ValueError):
        fields["sort_order"] = 0
    for c, t in cfg["fields"]:
        v = body.get(c)
        if t == "bool":
            fields[c] = bool(v)
        elif t == "jsonlist_str":
            fields[c] = json.dumps(_coerce_str_list(v, cap_item=400, cap_len=20))
        elif t == "jsonlist_obj":
            fields[c] = json.dumps(_coerce_example_list(v))
        else:
            fields[c] = (str(v) if v is not None else "").strip()[:_PALETTE_STR_CAPS.get(c, 4000)]
    if for_create:
        key = (body.get(cfg["key_col"]) or "").strip().lower()
        err = _validate_palette_key(cfg, key)
        if err:
            return None, err
        fields[cfg["key_col"]] = key
    return fields, ""


def _row_palette(cfg, r):
    """Serialize a palette row for the editor (incl. id + is_default)."""
    out = {"id": r.get("id"), cfg["key_col"]: r.get(cfg["key_col"])}
    for c, _t in cfg["fields"]:
        out[c] = _jload(r.get(c), []) if c in cfg["jsonb"] else r.get(c)
    out["enabled"] = bool(r.get("enabled", True))
    out["is_builtin"] = bool(r.get("is_builtin", False))
    out["sort_order"] = r.get("sort_order") or 0
    out["updated_by"] = r.get("updated_by")
    out["is_default"] = out["is_builtin"] and r.get("updated_by") is None
    return out


def _palette_chat_shape(entity, r):
    """Shape a palette row for the CHAT front-end — field names match the former
    hardcoded csrf.js consts (group/desc, key/grant) so the renderers are unchanged."""
    if entity == "commands":
        return {"cmd": r.get("cmd"), "icon": r.get("icon") or "", "group": r.get("group_label") or "",
                "tool": r.get("tool") or "", "desc": r.get("description") or "",
                "seed": r.get("seed") or "", "arg": r.get("arg") or "",
                "tail": bool(r.get("tail")), "persona": r.get("persona") or "",
                "super": bool(r.get("super"))}
    if entity == "capabilities":
        return {"key": r.get("cap_key"), "icon": r.get("icon") or "", "title": r.get("title") or "",
                "super": bool(r.get("super")), "grant": bool(r.get("grant_aware")),
                "lines": _jload(r.get("lines"), []), "examples": _jload(r.get("examples"), [])}
    return {"icon": r.get("icon") or "", "label": r.get("label") or "",
            "seed": r.get("seed") or "", "persona": r.get("persona") or "",
            "super": bool(r.get("super"))}


@admin_ai_bp.route("/admin/api/admin-ai/<entity>", methods=["GET"])
@admin_required
def admin_ai_list_palette(entity):
    guard = _require_super_admin_role()
    if guard:
        return guard
    cfg = _PALETTE.get(entity)
    if not cfg:
        return jsonify({"error": "unknown_entity"}), 404
    rows = query_db(
        f"SELECT * FROM {cfg['table']} WHERE tenant_id=%s ORDER BY sort_order, id",
        (_ADMIN_AI_TENANT,)) or []
    return jsonify({entity: [_row_palette(cfg, r) for r in rows]})


@admin_ai_bp.route("/admin/api/admin-ai/<entity>", methods=["POST"])
@admin_required
def admin_ai_create_palette(entity):
    guard = _require_super_admin_role()
    if guard:
        return guard
    cfg = _PALETTE.get(entity)
    if not cfg:
        return jsonify({"error": "unknown_entity"}), 404
    fields, err = _palette_coerce(cfg, request.get_json(silent=True) or {}, for_create=True)
    if err:
        return jsonify({"error": err}), 400
    keyc = cfg["key_col"]
    if query_db(f"SELECT 1 FROM {cfg['table']} WHERE tenant_id=%s AND {keyc}=%s",
                (_ADMIN_AI_TENANT, fields[keyc]), fetchone=True):
        return jsonify({"error": "key already exists"}), 409
    cols = _palette_cols(cfg)
    allcols = [keyc] + cols
    ph = ", ".join("%s::jsonb" if c in cfg["jsonb"] else "%s" for c in allcols)
    params = [_ADMIN_AI_TENANT] + [fields[c] for c in allcols] + [fields["enabled"], fields["sort_order"], _who()]
    try:
        execute_db(
            f"INSERT INTO {cfg['table']} (tenant_id, {', '.join(allcols)}, enabled, is_builtin, sort_order, updated_by) "
            f"VALUES (%s, {ph}, %s, FALSE, %s, %s)", tuple(params))
    except Exception as e:
        print(f"[admin-ai] create {entity} failed: {e}")
        return jsonify({"error": "create_failed"}), 500
    return jsonify({"ok": True, "key": fields[keyc]}), 201


@admin_ai_bp.route("/admin/api/admin-ai/<entity>/<int:item_id>", methods=["PUT"])
@admin_required
def admin_ai_update_palette(entity, item_id):
    guard = _require_super_admin_role()
    if guard:
        return guard
    cfg = _PALETTE.get(entity)
    if not cfg:
        return jsonify({"error": "unknown_entity"}), 404
    if not query_db(f"SELECT 1 FROM {cfg['table']} WHERE tenant_id=%s AND id=%s",
                    (_ADMIN_AI_TENANT, item_id), fetchone=True):
        return jsonify({"error": "not_found"}), 404
    fields, err = _palette_coerce(cfg, request.get_json(silent=True) or {}, for_create=False)
    if err:
        return jsonify({"error": err}), 400
    cols = _palette_cols(cfg)
    set_parts, params = [], []
    for c in cols:
        set_parts.append(f"{c}=%s::jsonb" if c in cfg["jsonb"] else f"{c}=%s")
        params.append(fields[c])
    set_parts += ["enabled=%s", "sort_order=%s", "updated_by=%s", "updated_at=NOW()"]
    params += [fields["enabled"], fields["sort_order"], _who(), _ADMIN_AI_TENANT, item_id]
    try:
        execute_db(
            f"UPDATE {cfg['table']} SET {', '.join(set_parts)} WHERE tenant_id=%s AND id=%s",
            tuple(params))
    except Exception as e:
        print(f"[admin-ai] update {entity} {item_id} failed: {e}")
        return jsonify({"error": "update_failed"}), 500
    return jsonify({"ok": True, "id": item_id})


@admin_ai_bp.route("/admin/api/admin-ai/<entity>/<int:item_id>/reset", methods=["POST"])
@admin_required
def admin_ai_reset_palette(entity, item_id):
    guard = _require_super_admin_role()
    if guard:
        return guard
    cfg = _PALETTE.get(entity)
    if not cfg:
        return jsonify({"error": "unknown_entity"}), 404
    keyc = cfg["key_col"]
    row = query_db(f"SELECT {keyc}, is_builtin FROM {cfg['table']} WHERE tenant_id=%s AND id=%s",
                   (_ADMIN_AI_TENANT, item_id), fetchone=True)
    if not row:
        return jsonify({"error": "not_found"}), 404
    if not row.get("is_builtin"):
        return jsonify({"error": "not a built-in; nothing to reset"}), 400
    defaults = {d[keyc]: d for d in cfg["registry"]()}
    d = defaults.get(row.get(keyc))
    if not d:
        return jsonify({"error": "no built-in default for this key"}), 400
    cols = _palette_cols(cfg)
    set_parts, params = [], []
    for c in cols:
        set_parts.append(f"{c}=%s::jsonb" if c in cfg["jsonb"] else f"{c}=%s")
        v = d.get(c)
        params.append(json.dumps(v if v is not None else []) if c in cfg["jsonb"] else v)
    set_parts += ["enabled=TRUE", "is_builtin=TRUE", "sort_order=%s", "updated_by=NULL", "updated_at=NOW()"]
    params += [int(d.get("sort_order") or 0), _ADMIN_AI_TENANT, item_id]
    try:
        execute_db(
            f"UPDATE {cfg['table']} SET {', '.join(set_parts)} WHERE tenant_id=%s AND id=%s",
            tuple(params))
    except Exception as e:
        print(f"[admin-ai] reset {entity} {item_id} failed: {e}")
        return jsonify({"error": "reset_failed"}), 500
    return jsonify({"ok": True, "id": item_id, "is_default": True})


@admin_ai_bp.route("/admin/api/admin-ai/<entity>/<int:item_id>", methods=["DELETE"])
@admin_required
def admin_ai_delete_palette(entity, item_id):
    guard = _require_super_admin_role()
    if guard:
        return guard
    cfg = _PALETTE.get(entity)
    if not cfg:
        return jsonify({"error": "unknown_entity"}), 404
    row = query_db(f"SELECT is_builtin FROM {cfg['table']} WHERE tenant_id=%s AND id=%s",
                   (_ADMIN_AI_TENANT, item_id), fetchone=True)
    if not row:
        return jsonify({"error": "not_found"}), 404
    if row.get("is_builtin"):
        return jsonify({"error": "built-in items cannot be deleted — disable it instead"}), 409
    execute_db(f"DELETE FROM {cfg['table']} WHERE tenant_id=%s AND id=%s",
               (_ADMIN_AI_TENANT, item_id))
    return jsonify({"ok": True, "deleted": item_id})


@admin_ai_bp.route("/admin/api/chat/palette", methods=["GET"])
@admin_required
def admin_chat_palette():
    """Enabled palette for the chat: {commands, capabilities, starters}. Server-side
    role filter — super-admin-only rows are dropped for a non-super admin (the chat
    keeps a client-side filter too as defense). Field names match the former csrf.js
    consts so the renderers are unchanged."""
    is_super = _is_super_admin()

    def fetch(entity):
        cfg = _PALETTE[entity]
        sql = (f"SELECT * FROM {cfg['table']} WHERE tenant_id=%s AND enabled=TRUE "
               + ("" if is_super else "AND super=FALSE ")
               + "ORDER BY sort_order, id")
        rows = query_db(sql, (_ADMIN_AI_TENANT,)) or []
        return [_palette_chat_shape(entity, r) for r in rows]

    return jsonify({
        "commands": fetch("commands"),
        "capabilities": fetch("capabilities"),
        "starters": fetch("starters"),
    })
