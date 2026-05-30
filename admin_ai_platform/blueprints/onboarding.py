"""
admin_ai_platform.blueprints.onboarding
========================================

First-run + client + agency onboarding (M17).

  * ``GET  /setup``            first-run wizard form — 404 once setup is complete
  * ``POST /setup``            provision (preset + business name + admin password →
                               settings + seed content + first embed key), then
                               self-closes (subsequent /setup → 404)
  * ``GET  /admin/api/onboarding/checklist``     guided client checklist state
  * ``POST /admin/api/onboarding/seed-sample``   onboarding tool: seed sample content
  * ``GET  /admin/api/onboarding/assistant-prompt``  onboarding system prompt for the AI
  * ``POST /admin/api/onboarding/provision-tenant``  agency: new tenant + snapshot + key

**Security note:** provider API keys are intentionally NOT persisted to the DB by
``/setup`` — they belong in the environment (or the M19 secrets-at-rest store).
The wizard captures business identity, the admin password (hashed, see auth.py),
the preset seed, and the first publishable embed key.
"""

from __future__ import annotations

import json
import secrets as _secrets

from flask import Blueprint, request, jsonify

from ..db import query_db, execute_db
from ..auth import admin_required, set_admin_password
from ..tenancy import current_tenant_id

bp = Blueprint("onboarding", __name__)

# Industry presets — a greeting + a few sample experiences to seed so a fresh
# install isn't empty. Kept small; the operator edits/extends from the dashboard.
PRESETS = {
    "generic": {"greeting": "Hi! How can I help you today?",
                "experiences": [("Welcome", "Ask me anything about us."),
                                ("Get in touch", "I can help you reach the team.")]},
    "restaurant": {"greeting": "Welcome! Hungry? I can help with menu, hours, and reservations.",
                   "experiences": [("Reserve a table", "I can take your booking."),
                                   ("Tonight's specials", "Ask about the chef's specials."),
                                   ("Private events", "We host private dinners.")]},
    "salon": {"greeting": "Hi! Looking to book an appointment or ask about services?",
              "experiences": [("Book an appointment", "Pick a service and time."),
                              ("Our services", "Cuts, color, and treatments."),
                              ("Meet our stylists", "Find the right stylist for you.")]},
    "retail": {"greeting": "Welcome! I can help you find products, sizes, and orders.",
               "experiences": [("Shop products", "Browse what's in stock."),
                               ("Track an order", "I can look up your order."),
                               ("Store hours", "Find when we're open.")]},
}


def _setup_row():
    return query_db("SELECT * FROM platform_setup WHERE id=1", fetchone=True) or {}


def _is_complete():
    return bool(_setup_row().get("completed"))


