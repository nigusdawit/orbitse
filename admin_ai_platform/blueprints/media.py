"""
admin_ai_platform.blueprints.media
==================================

Image/media uploads + serving. Admin uploads land under ``UPLOADS_DIR`` and are
recorded in ``uploaded_images``; the public ``/uploads/<path>`` route serves
them (also used by the voice TTS cache from M-voice on).

Routes:
  * ``POST /admin/api/upload-image``  — upload an image, returns its URL
  * ``GET  /admin/api/media``         — list uploads
  * ``DELETE /admin/api/media/<id>``  — delete an upload (row + file)
  * ``GET  /uploads/<path:filename>`` — serve an uploaded file
"""

from __future__ import annotations

import os
import re
import time

from flask import Blueprint, request, jsonify, send_from_directory, abort

from ..db import query_db, execute_db
from ..auth import admin_required
from .. import config

bp = Blueprint("media", __name__)

_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4", ".webm", ".pdf"}
_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _uploads_root() -> str:
    root = os.path.abspath(config.UPLOADS_DIR)
    os.makedirs(root, exist_ok=True)
    return root


def _safe_filename(name: str) -> str:
    base = os.path.basename(name or "file")
    base = _SAFE_NAME_RE.sub("-", base).strip("-.") or "file"
    return base[:120]


@bp.route("/admin/api/upload-image", methods=["POST"])
@admin_required
def upload_image():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f or not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in _ALLOWED_EXT:
        return jsonify({"error": f"Disallowed file type {ext}"}), 400
    safe = _safe_filename(f.filename)
    fname = f"{int(time.time())}-{safe}"
    path = os.path.join(_uploads_root(), fname)
    f.save(path)
    size = os.path.getsize(path)
    execute_db(
        "INSERT INTO uploaded_images (filename, original_name, file_size) VALUES (%s,%s,%s)",
        (fname, f.filename[:255], size),
    )
    return jsonify({"success": True, "url": f"/uploads/{fname}", "filename": fname}), 201


@bp.route("/admin/api/media", methods=["GET"])
@admin_required
def list_media():
    rows = query_db("SELECT * FROM uploaded_images ORDER BY uploaded_at DESC")
    return jsonify(rows or [])


@bp.route("/admin/api/media/<int:media_id>", methods=["DELETE"])
@admin_required
def delete_media(media_id):
    row = query_db("SELECT filename FROM uploaded_images WHERE id = %s",
                   (media_id,), fetchone=True)
    if not row:
        return jsonify({"error": "Not found"}), 404
    # Remove the file if it lives under the uploads root (defence-in-depth).
    fpath = os.path.abspath(os.path.join(_uploads_root(), row["filename"]))
    if fpath.startswith(_uploads_root()) and os.path.isfile(fpath):
        try:
            os.remove(fpath)
        except OSError:
            pass
    execute_db("DELETE FROM uploaded_images WHERE id = %s", (media_id,))
    return jsonify({"success": True})


@bp.route("/uploads/<path:filename>", methods=["GET"])
def serve_upload(filename):
    # send_from_directory rejects path traversal; double-check the resolved path.
    root = _uploads_root()
    target = os.path.abspath(os.path.join(root, filename))
    if not target.startswith(root):
        abort(404)
    return send_from_directory(root, filename)
