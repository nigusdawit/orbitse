"""admin/forms.py - admin CRUD for the dynamic form builder, as a Flask blueprint.

Track B / B9 of the app.py de-monolith. Covers the admin-facing form builder:
custom_forms CRUD, per-form field CRUD + reorder, and form submission
listing/status/delete/analytics. All routes are gated by @admin_required (from
core) and touch the database only via query_db/execute_db (also from core).

URLs keep their absolute /admin/api/forms/* and /admin/api/submissions/* paths,
so the route table is byte-identical to when these lived on the global app -
the route-snapshot test sees zero change. Only the Flask endpoint name gains a
"forms." prefix; admin JS calls these by URL (not url_for), so nothing breaks.

Two small private helpers (_form_is_managed / _reject_if_managed) move with the
routes - they are only used by these routes and depend solely on query_db /
jsonify, so the blueprint stays self-contained. The PUBLIC form API
(/api/forms/<slug>) stays in app.py: it is an unauthenticated read with its own
UA-parsing helper, a separate concern from this admin surface.

Why no CSRF / feature-flag code here: those run in app.py's GLOBAL
@app.before_request hooks, which apply to blueprint routes too, so a moved admin
route keeps the exact same protection it had on the global app. Imports come
from core (never app - that would be circular).

Registered in app.py via app.register_blueprint(forms_bp).
"""
import json
import re

from flask import Blueprint, request, jsonify

from core import query_db, execute_db, admin_required

forms_bp = Blueprint("forms", __name__)


# ---- dynamic form builder: forms + fields + submissions CRUD (Track B / B9, verbatim) ----

@forms_bp.route("/admin/api/forms", methods=["GET"])
@admin_required
def admin_list_forms():
    """GET /admin/api/forms — List all forms with field/submission counts."""
    forms = query_db("""
        SELECT f.*,
            (SELECT COUNT(*) FROM form_fields WHERE form_id = f.id) AS field_count,
            (SELECT COUNT(*) FROM form_submissions WHERE form_id = f.id) AS submission_count
        FROM custom_forms f ORDER BY f.sort_order, f.created_at
    """)
    return jsonify(forms or [])


@forms_bp.route("/admin/api/forms", methods=["POST"])
@admin_required
def admin_create_form():
    """POST /admin/api/forms — Create a new form."""
    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"error": "Form name is required"}), 400
    slug = data.get("slug") or data["name"].lower().replace(" ", "-").replace("'", "")
    slug = re.sub(r'[^a-z0-9\-]', '', slug)
    existing = query_db("SELECT id FROM custom_forms WHERE slug = %s", (slug,), fetchone=True)
    if existing:
        return jsonify({"error": "A form with this slug already exists"}), 400
    result = execute_db(
        """INSERT INTO custom_forms (name, slug, description, status, submit_button_text, success_message, sort_order)
           VALUES (%s, %s, %s, %s, %s, %s, COALESCE((SELECT MAX(sort_order)+1 FROM custom_forms), 0))
           RETURNING *""",
        (
            data["name"],
            slug,
            data.get("description", ""),
            data.get("status", "active"),
            data.get("submit_button_text", "Submit"),
            data.get("success_message", "Thank you! Your submission has been received.")
        )
    )
    return jsonify(result), 201


@forms_bp.route("/admin/api/forms/<int:form_id>", methods=["GET"])
@admin_required
def admin_get_form(form_id):
    """GET /admin/api/forms/<id> — Get a single form with all its fields."""
    form = query_db("SELECT * FROM custom_forms WHERE id = %s", (form_id,), fetchone=True)
    if not form:
        return jsonify({"error": "Form not found"}), 404
    fields = query_db("SELECT * FROM form_fields WHERE form_id = %s ORDER BY sort_order", (form_id,))
    form["fields"] = fields or []
    sub_count = query_db("SELECT COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s", (form_id,), fetchone=True)
    form["submission_count"] = sub_count["cnt"] if sub_count else 0
    return jsonify(form)


def _form_is_managed(form_id):
    """Return (form_row, is_managed). Managed forms (form_type != 'standard')
    are auto-created by features like Service Bookings — admins can browse
    submissions but must NOT edit/delete the form itself or its fields,
    otherwise the feature that owns the form breaks."""
    row = query_db(
        "SELECT id, form_type, name FROM custom_forms WHERE id = %s",
        (form_id,), fetchone=True,
    )
    if not row:
        return (None, False)
    return (row, (row.get("form_type") or "standard") != "standard")


