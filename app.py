"""
===============================================================================
CASA SERENA — Flask Backend (app.py)
===============================================================================

PURPOSE:
  This is the main backend server for the Casa Serena website template.
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
                    site_name     TEXT NOT NULL DEFAULT 'Casa Serena',
                    site_subtitle TEXT NOT NULL DEFAULT 'Mediterranean Villa',
                    hero_tagline  TEXT NOT NULL DEFAULT 'A Private Mediterranean Retreat',
                    hero_title    TEXT NOT NULL DEFAULT 'Casa Serena',
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
                    agent_name    TEXT NOT NULL DEFAULT 'Marco',
                    agent_role    TEXT NOT NULL DEFAULT 'Concierge',
                    agent_avatar  TEXT NOT NULL DEFAULT 'M',
                    greeting      TEXT NOT NULL DEFAULT 'Welcome! I''m Marco, your personal concierge. How can I help you explore Casa Serena today?',
                    quick_prompts JSONB DEFAULT '["Tour the villa", "Show me the rooms", "What experiences do you offer?", "Tell me about pricing"]'::jsonb,
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

                -- Booking form submissions with funnel tracking
                CREATE TABLE IF NOT EXISTS booking_submissions (
                    id             SERIAL PRIMARY KEY,
                    name           TEXT NOT NULL DEFAULT '',
                    email          TEXT NOT NULL DEFAULT '',
                    room_slug      VARCHAR(100) DEFAULT '',
                    room_name      TEXT DEFAULT '',
                    check_in       DATE,
                    check_out      DATE,
                    guests         INTEGER DEFAULT 1,
                    status         VARCHAR(20) NOT NULL DEFAULT 'new',
                    device_type    VARCHAR(20) DEFAULT 'desktop',
                    user_agent     TEXT DEFAULT '',
                    referrer_url   TEXT DEFAULT '',
                    utm_source     TEXT DEFAULT '',
                    utm_medium     TEXT DEFAULT '',
                    utm_campaign   TEXT DEFAULT '',
                    page_url       TEXT DEFAULT '',
                    ip_address     VARCHAR(45) DEFAULT '',
                    step_reached   VARCHAR(30) DEFAULT 'opened_modal',
                    form_started_at TIMESTAMP,
                    submitted_at   TIMESTAMP DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_booking_status ON booking_submissions (status);

                -- Uploaded images
                CREATE TABLE IF NOT EXISTS uploaded_images (
                    id            SERIAL PRIMARY KEY,
                    filename      TEXT NOT NULL,
                    original_name TEXT NOT NULL DEFAULT '',
                    file_size     INTEGER DEFAULT 0,
                    uploaded_at   TIMESTAMP DEFAULT NOW()
                );
            """)

            # Seed chatbot_settings singleton if it doesn't exist
            cur.execute("""
                INSERT INTO chatbot_settings (id, enabled, mode, agent_name, agent_role, agent_avatar,
                    greeting, quick_prompts, api_endpoint, embed_code)
                VALUES (1, false, 'builtin', 'Marco', 'Concierge', 'M',
                    'Welcome! I''m Marco, your personal concierge. How can I help you explore Casa Serena today?',
                    '["Tour the villa", "Show me the rooms", "What experiences do you offer?", "Tell me about pricing"]'::jsonb,
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
            ]:
                cur.execute(col_sql)
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
#     "reply": "Here's a comparison of our rooms.",
#     "command": {
#       "action": "showSlide",
#       "title": "Room Comparison",
#       "subtitle": "Finding your perfect suite",
#       "points": ["Master Suite: $1,800/night", "Ocean Room: $1,200/night"]
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
#      (e.g., "hero-villa", "master-suite", "infinity-pool", etc.)
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
You are Marco, a luxury concierge for Casa Serena, a Mediterranean villa.
You help guests explore the property and plan their stay.

IMPORTANT: You can control what the user sees on the website by including
a JSON command block in your response. Always wrap commands in ```command``` blocks.

AVAILABLE COMMANDS:

1. Navigate to a section of the property:
```command
{"action": "navigate", "target": "CARD_SLUG"}
```
Valid targets: hero-villa, master-suite, ocean-room, infinity-pool,
chef-kitchen, wine-cellar, sunset-terrace, coastal-village

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

RULES:
- ALWAYS navigate when discussing a specific space. This IS the experience.
- Keep text responses to 1-3 sentences. Let the visuals do the talking.
- Use showSlide for comparisons, recommendations, and structured info.
- Do NOT use generateVisual unless the user explicitly says "show me visually", "visualize", "create a visual", or similar. For normal questions about pricing, rooms, etc., just respond with text and use navigate or showSlide instead.
- Only include ONE command block per response.
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


# --------------- Booking Submissions ---------------

@app.route("/api/bookings", methods=["POST"])
def api_create_booking():
    """POST /api/bookings — Save a booking form submission with funnel tracking."""
    data = request.get_json()
    if not data or not data.get("name") or not data.get("email"):
        return jsonify({"error": "Name and email are required"}), 400
    try:
        guests = int(data.get("guests", 1))
    except (ValueError, TypeError):
        guests = 1
    ua = request.headers.get("User-Agent", "")
    device = "mobile" if any(m in ua.lower() for m in ["mobile", "android", "iphone"]) else "desktop"
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")

    booking = execute_db(
        """INSERT INTO booking_submissions
            (name, email, room_slug, room_name, check_in, check_out, guests,
             device_type, user_agent, referrer_url, utm_source, utm_medium,
             utm_campaign, page_url, ip_address, step_reached)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'submitted')
           RETURNING *""",
        (
            data.get("name", ""),
            data.get("email", ""),
            data.get("room_slug", ""),
            data.get("room_name", ""),
            data.get("check_in") or None,
            data.get("check_out") or None,
            guests,
            device,
            ua[:500],
            data.get("referrer", ""),
            data.get("utm_source", ""),
            data.get("utm_medium", ""),
            data.get("utm_campaign", ""),
            data.get("page_url", ""),
            ip
        )
    )
    return jsonify(booking), 201


@app.route("/api/booking-step", methods=["POST"])
def api_booking_step():
    """POST /api/booking-step — Log a funnel step (opened_modal, filling_form, etc.)."""
    data = request.get_json()
    ua = request.headers.get("User-Agent", "")
    device = "mobile" if any(m in ua.lower() for m in ["mobile", "android", "iphone"]) else "desktop"
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    step = data.get("step", "opened_modal")

    execute_db(
        """INSERT INTO booking_submissions
            (name, email, step_reached, device_type, user_agent, referrer_url,
             utm_source, utm_medium, utm_campaign, page_url, ip_address,
             form_started_at)
           VALUES ('', '', %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
           RETURNING id""",
        (
            step, device, ua[:500],
            data.get("referrer", ""),
            data.get("utm_source", ""),
            data.get("utm_medium", ""),
            data.get("utm_campaign", ""),
            data.get("page_url", ""),
            ip
        )
    )
    return jsonify({"success": True}), 201


@app.route("/admin/api/bookings", methods=["GET"])
@admin_required
def admin_list_bookings():
    """GET /admin/api/bookings — List all booking submissions with funnel stats."""
    bookings = query_db(
        "SELECT * FROM booking_submissions ORDER BY submitted_at DESC"
    )

    stats = query_db("""
        SELECT
            COUNT(*) FILTER (WHERE step_reached = 'opened_modal') as modal_opens,
            COUNT(*) FILTER (WHERE step_reached = 'filling_form') as form_starts,
            COUNT(*) FILTER (WHERE step_reached = 'submitted') as submissions,
            COUNT(*) as total
        FROM booking_submissions
    """, fetchone=True)

    return jsonify({"bookings": bookings or [], "stats": stats or {}})


@app.route("/admin/api/bookings/<int:booking_id>/status", methods=["PUT"])
@admin_required
def admin_update_booking_status(booking_id):
    """PUT /admin/api/bookings/<id>/status — Change a booking's status."""
    data = request.get_json()
    status = data.get("status", "new")
    result = execute_db(
        "UPDATE booking_submissions SET status = %s WHERE id = %s RETURNING id, status",
        (status, booking_id)
    )
    if not result:
        return jsonify({"error": "Booking not found"}), 404
    return jsonify(result)


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
# APP ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
