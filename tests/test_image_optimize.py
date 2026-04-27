"""
Tests for image_optimize — Optimization #4 (April 2026).

Three layers:

1. Pure helpers (`is_variant_filename`, `srcset_for`) — fast, no I/O.
2. Generation (`generate_webp_variants`, `ensure_variant_on_demand`) —
   round-trips real bytes through `storage.get_storage()` (the local
   backend during tests, writing under `uploads/__t4__<hex>...`).
3. Flask integration (`/uploads/<base>-800.webp`) — verifies the
   serve_upload route actually calls the on-demand generator and
   returns the WebP bytes when a viewer requests a variant for a
   legacy upload that wasn't pre-warmed.

Every test cleans up its own files in a try/finally so a failed run
doesn't leave orphans in `uploads/` (they'd show up in the admin
Media Library).
"""

import io
import secrets

import pytest
from PIL import Image

import image_optimize
import storage


# ---- Fixtures and helpers --------------------------------------------------

def _unique_stem() -> str:
    """Tests share the dev `uploads/` directory with the running app, so
    we prefix every test artifact with `__t4__` AND a per-test random
    nonce. This makes the files trivial to spot in the Media Library
    and impossible to collide with a real upload."""
    return f"__t4__{secrets.token_hex(6)}"


def _make_jpeg_bytes(width: int = 2000, height: int = 1000,
                     color: tuple[int, int, int] = (200, 80, 60)) -> bytes:
    """Generate an in-memory JPEG of the given size."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _make_png_rgba_bytes(width: int = 1500, height: int = 800) -> bytes:
    """Generate an in-memory PNG with an alpha channel."""
    img = Image.new("RGBA", (width, height), color=(50, 120, 200, 128))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _make_animated_gif_bytes() -> bytes:
    """Two-frame animated GIF — the kind we want to skip."""
    frames = [
        Image.new("P", (200, 200), color=i) for i in range(2)
    ]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=200, loop=0)
    return buf.getvalue()


@pytest.fixture
def store():
    return storage.get_storage()


@pytest.fixture
def cleanup_files(store):
    """Track filenames written during a test and delete them on exit
    regardless of pass/fail. Variants are derived from the stem so we
    don't need the test to register each one explicitly."""
    written: list[str] = []
    stems: list[str] = []

    def _track_stem(stem: str):
        stems.append(stem)

    def _track_file(name: str):
        written.append(name)

    yield (_track_file, _track_stem)

    for name in written:
        try:
            store.delete(name)
        except Exception:
            pass
    for stem in stems:
        for w in (400, 800, 1600):
            try:
                store.delete(f"{stem}-{w}.webp")
            except Exception:
                pass


# ---- Layer 1: pure helpers (no I/O) ----------------------------------------

class TestIsVariantFilename:
    @pytest.mark.parametrize("name", [
        "abc-400.webp", "abc-800.webp", "abc-1600.webp",
        "long_underscore_name-800.webp",
        "abc.def-800.webp",  # dotted stem (rare but legal)
        "abc-123-400.webp",  # multi-dash stem
    ])
    def test_valid_variant_names_match(self, name):
        assert image_optimize.is_variant_filename(name) is True

    @pytest.mark.parametrize("name", [
        "abc.jpg",                  # source, not variant
        "abc-200.webp",             # not in our breakpoint list
        "abc-401.webp",             # not in our breakpoint list
        "abc-800.jpg",              # not webp
        "abc-800",                  # no extension
        "abc.webp",                 # no width
        "voice/abc-800.webp",       # subpath excluded
        "contracts/x-400.webp",     # subpath excluded
        "abc-abc.webp",             # width isn't numeric
        "",                         # empty
    ])
    def test_non_variant_names_dont_match(self, name):
        assert image_optimize.is_variant_filename(name) is False


