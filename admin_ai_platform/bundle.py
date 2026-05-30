"""
admin_ai_platform.bundle
========================

Widget bundling (M20). Concatenates the embeddable widget's source assets
(``web/chat-ui.css`` + ``web/voice.js`` + ``web/chat-ui.js``) into a single
**content-hashed**, optionally-minified bundle under ``embed/dist/`` so a
cross-origin host loads one cached JS + one CSS instead of three requests.

Cache strategy (served by ``blueprints/assets.py``):
  * ``/embed/dist/widget.<hash>.js`` / ``.css`` — the filename contains a hash of
    the contents, so it can be served ``immutable, max-age=1y``. A source change
    produces a NEW hash → automatic cache-bust, no stale assets.
  * ``/embed/dist/manifest.json`` — ``{"version", "js", "css"}`` with a SHORT
    cache; the loader reads it to discover the current hashed filenames.

Build at deploy time (Docker build step or CI): ``python -m admin_ai_platform.bundle``.
The build is deterministic (hash of concatenated source), so re-running without a
source change is a no-op.
"""

from __future__ import annotations

import hashlib
import json
import os

_PKG = os.path.dirname(os.path.abspath(__file__))
_WEB = os.path.join(_PKG, "web")
_DIST = os.path.join(os.path.dirname(_PKG), "embed", "dist")  # repo-root embed/dist

# Order matters: voice.js defines VoiceAgent that chat-ui.js may reference.
_JS_SOURCES = ("voice.js", "chat-ui.js")
_CSS_SOURCES = ("chat-ui.css",)


def _read(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as fh:
        return fh.read()


def _maybe_minify_js(src):
    """Minify with rjsmin when available; otherwise return the source unchanged
    (the bundle still works, just larger)."""
    try:
        import rjsmin
        return rjsmin.jsmin(src)
    except Exception:
        return src


def build_bundle(minify: bool = True) -> dict:
    """Build the widget bundle. Returns the manifest dict
    ``{version, js, css, bytes_js, bytes_css}`` and writes the hashed files +
    manifest.json into ``embed/dist/``. Idempotent for unchanged source."""
    js_concat = "\n;\n".join(
        f"/* --- {n} --- */\n{_read(n)}" for n in _JS_SOURCES)
    css_concat = "\n".join(f"/* --- {n} --- */\n{_read(n)}" for n in _CSS_SOURCES)
    if minify:
        js_concat = _maybe_minify_js(js_concat)

    # Version = short sha256 of the concatenated (post-minify) payload, so any
    # content change rotates the filename and busts caches.
    digest = hashlib.sha256((js_concat + "" + css_concat).encode()).hexdigest()[:12]
    js_name = f"widget.{digest}.js"
    css_name = f"widget.{digest}.css"

    os.makedirs(_DIST, exist_ok=True)
    with open(os.path.join(_DIST, js_name), "w", encoding="utf-8") as fh:
        fh.write(js_concat)
    with open(os.path.join(_DIST, css_name), "w", encoding="utf-8") as fh:
        fh.write(css_concat)
    manifest = {"version": digest, "js": js_name, "css": css_name,
                "bytes_js": len(js_concat.encode()), "bytes_css": len(css_concat.encode())}
    with open(os.path.join(_DIST, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest


def current_manifest():
    """Read the built manifest, or None if the bundle hasn't been built yet."""
    try:
        with open(os.path.join(_DIST, "manifest.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def dist_dir():
    return _DIST


if __name__ == "__main__":
    m = build_bundle()
    print(f"[bundle] built widget {m['version']}: {m['js']} "
          f"({m['bytes_js']} B) + {m['css']} ({m['bytes_css']} B)")
