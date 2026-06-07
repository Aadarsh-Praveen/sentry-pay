# ═════════════════════════════════════════════════════════════════════════════
# Stage 1 — Build the React frontend with Vite
# ═════════════════════════════════════════════════════════════════════════════
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Install dependencies first (better Docker layer caching)
COPY frontend/package*.json ./
RUN npm ci --silent

# Build the production bundle
COPY frontend/ ./
RUN npm run build

# Output is at /app/frontend/dist


# ═════════════════════════════════════════════════════════════════════════════
# Stage 2 — Python runtime that serves FastAPI + built frontend
# ═════════════════════════════════════════════════════════════════════════════
FROM python:3.12-slim

WORKDIR /app

# System dependencies for some Python packages (cryptography, lxml etc.)
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

# Built React frontend (from stage 1)
COPY --from=frontend-builder /app/frontend/dist ./static

# Where SAR PDFs are written at runtime
RUN mkdir -p /app/data/sar_reports

# Cloud Run sets PORT=8080 by default
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
EXPOSE 8080

# Start the FastAPI server
CMD exec uvicorn agent.api:app --host 0.0.0.0 --port ${PORT} --workers 1