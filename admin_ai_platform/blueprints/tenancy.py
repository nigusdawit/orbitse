"""
admin_ai_platform.blueprints.tenancy
====================================

Agency/operator-side controls:
  * Plans & Features — list + per-tenant toggle of feature flags.
  * Embed keys — publishable per-tenant keys + origin allowlist for the
    cross-origin widget (M7 enforces these on the embeddable endpoints).
  * Snapshot/clone — export the tenant's config as JSON and re-apply it.
  * Secrets — env-var PRESENCE view (names + booleans, never values).
  * Dev console — a quick health/overview snapshot.

  * ``GET /admin/api/plans-features`` · ``POST /admin/api/features/toggle``
  * ``GET/POST /admin/api/embed-keys`` · ``PUT/DELETE /admin/api/embed-keys/<id>``
  * ``GET /admin/api/snapshot/export`` · ``POST /admin/api/snapshot/apply``
  * ``GET /admin/api/secrets`` · ``GET /admin/api/devconsole/overview``
"""

from __future__ import annotations

import json
import secrets as _secrets

from flask import Blueprint, request, jsonify

from .. import config
from ..db import query_db, execute_db
from ..auth import admin_required
from ..tenancy import (current_tenant_id, list_tenant_features, tenant_has_feature,
                       invalidate_tenant_features_cache, _FEATURE_NAMES)

bp = Blueprint("tenancy", __name__)


# ---- Plans & Features ---------------------------------------------------
@bp.route("/admin/api/plans-features", methods=["GET"])
@admin_required
def plans_features():
    return jsonify({"features": list_tenant_features(), "deploy_mode": config.DEPLOY_MODE,
                    "admin_mode": config.ADMIN_MODE})


@bp.route("/admin/api/features/toggle", methods=["POST"])
@admin_required
def toggle_feature():
    d = request.get_json() or {}
    name = d.get("name")
    if name not in _FEATURE_NAMES:
        return jsonify({"error": "unknown feature"}), 400
    tid = current_tenant_id()
    execute_db(
        "INSERT INTO tenant_features (tenant_id, feature_name, enabled) VALUES (%s,%s,%s) "
        "ON CONFLICT (tenant_id, feature_name) DO UPDATE SET enabled=EXCLUDED.enabled, updated_at=NOW()",
        (tid, name, bool(d.get("enabled", True))))
    invalidate_tenant_features_cache(tid)
    return jsonify({"name": name, "enabled": tenant_has_feature(name, tid)})


# ---- Embed keys (feeds M7) ---------------------------------------------
@bp.route("/admin/api/embed-keys", methods=["GET"])
@admin_required
def list_embed_keys():
    rows = query_db("SELECT * FROM tenant_embed_keys WHERE tenant_id=%s ORDER BY id DESC",
                    (current_tenant_id(),))
    return jsonify({"keys": rows or []})


@bp.route("/admin/api/embed-keys", methods=["POST"])
@admin_required
def create_embed_key():
    d = request.get_json() or {}
    key = "pk_" + _secrets.token_urlsafe(24)
    row = execute_db(
        "INSERT INTO tenant_embed_keys (tenant_id, embed_key, label, origin_allowlist) "
        "VALUES (%s,%s,%s,%s::jsonb) RETURNING *",
        (current_tenant_id(), key, d.get("label", ""),
         json.dumps(d.get("origin_allowlist", []))))
    return jsonify(row), 201


@bp.route("/admin/api/embed-keys/<int:kid>", methods=["PUT"])
@admin_required
def update_embed_key(kid):
    d = request.get_json() or {}
    sets, vals = [], []
    if "label" in d:
        sets.append("label=%s")
        vals.append(d["label"])
    if "origin_allowlist" in d:
        sets.append("origin_allowlist=%s::jsonb")
        vals.append(json.dumps(d["origin_allowlist"]))
    if "enabled" in d:
        sets.append("enabled=%s")
        vals.append(bool(d["enabled"]))
    if not sets:
        return jsonify({"error": "No fields"}), 400
    vals.extend([kid, current_tenant_id()])
    row = execute_db(f"UPDATE tenant_embed_keys SET {', '.join(sets)} WHERE id=%s AND tenant_id=%s "
                     f"RETURNING *", tuple(vals))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/embed-keys/<int:kid>", methods=["DELETE"])
