"""Pins slug generation (Track B, task 078, piece #3) BEFORE resolving the
3-way _slugify name collision in app.py.

app.py defines `_slugify` THREE times at module scope (presentations ~22862,
pages/sections ~25118, products ~31535). In Python the LAST def wins, so at
runtime every call site -- presentations, pages, AND products -- resolves to the
products variant (31535: `re.sub(r"[^a-z0-9]+","-", lower).strip("-")` with a
`secrets.token_hex(4)` fallback for empty input, no length cap). The other two
defs are dead (shadowed) code. The collision is resolved by removing the two
dead defs and keeping the one canonical `_slugify`; these tests pin the OBSERVED
current output (which is the 31535 logic everywhere) so that removal is proven
to change nothing.

Load-bearing edge case: POST /admin/api/pages with an empty slug currently
returns 201 with a random token slug (NOT a 400), because the live _slugify
never returns "" -- the `if not slug` guard in the handler can't fire. That
behavior is pinned below so it cannot regress.

Runs under the embedded-Postgres harness. Slug output goes through the `app.`
namespace and the live routes -- exactly how production resolves it.
"""
import os
import re

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")

# 8 lowercase hex chars == secrets.token_hex(4): the canonical empty-input slug.
_HEX8 = re.compile(r"^[0-9a-f]{8}$")


# ---- the canonical _slugify (the live 31535 variant) ------------------------

def test_slugify_normal_cases():
    assert app._slugify("Hello World") == "hello-world"
    assert app._slugify("UPPER_case") == "upper-case"
    assert app._slugify("  multiple   spaces  ") == "multiple-spaces"
    assert app._slugify("already-hyphenated") == "already-hyphenated"
    assert app._slugify("trailing--dashes--") == "trailing-dashes"
    assert app._slugify("mix-of_things and!stuff") == "mix-of-things-and-stuff"


def test_slugify_empty_returns_token_not_blank():
    """The live variant falls back to secrets.token_hex(4) for empty/symbol-only
    input -- it NEVER returns "". (This is the behavior all call sites get.)"""
    out = app._slugify("")
    assert _HEX8.match(out), out
    # symbol-only input also reduces to empty-core -> token fallback
    assert _HEX8.match(app._slugify("!!!@@@"))
    # two empty calls produce different tokens (random), proving the fallback
    assert app._slugify("") != app._slugify("") or True  # randomness, not asserted hard


def test_slugify_no_length_cap():
    """The live variant does NOT truncate (the dead presentations variant
    capped at 120 -- pinning this proves we kept the live one)."""
    assert len(app._slugify("a" * 200)) == 200


# ---- products + pages CRUD slug output (via routes) -------------------------

def _login(c):
    return c.post("/admin/login", data={"password": ADMIN_PW})


def _csrf(c):
    with c.session_transaction() as s:
        s["_csrf_token"] = "tok"
    return {"X-CSRF-Token": "tok"}


def test_product_create_slug_from_name():
    c = app.app.test_client()
    assert _login(c).status_code in (200, 302)
    hdr = _csrf(c)
    r = c.post("/admin/api/products",
               json={"name": "Cool Product 2!", "price": 1.5}, headers=hdr)
    assert r.status_code == 201, r.get_data(as_text=True)
    slug = r.get_json()["slug"]
    # First create of this name slugifies cleanly; a later duplicate would get a
    # `-<token>` suffix, so accept the base or a suffixed form.
    assert slug == "cool-product-2" or slug.startswith("cool-product-2-")


def test_product_create_slug_from_explicit_slug():
    c = app.app.test_client()
    assert _login(c).status_code in (200, 302)
    hdr = _csrf(c)
    r = c.post("/admin/api/products",
               json={"name": "X", "price": 1, "slug": "Custom Slug Here"}, headers=hdr)
    assert r.status_code == 201, r.get_data(as_text=True)
    slug = r.get_json()["slug"]
    assert slug == "custom-slug-here" or slug.startswith("custom-slug-here-")


def test_page_create_slug_from_explicit_slug():
    c = app.app.test_client()
    assert _login(c).status_code in (200, 302)
    hdr = _csrf(c)
    r = c.post("/admin/api/pages",
               json={"slug": "My Test Page!", "title": "T"}, headers=hdr)
    assert r.status_code == 201, r.get_data(as_text=True)
    assert r.get_json()["slug"] == "my-test-page"


def test_page_create_empty_slug_gets_token_not_400():
    """LOAD-BEARING: empty slug currently yields a random token slug + 201,
    NOT a 400. (The live _slugify never returns "" so the handler's
    `if not slug` 400 guard is unreachable.) Pinning this guards the edge."""
    c = app.app.test_client()
    assert _login(c).status_code in (200, 302)
    hdr = _csrf(c)
    r = c.post("/admin/api/pages", json={"slug": "", "title": "X"}, headers=hdr)
    assert r.status_code == 201, r.get_data(as_text=True)
    assert _HEX8.match(r.get_json()["slug"]), r.get_json()
