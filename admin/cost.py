"""admin/cost.py - the Cost transparency dashboard API, as a Flask blueprint.

Part of the app.py de-monolith (Track B / task 078, piece #2), mirroring
admin/reporting.py. These eight /admin/api/cost/* routes are the admin-facing
Cost tab: MTD summary + cap status, the spend-over-time series, by-surface and
by-model breakdowns, the editable model_prices table (GET + PATCH), and the
cost-cap config (GET + PUT).

Every route is gated behind the cost_dashboard feature flag via the shared
_cost_feature_required() helper (moved here with the routes) so a tenant without
the entitlement gets a clean 404 - the tab is also hidden in the UI for them
(defense in depth). @admin_required (from core) gates on a logged-in admin.

The cost INFRA these routes call - compute_mtd_spend, get_tenant_cost_cap,
_to_float, _current_period, and the price-cache invalidator _invalidate_price_cache
- lives in core (Track B / task 078, piece #2), so this blueprint imports it
cleanly, never `from app` (which would be circular). The cost-prices PATCH route
busts the in-process price cache by calling _invalidate_price_cache().

URLs keep their absolute /admin/api/cost/* paths, so the route table is unchanged
- only the Flask endpoint name gains a "cost." prefix (admin JS calls these by URL,
not url_for). CSRF / feature-flag enforcement runs in app.py's global before_request
hooks, which apply to blueprint routes too, so nothing extra is needed here.

Registered in app.py via app.register_blueprint(cost_bp), after ai_prompts_bp.
"""
from flask import Blueprint, request, jsonify

from core import (
    query_db,
    execute_db,
    current_tenant_id,
    admin_required,
    tenant_has_feature,
    _to_float,
    _current_period,
    compute_mtd_spend,
    get_tenant_cost_cap,
    _invalidate_price_cache,
)

cost_bp = Blueprint("cost", __name__)


# =============================================================================
# COST DASHBOARD — Admin-facing endpoints for the cost transparency tab.
# Each endpoint is gated behind the cost_dashboard feature flag so tenants
# without the entitlement get a clean 404 (the tab is also hidden in the UI
# for them — defense in depth).
# =============================================================================

def _cost_feature_required():
    """Returns a Flask error response if the cost_dashboard feature is off
    for this tenant, else None. Centralized so every cost endpoint reads
    the same way."""
    if not tenant_has_feature("cost_dashboard"):
        return jsonify({"error": "cost dashboard not enabled"}), 404
    return None


