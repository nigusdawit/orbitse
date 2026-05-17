"""
Admin-chat RAG / memory module.

Three responsibilities, all admin-chat-scoped:

1. Knowledge Base — ingest PDF/DOCX/PPTX/CSV/TXT files uploaded by the
   admin, chunk + embed them, and offer cosine-similarity retrieval
   against `rag_chunks` (pgvector ivfflat index).

2. Cross-chat recall — embed every persisted admin chat user/assistant
   turn into `rag_chat_turns` so the agent can semantically pull snippets
   from prior sessions on demand.

3. Auto-memory — lightweight regex + LLM-assisted extractor that watches
   each completed turn for "remember that …", "I prefer …", "my X is …"
   style facts, writes them into `admin_chat_memories` (deduped by sha256
   of the normalized fact), and provides a helper that returns the top-K
   facts to inject as a system block on each new turn.

Why no LangChain
----------------
The task plan explicitly forbids LangChain — every primitive here uses
the OpenAI SDK directly + raw SQL via the host app's `execute_db` /
`query_db` helpers. Late-bound via init_module() so this file has no
import cycle with `app.py`.

Cost accounting
---------------
Embedding calls land on a new `rag_embed` surface in `api_cost_events`
so the existing cost dashboard / weekly digest pick them up without any
changes there.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import time
from typing import Any, Callable, Iterable

# ---- Late-bound host wiring ------------------------------------------------
_openai_client = None
_query_db: Callable | None = None
_execute_db: Callable | None = None
_record_chat_cost: Callable | None = None
_current_tenant_id: Callable | None = None


def init_module(*, openai_client, query_db, execute_db,
                record_chat_cost, current_tenant_id):
    """Wired from app.py at startup, just like semantic_cache.init_module."""
    global _openai_client, _query_db, _execute_db
    global _record_chat_cost, _current_tenant_id
    _openai_client = openai_client
    _query_db = query_db
    _execute_db = execute_db
    _record_chat_cost = record_chat_cost
    _current_tenant_id = current_tenant_id


# ---- Constants -------------------------------------------------------------

EMBED_MODEL = "text-embedding-3-small"   # 1536 dims, matches schema
EMBED_DIMS = 1536
EMBED_BATCH = 100                        # OpenAI hard limit is 2048; 100 is comfy
CHUNK_TARGET_TOKENS = 800
CHUNK_OVERLAP_TOKENS = 100
CHARS_PER_TOKEN = 4                      # rough average; only used for sizing
MAX_UPLOAD_BYTES = 25 * 1024 * 1024      # 25 MB — matches task plan

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".csv", ".txt", ".md"}

# Memory extraction — patterns that trigger the extractor BEFORE we burn
# an LLM call. Cheap pre-filter: if none of these fire, the turn is
# extremely unlikely to contain a personal/preference fact.
_MEMORY_TRIGGERS = re.compile(
    r"\b(remember(?: that)?|note(?: that)?|"
    r"my (?:name|business|company|role|job|email|phone|number|address|"
    r"website|product|industry|niche|audience|customer|client|tone|style|brand|"
    r"team|partner|spouse|wife|husband|kid|child|son|daughter|pet|dog|cat) "
    r"(?:is|are|=)|"
    r"i (?:am|prefer|like|hate|always|never|usually|don't|do not) |"
    r"we (?:are|prefer|always|never|usually|don't|do not) |"
    r"(?:please )?call me |"
    r"i(?:'m| am) (?:based|located|working) in |"
    r"our (?:business|company|brand|product) )",
    re.IGNORECASE,
)


# ---- Embedding helpers -----------------------------------------------------

def _to_pgvector(vec: list[float]) -> str:
    """pgvector accepts "[0.1,0.2,...]" cast to ::vector. Round to 6dp so
    the SQL payload stays under ~9 KB per chunk (consistent with the
    semantic_cache pattern)."""
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


def _embed_batch(texts: list[str], *, surface: str = "rag_embed",
                 session_id: str = "") -> list[list[float]]:
    """Call text-embedding-3-small for a batch of up to EMBED_BATCH texts.
    Records cost against `surface` so the dashboard can break out RAG
    spend separately from chat spend. NEVER raises — on failure returns
    an empty list and the caller treats the chunk batch as un-embedded.
    """
    if not texts or _openai_client is None:
        return []
    # Strip empties — OpenAI rejects "" inputs.
    cleaned = [(t or "").strip() for t in texts]
    cleaned = [t if t else "(empty)" for t in cleaned]
    try:
        resp = _openai_client.embeddings.create(model=EMBED_MODEL, input=cleaned)
    except Exception as e:
        print(f"[rag] embed batch failed: {e}")
        return []
    vecs = [d.embedding for d in resp.data]
    # Cost. Embeddings only burn prompt tokens — completion is 0.
    try:
        tok = getattr(resp, "usage", None)
        prompt = int(getattr(tok, "prompt_tokens", 0) or 0) if tok else 0
        if _record_chat_cost is not None:
            _record_chat_cost(
                session_id=session_id,
                surface=surface,
                provider="openai",
                model=EMBED_MODEL,
                prompt_tokens=prompt,
                completion_tokens=0,
                total_tokens=prompt,
                usage_known=bool(prompt),
            )
    except Exception as e:
        print(f"[rag] embed cost record failed: {e}")
    return vecs


def embed_one(text: str, *, surface: str = "rag_embed",
              session_id: str = "") -> list[float] | None:
    """Single-text convenience wrapper (used by retrieval — we always
    embed the user query before searching)."""
    vecs = _embed_batch([text], surface=surface, session_id=session_id)
    return vecs[0] if vecs else None


# ---- Document extraction ---------------------------------------------------

def _extract_pdf(path: str) -> list[tuple[int, str]]:
    """Return [(page_number, text), ...] for a text-layer PDF."""
    try:
        from pypdf import PdfReader  # lazy import — heavy
    except Exception as e:
        raise RuntimeError(f"pypdf not available: {e}")
    out: list[tuple[int, str]] = []
    reader = PdfReader(path)
    for i, page in enumerate(reader.pages):
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        if txt.strip():
            out.append((i + 1, txt))
    return out


def _extract_docx(path: str) -> list[tuple[int, str]]:
    """DOCX has no real "pages" concept (rendering-dependent), so we
    flatten the whole doc into one logical page. Chunker still produces
    multiple chunks — page_number stays NULL for chunks past the first."""
    try:
        from docx import Document  # python-docx
    except Exception as e:
        raise RuntimeError(f"python-docx not available: {e}")
    doc = Document(path)
    paras = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
    if not paras:
        return []
    return [(1, "\n\n".join(paras))]


def _extract_pptx(path: str) -> list[tuple[int, str]]:
    """One slide = one logical page. Pulls text from every shape that
    has a .text attribute (titles, body placeholders, text boxes)."""
    try:
        from pptx import Presentation  # python-pptx
    except Exception as e:
        raise RuntimeError(f"python-pptx not available: {e}")
    prs = Presentation(path)
    out: list[tuple[int, str]] = []
    for i, slide in enumerate(prs.slides):
        bits: list[str] = []
        for shape in slide.shapes:
            t = getattr(shape, "text", "")
            if t and t.strip():
                bits.append(t)
        if bits:
            out.append((i + 1, "\n".join(bits)))
    return out


def _extract_csv(path: str) -> list[tuple[int, str]]:
    """CSV → one chunk per ~50 rows so even a wide spreadsheet stays
    inside the chunk size budget."""
    import csv
    out: list[tuple[int, str]] = []
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return []
    header = rows[0]
    body = rows[1:] if len(rows) > 1 else []
    page_size = 50
    for pi in range(0, max(1, len(body)), page_size):
        block = body[pi:pi + page_size]
        if not block and pi == 0:
            block = []  # header-only file
        lines = [", ".join(header)]
        lines.extend(", ".join(r) for r in block)
        out.append((pi // page_size + 1, "\n".join(lines)))
    return out


def _extract_txt(path: str) -> list[tuple[int, str]]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return [(1, f.read())]


def extract_document(path: str, *, filename: str | None = None) -> list[tuple[int, str]]:
    """Dispatch by extension. Returns [(page_number, page_text), ...].
    Empty list = nothing extractable (scanned PDF, blank doc, etc.)."""
    ext = os.path.splitext(filename or path)[1].lower()
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext == ".docx":
        return _extract_docx(path)
    if ext == ".pptx":
        return _extract_pptx(path)
    if ext == ".csv":
        return _extract_csv(path)
    if ext in (".txt", ".md"):
        return _extract_txt(path)
    raise RuntimeError(f"Unsupported file extension: {ext}")


# ---- Chunking --------------------------------------------------------------

_PARA_SPLIT = re.compile(r"\n{2,}|\r\n{2,}")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _approx_tokens(s: str) -> int:
    return max(1, len(s) // CHARS_PER_TOKEN)


def chunk_text(text: str,
               target_tokens: int = CHUNK_TARGET_TOKENS,
               overlap_tokens: int = CHUNK_OVERLAP_TOKENS) -> list[str]:
    """Greedy paragraph-then-sentence packer.

    Reads paragraphs in order; if a single paragraph is bigger than the
    target it falls back to sentence-level packing inside it. Maintains
    a token-budget tail that's prepended to the next chunk so retrieved
    snippets near a chunk boundary still have local context (the
    standard sliding-window pattern, no LangChain).
    """
    if not text or not text.strip():
        return []
    target_chars = target_tokens * CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN
    paras = [p.strip() for p in _PARA_SPLIT.split(text) if p and p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        # If the paragraph alone is bigger than budget, split into
        # sentences and pack them.
        if len(p) > target_chars:
            sents = [s.strip() for s in _SENT_SPLIT.split(p) if s and s.strip()]
            for s in sents:
                if len(buf) + len(s) + 2 > target_chars and buf:
                    chunks.append(buf.strip())
                    buf = (buf[-overlap_chars:] if overlap_chars and buf else "")
                buf = (buf + " " + s).strip() if buf else s
            continue
        if len(buf) + len(p) + 2 > target_chars and buf:
            chunks.append(buf.strip())
            buf = (buf[-overlap_chars:] if overlap_chars and buf else "")
        buf = (buf + "\n\n" + p).strip() if buf else p
    if buf.strip():
        chunks.append(buf.strip())
    return chunks


# ---- KB ingest -------------------------------------------------------------

def ingest_document(file_path: str, filename: str, mime: str,
                    size_bytes: int, *, tenant_id: int | None = None) -> int:
    """Extract → chunk → embed → store one uploaded document.

    Returns the new rag_documents.id. Marks status='ready' on success,
    'failed' (with error_message) on any extraction/embedding error so
    the admin UI can show a useful failure reason instead of a silent
    empty row.
    """
    if _execute_db is None or _query_db is None:
        raise RuntimeError("rag module not initialized")
    tid = tenant_id if tenant_id is not None else (
        _current_tenant_id() if _current_tenant_id else 1)
    # Insert the document row immediately in 'indexing' state so the UI
    # shows it right away even if extraction is slow.
    row = _query_db(
        "INSERT INTO rag_documents "
        "(tenant_id, filename, mime, size_bytes, status, source_path, "
        " source_mtime) "
        "VALUES (%s, %s, %s, %s, 'indexing', %s, %s) RETURNING id",
        (tid, filename[:500], (mime or "")[:200], int(size_bytes or 0),
         file_path, os.path.getmtime(file_path) if os.path.exists(file_path) else None),
        fetchone=True,
    )
    doc_id = row["id"] if isinstance(row, dict) else row[0]
    try:
        pages = extract_document(file_path, filename=filename)
        if not pages:
            _execute_db(
                "UPDATE rag_documents SET status='failed', "
                "error_message=%s WHERE id=%s",
                ("No extractable text. (Scanned PDFs require OCR — not supported yet.)",
                 doc_id),
            )
            return doc_id
        # Build (chunk_text, page_number) pairs across all pages.
        chunk_rows: list[tuple[int, int, str]] = []  # (chunk_index, page, text)
        ci = 0
        for page_no, page_text in pages:
            for piece in chunk_text(page_text):
                chunk_rows.append((ci, page_no, piece))
                ci += 1
        if not chunk_rows:
            _execute_db(
                "UPDATE rag_documents SET status='failed', "
                "error_message=%s WHERE id=%s",
                ("No chunks produced.", doc_id),
            )
            return doc_id
        # Embed in batches of EMBED_BATCH.
        for batch_start in range(0, len(chunk_rows), EMBED_BATCH):
            batch = chunk_rows[batch_start:batch_start + EMBED_BATCH]
            vecs = _embed_batch([t for _, _, t in batch],
                                surface="rag_embed",
                                session_id=f"kb_ingest_{doc_id}")
            if len(vecs) != len(batch):
                # Partial embed — write what we have, leave the rest
                # for a reindex. Better than silently dropping the doc.
                vecs = vecs + [None] * (len(batch) - len(vecs))
            for (idx, page, content), vec in zip(batch, vecs):
                if vec is None:
                    continue
                _execute_db(
                    "INSERT INTO rag_chunks "
                    "(document_id, tenant_id, chunk_index, page_number, "
                    " content_text, token_count, embedding) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s::vector)",
                    (doc_id, tid, idx, page, content,
                     _approx_tokens(content), _to_pgvector(vec)),
                )
        # Final status flip.
        _execute_db(
            "UPDATE rag_documents SET status='ready', "
            "page_count=%s, chunk_count=%s, indexed_at=NOW() WHERE id=%s",
            (len(pages), len(chunk_rows), doc_id),
        )
        return doc_id
    except Exception as e:
        print(f"[rag] ingest doc {doc_id} failed: {e}")
        try:
            _execute_db(
                "UPDATE rag_documents SET status='failed', "
                "error_message=%s WHERE id=%s",
                (str(e)[:1000], doc_id),
            )
        except Exception:
            pass
        return doc_id


def list_documents(*, tenant_id: int | None = None) -> list[dict]:
    if _query_db is None:
        return []
    tid = tenant_id if tenant_id is not None else (
        _current_tenant_id() if _current_tenant_id else 1)
    rows = _query_db(
        "SELECT id, filename, mime, size_bytes, page_count, chunk_count, "
        "       status, error_message, indexed_at, created_at "
        "FROM rag_documents WHERE tenant_id=%s "
        "ORDER BY created_at DESC, id DESC",
        (tid,),
    ) or []
    return list(rows)


def delete_document(doc_id: int, *, tenant_id: int | None = None) -> bool:
    if _execute_db is None or _query_db is None:
        return False
    tid = tenant_id if tenant_id is not None else (
        _current_tenant_id() if _current_tenant_id else 1)
    row = _query_db(
        "SELECT source_path FROM rag_documents WHERE id=%s AND tenant_id=%s",
        (doc_id, tid), fetchone=True,
    )
    if not row:
        return False
    # CASCADE on rag_chunks takes care of the chunk rows.
    _execute_db("DELETE FROM rag_documents WHERE id=%s AND tenant_id=%s",
                (doc_id, tid))
    sp = (row["source_path"] if isinstance(row, dict) else row[0]) if row else None
    if sp:
        try:
            if os.path.exists(sp):
                os.remove(sp)
        except Exception as e:
            print(f"[rag] failed to remove source file {sp}: {e}")
    return True


# ---- KB retrieval ----------------------------------------------------------

def search_kb(query: str, *, top_k: int = 6,
              tenant_id: int | None = None,
              session_id: str = "") -> list[dict]:
    """Return [{document_id, filename, page_number, content_text,
    similarity}, ...]. Similarity is 1 - cosine_distance (higher = more
    relevant). Empty list if KB is empty or embedding failed."""
    if _query_db is None:
        return []
    tid = tenant_id if tenant_id is not None else (
        _current_tenant_id() if _current_tenant_id else 1)
    vec = embed_one(query, surface="rag_embed", session_id=session_id)
    if vec is None:
        return []
    pgv = _to_pgvector(vec)
    rows = _query_db(
        "SELECT c.id, c.document_id, c.page_number, c.content_text, "
        "       d.filename, "
        "       (1 - (c.embedding <=> %s::vector)) AS similarity "
        "FROM rag_chunks c "
        "JOIN rag_documents d ON d.id = c.document_id "
        "WHERE c.tenant_id=%s AND d.status='ready' "
        "  AND c.embedding IS NOT NULL "
        "ORDER BY c.embedding <=> %s::vector "
        "LIMIT %s",
        (pgv, tid, pgv, int(max(1, min(20, top_k)))),
    ) or []
    return list(rows)


# ---- Chat-turn recall ------------------------------------------------------

def embed_chat_turn(*, session_id: str, message_id: int | None,
                    role: str, content: str, session_title: str = "",
                    tenant_id: int | None = None) -> None:
    """Embed one admin chat turn into rag_chat_turns. Idempotent by
    (session_id, message_id) — re-embedding the same row is a no-op via
    ON CONFLICT. Called from app.py right after _admin_chat_persist for
    user + assistant turns."""
    if _execute_db is None or not content or not content.strip():
        return
    tid = tenant_id if tenant_id is not None else (
        _current_tenant_id() if _current_tenant_id else 1)
    # Skip very short content — single-word turns ("ok", "thanks")
    # produce embeddings that just confuse cosine recall.
    if len(content.strip()) < 30:
        return
    vec = embed_one(content[:4000], surface="rag_embed", session_id=session_id)
    if vec is None:
        return
    try:
        _execute_db(
            "INSERT INTO rag_chat_turns "
            "(tenant_id, session_id, message_id, role, content_text, "
            " token_count, embedding, session_title) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s) "
            "ON CONFLICT (session_id, message_id) "
            "WHERE message_id IS NOT NULL DO NOTHING",
            (tid, session_id, message_id, (role or "user")[:20],
             content[:8000], _approx_tokens(content),
             _to_pgvector(vec), (session_title or "")[:200]),
        )
    except Exception as e:
        print(f"[rag] embed_chat_turn failed: {e}")


def search_past_chats(query: str, *, top_k: int = 4,
                      exclude_session_id: str = "",
                      tenant_id: int | None = None,
                      session_id: str = "") -> list[dict]:
    """Cross-chat semantic recall. Excludes the current session so the
    agent doesn't 'recall' something it literally just said.

    Returns [{session_id, session_title, role, content_text, created_at,
    similarity}]."""
    if _query_db is None:
        return []
    tid = tenant_id if tenant_id is not None else (
        _current_tenant_id() if _current_tenant_id else 1)
    vec = embed_one(query, surface="rag_embed", session_id=session_id)
    if vec is None:
        return []
    pgv = _to_pgvector(vec)
    rows = _query_db(
        "SELECT session_id, session_title, role, content_text, created_at, "
        "       (1 - (embedding <=> %s::vector)) AS similarity "
        "FROM rag_chat_turns "
        "WHERE tenant_id=%s AND embedding IS NOT NULL "
        "  AND session_id <> %s "
        "ORDER BY embedding <=> %s::vector "
        "LIMIT %s",
        (pgv, tid, exclude_session_id or "", pgv,
         int(max(1, min(10, top_k)))),
    ) or []
    return list(rows)


# ---- Auto-memory -----------------------------------------------------------

def _normalize_memory(text: str) -> str:
    """Normalize a candidate fact for dedupe — lowercase, collapse
    whitespace, strip trailing punctuation."""
    s = re.sub(r"\s+", " ", (text or "").strip().lower())
    s = re.sub(r"[\.!?,;:]+$", "", s)
    return s


def _hash_memory(text: str) -> str:
    return hashlib.sha256(_normalize_memory(text).encode("utf-8")).hexdigest()


def _should_extract_memory(user_text: str, assistant_text: str) -> bool:
    """Cheap pre-filter: only run the LLM extractor when the user turn
    contains a trigger phrase. Saves ~95% of extractor calls on a
    typical chat."""
    if not user_text:
        return False
    return bool(_MEMORY_TRIGGERS.search(user_text))


def extract_and_store_memories(*, user_text: str, assistant_text: str,
                               session_id: str, message_id: int | None = None,
                               tenant_id: int | None = None) -> list[str]:
    """Extract durable facts from a completed turn and persist them.
    Returns the list of new fact strings (empty when nothing was
    extracted or the row already existed).

    Uses a single small gpt-4o-mini call in JSON mode — only fires when
    `_should_extract_memory` matched, so the steady-state cost is
    negligible.
    """
    if not _should_extract_memory(user_text, assistant_text):
        return []
    if _openai_client is None or _execute_db is None:
        return []
    tid = tenant_id if tenant_id is not None else (
        _current_tenant_id() if _current_tenant_id else 1)
    prompt = (
        "You extract DURABLE FACTS about the user from a single chat turn. "
        "Return STRICT JSON of the form {\"facts\": [\"fact one\", \"fact "
        "two\"]}. Each fact must be:\n"
        "  • a single declarative sentence in third person about THE USER "
        "(e.g., \"User's business is a coffee shop in Lisbon.\")\n"
        "  • genuinely durable — preferences, identity, ongoing context. "
        "NOT one-off tasks, requests, or questions.\n"
        "  • self-contained (no pronouns referring to prior context).\n"
        "If nothing durable was stated, return {\"facts\": []}.\n\n"
        f"USER MESSAGE:\n{user_text[:2000]}\n\n"
        f"ASSISTANT REPLY:\n{(assistant_text or '')[:1000]}"
    )
    try:
        resp = _openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=300,
            temperature=0.0,
        )
        # Cost.
        try:
            if _record_chat_cost is not None:
                u = getattr(resp, "usage", None)
                _record_chat_cost(
                    session_id=session_id, surface="rag_memory_extract",
                    provider="openai", model="gpt-4o-mini",
                    prompt_tokens=int(getattr(u, "prompt_tokens", 0) or 0),
                    completion_tokens=int(getattr(u, "completion_tokens", 0) or 0),
                    total_tokens=int(getattr(u, "total_tokens", 0) or 0),
                    usage_known=bool(u),
                )
        except Exception:
            pass
        import json as _json
        raw = (resp.choices[0].message.content or "").strip()
        data = _json.loads(raw) if raw else {}
        facts = data.get("facts") or []
    except Exception as e:
        print(f"[rag] memory extract failed: {e}")
        return []
    new_facts: list[str] = []
    for f in facts:
        if not isinstance(f, str):
            continue
        f = f.strip()
        if len(f) < 8 or len(f) > 500:
            continue
        h = _hash_memory(f)
        try:
            row = _query_db(
                "INSERT INTO admin_chat_memories "
                "(tenant_id, content, content_hash, source_session_id, "
                " source_message_id, confidence) "
                "VALUES (%s, %s, %s, %s, %s, 0.7) "
                "ON CONFLICT (tenant_id, content_hash) DO NOTHING "
                "RETURNING id",
                (tid, f[:1000], h, session_id, message_id),
                fetchone=True,
            )
            if row:
                new_facts.append(f)
        except Exception as e:
            print(f"[rag] memory insert failed: {e}")
    return new_facts


def get_memories_for_prompt(*, limit: int = 25,
                            tenant_id: int | None = None) -> list[dict]:
    """Return the top `limit` durable facts to inject as a system block.
    Sort: most recently used / created first."""
    if _query_db is None:
        return []
    tid = tenant_id if tenant_id is not None else (
        _current_tenant_id() if _current_tenant_id else 1)
    rows = _query_db(
        "SELECT id, content, use_count, last_used_at, created_at "
        "FROM admin_chat_memories WHERE tenant_id=%s "
        "ORDER BY COALESCE(last_used_at, created_at) DESC "
        "LIMIT %s",
        (tid, int(max(1, min(100, limit)))),
    ) or []
    return list(rows)


def bump_memories_used(ids: Iterable[int]) -> None:
    """Mark the given memory ids as recently used. Called after we
    inject them into a turn so use_count / last_used_at reflect real
    usage (drives the sort in get_memories_for_prompt)."""
    if not ids or _execute_db is None:
        return
    ids = [int(i) for i in ids if i is not None]
    if not ids:
        return
    try:
        _execute_db(
            "UPDATE admin_chat_memories "
            "SET use_count=use_count+1, last_used_at=NOW() "
            "WHERE id = ANY(%s)",
            (ids,),
        )
    except Exception as e:
        print(f"[rag] bump_memories_used failed: {e}")


def list_memories(*, tenant_id: int | None = None) -> list[dict]:
    """Admin UI list (forget-button surface)."""
    if _query_db is None:
        return []
    tid = tenant_id if tenant_id is not None else (
        _current_tenant_id() if _current_tenant_id else 1)
    rows = _query_db(
        "SELECT id, content, source_session_id, use_count, last_used_at, "
        "       created_at "
        "FROM admin_chat_memories WHERE tenant_id=%s "
        "ORDER BY COALESCE(last_used_at, created_at) DESC, id DESC",
        (tid,),
    ) or []
    return list(rows)


def delete_memory(memory_id: int, *, tenant_id: int | None = None) -> bool:
    """Return True only if a matching row actually existed (and was
    deleted). Pre-checking with SELECT keeps the API able to return a
    proper 404 for non-existent or other-tenant IDs without depending on
    _execute_db exposing rowcount."""
    if _execute_db is None or _query_db is None:
        return False
    tid = tenant_id if tenant_id is not None else (
        _current_tenant_id() if _current_tenant_id else 1)
    existing = _query_db(
        "SELECT id FROM admin_chat_memories WHERE id=%s AND tenant_id=%s",
        (memory_id, tid), fetchone=True,
    )
    if not existing:
        return False
    _execute_db("DELETE FROM admin_chat_memories WHERE id=%s AND tenant_id=%s",
                (memory_id, tid))
    return True


# ---- System-block formatters used by the chat loop -------------------------

def format_kb_block(rows: list[dict]) -> str:
    """Render KB retrieval hits as a Markdown-ish system block."""
    if not rows:
        return ""
    lines = ["### Knowledge Base (auto-retrieved)"]
    for r in rows:
        fn = (r.get("filename") or "doc")[:80]
        pg = r.get("page_number")
        cite = f"[source: {fn}" + (f" p.{pg}" if pg else "") + "]"
        snippet = (r.get("content_text") or "")[:1200]
        lines.append(f"{cite}\n{snippet}\n")
    return "\n".join(lines)


def format_past_chats_block(rows: list[dict]) -> str:
    if not rows:
        return ""
    lines = ["### Recall from past conversations"]
    for r in rows:
        title = (r.get("session_title") or "(untitled chat)")[:80]
        when = r.get("created_at")
        when_str = when.strftime("%Y-%m-%d") if hasattr(when, "strftime") else ""
        cite = f"[from chat: {title}" + (f", {when_str}" if when_str else "") + "]"
        snippet = (r.get("content_text") or "")[:600]
        role = r.get("role") or "user"
        lines.append(f"{cite} ({role})\n{snippet}\n")
    return "\n".join(lines)


def format_memories_block(rows: list[dict]) -> str:
    if not rows:
        return ""
    lines = ["### What you've told me before (durable facts)"]
    for r in rows:
        c = (r.get("content") or "").strip()
        if c:
            lines.append(f"- {c}")
    return "\n".join(lines)
