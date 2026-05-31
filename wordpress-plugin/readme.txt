=== AI Concierge ===
Requires at least: 5.8
Requires PHP: 7.4
Stable tag: 1.1.0
License: Proprietary

Adds the hosted AI Concierge widget to your WordPress site and lets you manage
it from wp-admin — without your clients ever touching the platform code.

== What it does ==
* Loads the concierge widget on your public site (style-isolated Shadow DOM).
* Manage everything (chat, voice, content, automations, …) from the wp-admin
  "AI Concierge" page, which securely embeds the hosted admin via single-use SSO.
* [concierge] shortcode + a Gutenberg block (the widget is a global floating bar,
  so these simply confirm it's active on a page).

== Setup ==
1. Install + activate the plugin (upload the zip, or drop the folder in wp-content/plugins).
2. Settings → AI Concierge:
   - Platform URL   — your hosted platform, e.g. https://concierge.youragency.com
   - Embed key      — the publishable pk_… key from the platform's admin → Embed Keys
                      (add your WordPress site's origin to that key's allowlist!)
   - SSO secret     — confidential; must equal the platform's SSO_SIGNING_SECRET
                      (leave blank to disable the embedded-admin page)
   - Tenant ID      — your tenant (1 for a single-tenant / self-hosted platform)
   - Enable widget  — tick to show the concierge on the public site
3. Save. The widget appears on your site; "AI Concierge" in the sidebar opens the
   hosted admin in an iframe (no second login).

== Security ==
* The embed key is publishable (origin-allowlisted + rate-limited on the platform).
* The SSO secret is confidential — used only server-side (PHP) to sign a 45-second,
  single-use token. The platform verifies it (HMAC-SHA256) and only allows your
  WordPress origin to frame the admin (set CSP_FRAME_ANCESTORS on the platform to
  your WP site origin).

== Manual verification (no automated WP test in the build env) ==
* Activate, configure, confirm the widget loads on a front-end page (network call
  to /embed/loader.js, then /api/chatbot-settings with the X-Embed-Key header).
* Open wp-admin → AI Concierge; the hosted admin should load in the iframe and be
  logged in. A tampered/expired token must show "invalid or expired SSO token".
