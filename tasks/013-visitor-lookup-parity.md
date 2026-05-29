# Task 013 — M13: full visitor lookup tools + dropped-content data/CRUD + web search

## Goal
Bring the visitor AI to full lookup parity with the original (~14 tools) and give
operators a way to populate the AI-referenced content the kit currently omits.

## Acceptance criteria
- [ ] Schema + minimal admin CRUD for the AI-referenced content the kit dropped:
      experiences, pricing_seasons, testimonials, team_members, faqs, blog_posts,
      video_gallery/podcast (optional), business info (site_settings subset or a
      `business_info` singleton), custom_section_items.
- [ ] Lookup tools (executors + schemas + registry): `lookup_services`,
      `lookup_service_availability`, `lookup_products`, `lookup_events`,
      `lookup_experiences`, `lookup_pricing`, `lookup_blog`, `lookup_team`,
      `lookup_faq`, `lookup_testimonials`, `lookup_business_info`,
      `lookup_custom_section_items`. Wire into `build_site_index` so each appears.
- [ ] `lookup_web_search` tool: Brave Search (`BRAVE_SEARCH_API_KEY`) with
      Anthropic web-search fallback + the WEB SEARCH POLICY prompt block;
      toggleable via agent_skills.
- [ ] `bookService` + availability chips surfaced in the visitor chat (services).

## Test requirements
- Gate: each new lookup tool returns expected shape against seeded rows; site
  index includes the new categories; web_search degrades cleanly without a key.

## Dependencies: none (uses M11/M12 commerce tables where present)
## Status: not_started   ## Branch: task/013-visitor-lookup-parity
