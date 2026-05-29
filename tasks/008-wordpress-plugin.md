# Task 008 — M8: WordPress plugin + SSO

## Goal
`wordpress-plugin/` PHP plugin: settings page (embed key + api base + toggles), auto-enqueue
`loader.js` site-wide, `[concierge]` shortcode + Gutenberg block, and a wp-admin "AI Concierge" page
that iframes the hosted per-tenant admin via a short-lived single-use signed SSO token. Platform-side
SSO mint/verify endpoint.

## Acceptance criteria (to expand on first touch)
- [ ] `ai-concierge.php` (header, settings page, enqueue, shortcode, block), `readme.txt`, assets.
- [ ] Platform SSO endpoint: HMAC, single-use, tenant-scoped, exp ≤ 60s; verify on admin-iframe load.
- [ ] wp-admin embedded admin loads via SSO; forged/expired token rejected.

## Test requirements (to expand)
- pytest: SSO token mint/verify, single-use enforcement, expiry, tenant scoping.
- Manual: install plugin zip in local WP; widget injects; shortcode/block render; admin iframe loads.
- **security-review required** (SSO + iframe embedding / clickjacking headers).

## Dependencies: 007, 002   ## Parallel-with: —
## Status: not_started   ## Branch: task/008-wordpress-plugin
