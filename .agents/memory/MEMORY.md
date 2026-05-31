# Memory Index
- [Embed origin allowlist](embed-origin-allowlist.md) — embed Origin matching uses canonical scheme://host[:port] (no path); server-side emulators must match; SSO dry-verify mirrors real verifier.
- [WP self-hosted updater](wp-plugin-self-hosted-updater.md) — private WP plugin auto-update via /plugin/update.json; NEVER build download_url from request headers (host-poisoning→RCE); use _public_base_url().
