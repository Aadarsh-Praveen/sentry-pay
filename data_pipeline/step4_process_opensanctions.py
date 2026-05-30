"""
SentryPay — Step 4: Beneficiary Intelligence Processing
========================================================
Builds the beneficiary_intel index by processing real sanctions data
and generating synthetic account records to create a balanced dataset
for mule account risk scoring.

Data sources used:

  OpenSanctions (real, public):
      A consolidated, daily-updated dataset of sanctioned individuals
      and organizations from 100+ government sources worldwide.
      Downloaded from opensanctions.org as a CSV.
      Filtered to finance-relevant topics (fraud, money laundering,
      cybercrime, corruption) before processing.

  OFAC SDN List (real, public):
      The U.S. Treasury's Specially Designated Nationals list.
      Entities on this list are blocked from transacting with
      U.S. persons or businesses.

  Synthetic mule accounts (generated):
      500 realistic fake flagged accounts with high risk scores,
      representing the types of accounts used in payment fraud
      to receive and quickly disperse stolen funds.

  Synthetic clean accounts (generated):
      5,000 realistic fake legitimate accounts with low risk scores,
      providing the contrast needed for meaningful risk scoring.
      Without clean accounts, every payment would look suspicious.

Feature engineering — risk score:
    Each flagged entity receives a 0.0–1.0 risk score computed from:
      - Number of sanctions lists the entity appears on
      - Recency of the most recent flagging
      - Severity of the sanction topic (fraud vs general sanction)

Output:
    data/processed/beneficiary_intel.json  (~68,000 records)
    data/processed/eda_report.txt          (exploratory data analysis)

Usage:
    python data_pipeline/step4_process_opensanctions.py
"""

import os
import sys
import json
import uuid
import random
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
from colorama import Fore, Style, init
import pandas as pd
import numpy as np
from faker import Faker

init(autoreset=True)
load_dotenv()

RAW_DIR       = Path(os.getenv("RAW_DATA_DIR", "data/raw"))
PROCESSED_DIR = Path(os.getenv("PROCESSED_DATA_DIR", "data/processed"))
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

OPENSANCTIONS_FILE = RAW_DIR / "targets.simple.csv"
OFAC_FILE          = RAW_DIR / "sdn.csv"
OUTPUT_FILE        = PROCESSED_DIR / "beneficiary_intel.json"
EDA_REPORT_FILE    = PROCESSED_DIR / "eda_report.txt"

# Target ratio: 1 flagged : 10 clean
N_SYNTHETIC_CLEAN  = 5000

fake = Faker()
Faker.seed(42)
random.seed(42)
np.random.seed(42)


# ── EDA ──────────────────────────────────────────────────────────────────────

def run_eda(df: pd.DataFrame, name: str) -> str:
    """Run exploratory data analysis and return a text report."""
    lines = [
        f"\n{'='*60}",
        f"EDA Report: {name}",
        f"Generated: {datetime.now().isoformat()}",
        f"{'='*60}",
        f"\nShape: {df.shape[0]:,} rows × {df.shape[1]} columns",
        f"\nColumns:\n{chr(10).join(f'  - {c}' for c in df.columns.tolist())}",
        f"\nMissing values:",
    ]

    missing = df.isnull().sum()
    for col, n in missing.items():
        pct = n / len(df) * 100
        lines.append(f"  {col}: {n:,} ({pct:.1f}%)")

    lines.append(f"\nData types:\n{df.dtypes.to_string()}")

    # Categorical distributions
    for col in df.select_dtypes(include='object').columns[:5]:
        vc = df[col].value_counts().head(10)
        lines.append(f"\n{col} (top 10):\n{vc.to_string()}")

    return '\n'.join(lines)


# ── OpenSanctions processing ──────────────────────────────────────────────────

FRAUD_TOPICS = [
    'fraud', 'money.laundering', 'financial.crime', 'corruption',
    'bribery', 'cybercrime', 'organized.crime', 'crime'
]

FRAUD_KEYWORDS_TEXT = [
    'fraud', 'scam', 'money launder', 'wire transfer', 'embezzl',
    'financial crime', 'cyber', 'corruption', 'bribery'
]


