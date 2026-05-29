# Task 007 — M7: Embed snippet + cross-origin widget

## Goal
`embed/loader.js` snippet that mounts the visitor widget in a Shadow DOM on any third-party origin,
configured by `data-embed-key` + `data-api-base`, self-fetching theme/config; plus the server-side
cross-origin trust boundary: per-tenant embed-key auth, origin allowlist validation, scoped CORS, and
per-tenant rate limiting on the embeddable endpoints.

## Acceptance criteria (to expand on first touch)
- [ ] `embed/loader.js` + concatenated widget bundle; Shadow DOM isolation; no host-CSS dependency.
- [ ] Embed-key auth + `Origin`/`Referer` allowlist check on `/api/chat`, voice, forms, gallery reads.
- [ ] Per-tenant scoped CORS (not `*`) + preflight; per-tenant rate limiting (Postgres/Redis-backed
      for central mode — replace in-process limiter).

## Test requirements (to expand)
- pytest: allowlisted origin passes / non-allowlisted rejected; embed-key→tenant resolution; CORS
  headers correct; rate-limit triggers.
- Cross-origin runtime test page (different origin) loads widget; **security-review required**.

## Dependencies: 001, 006   ## Parallel-with: —
## Status: not_started   ## Branch: task/007-embed-widget