class TestSrcsetFor:
    @pytest.mark.parametrize("url,stem", [
        ("/uploads/abc.jpg", "abc"),
        ("/uploads/abc.jpeg", "abc"),
        ("/uploads/abc.png", "abc"),
        ("/uploads/ABC.JPG", "ABC"),  # uppercase ext still works
        ("/uploads/my.photo.png", "my.photo"),  # dotted stem preserved
    ])
    def test_eligible_urls_emit_three_widths(self, url, stem):
        result = image_optimize.srcset_for(url)
        # Should contain all three widths in order.
        assert f"/uploads/{stem}-400.webp 400w" in result
        assert f"/uploads/{stem}-800.webp 800w" in result
        assert f"/uploads/{stem}-1600.webp 1600w" in result
        # The order should be 400, 800, 1600 (browsers don't care, but
        # consistency makes the output diffable).
        assert result.index("400w") < result.index("800w") < result.index("1600w")

    @pytest.mark.parametrize("url", [
        "",
        None,
        "/uploads/abc.gif",                  # animation, skipped
        "/uploads/abc.webp",                 # already optimal
        "/uploads/abc.svg",                  # vector
        "/uploads/abc",                      # no extension
        "/uploads/voice/abc.jpg",            # subpath
        "/uploads/contracts/x.png",          # subpath
        "https://cdn.example.com/abc.jpg",   # absolute external
        "abc.jpg",                            # not under /uploads/
        "/static/abc.jpg",                    # under /static/
    ])
    def test_ineligible_urls_yield_empty_string(self, url):
        assert image_optimize.srcset_for(url) == ""


# ---- Layer 2: generation (round-trips through storage) ---------------------

class TestGenerateWebpVariants:
    def test_jpeg_yields_three_variants_smaller_than_source(self, store, cleanup_files):
        track_file, track_stem = cleanup_files
        stem = _unique_stem()
        original = f"{stem}.jpg"
        track_stem(stem)
        track_file(original)
        original_bytes = _make_jpeg_bytes(width=2000, height=1000)
        store.write_bytes(original, original_bytes, content_type="image/jpeg")

        variants = image_optimize.generate_webp_variants(original)

        assert variants == [f"{stem}-400.webp", f"{stem}-800.webp", f"{stem}-1600.webp"]
        for v in variants:
            assert store.exists(v)
            # WebP variant of any width should be smaller than the
            # original JPEG, given our quality=82 + method=6 settings
            # and a smooth 2000x1000 source.
            assert (store.size(v) or 0) < len(original_bytes)

    def test_png_with_alpha_preserved_in_webp(self, store, cleanup_files):
        track_file, track_stem = cleanup_files
        stem = _unique_stem()
        original = f"{stem}.png"
        track_stem(stem)
        track_file(original)
        store.write_bytes(original, _make_png_rgba_bytes(width=1500),
                          content_type="image/png")

        variants = image_optimize.generate_webp_variants(original)
        assert len(variants) >= 2  # 400, 800 — 1600 skipped (>= source width)

        # Decode the 800w variant and confirm it still has alpha.
        webp_bytes = store.read_bytes(variants[0])
        with Image.open(io.BytesIO(webp_bytes)) as decoded:
            assert decoded.mode == "RGBA", \
                "alpha channel was stripped during PNG -> WebP conversion"

    def test_skips_widths_at_or_above_source_width(self, store, cleanup_files):
        track_file, track_stem = cleanup_files
        stem = _unique_stem()
        original = f"{stem}.jpg"
        track_stem(stem)
        track_file(original)
        # 200px wide — smaller than ALL three breakpoints (400/800/1600),
        # so generate_webp_variants should produce zero variants.
        store.write_bytes(original, _make_jpeg_bytes(width=200, height=100),
                          content_type="image/jpeg")
        variants = image_optimize.generate_webp_variants(original)
        assert variants == []

    def test_partial_skip_when_source_smaller_than_largest_width(
            self, store, cleanup_files):
        """A 1000px-wide source should produce 400 + 800 variants but
        not 1600 (which would be an upscale)."""
        track_file, track_stem = cleanup_files
        stem = _unique_stem()
        original = f"{stem}.jpg"
        track_stem(stem)
        track_file(original)
        store.write_bytes(original, _make_jpeg_bytes(width=1000, height=500),
                          content_type="image/jpeg")
        variants = image_optimize.generate_webp_variants(original)
        assert variants == [f"{stem}-400.webp", f"{stem}-800.webp"]
        assert not store.exists(f"{stem}-1600.webp")

    def test_pre_warm_includes_exact_breakpoint_widths(
            self, store, cleanup_files):
        """A source whose width EXACTLY equals a breakpoint (e.g.
        800x400) gets a same-width WebP variant on the pre-warm path,
        not skipped. The skip rule is `width > source.width` (strict),
        not `>=`. Without this, the most common Web-resized image
        dimensions (800px, 1600px) would pay first-hit encode latency
        on every viewer; with it, the WebP-vs-original size win is
        captured at upload time. Smaller breakpoints (400) still
        generate as a real downscale."""
        track_file, track_stem = cleanup_files
        stem = _unique_stem()
        original = f"{stem}.jpg"
        track_stem(stem)
        track_file(original)
        # 800px wide — exactly matches the 800w breakpoint, smaller
        # than 1600 (skipped), larger than 400 (downscaled).
        store.write_bytes(original, _make_jpeg_bytes(width=800, height=400),
                          content_type="image/jpeg")
        variants = image_optimize.generate_webp_variants(original)
        assert variants == [f"{stem}-400.webp", f"{stem}-800.webp"]
        # 800w variant exists and is encoded at native 800px.
        with Image.open(io.BytesIO(store.read_bytes(f"{stem}-800.webp"))) as decoded:
            assert decoded.format == "WEBP"
            assert decoded.width == 800
        # 1600w (true upscale) still skipped.
        assert not store.exists(f"{stem}-1600.webp")

    def test_skipped_for_gif(self, store, cleanup_files):
        """Animated GIFs would lose animation if converted to WebP, and
        static GIFs are too small to bother. We skip the entire format."""
        track_file, track_stem = cleanup_files
        stem = _unique_stem()
        original = f"{stem}.gif"
        track_stem(stem)
        track_file(original)
        store.write_bytes(original, _make_animated_gif_bytes(),
                          content_type="image/gif")
        assert image_optimize.generate_webp_variants(original) == []

    def test_skipped_for_webp(self, store, cleanup_files):
        """WebP source files are already optimal — skip."""
        track_file, track_stem = cleanup_files
        stem = _unique_stem()
        original = f"{stem}.webp"
        track_stem(stem)
        track_file(original)
        # Make a real WebP so the file isn't gibberish.
        img = Image.new("RGB", (1500, 800), color=(0, 200, 100))
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=80)
        store.write_bytes(original, buf.getvalue(), content_type="image/webp")
        assert image_optimize.generate_webp_variants(original) == []

    def test_no_raise_on_corrupt_bytes(self, store, cleanup_files):
        track_file, _ = cleanup_files
        stem = _unique_stem()
        original = f"{stem}.jpg"
        track_file(original)
        store.write_bytes(original, b"this is not an image", content_type="image/jpeg")
        # Must not raise; just skip silently.
        assert image_optimize.generate_webp_variants(original) == []

    def test_no_raise_on_missing_source(self):
        """If somehow the original isn't there at variant-gen time
        (deleted between upload write and post-write hook), we log and
        return empty — the caller must not see an exception."""
        result = image_optimize.generate_webp_variants(f"{_unique_stem()}.jpg")
        assert result == []

    def test_no_raise_on_non_image_extension(self):
        """Defence-in-depth: even though admin_upload_image filters by
        ALLOWED_EXTENSIONS, calling with a video extension should be a
        clean no-op rather than a crash."""
        assert image_optimize.generate_webp_variants("foo.mp4") == []
        assert image_optimize.generate_webp_variants("foo.pdf") == []


