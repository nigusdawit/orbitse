"""
admin_ai_platform.blueprints.presentations
==========================================

Presentation decks the AI can launch on a visitor's screen with voice narration
(via the start_presentation command + lookup_presentation tool). Admin CRUD for
decks + ordered slides; public read by slug.

  * ``GET/POST /admin/api/presentations`` + ``GET/PUT/DELETE /<id>``
  * ``POST /admin/api/presentations/<id>/slides``   add a slide
  * ``PUT/DELETE /admin/api/slides/<sid>``          edit / remove a slide
  * ``GET /api/presentations/<slug>``               public deck + slides
  * ``POST /admin/api/presentations/import``         Office/PPTX → deck + slides
  * ``POST /admin/api/presentations/<id>/generate-narration``  AI narration

Import extracts slide text + speaker notes with python-pptx (no external tools
needed). Per-slide images are rendered best-effort via LibreOffice
(``soffice`` → PDF) + ``pdftoppm`` when those binaries are present; when they're
not, the deck still imports with text + narration and a clear note.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time

from flask import Blueprint, request, jsonify

from .. import config
from ..db import query_db, execute_db
from ..auth import admin_required

bp = Blueprint("presentations", __name__)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,119}$")
# Office presentation formats python-pptx/LibreOffice can ingest.
_IMPORT_EXT = {".pptx", ".ppt", ".odp", ".key"}


@bp.route("/admin/api/presentations", methods=["GET"])
@admin_required
def list_decks():
    return jsonify({"presentations": query_db(
        "SELECT p.*, (SELECT COUNT(*) FROM presentation_slides WHERE presentation_id=p.id) "
        "AS slide_count FROM presentations p ORDER BY p.id DESC") or []})


@bp.route("/admin/api/presentations", methods=["POST"])
@admin_required
def create_deck():
    d = request.get_json() or {}
    slug = (d.get("slug") or "").strip().lower()
    if not _SLUG_RE.match(slug):
        return jsonify({"error": "slug must match ^[a-z0-9][a-z0-9-]{0,119}$"}), 400
    row = execute_db(
        "INSERT INTO presentations (slug, title, description, cover_image_url, source, "
        " auto_play, enabled) VALUES (%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (slug) DO NOTHING RETURNING *",
        (slug, d.get("title", ""), d.get("description", ""), d.get("cover_image_url", ""),
         d.get("source", "admin"), bool(d.get("auto_play", False)), bool(d.get("enabled", True))))
    if not row:
        return jsonify({"error": "slug already exists"}), 409
    return jsonify(row), 201


@bp.route("/admin/api/presentations/<int:pid>", methods=["GET"])
@admin_required
def get_deck(pid):
    deck = query_db("SELECT * FROM presentations WHERE id=%s", (pid,), fetchone=True)
    if not deck:
        return jsonify({"error": "Not found"}), 404
    deck["slides"] = query_db("SELECT * FROM presentation_slides WHERE presentation_id=%s "
                              "ORDER BY order_index, id", (pid,)) or []
    return jsonify(deck)


@bp.route("/admin/api/presentations/<int:pid>", methods=["PUT"])
@admin_required
def update_deck(pid):
    d = request.get_json() or {}
    sets, vals = [], []
    for k in ("title", "description", "cover_image_url", "auto_play", "enabled"):
        if k in d:
            sets.append(f"{k}=%s")
            vals.append(d[k])
    if not sets:
        return jsonify({"error": "No fields"}), 400
    vals.append(pid)
    row = execute_db(f"UPDATE presentations SET {', '.join(sets)} WHERE id=%s RETURNING *", tuple(vals))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/presentations/<int:pid>", methods=["DELETE"])
@admin_required
def delete_deck(pid):
    execute_db("DELETE FROM presentations WHERE id=%s", (pid,))
    return jsonify({"success": True})


@bp.route("/admin/api/presentations/<int:pid>/slides", methods=["POST"])
@admin_required
def add_slide(pid):
    if not query_db("SELECT 1 FROM presentations WHERE id=%s", (pid,), fetchone=True):
        return jsonify({"error": "deck not found"}), 404
    d = request.get_json() or {}
    nxt = (query_db("SELECT COALESCE(MAX(order_index),-1)+1 AS n FROM presentation_slides "
                    "WHERE presentation_id=%s", (pid,), fetchone=True) or {}).get("n", 0)
    row = execute_db(
        "INSERT INTO presentation_slides (presentation_id, order_index, title, body, "
        " image_url, narration_text) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
        (pid, int(d.get("order_index", nxt)), d.get("title", ""), d.get("body", ""),
         d.get("image_url", ""), d.get("narration_text", "")))
    return jsonify(row), 201


@bp.route("/admin/api/slides/<int:sid>", methods=["PUT"])
@admin_required
def update_slide(sid):
    d = request.get_json() or {}
    sets, vals = [], []
    for k in ("order_index", "title", "body", "image_url", "narration_text"):
        if k in d:
            sets.append(f"{k}=%s")
            vals.append(d[k])
    if not sets:
        return jsonify({"error": "No fields"}), 400
    vals.append(sid)
    row = execute_db(f"UPDATE presentation_slides SET {', '.join(sets)} WHERE id=%s RETURNING *", tuple(vals))
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row)


@bp.route("/admin/api/slides/<int:sid>", methods=["DELETE"])
@admin_required
def delete_slide(sid):
    execute_db("DELETE FROM presentation_slides WHERE id=%s", (sid,))
    return jsonify({"success": True})


# ---- import (Office/PPTX) ----------------------------------------------
def _unique_slug(base):
    """A slug derived from ``base`` that doesn't collide with an existing deck."""
    slug = re.sub(r"[^a-z0-9]+", "-", (base or "deck").lower()).strip("-")[:110] or "deck"
    candidate = slug
    n = 1
    while query_db("SELECT 1 FROM presentations WHERE slug=%s", (candidate,), fetchone=True):
        n += 1
        candidate = f"{slug}-{n}"
    return candidate


