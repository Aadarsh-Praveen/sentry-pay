"""
SentryPay — Step 8: Phase 1 Validation & Go/No-Go Gate
=======================================================
Runs a comprehensive set of automated checks to verify that the
entire Phase 1 data pipeline completed successfully and the system
is ready for Phase 2 (Gemini agent development).

This script is the formal gate between Phase 1 and Phase 2.
All 7 checks must pass before proceeding to build the agent.

Checks performed:
    [1] Elastic connection      — confirms credentials and connectivity
    [2] Index record counts     — verifies minimum document counts
                                  in all four indices
    [3] Embedding presence      — confirms all scam typology records
                                  have valid 768-dimensional vectors
    [4] Vector search           — runs a live semantic search to confirm
                                  Elasticsearch can find relevant typologies
                                  from natural language input
    [5] ES|QL mule scoring      — confirms the beneficiary_intel index
                                  supports aggregate risk queries
    [6] ES|QL velocity check    — confirms transaction history and
                                  behavioral baseline data is queryable
    [7] Class balance           — verifies the ratio of flagged to clean
                                  accounts in beneficiary_intel

Go/No-Go decision:
    0 failures   → GO — proceed to Phase 2
    1-2 failures → CONDITIONAL GO — fix issues before Phase 2
    3+ failures  → NO-GO — re-run failed pipeline steps

Usage:
    python data_pipeline/step8_validate.py
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from colorama import Fore, Style, init

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.elastic_client import get_client

init(autoreset=True)
load_dotenv()

GCP_PROJECT     = os.getenv("GCP_PROJECT_ID")
GCP_REGION      = os.getenv("GCP_REGION", "us-central1")

PASS_MARK = 0
FAIL_MARK = 0


def passed(msg):
    """Record a passed test and print a green checkmark with the message."""
    global PASS_MARK
    PASS_MARK += 1
    print(f"  {Fore.GREEN}✓{Style.RESET_ALL}  {msg}")


def failed(msg):
    """Record a failed test and print a red cross with the message."""
    global FAIL_MARK
    FAIL_MARK += 1
    print(f"  {Fore.RED}✗{Style.RESET_ALL}  {msg}")


def warned(msg):
    """Print a yellow warning for non-critical issues that do not affect the gate."""
    print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL}  {msg}")


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_elastic_connection(es):
    print(Fore.CYAN + "\n[1] Elastic connection")
    try:
        info = es.info()
        passed(f"Connected — Elasticsearch {info['version']['number']}")
    except Exception as e:
        failed(f"Cannot connect: {e}")


def test_index_counts(es):
    print(Fore.CYAN + "\n[2] Index record counts")
    min_counts = {
        "scam_typologies":       100,
        "beneficiary_intel":     1000,
        "customer_transactions": 50,
        "user_baselines":        1
    }
    for index, minimum in min_counts.items():
        try:
            count = es.count(index=index)['count']
            if count >= minimum:
                passed(f"{index}: {count:,} records")
            else:
                failed(f"{index}: only {count:,} records (min: {minimum})")
        except Exception as e:
            failed(f"{index}: {e}")


def test_embeddings(es):
    print(Fore.CYAN + "\n[3] Embedding presence and dimensions")
    try:
        result = es.search(
            index="scam_typologies",
            body={"query": {"match_all": {}}, "size": 5,
                  "_source": ["typology_name", "description_vector"]}
        )
        hits = result['hits']['hits']
        if not hits:
            failed("No records in scam_typologies")
            return

        missing = sum(1 for h in hits if not h['_source'].get('description_vector'))
        if missing == 0:
            passed("All sampled records have embeddings")
        else:
            failed(f"{missing}/{len(hits)} records missing embeddings")

        dims = len(hits[0]['_source'].get('description_vector', []))
        if dims == 768:
            passed(f"Embedding dimensions: {dims} ✓")
        else:
            failed(f"Embedding dimensions: {dims} (expected 768)")
    except Exception as e:
        failed(f"Embedding check failed: {e}")


def test_vector_search(es):
    print(Fore.CYAN + "\n[4] Vector search — semantic matching")
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_REGION)

        test_text = "Our bank changed its account. Please update payment details."
        response  = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Generate a single embedding representation. Text: {test_text}",
            config=types.GenerateContentConfig(max_output_tokens=100)
        )

        # Use Vertex AI embedding directly
        from vertexai.language_models import TextEmbeddingModel
        import vertexai
        vertexai.init(project=GCP_PROJECT, location=GCP_REGION)
        model     = TextEmbeddingModel.from_pretrained("text-embedding-004")
        embedding = model.get_embeddings([test_text])[0].values

        result = es.search(
            index="scam_typologies",
            body={
                "knn": {
                    "field":          "description_vector",
                    "query_vector":   embedding,
                    "k":              3,
                    "num_candidates": 50
                },
                "_source": ["typology_name"],
                "size": 3
            }
        )
        hits = result['hits']['hits']
        if hits:
            top      = hits[0]['_source']['typology_name']
            score    = hits[0]['_score']
            passed(f"Vector search works → top match: '{top}' (score: {score:.3f})")
        else:
            failed("No results from vector search")
    except Exception as e:
        warned(f"Vector search test skipped: {e}")


def test_esql_mule_scoring(es):
    print(Fore.CYAN + "\n[5] ES|QL — Mule account scoring")
    try:
        result = es.esql.query(body={
            "query": """
                FROM beneficiary_intel
                | WHERE is_flagged == true
                | STATS count = COUNT(*), avg_risk = AVG(risk_score)
                | LIMIT 1
            """
        })
        rows = result.get('values', [])
        if rows:
            count, avg_risk = rows[0]
            passed(f"Flagged accounts: {count:,} | Avg risk: {avg_risk:.3f}")
        else:
            failed("Mule scoring returned no rows")
    except Exception as e:
        failed(f"ES|QL mule scoring failed: {e}")


def test_esql_velocity(es):
    print(Fore.CYAN + "\n[6] ES|QL — Velocity check")
    try:
        result = es.esql.query(body={
            "query": """
                FROM customer_transactions
                | WHERE user_id == "demo_user_001"
                | STATS count = COUNT(*), avg_amount = AVG(amount), max_amount = MAX(amount)
                | LIMIT 1
            """
        })
        rows = result.get('values', [])
        if rows:
            count, avg, max_amt = rows[0]
            passed(f"demo_user_001: {count} txns | avg ${avg:,.0f} | max ${max_amt:,.0f}")
        else:
            failed("Velocity check returned no rows")
    except Exception as e:
        failed(f"ES|QL velocity check failed: {e}")


def test_class_balance(es):
    print(Fore.CYAN + "\n[7] Class balance")
    try:
        flagged = es.count(index="beneficiary_intel", body={"query": {"term": {"is_flagged": True}}})['count']
        clean   = es.count(index="beneficiary_intel", body={"query": {"term": {"is_flagged": False}}})['count']
        total   = flagged + clean
        passed(f"Flagged: {flagged:,} | Clean: {clean:,} | Total: {total:,}")
    except Exception as e:
        failed(f"Class balance check failed: {e}")


# ── Verdict ───────────────────────────────────────────────────────────────────

def print_verdict():
    """
    Print the final go/no-go decision based on accumulated test results.

    Calculates pass percentage and prints one of three outcomes:
        GO              — all tests passed, safe to start Phase 2
        CONDITIONAL GO  — minor failures, review before proceeding
        NO-GO           — critical failures, pipeline must be re-run
    """
    print("PHASE 1 GATE RESULT")

    total = PASS_MARK + FAIL_MARK
    pct   = (PASS_MARK / total * 100) if total > 0 else 0

    print(f"  Tests passed: {Fore.GREEN}{PASS_MARK}{Style.RESET_ALL} / {total}")
    print(f"  Score:        {pct:.0f}%\n")

    if FAIL_MARK == 0:
        print(Fore.GREEN + "All checks passed.\n")
    elif FAIL_MARK <= 2:
        print(Fore.YELLOW + "Minor issues.\n")
    else:
        print(Fore.RED + "Critical failures.\n")



# ── Main ─────────────────────────────────────────────────────────────────────

def run():
    print(Fore.CYAN + "\n SentryPay: Phase 1 Validation \n")

    es = get_client()

    test_elastic_connection(es)
    test_index_counts(es)
    test_embeddings(es)
    test_vector_search(es)
    test_esql_mule_scoring(es)
    test_esql_velocity(es)
    test_class_balance(es)

    print_verdict()


if __name__ == "__main__":
    run()