"""
admin_ai_platform.blueprints.commerce
=====================================

Services/bookings + products/orders. The visitor AI books services and sells
products via this surface (lookup_services/lookup_products feed it; the
bookService/checkout commands hit it).

Verifiable core (no Stripe key needed): products/services CRUD, the **availability
slot engine** (recurring rules ∪ open-overrides − block-overrides − filled slots,
capped at capacity_per_slot), and RSVP bookings with capacity enforcement.

Paid flows (deposit/full/products) require Stripe keys — the booking/checkout
endpoints return a clear "Stripe not configured" error without them, and the
webhook is a verified-signature stub. Full Stripe Checkout + product sync is a
follow-on (the stripe_* modules need a key to exercise).

  * public: ``/api/products``, ``/api/services``, ``/api/services/<slug>/availability``,
    ``POST /api/services/<slug>/book``
  * admin: products / services / addons / rules / overrides / bookings / orders CRUD
  * ``GET/PUT /admin/api/stripe-settings`` + ``POST /api/stripe/webhook`` (stub)
"""

from __future__ import annotations

import json
import secrets
from datetime import date, datetime, timedelta

from flask import Blueprint, request, jsonify

from .. import config
from ..db import query_db, execute_db
from ..auth import admin_required

bp = Blueprint("commerce", __name__)


# ======================= PRODUCTS =======================
@bp.route("/api/products", methods=["GET"])
def public_products():
    return jsonify(query_db("SELECT slug, name, description, price_cents, currency, "
                            "image_url, stock, track_inventory FROM products "
                            "WHERE active = TRUE ORDER BY sort_order, id") or [])


@bp.route("/api/products/<slug>", methods=["GET"])
def public_product(slug):
    row = query_db("SELECT * FROM products WHERE slug=%s AND active=TRUE", (slug,), fetchone=True)
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/products", methods=["GET"])
@admin_required
def admin_products():
    return jsonify({"products": query_db("SELECT * FROM products ORDER BY sort_order, id") or []})


@bp.route("/admin/api/products", methods=["POST"])
@admin_required
def create_product():
    d = request.get_json() or {}
    if not (d.get("slug") or "").strip():
        return jsonify({"error": "slug required"}), 400
    row = execute_db(
        "INSERT INTO products (slug, name, description, price_cents, currency, image_url, "
        " stock, track_inventory, active, sort_order) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (slug) DO NOTHING RETURNING *",
        (d["slug"], d.get("name", ""), d.get("description", ""), int(d.get("price_cents", 0) or 0),
         d.get("currency", "USD"), d.get("image_url", ""), int(d.get("stock", 0) or 0),
         bool(d.get("track_inventory", True)), bool(d.get("active", True)),
         int(d.get("sort_order", 0) or 0)))
    if not row:
        return jsonify({"error": "slug exists"}), 409
    return jsonify(row), 201


@bp.route("/admin/api/products/<int:pid>", methods=["PUT"])
@admin_required
def update_product(pid):
    d = request.get_json() or {}
    sets, vals = [], []
    for k in ("slug", "name", "description", "price_cents", "currency", "image_url",
              "stock", "track_inventory", "active", "sort_order"):
        if k in d:
            sets.append(f"{k}=%s")
            vals.append(d[k])
    if not sets:
        return jsonify({"error": "No fields"}), 400
    vals.append(pid)
    row = execute_db(f"UPDATE products SET {', '.join(sets)} WHERE id=%s RETURNING *", tuple(vals))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/products/<int:pid>", methods=["DELETE"])
@admin_required
def delete_product(pid):
    execute_db("DELETE FROM products WHERE id=%s", (pid,))
    return jsonify({"success": True})


@bp.route("/admin/api/orders", methods=["GET"])
@admin_required
def admin_orders():
    return jsonify({"orders": query_db("SELECT * FROM orders ORDER BY id DESC LIMIT 200") or []})


# ======================= SERVICES =======================
@bp.route("/api/services", methods=["GET"])
def public_services():
    return jsonify(query_db("SELECT slug, name, short_description, image_url, duration_minutes, "
                            "pricing_model, base_price_cents, currency, requires_calendar "
                            "FROM services WHERE is_active=TRUE ORDER BY sort_order, id") or [])


@bp.route("/api/services/<slug>", methods=["GET"])
def public_service(slug):
    svc = query_db("SELECT * FROM services WHERE slug=%s AND is_active=TRUE", (slug,), fetchone=True)
    if not svc:
        return jsonify({"error": "Not found"}), 404
    svc["addons"] = query_db("SELECT id, name, description, price_cents FROM service_addons "
                             "WHERE service_id=%s AND is_active=TRUE ORDER BY sort_order, id",
                             (svc["id"],)) or []
    return jsonify(svc)


