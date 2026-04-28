"""
Mirror local `products` rows into Stripe Products + Prices.

The mapping lives in `stripe_product_sync` keyed by `(local_product_id,
mode)`, so test and live each have their own independent catalogue. A
mode flip does NOT re-create any product — it just changes which row
gets consulted on the next sync.

Three operations, all exception-safe (Stripe failures are recorded into
the mapping row's `last_error` column and returned in the result dict;
they NEVER raise out, so a Stripe outage can't break local product
CRUD):

- `sync_product(local_id)` — idempotent. Creates a Stripe Product +
  Price the first time it runs. On subsequent calls: updates name /
  description / images on the Product (those are mutable), and if the
  price_cents changed, creates a NEW Price + sets it as the Product's
  default and flips the old Price to inactive (Stripe forbids modifying
  Price.unit_amount in place).

- `archive_product(local_id)` — flips `active=False` on the Stripe
  Product across BOTH modes (test + live) if either side has a mapping.
  Called from the local DELETE route BEFORE the row is removed (the
  mapping cascades on DELETE so we have to read it first).

- `backfill_all()` — iterates every active local product and runs
  `sync_product` for each. Returns `{synced, failed, skipped, errors}`.
  Used for the "Backfill all products" admin button.

Stripe Product/Price model recap (so the mapping logic is clear to
future readers):
  - A Product is the catalog entry (name, description, images). Mutable.
  - A Price is what the customer is charged. ONE-WAY: once created, you
    can change `active` and `nickname` but NOT `unit_amount` or
    `currency`. So a price-bump = create a new Price + flip the old to
    inactive + set new as default. The old Price still exists (and
    still works on any in-flight Checkout Sessions that reference it
    by ID); it's just no longer the catalog default.
"""
import json
from datetime import datetime, timezone

import sentry_sdk

import stripe_client
import stripe_settings
import app as _app


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _read_product(local_id):
    """Fetch the local product row. Returns None if it doesn't exist
    (caller should treat that as a no-op success, not an error)."""
    return _app.query_db(
        "SELECT id, slug, name, description, price_cents, currency, "
        "       image_url, gallery_images, active "
        "FROM products WHERE id = %s",
        (int(local_id),),
        fetchone=True,
    )


def _read_mapping(local_id, mode):
    return _app.query_db(
        "SELECT id, stripe_product_id, stripe_price_id, "
        "       synced_price_cents, synced_currency, last_synced_at "
        "FROM stripe_product_sync "
        "WHERE local_product_id = %s AND mode = %s",
        (int(local_id), mode),
        fetchone=True,
    )


def _read_all_mappings(local_id):
    """Both modes — used by archive_product so we hit both catalogs."""
    return _app.query_db(
        "SELECT mode, stripe_product_id "
        "FROM stripe_product_sync "
        "WHERE local_product_id = %s",
        (int(local_id),),
    ) or []


def _upsert_mapping(local_id, mode, *, stripe_product_id="",
                    stripe_price_id="", price_cents=None, currency="",
                    error=""):
    """Insert/update the mapping row. Stamps last_attempt_at always;
    stamps last_synced_at only when error is empty (a successful sync)."""
    # When this is an error-only upsert, INSERT must NOT touch
    # last_synced_at (so a fresh row gets NULL — meaning "never
    # synced") and the ON CONFLICT branch must KEEP the prior value
    # (so an existing successful sync isn't blanked by a transient
    # failure). On success we stamp NOW() in both INSERT and update.
    last_synced_insert = "NOW()" if not error else "NULL"
    last_synced_update = (
        "EXCLUDED.last_synced_at"
        if not error
        else "stripe_product_sync.last_synced_at"
    )
    _app.execute_db(
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
         price_cents, currency, (error or "")[:1000]),
    )


def _gallery_to_image_list(product):
    """Stripe accepts up to 8 image URLs per Product. Build the list
    from image_url + gallery_images (JSONB array of URL strings),
    de-duplicating and capping at 8 to match Stripe's limit."""
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
    """Stripe currency codes are lowercase ISO-4217 strings (e.g. 'usd').
    Local rows store either 'USD' or 'usd' depending on which form
    was used at create time."""
    return (currency or "usd").strip().lower() or "usd"