def _reject_if_managed(form_id):
    """Helper for admin mutation endpoints — returns a Flask response if the
    form is system-managed, or None if it's a normal admin-editable form."""
    row, managed = _form_is_managed(form_id)
    if not row:
        return jsonify({"error": "Form not found"}), 404
    if managed:
        return jsonify({
            "error": (
                f"This is an auto-managed form ({row.get('name','')}). "
                "It is owned by another feature (e.g. Service Bookings) and "
                "cannot be edited or deleted from the Forms tab. "
                "You can still view its submissions and analytics."
            )
        }), 403
    return None


@forms_bp.route("/admin/api/forms/<int:form_id>", methods=["PUT"])
@admin_required
def admin_update_form(form_id):
    """PUT /admin/api/forms/<id> — Update form settings."""
    blocked = _reject_if_managed(form_id)
    if blocked:
        return blocked
    data = request.get_json()
    result = execute_db(
        """UPDATE custom_forms SET
             name = %s, description = %s, status = %s,
             submit_button_text = %s, success_message = %s, updated_at = NOW()
           WHERE id = %s RETURNING *""",
        (
            data.get("name", ""),
            data.get("description", ""),
            data.get("status", "active"),
            data.get("submit_button_text", "Submit"),
            data.get("success_message", "Thank you! Your submission has been received."),
            form_id
        )
    )
    if not result:
        return jsonify({"error": "Form not found"}), 404
    return jsonify(result)


@forms_bp.route("/admin/api/forms/<int:form_id>", methods=["DELETE"])
@admin_required
def admin_delete_form(form_id):
    """DELETE /admin/api/forms/<id> — Delete a form (cascades fields and submissions)."""
    blocked = _reject_if_managed(form_id)
    if blocked:
        return blocked
    sub_count = query_db("SELECT COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s", (form_id,), fetchone=True)
    if sub_count and sub_count["cnt"] > 0:
        confirm = request.args.get("confirm") == "true"
        if not confirm:
            return jsonify({"error": f"Form has {sub_count['cnt']} submission(s). Add ?confirm=true to delete anyway."}), 400
    result = execute_db("DELETE FROM custom_forms WHERE id = %s RETURNING id", (form_id,))
    if not result:
        return jsonify({"error": "Form not found"}), 404
    return jsonify({"success": True})


@forms_bp.route("/admin/api/forms/<int:form_id>/fields", methods=["POST"])
@admin_required
def admin_add_field(form_id):
    """POST /admin/api/forms/<id>/fields — Add a field to a form."""
    blocked = _reject_if_managed(form_id)
    if blocked:
        return blocked
    data = request.get_json()
    if not data or not data.get("label"):
        return jsonify({"error": "Field label is required"}), 400
    name = data.get("name") or data["label"].lower().replace(" ", "_")
    name = re.sub(r'[^a-z0-9_]', '', name)
    options_val = json.dumps(data["options"]) if data.get("options") else None
    step_val = max(1, int(data.get("step", 1))) if data.get("step") else 1
    result = execute_db(
        """INSERT INTO form_fields (form_id, field_type, label, name, placeholder, required, options, default_value, sort_order, width, validation_regex, help_text, step)
           VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, COALESCE((SELECT MAX(sort_order)+1 FROM form_fields WHERE form_id = %s), 0), %s, %s, %s, %s)
           RETURNING *""",
        (
            form_id,
            data.get("field_type", "text"),
            data["label"],
            name,
            data.get("placeholder", ""),
            data.get("required", False),
            options_val,
            data.get("default_value", ""),
            form_id,
            data.get("width", "full"),
            data.get("validation_regex", ""),
            data.get("help_text", ""),
            step_val
        )
    )
    return jsonify(result), 201


@forms_bp.route("/admin/api/forms/<int:form_id>/fields/<int:field_id>", methods=["PUT"])
@admin_required
def admin_update_field(form_id, field_id):
    """PUT /admin/api/forms/<id>/fields/<field_id> — Update a field."""
    blocked = _reject_if_managed(form_id)
    if blocked:
        return blocked
    data = request.get_json()
    options_val = json.dumps(data["options"]) if data.get("options") else None
    step_val = max(1, int(data.get("step", 1))) if data.get("step") else 1
    result = execute_db(
        """UPDATE form_fields SET
             field_type = %s, label = %s, name = %s, placeholder = %s,
             required = %s, options = %s::jsonb, default_value = %s,
             width = %s, validation_regex = %s, help_text = %s, step = %s
           WHERE id = %s AND form_id = %s RETURNING *""",
        (
            data.get("field_type", "text"),
            data.get("label", ""),
            data.get("name", ""),
            data.get("placeholder", ""),
            data.get("required", False),
            options_val,
            data.get("default_value", ""),
            data.get("width", "full"),
            data.get("validation_regex", ""),
            data.get("help_text", ""),
            step_val,
            field_id,
            form_id
        )
    )
    if not result:
        return jsonify({"error": "Field not found"}), 404
    return jsonify(result)


