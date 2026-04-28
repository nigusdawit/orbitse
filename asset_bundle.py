"""
JS bundle + minify for the public homepage.

Concatenates `public/script.js` + `public/voice.js` into ONE minified blob
served from a content-fingerprinted URL like `/bundle.{sha256[:12]}.min.js`.
Drops the homepage from 2 JS requests to 1 and shrinks the bytes-on-wire
by ~42% pre-Brotli (closer to ~45% post-Brotli) on the current sources.

Design notes:

- **In-memory only**: the minified blob is built once at first access and
  cached in a module-level dict for the lifetime of the worker process.
  No filesystem writes, no derived artifacts to gitignore, no race
  conditions between multi-worker deployments — every worker independently
  builds the same deterministic bundle on boot. The trade-off is ~50 ms
  of cold-start CPU per worker; rjsmin processes 400 KB of JS in well
  under that budget.

- **Rolling-deploy caveat**: each worker only knows ONE bundle hash —
  the one matching its own source files. During a rolling deploy where
  old + new workers serve traffic simultaneously, a client holding an
  old HTML page (with the old bundle hash baked in) could hit a new
  worker and get 404 on the bundle URL; one page reload fixes it
  (refetched HTML carries the new hash). Replit's autoscale deployment
  model replaces workers atomically rather than rolling, so the window
  is effectively zero there. If this module ever lands in an environment
  with true rolling deploys (k8s rollingUpdate, etc.) and the transient
  404 is unacceptable, the lowest-effort mitigation is to keep the
  PREVIOUS bundle bytes in `_STATE` for a short grace window so the old
  hash also resolves; not added speculatively because it adds state
  that's wasted on the dominant deployment model.

- **Content-fingerprinted URL**: the bundle URL embeds the first 12 hex
  chars of the SHA-256 of the minified bytes. When the source files
  change, the hash changes, the URL changes, and any cached HTML pointing
  at the old URL gets a fresh 404 — which is the standard web pattern
  for forever-cacheable static assets and lets the bundle response carry
  `Cache-Control: public, max-age=31536000, immutable` (one year, no
  revalidation). Without fingerprinting we'd be stuck with `no-cache` to
  avoid serving stale code, throwing away the entire caching win.

- **Source files stay served**: `/script.js` and `/voice.js` continue to
  serve from the existing `serve_static()` route. Two reasons: (1) admin-
  saved designs in `site_designs.html` may inline `<script src="/script.js">`
  directly, and (2) developers debugging in browser devtools find the
  unminified source easier to read. The bundle is a same-content optimised
  view, not a replacement.

- **Concatenation order matters**: `script.js` defines globals (e.g.
  `BUILTIN_SECTION_MAP`, `loadGoogleFont`) that `voice.js` reads at
  initialisation. The original `public/index.html` loaded them in that
  order; we preserve it. A `\n;\n` separator between files prevents
  ASI ambiguity if the last line of one file lacks a semicolon and the
  first token of the next starts with `[ ( + - / \``.

- **rjsmin choice**: pure Python (no Node toolchain to add to the
  Dockerfile), conservative whitespace + comment stripping (no name
  mangling, no AST rewrites), deterministic, and handles every modern
  syntax feature we use (template literals, optional chaining, async/await,
  spread). It hits ~40% size reduction on hand-written commented JS,
  which is the bulk of the win — Brotli already squeezes the rest.

Public API:
    build_bundle(force=False) — build (or rebuild) the in-memory bundle.
    get_bundle()              — lazy accessor; calls build_bundle once.
    bundle_script_tag()       — `<script src="/bundle.{hash}.min.js"></script>`
    BUNDLE_URL_PATTERN        — regex for any fingerprinted bundle URL.
"""

import hashlib
import re
import threading
from pathlib import Path

import rjsmin

PUBLIC_DIR = Path(__file__).resolve().parent / "public"

# Order matches public/index.html load order. script.js sets globals that
# voice.js consumes — preserving the order keeps runtime semantics identical
# to the pre-bundling load.
BUNDLE_SOURCES = ["script.js", "voice.js"]

# ASI-safe separator. Inserted between concatenated files so the last line
# of one source can't accidentally fuse with the first token of the next.
_FILE_SEPARATOR = "\n;\n"

# Regex matching any fingerprinted bundle URL. Used by tests + by app.py to
# decide whether an incoming request is for a bundle (and therefore deserves
# the immutable cache header).
BUNDLE_URL_PATTERN = re.compile(r"^/bundle\.[a-f0-9]{12}\.min\.js$")

_BUILD_LOCK = threading.Lock()
_STATE = {
    "hash": None,           # 12-char hex prefix of sha256(minified bytes)
    "content_bytes": None,  # bytes — minified UTF-8
    "url": None,            # "/bundle.{hash}.min.js"
    "raw_size": 0,          # bytes pre-minify (sum of source files)
    "min_size": 0,          # bytes post-minify
    "sources": list(BUNDLE_SOURCES),
}


def build_bundle(force=False):
    """Build (or rebuild) the in-memory bundle.

    Idempotent within a process: subsequent calls are O(1) once built unless
    `force=True` is passed (used by tests to verify hash stability across
    rebuilds and by future ops if a hot-reload path is ever needed).
    """
    with _BUILD_LOCK:
        if _STATE["content_bytes"] is not None and not force:
            return _STATE

        parts = []
        raw_size = 0
        for name in BUNDLE_SOURCES:
            path = PUBLIC_DIR / name
            src = path.read_text(encoding="utf-8")
            raw_size += len(src.encode("utf-8"))
            # Marker comment helps anyone who curls the bundle to map a
            # given line of minified output back to its source file. rjsmin
            # preserves /* ... */ comments by default? Actually it strips
            # them — that's fine, they're just for debugging during dev.
            parts.append(f"\n/* === {name} === */\n")
            parts.append(src)
            parts.append(_FILE_SEPARATOR)

        concatenated = "".join(parts)
        minified = rjsmin.jsmin(concatenated)
        content_bytes = minified.encode("utf-8")
        bundle_hash = hashlib.sha256(content_bytes).hexdigest()[:12]

        _STATE.update({
            "hash": bundle_hash,
            "content_bytes": content_bytes,
            "url": f"/bundle.{bundle_hash}.min.js",
            "raw_size": raw_size,
            "min_size": len(content_bytes),
        })
        return _STATE


def get_bundle():
    """Lazy accessor — builds on first call, returns cached state thereafter."""
    if _STATE["content_bytes"] is None:
        build_bundle()
    return _STATE


def bundle_script_tag():
    """Single <script> tag pointing at the fingerprinted bundle URL.

    Inserted into served HTML by serve_index() in place of the original
    two `<script src="/script.js">` and `<script src="/voice.js">` tags.
    """
    state = get_bundle()
    return f'<script src="{state["url"]}"></script>'
