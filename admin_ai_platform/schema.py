"""
admin_ai_platform.schema
========================

Schema bootstrapper — an independent, *pruned* copy of the original
``init_db()`` containing only the tables this package owns (the IN set; see
PLAN.md → "The boundary"). Every statement is ``CREATE ... IF NOT EXISTS`` /
``ADD COLUMN IF NOT EXISTS`` so it is idempotent and safe to re-run on every
boot.

Scope grows per milestone: this M0/M1 cut covers the foundation (tenancy +
feature flags + cost ledgers) and the visitor-chat slice (gallery, chat, forms,
uploads, generated pages, voice, presentations, skills, provider). Later
milestones append their tables here (admin chat, MCP, RAG, automations,
scraper, reviews, messaging, commerce).

Public-web-only tables (sphere_settings, site_designs, blog_posts editors,
etc.) are intentionally NOT created here — they live with the original app.
A handful of AI-referenced content tables that have *no editor* in this package
(blog/team/faq/etc.) are added in later milestones as data-only.
"""

from __future__ import annotations

from .db import get_db

# Tables the package owns at this milestone — used by the verification test to
# assert presence, and to document the growing surface.
IN_TABLES_M0_M1 = (
    "plans", "tenants", "platform_setup", "tenant_features", "feature_addons",
    "managed_defaults", "managed_override_history", "fleet_bundles",
    "gallery_cards", "chatbot_settings", "chat_conversations", "chat_messages",
    "page_views",
    "uploaded_images", "custom_forms", "form_fields", "form_submissions",
    "generated_pages", "voice_settings", "voice_intros", "voice_usage_log",
    "presentations", "presentation_slides", "agent_skills", "skill_usage_log",
    "agent_provider_settings", "model_prices", "api_cost_events",
    "voice_cost_events", "sms_cost_events", "tenant_cost_caps", "cost_alerts",
    "weekly_digest_sends",
    # M2
    "admin_chat_messages", "admin_chat_sessions", "admin_pending_actions",
    # M3
    "custom_knowledge_entries", "custom_webhook_skills", "custom_sql_skills",
    "mcp_servers", "mcp_tools_cache",
    # M4
    "automations", "automation_runs", "automation_versions",
    "automation_settings", "automation_webhook_rejections",
    "scraper_settings", "scrape_jobs", "scrape_schedules",
    # M5
    "subscribers", "messaging_templates", "messaging_campaigns", "messaging_log",
    "review_destinations", "review_requests", "external_reviews", "review_settings",
    # M6
    "products", "customers", "orders", "order_items", "services", "service_addons",
    "service_availability_rules", "service_availability_overrides", "service_bookings",
    "stripe_settings", "stripe_product_sync", "stripe_events", "tenant_embed_keys",
    "sso_used_jtis", "rate_buckets",
    # M12
    "events", "event_rsvps",
    # M13
    "experiences", "pricing_seasons", "testimonials", "team_members", "faqs",
    "blog_posts", "business_info", "custom_section_items",
)

# Tables that belong to the original public website and must NOT be created by
# this package (used by the negative assertion in the schema test).
OUT_TABLES = ("sphere_settings", "sphere_images", "site_designs", "site_themes")


