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

# ---- business-info + seo (Track B / B3 batch 2, verbatim) ----

@public_bp.route("/api/business-info")
def api_business_info():
    """
    GET /api/business-info
    Returns business contact info, hours, and social links
    from the site_settings table (single-row config).
    """
    info = query_db("""
        SELECT business_phone, business_email, business_address,
               business_hours, business_map_embed, social_links
        FROM site_settings WHERE id = 1
    """, fetchone=True)
    if not info:
        return jsonify({})
    return jsonify(info)


# =============================================================
# PUBLIC API — SEO SETTINGS
# =============================================================

@public_bp.route("/api/seo")
def api_seo():
    """
    GET /api/seo
    Returns the SEO settings for the public site. These are the values
    injected into the <head> meta tags by serve_index(). This endpoint
    is also available for any client-side JavaScript that needs SEO data.
    """
    settings = query_db("""
        SELECT seo_meta_title, seo_meta_description, seo_keywords,
               seo_og_image, seo_twitter_handle, seo_canonical_url,
               seo_robots, site_name, site_subtitle, hero_description
        FROM site_settings WHERE id = 1
    """, fetchone=True)
    if not settings:
        return jsonify({})
    return jsonify(settings)

# ---- events (read-only GETs; Track B / B3 batch 3, verbatim) ----

@public_bp.route("/api/events")
def api_events():
    """
    GET /api/events
    Returns published + cancelled events whose start date is today or
    later, ordered by start_at ASC (soonest first). Each row includes
    a `rsvp_count` aggregate (sum of guests across RSVPs) so the public
    card can show "12/30 spots taken" when capacity is set.
    Drafts are never returned here.
    """
    rows = query_db(
        """SELECT e.*,
                  COALESCE((SELECT SUM(guests) FROM event_rsvps r
                            WHERE r.event_id = e.id
                              AND r.payment_status NOT IN ('expired','failed')), 0)::int AS rsvp_count
           FROM events e
           WHERE e.status IN ('published', 'cancelled')
             AND e.start_at IS NOT NULL
             AND COALESCE(e.end_at, e.start_at) >= NOW()
           ORDER BY e.sort_order ASC, e.start_at ASC"""
    )
    return jsonify(rows or [])


@public_bp.route("/api/events/<string:slug>")
def api_event_detail(slug):
    """
    GET /api/events/<slug>
    Returns a single event by slug for the public detail page. Drafts
    return 404; cancelled events ARE returned (so the page can show a
    "This event has been cancelled" notice rather than a dead link).
    Includes `rsvp_count` for capacity display.
    """
    event = query_db(
        """SELECT e.*,
                  COALESCE((SELECT SUM(guests) FROM event_rsvps r
                            WHERE r.event_id = e.id
                              AND r.payment_status NOT IN ('expired','failed')), 0)::int AS rsvp_count
           FROM events e
           WHERE e.slug = %s AND e.status IN ('published', 'cancelled')""",
        (slug,), fetchone=True
    )
    if not event:
        return jsonify({"error": "Event not found"}), 404
    return jsonify(event)

# ---- sphere/page-sections + custom-section/chatbot-settings (Track B / B3 batch 4) ----

@public_bp.route("/api/sphere-settings")
def api_sphere_settings():
    """
    GET /api/sphere-settings
    Returns sphere view configuration and image URLs for the public site.
    If image_source is 'gallery', images come from gallery_cards.
    If image_source is 'custom', images come from sphere_images.
    """
    settings = query_db("SELECT * FROM sphere_settings WHERE id = 1", fetchone=True)
    if not settings:
        return jsonify({"enabled": False})

    result = dict(settings)

    if result.get("image_source") == "gallery":
        cards = query_db("SELECT image_url FROM gallery_cards WHERE image_url != '' ORDER BY sort_order ASC")
        result["images"] = [c["image_url"] for c in (cards or [])]
    else:
        imgs = query_db("SELECT id, image_url, caption, sort_order FROM sphere_images ORDER BY sort_order ASC")
        result["images"] = [i["image_url"] for i in (imgs or [])]

    # If sections mode, include section summary data for the 3D cards
    if result.get("view_mode") == "sections":
        site = query_db("SELECT site_name, site_subtitle, hero_tagline, hero_title, hero_description, hero_image FROM site_settings WHERE id = 1", fetchone=True)
        cards_data = query_db("SELECT slug, title, subtitle, image_url, category, price FROM gallery_cards ORDER BY sort_order ASC LIMIT 6")
        exps = query_db("SELECT name, description, icon FROM experiences ORDER BY sort_order ASC LIMIT 4")
        pricing = query_db("SELECT label, date_range, price_range FROM pricing_seasons ORDER BY sort_order ASC LIMIT 4")
        testimonials = query_db("SELECT reviewer_name, reviewer_role, content, rating FROM testimonials ORDER BY sort_order ASC LIMIT 3")
        team = query_db("SELECT name, title, image_url FROM team_members ORDER BY sort_order ASC LIMIT 4")
        faqs = query_db("SELECT question FROM faqs ORDER BY sort_order ASC LIMIT 4")
        blog = query_db("SELECT title, category, cover_image FROM blog_posts WHERE status = 'published' ORDER BY sort_order ASC LIMIT 3")

        result["sections_data"] = {
            "site": dict(site) if site else {},
            "highlights": [dict(c) for c in (cards_data or [])],
            "experiences": [dict(e) for e in (exps or [])],
            "pricing": [dict(p) for p in (pricing or [])],
            "testimonials": [dict(t) for t in (testimonials or [])],
            "team": [dict(t) for t in (team or [])],
            "faq": [dict(f) for f in (faqs or [])],
            "blog": [dict(b) for b in (blog or [])],
        }

    return jsonify(result)


@public_bp.route("/api/page-sections")
def api_page_sections():
    """
    GET /api/page-sections
    Returns ALL sections (enabled and disabled) ordered by sort_order.
    The frontend uses this to determine section order AND visibility —
    it needs disabled sections in the list so it can hide them properly.
    """
    sections = query_db(
        "SELECT * FROM page_sections ORDER BY sort_order ASC"
    )
    return jsonify(sections or [])

@public_bp.route("/api/custom-section/<int:section_id>/items")
def api_custom_section_items(section_id):
    """
    GET /api/custom-section/<section_id>/items
    Returns all items for a specific custom section, ordered by sort_order.
    """
    items = query_db(
        "SELECT * FROM custom_section_items WHERE section_id = %s ORDER BY sort_order ASC",
        (section_id,)
    )
    return jsonify(items or [])


@public_bp.route("/api/chatbot-settings")
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
    # Prompt privacy: the public site never needs the prompt wording, so it is
    # never exposed here (this endpoint is unauthenticated). The Brand Voice
    # layer is operator/business config too — also stripped from the public
    # payload.
    out = dict(settings)
    out.pop("system_prompt", None)
    out.pop("brand_voice", None)
    return jsonify(out)
