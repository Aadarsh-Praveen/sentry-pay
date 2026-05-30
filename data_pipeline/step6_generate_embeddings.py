"""
SentryPay — Step 6: Vector Embedding Generation
================================================
Converts each scam typology description into a 768-dimensional
vector embedding using Google's text-embedding-004 model on Vertex AI.

What embeddings are and why they matter:
    A vector embedding is a list of 768 numbers that represent the
    semantic meaning of a piece of text. Texts with similar meanings
    have vectors that are close together in 768-dimensional space,
    regardless of whether they share the same words.

    This is what enables SentryPay's core capability: when a user
    pastes a suspicious email, the agent converts it to a vector and
    searches for the nearest scam typology vectors — matching the
    email's meaning rather than its exact wording. A scam email that
    says "please update our banking details" will match the BEC
    typology even though neither the email nor the typology uses
    exactly the same words.

Embedding input construction:
    Rather than embedding just the description field, this script
    combines multiple fields (typology_name, description, red_flags,
    target_victim, payment_type) into a single rich text string.
    More context in the embedding input produces more accurate
    semantic search results.

Resume support:
    If the script is interrupted mid-run, it saves a checkpoint
    after every batch. Re-running the script will skip records
    that already have embeddings and continue from where it stopped.

Input:
    data/processed/scam_typologies_augmented.json  (306 records)

Output:
    data/processed/scam_typologies_with_embeddings.json  (306 records,
    each with an additional description_vector field of 768 floats)

Usage:
    python data_pipeline/step6_generate_embeddings.py
"""

import os
import sys
import json
import time
from pathlib import Path
from dotenv import load_dotenv
from colorama import Fore, Style, init
from tqdm import tqdm
import vertexai
from vertexai.language_models import TextEmbeddingModel

init(autoreset=True)
load_dotenv()

PROCESSED_DIR   = Path(os.getenv("PROCESSED_DATA_DIR", "data/processed"))
GCP_PROJECT     = os.getenv("GCP_PROJECT_ID")
GCP_REGION      = os.getenv("GCP_REGION", "us-central1")
EMBEDDING_MODEL = os.getenv("VERTEX_EMBEDDING_MODEL", "text-embedding-004")
EMBEDDING_DIM   = int(os.getenv("VERTEX_EMBEDDING_DIMENSION", "768"))

INPUT_FILE      = PROCESSED_DIR / "scam_typologies_augmented.json"
OUTPUT_FILE     = PROCESSED_DIR / "scam_typologies_with_embeddings.json"

# Vertex AI allows up to 250 texts per batch
BATCH_SIZE = 50


# ── Vertex AI setup ──────────────────────────────────────────────────────────

def init_vertex():
    if not GCP_PROJECT:
        print(Fore.RED + "ERROR: GCP_PROJECT_ID not set in .env")
        sys.exit(1)

    vertexai.init(project=GCP_PROJECT, location=GCP_REGION)
    model = TextEmbeddingModel.from_pretrained(EMBEDDING_MODEL)
    print(f"  Loaded model: {EMBEDDING_MODEL}")
    return model


# ── Embedding generation ─────────────────────────────────────────────────────

def generate_embeddings_batch(model, texts: list[str]) -> list[list[float]]:
    """
    Generate vector embeddings for a batch of text strings.

    Sends up to BATCH_SIZE texts in a single Vertex AI API call for
    efficiency. If the batch call fails, falls back to processing
    each text individually to maximize the number of successful
    embeddings. Returns a zero vector for any text that cannot be
    embedded, so the pipeline completes rather than failing.

    Args:
        model: Vertex AI TextEmbeddingModel instance
        texts (list[str]): batch of text strings to embed

    Returns:
        list[list[float]]: one 768-dimensional vector per input text
    """
    try:
        embeddings = model.get_embeddings(texts)
        return [e.values for e in embeddings]
    except Exception as e:
        print(Fore.YELLOW + f"\n    Embedding batch failed: {e}")
        time.sleep(5)

        # Retry one at a time
        results = []
        for text in texts:
            try:
                emb = model.get_embeddings([text])
                results.append(emb[0].values)
            except Exception as e2:
                print(Fore.RED + f"    Single embedding failed: {e2}")
                results.append([0.0] * EMBEDDING_DIM)  # zero vector fallback
            time.sleep(1)
        return results


