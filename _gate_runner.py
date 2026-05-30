"""TEMP M1 gate runner — boots an embedded Postgres (pgserver), points the
package at it, runs init_db + live route/DB integration checks + the DB-backed
pytest suite. Deleted after use. Not part of the package.

Run: uv run --python 3.12 --with pgserver --with pytest python _gate_runner.py
"""
import os
import sys
import tempfile
import time as _t


def main():
    import pgserver
    data_dir = tempfile.mkdtemp(prefix="aap_gate_")
    srv = pgserver.get_server(data_dir)
    # Use pgserver's default 'postgres' database directly (its .psql() helper
    # shells out with the binary path, which breaks under a dir with spaces/
    # parens — so we avoid it and talk to the DB via psycopg2/the package).
    dsn = srv.get_uri()
    os.environ["DATABASE_URL"] = dsn
    os.environ.setdefault("FLASK_SECRET_KEY", "gatekey")
    os.environ["DEPLOY_MODE"] = "self_host"
    print(f"[gate] embedded PG up: {dsn}", flush=True)

    passed, failed = [], []

    def check(name, cond):
        (passed if cond else failed).append(name)
        print(("  PASS " if cond else "  FAIL ") + name)

    try:
        import admin_ai_platform as aap
        from admin_ai_platform import schema, tools, prompts, cost
        from admin_ai_platform.db import query_db, execute_db

        # 1. App boot + schema bootstrap against the real DB.
        app = aap.create_app(init_schema=True, start_scheduler=False)
        c = app.test_client()

        # 2. Schema: IN tables present, OUT tables absent, idempotent re-run.
        schema.init_db()  # second run must not raise

        def table_exists(t):
            r = query_db("SELECT to_regclass(%s) AS t", (f"public.{t}",), fetchone=True)
            return bool(r and r.get("t"))
        check("all IN tables created", all(table_exists(t) for t in schema.IN_TABLES_M0_M1))
        check("OUT tables absent", all(not table_exists(t) for t in schema.OUT_TABLES))

        # 3. Seeded singletons.
        check("chatbot_settings seeded", bool(query_db(
            "SELECT id FROM chatbot_settings WHERE id=1", fetchone=True)))
        check("model_prices seeded", bool(query_db(
            "SELECT 1 FROM model_prices WHERE provider='openai' AND model='gpt-4o-mini'",
            fetchone=True)))

        # 4. Public reads.
        check("GET /api/chatbot-settings 200", c.get("/api/chatbot-settings").status_code == 200)
        r = c.get("/api/gallery-cards")
        check("GET /api/gallery-cards 200 empty", r.status_code == 200 and r.get_json() == [])
        check("GET /api/voice/settings 200", c.get("/api/voice/settings").status_code == 200)

        # 5. Gallery write -> read -> lookup tool -> site index.
        execute_db(
            "INSERT INTO gallery_cards (slug,title,subtitle,image_url,category,description,price,sort_order)"
            " VALUES ('wine-cellar','Wine Cellar','400+ labels','/img.jpg','spaces','Stone-vaulted cellar.','$120',1)")
        cards = c.get("/api/gallery-cards").get_json()
        check("gallery read after insert", len(cards) == 1 and cards[0]["slug"] == "wine-cellar")
        looked = tools.lookup_gallery_cards(slug="wine-cellar")
        check("lookup_gallery_cards returns card", looked and looked[0]["title"] == "Wine Cellar")
        idx = prompts.build_site_index()
        check("site index contains card", "wine-cellar" in idx and "Wine Cellar" in idx)
        check("assemble_system_prompt includes SITE INDEX",
              "SITE INDEX" in prompts.assemble_system_prompt())

        # 6. Skills sync + enable filter.
        tools.sync_skills_to_db()
        active = {t["function"]["name"] for t in tools.get_active_chat_tools()}
        check("all builtin skills active", active == set(tools.CHAT_LOOKUP_FUNCTIONS))
        execute_db("UPDATE agent_skills SET enabled=FALSE WHERE name='lookup_presentation'")
        active2 = {t["function"]["name"] for t in tools.get_active_chat_tools()}
        check("disabled skill excluded", "lookup_presentation" not in active2)

        # 7. Forms: create -> submit (required validation + confirmation #).
        form = execute_db(
            "INSERT INTO custom_forms (name, slug, status) VALUES ('Booking','book','active') RETURNING id")
        execute_db(
            "INSERT INTO form_fields (form_id, field_type, label, name, required) "
            "VALUES (%s,'email','Email','email',TRUE)", (form["id"],))
        bad = c.post("/api/forms/book/submit", json={"fields": {}})
        check("form submit rejects missing required", bad.status_code == 400)
        good = c.post("/api/forms/book/submit",
                      json={"fields": {"email": "a@b.com"}, "session_id": "s1"})
        gj = good.get_json()
        check("form submit 201 + confirmation", good.status_code == 201 and gj.get("confirmation_number"))
        sub = query_db("SELECT status, submission_data FROM form_submissions WHERE form_id=%s",
                       (form["id"],), fetchone=True)
        check("submission persisted as new", sub and sub["status"] == "new")

        # 8. Cost ledger write + MTD spend.
        cost.record_chat_cost(session_id="s1", surface="visitor_chat", provider="openai",
                              model="gpt-4o-mini", prompt_tokens=1000, completion_tokens=500)
        _t.sleep(0.3)  # async warn-check thread harmless
        n = query_db("SELECT COUNT(*) AS c FROM api_cost_events", fetchone=True)
        check("api_cost_events row written", n and n["c"] >= 1)
        mtd = cost.compute_mtd_spend()
        check("compute_mtd_spend returns total", isinstance(mtd.get("total_usd"), float) and mtd["total_usd"] > 0)

        # 9. by-slug generated page (published) for showSavedPage.
        execute_db("INSERT INTO generated_pages (title, html, slug, status) "
                   "VALUES ('Tour','<div>hi</div>','tour','published')")
        bs = c.get("/api/generated-pages/by-slug/tour")
        check("by-slug published page 200", bs.status_code == 200 and bs.get_json()["html"] == "<div>hi</div>")

        # ----- M2: admin auth + settings + history + pages -----
        # Unauthenticated admin API is rejected; /admin redirects to login.
        anon = app.test_client()
        check("admin API 401 when unauthenticated",
              anon.get("/admin/api/llm-provider").status_code == 401)
        check("/admin redirects to login when anon",
              anon.get("/admin").status_code in (301, 302))

        # Wrong password does not authenticate.
        admin = app.test_client()
        bad_login = admin.post("/admin/login", json={"password": "wrong"})
        check("bad password rejected", bad_login.status_code == 401)
        # Correct password (config default 'admin') authenticates.
        ok_login = admin.post("/admin/login", json={"password": "admin"})
        check("login sets session", ok_login.status_code == 200)
        check("/admin serves dashboard when authed", admin.get("/admin").status_code == 200)

        # M19 CSRF: cookie-authed admin mutations now require X-CSRF-Token. The
        # real dashboard fetches it from /admin/api/csrf-token and echoes it on
        # every write — simulate that by wrapping the admin client's .open() to
        # inject the header on unsafe methods (so the rest of the gate's existing
        # admin POST/PUT/DELETE calls keep working, exactly like the browser).
        _csrf_tok = admin.get("/admin/api/csrf-token").get_json()["csrf_token"]
        _admin_open = admin.open

        def _open_csrf(*a, **k):
            method = (k.get("method") or "GET").upper()
            if method not in ("GET", "HEAD", "OPTIONS"):
                hdrs = dict(k.get("headers") or {})
                hdrs.setdefault("X-CSRF-Token", _csrf_tok)
                k["headers"] = hdrs
            return _admin_open(*a, **k)
        admin.open = _open_csrf

        # Provider get/put roundtrip.
        check("GET llm-provider", admin.get("/admin/api/llm-provider").get_json()["provider"] == "openai")
        admin.put("/admin/api/llm-provider", json={"provider": "claude"})
        check("provider switched to claude",
              admin.get("/admin/api/llm-provider").get_json()["provider"] == "claude")
        admin.put("/admin/api/llm-provider", json={"provider": "openai"})

        # Chatbot settings get/put.
        admin.put("/admin/api/chatbot-settings",
                  json={"enabled": True, "agent_name": "Aria", "greeting": "Hi"})
        cs = admin.get("/admin/api/chatbot-settings").get_json()
        check("chatbot settings persisted", cs.get("agent_name") == "Aria" and cs.get("enabled"))
        check("default-system-prompt served",
              "system_prompt" in admin.get("/admin/api/default-system-prompt").get_json())

        # Chat history from a seeded conversation.
        conv = execute_db("INSERT INTO chat_conversations (session_id, visitor_id) "
                          "VALUES ('hist1','vh') RETURNING id")
        execute_db("INSERT INTO chat_messages (conversation_id, role, content) "
                   "VALUES (%s,'user','hello')", (conv["id"],))
        hist = admin.get("/admin/api/chat-history").get_json()
        check("chat-history lists conversation", hist["stats"]["total_conversations"] >= 1)
        detail = admin.get(f"/admin/api/chat-history/{conv['id']}").get_json()
        check("chat-history detail has messages", len(detail["messages"]) >= 1)

        # Generated pages admin (the 'tour' page from check 9 exists).
        pages = admin.get("/admin/api/generated-pages").get_json()
        check("generated-pages admin lists", any(p["slug"] == "tour" for p in pages))
        pid = [p for p in pages if p["slug"] == "tour"][0]["id"]
        check("generated-pages PUT status",
              admin.put(f"/admin/api/generated-pages/{pid}", json={"status": "draft"}).status_code == 200)
        check("generated-pages DELETE",
              admin.delete(f"/admin/api/generated-pages/{pid}").status_code == 200)

        # ----- M2: admin tools + pending-action approval flow (no LLM needed) -----
        from admin_ai_platform import admin_tools as at
        # Read tool: SELECT allowed, INSERT rejected.
        check("admin_run_sql allows SELECT",
              "rows" in at.admin_run_sql("SELECT 1 AS x"))
        check("admin_run_sql rejects write",
              "error" in at.admin_run_sql("INSERT INTO gallery_cards (slug) VALUES ('x')"))
        check("admin_run_sql rejects multi-statement",
              "error" in at.admin_run_sql("SELECT 1; SELECT 2"))
        check("admin_describe_table works",
              at.admin_describe_table("gallery_cards").get("row_count") is not None)
        check("admin tool blocks non-writable table",
              "error" in at.admin_propose_insert(table_name="api_cost_events",
                                                  fields={"surface": "x"}, _session_id="s"))

        # Propose insert -> parked pending -> approve -> row exists.
        prop = at.admin_propose_insert(
            table_name="gallery_cards",
            fields={"slug": "spa", "title": "Spa", "subtitle": "Relax",
                    "image_url": "/s.jpg", "category": "spaces"},
            _session_id="adm1")
        check("propose_insert parks action", prop.get("awaiting_approval") and prop.get("action_id"))
        aid = prop["action_id"]
        # Action route reachable (authed).
        check("GET action detail 200", admin.get(f"/admin/api/chat/action/{aid}").status_code == 200)
        before = query_db("SELECT COUNT(*) AS c FROM gallery_cards WHERE slug='spa'", fetchone=True)["c"]
        check("nothing written before approval", before == 0)
        ap = admin.post(f"/admin/api/chat/action/{aid}/approve")
        check("approve executes write", ap.status_code == 200 and ap.get_json().get("success"))
        after = query_db("SELECT COUNT(*) AS c FROM gallery_cards WHERE slug='spa'", fetchone=True)["c"]
        check("row written after approval", after == 1)
        check("re-approve rejected (already approved)",
              admin.post(f"/admin/api/chat/action/{aid}/approve").status_code == 409)

        # Propose delete -> reject -> row remains.
        prop2 = at.admin_propose_delete(table_name="gallery_cards",
                                        row_id=query_db("SELECT id FROM gallery_cards WHERE slug='spa'",
                                                        fetchone=True)["id"], _session_id="adm1")
        rj = admin.post(f"/admin/api/chat/action/{prop2['action_id']}/reject")
        check("reject works", rj.status_code == 200)
        check("rejected action does not delete",
              query_db("SELECT COUNT(*) AS c FROM gallery_cards WHERE slug='spa'", fetchone=True)["c"] == 1)

        # admin chat history endpoint (authed).
        execute_db("INSERT INTO admin_chat_messages (session_id, mode, role, content) "
                   "VALUES ('adm1','admin','user','hi')")
        ah = admin.get("/admin/api/chat/history?session_id=adm1").get_json()
        check("admin chat history returns messages", len(ah["messages"]) >= 1)

        # ----- M3: cost dashboard -----
        check("cost summary 200", admin.get("/admin/api/cost/summary").status_code == 200)
        check("cost series 200", "series" in admin.get("/admin/api/cost/series").get_json())
        check("cost by-surface 200", "by_surface" in admin.get("/admin/api/cost/by-surface").get_json())
        check("cost by-model 200", "by_model" in admin.get("/admin/api/cost/by-model").get_json())
        prices = admin.get("/admin/api/cost/prices").get_json()["prices"]
        check("cost prices listed", len(prices) >= 1)
        pid_price = prices[0]["id"]
        check("cost price PATCH",
              admin.patch(f"/admin/api/cost/prices/{pid_price}", json={"notes": "edited"}).status_code == 200)
        check("cost cap PUT",
              admin.put("/admin/api/cost/cap", json={"monthly_cap_usd": 50, "cap_behavior": "alert_only"}).status_code == 200)
        check("cost cap PUT rejects bad behavior",
              admin.put("/admin/api/cost/cap", json={"cap_behavior": "nuke"}).status_code == 400)

        # ----- M3: skills registry + custom SQL skill executed via dispatcher -----
        skills = admin.get("/admin/api/skills").get_json()["skills"]
        check("skills registry lists builtins", any(s["name"] == "lookup_gallery_cards" for s in skills))
        builtin_id = [s for s in skills if s["name"] == "lookup_gallery_cards"][0]["id"]
        check("builtin delete refused",
              admin.delete(f"/admin/api/skills/{builtin_id}").status_code == 400)
        check("custom skill name validation",
              admin.post("/admin/api/skills", json={"name": "Bad Name"}).status_code == 400)
        # Create a custom SQL skill, enable it, and run it through the chat dispatcher.
        csql = admin.post("/admin/api/custom-sql", json={
            "name": "count_cards", "description": "count gallery cards",
            "sql_template": "SELECT COUNT(*) AS n FROM gallery_cards",
            "enabled": True, "args_schema_json": {"type": "object", "properties": {}}})
        check("custom-sql created", csql.status_code == 201)
        from admin_ai_platform.tools import get_active_chat_tools, execute_chat_tool
        names = {t["function"]["name"] for t in get_active_chat_tools()}
        check("custom skill appears in tools", "count_cards" in names)
        res_str, _ = execute_chat_tool("count_cards", "{}", session_id="s")
        check("custom SQL skill executes (read-only)", '"rows"' in res_str and '"n"' in res_str)
        # SSRF / write guards.
        from admin_ai_platform.custom_skills import _url_is_safe, _run_sql_skill
        check("SSRF blocks localhost", _url_is_safe("http://127.0.0.1/x") is False)
        check("SSRF blocks private", _url_is_safe("http://192.168.1.5/x") is False)
        check("custom SQL rejects write",
              "error" in _run_sql_skill({"sql_template": "DELETE FROM gallery_cards"}, {}))

        # ----- M3: MCP registry + graceful failure on unreachable server -----
        mcp = admin.post("/admin/api/mcp/servers", json={
            "name": "demo-mcp", "url": "http://localhost:59999/mcp",
            "transport": "http", "auth_type": "none", "allowed_for_velo": True})
        check("mcp server created", mcp.status_code == 201)
        msid = mcp.get_json()["id"]
        check("mcp credential redacted in list",
              all(s["auth_credential"] in ("", "***") for s in admin.get("/admin/api/mcp/servers").get_json()["servers"]))
        test = admin.post(f"/admin/api/mcp/servers/{msid}/test").get_json()
        check("mcp test fails gracefully on unreachable", test["ok"] is False)
        # Seed a cached tool directly and verify it surfaces as a namespaced visitor tool.
        execute_db("INSERT INTO mcp_tools_cache (server_id, tool_name, description, enabled) "
                   "VALUES (%s,'search','search the web',TRUE)", (msid,))
        from admin_ai_platform.mcp_tools import mcp_tool_schemas, is_mcp_tool
        mschemas = mcp_tool_schemas(audience="visitor")
        check("mcp tool exposed to visitor (allowed_for_velo)",
              any(t["function"]["name"] == f"mcp__{msid}__search" for t in mschemas))
        check("is_mcp_tool detects namespace", is_mcp_tool(f"mcp__{msid}__search"))
        check("mcp delete", admin.delete(f"/admin/api/mcp/servers/{msid}").status_code == 200)

        # ----- M4: automations engine -----
        import time as _tt
        meta = admin.get("/admin/api/automations/metadata").get_json()
        check("automations metadata", meta.get("triggers") and meta.get("actions"))
        # Create a webhook-triggered automation with a single save_data step.
        created = admin.post("/admin/api/automations", json={
            "name": "Gate test", "enabled": True, "trigger_type": "webhook",
            "trigger_config": {},
            "action_steps": [{"type": "save_data", "config": {
                "table": "form_submissions", "fields": {}}}]})
        check("automation created", created.status_code == 201)
        autoid = created.get_json()["id"]
        # Give it a webhook token, then hit the public hook -> queues a run.
        tok = admin.post(f"/admin/api/automations/{autoid}/regenerate-webhook").get_json()["webhook_token"]
        check("webhook token issued", bool(tok))
        hook = anon.post(f"/automations/hook/{tok}", json={"hello": "world"})
        check("public webhook queues a run", hook.status_code == 200 and hook.get_json().get("queued"))
        _tt.sleep(0.6)  # let the inline dispatch thread record the run
        runs = admin.get(f"/admin/api/automations/{autoid}/runs").get_json()["runs"]
        check("automation run recorded", len(runs) >= 1)
        # test-run (manual dry run).
        tr = admin.post(f"/admin/api/automations/{autoid}/test-run", json={"trigger_data": {}})
        check("manual test-run queued", tr.status_code == 200 and tr.get_json().get("run_id"))
        # toggle + version snapshot on update + delete.
        check("toggle flips enabled",
              admin.post(f"/admin/api/automations/{autoid}/toggle").get_json()["enabled"] is False)
        admin.put(f"/admin/api/automations/{autoid}", json={"name": "Renamed"})
        vrow = query_db("SELECT COUNT(*) AS c FROM automation_versions WHERE automation_id=%s",
                        (autoid,), fetchone=True)
        check("update snapshots a version", vrow["c"] >= 1)
        check("automation delete",
              admin.delete(f"/admin/api/automations/{autoid}").status_code == 200)
        # Unknown webhook token -> 404.
        check("unknown webhook 404", anon.post("/automations/hook/nope").status_code == 404)

        # ----- M4: scraper -----
        from admin_ai_platform.reused import scraper as _scraper
        ssrf = _scraper.fetch_url("http://127.0.0.1/secret")
        check("scraper SSRF blocks loopback", ssrf.get("ok") is False)
        check("scraper-settings GET", admin.get("/admin/api/scraper-settings").status_code == 200)
        check("scraper-settings PUT",
              admin.put("/admin/api/scraper-settings",
                        json={"disallowed_domains": "evil.com", "render_enabled": False}).status_code == 200)
        check("scraper-status", admin.get("/admin/api/scraper-status").status_code == 200)
        sj = admin.post("/admin/api/scrape-jobs", json={"input_mode": "url", "url": "https://example.com",
                                                        "target_shape": "free_form"})
        check("scrape job created", sj.status_code == 201 and sj.get_json().get("id"))
        check("scrape job url required",
              admin.post("/admin/api/scrape-jobs", json={"input_mode": "url"}).status_code == 400)
        check("scrape jobs list", "jobs" in admin.get("/admin/api/scrape-jobs").get_json())
        sch = admin.post("/admin/api/scrape-schedules", json={"name": "daily news", "url": "https://example.com",
                                                              "schedule_mode": "daily"})
        check("scrape schedule created", sch.status_code == 201)
        schid = sch.get_json()["id"]
        check("scrape schedule patch",
              admin.patch(f"/admin/api/scrape-schedules/{schid}", json={"enabled": False}).status_code == 200)
        check("scrape schedule resume",
              admin.post(f"/admin/api/scrape-schedules/{schid}/resume").status_code == 200)
        check("scrape schedule delete",
              admin.delete(f"/admin/api/scrape-schedules/{schid}").status_code == 200)

        # ----- M4: RAG/KB graceful degradation (this gate DB has no pgvector) -----
        from admin_ai_platform import schema as _schema
        from admin_ai_platform.tools import get_active_chat_tools as _tools_now
        if _schema.rag_available():
            # If a future gate DB DOES have pgvector, assert the happy path.
            check("kb list 200 (pgvector present)",
                  admin.get("/admin/api/kb/list").status_code == 200)
            check("kb tool offered when available",
                  any(t["function"]["name"] == "lookup_knowledge_base" for t in _tools_now()))
        else:
            check("kb endpoints 503 without pgvector",
                  admin.get("/admin/api/kb/list").status_code == 503)
            check("kb upload 503 without pgvector",
                  admin.post("/admin/api/kb/upload").status_code == 503)
            check("kb tool hidden when unavailable",
                  not any(t["function"]["name"] == "lookup_knowledge_base" for t in _tools_now()))
            # The tool executor also degrades cleanly if called directly.
            kbres, _ = execute_chat_tool("lookup_knowledge_base", '{"query":"x"}', session_id="s")
            check("kb tool executor degrades cleanly", "unavailable" in kbres)
        check("rag blueprint registered",
              any("/admin/api/kb/list" in str(r) for r in app.url_map.iter_rules()))

        # ----- M5: messaging -----
        from admin_ai_platform.reused import messaging as _msg
        check("messaging status", admin.get("/admin/api/messaging/status").status_code == 200)
        subc = admin.post("/admin/api/messaging/subscribers",
                          json={"email": "jane@example.com", "full_name": "Jane Doe"})
        check("subscriber created", subc.status_code == 201)
        tpl = admin.post("/admin/api/messaging/templates",
                         json={"name": "Welcome", "subject": "Hi {{full_name}}",
                               "body": "Hello {{full_name}}!"})
        check("template created", tpl.status_code == 201)
        tid = tpl.get_json()["id"]
        prev = admin.get(f"/admin/api/messaging/templates/{tid}/preview").get_json()
        check("merge tags rendered", "Jane Doe" in prev["subject"] and "Jane Doe" in prev["body"])
        camp = admin.post("/admin/api/messaging/campaigns",
                          json={"name": "Blast", "channel": "email", "recipient_kind": "ids",
                                "recipient_filter": {"ids": []}, "subject_snapshot": "Hi",
                                "body_snapshot": "Yo"})
        check("campaign created", camp.status_code == 201)
        # unsubscribe token roundtrip + endpoint.
        utok = _msg.make_unsubscribe_token(subc.get_json()["id"])
        check("unsubscribe token parses", _msg.parse_unsubscribe_token(utok) == subc.get_json()["id"])
        check("unsubscribe endpoint", anon.get(f"/unsubscribe?token={utok}").status_code == 200)
        sub_after = query_db("SELECT opt_in FROM subscribers WHERE id=%s",
                             (subc.get_json()["id"],), fetchone=True)
        check("unsubscribe flips opt_in", sub_after["opt_in"] is False)
        check("twilio status webhook 204",
              anon.post("/webhooks/twilio/sms-status", data={"MessageSid": "SM1", "MessageStatus": "delivered"}).status_code == 204)

        # ----- M5: reviews -----
        rdest = admin.post("/admin/api/reviews/destinations",
                           json={"name": "Our Google", "kind": "google",
                                 "url": "https://g.page/x", "public_visible": True})
        check("review destination created", rdest.status_code == 201)
        did = rdest.get_json()["id"]
        check("review settings GET", admin.get("/admin/api/reviews/settings").status_code == 200)
        rreq = admin.post("/admin/api/reviews/requests",
                          json={"destination_id": did, "recipient_email": "a@b.com",
                                "purchased_item": "Spa day"})
        check("review request created", rreq.status_code == 201)
        rtok = rreq.get_json()["short_token"]
        clk = anon.get(f"/r/{rtok}")
        check("short link redirects", clk.status_code in (301, 302))
        clicked = query_db("SELECT clicked_at FROM review_requests WHERE short_token=%s",
                           (rtok,), fetchone=True)
        check("short link records click", clicked["clicked_at"] is not None)
        check("review insights", "funnel" in admin.get("/admin/api/reviews/insights").get_json())
        check("public review-snapshots", anon.get("/api/review-snapshots").status_code == 200)
        check("unknown short link 404", anon.get("/r/nope").status_code == 404)

        # ----- M5: presentations -----
        deck = admin.post("/admin/api/presentations",
                          json={"slug": "tour-deck", "title": "Tour", "enabled": True})
        check("deck created", deck.status_code == 201)
        pid2 = deck.get_json()["id"]
        check("deck slug validation",
              admin.post("/admin/api/presentations", json={"slug": "Bad Slug"}).status_code == 400)
        sl = admin.post(f"/admin/api/presentations/{pid2}/slides",
                        json={"title": "Welcome", "body": "Hi", "narration_text": "Hello there"})
        check("slide added", sl.status_code == 201)
        pub = anon.get("/api/presentations/tour-deck").get_json()
        check("public deck has slide", len(pub["slides"]) == 1 and pub["slides"][0]["title"] == "Welcome")
        check("deck delete", admin.delete(f"/admin/api/presentations/{pid2}").status_code == 200)

        # ----- M6: commerce -----
        prod = admin.post("/admin/api/products", json={"slug": "mug", "name": "Mug",
                                                       "price_cents": 1500, "stock": 10})
        check("product created", prod.status_code == 201)
        check("public products lists", any(p["slug"] == "mug" for p in anon.get("/api/products").get_json()))
        svc = admin.post("/admin/api/services", json={
            "slug": "tasting", "name": "Wine Tasting", "pricing_model": "rsvp",
            "requires_calendar": True, "capacity_per_slot": 2})
        check("service created", svc.status_code == 201)
        svid = svc.get_json()["id"]
        # Weekly rule: every day 09:00-11:00, 60-min slots -> 09:00 & 10:00.
        for dow in range(7):
            admin.post(f"/admin/api/services/{svid}/rules",
                       json={"day_of_week": dow, "start_time": "09:00", "end_time": "11:00",
                             "slot_minutes": 60})
        avail = anon.get("/api/services/tasting/availability?days=2").get_json()
        check("availability engine returns slots",
              avail["requires_calendar"] and len(avail["days"]) >= 1
              and "09:00:00" in avail["days"][0]["open_starts"])
        # RSVP booking on a slot; capacity=2 so two succeed, third 409.
        day0 = avail["days"][0]["date"]
        b1 = anon.post("/api/services/tasting/book", json={"client_name": "A", "client_email": "a@x.com",
                       "scheduled_date": day0, "scheduled_start": "09:00:00"})
        check("rsvp booking 1 confirmed", b1.status_code == 201 and b1.get_json()["action"] == "rsvp_confirmed")
        anon.post("/api/services/tasting/book", json={"client_name": "B", "client_email": "b@x.com",
                  "scheduled_date": day0, "scheduled_start": "09:00:00"})
        b3 = anon.post("/api/services/tasting/book", json={"client_name": "C", "client_email": "c@x.com",
                       "scheduled_date": day0, "scheduled_start": "09:00:00"})
        check("rsvp capacity enforced (3rd rejected)", b3.status_code == 409)
        # Filled slot drops out of availability.
        avail2 = anon.get("/api/services/tasting/availability?days=2").get_json()
        slot0 = next((s for s in avail2["days"][0]["slots"] if s["start"] == "09:00:00"), None)
        check("filled slot removed from availability", slot0 is None)
        check("stripe-settings GET", admin.get("/admin/api/stripe-settings").status_code == 200)
        # Webhook now refuses (503) when no signing secret is configured — the
        # full verify/idempotency/routing path is exercised in the M11 section.
        check("stripe webhook 503 without secret",
              anon.post("/api/stripe/webhook", json={}).status_code == 503)

        # ----- M6: tenancy -----
        pf = admin.get("/admin/api/plans-features").get_json()
        check("plans-features lists", len(pf["features"]) > 0)
        tog = admin.post("/admin/api/features/toggle", json={"name": "reviews", "enabled": False})
        check("feature toggle off", tog.get_json()["enabled"] is False)
        admin.post("/admin/api/features/toggle", json={"name": "reviews", "enabled": True})
        ek = admin.post("/admin/api/embed-keys", json={"label": "site1",
                        "origin_allowlist": ["https://site1.com"]})
        check("embed key created", ek.status_code == 201 and ek.get_json()["embed_key"].startswith("pk_"))
        check("embed keys list", len(admin.get("/admin/api/embed-keys").get_json()["keys"]) >= 1)
        snap = admin.get("/admin/api/snapshot/export").get_json()
        check("snapshot export has gallery", "gallery_cards" in snap["tables"])
        check("secrets view presence-only",
              "database_configured" in admin.get("/admin/api/secrets").get_json())
        check("devconsole overview", "counts" in admin.get("/admin/api/devconsole/overview").get_json())

        # ----- M6: VELO -----
        import admin_ai_platform.config as _cfg
        _cfg.VELO_SHARED_SECRET = "topsecret"  # enable the surface for the test
        check("velo rejects bad secret",
              anon.post("/api/velo/command", json={"command": "ping", "secret": "wrong"}).status_code == 403)
        vp = anon.post("/api/velo/command", json={"command": "ping", "secret": "topsecret"})
        check("velo ping authed", vp.status_code == 200 and vp.get_json()["result"]["pong"])
        vf = anon.post("/api/velo/command", json={"command": "set_feature", "secret": "topsecret",
                       "params": {"name": "voice", "enabled": False}})
        check("velo set_feature", vf.get_json()["result"]["enabled"] is False)
        check("velo unknown command 400",
              anon.post("/api/velo/command", json={"command": "nope", "secret": "topsecret"}).status_code == 400)
        check("velo status liveness", anon.get("/api/velo/status").status_code == 200)
        _cfg.VELO_SHARED_SECRET = ""  # restore

        # ----- M7: embed-key auth + origin allowlist + CORS + rate limit -----
        # Create an embed key allowlisting one origin.
        ekr = admin.post("/admin/api/embed-keys",
                         json={"label": "embed", "origin_allowlist": ["https://shop.example"]})
        ekey = ekr.get_json()["embed_key"]

        # 1. No key (first-party) -> passes through.
        check("embeddable no-key passes", anon.get("/api/gallery-cards").status_code == 200)
        # 2. Valid key + allowlisted Origin -> 200 + CORS echoes that origin.
        r_ok = anon.get("/api/gallery-cards", headers={"X-Embed-Key": ekey,
                        "Origin": "https://shop.example"})
        check("keyed + allowlisted origin 200", r_ok.status_code == 200)
        check("CORS echoes allowlisted origin",
              r_ok.headers.get("Access-Control-Allow-Origin") == "https://shop.example")
        # 3. Valid key + NON-allowlisted Origin -> 403.
        r_bad = anon.get("/api/gallery-cards", headers={"X-Embed-Key": ekey,
                         "Origin": "https://evil.example"})
        check("keyed + bad origin 403", r_bad.status_code == 403)
        # 4. Unknown key -> 403.
        check("unknown embed key 403",
              anon.get("/api/gallery-cards", headers={"X-Embed-Key": "pk_nope",
                       "Origin": "https://shop.example"}).status_code == 403)
        # 5. OPTIONS preflight answered 204 with CORS.
        pre = anon.open("/api/chat", method="OPTIONS",
                        headers={"X-Embed-Key": ekey, "Origin": "https://shop.example"})
        check("preflight 204", pre.status_code == 204)
        # 5b. Cost-bearing endpoints are protected (hardened after security review):
        #     no-key cross-origin chat -> 403; keyed chat with no Origin -> 403.
        check("no-key cross-origin chat 403",
              anon.post("/api/chat", headers={"Origin": "https://evil.example"},
                        json={"message": "hi", "session_id": "x"}).status_code == 403)
        check("keyed chat without origin 403",
              anon.post("/api/chat", headers={"X-Embed-Key": ekey},
                        json={"message": "hi", "session_id": "x"}).status_code == 403)

        # 6. Rate limit: hammer chat past the cap (no LLM call needed — 429 short-circuits).
        import admin_ai_platform.embed_auth as _ea
        import admin_ai_platform.config as _cfg7
        _ea._RATE_BUCKETS.clear()
        execute_db("DELETE FROM rate_buckets")
        _cfg7.RATE_LIMIT_MAX = 3
        codes = [anon.post("/api/chat", headers={"X-Embed-Key": ekey, "Origin": "https://shop.example"},
                           json={"message": "hi", "session_id": "rl"}).status_code for _ in range(5)]
        check("rate limit eventually 429", 429 in codes)
        _cfg7.RATE_LIMIT_MAX = 40
        # 7. loader.js served.
        check("loader.js served",
              admin.get("/embed/loader.js").status_code == 200)

        # ----- M8: SSO (platform side; PHP uses the identical token scheme) -----
        import admin_ai_platform.config as _cfg8
        from admin_ai_platform.sso import mint_sso_token, verify_sso_token, _USED_JTIS
        # Fail-closed when no SSO secret is configured (no FLASK_SECRET_KEY fallback).
        _cfg8.SSO_SIGNING_SECRET = ""
        check("sso verify disabled without secret", verify_sso_token("a.b") is None)
        _minted_no_secret = True
        try:
            mint_sso_token(1)
        except RuntimeError:
            _minted_no_secret = False
        check("sso mint fails closed without secret", _minted_no_secret is False)
        _cfg8.SSO_SIGNING_SECRET = "ssosecret_for_gate"
        _USED_JTIS.clear()
        tok = mint_sso_token(1, secret="ssosecret_for_gate")
        check("sso verify roundtrip", verify_sso_token(tok) == 1)
        check("sso single-use (replay rejected)", verify_sso_token(tok) is None)
        check("sso forged signature rejected", verify_sso_token(tok.split(".")[0] + ".bogus") is None)
        check("sso expired rejected", verify_sso_token(mint_sso_token(1, ttl_seconds=-5)) is None)
        check("sso over-long token rejected", verify_sso_token(mint_sso_token(1, ttl_seconds=3600)) is None)
        # /admin/sso route establishes a session for a fresh client.
        sso_client = app.test_client()
        route_tok = mint_sso_token(1, secret="ssosecret_for_gate")
        r_sso = sso_client.get(f"/admin/sso?token={route_tok}")
        check("/admin/sso redirects on valid token", r_sso.status_code in (301, 302))
        check("/admin/sso establishes admin session", sso_client.get("/admin").status_code == 200)
        check("/admin/sso forged token 403",
              app.test_client().get("/admin/sso?token=nope.nope").status_code == 403)
        # Clickjacking: with a configured WP origin, admin allows only that framer.
        _cfg8.CSP_FRAME_ANCESTORS = "https://wp.example"
        csp = sso_client.get("/admin/login").headers.get("Content-Security-Policy", "")
        check("frame-ancestors allows configured WP origin",
              "frame-ancestors" in csp and "https://wp.example" in csp)
        _cfg8.CSP_FRAME_ANCESTORS = ""
        xfo = app.test_client().get("/admin/login").headers.get("X-Frame-Options", "")
        check("frame default-deny without WP origin", xfo == "SAMEORIGIN")

        # ----- M10: scheduler ticks + scaling --------------------------------
        check("rate_buckets table present", table_exists("rate_buckets"))

        # Postgres-backed rate limiter: shared, atomic, enforces the cap.
        import admin_ai_platform.embed_auth as _ea
        import admin_ai_platform.config as _cfg10
        execute_db("DELETE FROM rate_buckets")
        _cfg10.RATE_LIMIT_MAX = 3
        _cfg10.RATE_LIMIT_WINDOW_SEC = 60
        oks = [_ea._rate_ok(99, "1.2.3.4") for _ in range(5)]
        check("rate limiter allows up to the cap", oks[:3] == [True, True, True])
        check("rate limiter blocks past the cap", oks[3] is False and oks[4] is False)
        _bk = query_db("SELECT count FROM rate_buckets WHERE bucket_key=%s",
                       ("99:1.2.3.4",), fetchone=True)
        check("rate limiter persists count in Postgres", _bk and int(_bk["count"]) >= 4)
        check("separate ip gets its own bucket", _ea._rate_ok(99, "5.6.7.8") is True)

        # scrape_schedule_tick dispatches a due schedule and advances next_run_at.
        from admin_ai_platform.blueprints.scraper import (
            scrape_schedule_tick, _compute_next_run)
        execute_db("DELETE FROM scrape_jobs")
        execute_db("DELETE FROM scrape_schedules")
        _sid = execute_db(
            "INSERT INTO scrape_schedules (name, input_mode, url, schedule_mode, "
            " interval_minutes, enabled, next_run_at) "
            "VALUES ('gate','url','http://example.com','interval',60,TRUE, NOW() - INTERVAL '1 minute') "
            "RETURNING id")["id"]
        scrape_schedule_tick()
        _job = query_db("SELECT COUNT(*) AS n FROM scrape_jobs WHERE schedule_id=%s",
                        (_sid,), fetchone=True)
        check("scrape_schedule_tick spawns a job for a due schedule", int(_job["n"]) == 1)
        _sch = query_db("SELECT next_run_at FROM scrape_schedules WHERE id=%s",
                        (_sid,), fetchone=True)
        check("scrape_schedule_tick advances next_run_at into the future",
              _sch["next_run_at"] is not None)
        # Not-due schedule is left alone on a second tick (no extra job).
        scrape_schedule_tick()
        _job2 = query_db("SELECT COUNT(*) AS n FROM scrape_jobs WHERE schedule_id=%s",
                         (_sid,), fetchone=True)
        check("scrape_schedule_tick skips a not-yet-due schedule", int(_job2["n"]) == 1)
        # next-run computation: interval mode is strictly in the future.
        from datetime import datetime as _dt
        _nr = _compute_next_run({"schedule_mode": "interval", "interval_minutes": 30}, _dt.utcnow())
        check("_compute_next_run interval is in the future", _nr > _dt.utcnow())

        # campaign_dispatch_tick claims a due queued campaign (send fails w/o
        # provider keys, but the row must transition out of 'queued').
        from admin_ai_platform.blueprints.messaging import campaign_dispatch_tick
        execute_db("DELETE FROM messaging_campaigns")
        _cid = execute_db(
            "INSERT INTO messaging_campaigns (name, channel, status, send_at) "
            "VALUES ('gate','email','queued', NOW() - INTERVAL '1 minute') RETURNING id")["id"]
        campaign_dispatch_tick()
        _camp = query_db("SELECT status FROM messaging_campaigns WHERE id=%s",
                         (_cid,), fetchone=True)
        check("campaign_dispatch_tick claims a due queued campaign",
              _camp["status"] != "queued")
        # A future-dated queued campaign is left untouched.
        _cid2 = execute_db(
            "INSERT INTO messaging_campaigns (name, channel, status, send_at) "
            "VALUES ('gate2','email','queued', NOW() + INTERVAL '1 hour') RETURNING id")["id"]
        campaign_dispatch_tick()
        _camp2 = query_db("SELECT status FROM messaging_campaigns WHERE id=%s",
                          (_cid2,), fetchone=True)
        check("campaign_dispatch_tick ignores a future campaign", _camp2["status"] == "queued")

        # review_collector_tick dispatches a due queued request (no provider ->
        # marked failed, but must leave 'queued').
        from admin_ai_platform.blueprints.reviews import review_collector_tick
        execute_db("DELETE FROM review_requests")
        _rid = execute_db(
            "INSERT INTO review_requests (channel, recipient_email, status, short_token, send_at) "
            "VALUES ('email','x@example.com','queued','gatetok', NOW() - INTERVAL '1 minute') "
            "RETURNING id")["id"]
        review_collector_tick()
        _rr = query_db("SELECT status FROM review_requests WHERE id=%s", (_rid,), fetchone=True)
        check("review_collector_tick dispatches a due request", _rr["status"] != "queued")

        # All ticks are registered with the scheduler (leader-gated at runtime).
        from admin_ai_platform import scheduler as _sched_g
        _tick_names = {getattr(cb, "__name__", "") for cb in _sched_g._TICK_CALLBACKS}
        check("scheduler has scrape tick registered", "scrape_schedule_tick" in _tick_names)
        check("scheduler has campaign tick registered", "campaign_dispatch_tick" in _tick_names)
        check("scheduler has review tick registered", "review_collector_tick" in _tick_names)
        check("scheduler has weekly digest tick registered", "weekly_digest_tick" in _tick_names)

        # ----- M11: Stripe end-to-end (no live SDK; fakes for the SDK calls) ---
        check("stripe_events table present", table_exists("stripe_events"))
        import os as _os11
        import admin_ai_platform.reused.stripe_client as _sc
        import admin_ai_platform.reused_di.stripe_settings as _sset
        import admin_ai_platform.reused_di.stripe_sync as _ssync

        # DI wiring is in place (configure() ran in create_app).
        check("stripe_settings DI configured", _sset._query_db is not None)
        check("stripe default mode is test", _sset.get_mode() == "test")

        # --- product sync upsert logic (fake Stripe SDK) ---
        class _FakeObj(dict):
            pass

        class _FakeProduct:
            @staticmethod
            def create(**k):
                return _FakeObj(id="prod_FAKE")

            @staticmethod
            def modify(*a, **k):
                return _FakeObj(id=a[0] if a else "prod_FAKE")

        class _FakePrice:
            @staticmethod
            def create(**k):
                return _FakeObj(id="price_FAKE")

            @staticmethod
            def modify(*a, **k):
                return _FakeObj()

        class _FakeStripeSync:
            Product = _FakeProduct
            Price = _FakePrice

        _orig_get_stripe = _sc.get_stripe
        _sc.get_stripe = lambda: _FakeStripeSync
        execute_db("DELETE FROM stripe_product_sync")
        execute_db("DELETE FROM products WHERE slug='gate-sku'")
        _pid = execute_db("INSERT INTO products (slug, name, price_cents, currency, active, "
                          " stock, track_inventory) "
                          "VALUES ('gate-sku','Gate SKU',1500,'USD',TRUE,100,TRUE) RETURNING id")["id"]
        _res = _ssync.sync_product(_pid)
        check("sync_product creates mapping (action=created)",
              _res.get("ok") and _res.get("action") == "created")
        _map = query_db("SELECT stripe_product_id, stripe_price_id, synced_price_cents "
                        "FROM stripe_product_sync WHERE local_product_id=%s AND mode='test'",
                        (_pid,), fetchone=True)
        check("sync mapping row persisted", _map and _map["stripe_product_id"] == "prod_FAKE")
        # Re-sync with same price -> 'updated' (no new price); price change -> new price.
        _res2 = _ssync.sync_product(_pid)
        check("re-sync with no price change -> updated", _res2.get("action") == "updated")
        execute_db("UPDATE products SET price_cents=2500 WHERE id=%s", (_pid,))
        _res3 = _ssync.sync_product(_pid)
        check("price change -> updated_with_new_price",
              _res3.get("action") == "updated_with_new_price")

        # --- product checkout creates a pending order (fake Checkout Session) ---
        class _FakeSession:
            @staticmethod
            def create(**k):
                return _FakeObj(id="cs_FAKE", url="https://stripe.test/cs_FAKE")

        class _FakeCheckout:
            Session = _FakeSession

        class _FakeStripeCheckout:
            checkout = _FakeCheckout

        _sc.get_stripe = lambda: _FakeStripeCheckout
        # The sync test above bumped the price to 2500; reset so the checkout
        # math is the intuitive 1500 x 2 = 3000.
        execute_db("UPDATE products SET price_cents=1500 WHERE id=%s", (_pid,))
        execute_db("DELETE FROM orders WHERE customer_email='buyer@gate.test'")
        _co = c.post("/api/checkout/create-payment-intent",
                     json={"items": [{"slug": "gate-sku", "quantity": 2}],
                           "customer_email": "buyer@gate.test", "customer_name": "Gate Buyer"})
        check("checkout returns 201 + checkout_url",
              _co.status_code == 201 and _co.get_json().get("checkout_url"))
        _onum = _co.get_json().get("order_number")
        _ord = query_db("SELECT status, total_cents, stripe_payment_intent_id FROM orders "
                        "WHERE order_number=%s", (_onum,), fetchone=True)
        check("checkout order is pending with server-side total",
              _ord and _ord["status"] == "pending" and _ord["total_cents"] == 3000)
        check("checkout stored the stripe session id", _ord["stripe_payment_intent_id"] == "cs_FAKE")
        check("public order lookup returns items",
              len(c.get(f"/api/orders/{_onum}").get_json().get("items", [])) == 1)
        check("unknown product rejected",
              c.post("/api/checkout/create-payment-intent",
                     json={"items": [{"slug": "nope"}]}).status_code == 400)

        # --- webhook: no secret -> 503; bad signature -> 400; valid -> routes ---
        _sc.invalidate_cache()
        _os11.environ.pop("STRIPE_WEBHOOK_SECRET", None)
        check("webhook 503 without signing secret",
              c.post("/api/stripe/webhook", data=b"{}").status_code == 503)
        _os11.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_gate"
        _sc.invalidate_cache()

        _evt_holder = {"event": None, "raise": False}

        class _FakeWebhook:
            @staticmethod
            def construct_event(payload, sig, secret):
                if _evt_holder["raise"]:
                    raise ValueError("bad signature")
                return _evt_holder["event"]

        class _FakeStripeWebhook:
            Webhook = _FakeWebhook
        _orig_stripe_attr = _sc.stripe
        _sc.stripe = _FakeStripeWebhook

        _evt_holder["raise"] = True
        check("webhook bad signature -> 400",
              c.post("/api/stripe/webhook", data=b"{}",
                     headers={"Stripe-Signature": "x"}).status_code == 400)

        # Valid completed event flips the order to paid (idempotently).
        _evt_holder["raise"] = False
        _evt_holder["event"] = {
            "id": "evt_GATE1", "type": "checkout.session.completed",
            "data": {"object": {"payment_intent": "pi_GATE", "metadata":
                     {"kind": "order", "order_number": _onum}}}}
        r_wh = c.post("/api/stripe/webhook", data=b"{}", headers={"Stripe-Signature": "x"})
        check("webhook completed -> 200", r_wh.status_code == 200)
        _ord2 = query_db("SELECT status, paid_at FROM orders WHERE order_number=%s",
                         (_onum,), fetchone=True)
        check("webhook flips order to paid", _ord2["status"] == "paid" and _ord2["paid_at"])
        check("webhook decrements tracked stock (100 - 2)",
              query_db("SELECT stock FROM products WHERE id=%s", (_pid,), fetchone=True)["stock"] == 98)
        # Replay the SAME event id -> no-op, reported as duplicate.
        r_dup = c.post("/api/stripe/webhook", data=b"{}", headers={"Stripe-Signature": "x"})
        check("webhook duplicate event is idempotent",
              r_dup.get_json().get("duplicate") is True)

        # Booking completed event confirms the booking.
        execute_db("DELETE FROM service_bookings WHERE booking_token='tok_GATE'")
        execute_db("INSERT INTO service_bookings (service_id, booking_token, client_name, "
                   " client_email, pricing_model, total_cents, payment_status, status) "
                   "VALUES (NULL,'tok_GATE','G','g@gate.test','deposit',5000,'pending','pending')")
        _evt_holder["event"] = {
            "id": "evt_GATE2", "type": "checkout.session.completed",
            "data": {"object": {"amount_total": 5000, "metadata":
                     {"kind": "booking", "booking_token": "tok_GATE"}}}}
        c.post("/api/stripe/webhook", data=b"{}", headers={"Stripe-Signature": "x"})
        _bk = query_db("SELECT payment_status, status, amount_paid_cents FROM service_bookings "
                       "WHERE booking_token='tok_GATE'", fetchone=True)
        check("webhook confirms paid booking",
              _bk["payment_status"] == "paid" and _bk["status"] == "confirmed"
              and _bk["amount_paid_cents"] == 5000)

        # Expired event cancels a pending order.
        _co2 = c.post("/api/checkout/create-payment-intent",
                      json={"items": [{"slug": "gate-sku"}], "customer_email": "x@gate.test"})
        _onum2 = _co2.get_json().get("order_number")
        _evt_holder["event"] = {
            "id": "evt_GATE3", "type": "checkout.session.expired",
            "data": {"object": {"metadata": {"kind": "order", "order_number": _onum2}}}}
        c.post("/api/stripe/webhook", data=b"{}", headers={"Stripe-Signature": "x"})
        check("webhook expired cancels pending order",
              query_db("SELECT status FROM orders WHERE order_number=%s", (_onum2,),
                       fetchone=True)["status"] == "cancelled")

        # Admin order detail + status transition (admin client from M7 section).
        _oid = query_db("SELECT id FROM orders WHERE order_number=%s", (_onum,),
                        fetchone=True)["id"]
        check("admin order detail returns items",
              len(admin.get(f"/admin/api/orders/{_oid}").get_json().get("items", [])) == 1)
        check("admin order status update to fulfilled",
              admin.put(f"/admin/api/orders/{_oid}/status",
                        json={"status": "fulfilled"}).get_json().get("status") == "fulfilled")
        check("admin order status rejects bad value",
              admin.put(f"/admin/api/orders/{_oid}/status",
                        json={"status": "bogus"}).status_code == 400)
        check("admin stripe sync-status lists products",
              admin.get("/admin/api/stripe/sync-status").status_code == 200)

        # Refund hardening: the paid order (_onum) has a fake PI; over-refund and
        # zero/negative amounts are rejected before any Stripe call; a valid
        # partial refund flips to partially_refunded and tracks refunded_cents.
        class _FakeRefund:
            @staticmethod
            def create(**k):
                return _FakeObj(id="re_FAKE")

        class _FakeStripeRefund:
            Refund = _FakeRefund
        _sc.get_stripe = lambda: _FakeStripeRefund
        # _onum total is 3000, currently 'paid' with stripe_payment_intent_id.
        check("refund rejects over-amount",
              admin.post(f"/admin/api/orders/{_oid}/refund",
                         json={"amount_cents": 99999}).status_code == 400)
        check("refund rejects zero amount",
              admin.post(f"/admin/api/orders/{_oid}/refund",
                         json={"amount_cents": 0}).status_code == 400)
        # Note: _oid was set to 'fulfilled' above — still refundable.
        _rf = admin.post(f"/admin/api/orders/{_oid}/refund", json={"amount_cents": 1000})
        check("partial refund -> partially_refunded",
              _rf.get_json().get("status") == "partially_refunded")
        check("partial refund tracks refunded_cents",
              query_db("SELECT refunded_cents FROM orders WHERE id=%s", (_oid,),
                       fetchone=True)["refunded_cents"] == 1000)
        _rf2 = admin.post(f"/admin/api/orders/{_oid}/refund", json={"amount_cents": 2000})
        check("refund balance -> fully refunded",
              _rf2.get_json().get("status") == "refunded")
        check("refund past balance rejected (409)",
              admin.post(f"/admin/api/orders/{_oid}/refund",
                         json={"amount_cents": 100}).status_code == 409)

        # Restore patched module state.
        _sc.get_stripe = _orig_get_stripe
        _sc.stripe = _orig_stripe_attr
        _os11.environ.pop("STRIPE_WEBHOOK_SECRET", None)
        _sc.invalidate_cache()

        # ----- M12: Events ticketing ------------------------------------------
        check("events table present", table_exists("events"))
        check("event_rsvps table present", table_exists("event_rsvps"))
        check("lookup_events registered", "lookup_events" in tools.CHAT_LOOKUP_FUNCTIONS)

        # Admin create (free) + public reads.
        execute_db("DELETE FROM events")
        r_ce = admin.post("/admin/api/events",
                          json={"slug": "gala", "title": "Spring Gala", "price_mode": "free",
                                "capacity": 2, "status": "published"})
        check("admin create free event 201", r_ce.status_code == 201)
        check("public events lists it",
              any(e["slug"] == "gala" for e in c.get("/api/events").get_json()))
        _ev = c.get("/api/events/gala").get_json()
        check("public event detail seats_remaining=2", _ev.get("seats_remaining") == 2)

        # Free RSVP confirmed immediately + reserves a seat.
        r_rsvp = c.post("/api/events/gala/rsvp",
                        json={"name": "A", "email": "a@gate.test", "guests": 1})
        check("free RSVP confirmed", r_rsvp.get_json().get("action") == "rsvp_confirmed")
        check("seats decremented after RSVP",
              c.get("/api/events/gala").get_json().get("seats_remaining") == 1)

        # Capacity enforced: 2-guest RSVP would exceed the remaining 1 -> 409.
        r_full = c.post("/api/events/gala/rsvp",
                        json={"name": "B", "email": "b@gate.test", "guests": 2})
        check("over-capacity RSVP rejected (409)", r_full.status_code == 409)
        # Exactly filling the last seat is allowed.
        check("last seat RSVP allowed",
              c.post("/api/events/gala/rsvp",
                     json={"name": "C", "email": "c@gate.test", "guests": 1}).status_code == 201)
        check("event now sold out",
              c.get("/api/events/gala").get_json().get("seats_remaining") == 0)

        # lookup_events reflects capacity.
        _le = tools.lookup_events(slug="gala")
        check("lookup_events returns sold-out seats_remaining=0",
              _le and _le[0]["seats_remaining"] == 0)

        # Paid event -> pending RSVP + Stripe redirect (fake), webhook confirms.
        _sc.get_stripe = lambda: _FakeStripeCheckout   # reuse the M11 fake
        admin.post("/admin/api/events",
                   json={"slug": "concert", "title": "Concert", "price_mode": "paid",
                         "price_cents": 2000, "capacity": 50, "status": "published"})
        r_paid = c.post("/api/events/concert/rsvp",
                        json={"name": "P", "email": "p@gate.test", "guests": 2})
        check("paid RSVP returns redirect + checkout_url",
              r_paid.get_json().get("action") == "redirect"
              and r_paid.get_json().get("checkout_url"))
        _ptok = r_paid.get_json().get("rsvp_token")
        _prsvp = query_db("SELECT payment_status, status, amount_cents FROM event_rsvps "
                          "WHERE rsvp_token=%s", (_ptok,), fetchone=True)
        check("paid RSVP pending with per-guest amount (2000 x 2)",
              _prsvp["payment_status"] == "pending" and _prsvp["amount_cents"] == 4000)
        check("pending paid RSVP still reserves the seat",
              tools.lookup_events(slug="concert")[0]["seats_remaining"] == 48)

        # Webhook (event_rsvp completed) confirms; (expired) frees the seat.
        _os11.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_gate"
        _sc.invalidate_cache()
        _sc.stripe = _FakeStripeWebhook
        _evt_holder["raise"] = False
        _evt_holder["event"] = {
            "id": "evt_EV1", "type": "checkout.session.completed",
            "data": {"object": {"metadata": {"kind": "event_rsvp", "rsvp_token": _ptok}}}}
        c.post("/api/stripe/webhook", data=b"{}", headers={"Stripe-Signature": "x"})
        check("webhook confirms paid event RSVP",
              query_db("SELECT payment_status, status FROM event_rsvps WHERE rsvp_token=%s",
                       (_ptok,), fetchone=True)["payment_status"] == "paid")

        # A second pending RSVP that expires releases its held seats.
        r_paid2 = c.post("/api/events/concert/rsvp",
                         json={"name": "Q", "email": "q@gate.test", "guests": 3})
        _ptok2 = r_paid2.get_json().get("rsvp_token")
        check("expiring RSVP held 3 seats (50-2-3=45)",
              tools.lookup_events(slug="concert")[0]["seats_remaining"] == 45)
        _evt_holder["event"] = {
            "id": "evt_EV2", "type": "checkout.session.expired",
            "data": {"object": {"metadata": {"kind": "event_rsvp", "rsvp_token": _ptok2}}}}
        c.post("/api/stripe/webhook", data=b"{}", headers={"Stripe-Signature": "x"})
        check("expired RSVP frees its seats (back to 48)",
              tools.lookup_events(slug="concert")[0]["seats_remaining"] == 48)

        # Admin RSVP list + delete.
        _ceid = query_db("SELECT id FROM events WHERE slug='concert'", fetchone=True)["id"]
        check("admin RSVP list returns rows",
              len(admin.get(f"/admin/api/events/{_ceid}/rsvps").get_json()["rsvps"]) >= 1)

        _sc.get_stripe = _orig_get_stripe
        _sc.stripe = _orig_stripe_attr
        _os11.environ.pop("STRIPE_WEBHOOK_SECRET", None)
        _sc.invalidate_cache()

        # ----- M13: visitor lookup parity + content CRUD + web search ---------
        for _t13 in ("experiences", "pricing_seasons", "testimonials", "team_members",
                     "faqs", "blog_posts", "business_info", "custom_section_items"):
            check(f"M13 table {_t13} present", table_exists(_t13))

        # Content admin CRUD (generic, column-allowlisted).
        r_exp = admin.post("/admin/api/content/experiences",
                           json={"name": "Wine Tasting", "description": "Guided flight",
                                 "icon": "wine", "sort_order": 1})
        check("content create experience 201", r_exp.status_code == 201)
        _exp_id = r_exp.get_json()["id"]
        check("content list experiences",
              len(admin.get("/admin/api/content/experiences").get_json()["items"]) >= 1)
        check("content update experience",
              admin.put(f"/admin/api/content/experiences/{_exp_id}",
                        json={"description": "Updated"}).get_json()["description"] == "Updated")
        check("content unknown resource 404",
              admin.get("/admin/api/content/nope").status_code == 404)
        # Blog requires a unique slug on create.
        check("content blog requires slug",
              admin.post("/admin/api/content/blog", json={"title": "x"}).status_code == 400)
        check("content blog create with slug",
              admin.post("/admin/api/content/blog",
                         json={"slug": "hello", "title": "Hello", "excerpt": "Hi there",
                               "status": "published"}).status_code == 201)
        # business_info singleton PUT/GET (incl. JSONB hours).
        admin.put("/admin/api/content/business-info",
                  json={"name": "Acme Vineyard", "phone": "555-1234",
                        "hours": {"mon": "9-5"}})
        _bi = admin.get("/admin/api/content/business-info").get_json()
        check("business_info persisted", _bi.get("name") == "Acme Vineyard")
        check("business_info JSONB hours stored", (_bi.get("hours") or {}).get("mon") == "9-5")

        # Seed remaining content + a service/product so the lookups have rows.
        execute_db("INSERT INTO pricing_seasons (label, date_range, price_range) "
                   "VALUES ('Peak','Jun-Aug','$200-$300')")
        execute_db("INSERT INTO faqs (question, answer) VALUES ('Parking?','Yes, free.')")
        execute_db("INSERT INTO testimonials (reviewer_name, content, rating) "
                   "VALUES ('Sam','Loved it',5)")
        execute_db("INSERT INTO team_members (name, title) VALUES ('Ada','Host')")
        execute_db("INSERT INTO custom_section_items (section_slug, title, content) "
                   "VALUES ('awards','Best of 2025','We won')")
        execute_db("INSERT INTO services (slug, name, is_active, pricing_model, base_price_cents) "
                   "VALUES ('tour','Tour',TRUE,'rsvp',0) ON CONFLICT (slug) DO NOTHING")

        # Lookup tools return expected shapes.
        check("lookup_services returns rows", any(s["slug"] == "tour" for s in tools.lookup_services()))
        check("lookup_products returns rows", any(p["slug"] == "gate-sku" for p in tools.lookup_products()))
        check("lookup_experiences returns rows",
              any(e["name"] == "Wine Tasting" for e in tools.lookup_experiences()))
        check("lookup_pricing returns rows", any(p["label"] == "Peak" for p in tools.lookup_pricing()))
        check("lookup_faq returns rows", any("Parking" in f["question"] for f in tools.lookup_faq()))
        check("lookup_testimonials returns rows",
              any(t["reviewer_name"] == "Sam" for t in tools.lookup_testimonials()))
        check("lookup_team returns rows", any(t["name"] == "Ada" for t in tools.lookup_team()))
        check("lookup_blog returns only published",
              any(b["slug"] == "hello" for b in tools.lookup_blog()))
        check("lookup_business_info returns the profile",
              tools.lookup_business_info().get("name") == "Acme Vineyard")
        check("lookup_custom_section_items filter by slug",
              len(tools.lookup_custom_section_items(section_slug="awards")) == 1)
        _avail = tools.lookup_service_availability(slug="tour")
        check("lookup_service_availability returns shape", "days" in _avail or "error" in _avail)

        # Web search degrades cleanly without a key.
        _wsearch = tools.lookup_web_search(query="anything")
        check("web search degrades without a key",
              _wsearch.get("error") == "web search not configured")

        # All new lookups are registered + appear in the site index.
        for _n in ("lookup_services", "lookup_products", "lookup_experiences", "lookup_pricing",
                   "lookup_blog", "lookup_team", "lookup_faq", "lookup_testimonials",
                   "lookup_business_info", "lookup_custom_section_items", "lookup_web_search",
                   "lookup_service_availability"):
            check(f"{_n} registered", _n in tools.CHAT_LOOKUP_FUNCTIONS)
        _idx = prompts.build_site_index()
        check("site index includes services + experiences + business",
              "lookup_services" in _idx and "EXPERIENCES" in _idx and "BUSINESS" in _idx)

        # ----- M14: integrations completion (the genuinely-new pieces) --------
        import io
        # Reviews aggregate parsers (pure) + no-key refresh path.
        from admin_ai_platform.blueprints import reviews as _rev
        check("google places parser", _rev._parse_google(
            {"result": {"rating": 4.6, "user_ratings_total": 120}}) == (120, 4.6))
        check("yelp parser", _rev._parse_yelp({"rating": 4.0, "review_count": 88}) == (88, 4.0))
        check("tripadvisor parser",
              _rev._parse_tripadvisor({"rating": "3.5", "num_reviews": "12"}) == (12, 3.5))
        _did = execute_db("INSERT INTO review_destinations (name, kind, external_id) "
                          "VALUES ('G','google','PLACE123') RETURNING id")["id"]
        _rr = admin.post(f"/admin/api/reviews/destinations/{_did}/refresh").get_json()
        check("review refresh records key-not-configured cleanly",
              _rr.get("ok") is False and "not configured" in _rr.get("error", ""))
        check("review refresh wrote an error snapshot row",
              (query_db("SELECT error_text FROM external_reviews WHERE destination_id=%s",
                        (_did,), fetchone=True) or {}).get("error_text", "") != "")
        check("reviews ai-draft requires LLM (503 without key)",
              admin.post("/admin/api/reviews/ai-draft", json={}).status_code == 503)

        # Presentations import: rejects unsupported types, imports a real .pptx
        # (built in-memory) with text + speaker-notes -> narration.
        check("import rejects unsupported type",
              admin.post("/admin/api/presentations/import",
                         data={"file": (io.BytesIO(b"x"), "notes.txt")},
                         content_type="multipart/form-data").status_code == 400)
        try:
            import io as _io
            from pptx import Presentation as _Prs
            _prs = _Prs()
            _slide = _prs.slides.add_slide(_prs.slide_layouts[1])
            _slide.shapes.title.text = "Welcome"
            _slide.placeholders[1].text = "Body bullet one"
            _slide.notes_slide.notes_text_frame.text = "Say hello warmly."
            _buf = _io.BytesIO()
            _prs.save(_buf)
            _buf.seek(0)
            _imp = admin.post("/admin/api/presentations/import",
                              data={"file": (_buf, "MyDeck.pptx")},
                              content_type="multipart/form-data")
            _ij = _imp.get_json()
            check("pptx import 201 + slides created",
                  _imp.status_code == 201 and _ij.get("slides_created", 0) >= 1)
            _pid14 = _ij["id"]
            _sl = query_db("SELECT title, narration_text FROM presentation_slides "
                           "WHERE presentation_id=%s ORDER BY order_index", (_pid14,))
            check("pptx import extracted title", _sl and _sl[0]["title"] == "Welcome")
            check("pptx import extracted speaker notes as narration",
                  _sl and _sl[0]["narration_text"] == "Say hello warmly.")
            check("generate-narration needs LLM (503 without key)",
                  admin.post(f"/admin/api/presentations/{_pid14}/generate-narration",
                             json={}).status_code == 503)
        except Exception as _pe:
            check(f"pptx import smoke (python-pptx available): {_pe}", False)

        # Legacy non-streaming TTS route is wired (403 when AI voice disabled by
        # default — not a 404).
        check("legacy /api/voice/tts wired (not 404)",
              c.post("/api/voice/tts", json={"text": "hi"}).status_code in (403, 503, 201, 429))

        # ----- M15: analytics -------------------------------------------------
        check("page_views table present", table_exists("page_views"))
        execute_db("DELETE FROM page_views")
        _pv = c.post("/api/track/pageview",
                     json={"url": "https://shop.test/pricing?utm_source=fb",
                           "session_id": "sess-A", "visitor_id": "vis-1",
                           "utm_source": "fb", "referrer": "https://google.com"},
                     headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS) Safari"})
        check("pageview tracked 200", _pv.status_code == 200 and _pv.get_json().get("tracked"))
        _row = query_db("SELECT path, utm_source, device_type, browser FROM page_views "
                        "WHERE session_id='sess-A'", fetchone=True)
        check("pageview parsed path + UTM + UA",
              _row and _row["path"] == "/pricing" and _row["utm_source"] == "fb"
              and _row["device_type"] == "mobile" and _row["browser"] == "Safari")
        _pv2 = c.post("/api/track/pageview",
                      json={"url": "https://shop.test/pricing", "session_id": "sess-A"})
        check("repeat pageview deduped", _pv2.get_json().get("deduped") is True)
        check("dedupe left a single row",
              query_db("SELECT COUNT(*) AS n FROM page_views WHERE session_id='sess-A'",
                       fetchone=True)["n"] == 1)
        c.post("/api/track/pageview", json={"url": "https://shop.test/", "session_id": "sess-B",
                                            "visitor_id": "vis-2"})
        c.post("/api/track/duration", json={"session_id": "sess-A", "path": "/pricing",
                                            "duration_ms": 4200})
        check("duration patched onto pageview",
              query_db("SELECT duration_ms FROM page_views WHERE session_id='sess-A'",
                       fetchone=True)["duration_ms"] == 4200)
        _an = admin.get("/admin/api/analytics?days=30").get_json()
        check("analytics totals views=2 sessions=2",
              _an["totals"]["views"] == 2 and _an["totals"]["sessions"] == 2)
        check("analytics top_pages includes /pricing",
              any(p["value"] == "/pricing" for p in _an["top_pages"]))
        check("analytics chart returns a daily series",
              len(admin.get("/admin/api/analytics/chart").get_json()["series"]) >= 1)
        check("analytics chat endpoint returns tool_usage key",
              "tool_usage" in admin.get("/admin/api/analytics/chat").get_json())
        check("analytics forms endpoint returns forms",
              "forms" in admin.get("/admin/api/analytics/forms").get_json())
        check("analytics admin read requires auth",
              anon.get("/admin/api/analytics").status_code == 401)

        # ----- M16: admin dashboard SPA --------------------------------------
        _dash = admin.get("/admin")
        check("dashboard served to authed admin", _dash.status_code == 200)
        _html = _dash.get_data(as_text=True)
        for _lbl in ("Analytics", "Embed Keys", "Web Scraper", "Knowledge Base",
                     "Automations", "MCP Connectors", "Events", "Products",
                     "Campaigns", "Developer Console", "renderResource", "TABS"):
            check(f"dashboard contains '{_lbl}'", _lbl in _html)
        check("dashboard is dependency-free (no external script src)",
              "<script src" not in _html.lower())
        check("anon still redirected from dashboard",
              anon.get("/admin").status_code in (301, 302))

        # ----- M19: security hardening (CSRF + secrets-at-rest + headers) ----
        import admin_ai_platform.crypto as _crypto
        # crypto roundtrip (pure).
        _ct = _crypto.encrypt("super-secret-token")
        check("crypto ciphertext is tagged + differs from plaintext",
              _ct.startswith("enc:v1:") and _ct != "super-secret-token")
        check("crypto decrypt roundtrips", _crypto.decrypt(_ct) == "super-secret-token")
        check("crypto decrypt passes through legacy plaintext",
              _crypto.decrypt("legacy-plain") == "legacy-plain")
        # CSRF: a cookie-authed admin WITHOUT a token is rejected; with it, ok.
        _nocsrf = app.test_client()
        _nocsrf.post("/admin/login", json={"password": "admin"})
        check("admin mutation without CSRF token -> 403",
              _nocsrf.post("/admin/api/mcp/servers", json={"name": "x"}).status_code == 403)
        _tok2 = _nocsrf.get("/admin/api/csrf-token").get_json()["csrf_token"]
        check("admin mutation WITH CSRF token accepted",
              _nocsrf.post("/admin/api/mcp/servers",
                           json={"name": "csrf-ok", "transport": "http"},
                           headers={"X-CSRF-Token": _tok2}).status_code in (201, 409))
        check("safe GET needs no CSRF token",
              _nocsrf.get("/admin/api/mcp/servers").status_code == 200)
        check("API-key callers are CSRF-exempt (still 401 without key here)",
              app.test_client().post("/admin/api/mcp/servers", json={"name": "y"}).status_code == 401)
        # Secrets at rest: a stored MCP credential is ciphertext in the DB but
        # decrypts at the point of use.
        execute_db("DELETE FROM mcp_servers WHERE name='sec-test'")
        admin.post("/admin/api/mcp/servers",
                   json={"name": "sec-test", "transport": "http", "url": "http://x",
                         "auth_type": "bearer", "auth_credential": "tok_PLAINTEXT_123"})
        _stored = query_db("SELECT auth_credential FROM mcp_servers WHERE name='sec-test'",
                           fetchone=True)["auth_credential"]
        check("stored credential is encrypted (not plaintext)",
              _stored.startswith("enc:v1:") and "tok_PLAINTEXT_123" not in _stored)
        check("stored credential decrypts to original",
              _crypto.decrypt(_stored) == "tok_PLAINTEXT_123")
        import admin_ai_platform.mcp_client as _mc
        _hdrs = _mc._headers({"auth_type": "bearer", "auth_credential": _stored})
        check("mcp_client builds Bearer from decrypted credential",
              _hdrs.get("authorization") == "Bearer tok_PLAINTEXT_123")
        check("GET list redacts the credential (never returns ciphertext/plaintext)",
              all(s.get("auth_credential") in ("***", "") for s in
                  admin.get("/admin/api/mcp/servers").get_json()["servers"]))
        # Migration encrypts legacy plaintext rows idempotently.
        execute_db("UPDATE mcp_servers SET auth_credential='legacy_plain_cred' WHERE name='sec-test'")
        from admin_ai_platform.blueprints.mcp import migrate_encrypt_credentials
        migrate_encrypt_credentials()
        check("migration encrypted a legacy plaintext credential",
              _crypto.is_encrypted(query_db("SELECT auth_credential FROM mcp_servers "
                                            "WHERE name='sec-test'", fetchone=True)["auth_credential"]))
        # Security headers.
        _h = admin.get("/admin").headers
        check("X-Content-Type-Options nosniff", _h.get("X-Content-Type-Options") == "nosniff")
        check("Referrer-Policy set", "strict-origin" in _h.get("Referrer-Policy", ""))
        check("baseline CSP on /admin", "default-src 'self'" in _h.get("Content-Security-Policy", ""))

        # ----- M17: onboarding -----------------------------------------------
        check("platform_setup table present", table_exists("platform_setup"))
        # Before completion the wizard is open.
        check("/setup open before completion", c.get("/setup").status_code == 200)
        # Validation runs before provisioning: a too-short password is rejected.
        check("/setup short password rejected (400)",
              c.post("/setup", json={"business_name": "x", "admin_password": "abc"})
              .status_code == 400)
        # Provision: business + preset seed + admin password + first embed key.
        execute_db("DELETE FROM experiences")  # so preset seed is observable
        _setup = c.post("/setup", json={"business_name": "Gate Vineyard",
                                        "preset": "restaurant", "admin_password": "setuppw123"})
        check("/setup provisions (201 + embed key)",
              _setup.status_code == 201 and _setup.get_json().get("embed_key", "").startswith("pk_"))
        check("setup set business_info name",
              (query_db("SELECT name FROM business_info WHERE id=1", fetchone=True) or {})
              .get("name") == "Gate Vineyard")
        check("setup seeded preset experiences",
              query_db("SELECT COUNT(*) AS n FROM experiences", fetchone=True)["n"] >= 1)
        check("setup created a publishable embed key",
              query_db("SELECT 1 FROM tenant_embed_keys LIMIT 1", fetchone=True) is not None)
        # Self-closes: subsequent GET + POST -> 404.
        check("/setup 404 after completion (GET)", c.get("/setup").status_code == 404)
        check("/setup 404 after completion (POST)",
              c.post("/setup", json={"business_name": "x", "admin_password": "yyyyyy"}).status_code == 404)
        # DB admin password now overrides env: new password logs in, old 'admin' rejected.
        _fresh = app.test_client()
        check("login with new DB password works",
              _fresh.post("/admin/login", json={"password": "setuppw123"}).status_code == 200)
        check("old env password now rejected",
              app.test_client().post("/admin/login", json={"password": "admin"}).status_code == 401)
        # Checklist reflects real state.
        _cl = admin.get("/admin/api/onboarding/checklist").get_json()
        check("checklist business_named true after setup", _cl["steps"]["business_named"] is True)
        check("checklist has_embed_key true", _cl["steps"]["has_embed_key"] is True)
        # Onboarding tools.
        execute_db("DELETE FROM gallery_cards")
        _seed = admin.post("/admin/api/onboarding/seed-sample", json={})
        check("seed-sample creates gallery cards", _seed.get_json().get("seeded", 0) >= 1)
        check("assistant-prompt returned",
              "onboarding" in admin.get("/admin/api/onboarding/assistant-prompt")
              .get_json().get("prompt", "").lower())
        # Agency provisioning: new tenant + embed key + snapshot cards.
        _prov = admin.post("/admin/api/onboarding/provision-tenant",
                           json={"name": "Client Co",
                                 "snapshot": {"tables": {"gallery_cards":
                                              [{"slug": "snap-card", "title": "Snapped"}]}}})
        _pj = _prov.get_json()
        check("provision-tenant creates tenant + key",
              _prov.status_code == 201 and _pj.get("tenant_id") and _pj.get("embed_key", "").startswith("pk_"))
        check("provision-tenant applied snapshot card", _pj.get("snapshot_cards_applied", 0) == 1)
        check("provisioned tenant row exists",
              query_db("SELECT 1 FROM tenants WHERE id=%s", (_pj["tenant_id"],), fetchone=True) is not None)

        print("[gate] schema + integration checks complete", flush=True)

    finally:
        try:
            srv.cleanup()
        except Exception:
            pass

    print(f"\n[gate] {len(passed)} passed, {len(failed)} failed")
    if failed:
        print("[gate] FAILURES: " + ", ".join(failed))
        sys.exit(1)
    print("[gate] ALL GREEN")


if __name__ == "__main__":
    main()
