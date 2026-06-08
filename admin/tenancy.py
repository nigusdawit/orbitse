"""admin/tenancy.py - super-admin Plans & Features management API, as a blueprint.

Part of the app.py de-monolith (Track B), mirroring admin/crm.py. These two routes
back the "Plans & Features" tab: list every feature in the registry with its on/off
state + plan tier, and flip one feature on/off. They are the REAL security boundary
for feature visibility, so each calls _require_super_admin_role() (from core) up front
- exactly as it did in app.py. The @admin_required decorator only proves "an admin is
logged in"; the super-admin gate is enforced in the body and is preserved verbatim. A
plain client session is 403'd, which is what stops a client from re-granting itself
tabs by hitting the API directly (independent of the hidden UI tab).

URLs keep their absolute /admin/api/* paths, so the route table is unchanged - only the
Flask endpoint name gains a "tenancy." prefix (admin JS calls these by URL, not url_for).
CSRF / feature-flag enforcement runs in app.py's global before_request hooks, which apply
to blueprint routes too, so nothing extra is needed here.

Imports come from core (never app - that would be circular). The feature subsystem now
lives in core (Track B): list_tenant_features / set_tenant_feature do the read + flip
(the flip busts the in-process cache), and current_tenant_id scopes to the active tenant.

Registered in app.py via app.register_blueprint(tenancy_bp), after crm_bp.
"""
import os

from flask import Blueprint, request, jsonify

from core import (
    capture_exc,
    query_db,
    execute_db,
    admin_required,
    _require_super_admin_role,
    current_tenant_id,
    list_tenant_features,
    set_tenant_feature,
    set_tenant_feature_visible,
)

# Stripe SDK is OPTIONAL here — billing (gap §6.2) only does anything once the operator
# sets PLATFORM_STRIPE_SECRET_KEY. Guard the import so the module loads fine on installs
# without the package or without billing configured.
try:
    import stripe as _stripe
except Exception:  # pragma: no cover - package always present in this repo's requirements
    _stripe = None

tenancy_bp = Blueprint("tenancy", __name__)


@tenancy_bp.route("/admin/api/tenant/features", methods=["GET"])
@admin_required
def admin_list_tenant_features():
    """Return every known feature + on/off state + plan tier + addon flag."""
    # HARD boundary: only the super admin manages feature visibility. A client
    # session is logged-in (passes @admin_required) but must never read or change
    # the feature roster — this is what stops a client from re-granting itself
    # tabs by hitting the API directly, independent of the hidden UI tab.
    _guard = _require_super_admin_role()
    if _guard is not None:
        return _guard
    try:
        tid = current_tenant_id()
        # Pull plan + tenant info so the UI can show "you're on the Growth plan".
        # NOTE: the plans table has columns (id, slug, name, description,
        # sort_order). We expose `slug` as `plan_code` for UI back-compat.
        tenant = query_db(
            "SELECT t.id, t.name AS tenant_name, t.plan_id, "
            "       p.slug AS plan_code, p.name AS plan_name "
            "FROM tenants t LEFT JOIN plans p ON p.id = t.plan_id "
            "WHERE t.id = %s",
            (tid,), fetchone=True,
        ) or {}
        features = list_tenant_features(tid)
        plans = query_db(
            "SELECT id, slug AS code, name, description, sort_order "
            "FROM plans ORDER BY sort_order, id"
        ) or []
        return jsonify({
            "tenant": dict(tenant) if tenant else {"id": tid},
            "features": features,
            "plans": [dict(p) for p in plans],
        })
    except Exception as e:
        capture_exc(e, "tenancy.admin_list_tenant_features")
        print(f"[plans] list_tenant_features failed: {e}")
        return jsonify({"error": "failed_to_list_features", "detail": str(e)}), 500


@tenancy_bp.route("/admin/api/tenant/features/<name>", methods=["PATCH"])
@admin_required
def admin_toggle_tenant_feature(name):
    """Set one feature's function and/or visibility.

    Body may carry either or both knobs (they are independent):
      {"enabled": bool, "note"?: str}  → backend function gate (on/off)
      {"visible": bool}                → UI visibility (sidebar/tab shown to client)
    The function gate is unchanged from before; visibility is the new separate knob.
    """
    # HARD boundary: super admin only (see admin_list_tenant_features). Without
    # this in-handler check a client could PATCH its own flags via curl.
    _guard = _require_super_admin_role()
    if _guard is not None:
        return _guard
    body = request.get_json(silent=True) or {}
    has_enabled = "enabled" in body
    has_visible = "visible" in body
    if not has_enabled and not has_visible:
        return jsonify({"error": "missing_field", "field": "enabled|visible"}), 400
    try:
        resp = {"feature": name}
        if has_enabled:
            resp["enabled"] = set_tenant_feature(
                name,
                bool(body.get("enabled")),
                note=str(body.get("note") or ""),
            )
        if has_visible:
            resp["visible"] = set_tenant_feature_visible(
                name,
                bool(body.get("visible")),
            )
        return jsonify(resp)
    except ValueError as ve:
        return jsonify({"error": "unknown_feature", "feature": name, "detail": str(ve)}), 400
    except Exception as e:
        capture_exc(e, "tenancy.admin_toggle_tenant_feature")
        print(f"[plans] toggle feature {name} failed: {e}")
        return jsonify({"error": "toggle_failed", "detail": str(e)}), 500


