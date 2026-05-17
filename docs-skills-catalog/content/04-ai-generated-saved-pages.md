# AI-Generated Saved Pages Library

**Category:** Content Management
**Related:** `ai-pipelines/...`, `content/01-page-section-registry.md`

## When to use
Your AI chatbot can generate full HTML pages on demand (a "generate me a page about X" command). You want every one of those generations to be persistable as a shareable URL so the operator can curate the best ones, link to them from marketing emails, and have the AI itself re-discover them from a slug index instead of re-generating from scratch.

## Architecture
- **One DB row per saved page.** Slug-addressable, immutable HTML blob, optional source prompt for re-generation, status flag for draft/published.
- **Sandboxed iframe render.** The saved HTML can include `<style>` tags, `@keyframes`, scripts — so it's rendered inside `<iframe sandbox="allow-scripts">` (NO `allow-same-origin`) to prevent it from touching the parent page's DOM, cookies, or storage.
- **Theme variables injected into the iframe.** On render, the parent passes the active `--color-accent`, `--font-serif`, `--hero-image`, etc. via the iframe's `:root` so the page visually flows from the live site even though it's isolated.
- **AI prompt knows the page library.** The site index injected into every chat turn includes the slug + title of every saved page so the AI can `scrollToPage` instead of re-generating identical content. Bulky HTML stays out of the prompt — fetched on demand via a `lookup_generated_page` tool.
- **Public viewer route at `/p/<slug>`.** Standalone page (no landing chrome) so it can be linked, screenshotted, and shared.

## Data model
Table `generated_pages`:

| Column | Notes |
|---|---|
| `id` SERIAL PK | |
| `slug` UNIQUE | Lowercase alphanumerics + hyphens, 1–200 chars, must start with alphanumeric (`^[a-z0-9][a-z0-9\-]{0,199}$`). Validated both at prompt-time (when listing the PAGE LIBRARY) and request-time (when serving by slug). |
| `title` | Display title shown in admin + AI index |
| `html` | The full generated page (`<style>` + body markup, no `<html>`/`<head>` wrapper) |
| `prompt` | Original user/system prompt that produced the page, for re-generation |
| `status` | `draft` (admin-only) or `published` (publicly viewable) |
| `created_at` | |

The slug regex is enforced as a module-level constant (`_GENERATED_PAGE_SLUG_RE` in `app.py`) so prompt-time and request-time use the exact same shape.

## API surface
- `GET /api/generated-page/<slug>` — public read (returns 404 for `status='draft'`).
- `GET /p/<slug>` — public viewer; renders the HTML inside a sandboxed iframe with theme-var injection.
- `GET /admin/api/generated-pages` — admin list (all statuses).
- `POST /admin/api/generated-pages` — admin create or save-from-chat (validates slug shape, ensures uniqueness).
- `PATCH /admin/api/generated-pages/<id>` — admin edit title/html/status.
- `DELETE /admin/api/generated-pages/<id>` — admin delete.
- **AI tool: `lookup_generated_page`** — function-call exposed to the chat completion so the AI can fetch the full HTML of a saved page by slug without paying the prompt-cost of including every page upfront.

## Key files
- `app.py` — `_GENERATED_PAGE_SLUG_RE` constant (~line 60), `generated_pages` table init, `/p/<slug>` viewer route (~line 6332), admin CRUD routes, AI tool registration
- `public/script.js` — iframe creation with `sandbox="allow-scripts"` (~line 9090), `postMessage` mount for live streaming, theme-var injection into iframe `:root`
- Chat pipeline — includes saved-page slug+title list in the per-turn site index

## External dependencies
- DOMPurify on the parent page is unnecessary because the iframe sandbox isolates the HTML — but if you ever inline the HTML directly (e.g. for SEO crawling), sanitize first.

## Pitfalls
- **`sandbox="allow-scripts"` without `allow-same-origin` is intentional.** Adding `allow-same-origin` defeats the sandbox: the iframe content could then access cookies and parent storage. If you need the iframe to talk to the parent, use `postMessage`, not shared origin.
- **Slug collisions.** Validate uniqueness on insert; AI is happy to suggest "summer-special" three times in a row.
- **HTML stored as-is** — no migration when the site theme changes. Theme-var injection is what keeps old pages visually fresh; if you change the variable NAMES, old pages break.
- **Don't put HTML in the prompt context.** The site index lists slug + title only; bulky HTML is fetched via the lookup tool. Otherwise the prompt cost grows linearly with the page library.
- **`<script>` tags inside the saved HTML execute** under `allow-scripts`. That's a feature for animations, but the AI must not be allowed to inject scripts pointing to attacker-controlled URLs. Either strip `<script src=...>` server-side, restrict to inline scripts, or document the trust boundary clearly.

## Adaptation notes
- For multi-tenant: scope `generated_pages` by `tenant_id` and add tenant to the slug uniqueness constraint.
- To support live progressive render (the page builds as the AI streams tokens), the iframe needs a `#__stream_root__` mount node and a `postMessage` channel — the parent feeds HTML chunks into the iframe as they arrive, and a post-stream `case 'generatePage'` skips the one-shot re-render so animations don't restart.
- For SEO, add a server-rendered fallback that strips scripts and inlines the HTML for crawlers without `User-Agent: Mozilla/...`.

## Adoption checklist
- [ ] `generated_pages` table with slug-uniqueness + status flag
- [ ] Module-level slug regex constant used in BOTH prompt-time and request-time validation
- [ ] Public viewer route at a stable URL prefix
- [ ] Iframe with `sandbox="allow-scripts"` only (no `allow-same-origin`)
- [ ] Theme-var injection into iframe `:root` on render
- [ ] AI tool that returns HTML on demand by slug
- [ ] Site-index block in the AI prompt that lists slug + title only