class TestEnsureVariantOnDemand:
    def test_generates_when_source_exists_and_variant_missing(
            self, store, cleanup_files):
        track_file, track_stem = cleanup_files
        stem = _unique_stem()
        original = f"{stem}.jpg"
        variant = f"{stem}-800.webp"
        track_stem(stem)
        track_file(original)
        store.write_bytes(original, _make_jpeg_bytes(width=2000, height=1000),
                          content_type="image/jpeg")

        assert image_optimize.ensure_variant_on_demand(variant) is True
        assert store.exists(variant)
        # Variants 400 and 1600 should NOT have been generated — the
        # on-demand path is single-variant, not three.
        assert not store.exists(f"{stem}-400.webp")
        assert not store.exists(f"{stem}-1600.webp")

    def test_idempotent_when_variant_already_exists(self, store, cleanup_files):
        track_file, track_stem = cleanup_files
        stem = _unique_stem()
        original = f"{stem}.jpg"
        variant = f"{stem}-800.webp"
        track_stem(stem)
        track_file(original)
        store.write_bytes(original, _make_jpeg_bytes(width=2000),
                          content_type="image/jpeg")

        # First call generates it.
        assert image_optimize.ensure_variant_on_demand(variant) is True
        first_size = store.size(variant)

        # Second call must NOT regenerate (it'd waste CPU). Returns
        # False to signal "no work done", and the bytes are unchanged.
        assert image_optimize.ensure_variant_on_demand(variant) is False
        assert store.size(variant) == first_size

    def test_returns_false_when_no_source_image(self):
        # Random stem → no source on disk → can't generate.
        variant = f"{_unique_stem()}-800.webp"
        assert image_optimize.ensure_variant_on_demand(variant) is False

    def test_returns_false_for_non_variant_filename(self, store, cleanup_files):
        """The serve_upload route ALSO calls is_variant_filename first,
        but the function itself should be defensive: a bare /uploads/
        request that happens to end in .webp but isn't a variant
        pattern (e.g. user uploaded `vacation.webp`) must NOT trigger
        generation that could overwrite their file."""
        track_file, _ = cleanup_files
        original = f"vacation_{secrets.token_hex(4)}.webp"
        track_file(original)
        # Write a real WebP so it'd be a valid target if we mis-detected.
        img = Image.new("RGB", (200, 200), color=(0, 0, 255))
        buf = io.BytesIO()
        img.save(buf, "WEBP")
        store.write_bytes(original, buf.getvalue(), content_type="image/webp")
        original_bytes = store.read_bytes(original)

        assert image_optimize.ensure_variant_on_demand(original) is False
        # File untouched.
        assert store.read_bytes(original) == original_bytes

    def test_returns_false_for_subpath(self):
        """voice/ and contracts/ never get variants, even if they
        happen to end in `-800.webp`."""
        assert image_optimize.ensure_variant_on_demand("voice/foo-800.webp") is False
        assert image_optimize.ensure_variant_on_demand("contracts/x-400.webp") is False

    def test_returns_false_for_invalid_width(self):
        """Width 999 isn't in our breakpoint list; the route handler
        won't even call us, but defence-in-depth."""
        assert image_optimize.ensure_variant_on_demand("abc-999.webp") is False

    def test_caps_to_source_width_when_requested_larger(
            self, store, cleanup_files):
        """For a 300-px-wide source, requesting an 800w or 1600w
        variant must still produce a valid WebP — clamped to source
        width — instead of 404'ing. The frontend `imgAttrs` helper
        emits all three variant URLs without knowing source dimensions,
        so a 404 here would cost every page load with a small image
        one wasted round-trip before the browser falls back to `src=`.
        Pre-warm path (`generate_webp_variants`) still skips upscales
        — this cap-to-source behavior is on-demand only."""
        track_file, track_stem = cleanup_files
        stem = _unique_stem()
        original = f"{stem}.jpg"
        track_stem(stem)
        track_file(original)
        # 300x200 source — smaller than 400, 800, AND 1600 breakpoints.
        store.write_bytes(original, _make_jpeg_bytes(width=300, height=200),
                          content_type="image/jpeg")

        for requested_w in (400, 800, 1600):
            variant = f"{stem}-{requested_w}.webp"
            assert image_optimize.ensure_variant_on_demand(variant) is True, \
                f"on-demand path should generate {requested_w}w variant from 300px source"
            assert store.exists(variant)
            # Bytes are valid WebP at SOURCE width (300), not 800/1600.
            with Image.open(io.BytesIO(store.read_bytes(variant))) as decoded:
                assert decoded.format == "WEBP"
                assert decoded.width == 300, \
                    f"variant {variant} should be capped to 300px source, got {decoded.width}"

    def test_pre_warm_still_skips_upscales(self, store, cleanup_files):
        """Sanity check that the pre-warm path's no-upscale rule
        survived the on-demand cap-to-source change. A 300px source
        through `generate_webp_variants` must still produce zero
        variants — we don't want disk filling up with three
        near-identical WebPs of every thumbnail."""
        track_file, track_stem = cleanup_files
        stem = _unique_stem()
        original = f"{stem}.jpg"
        track_stem(stem)
        track_file(original)
        store.write_bytes(original, _make_jpeg_bytes(width=300, height=200),
                          content_type="image/jpeg")
        assert image_optimize.generate_webp_variants(original) == []
        # And explicitly: nothing was written to disk.
        for w in (400, 800, 1600):
            assert not store.exists(f"{stem}-{w}.webp")


