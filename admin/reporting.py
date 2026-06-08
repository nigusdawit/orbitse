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
import json

from flask import Blueprint, request, jsonify, session

from core import (
    query_db,
    execute_db,
    admin_required,
    current_tenant_id,
    _vp_as_list,
    capture_exc,
)

reporting_bp = Blueprint("reporting", __name__)


# ---- chat history (conversation log + stats), verbatim from app.py ----

@reporting_bp.route("/admin/api/chat-history", methods=["GET"])
@admin_required
def admin_chat_history():
    """GET /admin/api/chat-history — List conversations with stats."""
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    offset = (page - 1) * per_page

    # 095 §2.4 — additive columns for the inbox: ai_paused (LEFT JOIN the takeover
    # table, which the bootstrap guarantees exists), plus last-message time/role to
    # drive live/unread markers. Existing keys (c.*, message_count, first_message)
    # are unchanged, so the legacy table renderer keeps working.
    conversations = query_db("""
        SELECT c.*,
            c.visitor_id,
            (SELECT COUNT(*) FROM chat_messages WHERE conversation_id = c.id) as message_count,
            (SELECT content FROM chat_messages WHERE conversation_id = c.id AND role = 'user' ORDER BY id LIMIT 1) as first_message,
            COALESCE(t.ai_paused, FALSE) as ai_paused,
            (SELECT created_at FROM chat_messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) as last_message_at,
            (SELECT role FROM chat_messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) as last_role
        FROM chat_conversations c
        LEFT JOIN conversation_takeover t ON t.conversation_id = c.id
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


@reporting_bp.route("/admin/api/conversations/<int:conv_id>/context", methods=["GET"])
@admin_required
def admin_conversation_context(conv_id):
    """Side-panel context for a conversation (task 095, gap §2.4). Available to any
    logged-in admin who can open the Chat History inbox — the visitor context is part
    of handling a conversation, so it shares the same audience as the inbox itself
    (single-tenant template, no cross-tenant boundary to protect). Returns the
    visitor_profile (lead_score / interests / needs / summary — 'intent' ≈
    interests+needs, the closest existing signal), a derived source channel (latest
    page_views utm/referrer for the visitor), and the linked lead, if any. Each
    section is independently try/except'd → a missing profile/lead/source yields an empty
    section, never a 500."""
    conv = query_db("SELECT id, visitor_id FROM chat_conversations WHERE id=%s", (conv_id,), fetchone=True)
    if not conv:
        return jsonify({"error": "Conversation not found"}), 404
    vid = (conv.get("visitor_id") or "").strip()
    tid = current_tenant_id()

    profile = None
    try:
        if vid:
            p = query_db(
                "SELECT lead_score, interests, needs, consent, summary, turns "
                "FROM visitor_profiles WHERE tenant_id=%s AND visitor_id=%s",
                (tid, vid), fetchone=True)
            if p:
                profile = {
                    "lead_score": int(p.get("lead_score") or 0),
                    "interests": _vp_as_list(p.get("interests")),
                    "needs": _vp_as_list(p.get("needs")),
                    "consent": bool(p.get("consent")),
                    "summary": p.get("summary") or "",
                    "turns": int(p.get("turns") or 0),
                }
    except Exception:
        profile = None

    source = ""
    try:
        if vid:
            s = query_db(
                "SELECT utm_source, referrer_url FROM page_views "
                "WHERE visitor_id=%s ORDER BY id DESC LIMIT 1", (vid,), fetchone=True) or {}
            utm = (s.get("utm_source") or "").strip()
            ref = (s.get("referrer_url") or "").strip()
            source = ("UTM: " + utm) if utm else (("Referral: " + ref) if ref else "Direct")
    except Exception:
        source = ""

    lead = None
    try:
        if vid:
            l = query_db(
                "SELECT id, name, email, phone, status, interest FROM leads "
                "WHERE tenant_id=%s AND visitor_id=%s ORDER BY id DESC LIMIT 1",
                (tid, vid), fetchone=True)
            if l:
                lead = {"id": l["id"], "name": l.get("name") or "", "email": l.get("email") or "",
                        "phone": l.get("phone") or "", "status": l.get("status") or "",
                        "interest": l.get("interest") or ""}
    except Exception:
        lead = None

    return jsonify({"ok": True, "visitor_id": vid, "profile": profile, "source": source, "lead": lead})


# ---- 095 §2.4 human takeover (any logged-in admin; MUTATING) ----------------
# Available to any admin who can open the Chat History inbox (the tab is shown
# to clients via the `chat_history` feature, so the actions inside it must be
# usable by the same audience — replying is the core action of an inbox). The
# visitor context panel above shares this same admin audience. Conversations are
# not tenant-scoped (single-tenant template), so there is no cross-tenant boundary
# to protect here.
# Pausing the AI for a conversation is stored in conversation_takeover. The live
# /api/chat SSE generator reads ai_paused at the top of generate() and, if set,
# records the visitor's message + skips the LLM (see app._persist_visitor_user_message
# + the gate in api_chat). Releasing flips ai_paused back to FALSE so the AI resumes.

def _takeover_upsert(conv_id, ai_paused, who):
    """Upsert the conversation_takeover row. Sets ai_paused + bookkeeping stamps:
    taken_over_at is set once (kept on re-takeover), released_at is stamped when
    ai_paused goes FALSE and cleared when it goes TRUE. Raises on DB error so the
    caller's try/except can capture + 500."""
    execute_db(
        "INSERT INTO conversation_takeover "
        "  (conversation_id, ai_paused, taken_over_by, taken_over_at, released_at, updated_at) "
        "VALUES (%s, %s, %s, CASE WHEN %s THEN NOW() END, CASE WHEN %s THEN NULL ELSE NOW() END, NOW()) "
        "ON CONFLICT (conversation_id) DO UPDATE SET "
        "  ai_paused      = EXCLUDED.ai_paused, "
        "  taken_over_by  = EXCLUDED.taken_over_by, "
        "  taken_over_at  = COALESCE(conversation_takeover.taken_over_at, EXCLUDED.taken_over_at), "
        "  released_at    = CASE WHEN EXCLUDED.ai_paused THEN NULL ELSE NOW() END, "
        "  updated_at     = NOW()",
        (conv_id, bool(ai_paused), who, bool(ai_paused), bool(ai_paused)),
    )


@reporting_bp.route("/admin/api/conversations/<int:conv_id>/takeover", methods=["POST"])
@admin_required
def admin_conversation_takeover(conv_id):
    """Pause the AI for a conversation (human takeover). Any logged-in admin."""
    conv = query_db("SELECT id FROM chat_conversations WHERE id=%s", (conv_id,), fetchone=True)
    if not conv:
        return jsonify({"error": "Conversation not found"}), 404
    try:
        _takeover_upsert(conv_id, True, session.get("admin_role", "admin"))
    except Exception as e:
        capture_exc(e, "admin_conversation_takeover")
        return jsonify({"error": "takeover_failed"}), 500
    return jsonify({"ok": True, "ai_paused": True})


@reporting_bp.route("/admin/api/conversations/<int:conv_id>/release", methods=["POST"])
@admin_required
def admin_conversation_release(conv_id):
    """Resume the AI for a conversation (release the human takeover). Any logged-in admin."""
    conv = query_db("SELECT id FROM chat_conversations WHERE id=%s", (conv_id,), fetchone=True)
    if not conv:
        return jsonify({"error": "Conversation not found"}), 404
    try:
        _takeover_upsert(conv_id, False, session.get("admin_role", "admin"))
    except Exception as e:
        capture_exc(e, "admin_conversation_release")
        return jsonify({"error": "release_failed"}), 500
    return jsonify({"ok": True, "ai_paused": False})


@reporting_bp.route("/admin/api/conversations/<int:conv_id>/message", methods=["POST"])
@admin_required
def admin_conversation_message(conv_id):
    """Send a human reply into a conversation. Inserts a chat_messages row with
    role='agent_human' and, as a side effect, PAUSES the AI (a human is now
    handling the thread, so the AI must not also reply). The visitor receives it
    via the public agent-messages poll (P3). Any logged-in admin.

    SECURITY: the content is operator-authored but is treated as untrusted on the
    way OUT to the visitor — the public widget renders agent_human messages as
    TEXT (textContent), never HTML, so an operator can't inject script into a
    visitor's page. We also bound the length."""
    conv = query_db("SELECT id FROM chat_conversations WHERE id=%s", (conv_id,), fetchone=True)
    if not conv:
        return jsonify({"error": "Conversation not found"}), 404
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "empty"}), 400
    content = content[:8000]   # bound — chat_messages.content is TEXT but keep it sane
    try:
        # Sending implies takeover: pause the AI so it won't also answer this turn.
        _takeover_upsert(conv_id, True, session.get("admin_role", "admin"))
        row = execute_db(
            "INSERT INTO chat_messages (conversation_id, role, content) "
            "VALUES (%s, 'agent_human', %s) RETURNING id",
            (conv_id, content),
        )
        execute_db("UPDATE chat_conversations SET updated_at = NOW() WHERE id = %s RETURNING id", (conv_id,))
    except Exception as e:
        capture_exc(e, "admin_conversation_message")
        return jsonify({"error": "send_failed"}), 500
    msg_id = row.get("id") if isinstance(row, dict) else None
    return jsonify({"ok": True, "id": msg_id, "ai_paused": True})


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


