"""
admin_ai_platform.blueprints.presentations
==========================================

Presentation decks the AI can launch on a visitor's screen with voice narration
(via the start_presentation command + lookup_presentation tool). Admin CRUD for
decks + ordered slides; public read by slug.

  * ``GET/POST /admin/api/presentations`` + ``GET/PUT/DELETE /<id>``
  * ``POST /admin/api/presentations/<id>/slides``   add a slide
  * ``PUT/DELETE /admin/api/slides/<sid>``          edit / remove a slide
  * ``GET /api/presentations/<slug>``               public deck + slides

PPTX/Office import (LibreOffice → per-slide images) is a follow-on; this build
covers admin-authored decks + the public player payload.
"""

from __future__ import annotations

import re

from flask import Blueprint, request, jsonify

from ..db import query_db, execute_db
from ..auth import admin_required

bp = Blueprint("presentations", __name__)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,119}$")


@bp.route("/admin/api/presentations", methods=["GET"])
@admin_required
def list_decks():
    return jsonify({"presentations": query_db(
        "SELECT p.*, (SELECT COUNT(*) FROM presentation_slides WHERE presentation_id=p.id) "
        "AS slide_count FROM presentations p ORDER BY p.id DESC") or []})


@bp.route("/admin/api/presentations", methods=["POST"])
@admin_required
def create_deck():
    d = request.get_json() or {}
    slug = (d.get("slug") or "").strip().lower()
    if not _SLUG_RE.match(slug):
        return jsonify({"error": "slug must match ^[a-z0-9][a-z0-9-]{0,119}$"}), 400
    row = execute_db(
        "INSERT INTO presentations (slug, title, description, cover_image_url, source, "
        " auto_play, enabled) VALUES (%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (slug) DO NOTHING RETURNING *",
        (slug, d.get("title", ""), d.get("description", ""), d.get("cover_image_url", ""),
         d.get("source", "admin"), bool(d.get("auto_play", False)), bool(d.get("enabled", True))))
    if not row:
        return jsonify({"error": "slug already exists"}), 409
    return jsonify(row), 201


@bp.route("/admin/api/presentations/<int:pid>", methods=["GET"])
@admin_required
def get_deck(pid):
    deck = query_db("SELECT * FROM presentations WHERE id=%s", (pid,), fetchone=True)
    if not deck:
        return jsonify({"error": "Not found"}), 404
    deck["slides"] = query_db("SELECT * FROM presentation_slides WHERE presentation_id=%s "
                              "ORDER BY order_index, id", (pid,)) or []
    return jsonify(deck)


@bp.route("/admin/api/presentations/<int:pid>", methods=["PUT"])
@admin_required
def update_deck(pid):
    d = request.get_json() or {}
    sets, vals = [], []
    for k in ("title", "description", "cover_image_url", "auto_play", "enabled"):
        if k in d:
            sets.append(f"{k}=%s")
            vals.append(d[k])
    if not sets:
        return jsonify({"error": "No fields"}), 400
    vals.append(pid)
    row = execute_db(f"UPDATE presentations SET {', '.join(sets)} WHERE id=%s RETURNING *", tuple(vals))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/presentations/<int:pid>", methods=["DELETE"])
@admin_required
def delete_deck(pid):
    execute_db("DELETE FROM presentations WHERE id=%s", (pid,))
    return jsonify({"success": True})


@bp.route("/admin/api/presentations/<int:pid>/slides", methods=["POST"])
@admin_required
def add_slide(pid):
    if not query_db("SELECT 1 FROM presentations WHERE id=%s", (pid,), fetchone=True):
        return jsonify({"error": "deck not found"}), 404
    d = request.get_json() or {}
    nxt = (query_db("SELECT COALESCE(MAX(order_index),-1)+1 AS n FROM presentation_slides "
                    "WHERE presentation_id=%s", (pid,), fetchone=True) or {}).get("n", 0)
    row = execute_db(
        "INSERT INTO presentation_slides (presentation_id, order_index, title, body, "
        " image_url, narration_text) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
        (pid, int(d.get("order_index", nxt)), d.get("title", ""), d.get("body", ""),
         d.get("image_url", ""), d.get("narration_text", "")))
    return jsonify(row), 201


@bp.route("/admin/api/slides/<int:sid>", methods=["PUT"])
@admin_required
def update_slide(sid):
    d = request.get_json() or {}
    sets, vals = [], []
    for k in ("order_index", "title", "body", "image_url", "narration_text"):
        if k in d:
            sets.append(f"{k}=%s")
            vals.append(d[k])
    if not sets:
        return jsonify({"error": "No fields"}), 400
    vals.append(sid)
    row = execute_db(f"UPDATE presentation_slides SET {', '.join(sets)} WHERE id=%s RETURNING *", tuple(vals))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/slides/<int:sid>", methods=["DELETE"])
@admin_required
def delete_slide(sid):
    execute_db("DELETE FROM presentation_slides WHERE id=%s", (sid,))
    return jsonify({"success": True})


@bp.route("/api/presentations/<slug>", methods=["GET"])
def public_deck(slug):
    deck = query_db("SELECT id, slug, title, description, cover_image_url, auto_play "
                    "FROM presentations WHERE slug=%s AND enabled=TRUE", (slug,), fetchone=True)
    if not deck:
        return jsonify({"error": "Not found"}), 404
    deck["slides"] = query_db(
        "SELECT order_index, title, body, image_url, narration_text "
        "FROM presentation_slides WHERE presentation_id=%s ORDER BY order_index, id",
        (deck["id"],)) or []
    return jsonify(deck)
