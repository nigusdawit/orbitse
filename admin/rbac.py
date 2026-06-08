"""admin/rbac.py — multi-user admin accounts, roles, and invites (gap §6.3, Phase 1).

This is the management + invite surface for per-user admin login. The LOGIN itself is
extended additively in app.py's /admin/login (it calls rbac_authenticate); the existing
ADMIN_PASSWORD / CLIENT_PASSWORD flow is untouched and remains the break-glass super-admin.

Security notes:
- Passwords are hashed with werkzeug (pbkdf2). We never store or log plaintext.
- Invite tokens are high-entropy (secrets.token_urlsafe(32)); only a SHA-256 HASH is stored,
  so a DB leak can't be replayed. Invites are single-use (used_at) and expire (7 days).
- No email enumeration: login + join return the same generic failure for unknown email and
  wrong password.
- Lockout guards: the last active super-admin can't be demoted/disabled/deleted, and you
  can't delete your own account. (The ENV ADMIN_PASSWORD is always a separate break-glass.)
- Every state change is appended to super_admin_audit.

Registered in app.py via app.register_blueprint(rbac_bp).
"""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify, render_template, session
from werkzeug.security import generate_password_hash, check_password_hash

from core import (
    query_db,
    execute_db,
    admin_required,
    _require_super_admin_role,
    current_tenant_id,
    capture_exc,
)

try:
    from messaging import send_email
except Exception:  # pragma: no cover - messaging always importable in this repo
    send_email = None

rbac_bp = Blueprint("rbac", __name__)

ROLES = ("super_admin", "admin", "editor")
STATUSES = ("invited", "active", "disabled")
INVITE_TTL_DAYS = 7
MIN_PASSWORD_LEN = 8


# --- helpers -----------------------------------------------------------------

def _token_hash(token):
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _email_configured():
    return bool(send_email and (os.environ.get("RESEND_API_KEY") or "").strip())


def _audit(action, outcome, detail=""):
    """Append a row to super_admin_audit (reused for RBAC events). Best-effort."""
    try:
        ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
        ua = (request.headers.get("User-Agent") or "")[:300]
        execute_db(
            "INSERT INTO super_admin_audit (ip, user_agent, action, outcome, reason) VALUES (%s,%s,%s,%s,%s)",
            (ip, ua, action, outcome, detail),
        )
    except Exception:
        pass


