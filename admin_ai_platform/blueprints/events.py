"""
admin_ai_platform.blueprints.events
====================================

Events + ticketing (M12). Event listings with RSVPs in three price modes:

  * **free**     — RSVP confirmed immediately.
  * **paid**     — ``price_cents`` per guest; RSVP goes ``pending`` and the
    caller is redirected to a Stripe Checkout Session (M11). The webhook flips
    it to paid/confirmed.
  * **donation** — donor-chosen ``amount_cents`` at RSVP time; same Stripe flow.

**Capacity is reserved at RSVP time** (not at payment time) so a paid RSVP can't
be double-sold while the buyer is on the Stripe page: the reservation counts
both ``confirmed`` and ``pending`` (non-expired) guests, taken under a
``SELECT ... FOR UPDATE`` lock on the event row. An expired/cancelled checkout
(webhook ``checkout.session.expired``) frees the held seats.

  * public: ``GET /api/events``, ``GET /api/events/<slug>``,
    ``POST /api/events/<slug>/rsvp``, ``GET /api/events/<slug>/rsvp/<token>``
  * admin: events CRUD, RSVP list, delete RSVP
"""

from __future__ import annotations

import secrets

from flask import Blueprint, request, jsonify

from ..db import query_db, execute_db
from ..auth import admin_required
from .commerce import _get_stripe, _public_base_url, _locked_tx

bp = Blueprint("events", __name__)

_PRICE_MODES = ("free", "paid", "donation")
# RSVPs that still hold a seat (anything not expired/cancelled).
_HELD = "('confirmed','pending')"


# ======================= public reads =======================
@bp.route("/api/events", methods=["GET"])
def public_events():
    return jsonify(query_db(
        "SELECT slug, title, description, start_at, end_at, location, capacity, "
        "price_mode, price_cents, currency, image_url FROM events "
        "WHERE status='published' ORDER BY sort_order, start_at NULLS LAST, id") or [])


def _reserved_guests(event_id, cur=None):
    """Seats currently held (confirmed + pending, non-expired). Uses the passed
    cursor when inside a locked txn, else a plain read."""
    sql = ("SELECT COALESCE(SUM(guests),0) AS n FROM event_rsvps "
           f"WHERE event_id=%s AND status IN {_HELD} "
           "AND payment_status NOT IN ('expired','refunded')")
    if cur is not None:
        cur.execute(sql, (event_id,))
        return int(cur.fetchone()["n"])
    return int((query_db(sql, (event_id,), fetchone=True) or {}).get("n", 0))


@bp.route("/api/events/<slug>", methods=["GET"])
def public_event(slug):
    e = query_db("SELECT * FROM events WHERE slug=%s AND status='published'",
                 (slug,), fetchone=True)
    if not e:
        return jsonify({"error": "Not found"}), 404
    reserved = _reserved_guests(e["id"])
    e["seats_taken"] = reserved
    e["seats_remaining"] = (max(0, e["capacity"] - reserved) if e["capacity"] else None)
    return jsonify(e)


@bp.route("/api/events/<slug>/rsvp", methods=["POST"])
def rsvp(slug):
    """Create an RSVP. Free → confirmed immediately. Paid/donation → pending +
    Stripe Checkout redirect, with the seats reserved under a row lock so two
    concurrent RSVPs can't oversell the last seats."""
    e = query_db("SELECT * FROM events WHERE slug=%s AND status='published'",
                 (slug,), fetchone=True)
    if not e:
        return jsonify({"error": "Not found"}), 404
    d = request.get_json() or {}
    name = (d.get("name") or "").strip()
    email = (d.get("email") or "").strip()
    if not (name and email):
        return jsonify({"error": "name and email required"}), 400
    guests = max(1, int(d.get("guests", 1) or 1))
    mode = e["price_mode"]
    currency = e.get("currency", "usd")

    # Amount per mode (server-derived; donation accepts a client amount >= 1).
    if mode == "paid":
        amount = e["price_cents"] * guests
    elif mode == "donation":
        amount = int(d.get("amount_cents", 0) or 0)
        if amount < 1:
            return jsonify({"error": "donation amount_cents required (min 1)"}), 400
    else:
        amount = 0

    token = secrets.token_urlsafe(24)
    paid_flow = mode in ("paid", "donation")
    pay_status = "pending" if paid_flow else "none"
    rsvp_status = "pending" if paid_flow else "confirmed"

    # Reserve seats + insert under a lock so the capacity check and the insert
    # are atomic (no double-sell on the final seats).
    try:
        with _locked_tx() as cur:
            cur.execute("SELECT id, capacity FROM events WHERE id=%s FOR UPDATE", (e["id"],))
            locked = cur.fetchone()
            cap = int(locked["capacity"] or 0)
            if cap:
                reserved = _reserved_guests(e["id"], cur)
                if reserved + guests > cap:
                    return jsonify({"error": "sold_out",
                                    "seats_remaining": max(0, cap - reserved)}), 409
            cur.execute(
                "INSERT INTO event_rsvps (event_id, rsvp_token, name, email, phone, guests, "
                " notes, amount_cents, currency, payment_status, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (e["id"], token, name, email, d.get("phone", ""), guests, d.get("notes", ""),
                 amount, currency, pay_status, rsvp_status))
    except Exception as ex:
        return jsonify({"error": "rsvp_failed", "detail": str(ex)[:200]}), 500

    if not paid_flow:
        return jsonify({"action": "rsvp_confirmed", "rsvp_token": token}), 201

    # Paid/donation → Stripe Checkout. If Stripe isn't configured the seat is
    # already held as pending; we surface that so the operator can follow up.
    s, err = _get_stripe()
    if err:
        return jsonify({"action": "payment_unavailable",
                        "error": "Stripe is not configured for paid events.",
                        "rsvp_token": token}), 200
    base = _public_base_url()
    label = f"{'Donation' if mode == 'donation' else 'Tickets'} — {e.get('title') or slug}"
    try:
        session = s.checkout.Session.create(
            mode="payment",
            line_items=[{"price_data": {"currency": currency,
                                        "product_data": {"name": label},
                                        "unit_amount": amount},
                         "quantity": 1}],
            customer_email=email,
            success_url=f"{base}/api/events/{slug}/rsvp/{token}?paid=1",
            cancel_url=f"{base}/api/events/{slug}/rsvp/{token}?cancelled=1",
            metadata={"kind": "event_rsvp", "rsvp_token": token})
    except Exception as ex:
        return jsonify({"action": "payment_unavailable",
                        "error": f"Stripe checkout failed: {str(ex)[:200]}",
                        "rsvp_token": token}), 200
    execute_db("UPDATE event_rsvps SET stripe_session_id=%s WHERE rsvp_token=%s",
               (session.get("id", ""), token))
    return jsonify({"action": "redirect", "checkout_url": session.get("url"),
                    "rsvp_token": token}), 201


