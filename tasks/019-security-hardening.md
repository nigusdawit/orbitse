# Task 019 — M19: security hardening (CSRF + secrets-at-rest)

## Goal
Close the remaining security-review prerequisites for production + cross-site WP.

## Acceptance criteria
- [ ] CSRF protection on state-changing admin routes (POST/PUT/PATCH/DELETE under
      /admin/api): per-session token issued to the dashboard + validated; exempt
      the token-authed surfaces (embed endpoints, webhooks, VELO, /admin/sso).
      This unblocks `SESSION_COOKIE_SAMESITE=None` for cross-site WP.
- [ ] Secrets at rest (Fernet, key from env): encrypt mcp_servers.auth_credential,
      automation webhook secrets, review/provider API keys stored in DB. Relocate
      `env_manager` + the secrets UI (write-masked, read presence-only).
- [ ] Security headers: HSTS (prod), X-Content-Type-Options, Referrer-Policy,
      a baseline CSP on /admin.
- [ ] Audit: confirm no secret is ever logged; admin API key compare is constant-time.

## Test requirements
- Gate: state-changing admin call without CSRF token → 403; with token → ok;
  encrypted credential round-trips (stored ciphertext != plaintext, decrypts on
  use); security headers present.
- **security-review** required.

## Dependencies: 018   ## Status: not_started   ## Branch: task/019-security-hardening
