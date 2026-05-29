# Task 013 — M13: full visitor lookup tools + dropped-content data/CRUD + web search

## Goal
Bring the visitor AI to full lookup parity with the original (~14 tools) and give
operators a way to populate the AI-referenced content the kit currently omits.

## Acceptance criteria
- [x] Schema + minimal admin CRUD for the AI-referenced content the kit dropped:
      experiences, pricing_seasons, testimonials, team_members, faqs, blog_posts,
      business_info singleton, custom_section_items. (video_gallery/podcast were
      the explicitly-optional extras — omitted.)
- [x] Lookup tools (executors + schemas + registry): `lookup_services`,
      `lookup_service_availability`, `lookup_products`, `lookup_events` (M12),
      `lookup_experiences`, `lookup_pricing`, `lookup_blog`, `lookup_team`,
      `lookup_faq`, `lookup_testimonials`, `lookup_business_info`,
      `lookup_custom_section_items`. Wired into `build_site_index`.
- [x] `lookup_web_search` tool: Brave Search (`BRAVE_SEARCH_API_KEY`) with
      Anthropic web-search fallback + the WEB SEARCH POLICY prompt block (only
      injected when the skill is enabled); toggleable via agent_skills.
- [~] `bookService` + availability: `lookup_service_availability` returns the
      slot data; the visitor-chat UI chips are a frontend follow-on (M16 SPA).

## Test requirements
- Gate: each new lookup tool returns expected shape against seeded rows; site
  index includes the new categories; web_search degrades cleanly without a key.

## Dependencies: none (uses M11/M12 commerce tables where present)
## Status: done   ## Branch: task/013-visitor-lookup-parity

## Notes
Merged to main (--no-ff). Gate: 265/265 green incl. content CRUD (create/list/
update, unknown-resource 404, blog slug-required, business_info JSONB),
every new lookup returning expected shape against seeded rows, site-index
categories, and web-search fail-closed without a key. Unit: `test_lookup_parity`
pins the registry consistency (executor↔schema↔metadata) + web-search
degradation. Drift: `custom_section_items` made standalone (a `section_slug`
group field) instead of FK→page_sections, since the package drops the
page_sections editor. bookService availability UI chips deferred to the M16 SPA.
