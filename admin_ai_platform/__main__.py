"""
Dev entrypoint: ``python -m admin_ai_platform``.

Production should use a WSGI server, e.g.::

    gunicorn "admin_ai_platform:create_app()" --bind 0.0.0.0:5000 --workers 4
"""

from __future__ import annotations

from . import create_app, config


def main():
    app = create_app()
    app.run(host="0.0.0.0", port=config.PORT, debug=False)


if __name__ == "__main__":
    main()
