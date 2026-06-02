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
import re
from datetime import datetime

from flask import Blueprint, request, jsonify

from core import query_db, execute_db, get_db, admin_required

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

# ---- testimonials / video-gallery / podcast / team / faq CRUD (Track B / B6) ----

@content_bp.route("/admin/api/testimonials", methods=["GET"])
@admin_required
def admin_get_testimonials():
    """GET all testimonials for the admin panel."""
    items = query_db("SELECT * FROM testimonials ORDER BY sort_order ASC")
    return jsonify(items or [])


@content_bp.route("/admin/api/testimonials", methods=["POST"])
@admin_required
def admin_create_testimonial():
    """POST /admin/api/testimonials — Create a new testimonial."""
    data = request.get_json()
    item = execute_db(
        """INSERT INTO testimonials (reviewer_name, reviewer_role, content, rating, image_url, sort_order)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (data.get("reviewer_name", ""), data.get("reviewer_role", ""),
         data.get("content", ""), data.get("rating", 5),
         data.get("image_url", ""), data.get("sort_order", 0))
    )
    return jsonify(item), 201


@content_bp.route("/admin/api/testimonials/<int:item_id>", methods=["PUT"])
@admin_required
def admin_update_testimonial(item_id):
    """PUT /admin/api/testimonials/<id> — Update a testimonial."""
    data = request.get_json()
    item = execute_db(
        """UPDATE testimonials SET
             reviewer_name = %s, reviewer_role = %s, content = %s,
             rating = %s, image_url = %s, sort_order = %s
           WHERE id = %s RETURNING *""",
        (data.get("reviewer_name", ""), data.get("reviewer_role", ""),
         data.get("content", ""), data.get("rating", 5),
         data.get("image_url", ""), data.get("sort_order", 0), item_id)
    )
    if not item:
        return jsonify({"error": "Testimonial not found"}), 404
    return jsonify(item)


@content_bp.route("/admin/api/video-gallery", methods=["GET"])
@admin_required
def admin_get_video_gallery():
    items = query_db("SELECT * FROM video_gallery_items ORDER BY sort_order ASC, id ASC")
    return jsonify(items or [])


@content_bp.route("/admin/api/video-gallery", methods=["POST"])
@admin_required
def admin_create_video_gallery():
    data = request.get_json() or {}
    item = execute_db(
        """INSERT INTO video_gallery_items
              (title, description, video_url, thumbnail_url, sort_order)
           VALUES (%s, %s, %s, %s, %s) RETURNING *""",
        (data.get("title", ""), data.get("description", ""),
         data.get("video_url", ""), data.get("thumbnail_url", ""),
         data.get("sort_order", 0))
    )
    return jsonify(item), 201


@content_bp.route("/admin/api/video-gallery/<int:item_id>", methods=["PUT"])
@admin_required
def admin_update_video_gallery(item_id):
    data = request.get_json() or {}
    item = execute_db(
        """UPDATE video_gallery_items SET
             title = %s, description = %s, video_url = %s,
             thumbnail_url = %s, sort_order = %s
           WHERE id = %s RETURNING *""",
        (data.get("title", ""), data.get("description", ""),
         data.get("video_url", ""), data.get("thumbnail_url", ""),
         data.get("sort_order", 0), item_id)
    )
    if not item:
        return jsonify({"error": "Video not found"}), 404
    return jsonify(item)


@content_bp.route("/admin/api/video-gallery/<int:item_id>", methods=["DELETE"])
@admin_required
def admin_delete_video_gallery(item_id):
    count = execute_db("DELETE FROM video_gallery_items WHERE id = %s", (item_id,))
    if count == 0:
        return jsonify({"error": "Video not found"}), 404
    return jsonify({"success": True})


@content_bp.route("/admin/api/podcast", methods=["GET"])
@admin_required
def admin_get_podcast():
    items = query_db("SELECT * FROM podcast_episodes ORDER BY sort_order ASC, id ASC")
    return jsonify(items or [])


@content_bp.route("/admin/api/podcast", methods=["POST"])
@admin_required
def admin_create_podcast():
    data = request.get_json() or {}
    item = execute_db(
        """INSERT INTO podcast_episodes
              (title, description, audio_url, cover_image,
               episode_number, sort_order)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (data.get("title", ""), data.get("description", ""),
         data.get("audio_url", ""), data.get("cover_image", ""),
         data.get("episode_number") or None,
         data.get("sort_order", 0))
    )
    return jsonify(item), 201


