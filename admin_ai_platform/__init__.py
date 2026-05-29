"""
admin_ai_platform
=================

Standalone, embeddable Admin/AI Platform — the admin/AI half of the original
monolith carved into its own Flask package (see PLAN.md). Distributed as a JS
embed snippet and a WordPress plugin; deployable as central multi-tenant SaaS
or self-host, with self-serve or agency-only admin.

``create_app()`` is the single entry point: it builds the Flask app, bootstraps
the schema, wires shared infrastructure, mounts whatever blueprints exist at the
current milestone, and starts the background scheduler.
"""

from __future__ import annotations

import sys

from flask import Flask, jsonify

from . import config

__version__ = "0.0.0"


def create_app(*, init_schema: bool = True, start_scheduler: bool = True) -> Flask:
    """Build and return the configured Flask application.

    Args:
        init_schema: run ``schema.init_db()`` on boot (skip in unit tests with
            no DB). Guarded so a missing/unreachable DB logs rather than crashes
            — honest failure, but the process still answers /healthz.
        start_scheduler: start the background tick loop (skip in tests).
    """
    app = Flask(__name__, static_folder=None)

    # Secret key — required for admin sessions. Fall back to an ephemeral key in
    # dev (with a loud warning) so a bare `python -m admin_ai_platform` runs.
    if config.FLASK_SECRET_KEY:
        app.secret_key = config.FLASK_SECRET_KEY
    else:
        import secrets as _secrets
        app.secret_key = _secrets.token_hex(32)
        print("[app] FLASK_SECRET_KEY unset — using an ephemeral key; sessions "
              "will not survive a restart. Set FLASK_SECRET_KEY in production.",
              file=sys.stderr)

    # Optional Sentry.
    if config.SENTRY_DSN:
        try:
            import sentry_sdk
            sentry_sdk.init(dsn=config.SENTRY_DSN, send_default_pii=False)
        except Exception as e:  # pragma: no cover
            print(f"[app] Sentry init failed: {e}", file=sys.stderr)

    # Schema bootstrap (idempotent). Failure is logged, not fatal.
    if init_schema:
        try:
            from .schema import init_db
            init_db()
        except Exception as e:
            print(f"[app] schema init failed (continuing): {e}", file=sys.stderr)
        # Sync builtin chat skills so the admin Skills tab can toggle them.
        try:
            from .tools import sync_skills_to_db
            sync_skills_to_db()
        except Exception as e:
            print(f"[app] skill sync skipped: {e}", file=sys.stderr)

    # Wire the cost warn-line email sender once messaging is available (M3/M5).
    # No-op until then.
    try:
        from . import cost
        # messaging relocation lands later; leave sender unset for now.
        _ = cost  # referenced to keep import meaningful
    except Exception as e:  # pragma: no cover
        print(f"[app] cost wiring skipped: {e}", file=sys.stderr)

    # Wire the automations engine: bind DB/LLM/cost helpers, register its
    # background tick with our scheduler, and give it a skill executor so the
    # "call a skill" action can reach the chat tools. Fail-open.
    try:
        import json as _json
        from . import db as _db, llm as _llm, scheduler as _sched
        from .cost import cost_cap_blocks_send, record_sms_cost
        from .tools import execute_chat_tool
        from .reused import automations
        automations.configure(
            query_db=_db.query_db, execute_db=_db.execute_db,
            database_url=config.DATABASE_URL, openai_client=_llm.openai_client,
            public_base_url_fn=lambda: config.PUBLIC_BASE_URL,
            cost_cap_blocks_send_fn=cost_cap_blocks_send,
            record_sms_cost_fn=record_sms_cost)

        def _skill_exec(name, args):
            try:
                return _json.loads(execute_chat_tool(name, args)[0])
            except Exception as ex:
                return {"error": str(ex)[:200]}
        automations.set_skill_executor(_skill_exec)
        automations.register_with_scheduler(_sched)
    except Exception as e:
        print(f"[app] automations wiring skipped: {e}", file=sys.stderr)

    # Wire the RAG/KB module (pgvector). init_module just stashes deps; the
    # blueprint guards every call behind schema.rag_available() so a DB without
    # pgvector degrades cleanly to "KB unavailable" instead of erroring.
    try:
        from . import llm as _llm2
        from .db import query_db as _q, execute_db as _e
        from .cost import record_chat_cost as _rc
        from .reused_di import rag
        rag.init_module(openai_client=_llm2.openai_client, query_db=_q,
                        execute_db=_e, record_cost=_rc)
    except Exception as e:
        print(f"[app] rag wiring skipped: {e}", file=sys.stderr)

    # Mount blueprints that exist at this milestone.
    from .blueprints import register_all
    register_all(app)

    # Health + config-summary routes (no secrets).
    @app.route("/healthz")
    def _healthz():
        return jsonify({"status": "ok", "version": __version__,
                        **config.summary()})

    if start_scheduler:
        try:
            from .scheduler import start_scheduler as _start
            _start()
        except Exception as e:  # pragma: no cover
            print(f"[app] scheduler start failed: {e}", file=sys.stderr)

    print(f"[app] created (deploy={config.DEPLOY_MODE}, admin={config.ADMIN_MODE})",
          flush=True)
    return app
