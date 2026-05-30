"""
SentryPay — Elastic Index Setup
=================================
Creates the four Elasticsearch indices that form SentryPay's
knowledge base. Think of each index as a database table —
this script defines their schema (field names and data types)
and creates them as empty containers before data is loaded.

The four indices created:

  scam_typologies       — Fraud pattern library with vector embeddings.
                          Each record describes how a specific scam works,
                          its red flags, and who it targets. Used for
                          semantic search during payment analysis.

  beneficiary_intel     — Flagged and clean account database sourced from
                          OpenSanctions, OFAC, and synthetic mule accounts.
                          Used to score the risk of a destination account.

  customer_transactions — 90-day synthetic payment history per demo user.
                          Used to establish what "normal" looks like for
                          each user and detect anomalous payments.

  user_baselines        — Pre-computed behavioral profile per user including
                          average payment amount, known vendors, and the
                          statistical threshold above which a payment is
                          considered anomalous.

Run this ONCE before loading any data. Use --force to recreate
indices if they already exist (WARNING: deletes all existing data).

Usage:
    python setup/create_elastic_indices.py
    python setup/create_elastic_indices.py --force
"""

import sys
from pathlib import Path
from colorama import Fore, Style, init

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.elastic_client import get_client

init(autoreset=True)


# ── Index 1: Scam Typologies ─────────────────────────────────────────────────
SCAM_TYPOLOGIES_MAPPING = {
    "mappings": {
        "properties": {
            "typology_id":          {"type": "keyword"},
            "typology_name":        {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "description":          {"type": "text"},
            "description_vector":   {"type": "dense_vector", "dims": 768, "index": True, "similarity": "cosine"},
            "red_flags":            {"type": "keyword"},
            "target_victim":        {"type": "keyword"},
            "typical_payment_type": {"type": "keyword"},
            "avg_loss_usd":         {"type": "float"},
            "source":               {"type": "keyword"},
            "year":                 {"type": "integer"},
            "last_updated":         {"type": "date"},
            "is_augmented":         {"type": "boolean"},
            "source_original":      {"type": "keyword"}
        }
    }
}

# ── Index 2: Beneficiary Intel ───────────────────────────────────────────────
BENEFICIARY_INTEL_MAPPING = {
    "mappings": {
        "properties": {
            "entity_id":      {"type": "keyword"},
            "account_number": {"type": "keyword"},
            "routing_number": {"type": "keyword"},
            "entity_name":    {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "name_aliases":   {"type": "text"},
            "risk_score":     {"type": "float"},
            "risk_category":  {"type": "keyword"},
            "flag_reason":    {"type": "text"},
            "is_flagged":     {"type": "boolean"},
            "datasets":       {"type": "keyword"},
            "country_code":   {"type": "keyword"},
            "topics":         {"type": "keyword"},
            "first_seen":     {"type": "date"},
            "last_seen":      {"type": "date"},
            "last_updated":   {"type": "date"}
        }
    }
}

# ── Index 3: Customer Transactions ───────────────────────────────────────────
CUSTOMER_TRANSACTIONS_MAPPING = {
    "mappings": {
        "properties": {
            "transaction_id": {"type": "keyword"},
            "user_id":        {"type": "keyword"},
            "date":           {"type": "date", "format": "yyyy-MM-dd"},
            "amount":         {"type": "float"},
            "recipient_name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "account_number": {"type": "keyword"},
            "routing_number": {"type": "keyword"},
            "payment_type":   {"type": "keyword"},
            "memo":           {"type": "text"},
            "is_anomalous":   {"type": "boolean"}
        }
    }
}

# ── Index 4: User Baselines ───────────────────────────────────────────────────
USER_BASELINES_MAPPING = {
    "mappings": {
        "properties": {
            "user_id":        {"type": "keyword"},
            "mean_payment":   {"type": "float"},
            "std_payment":    {"type": "float"},
            "p95_payment":    {"type": "float"},
            "max_normal":     {"type": "float"},
            "known_accounts": {"type": "keyword"},
            "known_vendors":  {"type": "keyword"},
            "preferred_rail": {"type": "keyword"},
            "computed_at":    {"type": "date"}
        }
    }
}

# ── All indices ───────────────────────────────────────────────────────────────
INDICES = {
    "scam_typologies":       SCAM_TYPOLOGIES_MAPPING,
    "beneficiary_intel":     BENEFICIARY_INTEL_MAPPING,
    "customer_transactions": CUSTOMER_TRANSACTIONS_MAPPING,
    "user_baselines":        USER_BASELINES_MAPPING
}

# ── Create ────────────────────────────────────────────────────────────────────
def create_indices(es, force_recreate=False):
    """
    Iterate over all index definitions and create them in Elasticsearch.

    For each index:
      - Skips creation if the index already exists (unless force_recreate=True)
      - Passes only the mappings (field schema) — settings are managed
        automatically by Elastic Serverless

    Args:
        es (Elasticsearch): authenticated Elastic client
        force_recreate (bool): if True, deletes existing indices before
                               recreating them. Use with caution in production.
    """
    print(Fore.CYAN + "\n SentryPay: Elastic Index Setup \n")

    for index_name, mapping in INDICES.items():
        exists = es.indices.exists(index=index_name)

        if exists:
            if force_recreate:
                print(Fore.YELLOW + f"Deleting existing index: {index_name}")
                es.indices.delete(index=index_name)
            else:
                print(Fore.GREEN + f"Already exists (skipping): {index_name}")
                continue

        es.indices.create(index=index_name, mappings=mapping["mappings"])
        print(Fore.GREEN + f" Created: {index_name}")

    print(Fore.CYAN + "\n Verifying \n")
    for index_name in INDICES:
        count = es.count(index=index_name)['count']
        print(f"  {index_name}: {Fore.GREEN}EXISTS{Style.RESET_ALL} | {count} documents")

    print(Fore.CYAN + "\n Done. All indices ready. \n")

# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Recreate indices if they exist")
    args = parser.parse_args()

    es = get_client()
    try:
        info = es.info()
        print(Fore.GREEN + f"Connected: Elasticsearch {info['version']['number']}")
    except Exception as e:
        print(Fore.RED + f"Could not connect: {e}")
        sys.exit(1)

    create_indices(es, force_recreate=args.force)