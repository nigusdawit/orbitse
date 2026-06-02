"""admin/commerce.py - admin CRUD routes for bookable services, as a Flask blueprint.

Part of the app.py de-monolith (Track B), mirroring admin/content.py. These routes
cover the service catalog and its scheduling primitives: services CRUD, per-service
addons, recurring availability rules, and date overrides. All are gated by
@admin_required (from core) and do CRUD via query_db/execute_db (also from core).

URLs keep their absolute /admin/api/* paths, so the route table is unchanged - only
the Flask endpoint name gains a "commerce." prefix (admin JS calls these by URL, not
url_for). CSRF / feature-flag enforcement runs in app.py's global before_request
hooks, which apply to blueprint routes too, so nothing extra is needed here.

Helper placement (same rule as offers.py):
  - _slugify_service / _unique_service_slug and the SERVICE_PRICING_MODELS allowlist
    are used ONLY by these service routes, so they were moved here verbatim with them.
  - _service_to_dict / _hydrate_service (row serializers) are ALSO used by the public
    service + booking routes that remain in app.py, so they live in core and are
    imported from there (and re-exported by app.py for its remaining call sites).

The contract-template UPLOAD route stays in app.py: it uses the storage backend, which
is outside this blueprint's core-only dependency set.

Registered in app.py via app.register_blueprint(commerce_bp), after personas_bp.
Imports come from core (never app - that would be circular).
"""
import re

from flask import Blueprint, request, jsonify

from core import (
    query_db,
    execute_db,
    admin_required,
    _service_to_dict,
    _hydrate_service,
)

commerce_bp = Blueprint("commerce", __name__)


SERVICE_PRICING_MODELS = {"rsvp", "deposit", "full", "contract"}


def _slugify_service(text: str) -> str:
    """Lowercase ASCII slug used for public service URLs."""
    text = (text or "").lower().strip()
    out = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return out[:100] or "service"


def _unique_service_slug(name: str, exclude_id: int | None = None) -> str:
    """Pick a slug that doesn't collide with any other service row."""
    base = _slugify_service(name)
    candidate = base
    n = 1
    while True:
        existing = query_db(
            "SELECT id FROM services WHERE slug = %s AND (%s::int IS NULL OR id != %s)",
            (candidate, exclude_id, exclude_id),
            fetchone=True,
        )
        if not existing:
            return candidate
        n += 1
        candidate = f"{base}-{n}"


# --------------- Admin: services CRUD ---------------

@commerce_bp.route("/admin/api/services", methods=["GET"])
@admin_required
def admin_list_services():
    rows = query_db(
        "SELECT * FROM services ORDER BY sort_order ASC, id ASC"
    ) or []
    out = []
    for r in rows:
        d = _service_to_dict(r)
        d["addons"] = [_service_to_dict(a) for a in query_db(
            "SELECT * FROM service_addons WHERE service_id = %s "
            "ORDER BY sort_order ASC, id ASC", (d["id"],)
        ) or []]
        d["pending_bookings_count"] = (query_db(
            "SELECT COUNT(*) AS n FROM service_bookings "
            "WHERE service_id = %s AND status = 'pending'",
            (d["id"],), fetchone=True
        ) or {"n": 0})["n"]
        out.append(d)
    return jsonify(out)


@commerce_bp.route("/admin/api/services", methods=["POST"])
@admin_required
def admin_create_service():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400
    pricing_model = (data.get("pricing_model") or "rsvp").strip()
    if pricing_model not in SERVICE_PRICING_MODELS:
        return jsonify({"error": "Invalid pricing model"}), 400
    slug = _unique_service_slug(data.get("slug") or name)

    row = execute_db(
        """INSERT INTO services
           (slug, name, short_description, long_description, image_url,
            duration_minutes, pricing_model, base_price_cents, deposit_cents,
            currency, requires_calendar, capacity_per_slot, sort_order, is_active)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING *""",
        (
            slug, name,
            data.get("short_description", ""),
            data.get("long_description", ""),
            data.get("image_url", ""),
            int(data.get("duration_minutes") or 60),
            pricing_model,
            int(data.get("base_price_cents") or 0),
            int(data.get("deposit_cents") or 0),
            (data.get("currency") or "usd").lower(),
            bool(data.get("requires_calendar", True)),
            max(1, int(data.get("capacity_per_slot") or 1)),
            int(data.get("sort_order") or 0),
            bool(data.get("is_active", True)),
        ),
    )
    return jsonify(_hydrate_service(row)), 201


