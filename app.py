"""
===============================================================================
SITE TEMPLATE — Flask Backend (app.py)
===============================================================================

PURPOSE:
  This is the main backend server for a database-driven website template.
  It connects to a PostgreSQL database and serves:
    1. A public-facing HTML/CSS/JS website (from the /public folder)
    2. A password-protected admin dashboard (from /templates/admin)
    3. REST API endpoints for public reads and admin CRUD operations
    4. A chat API endpoint for the AI chatbot (configurable)

HOW IT WORKS:
  - The public site (index.html) calls GET /api/* endpoints to fetch content
    from the database, then renders it client-side with JavaScript.
  - The admin dashboard calls GET/POST/PUT/DELETE /admin/api/* endpoints
    to create, read, update, and delete content in the database.
  - The chatbot can be enabled/disabled from the admin dashboard.
  - Both share the same PostgreSQL database, so changes in the admin panel
    are immediately visible on the public site.

ADMIN AUTHENTICATION:
  - The admin dashboard is protected by a password.
  - Set the password via the ADMIN_PASSWORD environment variable.
  - Default password for development: "admin"
  - To change: set ADMIN_PASSWORD in your environment variables.

TO CUSTOMIZE:
  - To add a new content type (e.g., "testimonials"), follow these steps:
    1. Create a new table in the database (see init_db function below)
    2. Add public API routes (GET) for the public site
    3. Add admin API routes (GET/POST/PUT/DELETE) for the admin dashboard
    4. Update the admin dashboard HTML to include the new section
    5. Update the public site JS to fetch and render the new content

TO RUN:
  python app.py
  The server starts on port 5000.

===============================================================================
"""

import os
import re
import json
import html as html_module
import secrets
from datetime import datetime
from functools import wraps

import psycopg2
import psycopg2.extras
import sentry_sdk
from flask import (
    Flask, request, jsonify, send_from_directory,
    render_template, session, redirect, url_for, Response, stream_with_context
)
from openai import OpenAI

# =============================================================================
# ERROR TRACKING — Sentry (optional)
# =============================================================================
# Sentry captures unhandled exceptions, slow requests, and errors in production.
# To enable: set the SENTRY_DSN environment variable to your Sentry project DSN.
# Get your DSN from https://sentry.io → Project Settings → Client Keys (DSN).
# If SENTRY_DSN is not set, Sentry is silently disabled — no errors, no overhead.
sentry_dsn = os.environ.get("SENTRY_DSN")
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        traces_sample_rate=0.2,       # Capture 20% of transactions for performance monitoring
        profiles_sample_rate=0.1,     # Profile 10% of sampled transactions
        environment=os.environ.get("SENTRY_ENV", "production"),
        send_default_pii=False,       # Don't send personally identifiable information
    )

# =============================================================================
# APP CONFIGURATION
# =============================================================================

app = Flask(
    __name__,
    static_folder="public",       # Serve public site files from /public
    template_folder="templates"   # Jinja2 templates for admin dashboard
)

# Secret key for Flask sessions (used for admin login persistence)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

# Session cookie security settings
# SESSION_COOKIE_HTTPONLY: Prevents JavaScript from accessing the session cookie
# SESSION_COOKIE_SAMESITE: Prevents CSRF by limiting cross-site cookie sending
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Admin password — set via environment variable, defaults to "admin" for development
# IMPORTANT: Change this in production by setting the ADMIN_PASSWORD env var
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")

# Database connection string from environment variable
DATABASE_URL = os.environ.get("DATABASE_URL")

# OpenAI client — uses Replit AI Integrations environment variables
# These are automatically set when the OpenAI integration is installed
openai_client = OpenAI(
    api_key=os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY", ""),
    base_url=os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL", "https://api.openai.com/v1"),
)


# =============================================================================
# DATABASE HELPERS
# =============================================================================

def get_db():
    """
    Create and return a new database connection.
    Uses RealDictCursor so query results come back as dictionaries
    instead of tuples, making them easy to convert to JSON.
    """
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    return conn


def query_db(sql, params=None, fetchone=False):
    """
    Execute a SQL query and return results as a list of dicts (or a single dict).

    Args:
        sql (str): The SQL query to execute.
        params (tuple, optional): Parameters to safely inject into the query.
        fetchone (bool): If True, return only the first row.

    Returns:
        list[dict] or dict or None: Query results.
    """
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                rows = cur.fetchall()
                result = [dict(row) for row in rows]
                return result[0] if fetchone and result else result
            return None
    finally:
        conn.close()


def execute_db(sql, params=None):
    """
    Execute a SQL statement that modifies data (INSERT, UPDATE, DELETE).
    Returns the number of rows affected, or the new row for INSERT...RETURNING.

    Args:
        sql (str): The SQL statement to execute.
        params (tuple, optional): Parameters to safely inject.

    Returns:
        dict or int: The returned row (if RETURNING is used) or affected row count.
    """
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                return dict(cur.fetchone())
            return cur.rowcount
    finally:
        conn.close()


# =============================================================================
# DATABASE INITIALIZATION
# =============================================================================

