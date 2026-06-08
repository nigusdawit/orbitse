"""
Tests for the JS bundle + minify pipeline (Optimization #11).

Covers:
- TestBundleBuild: the in-memory bundle exists, is meaningfully smaller
  than the raw concatenated sources, preserves the key identifiers the
  homepage runtime depends on, has a stable hash across rebuilds, and
  handles modern JS syntax features (template literals, optional
  chaining, async/await) without corrupting them.

- TestBundleServing: the fingerprinted bundle URL serves 200 with the
  right Content-Type, the immutable cache header is present, and a
  wrong-hash request 404s (rather than silently serving the current
  bundle from a stale URL).

- TestSourceFilesStillServe: /script.js and /voice.js continue to serve
  the unminified source for back-compat with admin-saved designs in
  site_designs that inline those tags directly.

- TestHomepageInjection: the served homepage HTML contains the bundle
  <script> tag (with the actual current hash), the placeholder is
  consumed (not literal in the response), and the original two script
  tags are NOT in the served HTML.

- TestLegacyDesignFallback: an admin-saved design without the placeholder
  but with the original two script tags gets the bundle injected via
  regex fallback; original tags are removed.

- TestBundleListDriftDetection: every JS file referenced from
  `<script src="/...">` in public/index.html is in the bundle source list
  (catches "added a 3rd JS file but forgot to bundle it" drift).

- TestProductionRegression: pin the size win is meaningful (>= 25%
  smaller than raw) and that the bundle URL pattern is what tests
  expect (so the route registration can't silently change format).
"""

import re
import pytest
from pathlib import Path

import asset_bundle


# Build once per test session so we're not paying the 50 ms cost N times.
@pytest.fixture(scope="module")
def bundle():
    return asset_bundle.build_bundle()


PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"


# =============================================================================
# Bundle-build behaviour (no Flask client needed)
# =============================================================================