# ---- marketing-insights viewers (Track B, verbatim; read-only) ----
# The "Marketing Insights" tab is purely a viewer over tables the admin AI
# populates; approve/reject of drafts still goes through the chat-action
# endpoints (which stay in app.py). Pure query_db reads, no shared helpers.


@reporting_bp.route("/admin/api/marketing/insights", methods=["GET"])
@admin_required
def admin_list_marketing_insights():
    """GET /admin/api/marketing/insights — list cached insight runs.
    Optional ?type=<insight_type> filters to one kind (chat_topics /
    page_library / seo_gaps). Default 50 most recent."""
    insight_type = (request.args.get("type") or "").strip()[:50]
    try:
        limit = max(1, min(int(request.args.get("limit") or 50), 200))
    except Exception:
        limit = 50
    where = ["1=1"]
    args = []
    if insight_type:
        where.append("insight_type = %s")
        args.append(insight_type)
    rows = query_db(
        "SELECT id, insight_type, window_start, window_end, "
        "       summary_json, notes, created_at "
        "FROM marketing_insights_log WHERE " + " AND ".join(where)
        + " ORDER BY created_at DESC LIMIT %s",
        tuple(args + [limit]),
    ) or []
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "insight_type": r.get("insight_type") or "",
            "window_start": (r["window_start"].isoformat()
                              if r.get("window_start") else None),
            "window_end": (r["window_end"].isoformat()
                            if r.get("window_end") else None),
            "summary_json": r.get("summary_json") or {},
            "notes": r.get("notes") or "",
            "created_at": (r["created_at"].isoformat()
                           if r.get("created_at") else None),
        })
    return jsonify({"insights": out, "count": len(out)})