def init_db():
    """
    Create all required tables if they don't already exist.
    This runs on every app startup to ensure the schema is ready.
    Existing data is never touched (IF NOT EXISTS / ON CONFLICT).
    """
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                -- Site-wide settings (singleton row with id=1)
                CREATE TABLE IF NOT EXISTS site_settings (
                    id            SERIAL PRIMARY KEY,
                    site_name     TEXT NOT NULL DEFAULT 'My Site',
                    site_subtitle TEXT NOT NULL DEFAULT 'Your Tagline Here',
                    hero_tagline  TEXT NOT NULL DEFAULT 'Welcome to Our Website',
                    hero_title    TEXT NOT NULL DEFAULT 'My Site',
                    hero_description TEXT NOT NULL DEFAULT '',
                    hero_image    TEXT NOT NULL DEFAULT '',
                    logo_initials TEXT NOT NULL DEFAULT 'CS',
                    created_at    TIMESTAMP DEFAULT NOW(),
                    updated_at    TIMESTAMP DEFAULT NOW()
                );

                -- Gallery slides / explore cards
                CREATE TABLE IF NOT EXISTS gallery_cards (
                    id          SERIAL PRIMARY KEY,
                    slug        VARCHAR(100) UNIQUE NOT NULL,
                    title       TEXT NOT NULL,
                    subtitle    TEXT NOT NULL,
                    image_url   TEXT NOT NULL,
                    category    VARCHAR(50) NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    details     JSONB DEFAULT '[]'::jsonb,
                    price       TEXT,
                    sort_order  INTEGER NOT NULL DEFAULT 0,
                    created_at  TIMESTAMP DEFAULT NOW(),
                    updated_at  TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_gallery_cards_sort ON gallery_cards (sort_order);

                -- Curated experiences
                CREATE TABLE IF NOT EXISTS experiences (
                    id          SERIAL PRIMARY KEY,
                    name        TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    icon        VARCHAR(50) NOT NULL DEFAULT 'star',
                    sort_order  INTEGER NOT NULL DEFAULT 0,
                    created_at  TIMESTAMP DEFAULT NOW(),
                    updated_at  TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_experiences_sort ON experiences (sort_order);

                -- Seasonal pricing tiers
                CREATE TABLE IF NOT EXISTS pricing_seasons (
                    id          SERIAL PRIMARY KEY,
                    label       VARCHAR(50) NOT NULL,
                    date_range  TEXT NOT NULL,
                    price_range TEXT NOT NULL,
                    sort_order  INTEGER NOT NULL DEFAULT 0,
                    created_at  TIMESTAMP DEFAULT NOW(),
                    updated_at  TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_pricing_sort ON pricing_seasons (sort_order);

                -- =============================================================
                -- CHATBOT SETTINGS (singleton row with id=1)
                -- =============================================================
                -- Controls whether the AI chatbot is shown on the public site,
                -- and how it connects to an AI agent.
                --
                -- enabled: Master on/off toggle. When false, no chatbot appears.
                -- mode: 'builtin' uses the template's built-in chat UI.
                --        'embed' loads an external chatbot widget via embed_code.
                -- agent_name: Display name shown in the chat bar.
                -- agent_role: Role label (e.g., "Concierge", "Assistant").
                -- agent_avatar: Text initials or image URL for the avatar.
                -- greeting: First message the bot sends when chat opens.
                -- quick_prompts: JSON array of suggested prompt strings.
                -- api_endpoint: URL to POST messages to (for builtin mode).
                -- embed_code: External HTML/script snippet (for embed mode).
                -- =============================================================
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

                -- Chat conversations (one per page load / session).
                -- session_id: unique per page load (new conversation each refresh).
                -- visitor_id: persistent across reloads (tracks returning visitors via localStorage).
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

                -- Chat messages (linked to conversations)
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id              SERIAL PRIMARY KEY,
                    conversation_id INTEGER REFERENCES chat_conversations(id) ON DELETE CASCADE,
                    role            VARCHAR(20) NOT NULL DEFAULT 'user',
                    content         TEXT NOT NULL DEFAULT '',
                    command_json    JSONB,
                    created_at      TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_chat_msg_conv ON chat_messages (conversation_id);

                -- Uploaded images
                CREATE TABLE IF NOT EXISTS uploaded_images (
                    id            SERIAL PRIMARY KEY,
                    filename      TEXT NOT NULL,
                    original_name TEXT NOT NULL DEFAULT '',
                    file_size     INTEGER DEFAULT 0,
                    uploaded_at   TIMESTAMP DEFAULT NOW()
                );

                -- Dynamic forms (form builder)
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

                -- Dynamic form fields
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
                    help_text       TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_form_fields_form ON form_fields (form_id);

                -- Dynamic form submissions (JSONB for flexible field storage)
                CREATE TABLE IF NOT EXISTS form_submissions (
                    id                SERIAL PRIMARY KEY,
                    form_id           INTEGER NOT NULL REFERENCES custom_forms(id) ON DELETE CASCADE,
                    submission_data   JSONB NOT NULL DEFAULT '{}'::jsonb,
                    status            VARCHAR(20) NOT NULL DEFAULT 'new',
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
                    submitted_at      TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_form_sub_form ON form_submissions (form_id);
                CREATE INDEX IF NOT EXISTS idx_form_sub_status ON form_submissions (status);

                -- AI-generated HTML pages (saved from the chatbot)
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

                -- =============================================================
                -- TESTIMONIALS / REVIEWS
                -- =============================================================
                -- Client reviews displayed on the public site.
                -- Each has a star rating (1-5), reviewer info, and optional photo.
                -- Enabled/disabled via section_testimonials toggle in site_settings.
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

                -- =============================================================
                -- TEAM MEMBERS
                -- =============================================================
                -- Staff/team member cards displayed on the public site.
                -- Enabled/disabled via section_team toggle in site_settings.
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

                -- =============================================================
                -- FREQUENTLY ASKED QUESTIONS
                -- =============================================================
                -- FAQ pairs shown in an accordion on the public site.
                -- Enabled/disabled via section_faq toggle in site_settings.
                CREATE TABLE IF NOT EXISTS faqs (
                    id          SERIAL PRIMARY KEY,
                    question    TEXT NOT NULL DEFAULT '',
                    answer      TEXT NOT NULL DEFAULT '',
                    sort_order  INTEGER NOT NULL DEFAULT 0,
                    created_at  TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_faqs_sort ON faqs (sort_order);

                -- =============================================================
                -- PAGE SECTIONS REGISTRY
                -- =============================================================
                -- Master list of ALL page sections (built-in + custom).
                -- Controls the order sections appear on the public site,
                -- which ones are enabled/disabled, and what template to use.
                -- Built-in sections (hero, highlights, etc.) are seeded on first run.
                -- Custom sections are created by the admin and use templates.
                CREATE TABLE IF NOT EXISTS page_sections (
                    id            SERIAL PRIMARY KEY,
                    slug          TEXT UNIQUE NOT NULL,
                    title         TEXT NOT NULL DEFAULT '',
                    section_type  TEXT NOT NULL DEFAULT 'built_in',
                    template      TEXT NOT NULL DEFAULT '',
                    sort_order    INTEGER NOT NULL DEFAULT 0,
                    enabled       BOOLEAN DEFAULT true,
                    settings      JSONB DEFAULT '{}'::jsonb,
                    created_at    TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_page_sections_sort ON page_sections (sort_order);

                -- =============================================================
                -- CUSTOM SECTION ITEMS
                -- =============================================================
                -- Content items for custom sections. Each item belongs to a
                -- page_section via section_id. The fields used depend on the
                -- section's template (cards_grid uses title/image/content,
                -- stats_counter uses title/subtitle for number/label, etc.)
                CREATE TABLE IF NOT EXISTS custom_section_items (
                    id          SERIAL PRIMARY KEY,
                    section_id  INTEGER NOT NULL REFERENCES page_sections(id) ON DELETE CASCADE,
                    title       TEXT NOT NULL DEFAULT '',
                    subtitle    TEXT NOT NULL DEFAULT '',
                    content     TEXT NOT NULL DEFAULT '',
                    image_url   TEXT NOT NULL DEFAULT '',
                    link_url    TEXT NOT NULL DEFAULT '',
                    link_text   TEXT NOT NULL DEFAULT '',
                    icon        TEXT NOT NULL DEFAULT '',
                    sort_order  INTEGER NOT NULL DEFAULT 0,
                    extra_data  JSONB DEFAULT '{}'::jsonb,
                    created_at  TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_custom_items_section ON custom_section_items (section_id, sort_order);

                -- =============================================================
                -- BLOG POSTS
                -- =============================================================
                -- Database-driven blog with gallery-style preview cards on the
                -- landing page. Each post has SEO fields, cover image, and
                -- supports draft/published workflow.
                CREATE TABLE IF NOT EXISTS blog_posts (
                    id              SERIAL PRIMARY KEY,
                    slug            TEXT UNIQUE NOT NULL,
                    title           TEXT NOT NULL,
                    subtitle        TEXT DEFAULT '',
                    excerpt         TEXT DEFAULT '',
                    content         TEXT DEFAULT '',
                    cover_image     TEXT DEFAULT '',
                    author          TEXT DEFAULT '',
                    category        TEXT DEFAULT '',
                    tags            TEXT DEFAULT '',
                    status          TEXT DEFAULT 'draft',
                    seo_title       TEXT DEFAULT '',
                    seo_description TEXT DEFAULT '',
                    published_at    TIMESTAMP,
                    created_at      TIMESTAMP DEFAULT NOW(),
                    updated_at      TIMESTAMP DEFAULT NOW(),
                    sort_order      INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_blog_posts_status ON blog_posts (status);
                CREATE INDEX IF NOT EXISTS idx_blog_posts_slug ON blog_posts (slug);
                CREATE INDEX IF NOT EXISTS idx_blog_posts_sort ON blog_posts (sort_order);

                -- =============================================================
                -- PAGE VIEWS — Visitor Analytics
                -- =============================================================
                -- Tracks individual page views for the visitor analytics
                -- dashboard. Captures session, referrer, UTM params, device
                -- info, and session duration for aggregated reporting.
                CREATE TABLE IF NOT EXISTS page_views (
                    id                SERIAL PRIMARY KEY,
                    session_id        VARCHAR(100) NOT NULL,
                    visitor_id        VARCHAR(100) DEFAULT '',
                    page_url          TEXT NOT NULL,
                    referrer_url      TEXT DEFAULT '',
                    utm_source        TEXT DEFAULT '',
                    utm_medium        TEXT DEFAULT '',
                    utm_campaign      TEXT DEFAULT '',
                    utm_term          TEXT DEFAULT '',
                    utm_content       TEXT DEFAULT '',
                    ip_address        VARCHAR(45) DEFAULT '',
                    browser           TEXT DEFAULT '',
                    os                TEXT DEFAULT '',
                    device_type       TEXT DEFAULT 'desktop',
                    screen_resolution TEXT DEFAULT '',
                    language          TEXT DEFAULT '',
                    country           TEXT DEFAULT '',
                    duration_seconds  INTEGER DEFAULT 0,
                    created_at        TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_page_views_session ON page_views (session_id);
                CREATE INDEX IF NOT EXISTS idx_page_views_created ON page_views (created_at);
                CREATE INDEX IF NOT EXISTS idx_page_views_page ON page_views (page_url);
            """)

            # Seed chatbot_settings singleton if it doesn't exist
            cur.execute("""
                INSERT INTO chatbot_settings (id, enabled, mode, agent_name, agent_role, agent_avatar,
                    greeting, quick_prompts, api_endpoint, embed_code)
                VALUES (1, false, 'builtin', 'AI Assistant', 'Assistant', 'A',
                    'Welcome! I''m your AI assistant. How can I help you today?',
                    '["Browse our gallery", "Tell me more", "What do you offer?", "Show me pricing"]'::jsonb,
                    '/api/chat', '')
                ON CONFLICT (id) DO NOTHING
            """)

            # Add new columns to existing tables (safe — does nothing if already present)
            for col_sql in [
                "ALTER TABLE chatbot_settings ADD COLUMN IF NOT EXISTS system_prompt TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS theme_bg TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS theme_section1 TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS theme_section2 TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS theme_accent TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS theme_text TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS theme_glass_border TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS theme_glass_bg TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS theme_font_serif TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS theme_font_sans TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE form_submissions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()",
                "ALTER TABLE form_submissions ADD COLUMN IF NOT EXISTS confirmation_number VARCHAR(20) DEFAULT ''",
                "ALTER TABLE form_fields ADD COLUMN IF NOT EXISTS step INTEGER NOT NULL DEFAULT 1",
                "ALTER TABLE chat_conversations ADD COLUMN IF NOT EXISTS visitor_id VARCHAR(100) DEFAULT ''",
                # --- Section visibility toggles (admin can show/hide entire sections) ---
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS section_testimonials BOOLEAN DEFAULT false",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS section_team BOOLEAN DEFAULT false",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS section_faq BOOLEAN DEFAULT false",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS section_footer BOOLEAN DEFAULT true",
                # --- Business contact information ---
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS business_phone TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS business_email TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS business_address TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS business_hours JSONB DEFAULT '[]'::jsonb",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS business_map_embed TEXT NOT NULL DEFAULT ''",
                # --- Social media profile links (JSON object) ---
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS social_links JSONB DEFAULT '{}'::jsonb",
                # --- SEO settings columns (admin-managed meta tags for the public site) ---
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS seo_meta_title TEXT DEFAULT ''",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS seo_meta_description TEXT DEFAULT ''",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS seo_keywords TEXT DEFAULT ''",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS seo_og_image TEXT DEFAULT ''",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS seo_twitter_handle TEXT DEFAULT ''",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS seo_canonical_url TEXT DEFAULT ''",
                "ALTER TABLE site_settings ADD COLUMN IF NOT EXISTS seo_robots TEXT DEFAULT 'index, follow'",
            ]:
                cur.execute(col_sql)

            # Seed a default "Contact / Inquiry" form if no forms exist yet
            # This is sample data — customize it from the admin panel for your industry
            cur.execute("SELECT COUNT(*) FROM custom_forms")
            row = cur.fetchone()
            form_count = row[0] if row else 0
            if form_count == 0:
                cur.execute("""
                    INSERT INTO custom_forms (name, slug, description, status, submit_button_text, success_message, sort_order)
                    VALUES ('Contact Request', 'contact-request',
                            'Get in touch with us',
                            'active', 'Submit Request',
                            'Thank you! Your request has been received. We will get back to you within 24 hours.',
                            0)
                    RETURNING id
                """)
                form_row = cur.fetchone()
                if form_row:
                    fid = form_row[0]
                    fields = [
                        (fid, 'text',   'Full Name',    'name',      'Enter your full name', True,  None, '', 0, 'full', '', '', 1),
                        (fid, 'email',  'Email',        'email',     'your@email.com',       True,  None, '', 1, 'full', '', '', 1),
                        (fid, 'select', 'Service',      'service',   '',                     True,  '[]', '', 2, 'full', '', 'Select your preferred option', 1),
                        (fid, 'date',   'Start Date',   'start_date','',                     True,  None, '', 3, 'half', '', '', 2),
                        (fid, 'date',   'End Date',     'end_date',  '',                     True,  None, '', 4, 'half', '', '', 2),
                        (fid, 'number', 'Quantity',     'quantity',  '',                     False, None, '1', 5, 'half', '', 'How many?', 2),
                        (fid, 'tel',    'Phone',        'phone',     '+1 (555) 000-0000',    False, None, '', 6, 'half', '', '', 2),
                        (fid, 'textarea','Additional Details','details','Any special requirements or preferences...', False, None, '', 7, 'full', '', '', 3),
                    ]
                    for f in fields:
                        cur.execute("""
                            INSERT INTO form_fields (form_id, field_type, label, name, placeholder, required, options, default_value, sort_order, width, validation_regex, help_text, step)
                            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
                        """, f)

            # Seed built-in page sections if the table is empty
            # These represent the hardcoded sections that exist in index.html.
            # The admin can reorder them but not delete them.
            cur.execute("SELECT COUNT(*) FROM page_sections")
            row = cur.fetchone()
            section_count = row[0] if row else 0
            if section_count == 0:
                built_in_sections = [
                    ('hero',         'Hero',            'built_in', 'hero',         0, True),
                    ('highlights',   'Gallery Highlights', 'built_in', 'highlights', 1, True),
                    ('experiences',  'Experiences & Pricing', 'built_in', 'experiences', 2, True),
                    ('testimonials', 'Testimonials',    'built_in', 'testimonials', 3, False),
                    ('team',         'Our Team',        'built_in', 'team',         4, False),
                    ('faq',          'FAQ',             'built_in', 'faq',          5, False),
                    ('blog',         'Latest Stories',  'built_in', 'blog',         6, False),
                    ('footer',       'Footer',          'built_in', 'footer',       7, True),
                ]
                for slug, title, stype, tmpl, order, enabled in built_in_sections:
                    cur.execute("""
                        INSERT INTO page_sections (slug, title, section_type, template, sort_order, enabled)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (slug) DO NOTHING
                    """, (slug, title, stype, tmpl, order, enabled))

            # =============================================================
            # SEED: Insert the 'blog' page section if it doesn't exist yet
            # (for databases that were initialized before blog support)
            # =============================================================
            cur.execute("""
                INSERT INTO page_sections (slug, title, section_type, template, sort_order, enabled)
                VALUES ('blog', 'Latest Stories', 'built_in', 'blog', 6, false)
                ON CONFLICT (slug) DO NOTHING
            """)

            cur.execute("""
                INSERT INTO page_sections (slug, title, section_type, template, sort_order, enabled)
                VALUES ('business-info', 'Contact Us', 'built_in', 'business-info', 7, true)
                ON CONFLICT (slug) DO NOTHING
            """)

            cur.execute("SELECT COUNT(*) FROM custom_forms WHERE slug = 'contact-us'")
            contact_form_exists = cur.fetchone()[0]
            if contact_form_exists == 0:
                cur.execute("""
                    INSERT INTO custom_forms (name, slug, description, status, submit_button_text, success_message, sort_order)
                    VALUES ('Contact Us', 'contact-us', 'General contact and inquiry form',
                            'active', 'Send Message',
                            'Thank you for reaching out! We will get back to you soon.',
                            COALESCE((SELECT MAX(sort_order)+1 FROM custom_forms), 0))
                    RETURNING id
                """)
                contact_form_id = cur.fetchone()[0]
                contact_fields = [
                    ('full_name', 'Full Name', 'text', True, 'Your name', 1, 'half'),
                    ('email', 'Email Address', 'email', True, 'you@example.com', 2, 'half'),
                    ('subject', 'Subject', 'text', False, 'What is this about?', 3, 'full'),
                    ('message', 'Message', 'textarea', True, 'Tell us more...', 4, 'full'),
                ]
                for fname, flabel, ftype, freq, fplaceholder, fsort, fwidth in contact_fields:
                    cur.execute("""
                        INSERT INTO form_fields (form_id, field_type, label, name, placeholder, required, sort_order, width, step)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
                    """, (contact_form_id, ftype, flabel, fname, fplaceholder, freq, fsort, fwidth))

            # =============================================================
            # SEED: Sample blog post (industry-agnostic)
            # =============================================================
            # Insert one well-written sample blog post so the blog section
            # has content to display immediately. Only inserted if no blog
            # posts exist yet — admins can edit or delete from the dashboard.
            cur.execute("SELECT COUNT(*) FROM blog_posts")
            row = cur.fetchone()
            blog_count = row[0] if row else 0
            if blog_count == 0:
                cur.execute("""
                    INSERT INTO blog_posts (
                        slug, title, subtitle, excerpt, content, cover_image,
                        author, category, tags, status, seo_title, seo_description,
                        published_at, sort_order
                    ) VALUES (
                        'the-art-of-first-impressions',
                        'The Art of First Impressions: Why Every Detail Matters',
                        'How thoughtful design transforms ordinary moments into lasting memories',
                        'First impressions are formed in milliseconds, yet their impact endures for years. Discover how attention to detail — from the warmth of a greeting to the subtlety of ambient lighting — shapes the way people experience your space and your brand.',
                        '<p>First impressions are formed in milliseconds, yet their impact endures for years. Whether you are welcoming a guest into a boutique hotel, greeting a client at your office, or launching a new product online, the initial moment of contact sets the tone for everything that follows.</p>

<h2>The Science Behind First Impressions</h2>
<p>Research in cognitive psychology shows that people make judgments about trustworthiness, competence, and likability within the first seven seconds of an encounter. These snap judgments are remarkably persistent — once formed, they color every subsequent interaction.</p>
<p>This is not limited to face-to-face meetings. Digital experiences follow the same pattern. A website visitor decides whether to stay or leave in roughly 50 milliseconds, based on visual appeal alone. The implications for businesses are profound: every pixel, every word, and every interaction point is an opportunity to build — or erode — trust.</p>

<h2>Details That Make the Difference</h2>
<p>The most memorable experiences share a common thread: intentionality. Nothing feels accidental. Consider these elements that elevate an ordinary moment into something remarkable:</p>
<ul>
<li><strong>Consistency</strong> — Every touchpoint reflects the same values and aesthetic, from signage to staff demeanor to digital presence.</li>
<li><strong>Sensory awareness</strong> — Lighting, temperature, scent, and sound are calibrated to create comfort without being obtrusive.</li>
<li><strong>Personalization</strong> — Small gestures that acknowledge the individual — a remembered name, a tailored recommendation — signal genuine care.</li>
<li><strong>Anticipation</strong> — Great hosts solve problems before they arise. The umbrella by the door on a cloudy day. The FAQ that answers the question before it is asked.</li>
</ul>

<h2>Translating This to Your Brand</h2>
<p>Whether you run a physical space or a digital platform, the principle is the same: design every interaction as if it were the first and only chance to earn someone''s trust. Audit your customer journey from the outside in. What does a newcomer see, feel, and understand in those critical opening seconds?</p>
<p>The brands that thrive are those that treat first impressions not as a marketing problem, but as a design philosophy — one that permeates every layer of the experience.</p>

<h2>Start With One Thing</h2>
<p>You do not need to overhaul everything at once. Pick the single most common entry point for your audience — your homepage, your front door, your opening email — and refine it until it feels effortless. Then move to the next. Excellence is built one detail at a time.</p>',
                        '',
                        'Editorial Team',
                        'Insights',
                        'branding, design, customer experience, first impressions',
                        'published',
                        'The Art of First Impressions: Why Every Detail Matters',
                        'Discover how attention to detail shapes lasting impressions — from the warmth of a greeting to the subtlety of ambient design.',
                        NOW(),
                        0
                    ) ON CONFLICT (slug) DO NOTHING
                """)
    finally:
        conn.close()


# =============================================================================
# CUSTOM JSON ENCODER
# =============================================================================

class CustomJSONEncoder(json.JSONEncoder):
    """Handle datetime and boolean serialization for JSON responses."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

app.json_encoder = CustomJSONEncoder


# =============================================================================
# ADMIN AUTHENTICATION
# =============================================================================
# Protects the admin dashboard with a simple password login.
# The password is set via the ADMIN_PASSWORD environment variable.
#
# HOW IT WORKS:
# - When a user visits /admin, they're redirected to /admin/login if not logged in.
# - After entering the correct password, a session cookie is set.
# - The session persists until the user logs out or closes the browser.
#
# TO CHANGE THE PASSWORD:
# - Set the ADMIN_PASSWORD environment variable to your desired password.
# - Default is "admin" for development only.
#
# FOR STRONGER SECURITY:
# - Use a long, random password in production.
# - Consider adding rate limiting to prevent brute-force attacks.
# - Consider adding HTTPS-only cookie flags.
# =============================================================================

def admin_required(f):
    """
    Decorator that protects a route with admin authentication.
    Redirects to the login page if the user isn't logged in.
    Use this on any route that should be admin-only.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """
    GET: Show the login form.
    POST: Validate the password and log in.
    """
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))
        else:
            error = "Invalid password. Please try again."

    return render_template("admin/login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    """Log out of the admin dashboard and redirect to login."""
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))


# =============================================================================
# SEO HELPERS — Build meta tags and structured data from database settings
# =============================================================================
# These functions read SEO settings from the site_settings table and produce
# HTML strings that are injected into index.html server-side, so search engine
# crawlers see proper meta tags without needing JavaScript execution.

def _esc(s):
    """
    HTML-escape a string for safe use in meta tag attributes.
    Prevents XSS if SEO fields contain special characters.
    """
    return html_module.escape(str(s), quote=True)


def _build_seo_meta_html():
    """
    Build the complete SEO meta tags HTML block from database settings.
    Returns an HTML string containing: title, meta description, keywords,
    robots directive, canonical URL, Open Graph tags, Twitter Card tags,
    and favicon links. Falls back to site_settings values if SEO-specific
    fields are empty.
    """
    settings = query_db("SELECT * FROM site_settings WHERE id = 1", fetchone=True)
    if not settings:
        settings = {}

    # Determine SEO values with cascading fallbacks
    title = (settings.get("seo_meta_title") or "").strip()
    if not title:
        # Fall back to site name + subtitle for the page title
        site_name = settings.get("site_name", "My Site")
        subtitle = settings.get("site_subtitle", "")
        title = f"{site_name} — {subtitle}" if subtitle else site_name

    description = (settings.get("seo_meta_description") or "").strip()
    if not description:
        # Fall back to the hero description text
        description = settings.get("hero_description", "")

    keywords = (settings.get("seo_keywords") or "").strip()
    og_image = (settings.get("seo_og_image") or "").strip() or "/ai_concierge.png"
    twitter_handle = (settings.get("seo_twitter_handle") or "").strip()
    canonical_url = (settings.get("seo_canonical_url") or "").strip()
    robots = (settings.get("seo_robots") or "").strip() or "index, follow"
    site_name = settings.get("site_name", "My Site")

    lines = []

    # --- Core meta tags ---
    lines.append('  <!-- SEO Meta Tags — Injected server-side from database settings -->')
    lines.append(f'  <title>{_esc(title)}</title>')
    lines.append(f'  <meta name="description" content="{_esc(description)}">')
    if keywords:
        lines.append(f'  <meta name="keywords" content="{_esc(keywords)}">')
    lines.append(f'  <meta name="robots" content="{_esc(robots)}">')
    if canonical_url:
        lines.append(f'  <link rel="canonical" href="{_esc(canonical_url)}">')

    # --- Favicon ---
    lines.append('  <!-- Favicon — Shows next to the URL in browser tabs and on smartphone home screens -->')
    lines.append('  <link rel="icon" type="image/png" href="/ai_concierge.png">')
    lines.append('  <link rel="apple-touch-icon" href="/ai_concierge.png">')

    # --- Open Graph tags (for Facebook, LinkedIn, etc.) ---
    lines.append('  <!-- Open Graph Tags — For social media sharing -->')
    lines.append(f'  <meta property="og:title" content="{_esc(title)}">')
    lines.append(f'  <meta property="og:description" content="{_esc(description)}">')
    lines.append('  <meta property="og:type" content="website">')
    lines.append(f'  <meta property="og:image" content="{_esc(og_image)}">')
    if canonical_url:
        lines.append(f'  <meta property="og:url" content="{_esc(canonical_url)}">')
    lines.append(f'  <meta property="og:site_name" content="{_esc(site_name)}">')

    # --- Twitter Card tags ---
    lines.append('  <!-- Twitter Card Tags -->')
    lines.append('  <meta name="twitter:card" content="summary_large_image">')
    lines.append(f'  <meta name="twitter:title" content="{_esc(title)}">')
    lines.append(f'  <meta name="twitter:description" content="{_esc(description)}">')
    lines.append(f'  <meta name="twitter:image" content="{_esc(og_image)}">')
    if twitter_handle:
        # Ensure handle starts with @
        handle = twitter_handle if twitter_handle.startswith("@") else f"@{twitter_handle}"
        lines.append(f'  <meta name="twitter:site" content="{_esc(handle)}">')

    return "\n".join(lines)


def _build_json_ld():
    """
    Build JSON-LD structured data for search engine rich results.
    Returns an HTML string containing two <script type="application/ld+json"> blocks:
      1. Organization schema — site name, URL, logo, and social profiles
      2. WebSite schema — site name, URL, and description
    These help Google and other search engines understand the site's identity
    and display enhanced search results (knowledge panels, sitelinks, etc.).
    """
    settings = query_db("SELECT * FROM site_settings WHERE id = 1", fetchone=True) or {}

    site_name = settings.get("site_name", "My Site")
    canonical_url = (settings.get("seo_canonical_url") or "").strip()
    og_image = (settings.get("seo_og_image") or "").strip() or "/ai_concierge.png"
    description = (settings.get("seo_meta_description") or "").strip() or settings.get("hero_description", "")

    # Build social profile URLs array from the social_links JSONB column
    social_links = settings.get("social_links", {})
    if isinstance(social_links, str):
        try:
            social_links = json.loads(social_links)
        except Exception:
            social_links = {}
    same_as = [url for url in social_links.values() if url and isinstance(url, str)]

    # Organization schema — tells search engines who operates this site
    org_data = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": site_name,
        "url": canonical_url or "/",
        "logo": og_image,
    }
    if same_as:
        org_data["sameAs"] = same_as

    # WebSite schema — tells search engines about the site itself
    website_data = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": site_name,
        "url": canonical_url or "/",
        "description": description,
    }

    lines = []
    lines.append('  <!-- JSON-LD Structured Data — Injected server-side for SEO -->')
    lines.append(f'  <script type="application/ld+json">{json.dumps(org_data)}</script>')
    lines.append(f'  <script type="application/ld+json">{json.dumps(website_data)}</script>')

    return "\n".join(lines)


# =============================================================================
# PUBLIC ROUTES — Serve the static HTML site
# =============================================================================

@app.route("/")
def serve_index():
    """
    Serve the main public website with SEO meta tags injected server-side.
    Reads public/index.html and replaces placeholder markers with actual
    meta tags from the database, so search engine crawlers see proper SEO
    data (title, description, OG tags, Twitter Cards, JSON-LD) without
    needing JavaScript execution.
    """
    try:
        # Read the base HTML template from the public directory
        index_path = os.path.join(app.static_folder, "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # Inject SEO meta tags (replaces the <!-- SEO_META_INJECT --> placeholder in <head>)
        seo_html = _build_seo_meta_html()
        html_content = html_content.replace("<!-- SEO_META_INJECT -->", seo_html)

        # Inject JSON-LD structured data (replaces the <!-- JSON_LD_INJECT --> placeholder before </head>)
        json_ld_html = _build_json_ld()
        html_content = html_content.replace("<!-- JSON_LD_INJECT -->", json_ld_html)

        return Response(html_content, mimetype="text/html")
    except Exception:
        # Fallback: serve the raw file if SEO injection fails
        return send_from_directory("public", "index.html")


# =============================================================
# PUBLIC BLOG PAGE — Individual blog post pages
# =============================================================

@app.route("/blog/<string:slug>")
def serve_blog_post(slug):
    """
    GET /blog/<slug>
    Serves a standalone blog post page with the same dark theme and
    frosted glass aesthetic as the main site. Injects SEO meta tags
    (seo_title, seo_description, cover_image as og:image) for each post.
    Returns 404 if the post doesn't exist or isn't published.
    """
    # Fetch the blog post by slug — only published posts are visible
    post = query_db(
        "SELECT * FROM blog_posts WHERE slug = %s AND status = 'published'",
        (slug,), fetchone=True
    )
    if not post:
        return "Post not found", 404

    # Fetch site settings for branding (site name, theme colors, etc.)
    settings = query_db("SELECT * FROM site_settings WHERE id = 1", fetchone=True) or {}

    # Build theme colors dict for the blog post template (mirrors chat theme injection)
    theme_colors = {
        "bg": settings.get("theme_bg", "#060b14") or "#060b14",
        "accent": settings.get("theme_accent", "#c9a96e") or "#c9a96e",
        "text": settings.get("theme_text", "#e4e4e7") or "#e4e4e7",
        "glass_bg": settings.get("theme_glass_bg", "rgba(255,255,255,0.03)") or "rgba(255,255,255,0.03)",
        "glass_border": settings.get("theme_glass_border", "rgba(255,255,255,0.08)") or "rgba(255,255,255,0.08)",
        "font_serif": settings.get("theme_font_serif", "Playfair Display") or "Playfair Display",
        "font_sans": settings.get("theme_font_sans", "DM Sans") or "DM Sans",
    }

    return render_template(
        "blog_post.html",
        post=post,
        settings=settings,
        theme=theme_colors
    )


@app.route("/<path:filename>")
def serve_static(filename):
    """
    Serve any static file from the /public directory.
    This handles CSS, JS, images, fonts, etc.
    Falls through to serve_index() if the file doesn't exist (SPA-style fallback).
    """
    try:
        return send_from_directory("public", filename)
    except Exception:
        # SPA fallback — serve the SEO-injected index for unknown paths
        return serve_index()


# =============================================================================
# PUBLIC API — Read-only endpoints for the public site
# =============================================================================

@app.route("/api/site-settings")
def api_site_settings():
    """
    GET /api/site-settings
    Returns the site-wide configuration (name, tagline, hero content, etc.).
    """
    settings = query_db("SELECT * FROM site_settings WHERE id = 1", fetchone=True)
    if not settings:
        return jsonify({"error": "No site settings found"}), 404
    return jsonify(settings)


@app.route("/api/gallery-cards")
def api_gallery_cards():
    """
    GET /api/gallery-cards
    Returns all gallery cards ordered by sort_order.
    """
    cards = query_db("SELECT * FROM gallery_cards ORDER BY sort_order ASC")
    return jsonify(cards or [])


@app.route("/api/experiences")
def api_experiences():
    """
    GET /api/experiences
    Returns all curated experiences ordered by sort_order.
    """
    exps = query_db("SELECT * FROM experiences ORDER BY sort_order ASC")
    return jsonify(exps or [])


@app.route("/api/pricing")
def api_pricing():
    """
    GET /api/pricing
    Returns all pricing seasons ordered by sort_order.
    """
    pricing = query_db("SELECT * FROM pricing_seasons ORDER BY sort_order ASC")
    return jsonify(pricing or [])


# =============================================================
# PUBLIC API — TESTIMONIALS
# =============================================================
@app.route("/api/testimonials")
def api_testimonials():
    """
    GET /api/testimonials
    Returns all testimonials ordered by sort_order.
    Only returned if the section is enabled in site_settings.
    """
    testimonials = query_db("SELECT * FROM testimonials ORDER BY sort_order ASC")
    return jsonify(testimonials or [])


# =============================================================
# PUBLIC API — TEAM MEMBERS
# =============================================================
@app.route("/api/team")
def api_team():
    """
    GET /api/team
    Returns all team members ordered by sort_order.
    Only returned if the section is enabled in site_settings.
    """
    team = query_db("SELECT * FROM team_members ORDER BY sort_order ASC")
    return jsonify(team or [])


# =============================================================
# PUBLIC API — FAQ
# =============================================================
@app.route("/api/faq")
def api_faq():
    """
    GET /api/faq
    Returns all FAQ entries ordered by sort_order.
    Only returned if the section is enabled in site_settings.
    """
    faqs = query_db("SELECT * FROM faqs ORDER BY sort_order ASC")
    return jsonify(faqs or [])


# =============================================================
# PUBLIC API — BLOG POSTS
# =============================================================

@app.route("/api/blog")
def api_blog():
    """
    GET /api/blog
    Returns all published blog posts, sorted by published_at DESC
    (most recent first), with sort_order as a secondary sort.
    Only published posts are returned to the public site.
    """
    posts = query_db(
        """SELECT id, slug, title, subtitle, excerpt, cover_image,
                  author, category, tags, published_at, sort_order
           FROM blog_posts
           WHERE status = 'published'
           ORDER BY sort_order ASC, published_at DESC"""
    )
    return jsonify(posts or [])


@app.route("/api/blog/<string:slug>")
def api_blog_post(slug):
    """
    GET /api/blog/<slug>
    Returns a single published blog post by its URL slug.
    Used by the blog detail page and for preview cards.
    """
    post = query_db(
        "SELECT * FROM blog_posts WHERE slug = %s AND status = 'published'",
        (slug,), fetchone=True
    )
    if not post:
        return jsonify({"error": "Blog post not found"}), 404
    return jsonify(post)


# =============================================================
# PUBLIC API — BUSINESS INFO
# =============================================================
@app.route("/api/business-info")
def api_business_info():
    """
    GET /api/business-info
    Returns business contact info, hours, and social links
    from the site_settings table (single-row config).
    """
    info = query_db("""
        SELECT business_phone, business_email, business_address,
               business_hours, business_map_embed, social_links
        FROM site_settings WHERE id = 1
    """, fetchone=True)
    if not info:
        return jsonify({})
    return jsonify(info)


# =============================================================
# PUBLIC API — SEO SETTINGS
# =============================================================

@app.route("/api/seo")
def api_seo():
    """
    GET /api/seo
    Returns the SEO settings for the public site. These are the values
    injected into the <head> meta tags by serve_index(). This endpoint
    is also available for any client-side JavaScript that needs SEO data.
    """
    settings = query_db("""
        SELECT seo_meta_title, seo_meta_description, seo_keywords,
               seo_og_image, seo_twitter_handle, seo_canonical_url,
               seo_robots, site_name, site_subtitle, hero_description
        FROM site_settings WHERE id = 1
    """, fetchone=True)
    if not settings:
        return jsonify({})
    return jsonify(settings)


# =============================================================
# PUBLIC — SITEMAP.XML (auto-generated from database content)
# =============================================================

@app.route("/sitemap.xml")
def sitemap():
    """
    GET /sitemap.xml
    Auto-generated XML sitemap including the home page, published blog
    posts, and published AI-generated pages. Search engines use this to
    discover and index all public URLs on the site.
    """
    # Determine the base URL from SEO settings or the request URL
    settings = query_db(
        "SELECT seo_canonical_url FROM site_settings WHERE id = 1",
        fetchone=True
    )
    base_url = ""
    if settings:
        base_url = (settings.get("seo_canonical_url") or "").strip().rstrip("/")
    if not base_url:
        # Fall back to the request's host URL
        base_url = request.url_root.rstrip("/")

    urls = []

    # Home page — highest priority, changes daily
    urls.append({
        "loc": base_url + "/",
        "priority": "1.0",
        "changefreq": "daily"
    })

    # Published blog posts — medium-high priority
    posts = query_db(
        "SELECT slug, updated_at FROM blog_posts WHERE status = 'published' ORDER BY published_at DESC"
    )
    for post in (posts or []):
        lastmod = ""
        if post.get("updated_at"):
            lastmod = post["updated_at"].strftime("%Y-%m-%d")
        urls.append({
            "loc": f"{base_url}/blog/{post['slug']}",
            "priority": "0.7",
            "changefreq": "weekly",
            "lastmod": lastmod
        })

    # Published AI-generated pages — lower priority
    pages = query_db(
        "SELECT slug, updated_at FROM generated_pages WHERE status = 'published' ORDER BY created_at DESC"
    )
    for page in (pages or []):
        lastmod = ""
        if page.get("updated_at"):
            lastmod = page["updated_at"].strftime("%Y-%m-%d")
        urls.append({
            "loc": f"{base_url}/page/{page['slug']}",
            "priority": "0.5",
            "changefreq": "monthly",
            "lastmod": lastmod
        })

    # Build the XML sitemap document
    xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml_parts.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for url in urls:
        xml_parts.append("  <url>")
        xml_parts.append(f"    <loc>{_esc(url['loc'])}</loc>")
        if url.get("lastmod"):
            xml_parts.append(f"    <lastmod>{url['lastmod']}</lastmod>")
        xml_parts.append(f"    <changefreq>{url.get('changefreq', 'weekly')}</changefreq>")
        xml_parts.append(f"    <priority>{url.get('priority', '0.5')}</priority>")
        xml_parts.append("  </url>")
    xml_parts.append("</urlset>")

    return Response("\n".join(xml_parts), mimetype="application/xml")


# =============================================================
# PUBLIC — ROBOTS.TXT (standard crawler directives)
# =============================================================

@app.route("/robots.txt")
def robots_txt():
    """
    GET /robots.txt
    Standard robots.txt file that allows all crawlers and points them
    to the sitemap. The sitemap URL is derived from the canonical URL
    in SEO settings, or from the current request's host.
    """
    # Determine sitemap URL
    settings = query_db(
        "SELECT seo_canonical_url FROM site_settings WHERE id = 1",
        fetchone=True
    )
    base_url = ""
    if settings:
        base_url = (settings.get("seo_canonical_url") or "").strip().rstrip("/")
    if not base_url:
        base_url = request.url_root.rstrip("/")

    # Standard robots.txt — allow all crawlers, point to sitemap
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        "# Disallow admin and API routes from indexing\n"
        "Disallow: /admin/\n"
        "Disallow: /api/\n"
        "\n"
        f"Sitemap: {base_url}/sitemap.xml\n"
    )
    return Response(content, mimetype="text/plain")


# =============================================================
# PUBLIC API — PAGE SECTIONS (controls section order on public site)
# =============================================================
@app.route("/api/page-sections")
def api_page_sections():
    """
    GET /api/page-sections
    Returns ALL sections (enabled and disabled) ordered by sort_order.
    The frontend uses this to determine section order AND visibility —
    it needs disabled sections in the list so it can hide them properly.
    """
    sections = query_db(
        "SELECT * FROM page_sections ORDER BY sort_order ASC"
    )
    return jsonify(sections or [])


# =============================================================
# PUBLIC API — CUSTOM SECTION ITEMS
# =============================================================
@app.route("/api/custom-section/<int:section_id>/items")
def api_custom_section_items(section_id):
    """
    GET /api/custom-section/<section_id>/items
    Returns all items for a specific custom section, ordered by sort_order.
    """
    items = query_db(
        "SELECT * FROM custom_section_items WHERE section_id = %s ORDER BY sort_order ASC",
        (section_id,)
    )
    return jsonify(items or [])


@app.route("/api/chatbot-settings")
def api_chatbot_settings():
    """
    GET /api/chatbot-settings
    Returns the chatbot configuration for the public site.
    The public site JavaScript uses this to decide whether to show
    the chatbot and how to configure it.
    """
    settings = query_db("SELECT * FROM chatbot_settings WHERE id = 1", fetchone=True)
    if not settings:
        return jsonify({"enabled": False})
    return jsonify(settings)


# =============================================================================
# CHAT API — AI Chatbot Endpoint
# =============================================================================
# This endpoint receives messages from the chatbot and returns responses.
#
# REQUEST FORMAT:
#   POST /api/chat
#   Content-Type: application/json
#   Body: {
#     "message": "Show me the pool",
#     "history": [
#       { "role": "assistant", "content": "Welcome! How can I help?" },
#       { "role": "user", "content": "Show me the pool" }
#     ]
#   }
#
# RESPONSE FORMAT:
#   The response can include a text reply AND optional commands:
#
#   Plain text reply:
#   { "reply": "Here's what I found..." }
#
#   Reply with navigation command (scroll to a gallery slide):
#   {
#     "reply": "Let me show you our stunning infinity pool!",
#     "command": { "action": "navigate", "target": "infinity-pool" }
#   }
#
#   Reply with structured slide (presentation-style):
#   {
#     "reply": "Here's a comparison of our options.",
#     "command": {
#       "action": "showSlide",
#       "title": "Options Comparison",
#       "subtitle": "Finding your perfect match",
#       "points": ["Option A: $1,800", "Option B: $1,200"]
#     }
#   }
#
#   Reply with custom HTML (AI-generated dynamic content):
#   {
#     "reply": "I've created a pricing breakdown for you.",
#     "command": {
#       "action": "generateHTML",
#       "title": "Pricing Breakdown",
#       "html": "<div style='padding:2rem;'><h2>Pricing</h2><table>...</table></div>"
#     }
#   }
#
# AVAILABLE COMMANDS (the AI can send these to control the website):
#
#   1. navigate — Scrolls the site to a specific gallery slide
#      { "action": "navigate", "target": "<card-slug>" }
#      Valid targets: any slug from the gallery_cards table
#      (e.g., "hero-image", "featured-item", "gallery-item-1", etc.)
#
#   2. showSlide — Shows a structured presentation overlay
#      { "action": "showSlide", "title": "...", "subtitle": "...",
#        "points": ["point 1", "point 2"], "image": "optional URL" }
#
#   3. generateHTML — Renders custom AI-generated HTML in a canvas
#      { "action": "generateHTML", "title": "Page Title", "html": "<div>Any valid HTML</div>" }
#      The AI can generate comparison tables, charts, custom layouts, etc.
#      Generated pages are auto-saved to the database for admin review.
#
#   4. submitForm — Submit a form with data collected in conversation
#      { "action": "submitForm", "slug": "form-slug", "fields": {"name": "value"} }
#      The AI collects form field values through conversation, then submits them.
#
#   5. partialFormSave — Auto-save partial form data during collection
#      { "action": "partialFormSave", "slug": "form-slug", "fields": {"name": "value"} }
#      Sent after each field is collected for abandon/lead recovery.
#
# HOW TO ADD MORE COMMANDS:
#   1. Define the command format in this comment block
#   2. Add handling logic in script.js (see the executeCommand function)
#   3. Update the system prompt to teach the AI about the new command
#   4. Test with a sample response
#
# HOW TO CONNECT TO OPENAI:
#   Install the openai package: pip install openai
#   Then replace the placeholder logic below with:
#
#   from openai import OpenAI
#   client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
#
#   # In the chat endpoint:
#   completion = client.chat.completions.create(
#       model="gpt-4o-mini",
#       messages=[
#           {"role": "system", "content": SYSTEM_PROMPT},
#           *history
#       ],
#       tools=[...],  # Define your function calling tools here
#   )
#
# HOW TO CONNECT TO A CUSTOM MULTI-AGENT API:
#   Replace the placeholder logic with a request to your agent's API:
#
#   import requests
#   response = requests.post("https://your-agent-api.com/chat",
#       json={"message": message, "history": history},
#       headers={"Authorization": f"Bearer {os.environ.get('AGENT_API_KEY')}"}
#   )
#   return jsonify(response.json())
#
# SAMPLE SYSTEM PROMPT (teach your AI about site control commands):
#   See the SAMPLE_SYSTEM_PROMPT variable below.
# =============================================================================

# This sample system prompt teaches an AI agent how to control the website.
# Copy and customize this when connecting to your own AI provider.
SYSTEM_PROMPT = """
You are an intelligent, warm, and knowledgeable concierge for this website.
You have deep knowledge of everything offered here — the spaces, experiences, pricing,
and details. You speak naturally and conversationally, like a real person who genuinely
cares about helping each visitor. Adapt your tone to match the visitor: be professional
yet approachable. Share specific details, make personalized suggestions, and anticipate
what the visitor might want to know next. Never give generic answers — always reference
the actual content, names, prices, and descriptions from the site data below.

RESPONSE FORMATTING — Your text responses are rendered with markdown support. ALWAYS format your responses for readability:
- Use **bold** for names, places, features, and key highlights
- Use bullet points (- ) when listing multiple items, features, or options
- Use ### or #### headings to separate sections in longer responses
- Use short paragraphs — break up walls of text
- Keep responses scannable — visitors should be able to quickly find what matters
- For short answers (1-2 sentences), plain text is fine — no need to over-format
- For anything listing 3+ items, ALWAYS use bullet points
- Example of good formatting:
  "Here are our top experiences:\n\n- **Wine Tasting** — Sample over 400 labels in our stone-vaulted cellar\n- **Private Chef Dinner** — Al fresco dining on the Sunset Terrace\n- **Cooking Class** — Learn Mediterranean recipes in the Chef's Kitchen"
- Example of BAD formatting (never do this):
  "We offer Wine Tasting where you can sample over 400 labels. We also have Private Chef Dinner on the Sunset Terrace. And Cooking Class in the Chef's Kitchen."

IMPORTANT: You can control what the user sees on the website by including
a JSON command block in your response. Always wrap commands in ```command``` blocks.

AVAILABLE COMMANDS:

1. Navigate to a specific gallery item (USE THIS WHENEVER a visitor asks about a specific item):
```command
{"action": "navigate", "target": "CARD_SLUG"}
```
Valid targets: use slugs from the gallery cards listed below.
EXAMPLES of when to navigate:
- "Tell me about the wine cellar" → reply 1-2 sentences + navigate to "wine-cellar"
- "Show me the pool" → reply 1 sentence + navigate to "infinity-pool"
- "What rooms do you have?" → navigate to the first room
- "I'm interested in dining" → navigate to "chef-kitchen"
You MUST include the navigate command — do NOT just describe the item in text.

2. Show a structured slide with information:
```command
{"action": "showSlide", "title": "TITLE", "subtitle": "SUBTITLE", "points": ["point1", "point2"]}
```

3. Generate a quick visual data card (for simple data displays):
```command
{"action": "generateVisual", "title": "TITLE", "subtitle": "optional subtitle", "columns": ["Col1", "Col2", "Col3"], "rows": [["Cell1", "Cell2", "Cell3"], ["Cell4", "Cell5", "Cell6"]], "footer": "optional footnote"}
```
The frontend renders this as a frosted-glass card automatically. You just provide the data.
- "title" (required), "subtitle" (optional), "columns" + "rows" for tables, "items" for simple lists, "footer" (optional)
Use this for quick, simple data. For anything more creative or complex, use generateHTML instead.

4. Generate fully custom HTML (FULL CREATIVE FREEDOM):
```command
{"action": "generateHTML", "title": "Short descriptive title", "html": "<div style='...'>YOUR COMPLETE HTML HERE</div>"}
```
This renders your HTML on a fullscreen canvas. You are a world-class web designer with COMPLETE creative freedom — create anything you can imagine in HTML + inline CSS.

SITE THEME — YOU MUST USE THESE EXACT VALUES in ALL generated HTML. Never use generic colors or fonts. Every element you create must match the site's look and feel:
{THEME_PLACEHOLDER}

CRITICAL: Always reference the theme values above. Use the accent color for highlights, the heading font for titles, the body font for text, and the glass effects for cards. If you ignore the theme, the output will look out of place on the site.

DESIGN SYSTEM — follow these rules for a cohesive, premium feel:

CONTAINERS & CARDS:
- Outer wrapper: max-width: 900px; margin: 0 auto; padding: 2.5rem; width: 100%;
- Frosted glass cards: background: rgba(255,255,255,0.03); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); border: 1px solid rgba(255,255,255,0.08); border-radius: 1rem; padding: 2rem;
- Elevated cards (featured): background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);
- Card hover feel: box-shadow: 0 8px 32px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.08);

TYPOGRAPHY:
- Page/section titles: font-family: {heading_font}; color: #fff; font-size: clamp(1.5rem, 3vw, 2.25rem); font-weight: 700;
- Subtitles/eyebrows: font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.2em; color: {accent};
- Body text: font-family: {body_font}; color: rgba(255,255,255,0.85); font-size: 0.95rem; line-height: 1.7;
- Muted/secondary: color: rgba(255,255,255,0.5); font-size: 0.85rem;
- Labels/captions: color: rgba(255,255,255,0.4); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.1em;

ACCENT COLOR USAGE:
- Decorative left borders: border-left: 3px solid {accent};
- Badges/tags: background: rgba(accent, 0.15); color: {accent}; padding: 0.25rem 0.75rem; border-radius: 9999px;
- Highlight numbers/prices: color: {accent}; font-weight: 600;
- Divider accents: thin lines using {accent} at low opacity
- Icons/bullet markers: small circles or dots in {accent}

LAYOUT PATTERNS:
- Two-column comparison: display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem;
- Three-column features: display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.25rem;
- Timeline/itinerary: single column with left border accent, time markers
- Table: border-collapse: collapse; alternating row backgrounds at rgba(255,255,255,0.02)
- Card grid: display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1.5rem;

DECORATIVE TOUCHES:
- Subtle gradient headers: linear-gradient(135deg, rgba(accent, 0.08), transparent)
- Section dividers: 1px solid rgba(255,255,255,0.06); margin: 2rem 0;
- Numbered steps: accent-colored numbers with frosted glass circle backgrounds
- Star ratings, check marks, progress bars — use {accent} color

RESPONSIVE: Always use max-width with percentage fallbacks. On small screens, grid columns should collapse to 1fr.

WHAT TO CREATE (examples — be creative!):
- Side-by-side comparison tables with pros/cons
- Day-by-day itineraries with time blocks
- Pricing breakdowns with highlighted best value
- Feature grids with icon-style headers
- Step-by-step booking guides
- FAQ accordions (styled, not interactive)
- Testimonial/review cards
- Photo gallery layouts with captions
- Multi-section landing pages
- Timeline visualizations
- Stat dashboards with big numbers
- Menu/catalog layouts

IMPORTANT: Your HTML must be completely self-contained — ALL styles inline. Do not use <style> tags or external stylesheets. The output renders inside a scrollable container on a dark background.

5. Submit a form with data collected in conversation:
```command
{"action": "submitForm", "slug": "FORM_SLUG", "fields": {"field_name": "value", "another_field": "value"}}
```
CRITICAL: When you say you will submit or finalize a booking/form, you MUST include the submitForm command block in that SAME message. Do NOT just say "I'll submit now" without the actual command — saying it without the command does nothing. The command block is what actually triggers the submission.

Use this when you have collected ALL required information from the visitor through conversation.
HOW TO COLLECT FORM DATA:
- When a visitor wants to book, inquire, get started, or fill out a form, check the AVAILABLE FORMS section for matching forms.
- Ask the visitor for each required field naturally in conversation, one or two at a time.
- IMPORTANT: After EACH reply where the visitor gives you field data, send a partialFormSave command to save what you have so far. This way if they leave mid-conversation, we still capture their info for follow-up.
- Once you have ALL required fields, confirm with the visitor, then use submitForm to finalize.
- Keep track of what the visitor has told you throughout the conversation.

Example conversation flow:
1. Visitor: "I'd like to book" → You: "I'd love to help! Could I get your name?"
2. Visitor: "John Smith" → You: "Thanks John! And your email?" + partialFormSave with {"name": "John Smith"}
3. Visitor: "john@email.com" → You: "Great! What service interests you?" + partialFormSave with {"name": "John Smith", "email": "john@email.com"}
4. Visitor: "The wine tasting" → You: "Perfect! Let me confirm: John Smith, john@email.com, wine tasting. Shall I submit?" + partialFormSave with all fields
5. Visitor: "Yes" → You: "Submitting your booking now!" + submitForm with ALL collected data in the fields object

WRONG (does nothing): "I'll submit your booking now! Just a moment."
RIGHT (actually submits): "Submitting your booking now!" followed by the submitForm command block with all field values.

SUBMISSION BEHAVIOR — CRITICAL:
- When the form is submitted successfully, the system automatically generates a unique confirmation number (like BK-20260228-A3X9K) and displays it to the visitor. You do NOT need to generate or mention a confirmation number yourself — the system handles this automatically after the submitForm command executes.
- When the user confirms and you include the submitForm command, your text in that response will NOT be shown to the visitor. The system shows a loading indicator while submitting, then displays the confirmation automatically. So do NOT write things like "Just a moment" or "Submitting now, please wait" — the visitor will never see that text. Keep your response text minimal when using submitForm.
- NEVER send a response that says "I'll submit that now" without the actual submitForm command block. Saying it without the command does nothing.

6. Save partial form data (auto-save during collection for lead recovery):
```command
{"action": "partialFormSave", "slug": "FORM_SLUG", "fields": {"field_name": "value"}}
```
Send this after EVERY message where the visitor provides form field data. Include ALL fields collected so far (not just the new one). This enables abandon capture — if the visitor leaves before completing the form, we still have their partial data for follow-up.

7. Scroll to a specific page section:
```command
{"action": "scrollToSection", "target": "SECTION_ID"}
```
Valid built-in section IDs: section-hero, section-highlights, section-experiences, section-pricing, section-testimonials, section-team, section-faq, section-blog
Custom sections use the format: section-custom-{id} (where {id} is the database ID shown in the custom section info below)
Use this when the visitor asks about testimonials, reviews, the team, FAQ, pricing, or any custom section to scroll them directly to it. For example:
- "Show me your reviews" → short reply + scrollToSection to section-testimonials
- "Who's on your team?" → short reply + scrollToSection to section-team
- "Do you have a FAQ?" → short reply + scrollToSection to section-faq

8. Display a message on the hero section:
```command
{"action": "heroMessage", "message": "YOUR MESSAGE HERE"}
```
Use ONLY for special welcome messages or dramatic announcements. Normal Q&A text
automatically appears on the hero section — you don't need this command for regular conversation.

IMPORTANT BEHAVIOR:
When the visitor asks a question from the chat bar (not from an expanded chat panel), your
text reply automatically appears on the hero section with a typing animation. This creates a
beautiful, immersive experience. Only gallery navigation opens the gallery view — everything
else stays on the landing page with your response displayed prominently.

RULES:
- **NAVIGATION IS YOUR PRIMARY TOOL** — When the visitor asks about, mentions, or shows interest in ANY specific gallery item (room, product, service, etc.), you MUST use the navigate command to take them there. This is the most important rule. A short 1-2 sentence reply + navigate command. Do NOT just describe an item in text — SHOW them by navigating.
- For general questions (pricing overview, broad info, recommendations across items), reply with text. It will appear on the hero.
- Keep text responses concise but natural (1-4 sentences). Be conversational, not robotic.
- Use showSlide for quick structured comparisons and bullet-point recommendations (3-6 points max).
- IMPORTANT: Keep plain text replies SHORT — 1 to 4 sentences maximum. If your answer needs more detail, create a generateHTML visual instead of writing a long text reply. The visitor sees short text on the landing page hero; anything longer should become a beautiful visual slide.
- "SHOW ME VISUALLY" RULE: When the visitor's message contains phrases like "show me visually", "visualize", "make it visual", "display it", or similar visual-request language, you MUST respond with a generateHTML command — NO EXCEPTIONS. Do NOT write a long markdown text reply. Create a beautifully designed HTML visual using the frosted glass design system. Even if the topic is simple (a process, a list, a comparison), wrap it in stunning generateHTML output. A plain text response to a "show me visually" request is ALWAYS wrong.
- Use generateHTML LIBERALLY — it's your most powerful tool. Use it for:
  * Any answer that would be more than 4 sentences
  * Comparisons ("compare X and Y", "what's the difference between")
  * Detailed information ("tell me everything about", "full details")
  * Lists of features, amenities, or options
  * Itineraries, schedules, timelines
  * Pricing breakdowns or rate comparisons
  * Recommendations with multiple options
  * Any request where a visual layout adds clarity or beauty
  * ANY response that contains tabular data, feature lists, or structured comparisons — even if the user did NOT explicitly ask for a visual. If the best way to present information is in a table or comparison layout, USE generateHTML automatically.
  You are a designer — make every generateHTML output stunning with the frosted glass design system.
- AUTOMATIC VISUAL RULE: If your answer would naturally include a table (markdown or otherwise), a comparison grid, a pricing breakdown, or a multi-item feature list, you MUST use generateHTML to render it beautifully. NEVER put raw markdown tables (|---|) in your plain text response — always route tables through generateHTML.
- Use generateVisual only for very simple quick data cards (2-3 rows of data).
- Only use heroMessage for special greetings or announcements, not for regular Q&A.
- Only include ONE command block per response. Make sure the JSON in your command block is valid — no trailing backslashes or line breaks inside the JSON string.
- Reference real names, prices, and details from the site data. Never make up information.
- If the visitor seems interested, proactively suggest related items or experiences they might enjoy.
- When a visitor wants to book, inquire, get started, contact, or shows intent to take action, start collecting their information for the appropriate form. Ask for 1-2 fields at a time in a natural conversational way. Once you have all required fields, use the submitForm command to submit. Always confirm what you collected before submitting.
- REMINDER: When you tell the visitor you are submitting their form, you MUST include the submitForm command block with ALL collected field values in that same message. Without the command block, nothing actually gets submitted.
"""


def parse_command_from_text(text):
    """
    Extract a command JSON block from the AI's response text.
    Returns (clean_text, command_dict) — the text with the command removed,
    and the parsed command (or None if no command was found).

    APPROACH: Find the JSON object containing "action" directly, regardless
    of how the AI wrapped it (fenced block, backtick-adjacent, bare, etc.).
    This is robust against all formatting variations the model might produce.
    """
    # Step 1: Look for a JSON object containing "action" in the text.
    # Find the first occurrence of {"action" and extract the full JSON object.
    action_pos = text.find('{"action"')
    if action_pos == -1:
        action_pos = text.find('{ "action"')
    if action_pos == -1:
        return text.strip(), None

    # Step 2: Extract the JSON by finding the matching closing brace.
    json_str = text[action_pos:]
    # Walk through the string counting braces to find the complete JSON object.
    depth = 0
    end_pos = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(json_str):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end_pos = i + 1
                break

    if end_pos == 0:
        return text.strip(), None

    raw_json = json_str[:end_pos].strip()
    # Clean up common formatting issues
    raw_json = raw_json.replace('\\\n', '').replace('\\ \n', '')

    try:
        cmd = json.loads(raw_json)
    except json.JSONDecodeError:
        return text.strip(), None

    # Step 3: Build the clean display text by removing the command + any
    # surrounding backtick markers (```command```, ```command\n...\n```, etc.)
    before = text[:action_pos]
    after = text[action_pos + end_pos:]

    # Strip backtick fencing that precedes the JSON
    before = re.sub(r'`{1,3}\s*command\s*`{0,3}\s*$', '', before, flags=re.IGNORECASE).strip()
    # Strip trailing backticks after the JSON
    after = re.sub(r'^\s*`{1,3}', '', after).strip()

    clean = (before + ' ' + after).strip()
    # Remove any leftover isolated backticks
    clean = re.sub(r'`{1,3}', '', clean).strip()

    return clean, cmd


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """
    POST /api/chat
    Unified streaming chat endpoint using Server-Sent Events (SSE).

    ALL messages use streaming so the user sees tokens appear live.
    After the full response is collected, the server parses it and sends:
      - {"type": "token", "content": "..."} for each token as it arrives
      - {"type": "text", "content": "..."} for the final clean reply text
      - {"type": "html", "content": "..."} if generateHTML was used
      - {"type": "command", "command": {...}} for any parsed command
      - {"type": "done"} when complete
      - {"type": "error", "content": "..."} on failure
    """
    data = request.get_json()
    message = data.get("message", "").strip()
    history = data.get("history", [])
    session_id = data.get("session_id", "")
    # visitor_id persists across page reloads (stored in localStorage on the frontend).
    # session_id is unique per page load — each refresh starts a new conversation.
    # Together they let the admin track both individual conversations and returning visitors.
    visitor_id = data.get("visitor_id", "")

    # Use database system prompt if available, otherwise fall back to hardcoded
    active_prompt = SYSTEM_PROMPT
    try:
        cs = query_db("SELECT system_prompt FROM chatbot_settings WHERE id = 1")
        if cs and cs.get("system_prompt", "").strip():
            active_prompt = cs["system_prompt"]
    except Exception:
        pass

    # ----- THEME INJECTION -----
    # Build the theme string from defaults + any admin overrides
    theme_colors = {
        "background": "#060b14",
        "section_dark": "#0a0f1a",
        "accent_gold": "#c9a96e",
        "text": "#e4e4e7",
        "heading_font": "Playfair Display, Georgia, serif",
        "body_font": "DM Sans, sans-serif",
        "glass_bg": "rgba(255, 255, 255, 0.03)",
        "glass_border": "rgba(255, 255, 255, 0.08)",
    }
    try:
        theme = query_db(
            "SELECT theme_bg, theme_accent, theme_text, theme_glass_border, theme_glass_bg, theme_font_serif, theme_font_sans FROM site_settings WHERE id = 1",
            fetchone=True
        )
        if theme:
            if theme.get("theme_accent"): theme_colors["accent_gold"] = theme["theme_accent"]
            if theme.get("theme_bg"): theme_colors["background"] = theme["theme_bg"]
            if theme.get("theme_text"): theme_colors["text"] = theme["theme_text"]
            if theme.get("theme_font_serif"): theme_colors["heading_font"] = theme["theme_font_serif"] + ", Georgia, serif"
            if theme.get("theme_font_sans"): theme_colors["body_font"] = theme["theme_font_sans"] + ", sans-serif"
            if theme.get("theme_glass_bg"): theme_colors["glass_bg"] = theme["theme_glass_bg"]
            if theme.get("theme_glass_border"): theme_colors["glass_border"] = theme["theme_glass_border"]
    except Exception:
        pass

    theme_block = (
        f"- Page background: {theme_colors['background']}\n"
        f"- Section backgrounds: {theme_colors['section_dark']} (alternate with page bg)\n"
        f"- Accent color: {theme_colors['accent_gold']} — use for highlights, badges, borders, emphasis, prices\n"
        f"- Primary text color: {theme_colors['text']}\n"
        f"- Heading font ({{heading_font}}): font-family: '{theme_colors['heading_font']}'\n"
        f"- Body font ({{body_font}}): font-family: '{theme_colors['body_font']}'\n"
        f"- Glass card background ({{glass_bg}}): {theme_colors['glass_bg']}\n"
        f"- Glass card border ({{glass_border}}): {theme_colors['glass_border']}\n"
        f"- Frosted glass effect: backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);\n"
        f"- When the design system above says {{accent}}, use: {theme_colors['accent_gold']}"
    )
    active_prompt = active_prompt.replace("{THEME_PLACEHOLDER}", theme_block)

    # =========================================================================
    # AI KNOWLEDGE BASE — Dynamic Content Injection
    # =========================================================================
    #
    # HOW IT WORKS:
    # Every time a visitor sends a chat message, the AI receives a system
    # prompt that includes ALL of the site's real content. This is what makes
    # the AI feel "alive" — it knows the actual business name, room names,
    # prices, experiences, and descriptions rather than giving generic answers.
    #
    # The content is pulled fresh from the database on each request, so any
    # changes made in the admin panel are immediately reflected in the AI's
    # knowledge without restarting the server.
    #
    # WHAT'S CURRENTLY INJECTED:
    #   1. SITE IDENTITY    — site name, subtitle, tagline, hero title/description
    #   2. GALLERY CARDS    — slug, title, subtitle, category, description, details, price
    #   3. EXPERIENCES      — name, description, duration, price
    #   4. PRICING          — label, price, description, features
    #
    # HOW TO ADD MORE KNOWLEDGE:
    # To teach the AI about a new type of content, follow this pattern:
    #
    #   Step 1: Query your database table
    #       data = query_db("SELECT column1, column2 FROM your_table ORDER BY sort_order ASC")
    #
    #   Step 2: Format the results as readable text lines
    #       lines = [f'  - {row["column1"]}: {row["column2"]}' for row in data]
    #
    #   Step 3: Append to the active prompt with a clear section header
    #       active_prompt += f"\n\nYOUR SECTION NAME:\n" + "\n".join(lines)
    #
    # EXAMPLES OF THINGS YOU COULD ADD:
    #   - FAQ entries:        query faq table, format as Q&A pairs
    #   - Team/staff bios:    query staff table, include name/role/bio
    #   - Location/hours:     query settings for address, phone, hours
    #   - Testimonials:       query reviews table, include name/quote/rating
    #   - Policies:           query policies table (cancellation, check-in, etc.)
    #   - Menu items:         query menu table with names, descriptions, prices
    #   - Blog/news posts:    query posts table for recent titles and summaries
    #
    # TIPS:
    #   - Keep each section clearly labeled (the AI uses headers to find info)
    #   - Only include fields the AI would actually reference in conversation
    #   - The more specific the data, the more natural the AI sounds
    #   - All injected content counts toward the AI's context window, so
    #     avoid dumping huge text blocks — summarize where possible
    #   - Wrap everything in try/except so a missing table won't break chat
    # =========================================================================

    try:
        # ----- 1. SITE IDENTITY -----
        # Gives the AI awareness of the business name, branding, and messaging
        settings = query_db("SELECT site_name, site_subtitle, hero_tagline, hero_title, hero_description FROM site_settings WHERE id = 1", fetchone=True)
        if settings:
            active_prompt += f"\n\nSITE IDENTITY:\n- Name: {settings.get('site_name', '')}\n- Subtitle: {settings.get('site_subtitle', '')}\n- Tagline: {settings.get('hero_tagline', '')}\n- Title: {settings.get('hero_title', '')}\n- Description: {settings.get('hero_description', '')}"

        # ----- 2. GALLERY CARDS -----
        # Each card represents a key item (room, product, service, etc.)
        # The slug is critical — the AI uses it for the navigate command
        cards = query_db("SELECT slug, title, subtitle, category, description, details, price FROM gallery_cards ORDER BY sort_order ASC")
        if cards:
            card_lines = []
            for c in cards:
                line = f'  - slug: "{c["slug"]}", title: "{c["title"]}"'
                if c.get("subtitle"): line += f', subtitle: "{c["subtitle"]}"'
                if c.get("category"): line += f', category: "{c["category"]}"'
                if c.get("description"): line += f', description: "{c["description"]}"'
                if c.get("details"): line += f', details: "{c["details"]}"'
                if c.get("price"): line += f', price: "{c["price"]}"'
                card_lines.append(line)
            active_prompt += f"\n\nGALLERY CARDS (use exact slug values for navigate targets):\n" + "\n".join(card_lines)

        # ----- 3. EXPERIENCES -----
        # Activities, services, or add-ons the business offers
        experiences = query_db("SELECT name, description, duration, price FROM experiences ORDER BY sort_order ASC")
        if experiences:
            exp_lines = [f'  - {e["name"]}: {e.get("description", "")} (duration: {e.get("duration", "N/A")}, price: {e.get("price", "N/A")})' for e in experiences]
            active_prompt += f"\n\nEXPERIENCES OFFERED:\n" + "\n".join(exp_lines)

        # ----- 4. PRICING -----
        # Seasonal tiers, packages, or rate information
        pricing = query_db("SELECT label, price, description, features FROM pricing_seasons ORDER BY sort_order ASC")
        if pricing:
            price_lines = []
            for p in pricing:
                line = f'  - {p["label"]}: {p.get("price", "N/A")}'
                if p.get("description"): line += f' — {p["description"]}'
                if p.get("features"): line += f' | Features: {p["features"]}'
                price_lines.append(line)
            active_prompt += f"\n\nPRICING:\n" + "\n".join(price_lines)

        # ----- 5. AVAILABLE FORMS -----
        # Lets the AI know which forms exist and what fields they have,
        # so it can collect information conversationally and submit
        forms = query_db("SELECT id, name, slug, description FROM custom_forms WHERE status = 'active' ORDER BY sort_order ASC")
        if forms:
            form_lines = []
            for frm in forms:
                fields = query_db(
                    "SELECT name, label, field_type, required, options, help_text FROM form_fields WHERE form_id = %s ORDER BY step, sort_order ASC",
                    (frm["id"],)
                )
                field_descs = []
                for fld in (fields or []):
                    desc = f'    - "{fld["name"]}" ({fld["field_type"]}): "{fld["label"]}"'
                    if fld.get("required"): desc += " [REQUIRED]"
                    if fld.get("options") and fld["options"]:
                        import json as _json
                        try:
                            opts = _json.loads(fld["options"]) if isinstance(fld["options"], str) else fld["options"]
                            if isinstance(opts, list) and opts:
                                desc += f' options: {opts}'
                        except Exception:
                            pass
                    if fld.get("help_text"): desc += f' — {fld["help_text"]}'
                    field_descs.append(desc)
                form_lines.append(
                    f'  Form: "{frm["name"]}" (slug: "{frm["slug"]}")\n'
                    f'  Description: {frm.get("description", "")}\n'
                    f'  Fields:\n' + "\n".join(field_descs)
                )
            active_prompt += f"\n\nAVAILABLE FORMS (you can collect this info in chat and submit):\n" + "\n\n".join(form_lines)

        # ----- 6. TESTIMONIALS / REVIEWS -----
        # Customer reviews with star ratings so the AI can reference real feedback
        testimonials = query_db("SELECT reviewer_name, reviewer_role, content, rating FROM testimonials ORDER BY sort_order ASC")
        if testimonials:
            test_lines = [f'  - {t["reviewer_name"]} ({t.get("reviewer_role", "")}): "{t["content"]}" — {t.get("rating", 5)}★' for t in testimonials]
            active_prompt += f"\n\nCUSTOMER TESTIMONIALS:\n" + "\n".join(test_lines)

        # ----- 7. TEAM / ABOUT -----
        # Staff bios so the AI can tell visitors about the team
        team = query_db("SELECT name, title, bio FROM team_members ORDER BY sort_order ASC")
        if team:
            team_lines = [f'  - {m["name"]} — {m.get("title", "")}: {m.get("bio", "")}' for m in team]
            active_prompt += f"\n\nOUR TEAM:\n" + "\n".join(team_lines)

        # ----- 8. FAQ -----
        # Common questions and answers the AI should know by heart
        faqs = query_db("SELECT question, answer FROM faqs ORDER BY sort_order ASC")
        if faqs:
            faq_lines = [f'  Q: {f["question"]}\n  A: {f["answer"]}' for f in faqs]
            active_prompt += f"\n\nFREQUENTLY ASKED QUESTIONS:\n" + "\n\n".join(faq_lines)

        # ----- 9. BLOG POSTS -----
        # Published blog post titles and excerpts so the AI can reference
        # them and suggest reading specific articles to visitors
        blog_posts = query_db(
            "SELECT title, slug, excerpt, category FROM blog_posts WHERE status = 'published' ORDER BY sort_order ASC, published_at DESC"
        )
        if blog_posts:
            blog_lines = [
                f'  - "{bp["title"]}" (slug: "{bp["slug"]}", category: {bp.get("category", "General")}): {bp.get("excerpt", "")}'
                for bp in blog_posts
            ]
            active_prompt += (
                f"\n\nBLOG POSTS (you can suggest visitors read these at /blog/<slug>):\n"
                + "\n".join(blog_lines)
            )

        # ----- 10. BUSINESS INFO -----
        # Contact details, hours, and address so the AI can share them
        biz = query_db("""
            SELECT business_phone, business_email, business_address, business_hours
            FROM site_settings WHERE id = 1
        """, fetchone=True)
        if biz:
            biz_lines = []
            if biz.get("business_phone"): biz_lines.append(f"  - Phone: {biz['business_phone']}")
            if biz.get("business_email"): biz_lines.append(f"  - Email: {biz['business_email']}")
            if biz.get("business_address"): biz_lines.append(f"  - Address: {biz['business_address']}")
            hours = biz.get("business_hours")
            if hours and isinstance(hours, list) and len(hours) > 0:
                hours_str = ", ".join([f'{h.get("day", "")}: {h.get("open", "")}–{h.get("close", "")}' for h in hours if h.get("day")])
                if hours_str:
                    biz_lines.append(f"  - Hours: {hours_str}")
            if biz_lines:
                active_prompt += f"\n\nBUSINESS CONTACT INFO:\n" + "\n".join(biz_lines)

        # ----- 11. CUSTOM SECTIONS -----
        # Content from admin-created custom sections so the AI knows about them.
        # Also includes the section ID so the AI can use scrollToSection.
        custom_sections = query_db("""
            SELECT ps.id as section_id, ps.slug, ps.title, ps.template,
                   csi.title as item_title, csi.subtitle as item_subtitle,
                   csi.content as item_content
            FROM page_sections ps
            JOIN custom_section_items csi ON csi.section_id = ps.id
            WHERE ps.enabled = true AND ps.section_type = 'custom'
            ORDER BY ps.sort_order, csi.sort_order
        """)
        if custom_sections:
            current_section = None
            current_section_id = None
            section_lines = []
            for row in custom_sections:
                if row["slug"] != current_section:
                    if current_section and section_lines:
                        active_prompt += f"\n\nCUSTOM SECTION — {current_section.upper().replace('-', ' ')} (scrollToSection target: section-custom-{current_section_id}):\n" + "\n".join(section_lines)
                    current_section = row["slug"]
                    current_section_id = row["section_id"]
                    section_lines = []
                line = f'  - {row["item_title"]}'
                if row.get("item_subtitle"): line += f' — {row["item_subtitle"]}'
                if row.get("item_content"): line += f': {row["item_content"]}'
                section_lines.append(line)
            if current_section and section_lines:
                active_prompt += f"\n\nCUSTOM SECTION — {current_section.upper().replace('-', ' ')} (scrollToSection target: section-custom-{current_section_id}):\n" + "\n".join(section_lines)

    except Exception:
        pass

    messages = [{"role": "system", "content": active_prompt}]
    for h in history[-20:]:
        role = "assistant" if h.get("role") == "agent" else "user"
        messages.append({"role": role, "content": h.get("content", "")})
    messages.append({"role": "user", "content": message})

    def generate():
        try:
            stream = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=4096,
                temperature=0.7,
                stream=True,
            )

            full_text = ""

            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    full_text += delta.content
                    yield f"data: {json.dumps({'type': 'token', 'content': delta.content})}\n\n"

            reply, cmd = parse_command_from_text(full_text)
            if reply:
                yield f"data: {json.dumps({'type': 'text', 'content': reply})}\n\n"
            if cmd:
                yield f"data: {json.dumps({'type': 'command', 'command': cmd})}\n\n"

            # Save chat messages to the database for history/analytics
            if session_id:
                try:
                    ua = request.headers.get("User-Agent", "")
                    device = "mobile" if any(m in ua.lower() for m in ["mobile", "android", "iphone"]) else "desktop"
                    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")

                    # Look up an existing conversation by session_id.
                    # Since session_id is unique per page load, this naturally
                    # groups messages from the same page session together while
                    # creating a new conversation after each refresh.
                    conv = query_db(
                        "SELECT id FROM chat_conversations WHERE session_id = %s ORDER BY id DESC LIMIT 1",
                        (session_id,), fetchone=True
                    )
                    if not conv:
                        # First message in this page session — create a new conversation.
                        # visitor_id is stored alongside to track returning visitors.
                        conv = execute_db(
                            "INSERT INTO chat_conversations (session_id, visitor_id, visitor_ip, device_type, user_agent) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                            (session_id, visitor_id, ip, device, ua[:500])
                        )
                    conv_id = conv["id"]
                    execute_db("UPDATE chat_conversations SET updated_at = NOW() WHERE id = %s RETURNING id", (conv_id,))
                    execute_db(
                        "INSERT INTO chat_messages (conversation_id, role, content) VALUES (%s, 'user', %s) RETURNING id",
                        (conv_id, message)
                    )
                    execute_db(
                        "INSERT INTO chat_messages (conversation_id, role, content, command_json) VALUES (%s, 'assistant', %s, %s) RETURNING id",
                        (conv_id, reply or full_text, json.dumps(cmd) if cmd else None)
                    )
                except Exception:
                    pass

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'content': 'Connection issue. Please try again.'})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


# =============================================================================
# ADMIN DASHBOARD — HTML pages (protected by login)
# =============================================================================

@app.route("/admin")
@admin_required
def admin_dashboard():
    """
    GET /admin
    Render the admin dashboard HTML page.
    Protected by password authentication.
    """
    return render_template("admin/dashboard.html")


# =============================================================================
# ADMIN API — CRUD endpoints (protected by login)
# =============================================================================

# --------------- Gallery Cards CRUD ---------------

@app.route("/admin/api/gallery-cards", methods=["GET"])
@admin_required
def admin_get_cards():
    """GET all gallery cards for the admin panel."""
    cards = query_db("SELECT * FROM gallery_cards ORDER BY sort_order ASC")
    return jsonify(cards or [])


@app.route("/admin/api/gallery-cards", methods=["POST"])
@admin_required
def admin_create_card():
    """
    POST /admin/api/gallery-cards
    Create a new gallery card.
    """
    data = request.get_json()
    card = execute_db(
        """INSERT INTO gallery_cards (slug, title, subtitle, image_url, category, description, details, price, sort_order)
           VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
           RETURNING *""",
        (
            data["slug"], data["title"], data["subtitle"],
            data["image_url"], data["category"], data["description"],
            json.dumps(data.get("details", [])),
            data.get("price"), data.get("sort_order", 0)
        )
    )
    return jsonify(card), 201


@app.route("/admin/api/gallery-cards/<int:card_id>", methods=["PUT"])
@admin_required
def admin_update_card(card_id):
    """PUT /admin/api/gallery-cards/<id> — Update a gallery card."""
    data = request.get_json()
    card = execute_db(
        """UPDATE gallery_cards SET
             slug = %s, title = %s, subtitle = %s, image_url = %s,
             category = %s, description = %s, details = %s::jsonb,
             price = %s, sort_order = %s, updated_at = NOW()
           WHERE id = %s RETURNING *""",
        (
            data["slug"], data["title"], data["subtitle"],
            data["image_url"], data["category"], data["description"],
            json.dumps(data.get("details", [])),
            data.get("price"), data.get("sort_order", 0),
            card_id
        )
    )
    if not card:
        return jsonify({"error": "Card not found"}), 404
    return jsonify(card)


@app.route("/admin/api/gallery-cards/<int:card_id>", methods=["DELETE"])
@admin_required
def admin_delete_card(card_id):
    """DELETE /admin/api/gallery-cards/<id> — Remove a gallery card."""
    count = execute_db("DELETE FROM gallery_cards WHERE id = %s", (card_id,))
    if count == 0:
        return jsonify({"error": "Card not found"}), 404
    return jsonify({"success": True})


# --------------- Experiences CRUD ---------------

@app.route("/admin/api/experiences", methods=["GET"])
@admin_required
def admin_get_experiences():
    """GET all experiences."""
    exps = query_db("SELECT * FROM experiences ORDER BY sort_order ASC")
    return jsonify(exps or [])


@app.route("/admin/api/experiences", methods=["POST"])
@admin_required
def admin_create_experience():
    """POST /admin/api/experiences — Create a new experience."""
    data = request.get_json()
    exp = execute_db(
        """INSERT INTO experiences (name, description, icon, sort_order)
           VALUES (%s, %s, %s, %s) RETURNING *""",
        (data["name"], data["description"], data.get("icon", "star"), data.get("sort_order", 0))
    )
    return jsonify(exp), 201


@app.route("/admin/api/experiences/<int:exp_id>", methods=["PUT"])
@admin_required
def admin_update_experience(exp_id):
    """PUT /admin/api/experiences/<id> — Update an experience."""
    data = request.get_json()
    exp = execute_db(
        """UPDATE experiences SET
             name = %s, description = %s, icon = %s,
             sort_order = %s, updated_at = NOW()
           WHERE id = %s RETURNING *""",
        (data["name"], data["description"], data.get("icon", "star"), data.get("sort_order", 0), exp_id)
    )
    if not exp:
        return jsonify({"error": "Experience not found"}), 404
    return jsonify(exp)


@app.route("/admin/api/experiences/<int:exp_id>", methods=["DELETE"])
@admin_required
def admin_delete_experience(exp_id):
    """DELETE /admin/api/experiences/<id> — Remove an experience."""
    count = execute_db("DELETE FROM experiences WHERE id = %s", (exp_id,))
    if count == 0:
        return jsonify({"error": "Experience not found"}), 404
    return jsonify({"success": True})


# --------------- Pricing CRUD ---------------

@app.route("/admin/api/pricing", methods=["GET"])
@admin_required
def admin_get_pricing():
    """GET all pricing seasons."""
    pricing = query_db("SELECT * FROM pricing_seasons ORDER BY sort_order ASC")
    return jsonify(pricing or [])


@app.route("/admin/api/pricing", methods=["POST"])
@admin_required
def admin_create_pricing():
    """POST /admin/api/pricing — Create a new pricing season."""
    data = request.get_json()
    p = execute_db(
        """INSERT INTO pricing_seasons (label, date_range, price_range, sort_order)
           VALUES (%s, %s, %s, %s) RETURNING *""",
        (data["label"], data["date_range"], data["price_range"], data.get("sort_order", 0))
    )
    return jsonify(p), 201


@app.route("/admin/api/pricing/<int:price_id>", methods=["PUT"])
@admin_required
def admin_update_pricing(price_id):
    """PUT /admin/api/pricing/<id> — Update a pricing season."""
    data = request.get_json()
    p = execute_db(
        """UPDATE pricing_seasons SET
             label = %s, date_range = %s, price_range = %s,
             sort_order = %s, updated_at = NOW()
           WHERE id = %s RETURNING *""",
        (data["label"], data["date_range"], data["price_range"], data.get("sort_order", 0), price_id)
    )
    if not p:
        return jsonify({"error": "Pricing not found"}), 404
    return jsonify(p)


@app.route("/admin/api/pricing/<int:price_id>", methods=["DELETE"])
@admin_required
def admin_delete_pricing(price_id):
    """DELETE /admin/api/pricing/<id> — Remove a pricing season."""
    count = execute_db("DELETE FROM pricing_seasons WHERE id = %s", (price_id,))
    if count == 0:
        return jsonify({"error": "Pricing not found"}), 404
    return jsonify({"success": True})


# =============================================================
# ADMIN CRUD — TESTIMONIALS
# =============================================================
# Manages client reviews / testimonials displayed on the public site.

@app.route("/admin/api/testimonials", methods=["GET"])
@admin_required
def admin_get_testimonials():
    """GET all testimonials for the admin panel."""
    items = query_db("SELECT * FROM testimonials ORDER BY sort_order ASC")
    return jsonify(items or [])


@app.route("/admin/api/testimonials", methods=["POST"])
@admin_required
def admin_create_testimonial():
    """POST /admin/api/testimonials — Create a new testimonial."""
    data = request.get_json()
    item = execute_db(
        """INSERT INTO testimonials (reviewer_name, reviewer_role, content, rating, image_url, sort_order)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (data.get("reviewer_name", ""), data.get("reviewer_role", ""),
         data.get("content", ""), data.get("rating", 5),
         data.get("image_url", ""), data.get("sort_order", 0))
    )
    return jsonify(item), 201


@app.route("/admin/api/testimonials/<int:item_id>", methods=["PUT"])
@admin_required
def admin_update_testimonial(item_id):
    """PUT /admin/api/testimonials/<id> — Update a testimonial."""
    data = request.get_json()
    item = execute_db(
        """UPDATE testimonials SET
             reviewer_name = %s, reviewer_role = %s, content = %s,
             rating = %s, image_url = %s, sort_order = %s
           WHERE id = %s RETURNING *""",
        (data.get("reviewer_name", ""), data.get("reviewer_role", ""),
         data.get("content", ""), data.get("rating", 5),
         data.get("image_url", ""), data.get("sort_order", 0), item_id)
    )
    if not item:
        return jsonify({"error": "Testimonial not found"}), 404
    return jsonify(item)


@app.route("/admin/api/testimonials/<int:item_id>", methods=["DELETE"])
@admin_required
def admin_delete_testimonial(item_id):
    """DELETE /admin/api/testimonials/<id> — Remove a testimonial."""
    count = execute_db("DELETE FROM testimonials WHERE id = %s", (item_id,))
    if count == 0:
        return jsonify({"error": "Testimonial not found"}), 404
    return jsonify({"success": True})


# =============================================================
# ADMIN CRUD — TEAM MEMBERS
# =============================================================
# Manages team/staff member cards displayed on the public site.

@app.route("/admin/api/team", methods=["GET"])
@admin_required
def admin_get_team():
    """GET all team members for the admin panel."""
    items = query_db("SELECT * FROM team_members ORDER BY sort_order ASC")
    return jsonify(items or [])


@app.route("/admin/api/team", methods=["POST"])
@admin_required
def admin_create_team_member():
    """POST /admin/api/team — Create a new team member."""
    data = request.get_json()
    item = execute_db(
        """INSERT INTO team_members (name, title, bio, image_url, sort_order)
           VALUES (%s, %s, %s, %s, %s) RETURNING *""",
        (data.get("name", ""), data.get("title", ""),
         data.get("bio", ""), data.get("image_url", ""),
         data.get("sort_order", 0))
    )
    return jsonify(item), 201


@app.route("/admin/api/team/<int:item_id>", methods=["PUT"])
@admin_required
def admin_update_team_member(item_id):
    """PUT /admin/api/team/<id> — Update a team member."""
    data = request.get_json()
    item = execute_db(
        """UPDATE team_members SET
             name = %s, title = %s, bio = %s,
             image_url = %s, sort_order = %s
           WHERE id = %s RETURNING *""",
        (data.get("name", ""), data.get("title", ""),
         data.get("bio", ""), data.get("image_url", ""),
         data.get("sort_order", 0), item_id)
    )
    if not item:
        return jsonify({"error": "Team member not found"}), 404
    return jsonify(item)


@app.route("/admin/api/team/<int:item_id>", methods=["DELETE"])
@admin_required
def admin_delete_team_member(item_id):
    """DELETE /admin/api/team/<id> — Remove a team member."""
    count = execute_db("DELETE FROM team_members WHERE id = %s", (item_id,))
    if count == 0:
        return jsonify({"error": "Team member not found"}), 404
    return jsonify({"success": True})


# =============================================================
# ADMIN CRUD — FAQ
# =============================================================
# Manages frequently asked questions displayed on the public site.

@app.route("/admin/api/faq", methods=["GET"])
@admin_required
def admin_get_faq():
    """GET all FAQ entries for the admin panel."""
    items = query_db("SELECT * FROM faqs ORDER BY sort_order ASC")
    return jsonify(items or [])


@app.route("/admin/api/faq", methods=["POST"])
@admin_required
def admin_create_faq():
    """POST /admin/api/faq — Create a new FAQ entry."""
    data = request.get_json()
    item = execute_db(
        """INSERT INTO faqs (question, answer, sort_order)
           VALUES (%s, %s, %s) RETURNING *""",
        (data.get("question", ""), data.get("answer", ""),
         data.get("sort_order", 0))
    )
    return jsonify(item), 201


@app.route("/admin/api/faq/<int:item_id>", methods=["PUT"])
@admin_required
def admin_update_faq(item_id):
    """PUT /admin/api/faq/<id> — Update a FAQ entry."""
    data = request.get_json()
    item = execute_db(
        """UPDATE faqs SET
             question = %s, answer = %s, sort_order = %s
           WHERE id = %s RETURNING *""",
        (data.get("question", ""), data.get("answer", ""),
         data.get("sort_order", 0), item_id)
    )
    if not item:
        return jsonify({"error": "FAQ not found"}), 404
    return jsonify(item)


@app.route("/admin/api/faq/<int:item_id>", methods=["DELETE"])
@admin_required
def admin_delete_faq(item_id):
    """DELETE /admin/api/faq/<id> — Remove a FAQ entry."""
    count = execute_db("DELETE FROM faqs WHERE id = %s", (item_id,))
    if count == 0:
        return jsonify({"error": "FAQ not found"}), 404
    return jsonify({"success": True})


# =============================================================
# ADMIN CRUD — BLOG POSTS
# =============================================================
# Manages blog posts with draft/published workflow.
# Admin can create, edit, delete, and publish/unpublish posts.
# Published posts appear on the public site and in the AI knowledge base.

@app.route("/admin/api/blog", methods=["GET"])
@admin_required
def admin_get_blog_posts():
    """
    GET /admin/api/blog
    Returns ALL blog posts (including drafts) for the admin panel,
    sorted by sort_order and then by created_at descending.
    """
    posts = query_db(
        "SELECT * FROM blog_posts ORDER BY sort_order ASC, created_at DESC"
    )
    return jsonify(posts or [])


@app.route("/admin/api/blog", methods=["POST"])
@admin_required
def admin_create_blog_post():
    """
    POST /admin/api/blog
    Create a new blog post. Auto-generates slug from title if not provided.
    Sets published_at to NOW() if status is 'published'.
    """
    data = request.get_json()

    # Auto-generate slug from title if not provided
    slug = data.get("slug", "").strip()
    if not slug:
        slug = re.sub(r'[^a-z0-9]+', '-', data.get("title", "untitled").lower()).strip('-')

    # Set published_at timestamp when publishing
    published_at = None
    if data.get("status") == "published":
        published_at = datetime.now()

    post = execute_db(
        """INSERT INTO blog_posts
             (slug, title, subtitle, excerpt, content, cover_image,
              author, category, tags, status, seo_title, seo_description,
              published_at, sort_order)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           RETURNING *""",
        (
            slug,
            data.get("title", ""),
            data.get("subtitle", ""),
            data.get("excerpt", ""),
            data.get("content", ""),
            data.get("cover_image", ""),
            data.get("author", ""),
            data.get("category", ""),
            data.get("tags", ""),
            data.get("status", "draft"),
            data.get("seo_title", ""),
            data.get("seo_description", ""),
            published_at,
            data.get("sort_order", 0)
        )
    )
    return jsonify(post), 201


@app.route("/admin/api/blog/<int:post_id>", methods=["PUT"])
@admin_required
def admin_update_blog_post(post_id):
    """
    PUT /admin/api/blog/<id>
    Update an existing blog post. If status changes to 'published'
    and published_at is not already set, it gets set to NOW().
    """
    data = request.get_json()

    # Check if this is a newly published post (needs published_at timestamp)
    existing = query_db(
        "SELECT status, published_at FROM blog_posts WHERE id = %s",
        (post_id,), fetchone=True
    )
    if not existing:
        return jsonify({"error": "Blog post not found"}), 404

    # Set published_at when first published, keep existing if re-saving
    published_at = existing.get("published_at")
    if data.get("status") == "published" and not published_at:
        published_at = datetime.now()

    post = execute_db(
        """UPDATE blog_posts SET
             slug = %s, title = %s, subtitle = %s, excerpt = %s,
             content = %s, cover_image = %s, author = %s, category = %s,
             tags = %s, status = %s, seo_title = %s, seo_description = %s,
             published_at = %s, sort_order = %s, updated_at = NOW()
           WHERE id = %s RETURNING *""",
        (
            data.get("slug", ""),
            data.get("title", ""),
            data.get("subtitle", ""),
            data.get("excerpt", ""),
            data.get("content", ""),
            data.get("cover_image", ""),
            data.get("author", ""),
            data.get("category", ""),
            data.get("tags", ""),
            data.get("status", "draft"),
            data.get("seo_title", ""),
            data.get("seo_description", ""),
            published_at,
            data.get("sort_order", 0),
            post_id
        )
    )
    if not post:
        return jsonify({"error": "Blog post not found"}), 404
    return jsonify(post)


@app.route("/admin/api/blog/<int:post_id>", methods=["DELETE"])
@admin_required
def admin_delete_blog_post(post_id):
    """
    DELETE /admin/api/blog/<id>
    Permanently remove a blog post from the database.
    """
    count = execute_db("DELETE FROM blog_posts WHERE id = %s", (post_id,))
    if count == 0:
        return jsonify({"error": "Blog post not found"}), 404
    return jsonify({"success": True})


# =============================================================
# ADMIN CRUD — PAGE SECTIONS (Layout + Custom Sections)
# =============================================================
# Manages the section registry — controls page layout order,
# section visibility, and custom section creation.

@app.route("/admin/api/page-sections", methods=["GET"])
@admin_required
def admin_get_page_sections():
    """GET all page sections (built-in + custom) for the admin panel."""
    sections = query_db("SELECT * FROM page_sections ORDER BY sort_order ASC")
    return jsonify(sections or [])


@app.route("/admin/api/page-sections", methods=["POST"])
@admin_required
def admin_create_page_section():
    """POST /admin/api/page-sections — Create a new custom section."""
    data = request.get_json()
    slug = data.get("slug", "").strip().lower()
    slug = re.sub(r'[^a-z0-9-]', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    if not slug:
        return jsonify({"error": "Slug is required"}), 400

    # Get the next sort_order (add to the end, before footer)
    max_order = query_db(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 as next_order FROM page_sections",
        fetchone=True
    )
    next_order = max_order["next_order"] if max_order else 0

    item = execute_db(
        """INSERT INTO page_sections (slug, title, section_type, template, sort_order, enabled, settings)
           VALUES (%s, %s, 'custom', %s, %s, %s, %s::jsonb) RETURNING *""",
        (slug, data.get("title", "New Section"),
         data.get("template", "cards_grid"), next_order,
         data.get("enabled", True), json.dumps(data.get("settings", {})))
    )
    return jsonify(item), 201


@app.route("/admin/api/page-sections/<int:section_id>", methods=["PUT"])
@admin_required
def admin_update_page_section(section_id):
    """PUT /admin/api/page-sections/<id> — Update a section's title, enabled, settings."""
    data = request.get_json()
    item = execute_db(
        """UPDATE page_sections SET
             title = %s, enabled = %s, settings = %s::jsonb
           WHERE id = %s RETURNING *""",
        (data.get("title", ""), data.get("enabled", True),
         json.dumps(data.get("settings", {})), section_id)
    )
    if not item:
        return jsonify({"error": "Section not found"}), 404
    return jsonify(item)


@app.route("/admin/api/page-sections/<int:section_id>", methods=["DELETE"])
@admin_required
def admin_delete_page_section(section_id):
    """DELETE /admin/api/page-sections/<id> — Delete a custom section (built-in protected)."""
    section = query_db("SELECT * FROM page_sections WHERE id = %s", (section_id,), fetchone=True)
    if not section:
        return jsonify({"error": "Section not found"}), 404
    if section.get("section_type") == "built_in":
        return jsonify({"error": "Cannot delete built-in sections"}), 400
    execute_db("DELETE FROM page_sections WHERE id = %s", (section_id,))
    return jsonify({"success": True})


@app.route("/admin/api/page-sections/<int:section_id>/toggle", methods=["PUT"])
@admin_required
def admin_toggle_page_section(section_id):
    """PUT /admin/api/page-sections/<id>/toggle — Quick toggle enabled/disabled."""
    data = request.get_json()
    enabled = data.get("enabled", True)
    item = execute_db(
        "UPDATE page_sections SET enabled = %s WHERE id = %s RETURNING *",
        (enabled, section_id)
    )
    if not item:
        return jsonify({"error": "Section not found"}), 404

    # Sync the old section_testimonials/team/faq/footer toggles in site_settings
    # so existing code that reads those columns stays in sync
    section = query_db("SELECT slug FROM page_sections WHERE id = %s", (section_id,), fetchone=True)
    if section:
        toggle_map = {
            "testimonials": "section_testimonials",
            "team": "section_team",
            "faq": "section_faq",
            "footer": "section_footer"
        }
        col = toggle_map.get(section["slug"])
        if col:
            execute_db(
                f"UPDATE site_settings SET {col} = %s WHERE id = 1",
                (enabled,)
            )

    return jsonify(item)


# =============================================================
# ADMIN CRUD — CUSTOM SECTION ITEMS
# =============================================================
# Manages the content items inside custom sections.

@app.route("/admin/api/custom-sections/<int:section_id>/items", methods=["GET"])
@admin_required
def admin_get_custom_items(section_id):
    """GET all items for a specific custom section."""
    items = query_db(
        "SELECT * FROM custom_section_items WHERE section_id = %s ORDER BY sort_order ASC",
        (section_id,)
    )
    return jsonify(items or [])


@app.route("/admin/api/custom-sections/<int:section_id>/items", methods=["POST"])
@admin_required
def admin_create_custom_item(section_id):
    """POST /admin/api/custom-sections/<section_id>/items — Add an item to a custom section."""
    data = request.get_json()
    item = execute_db(
        """INSERT INTO custom_section_items
           (section_id, title, subtitle, content, image_url, link_url, link_text, icon, sort_order, extra_data)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) RETURNING *""",
        (section_id, data.get("title", ""), data.get("subtitle", ""),
         data.get("content", ""), data.get("image_url", ""),
         data.get("link_url", ""), data.get("link_text", ""),
         data.get("icon", ""), data.get("sort_order", 0),
         json.dumps(data.get("extra_data", {})))
    )
    return jsonify(item), 201


@app.route("/admin/api/custom-sections/<int:section_id>/items/<int:item_id>", methods=["PUT"])
@admin_required
def admin_update_custom_item(section_id, item_id):
    """PUT /admin/api/custom-sections/<section_id>/items/<item_id> — Update an item."""
    data = request.get_json()
    item = execute_db(
        """UPDATE custom_section_items SET
             title = %s, subtitle = %s, content = %s, image_url = %s,
             link_url = %s, link_text = %s, icon = %s, sort_order = %s,
             extra_data = %s::jsonb
           WHERE id = %s AND section_id = %s RETURNING *""",
        (data.get("title", ""), data.get("subtitle", ""),
         data.get("content", ""), data.get("image_url", ""),
         data.get("link_url", ""), data.get("link_text", ""),
         data.get("icon", ""), data.get("sort_order", 0),
         json.dumps(data.get("extra_data", {})), item_id, section_id)
    )
    if not item:
        return jsonify({"error": "Item not found"}), 404
    return jsonify(item)


@app.route("/admin/api/custom-sections/<int:section_id>/items/<int:item_id>", methods=["DELETE"])
@admin_required
def admin_delete_custom_item(section_id, item_id):
    """DELETE /admin/api/custom-sections/<section_id>/items/<item_id> — Remove an item."""
    count = execute_db(
        "DELETE FROM custom_section_items WHERE id = %s AND section_id = %s",
        (item_id, section_id)
    )
    if count == 0:
        return jsonify({"error": "Item not found"}), 404
    return jsonify({"success": True})


# =============================================================
# ADMIN — SEO SETTINGS
# =============================================================
# Manages the SEO meta tags, Open Graph, Twitter Cards, and other
# search engine optimization settings stored on the site_settings table.

@app.route("/admin/api/seo", methods=["GET"])
@admin_required
def admin_get_seo():
    """
    GET /admin/api/seo
    Returns the current SEO settings for the admin panel.
    """
    settings = query_db("""
        SELECT seo_meta_title, seo_meta_description, seo_keywords,
               seo_og_image, seo_twitter_handle, seo_canonical_url, seo_robots
        FROM site_settings WHERE id = 1
    """, fetchone=True)
    return jsonify(settings or {})


@app.route("/admin/api/seo", methods=["PUT"])
@admin_required
def admin_update_seo():
    """
    PUT /admin/api/seo
    Update SEO settings (meta title, description, keywords, OG image,
    Twitter handle, canonical URL, robots directive).
    """
    data = request.get_json()
    result = execute_db(
        """UPDATE site_settings SET
             seo_meta_title = %s, seo_meta_description = %s,
             seo_keywords = %s, seo_og_image = %s,
             seo_twitter_handle = %s, seo_canonical_url = %s,
             seo_robots = %s, updated_at = NOW()
           WHERE id = 1 RETURNING
             seo_meta_title, seo_meta_description, seo_keywords,
             seo_og_image, seo_twitter_handle, seo_canonical_url, seo_robots""",
        (
            data.get("seo_meta_title", ""),
            data.get("seo_meta_description", ""),
            data.get("seo_keywords", ""),
            data.get("seo_og_image", ""),
            data.get("seo_twitter_handle", ""),
            data.get("seo_canonical_url", ""),
            data.get("seo_robots", "index, follow")
        )
    )
    return jsonify(result or {})


@app.route("/admin/api/seo/generate", methods=["POST"])
@admin_required
def admin_generate_seo():
    """
    POST /admin/api/seo/generate
    Uses OpenAI to analyze the site's actual content and generate
    optimized SEO suggestions for meta title, description, and keywords.
    The admin can review and apply these suggestions before saving.
    """
    # Gather site content to provide context for SEO generation
    settings = query_db("SELECT * FROM site_settings WHERE id = 1", fetchone=True)
    cards = query_db("SELECT title, subtitle, description FROM gallery_cards ORDER BY sort_order LIMIT 10")
    experiences = query_db("SELECT name, description FROM experiences ORDER BY sort_order LIMIT 10")

    site_name = settings.get("site_name", "My Site") if settings else "My Site"
    site_subtitle = settings.get("site_subtitle", "") if settings else ""
    hero_desc = settings.get("hero_description", "") if settings else ""

    # Build a content summary for the AI to analyze
    content_summary = f"Site name: {site_name}\n"
    if site_subtitle:
        content_summary += f"Tagline: {site_subtitle}\n"
    if hero_desc:
        content_summary += f"Main description: {hero_desc}\n"
    if cards:
        card_names = ", ".join([c["title"] for c in cards])
        content_summary += f"Featured items: {card_names}\n"
    if experiences:
        exp_names = ", ".join([e["name"] for e in experiences])
        content_summary += f"Services/experiences: {exp_names}\n"

    try:
        # Call OpenAI to generate SEO suggestions based on the site's actual content
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an SEO expert. Based on the website content provided, "
                        "generate optimized SEO metadata. Respond with ONLY a JSON object "
                        "(no markdown, no code fences) containing exactly these fields:\n"
                        '  "meta_title": (max 60 characters, compelling and keyword-rich),\n'
                        '  "meta_description": (max 160 characters, action-oriented summary),\n'
                        '  "keywords": (comma-separated, max 10 relevant keywords)\n'
                        "Make them compelling, search-engine friendly, and specific to the business."
                    )
                },
                {
                    "role": "user",
                    "content": f"Generate SEO metadata for this website:\n\n{content_summary}"
                }
            ],
            max_tokens=500,
            temperature=0.7,
        )

        result_text = response.choices[0].message.content.strip()
        # Remove markdown code fences if the AI wrapped the JSON
        result_text = re.sub(r'^```(?:json)?\s*', '', result_text)
        result_text = re.sub(r'\s*```$', '', result_text)

        seo_data = json.loads(result_text)
        return jsonify(seo_data)
    except Exception as e:
        return jsonify({"error": f"Failed to generate SEO suggestions: {str(e)}"}), 500


# =============================================================
# ADMIN — BUSINESS INFO + SOCIAL LINKS + SECTION VISIBILITY
# =============================================================
# These endpoints update columns on the single-row site_settings table
# rather than managing separate tables.

@app.route("/admin/api/business-info", methods=["GET"])
@admin_required
def admin_get_business_info():
    """GET business contact info for the admin panel."""
    info = query_db("""
        SELECT business_phone, business_email, business_address,
               business_hours, business_map_embed
        FROM site_settings WHERE id = 1
    """, fetchone=True)
    return jsonify(info or {})


@app.route("/admin/api/business-info", methods=["PUT"])
@admin_required
def admin_update_business_info():
    """PUT /admin/api/business-info — Update business contact info."""
    data = request.get_json()
    info = execute_db(
        """UPDATE site_settings SET
             business_phone = %s, business_email = %s,
             business_address = %s, business_hours = %s::jsonb,
             business_map_embed = %s, updated_at = NOW()
           WHERE id = 1 RETURNING
             business_phone, business_email, business_address,
             business_hours, business_map_embed""",
        (data.get("business_phone", ""), data.get("business_email", ""),
         data.get("business_address", ""),
         json.dumps(data.get("business_hours", [])),
         data.get("business_map_embed", ""))
    )
    return jsonify(info or {})


@app.route("/admin/api/social-links", methods=["GET"])
@admin_required
def admin_get_social_links():
    """GET social media links for the admin panel."""
    info = query_db("SELECT social_links FROM site_settings WHERE id = 1", fetchone=True)
    return jsonify(info.get("social_links", {}) if info else {})


@app.route("/admin/api/social-links", methods=["PUT"])
@admin_required
def admin_update_social_links():
    """PUT /admin/api/social-links — Update social media profile URLs."""
    data = request.get_json()
    execute_db(
        "UPDATE site_settings SET social_links = %s::jsonb, updated_at = NOW() WHERE id = 1",
        (json.dumps(data),)
    )
    return jsonify(data)


@app.route("/admin/api/section-visibility", methods=["GET"])
@admin_required
def admin_get_section_visibility():
    """GET section visibility toggles for the admin panel."""
    info = query_db("""
        SELECT section_testimonials, section_team, section_faq, section_footer
        FROM site_settings WHERE id = 1
    """, fetchone=True)
    return jsonify(info or {})


@app.route("/admin/api/section-visibility", methods=["PUT"])
@admin_required
def admin_update_section_visibility():
    """PUT /admin/api/section-visibility — Toggle sections on/off."""
    data = request.get_json()
    info = execute_db(
        """UPDATE site_settings SET
             section_testimonials = %s, section_team = %s,
             section_faq = %s, section_footer = %s,
             updated_at = NOW()
           WHERE id = 1 RETURNING
             section_testimonials, section_team, section_faq, section_footer""",
        (data.get("section_testimonials", False), data.get("section_team", False),
         data.get("section_faq", False), data.get("section_footer", True))
    )
    return jsonify(info or {})


# --------------- Site Settings CRUD ---------------

@app.route("/admin/api/site-settings", methods=["GET"])
@admin_required
def admin_get_settings():
    """GET the current site settings."""
    settings = query_db("SELECT * FROM site_settings WHERE id = 1", fetchone=True)
    return jsonify(settings or {})


@app.route("/admin/api/site-settings", methods=["PUT"])
@admin_required
def admin_update_settings():
    """PUT /admin/api/site-settings — Update site-wide settings."""
    data = request.get_json()
    settings = execute_db(
        """UPDATE site_settings SET
             site_name = %s, site_subtitle = %s, hero_tagline = %s,
             hero_title = %s, hero_description = %s, hero_image = %s,
             logo_initials = %s, updated_at = NOW()
           WHERE id = 1 RETURNING *""",
        (
            data["site_name"], data["site_subtitle"], data["hero_tagline"],
            data["hero_title"], data["hero_description"], data["hero_image"],
            data["logo_initials"]
        )
    )
    return jsonify(settings)


# --------------- Chatbot Settings CRUD ---------------

@app.route("/admin/api/chatbot-settings", methods=["GET"])
@admin_required
def admin_get_chatbot():
    """GET the current chatbot settings."""
    settings = query_db("SELECT * FROM chatbot_settings WHERE id = 1", fetchone=True)
    return jsonify(settings or {})


@app.route("/admin/api/chatbot-settings", methods=["PUT"])
@admin_required
def admin_update_chatbot():
    """
    PUT /admin/api/chatbot-settings
    Update the chatbot configuration including system_prompt.
    """
    data = request.get_json()
    settings = execute_db(
        """UPDATE chatbot_settings SET
             enabled = %s, mode = %s, agent_name = %s, agent_role = %s,
             agent_avatar = %s, greeting = %s, quick_prompts = %s::jsonb,
             api_endpoint = %s, embed_code = %s, system_prompt = %s,
             updated_at = NOW()
           WHERE id = 1 RETURNING *""",
        (
            data.get("enabled", False),
            data.get("mode", "builtin"),
            data.get("agent_name", "Marco"),
            data.get("agent_role", "Concierge"),
            data.get("agent_avatar", "M"),
            data.get("greeting", ""),
            json.dumps(data.get("quick_prompts", [])),
            data.get("api_endpoint", "/api/chat"),
            data.get("embed_code", ""),
            data.get("system_prompt", "")
        )
    )
    return jsonify(settings)


# --------------- Default System Prompt (public read for admin pre-fill) ------

@app.route("/admin/api/default-system-prompt", methods=["GET"])
@admin_required
def admin_get_default_prompt():
    """GET the hardcoded default system prompt so the admin can pre-fill."""
    return jsonify({"system_prompt": SYSTEM_PROMPT})


# --------------- Image Upload ---------------

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    """Serve uploaded images from the /uploads directory."""
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/admin/api/upload-image", methods=["POST"])
@admin_required
def admin_upload_image():
    """POST /admin/api/upload-image — Upload an image file, return its URL."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"File type .{ext} not allowed. Use jpg, png, gif, or webp."}), 400

    unique_name = f"{secrets.token_hex(8)}.{ext}"
    f.save(os.path.join(UPLOAD_FOLDER, unique_name))
    file_size = os.path.getsize(os.path.join(UPLOAD_FOLDER, unique_name))

    execute_db(
        "INSERT INTO uploaded_images (filename, original_name, file_size) VALUES (%s, %s, %s) RETURNING id",
        (unique_name, f.filename, file_size)
    )

    return jsonify({"url": f"/uploads/{unique_name}", "filename": unique_name})


# --------------- Drag-and-Drop Reorder ---------------

@app.route("/admin/api/reorder/<string:content_type>", methods=["PUT"])
@admin_required
def admin_reorder(content_type):
    """PUT /admin/api/reorder/<type> — Batch-update sort_order for a content type."""
    table_map = {
        "gallery-cards": "gallery_cards",
        "experiences": "experiences",
        "pricing": "pricing_seasons",
        "testimonials": "testimonials",
        "team": "team_members",
        "faq": "faqs",
        "page-sections": "page_sections",
        "custom-section-items": "custom_section_items",
        "blog-posts": "blog_posts",
        "page-views": "page_views"
    }
    table = table_map.get(content_type)
    if not table:
        return jsonify({"error": "Invalid content type"}), 400

    items = request.get_json()
    if not isinstance(items, list):
        return jsonify({"error": "Expected array of {id, sort_order}"}), 400

    # Tables that have an updated_at column get it refreshed on reorder
    tables_with_updated_at = {"gallery_cards", "experiences", "pricing_seasons"}

    conn = get_db()
    try:
        with conn.cursor() as cur:
            for item in items:
                if table in tables_with_updated_at:
                    cur.execute(
                        f"UPDATE {table} SET sort_order = %s, updated_at = NOW() WHERE id = %s",
                        (item["sort_order"], item["id"])
                    )
                else:
                    cur.execute(
                        f"UPDATE {table} SET sort_order = %s WHERE id = %s",
                        (item["sort_order"], item["id"])
                    )
    finally:
        conn.close()

    return jsonify({"success": True})


# --------------- Chat History & Analytics ---------------

@app.route("/admin/api/chat-history", methods=["GET"])
@admin_required
def admin_chat_history():
    """GET /admin/api/chat-history — List conversations with stats."""
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    offset = (page - 1) * per_page

    conversations = query_db("""
        SELECT c.*,
            c.visitor_id,
            (SELECT COUNT(*) FROM chat_messages WHERE conversation_id = c.id) as message_count,
            (SELECT content FROM chat_messages WHERE conversation_id = c.id AND role = 'user' ORDER BY id LIMIT 1) as first_message
        FROM chat_conversations c
        ORDER BY c.updated_at DESC
        LIMIT %s OFFSET %s
    """, (per_page, offset))

    # Chat analytics stats:
    # - total_conversations: one per page load (each refresh = new conversation)
    # - messages_today: all messages sent today across all conversations
    # - avg_messages: average messages per conversation
    # - unique_visitors: distinct visitor_ids (tracks returning visitors across sessions)
    stats = query_db("""
        SELECT
            (SELECT COUNT(*) FROM chat_conversations) as total_conversations,
            (SELECT COUNT(*) FROM chat_messages WHERE created_at >= CURRENT_DATE) as messages_today,
            (SELECT ROUND(AVG(cnt), 1) FROM (SELECT COUNT(*) as cnt FROM chat_messages GROUP BY conversation_id) sub) as avg_messages,
            (SELECT COUNT(DISTINCT visitor_id) FROM chat_conversations WHERE visitor_id != '' AND visitor_id IS NOT NULL) as unique_visitors
    """, fetchone=True)

    return jsonify({"conversations": conversations or [], "stats": stats or {}})


@app.route("/admin/api/chat-history/<int:conv_id>", methods=["GET"])
@admin_required
def admin_chat_detail(conv_id):
    """GET /admin/api/chat-history/<id> — Full conversation with messages."""
    conv = query_db("SELECT * FROM chat_conversations WHERE id = %s", (conv_id,), fetchone=True)
    if not conv:
        return jsonify({"error": "Conversation not found"}), 404
    messages = query_db(
        "SELECT * FROM chat_messages WHERE conversation_id = %s ORDER BY created_at", (conv_id,)
    )
    return jsonify({"conversation": conv, "messages": messages or []})


# --------------- Theme / Color Editor ---------------

@app.route("/api/theme", methods=["GET"])
def api_get_theme():
    """GET /api/theme — Public endpoint returning theme customization values."""
    settings = query_db("""
        SELECT theme_bg, theme_section1, theme_section2, theme_accent,
               theme_text, theme_glass_border, theme_glass_bg,
               theme_font_serif, theme_font_sans
        FROM site_settings WHERE id = 1
    """, fetchone=True)
    return jsonify(settings or {})


@app.route("/admin/api/theme", methods=["GET"])
@admin_required
def admin_get_theme():
    """GET /admin/api/theme — Admin read of theme settings."""
    settings = query_db("""
        SELECT theme_bg, theme_section1, theme_section2, theme_accent,
               theme_text, theme_glass_border, theme_glass_bg,
               theme_font_serif, theme_font_sans
        FROM site_settings WHERE id = 1
    """, fetchone=True)
    return jsonify(settings or {})


@app.route("/admin/api/theme", methods=["PUT"])
@admin_required
def admin_update_theme():
    """PUT /admin/api/theme — Save theme color/font overrides."""
    data = request.get_json()
    result = execute_db(
        """UPDATE site_settings SET
             theme_bg = %s, theme_section1 = %s, theme_section2 = %s,
             theme_accent = %s, theme_text = %s, theme_glass_border = %s,
             theme_glass_bg = %s, theme_font_serif = %s, theme_font_sans = %s,
             updated_at = NOW()
           WHERE id = 1 RETURNING *""",
        (
            data.get("theme_bg", ""),
            data.get("theme_section1", ""),
            data.get("theme_section2", ""),
            data.get("theme_accent", ""),
            data.get("theme_text", ""),
            data.get("theme_glass_border", ""),
            data.get("theme_glass_bg", ""),
            data.get("theme_font_serif", ""),
            data.get("theme_font_sans", "")
        )
    )
    return jsonify(result)


# =============================================================================
# GENERATED PAGES — Save & manage AI-created HTML pages
# =============================================================================

@app.route("/api/generated-pages", methods=["POST"])
def api_save_generated_page():
    """POST /api/generated-pages — Save an AI-generated HTML page (called from frontend)."""
    data = request.get_json()
    html = data.get("html", "").strip()
    title = data.get("title", "Untitled Page").strip()
    prompt = data.get("prompt", "").strip()

    if not html:
        return jsonify({"error": "No HTML content provided"}), 400

    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    slug = slug[:180] + '-' + str(int(__import__('time').time()))

    result = execute_db(
        """INSERT INTO generated_pages (title, html, prompt, slug, status)
           VALUES (%s, %s, %s, %s, 'draft') RETURNING id""",
        (title, html, prompt, slug)
    )
    page_id = result['id'] if isinstance(result, dict) else result
    return jsonify({"success": True, "id": page_id, "slug": slug})


@app.route("/admin/api/generated-pages", methods=["GET"])
@admin_required
def admin_list_generated_pages():
    """GET /admin/api/generated-pages — List all saved AI-generated pages."""
    pages = query_db(
        "SELECT id, title, slug, status, prompt, created_at, updated_at FROM generated_pages ORDER BY created_at DESC"
    )
    return jsonify(pages or [])


@app.route("/admin/api/generated-pages/<int:page_id>", methods=["GET"])
@admin_required
def admin_get_generated_page(page_id):
    """GET /admin/api/generated-pages/<id> — Get a single page with full HTML."""
    page = query_db("SELECT * FROM generated_pages WHERE id = %s", (page_id,), fetchone=True)
    if not page:
        return jsonify({"error": "Page not found"}), 404
    return jsonify(page)


@app.route("/admin/api/generated-pages/<int:page_id>", methods=["PUT"])
@admin_required
def admin_update_generated_page(page_id):
    """PUT /admin/api/generated-pages/<id> — Update page title, status, or HTML."""
    data = request.get_json()
    fields, values = [], []
    for key in ['title', 'html']:
        if key in data:
            fields.append(f"{key} = %s")
            values.append(data[key])
    if 'status' in data and data['status'] in ('draft', 'published'):
        fields.append("status = %s")
        values.append(data['status'])
    if not fields:
        return jsonify({"error": "No fields to update"}), 400
    fields.append("updated_at = NOW()")
    values.append(page_id)
    execute_db(f"UPDATE generated_pages SET {', '.join(fields)} WHERE id = %s", tuple(values))
    return jsonify({"success": True})


@app.route("/admin/api/generated-pages/<int:page_id>", methods=["DELETE"])
@admin_required
def admin_delete_generated_page(page_id):
    """DELETE /admin/api/generated-pages/<id> — Delete a saved page."""
    execute_db("DELETE FROM generated_pages WHERE id = %s", (page_id,))
    return jsonify({"success": True})


@app.route("/page/<slug>")
def public_generated_page(slug):
    """GET /page/<slug> — Render a published AI-generated page."""
    page = query_db("SELECT * FROM generated_pages WHERE slug = %s AND status = 'published'", (slug,), fetchone=True)
    if not page:
        return "Page not found", 404
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page['title'].replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')}</title>
    <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=DM+Sans:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>
        body {{ margin: 0; padding: 0; background: #060b14; color: #e4e4e7; font-family: 'DM Sans', sans-serif; min-height: 100vh; display: flex; align-items: center; justify-content: center; }}
    </style>
</head>
<body>
    {page['html']}
</body>
</html>"""


# =============================================================================
# DYNAMIC FORM BUILDER — Admin API Routes
# =============================================================================

@app.route("/admin/api/forms", methods=["GET"])
@admin_required
def admin_list_forms():
    """GET /admin/api/forms — List all forms with field/submission counts."""
    forms = query_db("""
        SELECT f.*,
            (SELECT COUNT(*) FROM form_fields WHERE form_id = f.id) AS field_count,
            (SELECT COUNT(*) FROM form_submissions WHERE form_id = f.id) AS submission_count
        FROM custom_forms f ORDER BY f.sort_order, f.created_at
    """)
    return jsonify(forms or [])


@app.route("/admin/api/forms", methods=["POST"])
@admin_required
def admin_create_form():
    """POST /admin/api/forms — Create a new form."""
    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"error": "Form name is required"}), 400
    slug = data.get("slug") or data["name"].lower().replace(" ", "-").replace("'", "")
    slug = re.sub(r'[^a-z0-9\-]', '', slug)
    existing = query_db("SELECT id FROM custom_forms WHERE slug = %s", (slug,), fetchone=True)
    if existing:
        return jsonify({"error": "A form with this slug already exists"}), 400
    result = execute_db(
        """INSERT INTO custom_forms (name, slug, description, status, submit_button_text, success_message, sort_order)
           VALUES (%s, %s, %s, %s, %s, %s, COALESCE((SELECT MAX(sort_order)+1 FROM custom_forms), 0))
           RETURNING *""",
        (
            data["name"],
            slug,
            data.get("description", ""),
            data.get("status", "active"),
            data.get("submit_button_text", "Submit"),
            data.get("success_message", "Thank you! Your submission has been received.")
        )
    )
    return jsonify(result), 201


