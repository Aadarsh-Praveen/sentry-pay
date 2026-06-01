# 🛡️ SentryPay

**AI-powered pre-payment fraud detection for small businesses and community banks.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Built with Gemini](https://img.shields.io/badge/Built%20with-Gemini%202.5-blue)](https://cloud.google.com/vertex-ai)
[![Elastic](https://img.shields.io/badge/Partner-Elastic-orange)](https://elastic.co)
[![Google Cloud](https://img.shields.io/badge/Cloud-Google%20Cloud-red)](https://cloud.google.com)

> Built for the **Google Cloud Rapid Agent Hackathon 2026** — Elastic Track

---

## The Problem

Every year, $1 trillion is lost to payment scams. A fraudster sends a fake email claiming a supplier changed their bank account. The victim authorizes the payment themselves — so banks won't refund it. Nobody watches the moment between receiving the suspicious email and clicking Send.

**SentryPay does.**

---

## What It Does

SentryPay is an AI agent that intercepts at the payment initiation moment — before money leaves. Paste the suspicious email and payment details, and SentryPay:

1. **Searches** 306 fraud patterns using semantic vector search (Elastic)
2. **Scores** the destination account against 68,000+ flagged accounts (Elastic ES|QL)
3. **Checks** if the payment is anomalous for this user's history (Elastic ES|QL)
4. **Reasons** over all three signals with Gemini 2.5 Flash
5. **Decides**: 🔴 BLOCK / 🟡 FRICTION / 🟢 ALLOW

If blocked, automatically generates a **FinCEN SAR draft** for compliance officers.

---

## Architecture

```
User (Web App)
      │
      ▼
FastAPI Backend (Cloud Run)
      │
      ▼
Google Cloud Agent Builder
Gemini 2.5 Flash
      │
      ├── Elastic MCP Tool 1: Vector search → scam_typologies
      ├── Elastic MCP Tool 2: ES|QL mule scoring → beneficiary_intel
      └── Elastic MCP Tool 3: ES|QL velocity check → customer_transactions
      │
      ▼
Verdict (BLOCK / FRICTION / ALLOW)
      │
      ├── BigQuery audit log (every decision)
      ├── Langfuse trace (every tool call)
      └── SAR PDF (if BLOCK)
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Agent reasoning | Gemini 2.5 Flash (Vertex AI) |
| Vector search | Elasticsearch 9.5 Serverless |
| Fraud ES\|QL tools | Elastic Agent Builder MCP |
| Audit logging | Google BigQuery |
| Observability | Langfuse Cloud |
| Secret management | GCP Secret Manager |
| Deployment | Google Cloud Run |
| Backend | FastAPI + Python 3.12 |
| Frontend | React + Tailwind CSS |

---

## Project Structure

```
sentry-pay/
├── agent/
│   ├── api.py                  # FastAPI server (4 endpoints)
│   ├── gemini_agent.py         # Gemini function calling loop
│   ├── tools.py                # 3 Elastic MCP tool functions
│   ├── bigquery_logger.py      # Audit log writer
│   ├── observability.py        # Langfuse tracing
│   ├── sar_generator.py        # SAR PDF generation
│   ├── cli_demo.py             # CLI test runner
│   └── regression_tests.py    # 20-case regression suite
├── config/
│   ├── elastic_client.py       # Elasticsearch client factory
│   └── secrets_manager.py     # GCP Secret Manager integration
├── data_pipeline/
│   ├── step1_extract_pdfs.py   # FBI IC3 PDF extraction
│   ├── step2_parse_typologies.py  # Gemini fraud pattern parsing
│   ├── step3_augment_typologies.py # Data augmentation (50→306)
│   ├── step4_process_opensanctions.py # Sanctions data processing
│   ├── step5_generate_synthetic_transactions.py
│   ├── step6_generate_embeddings.py # Vertex AI embeddings
│   ├── step7_load_to_elastic.py    # Bulk index loading
│   └── step8_validate.py           # Phase 1 gate validation
├── setup/
│   ├── create_elastic_indices.py
│   ├── create_bigquery_tables.py
│   └── update_bigquery_schema.py
├── tests/
│   ├── test_tools.py
│   └── test_agent.py
├── cloud-run/
│   ├── Dockerfile
│   ├── service.yaml
│   └── cloudbuild.yaml
├── docs/
│   └── architecture.md
├── .github/workflows/ci.yml
└── run_phase1.py               # Full data pipeline runner
```

---

## Quick Start

### Prerequisites
- Python 3.12+
- Google Cloud account with Vertex AI enabled
- Elastic Cloud Serverless account
- Langfuse account (free)

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/sentry-pay.git
cd sentry-pay
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your credentials:
# ELASTIC_ENDPOINT, ELASTIC_API_KEY
# GCP_PROJECT_ID
# LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL
# SENTRY_PAY_API_KEY
```

### 3. Authenticate with Google Cloud

```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com bigquery.googleapis.com
```

### 4. Run the data pipeline

```bash
# Create Elastic indices
python setup/create_elastic_indices.py

# Create BigQuery tables
python setup/create_bigquery_tables.py

# Run full data pipeline (takes ~30 minutes)
python run_phase1.py
```

### 5. Start the backend

```bash
python -m uvicorn agent.api:app --reload --port 8000
```

API docs available at: `http://localhost:8000/docs`

### 6. Test the agent

```bash
# Run 3 demo scenarios
python agent/cli_demo.py

# Run regression test suite (20 cases)
python agent/regression_tests.py
```

---

## API Reference

All endpoints require `X-API-Key` header.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/analyse` | POST | Analyse a payment request for fraud |
| `/health` | GET | Health check (no auth required) |
| `/decisions` | GET | Recent decisions from BigQuery |
| `/sar/{id}` | GET | Download SAR PDF for a blocked payment |
| `/traces` | GET | Recent traces (in-memory) |
| `/stats` | GET | Aggregate agent statistics |

### Example request

```bash
curl -X POST http://localhost:8000/analyse \
  -H "X-API-Key: sentry-pay-dev-key-2026" \
  -H "Content-Type: application/json" \
  -d '{
    "email_text": "Hi Sarah, our bank details have changed...",
    "amount": 47000,
    "recipient_name": "Apex Scaffolding Ltd",
    "account_number": "GB94METRO00000087654321",
    "payment_type": "Wire",
    "user_id": "demo_user_001"
  }'
```

### Example response

```json
{
  "verdict": "BLOCK",
  "confidence": 0.90,
  "typology_matched": "Business Email Compromise",
  "reasoning": "Payment strongly matches BEC typology...",
  "red_flags": ["New account", "Amount anomalous", "Banking details change"],
  "recommended_action": "Block and contact supplier via verified channel",
  "sar_required": true,
  "decision_id": "uuid-here",
  "processing_ms": 12658,
  "sar_pdf_url": "/sar/uuid-here"
}
```

---

## Elastic MCP Integration

SentryPay uses the Elastic Agent Builder MCP server with three custom tools:

**Tool 1 — `search_scam_typologies`**
Vector similarity search against 306 fraud patterns extracted from FBI IC3 reports and augmented with Gemini. Returns the top 3 matching typologies with cosine similarity scores.

**Tool 2 — `check_beneficiary_account`**
ES|QL query against 68,564 beneficiary records (OpenSanctions + OFAC + synthetic mule accounts). Returns risk score, flag status, and flag reason.

**Tool 3 — `check_payment_velocity`**
ES|QL query against user transaction history and behavioural baselines. Returns anomaly signals: is_amount_anomalous, z_score, is_new_account, is_new_vendor.

---

## Data Sources

| Source | Type | Records | Update frequency |
|--------|------|---------|-----------------|
| FBI IC3 Reports (2023-2024) | Real, public | 51 base typologies | Yearly |
| Gemini augmentation | Synthetic | 255 variations | On demand |
| OpenSanctions | Real, public | 63,064 entities | Daily |
| OFAC SDN List | Real, public | Included in OpenSanctions | Weekly |
| Synthetic mule accounts | Generated | 500 | On demand |
| Synthetic clean accounts | Generated | 5,000 | On demand |
| Demo transactions | Generated | 153 | On demand |

---

## Security

- API key authentication on all endpoints
- Rate limiting (10 requests/minute per IP)
- Input validation with Pydantic field constraints
- Input sanitization (control character removal, length limits)
- Prompt injection guard in Gemini system prompt
- Account numbers masked in BigQuery logs (last 4 digits only)
- Secrets stored in GCP Secret Manager
- Non-root user in Docker container
- CORS restricted to allowed origins

---

## Observability

Every agent decision produces:
- **Langfuse trace** — full tool call timeline, token counts, latency breakdown
- **BigQuery record** — immutable audit log with verdict, reasoning, and token usage
- **In-memory entry** — accessible via `/traces` and `/stats` endpoints

Regression test suite: 20 fixed cases, 90% pass rate, run on every deployment.

---

## Deployment

```bash
# Build and deploy to Cloud Run
gcloud builds submit --config cloud-run/cloudbuild.yaml

# Or manually
docker build -t gcr.io/PROJECT_ID/sentry-pay .
docker push gcr.io/PROJECT_ID/sentry-pay
gcloud run deploy sentry-pay \
  --image gcr.io/PROJECT_ID/sentry-pay \
  --region us-central1 \
  --timeout 300 \
  --memory 2Gi
```

---

## Hackathon

Built for the [Google Cloud Rapid Agent Hackathon 2026](https://rapid-agent.devpost.com) — **Elastic Track**.

- **Partner**: Elastic (MCP server integration)
- **Cloud**: Google Cloud (Vertex AI, BigQuery, Cloud Run, Secret Manager)
- **Model**: Gemini 2.5 Flash

---

## License

MIT License — see [LICENSE](LICENSE) file.