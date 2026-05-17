# Merge-Tag Templates

**Category:** Messaging
**Related:** `messaging/01-unified-send-helper.md`, `messaging/03-campaign-manager.md`

## When to use
You need to personalize message bodies with recipient data — `Hi {{first_name}}, your order {{order.id}} is ready` — without dragging in a full templating engine (Jinja, Handlebars). One regex, one dotted-lookup helper, missing keys render as empty string so a half-filled subscriber row never produces a literal `{{first_name}}` in the wild.

## Architecture
- **One regex** matches `{{ key }}` (whitespace tolerant, dotted paths allowed).
- **Two-layer context build:** a flat subscriber-derived dict (`id`, `email`, `phone`, `full_name`, `first_name`, `last_name`) merged with the subscriber's free-form `custom_fields` JSONB column and any per-send `extra` dict (e.g. `unsubscribe_url`, `order.total`).
- **Missing keys → empty string**, not the literal token. Loud failure is worse than a slightly-awkward greeting.
- **Dotted lookups** (`{{order.total}}`) walk nested dicts; any missing hop short-circuits to empty.

## Data model
No dedicated table. Context is built at send time from:
- `subscribers.full_name` (split into first/last by first space — good enough for 95% of real names)
- `subscribers.email`, `subscribers.phone`
- `subscribers.custom_fields` JSONB — arbitrary admin-defined fields (`company`, `tier`, etc.) automatically become merge tags
- Per-send `extra` dict from the campaign loop (typically just `unsubscribe_url`)

## API surface
From `messaging.py`:
- `render_merge_tags(text: str, context: dict) -> str` (line 148) — pure function, idempotent, safe on `None`/empty
- `subscriber_context(sub: dict, extra: dict | None = None) -> dict` (line 173) — builds the flat dict from a subscriber row

## Key files
- `messaging.py:145` — `_MERGE_RE` regex
- `messaging.py:148` — `render_merge_tags`
- `messaging.py:173` — `subscriber_context`
- `app.py:~33041` — campaign dispatch loop that calls both per recipient

## External dependencies
None.

## Pitfalls
- **Name splitting is naive.** "Mary Anne Smith" → first="Mary", last="Anne Smith". Acceptable for greeting copy, **NOT** for legal/billing docs — use a real name field instead.
- **Custom fields shadow nothing.** The flat dict is built first, then `custom_fields` is merged with a "don't overwrite existing keys" rule (line 190). So an admin who names a custom field `email` won't accidentally clobber the canonical email. Verify this if you refactor.
- **No HTML escaping.** Output goes straight into the email body. If a subscriber's `full_name` is `<script>...</script>` and the email is rendered in a web preview, you have XSS. Mitigation: store the snapshot (`body_snapshot`) and escape at render time in the admin viewer.
- **The regex does NOT support conditionals or loops.** If you find yourself wanting `{% if first_name %}`, switch to Jinja — don't extend this.

## Adaptation notes
- To add a global merge tag (`{{site_name}}` everywhere), inject it into `extra` at the top of every send loop. Don't bake it into `subscriber_context` — keep that function strictly about the subscriber.
- For multi-language merge tags, pass the resolved-language string in `extra` (e.g. `{"greeting": "Hola"}`) and reference `{{greeting}}` in the template.
- To get strict mode (missing key raises), wrap `render_merge_tags` and have the regex callback raise `KeyError` instead of returning empty. Keep both modes available so transactional emails can be strict while marketing remains lenient.
- The same renderer is reused by the Review-Collector module to wrap an AI-drafted message inside a brand template — anywhere you have `subscriber-like context + a template string` this helper is the right answer.
