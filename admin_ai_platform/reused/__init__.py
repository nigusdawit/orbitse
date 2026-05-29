"""
admin_ai_platform.reused
========================

Home for the Tier-1 helper modules copied verbatim from the original repo
(messaging, automations, scraper, storage, image_optimize, asset_bundle,
devconsole, stripe_client, velo_client, env_manager) with their imports made
relative and any ``from app import ...`` removed.

RELOCATION POLICY (M0 drift, by design): rather than copy all 16 helper modules
up front — most of which no M0/M1 code path touches — each module is relocated
in the milestone that first consumes it (messaging/automations/scraper → M4/M5,
stripe/velo → M6, rag/semantic_cache → M1/M3/M4). This keeps M0 a small,
genuinely bootable foundation and avoids carrying dead code. The mechanism
(this package + reused_di/) is in place now; modules land as needed.
"""
