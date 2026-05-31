---
name: Embed origin allowlist shape
description: How the platform matches an embed request's Origin against a key's allowlist
---

# Embed origin allowlist matching

The embed-key origin allowlist (`tenant_embed_keys.origin_allowlist`, checked in
`admin_ai_platform/embed_auth.py:_origin_allowed`) compares against a **canonical
browser Origin: `scheme://host[:port]` with NO path**.

**Why:** A real browser only ever sends `Origin: https://example.com` (no path).
Any server-side caller emulating an embed (e.g. the WordPress plugin's Test
Connection, which sends `Origin: <site>`) must send the same shape. Sending
`home_url()` raw (which can include a subdirectory path like
`https://example.com/blog`) makes the allowlist check false-fail.

**How to apply:** When constructing an Origin header from a WordPress/site URL,
strip to scheme+host+port (the plugin uses `aap_site_origin()` via
`wp_parse_url`). The same canonical shape is what admins must paste into the
embed key's allowlist in the admin UI.

# SSO dry-verify

`_sso_verify_signature_only` in `app.py` (used only by `/embed/diagnostics`)
intentionally skips jti consumption but otherwise MUST mirror the real
`_sso_verify_token` structural checks (require non-empty jti, castable int tid,
exp/ttl) — otherwise it can report a token "valid" that the real `/admin/sso`
login would still reject.
