# Asset bundle pipeline (pure-Python JS bundling)

## When to use
A small/medium app whose public HTML loads two or three hand-written JS files (`script.js`, `voice.js`, etc.). You want to:
- collapse them into one minified request,
- get long-cache (`immutable`) headers safely via content fingerprints,
- avoid adding Node, webpack, esbuild, or a separate build step to the Dockerfile.

Skip this if you already have a real frontend toolchain (Vite, Next.js, etc.); they do this better.

## Architecture
A pure-Python module concatenates source files in declared order, minifies via `rjsmin`, hashes the output, and serves it from a content-fingerprinted URL. Everything lives in process memory — no on-disk artefacts, no race conditions, no derived files to gitignore.

Flow on first request after worker boot:
1. Read `public/script.js` + `public/voice.js` in declared order.
2. Insert an ASI-safe separator (`\n;\n`) between files so the last token of one can't fuse with the first token of the next.
3. Minify with `rjsmin.jsmin` (conservative whitespace/comment stripping — no name mangling, no AST rewrites).
4. SHA-256 the minified bytes; take first 12 hex chars as the fingerprint.
5. Cache `{hash, bytes, url, sizes}` in a module-level dict guarded by a single `threading.Lock`.
6. Serve from `/bundle.<hash>.min.js` with `Cache-Control: public, max-age=31536000, immutable`.

The originals (`/script.js`, `/voice.js`) keep serving too — debuggers want unminified source, and admin-saved designs may inline `<script src="/script.js">` directly. The bundle is a content-equivalent optimised view, not a replacement.

**Concatenation order matters**: `script.js` defines globals (`BUILTIN_SECTION_MAP`, etc.) that `voice.js` reads at init. Preserve the load order of the original HTML.

**Rolling-deploy caveat**: each worker only knows ONE bundle hash — the one matching its own source files. During a rolling deploy where old + new workers coexist, a client holding an old HTML page (with the old bundle hash baked in) could hit a new worker and get 404; one page reload fixes it. Atomic deploys (Replit autoscale) have a zero-second window. If you need rolling-safe behaviour, keep the previous bundle bytes in the cache for a short grace window.

## Data model
None — fully in-memory.

## API surface
Programmatic:
- `asset_bundle.build_bundle(force=False)` — build/rebuild the in-memory state.
- `asset_bundle.get_bundle()` — lazy accessor, returns the state dict.
- `asset_bundle.bundle_script_tag()` — `<script src="/bundle.<hash>.min.js"></script>` to inject into your HTML shell.
- `asset_bundle.BUNDLE_URL_PATTERN` — `re.Pattern` for `^/bundle\.[a-f0-9]{12}\.min\.js$`, used by the cache-control middleware to recognise bundle URLs.

HTTP:
- `GET /bundle.<hash>.min.js` → minified JS, `immutable` cache. A wrong hash returns 404; the next HTML fetch will carry the right one.

## Key files
- `asset_bundle.py` — entire module (~160 lines).
- `asset_bundle.py:82` — `BUNDLE_SOURCES` declaration (order-sensitive).
- `asset_bundle.py:104` — `build_bundle()`.
- `asset_bundle.py:151` — `bundle_script_tag()`.
- `app.py:5653` — bundle URL routed via `asset_bundle.get_bundle()`.

## External deps
- `rjsmin` — pure Python minifier (no Node required). Conservative, deterministic, handles all modern syntax (template literals, optional chaining, async/await, spread).

## Pitfalls
- Don't forget the ASI separator (`\n;\n`). Without it, `script.js` ending in `return foo` followed by `voice.js` starting with `[bar]` becomes `return foo[bar]`.
- Cold-start CPU cost (~50 ms for 400 KB of JS) is paid once per worker per process. Acceptable on serve-time-warmup; budget it if you have very tight cold-start SLOs.
- Don't bundle admin JS into the public bundle — admins are <1% of traffic and the bytes would be wasted on every public visitor.
- The fingerprint must be embedded in the URL, not the query string. Some CDNs treat query strings as cache-busters only and won't apply long-cache rules.
- `rjsmin` strips `/* */` comments — fine for production, but means source-map references in comments are also lost. Add a separate sourcemap pipeline if you need that.

## Adaptation notes
- Add a CSS bundle the same way with a CSS minifier (`rcssmin` is the sibling library).
- For content-hashed images, the same fingerprint+immutable-cache pattern applies — see the image-optimizer skill.
- If you outgrow this, esbuild via `subprocess` gives you tree-shaking + sourcemaps for ~10× the throughput; the URL/route layer here doesn't need to change.

## Adoption checklist
- [ ] Add `rjsmin` to dependencies.
- [ ] Declare your bundle sources in a list (order matters).
- [ ] Replace the multiple `<script src="...">` tags in your HTML shell with `bundle_script_tag()`.
- [ ] Add the bundle route handler with `Cache-Control: public, max-age=31536000, immutable`.
- [ ] Keep the source files served alongside the bundle for debugging.
- [ ] Decide whether your deployment is atomic; if not, plan for the rolling-deploy grace window.
