# Image optimizer (responsive WebP variants)

## When to use
A CMS that lets operators upload arbitrary JPEG/PNG photos that then render in galleries, cards, and hero sections at very different display widths. You want to ship a `srcset` with three sensible breakpoints and `image/webp` for the per-request bandwidth savings, but without breaking legacy uploads from before this feature shipped.

## Architecture
Two complementary jobs share one Pillow encoder:

1. **Upload-time preheat** — when an admin uploads `abc.jpg`, immediately generate `abc-400.webp`, `abc-800.webp`, `abc-1600.webp` alongside it. The original is preserved so existing `/uploads/<file>` URLs keep working and re-edits still have the source bytes.
2. **On-demand backfill** — when a request comes in for a variant URL that doesn't exist (e.g. legacy files), the `serve_upload` route calls `ensure_variant_on_demand()` which finds any matching source (`<base>.jpg|.jpeg|.png`) and synthesises the requested WebP on the fly. First request pays ~150–500 ms of resize; every subsequent request hits the cached variant. This means responsive `srcset` flips on for the entire library with no migration script.

A frontend helper (`imgSrcset` in `script.js`) and a server helper (`srcset_for`) emit the same `<stem>-<w>.webp Nw` pattern from either side, so a given URL builds the same `srcset` regardless of who generates the markup.

Encode settings: `quality=82`, `method=6` (slowest/highest compression — paid once at upload, saved forever).

Why these three widths:
- 400 — phones at 1× DPR, tablet thumbnails
- 800 — phones at 2× DPR, half-width desktop cards
- 1600 — desktop hero / full-bleed (also 2× of 800 for retina)

Why no upscale on the preheat path, but cap-to-source on the on-demand path: pre-warming a 300 px source into 3 near-identical WebPs wastes disk; but if the visitor's frontend already emitted a `…-800.webp` URL, 404-ing it costs a round-trip while encoding at native width costs ~1–2 KB. Different paths, different defaults.

## Data model
None — variants are derived files keyed off the source filename.

## API surface
Programmatic:
- `image_optimize.generate_webp_variants(filename)` → `list[str]` of generated names (called from the upload handler).
- `image_optimize.delete_variants(filename)` → `int` count deleted (called BEFORE re-generating on a re-upload of the same filename to bust browser/CDN caches that hold the OLD bytes under the same `<stem>-<w>.webp` URL).
- `image_optimize.ensure_variant_on_demand(filename)` → `bool` (called from `serve_upload` before the 404).
- `image_optimize.is_variant_filename(filename)` → `bool` parser.
- `image_optimize.srcset_for(public_url, base_url=None)` → `srcset` string for templates.

## Key files
- `image_optimize.py` — entire module.
- `image_optimize.py:60` — `_RESPONSIVE_WIDTHS = (400, 800, 1600)`.
- `image_optimize.py:73-74` — quality/method constants.
- `image_optimize.py:205` — `generate_webp_variants()` upload-time entry.
- `image_optimize.py:261` — `delete_variants()` re-upload cache buster.
- `image_optimize.py:317` — `ensure_variant_on_demand()` on-demand entry.
- `image_optimize.py:376` — `srcset_for()` template helper.
- `app.py:24550` — `serve_upload()` route that calls `ensure_variant_on_demand` before responding 404.

## External deps
- Pillow (`PIL.Image`) — `WEBP` encoder is built into Pillow 12.x with no extra plugin.

## Pitfalls
- Pillow's `load()` must be called explicitly to catch truncated streams — `Image.open()` alone is lazy and will raise later inside the encode step.
- `DecompressionBombError` must be caught; never raise from an upload handler over a malicious PNG.
- The preheat path skips upscaling (no point), but the on-demand path **must** cap to source — see the file's docstring rationale.
- WebP variants share deterministic URLs (`<stem>-{400,800,1600}.webp`). If an operator re-uploads `hero.jpg` with new bytes under the same filename, you MUST call `delete_variants()` before `generate_webp_variants()` or browsers + CDN will keep serving the OLD WebP for up to a year under the immutable cache header.
- Subdirectories (`voice/`, `contracts/`) are explicitly excluded — variants live only at the root of `uploads/`.
- The frontend `imgSrcset()` helper and server-side `srcset_for()` must stay in lock-step on the breakpoint list. Drift = some URLs build wrong markup.

## Adaptation notes
- Add 3200 to `_RESPONSIVE_WIDTHS` once 4K-on-4K becomes a real demand.
- Add AVIF as a `<picture>` `<source>` upgrade for browsers that prefer it; keep WebP as the broad fallback because AVIF encode is 3–10× slower for ~10% extra savings — wrong trade on the on-demand path.
- For object-storage backends, the same code works — `storage.write_bytes` already routes per-backend.
- To support GIFs without losing animation, fork the encode path to use `Image.save(..., save_all=True, append_images=...)`.

## Adoption checklist
- [ ] Add Pillow to your dependencies.
- [ ] Decide the breakpoint list and freeze it (changes invalidate every cached variant).
- [ ] Call `generate_webp_variants()` from every upload handler.
- [ ] Call `delete_variants()` BEFORE re-generating on overwrites.
- [ ] Hook `ensure_variant_on_demand()` into the upload-serving route before the 404 branch.
- [ ] Emit `srcset` from both server templates and client-side renderers using the shared helper.
- [ ] Set `Cache-Control: public, max-age=31536000, immutable` on `*-<w>.webp` responses.
