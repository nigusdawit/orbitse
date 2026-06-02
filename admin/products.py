"""admin/products.py - admin product CRUD + Stripe-sync hooks, as a Flask blueprint.

Part of the app.py de-monolith (Track B / task 078, piece #3), mirroring
admin/commerce.py. These five /admin/api/products* routes are the store-admin
product manager: list, create, update, delete, and a lightweight stock PATCH.

The two Stripe-sync hooks moved here with the routes (_maybe_sync_product_to_stripe
/ _maybe_archive_product_in_stripe). They import stripe_settings / stripe_sync
LAZILY (call-time) precisely because those modules `import app`; doing the import
inside the function avoids the circular-import the module-level form would create,
and works identically from a blueprint. Both swallow all exceptions (a broken
Stripe layer must never block local product CRUD) and return a JSON-safe status
dict the route attaches under "stripe_sync" / "stripe_archive".

The shared leaves these routes use - _slugify and _product_row_to_dict - live in
core (Track B / task 078, piece #3), so this blueprint imports them from core
cleanly, never `from app` (which would be circular). secrets + json are stdlib.

URLs keep their absolute /admin/api/products* paths, so the route table is
unchanged - only the Flask endpoint name gains a "products." prefix (admin JS
calls these by URL, not url_for). CSRF / feature-flag enforcement runs in app.py's
global before_request hooks, which apply to blueprint routes too, so the products
feature gate + CSRF still apply unchanged.

Registered in app.py via app.register_blueprint(products_bp), after cost_bp.
"""
import json
import secrets

from flask import Blueprint, request, jsonify

from core import (
    query_db,
    admin_required,
    _slugify,
    _product_row_to_dict,
)

products_bp = Blueprint("products", __name__)


# ---------------------------------------------------------------------------
# Stripe sync hooks for the admin product CRUD routes below.
#
# Two thin wrappers so the route bodies stay readable. Both:
#  - import stripe_sync / stripe_settings LAZILY (avoids any circular-import
#    risk with stripe_settings.py / stripe_sync.py which both `import app`)
#  - swallow ALL exceptions (a broken Stripe layer must NEVER block local
#    product CRUD — that's an explicit design rule for this feature)
#  - return a JSON-safe dict so the frontend can show a toast on failure
# ---------------------------------------------------------------------------

def _maybe_sync_product_to_stripe(local_product_id):
    """Called from POST/PUT product routes. Returns a status dict that
    the route attaches to its response under "stripe_sync". Returns
    `{"skipped": "autosync_off"}` when the toggle is off so the frontend
    can stay silent in that case."""
    try:
        import stripe_settings as _ss
        if not _ss.get_settings().get("autosync_products"):
            return {"skipped": "autosync_off"}
        import stripe_sync as _ssync
        return _ssync.sync_product(local_product_id)
    except Exception as e:
        print(f"[stripe_sync hook] sync failed for product {local_product_id}: {e}")
        return {"ok": False, "error": str(e)}


def _maybe_archive_product_in_stripe(local_product_id):
    """Called from DELETE product route. Always runs (regardless of the
    autosync toggle) IFF a mapping exists for either mode — otherwise
    the Stripe Product would be left active in the catalog after the
    local row is gone. archive_product itself is a no-op when there's
    no mapping, so this is cheap."""
    try:
        import stripe_sync as _ssync
        return _ssync.archive_product(local_product_id)
    except Exception as e:
        print(f"[stripe_sync hook] archive failed for product {local_product_id}: {e}")
        return {"ok": False, "error": str(e)}


@products_bp.route("/admin/api/products", methods=["GET"])
@admin_required
def admin_products_list():
    rows = query_db(
        "SELECT * FROM products ORDER BY sort_order ASC, id ASC"
    ) or []
    return jsonify([_product_row_to_dict(r) for r in rows])


