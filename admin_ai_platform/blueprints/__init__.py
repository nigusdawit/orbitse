"""
admin_ai_platform.blueprints
============================

Per-subsystem Flask blueprints. ``register_all(app)`` mounts every blueprint
that exists; blueprints are added milestone by milestone (M1: visitor_chat,
gallery, forms, voice, media; M2: admin_chat, provider; ...). Importing a
not-yet-built blueprint is guarded so the package boots cleanly at any
milestone.
"""

from __future__ import annotations

import importlib

# (module_name, attribute_name) for each blueprint, in mount order. Entries are
# uncommented as each milestone lands its blueprint module.
_BLUEPRINT_SPECS = [
    # M1
    ("visitor_chat", "bp"),
    ("gallery", "bp"),
    ("forms", "bp"),
    ("media", "bp"),
    ("voice", "bp"),
    ("assets", "bp"),
    # M2
    ("admin", "bp"),
    ("provider", "bp"),
    ("admin_chat", "bp"),
    # M3
    ("cost", "bp"),
    ("skills", "bp"),
    ("mcp", "bp"),
    # M4
    ("automations", "bp"),
    # ... later milestones append here.
]


def register_all(app):
    """Import and register every available blueprint. Missing modules are
    skipped (logged) so the package boots at any milestone."""
    mounted = []
    for mod_name, attr in _BLUEPRINT_SPECS:
        try:
            mod = importlib.import_module(f"{__name__}.{mod_name}")
            bp = getattr(mod, attr)
            app.register_blueprint(bp)
            mounted.append(mod_name)
        except ModuleNotFoundError:
            # Blueprint not built yet at this milestone — fine.
            continue
        except Exception as e:
            print(f"[blueprints] failed to register {mod_name}: {e}")
    if mounted:
        print(f"[blueprints] mounted: {', '.join(mounted)}", flush=True)
    return mounted