# --- Billing (gap §6.2) -----------------------------------------------------
# Shows the TENANT's subscription to THIS PLATFORM (the client paying us). That runs on a
# SEPARATE platform Stripe account (PLATFORM_STRIPE_SECRET_KEY), distinct from each client's
# own order-checkout Stripe (STRIPE_SECRET_KEY) — so we pass the platform key per-call and
# never touch the order-checkout client's global stripe.api_key. Super-admin only, matching
# the Plans & Features tab. Everything degrades gracefully: the plan always renders from the
# DB; a missing key / unlinked tenant / Stripe error becomes a clear flag, never a hard 500.

def _platform_stripe_key():
    return (os.environ.get("PLATFORM_STRIPE_SECRET_KEY") or "").strip()


def _billing_configured():
    return bool(_stripe and _platform_stripe_key())


def _tenant_billing_row(tid):
    return query_db(
        "SELECT t.id, t.name AS tenant_name, t.status AS tenant_status, "
        "       t.stripe_customer_id, t.stripe_subscription_id, "
        "       p.slug AS plan_code, p.name AS plan_name, p.price_display "
        "  FROM tenants t LEFT JOIN plans p ON p.id = t.plan_id "
        " WHERE t.id = %s",
        (tid,), fetchone=True,
    ) or {}


@tenancy_bp.route("/admin/api/billing", methods=["GET"])
@admin_required
def admin_billing():
    """Current plan (always, from the DB) + — when PLATFORM_STRIPE_SECRET_KEY is set AND the
    tenant is linked — live subscription status + recent invoices from the platform Stripe
    account. Fail-open: any missing-key / not-linked / Stripe error degrades to a flag.

    Visible to ANY admin: a client sees their OWN tenant's plan/invoices/portal (scoped by
    current_tenant_id). The management surface (test connection, products, linking) is a
    separate super-admin-only concern — see the routes below."""
    try:
        tid = current_tenant_id()
        row = _tenant_billing_row(tid)
        cust = (row.get("stripe_customer_id") or "").strip()
        sub_id = (row.get("stripe_subscription_id") or "").strip()
        out = {
            "plan": {
                "code": row.get("plan_code") or "",
                "name": row.get("plan_name") or "Free",
                "price_display": row.get("price_display") or "",
            },
            "tenant": {
                "id": row.get("id") or tid,
                "name": row.get("tenant_name") or "",
                "status": row.get("tenant_status") or "",
            },
            "configured": _billing_configured(),
            "linked": bool(cust),
            "link": {"customer_id": cust, "subscription_id": sub_id},
            "subscription": None,
            "invoices": [],
            "portal_available": False,
            "stripe_error": "",
        }
        if not out["configured"] or not cust:
            return jsonify(out)
        # Live read from the PLATFORM account (read-only; per-call api_key keeps it isolated
        # from the order-checkout client). Any failure here is non-fatal — we still return
        # the plan + flags so the tab renders.
        key = _platform_stripe_key()
        try:
            if sub_id:
                sub = _stripe.Subscription.retrieve(sub_id, api_key=key, expand=["items.data.price"])
                item = ((sub.get("items") or {}).get("data") or [{}])[0]
                price = item.get("price") or {}
                out["subscription"] = {
                    "status": sub.get("status") or "",
                    "current_period_end": sub.get("current_period_end"),
                    "cancel_at_period_end": bool(sub.get("cancel_at_period_end")),
                    "amount": price.get("unit_amount"),
                    "currency": (price.get("currency") or "usd").upper(),
                    "interval": (price.get("recurring") or {}).get("interval") or "",
                }
            inv = _stripe.Invoice.list(customer=cust, limit=6, api_key=key)
            out["invoices"] = [{
                "number": i.get("number") or "",
                "created": i.get("created"),
                "amount_paid": i.get("amount_paid"),
                "currency": (i.get("currency") or "usd").upper(),
                "status": i.get("status") or "",
                "hosted_invoice_url": i.get("hosted_invoice_url") or "",
            } for i in (inv.get("data") or [])]
            out["portal_available"] = True
        except Exception as e:
            print(f"[billing] stripe fetch failed: {e}")
            out["stripe_error"] = "Could not reach Stripe with the platform key."
        return jsonify(out)
    except Exception as e:
        capture_exc(e, "tenancy.admin_billing")
        print(f"[billing] admin_billing failed: {e}")
        return jsonify({"error": "billing_failed", "detail": str(e)}), 500


