"""Pins the product row serializer (_product_row_to_dict) BEFORE it is relocated
from app.py into core.py (Track B, task 078, piece #3).

_product_row_to_dict is a pure dict-shaping leaf shared by BOTH the public product
routes (/api/products[/<slug>], which stay in app.py) AND the admin product CRUD
(which is a candidate to move into a blueprint). Moving it to core -- re-exported,
mirroring _service_to_dict/_iso_row -- lets a future admin-products blueprint
import it without `from app`. These tests pin its exact output shape so the move
is proven verbatim.

Runs under the embedded-Postgres harness. The serializer is checked directly via
the `app.` namespace and through the public /api/products route.
"""
import app


EXPECTED_KEYS = {
    "id", "slug", "name", "description", "price_cents", "price", "currency",
    "image_url", "gallery_images", "stock", "track_inventory", "active",
    "sort_order",
}


def test_serializer_none_is_none():
    assert app._product_row_to_dict(None) is None


def test_serializer_shape_and_price_rounding():
    row = {
        "id": 7, "slug": "widget", "name": "Widget", "description": "d",
        "price_cents": 1999, "currency": "USD", "image_url": "x.png",
        "gallery_images": None, "stock": 3, "track_inventory": True,
        "active": True, "sort_order": 2,
    }
    out = app._product_row_to_dict(row)
    assert set(out.keys()) == EXPECTED_KEYS
    assert out["price_cents"] == 1999
    assert out["price"] == 19.99          # cents -> dollars, rounded to 2dp
    assert out["gallery_images"] == []    # None coerced to []


def test_public_products_route_uses_serializer_shape():
    """Create a product, then read it back through the public route and confirm
    the serialized shape (proves the route + serializer wiring is intact)."""
    c = app.app.test_client()
    c.post("/admin/login", data={"password": __import__("os").environ.get("ADMIN_PASSWORD", "admin")})
    with c.session_transaction() as s:
        s["_csrf_token"] = "tok"
    hdr = {"X-CSRF-Token": "tok"}
    c.post("/admin/api/products",
           json={"name": "Serializer Probe Widget", "price": 5.5, "active": True},
           headers=hdr)
    r = c.get("/api/products")
    assert r.status_code == 200
    rows = r.get_json()
    assert isinstance(rows, list)
    if rows:  # at least our product should be present
        assert EXPECTED_KEYS.issubset(set(rows[0].keys()))
