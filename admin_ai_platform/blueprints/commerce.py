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
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from flask import Blueprint, request, jsonify

from .. import config
from ..db import query_db, execute_db, get_db
from ..auth import admin_required
from ..reused import stripe_client
from ..reused_di import stripe_settings, stripe_sync

bp = Blueprint("commerce", __name__)


# ======================= Stripe helpers =======================
def _public_base_url():
    """Origin for building Stripe success/cancel return URLs."""
    return (config.PUBLIC_BASE_URL or request.host_url.rstrip("/")).rstrip("/")


def _get_stripe():
    """Return (stripe_module, None) when usable, else (None, (json, status))
    so route handlers can `s, err = _get_stripe(); if err: return err`."""
    try:
        return stripe_client.get_stripe(), None
    except Exception as e:
        return None, (jsonify({"error": "stripe_unavailable", "detail": str(e)[:200]}), 503)


@contextmanager
def _locked_tx():
    """A real transaction (autocommit off) for SELECT ... FOR UPDATE + UPDATE so
    a webhook flip can't race a concurrent reader. Commits on success, rolls back
    on error, and always returns the connection to the pool."""
    conn = get_db()
    try:
        conn.autocommit = False
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
    finally:
        try:
            conn.autocommit = True
        except Exception:
            pass
        conn.close()


def _maybe_sync_product(local_id):
    """Mirror a product into Stripe when autosync is on. Fail-open: a sync error
    never breaks the local CRUD response (it's recorded on the mapping row)."""
    try:
        if stripe_settings.get_settings().get("autosync_products"):
            stripe_sync.sync_product(local_id)
    except Exception as e:
        print(f"[commerce] autosync skipped for product {local_id}: {e}")


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
    _maybe_sync_product(row["id"])
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
    _maybe_sync_product(pid)
    return jsonify(row)


@bp.route("/admin/api/products/<int:pid>", methods=["DELETE"])
@admin_required
def delete_product(pid):
    # Archive the Stripe product(s) BEFORE the local row (and its mapping rows,
    # which cascade) are deleted. Fail-open: a Stripe error must not block delete.
    try:
        stripe_sync.archive_product(pid)
    except Exception as e:
        print(f"[commerce] stripe archive skipped for product {pid}: {e}")
    execute_db("DELETE FROM products WHERE id=%s", (pid,))
    return jsonify({"success": True})


@bp.route("/admin/api/orders", methods=["GET"])
@admin_required
def admin_orders():
    return jsonify({"orders": query_db("SELECT * FROM orders ORDER BY id DESC LIMIT 200") or []})


# ----- product checkout (public) ----------------------------------------
def _upsert_customer(email, name):
    """Find-or-create a customer by email; refresh the name when provided.
    Returns the customer id or None when no email was given."""
    email = (email or "").strip().lower()
    if not email:
        return None
    row = execute_db(
        "INSERT INTO customers (email, name) VALUES (%s,%s) "
        "ON CONFLICT (email) DO UPDATE SET name=COALESCE(NULLIF(EXCLUDED.name,''), customers.name) "
        "RETURNING id", (email, (name or "").strip()))
    return row["id"] if row else None