@app.route("/admin/api/forms/<int:form_id>", methods=["GET"])
@admin_required
def admin_get_form(form_id):
    """GET /admin/api/forms/<id> — Get a single form with all its fields."""
    form = query_db("SELECT * FROM custom_forms WHERE id = %s", (form_id,), fetchone=True)
    if not form:
        return jsonify({"error": "Form not found"}), 404
    fields = query_db("SELECT * FROM form_fields WHERE form_id = %s ORDER BY sort_order", (form_id,))
    form["fields"] = fields or []
    sub_count = query_db("SELECT COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s", (form_id,), fetchone=True)
    form["submission_count"] = sub_count["cnt"] if sub_count else 0
    return jsonify(form)


@app.route("/admin/api/forms/<int:form_id>", methods=["PUT"])
@admin_required
def admin_update_form(form_id):
    """PUT /admin/api/forms/<id> — Update form settings."""
    data = request.get_json()
    result = execute_db(
        """UPDATE custom_forms SET
             name = %s, description = %s, status = %s,
             submit_button_text = %s, success_message = %s, updated_at = NOW()
           WHERE id = %s RETURNING *""",
        (
            data.get("name", ""),
            data.get("description", ""),
            data.get("status", "active"),
            data.get("submit_button_text", "Submit"),
            data.get("success_message", "Thank you! Your submission has been received."),
            form_id
        )
    )
    if not result:
        return jsonify({"error": "Form not found"}), 404
    return jsonify(result)


