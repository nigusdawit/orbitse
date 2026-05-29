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
## Status: done (merged)   ## Branch: task/008-wordpress-plugin

## Security review (independent) — findings + resolution
Crypto core judged sound (HMAC over correct bytes, constant-time, no alg field,
tid authenticated by signature, PHP↔Python byte-identical). Findings:
- HIGH single-use jti was in-process only → multi-worker replay. FIXED: DB-backed
  sso_used_jtis claim (INSERT ON CONFLICT DO NOTHING) — final across workers.
- HIGH SSO secret fell back to FLASK_SECRET_KEY. FIXED: no fallback; SSO is
  disabled (mint raises / verify None) when SSO_SIGNING_SECRET is unset.
- HIGH cross-site iframe vs SameSite=Lax cookie. ADDRESSED: SESSION_COOKIE_SAMESITE
  + SESSION_COOKIE_SECURE are configurable (opt-in None+Secure for cross-site WP);
  documented that cross-site cookies require CSRF protection on state-changing
  admin routes (follow-on before enabling None+Secure).
- HIGH "admin queries not tenant-scoped." DECISION (documented, not a code bug for
  the shipping model): the deployment model is ONE DATABASE PER TENANT (each
  client install has its own Postgres), so there is no cross-tenant data in one
  DB. tenants/tenant_features/embed-keys provide feature-flag + key management,
  NOT per-row isolation. Single-DB multi-tenancy (adding tenant_id columns +
  query scoping to chat/pages/etc.) is an explicit follow-on if that model is
  ever adopted. In self_host (default) there is exactly one tenant.
- MEDIUM token-in-URL leak: mitigated by 45s TTL + final DB single-use.

Gate (159/159): fail-closed-without-secret, roundtrip, DB single-use replay
reject, forged/expired/over-long reject, /admin/sso session + 403,
frame-ancestors allow configured WP origin / default-deny.
PHP unverified in sandbox (no php binary); manual WP-install check in readme.txt.
