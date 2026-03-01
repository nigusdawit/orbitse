-- =============================================================================
-- CHAT UI KIT — Database Schema (PostgreSQL)
-- =============================================================================
--
-- PURPOSE:
--   Creates all tables required by the Chat UI Kit backend. Run this file
--   against a fresh PostgreSQL database before starting server.py.
--
-- USAGE:
--   psql -U your_user -d your_database -f schema.sql
--
-- TABLES:
--   1. chatbot_settings    — Singleton config row controlling the AI agent
--   2. chat_conversations  — One row per visitor chat session
--   3. chat_messages       — Individual messages within a conversation
--   4. generated_pages     — HTML pages created by the AI and saved for later
--   5. custom_forms        — Dynamic form definitions (contact, inquiry, etc.)
--   6. form_fields         — Individual fields belonging to a form
--   7. form_submissions    — Completed and partial submissions with analytics
--
-- NOTES:
--   - All tables use SERIAL primary keys (auto-incrementing integers).
--   - JSONB columns store flexible/dynamic data (form answers, UTM params, etc.)
--   - Timestamps default to NOW() so you rarely need to pass them explicitly.
--   - The chatbot_settings table is seeded with a default row (id=1) at the end.
--
-- =============================================================================


-- =============================================================================
-- 1. CHATBOT SETTINGS (singleton — always id=1)
-- =============================================================================
-- Controls the AI chatbot behavior and appearance on the public site.
--
-- enabled       : Master on/off toggle. When false, the chat widget is hidden.
-- mode          : 'builtin' uses the kit's built-in chat UI + OpenAI streaming.
--                 'embed'   loads an external chatbot widget via embed_code.
-- agent_name    : Display name shown in the chat bar header.
-- agent_role    : Role/title label (e.g., "Concierge", "Support Agent").
-- agent_avatar  : Text initials or image URL rendered in the avatar circle.
-- greeting      : First message the bot sends when chat opens.
-- quick_prompts : JSON array of suggested prompt strings shown as quick-reply
--                 buttons below the greeting message.
-- system_prompt : The full system prompt sent to the AI model. Contains
--                 personality instructions, command definitions, and knowledge.
-- api_endpoint  : URL the frontend POSTs messages to (default: /api/chat).
-- embed_code    : External HTML/JS snippet injected on the page (embed mode).
-- =============================================================================
CREATE TABLE IF NOT EXISTS chatbot_settings (
    id            SERIAL PRIMARY KEY,
    enabled       BOOLEAN NOT NULL DEFAULT false,
    mode          TEXT NOT NULL DEFAULT 'builtin',
    agent_name    TEXT NOT NULL DEFAULT 'AI Assistant',
    agent_role    TEXT NOT NULL DEFAULT 'Assistant',
    agent_avatar  TEXT NOT NULL DEFAULT 'A',
    greeting      TEXT NOT NULL DEFAULT 'Welcome! I''m your AI assistant. How can I help you today?',
    quick_prompts JSONB DEFAULT '["Browse our gallery", "Tell me more", "What do you offer?", "Show me pricing"]'::jsonb,
    system_prompt TEXT NOT NULL DEFAULT '',
    api_endpoint  TEXT NOT NULL DEFAULT '/api/chat',
    embed_code    TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);


-- =============================================================================
-- 2. CHAT CONVERSATIONS (one per browser session / page load)
-- =============================================================================
-- Tracks each chat session. A new conversation is created when the visitor
-- opens the chat widget (or on page load, depending on implementation).
--
-- session_id  : Unique ID generated per page load. Every refresh = new session.
-- visitor_id  : Persistent ID stored in localStorage. Tracks returning visitors
--               across multiple sessions/page loads.
-- visitor_ip  : IP address of the visitor (for analytics / fraud detection).
-- device_type : 'desktop', 'tablet', or 'mobile' — detected from user agent.
-- user_agent  : Raw browser user-agent string for device/browser analytics.
-- started_at  : When the conversation began (first message or widget open).
-- updated_at  : When the last message was sent (kept current for sorting).
-- =============================================================================
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

-- Fast lookup by session_id (used when resuming or saving messages)
CREATE INDEX IF NOT EXISTS idx_chat_conv_session ON chat_conversations (session_id);