@forms_bp.route("/admin/api/forms/<int:form_id>/fields/<int:field_id>", methods=["DELETE"])
@admin_required
def admin_delete_field(form_id, field_id):
    """DELETE /admin/api/forms/<id>/fields/<field_id> — Remove a field."""
    blocked = _reject_if_managed(form_id)
    if blocked:
        return blocked
    result = execute_db("DELETE FROM form_fields WHERE id = %s AND form_id = %s RETURNING id", (field_id, form_id))
    if not result:
        return jsonify({"error": "Field not found"}), 404
    return jsonify({"success": True})


@forms_bp.route("/admin/api/forms/<int:form_id>/fields/reorder", methods=["PUT"])
@admin_required
def admin_reorder_fields(form_id):
    """PUT /admin/api/forms/<id>/fields/reorder — Batch reorder fields."""
    blocked = _reject_if_managed(form_id)
    if blocked:
        return blocked
    data = request.get_json()
    order = data.get("order", [])
    for item in order:
        execute_db(
            "UPDATE form_fields SET sort_order = %s WHERE id = %s AND form_id = %s",
            (item["sort_order"], item["id"], form_id)
        )
    return jsonify({"success": True})


# =============================================================================
# DYNAMIC FORM BUILDER — Submissions & Analytics
# =============================================================================

@forms_bp.route("/admin/api/forms/<int:form_id>/submissions", methods=["GET"])
@admin_required
def admin_form_submissions(form_id):
    """GET /admin/api/forms/<id>/submissions — List submissions with all fields."""
    submissions = query_db(
        "SELECT * FROM form_submissions WHERE form_id = %s ORDER BY submitted_at DESC",
        (form_id,)
    )
    fields = query_db(
        "SELECT id, label, name, field_type FROM form_fields WHERE form_id = %s ORDER BY sort_order",
        (form_id,)
    )
    return jsonify({"submissions": submissions or [], "fields": fields or []})


@forms_bp.route("/admin/api/submissions/<int:sub_id>/status", methods=["PUT"])
@admin_required
def admin_update_submission_status(sub_id):
    """PUT /admin/api/submissions/<id>/status — Update submission status."""
    data = request.get_json()
    result = execute_db(
        "UPDATE form_submissions SET status = %s WHERE id = %s RETURNING id, status",
        (data.get("status", "new"), sub_id)
    )
    if not result:
        return jsonify({"error": "Submission not found"}), 404
    return jsonify(result)


@forms_bp.route("/admin/api/submissions/<int:sub_id>", methods=["DELETE"])
@admin_required
def admin_delete_submission(sub_id):
    """DELETE /admin/api/submissions/<id> — Delete a submission."""
    result = execute_db("DELETE FROM form_submissions WHERE id = %s RETURNING id", (sub_id,))
    if not result:
        return jsonify({"error": "Submission not found"}), 404
    return jsonify({"success": True})


@forms_bp.route("/admin/api/submissions", methods=["GET"])
@admin_required
def admin_submissions_inbox():
    """Cross-form submissions INBOX (task 100, gap §2.6): the most recent submissions
    across ALL forms with the form name + status + a short field preview, so the operator
    has one unified queue instead of picking a form first. ?limit (default 50, max 200)."""
    try:
        limit = max(1, min(int(request.args.get("limit", 50) or 50), 200))
    except (TypeError, ValueError):
        limit = 50
    rows = query_db(
        "SELECT s.id, s.form_id, s.status, s.submitted_at, s.submission_data, "
        "       COALESCE(f.name,'(form)') AS form_name "
        "FROM form_submissions s LEFT JOIN custom_forms f ON f.id = s.form_id "
        "ORDER BY s.submitted_at DESC LIMIT %s", (limit,)) or []
    out = []
    for r in rows:
        d = r.get("submission_data") or {}
        if isinstance(d, str):
            try:
                import json as _json
                d = _json.loads(d)
            except Exception:
                d = {}
        preview = " · ".join("%s: %s" % (k, str(v)[:40])
                             for k, v in (list(d.items())[:3] if isinstance(d, dict) else []))
        out.append({"id": r["id"], "form_id": r.get("form_id"),
                    "form_name": r.get("form_name") or "", "status": r.get("status") or "new",
                    "submitted_at": r["submitted_at"].isoformat() if r.get("submitted_at") else None,
                    "preview": preview})
    return jsonify({"submissions": out})


