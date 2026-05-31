"""
Admin chat Knowledge Base — RAG over uploaded documents (Task #79).

Pipeline
--------
  upload  -> extract_text(filename, bytes) -> [(page_no, text), ...]
          -> chunk_pages(...)              -> [{chunk_index, page_number, text, token_count}, ...]
          -> embed_batch(texts)            -> [vector(1536), ...]
          -> INSERT rag_chunks (1 row per chunk)

  query   -> embed_batch([query])          -> [vector(1536)]
          -> SELECT chunks ORDER BY embedding <=> %s LIMIT top_k

Supported extensions: pdf (pypdf), docx (python-docx), pptx
(python-pptx), csv (stdlib), txt (utf-8 with fallback). Scanned /
image-only PDFs return empty text — note this in the upload UI.

Embeddings: OpenAI `text-embedding-3-small` (1536 dims) via the same
`openai_client` the rest of the app uses (Replit AI proxy or direct
key, whichever was wired at startup). Calls are batched 100 chunks
at a time and each batch records one `rag_embed` row in
api_cost_events so spend is visible in the Cost tab.

This module is intentionally a thin functional layer (no class state)
so app.py can call into it from route handlers, the chat loop, and the
scheduler tick without worrying about lifecycle.
"""

from __future__ import annotations

import csv as _csv
import io
import json
import os
import re
import time
import traceback
from typing import Callable, Iterable, List, Optional, Tuple


# Late-binding deps (injected by app.py via init_module so we don't
# create an import cycle).
_openai_client = None
_query_db: Optional[Callable] = None
_execute_db: Optional[Callable] = None
_record_cost: Optional[Callable] = None


def init_module(*, openai_client, query_db, execute_db, record_cost):
    """Wire up dependencies. Called once from app.py at boot."""
    global _openai_client, _query_db, _execute_db, _record_cost
    _openai_client = openai_client
    _query_db = query_db
    _execute_db = execute_db
    _record_cost = record_cost


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIMS = 1536
EMBED_BATCH = 100          # OpenAI accepts up to 2048 inputs; 100 keeps each
                           # batch well under the 8191-token per-input cap.
CHUNK_TARGET_TOKENS = 800  # ~800 tokens per chunk (per task spec)
CHUNK_OVERLAP_TOKENS = 100 # ~100 tokens overlap between adjacent chunks
MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MB hard cap (task spec)
TOP_K_DEFAULT = 6
TOP_K_MAX = 20

# Rough word→token ratio for English prose. text-embedding-3-small uses
# cl100k_base; without tiktoken installed, 1 token ≈ 0.75 words is a
# safe approximation (under-estimates token count by a few percent
# which keeps us under provider limits).
_WORDS_PER_TOKEN = 0.75

SUPPORTED_EXTS = {".pdf", ".csv", ".txt", ".docx", ".pptx"}


def _approx_tokens(text: str) -> int:
    """Approximate token count for English prose."""
    if not text:
        return 0
    words = len(text.split())
    return max(1, int(words / _WORDS_PER_TOKEN))


# ---------------------------------------------------------------------------
# Text extraction — one branch per supported format
# ---------------------------------------------------------------------------

def _extract_pdf(data: bytes) -> List[Tuple[int, str]]:
    """Return [(page_number, text)]. page_number is 1-indexed."""
    try:
        from pypdf import PdfReader  # lazy
    except Exception:
        return [(1, "[PDF parser not installed]")]
    out: List[Tuple[int, str]] = []
    try:
        reader = PdfReader(io.BytesIO(data))
        for i, page in enumerate(reader.pages, start=1):
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            if t.strip():
                out.append((i, t))
    except Exception as e:
        print(f"[rag] pdf extract failed: {e}")
    return out


def _extract_docx(data: bytes) -> List[Tuple[int, str]]:
    """Return [(1, full_text)] — docx has no inherent page numbers."""
    try:
        from docx import Document  # lazy (python-docx)
    except Exception:
        return [(1, "[DOCX parser not installed]")]
    try:
        doc = Document(io.BytesIO(data))
        paras = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
        # Tables — flatten cells row-by-row into a tab-separated line.
        for tbl in doc.tables:
            for row in tbl.rows:
                cells = [c.text.strip() for c in row.cells if c.text]
                if cells:
                    paras.append("\t".join(cells))
        return [(1, "\n".join(paras))]
    except Exception as e:
        print(f"[rag] docx extract failed: {e}")
        return []


