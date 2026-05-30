"""
SentryPay — Phase 1 Master Runner
====================================
Executes all Phase 1 data pipeline steps in sequence using a single
command. Provides a convenient alternative to running each step
individually when setting up the project from scratch.

Steps executed in order:
    0. create_elastic_indices.py  — creates the four Elastic index schemas
    1. step1_extract_pdfs.py      — extracts text from FBI IC3 PDF reports
    2. step2_parse_typologies.py  — uses Gemini to extract fraud patterns
    3. step3_augment_typologies.py — generates variations to fix class imbalance
    4. step4_process_opensanctions.py — processes sanctions data and risk scores
    5. step5_generate_synthetic_transactions.py — generates demo user data
    6. step6_generate_embeddings.py — generates vector embeddings via Vertex AI
    7. step7_load_to_elastic.py   — bulk loads all data into Elasticsearch
    8. step8_validate.py          — runs the go/no-go gate validation

Early exit behaviour:
    If any step exits with a non-zero return code, the runner stops
    immediately and prints the name of the failed step. Individual
    steps can be re-run in isolation to fix the issue before
    resuming the pipeline.

Recommended approach:
    Run steps individually the first time to monitor each step's output.
    Use this master runner for re-runs after environment setup is verified.

Usage:
    python run_phase1.py
"""

import subprocess
import sys
from colorama import Fore, Style, init

init(autoreset=True)

STEPS = [
    ("setup/create_elastic_indices.py",                   "Create Elastic indices"),
    ("data_pipeline/step1_extract_pdfs.py",               "Extract PDF text"),
    ("data_pipeline/step2_parse_typologies.py",           "Parse scam typologies"),
    ("data_pipeline/step3_augment_typologies.py",         "Augment typologies"),
    ("data_pipeline/step4_process_opensanctions.py",      "Process OpenSanctions + OFAC"),
    ("data_pipeline/step5_generate_synthetic_transactions.py", "Generate synthetic transactions"),
    ("data_pipeline/step6_generate_embeddings.py",        "Generate embeddings"),
    ("data_pipeline/step7_load_to_elastic.py",            "Load to Elastic"),
    ("data_pipeline/step8_validate.py",                   "Validate — Phase 1 Gate"),
]


def run():
    print(Fore.CYAN + """SentryPay — Phase 1 Master Runner""")

    print(f"  Running {len(STEPS)} steps:\n")
    for i, (script, label) in enumerate(STEPS, 1):
        print(f"    {i}. {label}")
    print()

    for i, (script, label) in enumerate(STEPS, 1):
        print(f"  Step {i}/{len(STEPS)}: {label}")

        result = subprocess.run(
            [sys.executable, script],
            capture_output=False  # Stream output directly
        )

        if result.returncode != 0:
            print(Fore.RED + f"\n  Step {i} failed (exit code {result.returncode})")
            print(Fore.YELLOW + "  Fix the error above before continuing.")
            print(Fore.YELLOW + f"  You can re-run just this step: python {script}")
            sys.exit(result.returncode)
        else:
            print(Fore.GREEN + f"\n Step {i} complete")

    print(Fore.GREEN + """Phase 1 Complete! All indices populated and validated.""")


if __name__ == "__main__":
    run()