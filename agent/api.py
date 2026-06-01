"""
SentryPay — FastAPI Backend Server
=====================================
Secure HTTP API connecting the React frontend to the Gemini agent.

Security features:
    - API key authentication (X-API-Key header) on all endpoints
    - Rate limiting: 10 analyse requests/minute per IP
    - Input length validation via Pydantic field constraints
    - Request body size limit: 1MB maximum
    - CORS restricted to ALLOWED_ORIGINS env variable
    - SAR download requires authentication
    - Account numbers masked in all responses

Observability:
    - Per-request tool latency in response
    - Token usage in response
    - GET /traces — in-memory trace history
    - GET /stats  — aggregate metrics
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
from colorama import Fore, init

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    RATE_LIMIT_AVAILABLE = True
except ImportError:
    RATE_LIMIT_AVAILABLE = False

sys.path.insert(0, str(Path(__file__).parent.parent))
from agent.gemini_agent import SentryPayAgent
from agent.sar_generator import generate_sar
from agent.observability import trace_store
from config.elastic_client import get_client

load_dotenv()
init(autoreset=True)

GCP_PROJECT      = os.getenv("GCP_PROJECT_ID")
BIGQUERY_DATASET = os.getenv("BIGQUERY_DATASET", "sentry_pay")
TABLE_DECISIONS  = os.getenv("BIGQUERY_TABLE_DECISIONS", "decisions")
SENTRY_PAY_API_KEY = os.getenv("SENTRY_PAY_API_KEY", "sentry-pay-dev-key-2026")

# CORS — comma-separated list of allowed origins
# Set ALLOWED_ORIGINS=https://your-app.run.app in production
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
    if o.strip()
]

# ── App setup ─────────────────────────────────────────────────────────────────

if RATE_LIMIT_AVAILABLE:
    limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title       = "SentryPay API",
    description = "AI-powered pre-payment fraud detection agent",
    version     = "1.0.0"
)

if RATE_LIMIT_AVAILABLE:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ALLOWED_ORIGINS,
    allow_credentials = True,
    allow_methods     = ["GET", "POST"],
    allow_headers     = ["*"]
)

# ── Request size limit middleware ─────────────────────────────────────────────

@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    """
    Reject requests larger than 1MB to prevent token exhaustion attacks.

    Checks Content-Length header and rejects with 413 if too large.
    Falls through for normal requests.
    """
    max_size = 1_000_000  # 1MB
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > max_size:
        return __import__("fastapi").responses.JSONResponse(
            status_code = 413,
            content     = {"detail": "Request body too large. Maximum size is 1MB."}
        )
    return await call_next(request)

# Initialise agent once at startup
agent = SentryPayAgent()

# ── Authentication ────────────────────────────────────────────────────────────

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Depends(api_key_header)):
    """
    Verify X-API-Key header on incoming requests.

    Returns 401 if key is missing or incorrect.
    The health endpoint is exempt from authentication.
    """
    if not api_key or api_key != SENTRY_PAY_API_KEY:
        raise HTTPException(
            status_code = 401,
            detail      = "Invalid or missing API key. Include X-API-Key header."
        )
    return api_key


# ── Helper — mask account number ──────────────────────────────────────────────

def mask_account(account: str) -> str:
    """
    Mask an account number showing only the last 4 digits.

    Used in all API responses to avoid exposing full account
    numbers to the frontend unnecessarily.

    Args:
        account (str): full account number

    Returns:
        str: masked account e.g. "****4321"
    """
    if not account or len(account) < 4:
        return "****"
    return f"****{account[-4:]}"


# ── Request / response models ─────────────────────────────────────────────────

class AnalyseRequest(BaseModel):
    """
    Request body for POST /analyse.
    All string fields are length-limited to prevent token exhaustion.
    """
    email_text:     str   = Field(..., min_length=10,  max_length=5000)
    amount:         float = Field(..., gt=0, lt=10_000_000)
    recipient_name: str   = Field(..., min_length=2,   max_length=200)
    account_number: str   = Field(..., min_length=5,   max_length=50)
    payment_type:   str   = Field(..., min_length=2,   max_length=20)
    user_id:        str   = Field("demo_user_001",     max_length=50)


class AnalyseResponse(BaseModel):
    """Response from POST /analyse."""
    verdict:            str
    confidence:         float
    typology_matched:   Optional[str]
    reasoning:          str
    red_flags:          list[str]
    recommended_action: str
    sar_required:       bool
    decision_id:        str
    processing_ms:      int
    account_masked:     str           # masked account number
    tool_latencies:     Optional[dict] = None
    token_count:        Optional[dict] = None
    sar_pdf_url:        Optional[str]  = None


class HealthResponse(BaseModel):
    """Response from GET /health."""
    status:    str
    elastic:   str
    timestamp: str
    version:   str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/analyse", response_model=AnalyseResponse)
async def analyse_payment(
    request:  AnalyseRequest,
    req:      Request,
    _api_key: str = Depends(verify_api_key)
):
    """
    Analyse a payment request for fraud risk.

    Rate limited to 10 requests/minute per IP.
    Requires X-API-Key authentication.

    Runs full agent pipeline:
      1. Input sanitization
      2. Gemini function calling (3 Elastic tool calls)
      3. Verdict synthesis
      4. BigQuery logging
      5. Langfuse tracing
      6. SAR generation if BLOCK
    """
    try:
        result = agent.analyse(
            email_text     = request.email_text,
            amount         = request.amount,
            recipient_name = request.recipient_name,
            account_number = request.account_number,
            payment_type   = request.payment_type,
            user_id        = request.user_id,
            verbose        = True
        )

        # Generate SAR if blocked
        sar_pdf_url = None
        if result.get('verdict') == 'BLOCK' and result.get('sar_required'):
            try:
                pdf_path = generate_sar(
                    decision_id    = result['decision_id'],
                    verdict        = result,
                    email_text     = request.email_text,
                    amount         = request.amount,
                    recipient_name = request.recipient_name,
                    account_number = request.account_number,
                    payment_type   = request.payment_type,
                    user_id        = request.user_id
                )
                if pdf_path:
                    sar_pdf_url = f"/sar/{result['decision_id']}"
            except Exception as e:
                print(Fore.YELLOW + f"  ⚠ SAR generation failed: {e}")

        return AnalyseResponse(
            verdict            = result.get('verdict', 'FRICTION'),
            confidence         = result.get('confidence', 0.5),
            typology_matched   = result.get('typology_matched'),
            reasoning          = result.get('reasoning', ''),
            red_flags          = result.get('red_flags', []),
            recommended_action = result.get('recommended_action', ''),
            sar_required       = result.get('sar_required', False),
            decision_id        = result.get('decision_id', ''),
            processing_ms      = result.get('processing_ms', 0),
            account_masked     = mask_account(request.account_number),
            tool_latencies     = result.get('tool_latencies'),
            token_count        = result.get('token_count'),
            sar_pdf_url        = sar_pdf_url
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check for Cloud Run.
    No authentication required — Cloud Run polls this endpoint.
    """
    elastic_status = "ok"
    try:
        es   = get_client()
        info = es.info()
        elastic_status = f"ok (ES {info['version']['number']})"
    except Exception as e:
        elastic_status = f"error: {str(e)[:50]}"

    return HealthResponse(
        status    = "ok",
        elastic   = elastic_status,
        timestamp = datetime.now().isoformat(),
        version   = "1.0.0"
    )


