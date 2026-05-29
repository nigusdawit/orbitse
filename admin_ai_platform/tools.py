"""
admin_ai_platform.tools
======================

Chat lookup tools — the on-demand retrieval layer that keeps per-turn token
cost flat as content grows. The visitor gets a compact SITE INDEX (names +
slugs); the model calls a ``lookup_*`` tool when it needs detail.

This M1 cut ships the tools whose data the package owns now — gallery, forms,
generated pages, presentations. Later milestones append more (services,
products, events, blog, team, faq, web_search, knowledge_base) following the
exact same three-part pattern:

  1. an executor function ``lookup_x(**args) -> list|dict``
  2. an entry in ``CHAT_TOOLS`` (OpenAI function-calling schema)
  3. an entry in ``CHAT_LOOKUP_FUNCTIONS`` + ``SKILL_METADATA``

``get_active_chat_tools`` filters the schema by the admin's per-skill enable
flags (``agent_skills``); ``execute_chat_tool`` dispatches + logs each call.
"""

from __future__ import annotations

import json
import time

from .db import query_db, execute_db
from .util import trim_text


# --------------------------------------------------------------------------
# Executors
# --------------------------------------------------------------------------
def lookup_gallery_cards(slug=None, category=None, query=None, limit=5):
    """Full details for gallery cards. Filter by slug, category, or free text."""
    sql = ("SELECT slug, title, subtitle, category, description, details, "
           "price, image_url FROM gallery_cards WHERE 1=1")
    params = []
    if slug:
        sql += " AND slug = %s"
        params.append(slug)
    if category:
        sql += " AND category ILIKE %s"
        params.append(f"%{category}%")
    if query:
        sql += (" AND (title ILIKE %s OR subtitle ILIKE %s OR "
                "description ILIKE %s OR category ILIKE %s)")
        q = f"%{query}%"
        params.extend([q, q, q, q])
    sql += " ORDER BY sort_order ASC LIMIT %s"
    params.append(max(1, min(int(limit or 5), 20)))
    rows = query_db(sql, tuple(params)) or []
    out = []
    for r in rows:
        details = r.get("details")
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except Exception:
                details = []
        out.append({
            "slug": r["slug"], "title": r["title"],
            "subtitle": trim_text(r.get("subtitle"), 200),
            "category": r.get("category"),
            "description": trim_text(r.get("description"), 600),
            "details": details if isinstance(details, list) else [],
            "price": r.get("price"), "image_url": r.get("image_url") or None,
        })
    return out


def lookup_forms(slug=None, query=None, limit=10):
    """Active forms + their field schema, so the AI can collect + submit them."""
    sql = ("SELECT id, name, slug, description, submit_button_text "
           "FROM custom_forms WHERE status = 'active'")
    params = []
    if slug:
        sql += " AND slug = %s"
        params.append(slug)
    if query:
        sql += " AND (name ILIKE %s OR description ILIKE %s)"
        params.extend([f"%{query}%", f"%{query}%"])
    sql += " ORDER BY sort_order, id LIMIT %s"
    params.append(max(1, min(int(limit or 10), 30)))
    forms = query_db(sql, tuple(params)) or []
    out = []
    for f in forms:
        fields = query_db(
            "SELECT label, name, field_type, required, options, help_text, step "
            "FROM form_fields WHERE form_id = %s ORDER BY sort_order, id",
            (f["id"],),
        ) or []
        out.append({
            "slug": f["slug"], "name": f["name"],
            "description": trim_text(f.get("description"), 300),
            "submit_button_text": f.get("submit_button_text"),
            "fields": [{
                "name": fl["name"], "label": fl["label"], "type": fl["field_type"],
                "required": bool(fl["required"]),
                "options": fl.get("options"), "help_text": fl.get("help_text"),
                "step": fl.get("step", 1),
            } for fl in fields],
        })
    return out