@reporting_bp.route("/admin/api/marketing/drafts", methods=["GET"])
@admin_required
def admin_list_marketing_drafts():
    """GET /admin/api/marketing/drafts — list AI-drafted blog / FAQ
    entries the admin AI has queued for approval. Wraps the existing
    admin_pending_actions table; approve / reject still go through
    /admin/api/chat/action/<id>/approve | /reject.

    The optional ?status filter accepts pending | executed | rejected |
    failed and also takes 'approved' as a UI-friendly alias for 'executed'
    so the dashboard filter labels can read naturally."""
    status_raw = (request.args.get("status") or "pending").strip()[:20]
    # Allowlist + 'approved' alias → 'executed' (the real DB value).
    valid_status = {"pending", "executed", "rejected", "failed"}
    if status_raw == "approved":
        status = "executed"
    elif status_raw in valid_status:
        status = status_raw
    else:
        status = "pending"
    try:
        limit = max(1, min(int(request.args.get("limit") or 50), 200))
    except Exception:
        limit = 50
    rows = query_db(
        "SELECT id, action_type, target_table, target_id, "
        "       payload_json, preview, status, error_text, "
        "       created_at, decided_at "
        "FROM admin_pending_actions "
        "WHERE target_table IN ('blog_posts','faqs') "
        "  AND status = %s "
        "ORDER BY created_at DESC LIMIT %s",
        (status, limit),
    ) or []
    out = []
    for r in rows:
        payload = r.get("payload_json") or {}
        if isinstance(payload, str):
            try: payload = json.loads(payload)
            except Exception: payload = {}
        fields = (payload.get("fields") or {}) if isinstance(payload, dict) else {}
        out.append({
            "id": r["id"],
            "kind": ("blog" if r.get("target_table") == "blog_posts"
                     else "faq" if r.get("target_table") == "faqs"
                     else (r.get("target_table") or "")),
            "target_table": r.get("target_table") or "",
            "target_id": r.get("target_id"),
            "title": (fields.get("title") or fields.get("question")
                      or "(untitled)"),
            "body_preview": ((fields.get("content") or fields.get("answer")
                              or "")[:400]),
            "preview": r.get("preview") or "",
            "status": r.get("status") or "",
            "error_text": r.get("error_text") or "",
            "created_at": (r["created_at"].isoformat()
                           if r.get("created_at") else None),
            "decided_at": (r["decided_at"].isoformat()
                           if r.get("decided_at") else None),
        })
    return jsonify({"drafts": out, "count": len(out)})