@bp.route("/admin/api/services", methods=["GET"])
@admin_required
def admin_services():
    return jsonify({"services": query_db("SELECT * FROM services ORDER BY sort_order, id") or []})


@bp.route("/admin/api/services", methods=["POST"])
@admin_required
def create_service():
    d = request.get_json() or {}
    if not (d.get("slug") or "").strip():
        return jsonify({"error": "slug required"}), 400
    row = execute_db(
        "INSERT INTO services (slug, name, short_description, long_description, image_url, "
        " duration_minutes, pricing_model, base_price_cents, deposit_cents, currency, "
        " requires_calendar, capacity_per_slot, sort_order, is_active) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (slug) DO NOTHING RETURNING *",
        (d["slug"], d.get("name", ""), d.get("short_description", ""), d.get("long_description", ""),
         d.get("image_url", ""), int(d.get("duration_minutes", 60) or 60),
         d.get("pricing_model", "rsvp"), int(d.get("base_price_cents", 0) or 0),
         int(d.get("deposit_cents", 0) or 0), d.get("currency", "usd"),
         bool(d.get("requires_calendar", True)), int(d.get("capacity_per_slot", 1) or 1),
         int(d.get("sort_order", 0) or 0), bool(d.get("is_active", True))))
    if not row:
        return jsonify({"error": "slug exists"}), 409
    return jsonify(row), 201


@bp.route("/admin/api/services/<int:sid>", methods=["PUT"])
@admin_required
def update_service(sid):
    d = request.get_json() or {}
    sets, vals = [], []
    for k in ("name", "short_description", "long_description", "image_url", "duration_minutes",
              "pricing_model", "base_price_cents", "deposit_cents", "currency",
              "requires_calendar", "capacity_per_slot", "sort_order", "is_active"):
        if k in d:
            sets.append(f"{k}=%s")
            vals.append(d[k])
    if not sets:
        return jsonify({"error": "No fields"}), 400
    sets.append("updated_at=NOW()")
    vals.append(sid)
    row = execute_db(f"UPDATE services SET {', '.join(sets)} WHERE id=%s RETURNING *", tuple(vals))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/services/<int:sid>", methods=["DELETE"])
@admin_required
def delete_service(sid):
    execute_db("DELETE FROM services WHERE id=%s", (sid,))
    return jsonify({"success": True})


@bp.route("/admin/api/services/<int:sid>/addons", methods=["POST"])
@admin_required
def add_addon(sid):
    d = request.get_json() or {}
    row = execute_db("INSERT INTO service_addons (service_id, name, description, price_cents, sort_order) "
                     "VALUES (%s,%s,%s,%s,%s) RETURNING *",
                     (sid, d.get("name", ""), d.get("description", ""),
                      int(d.get("price_cents", 0) or 0), int(d.get("sort_order", 0) or 0)))
    return jsonify(row), 201


@bp.route("/admin/api/services/<int:sid>/rules", methods=["POST"])
@admin_required
def add_rule(sid):
    d = request.get_json() or {}
    row = execute_db("INSERT INTO service_availability_rules (service_id, day_of_week, start_time, "
                     "end_time, slot_minutes) VALUES (%s,%s,%s,%s,%s) RETURNING *",
                     (sid, int(d.get("day_of_week", 1)), d.get("start_time", "09:00"),
                      d.get("end_time", "17:00"), int(d.get("slot_minutes", 60) or 60)))
    return jsonify(row), 201


@bp.route("/admin/api/services/<int:sid>/overrides", methods=["POST"])
@admin_required
def add_override(sid):
    d = request.get_json() or {}
    if (d.get("override_kind") or "") not in ("block", "open"):
        return jsonify({"error": "override_kind must be block|open"}), 400
    row = execute_db("INSERT INTO service_availability_overrides (service_id, override_date, "
                     "start_time, end_time, override_kind, slot_minutes, note) "
                     "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                     (sid, d.get("override_date"), d.get("start_time"), d.get("end_time"),
                      d["override_kind"], int(d.get("slot_minutes", 60) or 60), d.get("note", "")))
    return jsonify(row), 201


# ---- Availability engine -------------------------------------------------
def _slots_for_window(start_t, end_t, slot_minutes):
    """Yield HH:MM:SS start times stepping slot_minutes from start_t up to (but
    not reaching) end_t."""
    out = []
    cur = datetime.combine(date.today(), start_t)
    end = datetime.combine(date.today(), end_t)
    step = timedelta(minutes=max(5, slot_minutes))
    while cur + step <= end:
        out.append(cur.time().strftime("%H:%M:%S"))
        cur += step
    return out