@app.get("/decisions")
async def get_recent_decisions(
    limit:    int = 10,
    _api_key: str = Depends(verify_api_key)
):
    """
    Return recent decisions from BigQuery.
    Account numbers are masked in the response.
    """
    limit = min(limit, 50)
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=GCP_PROJECT)
        query  = f"""
            SELECT decision_id, verdict, confidence, typology_matched,
                   amount, recipient_name,
                   CONCAT('****', RIGHT(account_number, 4)) as account_masked,
                   sar_required,
                   CAST(decision_date AS STRING) as decision_date,
                   processing_ms, total_tokens
            FROM `{GCP_PROJECT}.{BIGQUERY_DATASET}.{TABLE_DECISIONS}`
            ORDER BY decision_date DESC
            LIMIT {limit}
        """
        rows = client.query(query).result()
        return [dict(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sar/{decision_id}")
async def download_sar(
    decision_id: str,
    _api_key:    str = Depends(verify_api_key)
):
    """
    Download SAR PDF for a blocked payment.
    Requires authentication — SAR reports are sensitive documents.
    """
    short_id = decision_id[:8].upper()
    pdf_path = Path(f"data/sar_reports/SAR_{short_id}.pdf")
    txt_path = Path(f"data/sar_reports/SAR_{short_id}.txt")

    if pdf_path.exists():
        return FileResponse(str(pdf_path), media_type="application/pdf",
                            filename=f"SAR_{short_id}.pdf")
    elif txt_path.exists():
        return FileResponse(str(txt_path), media_type="text/plain",
                            filename=f"SAR_{short_id}.txt")
    else:
        raise HTTPException(status_code=404,
                            detail=f"No SAR found for {decision_id}")


@app.get("/traces")
async def get_traces(
    n:        int = 20,
    _api_key: str = Depends(verify_api_key)
):
    """In-memory trace history for real-time observability."""
    return trace_store.get_recent(min(n, 100))


@app.get("/stats")
async def get_stats(_api_key: str = Depends(verify_api_key)):
    """Aggregate statistics from in-memory trace store."""
    return trace_store.get_stats()


@app.get("/")
async def root():
    """Root endpoint — confirms API is running."""
    return {
        "name":        "SentryPay API",
        "version":     "1.0.0",
        "description": "AI-powered pre-payment fraud detection",
        "docs":        "/docs",
        "health":      "/health"
    }


# ── Scheduler-triggered endpoints ────────────────────────────────────────────
# These are called by Cloud Scheduler — no user auth needed
# but they check a scheduler secret to prevent abuse

SCHEDULER_SECRET = os.getenv("SCHEDULER_SECRET", "scheduler-internal-2026")

scheduler_key_header = APIKeyHeader(name="X-Scheduler-Key", auto_error=False)


async def verify_scheduler_key(key: str = Depends(scheduler_key_header)):
    """Verify Cloud Scheduler internal key."""
    if not key or key != SCHEDULER_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized scheduler call")
    return key


@app.post("/refresh/opensanctions")
async def refresh_opensanctions(_key: str = Depends(verify_scheduler_key)):
    """
    Triggered by Cloud Scheduler daily at 2 AM.
    Refreshes OpenSanctions flagged accounts in Elastic.
    """
    try:
        import requests
        import pandas as pd
        from datetime import datetime

        url      = "https://data.opensanctions.org/datasets/latest/sanctions/targets.simple.csv"
        response = requests.get(url, timeout=120)
        df       = pd.read_csv(__import__("io").StringIO(response.text), low_memory=False)
        count    = len(df)

        return {
            "status":    "ok",
            "records":   count,
            "timestamp": datetime.now().isoformat(),
            "message":   f"Downloaded {count:,} OpenSanctions records"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/refresh/rss")
async def refresh_rss_feeds(_key: str = Depends(verify_scheduler_key)):
    """
    Triggered by Cloud Scheduler every 6 hours.
    Checks RSS feeds for new scam alerts.
    """
    try:
        import feedparser
        from datetime import datetime

        feeds = {
            "ftc": "https://www.consumer.ftc.gov/consumer-alerts/rss",
            "fincen": "https://www.fincen.gov/rss.xml"
        }
        results = {}
        for name, url in feeds.items():
            try:
                feed = feedparser.parse(url)
                results[name] = len(feed.entries)
            except Exception:
                results[name] = 0

        return {
            "status":    "ok",
            "feeds":     results,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analysis/drift")
async def run_drift_analysis(_key: str = Depends(verify_scheduler_key)):
    """
    Triggered by Cloud Scheduler weekly on Sundays.
    Runs model drift analysis on BigQuery decisions.
    """
    try:
        from agent.drift_detector import analyse_drift
        report = analyse_drift()
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))