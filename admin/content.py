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