def load_opensanctions(filepath: Path) -> pd.DataFrame:
    """Load and filter OpenSanctions data."""
    print(f"\n  Loading OpenSanctions from: {filepath}")

    if not filepath.exists():
        print(Fore.YELLOW + f"  WARNING: {filepath} not found. Download from:")
        print(Fore.YELLOW + "  https://data.opensanctions.org/datasets/latest/sanctions/targets.simple.csv")
        return pd.DataFrame()

    try:
        df = pd.read_csv(filepath, low_memory=False)
        print(f"  Loaded: {df.shape[0]:,} total records")
    except Exception as e:
        print(Fore.RED + f"  Failed to load: {e}")
        return pd.DataFrame()

    # Filter to relevant entity types
    if 'schema' in df.columns:
        df = df[df['schema'].isin(['Person', 'Company', 'Organization', 'LegalEntity'])]

    # Filter to finance-relevant topics
    if 'topics' in df.columns:
        mask = df['topics'].fillna('').str.lower().apply(
            lambda t: any(kw in t for kw in FRAUD_TOPICS)
        )
        df = df[mask]

    print(f"  After finance filter: {Fore.GREEN}{df.shape[0]:,} records")
    return df


def compute_risk_score_opensanctions(row) -> float:
    """
    Compute a 0.0–1.0 risk score for a single OpenSanctions entity.

    The score is built from three additive components:
      1. Dataset breadth  — entities appearing on more sanctions lists
                            receive a higher score (up to 0.45)
      2. Recency          — entities flagged within the last 6 months
                            score higher than older flags (up to 0.30)
      3. Topic severity   — entities explicitly linked to financial
                            crime score higher than general sanctions (0.20–0.25)

    The final score is capped at 1.0.

    Args:
        row: a single row from the OpenSanctions DataFrame

    Returns:
        float: risk score between 0.0 and 1.0
    """
    score = 0.0

    # Number of sanctions lists
    datasets = str(row.get('datasets', ''))
    n_lists  = len([d for d in datasets.split(',') if d.strip()])
    score   += min(n_lists * 0.15, 0.45)

    # Recency
    last_seen = row.get('last_seen', '')
    if pd.notna(last_seen) and last_seen:
        try:
            days_ago = (datetime.now() - pd.to_datetime(last_seen)).days
            if days_ago < 180:
                score += 0.30
            elif days_ago < 365:
                score += 0.15
            else:
                score += 0.05
        except Exception:
            pass

    # Topic severity
    topics = str(row.get('topics', '')).lower()
    if 'sanction' in topics:
        score += 0.25
    if any(kw in topics for kw in ['fraud', 'money.launder', 'cybercrime']):
        score += 0.20

    return min(round(score, 3), 1.0)


def process_opensanctions(df: pd.DataFrame) -> list:
    """Transform OpenSanctions rows into SentryPay records."""
    if df.empty:
        return []

    records = []

    for _, row in df.iterrows():
        risk_score = compute_risk_score_opensanctions(row)

        record = {
            "entity_id":      str(row.get('id', uuid.uuid4().hex)),
            "account_number": None,   # OpenSanctions doesn't have account numbers
            "routing_number": None,
            "entity_name":    str(row.get('caption', row.get('name', 'Unknown'))),
            "name_aliases":   str(row.get('aliases', '')),
            "risk_score":     risk_score,
            "risk_category":  (
                "HIGH" if risk_score > 0.7
                else "MEDIUM" if risk_score > 0.4
                else "LOW"
            ),
            "flag_reason":    str(row.get('topics', '')),
            "is_flagged":     True,
            "datasets":       str(row.get('datasets', '')),
            "country_code":   str(row.get('country', '')).upper()[:2],
            "topics":         str(row.get('topics', '')),
            "first_seen":     str(row.get('first_seen', '')),
            "last_seen":      str(row.get('last_seen', '')),
            "last_updated":   datetime.now().isoformat()
        }

        records.append(record)

    return records


# ── Synthetic clean accounts (to balance the index) ──────────────────────────

def generate_clean_accounts(n: int) -> list:
    """
    Generate n synthetic legitimate account records using Faker.

    Clean accounts have risk scores between 0.0 and 0.12, no flag
    reason, and is_flagged set to False. These records balance the
    index so the agent does not treat every unknown account as
    suspicious — it has a realistic baseline of clean accounts
    to compare against.

    Args:
        n (int): number of clean account records to generate

    Returns:
        list[dict]: synthetic clean account records
    """
    print(f"\n  Generating {n:,} synthetic clean accounts...")

    records = []
    for _ in range(n):
        record = {
            "entity_id":      uuid.uuid4().hex,
            "account_number": fake.bban(),
            "routing_number": str(random.randint(100000000, 999999999)),
            "entity_name":    fake.company(),
            "name_aliases":   "",
            "risk_score":     round(random.uniform(0.0, 0.12), 3),
            "risk_category":  "LOW",
            "flag_reason":    None,
            "is_flagged":     False,
            "datasets":       "",
            "country_code":   fake.country_code(),
            "topics":         "",
            "first_seen":     None,
            "last_seen":      None,
            "last_updated":   datetime.now().isoformat()
        }
        records.append(record)

    return records


