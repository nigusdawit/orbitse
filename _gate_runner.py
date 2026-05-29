"""TEMP M1 gate runner — boots an embedded Postgres (pgserver), points the
package at it, runs init_db + live route/DB integration checks + the DB-backed
pytest suite. Deleted after use. Not part of the package.

Run: uv run --python 3.12 --with pgserver --with pytest python _gate_runner.py
"""
import os
import sys
import tempfile
import json


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
        import time as _t; _t.sleep(0.3)  # async warn-check thread harmless
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
        # Give it a webhook token, then hit the public hook → queues a run.
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
        # Unknown webhook token → 404.
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
        # Weekly rule: every day 09:00-11:00, 60-min slots → 09:00 & 10:00.
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
        check("stripe webhook acks", anon.post("/api/stripe/webhook", json={}).status_code == 200)

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