@app.route("/admin/api/forms/<int:form_id>", methods=["DELETE"])
@admin_required
def admin_delete_form(form_id):
    """DELETE /admin/api/forms/<id> — Delete a form (cascades fields and submissions)."""
    sub_count = query_db("SELECT COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s", (form_id,), fetchone=True)
    if sub_count and sub_count["cnt"] > 0:
        confirm = request.args.get("confirm") == "true"
        if not confirm:
            return jsonify({"error": f"Form has {sub_count['cnt']} submission(s). Add ?confirm=true to delete anyway."}), 400
    result = execute_db("DELETE FROM custom_forms WHERE id = %s RETURNING id", (form_id,))
    if not result:
        return jsonify({"error": "Form not found"}), 404
    return jsonify({"success": True})


@app.route("/admin/api/forms/<int:form_id>/fields", methods=["POST"])
@admin_required
def admin_add_field(form_id):
    """POST /admin/api/forms/<id>/fields — Add a field to a form."""
    data = request.get_json()
    if not data or not data.get("label"):
        return jsonify({"error": "Field label is required"}), 400
    name = data.get("name") or data["label"].lower().replace(" ", "_")
    name = re.sub(r'[^a-z0-9_]', '', name)
    options_val = json.dumps(data["options"]) if data.get("options") else None
    step_val = max(1, int(data.get("step", 1))) if data.get("step") else 1
    result = execute_db(
        """INSERT INTO form_fields (form_id, field_type, label, name, placeholder, required, options, default_value, sort_order, width, validation_regex, help_text, step)
           VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, COALESCE((SELECT MAX(sort_order)+1 FROM form_fields WHERE form_id = %s), 0), %s, %s, %s, %s)
           RETURNING *""",
        (
            form_id,
            data.get("field_type", "text"),
            data["label"],
            name,
            data.get("placeholder", ""),
            data.get("required", False),
            options_val,
            data.get("default_value", ""),
            form_id,
            data.get("width", "full"),
            data.get("validation_regex", ""),
            data.get("help_text", ""),
            step_val
        )
    )
    return jsonify(result), 201