# ---- Layer 2.5: frontend / backend parity drift guard ---------------------

class TestFrontendBackendParity:
    """The JS `imgSrcset` helper in `public/script.js` and the Python
    `srcset_for` in `image_optimize.py` MUST make IDENTICAL eligibility
    decisions — same widths emitted, same source extensions accepted,
    same top-level-only check. If they drift, half the page's <img>
    tags emit srcset URLs the backend won't generate (broken images
    after a couple of hops), or the backend pre-generates variants
    nothing on the frontend ever requests (wasted disk on every
    upload).

    These tests parse the JS source directly and assert the constants
    match the Python ones. They're not a substitute for a shared
    config file, but they're a cheap canary that catches the most
    common silent drift."""

    @pytest.fixture(scope="class")
    def js_source(self):
        with open("public/script.js", encoding="utf-8") as f:
            return f.read()

    def test_widths_match_between_js_and_python(self, js_source):
        import re as _re
        m = _re.search(r"IMG_RESPONSIVE_WIDTHS\s*=\s*\[([^\]]+)\]", js_source)
        assert m, "IMG_RESPONSIVE_WIDTHS constant not found in public/script.js"
        js_widths = tuple(int(x.strip()) for x in m.group(1).split(",") if x.strip())
        assert js_widths == image_optimize._RESPONSIVE_WIDTHS, (
            f"width drift! JS has {js_widths} but Python has "
            f"{image_optimize._RESPONSIVE_WIDTHS}. If you changed one, "
            f"change the other (and update `is_variant_filename` if "
            f"the breakpoint set is what changed)."
        )

    def test_extensions_match_between_js_and_python(self, js_source):
        import re as _re
        m = _re.search(
            r"IMG_VARIANT_SOURCE_EXTS\s*=\s*new\s+Set\s*\(\s*\[([^\]]+)\]\s*\)",
            js_source,
        )
        assert m, "IMG_VARIANT_SOURCE_EXTS constant not found in public/script.js"
        js_exts = frozenset(
            x.strip().strip("'\"").lower()
            for x in m.group(1).split(",") if x.strip()
        )
        assert js_exts == image_optimize._VARIANT_SOURCE_EXTENSIONS, (
            f"extension drift! JS accepts {sorted(js_exts)} but Python "
            f"accepts {sorted(image_optimize._VARIANT_SOURCE_EXTENSIONS)}. "
            f"Both sides must agree on which uploads get variants."
        )

    def test_top_level_only_check_present_in_js(self, js_source):
        """Both sides exclude `/uploads/voice/...` and
        `/uploads/contracts/...` from variant generation — voice cache
        is mp3/wav (not images), contracts are PDFs. The Python check
        is `if "/" in filename: return False` inside `is_variant_filename`
        and srcset_for. The JS check is the equivalent
        `filename.indexOf('/') !== -1` inside `imgSrcset`. We're not
        executing the JS — just checking the guard exists in the
        right function so a refactor doesn't accidentally remove it."""
        # Locate the imgSrcset function body and check the guard is present.
        assert "function imgSrcset(url)" in js_source
        # The guard line — match a fairly tight pattern so a typo
        # like `=== -1` (which would invert the check) trips this.
        assert "filename.indexOf('/') !== -1" in js_source, (
            "imgSrcset() missing the top-level-only guard "
            "(`filename.indexOf('/') !== -1`); subdirectory uploads "
            "would now incorrectly emit srcset URLs that 404."
        )


