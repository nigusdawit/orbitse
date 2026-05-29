"""
admin_ai_platform.blueprints.automations
========================================

IFTTT-style automations admin + the public webhook trigger. CRUD is direct SQL;
the engine (matching, queueing, step execution, scheduling) lives in the
relocated ``reused/automations.py`` module wired up in ``create_app``.

  * ``GET  /admin/api/automations/metadata``        triggers / actions / operators
  * ``GET/PUT /admin/api/automations/settings``     retention knobs
  * ``GET/POST /admin/api/automations``             list / create
  * ``GET/PUT/DELETE /admin/api/automations/<id>``  detail / update(+version) / delete
  * ``POST /admin/api/automations/<id>/toggle``     enable/disable
  * ``POST /admin/api/automations/<id>/regenerate-webhook``
  * ``POST /admin/api/automations/<id>/test-run``   queue a manual (dry) run
  * ``GET  /admin/api/automations/<id>/runs``       recent runs
  * ``GET  /admin/api/automations/runs/<rid>``      run detail
  * ``POST /automations/hook/<token>``              public webhook trigger
"""

from __future__ import annotations

import json

from flask import Blueprint, request, jsonify

from ..db import query_db, execute_db
from ..auth import admin_required
from ..util import client_ip
from ..reused import automations

bp = Blueprint("automations", __name__)


@bp.route("/admin/api/automations/metadata", methods=["GET"])
@admin_required
def metadata():
    return jsonify({"triggers": automations.trigger_metadata(),
                    "actions": automations.action_metadata(),
                    "condition_operators": automations.condition_operator_metadata()})


@bp.route("/admin/api/automations/settings", methods=["GET"])
@admin_required
def get_settings():
    return jsonify(automations.retention_settings())


@bp.route("/admin/api/automations/settings", methods=["PUT"])
@admin_required
def put_settings():
    d = request.get_json() or {}
    execute_db("UPDATE automation_settings SET retention_days=%s, "
               "keep_recent_per_automation=%s, updated_at=NOW() WHERE id=1",
               (d.get("retention_days"), d.get("keep_recent_per_automation")))
    return jsonify(automations.retention_settings())


@bp.route("/admin/api/automations", methods=["GET"])
@admin_required
def list_automations():
    rows = query_db("SELECT id, name, description, enabled, trigger_type, "
                    "last_run_at, last_run_status, next_scheduled_at, updated_at "
                    "FROM automations ORDER BY updated_at DESC")
    return jsonify({"automations": rows or []})


@bp.route("/admin/api/automations", methods=["POST"])
@admin_required
def create_automation():
    d = request.get_json() or {}
    row = execute_db(
        "INSERT INTO automations (name, description, enabled, trigger_type, "
        " trigger_config, action_steps) VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb) RETURNING *",
        (d.get("name", "Untitled automation"), d.get("description", ""),
         bool(d.get("enabled", False)), d.get("trigger_type", "manual"),
         json.dumps(d.get("trigger_config", {})), json.dumps(d.get("action_steps", []))))
    return jsonify(row), 201


@bp.route("/admin/api/automations/<int:aid>", methods=["GET"])
@admin_required
def get_automation(aid):
    row = query_db("SELECT * FROM automations WHERE id=%s", (aid,), fetchone=True)
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/automations/<int:aid>", methods=["PUT"])
@admin_required
def update_automation(aid):
    d = request.get_json() or {}
    cur = query_db("SELECT * FROM automations WHERE id=%s", (aid,), fetchone=True)
    if not cur:
        return jsonify({"error": "Not found"}), 404
    # Snapshot the prior content as a new version before overwriting.
    vno = (query_db("SELECT COALESCE(MAX(version_no),0) AS v FROM automation_versions "
                    "WHERE automation_id=%s", (aid,), fetchone=True) or {}).get("v", 0) + 1
    execute_db("INSERT INTO automation_versions (automation_id, version_no, snapshot) "
               "VALUES (%s,%s,%s::jsonb)", (aid, vno, json.dumps({
                   "name": cur["name"], "description": cur["description"],
                   "trigger_type": cur["trigger_type"], "trigger_config": cur["trigger_config"],
                   "action_steps": cur["action_steps"]})))
    row = execute_db(
        "UPDATE automations SET name=%s, description=%s, trigger_type=%s, "
        " trigger_config=%s::jsonb, action_steps=%s::jsonb, updated_at=NOW() "
        "WHERE id=%s RETURNING *",
        (d.get("name", cur["name"]), d.get("description", cur["description"]),
         d.get("trigger_type", cur["trigger_type"]),
         json.dumps(d.get("trigger_config", cur["trigger_config"])),
         json.dumps(d.get("action_steps", cur["action_steps"])), aid))
    return jsonify(row)


@bp.route("/admin/api/automations/<int:aid>", methods=["DELETE"])
@admin_required
def delete_automation(aid):
    execute_db("DELETE FROM automations WHERE id=%s", (aid,))
    return jsonify({"success": True})


@bp.route("/admin/api/automations/<int:aid>/toggle", methods=["POST"])
@admin_required
def toggle(aid):
    row = execute_db("UPDATE automations SET enabled = NOT enabled, updated_at=NOW() "
                     "WHERE id=%s RETURNING id, enabled", (aid,))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/automations/<int:aid>/regenerate-webhook", methods=["POST"])
@admin_required
def regen_webhook(aid):
    token = automations.generate_webhook_token()
    row = execute_db("UPDATE automations SET webhook_token=%s, updated_at=NOW() "
                     "WHERE id=%s RETURNING webhook_token", (token, aid))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/automations/<int:aid>/test-run", methods=["POST"])
@admin_required
def test_run(aid):
    d = request.get_json(silent=True) or {}
    run_id = automations.queue_run(aid, d.get("trigger_data", {}),
                                   triggered_by="manual", is_dry_run=True)
    if run_id is None:
        return jsonify({"error": "rate-limited or not runnable"}), 429
    return jsonify({"run_id": run_id})


@bp.route("/admin/api/automations/<int:aid>/runs", methods=["GET"])
@admin_required
def runs(aid):
    rows = query_db("SELECT id, status, triggered_by, is_dry_run, error_text, "
                    "queued_at, started_at, finished_at FROM automation_runs "
                    "WHERE automation_id=%s ORDER BY id DESC LIMIT 100", (aid,))
    return jsonify({"runs": rows or []})


@bp.route("/admin/api/automations/runs/<int:rid>", methods=["GET"])
@admin_required
def run_detail(rid):
    row = query_db("SELECT * FROM automation_runs WHERE id=%s", (rid,), fetchone=True)
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/automations/hook/<token>", methods=["POST"])
def webhook(token):
    """Public webhook trigger. Matches an automation by its webhook_token and
    queues a run with the posted JSON as trigger data."""
    if not token:
        return jsonify({"error": "missing token"}), 400
    auto = query_db("SELECT id, enabled FROM automations WHERE webhook_token=%s",
                    (token,), fetchone=True)
    if not auto:
        return jsonify({"error": "unknown webhook"}), 404
    if not auto["enabled"]:
        return jsonify({"error": "automation disabled"}), 409
    payload = request.get_json(silent=True) or {}
    run_id = automations.queue_run(auto["id"], {"webhook": payload, "ip": client_ip()},
                                   triggered_by="webhook")
    if run_id is None:
        return jsonify({"error": "rate-limited"}), 429
    return jsonify({"queued": True, "run_id": run_id})
