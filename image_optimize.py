"""
Image optimization for /uploads — Optimization #4 (April 2026).

Two complementary jobs:

1. **Upload-time preheat**: when an admin uploads a JPEG / PNG, we
   immediately generate three responsive WebP variants alongside the
   original — `<base>-400.webp`, `<base>-800.webp`, `<base>-1600.webp`.
   The original is preserved unchanged so existing /uploads/<file> URLs
   in the database keep working and admin re-edit / re-export still has
   the source bytes.

2. **On-demand backfill**: when a request comes in for a variant URL
   that doesn't exist (e.g. one of the 595 pre-Opt-4 files), the
   `serve_upload` route calls `ensure_variant_on_demand()` which finds
   any matching source image (`<base>.jpg`, `<base>.jpeg`, `<base>.png`)
   and synthesizes the requested WebP variant on the fly. The first
   request pays the resize cost (~150-500 ms depending on source size);
   every subsequent request hits the cached variant directly. This
   means we can flip on responsive `srcset` for the entire image
   library WITHOUT a separate one-shot migration script.

WHY WEBP, NOT AVIF: WebP is built into Pillow 12.x with no extra
dependencies. AVIF needs `pillow-avif-plugin` and AVIF encode is
3-10x slower than WebP for ~10% extra savings — a worse trade for
on-demand generation where a viewer is blocking on the response.
A future Optimization could add AVIF as a `<picture>`-with-`<source>`
upgrade for browsers that prefer it; we'd keep WebP as the broad
fallback.

WHY THESE THREE WIDTHS:
  * 400  — phones at 1× DPR (most ~360-414 px wide), tablet thumbnails
  * 800  — phones at 2× DPR, tablet 1×, half-width desktop cards
  * 1600 — desktop hero / full-bleed (also 2× of 800 for retina)

Anything > 1600 we don't generate — almost no uploaded photo is bigger
than that anyway, and shipping 4K backgrounds to a 4K monitor is a
problem we don't have today (and one trivially solved later by adding
3200 to `_RESPONSIVE_WIDTHS`).

WHY ONLY top-level /uploads/ files get variants: subdirectories under
/uploads/ are reserved by Tier 9 for non-image content — `voice/`
holds TTS MP3s, `contracts/` holds signed PDFs. Treating those as
image candidates would just generate decode-error noise.
"""
from __future__ import annotations

import io
import logging
import re
from typing import Iterable, Optional

from PIL import Image, UnidentifiedImageError

import storage

log = logging.getLogger(__name__)


_RESPONSIVE_WIDTHS: tuple[int, ...] = (400, 800, 1600)

# Image extensions for which we'll generate WebP variants. Excludes:
#   gif  — animation would be lost in a single-frame WebP; static GIFs
#          are also rare and tiny enough that the savings don't matter
#   webp — already in the target format
#   svg  — vector; Pillow doesn't decode it and resampling is meaningless
_VARIANT_SOURCE_EXTENSIONS: frozenset[str] = frozenset({"jpg", "jpeg", "png"})

# WebP encode settings. quality=82 is visually indistinguishable from
# 90 on photographic content (~25% smaller); method=6 is the slowest /
# highest-compression setting (~5% smaller than method=4 default) — we
# pay the upload-time cost once and serve thousands of times after.
_WEBP_QUALITY = 82
_WEBP_METHOD = 6

# Variant filename pattern: `<stem>-<width>.webp`. The `<width>` is one
# of `_RESPONSIVE_WIDTHS`. Used by the on-demand route handler to parse
# an incoming request URL back into (stem, width). Greedy `.+` is fine
# because the trailing `-\d+\.webp` is unambiguous.
_VARIANT_RE = re.compile(r"^(.+)-(\d+)\.webp$")


def _stem(filename: str) -> str:
    """Strip the file extension. `abc.jpg` -> `abc`, `my.photo.png` -> `my.photo`."""
    if "." in filename:
        return filename.rsplit(".", 1)[0]
    return filename


def _variant_key(original_filename: str, width: int) -> str:
    """For `abc.jpg` + width 800, returns `abc-800.webp`."""
    return f"{_stem(original_filename)}-{width}.webp"


