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


# =============================================================================
# More public reads (Track B / B3) - moved verbatim from app.py. All simple
# query_db + jsonify GETs; @app.route rewritten to @public_bp.route (same URLs).
# =============================================================================

@public_bp.route("/api/gallery-cards")
def api_gallery_cards():
    """
    GET /api/gallery-cards
    Returns all gallery cards ordered by sort_order.
    """
    cards = query_db("SELECT * FROM gallery_cards ORDER BY sort_order ASC")
    return jsonify(cards or [])


@public_bp.route("/api/video-gallery")
def api_video_gallery():
    """GET /api/video-gallery — Public list of video gallery items."""
    items = query_db(
        "SELECT * FROM video_gallery_items ORDER BY sort_order ASC, id ASC"
    )
    return jsonify(items or [])


@public_bp.route("/api/podcast")
def api_podcast():
    """GET /api/podcast — Public list of podcast episodes."""
    items = query_db(
        "SELECT * FROM podcast_episodes ORDER BY sort_order ASC, id ASC"
    )
    return jsonify(items or [])


@public_bp.route("/api/experiences")
def api_experiences():
    """
    GET /api/experiences
    Returns all curated experiences ordered by sort_order.
    """
    exps = query_db("SELECT * FROM experiences ORDER BY sort_order ASC")
    return jsonify(exps or [])


@public_bp.route("/api/pricing")
def api_pricing():
    """
    GET /api/pricing
    Returns all pricing seasons ordered by sort_order.
    """
    pricing = query_db("SELECT * FROM pricing_seasons ORDER BY sort_order ASC")
    return jsonify(pricing or [])


# =============================================================
# PUBLIC API — TESTIMONIALS
# =============================================================
@public_bp.route("/api/testimonials")
def api_testimonials():
    """
    GET /api/testimonials
    Returns all testimonials ordered by sort_order.
    Only returned if the section is enabled in site_settings.
    """
    testimonials = query_db("SELECT * FROM testimonials ORDER BY sort_order ASC")
    return jsonify(testimonials or [])


# =============================================================
# PUBLIC API — TEAM MEMBERS
# =============================================================
@public_bp.route("/api/team")
def api_team():
    """
    GET /api/team
    Returns all team members ordered by sort_order.
    Only returned if the section is enabled in site_settings.
    """
    team = query_db("SELECT * FROM team_members ORDER BY sort_order ASC")
    return jsonify(team or [])


# =============================================================
# PUBLIC API — FAQ
# =============================================================
@public_bp.route("/api/faq")
def api_faq():
    """
    GET /api/faq
    Returns all FAQ entries ordered by sort_order.
    Only returned if the section is enabled in site_settings.
    """
    faqs = query_db("SELECT * FROM faqs ORDER BY sort_order ASC")
    return jsonify(faqs or [])


# =============================================================
# PUBLIC API — BLOG POSTS
# =============================================================

@public_bp.route("/api/blog")
def api_blog():
    """
    GET /api/blog
    Returns all published blog posts, sorted by published_at DESC
    (most recent first), with sort_order as a secondary sort.
    Only published posts are returned to the public site.
    """
    posts = query_db(
        """SELECT id, slug, title, subtitle, excerpt, cover_image,
                  author, category, tags, published_at, sort_order
           FROM blog_posts
           WHERE status = 'published'
           ORDER BY sort_order ASC, published_at DESC"""
    )
    return jsonify(posts or [])


@public_bp.route("/api/blog/<string:slug>")
def api_blog_post(slug):
    """
    GET /api/blog/<slug>
    Returns a single published blog post by its URL slug.
    Used by the blog detail page and for preview cards.
    """
    post = query_db(
        "SELECT * FROM blog_posts WHERE slug = %s AND status = 'published'",
        (slug,), fetchone=True
    )
    if not post:
        return jsonify({"error": "Blog post not found"}), 404
    return jsonify(post)