@content_bp.route("/admin/api/podcast/<int:item_id>", methods=["PUT"])
@admin_required
def admin_update_podcast(item_id):
    data = request.get_json() or {}
    item = execute_db(
        """UPDATE podcast_episodes SET
             title = %s, description = %s, audio_url = %s,
             cover_image = %s, episode_number = %s, sort_order = %s
           WHERE id = %s RETURNING *""",
        (data.get("title", ""), data.get("description", ""),
         data.get("audio_url", ""), data.get("cover_image", ""),
         data.get("episode_number") or None,
         data.get("sort_order", 0), item_id)
    )
    if not item:
        return jsonify({"error": "Episode not found"}), 404
    return jsonify(item)


@content_bp.route("/admin/api/podcast/<int:item_id>", methods=["DELETE"])
@admin_required
def admin_delete_podcast(item_id):
    count = execute_db("DELETE FROM podcast_episodes WHERE id = %s", (item_id,))
    if count == 0:
        return jsonify({"error": "Episode not found"}), 404
    return jsonify({"success": True})


@content_bp.route("/admin/api/testimonials/<int:item_id>", methods=["DELETE"])
@admin_required
def admin_delete_testimonial(item_id):
    """DELETE /admin/api/testimonials/<id> — Remove a testimonial."""
    count = execute_db("DELETE FROM testimonials WHERE id = %s", (item_id,))
    if count == 0:
        return jsonify({"error": "Testimonial not found"}), 404
    return jsonify({"success": True})


# =============================================================
# ADMIN CRUD — TEAM MEMBERS
# =============================================================
# Manages team/staff member cards displayed on the public site.

@content_bp.route("/admin/api/team", methods=["GET"])
@admin_required
def admin_get_team():
    """GET all team members for the admin panel."""
    items = query_db("SELECT * FROM team_members ORDER BY sort_order ASC")
    return jsonify(items or [])


@content_bp.route("/admin/api/team", methods=["POST"])
@admin_required
def admin_create_team_member():
    """POST /admin/api/team — Create a new team member."""
    data = request.get_json()
    item = execute_db(
        """INSERT INTO team_members (name, title, bio, image_url, sort_order)
           VALUES (%s, %s, %s, %s, %s) RETURNING *""",
        (data.get("name", ""), data.get("title", ""),
         data.get("bio", ""), data.get("image_url", ""),
         data.get("sort_order", 0))
    )
    return jsonify(item), 201


@content_bp.route("/admin/api/team/<int:item_id>", methods=["PUT"])
@admin_required
def admin_update_team_member(item_id):
    """PUT /admin/api/team/<id> — Update a team member."""
    data = request.get_json()
    item = execute_db(
        """UPDATE team_members SET
             name = %s, title = %s, bio = %s,
             image_url = %s, sort_order = %s
           WHERE id = %s RETURNING *""",
        (data.get("name", ""), data.get("title", ""),
         data.get("bio", ""), data.get("image_url", ""),
         data.get("sort_order", 0), item_id)
    )
    if not item:
        return jsonify({"error": "Team member not found"}), 404
    return jsonify(item)


@content_bp.route("/admin/api/team/<int:item_id>", methods=["DELETE"])
@admin_required
def admin_delete_team_member(item_id):
    """DELETE /admin/api/team/<id> — Remove a team member."""
    count = execute_db("DELETE FROM team_members WHERE id = %s", (item_id,))
    if count == 0:
        return jsonify({"error": "Team member not found"}), 404
    return jsonify({"success": True})


# =============================================================
# ADMIN CRUD — FAQ
# =============================================================
# Manages frequently asked questions displayed on the public site.

@content_bp.route("/admin/api/faq", methods=["GET"])
@admin_required
def admin_get_faq():
    """GET all FAQ entries for the admin panel."""
    items = query_db("SELECT * FROM faqs ORDER BY sort_order ASC")
    return jsonify(items or [])


@content_bp.route("/admin/api/faq", methods=["POST"])
@admin_required
def admin_create_faq():
    """POST /admin/api/faq — Create a new FAQ entry."""
    data = request.get_json()
    item = execute_db(
        """INSERT INTO faqs (question, answer, sort_order)
           VALUES (%s, %s, %s) RETURNING *""",
        (data.get("question", ""), data.get("answer", ""),
         data.get("sort_order", 0))
    )
    return jsonify(item), 201