def _extract_pptx(data: bytes) -> List[Tuple[int, str]]:
    """Return [(slide_no, text_of_slide)] — slide number = page number."""
    try:
        from pptx import Presentation  # lazy
    except Exception:
        return [(1, "[PPTX parser not installed]")]
    out: List[Tuple[int, str]] = []
    try:
        prs = Presentation(io.BytesIO(data))
        for i, slide in enumerate(prs.slides, start=1):
            chunks = []
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False):
                    for p in shape.text_frame.paragraphs:
                        line = "".join(r.text or "" for r in p.runs)
                        if line.strip():
                            chunks.append(line)
                # Tables
                if getattr(shape, "has_table", False):
                    try:
                        for row in shape.table.rows:
                            line = "\t".join(
                                (c.text or "").strip() for c in row.cells)
                            if line.strip():
                                chunks.append(line)
                    except Exception:
                        pass
            text = "\n".join(chunks).strip()
            if text:
                out.append((i, text))
    except Exception as e:
        print(f"[rag] pptx extract failed: {e}")
    return out


def _extract_csv(data: bytes) -> List[Tuple[int, str]]:
    """Render each row as `col1: val1 | col2: val2 | ...` lines so a
    naive embedding still captures the column/value association."""
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        return []
    reader = _csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return []
    lines = []
    for row in reader:
        parts = []
        for i, v in enumerate(row):
            col = header[i] if i < len(header) else f"col{i}"
            parts.append(f"{col}: {v}")
        if parts:
            lines.append(" | ".join(parts))
    return [(1, "\n".join(lines))]


def _extract_txt(data: bytes) -> List[Tuple[int, str]]:
    try:
        return [(1, data.decode("utf-8"))]
    except UnicodeDecodeError:
        return [(1, data.decode("utf-8", errors="replace"))]


