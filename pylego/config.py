"""pylego.config — one typed, env-driven settings object for every pylego knob.

Ported from @altay/typed-config: a single place that reads environment
variables once, coerces them to the right type, and exposes them as a frozen
dataclass with safe defaults. No third-party dependency (stdlib only) so it can
never fail to import on a fresh host.

Every feature defaults to the *least disruptive* setting:
  * observability defaults ON but to local structured logging only (no external
    calls, no behavior change) — it upgrades to Langfuse automatically when keys
    are present.
  * The heavier behavior-affecting modules (reliability/context/safety, added in
    later tasks) default OFF here and are turned on deliberately.

Read once at import via `get_config()`; call `reload_config()` in tests after
monkeypatching os.environ.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class PylegoConfig:
    # ---- Master kill switch (Phase 6 safety) --------------------------------
    # When False, EVERY pylego enhancement reverts to pre-pylego behavior: no
    # activity DB writes, and all behavior knobs report their inert value (even
    # if individually enabled via DB/env). One switch to "turn it all off".
    ai_enhancements_enabled: bool

    # ---- Observability (task 026) -------------------------------------------
    # Master switch for the obs wrapper. When False, observe_admin_turn is a
    # pure pass-through (zero overhead, no logging).
    obs_enabled: bool
    # Emit a structured local log line per admin turn (cheap, no external dep).
    obs_local_logging: bool
    # Langfuse lights up automatically ONLY when enabled AND both keys exist.
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_base_url: str

    # ---- Error tracking / Sentry mute toggle (task 084) ---------------------
    # Super-admin "mute" switch for Sentry. Defaults ON. This does NOT turn
    # Sentry on by itself — Sentry only runs when the SENTRY_DSN secret is set
    # (owner action). When a DSN IS set, flipping this OFF makes before_send
    # drop every event (a live mute) without a restart. Deliberately NOT listed
    # in core._AI_INERT: error tracking is observability and must survive the AI
    # master kill-switch, so when the master is OFF this falls through to
    # env/default (True) rather than being forced off. It can only MUTE — it is
    # not a code-exec/RCE surface — so a DB-backed knob is acceptable here.
    error_tracking_enabled: bool

    # ---- Reliability (task 027) — ALL default to no-op / current behavior ----
    # Each of these is inert at its default value: timeout 0 = "use SDK default"
    # (no change), retries 0 = "no extra attempts" (current behavior), fallback
    # off, rate limit off. Operators opt in via env for production.
    llm_timeout_seconds: float        # per-call timeout; <=0 → unchanged (SDK default)
    llm_max_retries: int              # extra attempts on transient stream-open errors; 0 → none
    provider_fallback_enabled: bool   # try the other provider if the primary fails to open
    admin_chat_fallback_model: str    # model name to use for the fallback provider ("" → no fallback)
    admin_rate_limit_enabled: bool
    admin_rate_limit_max: int         # requests per window
    admin_rate_limit_window_seconds: int
    admin_rate_limit_store: str       # "postgres" (cluster-wide) | "memory" (per-process)

    # ---- Smarter context (task 028 — defaults off / current behavior) -------
    history_token_budget: int         # 0 == disabled (keep fixed-turn behavior)
    history_summarize_enabled: bool   # task 032: summarize dropped turns vs plain drop
    respcache_enabled: bool
    respcache_threshold: float

    # ---- Per-request model routing (task 040 — Epic C / speed) --------------
    # When enabled, short/simple turns are routed to a cheaper/faster model so
    # trivial lookups don't pay for the flagship model. All inert at default:
    # routing off → every turn uses the configured default model (no change).
    model_routing_enabled: bool       # master toggle for routing; False → identity
    fast_model: str                   # model name for "simple" turns ("" → no routing)
    routing_simple_max_chars: int     # a turn is "simple" if user message length <= this
    # task 041: Anthropic prompt caching on the big static system prompt. When
    # on, the system prompt is sent as a cache_control block so repeated turns
    # reuse it (cheaper + faster). Inert default OFF (system sent as a plain
    # string = current request shape). OpenAI caches automatically — no knob.
    prompt_cache_enabled: bool

    # ---- Datahub AI-define (task 083) ---------------------------------------
    # Tunables for the Datahub "AI define" feature (drafting the semantic layer
    # for a connected DB). These are deliberately NOT inert under the AI master
    # kill-switch (see core._AI_INERT): AI-define is an explicit, super-admin
    # action that must keep working even when the per-turn AI enhancements are
    # off, so get_ai_setting falls through to these env/default values.
    #   * max_tokens — output-token budget PER one-table LLM draft. The old code
    #     hardcoded 2000 and sent ALL tables in one call, so a wide/large schema
    #     overflowed and the JSON was silently truncated (the core bug). Raised
    #     to 8000 AND the work is now split one-table-per-call, so each table
    #     gets the full budget.
    #   * max_tables — safety cap on how many objects an "all" run will define in
    #     one request (each is its own LLM call → bounds cost/latency). Anything
    #     beyond the cap is flagged `truncated` so the admin can re-run. Was an
    #     internal 12 (a truncation workaround); 40 is sane now that calls split.
    #   * input_chars — max characters of the per-call schema+samples blob sent to
    #     the model (replaces the old global [:14000] that silently dropped whole
    #     tables once the single combined blob got large).
    datahub_define_max_tokens: int
    datahub_define_max_tables: int
    datahub_define_input_chars: int

    # ---- Visitor CRM / profiles (task 042 — Epic D) -------------------------
    # When enabled, a fail-open background updater extracts soft signals
    # (interests/needs/lead_score/consent) from each visitor turn and upserts a
    # visitor_profiles row. Inert default OFF → no extra LLM call, table stays
    # empty, visitor chat behaves exactly as before.
    visitor_profiles_enabled: bool
    visitor_profiles_model: str       # model for the tiny extraction call ("" → use the default)

    # ---- Newsletter signup (task 043 — Epic D) ------------------------------
    # Gate for the visitor `subscribe_newsletter` agent tool. Inert default OFF:
    # the tool exists in the registry but politely declines until a super-admin
    # turns this on, so a fresh fork never silently captures email signups.
    newsletter_signup_enabled: bool

    # ---- Offers / deals (task 044 — Epic D) ---------------------------------
    # Gate for the visitor `lookup_offers` tool (contextual promo surfacing).
    # Inert default OFF: the tool returns nothing until a super-admin turns it
    # on AND has defined offers, so a fresh fork surfaces no promotions.
    offers_enabled: bool

    # ---- Agentic growth tools (task 045 — Epic D) ---------------------------
    # Three independent gates, all inert-OFF by default. `team_notify_*` are the
    # OPERATOR-configured destinations for notify_team — the visitor/agent can
    # NEVER specify a recipient, only the subject/message, so the tool can't be
    # used to email/text arbitrary third parties.
    lead_capture_enabled: bool        # capture_lead writes a leads row
    callback_requests_enabled: bool   # request_callback writes a callback row
    team_notifications_enabled: bool  # notify_team (+ optional notify on capture)
    team_notify_email: str            # where notify_team emails go ("" → no email)
    team_notify_sms: str              # where notify_team texts go ("" → no SMS)

    # ---- Visitor persona router (task 046 — Epic E) -------------------------
    # When enabled, a cheap classifier routes each visitor turn to a super-admin
    # -defined persona (specialist agent) that constrains tools + augments the
    # prompt (+ optional model). Inert default OFF → single-agent behavior.
    visitor_persona_router_enabled: bool
    visitor_persona_router_model: str  # classifier model ("" → gpt-4o-mini)

    # ---- Visitor specialist router (task 079 Phase 2 — speed) ----------------
    # Operator master for the hybrid keyword→embedding→tiny-classifier router
    # that picks a specialist sub-prompt + smaller tool subset per visitor turn.
    # Inert default OFF → single-agent behavior (today's flow). The model knob
    # ("" → gpt-4o-mini) is the cheap classifier used only on ambiguity; the
    # threshold is the embedding-match confidence cutoff before falling back to
    # the classifier.
    visitor_specialist_router_enabled: bool
    visitor_specialist_router_model: str    # classifier model ("" → gpt-4o-mini)
    visitor_specialist_embed_threshold: float  # cosine cutoff before AI classifier

    # ---- Handoff summary (task 048 — Epic F, no-creds part) -----------------
    # When on, request_callback generates a short AI summary of the conversation
    # for the team handoff (stored + included in the notification). Inert default
    # OFF → no extra LLM call, callbacks behave as in task 045.
    handoff_summary_enabled: bool
    handoff_summary_model: str         # model for the summary ("" → gpt-4o-mini)

    # ---- Meetings / book_meeting (task 047 — Epic F) ------------------------
    # Gate for the visitor book_meeting tool. Inert default OFF. The calendar
    # push is OPTIONAL: when meeting_calendar_mcp_server names a connected MCP
    # server, book_meeting attempts to create a real event via that server's
    # tool; otherwise it just records the request for the team (no creds needed).
    meetings_enabled: bool
    meeting_default_duration_minutes: int
    meeting_calendar_mcp_server: str   # mcp_servers.name to push events to ("" → store-only)
    meeting_calendar_tool: str         # tool name on that server ("" → 'create_event')

    # ---- Research & Content Engine (Phase 8 / task 062) ---------------------
    # All inert-OFF by default so a fresh fork is unaffected. research_hub gates
    # the gathered-sources + Deep Research; content_studio gates generation;
    # visual_content gates image/diagram/clip generation; autopublish lets
    # trusted content types publish without the manual review step (off = always
    # draft → approve). research_max_sources caps Deep Research fan-out (cost).
    research_hub_enabled: bool
    content_studio_enabled: bool
    visual_content_enabled: bool
    autopublish_enabled: bool
    research_max_sources: int
    research_model: str        # model for synthesis ("" → default)
    content_model: str         # model for content generation ("" → default)
    image_model: str           # visual model id ("" → provider default)

    # ---- Live AI phone call (task 049 — Epic F) -----------------------------
    # Gate for the Twilio Voice webhook routing inbound calls to the AI. Inert
    # default OFF → the webhook politely declines. The live media bridge needs a
    # public wss endpoint (voice_wss_url) streaming to a realtime voice model —
    # the credential/infra leg, deferred to an operator runbook. With no wss set,
    # the call gets a spoken fallback message (no media bridge).
    live_call_enabled: bool
    voice_wss_url: str                 # wss:// media-stream endpoint ("" → spoken fallback)
    voice_greeting: str                # greeting spoken before connecting

    # ---- Activity logging (task 031) ----------------------------------------
    activity_logging_enabled: bool    # persist each admin-AI turn to ai_activity_log

    # ---- Knowledge base ingestion (Phase 6 / task 039) ----------------------
    # When True, KB uploads run the extract+chunk+embed pipeline in a background
    # thread (upload returns immediately); when False (default) it runs inline as
    # before. Lets a client drop many large docs without blocking the request.
    async_ingestion_enabled: bool

    # ---- Visitor AI reliability/context (Phase 6 / task 035) ----------------
    # Separate from the admin knobs because the visitor endpoint is public +
    # higher-volume. All inert at default (= current visitor behavior).
    visitor_llm_max_retries: int
    visitor_provider_fallback_enabled: bool
    visitor_fallback_model: str
    visitor_history_token_budget: int
    visitor_max_tool_rounds: int
    visitor_max_tool_rounds_complex: int

    # ---- Safety (task 029) --------------------------------------------------
    # sqlguard/structured default OFF (they can affect behavior — they're a
    # stricter layer on top of the monolith's existing guards). redact defaults
    # ON because it only sanitizes observability output (logs/traces) — it can
    # never change app behavior, responses, or stored data, so it's safe-by-default.
    sqlguard_enabled: bool
    structured_enabled: bool
    redact_enabled: bool

    # ---- AI guardrails (task 096) -------------------------------------------
    # daily_spend_cap_usd: pause ALL AI when today's total cost (chat+voice+sms)
    # reaches this many USD. 0.0 = disabled (default) → no cap, no extra spend
    # query. Amount-only — NOT in core._AI_INERT; falls back to 0.0 under the
    # master kill-switch (same pattern as rate_limit_max).
    daily_spend_cap_usd: float
    # safety_filter_enabled: when ON, append a softening instruction to the
    # visitor concierge's system prompt (professional/family-friendly, no
    # profanity). Inert-OFF under the master kill-switch.
    safety_filter_enabled: bool

    # ---- CRM segment thresholds (task 100 §2.7) -----------------------------
    # Super-admin lead-score cutoffs for the Contacts segments: Hot >= crm_hot_min,
    # Warm >= crm_warm_min (and < hot), New below. Amount-only (NOT in _AI_INERT).
    crm_hot_min: int
    crm_warm_min: int

    # escalation_enabled (task 101 §3.5): when ON, the visitor concierge proactively
    # offers a human handoff / callback when it's stuck or the visitor is frustrated.
    # Inert-OFF under the master kill-switch (behavior toggle).
    escalation_enabled: bool

    @property
    def langfuse_active(self) -> bool:
        """True only when obs is on AND real Langfuse keys are present."""
        return bool(self.obs_enabled and self.langfuse_public_key
                    and self.langfuse_secret_key)


def _build() -> PylegoConfig:
    return PylegoConfig(
        # Master switch: ON by default (enhancements available). Set
        # AI_ENHANCEMENTS_ENABLED=0 to revert everything to pre-pylego behavior.
        ai_enhancements_enabled=_env_bool("AI_ENHANCEMENTS_ENABLED", True),
        # Observability: ON by default but local-logging only (non-disruptive).
        obs_enabled=_env_bool("PYLEGO_OBS_ENABLED", True),
        obs_local_logging=_env_bool("PYLEGO_OBS_LOCAL_LOGGING", True),
        langfuse_public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip(),
        langfuse_secret_key=os.environ.get("LANGFUSE_SECRET_KEY", "").strip(),
        langfuse_base_url=os.environ.get(
            "LANGFUSE_BASE_URL", "https://cloud.langfuse.com").strip(),
        # Error tracking (Sentry) mute toggle — wired in 084. Default ON; only
        # has any effect once SENTRY_DSN is set (then OFF = drop all events).
        error_tracking_enabled=_env_bool("ERROR_TRACKING_ENABLED", True),
        # Reliability — wired in 027; defaults are INERT (= current behavior).
        llm_timeout_seconds=_env_float("ADMIN_CHAT_LLM_TIMEOUT", 0.0),     # 0 → SDK default
        llm_max_retries=_env_int("ADMIN_CHAT_LLM_MAX_RETRIES", 0),         # 0 → no extra attempts
        provider_fallback_enabled=_env_bool("ADMIN_CHAT_PROVIDER_FALLBACK", False),
        admin_chat_fallback_model=os.environ.get("ADMIN_CHAT_FALLBACK_MODEL", "").strip(),
        admin_rate_limit_enabled=_env_bool("ADMIN_CHAT_RATE_LIMIT_ENABLED", False),
        admin_rate_limit_max=_env_int("ADMIN_CHAT_RATE_LIMIT_MAX", 60),
        admin_rate_limit_window_seconds=_env_int("ADMIN_CHAT_RATE_LIMIT_WINDOW", 60),
        admin_rate_limit_store=os.environ.get("ADMIN_CHAT_RATE_LIMIT_STORE", "postgres").strip().lower(),
        # Smarter context — wired in 028.
        history_token_budget=_env_int("ADMIN_CHAT_HISTORY_TOKEN_BUDGET", 0),
        history_summarize_enabled=_env_bool("ADMIN_CHAT_HISTORY_SUMMARIZE", False),
        respcache_enabled=_env_bool("ADMIN_RESPCACHE_ENABLED", False),
        respcache_threshold=_env_float("ADMIN_RESPCACHE_THRESHOLD", 0.93),
        # Per-request model routing — wired in 040; inert default (routing off).
        model_routing_enabled=_env_bool("MODEL_ROUTING_ENABLED", False),
        fast_model=os.environ.get("MODEL_ROUTING_FAST_MODEL", "").strip(),
        routing_simple_max_chars=_env_int("MODEL_ROUTING_SIMPLE_MAX_CHARS", 280),
        prompt_cache_enabled=_env_bool("PROMPT_CACHE_ENABLED", False),
        # Datahub AI-define — wired in 083. Defaults are the new healthy values;
        # all overridable via env or the AI Control panel (group "Datahub").
        datahub_define_max_tokens=_env_int("DATAHUB_DEFINE_MAX_TOKENS", 8000),
        datahub_define_max_tables=_env_int("DATAHUB_DEFINE_MAX_TABLES", 40),
        datahub_define_input_chars=_env_int("DATAHUB_DEFINE_INPUT_CHARS", 14000),
        # Visitor CRM — wired in 042; inert default (no profiling).
        visitor_profiles_enabled=_env_bool("VISITOR_PROFILES_ENABLED", False),
        visitor_profiles_model=os.environ.get("VISITOR_PROFILES_MODEL", "").strip(),
        # Newsletter signup — wired in 043; inert default (tool declines).
        newsletter_signup_enabled=_env_bool("NEWSLETTER_SIGNUP_ENABLED", False),
        # Offers — wired in 044; inert default (tool returns nothing).
        offers_enabled=_env_bool("OFFERS_ENABLED", False),
        # Agentic growth tools — wired in 045; inert defaults (tools decline).
        lead_capture_enabled=_env_bool("LEAD_CAPTURE_ENABLED", False),
        callback_requests_enabled=_env_bool("CALLBACK_REQUESTS_ENABLED", False),
        team_notifications_enabled=_env_bool("TEAM_NOTIFICATIONS_ENABLED", False),
        team_notify_email=os.environ.get("TEAM_NOTIFY_EMAIL", "").strip(),
        team_notify_sms=os.environ.get("TEAM_NOTIFY_SMS", "").strip(),
        # Visitor persona router — wired in 046; inert default (single agent).
        visitor_persona_router_enabled=_env_bool("VISITOR_PERSONA_ROUTER_ENABLED", False),
        visitor_persona_router_model=os.environ.get("VISITOR_PERSONA_ROUTER_MODEL", "").strip(),
        # Visitor specialist router — wired in 079 P2; inert default (single agent).
        visitor_specialist_router_enabled=_env_bool("VISITOR_SPECIALIST_ROUTER_ENABLED", False),
        visitor_specialist_router_model=os.environ.get("VISITOR_SPECIALIST_ROUTER_MODEL", "").strip(),
        visitor_specialist_embed_threshold=_env_float("VISITOR_SPECIALIST_EMBED_THRESHOLD", 0.78),
        # Handoff summary — wired in 048; inert default (no summary).
        handoff_summary_enabled=_env_bool("HANDOFF_SUMMARY_ENABLED", False),
        handoff_summary_model=os.environ.get("HANDOFF_SUMMARY_MODEL", "").strip(),
        # Meetings — wired in 047; inert default (tool declines).
        meetings_enabled=_env_bool("MEETINGS_ENABLED", False),
        meeting_default_duration_minutes=_env_int("MEETING_DEFAULT_DURATION_MINUTES", 30),
        meeting_calendar_mcp_server=os.environ.get("MEETING_CALENDAR_MCP_SERVER", "").strip(),
        meeting_calendar_tool=os.environ.get("MEETING_CALENDAR_TOOL", "").strip(),
        # Research & Content Engine — wired in Phase 8; inert defaults.
        research_hub_enabled=_env_bool("RESEARCH_HUB_ENABLED", False),
        content_studio_enabled=_env_bool("CONTENT_STUDIO_ENABLED", False),
        visual_content_enabled=_env_bool("VISUAL_CONTENT_ENABLED", False),
        autopublish_enabled=_env_bool("AUTOPUBLISH_ENABLED", False),
        research_max_sources=_env_int("RESEARCH_MAX_SOURCES", 8),
        research_model=os.environ.get("RESEARCH_MODEL", "").strip(),
        content_model=os.environ.get("CONTENT_MODEL", "").strip(),
        image_model=os.environ.get("IMAGE_MODEL", "").strip(),
        # Live AI phone call — wired in 049; inert default (webhook declines).
        live_call_enabled=_env_bool("LIVE_CALL_ENABLED", False),
        voice_wss_url=os.environ.get("VOICE_WSS_URL", "").strip(),
        voice_greeting=os.environ.get(
            "VOICE_GREETING", "Hello! Connecting you to our AI assistant.").strip(),
        # Activity logging — wired in 031 (default ON: low-volume admin turns).
        activity_logging_enabled=_env_bool("ADMIN_CHAT_ACTIVITY_LOGGING", True),
        # KB ingestion — wired in 039; inert default (inline ingestion).
        async_ingestion_enabled=_env_bool("KB_ASYNC_INGESTION", False),
        # Visitor reliability/context — wired in 035; inert defaults.
        visitor_llm_max_retries=_env_int("VISITOR_CHAT_LLM_MAX_RETRIES", 0),
        visitor_provider_fallback_enabled=_env_bool("VISITOR_CHAT_PROVIDER_FALLBACK", False),
        visitor_fallback_model=os.environ.get("VISITOR_CHAT_FALLBACK_MODEL", "").strip(),
        visitor_history_token_budget=_env_int("VISITOR_CHAT_HISTORY_TOKEN_BUDGET", 0),
        # Tool-round budgets for the visitor concierge (admin-controlled).
        # Normal = everyday quick questions; complex = auto-applied to broad,
        # research-heavy asks. Default 4/6 = current behavior + a modest bump.
        visitor_max_tool_rounds=_env_int("VISITOR_CHAT_MAX_TOOL_ROUNDS", 4),
        visitor_max_tool_rounds_complex=_env_int("VISITOR_CHAT_MAX_TOOL_ROUNDS_COMPLEX", 6),
        # Safety — wired in 029.
        sqlguard_enabled=_env_bool("ADMIN_SQLGUARD_ENABLED", False),
        structured_enabled=_env_bool("ADMIN_STRUCTURED_ARGS_ENABLED", False),
        redact_enabled=_env_bool("ADMIN_REDACT_ENABLED", True),  # log-only → safe default-on
        # AI guardrails — wired in 096. Inert at default (no cap, filter off).
        daily_spend_cap_usd=_env_float("DAILY_SPEND_CAP_USD", 0.0),
        safety_filter_enabled=_env_bool("SAFETY_FILTER_ENABLED", False),
        # CRM segment thresholds — wired in 100 §2.7.
        crm_hot_min=_env_int("CRM_HOT_MIN", 80),
        crm_warm_min=_env_int("CRM_WARM_MIN", 50),
        escalation_enabled=_env_bool("ESCALATION_ENABLED", False),
    )


_CONFIG: PylegoConfig | None = None
_LOCK = threading.Lock()


def get_config() -> PylegoConfig:
    """Return the process-wide config, building it once on first use."""
    global _CONFIG
    if _CONFIG is None:
        with _LOCK:
            if _CONFIG is None:
                _CONFIG = _build()
    return _CONFIG


def reload_config() -> PylegoConfig:
    """Rebuild from the current environment (test helper)."""
    global _CONFIG
    with _LOCK:
        _CONFIG = _build()
    return _CONFIG
