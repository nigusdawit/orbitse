"""admin/shell.py — Workspaces shell chrome: cross-cutting read APIs (task 093, gap §0).

P1 = GET /admin/api/nav-counts: live badge counts for the Workspaces sub-nav, keyed by
each tab's data-testid so the front-end (workspaces.js `navItem`) maps straight onto its
items.

Strictly additive + FAIL-OPEN: every count is its own try/except (a missing/unmigrated
table → that key is simply omitted, never a 500), and the route returns {"counts": {...}}
even on total failure. A 30s in-process TTL cache (one slot per privilege level) keeps the
header poll off the DB. PII domains (leads / CRM) are counted ONLY for a super-admin
session — the route is `@admin_required` (which only proves "an admin is logged in"), so
the PII gate is enforced IN-BODY via `_is_super_admin()`, mirroring admin/crm.py's
super-admin discipline.

Silo deploy (one DB per tenant; all rows tenant_id=1) → a plain COUNT(*) already IS the
tenant's count, so no tenant filter is needed for these aggregates.

Imports come from core (never app — that would be circular). Registered in app.py via
app.register_blueprint(shell_bp), right after crm_bp.
"""
import os
import time
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify

from core import (
    query_db,
    admin_required,
    _is_super_admin,
    _require_super_admin_role,
    current_tenant_id,
)

shell_bp = Blueprint("shell", __name__)

# (testid, table, pii). Table names are HARD-CODED here (never user input), so they're
# safe to interpolate into the COUNT query. pii=True domains hold visitor PII and are
# counted only for a super-admin (same boundary admin/crm.py enforces on the full rows).
_COUNT_SOURCES = (
    ("tab-crm",           "leads",              True),
    ("tab-chat-history",  "chat_conversations", False),
    ("tab-orders",        "orders",             False),
    ("tab-products",      "products",           False),
    ("tab-pages",         "pages",              False),
    ("tab-offers",        "offers",             False),
    ("tab-forms",         "form_submissions",   False),
    ("tab-messaging",     "subscribers",        False),
    ("tab-blog",          "blog_posts",         False),
    ("tab-events",        "events",             False),
    ("tab-automations",   "automations",        False),
)

# 30s TTL cache, one slot per privilege level (super vs not — the PII domains differ).
# Mirrors app.py's _CHAT_ONLY_CACHE val/ts idiom; 30s is our deliberate choice (the
# chat-only precedent is 10s).
_NAV_COUNTS_TTL_SEC = 30.0
_NAV_COUNTS_CACHE = {}  # bool(is_super) -> {"val": dict, "ts": float}


def _count_table(table):
    """COUNT(*) for one HARD-CODED table name; None on any error (fail-open)."""
    try:
        row = query_db("SELECT COUNT(*) AS n FROM " + table, fetchone=True)
        if isinstance(row, dict):
            return int(row.get("n") or 0)
    except Exception:
        return None
    return None


def _compute_counts(is_super):
    """Build the testid->count map, skipping PII domains for non-super sessions and
    omitting any domain whose count errored (fail-open)."""
    out = {}
    for testid, table, pii in _COUNT_SOURCES:
        if pii and not is_super:
            continue
        n = _count_table(table)
        if n is not None:
            out[testid] = n
    return out


@shell_bp.route("/admin/api/nav-counts", methods=["GET"])
@admin_required
def admin_nav_counts():
    """Live sub-nav badge counts keyed by tab data-testid. 30s-cached per privilege
    level; fully fail-open (always returns {"counts": {...}})."""
    try:
        is_super = bool(_is_super_admin())
    except Exception:
        is_super = False
    now = time.time()
    slot = _NAV_COUNTS_CACHE.get(is_super)
    if slot and slot.get("val") is not None and (now - slot["ts"]) < _NAV_COUNTS_TTL_SEC:
        return jsonify({"counts": slot["val"]})
    try:
        counts = _compute_counts(is_super)
    except Exception:
        counts = {}
    _NAV_COUNTS_CACHE[is_super] = {"val": counts, "ts": now}
    return jsonify({"counts": counts})