def _open_and_normalize(raw: bytes) -> Optional[Image.Image]:
    """Decode `raw` with Pillow and return a Pillow image ready for
    resize+encode, or None if it can't be decoded.

    Mode handling:
      * RGBA → kept (WebP supports alpha natively)
      * everything else (palette, CMYK, L grayscale, etc.) → RGB

    Returns None on truncated / corrupt / unsupported data — never
    raises, since this function is called from request handlers and an
    upload should not fail because Pillow couldn't decode an oddball
    file. The caller logs and continues with just the original bytes.
    """
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()  # force decode now so we catch truncated streams here
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return None
    if img.mode == "RGBA":
        return img
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _encode_webp(img: Image.Image, width: int, *,
                 cap_to_source: bool = False) -> Optional[bytes]:
    """Resize `img` to `width` pixels (preserving aspect ratio) and
    return the WebP-encoded bytes. Returns None on any encode error
    (extremely rare in practice — Pillow raises on disk-full / OOM).

    When `cap_to_source=False` (the pre-warm path), refuse to UPSCALE:
    if `width > img.width`, return None and let the caller skip this
    variant. This keeps disk usage tight for sub-1600px sources — no
    point storing three near-identical WebPs of a 300px thumbnail.
    Note: `width == img.width` is allowed (exact-breakpoint case) so
    the WebP-vs-original size win is captured for sources that happen
    to be exactly 400 / 800 / 1600 wide; that match avoids paying the
    first-hit encode cost on the on-demand path for the most common
    Web-resized image dimensions.

    When `cap_to_source=True` (the on-demand path), silently clamp the
    target down to `img.width` instead of skipping. The viewer asked
    for a specific variant URL (the frontend `imgAttrs` helper emitted
    it without knowing source dimensions); if we 404, the browser pays
    a round-trip to discover the fallback, AND that 404 won't be
    cached by every CDN configuration. Producing a valid WebP at
    source-width costs ~1-2 KB of disk and zero round-trips on the
    viewer's hot path. Strict improvement.
    """
    target_width = min(width, img.width) if cap_to_source else width
    if target_width > img.width and not cap_to_source:
        return None
    try:
        if target_width >= img.width:
            # Cap-to-source case: encode at native size, no resize step.
            resized = img
        else:
            ratio = target_width / img.width
            new_size = (target_width, max(1, int(round(img.height * ratio))))
            resized = img.resize(new_size, Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, "WEBP", quality=_WEBP_QUALITY, method=_WEBP_METHOD)
        return buf.getvalue()
    except Exception:
        log.warning("image_optimize: webp encode failed at width=%d", width, exc_info=True)
        return None


def is_variant_filename(filename: str) -> bool:
    """True iff `filename` matches the `<stem>-<width>.webp` variant
    naming convention with a width that's one of our breakpoints. Used
    by `serve_upload` to decide whether to attempt on-demand
    generation."""
    if "/" in filename:
        # Variants only live at the root of /uploads/. Subdirectory
        # files (voice/, contracts/) are explicitly out of scope.
        return False
    m = _VARIANT_RE.match(filename)
    if not m:
        return False
    try:
        return int(m.group(2)) in _RESPONSIVE_WIDTHS
    except ValueError:
        return False


def _find_source_for_variant(stem: str) -> Optional[str]:
    """Given a variant stem like `abc123`, find the matching source
    image filename — `abc123.jpg`, `abc123.jpeg`, or `abc123.png` —
    by checking the storage backend in that order. Returns the first
    match or None.

    Order matches the conventional preference: JPEG sources are most
    common (compressed photos), then PNG (screenshots / graphics with
    text). We don't try `.webp` because the variant URL is itself .webp
    and converting WebP-to-WebP would just rewrite the bytes for no
    gain.
    """
    store = storage.get_storage()
    for ext in ("jpg", "jpeg", "png"):
        candidate = f"{stem}.{ext}"
        if store.exists(candidate):
            return candidate
    return None


# -------------------------------------------------------------------- API


def generate_webp_variants(
    original_filename: str,
    *,
    widths: Iterable[int] = _RESPONSIVE_WIDTHS,
) -> list[str]:
    """Pre-generate WebP variants for an image just uploaded to storage.

    Reads the original bytes, decodes once, resizes + encodes each
    width, and writes each variant via the same storage backend
    (`local` or `s3`). Returns the list of variant filenames that were
    successfully written.

    NEVER raises. Variant generation is best-effort; the upload itself
    has already succeeded by the time this is called, so any failure
    here is logged and swallowed — the user gets the original file
    back and the on-demand path will still work for variants on the
    next request.

    Skipped silently when:
      * `original_filename` extension is not one of jpg/jpeg/png
      * the original bytes can't be decoded by Pillow (corrupt /
        truncated / animated GIF / something exotic)
      * a particular target width is > the source width (no upscaling;
        width == source width is allowed and produces a same-size
        WebP that's still smaller than the original JPEG/PNG)
    """
    ext = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else ""
    if ext not in _VARIANT_SOURCE_EXTENSIONS:
        return []

    store = storage.get_storage()
    raw = store.read_bytes(original_filename)
    if raw is None:
        log.warning("image_optimize: source %s not found at variant-gen time", original_filename)
        return []

    img = _open_and_normalize(raw)
    if img is None:
        log.info("image_optimize: %s isn't decodable, skipping variants", original_filename)
        return []

    generated: list[str] = []
    for w in widths:
        variant_name = _variant_key(original_filename, w)
        webp_bytes = _encode_webp(img, w)
        if webp_bytes is None:
            continue
        try:
            store.write_bytes(variant_name, webp_bytes, content_type="image/webp")
            generated.append(variant_name)
        except Exception:
            log.warning("image_optimize: failed to write %s", variant_name, exc_info=True)
            continue
    return generated


