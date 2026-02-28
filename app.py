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
                    created_at    TIMESTAMP DEFAULT NOW(),
                    updated_at    TIMESTAMP DEFAULT NOW()
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

3. Generate custom HTML content (tables, comparisons, etc.):
```command
{"action": "generateHTML", "html": "<div>YOUR HTML HERE</div>"}
```
Use this for complex visual layouts: pricing tables, comparison charts,
itineraries, timelines, or anything that benefits from rich formatting.
Use inline styles (dark theme: white text on transparent/dark background).
Use font-family: 'DM Sans', sans-serif for body and 'Playfair Display', serif for headings.

RULES:
- ALWAYS navigate when discussing a specific space. This IS the experience.
- Keep text responses to 1-3 sentences. Let the visuals do the talking.
- Use showSlide for comparisons, recommendations, and structured info.
- Use generateHTML for complex layouts like pricing tables or itineraries.
- When the user asks to "show me visually" or "visualize" something, ALWAYS use generateHTML to create a rich, beautiful HTML layout. Make it detailed and visually impressive.
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
    Handle incoming chat messages using OpenAI.

    Sends the user message + conversation history to GPT, parses the
    response for visual commands (navigate, showSlide, generateHTML),
    and returns both the text reply and any command.
    """
    data = request.get_json()
    message = data.get("message", "").strip()
    history = data.get("history", [])

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history[-20:]:
        role = "assistant" if h.get("role") == "agent" else "user"
        messages.append({"role": role, "content": h.get("content", "")})
    messages.append({"role": "user", "content": message})

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=2048,
            temperature=0.7,
        )
        full_text = response.choices[0].message.content or ""
        reply, command = parse_command_from_text(full_text)

        result = {"reply": reply}
        if command:
            result["command"] = command
        return jsonify(result)

    except Exception as e:
        return jsonify({
            "reply": f"I apologize, but I'm having trouble connecting right now. Please try again in a moment."
        }), 500


@app.route("/api/chat/stream", methods=["POST"])
def api_chat_stream():
    """
    POST /api/chat/stream
    Streaming version of the chat endpoint using Server-Sent Events (SSE).

    Used for generateHTML commands where the user sees the HTML being
    built live in the split-screen canvas. The stream sends:
      - {"type": "text", "content": "..."} for reply text chunks
      - {"type": "html_chunk", "content": "..."} for HTML chunks (live preview)
      - {"type": "command", "command": {...}} for the final parsed command
      - {"type": "done"} when streaming is complete
    """
    data = request.get_json()
    message = data.get("message", "").strip()
    history = data.get("history", [])

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
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
                if cmd.get("action") == "generateHTML" and cmd.get("html"):
                    yield f"data: {json.dumps({'type': 'html', 'content': cmd['html']})}\n\n"
                yield f"data: {json.dumps({'type': 'command', 'command': cmd})}\n\n"

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
    Update the chatbot configuration. Expects JSON body with:
      enabled, mode, agent_name, agent_role, agent_avatar,
      greeting, quick_prompts, api_endpoint, embed_code
    """
    data = request.get_json()
    settings = execute_db(
        """UPDATE chatbot_settings SET
             enabled = %s, mode = %s, agent_name = %s, agent_role = %s,
             agent_avatar = %s, greeting = %s, quick_prompts = %s::jsonb,
             api_endpoint = %s, embed_code = %s, updated_at = NOW()
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
            data.get("embed_code", "")
        )
    )
    return jsonify(settings)


# =============================================================================
# APP ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