_DDL = r"""
-- ============================ TENANCY + PLANS ============================
CREATE TABLE IF NOT EXISTS plans (
    id          SERIAL PRIMARY KEY,
    slug        VARCHAR(40) NOT NULL UNIQUE,
    name        TEXT        NOT NULL,
    description TEXT        NOT NULL DEFAULT '',
    sort_order  INTEGER     NOT NULL DEFAULT 0,
    created_at  TIMESTAMP   DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tenants (
    id          SERIAL PRIMARY KEY,
    name        TEXT        NOT NULL DEFAULT 'Default Tenant',
    plan_id     INTEGER     REFERENCES plans(id) ON DELETE SET NULL,
    status      VARCHAR(20) NOT NULL DEFAULT 'active',
    timezone    VARCHAR(64) NOT NULL DEFAULT 'UTC',
    created_at  TIMESTAMP   DEFAULT NOW(),
    updated_at  TIMESTAMP   DEFAULT NOW()
);
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) NOT NULL DEFAULT 'UTC';

-- First-run setup state (M17). The /setup wizard provisions once, sets this
-- completed=TRUE, and afterwards /setup returns 404. admin_password_hash, when
-- set, overrides the env ADMIN_PASSWORD (pbkdf2-hmac-sha256 + per-install salt).
CREATE TABLE IF NOT EXISTS platform_setup (
    id                  INTEGER PRIMARY KEY DEFAULT 1,
    completed           BOOLEAN NOT NULL DEFAULT FALSE,
    preset              VARCHAR(40) NOT NULL DEFAULT 'generic',
    business_name       TEXT NOT NULL DEFAULT '',
    admin_password_hash TEXT NOT NULL DEFAULT '',
    admin_password_salt TEXT NOT NULL DEFAULT '',
    completed_at        TIMESTAMP
);
INSERT INTO platform_setup (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- ============================ FLEET SYNC (M22) ==========================
-- Master-managed defaults with per-item versioning + local override. Master
-- pushes signed bundles over the VELO channel; each item carries a monotonic
-- version. A client edit pins a local value (is_overridden). Master can FORCE
-- past an override by bumping the version with force=true — the prior local
-- value is preserved as an override-of-record in managed_override_history.
CREATE TABLE IF NOT EXISTS managed_defaults (
    item_key         VARCHAR(160) PRIMARY KEY,
    category         VARCHAR(40) NOT NULL DEFAULT '',
    master_version   INTEGER NOT NULL DEFAULT 0,
    master_value     JSONB NOT NULL DEFAULT 'null'::jsonb,
    local_value      JSONB,                          -- NULL = following master
    is_overridden    BOOLEAN NOT NULL DEFAULT FALSE,
    override_version INTEGER,                         -- master_version at override time
    updated_at       TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_managed_defaults_cat ON managed_defaults (category);

-- Override-of-record: a client's local value preserved when master force-wins.
CREATE TABLE IF NOT EXISTS managed_override_history (
    id                    SERIAL PRIMARY KEY,
    item_key              VARCHAR(160) NOT NULL,
    local_value           JSONB,
    override_version      INTEGER,
    superseded_by_version INTEGER,
    created_at            TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_managed_override_hist_key ON managed_override_history (item_key);

-- Applied bundle log: idempotency + monotonic downgrade/replay protection. A
-- bundle whose version <= the latest applied is rejected.
CREATE TABLE IF NOT EXISTS fleet_bundles (
    bundle_version INTEGER PRIMARY KEY,
    item_count     INTEGER NOT NULL DEFAULT 0,
    note           TEXT NOT NULL DEFAULT '',
    applied_at     TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tenant_features (
    id           SERIAL PRIMARY KEY,
    tenant_id    INTEGER     NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    feature_name VARCHAR(80) NOT NULL,
    enabled      BOOLEAN     NOT NULL DEFAULT true,
    note         TEXT        NOT NULL DEFAULT '',
    created_at   TIMESTAMP   DEFAULT NOW(),
    updated_at   TIMESTAMP   DEFAULT NOW(),
    UNIQUE(tenant_id, feature_name)
);
CREATE INDEX IF NOT EXISTS idx_tenant_features_tenant ON tenant_features (tenant_id);

CREATE TABLE IF NOT EXISTS feature_addons (
    id           SERIAL PRIMARY KEY,
    tenant_id    INTEGER     NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    feature_name VARCHAR(80) NOT NULL,
    granted_at   TIMESTAMP   DEFAULT NOW(),
    note         TEXT        NOT NULL DEFAULT '',
    UNIQUE(tenant_id, feature_name)
);

-- ============================ CONTENT (AI-referenced) ====================
CREATE TABLE IF NOT EXISTS gallery_cards (
    id          SERIAL PRIMARY KEY,
    slug        VARCHAR(100) UNIQUE NOT NULL,
    title       TEXT NOT NULL,
    subtitle    TEXT NOT NULL,
    image_url   TEXT NOT NULL,
    video_url   TEXT NOT NULL DEFAULT '',
    category    VARCHAR(50) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    details     JSONB DEFAULT '[]'::jsonb,
    price       TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_gallery_cards_sort ON gallery_cards (sort_order);
ALTER TABLE gallery_cards ADD COLUMN IF NOT EXISTS video_url TEXT NOT NULL DEFAULT '';

-- ============================ CHATBOT + CHAT =============================
CREATE TABLE IF NOT EXISTS chatbot_settings (
    id            SERIAL PRIMARY KEY,
    enabled       BOOLEAN NOT NULL DEFAULT false,
    mode          TEXT NOT NULL DEFAULT 'builtin',
    agent_name    TEXT NOT NULL DEFAULT 'AI Assistant',
    agent_role    TEXT NOT NULL DEFAULT 'Assistant',
    agent_avatar  TEXT NOT NULL DEFAULT 'A',
    greeting      TEXT NOT NULL DEFAULT 'Welcome! I''m your AI assistant. How can I help you today?',
    quick_prompts JSONB DEFAULT '["Browse our gallery", "Tell me more", "What do you offer?", "Show me pricing"]'::jsonb,
    api_endpoint  TEXT NOT NULL DEFAULT '/api/chat',
    embed_code    TEXT NOT NULL DEFAULT '',
    system_prompt TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_conversations (
    id          SERIAL PRIMARY KEY,
    session_id  VARCHAR(100) NOT NULL,
    visitor_id  VARCHAR(100) DEFAULT '',
    visitor_ip  VARCHAR(45) DEFAULT '',
    device_type VARCHAR(20) DEFAULT 'desktop',
    user_agent  TEXT DEFAULT '',
    started_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chat_conv_session ON chat_conversations (session_id);

CREATE TABLE IF NOT EXISTS chat_messages (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER REFERENCES chat_conversations(id) ON DELETE CASCADE,
    role            VARCHAR(20) NOT NULL DEFAULT 'user',
    content         TEXT NOT NULL DEFAULT '',
    command_json    JSONB,
    tool_calls_json JSONB,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chat_msg_conv ON chat_messages (conversation_id);
-- tool_calls_json was added after the original chat_messages shipped; keep the
-- idempotent add so an older DB upgrades cleanly.
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS tool_calls_json JSONB;

-- Visitor pageview analytics (M15). One row per tracked view; duration is
-- patched in later via the sendBeacon /api/track/duration call on unload.
CREATE TABLE IF NOT EXISTS page_views (
    id            SERIAL PRIMARY KEY,
    tenant_id     INTEGER NOT NULL DEFAULT 1,
    session_id    VARCHAR(100) NOT NULL DEFAULT '',
    visitor_id    VARCHAR(100) NOT NULL DEFAULT '',
    url           TEXT NOT NULL DEFAULT '',
    path          TEXT NOT NULL DEFAULT '',
    referrer      TEXT NOT NULL DEFAULT '',
    utm_source    VARCHAR(200) NOT NULL DEFAULT '',
    utm_medium    VARCHAR(200) NOT NULL DEFAULT '',
    utm_campaign  VARCHAR(200) NOT NULL DEFAULT '',
    device_type   VARCHAR(20) NOT NULL DEFAULT 'desktop',
    browser       VARCHAR(40) NOT NULL DEFAULT '',
    os            VARCHAR(40) NOT NULL DEFAULT '',
    screen        VARCHAR(20) NOT NULL DEFAULT '',
    language      VARCHAR(20) NOT NULL DEFAULT '',
    duration_ms   INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_page_views_created ON page_views (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_page_views_session ON page_views (session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_page_views_path ON page_views (tenant_id, path);

CREATE TABLE IF NOT EXISTS uploaded_images (
    id            SERIAL PRIMARY KEY,
    filename      TEXT NOT NULL,
    original_name TEXT NOT NULL DEFAULT '',
    file_size     INTEGER DEFAULT 0,
    uploaded_at   TIMESTAMP DEFAULT NOW()
);

-- ============================ FORMS =====================================
CREATE TABLE IF NOT EXISTS custom_forms (
    id                SERIAL PRIMARY KEY,
    name              TEXT NOT NULL DEFAULT '',
    slug              VARCHAR(100) NOT NULL UNIQUE,
    description       TEXT NOT NULL DEFAULT '',
    status            VARCHAR(20) NOT NULL DEFAULT 'active',
    submit_button_text TEXT NOT NULL DEFAULT 'Submit',
    success_message   TEXT NOT NULL DEFAULT 'Thank you! Your submission has been received.',
    created_at        TIMESTAMP DEFAULT NOW(),
    updated_at        TIMESTAMP DEFAULT NOW(),
    sort_order        INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS form_fields (
    id              SERIAL PRIMARY KEY,
    form_id         INTEGER NOT NULL REFERENCES custom_forms(id) ON DELETE CASCADE,
    field_type      VARCHAR(30) NOT NULL DEFAULT 'text',
    label           TEXT NOT NULL DEFAULT '',
    name            VARCHAR(100) NOT NULL DEFAULT '',
    placeholder     TEXT NOT NULL DEFAULT '',
    required        BOOLEAN NOT NULL DEFAULT false,
    options         JSONB,
    default_value   TEXT NOT NULL DEFAULT '',
    sort_order      INTEGER DEFAULT 0,
    width           VARCHAR(10) NOT NULL DEFAULT 'full',
    validation_regex TEXT NOT NULL DEFAULT '',
    help_text       TEXT NOT NULL DEFAULT '',
    step            INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_form_fields_form ON form_fields (form_id);
ALTER TABLE form_fields ADD COLUMN IF NOT EXISTS step INTEGER NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS form_submissions (
    id                SERIAL PRIMARY KEY,
    form_id           INTEGER NOT NULL REFERENCES custom_forms(id) ON DELETE CASCADE,
    submission_data   JSONB NOT NULL DEFAULT '{}'::jsonb,
    status            VARCHAR(20) NOT NULL DEFAULT 'new',
    confirmation_number TEXT DEFAULT '',
    device_type       VARCHAR(20) DEFAULT 'desktop',
    user_agent        TEXT DEFAULT '',
    referrer_url      TEXT DEFAULT '',
    utm_source        TEXT DEFAULT '',
    utm_medium        TEXT DEFAULT '',
    utm_campaign      TEXT DEFAULT '',
    utm_term          TEXT DEFAULT '',
    utm_content       TEXT DEFAULT '',
    page_url          TEXT DEFAULT '',
    ip_address        VARCHAR(45) DEFAULT '',
    browser           TEXT DEFAULT '',
    os                TEXT DEFAULT '',
    screen_resolution TEXT DEFAULT '',
    language          TEXT DEFAULT '',
    session_id        TEXT DEFAULT '',
    updated_at        TIMESTAMP DEFAULT NOW(),
    submitted_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_form_sub_form ON form_submissions (form_id);
CREATE INDEX IF NOT EXISTS idx_form_sub_status ON form_submissions (status);
ALTER TABLE form_submissions ADD COLUMN IF NOT EXISTS confirmation_number TEXT DEFAULT '';
ALTER TABLE form_submissions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

-- ============================ GENERATED PAGES ===========================
CREATE TABLE IF NOT EXISTS generated_pages (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT 'Untitled Page',
    html        TEXT NOT NULL DEFAULT '',
    prompt      TEXT NOT NULL DEFAULT '',
    slug        VARCHAR(200) UNIQUE,
    status      VARCHAR(20) NOT NULL DEFAULT 'draft',
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_generated_pages_status ON generated_pages (status);

-- ============================ VOICE =====================================
CREATE TABLE IF NOT EXISTS voice_settings (
    id                       INTEGER PRIMARY KEY DEFAULT 1,
    enabled_intros           BOOLEAN NOT NULL DEFAULT false,
    enabled_visitor_voice    BOOLEAN NOT NULL DEFAULT false,
    enabled_ai_voice         BOOLEAN NOT NULL DEFAULT false,
    default_voice            TEXT NOT NULL DEFAULT 'alloy',
    tts_model                TEXT NOT NULL DEFAULT 'tts-1',
    autoplay_strategy        TEXT NOT NULL DEFAULT 'gesture',
    tts_provider             TEXT NOT NULL DEFAULT 'openai',
    stt_provider             TEXT NOT NULL DEFAULT 'webspeech',
    premium_enabled          BOOLEAN NOT NULL DEFAULT false,
    elevenlabs_voice_id      TEXT NOT NULL DEFAULT '',
    elevenlabs_model         TEXT NOT NULL DEFAULT 'eleven_turbo_v2_5',
    updated_at               TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS voice_intros (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL DEFAULT '',
    message_text    TEXT NOT NULL DEFAULT '',
    audio_url       TEXT NOT NULL DEFAULT '',
    voice_id        TEXT NOT NULL DEFAULT 'alloy',
    utm_source      TEXT NOT NULL DEFAULT '',
    utm_medium      TEXT NOT NULL DEFAULT '',
    utm_campaign    TEXT NOT NULL DEFAULT '',
    referrer_match  TEXT NOT NULL DEFAULT '',
    priority        INTEGER NOT NULL DEFAULT 0,
    enabled         BOOLEAN NOT NULL DEFAULT true,
    play_count      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_voice_intros_priority ON voice_intros (priority DESC, id);
CREATE INDEX IF NOT EXISTS idx_voice_intros_enabled ON voice_intros (enabled);

CREATE TABLE IF NOT EXISTS voice_usage_log (
    id            SERIAL PRIMARY KEY,
    session_id    VARCHAR(100) DEFAULT '',
    feature_type  VARCHAR(40) NOT NULL DEFAULT '',
    char_count    INTEGER NOT NULL DEFAULT 0,
    voice_id      TEXT NOT NULL DEFAULT '',
    intro_id      INTEGER,
    created_at    TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_voice_usage_created ON voice_usage_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_voice_usage_feature ON voice_usage_log (feature_type);

-- ============================ PRESENTATIONS =============================
CREATE TABLE IF NOT EXISTS presentations (
    id              SERIAL PRIMARY KEY,
    slug            VARCHAR(120) UNIQUE NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    cover_image_url TEXT NOT NULL DEFAULT '',
    source          VARCHAR(20) NOT NULL DEFAULT 'admin',
    auto_play       BOOLEAN NOT NULL DEFAULT false,
    enabled         BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_presentations_slug ON presentations (slug);

CREATE TABLE IF NOT EXISTS presentation_slides (
    id              SERIAL PRIMARY KEY,
    presentation_id INTEGER NOT NULL REFERENCES presentations(id) ON DELETE CASCADE,
    order_index     INTEGER NOT NULL DEFAULT 0,
    title           TEXT NOT NULL DEFAULT '',
    body            TEXT NOT NULL DEFAULT '',
    image_url       TEXT NOT NULL DEFAULT '',
    narration_text  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_presentation_slides_presentation ON presentation_slides (presentation_id, order_index);

-- ============================ SKILLS + PROVIDER =========================
CREATE TABLE IF NOT EXISTS agent_skills (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(100) UNIQUE NOT NULL,
    display_name    TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    category        VARCHAR(40) NOT NULL DEFAULT 'lookup',
    builtin         BOOLEAN NOT NULL DEFAULT true,
    enabled         BOOLEAN NOT NULL DEFAULT true,
    config_json     JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_skills_enabled ON agent_skills (enabled);
CREATE INDEX IF NOT EXISTS idx_agent_skills_category ON agent_skills (category);

CREATE TABLE IF NOT EXISTS skill_usage_log (
    id           SERIAL PRIMARY KEY,
    session_id   VARCHAR(100) DEFAULT '',
    skill_name   VARCHAR(100) NOT NULL DEFAULT '',
    args_json    JSONB,
    row_count    INTEGER NOT NULL DEFAULT 0,
    duration_ms  INTEGER NOT NULL DEFAULT 0,
    error        TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_skill_usage_skill ON skill_usage_log (skill_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_skill_usage_created ON skill_usage_log (created_at DESC);

CREATE TABLE IF NOT EXISTS agent_provider_settings (
    id            INTEGER PRIMARY KEY DEFAULT 1,
    provider      VARCHAR(20) NOT NULL DEFAULT 'openai',
    openai_model  TEXT NOT NULL DEFAULT 'gpt-4o-mini',
    claude_model  TEXT NOT NULL DEFAULT 'claude-sonnet-4-5',
    updated_at    TIMESTAMP DEFAULT NOW()
);

-- ============================ COST LEDGERS ==============================
CREATE TABLE IF NOT EXISTS model_prices (
    id                                SERIAL PRIMARY KEY,
    provider                          VARCHAR(40)  NOT NULL,
    model                             VARCHAR(120) NOT NULL,
    surface                           VARCHAR(40)  NOT NULL DEFAULT 'chat',
    input_price_per_million_tokens    NUMERIC(12,6),
    output_price_per_million_tokens   NUMERIC(12,6),
    tts_price_per_million_chars       NUMERIC(12,6),
    stt_price_per_minute              NUMERIC(12,6),
    sms_price_per_segment             NUMERIC(12,6),
    notes                             TEXT NOT NULL DEFAULT '',
    active                            BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at                        TIMESTAMP DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_model_prices_lookup ON model_prices (provider, model, surface);

CREATE TABLE IF NOT EXISTS api_cost_events (
    id                       SERIAL PRIMARY KEY,
    tenant_id                INTEGER NOT NULL DEFAULT 1,
    session_id               VARCHAR(100) NOT NULL DEFAULT '',
    visitor_id               VARCHAR(100) NOT NULL DEFAULT '',
    surface                  VARCHAR(40)  NOT NULL DEFAULT 'visitor_chat',
    provider                 VARCHAR(40)  NOT NULL DEFAULT '',
    model                    VARCHAR(120) NOT NULL DEFAULT '',
    prompt_tokens            INTEGER NOT NULL DEFAULT 0,
    completion_tokens        INTEGER NOT NULL DEFAULT 0,
    total_tokens             INTEGER NOT NULL DEFAULT 0,
    unit_input_price_usd     NUMERIC(14,8),
    unit_output_price_usd    NUMERIC(14,8),
    cost_usd                 NUMERIC(14,8),
    created_at               TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_api_cost_tenant_created ON api_cost_events (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_cost_tenant_surface ON api_cost_events (tenant_id, surface, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_cost_tenant_model ON api_cost_events (tenant_id, provider, model, created_at DESC);

CREATE TABLE IF NOT EXISTS voice_cost_events (
    id                       SERIAL PRIMARY KEY,
    tenant_id                INTEGER NOT NULL DEFAULT 1,
    session_id               VARCHAR(100) NOT NULL DEFAULT '',
    surface                  VARCHAR(40)  NOT NULL DEFAULT 'voice_tts',
    provider                 VARCHAR(40)  NOT NULL DEFAULT '',
    model                    VARCHAR(120) NOT NULL DEFAULT '',
    feature_type             VARCHAR(40)  NOT NULL DEFAULT '',
    voice_id                 TEXT NOT NULL DEFAULT '',
    char_count               INTEGER NOT NULL DEFAULT 0,
    audio_seconds            NUMERIC(10,3) NOT NULL DEFAULT 0,
    unit_tts_price_usd       NUMERIC(14,8),
    unit_stt_price_usd       NUMERIC(14,8),
    cost_usd                 NUMERIC(14,8),
    created_at               TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_voice_cost_tenant_created ON voice_cost_events (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS sms_cost_events (
    id                       SERIAL PRIMARY KEY,
    tenant_id                INTEGER NOT NULL DEFAULT 1,
    surface                  VARCHAR(40)  NOT NULL DEFAULT 'sms_outbound',
    provider                 VARCHAR(40)  NOT NULL DEFAULT 'twilio',
    to_number                VARCHAR(40)  NOT NULL DEFAULT '',
    message_sid              VARCHAR(80)  NOT NULL DEFAULT '',
    segments                 INTEGER,
    unit_sms_price_usd       NUMERIC(14,8),
    cost_usd                 NUMERIC(14,8),
    created_at               TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sms_cost_tenant_created ON sms_cost_events (tenant_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sms_cost_msgsid
    ON sms_cost_events (tenant_id, message_sid) WHERE message_sid <> '';

CREATE TABLE IF NOT EXISTS tenant_cost_caps (
    id                       SERIAL PRIMARY KEY,
    tenant_id                INTEGER NOT NULL UNIQUE,
    monthly_cap_usd          NUMERIC(12,2),
    warn_at_percent          INTEGER NOT NULL DEFAULT 80,
    cap_behavior             VARCHAR(20) NOT NULL DEFAULT 'alert_only',
    alert_email              TEXT NOT NULL DEFAULT '',
    digest_email             TEXT NOT NULL DEFAULT '',
    digest_send_hour_utc     INTEGER NOT NULL DEFAULT 9,
    last_warned_period       VARCHAR(10) NOT NULL DEFAULT '',
    last_capped_period       VARCHAR(10) NOT NULL DEFAULT '',
    updated_at               TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cost_alerts (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL,
    period          VARCHAR(10) NOT NULL,
    kind            VARCHAR(20) NOT NULL,
    spent_usd       NUMERIC(12,4) NOT NULL DEFAULT 0,
    cap_usd         NUMERIC(12,4) NOT NULL DEFAULT 0,
    sent_at         TIMESTAMP DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cost_alerts_unique ON cost_alerts (tenant_id, period, kind);

CREATE TABLE IF NOT EXISTS weekly_digest_sends (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL,
    week_start      DATE NOT NULL,
    sent_at         TIMESTAMP DEFAULT NOW(),
    payload_json    JSONB,
    UNIQUE(tenant_id, week_start)
);

-- ============================ ADMIN CHAT (M2) ===========================
CREATE TABLE IF NOT EXISTS admin_chat_messages (
    id              SERIAL PRIMARY KEY,
    session_id      VARCHAR(100) NOT NULL DEFAULT '',
    mode            VARCHAR(20)  NOT NULL DEFAULT 'admin',
    role            VARCHAR(20)  NOT NULL DEFAULT 'user',
    content         TEXT         NOT NULL DEFAULT '',
    tool_calls_json JSONB,
    tool_call_id    TEXT,
    tool_name       TEXT,
    usage_json      JSONB,
    tool_meta_json  JSONB,
    created_at      TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_admin_chat_session
    ON admin_chat_messages (session_id, mode, created_at);

CREATE TABLE IF NOT EXISTS admin_chat_sessions (
    id                     SERIAL PRIMARY KEY,
    session_id             VARCHAR(100) NOT NULL UNIQUE,
    mode                   VARCHAR(20)  NOT NULL DEFAULT 'admin',
    title                  TEXT         NOT NULL DEFAULT '',
    pinned                 BOOLEAN      NOT NULL DEFAULT false,
    model                  TEXT         NOT NULL DEFAULT '',
    system_prompt_override TEXT         NOT NULL DEFAULT '',
    disabled_tools_json    JSONB        NOT NULL DEFAULT '[]'::jsonb,
    created_at             TIMESTAMP    DEFAULT NOW(),
    updated_at             TIMESTAMP    DEFAULT NOW(),
    last_message_at        TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_admin_chat_sessions_recent
    ON admin_chat_sessions (mode, pinned DESC, last_message_at DESC);

-- Every WRITE the admin assistant wants to make is parked here with a preview
-- and only runs after the owner approves it in the chat UI.
CREATE TABLE IF NOT EXISTS admin_pending_actions (
    id              SERIAL PRIMARY KEY,
    session_id      VARCHAR(100) NOT NULL DEFAULT '',
    action_type     VARCHAR(20)  NOT NULL,
    target_table    VARCHAR(100),
    target_id       INTEGER,
    payload_json    JSONB,
    preview         TEXT         NOT NULL DEFAULT '',
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending',
    result_json     JSONB,
    error_text      TEXT,
    created_at      TIMESTAMP    DEFAULT NOW(),
    decided_at      TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_admin_pending_session
    ON admin_pending_actions (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_admin_pending_status
    ON admin_pending_actions (status, created_at);

-- ============================ SKILLS + MCP (M3) =========================
CREATE TABLE IF NOT EXISTS custom_knowledge_entries (
    id          SERIAL PRIMARY KEY,
    topic       VARCHAR(200) NOT NULL DEFAULT '',
    content     TEXT         NOT NULL DEFAULT '',
    enabled     BOOLEAN      NOT NULL DEFAULT true,
    created_at  TIMESTAMP    DEFAULT NOW(),
    updated_at  TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_custom_knowledge_enabled ON custom_knowledge_entries (enabled);

-- Webhook skills: calling the tool POSTs/GETs to url with the tool args. URL is
-- SSRF-validated at call time (no private/loopback/link-local).
CREATE TABLE IF NOT EXISTS custom_webhook_skills (
    id                  SERIAL PRIMARY KEY,
    name                VARCHAR(100) NOT NULL UNIQUE,
    description         TEXT         NOT NULL DEFAULT '',
    url                 TEXT         NOT NULL DEFAULT '',
    method              VARCHAR(10)  NOT NULL DEFAULT 'POST',
    headers_json        JSONB        DEFAULT '{}'::jsonb,
    args_schema_json    JSONB        DEFAULT '{"type":"object","properties":{},"required":[]}'::jsonb,
    timeout_seconds     INTEGER      NOT NULL DEFAULT 10,
    enabled             BOOLEAN      NOT NULL DEFAULT false,
    created_at          TIMESTAMP    DEFAULT NOW(),
    updated_at          TIMESTAMP    DEFAULT NOW()
);

-- SQL skills: one read-only SELECT tool each. sql_template uses %(name)s named
-- params, bound at call time under the SELECT-only / 100-row / 5s guardrails.
CREATE TABLE IF NOT EXISTS custom_sql_skills (
    id                  SERIAL PRIMARY KEY,
    name                VARCHAR(100) NOT NULL UNIQUE,
    description         TEXT         NOT NULL DEFAULT '',
    sql_template        TEXT         NOT NULL DEFAULT '',
    args_schema_json    JSONB        DEFAULT '{"type":"object","properties":{},"required":[]}'::jsonb,
    enabled             BOOLEAN      NOT NULL DEFAULT false,
    created_at          TIMESTAMP    DEFAULT NOW(),
    updated_at          TIMESTAMP    DEFAULT NOW()
);

-- MCP connector registry. Discovered tools are cached in mcp_tools_cache.
-- NOTE: auth_credential is stored as-is in this package (the upstream app
-- encrypts it at rest via Fernet; encrypting here is a follow-on hardening).
CREATE TABLE IF NOT EXISTS mcp_servers (
    id                  SERIAL PRIMARY KEY,
    name                VARCHAR(100) NOT NULL UNIQUE,
    description         TEXT         NOT NULL DEFAULT '',
    transport           VARCHAR(20)  NOT NULL DEFAULT 'http',
    url                 TEXT         NOT NULL DEFAULT '',
    auth_type           VARCHAR(20)  NOT NULL DEFAULT 'none',
    auth_header_name    VARCHAR(100) NOT NULL DEFAULT '',
    auth_credential     TEXT         NOT NULL DEFAULT '',
    enabled             BOOLEAN      NOT NULL DEFAULT true,
    allowed_for_admin   BOOLEAN      NOT NULL DEFAULT true,
    allowed_for_velo    BOOLEAN      NOT NULL DEFAULT false,
    connector_type      VARCHAR(50)  NOT NULL DEFAULT 'custom',
    oauth_state         JSONB        DEFAULT '{}'::jsonb,
    last_test_at        TIMESTAMP,
    last_test_ok        BOOLEAN,
    last_test_error     TEXT         NOT NULL DEFAULT '',
    created_at          TIMESTAMP    DEFAULT NOW(),
    updated_at          TIMESTAMP    DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mcp_tools_cache (
    id                  SERIAL PRIMARY KEY,
    server_id           INTEGER      NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
    tool_name           VARCHAR(200) NOT NULL,
    description         TEXT         NOT NULL DEFAULT '',
    input_schema_json   JSONB        DEFAULT '{"type":"object","properties":{},"required":[]}'::jsonb,
    enabled             BOOLEAN      NOT NULL DEFAULT true,
    last_synced_at      TIMESTAMP    DEFAULT NOW(),
    UNIQUE(server_id, tool_name)
);
CREATE INDEX IF NOT EXISTS idx_mcp_tools_server ON mcp_tools_cache (server_id);

-- ============================ AUTOMATIONS (M4) ==========================
CREATE TABLE IF NOT EXISTS automations (
    id                  SERIAL PRIMARY KEY,
    name                TEXT NOT NULL DEFAULT 'Untitled automation',
    description         TEXT NOT NULL DEFAULT '',
    enabled             BOOLEAN NOT NULL DEFAULT FALSE,
    trigger_type        VARCHAR(30) NOT NULL DEFAULT 'manual',
    trigger_config      JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_steps        JSONB NOT NULL DEFAULT '[]'::jsonb,
    webhook_token       TEXT NOT NULL DEFAULT '',
    last_run_at         TIMESTAMP,
    last_run_status     VARCHAR(20) NOT NULL DEFAULT '',
    next_scheduled_at   TIMESTAMP,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_automations_enabled ON automations (enabled);
CREATE INDEX IF NOT EXISTS idx_automations_trigger ON automations (trigger_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_automations_webhook
    ON automations (webhook_token) WHERE webhook_token <> '';

CREATE TABLE IF NOT EXISTS automation_runs (
    id                  SERIAL PRIMARY KEY,
    automation_id       INTEGER REFERENCES automations(id) ON DELETE CASCADE,
    status              VARCHAR(20) NOT NULL DEFAULT 'queued',
    triggered_by        VARCHAR(20) NOT NULL DEFAULT 'event',
    trigger_data        JSONB NOT NULL DEFAULT '{}'::jsonb,
    step_results        JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_text          TEXT NOT NULL DEFAULT '',
    is_dry_run          BOOLEAN NOT NULL DEFAULT FALSE,
    queued_at           TIMESTAMP DEFAULT NOW(),
    started_at          TIMESTAMP,
    finished_at         TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_runs_automation ON automation_runs (automation_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON automation_runs (status);
CREATE INDEX IF NOT EXISTS idx_runs_queued ON automation_runs (status, queued_at);
CREATE INDEX IF NOT EXISTS idx_runs_automation_queued
    ON automation_runs (automation_id, queued_at DESC);

CREATE TABLE IF NOT EXISTS automation_versions (
    id              SERIAL PRIMARY KEY,
    automation_id   INTEGER NOT NULL REFERENCES automations(id) ON DELETE CASCADE,
    version_no      INTEGER NOT NULL,
    snapshot        JSONB NOT NULL,
    note            TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_versions_automation ON automation_versions (automation_id, version_no DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_versions_unique ON automation_versions (automation_id, version_no);

CREATE TABLE IF NOT EXISTS automation_settings (
    id                          INTEGER PRIMARY KEY DEFAULT 1,
    retention_days              INTEGER,
    keep_recent_per_automation  INTEGER,
    updated_at                  TIMESTAMP DEFAULT NOW()
);
INSERT INTO automation_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS automation_webhook_rejections (
    id              SERIAL PRIMARY KEY,
    automation_id   INTEGER NOT NULL REFERENCES automations(id) ON DELETE CASCADE,
    reason          TEXT NOT NULL DEFAULT '',
    source_ip       VARCHAR(64) NOT NULL DEFAULT '',
    header_excerpt  TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_webhook_rejections_automation
    ON automation_webhook_rejections (automation_id, created_at DESC);

-- ============================ SCRAPER (M4) ==============================
-- The upstream app hangs scraper config off site_settings; this package has no
-- public-site settings table, so config lives in its own singleton instead.
CREATE TABLE IF NOT EXISTS scraper_settings (
    id                   INTEGER PRIMARY KEY DEFAULT 1,
    disallowed_domains   TEXT NOT NULL DEFAULT '',
    render_enabled       BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at           TIMESTAMP DEFAULT NOW()
);
INSERT INTO scraper_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS scrape_jobs (
    id              SERIAL PRIMARY KEY,
    input_mode      VARCHAR(20) NOT NULL DEFAULT 'url',
    url             TEXT NOT NULL DEFAULT '',
    objective       TEXT NOT NULL DEFAULT '',
    target_shape    VARCHAR(40) NOT NULL DEFAULT 'free_form',
    custom_schema   JSONB,
    status          VARCHAR(20) NOT NULL DEFAULT 'queued',
    result_json     JSONB,
    error           TEXT NOT NULL DEFAULT '',
    schedule_id     INTEGER,
    result_signature TEXT NOT NULL DEFAULT '',
    changed_from_previous BOOLEAN NOT NULL DEFAULT FALSE,
    progress_steps  JSONB NOT NULL DEFAULT '[]'::jsonb,
    stop_requested  BOOLEAN NOT NULL DEFAULT FALSE,
    partial_state   JSONB,
    requested_at    TIMESTAMP DEFAULT NOW(),
    completed_at    TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_scrape_jobs_status ON scrape_jobs (status);
CREATE INDEX IF NOT EXISTS idx_scrape_jobs_requested ON scrape_jobs (requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_scrape_jobs_schedule ON scrape_jobs (schedule_id, requested_at DESC);

CREATE TABLE IF NOT EXISTS scrape_schedules (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(200) NOT NULL DEFAULT '',
    input_mode      VARCHAR(20) NOT NULL DEFAULT 'url',
    url             TEXT NOT NULL DEFAULT '',
    objective       TEXT NOT NULL DEFAULT '',
    target_shape    VARCHAR(40) NOT NULL DEFAULT 'free_form',
    custom_schema   JSONB,
    schedule_mode   VARCHAR(20) NOT NULL DEFAULT 'daily',
    interval_minutes INTEGER NOT NULL DEFAULT 60,
    daily_time      VARCHAR(5) NOT NULL DEFAULT '09:00',
    weekly_dow      INTEGER NOT NULL DEFAULT 1,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    notify_email    TEXT NOT NULL DEFAULT '',
    notify_phone    TEXT NOT NULL DEFAULT '',
    notify_only_on_change BOOLEAN NOT NULL DEFAULT TRUE,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    failure_threshold INTEGER NOT NULL DEFAULT 5,
    auto_paused     BOOLEAN NOT NULL DEFAULT FALSE,
    last_run_at     TIMESTAMP,
    last_job_id     INTEGER,
    next_run_at     TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_scrape_schedules_enabled ON scrape_schedules (enabled, next_run_at);

-- ============================ MESSAGING (M5) ============================
CREATE TABLE IF NOT EXISTS subscribers (
    id              SERIAL PRIMARY KEY,
    email           TEXT NOT NULL DEFAULT '',
    phone           TEXT NOT NULL DEFAULT '',
    full_name       TEXT NOT NULL DEFAULT '',
    list_name       TEXT NOT NULL DEFAULT 'default',
    source          TEXT NOT NULL DEFAULT 'manual',
    opt_in          BOOLEAN NOT NULL DEFAULT TRUE,
    opt_in_email    BOOLEAN NOT NULL DEFAULT TRUE,
    opt_in_sms      BOOLEAN NOT NULL DEFAULT TRUE,
    custom_fields   JSONB NOT NULL DEFAULT '{}'::jsonb,
    unsubscribed_at TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_subscribers_email ON subscribers (email);
CREATE INDEX IF NOT EXISTS idx_subscribers_phone ON subscribers (phone);
CREATE INDEX IF NOT EXISTS idx_subscribers_list ON subscribers (list_name);

CREATE TABLE IF NOT EXISTS messaging_templates (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL DEFAULT 'Untitled template',
    channel      VARCHAR(10) NOT NULL DEFAULT 'email',
    subject      TEXT NOT NULL DEFAULT '',
    body         TEXT NOT NULL DEFAULT '',
    from_name    TEXT NOT NULL DEFAULT '',
    reply_to     TEXT NOT NULL DEFAULT '',
    notes        TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMP DEFAULT NOW(),
    updated_at   TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messaging_campaigns (
    id                 SERIAL PRIMARY KEY,
    name               TEXT NOT NULL DEFAULT '',
    template_id        INTEGER REFERENCES messaging_templates(id) ON DELETE SET NULL,
    channel            VARCHAR(10) NOT NULL DEFAULT 'email',
    subject_snapshot   TEXT NOT NULL DEFAULT '',
    body_snapshot      TEXT NOT NULL DEFAULT '',
    recipient_kind     VARCHAR(20) NOT NULL DEFAULT 'all',
    recipient_filter   JSONB NOT NULL DEFAULT '{}'::jsonb,
    status             VARCHAR(20) NOT NULL DEFAULT 'draft',
    send_at            TIMESTAMP,
    started_at         TIMESTAMP,
    finished_at        TIMESTAMP,
    total_recipients   INTEGER NOT NULL DEFAULT 0,
    sent_count         INTEGER NOT NULL DEFAULT 0,
    failed_count       INTEGER NOT NULL DEFAULT 0,
    error_text         TEXT NOT NULL DEFAULT '',
    created_at         TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_campaigns_status ON messaging_campaigns (status);
CREATE INDEX IF NOT EXISTS idx_campaigns_send_at ON messaging_campaigns (send_at);

CREATE TABLE IF NOT EXISTS messaging_log (
    id                 SERIAL PRIMARY KEY,
    campaign_id        INTEGER REFERENCES messaging_campaigns(id) ON DELETE SET NULL,
    subscriber_id      INTEGER REFERENCES subscribers(id) ON DELETE SET NULL,
    channel            VARCHAR(10) NOT NULL DEFAULT 'email',
    to_address         TEXT NOT NULL DEFAULT '',
    subject_snapshot   TEXT NOT NULL DEFAULT '',
    body_snapshot      TEXT NOT NULL DEFAULT '',
    status             VARCHAR(20) NOT NULL DEFAULT 'queued',
    provider           VARCHAR(20) NOT NULL DEFAULT '',
    provider_message_id TEXT NOT NULL DEFAULT '',
    error_text         TEXT NOT NULL DEFAULT '',
    sent_at            TIMESTAMP,
    delivered_at       TIMESTAMP,
    opened_at          TIMESTAMP,
    clicked_at         TIMESTAMP,
    open_count         INTEGER NOT NULL DEFAULT 0,
    click_count        INTEGER NOT NULL DEFAULT 0,
    is_test            BOOLEAN NOT NULL DEFAULT FALSE,
    created_at         TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_msg_log_campaign ON messaging_log (campaign_id);
CREATE INDEX IF NOT EXISTS idx_msg_log_provider ON messaging_log (provider_message_id);
CREATE INDEX IF NOT EXISTS idx_msg_log_to ON messaging_log (to_address);

-- ============================ REVIEWS (M5) ==============================
CREATE TABLE IF NOT EXISTS review_destinations (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL DEFAULT '',
    kind            VARCHAR(20) NOT NULL DEFAULT 'google',
    url             TEXT NOT NULL DEFAULT '',
    external_id     TEXT NOT NULL DEFAULT '',
    auto_send       BOOLEAN NOT NULL DEFAULT FALSE,
    auto_send_days  INTEGER NOT NULL DEFAULT 3,
    is_default      BOOLEAN NOT NULL DEFAULT FALSE,
    public_visible  BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_review_dest_sort ON review_destinations (sort_order);

CREATE TABLE IF NOT EXISTS review_requests (
    id                SERIAL PRIMARY KEY,
    destination_id    INTEGER REFERENCES review_destinations(id) ON DELETE SET NULL,
    channel           VARCHAR(10) NOT NULL DEFAULT 'email',
    recipient_name    TEXT NOT NULL DEFAULT '',
    recipient_email   TEXT NOT NULL DEFAULT '',
    recipient_phone   TEXT NOT NULL DEFAULT '',
    purchased_item    TEXT NOT NULL DEFAULT '',
    source_kind       VARCHAR(20) NOT NULL DEFAULT 'manual',
    source_id         INTEGER,
    status            VARCHAR(20) NOT NULL DEFAULT 'queued',
    short_token       VARCHAR(40) UNIQUE NOT NULL,
    subject_snapshot  TEXT NOT NULL DEFAULT '',
    body_snapshot     TEXT NOT NULL DEFAULT '',
    error_text        TEXT NOT NULL DEFAULT '',
    send_at           TIMESTAMP DEFAULT NOW(),
    sent_at           TIMESTAMP,
    clicked_at        TIMESTAMP,
    converted_at      TIMESTAMP,
    click_count       INTEGER NOT NULL DEFAULT 0,
    created_at        TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_review_req_status ON review_requests (status);
CREATE INDEX IF NOT EXISTS idx_review_req_send_at ON review_requests (send_at);
CREATE INDEX IF NOT EXISTS idx_review_req_dest ON review_requests (destination_id);
CREATE INDEX IF NOT EXISTS idx_review_req_source ON review_requests (source_kind, source_id);

CREATE TABLE IF NOT EXISTS external_reviews (
    id              SERIAL PRIMARY KEY,
    destination_id  INTEGER UNIQUE REFERENCES review_destinations(id) ON DELETE CASCADE,
    total_count     INTEGER NOT NULL DEFAULT 0,
    avg_rating      REAL NOT NULL DEFAULT 0,
    snapshot_at     TIMESTAMP DEFAULT NOW(),
    raw_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_text      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS review_settings (
    id                  INTEGER PRIMARY KEY DEFAULT 1,
    email_template_id   INTEGER REFERENCES messaging_templates(id) ON DELETE SET NULL,
    sms_template_id     INTEGER REFERENCES messaging_templates(id) ON DELETE SET NULL,
    auto_send_days      INTEGER NOT NULL DEFAULT 3,
    public_show         BOOLEAN NOT NULL DEFAULT FALSE,
    last_snapshot_at    TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT NOW()
);
INSERT INTO review_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- ============================ COMMERCE (M6) =============================
CREATE TABLE IF NOT EXISTS products (
    id              SERIAL PRIMARY KEY,
    slug            VARCHAR(150) UNIQUE NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    price_cents     INTEGER NOT NULL DEFAULT 0,
    currency        VARCHAR(3) NOT NULL DEFAULT 'USD',
    image_url       TEXT NOT NULL DEFAULT '',
    gallery_images  JSONB NOT NULL DEFAULT '[]'::jsonb,
    stock           INTEGER NOT NULL DEFAULT 0,
    track_inventory BOOLEAN NOT NULL DEFAULT true,
    active          BOOLEAN NOT NULL DEFAULT true,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_products_active ON products (active);
CREATE INDEX IF NOT EXISTS idx_products_sort ON products (sort_order);

CREATE TABLE IF NOT EXISTS customers (
    id                 SERIAL PRIMARY KEY,
    email              VARCHAR(255) UNIQUE NOT NULL,
    name               TEXT NOT NULL DEFAULT '',
    stripe_customer_id VARCHAR(100) DEFAULT '',
    created_at         TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
    id                       SERIAL PRIMARY KEY,
    order_number             VARCHAR(40) UNIQUE NOT NULL,
    customer_id              INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    customer_email           VARCHAR(255) NOT NULL DEFAULT '',
    customer_name            TEXT NOT NULL DEFAULT '',
    status                   VARCHAR(20) NOT NULL DEFAULT 'pending',
    subtotal_cents           INTEGER NOT NULL DEFAULT 0,
    total_cents              INTEGER NOT NULL DEFAULT 0,
    currency                 VARCHAR(3) NOT NULL DEFAULT 'USD',
    stripe_payment_intent_id VARCHAR(100) DEFAULT '',
    stripe_charge_id         VARCHAR(100) DEFAULT '',
    refunded_cents           INTEGER NOT NULL DEFAULT 0,
    shipping_address         JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes                    TEXT NOT NULL DEFAULT '',
    created_at               TIMESTAMP DEFAULT NOW(),
    paid_at                  TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);
CREATE INDEX IF NOT EXISTS idx_orders_pi ON orders (stripe_payment_intent_id);

CREATE TABLE IF NOT EXISTS order_items (
    id               SERIAL PRIMARY KEY,
    order_id         INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id       INTEGER REFERENCES products(id) ON DELETE SET NULL,
    product_name     TEXT NOT NULL DEFAULT '',
    unit_price_cents INTEGER NOT NULL DEFAULT 0,
    quantity         INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items (order_id);

CREATE TABLE IF NOT EXISTS services (
    id                     SERIAL PRIMARY KEY,
    slug                   VARCHAR(100) UNIQUE NOT NULL,
    name                   VARCHAR(200) NOT NULL,
    short_description      VARCHAR(500) NOT NULL DEFAULT '',
    long_description       TEXT NOT NULL DEFAULT '',
    image_url              TEXT NOT NULL DEFAULT '',
    duration_minutes       INTEGER NOT NULL DEFAULT 60,
    pricing_model          VARCHAR(20) NOT NULL DEFAULT 'rsvp',
    base_price_cents       INTEGER NOT NULL DEFAULT 0,
    deposit_cents          INTEGER NOT NULL DEFAULT 0,
    currency               VARCHAR(8) NOT NULL DEFAULT 'usd',
    contract_template_url  TEXT NOT NULL DEFAULT '',
    contract_template_name VARCHAR(200) NOT NULL DEFAULT '',
    requires_calendar      BOOLEAN NOT NULL DEFAULT TRUE,
    capacity_per_slot      INTEGER NOT NULL DEFAULT 1,
    sort_order             INTEGER NOT NULL DEFAULT 0,
    is_active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at             TIMESTAMP DEFAULT NOW(),
    updated_at             TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_services_active_sort ON services (is_active, sort_order);

CREATE TABLE IF NOT EXISTS service_addons (
    id           SERIAL PRIMARY KEY,
    service_id   INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    name         VARCHAR(200) NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    price_cents  INTEGER NOT NULL DEFAULT 0,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_service_addons_svc ON service_addons (service_id, sort_order);

CREATE TABLE IF NOT EXISTS service_availability_rules (
    id            SERIAL PRIMARY KEY,
    service_id    INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    day_of_week   INTEGER NOT NULL,
    start_time    TIME NOT NULL,
    end_time      TIME NOT NULL,
    slot_minutes  INTEGER NOT NULL DEFAULT 60,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_avail_rules_svc ON service_availability_rules (service_id, day_of_week);

CREATE TABLE IF NOT EXISTS service_availability_overrides (
    id             SERIAL PRIMARY KEY,
    service_id     INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    override_date  DATE NOT NULL,
    start_time     TIME,
    end_time       TIME,
    override_kind  VARCHAR(10) NOT NULL,
    slot_minutes   INTEGER NOT NULL DEFAULT 60,
    note           TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_avail_ovr_svc ON service_availability_overrides (service_id, override_date);

CREATE TABLE IF NOT EXISTS service_bookings (
    id                    SERIAL PRIMARY KEY,
    service_id            INTEGER REFERENCES services(id) ON DELETE SET NULL,
    booking_token         VARCHAR(64) NOT NULL UNIQUE,
    client_name           VARCHAR(200) NOT NULL,
    client_email          VARCHAR(200) NOT NULL,
    client_phone          VARCHAR(50) NOT NULL DEFAULT '',
    notes                 TEXT NOT NULL DEFAULT '',
    scheduled_date        DATE,
    scheduled_start       TIME,
    scheduled_end         TIME,
    selected_addon_ids    INTEGER[] NOT NULL DEFAULT '{}',
    addon_snapshot        JSONB NOT NULL DEFAULT '[]'::jsonb,
    pricing_model         VARCHAR(20) NOT NULL DEFAULT 'rsvp',
    base_price_cents      INTEGER NOT NULL DEFAULT 0,
    addons_total_cents    INTEGER NOT NULL DEFAULT 0,
    total_cents           INTEGER NOT NULL DEFAULT 0,
    amount_paid_cents     INTEGER NOT NULL DEFAULT 0,
    currency              VARCHAR(8) NOT NULL DEFAULT 'usd',
    payment_status        VARCHAR(20) NOT NULL DEFAULT 'none',
    stripe_session_id     VARCHAR(200) NOT NULL DEFAULT '',
    signed_contract_url   TEXT NOT NULL DEFAULT '',
    status                VARCHAR(20) NOT NULL DEFAULT 'pending',
    utm_source            VARCHAR(200) NOT NULL DEFAULT '',
    utm_medium            VARCHAR(200) NOT NULL DEFAULT '',
    utm_campaign          VARCHAR(200) NOT NULL DEFAULT '',
    created_at            TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bookings_recent ON service_bookings (created_at DESC);

CREATE TABLE IF NOT EXISTS stripe_settings (
    id                    INTEGER PRIMARY KEY,
    mode                  VARCHAR(10) NOT NULL DEFAULT 'test',
    autosync_products     BOOLEAN NOT NULL DEFAULT FALSE,
    last_health_check_at  TIMESTAMP,
    last_health_ok        BOOLEAN,
    last_health_error     TEXT NOT NULL DEFAULT '',
    last_backfill_at      TIMESTAMP,
    last_backfill_summary JSONB DEFAULT '{}'::jsonb,
    updated_at            TIMESTAMP DEFAULT NOW()
);
INSERT INTO stripe_settings (id, mode) VALUES (1, 'test') ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS stripe_product_sync (
    id                  SERIAL PRIMARY KEY,
    local_product_id    INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    mode                VARCHAR(10) NOT NULL,
    stripe_product_id   VARCHAR(100) NOT NULL DEFAULT '',
    stripe_price_id     VARCHAR(100) NOT NULL DEFAULT '',
    synced_price_cents  INTEGER,
    synced_currency     VARCHAR(8) NOT NULL DEFAULT '',
    last_synced_at      TIMESTAMP,
    last_attempt_at     TIMESTAMP DEFAULT NOW(),
    last_error          TEXT NOT NULL DEFAULT '',
    UNIQUE (local_product_id, mode)
);

-- Webhook idempotency: each Stripe event id is recorded the first time it's
-- processed; a redelivery (Stripe retries aggressively) is a no-op. The PK
-- INSERT ON CONFLICT is the atomic claim.
CREATE TABLE IF NOT EXISTS stripe_events (
    event_id      VARCHAR(120) PRIMARY KEY,
    event_type    VARCHAR(80) NOT NULL DEFAULT '',
    processed_at  TIMESTAMP DEFAULT NOW()
);

-- ============================ EVENTS / TICKETING (M12) ==================
-- Event listings + RSVPs. price_mode: free (RSVP confirmed immediately),
-- paid (price_cents per guest, Stripe Checkout), donation (donor-chosen
-- amount at RSVP time, Stripe Checkout). capacity 0 = unlimited.
CREATE TABLE IF NOT EXISTS events (
    id             SERIAL PRIMARY KEY,
    slug           VARCHAR(150) UNIQUE NOT NULL,
    title          TEXT NOT NULL DEFAULT '',
    description    TEXT NOT NULL DEFAULT '',
    start_at       TIMESTAMP,
    end_at         TIMESTAMP,
    location       TEXT NOT NULL DEFAULT '',
    capacity       INTEGER NOT NULL DEFAULT 0,
    price_mode     VARCHAR(10) NOT NULL DEFAULT 'free',
    price_cents    INTEGER NOT NULL DEFAULT 0,
    currency       VARCHAR(8) NOT NULL DEFAULT 'usd',
    image_url      TEXT NOT NULL DEFAULT '',
    status         VARCHAR(20) NOT NULL DEFAULT 'published',
    sort_order     INTEGER NOT NULL DEFAULT 0,
    created_at     TIMESTAMP DEFAULT NOW(),
    updated_at     TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_events_status_sort ON events (status, sort_order);
CREATE INDEX IF NOT EXISTS idx_events_start ON events (start_at);

CREATE TABLE IF NOT EXISTS event_rsvps (
    id              SERIAL PRIMARY KEY,
    event_id        INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    rsvp_token      VARCHAR(64) UNIQUE NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    email           TEXT NOT NULL DEFAULT '',
    phone           TEXT NOT NULL DEFAULT '',
    guests          INTEGER NOT NULL DEFAULT 1,
    notes           TEXT NOT NULL DEFAULT '',
    amount_cents    INTEGER NOT NULL DEFAULT 0,
    currency        VARCHAR(8) NOT NULL DEFAULT 'usd',
    payment_status  VARCHAR(20) NOT NULL DEFAULT 'none',
    status          VARCHAR(20) NOT NULL DEFAULT 'confirmed',
    stripe_session_id VARCHAR(200) NOT NULL DEFAULT '',
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_event_rsvps_event ON event_rsvps (event_id, status);

-- ============================ AI-REFERENCED CONTENT (M13) ===============
-- Data tables for content the visitor AI looks up. The kit dropped the public
-- website editors for these (per the boundary decision), but keeps the data +
-- a minimal admin CRUD so an operator can populate what the AI references.
CREATE TABLE IF NOT EXISTS experiences (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    icon        VARCHAR(50) NOT NULL DEFAULT 'star',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_experiences_sort ON experiences (sort_order);

CREATE TABLE IF NOT EXISTS pricing_seasons (
    id          SERIAL PRIMARY KEY,
    label       VARCHAR(80) NOT NULL DEFAULT '',
    date_range  TEXT NOT NULL DEFAULT '',
    price_range TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pricing_sort ON pricing_seasons (sort_order);

CREATE TABLE IF NOT EXISTS testimonials (
    id            SERIAL PRIMARY KEY,
    reviewer_name TEXT NOT NULL DEFAULT '',
    reviewer_role TEXT NOT NULL DEFAULT '',
    content       TEXT NOT NULL DEFAULT '',
    rating        INTEGER NOT NULL DEFAULT 5,
    image_url     TEXT NOT NULL DEFAULT '',
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_testimonials_sort ON testimonials (sort_order);

CREATE TABLE IF NOT EXISTS team_members (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL DEFAULT '',
    bio         TEXT NOT NULL DEFAULT '',
    image_url   TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_team_sort ON team_members (sort_order);

CREATE TABLE IF NOT EXISTS faqs (
    id          SERIAL PRIMARY KEY,
    question    TEXT NOT NULL DEFAULT '',
    answer      TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_faqs_sort ON faqs (sort_order);

CREATE TABLE IF NOT EXISTS blog_posts (
    id              SERIAL PRIMARY KEY,
    slug            TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    subtitle        TEXT NOT NULL DEFAULT '',
    excerpt         TEXT NOT NULL DEFAULT '',
    content         TEXT NOT NULL DEFAULT '',
    cover_image     TEXT NOT NULL DEFAULT '',
    author          TEXT NOT NULL DEFAULT '',
    category        TEXT NOT NULL DEFAULT '',
    tags            TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'draft',
    seo_title       TEXT NOT NULL DEFAULT '',
    seo_description TEXT NOT NULL DEFAULT '',
    published_at    TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    sort_order      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_blog_posts_status ON blog_posts (status);
CREATE INDEX IF NOT EXISTS idx_blog_posts_sort ON blog_posts (sort_order);

-- Single-row business profile the AI quotes (name, contact, hours, socials).
CREATE TABLE IF NOT EXISTS business_info (
    id          INTEGER PRIMARY KEY DEFAULT 1,
    name        TEXT NOT NULL DEFAULT '',
    tagline     TEXT NOT NULL DEFAULT '',
    about       TEXT NOT NULL DEFAULT '',
    phone       TEXT NOT NULL DEFAULT '',
    email       TEXT NOT NULL DEFAULT '',
    address     TEXT NOT NULL DEFAULT '',
    hours       JSONB NOT NULL DEFAULT '{}'::jsonb,
    social      JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMP DEFAULT NOW()
);
INSERT INTO business_info (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Generic content rows grouped by a free-form section_slug (standalone — the
-- package drops the page_sections editor, so no FK to it).
CREATE TABLE IF NOT EXISTS custom_section_items (
    id           SERIAL PRIMARY KEY,
    section_slug VARCHAR(150) NOT NULL DEFAULT '',
    title        TEXT NOT NULL DEFAULT '',
    subtitle     TEXT NOT NULL DEFAULT '',
    content      TEXT NOT NULL DEFAULT '',
    image_url    TEXT NOT NULL DEFAULT '',
    link_url     TEXT NOT NULL DEFAULT '',
    link_text    TEXT NOT NULL DEFAULT '',
    icon         TEXT NOT NULL DEFAULT '',
    sort_order   INTEGER NOT NULL DEFAULT 0,
    extra_data   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_custom_items_section ON custom_section_items (section_slug, sort_order);

-- ============================ TENANCY: EMBED KEYS (M6, feeds M7) =========
-- Publishable per-tenant key for the cross-origin widget, with an origin
-- allowlist. The visitor/embed endpoints validate the request Origin against
-- this allowlist in central mode (M7 wires the enforcement).
CREATE TABLE IF NOT EXISTS tenant_embed_keys (
    id                SERIAL PRIMARY KEY,
    tenant_id         INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    embed_key         VARCHAR(64) UNIQUE NOT NULL,
    label             TEXT NOT NULL DEFAULT '',
    origin_allowlist  JSONB NOT NULL DEFAULT '[]'::jsonb,
    enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_embed_keys_tenant ON tenant_embed_keys (tenant_id);

-- Single-use SSO token ledger (M8). A token's jti is claimed via INSERT ... ON
-- CONFLICT DO NOTHING, so consumption is final ACROSS workers/instances — the
-- in-process cache alone couldn't guarantee single-use under gunicorn.
CREATE TABLE IF NOT EXISTS sso_used_jtis (
    jti         VARCHAR(64) PRIMARY KEY,
    expires_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Shared rate-limit buckets (M10) so limits hold ACROSS workers when Redis isn't
-- configured. One row per (key, window); incremented atomically.
CREATE TABLE IF NOT EXISTS rate_buckets (
    bucket_key    VARCHAR(180) PRIMARY KEY,
    window_start  BIGINT NOT NULL,
    count         INTEGER NOT NULL DEFAULT 0
);

-- Shareable WordPress onboarding links. The super admin generates one of these
-- per client; the client opens /plugin/onboard/<token> (no login) to download
-- the plugin zip and copy their pre-filled setup values + instructions. The SSO
-- secret is GLOBAL, so it is embedded in the page ONLY when include_sso is TRUE
-- (opt-in, with a warning) — otherwise the super admin shares it securely.
CREATE TABLE IF NOT EXISTS wp_onboarding_links (
    id              SERIAL PRIMARY KEY,
    token           TEXT UNIQUE NOT NULL,
    tenant_id       INTEGER NOT NULL DEFAULT 1,
    label           TEXT NOT NULL DEFAULT '',
    embed_key       TEXT NOT NULL DEFAULT '',
    include_sso     BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at      TIMESTAMP,
    revoked         BOOLEAN NOT NULL DEFAULT FALSE,
    view_count      INTEGER NOT NULL DEFAULT 0,
    last_viewed_at  TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW()
);
"""

