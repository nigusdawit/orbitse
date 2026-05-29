"""
admin_ai_platform.blueprints.forms
==================================

Dynamic forms: public schema read + submit + partial (abandon-capture) save,
plus minimal admin list/submissions. The AI fills these conversationally via
the ``submitForm`` / ``partialFormSave`` commands.

Routes:
  * ``GET  /api/forms/<slug>``           — public form schema (fields) for rendering
  * ``POST /api/forms/<slug>/submit``    — submit (validates required, conf #)
  * ``POST /api/forms/<slug>/partial``   — auto-save partial by session_id
  * ``GET  /admin/api/forms``            — admin list w/ counts
  * ``GET  /admin/api/forms/<id>/submissions`` — submissions + field defs
"""

from __future__ import annotations

import json
import random
import string
from datetime import datetime

from flask import Blueprint, request, jsonify

from ..db import query_db, execute_db
from ..auth import admin_required
from ..util import parse_ua, client_ip

bp = Blueprint("forms", __name__)


def _active_form(slug):
    return query_db(
        "SELECT id, name FROM custom_forms WHERE slug = %s AND status = 'active'",
        (slug,), fetchone=True,
    )


@bp.route("/api/forms/<slug>", methods=["GET"])
def public_form_schema(slug):
    """Public: form config + ordered fields for client-side rendering."""
    form = query_db(
        "SELECT id, name, slug, description, submit_button_text, success_message "
        "FROM custom_forms WHERE slug = %s AND status = 'active'",
        (slug,), fetchone=True,
    )
    if not form:
        return jsonify({"error": "Form not found"}), 404
    fields = query_db(
        "SELECT field_type, label, name, placeholder, required, options, "
        "default_value, width, validation_regex, help_text, step "
        "FROM form_fields WHERE form_id = %s ORDER BY sort_order, id",
        (form["id"],),
    )
    form["fields"] = fields or []
    return jsonify(form)


@bp.route("/api/forms/<slug>/submit", methods=["POST"])
def submit_form(slug):
    """Validate + persist a submission; upgrades a prior partial for the same
    session. Generates a confirmation number. Captures marketing metadata."""
    form = _active_form(slug)
    if not form:
        return jsonify({"error": "Form not found"}), 404
    data = request.get_json() or {}
    form_data = data.get("fields", {}) or {}

    fields = query_db(
        "SELECT name, required, label FROM form_fields WHERE form_id = %s",
        (form["id"],),
    )
    for fld in (fields or []):
        if fld["required"] and not form_data.get(fld["name"]):
            return jsonify({"error": f"{fld['label']} is required"}), 400

    ua = request.headers.get("User-Agent", "")
    ip = client_ip()
    browser, os_name, device = parse_ua(ua)
    conf = f"BK-{datetime.now():%Y%m%d}-" + "".join(
        random.choices(string.ascii_uppercase + string.digits, k=5))
    session_id = data.get("session_id", "")

    existing = None
    if session_id:
        existing = query_db(
            "SELECT id FROM form_submissions WHERE form_id = %s AND session_id = %s "
            "AND status = 'partial' ORDER BY submitted_at DESC LIMIT 1",
            (form["id"], session_id), fetchone=True,
        )

    params = (
        json.dumps(form_data), conf, device, ua[:500],
        data.get("referrer", ""), data.get("utm_source", ""),
        data.get("utm_medium", ""), data.get("utm_campaign", ""),
        data.get("utm_term", ""), data.get("utm_content", ""),
        data.get("page_url", ""), ip, browser, os_name,
        data.get("screen_resolution", ""), data.get("language", ""),
    )
    if existing:
        result = execute_db(
            """UPDATE form_submissions SET
                 submission_data=%s::jsonb, status='new', updated_at=NOW(),
                 submitted_at=NOW(), confirmation_number=%s, device_type=%s,
                 user_agent=%s, referrer_url=%s, utm_source=%s, utm_medium=%s,
                 utm_campaign=%s, utm_term=%s, utm_content=%s, page_url=%s,
                 ip_address=%s, browser=%s, os=%s, screen_resolution=%s, language=%s
               WHERE id=%s RETURNING id, confirmation_number""",
            params + (existing["id"],),
        )
    else:
        result = execute_db(
            """INSERT INTO form_submissions
                 (form_id, submission_data, confirmation_number, device_type,
                  user_agent, referrer_url, utm_source, utm_medium, utm_campaign,
                  utm_term, utm_content, page_url, ip_address, browser, os,
                  screen_resolution, language, session_id, status)
               VALUES (%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'new')
               RETURNING id, confirmation_number""",
            (form["id"],) + params + (session_id,),
        )
    return jsonify({
        "success": True,
        "id": result["id"] if result else None,
        "confirmation_number": result["confirmation_number"] if result else conf,
    }), 201


