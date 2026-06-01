"""
SentryPay — BigQuery Decision Logger
======================================
Writes every agent verdict to the BigQuery audit table.

Privacy protection:
    Account numbers are masked before storage — only the last
    4 digits are stored (e.g. "****4321"). This protects
    sensitive financial data while preserving enough information
    for fraud investigation and drift analysis.

Extended observability fields:
    prompt_tokens, completion_tokens, total_tokens — Gemini usage
    tool_latencies_json — per-tool millisecond breakdown
"""

import os
import json
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv
from colorama import Fore, init
from google.cloud import bigquery

load_dotenv()
init(autoreset=True)

GCP_PROJECT      = os.getenv("GCP_PROJECT_ID")
BIGQUERY_DATASET = os.getenv("BIGQUERY_DATASET", "sentry_pay")
TABLE_DECISIONS  = os.getenv("BIGQUERY_TABLE_DECISIONS", "decisions")


def get_bigquery_client() -> bigquery.Client:
    """Return an authenticated BigQuery client."""
    return bigquery.Client(project=GCP_PROJECT)


def mask_account(account: str) -> str:
    """
    Mask an account number to last 4 digits only.

    Protects sensitive financial data in BigQuery while preserving
    enough information for investigation. Follows PCI DSS guidance
    on primary account number truncation.

    Args:
        account (str): full account number

    Returns:
        str: masked number e.g. "****4321"
    """
    if not account or len(account) < 4:
        return "****"
    return f"****{account[-4:]}"


def log_decision(
    user_id:          str,
    verdict:          str,
    confidence:       float,
    typology_matched: str | None,
    reasoning:        str,
    red_flags:        list[str],
    amount:           float,
    recipient_name:   str,
    account_number:   str,
    email_text:       str,
    sar_required:     bool,
    processing_ms:    int,
    token_count:      dict = None,
    tool_latencies:   dict = None
) -> str:
    """
    Write one agent decision to the BigQuery audit table.

    Account numbers are masked before storage. Email text is
    truncated to 500 characters to limit PII exposure.

    Args:
        user_id (str): user who submitted the request
        verdict (str): ALLOW, FRICTION, or BLOCK
        confidence (float): agent confidence score (0.0-1.0)
        typology_matched (str | None): matched scam pattern
        reasoning (str): plain English explanation
        red_flags (list[str]): specific concerns identified
        amount (float): payment amount
        recipient_name (str): intended recipient
        account_number (str): destination account (will be masked)
        email_text (str): submitted email (truncated to 500 chars)
        sar_required (bool): whether SAR was generated
        processing_ms (int): total processing time
        token_count (dict): Gemini token usage breakdown
        tool_latencies (dict): milliseconds per tool call

    Returns:
        str: the decision_id of the logged record
    """
    decision_id  = str(uuid.uuid4())
    token_count  = token_count  or {}
    tool_lats    = tool_latencies or {}

    row = {
        "decision_id":         decision_id,
        "user_id":             user_id,
        "verdict":             verdict,
        "confidence":          round(confidence, 4),
        "typology_matched":    typology_matched,
        "reasoning":           reasoning,
        "red_flags":           red_flags,
        "amount":              amount,
        "recipient_name":      recipient_name,
        "account_number":      mask_account(account_number),  # MASKED
        "email_snippet":       email_text[:500],
        "sar_required":        sar_required,
        "user_feedback":       "UNKNOWN",
        "decision_date":       datetime.now(timezone.utc).isoformat(),
        "processing_ms":       processing_ms,
        "prompt_tokens":       token_count.get("prompt_tokens", 0),
        "completion_tokens":   token_count.get("completion_tokens", 0),
        "total_tokens":        token_count.get("total_tokens", 0),
        "tool_latencies_json": json.dumps(tool_lats)
    }

    try:
        client   = get_bigquery_client()
        table_id = f"{GCP_PROJECT}.{BIGQUERY_DATASET}.{TABLE_DECISIONS}"
        errors   = client.insert_rows_json(table_id, [row])

        if errors:
            print(Fore.YELLOW + f"BigQuery warning: {errors}")
        else:
            print(Fore.GREEN + f"Logged to BigQuery: {decision_id[:8]}...")

    except Exception as e:
        print(Fore.YELLOW + f"BigQuery logging failed (non-fatal): {e}")

    return decision_id


def update_feedback(decision_id: str, feedback: str):
    """
    Update user feedback for an existing decision.

    Args:
        decision_id (str): the decision to update
        feedback (str): TRUE_POSITIVE or FALSE_POSITIVE
    """
    try:
        client = get_bigquery_client()
        query  = f"""
            UPDATE `{GCP_PROJECT}.{BIGQUERY_DATASET}.{TABLE_DECISIONS}`
            SET user_feedback = '{feedback}'
            WHERE decision_id = '{decision_id}'
        """
        client.query(query).result()
        print(Fore.GREEN + f"Feedback: {decision_id[:8]} → {feedback}")
    except Exception as e:
        print(Fore.YELLOW + f"Feedback update failed: {e}")