@cost_bp.route("/admin/api/cost/summary", methods=["GET"])
@admin_required
def admin_cost_summary():
    """MTD totals + cap status. The headline numbers shown at the top of
    the Cost tab. Includes both raw spend and the configured cap so the
    UI can render a progress bar without a second round-trip."""
    err = _cost_feature_required()
    if err is not None:
        return err
    spend = compute_mtd_spend()
    cap_row = get_tenant_cost_cap()
    cap_usd = cap_row.get("monthly_cap_usd")
    cap_f = _to_float(cap_usd) if cap_usd is not None else None
    pct = None
    if cap_f and cap_f > 0:
        pct = round((spend["total_usd"] / cap_f) * 100.0, 1)
    # Uncosted-call visibility — rows ledgered with cost_usd IS NULL
    # (usage data missing or no price configured for the model). The
    # admin needs to see these so the dashboard can't quietly under-
    # report by simply skipping them. We expose per-channel + total.
    # Window matches compute_mtd_spend (DATE_TRUNC('month', NOW())) so
    # totals + uncosted counts cover the same rows.
    tid = current_tenant_id()
    def _uncosted(table):
        try:
            row = query_db(
                f"SELECT COUNT(*) AS c FROM {table} "
                f"WHERE tenant_id=%s "
                f"  AND created_at >= DATE_TRUNC('month', NOW()) "
                f"  AND cost_usd IS NULL",
                (tid,), fetchone=True) or {}
            return int(row.get("c") or 0)
        except Exception as e:
            print(f"[cost summary] uncosted({table}) failed: {e}")
            return 0
    uc_chat = _uncosted("api_cost_events")
    uc_voice = _uncosted("voice_cost_events")
    uc_sms = _uncosted("sms_cost_events")

    # Today / this-week rollups in addition to MTD. The Cost tab spec
    # explicitly calls out "today, this week, this month" as required
    # headline numbers — admins reading the dashboard care more about
    # "are we on fire RIGHT NOW" than "what was the month-of-April".
    def _window_total(start_clause):
        try:
            row = query_db(
                "SELECT COALESCE(SUM(c),0) AS t FROM ("
                "  SELECT SUM(cost_usd) AS c FROM api_cost_events "
                f"   WHERE tenant_id=%s AND created_at >= {start_clause} "
                "  UNION ALL "
                "  SELECT SUM(cost_usd) FROM voice_cost_events "
                f"   WHERE tenant_id=%s AND created_at >= {start_clause} "
                "  UNION ALL "
                "  SELECT SUM(cost_usd) FROM sms_cost_events "
                f"   WHERE tenant_id=%s AND created_at >= {start_clause} "
                ") s",
                (tid, tid, tid), fetchone=True) or {}
            return _to_float(row.get("t") or 0)
        except Exception as e:
            print(f"[cost summary] window total failed: {e}")
            return 0.0
    today_usd = _window_total("DATE_TRUNC('day', NOW())")
    week_usd = _window_total("DATE_TRUNC('week', NOW())")

    # Month-end projection from the last 7-day rolling rate. Spec
    # wording: "month-end projection based on the last 7-day rolling
    # rate". Formula: avg_daily_last_7 × days_remaining_in_month +
    # mtd_already_spent. Returns None when we have <1 day of data so
    # the UI can render "—" instead of a misleading $0.
    projection_usd = None
    try:
        last7 = _window_total("NOW() - INTERVAL '7 days'")
        avg_daily = last7 / 7.0
        days_row = query_db(
            "SELECT EXTRACT(DAY FROM (DATE_TRUNC('month', NOW()) "
            "       + INTERVAL '1 month' - INTERVAL '1 day'))::int AS dim, "
            "       EXTRACT(DAY FROM NOW())::int AS dom",
            fetchone=True) or {}
        days_in_month = int(days_row.get("dim") or 30)
        day_of_month = int(days_row.get("dom") or 1)
        days_remaining = max(0, days_in_month - day_of_month)
        if last7 > 0:
            projection_usd = round(spend["total_usd"] + (avg_daily * days_remaining), 4)
    except Exception as e:
        print(f"[cost summary] projection failed: {e}")

    # Top visitors by spend MTD — only chat events carry visitor_id,
    # which matches the spec since tools/voice/SMS aren't visitor-
    # attributable. Filtered to non-empty visitor_id so anonymous
    # admin chats don't dominate the list.
    top_visitors = []
    try:
        rows = query_db(
            "SELECT visitor_id, SUM(cost_usd) AS usd, COUNT(*) AS calls "
            "  FROM api_cost_events "
            " WHERE tenant_id=%s "
            "   AND created_at >= DATE_TRUNC('month', NOW()) "
            "   AND visitor_id IS NOT NULL AND visitor_id <> '' "
            "   AND cost_usd IS NOT NULL "
            " GROUP BY visitor_id "
            " ORDER BY usd DESC LIMIT 10",
            (tid,)) or []
        top_visitors = [
            {"visitor_id": r["visitor_id"],
             "usd": round(_to_float(r["usd"] or 0), 5),
             "calls": int(r["calls"] or 0)}
            for r in rows
        ]
    except Exception as e:
        print(f"[cost summary] top_visitors failed: {e}")

    # Task #80: parallel subagent activity. Today's run count + cap
    # (from the atomic daily-counter table) and MTD total runs +
    # spend. Powers the "Sub-agent runs" tile on the Cost dashboard
    # so admins can see fan-out activity at a glance and drill into
    # /admin/api/chat/subagent-runs for the full per-run log.
    sub_today = 0
    sub_cap = int(cap_row.get("daily_subagent_runs_cap") or 50)
    sub_mtd_runs = 0
    sub_mtd_cost = 0.0
    try:
        r1 = query_db(
            "SELECT count FROM admin_subagent_daily_counters "
            "WHERE tenant_id=%s AND day=CURRENT_DATE",
            (tid,), fetchone=True) or {}
        sub_today = int(r1.get("count") or 0)
        r2 = query_db(
            "SELECT COUNT(*) AS runs, COALESCE(SUM(cost_usd),0) AS usd "
            "FROM admin_subagent_runs "
            "WHERE tenant_id=%s AND created_at >= DATE_TRUNC('month', NOW())",
            (tid,), fetchone=True) or {}
        sub_mtd_runs = int(r2.get("runs") or 0)
        sub_mtd_cost = round(_to_float(r2.get("usd") or 0), 5)
    except Exception as e:
        print(f"[cost summary] subagent stats failed: {e}")

    return jsonify({
        "period": _current_period(),
        "spend": spend,
        "today_usd": round(today_usd, 5),
        "week_usd": round(week_usd, 5),
        "projection_usd_eom": projection_usd,
        "top_visitors": top_visitors,
        "subagents": {
            "today_runs": sub_today,
            "daily_cap": sub_cap,
            "mtd_runs":  sub_mtd_runs,
            "mtd_cost_usd": sub_mtd_cost,
        },
        "cap": {
            "monthly_cap_usd": cap_f,
            "warn_at_percent": int(cap_row.get("warn_at_percent") or 80),
            "cap_behavior": cap_row.get("cap_behavior") or "alert_only",
            "alert_email": cap_row.get("alert_email") or "",
            "digest_email": cap_row.get("digest_email") or "",
            "percent_used": pct,
        },
        "uncosted_calls": {
            "chat":  uc_chat,
            "voice": uc_voice,
            "sms":   uc_sms,
            "total": uc_chat + uc_voice + uc_sms,
        },
    })


