"""
admin_ai_platform.blueprints.rag
================================

Knowledge Base (RAG) admin. Uploaded docs are chunked + embedded (pgvector via
the relocated reused_di/rag.py) and retrieved by cosine similarity for the
admin/visitor chat. Files are stored under ``UPLOADS_DIR/kb``.

EVERY endpoint is gated by ``schema.rag_available()`` — when pgvector isn't
installed the KB degrades to a clean 503 instead of erroring.

  * ``GET  /admin/api/kb/list``              list documents
  * ``POST /admin/api/kb/upload``            upload + ingest a file
  * ``POST /admin/api/kb/preview``           retrieve top-K chunks for a query
  * ``POST /admin/api/kb/<id>/reindex``      re-embed a document
  * ``DELETE /admin/api/kb/<id>``            delete a document + its chunks
  * ``GET  /admin/api/kb/chunk/<id>``        one chunk's text (citation viewer)
"""

from __future__ import annotations

import os
import time

from flask import Blueprint, request, jsonify

from ..auth import admin_required
from ..tenancy import current_tenant_id
from .. import config
from ..schema import rag_available
from ..reused_di import rag

bp = Blueprint("rag", __name__)

_ALLOWED = {".pdf", ".docx", ".pptx", ".csv", ".txt", ".md"}
_MAX_BYTES = 25 * 1024 * 1024


def _kb_dir():
    d = os.path.join(os.path.abspath(config.UPLOADS_DIR), "kb")
    os.makedirs(d, exist_ok=True)
    return d


def _guard():
    """Return a 503 response tuple if RAG is unavailable, else None."""
    if not rag_available():
        return jsonify({"error": "Knowledge base unavailable — pgvector is not "
                                 "installed on this database."}), 503
    return None


@bp.route("/admin/api/kb/list", methods=["GET"])
@admin_required
def kb_list():
    g = _guard()
    if g:
        return g
    return jsonify({"documents": rag.list_documents(tenant_id=current_tenant_id())})


@bp.route("/admin/api/kb/upload", methods=["POST"])
@admin_required
def kb_upload():
    g = _guard()
    if g:
        return g
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    ext = os.path.splitext(f.filename or "")[1].lower()
    if ext not in _ALLOWED:
        return jsonify({"error": f"Unsupported type {ext}"}), 400
    data = f.read()
    if len(data) > _MAX_BYTES:
        return jsonify({"error": "File too large (max 25 MB)"}), 413
    if not data:
        return jsonify({"error": "Empty file"}), 400
    storage_key = f"kb/{int(time.time())}-{os.path.basename(f.filename)}"
    path = os.path.join(os.path.abspath(config.UPLOADS_DIR), storage_key)
    with open(path, "wb") as out:
        out.write(data)
    try:
        doc_id = rag.ingest_document(
            f.filename, data, tenant_id=current_tenant_id(),
            storage_key=storage_key, mime=f.mimetype or "",
            source_mtime=os.path.getmtime(path))
    except Exception as e:
        return jsonify({"error": f"ingest failed: {str(e)[:200]}"}), 500
    return jsonify({"id": doc_id, "status": "indexing"}), 201


@bp.route("/admin/api/kb/preview", methods=["POST"])
@admin_required
def kb_preview():
    g = _guard()
    if g:
        return g
    q = (request.get_json(silent=True) or {}).get("query", "").strip()
    if not q:
        return jsonify({"error": "query required"}), 400
    chunks = rag.retrieve(q, tenant_id=current_tenant_id(), top_k=6)
    return jsonify({"chunks": chunks})


@bp.route("/admin/api/kb/<int:doc_id>/reindex", methods=["POST"])
@admin_required
def kb_reindex(doc_id):
    g = _guard()
    if g:
        return g
    ok = rag.reindex_document(doc_id, read_file_bytes=_read_kb_file)
    return jsonify({"success": bool(ok)})


@bp.route("/admin/api/kb/<int:doc_id>", methods=["DELETE"])
@admin_required
def kb_delete(doc_id):
    g = _guard()
    if g:
        return g
    rag.delete_document(doc_id, tenant_id=current_tenant_id())
    return jsonify({"success": True})


@bp.route("/admin/api/kb/chunk/<int:chunk_id>", methods=["GET"])
@admin_required
def kb_chunk(chunk_id):
    g = _guard()
    if g:
        return g
    chunk = rag.get_chunk(chunk_id, tenant_id=current_tenant_id())
    if not chunk:
        return jsonify({"error": "Not found"}), 404
    return jsonify(chunk)


def _read_kb_file(storage_key):
    """Read a stored KB file's bytes (used by reindex). None if missing."""
    try:
        path = os.path.join(os.path.abspath(config.UPLOADS_DIR), storage_key)
        with open(path, "rb") as fh:
            return fh.read()
    except Exception:
        return None