@forms_bp.route("/admin/api/submissions/<int:sub_id>/to-lead", methods=["POST"])
@admin_required
def admin_submission_to_lead(sub_id):
    """Route a form submission into the CRM as a lead (task 100, gap §2.6). Heuristically
    pulls name/email/phone from the submission_data JSONB, creates a 'form'-sourced lead
    (tenant_id defaults to 1 — silo), and marks the submission 'converted'."""
    sub = query_db("SELECT id, submission_data FROM form_submissions WHERE id=%s",
                   (sub_id,), fetchone=True)
    if not sub:
        return jsonify({"error": "Submission not found"}), 404
    data = sub.get("submission_data") or {}
    if isinstance(data, str):
        try:
            import json as _json
            data = _json.loads(data)
        except Exception:
            data = {}
    name = email = phone = ""
    if isinstance(data, dict):
        for k, v in data.items():
            kl = str(k).lower()
            sv = "" if v is None else str(v)
            if not email and ("email" in kl or "@" in sv):
                email = sv[:320]
            elif not name and "name" in kl:
                name = sv[:200]
            elif not phone and ("phone" in kl or "tel" in kl or "mobile" in kl):
                phone = sv[:50]
    if not (name or email or phone):
        return jsonify({"error": "No name/email/phone found in this submission."}), 400
    row = execute_db(
        "INSERT INTO leads (name, email, phone, interest, source, status) "
        "VALUES (%s,%s,%s,'Form submission','form','new') RETURNING id",
        (name, email.lower(), phone))
    try:
        execute_db("UPDATE form_submissions SET status='converted' WHERE id=%s", (sub_id,))
    except Exception:
        pass
    return jsonify({"ok": True, "lead_id": row["id"] if isinstance(row, dict) else None})


@forms_bp.route("/admin/api/forms/<int:form_id>/analytics", methods=["GET"])
@admin_required
def admin_form_analytics(form_id):
    """GET /admin/api/forms/<id>/analytics — Marketing analytics for a form."""
    total = query_db("SELECT COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s", (form_id,), fetchone=True)
    today = query_db(
        "SELECT COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s AND submitted_at::date = CURRENT_DATE",
        (form_id,), fetchone=True
    )
    by_status = query_db(
        "SELECT status, COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s GROUP BY status ORDER BY cnt DESC",
        (form_id,)
    )
    by_device = query_db(
        "SELECT device_type, COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s GROUP BY device_type ORDER BY cnt DESC",
        (form_id,)
    )
    by_utm = query_db(
        "SELECT utm_source, COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s AND utm_source != '' GROUP BY utm_source ORDER BY cnt DESC LIMIT 10",
        (form_id,)
    )
    by_browser = query_db(
        "SELECT browser, COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s AND browser != '' GROUP BY browser ORDER BY cnt DESC LIMIT 10",
        (form_id,)
    )
    by_os = query_db(
        "SELECT os, COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s AND os != '' GROUP BY os ORDER BY cnt DESC LIMIT 10",
        (form_id,)
    )
    top_referrers = query_db(
        "SELECT referrer_url, COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s AND referrer_url != '' GROUP BY referrer_url ORDER BY cnt DESC LIMIT 10",
        (form_id,)
    )
    by_language = query_db(
        "SELECT language, COUNT(*) AS cnt FROM form_submissions WHERE form_id = %s AND language != '' GROUP BY language ORDER BY cnt DESC LIMIT 10",
        (form_id,)
    )
    return jsonify({
        "total": total["cnt"] if total else 0,
        "today": today["cnt"] if today else 0,
        "by_status": by_status or [],
        "by_device": by_device or [],
        "by_utm_source": by_utm or [],
        "by_browser": by_browser or [],
        "by_os": by_os or [],
        "top_referrers": top_referrers or [],
        "by_language": by_language or []
    })
