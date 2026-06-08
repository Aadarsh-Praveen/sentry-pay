#!/bin/bash
# deploy.sh — Build and deploy SentryPay to Cloud Run.
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh

set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────────
PROJECT_ID="${GCP_PROJECT_ID:-sentry-pay}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="sentrypay"
IMAGE_TAG="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:latest"
ENV_FILE="env.cloudrun.yaml"

# ─── Pre-flight checks ───────────────────────────────────────────────────────
echo "════════════════════════════════════════════════════════════════"
echo " SentryPay Cloud Run Deploy"
echo "════════════════════════════════════════════════════════════════"
echo "  Project:  ${PROJECT_ID}"
echo "  Region:   ${REGION}"
echo "  Service:  ${SERVICE_NAME}"
echo "  Image:    ${IMAGE_TAG}"
echo "════════════════════════════════════════════════════════════════"

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "ERROR: ${ENV_FILE} not found."
    echo "       cp env.cloudrun.yaml.template env.cloudrun.yaml"
    echo "       Then edit env.cloudrun.yaml with your real values."
    exit 1
fi

if [[ ! -f "Dockerfile" ]]; then
    echo "ERROR: Dockerfile not found in current directory."
    exit 1
fi

# Make sure gcloud is configured
gcloud config set project "${PROJECT_ID}" --quiet

# ─── Build the image with Cloud Build ────────────────────────────────────────
echo ""
echo "▶️ Building Docker image with Cloud Build..."
echo "  (this typically takes 4-8 minutes)"
gcloud builds submit --tag "${IMAGE_TAG}" --timeout 20m .

# ─── Deploy to Cloud Run ─────────────────────────────────────────────────────
echo ""
echo "▶️ Deploying to Cloud Run..."

gcloud run deploy "${SERVICE_NAME}" \
    --image           "${IMAGE_TAG}" \
    --region          "${REGION}" \
    --platform        managed \
    --allow-unauthenticated \
    --port            8080 \
    --memory          2Gi \
    --cpu             2 \
    --timeout         300 \
    --concurrency     80 \
    --min-instances   0 \
    --max-instances   10 \
    --env-vars-file   "${ENV_FILE}"

# ─── Done ────────────────────────────────────────────────────────────────────
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
    --region "${REGION}" --format='value(status.url)')

echo ""
echo "════════════════════════════════════════════════════════════════"
echo " ✓ Deployed successfully"
echo "════════════════════════════════════════════════════════════════"
echo "  Public URL:  ${SERVICE_URL}"
echo ""
echo "  Smoke test:"
echo "    curl ${SERVICE_URL}/auth/me"
echo ""
echo "  NEXT STEPS:"
echo "    1. Update GOOGLE_REDIRECT_URI in env.cloudrun.yaml to:"
echo "         ${SERVICE_URL}/auth/callback"
echo "    2. Add the same URI in Google Cloud Console →"
echo "       Credentials → OAuth 2.0 Client → Authorised redirect URIs"
echo "    3. Re-run ./deploy.sh to apply the new redirect URI"
echo "════════════════════════════════════════════════════════════════"