"""
VELO Command Handlers — concrete capabilities exposed to VELO Master.

Each @velo_command function becomes a tool VELO can call. Importing this
module from app.py is what triggers the @velo_command decorators to
populate the registry in velo_endpoints._command_handlers.

All handler bodies are adapted to this codebase's actual schema and use
the existing psycopg2 helpers (query_db / execute_db). Plan and feature
state hooks into the existing tenant_features system rather than
introducing a parallel feature_flags table.

Handlers in this file (Phase 2 set):
    get_analytics      — signups, revenue, page views, chat sessions by period
    get_system_status  — DB health, table count, uptime, key counters
    manage_features    — get / set / bulk_set / apply_plan against tenant_features
    get_plans          — returns the real plan tiers from _FEATURE_REGISTRY
    get_faq            — list FAQ entries
    update_faq         — create or update a single FAQ entry
    get_users          — customers list (the closest user-equivalent in this app)

Skipped for now (per spec): send_email, get_subscriptions, send_chat_message,
manage_user, escalate_response, get_visitor_sessions, update_content. Each
can be added later as a single new @velo_command function.
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
