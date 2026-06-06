---
name: generated_pages reuse vs public-web policy
description: where the "saved AI page" reuse status filter lives, and why all the spots must agree
---

# generated_pages: reuse status filter is spread across several spots

The visitor AI's "reuse a saved page" feature (showSavedPage) decides what
the model may re-show based on `generated_pages.status`. That policy is NOT in
one place — it is enforced (and *advertised to the model*) in several spots
that must all agree, or the model gets contradictory signals and silently
refuses to reuse:

- The **PAGE LIBRARY** catalog spliced into the visitor system prompt (what the
  model is *told* it can reuse).
- The **lookup tool** (`lookup_generated_page`) — both slug mode and topic
  full-text mode.
- The **by-slug serving endpoint** (`api_generated_page_by_slug`) — both the
  exact-slug query AND the stem/fuzzy fallback query.
- A **separate prompt block** that used to list drafts as "cannot reuse" — this
  one is easy to miss; if you flip reuse to include drafts but leave this block,
  the model is told both "reuse this draft" and "you can't reuse drafts."

**Why:** a 2026-06 change let in-chat reuse include `draft` pages while keeping
them off the public web. Flipping the obvious queries wasn't enough — the stale
"UNPUBLISHED DRAFT PAGES (cannot reuse)" prompt block contradicted it, so the
model still avoided draft reuse. Only a code review caught the 6th spot.

**How to apply:** when changing which statuses are reusable, grep ALL of:
PAGE-LIBRARY query, lookup_generated_page (x2), api_generated_page_by_slug (x2),
and any draft-listing prompt text — and keep the public surfaces
(`/page/<slug>`, sitemap, llms.txt) on their own (published-only) policy. The
chat reuse path (by-slug → rendered in the immersive overlay) is separate from
the public standalone page route; they can legitimately have different filters.
