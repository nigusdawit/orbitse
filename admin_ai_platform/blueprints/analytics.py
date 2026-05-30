"""
admin_ai_platform.blueprints.analytics
=======================================

Visitor + chat + form analytics (M15).

Public tracking (embeddable — the widget/loader fires these cross-origin with an
X-Embed-Key):
  * ``POST /api/track/pageview``   record a view (deduped per session+path/window)
  * ``POST /api/track/duration``   patch dwell time on unload (sendBeacon)

Admin reads (``@admin_required``):
  * ``GET /admin/api/analytics``         totals + top pages/referrers/UTM + device
  * ``GET /admin/api/analytics/chart``   daily series (default 30d)
  * ``GET /admin/api/analytics/chat``    chat volume + tool-usage from tool_calls_json
  * ``GET /admin/api/analytics/forms``   submissions per form

Tenant scoping uses ``current_tenant_id()`` so central + self-host both work.
"""

from __future__ import annotations

import time
import threading
from urllib.parse import urlparse

from flask import Blueprint, request, jsonify, g

from ..db import query_db, execute_db
from ..auth import admin_required
from ..tenancy import current_tenant_id

bp = Blueprint("analytics", __name__)

# Per-(session, path) pageview dedupe window — repeat views inside this many
# seconds are treated as the same view (SPA re-renders, double-fires).
_PAGEVIEW_WINDOW_SEC = 10
_DEDUPE_LOCK = threading.Lock()
_RECENT: dict = {}   # (session, path) -> last_epoch


def _parse_ua(ua: str):
    """Cheap User-Agent classification → (device_type, browser, os). Good enough
    for dashboard breakdowns without pulling a UA-parsing dependency."""
    u = (ua or "").lower()
    if any(x in u for x in ("mobile", "iphone", "android", "ipod")):
        device = "tablet" if "ipad" in u or "tablet" in u else "mobile"
    elif "ipad" in u or "tablet" in u:
        device = "tablet"
    else:
        device = "desktop"
    if "edg" in u:
        browser = "Edge"
    elif "chrome" in u or "crios" in u:
        browser = "Chrome"
    elif "firefox" in u or "fxios" in u:
        browser = "Firefox"
    elif "safari" in u:
        browser = "Safari"
    else:
        browser = "Other"
    # iOS first: iPhone/iPad UAs also contain "Mac OS X", which would otherwise
    # be misread as macOS. Android before Linux for the same reason.
    if "windows" in u:
        os_name = "Windows"
    elif "iphone" in u or "ipad" in u or "ipod" in u:
        os_name = "iOS"
    elif "android" in u:
        os_name = "Android"
    elif "mac os" in u or "macintosh" in u:
        os_name = "macOS"
    elif "linux" in u:
        os_name = "Linux"
    else:
        os_name = "Other"
    return device, browser, os_name


def _tenant():
    """Tenant id for the row — set by embed-auth on keyed requests, else default."""
    return getattr(g, "tenant_id", None) or current_tenant_id()


def _deduped(session_id, path):
    """True if a pageview for this (session, path) fired within the window."""
    now = time.time()
    key = (session_id, path)
    with _DEDUPE_LOCK:
        if len(_RECENT) > 20000:
            for k, ts in [(k, t) for k, t in _RECENT.items()
                          if now - t > _PAGEVIEW_WINDOW_SEC]:
                _RECENT.pop(k, None)
        last = _RECENT.get(key)
        if last is not None and now - last < _PAGEVIEW_WINDOW_SEC:
            return True
        _RECENT[key] = now
        return False


@bp.route("/api/track/pageview", methods=["POST"])
def track_pageview():
    """Record a pageview. Deduped per (session, path) inside a short window so a
    page that re-fires on SPA navigation doesn't inflate counts. Always 200 so a
    tracking failure never disrupts the host page."""
    d = request.get_json(silent=True) or {}
    url = (d.get("url") or "").strip()[:2000]
    session_id = (d.get("session_id") or "").strip()[:100]
    if not url:
        return jsonify({"ok": True, "skipped": "no url"}), 200
    try:
        path = urlparse(url).path or "/"
    except Exception:
        path = "/"
    if session_id and _deduped(session_id, path):
        return jsonify({"ok": True, "deduped": True}), 200
    device, browser, os_name = _parse_ua(request.headers.get("User-Agent", ""))
    try:
        execute_db(
            "INSERT INTO page_views (tenant_id, session_id, visitor_id, url, path, referrer, "
            " utm_source, utm_medium, utm_campaign, device_type, browser, os, screen, language) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (_tenant(), session_id, (d.get("visitor_id") or "")[:100], url, path,
             (d.get("referrer") or "")[:2000], (d.get("utm_source") or "")[:200],
             (d.get("utm_medium") or "")[:200], (d.get("utm_campaign") or "")[:200],
             device, browser, os_name, (d.get("screen") or "")[:20],
             (d.get("language") or "")[:20]))
    except Exception as e:
        print(f"[analytics] pageview insert failed: {e}")
        return jsonify({"ok": False}), 200
    return jsonify({"ok": True, "tracked": True}), 200


