"""
admin_ai_platform.blueprints.scraper
====================================

Web scraper admin: one-off jobs (URL fetch or objective research → AI-extracted
structured record) and recurring schedules. The fetch/clean/extract engine is
the relocated ``reused/scraper.py`` (SSRF-guarded fetch, HTML clean, JSON-mode
extraction). Config lives in the ``scraper_settings`` singleton.

  * ``GET/POST /admin/api/scrape-jobs``           list / create+run
  * ``GET/DELETE /admin/api/scrape-jobs/<id>``    detail / delete
  * ``POST /admin/api/scrape-jobs/<id>/stop``     request cooperative stop
  * ``GET/PUT /admin/api/scraper-settings``       disallowed domains + render toggle
  * ``GET /admin/api/scraper-status``             render-provider status
  * ``GET/POST /admin/api/scrape-schedules``      list / create
  * ``PATCH/DELETE /admin/api/scrape-schedules/<id>``  edit / delete
  * ``POST /admin/api/scrape-schedules/<id>/run-now``  spawn a job now
  * ``POST /admin/api/scrape-schedules/<id>/resume``   clear auto-pause
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify

from .. import llm
from ..db import query_db, execute_db
from ..auth import admin_required
from ..reused import scraper

bp = Blueprint("scraper", __name__)


def _disallowed():
    row = query_db("SELECT disallowed_domains FROM scraper_settings WHERE id=1", fetchone=True)
    return scraper.parse_disallowed_domains((row or {}).get("disallowed_domains", ""))


def _run_job(job_id):
    """Execute a scrape job inline (fetch -> clean -> AI extract). Best-effort;
    records status + result/error on the row. Runs in a daemon thread."""
    job = query_db("SELECT * FROM scrape_jobs WHERE id=%s", (job_id,), fetchone=True)
    if not job:
        return
    execute_db("UPDATE scrape_jobs SET status='running' WHERE id=%s", (job_id,))
    try:
        if job["input_mode"] == "objective":
            research = scraper.research_objective(llm.openai_client, llm.openai_direct_client,
                                                  job["objective"])
            source_text = research.get("notes") or json.dumps(research)
            extracted = scraper.extract_with_ai(
                llm.openai_client, source_text, job["target_shape"],
                job.get("custom_schema"), source_kind="objective",
                source_label=job["objective"])
        else:
            fetched = scraper.fetch_url(job["url"], _disallowed())
            if not fetched.get("ok"):
                raise RuntimeError(fetched.get("error") or "fetch failed")
            cleaned = scraper.clean_html(fetched.get("body", ""), fetched.get("content_type", ""))
            extracted = scraper.extract_with_ai(
                llm.openai_client, cleaned, job["target_shape"],
                job.get("custom_schema"), source_kind="url", source_label=job["url"])
        execute_db("UPDATE scrape_jobs SET status='done', result_json=%s::jsonb, "
                   "completed_at=NOW() WHERE id=%s", (json.dumps(extracted), job_id))
    except Exception as e:
        execute_db("UPDATE scrape_jobs SET status='error', error=%s, completed_at=NOW() "
                   "WHERE id=%s", (str(e)[:500], job_id))


@bp.route("/admin/api/scrape-jobs", methods=["GET"])
@admin_required
def list_jobs():
    rows = query_db("SELECT id, input_mode, url, objective, target_shape, status, error, "
                    "requested_at, completed_at FROM scrape_jobs "
                    "WHERE schedule_id IS NULL ORDER BY id DESC LIMIT 100")
    return jsonify({"jobs": rows or []})


@bp.route("/admin/api/scrape-jobs", methods=["POST"])
@admin_required
def create_job():
    d = request.get_json() or {}
    mode = d.get("input_mode", "url")
    if mode == "url" and not (d.get("url") or "").strip():
        return jsonify({"error": "url required for url mode"}), 400
    if mode == "objective" and not (d.get("objective") or "").strip():
        return jsonify({"error": "objective required for objective mode"}), 400
    row = execute_db(
        "INSERT INTO scrape_jobs (input_mode, url, objective, target_shape, custom_schema) "
        "VALUES (%s,%s,%s,%s,%s::jsonb) RETURNING id",
        (mode, d.get("url", ""), d.get("objective", ""), d.get("target_shape", "free_form"),
         json.dumps(d.get("custom_schema")) if d.get("custom_schema") else None))
    job_id = row["id"]
    threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
    return jsonify({"id": job_id, "status": "queued"}), 201


@bp.route("/admin/api/scrape-jobs/<int:job_id>", methods=["GET"])
@admin_required
def get_job(job_id):
    row = query_db("SELECT * FROM scrape_jobs WHERE id=%s", (job_id,), fetchone=True)
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/scrape-jobs/<int:job_id>", methods=["DELETE"])
@admin_required
def delete_job(job_id):
    execute_db("DELETE FROM scrape_jobs WHERE id=%s", (job_id,))
    return jsonify({"success": True})


@bp.route("/admin/api/scrape-jobs/<int:job_id>/stop", methods=["POST"])
@admin_required
def stop_job(job_id):
    execute_db("UPDATE scrape_jobs SET stop_requested=TRUE WHERE id=%s", (job_id,))
    return jsonify({"success": True})


@bp.route("/admin/api/scraper-settings", methods=["GET"])
@admin_required
def get_settings():
    row = query_db("SELECT * FROM scraper_settings WHERE id=1", fetchone=True)
    return jsonify(row or {})


@bp.route("/admin/api/scraper-settings", methods=["PUT"])
@admin_required
def put_settings():
    d = request.get_json() or {}
    row = execute_db("UPDATE scraper_settings SET disallowed_domains=%s, render_enabled=%s, "
                     "updated_at=NOW() WHERE id=1 RETURNING *",
                     (d.get("disallowed_domains", ""), bool(d.get("render_enabled", False))))
    return jsonify(row)


@bp.route("/admin/api/scraper-status", methods=["GET"])
@admin_required
def status():
    return jsonify(scraper.render_provider_status())


# ---- Schedules ----------------------------------------------------------
_SCHED_FIELDS = ("name", "input_mode", "url", "objective", "target_shape", "schedule_mode",
                 "interval_minutes", "daily_time", "weekly_dow", "enabled", "notify_email",
                 "notify_phone", "notify_only_on_change", "failure_threshold")


@bp.route("/admin/api/scrape-schedules", methods=["GET"])
@admin_required
def list_schedules():
    rows = query_db("SELECT * FROM scrape_schedules ORDER BY id DESC")
    return jsonify({"schedules": rows or []})


@bp.route("/admin/api/scrape-schedules", methods=["POST"])
@admin_required
def create_schedule():
    d = request.get_json() or {}
    row = execute_db(
        "INSERT INTO scrape_schedules (name, input_mode, url, objective, target_shape, "
        " custom_schema, schedule_mode, interval_minutes, daily_time, weekly_dow, enabled, "
        " notify_email, notify_phone, notify_only_on_change) "
        "VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (d.get("name", ""), d.get("input_mode", "url"), d.get("url", ""), d.get("objective", ""),
         d.get("target_shape", "free_form"),
         json.dumps(d.get("custom_schema")) if d.get("custom_schema") else None,
         d.get("schedule_mode", "daily"), int(d.get("interval_minutes", 60) or 60),
         d.get("daily_time", "09:00"), int(d.get("weekly_dow", 1) or 1),
         bool(d.get("enabled", True)), d.get("notify_email", ""), d.get("notify_phone", ""),
         bool(d.get("notify_only_on_change", True))))
    return jsonify(row), 201


@bp.route("/admin/api/scrape-schedules/<int:sid>", methods=["PATCH"])
@admin_required
def patch_schedule(sid):
    d = request.get_json() or {}
    sets, vals = [], []
    for f in _SCHED_FIELDS:
        if f in d:
            sets.append(f"{f}=%s")
            vals.append(d[f])
    if not sets:
        return jsonify({"error": "No fields"}), 400
    vals.append(sid)
    row = execute_db(f"UPDATE scrape_schedules SET {', '.join(sets)} WHERE id=%s RETURNING *", tuple(vals))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/scrape-schedules/<int:sid>", methods=["DELETE"])
@admin_required
def delete_schedule(sid):
    execute_db("DELETE FROM scrape_schedules WHERE id=%s", (sid,))
    return jsonify({"success": True})


@bp.route("/admin/api/scrape-schedules/<int:sid>/run-now", methods=["POST"])
@admin_required
def run_now(sid):
    sch = query_db("SELECT * FROM scrape_schedules WHERE id=%s", (sid,), fetchone=True)
    if not sch:
        return jsonify({"error": "Not found"}), 404
    row = execute_db(
        "INSERT INTO scrape_jobs (input_mode, url, objective, target_shape, custom_schema, schedule_id) "
        "VALUES (%s,%s,%s,%s,%s::jsonb,%s) RETURNING id",
        (sch["input_mode"], sch["url"], sch["objective"], sch["target_shape"],
         json.dumps(sch.get("custom_schema")) if sch.get("custom_schema") else None, sid))
    threading.Thread(target=_run_job, args=(row["id"],), daemon=True).start()
    return jsonify({"job_id": row["id"]})


@bp.route("/admin/api/scrape-schedules/<int:sid>/resume", methods=["POST"])
@admin_required
def resume_schedule(sid):
    row = execute_db("UPDATE scrape_schedules SET auto_paused=FALSE, consecutive_failures=0, "
                     "next_run_at=NOW() WHERE id=%s RETURNING id", (sid,))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"success": True})


# ---- scheduler tick -----------------------------------------------------
def _compute_next_run(sch, from_dt=None):
    """Next UTC run time for a schedule given its mode. ``interval`` adds
    ``interval_minutes``; ``daily`` targets ``daily_time`` HH:MM; ``weekly``
    targets ``weekly_dow`` (0=Mon) at ``daily_time``. Falls back to +60min on a
    malformed config so a bad row can't wedge the loop."""
    base = from_dt or datetime.utcnow()
    mode = (sch.get("schedule_mode") or "daily").lower()
    try:
        if mode == "interval":
            # 0/None is not a sane interval → fall back to hourly.
            mins = int(sch.get("interval_minutes") or 60)
            return base + timedelta(minutes=max(1, mins))
        hh, mm = (sch.get("daily_time") or "09:00").split(":")
        target = base.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if mode == "weekly":
            # weekly_dow=0 (Monday) is valid, so don't use `or` (it's falsy) —
            # only substitute the default when the value is genuinely missing.
            dow = sch.get("weekly_dow")
            want_dow = (int(dow) if dow is not None else 1) % 7
            days = (want_dow - target.weekday()) % 7
            target = target + timedelta(days=days)
            if target <= base:
                target = target + timedelta(days=7)
            return target
        # daily
        if target <= base:
            target = target + timedelta(days=1)
        return target
    except Exception:
        return base + timedelta(minutes=60)