# Seeds — singletons + default tenant + reference prices. All idempotent.
_SEED = r"""
INSERT INTO plans (slug, name, description, sort_order) VALUES
  ('solo',       'Solo',       'Single site, core features',        1),
  ('growth',     'Growth',     'AI + automations + analytics',      2),
  ('enterprise', 'Enterprise', 'Everything, multi-tenant',          3)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO tenants (id, name, status)
VALUES (1, 'Default Tenant', 'active')
ON CONFLICT (id) DO NOTHING;
-- The explicit id=1 seed above does NOT advance the SERIAL sequence, so the
-- first auto-id INSERT would collide on id=1. Bump the sequence past the max.
SELECT setval(pg_get_serial_sequence('tenants', 'id'),
              GREATEST((SELECT MAX(id) FROM tenants), 1));

INSERT INTO chatbot_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
INSERT INTO voice_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
INSERT INTO agent_provider_settings (id, provider, openai_model, claude_model)
VALUES (1, 'openai', 'gpt-4o-mini', 'claude-sonnet-4-5')
ON CONFLICT (id) DO NOTHING;

INSERT INTO tenant_cost_caps (tenant_id, monthly_cap_usd, warn_at_percent, cap_behavior)
VALUES (1, NULL, 80, 'alert_only')
ON CONFLICT (tenant_id) DO NOTHING;

INSERT INTO model_prices
  (provider, model, surface,
   input_price_per_million_tokens, output_price_per_million_tokens,
   tts_price_per_million_chars, stt_price_per_minute, sms_price_per_segment, notes)
VALUES
  ('openai',     'gpt-4o-mini',           'chat', 0.150, 0.600, NULL, NULL, NULL,  'OpenAI gpt-4o-mini list price (2025)'),
  ('openai',     'gpt-4o',                'chat', 2.500, 10.000, NULL, NULL, NULL, 'OpenAI gpt-4o list price (2025)'),
  ('anthropic',  'claude-sonnet-4-5',     'chat', 3.000, 15.000, NULL, NULL, NULL, 'Anthropic Claude Sonnet 4.5 list price (2025)'),
  ('anthropic',  'claude-opus-4',         'chat', 15.000, 75.000, NULL, NULL, NULL,'Anthropic Claude Opus 4 list price (2025)'),
  ('openai',     'tts-1',                 'tts',  NULL, NULL, 15.000, NULL, NULL,   'OpenAI tts-1: $15 per 1M chars'),
  ('openai',     'tts-1-hd',              'tts',  NULL, NULL, 30.000, NULL, NULL,   'OpenAI tts-1-hd: $30 per 1M chars'),
  ('elevenlabs', 'eleven_turbo_v2_5',     'tts',  NULL, NULL, 50.000, NULL, NULL,   'ElevenLabs Turbo v2.5 approx (2025)'),
  ('elevenlabs', 'eleven_multilingual_v2','tts',  NULL, NULL, 90.000, NULL, NULL,   'ElevenLabs Multilingual v2 approx (2025)'),
  ('openai',     'whisper-1',             'stt',  NULL, NULL, NULL, 0.006, NULL,    'OpenAI Whisper: $0.006 per minute'),
  ('openai',     'text-embedding-3-small','embedding', 0.020, NULL, NULL, NULL, NULL, 'OpenAI text-embedding-3-small: $0.02 per 1M tokens'),
  ('twilio',     'sms-us',                'sms',  NULL, NULL, NULL, NULL, 0.0079,   'Twilio US outbound SMS approx (2025)')
ON CONFLICT (provider, model, surface) DO NOTHING;
"""