def ensure_variant_on_demand(filename: str) -> bool:
    """If `filename` matches the variant pattern AND the variant
    doesn't already exist AND a matching source image is present,
    generate the single requested variant and write it to storage.
    Returns True iff a variant was actually generated by this call.

    This is the entry point called from the `serve_upload` route — it
    lets us transparently serve responsive WebP for legacy files
    uploaded before Opt #4 without a one-shot backfill.

    Idempotent: a no-op if the variant already exists. Safe to call
    concurrently — two parallel requests for the same missing variant
    will both regenerate, but it's last-write-wins and both produce
    functionally equivalent WebP for the same source bytes. (We avoid
    the stronger "byte-identical" claim across runtimes because
    libwebp encoder output can drift across Pillow / libwebp builds
    even with the same quality + method settings.)
    """
    if not is_variant_filename(filename):
        return False
    store = storage.get_storage()
    if store.exists(filename):
        return False

    m = _VARIANT_RE.match(filename)
    if not m:  # belt-and-braces; is_variant_filename already checked
        return False
    stem, width_str = m.group(1), m.group(2)
    try:
        width = int(width_str)
    except ValueError:
        return False

    source_filename = _find_source_for_variant(stem)
    if source_filename is None:
        return False

    raw = store.read_bytes(source_filename)
    if raw is None:
        return False
    img = _open_and_normalize(raw)
    if img is None:
        return False
    # cap_to_source=True: a viewer's frontend already emitted this
    # variant URL without knowing the source dimensions. If we 404 on
    # a small source, the browser pays a wasted round-trip before
    # falling back to `src=`. Encoding at source-width instead costs
    # ~1-2 KB of disk and zero round-trips. See `_encode_webp` docstring.
    webp_bytes = _encode_webp(img, width, cap_to_source=True)
    if webp_bytes is None:
        return False
    try:
        store.write_bytes(filename, webp_bytes, content_type="image/webp")
        return True
    except Exception:
        log.warning("image_optimize: on-demand write failed for %s", filename, exc_info=True)
        return False


def srcset_for(public_url: str,
               widths: Iterable[int] = _RESPONSIVE_WIDTHS,
               base_url: Optional[str] = None) -> str:
    """Build a `srcset` attribute value for an image's public URL.

    `/uploads/abc123.jpg` ->
      `/uploads/abc123-400.webp 400w,
       /uploads/abc123-800.webp 800w,
       /uploads/abc123-1600.webp 1600w`

    Returns an empty string when the URL doesn't refer to a top-level
    /uploads/ image of a supported source extension. The frontend
    helper `imgSrcset()` in script.js mirrors this logic so the same
    decision is made regardless of which side of the wire constructs
    the markup.

    The caller renders the original URL as the `<img src=...>` so a
    browser that doesn't pick any srcset candidate (or a srcset entry
    that fails to load — no variant generated, weird mime, etc.) still
    gets the original.

    Optimization #5: when `base_url` is provided (or `UPLOADS_PUBLIC_BASE_URL`
    env var is set, picked up automatically when base_url is None), variant
    URLs are emitted as `<base>/uploads/<stem>-<w>.webp` so visitors fetch
    them straight from the CDN instead of paying an origin-redirect round-
    trip. Pass `base_url=""` explicitly to force the relative form even
    when the env var is set (used by tests to compare both shapes).
    """
    if not public_url or not isinstance(public_url, str):
        return ""
    if not public_url.startswith("/uploads/"):
        return ""
    filename = public_url[len("/uploads/"):]
    if "/" in filename:
        return ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _VARIANT_SOURCE_EXTENSIONS:
        return ""
    stem = _stem(filename)
    if base_url is None:
        import os as _os
        base_url = (_os.environ.get("UPLOADS_PUBLIC_BASE_URL") or "").rstrip("/")
    else:
        base_url = (base_url or "").rstrip("/")
    prefix = f"{base_url}/uploads" if base_url else "/uploads"
    return ", ".join(f"{prefix}/{stem}-{w}.webp {w}w" for w in widths)