@cost_bp.route("/admin/api/cost/series", methods=["GET"])
@admin_required
def admin_cost_series():
    """Daily totals for the last N days (default 30). Used to draw the
    spend-over-time line chart on the dashboard."""
    err = _cost_feature_required()
    if err is not None:
        return err
    try:
        days = max(1, min(90, int(request.args.get("days", 30))))
    except (TypeError, ValueError):
        days = 30
    tid = current_tenant_id()
    sql = (
        "WITH days AS ("
        "  SELECT generate_series("
        "    DATE_TRUNC('day', NOW()) - (%s - 1) * INTERVAL '1 day',"
        "    DATE_TRUNC('day', NOW()), INTERVAL '1 day'"
        "  )::date AS d"
        "), api AS ("
        "  SELECT DATE_TRUNC('day', created_at)::date AS d, "
        "         COALESCE(SUM(cost_usd),0) AS s "
        "  FROM api_cost_events WHERE tenant_id = %s "
        "    AND created_at >= NOW() - (%s - 1) * INTERVAL '1 day' "
        "  GROUP BY 1"
        "), v AS ("
        "  SELECT DATE_TRUNC('day', created_at)::date AS d, "
        "         COALESCE(SUM(cost_usd),0) AS s "
        "  FROM voice_cost_events WHERE tenant_id = %s "
        "    AND created_at >= NOW() - (%s - 1) * INTERVAL '1 day' "
        "  GROUP BY 1"
        "), s AS ("
        "  SELECT DATE_TRUNC('day', created_at)::date AS d, "
        "         COALESCE(SUM(cost_usd),0) AS s "
        "  FROM sms_cost_events WHERE tenant_id = %s "
        "    AND created_at >= NOW() - (%s - 1) * INTERVAL '1 day' "
        "  GROUP BY 1"
        ") "
        "SELECT days.d AS day, "
        "       COALESCE(api.s,0) AS chat_usd, "
        "       COALESCE(v.s,0)   AS voice_usd, "
        "       COALESCE(s.s,0)   AS sms_usd, "
        "       COALESCE(api.s,0)+COALESCE(v.s,0)+COALESCE(s.s,0) AS total_usd "
        "  FROM days "
        "  LEFT JOIN api ON api.d = days.d "
        "  LEFT JOIN v   ON v.d   = days.d "
        "  LEFT JOIN s   ON s.d   = days.d "
        " ORDER BY days.d ASC"
    )
    rows = query_db(sql, (days, tid, days, tid, days, tid, days)) or []
    series = [{
        "day": (r["day"].isoformat() if hasattr(r["day"], "isoformat") else str(r["day"])),
        "chat_usd": _to_float(r["chat_usd"]),
        "voice_usd": _to_float(r["voice_usd"]),
        "sms_usd": _to_float(r["sms_usd"]),
        "total_usd": _to_float(r["total_usd"]),
    } for r in rows]
    return jsonify({"days": days, "series": series})


