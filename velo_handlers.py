"""
VELO Command Handlers — concrete capabilities exposed to VELO Master.

Each @velo_command function becomes a tool VELO can call. Importing this
module from app.py is what triggers the @velo_command decorators to
populate the registry in velo_endpoints._command_handlers.

All handler bodies are adapted to this codebase's actual schema and use
the existing psycopg2 helpers (query_db / execute_db). Plan and feature
state hooks into the existing tenant_features system rather than
introducing a parallel feature_flags table.

Phase 2 handlers (the original 7):
    get_analytics, get_system_status, manage_features, get_plans,
    get_faq, update_faq, get_users.

Phase 3 expansion (this turn — full surface):
    Reads:        get_subscriptions, get_visitor_sessions, get_chat_history,
                  get_content, get_orders, get_audit_log, get_settings,
                  get_costs, get_form_submissions, get_voice_logs,
                  get_skills, get_mcp_servers
    Writes:       update_content, update_settings, manage_user,
                  send_chat_message, toggle_skill
    Outbound:     send_email (gated), send_sms (gated),
                  trigger_weekly_digest (gated)
    Destructive:  manage_plan (gated), delete_content (gated),
                  refund_order (gated)

`@velo_command(..., requires_confirmation=True)` opts a handler into the
two-step confirm-token flow defined in velo_endpoints — the handler
body itself never has to think about it.
"""

from velo_endpoints import velo_command


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_PERIOD_TO_INTERVAL = {
    "today": "1 day",
    "day":   "1 day",
    "week":  "7 days",
    "month": "30 days",
    "year":  "365 days",
}


def _interval(period):
    """Map a period string to a Postgres INTERVAL literal. Defaults to week."""
    return _PERIOD_TO_INTERVAL.get((period or "week").lower(), "7 days")


def _safe_int(v, default=None, lo=None, hi=None):
    """Coerce v to int with bounds. Returns `default` when v is missing or junk.

    Used to keep handlers from raising 500s on malformed VELO params; the
    handler can return a clean error payload instead.
    """
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


# ---------------------------------------------------------------------------
# get_analytics
# ---------------------------------------------------------------------------
@velo_command(
    "get_analytics",
    description="Site analytics for a time range: signups, revenue, page views, chat sessions.",
    params_schema={
        "type": "object",
        "properties": {
            "period": {
                "type": "string",
                "description": "today, week, month, or year. Defaults to week.",
            },
            "metrics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional subset of metrics to include. Defaults to all.",
            },
        },
    },
)
def get_analytics(params):
    from app import query_db
    period = (params or {}).get("period", "week")
    requested = set((params or {}).get("metrics") or [])
    interval = _interval(period)
    out = {"period": period}

    def want(name):
        return not requested or name in requested

    if want("signups"):
        row = query_db(
            f"SELECT COUNT(*) AS n FROM customers "
            f"WHERE created_at >= NOW() - INTERVAL '{interval}'",
            fetchone=True,
        )
        out["signups"] = int(row["n"]) if row else 0

    if want("revenue_cents") or want("revenue"):
        row = query_db(
            f"SELECT COALESCE(SUM(total_cents), 0) AS cents, COUNT(*) AS n "
            f"FROM orders "
            f"WHERE status = 'paid' "
            f"  AND paid_at IS NOT NULL "
            f"  AND paid_at >= NOW() - INTERVAL '{interval}'",
            fetchone=True,
        )
        cents = int(row["cents"]) if row else 0
        out["revenue_cents"] = cents
        out["revenue_dollars"] = round(cents / 100.0, 2)
        out["paid_orders"] = int(row["n"]) if row else 0

    if want("page_views"):
        row = query_db(
            f"SELECT COUNT(*) AS n, COUNT(DISTINCT session_id) AS sessions "
            f"FROM page_views "
            f"WHERE created_at >= NOW() - INTERVAL '{interval}'",
            fetchone=True,
        )
        out["page_views"] = int(row["n"]) if row else 0
        out["unique_sessions"] = int(row["sessions"]) if row else 0

    if want("chat_sessions"):
        row = query_db(
            f"SELECT COUNT(*) AS n FROM chat_conversations "
            f"WHERE started_at >= NOW() - INTERVAL '{interval}'",
            fetchone=True,
        )
        out["chat_sessions"] = int(row["n"]) if row else 0

    return out


# ---------------------------------------------------------------------------
# get_system_status
# ---------------------------------------------------------------------------
@velo_command(
    "get_system_status",
    description="App health snapshot: DB connectivity, table count, uptime, key counters.",
)
def get_system_status(params):
    from app import query_db, VELO_APP_START_TIME
    import time as _time

    status = {"db": "ok"}

    # DB ping
    try:
        ping = query_db("SELECT 1 AS one", fetchone=True)
        if not ping or ping.get("one") != 1:
            status["db"] = "error"
    except Exception as e:
        status["db"] = f"error: {e}"

    # Table count (public schema)
    try:
        row = query_db(
            "SELECT COUNT(*) AS n FROM information_schema.tables "
            "WHERE table_schema = 'public'",
            fetchone=True,
        )
        status["table_count"] = int(row["n"]) if row else 0
    except Exception as e:
        status["table_count_error"] = str(e)

    # Coarse counters
    for label, sql in (
        ("customers_total",   "SELECT COUNT(*) AS n FROM customers"),
        ("orders_total",      "SELECT COUNT(*) AS n FROM orders"),
        ("paid_orders_total", "SELECT COUNT(*) AS n FROM orders WHERE status='paid'"),
        ("page_views_total",  "SELECT COUNT(*) AS n FROM page_views"),
        ("chat_sessions_total","SELECT COUNT(*) AS n FROM chat_conversations"),
        ("audit_log_total",   "SELECT COUNT(*) AS n FROM velo_audit_log"),
    ):
        try:
            row = query_db(sql, fetchone=True)
            status[label] = int(row["n"]) if row else 0
        except Exception as e:
            status[label] = f"error: {e}"

    # Recent VELO command errors (last 24h)
    try:
        row = query_db(
            "SELECT COUNT(*) AS n FROM velo_audit_log "
            "WHERE status = 'error' AND created_at >= NOW() - INTERVAL '1 day'",
            fetchone=True,
        )
        status["velo_errors_24h"] = int(row["n"]) if row else 0
    except Exception as e:
        status["velo_errors_24h_error"] = str(e)

    # Uptime
    uptime_seconds = int(_time.time() - VELO_APP_START_TIME)
    status["uptime_seconds"] = uptime_seconds
    status["uptime_hours"] = round(uptime_seconds / 3600.0, 2)

    return status


