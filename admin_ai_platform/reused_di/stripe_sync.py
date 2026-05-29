"""
admin_ai_platform.reused_di.stripe_sync
=======================================

Mirror local ``products`` rows into Stripe Products + Prices (relocated +
DI-refactored from the monolith's ``stripe_sync.py``).

The mapping lives in ``stripe_product_sync`` keyed by ``(local_product_id, mode)``
so test and live keep independent catalogs. All three operations are
exception-safe — a Stripe failure is recorded into the mapping row's
``last_error`` and returned in the result dict; it never raises out, so a Stripe
outage can't break local product CRUD.

- ``sync_product(local_id)`` — idempotent create/update. Price changes create a
  new Price + flip the old inactive (Stripe forbids editing unit_amount in place).
- ``archive_product(local_id)`` — flips Stripe Product active=False across both
  modes that have a mapping. Call from DELETE *before* the row is removed.
- ``backfill_all()`` — sync every active product; returns counts + an error sample.

**Package change vs the monolith original:** ``import app as _app`` is replaced by
DB helpers injected via :func:`configure`; ``stripe_client``/``stripe_settings``
are imported from the package; Sentry is optional.
"""
import json
from datetime import datetime, timezone

try:
    import sentry_sdk
except Exception:  # pragma: no cover
    sentry_sdk = None

from ..reused import stripe_client
from . import stripe_settings

# Injected by create_app() via configure().
_query_db = None
_execute_db = None


def configure(*, query_db, execute_db):
    """Bind the package DB helpers. Called once from create_app()."""
    global _query_db, _execute_db
    _query_db = query_db
    _execute_db = execute_db


def _capture(e):
    if sentry_sdk is not None:
        try:
            sentry_sdk.capture_exception(e)
        except Exception:
            pass


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _read_product(local_id):
    return _query_db(
        "SELECT id, slug, name, description, price_cents, currency, image_url, "
        "       gallery_images, active FROM products WHERE id = %s",
        (int(local_id),), fetchone=True)


def _read_mapping(local_id, mode):
    return _query_db(
        "SELECT id, stripe_product_id, stripe_price_id, synced_price_cents, "
        "       synced_currency, last_synced_at FROM stripe_product_sync "
        "WHERE local_product_id = %s AND mode = %s",
        (int(local_id), mode), fetchone=True)


def _read_all_mappings(local_id):
    return _query_db(
        "SELECT mode, stripe_product_id FROM stripe_product_sync "
        "WHERE local_product_id = %s", (int(local_id),)) or []


def _upsert_mapping(local_id, mode, *, stripe_product_id="", stripe_price_id="",
                    price_cents=None, currency="", error=""):
    """Insert/update the mapping. Stamps last_attempt_at always; last_synced_at
    only on success (empty error)."""
    last_synced_insert = "NOW()" if not error else "NULL"
    last_synced_update = ("EXCLUDED.last_synced_at" if not error
                          else "stripe_product_sync.last_synced_at")
    _execute_db(
        f"""
        INSERT INTO stripe_product_sync
            (local_product_id, mode, stripe_product_id, stripe_price_id,
             synced_price_cents, synced_currency, last_synced_at,
             last_attempt_at, last_error)
        VALUES
            (%s, %s, %s, %s, %s, %s, {last_synced_insert}, NOW(), %s)
        ON CONFLICT (local_product_id, mode) DO UPDATE SET
            stripe_product_id = COALESCE(NULLIF(EXCLUDED.stripe_product_id, ''),
                                         stripe_product_sync.stripe_product_id),
            stripe_price_id   = COALESCE(NULLIF(EXCLUDED.stripe_price_id, ''),
                                         stripe_product_sync.stripe_price_id),
            synced_price_cents = COALESCE(EXCLUDED.synced_price_cents,
                                          stripe_product_sync.synced_price_cents),
            synced_currency   = COALESCE(NULLIF(EXCLUDED.synced_currency, ''),
                                         stripe_product_sync.synced_currency),
            last_synced_at    = {last_synced_update},
            last_attempt_at   = EXCLUDED.last_attempt_at,
            last_error        = EXCLUDED.last_error
        """,
        (int(local_id), mode, stripe_product_id, stripe_price_id,
         price_cents, currency, (error or "")[:1000]))