# Settings aren't a table — a small static label->tab map so "search … settings"
# (the gap-doc placeholder) lands the user on the right tab. The value is the owning
# tab's data-testid; the front-end clicks that real .tab-btn, same as every result.
_SETTING_TARGETS = (
    ("Appearance & theme", "tab-appearance"),
    ("Plans & features", "tab-plans-features"),
    ("Secrets & API keys", "tab-secrets"),
    ("Business info", "tab-business-info"),
    ("Site settings", "tab-settings"),
    ("Stripe & payments", "tab-stripe"),
    ("AI control", "tab-ai-control"),
    ("AI prompts", "tab-ai-prompts"),
    ("Developer console", "tab-developer"),
    ("Cost & usage", "tab-cost"),
)


@shell_bp.route("/admin/api/search", methods=["GET"])
@admin_required
def admin_global_search():
    """Cross-record search for the ⌘K palette. Returns grouped results keyed to the
    owning tab's data-testid (the front-end clicks that real .tab-btn — no new page
    routes, no SPA changes). PII domains (leads / callbacks) are included ONLY for a
    super-admin (in-body gate, mirrors admin/crm.py). FAIL-OPEN: q<2 chars →
    {"groups":[]} fast; each domain query in its own try/except; the route never 500s.
    `q` is always a BOUND ILIKE parameter (never interpolated) — no SQL injection."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"groups": []})
    try:
        per = max(1, min(int(request.args.get("limit") or 5), 10))  # per-domain cap
    except (TypeError, ValueError):
        per = 5
    like = "%" + q + "%"
    try:
        is_super = bool(_is_super_admin())
    except Exception:
        is_super = False

    groups = []

    def _grp(gtype, label, items):
        if items:
            groups.append({"type": gtype, "label": label, "items": items})

    def _sub(*parts):
        return " · ".join([str(p) for p in parts if p])

    # --- PII domains: super-admin only (visitor sales data) ---
    if is_super:
        try:
            rows = query_db(
                "SELECT id, name, email, interest FROM leads "
                "WHERE name ILIKE %s OR email ILIKE %s OR phone ILIKE %s OR interest ILIKE %s "
                "ORDER BY id DESC LIMIT %s", (like, like, like, like, per)) or []
            _grp("lead", "Leads", [
                {"label": r.get("name") or r.get("email") or ("Lead #%s" % r.get("id")),
                 "sublabel": _sub(r.get("email"), r.get("interest")),
                 "tabAction": "tab-crm", "recordId": r.get("id")} for r in rows])
        except Exception:
            pass
        try:
            rows = query_db(
                "SELECT id, name, phone, reason FROM callback_requests "
                "WHERE name ILIKE %s OR phone ILIKE %s OR reason ILIKE %s "
                "ORDER BY id DESC LIMIT %s", (like, like, like, per)) or []
            _grp("callback", "Callbacks", [
                {"label": r.get("name") or r.get("phone") or ("Callback #%s" % r.get("id")),
                 "sublabel": _sub(r.get("phone"), r.get("reason")),
                 "tabAction": "tab-crm", "recordId": r.get("id")} for r in rows])
        except Exception:
            pass

    # --- non-PII domains: any logged-in admin ---
    try:
        rows = query_db(
            "SELECT id, slug, title FROM pages WHERE title ILIKE %s OR slug ILIKE %s "
            "ORDER BY sort_order, id LIMIT %s", (like, like, per)) or []
        _grp("page", "Pages", [
            {"label": r.get("title") or r.get("slug"), "sublabel": "/" + (r.get("slug") or ""),
             "tabAction": "tab-pages", "recordId": r.get("id")} for r in rows])
    except Exception:
        pass
    try:
        rows = query_db(
            "SELECT id, slug, name FROM products WHERE name ILIKE %s OR slug ILIKE %s "
            "ORDER BY sort_order, id LIMIT %s", (like, like, per)) or []
        _grp("product", "Products", [
            {"label": r.get("name") or r.get("slug"), "sublabel": "/" + (r.get("slug") or ""),
             "tabAction": "tab-products", "recordId": r.get("id")} for r in rows])
    except Exception:
        pass
    try:
        rows = query_db(
            "SELECT id, order_number, customer_name FROM orders "
            "WHERE order_number ILIKE %s OR customer_name ILIKE %s OR customer_email ILIKE %s "
            "ORDER BY created_at DESC, id DESC LIMIT %s", (like, like, like, per)) or []
        _grp("order", "Orders", [
            {"label": r.get("order_number") or ("Order #%s" % r.get("id")),
             "sublabel": r.get("customer_name") or "",
             "tabAction": "tab-orders", "recordId": r.get("id")} for r in rows])
    except Exception:
        pass
    try:
        rows = query_db(
            "SELECT id, title FROM offers WHERE title ILIKE %s OR description ILIKE %s OR code ILIKE %s "
            "ORDER BY id DESC LIMIT %s", (like, like, like, per)) or []
        _grp("offer", "Offers", [
            {"label": r.get("title") or ("Offer #%s" % r.get("id")), "sublabel": "",
             "tabAction": "tab-offers", "recordId": r.get("id")} for r in rows])
    except Exception:
        pass

    # --- settings (static label map, no DB) ---
    try:
        ql = q.lower()
        hits = [(lbl, tid) for (lbl, tid) in _SETTING_TARGETS if ql in lbl.lower()][:per]
        _grp("setting", "Settings", [
            {"label": lbl, "sublabel": "", "tabAction": tid, "recordId": None}
            for (lbl, tid) in hits])
    except Exception:
        pass

    return jsonify({"groups": groups})


# ===========================================================================
# Home command center (task 094, gap §1) — super-admin overview aggregations.
# All read-only, additive, fail-open (every source in its own try/except). They
# touch CRM PII + revenue, so each route gates on _require_super_admin_role() in
# the body (mirrors admin/crm.py), not just @admin_required.
# ===========================================================================

# "Hot" uncontacted-lead threshold for the needs-attention widget. The gap doc
# §2.8 says ≥80; we start at 70 to catch more (one constant, easily tuned).
_HOT_LEAD_SCORE = 70


@shell_bp.route("/admin/api/overview/attention", methods=["GET"])
@admin_required
def admin_overview_attention():
    """Needs-attention action list for the Home command center (gap §1.1). Super-admin
    only. Each source in its own try/except → fail-open (one source failing drops one
    item, never the response). Items are deep-linkable: {kind, severity, title, detail,
    count, tab, loader}. An empty list (a quiet command center) is the healthy state."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    tid = current_tenant_id()
    items = []

    # 1) Hot uncontacted leads (>1h old, lead_score >= threshold via visitor_profiles).
    try:
        r = query_db(
            "SELECT COUNT(*) AS n FROM leads l "
            "LEFT JOIN visitor_profiles vp "
            "  ON vp.visitor_id = l.visitor_id AND vp.tenant_id = l.tenant_id "
            "WHERE l.tenant_id = %s AND l.status = 'new' "
            "  AND l.created_at < NOW() - INTERVAL '1 hour' "
            "  AND COALESCE(vp.lead_score, 0) >= %s",
            (tid, _HOT_LEAD_SCORE), fetchone=True) or {}
        n = int(r.get("n") or 0)
        if n:
            items.append({
                "kind": "hot_leads_uncontacted", "severity": "warn", "count": n,
                "title": "%d hot lead%s waiting > 1h" % (n, "" if n == 1 else "s"),
                "detail": "Uncontacted, lead score ≥ %d" % _HOT_LEAD_SCORE,
                "tab": "crm", "loader": "loadCrm"})
    except Exception:
        pass

    # 2) Missing required / recommended keys — reuse the secrets-banner filter
    #    (env_manager is a standalone module; import locally to avoid a top-level dep).
    try:
        import env_manager
        rows = env_manager.get_status() or []
        req = [r for r in rows if (not r.get("set")) and r.get("level") == "required"]
        rec = [r for r in rows if (not r.get("set")) and r.get("level") == "recommended"]
        if req:
            items.append({
                "kind": "missing_required_keys", "severity": "critical", "count": len(req),
                "title": "%d required key%s not configured" % (len(req), "" if len(req) == 1 else "s"),
                "detail": ", ".join([str(r.get("key")) for r in req][:5]),
                "tab": "secrets", "loader": "loadSecrets"})
        if rec:
            items.append({
                "kind": "missing_recommended_keys", "severity": "info", "count": len(rec),
                "title": "%d recommended key%s not set" % (len(rec), "" if len(rec) == 1 else "s"),
                "detail": ", ".join([str(r.get("key")) for r in rec][:5]),
                "tab": "secrets", "loader": "loadSecrets"})
    except Exception:
        pass

    # 3) Drafts / unpublished content (one combined item).
    try:
        d_blog = int((query_db("SELECT COUNT(*) AS n FROM blog_posts WHERE status='draft'",
                               fetchone=True) or {}).get("n") or 0)
    except Exception:
        d_blog = 0
    try:
        d_pages = int((query_db("SELECT COUNT(*) AS n FROM pages WHERE enabled = FALSE",
                                fetchone=True) or {}).get("n") or 0)
    except Exception:
        d_pages = 0
    drafts = d_blog + d_pages
    if drafts:
        items.append({
            "kind": "draft_content", "severity": "info", "count": drafts,
            "title": "%d draft / unpublished item%s" % (drafts, "" if drafts == 1 else "s"),
            "detail": "%d blog draft(s), %d hidden page(s)" % (d_blog, d_pages),
            "tab": "blog", "loader": "loadBlog"})

    # 4) Failed automations in the last 7 days.
    try:
        r = query_db(
            "SELECT COUNT(*) AS n FROM automation_runs "
            "WHERE status='failed' AND queued_at >= NOW() - INTERVAL '7 days'",
            fetchone=True) or {}
        n = int(r.get("n") or 0)
        if n:
            items.append({
                "kind": "failed_automations", "severity": "warn", "count": n,
                "title": "%d automation run%s failed (7d)" % (n, "" if n == 1 else "s"),
                "detail": "Check the Automations log",
                "tab": "automations", "loader": "loadAutomations"})
    except Exception:
        pass

    return jsonify({"ok": True, "items": items})