# ---------------------------------------------------------------------------
# manage_features  — hooks into the existing tenant_features system
# ---------------------------------------------------------------------------
@velo_command(
    "manage_features",
    description="Get, set, bulk-set, or apply a plan preset to feature flags for this install.",
    params_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "get | set | bulk_set | apply_plan",
            },
            "feature": {"type": "string", "description": "feature name for action=set"},
            "enabled": {"type": "boolean", "description": "value for action=set"},
            "features": {
                "type": "object",
                "description": "for action=bulk_set: {feature_name: bool, ...}",
            },
            "plan": {
                "type": "string",
                "description": "for action=apply_plan: solo | growth | enterprise",
            },
        },
        "required": ["action"],
    },
)
def manage_features(params):
    from app import (
        list_tenant_features,
        set_tenant_feature,
        current_tenant_id,
        _FEATURE_NAMES,
        _FEATURE_REGISTRY,
    )

    action = (params or {}).get("action", "get")
    tenant_id = current_tenant_id()

    if action == "get":
        return {
            "tenant_id": tenant_id,
            "features": list_tenant_features(tenant_id),
        }

    if action == "set":
        feature = (params or {}).get("feature", "")
        enabled = bool((params or {}).get("enabled", False))
        if not feature:
            return {"error": "feature name required for action=set"}
        if feature not in _FEATURE_NAMES:
            return {
                "error": f"Unknown feature: {feature}",
                "available_features": sorted(_FEATURE_NAMES),
            }
        new_value = set_tenant_feature(feature, enabled, tenant_id, note="set via velo")
        return {"feature": feature, "enabled": new_value, "updated": True}

    if action == "bulk_set":
        features = (params or {}).get("features") or {}
        if not features:
            return {"error": "features dict required, e.g. {'analytics': true, 'voice': false}"}
        updated = []
        skipped = []
        for key, val in features.items():
            if key not in _FEATURE_NAMES:
                skipped.append(key)
                continue
            set_tenant_feature(key, bool(val), tenant_id, note="bulk_set via velo")
            updated.append({"feature": key, "enabled": bool(val)})
        return {"updated": updated, "skipped_unknown": skipped, "count": len(updated)}

    if action == "apply_plan":
        plan = (params or {}).get("plan", "")
        # Plan tiers in this codebase: solo, growth, enterprise. Applying a
        # plan enables every feature whose required tier is at or below the
        # chosen plan, and disables everything above it.
        tier_rank = {"solo": 1, "growth": 2, "enterprise": 3}
        if plan not in tier_rank:
            return {"error": f"Unknown plan: {plan}", "available_plans": list(tier_rank.keys())}
        chosen_rank = tier_rank[plan]
        applied = []
        for name, _label, plan_tier, _default, _group in _FEATURE_REGISTRY:
            should_be_on = tier_rank.get(plan_tier, 99) <= chosen_rank
            set_tenant_feature(name, should_be_on, tenant_id, note=f"apply_plan={plan} via velo")
            applied.append({"feature": name, "enabled": should_be_on, "required_tier": plan_tier})
        return {"plan": plan, "applied": applied, "count": len(applied)}

    return {"error": f"Unknown action: {action}. Use: get, set, bulk_set, apply_plan"}


# ---------------------------------------------------------------------------
# get_plans
# ---------------------------------------------------------------------------
@velo_command(
    "get_plans",
    description="Return the real plan tiers in this app and which features each unlocks.",
)
def get_plans(params):
    from app import _FEATURE_REGISTRY
    tier_order = ["solo", "growth", "enterprise"]
    plans = {tier: [] for tier in tier_order}
    for name, label, plan_tier, default_enabled, group in _FEATURE_REGISTRY:
        plans.setdefault(plan_tier, []).append({
            "name": name,
            "label": label,
            "group": group,
            "default_enabled": default_enabled,
        })
    return {"tiers": tier_order, "plans": plans}


# ---------------------------------------------------------------------------
# get_faq
# ---------------------------------------------------------------------------
@velo_command(
    "get_faq",
    description="Return all FAQ entries for this site, ordered by sort_order.",
    params_schema={
        "type": "object",
        "properties": {
            "search": {"type": "string", "description": "Optional case-insensitive substring filter on question/answer."},
            "limit": {"type": "integer", "description": "Max rows to return (default 200)."},
        },
    },
)
def get_faq(params):
    from app import query_db
    search = ((params or {}).get("search") or "").strip()
    limit = _safe_int((params or {}).get("limit"), default=200, lo=1, hi=1000)
    if search:
        rows = query_db(
            "SELECT id, question, answer, sort_order, created_at "
            "FROM faqs "
            "WHERE question ILIKE %s OR answer ILIKE %s "
            "ORDER BY sort_order ASC, id ASC LIMIT %s",
            (f"%{search}%", f"%{search}%", limit),
        )
    else:
        rows = query_db(
            "SELECT id, question, answer, sort_order, created_at "
            "FROM faqs ORDER BY sort_order ASC, id ASC LIMIT %s",
            (limit,),
        )
    return {"faqs": rows or [], "count": len(rows or [])}


# ---------------------------------------------------------------------------
# update_faq — create or update a single FAQ entry
# ---------------------------------------------------------------------------
@velo_command(
    "update_faq",
    description="Create a new FAQ (omit id) or update an existing one (provide id).",
    params_schema={
        "type": "object",
        "properties": {
            "id": {"type": "integer", "description": "Existing FAQ id (omit to create new)."},
            "question": {"type": "string"},
            "answer": {"type": "string"},
            "sort_order": {"type": "integer"},
        },
    },
)
def update_faq(params):
    from app import query_db, execute_db
    p = params or {}
    raw_id = p.get("id")
    faq_id = _safe_int(raw_id) if raw_id is not None else None
    if raw_id is not None and faq_id is None:
        return {"error": f"invalid id: {raw_id!r}"}
    question = p.get("question")
    answer = p.get("answer")
    sort_order_raw = p.get("sort_order")
    sort_order = _safe_int(sort_order_raw) if sort_order_raw is not None else None
    if sort_order_raw is not None and sort_order is None:
        return {"error": f"invalid sort_order: {sort_order_raw!r}"}

    if faq_id:
        # Update path — only patch fields that were actually provided.
        existing = query_db("SELECT id FROM faqs WHERE id = %s", (faq_id,), fetchone=True)
        if not existing:
            return {"error": f"FAQ id {faq_id} not found"}
        sets, vals = [], []
        if question is not None:
            sets.append("question = %s"); vals.append(question)
        if answer is not None:
            sets.append("answer = %s"); vals.append(answer)
        if sort_order is not None:
            sets.append("sort_order = %s"); vals.append(sort_order)
        if not sets:
            return {"error": "no fields to update"}
        vals.append(faq_id)
        execute_db(f"UPDATE faqs SET {', '.join(sets)} WHERE id = %s", tuple(vals))
        return {"id": faq_id, "updated": True}

    # Create path
    if not question or not answer:
        return {"error": "question and answer are required to create a new FAQ"}
    row = query_db(
        "INSERT INTO faqs (question, answer, sort_order) "
        "VALUES (%s, %s, %s) RETURNING id",
        (question, answer, sort_order if sort_order is not None else 0),
        fetchone=True,
    )
    return {"id": row["id"] if row else None, "created": True}


