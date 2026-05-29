"""
admin_ai_platform.blueprints.content
=====================================

Minimal admin CRUD for the AI-referenced content the kit otherwise omits (M13).

The public-site *editors* for this content were intentionally dropped (per the
extraction boundary), but the data + a thin admin CRUD are kept so an operator
can populate what the visitor AI looks up (`lookup_experiences`, `lookup_faq`,
`lookup_blog`, etc.). There are NO public read routes here — the chat lookup
tools are the read surface.

A single registry (`_RESOURCES`) drives generic list/create/update/delete with a
per-resource **column allowlist** (so a client can't set arbitrary columns) and
explicit JSONB handling. ``business_info`` is a singleton (GET/PUT only).

  * ``GET/POST   /admin/api/content/<resource>``
  * ``PUT/DELETE /admin/api/content/<resource>/<id>``
  * ``GET/PUT    /admin/api/content/business-info``   (singleton)
"""

from __future__ import annotations

import json

from flask import Blueprint, request, jsonify

from ..db import query_db, execute_db
from ..auth import admin_required

bp = Blueprint("content", __name__)

# resource -> {table, cols (scalar allowlist), json_cols, slug (unique col or None)}
_RESOURCES = {
    "experiences": {"table": "experiences",
                    "cols": ["name", "description", "icon", "sort_order"]},
    "pricing-seasons": {"table": "pricing_seasons",
                        "cols": ["label", "date_range", "price_range", "sort_order"]},
    "testimonials": {"table": "testimonials",
                     "cols": ["reviewer_name", "reviewer_role", "content", "rating",
                              "image_url", "sort_order"]},
    "team": {"table": "team_members",
             "cols": ["name", "title", "bio", "image_url", "sort_order"]},
    "faqs": {"table": "faqs", "cols": ["question", "answer", "sort_order"]},
    "blog": {"table": "blog_posts",
             "cols": ["title", "subtitle", "excerpt", "content", "cover_image", "author",
                      "category", "tags", "status", "seo_title", "seo_description",
                      "sort_order"],
             "slug": "slug"},
    "custom-items": {"table": "custom_section_items",
                     "cols": ["section_slug", "title", "subtitle", "content", "image_url",
                              "link_url", "link_text", "icon", "sort_order"],
                     "json_cols": ["extra_data"]},
}


def _spec(resource):
    return _RESOURCES.get(resource)


@bp.route("/admin/api/content/<resource>", methods=["GET"])
@admin_required
def list_items(resource):
    spec = _spec(resource)
    if not spec:
        return jsonify({"error": "unknown resource"}), 404
    rows = query_db(f"SELECT * FROM {spec['table']} ORDER BY sort_order, id") or []
    return jsonify({"items": rows})


@bp.route("/admin/api/content/<resource>", methods=["POST"])
@admin_required
def create_item(resource):
    spec = _spec(resource)
    if not spec:
        return jsonify({"error": "unknown resource"}), 404
    d = request.get_json() or {}
    cols, vals, placeholders = [], [], []
    # Unique slug (blog) is required on create.
    if spec.get("slug"):
        sval = (d.get(spec["slug"]) or "").strip()
        if not sval:
            return jsonify({"error": f"{spec['slug']} required"}), 400
        cols.append(spec["slug"])
        vals.append(sval)
        placeholders.append("%s")
    for c in spec["cols"]:
        if c in d:
            cols.append(c)
            vals.append(d[c])
            placeholders.append("%s")
    for jc in spec.get("json_cols", []):
        if jc in d:
            cols.append(jc)
            vals.append(json.dumps(d[jc]))
            placeholders.append("%s::jsonb")
    if not cols:
        return jsonify({"error": "no fields"}), 400
    conflict = (f" ON CONFLICT ({spec['slug']}) DO NOTHING" if spec.get("slug") else "")
    row = execute_db(
        f"INSERT INTO {spec['table']} ({', '.join(cols)}) "
        f"VALUES ({', '.join(placeholders)}){conflict} RETURNING *", tuple(vals))
    if not row:
        return jsonify({"error": "conflict (slug exists)"}), 409
    return jsonify(row), 201


@bp.route("/admin/api/content/<resource>/<int:item_id>", methods=["PUT"])
@admin_required
def update_item(resource, item_id):
    spec = _spec(resource)
    if not spec:
        return jsonify({"error": "unknown resource"}), 404
    d = request.get_json() or {}
    sets, vals = [], []
    editable = list(spec["cols"]) + ([spec["slug"]] if spec.get("slug") else [])
    for c in editable:
        if c in d:
            sets.append(f"{c}=%s")
            vals.append(d[c])
    for jc in spec.get("json_cols", []):
        if jc in d:
            sets.append(f"{jc}=%s::jsonb")
            vals.append(json.dumps(d[jc]))
    if not sets:
        return jsonify({"error": "no fields"}), 400
    vals.append(item_id)
    row = execute_db(f"UPDATE {spec['table']} SET {', '.join(sets)} WHERE id=%s RETURNING *",
                     tuple(vals))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/content/<resource>/<int:item_id>", methods=["DELETE"])
@admin_required
def delete_item(resource, item_id):
    spec = _spec(resource)
    if not spec:
        return jsonify({"error": "unknown resource"}), 404
    execute_db(f"DELETE FROM {spec['table']} WHERE id=%s", (item_id,))
    return jsonify({"success": True})


# ---- business_info singleton -------------------------------------------
_BIZ_SCALAR = ("name", "tagline", "about", "phone", "email", "address")
_BIZ_JSON = ("hours", "social")


@bp.route("/admin/api/content/business-info", methods=["GET"])
@admin_required
def get_business_info():
    return jsonify(query_db("SELECT * FROM business_info WHERE id=1", fetchone=True) or {})


@bp.route("/admin/api/content/business-info", methods=["PUT"])
@admin_required
def put_business_info():
    d = request.get_json() or {}
    sets, vals = [], []
    for c in _BIZ_SCALAR:
        if c in d:
            sets.append(f"{c}=%s")
            vals.append(d[c])
    for jc in _BIZ_JSON:
        if jc in d:
            sets.append(f"{jc}=%s::jsonb")
            vals.append(json.dumps(d[jc]))
    if not sets:
        return jsonify({"error": "no fields"}), 400
    sets.append("updated_at=NOW()")
    execute_db("INSERT INTO business_info (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    row = execute_db(f"UPDATE business_info SET {', '.join(sets)} WHERE id=1 RETURNING *",
                     tuple(vals))
    return jsonify(row)