def _extract_pptx(path):
    """Return [{title, body, narration}] from a .pptx via python-pptx. Title =
    the slide's title placeholder (or first text); body = remaining text; the
    narration seed = the slide's speaker notes. Lazy import so the package boots
    without python-pptx installed."""
    from pptx import Presentation
    prs = Presentation(path)
    out = []
    for slide in prs.slides:
        title = ""
        try:
            if slide.shapes.title and slide.shapes.title.text:
                title = slide.shapes.title.text.strip()
        except Exception:
            pass
        texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                t = shape.text_frame.text.strip()
                if t and t != title:
                    texts.append(t)
        notes = ""
        try:
            if slide.has_notes_slide:
                notes = (slide.notes_slide.notes_text_frame.text or "").strip()
        except Exception:
            pass
        out.append({"title": title or (texts[0][:120] if texts else "Slide"),
                    "body": "\n".join(texts), "narration": notes})
    return out


def _render_slide_images(path, ext):
    """Best-effort per-slide JPGs via LibreOffice (→PDF) + pdftoppm. Returns a
    list of public ``/uploads/...`` URLs (one per page) or [] when the tools
    aren't available — the import still succeeds with text + narration."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    pdftoppm = shutil.which("pdftoppm")
    if not soffice:
        return []
    uploads = os.path.abspath(config.UPLOADS_DIR)
    os.makedirs(uploads, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, path],
                           check=True, timeout=120, capture_output=True)
        except Exception as e:
            print(f"[presentations] soffice convert failed: {e}")
            return []
        pdfs = [f for f in os.listdir(tmp) if f.lower().endswith(".pdf")]
        if not pdfs:
            return []
        pdf_path = os.path.join(tmp, pdfs[0])
        if not pdftoppm:
            return []
        stamp = int(time.time())
        prefix = os.path.join(uploads, f"slide-{stamp}")
        try:
            subprocess.run([pdftoppm, "-jpeg", "-r", "120", pdf_path, prefix],
                           check=True, timeout=120, capture_output=True)
        except Exception as e:
            print(f"[presentations] pdftoppm failed: {e}")
            return []
        imgs = sorted(f for f in os.listdir(uploads) if f.startswith(f"slide-{stamp}"))
        return [f"/uploads/{f}" for f in imgs]


@bp.route("/admin/api/presentations/import", methods=["POST"])
@admin_required
def import_deck():
    """Import an Office/PPTX file as a deck: text + speaker-notes via python-pptx,
    per-slide images best-effort via LibreOffice. Rejects unsupported types."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f or not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in _IMPORT_EXT:
        return jsonify({"error": f"Unsupported type {ext}; expected one of "
                        f"{sorted(_IMPORT_EXT)}"}), 400

    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, f"upload{ext}")
        f.save(src)
        slides = []
        note = ""
        if ext == ".pptx":
            try:
                slides = _extract_pptx(src)
            except Exception as e:
                return jsonify({"error": f"could not parse pptx: {str(e)[:200]}"}), 422
        else:
            # .ppt/.odp/.key need LibreOffice to extract text; we still create the
            # deck and render images if soffice is present.
            note = f"text extraction for {ext} requires .pptx; only images imported"
        images = _render_slide_images(src, ext)

    title = os.path.splitext(os.path.basename(f.filename))[0][:200] or "Imported deck"
    slug = _unique_slug(title)
    deck = execute_db(
        "INSERT INTO presentations (slug, title, description, source, enabled) "
        "VALUES (%s,%s,%s,'import',TRUE) RETURNING *",
        (slug, title, note))
    # If we have neither parsed slides nor images, still create one placeholder
    # row per rendered image; if both empty, create a single empty slide.
    n = max(len(slides), len(images), 1)
    created = 0
    for i in range(n):
        s = slides[i] if i < len(slides) else {}
        img = images[i] if i < len(images) else ""
        execute_db(
            "INSERT INTO presentation_slides (presentation_id, order_index, title, body, "
            " image_url, narration_text) VALUES (%s,%s,%s,%s,%s,%s)",
            (deck["id"], i, s.get("title", f"Slide {i + 1}"), s.get("body", ""),
             img, s.get("narration", "")))
        created += 1
    deck["slides_created"] = created
    deck["images_rendered"] = len(images)
    if note:
        deck["note"] = note
    return jsonify(deck), 201


