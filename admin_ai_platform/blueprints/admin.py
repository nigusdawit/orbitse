"""
admin_ai_platform.blueprints.admin
==================================

Admin auth + dashboard shell + admin data views (chat history, generated pages).

  * ``GET  /admin``               dashboard (redirects to login if unauthenticated)
  * ``GET/POST /admin/login``     password login (sets session)
  * ``GET  /admin/logout``        clear session
  * ``GET  /admin/api/chat-history``          visitor conversations + stats
  * ``GET  /admin/api/chat-history/<id>``     full transcript
  * ``DELETE /admin/api/chat-history/<id>``   delete a conversation
  * ``GET/PUT/DELETE /admin/api/generated-pages[/<id>]``  saved AI pages

ADMIN_MODE governs whether per-tenant self-serve admin is *offered*; the gate
itself is the password/session. In ``self_host`` the single operator logs in
here; full per-tenant admin users land with the multi-tenant work (M6).
"""

from __future__ import annotations

import os

from flask import (Blueprint, request, session, redirect, jsonify,
                   send_from_directory)

from ..db import query_db, execute_db
from ..auth import admin_required, check_admin_password, is_admin_authenticated

bp = Blueprint("admin", __name__)

_ADMIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "admin")


# ---- Auth + shell -------------------------------------------------------
@bp.route("/admin", methods=["GET"])
def dashboard():
    if not is_admin_authenticated():
        return redirect("/admin/login")
    # Inject a per-response CSP nonce into the inline <script> so the admin CSP
    # can use 'nonce-…' instead of 'unsafe-inline' (M19 security-review M2). The
    # nonce is stashed on g for the after_request CSP composer.
    import os
    import base64
    from flask import g, Response
    nonce = base64.b64encode(os.urandom(16)).decode()
    g.csp_nonce = nonce
    try:
        with open(os.path.join(_ADMIN_DIR, "dashboard.html"), encoding="utf-8") as fh:
            html = fh.read()
    except OSError:
        return send_from_directory(_ADMIN_DIR, "dashboard.html")
    return Response(html.replace("__CSP_NONCE__", nonce), mimetype="text/html")


@bp.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return send_from_directory(_ADMIN_DIR, "login.html")
    # Accept form-encoded or JSON.
    pwd = (request.form.get("password") if request.form else None) \
        or ((request.get_json(silent=True) or {}).get("password"))
    if check_admin_password(pwd or ""):
        session["is_admin"] = True
        session.permanent = True
        if request.is_json:
            return jsonify({"success": True})
        return redirect("/admin")
    if request.is_json:
        return jsonify({"error": "Invalid password"}), 401
    return send_from_directory(_ADMIN_DIR, "login.html")


@bp.route("/admin/logout", methods=["GET"])
def logout():
    session.pop("is_admin", None)
    return redirect("/admin/login")


@bp.route("/admin/sso", methods=["GET"])
def sso_login():
    """Single-use SSO entry for the WordPress-embedded admin iframe. Verifies a
    short-lived HMAC token (signed by the plugin with the shared SSO secret),
    establishes the admin session, and redirects into /admin — which then
    renders inside the wp-admin iframe (frame-ancestors set in after_request)."""
    from ..sso import verify_sso_token
    tid = verify_sso_token(request.args.get("token", ""))
    if tid is None:
        return jsonify({"error": "invalid or expired SSO token"}), 403
    session["is_admin"] = True
    session["tenant_id"] = tid
    session.permanent = True
    return redirect("/admin")


# NOTE: the admin framing policy (frame-ancestors + X-Frame-Options) and the
# baseline CSP are now composed in a SINGLE app-level after_request in
# admin_ai_platform/__init__.py (M19), so this blueprint no longer sets CSP
# headers itself — two after_requests both writing Content-Security-Policy fought
# and dropped the baseline directives.


# ---- Chat history (visitor conversations) -------------------------------
@bp.route("/admin/api/chat-history", methods=["GET"])
@admin_required
def chat_history():
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(1, int(request.args.get("per_page", 50))))
    offset = (page - 1) * per_page
    conversations = query_db(
        "SELECT c.*, "
        " (SELECT COUNT(*) FROM chat_messages WHERE conversation_id=c.id) AS message_count, "
        " (SELECT content FROM chat_messages WHERE conversation_id=c.id AND role='user' "
        "    ORDER BY id LIMIT 1) AS first_message "
        "FROM chat_conversations c ORDER BY c.updated_at DESC LIMIT %s OFFSET %s",
        (per_page, offset))
    stats = query_db(
        "SELECT (SELECT COUNT(*) FROM chat_conversations) AS total_conversations, "
        " (SELECT COUNT(*) FROM chat_messages WHERE created_at >= CURRENT_DATE) AS messages_today, "
        " (SELECT COUNT(DISTINCT visitor_id) FROM chat_conversations "
        "    WHERE visitor_id <> '' AND visitor_id IS NOT NULL) AS unique_visitors",
        fetchone=True)
    return jsonify({"conversations": conversations or [], "stats": stats or {}})


@bp.route("/admin/api/chat-history/<int:conv_id>", methods=["GET"])
@admin_required
def chat_detail(conv_id):
    conv = query_db("SELECT * FROM chat_conversations WHERE id=%s", (conv_id,), fetchone=True)
    if not conv:
        return jsonify({"error": "Not found"}), 404
    msgs = query_db("SELECT * FROM chat_messages WHERE conversation_id=%s ORDER BY created_at, id",
                    (conv_id,))
    return jsonify({"conversation": conv, "messages": msgs or []})


@bp.route("/admin/api/chat-history/<int:conv_id>", methods=["DELETE"])
@admin_required
def chat_delete(conv_id):
    execute_db("DELETE FROM chat_conversations WHERE id=%s", (conv_id,))
    return jsonify({"success": True})


# ---- Generated pages admin ---------------------------------------------
@bp.route("/admin/api/generated-pages", methods=["GET"])
@admin_required
def list_pages():
    rows = query_db("SELECT id, title, slug, status, prompt, created_at, updated_at "
                    "FROM generated_pages ORDER BY created_at DESC")
    return jsonify(rows or [])


@bp.route("/admin/api/generated-pages/<int:pid>", methods=["GET"])
@admin_required
def get_page(pid):
    row = query_db("SELECT * FROM generated_pages WHERE id=%s", (pid,), fetchone=True)
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/generated-pages/<int:pid>", methods=["PUT"])
@admin_required
def update_page(pid):
    data = request.get_json() or {}
    sets, vals = [], []
    for k in ("title", "html"):
        if k in data:
            sets.append(f"{k}=%s")
            vals.append(data[k])
    if data.get("status") in ("draft", "published"):
        sets.append("status=%s")
        vals.append(data["status"])
    if not sets:
        return jsonify({"error": "No fields"}), 400
    sets.append("updated_at=NOW()")
    vals.append(pid)
    row = execute_db(f"UPDATE generated_pages SET {', '.join(sets)} WHERE id=%s RETURNING id", tuple(vals))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"success": True})


@bp.route("/admin/api/generated-pages/<int:pid>", methods=["DELETE"])
@admin_required
def delete_page(pid):
    execute_db("DELETE FROM generated_pages WHERE id=%s", (pid,))
    return jsonify({"success": True})
