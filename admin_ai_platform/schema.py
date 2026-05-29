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
    "plans", "tenants", "tenant_features", "feature_addons",
    "gallery_cards", "chatbot_settings", "chat_conversations", "chat_messages",
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


def init_db():
    """Create the package's owned tables + seed singletons. Idempotent."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(_DDL)
            cur.execute(_SEED)
    finally:
        conn.close()
