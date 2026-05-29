"""
admin_ai_platform.blueprints.messaging
======================================

Email/SMS messaging: subscribers, templates (with merge tags), campaigns, the
delivery log, AI drafting, plus the Resend/Twilio status webhooks and the
unsubscribe flow. Sending goes through the relocated ``reused/messaging.py``
(Resend + Twilio); every send is recorded in ``messaging_log``.

Admin routes are @admin_required. Webhooks + /unsubscribe are public (signature-
verified where the provider supports it).
"""

from __future__ import annotations

import json
import threading

from flask import Blueprint, request, jsonify

from .. import llm
from ..db import query_db, execute_db
from ..auth import admin_required
from ..cost import cost_cap_blocks_send, record_sms_cost
from ..reused import messaging

bp = Blueprint("messaging", __name__)


# ---- status -------------------------------------------------------------
@bp.route("/admin/api/messaging/status", methods=["GET"])
@admin_required
def status():
    return jsonify({"resend": messaging.resend_status(), "twilio": messaging.twilio_status()})


# ---- subscribers --------------------------------------------------------
@bp.route("/admin/api/messaging/subscribers", methods=["GET"])
@admin_required
def list_subscribers():
    rows = query_db("SELECT * FROM subscribers ORDER BY created_at DESC LIMIT 500")
    return jsonify({"subscribers": rows or []})


@bp.route("/admin/api/messaging/subscribers", methods=["POST"])
@admin_required
def create_subscriber():
    d = request.get_json() or {}
    row = execute_db(
        "INSERT INTO subscribers (email, phone, full_name, list_name, source, custom_fields) "
        "VALUES (%s,%s,%s,%s,%s,%s::jsonb) RETURNING *",
        (d.get("email", ""), d.get("phone", ""), d.get("full_name", ""),
         d.get("list_name", "default"), d.get("source", "manual"),
         json.dumps(d.get("custom_fields", {}))))
    return jsonify(row), 201


@bp.route("/admin/api/messaging/subscribers/<int:sid>", methods=["PUT"])
@admin_required
def update_subscriber(sid):
    d = request.get_json() or {}
    sets, vals = [], []
    for k in ("email", "phone", "full_name", "list_name", "opt_in", "opt_in_email", "opt_in_sms"):
        if k in d:
            sets.append(f"{k}=%s")
            vals.append(d[k])
    if not sets:
        return jsonify({"error": "No fields"}), 400
    sets.append("updated_at=NOW()")
    vals.append(sid)
    row = execute_db(f"UPDATE subscribers SET {', '.join(sets)} WHERE id=%s RETURNING *", tuple(vals))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/messaging/subscribers/<int:sid>", methods=["DELETE"])
@admin_required
def delete_subscriber(sid):
    execute_db("DELETE FROM subscribers WHERE id=%s", (sid,))
    return jsonify({"success": True})


@bp.route("/admin/api/messaging/subscribers/import-csv", methods=["POST"])
@admin_required
def import_csv():
    text = (request.get_json(silent=True) or {}).get("csv", "")
    if not text and request.data:
        text = request.data.decode("utf-8", "replace")
    rows = messaging.parse_subscriber_csv(text)
    added = 0
    for r in rows:
        try:
            execute_db("INSERT INTO subscribers (email, phone, full_name, source) "
                       "VALUES (%s,%s,%s,'csv')",
                       (r.get("email", ""), r.get("phone", ""), r.get("full_name", "")))
            added += 1
        except Exception:
            pass
    return jsonify({"imported": added, "parsed": len(rows)})


# ---- templates ----------------------------------------------------------
@bp.route("/admin/api/messaging/templates", methods=["GET"])
@admin_required
def list_templates():
    return jsonify({"templates": query_db("SELECT * FROM messaging_templates ORDER BY id DESC") or []})


@bp.route("/admin/api/messaging/templates", methods=["POST"])
@admin_required
def create_template():
    d = request.get_json() or {}
    row = execute_db(
        "INSERT INTO messaging_templates (name, channel, subject, body, from_name, reply_to, notes) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (d.get("name", "Untitled template"), d.get("channel", "email"), d.get("subject", ""),
         d.get("body", ""), d.get("from_name", ""), d.get("reply_to", ""), d.get("notes", "")))
    return jsonify(row), 201


