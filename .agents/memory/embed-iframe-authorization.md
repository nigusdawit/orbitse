---
name: Embed concierge iframe authorization
description: How unauthorized third-party embedding of the concierge widget is prevented, and why same-origin keyed API calls must bypass the origin allowlist.
---

# Embed concierge iframe authorization

The embeddable concierge is the REAL site shell served at `/embed/concierge`
inside a cross-origin iframe on the client's own site. Because the iframe is
served from OUR origin, its `/api/*` calls are SAME-ORIGIN — they carry our
origin, not the host site's.

## The control model (what actually stops abuse)
- **CSP `frame-ancestors` on `/embed/concierge` is the primary, browser-enforced
  gate** over who may iframe the widget. It can't be spoofed by a forged
  Referer/Origin. No/invalid key → `'self'` only; valid key → `'self'` + the
  key's allowlisted origins; wildcard allowlist → `*`.
- An explicit key that doesn't resolve to an **enabled** key fails CLOSED (403),
  so a revoked/disabled client embed visibly stops working.

**Why:** The iframe model means per-request Origin checks alone can't gate the
host site (the iframe's API calls look same-origin). The framing decision has to
be made at iframe-load time, and `frame-ancestors` is the only spoof-proof lever.

## Same-origin keyed API calls must bypass the origin allowlist
The validated key is injected into the served shell (`window.__AAP_EMBED_KEY__`)
plus a fetch wrapper that adds `X-Embed-Key` to same-origin `/api/*` calls. So
`_embed_auth` must **skip the per-key origin-allowlist check when the request's
Origin equals our own origin** (still validating the key is enabled), while
keeping allowlist enforcement for genuine cross-origin keyed traffic (the old
direct-fetch widget). If you don't skip it, every iframe API call 403s because
our own origin isn't in the host-site allowlist.

## Don't break first-party
The homepage `/` renders the same shell but with NO key injected and NO embed
CSP header — it stays keyless/first-party. Only `/embed/concierge` gets the key
injection + `frame-ancestors`. Direct visits to `/embed/concierge` still work
(frame-ancestors restricts framing, not navigation).

**How to apply:** Any change to the embed flow must preserve all four:
(1) frame-ancestors scoped to the key, (2) fail-closed on disabled/unknown key,
(3) same-origin keyed-call allowlist bypass, (4) homepage stays keyless.
Regression coverage lives in `tests/test_embed_auth.py`.
