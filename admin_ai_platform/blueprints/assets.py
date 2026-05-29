"""
admin_ai_platform.blueprints.assets
===================================

Serves the widget's static assets and the self-contained demo page during
development / same-origin use:

  * ``GET /widget/<file>``  — chat-ui.css / chat-ui.js / voice.js from ``web/``
  * ``GET /demo``           — the demo page from ``demo/index.html``
  * ``GET /api/generated-pages/by-slug/<slug>`` — published AI page HTML
    (used by the showSavedPage command)

The cross-origin embed loader (``/embed/loader.js``) lands in M7.
"""

from __future__ import annotations

import os
import re

from flask import Blueprint, send_from_directory, jsonify, abort

from ..db import query_db

bp = Blueprint("assets", __name__)

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEB_DIR = os.path.join(_PKG, "web")
_DEMO_DIR = os.path.join(_PKG, "demo")
_EMBED_DIR = os.path.join(os.path.dirname(_PKG), "embed")  # repo-root /embed
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,199}$")
_ALLOWED = {"chat-ui.js", "chat-ui.css", "voice.js"}


@bp.route("/widget/<path:filename>", methods=["GET"])
def widget_asset(filename):
    if filename not in _ALLOWED:
        abort(404)
    return send_from_directory(_WEB_DIR, filename)


@bp.route("/demo", methods=["GET"])
def demo_page():
    return send_from_directory(_DEMO_DIR, "index.html")


@bp.route("/embed/loader.js", methods=["GET"])
def embed_loader():
    # The cross-origin snippet target. Loaded via <script src> from any site —
    # script tags need no CORS. Served with a JS content type.
    resp = send_from_directory(_EMBED_DIR, "loader.js")
    resp.headers["Content-Type"] = "text/javascript"
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


@bp.route("/api/generated-pages/by-slug/<slug>", methods=["GET"])
def generated_page_by_slug(slug):
    if not slug or not _SLUG_RE.match(slug):
        return jsonify({"error": "Invalid slug"}), 400
    page = query_db(
        "SELECT title, slug, html FROM generated_pages "
        "WHERE slug = %s AND status = 'published'", (slug,), fetchone=True)
    if not page:
        return jsonify({"error": "Page not found"}), 404
    return jsonify({"title": page.get("title", ""), "slug": page.get("slug", ""),
                    "html": page.get("html", "")})