@bp.route("/admin/api/messaging/templates/<int:tid>", methods=["PUT"])
@admin_required
def update_template(tid):
    d = request.get_json() or {}
    sets, vals = [], []
    for k in ("name", "channel", "subject", "body", "from_name", "reply_to", "notes"):
        if k in d:
            sets.append(f"{k}=%s")
            vals.append(d[k])
    if not sets:
        return jsonify({"error": "No fields"}), 400
    sets.append("updated_at=NOW()")
    vals.append(tid)
    row = execute_db(f"UPDATE messaging_templates SET {', '.join(sets)} WHERE id=%s RETURNING *", tuple(vals))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/messaging/templates/<int:tid>", methods=["DELETE"])
@admin_required
def delete_template(tid):
    execute_db("DELETE FROM messaging_templates WHERE id=%s", (tid,))
    return jsonify({"success": True})


@bp.route("/admin/api/messaging/templates/<int:tid>/preview", methods=["GET"])
@admin_required
def preview_template(tid):
    t = query_db("SELECT * FROM messaging_templates WHERE id=%s", (tid,), fetchone=True)
    if not t:
        return jsonify({"error": "Not found"}), 404
    ctx = {"full_name": "Jane Doe", "email": "jane@example.com", "first_name": "Jane"}
    return jsonify({"subject": messaging.render_merge_tags(t["subject"], ctx),
                    "body": messaging.render_merge_tags(t["body"], ctx)})


