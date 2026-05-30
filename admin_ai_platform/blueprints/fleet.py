"""
admin_ai_platform.blueprints.fleet
==================================

Fleet-sync HTTP surface (M22).

  * ``POST /api/fleet/bundle``                  master → instance: apply a signed,
    versioned bundle of managed defaults. Authenticated by an HMAC signature over
    the bundle (key = VELO_SHARED_SECRET), not the admin cookie — it's a
    server-to-server control call. Replay/downgrade-protected by bundle_version.
  * ``GET  /admin/api/fleet/status``            admin: this install's fleet state
  * ``GET  /admin/api/fleet/managed``           admin: managed items + override state
  * ``PUT  /admin/api/fleet/managed/<key>``     admin: set a local override {value}
  * ``POST /admin/api/fleet/managed/<key>/reset`` admin: drop the override

The bundle endpoint lives under ``/api`` (not ``/admin``) so it is NOT gated by
the admin-cookie CSRF check — its auth is the signature. It is also NOT an
embeddable endpoint (no embed-key / CORS).
"""

from __future__ import annotations

from flask import Blueprint, request, jsonify

from .. import config, fleet
from ..auth import admin_required

bp = Blueprint("fleet", __name__)


@bp.route("/api/fleet/bundle", methods=["POST"])
def receive_bundle():
    """Apply a signed managed-defaults bundle from the master. Fail closed when no
    shared secret is configured; 401 on a bad/missing signature."""
    if not config.VELO_SHARED_SECRET:
        return jsonify({"error": "fleet sync disabled (no VELO_SHARED_SECRET)"}), 503
    bundle = request.get_json(silent=True) or {}
    if not fleet.verify_signature(bundle):
        return jsonify({"error": "invalid bundle signature"}), 401
    result = fleet.apply_bundle(bundle)
    return jsonify(result), (200 if result.get("applied") or result.get("reason") else 400)


@bp.route("/admin/api/fleet/status", methods=["GET"])
@admin_required
def status():
    return jsonify(fleet.fleet_status())


@bp.route("/admin/api/fleet/managed", methods=["GET"])
@admin_required
def managed():
    return jsonify({"items": fleet.list_managed()})


@bp.route("/admin/api/fleet/managed/<path:item_key>", methods=["PUT"])
@admin_required
def set_override(item_key):
    d = request.get_json(silent=True) or {}
    if "value" not in d:
        return jsonify({"error": "value required"}), 400
    if not fleet.set_local_override(item_key, d["value"]):
        return jsonify({"error": "unknown managed item (master must seed it first)"}), 404
    return jsonify({"ok": True, "item_key": item_key, "overridden": True})


@bp.route("/admin/api/fleet/managed/<path:item_key>/reset", methods=["POST"])
@admin_required
def reset_override(item_key):
    if not fleet.reset_override(item_key):
        return jsonify({"error": "unknown managed item"}), 404
    return jsonify({"ok": True, "item_key": item_key, "overridden": False})
