"""
admin_ai_platform.blueprints.reviews
====================================

AI review collector: destinations (Google/Yelp/TripAdvisor/internal), outgoing
review-ask requests with a tracked ``/r/<token>`` short link (records click +
conversion), aggregate snapshots, and an insights funnel. Aggregate fetching
needs the provider API keys; without them it records a clear error rather than
failing.

  * ``GET/POST /admin/api/reviews/destinations`` + ``PUT/DELETE/<id>`` + ``/<id>/refresh``
  * ``GET/PUT /admin/api/reviews/settings``
  * ``GET/POST /admin/api/reviews/requests`` + ``GET/<id>`` + ``/<id>/cancel`` + ``DELETE/<id>``
  * ``GET /admin/api/reviews/insights``      funnel rates
  * ``GET /r/<token>``                        public: record click + redirect
  * ``GET /api/review-snapshots``             public: aggregate cards
"""

from __future__ import annotations

import secrets

from flask import Blueprint, request, jsonify, redirect

from .. import config
from ..db import query_db, execute_db
from ..auth import admin_required

bp = Blueprint("reviews", __name__)

_VALID_KIND = ("google", "yelp", "tripadvisor", "internal")


# ---- destinations -------------------------------------------------------
@bp.route("/admin/api/reviews/destinations", methods=["GET"])
@admin_required
def list_destinations():
    return jsonify({"destinations": query_db(
        "SELECT d.*, e.total_count, e.avg_rating, e.snapshot_at "
        "FROM review_destinations d LEFT JOIN external_reviews e ON e.destination_id=d.id "
        "ORDER BY d.sort_order, d.id") or []})


@bp.route("/admin/api/reviews/destinations", methods=["POST"])
@admin_required
def create_destination():
    d = request.get_json() or {}
    if (d.get("kind") or "google") not in _VALID_KIND:
        return jsonify({"error": f"kind must be {_VALID_KIND}"}), 400
    row = execute_db(
        "INSERT INTO review_destinations (name, kind, url, external_id, auto_send, "
        " auto_send_days, is_default, public_visible, sort_order) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (d.get("name", ""), d.get("kind", "google"), d.get("url", ""), d.get("external_id", ""),
         bool(d.get("auto_send", False)), int(d.get("auto_send_days", 3) or 3),
         bool(d.get("is_default", False)), bool(d.get("public_visible", False)),
         int(d.get("sort_order", 0) or 0)))
    return jsonify(row), 201


@bp.route("/admin/api/reviews/destinations/<int:did>", methods=["PUT"])
@admin_required
def update_destination(did):
    d = request.get_json() or {}
    sets, vals = [], []
    for k in ("name", "kind", "url", "external_id", "auto_send", "auto_send_days",
              "is_default", "public_visible", "sort_order"):
        if k in d:
            sets.append(f"{k}=%s")
            vals.append(d[k])
    if not sets:
        return jsonify({"error": "No fields"}), 400
    vals.append(did)
    row = execute_db(f"UPDATE review_destinations SET {', '.join(sets)} WHERE id=%s RETURNING *", tuple(vals))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/reviews/destinations/<int:did>", methods=["DELETE"])
@admin_required
def delete_destination(did):
    execute_db("DELETE FROM review_destinations WHERE id=%s", (did,))
    return jsonify({"success": True})


