"""
===============================================================================
CASA SERENA — Flask Backend (app.py)
===============================================================================

PURPOSE:
  This is the main backend server for the Casa Serena website template.
  It connects to a PostgreSQL database and serves:
    1. A public-facing HTML/CSS/JS website (from the /public folder)
    2. An admin dashboard for editing all site content (from /templates/admin)
    3. REST API endpoints for both public reads and admin CRUD operations

HOW IT WORKS:
  - The public site (index.html) calls GET /api/* endpoints to fetch content
    from the database, then renders it client-side with JavaScript.
  - The admin dashboard calls GET/POST/PUT/DELETE /admin/api/* endpoints
    to create, read, update, and delete content in the database.
  - Both share the same PostgreSQL database, so changes in the admin panel
    are immediately visible on the public site.

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
import json
from datetime import datetime

import psycopg2
import psycopg2.extras
from flask import Flask, request, jsonify, send_from_directory, render_template

# =============================================================================
# APP CONFIGURATION
# =============================================================================

app = Flask(
    __name__,
    static_folder="public",       # Serve public site files from /public
    template_folder="templates"   # Jinja2 templates for admin dashboard
)

# Database connection string from environment variable
DATABASE_URL = os.environ.get("DATABASE_URL")


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
                # Convert RealDictRow objects to plain dicts for JSON serialization
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
    Existing data is never touched (IF NOT EXISTS).
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
            """)
    finally:
        conn.close()


# =============================================================================
# CUSTOM JSON ENCODER
# =============================================================================

class CustomJSONEncoder(json.JSONEncoder):
    """Handle datetime serialization for JSON responses."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

app.json_encoder = CustomJSONEncoder


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
# These endpoints are called by the public site's JavaScript (script.js)
# to load content from the database and render it on the page.
# They are read-only (GET) — no modifications allowed from the public site.

@app.route("/api/site-settings")
def api_site_settings():
    """
    GET /api/site-settings
    Returns the site-wide configuration (name, tagline, hero content, etc.).
    The public site uses this to populate the hero section and navigation.
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
    Used for both the Highlights grid on the landing page
    and the fullscreen slides in the Explore/Gallery view.
    """
    cards = query_db("SELECT * FROM gallery_cards ORDER BY sort_order ASC")
    return jsonify(cards or [])


@app.route("/api/experiences")
def api_experiences():
    """
    GET /api/experiences
    Returns all curated experiences ordered by sort_order.
    Used in the Experiences section of the landing page.
    """
    exps = query_db("SELECT * FROM experiences ORDER BY sort_order ASC")
    return jsonify(exps or [])


@app.route("/api/pricing")
def api_pricing():
    """
    GET /api/pricing
    Returns all pricing seasons ordered by sort_order.
    Used in the Pricing section of the landing page.
    """
    pricing = query_db("SELECT * FROM pricing_seasons ORDER BY sort_order ASC")
    return jsonify(pricing or [])


# =============================================================================
# ADMIN DASHBOARD — HTML pages
# =============================================================================

@app.route("/admin")
def admin_dashboard():
    """
    GET /admin
    Render the admin dashboard HTML page.
    This is where site owners can edit all content.
    """
    return render_template("admin/dashboard.html")


# =============================================================================
# ADMIN API — CRUD endpoints for the admin dashboard
# =============================================================================
# These endpoints are called by the admin dashboard's JavaScript
# to create, read, update, and delete content in the database.
# In a production app, you would protect these with authentication.

# --------------- Gallery Cards CRUD ---------------

@app.route("/admin/api/gallery-cards", methods=["GET"])
def admin_get_cards():
    """GET all gallery cards for the admin panel."""
    cards = query_db("SELECT * FROM gallery_cards ORDER BY sort_order ASC")
    return jsonify(cards or [])


@app.route("/admin/api/gallery-cards", methods=["POST"])
def admin_create_card():
    """
    POST /admin/api/gallery-cards
    Create a new gallery card. Expects JSON body with:
      slug, title, subtitle, image_url, category, description, details, price, sort_order
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
def admin_update_card(card_id):
    """
    PUT /admin/api/gallery-cards/<id>
    Update an existing gallery card. Expects JSON body with fields to update.
    """
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
def admin_delete_card(card_id):
    """
    DELETE /admin/api/gallery-cards/<id>
    Remove a gallery card from the database.
    """
    count = execute_db("DELETE FROM gallery_cards WHERE id = %s", (card_id,))
    if count == 0:
        return jsonify({"error": "Card not found"}), 404
    return jsonify({"success": True})