def build_embedding_text(record: dict) -> str:
    """
    Construct a rich text string from a typology record for embedding.

    Combines multiple record fields into a single structured string
    to give the embedding model maximum semantic context. Using only
    the description field produces embeddings that miss important
    signals like payment type and target victim, which help distinguish
    similar fraud patterns from each other.

    Args:
        record (dict): a scam typology record

    Returns:
        str: combined text string ready for embedding generation
    """
    parts = [
        f"Fraud type: {record.get('typology_name', '')}",
        f"Description: {record.get('description', '')}",
        f"Red flags: {', '.join(record.get('red_flags', []))}",
        f"Target: {record.get('target_victim', '')}",
        f"Payment method: {record.get('typical_payment_type', '')}",
    ]
    return ' | '.join(p for p in parts if p.split(': ', 1)[1])


# ── Main ─────────────────────────────────────────────────────────────────────

def run():
    print(Fore.CYAN + "\n SentryPay: Step 6 — Generate Embeddings\n")

    # Load typologies
    if not INPUT_FILE.exists():
        print(Fore.RED + f"ERROR: {INPUT_FILE} not found.")
        print(Fore.YELLOW + "Run step3_augment_typologies.py first.")
        sys.exit(1)

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        typologies = json.load(f)

    print(f"  Typologies to embed: {Fore.GREEN}{len(typologies):,}")
    print(f"  Batch size: {BATCH_SIZE}")
    print(f"  Model: {EMBEDDING_MODEL}")
    print(f"  Dimensions: {EMBEDDING_DIM}")

    # Check if output already exists (resume support)
    already_embedded = set()
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            existing = json.load(f)
        already_embedded = {r['typology_id'] for r in existing if r.get('description_vector')}
        print(f"\n  Resuming — already embedded: {len(already_embedded)}")

    model            = init_vertex()
    to_process       = [t for t in typologies if t['typology_id'] not in already_embedded]
    embedded_records = [t for t in typologies if t['typology_id'] in already_embedded]

    if not to_process:
        print(Fore.GREEN + "\n  All typologies already have embeddings. Nothing to do.")
    else:
        print(f"\n  To process: {len(to_process)}")

        # Process in batches
        for i in tqdm(range(0, len(to_process), BATCH_SIZE),
                      desc="  Embedding batches",
                      unit="batch"):
            batch   = to_process[i:i + BATCH_SIZE]
            texts   = [build_embedding_text(r) for r in batch]
            vectors = generate_embeddings_batch(model, texts)

            for record, vector in zip(batch, vectors):
                record['description_vector'] = vector
                embedded_records.append(record)

            # Save checkpoint after every batch (so we can resume if interrupted)
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(embedded_records, f, ensure_ascii=False)

            time.sleep(0.5)  # polite to the API

    # Validation
    total          = len(embedded_records)
    with_vectors   = sum(1 for r in embedded_records if r.get('description_vector'))
    without_vectors = total - with_vectors

    print(Fore.CYAN + "\n Validation \n")
    print(f"  Total records:       {total:,}")
    print(f"  With embeddings:     {Fore.GREEN}{with_vectors:,}")
    print(f"  Without embeddings:  {Fore.RED if without_vectors else Fore.GREEN}{without_vectors:,}")

    if with_vectors > 0:
        sample_vector = embedded_records[0]['description_vector']
        print(f"  Vector dimensions:   {len(sample_vector)} (expected {EMBEDDING_DIM})")
        print(f"  Sample vector range: [{min(sample_vector):.4f}, {max(sample_vector):.4f}]")

    print(f"\n  Saved: {Fore.GREEN}{OUTPUT_FILE}")

    print(Fore.CYAN + "\n Step 6 Complete. \n")


if __name__ == "__main__":
    run()