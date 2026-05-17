# Chat Markdown Rendering (Headings, Lists, Code, Tables)

## When to use
The AI returns markdown by default — `**bold**`, `# headings`, `- lists`, `` ```code blocks``` ``, pipe tables. Rendering it as raw text looks like broken output; rendering it as HTML without sanitization is dangerous (see `03-dompurify-html-sanitization.md`). You want chat bubbles, admin previews, and the auto-canvas fallback to render the same formatting consistently, with theme-token styling baked in.

## Architecture
A self-contained `renderMarkdown(text) → string` converter — no markdown library dependency. It handles only the subset the AI actually emits, in this fixed order:

1. **Code fences** (` ```lang\n...\n``` `) extracted first into placeholders so their contents don't get further processed.
2. **Tables** (pipe-delimited rows with a `|---|---|` divider) — rebuilt into a real `<table>` with `<thead>` and `<tbody>`.
3. **Headings** (`#`, `##`, `###`) → `<h1>`, `<h2>`, `<h3>`.
4. **Block lists** (`- item` / `* item` / `1. item`) — coalesced into `<ul>` / `<ol>` runs.
5. **Inline formatting** (`**bold**`, `*italic*`, `` `code` ``, `[text](url)`).
6. **Paragraphs** — remaining blank-line-separated runs wrapped in `<p>`.
7. **Code-fence placeholders** restored as `<pre><code class="lang-X">`.
8. The whole string is run through `safeSetHTML` (see DOMPurify skill) before reaching the DOM.

Theme integration is done in CSS — the chat stylesheet targets `.chat-bubble :is(h1,h2,h3,ul,ol,table,pre,code,a)` directly, so every theme swap (color editor, density preset) flows through to AI output without any JS re-render.

For long replies (>4 sentences OR >6 lines OR contains a table), the chat bubble collapses to a "View more" affordance that opens the auto-canvas fallback (see `06-auto-canvas-fallback.md`) instead of letting the corner chat bubble grow off-screen.

## Data model
None.

## API surface
- `renderMarkdown(text) → string` — pure function, no DOM.
- `safeSetHTML(node, renderMarkdown(text))` — the actual write.

## Key files
- `public/script.js` — `renderMarkdown`, length-detection for auto-canvas promotion.
- `public/styles.css` — the `.chat-bubble :is(...)` rules that style each rendered element.

## External deps
None. The converter is ~150 lines of regex; no `marked`, no `remark`, no `markdown-it`.

## Pitfalls
- **Regex order matters.** If you process inline bold before extracting code fences, ` ```js\n**not bold**\n``` ` will get HTML `<strong>` tags injected inside the code. Always extract fences first, restore last.
- **Pipe tables are fragile.** The AI sometimes emits a markdown table missing the `---` divider row. Treat it as a soft requirement; fall back to plain text rather than rendering a malformed `<table>`.
- **Streaming = partial markdown.** Halfway through a code fence the buffer ends with `` ``` `` and nothing else — your converter will emit `<pre></pre>` with no body until the next chunk. Either: render textContent-only while streaming, then convert once on stream-end; or: detect "open fence" and bail out of converting the trailing run.
- **Auto-link the wrong things.** A naive `https?://\S+` regex will eat trailing punctuation (`See https://example.com.` → link includes the period). Strip trailing `.,;:!?` after the match.
- **Code blocks must NOT be inside `<p>`.** Invalid HTML, browsers will close the `<p>` early and reflow. Process blocks before paragraphs.
- **Don't use the chat markdown renderer for admin-authored docs.** Admins expect real markdown (footnotes, frontmatter, blockquotes). Use a real library there.

## Adaptation notes
- If your AI rarely emits tables, drop the table phase — it's the heaviest regex.
- Syntax highlighting can be slotted in by setting `class="lang-X"` on `<pre><code>` and lazy-loading Prism/Shiki for those bubbles only.
- For RTL languages, set `dir="auto"` on the bubble root and let the browser do per-paragraph mirroring; don't try to detect in the converter.
- If you adopt a real markdown library later, keep the same `renderMarkdown` signature so call sites don't change.

## Adoption checklist
- [ ] Implement `renderMarkdown(text) → string` with the phase order above.
- [ ] Route every call through `safeSetHTML`.
- [ ] Style `.chat-bubble :is(h1,h2,h3,ul,ol,table,pre,code,a)` with theme tokens so theme edits flow through.
- [ ] During streaming, render `textContent` only; rerun the converter once on stream end (or on each `\n` boundary).
- [ ] Add a length detector that promotes long replies to the auto-canvas fallback.
- [ ] Verify a half-finished code fence in the stream doesn't crash the bubble.