@content_bp.route("/admin/api/faq/<int:item_id>", methods=["PUT"])
@admin_required
def admin_update_faq(item_id):
    """PUT /admin/api/faq/<id> — Update a FAQ entry."""
    data = request.get_json()
    item = execute_db(
        """UPDATE faqs SET
             question = %s, answer = %s, sort_order = %s
           WHERE id = %s RETURNING *""",
        (data.get("question", ""), data.get("answer", ""),
         data.get("sort_order", 0), item_id)
    )
    if not item:
        return jsonify({"error": "FAQ not found"}), 404
    return jsonify(item)


@content_bp.route("/admin/api/faq/<int:item_id>", methods=["DELETE"])
@admin_required
def admin_delete_faq(item_id):
    """DELETE /admin/api/faq/<id> — Remove a FAQ entry."""
    count = execute_db("DELETE FROM faqs WHERE id = %s", (item_id,))
    if count == 0:
        return jsonify({"error": "FAQ not found"}), 404
    return jsonify({"success": True})

# ---- blog posts CRUD (Track B / B7, verbatim; uses re + datetime) ----

@content_bp.route("/admin/api/blog", methods=["GET"])
@admin_required
def admin_get_blog_posts():
    """
    GET /admin/api/blog
    Returns ALL blog posts (including drafts) for the admin panel,
    sorted by sort_order and then by created_at descending.
    """
    posts = query_db(
        "SELECT * FROM blog_posts ORDER BY sort_order ASC, created_at DESC"
    )
    return jsonify(posts or [])


@content_bp.route("/admin/api/blog", methods=["POST"])
@admin_required
def admin_create_blog_post():
    """
    POST /admin/api/blog
    Create a new blog post. Auto-generates slug from title if not provided.
    Sets published_at to NOW() if status is 'published'.
    """
    data = request.get_json()

    # Auto-generate slug from title if not provided
    slug = data.get("slug", "").strip()
    if not slug:
        slug = re.sub(r'[^a-z0-9]+', '-', data.get("title", "untitled").lower()).strip('-')

    # Set published_at timestamp when publishing
    published_at = None
    if data.get("status") == "published":
        published_at = datetime.now()

    post = execute_db(
        """INSERT INTO blog_posts
             (slug, title, subtitle, excerpt, content, cover_image,
              author, category, tags, status, seo_title, seo_description,
              published_at, sort_order)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           RETURNING *""",
        (
            slug,
            data.get("title", ""),
            data.get("subtitle", ""),
            data.get("excerpt", ""),
            data.get("content", ""),
            data.get("cover_image", ""),
            data.get("author", ""),
            data.get("category", ""),
            data.get("tags", ""),
            data.get("status", "draft"),
            data.get("seo_title", ""),
            data.get("seo_description", ""),
            published_at,
            data.get("sort_order", 0)
        )
    )
    return jsonify(post), 201


@content_bp.route("/admin/api/blog/<int:post_id>", methods=["PUT"])
@admin_required
def admin_update_blog_post(post_id):
    """
    PUT /admin/api/blog/<id>
    Update an existing blog post. If status changes to 'published'
    and published_at is not already set, it gets set to NOW().
    """
    data = request.get_json()

    # Check if this is a newly published post (needs published_at timestamp)
    existing = query_db(
        "SELECT status, published_at FROM blog_posts WHERE id = %s",
        (post_id,), fetchone=True
    )
    if not existing:
        return jsonify({"error": "Blog post not found"}), 404

    # Set published_at when first published, keep existing if re-saving
    published_at = existing.get("published_at")
    if data.get("status") == "published" and not published_at:
        published_at = datetime.now()

    post = execute_db(
        """UPDATE blog_posts SET
             slug = %s, title = %s, subtitle = %s, excerpt = %s,
             content = %s, cover_image = %s, author = %s, category = %s,
             tags = %s, status = %s, seo_title = %s, seo_description = %s,
             published_at = %s, sort_order = %s, updated_at = NOW()
           WHERE id = %s RETURNING *""",
        (
            data.get("slug", ""),
            data.get("title", ""),
            data.get("subtitle", ""),
            data.get("excerpt", ""),
            data.get("content", ""),
            data.get("cover_image", ""),
            data.get("author", ""),
            data.get("category", ""),
            data.get("tags", ""),
            data.get("status", "draft"),
            data.get("seo_title", ""),
            data.get("seo_description", ""),
            published_at,
            data.get("sort_order", 0),
            post_id
        )
    )
    if not post:
        return jsonify({"error": "Blog post not found"}), 404
    return jsonify(post)


