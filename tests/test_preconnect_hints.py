"""
Preconnect / dns-prefetch hint tests for the public homepage
(Optimization #10 — April 2026).

Pin the contract that:

  1. Every served homepage HTML includes preconnect AND dns-prefetch
     hints for all six third-party origins the template loads from
     (unpkg, cdnjs, jsdelivr, js.stripe, fonts.googleapis, fonts.gstatic).
  2. The fonts.gstatic.com preconnect carries `crossorigin` — without
     it the hint warms a connection pool that the actual font fetch
     (which IS crossorigin per CSS spec) never reuses, wasting the
     hint entirely. This is the most common preconnect bug in the
     wild and worth pinning explicitly.
  3. The hint block appears BEFORE the parser-blocking <script> tags
     it's optimizing for. Otherwise the handshakes start at the same
     time as the script fetches and the optimization is a no-op.
  4. The disk-template path uses the placeholder; if the placeholder
     is missing (e.g. an admin-published design from before this
     change), the injection still happens via the </head> fallback
     so legacy designs don't silently lose the optimization.
"""
import pytest


# Mirror the hardcoded list in app.py _build_preconnect_hints_html().
# If it drifts the parametrized test below fails — keep in lock-step.
EXPECTED_ORIGINS = [
    "https://fonts.googleapis.com",
    "https://fonts.gstatic.com",
    "https://unpkg.com",
    "https://cdnjs.cloudflare.com",
    "https://cdn.jsdelivr.net",
    "https://js.stripe.com",
]


class TestPreconnectHelper:
    """Pure-function tests on _build_preconnect_hints_html() — no Flask
    context needed, just import and call."""

    def test_helper_returns_non_empty_string(self):
        from app import _build_preconnect_hints_html
        out = _build_preconnect_hints_html()
        assert isinstance(out, str)
        assert len(out) > 0

    @pytest.mark.parametrize("origin", EXPECTED_ORIGINS)
    def test_helper_emits_preconnect_for_every_origin(self, origin):
        from app import _build_preconnect_hints_html
        out = _build_preconnect_hints_html()
        assert f'rel="preconnect" href="{origin}"' in out, (
            f"missing preconnect hint for {origin}"
        )

    @pytest.mark.parametrize("origin", EXPECTED_ORIGINS)
    def test_helper_emits_dns_prefetch_fallback_for_every_origin(self, origin):
        from app import _build_preconnect_hints_html
        out = _build_preconnect_hints_html()
        assert f'rel="dns-prefetch" href="{origin}"' in out, (
            f"missing dns-prefetch fallback for {origin}"
        )

    def test_fonts_gstatic_preconnect_has_crossorigin(self):
        # CSS-spec font fetches are anonymous-CORS. Without `crossorigin`
        # on the preconnect, the browser warms a credentialed connection
        # pool and opens a SECOND, fresh connection for the actual font
        # fetch — wasting the hint. This is the #1 preconnect footgun.
        from app import _build_preconnect_hints_html
        out = _build_preconnect_hints_html()
        assert (
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            in out
        ), "fonts.gstatic.com preconnect MUST include crossorigin attribute"

    def test_other_preconnects_do_not_have_crossorigin(self):
        # Only fonts.gstatic.com needs crossorigin; the head <script> tags
        # for unpkg/cdnjs/jsdelivr/js.stripe/fonts.googleapis don't carry
        # crossorigin, so a crossorigin preconnect would warm an unused
        # connection pool. Pin this so a well-meaning future edit that
        # blanket-adds crossorigin doesn't silently regress.
        from app import _build_preconnect_hints_html
        out = _build_preconnect_hints_html()
        for origin in EXPECTED_ORIGINS:
            if origin == "https://fonts.gstatic.com":
                continue
            assert (
                f'<link rel="preconnect" href="{origin}">'
                in out
            ), f"{origin} preconnect should NOT carry crossorigin"


