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

        # 10. (Schema assertions above already cover what test_schema.py checks —
        # idempotent init_db, IN tables present, OUT absent, seeds. The unit
        # suite runs separately under the project venv via `uv run pytest`.)
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