@products_bp.route("/admin/api/products", methods=["POST"])
@admin_required
def admin_products_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400
    slug = _slugify(data.get("slug") or name)
    # Ensure unique slug.
    existing = query_db("SELECT id FROM products WHERE slug = %s", (slug,), fetchone=True)
    if existing:
        slug = f"{slug}-{secrets.token_hex(2)}"

    price_cents = int(round(float(data.get("price") or 0) * 100))
    if "price_cents" in data:
        price_cents = int(data["price_cents"])

    row = query_db(
        """
        INSERT INTO products
          (slug, name, description, price_cents, currency, image_url,
           gallery_images, stock, track_inventory, active, sort_order)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            slug,
            name,
            (data.get("description") or "").strip(),
            price_cents,
            (data.get("currency") or "USD").upper(),
            (data.get("image_url") or "").strip(),
            json.dumps(data.get("gallery_images") or []),
            int(data.get("stock") or 0),
            bool(data.get("track_inventory", True)),
            bool(data.get("active", True)),
            int(data.get("sort_order") or 0),
        ),
        fetchone=True,
    
    )
    out = _product_row_to_dict(row)
    out["stripe_sync"] = _maybe_sync_product_to_stripe(row["id"])
    return jsonify(out), 201


@products_bp.route("/admin/api/products/<int:pid>", methods=["PUT"])
@admin_required
def admin_products_update(pid):
    data = request.get_json(silent=True) or {}
    existing = query_db("SELECT * FROM products WHERE id = %s", (pid,), fetchone=True)
    if not existing:
        return jsonify({"error": "Not found"}), 404

    name = (data.get("name") or existing["name"]).strip()
    slug = (data.get("slug") or existing["slug"]).strip() or existing["slug"]
    price_cents = existing["price_cents"]
    if "price" in data:
        price_cents = int(round(float(data["price"]) * 100))
    if "price_cents" in data:
        price_cents = int(data["price_cents"])

    row = query_db(
        """
        UPDATE products SET
          slug=%s, name=%s, description=%s, price_cents=%s, currency=%s,
          image_url=%s, gallery_images=%s, stock=%s, track_inventory=%s,
          active=%s, sort_order=%s
        WHERE id = %s
        RETURNING *
        """,
        (
            slug, name,
            data.get("description", existing["description"]),
            price_cents,
            (data.get("currency") or existing["currency"]).upper(),
            data.get("image_url", existing["image_url"]),
            json.dumps(data.get("gallery_images", existing["gallery_images"] or [])),
            int(data.get("stock", existing["stock"])),
            bool(data.get("track_inventory", existing["track_inventory"])),
            bool(data.get("active", existing["active"])),
            int(data.get("sort_order", existing["sort_order"])),
            pid,
        ),
        fetchone=True,
    
    )
    out = _product_row_to_dict(row)
    out["stripe_sync"] = _maybe_sync_product_to_stripe(pid)
    return jsonify(out)


@products_bp.route("/admin/api/products/<int:pid>", methods=["DELETE"])
@admin_required
def admin_products_delete(pid):
    # Archive in Stripe BEFORE the local DELETE — once the row is gone
    # the ON DELETE CASCADE on stripe_product_sync would wipe out the
    # mappings and we'd lose the Stripe Product IDs we need to archive.
    archive_result = _maybe_archive_product_in_stripe(pid)
    query_db("DELETE FROM products WHERE id = %s", (pid,))
    return jsonify({"success": True, "stripe_archive": archive_result})


@products_bp.route("/admin/api/products/<int:pid>/stock", methods=["PATCH"])
@admin_required
def admin_products_stock(pid):
    data = request.get_json(silent=True) or {}
    if "stock" not in data:
        return jsonify({"error": "stock required"}), 400
    row = query_db(
        "UPDATE products SET stock = %s WHERE id = %s RETURNING *",
        (int(data["stock"]), pid),
        fetchone=True,
    
    )
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(_product_row_to_dict(row))