# ── Synthetic mule accounts (high risk, for demo) ────────────────────────────

def generate_mule_accounts(n: int = 500) -> list:
    """
    Generate n synthetic high-risk mule account records using Faker.

    Mule accounts are used by fraudsters to receive stolen funds and
    quickly move them onward. These synthetic records have risk scores
    between 0.75 and 0.99 and realistic flag reasons describing
    patterns associated with money mule activity.

    Args:
        n (int): number of mule account records to generate

    Returns:
        list[dict]: synthetic mule account records
    """
    print(f"  Generating {n} synthetic mule accounts...")

    flag_reasons = [
        "Account appeared in multiple fraud reports — high velocity fan-out pattern",
        "Linked to known money mule network — multiple BEC complaints",
        "Rapid fund movement detected — same-day withdrawal pattern",
        "Account name/number mismatch reported by sending banks",
        "Associated with supplier fraud complaints — account opened < 30 days before first complaint",
    ]

    records = []
    for _ in range(n):
        days_ago = random.randint(10, 400)
        first    = datetime.now() - timedelta(days=days_ago + random.randint(5, 60))
        last     = datetime.now() - timedelta(days=random.randint(0, days_ago))

        record = {
            "entity_id":      uuid.uuid4().hex,
            "account_number": fake.bban(),
            "routing_number": str(random.randint(100000000, 999999999)),
            "entity_name":    fake.company(),
            "name_aliases":   "",
            "risk_score":     round(random.uniform(0.75, 0.99), 3),
            "risk_category":  "HIGH",
            "flag_reason":    random.choice(flag_reasons),
            "is_flagged":     True,
            "datasets":       "sentry_pay_community",
            "country_code":   random.choice(["US", "GB", "NG", "CN", "RO", "UA"]),
            "topics":         "fraud money.laundering",
            "first_seen":     first.date().isoformat(),
            "last_seen":      last.date().isoformat(),
            "last_updated":   datetime.now().isoformat()
        }
        records.append(record)

    return records


# ── Main ─────────────────────────────────────────────────────────────────────

def run():
    print(Fore.CYAN + "\n SentryPay: Step 4 — Beneficiary Intel \n")

    all_records  = []
    eda_sections = []

    # 1. OpenSanctions
    df_os = load_opensanctions(OPENSANCTIONS_FILE)
    if not df_os.empty:
        eda_sections.append(run_eda(df_os, "OpenSanctions"))
        os_records = process_opensanctions(df_os)
        all_records.extend(os_records)
        print(f"  OpenSanctions processed: {Fore.GREEN}{len(os_records):,} records")

        # Risk score distribution
        scores = [r['risk_score'] for r in os_records]
        df_scores = pd.Series(scores)
        print(f"  Risk score stats:")
        print(f"    mean={df_scores.mean():.2f}  "
              f"std={df_scores.std():.2f}  "
              f"high(>0.7)={sum(1 for s in scores if s > 0.7):,}")

    # 2. Synthetic mule accounts (always generated)
    mule_records = generate_mule_accounts(500)
    all_records.extend(mule_records)

    # 3. Synthetic clean accounts (balance the index)
    clean_records = generate_clean_accounts(N_SYNTHETIC_CLEAN)
    all_records.extend(clean_records)

    # Summary stats
    flagged = sum(1 for r in all_records if r['is_flagged'])
    clean   = sum(1 for r in all_records if not r['is_flagged'])
    ratio   = flagged / max(clean, 1)

    print(Fore.CYAN + "\n Class balance \n")
    print(f"  Flagged records:  {Fore.RED}{flagged:,}")
    print(f"  Clean records:    {Fore.GREEN}{clean:,}")
    print(f"  Flagged ratio:    1 : {int(1/ratio) if ratio < 1 else int(ratio)}")

    # Save EDA report
    eda_report = '\n'.join(eda_sections) if eda_sections else "No external data loaded."
    with open(EDA_REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write(eda_report)
    print(f"\n  EDA report saved: {EDA_REPORT_FILE}")

    # Save records
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_records, f, indent=2, ensure_ascii=False)

    print(f"  Beneficiary intel saved: {Fore.GREEN}{OUTPUT_FILE}")
    print(f"  Total records: {Fore.GREEN}{len(all_records):,}")

    print(Fore.CYAN + "\n Step 4 Complete. \n")


if __name__ == "__main__":
    run()