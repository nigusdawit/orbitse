# =============================================================================
# admin_ai_platform — production container image (M20)
# =============================================================================
# Build:  docker build -t ai-concierge .
# Run:    docker run --env-file .env -p 5000:5000 ai-concierge
#
# Gunicorn entry is the package app factory: admin_ai_platform:create_app().
# The image is the SAME for every silo client; per-client config is env + DB.
# =============================================================================

FROM python:3.12-slim

# Runtime system packages for the full feature set:
#   libreoffice-impress / -core  — presentation import (Office/PPTX -> PDF)
#   poppler-utils (pdftoppm)     — per-slide JPGs from the converted PDF
#   libpq5                       — Postgres client lib
#   fonts-*                      — so LibreOffice renders deck text
#   curl                         — container HEALTHCHECK
# pgvector is a SERVER-side extension (provided by the Postgres image / managed
# DB), not a client package — nothing to install here for it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-impress libreoffice-core \
        poppler-utils \
        libpq5 \
        fonts-liberation fonts-dejavu-core \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so this layer caches across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code (the package + embed/ + wordpress-plugin/ etc).
COPY . .

# Build the content-hashed widget bundle at image-build time so /embed/dist is
# ready to serve (immutable, cache-busted on source change).
RUN python -m admin_ai_platform.bundle || echo "[build] widget bundle skipped"

# Persistent data: user-uploaded media + the RAG/voice file cache. Mount as a
# volume so it survives restarts.
VOLUME ["/app/uploads"]

EXPOSE 5000

# 4 workers suits a 1-2 vCPU box; tune via $WEB_CONCURRENCY. The scheduler picks
# a single leader across workers via a Postgres advisory lock (M10).
ENV WEB_CONCURRENCY=4 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl --fail --silent http://localhost:5000/healthz >/dev/null || exit 1

# Factory-style entry: gunicorn calls create_app() to build the WSGI app.
CMD ["sh", "-c", "exec gunicorn 'admin_ai_platform:create_app()' --bind 0.0.0.0:5000 --workers ${WEB_CONCURRENCY} --timeout 120 --access-logfile - --error-logfile -"]
