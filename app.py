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
import secrets
from datetime import datetime
from functools import wraps

import psycopg2
import psycopg2.extras
from flask import (
    Flask, request, jsonify, send_from_directory,
    render_template, session, redirect, url_for, Response, stream_with_context
)
from openai import OpenAI

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

                -- Chat conversations (one per visitor session)
                CREATE TABLE IF NOT EXISTS chat_conversations (
                    id          SERIAL PRIMARY KEY,
                    session_id  VARCHAR(100) NOT NULL,
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
                "ALTER TABLE form_fields ADD COLUMN IF NOT EXISTS step INTEGER NOT NULL DEFAULT 1",
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
# PUBLIC ROUTES — Serve the static HTML site
# =============================================================================

@app.route("/")
def serve_index():
    """
    Serve the main public website (index.html).
    This is the landing page visitors see.
    """
    return send_from_directory("public", "index.html")


@app.route("/<path:filename>")
def serve_static(filename):
    """
    Serve any static file from the /public directory.
    This handles CSS, JS, images, fonts, etc.
    Falls through to other routes if the file doesn't exist.
    """
    try:
        return send_from_directory("public", filename)
    except Exception:
        return send_from_directory("public", "index.html")


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
#      { "action": "generateHTML", "html": "<div>Any valid HTML</div>" }
#      The AI can generate comparison tables, charts, custom layouts, etc.
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

IMPORTANT: You can control what the user sees on the website by including
a JSON command block in your response. Always wrap commands in ```command``` blocks.

AVAILABLE COMMANDS:

1. Navigate to a specific gallery item:
```command
{"action": "navigate", "target": "CARD_SLUG"}
```
Valid targets: use slugs from the gallery cards (the site owner configures these).

2. Show a structured slide with information:
```command
{"action": "showSlide", "title": "TITLE", "subtitle": "SUBTITLE", "points": ["point1", "point2"]}
```

3. Generate a visual slide (ONLY when user explicitly asks to "show me visually" or "visualize"):
```command
{"action": "generateVisual", "title": "TITLE", "subtitle": "optional subtitle", "columns": ["Col1", "Col2", "Col3"], "rows": [["Cell1", "Cell2", "Cell3"], ["Cell4", "Cell5", "Cell6"]], "footer": "optional footnote"}
```
The frontend renders this as a beautiful frosted-glass card automatically. You just provide the data.
- "title" (required): The heading of the visual
- "subtitle" (optional): A line below the title
- "columns" (optional): Column headers for a table layout
- "rows" (optional): Array of arrays — each inner array is one row of data matching the columns
- "items" (optional): Use INSTEAD of columns/rows for a simple list: [{"label": "Label", "value": "Value"}, ...]
- "footer" (optional): A footnote at the bottom

4. Display a message on the hero section (replaces the hero description text with a typing animation):
```command
{"action": "heroMessage", "message": "YOUR MESSAGE HERE"}
```
This updates the large hero text on the landing page. Use it for welcome messages,
personalized greetings, or key announcements. The page scrolls to the top automatically.
The original description restores when the page reloads.

RULES:
- ALWAYS navigate when discussing a specific item. This IS the experience — show, don't just tell.
- Keep text responses concise but natural (1-4 sentences). Be conversational, not robotic.
- Use showSlide for comparisons, recommendations, and structured info.
- Use heroMessage when the user asks you to greet them, display a welcome message, or when you want to highlight something prominently on the landing page.
- Do NOT use generateVisual unless the user explicitly says "show me visually", "visualize", "create a visual", or similar. For normal questions about pricing, services, etc., just respond with text and use navigate or showSlide instead.
- Only include ONE command block per response.
- Reference real names, prices, and details from the site data. Never make up information.
- If the visitor seems interested, proactively suggest related items or experiences they might enjoy.
"""


def parse_command_from_text(text):
    """
    Extract a ```command``` block from the AI's response text.
    Returns (clean_text, command_dict) — the text with the block removed,
    and the parsed command (or None if no command was found).

    Handles both properly closed ```command...``` blocks and cases where
    the closing fence is missing (model truncation).
    """
    pattern = r'```command\s*\n?(.*?)\n?\s*```'
    match = re.search(pattern, text, re.DOTALL)

    if not match:
        unclosed = re.search(r'```command\s*\n?(.*)', text, re.DOTALL)
        if unclosed:
            try:
                raw = unclosed.group(1).strip().rstrip('`').strip()
                cmd = json.loads(raw)
                clean = text[:unclosed.start()].strip()
                return clean, cmd
            except json.JSONDecodeError:
                return text.strip(), None
        return text.strip(), None

    try:
        cmd = json.loads(match.group(1).strip())
        clean = re.sub(pattern, '', text, flags=re.DOTALL).strip()
        return clean, cmd
    except json.JSONDecodeError:
        return text.strip(), None


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

    # Use database system prompt if available, otherwise fall back to hardcoded
    active_prompt = SYSTEM_PROMPT
    try:
        cs = query_db("SELECT system_prompt FROM chatbot_settings WHERE id = 1")
        if cs and cs.get("system_prompt", "").strip():
            active_prompt = cs["system_prompt"]
    except Exception:
        pass

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

        # ----- ADD MORE SECTIONS BELOW -----
        # Follow the same pattern: query → format → append to active_prompt
        # Example:
        #   faq = query_db("SELECT question, answer FROM faq ORDER BY sort_order ASC")
        #   if faq:
        #       faq_lines = [f'  Q: {f["question"]}\n  A: {f["answer"]}' for f in faq]
        #       active_prompt += f"\n\nFREQUENTLY ASKED QUESTIONS:\n" + "\n".join(faq_lines)

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

                    conv = query_db("SELECT id FROM chat_conversations WHERE session_id = %s ORDER BY id DESC LIMIT 1", (session_id,), fetchone=True)
                    if not conv:
                        conv = execute_db(
                            "INSERT INTO chat_conversations (session_id, visitor_ip, device_type, user_agent) VALUES (%s, %s, %s, %s) RETURNING id",
                            (session_id, ip, device, ua[:500])
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
        "pricing": "pricing_seasons"
    }
    table = table_map.get(content_type)
    if not table:
        return jsonify({"error": "Invalid content type"}), 400

    items = request.get_json()
    if not isinstance(items, list):
        return jsonify({"error": "Expected array of {id, sort_order}"}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            for item in items:
                cur.execute(
                    f"UPDATE {table} SET sort_order = %s, updated_at = NOW() WHERE id = %s",
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
            (SELECT COUNT(*) FROM chat_messages WHERE conversation_id = c.id) as message_count,
            (SELECT content FROM chat_messages WHERE conversation_id = c.id AND role = 'user' ORDER BY id LIMIT 1) as first_message
        FROM chat_conversations c
        ORDER BY c.updated_at DESC
        LIMIT %s OFFSET %s
    """, (per_page, offset))

    stats = query_db("""
        SELECT
            (SELECT COUNT(*) FROM chat_conversations) as total_conversations,
            (SELECT COUNT(*) FROM chat_messages WHERE created_at >= CURRENT_DATE) as messages_today,
            (SELECT ROUND(AVG(cnt), 1) FROM (SELECT COUNT(*) as cnt FROM chat_messages GROUP BY conversation_id) sub) as avg_messages
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

    if existing:
        result = execute_db(
            """UPDATE form_submissions SET
                 submission_data = %s::jsonb, status = 'new', updated_at = NOW(),
                 submitted_at = NOW(), device_type = %s, user_agent = %s,
                 referrer_url = %s, utm_source = %s, utm_medium = %s,
                 utm_campaign = %s, utm_term = %s, utm_content = %s,
                 page_url = %s, ip_address = %s, browser = %s, os = %s,
                 screen_resolution = %s, language = %s
               WHERE id = %s RETURNING id""",
            (
                json.dumps(form_data),
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
                (form_id, submission_data, status, device_type, user_agent,
                 referrer_url, utm_source, utm_medium, utm_campaign, utm_term, utm_content,
                 page_url, ip_address, browser, os, screen_resolution, language, session_id)
               VALUES (%s, %s::jsonb, 'new', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                form["id"],
                json.dumps(form_data),
                device, ua_string[:500],
                data.get("referrer", ""), data.get("utm_source", ""),
                data.get("utm_medium", ""), data.get("utm_campaign", ""),
                data.get("utm_term", ""), data.get("utm_content", ""),
                data.get("page_url", ""), ip, browser, os_name,
                data.get("screen_resolution", ""), data.get("language", ""),
                session_id
            )
        )
    return jsonify({"success": True, "id": result["id"] if result else None}), 201


# =============================================================================
# APP ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
