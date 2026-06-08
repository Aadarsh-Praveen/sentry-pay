# SentryPay

**AI agent that stops payment fraud before the wire goes out.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Built with Gemini](https://img.shields.io/badge/Built%20with-Gemini%202.5-blue)](https://cloud.google.com/vertex-ai)
[![Elastic](https://img.shields.io/badge/Partner-Elastic-orange)](https://elastic.co)
[![MCP](https://img.shields.io/badge/Protocol-MCP-purple)](https://modelcontextprotocol.io)
[![Cloud Run](https://img.shields.io/badge/Deploy-Cloud%20Run-red)](https://cloud.google.com/run)

> 🚀 **Live demo:** [sentrypay-6c5idgmgza-uc.a.run.app](https://sentrypay-6c5idgmgza-uc.a.run.app)
> No sign-in needed — click **"View Demo Account"**.


---

## The Problem

**Business Email Compromise (BEC) costs companies $2.9 billion a year.** Median single loss: $50,000. Recovery rate after the wire goes out: under 30%.

The attack is brutally simple. A fraudster compromises a vendor's email account, then sends "the vendor's" finance team an urgent message: *"We've changed banks — here's our new wiring info."* The team updates the payment details. The money goes to the fraudster.

No off-the-shelf tool gives a small business the same multi-source, real-time fraud intelligence that big banks pay millions for. **SentryPay puts a fraud analyst behind every Gmail inbox.**

---

## What It Does

SentryPay watches your Gmail in real time. For every payment email — automatically detected or manually submitted — it produces a **BLOCK / FRICTION / ALLOW** verdict in under 2 seconds, grounded in three independent intelligence sources:

1. **kNN vector search** across 306 known fraud typologies
2. **Sanctions lookup** against 68,564 flagged beneficiary accounts
3. **Behavioural anomaly detection** against the user's 90-day Gmail payment baseline

When a BLOCK verdict fires, SentryPay **auto-generates a FinCEN-compliant draft Suspicious Activity Report (SAR)** ready for the compliance officer.

It also exposes its three fraud-detection tools through a **custom MCP server**, so any MCP-compatible agent (Claude Desktop, Cursor, Gemini, ADK) can plug in.

---

## Architecture

```
                          ┌──────────────────────┐
   User's Gmail  ────────▶│   SentryPay Agent    │
   (OAuth + monitor)      │   (Gemini 2.5 Flash) │
                          └──────────┬───────────┘
                                     │
            ┌────────────────────────┼────────────────────────┐
            ▼                        ▼                        ▼
  ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
  │ search_scam_     │   │ check_           │   │ check_payment_   │
  │ typologies       │   │ beneficiary_     │   │ velocity         │
  │ (kNN vector)     │   │ account          │   │ (per-user        │
  │                  │   │ (sanctions +     │   │ baseline)        │
  │                  │   │  community)      │   │                  │
  └─────────┬────────┘   └─────────┬────────┘   └─────────┬────────┘
            │                      │                      │
            └──────────────────────┼──────────────────────┘
                                   ▼
                  ┌──────────────────────────────┐
                  │   Elasticsearch Serverless   │
                  │   5 indices:                 │
                  │   • scam_typologies (kNN)    │
                  │   • beneficiary_intel        │
                  │   • customer_transactions    │
                  │   • user_baselines           │
                  │   • email_verdicts           │
                  └──────────────────────────────┘
                              │
                              ▼
            ┌──────────────────────────────────────┐
            │   BigQuery (audit) + Langfuse (LLM)  │
            │     + SAR PDF (FinCEN-compliant)     │
            └──────────────────────────────────────┘
```

The killer architectural choice: **all five datasets in a single Elasticsearch substrate** — typologies, sanctions, transactions, behavioural baseline, and audit trail. Cross-channel correlation that normally requires multiple systems happens in one kNN query.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Reasoning** | Gemini 2.5 Flash via Vertex AI (structured-output JSON schemas) |
| **Tool protocol** | Model Context Protocol (MCP) via FastMCP — stdio + HTTP/SSE |
| **Search substrate** | Elasticsearch Serverless 9.5.0 — kNN vector + structured + aggregations in one cluster |
| **Embeddings** | Vertex AI `text-embedding-004` (768-dim) |
| **Backend** | FastAPI on Cloud Run, JWT auth, rate-limited |
| **Frontend** | React + Vite, served from the same Cloud Run service (no CORS) |
| **Gmail integration** | OAuth 2.0, 90-day backfill, 5-minute real-time monitor, Gmail labels |
| **Audit + observability** | BigQuery for decision trail, Langfuse for LLM traces |
| **Compliance** | Auto-generated SAR PDFs (ReportLab, FinCEN-compliant format) |
| **CI/CD** | GitHub Actions → Cloud Build → Cloud Run |

---

## Project Structure

```
sentry-pay/
├── .github/workflows/
│   └── ci.yml                    # CI/CD: lint → build → deploy on push to main
├── agent/
│   ├── api.py                    # FastAPI server (serves API + React SPA)
│   ├── gemini_agent.py           # Gemini function-calling reasoning loop
│   ├── tools.py                  # Direct Elastic tool implementations
│   ├── auth.py                   # JWT + OAuth helpers
│   ├── auth_routes.py            # /auth/* endpoints (Google + Demo)
│   ├── gmail_client.py           # Gmail API wrapper
│   ├── email_extractor.py        # Gemini extraction of payment details
│   ├── email_monitor.py          # Background monitor (5-min polling)
│   ├── history_builder.py        # 90-day baseline construction
│   ├── sar_generator.py          # FinCEN-compliant SAR PDF generator
│   ├── observability.py          # Langfuse tracing
│   ├── bigquery_logger.py        # BigQuery audit log writer
│   └── regression_tests.py       # 20-case regression suite
├── mcp_server/
│   ├── server.py                 # FastMCP server exposing 3 Elastic tools
│   ├── test_client.py            # End-to-end MCP demo client
│   └── README.md                 # MCP architecture + how to run
├── frontend/
│   ├── src/
│   │   ├── pages/                # Login, EmailDashboard, Onboarding
│   │   ├── components/           # Header, Dashboard, HistoryDrawer, ...
│   │   ├── hooks/useAuth.js      # JWT + OAuth + Demo Mode
│   │   └── api/sentrypay.js      # Axios client w/ JWT injection
│   ├── public/favicon.svg
│   └── vite.config.js            # Builds to agent/static
├── config/
│   ├── elastic_client.py
│   └── secrets_manager.py
├── data_pipeline/                # One-time data preparation (8 steps)
├── setup/
│   ├── create_elastic_indices.py
│   ├── create_bigquery_tables.py
│   ├── seed_gmail_demo.py
│   └── send_test_email.py
├── Dockerfile                    # Multi-stage: Node (frontend) → Python (runtime)
├── .dockerignore
├── .gcloudignore
├── deploy.sh                     # Local one-command deploy (alternative to CI/CD)
├── env.cloudrun.yaml.template
├── DEPLOY.md                     # Full deployment guide
├── requirements.txt
└── LICENSE
```

---

## Try It Yourself

### Option 1 — Live Demo (zero setup)

Visit **[sentrypay-6c5idgmgza-uc.a.run.app](https://sentrypay-6c5idgmgza-uc.a.run.app)**, click **"View Demo Account"**, and you're inside:

- 32 pre-analysed emails (3 blocked BEC attempts, 14 review, 15 safe)
- Click any 🔴 BLOCKED row → expand → download the auto-generated SAR PDF
- Visit the Manual Check page to submit your own payment for analysis

### Option 2 — Run it locally

See [Local Development](#local-development) below.

---

## API Reference

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api` | GET | None | API metadata |
| `/health` | GET | None | Health check + Elastic status |
| `/auth/google` | GET | None | Start Google OAuth flow |
| `/auth/callback` | GET | None | OAuth callback handler |
| `/auth/demo` | POST | None | One-click demo sign-in |
| `/auth/me` | GET | JWT | Current user info |
| `/auth/logout` | POST | JWT | Sign out |
| `/gmail/scan` | POST | JWT | Trigger 90-day baseline build |
| `/gmail/scan/progress` | GET | JWT | Baseline build status |
| `/gmail/status` | GET | JWT | Monitor status |
| `/gmail/emails` | GET | JWT | List verdicts |
| `/analyse` | POST | API key | Manual payment analysis |
| `/sar/{decision_id}` | GET | API key | Download generated SAR PDF |
| `/decisions` | GET | API key | Recent decisions from BigQuery |
| `/feedback/*` | POST | JWT | Human feedback for continuous learning |
| `/learning/stats` | GET | JWT | Continuous learning metrics |
| `/traces` | GET | API key | Recent LLM traces |
| `/stats` | GET | API key | Aggregate agent statistics |

### Example: manual payment analysis

```bash
curl -X POST https://sentrypay-6c5idgmgza-uc.a.run.app/analyse \
  -H "X-API-Key: ${SENTRY_PAY_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "email_text": "Hi Sarah, our bank details have changed urgently...",
    "amount": 47000,
    "recipient_name": "Apex Scaffolding Ltd",
    "account_number": "GB94METRO00000087654321",
    "payment_type": "Wire",
    "user_id": "demo_user_001"
  }'
```

### Response

```json
{
  "verdict": "BLOCK",
  "confidence": 0.90,
  "typology_matched": "Business Email Compromise",
  "reasoning": "Payment strongly matches BEC typology — urgent banking change, anomalous amount...",
  "red_flags": [
    "Strong BEC typology match",
    "Urgent request to change bank details",
    "Payment amount is 9.08× the user's normal mean"
  ],
  "recommended_action": "Block and contact supplier via verified phone number (not email)",
  "sar_required": true,
  "decision_id": "303ee20c-dc10-4d43-a43a-33ba43bdfa01",
  "processing_ms": 1742,
  "sar_pdf_url": "/sar/303ee20c-dc10-4d43-a43a-33ba43bdfa01"
}
```

---

## MCP Server

SentryPay exposes its three fraud-detection tools through a custom **Model Context Protocol (MCP) server**. Any MCP-compatible agent can discover and call them.

```bash
# stdio transport (for Claude Desktop / Cursor)
python -m mcp_server.server

# HTTP/SSE transport (for remote agents)
python -m mcp_server.server --http --port 9000

# End-to-end test
python -m mcp_server.test_client
```

See [`mcp_server/README.md`](mcp_server/README.md) for the full architecture and Claude Desktop integration instructions.

---

## Data Sources

| Source | Type | Records | Update frequency |
|--------|------|---------|-----------------|
| FBI IC3 Reports (2023-2024) | Real, public | 51 base typologies | Yearly |
| Gemini augmentation | Synthetic | 255 variations → 306 total | On demand |
| OpenSanctions | Real, public | 63,064 entities | Daily |
| OFAC SDN List | Real, public | Included in OpenSanctions | Weekly |
| Synthetic mule accounts | Generated | 500 | On demand |
| Synthetic clean accounts | Generated | 5,000 | On demand |
| Gmail (per-user) | Real | 90-day rolling window | Real-time monitor |

---

## Security

- **OAuth 2.0** for user identity, **JWT** (HS256, 7-day expiry) for sessions
- **API key** auth on payment-analysis endpoints
- **Rate limiting** — 10 analyse requests/min per IP (slowapi)
- **CORS** restricted to allowed origins env var
- **Pydantic** input validation with strict field constraints + 1MB body limit
- **Account numbers masked** in all logs (last 4 digits only)
- **Secrets** stored in GitHub Secrets and Cloud Run env vars
- **No long-lived credentials in the image** — multi-stage Docker build excludes `.env`
- **CI/CD service account** scoped to minimum IAM roles
- **Non-root user** in container (Cloud Run default)

---

## Observability

| Sink | Captures | Used for |
|------|---------|----------|
| **Langfuse** | Full tool-call timeline, token counts, latency, prompts | Debugging + cost analysis |
| **BigQuery** | Immutable decision record (verdict, reasoning, all flags) | Audit + analytics |
| **In-memory trace store** | Recent decisions | `/traces` + `/stats` endpoints |

**Regression suite:** 20 fixed scenarios spanning BEC, romance scams, invoice fraud, and legitimate payments. Current pass rate: **18/20 (90%)**.

---

## Local Development

### Prerequisites

- Python 3.12+
- Node.js 20+
- Google Cloud account with Vertex AI + BigQuery + Gmail API enabled
- Elastic Cloud Serverless account
- Langfuse account (free tier)

### Setup

```bash
git clone https://github.com/Aadarsh-Praveen/sentry-pay.git
cd sentry-pay

# Backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Frontend
cd frontend && npm install && cd ..

# Environment
cp .env.example .env
# Edit .env with your credentials

# Google Cloud auth
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com bigquery.googleapis.com gmail.googleapis.com

# One-time data preparation (~30 min)
python setup/create_elastic_indices.py
python setup/create_bigquery_tables.py
python run_phase1.py
```

### Run

```bash
# Terminal 1 — backend
python -m uvicorn agent.api:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev
```

Open `http://localhost:5173`.

### Test

```bash
python agent/cli_demo.py            # CLI demo
python agent/regression_tests.py    # 20-case regression suite
python -m mcp_server.test_client    # MCP end-to-end test
```

---

## Deployment

Production deploys happen automatically on every push to `main` via GitHub Actions. See [`DEPLOY.md`](DEPLOY.md) for the full CI/CD setup.

For manual one-off deploys, use `./deploy.sh`.

---

## Continuous Learning

When a user confirms a verdict (or marks a false positive), SentryPay:

1. Updates the `email_verdicts` index with the corrected verdict
2. If fraud is confirmed, the beneficiary account is auto-added to `beneficiary_intel` so other users benefit
3. Aggregate stats are exposed via `/learning/stats`

This creates a community-driven flywheel — the more users review verdicts, the smarter SentryPay gets for everyone.

---



- **Partner integration:** Custom MCP server exposing 3 Elastic-backed fraud detection tools
- **Cloud:** Cloud Run, Cloud Build, Container Registry, Vertex AI, BigQuery, IAM
- **Model:** Gemini 2.5 Flash with structured-output JSON schemas
- **Data:** Elasticsearch Serverless 9.5.0 — 5 indices, kNN vector + structured + aggregations

---

## What's Next

- **Slack + Microsoft Teams integration** — BEC happens via DMs too
- **Bank API integration** — block at the wire rail, not just the email
- **Multi-tenant compliance dashboard** for CFOs monitoring whole orgs
- **OAuth Verified status** so any Gmail user can sign in without whitelisting
- **Fine-tuned classifier** trained on community verdicts — sub-cent inference

---

## License

[MIT License](LICENSE) — free to use, study, and build upon.

---

<p align="center">
  <strong>SentryPay</strong> — AI agent that stops payment fraud before the wire goes out.<br>
  <a href="https://sentrypay-6c5idgmgza-uc.a.run.app">Live demo</a> ·
  <a href="DEPLOY.md">Deployment guide</a> ·
  <a href="mcp_server/README.md">MCP server</a>
</p>