@shell_bp.route("/admin/api/integrations", methods=["GET"])
@admin_required
def admin_integrations():
    """Integrations hub (task 098, gap §6.1): one status grid aggregating each
    integration's configured/missing state from the loaded env (env_manager writes
    secrets into os.environ at boot) + the mcp_servers table. Super-admin only
    (reveals which secrets are set); MCP count is its own fail-open try/except."""
    guard = _require_super_admin_role()
    if guard:
        return guard

    def _set(*names):
        return any((os.environ.get(n) or "").strip() for n in names)

    specs = [
        ("anthropic", "Anthropic (Claude)", "AI", _set("ANTHROPIC_API_KEY"), "ANTHROPIC_API_KEY"),
        ("openai", "OpenAI", "AI", _set("OPENAI_API_KEY", "AI_INTEGRATIONS_OPENAI_API_KEY"), "OPENAI_API_KEY"),
        ("stripe", "Stripe (payments)", "Commerce",
         _set("STRIPE_SECRET_KEY", "STRIPE_TEST_SECRET_KEY"), "STRIPE_SECRET_KEY"),
        ("twilio", "Twilio (SMS / voice)", "Messaging",
         _set("TWILIO_ACCOUNT_SID") and _set("TWILIO_AUTH_TOKEN"), "TWILIO_ACCOUNT_SID + AUTH_TOKEN"),
        ("resend", "Resend (email)", "Messaging", _set("RESEND_API_KEY"), "RESEND_API_KEY"),
    ]
    items = [{"key": k, "label": lbl, "category": cat, "configured": bool(ok), "hint": hint}
             for (k, lbl, cat, ok, hint) in specs]
    # MCP connectors — count enabled servers (its own try/except → fail-open).
    try:
        n = int((query_db("SELECT COUNT(*) AS n FROM mcp_servers WHERE enabled = TRUE",
                           fetchone=True) or {}).get("n") or 0)
        items.append({"key": "mcp", "label": "MCP connectors", "category": "AI",
                      "configured": n > 0, "hint": ("%d connected" % n) if n else "none connected"})
    except Exception:
        items.append({"key": "mcp", "label": "MCP connectors", "category": "AI",
                      "configured": False, "hint": ""})
    return jsonify({"integrations": items,
                    "configured": sum(1 for i in items if i["configured"]),
                    "total": len(items)})


