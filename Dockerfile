# =============================================================================
# AI Concierge Platform — production container image
# =============================================================================
# Build:   docker build -t ai-concierge .
# Run:     docker run --env-file .env -p 5000:5000 ai-concierge
# =============================================================================

FROM python:3.11-slim

# System packages required at runtime:
#   libreoffice-impress  — used by the PowerPoint export pipeline
#                          (see slide-deck generation in app.py)
#   libreoffice-core     — pulled in by impress; explicit for clarity
#   libpq5               — Postgres client lib (psycopg2-binary bundles its own,
#                          but having libpq5 makes troubleshooting easier)
#   fonts-*              — so libreoffice can render text in exported decks
#   curl                 — used for the container HEALTHCHECK below
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-impress libreoffice-core \
        libpq5 \
        fonts-liberation fonts-dejavu-core \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so this layer caches across code changes.
COPY requirements.in ./
RUN pip install --no-cache-dir -r requirements.in

# Application code
COPY . .

# Persistent data:
#   /app/uploads        — user-uploaded media (images, PDFs, attachments)
# Mount these as volumes in your orchestrator so they survive container restarts.
# The .flask_secret file is NOT persisted here — set FLASK_SECRET_KEY explicitly
# in the environment for any container deployment.
VOLUME ["/app/uploads"]

EXPOSE 5000

# 4 workers is sane for a 1-2 vCPU box. Tune via $WEB_CONCURRENCY at runtime.
ENV WEB_CONCURRENCY=4 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Surface degraded health with a 5xx so orchestrators can act on it.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl --fail --silent http://localhost:5000/healthz >/dev/null || exit 1

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:5000 --workers ${WEB_CONCURRENCY} --timeout 120 --access-logfile - --error-logfile - app:app"]
