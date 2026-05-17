# DOMPurify-Sanitized AI HTML Injection

## When to use
Any time you take a string from the AI (chat reply, generated page, fallback canvas, knowledge-base citation snippet) and inject it into the DOM as HTML. The model is allowed to emit markdown/HTML on purpose, but a prompt-injection attack or an upstream RAG document could try to slip a `<script>` tag, an `onerror=` attribute, or a `javascript:` URL through that path. DOMPurify is the trusted gate that strips them out without breaking legitimate formatting.

## Architecture
A single trusted helper function — `safeSetHTML(node, html)` — is the *only* place in the frontend that ever assigns `innerHTML` from a string that originated outside the app. Direct `element.innerHTML = ...` from AI text is treated as a bug in code review.

```
safeSetHTML(node, html):
    if window.DOMPurify is missing → log + fall back to textContent
    clean = DOMPurify.sanitize(html, profile)
    node.innerHTML = clean
```

Each surface picks a `profile` (DOMPurify config) appropriate to its needs:
- **Chat bubble** — allows the markdown output: headings, lists, bold, code, inline links (target="_blank" added in an `afterSanitize` hook), and the `[source: file p.N]` pill anchors used by RAG citations.
- **Auto-canvas fallback** — same as chat bubble but allows additional layout tags (`section`, `aside`, `table`).
- **`generatePage` iframe** — the iframe is `sandbox="allow-scripts"` and isolated from the parent, so the streaming HTML is appended via `postMessage` to the iframe; the iframe itself runs DOMPurify on each chunk before appending it. The host page never sees the unsanitized content.

For RAG citations, DOMPurify's `ADD_ATTR` + `ALLOWED_URI_REGEXP` is widened *only* to permit `data-cite-id="<integer>"` on `<a>` tags so the click handler can resolve the chunk via `/admin/api/kb/chunk/<id>`.

## Data model
None.

## API surface
- `safeSetHTML(node, html, profileName?)` — the only sanctioned innerHTML write path.
- `renderMarkdown(text)` — converts markdown to HTML, then routes the result through `safeSetHTML` automatically.

## Key files
- `public/index.html` — DOMPurify CDN `<script>` tag.
- `public/script.js` — `safeSetHTML`, `renderMarkdown`, the RAG citation hook.
- (Optional) `chat-ui-kit/chat-ui.js` — same helpers if the chat UI is extracted as a reusable widget.

## External deps
- [DOMPurify](https://github.com/cure53/DOMPurify) — single CDN script, no build step.

## Pitfalls
- **CDN failure = no formatting OR worse, raw HTML injection.** Always fall back to `textContent` (visible markdown source) if `window.DOMPurify` is missing — never silently set `innerHTML`.
- **`target="_blank"` without `rel="noopener noreferrer"`** is an XSS-adjacent footgun (the opened tab can `window.opener.location = …`). Use `DOMPurify.addHook('afterSanitizeAttributes', ...)` to inject the rel attribute on every external link.
- **`data:` URIs are blocked by default.** If you genuinely need inline images in chat bubbles (e.g. AI-generated chart screenshots), explicitly allow `data:image/...` via `ALLOWED_URI_REGEXP` — don't disable URI checking globally.
- **The streaming render path is the tricky one.** If you sanitize the *cumulative buffer* on every token, the cost is O(n²). Sanitize the *complete* buffer only when the stream ends, and stream a textContent-only preview while it's growing. Or: only run `safeSetHTML` on `\n`-bounded chunks.
- **iframe-injected HTML must sanitize INSIDE the iframe**, not in the host. The iframe is sandboxed precisely so a payload can't reach the host; sanitizing in the host AND the iframe is belt-and-braces, sanitizing only in the host is wrong (a `postMessage` listener inside the iframe could be tricked into running unsanitized HTML).
- **Markdown renderers vary.** A naive regex markdown converter may leave `<script>` in code blocks. Always: markdown→HTML→DOMPurify→DOM. Never: markdown→DOMPurify→DOM (DOMPurify can't see the script before the converter wraps it in a `<code>` block).

## Adaptation notes
- Per-surface profiles let you be strict in less-trusted places (chat bubbles) and loose in more-trusted ones (admin preview of an admin-authored doc). Don't unify them into one profile to "simplify".
- If you replace DOMPurify with a different sanitizer (sanitize-html on Node, bleach on Python), keep the same `safeSetHTML` indirection so the swap is one file.
- A server-side mirror — running DOMPurify-equivalent sanitization at write time too — is worth it for content stored in the DB that you don't want to re-sanitize on every render (e.g. saved KB documents).

## Adoption checklist
- [ ] Add DOMPurify via CDN in your base template.
- [ ] Write a single `safeSetHTML(node, html, profile?)` helper and forbid all other innerHTML-from-string usage in code review.
- [ ] Pick per-surface profiles; do NOT use the default profile for chat bubbles (it's too loose for AI output).
- [ ] Add the `afterSanitizeAttributes` hook for `target="_blank"` → `rel="noopener noreferrer"`.
- [ ] If you support RAG citation pills, widen `ADD_ATTR` to permit `data-cite-id` on anchors.
- [ ] In any sandboxed iframe that receives streamed HTML, sanitize INSIDE the iframe, not just in the host.
- [ ] Sanitize markdown AFTER converting to HTML, never before.