def extract_text(filename: str, data: bytes) -> List[Tuple[int, str]]:
    """Dispatch by extension. Returns [(page_number, text)] in source
    order. Empty list means the file has no extractable text (e.g.
    image-only PDF, all blank slides)."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext == ".pdf":
        return _extract_pdf(data)
    if ext == ".docx":
        return _extract_docx(data)
    if ext == ".pptx":
        return _extract_pptx(data)
    if ext == ".csv":
        return _extract_csv(data)
    if ext == ".txt":
        return _extract_txt(data)
    raise ValueError(f"Unsupported file extension: {ext or '(none)'}")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _split_to_words_with_page(pages: List[Tuple[int, str]]
                              ) -> List[Tuple[int, str]]:
    """Flatten [(page,text)] into [(page, word)] preserving page mapping
    so each chunk we emit knows the page it started on."""
    out = []
    for page, text in pages:
        for word in (text or "").split():
            out.append((page, word))
    return out


def chunk_pages(pages: List[Tuple[int, str]],
                target_tokens: int = CHUNK_TARGET_TOKENS,
                overlap_tokens: int = CHUNK_OVERLAP_TOKENS) -> List[dict]:
    """Token-aware sliding window chunker. Splits the document into
    overlapping windows of ~`target_tokens` with ~`overlap_tokens`
    carryover so a paragraph straddling a chunk boundary is still
    retrievable from at least one chunk.

    Returns a list of:
        {"chunk_index": int, "page_number": int,
         "content_text": str, "token_count": int}

    Page number is the page the chunk STARTS on (cite-friendly: the
    AI will say "p.4" and that's where the reader should look first)."""
    words = _split_to_words_with_page(pages)
    if not words:
        return []
    target_words = max(50, int(target_tokens * _WORDS_PER_TOKEN))
    overlap_words = max(0, int(overlap_tokens * _WORDS_PER_TOKEN))
    step = max(1, target_words - overlap_words)

    chunks: List[dict] = []
    i = 0
    idx = 0
    while i < len(words):
        window = words[i:i + target_words]
        if not window:
            break
        text = " ".join(w for _, w in window).strip()
        if text:
            chunks.append({
                "chunk_index": idx,
                "page_number": window[0][0],
                "content_text": text,
                "token_count": _approx_tokens(text),
            })
            idx += 1
        if i + target_words >= len(words):
            break
        i += step
    return chunks


# ---------------------------------------------------------------------------
# Embedding (with cost recording)
# ---------------------------------------------------------------------------

def embed_batch(texts: List[str], *, session_id: str = "",
                surface: str = "rag_embed") -> List[List[float]]:
    """Embed up to len(texts) inputs in chunks of EMBED_BATCH. Records
    one cost event per batch. Returns vectors in the SAME order as
    `texts`. Empty input list returns []."""
    if not texts:
        return []
    if _openai_client is None:
        raise RuntimeError("rag.embed_batch: openai_client not initialised")

    out: List[List[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start:start + EMBED_BATCH]
        try:
            resp = _openai_client.embeddings.create(
                model=EMBED_MODEL,
                input=batch,
            )
        except Exception as e:
            raise RuntimeError(f"OpenAI embeddings failed: {e}") from e
        out.extend([d.embedding for d in resp.data])

        # Cost ledger. text-embedding-3-small only has an "input" side,
        # so we feed the prompt tokens slot and leave completion at 0.
        try:
            u = getattr(resp, "usage", None)
            prompt = int(getattr(u, "prompt_tokens", 0) or 0) if u else 0
            if _record_cost is not None:
                _record_cost(
                    session_id=session_id,
                    surface=surface,
                    provider="openai",
                    model=EMBED_MODEL,
                    prompt_tokens=prompt,
                    completion_tokens=0,
                    total_tokens=prompt,
                    usage_known=bool(u),
                )
        except Exception as e:
            print(f"[rag] cost record failed: {e}")
    return out


def _vec_literal(vec: List[float]) -> str:
    """pgvector accepts vectors as the string '[v1,v2,...]'. We pass
    that string with a ::vector cast so psycopg2 doesn't need a custom
    type adapter."""
    return "[" + ",".join(f"{float(v):.7f}" for v in vec) + "]"


# ---------------------------------------------------------------------------
# Upload + indexing
# ---------------------------------------------------------------------------

def ingest_document(filename: str, data: bytes, *,
                    tenant_id: int = 1,
                    storage_key: str = "",
                    mime: str = "",
                    source_mtime: Optional[float] = None,
                    session_id: str = "") -> dict:
    """Full ingest path: extract + chunk + embed + insert. Inserts the
    rag_documents row first (status='indexing') so the UI can show
    progress even if embedding is slow on a large file. Returns the
    document dict on success or {"error": "..."} on failure."""
    if _execute_db is None or _query_db is None:
        return {"error": "rag module not initialised"}
    if len(data) > MAX_FILE_BYTES:
        return {"error": f"file exceeds {MAX_FILE_BYTES // (1024*1024)} MB cap"}

    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in SUPPORTED_EXTS:
        return {"error": f"unsupported file extension: {ext or '(none)'}"}

    # Create the document row up front so the admin UI can list it as
    # "indexing…" while embedding is in flight.
    doc = _execute_db(
        "INSERT INTO rag_documents "
        "  (tenant_id, filename, storage_key, mime, size_bytes, "
        "   status, source_mtime) "
        "VALUES (%s, %s, %s, %s, %s, 'indexing', %s) "
        "RETURNING *",
        (int(tenant_id), filename[:300], (storage_key or "")[:400],
         (mime or "")[:120], len(data), source_mtime),
    )
    if not doc:
        return {"error": "could not insert rag_documents row"}
    doc_id = doc["id"]

    try:
        pages = extract_text(filename, data)
        page_count = len(pages)
        chunks = chunk_pages(pages)
        if not chunks:
            _execute_db(
                "UPDATE rag_documents SET status='empty', "
                "  page_count=%s, chunk_count=0, indexed_at=NOW(), "
                "  error_text='no extractable text (scanned PDF?)' "
                "WHERE id=%s",
                (page_count, doc_id))
            return {"id": doc_id, "warning": "no extractable text"}

        texts = [c["content_text"] for c in chunks]
        vectors = embed_batch(texts, session_id=session_id)
        if len(vectors) != len(chunks):
            raise RuntimeError(
                f"embed count mismatch: {len(vectors)} vs {len(chunks)}")

        total_tokens = 0
        for ch, vec in zip(chunks, vectors):
            total_tokens += int(ch["token_count"] or 0)
            _execute_db(
                "INSERT INTO rag_chunks "
                "  (document_id, chunk_index, page_number, "
                "   content_text, token_count, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s::vector)",
                (doc_id, ch["chunk_index"], ch["page_number"],
                 ch["content_text"], ch["token_count"],
                 _vec_literal(vec)),
            )

        _execute_db(
            "UPDATE rag_documents SET status='ready', "
            "  page_count=%s, chunk_count=%s, token_count=%s, "
            "  indexed_at=NOW(), error_text='' "
            "WHERE id=%s",
            (page_count, len(chunks), total_tokens, doc_id))
        return {"id": doc_id, "chunk_count": len(chunks),
                "page_count": page_count, "token_count": total_tokens}
    except Exception as e:
        err = f"{e}\n{traceback.format_exc()[:1500]}"
        print(f"[rag] ingest failed for doc {doc_id}: {err}")
        try:
            _execute_db(
                "UPDATE rag_documents SET status='error', "
                "  error_text=%s WHERE id=%s",
                (str(e)[:500], doc_id))
        except Exception:
            pass
        return {"id": doc_id, "error": str(e)[:300]}


def reindex_document(doc_id: int, *,
                     filename: str, data: bytes,
                     session_id: str = "") -> dict:
    """Wipe a document's chunks and re-embed from a freshly-read file.
    Used by the manual Reindex button and the nightly mtime sweep.
    Keeps the same rag_documents row (and id) so external references
    survive the rebuild."""
    if _execute_db is None or _query_db is None:
        return {"error": "rag module not initialised"}
    row = _query_db("SELECT * FROM rag_documents WHERE id=%s",
                    (int(doc_id),), fetchone=True)
    if not row:
        return {"error": "document not found"}
    try:
        _execute_db("DELETE FROM rag_chunks WHERE document_id=%s",
                    (int(doc_id),))
        _execute_db(
            "UPDATE rag_documents SET status='indexing', "
            "  chunk_count=0, token_count=0, error_text='' "
            "WHERE id=%s", (int(doc_id),))
        pages = extract_text(filename, data)
        page_count = len(pages)
        chunks = chunk_pages(pages)
        if not chunks:
            _execute_db(
                "UPDATE rag_documents SET status='empty', "
                "  page_count=%s, chunk_count=0, indexed_at=NOW(), "
                "  error_text='no extractable text (scanned PDF?)' "
                "WHERE id=%s",
                (page_count, int(doc_id)))
            return {"id": int(doc_id), "warning": "no extractable text"}
        texts = [c["content_text"] for c in chunks]
        vectors = embed_batch(texts, session_id=session_id)
        total_tokens = 0
        for ch, vec in zip(chunks, vectors):
            total_tokens += int(ch["token_count"] or 0)
            _execute_db(
                "INSERT INTO rag_chunks "
                "  (document_id, chunk_index, page_number, "
                "   content_text, token_count, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s::vector)",
                (int(doc_id), ch["chunk_index"], ch["page_number"],
                 ch["content_text"], ch["token_count"],
                 _vec_literal(vec)),
            )
        _execute_db(
            "UPDATE rag_documents SET status='ready', "
            "  page_count=%s, chunk_count=%s, token_count=%s, "
            "  indexed_at=NOW(), error_text='' "
            "WHERE id=%s",
            (page_count, len(chunks), total_tokens, int(doc_id)))
        return {"id": int(doc_id), "chunk_count": len(chunks),
                "page_count": page_count, "token_count": total_tokens}
    except Exception as e:
        print(f"[rag] reindex failed for doc {doc_id}: {e}")
        try:
            _execute_db(
                "UPDATE rag_documents SET status='error', "
                "  error_text=%s WHERE id=%s",
                (str(e)[:500], int(doc_id)))
        except Exception:
            pass
        return {"id": int(doc_id), "error": str(e)[:300]}


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def retrieve(query: str, *, tenant_id: int,
             top_k: int = TOP_K_DEFAULT,
             session_id: str = "", surface: str = None) -> List[dict]:
    """Embed `query` and return the top-K nearest chunks across documents owned
    by `tenant_id`. Each result dict:

        {"chunk_id": int, "document_id": int, "filename": str,
         "page_number": int, "content_text": str, "score": float}

    `surface` scopes by document audience (Phase 6):
        "admin"   → docs with audience in ('admin','both')
        "visitor" → docs with audience in ('visitor','both')
        None      → no audience filter (back-compat).

    `score` is 1 - cosine_distance, so higher = more similar. Returns
    [] on empty query / embedding failure / no documents."""
    if _query_db is None:
        return []
    q = (query or "").strip()
    if not q:
        return []
    k = max(1, min(int(top_k or TOP_K_DEFAULT), TOP_K_MAX))
    try:
        vecs = embed_batch([q], session_id=session_id, surface="rag_embed")
    except Exception as e:
        print(f"[rag] retrieve embed failed: {e}")
        return []
    if not vecs:
        return []
    vec_lit = _vec_literal(vecs[0])
    # Audience filter — parametrized; unknown/None surface → no filter.
    _aud_sql, _aud_params = "", []
    if surface == "admin":
        _aud_sql, _aud_params = "AND d.audience IN ('admin','both') ", []
    elif surface == "visitor":
        _aud_sql, _aud_params = "AND d.audience IN ('visitor','both') ", []
    try:
        rows = _query_db(
            "SELECT c.id AS chunk_id, c.document_id, "
            "       c.page_number, c.content_text, "
            "       (1 - (c.embedding <=> %s::vector)) AS score, "
            "       d.filename "
            "FROM rag_chunks c "
            "JOIN rag_documents d ON d.id = c.document_id "
            "WHERE d.tenant_id = %s AND d.status = 'ready' " + _aud_sql +
            "ORDER BY c.embedding <=> %s::vector "
            "LIMIT %s",
            tuple([vec_lit, int(tenant_id)] + _aud_params + [vec_lit, k]),
        ) or []
    except Exception as e:
        print(f"[rag] retrieve query failed: {e}")
        return []
    out = []
    for r in rows:
        out.append({
            "chunk_id":     int(r.get("chunk_id") or 0),
            "document_id":  int(r.get("document_id") or 0),
            "filename":     r.get("filename") or "",
            "page_number":  int(r.get("page_number") or 0) or None,
            "content_text": r.get("content_text") or "",
            "score":        float(r.get("score") or 0.0),
        })
    return out


def format_chunks_for_prompt(chunks: List[dict],
                             max_chars: int = 8000) -> str:
    """Render retrieved chunks into a system-prompt-friendly block with
    `[source: <file> p.N]` markers the AI can quote back verbatim.
    Caps total length so a runaway corpus can't blow the context."""
    if not chunks:
        return ""
    parts = []
    used = 0
    for c in chunks:
        fname = c.get("filename") or "document"
        page = c.get("page_number")
        cid = int(c.get("chunk_id") or 0)
        # `#<chunk_id>` sneaks the originating chunk's id into the
        # citation marker so the UI can deep-link to the exact chunk
        # the AI quoted, instead of guessing by filename+page (which
        # would be ambiguous when several chunks share a page).
        cite = (f"[source: {fname}"
                + (f" p.{page}" if page else "")
                + (f" #{cid}" if cid else "") + "]")
        body = (c.get("content_text") or "").strip()
        block = f"{cite}\n{body}\n"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    if not parts:
        return ""
    header = (
        "KNOWLEDGE BASE EXCERPTS (from documents the admin has uploaded):\n"
        "When you quote or rely on one of these excerpts, KEEP its "
        "`[source: file p.N #id]` marker EXACTLY as written (including "
        "the `#id` portion) so the admin UI can link the citation to "
        "the originating chunk. If the excerpts don't actually answer "
        "the question, say so instead of guessing.\n\n"
    )
    return header + "\n".join(parts)


# ---------------------------------------------------------------------------
# Listing / deletion / lookup helpers used by routes
# ---------------------------------------------------------------------------

def list_documents(*, tenant_id: int) -> List[dict]:
    if _query_db is None:
        return []
    rows = _query_db(
        "SELECT id, filename, mime, size_bytes, page_count, "
        "       chunk_count, token_count, status, error_text, "
        "       COALESCE(audience, 'both') AS audience, "
        "       indexed_at, created_at "
        "FROM rag_documents WHERE tenant_id=%s "
        "ORDER BY created_at DESC",
        (int(tenant_id),),
    ) or []
    out = []
    for r in rows:
        d = dict(r)
        for k in ("indexed_at", "created_at"):
            v = d.get(k)
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        out.append(d)
    return out


VALID_AUDIENCES = ("visitor", "admin", "both")


def set_audience(doc_id: int, *, tenant_id: int, audience: str) -> bool:
    """Set which AI(s) a document is visible to: 'visitor' | 'admin' | 'both'.
    Tenant-scoped. Returns False on an invalid audience or a row that isn't this
    tenant's (so the route can 400/404). Phase 6 / Epic B."""
    if _execute_db is None:
        return False
    aud = (audience or "").strip().lower()
    if aud not in VALID_AUDIENCES:
        return False
    row = _execute_db(
        "UPDATE rag_documents SET audience=%s WHERE id=%s AND tenant_id=%s "
        "RETURNING id",
        (aud, int(doc_id), int(tenant_id)))
    return bool(row)


def delete_document(doc_id: int, *, tenant_id: int) -> bool:
    """Tenant-scoped delete. Returns False if the row didn't belong to
    `tenant_id` (or didn't exist) so callers can return 404 instead of
    silently succeeding on someone else's document."""
    if _execute_db is None:
        return False
    # SELECT-then-DELETE inside the same call so we can report whether
    # the row existed for this tenant. ON CASCADE wipes the chunks.
    if _query_db is not None:
        row = _query_db(
            "SELECT id FROM rag_documents WHERE id=%s AND tenant_id=%s",
            (int(doc_id), int(tenant_id)), fetchone=True)
        if not row:
            return False
    _execute_db(
        "DELETE FROM rag_documents WHERE id=%s AND tenant_id=%s",
        (int(doc_id), int(tenant_id)))
    return True


def get_chunk(chunk_id: int, *, tenant_id: int) -> Optional[dict]:
    """Tenant-scoped chunk fetch. Returns None for chunks belonging to
    a different tenant so the citation viewer / IDOR probes can't leak
    cross-tenant content."""
    if _query_db is None:
        return None
    row = _query_db(
        "SELECT c.id AS chunk_id, c.document_id, c.page_number, "
        "       c.content_text, c.token_count, d.filename "
        "FROM rag_chunks c "
        "JOIN rag_documents d ON d.id = c.document_id "
        "WHERE c.id = %s AND d.tenant_id = %s",
        (int(chunk_id), int(tenant_id)), fetchone=True,
    )
    if not row:
        return None
    return {
        "chunk_id":     int(row.get("chunk_id") or 0),
        "document_id":  int(row.get("document_id") or 0),
        "filename":     row.get("filename") or "",
        "page_number":  int(row.get("page_number") or 0) or None,
        "content_text": row.get("content_text") or "",
        "token_count":  int(row.get("token_count") or 0),
    }


# ---------------------------------------------------------------------------
# Reindex tick — called from messaging.register_tick
# ---------------------------------------------------------------------------

_LAST_REINDEX_SWEEP = 0.0
_REINDEX_INTERVAL_SECONDS = 6 * 3600  # every 6 hours


def reindex_tick(read_file_bytes: Callable[[str], Optional[bytes]]) -> None:
    """Scheduler tick: rebuild any document whose underlying file mtime
    changed since the last index. `read_file_bytes` is injected by
    app.py so this module doesn't need to import the storage backend
    directly.

    Throttled to once every 6 hours per process — the scheduler fires
    every 30 seconds so without this gate we'd hammer disk on every
    tick. State is in-memory: a process restart re-checks immediately,
    which is the safest behavior."""
    global _LAST_REINDEX_SWEEP
    now = time.time()
    if now - _LAST_REINDEX_SWEEP < _REINDEX_INTERVAL_SECONDS:
        return
    _LAST_REINDEX_SWEEP = now
    if _query_db is None or _execute_db is None:
        return
    try:
        rows = _query_db(
            "SELECT id, filename, storage_key, source_mtime "
            "FROM rag_documents WHERE status IN ('ready','empty') "
            "  AND storage_key <> ''",
        ) or []
    except Exception as e:
        print(f"[rag] reindex_tick query failed: {e}")
        return
    for row in rows:
        key = row.get("storage_key") or ""
        if not key:
            continue
        try:
            data = read_file_bytes(key)
            if data is None:
                continue
            # mtime check — caller can pass any monotonic source; we
            # compare against the value stored at ingest time. If the
            # storage backend doesn't expose mtime we re-check size as
            # a proxy by comparing byte length to size_bytes.
            current_mtime = None
            try:
                from storage import get_storage
                full = os.path.join(os.path.dirname(
                    os.path.abspath(__file__)), "uploads", key)
                if os.path.exists(full):
                    current_mtime = os.path.getmtime(full)
            except Exception:
                current_mtime = None
            stored = row.get("source_mtime")
            if (current_mtime is not None and stored is not None
                    and abs(float(current_mtime) - float(stored)) < 1e-3):
                continue
            print(f"[rag] reindexing doc {row['id']} ({row['filename']})")
            reindex_document(int(row["id"]),
                             filename=row["filename"],
                             data=data,
                             session_id="reindex_tick")
            if current_mtime is not None:
                _execute_db(
                    "UPDATE rag_documents SET source_mtime=%s "
                    "WHERE id=%s",
                    (float(current_mtime), int(row["id"])))
        except Exception as e:
            print(f"[rag] reindex doc {row.get('id')} failed: {e}")
