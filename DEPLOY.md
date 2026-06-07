# SentryPay — Cloud Run Deployment Guide

Estimated time: **45 minutes** first time, ~5 minutes for redeploys.

## Architecture

```
┌─────────────────────────────────────────────────┐
│       Cloud Run service: sentrypay              │
│       https://sentrypay-xyz.run.app             │
│                                                 │
│  ┌───────────────────────────────────────────┐  │
│  │   FastAPI (port 8080)                     │  │
│  │   ├── /auth/*       → OAuth + JWT         │  │
│  │   ├── /gmail/*      → Gmail scan + status │  │
│  │   ├── /analyse      → manual check        │  │
│  │   ├── /sar/{id}     → SAR PDF download    │  │
│  │   ├── /decisions    → history             │  │
│  │   └── /*            → serves React app    │  │
│  └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
        │            │           │
        ▼            ▼           ▼
  Elastic Cloud  BigQuery    Vertex AI
```

One service, one URL, no CORS.

---

## Prerequisites

```bash
# Verify gcloud is installed and authenticated
gcloud --version
gcloud auth login
gcloud config set project sentry-pay

# Enable the APIs we need (one-time, idempotent)
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    containerregistry.googleapis.com \
    bigquery.googleapis.com \
    aiplatform.googleapis.com
```

---

## Setup (do once)

### 1. Place all deployment files at your project root

```
sentry-pay/
├── Dockerfile                       ← new
├── .dockerignore                    ← new
├── .gcloudignore                    ← new
├── deploy.sh                        ← new
├── env.cloudrun.yaml.template       ← new
├── agent/
│   └── api.py                       ← modify (append static-serving block)
├── frontend/
├── mcp_server/
├── config/
└── requirements.txt
```

### 2. Update `agent/api.py`

Append the contents of `agent_api_static_patch.py` to the **very end** of your existing `agent/api.py`.

Verify the patch landed:
```bash
grep "_STATIC_DIR" agent/api.py
```
Should return one match.

### 3. Create your env file

```bash
cp env.cloudrun.yaml.template env.cloudrun.yaml
```

Then edit `env.cloudrun.yaml` and paste in your real values from `.env`.
(Leave `GOOGLE_REDIRECT_URI` as the placeholder for now — you'll set it after the first deploy.)

### 4. Make the script executable

```bash
chmod +x deploy.sh
```

### 5. Grant the Cloud Run service account access to BigQuery and Vertex AI

```bash
# Get the default Compute service account
PROJECT_NUMBER=$(gcloud projects describe sentry-pay --format='value(projectNumber)')
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# Grant BigQuery + Vertex AI access
gcloud projects add-iam-policy-binding sentry-pay \
    --member="serviceAccount:${SA}" \
    --role="roles/bigquery.dataEditor"

gcloud projects add-iam-policy-binding sentry-pay \
    --member="serviceAccount:${SA}" \
    --role="roles/bigquery.jobUser"

gcloud projects add-iam-policy-binding sentry-pay \
    --member="serviceAccount:${SA}" \
    --role="roles/aiplatform.user"
```

---

## First Deploy

```bash
./deploy.sh
```

What happens:
1. `gcloud builds submit` — uploads your code to Cloud Build (~30s)
2. Cloud Build runs the Dockerfile (~4-8 minutes)
   - Stage 1: `npm ci && npm run build` for the frontend
   - Stage 2: `pip install -r requirements.txt` + copy code + static files
   - Pushes the image to `gcr.io/sentry-pay/sentrypay:latest`
3. `gcloud run deploy` — provisions the service (~1 minute)
4. Returns the public URL

At the end you'll see:
```
✓ Deployed successfully
Public URL: https://sentrypay-abc123def-uc.a.run.app
```

---

## Post-Deploy (one-time)

### 1. Update the OAuth redirect URI

Edit `env.cloudrun.yaml`:
```yaml
GOOGLE_REDIRECT_URI: "https://sentrypay-abc123def-uc.a.run.app/auth/callback"
```

### 2. Add the URI in Google Cloud Console

Go to:
- **Console → APIs & Services → Credentials**
- Click your OAuth 2.0 Client ID
- Under **Authorised redirect URIs**, click **+ ADD URI**
- Paste: `https://sentrypay-abc123def-uc.a.run.app/auth/callback`
- **Save**

### 3. Re-deploy with the updated redirect URI

```bash
./deploy.sh
```

---

## Smoke Tests

```bash
URL="https://sentrypay-abc123def-uc.a.run.app"

# 1. Frontend loads
curl -I "${URL}/"
# Expected: 200 OK, content-type: text/html

# 2. API responds
curl "${URL}/health" || curl "${URL}/auth/me"
# Expected: 401 (no JWT) or similar

# 3. Demo sign-in works
curl -X POST "${URL}/auth/demo"
# Expected: { "jwt": "...", "user": {...} }

# 4. Open in browser
open "${URL}"
# Click "View Demo Account" — should land on the dashboard
```

---

## Redeploys (future updates)

Just run:
```bash
./deploy.sh
```

Cloud Build re-uses cached layers, so subsequent builds take ~2-3 minutes instead of 8.

---

## Troubleshooting

### Build fails on `npm ci`
- Make sure `frontend/package-lock.json` is checked into git (not gitignored).

### Build fails on `pip install`
- Check `requirements.txt` includes all packages. Run `pip freeze > req.txt` locally and diff.

### App boots but errors with "credentials not found"
- The Cloud Run service account doesn't have BigQuery/Vertex AI access.
- Re-run the IAM commands in Setup step 5.

### "Failed to create user — BigQuery permission denied"
- Same as above. The service account needs `bigquery.dataEditor` + `bigquery.jobUser`.

### "OAuth redirect_uri_mismatch"
- The URI in `env.cloudrun.yaml` doesn't match the URI in Google Cloud Console.
- They MUST be exactly equal (including trailing slashes, http vs https).

### SAR PDFs fail to generate
- Cloud Run filesystem is ephemeral but writeable. The Dockerfile creates `/app/data/sar_reports`.
- If you need persistent storage, switch SAR storage to Cloud Storage (GCS bucket). Not needed for the hackathon demo.

### Cold starts feel slow
- First request after idle takes 5-10 seconds because Cloud Run is loading the container.
- For the demo, hit the URL once 30s before recording to "warm" the instance.

---

## Cost Estimate

For the hackathon (sporadic traffic), you'll likely spend **under $5/month**:
- Cloud Run: free tier covers 2M requests/month
- Cloud Build: free tier covers 120 build-minutes/day
- Container Registry: $0.026/GB/month (negligible)
- Cloud Build storage: ~$0.10/GB/month