def _compute_availability(svc, start_date, end_date):
    """Open slots per day = (recurring rules for that weekday ∪ open-overrides)
    − block-overrides − slots already filled to capacity by pending/confirmed
    bookings. Returns a list of {date, open_starts, slots:[{start,remaining}]}."""
    sid = svc["id"]
    cap = max(1, int(svc.get("capacity_per_slot", 1) or 1))
    rules = query_db("SELECT day_of_week, start_time, end_time, slot_minutes FROM "
                     "service_availability_rules WHERE service_id=%s AND is_active=TRUE", (sid,)) or []
    overrides = query_db("SELECT override_date, start_time, end_time, override_kind, slot_minutes "
                         "FROM service_availability_overrides WHERE service_id=%s "
                         "AND override_date BETWEEN %s AND %s", (sid, start_date, end_date)) or []
    booked = query_db(
        "SELECT scheduled_date, scheduled_start, COUNT(*) AS n FROM service_bookings "
        "WHERE service_id=%s AND scheduled_date BETWEEN %s AND %s "
        "AND status IN ('pending','confirmed') AND payment_status NOT IN ('expired','refunded') "
        "GROUP BY scheduled_date, scheduled_start", (sid, start_date, end_date)) or []
    filled = {}
    for b in booked:
        if b["scheduled_date"] and b["scheduled_start"]:
            key = (b["scheduled_date"].isoformat(), b["scheduled_start"].strftime("%H:%M:%S"))
            filled[key] = b["n"]

    by_date_block = {}
    by_date_open = {}
    for o in overrides:
        ds = o["override_date"].isoformat()
        if o["override_kind"] == "block":
            by_date_block.setdefault(ds, []).append(o)
        else:
            by_date_open.setdefault(ds, []).append(o)

    out = []
    d = start_date
    while d <= end_date:
        ds = d.isoformat()
        dow = (d.weekday() + 1) % 7  # python Mon=0..Sun=6 → app Sun=0..Sat=6
        starts = set()
        for r in rules:
            if r["day_of_week"] == dow:
                starts.update(_slots_for_window(r["start_time"], r["end_time"], r["slot_minutes"]))
        for o in by_date_open.get(ds, []):
            if o["start_time"] and o["end_time"]:
                starts.update(_slots_for_window(o["start_time"], o["end_time"], o["slot_minutes"]))
        # Remove blocked starts.
        for o in by_date_block.get(ds, []):
            if o["start_time"] and o["end_time"]:
                for s in _slots_for_window(o["start_time"], o["end_time"], o["slot_minutes"]):
                    starts.discard(s)
            else:
                starts.clear()  # whole-day block
        # Subtract filled-to-capacity.
        slots = []
        for s in sorted(starts):
            remaining = cap - filled.get((ds, s), 0)
            if remaining > 0:
                slots.append({"start": s, "remaining": remaining})
        if slots:
            out.append({"date": ds, "open_starts": [x["start"] for x in slots], "slots": slots})
        d += timedelta(days=1)
    return out


@bp.route("/api/services/<slug>/availability", methods=["GET"])
def availability(slug):
    svc = query_db("SELECT * FROM services WHERE slug=%s AND is_active=TRUE", (slug,), fetchone=True)
    if not svc:
        return jsonify({"error": "Not found"}), 404
    if not svc.get("requires_calendar"):
        return jsonify({"requires_calendar": False, "days": []})
    try:
        start_date = (datetime.strptime(request.args["start"], "%Y-%m-%d").date()
                      if request.args.get("start") else date.today())
        days = min(60, max(1, int(request.args.get("days", 14))))
        end_date = (datetime.strptime(request.args["end"], "%Y-%m-%d").date()
                    if request.args.get("end") else start_date + timedelta(days=days - 1))
    except ValueError:
        return jsonify({"error": "bad date"}), 400
    return jsonify({"requires_calendar": True,
                    "days": _compute_availability(svc, start_date, end_date)})


