"""
SentryPay — Step 2: Scam Typology Extraction
==============================================
Uses Gemini to read the cleaned FBI IC3 report text and extract
structured fraud pattern records. This is the step that transforms
unstructured human-readable text into machine-readable JSON records
that Elasticsearch can index and the agent can search.

Why chunking is necessary:
    The cleaned PDF text is tens of thousands of characters long —
    too large to send to Gemini in a single API call. This script
    splits the text into overlapping chunks of 3,000 characters
    (with 300-character overlap to prevent fraud descriptions from
    being cut mid-sentence at chunk boundaries), processes each chunk
    independently, then deduplicates the results.

What Gemini extracts from each chunk:
    - typology_name       — short name for the fraud type
    - description         — 2-sentence explanation of how it works
    - red_flags           — 3 specific warning signs
    - target_victim       — who gets targeted
    - typical_payment_type — Wire / ACH / Zelle / Crypto / etc.
    - avg_loss_usd        — average financial loss

Input:
    data/processed/ic3_2023_clean.txt
    data/processed/ic3_2024_clean.txt

Output:
    data/processed/scam_typologies_raw.json  (~50 unique records)

Usage:
    python data_pipeline/step2_parse_typologies.py
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
from google import genai
from google.genai import types

init(autoreset=True)
load_dotenv()

PROCESSED_DIR = Path(os.getenv("PROCESSED_DATA_DIR", "data/processed"))
GCP_PROJECT   = os.getenv("GCP_PROJECT_ID")
GCP_REGION    = os.getenv("GCP_REGION", "us-central1")
OUTPUT_FILE   = PROCESSED_DIR / "scam_typologies_raw.json"

# Smaller chunks so Gemini can complete each response without hitting token limit
CHUNK_SIZE    = 3000
CHUNK_OVERLAP = 300


# ── Gemini client ─────────────────────────────────────────────────────────────

def init_gemini():
    if not GCP_PROJECT:
        print(Fore.RED + "ERROR: GCP_PROJECT_ID not set in .env")
        sys.exit(1)
    client = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_REGION)
    print(Fore.GREEN + f"  Gemini client ready (project: {GCP_PROJECT})")
    return client


# ── Chunking ──────────────────────────────────────────────────────────────────

def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """
    Split a long text into overlapping fixed-size chunks.

    Overlapping ensures that fraud descriptions spanning a chunk
    boundary appear fully in at least one chunk, preventing
    incomplete records from being extracted.

    Args:
        text (str): full document text to split
        size (int): maximum characters per chunk
        overlap (int): characters shared between consecutive chunks

    Returns:
        list[str]: list of text chunks covering the entire document
    """
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks


# ── Extraction ────────────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """
You are a financial fraud analyst. Extract all distinct fraud and scam types from the text below.

For each fraud type, return a JSON object with EXACTLY these fields:
- typology_name: short clear name e.g. "Business Email Compromise"
- description: 2 sentences max explaining HOW the scam works
- red_flags: list of exactly 3 warning signs (short phrases only)
- target_victim: who gets targeted (10 words max)
- typical_payment_type: one of "Wire", "ACH", "Zelle", "Crypto", "Gift Cards", "Multiple"
- avg_loss_usd: number only, 0 if unknown

IMPORTANT:
- Keep ALL text values SHORT — under 100 characters each
- Return ONLY a valid JSON array, nothing else
- No markdown, no code fences, no explanation
- If no fraud types found, return []

