# Task 019 — M19: security hardening (CSRF + secrets-at-rest)

## Goal
Close the remaining security-review prerequisites for production + cross-site WP.

## Acceptance criteria
- [x] CSRF protection on state-changing admin routes: per-session token
      (`secrets.token_urlsafe(32)`, constant-time compare) issued via
      `/admin/api/csrf-token`, validated on every cookie-authed unsafe-method
      request under **/admin** (broadened from /admin/api per review H1); exempt
      the token-authed surfaces (Bearer API key, embed/public, webhooks, VELO,
      /admin/sso, /admin/login). Unblocks `SESSION_COOKIE_SAMESITE=None` for WP.
- [x] Secrets at rest (Fernet, key from `SECRETS_ENCRYPTION_KEY` or derived from
      FLASK_SECRET_KEY): encrypt `mcp_servers.auth_credential` on write, decrypt
      at point of use, idempotent migration for legacy plaintext, GET redacts.
      `encrypt()` fails closed (raises) rather than storing cleartext (review M1).
      (Provider/webhook secrets reuse the same `crypto` layer when DB-stored;
      env_manager relocation not needed — no such module in the package.)
- [x] Security headers: opt-in HSTS (`ENABLE_HSTS`/Secure-cookie),
      X-Content-Type-Options, Referrer-Policy, single composed CSP on /admin with
      a per-response **script nonce** (no `unsafe-inline` for scripts; review M2).
- [x] Audit: no secret logged (Fernet errors carry no plaintext; GET redacts);
      admin API key + CSRF token compares are constant-time; `?key=` no longer
      relaxes CSRF (review L1).

## Test requirements
- Gate: state-changing admin call without CSRF token → 403; with token → ok;
  encrypted credential round-trips (stored ciphertext != plaintext, decrypts on
  use); security headers present.
- **security-review** required.

## Dependencies: none (M18 dep dropped — silo)   ## Status: done   ## Branch: task/019-security-hardening

## Notes
Merged to main (--no-ff). Gate: 339/339 incl. crypto roundtrip/legacy-passthrough,
CSRF reject-without-token / accept-with / safe-GET-exempt / API-key-exempt,
stored credential is ciphertext + decrypts at use + GET redacts + migration
encrypts legacy plaintext, and the security headers (nosniff, Referrer-Policy,
nonce'd CSP). Unit: `test_security.py` pins the crypto primitives (roundtrip,
empty/legacy passthrough, idempotent encrypt_if_plaintext, wrong-key + corrupt-
token fail-closed). **security-review (agent) run; 4 findings all fixed** in a
follow-up commit: H1 CSRF scope broadened to all /admin, M1 crypto fails closed,
M2 CSP script nonce (dropped unsafe-inline), L1 Bearer-only API-key exemption.
Reviewer confirmed correct: constant-time token, SameSite=None soundness,
enc:v1: non-confusable, no secret leakage, embed widget unconstrained by admin CSP.
