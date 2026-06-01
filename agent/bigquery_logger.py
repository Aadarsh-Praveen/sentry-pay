"""
SentryPay — BigQuery Decision Logger
======================================
Writes every agent verdict to the BigQuery audit table including
extended observability fields: token usage and per-tool latencies.

Extended schema (added for observability):
    prompt_tokens     — Gemini input token count
    completion_tokens — Gemini output token count
    total_tokens      — total tokens consumed
    tool_latencies    — JSON string of per-tool milliseconds
    trace_id          — OpenTelemetry trace ID for correlation
"""

import os
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
    token_count:      dict  = None,
    tool_latencies:   dict  = None
) -> str:
    """
    Write one agent decision to the BigQuery audit table.

    Extended from the base version to include observability fields:
    token usage breakdown and per-tool latency measurements.

    Args:
        user_id (str): user who submitted the request
        verdict (str): ALLOW, FRICTION, or BLOCK
        confidence (float): agent confidence score (0.0-1.0)
        typology_matched (str | None): matched scam pattern name
        reasoning (str): plain English explanation
        red_flags (list[str]): specific concerns identified
        amount (float): payment amount
        recipient_name (str): intended recipient
        account_number (str): destination account
        email_text (str): submitted email text
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

    import json
    row = {
        "decision_id":        decision_id,
        "user_id":            user_id,
        "verdict":            verdict,
        "confidence":         round(confidence, 4),
        "typology_matched":   typology_matched,
        "reasoning":          reasoning,
        "red_flags":          red_flags,
        "amount":             amount,
        "recipient_name":     recipient_name,
        "account_number":     account_number,
        "email_snippet":      email_text[:500],
        "sar_required":       sar_required,
        "user_feedback":      "UNKNOWN",
        "decision_date":      datetime.now(timezone.utc).isoformat(),
        "processing_ms":      processing_ms,
        "prompt_tokens":      token_count.get("prompt_tokens", 0),
        "completion_tokens":  token_count.get("completion_tokens", 0),
        "total_tokens":       token_count.get("total_tokens", 0),
        "tool_latencies_json": json.dumps(tool_lats)
    }

    try:
        client   = get_bigquery_client()
        table_id = f"{GCP_PROJECT}.{BIGQUERY_DATASET}.{TABLE_DECISIONS}"
        errors   = client.insert_rows_json(table_id, [row])

        if errors:
            print(Fore.YELLOW + f"  ⚠ BigQuery warning: {errors}")
        else:
            print(Fore.GREEN + f"  ✓ Logged to BigQuery: {decision_id[:8]}...")

    except Exception as e:
        print(Fore.YELLOW + f"  ⚠ BigQuery logging failed (non-fatal): {e}")

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
        print(Fore.GREEN + f"  ✓ Feedback: {decision_id[:8]} → {feedback}")
    except Exception as e:
        print(Fore.YELLOW + f"  ⚠ Feedback update failed: {e}")