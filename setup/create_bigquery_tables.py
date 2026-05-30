"""
SentryPay — BigQuery Audit Table Setup
========================================
Creates the BigQuery dataset and decisions table used to log every
verdict the SentryPay agent produces.

Why BigQuery:
    Every decision the agent makes — Allow, Friction, or Block —
    is written to this immutable audit log. This serves three purposes:
      1. Compliance — provides a tamper-proof record of all fraud
         decisions, consistent with SR 11-7 model risk guidelines
      2. Drift detection — the weekly drift analysis job reads this
         table to detect when agent confidence is dropping over time
      3. Feedback loop — user confirmations ("this was a scam" /
         "this was legitimate") are stored here and used to improve
         the scam typology index

Table schema:
    decision_id       — unique identifier for each decision
    user_id           — which demo user made the payment request
    verdict           — ALLOW / FRICTION / BLOCK
    confidence        — agent confidence score (0.0 to 1.0)
    typology_matched  — which scam pattern was matched (if any)
    reasoning         — plain English explanation from the agent
    red_flags         — specific concerns the agent identified
    amount            — payment amount submitted for analysis
    recipient_name    — intended payment recipient
    account_number    — destination account number
    email_snippet     — first 500 characters of the submitted email
    sar_required      — whether a SAR report was generated
    user_feedback     — TRUE_POSITIVE / FALSE_POSITIVE / UNKNOWN
    decision_date     — timestamp of the decision
    processing_ms     — time taken to produce the verdict

Usage:
    python setup/create_bigquery_tables.py
"""

import os
import sys
from dotenv import load_dotenv
from colorama import Fore, Style, init
from google.cloud import bigquery

load_dotenv()
init(autoreset=True)

GCP_PROJECT      = os.getenv("GCP_PROJECT_ID")
BIGQUERY_DATASET = os.getenv("BIGQUERY_DATASET", "sentry_pay")
TABLE_DECISIONS  = os.getenv("BIGQUERY_TABLE_DECISIONS", "decisions")


# ── Table schema ──────────────────────────────────────────────────────────────

DECISIONS_SCHEMA = [
    bigquery.SchemaField("decision_id",      "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("user_id",          "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("verdict",          "STRING",    mode="REQUIRED"),   # ALLOW / FRICTION / BLOCK
    bigquery.SchemaField("confidence",       "FLOAT64",   mode="NULLABLE"),
    bigquery.SchemaField("typology_matched", "STRING",    mode="NULLABLE"),
    bigquery.SchemaField("reasoning",        "STRING",    mode="NULLABLE"),
    bigquery.SchemaField("red_flags",        "STRING",    mode="REPEATED"),   # list of strings
    bigquery.SchemaField("amount",           "FLOAT64",   mode="NULLABLE"),
    bigquery.SchemaField("recipient_name",   "STRING",    mode="NULLABLE"),
    bigquery.SchemaField("account_number",   "STRING",    mode="NULLABLE"),
    bigquery.SchemaField("email_snippet",    "STRING",    mode="NULLABLE"),
    bigquery.SchemaField("sar_required",     "BOOL",      mode="NULLABLE"),
    bigquery.SchemaField("user_feedback",    "STRING",    mode="NULLABLE"),   # TRUE_POSITIVE / FALSE_POSITIVE / UNKNOWN
    bigquery.SchemaField("decision_date",    "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("processing_ms",    "INTEGER",   mode="NULLABLE"),
]


# ── Setup ─────────────────────────────────────────────────────────────────────

def create_dataset(client: bigquery.Client) -> bigquery.Dataset:
    """
    Create the BigQuery dataset if it does not already exist.

    The dataset acts as a container (like a database schema) for all
    SentryPay tables. Uses US multi-region for broad availability.

    Args:
        client (bigquery.Client): authenticated BigQuery client

    Returns:
        bigquery.Dataset: the created or existing dataset
    """
    dataset_id = f"{GCP_PROJECT}.{BIGQUERY_DATASET}"
    dataset    = bigquery.Dataset(dataset_id)
    dataset.location = "US"

    try:
        dataset = client.create_dataset(dataset, exists_ok=True)
        print(Fore.GREEN + f"Dataset ready: {BIGQUERY_DATASET}")
        return dataset
    except Exception as e:
        print(Fore.RED + f"Dataset creation failed: {e}")
        sys.exit(1)


def create_decisions_table(client: bigquery.Client):
    """
    Create the decisions audit table if it does not already exist.

    Uses exists_ok=True so re-running this script is always safe —
    it will not overwrite or truncate an existing table with data.

    Args:
        client (bigquery.Client): authenticated BigQuery client
    """
    table_id = f"{GCP_PROJECT}.{BIGQUERY_DATASET}.{TABLE_DECISIONS}"
    table    = bigquery.Table(table_id, schema=DECISIONS_SCHEMA)

    try:
        table = client.create_table(table, exists_ok=True)
        print(Fore.GREEN + f"Table ready: {BIGQUERY_DATASET}.{TABLE_DECISIONS}")

        # Verify it's accessible
        count_query = f"SELECT COUNT(*) as cnt FROM `{table_id}`"
        result      = client.query(count_query).result()
        count       = list(result)[0].cnt
        print(Fore.GREEN + f"Current decisions in table: {count:,}")

    except Exception as e:
        print(Fore.RED + f"Table creation failed: {e}")
        sys.exit(1)


def run():
    print(Fore.CYAN + "\n SentryPay: BigQuery Setup \n")

    if not GCP_PROJECT:
        print(Fore.RED + "ERROR: GCP_PROJECT_ID not set in .env")
        sys.exit(1)

    print(f"  Project: {GCP_PROJECT}")
    print(f"  Dataset: {BIGQUERY_DATASET}")
    print(f"  Table:   {TABLE_DECISIONS}\n")

    client = bigquery.Client(project=GCP_PROJECT)

    create_dataset(client)
    create_decisions_table(client)

    print(Fore.CYAN + "\n BigQuery setup complete.\n")


if __name__ == "__main__":
    run()