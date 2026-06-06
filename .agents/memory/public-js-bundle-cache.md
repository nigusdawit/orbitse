---
name: Public JS served as a cached bundle (not script.js directly)
description: Why edits to public/script.js don't show up until you restart the workflow.
---
The public site does NOT load `/script.js` directly. `serve_index()` injects a
`<script src="/bundle.<sha256[:12]>.min.js">` tag (replacing the
`<!-- JS_BUNDLE_INJECT -->` placeholder in `public/index.html`). The bundle is
`public/script.js` + `public/voice.js` concatenated + minified.

**Why edits seem to do nothing:** the bundle is built ONCE per worker process and
cached in memory (`asset_bundle._STATE`, no disk cache), served with
`Cache-Control: public, max-age=31536000, immutable`. The dev workflow runs
`gunicorn --reload`, which only watches **Python** files — it does NOT restart on
static-asset (.js/.css) changes. So after editing script.js the worker keeps
serving the old bundle and the browser keeps the old immutable URL.

**How to apply:** after editing `public/script.js` or `public/voice.js`, RESTART
the "Start application" workflow so a fresh worker rebuilds the bundle (new hash →
new URL → browser refetches). Then hard-refresh the browser. The `/script.js`
endpoint still works for direct debugging, but the live site uses the bundle.
