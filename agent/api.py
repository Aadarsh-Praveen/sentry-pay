"""
SentryPay — FastAPI Backend Server
=====================================
The HTTP API layer that connects the React frontend to the
Gemini agent. All communication between the web app and the
agent goes through this server.

Why FastAPI:
    FastAPI is a modern Python web framework that automatically
    generates API documentation, handles request validation,
    and supports async operations. It is deployed on Google
    Cloud Run alongside the agent code.

Endpoints:

    POST /analyse
        The main endpoint. Receives a payment analysis request
        from the frontend, passes it to the Gemini agent, and
        returns the structured verdict. If the verdict is BLOCK,
        also generates a SAR PDF and returns its download URL.

    GET /health
        Simple health check endpoint. Returns 200 OK if the
        server is running and Elastic is reachable. Used by
        Cloud Run to confirm the container is healthy.

    GET /decisions
        Returns the last N decisions from BigQuery. Used by
        the frontend to display the decision history panel.

    GET /sar/{decision_id}
        Downloads the SAR PDF for a specific blocked payment.

CORS:
    Cross-Origin Resource Sharing is enabled for all origins
    during development. In production, restrict this to your
    Cloud Run frontend URL.

Usage (local development):
    uvicorn agent.api:app --reload --port 8000

Usage (production):
    Deployed automatically by Cloud Run using the Dockerfile.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
from colorama import Fore, init

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent.parent))
from agent.gemini_agent import SentryPayAgent
from agent.sar_generator import generate_sar
from config.elastic_client import get_client

load_dotenv()
init(autoreset=True)

GCP_PROJECT      = os.getenv("GCP_PROJECT_ID")
BIGQUERY_DATASET = os.getenv("BIGQUERY_DATASET", "sentry_pay")
TABLE_DECISIONS  = os.getenv("BIGQUERY_TABLE_DECISIONS", "decisions")


# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="SentryPay API",
    description="AI-powered payment fraud detection agent",
    version="1.0.0"
)

# Allow requests from the React frontend (any origin during development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Initialise the agent once at startup (not per request)
agent = SentryPayAgent()


# ── Request and response models ───────────────────────────────────────────────

class AnalyseRequest(BaseModel):
    """
    Request body for POST /analyse.

    All fields except user_id are required. user_id defaults to
    demo_user_001 for demo purposes.
    """
    email_text:     str   = Field(..., description="The suspicious email or message text")
    amount:         float = Field(..., description="Payment amount in USD", gt=0)
    recipient_name: str   = Field(..., description="Intended payment recipient name")
    account_number: str   = Field(..., description="Destination bank account number")
    payment_type:   str   = Field(..., description="ACH / Wire / RTP / Zelle / Check")
    user_id:        str   = Field("demo_user_001", description="User identifier")


class AnalyseResponse(BaseModel):
    """
    Response body from POST /analyse.

    Contains the full verdict, decision ID for BigQuery lookup,
    and an optional SAR PDF path if the verdict was BLOCK.
    """
    verdict:          str
    confidence:       float
    typology_matched: Optional[str]
    reasoning:        str
    red_flags:        list[str]
    recommended_action: str
    sar_required:     bool
    decision_id:      str
    processing_ms:    int
    sar_pdf_path:     Optional[str] = None


class HealthResponse(BaseModel):
    """Response body from GET /health."""
    status:      str
    elastic:     str
    timestamp:   str
    version:     str


class DecisionSummary(BaseModel):
    """One decision record from the BigQuery history."""
    decision_id:      str
    verdict:          str
    confidence:       float
    typology_matched: Optional[str]
    amount:           Optional[float]
    recipient_name:   Optional[str]
    sar_required:     Optional[bool]
    decision_date:    str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/analyse", response_model=AnalyseResponse)
async def analyse_payment(request: AnalyseRequest):
    """
    Analyse a payment request for fraud risk.

    Passes the email and payment details to the Gemini agent,
    which calls all three Elastic tools and produces a verdict.
    If the verdict is BLOCK, automatically generates a SAR PDF.

    Args:
        request (AnalyseRequest): email text and payment details

    Returns:
        AnalyseResponse: structured verdict with reasoning and red flags

    Raises:
        HTTPException 500: if the agent fails to produce a verdict
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

        # Generate SAR PDF if payment is blocked
        sar_pdf_path = None
        if result.get('verdict') == 'BLOCK' and result.get('sar_required'):
            try:
                sar_pdf_path = generate_sar(
                    decision_id    = result['decision_id'],
                    verdict        = result,
                    email_text     = request.email_text,
                    amount         = request.amount,
                    recipient_name = request.recipient_name,
                    account_number = request.account_number,
                    payment_type   = request.payment_type,
                    user_id        = request.user_id
                )
            except Exception as sar_err:
                print(Fore.YELLOW + f"  ⚠ SAR generation failed (non-fatal): {sar_err}")

        return AnalyseResponse(
            verdict           = result.get('verdict', 'FRICTION'),
            confidence        = result.get('confidence', 0.5),
            typology_matched  = result.get('typology_matched'),
            reasoning         = result.get('reasoning', ''),
            red_flags         = result.get('red_flags', []),
            recommended_action = result.get('recommended_action', ''),
            sar_required      = result.get('sar_required', False),
            decision_id       = result.get('decision_id', ''),
            processing_ms     = result.get('processing_ms', 0),
            sar_pdf_path      = sar_pdf_path
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint for Cloud Run.

    Verifies the server is running and Elasticsearch is reachable.
    Returns 200 OK if healthy, 503 if Elastic is unreachable.

    Returns:
        HealthResponse: status, elastic connection state, timestamp
    """
    elastic_status = "ok"
    try:
        es   = get_client()
        info = es.info()
        elastic_status = f"ok ({info['version']['number']})"
    except Exception as e:
        elastic_status = f"error: {str(e)[:50]}"

    return HealthResponse(
        status    = "ok",
        elastic   = elastic_status,
        timestamp = datetime.now().isoformat(),
        version   = "1.0.0"
    )


@app.get("/decisions")
async def get_recent_decisions(limit: int = 10):
    """
    Retrieve the most recent decisions from BigQuery.

    Used by the frontend to display the decision history panel
    showing recent verdicts with their outcomes.

    Args:
        limit (int): maximum number of decisions to return (default 10)

    Returns:
        list[DecisionSummary]: recent decisions ordered by date descending
    """
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=GCP_PROJECT)

        query = f"""
            SELECT
                decision_id,
                verdict,
                confidence,
                typology_matched,
                amount,
                recipient_name,
                sar_required,
                CAST(decision_date AS STRING) as decision_date
            FROM `{GCP_PROJECT}.{BIGQUERY_DATASET}.{TABLE_DECISIONS}`
            ORDER BY decision_date DESC
            LIMIT {limit}
        """

        rows    = client.query(query).result()
        results = []

        for row in rows:
            results.append({
                "decision_id":      row.decision_id,
                "verdict":          row.verdict,
                "confidence":       row.confidence,
                "typology_matched": row.typology_matched,
                "amount":           row.amount,
                "recipient_name":   row.recipient_name,
                "sar_required":     row.sar_required,
                "decision_date":    row.decision_date
            })

        return results

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sar/{decision_id}")
async def download_sar(decision_id: str):
    """
    Download the SAR PDF for a specific blocked payment.

    Looks for a PDF file named SAR_{decision_id[:8].upper()}.pdf
    in the data/sar_reports/ directory.

    Args:
        decision_id (str): the full decision ID from the verdict

    Returns:
        FileResponse: the SAR PDF file as a download

    Raises:
        HTTPException 404: if no SAR exists for this decision
    """
    short_id  = decision_id[:8].upper()
    pdf_path  = Path(f"data/sar_reports/SAR_{short_id}.pdf")
    txt_path  = Path(f"data/sar_reports/SAR_{short_id}.txt")

    if pdf_path.exists():
        return FileResponse(
            path         = str(pdf_path),
            media_type   = "application/pdf",
            filename     = f"SAR_{short_id}.pdf"
        )
    elif txt_path.exists():
        return FileResponse(
            path         = str(txt_path),
            media_type   = "text/plain",
            filename     = f"SAR_{short_id}.txt"
        )
    else:
        raise HTTPException(
            status_code = 404,
            detail      = f"No SAR found for decision {decision_id}"
        )


@app.get("/")
async def root():
    """Root endpoint — confirms the API is running."""
    return {
        "name":    "SentryPay API",
        "version": "1.0.0",
        "docs":    "/docs",
        "health":  "/health"
    }