# ---------------------------------------------------------------------------
# get_users — adapted to this codebase, where "users" really means customers
# ---------------------------------------------------------------------------
@velo_command(
    "get_users",
    description="List customer accounts (this app's user-equivalent). Optional search by name/email.",
    params_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max rows (default 50, max 500)."},
            "search": {"type": "string", "description": "Case-insensitive match on email or name."},
        },
    },
)
def get_users(params):
    from app import query_db
    p = params or {}
    limit = _safe_int(p.get("limit"), default=50, lo=1, hi=500)
    search = (p.get("search") or "").strip()
    if search:
        rows = query_db(
            "SELECT id, email, name, stripe_customer_id, created_at "
            "FROM customers "
            "WHERE email ILIKE %s OR name ILIKE %s "
            "ORDER BY created_at DESC LIMIT %s",
            (f"%{search}%", f"%{search}%", limit),
        )
    else:
        rows = query_db(
            "SELECT id, email, name, stripe_customer_id, created_at "
            "FROM customers ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
    total_row = query_db("SELECT COUNT(*) AS n FROM customers", fetchone=True)
    total = int(total_row["n"]) if total_row else 0
    return {"users": rows or [], "returned": len(rows or []), "total": total}


# ===========================================================================
# PHASE 3 — full surface expansion
# ===========================================================================
# Reads, writes, outbound actions, and destructive operations. Every
# destructive handler opts into requires_confirmation=True so a stray
# master-side bug or an automation gone wrong cannot wipe data on the
# first call — the master must echo back a confirm_token issued by the
# first call within ~2 minutes. The confirm-flow is implemented in
# velo_endpoints.handle_command; handler bodies stay clean.
# ===========================================================================


# ---- helpers shared by Phase 3 handlers ----------------------------------
# Whitelist of content types update_content / delete_content / get_content
# can touch. Each row maps the public name → (table, slug_column, search_cols)
# where search_cols is a tuple of column names get_content's free-text search
# should ILIKE against. Different content tables have wildly different
# "headline" columns (testimonials uses reviewer_name, team uses name,
# blog uses title), so a single hardcoded `COALESCE(title, name)` would
# error on the tables that have neither. Empty tuple = search disabled.
_CONTENT_TABLES = {
    "blog":         ("blog_posts",          "slug", ("title", "excerpt")),
    "events":       ("events",              "slug", ("title", "description")),
    "products":     ("products",            "slug", ("name", "description")),
    "services":     ("services",            "slug", ("name", "description")),
    "testimonials": ("testimonials",        None,   ("reviewer_name", "content")),
    "team":         ("team_members",        None,   ("name", "role", "bio")),
    "gallery":      ("gallery_cards",       "slug", ("title", "description")),
    "video":        ("video_gallery_items", None,   ("title", "description")),
    "podcast":      ("podcast_episodes",    None,   ("title", "description")),
    "pages":        ("page_sections",       "slug", ("title", "content")),
}

# Whitelist of singleton settings rows the master can read/write. Each
# entry is (table, columns_allowed_for_update). `columns_allowed_for_update`
# is the safelist for update_settings — anything outside it is rejected so
# the master can never write to internal columns like id/created_at.
_SETTINGS_TABLES = {
    "site_settings": (
        "site_settings",
        {"site_name", "site_subtitle", "hero_tagline", "hero_title",
         "hero_description", "hero_image", "logo_initials"},
    ),
    "business_info": (
        # Business info shares the site_settings row — the columns were
        # added later via ALTER TABLE. We expose them under their own
        # logical key so master code can be explicit about intent.
        "site_settings",
        {"business_phone", "business_email", "business_address",
         "business_hours", "business_map_embed", "social_links"},
    ),
    "chatbot_settings": (
        "chatbot_settings",
        {"enabled", "mode", "agent_name", "agent_role", "agent_avatar",
         "greeting", "quick_prompts", "api_endpoint", "embed_code",
         "system_prompt"},
    ),
    "voice_settings": (
        "voice_settings",
        {"enabled_intros", "enabled_visitor_voice", "enabled_ai_voice",
         "default_voice", "tts_model", "autoplay_strategy",
         "tts_provider", "stt_provider", "premium_enabled",
         "elevenlabs_voice_id", "elevenlabs_model"},
    ),
    "sphere_settings": (
        "sphere_settings",
        {"enabled", "heading_text", "view_mode", "particle_count",
         "rotation_speed", "sphere_radius", "image_size", "image_source",
         "position_randomness", "particle_opacity", "zoom_min", "zoom_max",
         "card_scale", "card_gap"},
    ),
}


def _resolve_content(content_type):
    info = _CONTENT_TABLES.get((content_type or "").lower())
    if not info:
        return None, {"error": f"unknown content_type: {content_type!r}",
                      "available": sorted(_CONTENT_TABLES.keys())}
    return info, None


# ---------------------------------------------------------------------------
# get_subscriptions — plan + tenant + feature add-ons
# ---------------------------------------------------------------------------
@velo_command(
    "get_subscriptions",
    description="Subscription state for this install: tenant, current plan, and feature add-ons.",
)
def get_subscriptions(params):
    from app import query_db, current_tenant_id
    tid = current_tenant_id()
    tenant = query_db(
        "SELECT t.*, p.slug AS plan_slug, p.name AS plan_name "
        "FROM tenants t LEFT JOIN plans p ON p.id = t.plan_id "
        "WHERE t.id = %s",
        (tid,), fetchone=True,
    )
    addons = query_db(
        "SELECT feature_name, granted_at, note FROM feature_addons "
        "WHERE tenant_id = %s ORDER BY granted_at DESC",
        (tid,),
    )
    plans = query_db("SELECT id, slug, name, description, sort_order FROM plans ORDER BY sort_order, id")
    return {
        "tenant": tenant or {},
        "addons": addons or [],
        "available_plans": plans or [],
    }


# ---------------------------------------------------------------------------
# get_visitor_sessions — page_views grouped + chat link
# ---------------------------------------------------------------------------
@velo_command(
    "get_visitor_sessions",
    description="Recent visitor sessions with page-view counts, duration, and traffic source.",
    params_schema={
        "type": "object",
        "properties": {
            "limit":  {"type": "integer", "description": "Max sessions (default 50, max 500)."},
            "period": {"type": "string", "description": "today, week, month, year. Defaults to week."},
        },
    },
)
def get_visitor_sessions(params):
    from app import query_db
    p = params or {}
    limit = _safe_int(p.get("limit"), default=50, lo=1, hi=500)
    interval = _interval(p.get("period", "week"))
    rows = query_db(
        f"SELECT session_id, "
        f"       MIN(created_at) AS started_at, "
        f"       MAX(created_at) AS last_seen, "
        f"       COUNT(*) AS page_views, "
        f"       COUNT(DISTINCT page_url) AS unique_pages, "
        f"       COALESCE(SUM(duration_seconds), 0) AS total_seconds, "
        f"       MAX(utm_source) AS utm_source, "
        f"       MAX(utm_campaign) AS utm_campaign, "
        f"       MAX(country) AS country, "
        f"       MAX(device_type) AS device_type "
        f"FROM page_views "
        f"WHERE created_at >= NOW() - INTERVAL '{interval}' "
        f"GROUP BY session_id "
        f"ORDER BY MAX(created_at) DESC LIMIT %s",
        (limit,),
    )
    return {"sessions": rows or [], "count": len(rows or []), "period": p.get("period", "week")}


# ---------------------------------------------------------------------------
# get_chat_history — conversations + (optional) messages for one session
# ---------------------------------------------------------------------------
@velo_command(
    "get_chat_history",
    description="Recent chatbot conversations. Pass session_id to get full message transcript.",
    params_schema={
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "If set, return messages for that one session."},
            "limit":      {"type": "integer", "description": "Max conversations or messages (default 50, max 500)."},
        },
    },
)
def get_chat_history(params):
    from app import query_db
    p = params or {}
    limit = _safe_int(p.get("limit"), default=50, lo=1, hi=500)
    session_id = (p.get("session_id") or "").strip()
    if session_id:
        conv = query_db(
            "SELECT * FROM chat_conversations WHERE session_id = %s LIMIT 1",
            (session_id,), fetchone=True,
        )
        msgs = query_db(
            "SELECT id, role, content, created_at FROM chat_messages "
            "WHERE conversation_id = (SELECT id FROM chat_conversations WHERE session_id = %s) "
            "ORDER BY id ASC LIMIT %s",
            (session_id, limit),
        )
        return {"conversation": conv or {}, "messages": msgs or [], "count": len(msgs or [])}
    rows = query_db(
        "SELECT c.id, c.session_id, c.visitor_id, c.device_type, c.started_at, c.updated_at, "
        "       (SELECT COUNT(*) FROM chat_messages m WHERE m.conversation_id = c.id) AS message_count "
        "FROM chat_conversations c "
        "ORDER BY c.updated_at DESC LIMIT %s",
        (limit,),
    )
    return {"conversations": rows or [], "count": len(rows or [])}


