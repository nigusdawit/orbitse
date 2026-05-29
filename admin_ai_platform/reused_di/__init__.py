"""
admin_ai_platform.reused_di
===========================

Home for the Tier-2 helper modules that originally did ``from app import
query_db/execute_db/clients`` (rag, semantic_cache, stripe_sync,
stripe_settings, velo_endpoints, velo_handlers). When relocated, each is
refactored to receive its dependencies via an ``init_module(...)`` /
factory call made from ``create_app()`` — pointing at this package's
``db``/``llm``/``cost`` modules instead of the legacy app.

See the relocation policy note in ``admin_ai_platform.reused``. Modules land in
the milestone that first consumes them.
"""