@cost_bp.route("/admin/api/cost/by-surface", methods=["GET"])
@admin_required
def admin_cost_by_surface():
    """MTD spend grouped by surface (visitor_chat, admin_chat, voice_tts,
    voice_stt, sms_campaign, etc). Powers the breakdown table on the
    Cost tab — answers 'where is my money actually going?'"""
    err = _cost_feature_required()
    if err is not None:
        return err
    tid = current_tenant_id()
    out = []
    try:
        rows = query_db(
            "SELECT surface, COUNT(*) AS events, COALESCE(SUM(cost_usd),0) AS s "
            "FROM api_cost_events "
            "WHERE tenant_id=%s AND created_at >= DATE_TRUNC('month', NOW()) "
            "GROUP BY surface", (tid,)) or []
        for r in rows:
            out.append({"surface": r["surface"], "channel": "chat",
                        "events": int(r["events"] or 0),
                        "cost_usd": _to_float(r["s"])})
        rows = query_db(
            "SELECT surface, COUNT(*) AS events, COALESCE(SUM(cost_usd),0) AS s "
            "FROM voice_cost_events "
            "WHERE tenant_id=%s AND created_at >= DATE_TRUNC('month', NOW()) "
            "GROUP BY surface", (tid,)) or []
        for r in rows:
            out.append({"surface": r["surface"], "channel": "voice",
                        "events": int(r["events"] or 0),
                        "cost_usd": _to_float(r["s"])})
        rows = query_db(
            "SELECT surface, COUNT(*) AS events, COALESCE(SUM(cost_usd),0) AS s "
            "FROM sms_cost_events "
            "WHERE tenant_id=%s AND created_at >= DATE_TRUNC('month', NOW()) "
            "GROUP BY surface", (tid,)) or []
        for r in rows:
            out.append({"surface": r["surface"], "channel": "sms",
                        "events": int(r["events"] or 0),
                        "cost_usd": _to_float(r["s"])})
    except Exception as e:
        print(f"[cost] by-surface failed: {e}")
    out.sort(key=lambda x: x["cost_usd"], reverse=True)
    return jsonify({"rows": out})


@cost_bp.route("/admin/api/cost/by-model", methods=["GET"])
@admin_required
def admin_cost_by_model():
    """MTD spend grouped by provider+model across all three ledgers.
    Lets the admin see e.g. 'GPT-4o-mini = $4.12, ElevenLabs Turbo =
    $1.30, Twilio US SMS = $0.18' at a glance."""
    err = _cost_feature_required()
    if err is not None:
        return err
    tid = current_tenant_id()
    out = []
    try:
        rows = query_db(
            "SELECT provider, model, COUNT(*) AS events, "
            "       COALESCE(SUM(cost_usd),0) AS s, "
            "       COALESCE(SUM(prompt_tokens),0)::bigint AS prompt_tok, "
            "       COALESCE(SUM(completion_tokens),0)::bigint AS completion_tok "
            "FROM api_cost_events "
            "WHERE tenant_id=%s AND created_at >= DATE_TRUNC('month', NOW()) "
            "GROUP BY provider, model", (tid,)) or []
        for r in rows:
            out.append({"channel": "chat",
                        "provider": r["provider"], "model": r["model"],
                        "events": int(r["events"] or 0),
                        "prompt_tokens": int(r["prompt_tok"] or 0),
                        "completion_tokens": int(r["completion_tok"] or 0),
                        "cost_usd": _to_float(r["s"])})
        rows = query_db(
            "SELECT provider, model, COUNT(*) AS events, "
            "       COALESCE(SUM(cost_usd),0) AS s, "
            "       COALESCE(SUM(char_count),0)::bigint AS chars, "
            "       COALESCE(SUM(audio_seconds),0) AS secs "
            "FROM voice_cost_events "
            "WHERE tenant_id=%s AND created_at >= DATE_TRUNC('month', NOW()) "
            "GROUP BY provider, model", (tid,)) or []
        for r in rows:
            out.append({"channel": "voice",
                        "provider": r["provider"], "model": r["model"],
                        "events": int(r["events"] or 0),
                        "chars": int(r["chars"] or 0),
                        "audio_seconds": _to_float(r["secs"]),
                        "cost_usd": _to_float(r["s"])})
        rows = query_db(
            "SELECT provider, COUNT(*) AS events, "
            "       COALESCE(SUM(cost_usd),0) AS s, "
            "       COALESCE(SUM(segments),0)::bigint AS segs "
            "FROM sms_cost_events "
            "WHERE tenant_id=%s AND created_at >= DATE_TRUNC('month', NOW()) "
            "GROUP BY provider", (tid,)) or []
        for r in rows:
            out.append({"channel": "sms",
                        "provider": r["provider"], "model": "sms",
                        "events": int(r["events"] or 0),
                        "segments": int(r["segs"] or 0),
                        "cost_usd": _to_float(r["s"])})
    except Exception as e:
        print(f"[cost] by-model failed: {e}")
    out.sort(key=lambda x: x["cost_usd"], reverse=True)
    return jsonify({"rows": out})