# ---------------------------------------------------------------------------
# get_content — generic content listing across blog/events/products/etc.
# ---------------------------------------------------------------------------
@velo_command(
    "get_content",
    description=("List rows from any content table: blog, events, products, services, "
                 "testimonials, team, gallery, video, podcast, pages."),
    params_schema={
        "type": "object",
        "properties": {
            "type":   {"type": "string", "description": "Content type (see description)."},
            "limit":  {"type": "integer", "description": "Max rows (default 100, max 500)."},
            "id":     {"type": "integer", "description": "Optional: fetch a single row by id."},
            "slug":   {"type": "string",  "description": "Optional: fetch a single row by slug."},
            "search": {"type": "string",  "description": "Optional title/name substring filter."},
        },
        "required": ["type"],
    },
)
def get_content(params):
    from app import query_db
    p = params or {}
    info, err = _resolve_content(p.get("type"))
    if err:
        return err
    table, slug_col, search_cols = info
    limit = _safe_int(p.get("limit"), default=100, lo=1, hi=500)
    row_id = _safe_int(p.get("id")) if p.get("id") is not None else None
    slug = (p.get("slug") or "").strip()
    search = (p.get("search") or "").strip()

    if row_id:
        row = query_db(f"SELECT * FROM {table} WHERE id = %s", (row_id,), fetchone=True)
        return {"type": p.get("type"), "row": row or {}}
    if slug and slug_col:
        row = query_db(f"SELECT * FROM {table} WHERE {slug_col} = %s", (slug,), fetchone=True)
        return {"type": p.get("type"), "row": row or {}}
    if search and search_cols:
        # Per-table searchable column list (different content tables expose
        # different "headline" columns). Build a parameterized OR-ILIKE
        # clause; column names come from the trusted module-level whitelist
        # so they're safe to interpolate.
        ors = " OR ".join(f"COALESCE({c}::text, '') ILIKE %s" for c in search_cols)
        like = f"%{search}%"
        rows = query_db(
            f"SELECT * FROM {table} WHERE {ors} ORDER BY id DESC LIMIT %s",
            tuple([like] * len(search_cols) + [limit]),
        )
    else:
        rows = query_db(f"SELECT * FROM {table} ORDER BY id DESC LIMIT %s", (limit,))
    return {"type": p.get("type"), "rows": rows or [], "count": len(rows or [])}


# ---------------------------------------------------------------------------
# get_orders
# ---------------------------------------------------------------------------
@velo_command(
    "get_orders",
    description="Orders list with optional status filter and time range.",
    params_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "pending | paid | refunded | cancelled."},
            "period": {"type": "string", "description": "today, week, month, year. Defaults to month."},
            "limit":  {"type": "integer", "description": "Max rows (default 100, max 500)."},
        },
    },
)
def get_orders(params):
    from app import query_db
    p = params or {}
    limit = _safe_int(p.get("limit"), default=100, lo=1, hi=500)
    interval = _interval(p.get("period", "month"))
    status = (p.get("status") or "").strip()

    where = [f"created_at >= NOW() - INTERVAL '{interval}'"]
    args = []
    if status:
        where.append("status = %s")
        args.append(status)
    args.append(limit)

    rows = query_db(
        f"SELECT id, order_number, customer_email, customer_name, status, "
        f"       total_cents, currency, stripe_payment_intent_id, "
        f"       created_at, paid_at "
        f"FROM orders WHERE {' AND '.join(where)} "
        f"ORDER BY created_at DESC LIMIT %s",
        tuple(args),
    )
    summary = query_db(
        f"SELECT status, COUNT(*) AS n, COALESCE(SUM(total_cents),0) AS total_cents "
        f"FROM orders WHERE created_at >= NOW() - INTERVAL '{interval}' "
        f"GROUP BY status",
    )
    return {"orders": rows or [], "count": len(rows or []),
            "summary": summary or [], "period": p.get("period", "month")}