TEXT:
{text}
"""

def extract_from_chunk(client, chunk, source):
     """
    Send one text chunk to Gemini and extract structured fraud records.

    Prompts Gemini to identify all distinct fraud types in the chunk
    and return them as a JSON array. Handles cases where Gemini adds
    markdown formatting around the JSON by stripping code fences before
    parsing. Returns an empty list on JSON parse errors so the pipeline
    continues with the remaining chunks rather than failing entirely.

    Args:
        client: authenticated Gemini client
        chunk (str): one chunk of cleaned PDF text
        source (str): source filename, used to populate the source field

    Returns:
        list[dict]: extracted typology records, or [] on failure
    """
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=EXTRACTION_PROMPT.format(text=chunk),
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=8192
            )
        )
        raw = response.text.strip()

        # Strip any markdown fences Gemini adds
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'^```\s*',     '', raw)
        raw = re.sub(r'\s*```$',     '', raw)
        raw = raw.strip()

        if not raw or raw == '[]':
            return []

        parsed = json.loads(raw)

        # Add metadata
        year_match = re.search(r'20\d{2}', source)
        for record in parsed:
            record['source']       = source
            record['typology_id']  = f"T-{uuid.uuid4().hex[:8].upper()}"
            record['is_augmented'] = False
            record['year']         = int(year_match.group()) if year_match else 2024

        return parsed

    except json.JSONDecodeError as e:
        print(Fore.YELLOW + f"\n    JSON error (skipping chunk): {e}")
        return []
    except Exception as e:
        print(Fore.YELLOW + f"\n    Gemini error: {e}")
        time.sleep(5)
        return []


# ── Deduplication ─────────────────────────────────────────────────────────────

def deduplicate(typologies):
    """
    Remove duplicate typology records by name.

    Both the 2023 and 2024 IC3 reports cover the same fraud types
    (BEC, Investment Fraud, Ransomware, etc.). After processing both
    files, duplicates are removed by keeping only the first occurrence
    of each unique typology_name (case-insensitive).

    Args:
        typologies (list[dict]): combined records from all files

    Returns:
        list[dict]: deduplicated records
    """
    seen, unique = set(), []
    for t in typologies:
        key = t.get('typology_name', '').lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(t)
    return unique


# ── Main ─────────────────────────────────────────────────────────────────────

def run():
    print(Fore.CYAN + "\n SentryPay: Step 2 — Parse Typologies \n")

    input_files = list(PROCESSED_DIR.glob("*_clean.txt"))
    if not input_files:
        print(Fore.RED + "ERROR: No cleaned text files found. Run step1 first.")
        sys.exit(1)

    client         = init_gemini()
    all_typologies = []

    for txt_file in sorted(input_files):
        source_name = txt_file.stem
        print(f"\n  Processing: {Fore.CYAN}{txt_file.name}{Style.RESET_ALL}")

        with open(txt_file, 'r', encoding='utf-8') as f:
            text = f.read()

        chunks = chunk_text(text)
        print(f"    Chunks to process: {len(chunks)}")

        file_types = []
        for i, chunk in enumerate(chunks):
            print(f"    Chunk {i+1}/{len(chunks)}...", end='\r')
            extracted = extract_from_chunk(client, chunk, source_name)
            if extracted:
                file_types.extend(extracted)
                print(f"    Chunk {i+1}/{len(chunks)} → {Fore.GREEN}{len(extracted)} found")
            time.sleep(1)

        print(f"\n    Total from this file: {Fore.GREEN}{len(file_types)}")
        all_typologies.extend(file_types)

    unique = deduplicate(all_typologies)

    print(Fore.CYAN + f"\n Summary \n")
    print(f"  Raw extracted:     {len(all_typologies)}")
    print(f"  After dedup:       {Fore.GREEN}{len(unique)} unique typologies")

    if not unique:
        print(Fore.RED + "\n  No typologies extracted. Check your PDF content.")
        sys.exit(1)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(unique, f, indent=2, ensure_ascii=False)

    print(f"\n  Saved: {Fore.GREEN}{OUTPUT_FILE}")

    # Show sample
    print(Fore.CYAN + "\n Sample record \n")
    for k, v in unique[0].items():
        print(f"  {k}: {v}")

    print(Fore.CYAN + f"\n Step 2 Complete. {len(unique)} typologies ready. \n")


if __name__ == "__main__":
    run()