@commerce_bp.route("/admin/api/services/<int:svc_id>", methods=["PUT"])
@admin_required
def admin_update_service(svc_id):
    data = request.get_json() or {}
    existing = query_db("SELECT * FROM services WHERE id = %s",
                        (svc_id,), fetchone=True)
    if not existing:
        return jsonify({"error": "Service not found"}), 404
    name = (data.get("name") or existing["name"]).strip()
    pricing_model = (data.get("pricing_model") or existing["pricing_model"]).strip()
    if pricing_model not in SERVICE_PRICING_MODELS:
        return jsonify({"error": "Invalid pricing model"}), 400
    new_slug = data.get("slug")
    if new_slug:
        slug = _unique_service_slug(new_slug, exclude_id=svc_id)
    else:
        slug = existing["slug"]

    row = execute_db(
        """UPDATE services SET
             slug = %s, name = %s, short_description = %s,
             long_description = %s, image_url = %s,
             duration_minutes = %s, pricing_model = %s,
             base_price_cents = %s, deposit_cents = %s,
             currency = %s, requires_calendar = %s,
             capacity_per_slot = %s, sort_order = %s,
             is_active = %s, updated_at = NOW()
           WHERE id = %s RETURNING *""",
        (
            slug, name,
            data.get("short_description", existing["short_description"]),
            data.get("long_description", existing["long_description"]),
            data.get("image_url", existing["image_url"]),
            int(data.get("duration_minutes", existing["duration_minutes"])),
            pricing_model,
            int(data.get("base_price_cents", existing["base_price_cents"])),
            int(data.get("deposit_cents", existing["deposit_cents"])),
            (data.get("currency", existing["currency"]) or "usd").lower(),
            bool(data.get("requires_calendar", existing["requires_calendar"])),
            max(1, int(data.get("capacity_per_slot", existing["capacity_per_slot"]))),
            int(data.get("sort_order", existing["sort_order"])),
            bool(data.get("is_active", existing["is_active"])),
            svc_id,
        ),
    )
    return jsonify(_hydrate_service(row))


@commerce_bp.route("/admin/api/services/<int:svc_id>", methods=["DELETE"])
@admin_required
def admin_delete_service(svc_id):
    n = execute_db("DELETE FROM services WHERE id = %s", (svc_id,))
    if n == 0:
        return jsonify({"error": "Service not found"}), 404
    return jsonify({"success": True})


# --------------- Admin: addons CRUD ---------------

@commerce_bp.route("/admin/api/services/<int:svc_id>/addons", methods=["GET"])
@admin_required
def admin_list_addons(svc_id):
    rows = query_db(
        "SELECT * FROM service_addons WHERE service_id = %s "
        "ORDER BY sort_order ASC, id ASC", (svc_id,)
    ) or []
    return jsonify([_service_to_dict(r) for r in rows])


@commerce_bp.route("/admin/api/services/<int:svc_id>/addons", methods=["POST"])
@admin_required
def admin_create_addon(svc_id):
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    row = execute_db(
        "INSERT INTO service_addons "
        "(service_id, name, description, price_cents, sort_order, is_active) "
        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
        (
            svc_id, name,
            data.get("description", ""),
            int(data.get("price_cents") or 0),
            int(data.get("sort_order") or 0),
            bool(data.get("is_active", True)),
        ),
    )
    return jsonify(_service_to_dict(row)), 201


@commerce_bp.route("/admin/api/addons/<int:addon_id>", methods=["PUT"])
@admin_required
def admin_update_addon(addon_id):
    data = request.get_json() or {}
    row = execute_db(
        "UPDATE service_addons SET "
        "name = %s, description = %s, price_cents = %s, "
        "sort_order = %s, is_active = %s "
        "WHERE id = %s RETURNING *",
        (
            data.get("name", ""),
            data.get("description", ""),
            int(data.get("price_cents") or 0),
            int(data.get("sort_order") or 0),
            bool(data.get("is_active", True)),
            addon_id,
        ),
    )
    if not row:
        return jsonify({"error": "Addon not found"}), 404
    return jsonify(_service_to_dict(row))


