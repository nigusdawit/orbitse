# Integration Guide — putting the concierge on a site

Two ways to add the widget to an existing site. Both talk back to your hosted
platform; neither requires the client to see the code.

---

## 1. JS embed snippet (any site)

In the admin, create an **embed key** (Admin → Embed Keys) and add the site's
origin to its allowlist (e.g. `https://shop.example`). Then paste one tag before
`</body>`:

```html
<script src="https://YOUR-PLATFORM/embed/loader.js"
        data-embed-key="pk_xxxxxxxx"
        data-api-base="https://YOUR-PLATFORM"
        defer></script>
```

- The widget mounts in a **Shadow DOM** — the host page's CSS can't collide with
  it and vice-versa.
- Every API call carries `X-Embed-Key`. The platform validates the key **and**
  the request `Origin` against that key's allowlist; non-allowlisted origins get
  `403`, and chat/voice are rate-limited per tenant.
- `data-api-base` defaults to the origin the loader was served from, so you can
  often omit it.

**Same-origin (self-host):** if the widget is served from the same origin as the
platform (operator's own site), you can call `ChatUI.init({ apiBase: "" })`
directly without an embed key — see `/demo`.

---

## 2. WordPress plugin

1. Zip `wordpress-plugin/` (or drop the folder in `wp-content/plugins/`) and
   activate **AI Concierge**.
2. **Settings → AI Concierge**:
   - **Platform URL** — `https://YOUR-PLATFORM`
   - **Embed key** — the `pk_…` key (add the WP site origin to its allowlist)
   - **SSO secret** — must equal the platform's `SSO_SIGNING_SECRET` (leave blank
     to disable the embedded admin)
   - **Tenant ID** — `1` for self-host
   - **Enable widget** — tick to show it site-wide
3. The widget now loads on the front end. The **AI Concierge** sidebar item opens
   the hosted admin **inside wp-admin** via a single-use SSO token — no second
   login.

**For the embedded admin to work cross-site**, set on the platform:
`CSP_FRAME_ANCESTORS=https://your-wp-site.com`, and (because the admin cookie must
cross sites) `SESSION_COOKIE_SAMESITE=None` + `SESSION_COOKIE_SECURE=true` over
HTTPS. Add CSRF protection to state-changing admin routes before enabling cross-
site cookies. If WP and the platform are same-site, the defaults work as-is.

---

## Theming

The widget reads CSS variables with sensible fallbacks: `--color-accent`,
`--font-serif`, `--font-sans`, `--color-bg`, `--color-text`, `--glass-bg`,
`--glass-border`. Set them in the host page's `:root` (or the admin Theme settings
once wired) and the widget + generated pages inherit the brand.

---

## What the widget can do

Navigate a bundled gallery, scroll to sections, fill + submit forms through
conversation, render `generatePage` HTML live in a sandboxed iframe, reuse saved
pages, and speak replies. See `PROMPT_GUIDE.md` for the command model the AI uses.