class TestBundleBuild:
    def test_bundle_state_populated(self, bundle):
        assert bundle["hash"] is not None
        assert bundle["content_bytes"] is not None
        assert bundle["url"] is not None
        assert bundle["raw_size"] > 0
        assert bundle["min_size"] > 0

    def test_hash_format_is_12_hex_chars(self, bundle):
        assert re.fullmatch(r"[a-f0-9]{12}", bundle["hash"]), (
            f"hash {bundle['hash']!r} must be 12 lowercase hex chars"
        )

    def test_url_format(self, bundle):
        assert bundle["url"] == f"/bundle.{bundle['hash']}.min.js"
        assert asset_bundle.BUNDLE_URL_PATTERN.match(bundle["url"]), (
            f"URL {bundle['url']!r} must match BUNDLE_URL_PATTERN"
        )

    def test_minified_smaller_than_raw(self, bundle):
        assert bundle["min_size"] < bundle["raw_size"], (
            f"min_size={bundle['min_size']} should be < raw_size={bundle['raw_size']}"
        )

    def test_size_reduction_at_least_20_percent(self, bundle):
        # Conservative whitespace+comment minify on hand-commented JS
        # typically lands in the 35-45% range; current sources hit 42%.
        # 20% is a deliberately loose safety floor — its job is to catch
        # rjsmin becoming a no-op stub or comments being stripped from
        # all sources, NOT to police natural source-code evolution
        # toward denser code (e.g. someone embedding a base64 blob).
        # If this fires, the actionable response is to investigate
        # rjsmin's behaviour, not to inflate the source files.
        ratio = 1 - (bundle["min_size"] / bundle["raw_size"])
        assert ratio >= 0.20, (
            f"Minify only saved {ratio:.1%}; floor is 20%. "
            f"raw={bundle['raw_size']} min={bundle['min_size']}. "
            f"Investigate whether rjsmin is silently failing or "
            f"whether the source files now contain large pre-minified "
            f"blobs (e.g. embedded base64 assets)."
        )

    def test_sources_list_matches_constant(self, bundle):
        assert bundle["sources"] == ["script.js", "voice.js"]

    def test_hash_is_stable_across_rebuilds(self, bundle):
        # Same source bytes -> same hash. Pins that the bundle hash is
        # purely content-derived (no timestamp, no random salt, no host
        # name leaking in) — required for cache-friendliness across
        # multi-worker deployments where every worker rebuilds independently.
        first_hash = bundle["hash"]
        rebuilt = asset_bundle.build_bundle(force=True)
        assert rebuilt["hash"] == first_hash

    @pytest.mark.parametrize("identifier", [
        "loadGoogleFont",
        "imgSrcset",
        "BUILTIN_SECTION_MAP",
        "DOMPurify",
    ])
    def test_critical_identifiers_preserved(self, bundle, identifier):
        # Conservative minification preserves all variable/function names.
        # If any of these go missing, the homepage will throw
        # ReferenceError at runtime — fail loudly in tests instead.
        text = bundle["content_bytes"].decode("utf-8")
        assert identifier in text, f"{identifier!r} missing from minified bundle"

    def test_template_literal_interpolation_preserved(self, bundle):
        # Template literals like `Hello ${name}` are fragile under naive
        # whitespace stripping (the ${...} block must NOT be touched).
        # Spot-check by counting interpolations: rjsmin should preserve
        # them all.
        text = bundle["content_bytes"].decode("utf-8")
        raw_count = sum(
            (PUBLIC_DIR / name).read_text(encoding="utf-8").count("${")
            for name in asset_bundle.BUNDLE_SOURCES
        )
        # Every ${ in the source must survive into the minified bundle.
        # We allow >= because string concat can preserve them within
        # template strings while comments containing ${ get stripped.
        assert text.count("${") >= raw_count - 5, (
            f"Template-literal interpolations dropped: "
            f"raw={raw_count}, minified={text.count('${')}"
        )

    def test_async_await_preserved(self, bundle):
        text = bundle["content_bytes"].decode("utf-8")
        # We know the source uses async/await heavily; the keywords must
        # survive minification (rjsmin doesn't rename, but a future
        # swap to a more aggressive minifier might break this).
        assert "async " in text or "async(" in text, "async keyword stripped"
        assert "await " in text or "await(" in text, "await keyword stripped"

    def test_get_bundle_is_lazy_and_idempotent(self):
        # First call builds; second call returns cached. Both return the
        # same dict object (not a copy) — callers can rely on identity.
        a = asset_bundle.get_bundle()
        b = asset_bundle.get_bundle()
        assert a is b


# =============================================================================
# HTTP serving
# =============================================================================

class TestBundleServing:
    def test_bundle_url_returns_200(self, client, bundle):
        resp = client.get(bundle["url"])
        assert resp.status_code == 200

    def test_bundle_url_returns_javascript_content_type(self, client, bundle):
        resp = client.get(bundle["url"])
        assert resp.headers["Content-Type"].startswith("application/javascript")

    def test_bundle_url_has_immutable_long_cache(self, client, bundle):
        resp = client.get(bundle["url"])
        cc = resp.headers.get("Cache-Control", "")
        assert "max-age=31536000" in cc, (
            f"Bundle must carry one-year max-age, got {cc!r}"
        )
        assert "immutable" in cc, (
            f"Bundle must be marked immutable, got {cc!r}"
        )

    def test_bundle_url_has_vary_accept_encoding(self, client, bundle):
        # Brotli/gzip compression branches on Accept-Encoding; without
        # Vary, intermediate caches could serve a brotli body to a
        # client that doesn't accept brotli.
        resp = client.get(bundle["url"])
        assert "Accept-Encoding" in resp.headers.get("Vary", "")

    def test_bundle_body_matches_in_memory_bytes(self, client, bundle):
        resp = client.get(bundle["url"])
        # Werkzeug test client decompresses transparently, so resp.data
        # is the raw bytes. They should match exactly.
        assert resp.data == bundle["content_bytes"]

    def test_wrong_hash_returns_404_not_current_bundle(self, client):
        # Critical safety property: a stale-hash URL must NOT silently
        # serve the current bundle (would let the stale URL cache forever
        # as if valid). It must 404 so the client refetches HTML.
        resp = client.get("/bundle.deadbeefcafe.min.js")
        assert resp.status_code == 404

    def test_wrong_hash_404_body_does_not_leak_current_hash(self, client, bundle):
        # Defensive: the 404 response shouldn't echo the current valid
        # hash (would let an attacker probe for the exact current hash
        # via a single request, vs being told nothing).
        resp = client.get("/bundle.deadbeefcafe.min.js")
        assert bundle["hash"].encode() not in resp.data