def sync_product(local_id):
    """Idempotent mirror of local product → Stripe. Returns a dict:
        { ok: bool, mode: str, stripe_product_id: str|None,
          stripe_price_id: str|None, error: str|None,
          action: 'created'|'updated'|'updated_with_new_price'|'no_change' }
    NEVER raises. A Stripe failure is captured into last_error AND the
    return dict; the caller's local CRUD is unaffected.
    """
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
        # Stripe not configured at all — record on the mapping so the
        # admin sees it inline.
        try:
            _upsert_mapping(local_id, mode, error=str(e))
        except Exception as _:
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

    metadata = {
        "local_product_id": str(product["id"]),
        "local_slug": product.get("slug") or "",
    }

    try:
        # ---------- CREATE PATH ----------
        if not existing or not existing.get("stripe_product_id"):
            sp = stripe.Product.create(
                name=name,
                description=description,
                images=images or None,
                active=is_active,
                metadata=metadata,
            )
            sprice = stripe.Price.create(
                product=sp["id"],
                unit_amount=price_cents,
                currency=currency,
                metadata=metadata,
            )
            try:
                stripe.Product.modify(sp["id"], default_price=sprice["id"])
            except Exception as _:
                # Non-fatal — the Price still works for Checkout, the
                # default_price is just a convenience.
                pass
            _upsert_mapping(
                local_id, mode,
                stripe_product_id=sp["id"],
                stripe_price_id=sprice["id"],
                price_cents=price_cents,
                currency=currency,
            )
            out.update({"ok": True, "stripe_product_id": sp["id"],
                        "stripe_price_id": sprice["id"], "action": "created"})
            return out

        # ---------- UPDATE PATH ----------
        sp_id = existing["stripe_product_id"]
        sprice_id_old = existing.get("stripe_price_id") or ""
        prev_cents = existing.get("synced_price_cents")
        prev_currency = existing.get("synced_currency") or ""

        # Always update the mutable Product fields.
        stripe.Product.modify(
            sp_id,
            name=name,
            description=description,
            images=images or None,
            active=is_active,
            metadata=metadata,
        )

        # Did the Price change? Stripe forbids in-place edits to
        # unit_amount/currency, so create a new Price and flip the old
        # one to inactive.
        price_changed = (
            prev_cents != price_cents
            or (prev_currency.lower() != currency.lower())
        )

        if price_changed or not sprice_id_old:
            new_price = stripe.Price.create(
                product=sp_id,
                unit_amount=price_cents,
                currency=currency,
                metadata=metadata,
            )
            try:
                stripe.Product.modify(sp_id, default_price=new_price["id"])
            except Exception as _:
                pass
            if sprice_id_old:
                try:
                    stripe.Price.modify(sprice_id_old, active=False)
                except Exception as _:
                    # Old Price might already be inactive / not found.
                    pass
            _upsert_mapping(
                local_id, mode,
                stripe_product_id=sp_id,
                stripe_price_id=new_price["id"],
                price_cents=price_cents,
                currency=currency,
            )
            out.update({"ok": True, "stripe_product_id": sp_id,
                        "stripe_price_id": new_price["id"],
                        "action": "updated_with_new_price"})
            return out

        # No price change — just stamp the timestamp.
        _upsert_mapping(
            local_id, mode,
            stripe_product_id=sp_id,
            stripe_price_id=sprice_id_old,
            price_cents=price_cents,
            currency=currency,
        )
        out.update({"ok": True, "stripe_product_id": sp_id,
                    "stripe_price_id": sprice_id_old, "action": "updated"})
        return out

    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        try:
            _upsert_mapping(local_id, mode, error=msg)
        except Exception as _:
            pass
        try:
            sentry_sdk.capture_exception(e)
        except Exception:
            pass
        out["error"] = msg
        return out


def archive_product(local_id):
    """Flip Stripe Product `active=False` for ALL modes that have a
    mapping for this local_id. Called from the DELETE route BEFORE the
    local row is removed (the mapping rows cascade on DELETE so we'd
    lose them otherwise). Returns a dict per mode. Never raises.
    """
    out = {}
    try:
        mappings = _read_all_mappings(local_id)
    except Exception as e:
        return {"error": f"mapping read failed: {e}"}
    if not mappings:
        return {"skipped": "no mappings"}

    # Resolve keys per-mode WITHOUT mutating the persisted global mode —
    # mutating it would race with concurrent requests and could leave the
    # process in the wrong mode if we crash mid-loop. get_stripe_for_mode
    # uses the cached resolver keyed by mode, no settings write.
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
            try:
                sentry_sdk.capture_exception(e)
            except Exception:
                pass
            out[m] = {"ok": False, "error": f"{type(e).__name__}: {e}",
                      "stripe_product_id": sp_id}
    return out


def backfill_all():
    """Run sync_product for every active local product. Returns counts +
    a small error sample so the admin UI can show what failed without
    pulling 100s of error rows.
    """
    summary = {"synced": 0, "failed": 0, "skipped": 0,
               "errors": [], "ran_at": _now_iso()}
    try:
        rows = _app.query_db(
            "SELECT id, slug FROM products "
            "WHERE active = TRUE ORDER BY sort_order, id"
        ) or []
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
                summary["errors"].append({
                    "local_id": r["id"],
                    "slug": r.get("slug") or "",
                    "error": res.get("error") or "unknown",
                })

    try:
        stripe_settings.record_backfill(summary)
    except Exception:
        pass
    return summary


def get_sync_status_rows():
    """Return joined product + current-mode mapping rows for the admin
    UI table. Fields are flat & JSON-serialisable. Includes products
    that have NO mapping yet (left-join) so the admin sees them too."""
    mode = stripe_settings.get_mode()
    rows = _app.query_db(
        """
        SELECT p.id              AS local_id,
               p.slug,
               p.name,
               p.price_cents,
               p.currency,
               p.active           AS local_active,
               s.stripe_product_id,
               s.stripe_price_id,
               s.synced_price_cents,
               s.synced_currency,
               s.last_synced_at,
               s.last_attempt_at,
               s.last_error
        FROM products p
        LEFT JOIN stripe_product_sync s
               ON s.local_product_id = p.id AND s.mode = %s
        ORDER BY p.sort_order, p.id
        """,
        (mode,),
    ) or []
    out = []
    for r in rows:
        d = dict(r)
        # Stamp the boolean for the UI: synced this mode? price drift?
        d["has_mapping"] = bool(r.get("stripe_product_id"))
        d["price_drift"] = (
            d["has_mapping"]
            and r.get("synced_price_cents") is not None
            and int(r.get("synced_price_cents") or 0) != int(r.get("price_cents") or 0)
        )
        d["last_synced_at"] = (r["last_synced_at"].isoformat()
                               if r.get("last_synced_at") else None)
        d["last_attempt_at"] = (r["last_attempt_at"].isoformat()
                                if r.get("last_attempt_at") else None)
        out.append(d)
    return {"mode": mode, "rows": out, "count": len(out)}