@shell_bp.route("/admin/api/voice-stats", methods=["GET"])
@admin_required
def admin_voice_stats():
    """Voice call KPIs for the CRM Voice pane (task 098, gap §3.6): calls in the last
    7 days, total, a status breakdown, and a derived 'missed' count. Super-admin only
    (call metadata); fail-open to zeros. NOTE: voice_calls has no duration or
    booking-link column, so 'Avg handle' + 'Booked on call' aren't derivable here
    without a schema add — deliberately omitted rather than faked."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    out = {"calls_7d": 0, "total": 0, "by_status": {}, "missed": 0}
    try:
        out["calls_7d"] = int((query_db(
            "SELECT COUNT(*) AS n FROM voice_calls WHERE created_at >= NOW() - INTERVAL '7 days'",
            fetchone=True) or {}).get("n") or 0)
        out["total"] = int((query_db("SELECT COUNT(*) AS n FROM voice_calls",
                                     fetchone=True) or {}).get("n") or 0)
        rows = query_db("SELECT COALESCE(status,'') AS status, COUNT(*) AS n "
                        "FROM voice_calls GROUP BY status") or []
        bs = {}
        for r in rows:
            bs[(r.get("status") or "unknown").lower()] = int(r.get("n") or 0)
        out["by_status"] = bs
        out["missed"] = sum(bs.get(k, 0) for k in
                            ("missed", "no-answer", "no_answer", "failed", "busy"))
    except Exception:
        pass   # fail-open → zeros
    return jsonify(out)


@shell_bp.route("/admin/api/campaign-stats", methods=["GET"])
@admin_required
def admin_campaign_stats():
    """Campaign analytics (task 099, gap §5.1/5.2): per-campaign sent/opens/clicks +
    open/click rates from messaging_log, plus 30-day KPIs. Super-admin only; fail-open.
    Revenue attribution is omitted (no campaign→utm link is modeled — surfacing a faked
    number would be dishonest)."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    campaigns = []
    kpis = {"sent_30d": 0, "open_rate": 0.0, "click_rate": 0.0, "campaigns_30d": 0}
    try:
        rows = query_db(
            "SELECT c.id, c.name, c.channel, c.status, c.created_at, "
            "       COUNT(l.id) AS sent, COUNT(l.opened_at) AS opens, COUNT(l.clicked_at) AS clicks "
            "FROM messaging_campaigns c "
            "LEFT JOIN messaging_log l ON l.campaign_id = c.id AND l.is_test = FALSE "
            "GROUP BY c.id, c.name, c.channel, c.status, c.created_at "
            "ORDER BY c.id DESC LIMIT 100") or []
        for r in rows:
            sent = int(r.get("sent") or 0)
            opens = int(r.get("opens") or 0)
            clicks = int(r.get("clicks") or 0)
            campaigns.append({
                "id": r["id"], "name": r.get("name") or "", "channel": r.get("channel") or "",
                "status": r.get("status") or "", "sent": sent, "opens": opens, "clicks": clicks,
                "open_rate": round(100.0 * opens / sent, 1) if sent else 0.0,
                "click_rate": round(100.0 * clicks / sent, 1) if sent else 0.0,
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            })
    except Exception:
        pass
    try:
        k = query_db(
            "SELECT COUNT(*) AS sent, COUNT(opened_at) AS opens, COUNT(clicked_at) AS clicks "
            "FROM messaging_log WHERE is_test = FALSE AND created_at >= NOW() - INTERVAL '30 days'",
            fetchone=True) or {}
        sent = int(k.get("sent") or 0)
        kpis["sent_30d"] = sent
        kpis["open_rate"] = round(100.0 * int(k.get("opens") or 0) / sent, 1) if sent else 0.0
        kpis["click_rate"] = round(100.0 * int(k.get("clicks") or 0) / sent, 1) if sent else 0.0
        kpis["campaigns_30d"] = int((query_db(
            "SELECT COUNT(*) AS n FROM messaging_campaigns WHERE created_at >= NOW() - INTERVAL '30 days'",
            fetchone=True) or {}).get("n") or 0)
    except Exception:
        pass
    return jsonify({"campaigns": campaigns, "kpis": kpis})