def _gallery_to_image_list(product):
    """Up to 8 de-duplicated image URLs from image_url + gallery_images."""
    out = []
    main = (product.get("image_url") or "").strip()
    if main:
        out.append(main)
    gallery_raw = product.get("gallery_images") or []
    if isinstance(gallery_raw, str):
        try:
            gallery_raw = json.loads(gallery_raw)
        except Exception:
            gallery_raw = []
    if isinstance(gallery_raw, list):
        for u in gallery_raw:
            if isinstance(u, str) and u.strip() and u.strip() not in out:
                out.append(u.strip())
            if len(out) >= 8:
                break
    return out[:8]


def _normalize_currency(currency):
    return (currency or "usd").strip().lower() or "usd"


def sync_product(local_id):
    """Idempotent mirror of local product → Stripe. Returns a result dict; never
    raises. A Stripe failure is captured into last_error AND the dict."""
    mode = stripe_settings.get_mode()
    out = {"ok": False, "mode": mode, "stripe_product_id": None,
           "stripe_price_id": None, "error": None, "action": None}
    try:
        product = _read_product(local_id)
    except Exception as e:
        out["error"] = f"local read failed: {e}"
        return out
    if not product:
        out["error"] = f"local product {local_id} not found"
        return out

    try:
        stripe = stripe_client.get_stripe()
    except RuntimeError as e:
        try:
            _upsert_mapping(local_id, mode, error=str(e))
        except Exception:
            pass
        out["error"] = str(e)
        return out

    try:
        existing = _read_mapping(local_id, mode)
    except Exception as e:
        existing = None
        out["error"] = f"mapping read failed: {e}"

    name = (product.get("name") or "").strip() or product.get("slug") or "Product"
    description = (product.get("description") or "").strip() or None
    images = _gallery_to_image_list(product)
    price_cents = int(product.get("price_cents") or 0)
    currency = _normalize_currency(product.get("currency"))
    is_active = bool(product.get("active"))
    metadata = {"local_product_id": str(product["id"]), "local_slug": product.get("slug") or ""}

    try:
        if not existing or not existing.get("stripe_product_id"):
            sp = stripe.Product.create(name=name, description=description,
                                       images=images or None, active=is_active,
                                       metadata=metadata)
            sprice = stripe.Price.create(product=sp["id"], unit_amount=price_cents,
                                         currency=currency, metadata=metadata)
            try:
                stripe.Product.modify(sp["id"], default_price=sprice["id"])
            except Exception:
                pass
            _upsert_mapping(local_id, mode, stripe_product_id=sp["id"],
                            stripe_price_id=sprice["id"], price_cents=price_cents,
                            currency=currency)
            out.update({"ok": True, "stripe_product_id": sp["id"],
                        "stripe_price_id": sprice["id"], "action": "created"})
            return out

        sp_id = existing["stripe_product_id"]
        sprice_id_old = existing.get("stripe_price_id") or ""
        prev_cents = existing.get("synced_price_cents")
        prev_currency = existing.get("synced_currency") or ""

        stripe.Product.modify(sp_id, name=name, description=description,
                              images=images or None, active=is_active, metadata=metadata)

        price_changed = (prev_cents != price_cents
                         or (prev_currency.lower() != currency.lower()))
        if price_changed or not sprice_id_old:
            new_price = stripe.Price.create(product=sp_id, unit_amount=price_cents,
                                            currency=currency, metadata=metadata)
            try:
                stripe.Product.modify(sp_id, default_price=new_price["id"])
            except Exception:
                pass
            if sprice_id_old:
                try:
                    stripe.Price.modify(sprice_id_old, active=False)
                except Exception:
                    pass
            _upsert_mapping(local_id, mode, stripe_product_id=sp_id,
                            stripe_price_id=new_price["id"], price_cents=price_cents,
                            currency=currency)
            out.update({"ok": True, "stripe_product_id": sp_id,
                        "stripe_price_id": new_price["id"],
                        "action": "updated_with_new_price"})
            return out

        _upsert_mapping(local_id, mode, stripe_product_id=sp_id,
                        stripe_price_id=sprice_id_old, price_cents=price_cents,
                        currency=currency)
        out.update({"ok": True, "stripe_product_id": sp_id,
                    "stripe_price_id": sprice_id_old, "action": "updated"})
        return out
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        try:
            _upsert_mapping(local_id, mode, error=msg)
        except Exception:
            pass
        _capture(e)
        out["error"] = msg
        return out


