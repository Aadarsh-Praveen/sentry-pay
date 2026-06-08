# SentryPay — Deployment Guide

SentryPay deploys to **Google Cloud Run** automatically on every push to `main`, via **GitHub Actions**.

| Path | Time | When to use |
|------|------|-------------|
| **GitHub Actions** (default) | Push → live in ~5 min | Every normal change |
| **`./deploy.sh`** (manual) | One command from your laptop | Hotfixes, first-time setup, debugging the Dockerfile |

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│       Cloud Run service: sentrypay              │
│       https://sentrypay-6c5idgmgza-uc.a.run.app │
│                                                 │
│  ┌───────────────────────────────────────────┐  │
│  │   FastAPI (port 8080)                     │  │
│  │   ├── /auth/*       → OAuth + JWT + demo  │  │
│  │   ├── /gmail/*      → Gmail scan + status │  │
│  │   ├── /analyse      → manual check        │  │
│  │   ├── /sar/{id}     → SAR PDF download    │  │
│  │   ├── /decisions    → BigQuery history    │  │
│  │   ├── /api          → API metadata        │  │
│  │   └── /*            → serves React app    │  │
│  └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
        │            │           │           │
        ▼            ▼           ▼           ▼
  Elastic Cloud  BigQuery   Vertex AI    Gmail API
```

One service, one URL, no CORS. The Dockerfile builds the React frontend in stage 1, then copies it into a Python runtime in stage 2. FastAPI serves both the API and the static frontend.

---

## One-Time Setup (~30 min)

You only do this once. Future deploys happen automatically on `git push`.

### 1. Enable required GCP APIs

```bash
gcloud config set project sentry-pay

gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    containerregistry.googleapis.com \
    bigquery.googleapis.com \
    aiplatform.googleapis.com \
    gmail.googleapis.com \
    iam.googleapis.com
```

### 2. Grant the Cloud Run runtime service account access to BigQuery + Vertex AI

This is the service account the *running container* uses to talk to GCP services:

```bash
PROJECT_NUMBER=$(gcloud projects describe sentry-pay --format='value(projectNumber)')
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

for role in roles/bigquery.dataEditor roles/bigquery.jobUser roles/aiplatform.user
do
    gcloud projects add-iam-policy-binding sentry-pay \
        --member="serviceAccount:${RUNTIME_SA}" \
        --role="${role}"
done
```

### 3. Create the GitHub Actions deploy service account

This is a *separate* service account that GitHub Actions uses to build + deploy:

```bash
PROJECT_ID="sentry-pay"
SA_NAME="github-actions-deploy"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create ${SA_NAME} \
    --display-name="GitHub Actions Deployer" \
    --project=${PROJECT_ID}

for role in \
    roles/run.admin \
    roles/cloudbuild.builds.editor \
    roles/storage.admin \
    roles/iam.serviceAccountUser \
    roles/artifactregistry.admin \
    roles/viewer
do
    gcloud projects add-iam-policy-binding ${PROJECT_ID} \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="${role}"
done

# Generate a key file (used as GitHub Secret GCP_SA_KEY)
gcloud iam service-accounts keys create gcp-sa-key.json \
    --iam-account=${SA_EMAIL} \
    --project=${PROJECT_ID}

echo "✓ Key created: gcp-sa-key.json — DO NOT COMMIT"
```

⚠️ **`gcp-sa-key.json` is sensitive.** Make sure your `.gitignore` excludes it:

```bash
grep -q "^gcp-sa-key.json$" .gitignore || echo "gcp-sa-key.json" >> .gitignore
```

### 4. Configure GitHub Secrets

Open: **GitHub repo → Settings → Secrets and variables → Actions → New repository secret**

Add **all of these**:

| Secret name | Value source |
|-------------|--------------|
| `GCP_PROJECT_ID` | `sentry-pay` |
| `GCP_SA_KEY` | **Entire contents** of `gcp-sa-key.json` |
| `ELASTIC_ENDPOINT` | From your `.env` |
| `ELASTIC_API_KEY` | From your `.env` |
| `SENTRY_PAY_API_KEY` | From your `.env` |
| `GOOGLE_CLIENT_ID` | From your `.env` |
| `GOOGLE_CLIENT_SECRET` | From your `.env` |
| `GOOGLE_REDIRECT_URI` | Use a placeholder for first deploy — you'll update it after |
| `FRONTEND_URL` | Placeholder for first deploy |
| `JWT_SECRET` | From your `.env` |
| `DEMO_USER_EMAIL` | `sentrypaydemo@gmail.com` |
| `LANGFUSE_PUBLIC_KEY` | From your `.env` |
| `LANGFUSE_SECRET_KEY` | From your `.env` |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` |

### 5. First deploy

```bash
git add .
git commit -m "Initial deploy"
git push origin main
```

Watch the build at: `https://github.com/<your-org>/sentry-pay/actions`

After ~8 minutes, the workflow will print your public URL — e.g. `https://sentrypay-abc123-uc.a.run.app`.

### 6. Wire up OAuth with the real URL

Now that you have your Cloud Run URL, point Google OAuth at it.

#### a. Update the GitHub Secrets

| Secret | New value |
|--------|-----------|
| `GOOGLE_REDIRECT_URI` | `https://<your-url>/auth/callback` |
| `FRONTEND_URL` | `https://<your-url>` |

#### b. Add the redirect URI in Google Cloud Console

- **Console → APIs & Services → Credentials**
- Click your OAuth 2.0 Client ID
- Under **Authorised redirect URIs**, click **+ ADD URI**
- Paste: `https://<your-url>/auth/callback`
- Click **Save**

#### c. Trigger a redeploy

```bash
git commit --allow-empty -m "Deploy with production OAuth URIs"
git push origin main
```

---

## What Happens on Every Push to `main`

```
┌─────────────────────────────────────────────────────┐
│  GitHub Actions  (.github/workflows/ci.yml)         │
│                                                     │
│  Job 1 — Code quality                               │
│    ├─ Checkout                                      │
│    ├─ Python 3.12 setup                             │
│    └─ flake8 (non-blocking)                         │
│                                                     │
│  Job 2 — Deploy to Cloud Run                        │
│    ├─ Authenticate via GCP_SA_KEY                   │
│    ├─ Cloud Build (async + poll)                    │
│    │   ├─ Stage 1: npm ci && npm run build          │
│    │   └─ Stage 2: pip install + copy code          │
│    ├─ Tag image as latest                           │
│    ├─ gcloud run deploy with all env vars           │
│    ├─ Smoke test (frontend)                         │
│    ├─ Smoke test (demo auth)                        │
│    └─ Deployment summary with public URL            │
└─────────────────────────────────────────────────────┘
```

Subsequent deploys take **~3-5 minutes** thanks to Cloud Build layer caching.

---

## Manual Deploy (alternative path)

For first-time setup, hotfixes, or debugging the Dockerfile without going through GitHub:

### Setup

```bash
cp env.cloudrun.yaml.template env.cloudrun.yaml
# Edit env.cloudrun.yaml — paste real values from your .env
chmod +x deploy.sh
```

### Deploy

```bash
./deploy.sh
```

This script:
1. `gcloud builds submit` — uploads to Cloud Build
2. Cloud Build runs the Dockerfile
3. `gcloud run deploy` — provisions Cloud Run with env vars from `env.cloudrun.yaml`
4. Prints the public URL + next steps

---

## Smoke Tests

```bash
URL="https://sentrypay-6c5idgmgza-uc.a.run.app"

# 1. Frontend loads
curl -I "${URL}/"
# Expected: 200 OK, content-type: text/html

# 2. Health endpoint
curl "${URL}/health"
# Expected: {"status":"ok","elastic":"ok (ES 9.5.0)",...}

# 3. Demo sign-in works
curl -X POST "${URL}/auth/demo"
# Expected: {"jwt":"eyJ...", "user": {...}}

# 4. Browser smoke test
open "${URL}"
# Click "View Demo Account" → should land on the dashboard
```

---

## Troubleshooting

### Build fails on `npm ci`
- `frontend/package-lock.json` must be checked into git (not gitignored)
- Check `frontend/package.json` for unresolvable dependency versions

### Build fails on `pip install`
- Compare `requirements.txt` against `pip freeze` locally:
  ```bash
  pip freeze > /tmp/req_local.txt
  diff requirements.txt /tmp/req_local.txt
  ```

### Container fails to start: `NameError: name 'os' is not defined`
- A module is using `os.getenv(...)` without `import os` at the top
- Check the Cloud Run logs: `gcloud run services logs read sentrypay --region=us-central1 --limit=50`

### Container fails: "credentials not found"
- The **runtime** service account (default Compute SA) doesn't have BigQuery/Vertex AI access
- Re-run the IAM commands in [Setup step 2](#2-grant-the-cloud-run-runtime-service-account-access-to-bigquery--vertex-ai)

### OAuth fails with `redirect_uri_mismatch`
- The URI in your `GOOGLE_REDIRECT_URI` GitHub Secret must exactly match the URI in Google Cloud Console (including `https`, trailing slash, port)
- Common mistake: secret has `http://` instead of `https://`

### OAuth callback redirects to `localhost:5173` in production
- The `FRONTEND_URL` GitHub Secret is missing or wrong
- After OAuth callback, the backend uses `FRONTEND_URL` to redirect the user with their JWT
- Verify: `gcloud run services describe sentrypay --region=us-central1 --format='value(spec.template.spec.containers[0].env[?name=`FRONTEND_URL`].value)'`

### Build succeeded on GCB but GitHub Actions reports failure
- This used to happen due to `gcloud builds submit` log streaming requiring Viewer role
- Fixed in `ci.yml` by using `--async` + polling. If you still hit it, add `roles/viewer` to the GitHub Actions service account

### SAR PDFs can't be downloaded after a redeploy
- Cloud Run filesystem is **ephemeral** — every new revision starts fresh
- For persistent SAR storage, switch to Cloud Storage (a GCS bucket). Not needed for the demo
- The PDFs are auto-regenerated when a verdict is re-issued

### Cold starts feel slow in the demo
- First request after idle takes 5-10 seconds (Cloud Run loads the container)
- For demo videos, warm the instance 30 seconds before recording:
  ```bash
  curl https://sentrypay-6c5idgmgza-uc.a.run.app/health
  ```

---

## Cost Estimate

For hackathon traffic patterns (sporadic, low volume), expect **under $5/month total**:

| Service | Monthly cost |
|---------|--------------|
| Cloud Run | Free tier covers 2M requests/month |
| Cloud Build | Free tier covers 120 build-minutes/day |
| Container Registry | ~$0.026/GB/month |
| BigQuery | Free tier covers 1 TB queries/month |
| Vertex AI (Gemini Flash) | ~$0.001 per analysis |
| Elasticsearch Serverless | Tied to your Elastic Cloud plan |

---

## Production Hardening (post-hackathon)

For a real production deployment, you'd want to:

1. **Migrate secrets to Google Secret Manager** instead of Cloud Run env vars
2. **Replace the JSON service account key** with [Workload Identity Federation](https://github.com/google-github-actions/auth#setting-up-workload-identity-federation)
3. **Set up a custom domain** (e.g. `app.sentrypay.io`) via Cloud Run domain mappings
4. **Enable Cloud Armor** for WAF + DDoS protection
5. **Switch SAR storage to Cloud Storage** with signed URLs for download
6. **Run multiple regions** behind a global load balancer
7. **Enable Cloud Audit Logging** for IAM + Cloud Run + BigQuery
8. **Add Cloud Monitoring alerts** for error rate, P95 latency, cold-start frequency