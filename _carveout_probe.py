"""TEMP probe — boots the monolith (app.py) against an embedded Postgres and
verifies the M-client website_builder carve-out: the website-builder admin routes
403 when the flag is off, AI-concierge routes do NOT, and operator default is
unchanged. Deleted after use.
"""
import os
import tempfile


def main():
    import pgserver
    data_dir = tempfile.mkdtemp(prefix="carveout_")
    srv = pgserver.get_server(data_dir)
    os.environ["DATABASE_URL"] = srv.get_uri()
    os.environ.setdefault("SESSION_SECRET", "probe")
    os.environ.setdefault("ADMIN_PASSWORD", "admin")
    os.environ["SSO_SIGNING_SECRET"] = "ssosecret"   # before importing app
    print(f"[probe] PG up: {srv.get_uri()}", flush=True)

    passed, failed = [], []

    def check(name, cond):
        (passed if cond else failed).append(name)
        print(("  PASS " if cond else "  FAIL ") + name)

    try:
        import app as monolith
        flask_app = monolith.app
        # Ensure schema exists (monolith bootstraps via init_db()).
        try:
            monolith.init_db()
        except Exception as e:
            print(f"[probe] init_db note: {e}", flush=True)
        c = flask_app.test_client()

        # Registry wiring.
        check("website_builder in feature registry", "website_builder" in monolith._FEATURE_NAMES)
        check("website_builder defaults ON for operators",
              monolith._FEATURE_DEFAULTS.get("website_builder") is True)
        _prefixes = dict(monolith._FEATURE_ROUTE_PREFIXES)
        check("theme route mapped to website_builder",
              _prefixes.get("/admin/api/theme") == "website_builder")

        # With the flag ON (default), the website-builder route is NOT
        # feature-blocked — it should be 401 (needs admin), never a 403
        # feature_disabled.
        r_on = c.get("/admin/api/theme")
        body_on = r_on.get_json(silent=True) or {}
        check("theme NOT feature-blocked when flag ON",
              body_on.get("error") != "feature_disabled")

        # Turn website_builder OFF for tenant 1, bust the cache.
        monolith.execute_db(
            "INSERT INTO tenant_features (tenant_id, feature_name, enabled) VALUES (1,'website_builder',FALSE) "
            "ON CONFLICT (tenant_id, feature_name) DO UPDATE SET enabled=FALSE")
        monolith.invalidate_tenant_features_cache(1)

        r_off = c.get("/admin/api/theme")
        check("theme 403/404 feature-blocked when flag OFF",
              r_off.status_code in (403, 404))
        # POST (admin path) returns the explicit 403 feature_disabled.
        r_off_post = c.put("/admin/api/theme", json={})
        check("theme PUT -> 403 feature_disabled when OFF",
              r_off_post.status_code == 403
              and (r_off_post.get_json(silent=True) or {}).get("error") == "feature_disabled")

        # AI-concierge route must NOT be gated by website_builder.
        r_ai = c.get("/admin/api/chatbot-settings")
        check("AI route chatbot-settings NOT feature-blocked by website_builder",
              (r_ai.get_json(silent=True) or {}).get("feature") != "website_builder")
        # Public chat API must stay reachable (not website_builder-gated).
        r_chat = c.post("/api/chat", json={"message": "hi", "session_id": "p"})
        check("public /api/chat not website_builder-blocked",
              (r_chat.get_json(silent=True) or {}).get("feature") != "website_builder")

        # ===== Embed / cross-origin widget layer =====
        check("tenant_embed_keys table exists",
              monolith.query_db("SELECT to_regclass('public.tenant_embed_keys') AS t",
                                fetchone=True).get("t") is not None)
        monolith.execute_db("DELETE FROM tenant_embed_keys")
        monolith.execute_db(
            "INSERT INTO tenant_embed_keys (tenant_id, embed_key, label, origin_allowlist) "
            "VALUES (1, 'pk_probe', 'probe', '[\"https://shop.example\"]'::jsonb)")

        # Keyed request from an ALLOWLISTED origin → allowed + CORS header echoed.
        r_ok = c.get("/api/chatbot-settings",
                     headers={"X-Embed-Key": "pk_probe", "Origin": "https://shop.example"})
        check("keyed allowlisted origin allowed",
              r_ok.status_code == 200
              and r_ok.headers.get("Access-Control-Allow-Origin") == "https://shop.example")
        # Keyed request from a NON-allowlisted origin → 403.
        r_bad = c.get("/api/chatbot-settings",
                      headers={"X-Embed-Key": "pk_probe", "Origin": "https://evil.example"})
        check("keyed non-allowlisted origin -> 403", r_bad.status_code == 403)
        # Invalid key → 403.
        r_badkey = c.get("/api/chatbot-settings",
                         headers={"X-Embed-Key": "nope", "Origin": "https://shop.example"})
        check("invalid embed key -> 403", r_badkey.status_code == 403)
        # No key (same-origin / first-party) → unchanged behavior (200, no CORS).
        r_nokey = c.get("/api/chatbot-settings")
        check("no-key same-origin unchanged (200, no CORS header)",
              r_nokey.status_code == 200
              and "Access-Control-Allow-Origin" not in r_nokey.headers)
        # CORS preflight answered.
        r_pre = c.open("/api/chat", method="OPTIONS",
                       headers={"X-Embed-Key": "pk_probe", "Origin": "https://shop.example"})
        check("CORS preflight answered (204)", r_pre.status_code == 204)
        # Loader served.
        r_loader = c.get("/embed/loader.js")
        check("/embed/loader.js served as javascript",
              r_loader.status_code == 200 and "javascript" in r_loader.headers.get("Content-Type", ""))
        # Admin embed-keys CRUD is registered + protected.
        check("embed-keys admin route requires auth",
              c.get("/admin/api/embed-keys").status_code == 401)
        # Widget assets the loader pulls are served.
        r_w = c.get("/widget/chat-ui.js")
        check("/widget/chat-ui.js served as javascript",
              r_w.status_code == 200 and "javascript" in r_w.headers.get("Content-Type", ""))
        check("/widget/chat-ui.css served", c.get("/widget/chat-ui.css").status_code == 200)
        check("/widget rejects unknown file",
              c.get("/widget/secrets.py").status_code == 404)

        # ===== WordPress-embedded admin SSO =====
        import base64 as _b64m, hashlib as _hm, hmac as _hmacm, json as _jm
        import secrets as _secm, time as _tm

        def _mint(tid, secret, ttl=45, jti=None):
            payload = {"tid": tid, "exp": int(_tm.time()) + ttl,
                       "jti": jti or _secm.token_hex(16)}
            b64 = _b64m.urlsafe_b64encode(
                _jm.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=").decode()
            sig = _b64m.urlsafe_b64encode(
                _hmacm.new(secret.encode(), b64.encode(), _hm.sha256).digest()
            ).rstrip(b"=").decode()
            return b64 + "." + sig

        check("sso_used_jtis table exists",
              monolith.query_db("SELECT to_regclass('public.sso_used_jtis') AS t",
                                fetchone=True).get("t") is not None)
        # Valid token logs in (302 → /admin) and establishes the session.
        sso_c = monolith.app.test_client()
        tok = _mint(1, "ssosecret")
        r_sso = sso_c.get("/admin/sso?token=" + tok)
        check("valid SSO token -> 302 redirect", r_sso.status_code in (301, 302))
        check("SSO establishes admin session", sso_c.get("/admin").status_code == 200)
        # Replaying the SAME token is rejected (single-use jti).
        check("SSO replay (same token) -> 403",
              monolith.app.test_client().get("/admin/sso?token=" + tok).status_code == 403)
        # Forged signature -> 403.
        check("SSO forged token -> 403",
              monolith.app.test_client().get("/admin/sso?token=" + tok.split(".")[0]
                                             + ".bogus").status_code == 403)
        # Expired token -> 403.
        check("SSO expired token -> 403",
              monolith.app.test_client().get(
                  "/admin/sso?token=" + _mint(1, "ssosecret", ttl=-10)).status_code == 403)

    finally:
        try:
            srv.cleanup()
        except Exception:
            pass

    print(f"\n[probe] {len(passed)} passed, {len(failed)} failed")
    if failed:
        print("[probe] FAILURES: " + ", ".join(failed))
        raise SystemExit(1)
    print("[probe] ALL GREEN")


if __name__ == "__main__":
    main()
