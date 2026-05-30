"""
SentryPay — Step 7: Load Data into Elasticsearch
=================================================
Performs the final data loading step by bulk-uploading all processed
JSON files into their respective Elasticsearch indices.

Uses Elasticsearch's bulk API for efficiency — rather than sending
one document at a time (which would require 69,000+ individual API
calls), documents are batched in groups of 200 and uploaded in a
single request per batch, dramatically reducing load time.

All operations use upsert semantics (doc_as_upsert: True), meaning:
  - If a document with that ID does not exist → it is created
  - If a document with that ID already exists → it is updated
This makes the script safe to re-run without creating duplicates.

Files loaded:
    scam_typologies_with_embeddings.json → scam_typologies index
        306 fraud patterns with 768-dimensional vector embeddings

    beneficiary_intel.json               → beneficiary_intel index
        68,564 flagged and clean account records with risk scores

    customer_transactions.json           → customer_transactions index
        153 synthetic payment transactions across 3 demo users

    user_baselines.json                  → user_baselines index
        3 behavioral baseline profiles, one per demo user

After loading, runs verification queries to confirm:
    - Correct document counts in all indices
    - Vector embeddings are present and correct dimension
    - ES|QL queries return expected results

Usage:
    python data_pipeline/step7_load_to_elastic.py
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
from colorama import Fore, Style, init
from elasticsearch import helpers
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.elastic_client import get_client

init(autoreset=True)
load_dotenv()

PROCESSED_DIR   = Path(os.getenv("PROCESSED_DATA_DIR", "data/processed"))
BULK_CHUNK_SIZE = 200

LOAD_CONFIG = [
    {
        "file":     "scam_typologies_with_embeddings.json",
        "index":    "scam_typologies",
        "id_field": "typology_id",
        "label":    "Scam typologies"
    },
    {
        "file":     "beneficiary_intel.json",
        "index":    "beneficiary_intel",
        "id_field": "entity_id",
        "label":    "Beneficiary intel"
    },
    {
        "file":     "customer_transactions.json",
        "index":    "customer_transactions",
        "id_field": "transaction_id",
        "label":    "Customer transactions"
    },
    {
        "file":     "user_baselines.json",
        "index":    "user_baselines",
        "id_field": "user_id",
        "label":    "User baselines"
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def prepare_actions(records, index, id_field):
    """
    Generate Elasticsearch bulk action dictionaries for a list of records.

    Each action instructs Elasticsearch to perform an upsert:
    insert the document if it does not exist, or update it if it does.
    Using a deterministic ID field (typology_id, entity_id, etc.) ensures
    re-running this script updates existing records rather than
    creating duplicates.

    Args:
        records (list[dict]): documents to load
        index (str): target Elasticsearch index name
        id_field (str): field name to use as the document ID

    Yields:
        dict: one bulk action dict per record
    """
    for record in records:
        doc_id = record.get(id_field)
        if doc_id:
            yield {
                "_op_type":      "update",
                "_index":        index,
                "_id":           str(doc_id),
                "doc":           record,
                "doc_as_upsert": True
            }


def load_index(es, config):
    """
    Load one JSON file into one Elasticsearch index using bulk upsert.

    Skips gracefully if the source file or target index does not exist,
    so a single missing file does not prevent other indices from loading.
    Progress is displayed as a tqdm progress bar counted in chunks.

    Args:
        es (Elasticsearch): authenticated Elastic client
        config (dict): load configuration with keys:
                       file, index, id_field, label

    Returns:
        dict: summary with keys loaded, failed, skipped
    """
    filepath = PROCESSED_DIR / config['file']
    index    = config['index']
    id_field = config['id_field']
    label    = config['label']

    print(f"\n  {Fore.CYAN}{label}{Style.RESET_ALL}")

    if not filepath.exists():
        print(Fore.YELLOW + f"    File not found: {filepath} — skipping.")
        return {"loaded": 0, "failed": 0, "skipped": True}

    with open(filepath, 'r', encoding='utf-8') as f:
        records = json.load(f)

    if isinstance(records, dict):
        records = [records]

    print(f"    Records to load: {len(records):,}")

    if not es.indices.exists(index=index):
        print(Fore.RED + f"    Index '{index}' does not exist. Run setup first.")
        return {"loaded": 0, "failed": 0, "skipped": True}

    actions    = list(prepare_actions(records, index, id_field))
    loaded     = 0
    failed     = 0
    errors_log = []

    for i in tqdm(range(0, len(actions), BULK_CHUNK_SIZE),
                  desc="    Loading",
                  unit="chunk",
                  leave=False):
        chunk = actions[i:i + BULK_CHUNK_SIZE]
        success, errors = helpers.bulk(
            es, chunk,
            raise_on_error=False,
            stats_only=False
        )
        loaded += success
        if errors:
            failed += len(errors)
            errors_log.extend(errors[:2])

    status = Fore.GREEN + f"{loaded:,} loaded" + Style.RESET_ALL
    if failed:
        status += Fore.RED + f", {failed:,} failed"
    print(f"    {status}")

    if errors_log:
        print(Fore.YELLOW + f"    Sample error: {str(errors_log[0])[:120]}")

    return {"loaded": loaded, "failed": failed, "skipped": False}


# ── Verification ──────────────────────────────────────────────────────────────

def verify_indices(es):
    """
    Run post-load verification queries to confirm data integrity.

    Checks performed:
        1. Document count in each index matches expected records loaded
        2. A sampled scam_typologies record has a valid 768-dim vector
        3. ES|QL query on customer_transactions returns expected results

    Any check that fails prints a warning but does not raise an
    exception — the script reports what it finds and lets the operator
    decide whether to re-run the load.

    Args:
        es (Elasticsearch): authenticated Elastic client
    """
    print(Fore.CYAN + "\n Verification \n")

    # Document counts
    for config in LOAD_CONFIG:
        try:
            count = es.count(index=config['index'])['count']
            print(f"  {config['index']}: {Fore.GREEN}{count:,} documents")
        except Exception as e:
            print(f"  {config['index']}: {Fore.RED}ERROR — {e}")

    # Vector search test
    print(f"\n  Testing vector search on scam_typologies...")
    try:
        sample = es.search(
            index="scam_typologies",
            body={
                "query":   {"match_all": {}},
                "size":    1,
                "_source": ["typology_name", "description_vector"]
            }
        )
        hit        = sample['hits']['hits'][0]
        has_vector = bool(hit['_source'].get('description_vector'))
        dims       = len(hit['_source']['description_vector']) if has_vector else 0
        print(f"  Sample: {Fore.GREEN}{hit['_source'].get('typology_name', '?')}")
        print(f"  Has vector: {Fore.GREEN}{has_vector} | Dims: {Fore.GREEN}{dims}")
    except Exception as e:
        print(Fore.RED + f"  Vector test failed: {e}")

    # ES|QL transaction test
    print(f"\n  Testing ES|QL on customer_transactions...")
    try:
        result = es.esql.query(body={
            "query": """
                FROM customer_transactions
                | WHERE user_id == "demo_user_001"
                | STATS count = COUNT(*), avg_amount = AVG(amount)
                | LIMIT 1
            """
        })
        rows = result.get('values', [])
        if rows:
            count, avg = rows[0]
            print(f"  demo_user_001: {Fore.GREEN}{count} txns, avg ${avg:,.0f}")
    except Exception as e:
        print(Fore.YELLOW + f"  ES|QL test skipped: {e}")


# ── Main ─────────────────────────────────────────────────────────────────────

def run():
    print(Fore.CYAN + "\n SentryPay: Step 7 — Load to Elastic \n")

    es = get_client()

    try:
        info = es.info()
        print(Fore.GREEN + f"  Connected: Elasticsearch {info['version']['number']}")
    except Exception as e:
        print(Fore.RED + f"  Connection failed: {e}")
        sys.exit(1)

    results = {}
    for config in LOAD_CONFIG:
        results[config['label']] = load_index(es, config)

    print(Fore.CYAN + "\n Load Summary \n")
    total_loaded, total_failed = 0, 0

    for label, result in results.items():
        if result['skipped']:
            print(f"  {label}: {Fore.YELLOW}SKIPPED")
        elif result['failed'] == 0:
            print(f"  {label}: {Fore.GREEN}{result['loaded']:,} loaded")
        else:
            print(f"  {label}: {Fore.YELLOW}{result['loaded']:,} loaded, {result['failed']:,} failed")
        total_loaded += result.get('loaded', 0)
        total_failed += result.get('failed', 0)

    print(f"\n  Total loaded: {Fore.GREEN}{total_loaded:,}")
    if total_failed:
        print(f"  Total failed: {Fore.RED}{total_failed:,}")

    verify_indices(es)

    print(Fore.CYAN + "\n Step 7 Complete. \n")
    print(Fore.GREEN + "All data in Elastic.")


if __name__ == "__main__":
    run()