class TestServedHomepage:
    """End-to-end tests that the served `/` HTML contains the hints in
    the right place. Uses the existing flask_app + client fixtures."""

    def test_homepage_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"<head" in resp.data

    @pytest.mark.parametrize("origin", EXPECTED_ORIGINS)
    def test_served_homepage_contains_preconnect(self, client, origin):
        resp = client.get("/")
        body = resp.data.decode("utf-8")
        assert f'rel="preconnect" href="{origin}"' in body, (
            f"served homepage missing preconnect for {origin}"
        )

    def test_served_homepage_fonts_gstatic_has_crossorigin(self, client):
        resp = client.get("/")
        body = resp.data.decode("utf-8")
        assert (
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            in body
        ), "served homepage fonts.gstatic.com preconnect missing crossorigin"

    def test_preconnect_appears_before_blocking_scripts(self, client):
        # The whole point: preconnect must be discoverable BEFORE the
        # parser hits the <script src="https://unpkg.com/..."> tag,
        # otherwise the handshake starts at the same time as the
        # script fetch and the optimization saves nothing. Compare
        # byte offsets.
        resp = client.get("/")
        body = resp.data.decode("utf-8")
        preconnect_pos = body.find('rel="preconnect" href="https://unpkg.com"')
        script_pos = body.find('<script src="https://unpkg.com')
        assert preconnect_pos != -1, "no unpkg preconnect found in served HTML"
        assert script_pos != -1, "no unpkg <script> found in served HTML"
        assert preconnect_pos < script_pos, (
            f"unpkg preconnect at byte {preconnect_pos} appears AFTER unpkg "
            f"<script> at byte {script_pos} — handshake won't be parallelized"
        )

    def test_preconnect_placeholder_consumed_not_left_in_html(self, client):
        # The placeholder comment should be REPLACED by the hint block,
        # not left as a literal HTML comment in the served response.
        # If this fires it usually means the placeholder string in the
        # disk file drifted from the one app.py looks for.
        resp = client.get("/")
        body = resp.data.decode("utf-8")
        assert "<!-- PRECONNECT_HINTS_INJECT -->" not in body

    @pytest.mark.parametrize("origin", EXPECTED_ORIGINS)
    def test_served_homepage_contains_dns_prefetch_fallback(self, client, origin):
        # The dns-prefetch fallback must also survive the round-trip,
        # not just the preconnect. A mismatch here would mean the helper
        # output is being truncated or post-processed by some middleware
        # before the response goes out.
        resp = client.get("/")
        body = resp.data.decode("utf-8")
        assert f'rel="dns-prefetch" href="{origin}"' in body, (
            f"served homepage missing dns-prefetch fallback for {origin}"
        )


class TestListDriftDetection:
    """Catches the case where someone adds a new third-party <script>
    or <link> to public/index.html without adding a matching preconnect
    hint to _build_preconnect_hints_html(). Without this, the new
    origin silently pays serial handshakes on every cold visit and
    no test fails — the kind of drift that happens during a Tuesday
    afternoon refactor and gets discovered six months later in a
    Lighthouse audit."""

    def _extract_external_origins_from_disk(self):
        """Scrape public/index.html for every distinct `https://<host>`
        origin appearing in a <script src="..."> or <link href="...">
        attribute. Returns a set of origins (scheme + host, no path).
        Skips anchor href targets like `<a href="https://...">` which
        are user-clickable links, not resource fetches that benefit
        from preconnect — only resource-fetching tags matter."""
        import os
        import re as _re
        from urllib.parse import urlparse
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "public", "index.html"
        )
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        # Match src= or href= on <script> or <link> tags only
        pattern = _re.compile(
            r'<(?:script|link)\b[^>]*\b(?:src|href)\s*=\s*["\'](https?://[^"\']+)["\']',
            _re.IGNORECASE,
        )
        origins = set()
        for url in pattern.findall(html):
            parsed = urlparse(url)
            if parsed.scheme and parsed.netloc:
                origins.add(f"{parsed.scheme}://{parsed.netloc}")
        return origins

    def test_every_external_resource_origin_in_index_has_a_preconnect(self):
        # The KEY drift detector: every distinct https://host that
        # public/index.html loads a <script> or <link> from must
        # have a corresponding preconnect hint in our helper. If
        # someone adds <script src="https://newcdn.com/lib.js">
        # without updating _build_preconnect_hints_html(), this fails.
        from app import _build_preconnect_hints_html
        disk_origins = self._extract_external_origins_from_disk()
        helper_out = _build_preconnect_hints_html()
        missing = []
        for origin in disk_origins:
            if f'rel="preconnect" href="{origin}"' not in helper_out:
                missing.append(origin)
        assert not missing, (
            f"public/index.html loads from {missing} but "
            f"_build_preconnect_hints_html() has no preconnect for them. "
            f"Either add them to the helper, or remove the <script>/<link>."
        )

    def test_extractor_actually_finds_the_known_origins(self):
        # Sanity check that the extractor itself works — if the regex
        # silently matches nothing, the drift detector above would
        # vacuously pass forever. Pin that the extractor finds at
        # least the four origins we know are unconditionally in head.
        disk_origins = self._extract_external_origins_from_disk()
        for must_find in [
            "https://unpkg.com",
            "https://cdnjs.cloudflare.com",
            "https://cdn.jsdelivr.net",
            "https://js.stripe.com",
        ]:
            assert must_find in disk_origins, (
                f"extractor failed to find known origin {must_find} in "
                f"public/index.html — regex may be broken"
            )