@cost_bp.route("/admin/api/cost/prices", methods=["GET"])
@admin_required
def admin_cost_prices_get():
    """List every model_prices row so the admin can audit/edit unit
    prices. Sorted for stable rendering across reloads."""
    err = _cost_feature_required()
    if err is not None:
        return err
    rows = query_db(
        "SELECT * FROM model_prices ORDER BY provider, model, surface") or []
    return jsonify({"rows": [dict(r) for r in rows]})


@cost_bp.route("/admin/api/cost/prices/<int:row_id>", methods=["PATCH"])
@admin_required
def admin_cost_prices_patch(row_id):
    """Update one model_prices row. Only the four price columns and
    notes are editable — provider/model/kind are identity and changing
    them would orphan historical events. Existing event rows are NOT
    rewritten (we stamp unit price at write time on purpose), so a
    price edit only affects future events."""
    err = _cost_feature_required()
    if err is not None:
        return err
    body = request.get_json(silent=True) or {}
    allowed = {
        "input_price_per_million_tokens",
        "output_price_per_million_tokens",
        "tts_price_per_million_chars",
        "stt_price_per_minute",
        "sms_price_per_segment",
        "notes",
    }
    sets = []
    args = []
    for k, v in body.items():
        if k not in allowed:
            continue
        if k == "notes":
            sets.append("notes = %s")
            args.append((v or "")[:500])
        else:
            sets.append(f"{k} = %s")
            args.append(None if v in ("", None) else _to_float(v))
    if not sets:
        return jsonify({"error": "no editable fields supplied"}), 400
    sets.append("updated_at = NOW()")
    args.append(row_id)
    execute_db(
        f"UPDATE model_prices SET {', '.join(sets)} WHERE id = %s", tuple(args))
    # Bust the in-process price cache so the next cost write picks up
    # the new unit price immediately. Goes through the core invalidator
    # (which clears both _PRICE_CACHE and its TTL map) rather than mutating
    # the re-exported dict directly — the cache + its invalidator now live
    # together in core (Track B / task 078, piece #2).
    try:
        _invalidate_price_cache()
    except Exception:
        pass
    row = query_db("SELECT * FROM model_prices WHERE id = %s",
                   (row_id,), fetchone=True)
    return jsonify(dict(row) if row else {})


@cost_bp.route("/admin/api/cost/cap", methods=["GET"])
@admin_required
def admin_cost_cap_get():
    """Return the current tenant's cost cap configuration."""
    err = _cost_feature_required()
    if err is not None:
        return err
    return jsonify(dict(get_tenant_cost_cap()))


@cost_bp.route("/admin/api/cost/cap", methods=["PUT"])
@admin_required
def admin_cost_cap_put():
    """Upsert the cost-cap row. Validates cap_behavior to one of three
    known values and warn_at_percent to a 1-100 integer so a bad payload
    can't silently disable the cap."""
    err = _cost_feature_required()
    if err is not None:
        return err
    body = request.get_json(silent=True) or {}
    tid = current_tenant_id()

    monthly = body.get("monthly_cap_usd")
    if monthly in ("", None):
        monthly_v = None
    else:
        try:
            monthly_v = max(0.0, _to_float(monthly))
        except Exception:
            return jsonify({"error": "monthly_cap_usd must be a number"}), 400

    try:
        warn_pct = int(body.get("warn_at_percent", 80))
    except (TypeError, ValueError):
        return jsonify({"error": "warn_at_percent must be an integer"}), 400
    if warn_pct < 1 or warn_pct > 100:
        return jsonify({"error": "warn_at_percent must be 1-100"}), 400

    behavior = (body.get("cap_behavior") or "alert_only").lower()
    if behavior not in ("alert_only", "throttle", "strict_block"):
        return jsonify({"error": "cap_behavior must be alert_only|throttle|strict_block"}), 400

    alert_email = (body.get("alert_email") or "")[:200]
    digest_email = (body.get("digest_email") or "")[:200]

    execute_db(
        "INSERT INTO tenant_cost_caps "
        "  (tenant_id, monthly_cap_usd, warn_at_percent, cap_behavior, "
        "   alert_email, digest_email, updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,NOW()) "
        "ON CONFLICT (tenant_id) DO UPDATE SET "
        "  monthly_cap_usd = EXCLUDED.monthly_cap_usd, "
        "  warn_at_percent = EXCLUDED.warn_at_percent, "
        "  cap_behavior    = EXCLUDED.cap_behavior, "
        "  alert_email     = EXCLUDED.alert_email, "
        "  digest_email    = EXCLUDED.digest_email, "
        "  updated_at      = NOW()",
        (tid, monthly_v, warn_pct, behavior, alert_email, digest_email),
    )
    return jsonify(dict(get_tenant_cost_cap()))