def lookup_generated_page(topic=None, slug=None, limit=5):
    """Full-text search over published AI-generated pages (for showSavedPage)."""
    sql = "SELECT slug, title, prompt FROM generated_pages WHERE status = 'published'"
    params = []
    if slug:
        sql += " AND slug = %s"
        params.append(slug)
    if topic:
        sql += " AND (title ILIKE %s OR prompt ILIKE %s)"
        params.extend([f"%{topic}%", f"%{topic}%"])
    sql += " ORDER BY updated_at DESC LIMIT %s"
    params.append(max(1, min(int(limit or 5), 20)))
    rows = query_db(sql, tuple(params)) or []
    return [{"slug": r["slug"], "title": r.get("title"),
             "originally_for": trim_text(r.get("prompt"), 160)} for r in rows]


def lookup_knowledge_base(query=None, limit=6):
    """Semantic search over uploaded KB documents (pgvector). Returns matched
    chunks with source markers. No-op message when pgvector is unavailable."""
    from .schema import rag_available
    if not rag_available():
        return {"error": "knowledge base unavailable"}
    if not (query or "").strip():
        return {"error": "query required"}
    from .reused_di import rag
    from .tenancy import current_tenant_id
    chunks = rag.retrieve(query, tenant_id=current_tenant_id(), top_k=int(limit or 6))
    return {"chunks": chunks}


def lookup_presentation(slug=None, query=None, limit=3):
    """Presentation decks + their slide bodies (for start_presentation)."""
    sql = ("SELECT id, slug, title, description FROM presentations "
           "WHERE enabled = TRUE")
    params = []
    if slug:
        sql += " AND slug = %s"
        params.append(slug)
    if query:
        sql += " AND (title ILIKE %s OR description ILIKE %s)"
        params.extend([f"%{query}%", f"%{query}%"])
    sql += " ORDER BY id LIMIT %s"
    params.append(max(1, min(int(limit or 3), 10)))
    decks = query_db(sql, tuple(params)) or []
    out = []
    for d in decks:
        slides = query_db(
            "SELECT order_index, title, body, narration_text FROM presentation_slides "
            "WHERE presentation_id = %s ORDER BY order_index, id",
            (d["id"],),
        ) or []
        out.append({
            "slug": d["slug"], "title": d["title"],
            "description": trim_text(d.get("description"), 200),
            "slides": [{"title": s.get("title"),
                        "body": trim_text(s.get("body"), 400)} for s in slides],
        })
    return out


def lookup_events(slug=None, query=None, limit=5):
    """Upcoming published events with capacity + price mode (for RSVP/ticketing).
    Returns seats_remaining so the AI can tell a visitor if an event is sold out."""
    sql = ("SELECT id, slug, title, description, start_at, location, capacity, "
           "price_mode, price_cents, currency FROM events WHERE status='published'")
    params = []
    if slug:
        sql += " AND slug = %s"
        params.append(slug)
    if query:
        sql += " AND (title ILIKE %s OR description ILIKE %s OR location ILIKE %s)"
        params.extend([f"%{query}%", f"%{query}%", f"%{query}%"])
    sql += " ORDER BY start_at NULLS LAST, sort_order, id LIMIT %s"
    params.append(max(1, min(int(limit or 5), 20)))
    rows = query_db(sql, tuple(params)) or []
    out = []
    for r in rows:
        taken = int((query_db(
            "SELECT COALESCE(SUM(guests),0) AS n FROM event_rsvps WHERE event_id=%s "
            "AND status IN ('confirmed','pending') AND payment_status NOT IN ('expired','refunded')",
            (r["id"],), fetchone=True) or {}).get("n", 0))
        out.append({
            "slug": r["slug"], "title": r.get("title"),
            "description": trim_text(r.get("description"), 200),
            "start_at": r["start_at"].isoformat() if r.get("start_at") else None,
            "location": r.get("location"), "price_mode": r.get("price_mode"),
            "price_cents": r.get("price_cents"), "currency": r.get("currency"),
            "seats_remaining": (max(0, r["capacity"] - taken) if r["capacity"] else None)})
    return out