@shell_bp.route("/admin/api/subscriber-lists", methods=["GET"])
@admin_required
def admin_subscriber_lists():
    """Subscribers → Lists view + opt-in KPIs (task 100, gap §2.5): per-list counts +
    email/SMS opt-in % and unsubscribe %, plus overall KPIs. Aggregate only (no
    individual PII), so @admin_required like the Subscribers tab itself. Fail-open."""
    out = {"lists": [], "kpis": {"total": 0, "email_pct": 0.0, "sms_pct": 0.0, "unsub_pct": 0.0}}
    try:
        rows = query_db(
            "SELECT COALESCE(NULLIF(list_name,''),'default') AS list_name, COUNT(*) AS total, "
            "       COUNT(*) FILTER (WHERE opt_in_email) AS email_in, "
            "       COUNT(*) FILTER (WHERE opt_in_sms) AS sms_in, "
            "       COUNT(*) FILTER (WHERE unsubscribed_at IS NOT NULL) AS unsub "
            "FROM subscribers GROUP BY 1 ORDER BY total DESC") or []
        lists, T, E, S, U = [], 0, 0, 0, 0
        for r in rows:
            t = int(r.get("total") or 0); e = int(r.get("email_in") or 0)
            s = int(r.get("sms_in") or 0); u = int(r.get("unsub") or 0)
            T += t; E += e; S += s; U += u
            lists.append({"name": r.get("list_name") or "default", "total": t,
                          "email_pct": round(100.0 * e / t, 1) if t else 0.0,
                          "sms_pct": round(100.0 * s / t, 1) if t else 0.0,
                          "unsub_pct": round(100.0 * u / t, 1) if t else 0.0})
        out["lists"] = lists
        out["kpis"] = {"total": T,
                       "email_pct": round(100.0 * E / T, 1) if T else 0.0,
                       "sms_pct": round(100.0 * S / T, 1) if T else 0.0,
                       "unsub_pct": round(100.0 * U / T, 1) if T else 0.0}
    except Exception:
        pass
    return jsonify(out)


