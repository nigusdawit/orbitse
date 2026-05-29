# Prompt & Command Guide

How the visitor AI is steered, and the action commands it emits. The default
system prompt lives in `prompts.py` (`BASE_SYSTEM_PROMPT`); the admin can
override it from **Chatbot → System prompt** (blank = the built-in default).

---

## Per-turn context (kept small on purpose)

Every turn the prompt is assembled from:
1. the base prompt (or the admin override),
2. the theme block (substituted into `{THEME_PLACEHOLDER}`),
3. a **compact SITE INDEX** — names + slugs per category (gallery, forms,
   presentations, …), NOT full descriptions,
4. the **FORMS schema**, and
5. the **PAGE LIBRARY** (published AI pages, for reuse).

Full detail is fetched on demand via **lookup tools**, so per-turn token cost
stays roughly flat as the site grows.

## Lookup tools (function calling)

`lookup_gallery_cards`, `lookup_forms`, `lookup_generated_page`,
`lookup_presentation`, `lookup_knowledge_base` (hidden unless pgvector is
available), plus any admin-defined **custom SQL/HTTP skills** and enabled **MCP**
tools. The model calls them with narrow filters; results stream back into context.
The loop runs up to 4 rounds per turn, each round cost-stamped to the ledger.

## Commands (the AI acts by emitting one ```command``` JSON block)

| Command | Effect |
| --- | --- |
| `navigate` | Open a gallery card by slug (split-screen). |
| `scrollToSection` | Scroll the host page to a section id. |
| `showSavedPage` | Render a published AI page by slug (instant, no tokens). |
| `generatePage` | Render fully custom HTML **live** into a sandboxed iframe as it streams. |
| `generateVisual` / `showSlide` | Quick data card / structured slide. |
| `submitForm` / `partialFormSave` | Submit / autosave a form collected in chat. |
| `start_presentation` | Launch a deck with voice narration. |
| `heroMessage` | Update a hero element's text. |

**Decision priority** (cheapest match wins): gallery card → section → saved page →
`generatePage` (last resort) → plain text. The prompt enforces "every promise to
act needs a command block in the same reply" and "no colons in spoken text".

## generatePage specifics

It renders in a sandboxed `iframe` with the site's CSS variables + hero image
injected, so generated pages match the brand. The widget live-streams the HTML
(decoding the JSON string incrementally and flushing on safe tag boundaries via
`postMessage`), and skips the one-shot re-render at the end so animations don't
restart. Because it's slow, the prompt tells the AI to "talk while it builds" —
emit a bridge line + 2–4 real bullets before the command block.

## Voice

Replies are spoken sentence-by-sentence as they stream (`VoiceAgent.streamSpeak*`),
so the first sentence is audible ~1s after the model's first period. STT is Web
Speech (free) or Whisper (premium). All gated by the admin Voice settings.

## Admin AI

The admin assistant uses elevated tools: read-only `admin_run_sql` (SELECT-only,
100-row, rolled-back) + `admin_propose_insert/update/delete`, which **park** a
change for the owner to **Approve** — nothing is written until then.
