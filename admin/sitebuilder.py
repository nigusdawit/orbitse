"""admin/sitebuilder.py - admin CRUD routes for the site builder, as a Flask blueprint.

Part of the app.py de-monolith (Track B), mirroring admin/content.py. This blueprint
owns the page-section primitives the dashboard's "Site Builder" tab edits: the
built-in + custom section rows (page_sections) plus their per-section settings, SEO
overrides, background image, and Section-Menu link target.

All routes are gated by @admin_required (from core) and do CRUD via query_db/execute_db
(also from core). URLs keep their absolute /admin/api/* paths, so the route table is
unchanged - only the Flask endpoint name gains a "sitebuilder." prefix (admin JS calls
these by URL, not url_for). CSRF / feature-flag enforcement runs in app.py's global
before_request hooks, which apply to blueprint routes too, so nothing extra is needed.

The nav-link-target validator (_validate_nav_link_target + its scheme allowlist) is a
SECURITY helper - it rejects javascript:/data: and protocol-relative links so the value
can be written verbatim into an <a href> by the public renderer without stored-XSS risk.
It has exactly one caller (the page-section PUT below) and no other app.py call site, so
it was moved here verbatim with that route - kept byte-for-byte to preserve the exact
allow/deny boundary. It is a pure leaf (str ops + the constant tuple only).

The standalone /admin/api/pages CRUD (+ its _serialize_page hydrator) now lives here
too (Track B / task 078, piece #3). It was previously held back in app.py because it
depended on the module-level _slugify, which had three colliding same-named definitions;
that collision has since been resolved (the two dead defs removed) and the surviving
_slugify moved to core, so these routes import it cleanly here. A page is a row in
`pages` that reuses page_sections via the page_section_assignments join table, which is
why this CRUD belongs alongside the section primitives above.

Registered in app.py via app.register_blueprint(sitebuilder_bp), after commerce_bp.
Imports come from core (never app - that would be circular).
"""
import json
import re
import sys

from flask import Blueprint, request, jsonify

from core import query_db, execute_db, get_db, admin_required, _slugify, capture_exc

sitebuilder_bp = Blueprint("sitebuilder", __name__)


@sitebuilder_bp.route("/admin/api/page-sections", methods=["GET"])
@admin_required
def admin_get_page_sections():
    """GET all page sections (built-in + custom) for the admin panel."""
    sections = query_db("SELECT * FROM page_sections ORDER BY sort_order ASC")
    return jsonify(sections or [])