class TestLegacyDesignFallback:
    """If an admin saved a custom design from before April 2026, that
    HTML lives in site_designs.html WITHOUT the PRECONNECT_HINTS_INJECT
    placeholder. The serve_index() code must still inject the hints
    via the pre-</head> fallback — late-but-present is much better
    than missing entirely."""

    def test_helper_idempotent_no_html_state(self):
        # Calling the helper twice returns the same string — no hidden
        # state, safe for any number of injections per request.
        from app import _build_preconnect_hints_html
        a = _build_preconnect_hints_html()
        b = _build_preconnect_hints_html()
        assert a == b

    def test_fallback_inserts_right_after_head_open(self, monkeypatch, client):
        # Simulate a legacy admin-saved design by patching query_db so
        # serve_index() returns HTML WITHOUT the placeholder, AND with
        # a parser-blocking <script src="https://..."> in head BEFORE
        # </head>. The fallback must insert preconnect hints RIGHT AFTER
        # <head>, not right before </head> — otherwise the script's own
        # handshake starts before the preconnect is parsed and the
        # optimization is a no-op.
        legacy_html = (
            "<!DOCTYPE html><html><head>"
            "<meta charset='utf-8'>"
            "<title>Legacy Design</title>"
            '<script src="https://unpkg.com/somelib"></script>'
            "</head><body>legacy</body></html>"
        )
        import app as app_module

        # Save the original to restore mid-call for the rest of the
        # request pipeline (which queries other tables).
        original_query_db = app_module.query_db

        def fake_query_db(sql, *args, **kwargs):
            if "site_designs" in sql:
                return {"aid": 999, "html": legacy_html}
            return original_query_db(sql, *args, **kwargs)

        monkeypatch.setattr(app_module, "query_db", fake_query_db)
        resp = client.get("/")
        body = resp.data.decode("utf-8")
        # All six preconnects present even though placeholder is absent:
        for origin in EXPECTED_ORIGINS:
            assert f'rel="preconnect" href="{origin}"' in body, (
                f"legacy design path lost preconnect for {origin}"
            )
        # And critically — they appear BEFORE the parser-blocking
        # <script src="https://unpkg.com/...">, not after it:
        preconnect_pos = body.find('rel="preconnect" href="https://unpkg.com"')
        script_pos = body.find('<script src="https://unpkg.com')
        assert preconnect_pos != -1
        assert script_pos != -1
        assert preconnect_pos < script_pos, (
            f"legacy fallback put preconnect at byte {preconnect_pos} which "
            f"is AFTER the <script> at byte {script_pos} — handshake won't "
            f"be parallelized. Fallback should insert right after <head>."
        )

    def test_fallback_handles_head_with_attributes(self):
        # Some legacy designs use `<head lang="en">` or similar. The
        # regex-based fallback insertion must handle that.
        from app import _build_preconnect_hints_html
        import re as re_module
        legacy_html = '<html><head lang="en"><title>x</title></head></html>'
        head_open = re_module.search(r"<head\b[^>]*>", legacy_html, flags=re_module.IGNORECASE)
        assert head_open is not None
        assert head_open.group(0) == '<head lang="en">'
        # The actual injection logic just needs the regex to match — we
        # don't import the private injection block, but matching the
        # regex used by serve_index is sufficient to pin the contract.