# ---------------------------------------------------------------------------
# get_audit_log — VELO command history (great for "what did master do today?")
# ---------------------------------------------------------------------------
@velo_command(
    "get_audit_log",
    description="VELO command audit history. Filter by command, status, and time range.",
    params_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string",  "description": "Optional command-name filter."},
            "status":  {"type": "string",  "description": "ok | error."},
            "period":  {"type": "string",  "description": "today, week, month, year. Defaults to week."},
            "limit":   {"type": "integer", "description": "Max rows (default 100, max 1000)."},
        },
    },
)
def get_audit_log(params):
    from app import query_db
    p = params or {}
    limit = _safe_int(p.get("limit"), default=100, lo=1, hi=1000)
    interval = _interval(p.get("period", "week"))
    cmd = (p.get("command") or "").strip()
    status = (p.get("status") or "").strip()

    where = [f"created_at >= NOW() - INTERVAL '{interval}'"]
    args = []
    if cmd:
        where.append("command = %s"); args.append(cmd)
    if status:
        where.append("status = %s"); args.append(status)
    args.append(limit)

    rows = query_db(
        f"SELECT id, command, status, result_summary, error_msg, actor, created_at "
        f"FROM velo_audit_log WHERE {' AND '.join(where)} "
        f"ORDER BY created_at DESC LIMIT %s",
        tuple(args),
    )
    return {"entries": rows or [], "count": len(rows or [])}


# ---------------------------------------------------------------------------
# get_settings — singleton-row config readers (site/business/chatbot/voice/sphere)
# ---------------------------------------------------------------------------
@velo_command(
    "get_settings",
    description=("Read a singleton settings row: site_settings, business_info, "
                 "chatbot_settings, voice_settings, sphere_settings."),
    params_schema={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Which settings group to read."},
        },
        "required": ["key"],
    },
)
def get_settings(params):
    from app import query_db
    p = params or {}
    key = (p.get("key") or "").lower()
    info = _SETTINGS_TABLES.get(key)
    if not info:
        return {"error": f"unknown settings key: {key!r}",
                "available": sorted(_SETTINGS_TABLES.keys())}
    table, allowed = info
    cols = ", ".join(sorted(allowed))
    row = query_db(f"SELECT id, {cols} FROM {table} WHERE id = 1", fetchone=True)
    return {"key": key, "settings": row or {}}


# ---------------------------------------------------------------------------
# get_costs — api_cost_events summary
# ---------------------------------------------------------------------------
@velo_command(
    "get_costs",
    description="API cost summary by surface/model/provider for a time range.",
    params_schema={
        "type": "object",
        "properties": {
            "period": {"type": "string",  "description": "today, week, month, year. Defaults to month."},
            "group_by": {"type": "string", "description": "surface | provider | model. Defaults to surface."},
        },
    },
)
def get_costs(params):
    from app import query_db
    p = params or {}
    interval = _interval(p.get("period", "month"))
    group_by = (p.get("group_by") or "surface").lower()
    if group_by not in ("surface", "provider", "model"):
        return {"error": f"invalid group_by: {group_by!r}"}
    rows = query_db(
        f"SELECT {group_by} AS bucket, "
        f"       COUNT(*) AS events, "
        f"       COALESCE(SUM(total_tokens),0) AS tokens, "
        f"       ROUND(COALESCE(SUM(cost_usd),0)::numeric, 4) AS cost_usd "
        f"FROM api_cost_events "
        f"WHERE created_at >= NOW() - INTERVAL '{interval}' "
        f"GROUP BY {group_by} "
        f"ORDER BY cost_usd DESC NULLS LAST",
    )
    total_row = query_db(
        f"SELECT COUNT(*) AS n, ROUND(COALESCE(SUM(cost_usd),0)::numeric, 4) AS total_usd "
        f"FROM api_cost_events WHERE created_at >= NOW() - INTERVAL '{interval}'",
        fetchone=True,
    )
    return {
        "by": group_by,
        "buckets": rows or [],
        "total_events": int(total_row["n"]) if total_row else 0,
        "total_usd": float(total_row["total_usd"]) if total_row and total_row.get("total_usd") is not None else 0.0,
        "period": p.get("period", "month"),
    }


# ---------------------------------------------------------------------------
# get_form_submissions
# ---------------------------------------------------------------------------
@velo_command(
    "get_form_submissions",
    description="List form submissions across all custom forms.",
    params_schema={
        "type": "object",
        "properties": {
            "form_id": {"type": "integer", "description": "Optional: only this form."},
            "status":  {"type": "string",  "description": "new | reviewed | archived."},
            "limit":   {"type": "integer", "description": "Max rows (default 100, max 500)."},
        },
    },
)
def get_form_submissions(params):
    from app import query_db
    p = params or {}
    limit = _safe_int(p.get("limit"), default=100, lo=1, hi=500)
    form_id = _safe_int(p.get("form_id")) if p.get("form_id") is not None else None
    status = (p.get("status") or "").strip()
    where, args = [], []
    if form_id:
        where.append("form_id = %s"); args.append(form_id)
    if status:
        where.append("status = %s"); args.append(status)
    args.append(limit)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = query_db(
        f"SELECT id, form_id, status, submission_data, page_url, "
        f"       utm_source, utm_campaign, submitted_at "
        f"FROM form_submissions {where_sql} "
        f"ORDER BY submitted_at DESC LIMIT %s",
        tuple(args),
    )
    return {"submissions": rows or [], "count": len(rows or [])}