def archive_product(local_id):
    """Flip Stripe Product active=False for ALL modes with a mapping. Call from
    the DELETE route BEFORE the local row is removed. Never raises."""
    out = {}
    try:
        mappings = _read_all_mappings(local_id)
    except Exception as e:
        return {"error": f"mapping read failed: {e}"}
    if not mappings:
        return {"skipped": "no mappings"}
    for row in mappings:
        m = row.get("mode") or ""
        sp_id = row.get("stripe_product_id") or ""
        if not sp_id:
            out[m] = {"skipped": "no stripe_product_id"}
            continue
        if m not in ("test", "live"):
            out[m] = {"skipped": f"unknown mode {m!r}"}
            continue
        try:
            stripe = stripe_client.get_stripe_for_mode(m)
            stripe.Product.modify(sp_id, active=False)
            out[m] = {"ok": True, "stripe_product_id": sp_id}
        except Exception as e:
            _capture(e)
            out[m] = {"ok": False, "error": f"{type(e).__name__}: {e}",
                      "stripe_product_id": sp_id}
    return out


def backfill_all():
    """Run sync_product for every active local product. Returns counts + a small
    error sample."""
    summary = {"synced": 0, "failed": 0, "skipped": 0, "errors": [], "ran_at": _now_iso()}
    try:
        rows = _query_db("SELECT id, slug FROM products WHERE active = TRUE "
                         "ORDER BY sort_order, id") or []
    except Exception as e:
        summary["errors"].append(f"product list failed: {e}")
        return summary
    for r in rows:
        try:
            res = sync_product(r["id"])
        except Exception as e:
            res = {"ok": False, "error": f"sync_product raised: {e}"}
        if res.get("ok"):
            summary["synced"] += 1
        else:
            summary["failed"] += 1
            if len(summary["errors"]) < 20:
                summary["errors"].append({"local_id": r["id"], "slug": r.get("slug") or "",
                                          "error": res.get("error") or "unknown"})
    try:
        stripe_settings.record_backfill(summary)
    except Exception:
        pass
    return summary


def get_sync_status_rows():
    """Joined product + current-mode mapping rows for the admin UI table."""
    mode = stripe_settings.get_mode()
    rows = _query_db(
        """
        SELECT p.id AS local_id, p.slug, p.name, p.price_cents, p.currency,
               p.active AS local_active, s.stripe_product_id, s.stripe_price_id,
               s.synced_price_cents, s.synced_currency, s.last_synced_at,
               s.last_attempt_at, s.last_error
        FROM products p
        LEFT JOIN stripe_product_sync s
               ON s.local_product_id = p.id AND s.mode = %s
        ORDER BY p.sort_order, p.id
        """, (mode,)) or []
    out = []
    for r in rows:
        d = dict(r)
        d["has_mapping"] = bool(r.get("stripe_product_id"))
        d["price_drift"] = (d["has_mapping"]
                            and r.get("synced_price_cents") is not None
                            and int(r.get("synced_price_cents") or 0) != int(r.get("price_cents") or 0))
        d["last_synced_at"] = (r["last_synced_at"].isoformat() if r.get("last_synced_at") else None)
        d["last_attempt_at"] = (r["last_attempt_at"].isoformat() if r.get("last_attempt_at") else None)
        out.append(d)
    return {"mode": mode, "rows": out, "count": len(out)}