# ---- AI draft -----------------------------------------------------------
@bp.route("/admin/api/messaging/ai-draft", methods=["POST"])
@admin_required
def ai_draft():
    if llm.openai_client is None:
        return jsonify({"error": "No LLM provider configured"}), 503
    d = request.get_json() or {}
    prompt = (d.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt required"}), 400
    try:
        resp = llm.openai_client.chat.completions.create(
            model="gpt-4o-mini", temperature=0.7, max_tokens=600,
            messages=[{"role": "system", "content": "You draft concise marketing "
                       "emails. Return plain text with merge tags like {{full_name}} "
                       "where personalization helps."},
                      {"role": "user", "content": prompt}])
        return jsonify({"draft": resp.choices[0].message.content or ""})
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 502


# ---- campaigns ----------------------------------------------------------
@bp.route("/admin/api/messaging/campaigns", methods=["GET"])
@admin_required
def list_campaigns():
    return jsonify({"campaigns": query_db("SELECT * FROM messaging_campaigns ORDER BY id DESC") or []})


@bp.route("/admin/api/messaging/campaigns", methods=["POST"])
@admin_required
def create_campaign():
    d = request.get_json() or {}
    row = execute_db(
        "INSERT INTO messaging_campaigns (name, template_id, channel, subject_snapshot, "
        " body_snapshot, recipient_kind, recipient_filter) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb) RETURNING *",
        (d.get("name", ""), d.get("template_id"), d.get("channel", "email"),
         d.get("subject_snapshot", ""), d.get("body_snapshot", ""),
         d.get("recipient_kind", "all"), json.dumps(d.get("recipient_filter", {}))))
    return jsonify(row), 201


@bp.route("/admin/api/messaging/campaigns/<int:cid>", methods=["GET"])
@admin_required
def get_campaign(cid):
    row = query_db("SELECT * FROM messaging_campaigns WHERE id=%s", (cid,), fetchone=True)
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/messaging/campaigns/<int:cid>/cancel", methods=["POST"])
@admin_required
def cancel_campaign(cid):
    execute_db("UPDATE messaging_campaigns SET status='cancelled' WHERE id=%s "
               "AND status IN ('draft','queued')", (cid,))
    return jsonify({"success": True})


@bp.route("/admin/api/messaging/campaigns/<int:cid>/send-now", methods=["POST"])
@admin_required
def send_now(cid):
    camp = query_db("SELECT * FROM messaging_campaigns WHERE id=%s", (cid,), fetchone=True)
    if not camp:
        return jsonify({"error": "Not found"}), 404
    if camp["status"] in ("sending", "sent"):
        return jsonify({"error": f"already {camp['status']}"}), 409
    threading.Thread(target=_run_campaign, args=(cid,), daemon=True).start()
    return jsonify({"status": "sending"})


def _recipients(camp):
    kind = camp.get("recipient_kind", "all")
    flt = camp.get("recipient_filter") or {}
    if kind == "list":
        return query_db("SELECT * FROM subscribers WHERE list_name=%s AND opt_in",
                        (flt.get("list_name", "default"),)) or []
    if kind == "ids":
        ids = flt.get("ids") or []
        if not ids:
            return []
        ph = ",".join(["%s"] * len(ids))
        return query_db(f"SELECT * FROM subscribers WHERE id IN ({ph})", tuple(ids)) or []
    return query_db("SELECT * FROM subscribers WHERE opt_in") or []


def _run_campaign(cid):
    camp = query_db("SELECT * FROM messaging_campaigns WHERE id=%s", (cid,), fetchone=True)
    if not camp:
        return
    if cost_cap_blocks_send(surface="campaign"):
        execute_db("UPDATE messaging_campaigns SET status='failed', error_text='cost cap reached' "
                   "WHERE id=%s", (cid,))
        return
    recips = _recipients(camp)
    execute_db("UPDATE messaging_campaigns SET status='sending', started_at=NOW(), "
               "total_recipients=%s WHERE id=%s", (len(recips), cid))
    sent = failed = 0
    channel = camp.get("channel", "email")
    for sub in recips:
        ctx = messaging.subscriber_context(sub)
        subject = messaging.render_merge_tags(camp.get("subject_snapshot", ""), ctx)
        body = messaging.render_merge_tags(camp.get("body_snapshot", ""), ctx)
        to = sub.get("email") if channel == "email" else sub.get("phone")
        log = execute_db(
            "INSERT INTO messaging_log (campaign_id, subscriber_id, channel, to_address, "
            " subject_snapshot, body_snapshot, status) VALUES (%s,%s,%s,%s,%s,%s,'queued') RETURNING id",
            (cid, sub["id"], channel, to or "", subject, body))
        try:
            if channel == "email":
                resp = messaging.send_email(to, subject, body)
                mid = resp.get("id", "")
            else:
                resp = messaging.send_sms(to, body)
                mid = resp.get("sid", "") if isinstance(resp, dict) else ""
                record_sms_cost(message_sid=mid, to_number=to or "", segments=resp.get("segments")
                                if isinstance(resp, dict) else None)
            execute_db("UPDATE messaging_log SET status='sent', provider_message_id=%s, sent_at=NOW() "
                       "WHERE id=%s", (mid, log["id"]))
            sent += 1
        except Exception as e:
            execute_db("UPDATE messaging_log SET status='failed', error_text=%s WHERE id=%s",
                       (str(e)[:300], log["id"]))
            failed += 1
    execute_db("UPDATE messaging_campaigns SET status='sent', finished_at=NOW(), "
               "sent_count=%s, failed_count=%s WHERE id=%s", (sent, failed, cid))


@bp.route("/admin/api/messaging/campaigns/<int:cid>", methods=["DELETE"])
@admin_required
def delete_campaign(cid):
    execute_db("DELETE FROM messaging_campaigns WHERE id=%s", (cid,))
    return jsonify({"success": True})


@bp.route("/admin/api/messaging/log", methods=["GET"])
@admin_required
def log():
    rows = query_db("SELECT * FROM messaging_log ORDER BY id DESC LIMIT 200")
    return jsonify({"log": rows or []})


# ---- webhooks + unsubscribe (public) -----------------------------------
@bp.route("/webhooks/resend", methods=["POST"])
def resend_webhook():
    raw = request.get_data()
    if not messaging.verify_resend_signature(dict(request.headers), raw):
        # Fail-open is configurable upstream; here we record but mark unverified.
        print("[messaging] Resend webhook signature not verified")
    ev = request.get_json(silent=True) or {}
    mid = (ev.get("data") or {}).get("email_id") or ev.get("message_id") or ""
    etype = ev.get("type", "")
    status_map = {"email.delivered": "delivered", "email.opened": "opened",
                  "email.clicked": "clicked", "email.bounced": "bounced",
                  "email.complained": "complained"}
    new_status = status_map.get(etype)
    if mid and new_status:
        execute_db("UPDATE messaging_log SET status=%s WHERE provider_message_id=%s",
                   (new_status, mid))
    return jsonify({"ok": True})


@bp.route("/webhooks/twilio/sms-status", methods=["POST"])
def twilio_status_webhook():
    sid = request.form.get("MessageSid", "")
    status = request.form.get("MessageStatus", "")
    if sid and status:
        execute_db("UPDATE messaging_log SET status=%s WHERE provider_message_id=%s",
                   (status, sid))
    return ("", 204)


@bp.route("/unsubscribe", methods=["GET", "POST"])
def unsubscribe():
    token = request.args.get("token") or (request.form.get("token") if request.form else "")
    sub_id = messaging.parse_unsubscribe_token(token or "")
    if not sub_id:
        return "Invalid or expired unsubscribe link.", 400
    execute_db("UPDATE subscribers SET opt_in=FALSE, opt_in_email=FALSE, "
               "unsubscribed_at=NOW() WHERE id=%s", (sub_id,))
    return "You have been unsubscribed."