@content_bp.route("/admin/api/blog/<int:post_id>", methods=["DELETE"])
@admin_required
def admin_delete_blog_post(post_id):
    """
    DELETE /admin/api/blog/<id>
    Permanently remove a blog post from the database.
    """
    count = execute_db("DELETE FROM blog_posts WHERE id = %s", (post_id,))
    if count == 0:
        return jsonify({"error": "Blog post not found"}), 404
    return jsonify({"success": True})

# ---- sphere-settings + sphere-images CRUD (Track B / B8, verbatim) ----

@content_bp.route("/admin/api/sphere-settings", methods=["GET"])
@admin_required
def admin_get_sphere_settings():
    settings = query_db("SELECT * FROM sphere_settings WHERE id = 1", fetchone=True)
    if not settings:
        return jsonify({"enabled": False})
    result = dict(settings)
    imgs = query_db("SELECT id, image_url, caption, sort_order FROM sphere_images ORDER BY sort_order ASC")
    result["custom_images"] = imgs or []
    return jsonify(result)


@content_bp.route("/admin/api/sphere-settings", methods=["PUT"])
@admin_required
def admin_update_sphere_settings():
    data = request.get_json(force=True)
    execute_db("""
        UPDATE sphere_settings SET
            enabled = %s,
            heading_text = %s,
            view_mode = %s,
            particle_count = %s,
            rotation_speed = %s,
            sphere_radius = %s,
            image_size = %s,
            image_source = %s,
            position_randomness = %s,
            particle_opacity = %s,
            zoom_min = %s,
            zoom_max = %s,
            card_scale = %s,
            card_gap = %s,
            updated_at = NOW()
        WHERE id = 1
    """, (
        data.get("enabled", False),
        data.get("heading_text", ""),
        data.get("view_mode", "sections"),
        int(data.get("particle_count", 1500)),
        float(data.get("rotation_speed", 0.0005)),
        float(data.get("sphere_radius", 9)),
        float(data.get("image_size", 1.5)),
        data.get("image_source", "gallery"),
        float(data.get("position_randomness", 4)),
        float(data.get("particle_opacity", 1)),
        float(data.get("zoom_min", 5)),
        float(data.get("zoom_max", 30)),
        float(data.get("card_scale", 1.0)),
        float(data.get("card_gap", 2.5)),
    ))
    return jsonify({"status": "ok"})


@content_bp.route("/admin/api/sphere-settings/enabled", methods=["PATCH"])
@admin_required
def admin_patch_sphere_enabled():
    """Lightweight toggle endpoint — flips just the `enabled` flag so the
    admin checkbox can auto-save without rewriting every other field."""
    data = request.get_json(force=True) or {}
    enabled = bool(data.get("enabled", False))
    execute_db("UPDATE sphere_settings SET enabled = %s, updated_at = NOW() WHERE id = 1", (enabled,))
    return jsonify({"status": "ok", "enabled": enabled})


@content_bp.route("/admin/api/sphere-images", methods=["GET"])
@admin_required
def admin_get_sphere_images():
    imgs = query_db("SELECT * FROM sphere_images ORDER BY sort_order ASC")
    return jsonify(imgs or [])


@content_bp.route("/admin/api/sphere-images", methods=["POST"])
@admin_required
def admin_create_sphere_image():
    data = request.get_json(force=True)
    max_order = query_db("SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM sphere_images", fetchone=True)
    next_order = max_order["next_order"] if max_order else 0
    execute_db(
        "INSERT INTO sphere_images (image_url, caption, sort_order) VALUES (%s, %s, %s)",
        (data.get("image_url", ""), data.get("caption", ""), next_order)
    )
    return jsonify({"status": "ok"})


@content_bp.route("/admin/api/sphere-images/<int:img_id>", methods=["DELETE"])
@admin_required
def admin_delete_sphere_image(img_id):
    execute_db("DELETE FROM sphere_images WHERE id = %s", (img_id,))
    return jsonify({"status": "ok"})


