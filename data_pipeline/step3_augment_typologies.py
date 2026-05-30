"""
SentryPay — Step 3: Typology Augmentation
==========================================
Addresses class imbalance in the scam typology index by using Gemini
to generate multiple paraphrased variations of each real fraud pattern.

Why augmentation is necessary:
    Step 2 extracts ~50 real fraud descriptions. When the agent performs
    a vector similarity search against an incoming payment email, having
    only 50 records means it may miss scam emails that use phrasing
    different from the original FBI report language. Generating 5
    variations per typology (same fraud mechanism, different wording,
    tone, and specific details) dramatically improves recall across
    diverse real-world scam email styles.

What stays the same across variations:
    - The core fraud mechanism (how the scam works)
    - The typology_name and metadata fields

What changes across variations:
    - Sentence structure and vocabulary
    - Specific details (company names, amounts, urgency level)
    - Tone (formal, casual, urgent, friendly)

Result:
    51 real records × 5 variations = 255 augmented records
    51 + 255 = 306 total records in the scam typologies index

Input:
    data/processed/scam_typologies_raw.json

Output:
    data/processed/scam_typologies_augmented.json  (306 records)

Usage:
    python data_pipeline/step3_augment_typologies.py
"""

import os
import re
import sys
import json
import time
import uuid
from pathlib import Path
from dotenv import load_dotenv
from colorama import Fore, Style, init
from tqdm import tqdm
from google import genai
from google.genai import types

init(autoreset=True)
load_dotenv()

PROCESSED_DIR = Path(os.getenv("PROCESSED_DATA_DIR", "data/processed"))
GCP_PROJECT   = os.getenv("GCP_PROJECT_ID")
GCP_REGION    = os.getenv("GCP_REGION", "us-central1")
INPUT_FILE    = PROCESSED_DIR / "scam_typologies_raw.json"
OUTPUT_FILE   = PROCESSED_DIR / "scam_typologies_augmented.json"
N_VARIATIONS  = 5


def init_gemini():
    if not GCP_PROJECT:
        print(Fore.RED + "ERROR: GCP_PROJECT_ID not set in .env")
        sys.exit(1)
    client = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_REGION)
    print(Fore.GREEN + f"  Gemini client ready (project: {GCP_PROJECT})")
    return client


AUGMENTATION_PROMPT = """
You are a financial fraud analyst writing training data for a scam detection system.

Here is a real scam description:
Name: {name}
Description: {description}
Red flags: {red_flags}

Generate exactly {n} paraphrased variations of this description.
Each variation must:
- Keep the CORE MECHANISM identical (same type of fraud)
- Use different language, tone, and sentence structure
- Vary specific details (company names, amounts, urgency level)
- Sound like it came from a different real case
- Be 2-4 sentences long

Return ONLY a JSON array of {n} strings. No explanation, no markdown, no preamble.
"""


def augment_typology(client, record, n=N_VARIATIONS):
    """
    Generate n paraphrased variations of a single typology description.

    Prompts Gemini to write n alternative descriptions of the same
    fraud pattern. Each variation preserves the core mechanism but
    uses different language to improve the vector index's coverage
    of real-world scam email phrasing.

    Failed generations (API errors or JSON parse failures) return an
    empty list so the pipeline skips that record and continues rather
    than stopping entirely.

    Args:
        client: authenticated Gemini client
        record (dict): original typology record to augment
        n (int): number of variations to generate

    Returns:
        list[dict]: n augmented records with the same metadata as the
                    original but unique typology_id and description fields
    """
    prompt = AUGMENTATION_PROMPT.format(
        name        = record.get('typology_name', ''),
        description = record.get('description', ''),
        red_flags   = ', '.join(record.get('red_flags', [])),
        n           = n
    )
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=2048
            )
        )
        raw = response.text.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'^```\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        variations = json.loads(raw.strip())
        augmented  = []
        for i, desc in enumerate(variations[:n]):
            augmented.append({
                **record,
                "typology_id":     f"T-{uuid.uuid4().hex[:8].upper()}",
                "description":     desc,
                "is_augmented":    True,
                "source_original": record['typology_id'],
                "aug_index":       i
            })
        return augmented

    except Exception as e:
        print(Fore.YELLOW + f"\n    Augmentation failed: {e}")
        time.sleep(5)
        return []


def run():
    print(Fore.CYAN + "\n SentryPay: Step 3 — Augment Typologies \n")

    if not INPUT_FILE.exists():
        print(Fore.RED + f"ERROR: {INPUT_FILE} not found. Run step2 first.")
        sys.exit(1)

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        originals = json.load(f)

    print(f"  Original typologies: {Fore.GREEN}{len(originals)}")
    print(f"  Variations each:     {N_VARIATIONS}")
    print(f"  Expected total:      ~{len(originals) * (N_VARIATIONS + 1)}\n")

    client       = init_gemini()
    all_records  = list(originals)
    failed       = 0

    for record in tqdm(originals, desc="  Augmenting", unit="typology"):
        augmented = augment_typology(client, record)
        if augmented:
            all_records.extend(augmented)
        else:
            failed += 1
        time.sleep(1.5)

    print(f"\n  Original:  {len(originals)}")
    print(f"  Augmented: {Fore.GREEN}{len(all_records) - len(originals)}")
    print(f"  Failed:    {Fore.RED if failed else Fore.GREEN}{failed}")
    print(f"  Total:     {Fore.GREEN}{len(all_records)}")

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_records, f, indent=2, ensure_ascii=False)

    print(f"\n  Saved: {Fore.GREEN}{OUTPUT_FILE}")
    print(Fore.CYAN + f"\n Step 3 Complete. \n")


if __name__ == "__main__":
    run()