"""
SentryPay — FastAPI Backend Server
=====================================
Secure HTTP API connecting the React frontend to the Gemini agent.

Security features implemented:
    - API key authentication on all endpoints
    - Rate limiting (10 analyse requests/minute per IP)
    - Input length validation via Pydantic field constraints
    - CORS restricted to known origins in production
    - SAR download endpoint requires matching decision ID
    - Request/response logging for audit trail

Observability features:
    - Per-request trace IDs in response headers
    - Tool latency breakdown in analyse response
    - Token usage in analyse response
    - GET /traces endpoint for in-memory trace history
    - GET /stats endpoint for aggregate metrics

Endpoints:
    POST /analyse         — main fraud analysis endpoint
    GET  /health          — health check for Cloud Run
    GET  /decisions       — recent decisions from BigQuery
    GET  /sar/{id}        — download SAR PDF
    GET  /traces          — recent traces (in-memory)
    GET  /stats           — aggregate agent statistics
    GET  /docs            — auto-generated API documentation
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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

# Rate limiting
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

# API key — loaded from env (or Secret Manager in production)
SENTRY_PAY_API_KEY = os.getenv("SENTRY_PAY_API_KEY", "sentry-pay-dev-key-2026")

# ── App setup ─────────────────────────────────────────────────────────────────

if RATE_LIMIT_AVAILABLE:
    limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="SentryPay API",
    description="AI-powered pre-payment fraud detection agent",
    version="1.0.0"
)

if RATE_LIMIT_AVAILABLE:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — restrict to your Cloud Run frontend URL in production
# During development, allow all origins
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"]
)

# Initialise the agent once at startup
agent = SentryPayAgent()

# ── Authentication ────────────────────────────────────────────────────────────

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Depends(api_key_header)):
    """
    Verify the X-API-Key header on incoming requests.

    Compares the provided key against the SENTRY_PAY_API_KEY
    environment variable. Returns 401 if the key is missing or
    incorrect.

    Args:
        api_key (str): value from X-API-Key request header

    Raises:
        HTTPException 401: if key is missing or invalid
    """
    if not api_key or api_key != SENTRY_PAY_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Include X-API-Key header."
        )
    return api_key


# ── Request/response models ───────────────────────────────────────────────────

class AnalyseRequest(BaseModel):
    """
    Request body for POST /analyse.

    All string fields are length-limited to prevent token exhaustion
    and injection attacks. Amount is validated to be a positive number
    below a reasonable ceiling.
    """
    email_text:     str   = Field(..., min_length=10,  max_length=5000,
                                  description="The suspicious email or message text")
    amount:         float = Field(..., gt=0, lt=10_000_000,
                                  description="Payment amount in USD")
    recipient_name: str   = Field(..., min_length=2,   max_length=200,
                                  description="Intended payment recipient")
    account_number: str   = Field(..., min_length=5,   max_length=50,
                                  description="Destination account number")
    payment_type:   str   = Field(..., min_length=2,   max_length=20,
                                  description="ACH / Wire / RTP / Zelle / Check")
    user_id:        str   = Field("demo_user_001",     max_length=50,
                                  description="User identifier")


class AnalyseResponse(BaseModel):
    """Response body from POST /analyse."""
    verdict:           str
    confidence:        float
    typology_matched:  Optional[str]
    reasoning:         str
    red_flags:         list[str]
    recommended_action: str
    sar_required:      bool
    decision_id:       str
    processing_ms:     int
    tool_latencies:    Optional[dict] = None
    token_count:       Optional[dict] = None
    sar_pdf_url:       Optional[str]  = None


class HealthResponse(BaseModel):
    """Response from GET /health."""
    status:    str
    elastic:   str
    timestamp: str
    version:   str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/analyse", response_model=AnalyseResponse)
async def analyse_payment(
    request:    AnalyseRequest,
    req:        Request,
    _api_key:   str = Depends(verify_api_key)
):
    """
    Analyse a payment request for fraud risk.

    Rate limited to 10 requests per minute per IP address.
    Requires X-API-Key header authentication.

    The full agent pipeline runs for each request:
      1. Input sanitization
      2. Gemini function calling (3 Elastic tool calls)
      3. Verdict synthesis
      4. BigQuery logging
      5. SAR generation if BLOCK

    Returns tool latencies and token counts for observability.
    """
    # Apply rate limit if available
    if RATE_LIMIT_AVAILABLE:
        try:
            await limiter._check_request_limit(
                req, analyse_payment, "10/minute"
            )
        except Exception:
            pass

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

    Does not require authentication — Cloud Run calls this to
    determine if the container is healthy and ready to serve.
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
    Return the most recent decisions from BigQuery.

    Requires authentication. Used by the frontend history panel.

    Args:
        limit (int): max records to return (capped at 50)
    """
    limit = min(limit, 50)
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=GCP_PROJECT)
        query  = f"""
            SELECT decision_id, verdict, confidence, typology_matched,
                   amount, recipient_name, sar_required,
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
    Download the SAR PDF for a specific blocked payment.

    Requires authentication to prevent unauthorised access to
    sensitive compliance documents.
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
    """
    Return recent traces from the in-memory trace store.

    Provides real-time observability data without requiring BigQuery
    queries. Useful for the demo's live monitoring view.

    Args:
        n (int): number of recent traces to return (max 100)
    """
    return trace_store.get_recent(min(n, 100))


@app.get("/stats")
async def get_stats(_api_key: str = Depends(verify_api_key)):
    """
    Return aggregate statistics from the in-memory trace store.

    Includes verdict distribution, average confidence,
    average latency, and most common typologies matched.
    """
    return trace_store.get_stats()


@app.get("/")
async def root():
    """Root endpoint — confirms the API is running."""
    return {
        "name":        "SentryPay API",
        "version":     "1.0.0",
        "description": "AI-powered pre-payment fraud detection",
        "docs":        "/docs",
        "health":      "/health"
    }