# --------------------------------------------------------------------------
# Schemas + registry
# --------------------------------------------------------------------------
CHAT_TOOLS = [
    {"type": "function", "function": {
        "name": "lookup_gallery_cards",
        "description": ("Full details (description, details list, price, image) for "
                        "gallery cards. Use when the visitor asks about a card by "
                        "name/slug or wants to browse a category."),
        "parameters": {"type": "object", "properties": {
            "slug": {"type": "string"}, "category": {"type": "string"},
            "query": {"type": "string"}, "limit": {"type": "integer"}}},
    }},
    {"type": "function", "function": {
        "name": "lookup_forms",
        "description": ("Get a form's field schema so you can collect it "
                        "conversationally and submit via submitForm. Call before "
                        "asking for fields."),
        "parameters": {"type": "object", "properties": {
            "slug": {"type": "string"}, "query": {"type": "string"},
            "limit": {"type": "integer"}}},
    }},
    {"type": "function", "function": {
        "name": "lookup_generated_page",
        "description": ("Full-text search the published AI-page library by topic. Use "
                        "before generatePage to reuse an existing page via showSavedPage."),
        "parameters": {"type": "object", "properties": {
            "topic": {"type": "string"}, "slug": {"type": "string"},
            "limit": {"type": "integer"}}},
    }},
    {"type": "function", "function": {
        "name": "lookup_presentation",
        "description": ("Get a deck's slide bodies. Call with a slug before launching "
                        "it with a start_presentation command."),
        "parameters": {"type": "object", "properties": {
            "slug": {"type": "string"}, "query": {"type": "string"},
            "limit": {"type": "integer"}}},
    }},
    {"type": "function", "function": {
        "name": "lookup_knowledge_base",
        "description": ("Semantic search over the uploaded knowledge-base documents. "
                        "Use for questions the site index/other lookups can't answer."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "lookup_events",
        "description": ("Upcoming events with date, location, price mode (free/paid/"
                        "donation) and seats remaining. Use when a visitor asks about "
                        "events or wants to RSVP/buy tickets."),
        "parameters": {"type": "object", "properties": {
            "slug": {"type": "string"}, "query": {"type": "string"},
            "limit": {"type": "integer"}}},
    }},
]

CHAT_LOOKUP_FUNCTIONS = {
    "lookup_gallery_cards": lookup_gallery_cards,
    "lookup_forms": lookup_forms,
    "lookup_generated_page": lookup_generated_page,
    "lookup_presentation": lookup_presentation,
    "lookup_knowledge_base": lookup_knowledge_base,
    "lookup_events": lookup_events,
}

# name -> (display_name, category) for the agent_skills registry sync.
SKILL_METADATA = {
    "lookup_gallery_cards": ("Look up gallery cards", "lookup"),
    "lookup_forms": ("Look up forms", "lookup"),
    "lookup_generated_page": ("Search saved pages", "lookup"),
    "lookup_presentation": ("Look up presentations", "presentation"),
    "lookup_knowledge_base": ("Search knowledge base", "rag"),
    "lookup_events": ("Look up events", "lookup"),
}


def sync_skills_to_db():
    """Upsert builtin skills into agent_skills so the admin can toggle them.
    Preserves admin edits to display_name/description/category via COALESCE."""
    for name, (display, category) in SKILL_METADATA.items():
        desc = ""
        for t in CHAT_TOOLS:
            if t["function"]["name"] == name:
                desc = t["function"]["description"]
                break
        try:
            execute_db(
                "INSERT INTO agent_skills (name, display_name, description, category, builtin, enabled) "
                "VALUES (%s,%s,%s,%s,TRUE,TRUE) "
                "ON CONFLICT (name) DO UPDATE SET "
                "  display_name = COALESCE(NULLIF(agent_skills.display_name,''), EXCLUDED.display_name), "
                "  description  = COALESCE(NULLIF(agent_skills.description,''),  EXCLUDED.description), "
                "  category     = COALESCE(NULLIF(agent_skills.category,''),     EXCLUDED.category), "
                "  builtin = TRUE",
                (name, display, desc, category),
            )
        except Exception as e:
            print(f"[tools] sync_skills_to_db({name}) failed: {e}")


def get_active_chat_tools():
    """Return the enabled builtin tools PLUS any enabled admin-defined custom
    skills (SQL / HTTP). On a DB error, fail open to all builtins."""
    try:
        rows = query_db("SELECT name, enabled FROM agent_skills") or []
        enabled = {r["name"]: bool(r["enabled"]) for r in rows}
    except Exception:
        return list(CHAT_TOOLS)
    # Drop the KB tool entirely when pgvector isn't available, so the model is
    # never offered a tool that can only error.
    try:
        from .schema import rag_available
        kb_ok = rag_available()
    except Exception:
        kb_ok = False
    out = []
    for t in CHAT_TOOLS:
        name = t["function"]["name"]
        if name == "lookup_knowledge_base" and not kb_ok:
            continue
        # Unknown (not yet synced) → include; known+disabled → exclude.
        if enabled.get(name, True):
            out.append(t)
    # Append admin-defined custom skills (their own enabled flag governs them).
    try:
        from .custom_skills import custom_tool_schemas
        out.extend(custom_tool_schemas())
    except Exception as e:
        print(f"[tools] custom skill schemas skipped: {e}")
    # Append MCP tools visible to visitors (servers flagged allowed_for_velo).
    try:
        from .mcp_tools import mcp_tool_schemas
        out.extend(mcp_tool_schemas(audience="visitor"))
    except Exception as e:
        print(f"[tools] mcp schemas skipped: {e}")
    return out


def _log_skill_usage(session_id, entry):
    try:
        execute_db(
            "INSERT INTO skill_usage_log (session_id, skill_name, args_json, "
            " row_count, duration_ms, error) VALUES (%s,%s,%s,%s,%s,%s)",
            (session_id[:100], (entry.get("name") or "")[:100],
             json.dumps(entry.get("args")), int(entry.get("row_count") or 0),
             int(entry.get("duration_ms") or 0), (entry.get("error") or "")[:500]),
        )
    except Exception as e:
        print(f"[tools] _log_skill_usage failed: {e}")


def execute_chat_tool(name, args_json, session_id=""):
    """Dispatch one tool call. Returns ``(result_json_str, log_entry)`` and
    writes a skill_usage_log row. Never raises into the caller."""
    t0 = time.time()
    try:
        args = json.loads(args_json) if isinstance(args_json, str) else (args_json or {})
        if not isinstance(args, dict):
            args = {}
    except Exception:
        args = {}
    fn = CHAT_LOOKUP_FUNCTIONS.get(name)
    entry = {"name": name, "args": args, "row_count": 0, "duration_ms": 0, "error": ""}
    if fn is None:
        # Not a builtin — try an admin-defined custom skill (SQL / HTTP).
        try:
            from .custom_skills import is_custom_skill, execute_custom_skill
            from .mcp_tools import is_mcp_tool, execute_mcp_tool
            if is_mcp_tool(name):
                result = execute_mcp_tool(name, args)
                result_str = json.dumps(result, default=str)
            elif is_custom_skill(name):
                result = execute_custom_skill(name, args)
                entry["row_count"] = result.get("row_count", 0) if isinstance(result, dict) else 0
                result_str = json.dumps(result, default=str)
            else:
                entry["error"] = "unknown_tool"
                result_str = json.dumps({"error": f"Unknown tool {name}"})
        except Exception as e:
            entry["error"] = str(e)[:500]
            result_str = json.dumps({"error": "tool_failed", "detail": str(e)[:200]})
    else:
        try:
            result = fn(**args)
            entry["row_count"] = len(result) if isinstance(result, (list, dict)) else 0
            result_str = json.dumps(result, default=str)
        except Exception as e:
            entry["error"] = str(e)[:500]
            result_str = json.dumps({"error": "tool_failed", "detail": str(e)[:200]})
    entry["duration_ms"] = int((time.time() - t0) * 1000)
    _log_skill_usage(session_id, entry)
    return result_str, entry