# ---------------------------------------------------------------------------
# get_voice_logs — voice usage breakdown
# ---------------------------------------------------------------------------
@velo_command(
    "get_voice_logs",
    description="Voice agent usage events (TTS, STT, intro plays).",
    params_schema={
        "type": "object",
        "properties": {
            "period":  {"type": "string",  "description": "today, week, month, year."},
            "feature": {"type": "string",  "description": "Filter to a single feature_type."},
            "limit":   {"type": "integer", "description": "Max rows (default 100, max 1000)."},
        },
    },
)
def get_voice_logs(params):
    from app import query_db
    p = params or {}
    limit = _safe_int(p.get("limit"), default=100, lo=1, hi=1000)
    interval = _interval(p.get("period", "week"))
    feature = (p.get("feature") or "").strip()
    where = [f"created_at >= NOW() - INTERVAL '{interval}'"]
    args = []
    if feature:
        where.append("feature_type = %s"); args.append(feature)
    args.append(limit)
    rows = query_db(
        f"SELECT id, feature_type, session_id, created_at "
        f"FROM voice_usage_log WHERE {' AND '.join(where)} "
        f"ORDER BY created_at DESC LIMIT %s",
        tuple(args),
    )
    summary = query_db(
        f"SELECT feature_type, COUNT(*) AS n FROM voice_usage_log "
        f"WHERE created_at >= NOW() - INTERVAL '{interval}' "
        f"GROUP BY feature_type ORDER BY n DESC",
    )
    return {"events": rows or [], "summary": summary or [], "count": len(rows or [])}


# ---------------------------------------------------------------------------
# get_skills — agent_skills catalogue
# ---------------------------------------------------------------------------
@velo_command(
    "get_skills",
    description="Agent skills catalogue (built-in + custom). Pass enabled_only=true to filter.",
    params_schema={
        "type": "object",
        "properties": {
            "enabled_only": {"type": "boolean"},
            "category":     {"type": "string"},
        },
    },
)
def get_skills(params):
    from app import query_db
    p = params or {}
    where, args = [], []
    if p.get("enabled_only"):
        where.append("enabled = true")
    if (p.get("category") or "").strip():
        where.append("category = %s"); args.append(p["category"].strip())
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = query_db(
        f"SELECT id, name, display_name, description, category, "
        f"       builtin, enabled, created_at "
        f"FROM agent_skills {where_sql} ORDER BY category, name",
        tuple(args) if args else None,
    )
    return {"skills": rows or [], "count": len(rows or [])}


# ---------------------------------------------------------------------------
# get_mcp_servers — MCP servers wired into this install
# ---------------------------------------------------------------------------
@velo_command(
    "get_mcp_servers",
    description="MCP servers registered for tool use, including last-test status.",
)
def get_mcp_servers(params):
    from app import query_db
    rows = query_db(
        "SELECT id, name, description, transport, url, auth_type, "
        "       enabled, allowed_for_admin, allowed_for_velo, connector_type, "
        "       last_test_at, last_test_ok, last_test_error, "
        "       created_at, updated_at "
        "FROM mcp_servers ORDER BY name"
    )
    return {"servers": rows or [], "count": len(rows or [])}


# ---------------------------------------------------------------------------
# update_content — generic CREATE/UPDATE for content tables
# ---------------------------------------------------------------------------
@velo_command(
    "update_content",
    description=("Create (omit id) or update (with id) a content row. "
                 "fields is a dict of column → value, validated against the table."),
    params_schema={
        "type": "object",
        "properties": {
            "type":   {"type": "string", "description": "Same set as get_content."},
            "id":     {"type": "integer", "description": "Existing row id (omit to create)."},
            "fields": {"type": "object",  "description": "Dict of column → new value."},
        },
        "required": ["type", "fields"],
    },
)
def update_content(params):
    from app import query_db, execute_db
    p = params or {}
    info, err = _resolve_content(p.get("type"))
    if err:
        return err
    table, _slug_col, _ = info
    fields = p.get("fields") or {}
    if not isinstance(fields, dict) or not fields:
        return {"error": "fields must be a non-empty object"}

    # Discover the real column list for this table so we don't trust the
    # master with raw INSERT/UPDATE strings. Anything not in the live
    # schema is silently dropped + reported back.
    cols_rows = query_db(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name = %s",
        (table,),
    )
    valid_cols = {r["column_name"] for r in (cols_rows or [])} - {"id", "created_at", "updated_at"}
    safe = {k: v for k, v in fields.items() if k in valid_cols}
    rejected = sorted(set(fields.keys()) - set(safe.keys()))
    if not safe:
        return {"error": "no valid columns supplied", "rejected": rejected,
                "valid_columns": sorted(valid_cols)}

    raw_id = p.get("id")
    row_id = _safe_int(raw_id) if raw_id is not None else None
    if raw_id is not None and row_id is None:
        return {"error": f"invalid id: {raw_id!r}"}

    if row_id:
        sets = ", ".join(f"{k} = %s" for k in safe.keys())
        vals = list(safe.values()) + [row_id]
        execute_db(f"UPDATE {table} SET {sets} WHERE id = %s", tuple(vals))
        return {"type": p.get("type"), "id": row_id, "updated": True,
                "rejected_columns": rejected}

    cols_sql = ", ".join(safe.keys())
    placeholders = ", ".join(["%s"] * len(safe))
    new_row = query_db(
        f"INSERT INTO {table} ({cols_sql}) VALUES ({placeholders}) RETURNING id",
        tuple(safe.values()), fetchone=True,
    )
    return {"type": p.get("type"), "id": new_row["id"] if new_row else None,
            "created": True, "rejected_columns": rejected}


# ---------------------------------------------------------------------------
# update_settings — generic singleton-row updater
# ---------------------------------------------------------------------------
@velo_command(
    "update_settings",
    description=("Update a singleton settings row. Same key set as get_settings. "
                 "fields is a dict of column → value."),
    params_schema={
        "type": "object",
        "properties": {
            "key":    {"type": "string"},
            "fields": {"type": "object"},
        },
        "required": ["key", "fields"],
    },
)
def update_settings(params):
    from app import execute_db
    import json as _json
    p = params or {}
    key = (p.get("key") or "").lower()
    info = _SETTINGS_TABLES.get(key)
    if not info:
        return {"error": f"unknown settings key: {key!r}",
                "available": sorted(_SETTINGS_TABLES.keys())}
    table, allowed = info
    fields = p.get("fields") or {}
    if not isinstance(fields, dict) or not fields:
        return {"error": "fields must be a non-empty object"}

    safe = {k: v for k, v in fields.items() if k in allowed}
    rejected = sorted(set(fields.keys()) - set(safe.keys()))
    if not safe:
        return {"error": "no valid columns supplied", "rejected": rejected,
                "valid_columns": sorted(allowed)}

    # Hours and social_links live as JSONB; coerce dict/list values so
    # callers don't have to pre-serialize them.
    sets, vals = [], []
    for k, v in safe.items():
        if isinstance(v, (dict, list)):
            sets.append(f"{k} = %s::jsonb")
            vals.append(_json.dumps(v))
        else:
            sets.append(f"{k} = %s")
            vals.append(v)
    execute_db(
        f"UPDATE {table} SET {', '.join(sets)}, updated_at = NOW() WHERE id = 1",
        tuple(vals),
    )
    return {"key": key, "updated": True, "fields": list(safe.keys()),
            "rejected_columns": rejected}


