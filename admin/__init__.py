"""admin/ - Flask blueprint package for the app.py de-monolith (Track B).

Each module here owns one feature area's routes as a Flask Blueprint, importing
shared infrastructure from core.py (NEVER from app.py - app.py imports these, so
importing app here would be a circular import). app.py imports each blueprint and
registers it with app.register_blueprint(...). URLs are unchanged (routes use
absolute paths); only the Flask endpoint NAME gains a "<blueprint>." prefix.

See the refactor plan and templates/admin/README.md.
"""
