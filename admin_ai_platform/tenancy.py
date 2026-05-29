"""
admin_ai_platform.tenancy
=========================

Foundational tenant resolution + feature-flag layer (independent copy of the
app.py TENANCY block, ~3934-4079). The tenancy *admin UI / blueprint* lands in
M6; this module is just the core every other module depends on:

  * ``current_tenant_id()``  — mode-aware. In ``self_host`` always returns the
    single tenant; in ``central`` resolves from the request context (embed key
    / admin session / explicit header) populated by the request pipeline.
  * ``tenant_has_feature()`` / ``list_tenant_features()`` — per-tenant flags
    backed by ``tenant_features``, lazy-seeded from ``_FEATURE_REGISTRY``,
    failing OPEN for unknown names so adding a gate never breaks production.
"""

from __future__ import annotations

import time as _time

from . import config
from .db import query_db, execute_db

# (feature_name, human_label, plan_tier_required, default_enabled, group)
_FEATURE_REGISTRY = [
    ("site_themes",        "Site Themes",                  "solo",       True,  "Design"),
    ("site_designs",       "Multi-Homepage Designs",       "growth",     True,  "Design"),
    ("deck_launch",        "Presentation deck launches",   "growth",     True,  "AI"),
    ("web_search",         "Web search tool",              "growth",     True,  "AI"),
    ("voice",              "Voice agent (TTS / STT)",      "growth",     True,  "AI"),
    ("generated_pages",    "AI-generated pages",           "growth",     True,  "AI"),
    ("agent_scope_slider", "Agent scope tightness slider", "growth",     True,  "AI"),
    ("custom_forms",       "Custom forms",                 "solo",       True,  "Capabilities"),
    ("mcp",                "MCP connectors",               "enterprise", True,  "Capabilities"),
    ("presentations",      "Presentations admin",          "growth",     True,  "Capabilities"),
    ("automations",        "Automations builder",          "growth",     True,  "Capabilities"),
    ("messaging",          "Email & SMS messaging",        "growth",     True,  "Capabilities"),
    ("chat_history",       "Chat history & transcripts",   "solo",       True,  "Capabilities"),
    ("reviews",            "Reviews collector",            "growth",     True,  "Capabilities"),
    ("scraper",            "Web scraper",                  "growth",     True,  "Capabilities"),
    ("rag_kb",             "Knowledge base (RAG)",         "growth",     True,  "Capabilities"),
    ("analytics",          "Analytics dashboard",          "growth",     True,  "Analytics"),
    ("cost_dashboard",     "Cost transparency dashboard",  "growth",     True,  "Analytics"),
    ("weekly_digest",      "Weekly AI activity digest",    "growth",     True,  "Analytics"),
]
_FEATURE_NAMES = {row[0] for row in _FEATURE_REGISTRY}
_FEATURE_DEFAULTS = {row[0]: row[3] for row in _FEATURE_REGISTRY}

_FEATURE_CACHE: dict = {}
_FEATURE_CACHE_TTL_SEC = 30


def current_tenant_id():
    """Return the active tenant id for this request.

    ``self_host``: always the single configured tenant. ``central``: resolved
    from the request context (set by embed-key auth in M7 or admin session in
    M2). Until those land, central also returns the default — call sites must
    use this helper rather than hardcoding 1 so the central resolution can be
    dropped in centrally later.
    """
    if config.is_self_host():
        return config.DEFAULT_TENANT_ID
    # central mode: look for a tenant id stashed on the Flask request context.
    try:
        from flask import g, has_request_context
        if has_request_context():
            tid = getattr(g, "tenant_id", None)
            if tid:
                return tid
    except Exception:
        pass
    return config.DEFAULT_TENANT_ID


def invalidate_tenant_features_cache(tenant_id=None):
    """Drop cached feature lookups so flag flips take effect immediately."""
    global _FEATURE_CACHE
    if tenant_id is None:
        _FEATURE_CACHE = {}
    else:
        _FEATURE_CACHE = {k: v for k, v in _FEATURE_CACHE.items() if k[0] != tenant_id}


def _ensure_tenant_feature_row(tenant_id, feature_name):
    """Lazy-seed a tenant_features row using the registry default (idempotent)."""
    default_enabled = _FEATURE_DEFAULTS.get(feature_name, True)
    try:
        execute_db(
            "INSERT INTO tenant_features (tenant_id, feature_name, enabled) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (tenant_id, feature_name) DO NOTHING",
            (tenant_id, feature_name, default_enabled),
        )
    except Exception as e:
        print(f"[features] could not lazy-seed {feature_name}: {e}")


def tenant_has_feature(name, tenant_id=None):
    """True if ``name`` is enabled for the tenant. Unknown names fail OPEN."""
    if tenant_id is None:
        tenant_id = current_tenant_id()
    cache_key = (tenant_id, name)
    cached = _FEATURE_CACHE.get(cache_key)
    now = _time.time()
    if cached is not None and cached[1] > now:
        return cached[0]

    if name not in _FEATURE_NAMES:
        _FEATURE_CACHE[cache_key] = (True, now + _FEATURE_CACHE_TTL_SEC)
        return True

    try:
        row = query_db(
            "SELECT enabled FROM tenant_features "
            "WHERE tenant_id = %s AND feature_name = %s",
            (tenant_id, name), fetchone=True,
        )
        if row is None:
            _ensure_tenant_feature_row(tenant_id, name)
            enabled = _FEATURE_DEFAULTS.get(name, True)
        else:
            enabled = bool(row.get("enabled"))
    except Exception as e:
        print(f"[features] tenant_has_feature({name}) failed: {e}; failing open")
        enabled = True

    _FEATURE_CACHE[cache_key] = (enabled, now + _FEATURE_CACHE_TTL_SEC)
    return enabled


def list_tenant_features(tenant_id=None):
    """Return the full feature roster for the Plans & Features UI."""
    if tenant_id is None:
        tenant_id = current_tenant_id()
    out = []
    for name, label, plan_tier, default_enabled, group in _FEATURE_REGISTRY:
        out.append({
            "name": name, "label": label, "plan_tier": plan_tier,
            "default_enabled": default_enabled, "group": group,
            "enabled": tenant_has_feature(name, tenant_id),
        })
    return out
