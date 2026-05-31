---
name: WordPress self-hosted plugin updater
description: How private (non-wordpress.org) WP plugin auto-updates work here and the host-header trust gotcha.
---

# Self-hosted WordPress plugin auto-updates

The AI Concierge WP plugin is private, so it can't use wordpress.org auto-updates.
Instead it hooks WordPress's own update flow (`pre_set_site_transient_update_plugins`,
`plugins_api`) and polls a manifest the platform serves at `/plugin/update.json`;
the zip is served from `/plugin/download/<name>.zip` out of `plugin_dist/`.

## Rule: never build the update download_url from request headers
**Why:** WordPress treats the manifest's `download_url`/`package` as the trusted
source of the install package. With `ProxyFix(x_host=1)`, Flask's `request.url_root`
/ `request.host_url` derive host+scheme from forwarding headers, which can be
spoofed (Host / X-Forwarded-Host). Emitting an attacker host there = WordPress
downloads and installs an attacker ZIP = remote code execution on client sites.

**How to apply:** Build `download_url` from a TRUSTED canonical base. Reuse
`_public_base_url()` (admin-configured canonical URL → `PUBLIC_BASE_URL` env →
first `REPLIT_DOMAINS` host → request host only as a last-resort dev fallback).
Also validate the manifest's `zip` against the zip-name allowlist regex before
using it. A spoofed Host header must not change the emitted `download_url`.

## Publishing a new plugin version
Bump the `Version:` header AND `AAP_VERSION` in `wordpress-plugin/ai-concierge.php`,
run `scripts/build_plugin.py` (pure-stdlib zipfile; no `zip` CLI in this env), then
deploy. The zip MUST contain a top-level `ai-concierge/` folder or WordPress installs
it wrong. `plugin_dist/` must be committed since the workflow has no build hook.