# RAG tables need the pgvector extension. They're created in a SEPARATE guarded
# step so a Postgres without pgvector (e.g. the embedded test DB) still boots —
# RAG features then degrade to "unavailable" instead of failing the whole schema.
# Columns match reused_di/rag.py exactly (storage_key, content_text, vector(1536)).
_RAG_DDL = r"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_documents (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    filename        TEXT NOT NULL,
    storage_key     TEXT NOT NULL DEFAULT '',
    mime            TEXT NOT NULL DEFAULT '',
    size_bytes      BIGINT NOT NULL DEFAULT 0,
    page_count      INTEGER NOT NULL DEFAULT 0,
    chunk_count     INTEGER NOT NULL DEFAULT 0,
    token_count     INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'indexing',
    error_text      TEXT NOT NULL DEFAULT '',
    source_mtime    DOUBLE PRECISION,
    indexed_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS rag_documents_tenant_idx ON rag_documents (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id              BIGSERIAL PRIMARY KEY,
    document_id     INTEGER NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
    tenant_id       INTEGER NOT NULL DEFAULT 1,
    chunk_index     INTEGER NOT NULL,
    page_number     INTEGER,
    content_text    TEXT NOT NULL,
    token_count     INTEGER NOT NULL DEFAULT 0,
    embedding       vector(1536),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS rag_chunks_doc_idx ON rag_chunks (document_id, chunk_index);
CREATE INDEX IF NOT EXISTS rag_chunks_tenant_idx ON rag_chunks (tenant_id);
"""

_rag_ready = False


def rag_available() -> bool:
    """True if the RAG tables exist (i.e. pgvector was available at boot)."""
    return _rag_ready


def _try_init_rag(conn):
    """Attempt to create the pgvector-backed RAG tables. On any failure (no
    pgvector extension available), log and leave RAG disabled — never fatal."""
    global _rag_ready
    try:
        with conn.cursor() as cur:
            cur.execute(_RAG_DDL)
            # Best-effort cosine index (separate so its failure doesn't drop tables).
            try:
                cur.execute("CREATE INDEX IF NOT EXISTS rag_chunks_embedding_idx "
                            "ON rag_chunks USING ivfflat (embedding vector_cosine_ops) "
                            "WITH (lists = 100)")
            except Exception:
                pass
        _rag_ready = True
    except Exception as e:
        import sys
        print(f"[schema] RAG/pgvector unavailable — KB features disabled: "
              f"{str(e)[:160]}", file=sys.stderr)
        _rag_ready = False


def init_db():
    """Create the package's owned tables + seed singletons. Idempotent.
    RAG tables are attempted separately and skipped if pgvector is missing."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(_DDL)
            cur.execute(_SEED)
    finally:
        conn.close()
    # RAG in its own connection so a pgvector failure can't poison the main txn.
    rag_conn = get_db()
    try:
        _try_init_rag(rag_conn)
    finally:
        rag_conn.close()
