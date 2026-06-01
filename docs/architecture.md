# SentryPay — Architecture

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER (Browser)                              │
│                    React PWA — Cloud Run                            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ HTTPS POST /analyse
                               │ X-API-Key header
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    FastAPI Backend — Cloud Run                      │
│                                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────────────┐   │
│  │ Rate Limiter│  │ API Key Auth │  │ Request Size Limit (1MB)  │   │
│  └─────────────┘  └──────────────┘  └───────────────────────────┘   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│               Google Cloud Agent Builder                            │
│                   Gemini 2.5 Flash                                  │
│                                                                     │
│   System prompt: fraud detection rules + security guard             │
│   Input sanitization + prompt injection protection                  │
│                                                                     │
│   Function calling loop (up to 8 iterations):                       │
└────────────┬──────────────────┬──────────────────┬──────────────────┘
             │                  │                  │
             ▼                  ▼                  ▼
┌────────────────┐  ┌──────────────────┐  ┌─────────────────────────┐
│ Elastic MCP    │  │ Elastic MCP      │  │ Elastic MCP             │
│ Tool 1         │  │ Tool 2           │  │ Tool 3                  │
│                │  │                  │  │                         │
│ Vector search  │  │ ES|QL mule score │  │ ES|QL velocity check    │
│ scam_typologies│  │ beneficiary_intel│  │ customer_transactions   │
│ 306 patterns   │  │ 68,564 accounts  │  │ 153 transactions        │
│ 768-dim embed  │  │ risk 0.0-1.0     │  │ + user_baselines        │
└────────────────┘  └──────────────────┘  └─────────────────────────┘
             │                  │                  │
             └──────────────────┴──────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Gemini Verdict Synthesis                         │
│                                                                     │
│   {verdict, confidence, typology_matched, reasoning, red_flags}     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
┌───────────────┐  ┌──────────────────┐  ┌─────────────────────────┐
│ BigQuery      │  │ Langfuse Cloud   │  │ SAR PDF Generator       │
│ Audit Log     │  │ Trace per call   │  │ (BLOCK only)            │
│               │  │ Tool spans       │  │ FinCEN-format draft     │
│ Immutable     │  │ Token counts     │  │ Auto-generated          │
│ Every verdict │  │ Latency breakdown│  │ data/sar_reports/       │
└───────────────┘  └──────────────────┘  └─────────────────────────┘
```

---

## Data Pipeline Architecture

```
RAW SOURCES
│
├── FBI IC3 PDFs (2023-2024)
│   └── pdfplumber → clean text
│       └── Gemini parse → 51 fraud typologies
│           └── Gemini augment → 306 typologies
│               └── Vertex AI embed → 768-dim vectors
│                   └── Elastic: scam_typologies index
│
├── OpenSanctions CSV (daily)
│   └── pandas filter → finance-relevant
│       └── risk score computation
│           └── Elastic: beneficiary_intel index
│
├── OFAC SDN List (weekly)
│   └── merge with OpenSanctions
│
├── Synthetic mule accounts (500)
│   └── Faker + high risk scores
│       └── Elastic: beneficiary_intel index
│
├── Synthetic clean accounts (5,000)
│   └── Faker + low risk scores
│       └── Elastic: beneficiary_intel index
│
└── Synthetic transactions (153)
    └── Faker + realistic patterns
        └── IQR baseline computation
            └── Elastic: customer_transactions + user_baselines
```

---

## Automated Data Refresh (Cloud Scheduler)

```
Every day at 2 AM UTC:
    Cloud Scheduler → Cloud Function → refresh_opensanctions.py
    → filter → risk score → upsert → Elastic beneficiary_intel

Every 6 hours:
    Cloud Scheduler → Cloud Function → monitor_rss_feeds.py
    → Action Fraud UK, FTC, FinCEN RSS
    → parse new scam alerts → embed → upsert → Elastic scam_typologies

Every Sunday at 4 AM UTC:
    Cloud Scheduler → Cloud Function → run_drift_analysis.py
    → BigQuery query → confidence trend analysis
    → alert if score drops below 85%
```

---

## Security Architecture

```
Request flow:
  Browser → [HTTPS TLS] → Cloud Run
  Cloud Run → [X-API-Key check]
  Cloud Run → [Rate limit: 10/min/IP]
  Cloud Run → [Request size: max 1MB]
  Cloud Run → [Input sanitization]
  Gemini prompt → [Injection guard in system prompt]
  BigQuery write → [Account numbers masked: ****4321]
  Secret Manager → [All API keys, never in code or .env in prod]
```

---

## Observability Stack

```
Every agent request produces:

Langfuse Cloud:
  Trace: sentry_pay_analysis
  ├── Span: search_scam_typologies  (latency, input, output)
  ├── Span: check_beneficiary_account (latency, input, output)
  ├── Span: check_payment_velocity (latency, input, output)
  └── Span: gemini_reasoning (tokens, prompt, response)

BigQuery:
  decisions table row:
    decision_id, verdict, confidence, typology_matched,
    reasoning, red_flags, amount, recipient_name,
    account_number (masked), email_snippet (500 chars),
    sar_required, decision_date, processing_ms,
    prompt_tokens, completion_tokens, total_tokens,
    tool_latencies_json

In-memory (GET /traces, GET /stats):
  Recent 1,000 traces with verdict distribution,
  avg confidence, avg latency, top typologies
```

---

## Elastic Index Schemas

### scam_typologies
| Field | Type | Description |
|-------|------|-------------|
| typology_id | keyword | Unique ID (T-XXXXXXXX) |
| typology_name | text | Fraud pattern name |
| description | text | How the scam works |
| description_vector | dense_vector(768) | Semantic embedding |
| red_flags | keyword[] | Warning signs |
| target_victim | keyword | Who gets targeted |
| typical_payment_type | keyword | Wire/ACH/Zelle etc |
| avg_loss_usd | float | Average loss amount |
| source | keyword | FBI IC3/GASA/FTC etc |
| is_augmented | boolean | AI-generated variation |

### beneficiary_intel
| Field | Type | Description |
|-------|------|-------------|
| entity_id | keyword | Unique ID |
| account_number | keyword | Bank account |
| entity_name | text | Company/person name |
| risk_score | float | 0.0 (clean) to 1.0 (high) |
| risk_category | keyword | LOW/MEDIUM/HIGH/UNKNOWN |
| is_flagged | boolean | True if sanctioned/mule |
| flag_reason | text | Why flagged |
| datasets | keyword | OpenSanctions/OFAC etc |

### customer_transactions
| Field | Type | Description |
|-------|------|-------------|
| transaction_id | keyword | Unique ID |
| user_id | keyword | Which demo user |
| date | date | Payment date |
| amount | float | Amount in USD |
| recipient_name | text | Who was paid |
| account_number | keyword | Destination account |
| payment_type | keyword | ACH/Wire/RTP etc |

### user_baselines
| Field | Type | Description |
|-------|------|-------------|
| user_id | keyword | Which user |
| mean_payment | float | Average payment (outliers removed) |
| std_payment | float | Standard deviation |
| max_normal | float | IQR upper fence (anomaly threshold) |
| known_accounts | keyword[] | Previously paid accounts |
| known_vendors | keyword[] | Previously paid vendors |