@app.route("/admin/api/forms/<int:form_id>/fields/<int:field_id>", methods=["PUT"])
@admin_required
def admin_update_field(form_id, field_id):
    """PUT /admin/api/forms/<id>/fields/<field_id> — Update a field."""
    data = request.get_json()
    options_val = json.dumps(data["options"]) if data.get("options") else None
    step_val = max(1, int(data.get("step", 1))) if data.get("step") else 1
    result = execute_db(
        """UPDATE form_fields SET
             field_type = %s, label = %s, name = %s, placeholder = %s,
             required = %s, options = %s::jsonb, default_value = %s,
             width = %s, validation_regex = %s, help_text = %s, step = %s
           WHERE id = %s AND form_id = %s RETURNING *""",
        (
            data.get("field_type", "text"),
            data.get("label", ""),
            data.get("name", ""),
            data.get("placeholder", ""),
            data.get("required", False),
            options_val,
            data.get("default_value", ""),
            data.get("width", "full"),
            data.get("validation_regex", ""),
            data.get("help_text", ""),
            step_val,
            field_id,
            form_id
        )
    )
    if not result:
        return jsonify({"error": "Field not found"}), 404
    return jsonify(result)


@app.route("/admin/api/forms/<int:form_id>/fields/<int:field_id>", methods=["DELETE"])
@admin_required
def admin_delete_field(form_id, field_id):
    """DELETE /admin/api/forms/<id>/fields/<field_id> — Remove a field."""
    result = execute_db("DELETE FROM form_fields WHERE id = %s AND form_id = %s RETURNING id", (field_id, form_id))
    if not result:
        return jsonify({"error": "Field not found"}), 404
    return jsonify({"success": True})