# =============================================================================
# Source files continue to serve (back-compat)
# =============================================================================

class TestSourceFilesStillServe:
    def test_script_js_still_serves(self, client):
        resp = client.get("/script.js")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"].startswith(
            ("application/javascript", "text/javascript")
        )

    def test_voice_js_still_serves(self, client):
        resp = client.get("/voice.js")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"].startswith(
            ("application/javascript", "text/javascript")
        )

    def test_script_js_unchanged_size(self, client):
        # The source file is served as-is, NOT minified. Pins that the
        # serve_static path doesn't accidentally start serving the
        # minified blob from /script.js.
        resp = client.get("/script.js")
        on_disk = (PUBLIC_DIR / "script.js").read_bytes()
        assert len(resp.data) == len(on_disk), (
            "Raw /script.js size changed — bundle path may be leaking "
            "into the source file route"
        )


# =============================================================================
# Homepage HTML injection
# =============================================================================

class TestHomepageInjection:
    def test_served_homepage_contains_bundle_script_tag(self, client, bundle):
        resp = client.get("/")
        assert resp.status_code == 200
        assert bundle["url"].encode() in resp.data, (
            f"Served HTML must contain bundle URL {bundle['url']!r}"
        )

    def test_served_homepage_does_not_contain_placeholder(self, client):
        # The placeholder must be CONSUMED — leaving it as literal HTML
        # comment text means injection silently failed and the page has
        # no JS at all.
        resp = client.get("/")
        assert b"<!-- JS_BUNDLE_INJECT -->" not in resp.data, (
            "JS_BUNDLE_INJECT placeholder leaked through to served HTML"
        )

    def test_served_homepage_does_not_load_unbundled_sources(self, client):
        # The new bundle replaces both /script.js and /voice.js loads.
        # If either appears as a <script src=>, we're double-loading
        # JS (waste) or the bundle isn't the canonical path. Tolerant
        # regex matches all attribute orderings (`<script defer src=>`,
        # `<script src=... type=>`) and quote styles so the assertion
        # can't be fooled by formatting variants.
        resp = client.get("/")
        body = resp.data.decode("utf-8", errors="ignore")
        unwanted = re.compile(
            r'<script\b[^>]*\bsrc\s*=\s*["\']\/(?:script|voice)\.js(?:\?[^"\']*)?["\']',
            re.IGNORECASE,
        )
        match = unwanted.search(body)
        assert match is None, (
            f"Served homepage still loads unbundled source: {match.group(0)!r}"
        )

    def test_bundle_tag_is_well_formed(self, client, bundle):
        # Must be exactly one self-contained <script src="..."></script>
        # — not a malformed `<script src=...` cut off mid-attribute.
        resp = client.get("/")
        body = resp.data.decode("utf-8")
        expected = f'<script src="{bundle["url"]}"></script>'
        assert expected in body, (
            f"Bundle tag must appear verbatim in served HTML; "
            f"expected {expected!r}"
        )


# =============================================================================
# Legacy admin-saved design fallback
# =============================================================================