def _serialize_user(row):
    d = dict(row)
    d.pop("password_hash", None)   # never expose the hash
    for k in ("created_at", "last_login_at"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    d["has_password"] = bool((row.get("password_hash") or "").strip())
    return d


def _active_super_admin_count(tid, exclude=None):
    r = query_db(
        "SELECT COUNT(*) AS n FROM admin_users "
        "WHERE tenant_id=%s AND role='super_admin' AND status='active' AND id <> %s",
        (tid, exclude if exclude is not None else -1), fetchone=True,
    )
    return (r or {}).get("n", 0) if isinstance(r, dict) else 0


def _valid_invite(token):
    """Return {invite_id, user_id, email} for a live (unused, unexpired) token, else None.
    The expiry/used checks run in SQL to avoid tz-aware/naive comparison pitfalls."""
    if not token:
        return None
    row = query_db(
        "SELECT i.id AS invite_id, i.user_id, u.email "
        "  FROM admin_invites i JOIN admin_users u ON u.id = i.user_id "
        " WHERE i.token_hash=%s AND i.used_at IS NULL AND i.expires_at > NOW()",
        (_token_hash(token),), fetchone=True,
    )
    if not row or not isinstance(row, dict):
        return None
    return {"invite_id": row["invite_id"], "user_id": row["user_id"], "email": row.get("email", "")}


# --- used by app.py's /admin/login (additive per-user auth) ------------------

def rbac_authenticate(email, password):
    """Return the active admin_users row (dict) for a correct email+password, else None.
    Used by /admin/login. No email enumeration — None for unknown email and wrong password
    alike. Never raises (callers still fall through to the password-only flow)."""
    try:
        email = (email or "").strip().lower()
        if not email or not password:
            return None
        row = query_db(
            "SELECT * FROM admin_users WHERE tenant_id=%s AND lower(email)=%s",
            (current_tenant_id(), email), fetchone=True,
        )
        if not row or not isinstance(row, dict) or row.get("status") != "active":
            return None
        ph = row.get("password_hash") or ""
        if not ph or not check_password_hash(ph, password):
            return None
        return dict(row)
    except Exception:
        return None


def rbac_note_login(uid):
    try:
        execute_db("UPDATE admin_users SET last_login_at=NOW() WHERE id=%s", (uid,))
    except Exception:
        pass


# --- management routes (super-admin only) ------------------------------------

@rbac_bp.route("/admin/api/admin-users", methods=["GET"])
@admin_required
def admin_list_users():
    g = _require_super_admin_role()
    if g is not None:
        return g
    try:
        rows = query_db(
            "SELECT * FROM admin_users WHERE tenant_id=%s ORDER BY created_at, id",
            (current_tenant_id(),),
        ) or []
        return jsonify({"users": [_serialize_user(r) for r in rows], "roles": list(ROLES)})
    except Exception as e:
        capture_exc(e, "rbac.admin_list_users")
        return jsonify({"error": "list_failed", "detail": str(e)}), 500


@rbac_bp.route("/admin/api/admin-users/invite", methods=["POST"])
@admin_required
def admin_invite_user():
    g = _require_super_admin_role()
    if g is not None:
        return g
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    name = (body.get("name") or "").strip()
    role = (body.get("role") or "admin").strip()
    if not email or "@" not in email or " " in email:
        return jsonify({"error": "bad_email", "message": "A valid email is required."}), 400
    if role not in ROLES:
        return jsonify({"error": "bad_role", "message": "Role must be super_admin, admin, or editor."}), 400
    try:
        tid = current_tenant_id()
        existing = query_db(
            "SELECT id, status FROM admin_users WHERE tenant_id=%s AND lower(email)=%s",
            (tid, email), fetchone=True,
        )
        if isinstance(existing, dict) and existing.get("status") == "active":
            return jsonify({"error": "exists", "message": "That email already has an active account."}), 409
        inviter = session.get("admin_user_id")
        if isinstance(existing, dict):
            uid = existing["id"]
            execute_db(
                "UPDATE admin_users SET role=%s, name=COALESCE(NULLIF(%s,''), name), status='invited' WHERE id=%s",
                (role, name, uid),
            )
        else:
            created = execute_db(
                "INSERT INTO admin_users (tenant_id, email, name, role, status, invited_by) "
                "VALUES (%s,%s,%s,%s,'invited',%s) RETURNING id",
                (tid, email, name, role, inviter),
            )
            uid = created["id"]
        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(days=INVITE_TTL_DAYS)
        execute_db(
            "INSERT INTO admin_invites (tenant_id, user_id, token_hash, role, expires_at) "
            "VALUES (%s,%s,%s,%s,%s)",
            (tid, uid, _token_hash(token), role, expires),
        )
        invite_url = request.host_url.rstrip("/") + "/admin/join?token=" + token
        emailed = False
        if _email_configured():
            try:
                send_email(email, "You've been invited to the admin dashboard",
                           _invite_html(invite_url, role))
                emailed = True
            except Exception as e:
                print(f"[rbac] invite email failed: {e}")
        _audit("rbac_invite", "success", f"{email} as {role}")
        return jsonify({"success": True, "invite_url": invite_url, "emailed": emailed, "user_id": uid})
    except Exception as e:
        capture_exc(e, "rbac.admin_invite_user")
        return jsonify({"error": "invite_failed", "detail": str(e)}), 500


@rbac_bp.route("/admin/api/admin-users/<int:uid>", methods=["PATCH"])
@admin_required
def admin_update_user(uid):
    g = _require_super_admin_role()
    if g is not None:
        return g
    body = request.get_json(silent=True) or {}
    new_role = body.get("role")
    new_status = body.get("status")
    if new_role is not None and new_role not in ROLES:
        return jsonify({"error": "bad_role"}), 400
    if new_status is not None and new_status not in STATUSES:
        return jsonify({"error": "bad_status"}), 400
    if new_role is None and new_status is None:
        return jsonify({"error": "nothing_to_update"}), 400
    try:
        tid = current_tenant_id()
        row = query_db("SELECT * FROM admin_users WHERE id=%s AND tenant_id=%s", (uid, tid), fetchone=True)
        if not isinstance(row, dict):
            return jsonify({"error": "not_found"}), 404
        # lockout guards: never demote/disable the LAST active super-admin
        demoting = new_role is not None and row["role"] == "super_admin" and new_role != "super_admin"
        disabling = new_status == "disabled" and row["role"] == "super_admin" and row["status"] == "active"
        if (demoting or disabling) and _active_super_admin_count(tid, exclude=uid) == 0:
            return jsonify({"error": "last_super_admin",
                            "message": "You can't remove the last super-admin account."}), 400
        if new_status == "disabled" and session.get("admin_user_id") == uid:
            return jsonify({"error": "self", "message": "You can't disable your own account."}), 400
        sets, params = [], []
        if new_role is not None:
            sets.append("role=%s"); params.append(new_role)
        if new_status is not None:
            sets.append("status=%s"); params.append(new_status)
        params.append(uid)
        execute_db(f"UPDATE admin_users SET {', '.join(sets)} WHERE id=%s", tuple(params))
        _audit("rbac_update", "success", f"user#{uid} role={new_role} status={new_status}")
        return jsonify({"success": True})
    except Exception as e:
        capture_exc(e, "rbac.admin_update_user")
        return jsonify({"error": "update_failed", "detail": str(e)}), 500


@rbac_bp.route("/admin/api/admin-users/<int:uid>", methods=["DELETE"])
@admin_required
def admin_delete_user(uid):
    g = _require_super_admin_role()
    if g is not None:
        return g
    try:
        tid = current_tenant_id()
        row = query_db("SELECT * FROM admin_users WHERE id=%s AND tenant_id=%s", (uid, tid), fetchone=True)
        if not isinstance(row, dict):
            return jsonify({"error": "not_found"}), 404
        if session.get("admin_user_id") == uid:
            return jsonify({"error": "self", "message": "You can't remove your own account."}), 400
        if (row["role"] == "super_admin" and row["status"] == "active"
                and _active_super_admin_count(tid, exclude=uid) == 0):
            return jsonify({"error": "last_super_admin",
                            "message": "You can't remove the last super-admin account."}), 400
        execute_db("DELETE FROM admin_users WHERE id=%s", (uid,))
        _audit("rbac_delete", "success", f"user#{uid} {row.get('email','')}")
        return jsonify({"success": True})
    except Exception as e:
        capture_exc(e, "rbac.admin_delete_user")
        return jsonify({"error": "delete_failed", "detail": str(e)}), 500


# --- public invite-acceptance (token-gated, NO session) ----------------------

@rbac_bp.route("/admin/join", methods=["GET"])
def admin_join_page():
    token = request.args.get("token", "")
    inv = _valid_invite(token)
    return render_template("admin/join.html", token=token, valid=bool(inv),
                           email=(inv.get("email") if inv else ""),
                           min_len=MIN_PASSWORD_LEN)


@rbac_bp.route("/admin/api/join", methods=["POST"])
def admin_join_submit():
    """Set the invited user's password and activate them. Token is the auth (no session),
    so this path is CSRF-exempt (see app.py's _CSRF_EXEMPT_PATHS)."""
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    password = body.get("password") or ""
    if len(password) < MIN_PASSWORD_LEN:
        return jsonify({"error": "weak_password",
                        "message": f"Password must be at least {MIN_PASSWORD_LEN} characters."}), 400
    inv = _valid_invite(token)
    if not inv:
        return jsonify({"error": "invalid_invite",
                        "message": "This invite link is invalid or has expired."}), 400
    try:
        execute_db("UPDATE admin_users SET password_hash=%s, status='active' WHERE id=%s",
                   (generate_password_hash(password), inv["user_id"]))
        execute_db("UPDATE admin_invites SET used_at=NOW() WHERE id=%s", (inv["invite_id"],))
        _audit("rbac_join", "success", inv.get("email", ""))
        return jsonify({"success": True})
    except Exception as e:
        capture_exc(e, "rbac.admin_join_submit")
        return jsonify({"error": "join_failed", "detail": str(e)}), 500


def _invite_html(url, role):
    return (
        "<p>You've been invited to the admin dashboard"
        + (f" as <strong>{role}</strong>" if role else "")
        + ".</p><p>Click the link below to set your password and sign in. "
        + "This link expires in " + str(INVITE_TTL_DAYS) + " days and can be used once.</p>"
        + f'<p><a href="{url}">{url}</a></p>'
    )
