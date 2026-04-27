"""
Regression tests for response compression (Optimization #2 — April 2026).

These pin the contract that flask-compress is wired up correctly with the
right algorithm sets and MIME whitelist, so a future library upgrade or
config edit can't silently regress us.

Specifically protects against:

  1. The exact bug we shipped and fixed mid-rollout: flask-compress's default
     COMPRESS_ALGORITHM_STREAMING is ('zstd', 'br', 'deflate') — gzip is
     OMITTED. Werkzeug's send_file always returns is_streamed=True, so
     large static assets (script.js = 354 KB) fell through uncompressed
     for any client that only advertises Accept-Encoding: gzip. The fix
     in app.py adds 'gzip' to the streaming list. If that override gets
     dropped, test_gzip_compresses_large_static_asset fails immediately.

  2. SSE buffering: chat / voice token streams use mimetype=text/event-stream
     and rely on tokens flushing to the browser as they arrive. If
     text/event-stream ever creeps into COMPRESS_MIMETYPES, every token
     gets buffered into the gzip window until the response closes — the
     UX degrades from "live typing" to "10-second pause then a wall of
     text". test_sse_mime_excluded_from_whitelist guards that.

  3. Compressing already-compressed media: gzipping a JPEG just adds
     ~20 bytes of framing overhead and burns CPU on both ends.
     test_image_not_compressed guards that.
"""
import gzip
import json
import os

import pytest


# -------------------------------------------------------------------- helpers
def _list_uploaded_images():
    """Find any existing uploaded image we can use as a real-data fixture."""
    uploads_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads"
    )
    if not os.path.isdir(uploads_dir):
        return []
    exts = (".jpg", ".jpeg", ".png", ".webp", ".gif")
    return [f for f in os.listdir(uploads_dir) if f.lower().endswith(exts)]


# -------------------------------------------------------------- positive tests
def test_gzip_compresses_large_static_asset(client):
    """Large static JS served via send_file (which is_streamed=True) must
    still compress with gzip when the client requests gzip only.

    This is the regression test for the COMPRESS_ALGORITHM_STREAMING bug.
    Without our explicit override, flask-compress drops gzip from the
    streaming algorithm set and a 354 KB script.js ships uncompressed to
    every gzip-only client.
    """
    res = client.get("/script.js", headers={"Accept-Encoding": "gzip"})
    assert res.status_code == 200
    assert res.headers.get("Content-Encoding") == "gzip", (
        "script.js was served uncompressed for gzip-only client — "
        "COMPRESS_ALGORITHM_STREAMING override likely missing or broken."
    )
    decompressed = gzip.decompress(res.data)
    assert len(decompressed) > 100_000, "script.js should be ~354 KB raw"
    # Sanity-check that we got actual JS, not a transcoded artifact.
    assert b"function" in decompressed[:5000] or b"const " in decompressed[:5000]


def test_brotli_compresses_json_bundle(client):
    """JSON endpoints over the 500-byte threshold get brotli when supported.

    Doubles as a sanity check that the page-bundle endpoint (Optimization #1)
    composes cleanly with compression: ~22 KB JSON → ~5 KB brotli.
    """
    res = client.get("/api/page-bundle", headers={"Accept-Encoding": "br"})
    assert res.status_code == 200
    assert res.headers.get("Content-Encoding") == "br"

    try:
        import brotli
    except ImportError:
        pytest.skip("brotli not available in this env")
    decompressed = brotli.decompress(res.data)
    parsed = json.loads(decompressed)
    assert isinstance(parsed, dict)
    assert len(parsed) > 10, "page-bundle should have ~17 keys"


def test_vary_header_set_on_compressed_response(client):
    """Compressed responses MUST set Vary: Accept-Encoding so caches /
    CDNs serve the right encoding to each client. Without this, a CDN can
    cache the brotli body and hand it to a client that only speaks gzip."""
    res = client.get("/api/page-bundle", headers={"Accept-Encoding": "br, gzip"})
    vary = res.headers.get("Vary", "")
    assert "accept-encoding" in vary.lower(), f"Vary header missing or wrong: {vary!r}"


# -------------------------------------------------------------- negative tests
def test_image_not_compressed(client):
    """Already-compressed media (JPEG/PNG/WebP) must pass through untouched.
    Re-compressing them wastes CPU and typically inflates the payload."""
    images = _list_uploaded_images()
    if not images:
        pytest.skip("no uploaded images on disk to test pass-through")
    res = client.get(
        f"/uploads/{images[0]}", headers={"Accept-Encoding": "br, gzip"}
    )
    assert res.status_code == 200
    assert "Content-Encoding" not in res.headers, (
        f"{images[0]} was compressed but its MIME isn't in the whitelist — "
        "did COMPRESS_MIMETYPES get widened?"
    )
    assert res.headers.get("Content-Type", "").startswith("image/")


def test_sse_mime_excluded_from_whitelist(flask_app):
    """text/event-stream MUST NOT be in the compress whitelist.

    This is the contract that keeps live chat / voice token streaming
    working — if the library ever adds it to defaults (or someone widens
    COMPRESS_MIMETYPES manually), tokens get buffered until the response
    closes and the streaming UX dies silently.
    """
    mimetypes = set(flask_app.config.get("COMPRESS_MIMETYPES", []))
    assert "text/event-stream" not in mimetypes, (
        "SSE mime type leaked into compress whitelist — chat / voice "
        "streams will buffer instead of flushing tokens live."
    )


def test_tiny_response_skipped(client):
    """Responses under COMPRESS_MIN_SIZE (500B default) shouldn't compress —
    gzip framing overhead would inflate them."""
    res = client.get("/healthz", headers={"Accept-Encoding": "br, gzip"})
    assert res.status_code == 200
    assert "Content-Encoding" not in res.headers, (
        "/healthz (~2 bytes) was compressed — COMPRESS_MIN_SIZE may have "
        "been lowered, or /healthz now returns a large response."
    )
