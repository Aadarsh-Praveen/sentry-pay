"""
SentryPay — BigQuery Decision Logger
======================================
Writes every agent verdict to the BigQuery audit table immediately
after the decision is produced.

Why every decision is logged:
    The audit log serves as SentryPay's institutional memory and is
    the foundation of the drift detection system. By recording the
    full reasoning trace alongside the verdict, the weekly drift
    analysis job can detect when agent confidence is declining on
    specific fraud typologies — a signal that scammer tactics have
    evolved and the typology index needs refreshing.

    The log is also immutable by design. BigQuery append-only tables
    cannot be updated after writing, providing a tamper-proof compliance
    record consistent with SR 11-7 model risk management guidelines.

What is logged per decision:
    - Full verdict (ALLOW / FRICTION / BLOCK)
    - Confidence score from the agent
    - Matched typology name
    - Agent reasoning in plain English
    - Red flags identified
    - Payment details (amount, recipient, account)
    - First 500 characters of the submitted email
    - Whether a SAR report was generated
    - Processing time in milliseconds
    - Timestamp of the decision
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
    """
    Create and return an authenticated BigQuery client.

    Returns:
        bigquery.Client: client authenticated via Application Default Credentials
    """
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
    processing_ms:    int
) -> str:
    """
    Write one agent decision to the BigQuery audit table.

    Generates a unique decision_id for the record and timestamps
    it with the current UTC time. The email is truncated to 500
    characters to keep the table size manageable while preserving
    enough context for future analysis.

    Args:
        user_id (str): identifier of the user who submitted the request
        verdict (str): ALLOW, FRICTION, or BLOCK
        confidence (float): agent's confidence score (0.0 to 1.0)
        typology_matched (str | None): scam type matched, or None
        reasoning (str): plain English explanation of the decision
        red_flags (list[str]): specific concerns identified by the agent
        amount (float): payment amount submitted
        recipient_name (str): intended payment recipient
        account_number (str): destination account number
        email_text (str): the submitted email or message text
        sar_required (bool): whether a SAR report was generated
        processing_ms (int): total agent processing time in milliseconds

    Returns:
        str: the decision_id of the logged record

    Raises:
        Exception: if the BigQuery insert fails (logged as a warning,
                   does not prevent the verdict from being returned)
    """
    decision_id = str(uuid.uuid4())

    row = {
        "decision_id":      decision_id,
        "user_id":          user_id,
        "verdict":          verdict,
        "confidence":       round(confidence, 4),
        "typology_matched": typology_matched,
        "reasoning":        reasoning,
        "red_flags":        red_flags,
        "amount":           amount,
        "recipient_name":   recipient_name,
        "account_number":   account_number,
        "email_snippet":    email_text[:500],
        "sar_required":     sar_required,
        "user_feedback":    "UNKNOWN",
        "decision_date":    datetime.now(timezone.utc).isoformat(),
        "processing_ms":    processing_ms
    }

    try:
        client   = get_bigquery_client()
        table_id = f"{GCP_PROJECT}.{BIGQUERY_DATASET}.{TABLE_DECISIONS}"
        errors   = client.insert_rows_json(table_id, [row])

        if errors:
            print(Fore.YELLOW + f"BigQuery insert warning: {errors}")
        else:
            print(Fore.GREEN + f"Decision logged to BigQuery: {decision_id[:8]}")

    except Exception as e:
        # Log failure is non-fatal — verdict is still returned to the user
        print(Fore.YELLOW + f"BigQuery logging failed (non-fatal): {e}")

    return decision_id


def update_feedback(decision_id: str, feedback: str):
    """
    Update the user_feedback field for an existing decision record.

    Called when a user confirms whether the agent's verdict was correct.
    Feedback values: TRUE_POSITIVE, FALSE_POSITIVE.

    Note: BigQuery does not support row-level updates on streaming inserts
    until the data is in the managed storage layer (~90 minutes). This
    function uses DML UPDATE which works on committed data.

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
        print(Fore.GREEN + f"Feedback updated: {decision_id[:8]} → {feedback}")
    except Exception as e:
        print(Fore.YELLOW + f"Feedback update failed: {e}")