@bp.route("/api/checkout/create-payment-intent", methods=["POST"])
def create_checkout():
    """Create a Stripe Checkout Session for a product cart and a local ``pending``
    order. Body: ``{items:[{slug, quantity}], customer_email, customer_name}``.
    Returns ``{order_number, checkout_url}``. The webhook flips the order to
    ``paid`` on ``checkout.session.completed``."""
    d = request.get_json() or {}
    items = d.get("items") or []
    if not isinstance(items, list) or not items:
        return jsonify({"error": "items required"}), 400

    # Resolve products + build line items + totals from server-side prices (never
    # trust client-supplied amounts).
    line_items, order_items, subtotal = [], [], 0
    currency = "usd"
    for it in items:
        slug = (it.get("slug") or "").strip()
        qty = max(1, int(it.get("quantity", 1) or 1))
        p = query_db("SELECT id, name, price_cents, currency, stock, track_inventory "
                     "FROM products WHERE slug=%s AND active=TRUE", (slug,), fetchone=True)
        if not p:
            return jsonify({"error": f"unknown product: {slug}"}), 400
        if p.get("track_inventory") and int(p.get("stock") or 0) < qty:
            return jsonify({"error": f"insufficient stock for {slug}"}), 409
        currency = (p.get("currency") or "usd").lower()
        subtotal += p["price_cents"] * qty
        order_items.append((p["id"], p["name"], p["price_cents"], qty))
        line_items.append({
            "price_data": {"currency": currency,
                           "product_data": {"name": p["name"]},
                           "unit_amount": p["price_cents"]},
            "quantity": qty})

    s, err = _get_stripe()
    if err:
        return err

    order_number = "ORD-" + secrets.token_hex(6).upper()
    cust_id = _upsert_customer(d.get("customer_email"), d.get("customer_name"))
    order = execute_db(
        "INSERT INTO orders (order_number, customer_id, customer_email, customer_name, "
        " status, subtotal_cents, total_cents, currency) "
        "VALUES (%s,%s,%s,%s,'pending',%s,%s,%s) RETURNING id",
        (order_number, cust_id, (d.get("customer_email") or "").strip(),
         (d.get("customer_name") or "").strip(), subtotal, subtotal, currency.upper()))
    for pid, pname, unit, qty in order_items:
        execute_db("INSERT INTO order_items (order_id, product_id, product_name, "
                   "unit_price_cents, quantity) VALUES (%s,%s,%s,%s,%s)",
                   (order["id"], pid, pname, unit, qty))

    base = _public_base_url()
    try:
        session = s.checkout.Session.create(
            mode="payment", line_items=line_items,
            customer_email=(d.get("customer_email") or "").strip() or None,
            success_url=f"{base}/api/orders/{order_number}?paid=1",
            cancel_url=f"{base}/api/orders/{order_number}?cancelled=1",
            metadata={"kind": "order", "order_number": order_number})
    except Exception as e:
        execute_db("UPDATE orders SET status='failed', notes=%s WHERE id=%s",
                   (str(e)[:500], order["id"]))
        return jsonify({"error": "stripe_checkout_failed", "detail": str(e)[:200]}), 502
    execute_db("UPDATE orders SET stripe_payment_intent_id=%s WHERE id=%s",
               (session.get("id", ""), order["id"]))
    return jsonify({"order_number": order_number, "checkout_url": session.get("url"),
                    "session_id": session.get("id")}), 201


@bp.route("/api/orders/<order_number>", methods=["GET"])
def public_order(order_number):
    """Public order status lookup by order number (no PII beyond what the buyer
    already submitted; used by the success page)."""
    o = query_db("SELECT order_number, status, total_cents, currency, paid_at "
                 "FROM orders WHERE order_number=%s", (order_number,), fetchone=True)
    if not o:
        return jsonify({"error": "Not found"}), 404
    o["items"] = query_db("SELECT product_name, unit_price_cents, quantity FROM order_items "
                          "WHERE order_id=(SELECT id FROM orders WHERE order_number=%s)",
                          (order_number,)) or []
    return jsonify(o)


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

    # Deposit/full → real Stripe Checkout. The webhook flips the booking to
    # confirmed/paid on checkout.session.completed (metadata.kind == 'booking').
    s, err = _get_stripe()
    if err:
        return jsonify({"action": "payment_unavailable",
                        "error": "Stripe is not configured for paid bookings.",
                        "booking_token": token}), 200
    base = _public_base_url()
    label = ("Deposit" if model == "deposit" else "Booking") + f" — {svc.get('name') or slug}"
    try:
        session = s.checkout.Session.create(
            mode="payment",
            line_items=[{"price_data": {"currency": svc.get("currency", "usd"),
                                        "product_data": {"name": label},
                                        "unit_amount": total},
                         "quantity": 1}],
            customer_email=d["client_email"],
            success_url=f"{base}/api/services/{slug}/booking/{token}?paid=1",
            cancel_url=f"{base}/api/services/{slug}/booking/{token}?cancelled=1",
            metadata={"kind": "booking", "booking_token": token})
    except Exception as e:
        return jsonify({"action": "payment_unavailable",
                        "error": f"Stripe checkout failed: {str(e)[:200]}",
                        "booking_token": token}), 200
    execute_db("UPDATE service_bookings SET stripe_session_id=%s WHERE booking_token=%s",
               (session.get("id", ""), token))
    return jsonify({"action": "redirect", "checkout_url": session.get("url"),
                    "booking_token": token}), 201