@tenancy_bp.route("/admin/api/billing/portal", methods=["POST"])
@admin_required
def admin_billing_portal():
    """Create a Stripe billing-portal session for this tenant's platform customer so the
    admin (the client themselves) can manage payment method / view invoices in Stripe.
    Returns {url}. Visible to any admin — it's their own subscription."""
    if not _billing_configured():
        return jsonify({"error": "not_configured",
                        "message": "Add PLATFORM_STRIPE_SECRET_KEY to enable the billing portal."}), 400
    try:
        tid = current_tenant_id()
        cust = (_tenant_billing_row(tid).get("stripe_customer_id") or "").strip()
        if not cust:
            return jsonify({"error": "not_linked",
                            "message": "Link this tenant to a Stripe customer first."}), 400
        return_url = request.host_url.rstrip("/") + "/admin"
        sess = _stripe.billing_portal.Session.create(
            customer=cust, return_url=return_url, api_key=_platform_stripe_key(),
        )
        return jsonify({"url": sess.get("url") or ""})
    except Exception as e:
        capture_exc(e, "tenancy.admin_billing_portal")
        print(f"[billing] portal session failed: {e}")
        return jsonify({"error": "portal_failed",
                        "message": "Could not create a billing portal session."}), 502


@tenancy_bp.route("/admin/api/billing/link", methods=["POST"])
@admin_required
def admin_billing_link():
    """Link this tenant to its platform Stripe customer/subscription so the Billing view can
    pull live status once PLATFORM_STRIPE_SECRET_KEY is set. Stores the ids only — no Stripe
    call. Light format check (cus_/sub_ prefixes; blank clears the link)."""
    _guard = _require_super_admin_role()
    if _guard is not None:
        return _guard
    body = request.get_json(silent=True) or {}
    cust = str(body.get("stripe_customer_id") or "").strip()
    sub = str(body.get("stripe_subscription_id") or "").strip()
    if cust and not cust.startswith("cus_"):
        return jsonify({"error": "bad_customer_id", "message": "Stripe customer ids start with 'cus_'."}), 400
    if sub and not sub.startswith("sub_"):
        return jsonify({"error": "bad_subscription_id", "message": "Stripe subscription ids start with 'sub_'."}), 400
    try:
        tid = current_tenant_id()
        execute_db(
            "UPDATE tenants SET stripe_customer_id=%s, stripe_subscription_id=%s, updated_at=NOW() "
            "WHERE id=%s",
            (cust, sub, tid),
        )
        return jsonify({"success": True, "stripe_customer_id": cust, "stripe_subscription_id": sub})
    except Exception as e:
        capture_exc(e, "tenancy.admin_billing_link")
        print(f"[billing] link failed: {e}")
        return jsonify({"error": "link_failed", "detail": str(e)}), 500


# --- Platform Stripe management (gap §6.2, SUPER-ADMIN only) ------------------
# The super admin manages the PLATFORM Stripe integration here — test the connection, see
# test/live mode, list the account's products/prices, and map plans to a Stripe price. This
# is the platform owner's concern (separate from each client's order-checkout Stripe console),
# so every route is super-admin gated. Everything is read-only against Stripe except the
# local plan↔price mapping; nothing is created in Stripe.

def _platform_stripe_mode():
    """test/live from the platform key prefix; 'none' if unset, 'unknown' if unrecognized."""
    k = _platform_stripe_key()
    if not k:
        return "none"
    if k.startswith("sk_live_") or k.startswith("rk_live_"):
        return "live"
    if k.startswith("sk_test_") or k.startswith("rk_test_"):
        return "test"
    return "unknown"


def _plans_with_mapping():
    return [dict(p) for p in (query_db(
        "SELECT slug AS code, name, stripe_price_id, stripe_product_id, price_display "
        "FROM plans ORDER BY sort_order, id"
    ) or [])]