@app.route("/admin/api/forms/<int:form_id>/fields/reorder", methods=["PUT"])
@admin_required
def admin_reorder_fields(form_id):
    """PUT /admin/api/forms/<id>/fields/reorder — Batch reorder fields."""
    data = request.get_json()
    order = data.get("order", [])
    for item in order:
        execute_db(
            "UPDATE form_fields SET sort_order = %s WHERE id = %s AND form_id = %s",
            (item["sort_order"], item["id"], form_id)
        )
    return jsonify({"success": True})


# =============================================================================
# DYNAMIC FORM BUILDER — Submissions & Analytics
# =============================================================================

@app.route("/admin/api/forms/<int:form_id>/submissions", methods=["GET"])
@admin_required
def admin_form_submissions(form_id):
    """GET /admin/api/forms/<id>/submissions — List submissions with all fields."""
    submissions = query_db(
        "SELECT * FROM form_submissions WHERE form_id = %s ORDER BY submitted_at DESC",
        (form_id,)
    )
    fields = query_db(
        "SELECT id, label, name, field_type FROM form_fields WHERE form_id = %s ORDER BY sort_order",
        (form_id,)
    )
    return jsonify({"submissions": submissions or [], "fields": fields or []})


@app.route("/admin/api/submissions/<int:sub_id>/status", methods=["PUT"])
@admin_required
def admin_update_submission_status(sub_id):
    """PUT /admin/api/submissions/<id>/status — Update submission status."""
    data = request.get_json()
    result = execute_db(
        "UPDATE form_submissions SET status = %s WHERE id = %s RETURNING id, status",
        (data.get("status", "new"), sub_id)
    )
    if not result:
        return jsonify({"error": "Submission not found"}), 404
    return jsonify(result)