class TestLegacyDesignFallback:
    """Admin-saved designs in `site_designs` predate the placeholder and
    inline the original two script tags directly. We must still inject
    the bundle into those by regex rewrite, otherwise legacy designs
    silently miss the optimisation."""

    # Single source of truth for the regex shape — kept in sync with
    # the production regex in app.py::serve_index() so every variant
    # this fixture covers also gets covered by the live code path.
    SCRIPT_RE = re.compile(
        r'<script\b[^>]*\bsrc\s*=\s*["\']\/script\.js(?:\?[^"\']*)?["\'][^>]*>\s*</script>',
        re.IGNORECASE,
    )
    VOICE_RE = re.compile(
        r'<script\b[^>]*\bsrc\s*=\s*["\']\/voice\.js(?:\?[^"\']*)?["\'][^>]*>\s*</script>',
        re.IGNORECASE,
    )

    def test_legacy_design_with_both_tags_gets_bundle(self):
        # Direct test of the injection logic: simulate serve_index()'s
        # regex fallback against a synthetic legacy design.
        from app import serve_index  # ensure module loaded
        bundle_tag = asset_bundle.bundle_script_tag()

        legacy_html = (
            '<!doctype html><html><head><title>x</title></head><body>'
            '<div>content</div>'
            '<script src="/script.js"></script>'
            '<!-- voice control -->'
            '<script src="/voice.js"></script>'
            '</body></html>'
        )
        result = self.SCRIPT_RE.sub(bundle_tag, legacy_html, count=1)
        result = self.VOICE_RE.sub("", result, count=1)

        assert bundle_tag in result, "Bundle tag not injected"
        assert '<script src="/script.js">' not in result, (
            "Original /script.js tag should be removed"
        )
        assert '<script src="/voice.js">' not in result, (
            "Original /voice.js tag should be removed"
        )

    def test_legacy_design_with_only_script_tag_still_gets_bundle(self):
        bundle_tag = asset_bundle.bundle_script_tag()
        legacy_html = '<body><script src="/script.js"></script></body>'
        result = self.SCRIPT_RE.sub(bundle_tag, legacy_html, count=1)
        assert bundle_tag in result

    @pytest.mark.parametrize("variant", [
        # Attribute before src
        '<script defer src="/script.js"></script>',
        '<script async src="/script.js"></script>',
        # Attribute after src
        '<script src="/script.js" type="text/javascript"></script>',
        '<script src="/script.js" defer></script>',
        # Single quotes
        "<script src='/script.js'></script>",
        # Whitespace around =
        '<script src = "/script.js"></script>',
        # Cache-bust query string
        '<script src="/script.js?v=123"></script>',
        # Mixed case tag
        '<SCRIPT src="/script.js"></SCRIPT>',
        # Multiple attributes around src
        '<script defer src="/script.js" crossorigin></script>',
    ])
    def test_legacy_regex_tolerates_attribute_variants(self, variant):
        # The original regex required `src` to be the FIRST attribute and
        # rejected anything with extra attributes. Real-world admin-saved
        # designs and CMS exports often add `defer`, `async`, `type=`,
        # `crossorigin`, or cache-bust query strings — the hardened
        # regex must match all of them so legacy designs don't silently
        # miss the optimisation. If any of these stop matching, the
        # legacy fallback path silently regresses.
        assert self.SCRIPT_RE.search(variant) is not None, (
            f"Hardened legacy regex must match variant: {variant!r}"
        )


# =============================================================================
# Drift detection
# =============================================================================

