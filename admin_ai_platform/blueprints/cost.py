"""
admin_ai_platform.blueprints.cost
=================================

Cost transparency dashboard. Reads the three ledgers (api/voice/sms cost events)
and exposes month-to-date spend, a daily series, per-surface and per-model
breakdowns, an editable unit-price table, and the monthly cap config.

  * ``GET   /admin/api/cost/summary``         MTD spend + cap status
  * ``GET   /admin/api/cost/series``          daily totals (last N days)
  * ``GET   /admin/api/cost/by-surface``      spend grouped by surface
  * ``GET   /admin/api/cost/by-model``        spend grouped by provider/model
  * ``GET   /admin/api/cost/prices``          editable unit-price rows
  * ``PATCH /admin/api/cost/prices/<id>``     edit a unit price (never re-prices
                                              already-stamped ledger rows)
  * ``GET/PUT /admin/api/cost/cap``           monthly cap + warn% + behavior

All @admin_required and gated by the ``cost_dashboard`` feature (404 when off).
"""

from __future__ import annotations

from functools import wraps

from flask import Blueprint, request, jsonify

from ..db import query_db, execute_db
from ..auth import admin_required
from ..tenancy import current_tenant_id, tenant_has_feature
from ..cost import compute_mtd_spend, get_tenant_cost_cap

bp = Blueprint("cost", __name__)

_CAP_BEHAVIORS = ("alert_only", "throttle", "strict_block")


def _feature_required(f):
    """404 when the cost_dashboard feature is off for this tenant."""
    @wraps(f)
    def inner(*a, **k):
        if not tenant_has_feature("cost_dashboard"):
            return jsonify({"error": "Not found"}), 404
        return f(*a, **k)
    return inner


@bp.route("/admin/api/cost/summary", methods=["GET"])
@admin_required
@_feature_required
def summary():
    mtd = compute_mtd_spend()
    cap = get_tenant_cost_cap()
    cap_usd = cap.get("monthly_cap_usd")
    pct = None
    if cap_usd:
        try:
            pct = round(mtd["total_usd"] / float(cap_usd) * 100, 1)
        except (TypeError, ZeroDivisionError):
            pct = None
    return jsonify({"mtd": mtd, "cap": cap, "percent_of_cap": pct})


@bp.route("/admin/api/cost/series", methods=["GET"])
@admin_required
@_feature_required
def series():
    days = min(120, max(1, int(request.args.get("days", 30))))
    tid = current_tenant_id()
    rows = query_db(
        "SELECT d::date AS day, "
        " COALESCE((SELECT SUM(cost_usd) FROM api_cost_events "
        "   WHERE tenant_id=%s AND created_at::date = d::date),0) AS chat, "
        " COALESCE((SELECT SUM(cost_usd) FROM voice_cost_events "
        "   WHERE tenant_id=%s AND created_at::date = d::date),0) AS voice, "
        " COALESCE((SELECT SUM(cost_usd) FROM sms_cost_events "
        "   WHERE tenant_id=%s AND created_at::date = d::date),0) AS sms "
        "FROM generate_series(CURRENT_DATE - (%s || ' days')::interval, CURRENT_DATE, '1 day') d "
        "ORDER BY day",
        (tid, tid, tid, days - 1))
    return jsonify({"series": rows or []})


@bp.route("/admin/api/cost/by-surface", methods=["GET"])
@admin_required
@_feature_required
def by_surface():
    tid = current_tenant_id()
    chat = query_db(
        "SELECT surface, COALESCE(SUM(cost_usd),0) AS usd, COUNT(*) AS calls "
        "FROM api_cost_events WHERE tenant_id=%s AND created_at >= DATE_TRUNC('month',NOW()) "
        "GROUP BY surface", (tid,)) or []
    voice = query_db(
        "SELECT surface, COALESCE(SUM(cost_usd),0) AS usd, COUNT(*) AS calls "
        "FROM voice_cost_events WHERE tenant_id=%s AND created_at >= DATE_TRUNC('month',NOW()) "
        "GROUP BY surface", (tid,)) or []
    sms = query_db(
        "SELECT surface, COALESCE(SUM(cost_usd),0) AS usd, COUNT(*) AS calls "
        "FROM sms_cost_events WHERE tenant_id=%s AND created_at >= DATE_TRUNC('month',NOW()) "
        "GROUP BY surface", (tid,)) or []
    return jsonify({"by_surface": (chat + voice + sms)})


@bp.route("/admin/api/cost/by-model", methods=["GET"])
@admin_required
@_feature_required
def by_model():
    tid = current_tenant_id()
    rows = query_db(
        "SELECT provider, model, COALESCE(SUM(cost_usd),0) AS usd, "
        " SUM(prompt_tokens) AS prompt_tokens, SUM(completion_tokens) AS completion_tokens, "
        " COUNT(*) AS calls FROM api_cost_events "
        "WHERE tenant_id=%s AND created_at >= DATE_TRUNC('month',NOW()) "
        "GROUP BY provider, model ORDER BY usd DESC", (tid,))
    return jsonify({"by_model": rows or []})


@bp.route("/admin/api/cost/prices", methods=["GET"])
@admin_required
@_feature_required
def prices():
    rows = query_db("SELECT * FROM model_prices ORDER BY provider, surface, model")
    return jsonify({"prices": rows or []})


@bp.route("/admin/api/cost/prices/<int:row_id>", methods=["PATCH"])
@admin_required
@_feature_required
def patch_price(row_id):
    data = request.get_json() or {}
    cols = ("input_price_per_million_tokens", "output_price_per_million_tokens",
            "tts_price_per_million_chars", "stt_price_per_minute",
            "sms_price_per_segment", "active", "notes")
    sets, vals = [], []
    for c in cols:
        if c in data:
            sets.append(f"{c}=%s")
            vals.append(data[c])
    if not sets:
        return jsonify({"error": "No fields"}), 400
    sets.append("updated_at=NOW()")
    vals.append(row_id)
    row = execute_db(f"UPDATE model_prices SET {', '.join(sets)} WHERE id=%s RETURNING *", tuple(vals))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/cost/cap", methods=["GET"])
@admin_required
@_feature_required
def get_cap():
    return jsonify(get_tenant_cost_cap())


@bp.route("/admin/api/cost/cap", methods=["PUT"])
@admin_required
@_feature_required
def put_cap():
    data = request.get_json() or {}
    behavior = (data.get("cap_behavior") or "alert_only").lower()
    if behavior not in _CAP_BEHAVIORS:
        return jsonify({"error": f"cap_behavior must be one of {_CAP_BEHAVIORS}"}), 400
    tid = current_tenant_id()
    row = execute_db(
        "INSERT INTO tenant_cost_caps (tenant_id, monthly_cap_usd, warn_at_percent, "
        " cap_behavior, alert_email, digest_email, digest_send_hour_utc, updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,NOW()) "
        "ON CONFLICT (tenant_id) DO UPDATE SET "
        " monthly_cap_usd=EXCLUDED.monthly_cap_usd, warn_at_percent=EXCLUDED.warn_at_percent, "
        " cap_behavior=EXCLUDED.cap_behavior, alert_email=EXCLUDED.alert_email, "
        " digest_email=EXCLUDED.digest_email, digest_send_hour_utc=EXCLUDED.digest_send_hour_utc, "
        " updated_at=NOW() RETURNING *",
        (tid, data.get("monthly_cap_usd"), int(data.get("warn_at_percent", 80) or 80),
         behavior, data.get("alert_email", ""), data.get("digest_email", ""),
         int(data.get("digest_send_hour_utc", 9) or 9)))
    return jsonify(row)