@bp.route("/admin/api/presentations/<int:pid>/generate-narration", methods=["POST"])
@admin_required
def generate_narration(pid):
    """AI-generate speaker narration (gpt-4o-mini) for slides from their title +
    body. By default only fills slides missing narration; ``regenerate:true``
    rewrites all. Needs an LLM key."""
    from .. import llm
    if not query_db("SELECT 1 FROM presentations WHERE id=%s", (pid,), fetchone=True):
        return jsonify({"error": "deck not found"}), 404
    if llm.openai_client is None:
        return jsonify({"error": "No LLM provider configured"}), 503
    regenerate = bool((request.get_json(silent=True) or {}).get("regenerate"))
    slides = query_db("SELECT id, title, body, narration_text FROM presentation_slides "
                      "WHERE presentation_id=%s ORDER BY order_index, id", (pid,)) or []
    updated = 0
    for s in slides:
        if s.get("narration_text") and not regenerate:
            continue
        content = f"Title: {s.get('title', '')}\n\n{s.get('body', '')}".strip()
        if not content:
            continue
        try:
            resp = llm.openai_client.chat.completions.create(
                model="gpt-4o-mini", temperature=0.6, max_tokens=200,
                messages=[{"role": "system", "content": "You write natural, spoken "
                           "presenter narration for a slide — 2-4 sentences, no markdown, "
                           "no 'this slide' meta-talk."},
                          {"role": "user", "content": content}])
            narration = (resp.choices[0].message.content or "").strip()
            execute_db("UPDATE presentation_slides SET narration_text=%s WHERE id=%s",
                       (narration, s["id"]))
            updated += 1
        except Exception as e:
            print(f"[presentations] narration gen failed for slide {s['id']}: {e}")
    return jsonify({"updated": updated, "total": len(slides)})


@bp.route("/api/presentations/<slug>", methods=["GET"])
def public_deck(slug):
    deck = query_db("SELECT id, slug, title, description, cover_image_url, auto_play "
                    "FROM presentations WHERE slug=%s AND enabled=TRUE", (slug,), fetchone=True)
    if not deck:
        return jsonify({"error": "Not found"}), 404
    deck["slides"] = query_db(
        "SELECT order_index, title, body, image_url, narration_text "
        "FROM presentation_slides WHERE presentation_id=%s ORDER BY order_index, id",
        (deck["id"],)) or []
    return jsonify(deck)