# ---------------------------------------------------------------------------
# manage_user — create / update a customer record
# ---------------------------------------------------------------------------
@velo_command(
    "manage_user",
    description="Create or update a customer (the user-equivalent in this app).",
    params_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "create | update"},
            "id":     {"type": "integer"},
            "email":  {"type": "string"},
            "name":   {"type": "string"},
            "stripe_customer_id": {"type": "string"},
        },
        "required": ["action"],
    },
)
def manage_user(params):
    from app import query_db, execute_db
    p = params or {}
    action = (p.get("action") or "").lower()

    if action == "create":
        email = (p.get("email") or "").strip()
        if not email or "@" not in email:
            return {"error": "valid email required"}
        existing = query_db("SELECT id FROM customers WHERE email = %s",
                            (email,), fetchone=True)
        if existing:
            return {"error": "customer with this email already exists",
                    "id": existing["id"]}
        new_row = query_db(
            "INSERT INTO customers (email, name, stripe_customer_id) "
            "VALUES (%s, %s, %s) RETURNING id",
            (email, p.get("name") or "", p.get("stripe_customer_id") or ""),
            fetchone=True,
        )
        return {"id": new_row["id"] if new_row else None, "created": True}

    if action == "update":
        cid = _safe_int(p.get("id"))
        if not cid:
            return {"error": "id required for update"}
        sets, vals = [], []
        for col in ("email", "name", "stripe_customer_id"):
            if p.get(col) is not None:
                sets.append(f"{col} = %s"); vals.append(p[col])
        if not sets:
            return {"error": "no fields to update"}
        vals.append(cid)
        execute_db(f"UPDATE customers SET {', '.join(sets)} WHERE id = %s", tuple(vals))
        return {"id": cid, "updated": True}

    return {"error": f"unknown action: {action!r}. Use create or update."}


# ---------------------------------------------------------------------------
# send_chat_message — push an admin/system message into a conversation
# ---------------------------------------------------------------------------
@velo_command(
    "send_chat_message",
    description="Insert a message into a chat conversation (role typically 'assistant' or 'system').",
    params_schema={
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "content":    {"type": "string"},
            "role":       {"type": "string", "description": "assistant | system | user. Default assistant."},
        },
        "required": ["session_id", "content"],
    },
)
def send_chat_message(params):
    from app import query_db, execute_db
    p = params or {}
    session_id = (p.get("session_id") or "").strip()
    content = p.get("content") or ""
    role = (p.get("role") or "assistant").strip()
    if not session_id or not content:
        return {"error": "session_id and content are required"}
    conv = query_db(
        "SELECT id FROM chat_conversations WHERE session_id = %s LIMIT 1",
        (session_id,), fetchone=True,
    )
    if not conv:
        return {"error": f"no conversation for session_id={session_id!r}"}
    new_row = query_db(
        "INSERT INTO chat_messages (conversation_id, role, content) "
        "VALUES (%s, %s, %s) RETURNING id",
        (conv["id"], role, content), fetchone=True,
    )
    execute_db("UPDATE chat_conversations SET updated_at = NOW() WHERE id = %s",
               (conv["id"],))
    return {"message_id": new_row["id"] if new_row else None,
            "conversation_id": conv["id"], "inserted": True}


# ---------------------------------------------------------------------------
# toggle_skill — enable/disable an agent_skill
# ---------------------------------------------------------------------------
@velo_command(
    "toggle_skill",
    description="Enable or disable a single agent_skill by name.",
    params_schema={
        "type": "object",
        "properties": {
            "name":    {"type": "string"},
            "enabled": {"type": "boolean"},
        },
        "required": ["name", "enabled"],
    },
)
def toggle_skill(params):
    from app import query_db, execute_db
    p = params or {}
    name = (p.get("name") or "").strip()
    enabled = bool(p.get("enabled", False))
    if not name:
        return {"error": "name required"}
    existing = query_db("SELECT id, enabled FROM agent_skills WHERE name = %s",
                        (name,), fetchone=True)
    if not existing:
        return {"error": f"skill not found: {name!r}"}
    execute_db("UPDATE agent_skills SET enabled = %s WHERE name = %s", (enabled, name))
    return {"name": name, "previous_enabled": existing["enabled"],
            "enabled": enabled, "updated": True}


# ===========================================================================
# OUTBOUND ACTIONS — every one is destructive (sends a real message)
# so they all opt into the confirmation-token flow.
# ===========================================================================

# ---------------------------------------------------------------------------
# send_email — Resend
# ---------------------------------------------------------------------------
@velo_command(
    "send_email",
    description="Send an email via Resend (gated — requires confirmation).",
    params_schema={
        "type": "object",
        "properties": {
            "to":       {"type": "string"},
            "subject":  {"type": "string"},
            "html":     {"type": "string"},
            "text":     {"type": "string"},
            "reply_to": {"type": "string"},
        },
        "required": ["to", "subject"],
    },
    requires_confirmation=True,
)
def send_email(params):
    import messaging
    p = params or {}
    to = (p.get("to") or "").strip()
    subject = p.get("subject") or ""
    html = p.get("html") or ""
    text = p.get("text") or None
    reply_to = (p.get("reply_to") or "").strip() or None
    if not to or "@" not in to:
        return {"error": "valid 'to' email required"}
    try:
        resp = messaging.send_email(to, subject, html, text_body=text, reply_to=reply_to)
        return {"sent": True, "to": to, "provider_response": resp}
    except messaging.MessagingError as e:
        return {"sent": False, "error": str(e)}


# ---------------------------------------------------------------------------
# send_sms — Twilio
# ---------------------------------------------------------------------------
@velo_command(
    "send_sms",
    description="Send an SMS via Twilio (gated — requires confirmation).",
    params_schema={
        "type": "object",
        "properties": {
            "to":   {"type": "string", "description": "E.164 number, e.g. +15551234567"},
            "body": {"type": "string"},
        },
        "required": ["to", "body"],
    },
    requires_confirmation=True,
)
def send_sms(params):
    import messaging
    p = params or {}
    to = (p.get("to") or "").strip()
    body = p.get("body") or ""
    if not to:
        return {"error": "'to' phone required"}
    if not body:
        return {"error": "'body' required"}
    try:
        resp = messaging.send_sms(to, body)
        return {"sent": True, "to": to, "provider_response": resp}
    except messaging.MessagingError as e:
        return {"sent": False, "error": str(e)}


