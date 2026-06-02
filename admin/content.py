"""admin/content.py - admin CRUD routes for site content, as a Flask blueprint.

The first ADMIN-area blueprint of the app.py de-monolith (Track B), after
public_api proved the public-read pattern. These routes are gated by
@admin_required (imported from core) and do content CRUD via query_db/execute_db
(also from core). URLs keep their absolute /admin/api/* paths, so the route table
is unchanged - only the Flask endpoint name gains a "content." prefix (admin JS
calls these by URL, not url_for).

Why no CSRF / feature-flag code here: those run in app.py's GLOBAL
@app.before_request hooks, which apply to blueprint routes too. So a moved admin
route keeps the exact same protection it had on the global app - nothing extra
needed. Imports come from core (never app - that would be circular).

Registered in app.py via app.register_blueprint(content_bp). Grow this blueprint
by moving more content CRUD groups (experiences, pricing, testimonials, team,
faq, blog, …) here the same way - they share this same core-only dependency set.
"""
import json

from flask import Blueprint, request, jsonify

from core import query_db, execute_db, admin_required

content_bp = Blueprint("content", __name__)


# ---- gallery cards CRUD (Track B / B4, verbatim from app.py) ----

@content_bp.route("/admin/api/gallery-cards", methods=["GET"])
@admin_required
def admin_get_cards():
    """GET all gallery cards for the admin panel."""
    cards = query_db("SELECT * FROM gallery_cards ORDER BY sort_order ASC")
    return jsonify(cards or [])


@content_bp.route("/admin/api/gallery-cards", methods=["POST"])
@admin_required
def admin_create_card():
    """
    POST /admin/api/gallery-cards
    Create a new gallery card.
    """
    data = request.get_json()
    card = execute_db(
        """INSERT INTO gallery_cards (slug, title, subtitle, image_url, video_url, category, description, details, price, sort_order)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
           RETURNING *""",
        (
            data["slug"], data["title"], data["subtitle"],
            data["image_url"], data.get("video_url", ""),
            data["category"], data["description"],
            json.dumps(data.get("details", [])),
            data.get("price"), data.get("sort_order", 0)
        )
    )
    return jsonify(card), 201


@content_bp.route("/admin/api/gallery-cards/<int:card_id>", methods=["PUT"])
@admin_required
def admin_update_card(card_id):
    """PUT /admin/api/gallery-cards/<id> — Update a gallery card."""
    data = request.get_json()
    card = execute_db(
        """UPDATE gallery_cards SET
             slug = %s, title = %s, subtitle = %s, image_url = %s,
             video_url = %s, category = %s, description = %s, details = %s::jsonb,
             price = %s, sort_order = %s, updated_at = NOW()
           WHERE id = %s RETURNING *""",
        (
            data["slug"], data["title"], data["subtitle"],
            data["image_url"], data.get("video_url", ""),
            data["category"], data["description"],
            json.dumps(data.get("details", [])),
            data.get("price"), data.get("sort_order", 0),
            card_id
        )
    )
    if not card:
        return jsonify({"error": "Card not found"}), 404
    return jsonify(card)


@content_bp.route("/admin/api/gallery-cards/<int:card_id>", methods=["DELETE"])
@admin_required
def admin_delete_card(card_id):
    """DELETE /admin/api/gallery-cards/<id> — Remove a gallery card."""
    count = execute_db("DELETE FROM gallery_cards WHERE id = %s", (card_id,))
    if count == 0:
        return jsonify({"error": "Card not found"}), 404
    return jsonify({"success": True})

# ---- experiences + pricing CRUD (Track B / B5, verbatim) ----

@content_bp.route("/admin/api/experiences", methods=["GET"])
@admin_required
def admin_get_experiences():
    """GET all experiences."""
    exps = query_db("SELECT * FROM experiences ORDER BY sort_order ASC")
    return jsonify(exps or [])


@content_bp.route("/admin/api/experiences", methods=["POST"])
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


@content_bp.route("/admin/api/experiences/<int:exp_id>", methods=["PUT"])
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


@content_bp.route("/admin/api/experiences/<int:exp_id>", methods=["DELETE"])
@admin_required
def admin_delete_experience(exp_id):
    """DELETE /admin/api/experiences/<id> — Remove an experience."""
    count = execute_db("DELETE FROM experiences WHERE id = %s", (exp_id,))
    if count == 0:
        return jsonify({"error": "Experience not found"}), 404
    return jsonify({"success": True})


# --------------- Pricing CRUD ---------------

@content_bp.route("/admin/api/pricing", methods=["GET"])
@admin_required
def admin_get_pricing():
    """GET all pricing seasons."""
    pricing = query_db("SELECT * FROM pricing_seasons ORDER BY sort_order ASC")
    return jsonify(pricing or [])


@content_bp.route("/admin/api/pricing", methods=["POST"])
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


@content_bp.route("/admin/api/pricing/<int:price_id>", methods=["PUT"])
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


@content_bp.route("/admin/api/pricing/<int:price_id>", methods=["DELETE"])
@admin_required
def admin_delete_pricing(price_id):
    """DELETE /admin/api/pricing/<id> — Remove a pricing season."""
    count = execute_db("DELETE FROM pricing_seasons WHERE id = %s", (price_id,))
    if count == 0:
        return jsonify({"error": "Pricing not found"}), 404
    return jsonify({"success": True})
