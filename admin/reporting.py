"""admin/reporting.py - read-only admin dashboards, as a Flask blueprint.

Part of the app.py de-monolith (Track B), mirroring admin/content.py. This blueprint
owns the two read-only reporting surfaces the dashboard renders: chat-history (the
conversation log + chat stats) and analytics (pageview aggregates + the daily bar
chart). Every route here is a GET that only reads via query_db - no writes, no shared
helpers, no module-level state, which is why they move cleanly as a self-contained set.

All routes are gated by @admin_required (from core). URLs keep their absolute
/admin/api/* paths, so the route table is unchanged - only the Flask endpoint name
gains a "reporting." prefix (admin JS calls these by URL, not url_for). CSRF /
feature-flag enforcement runs in app.py's global before_request hooks, which apply to
blueprint routes too, so nothing extra is needed here.

Registered in app.py via app.register_blueprint(reporting_bp), after sitebuilder_bp.
Imports come from core (never app - that would be circular).
"""
from flask import Blueprint, request, jsonify

from core import query_db, admin_required

reporting_bp = Blueprint("reporting", __name__)


# ---- chat history (conversation log + stats), verbatim from app.py ----

@reporting_bp.route("/admin/api/chat-history", methods=["GET"])
@admin_required
def admin_chat_history():
    """GET /admin/api/chat-history — List conversations with stats."""
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    offset = (page - 1) * per_page

    conversations = query_db("""
        SELECT c.*,
            c.visitor_id,
            (SELECT COUNT(*) FROM chat_messages WHERE conversation_id = c.id) as message_count,
            (SELECT content FROM chat_messages WHERE conversation_id = c.id AND role = 'user' ORDER BY id LIMIT 1) as first_message
        FROM chat_conversations c
        ORDER BY c.updated_at DESC
        LIMIT %s OFFSET %s
    """, (per_page, offset))

    # Chat analytics stats:
    # - total_conversations: one per page load (each refresh = new conversation)
    # - messages_today: all messages sent today across all conversations
    # - avg_messages: average messages per conversation
    # - unique_visitors: distinct visitor_ids (tracks returning visitors across sessions)
    stats = query_db("""
        SELECT
            (SELECT COUNT(*) FROM chat_conversations) as total_conversations,
            (SELECT COUNT(*) FROM chat_messages WHERE created_at >= CURRENT_DATE) as messages_today,
            (SELECT ROUND(AVG(cnt), 1) FROM (SELECT COUNT(*) as cnt FROM chat_messages GROUP BY conversation_id) sub) as avg_messages,
            (SELECT COUNT(DISTINCT visitor_id) FROM chat_conversations WHERE visitor_id != '' AND visitor_id IS NOT NULL) as unique_visitors
    """, fetchone=True)

    return jsonify({"conversations": conversations or [], "stats": stats or {}})


@reporting_bp.route("/admin/api/chat-history/<int:conv_id>", methods=["GET"])
@admin_required
def admin_chat_detail(conv_id):
    """GET /admin/api/chat-history/<id> — Full conversation with messages."""
    conv = query_db("SELECT * FROM chat_conversations WHERE id = %s", (conv_id,), fetchone=True)
    if not conv:
        return jsonify({"error": "Conversation not found"}), 404
    messages = query_db(
        "SELECT * FROM chat_messages WHERE conversation_id = %s ORDER BY created_at", (conv_id,)
    )
    return jsonify({"conversation": conv, "messages": messages or []})


# ---- analytics (pageview aggregates + daily chart), verbatim from app.py ----