@app.route("/admin/api/submissions/<int:sub_id>", methods=["DELETE"])
@admin_required
def admin_delete_submission(sub_id):
    """DELETE /admin/api/submissions/<id> — Delete a submission."""
    result = execute_db("DELETE FROM form_submissions WHERE id = %s RETURNING id", (sub_id,))
    if not result:
        return jsonify({"error": "Submission not found"}), 404
    return jsonify({"success": True})


@app.route("/admin/api/forms/<int:form_id>/analytics", methods=["GET"])
@admin_required
def admin_form_analytics(form_id):
    """GET /admin/api/forms/<id>/analytics — Marketing analytics for a form."""
    total = query_db("SELECT COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s", (form_id,), fetchone=True)
    today = query_db(
        "SELECT COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s AND submitted_at::date = CURRENT_DATE",
        (form_id,), fetchone=True
    )
    by_status = query_db(
        "SELECT status, COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s GROUP BY status ORDER BY cnt DESC",
        (form_id,)
    )
    by_device = query_db(
        "SELECT device_type, COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s GROUP BY device_type ORDER BY cnt DESC",
        (form_id,)
    )
    by_utm = query_db(
        "SELECT utm_source, COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s AND utm_source != '' GROUP BY utm_source ORDER BY cnt DESC LIMIT 10",
        (form_id,)
    )
    by_browser = query_db(
        "SELECT browser, COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s AND browser != '' GROUP BY browser ORDER BY cnt DESC LIMIT 10",
        (form_id,)
    )
    by_os = query_db(
        "SELECT os, COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s AND os != '' GROUP BY os ORDER BY cnt DESC LIMIT 10",
        (form_id,)
    )
    top_referrers = query_db(
        "SELECT referrer_url, COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s AND referrer_url != '' GROUP BY referrer_url ORDER BY cnt DESC LIMIT 10",
        (form_id,)
    )
    by_language = query_db(
        "SELECT language, COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s AND language != '' GROUP BY language ORDER BY cnt DESC LIMIT 10",
        (form_id,)
    )
    return jsonify({
        "total": total["cnt"] if total else 0,
        "today": today["cnt"] if today else 0,
        "by_status": by_status or [],
        "by_device": by_device or [],
        "by_utm_source": by_utm or [],
        "by_browser": by_browser or [],
        "by_os": by_os or [],
        "top_referrers": top_referrers or [],
        "by_language": by_language or []
    })