# --------------- Experiences CRUD ---------------

@app.route("/admin/api/experiences", methods=["GET"])
def admin_get_experiences():
    """GET all experiences for the admin panel."""
    exps = query_db("SELECT * FROM experiences ORDER BY sort_order ASC")
    return jsonify(exps or [])


@app.route("/admin/api/experiences", methods=["POST"])
def admin_create_experience():
    """
    POST /admin/api/experiences
    Create a new experience. Expects JSON body with:
      name, description, icon, sort_order
    """
    data = request.get_json()
    exp = execute_db(
        """INSERT INTO experiences (name, description, icon, sort_order)
           VALUES (%s, %s, %s, %s) RETURNING *""",
        (data["name"], data["description"], data.get("icon", "star"), data.get("sort_order", 0))
    )
    return jsonify(exp), 201


@app.route("/admin/api/experiences/<int:exp_id>", methods=["PUT"])
def admin_update_experience(exp_id):
    """
    PUT /admin/api/experiences/<id>
    Update an existing experience.
    """
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
def admin_delete_experience(exp_id):
    """
    DELETE /admin/api/experiences/<id>
    Remove an experience from the database.
    """
    count = execute_db("DELETE FROM experiences WHERE id = %s", (exp_id,))
    if count == 0:
        return jsonify({"error": "Experience not found"}), 404
    return jsonify({"success": True})


# --------------- Pricing CRUD ---------------

@app.route("/admin/api/pricing", methods=["GET"])
def admin_get_pricing():
    """GET all pricing seasons for the admin panel."""
    pricing = query_db("SELECT * FROM pricing_seasons ORDER BY sort_order ASC")
    return jsonify(pricing or [])


@app.route("/admin/api/pricing", methods=["POST"])
def admin_create_pricing():
    """
    POST /admin/api/pricing
    Create a new pricing season. Expects JSON body with:
      label, date_range, price_range, sort_order
    """
    data = request.get_json()
    p = execute_db(
        """INSERT INTO pricing_seasons (label, date_range, price_range, sort_order)
           VALUES (%s, %s, %s, %s) RETURNING *""",
        (data["label"], data["date_range"], data["price_range"], data.get("sort_order", 0))
    )
    return jsonify(p), 201


@app.route("/admin/api/pricing/<int:price_id>", methods=["PUT"])
def admin_update_pricing(price_id):
    """
    PUT /admin/api/pricing/<id>
    Update an existing pricing season.
    """
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
def admin_delete_pricing(price_id):
    """
    DELETE /admin/api/pricing/<id>
    Remove a pricing season from the database.
    """
    count = execute_db("DELETE FROM pricing_seasons WHERE id = %s", (price_id,))
    if count == 0:
        return jsonify({"error": "Pricing not found"}), 404
    return jsonify({"success": True})


# --------------- Site Settings CRUD ---------------

@app.route("/admin/api/site-settings", methods=["GET"])
def admin_get_settings():
    """GET the current site settings."""
    settings = query_db("SELECT * FROM site_settings WHERE id = 1", fetchone=True)
    return jsonify(settings or {})


@app.route("/admin/api/site-settings", methods=["PUT"])
def admin_update_settings():
    """
    PUT /admin/api/site-settings
    Update the site-wide settings. Expects JSON body with:
      site_name, site_subtitle, hero_tagline, hero_title, hero_description,
      hero_image, logo_initials
    """
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


# =============================================================================
# APP ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # Initialize database tables on startup
    init_db()

    # Start the Flask development server
    # Host 0.0.0.0 makes it accessible externally (required for Replit)
    # Port 5000 matches the Replit workflow configuration
    app.run(host="0.0.0.0", port=5000, debug=True)