@tenancy_bp.route("/admin/api/billing/stripe", methods=["GET"])
@admin_required
def admin_billing_stripe_status():
    """Super-admin: platform Stripe integration status (key present + test/live mode). No network."""
    _guard = _require_super_admin_role()
    if _guard is not None:
        return _guard
    return jsonify({
        "configured": _billing_configured(),
        "key_present": bool(_platform_stripe_key()),
        "sdk_present": bool(_stripe),
        "mode": _platform_stripe_mode(),
    })


@tenancy_bp.route("/admin/api/billing/stripe/probe", methods=["POST"])
@admin_required
def admin_billing_stripe_probe():
    """Super-admin: test the platform Stripe connection via Account.retrieve. Read-only. A bad
    key returns 200 {ok:false} (it's an expected test outcome, not a server error)."""
    _guard = _require_super_admin_role()
    if _guard is not None:
        return _guard
    if not _billing_configured():
        return jsonify({"ok": False, "error": "not_configured",
                        "message": "Add PLATFORM_STRIPE_SECRET_KEY to test the platform connection."}), 400
    try:
        acct = _stripe.Account.retrieve(api_key=_platform_stripe_key())
        bp = acct.get("business_profile") or {}
        dash = (acct.get("settings") or {}).get("dashboard") or {}
        name = dash.get("display_name") or bp.get("name") or acct.get("email") or acct.get("id") or ""
        return jsonify({
            "ok": True,
            "account_id": acct.get("id") or "",
            "name": name,
            "email": acct.get("email") or "",
            "mode": _platform_stripe_mode(),
            "charges_enabled": bool(acct.get("charges_enabled")),
        })
    except Exception as e:
        print(f"[billing] platform probe failed: {e}")
        return jsonify({"ok": False, "error": "probe_failed",
                        "message": "Stripe rejected the platform key. Check PLATFORM_STRIPE_SECRET_KEY."})


@tenancy_bp.route("/admin/api/billing/stripe/products", methods=["GET"])
@admin_required
def admin_billing_stripe_products():
    """Super-admin: list the platform account's active prices (+ their product) plus the app's
    plans with their current mapping, so the super admin can map plan ↔ price. Read-only."""
    _guard = _require_super_admin_role()
    if _guard is not None:
        return _guard
    if not _billing_configured():
        return jsonify({"configured": False, "products": [], "plans": _plans_with_mapping()})
    try:
        prices = _stripe.Price.list(active=True, limit=50, expand=["data.product"],
                                    api_key=_platform_stripe_key())
        out = []
        for pr in (prices.get("data") or []):
            prod = pr.get("product")
            is_obj = isinstance(prod, dict)
            rec = pr.get("recurring") or {}
            out.append({
                "price_id": pr.get("id") or "",
                "product_id": (prod.get("id") if is_obj else str(prod or "")),
                "product_name": (prod.get("name") if is_obj else ""),
                "amount": pr.get("unit_amount"),
                "currency": (pr.get("currency") or "usd").upper(),
                "interval": rec.get("interval") or "",
                "nickname": pr.get("nickname") or "",
            })
        return jsonify({"configured": True, "products": out, "plans": _plans_with_mapping()})
    except Exception as e:
        print(f"[billing] platform products failed: {e}")
        return jsonify({"configured": True, "products": [], "plans": _plans_with_mapping(),
                        "error": "Could not list products from the platform account."})


@tenancy_bp.route("/admin/api/billing/plan-price", methods=["POST"])
@admin_required
def admin_billing_plan_price():
    """Super-admin: map a plan to a platform Stripe price (+ its product). Stores the ids on the
    plan; no Stripe call. Blank price clears the mapping."""
    _guard = _require_super_admin_role()
    if _guard is not None:
        return _guard
    body = request.get_json(silent=True) or {}
    plan_code = str(body.get("plan_code") or "").strip()
    price_id = str(body.get("stripe_price_id") or "").strip()
    product_id = str(body.get("stripe_product_id") or "").strip()
    if not plan_code:
        return jsonify({"error": "missing_plan", "message": "plan_code is required."}), 400
    if price_id and not price_id.startswith("price_"):
        return jsonify({"error": "bad_price_id", "message": "Stripe price ids start with 'price_'."}), 400
    try:
        n = execute_db(
            "UPDATE plans SET stripe_price_id=%s, stripe_product_id=%s WHERE slug=%s",
            (price_id, product_id, plan_code),
        )
        if not n:
            return jsonify({"error": "unknown_plan", "message": f"No plan with code {plan_code!r}."}), 404
        return jsonify({"success": True, "plan_code": plan_code, "stripe_price_id": price_id})
    except Exception as e:
        capture_exc(e, "tenancy.admin_billing_plan_price")
        print(f"[billing] plan-price map failed: {e}")
        return jsonify({"error": "map_failed", "detail": str(e)}), 500
