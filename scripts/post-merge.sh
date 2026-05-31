#!/bin/bash
set -e

# This is a Python (Flask + psycopg2) project running on Replit.
# Python packages are managed by Replit's Nix environment — they are
# already installed and available on PATH. Do NOT run uv sync / pip install
# here: the Nix store is read-only and any attempt to install into it will
# fail with "Permission denied".
#
# Database schema is bootstrapped by app.py on every startup via Alembic,
# so no separate migration step is needed here either.

# Keep npm install around because a small amount of JS dev tooling is
# tracked in package.json. It's a no-op when nothing changed.
if [ -f package.json ]; then
  npm install --no-audit --no-fund
fi