@sitebuilder_bp.route("/admin/api/page-sections", methods=["POST"])
@admin_required
def admin_create_page_section():
    """POST /admin/api/page-sections — Create a new custom section."""
    data = request.get_json()
    slug = data.get("slug", "").strip().lower()
    slug = re.sub(r'[^a-z0-9-]', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    if not slug:
        return jsonify({"error": "Slug is required"}), 400

    # Get the next sort_order (add to the end, before footer)
    max_order = query_db(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 as next_order FROM page_sections",
        fetchone=True
    )
    next_order = max_order["next_order"] if max_order else 0

    item = execute_db(
        """INSERT INTO page_sections (slug, title, section_type, template, sort_order, enabled, settings)
           VALUES (%s, %s, 'custom', %s, %s, %s, %s::jsonb) RETURNING *""",
        (slug, data.get("title", "New Section"),
         data.get("template", "cards_grid"), next_order,
         data.get("enabled", True), json.dumps(data.get("settings", {})))
    )
    return jsonify(item), 201


@sitebuilder_bp.route("/admin/api/page-sections/<int:section_id>", methods=["PUT"])
@admin_required
def admin_update_page_section(section_id):
    """PUT /admin/api/page-sections/<id> — Update a section's title, subtitle,
    enabled flag, and settings.

    The optional subtitle is used by some custom-section templates as a small
    free-text "where to look" pointer (the rsvp_form template, for example,
    stashes the event slug here so the admin doesn't need a whole settings
    panel just to pick which event to show).

    Only the fields actually present in the request body are touched —
    callers that only want to flip `enabled` or rename `title` shouldn't
    have to round-trip the rest. We build the SET clause dynamically and
    fall back to the existing row for any omitted field so the UPDATE is
    safe even when called from older clients.
    """
    data = request.get_json() or {}

    existing = query_db(
        "SELECT title, subtitle, enabled, settings, bg_image, bg_overlay_alpha, "
        "nav_link_target, seo_title, seo_description, seo_image "
        "FROM page_sections WHERE id = %s",
        (section_id,), fetchone=True
    )
    if not existing:
        return jsonify({"error": "Section not found"}), 404

    title    = data["title"]    if "title"    in data else (existing.get("title") or "")
    subtitle = data["subtitle"] if "subtitle" in data else (existing.get("subtitle") or "")
    enabled  = data["enabled"]  if "enabled"  in data else bool(existing.get("enabled"))
    settings = data["settings"] if "settings" in data else (existing.get("settings") or {})
    bg_image = data["bg_image"] if "bg_image" in data else (existing.get("bg_image") or "")
    # Per-section SEO overrides (Task #69). Trim and coerce to string;
    # empty strings are allowed and explicitly mean "fall back to the
    # site-wide cascade in _build_seo_meta_html". We don't validate
    # that seo_image is a real URL — admins paste both /uploads/<hex>.jpg
    # internal paths and absolute https:// URLs (e.g. CDN-hosted assets)
    # here, both of which are legitimate as og:image values.
    def _seo_field(key):
        if key in data:
            return str(data.get(key) or "").strip()
        return str(existing.get(key) or "").strip()
    seo_title       = _seo_field("seo_title")
    seo_description = _seo_field("seo_description")
    seo_image       = _seo_field("seo_image")
    # Section Menu link override — empty = same-page anchor (default
    # behaviour); any non-empty value is used verbatim as the menu
    # entry's href, typically "/p/<slug>" to send the menu at a
    # standalone page. We restrict to safe schemes (no `javascript:`
    # / `data:`) to avoid stored XSS via an admin-supplied link
    # clicked by every visitor.
    if "nav_link_target" in data:
        try:
            nav_link_target = _validate_nav_link_target(data["nav_link_target"])
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    else:
        nav_link_target = (existing.get("nav_link_target") or "")
    # Clamp overlay alpha to a sane range — a stray slider value at 1.0
    # blacks the photo out entirely; <0 produces an invalid CSS color.
    if "bg_overlay_alpha" in data:
        try:
            bg_overlay_alpha = max(0.0, min(1.0, float(data["bg_overlay_alpha"])))
        except (TypeError, ValueError):
            bg_overlay_alpha = float(existing.get("bg_overlay_alpha") or 0.45)
    else:
        bg_overlay_alpha = float(existing.get("bg_overlay_alpha") or 0.45)

    item = execute_db(
        """UPDATE page_sections SET
             title = %s, subtitle = %s, enabled = %s, settings = %s::jsonb,
             bg_image = %s, bg_overlay_alpha = %s, nav_link_target = %s,
             seo_title = %s, seo_description = %s, seo_image = %s
           WHERE id = %s RETURNING *""",
        (title, subtitle, enabled, json.dumps(settings),
         bg_image, bg_overlay_alpha, nav_link_target,
         seo_title, seo_description, seo_image, section_id)
    )
    if not item:
        return jsonify({"error": "Section not found"}), 404
    return jsonify(item)


@sitebuilder_bp.route("/admin/api/page-sections/<int:section_id>", methods=["DELETE"])
@admin_required
def admin_delete_page_section(section_id):
    """DELETE /admin/api/page-sections/<id> — Delete a custom section (built-in protected)."""
    section = query_db("SELECT * FROM page_sections WHERE id = %s", (section_id,), fetchone=True)
    if not section:
        return jsonify({"error": "Section not found"}), 404
    if section.get("section_type") == "built_in":
        return jsonify({"error": "Cannot delete built-in sections"}), 400
    execute_db("DELETE FROM page_sections WHERE id = %s", (section_id,))
    return jsonify({"success": True})


@sitebuilder_bp.route("/admin/api/page-sections/<int:section_id>/toggle", methods=["PUT"])
@admin_required
def admin_toggle_page_section(section_id):
    """PUT /admin/api/page-sections/<id>/toggle — Quick toggle enabled/disabled."""
    data = request.get_json()
    enabled = data.get("enabled", True)
    item = execute_db(
        "UPDATE page_sections SET enabled = %s WHERE id = %s RETURNING *",
        (enabled, section_id)
    )
    if not item:
        return jsonify({"error": "Section not found"}), 404

    # Sync the old section_testimonials/team/faq/footer toggles in site_settings
    # so existing code that reads those columns stays in sync
    section = query_db("SELECT slug FROM page_sections WHERE id = %s", (section_id,), fetchone=True)
    if section:
        toggle_map = {
            "testimonials": "section_testimonials",
            "team": "section_team",
            "faq": "section_faq",
            "footer": "section_footer"
        }
        col = toggle_map.get(section["slug"])
        if col:
            execute_db(
                f"UPDATE site_settings SET {col} = %s WHERE id = 1",
                (enabled,)
            )

    return jsonify(item)


# Allowlist of URL schemes acceptable as a `page_sections.nav_link_target`.
# Anything else (notably `javascript:` and `data:`) is rejected to prevent
# stored XSS via an admin-supplied menu link clicked by every visitor.
_NAV_LINK_TARGET_ALLOWED_SCHEMES = ("http://", "https://", "mailto:", "tel:")


def _validate_nav_link_target(raw):
    """Return a sanitised `nav_link_target` value, or raise ValueError.

    Empty string is the disabled state and always passes through.
    Otherwise we only accept:
      - relative paths starting with "/" (e.g. "/p/about")
      - same-page anchors starting with "#"
      - absolute URLs using an allowlisted scheme above
    Dangerous schemes (`javascript:`, `data:`, `vbscript:`, etc.) are
    rejected so the value can be safely written verbatim into an <a>
    tag's href attribute by the admin UI / public renderer.
    """
    if raw is None:
        return ""
    val = str(raw).strip()
    if not val:
        return ""
    # Protocol-relative URLs ("//evil.example/x") and Windows-style
    # backslash paths ("\\evil.example") are treated as cross-origin
    # navigations by browsers — reject them so a "/"-prefixed value
    # is guaranteed to be a same-origin internal path.
    if val.startswith("//") or val.startswith("\\"):
        raise ValueError(
            "Menu link target must not start with '//' or '\\' "
            "(use a full https:// URL instead)."
        )
    if val[0] in ("/", "#"):
        return val
    lowered = val.lower()
    for scheme in _NAV_LINK_TARGET_ALLOWED_SCHEMES:
        if lowered.startswith(scheme):
            return val
    raise ValueError(
        "Menu link target must be a relative path (/...), an anchor (#...), "
        "or an http(s)://, mailto:, or tel: URL."
    )


# ---- standalone pages CRUD (Track B / task 078, piece #3, moved from app.py) ----
# A page (pages row) reuses page_sections via the page_section_assignments join
# table. _serialize_page hydrates a page row with its ordered section_ids. The
# /sections PUT does an atomic delete-all-then-insert under one pooled connection.
# _slugify (canonical, from core) generates slugs; note it never returns "", so the
# `if not slug` guards below only fire when a caller passes a slug that slugifies
# to empty AFTER a non-empty input cannot happen - kept verbatim for behavior parity.

def _serialize_page(page_row):
    """Hydrate a pages row with its assigned section_ids (in render
    order) so the admin UI can show + reorder them in a single round
    trip. Used by every endpoint that returns a page object."""
    if not page_row:
        return None
    out = dict(page_row)
    rows = query_db(
        "SELECT section_id FROM page_section_assignments "
        "WHERE page_id = %s ORDER BY sort_order ASC, id ASC",
        (page_row["id"],),
    ) or []
    out["section_ids"] = [r["section_id"] for r in rows]
    return out


@sitebuilder_bp.route("/admin/api/pages", methods=["GET"])
@admin_required
def admin_list_pages():
    """GET all standalone pages with their assigned section_ids."""
    rows = query_db("SELECT * FROM pages ORDER BY sort_order ASC, id ASC") or []
    return jsonify([_serialize_page(r) for r in rows])


@sitebuilder_bp.route("/admin/api/pages", methods=["POST"])
@admin_required
def admin_create_page():
    """POST /admin/api/pages — Create a standalone page."""
    data = request.get_json() or {}
    slug = _slugify(data.get("slug", ""))
    if not slug:
        return jsonify({"error": "Slug is required"}), 400
    title = (data.get("title") or "").strip() or slug.replace("-", " ").title()
    meta = (data.get("meta_description") or "").strip()
    enabled = bool(data.get("enabled", True))
    # Reject duplicates with a friendly 409 instead of leaking the
    # underlying psycopg2 UNIQUE-constraint exception.
    existing = query_db(
        "SELECT id FROM pages WHERE slug = %s", (slug,), fetchone=True
    )
    if existing:
        return jsonify({"error": "A page with that slug already exists."}), 409
    next_order = (query_db(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM pages",
        fetchone=True,
    ) or {}).get("n", 0)
    page = execute_db(
        """INSERT INTO pages (slug, title, meta_description, sort_order, enabled)
           VALUES (%s, %s, %s, %s, %s) RETURNING *""",
        (slug, title, meta, next_order, enabled),
    )
    return jsonify(_serialize_page(page)), 201


@sitebuilder_bp.route("/admin/api/pages/<int:page_id>", methods=["GET"])
@admin_required
def admin_get_page(page_id):
    """GET /admin/api/pages/<id> — single page with its section_ids."""
    page = query_db("SELECT * FROM pages WHERE id = %s", (page_id,), fetchone=True)
    if not page:
        return jsonify({"error": "Page not found"}), 404
    return jsonify(_serialize_page(page))


@sitebuilder_bp.route("/admin/api/pages/<int:page_id>", methods=["PUT", "PATCH"])
@admin_required
def admin_update_page(page_id):
    """PUT/PATCH /admin/api/pages/<id> — Update slug, title, meta,
    enabled. Only fields actually sent in the body are updated; section
    assignment is managed by the dedicated /sections endpoint below."""
    data = request.get_json() or {}
    existing = query_db(
        "SELECT slug, title, meta_description, sort_order, enabled "
        "FROM pages WHERE id = %s", (page_id,), fetchone=True,
    )
    if not existing:
        return jsonify({"error": "Page not found"}), 404
    slug = existing["slug"]
    if "slug" in data:
        new_slug = _slugify(data["slug"])
        if not new_slug:
            return jsonify({"error": "Slug cannot be empty"}), 400
        if new_slug != slug:
            clash = query_db(
                "SELECT id FROM pages WHERE slug = %s AND id <> %s",
                (new_slug, page_id), fetchone=True,
            )
            if clash:
                return jsonify({"error": "A page with that slug already exists."}), 409
            slug = new_slug
    title    = (data["title"] if "title" in data else existing.get("title")) or ""
    meta     = (data["meta_description"] if "meta_description" in data
                else existing.get("meta_description")) or ""
    enabled  = bool(data["enabled"]) if "enabled" in data else bool(existing.get("enabled"))
    sort_ord = int(data["sort_order"]) if "sort_order" in data else int(existing.get("sort_order") or 0)
    page = execute_db(
        """UPDATE pages SET
             slug = %s, title = %s, meta_description = %s,
             sort_order = %s, enabled = %s, updated_at = NOW()
           WHERE id = %s RETURNING *""",
        (slug, title, meta, sort_ord, enabled, page_id),
    )
    if not page:
        return jsonify({"error": "Page not found"}), 404
    return jsonify(_serialize_page(page))


@sitebuilder_bp.route("/admin/api/pages/<int:page_id>", methods=["DELETE"])
@admin_required
def admin_delete_page(page_id):
    """DELETE /admin/api/pages/<id>. Cascade on the join table drops
    every section assignment automatically — sections themselves are
    not touched (they're shared with the homepage)."""
    count = execute_db("DELETE FROM pages WHERE id = %s", (page_id,))
    if count == 0:
        return jsonify({"error": "Page not found"}), 404
    return jsonify({"success": True})


@sitebuilder_bp.route("/admin/api/pages/<int:page_id>/sections", methods=["PUT"])
@admin_required
def admin_set_page_sections(page_id):
    """PUT /admin/api/pages/<id>/sections — Replace the page's section
    assignment list in one shot. Body: {"section_ids": [3, 1, 7]}.
    Order in the array IS the render order (sort_order is assigned
    sequentially). Replaces atomically (delete-all-then-insert) so the
    admin UI doesn't have to do per-row diffing."""
    page = query_db("SELECT id FROM pages WHERE id = %s", (page_id,), fetchone=True)
    if not page:
        return jsonify({"error": "Page not found"}), 404
    data = request.get_json() or {}
    raw_ids = data.get("section_ids") or []
    if not isinstance(raw_ids, list):
        return jsonify({"error": "section_ids must be an array"}), 400
    # Validate every section exists, dedupe while preserving order so
    # the admin can't accidentally double-render a section by clicking
    # twice in the picker.
    seen, section_ids = set(), []
    for sid in raw_ids:
        try:
            sid_i = int(sid)
        except (TypeError, ValueError):
            return jsonify({"error": f"Invalid section id: {sid!r}"}), 400
        if sid_i in seen:
            continue
        seen.add(sid_i)
        section_ids.append(sid_i)
    if section_ids:
        existing_rows = query_db(
            "SELECT id FROM page_sections WHERE id = ANY(%s)", (section_ids,)
        ) or []
        existing_ids = {r["id"] for r in existing_rows}
        unknown = [sid for sid in section_ids if sid not in existing_ids]
        if unknown:
            return jsonify({"error": f"Unknown section ids: {unknown}"}), 400
    # Atomic replace — borrow a single pooled connection, flip out of
    # autocommit so the DELETE + N INSERTs land together, COMMIT on
    # success, ROLLBACK on any failure. Without this a crash mid-loop
    # (or a concurrent writer) could leave the page with partial /
    # empty assignments and a confused admin UI.
    conn = get_db()
    try:
        try:
            conn.autocommit = False
        except Exception:
            pass
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM page_section_assignments WHERE page_id = %s",
                (page_id,),
            )
            if section_ids:
                # executemany is fine here — N is bounded by the number
                # of page_sections rows the admin has, typically <30.
                cur.executemany(
                    "INSERT INTO page_section_assignments "
                    "(page_id, section_id, sort_order) VALUES (%s, %s, %s)",
                    [(page_id, sid, idx) for idx, sid in enumerate(section_ids)],
                )
        conn.commit()
    except Exception as e:
        capture_exc(e, "sitebuilder.admin_set_page_sections")
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[admin_set_page_sections] failed for page {page_id}: {e}",
              file=sys.stderr)
        return jsonify({"error": "Failed to save section assignments"}), 500
    finally:
        try:
            conn.autocommit = True
        except Exception:
            pass
        conn.close()
    page_full = query_db("SELECT * FROM pages WHERE id = %s", (page_id,), fetchone=True)
    return jsonify(_serialize_page(page_full))