@reporting_bp.route("/admin/api/analytics")
@admin_required
def admin_api_analytics():
    """GET /admin/api/analytics — Return aggregated analytics data.

    Query params:
      days  — number of past days to include (default 30, max 365)
    """
    days = min(int(request.args.get("days", 30)), 365)

    # --- Summary counts ------------------------------------------------------
    summary = query_db(
        """SELECT
               COUNT(*)                                     AS total_views,
               COUNT(DISTINCT visitor_id) FILTER (WHERE visitor_id != '') AS unique_visitors,
               COUNT(DISTINCT session_id)                   AS total_sessions,
               COALESCE(AVG(duration_seconds) FILTER (WHERE duration_seconds > 0), 0) AS avg_duration,
               COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE) AS today_views,
               COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE - INTERVAL '7 days') AS week_views
           FROM page_views
           WHERE created_at >= NOW() - MAKE_INTERVAL(days => %s)""",
        (days,),
        fetchone=True,
    )

    # --- Top pages -----------------------------------------------------------
    top_pages = query_db(
        """SELECT page_url, COUNT(*) AS views,
                  COALESCE(AVG(duration_seconds) FILTER (WHERE duration_seconds > 0), 0) AS avg_dur
             FROM page_views
            WHERE created_at >= NOW() - MAKE_INTERVAL(days => %s)
            GROUP BY page_url
            ORDER BY views DESC
            LIMIT 10""",
        (days,),
    )

    # --- Browser breakdown ---------------------------------------------------
    browsers = query_db(
        """SELECT browser, COUNT(*) AS cnt
             FROM page_views
            WHERE created_at >= NOW() - MAKE_INTERVAL(days => %s) AND browser != ''
            GROUP BY browser ORDER BY cnt DESC LIMIT 5""",
        (days,),
    )

    # --- Device breakdown ----------------------------------------------------
    devices = query_db(
        """SELECT device_type, COUNT(*) AS cnt
             FROM page_views
            WHERE created_at >= NOW() - MAKE_INTERVAL(days => %s)
            GROUP BY device_type ORDER BY cnt DESC""",
        (days,),
    )

    # --- OS breakdown --------------------------------------------------------
    os_stats = query_db(
        """SELECT os, COUNT(*) AS cnt
             FROM page_views
            WHERE created_at >= NOW() - MAKE_INTERVAL(days => %s) AND os != ''
            GROUP BY os ORDER BY cnt DESC LIMIT 5""",
        (days,),
    )

    # --- Top referrers -------------------------------------------------------
    referrers = query_db(
        """SELECT referrer_url, COUNT(*) AS cnt
             FROM page_views
            WHERE created_at >= NOW() - MAKE_INTERVAL(days => %s) AND referrer_url != ''
            GROUP BY referrer_url ORDER BY cnt DESC LIMIT 10""",
        (days,),
    )

    # --- Top UTM sources -----------------------------------------------------
    utm_sources = query_db(
        """SELECT utm_source, COUNT(*) AS cnt
             FROM page_views
            WHERE created_at >= NOW() - MAKE_INTERVAL(days => %s) AND utm_source != ''
            GROUP BY utm_source ORDER BY cnt DESC LIMIT 5""",
        (days,),
    )

    # --- Recent page views (last 50) ----------------------------------------
    recent = query_db(
        """SELECT id, session_id, visitor_id, page_url, referrer_url,
                  browser, os, device_type, duration_seconds,
                  utm_source, created_at
             FROM page_views
            WHERE created_at >= NOW() - MAKE_INTERVAL(days => %s)
            ORDER BY created_at DESC LIMIT 50""",
        (days,),
    )

    def _row(r):
        d = dict(r)
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        return d

    return jsonify({
        "summary": {
            "total_views": summary["total_views"],
            "unique_visitors": summary["unique_visitors"],
            "total_sessions": summary["total_sessions"],
            "avg_duration": round(float(summary["avg_duration"]), 1),
            "today_views": summary["today_views"],
            "week_views": summary["week_views"],
        },
        "top_pages":   [_row(r) for r in top_pages],
        "browsers":    [_row(r) for r in browsers],
        "devices":     [_row(r) for r in devices],
        "os_stats":    [_row(r) for r in os_stats],
        "referrers":   [_row(r) for r in referrers],
        "utm_sources": [_row(r) for r in utm_sources],
        "recent":      [_row(r) for r in recent],
    })


@reporting_bp.route("/admin/api/analytics/chart")
@admin_required
def admin_api_analytics_chart():
    """GET /admin/api/analytics/chart — Daily pageview counts for bar chart.

    Query params:
      days — number of past days (default 30, max 90)
    Returns JSON array of { date, views } objects.
    """
    days = min(int(request.args.get("days", 30)), 90)

    rows = query_db(
        """SELECT d::date AS date, COALESCE(pv.cnt, 0) AS views
             FROM generate_series(
                      (CURRENT_DATE - MAKE_INTERVAL(days => %s - 1)),
                      CURRENT_DATE,
                      '1 day'::interval
                  ) AS d
             LEFT JOIN (
                 SELECT created_at::date AS day, COUNT(*) AS cnt
                   FROM page_views
                  WHERE created_at >= CURRENT_DATE - MAKE_INTERVAL(days => %s - 1)
                  GROUP BY day
             ) pv ON pv.day = d::date
           ORDER BY d""",
        (days, days),
    )

    result = []
    for r in rows:
        d = r["date"]
        result.append({
            "date": d.isoformat() if hasattr(d, "isoformat") else str(d),
            "views": r["views"],
        })
    return jsonify(result)