# ----- booking status (public) ------------------------------------------
@bp.route("/api/services/<slug>/booking/<token>", methods=["GET"])
def public_booking(slug, token):
    b = query_db("SELECT booking_token, status, payment_status, total_cents, currency, "
                 "scheduled_date, scheduled_start FROM service_bookings WHERE booking_token=%s",
                 (token,), fetchone=True)
    if not b:
        return jsonify({"error": "Not found"}), 404
    return jsonify(b)


# ======================= STRIPE settings + sync + webhook =======================
@bp.route("/admin/api/stripe-settings", methods=["GET"])
@admin_required
def get_stripe_settings():
    """Settings + (secret-free) key-presence snapshot for the admin console."""
    s = stripe_settings.get_settings()
    s["keys_present"] = stripe_client.detect_keys_present()
    s["active_key_kind"] = stripe_client.detect_active_key_kind()
    s["publishable_key"] = stripe_client.get_publishable_key()
    return jsonify(s)


@bp.route("/admin/api/stripe-settings", methods=["PUT"])
@admin_required
def put_stripe_settings():
    d = request.get_json() or {}
    mode = d.get("mode", "test")
    if mode not in ("test", "live"):
        return jsonify({"error": "mode must be test|live"}), 400
    try:
        stripe_settings.set_mode(mode)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if "autosync_products" in d:
        stripe_settings.set_autosync(bool(d.get("autosync_products")))
    stripe_client.invalidate_cache()   # a mode flip must re-resolve keys
    return jsonify(stripe_settings.get_settings())


@bp.route("/admin/api/stripe/health", methods=["POST"])
@admin_required
def stripe_health():
    """Probe the active-mode key with a cheap Stripe call; record the result."""
    try:
        s = stripe_client.get_stripe()
        s.Balance.retrieve()
        stripe_settings.record_health(True, "")
        return jsonify({"ok": True})
    except Exception as e:
        stripe_settings.record_health(False, str(e)[:500])
        return jsonify({"ok": False, "error": str(e)[:200]}), 200


@bp.route("/admin/api/stripe/sync-status", methods=["GET"])
@admin_required
def stripe_sync_status():
    return jsonify(stripe_sync.get_sync_status_rows())


@bp.route("/admin/api/stripe/backfill", methods=["POST"])
@admin_required
def stripe_backfill():
    return jsonify(stripe_sync.backfill_all())


@bp.route("/admin/api/products/<int:pid>/sync", methods=["POST"])
@admin_required
def stripe_sync_one(pid):
    return jsonify(stripe_sync.sync_product(pid))


# ----- orders admin: detail / status / refund ---------------------------
@bp.route("/admin/api/orders/<int:oid>", methods=["GET"])
@admin_required
def admin_order_detail(oid):
    o = query_db("SELECT * FROM orders WHERE id=%s", (oid,), fetchone=True)
    if not o:
        return jsonify({"error": "Not found"}), 404
    o["items"] = query_db("SELECT * FROM order_items WHERE order_id=%s", (oid,)) or []
    return jsonify(o)


_ORDER_STATUSES = ("pending", "paid", "fulfilled", "cancelled", "refunded",
                   "partially_refunded", "failed")


@bp.route("/admin/api/orders/<int:oid>/status", methods=["PUT"])
@admin_required
def admin_order_status(oid):
    d = request.get_json() or {}
    st = d.get("status", "")
    if st not in _ORDER_STATUSES:
        return jsonify({"error": f"status must be one of {_ORDER_STATUSES}"}), 400
    row = execute_db("UPDATE orders SET status=%s WHERE id=%s RETURNING *", (st, oid))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/orders/<int:oid>/refund", methods=["POST"])
