"""admin/public_api.py - public, unauthenticated read API as a Flask blueprint.

The FIRST blueprint of the app.py de-monolith (Track B / B2 - the proof that the
route-extraction pattern works end to end). These are public GET reads the public
site fetches by URL (no auth, no CSRF).

Key invariants:
  * Routes use ABSOLUTE paths (@public_bp.route("/api/...")), so the externally
    visible URL + methods are byte-identical to when the route lived on the global
    `app`. The route-table snapshot test (tests/test_route_snapshot.py) compares on
    (rule, methods), so a move shows up as zero change there. Only the Flask
    endpoint NAME changes (api_site_settings -> public_api.api_site_settings); the
    front-end calls by URL, not url_for, so nothing references the old name.
  * Imports shared infra from core (query_db) - NEVER from app (circular).

Registered in app.py via: app.register_blueprint(public_bp).

To grow this blueprint, move the other public read routes (gallery-cards, pricing,
experiences, blog, events, page-bundle, ...) here the same way, bringing any
private render helpers they use (e.g. _render_hero_fragment) with them and routing
any remaining app.py helper dependency through core.
"""
from flask import Blueprint, jsonify

from core import query_db

public_bp = Blueprint("public_api", __name__)


@public_bp.route("/api/site-settings")
def api_site_settings():
    """
    GET /api/site-settings
    Returns the site-wide configuration (name, tagline, hero content, etc.).
    """
    settings = query_db("SELECT * FROM site_settings WHERE id = 1", fetchone=True)
    if not settings:
        return jsonify({"error": "No site settings found"}), 404
    return jsonify(settings)