# ---- reorder helpers: batch sort_order updates (Track B / B10, verbatim) ----

@content_bp.route("/admin/api/reorder/<string:content_type>", methods=["PUT"])
@admin_required
def admin_reorder(content_type):
    """PUT /admin/api/reorder/<type> — Batch-update sort_order for a content type."""
    table_map = {
        "gallery-cards": "gallery_cards",
        "experiences": "experiences",
        "pricing": "pricing_seasons",
        "testimonials": "testimonials",
        "team": "team_members",
        "faq": "faqs",
        "page-sections": "page_sections",
        "custom-section-items": "custom_section_items",
        "blog-posts": "blog_posts",
        "page-views": "page_views"
    }
    table = table_map.get(content_type)
    if not table:
        return jsonify({"error": "Invalid content type"}), 400

    items = request.get_json()
    if not isinstance(items, list):
        return jsonify({"error": "Expected array of {id, sort_order}"}), 400

    # Tables that have an updated_at column get it refreshed on reorder
    tables_with_updated_at = {"gallery_cards", "experiences", "pricing_seasons"}

    conn = get_db()
    try:
        with conn.cursor() as cur:
            for item in items:
                if table in tables_with_updated_at:
                    cur.execute(
                        f"UPDATE {table} SET sort_order = %s, updated_at = NOW() WHERE id = %s",
                        (item["sort_order"], item["id"])
                    )
                else:
                    cur.execute(
                        f"UPDATE {table} SET sort_order = %s WHERE id = %s",
                        (item["sort_order"], item["id"])
                    )
    finally:
        conn.close()

    return jsonify({"success": True})


@content_bp.route("/admin/api/reorder/sphere-images", methods=["PUT"])
@admin_required
def admin_reorder_sphere_images():
    data = request.get_json(force=True)
    ids = data.get("ids", [])
    for i, img_id in enumerate(ids):
        execute_db("UPDATE sphere_images SET sort_order = %s WHERE id = %s", (i, img_id))
    return jsonify({"status": "ok"})


# ---- social-links + section-visibility toggles (Track B / B11, verbatim) ----

@content_bp.route("/admin/api/social-links", methods=["GET"])
@admin_required
def admin_get_social_links():
    """GET social media links for the admin panel."""
    info = query_db("SELECT social_links FROM site_settings WHERE id = 1", fetchone=True)
    return jsonify(info.get("social_links", {}) if info else {})


@content_bp.route("/admin/api/social-links", methods=["PUT"])
@admin_required
def admin_update_social_links():
    """PUT /admin/api/social-links — Update social media profile URLs."""
    data = request.get_json()
    execute_db(
        "UPDATE site_settings SET social_links = %s::jsonb, updated_at = NOW() WHERE id = 1",
        (json.dumps(data),)
    )
    return jsonify(data)


@content_bp.route("/admin/api/section-visibility", methods=["GET"])
@admin_required
def admin_get_section_visibility():
    """GET section visibility toggles + landing scroll mode for the admin panel."""
    info = query_db("""
        SELECT section_testimonials, section_team, section_faq, section_footer,
               scroll_mode
        FROM site_settings WHERE id = 1
    """, fetchone=True)
    return jsonify(info or {})


@content_bp.route("/admin/api/section-visibility", methods=["PUT"])
@admin_required
def admin_update_section_visibility():
    """PUT /admin/api/section-visibility — Toggle sections on/off and pick scroll mode."""
    data = request.get_json()
    # Whitelist scroll_mode to the two values the frontend knows how to honor;
    # anything else falls back to 'snap' so a typo in the request can't put the
    # site into an undefined state.
    scroll_mode = data.get("scroll_mode", "snap")
    if scroll_mode not in ("snap", "smooth"):
        scroll_mode = "snap"
    info = execute_db(
        """UPDATE site_settings SET
             section_testimonials = %s, section_team = %s,
             section_faq = %s, section_footer = %s,
             scroll_mode = %s,
             updated_at = NOW()
           WHERE id = 1 RETURNING
             section_testimonials, section_team, section_faq, section_footer,
             scroll_mode""",
        (data.get("section_testimonials", False), data.get("section_team", False),
         data.get("section_faq", False), data.get("section_footer", True),
         scroll_mode)
    )
    return jsonify(info or {})


# ---- custom-section items + SEO settings CRUD (Track B / B12, verbatim) ----

