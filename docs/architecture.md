# SentryPay — Architecture

## System Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           USER (Browser)                                 │
│  React + Vite SPA   ←   served from same Cloud Run service               │
└──────────────────────────────┬───────────────────────────────────────────┘
                               │  HTTPS
                               │  - JWT (Bearer)        for user endpoints
                               │  - X-API-Key header    for payment APIs
                               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│            FastAPI Backend  —  Cloud Run (single service)                │
│                                                                          │
│  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────────┐     │
│  │ JWT auth         │  │ Rate Limiter     │  │ 1 MB body cap       │     │
│  │ OAuth2 / Demo    │  │ 10 req/min/IP    │  │ Pydantic validation │     │
│  └──────────────────┘  └──────────────────┘  └─────────────────────┘     │
│                                                                          │
│  Routes:                                                                 │
│   • /auth/google, /auth/callback, /auth/demo, /auth/me                   │
│   • /gmail/scan, /gmail/scan/progress, /gmail/status, /gmail/emails      │
│   • /analyse                       (manual fraud check)                  │
│   • /sar/{id}                      (download SAR PDF)                    │
│   • /decisions, /traces, /stats    (audit + observability)               │
│   • /feedback/*, /learning/stats   (continuous learning loop)            │
│   • /*                             (catch-all serves React SPA)          │
└──────────────────────────────┬───────────────────────────────────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
   ┌─────────────────┐  ┌──────────────┐  ┌──────────────────┐
   │  Gmail API      │  │ Gemini Agent │  │ SAR PDF Generator│
   │  • OAuth scopes │  │ 2.5 Flash    │  │ (ReportLab)      │
   │  • Label apply  │  │              │  │                  │
   │  • Real-time    │  │ Function-    │  │ FinCEN-format    │
   │    poll (5 min) │  │ calling loop │  │ Auto on BLOCK    │
   └─────────────────┘  └──────┬───────┘  └──────────────────┘
                               │
                               │  MCP protocol
                               │  (stdio + HTTP/SSE)
                               ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │                  SentryPay MCP Server (FastMCP)                 │
   │                                                                 │
   │  Tool 1  search_scam_typologies      kNN vector search          │
   │  Tool 2  check_beneficiary_account   structured lookup          │
   │  Tool 3  check_payment_velocity      per-user aggregations      │
   └────────────────────────────────┬────────────────────────────────┘
                                    │
                                    ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │                Elasticsearch Serverless 9.5.0                   │
   │                                                                 │
   │   • scam_typologies        (306 docs, 768-dim kNN vectors)      │
   │   • beneficiary_intel      (68,564 flagged accounts)            │
   │   • customer_transactions  (per-user from Gmail history)        │
   │   • user_baselines         (per-user behavioural profile)       │
   │   • email_verdicts         (audit trail, dedupe by SHA256 id)   │
   └─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │              BigQuery (audit log) + Langfuse (LLM traces)       │
   └─────────────────────────────────────────────────────────────────┘
```

---

## Request Flow: Manual Payment Analysis

```
1. User submits payment via React Manual Check page
       │
       ▼
2. Browser POST /analyse  (X-API-Key + JSON body)
       │
       ▼
3. FastAPI validates input (Pydantic), enforces rate limit, masks account
       │
       ▼
4. SentryPayAgent (Gemini 2.5 Flash, with response_schema)
       │
       │  Function-calling loop — up to 8 iterations:
       │
       ├─ Tool call 1:  search_scam_typologies(query=email_excerpt)
       │     → MCP server → Vertex AI embed → Elastic kNN search
       │
       ├─ Tool call 2:  check_beneficiary_account(account_number)
       │     → MCP server → Elastic structured term query
       │
       └─ Tool call 3:  check_payment_velocity(user_id, amount, …)
             → MCP server → Elastic get user_baseline + aggregate
       │
       ▼
5. Gemini synthesises:  {verdict, confidence, typology, red_flags, reasoning}
       │
       ▼
6. If verdict == BLOCK and sar_required:
       └─ generate_sar(…) → ReportLab → data/sar_reports/SAR_<id>.pdf
       │
       ▼
7. Parallel writes:
       ├─ Elastic email_verdicts          (audit trail)
       ├─ BigQuery decisions table        (compliance audit)
       ├─ Langfuse trace                  (LLM observability)
       └─ Response → browser
              {verdict, reasoning, sar_pdf_url, decision_id, …}
```

---

## Request Flow: Gmail Auto-Monitor

```
Background asyncio task started on FastAPI lifespan event.
Runs every GMAIL_POLL_INTERVAL_SECONDS (default 300s).

For each user with baseline_built = True (queried from BigQuery):

  1. List Gmail messages since last scan
  2. For each new email:
       a. extract_payment_details()  ← Gemini with response_schema
       b. Skip if not a payment request or amount missing
       c. Deduplicate by SHA256("user_id::email_id")
       d. Run SentryPayAgent.analyse() ← full 3-tool reasoning
       e. If BLOCK + sar_required → generate SAR PDF
       f. Write verdict to Elastic email_verdicts
       g. Apply Gmail label: 🔴 BLOCKED | 🟡 REVIEW | 🟢 SAFE
  3. Update last-scan timestamp in memory
```

---

## OAuth + Demo Mode

```
Sign in with Google:
  Browser /auth/google  →  Redirect to Google OAuth
  Google  →  /auth/callback?code=…
  Backend:
    - Exchange code → access + refresh tokens
    - Get userinfo
    - Upsert user in BigQuery `users` table
    - Issue JWT (HS256, 7-day expiry)
    - Redirect to FRONTEND_URL/#jwt=<token>
  Browser:
    - useAuth hook reads JWT from URL hash
    - Stores in localStorage
    - Triggers baseline build if new_user

Demo Mode (judges):
  Browser POST /auth/demo
  Backend:
    - Look up sentrypaydemo@gmail.com in BigQuery
    - Issue JWT marked {"demo": true}
    - Return JWT directly (no OAuth round-trip)
  Browser:
    - Store JWT, redirect to dashboard
    - Skip onboarding (demo user already has baseline)
```

---

## Data Pipeline (one-time, ~30 min)

```
RAW SOURCES
│
├── FBI IC3 PDFs (2023-2024)
│   └── pdfplumber → clean text
│       └── Gemini parse → 51 base typologies
│           └── Gemini augment → 306 typologies (variations)
│               └── Vertex AI text-embedding-004 (768-dim)
│                   └── Elastic: scam_typologies  (kNN index)
│
├── OpenSanctions CSV (~63k entities)
│   └── pandas filter → finance-relevant only
│       └── risk score normalisation
│           └── Elastic: beneficiary_intel
│
├── OFAC SDN list
│   └── Merged into OpenSanctions pipeline
│
└── Synthetic mule accounts (500) + clean accounts (5,000)
    └── Faker → realistic IBAN/routing
        └── Elastic: beneficiary_intel
```

Per-user transactions + baselines are NOT pre-built. They're generated dynamically from each user's 90-day Gmail history when they sign in for the first time (or click "Rebuild Baseline").

---

## Continuous Learning Flywheel

```
Verdict displayed in dashboard
       │
       ▼
User feedback: "Yes, confirmed fraud"  /  "No, this is safe"
       │
       ▼
POST /feedback/confirm-block  or  /feedback/mark-safe
       │
       ├─ Update Elastic email_verdicts.human_verdict
       │
       ├─ If user confirmed fraud:
       │     → Add beneficiary account to beneficiary_intel
       │       with risk_score=1.0, flag_reason="community_confirmed"
       │       → All other users benefit
       │
       └─ Log to BigQuery for analytics
       │
       ▼
Aggregate metrics surfaced at /learning/stats
```

---

## Security Architecture

```
Defense in depth:

  Browser → HTTPS only (Cloud Run TLS termination)
        │
        ▼
  Cloud Run service
    ├─ JWT auth on user-scoped endpoints (Authorization: Bearer)
    ├─ API-Key auth on payment endpoints (X-API-Key header)
    ├─ Rate limit: 10 /analyse req/min/IP (slowapi)
    ├─ Body size limit: 1 MB (middleware)
    ├─ Pydantic strict validation (length, range, type)
    ├─ CORS restricted to ALLOWED_ORIGINS env var
    └─ Non-root container user (Cloud Run default)
        │
        ▼
  Application layer
    ├─ Account numbers masked in all logs (****1234)
    ├─ Prompt-injection guard in Gemini system prompt
    ├─ Stdout writes redirected to stderr in MCP stdio mode
    └─ No long-lived credentials in Docker image
        │
        ▼
  Cloud / Secret storage
    ├─ GitHub Secrets (encrypted at rest by GitHub)
    ├─ Cloud Run env vars (encrypted at rest by Google KMS)
    ├─ Service account keys scoped to minimum IAM roles
    └─ Roadmap: migrate secrets to Google Secret Manager
```

---

## Observability

Every agent request emits three telemetry artifacts:

### Langfuse trace
```
trace: sentry_pay_analysis (decision_id)
├── span: search_scam_typologies
│   ├── input:  { query, top_k }
│   ├── output: { matches, top_match, top_score }
│   └── latency_ms, status
├── span: check_beneficiary_account
│   ├── input:  { account_number }
│   ├── output: { found, risk_score, flag_reasons }
│   └── latency_ms, status
├── span: check_payment_velocity
│   ├── input:  { user_id, amount, recipient, account }
│   ├── output: { mean, max_normal, deviation, is_anomaly, … }
│   └── latency_ms, status
└── span: gemini_reasoning
    ├── prompt_tokens, completion_tokens
    ├── response_schema validation
    └── final verdict JSON
```

### BigQuery `decisions` row
```
decision_id, verdict, confidence, typology_matched,
reasoning, red_flags (array), amount, recipient_name,
account_number_masked, email_snippet (500 chars),
sar_required, decision_date, processing_ms,
prompt_tokens, completion_tokens, total_tokens,
tool_latencies_json
```

### In-memory trace store
- Last ~1,000 decisions accessible via `/traces` and `/stats`
- Aggregate distribution of BLOCK/FRICTION/ALLOW
- Avg confidence + latency + tokens
- Top matched typologies

---

## Elastic Index Schemas

### scam_typologies
| Field | Type | Description |
|-------|------|-------------|
| typology_id | keyword | `T-XXXXXXXX` |
| name | text | Fraud pattern name |
| description | text | How the scam works |
| embedding | dense_vector(768) | Semantic embedding (text-embedding-004) |
| indicators | keyword[] | Trigger phrases |
| loss_avg_usd | float | Average loss |
| source | keyword | FBI IC3 / Gemini augmented |
| is_augmented | boolean | AI-generated variation flag |

### beneficiary_intel
| Field | Type | Description |
|-------|------|-------------|
| entity_id | keyword | Unique ID |
| account_number | keyword | Bank account / IBAN |
| entity_name | text | Owner name |
| risk_score | float | 0.0 (clean) — 1.0 (high) |
| flag_reasons | keyword[] | Why flagged |
| case_count | integer | How many cases involve this account |
| first_flagged | date | When it entered the index |
| datasets | keyword | OpenSanctions / OFAC / community |

### customer_transactions (per-user, from Gmail)
| Field | Type | Description |
|-------|------|-------------|
| transaction_id | keyword | `gmail_<message_id>` |
| user_id | keyword | Owner |
| timestamp | date | Email date |
| amount | float | Amount (USD) |
| recipient_name | text | Vendor |
| account_number | keyword | Destination |
| payment_type | keyword | ACH / Wire / RTP / … |
| sender_domain | keyword | Email sender domain |
| is_confirmation | boolean | Past payment vs request |

### user_baselines
| Field | Type | Description |
|-------|------|-------------|
| user_id | keyword | Owner |
| mean_payment | float | Average (after IQR outlier removal) |
| std_payment | float | Stddev |
| median_payment | float | Median |
| max_normal | float | Q3 + 1.5×IQR — anomaly threshold |
| known_accounts | keyword[] | Previously paid accounts |
| known_vendors | keyword[] | Previously paid vendors |
| preferred_rail | keyword | Most common payment_type |
| transaction_count | integer | Total txns in baseline |
| built_at | date | When baseline was last rebuilt |

### email_verdicts (audit trail)
| Field | Type | Description |
|-------|------|-------------|
| verdict_id | keyword | SHA256(user_id::email_id)[:24] |
| user_id | keyword | Owner |
| email_id | keyword | Gmail message ID |
| email_subject | text | Email subject |
| sender | keyword | From address |
| sender_domain | keyword | Domain only |
| amount | double | Payment amount |
| recipient_name | keyword | Vendor |
| account_number | keyword | Destination |
| agent_verdict | keyword | BLOCK / FRICTION / ALLOW |
| agent_confidence | float | 0.0 — 1.0 |
| human_verdict | keyword | User's feedback (or null) |
| typology_matched | keyword | Fraud type if matched |
| decision_id | keyword | Cross-ref to BigQuery + SAR |
| timestamp | date | Decision date |
| sar_generated | boolean | Whether SAR PDF exists |
| sar_pdf_url | keyword | `/sar/{decision_id}` |
| learning_applied | boolean | Has feedback been propagated |

---

## CI/CD Pipeline

```
git push origin main
       │
       ▼
GitHub Actions  (.github/workflows/ci.yml)
   │
   ├── Job 1: lint  (flake8, non-blocking)
   │
   └── Job 2: deploy
        ├── Authenticate via GCP_SA_KEY secret
        ├── gcloud builds submit  (async + poll for completion)
        │     ├── Stage 1: Node 20-alpine — npm ci + npm run build
        │     └── Stage 2: python:3.12-slim — pip install + copy code
        ├── Tag image as :latest
        ├── gcloud run deploy with --set-env-vars  (15 secrets)
        ├── Smoke test: curl /
        ├── Smoke test: curl -X POST /auth/demo
        └── Print deployment summary with public URL
```

Total build time: **~3-5 min** on cached layers, **~8-12 min** on cold builds.

---

## Cloud Run Configuration

| Setting | Value |
|---------|-------|
| Memory | 2 GiB |
| CPU | 2 vCPU |
| Concurrency | 80 requests per instance |
| Min instances | 0 (scale to zero on idle) |
| Max instances | 10 |
| Timeout | 300 s |
| Port | 8080 (uvicorn binds via $PORT) |
| Auth | `--allow-unauthenticated` (frontend is public) |

The single-service architecture (FastAPI serves both API and React SPA) eliminates CORS complexity and gives judges a single URL to test.

---

## Future Architecture Evolution

Items deferred from the hackathon scope:

1. **Workload Identity Federation** instead of service account JSON keys for GitHub Actions
2. **Google Secret Manager** instead of Cloud Run env vars for app secrets
3. **Cloud Storage for SAR PDFs** — Cloud Run filesystem is ephemeral; SARs are regenerated on demand
4. **Multi-region failover** behind a global load balancer
5. **Cloud Armor** for WAF / DDoS protection
6. **Cloud Scheduler-triggered refresh jobs** for OpenSanctions + RSS feeds (endpoints already exist at `/refresh/*` and `/analysis/drift`, ready to wire up)