# Content tables whose edits read as "page/content changes" (not raw config churn).
_FEED_CONTENT_TABLES = (
    "pages", "blog_posts", "page_sections", "faqs", "testimonials",
    "team_members", "events", "products", "gallery_cards", "experiences",
)


@shell_bp.route("/admin/api/activity-feed", methods=["GET"])
@admin_required
def admin_activity_feed():
    """Cross-module business-event stream for the Home command center (gap §1.2).
    Super-admin only. Per-source SELECT…LIMIT then a Python merge-sort by EPOCH (so we
    never compare tz-aware vs naive datetimes); each source in its own try/except
    (fail-open). NEVER selects secret/PII blobs (snapshot_json / final_answer /
    user_message). Query: ?limit= (default 30, max 100), optional ?kinds=order,lead,…"""
    guard = _require_super_admin_role()
    if guard:
        return guard
    tid = current_tenant_id()
    try:
        limit = max(1, min(int(request.args.get("limit") or 30), 100))
    except (TypeError, ValueError):
        limit = 30
    kinds_arg = (request.args.get("kinds") or "").strip()
    want = set(k.strip() for k in kinds_arg.split(",") if k.strip()) if kinds_arg else None

    events = []

    def _src(kind, sql, params, build):
        if want is not None and kind not in want:
            return
        try:
            for r in (query_db(sql, params) or []):
                e = build(r)
                if e and e.get("_epoch") is not None:
                    e["kind"] = kind
                    events.append(e)
        except Exception:
            pass

    _src("order",
         "SELECT order_number, total_cents, customer_email, "
         "EXTRACT(EPOCH FROM COALESCE(paid_at, created_at)) AS _epoch "
         "FROM orders WHERE status IN ('paid','fulfilled','completed') "
         "ORDER BY COALESCE(paid_at, created_at) DESC LIMIT %s", (limit,),
         lambda r: {"_epoch": r.get("_epoch"),
                    "title": "Order %s paid" % (r.get("order_number") or ""),
                    "detail": "$%.2f · %s" % (float(r.get("total_cents") or 0) / 100.0, r.get("customer_email") or ""),
                    "tab": "orders", "loader": "loadOrders"})

    _src("lead",
         "SELECT name, email, interest, source, EXTRACT(EPOCH FROM created_at) AS _epoch "
         "FROM leads WHERE tenant_id=%s ORDER BY created_at DESC LIMIT %s", (tid, limit),
         lambda r: {"_epoch": r.get("_epoch"),
                    "title": "New lead: %s" % (r.get("name") or r.get("email") or "—"),
                    "detail": " · ".join([x for x in [r.get("interest"), r.get("source")] if x]),
                    "tab": "crm", "loader": "loadCrm"})

    _src("callback",
         "SELECT name, reason, EXTRACT(EPOCH FROM created_at) AS _epoch "
         "FROM callback_requests WHERE tenant_id=%s ORDER BY created_at DESC LIMIT %s", (tid, limit),
         lambda r: {"_epoch": r.get("_epoch"),
                    "title": "Callback requested",
                    "detail": " · ".join([x for x in [r.get("name"), r.get("reason")] if x]),
                    "tab": "crm", "loader": "loadCrm"})

    _src("meeting",
         "SELECT name, requested_time, status, EXTRACT(EPOCH FROM created_at) AS _epoch "
         "FROM meetings WHERE tenant_id=%s ORDER BY created_at DESC LIMIT %s", (tid, limit),
         lambda r: {"_epoch": r.get("_epoch"),
                    "title": "Meeting %s" % (r.get("status") or "requested"),
                    "detail": " · ".join([x for x in [r.get("name"), r.get("requested_time")] if x]),
                    "tab": "crm", "loader": "loadCrm"})

    # page/content edits — title from table_name+row_id ONLY; snapshot_json never read.
    _src("page_edit",
         "SELECT table_name, row_id, EXTRACT(EPOCH FROM created_at) AS _epoch "
         "FROM admin_setting_snapshots WHERE table_name = ANY(%s) "
         "ORDER BY created_at DESC LIMIT %s", (list(_FEED_CONTENT_TABLES), limit),
         lambda r: {"_epoch": r.get("_epoch"),
                    "title": "Edited %s" % (r.get("table_name") or "content"),
                    "detail": ("#%s" % r.get("row_id")) if r.get("row_id") else "",
                    "tab": "changes", "loader": ""})

    # notable AI events — status/model ONLY; final_answer/user_message never read.
    _src("ai_event",
         "SELECT status, model, EXTRACT(EPOCH FROM created_at) AS _epoch "
         "FROM ai_activity_log WHERE tenant_id=%s "
         "AND (COALESCE(status,'') NOT IN ('', 'ok') OR COALESCE(error_text,'') <> '') "
         "ORDER BY created_at DESC LIMIT %s", (tid, limit),
         lambda r: {"_epoch": r.get("_epoch"),
                    "title": "AI %s" % (r.get("status") or "event"),
                    "detail": r.get("model") or "",
                    "tab": "ai-activity", "loader": "loadAiActivity"})

    events.sort(key=lambda e: e["_epoch"], reverse=True)
    out = []
    for e in events[:limit]:
        try:
            e["ts"] = datetime.fromtimestamp(float(e.pop("_epoch")), timezone.utc).isoformat()
        except Exception:
            e["ts"] = None
        out.append(e)
    return jsonify({"ok": True, "events": out})


