# ═════════════════════════════════════════════════════════════════════════════
# Stage 1 — Build the React frontend with Vite
# ═════════════════════════════════════════════════════════════════════════════
FROM node:20-alpine AS frontend-builder

WORKDIR /app

# Pre-create the directory Vite will write to. Vite resolves outDir relative
# to the frontend project root, so we need /app/agent to exist for the
# `../agent/static` path to resolve.
RUN mkdir -p /app/agent

WORKDIR /app/frontend

# Install dependencies first (better Docker layer caching)
COPY frontend/package*.json ./
RUN npm ci --silent

# Build the production bundle
# Output lands at /app/agent/static thanks to vite.config.js outDir setting
COPY frontend/ ./
RUN npm run build && ls -la /app/agent/static


# ═════════════════════════════════════════════════════════════════════════════
# Stage 2 — Python runtime that serves FastAPI + built frontend
# ═════════════════════════════════════════════════════════════════════════════
FROM python:3.12-slim

WORKDIR /app

# System dependencies for some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies first (cached)
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Application code
COPY agent/      ./agent/
COPY config/     ./config/
COPY mcp_server/ ./mcp_server/

# Built React frontend from stage 1
# The static-serving block in agent/api.py looks at <project_root>/static,
# so we copy the Vite output there.
COPY --from=frontend-builder /app/agent/static ./static

# Where SAR PDFs are written at runtime
RUN mkdir -p /app/data/sar_reports

# Cloud Run sets PORT=8080
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD exec uvicorn agent.api:app --host 0.0.0.0 --port ${PORT} --workers 1