@bp.route("/api/events/<slug>/rsvp/<token>", methods=["GET"])
def rsvp_status(slug, token):
    r = query_db("SELECT rsvp_token, status, payment_status, guests, amount_cents, currency "
                 "FROM event_rsvps WHERE rsvp_token=%s", (token,), fetchone=True)
    if not r:
        return jsonify({"error": "Not found"}), 404
    return jsonify(r)


# ======================= admin =======================
_EVENT_FIELDS = ("title", "description", "start_at", "end_at", "location", "capacity",
                 "price_mode", "price_cents", "currency", "image_url", "status", "sort_order")


@bp.route("/admin/api/events", methods=["GET"])
@admin_required
def admin_events():
    return jsonify({"events": query_db("SELECT * FROM events ORDER BY sort_order, id") or []})


@bp.route("/admin/api/events", methods=["POST"])
@admin_required
def create_event():
    d = request.get_json() or {}
    if not (d.get("slug") or "").strip():
        return jsonify({"error": "slug required"}), 400
    if (d.get("price_mode") or "free") not in _PRICE_MODES:
        return jsonify({"error": f"price_mode must be {_PRICE_MODES}"}), 400
    row = execute_db(
        "INSERT INTO events (slug, title, description, start_at, end_at, location, capacity, "
        " price_mode, price_cents, currency, image_url, status, sort_order) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (slug) DO NOTHING RETURNING *",
        (d["slug"], d.get("title", ""), d.get("description", ""), d.get("start_at") or None,
         d.get("end_at") or None, d.get("location", ""), int(d.get("capacity", 0) or 0),
         d.get("price_mode", "free"), int(d.get("price_cents", 0) or 0), d.get("currency", "usd"),
         d.get("image_url", ""), d.get("status", "published"), int(d.get("sort_order", 0) or 0)))
    if not row:
        return jsonify({"error": "slug exists"}), 409
    return jsonify(row), 201


@bp.route("/admin/api/events/<int:eid>", methods=["PUT"])
@admin_required
def update_event(eid):
    d = request.get_json() or {}
    if "price_mode" in d and d["price_mode"] not in _PRICE_MODES:
        return jsonify({"error": f"price_mode must be {_PRICE_MODES}"}), 400
    sets, vals = [], []
    for k in _EVENT_FIELDS:
        if k in d:
            sets.append(f"{k}=%s")
            vals.append(d[k] if d[k] != "" or k not in ("start_at", "end_at") else None)
    if not sets:
        return jsonify({"error": "No fields"}), 400
    sets.append("updated_at=NOW()")
    vals.append(eid)
    row = execute_db(f"UPDATE events SET {', '.join(sets)} WHERE id=%s RETURNING *", tuple(vals))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/events/<int:eid>", methods=["DELETE"])
@admin_required
def delete_event(eid):
    execute_db("DELETE FROM events WHERE id=%s", (eid,))
    return jsonify({"success": True})


@bp.route("/admin/api/events/<int:eid>/rsvps", methods=["GET"])
@admin_required
def list_rsvps(eid):
    return jsonify({"rsvps": query_db(
        "SELECT * FROM event_rsvps WHERE event_id=%s ORDER BY id DESC", (eid,)) or []})


@bp.route("/admin/api/events/rsvps/<int:rid>", methods=["DELETE"])
@admin_required
def delete_rsvp(rid):
    execute_db("DELETE FROM event_rsvps WHERE id=%s", (rid,))
    return jsonify({"success": True})