# =============================================================================
# DYNAMIC FORM BUILDER — Public API
# =============================================================================

@app.route("/api/forms/<slug>", methods=["GET"])
def api_get_form(slug):
    """GET /api/forms/<slug> — Public endpoint returning form config for rendering."""
    form = query_db(
        "SELECT id, name, slug, description, submit_button_text, success_message FROM custom_forms WHERE slug = %s AND status = 'active'",
        (slug,), fetchone=True
    )
    if not form:
        return jsonify({"error": "Form not found"}), 404
    fields = query_db(
        "SELECT id, field_type, label, name, placeholder, required, options, default_value, sort_order, width, help_text, step FROM form_fields WHERE form_id = %s ORDER BY sort_order",
        (form["id"],)
    )
    form["fields"] = fields or []
    return jsonify(form)


def _parse_ua(ua_string):
    """Extract browser and OS from a User-Agent string."""
    ua_lower = ua_string.lower()
    browser = ""
    if "firefox" in ua_lower:
        browser = "Firefox"
    elif "edg" in ua_lower:
        browser = "Edge"
    elif "chrome" in ua_lower:
        browser = "Chrome"
    elif "safari" in ua_lower:
        browser = "Safari"
    elif "opera" in ua_lower or "opr" in ua_lower:
        browser = "Opera"
    os_name = ""
    if "windows" in ua_lower:
        os_name = "Windows"
    elif "mac os" in ua_lower or "macintosh" in ua_lower:
        os_name = "macOS"
    elif "linux" in ua_lower:
        os_name = "Linux"
    elif "android" in ua_lower:
        os_name = "Android"
    elif "iphone" in ua_lower or "ipad" in ua_lower:
        os_name = "iOS"
    device = "mobile" if any(m in ua_lower for m in ["mobile", "android", "iphone"]) else "desktop"
    return browser, os_name, device


@app.route("/api/forms/<slug>/partial", methods=["POST"])
def api_partial_save(slug):
    """POST /api/forms/<slug>/partial — Auto-save partial form data for abandon recovery."""
    form = query_db(
        "SELECT id FROM custom_forms WHERE slug = %s AND status = 'active'",
        (slug,), fetchone=True
    )
    if not form:
        return jsonify({"error": "Form not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    session_id = data.get("session_id", "")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    form_data = data.get("fields", {})
    ua_string = request.headers.get("User-Agent", "")
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    browser, os_name, device = _parse_ua(ua_string)

    existing = query_db(
        "SELECT id, status FROM form_submissions WHERE form_id = %s AND session_id = %s ORDER BY submitted_at DESC LIMIT 1",
        (form["id"], session_id), fetchone=True
    )

    if existing and existing["status"] == "partial":
        execute_db(
            "UPDATE form_submissions SET submission_data = %s::jsonb, updated_at = NOW() WHERE id = %s",
            (json.dumps(form_data), existing["id"])
        )
        return jsonify({"success": True, "id": existing["id"], "action": "updated"})
    elif existing and existing["status"] != "partial":
        return jsonify({"success": True, "id": existing["id"], "action": "already_submitted"})
    else:
        result = execute_db(
            """INSERT INTO form_submissions
                (form_id, submission_data, status, device_type, user_agent,
                 referrer_url, utm_source, utm_medium, utm_campaign, utm_term, utm_content,
                 page_url, ip_address, browser, os, screen_resolution, language, session_id)
               VALUES (%s, %s::jsonb, 'partial', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                form["id"],
                json.dumps(form_data),
                device,
                ua_string[:500],
                data.get("referrer", ""),
                data.get("utm_source", ""),
                data.get("utm_medium", ""),
                data.get("utm_campaign", ""),
                data.get("utm_term", ""),
                data.get("utm_content", ""),
                data.get("page_url", ""),
                ip,
                browser,
                os_name,
                data.get("screen_resolution", ""),
                data.get("language", ""),
                session_id
            )
        )
        return jsonify({"success": True, "id": result["id"] if result else None, "action": "created"}), 201


@app.route("/api/forms/<slug>/submit", methods=["POST"])
def api_submit_form(slug):
    """POST /api/forms/<slug>/submit — Accept a dynamic form submission."""
    form = query_db(
        "SELECT id, name FROM custom_forms WHERE slug = %s AND status = 'active'",
        (slug,), fetchone=True
    )
    if not form:
        return jsonify({"error": "Form not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    fields = query_db(
        "SELECT name, required, label FROM form_fields WHERE form_id = %s",
        (form["id"],)
    )
    form_data = data.get("fields", {})
    for f in (fields or []):
        if f["required"] and not form_data.get(f["name"]):
            return jsonify({"error": f"{f['label']} is required"}), 400

    ua_string = request.headers.get("User-Agent", "")
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    browser, os_name, device = _parse_ua(ua_string)

    session_id = data.get("session_id", "")
    existing = None
    if session_id:
        existing = query_db(
            "SELECT id FROM form_submissions WHERE form_id = %s AND session_id = %s AND status = 'partial' ORDER BY submitted_at DESC LIMIT 1",
            (form["id"], session_id), fetchone=True
        )

    import random, string
    from datetime import datetime as _dt
    date_part = _dt.now().strftime("%Y%m%d")
    rand_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    conf_number = f"BK-{date_part}-{rand_part}"

    if existing:
        result = execute_db(
            """UPDATE form_submissions SET
                 submission_data = %s::jsonb, status = 'new', updated_at = NOW(),
                 submitted_at = NOW(), confirmation_number = %s, device_type = %s, user_agent = %s,
                 referrer_url = %s, utm_source = %s, utm_medium = %s,
                 utm_campaign = %s, utm_term = %s, utm_content = %s,
                 page_url = %s, ip_address = %s, browser = %s, os = %s,
                 screen_resolution = %s, language = %s
               WHERE id = %s RETURNING id, confirmation_number""",
            (
                json.dumps(form_data),
                conf_number,
                device, ua_string[:500],
                data.get("referrer", ""), data.get("utm_source", ""),
                data.get("utm_medium", ""), data.get("utm_campaign", ""),
                data.get("utm_term", ""), data.get("utm_content", ""),
                data.get("page_url", ""), ip, browser, os_name,
                data.get("screen_resolution", ""), data.get("language", ""),
                existing["id"]
            )
        )
    else:
        result = execute_db(
            """INSERT INTO form_submissions
                (form_id, submission_data, status, confirmation_number, device_type, user_agent,
                 referrer_url, utm_source, utm_medium, utm_campaign, utm_term, utm_content,
                 page_url, ip_address, browser, os, screen_resolution, language, session_id)
               VALUES (%s, %s::jsonb, 'new', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id, confirmation_number""",
            (
                form["id"],
                json.dumps(form_data),
                conf_number,
                device, ua_string[:500],
                data.get("referrer", ""), data.get("utm_source", ""),
                data.get("utm_medium", ""), data.get("utm_campaign", ""),
                data.get("utm_term", ""), data.get("utm_content", ""),
                data.get("page_url", ""), ip, browser, os_name,
                data.get("screen_resolution", ""), data.get("language", ""),
                session_id
            )
        )
    return jsonify({
        "success": True,
        "id": result["id"] if result else None,
        "confirmation_number": result["confirmation_number"] if result else conf_number
    }), 201


# =============================================================================
# VISITOR ANALYTICS — Tracking endpoints
# =============================================================================
# Public endpoints to record page views and time-on-page (duration).
# Rate-limited: max 1 pageview per session_id + page_url per 30 seconds.
# Duration is updated via sendBeacon on page unload.

# In-memory rate-limit cache: { "session_id|page_url": last_insert_timestamp }
_pv_rate_cache = {}

@app.route("/api/track/pageview", methods=["POST"])
def api_track_pageview():
    """POST /api/track/pageview — Record a new page view.

    Expected JSON body:
      session_id, visitor_id, page_url, referrer_url,
      utm_source, utm_medium, utm_campaign, utm_term, utm_content,
      screen_resolution, language
    """
    data = request.get_json(silent=True) or {}
    session_id = (data.get("session_id") or "").strip()
    page_url   = (data.get("page_url") or "").strip()

    if not session_id or not page_url:
        return jsonify({"error": "session_id and page_url required"}), 400

    # --- Rate-limit: 1 insert per session+page per 30 seconds ----------------
    import time as _time
    cache_key = f"{session_id}|{page_url}"
    now = _time.time()
    last = _pv_rate_cache.get(cache_key, 0)
    if now - last < 30:
        return jsonify({"ok": True, "rate_limited": True}), 200
    _pv_rate_cache[cache_key] = now

    # --- Parse User-Agent for browser / OS / device --------------------------
    ua_string = request.headers.get("User-Agent", "")
    browser, os_name, device = _parse_ua(ua_string)

    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")

    row = execute_db(
        """INSERT INTO page_views
               (session_id, visitor_id, page_url, referrer_url,
                utm_source, utm_medium, utm_campaign, utm_term, utm_content,
                ip_address, browser, os, device_type,
                screen_resolution, language)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id""",
        (
            session_id,
            data.get("visitor_id", ""),
            page_url,
            data.get("referrer_url", ""),
            data.get("utm_source", ""),
            data.get("utm_medium", ""),
            data.get("utm_campaign", ""),
            data.get("utm_term", ""),
            data.get("utm_content", ""),
            ip,
            browser,
            os_name,
            device,
            data.get("screen_resolution", ""),
            data.get("language", ""),
        ),
    )

    return jsonify({"ok": True, "id": row["id"] if row else None}), 201


@app.route("/api/track/duration", methods=["POST"])
def api_track_duration():
    """POST /api/track/duration — Update duration_seconds for the most recent
    page-view matching the given session_id + page_url.

    Called via navigator.sendBeacon on beforeunload.
    Body may arrive as plain text (sendBeacon sends Blob), so we accept both
    JSON content-type and plain text.
    """
    raw = request.get_data(as_text=True)
    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}

    session_id = (data.get("session_id") or "").strip()
    page_url   = (data.get("page_url") or "").strip()
    duration   = int(data.get("duration", 0) or 0)

    if not session_id or not page_url or duration <= 0:
        return jsonify({"ok": False}), 400

    # Cap duration at 30 minutes to avoid bogus values
    if duration > 1800:
        duration = 1800

    execute_db(
        """UPDATE page_views
              SET duration_seconds = %s
            WHERE id = (
                SELECT id FROM page_views
                 WHERE session_id = %s AND page_url = %s
                 ORDER BY created_at DESC LIMIT 1
            )""",
        (duration, session_id, page_url),
    )
    return jsonify({"ok": True}), 200


# =============================================================================
# ADMIN ANALYTICS API — Aggregated visitor stats for the dashboard
# =============================================================================

@app.route("/admin/api/analytics")
@admin_required
def admin_api_analytics():
    """GET /admin/api/analytics — Return aggregated analytics data.

    Query params:
      days  — number of past days to include (default 30, max 365)
    """
    days = min(int(request.args.get("days", 30)), 365)

    # --- Summary counts ------------------------------------------------------
    summary = query_db(
        """SELECT
               COUNT(*)                                     AS total_views,
               COUNT(DISTINCT visitor_id) FILTER (WHERE visitor_id != '') AS unique_visitors,
               COUNT(DISTINCT session_id)                   AS total_sessions,
               COALESCE(AVG(duration_seconds) FILTER (WHERE duration_seconds > 0), 0) AS avg_duration,
               COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE) AS today_views,
               COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE - INTERVAL '7 days') AS week_views
           FROM page_views
           WHERE created_at >= NOW() - MAKE_INTERVAL(days => %s)""",
        (days,),
        fetchone=True,
    )

    # --- Top pages -----------------------------------------------------------
    top_pages = query_db(
        """SELECT page_url, COUNT(*) AS views,
                  COALESCE(AVG(duration_seconds) FILTER (WHERE duration_seconds > 0), 0) AS avg_dur
             FROM page_views
            WHERE created_at >= NOW() - MAKE_INTERVAL(days => %s)
            GROUP BY page_url
            ORDER BY views DESC
            LIMIT 10""",
        (days,),
    )

    # --- Browser breakdown ---------------------------------------------------
    browsers = query_db(
        """SELECT browser, COUNT(*) AS cnt
             FROM page_views
            WHERE created_at >= NOW() - MAKE_INTERVAL(days => %s) AND browser != ''
            GROUP BY browser ORDER BY cnt DESC LIMIT 5""",
        (days,),
    )

    # --- Device breakdown ----------------------------------------------------
    devices = query_db(
        """SELECT device_type, COUNT(*) AS cnt
             FROM page_views
            WHERE created_at >= NOW() - MAKE_INTERVAL(days => %s)
            GROUP BY device_type ORDER BY cnt DESC""",
        (days,),
    )

    # --- OS breakdown --------------------------------------------------------
    os_stats = query_db(
        """SELECT os, COUNT(*) AS cnt
             FROM page_views
            WHERE created_at >= NOW() - MAKE_INTERVAL(days => %s) AND os != ''
            GROUP BY os ORDER BY cnt DESC LIMIT 5""",
        (days,),
    )

    # --- Top referrers -------------------------------------------------------
    referrers = query_db(
        """SELECT referrer_url, COUNT(*) AS cnt
             FROM page_views
            WHERE created_at >= NOW() - MAKE_INTERVAL(days => %s) AND referrer_url != ''
            GROUP BY referrer_url ORDER BY cnt DESC LIMIT 10""",
        (days,),
    )

    # --- Top UTM sources -----------------------------------------------------
    utm_sources = query_db(
        """SELECT utm_source, COUNT(*) AS cnt
             FROM page_views
            WHERE created_at >= NOW() - MAKE_INTERVAL(days => %s) AND utm_source != ''
            GROUP BY utm_source ORDER BY cnt DESC LIMIT 5""",
        (days,),
    )

    # --- Recent page views (last 50) ----------------------------------------
    recent = query_db(
        """SELECT id, session_id, visitor_id, page_url, referrer_url,
                  browser, os, device_type, duration_seconds,
                  utm_source, created_at
             FROM page_views
            WHERE created_at >= NOW() - MAKE_INTERVAL(days => %s)
            ORDER BY created_at DESC LIMIT 50""",
        (days,),
    )

    def _row(r):
        d = dict(r)
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        return d

    return jsonify({
        "summary": {
            "total_views": summary["total_views"],
            "unique_visitors": summary["unique_visitors"],
            "total_sessions": summary["total_sessions"],
            "avg_duration": round(float(summary["avg_duration"]), 1),
            "today_views": summary["today_views"],
            "week_views": summary["week_views"],
        },
        "top_pages":   [_row(r) for r in top_pages],
        "browsers":    [_row(r) for r in browsers],
        "devices":     [_row(r) for r in devices],
        "os_stats":    [_row(r) for r in os_stats],
        "referrers":   [_row(r) for r in referrers],
        "utm_sources": [_row(r) for r in utm_sources],
        "recent":      [_row(r) for r in recent],
    })


@app.route("/admin/api/analytics/chart")
@admin_required
def admin_api_analytics_chart():
    """GET /admin/api/analytics/chart — Daily pageview counts for bar chart.

    Query params:
      days — number of past days (default 30, max 90)
    Returns JSON array of { date, views } objects.
    """
    days = min(int(request.args.get("days", 30)), 90)

    rows = query_db(
        """SELECT d::date AS date, COALESCE(pv.cnt, 0) AS views
             FROM generate_series(
                      (CURRENT_DATE - MAKE_INTERVAL(days => %s - 1)),
                      CURRENT_DATE,
                      '1 day'::interval
                  ) AS d
             LEFT JOIN (
                 SELECT created_at::date AS day, COUNT(*) AS cnt
                   FROM page_views
                  WHERE created_at >= CURRENT_DATE - MAKE_INTERVAL(days => %s - 1)
                  GROUP BY day
             ) pv ON pv.day = d::date
           ORDER BY d""",
        (days, days),
    )

    result = []
    for r in rows:
        d = r["date"]
        result.append({
            "date": d.isoformat() if hasattr(d, "isoformat") else str(d),
            "views": r["views"],
        })
    return jsonify(result)


# =============================================================================
# APP ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