@bp.route("/api/track/duration", methods=["POST"])
def track_duration():
    """Patch dwell time onto the most recent matching pageview (sendBeacon on
    unload). Body: {session_id, path|url, duration_ms}."""
    d = request.get_json(silent=True) or {}
    session_id = (d.get("session_id") or "").strip()[:100]
    dur = max(0, min(int(d.get("duration_ms", 0) or 0), 86_400_000))  # cap at 24h
    if not session_id or dur <= 0:
        return jsonify({"ok": True, "skipped": True}), 200
    path = (d.get("path") or "").strip()[:2000]
    if not path and d.get("url"):
        try:
            path = urlparse(d["url"]).path or "/"
        except Exception:
            path = ""
    try:
        execute_db(
            "UPDATE page_views SET duration_ms=%s WHERE id = ("
            "  SELECT id FROM page_views WHERE session_id=%s "
            + ("AND path=%s " if path else "")
            + "  ORDER BY created_at DESC LIMIT 1)",
            (dur, session_id, path) if path else (dur, session_id))
    except Exception as e:
        print(f"[analytics] duration patch failed: {e}")
    return jsonify({"ok": True}), 200


def _days_arg(default=30):
    try:
        return max(1, min(int(request.args.get("days", default)), 365))
    except (TypeError, ValueError):
        return default


@bp.route("/admin/api/analytics", methods=["GET"])
@admin_required
def analytics_summary():
    """Aggregate visitor metrics over the last N days (default 30)."""
    days = _days_arg()
    tid = current_tenant_id()
    since = f"NOW() - INTERVAL '{days} days'"
    base = f"FROM page_views WHERE tenant_id=%s AND created_at >= {since}"

    totals = query_db(
        f"SELECT COUNT(*) AS views, COUNT(DISTINCT session_id) AS sessions, "
        f"COUNT(DISTINCT NULLIF(visitor_id,'')) AS visitors, "
        f"COALESCE(AVG(NULLIF(duration_ms,0)),0)::int AS avg_duration_ms {base}",
        (tid,), fetchone=True) or {}

    def _top(col, limit=10):
        return query_db(
            f"SELECT {col} AS value, COUNT(*) AS n {base} AND {col} <> '' "
            f"GROUP BY {col} ORDER BY n DESC LIMIT %s", (tid, limit)) or []

    return jsonify({
        "days": days,
        "totals": totals,
        "top_pages": _top("path"),
        "referrers": _top("referrer"),
        "utm_sources": _top("utm_source"),
        "devices": _top("device_type"),
        "browsers": _top("browser"),
        "os": _top("os"),
    })


@bp.route("/admin/api/analytics/chart", methods=["GET"])
@admin_required
def analytics_chart():
    """Daily views + unique sessions for the last N days (default 30)."""
    days = _days_arg()
    tid = current_tenant_id()
    rows = query_db(
        "SELECT to_char(date_trunc('day', created_at), 'YYYY-MM-DD') AS day, "
        "COUNT(*) AS views, COUNT(DISTINCT session_id) AS sessions "
        "FROM page_views WHERE tenant_id=%s "
        f"AND created_at >= NOW() - INTERVAL '{days} days' "
        "GROUP BY day ORDER BY day", (tid,)) or []
    return jsonify({"days": days, "series": rows})


@bp.route("/admin/api/analytics/chat", methods=["GET"])
@admin_required
def analytics_chat():
    """Chat volume + per-tool usage parsed from chat_messages.tool_calls_json."""
    days = _days_arg()
    since = f"NOW() - INTERVAL '{days} days'"
    convos = query_db(f"SELECT COUNT(*) AS n FROM chat_conversations "
                      f"WHERE started_at >= {since}", fetchone=True) or {}
    msgs = query_db(
        f"SELECT role, COUNT(*) AS n FROM chat_messages WHERE created_at >= {since} "
        "GROUP BY role") or []
    # Tool usage: unnest the JSON array of tool calls and count by name.
    tools = query_db(
        "SELECT tc->'function'->>'name' AS tool, COUNT(*) AS n "
        "FROM chat_messages m, jsonb_array_elements(m.tool_calls_json) tc "
        f"WHERE m.created_at >= {since} AND jsonb_typeof(m.tool_calls_json)='array' "
        "AND tc->'function'->>'name' IS NOT NULL "
        "GROUP BY tool ORDER BY n DESC") or []
    return jsonify({"days": days, "conversations": convos.get("n", 0),
                    "messages_by_role": msgs, "tool_usage": tools})


@bp.route("/admin/api/analytics/forms", methods=["GET"])
@admin_required
def analytics_forms():
    """Submission counts per form over the last N days."""
    days = _days_arg()
    rows = query_db(
        "SELECT f.id, f.name, COUNT(s.id) AS submissions "
        "FROM custom_forms f LEFT JOIN form_submissions s ON s.form_id=f.id "
        f"AND s.submitted_at >= NOW() - INTERVAL '{days} days' "
        "GROUP BY f.id, f.name ORDER BY submissions DESC") or []
    return jsonify({"days": days, "forms": rows})