@bp.route("/api/forms/<slug>/partial", methods=["POST"])
def partial_save(slug):
    """Auto-save partial form data keyed by session_id (abandon capture)."""
    form = _active_form(slug)
    if not form:
        return jsonify({"error": "Form not found"}), 404
    data = request.get_json() or {}
    session_id = data.get("session_id", "")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400
    form_data = data.get("fields", {}) or {}
    ua = request.headers.get("User-Agent", "")
    ip = client_ip()
    browser, os_name, device = parse_ua(ua)

    existing = query_db(
        "SELECT id, status FROM form_submissions WHERE form_id = %s AND session_id = %s "
        "ORDER BY submitted_at DESC LIMIT 1",
        (form["id"], session_id), fetchone=True,
    )
    if existing and existing["status"] == "partial":
        execute_db(
            "UPDATE form_submissions SET submission_data=%s::jsonb, updated_at=NOW() WHERE id=%s",
            (json.dumps(form_data), existing["id"]),
        )
        return jsonify({"success": True, "id": existing["id"], "action": "updated"})
    if existing:
        return jsonify({"success": True, "id": existing["id"], "action": "already_submitted"})
    result = execute_db(
        """INSERT INTO form_submissions
             (form_id, submission_data, status, device_type, user_agent,
              referrer_url, utm_source, utm_medium, utm_campaign, utm_term,
              utm_content, page_url, ip_address, browser, os, screen_resolution,
              language, session_id)
           VALUES (%s,%s::jsonb,'partial',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id""",
        (form["id"], json.dumps(form_data), device, ua[:500],
         data.get("referrer", ""), data.get("utm_source", ""),
         data.get("utm_medium", ""), data.get("utm_campaign", ""),
         data.get("utm_term", ""), data.get("utm_content", ""),
         data.get("page_url", ""), ip, browser, os_name,
         data.get("screen_resolution", ""), data.get("language", ""), session_id),
    )
    return jsonify({"success": True, "id": result["id"] if result else None,
                    "action": "created"}), 201


@bp.route("/admin/api/forms", methods=["GET"])
@admin_required
def admin_list_forms():
    forms = query_db(
        "SELECT f.*, "
        "  (SELECT COUNT(*) FROM form_fields WHERE form_id=f.id) AS field_count, "
        "  (SELECT COUNT(*) FROM form_submissions WHERE form_id=f.id) AS submission_count "
        "FROM custom_forms f ORDER BY f.sort_order, f.created_at"
    )
    return jsonify(forms or [])


@bp.route("/admin/api/forms/<int:form_id>/submissions", methods=["GET"])
@admin_required
def admin_form_submissions(form_id):
    submissions = query_db(
        "SELECT * FROM form_submissions WHERE form_id = %s ORDER BY submitted_at DESC",
        (form_id,),
    )
    fields = query_db(
        "SELECT id, label, name, field_type FROM form_fields WHERE form_id = %s ORDER BY sort_order",
        (form_id,),
    )
    return jsonify({"submissions": submissions or [], "fields": fields or []})
