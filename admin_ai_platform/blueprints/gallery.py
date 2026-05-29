"""
admin_ai_platform.blueprints.gallery
====================================

Gallery cards — the primary content type the visitor AI navigates to. Ships
with the package (the kit "comes with the gallery") so the ``navigate`` command
works out of the box.

Routes (ported from app.py):
  * ``GET  /api/gallery-cards``                 — public read (widget + site index)
  * ``GET  /admin/api/gallery-cards``           — admin list
  * ``POST /admin/api/gallery-cards``           — create
  * ``PUT  /admin/api/gallery-cards/<id>``      — update
  * ``DELETE /admin/api/gallery-cards/<id>``    — delete
"""

from __future__ import annotations

import json

from flask import Blueprint, request, jsonify

from ..db import query_db, execute_db
from ..auth import admin_required

bp = Blueprint("gallery", __name__)


@bp.route("/api/gallery-cards", methods=["GET"])
def public_list_cards():
    """Public: all gallery cards in display order (consumed by the widget)."""
    cards = query_db("SELECT * FROM gallery_cards ORDER BY sort_order ASC")
    return jsonify(cards or [])


@bp.route("/admin/api/gallery-cards", methods=["GET"])
@admin_required
def admin_list_cards():
    cards = query_db("SELECT * FROM gallery_cards ORDER BY sort_order ASC")
    return jsonify(cards or [])


@bp.route("/admin/api/gallery-cards", methods=["POST"])
@admin_required
def admin_create_card():
    data = request.get_json() or {}
    card = execute_db(
        """INSERT INTO gallery_cards
             (slug, title, subtitle, image_url, video_url, category,
              description, details, price, sort_order)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
           RETURNING *""",
        (data["slug"], data["title"], data.get("subtitle", ""),
         data.get("image_url", ""), data.get("video_url", ""),
         data.get("category", ""), data.get("description", ""),
         json.dumps(data.get("details", [])),
         data.get("price"), data.get("sort_order", 0)),
    )
    return jsonify(card), 201


@bp.route("/admin/api/gallery-cards/<int:card_id>", methods=["PUT"])
@admin_required
def admin_update_card(card_id):
    data = request.get_json() or {}
    card = execute_db(
        """UPDATE gallery_cards SET
             slug=%s, title=%s, subtitle=%s, image_url=%s, video_url=%s,
             category=%s, description=%s, details=%s::jsonb, price=%s,
             sort_order=%s, updated_at=NOW()
           WHERE id=%s RETURNING *""",
        (data["slug"], data["title"], data.get("subtitle", ""),
         data.get("image_url", ""), data.get("video_url", ""),
         data.get("category", ""), data.get("description", ""),
         json.dumps(data.get("details", [])),
         data.get("price"), data.get("sort_order", 0), card_id),
    )
    if not card:
        return jsonify({"error": "Card not found"}), 404
    return jsonify(card)


@bp.route("/admin/api/gallery-cards/<int:card_id>", methods=["DELETE"])
@admin_required
def admin_delete_card(card_id):
    count = execute_db("DELETE FROM gallery_cards WHERE id = %s", (card_id,))
    if count == 0:
        return jsonify({"error": "Card not found"}), 404
    return jsonify({"success": True})