@commerce_bp.route("/admin/api/addons/<int:addon_id>", methods=["DELETE"])
@admin_required
def admin_delete_addon(addon_id):
    n = execute_db("DELETE FROM service_addons WHERE id = %s", (addon_id,))
    if n == 0:
        return jsonify({"error": "Addon not found"}), 404
    return jsonify({"success": True})


# --------------- Admin: availability rules + overrides ---------------

@commerce_bp.route("/admin/api/services/<int:svc_id>/availability", methods=["GET"])
@admin_required
def admin_list_availability(svc_id):
    rules = query_db(
        "SELECT * FROM service_availability_rules WHERE service_id = %s "
        "ORDER BY day_of_week, start_time", (svc_id,)
    ) or []
    overrides = query_db(
        "SELECT * FROM service_availability_overrides WHERE service_id = %s "
        "ORDER BY override_date, COALESCE(start_time, '00:00')", (svc_id,)
    ) or []
    return jsonify({
        "rules": [_service_to_dict(r) for r in rules],
        "overrides": [_service_to_dict(o) for o in overrides],
    })


@commerce_bp.route("/admin/api/services/<int:svc_id>/rules", methods=["POST"])
@admin_required
def admin_create_rule(svc_id):
    data = request.get_json() or {}
    row = execute_db(
        "INSERT INTO service_availability_rules "
        "(service_id, day_of_week, start_time, end_time, slot_minutes, is_active) "
        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
        (
            svc_id,
            int(data.get("day_of_week") or 0),
            data.get("start_time", "09:00"),
            data.get("end_time", "17:00"),
            int(data.get("slot_minutes") or 60),
            bool(data.get("is_active", True)),
        ),
    )
    return jsonify(_service_to_dict(row)), 201


@commerce_bp.route("/admin/api/rules/<int:rule_id>", methods=["PUT"])
@admin_required
def admin_update_rule(rule_id):
    data = request.get_json() or {}
    row = execute_db(
        "UPDATE service_availability_rules SET "
        "day_of_week = %s, start_time = %s, end_time = %s, "
        "slot_minutes = %s, is_active = %s "
        "WHERE id = %s RETURNING *",
        (
            int(data.get("day_of_week") or 0),
            data.get("start_time", "09:00"),
            data.get("end_time", "17:00"),
            int(data.get("slot_minutes") or 60),
            bool(data.get("is_active", True)),
            rule_id,
        ),
    )
    if not row:
        return jsonify({"error": "Rule not found"}), 404
    return jsonify(_service_to_dict(row))


@commerce_bp.route("/admin/api/rules/<int:rule_id>", methods=["DELETE"])
@admin_required
def admin_delete_rule(rule_id):
    n = execute_db("DELETE FROM service_availability_rules WHERE id = %s", (rule_id,))
    if n == 0:
        return jsonify({"error": "Rule not found"}), 404
    return jsonify({"success": True})


@commerce_bp.route("/admin/api/services/<int:svc_id>/overrides", methods=["POST"])
@admin_required
def admin_create_override(svc_id):
    data = request.get_json() or {}
    kind = (data.get("override_kind") or "block").strip()
    if kind not in ("block", "open"):
        return jsonify({"error": "override_kind must be 'block' or 'open'"}), 400
    row = execute_db(
        "INSERT INTO service_availability_overrides "
        "(service_id, override_date, start_time, end_time, override_kind, "
        " slot_minutes, note) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (
            svc_id,
            data.get("override_date"),
            data.get("start_time") or None,
            data.get("end_time") or None,
            kind,
            int(data.get("slot_minutes") or 60),
            data.get("note", ""),
        ),
    )
    return jsonify(_service_to_dict(row)), 201


@commerce_bp.route("/admin/api/overrides/<int:ovr_id>", methods=["DELETE"])
@admin_required
def admin_delete_override(ovr_id):
    n = execute_db(
        "DELETE FROM service_availability_overrides WHERE id = %s", (ovr_id,)
    )
    if n == 0:
        return jsonify({"error": "Override not found"}), 404
    return jsonify({"success": True})
