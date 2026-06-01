# ── SentryPay — Dockerfile ────────────────────────────────────────────────────
#
# Builds a single container running the FastAPI backend.
# The React frontend is served as static files by FastAPI
# after being built separately and copied into the image.
#
# Build:
#   docker build -t sentry-pay .
#
# Run locally:
#   docker run -p 8000:8000 --env-file .env sentry-pay
#
# Deploy to Cloud Run:
#   gcloud run deploy sentry-pay \
#     --image gcr.io/PROJECT_ID/sentry-pay \
#     --platform managed \
#     --region us-central1 \
#     --allow-unauthenticated \
#     --timeout 300 \
#     --memory 2Gi \
#     --cpu 2

# ── Base image ────────────────────────────────────────────────────────────────
# Python 3.12 slim — smaller than 3.14, better package compatibility
FROM python:3.12-slim

# ── System dependencies ───────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ─────────────────────────────────────────────────────────
WORKDIR /app

# ── Python dependencies ───────────────────────────────────────────────────────
# Copy requirements first to leverage Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── Application code ──────────────────────────────────────────────────────────
COPY agent/       ./agent/
COPY config/      ./config/
COPY setup/       ./setup/
COPY .env.example ./

# ── Create required directories ───────────────────────────────────────────────
RUN mkdir -p data/sar_reports data/processed

# ── Non-root user for security ────────────────────────────────────────────────
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

# ── Port ─────────────────────────────────────────────────────────────────────
# Cloud Run injects PORT env variable — default to 8000
ENV PORT=8000
EXPOSE 8000

# ── Health check ──────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# ── Start command ─────────────────────────────────────────────────────────────
# Use shell form to expand $PORT env variable
CMD uvicorn agent.api:app \
    --host 0.0.0.0 \
    --port $PORT \
    --workers 1 \
    --timeout-keep-alive 300 \
    --log-level info