# ---- Layer 3: end-to-end through Flask -------------------------------------

class TestServeUploadOnDemand:
    """The serve_upload route should transparently generate a variant
    on first request when the variant doesn't exist but a source does.
    This is what makes legacy uploads (the 595 pre-Opt-4 files) work
    with the frontend `imgSrcset()` helper without any backfill step."""

    def test_first_request_generates_variant_then_serves_it(
            self, client, store, cleanup_files):
        track_file, track_stem = cleanup_files
        stem = _unique_stem()
        original = f"{stem}.jpg"
        variant = f"{stem}-800.webp"
        track_stem(stem)
        track_file(original)
        store.write_bytes(original, _make_jpeg_bytes(width=2000, height=1000),
                          content_type="image/jpeg")
        # Variant doesn't exist yet — this simulates a legacy upload.
        assert not store.exists(variant)

        resp = client.get(f"/uploads/{variant}")
        assert resp.status_code == 200
        # The response body MUST be a valid WebP (sniff via Pillow,
        # which gives us format + dimensions in one decode).
        with Image.open(io.BytesIO(resp.data)) as decoded:
            assert decoded.format == "WEBP"
            assert decoded.width == 800

        # Variant was persisted as a side effect — second request can
        # serve directly without paying the resize cost again.
        assert store.exists(variant)

    def test_variant_request_with_no_source_returns_404(self, client):
        """If there's no matching source image, the on-demand path is
        a no-op and storage.serve() returns the standard 404. We don't
        500 on an unknown-variant request."""
        # Random stem with no source anywhere.
        variant = f"__t4__nosource_{secrets.token_hex(4)}-800.webp"
        resp = client.get(f"/uploads/{variant}")
        assert resp.status_code == 404