@admin_required
def delete_embed_key(kid):
    execute_db("DELETE FROM tenant_embed_keys WHERE id=%s AND tenant_id=%s",
               (kid, current_tenant_id()))
    return jsonify({"success": True})


# ---- Snapshot / clone ---------------------------------------------------
# Export the tenant's *template* config (not runtime/customer data) as JSON, and
# re-apply it (UPSERT by natural key) to clone one install onto another.
_SNAPSHOT_TABLES = {
    "chatbot_settings": "id=1", "agent_provider_settings": "id=1",
    "gallery_cards": None, "custom_forms": None, "presentations": None,
}


@bp.route("/admin/api/snapshot/export", methods=["GET"])
@admin_required
def snapshot_export():
    out = {"version": 1, "tables": {}}
    for table, where in _SNAPSHOT_TABLES.items():
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {where}"
        out["tables"][table] = query_db(sql) or []
    # Feature flags too (so plan/feature config travels).
    out["features"] = list_tenant_features()
    return jsonify(out)


@bp.route("/admin/api/snapshot/apply", methods=["POST"])
@admin_required
def snapshot_apply():
    snap = request.get_json() or {}
    tables = snap.get("tables", {})
    applied = {}
    # Gallery cards: UPSERT by slug (the common clone need). Other tables are
    # left to the operator to avoid clobbering singletons unexpectedly.
    for card in tables.get("gallery_cards", []):
        try:
            execute_db(
                "INSERT INTO gallery_cards (slug, title, subtitle, image_url, category, "
                " description, details, price, sort_order) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s) "
                "ON CONFLICT (slug) DO UPDATE SET title=EXCLUDED.title, subtitle=EXCLUDED.subtitle, "
                " image_url=EXCLUDED.image_url, category=EXCLUDED.category, "
                " description=EXCLUDED.description, details=EXCLUDED.details, price=EXCLUDED.price, "
                " sort_order=EXCLUDED.sort_order, updated_at=NOW()",
                (card.get("slug"), card.get("title", ""), card.get("subtitle", ""),
                 card.get("image_url", ""), card.get("category", ""), card.get("description", ""),
                 json.dumps(card.get("details", [])), card.get("price"),
                 int(card.get("sort_order", 0) or 0)))
        except Exception as e:
            print(f"[snapshot] gallery upsert failed: {e}")
    applied["gallery_cards"] = len(tables.get("gallery_cards", []))
    return jsonify({"applied": applied})


# ---- Secrets (presence only) + dev console ------------------------------
@bp.route("/admin/api/secrets", methods=["GET"])
@admin_required
def secrets_view():
    # NEVER return values — only whether each integration is configured.
    return jsonify(config.summary())


@bp.route("/admin/api/devconsole/overview", methods=["GET"])
@admin_required
def devconsole():
    def c(sql):
        return (query_db(sql, fetchone=True) or {}).get("c", 0)
    return jsonify({
        "config": config.summary(),
        "counts": {
            "gallery_cards": c("SELECT COUNT(*) AS c FROM gallery_cards"),
            "conversations": c("SELECT COUNT(*) AS c FROM chat_conversations"),
            "forms": c("SELECT COUNT(*) AS c FROM custom_forms"),
            "automations": c("SELECT COUNT(*) AS c FROM automations"),
            "products": c("SELECT COUNT(*) AS c FROM products"),
            "services": c("SELECT COUNT(*) AS c FROM services"),
        },
    })