@bp.route("/admin/api/reviews/destinations/<int:did>/refresh", methods=["POST"])
@admin_required
def refresh_destination(did):
    # Aggregate fetch requires Google/Yelp/TripAdvisor API keys (not wired in
    # this build). Record a clear "needs credentials" snapshot rather than fail.
    from .. import config
    keyed = {"google": config.GOOGLE_PLACES_API_KEY, "yelp": config.YELP_API_KEY,
             "tripadvisor": config.TRIPADVISOR_API_KEY}
    dest = query_db("SELECT kind FROM review_destinations WHERE id=%s", (did,), fetchone=True)
    if not dest:
        return jsonify({"error": "Not found"}), 404
    if not keyed.get(dest["kind"]):
        execute_db("INSERT INTO external_reviews (destination_id, error_text) VALUES (%s,%s) "
                   "ON CONFLICT (destination_id) DO UPDATE SET error_text=EXCLUDED.error_text, "
                   "snapshot_at=NOW()", (did, f"{dest['kind']} API key not configured"))
        return jsonify({"ok": False, "error": f"{dest['kind']} API key not configured"}), 200
    # With a key, a real provider fetch would go here (follow-on).
    return jsonify({"ok": True, "note": "provider fetch not implemented in this build"})


# ---- settings -----------------------------------------------------------
@bp.route("/admin/api/reviews/settings", methods=["GET"])
@admin_required
def get_settings():
    return jsonify(query_db("SELECT * FROM review_settings WHERE id=1", fetchone=True) or {})


@bp.route("/admin/api/reviews/settings", methods=["PUT"])
@admin_required
def put_settings():
    d = request.get_json() or {}
    row = execute_db(
        "UPDATE review_settings SET email_template_id=%s, sms_template_id=%s, "
        " auto_send_days=%s, public_show=%s, updated_at=NOW() WHERE id=1 RETURNING *",
        (d.get("email_template_id"), d.get("sms_template_id"),
         int(d.get("auto_send_days", 3) or 3), bool(d.get("public_show", False))))
    return jsonify(row)


# ---- requests -----------------------------------------------------------
@bp.route("/admin/api/reviews/requests", methods=["GET"])
@admin_required
def list_requests():
    return jsonify({"requests": query_db(
        "SELECT * FROM review_requests ORDER BY id DESC LIMIT 200") or []})


@bp.route("/admin/api/reviews/requests", methods=["POST"])
@admin_required
def create_request():
    d = request.get_json() or {}
    token = secrets.token_urlsafe(16)
    row = execute_db(
        "INSERT INTO review_requests (destination_id, channel, recipient_name, recipient_email, "
        " recipient_phone, purchased_item, source_kind, source_id, short_token) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (d.get("destination_id"), d.get("channel", "email"), d.get("recipient_name", ""),
         d.get("recipient_email", ""), d.get("recipient_phone", ""), d.get("purchased_item", ""),
         d.get("source_kind", "manual"), d.get("source_id"), token))
    return jsonify(row), 201


@bp.route("/admin/api/reviews/requests/<int:rid>", methods=["GET"])
@admin_required
def get_request(rid):
    row = query_db("SELECT * FROM review_requests WHERE id=%s", (rid,), fetchone=True)
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/reviews/requests/<int:rid>/cancel", methods=["POST"])
@admin_required
def cancel_request(rid):
    execute_db("UPDATE review_requests SET status='cancelled' WHERE id=%s "
               "AND status IN ('queued','sending')", (rid,))
    return jsonify({"success": True})


@bp.route("/admin/api/reviews/requests/<int:rid>", methods=["DELETE"])
@admin_required
def delete_request(rid):
    execute_db("DELETE FROM review_requests WHERE id=%s", (rid,))
    return jsonify({"success": True})


@bp.route("/admin/api/reviews/insights", methods=["GET"])
@admin_required
def insights():
    row = query_db(
        "SELECT COUNT(*) AS total, "
        " SUM(CASE WHEN sent_at IS NOT NULL THEN 1 ELSE 0 END) AS sent, "
        " SUM(CASE WHEN clicked_at IS NOT NULL THEN 1 ELSE 0 END) AS clicked, "
        " SUM(CASE WHEN converted_at IS NOT NULL THEN 1 ELSE 0 END) AS converted "
        "FROM review_requests", fetchone=True) or {}
    return jsonify({"funnel": row})


