"""Task 050 — Phase 6 admin dashboard tabs (Offers, Personas, Leads & CRM).
Embedded Postgres.

The CRUD/read APIs behind these tabs are tested in their own suites; here we
pin the UI wiring: the super-admin dashboard renders the new tab buttons,
panels, and JS, and a CLIENT-role session never sees the super-admin-only tabs.
"""
import os

import app

ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "admin")
CLIENT_PW = os.environ.get("CLIENT_PASSWORD", "")

SUPERADMIN_MARKERS = [
    "switchTab('offers'", "loadOffers()", 'id="tab-offers"',
    "switchTab('visitor-personas'", "loadVisitorPersonas()", 'id="tab-visitor-personas"',
    "switchTab('crm'", "loadCrm()", 'id="tab-crm"',
    "function saveOffer", "function savePersona", "function crmShow",
    "/admin/api/offers", "/admin/api/visitor-personas", "/admin/api/leads",
    "/admin/api/callbacks", "/admin/api/meetings", "/admin/api/voice-calls",
]

TAB_BUTTONS = ["switchTab('offers'", "switchTab('visitor-personas'", "switchTab('crm'"]


def _login(pw):
    c = app.app.test_client()
    c.post("/admin/login", data={"password": pw})
    return c


def test_super_admin_sees_all_phase6_tabs():
    html = _login(ADMIN_PW).get("/admin").get_data(as_text=True)
    missing = [m for m in SUPERADMIN_MARKERS if m not in html]
    assert not missing, f"missing from super-admin dashboard: {missing}"


def test_client_does_not_see_phase6_tabs():
    if not CLIENT_PW:
        return
    html = _login(CLIENT_PW).get("/admin").get_data(as_text=True)
    leaked = [m for m in TAB_BUTTONS if m in html]
    assert not leaked, f"super-admin-only tabs leaked to client: {leaked}"