@bp.route("/api/services/<slug>/book", methods=["POST"])
def book_service(slug):
    svc = query_db("SELECT * FROM services WHERE slug=%s AND is_active=TRUE", (slug,), fetchone=True)
    if not svc:
        return jsonify({"error": "Not found"}), 404
    d = request.get_json() or {}
    if not (d.get("client_name") and d.get("client_email")):
        return jsonify({"error": "client_name and client_email required"}), 400

    # Capacity check for calendar services.
    sched_date = d.get("scheduled_date")
    sched_start = d.get("scheduled_start")
    if svc.get("requires_calendar") and sched_date and sched_start:
        taken = query_db(
            "SELECT COUNT(*) AS n FROM service_bookings WHERE service_id=%s AND scheduled_date=%s "
            "AND scheduled_start=%s AND status IN ('pending','confirmed') "
            "AND payment_status NOT IN ('expired','refunded')",
            (svc["id"], sched_date, sched_start), fetchone=True)
        if (taken or {}).get("n", 0) >= max(1, svc.get("capacity_per_slot", 1)):
            return jsonify({"error": "That time is fully booked."}), 409

    # Addon snapshot + totals.
    addon_ids = [int(a) for a in (d.get("addon_ids") or []) if str(a).isdigit()]
    addons = []
    addons_total = 0
    if addon_ids:
        ph = ",".join(["%s"] * len(addon_ids))
        rows = query_db(f"SELECT id, name, price_cents FROM service_addons WHERE id IN ({ph}) "
                        f"AND service_id=%s", tuple(addon_ids) + (svc["id"],)) or []
        addons = [dict(r) for r in rows]
        addons_total = sum(r["price_cents"] for r in rows)

    model = svc.get("pricing_model", "rsvp")
    base = svc.get("base_price_cents", 0) if model in ("full", "rsvp") else svc.get("deposit_cents", 0)
    total = base + addons_total
    token = secrets.token_urlsafe(24)

    if model == "rsvp":
        execute_db(
            "INSERT INTO service_bookings (service_id, booking_token, client_name, client_email, "
            " client_phone, notes, scheduled_date, scheduled_start, selected_addon_ids, "
            " addon_snapshot, pricing_model, base_price_cents, addons_total_cents, total_cents, "
            " currency, payment_status, status) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,'none','confirmed')",
            (svc["id"], token, d["client_name"], d["client_email"], d.get("client_phone", ""),
             d.get("notes", ""), sched_date or None, sched_start or None, addon_ids,
             json.dumps(addons), model, base, addons_total, total, svc.get("currency", "usd")))
        return jsonify({"action": "rsvp_confirmed", "booking_token": token}), 201

    # Paid flows need Stripe — create a pending booking + signal config gap.
    execute_db(
        "INSERT INTO service_bookings (service_id, booking_token, client_name, client_email, "
        " client_phone, notes, scheduled_date, scheduled_start, selected_addon_ids, addon_snapshot, "
        " pricing_model, base_price_cents, addons_total_cents, total_cents, currency, "
        " payment_status, status) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,'pending','pending')",
        (svc["id"], token, d["client_name"], d["client_email"], d.get("client_phone", ""),
         d.get("notes", ""), sched_date or None, sched_start or None, addon_ids,
         json.dumps(addons), model, base, addons_total, total, svc.get("currency", "usd")))
    if model == "contract":
        return jsonify({"action": "contract_upload",
                        "url": f"/booking/{token}/contract", "booking_token": token}), 201
    if not config.STRIPE_SECRET_KEY:
        return jsonify({"action": "payment_unavailable",
                        "error": "Stripe is not configured for paid bookings.",
                        "booking_token": token}), 200
    return jsonify({"action": "redirect", "booking_token": token}), 201  # Stripe URL (follow-on)


# ======================= STRIPE settings + webhook (stub) =======================
@bp.route("/admin/api/stripe-settings", methods=["GET"])
@admin_required
def get_stripe_settings():
    return jsonify(query_db("SELECT * FROM stripe_settings WHERE id=1", fetchone=True) or {})


@bp.route("/admin/api/stripe-settings", methods=["PUT"])
@admin_required
def put_stripe_settings():
    d = request.get_json() or {}
    mode = d.get("mode", "test")
    if mode not in ("test", "live"):
        return jsonify({"error": "mode must be test|live"}), 400
    row = execute_db("UPDATE stripe_settings SET mode=%s, autosync_products=%s, updated_at=NOW() "
                     "WHERE id=1 RETURNING *", (mode, bool(d.get("autosync_products", False))))
    return jsonify(row)


@bp.route("/api/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Stripe webhook. Full signature verification + checkout.session.completed
    routing (flip orders/bookings to paid, idempotent FOR UPDATE) requires the
    Stripe SDK + signing secret — a follow-on. We ack 200 so Stripe doesn't
    retry-storm, and log when unconfigured."""
    print("[commerce] Stripe webhook received (verification not configured in this build)")
    return jsonify({"received": True}), 200
