"""
SentryPay — BigQuery Schema Update
=====================================
Adds observability fields to the existing decisions table.
Run this once to add the new columns for token tracking and
per-tool latency measurements.

New fields added:
    prompt_tokens        — Gemini input token count per request
    completion_tokens    — Gemini output token count per request
    total_tokens         — total tokens consumed per request
    tool_latencies_json  — JSON string: {tool_name: milliseconds}

Usage:
    python setup/update_bigquery_schema.py
"""

import os
import sys
from dotenv import load_dotenv
from colorama import Fore, init
from google.cloud import bigquery

load_dotenv()
init(autoreset=True)

GCP_PROJECT      = os.getenv("GCP_PROJECT_ID")
BIGQUERY_DATASET = os.getenv("BIGQUERY_DATASET", "sentry_pay")
TABLE_DECISIONS  = os.getenv("BIGQUERY_TABLE_DECISIONS", "decisions")

NEW_FIELDS = [
    bigquery.SchemaField("prompt_tokens",       "INTEGER", mode="NULLABLE"),
    bigquery.SchemaField("completion_tokens",    "INTEGER", mode="NULLABLE"),
    bigquery.SchemaField("total_tokens",         "INTEGER", mode="NULLABLE"),
    bigquery.SchemaField("tool_latencies_json",  "STRING",  mode="NULLABLE"),
]


def update_schema():
    print(Fore.CYAN + "\n SentryPay: BigQuery Schema Update \n")

    client   = bigquery.Client(project=GCP_PROJECT)
    table_id = f"{GCP_PROJECT}.{BIGQUERY_DATASET}.{TABLE_DECISIONS}"

    try:
        table = client.get_table(table_id)
        existing_names = {f.name for f in table.schema}
        new_schema = list(table.schema)
        added = []

        for field in NEW_FIELDS:
            if field.name not in existing_names:
                new_schema.append(field)
                added.append(field.name)
            else:
                print(Fore.YELLOW + f"  ↻ Already exists: {field.name}")

        if added:
            table.schema = new_schema
            client.update_table(table, ["schema"])
            for name in added:
                print(Fore.GREEN + f"Added field: {name}")
        else:
            print(Fore.GREEN + "Schema already up to date")

        print(Fore.CYAN + "\n Schema update complete.\n")

    except Exception as e:
        print(Fore.RED + f"Schema update failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    update_schema()