@admin_required
def admin_order_refund(oid):
    """Refund a paid order via Stripe (full or partial ``amount_cents``).

    Hardened against the two ways a naive refund leaks money: (1) the order row
    is locked FOR UPDATE and its refundable state re-checked *inside* the txn so
    two concurrent refund clicks can't both call Stripe (TOCTOU); (2) the amount
    is validated against the remaining refundable balance so an over-refund or a
    zero/negative amount is rejected before any Stripe call. A deterministic
    idempotency key makes a retried request a no-op at Stripe too."""
    d = request.get_json() or {}
    s, err = _get_stripe()
    if err:
        return err

    # Phase 1: claim the order under a row lock, compute the refund amount, and
    # provisionally mark it so a concurrent request sees the new state. We do the
    # Stripe call OUTSIDE the lock (network I/O under a row lock is an
    # availability foot-gun), guarded by a 'refunding' marker we set here.
    try:
        with _locked_tx() as cur:
            cur.execute("SELECT * FROM orders WHERE id=%s FOR UPDATE", (oid,))
            o = cur.fetchone()
            if not o:
                return jsonify({"error": "Not found"}), 404
            if o["status"] not in ("paid", "fulfilled", "partially_refunded"):
                return jsonify({"error": "only paid/fulfilled orders can be refunded"}), 409
            charge = o.get("stripe_charge_id") or ""
            pi = o.get("stripe_payment_intent_id") or ""
            if not (charge or pi):
                return jsonify({"error": "no charge/payment_intent recorded"}), 409
            already = int(o.get("refunded_cents") or 0)
            remaining = int(o["total_cents"]) - already
            if remaining <= 0:
                return jsonify({"error": "nothing left to refund"}), 409
            # Distinguish "omitted" (→ full remaining) from an explicit 0 (which
            # must be rejected, not silently coerced to a full refund).
            amount = int(d["amount_cents"]) if "amount_cents" in d else remaining
            if amount <= 0 or amount > remaining:
                return jsonify({"error": f"amount must be 1..{remaining} cents"}), 400
            # Mark in-flight so a racing request bails (we re-check on commit).
            cur.execute("UPDATE orders SET refunded_cents=refunded_cents+%s WHERE id=%s",
                        (amount, oid))
    except Exception as e:
        return jsonify({"error": "refund_lock_failed", "detail": str(e)[:200]}), 500

    # Phase 2: call Stripe with a deterministic idempotency key (order + running
    # refunded total) so a network retry never double-refunds.
    kwargs = {"amount": amount}
    if charge:
        kwargs["charge"] = charge
    else:
        kwargs["payment_intent"] = pi
    idem = f"refund-{o['order_number']}-{already + amount}"
    try:
        s.Refund.create(idempotency_key=idem, **kwargs)
    except Exception as e:
        # Roll back the provisional increment so the operator can retry.
        execute_db("UPDATE orders SET refunded_cents=GREATEST(0, refunded_cents-%s) WHERE id=%s",
                   (amount, oid))
        return jsonify({"error": "stripe_refund_failed", "detail": str(e)[:200]}), 502

    new_total = already + amount
    new_status = "refunded" if new_total >= int(o["total_cents"]) else "partially_refunded"
    row = execute_db("UPDATE orders SET status=%s WHERE id=%s RETURNING *", (new_status, oid))
    return jsonify(row)


# ----- webhook ----------------------------------------------------------
def _claim_event(event_id, event_type):
    """Atomically record an event id; returns True only the FIRST time it's seen
    (Stripe retries aggressively, so every handler must be idempotent)."""
    try:
        row = execute_db(
            "INSERT INTO stripe_events (event_id, event_type) VALUES (%s,%s) "
            "ON CONFLICT (event_id) DO NOTHING RETURNING event_id", (event_id, event_type))
        return bool(row)
    except Exception as e:
        print(f"[commerce] event claim failed (processing anyway): {e}")
        return True