# Range key → window in days (None = all-time). Small local helper (no app.py import).
_RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90}


@shell_bp.route("/admin/api/overview/revenue-by-source", methods=["GET"])
@admin_required
def admin_revenue_by_source():
    """Revenue segmented by the revenue MODULES that actually exist in the schema —
    Store orders / Service bookings / Event tickets — NOT the mock's fictional
    catering/membership/gift categories (no such tables). + an optional UTM-source
    drill-down for bookings (the only attribution column in the schema). Super-admin
    only; every source in its own try/except (fail-open). ?range=7d|30d|90d|all.
    Table/column names are hard-coded literals; only the day-window is parameterized."""
    guard = _require_super_admin_role()
    if guard:
        return guard
    rk = (request.args.get("range") or "7d").strip().lower()
    days = None if rk == "all" else _RANGE_DAYS.get(rk, 7)

    sources = []
    total = {"v": 0.0}

    def _revenue(key, label, table, rev_col, base_where):
        try:
            sql = ("SELECT COALESCE(SUM(%s),0) AS rev, COUNT(*) AS n FROM %s WHERE %s"
                   % (rev_col, table, base_where))
            params = ()
            if days is not None:
                sql += " AND created_at >= NOW() - (%s * INTERVAL '1 day')"
                params = (days,)
            r = query_db(sql, params, fetchone=True) or {}
            rev = round(float(r.get("rev") or 0) / 100.0, 2)
            sources.append({"key": key, "label": label, "revenue": rev, "count": int(r.get("n") or 0)})
            total["v"] += rev
        except Exception:
            pass

    _revenue("store", "Store orders", "orders", "total_cents",
             "status IN ('paid','fulfilled','completed')")
    _revenue("bookings", "Service bookings", "service_bookings", "amount_paid_cents",
             "amount_paid_cents > 0")
    _revenue("events", "Event tickets", "event_rsvps", "payment_amount",
             "payment_status = 'paid'")

    # Optional UTM-source drill-down (bookings — the only table with attribution).
    by_utm = []
    try:
        sql = ("SELECT utm_source AS source, COALESCE(SUM(amount_paid_cents),0) AS rev "
               "FROM service_bookings "
               "WHERE amount_paid_cents > 0 AND COALESCE(utm_source,'') <> ''")
        params = ()
        if days is not None:
            sql += " AND created_at >= NOW() - (%s * INTERVAL '1 day')"
            params = (days,)
        sql += " GROUP BY utm_source ORDER BY rev DESC LIMIT 8"
        for r in (query_db(sql, params) or []):
            by_utm.append({"source": r.get("source") or "—",
                           "revenue": round(float(r.get("rev") or 0) / 100.0, 2)})
    except Exception:
        by_utm = []

    return jsonify({"ok": True, "range": rk, "currency": "USD",
                    "sources": sources, "total": round(total["v"], 2), "by_utm": by_utm})