def scrape_schedule_tick():
    """Scheduler tick: dispatch any enabled, non-paused schedule whose
    ``next_run_at`` is due (or unset). Before dispatching, fold the *previous*
    job's outcome into the failure counter and auto-pause once the threshold is
    crossed. Best-effort; one bad schedule never blocks the others."""
    try:
        due = query_db(
            "SELECT * FROM scrape_schedules WHERE enabled = TRUE AND auto_paused = FALSE "
            "  AND (next_run_at IS NULL OR next_run_at <= NOW())") or []
    except Exception as e:
        print(f"[scraper] schedule_tick query failed: {e}")
        return
    now = datetime.utcnow()
    for sch in due:
        sid = sch["id"]
        try:
            # Fold the last job's result into the failure counter / auto-pause.
            last_job_id = sch.get("last_job_id")
            if last_job_id:
                lj = query_db("SELECT status FROM scrape_jobs WHERE id=%s", (last_job_id,),
                              fetchone=True)
                if lj and lj.get("status") == "error":
                    fails = int(sch.get("consecutive_failures") or 0) + 1
                    threshold = int(sch.get("failure_threshold") or 5)
                    if fails >= threshold:
                        execute_db("UPDATE scrape_schedules SET consecutive_failures=%s, "
                                   "auto_paused=TRUE WHERE id=%s", (fails, sid))
                        continue
                    execute_db("UPDATE scrape_schedules SET consecutive_failures=%s WHERE id=%s",
                               (fails, sid))
                elif lj and lj.get("status") == "done":
                    execute_db("UPDATE scrape_schedules SET consecutive_failures=0 WHERE id=%s",
                               (sid,))
            # Spawn the job for this run.
            job = execute_db(
                "INSERT INTO scrape_jobs (input_mode, url, objective, target_shape, custom_schema, "
                " schedule_id) VALUES (%s,%s,%s,%s,%s::jsonb,%s) RETURNING id",
                (sch["input_mode"], sch["url"], sch["objective"], sch["target_shape"],
                 json.dumps(sch.get("custom_schema")) if sch.get("custom_schema") else None, sid))
            next_run = _compute_next_run(sch, now)
            execute_db("UPDATE scrape_schedules SET last_run_at=NOW(), last_job_id=%s, "
                       "next_run_at=%s WHERE id=%s", (job["id"], next_run, sid))
            threading.Thread(target=_run_job, args=(job["id"],), daemon=True).start()
        except Exception as e:
            print(f"[scraper] schedule_tick dispatch failed for {sid}: {e}")