-- =============================================================================
-- 3. CHAT MESSAGES (linked to conversations via FK)
-- =============================================================================
-- Stores every message exchanged in a conversation. Both user messages and
-- assistant responses are saved here for the admin transcript view.
--
-- conversation_id : FK to chat_conversations. CASCADE delete removes messages
--                   when a conversation is deleted.
-- role            : 'user' or 'assistant' (matches OpenAI message roles).
-- content         : The text content of the message (markdown/plain text).
-- command_json    : If the assistant's response included a command block
--                   (e.g., navigate, scrollToSection), the parsed JSON is
--                   stored here for analytics and replay.
-- created_at      : Timestamp of when the message was sent/received.
-- =============================================================================
CREATE TABLE IF NOT EXISTS chat_messages (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER REFERENCES chat_conversations(id) ON DELETE CASCADE,
    role            VARCHAR(20) NOT NULL DEFAULT 'user',
    content         TEXT NOT NULL DEFAULT '',
    command_json    JSONB,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Fast lookup of all messages in a conversation (for transcript loading)
CREATE INDEX IF NOT EXISTS idx_chat_msg_conv ON chat_messages (conversation_id);


-- =============================================================================
-- 4. GENERATED PAGES (AI-created HTML saved from the chat)
-- =============================================================================
-- When the AI generates a full HTML page (via the generateHTML command),
-- the frontend can save it to the database. Admins can then preview,
-- edit, publish, or delete these pages from the admin dashboard.
--
-- title      : Page title extracted from the generated content.
-- html       : The full HTML markup of the generated page.
-- prompt     : The original user prompt that triggered the generation.
-- slug       : URL-friendly identifier (auto-generated from title). Must be
--              unique — used for the public URL: /page/<slug>
-- status     : 'draft' (default) or 'published'. Only published pages are
--              accessible via the public /page/<slug> route.
-- created_at : When the page was first saved.
-- updated_at : When the page was last modified (status change, HTML edit).
-- =============================================================================
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

-- Filter pages by status (e.g., list only published pages)
CREATE INDEX IF NOT EXISTS idx_generated_pages_status ON generated_pages (status);


-- =============================================================================
-- 5. CUSTOM FORMS (dynamic form definitions)
-- =============================================================================
-- Defines forms that can be rendered by the chat UI or embedded on pages.
-- Each form has a unique slug used in the submission API endpoint:
--   POST /api/forms/<slug>/submit
--
-- name               : Human-readable form name (shown in admin).
-- slug               : URL-safe identifier, must be unique. Used in API routes.
-- description        : Optional description shown above the form.
-- status             : 'active' or 'inactive'. Inactive forms reject submissions.
-- submit_button_text : Label for the submit button (e.g., "Send", "Book Now").
-- success_message    : Message shown to the user after successful submission.
-- sort_order         : Controls display order when listing multiple forms.
-- =============================================================================
CREATE TABLE IF NOT EXISTS custom_forms (
    id                 SERIAL PRIMARY KEY,
    name               TEXT NOT NULL DEFAULT '',
    slug               VARCHAR(100) NOT NULL UNIQUE,
    description        TEXT NOT NULL DEFAULT '',
    status             VARCHAR(20) NOT NULL DEFAULT 'active',
    submit_button_text TEXT NOT NULL DEFAULT 'Submit',
    success_message    TEXT NOT NULL DEFAULT 'Thank you! Your submission has been received.',
    created_at         TIMESTAMP DEFAULT NOW(),
    updated_at         TIMESTAMP DEFAULT NOW(),
    sort_order         INTEGER DEFAULT 0
);


-- =============================================================================
-- 6. FORM FIELDS (individual fields belonging to a form)
-- =============================================================================
-- Each row defines one input field within a custom form. Fields are rendered
-- in sort_order within their step group.
--
-- form_id          : FK to custom_forms. CASCADE delete removes fields when
--                    the parent form is deleted.
-- field_type       : Input type — 'text', 'email', 'tel', 'number', 'date',
--                    'select', 'textarea', 'checkbox', 'radio', etc.
-- label            : Human-readable label displayed above the input.
-- name             : Machine-readable field name (used as the key in
--                    submission_data JSONB). Should be snake_case.
-- placeholder      : Placeholder text shown inside the input.
-- required         : Whether this field must be filled before submission.
-- options          : JSONB array of options for select/radio/checkbox fields.
--                    Example: ["Option A", "Option B", "Option C"]
-- default_value    : Pre-filled value for the field.
-- sort_order       : Controls the order fields appear within their step.
-- width            : 'full' (100%) or 'half' (50%) — controls layout width.
-- validation_regex : Optional regex pattern for custom client-side validation.
-- help_text        : Small hint text displayed below the field.
-- step             : For multi-step forms, which step this field belongs to.
--                    Step 1 fields show first, step 2 after "Next", etc.
-- =============================================================================
CREATE TABLE IF NOT EXISTS form_fields (
    id               SERIAL PRIMARY KEY,
    form_id          INTEGER NOT NULL REFERENCES custom_forms(id) ON DELETE CASCADE,
    field_type       VARCHAR(30) NOT NULL DEFAULT 'text',
    label            TEXT NOT NULL DEFAULT '',
    name             VARCHAR(100) NOT NULL DEFAULT '',
    placeholder      TEXT NOT NULL DEFAULT '',
    required         BOOLEAN NOT NULL DEFAULT false,
    options          JSONB,
    default_value    TEXT NOT NULL DEFAULT '',
    sort_order       INTEGER DEFAULT 0,
    width            VARCHAR(10) NOT NULL DEFAULT 'full',
    validation_regex TEXT NOT NULL DEFAULT '',
    help_text        TEXT NOT NULL DEFAULT '',
    step             INTEGER NOT NULL DEFAULT 1
);

-- Fast lookup of all fields belonging to a form
CREATE INDEX IF NOT EXISTS idx_form_fields_form ON form_fields (form_id);


-- =============================================================================
-- 7. FORM SUBMISSIONS (completed + partial, with full marketing analytics)
-- =============================================================================
-- Stores every form submission. The actual field values are in submission_data
-- (JSONB), so this table works for ANY form structure without schema changes.
--
-- Partial submissions (status='partial') are saved when a visitor starts
-- filling out a form but doesn't complete it — useful for lead capture and
-- abandon-recovery workflows.
--
-- MARKETING ANALYTICS COLUMNS:
--   device_type, user_agent, referrer_url — basic visitor info
--   utm_source/medium/campaign/term/content — full UTM parameter tracking
--   page_url — which page the form was submitted from
--   ip_address, browser, os, screen_resolution, language — device fingerprint
--   session_id — links submission to a chat session for attribution
--   confirmation_number — unique reference number for the submission
--
-- These analytics fields let you build reports like:
--   "Which UTM campaign drives the most form completions?"
--   "What % of mobile visitors abandon the form?"
--   "Which referrer sources have the highest conversion rate?"
-- =============================================================================
CREATE TABLE IF NOT EXISTS form_submissions (
    id                  SERIAL PRIMARY KEY,
    form_id             INTEGER NOT NULL REFERENCES custom_forms(id) ON DELETE CASCADE,
    submission_data     JSONB NOT NULL DEFAULT '{}'::jsonb,
    status              VARCHAR(20) NOT NULL DEFAULT 'new',
    device_type         VARCHAR(20) DEFAULT 'desktop',
    user_agent          TEXT DEFAULT '',
    referrer_url        TEXT DEFAULT '',
    utm_source          TEXT DEFAULT '',
    utm_medium          TEXT DEFAULT '',
    utm_campaign        TEXT DEFAULT '',
    utm_term            TEXT DEFAULT '',
    utm_content         TEXT DEFAULT '',
    page_url            TEXT DEFAULT '',
    ip_address          VARCHAR(45) DEFAULT '',
    browser             TEXT DEFAULT '',
    os                  TEXT DEFAULT '',
    screen_resolution   TEXT DEFAULT '',
    language            TEXT DEFAULT '',
    session_id          TEXT DEFAULT '',
    confirmation_number VARCHAR(20) DEFAULT '',
    submitted_at        TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

-- Fast lookup of all submissions for a specific form
CREATE INDEX IF NOT EXISTS idx_form_sub_form ON form_submissions (form_id);

-- Filter submissions by status (new, reviewed, contacted, archived, partial)
CREATE INDEX IF NOT EXISTS idx_form_sub_status ON form_submissions (status);


-- =============================================================================
-- SEED DATA — Default chatbot settings
-- =============================================================================
-- Inserts a single default configuration row (id=1). This row is required
-- for the backend to function. The admin can update all values from the
-- admin dashboard — this just provides sensible starting defaults.
--
-- ON CONFLICT DO NOTHING ensures this is safe to run multiple times.
-- =============================================================================
INSERT INTO chatbot_settings (
    id,
    enabled,
    mode,
    agent_name,
    agent_role,
    agent_avatar,
    greeting,
    quick_prompts,
    system_prompt,
    api_endpoint,
    embed_code
) VALUES (
    1,
    false,
    'builtin',
    'AI Assistant',
    'Assistant',
    'A',
    'Welcome! I''m your AI assistant. How can I help you today?',
    '["Browse our gallery", "Tell me more", "What do you offer?", "Show me pricing"]'::jsonb,
    '',
    '/api/chat',
    ''
) ON CONFLICT (id) DO NOTHING;