_SETUP_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Set up your AI Concierge</title>
<style>body{font-family:system-ui,sans-serif;background:#0a0f1a;color:#e8e8ec;
max-width:560px;margin:40px auto;padding:0 20px}h1{color:#c9a96e}label{display:block;
margin:14px 0 4px;font-size:14px}input,select{width:100%;padding:10px;border-radius:8px;
border:1px solid rgba(255,255,255,.15);background:rgba(255,255,255,.05);color:#e8e8ec}
button{margin-top:18px;background:#c9a96e;color:#1a1a1a;border:0;border-radius:8px;
padding:11px 18px;font-weight:600;cursor:pointer}.muted{opacity:.6;font-size:13px}
#out{margin-top:16px;white-space:pre-wrap}</style></head><body>
<h1>Set up your AI Concierge</h1>
<p class="muted">First-run setup. This page disappears once completed.</p>
<label>Business name</label><input id="biz" placeholder="Acme Vineyard">
<label>Industry preset</label><select id="preset">
<option value="generic">Generic</option><option value="restaurant">Restaurant</option>
<option value="salon">Salon / Spa</option><option value="retail">Retail / Shop</option></select>
<label>Admin password</label><input id="pw" type="password" placeholder="choose a strong password">
<p class="muted">Provider API keys (OpenAI/Anthropic/etc.) are set as environment
variables, not here.</p>
<button onclick="go()">Finish setup</button>
<div id="out"></div>
<script>
async function go(){
  const out=document.getElementById('out'); out.textContent='Provisioning…';
  const r=await fetch('/setup',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({business_name:document.getElementById('biz').value,
      preset:document.getElementById('preset').value,
      admin_password:document.getElementById('pw').value})});
  const j=await r.json().catch(()=>({}));
  if(r.ok){ out.textContent='Done! Your embed key: '+(j.embed_key||'(created)')+
    '\\nRedirecting to admin…'; setTimeout(()=>location.href='/admin/login',1500); }
  else { out.textContent='Error: '+(j.error||r.status); }
}
</script></body></html>"""


@bp.route("/setup", methods=["GET"])
def setup_form():
    if _is_complete():
        return jsonify({"error": "setup already complete"}), 404
    return _SETUP_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


@bp.route("/setup", methods=["POST"])
def setup_provision():
    if _is_complete():
        return jsonify({"error": "setup already complete"}), 404
    d = request.get_json(silent=True) or {}
    business = (d.get("business_name") or "").strip()
    preset = (d.get("preset") or "generic").lower()
    password = (d.get("admin_password") or "").strip()
    if preset not in PRESETS:
        preset = "generic"
    if len(password) < 6:
        return jsonify({"error": "admin_password must be at least 6 characters"}), 400

    p = PRESETS[preset]
    # 1) Business identity.
    execute_db("INSERT INTO business_info (id, name) VALUES (1,%s) "
               "ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name", (business,))
    # 2) Chatbot greeting + enable.
    execute_db("UPDATE chatbot_settings SET greeting=%s, enabled=TRUE, "
               "agent_name=COALESCE(NULLIF(agent_name,''),%s) WHERE id=1",
               (p["greeting"], (business or "Concierge")))
    # 3) Seed sample experiences (only if the table is empty — don't clobber).
    if not query_db("SELECT 1 FROM experiences LIMIT 1", fetchone=True):
        for i, (name, desc) in enumerate(p["experiences"]):
            execute_db("INSERT INTO experiences (name, description, sort_order) "
                       "VALUES (%s,%s,%s)", (name, desc, i))
    # 4) Admin password (hashed).
    set_admin_password(password)
    # 5) First publishable embed key.
    key = "pk_" + _secrets.token_urlsafe(24)
    execute_db("INSERT INTO tenant_embed_keys (tenant_id, embed_key, label, origin_allowlist) "
               "VALUES (%s,%s,'Default',%s::jsonb)",
               (current_tenant_id(), key, json.dumps([])))
    # 6) Mark complete (closes /setup).
    execute_db("UPDATE platform_setup SET completed=TRUE, preset=%s, business_name=%s, "
               "completed_at=NOW() WHERE id=1", (preset, business))
    return jsonify({"ok": True, "embed_key": key, "preset": preset}), 201


# ---- client onboarding checklist ---------------------------------------
@bp.route("/admin/api/onboarding/checklist", methods=["GET"])
@admin_required
def checklist():
    """Live completion state for the guided client checklist."""
    def has(sql):
        return bool(query_db(sql, fetchone=True))
    biz = query_db("SELECT name FROM business_info WHERE id=1", fetchone=True) or {}
    steps = {
        "business_named": bool((biz.get("name") or "").strip()),
        "has_content": has("SELECT 1 FROM gallery_cards LIMIT 1")
                       or has("SELECT 1 FROM experiences LIMIT 1")
                       or has("SELECT 1 FROM products LIMIT 1"),
        "has_embed_key": has("SELECT 1 FROM tenant_embed_keys WHERE tenant_id=%s LIMIT 1"
                             % current_tenant_id()),
        "chatbot_enabled": has("SELECT 1 FROM chatbot_settings WHERE id=1 AND enabled=TRUE"),
        "had_a_chat": has("SELECT 1 FROM chat_conversations LIMIT 1"),
    }
    done = sum(1 for v in steps.values() if v)
    return jsonify({"steps": steps, "complete": done, "total": len(steps)})


@bp.route("/admin/api/onboarding/seed-sample", methods=["POST"])
@admin_required
def seed_sample():
    """Onboarding tool: seed a couple of sample gallery cards so a new operator
    sees the widget do something immediately. Idempotent-ish (skips if present)."""
    if query_db("SELECT 1 FROM gallery_cards LIMIT 1", fetchone=True):
        return jsonify({"ok": True, "skipped": "gallery already has cards"})
    samples = [("welcome", "Welcome", "Discover what we offer", "spaces"),
               ("contact", "Get in touch", "We'd love to hear from you", "info")]
    for i, (slug, title, sub, cat) in enumerate(samples):
        execute_db("INSERT INTO gallery_cards (slug, title, subtitle, image_url, category, "
                   "sort_order) VALUES (%s,%s,%s,'',%s,%s) ON CONFLICT (slug) DO NOTHING",
                   (slug, title, sub, cat, i))
    return jsonify({"ok": True, "seeded": len(samples)})


_ONBOARDING_PROMPT = (
    "You are an onboarding assistant for a new operator setting up their AI "
    "Concierge. Walk them through, one step at a time: (1) name their business "
    "and set a greeting, (2) add some content (gallery cards / experiences / "
    "products), (3) create an embed key and paste the snippet on their site, "
    "(4) try a test chat. Use the onboarding tools when helpful (seed sample "
    "content, create an embed key). Be concise and encouraging; confirm each "
    "step before moving on.")


@bp.route("/admin/api/onboarding/assistant-prompt", methods=["GET"])
@admin_required
def assistant_prompt():
    """The onboarding system prompt the admin AI uses in onboarding mode."""
    return jsonify({"prompt": _ONBOARDING_PROMPT})


# ---- agency provisioning -----------------------------------------------
@bp.route("/admin/api/onboarding/provision-tenant", methods=["POST"])
@admin_required
def provision_tenant():
    """Agency flow: create a new tenant, issue its first embed key, and (optionally)
    apply a snapshot JSON into it. Wraps the tenancy snapshot/apply primitives.
    Only meaningful in central mode (multi-tenant)."""
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    tenant = execute_db("INSERT INTO tenants (name) VALUES (%s) RETURNING id", (name,))
    tid = tenant["id"]
    key = "pk_" + _secrets.token_urlsafe(24)
    execute_db("INSERT INTO tenant_embed_keys (tenant_id, embed_key, label, origin_allowlist) "
               "VALUES (%s,%s,'Default',%s::jsonb)", (tid, key, json.dumps([])))
    # Optionally seed the new tenant's catalog from a snapshot's gallery cards
    # (the common clone need). Per-tenant data isolation lands in M18; here we
    # apply the cards with the same UPSERT-by-slug the snapshot/apply route uses.
    applied = 0
    snapshot = d.get("snapshot") or {}
    for card in (snapshot.get("tables", {}) or {}).get("gallery_cards", []):
        try:
            execute_db(
                "INSERT INTO gallery_cards (slug, title, subtitle, image_url, category, "
                "sort_order) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (slug) DO NOTHING",
                (card.get("slug"), card.get("title", ""), card.get("subtitle", ""),
                 card.get("image_url", ""), card.get("category", ""),
                 int(card.get("sort_order", 0) or 0)))
            applied += 1
        except Exception as e:
            print(f"[onboarding] snapshot card skipped: {e}")
    return jsonify({"ok": True, "tenant_id": tid, "embed_key": key,
                    "snapshot_cards_applied": applied}), 201