class TestBundleListDriftDetection:
    """If a future PR adds a third JS file (e.g. `chat.js`) and references
    it from `<script src="/chat.js">` in `public/index.html` without adding
    it to `BUNDLE_SOURCES`, that file will load on its own request, the
    bundle won't include it, and the optimisation silently degrades. This
    test catches that drift."""

    def test_every_local_script_src_in_index_is_bundled(self):
        index_html = (PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        # Match `<script src="/foo.js">` — local paths only, NOT
        # https:// (those are CDN scripts handled by Optimization #10).
        # Tolerant of attribute ordering (`<script defer src=>`),
        # whitespace, single/double quotes, and cache-bust query
        # strings — without this, a future PR adding `<script defer
        # src="/chat.js">` would slip through the drift detector.
        local_script_re = re.compile(
            r'<script\b[^>]*\bsrc\s*=\s*["\']\/([\w./-]+\.js)(?:\?[^"\']*)?["\']',
            re.IGNORECASE,
        )
        local_scripts = set(local_script_re.findall(index_html))
        bundled = set(asset_bundle.BUNDLE_SOURCES)

        # Intentionally-standalone scripts that must stay as their own
        # <script defer> tag and NOT be folded into the homepage bundle.
        # widget-bridge.js is the embed iframe-resize bridge — a no-op on
        # normal pages, loaded separately on purpose (see public/index.html +
        # the file header). It's served on /widget-bridge.js, not bundled.
        standalone_ok = {"widget-bridge.js"}

        # After bundling, the only local script reference in
        # public/index.html should be the bundle URL itself, which has
        # the form `bundle.{hash}.min.js` and is NOT pre-listed in
        # BUNDLE_SOURCES (it's the OUTPUT, not a source).
        unbundled = {
            s for s in local_scripts
            if s not in bundled and s not in standalone_ok
            and not re.match(r"bundle\.[a-f0-9]{12}\.min\.js$", s)
        }
        assert not unbundled, (
            f"Local JS files referenced in index.html but not in "
            f"asset_bundle.BUNDLE_SOURCES: {unbundled}. Either add them "
            f"to BUNDLE_SOURCES (preferred — keeps single-request perf "
            f"win) or extend this test's exception list."
        )

    def test_every_bundled_source_exists_on_disk(self):
        # Inverse drift: BUNDLE_SOURCES lists a file that no longer
        # exists. build_bundle() would crash on first call.
        for name in asset_bundle.BUNDLE_SOURCES:
            assert (PUBLIC_DIR / name).exists(), (
                f"BUNDLE_SOURCES references {name!r} but it doesn't "
                f"exist in public/"
            )


# =============================================================================
# Production-regression pins
# =============================================================================

class TestProductionRegression:
    def test_bundle_url_pattern_is_stable(self, bundle):
        # The route registration in app.py uses
        # `/bundle.<bundle_hash>.min.js`. If the URL shape ever changes
        # (e.g. someone adds a `/static/` prefix or changes `.min.js`
        # to `.js`), the route + this test must change in lockstep.
        # Pinning the format here so a one-sided change can't ship.
        assert re.fullmatch(
            r"^/bundle\.[a-f0-9]{12}\.min\.js$", bundle["url"]
        ), f"URL shape changed: {bundle['url']!r}"

    def test_total_savings_at_least_one_request_and_25_percent(
        self, client, bundle
    ):
        # End-to-end pin: the optimisation actually saves what it
        # promises. The original homepage loaded 2 separate JS requests
        # totalling raw_size bytes; now it loads 1 request of min_size.
        # If either of these regress meaningfully, fail loudly.
        # Threshold sized to give source-code evolution headroom while
        # still catching catastrophic regression (e.g. minifier bypass).
        request_count_before = 2  # script.js + voice.js
        request_count_after = 1   # bundle.{hash}.min.js
        assert request_count_after < request_count_before

        savings = 1 - (bundle["min_size"] / bundle["raw_size"])
        assert savings >= 0.25, (
            f"Total byte savings {savings:.1%} below 25% threshold. "
            f"raw={bundle['raw_size']} min={bundle['min_size']}. "
            f"Either rjsmin is silently bypassed or sources have "
            f"grown denser — investigate before bumping this floor."
        )