def _unclaim_event(event_id):
    """Release a claimed event so a Stripe retry re-processes it. Called when the
    handler raised AFTER the claim — otherwise the retry would hit the dedupe
    path and the paid order would be stranded as 'pending'."""
    try:
        execute_db("DELETE FROM stripe_events WHERE event_id=%s", (event_id,))
    except Exception as e:
        print(f"[commerce] event unclaim failed: {e}")


def _handle_checkout_completed(session):
    """Flip the matching order/booking to paid/confirmed under a row lock."""
    md = session.get("metadata") or {}
    kind = md.get("kind")
    pi = session.get("payment_intent") or ""
    if kind == "order":
        onum = md.get("order_number") or ""
        with _locked_tx() as cur:
            cur.execute("SELECT id, status FROM orders WHERE order_number=%s FOR UPDATE", (onum,))
            o = cur.fetchone()
            if o and o["status"] == "pending":
                cur.execute("UPDATE orders SET status='paid', paid_at=NOW(), "
                            "stripe_payment_intent_id=%s WHERE id=%s",
                            (pi or "", o["id"]))
                # Decrement inventory for tracked products in the same txn so a
                # paid order and its stock change commit atomically.
                cur.execute("SELECT product_id, quantity FROM order_items WHERE order_id=%s",
                            (o["id"],))
                for item in cur.fetchall():
                    if item["product_id"]:
                        cur.execute("UPDATE products SET stock = GREATEST(0, stock - %s) "
                                    "WHERE id=%s AND track_inventory=TRUE",
                                    (item["quantity"], item["product_id"]))
    elif kind == "booking":
        token = md.get("booking_token") or ""
        amount = int(session.get("amount_total") or 0)
        with _locked_tx() as cur:
            cur.execute("SELECT id, payment_status FROM service_bookings "
                        "WHERE booking_token=%s FOR UPDATE", (token,))
            b = cur.fetchone()
            if b and b["payment_status"] != "paid":
                cur.execute("UPDATE service_bookings SET payment_status='paid', "
                            "status='confirmed', amount_paid_cents=%s WHERE id=%s",
                            (amount, b["id"]))


def _handle_checkout_expired(session):
    """Mark abandoned checkouts so they free their slot / show as cancelled."""
    md = session.get("metadata") or {}
    kind = md.get("kind")
    if kind == "order":
        execute_db("UPDATE orders SET status='cancelled' WHERE order_number=%s AND status='pending'",
                   (md.get("order_number") or "",))
    elif kind == "booking":
        execute_db("UPDATE service_bookings SET payment_status='expired', status='cancelled' "
                   "WHERE booking_token=%s AND payment_status='pending'",
                   (md.get("booking_token") or "",))


@bp.route("/api/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Verify the Stripe signature, dedupe by event id, then route
    checkout.session.{completed,expired}. Returns 400 on a bad/again-unverifiable
    signature; 200 once accepted (so Stripe stops retrying)."""
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")
    secret = stripe_client.get_webhook_secret()
    if not secret:
        # No signing secret configured — we cannot trust the body, so refuse
        # rather than act on an unauthenticated event.
        return jsonify({"error": "webhook not configured"}), 503
    if stripe_client.stripe is None:
        return jsonify({"error": "stripe sdk missing"}), 503
    try:
        event = stripe_client.stripe.Webhook.construct_event(payload, sig, secret)
    except Exception as e:
        return jsonify({"error": "signature verification failed", "detail": str(e)[:120]}), 400

    eid = event.get("id") or ""
    etype = event.get("type") or ""
    if eid and not _claim_event(eid, etype):
        return jsonify({"received": True, "duplicate": True}), 200

    obj = (event.get("data") or {}).get("object") or {}
    try:
        if etype == "checkout.session.completed":
            _handle_checkout_completed(obj)
        elif etype == "checkout.session.expired":
            _handle_checkout_expired(obj)
    except Exception as e:
        # Release the claim so Stripe's retry re-processes — otherwise a paid
        # order whose flip failed here would be permanently stranded 'pending'.
        if eid:
            _unclaim_event(eid)
        print(f"[commerce] webhook handler error for {etype}: {e}")
        return jsonify({"error": "handler error"}), 500
    return jsonify({"received": True}), 200