# ---------------------------------------------------------------------------
# trigger_weekly_digest — re-run the weekly digest send for current tenant
# ---------------------------------------------------------------------------
@velo_command(
    "trigger_weekly_digest",
    description="Force-send the weekly admin digest email now (gated).",
    requires_confirmation=True,
)
def trigger_weekly_digest(params):
    # The digest runs as a background scheduler in normal operation.
    # We poke its internals here only if it exposes a callable; otherwise
    # we surface a clean error rather than fail mysteriously.
    from app import query_db
    try:
        # Some installs name this _send_weekly_digest_now / send_weekly_digest;
        # try a couple before giving up.
        import app as _app
        for fn_name in ("send_weekly_digest_now", "_send_weekly_digest_now",
                        "send_weekly_digest", "_send_weekly_digest",
                        "run_weekly_digest"):
            fn = getattr(_app, fn_name, None)
            if callable(fn):
                result = fn()
                return {"triggered": True, "via": fn_name, "result": result}
    except Exception as e:
        return {"triggered": False, "error": str(e)}
    last = query_db(
        "SELECT * FROM weekly_digest_sends ORDER BY id DESC LIMIT 1",
        fetchone=True,
    )
    return {
        "triggered": False,
        "error": "no weekly digest entry-point exposed by app.py",
        "last_send": last or {},
    }


# ===========================================================================
# DESTRUCTIVE — gated. Every one is irreversible or expensive.
# ===========================================================================

# ---------------------------------------------------------------------------
# manage_plan — change a plan's slug/name/description/sort_order
# ---------------------------------------------------------------------------
@velo_command(
    "manage_plan",
    description="Update a plan row (id required). Cannot delete plans here.",
    params_schema={
        "type": "object",
        "properties": {
            "id":          {"type": "integer"},
            "slug":        {"type": "string"},
            "name":        {"type": "string"},
            "description": {"type": "string"},
            "sort_order":  {"type": "integer"},
        },
        "required": ["id"],
    },
    requires_confirmation=True,
)
def manage_plan(params):
    from app import query_db, execute_db
    p = params or {}
    pid = _safe_int(p.get("id"))
    if not pid:
        return {"error": "id required"}
    existing = query_db("SELECT id FROM plans WHERE id = %s", (pid,), fetchone=True)
    if not existing:
        return {"error": f"plan id {pid} not found"}
    sets, vals = [], []
    for col in ("slug", "name", "description", "sort_order"):
        if p.get(col) is not None:
            sets.append(f"{col} = %s"); vals.append(p[col])
    if not sets:
        return {"error": "no fields to update"}
    vals.append(pid)
    execute_db(f"UPDATE plans SET {', '.join(sets)} WHERE id = %s", tuple(vals))
    return {"id": pid, "updated": True}


# ---------------------------------------------------------------------------
# delete_content — DELETE FROM <whitelisted table> WHERE id = ?
# ---------------------------------------------------------------------------
@velo_command(
    "delete_content",
    description="Hard-delete a content row by id. Whitelisted tables only.",
    params_schema={
        "type": "object",
        "properties": {
            "type": {"type": "string", "description": "Same set as get_content."},
            "id":   {"type": "integer"},
        },
        "required": ["type", "id"],
    },
    requires_confirmation=True,
)
def delete_content(params):
    from app import execute_db, query_db
    p = params or {}
    info, err = _resolve_content(p.get("type"))
    if err:
        return err
    table, _slug, _ = info
    rid = _safe_int(p.get("id"))
    if not rid:
        return {"error": "id required"}
    existing = query_db(f"SELECT id FROM {table} WHERE id = %s", (rid,), fetchone=True)
    if not existing:
        return {"error": f"{p.get('type')} id {rid} not found"}
    execute_db(f"DELETE FROM {table} WHERE id = %s", (rid,))
    return {"type": p.get("type"), "id": rid, "deleted": True}


# ---------------------------------------------------------------------------
# refund_order — issue a Stripe refund for a paid order
# ---------------------------------------------------------------------------
@velo_command(
    "refund_order",
    description="Refund a paid order via Stripe. Order must be in 'paid' status.",
    params_schema={
        "type": "object",
        "properties": {
            "order_number": {"type": "string"},
            "amount_cents": {"type": "integer", "description": "Optional partial refund amount."},
            "reason":       {"type": "string"},
        },
        "required": ["order_number"],
    },
    requires_confirmation=True,
)
def refund_order(params):
    from app import query_db, execute_db
    p = params or {}
    order_number = (p.get("order_number") or "").strip()
    if not order_number:
        return {"error": "order_number required"}
    order = query_db(
        "SELECT id, status, total_cents, stripe_payment_intent_id "
        "FROM orders WHERE order_number = %s",
        (order_number,), fetchone=True,
    )
    if not order:
        return {"error": f"order not found: {order_number}"}
    if order["status"] != "paid":
        return {"error": f"order is {order['status']!r}, only 'paid' orders can be refunded"}
    if not order.get("stripe_payment_intent_id"):
        return {"error": "order has no stripe_payment_intent_id"}

    try:
        # Prefer the repo's Stripe resolver — it picks up the Replit
        # connector token (the storefront's auth path) before falling back
        # to STRIPE_SECRET_KEY. A bare `import stripe` skips that and can
        # 401 even when checkout works fine.
        try:
            import stripe_client
            _stripe = stripe_client.get_stripe()
        except Exception:
            import stripe as _stripe
        kwargs = {"payment_intent": order["stripe_payment_intent_id"]}
        amt = _safe_int(p.get("amount_cents"))
        if amt:
            kwargs["amount"] = amt
        reason = (p.get("reason") or "").strip()
        if reason:
            kwargs["reason"] = reason
        refund = _stripe.Refund.create(**kwargs)
    except Exception as e:
        return {"refunded": False, "error": str(e)}

    execute_db(
        "UPDATE orders SET status = 'refunded' WHERE id = %s",
        (order["id"],),
    )
    return {
        "refunded": True,
        "order_number": order_number,
        "refund_id": getattr(refund, "id", None),
        "amount_cents": getattr(refund, "amount", None),
    }