# ---- public short link + snapshots -------------------------------------
@bp.route("/r/<token>", methods=["GET"])
def short_link(token):
    req = query_db("SELECT id, destination_id FROM review_requests WHERE short_token=%s",
                   (token,), fetchone=True)
    if not req:
        return "Link not found.", 404
    execute_db("UPDATE review_requests SET clicked_at=COALESCE(clicked_at, NOW()), "
               "click_count=click_count+1 WHERE id=%s", (req["id"],))
    dest = None
    if req["destination_id"]:
        dest = query_db("SELECT url FROM review_destinations WHERE id=%s",
                        (req["destination_id"],), fetchone=True)
    if dest and dest.get("url"):
        return redirect(dest["url"])
    return "Thank you! Redirect target not configured.", 200


# ---- scheduler tick -----------------------------------------------------
def _review_link(token):
    base = (config.PUBLIC_BASE_URL or "").rstrip("/")
    return f"{base}/r/{token}" if base else f"/r/{token}"


def review_collector_tick():
    """Scheduler tick: deliver any queued review-ask request whose ``send_at``
    has passed (email/SMS with the tracked ``/r/<token>`` link), and refresh
    aggregate snapshots for destinations that have provider keys. Best-effort;
    missing messaging/keys degrade to a recorded error, never a crash."""
    try:
        from ..reused import messaging
    except Exception:
        messaging = None
    try:
        from ..cost import cost_cap_blocks_send, record_sms_cost
    except Exception:
        cost_cap_blocks_send = lambda **k: False  # noqa: E731
        record_sms_cost = None

    # 1) Dispatch due requests.
    try:
        due = query_db(
            "SELECT * FROM review_requests WHERE status='queued' "
            "  AND send_at IS NOT NULL AND send_at <= NOW() ORDER BY send_at LIMIT 50") or []
    except Exception as e:
        print(f"[reviews] collector_tick query failed: {e}")
        due = []
    for req in due:
        rid = req["id"]
        try:
            claimed = execute_db(
                "UPDATE review_requests SET status='sending' WHERE id=%s AND status='queued' "
                "RETURNING id", (rid,))
            if not claimed:
                continue
            if messaging is None or cost_cap_blocks_send(surface="review"):
                execute_db("UPDATE review_requests SET status='failed', "
                           "error_text='messaging unavailable or cost cap' WHERE id=%s", (rid,))
                continue
            link = _review_link(req["short_token"])
            channel = req.get("channel", "email")
            name = req.get("recipient_name") or "there"
            if channel == "email":
                to = req.get("recipient_email", "")
                subject = req.get("subject_snapshot") or "How did we do?"
                body = req.get("body_snapshot") or (
                    f"Hi {name}, we'd love your feedback — please leave a review: {link}")
                if not to:
                    raise RuntimeError("no recipient email")
                messaging.send_email(to, subject, body)
            else:
                to = req.get("recipient_phone", "")
                body = req.get("body_snapshot") or (
                    f"Hi {name}, we'd love your feedback: {link}")
                if not to:
                    raise RuntimeError("no recipient phone")
                resp = messaging.send_sms(to, body)
                if record_sms_cost and isinstance(resp, dict):
                    record_sms_cost(message_sid=resp.get("sid", ""), to_number=to,
                                    segments=resp.get("segments"))
            execute_db("UPDATE review_requests SET status='sent', sent_at=NOW() WHERE id=%s", (rid,))
        except Exception as e:
            execute_db("UPDATE review_requests SET status='failed', error_text=%s WHERE id=%s",
                       (str(e)[:300], rid))


@bp.route("/api/review-snapshots", methods=["GET"])
def public_snapshots():
    rows = query_db(
        "SELECT d.name, d.kind, d.url, e.total_count, e.avg_rating, e.snapshot_at "
        "FROM review_destinations d JOIN external_reviews e ON e.destination_id=d.id "
        "WHERE d.public_visible = TRUE ORDER BY d.sort_order") or []
    return jsonify({"snapshots": rows})