@content_bp.route("/admin/api/custom-sections/<int:section_id>/items", methods=["GET"])
@admin_required
def admin_get_custom_items(section_id):
    """GET all items for a specific custom section."""
    items = query_db(
        "SELECT * FROM custom_section_items WHERE section_id = %s ORDER BY sort_order ASC",
        (section_id,)
    )
    return jsonify(items or [])


@content_bp.route("/admin/api/custom-sections/<int:section_id>/items", methods=["POST"])
@admin_required
def admin_create_custom_item(section_id):
    """POST /admin/api/custom-sections/<section_id>/items — Add an item to a custom section."""
    data = request.get_json()
    item = execute_db(
        """INSERT INTO custom_section_items
           (section_id, title, subtitle, content, image_url, link_url, link_text, icon, sort_order, extra_data)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) RETURNING *""",
        (section_id, data.get("title", ""), data.get("subtitle", ""),
         data.get("content", ""), data.get("image_url", ""),
         data.get("link_url", ""), data.get("link_text", ""),
         data.get("icon", ""), data.get("sort_order", 0),
         json.dumps(data.get("extra_data", {})))
    )
    return jsonify(item), 201


@content_bp.route("/admin/api/custom-sections/<int:section_id>/items/<int:item_id>", methods=["PUT"])
@admin_required
def admin_update_custom_item(section_id, item_id):
    """PUT /admin/api/custom-sections/<section_id>/items/<item_id> — Update an item."""
    data = request.get_json()
    item = execute_db(
        """UPDATE custom_section_items SET
             title = %s, subtitle = %s, content = %s, image_url = %s,
             link_url = %s, link_text = %s, icon = %s, sort_order = %s,
             extra_data = %s::jsonb
           WHERE id = %s AND section_id = %s RETURNING *""",
        (data.get("title", ""), data.get("subtitle", ""),
         data.get("content", ""), data.get("image_url", ""),
         data.get("link_url", ""), data.get("link_text", ""),
         data.get("icon", ""), data.get("sort_order", 0),
         json.dumps(data.get("extra_data", {})), item_id, section_id)
    )
    if not item:
        return jsonify({"error": "Item not found"}), 404
    return jsonify(item)


@content_bp.route("/admin/api/custom-sections/<int:section_id>/items/<int:item_id>", methods=["DELETE"])
@admin_required
def admin_delete_custom_item(section_id, item_id):
    """DELETE /admin/api/custom-sections/<section_id>/items/<item_id> — Remove an item."""
    count = execute_db(
        "DELETE FROM custom_section_items WHERE id = %s AND section_id = %s",
        (item_id, section_id)
    )
    if count == 0:
        return jsonify({"error": "Item not found"}), 404
    return jsonify({"success": True})


@content_bp.route("/admin/api/seo", methods=["GET"])
@admin_required
def admin_get_seo():
    """
    GET /admin/api/seo
    Returns the current SEO settings for the admin panel.
    """
    settings = query_db("""
        SELECT seo_meta_title, seo_meta_description, seo_keywords,
               seo_og_image, seo_twitter_handle, seo_canonical_url, seo_robots
        FROM site_settings WHERE id = 1
    """, fetchone=True)
    return jsonify(settings or {})


@content_bp.route("/admin/api/seo", methods=["PUT"])
@admin_required
def admin_update_seo():
    """
    PUT /admin/api/seo
    Update SEO settings (meta title, description, keywords, OG image,
    Twitter handle, canonical URL, robots directive).
    """
    data = request.get_json()
    result = execute_db(
        """UPDATE site_settings SET
             seo_meta_title = %s, seo_meta_description = %s,
             seo_keywords = %s, seo_og_image = %s,
             seo_twitter_handle = %s, seo_canonical_url = %s,
             seo_robots = %s, updated_at = NOW()
           WHERE id = 1 RETURNING
             seo_meta_title, seo_meta_description, seo_keywords,
             seo_og_image, seo_twitter_handle, seo_canonical_url, seo_robots""",
        (
            data.get("seo_meta_title", ""),
            data.get("seo_meta_description", ""),
            data.get("seo_keywords", ""),
            data.get("seo_og_image", ""),
            data.get("seo_twitter_handle", ""),
            data.get("seo_canonical_url", ""),
            data.get("seo_robots", "index, follow")
        )
    )
    return jsonify(result or {})
