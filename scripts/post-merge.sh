#!/bin/bash
set -e

# This is a Python (Flask + psycopg2) project. Database schema is
# bootstrapped by app.py's init_db() on every startup, so no separate
# migration step is needed here.

# Keep npm install around because a small amount of JS dev tooling is
# tracked in package.json. It's a no-op when nothing changed.
if [ -f package.json ]; then
  npm install --no-audit --no-fund
fi

# Sync Python deps if either lockfile / manifest is present.
if [ -f pyproject.toml ] || [ -f requirements.txt ]; then
  if command -v uv >/dev/null 2>&1 && [ -f pyproject.toml ]; then
    uv sync --frozen 2>/dev/null || uv sync
  elif [ -f requirements.txt ]; then
    pip install -q -r requirements.txt
  fi
fi
