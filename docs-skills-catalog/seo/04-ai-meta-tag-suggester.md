# AI meta-tag suggester

## When to use
Operators who edit SEO fields rarely and don't know what makes a good title/description. An "Ask AI" button that proposes a title, description, and keywords from the live site content removes the blank-page problem and keeps quality consistent.

## Architecture
A single admin-only endpoint reads compact context about the site (name, tagline, top sections, business description) and asks the LLM for a JSON object the admin form can pre-fill:

1. Admin clicks "Generate suggestions" in the SEO tab.
2. Frontend POSTs to the suggester endpoint.
3. Server builds a compact prompt from `site_settings`, `business_info`, and a few section titles — no bulky body text.
4. OpenAI is called in JSON mode requesting `{title, description, keywords[]}`.
5. The endpoint stamps a `seo_suggest` row in `api_cost_events` so the spend lands in the Cost dashboard.
6. The form fields are populated; the admin reviews and saves.

This is suggest-only — nothing is written to `site_settings` automatically.

## Data model
- Reads `site_settings`, `business_info`, `page_sections`.
- Writes a cost-event row (see the cost-transparency skill in the analytics catalog).
- No new tables.

## API surface
- `POST /admin/api/seo/generate` → `{title, description, keywords[]}`, auth: `@admin_required`.

## Key files
- `app.py:23773` — `generate_seo_suggestions()` route.
- `app.py:23824` — OpenAI JSON-mode call with content extraction.
- `templates/admin/dashboard.html:14819` — "SEO" tab UI with the Generate button.

## External deps
- OpenAI Python SDK (any chat-completions model that supports `response_format={"type":"json_object"}` works).

## Pitfalls
- Force JSON mode (`response_format={"type":"json_object"}`) and still wrap the parse in `try/except` — models occasionally return JSON wrapped in prose.
- Cap input tokens. If the admin's site has 200 sections, do not dump them all — pick the top N by `sort_order`.
- Rate-limit per admin (the LLM call costs money). One generation per minute is plenty.
- Never auto-save. Always populate the form and let the human approve.
- Suggested keywords are mostly cosmetic for Google but help operators think about coverage — keep them in the response.

## Adaptation notes
- The same pattern works for blog excerpt suggestions, alt-text suggestions, and social-share copy — swap the prompt and target field set.
- For very large sites, summarise the context first (RAG-style) instead of stuffing it; the page-bundle approach (compact index, not full bodies) maps directly.

## Adoption checklist
- [ ] Decide which DB rows form the "context" — keep it small and stable.
- [ ] Add a JSON-mode chat-completion helper if you don't already have one.
- [ ] Wire a Generate button into the admin SEO form that POSTs to the endpoint and pre-fills inputs.
- [ ] Stamp a cost-event row per call (provider, model, tokens).
- [ ] Rate-limit per admin session.
